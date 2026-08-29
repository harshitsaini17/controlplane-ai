"""Tests for `eval/suggest_thresholds.py` — the 06 §3 threshold calibration harness.

**Why every test here stubs the scorer or uses synthetic scores.** This file pins the
*algebra* of calibration: the finite-sample quantile index, the AUC rank statistic, the
oracle ceiling, the inversion detection, and the refusal to apply anything. It deliberately
does not measure the detector — that is `eval.suggest_thresholds`' own job, run on a quiet
host (06 §8), and a unit test that loaded MiniLM would both be slow and contaminate any
measurement in flight. So no assertion here is a measurement, and none of them can be
satisfied by weakening a real result (AGENTS.md §5.4).

Two tests pin **published claims** rather than implementation details, and are the reason
this file exists at all: `test_the_inversion_survives_every_monotone_transform` and
`test_the_oracle_ceiling_is_a_ceiling`. SL-7 asserts in judge-facing text that the band
inversion is not an artifact of how non-conformity was defined and that no α could have
rescued it. Both of those are claims about the code, so both get a test.
"""

from __future__ import annotations

import math

import pytest

from eval.suggest_thresholds import (
    CALIBRATION_FILES,
    CALIBRATION_FRACTION,
    DEFAULT_ALPHA,
    RESHUFFLE_SEEDS,
    Band,
    Calibration,
    _auc,
    _band_from,
    _conformal_quantile,
    _oracle_band,
    calibrate,
    load_calibration_cases,
    main,
    proposed_diff,
)
import eval.suggest_thresholds as st


# --------------------------------------------------------------------------
# The finite-sample quantile index
# --------------------------------------------------------------------------


def test_the_index_is_the_conformal_one_not_the_plain_empirical_quantile() -> None:
    """`ceil((n+1)(1-α)) - 1`. At n=40, α=0.1 that is index 36, not 35.

    The uncorrected index would place τ_low a whole order statistic lower and so overstate
    how tight the band is — the docstring's claim, pinned.
    """
    values = [i / 100 for i in range(40)]
    assert len(values) == 40
    conformal = _conformal_quantile(values, 0.1, upper=True)
    plain = sorted(values)[math.ceil(40 * 0.9) - 1]
    assert conformal == sorted(values)[36]
    assert plain == sorted(values)[35]
    assert conformal != plain


def test_the_two_ends_are_different_ends() -> None:
    values = [i / 10 for i in range(11)]
    lower = _conformal_quantile(values, 0.1, upper=False)
    upper = _conformal_quantile(values, 0.1, upper=True)
    assert lower < upper


def test_an_empty_quantile_raises_rather_than_returning_zero() -> None:
    """A 0.0 threshold from no data is a fabricated number (AGENTS.md §7), not a default."""
    with pytest.raises(ValueError, match="undefined, not 0.0"):
        _conformal_quantile([], 0.1, upper=True)


def test_an_index_past_the_end_clamps_to_the_sample_extreme() -> None:
    """Small n cannot resolve an extreme rate. Clamping is reported by `spread`, not hidden."""
    assert _conformal_quantile([0.2, 0.4, 0.9], 0.001, upper=True) == 0.9
    assert _conformal_quantile([0.2, 0.4, 0.9], 0.001, upper=False) == 0.2


# --------------------------------------------------------------------------
# AUC — is the score informative at all?
# --------------------------------------------------------------------------


def test_auc_is_one_for_perfect_separation_and_half_for_all_ties() -> None:
    assert _auc([0.9, 0.8], [0.2, 0.1]) == 1.0
    assert _auc([0.5, 0.5], [0.5, 0.5]) == 0.5


def test_auc_counts_ties_as_half() -> None:
    # one pair strictly wins, one pair ties -> (1.0 + 0.5) / 2
    assert _auc([0.9], [0.9, 0.1]) == pytest.approx(0.75)


def test_auc_is_none_when_a_side_is_empty_rather_than_zero() -> None:
    assert _auc([], [0.1]) is None
    assert _auc([0.1], []) is None


# --------------------------------------------------------------------------
# The oracle ceiling
# --------------------------------------------------------------------------


