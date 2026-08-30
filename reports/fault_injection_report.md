# Fail-open / fail-closed verification (06 §5)

FR-POL-006: a detector timeout or crash is resolved by the **policy's** `fail_mode` for that detector's class (04 §5) — never by the runner, never by a code-level preference. This report injects one fault and reads the consequence back out of the audit record. Feeds demo beat 7 / SC-3.

## Provenance

| Field | Value |
|---|---|
| Generated (UTC) | 2026-08-30T08:02:34+00:00 |
| Dataset digest | `6a3ecbbe75fd020bf806bf647d572c85ee187198fb9828eaac5e1c6e00737fbd` |
| Frozen at | `f162959f7d29` — MATCHES |
| Probe case | `CLN-001` (frozen; prompt **and** stub response) |
| Injected fault | `DetectorTimeout` (06 §5 "raise timeout") |
| Code commit | `27f0c2f98cac` + uncommitted changes |
| Python | 3.14.6 |
| Platform | Linux 7.1.2-arch3-1 · x86_64 |
| Command | `python -m eval.fault_injection --reps 5` |
| Host load at start (1/5/15) | 0.52 / 0.93 / 1.0 · 12 CPUs — **QUIET** |
| Host load at end (1/5/15) | 0.81 / 0.97 / 1.01 · 12 CPUs — **QUIET** |

> **Upstream provenance:** the active provider `kiro-local` is **dev-class**, which `require_measured_upstream()` refuses for judge-facing output (ADR-018). **This report is unaffected:** the upstream is a stub, so no verdict below involves a provider call, a token count, or a price. Every result is produced by local detectors and the policy engine. The gate is therefore **evaluated and non-binding here**, and becomes binding the moment this harness reports anything upstream-derived.

## Method

1. Probe text is `CLN-001` from the frozen dataset — used as **both** the prompt and the stub's response, and verified clean through every live detector. A faulted verdict is therefore attributable to the fault, not to content.
2. For each use case: one **control** request with no fault, then one request per exercisable fail_mode class with `DetectorTimeout` injected into that class's live detector at the output stages only (the input lane keeps working, so an input-lane short-circuit cannot be mistaken for an output-lane fail-closed).
3. Every assertion is evaluated against `canonical_view` of the request's audit record (05 §4) — not against the HTTP response. The response is what the client saw; 04 §5's claim is about what the system recorded about its own failure.
4. The upstream is a stub: no network, no credential, no token accounting.

## Class coverage

Which of the four 04 §3 classes can carry a fault today. Derived from `DETECTOR_FAIL_CLASS ∩ pipeline.LIVE`, never hardcoded — a new detector changes this table without an edit.

| Class | Live carrier | Exercisable | Modes across the three policies |
|---|---|---|---|
| `tier1` | `tier1_pii` | yes | UC-1 fail_closed · UC-2 fail_closed · UC-3 fail_closed |
| `tier2` | `tier2_toxicity` | yes | UC-1 fail_open · UC-2 fail_open · UC-3 fail_closed |
| `performance` | `rag_grounding` | yes | UC-1 fail_open · UC-2 fail_open · UC-3 fail_closed |
| `cost` | — none live — | **no** | UC-1 fail_open · UC-2 fail_open · UC-3 fail_closed |

## SC-3 — one identical fault, two opposite outcomes

### `tier2` — fault injected into `tier2_toxicity`

| Pipeline | Configured `fail_mode` | Verdict | HTTP | Fault recorded | Drove the verdict |
|---|---|---|---|---|---|
| UC-1 `support_bot` | `fail_open` | **pass** | 200 | yes | no |
| UC-2 `hr_copilot` | `fail_open` | **pass** | 200 | yes | no |
| UC-3 `finance_advisor` | `fail_closed` | **escalate** | 202 | yes | yes |

The last two columns are the substance of ADR-027 Amendment 1 and are **different facts**. Under `fail_open` the fault is recorded (`detector_failures_json`) but absent from `failure_record_ids`: it happened, it is auditable, and it changed nothing. Under `fail_closed` it appears in both. A single boolean could not express the difference, which is why the step-5 stamp is stored rather than reconstructed by filtering on `fail_mode_applied`.

### `performance` — fault injected into `rag_grounding`

| Pipeline | Configured `fail_mode` | Verdict | HTTP | Fault recorded | Drove the verdict |
|---|---|---|---|---|---|
| UC-1 `support_bot` | `fail_open` | **pass** | 200 | yes | no |
| UC-2 `hr_copilot` | `fail_open` | **pass** | 200 | yes | no |
| UC-3 `finance_advisor` | `fail_closed` | **escalate** | 202 | yes | yes |

