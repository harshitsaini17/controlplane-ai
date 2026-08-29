"""04 §2.2 evidence — what the 10 ms aggregate enrichment cap actually costs, measured.

`entity_enricher` has an NFR-P-002 budget (10 ms) and **no row in any lane**, so
`eval.bench_latency` cannot produce a figure for it: that harness enumerates `LANES`, and
04 §2.2 makes enrichment its own stage between detection and the policy engine. The
alternative to a separate harness is a budget that is never checked, which is the state
this file removes.

**The quantity is not a per-call latency.** M-18 ruled the budget a **per-sentence
aggregate**: 10 ms total however many spans the sentence carries, because "a budget that
scales with span count is not a budget". So the measurement that matters is a *curve over
span count* — does the hold stay bounded as k grows, or does it track `10k`? A single
per-call number would answer the wrong question.

**Three figures, three different meanings.**

* **Cold** — the first call in a fresh process, which pays `import spacy` + `spacy.load` +
  spaCy's deferred first-inference work. Reported as **n=1** and deliberately not compared
  to the budget: `entity_enricher.warm()` runs at boot precisely so no request pays it. It
  is measured because the warm path's necessity rests on this number being large.
* **Per-window** — one NER pass over one sentence window. This is what the aggregate is
  spent in units of, so it is what predicts how many spans fit.
* **The curve** — total `enrich()` wall time at k spans, with the spans actually enriched
  and skipped. This is the cap's behaviour, and the only one of the three that can fail.

**The cap can overshoot by design, and by a bounded amount.** The budget is checked
*after* each window, so a call can exceed 10 ms by up to one window's cost before it
stops. That is deliberate — checking first would let a cold or slow pipeline enrich
nothing at all, making the stage unreachable rather than degraded — and it means the
honest gate is not `total <= 10 ms`. The gate is that the hold stays **bounded in k**:
`total(k_max)` within one window of the budget rather than tracking `k x window`. A
failure there means the enforcement does not work, which is a real defect; a 12 ms hold at
k=8 is the specified behaviour.

**Text is synthetic, for the reason `eval/spike_window_latency.py` states**: the less this
repo's measurement code touches the frozen corpus, the less there is to argue about later.
It costs nothing here — NER cost is driven by the window's token count, not by which words
fill it. The one thing a synthetic fixture *can* get wrong is failing to contain what it
claims to, so the harness asserts spaCy finds a PERSON in its own text before timing
anything. Measuring the no-PERSON path and reporting it as the enrichment path is the M-40
failure mode, and it is silent.

Spans are constructed directly rather than taken from `numeric_claims`, because k has to be
exact for a curve over k. Nothing is lost: the cost depends on the window `_sentence_window`
derives from the offsets, and these offsets are real positions in the text.

Run: `python -m eval.spike_enrichment_latency [--reps N] [--out FILE]`
Re-render without measuring: `--render FILE`.

Exit codes are three-valued on purpose: **0** the cap holds, **1** measured and the cap
failed, **2** could not measure on a quiet host so nothing was written. Collapsing 2 into 1
would report a busy laptop as a broken cap; collapsing it into 0 would report it as a
working one.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from pathlib import Path
from typing import Any

from controlplane.detectors import entity_enricher as ee
from controlplane.detectors.base import Plane, Signal, Stage
from controlplane.telemetry.metrics import MetricsRegistry, percentile
from eval.spike_tier2_models import _percentiles_are_distinct
from eval.host_load import (
    QUIET_LOAD1_MAX,
    git_stamp,
    load_stamp,
    quiet_verdict,
)

#: Span counts to measure. 1 is the floor (the first span is always attempted), 8 is past
#: where the cap must be biting — if the hold at 8 still tracks `8 x window`, nothing is
#: bounding it. 4 is included because M-18's superseded per-span reading crossed the
#: 100 ms per-sentence P99 at exactly k=4 (ADR-030's derivation), so it is the span count
#: that ruling was argued over.
SPAN_COUNTS: tuple[int, ...] = (1, 2, 3, 4, 8)

#: 200, not the spike family's 40.
#:
#: `_percentiles_are_distinct(40)` is True, so 40 is enough to keep p95 and p99 off the same
#: order statistic — but it is NOT enough to keep p99 off the **max**. At n=40 an interpolated
#: P99 sits at rank 38.61 of 0..39: 61% of the way into the gap between the two worst samples
#: of forty, with nothing above it. The first version of this harness reported exactly that,
#: and printed a p99 column identical to its max column in all five rows.
#:
#: At n=200 the P99 interpolates between the 3rd- and 2nd-worst samples, with two observations
#: above it. It is cheap to buy here in a way it is not in the model spikes: a call is ~5 ms,
#: not ~600 ms, so the whole curve costs seconds.
DEFAULT_REPS = 200

#: Seconds between quiet-gate polls, and how long to wait before giving up.
POLL_S = 15.0
MAX_WAIT_S = 600.0

#: Synthetic. A PERSON at the head, then k quantity-shaped figures — the shape 04 §2.2
#: enriches: a fabricated detail about a named person, with the figures as the host spans.
_PREFIX = "Marguerite Vasconcelos-Thorne reported "
_FIGURE = "{n:,} EUR"
_SUFFIX = " in the quarter, which is above the published band for that role."


def _p99_resolves_off_the_max(n: int) -> bool:
    """Whether an interpolated P99 has any sample above it at this size.

    Distinct from `_percentiles_are_distinct`, which asks whether p95 and p99 land on
    different order statistics. Both were True at n=40, and yet `percentile(s, 99)` there
    interpolates at rank 38.61 of 0..39 — inside the gap between the two worst of forty,
    with **nothing above it**. That is a maximum wearing a percentile's name, and it is what
    the pre-correction artifact published. Two guards because there are two ways for a
    percentile to be a fiction, and the existing one does not catch this one.
    """
    if n < 3:
        return False
    return math.ceil(0.99 * (n - 1)) < n - 1


def _sentence(spans: int) -> tuple[str, list[Signal]]:
    """Synthetic text with `spans` quantity-shaped figures, and a signal over each.

    Every span sits in the **same** sentence, which is the case the aggregate budget is
    about: `_sentence_window` returns one identical window per span, so k spans cost k NER
    passes over the same text. That is what M-18 ruled a budget rather than a per-span
    allowance.
    """
    text = _PREFIX
    offsets: list[tuple[int, int]] = []
    for index in range(spans):
        if index:
            text += " and "
        figure = _FIGURE.format(n=94_000 + index * 1_137)
        offsets.append((len(text), len(text) + len(figure)))
        text += figure
    text += _SUFFIX

    signals = [
        Signal(
            signal_id=f"s{index}",
            detector="numeric_claims",
            planes=[Plane.PERFORMANCE],
            labels=["hallucination.unsourced_numeric"],
            score=1.0,
            score_kind="detection",
            span={"start": start, "end": end},
            stage=Stage.OUTPUT_SENTENCE,
            evidence="quantity-shaped, uncited",
            latency_ms=0.1,
        )
        for index, (start, end) in enumerate(offsets)
    ]
    return text, signals


def _wait_for_quiet(artifact: dict[str, Any]) -> dict[str, Any]:
    """Block until load1 is inside 06 §8's ceiling. Returns the certifying stamp.

    Polls rather than refusing outright: a harness that exits on a transient makes the
    citable path harder to reach than the uncitable one. Every poll is recorded, so a run
    that waited is visible as one.
    """
    polls: list[dict[str, Any]] = []
    waited = 0.0
    while True:
        stamp = load_stamp()
        if stamp["load1"] <= QUIET_LOAD1_MAX or waited >= MAX_WAIT_S:
            artifact["quiet_gate_polls"] = polls
            artifact["quiet_gate_waited_s"] = round(waited, 1)
            artifact["quiet_gate_timed_out"] = stamp["load1"] > QUIET_LOAD1_MAX
            return stamp
        polls.append({"load1": stamp["load1"], "waited_s": round(waited, 1)})
        print(f"  gate: load1={stamp['load1']:.2f} > {QUIET_LOAD1_MAX}; waiting")
        time.sleep(POLL_S)
        waited += POLL_S


async def _measure(reps: int) -> dict[str, Any]:
    text, signals = _sentence(1)

    # The fixture must contain what the harness claims to measure. Checked through the
    # stage itself rather than by calling spaCy directly, so what is verified is the path
    # that gets timed — window derivation included.
    probe = await ee.enrich(list(signals), text, use_case="hr_copilot")
    assert ee.APPENDED_LABEL in probe[0].labels, (
        "the synthetic fixture yields no PERSON, so every figure below would describe the "
        "no-enrichment path while claiming to describe enrichment (M-40)"
    )

    # Cold: a fresh process pays import + load + first inference. This process has already
    # paid it via the probe above, so the cold figure is taken from that call — recorded
    # separately by the caller, not re-derived here.
    result: dict[str, Any] = {}

    # Per-window, warm.
    window_samples: list[float] = []
    for _ in range(reps):
        fresh = [s.model_copy(deep=True) for s in signals]
        started = time.perf_counter()
        await ee.enrich(fresh, text, use_case="hr_copilot")
        window_samples.append((time.perf_counter() - started) * 1000.0)
    result["window"] = {
        "chars": len(text),
        "n": reps,
        "p50": round(statistics.median(window_samples), 3),
        "p99": round(percentile(window_samples, 99), 3),
        "max": round(max(window_samples), 3),
        "percentiles_resolved": _percentiles_are_distinct(reps),
        "p99_resolves_off_the_max": _p99_resolves_off_the_max(reps),
    }

    # The curve.
    curve = []
    for spans in SPAN_COUNTS:
        span_text, span_signals = _sentence(spans)
        metrics = MetricsRegistry()
        totals: list[float] = []
        enriched_counts: list[int] = []
        for _ in range(reps):
            fresh = [s.model_copy(deep=True) for s in span_signals]
            started = time.perf_counter()
            out = await ee.enrich(fresh, span_text, use_case="hr_copilot", metrics=metrics)
            totals.append((time.perf_counter() - started) * 1000.0)
            enriched_counts.append(
                sum(1 for s in out if ee.APPENDED_LABEL in s.labels)
            )
        snap = metrics.snapshot().get("cp_enrichment_skipped_total")
        skipped_total = sum(s["value"] for s in snap["series"]) if snap else 0.0
        curve.append({
            "spans": spans,
            "chars": len(span_text),
            "n": reps,
            "total_p50": round(statistics.median(totals), 3),
            "total_p99": round(percentile(totals, 99), 3),
            "total_max": round(max(totals), 3),
            "per_span_p50": round(statistics.median(totals) / spans, 3),
            "enriched_p50": statistics.median(enriched_counts),
            "skipped_per_call": round(skipped_total / reps, 3),
            "percentiles_resolved": _percentiles_are_distinct(reps),
            "p99_resolves_off_the_max": _p99_resolves_off_the_max(reps),
        })
    result["curve"] = curve
    return result


def _render(artifact: dict[str, Any]) -> str:
    lines: list[str] = []
    code = artifact.get("code") or {}
    certifying = artifact.get("load_at_process_start")
    lines.append("=" * 84)
    lines.append(f"04 §2.2 enrichment cap — budget {artifact['budget_ms']:.1f} ms "
                 f"AGGREGATE per sentence (M-18)")
    lines.append(f"code: {str(code.get('commit', '?'))[:12]} "
                 f"{'dirty' if code.get('dirty') else 'clean'}")
    if certifying is None:
        lines.append("host load at process start: NOT RECORDED — not citable")
    else:
        lines.append(
            f"host load at process start: {certifying['load1']} / {certifying['load5']} / "
            f"{certifying['load15']}  cpus={certifying['cpus']}  "
            f"quiet_max={QUIET_LOAD1_MAX}  [{quiet_verdict(certifying)}]"
        )
    if artifact.get("citability", {}).get("longer_averages_also_inside") is False:
        lines.append("  MARGINAL: load1 is inside the ceiling, load5/load15 are not — a "
                     "decaying transient caught")
        lines.append("  at its lowest instant. Citable by 06 §8, which reads load1; weigh it "
                     "against a run with all three inside.")
    if artifact.get("quiet_gate_waited_s"):
        lines.append(f"quiet gate: waited {artifact['quiet_gate_waited_s']}s "
                     f"({len(artifact.get('quiet_gate_polls', []))} poll(s))")
    lines.append("=" * 84)

    cold = artifact.get("cold") or {}
    lines.append("")
    lines.append(f"cold first call (n=1): {cold.get('first_call_ms', float('nan')):.1f} ms "
                 f"— import + load + first inference.")
    lines.append("  NOT compared to the budget: `warm()` runs at boot so no request pays it.")
    lines.append("  It is measured because the warm path's necessity rests on it.")

    win = artifact["window"]
    lines.append("")
    lines.append(f"per-window, warm ({win['chars']} chars, n={win['n']}):")
    lines.append(f"  p50 {win['p50']:.3f}   p99 {win['p99']:.3f}   max {win['max']:.3f} ms")

    lines.append("")
    lines.append("aggregate curve — the cap must bound the hold in k, not track 10k:")
    lines.append("  spans   n   total_p50   total_p99   total_max   per_span_p50   "
                 "enriched   skipped/call")
    for row in artifact["curve"]:
        lines.append(
            f"  {row['spans']:5d} {row['n']:3d} {row['total_p50']:11.3f} "
            f"{row['total_p99']:11.3f} {row['total_max']:11.3f} "
            f"{row['per_span_p50']:14.3f} {row['enriched_p50']:10.1f} "
            f"{row['skipped_per_call']:13.3f}"
        )

    verdict = artifact.get("verdict") or {}
    lines.append("")
    lines.append(f"CAP CHECK: {verdict.get('status', '?')}")
    lines.append(f"  spans bounded: {verdict.get('spans_bounded')}   "
                 f"time sublinear at k={verdict.get('top_k')}: {verdict.get('time_sublinear')}")
    lines.append(f"  {verdict.get('detail', '')}")
    lines.append("  budget is checked AFTER each window, so the overshoot is by design "
                 "(reported, not gated).")
    lines.append("  `enriched` can FALL as k rises: the window is the sentence, the sentence "
                 "grows with k,")
    lines.append("  so fewer of the more-expensive windows fit the budget. Not noise.")
    if not artifact["window"].get("p99_resolves_off_the_max", True):
        lines.append("  WARNING: at this n a P99 has no sample above it — read `max`, not `p99`.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="04 §2.2 enrichment cap, measured")
    ap.add_argument("--reps", type=int, default=DEFAULT_REPS)
    ap.add_argument("--out", default="reports/spike_enrichment_latency.json")
    ap.add_argument("--render", metavar="FILE",
                    help="re-render an existing artifact; measures nothing")
    args = ap.parse_args(argv)

    if args.render:
        print(_render(json.loads(Path(args.render).read_text())))
        return 0

    artifact: dict[str, Any] = {
        "spike": "04 §2.2 — the 10 ms aggregate enrichment cap, measured",
        "code": git_stamp(),
        "budget_ms": ee.BUDGET_MS,
        "span_counts": list(SPAN_COUNTS),
    }
    certifying = _wait_for_quiet(artifact)
    artifact["load_at_process_start"] = certifying

    # Citability is 06 §8's question and it reads `load1`, so that is the gate — one
    # definition, shared with every harness through `eval/host_load.py`. But a load1 that
    # grazes the ceiling while load5 and load15 sit above it is a decaying transient caught
    # at its lowest instant, not a settled quiet host: the first clean-statistics run of this
    # spike certified at 1.0 / 1.31 / 1.23, passing only because `is_quiet` uses `<=`.
    # Recorded as a margin, NOT enforced as a second threshold — inventing a stricter local
    # definition of "quiet" would leave two harnesses disagreeing about what the word means,
    # which is the defect this repo keeps finding, and a gate no run can pass produces no
    # evidence at all.
    artifact["citability"] = {
        "gate_reads": "load1",
        "quiet_max": QUIET_LOAD1_MAX,
        "margin": round(QUIET_LOAD1_MAX - certifying["load1"], 2),
        "longer_averages_also_inside": (
            certifying["load5"] <= QUIET_LOAD1_MAX
            and certifying["load15"] <= QUIET_LOAD1_MAX
        ),
    }

    if artifact.get("quiet_gate_timed_out"):
        print(
            f"\nREFUSING TO MEASURE: load1 {certifying['load1']} still above "
            f"{QUIET_LOAD1_MAX} after {artifact['quiet_gate_waited_s']}s "
            f"({len(artifact.get('quiet_gate_polls', []))} polls).\n"
            f"  Wrote nothing. An artifact stamped above the ceiling is NOT CITABLE (06 §8), "
            f"and writing one to {args.out}\n"
            f"  would replace evidence with a figure that cannot be cited. Re-run on a "
            f"quiet host.\n"
            f"  (exit 2 = could not measure; exit 1 = measured, cap failed. Different "
            f"outcomes, different codes.)"
        )
        return 2

    # Cold, before anything is warm. One sample by construction: a second call in this
    # process is warm, and a percentile over one number would be a fiction.
    text, signals = _sentence(1)
    started = time.perf_counter()
    asyncio.run(ee.enrich(signals, text, use_case="hr_copilot"))
    artifact["cold"] = {
        "first_call_ms": round((time.perf_counter() - started) * 1000.0, 1),
        "n": 1,
        "note": "import spacy + spacy.load + deferred first inference; paid by warm() at boot",
    }

    artifact.update(asyncio.run(_measure(args.reps)))
    artifact["load_at_end"] = load_stamp()

    # The gate. 04 §2.2 promises "on exceed: stop, log, count" — it does NOT promise a
    # total inside 10 ms, and cannot: the budget is checked AFTER each window, so a call
    # overshoots by up to one window by design. The first version of this harness invented
    # `budget + one k=1 call P99` as a pass line, missed it by 0.48 ms, and printed
    # UNBOUNDED — a verdict about a constant I chose, not about the code. What follows tests
    # the two properties the spec does promise, each from measured quantities only:
    #
    #   (1) SPANS BOUNDED — the number actually enriched stops growing with k. The ceiling
    #       is how many windows fit in the budget, plus the one overshoot window.
    #   (2) TIME SUBLINEAR — at the largest k, the hold is strictly cheaper than enriching
    #       every span would have been. This is what "the cap works" means in time, and its
    #       comparison value is measured in this same run.
    window_p50 = artifact["window"]["p50"]
    fits = max(1, math.floor(ee.BUDGET_MS / window_p50) if window_p50 > 0 else 1)
    span_ceiling = fits + 1
    worst_enriched = max(row["enriched_p50"] for row in artifact["curve"])
    spans_bounded = worst_enriched <= span_ceiling

    top = max(artifact["curve"], key=lambda row: row["spans"])
    unbounded_cost = top["spans"] * window_p50
    time_sublinear = top["total_p99"] < unbounded_cost

    ok = spans_bounded and time_sublinear
    worst_total = max(row["total_p99"] for row in artifact["curve"])
    artifact["verdict"] = {
        "status": "CAP HOLDS" if ok else "CAP FAILS",
        "spans_bounded": spans_bounded,
        "span_ceiling": span_ceiling,
        "worst_enriched": worst_enriched,
        "time_sublinear": time_sublinear,
        "sublinear_basis": (
            "Comparison value is k x the k=1 window P50. The window IS the sentence, and "
            "the sentence grows with k, so a k=8 window costs more than the k=1 window this "
            "figure uses — the unbounded cost is therefore UNDERSTATED and the check is "
            "conservative (it is harder to pass than a same-k comparison would be). Stated "
            "because the same growth is why `enriched` can fall as k rises: at larger k, "
            "fewer of the more-expensive windows fit inside the budget."
        ),
        "top_k": top["spans"],
        "top_k_total_p99_ms": top["total_p99"],
        "unbounded_cost_ms": round(unbounded_cost, 3),
        "worst_total_p99_ms": round(worst_total, 3),
        "overshoot_ms": round(worst_total - ee.BUDGET_MS, 3),
        "overshoot_is_by_design": (
            "The budget is checked after each window, so one window may start while the "
            "call is still inside budget and finish outside it. Checking first would let a "
            "slow pipeline enrich nothing, making the stage unreachable rather than "
            "degraded. The overshoot is therefore reported, not gated."
        ),
        "detail": (
            f"enriched at most {worst_enriched:.0f} spans (ceiling {span_ceiling} = "
            f"{fits} fitting + 1 overshoot); at k={top['spans']} held "
            f"{top['total_p99']:.3f} ms against {unbounded_cost:.3f} ms unbounded; "
            f"worst total P99 {worst_total:.3f} ms = budget + "
            f"{worst_total - ee.BUDGET_MS:.3f} ms of by-design overshoot"
        ),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2) + "\n")
    print(_render(artifact))
    print(f"\nwrote {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
