# 03 — Architecture Decision Records

Format per ADR: Context → Options → Decision → Trade-offs. Status: Accepted unless marked Proposed.
New behavioral changes (including approved deviations per AGENTS.md §5.5) append here.

---

## ADR-001 — Python/FastAPI gateway, not Go/Rust

**Context:** Round 1 pitched sub-15 ms compiled-gateway overhead; team velocity and agent-assisted coding favor Python; hackathon timeline is short.
**Options:** (a) Go/Rust proxy, (b) Python FastAPI, (c) extend an existing OSS gateway (LiteLLM/Portkey).
**Decision:** (b). FastAPI async proxy.
**Trade-offs:** Overhead target relaxed to NFR-P-001 (P99 < 100 ms) and **claims are re-scoped to measured numbers**; the compiled gateway becomes an explicit roadmap item in the proposal ("architecture ports; prototype proves mechanism, not microseconds"). (c) rejected: forking an OSS gateway obscures what *we* built and drags in their abstractions.

## ADR-002 — Sentence-level buffer interception (not token-level, not full-response)

**Context:** Streaming UX vs interception guarantee.
**Options:** token-level checks (noisy, wasteful), full-response buffering (kills streaming latency story), sentence-level buffer.
**Decision:** Sentence-level. Checks run per buffered sentence before release.
**Trade-offs:** Mid-stream BLOCK/ESCALATE cannot recall earlier released sentences — documented honestly (02 §4). Sentence segmentation is heuristic (punctuation + length cap); edge cases logged, not perfected.

## ADR-003 — Policies as versioned YAML data, zero use-case conditionals in code

**Context:** Round 2 brief's headline: behavior must vary by use case/geography/risk appetite; rigid rules age.
**Decision:** All thresholds, label→action maps, fail modes, fallback messages, sampling rates, budgets live in `policies/*.yaml`, schema-validated (04 §3), versioned; the engine is generic.
**Trade-offs:** Slightly more upfront schema work; expressive limits (no arbitrary logic in YAML) — acceptable, and *good* for auditability.

## ADR-004 — Fast/slow split with hard isolation

**Context:** The brief's latency-vs-coverage tension.
**Decision:** Sync fast lane (T1 patterns, T2 small classifiers, fast hallucination proxy) with per-detector budgets; async sampled deep lane (semantic-entropy clustering, fairness checks). No hot-path awaits on the deep lane — enforced by test (NFR-P-003).
**Trade-offs:** Deep findings can't stop the specific response they analyzed; they improve *future* behavior via feedback loop. This is the honest industry pattern, stated as such.

## ADR-005 — Hallucination scoring: fast proxy + calibrated thresholds; careful claims

**Context:** Round 1 cited "Conformal Abstention, NeurIPS 2026" — wrong venue/year; and "mathematical guarantees" over-claimed.
**Decision:** Fast path uses self-consistency (2-sample embedding agreement) or RAG grounding when context exists. Thresholds τ_low/τ_high are **calibrated on our labeled set**, conformal-style (target quantile of non-conformity scores). Citations corrected: Farquhar et al., *Nature* 2024 (semantic entropy); Manakul et al., EMNLP 2023 (SelfCheckGPT); **Yadkori et al., 2024 (arXiv, Google DeepMind) — "Mitigating LLM Hallucinations via Conformal Abstention."** Language: "statistically calibrated under standard exchangeability assumptions," never "guaranteed."
**Trade-offs:** Weaker-sounding claim; far more defensible in Q&A. Calibration quality limited by dataset size — reported, not hidden.

## ADR-006 — SQLite for audit + metrics (not ClickHouse/Kafka/Redis)

**Context:** Round 1 stack listed Grafana+ClickHouse+Redis Streams; prototype needs zero-ops storage.
**Decision:** SQLite (WAL mode): `audit_records`, `review_items`, `metrics_events`. In-process asyncio queue replaces Kafka/Redis for the deep lane.
**Trade-offs:** Not multi-node — irrelevant at prototype scale (charter NG1). Schema mirrors what a ClickHouse deployment would use; stated as roadmap.

## ADR-007 — Dashboard: Streamlit reading SQLite

