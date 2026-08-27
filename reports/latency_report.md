# Gateway latency benchmark (06 §4)

NFR-P-001 (gateway hot-path overhead, **streaming pipelines**) and NFR-P-002 (per-detector fast-path budgets). Every overhead figure below is read back out of `audit_records.latency_json` — the gateway's own recording under the **normative** 06 §4 definition — never recomputed by this harness.

## Provenance

| Field | Value |
|---|---|
| Generated (UTC) | 2026-08-27T11:55:55+00:00 |
| Dataset digest | `6a3ecbbe75fd020bf806bf647d572c85ee187198fb9828eaac5e1c6e00737fbd` |
| Frozen at | `f162959f7d29` — MATCHES |
| Requests attempted | 300 |
| Samples recorded | 300 |
| Stub cadence | 0.5 ms/token |
| Code commit | `149b00fd4191` |
| Python | 3.14.6 |
| Platform | Linux 7.1.2-arch3-1 · x86_64 |
| CPU | unreported |
| Percentile method | linear-interpolated (`telemetry.metrics.percentile`) |
| Command | `python -m eval.bench_latency` |

> **Upstream provenance:** the active provider `kiro-local` is **dev-class**, which `require_measured_upstream()` refuses for judge-facing output (ADR-018). **The stub-upstream tables are unaffected:** they involve no provider call at all — that is the point of a stub, and 06 §4 chose one so gateway overhead is isolated from provider variance. The gate binds only the end-to-end sanity row, which is reported as not-run below.

## Method

1. 300 requests replayed from the frozen corpus, balanced across the three pipelines and cycling deterministically — two runs on one freeze issue the identical sequence, so a change in these numbers is drift rather than noise.
2. Upstream is a **stub** emitting canned SSE word-by-word at the cadence above, so gateway overhead is isolated from provider variance (06 §4). Word-by-word matters: a single-chunk response would collapse every per-sentence hold into one and report the overhead of a pipeline nobody runs.
3. `gateway_overhead_ms` is read from each request's audit record. **Streaming and non-streaming are tabulated separately because they are different quantities** — streaming sums measured hold intervals, non-streaming subtracts the upstream call from wall-clock (06 §4).
4. **ADR-030 re-scoped NFR-P-001 onto the per-hold series, so the tables below carry no NFR-P-001 verdict.** The per-request sum is retained and published under its new name, untargeted; the requirement's own targets now attach to `input_hold_ms` and each `sentence_holds_ms` entry, neither of which is emitted yet (M-20). Gating these tables on a withdrawn target would assert a requirement the docs no longer contain.

## `total_attributable_overhead_ms` — streaming pipelines (published, no target)

Renamed by **ADR-030** from `gateway_overhead_ms`; **the 06 §4 formula is unchanged**, so these figures are comparable to every previously published run. What changed is its standing: it is no longer the quantity NFR-P-001 targets, and it keeps being published precisely so the respecification withdraws a target without withdrawing a number.

| Pipeline | n | P50 | P95 | P99 | min | max |
|---|---|---|---|---|---|---|
| UC-1 `support_bot` | 100 | 0.25 | 0.43 | 0.94 | 0.19 | 1.46 |
| UC-2 `hr_copilot` | 100 | 0.25 | 0.86 | 1.85 | 0.18 | 2.04 |
| **all streaming** | 200 | 0.25 | 0.48 | 1.46 | 0.18 | 2.04 |

## `total_attributable_overhead_ms` — non-streaming pipelines

Reported separately and **not** gated by NFR-P-001, whose scope is streaming pipelines. `total wall-clock − upstream duration` per 06 §4.

| Pipeline | n | P50 | P95 | P99 | min | max |
|---|---|---|---|---|---|---|
| UC-3 `finance_advisor` | 100 | 0.27 | 0.39 | 0.42 | 0.16 | 0.45 |
| **all non-streaming** | 100 | 0.27 | 0.39 | 0.42 | 0.16 | 0.45 |

### Reference row — client wall-clock − upstream (streaming)

06 §4 requires this be reported **separately and never as the headline number**, so it sits here rather than above. It exceeds `gateway_overhead_ms` by relay and `TestClient` ASGI transport time — neither a per-sentence hold nor a token wait, and the harness's own cost rather than the gateway's. Treat it as an upper bound.

| Series | n | P50 | P95 | P99 | min | max |
|---|---|---|---|---|---|---|
| wall − upstream (upper bound) | 200 | 2.32 | 3.00 | 4.14 | 1.86 | 9.25 |

## Per-detector latency vs NFR-P-002 budgets

Budgets are also enforced at runtime: `run_with_budget` cancels past budget and raises `DetectorTimeout`. A P99 sitting at the budget therefore usually means timeouts fired, not that a call ran long — the two need different responses, so the fault count is shown beside the percentiles.

| Detector | Budget | n | P50 | P95 | P99 | max | Faults | Within budget (P99) |
|---|---|---|---|---|---|---|---|---|
| `numeric_claims` | 5 ms | 290 | 0.044 | 0.141 | 0.205 | 0.712 | 0 | yes |
| `tier1_blocklist` | 2 ms | 590 | 0.011 | 0.014 | 0.020 | 0.032 | 0 | yes |
| `tier1_pii` | 2 ms | 590 | 0.039 | 0.081 | 0.126 | 1.716 | 0 | yes |

**Not exercised in this run:** `conv_tracker`, `cost_budget`, `entity_enricher`, `fast_consistency`, `loop_guard`, `rag_grounding`, `tier2_injection`, `tier2_toxicity`. These are unimplemented or policy-gated detectors, so their budgets are untested rather than met — the distinction M-10 draws between "checked, clean" and "never checked", applied to a benchmark.

## NFR verdict

