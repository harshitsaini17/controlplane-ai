# 08 — Open Questions

Format: Question / Why it matters / Options / Current assumption / Deadline / Status.
Agents: check here before raising a D4 deviation; MINOR gaps you resolve get logged here (AGENTS.md §6).

---

**Q-01 — Round 2 video length limit?**
Why: Round 1 limit was 3 min; the drafted script ran 5:00; Round 2 brief (our copy) doesn't state a limit.
Options: (a) confirm from portal/organizer email, (b) assume 3 min and cut.
Assumption: **3 minutes until confirmed** — storyboard must be cuttable to 3:00.
Deadline: before storyboarding. Status: OPEN

**Q-05 — Include conversation-level cumulative tracking (P2) in demo?**
Why: strong differentiator (brief's multi-turn/agentic complexity) but last-priority build item.
Assumption: build FR-DET-006 only after all P0+P1 green; demo beat 8 mentions it as roadmap if not landed.
Deadline: final week triage. Status: OPEN

**Q-06 — Team details for submission template**
Why: Accenture PPTX template requires names/college/stream/photos; repo must be public — decide what personal info goes where.
Assumption: template gets full details; public repo README gets names only (no photos/emails).
Deadline: before submission packaging. Status: OPEN

**Q-07 — Semantic-entropy deep audit: real NLI clustering or embedding-cluster approximation?**
Why: true NLI pairwise entailment on 5 samples may be slow/heavy for the worker; embedding clustering is a documented approximation.
Options: (a) NLI model pairwise, (b) embedding + agglomerative clustering labeled as approximation.
Assumption: (b), honestly labeled in report + proposal ("entropy over embedding-similarity clusters, an approximation of Farquhar et al.").
Deadline: deep-lane sprint. Status: OPEN

**Q-08 — Hosting for judges (live URL vs local-only)?**
Why: public repo is required; a live demo URL is not — but might impress.
Assumption: local-only + demo video; revisit only with time surplus (respect charter NG1).
Deadline: final week. Status: OPEN

**Q-10 — Which genuinely local model serves fallback + second-sample duty?** (reopened from Q-02 by ADR-018)
Why: three things lean on it — the `fail_open` path when the upstream is unreachable mid-demo, the parallel 2nd sample `fast_consistency` needs (04 §2.3, ~2× tokens wherever sampling occurs), and `--replay` recording generation. It is also the only provider that could be `measured` at zero marginal cost, which is what makes the cost plane demonstrable without spending real money.
Evidence closing the previous ruling: Q-02 named `llama-3.2-3b via Ollama`, but **no such model is installed**. The single model present is `minimax-m2.7:cloud`, whose manifest carries `remote_host: https://ollama.com:443` — a cloud model reached through a local CLI, so it fails the no-`remote_host` assertion and cannot honestly be classed local. `config/gateway.yaml`'s `ollama-local` entry is therefore `STUB`-marked with both `tiers` null: it is a declared shape, not a working provider.
Options: (a) `ollama pull` a small genuinely-local model (~2 GB) and assert no `remote_host` in its manifest before classing it; (b) drop the local provider and accept that fail-open has no fallback target and consistency sampling costs real Groq tokens; (c) keep the entry declared-but-null and let FR-GW-006's loud-fallback rule surface the gap at boot.
Assumption: **(a)**, gated on the assertion actually passing — the entry stays `STUB` until then. Until it passes, treat fallback as unavailable rather than as working, and never report a fallback latency or cost number from it (AGENTS.md §7).
Deadline: before the consistency detector sprint (it needs the 2nd sample) — earlier if the cost plane is demoed. Status: **RESOLVED 2026-08-28** — option (a), on owner evidence.

**Ruling (2026-08-28).** `llama3.2:3b` serves the small tier of `ollama-local`; the assertion the
assumption was gated on **passed** — a manifest grep shows no `remote_host`, so it is local in the
sense ADR-018 requires and the `unmetered` claim holds (its tokens are billed to no one). `frontier`
stays null: exactly one local model is evidenced, and binding both tiers to one id would make the
cascade a no-op while looking configured. The `STUB` markers are removed from `config/gateway.yaml`
and **SL-4** is closed.

⚠ **The evidence is host-specific, and that is recorded rather than smoothed over.** It comes from
the **owner's** machine (Apple Silicon, Ollama **v0.33.0**): a direct probe served real usage counts
and the FR-GW-006 canary passed as measured-class. The **development host** these docs were written
on runs Ollama **v0.31.1** and serves exactly one model — `minimax-m2.7:cloud`, carrying
`remote_host: https://ollama.com:443`, the original SL-4 condition, re-confirmed 2026-08-28. So on
that host the bound id names nothing and a dispatch to this provider fails; `ollama pull llama3.2:3b`
is the whole fix. Neither report is wrong — they describe different hosts — which is why the binding
is recorded with the host it was verified on. Two consequences follow, and both are constraints
rather than caveats: **no test may depend on a live local dispatch** (the config-level assertion is
what `tests/test_gateway_config.py` pins), and **no fallback latency or cost figure from this
provider may be reported from the development host**, since it cannot produce one — the AGENTS.md §7
rule the original assumption stated, still in force for the same reason.

Kept in place rather than relocated to *Resolved*: the housekeeping note further down records
dependents being **stranded** under this very question's heading when it last moved, and this entry
now has more dependents than it had then, not fewer.

Status: **RESOLVED**


---

## Deviation ledger

Every deviation report filed against this repo, and its current status. **This table is what
AGENTS.md §11's "enumerate every open deviation" rule is enumerated from** — before this,
slugs lived scattered across doc prose, YAML comments, docstrings and test notes, which made
"is anything still open?" a question only a full-tree grep could answer.

| Slug | Sev | Filed | Status |
|---|---|---|---|
| `[D1-band-logic-vs-beat-4b]` | BLOCKER | Phase 1 | **CLOSED** — ADR-017 (per-label band + required `borderline_action`) |
| `[D4-enriched-label-survival-semantics]` | BLOCKER | Step 2 | **CLOSED** — ADR-019 (two branches; the band never reaches an enriched label) |
| `[D4-input-stage-pii-edit-unresolvable]` | MAJOR | Step 2 | **CLOSED** — ADR-020 (input EDIT = pre-dispatch redaction; overruled the report's own recommendation) |
| `[D2-nonstreaming-token-counts-inflated]` | MAJOR | Step 1 | **CLOSED** — ADR-018 root-caused it as a provenance problem; the dev/measured split is the structural answer and FR-GW-006's canary catches recurrences at boot |
| `[D2-upstream-price-table-absent]` | MINOR | Step 1 | **CLOSED** — ADR-022 makes `pricing: null` a legitimate, documented state meaning UNKNOWN (distinct from `unmetered`, which is an affirmative zero) |
| `[D2-price-table-cannot-express-per-tier-cost]` | MAJOR | Step 2 | **CLOSED** — ADR-022 (prices keyed by concrete model id) |
| `[D3-tier1-pii-recall-below-target]` | **MAJOR** | Step 4 | **CLOSED** — ruled by ADR-026 (disclosed revision), patterns re-derived from named published specs, re-measured **once**: recall **0.8361 → 0.8852**, precision 1.000 both. **NFR-EVAL-001 remains UNMET and the target was not moved.** The residual 7 misses are **7/7 the documented bare-7-digit scope exclusion** (ADR-026 §3), verified programmatically. Closing this deviation closes the *decision*, not the gap — the gap is tracked permanently as **SL-1** below |
| `[D8-numeric-claims-treats-identifiers-as-statistics]` | **MAJOR** | Step 4 | **CLOSED** — ruled by ADR-025: the 04 §2 bare large-digit-run clause was **deleted**, not tuned. Precision **0.2667 → 0.8571** with recall **unchanged at 0.750**, so nothing was traded for the gain. The deletion is asserted positively in `tests/test_numeric_claims.py`, so re-introducing the rule fails the suite |
| `[D2-detector-params-cannot-hold-list-values]` | MINOR | ADR-025 | **CLOSED** — ruled: `detector_params` widened to `dict[str, dict[str, ParamValue]]` where `ParamValue = str\|int\|float\|bool \| list[...]`. pydantic v2 smart mode preserves `1` as int and `True` as bool across the union; validation test added; 04 §3 records it |
| `[D1-citation-marker-per-matches-the-rate-preposition]` | **BLOCKER** | ADR-025 impl | **CLOSED** — ruled by ADR-025 Amendment 1 **before** the single permitted re-measurement, so ADR-026 §5 was not strained. Bare `per ` removed; three attribution forms added (`as per`, determiner, proper-noun). Verified on the corpus pre-measurement: HAL-049/052 no longer suppressed, CLN-062 still correctly suppressed |
| `[D2-nanp-n-constraint-rejects-nothing-as-composed]` | **MAJOR** | ADR-026 impl | **CLOSED** — ruled: keep the composition, correct the description (ADR-026 Amendment 1). v1's `_PHONE` is deliberately retained and shadows both NANP rows, which therefore add **zero recall**; the whole v2 phone gain is E.164 + the spaced-parenthesis variant. Narrowing `_PHONE` would break v2's superset property and orphan the permanent v1 baseline. Precision hardening → **SL-2** |
| `[D2-adr-026-eyj-derivation-is-arithmetically-wrong]` | MINOR | ADR-026 impl | **CLOSED** — correction ratified (the error was the adjudicator's). ADR-026 carries a dated Correction block **preserving the original false claim verbatim** before refuting it with the arithmetic. The test pair asserting the false literal *as false* is retained as the artifact |
| `[D2-report-emits-a-q18-publication-gate-adr-025-lifted]` | **MAJOR** | ADR-026 §5 run | **CLOSED** — ruled by **ADR-026 Amendment 2**: the §5 no-touch rule binds measurement-affecting code, not presentation prose, subject to four conditions. Note corrected; figure identity **PROVEN** and committed as `reports/eval_report_prose_fix.diff`. Logged under *Prose-fix log* below (clause (d)) |
| `[D5-detector-failure-signal-is-unconstructible]` | **MAJOR** | Phase 3 | **CLOSED** — ruled by **ADR-027**, Option B: a detector fault is an **operational event, not a content risk** (no span, no plane, not detector-emitted, not policy-mapped), so the closed 04 §1.1 taxonomy is right to reject it and `Signal` is right to refuse to construct it. 04 §5 rewritten around `DetectorFailureRecord`; `detector_failures_json` added to 05 §3/§4; the §4.3 step-5 stamp now names contributing signal_ids **+ failure_record_ids**; review-queue `escalation_cause` added to 05 §2; 06 §5 reads the new field. Resolution semantics unchanged — `fail_closed` is an **ESCALATE floor**, never an override, so a genuine content BLOCK still wins |
| `[D1-usage-canary-has-no-independent-count-on-the-measured-class]` | **BLOCKER** | Phase 4 | **CLOSED** — ruled by **ADR-028**: the reference count is **repo-local** (`method: local_estimate`, estimator named in the result), never a provider endpoint, because comparing `count_tokens` against `usage.prompt_tokens` put both sides of the check in the hands of the party being audited. Ratio bound + absolute floor, ANDed (`max_ratio: 2.0`, `min_delta_floor: 50`); consequences unchanged (measured fails boot, dev warns). Scope stated in 01/05: **gross** corruption, not a fine-grained accounting audit. **The filed recommendation (option B) was NOT adopted** — it compared two provider-reported counts, so the ruling's rationale defeats it too; recorded in the ADR rather than read as convergence |
| `[D5-adr-027-stamp-has-no-column-in-the-05-3-ddl]` | **BLOCKER** | Phase 4 | **CLOSED** — ruled by **ADR-027 Amendment 1**, Option A: two `TEXT NOT NULL DEFAULT '[]'` columns added to the 05 §3 DDL. The non-derivability analysis is ratified into the amendment — `detector_failures_json` carries fail_open records, the escalate floor leaves a content BLOCK standing, and `contributing_signal_ids` is a strict subset of `signals_json` by design — so the stamp is **stored, not derived**; `escalation_cause` derives from the stored columns. Round-trip verified (21 columns, `[]` not NULL when empty); 10 tests added, all 6 mutants killed including the one reproducing this defect. No migration needed: no `.db` existed |
| `[D2-groq-tier-ids-shut-down-no-production-qwen-exists]` | **MAJOR** | Phase 5 | **CLOSED** — ruled by **ADR-029**, Option B (`openai/gpt-oss-20b` / `openai/gpt-oss-120b`). Both previously-bound llama ids were shut down 2026-08-16; probed live 2026-08-27, both return **HTTP 404 `model_not_found`** on this repo's key, so it is not on the exempt committed-spend contract and the rebinding is forced. **The filed recommendation (option A, `qwen/qwen3.6-27b` frontier) was OVERRULED** — that pair's frontier tier is smaller, less capable and 5x costlier than the one chosen, so it existed only to preserve a test ratio, and a number from an economically irrational config is harness-fitting by construction. The probe independently justified the overrule: qwen emits its `<think>` trace into the response body, which would have pushed reasoning scaffolding through the sentence buffer into every output-lane detector. **ADR-009 amended in the same commit** — the cascade premise is now ratio-parametric (2.0x shipped, blend-independent) and the `>5x` assertion was amended through the front door, not loosened. `reports/` and `demo/` grepped: **no committed figure referenced either dead id**, so no published number moved |
| `[D1-tier2-budgets-cannot-coexist-with-nfr-p-001]` | **MAJOR** | Phase 5 | **CLOSED** — ruled by **ADR-030**, the Option A direction as a **front-door respecification**. NFR-P-001 is re-scoped onto the **user-perceived hold** (input-lane hold, and each per-sentence hold), with targets **derived from the 04 §2 budgets** rather than chosen to fit; the per-request sum keeps being published as `total_attributable_overhead_ms` with no target, and `added_time_to_last_byte_ms` is added as a measured untargeted row. Filed from a **projection**, never a measurement, and ruled **before any Tier-2 figure exists** — the anti-laundering record is verbatim in ADR-030, and ADR-026 §5's bar on moving a *missed* target is untouched (SL-1 stays unmet and unmoved). The derivation surfaced three gaps of its own rather than hiding them: **M-18**, **M-19**, **M-20** |
| `[D3-tier2-injection-budget-cannot-hold-on-unbounded-input]` | **MAJOR** | Phase 5 | **CLOSED 2026-08-28** — ruled by **ADR-032**. Prefix truncation (this report's own recommendation A) was **OVERRULED**: a documented "we score the first N tokens" is an evasion recipe, and the interception guarantee is the product. Full coverage via strided windows (104 tokens / overlap 26 / step 76, MAX over windows) instead — which also closes the **512-token blind spot** this report found, the more serious half of it: an injection at token 3000 was previously never scored at all. The budget question the report raised is answered by the same ADR: NFR-P-002's <25 ms is scoped to single-window inputs, where it is measured to hold at 13.01 ms P99 |
| `[D3-full-coverage-windows-cost-600ms-at-the-policy-bound]` | **MAJOR** | Phase 5 | **CLOSED 2026-08-28** — ruled by **ADR-032**; the measured cost is **ACCEPTED and PUBLISHED**, and full coverage stands. Recorded rationale: cost scales with window count, window count scales with input length, so the guard's cost concentrates on exactly the long inputs where pad-then-inject attacks live — a typical single-window prompt pays 11.30 ms P50 / 13.01 ms P99. Pre-dispatch position is non-negotiable (optimistic dispatch would deliver the payload upstream, which is the event the gate exists to prevent). Batch size bound to **4**, not the nominal minimum 2: 599.20 vs 602.66 ms differ by 0.6%, inside this harness's own run-to-run spread, so the minimum over-fits one run. This report's cross-validation note is **corrected** in ADR-032 — 11.30 ms is the *faster* figure, not the conservative one, and the 11.30-vs-14.27 gap is ~26% run-to-run variance, not a synthetic-vs-real content effect (both harnesses time `sess.run` only, and a fixed 104-token tensor costs the same FLOPs whatever fills it) |

| `[D1-not-run-vocabulary-cannot-say-dependency-absent]` | **MAJOR** | Phase 5 | **CLOSED 2026-08-28** — ruled by **ADR-033**, which adds the third lifecycle state the vocabulary lacked: *registered but unloadable*, recorded in a new `detectors.unavailable[]` list ({detector, missing}) rather than as a `not_run` reason or a `DetectorFailureRecord`. `dependency_unavailable` was deliberately **not** added to `NOT_RUN_REASONS` — that would restate an environment fact once per request while leaving unanswerable whether the coverage promise was ever keepable. The D7 edge the filing flagged is answered by **boot-time enforcement** mirroring FR-GW-006: any active policy mapping the detector's class to `fail_closed` refuses the boot outright, so `finance_advisor`'s `tier2: fail_closed` can no longer be silently unhonoured — the process does not start. Fail-open-only policy sets boot with a loud warning and carry the entry per affected request, plus `cp_detector_unavailable_total{detector}`. Filed 2026-08-28 while landing `tier2_toxicity` (Phase 5 item 2), **before any detector code was written**. 05 §4 fixes `not_run[].reason` to a closed vocabulary whose single member `not_implemented` it defines as *"the detector has no live implementation in this phase"*, and `_check_detectors` enforces it — a probe confirms `dependency_unavailable` is refused outright. The moment a model-backed detector gains an implementation, a host without the `[ml]` extra has **no truthful value to record**: the detector exists, so `not_implemented` is a false statement, and it is the only member admitted. That host is not hypothetical — `.github/workflows/ci.yml` installs `.[dev]` only and says the model stack is *deliberately* absent, so CI is the case. Two further consequences: a binding import at module scope would break the gateway import there outright, and because 05 §4 states that a not-run entry is **not** a `DetectorFailureRecord` ("no attempt was made, so there is no fault"), `finance_advisor`'s `tier2: fail_closed` is **silently not honoured** on such a host — the request passes with a coverage note. Generic, not toxicity-specific: `rag_grounding` (sentence-transformers) and `entity_enricher` (spaCy) reach it identically, which is why it wants one ruling rather than three ad-hoc choices. **Filed D1 but carrying a D7 edge, stated so the ruling can weigh it:** "a fail-closed behaviour not honoured" is D7's own language. It is filed MAJOR rather than BLOCKER because the *behaviour* is not a regression — a detector that is not live does not honour `fail_closed` today either — so what breaks is the **record's truthfulness**, not a protection that currently works. If the ruling reads the silent non-enforcement as the primary harm rather than the record, this is a BLOCKER and the severity should be raised on that basis, not on mine |
| `[D1-added-time-to-last-byte-has-no-server-side-vantage]` | **MAJOR** | Phase 5 | **CLOSED 2026-08-28** — ruled by **ADR-030 Amendment 1**, Recommendation B: the figure is **re-sited, not withdrawn**. 06 §4 becomes its normative home as a **benchmark-client** quantity, and it is withdrawn from 05 §3/§5 — mechanically, since `check_latency_keys` enforces that vocabulary at the write path. It **aliases and absorbs** `reference_delta_ms` rather than joining it as a second series (one subtraction under two names invited the reading that one was uncontaminated), keeping both standing caveats: an **upper bound** (`TestClient` ASGI cost) and **never the headline number**. The four-ways-closed analysis is ratified into the amendment. **M-20 closes with it**, as a specification correction rather than an emission — the emission was never constructible. The checkpoint-3 tripwire fired on the transition and was **re-pointed, not deleted** (ADR-031 consequence 5's rule), now pinning the re-siting in both directions: the enforced vocabulary must not grow the key back, and 06 §4 must keep defining it. Filed 2026-08-28 while closing out **M-20**'s remainder (Phase 5 item 10), **before any code was written**. 06 §4 defines `added_time_to_last_byte_ms` as *"client-observed last-byte time minus the same request's upstream duration"*, and 05 §3 puts it in `latency_json` — a column the **gateway** writes. The gateway has no such vantage on either path: the buffered write at `app.py:586` precedes `return JSONResponse(...)` at `:632` (an ordering **M-13** established deliberately, so "audit later" reopens a closed gap), and the streaming write at `:875` runs inside the generator after the final `yield`, where a completed ASGI `send()` means *handed to the transport*, not received. There is no second phase to carry a post-delivery figure — the table is insert-only (no `UPDATE audit_records` in `controlplane/`) and `record_status` is a crash marker. Meanwhile `eval/bench_latency.py:237` already computes 06 §4's formula client-side as `reference_delta_ms`, but publishes it as a contaminated **upper bound** (`TestClient` ASGI cost), "never the headline number" — so the two cannot be equated by a rename | Filed **D1**, not D3: nothing is targeted and nothing measured breached: the documented design is not constructible from where the doc sites it. MAJOR because the row is untargeted, so NFR-P-001 keeps its verdict and no other Phase-5 item waits on it; the §7 edge — emitting a handoff delta under a name that claims a client vantage — would justify rounding up |
| `[D1-windowed-injection-cannot-be-enforced-by-a-per-call-budget]` | **MAJOR** | Phase 5 | **CLOSED 2026-08-28** — ruled by **ADR-034**, Recommendation A approved **and extended** with a generic execution-vehicle ruling the filing did not ask for: every CPU-bound model detector (`tier2_injection`, `tier2_toxicity`, `rag_grounding`, `fast_consistency`, `entity_enricher`) runs inference on a dedicated **single-worker `ThreadPoolExecutor`, awaited** — never inline on the loop. That is what makes `asyncio.wait_for` an enforcement point at all rather than a dead letter, and ONNX Runtime's GIL release is what keeps the loop live for concurrent requests; `max_workers=1` preserves SL-5's one-inference-at-a-time conditions and queue wait counts inside the ceiling. Recorded caveat: a timed-out executor task is **abandoned, not killed** (Python cannot preempt a thread), so the request proceeds under `fail_mode` while the thread finishes — counted by `cp_detector_timeout_abandoned_total`. The budget half is the filing's own option A: the per-window budget is enforced **inside** the detector and the runner's ceiling becomes **length-parametric**, derived from ADR-032's measured series, so the ceiling now means *"materially slower than its own measured envelope"* rather than *"longer than one window's budget"* — which is what dissolves the fail-mode pathology (`finance_advisor` no longer blocks every long input; the two `fail_open` pipelines no longer silently skip them). Two derivation points were resolved MINOR-style inside the ruling rather than assumed, and both are logged as **M-30**/**M-31** rather than left in prose: the envelope is grounded on ADR-032's **1-thread** column (the columns differ by **3.9x**, so a 2x factor over the optimistic figures sits *below* the pessimistic cost and would trip on contention alone), and the runner's window count is the detector's **exact** count rather than a character bound — measured chars/token spans **1.0 to 800** against a corpus median of 4.29, which would have turned a ~5.5 s envelope into a ~24 s ceiling on typical text and is unsound outside WordPiece. Filed 2026-08-28 while landing Phase 5 item 2, **before any detector code was written**. 04 §2 budgets `tier2_injection` **per 104-token window** and ADR-032 accepts ~651 ms for the 52-window bound case, but `BUDGETS_MS` is a flat per-call scalar and `pipeline.py:280` hands it straight to `asyncio.wait_for`. Measured on this interpreter: the correct (loop-yielding) detector shape is cancelled at 25 ms, while the incorrect (loop-blocking) one passes by stalling the event loop for the full duration — the two viable implementations fail in opposite directions and there is no third. A cancellation is not benign: it resolves under `fail_mode`, so `finance_advisor`'s `fail_closed` would block every multi-window input and the two `fail_open` policies would silently not scan them — reopening the 512-token blind spot ADR-032 consequence 2 claims to have closed. `tier2_toxicity` is unaffected (one window, 8.58 ms P99) |
| `[D1-input-hold-target-cannot-survive-multi-window-injection]` | **MAJOR** | Phase 5 | **CLOSED 2026-08-28** — ruled by **ADR-030 Amendment 2**, Recommendation A: `input_hold_ms`'s P50/P99 targets are **scoped to single-window inputs** and multi-window holds are published as an untargeted **window-count-bucketed** series (the per-request-sum precedent, **third** use); `bench_latency --check` gates only the single-window population, because a gate that stayed red on every long prompt is indistinguishable from a broken gate. The ruling establishes something about the record rather than only about the target: **the clause was already issued** as item 3 of the adjudication that produced ADR-032 and **did not survive transcription** — verified, not asserted, since ADR-032's committed text mentions `NFR-P-001` nowhere and names only NFR-P-002 in its "Docs touched" line. So this deviation was a real doc-versus-doc contradiction **in the committed record**, and the scoping it asks for was re-derived from scratch one detector later by a reader who could only see the committed text. **Process rule adopted from it:** when an issued adjudication clause is absent from the ADR transcribed from it, that is **drift** — diff the issued ruling against the transcription **before** closing the deviation it resolves. Anti-laundering record intact: filed and ruled from a projection over ADR-032's measured table **before** the detector exists, which is the ground `[D1-tier2-budgets-cannot-coexist-with-nfr-p-001]` stood on and precisely what distinguishes it from what ADR-026 §5 bars; **SL-1 stays unmet and unmoved**. Filed 2026-08-28, same reading. **Doc-versus-doc between two accepted ADRs**, which §3 precedence does not settle: ADR-030 derives NFR-P-001's input-lane hold (P50 < 40 ms, P99 < 50 ms) from a 30 ms worst case whose dominant term is `tier2_injection 25`, and ADR-032 then measured that term at 23.28 ms P50 for 2 windows and 651.41 for 52 — inside `input_hold_ms` by 06 §4's own definition. ADR-032 scoped **NFR-P-002** and left NFR-P-001 untouched, so the derivation still asserts a bound its own successor has measured at ~13×. Filed from a **projection** built on ADR-032's measured table, and deliberately **before** the detector exists — the same ground `[D1-tier2-budgets-cannot-coexist-with-nfr-p-001]` stood on, and the fact that makes a post-hoc scoping distinguishable from the laundering ADR-026 §5 bars |
| `[D2-tier2-served-graph-is-unbuildable-on-the-ml-extra]` | **MAJOR** | Phase 5 | **CLOSED 2026-08-29** — ruled by **ADR-035**, Option A approved with a testable invariant: `onnx` moves into the `ml` extra (the import set determined **empirically**, by masking `sys.meta_path`, after two plausible ways of faking absence gave confidently wrong answers), the guard becomes a permanent test whose expected import set is **derived from `pyproject.toml` at test time rather than hand-maintained**, `.[ml]` resolution is verified on both 3.12 and 3.14, and the measured graph-build duration is logged at startup beside the canary result so the boot cost is visible rather than an unexplained pause. Option B (cache the graph outside the repo) was **DECLINED** and is recorded as available if boot economics change. `onnxscript` stays in `dev` on measured evidence, logged as **M-32**. Originally filed 2026-08-28 while landing Phase 5 items 2-3, **before either tier-2 detector was written**, and found by *probing* rather than by reading: `onnx`/`onnxscript` were masked from `sys.meta_path` with every `ml` package left importable, and the ADR-031 served-graph build then failed `ModuleNotFoundError: No module named 'onnx'`. Three accepted positions cannot all hold. ADR-031 serves both checkpoints **on ONNX Runtime int8** (eager PyTorch misses the 04 §2 budget for every candidate measured); the graph is deliberately **never checked in** (*"a binary artifact whose provenance nobody could check"*), so it is built at **serve** time; and `pyproject.toml` puts the export toolchain in the **`dev`** extra on the stated reasoning that it *"BUILDS the ONNX graph, it does not serve it"* — true of the library, false in composition once serving builds. `optimum`, the one library that would collapse export and serve into an `ml`-only dependency, is deliberately excluded (its onnxruntime extra fails on torch 2.13 and downgrades transformers). The harm is that it lands **past ADR-033's stated boundary** — *"a present package whose model graph fails to build at first use is a runtime fault (state (b))"* — so an `.[ml]` host **boots clean**, `find_spec` succeeding for both declared names, and then converts a structurally unkeepable promise into a per-request fault: **BLOCK on every request** under `finance_advisor`'s `tier2: fail_closed`, **silent non-scan of every request** under the two `fail_open` pipelines. That is the exact D7 edge ADR-033 closed at boot, re-entering through a dependency its probe does not know to ask about. Invisible on the development host, where the toolchain is present — which is the reason to rule it before a deployment finds it. **Blocked work: the provisioning seam only** (how a serving host obtains the int8 session, and what `REQUIREMENTS` declares); both detectors' inference logic, windowing, aggregation, cutoffs, signal emission and blind measurements are identical under every option and proceeded, with graph provisioning behind **one shared helper** so a ruling changes one function rather than two detectors |
| `[D3-bound-case-window-count-undercovers-the-policy-bound]` | **MAJOR** | Phase 5 | **CLOSED 2026-08-29** — filed and **ruled the same day** (Option A approved: re-measure at the true bound, re-derive every label from the geometry, guard both). Closed by **ADR-032 Correction 1**, landed in the same commit as this closure — the row stayed OPEN until then because a closure citing a document that does not yet exist would be the same defect the Correction exists to remove. ADR-032's published table labelled its bound-case row **"52 windows / 4082 tokens"**, but 52 strided windows at step 76 span `102 + 51x76` = **3978** tokens — **22 short of the `per_request_max_tokens: 4000` bound the row claimed to measure**, contradicting the ADR's own full-coverage guarantee. The mechanism is the defect class this correction is named for: coverage labels were read off the **synthetic filler's token count** (which overshoots, because the generator length-checks only every 64 words) instead of **derived from the window geometry**. A derived label cannot drift from the geometry it describes; an observed one can, and did — two further labels in that table are underivable by any route (16 windows labelled 1546 against a geometry of 1242; 32 labelled 3100 against 2458). The latencies themselves are sound measurements of the windows actually fed, so this is a **label correction plus a re-measurement at 53 windows, not a re-roll**. **Also recorded here because the ledger itself failed:** this deviation was filed, adjudicated, and then **never entered as a row** — its only trace in the repo was a docstring in `tests/test_window_coverage.py`, while this table read "25 filed, 24 closed, one open", a count that was internally consistent and short by one. Caught by `tests/test_deviation_ledger.py::test_every_slug_mentioned_anywhere_has_a_ledger_row`, added for precisely this failure mode: every other test in that module reads the table, and so structurally cannot detect a row that was never written. **Blocked work: nothing.** What landed: the spike re-run at the true 53-window bound on a clean, quiet host (`445ca31dd087`, load 0.6 QUIET, n=40 with percentiles resolved at every rung, 0 contamination signals in both phases); every coverage label re-derived from `102 + (n-1)x76` rather than observed; the withdrawn table preserved blockquoted beside the corrected one; four guards added (geometry assertion in the spike runner, published-labels-are-derived test, detector-covers-every-token test, and the `eval.check_derivations` re-derivation check, itself gated by `tests/test_derivation_check.py` so CI runs it); and the 52 -> 53 propagation diffed against `03`, `04`, `06 §4`, `08`, ADR-034 Part B and ADR-030 Amendment 2 — the last three needed no change, which is recorded because "checked and unchanged" is a different claim from "not checked". The re-measurement also **surfaced two new MAJOR deviations** (the batch-4 justification and the two-window breach), both filed rather than rewritten |
| `[D1-batch-4-justification-falsified-at-the-corrected-bound]` | **MAJOR** | Phase 5 | **CLOSED 2026-08-29** — ruled the same day it was filed as **C-then-decide**: re-measure the curve at resolved percentiles, then apply a decision rule fixed *in the ruling* (lowest bound-case P99 among b2/b4/b8; ties under 5% break toward the smaller batch). Landed as **ADR-032 Correction 2**. The approved harness change decoupled `CURVE_REPS` from the ladder reps — two axes answering different questions, previously tied together, which is why the curve had been left at n=10 while the ladder ran n=40. Re-measured at **n=40** on a quiet host (`load1=0.96`), percentiles resolved at every point, 0 contamination signals: **batch 2 wins in both thread columns** and the decision rule needed no judgement — 6-thread b2 615.79 ms P99 with b8 **+7.2%** and b4 **+11.4%**; 1-thread b2 2577.48 ms with b8 +2.5% (inside the band, so the tie-break applies and also selects 2) and b4 +7.1%. So `batch 4` **is superseded by `batch 2`** — the filing was right that the stated reason did not hold, and the decision did not stand either. **No contract moves:** ADR-034’s ceiling is defined as measured-envelope × 2, so it re-derives automatically; `ceiling_ms(53)=5611.32` clears the winner by **9.11x** (6-thread) and **2.18x** (1-thread), verified rather than assumed. What the re-measurement showed about the *original* error is the part worth keeping: the "0.6%" was not fabricated — at n=40 the **P50** gap between b2 and b4 is +0.96%, so the flat basin is real **in medians and absent in tails**. A tail decision had been made on the only statistic n=10 could resolve, and b4 carries the worst max/P50 spread of all seven points (1.200). The filing’s own "6% per window" figure is withdrawn with it, being n=10 too. Filed 2026-08-29 by the Correction-1 re-measurement itself. ADR-032 chose `batch 4` on the claim that batch 2 and batch 4 "differ by 0.6%" and sit in "the same flat basin"; at the **corrected** 53-window bound they differ by **6% per window** and batch 4 is *slower than batch 8* despite half the calls. The decision may well stand — its stated reason does not, and every curve point is n=10 |
| `[D1-two-window-budget-breach-not-reproduced-on-the-clean-artifact]` | **MAJOR** | Phase 5 | **CLOSED 2026-08-29** — filed by the same Correction-1 re-measurement, one rung lower, and **ruled the same day** (Option A as recommended). ADR-032 scopes NFR-P-002 to single-window inputs on the stated ground that *"two windows measure 25.13 ms P99 against a 25 ms budget, so the target fails at the first multi-window input"*. On the clean artifact two windows measure **24.76 ms P99** (sequential; batched 22.53) — **under** budget in both columns, with the first breach at **4** windows. Unlike the batch-4 filing this flips a **verdict**, not a figure: the sentence's conclusion is false as written, and the margin (0.24 ms, 1.0%) sits far inside the disclosed ~26% run-to-run band, so whether the scope boundary moves is a specification call and not a relabel. **Ruling: the single-window scope STANDS and its justification is corrected in ADR-032.** The scope now rests on **principle** — a per-detector budget is a *per-inference* quantity, while multi-window cost is *length-parametric by construction* (ADR-034), so no flat per-call figure describes it at any window count — an argument that holds whichever side of 25 ms the two-window measurement lands on, which is why it is the stated ground and the measurement is not. The withdrawn wording is preserved blockquoted beside it. Re-scoping to ≤2 windows was **rejected**, reasoning ratified verbatim: it would widen a target on less evidence than the ADR already disclosed as insufficient, and in the self-flattering direction. Recorded because §7's anti-laundering rule does not cover this direction — not a target moved to hide a miss, but a **claimed miss that did not happen**, which had made a conservative choice look compelled by measurement. |
| `[D1-per-hold-derivation-maxes-detectors-that-share-one-worker]` | **MAJOR** | Phase 5 | **CLOSED** — ADR-030 **Amendment 3** (2026-08-30), implementing the ruling as filed (Recommendation A): the five ADR-034 Part A pool users **serialize** within a lane and so **sum**, non-pool detectors overlap, and a hold composes as `max(Σ pool, max(non-pool)) + 5 ms` engine step. Six rows re-derived to **30 / 30 / 40 / 70 / 100 / 130 ms** — the context-docs row 45 → 70, the `on_sampled` row 75 → 100. **No target moved**; the two rows that fit no plausible target publish **untargeted** (per-request-sum precedent), with the anti-laundering record stating that the `fast_consistency` cut is *not* what resolves them. `compose_hold` in `detectors/base.py` is the one implementation and `eval.check_derivations` re-derives all six rows from `BUDGETS_MS` — which on its first run caught **three pool-sum cells in the amendment's own table** that had omitted `entity_enricher`, the same defect class one document over. Unblocked `tier2_toxicity` and `rag_grounding` |
| `[D3-toxicity-wallclock-vs-25ms]` | **MAJOR** | Phase 5 | **CLOSED 2026-08-30** — filed and ruled the same day by **ADR-036**. Wiring `tier2_toxicity` made **2/30 control** fault-injection probes (no fault injected) record `DetectorTimeout` while the model measured 11.92 ms against a 25 ms budget: enforcement was reading wall-clock through the event loop, so pool queue wait, GIL contention and loop scheduling were charged to the detector. Ruled a **misattribution defect, not a detector defect** — NFR-P-002 now binds detector-attributable (in-thread) time, `wait_for` is retained as a 2x **hang backstop** raising a distinct `DetectorHang`, and failure records carry the measured `attributable_ms` so the two stay separable in audit. Supersedes ADR-034's "queue wait counts inside the ceiling" sentence by the front door. **SL-5's logged exposure materialized as predicted.** The ruling's own instrument (`perf_counter` in-thread) made it worse (18/30); shipped `thread_time` measures 0/30 — PROVISIONAL |
| `[D3-nfr-p002-gate-reads-the-clock-adr-036-rejected]` | MAJOR | Phase 5 | **CLOSED 2026-08-30** — ruled Recommendation **A + A2**, landed as **ADR-036 Amendment 1**. The gate now reads `cp_detector_attributable_ms`, the series `run_with_budget` enforces on, and the breaching sample is recorded **before** the raise so the gate is not structurally unfailable. A2: `cp_detector_latency_ms` gained `outcome=ok|fault`, so a fault and a breach can no longer be the same event counted twice; reports select rather than merge. Re-run on a quiet host (load1 0.84, clean tree, 300 samples) **changed the verdict in both directions**: `tier2_toxicity` CLEARS at 23.741 ms — that row was the artifact this deviation predicted — and `tier2_injection` breaches at 25.348 ms, which is genuine and now carries its own D3. Anti-laundering honoured: wall-clock stays published untargeted, both superseded rows preserved blockquoted. `fault_injection` went 36/39 → **39/39** with no test touched, which confirms the shared mechanism [[M-53]] described |
| `[D3-tier2-injection-attributable-p99-exceeds-25ms]` | MAJOR | Phase 5 | **CLOSED 2026-08-30 by adjudication — Option A approved, citing [[SL-8]].** The measured miss is published as-is: `tier2_injection` attributable P99 **25.348 ms** against NFR-P-002's flat **25 ms**, n=300, 0 faults, single-window, quiet host. **No threshold moved, no sample discarded, no harness adjusted** (§7). The target stands unmoved on ADR-026 §5's precedent, and the gap survives the closure as a Standing Limitation rather than disappearing with the row — which is what [[SL-8]] exists for. Option C (reduce per-call work) is retained as roadmap. The prose constraint the report attached is now permanent via SL-8: no artifact may claim NFR-P-002 **met** for this detector |
**Open: zero.** **32** deviations filed; **32** ruled and closed; **none** open. The last to close was `[D3-tier2-injection-attributable-p99-exceeds-25ms]`, filed and **ruled 2026-08-30** (Recommendation A: publish the measured breach, move no target) — and it is the clearest case in this table of why a zero here is not a statement that nothing is missing. **The gap outlived the row:** `tier2_injection` still misses NFR-P-002 at P99, the target is still unmoved, and the only thing closing the deviation settled was *what to do about it*. That miss now lives in [[SL-8]], which is the register that exists precisely so a closure cannot retire a gap. It replaces its own predecessor in this slot, and the succession is the point: `[D3-nfr-p002-gate-reads-the-clock-adr-036-rejected]` closed by moving the gate onto the instrument ADR-036 binds, and the first measurement on that instrument **cleared one of the two contested detectors and confirmed the other**. A correction that only ever exonerates is the shape this repo distrusts; this one did both, which is the evidence it was an instrument fix and not a laundering. It is the second filing here whose subject is **the clock a budget is enforced on** rather than the budget or the number, and it was found the way the first one's ruling made findable: ADR-036 changed what NFR-P-002 binds, and the **benchmark gate was never moved onto that quantity**. So `tier2_injection` publishes P99 25.569 ms against a 25 ms budget with **zero faults recorded** — an arithmetic impossibility if the gated series were the enforced one, and the proof that it is not. The last to close was `[D3-toxicity-wallclock-vs-25ms]`, filed and **ruled 2026-08-30** under **ADR-036** — the first filing in this table whose ruling **changed what a budget means** rather than what a number is: the measured breach was real, and the thing at fault was the clock enforcing it, which had been charging one detector for the lane contention of others. It is also the first whose approved ruling named an instrument that did not work (`perf_counter` in-thread made the spurious-fault rate 2/30 -> 18/30), so the implementation departs from the parenthetical and ships `thread_time` (0/30) under the ruling's stated intent, marked PROVISIONAL for batch review. The one before it was `[D1-per-hold-derivation-maxes-detectors-that-share-one-worker]`, filed 2026-08-29 and **ruled** 2026-08-30 (Recommendation A: re-derive the arithmetic, move no measured number) — **closed the same day under ADR-030 Amendment 3**, which makes the composition rule executable: `compose_hold` is the one implementation and `eval.check_derivations` re-derives all six published holds from `BUDGETS_MS`. As always in this table, the headline count means every *filed* question is ruled or awaiting a ruling — and it now reads **zero**, so the caveat that was hypothetical for most of this project's life is load-bearing today. **Zero open deviations does not mean nothing is missing.** It means nothing is *undecided*. What is missing is stated in the two registers below and is substantial: **9 Standing Limitations** (including an unmet PII-recall target, an uncalibratable τ, a breached detector budget, and two features cut from the demo path) and **64 MINOR resolutions**. A reader who takes `Open: zero` as a health score has read the one number in this file that was never about health. Both 2026-08-29 filings were surfaced by the re-measurement that closing `[D3-bound-case-window-count-undercovers-the-policy-bound]` required — itself filed and ruled 2026-08-29 and **closed the same day** under **ADR-032 Correction 1**, which landed it; the second of the two, `[D1-two-window-budget-breach-not-reproduced-on-the-clean-artifact]`, closed under that same Correction. That D3 entry is also the only entry in this table that had to be **discovered rather than recorded**: it was filed and adjudicated while this table said "25 filed, 24 closed, one open" — a count that balanced on its own terms and was short by one, because every check on it read the table and none read the repo. The completeness check that found it scans the other direction, and found exactly one such gap. `[D2-tier2-served-graph-is-unbuildable-on-the-ml-extra]`, filed 2026-08-28 while landing Phase 5 items 2-3, was the first in this repo found by **probing a host configuration** rather than by reading a doc or measuring our code; it **closed 2026-08-29 under ADR-035**. The two that preceded it, both filed by reading the Tier-2 contracts against the runner before writing the detector Phase 5 item 2 asks for, closed the same day under **ADR-034** and **ADR-030 Amendment 2**. The two that shared a subject — how much input `tier2_injection` may be asked to scan — **closed together** on 2026-08-28 under **ADR-032**, which is the shape that subject always had: one ruling reserved a branch for a measurement, the measurement fired it, and the second ruling accepted the cost rather than reducing coverage to hide it. The two Phase-5 filings that followed closed the same day they were ruled. The coverage-vocabulary question — what the audit record may truthfully say when a detector's dependency is absent — closed under **ADR-033**, which answered it with a third lifecycle state rather than a new `not_run` reason, and made the fail-closed case a **boot refusal**: you cannot promise fail_closed protection with the protector absent. The last-byte row closed under **ADR-030 Amendment 1** by a route worth naming, because it is neither of the two a reader expects: not by emitting the key and not by dropping the figure, but by establishing that the **gateway has no vantage from which the documented quantity is measurable** and re-siting it onto the benchmark client that does. A deviation can close by finding that one side of it was not constructible, and the honest record of that is a specification correction rather than a landed feature. The nineteenth (`[D3-tier2-injection-budget-cannot-hold-on-unbounded-input]`, filed from the ADR-031 latency spike) is the first since Step 4 to leave this count above zero, and the first filed from a **measurement of a model this repo intends to ship** rather than of our own code; its ruling overruled prefix truncation in favour of full-coverage strided windows. The twentieth (`[D3-full-coverage-windows-cost-600ms-at-the-policy-bound]`) was then filed **by that ruling's own item 5**, which required a stop-and-report if full coverage measured in the >500 ms class. It did, at both thread settings. Worth stating plainly because it is unusual: the second deviation is not a re-litigation of the first, it is the branch the first ruling explicitly reserved for this measurement. The twenty-first (`[D1-not-run-vocabulary-cannot-say-dependency-absent]`) is a different subject and a different kind: it is about the **audit record**, not a budget, and it was found by reading the coverage contract before writing the detector the phase's next item asks for — the cheapest place to find it, since the alternative was a shipped record that says `not_implemented` about code that exists. The **twenty-second** (`[D1-added-time-to-last-byte-has-no-server-side-vantage]`) was found the same way, one item later: by reading 06 §4's definition against the write path before implementing it, rather than by shipping a row whose name claims a vantage the writer does not have. The eighteenth (`[D1-tier2-budgets-cannot-coexist-with-nfr-p-001]`, closed by **ADR-030**) is the only one filed from a *projection* rather than from a measurement or a doc reading: it reported that two documents cannot both hold in a **future** state, which is why it was a D1 and not the D3 its subject matter might suggest — and why it could be ruled as a specification decision rather than as a target moved after a miss. Its own derivation then logged **M-18/M-19/M-20**, so closing it left three gaps *stated* rather than a clean slate. The Phase-5 filing
(`[D2-groq-tier-ids-shut-down-no-production-qwen-exists]`) is the seventeenth, closed by **ADR-029**:
an external event, not a defect in our specs — Groq retired both bound model ids — and the one
filing so far whose *recommendation was overruled on economic-rationality grounds* rather than on a
doc reading. The two Phase-4 BLOCKERs closed
together: `[D5-adr-027-stamp-has-no-column-in-the-05-3-ddl]` by **ADR-027 Amendment 1** and
`[D1-usage-canary-has-no-independent-count-on-the-measured-class]` by **ADR-028**. Both were
defects in *settled contracts* rather than in code — the stamp one a gap in ADR-027's own audit
representation, found while wiring the write path that ADR specified; the canary one a
requirement whose independent reference did not exist, found by probing for it. Per the note
below, a low `Open:` count means **little undecided**, not little missing: **five** Standing
Limitations remain (SL-4 closed 2026-08-28; SL-6 and SL-7 both filed 2026-08-30 — seven filed), and closing a deviation never closes the
gap it documented.

The **eight** filed from Step 4 up to that closure account as: **two** measured-accuracy findings
(D3, D8), **four** found while implementing the ADRs (`detector_params`, the `per` citation
marker, the NANP constraint, the `eyJ` derivation), **one** report-prose gate found after the
re-measurement, and **D5**. The **two** Phase-4 filings are the **ninth and tenth** from Step 4
onward and are **both now closed** — 10 closed + 0 open = 10, and 6 pre-Step-4 closures bring the
total to 16. The Phase-5 Groq rebinding is the **eleventh** from Step 4 onward, and the tier2
budget projection the **twelfth**. The ADR-031 spike filing is the **thirteenth** and the
measurement its ruling ordered is the **fourteenth**, and the coverage-vocabulary gap found
while landing `tier2_toxicity` is the **fifteenth**, and the last-byte vantage gap found while
closing out M-20 the **sixteenth**. All four have since closed — the thirteenth and fourteenth
together under **ADR-032**, the fifteenth under **ADR-033**, and the sixteenth under
**ADR-030 Amendment 1**. The **seventeenth** and **eighteenth** were the last two to sit open, and
they share a provenance worth naming: both were found by reading a settled contract against
the mechanism that has to honour it, one item before the code existed — the budget one because
`04 §2` says *per window* while the runner enforces *per call*, the hold one because ADR-032
rescoped NFR-P-002 and stopped one requirement short of the target that shares its dominant
term. Neither is a measurement of our code missing a target; both are two documents that
cannot both be satisfied by any implementation, which is what makes them D1 rather than D3. Both closed on the day they
were ruled, and the **nineteenth** — `[D2-tier2-served-graph-is-unbuildable-on-the-ml-extra]` — closed 2026-08-29 under **ADR-035**, and the **twentieth** (`[D3-bound-case-window-count-undercovers-the-policy-bound]`) closed the same day under **ADR-032 Correction 1**, and the **twenty-first** (`[D1-batch-4-justification-falsified-at-the-corrected-bound]`) closed 2026-08-29 under **ADR-032 Correction 2**, while the **twenty-second** (`[D1-two-window-budget-breach-not-reproduced-on-the-clean-artifact]`) closed 2026-08-29 under that same Correction — both surfaced by the twentieth's own re-measurement, which falsified written text at two separate rungs of the same table. That is the third and fourth instance in this workstream of a figure contradicted by the measurement it claims to come from, and the reason Correction 1 carries a mechanical re-derivation check rather than a promise to be careful. D2 stays worth reading for *how it was found*. It
breaks that pattern in the way worth recording: it was found neither by reading a doc nor by measuring our code, but by
**probing a host configuration this machine is not** — masking the `dev` extra's two packages and re-running the
ADR-031 graph build. Nothing in the docs is ambiguous and nothing measured missed a target; three individually correct
positions compose into an unkeepable promise, and only a probe of the composition surfaces it. That subtotal is **scoped to
Step-4-onward filings** — **26 closed + 0 open = 26** — and the 6 pre-Step-4 filings, all
closed, bring the whole table to **32 closed + 0 open = 32**. Both are stated because the
scoped figure alone, sitting a sentence after an unscoped "22 filed", reads as arithmetic
that cannot balance — it was reported that way once. The scope was the missing word, not the
sum. `tests/test_deviation_ledger.py` now parses this table and fails if either identity
does not balance, if the widest stated one disagrees with the rows, or if the `Open:`
headline drifts from the OPEN count — so a non-balancing count cannot ship again.
**Three of those eight were found by writing the ADR-026 spec-derived tests**, which is the
outcome that discipline exists to produce: tests authored from the specifications rather than
from the fixtures caught two defects in the ruled specs themselves and one in the implementer's
reading of them, *before* any number was computed. D5 was found the same way — by implementing
04 §5 literally and discovering the object it describes cannot exist.

⚠ **Open deviations and open questions are separate counts.** Five *questions* remain OPEN
above — **Q-01, Q-05, Q-06, Q-07, Q-08** (Q-10 **resolved 2026-08-28**) — while **two
deviations** are open, and the two
registers are deliberately kept apart: a deviation is a contradiction awaiting a ruling, a
question is a decision not yet needed. Collapsing them into one "open" number would hide which
kind of answer is owed. (The *gaps* left behind by closures are the
separate register below.)

**A closed deviation can still leave a gap.** "Ruled" means nothing is undecided, not that
nothing is missing: two of the closures above leave real gaps behind, and a decided gap is still a
gap. Every such item is carried permanently in the **Standing Limitations** register immediately
below, so the two numbers can never drift apart: a reader who reaches the end of the deviation
ledger — whatever it happens to count — sees the standing limitations in the same breath.

Also tracked as questions rather than deviations: **Q-10** (the local model — **resolved
2026-08-28**, **SL-4** closed with it, though the binding is verified on the owner's host only) and
the Groq price-provenance caveat under
**Q-02**, which constrains what the cost simulation may publish rather than blocking it (**SL-3** —
**downgraded 2026-08-27 by ADR-029**: first-party prices now exist for the two bound ids, so the
absolute-dollar gate is lifted for them).
**Q-18's publication gate is lifted** — ADR-025 made the citation-marker list normative in
04 §2.4.2, so a `numeric_claims` figure may now be published if labelled v1 or v2 (06 §3.2).

### MINOR resolutions (logged, not escalated)

Per the lightened protocol (AGENTS.md §11.1): a gap with one obvious low-risk answer is resolved
in place and logged here, so the open-deviation count above stays an *honest* count rather than
merely a low one. Sectioned by phase, because the lightened protocol is itself phase-scoped — though the
sectioning **stops after Phase 4**: every row from M-14 on sits under that heading without
belonging to that phase. Left as-is rather than retro-assigned, because the phase a row was
resolved in is not recoverable from the row, and a guessed heading is worse than a missing one.
The consequence to know when reading: **"here" in the Phase-4 paragraph below means the Phase-4
rows (M-3 to M-13), not the whole table.**

**Phase 3**

| # | Gap | Resolution | Why it is not a deviation |
|---|---|---|---|
| M-1 | 04 §3 defines `fail_mode` per detector **class** (`tier1`/`tier2`/`performance`/`cost`), but no doc maps each 04 §2 detector *to* its class, so `resolve_failure` had nothing to look up | `DETECTOR_FAIL_CLASS` in `controlplane/policy/engine.py`, transcribed from the 04 §2 registry rows. `entity_enricher` is deliberately **absent** (04 §2.2 makes enrichment failure skip-and-log, never blocking) and `fail_class_for()` **raises** on an unmapped detector rather than defaulting | The mapping is mechanical from the registry — every detector's class is unambiguous from its own §2 row. Refusing to invent a mode for an unmapped name is what keeps a future detector from silently inheriting `fail_open`. Pinned by `test_fail_class_covers_every_registry_detector_except_the_enricher` |
| M-2 | 04 §6 renders redactions as `[REDACTED:<category>]` (bare category, e.g. `email`) while 05 §4 records `category: "pii.ssn"` (full label) in `actions_json` | `AppliedEdit` carries **both**: `category` (bare, for the 04 §6 marker and the 07 beat-4 rendering) and `label` (full, for the 05 §4 audit field). Neither doc bends | Two consumers legitimately want different granularity; the only wrong answer was picking one and making the other doc inaccurate. Neither field ever holds the removed value (NFR-SEC-001), pinned by `test_applied_edit_records_category_and_span_but_never_the_value` |

**Phase 4** — M-3/M-4 arise from ADR-027 and are questions of *where* a ruled field lives,
not whether it exists. M-5/M-6 are gateway-surface gaps in 05 §1, found while implementing
ingress; M-7 is a 05 §6.1 gap found while implementing upstream dispatch, and M-8 a
05 §3-vs-§5 tension found while wiring per-detector timing. M-9 was, **of the Phase-4 rows**, the only one that is
not a doc gap at all — no doc is unclear, two code copies of a ruled list had drifted —
and it is logged here because the lightened protocol asks for every in-place resolution to
be written down, not only the ones that turned on a reading of a doc. M-10 is
downstream of the Phase-5 deferral recorded below: deferring two detectors made
*absence of coverage* a fact the audit record had no way to state. M-11 was the only Phase-4 row
that resolves a **reading** of two docs rather than a gap in one, and was called out
in the phase report for that reason; it was **ratified** on 2026-08-27 and 04 §2 now carries
the rule explicitly. M-13 was the only **Phase-4** row that arose from a **defect found in flight**
rather than from reading a doc: it is logged as a resolution because the fix is a contract
addition (a new 05 §3 column), and the incident that motivated it is named in the row so the
guarantee is not mistaken for a precaution against something hypothetical. Those
three "only" claims were **true when written and are now bounded to Phase 4**, because later rows
falsify them read table-wide: M-24, M-27, M-33 and M-36 each arose from a defect found in flight
rather than from reading a doc, and none of them — nor M-13 — is a doc gap. Found while adding
M-36, which is itself one of the falsifiers, so committing it unbounded would have left a document
whose prose its own new row contradicts.

| # | Gap | Resolution | Why it is not a deviation |
|---|---|---|---|
| M-3 | ADR-027 names `fail_mode_applied` as part of the `DetectorFailureRecord` shape, but the mode applied is unknowable at fault time — no policy has been consulted when the gateway synthesizes the record | The field is emitted by **`FailureOutcome.audit_entry()`**, at resolution, so the documented six-key shape (`failure_id, detector, error_class, stage, fail_mode_applied, ts`) exists at the **audit boundary** where 05 §3/§4 consumes it. `DetectorFailureRecord` carries the five facts known at fault time | Placement, not content: every ruled key reaches `detector_failures_json` exactly as ADR-027 specifies. Storing it on the record could only have held a placeholder until resolution overwrote it — a field whose value is a lie for part of its life. Pinned by `test_adr027_audit_entry_has_the_documented_shape_and_no_content` |
| M-4 | `failure_id`/`ts` are minted by the record, yet FR-POL-001 requires `evaluate()` to be a pure function of (signals, policy) with no clock and no randomness | Minted **at construction by the gateway**, exactly as `Signal.signal_id` already is (`default_factory`), and never read by the verdict computation | Determinism is a property of `evaluate()`, not of its inputs. Pinned by `test_adr027_record_mints_identity_without_making_the_engine_impure`, which asserts the guarantee that matters — two records for the same fault differ in id and yield identical verdicts — rather than merely that the fields exist |
| M-5 | 05 §1.1/§6 name `config/keys.yaml` normatively as the api_key→use_case map, but the file is **gitignored** (§6: "demo keys only") and so absent from a fresh clone. No doc says what its absence means | An absent file is an **empty map**, not a boot failure: the `X-ControlPlane-Use-Case` header is §1.1's primary path (marked `yes*`), and refusing to boot without a gitignored secrets file would block the documented dev path. A **malformed** file is still an error. `config/keys.yaml.example` added, mirroring the tracked `.env.example` convention | The doc specifies what the file contains, never that it must exist. The two wrong answers were boot-refusal (breaks a fresh clone) and treating a broken file as empty (every key-authed request would then look like a missing header). Pinned by `test_absent_keys_file_is_an_empty_map_not_a_failure` and `test_nfr_sec_002_a_malformed_key_map_never_echoes_the_key` |
| M-6 | 05 §1.1 says body `stream` "must be compatible with policy `streaming` flag, else `ERR-CFG-002`". "Compatible" admits a reading in which a client may *downgrade* a streaming pipeline to non-streaming — strictly safer buffering, so plausibly allowed | **Strict equality**: ERR-CFG-002 fires in *both* directions. A non-boolean flag gets its own message rather than being coerced (`bool("yes")` is True, which would emit "asked for stream=true" against "configured streaming=true" — an error claiming a value conflicts with itself) | The policy owns the interception mode: ADR-014 ties `consistency: on` to `streaming: false`, so a client-chosen mode would run a pipeline the policy does not describe while `stage_summary` recorded the configured one. Pinned by `test_err_cfg_002_fires_in_both_directions` |
| M-7 | 05 §6.1 types `base_url` as a bare `<url>` and states no rule for how a request path joins it. The two shipped providers disagree: `kiro-local` carries no version segment (`http://localhost:8000`), `groq` already ends in one (`https://api.groq.com/openai/v1`) | `upstream_url()` inserts `/v1` **iff** `base_url` does not already end in it. Resolved **empirically**, not by convention: both providers were probed keyless — no credential sent, so 401/403 means the path exists and is auth-gated while 404 means it is absent — with a `GET /v1/models` → 401 control row establishing that a 404 is a real absence rather than a network artefact. Probe table recorded in the `upstream_url` docstring with its date | Neither a naive join nor an unconditional `/v1` serves both providers, so *some* rule was required and the doc states none — a gap, not a contradiction. Deciding it by convention would have been a guess about two live endpoints when asking them was cheap. Pinned by `test_the_v1_prefix_is_inserted_only_when_missing`, parametrized over both shipped providers so a config change that moves the segment fails |
| M-8 | 05 §3 annotates `latency_json` as "per-**detector** ms", but 05 §5 records the same keys as a **fixed span vocabulary** — and that vocabulary has no entry for `numeric_claims`, one of 04 §2's seven detectors (ADR-025). `check_latency_keys` enforces the closed list at the write path, so a `numeric_claims` key is rejected. The detector appears in neither 05 nor 06 | 05 §5 is authoritative on the key vocabulary: it is the more specific statement and is explicitly labelled fixed. **Per-detector timing goes to `cp_detector_latency_ms{detector}`** — the detector-labelled channel 05 §5 already defines for exactly this, open by construction and the metric NFR-P-002 is measured by — while `latency_json` carries span keys only. `numeric_claims` therefore has no `latency_json` entry | Neither contract bends and NFR-P-002 stays measurable per detector. The two wrong answers were **inventing a span name** (`cp.out.numeric` is an undocumented addition to a vocabulary 05 §5 calls fixed — AGENTS.md §4 forbids it) and **folding it into `cp.out.grounding`** (a different detector on a different premise; the span would then misreport whose time it was). Spans are named for pipeline *stages* and already group detectors — `cp.out.tier1` covers both Tier-1 detectors — so a detector without its own span is the vocabulary working as designed, which `check_latency_keys`'s own docstring anticipates: "a per-detector span that is absent is normal" |
| M-9 | ADR-015 rules the span-less promotion, but no doc says **where the list of span-less labels lives**. `eval/policy_matrix` and `eval/validate_dataset` each reproduce the promotion rather than calling the engine, and each had grown its own copy — which had already diverged: the matrix's set held `cost.request_too_large`, the validator's did not, so the matrix applied the promotion where the validator skipped it | **One definition**: `SPAN_LESS_LABELS` in `controlplane/policy/schema.py`, imported by both consumers. The validator gains `cost.request_too_large`, which is genuinely span-less — it scores a whole request and has no extent to point at, so the validator was the side that was wrong. Guarded by `tests/test_span_less_single_source.py`, which walks the `controlplane/` and `eval/` ASTs for a third copy and asserts **identity** (`is`), not equality, on both imports | Nothing in any doc is contradicted or unclear: the promotion is ruled and both copies were trying to obey it. The defect was duplication, and the honest fix is structural — an `==` assertion would have passed for an equal-but-separate third copy, and a grep for the name would have missed this divergence entirely, since the two sets had **different names** (`_SPAN_LESS` and `SPAN_LESS_LABELS`). Freeze-adjacent and therefore re-verified rather than assumed: 280/280 unchanged, digest `6a3ecbbe75fd020b…` still matching, so a validator edit moved no number |
| M-10 | The Phase-5 amendment above creates a case no doc had a field for: `finance_advisor` sets `consistency: "on"`, but `fast_consistency` has no implementation this phase. A detector that runs and finds nothing emits no `Signal`, so a short `signals_json` cannot distinguish **checked-and-clean** from **never-checked** — and 05 §3/§4 recorded only signals, failures and the step-5 stamp, none of which answers *what was attempted* | **`detectors_json TEXT NOT NULL DEFAULT '{}'`** in the 05 §3 DDL, rendered as `detectors` in the §4 canonical view: `{ran: [name], not_run: [{detector, reason}]}`. `reason` is a fixed vocabulary with one member, `not_implemented`. Every string is validated against a closed set — detector names against `BUDGETS_MS` (the 04 §2 registry), reasons against `NOT_RUN_REASONS` — and a detector appearing in **both** lists is refused, since that contradiction is unresolvable by any reader. `{}` means *coverage not recorded* and stays distinct from `{"ran":[],"not_run":[]}` (*nothing ran, nothing expected*), the same `[]`-vs-NULL distinction as Amendment 1 | Nothing in any doc is contradicted: 05 had no coverage field because until this phase every detector in the registry was presumed present, so the question never arose. The field is **not** a `DetectorFailureRecord` and must not be read as one — a failure means *ran and broke* and carries `fail_mode_applied` because a policy resolved it, whereas a not-run entry means no attempt was made, so there is no fault, no fail mode, and nothing to resolve (ADR-027 stands unchanged). Deliberately outside `CONTENT_COLUMNS`: a value constrained to eleven known names cannot be a raw value, so the shape tripwire would add false positives and no safety. **Also closes a hole in the older guard** — the Amendment-1 differential named its two columns as literals, so when 05 §3 gained this column and `db.py` had not, the whole suite stayed green; the replacement compares the full column list in both directions and by order, and was mutation-probed on all three |
| M-11 | 04 §2's Stage column names `output_full` for **`fast_consistency` only**; every other output-lane row reads `output_sentence`. Read as an exhaustive whitelist, a non-streaming pipeline — which is the whole of UC-3 under ADR-014 — would run `fast_consistency` alone and **never scan a response for PII at all**, while 02 §4's non-streaming path says in terms: "buffer fully, run **all** checks incl. consistency, single verdict" | `pipeline.lane_members()` **composes** the full-response lane: the `output_sentence` rows **plus** `fast_consistency`. The Stage column is read as naming which *text* a detector consumes, not which delivery mode may consume it — `tier1_pii` over a whole response is the same regex pass over a longer string | Not a doc-vs-doc conflict needing the §3 precedence rule, because the strict reading is not a competing reading but an incoherent one: it contradicts 02 §4 in terms and would silently remove PII interception from the highest-stakes pipeline, which no requirement permits and no ADR contemplates. **Two pieces of already-ruled code settle it**: `review.mask_pii` runs `tier1_pii` at `OUTPUT_FULL` (05 §3's masking rule depends on it), and `Signal._check_span_stage_coherence` refuses a span only at `conversation` — so the schema, the one place a stage ban would be enforceable, does not ban this. Flagged in the phase report rather than buried: it is the one resolution this phase that turns on a reading of two docs rather than filling a gap, so it is the one most worth a human overruling if the strict reading was intended. **RATIFIED 2026-08-27**: the composed reading is correct and the strict reading is wrong — it would leave UC-3 unscanned for PII, inverting the risk gradient. The Stage column is per-detector native granularity, not a lane whitelist. 04 §2 now states the rule in prose rather than leaving it to be inferred |
| M-12 | 05 §1.1 fixes two renderings that a **streaming** response cannot produce: ESCALATE as **HTTP 202** with a `review_id`, and an edited response carrying the header `X-ControlPlane-Actions: edit`. Both are committed to the wire before the first sentence is ever checked — a status line and headers precede the body — so on the streaming path neither is reachable, while 04 §4.4 separately specifies terminate-and-notify for a mid-stream escalation | Read as **mode-specific rather than contradictory**: 05 §1.1's 202-and-header renderings govern the non-streaming path, where the verdict is reached before any byte is sent, and 04 §4.4 governs the streaming path. The streaming path carries the same two facts in its **final SSE frame's `controlplane` block** (`{verdict, review_id}`), so a client receives the `review_id` either way and nothing 05 §1.1 promises is actually withheld. **Narrowed 2026-08-28 (owner live-test finding).** The header half of this holds only for *output* edits, which is all the original reasoning covered: an **input-stage** redaction (ADR-020) is decided *before* dispatch, so it is known before the streaming response's status line exists, and the header is emitted there. Withholding it would have made the header unreachable in practice rather than mode-specific — `support_bot` is the only shipped policy mapping `pii.*` to `edit`, and it is `streaming: true`, so every reachable input EDIT took the one path that never set it. The 202 half is unchanged: an ESCALATE verdict is not available pre-dispatch on this path | Not a doc-vs-doc conflict: 04 §4.4 is the *more specific* statement about streaming and 05 §1.1 never claims its renderings are mode-independent — it describes one response shape at a time. The alternative readings are both worse and both testable as such: **buffering a streaming response** to keep the 202 available would delete FR-GW-002's release-as-you-go property and silently turn UC-1 into UC-3, and **omitting the review_id** from the stream would leave a user notified of a quarantine they cannot reference. `X-ControlPlane-Request-Id` is unaffected and present on both paths, since it is known at ingress |
| M-13 | **A request that released content could be delivered with no audit record at all.** The streaming handler yields checked sentences and writes its record *after* the last frame, but caught only `GatewayError` — so any other exception in between propagated past the write. Not hypothetical: `note_pii_intercepts` read `AppliedEdit.labels` where the field is `label`, and the resulting `AttributeError` fired mid-stream on a request whose sentences had already reached the client. ADR-002 forbids recalling released text, so the response could not be withdrawn and nothing recorded that it happened — the exact combination FR-AUD-001 exists to exclude. Client disconnect is the same hole reached by another route | Three parts. (a) **Crash-safe write path**: the streaming generator's release-and-audit region runs under `try/finally`, which covers all three ways a generator ends — a raise, a return, and the `GeneratorExit`/`CancelledError` of a disconnect. (b) **Partial-record marker**: `record_status TEXT NOT NULL DEFAULT 'complete' CHECK(record_status IN ('complete','partial'))` in the 05 §3 DDL, rendered in the §4 view. A **column** and not a JSON leaf, because every aggregate over this table must be able to exclude partials in its WHERE clause — a marker inside `actions_json` would let a crashed request's timings into a published number (AGENTS.md §7). (c) **Tests**: six, driving the ASGI app directly rather than through `TestClient`, which surfaces a response only once its body is consumed and so cannot establish *when* content left the gateway relative to the crash | Nothing in any doc is contradicted: 05 §3 says one row per request and never contemplated a handler dying part-way, so the gap was unstated rather than mis-stated. A partial row carries **real** measurements and is excluded by its status rather than by nulled fields — blanking them would make a crashed request look like a clean one that measured nothing. The rescue is **synchronous throughout**, because a `finally` reached by cancellation cannot reliably `await`: so the partial record is written and the review row is not, which is the right way round — a review item is recoverable from an audit record, an audit record is recoverable from nothing. Two boundaries stated rather than left to be found: a crash in `handle_completion` **before** the generator exists (ingress, input lane) leaves no record, which is within the guarantee since nothing was released; and a crash between minting a `review_id` and the review INSERT leaves an audit row naming a review item that does not exist, which is the honest record of what happened |
| M-14 | ADR-028 rules the FR-GW-006 canary's consequence by **upstream class** — `measured` fails boot, `dev` warns and continues — but both branches presuppose that the check *ran*. `run_canary` deliberately propagates `UpstreamError` so that "the provider is down" is never reported as "the provider miscounts", which leaves the startup hook holding a third outcome no doc names: the invariant was neither satisfied nor violated, because it could not be evaluated. A hook catching nothing would refuse boot through any provider outage, citing an invariant it never reached; a hook catching and ignoring would boot as though the check had passed | **Three states on `Gateway`, not two.** `canary` holds a `CanaryResult` when the check ran, `canary_error` names why it could not, and both `None` means it never ran (the knob is off, or nothing started the app). An unreachable provider warns under a **distinct** category — `CanaryUnavailableWarning`, separate from `UsageSanityWarning`, which means ran-and-failed on dev-class — and boots. `UsageSanityError` still propagates and refuses boot. Anything other than those two exceptions is left to propagate: swallowing it would hide a broken canary behind a clean boot log, which is the same failure in a quieter form. The hook lives in `lifespan` (FastAPI 0.115.6 deprecates `on_event`), so it fires under `with TestClient(app)` and not under a bare call — which is why the 872 pre-existing tests, whose stub reports a count that would *fail* the canary, were unaffected. **No `cp_*` metric was added**: none of the 13 in 05 §5 covers the canary, and inventing one is a contract change this wiring does not earn | Fills a gap rather than contradicting one. ADR-028 states the consequence of a *verdict* and is silent on the absence of one, and that silence is precisely what a boot hook must resolve. The shape is `canary.py`'s own rule — "a canary that always passes because it cannot run is worse than an absent one" — applied at the call site, and it is the same distinction M-10 and ADR-027 Amendment 1 already ruled: "verified" and "never checked" must not collapse into one value. Pinned by `test_an_unreachable_provider_is_recorded_as_unchecked_not_passed`, `test_a_measured_class_failure_refuses_boot` and `test_a_bare_testclient_does_not_run_the_canary` |
| M-15 | ADR-029's rebinding leaves the FR-GW-006 canary passing on the new measured-class pair with only **~7 tokens of margin**, and no doc states whether that is acceptable. At the shipped prompt (estimate 64) both gpt-oss sizes report `prompt_tokens: 121` — **1.89x** against `max_ratio: 2.0`, band [32, 128] — and the delta (57) already clears `min_delta_floor: 50`, so the ANDed condition rests entirely on the band leg | **Logged, no knob touched.** Measured across three prompt lengths (30 / 253 / 761 chars) the cause decomposes cleanly and is **not** the ADR-018 pathology: gpt-oss tokenizes this prose at ~5.1 chars/token where the estimator assumes 4.0, plus ~**72 tokens** of fixed chat-template overhead (qwen: ~11); residual under 1 token at every length. That is real scaffolding, correctly reported — an additive offset like ADR-018's, but two orders of magnitude smaller and *legitimate*. Recorded in ADR-029's trade-offs with the measurements | Nothing is failing, so there is nothing to contradict — and **widening `max_ratio` during a rebinding to buy margin is precisely the AGENTS.md §5.4 move**, since it would weaken the invariant to accommodate the provider it is meant to audit. ADR-028's rationale assumed "tokenizer variance well under 2x", which a 72-token fixed preamble against a 64-token estimate is not, so the honest options are a longer canary prompt (raising the estimate and shrinking the ratio) or an explicit template-overhead allowance — **both are ADR-028 amendments and neither is mine to make**. Logged here so the canary step finds it stated rather than rediscovers it as a boot failure |
| M-16 | 06 §5 and 07 beat 7 both specify the fault-injection demonstration on **`tier2`** ("assert UC-1 tier2 fails open"), and neither `tier2` detector is implemented — so a tier2 fault cannot be injected at all: there is nothing to monkeypatch. `cost` is in the same state. Left alone, SC-3 would be a P1 success criterion with no harness behind it, and 07 beat 7 would rehearse a fault the gateway cannot produce | **The requirement is verified on `performance` instead, and the report says so in its own scope section.** `numeric_claims` is live and its 04 §2 class is `performance`, which the shipped policies configure with the *identical* two-sided asymmetry `tier2` has (`fail_open` on UC-1/UC-2, `fail_closed` on UC-3) — so the contrast beat 7 exists to show is reproduced exactly. FR-POL-006 is stated per detector **class**, not per detector, so the requirement's own unit is satisfied. `eval/fault_injection.py` derives its coverage table from `DETECTOR_FAIL_CLASS ∩ pipeline.LIVE` rather than listing it, prints the unexercisable classes with their configured modes, and is pinned by `test_tier2_is_not_yet_injectable` — the OVLP-01 tripwire pattern ratified 2026-08-27 for deferred coverage. That test fails the moment a tier2 detector lands, forcing 07 beat 7 and the scope note back into review | Not a contradiction of any doc: 06 §5 states the eventual target and this defers one *instance* of it while satisfying the requirement it serves. The alternative readings are both worse and worth naming. Asserting tier2 anyway would need a fake tier2 detector existing only to break — a harness testing its own mock, which is the mocked-measurement shape AGENTS.md §5.4 forbids. Skipping SC-3 until Phase 5 would leave a P1 criterion unmeasured while the mechanism under it is fully working and demonstrably policy-driven. The substitution is visible in three places (this row, the report's scope section, the tripwire test), so it cannot quietly become permanent — which is the whole condition on which deferring is honest rather than convenient |
| M-17 | AGENTS.md §10 documented the gateway as `uvicorn controlplane.gateway.app:app --reload`, but `app.py` exposes **only** the `create_app()` factory — no module-level `app` — so the documented command cannot start the gateway at all (`Error loading ASGI app. Attribute "app" not found`). No doc states which of the two is wrong | **The command was corrected, not the code.** §10 is now `uvicorn --factory controlplane.gateway.app:create_app --reload`, verified by booting it and probing `/admin/policies` (200) and `/metrics`, with and without `--reload`. The entry also now warns off **port 8000**: `active_provider: kiro-local` has `base_url: http://localhost:8000`, so serving there makes the gateway proxy to itself — a trap the old line's `--port 8000` invocation walked straight into | Not a doc-vs-code contradiction needing a ruling: the line carried the `[Phase 2+]` marker, which §10 itself defines as "not runnable yet: the module exists as a docstring stub only", so it was an unverified placeholder written before the gateway spine landed (126d1ec) rather than a specification the code failed to meet. The factory-only shape is the **deliberate** side: the `Gateway` docstring rules it in terms — built once at startup "so a hot reload (FR-CFG-002) mutates the store the running app already holds, rather than leaving a stale copy behind a module global" — and every test injects through `create_app(gateway)`. Adding a module-level `app` to satisfy the stale line would have contradicted FR-CFG-002's hot reload and imported a `Gateway()` (policy load, `init_db`, dispatcher) as an import side effect |
| M-18 | **`entity_enricher` was unbounded inside a per-sentence hold.** 04 §2.2 budgeted it at < 10 ms **per enriched span** and capped the number of spans nowhere, so the composed hold was `60 + 10k`, crossing ADR-030's 100 ms P99 at **k = 4** | **RULED 2026-08-27 — closed.** 04 §2.2 now caps enrichment at **10 ms aggregate per sentence**, not per span. On exceed: skip remaining spans, log, increment `cp_enrichment_skipped_total{use_case,reason}` — semantics unchanged otherwise (never blocks, not a policy `fail_mode` class). ADR-030's derivation updates from *conditional on enrichment being capped* to **condition satisfied by the 04 §2.2 cap**: `k` leaves the arithmetic, the enriched typical row is a flat 40 ms, and every row fits | Never was a deviation — enrichment is unimplemented, so nothing measured could breach. It stayed logged rather than self-resolved because **the fix would have been a cap invented to make my own new target fit** (§5.4). The ruling came from the owner and lives in 04 §2.2 where the budget lives, not inside the target that needed it |
| M-19 | **Policy evaluate + action apply were inside a targeted quantity but unbudgeted.** 06 §4 puts them in the hold ("detector wait + policy + action"); 04 §2 budgets detectors only | **RULED 2026-08-27 — closed.** `cp.policy.evaluate` + `cp.action.apply` carry a **combined 5 ms budget** line in ADR-030's derivation, in every row. Measured, now that both spans are actually emitted: **combined P50 0.019 / P95 0.039 / P99 0.095 ms (n = 300)** — a per-request sum across units, so an upper bound on any single hold. Breach handling mirrors detectors: it surfaces in the per-hold series and trips `--check`, no new mechanism | Contradicted nothing — 04 §2 is a *detector* registry and never claimed the policy step. Worth recording that the three engine spans were in the 05 §5 vocabulary but **written by no code** when ADR-030 was accepted, so its original "measured well under 1 ms" had no measurement behind it; instrumenting them is what makes this row's figure real |
| M-20 | **ADR-030's `latency_json` changes were documented but not emitted — the rename included.** The write path wrote `gateway_overhead_ms`, and `input_hold_ms`, `sentence_holds_ms`, `added_time_to_last_byte_ms` existed as intervals in `app.py` but were **accumulated into one figure**, never recorded separately | **PARTLY CLOSED 2026-08-27 — the targeted half landed.** `input_hold_ms` and `sentence_holds_ms` are emitted on both delivery paths, `--check` gates both against NFR-P-001 naming the breaching subject and percentile, and the gated population is **holds, not requests**. So NFR-P-001 has a real verdict and the loud-stale note retires. **Rename landed 2026-08-28**: the write path, `spans.py`'s enforced vocabulary and the 06 §4 formula helper all carry `total_attributable_overhead_ms` (the metric `cp_gateway_overhead_ms` deliberately unchanged per 05 §5 — renaming it would orphan history for an unchanged definition). The checkpoint-3 review tripwire **fired on it**, which is what kept the code from drifting from the persisted rows, and was re-pointed rather than deleted. **CLOSED 2026-08-28.** The remainder — `added_time_to_last_byte_ms` — closed by **ADR-030 Amendment 1** as a **specification correction, not an emission**: the gateway has no vantage from which 06 §4's client-observed quantity is measurable, so the key is re-sited to 06 §4 as a benchmark-client figure and withdrawn from `latency_json`. It stays published, measured by the process that holds the stopwatch, absorbing the row previously called `reference_delta_ms`. Worth stating because the shape is unusual: this gap closed by establishing that one side of it was **not constructible**, which is a different outcome from either landing the code or dropping the row — and either of those would have been wrong here | Docs preceding code is this repo's design (§2). The residue is logged because **05 §5's vocabulary is enforced at the write path** by `check_latency_keys` while the `latency_json` key names are **not** doc-parsed by `tests/test_telemetry.py` (it parses the span and metric tables), so this particular divergence has no test holding it — a reader must be told, not left to infer |
| M-21 | **No continuous integration.** Every gate (suite, freeze, fault injection, latency tripwire) was runnable only by hand, so "passes on the author's machine" and "passes" were indistinguishable — and the repo became multi-machine at Checkpoint 3 | **RESOLVED 2026-08-27** — `.github/workflows/ci.yml`: matrix **py3.12 + py3.14**, running `pytest -q` → `validate_dataset --freeze` → `fault_injection` → `bench_latency --check`. **CI never writes to `reports/`**: both harnesses are redirected with `--out` and a final step asserts the directory is byte-identical, because a report from an ephemeral runner on unknown hardware would wear 06 §8 provenance it cannot support. The assertion exists because a comment promising it would not survive someone dropping the flag | Adds no contract and changes no behaviour — it executes commands AGENTS.md §10 already documents. Both matrix legs were **verified locally before the file was written** (py3.12.12 and py3.14.6, full suite exit 0, 0 failures), so the matrix is a measured claim rather than an aspiration |
| M-22 | **No onboarding path to verification.** AGENTS.md §10 lists the commands but not the order, the prerequisites, or what an uncomfortable-looking output means — so a newcomer could read `NFR-EVAL-001: MISSED` as a broken checkout rather than a logged, deliberately untuned target | **RESOLVED 2026-08-27** — `docs/TESTING.md`: four tiers (unit → eval → latency → live gateway), each self-contained, with the reasoning attached and the contracts cited rather than restated. Names the three pipelines and their `X-ControlPlane-Use-Case` values, the current measured-class `gpt-oss` tier ids, the `--factory` and port-8000 constraints, the frozen-dataset rule, and the stub inventory | Operational documentation, no contract. It **surfaced adjacent rot rather than working around it**: §10 still marked `eval.run_all` and `eval.bench_latency` `[Phase 2+]` — "not runnable, docstring stub only" — which both contradict (each was run to completion). Corrected in the same commit, since a guide saying *run these* beside a manual saying *these do not exist* is a doc-vs-doc conflict this repo would otherwise have to file |
| M-23 | **The README's status table had drifted from the docs it summarises — in the direction that overstates nothing and understates the build.** Three claims, three different ways of being wrong: it said **23 ADRs ruled** against a `03` holding **31**; it carried the literal suite count **`433`** in three places (status prose, quickstart comment, repo layout), each of which had to be right for the file to be right; and three rows read **not yet implemented** for the gateway hot path, the policy engine, and the latency + fault-injection harnesses — the code the prototype *is*, with committed evidence in `reports/`. The README is judge-facing, so this is an AGENTS.md §7 integrity problem rather than cosmetic doc rot, and it survived because nothing re-reads prose | Split by whether the number is **derivable**, because the two halves fail differently. The ADR count **is** derivable, so `tests/test_readme_status.py` now parses `03`'s level-2 `## ADR-NNN` headings and fails on any disagreement **in either direction** — a new ADR not reflected in the README, or a count the README invented. Counting `##` and not `###` is load-bearing and separately asserted: `03` carries **14** sub-headings (amendments, ADR-026's correction, ADR-030's derivations), and an amendment changes a decision rather than adding one, so counting them would inflate the total by over a third. The suite count is **not** derivable from any doc — it is a property of the run — so it was **removed** and pointed at `.github/workflows/ci.yml` (M-21), with a guard keeping literal 3-digit counts out; asserting the *correct* count would need editing on every commit that adds a test, which is the drift it was meant to prevent. The two conflated rows were **split** rather than flipped, since each mixed shipped code with real stubs (`cost_budget`, `cost_simulation`, `pii_leak_scan`, dashboard, demo runner are still unbuilt and still say so) | Not a deviation: the README is a **summary**, not a contract — `03`, `04` and `05` were correct throughout, and no reading of them was violated. Verified by mutation rather than by assertion alone: with the drifted README restored, **6 of the 8** new tests fail, naming the stale `23`, all three `433` copies and the understated rows; the 2 that pass read only `03` and are correctly independent of the README. **Provenance: owner adjudication, 2026-08-28 (Part 3), not the automated suite** |
| M-24 | **Policy `messages.*` templates were delivered to callers unrendered.** A live `hr_copilot` BLOCK returned the literal string `under {use_case} policy` — the judge-facing text on the most demonstrable beat in 07. 962 tests missed it because every assertion compared the served text against `policy.messages.block_fallback`, i.e. against the *same unrendered value the bug served*: a tautology that passes forever, in the exact shape 06 §3.1 rule 3 forbids elsewhere | Render both fields **once at load time** in `policy/schema.py`, not at the nine read sites. `{use_case}` is the only placeholder, `{{` escapes a literal brace, and every other form — including attribute access like `{use_case.__class__}`, which `str.format` would otherwise resolve into the object graph — is a **load-time** error, so a malformed template cannot reach a caller at all. Placeholders are validated *before* formatting, which is what makes that guarantee hold rather than merely usually hold. Regression assertions are now **properties** (no residual `{`/`}` in any shipped policy's rendered output), so they cannot be satisfied by the bug. 04 §4.3 records the rule; `fallback_used` in 05 §3 now stores rendered text | Not a deviation: no doc said templates were served raw. 05 §1.1 promises the caller the policy's fallback *text*, and a template is not text until it is rendered — the code simply did not do what the contract already required. **Provenance: found by owner testing (2026-08-28, first full manual run), not by the automated suite** |
| M-25 | **The request-level verdict was stamped from the output units alone.** An input-stage EDIT (ADR-020 pre-dispatch redaction) with a clean response stamped `verdict=pass`, so a request whose *prompt* was redacted was indistinguishable in the audit record, in `cp_requests_total{verdict}`, and to the caller from one where nothing happened — the gateway's most demonstrable privacy behaviour, unreported. 04 §4.3 steps 1–5 describe the stamp for **one evaluated unit** and never said how units combine, so neither side was contradicted | Owner ruling: the stamp is the **most severe action across every evaluated unit** (input lane, every output unit, conversation stage) under the §4.2 total order — added to 04 §4.3 as `Request-level aggregation`. The *evidence* is the **union** over units rather than the winning unit's row: `from_verdict` reads `detector_failures_json` off the stamped verdict, so picking one unit would drop a §5 fault whenever two units tied on severity (this regressed 4 of 27 fault-injection assertions and is why the union is not merely tidier). `contributing_signal_ids`/`failure_record_ids` still filter that union against the stamped action, keeping a `fail_open` fault under a PASS representable as *recorded but not contributing*. M-12's header half is narrowed in the same commit | Not a deviation but a **gap the ruling closed**: 04 §4.3 was silent on aggregation, so no reading of it was violated. Verified by mutation rather than by assertion alone — with the fix reverted, the new tests fail with `assert 'pass' == 'edit'`, the owner's exact observation. **Provenance: found by owner testing (2026-08-28), not by the automated suite** |
| M-26 | **A pre-dispatch terminal recorded its cost as unknown rather than as zero.** 04 §4.5 blocks before any upstream call, and the record left `tokens_*` and `est_cost_usd` null on the stated reasoning that a zero "would claim a free upstream call happened". That reasoning covers the *price* of an unpriceable model but not the *quantity* sent, which in this case is known exactly | Owner ruling: a short-circuited request records `tokens_in`/`tokens_out` = **0/0**, and on a `measured`-class provider `est_cost_usd` = **0.0** — a counted zero, not an estimate. `dev` class stays null (ADR-018: its accounting is not a measurement, so a 0.0 from it would be a barred figure in the column reports read), and `model_used` stays null on both, since no model answered. Added to 05 §3 as two `no dispatch` rows with the reason the null-not-zero rule inverts there, and pointed at from 04 §4.5 | Not a deviation: 04 §4.5 already said "no cost", so 0.0 is what the doc claimed and null was the weaker reading. The consequence is a real one for the cost plane — **null is excluded from an average**, so leaving it null made a pipeline that blocked half its traffic pre-dispatch report the same mean cost as one that blocked none, erasing exactly the saving the cost plane exists to show. Scoped by a test on the case the ruling did *not* touch: a **dispatched** request with an unpriceable model still records null, so the counted-zero branch cannot widen unnoticed. **Provenance: found by owner testing (2026-08-28), not by the automated suite** |
| M-27 | **Ingress rejections carried an empty `request_id`.** `ingest` minted the id on its own last line — *after* both rejections it can raise — so an ERR-CFG-001/002 body reached the caller as `"request_id": ""` with no `X-ControlPlane-Request-Id` header. 05 §1.1 already promised "All responses carry" that header, so this was non-compliant with an existing contract rather than an unspecified case | Mint in the handler before use-case resolution and pass it into `ingest` (which already accepted `request_id=`), publishing it to `request.state` immediately so the `GatewayError` handler finds it. Recorded in 05 §1.2. Both codes are tested because they fail at different points — ERR-CFG-001 before any policy resolves, ERR-CFG-002 relative to one — so a mint anywhere *inside* `ingest` would have fixed at most one | Not a deviation: no doc said the field could be empty, and §1.1 said the opposite. The failure mode worth naming is the one the fix could have introduced — **two** ids, one minted in the handler and one in `ingest`, would leave the header naming a request the audit table never heard of, which is worse than an empty string because an operator would follow it to a confident dead end. Pinned by a test asserting header == audit record id on the success path, plus a uniqueness test (a constant satisfies every other assertion here and correlates nothing). **Provenance: found by owner testing (2026-08-28), not by the automated suite** |
| M-28 | **`cost.request_too_large` is unmapped in all three shipped policies**, and ADR-032 item 4 makes `budget.per_request_max_tokens` the per-use-case **latency** control for `tier2_injection`. A policy that lowers it to cap input latency therefore has no mapped signal for the rejection it implies — the gate would bound the windows without anything user-facing saying why | **Logged, not fixed.** `cost_budget` is a Phase-6 stub and the label→action mapping belongs with it; ADR-032's escape valve works today for *raising* a ceiling, which is the direction a 4000-token pipeline needs. Filed so lowering it is known to be half-wired rather than discovered by a caller | Named in ADR-032 consequence 3 rather than left implicit: the escape valve is the ADR's answer to a 0.6 s worst case, so the fact that one direction of it is incomplete has to be visible beside the answer |
| M-29 | **`expected_for`'s ADR-014 consistency narrowing is dead code.** `pipeline.py` tests `str(policy.consistency) == "off"`, but `Consistency` is a `(str, Enum)` mixin, so `str(member)` is `'Consistency.OFF'` and the branch is never taken. `hr_copilot` ships `consistency: off`, so its records list `fast_consistency` in `not_run` — while 05 §4 says a detector switched off by policy "is not listed", neither `ran` nor `not_run`. Value equality (`== "off"`) would have worked; `str()` silently does not | **Logged, not fixed** (AGENTS.md §11: flag, don't fix outside the task). The one-line fix is `is not Consistency.OFF`, and no test pins the current behaviour either way — `test_uc3_records_fast_consistency_as_not_run` covers the `consistency: on` case, which is correct. Awaiting a ruling because the fix changes audit-record *content* for a shipped policy, which is contract-visible even though the doc already states the intended answer | Found while writing ADR-033's `availability._uses`, which had **the identical comparison** — copied from this line as the established idiom. That one is fixed (it is new code on this task) and its test asserts the narrowing fires rather than skipping when it does not: the first draft filtered policies with the same dead comparison, found none, and **skipped**, which is how a bug validates itself. Not a deviation by the M-27 precedent — no doc permits the current output and 05 §4 forbids it |
| M-30 | **ADR-034's parametric envelope says "ADR-032's measured series x 2", and ADR-032 publishes TWO thread settings** — so the phrase does not name a unique number until a column is chosen, and SL-5 exists precisely because the two disagree | **The envelope is grounded on the 1-thread (pessimistic) column**, recorded in ADR-034 Part B with the arithmetic beside it. The columns differ by **3.9x** (12.56 vs 51.28 ms P99 per window), so a 2x safety factor over the 6-thread figures sits *below* the 1-thread cost: a 2-window input would trip a ~50 ms ceiling at its actual 102.56 ms | Resolvable ambiguity with one low-risk answer, not a contradiction — the ruling's own stated intent is a ceiling that fires on anomalies rather than on length, and the optimistic column would have it fire on **contention**, which for a concurrent gateway is the normal case. The conservative direction can only fail to catch a mildly-slow detector; the other causes false blocks under `fail_closed` and false skips under `fail_open` on live traffic. NFR-P-002 is not restated and SL-5's disclosure is unchanged |
| M-31 | **ADR-034 Part C first specified the runner deriving its window count from a cheap character upper bound**, to avoid tokenizing twice (believed ~27 ms at the policy bound; **measured 8.22 ms P99** once a script existed to measure it — ADR-032 Correction 1). Sound for WordPiece (`n_tokens <= n_chars`) — but never checked against real text before being written down | **Measured, found far too loose, and the clause was corrected in place before any code depended on it.** Chars/token spans **1.00** (punctuation, CJK) to **800** (unspaced letters, digits, emoji, combining marks) against a frozen-corpus median of **4.29**, so at the 4000-token bound a ~5.5 s envelope becomes a ~24 s ceiling on *typical* text. Ruled instead: `tier2_injection` tokenizes **once**, enforces both its per-window budget and its exact total envelope itself, and the runner keeps a coarse `per_request_max_tokens`-derived **liveness backstop**. Nothing tokenizes twice and the meaningful guard is exact | An implementation-level correction **inside** a contract ADR-034 itself settles, which §11.1 puts outside the deviation protocol. Logged rather than silently fixed because the original clause was wrong on a measurable question and the loose bound would have preserved the *appearance* of the Part B guarantee while removing its content — it still catches a hung detector, never one that is merely 4x slow. It was also unsound beyond WordPiece: under byte-level BPE one character can yield several tokens and the inequality fails outright, so a checkpoint swap would have broken the guard silently |
| M-32 | **`onnxscript` stays in the `dev` extra while `onnx` moves to `ml` (ADR-035).** The split looks arbitrary — both are export-side libraries named in the same pin — and a later reader with no record would most likely 'fix' it by moving both | **Measured, not assumed.** `torch.onnx.export(..., dynamo=False)` selects the legacy TorchScript exporter, which never imports `onnxscript`: masking it from `sys.meta_path` builds **both** checkpoints successfully, while masking `onnx` fails with `ModuleNotFoundError`. So `onnx` is a serve-path dependency and `onnxscript` is not. It is retained in `dev` deliberately as the escape hatch if that export call ever moves to the dynamo exporter, which does import it | An implementation detail **inside** the contract ADR-035 itself settles, so §11.1 puts it outside the deviation protocol. Logged because the reason is invisible at the pin and the pin looks like an inconsistency without it — and because the claim is empirical: if the exporter call changes, this row is the thing that says what to re-check. **This row was itself missing:** ADR-035 said "logged as **M-32**" while this register ended at M-31, the same failure the deviation table had one register over |
| M-33 | **A measurement artifact recorded nothing about the conditions it was measured under.** A batch-curve phase of `eval/spike_window_latency.py` was poisoned by ~20 s of competing multi-core work (a concurrent ONNX export from the ADR-035 probes), and the contamination was detectable only by *inference* afterwards — a `p50` that came in 25% **above** its own cold sample. That argument was reconstructable, but only by a reader who thought to look | **Both harnesses now stamp their conditions, and 06 §8 makes the stamp binding:** measurement runs execute on a quiet host, and an artifact whose recorded load contradicts that is **not citable**. `eval/host_load.py` is the single definition (`load_stamp` + `git_stamp`); `spike_window_latency` and `bench_latency` both record it, and it absorbed a **4-way duplicated** `_git` helper that had already drifted (two copies carried `cwd`, one carried `timeout=5`, and the one without `cwd` read whichever directory the process started in) — the shared version keeps the **union**, since a consolidation that drops a safety property another copy had is a regression wearing a cleanup's clothes. Quietness is **three-valued** on purpose: quiet, measured-and-too-high (a finding), and unrecorded (uncitable, but not an accusation) | Cheap, and it converts a forensic argument into a mechanical check. Two things implementation added to the ruling, both recorded because they change what the stamp can be trusted to say. **(1) A stamp certifies a moment, not a measurement:** load averages lag ~60 s, so a short transient inside a 3-minute phase poisons two rungs and leaves both bracketing stamps clean — which is exactly what happened to the next run. `spike_window_latency.contamination_signals` therefore reads the *measurement* (local spikes, ladder-vs-curve cross-checks, cold/p50 ratio) and is what actually caught it; the three real artifacts it was calibrated against are retained as fixtures. **(2) Only ONE stamp per artifact can certify it.** The spike harness stamps once per *thread setting*, so the second phase's "start" read back the first phase's own load — 6.66 on a host that was quiet throughout, which would have condemned a clean artifact. Hence `load_at_process_start` (per artifact, the verdict) is a different key from `load_at_phase_start` (per phase, diagnostic) |
| M-34 | **The re-derivation check only scanned `03-decisions.md`, but ADR-032's figures are *copied* into `04` §2.1 and `06` §4** — so a corrected ADR could sit beside stale downstream copies and the checker would report clean. The same defect class the check exists for, one indirection out | **Widened to all three docs** (39 figures checked → 54), with Correction 2's batch figures routed to the artifact they were actually measured in (`reports/spike_batch_curve.json`, separate because one artifact carries one provenance stamp — M-33). Grep-shaped rather than parsed, per the ruling's *"coverage over precision"*. The widening found **no stale copies**: every 04/06 figure re-derived, because Correction 1 had propagated them by hand. Recorded because "checked and clean" is a different statement from "not checked", and only one of them was true before | The ruling that ordered it is the authority, and it extends coverage of a contract (ADR-032 Correction 1 item 3) rather than changing one. Three things implementation added, all recorded because they change what a green run means. **(1) An anchor matching nothing is a finding, not a skip** — the one real failure mode of a regex over prose is that a reworded sentence stops being checked while the run stays green, so an unmatched pattern is reported. **(2) ABSENT is a separate verdict from NO SOURCE**, because they send a reader to different places: a broken pattern versus a figure the artifact cannot produce. Collapsing them would have a drifted doc read as a bad number. **(3) The CLI and the landing-gate test now share one `collect()`** — they had each built their own list, so the gate could pass while the committed CLI failed. A guard and its test drifting apart is precisely what this module exists to prevent. Both new behaviours are themselves tested, by drifting a real sentence and asserting the verdict |
| M-35 | **The strided-window geometry had no production home.** `102 + (n-1) × 76` lived only in `eval/spike_window_latency.py`, and ADR-034 Part C needs it in **two** production places: the detector (which slices the windows) and the runner (which derives its liveness backstop from the policy's token bound). Production importing a measurement harness inverts the dependency; writing the formula down twice is the defect class this workstream is named for | **PROVISIONAL — batch review at phase end.** Moved to `controlplane/detectors/windowing.py`; the harness now imports and re-exports it, so every existing importer (`tests/`, `eval.check_derivations`) transitively reads one definition. Parity verified against the pre-move harness over 500+ inputs before the old copy was dropped, and pinned by **identity** rather than equality so a re-introduced duplicate fails while it still agrees. Dependency-free (`math` only), enforced by reading the module's own import statements — it is read on every request. Split at the honest seam: `POLICY_BOUND_TOKENS`, `BOUND_WINDOWS` and `WINDOW_COUNTS` **stay in the harness**, because those are measurement parameters (which bound we chose to publish a worst case for, which rungs we measured), while production reads the real bound per use case from `budget.per_request_max_tokens` — 4000 or 8000, so a module constant would be a second source of truth for a value config owns | Placement of code inside a contract **ADR-034 itself settles**, which §11.1 puts outside the deviation protocol; 04 §2 already records both budget halves, so no doc moved (checked, and stated because "checked and unchanged" is a different claim from "not checked"). Logged for the part worth keeping: this module's **first docstring justified the move with a false claim** — that the harness "imports the whole `ml` stack", so a gateway reaching for the arithmetic would fail to import on an ml-less host. Probed afterwards: every `torch`/`onnx`/`onnxruntime`/`transformers` import in that chain is **deferred inside a function**, so `import eval.spike_window_latency` succeeds with the entire stack masked, and `eval` is a declared package in `pyproject.toml` so "it would not be installed" fails as a fallback too. That is the **seventh** instance in this workstream of a claim described by a derivation it does not come from, and the first one self-inflicted in code written minutes earlier. The claim was **removed rather than repaired**, since the surviving reasons do not need it: dependency direction (the harness measures the implementation, so the implementation cannot depend on it — true whatever the import mechanics), and a **measured** side effect (both harness modules `sys.path.insert(0, REPO)` at module scope, so a gateway importing either would silently prepend the source tree to the import path, twice). Recorded with it: the deferred-import structure is an **unguarded implementation detail, not a contract**, so a future edit hoisting one import to module scope would make the withdrawn claim true with nothing noticing |
| M-36 | **Live doc prose cited code by line number, and line numbers rot silently.** ADR-034 Part C named `pipeline.py:280` as the place the resolved ceiling is consumed; wiring it moved that line to 312, so the citation became a pointer to an unrelated docstring fragment. Found while checking my own change — and the survey then turned up that `pipeline.py:212`, ADR-030's anchor for the sequential-vs-`gather` measurement decision, was **already stale before this session**, pointing at `Coverage.note_ran`. Nothing had noticed, because a line number is not checkable by reading the sentence around it | **PROVISIONAL — batch review at phase end.** All **7** live citations converted to **symbol** anchors (`run_lane`, `ceiling_ms(name, units)`, `_time_calls`, `_time_tokenize`), each verified to resolve to a real object — after the first attempt named `_time_windows`, which does not exist, making the correction itself an eighth instance until the check caught it. `tests/test_doc_code_anchors.py` now enforces the rule mechanically, negative-controlled by re-introducing a line number and confirming the guard fires. **History is exempt, deliberately**: a filed deviation report, a ledger closure row and a blockquoted withdrawn passage each record what was true when written, so re-pointing them at today's code would falsify the record — the guard checks *zones*, and a second test asserts the exempt zones are still populated so the rule cannot hold vacuously. One third-party citation (`import_utils.py:205`) is allow-listed: it cannot be anchored by symbol and is pinned by an inline code quote, which is what carries the claim | Doc hygiene inside settled contracts — no figure, budget or contract moved, so there is nothing for a ruling to decide. Logged because the failure was **silent and pre-existing**: one instance was introduced by this session's own change and one predated it, which makes it a class rather than two typos. Also logged for what the fix deliberately does *not* do — ADR-034's `**Context.**` narrative describes what the deviation found **at filing**, so it keeps the past tense and loses only the pointer, rather than being re-pointed at code that post-dates the finding <!-- rot-evidence --> |
| M-37 | **`tier2_injection` needs a positive-class cutoff and no doc names one.** The 04 §2 registry row gives the detector its budget, plane and stage but no score threshold, and the score is **DETECTION**-kind — verified against `evaluate` in `controlplane/policy/engine.py`, which bands CONFIDENCE-kind scores only — so the engine never gates it. The cutoff is therefore the *only* gate between a model score and a `security.prompt_injection` signal that all three shipped policies map to `block`; without one the detector would emit on every request | **PROVISIONAL — batch review at phase end.** `DEFAULT_CUTOFF = 0.5` exposed as `CUTOFF_PARAM = "cutoff"`, overridable per use case through the policy's `detector_params` — following `tier2_toxicity`'s adjacent documented precedent in the same table rather than inventing a convention. An override that is non-numeric or outside `[0, 1]` raises `DetectorError` instead of clamping, so a typo in a policy file surfaces as a detector fault the 04 §5 machinery already resolves, not as a silently widened gate | §11.1 — a resolvable ambiguity with a precedent one row away, resolved MINOR-style and logged rather than spent on a ruling. No contract moved: `detector_params` is already the documented channel for per-use-case detector tuning, and the default sits where a reader of the neighbouring detector would expect it |
| M-38 | **"Per-window budget" has two readings once a detector is windowed.** ADR-034 puts an exact per-window envelope inside the detector and a coarse parametric liveness ceiling in the runner, but does not say whether the inner envelope is a *timer* (a deadline armed around each window) or a *structural* guarantee (bounded batch rows, counted windows, the figure reported). The two produce materially different code | **PROVISIONAL — batch review at phase end.** Structural. The scan runs as one executor task with `BATCH_ROWS` bounded, and `meta` carries `window_count`, `max_window_index`, `per_window_ms` and `budget_per_window_ms` so the envelope is *reported* per request. The inner-deadline reading was rejected on mechanism: an `asyncio` deadline cannot preempt a blocking ONNX inference, so a per-window timer would fire only *between* windows — measuring nothing the batch bound does not already bound, while adding overhead to a 25 ms budget. `per_window_ms` is labelled the **mean** over one request's windows, explicitly not a percentile, because an unlabelled statistic in `meta` is the same defect class as a figure described by a derivation it does not come from | An implementation choice inside a settled contract (§11.1) — the runner's parametric ceiling still bounds the whole scan, which is the enforcement ADR-034 actually specifies. No new metric was needed either: 05 §5's closed vocabulary has no per-window-breach entry, and `cp_detector_failures_total{detector,fail_mode}` already counts the resolution |
| M-39 | **Graph provisioning had no production home and no boot trigger, and the lazy fallback was catastrophic.** ADR-031 keeps no checked-in graph, so a serving host exports and quantizes at first use — but the only implementation lived in a measurement spike, and nothing called it at startup. Wiring the detector with the build inside `detect()` put a ~7.8 s export against a 25 ms per-window budget and the bound-case ceiling, **inline on the event loop**, where `wait_for` cannot fire until control returns. Caught by `eval.fault_injection`: its *control* probe, with no fault injected, reported `failures=['tier2_injection']` | **PROVISIONAL — batch review at phase end.** `controlplane/detectors/onnx_models.py` is the production home — `SERVED` (single-sourcing the model id and positive labels the detector imports), `load_classifier`, `warm_models`, and `positive_index_for`, which resolves the positive class **by name** and raises on both no-match and ambiguity rather than trusting the index-1 coincidence ADR-031's candidates happen to share today. `build_onnx_session` moved out of the spike and is re-exported there, object identity verified. Boot calls `warm_models` after the FR-GW-006 canary, per ADR-035 item 4. Both measurement harnesses call it **explicitly**, because each constructs `TestClient` un-context-managed on purpose (so the canary does not fire) and therefore never runs lifespan — in `bench_latency` the build would otherwise land inside request #1 and be *timed*, corrupting every percentile it publishes | ADR-035 item 4 already ruled build-at-boot and even where to log the duration; this is the wiring that ruling named, and the defect was introduced by my own change minutes earlier. Logged rather than ruled because nothing in the contract moved — but logged loudly, because the failure mode is a provisioning cost silently entering a published measurement, which §7 forbids |
| M-40 | **The fault harness selected a carrier that could not carry, and reported the class as covered.** `class_carriers()` intersected `DETECTOR_FAIL_CLASS` with `pipeline.LIVE`, while `_Faulty` raises only at the OUTPUT stages. `tier2_injection` is INPUT-only (04 §2), so it was selected as `tier2`'s carrier, printed as covering the class, and then never faulted — every tier2 assertion failed with `failures=[]`. The stage precondition was always there; it was satisfied *by accident* while every carrier happened to be output-lane, so nothing had ever exercised the gap | **PROVISIONAL — batch review at phase end.** `FAULT_STAGES` is now one constant read by both `_Faulty` and the new `faultable()`, so fault site and coverage derivation cannot drift; carriers intersect `faultable()`, not `LIVE`. `run_probe` gained a second refusal branch: wrapping a live-but-unfaultable detector yields a probe stamped `injected=<name>` with an empty `failures` tuple — a control run mislabelled as a faulted one, the exact misreport its dead-detector guard exists to prevent. The tripwire was **re-pointed** from *live* to *faultable* per its own written instructions, never deleted, and the report's scope note now states the narrower reason; the old reason ("nothing to monkeypatch") is recorded as superseded rather than edited away, since `tier2_injection` being live falsified it | The harness's claim got **narrower**, not wider: measured coverage went down and the report says so, which is the opposite of the failure §7 guards against. The substitution 06 §5 and 07 beat 7 already document still stands for a stated reason, and `tier2_toxicity` (OUTPUT_SENTENCE) will carry `tier2` properly when it lands — `faultable()` picks it up with no source edit, and the tripwire fires again to force beat 7 back into review |
| M-41 | **The lane treated `LIVE` membership as proof of loadability, bypassing the ADR-033 boot manifest.** `run_lane`'s only check was absence from `LIVE`, which was sufficient for exactly as long as state (c) could *only* be expressed by absence — true while every live detector was a dependency-free regex pass. A live detector with real imports makes state (c) reachable **with** membership: on an `.[dev]`-only host the boot manifest correctly reports `tier2_injection` unloadable, yet the lane would still call `detect()`, and the ImportError would be filed as a per-request transient `DetectorFailureRecord` — re-discovered on every request — instead of the host-level absence ADR-033 exists to separate it from. A production defect, surfaced by two tests that had used the detector's *absence* from `LIVE` as their unloadable stand-in | **PROVISIONAL — batch review at phase end.** `run_lane` now consults `Coverage.unloadable` alongside membership and routes to `note_missing`, which already branches to `unavailable` — the branch was correct, nothing reached it. Pinned by a **spy** test asserting `detect()` is never called (the audit record cannot distinguish "not called" from "called and normalized"), negative-controlled by reverting the fix and confirming the spy fires with `called it at ['INPUT']`. Two docstrings that stated the now-dead arrival path ("absent from `LIVE`", "`LIVE` has no entry either way") were corrected rather than left to read as current fact | ADR-033 already rules the outcome — this is code failing to implement a settled contract on a path that only just became reachable, which is a defect to fix, not a question to rule on. Logged because the trigger generalises: every loadability check written while state (c) meant "absent" is suspect the moment a dependency-bearing detector goes live, and this was the first one |
| M-42 | **The latency report described a live, measured detector as unimplemented.** Three prose sites in `eval/bench_latency.py` named `tier2_injection` in string literals as absent — the projection docstring, the NFR-verdict coverage caveat, and the projection section header. Two of the three are **rendered into `reports/latency_report.md`**, so the published artifact asserted "`tier2_toxicity` and `tier2_injection` are unimplemented, so nothing here has been run" on the same page whose per-detector table measured `tier2_injection` at n=300. Found while reconciling a tripwire figure, not by any test | **PROVISIONAL — batch review at phase end.** All three sentences now read `projected_not_yet_live()`, derived from `LANES ∩ BUDGETS_MS − LIVE`, which reports `cost_budget, loop_guard, rag_grounding, tier2_toxicity` on this host and drops a detector automatically as it goes live. `pending` is bound once in `render` so the caveat and the header cannot disagree about which detectors are hypothetical. The two lists the report prints answer different questions and both stay: "not exercised in this run" is measured-this-run scope (7 detectors, wider than the hot path), the projection's is hot-path-lane scope (4) | Same defect class as [[M-36]] and [[M-40]] — a claim described by a premise it no longer comes from — reaching **report prose** rather than a code anchor or a harness derivation. No figure moved and no target changed: the arithmetic was always derived from `LANES`/`BUDGETS_MS`, it was only the sentence *about* the arithmetic that was hardcoded. Logged rather than ruled because §7's requirement is that a published artifact's claims be true of the run that produced it, which is a defect to fix, not a contract to decide |
| M-43 | **The M-42 sweep fixed the sites that named *detectors* and missed the one that named *figures*.** One paragraph further down the same rendered section, `eval/bench_latency.py` asserted `"Worst cases become 30 / 40 / 45 / 75 ms and every row fits"` as a string literal — a **verdict** over the four ADR-030 rows that `[D1-per-hold-derivation-maxes-detectors-that-share-one-worker]` contests, rendered into the published `reports/latency_report.md`. M-42 was filed for exactly this class in exactly this file and its sweep grepped for detector names, so a sentence restating *numbers* passed straight through | **PROVISIONAL — batch review at phase end.** The verdict is **withdrawn and the figures disclosed as contested**, naming both affected rows (45 → 70, 75 → 100 zero-margin), the untabulated 130 ms case, and — explicitly — what is *not* affected. Deliberately **not** re-derived: re-deriving from ADR-030 would propagate a contested table, and re-deriving under the pool rule would pre-empt a ruling whose three options are not equivalent. The computed projection needed no change at all, which is the part worth keeping: `project_tier2` already publishes the `sum` and `max` readings **side by side** precisely so its conclusion "does not depend on which way the implementation goes", and the true pool-aware composition lies between them. The harness was built honestly; only the prose beside it had hardcoded a winner | Same class as [[M-42]], [[M-36]] and [[M-40]] — a claim described by a premise it no longer comes from — and logged separately rather than folded into M-42 because the **lesson is different**: M-42's was that prose naming a fact must read the fact, and this one is that a *completeness sweep* scoped to one surface form (names) leaves the other (figures) untouched, so "class fixed" overstated what the sweep covered. No figure moved and no target changed |
| M-44 | **The canonical FR-DET-005 signal shape may be unconstructable, because its host label's only producer is plausibly span-less.** 04 §2.2 visits *span-bearing* `hallucination.*` signals only; 04 §39 (FR-DET-005) states the fabricated-personal-detail case emits ONE signal with `labels:["hallucination.ungrounded_claim","privacy.person"]`; `privacy.person` has **exactly one** producer in the whole system (`ENRICHED_ONLY_LABELS`, the enricher). `hallucination.ungrounded_claim` has exactly one producer too — `rag_grounding`, which 04 §2 row 61 describes as a sentence-vs-context *entailment proxy* with `score_kind: confidence`. No doc states whether it emits a span, and the architecture explicitly accommodates a span-less one: 04 §390-392 and the §6 `soften` row both provide for an `output_sentence` `hallucination.*` signal **with no span** (ADR-015 whole-sentence scope), and ADR-030 calls `fast_consistency` "span-less by design" for being a scorer. If `rag_grounding` is span-less, the enricher never visits it and the documented shape cannot be built — **14 of the 16 frozen `person_present: true` fixtures** carry `ungrounded_claim` as their only host label (`overlap.jsonl` 15/15, `conversation.jsonl` CONV-06), and OVLP-01 is on the 07 beat-4 demo path | **PROVISIONAL — batch review at phase end.** Resolved by the **narrowest** reading: `entity_enricher` implements 04 §2.2 verbatim — span-bearing `hallucination.*` only — and the trigger is **not** widened. Chosen because it changes no contract and adds no capability, and because it is measurably free: those 14 fixtures are unsatisfiable **today** for an unrelated reason (`rag_grounding` is unimplemented), so the narrow reading regresses no number and closes no option. The live producer `numeric_claims` already exercises the real path (OVLP-04, `span=(25,35)` over `'94,000 EUR'`), so the stage ships measured rather than projected. The two open readings — `rag_grounding` emits a whole-sentence span, or §2.2's trigger widens to include span-less `output_sentence` signals — are **both `rag_grounding`'s contract**, and that detector is already blocked by `[D1-per-hold-derivation-maxes-detectors-that-share-one-worker]`; whichever is ruled, the enricher change is one predicate, since NER over "span ± its sentence window" for a whole-sentence span *is* NER over the sentence | Not filed as a deviation because nothing contradicts anything **yet**: the contested signal has no producer, so no code and no published number depends on the answer, and §11.1 makes a resolvable ambiguity a MINOR rather than a D4. Same class as [[M-18]] — a budget or trigger whose *reachability* was never checked against the labels it must produce — and worth its own row because the lesson is new: a frozen dataset can encode a label that **no implemented detector can emit**, and the freeze gate cannot see it (it validates label/action consistency, never producibility). Flagged, not fixed, per AGENTS.md §11: the ruling belongs with `rag_grounding`'s |
| M-45 | **A category definition drawn around one shape misfiled a working stage as absent.** The `Measured inventory` table in this file classifies the 11 `BUDGETS_MS` detectors as **Live** or **Declared but absent**, where "live" is defined as *exposes an instance whose `.name` matches a budget entry and which has an `async detect`*. `entity_enricher` is implemented, wired, warmed at boot and tested — and has no `async detect`, **by design**: 04 §2.2 makes enrichment its own stage between detection and the policy engine, so its entry point is `enrich(signals, text, ...)`. With only two rows available it therefore filed under *Declared but absent*: a false statement about working code. The same table also still read `Live (3)` while `tier2_injection` had landed | **PROVISIONAL — batch review at phase end.** A **third** row added — *Implemented, but not a `Detector` (1)* — with the reason stated inline, and the table recounted mechanically from the tree (`Live (4)`, absent 6). Deliberately **not** resolved by giving the enricher a `detect` to satisfy the phrasing: that would be a type lie in service of a table, and the same temptation was refused twice more in this task (a `LIVE` entry to reach `app._probe_scope()`, and a `DetectorUnderTest` to reach `eval.run_all`'s scored set) — in all three the honest edit was to name the stage explicitly and say why it is not a detector. `docs/TESTING.md`'s stub list also dropped it, verified against the absence of a `STUB(` marker rather than by eye | Not a deviation: the inventory is a **measured** artifact, not a contract, so nothing here contradicts a doc — and §11.1 makes a resolvable ambiguity a MINOR. Same family as [[M-42]] and [[M-43]] (a claim described by a premise it no longer comes from) but the lesson is a **new** one and worth its own row: those two were sweeps that missed a *site*, while this is a **taxonomy** that had no bucket for the truth — a completeness check over such a table cannot find the error, because every row is individually well-formed and the omission is the *category*. Prompted the same question of `eval.run_all`'s `SkippedDetector`, whose one-line docstring ("a 04 §2 row with no implementation") named one of the **three** reasons it actually carries |
| M-46 | **A new measurement instrument reported maxima as P99s, and the existing resolution guard could not see it.** `eval/spike_enrichment_latency.py` (new, for the 04 §2.2 cap that no lane harness can reach) computed percentiles with its own `int(round(q * (n-1)))` helper. At its default n=40 that is `round(38.61)` = 39, the top index, so **every `p99` it published was the `max`** — visible in the artifact as p99 and max columns identical in all five curve rows. `_percentiles_are_distinct`, the guard ADR-032 Correction 1 added for exactly this family, returns True at n=40: it asks whether p95 and p99 land on *different* order statistics, which is a different question from whether p99 is *the max*. The same run also printed an `UNBOUNDED` verdict against `budget + one k=1 call P99` — a pass line the harness invented, not an NFR — missing it by 0.48 ms | **PROVISIONAL — batch review at phase end.** Percentiles now come from the one production definition (`controlplane.telemetry.metrics.percentile`, imported, interpolated); a second guard `_p99_resolves_off_the_max` asks whether any sample exceeds the interpolated rank; reps default to **200**, against a guard minimum of **n=101** — searched over 3..2000 rather than inferred from the three sizes that happened to be tried, because 'the first size I tested that passed' and 'the smallest size that passes' are different claims and only the second is a property of the guard. The extra reps buy margin, not compliance, and cost seconds at ~5 ms a call. Both flags travel in every row of the artifact. The verdict was rebuilt against what 04 §2.2 actually promises — spans bounded in k, time sublinear at the largest k — from quantities measured in the same run, with the by-design overshoot reported rather than gated (the budget is checked *after* each window, so checking first would let a slow pipeline enrich nothing and make the stage unreachable rather than degraded). No published figure moved: truncation, which `spike_window_latency` and `spike_tier2_models` both use, never lands on the max at any n — checked across n=10..300 rather than argued | Not a deviation: the defect was in an uncommitted new instrument and no published number was ever derived from it. Same class as [[M-42]], [[M-43]] and [[M-45]] — a claim described by a premise it does not come from — with two lessons that are new. First, a **guard can be passed and still not apply**: n=40 satisfied the only resolution check this repo had while the figure it certified was a maximum, so "the guard is green" was never the same claim as "the percentile is real." Second, and worse, the **first correction of the superseded artifact reproduced the very class it was recording** — it attributed the identical columns to interpolation at rank 38.61 when the cause was `round()` landing on index 39, two different defects fused into one false causal sentence, committed inside the fix. Both were separated in a follow-up and the arithmetic is now tabulated in the artifact instead of narrated |
| M-47 | **The SL-6 cut removed the *stated reason* for `finance_advisor: streaming: false`, and the value has an independent one.** Both the policy comment and 04 §3's example justified it as *"consistency:on requires full buffering (ADR-014)"*. At `consistency: "off"` that guard no longer binds, so a reader could take the value as vestigial and flip it | **Value unchanged; justification re-sited** to 01 §3 — UC-3 is high-stakes decision support, so the full response is judged before delivery. Recorded in both the policy comment and the 04 §3 example, in the same commit as the cut | This is the repo's recurring defect class — *a claim described by a premise it does not come from* — caught **before** it landed rather than after: the value was correct and its stated cause had just been removed. Left as a MINOR record because nothing about behaviour changed; had the comment been trusted and the flag flipped, UC-3 would have begun streaming unjudged text |
| M-48 | **`expected_for`'s `consistency: off` narrowing never fired in any shipped configuration.** `pipeline.py` compared `str(policy.consistency) == "off"`, but `Consistency` is a `(str, Enum)` mixin whose `str(member)` is `'Consistency.OFF'`, so the test was never true. `hr_copilot` shipped `consistency: "off"` and still had `fast_consistency` counted as expected coverage | **Fixed** to `policy.consistency is Consistency.OFF`, matching `availability._uses`. Found by a test written for the SL-6 cut, not by the cut itself — it reproduces on the pre-cut config | Two things worth recording. First, `availability._uses` carries a comment warning about **exactly** this mixin trap, added when the same mistake was caught there; the sibling module made it anyway, so a comment in one file is not a guard on another — the fix therefore lands beside a test that fails on the broken comparison. Second, the bug was **latent, not harmless**: 05 §4 distinguishes *not listed* (policy declined) from *not_run* (expected, absent), and while it stood, a declined check reported as a coverage gap. No published number derives from `expected_for`, so nothing measured needs re-running |
| M-49 | **`base.py` cited a test file that did not exist.** `POOL_USERS`'s docstring, committed in `fbb0803`, read *"Pinned against 04 §2 rule (a)'s own sentence by `tests/test_hold_composition.py`"*. No such file existed, and nothing under `tests/` referenced `compose_hold` or `POOL_USERS` at all | **The test was written** rather than the claim deleted, because the roster genuinely needs it: `POOL_USERS` is *declared, not derived* (three of its five detectors do not exist yet), so a short roster would make every published hold smaller — wrong in the safe-looking direction, with nothing failing. `tests/test_hold_composition.py` now parses 04 §2 rule (a)'s sentence and asserts the two agree, plus the six holds and both halves of the composition rule | The repo's recurring defect class — *a claim described by a premise it does not come from* — and this instance was **inside the amendment that exists to fix that class**, committed the same hour. Worth recording for what it says about the failure mode: `eval.check_derivations` re-derives the published *table*, so the amendment looked fully guarded; the unguarded thing was the roster the table rests on. A citation to a guard is not a guard |
| M-50 | **A detector's tunable parameter names were cited in a docstring before they existed anywhere else.** `tier2_toxicity` reads `cutoff_moderate` / `cutoff_high` from `detector_params`, and both names were introduced by the module itself — no entry in 04 §2's registry table, none in 05's policy schema. Resolved MINOR-style per §11.1 (the obvious low-risk answer: keep the names, which mirror the two cutoffs 04 §2.2 already describes in prose) and logged here rather than left implicit, because the same shape is M-49 one step earlier — a claim whose premise lives only in the sentence making it. Distinct from M-49 in that nothing is *false*: the params work, and the gap is that a config key a policy author could set is documented in a Python docstring instead of the schema |
| M-51 | **The embedding checkpoint was named "MiniLM" and never pinned.** `02 §8` says "sentence-transformers" and `pyproject.toml`'s comment says "MiniLM embeddings"; neither names a release, and `rag_grounding` cannot serve a family. Resolved MINOR-style per §11.1 with the canonical `sentence-transformers/all-MiniLM-L6-v2` — the smallest real bi-encoder, chosen for a 30 ms CPU budget — pinned in `rag_grounding.MODEL_ID` as the single source. Logged rather than left implicit because an unpinned family name lets two hosts publish different numbers under one figure, which is the defect class this repo keeps finding. | Resolved: `MODEL_ID` pins the release; no published figure predates the pin. | PROVISIONAL — batch review at phase end |
| M-52 | **The calibration target rate the spec calibrates at does not exist.** 04 §7 step 3 says τ is recomputed "at **the policy's target rate**", but there is no such field: not in `Thresholds`, not in any `policies/*.yaml`, and no α anywhere in 04/05/06. Resolved MINOR-style per §11.1 with the conventional conformal default **α=0.10**, applied uniformly, exposed as `--alpha` and printed beside every figure it produces. Deliberately **not** added to the policy schema — a new `Thresholds` field is a contract change needing an ADR, and the conservative reading of an undefined term is not to invent a contract for it. | Resolved: `suggest_thresholds.DEFAULT_ALPHA = 0.10`, stated in the report. Note SL-7 makes α moot for now — the band inverts at every α, so no choice of target rate would have shipped a calibrated value. | PROVISIONAL — batch review at phase end |
| M-53 | **A budget breach reaches the audit record as a detector fault, so a fault-injection assertion can fail with no fault injected.** Observed 2026-08-30: `test_fail_open_records_the_fault_without_letting_it_contribute` failed with `('tier2_toxicity', 'numeric_claims')` where one entry was injected. Load-dependent — 6 isolated reps passed, but at load1 2.6 → 1.5, so those reps are diagnostic only (06 §8) and no rate is published | Resolved: **not resolved here, and deliberately not resolved.** Logged against the OPEN `[D3-nfr-p002-gate-reads-the-clock-adr-036-rejected]`, whose recommendation (**A2**, partition the gated series by outcome) is the fix. The test is untouched: it fired on exactly the condition it guards, and relaxing the tuple to a subset would delete this repo's only live evidence of the phenomenon | **Ratified 2026-08-30. Diagnosis CONFIRMED; mechanism NOT eliminated.** On a quiet host `fault_injection` goes 36/39 -> **39/39** with **no test touched** (the failing assertion is byte-identical), which is the cleanest evidence for the diagnosis: the fix was upstream of the test, the direction §5.4 requires. But it **recurs under load** — in a full-suite run the same assertion fails 38/39 with `modes_applied=['fail_closed', 'fail_open']`. Amendment 1 separated the two *metric* series, which is what unfailed the bench gate; it did **not** change the audit record's failure vocabulary, where a budget overrun is still recorded as a detector fault. So the published 39/39 is a real quiet-host result and not a fixed invariant, and [[M-54]] (this harness stamps no load) is what makes that distinction invisible in the artifact. Stated rather than smoothed over: 'passes when quiet' and 'passes' are different claims. No rate published from loaded reps |
| M-54 | **`eval/fault_injection.py` stamps the commit but not the host load, and its outcomes have since become load-sensitive.** It imports `git_stamp` alone from `eval.host_load` — no `load_stamp` — so `reports/fault_injection_report.md` carries no load row, while both timing harnesses stamp start and end. Defensible when that harness published only boolean 04 §5 invariants; **M-53 removed that defence**: a budget breach reaches the audit record as a detector fault, so a contended host can flip a control-probe assertion. The published **36/39** therefore has a load dependence its own artifact cannot express | Resolved: **not fixed, and named rather than fixed.** Adding the stamp is a two-line change, but a *stamp* would only record the conditions — it would not make the 3 failures interpretable, and the interpretation is what the OPEN `[D3-nfr-p002-gate-reads-the-clock-adr-036-rejected]` decides (its **A2** partitions the gated series by outcome). Fixing the stamp first would publish a quiet-host artifact still carrying three failures of unstated cause, which reads as three defects rather than one root cause | PROVISIONAL — batch review at phase end |
| M-55 | **`git_stamp` reports any untracked file as a dirty tree, so read literally `reproducibility_verdict` disqualifies every artifact this repo emits.** `git_stamp` computes `"dirty"` as `None if porcelain is None else bool(porcelain)` — ANY `git status --porcelain` output, including untracked files and the **sibling reports each measurement run writes**. So the tree is dirty *by construction* during a measurement run, every artifact stamps "+ uncommitted changes", and `reproducibility_verdict` calls that NOT CITABLE | **Resolved 2026-08-30 by adjudication — fixed.** Was *logged, not fixed*, on the reasoning that the honest fix is a judgement about which dirt matters and that such a judgement should not be quietly widened at deadline **by the agent whose artifacts it grades**. The adjudicator widened it on the record instead: 06 §8 now exempts files under `reports/` that are untracked solely because the measuring run wrote them, and requires the stamp to **list** what it excused. `classify_porcelain` implements exactly that allowlist and no wider — untracked under `reports/` only, so a *modified tracked* report still disqualifies — and `code_commit_cell` renders `clean except run-generated: …`. Pinned by seven tests in `tests/test_host_load.py` whose job is to fail if the boundary moves outward, one per boundary the ruling drew (untracked-report excused, modified-tracked still dirty, outside-`reports/` still dirty, mixed dirt still dirty, spaced paths not split, listing present when excusing, listing absent when not). Side effect: the three report harnesses had the dirty-flag rendering copy-pasted, which is how the allowlist would have reached one report and not the others — consolidated onto `code_commit_cell`, and `reproducibility_verdict` gained the third value that became M-57 | Ratified 2026-08-30 (definition); implementation AUTO-RATIFY CONDITIONAL on Checkpoint 4 |
| M-56 | **A judge-facing report shipped a sentence that contradicted its own arithmetic: "no α clears the 56/78 = 0.718 oracle ceiling — the best row here reaches 59/78 = 0.756".** 0.756 > 0.718. The figures were each computed correctly and the *comparison* was invalid: `_in_band` partitions the line only when `tau_low < tau_high`, so for an INVERTED band the `borderline` arm is unsatisfiable (it places nothing) while the outer arms **overlap** on `[tau_high, tau_low)` and each grade against a looser threshold than any valid band could use — the count *inflates* with inversion depth. `_oracle_band` skips `lo >= hi`, so the ceiling is fitted over valid bands only. `_alpha_sweep_block` then took `best` over ALL sweep rows | Resolved: **fixed at the generator and the artifact regenerated**, never hand-edited (§5.4). `best` is now scoped to schema-valid rows, inverted rows are marked `†` as non-comparable, and the section states the mechanism. The inflated counts stay **published** — suppressing a real computation is the other failure mode; what was wrong was calling one of them best. Pinned by `test_an_inverted_band_places_no_borderline_case_and_overlaps_its_outer_arms`, `test_the_oracle_ceiling_is_fitted_over_valid_bands_only` and `test_the_sweep_scopes_its_best_row_claim_to_schema_valid_bands`. **SL-7 needed no correction** — it already said "no **schema-valid** band can beat that" and compared a valid row (51/78) to the ceiling; the defect was confined to the generated section | PROVISIONAL — batch review at phase end |
| M-57 | **`reproducibility_verdict` rendered an *unrecorded* tree state as a clean tree.** Found while implementing M-55's allowlist. `git_stamp` is deliberately three-valued about dirt — `dirty: None` means git did not answer — but the verdict tested only `if stamp.get("dirty")`, so `None` fell through to the `clean` branch and reported *unverified* dirt as *verified-absent*. That is the one conflation `eval/host_load.py` exists to refuse; it is the same defect `is_quiet`'s three-valued treatment was written to prevent, in the sibling field, and it survived because only the load half was ever pinned | Resolved: **fixed.** Third branch added to both `reproducibility_verdict` and `code_commit_cell` — "tree state not recorded — NOT CITABLE", worded so it cannot be misread as an accusation of dirt, matching `quiet_verdict`'s distinction between *never measured* and *measured and failed*. Pinned by `test_m57_an_unrecorded_tree_state_is_not_reported_as_a_clean_tree`. **No published artifact is affected**: the window needs `rev-parse` to succeed while `status` fails (an index lock, a `status`-only timeout), every committed report stamps a real `dirty` boolean, and the one consumer of `reproducibility_verdict` is `eval/spike_window_latency.py`. Latent, not observed | Ratified 2026-08-30 with M-55 (same change) |
| M-58 | **A negative control asserted a shared aggregate exit code, so a genuine breach elsewhere failed it with a message blaming the wrong thing.** `test_a_wall_clock_breach_alone_renders_no_budget_verdict` (added with ADR-036 Amendment 1) asserted `bl.main(...) == 0`. That exit code aggregates **every** violation — NFR-P-001 and NFR-P-002, all detectors — while the test's subject is one injected wall-clock overshoot on one detector. It passed in isolation and failed in the full suite, and its failure message read *"the gate is reading the series ADR-036 rejected"* — which was false: verified in isolation, the injected overshoot yields exit 0 and renders no `tier1_pii` verdict, so the gate was correct and the trip came from an unrelated violation under suite load. With `tier2_injection` now genuinely breaching at P99, an aggregate assertion makes this systematic rather than occasional | Resolved: **fixed, and the pin tightened.** The assertion is now **per-detector** — no NFR-P-002 line may name `tier1_pii` — which is a *stronger* pin on the actual subject than the exact-row string it replaced (it also catches the row being reformatted) and cannot be satisfied or broken by any other detector's result. `rc` is checked only for `in (0, 1)`, ruling out a crash. **Not a weakened test (§5.4):** the code under test was verified correct before the test was touched, so the defect was the assertion's scope, not the behaviour it guards — but flagged here prominently because *fixing the test rather than the code* is the shape of the forbidden move, and the adjudicator should see it as such | PROVISIONAL — flagged for Checkpoint 4 |
| M-59 | **Every published hold row composes from a *declared* budget, and one of those budgets is now measurably missed.** `compose_hold` reads `BUDGETS_MS`, so the six ADR-030 Amendment 3 rows are arithmetic over the declared 25.0 ms for `tier2_injection` while the measured attributable P99 is 25.348 ms. Every hold containing that detector is therefore optimistic by ~0.35 ms | Resolved: **checked, and no published row flips.** `tier2_injection` appears in exactly one row — the input lane, 30.0 ms against a P99 < 50 ms target — which absorbs 0.35 ms with ~20 ms to spare. The zero-margin row (per-sentence typical enriched, 40.0 against a strict < 40) composes `tier2_toxicity` + `entity_enricher`, and `tier2_toxicity` measured **inside** budget at 23.741 ms, so it inherits nothing from this miss. Rows stay derived from declared budgets deliberately: substituting a measured figure would make the published table move with every re-run and would no longer be the specification arithmetic `eval.check_derivations` verifies (72/72 OK). Logged so the optimism is stated rather than discovered | PROVISIONAL — batch review at phase end |
| M-60 | **[[M-53]]'s mechanism is carrier-general and occurs on a QUIET host, so "passes when quiet" was too strong a reading.** M-53 recorded the failure as load-dependent with `tier2_toxicity` as the carrier. Re-measured 2026-08-30 across **five separate harness processes** at `load1` 0.85–0.99 — inside the 06 §8 quiet threshold — the control-probe assertion `hr_copilot: control (no fault) passes` failed in **2 of 5** runs, and at pytest level in **2 of 6** quiet repetitions. The carrier is **any pool-serialized detector** (`rag_grounding` included, which M-53 predates): a budget overrun is recorded in the audit record as a *detector fault*, so whichever pool user happens to run slow manufactures a fault on a probe where none was injected. Load raises the probability; it is not the precondition. | Resolved: **the claim shape is fixed, the test is not touched.** Per the owner's Branch-B pre-ruling, `eval/fault_injection.py` gained `--reps N` and now publishes an observed **rate** with a per-repetition load table in place of the single-run `39/39` — the superseded claim preserved in a blockquote, not deleted. **Two n=5 measurements disagree and both are published:** 3/5 clean across separate processes, **5/5 clean within one process**. The candidate explanation is model warmth (one process pays first-touch ONNX initialization once; five pay it five times), supported by load climbing 1.04 → 1.24 during a single repetition and then flattening — **plausible, not established**, and the report states that an in-process rate measures the warmed steady state rather than the cold path. Remedy for CI is **retry-once at the CI level, never a test-level tolerance** (owner ruling; a tolerance would delete this repo's only live evidence of the phenomenon, AGENTS.md §5.4). | Ratified 2026-08-30 (owner Branch-A/B pre-ruling); measurement is Branch **B** |
| M-61 | **05 §1.1 documents an `X-ControlPlane-Actions` response header that the gateway does not send.** Found while wiring `dashboard/static/chat.html` against the real surface: observed EDIT responses carry only `x-controlplane-request-id` and `content-type`. The verdict and the applied transforms arrive in the **final SSE chunk's `controlplane` block** instead. | Resolved MINOR-style per §11.1: **the console reads the body**, which is the surface that actually exists, and a comment at the parse site records why rather than leaving a future reader to assume the header was overlooked. Deliberately **not** fixed by adding the header at this deadline — that is a response-contract change on the demo path, and the body already carries strictly more (the per-transform list a single header value cannot express). Logged rather than silently coded around, because a doc promising a header no client can rely on is the same defect class as a figure with no derivation. Roadmap: either emit the header or delete it from 05 §1.1 — the two states are not interchangeable, and one of them has to be chosen. | PROVISIONAL — batch review at phase end |
| M-62 | **One config key carried three unrelated meanings, and promoting it broke thirteen tests including a sentinel written to catch exactly that.** Switching `active_provider` to `groq` (to give the console chat a working upstream) also switched (a) the ADR-018 provenance class `require_measured_upstream()` gates judge-facing reports on and (b) the class every **offline** path inherits when it builds a `Gateway` with no explicit config — tests, `demo.run_script --replay`, `eval.fault_injection`. A fixture upstream reports no prompt-token usage, and for a measured provider FR-GW-006 makes that **boot-fatal**, so those paths refused to boot while claiming a provenance a fixture cannot have. `test_a_dispatched_unpriceable_request_is_still_null_on_the_measured_class` asserts `"active_provider: kiro-local" in text, "config drift: the dev default moved"` — it caught the change on the first run. | Resolved: **the key's jobs are split; no test was edited to accommodate the change.** `load_gateway_config(path, *, active=...)` overrides the provider **before validation** (through the constructor, not `model_copy` + attribute assignment, which would skip the provider-graph and pricing validators on a provider about to serve real traffic), and `create_app` gained a sibling `create_live_app()` that names the measured provider. The shipped default stays `kiro-local`/dev **deliberately**, and the YAML comment records why rather than reading as an oversight. The decisive reason is provenance, not convenience: every artifact in `reports/` was generated under dev class and says so in its own prose, so a measured shipped default would let the next regeneration **drop that caveat silently** — the same defect class as a figure described by a derivation it does not come from. Promoting `groq` to the default is a real upgrade (measured class + first-party prices for both bound ids makes cost figures citable) but it is an owner ruling about published provenance, not a side effect of fixing a chat page. Pinned by five tests, of which `test_the_shipped_default_is_dev_class_so_offline_paths_inherit_dev` and `test_the_override_is_validated_not_merely_assigned` are the load-bearing pair. | Ratified 2026-08-30 (owner: correct architecture; the sentinel catching the naive fix is a ledger highlight) |
| M-63 | **`.env` is documented as the secret mechanism and nothing in the repo loads it.** AGENTS.md §10 says secrets travel "via .env (gitignored)" and "Copy .env.example → .env to start"; 05 §6 makes the variable names normative. But no module imports `dotenv` — `python-dotenv` is not even installed — so `os.environ` never receives the file's contents and **every keyed provider sees an unset variable**. This is the actual root cause of the console chat rendering no model text: `kiro-local` returning HTTP 401 on an empty `UPSTREAM_API_KEY` was a symptom one layer down, not the cause. Measured, not inferred: with the key absent the FR-GW-006 canary emits `CanaryUnavailableWarning … the invariant is UNVERIFIED for this boot, not satisfied`; with the same file exported into the environment the canary passes silently and the same request returns HTTP 200 with real model prose. | Resolved MINOR-style per §11.1 without adding a dependency: the operator exports the file (`set -a; . ./.env; set +a`) before `uvicorn`, and AGENTS.md §10 now states this instead of implying the file is read. Deliberately **not** fixed by importing `dotenv` at module scope — an implicit environment mutation on import is the wrong default for a process whose boot behaviour is load-bearing (a measured-class provider *refuses to boot* on a failed canary), and it would make the gateway's key resolution depend on the current working directory. The canary's three-valued reporting is what made this diagnosable rather than a silent empty reply, and it is worth noting that it worked: it distinguished "unreachable" from "accounting wrong" and said UNVERIFIED rather than passing. Roadmap: either an explicit `--env-file` on the documented run command (uvicorn supports it, needs `python-dotenv`) or a first-line loader in the CLI entry point — both are real options and neither is a deadline task. | Ratified 2026-08-30 (owner: correct architecture; the sentinel catching the naive fix is a ledger highlight) |
| M-64 | **A non-streaming response body carries top-level `usage: None` while the FR-GW-006 canary receives `prompt_tokens: 121` from the same provider on the same boot.** Observed 2026-08-30 while verifying the live path end to end after the [[M-62]] split: `POST /v1/chat/completions` with `stream:false` against `finance_advisor` returned HTTP 200, `verdict: pass` and real model prose, but no top-level `usage` object — while the boot canary, dispatching through the same measured-class provider seconds earlier, read 121 prompt tokens and passed. Those two facts cannot both describe one accounting path, so one of them is reaching the response body by a route the other does not. | **Owed, and UNINVESTIGATED by owner ruling 2026-08-30 — deliberately not diagnosed.** It blocks nothing tonight, though for narrower reasons than when this row was written: the cost plane now **enforces** and beat 7b **passes**, so "the cost plane is a disclosed gap" and "beat 7b skips" are both stale — the surviving gap is the cascade *router* ([[SL-10]]), not the gate. Cost figures **do** ship, and the gate below still permits them because **none is derived from this path**: `reports/cost_report.md` computes from the frozen corpus, the `config/gateway.yaml` price table and a character-derived token estimate, never from a provider's self-reported non-streaming `usage`. The ledger reads `est_cost_usd` for the live budget gate, but no judge-facing figure is derived from it, and the gate's scope is **unchanged by tonight's work**. The failure mode is also the safe one — `None` is the honest reading (*nothing was observed*) rather than a `0.0` that would assert a request cost nothing, so no false figure is published today. **The gate this row exists to set: any future cost figure derived from the non-streaming path is blocked until this is resolved.** A cost figure computed over silently-absent token counts is exactly the defect class this repo keeps finding — a figure described by a derivation it does not come from — and it would be invisible, because the arithmetic succeeds. Roadmap: reconcile the canary's dispatch with the request path's usage propagation, then re-verify against a live measured provider before any cost claim is cited. | Owed — owner-ruled 2026-08-30 (do not investigate tonight); standing gate on any future cost figure from this path |
| M-65 | **`DetectorContext` gained a third projected-policy channel (`cost`), which tripped the FR-POL-002 sentinel that asserts its exact field set.** The guard's own docstring says it exists to catch "the subtler version, where someone adds `use_case` or `label_actions` for convenience" — so the failure was the guard doing its job, not a false alarm. | **Guard EXTENDED, not relaxed.** `cost` is admitted **only because** `CostView`'s own field set is now pinned beside it (`test_fr_pol_002_cost_view_carries_quantities_and_nothing_identifying`), plus two structural assertions: no field name may contain `use_case`/`policy`/`action`/`text`/`hash`/`id`, and no field may be typed `str` or `bytes`. Widening the outer set alone would have traded a guard for a hole — a nested model can carry a `use_case` the outer check never sees. The tempting alternative, smuggling the scalars through `detector_params` to avoid touching the test, was **rejected**: that channel mirrors policy-authored config, and routing live ledger measurements through it to dodge a sentinel is the laundering the sentinel exists to catch. | Not a deviation: 04 §1 already permits the engine to project policy figures as plain data, and this is the third instance of a documented pattern (`blocklist_extra`, `detector_params`). Numbers and one boolean; no `Policy`, no use case, no label→action map. |
| M-66 | **04 §2's `cost_budget` row text implies a ledger lookup inside the detector, and the shipped split puts that read in the gateway.** So the detector's measured 1 ms latency covers arithmetic only, and is narrower than the row's wording suggests. | **PROVISIONAL — batch review at phase end.** The read lives in `pipeline.cost_view()` and the detector receives plain scalars, for two reasons that both point the same way: a detector holding a use-case-keyed ledger handle could learn its use case (FR-POL-002, AGENTS.md §9.1), and a SQLite round-trip does not fit a 1 ms budget, so a detector-side read would have forced either a budget breach or a fabricated budget. Recorded in `detectors/cost.py` and in `tests/test_cost_plane.py::test_cost_detectors_complete_inside_their_budget` rather than left for a reader of the latency report to infer. | Not a deviation: no doc is contradicted — 04 §2 declares a budget and a signal, and both hold. What changed is *where* the I/O sits, an implementation choice inside a settled contract (§11.1). The **claim** about what the number covers is stated, which is the part that would otherwise rot. |
| M-67 | **`CostLedger` is a process global holding per-thread connections, and its turn state made `repeated_turn` order-dependent across tests.** Observed, not theorised: 13 `test_forensics.py` tests passed in isolation and failed in the full suite, because one test's turn became the next test's "repeat" and all three policies map `cost.loop_detected: block`. | Two fixes, both structural. `bind()` clears conversation state as well as the cache — a new database is a new deployment's view of history, so turn hashes accumulated against a different one describe conversations the ledger cannot see. And connections are opened **per calling thread**, matching `Gateway.conn`: a shared connection would raise cross-thread, and because `_query` treats a read failure as absence of evidence, the cost plane would have gone **silently** dead rather than failing loudly. `read_errors` counts what the fail-soft path swallows, since a fail-soft path with no counter is indistinguishable from one that never ran. | Not a deviation: ADR-006 already chose WAL so several connections to one file are safe, and this is the same arrangement the gateway documents. The global's scope is stated as PROVISIONAL in `app.py` — the most recently constructed gateway owns it, which is correct for serving and for test isolation, and would need a per-gateway ledger only for two concurrent gateways on different databases, which nothing in this build does. |
| M-68 | **A citable report could not be produced from the working tree**, because two untracked business-proposal binaries at repo root make `classify_porcelain` return `dirty: True` — its allowlist covers untracked paths under `reports/` only. Every artifact generated there self-stamps **NOT CITABLE**. | `reports/cost_report.md` was generated from a **pristine `git worktree` detached at the commit under test**, whose tracked content is byte-identical to `HEAD`, and the figures were then diffed against a working-tree probe with provenance lines excluded — **identical**. So the artifact's `0f48172384db clean` stamp is *true* rather than laundered. `classify_porcelain` was deliberately **not** widened: its docstring refuses that explicitly, and adjusting a citability harness so a run can excuse itself is what AGENTS.md §5.4 forbids. | Not a deviation: 06 §8's rule was satisfied as written, not reinterpreted. The two untracked files are outside this workstream and were left untouched — flagged to the owner rather than committed or gitignored, since deciding whether a deliverable binary belongs in the tree is not an agent's call. |
| M-69 | **Two judge-facing generators carried hardcoded claims that tonight made false.** `forensics.py` said "cost plane unbuilt — `cost_budget` and `loop_guard` are stubs" on any record with no cost span, and `eval/run_all.py` rendered "not implemented — stub" for both detectors into `reports/eval_report.md`. | Both **derived** now, following the `_enricher_reason()` precedent for the same rot. Forensics reads the record's own coverage column and distinguishes *ran-but-no-span* (a real column disagreement, reported rather than smoothed), *not_run*, *unavailable*, and *not listed at all* — which 05 §4 makes genuinely ambiguous between "policy disabled it" and "the record predates the plane", so the node says exactly that instead of guessing. `_cost_reason()` reads `LIVE` plus the corpus label counts. A forensic view reads **history**: a fixed sentence about the build's state is a claim about the reader's present tense stamped onto a row from the past. | Not a deviation: this is the M-42/M-43 class (a claim described by a premise it no longer comes from) caught in two more generators, and resolved the way that class already was — by derivation. Both replacements also handle the *future* flip: `_cost_reason` reports the corpus-carries-cases branch rather than silently keeping today's reading. |
| M-70 | **`cost.request_too_large` is emitted by a live detector and mapped by no shipped policy**, so it resolves to `default_action: pass` — recorded in the audit log, never acted on. ([[M-28]] anticipated this from the schema side; it is now observable at runtime.) | **Left unmapped, deliberately**, and pinned by `test_request_too_large_is_audit_visible_but_unmapped_today` in all three policies. Mapping it to make a demo beat fire is what AGENTS.md §9.1 forbids — the label→action map is the owner's decision surface, not a lever for the build to pull. The test asserts both halves (absent from the YAML **and** `Action.PASS` through the real engine), so if a policy later maps it, the test fails and the README claim is revisited with it rather than drifting. | Not a deviation: 04 §4 already defines the unmapped-label path, and `default_action: pass` is that path working. The gap is in *policy configuration*, which is exactly where the product says behaviour lives. |

**Resolved 2026-08-26 under the Phase-4 ruling** (was: flagged, not fixed):
`SPAN_LESS_LABELS` in `eval/validate_dataset.py` contained `cost.runaway_loop`, which is **not in
the taxonomy** — the real label is `cost.loop_detected`. Corrected on instruction. The member was
provably dead: zero corpus cases carry it, and the validator's output is **byte-identical**
before and after (280/280, freeze digest `6a3ecbbe75fd020b…` still matching), so the edit to a
freeze-adjacent file moved no number.

**Closed 2026-08-26 by M-9** (was: flagged, not fixed): the divergence reported here — the matrix
including `cost.request_too_large` where the validator did not — is resolved by single-sourcing,
which the Phase-4 housekeeping ruling authorized. The consequence noted at the time still reads
correctly as the reason it mattered: had a `cost.request_too_large` case ever been labelled EDIT,
the validator would have skipped the ADR-015 promotion the matrix applies. It stayed dead
throughout (zero corpus cases), so nothing computed under the freeze was ever affected.

## Standing Limitations

**Purpose.** Permanent home for **decided-but-unmet** items: things ruled on, understood, and
consciously accepted — not open questions and not open deviations. Without this register, closing
a deviation whose gap survives would make the gap invisible, and a ledger reading `Open: zero`
would look like "nothing missing" when it only ever means "nothing undecided". An entry leaves only when the limitation
itself is gone, never because it stopped being newsworthy.

| ID | Limitation | Measured / stated | Why it stands | Where it is visible |
|---|---|---|---|---|
| **SL-1** | **NFR-EVAL-001 unmet** — `tier1_pii` recall below the 0.95 target | **0.8852** vs 0.95 (precision 1.000, so no over-firing). v1 baseline **0.8361** | **100% of the residual misses are the documented bare-7-digit scope exclusion** (ADR-026 §3) — 7/7, verified programmatically by stripping co-occurring SSN/card/email spans and measuring the phone candidates' digit length (all 7, none ≥10). A bare `NNN-NNNN` is indistinguishable from an order or ticket id, so matching it would trade the perfect precision away. **The target was not moved** (ADR-026 §5) | `reports/eval_report.md` §NFR-EVAL-001 + §Disclosed revision; README claims row *Tier-1 PII recall*; closed deviation `D3-tier1-pii-recall-below-target` |
| **SL-2** | **v1-superset phone behaviour**: an invalid NANP area code still fires — e.g. `(115) 555-0123` | Documented v1-superset behaviour, **not a bug** | v1's `_PHONE` is retained deliberately and evaluated first, so it shadows the NANP `N ∈ [2–9]` rows. Narrowing it would change v1-derived behaviour and the permanent precision-1.000 baseline would no longer describe code that ships. Precision hardening is a **later freeze cycle** and must not ride along with a measurement | ADR-026 Amendment 1; 04 §2.5; `tests/test_tier1_detectors.py::test_nanp_n_constraint_rejects_leading_0_and_1` (asserts at pattern level, docstring records the shadowing) |
| **SL-3** | **DOWNGRADED 2026-08-27 (ADR-029) — now a provenance-*freshness* reminder, no longer a publication gate.** First-party prices exist for both bound ids | `console.groq.com/docs/models` carries per-1M figures directly: `openai/gpt-oss-20b` **$0.075 in / $0.30 out**, `openai/gpt-oss-120b` **$0.15 in / $0.60 out**. Retrieved 2026-08-27. The retired llama pair now prices as "ContactSales" on that same page, which is why its old figures were never obtainable first-party | **Absolute dollar figures ARE publishable for these two ids**, carrying `source_url` + `retrieved`. Two limits stand: any comparison priced on the **retired llama pair remains barred** (never first-party, and the models no longer serve, so it can never be re-verified); and prices are **re-verified at submission packaging**, since a stale price is a wrong price. The entry stays open for that re-verification, not for a missing source | `config/gateway.yaml` (provider `groq`); ADR-022; **ADR-029**; README claims section; 06 §6 |
| **SL-4** | **CLOSED 2026-08-28 (owner evidence).** ~~No genuinely local fallback model installed~~ | `llama3.2:3b` is installed on the **owner's** host (Ollama v0.33.0) and passes the no-`remote_host` assertion, so it is genuinely local and `unmetered` holds. Bound to `ollama-local`'s **small** tier; `frontier` left null (one model evidenced — binding both would make the cascade a no-op while looking configured) | The limitation itself is gone, which is the only reason a row leaves this register. **But it is gone host-by-host:** the development host still serves only `minimax-m2.7:cloud` with `remote_host` (Ollama v0.31.1, re-confirmed 2026-08-28), so there a dispatch to this provider fails and no fallback latency or cost figure can be produced — AGENTS.md §7 still bars reporting one from that host. The row is kept and struck through rather than deleted, so the closure is auditable against the condition it closed | `config/gateway.yaml` (`ollama-local`, `small` bound, STUBs removed); Q-10 **RESOLVED**; `tests/test_gateway_config.py::test_sl4_ollama_binds_the_owner_verified_local_model` pins the config-level claim — deliberately not a live dispatch |
| **SL-5** | **The Tier-2 <25 ms budget is measured with 6 threads free for one inference**, and NFR-P-002 states no concurrency assumption | At **1 thread**, both ADR-031 picks breach at the output segmenter cap: `madhurjindal` **25.90 P50 / 26.20 P99**, `martin-ha` **34.48 / 35.50** (ONNX int8, n=50). Both still fit at corpus-typical lengths (**17.81 / 10.62 P50**) | Every Tier-2 figure this repo publishes is a **low-concurrency** figure: one inference gets the whole CPU on an idle laptop, and under concurrent requests per-request parallelism falls toward the 1-thread column, where the budget stops holding at the cap. Not tuned away and not reported as a passing number — the 1-thread column is published beside the 6-thread one so the exposure is visible rather than inferred. Bounding it properly needs a concurrency figure NFR-P-002 does not state and no harness here measures; a load test is **Phase 6+** and out of hackathon scope | ADR-031 §5; `reports/spike_tier2_models.json` (both `threads` sweeps); any Tier-2 latency claim in the README or 06 §4 |
| **SL-6** | **`fast_consistency` is CUT to roadmap** — specified (04 §2.3), unimplemented. The UC-3 performance plane is covered by `rag_grounding` | Not a measurement: a **scope cut** taken 2026-08-30 under deadline and credit pressure, with the detector's spec left standing rather than deleted | 04 §2.3 already rules that where context exists `rag_grounding` covers the plane, so UC-3 keeps a performance-plane check; what is lost is the *context-free* case, where a claim with no retrieved document to check against now goes unscored on that plane. The 2nd-sample provider was bound (Q-10, 2026-08-28) and the detector was not, so this cut removes work that was never started rather than abandoning work in flight. All three policies consequently read `consistency: "off"`, which **flattens ADR-014's axis**: its `on => streaming: false` guard is now unexercised by any shipped policy, though still enforced by the schema. `hallucination.low_confidence` mappings are retained and **inert** — the label keeps its schema membership and no signal carries it | `policies/*.yaml` (`consistency`, `policy_version` bumps); 04 §3 example; `eval/run_all.py` SKIPPED reason and `reports/eval_report.md`; `tests/test_policy_schema.py::test_uc_profiles_differ_in_delivery_mode_per_adr_014` |
| **SL-7** | **τ cannot be calibrated as 06 §3 specifies — the band INVERTS at the blind-chosen target rate.** The documented procedure (conformal-style quantiles, 70/30 stratified split of `halluc` + `borderline`) at α=0.10 (M-52) yields τ_low **0.8365** ≥ τ_high **0.7157**, which `Thresholds._check_band_order` rejects, at **5 of 5** reshuffle seeds. So the τ in `policies/*.yaml` stay `# SEED(pre-calibration)` and 06 §3's rule holds: **no report figure derives from a seeded τ**. Figures below come from the *proposed* band, not a seed; they are the evidence for this row and are **not** a detector accuracy claim, since the band ships in nothing. | **78** context-bearing calibration points (62 `halluc` + 16 `borderline`), α=0.10, blind first contact. AUC(`yes` vs `no`) **0.8751** — the score is informative. **The mechanism is tail overlap, not class order.** The three medians ascend correctly (`no` **0.6380** < `borderline` **0.8188** < `yes` **0.8766**) and 13/16 `borderline` cases fall between the outer medians, so the classes are not mis-ranked. What breaks the band is the tails: `yes` reaches down to **0.1302** and `no` up to **0.9583**, so demanding 90% coverage on each edge drives τ_high *below* τ_low. At that band **11 of 41** `no` cases sit at/above τ_high and **7 of 21** `yes` cases below τ_low. Reshuffle spread: τ_low 0.8039–0.8808, τ_high 0.6546–0.7980. | **The ceiling, not the quantile, is the limit — and it is α-independent.** An oracle band fitted on all 78 points by exhaustive search, with every label visible, places only **56/78 = 0.718** correctly; no schema-valid band can beat that at any α. The α sweep confirms the shape rather than offering a fix: α≥0.20 does un-invert the band, but scores **worse** in-band (51/78 at α=0.20 vs the 0.718 ceiling), so no target rate yields a usable band — and selecting α *because* 0.10 failed would be tuning a parameter toward a desired outcome (§7, §11.1 item 3), so α stays where M-52 fixed it blind. Root cause: 04 §2 calls this detector an entailment **proxy**, and a cosine between sentence and context embeddings cannot see hedging — `BRD-01` ("refunds usually complete within about a week" vs context "processed within 5 business days") is a real overclaim that is lexically near-identical to its source, so it scores high where a `borderline` case must score low. That is what puts the tails where they are. Closing it needs a real entailment model: a **detector** change, not a τ change — out of scope at this deadline. | `eval/suggest_thresholds.py` (exits nonzero on the inversion rather than clamping; every figure here is one of its outputs), the *Threshold calibration* section of `reports/eval_report.md`, `tests/test_suggest_thresholds.py`, and this row |
| **SL-8** | **NFR-P-002 unmet for `tier2_injection`** — the single-window *attributable* P99 exceeds the flat 25 ms budget. | **`tier2_injection` single-window attributable P99 25.348 ms vs 25 ms target (CPU int8, quiet host); p50 within budget; tail breach; target unmoved per ADR-026 §5; roadmap: ORT intra-op tuning / serving hardware.** n=300, **0 faults**, measured on the ADR-036 Amendment 1 attributable instrument — so this is a budget miss, not the clock artifact its predecessor deviation turned out to be. | **A tail breach at 1.4% is the predicted shape of [[SL-5]], not a new discovery**: SL-5 records that the <25 ms figure was measured with six threads free for one inference, and ADR-034 then serialized the model detectors onto a single worker — a budget calibrated under the first condition should be marginal under the second. Filed per §7 as an honest number plus a deviation rather than a tuned harness, and closing the deviation does not close the gap, which is why this row exists. **Distinct quantity, stated to prevent a conflation:** ADR-034's *enforcement ceiling* (measured-envelope ×2, length-parametric) is unaffected — a budget is the intended cost, a ceiling is where the executor abandons the call, and this miss moves neither the ceiling nor any hold row derived from it ([[M-59]] checks that arithmetic). | `reports/latency_report.md` (per-detector table, NFR-P-002 column); closed deviation `[D3-tier2-injection-attributable-p99-exceeds-25ms]`; the README claims table, which states the breach; `dashboard/static/dashboard.html` (row marked "NO — SL-8"). **Prose constraint, permanent:** no README, proposal, dashboard or demo sentence may claim NFR-P-002 *met* for this detector |
| **SL-10** | **The two-tier cascade router is NOT BUILT** (04 §2.4 / ADR-009 / ADR-013). The cost plane's *gate* ships — `cost_budget` and `loop_guard` enforce live — but nothing routes a request to the small tier and escalates it on low confidence, so the cascade **saving** is a parametric result rather than a measurement. | Not a measurement: a **scope state**, stated so the simulation's shape is not mistaken for a hedge. `eval/cost_simulation.py` computes `saving = 1 − (1/r + f)` at the measured ratio `r = 2.0` (exact on input **and** output, so blend-independent), giving **+50.0%** at `f=0`, **+25.0%** at `f=0.25`, **break-even at `f=0.50`**, and a **loss above it**. **`f` is NOT COMPUTED** — it has no producer in this build: `fast_consistency` is cut ([[SL-6]]), no code path reads `thresholds.tau_route`, and `audit_records.cascade_escalated` is a column nothing writes. The 06 §6 cascade-quality proxy is NOT COMPUTED for the same reason: its input is the cut detector. | A curve with a named gap is the honest output; a single percentage would require choosing `f`, and any choice would be an assumption presented as a result — the defect class this repo keeps finding, *a figure described by a derivation it does not come from*. Publishing the break-even is the load-bearing half: it states the condition under which the routing **loses** money, which a savings-only claim would hide. Also gated by [[M-64]] — any cost figure from the non-streaming path is blocked until that token-accounting discrepancy is resolved, and no absolute dollar claim beyond the first-party prices in `config/gateway.yaml` is made. | This row; `reports/cost_report.md` (three explicit NOT COMPUTED verdicts); the README claims row for cascade saving; `eval/cost_simulation.py` |
| **SL-9** | **The two-plane OVLP-01 demo moment is CUT from the demo path to roadmap** — one sentence carrying a hallucination *and* a privacy signal, routed three ways by policy alone, does not fire reliably enough to stand in front of judges. | Measured 2026-08-30, quiet host, **10 repetitions × 3 policies**, verdicts read from the **audit record** via `canonical_view` (not the HTTP body — the streaming policies deliver SSE, so a `.json()` read reports `nonjson` and would have published a false 0/10). `support_bot` → `edit` **10/10** ✓ · `hr_copilot` → `block` **10/10** ✓ · `finance_advisor` → `pass` **10/10** where OVLP-01 expects `escalate` ✗. Both labels (`hallucination.ungrounded_claim` + `privacy.person`) present 10/10 on the two streaming policies, **absent** on UC-3. | **The demo never rests on an unreliable beat** (owner ruling, 2026-08-30): the 10× gate was set in advance and 2 of 3 policies is not 10/10, so **beat 4 stays on PII-001**, which is the beat that has always passed. What is lost is a *presentation* of the multi-label thesis, not the capability — `support_bot` vs `hr_copilot` still routes the identical response two different ways from config alone, which is the thesis itself, and beat 4 shows it on PII-001. **The UC-3 zero-signal `pass` is undiagnosed**: it runs at `Stage.OUTPUT_FULL`, all six live detectors appear in `detectors.ran`, and no detector reported a failure — so nothing was skipped and nothing errored, yet no signal was emitted. Recorded as owed diagnosis rather than guessed at. | This row; the beat-4 selection in `docs/07-demo-script.md`; `dashboard/static/chat.html` ships the OVLP-01 preset, so the moment is reachable live in the console for anyone who asks — it simply is not scripted |

### Prose-fix log — ADR-026 Amendment 2 clause (d)

Every post-measurement presentation-prose correction, logged on use. Amendment 2 requires the log
precisely so that uses **accumulate visibly**: a register with several entries is itself evidence
that report prose is being written carelessly, and the cheap path stays "get the prose right
before measuring".

| # | Date | What was corrected | Figure-identity proof | Verified |
|---|---|---|---|---|
| 1 | 2026-08-26 | `eval/run_all.py` `numeric_claims` note claimed a **Q-18 publication gate that ADR-025 had already lifted** — stale prose sitting directly above the figures it disclaimed | `reports/eval_report_prose_fix.diff` — **PROVEN**: 3 of 151 lines differ (run timestamp; `Code commit` stamp, which 06 §8 *requires* to change; the note itself). 276 numeric tokens on the 93 measurement-bearing lines identical in sequence; normalized SHA-256 identical; all 5 metric rows byte-identical; all 6 measurement inputs identical | **VERIFIED** 2026-08-26 (clause (c)) — `reviews/phase2-review.md` § *Publication-gate ruling* (committed as `554e0d0`, "review: record checkpoint 2 re-review"): the reviewer regenerated both reports independently from the archived source states `7c8261d` and `fbcfcf593552` and found **all 32 measurement/result rows byte-identical**, with no numeric delta. Clause (c) is satisfied because that is a second party's **reproduction from source**, not the executor's own identity check on its own artifact |

Note recorded against entry 1: the first identity check was written over *every* digit in the file
and **failed** — first divergence `18 → 04`, which is `Q-18` becoming `04 §2.4.2` inside the
rewritten sentence. The check was comparing document cross-references as if they were
measurements; its scope was wrong, not the artifact. The failure is disclosed in the proof itself
rather than dropped, because a check narrowed *after* it fails must show its working or the
narrowing is indistinguishable from evading it.
---

## Deferred scope (phase assignment)

**Purpose.** What is *planned but not yet built*, and which phase owns it. This is a third
register, distinct from the two above it: an **open question** is undecided, a **Standing
Limitation** is decided-and-permanently-unmet, and a deferred item is decided, understood, and
simply not reached yet. Without it, "not implemented" and "not required" are indistinguishable
from outside the code — and the whole point of AGENTS.md §7 is that a reader can tell coverage
from the absence of coverage.

**Amended 2026-08-27** (ruling, no ADR — no contract changes): `fast_consistency` and
`rag_grounding` move to **Phase 5** (the detector ML stack) alongside the Tier-2 classifiers.
Both were previously carried as if in scope for the gateway spine; neither is. The list now
matches the tree.

**Deferred coverage carries a tripwire test (ratified 2026-08-27).** Where a deferred detector
makes a spec artifact unreachable, the standard is to **assert the limitation** rather than delete
or weaken the case: `tests/test_gateway_app.py::test_ovlp01_is_not_yet_wired` pins that OVLP-01
yields `pass` and emits no signals today, so the moment `rag_grounding` or `entity_enricher` lands
the test fails and names what must be re-pointed. This is what keeps a deferral self-cancelling —
a deleted case is forgotten, an asserted limitation is not. PII-001 carries 07 beat 4 until then.

| Phase | Item | State in the tree |
|---|---|---|
| **5 — detector ML stack** | `tier2_injection`, `tier2_toxicity` | `detectors/tier2_classifiers.py`, `STUB(phase-1-scaffold, Q-04 deferred)`; checkpoints unpicked (Q-04) |
| **5 — detector ML stack** | `fast_consistency` | `detectors/consistency.py`, 7-line stub. Needs a second sample at temperature + embedding cosine (04 §2.3, ADR-014) |
| **5 — detector ML stack** | `rag_grounding` | **no module at all.** Needs sentence-vs-context embeddings (04 §2) |
| 5 | `entity_enricher` (ADR-011) | **LANDED 2026-08-29.** `detectors/entity_enricher.py` implements 04 §2.2 on spaCy `en_core_web_sm`; called by `pipeline.enrich_lane`, warmed at boot, named in `app._probe_scope()`. Reachable by **no corpus case** until `rag_grounding` lands — see [[M-44]] |
| 6 — cost plane | `cost_budget`, `loop_guard`, cascade probe (ADR-013) | `detectors/cost.py` stub; `sse_proxy` carries no probe **by design**, not stubbed (a probe that silently did nothing would make `cascade_escalated` false for the wrong reason) |
| 6 | `conv_tracker` (FR-GW-005) | `detectors/conversation.py` stub |
| 7 — slow lane | deep audit: `entropy`, `fairness`, `sampler` | three stubs under `deep_audit/` |
| 7 | dashboard (ADR-007) | `dashboard/app.py` absent |

**Measured inventory, re-measured 2026-08-29** — 4 of the 11 detectors declared in
`detectors/base.BUDGETS_MS` expose an instance whose `.name` matches a budget entry and which
has an `async detect`:

| | Detectors |
|---|---|
| **Live (4)** | `tier1_pii`, `tier1_blocklist`, `numeric_claims`, `tier2_injection` |
| **Implemented, but not a `Detector` (1)** | `entity_enricher` — see below |
| **Declared but absent (6)** | `tier2_toxicity`, `fast_consistency`, `rag_grounding`, `cost_budget`, `loop_guard`, `conv_tracker` |

**The third row exists because the definition above cannot express it.** `entity_enricher` is
implemented and runs, but 04 §2.2 makes enrichment its own stage between detection and the
policy engine, so it has no `async detect` **by design** — its entry point is
`enrich(signals, text, ...)`, and giving it a `detect` to satisfy this table's phrasing would be
a type lie. Under the two-row form it therefore filed as "declared but absent": a false
statement about working, tested code, and the *reason* it was false is that a category
definition drawn around one shape silently misfiles anything of another. Logged as [[M-45]].
`tier2_injection` moved for the ordinary reason — it landed and this table was not recounted,
the same staleness [[M-42]] found one file over.

`BUDGETS_MS` is deliberately **not** trimmed to the live four: `register()` refuses a detector
with no budget, so the table is the 04 §2 registry transcribed, and an entry there is a statement
about the spec rather than about today's tree.

**The consequence this creates is a requirement, not a caveat.** `finance_advisor` (UC-3) sets
`consistency: "on"`, so its policy asks for a check that no longer exists in this phase. A record
that listed only the detectors which *ran* would let a reader infer coverage that was never
attempted. Every audit record therefore carries what ran **and** what was expected but did not,
with a reason — see M-10 and 05 §3/§4 `detectors_json`. A registry gap is recorded as *not run*;
that is a different fact from a `DetectorFailureRecord`, which means a detector ran and broke.

## DEVIATION REPORT [D2-detector-params-cannot-hold-list-values]
Severity: MINOR
Doc & section: 04 §2.4.4 (ADR-025's extension point); 04 §3 policy schema `detector_params`
The doc says: ADR-025 makes `numeric_claims`' unit list and citation-marker list "extensible via
`detector_params.units` / `detector_params.citation_markers`".
Reality says: `Policy.detector_params` is typed `dict[str, dict[str, float]]` — a mapping of
detector name to **float** parameters, which is what `tier2_toxicity`'s cutoffs needed. A list of
strings cannot be stored in it, so the extension point ADR-025 describes does not exist yet.
`DetectorContext.params_for()` returns `dict[str, float]` for the same reason.
Impact if we ignore it: none immediately — 04 §2.4 carries the normative lists and the detector
reads those, so both detectors are fully implementable and no number is affected. The cost is that
a documented capability is not real, which is the kind of gap that gets discovered by whoever
first tries to use it.
Options:
  A) Widen to `dict[str, dict[str, float | list[str]]]` and have `params_for` return the union.
     Trade-off: every consumer must narrow the type; touches the detector contract in base.py.
  B) Add a separate `detector_lists: dict[str, list[str]]` field. Trade-off: two override
     mechanisms keyed by detector name, and a reader must know which one holds what.
  C) Drop the extension-point sentence from ADR-025 and keep 04 §2.4 as the only source.
     Trade-off: loses per-use-case tuning that a regulated UC might genuinely want (its own
     filing vocabulary as citation markers).
Recommendation: **A** — one mechanism, and the narrowing is local to the two detectors that read
lists. Not applied, because widening a core schema type to satisfy a doc sentence is exactly the
kind of change that should be ruled rather than assumed.
Blocked work: none. Filed because 04 §2.4.4 now cites this slug, and a slug in doc prose that is
absent from this ledger means the ledger is what is wrong (AGENTS.md §11).

## DEVIATION REPORT [D3-tier1-pii-recall-below-target]
Severity: MAJOR
Doc & section: 01 §2 NFR-EVAL-001 ("Tier-1 PII recall ≥ 0.95"); detector contract 04 §2 row 1
The doc says: Tier-1 PII recall ≥ 0.95 on the labeled set, measured by `eval/run_all.py`.
Reality says: **0.8361** micro recall (51 TP / 61 positive label occurrences) on the frozen
280-case corpus. Precision is **1.000** — zero false positives — so this is purely missed
coverage, not over-firing. 10 misses in two clusters:
  * **8 × `pii.phone`** — the NANP pattern requires a 10-digit form. Missed: 7-digit local
    (`NNN-NNNN`), E.164 with country code, dot-separated, and a parenthesised 7-digit form.
    5 of the 8 are multi-PII cases where the SSN/card/email span WAS caught, so the case is
    partially detected — the verdict would still fire, but per-label recall is short.
  * **2 × `pii.api_key`** — a JWT-shaped bearer token and a generic 32-char hex secret behind
    an `api_key=` assignment. Both fall outside the vendor-prefix rule, which was a
    documented deliberate choice (a generic high-entropy rule would fire on request ids).
Measurement verified before filing: each miss was re-run individually and confirmed to be a
real detector gap, not a harness artifact. `python -m eval.run_all` reproduces it.
Impact if we ignore it: NFR-EVAL-001 is the one detector target with a number attached, and
Tier-1 PII is the FR-DET-001 core. A 0.836 recall published against a 0.95 target is a missed
target; publishing 0.836 while *claiming* 0.95 would be fabrication (AGENTS.md §7).
Options:
  A) **Extend the patterns from the spec, not from these cases** — add 7-digit local and
     E.164 phone forms and a bounded generic-secret rule, derived from published format
     definitions, then re-measure. Trade-off: 7-digit runs and high-entropy strings are
     exactly `clean.jsonl`'s FP pressure, so precision (now a perfect 1.000) will drop. The
     honest version of this option accepts a precision cost and reports both numbers.
  B) **Accept 0.836 and report it as a missed target** with the cluster analysis above.
     Trade-off: the headline detector misses the stated bar, which a skeptical judge will
     read as the prototype's weakest claim — but it is defensible and true.
  C) Narrow NFR-EVAL-001's scope to the categories the vendor-prefix/10-digit rules cover.
     Trade-off: **rejected as target-gaming** — redefining the metric to match the result is
     precisely what AGENTS.md §7 forbids. Listed only to record that it was considered.
Recommendation: **A**, then re-measure and report whatever comes out, because the misses are
genuine format coverage rather than a threshold to tune — but it MUST be done from format
specifications with new tests authored independently, and I should not do it having now read
these case notes. If you'd rather protect the independence of the measurement entirely, B is
the honest fallback.
Blocked work: any publication of a Tier-1 PII recall number (README row, proposal, video).

## DEVIATION REPORT [D8-numeric-claims-treats-identifiers-as-statistics]
Severity: MAJOR
Doc & section: 04 §2 `numeric_claims` row — "currency/percent/large-number patterns with no
citation marker and no match in provided context"
The doc says: fire `hallucination.unsourced_numeric` on a large-number pattern that carries no
citation and no context match.
Reality says: implemented faithfully, that clause yields **precision 0.267** — 33 false
positives against 12 true positives. **30 of the 33 are `PII-*` cases.** The cause is
structural, not a tuning miss: an SSN, a credit-card number and a phone number are all runs of
digits, so the "large-number" clause classifies **identifiers as statistics**. Recall is 0.750,
so the clause works on real figures; it simply also fires on every identifier in the corpus.
Impact if we ignore it: a 0.267-precision detector mapped to **ESCALATE on UC-3** (01 §3) would
quarantine roughly three responses for every one that warranted it — the demo's escalation beat
becomes noise, and the eval report carries a number that invites exactly the skepticism 06 was
written to withstand. It also silently double-flags every PII case on the performance plane.
Options:
  A) **Exclude identifier-shaped runs in the detector** — suppress a large-number match whose
     span is inside, or adjacent to, a Tier-1 PII match. Trade-off: couples two detectors that
     04 §1 keeps independent, and detectors do not see each other's signals; it would need the
     engine to mediate, which is a real design change.
  B) **Narrow the "large-number" clause to quantity-shaped numerals** — require a magnitude
     word, thousands separators, or a unit/currency/percent context, and drop the bare
     "4+ consecutive digits" rule. Trade-off: loses bare statistics like "we processed 15000
     requests"; recall on genuinely unsourced bare integers drops. This is a **spec amendment**
     to the 04 §2 wording, not just a code change.
  C) Accept and report 0.267 with the cause stated. Trade-off: honest, but ships a detector
     whose ESCALATE mapping is not defensible on UC-3.
Recommendation: **B** — the clause's *purpose* is unsourced statistics, and an identifier is
not a statistic under any reading; the bare-digit-run rule is the part that overreaches. It
needs a doc change to 04 §2 rather than a quiet code edit, which is why it is here and not
already applied. Note this interacts with **Q-18**: both shape the same precision figure.
Blocked work: any `numeric_claims` precision/F1 number, and the UC-3 escalation demo beat's
credibility.

---

## DEVIATION REPORT [D1-citation-marker-per-matches-the-rate-preposition]
Severity: BLOCKER
Doc & section: 04 §2.4.2 (citation-marker list, closing Q-18); ADR-025
The doc says: the citation-marker list includes the attribution phrase `"per "` — quoted with a
trailing space, alongside `"as per"`, `"according to"`, `"reported by"`.
Reality says: `per` in English is overwhelmingly the **rate** preposition, not an attribution.
Implemented literally, the marker suppresses every rate-shaped quantity:

| sentence | v2 signal |
|---|---|
| `Cost is $4 million per year.` | **none** |
| `Latency was 250 ms per request.` | **none** |
| `Throughput hit 22% per node.` | **none** |
| `We store 4 TB per tenant.` | **none** |

Measured corpus exposure on the current freeze: 6 cases contain a rate `per`, of which **2 are
labelled `unsourced_numeric` — HAL-049 (`per day`) and HAL-052 (`per employee`) — and both are
suppressed**, i.e. two guaranteed false negatives.

This is not an implementation choice I can narrow away. v1 scoped the same clause as
`\bper\ (?:the|our|your|section|clause|§)\b` — attribution only — and ADR-025 replaced it with
the bare token. There is no reading of a literal `"per "` that excludes `per year`.
Impact if we ignore it: rate-expressed figures are the shape financial and performance claims
most often take, and this is the detector whose UC-3 mapping is **ESCALATE** — so the miss lands
on the highest-stakes path. Worse, ADR-026 §5 permits **one** re-measurement and forbids
adjusting anything afterwards, so measuring now makes the two known misses permanent and
unrevisable.
Options:
  A) Re-scope the marker to attribution contexts, e.g. `per (?:the|our|your|section|clause|§|
     annex|exhibit|filing)` — v1's shape, which is the precedent. Trade-off: `per Smith 2024`
     and other bare-noun attributions are missed, raising firing on genuinely-cited figures.
     Direction is safe: it can only *raise* the firing rate, never hide an unsourced number.
  B) Drop `per` from the list entirely and rely on `as per`, which is unambiguously
     attributive. Trade-off: `per the filing` stops being a marker; strictly more firing than A.
  C) Keep the list literally as ruled and accept the two misses. Trade-off: a documented,
     spec-mandated false negative on the ESCALATE path, permanently baked into the v2 number.
