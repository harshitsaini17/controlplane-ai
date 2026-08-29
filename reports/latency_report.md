# Gateway latency benchmark (06 §4)

NFR-P-001 (gateway hot-path overhead, **streaming pipelines**) and NFR-P-002 (per-detector fast-path budgets). Every overhead figure below is read back out of `audit_records.latency_json` — the gateway's own recording under the **normative** 06 §4 definition — never recomputed by this harness.

## Provenance

| Field | Value |
|---|---|
| Generated (UTC) | 2026-08-29T23:15:30+00:00 |
| Dataset digest | `6a3ecbbe75fd020bf806bf647d572c85ee187198fb9828eaac5e1c6e00737fbd` |
| Frozen at | `f162959f7d29` — MATCHES |
| Requests attempted | 300 |
| Samples recorded | 300 |
| Stub cadence | 0.5 ms/token |
| Code commit | `c838964ca3d9` + uncommitted changes |
| Python | 3.14.6 |
| Platform | Linux 7.1.2-arch3-1 · x86_64 |
| CPU | unreported |
| Percentile method | linear-interpolated (`telemetry.metrics.percentile`) |
| Host load at process start (1/5/15) | 0.95 / 1.92 / 1.96 · 12 CPUs — **QUIET** |
| Host load at end (1/5/15) | 3.02 / 2.31 / 2.08 · 12 CPUs |
| Command | `python -m eval.bench_latency --check` |

> **Upstream provenance:** the active provider `kiro-local` is **dev-class**, which `require_measured_upstream()` refuses for judge-facing output (ADR-018). **The stub-upstream tables are unaffected:** they involve no provider call at all — that is the point of a stub, and 06 §4 chose one so gateway overhead is isolated from provider variance. The gate binds only the end-to-end sanity row, which is reported as not-run below.

## Method

1. 300 requests replayed from the frozen corpus, balanced across the three pipelines and cycling deterministically — two runs on one freeze issue the identical sequence, so a change in these numbers is drift rather than noise.
2. Upstream is a **stub** emitting canned SSE word-by-word at the cadence above, so gateway overhead is isolated from provider variance (06 §4). Word-by-word matters: a single-chunk response would collapse every per-sentence hold into one and report the overhead of a pipeline nobody runs.
3. `total_attributable_overhead_ms` is read from each request's audit record. **Streaming and non-streaming are tabulated separately because they are different quantities** — streaming sums measured hold intervals, non-streaming subtracts the upstream call from wall-clock (06 §4).
4. **ADR-030 re-scoped NFR-P-001 onto the per-hold series**, so the requirement is gated on `input_hold_ms` and `sentence_holds_ms` — the two holds a user actually waits through — and **not** on the per-request sum, which is retained and published under its new name, untargeted. The per-sentence population is **holds, not requests**: a percentile over per-request means would let one slow hold hide behind a long response's fast ones.

## NFR-P-001 — the targeted per-hold series (streaming)

These two series are what NFR-P-001 targets after ADR-030, whose targets were *derived* from the 04 §2 budgets rather than fitted to a measurement. `sentence_holds_ms` is tabulated **over holds**, so `n` is the number of sentences held, not the number of requests. Non-streaming pipelines record one buffered hold each and are published below but never gated here — 01's NFR-P-001 row scopes to streaming.

| Series | Target P50 | Target P99 | n | P50 | P95 | P99 | min | max |
|---|---|---|---|---|---|---|---|---|
| `input_hold_ms` | < 40 ms | < 50 ms | 200 | 20.86 | 24.10 | 26.68 | 12.55 | 27.13 |
| `sentence_holds_ms` (per hold) | < 40 ms | < 100 ms | 231 | 20.70 | 27.59 | 31.40 | 11.85 | 509.75 |

## `total_attributable_overhead_ms` — streaming pipelines (published, no target)

Renamed by **ADR-030** from `gateway_overhead_ms`; **the 06 §4 formula is unchanged**, so these figures are comparable to every previously published run. What changed is its standing: it is no longer the quantity NFR-P-001 targets, and it keeps being published precisely so the respecification withdraws a target without withdrawing a number.

| Pipeline | n | P50 | P95 | P99 | min | max |
|---|---|---|---|---|---|---|
| UC-1 `support_bot` | 100 | 41.62 | 54.20 | 65.39 | 29.34 | 529.74 |
| UC-2 `hr_copilot` | 100 | 43.05 | 72.03 | 107.79 | 12.76 | 114.23 |
| **all streaming** | 200 | 42.18 | 59.07 | 107.79 | 12.76 | 529.74 |

## `total_attributable_overhead_ms` — non-streaming pipelines

Reported separately and **not** gated by NFR-P-001, whose scope is streaming pipelines. `total wall-clock − upstream duration` per 06 §4.

| Pipeline | n | P50 | P95 | P99 | min | max |
|---|---|---|---|---|---|---|
| UC-3 `finance_advisor` | 100 | 12.35 | 18.61 | 20.41 | 11.71 | 22.05 |
| **all non-streaming** | 100 | 12.35 | 18.61 | 20.41 | 11.71 | 22.05 |

