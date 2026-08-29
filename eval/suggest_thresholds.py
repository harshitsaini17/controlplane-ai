"""Threshold calibration (04 §7 step 3, 06 §3) — proposes a YAML diff, never applies one.

Computes τ_low / τ_high as conformal-style quantiles over non-conformity scores from the
labeled set, and reports the achieved-vs-target rate on a held-out split. `python -m
eval.suggest_thresholds` prints the proposed diff; `eval.run_all` imports `calibrate()` to
render the report's *Threshold calibration* section, so there is one implementation rather
than two.

**This module writes no YAML, by construction** — 04 §7 step 4 is "Human applies diff →
`policy_version` bump" and ADR-016 makes `policies/*.yaml` the normative source. There is no
`--apply` flag to add later: the absence is the control.

## What the ground truth is

06 §3's field table defines `grounded` as *the band the confidence score should land in* —
`yes` ≥ τ_high (nothing fires), `borderline` inside `[τ_low, τ_high)`, `no` < τ_low. That makes
the corpus directly a calibration set for a two-sided band, with no derived proxy in between.
Scores come from `rag_grounding`, which since SL-6 cut `fast_consistency` is the only
confidence-kind detector (ADR-012) and therefore the only source of a score to calibrate.

## Why one shared τ pair rather than three

`rag_grounding` reads no `detector_params` and the `grounded` labels are policy-independent, so
the score distribution is identical for all three use cases — per-policy calibration would
partition 78 points into ~39/17/22 and return three noisier estimates of the same quantity.
04 §7 step 3's "the policy's target rate" is honoured by α, not by splitting the data. This also
keeps `tests/test_policy_matrix.py::test_shared_band_refuses_to_synthesize_across_diverged_taus`
on its documented premise instead of retiring a caption the docs still make.

## What is NOT calibrated here

`tau_route` is ADR-009's cascade threshold — the confidence below which a request escalates to
the frontier tier. It is a different quantity from grounding, measured on a different signal,
and no corpus field carries its ground truth. It stays `# SEED(pre-calibration)` and the report
says so; silently emitting a calibrated-looking value for it would be the worse failure.

## The claim this makes, and the one it does not

ADR-005 exists because Round 1 called this "mathematical guarantees" over the wrong citation.
The finite-sample correction below is the standard conformal one, but a coverage *guarantee*
needs exchangeability between the calibration split and deployment traffic — and this corpus is
synthetic, authored, and 78 points deep. So: the numbers are a defensible calibration procedure
run honestly on a small labeled set, reported with the caveats 06 §3 makes mandatory. They are
not a guarantee, and nothing here should be quoted as one.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: 06 §3: "70/30 split of `halluc.jsonl` + `borderline.jsonl`".
CALIBRATION_FILES = ("halluc.jsonl", "borderline.jsonl")
CALIBRATION_FRACTION = 0.70

#: Target miss rate per band edge. **M-52: 04 §7 step 3 calibrates "at the policy's target
#: rate" and no such field exists** — not in `Thresholds`, not in any policy YAML, nowhere in
#: 04/05/06. Resolved MINOR-style per AGENTS.md §11.1 with the conventional conformal default,
#: applied uniformly and stated in the report rather than buried here.
#:
#: Deliberately NOT added to the policy schema: a new `Thresholds` field is a contract change,
#: which §11.1 says needs an ADR, and the conservative resolution of an undefined term is not
#: to invent a contract for it. A flag instead, so the value is visible at the call site.
DEFAULT_ALPHA = 0.10

#: Reshuffles for the mandatory small-n variance note (06 §3: "a bootstrap CI or min/max over
#: 5 reshuffles"). Seeds are fixed and listed so the interval is reproducible rather than
#: merely reported — an unseeded interval cannot be checked by a reader.
RESHUFFLE_SEEDS = (0, 1, 2, 3, 4)

#: α values swept for the report's α-dependence diagnostic. This is NOT a menu to select
#: from: α is fixed at DEFAULT_ALPHA by M-52, chosen before any score was seen. Picking the α
#: that happens to un-invert the band would be tuning a parameter toward a desired outcome
#: (AGENTS.md §7, §11.1 item 3). It is swept so the report can state whether the inversion is
#: α-dependent instead of guessing, and so a reader can see what the alternative would cost.
ALPHA_SWEEP = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50)

DATASET_DIR = Path(__file__).resolve().parent / "dataset"


@dataclass
class Band:
    """One (τ_low, τ_high) proposal plus what it achieved on the held-out split."""

    tau_low: float
    tau_high: float
    n_calibration: int
    n_eval: int
    #: Per-class achieved rates on the eval split: fraction landing in the band 06 §3 expects.
    achieved: dict[str, tuple[int, int]] = field(default_factory=dict)
    inverted: bool = False

    @property
    def achieved_overall(self) -> float | None:
        ok = sum(hit for hit, _ in self.achieved.values())
        tot = sum(tot for _, tot in self.achieved.values())
        return ok / tot if tot else None


@dataclass
class Calibration:
    """Everything the report needs. `unavailable` set means nothing else is populated."""

    alpha: float
    band: Band | None = None
    spread: dict[str, tuple[float, float]] = field(default_factory=dict)
    score_summary: dict[str, dict[str, float | int]] = field(default_factory=dict)
    #: AUC(`yes` vs `no`) — does the score separate the two OUTER classes at all?
    auc: float | None = None
    #: Per-α diagnostic: [(alpha, tau_low, tau_high, inverted, in_band, total)].
    alpha_sweep: list[tuple[float, float, float, bool, int, int]] = field(default_factory=list)
    #: Tail-overlap figures — the actual mechanism behind an inversion. Keys:
    #: yes_min, no_max, no_at_or_above_tau_high, yes_below_tau_low, plus the two denominators.
    overlap: dict[str, float | int] = field(default_factory=dict)
    #: (inverted, total) over RESHUFFLE_SEEDS. The report claims the inversion is not one
    #: unlucky split, so that claim is counted here rather than inferred from `spread`
    #: (min/max of the two edges cannot express "every seed inverted" in general).
    inverted_seeds: tuple[int, int] | None = None
    #: (correct, total) for the best band fittable on ALL points with labels visible.
    #: No calibration can beat this, so it separates "τ was placed badly" from "no τ works".
    oracle: tuple[int, int] | None = None
    unavailable: str = ""


def _conformal_quantile(values: Sequence[float], alpha: float, *, upper: bool) -> float:
    """Finite-sample-corrected empirical quantile (the standard conformal index).

    `upper=True` returns the (1-α) end — the threshold a `no` score must stay below.
    `upper=False` returns the α end — the threshold a `yes` score must stay at or above.

    The `ceil((n+1)(1-α))` index, not the plain empirical quantile: at n≈40 the difference is a
    whole order statistic, and using the uncorrected one would overstate how tight the band is.
    Clamped to the sample's own extremes, because an index past the end means "this n cannot
    resolve that rate" — reported by `spread`, not smoothed over here.
    """
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        raise ValueError("no calibration scores: an empty quantile is undefined, not 0.0")
    rate = (1.0 - alpha) if upper else alpha
    idx = math.ceil((n + 1) * rate) - 1
    return ordered[min(max(idx, 0), n - 1)]


def load_calibration_cases(dataset_dir: Path = DATASET_DIR) -> list[dict[str, Any]]:
    """The 06 §3 calibration corpus: `halluc` + `borderline`, context-bearing cases only.

    A case without context docs is dropped because `rag_grounding` is context-gated (04 §2) and
    would emit nothing for it — including it would put a phantom point in the split. The count
    dropped is reported rather than silently absorbed.
    """
    cases: list[dict[str, Any]] = []
    for name in CALIBRATION_FILES:
        for line in (dataset_dir / name).read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("context") and row.get("grounded") in {"yes", "no", "borderline"}:
                cases.append(row)
    return cases


def _score_cases(cases: Sequence[dict[str, Any]]) -> list[tuple[str, float]]:
    """`[(grounded, score)]` from the live detector. Raises if it cannot load."""
    import asyncio

    from controlplane.detectors import rag_grounding as rg
    from controlplane.detectors.base import DetectorContext, Stage

    async def run() -> list[tuple[str, float]]:
        await rg.warm()
        out = []
        for case in cases:
            ctx = DetectorContext(
                text=case["text"],
                stage=Stage.OUTPUT_SENTENCE,
                context_docs=list(case["context"]),
            )
            signals = await rg.rag_grounding.detect(ctx)
            if signals:
                out.append((case["grounded"], signals[0].score))
        return out

    return asyncio.run(run())


def _auc(pos: Sequence[float], neg: Sequence[float]) -> float | None:
    """AUC(`yes` vs `no`) as the rank statistic, ties at 0.5.

    Reported because it answers a question the band cannot: whether the inversion means the
    score is uninformative, or means it is informative and the MIDDLE class sits in the
    wrong place. Those have different fixes and only one of them is a threshold problem.
    """
    if not pos or not neg:
        return None
    wins = sum(
        1.0 if a > b else 0.5 if a == b else 0.0 for a in pos for b in neg
    )
    return wins / (len(pos) * len(neg))


def _in_band(scored: Sequence[tuple[str, float]], tau_low: float, tau_high: float) -> int:
    """How many points land in the band 06 line 85 expects for their class.

    Shared by the α sweep and the oracle so the two are commensurable — a ceiling measured
    by a different rule than the thing it bounds would not be a ceiling.
    """
    ok = 0
    for label, s in scored:
        if label == "yes":
            ok += s >= tau_high
        elif label == "no":
            ok += s < tau_low
        else:
            ok += tau_low <= s < tau_high
    return ok


def _oracle_band(scored: Sequence[tuple[str, float]]) -> tuple[int, int]:
    """The best band achievable with every label visible, by exhaustive search.

    This is a CEILING, not a proposal: it cheats by fitting on the same points it scores, so
    it is not a τ anyone may apply. Its only job is to bound what calibration could possibly
    have achieved — if the ceiling is low, no split, seed or α would have rescued the band,
    and the limitation is the score rather than the quantile.
    """
    cuts = sorted({s for _, s in scored})
    edges = [cuts[0] - 1e-9] + [(a + b) / 2 for a, b in zip(cuts, cuts[1:])] + [cuts[-1] + 1e-9]
    best = 0
    for lo in edges:
        for hi in edges:
            if lo >= hi:
                continue
            best = max(best, _in_band(scored, lo, hi))
    return best, len(scored)


def _band_from(scored: Sequence[tuple[str, float]], alpha: float, seed: int) -> Band:
    """One 70/30 shuffle → one band, plus its achieved rates on the held-out 30%.

    Stratified by `grounded`, so a shuffle cannot leave the calibration split with no `yes`
    cases and a τ_high computed from nothing.
    """
    by_class: dict[str, list[float]] = {}
    for label, score in scored:
        by_class.setdefault(label, []).append(score)

    cal: dict[str, list[float]] = {}
    ev: dict[str, list[float]] = {}
    rng = random.Random(seed)
    for label, scores in by_class.items():
        shuffled = list(scores)
        rng.shuffle(shuffled)
        cut = round(len(shuffled) * CALIBRATION_FRACTION)
        cal[label], ev[label] = shuffled[:cut], shuffled[cut:]

    # τ_high from the `yes` cases (they must land at or above it); τ_low from the `no` cases
    # (they must land below it). `borderline` is not used to place either edge — it is the
    # held-out check that the band it should fall inside actually exists.
    tau_high = _conformal_quantile(cal.get("yes", []), alpha, upper=False)
    tau_low = _conformal_quantile(cal.get("no", []), alpha, upper=True)

    band = Band(
        tau_low=round(tau_low, 4),
        tau_high=round(tau_high, 4),
        n_calibration=sum(len(v) for v in cal.values()),
        n_eval=sum(len(v) for v in ev.values()),
        inverted=tau_low >= tau_high,
    )
    for label, scores in sorted(ev.items()):
        if label == "yes":
            hit = sum(1 for s in scores if s >= band.tau_high)
        elif label == "no":
            hit = sum(1 for s in scores if s < band.tau_low)
        else:
            hit = sum(1 for s in scores if band.tau_low <= s < band.tau_high)
        band.achieved[label] = (hit, len(scores))
    return band


def calibrate(
    alpha: float = DEFAULT_ALPHA, dataset_dir: Path = DATASET_DIR
) -> Calibration:
    """Full calibration. Never raises for an unloadable host — returns `unavailable` instead.

    The primary band comes from `RESHUFFLE_SEEDS[0]`; the rest give the mandatory small-n
    spread. Reporting the first seed rather than an average of five is deliberate: an averaged
    τ is not any shuffle's quantile, and the spread is the honest statement of how much the
    choice of shuffle moves it.
    """
    cases = load_calibration_cases(dataset_dir)
    try:
        scored = _score_cases(cases)
    except Exception as exc:  # ADR-033: unloadable host is an absence, not a failure
        return Calibration(alpha=alpha, unavailable=f"{type(exc).__name__}: {exc}")

    if not scored:
        return Calibration(
            alpha=alpha,
            unavailable="no context-bearing calibration case produced a score",
        )

    result = Calibration(alpha=alpha)
    for label in sorted({label for label, _ in scored}):
        vals = sorted(s for lbl, s in scored if lbl == label)
        result.score_summary[label] = {
            "n": len(vals),
            "min": round(vals[0], 4),
            "median": round(vals[len(vals) // 2], 4),
            "max": round(vals[-1], 4),
        }

    result.auc = _auc(
        [s for lbl, s in scored if lbl == "yes"],
        [s for lbl, s in scored if lbl == "no"],
    )
    result.oracle = _oracle_band(scored)

    bands = [_band_from(scored, alpha, seed) for seed in RESHUFFLE_SEEDS]
    result.band = bands[0]
    ys = [s for lbl, s in scored if lbl == "yes"]
    ns = [s for lbl, s in scored if lbl == "no"]
    if ys and ns:
        for a in ALPHA_SWEEP:
            th = _conformal_quantile(ys, a, upper=False)
            tl = _conformal_quantile(ns, a, upper=True)
            result.alpha_sweep.append(
                (a, round(tl, 4), round(th, 4), tl >= th, _in_band(scored, tl, th), len(scored))
            )
        th0 = _conformal_quantile(ys, alpha, upper=False)
        tl0 = _conformal_quantile(ns, alpha, upper=True)
        result.overlap = {
            "yes_min": round(min(ys), 4),
            "yes_n": len(ys),
            "no_max": round(max(ns), 4),
            "no_n": len(ns),
            "no_at_or_above_tau_high": sum(1 for s in ns if s >= th0),
            "yes_below_tau_low": sum(1 for s in ys if s < tl0),
        }

    result.inverted_seeds = (sum(1 for b in bands if b.inverted), len(bands))
    result.spread = {
        "tau_low": (min(b.tau_low for b in bands), max(b.tau_low for b in bands)),
        "tau_high": (min(b.tau_high for b in bands), max(b.tau_high for b in bands)),
    }
    return result


def proposed_diff(cal: Calibration, policy_dir: Path = Path("policies")) -> list[str]:
    """The 04 §7 step 3 deliverable: a diff a human may choose to apply."""
    if cal.band is None:
        return [f"NOT COMPUTED — {cal.unavailable}"]
    out = [
        f"# proposed by `python -m eval.suggest_thresholds` (04 §7 step 3) at alpha={cal.alpha}",
        "# NOT APPLIED. 04 §7 step 4: a human applies this and bumps `policy_version`.",
        f"# tau_route is NOT proposed — ADR-009's cascade threshold, not a grounding quantity.",
        "",
    ]
    for path in sorted(policy_dir.glob("*.yaml")):
        out += [
            f"--- {path}",
            f"-  tau_low: <seed>",
            f"+  tau_low: {cal.band.tau_low}",
            f"-  tau_high: <seed>",
            f"+  tau_high: {cal.band.tau_high}",
            "",
        ]
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--alpha", type=float, default=DEFAULT_ALPHA,
                        help=f"target miss rate per band edge (default {DEFAULT_ALPHA}; M-52)")
    parser.add_argument("--dataset-dir", type=Path, default=DATASET_DIR)
    args = parser.parse_args(argv)

    cal = calibrate(args.alpha, args.dataset_dir)
    print("\n".join(proposed_diff(cal)))
    if cal.band is None:
        return 1
    if cal.band.inverted:
        print(f"\nINVERTED: tau_low {cal.band.tau_low} >= tau_high {cal.band.tau_high} — "
              "the schema rejects this band; it is reported, not clamped.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
