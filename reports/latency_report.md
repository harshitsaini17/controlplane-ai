# Gateway latency benchmark (06 §4)

NFR-P-001 (gateway hot-path overhead, **streaming pipelines**) and NFR-P-002 (per-detector fast-path budgets). Every overhead figure below is read back out of `audit_records.latency_json` — the gateway's own recording under the **normative** 06 §4 definition — never recomputed by this harness.

## Provenance

| Field | Value |
|---|---|
| Generated (UTC) | 2026-08-27T11:12:34+00:00 |
| Dataset digest | `6a3ecbbe75fd020bf806bf647d572c85ee187198fb9828eaac5e1c6e00737fbd` |
| Frozen at | `f162959f7d29` — MATCHES |
| Requests attempted | 300 |
| Samples recorded | 300 |
| Stub cadence | 0.5 ms/token |
| Code commit | `3507dba98a22` |
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
4. NFR-P-001 gates the **streaming** table only, per its own wording. The non-streaming table is reported in full and gated by NFR-P-002 alone; applying a streaming threshold to a subtraction-derived figure would invent a requirement.

## `gateway_overhead_ms` — streaming pipelines (NFR-P-001 scope)

Target: **P50 < 40 ms, P99 < 100 ms** on demo hardware.

| Pipeline | n | P50 | P95 | P99 | min | max |
|---|---|---|---|---|---|---|
| UC-1 `support_bot` | 100 | 0.25 | 0.47 | 1.01 | 0.19 | 1.47 |
| UC-2 `hr_copilot` | 100 | 0.26 | 0.87 | 1.76 | 0.17 | 1.96 |
| **all streaming** | 200 | 0.25 | 0.54 | 1.47 | 0.17 | 1.96 |

## `gateway_overhead_ms` — non-streaming pipelines

Reported separately and **not** gated by NFR-P-001, whose scope is streaming pipelines. `total wall-clock − upstream duration` per 06 §4.

| Pipeline | n | P50 | P95 | P99 | min | max |
|---|---|---|---|---|---|---|
| UC-3 `finance_advisor` | 100 | 0.27 | 0.37 | 0.41 | 0.16 | 0.52 |
| **all non-streaming** | 100 | 0.27 | 0.37 | 0.41 | 0.16 | 0.52 |

### Reference row — client wall-clock − upstream (streaming)

06 §4 requires this be reported **separately and never as the headline number**, so it sits here rather than above. It exceeds `gateway_overhead_ms` by relay and `TestClient` ASGI transport time — neither a per-sentence hold nor a token wait, and the harness's own cost rather than the gateway's. Treat it as an upper bound.

| Series | n | P50 | P95 | P99 | min | max |
|---|---|---|---|---|---|---|
| wall − upstream (upper bound) | 200 | 2.35 | 3.09 | 4.12 | 1.92 | 9.48 |

## Per-detector latency vs NFR-P-002 budgets

Budgets are also enforced at runtime: `run_with_budget` cancels past budget and raises `DetectorTimeout`. A P99 sitting at the budget therefore usually means timeouts fired, not that a call ran long — the two need different responses, so the fault count is shown beside the percentiles.

| Detector | Budget | n | P50 | P95 | P99 | max | Faults | Within budget (P99) |
|---|---|---|---|---|---|---|---|---|
| `numeric_claims` | 5 ms | 290 | 0.043 | 0.140 | 0.208 | 0.809 | 0 | yes |
| `tier1_blocklist` | 2 ms | 590 | 0.011 | 0.014 | 0.023 | 0.057 | 0 | yes |
| `tier1_pii` | 2 ms | 590 | 0.040 | 0.082 | 0.126 | 1.657 | 0 | yes |

**Not exercised in this run:** `conv_tracker`, `cost_budget`, `entity_enricher`, `fast_consistency`, `loop_guard`, `rag_grounding`, `tier2_injection`, `tier2_toxicity`. These are unimplemented or policy-gated detectors, so their budgets are untested rather than met — the distinction M-10 draws between "checked, clean" and "never checked", applied to a benchmark.

