"""ADR-032 Correction 1 — published window counts must cover the policy bound.

`[D3-bound-case-window-count-undercovers-the-policy-bound]`: ADR-032's original table labelled its
bound case **"52 windows at the `per_request_max_tokens: 4000` bound"** while 52 strided windows
span only `102 + 51*76 = 3978` content tokens — a **22-token unscanned tail** at a 4000-token bound.
The ADR's load-bearing claim is full coverage (*"Every window is scored; no input is skipped"*),
because prefix truncation was overruled as a pad-then-inject bypass. A bound case that under-covers
contradicts the guarantee the ADR exists to make.

The measured latencies were sound — cost tracks tensor shape and window count, both of which the
harness pinned exactly. The **labels** were not: they came from the synthetic filler's own token
count rather than from the geometry, and the filler overshoots its target (it length-checks every 64
words), so at the top rung it read 4082 against 3978 actually spanned.

These tests are the guard the ruling required, in three parts:

1. the harness cannot ship a top rung that under-covers the bound (also asserted at import in
   `eval/spike_window_latency`, so it fires before a measurement rather than after);
2. every published coverage label equals `coverage_tokens(n)` — computed, never observed;
3. the **detector-side** count (ADR-034 Part C: tokenize once, use the exact count) leaves no
   unscanned tail at the bound.

Part 3 is the one that matters for behaviour: the harness measures what the detector will do, so a
detector-side off-by-one would be a real coverage hole rather than a mislabelled row.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.spike_window_latency import (
    BOUND_WINDOWS,
    POLICY_BOUND_TOKENS,
    WINDOW_CONTENT_TOKENS,
    WINDOW_COUNTS,
    WINDOW_OVERLAP,
    WINDOW_STEP,
    WINDOW_TOKENS,
    coverage_tokens,
    windows_for_tokens,
)

ARTIFACT = Path(__file__).resolve().parents[1] / "reports" / "spike_window_latency.json"


def test_geometry_is_internally_consistent() -> None:
    """The three published constants must compose as ADR-032 states: 104 / 26 / 76.

    Pinned because every coverage figure below derives from `WINDOW_STEP`, and the step is the one
    value that is *derived* rather than declared — HuggingFace's `stride` is the overlap, not the
    step, and reading it the other way silently produces 26-token steps and 4x the windows.
    """
    assert WINDOW_TOKENS == 104
    assert WINDOW_OVERLAP == 26
    assert WINDOW_CONTENT_TOKENS == WINDOW_TOKENS - 2 == 102
    assert WINDOW_STEP == WINDOW_CONTENT_TOKENS - WINDOW_OVERLAP == 76


def test_correction1_top_rung_covers_the_policy_bound() -> None:
    """THE invariant: the measured bound case must actually reach `per_request_max_tokens`.

    This is the assertion whose absence let the original table publish a full-coverage claim it
    could not support. If it fails, the harness's top rung has drifted below the bound — raise the
    rung, never lower the bound (AGENTS.md §5.4).
    """
    top = max(WINDOW_COUNTS)
    assert coverage_tokens(top) >= POLICY_BOUND_TOKENS, (
        f"top rung {top} windows spans {coverage_tokens(top)} tokens, short of the "
        f"{POLICY_BOUND_TOKENS}-token policy bound by "
        f"{POLICY_BOUND_TOKENS - coverage_tokens(top)}"
    )


def test_correction1_the_bound_needs_53_windows_not_52() -> None:
    """The off-by-one itself, pinned as a regression test with the old value named.

    52 is not merely "one fewer" — it is the number that shipped, so it is the one worth asserting
    against explicitly rather than leaving to a boundary calculation.
    """
    assert BOUND_WINDOWS == 53
    assert coverage_tokens(53) == 4054 >= POLICY_BOUND_TOKENS
    assert coverage_tokens(52) == 3978 < POLICY_BOUND_TOKENS
    assert POLICY_BOUND_TOKENS - coverage_tokens(52) == 22, "the tail the old bound case left"


def test_correction1_windows_for_tokens_inverts_coverage() -> None:
    """`windows_for_tokens` is what ADR-034 Part C has the DETECTOR compute.

    Harness and detector must agree by construction rather than by coincidence, so the inverse is
    asserted across the whole range: the count it returns must always cover the input, and must
    never be larger than needed (an over-count would inflate the parametric ceiling).
    """
    assert windows_for_tokens(0) == 1
    assert windows_for_tokens(1) == 1
    assert windows_for_tokens(WINDOW_CONTENT_TOKENS) == 1
    assert windows_for_tokens(WINDOW_CONTENT_TOKENS + 1) == 2

    for n_tokens in (103, 178, 179, 330, 634, 1242, 2458, 3978, 3979, 4000, 4054, 4080):
        n = windows_for_tokens(n_tokens)
        assert coverage_tokens(n) >= n_tokens, f"{n_tokens} tokens: {n} windows under-covers"
        assert coverage_tokens(n - 1) < n_tokens, f"{n_tokens} tokens: {n} windows is one too many"


def test_correction1_detector_side_count_leaves_no_tail_at_the_bound() -> None:
    """ADR-034 Part C's exact-count rule, at the bound and just past it.

    The behavioural half of the correction. A mislabelled table is a publication defect; a detector
    that computes 52 windows for a 4000-token input would leave 22 tokens genuinely unscanned,
    which is the pad-then-inject hole ADR-032 overruled truncation to close.
    """
    for n_tokens in (POLICY_BOUND_TOKENS - 1, POLICY_BOUND_TOKENS, POLICY_BOUND_TOKENS + 80):
        n = windows_for_tokens(n_tokens)
        tail = n_tokens - coverage_tokens(n)
        assert tail <= 0, f"{n_tokens} tokens -> {n} windows leaves {tail} tokens unscanned"


@pytest.mark.xfail(
    reason="ADR-032 Correction 1 has not landed its re-measurement: the committed artifact is\n"
           "still the 52-rung pre-correction run",
    strict=True,
)
@pytest.mark.skipif(not ARTIFACT.exists(), reason="no published spike artifact")
def test_correction1_published_labels_are_derived_not_observed() -> None:
    """Every coverage label in the artifact must equal the formula's output.

    This is the defect's actual mechanism: labels read off `filler_tokens` (the whole synthetic
    text) instead of computed from the geometry. A computed label cannot drift from the geometry it
    describes; an observed one can, and did.
    """
    art = json.loads(ARTIFACT.read_text())
    for run in art["runs"]:
        if "error" in run:
            continue
        assert run["bound_windows"] == BOUND_WINDOWS
        assert run["bound_coverage_tokens"] == coverage_tokens(BOUND_WINDOWS)
        assert run["window_step"] == WINDOW_STEP
        for key, row in run["ladder"].items():
            assert row["covers_tokens"] == coverage_tokens(int(key)), (
                f"rung {key}: label {row['covers_tokens']} != "
                f"derived {coverage_tokens(int(key))}"
            )
        # The filler is provenance, not a label — and it OVERSHOOTS, which is what made
        # borrowing it as a label wrong. Asserted so the distinction stays visible.
        assert run["filler_tokens"] >= POLICY_BOUND_TOKENS


@pytest.mark.xfail(
    reason="ADR-032 Correction 1 has not landed its re-measurement: the committed artifact is\n"
           "still the 52-rung pre-correction run",
    strict=True,
)
@pytest.mark.skipif(not ARTIFACT.exists(), reason="no published spike artifact")
def test_correction1_artifact_measures_the_corrected_bound_case() -> None:
    """The published artifact must be the re-measured one, not the pre-correction table.

    Guards the republication itself: an artifact whose top rung is 52 is the one the correction
    replaced, and re-rendering it would reproduce the withdrawn figure.
    """
    art = json.loads(ARTIFACT.read_text())
    for run in art["runs"]:
        rungs = {int(k) for k in run["ladder"]}
        assert 53 in rungs, f"artifact top rung is {max(rungs)}, expected the corrected 53"
        assert 52 not in rungs, "52-window rung is the withdrawn pre-correction measurement"