def test_the_oracle_ceiling_is_a_ceiling() -> None:
    """It must reach 100% on a genuinely ordered set — otherwise it is not an upper bound,
    and SL-7's "no calibration could have beaten this" claim would rest on a broken search."""
    scored = (
        [("no", 0.1), ("no", 0.2)]
        + [("borderline", 0.5), ("borderline", 0.55)]
        + [("yes", 0.9), ("yes", 0.95)]
    )
    ok, total = _oracle_band(scored)
    assert (ok, total) == (6, 6)


def test_the_oracle_ceiling_is_below_total_when_the_middle_class_is_misplaced() -> None:
    """The measured structure in miniature: `borderline` sitting on top of `yes`.

    No band can place all six, so the ceiling must say so rather than reporting success.
    """
    scored = (
        [("no", 0.1), ("no", 0.2)]
        + [("borderline", 0.95), ("borderline", 0.97)]
        + [("yes", 0.5), ("yes", 0.55)]
    )
    ok, total = _oracle_band(scored)
    assert total == 6
    assert ok < 6


def test_the_oracle_beats_or_matches_every_calibrated_band_on_the_same_points() -> None:
    """The defining property of a ceiling. If a calibrated band ever scored higher, the
    oracle's search would be incomplete and the SL-7 bound would be wrong."""
    scored = [("no", i / 50) for i in range(20)]
    scored += [("borderline", 0.4 + i / 50) for i in range(10)]
    scored += [("yes", 0.9 + i / 500) for i in range(10)]
    ok, total = _oracle_band(scored)

    for seed in RESHUFFLE_SEEDS:
        band = _band_from(scored, DEFAULT_ALPHA, seed)
        hit = 0
        for label, s in scored:
            if label == "yes":
                hit += s >= band.tau_high
            elif label == "no":
                hit += s < band.tau_low
            else:
                hit += band.tau_low <= s < band.tau_high
        assert hit <= ok, f"seed {seed} beat the oracle: {hit} > {ok}"
    assert total == len(scored)


# --------------------------------------------------------------------------
# Band construction
# --------------------------------------------------------------------------


def test_a_well_ordered_corpus_produces_a_non_inverted_band() -> None:
    """The negative control. Without this, `inverted=True` could just mean "always True"."""
    scored = [("no", 0.05 + i / 200) for i in range(20)]
    scored += [("borderline", 0.45 + i / 200) for i in range(20)]
    scored += [("yes", 0.90 + i / 500) for i in range(20)]
    band = _band_from(scored, DEFAULT_ALPHA, 0)
    assert band.inverted is False
    assert band.tau_low < band.tau_high


def test_the_inversion_survives_every_monotone_transform() -> None:
    """SL-7 states the inversion "is invariant under any monotone transform of the score, so
    it is not an artifact of how non-conformity was defined." That is a claim about this
    code, so it is tested here rather than asserted in prose only.

    Both edges are order statistics of the sample, and a strictly increasing map preserves
    order — so it must preserve the inversion in both directions.
    """
    inverting = [("no", 0.1), ("no", 0.9), ("borderline", 0.95), ("yes", 0.5), ("yes", 0.6)]
    ordered = [("no", 0.1), ("no", 0.2), ("borderline", 0.5), ("yes", 0.9), ("yes", 0.95)]
    transforms = [
        lambda x: x**2,           # convex
        lambda x: math.sqrt(x),   # concave
        lambda x: (x + 1) / 2,    # affine
        lambda x: math.expm1(x),  # unbounded above
    ]
    for scored in (inverting, ordered):
        baseline = _band_from(scored, DEFAULT_ALPHA, 0).inverted
        for f in transforms:
            moved = [(lbl, f(s)) for lbl, s in scored]
            assert _band_from(moved, DEFAULT_ALPHA, 0).inverted is baseline


def test_the_split_is_stratified_so_no_class_can_vanish_from_calibration() -> None:
    """An unstratified shuffle can hand the calibration split zero `yes` cases, and τ_high
    would then be computed from nothing. `_conformal_quantile` raises on empty, so an
    unstratified implementation would crash at some seed instead of returning a band."""
    scored = [("no", i / 40) for i in range(40)]
    scored += [("borderline", 0.5)] * 4
    scored += [("yes", 0.9 + i / 100) for i in range(4)]
    for seed in RESHUFFLE_SEEDS:
        band = _band_from(scored, DEFAULT_ALPHA, seed)
        assert band.n_calibration > 0 and band.n_eval > 0