**Context:** Grafana is prettier but adds docker-compose + provisioning time.
**Options:** (a) Grafana+SQLite datasource, (b) Streamlit app, (c) static matplotlib report.
**Decision:** (b) Streamlit — fastest to a live, interactive judge-facing view; can screen-record for video. *(Confirmed 2026-08-24, Q-03 ruling — status Proposed → Accepted.)*
**Trade-offs:** Less "enterprise-looking" than Grafana. Revisit only if time surplus exists (unlikely).

## ADR-008 — Judge-facing integrity rules (stats, citations, numbers)

**Context:** Round 1 material contained unsourced stats ("300% PII leakage increase") and a gap table omitting Portkey.
**Decision:** (1) Every statistic in proposal/video/README is either sourced to a verifiable publication or replaced with our own measured result. (2) Competitive analysis includes Portkey, Datadog LLM Obs, Arize; differentiation claim narrowed to *converged tri-plane policy decisions + per-use-case governance + calibrated thresholds*, not "nobody does any two of these." (3) Repo numbers reproducible per AGENTS.md §7.
**Trade-offs:** Humbler table; survives expert judges.

## ADR-009 — Model cascade kept minimal: two tiers, confidence-gated

**Context:** Full RouteLLM-style learned routing is out of scope; cost plane still needs a real mechanism.
**Decision:** Two-tier cascade (small/cheap model first; escalate to frontier model when fast-confidence < τ_route or policy demands it), plus per-use-case budgets and a loop guard. Router is embedding-similarity intent matching against a small labeled intent set (semantic-router pattern), no training.
**Trade-offs:** Cost-savings numbers come from a *simulation over demo traffic* (both paths priced), labeled as simulation — not a production claim.

## ADR-010 — Escalation review UX: minimal admin endpoints + CLI, no review web app

**Context:** HITL loop is judged (charter S4) but a full reviewer UI is expensive.
**Decision:** `GET /admin/review`, `POST /admin/review/{id}` (approve/reject + note) + a tiny CLI wrapper used live in the demo.
**Trade-offs:** Less polished; loop is still fully demonstrated end-to-end with audit lineage.

## ADR-011 — `privacy.person` producer: entity-enrichment stage (resolves review finding 1, D1)

**Context:** The taxonomy, all three policies, `overlap.jsonl`, and demo beats 4–5 depend on `privacy.person`, but no detector in the 04 §2 registry emitted it; FR-DET-005 requires ONE multi-label signal, so a separate NER detector emitting its own signal would break the one-signal rule.
**Options:** (a) standalone NER detector + engine-side signal correlation, (b) enrichment stage that appends the label to the existing hallucination signal, (c) drop the label and rework the signature demo.
**Decision:** (b). New `entity_enricher` stage (04 §2.2): spaCy `en_core_web_sm` NER over spans of span-bearing `hallucination.*` signals; a PERSON entity appends `privacy.person` + `responsibility` plane to the **same** signal. New dependency: spaCy (+~40 MB model), recorded in 02 §8.
**Trade-offs:** Small-model NER quality is modest — acceptable on synthetic fixtures; enrichment failure skips silently (logged), never blocks — it is not a policy `fail_mode` class.

## ADR-012 — Score semantics: `detection` vs `confidence` kinds; band logic scoped (resolves findings 2+3, D4)

**Context:** 04 §4.3 step 2 dropped any hallucination signal with score ≥ τ_high — which silently killed deterministic `numeric_claims` (score 1.0). Score polarity was also undefined and inconsistent (toxicity: high=bad; consistency: high=good).
**Decision:** Signals carry `score_kind` (04 §1.2). `detection` = certainty the problem exists (higher = worse); emitters: tier1_*, tier2_*, numeric_claims, cost_*, loop_guard, conv_tracker; band logic NEVER applies. `confidence` = confidence content is correct/grounded (higher = better); emitters: fast_consistency, rag_grounding; these always emit, and only the policy engine's band logic decides firing.
**Trade-offs:** Engine branches on score_kind (one conditional); bonus: confidence scores are audited even on PASS → free calibration data for doc-06 §3.

