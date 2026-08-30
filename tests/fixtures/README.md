# Test fixtures

Three real `eval/spike_window_latency.py` artifacts, kept as the real-data test set for
`contamination_signals`. **None of them is citable. Never quote a number from any of these files.**

They exist because a guard validated only on synthetic input has never met the thing it was built
to catch, and because a guard proven only to *fire* has not been shown to stay quiet on good data.
Two dirty runs and one clean one give both directions, and the two dirty ones carry *different*
defect classes — a check that catches one and misses the other would look healthy against a single
fixture.

| file | top rung | what `contamination_signals` finds |
|---|---|---|
| `spike_dirty_batch_curve_2026-08-29.json` | 53 | `COLD RATIO batch_curve/2`, `CROSS-MEASUREMENT` 2w/4w/8w (curve-inflated direction) |
| `spike_dirty_ladder_2026-08-29.json` | 53 | `LOCAL SPIKE sequential 32w`, `CROSS-MEASUREMENT 16w` (ladder-excess direction) |
| `spike_clean_2026-08-29.json` | 53 | nothing, on either thread setting |

## `spike_dirty_batch_curve_2026-08-29.json`

The batch-curve phase was disturbed by a concurrent ONNX export (torch export + int8 quantize) —
a ~20 s multi-core transient, enough to poison three adjacent 10-rep points. Its tell is physical:
`cold_ms / p50 = 0.800` at batch 2, i.e. the median came in 25% *above* the first call, which is
backwards for a warming cache. Cross-checked against the ladder's own timing of the same operation,
its batches 2/4/8 sit 26-36% high where clean runs sit 3-9% low.

Diagnosed originally by inference — a reader who happened to look. Turning that into a mechanical
check is why `contamination_signals` and the load stamps exist.

## `spike_dirty_ladder_2026-08-29.json`

A different phase, a different cause: `eval.check_derivations` runs and several interpreter starts,
launched by the author *during* the measurement in the belief that only heavy jobs mattered. The
ladder's 32-window rung reads 14.98 ms/window against neighbours averaging 12.43, where three other
runs of that rung agree at 12.39-12.60.

Both bracketing load stamps were clean — which is the point. Load averages lag by ~60 s, so a short
transient inside a 3-minute phase leaves the machine's own summary statistic looking fine. This is
the fixture that proves a load stamp is necessary and not sufficient.

## `spike_clean_2026-08-29.json`

A genuine 53-rung `reps=40` run on a quiesced host. No signals on either thread setting; its
sequential curves agree with two independent runs to within 2.5% at every rung; its batch curve
shows the expected U.

**Its batch curve is n=10, not n=40** — it predates the `CURVE_REPS` decoupling (ADR-032
Correction 2), so `reps=40` at run level while every curve point carries `n: 10`. At n=10 a
"p99" is `samples[8]`, so this fixture cannot evidence a *batch choice*, and the sentence here
previously cited its "batch 2 and batch 4 within 0.6%" as if it could. What it does corroborate
is Correction 2's diagnosis: its b2→b4 **P50** gap is +0.61%, close to the resolved run's +0.96%,
while its P99 gap of +1.04% is nowhere near the resolved +11.4%. The flat basin is real in
medians and absent in tails, measured twice — which is exactly why the withdrawn justification
looked sound.

Uncitable for the ordinary reason: measured from a working tree whose harness edits were not
committed, so no committed code reproduces it (AGENTS.md §7).

## Why here and not `reports/`

`reports/` is citable-evidence space, and CI asserts a run leaves it untouched. A non-citable
artifact sitting there invites exactly the misreading these notes exist to prevent.