Recommendation: **A** — it restores the clause to the only sense in which it is an attribution,
matches the v1 precedent so the two columns stay comparable in kind, and its error direction is
the safe one. Not applied: the list is normative in a ruled ADR, and editing it is a ruling.
Blocked work: the ADR-026 §5 re-measurement, and therefore the closure of **D3 and D8**, the
dual-column report, and the README claims rows that cite it.

## DEVIATION REPORT [D2-nanp-n-constraint-rejects-nothing-as-composed]
Severity: MAJOR
Doc & section: 04 §2.5 (`tier1_pii` v2 pattern set, ADR-026)
The doc says: the NANP `N ∈ [2-9]` constraint on the first digit of the area code and exchange
"is a **spec-justified narrowing that also protects precision** — … it happens to reject the
digit runs that would otherwise false-positive."
Reality says: it rejects nothing in the composed detector. v1's `_PHONE`
(`(?:\(\d{3}\)|\b\d{3})[-.\s]?\d{3}[-.\s]?\d{4}`) is **retained** and runs **first** in
`_PII_PATTERNS`, matching the same extent, so longest-match-wins hands it the span:

    (115) 555-0123  -> fires (via _PHONE)      NPA starts with 1 — invalid NANP
    (015) 555-0123  -> fires (via _PHONE)      NPA starts with 0 — invalid NANP
    (415) 155-0123  -> fires (via _PHONE)      NXX starts with 1 — invalid NANP
    415.055.0123    -> fires (via _PHONE)      NXX starts with 0 — invalid NANP