### `added_time_to_last_byte_ms` — client wall-clock − upstream (streaming)

06 §4 requires this be reported **separately and never as the headline number**, so it sits here rather than above. It exceeds `total_attributable_overhead_ms` by relay and `TestClient` ASGI transport time — neither a per-sentence hold nor a token wait, and the harness's own cost rather than the gateway's. Treat it as an upper bound.

**Measured here, by the client, and not read back from `latency_json`** (ADR-030 Amendment 1). The figure is defined as *client-observed* last-byte time minus the request's upstream duration, and the gateway has no client vantage: a completed ASGI `send()` means handed to the transport, not received. So this row is the quantity itself rather than a stand-in for a column the gateway writes — it was previously reported under the name `reference_delta_ms`, and the two were one subtraction.

| Series | n | P50 | P95 | P99 | min | max |
|---|---|---|---|---|---|---|
| `added_time_to_last_byte_ms` (upper bound) | 200 | 45.23 | 61.80 | 110.57 | 15.71 | 532.73 |

## Per-detector latency vs NFR-P-002 budgets

Budgets are also enforced at runtime: `run_with_budget` cancels past budget and raises `DetectorTimeout`. A P99 sitting at the budget therefore usually means timeouts fired, not that a call ran long — the two need different responses, so the fault count is shown beside the percentiles.

| Detector | Budget | n | P50 | P95 | P99 | max | Faults | Within budget (P99) |
|---|---|---|---|---|---|---|---|---|
| `numeric_claims` | 5 ms | 283 | 0.079 | 0.242 | 0.309 | 0.378 | 0 | yes |
| `tier1_blocklist` | 2 ms | 583 | 0.014 | 0.018 | 0.024 | 0.068 | 0 | yes |
| `tier1_pii` | 2 ms | 583 | 0.058 | 0.094 | 0.124 | 0.234 | 0 | yes |
| `tier2_injection` | 25 ms | 300 | 20.136 | 23.372 | 25.569 | 26.909 | 0 | **NO** |
| `tier2_toxicity` | 25 ms | 283 | 19.883 | 22.915 | 25.114 | 31.629 | 2 (fail_open ×2) | **NO** |

**Not exercised in this run:** `conv_tracker`, `cost_budget`, `fast_consistency`, `loop_guard`, `rag_grounding`. These are unimplemented or policy-gated detectors, so their budgets are untested rather than met — the distinction M-10 draws between "checked, clean" and "never checked", applied to a benchmark.

**Implemented, but outside this harness:** `entity_enricher`. In no `LANES` row, so no lane benchmark can produce a row for it: its budget is untested **here**, which is a narrower claim than untested. Listed rather than omitted, because a detector silently missing from a latency table reads as one that met its budget.

## NFR verdict

**2 violation(s).** Per AGENTS.md §5.4 the response is a **D3 deviation** carrying the honest measured number — never a relaxed threshold.

| Requirement | Subject | Metric | Target | Measured |
|---|---|---|---|---|
| NFR-P-002 | tier2_injection | P99 | 25.0 ms | **25.569 ms** |
| NFR-P-002 | tier2_toxicity | P99 | 25.0 ms | **25.114 ms** |

## End-to-end sanity row (real provider)

**Not run** (`--live` not passed). 06 §4's 30-request sanity row is opt-in because the shipped active provider is dev-class and its numbers are not publishable (ADR-018).

## Forward projection — what happens when the remaining hot-path detectors land

**This section is a PROJECTION, not a measurement.** Every figure is arithmetic over the 04 §2 declared budgets, not an observation. It is derived from `LANES` and `BUDGETS_MS` rather than written down, so a budget or lane change moves it. Still unimplemented, and therefore genuinely unmeasurable here: `cost_budget`, `loop_guard`. Detectors that ARE live appear as measurements in the per-detector table above; their budgets are projected here only to keep this arithmetic comparable to the pre-ADR-030 figures it is kept to justify.

This section is also **the evidence that motivated ADR-030**, which re-scoped NFR-P-001 onto the per-hold series after this arithmetic showed the old per-request target could not survive the documented detector set. It is kept here, unshortened, so the ruling's basis stays visible in the artefact that produced it.

Pending detectors on the hot-path lanes: `cost_budget`, `loop_guard`. `rag_grounding` (30 ms/sentence) is **excluded** — `expected_for` skips it without context docs and no dataset case carries any; with them, add that per sentence.

The multiplier matters more than the per-detector cost. `total_attributable_overhead_ms` is a **sum over per-sentence holds**, so a per-sentence budget is paid once per sentence — which is precisely why ADR-030 stopped targeting the sum and started targeting the hold. Segment counts measured over the frozen corpus with the real `Segmentation` (n=280): P50 **1**, P95 **3**, P99 **6**, max **10**.

**Lane cost, sequential (as implemented)** — input 31 ms once, 34 ms per sentence (today: 29 ms / 34 ms).

NFR-P-001 as ADR-030 scopes it: input-lane hold **within** its 50 ms P99, per-sentence hold **within** its 100 ms P99.

