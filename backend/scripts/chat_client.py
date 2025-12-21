#!/usr/bin/env python3
"""CLI chat client for testing the chat endpoint.

Usage:
    python scripts/chat_client.py <game_slug>
    python scripts/chat_client.py catan --url http://localhost:8000
"""

import argparse
import asyncio
import json

import httpx
from rich.console import Console
from rich.panel import Panel

console = Console()


class ChatClient:
    """Interactive chat client for the game API."""

    def __init__(self, base_url: str, game_id: str):
        self.base_url = base_url.rstrip("/")
        self.game_id = game_id
        self.messages: list[dict[str, str]] = []
        self.client = httpx.AsyncClient(timeout=120.0)

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    async def send_message(self, content: str) -> str:
        """Send a message and stream the response.

        Returns the full response text.
        """
        self.messages.append({"role": "user", "content": content})

        url = f"{self.base_url}/api/games/{self.game_id}/chat"
        payload = {"messages": self.messages, "stream": True}

        full_response = ""
        current_text = ""
        active_tools: dict[str, dict] = {}
        citations: list[dict] = []
        usage = {}

        try:
            async with self.client.stream(
                "POST", url, json=payload, headers={"Accept": "text/event-stream"}
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    console.print(f"[red]Error {response.status_code}:[/red] {error_text.decode()}")
                    self.messages.pop()  # Remove failed message
                    return ""

                console.print()

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    if line.startswith("data: "):
                        data = line[6:]  # Remove "data: " prefix

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
                                tool_id = event.get("id")
                                tool_name = event.get("toolName")
                                active_tools[tool_id] = {"name": tool_name, "input": None, "output": None}
                                console.print(f"\n[dim cyan]> Calling {tool_name}...[/dim cyan]", end="")

                            elif event_type == "tool-input-available":
                                tool_id = event.get("id")
                                tool_input = event.get("input", {})
                                if tool_id in active_tools:
                                    active_tools[tool_id]["input"] = tool_input
                                    # Show search query if relevant
                                    if "query" in tool_input:
                                        console.print(f" query=\"{tool_input['query']}\"", end="")

                            elif event_type == "tool-output-available":
                                tool_id = event.get("id")
                                tool_output = event.get("output")
                                if tool_id in active_tools:
                                    active_tools[tool_id]["output"] = tool_output
                                    # Show result count
                                    if isinstance(tool_output, list):
                                        console.print(f" [dim green]({len(tool_output)} results)[/dim green]")
                                        # Collect citations
                                        citations.extend(
                                            r for r in tool_output
                                            if isinstance(r, dict) and "resource_name" in r
                                        )
                                    else:
                                        console.print()

                            elif event_type == "finish":
                                usage = event.get("totalUsage", {})

                            elif event_type == "error":
                                error_msg = event.get("error", "Unknown error")
                                console.print(f"\n[red]Error:[/red] {error_msg}")

                        except json.JSONDecodeError:
                            # Not JSON, treat as raw text (fallback)
                            current_text += data
                            console.print(data, end="")

                # Print newline after streaming
                console.print()

                full_response = current_text

                # Show citations if any
                if citations:
                    console.print("\n[dim]Citations:[/dim]")
                    seen = set()
                    for c in citations:
                        resource_name = c.get("resource_name", "Unknown")
                        resource_id = c.get("resource_id", "")
                        if resource_id not in seen:
                            seen.add(resource_id)
                            page = c.get("page_number")
                            page_str = f" (p.{page})" if page else ""
                            console.print(f"  [dim cyan]{resource_name}{page_str}[/dim cyan]")

                # Show token usage
                if usage:
                    prompt = usage.get("promptTokens", 0)
                    completion = usage.get("completionTokens", 0)
                    console.print(f"\n[dim]Tokens: {prompt} prompt + {completion} completion = {prompt + completion} total[/dim]")

        except httpx.ConnectError as e:
            console.print(f"[red]Connection error:[/red] Could not connect to {self.base_url}")
            console.print(f"[dim]{e}[/dim]")
            self.messages.pop()
            return ""
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            self.messages.pop()
            return ""

        # Add assistant response to history
        if full_response:
            self.messages.append({"role": "assistant", "content": full_response})

        return full_response

    async def run_interactive(self):
        """Run the interactive chat loop."""
        console.print(Panel.fit(
            f"[bold]Chat Client[/bold]\n"
            f"Game: [cyan]{self.game_id}[/cyan]\n"
            f"Server: [dim]{self.base_url}[/dim]\n\n"
            f"Commands: [dim]quit, exit, clear, history[/dim]",
            title="GameGame Chat",
        ))

        while True:
            try:
                console.print()
                user_input = console.input("[bold green]You:[/bold green] ").strip()

                if not user_input:
                    continue

                # Handle commands
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

                # Send message
                console.print("[bold blue]Assistant:[/bold blue]", end="")
                await self.send_message(user_input)

            except KeyboardInterrupt:
                console.print("\n[dim]Interrupted. Type 'quit' to exit.[/dim]")
            except EOFError:
                console.print("\n[dim]Goodbye![/dim]")
                break


async def main():
    parser = argparse.ArgumentParser(description="Chat with a game's AI assistant")
    parser.add_argument("game", help="Game ID or slug (e.g., 'catan')")
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Base URL of the API server (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--message", "-m",
        help="Send a single message instead of interactive mode",
    )

    args = parser.parse_args()

    client = ChatClient(base_url=args.url, game_id=args.game)

    try:
        if args.message:
            # Single message mode
            console.print("[bold blue]Assistant:[/bold blue]", end="")
            await client.send_message(args.message)
        else:
            # Interactive mode
            await client.run_interactive()
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