A second measured consequence, worth stating because it changes what the v2 column will show:
`_PHONE` already matched both the parenthesized and dot-separated 10-digit forms, so the two new
NANP rows add **no recall at all**. The v2 phone gain comes from **E.164 alone**, plus the
`( 415 ) 555-0123` spaced-parenthesis variant.
Impact if we ignore it: a precision claim in a contract doc that the code cannot support. It does
not block the re-measurement — recall can only rise — but it means the doc describes a
discrimination the detector does not make.
Options:
  A) Narrow `_PHONE` to `[2-9]` on both groups, making v1's rule NANP-conformant. Trade-off:
     changes v1-derived behaviour, so the v1 precision-1.000 baseline no longer describes the
     shipped code — exactly what ADR-026's permanence rule exists to prevent.
  B) Retire `_PHONE` in v2 in favour of the three spec-derived rows. Trade-off: same permanence
     objection, larger; also drops the bare `\b\d{3}` 10-digit form, which is real coverage.
  C) Amend 04 §2.5 to drop the precision sentence, keeping `[2-9]` as spec conformance only.
     Trade-off: the constraint stays inert — honest, but it earns nothing.
Recommendation: **C** — the constraint is genuinely in the NANP definition and belongs in a
spec-derived pattern; the false part is the precision claim, not the pattern. A is defensible in
a later freeze cycle but must not ride along with a measurement.
Blocked work: none. `tests/test_tier1_detectors.py::test_nanp_n_constraint_rejects_leading_0_and_1`
asserts the constraint at the **pattern** level, where it is real, and records the shadowing in
its docstring rather than pre-judging this ruling.