The last two columns are the substance of ADR-027 Amendment 1 and are **different facts**. Under `fail_open` the fault is recorded (`detector_failures_json`) but absent from `failure_record_ids`: it happened, it is auditable, and it changed nothing. Under `fail_closed` it appears in both. A single boolean could not express the difference, which is why the step-5 stamp is stored rather than reconstructed by filtering on `fail_mode_applied`.

## Controls (no fault injected)

Without these, "UC-3 escalates under fault" is unfalsifiable — a policy that escalated everything would look like a working fail-closed mechanism.

| Pipeline | Verdict | HTTP | Failures recorded |
|---|---|---|---|
| UC-1 `support_bot` | pass | 200 | none |
| UC-2 `hr_copilot` | pass | 200 | none |
| UC-3 `finance_advisor` | pass | 200 | none |

## Assertions

39/39 passed in this repetition — the final one of 5. The rate across all repetitions is the citable figure; see *Reproducibility* below.

| Result | Assertion | Evidence |
|---|---|---|
| PASS | support_bot: control (no fault) passes | `verdict='pass' failures=[]` |
| PASS | support_bot/tier1: verdict is escalate | `verdict='escalate' (HTTP 200)` |
| PASS | support_bot/tier1: fault present in detector_failures_json | `failures=['tier1_pii'] modes=['fail_closed']` |
| PASS | support_bot/tier1: fail_mode_applied is fail_closed | `modes_applied=['fail_closed']` |
| PASS | support_bot/tier1: fault stamped in failure_record_ids | `failure_record_ids=['c01f9b7f-6bf6-4664-a185-fb340b8bbb00']` |
| PASS | support_bot/tier2: verdict is pass | `verdict='pass' (HTTP 200)` |
| PASS | support_bot/tier2: fault present in detector_failures_json | `failures=['tier2_toxicity'] modes=['fail_open']` |
| PASS | support_bot/tier2: fail_mode_applied is fail_open | `modes_applied=['fail_open']` |
| PASS | support_bot/tier2: fault did NOT contribute to the verdict | `failure_record_ids=[] (expected empty)` |
| PASS | support_bot/performance: verdict is pass | `verdict='pass' (HTTP 200)` |
| PASS | support_bot/performance: fault present in detector_failures_json | `failures=['rag_grounding'] modes=['fail_open']` |
| PASS | support_bot/performance: fail_mode_applied is fail_open | `modes_applied=['fail_open']` |
| PASS | support_bot/performance: fault did NOT contribute to the verdict | `failure_record_ids=[] (expected empty)` |
| PASS | hr_copilot: control (no fault) passes | `verdict='pass' failures=[]` |
| PASS | hr_copilot/tier1: verdict is escalate | `verdict='escalate' (HTTP 200)` |
| PASS | hr_copilot/tier1: fault present in detector_failures_json | `failures=['tier1_pii'] modes=['fail_closed']` |
| PASS | hr_copilot/tier1: fail_mode_applied is fail_closed | `modes_applied=['fail_closed']` |
| PASS | hr_copilot/tier1: fault stamped in failure_record_ids | `failure_record_ids=['36c105c1-6931-48ea-b63c-5bd7e1696753']` |
| PASS | hr_copilot/tier2: verdict is pass | `verdict='pass' (HTTP 200)` |
| PASS | hr_copilot/tier2: fault present in detector_failures_json | `failures=['tier2_toxicity'] modes=['fail_open']` |
| PASS | hr_copilot/tier2: fail_mode_applied is fail_open | `modes_applied=['fail_open']` |
| PASS | hr_copilot/tier2: fault did NOT contribute to the verdict | `failure_record_ids=[] (expected empty)` |
| PASS | hr_copilot/performance: verdict is pass | `verdict='pass' (HTTP 200)` |
| PASS | hr_copilot/performance: fault present in detector_failures_json | `failures=['rag_grounding'] modes=['fail_open']` |
| PASS | hr_copilot/performance: fail_mode_applied is fail_open | `modes_applied=['fail_open']` |
| PASS | hr_copilot/performance: fault did NOT contribute to the verdict | `failure_record_ids=[] (expected empty)` |
| PASS | finance_advisor: control (no fault) passes | `verdict='pass' failures=[]` |
| PASS | finance_advisor/tier1: verdict is escalate | `verdict='escalate' (HTTP 202)` |
| PASS | finance_advisor/tier1: fault present in detector_failures_json | `failures=['tier1_pii'] modes=['fail_closed']` |
| PASS | finance_advisor/tier1: fail_mode_applied is fail_closed | `modes_applied=['fail_closed']` |
| PASS | finance_advisor/tier1: fault stamped in failure_record_ids | `failure_record_ids=['1c07daac-9beb-47f7-9255-4985194548c8']` |
| PASS | finance_advisor/tier2: verdict is escalate | `verdict='escalate' (HTTP 202)` |
| PASS | finance_advisor/tier2: fault present in detector_failures_json | `failures=['tier2_toxicity'] modes=['fail_closed']` |
| PASS | finance_advisor/tier2: fail_mode_applied is fail_closed | `modes_applied=['fail_closed']` |
| PASS | finance_advisor/tier2: fault stamped in failure_record_ids | `failure_record_ids=['fdd2314b-f828-435e-9d08-09ce26f94ba8']` |
| PASS | finance_advisor/performance: verdict is escalate | `verdict='escalate' (HTTP 202)` |
| PASS | finance_advisor/performance: fault present in detector_failures_json | `failures=['rag_grounding'] modes=['fail_closed']` |
| PASS | finance_advisor/performance: fail_mode_applied is fail_closed | `modes_applied=['fail_closed']` |
| PASS | finance_advisor/performance: fault stamped in failure_record_ids | `failure_record_ids=['558c4434-49fd-41ff-aa5e-03e2f8194887']` |

