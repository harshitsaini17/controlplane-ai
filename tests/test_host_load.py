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
    classify_porcelain,
    code_commit_cell,
    is_quiet,
    load_stamp,
    quiet_verdict,
    reproducibility_verdict,
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


# --- The amended citability rule (06 §8 / M-55) ------------------------------------------------
#
# These pin a *definition*, not a behaviour: what counts as a tree dirty enough to disqualify an
# artifact. It was widened by adjudication, and the reason it is pinned this densely is that the
# agent whose artifacts the rule grades is the one that implemented it — so each boundary the
# ruling drew gets a test that fails if the boundary moves outward.


def test_m55_an_untracked_report_the_run_itself_wrote_does_not_dirty_the_tree() -> None:
    """The whole point of the amendment: a run writes reports, so it cannot condemn itself.

    Before this, `dirty` was `bool(porcelain)` and any measurement run was dirty by construction
    from the moment it wrote its first artifact.
    """
    dirty, excused = classify_porcelain("?? reports/latency_report.md")
    assert dirty is False
    assert excused == ["reports/latency_report.md"]


def test_m55_a_modified_tracked_report_still_disqualifies() -> None:
    """The exemption is for *untracked* run output, not for edits to committed evidence.

    06 §8 already requires a report to be committed in the change that cites it, so a tracked
    report showing as modified is a stale edit or a hand-edit — the two things the section most
    wants to catch. Widening the allowlist to cover it would excuse exactly those.
    """
    dirty, excused = classify_porcelain(" M reports/latency_report.md")
    assert dirty is True
    assert excused == []


def test_m55_an_untracked_file_outside_reports_still_disqualifies() -> None:
    """`reports/` is the whole allowlist. A stray file elsewhere is unreviewed code or docs."""
    dirty, excused = classify_porcelain("?? DESIGN-notes.md")
    assert dirty is True
    assert excused == []


def test_m55_mixed_dirt_is_disqualifying_even_though_some_of_it_is_excused() -> None:
    """One disqualifying entry condemns the artifact regardless of how much run output sits
    beside it — the excused list is not a majority vote."""
    dirty, excused = classify_porcelain(
        "?? reports/fault_injection_report.md\n M controlplane/detectors/base.py"
    )
    assert dirty is True
    assert excused == ["reports/fault_injection_report.md"]


def test_m55_a_path_containing_spaces_is_not_split_into_two_paths() -> None:
    """Porcelain v1 is `XY<space>PATH`; splitting on whitespace truncates such a path to its
    first word, which would then miss the `reports/` prefix or invent a phantom entry."""
    dirty, excused = classify_porcelain("?? reports/latency report.md")
    assert dirty is False
    assert excused == ["reports/latency report.md"]


def test_m55_the_stamp_lists_what_it_excused_rather_than_absorbing_it() -> None:
    """06 §8 requires the listing. An exemption a reader cannot see is a blanket exemption: the
    listing is what lets them notice the stamp excusing dirt the run did not create."""
    cell = code_commit_cell(
        {"commit": "abcdef123456789", "dirty": False,
         "run_generated": ["reports/latency_report.md"]}
    )
    assert "clean except run-generated" in cell
    assert "reports/latency_report.md" in cell


def test_m55_a_genuinely_clean_tree_claims_no_exemption() -> None:
    """The listing must not appear when nothing was excused, or it stops being a signal."""
    cell = code_commit_cell({"commit": "abcdef123456789", "dirty": False, "run_generated": []})
    assert "run-generated" not in cell
    assert "uncommitted" not in cell


def test_m57_an_unrecorded_tree_state_is_not_reported_as_a_clean_tree() -> None:
    """Third value, same reasoning as `is_quiet`: absent is not the same as good.

    When git is unavailable `git_stamp` can still return a commit from elsewhere but knows
    nothing about the tree. Rendering that as `clean` would report unverified dirt as
    verified-absent — the one conflation this module exists to refuse.
    """
    unknown = reproducibility_verdict(
        {"commit": "abcdef123456789", "dirty": None, "run_generated": None}
    )
    assert "not recorded" in unknown
    assert "NOT CITABLE" in unknown
    assert "clean" not in unknown
    assert "not recorded" in code_commit_cell(
        {"commit": "abcdef123456789", "dirty": None, "run_generated": None}
    )
