"""Pins the REASONING of `contamination_signals`, including what it must NOT assert.

A measurement-quality check earns trust only by discriminating: one that fires on everything is
as useless as one that fires on nothing. So the load-bearing tests here are the negative ones —
the reproducible-but-odd shapes that must stay CLEAN. Two of them exist because a first version
of this check asserted them as defects and was wrong.

Synthetic runs rather than artifacts: the tolerances are host-specific, and CI runs on hosts that
never produced these numbers. The one test that does read a committed artifact asserts a finding
about that artifact, not a property of the host.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.spike_window_latency import contamination_signals

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
ARTIFACT = REPO / "reports" / "spike_window_latency.json"

TOP = 53
LADDER_RUNGS = (1, 2, 4, 8, 16, 32, TOP)


def _cell(p50: float, *, p99: float | None = None, cold: float | None = None) -> dict:
    return {
        "p50": p50,
        "p99": p99 if p99 is not None else p50 * 1.02,
        "cold_ms": cold if cold is not None else p50 * 1.05,
        "n": 40,
        "percentiles_resolved": True,
    }


def _run(*, seq_per_window=None, bat_per_window=None, curve_per_window=None) -> dict:
    """A synthetic 6-thread run that is CLEAN by construction, unless a callable perturbs it."""
    seq_per_window = seq_per_window or (lambda n: 11.5)
    bat_per_window = bat_per_window or (lambda n: 11.5)
    curve_per_window = curve_per_window or (lambda n: 11.5)
    return {
        "threads": 6,
        "reps": 40,
        "ladder": {
            str(n): {
                "windows": n,
                "covers_tokens": 102 + (n - 1) * 76,
                "sequential": _cell(seq_per_window(n) * n),
                "batched": _cell(bat_per_window(n) * n),
            }
            for n in LADDER_RUNGS
        },
        "batch_curve": {str(n): _cell(curve_per_window(n) * TOP) for n in LADDER_RUNGS},
    }


def test_a_clean_run_produces_no_signals() -> None:
    assert contamination_signals(_run()) == []


def test_sequential_per_window_growth_across_the_ladder_is_not_a_signal() -> None:
    """THE regression test for a false invariant this check once asserted.

    At 6 threads, per-window cost climbs ~11% from rung 1 to rung 53 in every run measured on
    this host — a rung feeding 53 distinct tensors has worse cache locality than one reusing a
    single tensor. Reproducible across three independent artifacts, therefore not a defect. A
    check that calls this contamination is asserting a derivation the measurement does not have.
    """
    climbing = _run(seq_per_window=lambda n: 11.33 + 1.22 * (LADDER_RUNGS.index(n) / 6))
    assert contamination_signals(climbing) == []


def test_batched_per_window_growth_with_batch_size_is_not_a_signal() -> None:
    """The batched column at rung `n` is ONE call at batch size `n`.

    Window count and batch size are the same axis there, so per-window cost rising with `n` is
    the batch-efficiency curve ADR-032 set out to measure. Real spread is 10.65 -> 15.10.
    """
    curve = dict(zip(LADDER_RUNGS, (11.46, 10.65, 10.94, 11.50, 12.89, 14.12, 15.10)))
    assert contamination_signals(
        _run(bat_per_window=curve.__getitem__, curve_per_window=curve.__getitem__)
    ) == []


def test_an_interior_local_spike_is_caught() -> None:
    """The signature of the contaminated publication run: 32w at +21% over its neighbours."""
    spiked = _run(seq_per_window=lambda n: 14.98 if n == 32 else 12.43)
    signals = contamination_signals(spiked)
    assert any(s.startswith("LOCAL SPIKE") and "32w" in s for s in signals), signals


def test_endpoint_rungs_are_a_documented_blind_spot() -> None:
    """LOCAL SPIKE compares against two neighbours, so the first and last rungs have none.

    Pinned as a limitation rather than fixed: inventing a one-sided rule for the endpoints would
    be a threshold with no evidence behind it. The endpoints are covered by CROSS-MEASUREMENT
    and COLD RATIO instead.
    """
    spiked = _run(seq_per_window=lambda n: 20.0 if n == TOP else 11.5)
    assert not [s for s in contamination_signals(spiked) if s.startswith("LOCAL SPIKE")]


def test_a_ladder_batched_rung_above_the_curve_is_attributed_to_the_ladder() -> None:
    over = _run(bat_per_window=lambda n: 15.17 if n == 16 else 11.5,
                curve_per_window=lambda n: 12.84 if n == 16 else 11.5)
    signals = [s for s in contamination_signals(over) if s.startswith("CROSS-MEASUREMENT")]
    assert any("16w" in s and "ladder-batched" in s.split("exceeds")[0] for s in signals), signals


def test_an_inflated_curve_point_is_attributed_to_the_curve_not_the_ladder() -> None:
    """Two-sidedness matters: the committed artifact's defect is an inflated curve, not a
    slow ladder. Across three artifacts the ladder's batched p50 agrees to ~2% while the
    curve's is what moves, so the direction of the excess decides who is blamed."""
    inflated = _run(curve_per_window=lambda n: 14.50 if n == 2 else 11.5)
    signals = [s for s in contamination_signals(inflated) if s.startswith("CROSS-MEASUREMENT")]
    assert any("batch_curve" in s.split("exceeds")[0] and "2w" in s for s in signals), signals