## DEVIATION REPORT [D2-adr-026-eyj-derivation-is-arithmetically-wrong]
Severity: MINOR
Doc & section: ADR-026 §2 (JWT pattern justification); 04 §2.5 JWT row
The doc says: anchoring on `eyJ` is permitted and spec-derived because "it is the base64url
encoding of `{\"`, the mandatory start of every JOSE header — that written justification is what
makes it auditable as non-fixture-shaped."
Reality says: `base64url({\") == "eyI="`, not `"eyJ"`. Base64 packs three input bytes into four
output characters, so two bytes cannot determine the third character. The third character is

    ((0x22 & 0x0F) << 2) | (next_byte >> 6)  =  8 | (next_byte >> 6)

and base64 index 9 is `J`, so the anchor holds exactly when `next_byte >> 6 == 1` — i.e. the
byte after `"` is in `0x40`–`0x7F`, which every ASCII letter is. RFC 7515 §4 makes the header a
JSON object and every registered parameter name (`alg`, `typ`, `kid`, `crit`, …) begins with a
letter, so the anchor does hold for every conforming header whose first member is a registered
parameter. **The ADR's conclusion is correct; only its stated derivation is wrong.**
It also exposes one real bound the ADR's version hides: JSON permits whitespace after `{`, and
`base64url({ \"alg\") == "eyIg…"` — no anchor. A pretty-printed JOSE header is missed.
Impact if we ignore it: the pattern is fine and no number moves. The cost is specific to
ADR-026's own purpose — the written justification is what makes the anchor auditable rather than
fixture-shaped, and an auditor who checks the arithmetic finds it false, which discredits a
correct decision.
Options:
  A) Amend ADR-026's justification to the true derivation and record the whitespace bound.
     Trade-off: none beyond editing a ruled ADR, which requires this ruling.
  B) Leave it and rely on the test docstring, which already carries the correct derivation.
     Trade-off: the ADR — the auditable artifact — stays wrong.