## NFR verdict

**No violation.** Every gated figure is inside its documented target. `--check` exits zero on this state and nonzero on any row above appearing.

## End-to-end sanity row (real provider)

**Not run** (`--live` not passed). 06 §4's 30-request sanity row is opt-in because the shipped active provider is dev-class and its numbers are not publishable (ADR-018).

## Forward projection — what happens when the remaining hot-path detectors land

**This section is a PROJECTION, not a measurement.** Every figure is arithmetic over the 04 §2 declared budgets, not an observation: `tier2_toxicity` and `tier2_injection` are unimplemented, so nothing here has been run. It is derived from `LANES` and `BUDGETS_MS` rather than written down, so a budget or lane change moves it.

Pending detectors on the hot-path lanes: `tier2_injection`, `cost_budget`, `loop_guard`, `tier2_toxicity`. `rag_grounding` (30 ms/sentence) is **excluded** — `expected_for` skips it without context docs and no dataset case carries any; with them, add that per sentence.

The multiplier matters more than the per-detector cost. 06 §4's streaming figure is a **sum over per-sentence holds**, so a per-sentence budget is paid once per sentence. Segment counts measured over the frozen corpus with the real `Segmentation` (n=280): P50 **1**, P95 **3**, P99 **6**, max **10**.

**Lane cost, sequential (as implemented)** — input 31 ms once, 34 ms per sentence (today: 4 ms / 9 ms).

| Segments | Projected streaming overhead | vs 100 ms P99 target |
|---|---|---|
| P50 — 1 | 65 ms | under |
| P95 — 3 | 133 ms | **BREACH** |
| P99 — 6 | 235 ms | **BREACH** |
| max — 10 | 371 ms | **BREACH** |

**Lane cost, parallel (02 §4 intent)** — input 25 ms once, 25 ms per sentence (today: 2 ms / 5 ms).

| Segments | Projected streaming overhead | vs 100 ms P99 target |
|---|---|---|
| P50 — 1 | 50 ms | under |
| P95 — 3 | 100 ms | **BREACH** |
| P99 — 6 | 175 ms | **BREACH** |
| max — 10 | 275 ms | **BREACH** |

**The projection does not clear the target, and it fails under both readings.** At the measured P99 segment count the projected overhead exceeds 100 ms even under the *favourable* parallel reading — so the conclusion does not rest on `run_lane` being sequential today. A single-sentence response stays inside budget; a multi-sentence one does not.

Three things this does **not** say. It is not a measurement, so it is not a D3 — a D3 needs an observed breach, and today's figures pass: measured streaming P99 is 1.47 ms over 200 samples against the 100 ms target, a factor of 68x. It is not a claim that the budgets are wrong: 04 §2 declares them and `run_with_budget` enforces them, so a detector at budget is a detector behaving as specified. And it is not a prediction that tier2 will actually cost its full budget — a fast classifier well inside 25 ms changes the arithmetic entirely. What it does say is that **NFR-P-001 and the 04 §2 budget set cannot both hold at the measured segment distribution once the documented detector set is complete**, which is a contradiction between two documents rather than a defect in either. Raised for a ruling rather than resolved here (AGENTS.md §5.4).

## Scope and limitations

**The headline figure is cadence-independent by construction**, because 06 §4 excludes upstream token wait from `gateway_overhead_ms`. That is verified, not assumed: `test_overhead_is_independent_of_token_cadence` runs the same mix at two cadences and asserts the figure does not track the change.

**`TestClient` transport is in the reference row, not the headline.** The in-process ASGI round trip is harness cost a real client would not pay, which is precisely why the headline reads the gateway's own recording instead of this harness's stopwatch.

**Prototype hardware, single machine, no warm-up discard.** The first requests include one-off import and compile cost, which inflates the maximum rather than the percentiles. Stated instead of trimmed: discarding a warm-up window without saying so would improve the number by choosing which measurements count.

Reproduce: `python -m eval.validate_dataset --freeze && python -m eval.bench_latency`
