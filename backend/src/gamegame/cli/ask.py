"""Chat/ask CLI command."""

import asyncio
import json
import time
from typing import Annotated

import httpx
import typer
from rich.console import Console
from rich.panel import Panel

console = Console()


def create_ask_command() -> typer.Typer:
    """Create the ask command as a Typer app."""
    app = typer.Typer()

    @app.callback(invoke_without_command=True)
    def ask(
        game: str = typer.Argument(..., help="Game ID or slug"),
        prompt: Annotated[str | None, typer.Argument(help="Question to ask (omit for interactive mode)")] = None,
        url: str = typer.Option("http://localhost:8000", "--url", "-u", help="API server URL"),
        verbose: bool = typer.Option(False, "--verbose", "-v", help="Show tool calls and details"),
    ):
        """Chat with a game's AI assistant.

        Examples:
            gamegame ask catan "How do I set up the game?"
            gamegame ask catan  # Interactive mode
        """
        client = ChatClient(base_url=url, game_id=game, verbose=verbose)

        if prompt:
            # Single message mode
            asyncio.run(client.send_message(prompt))
        else:
            # Interactive mode
            asyncio.run(client.run_interactive())

    return app


class ChatClient:
    """CLI chat client for the game API."""

    def __init__(self, base_url: str, game_id: str, verbose: bool = False):
        self.base_url = base_url.rstrip("/")
        self.game_id = game_id
        self.verbose = verbose
        self.messages: list[dict[str, str]] = []
        self.client = httpx.AsyncClient(timeout=120.0)

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    async def send_message(self, content: str) -> str:
        """Send a message and stream the response."""
        self.messages.append({"role": "user", "content": content})

        url = f"{self.base_url}/api/games/{self.game_id}/chat"
        payload = {"messages": self.messages, "stream": True}

        full_response = ""
        current_text = ""
        citations: dict[str, dict] = {}
        usage = {}
        tool_timings: list[dict] = []
        current_tool_start: float | None = None
        current_tool_name: str = ""

        try:
            request_start = time.perf_counter()

            async with self.client.stream(
                "POST", url, json=payload, headers={"Accept": "text/event-stream"}
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    console.print(f"[red]Error {response.status_code}:[/red] {error_text.decode()}")
                    self.messages.pop()
                    return ""

                console.print()
                console.print("[bold blue]Assistant:[/bold blue]", end=" ")

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    if line.startswith("data: "):
                        data = line[6:]

                        if data == "[DONE]":
                            break

                        try:
                            event = json.loads(data)
                            event_type = event.get("type")

                            if event_type == "text-delta":
                                text = event.get("text", "")
                                current_text += text
                                console.print(text, end="")

                            elif event_type == "tool-input-start":
                                current_tool_name = event.get("toolName", "")
                                current_tool_start = time.perf_counter()
                                if self.verbose:
                                    console.print(f"\n[dim cyan]> {current_tool_name}[/dim cyan]", end="")

                            elif event_type == "tool-input-available":
                                tool_input = event.get("input", {})
                                if self.verbose:
                                    # Show all input parameters
                                    params = " ".join(f'{k}="{v}"' for k, v in tool_input.items())
                                    console.print(f" [dim]{params}[/dim]", end="")

                            elif event_type == "tool-output-available":
                                tool_output = event.get("output")
                                tool_duration = (time.perf_counter() - current_tool_start) * 1000 if current_tool_start else 0

                                if isinstance(tool_output, list):
                                    if self.verbose:
                                        console.print(f" [dim green]→ {len(tool_output)} results ({tool_duration:.0f}ms)[/dim green]")
                                        # Show individual result scores
                                        for i, result in enumerate(tool_output[:5]):
                                            if isinstance(result, dict):
                                                score = result.get("score", 0)
                                                name = result.get("resource_name", "")[:20]
                                                page = result.get("page_number")
                                                page_str = f" p.{page}" if page else ""
                                                console.print(f"    [dim]{i+1}. {name}{page_str} (score: {score:.3f})[/dim]")
                                    for result in tool_output:
                                        if isinstance(result, dict) and "resource_name" in result:
                                            rid = result.get("resource_id", "")
                                            if rid not in citations:
                                                citations[rid] = result
                                    tool_timings.append({"name": current_tool_name, "duration_ms": tool_duration, "results": len(tool_output)})
                                elif self.verbose:
                                    console.print(f" [dim green]→ done ({tool_duration:.0f}ms)[/dim green]")
                                    tool_timings.append({"name": current_tool_name, "duration_ms": tool_duration, "results": 1})

                                current_tool_start = None

                            elif event_type == "finish":
                                usage = event.get("totalUsage", {})

                            elif event_type == "error":
                                error_msg = event.get("error", "Unknown error")
                                console.print(f"\n[red]Error:[/red] {error_msg}")

                        except json.JSONDecodeError:
                            current_text += data
                            console.print(data, end="")

                console.print()
                full_response = current_text
                total_time = (time.perf_counter() - request_start) * 1000

                # Show citations
                if citations:
                    console.print("\n[dim]Citations:[/dim]")
                    for c in citations.values():
                        resource_name = c.get("resource_name", "Unknown")
                        page = c.get("page_number")
                        page_str = f" (p.{page})" if page else ""
                        console.print(f"  [dim cyan]{resource_name}{page_str}[/dim cyan]")

                # Show verbose stats
                if self.verbose:
                    console.print()
                    prompt_tokens = usage.get("promptTokens", 0)
                    completion_tokens = usage.get("completionTokens", 0)
                    total_tokens = prompt_tokens + completion_tokens

                    # Estimate cost (gpt-5-mini pricing: $0.15/1M input, $0.60/1M output)
                    input_cost = (prompt_tokens / 1_000_000) * 0.15
                    output_cost = (completion_tokens / 1_000_000) * 0.60
                    total_cost = input_cost + output_cost

                    stats = [
                        f"Time: {total_time:.0f}ms",
                        f"Tokens: {prompt_tokens:,} in + {completion_tokens:,} out = {total_tokens:,}",
                        f"Est. cost: ${total_cost:.4f}",
                    ]
                    if tool_timings:
                        tool_time = sum(t["duration_ms"] for t in tool_timings)
                        stats.append(f"Tool calls: {len(tool_timings)} ({tool_time:.0f}ms)")

                    console.print(f"[dim]{' | '.join(stats)}[/dim]")

        except httpx.ConnectError:
            console.print(f"[red]Connection error:[/red] Could not connect to {self.base_url}")
            self.messages.pop()
            return ""
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            self.messages.pop()
            return ""
        finally:
            await self.close()

        if full_response:
            self.messages.append({"role": "assistant", "content": full_response})

        return full_response

    async def run_interactive(self):
        """Run interactive chat loop."""
        console.print(Panel.fit(
            f"[bold]Chat with {self.game_id}[/bold]\n"
            f"Server: [dim]{self.base_url}[/dim]\n\n"
            f"Commands: [dim]quit, exit, clear, history[/dim]",
            title="GameGame Chat",
        ))

        try:
            while True:
                console.print()
                user_input = console.input("[bold green]You:[/bold green] ").strip()

                if not user_input:
                    continue

                if user_input.lower() in ("quit", "exit", "q"):
                    console.print("[dim]Goodbye![/dim]")
                    break

                if user_input.lower() == "clear":
                    self.messages.clear()
                    console.print("[dim]Conversation cleared.[/dim]")
                    continue

                if user_input.lower() == "history":
                    if not self.messages:
                        console.print("[dim]No messages yet.[/dim]")
                    else:
                        for msg in self.messages:
                            role = msg["role"]
                            content = msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
                            color = "green" if role == "user" else "blue"
                            console.print(f"[{color}]{role}:[/{color}] {content}")
                    continue

                # Create new client for each message (to handle connection lifecycle)
                self.client = httpx.AsyncClient(timeout=120.0)
                await self.send_message(user_input)

        except KeyboardInterrupt:
            console.print("\n[dim]Goodbye![/dim]")
        except EOFError:
            console.print("\n[dim]Goodbye![/dim]")
        finally:
            await self.close()


# Create the app for import
app = create_ask_command()