Recommendation: **A**.
Blocked work: none. `test_rfc_7515_eyj_anchor_is_a_property_of_the_format` asserts the ADR's
literal claim **as false**, asserts the true condition across nine registered header parameters,
and asserts the whitespace bound, so the correction is executable rather than only prose.

## DEVIATION REPORT [D5-detector-failure-signal-is-unconstructible]
Severity: MAJOR
Doc & section: 04 §5 "Failure semantics (fail-open / fail-closed) — FR-POL-006", against 04 §1.1 (label taxonomy) and 05 §3/§4 (`signals_json`)
The doc says: on `DetectorTimeout`/`DetectorError` "the gateway **synthesizes**: `labels: ["_meta.detector_failure"], meta: {detector, error_class}`", and fail_closed means "**synthesized signal** maps to ESCALATE". `controlplane/detectors/base.py` calls it "a synthesized `_meta.detector_failure` signal" in the same terms.
Reality says: that object cannot be constructed. `_meta.detector_failure` is not in `TAXONOMY`, and `Signal._check_labels_in_taxonomy` rejects it — verified: `Signal(...labels=["_meta.detector_failure"]...)` raises `1 validation error for Signal`. The two rules are individually correct and jointly unsatisfiable: 04 §1.1 is a **closed** taxonomy of *content risks*, and a detector fault is not a content risk, so the label has nowhere legitimate to live in it.
Impact if we ignore it: three concrete consequences, not one aesthetic one. (1) 05 §3 `signals_json` is documented as `list[Signal]`, so a failure that is not a `Signal` has no defined place in the audit record — yet 04 §5 requires the fault to be visible to a human. (2) Anything reading `signals_json` to count risks would have to special-case a pseudo-label, or a `_meta.*` entry would be counted as a detected risk and inflate `cp_pii_intercepts_total`-style aggregates. (3) The fail_closed path is FR-POL-006 and SC-3 — a demo beat — so leaving the representation undecided leaves a demo artifact undecided.
Options:
  A) Add `_meta.detector_failure` to the taxonomy as an explicitly non-content namespace — trade-off: makes the doc literally true and `signals_json` uniform, but punctures the "taxonomy = content risks" invariant, and every consumer must now exclude `_meta.*` or over-count. The invariant is load-bearing in 04 §1.1 and in the detector tests.
  B) Keep faults off the `Signal` type (what ships today: `DetectorFailureRecord`, a frozen dataclass resolved by `resolve_failure`) and amend 04 §5 to describe a **failure record** rather than a synthesized signal, with its own audit field — trade-off: one more field in the audit schema (05 §3/§4), and 04 §5's wording plus the `base.py` docstring must change. Keeps the taxonomy clean and makes miscounting structurally impossible rather than merely discouraged.
  C) Represent the fault as a `Signal` carrying a real label from the affected detector's own scope — trade-off: rejected on sight; it would be indistinguishable from a genuine detection and is the one option that could produce a fabricated risk figure.