**No violation of any requirement this run can evaluate.** `--check` exits zero on this state and nonzero on any row above appearing. That covers NFR-P-002 only — see the NFR-P-001 note below, which is a *third* state and not a pass.

**NFR-P-001: `not measured`.** ADR-030 re-scoped it onto `input_hold_ms` and `sentence_holds_ms`, and neither series is emitted yet (**M-20**) — the intervals exist in `app.py` but are accumulated into one figure rather than recorded per hold. The previous per-request target is **withdrawn**, so this run neither meets nor fails NFR-P-001. `--check` therefore returns no NFR-P-001 verdict, which 06 §4 requires be stated in these words rather than left to read as a pass.

## End-to-end sanity row (real provider)

**Not run** (`--live` not passed). 06 §4's 30-request sanity row is opt-in because the shipped active provider is dev-class and its numbers are not publishable (ADR-018).

## Forward projection — what happens when the remaining hot-path detectors land

**This section is a PROJECTION, not a measurement.** Every figure is arithmetic over the 04 §2 declared budgets, not an observation: `tier2_toxicity` and `tier2_injection` are unimplemented, so nothing here has been run. It is derived from `LANES` and `BUDGETS_MS` rather than written down, so a budget or lane change moves it.

This section is also **the evidence that motivated ADR-030**, which re-scoped NFR-P-001 onto the per-hold series after this arithmetic showed the old per-request target could not survive the documented detector set. It is kept here, unshortened, so the ruling's basis stays visible in the artefact that produced it.

Pending detectors on the hot-path lanes: `tier2_injection`, `cost_budget`, `loop_guard`, `tier2_toxicity`. `rag_grounding` (30 ms/sentence) is **excluded** — `expected_for` skips it without context docs and no dataset case carries any; with them, add that per sentence.

The multiplier matters more than the per-detector cost. `total_attributable_overhead_ms` is a **sum over per-sentence holds**, so a per-sentence budget is paid once per sentence — which is precisely why ADR-030 stopped targeting the sum and started targeting the hold. Segment counts measured over the frozen corpus with the real `Segmentation` (n=280): P50 **1**, P95 **3**, P99 **6**, max **10**.

**Lane cost, sequential (as implemented)** — input 31 ms once, 34 ms per sentence (today: 4 ms / 9 ms).

NFR-P-001 as ADR-030 scopes it: input-lane hold **within** its 50 ms P99, per-sentence hold **within** its 100 ms P99.

| Segments | Projected `total_attributable_overhead_ms` | vs the **withdrawn** 100 ms per-request target |
|---|---|---|
| P50 — 1 | 65 ms | would have been under |
| P95 — 3 | 133 ms | would have breached |
| P99 — 6 | 235 ms | would have breached |
| max — 10 | 371 ms | would have breached |

**Lane cost, parallel (02 §4 intent)** — input 25 ms once, 25 ms per sentence (today: 2 ms / 5 ms).

NFR-P-001 as ADR-030 scopes it: input-lane hold **within** its 50 ms P99, per-sentence hold **within** its 100 ms P99.

| Segments | Projected `total_attributable_overhead_ms` | vs the **withdrawn** 100 ms per-request target |
|---|---|---|
| P50 — 1 | 50 ms | would have been under |
| P95 — 3 | 100 ms | would have breached |
| P99 — 6 | 175 ms | would have breached |
| max — 10 | 275 ms | would have breached |

**Under ADR-030's scope the composition fits, under both readings; under the withdrawn per-request target it did not, under either.** That is the whole content of the respecification: the arithmetic is unchanged and every budget is unchanged — what changed is which quantity NFR-P-001 judges. The per-request sum still grows with the segment count exactly as tabulated above, and is still published, so the trade-off is legible rather than hidden.

**The trade-off ADR-030 accepted, stated plainly:** a long response can hold ~371 ms in total while *every individual sentence* passes its target. A per-hold guarantee is genuinely weaker than a per-request one. It is the guarantee that matches what sentence-level interception promises — each hold is the delay before *that* sentence appears — and the total is published untargeted beside it so a reader can see both.

**The fit is conditional, not unconditional (M-18).** `entity_enricher` is budgeted per *span*, not per sentence, so a heavily-enriched sentence composes to `60 + 10k` and crosses the 100 ms per-sentence P99 at **k = 4**. No doc bounds `k`. ADR-030 records this against its own target rather than assuming it away, and inventing a cap to make the target fit is exactly the move AGENTS.md §5.4 forbids.

Three things this does **not** say. It is not a measurement, so it is not a D3 — a D3 needs an observed breach, and nothing here was observed: the measured sum is 1.46 ms P99 over 200 samples, against a smallest projected figure of 50 ms. It is not a claim that the budgets are wrong: 04 §2 declares them and `run_with_budget` enforces them, so a detector at budget is a detector behaving as specified. And it is not a prediction that tier2 will actually cost its full budget — a fast classifier well inside 25 ms changes the arithmetic entirely.

## Scope and limitations

**The headline figure is cadence-independent by construction**, because 06 §4 excludes upstream token wait from `gateway_overhead_ms`. That is verified, not assumed: `test_overhead_is_independent_of_token_cadence` runs the same mix at two cadences and asserts the figure does not track the change.

**`TestClient` transport is in the reference row, not the headline.** The in-process ASGI round trip is harness cost a real client would not pay, which is precisely why the headline reads the gateway's own recording instead of this harness's stopwatch.

**Prototype hardware, single machine, no warm-up discard.** The first requests include one-off import and compile cost, which inflates the maximum rather than the percentiles. Stated instead of trimmed: discarding a warm-up window without saying so would improve the number by choosing which measurements count.

Reproduce: `python -m eval.validate_dataset --freeze && python -m eval.bench_latency`