## ADR-013 — Cascade mechanics: pre-dispatch router + fully-buffered probe; never mid-stream re-dispatch (resolves finding 4, D1)

**Context:** ADR-009's "escalate when fast-confidence < τ_route" was computed on output, but by then small-tier sentences may already be released — colliding with the no-recall rule (ADR-002); 02 §4 showed a single dispatch.
**Decision:** Two mechanisms, both specified: (1) the semantic router picks the tier **pre-dispatch** (unchanged). (2) Optional per-policy `cascade_probe: on` — the small tier is called **non-streaming (fully buffered)**; if probe confidence ≥ τ_route, the buffered text is delivered through the normal sentence pipeline; if below, the request is re-dispatched to the frontier model (streaming). There is no mid-stream re-dispatch, ever. `cascade_probe: on` for support_bot & hr_copilot; `off` for finance_advisor (always frontier — high stakes). This makes the audit fields `model_requested`/`model_used`/`cascade_escalated` implementable exactly as documented in 05 §4.
**Trade-offs:** Probe path adds TTFB (small-tier full generation before first byte) — accepted for the cost savings, measured in bench_latency, and stated in the demo.

## ADR-014 — Consistency availability: `consistency: on` ⇒ `streaming: false`; sampled-mode lag = skip-with-marker (resolves finding 5, D4)

**Context:** The parallel 2nd sample arrives at provider pace; at a sentence boundary it may lag. Holding breaks NFR-P-001; silently skipping removes UC-3's most important check.
**Options:** (a) per-sentence hold with a timeout cap (weakens the latency claim), (b) skip-with-marker everywhere (silently degrades UC-3), (c) require full-response buffering wherever consistency is mandatory — reusing existing FR-GW-004.
**Decision:** (c)+(b) split by mode, schema-enforced. `consistency: on` requires `streaming: false`: the full response and its parallel sample are compared once, pre-delivery — the check is always available and **nothing reaches the user before the verdict** (UC-3 becomes non-streaming; decision-support tolerates latency, and it strengthens the quarantine story). `consistency: on_sampled` (streaming, UC-1): compare aligned prefixes only when sample-2 length ≥ 70% of primary; otherwise release without the signal, audit `meta.consistency:"lagged"`, count `cp_consistency_lagged_total`; deep audit is the backstop.
**Trade-offs:** UC-3 loses streaming UX — reframed as a *policy choice* (latency budget vs certainty), which strengthens the config-not-code thesis: the three pipelines now differ even in delivery mode. NFR-P-001 scoped to the streaming path; non-streaming overhead reported separately.

## ADR-015 — Edit eligibility derived from the §6 transform table + a per-signal stage rule (resolves D4-edit-eligible-label-set)