def test_borderline_places_neither_edge() -> None:
    """It is the held-out check that the band it should fall inside exists. If it moved an
    edge, the check would be circular."""
    base = [("no", i / 50) for i in range(20)] + [("yes", 0.9 + i / 500) for i in range(20)]
    without = _band_from(base, DEFAULT_ALPHA, 0)
    with_mid = _band_from(base + [("borderline", 0.5)] * 10, DEFAULT_ALPHA, 0)
    assert (without.tau_low, without.tau_high) == (with_mid.tau_low, with_mid.tau_high)


def test_achieved_overall_is_none_rather_than_zero_for_an_empty_eval_split() -> None:
    assert Band(0.1, 0.2, 0, 0).achieved_overall is None


# --------------------------------------------------------------------------
# The corpus gate
# --------------------------------------------------------------------------


def test_only_context_bearing_grounded_labelled_cases_are_loaded() -> None:
    """`rag_grounding` is context-gated (04 §2): a case with no context docs emits nothing,
    so including it would put a phantom point in the split."""
    cases = load_calibration_cases()
    assert cases, "the frozen corpus must supply calibration points"
    for case in cases:
        assert case["context"]
        assert case["grounded"] in {"yes", "no", "borderline"}


def test_the_corpus_is_the_two_documented_files() -> None:
    assert CALIBRATION_FILES == ("halluc.jsonl", "borderline.jsonl")


# --------------------------------------------------------------------------
# Refusal to apply, and the unloadable host
# --------------------------------------------------------------------------


def test_there_is_no_apply_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """04 §7 step 4 gives applying τ to a human, who also bumps `policy_version`. The
    absence is by construction, so it is pinned: an `--apply` flag must fail to parse."""
    with pytest.raises(SystemExit):
        main(["--apply"])
    assert "unrecognized arguments" in capsys.readouterr().err


def test_the_diff_says_it_is_not_applied_and_excludes_tau_route() -> None:
    cal = Calibration(alpha=0.1, band=Band(0.3, 0.7, 10, 5))
    text = "\n".join(proposed_diff(cal))
    assert "NOT APPLIED" in text
    assert "policy_version" in text
    assert "tau_route is NOT proposed" in text


def test_an_unloadable_host_is_an_absence_not_a_crash(monkeypatch) -> None:
    """ADR-033. `run_all` calls `calibrate()`, so raising here would take every accuracy
    figure in the eval report down with the model stack."""
    def boom(_cases):
        raise OSError("no model on this host")

    monkeypatch.setattr(st, "_score_cases", boom)
    cal = calibrate()
    assert cal.band is None
    assert "OSError" in cal.unavailable and "no model on this host" in cal.unavailable


def test_an_empty_score_set_is_reported_rather_than_divided_by(monkeypatch) -> None:
    monkeypatch.setattr(st, "_score_cases", lambda _cases: [])
    cal = calibrate()
    assert cal.band is None
    assert "no context-bearing calibration case" in cal.unavailable


def test_main_exits_nonzero_on_an_inverted_band(monkeypatch) -> None:
    """The inversion must be loud. Exiting 0 would let a schema-invalid band pass as a
    successful calibration run."""
    inverting = [("no", 0.9)] * 10 + [("yes", 0.4)] * 10 + [("borderline", 0.95)] * 4
    monkeypatch.setattr(st, "_score_cases", lambda _cases: inverting)
    assert main([]) == 1


def test_main_exits_zero_on_a_valid_band(monkeypatch) -> None:
    ordered = (
        [("no", i / 50) for i in range(20)]
        + [("borderline", 0.5 + i / 200) for i in range(10)]
        + [("yes", 0.9 + i / 500) for i in range(20)]
    )
    monkeypatch.setattr(st, "_score_cases", lambda _cases: ordered)
    assert main([]) == 0


def test_the_documented_defaults_are_the_ones_in_force() -> None:
    """M-52 resolved α with the conformal default and said so in the report. If the constant
    drifts, the report's stated α silently stops matching the computation."""
    assert DEFAULT_ALPHA == 0.10
    assert CALIBRATION_FRACTION == 0.70
    assert len(RESHUFFLE_SEEDS) >= 3
