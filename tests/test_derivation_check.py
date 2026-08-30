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

from eval.check_derivations import checks, collect, doc_claims, main  # noqa: E402

DECISIONS = REPO / "docs" / "03-decisions.md"
ARTIFACT = REPO / "reports" / "spike_window_latency.json"
PRE = REPO / "reports" / "spike_window_latency.pre-correction-1.json"
CURVE = REPO / "reports" / "spike_batch_curve.json"
SPEC = REPO / "docs" / "04-policy-and-detection-spec.md"
EVALPLAN = REPO / "docs" / "06-evaluation-plan.md"
VERDICTS = ("OK", "MISMATCH", "NO SOURCE", "ABSENT")


def _ladder_tables(doc: str) -> list[str]:
    """Every ADR-032 ladder table in the doc, live or blockquoted, as text blocks.

    Split out because two tests need the same slicing and a regex over the whole file would be
    the fragile way: the tables differ only by a `> ` prefix.
    """
    out, cur = [], []
    for line in doc.splitlines():
        bare = line.lstrip("> ").rstrip()
        if bare.startswith("|"):
            cur.append(line)
        elif cur:
            out.append("\n".join(cur)); cur = []
    if cur:
        out.append("\n".join(cur))
    return [t for t in out if "batched (all in one call)" in t]


def _first_ladder_table(doc: str) -> str:
    """The live (corrected) table — the one `_table_after` reads."""
    for t in _ladder_tables(doc):
        if t.lstrip().startswith("|"):
            return t
    raise AssertionError("no live ladder table found in ADR-032")


def _withdrawn_ladder_table(doc: str) -> str:
    """The preserved withdrawn table, un-quoted so the checker can see it."""
    for t in _ladder_tables(doc):
        if t.lstrip().startswith(">"):
            return "\n".join(ln.lstrip()[1:].lstrip() for ln in t.splitlines())
    raise AssertionError("no blockquoted (withdrawn) ladder table found in ADR-032")


def _verdicts(artifact: Path, curve: Path | None) -> dict[str, list[str]]:
    """Verdicts for every figure across all three docs, via the CLI's own collection path.

    `curve` is separate because Correction 2's batch figures were re-measured into their own
    artifact (one run, one provenance stamp — M-33). Passing the artifact under test as its own
    curve is what keeps a negative test honest: with `curve=None` the batch figures would come
    back NO SOURCE for a *missing file* rather than a real defect, and the assertion would pass
    for the wrong reason.
    """
    art = json.loads(artifact.read_text())
    out: dict[str, list[str]] = {v: [] for v in VERDICTS}
    for c in collect(art, json.loads(curve.read_text()) if curve else None,
                     DECISIONS.read_text(), SPEC.read_text(), EVALPLAN.read_text()):
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
    v = _verdicts(PRE, PRE)
    assert v["MISMATCH"] or v["NO SOURCE"], (
        "the checker reports the pre-correction artifact as clean — it has stopped checking"
    )
    # It must also still VALIDATE things: an all-fail checker is as useless as an all-pass one.
    assert len(v["OK"]) >= 10, f"only {len(v['OK'])} figures validated; matching is too strict"


def test_correction1_withdrawn_coverage_labels_are_caught_specifically() -> None:
    """Not just "some failure" — the coverage mismatch by name, on the real withdrawn figures.

    A test satisfied by any failure would keep passing if the checker broke in a new way and
    stopped seeing this one.

    **Re-pointed when Correction 1 landed, not deleted** (the convention ADR-031 consequence 5
    sets for tripwires). It previously read the pre-correction *artifact*, which no longer works
    and could not be made to: the coverage defect lived in the **doc text**, and this check's
    derived side is `coverage_tokens(n)`, a pure formula. Once the doc was corrected, the labels
    agree with the geometry against *any* artifact — the assertion had become unsatisfiable rather
    than merely unsatisfied, so leaving it pointed at `PRE` would have been a test that can never
    fail dressed as one that can.

    So the fixture is now the **withdrawn table itself**, which Correction 1 preserves verbatim
    (blockquoted) precisely so the defect stays inspectable. Un-quoting it hands the checker the
    exact rows that were published — 16w labelled 1546 against a derived 1242, 32w as ~3100
    against 2458, 52w as 4082 against 3978 — and the checker must still flag them. That ties the
    guard to preserved evidence rather than to a run, so it keeps working after the next
    re-measurement.
    """
    doc = DECISIONS.read_text()
    live = _first_ladder_table(doc)
    withdrawn = _withdrawn_ladder_table(doc)
    assert "| 52 |" in withdrawn or "| **52** |" in withdrawn, (
        "the withdrawn 52-window table is no longer preserved in ADR-032 Correction 1 — it is the "
        "only record of what was published, and this guard's fixture"
    )
    v: dict[str, list[str]] = {ver: [] for ver in VERDICTS}
    for c in checks(json.loads(ARTIFACT.read_text()), doc.replace(live, withdrawn)):
        v[c.verdict].append(c.label)
    coverage = [lab for lab in v["MISMATCH"] if "coverage label" in lab]
    assert len(coverage) >= 3, (
        f"checker no longer flags the withdrawn coverage labels; MISMATCH was {v['MISMATCH']}"
    )