Recommendation: **B** — the taxonomy's closure is what makes label-derived counts trustworthy, and a fault is a different kind of fact from a finding; the cost is a schema field and two sentences of doc, which is cheaper than teaching every consumer to filter a pseudo-label.
Blocked work: nothing is blocked *today* — `evaluate()`/`resolve_failure()` implement 04 §5's **semantics** correctly (fail_open proceeds and is recorded; fail_closed escalates and never silently blocks; both unit-tested, including the never-BLOCK guarantee swept across every policy × detector × error class). What waits on the ruling is the **audit representation**: the gateway's `signals_json`/`actions_json` write path for detector faults, and the 06 §5 fault-injection harness that will read it back.

## DEVIATION REPORT [D1-usage-canary-has-no-independent-count-on-the-measured-class]
Severity: BLOCKER
Doc & section: 01 §1 FR-GW-006; 05 §6.1 `usage_sanity`; ADR-018 (Context)
The doc says: at boot, one canary request "compares `count_tokens` against the provider's
reported prompt-token count. Delta > `usage_sanity.max_token_delta` (default 25) ⇒ the
provider's accounting is untrustworthy: **measured-class fails boot**, **dev-class warns
loudly and continues**."
Reality says: `count_tokens` is **not repo code** — it appears nowhere in the tree, and no
tokenizer is declared in `pyproject.toml` (02 §8's dependency list does not name one). It is a
**provider endpoint** (Anthropic-shaped `POST /v1/messages/count_tokens`), which is where
ADR-018's `14 / 75 / 5074` figures came from. Keyless existence probes — **no credential sent**,
so 401/403 = "exists, auth-gated" and 404 = absent — run 2026-08-26:

| provider | class | probe | result |
|---|---|---|---|
| `kiro-local` | dev | `POST /v1/messages/count_tokens` | **401 — EXISTS** |
| `groq` | measured | `POST /v1/messages/count_tokens` | **404 — ABSENT** |
| `groq` | measured | `POST /v1/tokenize` | 404 — ABSENT |
| `groq` | measured | `POST /v1/messages/count_tokens` (Anthropic path) | 404 — ABSENT |
| `groq` | measured | `GET /v1/models` *(control)* | 401 — host reachable, auth-gated paths do answer |

The control row is what makes the 404s meaningful rather than a network artifact. So the
independent count this invariant compares against exists **only on the class whose consequence
is a warning**, and is **absent on the class whose consequence is boot refusal**. The mechanism
is implementable exactly where it does not matter and unimplementable where it does.
Impact if we ignore it: the boot-time guard protecting every judge-facing number (AGENTS.md §7)
degrades to a no-op on the measured class, so the ~5000-token-offset class of bug ADR-018
documents would reach a report unchallenged. A canary that always passes **because it cannot
run** is worse than an absent one — it reads as a green check.
Options:
  A) Local tokenizer as the independent source (new dep — `tokenizers`/`transformers` plus the
     Llama tokenizer; **ADR note required per 02 §8**) — trade-off: a local tokenizer does not
     model Groq's server-side chat template, so its systematic error competes directly with
     `max_token_delta: 25`. Too tight and a measured-class provider is refused boot over a
     template mismatch; too loose and it stops being a check. The error budget is unquantified
     until measured, so the threshold has no meaning yet.
  B) Redefine the invariant as a **provider-internal self-consistency** check: one identical
     canary prompt sent twice, streaming and non-streaming, comparing the provider's *own*
     reported `prompt_tokens`. Needs no external count and works on every provider — and it is
     precisely the comparison that would have caught ADR-018's bug (75 streaming vs 5074
     non-streaming, delta 4999 ≫ 25 ⇒ dev-class warn, exactly FR-GW-006's specified behaviour).
     Trade-off: a different invariant from the one 01 §1 states, so FR-GW-006 and 05 §6.1 change;
     it cannot catch an error that is *consistent* across both paths.
  C) Scope FR-GW-006 to providers exposing a token-count endpoint, and make its absence on a
     measured-class provider a loud boot **WARNING** naming the provider — trade-off: honest and
     cheap, but the measured path keeps no automated guard; the protection becomes a Standing
     Limitation rather than a mechanism.
Recommendation: **B.** It adds no dependency, applies uniformly to both classes, and is the only
option demonstrated to catch the exact failure the requirement was written in response to — on
the two shipped providers it yields the right verdict in both directions (kiro-local warns, a
consistent provider passes). A's error budget could refuse to boot the measured path, which is
the one path that produces publishable numbers; C removes the guard precisely where it matters.
Blocked work: Phase 4 item 5's **canary half only** — provider dispatch itself is unaffected, and
items 2/3/9 proceed against the stub upstream the latency benchmark needs regardless.

---

## Resolved
*(move items here with the ruling + date + ADR link)*

**Q-18 — What counts as a "citation marker" for `numeric_claims`?** — RESOLVED 2026-08-26 by **ADR-025**.
Ruling: **(c)** — written into 04 §2.4.2 as normative, so it is no longer an implementation detail. Lexical only, searched in the numeral's own sentence, case-insensitive: attribution phrases · bracketed numeric reference · parenthetical author-year · URL. Judging whether a citation *supports* the figure stays `rag_grounding`'s job.
**The ruled list is not the provisional one, and the delta moves the FP rate in both directions** — recorded because it is the reason the v2 `numeric_claims` precision is not comparable to v1's on the citation clause alone:
- **Dropped** (stop suppressing → can only raise FP): bracketed author-year `[Smith 2024]`; structural pointers (`section 4`, `clause 12`, `§ 4`, `table 3`); named regulatory documents (`10-K`, `prospectus`, `filing`); the `ref:` / `reference:` / `see:` leaders; `as stated/noted in`.
- **Added** (start suppressing → can only lower FP): `as per`, `cited by`, `based on`, `study by`, `survey by`, `data from`, `figures from`.
The publication gate this question carried is **lifted**: a `numeric_claims` FP/FN figure may now be published, provided it is labelled v1 or v2 per 06 §3.2.

⚠ A marker is **not** a verification. It suppresses only this detector, whose question is "was this figure attributed?" — never "is the attribution true?", which is `rag_grounding`'s independent question. The two are *meant* to disagree on a plausible citation for a figure the context never states; 06 keeps that pair as a control and `test_a_citation_is_not_a_verification` pins it.

*Housekeeping, 2026-08-26:* the caveat above and a `Status: **OPEN**` deadline line reading "before any `numeric_claims` number reaches a report, the README…" were left stranded under **Q-10**'s heading when this question moved to *Resolved*. That line asserted the very gate ADR-025 lifted — the **same stale-gate defect** as `[D2-report-emits-a-q18-publication-gate-adr-025-lifted]`, from the same root cause (a question moved; its dependents did not), in a second file. It is removed under that deviation's ruling rather than filed again, and the caveat it was stranded with is **relocated here, not deleted** — it is unique in the repo and `tests/test_numeric_claims.py::test_a_citation_is_not_a_verification` pins it. Amendment 2's proof machinery is not engaged: this is a markdown doc read by no code, so it cannot move a figure.

**Q-17 — 04 §2 names "Aho-Corasick keyword sets"; the implementation uses a compiled regex alternation.** — RESOLVED 2026-08-26 (MINOR gap, AGENTS.md §6; agent-resolved).
Why: `pyahocorasick` is not a declared dependency, and the documented term source (`blocklist_extra`) ships **empty** in all three policies — so the structure would be carrying zero terms.
Ruling: **compiled regex alternation, sorted longest-first.** The doc names a data structure in a Notes column; the *requirement* is the <2 ms NFR-P-002 budget, and the semantics (leftmost-longest over a fixed term set, word-boundary anchored) are identical at this size. `_compile_terms` is the single seam to swap.
⚠ Offered rather than assumed: if the data structure is considered **normative**, this is a D2 and I will swap the implementation — it is one function, and no other code depends on the choice.

**Q-16 — Who detects `pii.person_data`?** — RESOLVED 2026-08-26 (MINOR gap, AGENTS.md §6; agent-resolved).
Why: the label is in the 04 §1.1 taxonomy and **no 04 §2 row says how to detect it.** It is a category ("employee record", "date of birth"), not a shape a Tier-1 pattern can match.
Ruling: **`tier1_pii` never emits it.** It also has **zero cases in the frozen corpus**, so the omission leaves nothing unmeasured; the label stays in the taxonomy for the policy files that already map it. If it should ever fire, that needs a documented detector row first (doc change), not a regex invented here.

**Q-15 — What is `tier1_blocklist`'s base term list?** — RESOLVED 2026-08-26 (MINOR gap, AGENTS.md §6; agent-resolved).
Why: 04 §2 describes `blocklist_extra` as "per-use-case **extra** terms", wording that implies a base list the docs specify **nowhere**.
Ruling: **there is no base list; `blocklist_extra` is the only term source.** All three shipped policies set it to `[]`, so the detector correctly emits nothing on the documented configuration — wired, budgeted and tested, with no terms to match. Inventing a base list would be writing policy into Python, the AGENTS.md §9.1 trap.
⚠ **Reporting consequence, stated rather than buried:** `security.blocklist` therefore has **zero positives** in the frozen corpus, so this detector's recall is **undefined — not 1.0**. `eval/run_all.py` must report it as no-cases; an empty denominator rendering as a perfect score would be a fabricated number (AGENTS.md §7).

**Q-14 — What does a detector receive as `ctx`?** — RESOLVED 2026-08-26 (MINOR gap, AGENTS.md §6; agent-resolved).
Why: 04 §2 fixes the contract as `async detect(ctx) -> list[Signal]` and **never says what `ctx` holds**, so no detector could be written against it.
Ruling: `DetectorContext` in `detectors/base.py`, containing only what the *documented* rows require — `text` + `stage` (every row), `context_docs` (`rag_grounding`, `numeric_claims`; source `controlplane.context` per 05 §1.1), `conversation_id` (`loop_guard`, `conv_tracker`), and the two policy fields 04 §2/§3 hand to a detector (`blocklist_extra`, `detector_params`).
⚠ Not a 05 addition: 05 governs endpoints, persisted schemas, config keys, metrics and log fields. `DetectorContext` is an internal call shape, none of those.
⚠ Load-bearing detail: **policy values arrive as plain data, never a `Policy` object.** base.py's stated asymmetry is that nothing there reads a policy, and it is what keeps FR-POL-002 true — a detector that could see the label→action map could start deciding actions. The engine projects the two documented fields in, and the detector stays unable to tell which use case it is serving (AGENTS.md §9.1).


**Q-13 — Does the ADR-022 hard-boot-failure rule apply to a `dev`-class provider?** — RESOLVED 2026-08-25 (MINOR gap, AGENTS.md §6; agent-resolved).
Why: 05 §6.1's table said "model missing at boot **and** named in `tiers` ⇒ hard boot failure" without naming a class. Read literally that refuses to boot the shipped `active_provider: kiro-local`, which is `dev`-class with `pricing: null` and both tiers bound — i.e. the documented development path would not start.
Ruling: **both boot rows are measured-class only.** The fatal row refines the `measured` warning row directly above it, and ADR-018 exists precisely so a dev-class provider is usable *while* unpriceable — its numbers are barred from every judge-facing artifact anyway, so bricking that path protects a report it can never produce. For a `measured` provider the reasoning inverts and the failure stays fatal: its data may carry judge-facing numbers, so an unpriced model on a routing path will answer real requests and mint uncostable audit records.
Applied to: 05 §6.1 (scope paragraph added), `GatewayConfig._check_price_coverage`, and `test_dev_class_provider_may_boot_unpriced_on_a_routing_path` — which pins the decision so a later "tighten the guard" edit fails loudly rather than silently breaking `make run`.

**Q-12 — What is the dataset freeze gate, concretely?** — RESOLVED 2026-08-25 (MINOR gap, AGENTS.md §6; agent-resolved).
Why: 06 §2 required labels to be reviewed and frozen but named no command, so "frozen" had no mechanical meaning and nothing could fail.
Ruling: `python -m eval.validate_dataset` is the gate, named in 06 §2.4. It checks the §2.1 format, the 04 §1.1 closed taxonomy, `action_expected` key sets, the ADR-023 causal fields, synthetic-safety construction (never-assigned SSN ranges, Luhn, RFC 2606, the 555-01xx block), and — the substantive part — **re-derives every expected action** from ground truth + the loaded policy and compares. It validates **consistency, not label correctness**; label judgement stays with the second-teammate review (06 §1) and its open items live in `eval/dataset/REVIEW_NEEDED.md`.
⚠ Scope note: the derivation is deliberately independent of `policy/engine.py` (still a stub). When the engine lands, the two must agree — and the gate is the artifact that will notice if they don't.

**Q-02 — Upstream provider choice** — RESOLVED 2026-08-24, **RE-RESOLVED 2026-08-25 (ADR-018)**. The fallback half is **reopened as Q-10**.
Ruling (current): provider set is classed by provenance, not picked as a single winner — **`measured` = {`groq`, `ollama-local`}**, **`dev` = {`kiro-local`}**; `active_provider: kiro-local` for development. Both Groq ids were verified first-party as *production* models (`llama-3.1-8b-instant` small, `llama-3.3-70b-versatile` frontier). Written to `config/gateway.yaml` per the amended 05 §6.1 schema.
Supersedes the 2026-08-24 ruling (upstream = Anthropic API / `claude-sonnet-4-6`), which is now moot — including its ⚠ note about that id not matching Anthropic's published naming. That concern was well-founded and the same class of failure is now caught at boot rather than by inspection: FR-GW-006's canary refuses a measured-class boot whose reported token accounting disagrees grossly with a **repo-local estimate** (ADR-028 — the earlier `count_tokens` / `max_token_delta` form of this sentence named a mechanism that ruling withdrew).
⚠ Price provenance remains the weak link, not the ids. The schema half is now fixed — ADR-022 keys prices by concrete model id, so the two-tier cascade is expressible and `[D2-price-table-cannot-express-per-tier-cost]` is CLOSED. The *provenance* half is not, and re-checking live on 2026-08-25 made it worse rather than better: `groq.com/pricing` 308-redirects to a homepage carrying no price content, `console.groq.com/docs/pricing` 404s, `console.groq.com/settings/billing` is authenticated with no public table, and the per-model doc pages contain zero dollar figures. **No first-party Groq price table is reachable at all**, so every figure in `config/gateway.yaml` rests on secondary aggregators plus a stale December-2024 blog post. ADR-022's `source_url`/`retrieved` fields now carry that admission in the config itself rather than in a comment. Consequence for AGENTS.md §7: the 06 §6 cost simulation may publish a **relative** delta (which survives a proportional error in both tiers) but **not an absolute dollar figure** until a first-party table exists.

**Q-11 — Multi-turn case encoding in `eval/dataset/conversation.jsonl`** — RESOLVED 2026-08-25 (MINOR gap, AGENTS.md §6; agent-resolved, obvious low-risk answer).
Why: 06 §2 specifies a case format with a single `text` string, but also specifies a file of "multi-turn sequences" (SC-4 / FR-DET-006). The format has no field for turns, and 06 §2's example shows only `"kind":"output"` without enumerating the legal values.
Ruling: encode turns as `"user: …\nassistant: …"` lines **inside** `text`, and use `kind: "conversation"` — a value borrowed from 04 §1's `stage` vocabulary, where `conversation` is already a documented stage. Chosen over adding a `turns` field because a new field is an undocumented schema change and the prefix convention needs no format edit; chosen over reusing `kind:"output"` because the conversation stage is genuinely distinct and `conv_tracker` is stage-scoped.
Consequence: `kind` now has three observed values (`input`, `output`, `conversation`). If a future validator or loader enumerates them, it must accept all three.
✓ The two related items flagged here as **not** MINOR are now both ruled, and both dataset coverage gaps are closed: `[D4-enriched-label-survival-semantics]` → **ADR-019**, unblocking `OVLP-11…15` (in-band, person-bearing); `[D4-input-stage-pii-edit-unresolvable]` → **ADR-020**, unblocking `PII-048…053` (input-stage, all five categories). See the deviation ledger below.

**Q-09 — YAML 1.1 boolean coercion of `consistency` / `cascade_probe`** — RESOLVED 2026-08-24 (MINOR gap, AGENTS.md §6; agent-resolved, obvious low-risk answer).
Why: PyYAML implements YAML 1.1, where bare `on`/`off`/`yes`/`no` resolve to **booleans**. Both fields are string enums whose members are literally `on`/`off` (04 §3, ADR-013, ADR-014), so the spec's own example — `cascade_probe: off` — loads as `False` and fails validation. Found when all three policies failed to load.
Ruling: the intended vocabulary is unambiguous across three docs, so only the quoting was wrong. Values are now quoted in all three policy files **and in the 04 §3 example** (which is the template people copy). `streaming` is a genuine boolean and stays unquoted. `policy/schema.py` raises a targeted error naming the trap instead of a bare enum mismatch (FR-CFG-001 "precise error").
No behavioural change; no ADR needed.

**Q-03 — Dashboard tech** — RESOLVED 2026-08-24. Ruling: **Streamlit**. ADR-007 flipped Proposed → Accepted; `streamlit` recorded as an optional `dashboard` extra in `pyproject.toml`.

**Q-04 — Tier-2 model picks (injection + toxicity classifiers)** — **CLOSED 2026-08-28 by ADR-031.**
Original ruling (2026-08-24): **defer the checkpoint choice**; stub the detector interfaces now (`detectors/tier2_classifiers.py`), pick real checkpoints later via the NFR-P-002 latency spike.
Ruling: **`madhurjindal/Jailbreak-Detector`** (injection) and **`martin-ha/toxic-comment-model`** (toxicity), both served on **ONNX Runtime with dynamic int8**. Six published candidates measured by `eval/spike_tier2_models.py` across three backends × five stage-reachable lengths × two thread settings; **selection on latency only**, no corpus label ever read, because picking a model by its score on the frozen fixtures that later measure it is harness-fitting. Eager PyTorch misses the budget for every candidate at the segmenter cap — **not a D3**, since 02 §8 and 04 §2 both specify ONNX and eager was never the documented backend. `protectai/deberta-v3-base-prompt-injection-v2` is rejected despite one FITS row: re-probed on the crossover ladder it measured **36.69 ms P99 at the same 240 characters** it passed at in the sweep (61 vs 50 tokens — the two composers build that length differently), and a verdict that flips on tokenizer detail is *at* the budget, not inside it. Full measurements, the population-correctness fix, and the int8 accuracy disclosure are in **ADR-031**.
⚠ Doc-rot note (now discharged): the original Q-04 said to record the eventual choice "as ADR-011", but ADR-011 is already the `privacy.person` producer decision. The spike result took the **next free ADR number** — **ADR-031**.
⚠ **This closure is not the whole story.** The picks satisfy the budget at every length their stages can *deliver*, but the `input` stage applies no length cap, so `tier2_injection` has reachable inputs it cannot serve in 25 ms. Filed as `[D3-tier2-injection-budget-cannot-hold-on-unbounded-input]` — **OPEN** in the ledger below. Thread sensitivity is logged as **SL-5**.