| Segments | Projected `total_attributable_overhead_ms` | vs the **withdrawn** 100 ms per-request target |
|---|---|---|
| P50 — 1 | 65 ms | would have been under |
| P95 — 3 | 133 ms | would have breached |
| P99 — 6 | 235 ms | would have breached |
| max — 10 | 371 ms | would have breached |

**Lane cost, parallel (02 §4 intent)** — input 25 ms once, 25 ms per sentence (today: 25 ms / 25 ms).

NFR-P-001 as ADR-030 scopes it: input-lane hold **within** its 50 ms P99, per-sentence hold **within** its 100 ms P99.

| Segments | Projected `total_attributable_overhead_ms` | vs the **withdrawn** 100 ms per-request target |
|---|---|---|
| P50 — 1 | 50 ms | would have been under |
| P95 — 3 | 100 ms | would have breached |
| P99 — 6 | 175 ms | would have breached |
| max — 10 | 275 ms | would have breached |

**Under ADR-030's scope the composition fits, under both readings; under the withdrawn per-request target it did not, under either.** That is the whole content of the respecification: the arithmetic is unchanged and every budget is unchanged — what changed is which quantity NFR-P-001 judges. The per-request sum still grows with the segment count exactly as tabulated above, and is still published, so the trade-off is legible rather than hidden.

**The trade-off ADR-030 accepted, stated plainly:** a long response can hold ~371 ms in total while *every individual sentence* passes its target. A per-hold guarantee is genuinely weaker than a per-request one. It is the guarantee that matches what sentence-level interception promises — each hold is the delay before *that* sentence appears — and the total is published untargeted beside it so a reader can see both.

**The unconditional fit (M-18 / M-19) is now contested — see below.** It was conditional when ADR-030 was accepted: `entity_enricher` was budgeted per *span*, so a heavily-enriched sentence composed to `60 + 10k` and crossed the 100 ms per-sentence P99 at **k = 4**, with no doc bounding `k`. 04 §2.2 now caps enrichment at **10 ms aggregate per sentence**, so `k` leaves the arithmetic entirely, and the policy+action step carries a **combined 5 ms budget** instead of sitting untracked inside a targeted quantity. Both caps were ruled where the budget lives (04 §2.2) rather than inside the target that needed them — inventing a bound to make one's own target fit is the move AGENTS.md §5.4 forbids.

**ADR-030's worst cases are re-derived under Amendment 3 (2026-08-30), which closed `[D1-per-hold-derivation-maxes-detectors-that-share-one-worker]` (08).** ADR-034 Part A binds five *named* model detectors to one shared `max_workers=1` pool, so a lane's pool users **serialize** and compose as `sum`; only non-pool detectors overlap (`~max`). A hold is therefore `max(Σ pool, max(non-pool)) + 5 ms` engine step, and the six rows read 30 / 30 / 40 / 70 / 100 / 130 ms — the context-docs row moved 45 → 70 and the `on_sampled` row 75 → 100. **No target moved.** The two rows that no longer fit a plausible target (`on_sampled`, with and without context docs) publish **untargeted**, following the per-request-sum precedent rather than widening a target to admit them. The composition is executable rather than prose: `eval.check_derivations` re-derives all six rows from `BUDGETS_MS` and the pool-user set, and on first run it caught three pool-sum cells in the amendment's own table that had omitted `entity_enricher`. **The measured rows above and the two computed projection readings are unaffected**: this section publishes the `sum` and `max` readings side by side, and the pool-aware composition lies between them, which is what reporting both was for.

One adjacency ADR-030 records rather than rounds away: the **enriched typical** row lands at exactly **40.0 ms** against a strict `< 40` P50. It is not a breach, because the P50 judges the *median* hold and a median sentence is unenriched — enrichment requires a span-bearing `hallucination.*` signal, so a median enriched sentence would mean over half of all traffic is hallucination-flagged. It is written down because it is the first place a future budget change would break the derivation.

Three things this does **not** say. It is not a measurement, so it is not a D3 — a D3 needs an observed breach, and nothing here was observed: the measured sum is 107.79 ms P99 over 200 samples, against a smallest projected figure of 50 ms. It is not a claim that the budgets are wrong: 04 §2 declares them and `run_with_budget` enforces them, so a detector at budget is a detector behaving as specified. And it is not a prediction that tier2 will actually cost its full budget — a fast classifier well inside 25 ms changes the arithmetic entirely.

## Scope and limitations

**The headline figure is cadence-independent by construction**, because 06 §4 excludes upstream token wait from `total_attributable_overhead_ms`. That is verified, not assumed: `test_overhead_is_independent_of_token_cadence` runs the same mix at two cadences and asserts the figure does not track the change.

**`TestClient` transport is in the reference row, not the headline.** The in-process ASGI round trip is harness cost a real client would not pay, which is precisely why the headline reads the gateway's own recording instead of this harness's stopwatch.

**Prototype hardware, single machine, no warm-up discard.** The first requests include one-off import and compile cost, which inflates the maximum rather than the percentiles. Stated instead of trimmed: discarding a warm-up window without saying so would improve the number by choosing which measurements count.

Reproduce: `python -m eval.validate_dataset --freeze && python -m eval.bench_latency`