**Context:** 04 §3's rule "only span-emitting labels may map to `edit`" had two non-equivalent readings. (R1) *span-emitting* — any label whose producer emits spans, which admits `privacy.person: edit` (inherited span, ADR-011) even though no 04 §6 transform would fire, i.e. a schema-legal EDIT verdict that performs nothing. (R2) *edit-eligible* — only labels with a defined §6 transform. Separately, 07 beat 4a promised "softened claim **+ redacted detail**" while the 06 §2 OVLP cases carry no `pii.*` label, so the redaction had no producer.
**Options:** (a) R2 — allowlist derived from §6; (b) R1 + invent a new `privacy.person` transform in §6; (c) drop the label and rework the signature beat.
**Decision:** (a), with three amendments.
1. **Single source.** Edit eligibility is *derived* from the 04 §6 transform table — §6 is normative, the label set is not maintained separately — and exported as `EDIT_ELIGIBLE_LABELS = {pii.*, hallucination.*}`.
2. **Stage rule.** Label eligibility is necessary but not sufficient, and is the only half a schema can check. An edit-mapped *signal* must also carry a span **or** be `stage: output_sentence` (§6's whole-sentence soften scope); satisfying neither means no editable extent, and 04 §4.3 step 4 promotes it to ESCALATE. Per-signal runtime check in `policy/engine.py`.
3. **Consequence made explicit, not left to promotion.** `fast_consistency` is `output_full` and span-less by design, so `hallucination.low_confidence: edit` would promote at *every* firing. `support_bot.yaml` therefore drops the `hallucination.*` family map for three per-label mappings: `ungrounded_claim: edit`, `unsourced_numeric: edit`, `low_confidence: escalate`.
4. **Beat 4a fixture.** The beat-4 **demo fixture** additionally carries one `pii.email` span so 4a renders exactly as scripted, with the redaction coming from a real `pii.*` transform. The 06 §2 `overlap.jsonl` eval cases stay pure multi-label and are untouched. Verified: the fixture still BLOCKs on UC-2 (`pii.*` and `privacy.person` both → block) and ESCALATEs on UC-3.
5. **`support_bot.privacy.person: pass`** confirmed (was provisional). The label stays visible in beat 5's audit JSON — informational on UC-1, escalation-grade on UC-3, which is itself the config-not-code contrast.
**Trade-offs:** UC-1's EDIT on the signature beat now rests on `hallucination.ungrounded_claim` + `pii.email` rather than on `privacy.person`; one demo fixture is deliberately richer than its eval-set counterpart, which is noted in 07 so it cannot be mistaken for eval-set contamination. Docs touched: 04 §3 (rule reworded + stage rule), 04 §6 (marked normative source), 04 §4.3 step 4, 07 beat 4.

## ADR-016 — UC-1/UC-2 policy values ruled; `policies/*.yaml` is the normative source (resolves D4-uc1-uc2-policy-gaps)

**Context:** 04 §3 ships a complete `finance_advisor` example, but 01 §3 gives UC-1/UC-2 as "policy highlights" only — 4–6 cells each. A schema-valid file needs values no doc supplied (`toxicity.moderate`, all `budget.*`, most `fail_mode` classes, UC-2 `risk_appetite`, τ seeds).
**Options:** (a) rule the cells now; (b) carry provisional values until 06 §3 calibration.
**Decision:** Hybrid — (b) for the τ seeds, (a) for everything else. Uncontested derived values (`cascade_probe: on` both; UC-1 `on_sampled`/streaming; UC-2 `consistency: off`; UC-2 `privacy.person: block`) confirmed as-is. Ruled: **UC-1** `toxicity.moderate: pass`, budget $500 / 4000 tok / 20 rpm, `fail_mode.performance: fail_open`, `fail_mode.cost: fail_open`. **UC-2** `risk_appetite: medium`, `toxicity.moderate: pass`, budget $800 / 8000 tok / 30 rpm, `fail_mode {tier1: fail_closed, tier2: fail_open, performance: fail_open, cost: fail_open}`. τ seeds for both: 0.35 / 0.70 / 0.55, marked `# SEED(pre-calibration)` — 06 §3 calibration overwrites them and **a seed value is never judge-facing**.
Two deliberate gradients fall out: budget ordering is now real ($800 UC-2 > $500 UC-1 > $200 UC-3, keeping beat 7b's UC-3 exhaustion intact), and toxicity appetite runs `pass → pass → escalate` across UC-1/2/3.
**Trade-offs:** `policies/*.yaml` is now the **normative** source for per-UC values and 01 §3 carries distinguishing highlights only — recorded in 01 §3 so an omission there is never read as an unset value. All PROVISIONAL markers removed for ruled cells; SEED markers retained until calibration runs. Docs touched: 01 §3 (normativity line + ruled highlights folded in), 06 §3 (SEED-marker note).

## Minor resolutions log (review findings 6–8 — doc edits, no ADR needed)

- **F6:** Cost plane gets a live enforcement moment — demo beat 7b added (budget-exhaustion BLOCK, SC-2 now covered live).
- **F7:** Calibration n grown: `halluc.jsonl` 35→60, `borderline.jsonl` 10→20 (dataset ~265); 06 §3 now mandates printing calibration n + variance caveat next to the exchangeability caveat.
- **F8:** `gateway_overhead_ms` given a normative definition in 06 §4 (streaming: ingress+input lane + Σ per-sentence hold + finalization, upstream wait excluded; non-streaming: wall-clock − upstream duration; TTFB delta reported as a separate reference row).
