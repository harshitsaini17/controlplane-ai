"""07 demo runner — the beats are a regression suite (AGENTS.md §8), so the runner is too.

What is pinned here is not "do the beats pass" — that is the runner's own job and it exits
nonzero when they do not. What is pinned is that the runner **can** fail: a demo harness whose
expectations come from its own observations passes unconditionally, and on the demo path that
defect would stay invisible until a judge was watching.
"""

from __future__ import annotations

import pytest

from demo import run_script as rs


def test_expectations_come_from_the_frozen_dataset_not_from_observation() -> None:
    """The load must carry real per-use-case expectations, or nothing is being checked."""
    cases = rs.load_cases()
    assert rs.expected_action(cases["PII-001"], "support_bot") == "edit"
    assert rs.expected_action(cases["PII-001"], "hr_copilot") == "block"
    assert rs.expected_action(cases["PII-001"], "finance_advisor") == "escalate"


def test_an_empty_dataset_is_a_hard_failure_not_an_all_green_run(tmp_path) -> None:
    """Zero expectations loaded must stop the run, not produce a vacuous pass."""
    with pytest.raises(SystemExit):
        rs.load_cases(tmp_path)


def test_a_case_with_no_expectation_for_the_use_case_is_refused() -> None:
    with pytest.raises(SystemExit):
        rs.expected_action({"case_id": "X", "action_expected": {}}, "support_bot")


def test_the_signature_beat_requires_all_three_verdicts(monkeypatch) -> None:
    """Beat 4 is the thesis: two of three is a failure, not a partial success.

    Driven by rewriting the *dataset expectation* rather than the gateway, which is the
    cheapest way to prove the assertion is live: if the runner mirrored observation, changing
    what the dataset demands would change nothing.
    """
    cases = rs.load_cases()
    case = dict(cases["PII-001"])
    case["action_expected"] = {**case["action_expected"], "hr_copilot": "pass"}
    result = rs.beat_4({**cases, "PII-001": case})
    assert result.status == rs.FAIL, "a wrong verdict under one policy must fail the beat"
    assert not result.ok


def test_a_raising_beat_is_a_failure_never_a_silent_skip(monkeypatch) -> None:
    def boom(_cases):
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr(rs, "beat_1", boom)
    results = rs.run_beats(rs.load_cases(), only=("1",))
    assert [r.status for r in results] == [rs.FAIL]
    assert "RuntimeError" in results[0].detail


def test_skipped_is_not_counted_as_passing_and_does_not_fail_the_build(capsys) -> None:
    """Cut scope must be loud and listed, but a cut is not a regression."""
    skipped = rs.BeatResult("7b", "cost plane", rs.SKIPPED, "unbuilt")
    assert rs.report([skipped]) == 0
    out = capsys.readouterr().out
    assert "SKIPPED" in out
    assert "0 passed" in out and "1 skipped" in out
    assert not skipped.ok


def test_a_failing_beat_exits_nonzero_and_names_the_demo_path(capsys) -> None:
    assert rs.report([rs.BeatResult("3", "block", rs.FAIL, "verdict drifted")]) == 1
    assert "BLOCKER" in capsys.readouterr().out


def test_a_fixture_reports_no_token_usage_rather_than_zero() -> None:
    """0 is an affirmative count that would enter the cost plane as a real measurement.

    ADR-018's dev/measured split one layer down: a replayed response has no self-reported
    usage at all, and `None` is the only honest encoding of that.
    """
    import asyncio

    resp = asyncio.run(rs.FixtureDispatcher("hello.").complete())
    assert resp.prompt_tokens is None and resp.completion_tokens is None


def test_a_live_provider_run_is_refused_rather_than_quietly_faked() -> None:
    """Without --replay the runner must not silently substitute fixtures (ADR-018)."""
    assert rs.main([]) == 2