def test_the_expected_curve_deficit_at_low_batch_is_not_a_signal() -> None:
    """A systematic negative offset is EXPECTED — the curve's p50 covers a full top-rung sweep
    including remainder handling, the ladder's a single call. Clean runs show -8.5%..-3.3%."""
    assert contamination_signals(
        _run(bat_per_window=lambda n: 11.46, curve_per_window=lambda n: 12.53)
    ) == []


def test_the_cold_ratio_floor_is_empirical_not_physical() -> None:
    """`cold_ms >= p50` LOOKS like a law and is not one: thermal and frequency drift over the
    reps lifts the median above the first call, and clean artifacts here bottom out at 0.926.
    Asserting the law would fire on every artifact in the repo. So 0.926 must pass while the
    known-bad 0.800 must not."""
    ladder_key = str(LADDER_RUNGS[1])

    clean = _run()
    cell = clean["ladder"][ladder_key]["sequential"]
    cell["cold_ms"] = cell["p50"] * 0.926
    assert not [s for s in contamination_signals(clean) if s.startswith("COLD RATIO")]

    dirty = _run()
    dirty["batch_curve"]["2"]["cold_ms"] = dirty["batch_curve"]["2"]["p50"] * 0.800
    assert any(s.startswith("COLD RATIO") for s in contamination_signals(dirty))


def test_tail_dispersion_is_declared_weak_and_behaves_that_way() -> None:
    """It did NOT catch the contaminated run (1.245 against a 1.25 threshold), and clean runs
    reach 1.191. Pinned so nobody later reads it as a working discriminator: 1.245 passes."""
    near_miss = _run()
    cell = near_miss["ladder"]["16"]["sequential"]
    cell["p99"] = cell["p50"] * 1.245
    assert not [s for s in contamination_signals(near_miss) if s.startswith("TAIL DISPERSION")]

    gross = _run()
    cell = gross["ladder"]["16"]["sequential"]
    cell["p99"] = cell["p50"] * 1.60
    assert any(s.startswith("TAIL DISPERSION") for s in contamination_signals(gross))


def test_the_check_discriminates_on_real_artifacts_not_only_synthetic_ones() -> None:
    """Both directions, on real measurements: the contaminated run is flagged, the clean one is not.

    The synthetic tests above pin the reasoning; this one pins that the *thresholds* survive
    contact with real data, which synthetic input cannot establish — every tolerance here was
    chosen by looking at artifacts, so a check that only ever sees constructed runs has never
    been tested against the thing it was built to catch.

    TWO dirty fixtures, because the two real contaminations found so far have disjoint
    signatures — one in the batch curve, one in the ladder. A check that caught either alone
    would look healthy against a single fixture, and an earlier version of this test asserted
    the ladder's signature against the batch curve's file, which is how that was noticed.

    All three sides are fixtures rather than live artifacts. `reports/` holds transient state:
    it changes with every republication, and a test pinned to it asserts a property of whatever
    happens to be checked in today.
    """
    dirty_curve = json.loads((FIXTURES / "spike_dirty_batch_curve_2026-08-29.json").read_text())
    six = next(r for r in dirty_curve["runs"] if r["threads"] == 6)
    signals = contamination_signals(six)
    assert any(s.startswith("COLD RATIO") and "batch_curve/2" in s for s in signals), signals
    assert any(s.startswith("CROSS-MEASUREMENT") and "2w" in s for s in signals), signals

    dirty_ladder = json.loads((FIXTURES / "spike_dirty_ladder_2026-08-29.json").read_text())
    six = next(r for r in dirty_ladder["runs"] if r["threads"] == 6)
    signals = contamination_signals(six)
    assert any(s.startswith("LOCAL SPIKE") and "32w" in s for s in signals), signals
    assert any(s.startswith("CROSS-MEASUREMENT") and "16w" in s for s in signals), signals

    clean = json.loads((FIXTURES / "spike_clean_2026-08-29.json").read_text())
    for run in clean["runs"]:
        assert contamination_signals(run) == [], (
            f"a real clean run is flagged at {run['threads']} threads — the thresholds do not "
            f"survive contact with ordinary measurement noise: {contamination_signals(run)}"
        )


@pytest.mark.xfail(
    reason="ADR-032 Correction 1 has not landed its re-measurement. The committed artifact passes "
           "`contamination_signals` but carries neither a load nor a code stamp, and is still the "
           "52-rung pre-correction run whose four largest rungs cannot resolve a P99",
    strict=True,
)
def test_landing_gate_the_published_artifact_is_clean() -> None:
    """The gate Correction 1 must satisfy. `strict=True`, so it fails loudly the moment the
    clean artifact lands and stops being an xfail — at which point the test above is deleted."""
    art = json.loads(ARTIFACT.read_text())
    assert art.get("load_at_process_start", {}).get("cpus") is not None
    for run in art["runs"]:
        assert contamination_signals(run) == [], (run["threads"], contamination_signals(run))
