"""The re-derivation check itself (ADR-032 Correction 1 item 3).

`eval/check_derivations.py` is a guard, and a guard nobody tests is a guard that passes because
it stopped looking. So the load-bearing test here is **negative**: pointed at the pre-correction
artifact — the one ADR-032's original table was written from — the checker must still find the
defects that correction was filed for. If a refactor makes it permissive, this fails.

The positive test is the landing gate: the committed docs must re-derive cleanly against the
committed artifact, with no MISMATCH and no NO SOURCE. Under the Correction 1 ruling there is no
third state — a figure gains a derivation or loses its derivation claim.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from eval.check_derivations import checks, main  # noqa: E402

DECISIONS = REPO / "docs" / "03-decisions.md"
ARTIFACT = REPO / "reports" / "spike_window_latency.json"
PRE = REPO / "reports" / "spike_window_latency.pre-correction-1.json"


def _verdicts(artifact: Path) -> dict[str, list[str]]:
    art = json.loads(artifact.read_text())
    out: dict[str, list[str]] = {"OK": [], "MISMATCH": [], "NO SOURCE": []}
    for c in checks(art, DECISIONS.read_text()):
        out[c.verdict].append(c.label)
    return out


@pytest.mark.skipif(not PRE.exists(), reason="pre-correction artifact not retained")
def test_correction1_checker_still_catches_the_defects_it_was_built_for() -> None:
    """Against the withdrawn artifact, the checker must find real defects — not pass.

    Three independent classes, all of them "a figure described by a derivation it does not come
    from":
      * coverage labels read off the filler's token count rather than the geometry,
      * percentiles published from sample sizes that cannot resolve them,
      * a tokenization table with no measuring script at all.
    """
    v = _verdicts(PRE)
    assert v["MISMATCH"] or v["NO SOURCE"], (
        "the checker reports the pre-correction artifact as clean — it has stopped checking"
    )
    # It must also still VALIDATE things: an all-fail checker is as useless as an all-pass one.
    assert len(v["OK"]) >= 10, f"only {len(v['OK'])} figures validated; matching is too strict"


@pytest.mark.skipif(not PRE.exists(), reason="pre-correction artifact not retained")
def test_correction1_withdrawn_coverage_labels_are_caught_specifically() -> None:
    """Not just "some failure" — the coverage mismatch by name.

    A test satisfied by any failure would keep passing if the checker broke in a new way and
    stopped seeing this one.
    """
    v = _verdicts(PRE)
    coverage = [lab for lab in v["MISMATCH"] if "coverage label" in lab]
    assert coverage, f"coverage labels not flagged; MISMATCH was {v['MISMATCH']}"


@pytest.mark.skipif(not ARTIFACT.exists(), reason="no published spike artifact")
@pytest.mark.xfail(
    reason="ADR-032 Correction 1 has not landed: the docs still cite the pre-re-run figures and "
           "the committed artifact's four largest rungs cannot resolve a P99 (n=20/n=10)",
    strict=True,
)
def test_correction1_committed_docs_rederive_against_committed_artifact() -> None:
    """The landing gate. Every derivation-claiming figure in ADR-032/034 must check out.

    `strict=True` so this fails loudly the moment it starts passing — the marker cannot outlive
    the work it is waiting on, which is the only reason an xfail is honest here rather than a
    failing test swept under a marker (AGENTS.md §5.4). What it asserts is unchanged and the
    checker still runs on every invocation; only the expectation is dated.

    Current verdicts against the committed pair: 6 OK / 22 MISMATCH / 12 NO SOURCE. The
    MISMATCHes are run-to-run variance (the docs cite the original run, `reports/` holds a
    re-run) except the batching-prose rows, which are 25-28% out because they read batch-curve
    points that `contamination_signals` independently flags in that same artifact. The NO SOURCE
    rows are the defect this correction exists for: a P99 was published from a sample that
    cannot resolve one.
    """
    v = _verdicts(ARTIFACT)
    assert not v["MISMATCH"], f"figures contradict the artifact: {v['MISMATCH']}"
    assert not v["NO SOURCE"], (
        "figures claim a derivation the artifact cannot produce — each must gain a source or "
        f"drop the claim (ADR-032 Correction 1): {v['NO SOURCE']}"
    )


@pytest.mark.skipif(not PRE.exists(), reason="pre-correction artifact not retained")
def test_correction1_check_exits_nonzero_on_a_defect() -> None:
    """Half of the exit-status contract, and the half that has teeth TODAY.

    Split from its other half deliberately. The clean-artifact direction is pending on Correction
    1 landing, but this direction is verifiable now, and folding both into one xfailed test would
    have retired a live assertion to accommodate a dated one — the failing half hiding the
    working half.
    """
    assert main(["--artifact", str(PRE)]) == 1


@pytest.mark.skipif(not ARTIFACT.exists(), reason="no published spike artifact")
@pytest.mark.xfail(reason="ADR-032 Correction 1 has not landed", strict=True)
def test_landing_gate_check_exits_zero_once_the_docs_rederive() -> None:
    """The other half: usable as a commit gate means exit 0 has to be reachable."""
    assert main(["--artifact", str(ARTIFACT)]) == 0


def test_correction1_withdrawn_tables_are_quoted_and_so_excluded_from_rederivation() -> None:
    """A withdrawn table must not be re-derived against the current artifact.

    Correction 1 preserves the original mislabelled table beside the corrected one. That table
    is **blockquoted**, which is both how the doc marks it withdrawn and how this check skips
    it: `_table_after` only recognises rows beginning with `|`. Pinned as a test because it is
    otherwise a coincidence one reformat away from breaking — un-quoting the withdrawn table
    would silently point the landing gate at figures that were deliberately retired.
    """
    from eval.check_derivations import _table_after

    doc = (
        "| windows | tokens | sequential | batched (all in one call) |\n"
        "|---|---|---|---|\n"
        "| 1 | 102 | 1.0 / 2.0 | 3.0 / 4.0 |\n"
        "\n"
        "> | windows | tokens | sequential | batched (all in one call) |\n"
        "> |---|---|---|---|\n"
        "> | 52 | 4082 | 651.41 / 657.04 | 800.75 / 819.96 |\n"
    )
    rows = _table_after(doc, "batched (all in one call)")
    assert [r[0] for r in rows] == ["1"], f"quoted table leaked into the check: {rows}"
