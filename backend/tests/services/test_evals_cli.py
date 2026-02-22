"""Tests for lightweight eval harness helpers."""

import json
import uuid
from pathlib import Path

from gamegame.cli.evals import EvalCase, load_suite, score_case


def test_score_case_passes_when_all_checks_satisfied():
    case = EvalCase(
        id="c1",
        prompt="How do I set up?",
        must_include=["set up"],
        must_not_include=["strategy"],
        min_citations=1,
    )
    passed, score, reasons = score_case(
        case=case,
        content="To set up the game, place the board and tokens.",
        citations=[{"resource_id": "r1"}],
    )
    assert passed is True
    assert score == 1.0
    assert reasons == []


def test_score_case_fails_with_missing_required_phrase():
    case = EvalCase(
        id="c1",
        prompt="How do I set up?",
        must_include=["set up"],
        min_citations=1,
    )
    passed, score, reasons = score_case(
        case=case,
        content="Place the board first.",
        citations=[{"resource_id": "r1"}],
    )
    assert passed is False
    assert score < 1.0
    assert "Missing required phrase" in reasons[0]


def test_load_suite_reads_cases():
    suite = {
        "name": "Smoke",
        "defaults": {"game": "test-game"},
        "cases": [
            {"id": "one", "prompt": "Q1"},
            {"id": "two", "prompt": "Q2", "game": "custom-game"},
        ],
    }
    path = Path("/tmp") / f"gamegame-eval-suite-{uuid.uuid4().hex}.json"
    path.write_text(json.dumps(suite))

    try:
        name, cases = load_suite(path)
        assert name == "Smoke"
        assert len(cases) == 2
        assert cases[0].game == "test-game"
        assert cases[1].game == "custom-game"
    finally:
        path.unlink(missing_ok=True)
