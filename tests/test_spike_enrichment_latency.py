"""The 04 §2.2 enrichment-cap harness (`eval/spike_enrichment_latency.py`).

Two kinds of test, following `test_derivation_check.py`'s shape.

The **load-bearing** ones are negative: they fail if a guard becomes permissive. M-46's
lesson is that a green guard is not the same claim as a real percentile —
`_percentiles_are_distinct(40)` is True while the p99 it certifies has no sample above it —
so the two guards are pinned as *different* predicates. Fuse them, or drop reps back to the
spike family's 40, and these fail.

The **positive** one is the landing gate: the committed artifact must be citable. An
artifact measured from a dirty tree is reproducible from nothing, and one stamped above the
quiet ceiling is not citable at all (06 §8) — both were live defects in this harness's first
two runs, and neither is visible by reading the figures.

Imports are safe on an ml-less host: the harness defers every spaCy import into a function,
and `eval.spike_tier2_models` (imported for the older guard) pulls no heavy module at
module scope. Nothing here runs a measurement — timing under pytest would contend with the
suite, which is exactly what 06 §8 forbids.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from controlplane.detectors.entity_enricher import (  # noqa: E402
    BUDGET_MS,
    _sentence_window,
)
from eval.host_load import QUIET_LOAD1_MAX, is_quiet  # noqa: E402
from eval.spike_enrichment_latency import (  # noqa: E402
    DEFAULT_REPS,
    SPAN_COUNTS,
    _p99_resolves_off_the_max,
    _sentence,
)
from eval.spike_tier2_models import _percentiles_are_distinct  # noqa: E402

ARTIFACT = REPO / "reports" / "spike_enrichment_latency.json"
SUPERSEDED = REPO / "reports" / "spike_enrichment_latency.pre-correction.json"


# --- the fixture premise -------------------------------------------------------------

@pytest.mark.parametrize("spans", SPAN_COUNTS)
def test_every_span_yields_one_identical_whole_text_window(spans: int) -> None:
    """The premise that makes the curve an *aggregate* measurement.

    M-18 ruled the 10 ms a per-sentence aggregate, so the harness must put all k spans in
    ONE sentence: k spans then cost k NER passes over the same window, and the curve
    measures the budget being spent rather than k independent calls. If the synthetic text
    ever segments into several sentences, every figure still computes and silently describes
    a different quantity — so this is checked, not assumed.
    """
    text, signals = _sentence(spans)
    assert len(signals) == spans
    windows = {_sentence_window(text, s.span.start, s.span.end) for s in signals}
    assert len(windows) == 1, f"{spans} spans produced {len(windows)} distinct windows"
    assert windows.pop() == text


def test_the_sentence_grows_with_span_count() -> None:
    """Disclosed rather than hidden: the window IS the sentence, so k inflates it.

    This is why `enriched` can *fall* as k rises (fewer of the more-expensive windows fit
    the budget), and why the harness's sublinear check is conservative — its comparison
    value comes from the shortest window it measured.
    """
    lengths = [len(_sentence(k)[0]) for k in SPAN_COUNTS]
    assert lengths == sorted(lengths)
    assert lengths[0] < lengths[-1]


def test_spans_cover_the_figures_and_never_the_person() -> None:
    """Each span must sit on its own figure — a span over the name would enrich trivially."""
    text, signals = _sentence(4)
    for signal in signals:
        assert text[signal.span.start:signal.span.end].endswith("EUR")
    assert len({(s.span.start, s.span.end) for s in signals}) == 4


# --- the guards (negative: these fail if a guard goes permissive) ---------------------

def test_the_two_percentile_guards_are_different_questions() -> None:
    """M-46, pinned. n=40 passes the old guard while its p99 is unresolved from the max.

    `_percentiles_are_distinct` asks whether p95 and p99 land on different order
    statistics; `_p99_resolves_off_the_max` asks whether any sample exceeds the
    interpolated P99 rank. The first was the only check this repo had, and it certified a
    maximum. Fusing them would restore the blind spot.
    """
    assert _percentiles_are_distinct(40) is True
    assert _p99_resolves_off_the_max(40) is False


@pytest.mark.parametrize("n", [3, 10, 20, 40, 100])
def test_no_sample_exceeds_the_p99_rank_below_the_minimum(n: int) -> None:
    assert _p99_resolves_off_the_max(n) is False


def test_the_guard_minimum_is_101_searched_not_assumed() -> None:
    """101 is a property of the arithmetic; 200 is a margin choice on top of it.

    Pinned because the first version of this claim said 200 was the smallest qualifying
    size — true only of the three sizes that happened to be tried.
    """
    first = next(n for n in range(3, 2000) if _p99_resolves_off_the_max(n))
    assert first == 101


def test_default_reps_satisfy_both_guards() -> None:
    """A future reps reduction must not silently republish maxima as percentiles."""
    assert _percentiles_are_distinct(DEFAULT_REPS)
    assert _p99_resolves_off_the_max(DEFAULT_REPS)
    above = (DEFAULT_REPS - 1) - math.ceil(0.99 * (DEFAULT_REPS - 1))
    assert above >= 1


def test_the_round_defect_would_land_on_the_max() -> None:
    """The actual cause of the superseded artifact's identical p99/max columns.

    Kept as a test because the first correction of that artifact misattributed it to
    interpolation — arithmetic the defect did not come from. `round` lands on the top index
    at n=40; the truncation every other harness here uses never does, at any n.
    """
    assert int(round(0.99 * 39)) == 39
    assert int(0.99 * 39) == 38
    for n in (10, 20, 40, 100, 200, 300):
        assert int(0.99 * (n - 1)) != n - 1


# --- the landing gate (positive) ------------------------------------------------------

@pytest.mark.skipif(not ARTIFACT.exists(), reason="no artifact published yet")
def test_the_published_artifact_is_citable() -> None:
    """Clean tree and a quiet stamp — the two things figures cannot show about themselves."""
    artifact = json.loads(ARTIFACT.read_text())
    assert artifact["code"]["dirty"] is False, "measured from a working tree; reproducible from nothing"
    assert is_quiet(artifact["load_at_process_start"]) is True
    assert artifact.get("quiet_gate_timed_out") is False
    assert artifact["budget_ms"] == BUDGET_MS


@pytest.mark.skipif(not ARTIFACT.exists(), reason="no artifact published yet")
def test_every_published_row_carries_both_resolution_flags() -> None:
    artifact = json.loads(ARTIFACT.read_text())
    rows = [artifact["window"], *artifact["curve"]]
    for row in rows:
        assert row["percentiles_resolved"] is True
        assert row["p99_resolves_off_the_max"] is True
        assert row["n"] >= 101
        assert row.get("total_p99", row.get("p99")) <= row.get("total_max", row.get("max"))


@pytest.mark.skipif(not SUPERSEDED.exists(), reason="no superseded artifact")
def test_the_superseded_artifact_says_it_is_superseded() -> None:
    """Its figures are valid and its verdict is withdrawn; a reader must not have to infer that.

    The precedent file (`spike_window_latency.pre-correction-1.json`) carries no such
    marker, which is how a withdrawn verdict stays quotable.
    """
    marker = json.loads(SUPERSEDED.read_text())["superseded"]
    assert marker["verdict_is_withdrawn"] is True
    assert marker["by"].endswith("spike_enrichment_latency.json")
    assert "round" in marker["why"]


def test_the_quiet_ceiling_is_not_redefined_locally() -> None:
    """One definition of "quiet", shared. A local stricter threshold would fork the word."""
    import eval.spike_enrichment_latency as harness

    assert harness.QUIET_LOAD1_MAX is QUIET_LOAD1_MAX
