"""Lightweight chat eval harness for board game answer quality."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import typer
from rich.console import Console
from rich.table import Table

console = Console()
app = typer.Typer(help="Run lightweight chat eval suites")

DEFAULT_SUITE = Path(__file__).parent.parent.parent.parent / "evals" / "cases" / "boardgame_smoke.json"


@dataclass
class EvalCase:
    """A single eval case."""

    id: str
    prompt: str
    game: str | None = None
    must_include: list[str] | None = None
    must_not_include: list[str] | None = None
    min_citations: int = 1


@dataclass
class EvalResult:
    """Result for one eval case."""

    case_id: str
    game: str
    prompt: str
    passed: bool
    score: float
    reasons: list[str]
    content: str
    citations: int


def load_suite(path: Path) -> tuple[str, list[EvalCase]]:
    """Load suite JSON from disk."""
    data = json.loads(path.read_text())
    name = data.get("name", path.stem)
    defaults = data.get("defaults", {})
    default_game = defaults.get("game")
    cases_raw = data.get("cases", [])

    cases = [EvalCase(
            id=raw["id"],
            prompt=raw["prompt"],
            game=raw.get("game", default_game),
            must_include=raw.get("must_include", []),
            must_not_include=raw.get("must_not_include", []),
            min_citations=raw.get("min_citations", 1),
        ) for raw in cases_raw]

    return name, cases


def score_case(
    case: EvalCase,
    content: str,
    citations: list[dict[str, Any]],
) -> tuple[bool, float, list[str]]:
    """Score one case with deterministic checks."""
    reasons: list[str] = []
    checks = 0
    passed_checks = 0
    content_lc = content.lower()

    for token in case.must_include or []:
        checks += 1
        if token.lower() in content_lc:
            passed_checks += 1
        else:
            reasons.append(f"Missing required phrase: {token!r}")

    for token in case.must_not_include or []:
        checks += 1
        if token.lower() not in content_lc:
            passed_checks += 1
        else:
            reasons.append(f"Contains forbidden phrase: {token!r}")

    checks += 1
    if len(citations) >= case.min_citations:
        passed_checks += 1
    else:
        reasons.append(
            f"Expected at least {case.min_citations} citation(s), got {len(citations)}"
        )

    score = passed_checks / checks if checks else 0.0
    passed = score == 1.0
    return passed, score, reasons


@app.command("list")
def list_cases(
    suite: Path = typer.Option(DEFAULT_SUITE, "--suite", help="Path to eval suite JSON"),
) -> None:
    """List eval cases in a suite."""
    suite_name, cases = load_suite(suite)
    table = Table(title=f"Eval Suite: {suite_name}")
    table.add_column("Case ID", style="cyan")
    table.add_column("Game", style="magenta")
    table.add_column("Prompt")
    for case in cases:
        table.add_row(case.id, case.game or "-", case.prompt)
    console.print(table)


@app.command("run")
def run_suite(
    suite: Path = typer.Option(DEFAULT_SUITE, "--suite", help="Path to eval suite JSON"),
    url: str = typer.Option("http://localhost:8000", "--url", "-u", help="API base URL"),
    game: str | None = typer.Option(None, "--game", help="Override game for all cases"),
    fail_fast: bool = typer.Option(False, "--fail-fast", help="Stop on first failure"),
) -> None:
    """Run eval suite against the chat API."""
    suite_name, cases = load_suite(suite)
    if not cases:
        console.print(f"[yellow]No cases in suite {suite_name}[/yellow]")
        raise typer.Exit(code=0)

    results: list[EvalResult] = []
    with httpx.Client(timeout=120.0) as client:
        for case in cases:
            target_game = game or case.game
            if not target_game:
                raise typer.BadParameter(
                    f"Case {case.id!r} has no game configured. Set it in suite or pass --game."
                )

            response = client.post(
                f"{url.rstrip('/')}/api/games/{target_game}/chat",
                json={"messages": [{"role": "user", "content": case.prompt}], "stream": False},
            )

            if response.status_code != 200:
                result = EvalResult(
                    case_id=case.id,
                    game=target_game,
                    prompt=case.prompt,
                    passed=False,
                    score=0.0,
                    reasons=[f"HTTP {response.status_code}: {response.text[:200]}"],
                    content="",
                    citations=0,
                )
            else:
                data = response.json()
                content = data.get("content", "")
                citations = data.get("citations", [])
                passed, score, reasons = score_case(case, content, citations)
                result = EvalResult(
                    case_id=case.id,
                    game=target_game,
                    prompt=case.prompt,
                    passed=passed,
                    score=score,
                    reasons=reasons,
                    content=content,
                    citations=len(citations),
                )

            results.append(result)
            status = "[green]PASS[/green]" if result.passed else "[red]FAIL[/red]"
            console.print(
                f"{status} {result.case_id} ({result.game}) score={result.score:.2f} citations={result.citations}"
            )
            if result.reasons:
                for reason in result.reasons:
                    console.print(f"  [dim]- {reason}[/dim]")
            if fail_fast and not result.passed:
                break

    passed_count = sum(1 for r in results if r.passed)
    total = len(results)
    avg_score = sum(r.score for r in results) / total if total else 0.0
    console.print(
        f"\n[bold]Summary:[/bold] {passed_count}/{total} passed, average score={avg_score:.2f}"
    )

    raise typer.Exit(code=0 if passed_count == total else 1)