## Reproducibility across repetitions

**5/5 repetitions reached 39/39.** All 5 repetitions stayed within the 06 §8 quiet threshold (`load1 <= 1.0`) at both ends, so the spread below is the system's rather than the host's.

| Rep | Passed | load1 start | load1 end | Quiet (06 §8) | Failing assertion |
|---:|---:|---:|---:|---|---|
| 1 | 39/39 | 0.52 | 0.81 | yes | none |
| 2 | 39/39 | 0.81 | 0.81 | yes | none |
| 3 | 39/39 | 0.81 | 0.81 | yes | none |
| 4 | 39/39 | 0.81 | 0.81 | yes | none |
| 5 | 39/39 | 0.81 | 0.81 | yes | none |

The assertions that did not hold in every repetition:

- none — every assertion held in every repetition

### What these repetitions do and do not establish

**They share one process, and therefore one warmed model pool.** The first repetition pays first-touch ONNX graph initialization; every later one runs against models already resident. So this rate measures the **warmed steady state**, which is the demo's condition but not the harness's cold one — a fresh process per repetition is a different and slower measurement, and it is where the [[M-53]]/[[M-60]] flake was originally observed. A clean rate here therefore does **not** retire that mechanism; it bounds it to the cold path and to contention.

**The load-sensitive failure did not reproduce in this run, which is not the same as absent.** The mechanism is documented: a budget overrun is recorded as a *detector fault*, so a pool-serialized detector running slow manufactures a fault on a probe where none was injected, and the control assertion correctly reads that as a broken invariant. It was observed on this host across **separate** harness processes at `load1` below the quiet threshold ([[M-60]]). Reporting a clean in-process rate as evidence that it is fixed would be the error; the assertion stays unrelaxed (AGENTS.md §5.4) precisely so the next occurrence is visible.

### Superseded single-run claim — preserved, not deleted

> The run of **2026-08-30** published this suite as **`39/39 passed`** from a single repetition, with no load stamp ([[M-54]]) and therefore no way for a reader to check the quiet-host condition the figure depended on.
>
> That number is a real measurement of one run and is kept for that reason. What was wrong was the **claim shape**: a single run cannot state a rate, and this suite's control-probe assertions are load-sensitive, so one clean run and a reproducible invariant are different facts. Superseded by the rate above; no figure in this blockquote is recomputed by this run.


## Scope and limitations

**06 §5 and 07 beat 7 both name `tier2`, and this run carries SC-3 on `tier2` — the substitution is retired.** It stood for two phases and for two different reasons: first nothing tier2 existed to monkeypatch, then `tier2_injection` shipped but runs at INPUT (04 §2) while faults are injected only at the OUTPUT stages (`FAULT_STAGES`), where a fault is a response-in-flight decision rather than a short-circuit before dispatch. `tier2_toxicity` (OUTPUT_SENTENCE) closes it, and the harness needed no edit: `faultable()` derives coverage rather than listing it. `performance` is still shown alongside, now as corroboration rather than a stand-in — FR-POL-006 is stated per detector *class*, and two classes with the same two-sided configuration showing the same contrast is a stronger result than one. `test_tier2_carries_sc3_on_the_class_the_docs_name` holds the line from the other side: it fails if tier2 ever stops being carried.

**Classes with no live carrier:** `cost`. Their `fail_mode` values are still read from config and shown above, so the configuration is visible even where the mechanism is not yet exercisable.

**`tier1` is live but cannot show a contrast:** all three policies set `tier1: fail_closed`, so it has no fail-open side. It is exercised and asserted anyway — unanimity is a fact worth showing beside a class where the policies disagree.

Reproduce: `python -m eval.validate_dataset --freeze && python -m eval.fault_injection`
