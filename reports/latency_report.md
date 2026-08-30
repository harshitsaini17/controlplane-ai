# Gateway latency benchmark (06 §4)

NFR-P-001 (gateway hot-path overhead, **streaming pipelines**) and NFR-P-002 (per-detector fast-path budgets). Every overhead figure below is read back out of `audit_records.latency_json` — the gateway's own recording under the **normative** 06 §4 definition — never recomputed by this harness.

## Provenance

| Field | Value |
|---|---|
| Generated (UTC) | 2026-08-30T06:16:07+00:00 |
| Dataset digest | `6a3ecbbe75fd020bf806bf647d572c85ee187198fb9828eaac5e1c6e00737fbd` |
| Frozen at | `f162959f7d29` — MATCHES |
| Requests attempted | 300 |
| Samples recorded | 300 |
| Stub cadence | 0.5 ms/token |
| Code commit | `94992335ff6b` |
| Python | 3.14.6 |
| Platform | Linux 7.1.2-arch3-1 · x86_64 |
| CPU | unreported |
| Percentile method | linear-interpolated (`telemetry.metrics.percentile`) |
| Host load at process start (1/5/15) | 0.84 / 1.02 / 1.29 · 12 CPUs — **QUIET** |
| Host load at end (1/5/15) | 2.44 / 1.35 / 1.39 · 12 CPUs |
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
| `input_hold_ms` | < 40 ms | < 50 ms | 200 | 21.58 | 25.67 | 27.49 | 11.83 | 29.38 |
| `sentence_holds_ms` (per hold) | < 40 ms | < 100 ms | 231 | 21.00 | 27.53 | 39.59 | 11.85 | 539.56 |

## `total_attributable_overhead_ms` — streaming pipelines (published, no target)

Renamed by **ADR-030** from `gateway_overhead_ms`; **the 06 §4 formula is unchanged**, so these figures are comparable to every previously published run. What changed is its standing: it is no longer the quantity NFR-P-001 targets, and it keeps being published precisely so the respecification withdraws a target without withdrawing a number.

| Pipeline | n | P50 | P95 | P99 | min | max |
|---|---|---|---|---|---|---|
| UC-1 `support_bot` | 100 | 43.10 | 64.04 | 74.52 | 31.64 | 560.75 |
| UC-2 `hr_copilot` | 100 | 43.48 | 74.44 | 109.77 | 12.26 | 110.92 |
| **all streaming** | 200 | 43.35 | 68.02 | 109.77 | 12.26 | 560.75 |

## `total_attributable_overhead_ms` — non-streaming pipelines

Reported separately and **not** gated by NFR-P-001, whose scope is streaming pipelines. `total wall-clock − upstream duration` per 06 §4.

| Pipeline | n | P50 | P95 | P99 | min | max |
|---|---|---|---|---|---|---|
| UC-3 `finance_advisor` | 100 | 12.72 | 19.91 | 20.32 | 12.18 | 21.62 |
| **all non-streaming** | 100 | 12.72 | 19.91 | 20.32 | 12.18 | 21.62 |

### `added_time_to_last_byte_ms` — client wall-clock − upstream (streaming)

06 §4 requires this be reported **separately and never as the headline number**, so it sits here rather than above. It exceeds `total_attributable_overhead_ms` by relay and `TestClient` ASGI transport time — neither a per-sentence hold nor a token wait, and the harness's own cost rather than the gateway's. Treat it as an upper bound.

**Measured here, by the client, and not read back from `latency_json`** (ADR-030 Amendment 1). The figure is defined as *client-observed* last-byte time minus the request's upstream duration, and the gateway has no client vantage: a completed ASGI `send()` means handed to the transport, not received. So this row is the quantity itself rather than a stand-in for a column the gateway writes — it was previously reported under the name `reference_delta_ms`, and the two were one subtraction.

| Series | n | P50 | P95 | P99 | min | max |
|---|---|---|---|---|---|---|
| `added_time_to_last_byte_ms` (upper bound) | 200 | 46.35 | 71.09 | 112.74 | 14.89 | 563.64 |

## Per-detector budget verdict — NFR-P-002, on the ATTRIBUTABLE series

**ADR-036 Amendment 1.** The budget binds detector-**attributable** time — in-thread CPU, the same figure `run_with_budget` enforces on. This table is the NFR-P-002 verdict and the only place one is rendered. Wall-clock follows below, untargeted.

A breaching call IS in this series: the figure is recorded before the raise. Were it otherwise the only samples able to fail the gate would be ones the gate never sees.