@pytest.mark.skipif(not ARTIFACT.exists(), reason="no published spike artifact")
@pytest.mark.skipif(not CURVE.exists(), reason="no published batch-curve artifact")
def test_correction1_committed_docs_rederive_against_committed_artifact() -> None:
    """The landing gate. Every derivation-claiming figure in ADR-032/034 must check out.

    `strict=True` so this fails loudly the moment it starts passing — the marker cannot outlive
    the work it is waiting on, which is the only reason an xfail is honest here rather than a
    failing test swept under a marker (AGENTS.md §5.4). What it asserts is unchanged and the
    checker still runs on every invocation; only the expectation is dated.

    **Live as of Correction 2** — no longer xfailed. The marker it carried was waiting on
    `[D1-batch-4-justification-falsified-at-the-corrected-bound]`: while that deviation was open,
    ADR-032's batching figures could not be re-cited without rewriting the justification under
    dispute (AGENTS.md §5.4), so 6 MISMATCH + 1 NO SOURCE were expected. Correction 2 re-measured
    the curve at n=40 and re-cited from it; the marker was `strict=True` precisely so it could not
    outlive that, and retiring it here is that mechanism working rather than a test being relaxed.
    The assertions are unchanged — only the expectation was dated.

    ABSENT is failed alongside them: a doc whose wording drifted out from under its anchor is an
    unchecked claim, and an unchecked claim passing as OK is the failure mode this file exists to
    prevent.
    """
    v = _verdicts(ARTIFACT, CURVE)
    assert not v["MISMATCH"], f"figures contradict the artifact: {v['MISMATCH']}"
    assert not v["NO SOURCE"], (
        "figures claim a derivation the artifact cannot produce — each must gain a source or "
        f"drop the claim (ADR-032 Correction 1): {v['NO SOURCE']}"
    )
    assert not v["ABSENT"], (
        f"a doc's wording drifted out from under its anchor, so these stopped being checked "
        f"(fix the pattern in _DOC_CLAIMS, do not drop the claim): {v['ABSENT']}"
    )
    assert len(v["OK"]) >= 50, f"only {len(v['OK'])} figures checked; coverage regressed"


@pytest.mark.skipif(not PRE.exists(), reason="pre-correction artifact not retained")
def test_correction1_check_exits_nonzero_on_a_defect() -> None:
    """Half of the exit-status contract, and the half that has teeth TODAY.

    Split from its other half deliberately. The clean-artifact direction is pending on Correction
    1 landing, but this direction is verifiable now, and folding both into one xfailed test would
    have retired a live assertion to accommodate a dated one — the failing half hiding the
    working half.
    """
    assert main(["--artifact", str(PRE), "--curve-artifact", str(PRE)]) == 1


@pytest.mark.skipif(not ARTIFACT.exists(), reason="no published spike artifact")
@pytest.mark.skipif(not CURVE.exists(), reason="no published batch-curve artifact")
def test_landing_gate_check_exits_zero_once_the_docs_rederive() -> None:
    """The other half: usable as a commit gate means exit 0 has to be reachable.

    Also no longer xfailed, same cause as the gate above (Correction 2 landed the re-cited batch
    figures). Kept split from its negative twin so the two directions of the exit contract fail
    independently and name their own cause.
    """
    assert main(["--artifact", str(ARTIFACT),
                 "--curve-artifact", str(CURVE)]) == 0


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


@pytest.mark.skipif(not ARTIFACT.exists(), reason="no published spike artifact")
def test_widened_checker_covers_the_figure_copies_outside_adr032() -> None:
    """The widening has teeth: `04` and `06` carry their own copies of ADR-032's figures.

    A corrected ADR with stale copies downstream is the same defect one indirection out, so the
    ruling that widened this check asked for coverage over precision. Asserted by count rather
    than by value because the values are already checked by the landing gate — what can silently
    regress is `_DOC_CLAIMS` being emptied or a doc dropping out of `collect()`.
    """
    art = json.loads(ARTIFACT.read_text())
    for label, doc in (("04 \u00a72.1", SPEC), ("06 \u00a74", EVALPLAN)):
        got = doc_claims(art, label, doc.read_text())
        assert len(got) >= 4, f"{label} contributes only {len(got)} checks: {got}"
        assert not [c for c in got if c.verdict == "ABSENT"], (
            f"{label}: anchors match nothing — the figures are no longer being checked"
        )


@pytest.mark.skipif(not ARTIFACT.exists(), reason="no published spike artifact")
def test_drifted_wording_reports_absent_not_ok() -> None:
    """Drifted wording must be a finding, not a silent pass.

    The regex approach's one real failure mode: reword the sentence and its figures stop being
    checked while the run stays green. So an anchor matching nothing is reported, and reported as
    ABSENT rather than NO SOURCE — the two send a reader to different places (a broken pattern vs
    an ungrounded figure), and collapsing them would have a drifted doc read as a bad number.
    """
    art = json.loads(ARTIFACT.read_text())
    drifted = SPEC.read_text().replace("0.41 / 8.22 at 6 threads", "0.41 / 8.22 at six threads")
    assert drifted != SPEC.read_text(), "fixture string no longer present in 04 — re-point this"
    verdicts = [c.verdict for c in doc_claims(art, "04 \u00a72.1", drifted)]
    assert "ABSENT" in verdicts, f"drift went unreported; verdicts were {verdicts}"
    assert "NO SOURCE" not in verdicts, "drift was misreported as an ungrounded figure"