## DEVIATION REPORT [D5-adr-027-stamp-has-no-column-in-the-05-3-ddl]
Severity: BLOCKER
Doc & section: 05 §3 (`audit_records` DDL) vs 05 §4 (canonical view) and 05 §2
(`escalation_cause`); ADR-027 consequences 2 and 3
The doc says: 05 §4's canonical JSON view carries `"contributing_signal_ids": ["…"],
"failure_record_ids": ["…"]` as top-level keys, and 05 §2 states `escalation_cause` is
"**derived, not stored**: it is computed from the referenced `audit_records.detector_failures_json`
and the step-5 stamp (§4 `contributing_signal_ids` / `failure_record_ids`), so there is one source
of truth for why a verdict happened." ADR-027 consequence 2: the stamp extends to "contributing
signal_ids **+ failure_record_ids**, so an ESCALATE with zero content signals is self-explaining
in the audit."
Reality says: **05 §3's own `audit_records` DDL declares neither column** — it ends at
`sampled_deep`, and `db.py` plus `write_record`'s 19-column `INSERT` are faithful to it. The two
fields exist on the `AuditRecord` dataclass and are populated correctly from the verdict
(`records.py:318-319`), then **silently dropped at the write boundary**. Verified by round-trip
on a fresh DB: `PRAGMA table_info(audit_records)` returns 19 columns, neither list among them,
and `canonical_view()` — which reads back via `SELECT * FROM audit_records` — emits neither key,
despite its docstring calling itself "The 05 §4 canonical JSON view". No test asserts either list
survives a write; the existing coverage
(`test_audit_records.py:258-259`, `test_policy_engine.py:889-912`) stops at the in-memory build,
which is why this reached the write path unnoticed.

**Neither list is recoverable by derivation**, so this cannot be closed by computing them at read
time:
- `detector_failures_json` is populated on **fail_open** too (05 §3, "a dropped detector that left
  no trace is indistinguishable from one that ran and found nothing"), so the presence of a
  failure record does not mean it *contributed*. Filtering on `fail_mode_applied` also misreports:
  ADR-027's floor "lifts a PASS or EDIT to ESCALATE but leaves a genuine content BLOCK standing",
  so a fail_closed record can be present without having decided the verdict.
- `contributing_signal_ids` is a strict subset of `signals_json` by design — pinned by
  `test_contributing_signal_ids_name_only_the_deciding_signals` — so it cannot be reconstructed as
  "all signal ids".
- 05 §2 requires `both` to be "reported as `both` rather than collapsed to either side", which is
  exactly the distinction that needs both lists present.
Impact if we ignore it: 05 §2's `escalation_cause` is unimplementable, taking ADR-027
consequence 3 with it — the reviewer sees "a bare quarantine" rather than "detector `tier2_toxicity`
failed under fail_closed", which the doc calls "the difference between a decision they can action
and one they must reverse-engineer". 05 §3's stated rationale ("Without the second list, that
record and a content escalation are indistinguishable after the fact") describes the state the
schema is currently in. Blocks Phase-4 item 7's review-queue listing. Item 8 (fault injection) is
**not** blocked — ADR-027 consequence 4 reads `detector_failures_json`, which is stored.
Options:
  A) Add two `TEXT` columns to 05 §3's DDL (`contributing_signal_ids`, `failure_record_ids`),
     JSON arrays, written by `write_record` and read by `canonical_view` — trade-off: a schema
     change, and the ids also appear inside `signals_json`/`detector_failures_json`, so the columns
     are a denormalized index. Mirrors the existing `*_json` convention and leaves 05 §4 and §2
     exactly as written.
  B) One `stamp_json` column holding both lists as an object — trade-off: fewer columns, but 05 §4
     shows the two keys at top level, so the view assembly gains a remapping step, and a future
     third id list would silently change the column's shape rather than the table's.
  C) Mark contributing signals inline (a `contributed: true` flag inside `signals_json` and
     `detector_failures_json`) and derive both lists at read time — trade-off: no new columns, but
     it edits the two payloads ADR-027 deliberately keeps as "pure Signals" and pure operational
     records, and the flag is a policy conclusion stored inside a detector's output.
Recommendation: **A** — the smallest change that makes §3 consistent with §4 and §2, it needs no
edit to either consumer's documented shape, and it keeps `signals_json` pure per ADR-027. The
duplication is an index, not a second source of truth: both lists are computed by the engine, and
the DDL is the only place they currently go missing.
Blocked work: Phase-4 item 7's `GET /admin/review?status=pending` (`escalation_cause` +
`failure_summary`). The audit write path itself is unblocked — records write correctly today, minus
the stamp — so items 1, 3, 4 and 6 proceed, and any ESCALATE they record will be missing the stamp
until this is ruled.

## DEVIATION REPORT [D1-tier2-budgets-cannot-coexist-with-nfr-p-001]
Severity: MAJOR
Doc & section: 01 NFR-P-001 (gateway overhead P50 < 40 ms, P99 < 100 ms, streaming pipelines) vs
04 §2 detector registry budgets (`tier2_toxicity` 25 ms at `OUTPUT_SENTENCE`, `tier2_injection`
25 ms at `INPUT`), read together with 06 §4's normative streaming formula.

The doc says: 06 §4 defines streaming `gateway_overhead_ms` as "ingress + input-lane time +
Σ per-sentence hold intervals", a **sum over holds**. 04 §2 budgets each per-sentence detector
individually. NFR-P-001 caps the total at 100 ms P99. Each doc is self-consistent.

Reality says: a per-sentence budget is paid **once per sentence**, so the segment count is a
multiplier on lane cost — and the multiplier is not 1. Measured over the frozen corpus (280
cases, the shipped `Segmentation`): P50 **1** segment, P95 **3**, P99 **6**, max **10**.
Projecting the two unimplemented tier2 detectors at their declared budgets, `rag_grounding`
excluded (no case carries context docs):

| Segments | Sequential (as implemented) | Parallel (02 §4 intent) |
|---|---|---|
| P50 — 1 | 65 ms — under | 50 ms — under |
| P95 — 3 | 133 ms — **breach** | 100 ms — **breach** |
| P99 — 6 | 235 ms — **breach** | 175 ms — **breach** |
| max — 10 | 371 ms — **breach** | 275 ms — **breach** |

It fails under **both** readings, so the finding does not depend on `run_lane` being sequential
today (it is, by the documented measurement decision at `pipeline.py:212`); 02 §4's parallelism
arriving with Tier-2 does not rescue it. The **measured** figures pass with room to spare — the
margin is a derived factor in `reports/latency_report.md`, not repeated here, because a number
copied into doc prose is machine-specific and rots on the next run — which is why this is filed
as a D1 doc-vs-doc contradiction and **not** a D3: there is no observed breach, and reporting a
projection as a measured one would be the fabrication AGENTS.md §7 forbids.

Impact if we ignore it: NFR-P-001 becomes unmeetable the moment FR-DET-002 is satisfied, and the
discovery would land during the tier2 sprint — the point of least schedule slack — rather than
now. The published latency claim would also need withdrawing after the fact, which is worse than
qualifying it in advance.

Options:
  A) Rule NFR-P-001 **per-sentence** rather than per-request, i.e. the hold interval is what the
     budget caps — trade-off: honest to the interception model and to what a user perceives
     (each hold is the delay before *that* sentence appears), but it stops being a whole-request
     guarantee, and a 10-segment response could hold 340 ms in total while every sentence
     "passes".
  B) Keep NFR-P-001 per-request and cut the 04 §2 tier2 budgets to fit the measured P99 segment
     count (~11 ms each at 6 segments) — trade-off: 25 ms was chosen as achievable for a real
     transformer classifier on CPU; 11 ms probably is not, so this risks specifying a detector
     nobody can build, or forcing a smaller model and trading detection accuracy for latency.
  C) Make `run_lane` genuinely parallel by offloading CPU-bound detectors to a thread pool —
     trade-off: helps least of the three (it only closes the sum/max gap, and the parallel column
     above still breaches), adds real complexity to the hot path, and would make each detector's
     recorded `latency_ms` include contention it did not cause.
  D) Scope NFR-P-001 explicitly to the **implemented** detector set and re-baseline it when
     tier2 lands — trade-off: keeps today's measured claim honest and publishable, defers the
     real decision rather than making it, and leaves the target soft at exactly the moment it
     would start to bind.

Recommendation: **A**, with the per-request total reported alongside as an observed figure rather
than a target. It is the only option that neither weakens a budget toward unbuildability (B) nor
defers the contradiction (D), and it matches what the interception model actually promises —
ADR-002 buys sentence-level granularity, so a sentence-level latency guarantee is the one that
follows from it. If A is taken, NFR-P-001's wording needs "per hold interval" and 06 §4 needs a
second reported row for the per-request sum.

Blocked work: nothing today — the benchmark, its report, and the current measured claim all
stand, and `--check` passes. It blocks the **tier2 detector sprint** (FR-DET-002), which should
not begin against a budget set that a ruling may move.

Ruling: **CLOSED 2026-08-27 by ADR-030** — Option A's direction, taken as a front-door
respecification rather than a patch. NFR-P-001 attaches to the **user-perceived hold**; the
per-request sum stays published, untargeted, as `total_attributable_overhead_ms`;
`added_time_to_last_byte_ms` joins it as a measured untargeted row. Targets are **derived from the
04 §2 budgets** in the ADR, and the derivation logged three gaps of its own rather than smoothing
them over — all three now ruled (2026-08-27): **M-18** enrichment capped at 10 ms *aggregate* per
sentence in 04 §2.2, **M-19** a combined 5 ms engine budget with a real measurement behind it, and
**M-20** the two targeted per-hold series emitted and, on 2026-08-28, the untargeted rename, leaving only the
last-byte row. The lane goes parallel **when
Tier-2 lands**, not now — switching earlier would change the conditions of the shipped
measurement. ADR-026 §5's bar on moving an already-missed target is untouched.

---

## DEVIATION REPORT [D3-tier2-injection-budget-cannot-hold-on-unbounded-input]
Severity: MAJOR
Doc & section: 04 §2 registry, `tier2_injection` row ("| `tier2_injection` | input | <25 ms |");
01 §5 NFR-P-002 ("Tier-2 < 25 ms"); 04 §3 `budget.per_request_max_tokens: 4000`
The doc says: `tier2_injection` runs at stage `input` under a **<25 ms** budget. NFR-P-002 states
that budget with **no length qualifier and no concurrency qualifier** — it reads as a property of
the detector, holding for whatever the stage hands it.
Reality says: it holds only up to a length the stage does not enforce. Measured on the ADR-031 pick
(`madhurjindal/Jailbreak-Detector`, ONNX int8, 6 threads, n=30,
`reports/spike_tier2_crossover.json`):

| input | tokens | P50 | P99 | verdict |
|---|---|---|---|---|
| 240 ch | 68 | 8.82 | 14.84 | FITS |
| 400 ch | 104 | 14.27 | 22.80 | FITS |
| 600 ch | 158 | 23.51 | **33.57** | **BREACH** |
| 1000 ch | 247 | 46.88 | **54.82** | **BREACH** |
| 4000 ch | 512 | 95.31 | **99.72** | **BREACH** |

The crossing lies between **400 and 600 characters (104–158 tokens)**; the exact point was not
measured. This is the *fastest* of six candidates — the runner-up breaches at 240 characters — so
no checkpoint choice avoids it.

**Nothing bounds the input length.** Verified rather than assumed: `DEFAULT_MAX_CHARS = 240` bounds
the **output** segmenter only (ADR-002, `sentence_buffer.py`); the request schema declares no
`max_length` on message content; `app.py` sets no body-size cap. `Budget.per_request_max_tokens`
(`policy/schema.py:251`, 04 §3 value 4000) is **read by nothing** — `cost_budget` is still a stub —
and by its own contract it is a *cost* control in the **same input lane**, emitting
`cost.request_too_large`, which is **unmapped in all three shipped policies**. So even fully
implemented it flags concurrently with the classifier rather than gating what the classifier sees.

A second consequence has the same cause: the tokenizer truncates at **512 tokens**
(`max_position_embeddings`), so an injection payload beyond token 512 is **never seen by the
classifier at all**. FR-DET-002's input check is length-limited by construction, independently of
latency.
Impact if we ignore it: NFR-P-002 is silently unmet for a reachable input class, and the miss lands
where it is most expensive — the input lane is fully buffered before dispatch, so this time is
**pure added latency** and feeds ADR-030's `input_hold_ms` target (P50 < 40 / P99 < 50), which a
600-character prompt breaches on the detector alone. It is also an evasion path: padding a prompt
past the crossing degrades the check, and past token 512 removes it.
Options:
  A) **Bound the scored window inside the detector** — score the first N tokens (N set so measured
     P99 < 25 ms; the data puts N ≈ 104), and record truncation on the signal plus a counter —
     trade-off: content past N is unscored, which makes the existing 512-token blind spot larger
     and more common. Bounded and disclosed rather than silent, but it *is* a coverage reduction.
  B) **Window the input and score every window**, taking the max score — trade-off: the 25 ms
     budget is per detector call, so k windows cost ≈k×; it breaks the budget at k ≥ 2 unless the
     windows run concurrently, and 04 §2 has no notion of a chunked detector.
  C) **Enforce a real input length bound before the lane** — implement `per_request_max_tokens` as a
     gate and map `cost.request_too_large` in all three policies — trade-off: repurposes a cost
     control as a safety gate, and rejects long-but-legitimate prompts, which changes the gateway's
     request semantics for every use case.
  D) **Re-scope NFR-P-002 to a stated input envelope** ("<25 ms up to N tokens") — trade-off: honest
     and cheap, but it is a target gaining a qualifier *after* a measured miss, so it needs
     ADR-026 §5's anti-laundering treatment or it reads as tuning the target to the result.
Recommendation: **A**, with the coverage loss logged as a Standing Limitation in the same commit.
It keeps the budget a real bound on the hot path, needs no change to request semantics or to any
policy, and converts a silent degradation into a counted one. C is the right *eventual* answer but
belongs to the cost plane (Phase 6), and D should not be reached for while a measured option holds
the documented number.
Blocked work: the `tier2_injection` implementation — specifically its behaviour on inputs above the
crossing. The **checkpoint choice is not blocked**: ADR-031 stands under every option here, since
the pick is fastest at every length measured. `tier2_toxicity` is unaffected — its stage caps input
at 240 characters, where it measures 8.58 ms P99.


## DEVIATION REPORT [D3-full-coverage-windows-cost-600ms-at-the-policy-bound]
Severity: MAJOR
Doc & section: the `[D3-tier2-injection-budget-cannot-hold-on-unbounded-input]` ruling (2026-08-28,
to become ADR-032), items 2, 3 and 5; 04 §2 `tier2_injection` budget; ADR-030's input-hold target.
The doc says: full coverage via strided windows, MAX over windows; "MEASURE batched ONNX inference
before concluding anything: score all windows in one (or few) batched calls; measure at the policy
bound (`per_request_max_tokens` 4000 ≈ ~50 windows)"; and item 5 — "if batched full coverage
measures grossly unacceptable at the bound (>500 ms class), STOP and report with figures — do not
truncate silently."
Reality says: it is in that class at both thread settings. `eval/spike_window_latency.py`, window
104 tokens / overlap 26 / step 76 (52 windows at the bound), synthetic filler, ONNX int8, P50 ms:

| windows | input tokens | 6 threads seq | 6 threads batched | 1 thread seq |
|---|---|---|---|---|
| 1 | 102 | 11.30 | 11.62 | 49.81 |
| 4 | 330 | 47.20 | 43.52 | 198.00 |
| 8 | 634 | 96.52 | 91.99 | 393.78 |
| 16 | 1546 | 196.19 | 203.88 | 788.30 |
| **52** | **4082** | **651.41** | **800.75** | **2566.68** |

**Batching does not amortise, and past batch=2 it hurts.** Best configuration at the bound is
batch=2 → **599 ms** (8% better than sequential); batch=52 is **801 ms**, *worse* than issuing 52
separate calls. The cause is measurable rather than speculative: a single window at 1 thread costs
49.81 ms and at 6 threads 11.30 ms — a **4.41x** speedup, so ONNX Runtime already spreads one
window across the cores. There is no idle parallelism for a batch to exploit, and batching only
adds a larger tensor to a saturated pipeline. Per-window marginal cost is flat across the whole
ladder (11.30 → 12.53 ms at 6 threads; 49.2 → 49.8 at 1), which is the signature of a
compute-bound stage.

Two checks that this is not a harness artefact. **Cross-validation:** ADR-031's crossover measured
this checkpoint on 104 tokens of *real, ragged* text at 14.27 ms; this harness measures 104 tokens
of *synthetic, padded* text at 11.30 ms — same order, and the padded figure is the conservative one
per window. **Window size is not the lever:** cost per content token is **0.111 ms** at a 104-token
window against **0.187 ms** at 512, because attention is quadratic in sequence length. Smaller
windows are more token-efficient, so no window geometry rescues the bound; full coverage of 4000
tokens is inherently ~52 x ~12 ms.
Impact if we ignore it: a 4000-token prompt pays ~**0.6 s** of input hold with all six cores free,
and ~**2.6 s** under the contention ADR-030's parallel lane creates — on the *input* lane, before
the provider is even called, so it is added latency the user waits through with nothing streaming.
Publishing that as an untargeted length-parametric series (the ruling's item 3) would be honest but
would leave the gateway's own worst case an order of magnitude past every latency figure this repo
currently reports. Silently truncating instead is the one thing both the ruling and AGENTS.md §5.4
forbid.
Options:
  A) **Lower `per_request_max_tokens` in the shipped policies to a measured, stated ceiling** — the
     ruling's item 4 already designates this the per-use-case latency control, so this uses existing
     config rather than new mechanism. Measured ceilings at 6 threads: 634 tokens ≈ 8 windows ≈ 97 ms;
     1546 ≈ 20 windows ≈ 250 ms — trade-off: `cost.request_too_large` is currently **unmapped in all
     three shipped policies**, so mapping it is required and long-but-legitimate prompts start being
     refused; it also repurposes a cost control as a latency gate.
  B) **Accept and publish the scaled figure untargeted**, exactly as the ruling's item 3 specifies,
     with the worst case at the bound stated as 599 ms / 2558 ms — trade-off: no code beyond the
     windowing itself, full coverage preserved, but the published worst case is ~0.6–2.6 s and
     nothing in the product prevents a caller from reaching it.
  C) **Shard windows across cores instead of within them** — the measurement implies this is the more
     efficient use of the same six cores: 6 windows at 1 thread each would complete in ~49.8 ms wall
     (~8.3 ms/window effective) against 11.30 ms/window under intra-op parallelism, projecting ~448 ms
     at the bound — trade-off: **projected, not measured** (I have not run concurrent single-thread
     sessions), it competes for the very cores ADR-030's parallel detector lane needs, and it would
     make SL-5's contention exposure the normal case rather than the pessimistic one.
  D) **Cap by policy AND publish the parametric series** — A for the shipped default, B's disclosure
     for anything above it — trade-off: two mechanisms and two numbers to explain, but no silent
     ceiling and no unbounded hold.
Recommendation: **D**, with A's ceiling set from the measured table rather than chosen. It keeps full
coverage (no evasion recipe, which is what the first ruling bought), keeps the honest worst case
published rather than hidden, and puts the actual limit in per-use-case config where 04 §9 says
thresholds belong — a pipeline that needs 4000-token prompts can raise its own ceiling and accept
the published latency. C is worth measuring before committing to any number, since it would change
the table it rests on, but it should not be adopted on a projection.
Blocked work: **ADR-032 itself.** Its items 1, 2 and 4 are settled and implementable today (window
geometry 104/26/76, MAX aggregation, `window_count` + max-window index in signal meta, policy
ceiling as the per-use-case control). What cannot be written is item 3's budget respecification,
because the figure it would publish is the one this deviation is about. `tier2_injection` is
therefore still blocked; **`tier2_toxicity` is not** — output sentences are segmenter-bounded at 240
characters, one window, 8.58 ms P99.

## DEVIATION REPORT [D1-added-time-to-last-byte-has-no-server-side-vantage]
Severity: MAJOR
Doc & section: 06 §4's normative definition of `added_time_to_last_byte_ms` — "client-observed
last-byte time minus the same request's upstream duration" — read against 05 §3, which places that
key inside `latency_json`, a column **the gateway writes**, and against ADR-030 consequence 3:
"the honest end-to-end quantity, and the one a user's stopwatch would agree with."

The doc says: the row is a *client* observation, and it is persisted per request in the audit
record. 05 §5 lists it in the vocabulary `check_latency_keys` enforces at the write path, and
05 §3's DDL comment marks it "not yet (the last of M-20's remainder)" — i.e. an emission gap, a
thing left to do rather than a thing to decide.

Reality says: the writer has no vantage from which that quantity is observable, on either
delivery path, and the record cannot be amended once written.

- **Buffered path.** `state.audit(...)` is called at `app.py:586`; `return JSONResponse(...)` is
  at `app.py:632`. The body is not serialized, let alone sent, at write time. This ordering is
  not incidental — **M-13** put the write before the return precisely so a crash cannot deliver
  content with no record, so "audit later" reopens a closed gap.
- **Streaming path.** `state.audit(...)` at `app.py:875` follows the final
  `yield f"data: {DONE}\n\n"` at `app.py:869`, but it runs **inside the generator**. A completed
  ASGI `send()` means "handed to the transport", not "received by the client"; the bytes may sit
  in kernel or proxy buffers. The closest honest server-side name for what is knowable there is
  *last-frame handoff*, which is not what the key is called.
- **No second phase exists to carry a post-delivery figure.** The table is insert-only: there is
  no `UPDATE audit_records` anywhere in `controlplane/`. `record_status` is a crash marker
  (`records.py:50`: `partial` "is written ONLY by the crash path"), not a two-phase write.
- **The quantity is already computed, client-side, under another name.**
  `eval/bench_latency.py:237-245` returns `max(0.0, self.wall_ms - self.upstream_ms)` as
  `reference_delta_ms` — 06 §4's formula exactly. But its own field comment (`:221-224`) says
  `wall_ms` "includes `TestClient`'s ASGI transport cost, which is harness overhead a real client
  would not pay", and the report prose (`:810-816`) publishes it as an **upper bound**, "never the
  headline number". So the two cannot simply be equated: 06 §4 asks for an honest figure and the
  existing client-side one is a contaminated bound. That is a ruling, not a rename.

This is filed as a **D1** and not a D3: there is no measured breach, and nothing here is a target.
It is the documented design not being constructible from where the doc puts it.

Impact if we ignore it: the two available failure modes are both bad in a way this repo has
already named. Emitting a server-side handoff delta **under the name
`added_time_to_last_byte_ms`** publishes a number whose label claims a vantage it does not have —
the AGENTS.md §7 problem, and worse here than a missing row, because the name is what a reader
would trust. Leaving it unemitted makes 05 §3's "not yet" permanent and keeps a promise in the
contract that no report can satisfy, which is the doc rot the M-row register exists to prevent.
Untargeted status limits the blast radius but does not remove it: NFR-P-001 keeps its verdict
either way, so this is MAJOR rather than BLOCKER — not on the demo path, no fail-safe implication,
and no other Phase-5 item depends on it. Rounding up would be defensible on the §7 edge alone.

Options:
  A) **Respecify 06 §4 to the server-side quantity** — "last-frame handoff − upstream duration" —
     and emit it, renaming the key to match (`added_time_to_last_handoff_ms` or similar). On the
     buffered path this needs the body serialized before the audit call, which is doable without
     moving the write. Trade-off: emittable and honest **once renamed**; but it silently drops
     network egress to a real client, so it is not the stopwatch figure ADR-030 asked for, and
     ADR-030 consequence 3 has to be amended rather than implemented.
  B) **Withdraw the key from `latency_json` and site the quantity in the benchmark**, where a
     client vantage actually exists, with the transport-cost caveat stated in the row. Trade-off:
     honest vantage, no new key, M-13 untouched, and the code already computes it; but the audit
     record can then never carry an end-to-end figure per request, and the benchmark's version
     needs its `TestClient` overhead either subtracted or disclosed for the row to be more than
     the upper bound it is today.
  C) **Have the client write it** — benchmark/demo harness reports its own last-byte time back
     for the request id. Trade-off: the only option that yields a genuinely client-observed
     per-request number; cost is a second write against an append-only table (a schema change
     AGENTS.md §9.6 constrains) plus client-supplied timing inside an audit record, which is a
     trust boundary this repo has not crossed anywhere else.
  D) **Leave it documented and unemitted.** Trade-off: zero work and zero risk of a mislabelled
     number; the contract keeps a row nothing produces, indefinitely.

Recommendation: **B.** It is the only option that neither labels a quantity as something it is not
(A), nor puts unverifiable client timing into the audit record (C), nor leaves the contract
promising a row forever (D) — and the vantage question answers itself: the benchmark *is* a
client, and the gateway is not. The disclosure work it implies is smaller than the rename A forces
through ADR-030.

Blocked work: **item 10's second half — the whole of M-20's remainder.** Nothing else waits on it:
the row is untargeted, so NFR-P-001's verdict, `--check`, and every other Phase-5 item are
unaffected.

---

## DEVIATION REPORT [D1-windowed-injection-cannot-be-enforced-by-a-per-call-budget]
Severity: MAJOR
Doc & section: **ADR-032** items 1-3 and consequence 1 ("`tier2_injection` is unblocked and
implementable: windowed 104/26/76, MAX aggregation, batch 4"); **04 §2** registry row
`tier2_injection` ("<25 ms **per 104-token window**"); **NFR-P-002**; the enforcement mechanism in
`controlplane/detectors/base.py` (`BUDGETS_MS` + `run_with_budget`) and its only call site,
`controlplane/gateway/pipeline.py:280`.
The doc says: two things that cannot both hold. 04 §2 now budgets `tier2_injection` **per window**,
and ADR-032 **accepts and publishes** ~651 ms P50 for the 52-window input at
`per_request_max_tokens: 4000` — full coverage, pre-dispatch, "not negotiable" (item 3). Meanwhile
`BUDGETS_MS["tier2_injection"] = 25.0` is a **flat per-call scalar**, and `pipeline.py:280` runs
every detector as `await run_with_budget(detector, ctx, BUDGETS_MS[name])`, which is
`asyncio.wait_for(detector.detect(ctx), timeout=0.025)`. A detector that is *specified* to take
651 ms is *enforced* at 25 ms by the only runner that calls it.
Reality says: the contradiction is not escapable by implementation choice, because the two viable
implementations fail in opposite directions. Measured on this interpreter (Python 3.14.6), a
`wait_for(..., timeout=0.025)` around 300 ms of work:

| detector shape | outcome |
|---|---|
| synchronous, never awaits (blocks the loop) | **returned normally — no `TimeoutError`** (300.1 ms elapsed) |
| yields at each window boundary (`await asyncio.sleep(0)`) | **raised `asyncio.TimeoutError`** at 36.4 ms |

`run_with_budget`'s own docstring already states the mechanism ("a detector that blocks the event
loop synchronously cannot be interrupted by `wait_for` — the timeout fires only once control
returns"), so this is a documented property being met, not a bug. The consequence is the trap: the
**correct** implementation — yielding between windows so a 651 ms scan does not stall every
concurrent request on a single-threaded event loop — is exactly the one the runner cancels at
25 ms, while the **incorrect** one passes by blocking the loop for 651 ms. There is no third shape.
And a cancellation is not a benign miss: `DetectorTimeout` resolves under policy `fail_mode`
(04 §5), which the shipped policies configure two ways, both wrong here —
`finance_advisor.yaml` `tier2: fail_closed` would **block every multi-window input** on the
highest-stakes pipeline as a detector fault, and `support_bot.yaml` / `hr_copilot.yaml`
`tier2: fail_open` would **silently not scan** them, which is the 512-token blind spot ADR-032
consequence 2 claims to have closed, returning in a different guise.
Impact if we ignore it: `tier2_injection` cannot be landed in a state that matches ADR-032. Either
it is written to block the event loop for up to 0.6 s per request (and 1.3 s at `hr_copilot`'s
8000-token ceiling ≈ 104 windows), or it is written correctly and never completes a multi-window
scan. FR-DET-002 and ADR-032 consequence 2 both rest on the scan completing.
Options:
  A) **Per-window budget enforced inside the detector; the runner's ceiling derived from ADR-032's
     published series.** 04 §2's "<25 ms per window" becomes literal — the detector checks its own
     per-window deadline window-by-window and raises `DetectorTimeout` itself — and `pipeline.py`
     passes a window-count-scaled ceiling instead of `BUDGETS_MS[name]` — trade-off: `BUDGETS_MS`
     stops being uniformly "the number `wait_for` gets" for one detector, and the scaled ceiling
     needs a window count the runner does not have until the detector has tokenized (either the
     detector exposes a cheap `window_count(text)`, or the ceiling comes from
     `per_request_max_tokens`, which over-provisions on short inputs).
  B) **Run the windows in a thread executor and leave the flat 25 ms `wait_for` in place.** The
     scan does not block the loop, and `wait_for` can then actually cancel it — trade-off: it
     *would* cancel it, at 25 ms, so this fixes the concurrency half and leaves the contradiction
     untouched. Listed because it is the reflexive fix and it does not work.
  C) **Enforce `per_request_max_tokens` as a real pre-lane token bound and set the runner budget to
     `25 × ceil(max_tokens / 76)`.** Mechanically simple and uses the ADR-032 escape valve —
     trade-off: on `hr_copilot`'s 8000 that is a ~1.3 s timeout, at which point the budget has
     stopped being a guard against anything; and M-28 records that `cost.request_too_large` is
     unmapped in all three policies, so the rejection this bound implies has no user-facing signal.
  D) **Keep the flat 25 ms and accept the fault.** Trade-off: contradicts ADR-032 outright and
     picks one of the two bad failure modes above per use case. Named so the ruling can reject it
     explicitly rather than by omission.
Recommendation: **A.** It is the only option under which the shipped code says what 04 §2 says —
the budget *is* per window, so the mechanism that enforces it should be too — and it keeps the
detector non-blocking, which is the property the gateway needs from every CPU-bound detector and
not a concession to this one. The cost is real and worth stating: one detector's budget stops being
enforced by the uniform outer wrapper, so the report should record that `run_with_budget`'s
guarantee is now explicitly two-tier rather than let that be discovered later.
Blocked work: **`tier2_injection`** (Phase 5 item 2's input half) and anything downstream of it —
07 beat 7's re-point to a real `tier2` fault, and `eval/fault_injection.py`'s `tier2` coverage row.
**`tier2_toxicity` is NOT blocked**: output sentences are segmenter-bounded at 240 characters, one
window, 8.58 ms P99, so the flat 25 ms budget fits it as written.

---

## DEVIATION REPORT [D1-input-hold-target-cannot-survive-multi-window-injection]
Severity: MAJOR
Doc & section: **ADR-030**'s input-lane derivation ("| Input lane |
`max(tier1_pii 2, tier1_blocklist 2, tier2_injection 25, cost_budget 1, loop_guard 1)` + engine 5 |
**30 ms** |") and its resulting target; **01 §5 NFR-P-001** ("Input-lane hold: P50 < 40 ms,
P99 < 50 ms"); **06 §4** (`input_hold_ms` — "**Targeted** (NFR-P-001)"); **ADR-032**'s measured
window series.
The doc says: NFR-P-001's input-lane hold is **P50 < 40 ms, P99 < 50 ms**, and ADR-030 states those
are "**derived from the 04 §2 budgets** rather than chosen to fit" — specifically from a 30 ms
worst case whose dominant term is `tier2_injection 25`. ADR-030 §"Why these and not others" is
explicit that the 25 ms term is what sets the floor: "The input lane's *detector* composition is
25 ms and `tier2_injection` runs on *every* request, so its P50 cannot be set below 25."
Reality says: that 25 ms term is no longer the cost of the detector for any input above one window.
ADR-032 measures and **accepts** 23.28 ms P50 at 2 windows, 96.52 at 8, 196.19 at 16, and 651.41 at
the 52-window `per_request_max_tokens: 4000` bound. `input_hold_ms` is ingress + input-lane time
before dispatch (06 §4:249) — so the injection scan is *inside* the measured quantity, by
definition and not by accident. A 2-window input already lands the hold at ~28 ms against a
`P99 < 50 ms` target it still clears; an 8-window input lands it at ~97 ms and breaches by ~2×; the
bound case breaches by ~13×. `eval/bench_latency.py --check` exits nonzero on the breach, and 01 §5
records the population as holds rather than requests, so a single long prompt in the corpus is a
sample that decides the percentile.
This is **doc-versus-doc between two accepted ADRs**, and §3's precedence rules do not settle it:
ADR-030 and ADR-032 are of equal standing, and ADR-032 did not touch NFR-P-001. Its budget
respecification section scopes **NFR-P-002** to single-window inputs and its "Docs touched" line
names 01 (the NFR-P-002 row), 04 §2, 06 §4 and 08 — the input-hold *target* is untouched, so the
ADR-030 derivation still stands in the docs asserting a 30 ms worst case that its own successor
has measured at 651.
Filed as **D1 and from a projection**, both stated rather than left to inference: no measurement of
our code exists, because the detector this depends on is not written — but the projection is built
on ADR-032's own measured table rather than on an estimate, so what is projected is the composition
and not the cost. The precedent is exact and worth naming:
`[D1-tier2-budgets-cannot-coexist-with-nfr-p-001]` was filed the same way, about the same
requirement, and was ruled a specification decision rather than a target moved after a miss —
because it was ruled **before** a measurement could miss.
Impact if we ignore it: `--check` goes red the day `tier2_injection` lands and stays red, which
makes the one gate that guards NFR-P-001 unreadable — a permanently-failing tripwire is
indistinguishable from a broken one. Alternatively the breach is discovered during item 6's bench
re-run, i.e. after the detector is written, when the only remaining moves are the bad ones.
Options:
  A) **Scope the input-hold target to single-window inputs and publish multi-window input holds as
     an untargeted window-count series** — exactly the shape ADR-032 gave NFR-P-002, applied to the
     requirement ADR-032 left behind — trade-off: a second target scoped after the fact, so it must
     carry its own anti-laundering record; the distinguishing fact is that **nothing has missed it
     yet**, since the code does not exist, which is the same ground the ADR-030 filing stood on and
     is precisely what ADR-026 §5 bars when it is *not* true.
  B) **Keep the target unscoped and let `--check` fail.** Trade-off: maximally honest and
     operationally useless — see the impact line; a gate nobody can act on gets ignored, and then
     a real regression hides behind the expected red.
  C) **Lower `per_request_max_tokens` toward a single window in the shipped policies.** Trade-off:
     contradicts ADR-032 item 4's stated direction (the valve exists so a pipeline needing
     4000-token prompts can *raise* it and accept the published latency), makes the gateway unable
     to serve realistic prompts, and inherits M-28's unmapped-rejection gap.
  D) **Exclude injection-scan time from `input_hold_ms`.** Trade-off: rejected on sight and listed
     only to be rejected on the record — ADR-030 defines the hold as **user-perceived**, and the
     user waits through a pre-dispatch scan. Removing a wait that happens from a number that claims
     to measure the wait is the number-laundering AGENTS.md §7 exists to prevent.
Recommendation: **A**, ruled now rather than after item 6. It is the only option that keeps the
gate meaningful without either deleting a real wait from the measurement (D) or crippling the
documented input ceiling (C), and it makes the two ADRs consistent by finishing the scoping ADR-032
started one requirement short of. The anti-laundering record should state, as ADR-030's did, that
it is written **before** any measurement exists and that SL-1 and ADR-026 §5 are untouched.
Blocked work: **item 6** (the ADR-030 parallel-lane trigger and the `bench_latency` re-run) and
NFR-P-001's published verdict, both only once `tier2_injection` exists. Nothing blocks today, and
that is the reason to rule it today: this is the last moment the ruling can precede the
measurement.

---

## DEVIATION REPORT [D2-tier2-served-graph-is-unbuildable-on-the-ml-extra]
Severity: MAJOR
Doc & section: **ADR-031** (both checkpoints "served on ONNX Runtime, which is what puts them inside
the 04 §2 <25 ms budget — eager PyTorch misses it for every candidate measured") and its
no-checked-in-artifact stance (`eval/spike_tier2_models.build_onnx_session`: *"The export happens
here rather than being cached in the repo: a checked-in graph would be a binary artifact whose
provenance nobody could check"*); **ADR-033**
`REQUIREMENTS["tier2_injection"|"tier2_toxicity"] = ("onnxruntime", "transformers")`;
`pyproject.toml` `[project.optional-dependencies]` — `onnx`/`onnxscript` in **`dev`**, with the
rationale *"deliberately dev-only and NOT in `ml` — it BUILDS the ONNX graph, it does not serve it."*
The doc says: three things that cannot all hold. The tier-2 graph is (1) served from ONNX Runtime
int8, (2) never checked in — so built at runtime — and (3) buildable without the `dev` extra, since
`ml` is defined as the complete 02 §8 model stack and ADR-033 declares tier-2's dependency set as
exactly `onnxruntime` + `transformers`.
Reality says: the build toolchain is not separable from the serve toolchain, **because the build
happens at serve time**. Probed on this interpreter by masking `onnx`/`onnxscript` from
`sys.meta_path` while leaving every `ml` package importable:

| host configuration | ADR-033 probe verdict | actual graph build |
|---|---|---|
| `.[dev,ml]` (this machine) | available | succeeds |
| `.[ml]` only | **available** | **`ModuleNotFoundError: No module named 'onnx'`** |

Both `torch.onnx.export(..., dynamo=False)` and `onnxruntime.quantization.quantize_dynamic` import
`onnx`; `import onnxruntime` alone does not pull it, which is why the pyproject comment reads
correctly in isolation and is still wrong in composition. `optimum` — the one library that would
collapse export and serve into an `ml`-only dependency — is deliberately excluded (its onnxruntime
extra fails on torch 2.13 and downgrades transformers as a side effect).

The failure lands **past ADR-033's stated boundary**, and that boundary is where the harm is:
*"a present package whose model graph fails to build at first use is a runtime fault (state (b)),
resolved by `fail_mode` like any other."* So an `.[ml]` host **boots clean** — `find_spec` succeeds
for both declared names — and then converts a structurally unkeepable promise into a per-request
fault. Under `finance_advisor` (`tier2: fail_closed`) that is a **BLOCK on every request**; under
`support_bot`/`hr_copilot` (`fail_open`) it is a **silent non-scan of every request**. This is
precisely the D7 edge ADR-033 closed at boot, re-entering through a dependency the probe does not
know to ask about.
Impact if we ignore it: `REQUIREMENTS` is a false statement about what tier-2 needs, and ADR-033's
boot refusal — the mechanism that exists so a fail-closed promise is never silently broken — cannot
fire for the most likely real deployment. It is invisible on this host, which is the reason to rule
it now rather than after someone installs `.[ml]`.
Options:
  A) **`onnx`/`onnxscript` move to (or are added to) `ml`, and `REQUIREMENTS` for both tier-2 rows
     grows `onnx`.** The probe becomes truthful and ADR-033's boot refusal works as designed —
     trade-off: reverses an explicit, reasoned pyproject decision, and puts build tooling on serving
     hosts to produce a graph they rebuild every boot (~4.6 s: 1.76 export + 2.85 quantize, measured).
  B) **Build once into a cache directory outside the repo, keeping the toolchain in `ml`.** Amortizes
     the 4.6 s across boots — trade-off: still needs the toolchain, so it does not answer the
     deviation. Strictly an optimization on top of A; listed to be rejected as a standalone fix.
  C) **Check the int8 graph into the repo.** Removes the build dependency entirely — trade-off:
     contradicts ADR-031's provenance reasoning, adds 66.2 MB per checkpoint (132 MB) to a public
     repo, and makes the served graph unverifiable — the objection that rationale was written against.
  D) **Serve eager PyTorch when the toolchain is absent.** Trade-off: contradicts ADR-031's budget
     ruling outright — eager misses <25 ms for every candidate measured — so it would silently ship a
     detector that breaches NFR-P-002. Named for explicit rejection rather than omission.
Recommendation: **A**, with **B** as a follow-on optimization ruled separately if the 4.6 s boot cost
matters. A is the only option that makes ADR-033's probe tell the truth, and the pyproject comment it
reverses is not wrong about *what onnx does* — it is wrong that serving never builds, which is a
consequence of ADR-031's no-artifact stance that the comment predates.
Blocked work: the **provisioning seam only** — how a serving host obtains the int8 session, and what
`REQUIREMENTS` declares. **Not blocked, and proceeding:** both detectors' inference logic, windowing,
MAX aggregation, cutoffs, signal/meta emission and their blind first-contact measurements, all of
which are identical under every option and measurable on this host where the toolchain is present.
Graph provisioning sits behind **one shared helper** so the ruling changes one function rather than
two detectors.

## DEVIATION REPORT [D3-bound-case-window-count-undercovers-the-policy-bound]
Severity: MAJOR
Doc & section: **ADR-032** — the published window-cost table (its bound-case row) and the ADR's own
full-coverage guarantee; `budget.per_request_max_tokens: 4000` in all three shipped policies.
Filed 2026-08-29, **retro-entered into the ledger the same day** — see the row's closing note, and
`tests/test_deviation_ledger.py::test_every_slug_mentioned_anywhere_has_a_ledger_row`.
The doc says: every token of a bounded input is scanned — *"full-coverage strided windows"*, window
104 tokens, overlap 26, step 76, MAX over windows, no tail left unscanned. Its table's bound-case
row is labelled **"52 windows | 4082 tokens"**, presented as the cost of scanning a request at the
`per_request_max_tokens: 4000` bound.
Reality says: 52 strided windows do not reach 4000 tokens. The geometry is
`coverage_tokens(n) = 102 + (n-1)x76`, so 52 windows span `102 + 51x76` = **3978** tokens — **22
tokens short of the bound the row claimed to measure**. The bound needs
`windows_for_tokens(4000) = 1 + ceil((4000-102)/76)` = **53** windows, spanning 4054. Two further
labels in the same table are underivable by *any* route: 16 windows labelled **1546** against a
geometry of 1242, and 32 labelled **3100** against 2458.

The mechanism is what makes this worth a report rather than a typo. The labels were read off the
**synthetic filler's token count** — the whole generated string, which overshoots its target because
the generator length-checks only every 64 words — instead of being **derived from the window
geometry**. A derived label cannot drift from the geometry it describes; an observed one can, and
did. The measured latencies are sound measurements *of the windows actually fed*; it is the coverage
claim attached to them that is false.
Impact if we ignore it: the ADR's headline guarantee and its headline table contradict each other,
and the table is the half that gets cited. A reader budgeting for the bound case under-provisions by
one window's inference (~12 ms at 6 threads, ~50 ms at 1). Worse, the detector contract inherits the
error: a runner that computes 52 windows for a 4000-token input leaves 22 tokens genuinely
unscanned — a silent coverage hole in exactly the adversarial tail an injection detector exists to
read, since an attacker controls where in the request their payload sits.
Options:
  A) **Re-measure at the true bound (53 windows) and re-derive every published coverage label from
     the formula**, keeping the sound latencies; add a harness assertion that the top rung covers
     `per_request_max_tokens`, a test that published labels equal the formula's output, and a
     detector-side test that the window count at the bound leaves no unscanned tail — trade-off:
     costs one re-measurement, and the ADR must carry a correction that preserves the withdrawn
     table beside the corrected one.
  B) **Relabel only** — correct "4082" to 3978 and leave the 52-window measurement standing as the
     published bound case — trade-off: cheaper, and wrong in the way that matters. The bound case
     would remain a measurement of something that is not the bound, and the ADR would publish a
     full-coverage guarantee alongside a table that does not exercise it.
Recommendation: **A.** B fixes the arithmetic and leaves the substance broken; the whole point of a
bound case is that it is measured *at* the bound.
Blocked work: **nothing.** The re-measurement is in flight, and every other Phase-5 item — the five
detectors, the migration, items 6-10 — is independent of the outcome.

---

## DEVIATION REPORT [D1-batch-4-justification-falsified-at-the-corrected-bound]
Severity: MAJOR
Doc & section: `03` ADR-032 §"Batching does not amortise, and past a small batch it hurts" — the
`Bound batch size: 4` sentence, and consequence 1's `batch 4`.

The doc says: *"**Bound batch size: 4.** Not 2, though 2 is the nominal minimum: 599.20 and 602.66
differ by 0.6%, which is inside this harness's own run-to-run spread (below), so picking the minimum
over-fits one run. Batch 4 sits in the same flat basin with half the call count, and costs ~0.6% at
1 thread where the curve is monotonically worse."*

Reality says: on the clean re-measured artifact (`445ca31dd087`, host **0.6 QUIET**, 0 contamination
signals, 53-window bound), 6 threads, p50 ms:

| batch | 1 | 2 | 4 | 8 | 16 | 32 | 53 |
|---|---|---|---|---|---|---|---|
| p50 | 656.48 | **601.44** | 637.25 | 632.27 | 678.05 | 727.48 | 799.73 |
| calls | 53 | 27 | 14 | 7 | 4 | 2 | 1 |

- **The 0.6% is now 6%, and most of the rise is *not* the finding.** The raw b2→b4 gap is +5.95%,
  but 53 = 13x4+**1** forces a 14th call where 52 = 13x4 needed 13. That part is geometry, and it
  is consistent with the run being clean. Normalising it away is what isolates the real change:
  per **full** call with the tail removed, a 4-window call costs **12.04 ms/window** against a
  2-window call's **11.35** — **6% apart**, where the same normalisation on the pre-correction
  artifact gives 11.59 vs 11.52, i.e. **0.6%**. The flat basin was real at 52 windows and is not
  at 53.
- **"Same flat basin" fails on a second, non-geometric count.** Batch 4 (637.25, 14 calls) is
  *slower* than batch 8 (632.27, **7** calls) — fewer calls yet more time, an inversion no basin
  story contains.
- **The 1-thread figure is wrong too:** batch 4 is **+2.35%** over batch 1 (2592.88 vs 2533.29),
  not ~0.6%. (There, batch 4 *is* below batch 2 — 2592.88 vs 2597.97.)
- **What reproduces across both runs:** the minimum's **location** (batch 2) and monotone growth
  from batch 8 up. **What does not:** the size of the b2→b4 gap.
- **The instrument cannot settle it, and that is stated rather than worked around.** Every
  batch-curve point is **n=10** (`_reps_for` quarters the reps; the curve publishes medians and
  leaves p99 deliberately unresolved). Batch 4 is the least stable point in the curve —
  `max/p50 = 1.135`, the worst — and its **cold sample 602.63 sits BELOW its own p50 637.25**, so
  the first call was fast and later ones slower. `contamination_signals` returns **0** for both
  phases and is *blind here by construction*: LOCAL SPIKE reads the sequential ladder, and
  CROSS-MEASUREMENT needs a ladder counterpart, which interior curve points do not have.

Impact if we ignore it: ADR-032 keeps publishing a decision whose stated justification its own
measurement contradicts — in the very commit whose purpose is to remove that defect class. Downstream,
`tier2_injection` batches 4 and pays ~6% more per window at the bound than batch 2 on this evidence:
small in absolute terms, but the ADR chose 4 on the explicit claim that the cost was 0.6%, and that
figure moved by 10x.

Options:
  A) **Keep `batch 4`, correct the justification.** Publish both curves, state the gap as ~6% at the
     corrected bound, disclose that n=10 cannot order b2 against b4 and that b4 is the curve's least
     stable point, and keep 4 for the halved call count. — trade-off: preserves the contract and every
     downstream figure; knowingly accepts a ~6% bound-path cost the ADR accepted only unknowingly.
  B) **Move to `batch 2`.** — trade-off: takes the measured minimum, whose *location* reproduces across
     both runs; costs 27 calls instead of 14 at the bound, and re-opens the ADR's own "over-fits one
     run" objection — decided on an n=10 point either way.
  C) **Re-measure the curve at n=40 and decide on that.** — trade-off: the only option that resolves
     the question instead of choosing under known-insufficient resolution, but it needs a **harness
     change**, not just a longer run: `--reps 160` would lift the curve to n=40 and simultaneously
     drag the ladder to n=160 (the 1-thread bound rung alone would run ~7 min per mode). Decoupling
     curve reps from ladder reps is a small edit to a measurement harness, so it is named here rather
     than made unilaterally.

Recommendation: **C, then A or B on the result.** The honest blocker is instrument resolution: A and B
both ask for a decision under a spread we can cheaply remove, and this workstream's recurring defect is
precisely a figure asserted past what its evidence supports. If the re-measure is unwanted, **A** —
keep the contract, correct the reason, disclose the limit — because churning a settled parameter on an
n=10 point would repeat the error in the other direction.

Blocked work: **only ADR-032's batching paragraph and the `batch 4` mention in its consequence 1.**
Correction 1's relabelling and re-citation, the `ParametricBudget` re-grounding, the ratio-pair fix,
the five detectors and items 6-10 are all independent and proceed.

---

## DEVIATION REPORT [D1-two-window-budget-breach-not-reproduced-on-the-clean-artifact]
Severity: MAJOR
Doc & section: `03` ADR-032 §"Budget respecification (04 §2 / NFR-P-002)", bullet 1 — the sentence
justifying where the single-window scope boundary sits.

The doc says: *"**NFR-P-002's <25 ms is scoped to single-window inputs** (≤104 tokens), where it is
measured to hold at 13.01 ms P99. The boundary is not a conservative choice — it is exactly where the
measurement puts it: two windows measure **25.13 ms P99** against a 25 ms budget, so the target fails
at the first multi-window input."*

Reality says: on the clean re-measured artifact (`445ca31dd087`, host **0.6 QUIET**, 0 contamination
signals, n=40 with percentiles resolved at every rung), 6 threads, P99 ms:

| windows | sequential | batched | worst | vs 25 ms |
|---|---|---|---|---|
| 1 | 11.87 | 12.59 | 12.59 | under |
| 2 | 24.76 | 22.53 | **24.76** | **under** |
| 4 | 48.77 | 46.71 | 48.77 | over |

- **The verdict flips, not just the figure.** Two windows pass in **both** columns. The first rung
  that breaches at 6 threads is **4 windows**. The withdrawn run had 25.13 (seq) and 26.10 (bat) —
  over in both — which is what the sentence was written from.
- **But the margin is 0.24 ms — 1.0%.** That is far inside the ~26% run-to-run band this same ADR
  discloses (and the band is not a hypothetical: identical single-window work measured 11.30 and
  14.27 ms in two runs). Two windows is therefore *indistinguishable from* the budget line, not
  safely inside it. A boundary that flips on 0.24 ms should not be re-drawn on 0.24 ms.
- **This is the one direction the anti-laundering rule does not cover.** ADR-032 flagged its own
  scoping as "a target scoped *after* a measurement missed it" and recorded it as such. On the clean
  artifact there is no miss at two windows, so the narrowing is now **more** conservative than the
  measurement requires. The risk here is the mirror image of §7's: not a target moved to hide a
  miss, but a live claim of a miss that did not happen.
- **Nothing in code depends on the falsified half.** `ceiling_ms` floors the single-window case at
  `nominal_ms` and no test pins 25.13 or the two-window breach (checked). So this blocks prose, not
  behaviour.

Impact if we ignore it: ADR-032 keeps asserting a measured breach its own clean artifact does not
reproduce, in the correction whose purpose is to remove exactly that defect. And the recorded
justification for a **requirement's scope** stays false as written — the most load-bearing sentence
class in the repo to leave wrong.

Options:
  A) **Keep the single-window scope; correct the reason.** Restate as: two windows measure 24.76 ms
     against a 25 ms budget — a 1.0% margin inside a ~26% band — so the boundary stands on the
     instrument's inability to separate two windows from the budget line, not on a clean miss.
     — trade-off: preserves every downstream contract (the parametric ceiling, ADR-030 Amendment 2's
     `input_hold_ms` scoping, 04 §2.1) and states the weaker, true ground; accepts a boundary
     justified by variance rather than by a measured failure.
  B) **Re-scope NFR-P-002 to ≤2 windows (≤178 tokens)** on the measurement as it stands.
     — trade-off: follows the artifact literally; but it widens a target on a 1.0% margin inside a
     26% band, in the direction that flatters the system, and drags ADR-030 Amendment 2 and 04 §2.1
     with it. A third run could flip it back.
  C) **Re-measure the low rungs at higher n before deciding.** — trade-off: unlike the batch-4
     filing, resolution is *not* the problem here — the ladder is already n=40 with percentiles
     resolved. The 25.13 → 24.76 gap is genuine between-run drift, and more reps inside one run do
     not shrink a between-run band. Cost without a decision.

Recommendation: **A.** The figure moved 1.4% at this rung and the budget line sits inside that
movement; B re-draws a requirement's scope on less evidence than the ADR already disclosed as
insufficient, and in the self-flattering direction. A states the true, weaker ground and leaves the
contract alone.

Blocked work: **only ADR-032's budget-respecification bullet 1 and the two-window breach claim
wherever it recurs.** The single-window relabels (13.01 → 12.59), 04 §2.1's ratio and tokenization
figures, 06 §4's three superseded figures, the `ParametricBudget` re-grounding, the bare-52
propagation, the five detectors and items 6-10 are all independent and proceed.

---

## DEVIATION REPORT [D1-per-hold-derivation-maxes-detectors-that-share-one-worker]
Severity: MAJOR
Doc & section: 03 ADR-030 "Derivation of the targets" table (rows 4-5); 04 §2 rule (a)
"Execution vehicle — generic"; 03 ADR-034 Part A "`max_workers=1` is load-bearing, not a default"

The doc says: ADR-030 composes every hold as **`max(...)` over the detectors on that lane** —
`| Per-sentence, with context docs | max(30, rag_grounding 30) + enrichment 10 + engine 5 | 45 ms |`
and `| Per-sentence, on_sampled boundary compare | max(30, fast_consistency 60) + ... | 75 ms |` —
and 02 §4 promises that once Tier-2 lands "lane composition becomes `~max` rather than `sum`".
ADR-034 Part A, ruled **one day later**, binds `tier2_injection`, `tier2_toxicity`,
`rag_grounding`, `fast_consistency`'s embedding comparison and `entity_enricher` to **one shared
single-worker pool**, and states that `max_workers=1` "is load-bearing, not a default" because it
preserves the one-inference-at-a-time conditions **SL-5** was measured under.

Reality says: the two rulings cannot both hold on a lane carrying **two** model detectors.
`max_workers=1` serializes pool users against each other by construction, so their budgets compose
as `sum`, not `max`. `LANES[Stage.OUTPUT_SENTENCE]` already names two of the five pool users
(`tier2_toxicity` <25 ms, `rag_grounding` <30 ms). Arithmetic over the 04 §2 budgets under
serialized pool users, with ADR-030's own engine (5 ms) and enrichment (10 ms) terms unchanged:

| ADR-030 row | Pool users in the hold | Published | Serialized | Status |
|---|---|---|---|---|
| Input lane | `tier2_injection` only | 30 ms | 30 ms | unchanged |
| Per-sentence, typical | `tier2_toxicity` only (`rag_grounding` skipped) | 30 ms | 30 ms | unchanged |
| Per-sentence, typical, enriched | + `entity_enricher`, already **additive** in the table | 40 ms | 40 ms | unchanged |
| Per-sentence, with context docs | `tier2_toxicity` 25 **+** `rag_grounding` 30 = 55 | 45 ms | **70 ms** | inside P99 < 100 |
| Per-sentence, `on_sampled`, no context docs | 25 **+** `fast_consistency` 60 = 85 | 75 ms | **100 ms** | **zero margin** vs P99 < 100 |
| Per-sentence, `on_sampled`, with context docs | 25 **+** 30 **+** 60 = 115 | (not tabulated) | **130 ms** | **breaches P99 < 100** |

Three things stated precisely, because the distinction is the whole finding:

1. **The trigger in 02 §4 is not the defect, and it fires correctly.** With *one* pool user plus
   regex detectors the `~max` claim holds: measured `gather(model + 2 regex)` at **1.04x** the model
   alone. It is only pool-user-vs-pool-user that serializes — measured `gather(model, model)` at
   **0.98x** of running them sequentially, i.e. `gather` buys nothing. Both figures are
   **DIAGNOSTIC ONLY, not citable** (`load1` 2.39, over `QUIET_LOAD1_MAX` 1.0 — 06 §8). The claim
   above does not rest on them: it rests on `max_workers=1`, which ADR-034 rules load-bearing.
2. **Nothing in the repo detects this.** `eval.check_derivations` re-derives ADR-032/034 figures
   only; ADR-030's table has no source artifact and no test. Two of the six rows are wrong today
   and CI is green.
3. **Stage separation does not rescue row 5.** `fast_consistency` is `output_full`, a different
   stage from `output_sentence` — but the pool is shared *across* stages, so a different `Stage`
   still queues behind the same worker.

Impact if we ignore it: ADR-030's per-hold targets were **derived from the 04 §2 budgets** and that
derivation is the stated reason they are trustworthy ("a target is not allowed to invent the bound
that makes it fit"). Two of its rows are arithmetically wrong against a later ADR, and the
worst-case row **breaches the published P99 < 100 ms** target it was derived to clear. README's
NFR-P-001 row tells judges the projection "is what the figure becomes when Tier-2 lands" — so the
error is already judge-facing, and it lands the moment `tier2_toxicity` ships, which is the next
item in this sweep.

Options:
  A) **Re-derive ADR-030's table with pool users composed as `sum`, keep `max_workers=1`, and
     correct 02 §4's `~max` sentence to the measured rule** (`~max` across *lanes* of one pool user
     + regex; `sum` across pool users) — trade-off: the `on_sampled` + context-docs worst case then
     stands at 130 ms against a published P99 < 100 ms, so this option **must** carry an
     accompanying decision on that row (retarget, or bound the co-occurrence in policy), and
     ADR-026 §5 bars moving an already-missed target.
  B) **Raise the pool to `max_workers>1`** so `max` composition becomes true — trade-off: directly
     contradicts ADR-034 Part A's load-bearing ruling, and pushes concurrent per-request inference
     toward the 1-thread column that **SL-5** describes, invalidating the conditions under which
     every published `tier2_injection` figure (ADR-032 Correction 2, the 12.59 ms single-window
     relabel, the citable quiet artifact) was measured. Re-measuring all of them is the real cost.
  C) **Keep both rulings and forbid the co-occurrence**: cap each lane at one pool user, making
     `rag_grounding` and `tier2_toxicity` mutually exclusive per sentence via policy — trade-off:
     `max` becomes true by construction and no published figure moves, but it removes a documented
     capability (grounding *and* toxicity on the same sentence) that 04 §2 and UC-1 both assume.

Recommendation: **A**. It is the only option that changes no measured number and no shipped
conditions — the error is in arithmetic over budgets, so the correction belongs in the arithmetic.
B re-opens every published `tier2_injection` figure to satisfy a composition claim that was never
measured; C pays for the fix with a capability the use cases need. A's cost is that it forces the
130 ms row into the open, which is the correct place for it.

Blocked work: **`tier2_toxicity` (the next sweep item) and `rag_grounding`** — both are pool users
whose landing makes the wrong rows live, and `tier2_toxicity` co-occurring with `rag_grounding` is
exactly the breaching case. Also blocked: the README NFR-P-001 projection sentence, and any
`bench_latency` re-run that publishes a forward projection. **Not blocked and proceeding:**
everything in the sweep that touches no pool user — the `bench_latency` re-run of *measured* rows
(today's lane has one pool user, where `~max` holds), tripwire re-points, τ calibration.

Adjacent finding, flagged not fixed (AGENTS.md §11): the **engine term is counted twice in
ADR-030's published rows 4-5**. Row 2's `30 ms` worst case already contains the 5 ms engine step,
and rows 4-5 use that `30` as their inner term and then add `+ engine 5` again. So the published
45 / 75 overstate their own convention by 5 ms each (the safe direction — a worst case too high).
The `Serialized` column above counts engine **once**, derived straight from the 04 §2 budgets, so
the two columns do not share a convention and the delta is not a naive subtraction. Whichever
convention a re-derivation picks, it must be picked **once** and applied to every row; this is
noted because it is in the same rows and would otherwise look like an inconsistency introduced by
the correction.

## DEVIATION REPORT [D3-nfr-p002-gate-reads-the-clock-adr-036-rejected]
Severity: MAJOR
Doc & section: 03 ADR-036 item 2 ("the budget binds detector-attributable time"); 04 §2
per-detector budgets; 05 §5 `cp_detector_latency_ms`; 06 §4 the NFR-P-002 check

The doc says: ADR-036 ruled — one day ago, on the previous filing in this same table — that
NFR-P-002 binds **detector-attributable** time rather than wall-clock, precisely because
`max_workers=1` makes a pool user's wall-clock include time a *different* detector held the
pool. `controlplane/detectors/base.py:878` enforces exactly that: `attributable_ms = sum(sink)
if sink else elapsed_ms`, and a breach raises `DetectorTimeout`.

Reality says: the benchmark gate was never moved onto that quantity. `pipeline.py:352-355`
observes `cp_detector_latency_ms` from **wall-clock** (`elapsed = (perf_counter - started) *
1000`); `eval/bench_latency.py:526` reads that same series and `check_nfr_p002` (line 557)
gates its P99 against `budget_ms(detector)` (line 578). So the gate judges a quantity the
ruling rejected. The stamped artifact from this sweep publishes two rows on that basis:

| Requirement | Detector | Stat | Budget | Published |
|---|---|---|---|---|
| NFR-P-002 | `tier2_injection` | P99 | 25.0 ms | **25.569 ms** |
| NFR-P-002 | `tier2_toxicity` | P99 | 25.0 ms | **25.114 ms** |

The two rows breach for **two different reasons**, and neither is a detector running long.

**`tier2_injection` — the clocks have already diverged.** Arithmetic, not inspection: that run
recorded **0 faults** over n=300 with a max of 26.909 ms, so samples above the 25 ms budget
exist. A sample above budget on the *enforced* quantity cannot exist without
`run_with_budget` raising `DetectorTimeout` and the pipeline recording a failure. Samples above
budget with no fault therefore prove the gated series is not the enforced series.

**`tier2_toxicity` — the gated series counts its own faults as latency data.** This row
recorded **2 faults** (`fail_open` ×2), so the zero-fault argument above does **not** apply to
it, and an earlier draft of this report wrongly claimed it did. What applies instead is
`pipeline.py:351-355`: `elapsed` is observed into `cp_detector_latency_ms` in a `finally`
block, deliberately — *"Recorded even when the detector faulted: a timeout consumed real
wall-clock, and hiding it would make the budget it breached invisible in the histogram."* That
is right for a histogram and wrong for a gate. With 2 faults in n=283 the top 1% is ~3 samples,
so the P99 that fails the gate may be a faulted attempt; the series carries no fault flag, so
**the harness cannot tell a long successful call from a timeout**. The `Faults` column and the
VIOLATION row can therefore be the same two events reported twice under different names.

(`reports/latency_report.md` per-detector table and NFR-verdict rows; quiet-host start stamp
load1 = 0.95, QUIET.)

**Observed live 2026-08-30, in the unit suite.** The predicted spurious fault is not
hypothetical. `tests/test_fault_injection.py::test_fail_open_records_the_fault_without_letting_it_contribute`
injects a fault into `numeric_claims` and asserts `probe.failures == ("numeric_claims",)`. It
failed with `('tier2_toxicity', 'numeric_claims')` — `tier2_toxicity` breached its budget during
the run and was recorded as a detector failure **indistinguishable from the injected one**. The
test was left exactly as written (§5.4): it fired correctly, on the thing it exists to detect.

Reproduction is **load-dependent**, which is itself the finding: 6 isolated repetitions of that
test all passed, while the full-suite run failed. Those 6 reps ran at load1 2.6 → 1.5 — the loop
was its own load — so under 06 §8 they are **diagnostic only and not citable**, and no rate is
published from them. The citable statement is the qualitative one: **1 occurrence in 1
full-suite run, 0 in 6 non-quiet isolated reps**, and a budget-breach fault therefore reaches
`detector_failures_json` under ordinary contention. This is the same root cause as the three
`eval.fault_injection` control-probe failures (36/39 assertions) already published, and the
reason that harness cannot distinguish an injected fault from a breach.

Impact if we ignore it: NFR-P-002 has no working tripwire in either direction. A real
attributable breach passes the gate whenever pool waiting is not the dominant term, and
ordinary queueing on a shared single-worker pool fails the gate with no detector at fault —
which is the same event `eval/fault_injection` cannot distinguish from an injected fault. The
second mechanism compounds it: because faulted attempts land in the gated series unflagged, a
breach can be **reported twice** — once in the `Faults` column and once as a VIOLATION row —
and the report's own advice that "a P99 sitting at the budget usually means timeouts fired"
cannot be checked against the data it sits above.

Options:
  A) Observe attributable time as its own series (a new 05 §5 channel), gate NFR-P-002 on it,
     and keep publishing the wall-clock series as an ungated **queueing** figure — trade-off:
     touches 05, and the two rows above stop being NFR-P-002 verdicts. It does **not** delete
     them: both measurements are real and stay published; what changes is which requirement
     they are evidence for. Cost is that wall-clock overhang becomes visible-but-ungated.
     **A is necessary but not sufficient:** it fixes `tier2_injection`'s mechanism and leaves
     `tier2_toxicity`'s untouched, since a new series observed in the same `finally` block
     inherits the same fault contamination. A must therefore carry **A2 — partition the gated
     series by outcome**, so a breach reads "N over budget, of which M were already recorded
     as faults". Partition rather than exclude: a timeout's overrun is a real breach, it is
     just not an *additional* one, and dropping those samples would hide the breach the
     `finally` block's comment exists to keep visible.
  B) Amend ADR-036 so NFR-P-002 binds wall-clock, and keep the gate where it is — trade-off:
     reverses a one-day-old ruling and re-opens what it settled. Under `max_workers=1` a
     detector then fails its budget for its neighbour's work, and every published
     `tier2_injection` figure becomes a verdict about pool scheduling.
  C) Status quo: publish both figures, gate neither, label them "measured wall-clock, neither
     met nor breached" (what README line 137 says today) — trade-off: honest, but leaves
     NFR-P-002 with no tripwire at all through submission.

Recommendation: **A + A2**. It is the only option in which a VIOLATION row and a recorded
detector fault can ever agree, and it costs no measurement — the numbers stay, their label
changes. A2 is not optional cleanup: without it, one of the two published breaches still has
no interpretation.

Blocked work: the OVLP-01 tripwire re-point (its instruction is to *cite the bench output*, and
that output's verdict is the contested thing); any README, proposal or dashboard sentence
asserting NFR-P-002 met **or** breached for the two Tier-2 detectors; and the ADR-030
Amendment-3 hold rows that compose from Tier-2 budgets.

## DEVIATION REPORT [D3-tier2-injection-attributable-p99-exceeds-25ms]
Severity: MAJOR
Doc & section: 04 §2 / 01 §NFR table "NFR-P-002 — Per-detector fast-path budgets: Tier-1 < 2 ms · Tier-2 < 25 ms"
The doc says: a Tier-2 detector's fast-path work completes inside **25 ms**. ADR-036 fixes the
quantity that budget binds: **detector-attributable** time, in-thread CPU, the figure
`run_with_budget` enforces on — not wall-clock.
Reality says: `tier2_injection` measures an attributable **P99 of 25.348 ms** against the 25.0 ms
budget. n=300, **0 faults**, P50 20.032 · P95 22.749 · max 28.317. Quiet host (load1 0.84 at
process start, 12 CPUs), clean tree, code `94992335ff6b`, `reports/latency_report.md` §Per-detector
budget verdict. Three things establish that this is a real miss rather than another instrument
artifact:

1. **It is on the ruled instrument.** This is the first `tier2_injection` verdict rendered on the
   attributable series, per ADR-036 Amendment 1. Its predecessor
   (`[D3-nfr-p002-gate-reads-the-clock-adr-036-rejected]`) was closed precisely by moving the gate
   here, so the clock is no longer available as an explanation.
2. **It is unit-clean.** NFR-P-002 is scoped to the flat per-unit figure and `check_nfr_p002`
   compares against `budget_ms`, never ADR-034's length-scaled runner ceiling. Every frozen case is
   single-window — max ~81 estimated tokens against `WINDOW_CONTENT_TOKENS` 102 — so the parametric
   ceiling does not enter and the flat budget is the correct comparand.
3. **The same run exonerated the other detector.** `tier2_toxicity` cleared at 23.741 ms. A
   correction that moved both rows in the friendly direction would be the suspicious outcome; this
   one cleared one and confirmed the other.

Impact if we ignore it: a documented NFR ships unmet with no record, and the one detector whose
budget is genuinely marginal is the one a judge is most likely to probe. The margin is **1.4%**, so
the honest reading is "at the budget", not "far past it" — but 04 §2's figure is a `<` and the
measurement is above it.
Options:
  A) **Publish as measured and record it as a standing limitation (SL).** Budget unchanged,
     detector unchanged, number unchanged. — trade-off: the repo ships with a Tier-2 budget
     measurably missed by 1.4%, stated plainly in the README claims table.
  B) **Amend NFR-P-002's Tier-2 figure to carry the concurrency condition it was measured under.**
     [[SL-5]] already records that the <25 ms budget was measured with 6 threads free for one
     inference and that NFR-P-002 states no concurrency assumption. — trade-off: this is a target
     moved **after** a miss, which AGENTS.md §7 forbids and which ADR-030's front-door precedent
     only permits pre-measurement. It would be laundering even if the physics is sound.
  C) **Reduce per-call work until it fits** — fewer windows, a smaller graph, or tighter int8
     settings. — trade-off: legitimate engineering rather than harness tuning, but it re-opens
     ADR-032's coverage ruling, costs the credits the endgame is conserving, and would invalidate
     the accuracy figures already published for this detector.
Recommendation: **A.** It is the only option that changes no published number and no specification
after the fact. The 1.4% overshoot is also the *expected* shape of [[SL-5]]'s recorded limitation
rather than a new discovery — a budget calibrated with six threads idle should be marginal under a
serialized single-worker pool — so the honest artifact is a miss plus the SL that predicts it, and
C remains available as roadmap if the margin ever matters more than the credits.
Blocked work: **none** — this is a fresh number rather than the integrity of a published one, so
endgame §11.1 does not halt on it. One prose constraint stands until it is ruled: no README,
proposal or dashboard sentence may claim NFR-P-002 **met** for `tier2_injection`. The claims table
already states the breach.
Ruling: **A APPROVED 2026-08-30.** Publish 25.348/25 as a measured breach and record it as [[SL-8]]; close citing that row. The adjudication added one clarification, carried into the SL row so it cannot be lost: **ADR-034's enforcement ceiling (measured-envelope ×2) is a distinct quantity and is unaffected by this miss** — a *budget* is what the detector is supposed to cost, a *ceiling* is when the executor gives up on it, and a reader who conflates the two will read a 1.4% budget overshoot as a ceiling breach. Roadmap for the margin: ONNX Runtime intra-op tuning, or serving hardware.


## Rulings received 2026-08-30 — implementation pending

Recorded on receipt so a ruling is not lost between sessions. **None of the three is
implemented yet** when they were recorded: the session that received them was scoped to the
enricher measurement and an explicit "no new work". **Ruling 1 landed 2026-08-30** as
ADR-030 Amendment 3, and its ledger row is now CLOSED. Rulings 2 and 3 are tracked by the
sweep items that carry them (`rag_grounding`, and the `fast_consistency` cut).

1. **`[D1-per-hold-derivation-maxes-detectors-that-share-one-worker]` — RULED.** ADR-030's
   table recomposes as: the five ADR-034 pool-user detectors **SUM** within a lane (one worker
   serializes them); non-pool detectors **overlap (~max)**. Requires: re-derive the affected
   rows; update targets **front-door** (pre-measurement, on ADR-030's own precedent, with the
   anti-laundering note); any row that cannot fit a plausible target **publishes untargeted**
   (per-request-sum precedent); land as **ADR-030 Amendment 3**; then close the ledger row.
   Closure is pending that work — the row is not closed by this record. Directly unblocks
   `tier2_toxicity` and `rag_grounding`, both of which were blocked on it.
2. **[[M-44]] — RULED, un-provisional.** `rag_grounding` **emits the whole scored sentence as
   its span**. FR-DET-005's canonical one-signal shape requires a span-bearing host, and 15/16
   frozen `person_present` fixtures depend on it. The span-less provision in 04 §6 **remains,
   for `fast_consistency` only**. Note this needs **no enricher change**: NER over "span ± its
   sentence window" for a whole-sentence span is NER over the sentence, as M-44's own
   resolution anticipated.
3. **`fast_consistency` — CUT to roadmap** (deadline + credits). SL entry to read: *"specified
   (04 §2.3), unimplemented; UC-3 performance plane covered by `rag_grounding`."* Requires
   policy adjustment (`consistency: "off"` — quoted, per the Q-09 YAML gotcha — and
   `policy_version` bumps). The deep audit stays cut.