| Detector | Budget | n | P50 | P95 | P99 | max | Faults | Within budget (P99) |
|---|---|---|---|---|---|---|---|---|
| `numeric_claims` | 5 ms | 283 | 0.077 | 0.234 | 0.277 | 0.372 | 0 | yes |
| `tier1_blocklist` | 2 ms | 583 | 0.012 | 0.014 | 0.020 | 0.029 | 0 | yes |
| `tier1_pii` | 2 ms | 583 | 0.053 | 0.093 | 0.133 | 0.266 | 0 | yes |
| `tier2_injection` | 25 ms | 300 | 20.032 | 22.749 | 25.348 | 28.317 | 0 | **NO** |
| `tier2_toxicity` | 25 ms | 283 | 19.553 | 21.635 | 23.741 | 25.880 | 2 (fail_open ×2) | yes |

### Superseded verdict — preserved, not deleted

> The run of **2026-08-30** published these two rows as NFR-P-002 violations, rendered on **wall-clock** — the clock ADR-036 had already rejected (`[D3-nfr-p002-gate-reads-the-clock-adr-036-rejected]`):
>
> | Requirement | Detector | Stat | Budget | Measured (wall-clock) |
> |---|---|---|---|---|
> | NFR-P-002 | `tier2_injection` | P99 | 25.0 ms | **25.569 ms**, 0 faults |
> | NFR-P-002 | `tier2_toxicity` | P99 | 25.0 ms | **25.114 ms**, 2 faults |
>
> **Superseded by the attributable verdict above.** Kept because both figures are real measurements and deleting a published breach to replace it with a friendlier instrument is exactly what an instrument change must not be allowed to do (AGENTS.md §7). These are a HISTORICAL RECORD of a prior artifact, not this run's data — no figure in them is recomputed here.

## Per-detector wall-clock — UNTARGETED (the holds' constituent)

**Not a budget series, and never was a fair one** (ADR-036 item 5): for a pool detector this includes queue wait and GIL contention with whatever shared its lane. It stays published because it is what the holds are made of, and what a user waits for. Percentiles are over calls that **returned**; faulted calls are a separate row set below rather than mixed in — the A2 partition, so a fault and a breach can never read as one event counted twice.

| Detector | n | P50 | P95 | P99 | max |
|---|---|---|---|---|---|
| `numeric_claims` | 283 | 0.083 | 0.241 | 0.285 | 0.380 |
| `tier1_blocklist` | 583 | 0.015 | 0.019 | 0.026 | 0.037 |
| `tier1_pii` | 583 | 0.059 | 0.101 | 0.144 | 0.273 |
| `tier2_injection` | 300 | 20.758 | 24.667 | 26.778 | 29.130 |
| `tier2_toxicity` | 281 | 20.286 | 23.292 | 26.599 | 34.268 |

**Wall-clock of faulted calls** (`outcome=fault`) — published, separately. A timeout consumed real time; hiding it would make the breach invisible.

| Detector | n | P50 | P99 | max |
|---|---|---|---|---|
| `tier2_toxicity` | 2 | 35.826 | 45.782 | 45.985 |

**Not exercised in this run:** `conv_tracker`, `cost_budget`, `fast_consistency`, `loop_guard`, `rag_grounding`. These are unimplemented or policy-gated detectors, so their budgets are untested rather than met — the distinction M-10 draws between "checked, clean" and "never checked", applied to a benchmark.

**Implemented, but outside this harness:** `entity_enricher`. In no `LANES` row, so no lane benchmark can produce a row for it: its budget is untested **here**, which is a narrower claim than untested. Listed rather than omitted, because a detector silently missing from a latency table reads as one that met its budget.

## NFR verdict

**1 violation(s).** Per AGENTS.md §5.4 the response is a **D3 deviation** carrying the honest measured number — never a relaxed threshold.

| Requirement | Subject | Metric | Target | Measured |
|---|---|---|---|---|
| NFR-P-002 | tier2_injection | P99 | 25.0 ms | **25.348 ms** |

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

Three things this does **not** say. It is not a measurement, so it is not a D3 — a D3 needs an observed breach, and nothing here was observed: the measured sum is 109.77 ms P99 over 200 samples, against a smallest projected figure of 50 ms. It is not a claim that the budgets are wrong: 04 §2 declares them and `run_with_budget` enforces them, so a detector at budget is a detector behaving as specified. And it is not a prediction that tier2 will actually cost its full budget — a fast classifier well inside 25 ms changes the arithmetic entirely.

## Scope and limitations

**The headline figure is cadence-independent by construction**, because 06 §4 excludes upstream token wait from `total_attributable_overhead_ms`. That is verified, not assumed: `test_overhead_is_independent_of_token_cadence` runs the same mix at two cadences and asserts the figure does not track the change.

**`TestClient` transport is in the reference row, not the headline.** The in-process ASGI round trip is harness cost a real client would not pay, which is precisely why the headline reads the gateway's own recording instead of this harness's stopwatch.

**Prototype hardware, single machine, no warm-up discard.** The first requests include one-off import and compile cost, which inflates the maximum rather than the percentiles. Stated instead of trimmed: discarding a warm-up window without saying so would improve the number by choosing which measurements count.

Reproduce: `python -m eval.validate_dataset --freeze && python -m eval.bench_latency`
