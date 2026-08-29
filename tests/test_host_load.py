"""Measurement-conditions stamp (ADR-032 Correction 1 item 2).

These pin the *reasoning* in `eval/host_load.py`, not just its return shape. The stamp exists
because a published artifact was once contaminated by concurrent multi-core work and the only
evidence was inferential — a percentile that moved 25% between runs. Two design decisions in
that module are load-bearing and both are the kind a later reader would "simplify" away:
three-valued quietness, and an absolute rather than per-CPU threshold.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from eval.host_load import (  # noqa: E402
    QUIET_LOAD1_MAX,
    is_quiet,
    load_stamp,
    quiet_verdict,
)


def test_correction1_stamp_carries_load_and_cpu_count() -> None:
    """The artifact needs both halves: a load figure means nothing without the core count."""
    stamp = load_stamp()
    assert set(stamp) == {"load1", "load5", "load15", "cpus"}
    assert stamp["cpus"] is None or stamp["cpus"] >= 1
    if stamp["load1"] is not None:                     # Unix; None is the documented fallback
        assert all(isinstance(stamp[k], float) for k in ("load1", "load5", "load15"))
        assert stamp["load1"] >= 0.0


def test_correction1_quietness_is_three_valued() -> None:
    """`None` (unknown) must not collapse into `False` (measured, and too high).

    Collapsing them either excuses real contamination or invents it. 06 §8 treats both as
    non-citable, but only one of them is a *finding* about the host.
    """
    assert is_quiet({"load1": 0.1, "load5": 0.1, "load15": 0.1, "cpus": 12}) is True
    assert is_quiet({"load1": 9.0, "load5": 9.0, "load15": 9.0, "cpus": 12}) is False
    assert is_quiet(None) is None
    assert is_quiet({}) is None
    assert is_quiet({"load1": None, "cpus": 12}) is None          # non-Unix platform


def test_correction1_threshold_is_absolute_not_per_cpu() -> None:
    """A load of 2 on a 12-CPU host is NOT quiet, even though 11 cores are idle.

    The tempting "fix" is to normalise by core count — a load of 2 on 12 CPUs looks like 17%
    utilisation. But the contamination this catches was ~20 s of a competing multi-core job
    that ruined a 10-rep measurement point, and it would have sailed through a normalised
    threshold. The threshold is about *whether anything else is running*, not about headroom.
    """
    assert QUIET_LOAD1_MAX <= 1.0
    assert is_quiet({"load1": 2.0, "load5": 2.0, "load15": 2.0, "cpus": 12}) is False
    assert is_quiet({"load1": 2.0, "load5": 2.0, "load15": 2.0, "cpus": 128}) is False


@pytest.mark.parametrize(
    "stamp,expect",
    [
        ({"load1": 0.2, "load5": 0.2, "load15": 0.2, "cpus": 12}, "QUIET"),
        ({"load1": 8.0, "load5": 8.0, "load15": 8.0, "cpus": 12}, "NOT CITABLE"),
        (None, "NOT CITABLE"),
    ],
)
def test_correction1_verdict_names_06_8_where_a_reader_will_look(
    stamp: dict[str, object] | None, expect: str
) -> None:
    """The rendered verdict cites the rule it applies, in both harnesses' reports."""
    verdict = quiet_verdict(stamp)
    assert expect in verdict
    if expect == "NOT CITABLE":
        assert "06 §8" in verdict


def test_correction1_unknown_load_is_not_reported_as_a_dirty_host() -> None:
    """An artifact predating the stamp is uncitable for a *different* reason than a busy one.

    Both block citation; only one is evidence about the machine. The wording must not accuse a
    host that was never measured.
    """
    unknown = quiet_verdict(None)
    busy = quiet_verdict({"load1": 9.0, "cpus": 12})
    assert unknown != busy
    assert "not recorded" in unknown
    assert "NOT QUIET" not in unknown
    assert "NOT QUIET" in busy
