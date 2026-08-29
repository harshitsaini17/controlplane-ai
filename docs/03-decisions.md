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

> **Amended 2026-08-27 by ADR-029 — the premise is RATIO-PARAMETRIC.** This ADR was recorded when the two tiers differed ~12x, and that figure was inherited elsewhere as though it were architectural. It never was: ~12x was llama-era vendor pricing. The mechanism is *route cheap, escalate on low confidence* and does not depend on the ratio; measured savings scale with **(tier ratio x routing fraction)** and are reported beside the deployment's own measured ratio (**2.0x** on the pair shipped since ADR-029, exact on input and output, so blend-independent). See ADR-029 for the ruling and the amended test.

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

## ADR-017 — Band adjustment is per-label with a policy-configurable `borderline_action` (resolves D1-band-logic-vs-beat-4b)

**Context:** 04 §4.3 step 2 said a borderline score should "cap/floor its action to ESCALATE" — self-contradictory, and each reading broke a demo beat. A *cap* downgrades BLOCK→ESCALATE, breaking beat 4b (UC-2 must BLOCK). A *floor* upgrades EDIT→ESCALATE, breaking beat 4a (UC-1 must EDIT). Worse, the band escape is τ-dependent while 06 §3 owns τ calibration, so a calibration run could silently break the signature beat. ADR-016's seed thresholds put the 05 §4 reference score of 0.41 *inside* the band, making this live rather than theoretical.
**Options:** (a) cap-only; (b) floor-only scoped to sub-ESCALATE actions; (c) name the band's action in policy.
**Decision:** (c). Band adjustment is applied **per label**, not per signal, and the borderline action is a required per-policy field `borderline_action` — so neither direction is hardcoded and the band's behaviour becomes config, like every other policy decision (ADR-003, FR-POL-002). Ruled values: `support_bot: edit`, `hr_copilot: pass`, `finance_advisor: escalate`. Each matches that use case's documented low-confidence posture in 01 §3, so the ruling is consistent with the profiles rather than layered on top of them.
Required, with no default: a silent default would decide borderline behaviour for a policy author who never considered the band.
**Trade-offs:** One more required field in every policy file (all three updated). Per-label adjustment makes `meta.enriched_labels` load-bearing in the engine, since an appended label's score provenance differs from its host's.
**Still open:** clause 3, the *enriched-label survival rule*, is **not** settled by this ADR — see `[D4-enriched-label-survival-semantics]`. `privacy.person` is appended by `entity_enricher` to a host signal whose score is a *grounding* confidence, and whether the enriched label bypasses the band, follows its host, or bypasses only the borderline adjustment decides `action_expected` for all of `overlap.jsonl`, all of `borderline.jsonl`, and every person-bearing case elsewhere. `borderline_action` is therefore deliberately **not** edit-eligibility-checked in `policy/schema.py` yet: adding that validator would bake in one reading. Docs touched: 04 §3 (schema + validation rule), 01 §3 (unchanged — the ruled values match the existing highlights).

## ADR-018 — Upstream providers carry a class (`dev` | `measured`); tiers bind to concrete model ids

**Context:** the demo upstream is a local gateway that bills nothing and reports a fixed ~5000-token input floor on its non-streaming path (measured: 14 via `count_tokens`, 75 streaming, 5074 non-streaming for the same 6-word prompt). Nothing in the schema distinguished "a provider I develop against" from "a provider whose numbers I may publish", so a tainted cost figure could reach a report through an ordinary code path. Separately, 05 §4 logged `model_requested: "small-tier"` while 05 §6 had no key binding a tier name to a model id.
**Options:** (a) drop the unmetered provider; (b) make provenance a first-class field that travels with the data.
**Decision:** (b). Every provider declares `upstream_class`: **`measured`** (accounting trustworthy; data may carry judge-facing numbers) or **`dev`** (convenient, but its accounting is *not a measurement*; data is tainted). Kiro = `dev`; Groq and local Ollama = `measured`. The class is stamped on every audit record and fixture (05 §3/§4) so provenance travels with the data rather than living in someone's memory, and `eval/`/`demo/` refuse dev-class data unless run with `--allow-dev`, which taints output filenames. Tier mapping added as `tiers: {small, frontier}` per provider; `audit_records` now records `tier_requested` (the pre-dispatch routing decision) **and** `model_used` (the concrete id that answered) instead of conflating them.
**Trade-offs:** every provider entry grows three keys, and a second env var (`GROQ_API_KEY`) enters `.env.example`. Groq model ids were verified against Groq's own docs as *production* models (`llama-3.1-8b-instant`, `llama-3.3-70b-versatile`) — preview ids can be discontinued without notice, which would break the demo silently. **Price provenance is weaker than the ids:** Groq's pricing page returned 404, so the 70B figures rest on a first-party 2024 blog post and the 8B figures on secondary trackers only. Re-verify before any cost number is published.
**Consequence:** a one-price-pair-per-provider schema cannot express a two-tier cascade whose premise is that the tiers cost ~12× differently — filed as `[D2-price-table-cannot-express-per-tier-cost]`, which blocks 06 §6 entirely.

> **Note added 2026-08-27 (ADR-029) — the trade-off note above came true, verbatim.** It warned
> that a discontinued id "would silently break the demo". Groq announced the deprecation of both
> ids on 2026-06-17 and shut them down on **2026-08-16** for free and developer-tier keys. Probed
> live on 2026-08-27, both return HTTP 404 `model_not_found` on this repo's key — so it is not on
> the exempt committed-spend contract. **The prediction was right and the mitigation it named is
> the standing answer:** FR-GW-006's boot canary (ADR-028) is what turns a dead upstream into a
> refusal to start rather than a mid-demo fallback. The original text is left unedited above,
> including the now-retired `~12×` figure and the two dead ids, because it is the record of what
> was verified on 2026-08-25 and why. ADR-029 rebinds the tiers and amends ADR-009's ratio.

## ADR-019 — Enriched-label survival: two branches, and the band never applies (resolves D4-enriched-label-survival-semantics)

**Context:** ADR-017 ruled band adjustment per-label with a configurable `borderline_action`, but explicitly left clause 3 open. `entity_enricher` (ADR-011) appends `privacy.person` to a **host** `hallucination.*` signal whose score is a *grounding* confidence, so the appended label inherits a number that was never about it. Three readings were live: the enriched label (A) follows its host through the band, (B) bypasses the band entirely, or (C) is dropped with the host above `tau_high` but otherwise fires unadjusted. They agree everywhere except one cell — `hr_copilot` in-band, where `privacy.person: block` meets `borderline_action: pass` — and that cell carries demo beat 4b. The ambiguity also blocked every in-band person-bearing dataset case (06 §2 OVLP coverage) and the post-band half of the beat-4 test.
**Options:** (a) follows-host; (b) unconditional bypass; (c) two branches — dropped with the host at `score >= tau_high`, mapped-and-unadjusted below it.
**Decision:** **(c), made normative.** An enriched label has exactly two branches and no third:

| host score | enriched label |
|---|---|
| `>= tau_high` | **removed**, together with the host `hallucination.*` labels |
| `< tau_high` | fires at its **mapped** action, **unadjusted** — `borderline_action` never applies |

The rationale is that a grounding confidence of 0.5 says *"this claim is half-supported"*; it does not say *"this person is half-identifiable"*. The person either is named or is not, so the band — which is a statement about the grounding score — has no meaning for the appended label, and interpolating one would be invention. Above `tau_high`, though, there is no fabrication at all: the host claim is supported, nothing fires, and there is no fabricated detail for a person to be the subject of. So removal there is not a special case for the enriched label, it is the host signal ceasing to exist.

Rejected (a) because it lets a calibration run — which 06 §3 owns, and which is allowed to move `tau_low`/`tau_high` freely — silently turn UC-2's BLOCK into a PASS and break beat 4b. Rejected (b) because it would keep `privacy.person` firing on well-grounded, truthful text that merely mentions someone by name, which is a false positive on ordinary content and would make the label unusable on UC-2.
**Trade-offs:** `meta.enriched_labels` stops being informational and becomes **load-bearing** — the engine cannot partition a signal's labels without it, exactly as ADR-017 predicted. Two consequences follow. First, `entity_enricher` must record **every** label it appends there; an unrecorded append would be silently treated as a host label and wrongly band-adjusted. Second, that contract is now guarded rather than trusted: `Signal` rejects a `privacy.person` label absent from `meta.enriched_labels`, and rejects an `enriched_labels` entry absent from `labels` — a bidirectional check, because either half being wrong corrupts step 2. The guard lives in the `Signal` model (`detectors/base.py`) so a malformed signal cannot be constructed at all, rather than in the engine where it would be caught only if that path ran.
**Docs touched:** 04 §4.3 step 2 (rewritten), 04 §1.1 (overlap rule cross-ref), 04 §2.2 (`meta.enriched_labels` made a contract), 01 §3 (UC-2 note replaced — the open-question caveat is now a ruling), 08 (item closed).

## ADR-020 — Input-stage EDIT is supported as pre-dispatch redaction (resolves D4-input-stage-pii-edit-unresolvable; overrules the deviation's own recommendation)

**Context:** filed as `[D4-input-stage-pii-edit-unresolvable]`. 04 §4.5 said "Input EDIT is not supported in v1 (input labels must not map to edit; schema-enforced)", and `policy/schema.py` claimed to enforce it via `EDIT_ELIGIBLE_LABELS`. That claim is false: the exclusion holds only for input-*only* labels. `tier1_pii` runs at **input + output_sentence** (04 §2) and `support_bot` maps `pii.*: edit`, so an SSN in a user prompt on UC-1 lands in a state 04 §4.5 says cannot exist. The schema cannot catch it because the label is legitimately edit-eligible at the output stage — it is the *stage*, not the label, that differs, and a schema sees no stages.
**Options:** (a) promote input-stage edit-mapped signals to ESCALATE, reusing the ADR-015 span-less precedent (the deviation's recommendation); (b) support input EDIT as pre-dispatch redaction.
**Decision:** **(b).** The deviation recommended (a); that recommendation is **overruled**, because it treated the easy case as the hard one. The input is **fully buffered before dispatch** — there is no streaming, no partial release, no recall problem, and no latency race. Redaction there is strictly simpler than the mid-stream output-sentence case v1 already implements.

Input EDIT is therefore defined as: **spans are replaced in the prompt before the upstream call, the categories are audited, and dispatch proceeds.** 04 §4.5's ban is replaced by this behaviour and "Input-stage edits" is struck from the 04 §8 exclusion list. Two guards carry over unchanged: the redacted prompt **re-runs `tier1_pii` once** before dispatch (the same transform-error guard 04 §6 applies to edited output) and a second failure promotes to ESCALATE without dispatching; and the ADR-015 span-less rule applies at input too — an edit-mapped input signal with no span and no whole-sentence scope has no editable extent and is promoted to ESCALATE.

The deciding argument is not simplicity, though: **"the provider never sees the PII" is a stronger product claim than "we refused to answer"**, and it is demonstrable on screen. Option (a) would have escalated an ordinary support prompt that happens to quote an account number — a false-positive-shaped outcome on UC-1's own traffic.
**Trade-offs:** the gateway now mutates a request body before dispatch, which the previous design never did — so the audit record must distinguish the prompt as received from the prompt as sent, and `actions_json` carries the input-stage spans and categories (never the values, NFR-SEC-001). Redaction can in principle change the model's answer; that is the intended trade and is a policy choice, since UC-2 and UC-3 map the same label to BLOCK and ESCALATE respectively and never redact. `EDIT_ELIGIBLE_LABELS`' docstring claim about enforcing 04 §4.5 is now wrong and is corrected.
**Docs touched:** 04 §4.5 (rewritten), 04 §6 (`redact` scoped to both stages + the input re-run guard), 04 §8 (exclusion struck), 01 §3 (UC-1 highlight), 05 §3/§4 (input-stage action recording), 08 (item closed).

## ADR-021 — `conv_tracker` accumulates output/conversation-stage signals only; ground truth is labelled per breach unit (resolves review findings F3/F9)

**Context:** 04 §2 described `conv_tracker` as keeping "running totals of pii/hallucination signals per conversation id". `tier1_pii` also runs at input stage, so a user's own disclosure produces a signal, and a literal reading of "totals of pii signals" accumulates it. `CONV-10` — the user volunteers their own email and the assistant never repeats it — was undecidable under that wording: an all-signal tracker fires, an assistant-disclosure tracker does not. `CONV-07` had the same ambiguity in reverse, carrying a `pii.email` label for an email that appears only in a user turn.
**Options:** (a) accumulate every signal including input-stage; (b) accumulate output and conversation-stage signals only.
**Decision:** **(b).** The control plane exists to stop the *assistant* disclosing data. Counting a user's own voluntary disclosure toward a cumulative-risk breach would make the tracker fire on ordinary support conversations — the user pasting their own order number is the normal case, not the risk — and would produce a metric that measures user behaviour rather than model behaviour. Input-stage PII is not ignored: it is acted on immediately at the input stage by its own policy mapping (and, per ADR-020, redacted before dispatch on UC-1). It simply does not accumulate.

**Ground-truth labelling convention, also made normative:** a conversation case is labelled **per breach unit** — the breaching turn's own labels plus the conversation-stage signal — not as the union of every turn's labels. This follows 04 §4.1, where the evaluated unit is one output sentence plus conversation-stage signals, so ground truth describes the unit where the verdict actually lands. Earlier turns' PII is already scored by its own `pii.jsonl` cases; unioning would triple-count it and inflate per-detector recall denominators without changing a single verdict.
**Trade-offs:** the tracker is now stage-scoped, so it needs the stage on each signal it counts — cheap, since 04 §1 already carries it. `CONV-10` stays a negative control and `CONV-07` loses its `pii.email` label. A reviewer reading per-detector PII recall must know the convention to interpret the denominator, so it is stated in 06 §2 next to the composition table rather than left implicit.
**Docs touched:** 04 §2 (`conv_tracker` row + the convention), 06 §2 (convention cross-ref), `conversation.jsonl` (CONV-07).

## ADR-022 — Pricing is keyed by concrete model id, with provenance, and is never estimated (resolves D2-price-table-cannot-express-per-tier-cost)

**Context:** ADR-018 bound `tiers: {small, frontier}` to concrete model ids but left price as one `price_per_1k_in`/`price_per_1k_out` pair per **provider**. A two-tier cascade whose entire premise is that the tiers cost roughly 12× differently cannot be expressed by a single pair, so the frontier tier's price had nowhere to live and 06 §6's cascade-savings simulation was unimplementable as specified. Separately, price provenance was carried in a YAML comment — the weakest possible place for the one field AGENTS.md §7 makes load-bearing.
**Options:** (a) add a second price pair per tier; (b) key price by concrete model id and carry provenance as data.
**Decision:** **(b).** `tiers` already names concrete model ids and `audit_records.model_used` already records the concrete id that answered, so keying price by model id needs no new join and stays correct when a tier is re-pointed. The per-provider price pair is replaced by:

```yaml
pricing:                         # or the literal `pricing: unmetered`
  source_url: <url>              # where these figures came from
  retrieved: <YYYY-MM-DD>        # when — a stale price is a wrong price
  models:
    <model-id>: {per_1k_in: <float>, per_1k_out: <float>}
```

`est_cost_usd` resolves through the concrete `model_used`, and **is never estimated and never averaged across tiers** — the whole point of the cost plane is that the two tiers differ, so an average would erase the effect being measured. Three behaviours make a gap loud instead of silent:

- **missing entry at runtime** → `est_cost_usd` is `null` (not 0.0, not a guess) and `cp_pricing_missing_total{provider,model}` increments;
- **missing entry at boot, measured class** → a boot **warning** naming the model;
- **missing entry at boot for a model that appears in `tiers`** → **hard boot failure**. That model is on a routing path, so it will answer requests and produce unpriceable audit records; refusing to start is the only way that does not end in a report with holes in it.

`pricing: unmetered` stays valid and is an **affirmative claim** that no per-token charge exists (local compute) — it yields `est_cost_usd: 0.0`, which is a measurement. That is deliberately distinct from a *missing* entry, which yields `null` because the cost is unknown. Zero and unknown are different facts and the schema now keeps them apart.
**Trade-offs:** `price_table_version` is retained as a coarse bump-on-change marker, but per-provider `retrieved` is now the finer-grained and more honest provenance. Adding a tier to a policy can now fail the boot rather than silently producing null costs — intended: a loud failure at start beats a quiet hole in a judge-facing number.
**Docs touched:** 05 §6.1 (schema amended), 05 §5 (`cp_pricing_missing_total` added), `config/gateway.yaml`, 06 §6 (now implementable), 08 (item closed).

> **Rationale corrected 2026-08-27 by ADR-029.** The reasoning above cites a ~12x tier gap as the motivation for keying price by concrete model id. **The decision stands unchanged and the key is still per-model** — but the justification is that the tiers cost *differently*, not that they differ by any particular factor. The shipped gap is 2.0x (ADR-029); the schema's necessity is unaffected by its size.

## ADR-023 — Dataset ground truth is causal, not literal; expectations are harness-derived (companion ruling to the Checkpoint-1 dispositions)

**Context:** 06 §2's case format recorded `action_expected` as a literal per-use-case string. For **detection-kind** labels that is exact — the mapping is a lookup. For **confidence-kind** labels (ADR-012: `fast_consistency`, `rag_grounding`) it is not: the action depends on where the score falls relative to `tau_low`/`tau_high`, and 06 §3 calibration is explicitly allowed to move both. So a literal string silently encoded the *seed* thresholds as ground truth, and a calibration run would leave ~150 cases asserting outcomes the policy no longer produces — with nothing to detect the drift. Review finding F6 named the same problem from the other side: `borderline.jsonl`'s band membership is a hypothesis, not a measurement.
**Options:** (a) keep literal expectations and re-author them after each calibration; (b) record the causal ground truth and have the harness derive the expectation.
**Decision:** **(b).** Confidence-driven cases gain two ground-truth fields:

- `grounded: yes | no | borderline` — the band the confidence score should land in: `yes` = at or above `tau_high` (nothing fires), `borderline` = inside `[tau_low, tau_high)`, `no` = below `tau_low`. Named for the dominant case; on span-less `fast_consistency` cases with no context it denotes self-consistency confidence rather than context grounding.
- `person_present: true | false` — whether `entity_enricher` should append `privacy.person`, which ADR-019 makes outcome-relevant.

`action_expected` is **retained** but redefined as *"the action expected at the v1 seeded thresholds"*, and the harness **verifies** it against its own derivation from (ground truth + the loaded policy + ADR-019 + the ADR-015 span-less rule). A mismatch is a dataset error today and a calibration-drift alarm later — which is precisely the F6 tripwire, obtained for free. **Detection-kind cases stay literal**: their action genuinely is a lookup, and adding a band field there would imply a band that never applies to them (ADR-012).
**Trade-offs:** the case format grows two optional fields and the validator grows a derivation that must track the engine's step 2 — a real duplication risk, mitigated by deriving from the *loaded policy objects* rather than from hardcoded action strings, so a policy edit moves both together. The literal field is kept rather than dropped because a human reviewing a diff needs to see the expected outcome without running anything.
**Docs touched:** 06 §2 (case format + composition table + freeze gate), `eval/validate_dataset.py` (new), all confidence-driven dataset files.

## ADR-024 — `pii.api_key` blocks on `support_bot`: a credential is an incident, not a field to redact

**Context:** UC-1 maps `pii.*: edit`, so a leaked API key was redacted and the request
proceeded. `PII-052` was authored as an input-stage credential and the tension was flagged in
`eval/dataset/REVIEW_NEEDED.md` rather than special-cased in code — the reviewer's question was
whether the permissive use case should forward a credential at all. Redaction is the right
default for a phone number: the value is removed and the interaction continues, no harm done.
It is the wrong default for a credential, because **a typed credential is already compromised
the moment it is typed.** Stripping it from the payload does not un-leak it — the key is still
valid, and the only correct response is rotation. Redact-and-continue therefore treats a
security incident as a formatting problem and, worse, hides it: the caller sees a normal
answer and never learns to rotate.
**Options:** (a) leave `pii.*: edit` covering credentials, accepting silent forwarding; (b) add
a specific `pii.api_key: block` mapping on UC-1; (c) build per-label block messages so the
fallback can say "rotate this key".
**Decision:** **(b).** `support_bot` gains the specific mapping `pii.api_key: block`, and
`policy_version` bumps 1 → 2. This needs **no code change**: 04 §3's precedence rule is
specific > wildcard > default, and `expand_actions` already applies specific keys after
wildcards, so the new key overrides `pii.*` regardless of YAML order. The standard
`block_fallback` is used; **(c) is rejected** as machinery for one label, and a fallback that
names the leak is arguably worse than a generic one.
**Dataset consequence, and a scope correction found while applying it:** the ruling named
`PII-052`. Applying it revealed the change reaches **seven** cases — `PII-036`…`PII-040`,
`PII-045` (output-stage) and `PII-052` (input-stage) — every case carrying `pii.api_key`. This
is mechanically forced, not a judgement call: the authorized mechanism is the label-keyed
`actions` map, and `validate_dataset.derive_action` is a pure function of (labels, policy).
Neither sees `kind`, so no configuration can block the input-stage credential while leaving the
output-stage ones at `edit`. Doing that would require a **stage-conditional action map** — a new
schema feature this ADR does not grant, and one that cuts against its own rejection of
per-label machinery. `labels_expected` is **unchanged** on all seven, which is what preserves
the v1 detector metrics: they were measured over an identical label set.
**The ADR-023 harness re-derived `block` unaided**, naming all six unedited cases as
mismatches before any of them was touched — the tripwire behaving exactly as designed, so
there is no harness bug to report. It is also what caught the scope difference.
**Trade-offs:** UC-1's demo posture is "soften and redact first", and this puts one BLOCK into
it, so the use-case profile is now *mostly* permissive rather than uniformly so — a more honest
description of any real policy. No demo beat is affected (beats 2 and 4a use `pii.email` /
`pii.phone`; no beat exercises `pii.api_key`). The freeze is bumped rather than broken, and the
bump is reviewed inside the Checkpoint 2 re-review.
**Docs touched:** `policies/support_bot.yaml` (mapping + version), 01 §3 UC-1 highlights, 06 §1
(new frozen hash + the identical-label-set note), `eval/validate_dataset.py`
(`FROZEN_COMMIT`/`FROZEN_SHA256`), `eval/dataset/pii.jsonl` (7 cases),
`eval/dataset/REVIEW_NEEDED.md` (item closed).

## ADR-025 — `numeric_claims` fires on quantity-shaped numerals only (resolves D8, closes Q-18)

**Context:** the v1 contract in 04 §2 read "currency/percent/**large-number** patterns with no
citation marker". Implemented faithfully and measured blind against the frozen corpus, it
returned **precision 0.267** — 33 false positives to 12 true positives, and **30 of the 33 were
`PII-*` cases**. The cause is structural rather than a tuning miss: an SSN, a credit-card number
and a phone number are all runs of digits, so a rule keyed on digit-run length classifies
**identifiers as statistics**. The flaw is in the *specified behaviour*, which is why it needed a
ruling and not a patch (D8).
**Options:** (a) accept and report 0.267; (b) suppress large-number matches overlapping a Tier-1
PII span; (c) delete the bare digit-run rule and require a *quantity* shape.
**Decision:** **(c)**, with (b)'s intent preserved as an independent pre-filter. Three parts:

1. **The bare large-digit-run rule is DELETED from 04 §2.** A numeral fires only if it carries
   a quantity shape: adjacent currency symbol or ISO code · percent · magnitude word or `k/M/B`
   suffix · comma-grouped thousands · attached measurement unit (04 §2.4.1).
2. **Identifier exclusion is a pre-filter inside `numeric_claims`, absolute and first**
   (04 §2.4.3). It excludes Luhn-valid 13–19 digit sequences, SSN shape, phone shapes, and digit
   runs inside alphanumeric tokens. **Absolute** means an excluded candidate never reaches the
   shape branches even when currency-adjacent — chosen over a scoring interaction so behaviour is
   predictable instead of order-dependent.
3. **Q-18 is closed with a lexical citation-marker list** (04 §2.4.2): attribution phrases,
   bracketed numeric references, parenthetical author-year, URLs — searched in the numeral's own
   sentence, case-insensitive.

**Why (b) alone was rejected:** suppressing on overlap with a Tier-1 span would make
`numeric_claims` depend on another detector's output, which §9.3 forbids and which the engine
would have to mediate. The pre-filter is a deliberate **structural duplicate** of those regexes,
never a call into them, so the detectors stay independent.
**Trade-offs, accepted and documented rather than discovered later:** a currency-prefixed
Luhn-valid amount will not fire — conservative silence is right for a detector whose subject is
unsourced statistics. Bare integers in prose ("we processed 15000 requests") no longer fire
either, so recall on that shape drops; the deleted rule was the only thing catching it, and it
was catching identifiers at three times the rate. The lexical marker list also cannot tell a
*real* citation from a decorative one — that is entailment, and it stays `rag_grounding`'s job.
**The v1 precision 0.267 stands permanently** as the blind measurement against the v1 spec
(ADR-026's dual-column rule).
**Docs touched:** 04 §2 registry row + new §2.4/§2.4.1–4, 06 §3 (revision methodology),
`docs/08` (Q-18 closed, D8 closed), `controlplane/detectors/numeric_claims.py`, its tests.

### Amendment 1 — 2026-08-26: `per` is not a bare marker token (resolves D1-BLOCKER)

The list above shipped `"per "` as an attribution phrase. Implementing it exposed a defect in
the ruling itself, filed as `[D1-citation-marker-per-matches-the-rate-preposition]` **before**
the ADR-026 §5 re-measurement, so this amendment lands ahead of that measurement and the
one-re-measurement rule is not violated.

**The defect:** `per` in English is overwhelmingly the *rate* preposition. As a bare token the
marker suppressed every rate-shaped figure — `Cost is $4 million per year` emitted nothing —
including two frozen-corpus cases labelled `unsourced_numeric` (HAL-049, HAL-052). Rates are the
shape financial and performance claims most often take, and this detector's UC-3 mapping is
ESCALATE, so the miss landed on the highest-stakes path. It was not narrowable in code: there is
no reading of a literal `"per "` that excludes `per year`.

**The ruling (option A):** remove the bare token; add three attribution forms — `as per`
(retained from v1), the determiner form (`per the|this|that|its|their`), and the proper-noun
form (`per` + capitalized token). **Rationale:** the rate preposition takes a lowercase common
noun (`per user`, `per month`); attribution takes determiner + source or a proper noun. The
discriminator is grammatical, which is why it can be lexical.

**Accepted documented edge:** sentence-initial `Per company filings, …` fires, because the
capitalization test reads the *following* word and that word is a lowercase common noun. It is a
false positive on a cited claim — the safe direction for a label mapped to EDIT/ESCALATE, where
the opposite error puts an unsourced figure in front of a user. Stated in 04 §2.4.2 alongside
the converse bound (a capitalized unit rate such as `per GB` reads as a proper noun and is
suppressed; measured corpus exposure: zero cases).

Verified against the freeze before measuring: HAL-049 and HAL-052 are **no longer suppressed**,
and CLN-062 (`… per the filing`) correctly remains suppressed.

## ADR-026 — Disclosed revision protocol for `tier1_pii` (resolves D3)

**Context:** `tier1_pii` measured **recall 0.8361** against NFR-EVAL-001's 0.95, with precision
1.000 — pure missed coverage across 8 phone shapes and 2 secret shapes (D3). Two obvious
responses are both wrong. A silent fix destroys the measurement: the v1 number was taken *before*
its failures were known, and a pattern written afterwards is indistinguishable from one fitted to
the failing fixtures unless something makes the derivation auditable. Pure acceptance is equally
wrong — the misses are genuine format coverage, and refusing to fix a real gap to protect a
number is its own kind of dishonesty.
**Options:** (a) silent fix; (b) accept 0.836 permanently; (c) narrow NFR-EVAL-001's scope to the
categories v1 covers; (d) revise under disclosure.
**Decision:** **(d)**. **(c) is rejected as target-gaming** — redefining a metric to match a
result is precisely what AGENTS.md §7 forbids, and it is recorded here so the option is visibly
considered and refused. The protocol:

1. **v1 numbers are permanent.** The eval report gains two columns — *v1 (blind first contact)*
   and *v2 (post-revision, disclosed)* — plus a revision-methodology section. Recall 0.8361 /
   precision 1.000 never disappears from the record.
2. **v2 patterns derive from named published specs only**, each cited in 04 §2.5: ITU-T E.164;
   NANP conventions including the `N ∈ [2–9]` constraint; RFC 7519/7515 for JWT. The `eyJ` anchor
   is **permitted and must be justified in writing as spec-derived** — ~~it is the base64url
   encoding of `{"`, the mandatory opening of every JOSE header~~ (**this clause is wrong; see
   Correction 2026-08-26 below**) — and *that written justification is what makes the pattern
   auditable as non-fixture-shaped*. Hex secrets fire only with a
   credential cue word in the same sentence.
3. **Two scope exclusions**, documented as precision-grounded DLP trade-offs and not fixture
   avoidance: bare 7-digit local numbers (indistinguishable from order/ticket ids — exactly
   `clean.jsonl`'s FP pressure) and bare 32/64-hex without a credential cue (collides with git
   SHAs, digests, dashless UUIDs, trace ids). Both **cost known recall**, and that cost is
   reported.
4. **New tests are authored from the specifications before the re-run**, with no strings copied
   from `eval/dataset/`.
5. **One re-measurement.** If v2 recall still lands under 0.95 the miss stands and is reported:
   **the target does not move and the harness is not touched.** Precision may fall from 1.000 —
   that is reported too, in the same table. *(The scope of "the harness is not touched" is
   clarified by **Amendment 2** below: it binds measurement-affecting code, not presentation
   prose, and never on the executor's own judgment.)*

**Trade-offs:** the report becomes harder to read than a single column, which is the intended
cost — a reader can see both what the detector did before it knew its failures and after. The
protocol also concedes that a v2 number is *weaker evidence* than a v1 number by construction,
however carefully derived; the dual column exists so nobody has to take that on trust.
**Docs touched:** 04 §2 registry row + new §2.5, 06 §3 (revision methodology + the report's
dual-column requirement), `docs/08` (D3 closed after re-measurement),
`controlplane/detectors/tier1_patterns.py`, its tests, `eval/run_all.py`, README claims rows.

### Correction — 2026-08-26: the `eyJ` derivation above is arithmetically wrong (resolves D2-eyj)

**The original claim, preserved verbatim:** *"it is the base64url encoding of `{"`, the mandatory
opening of every JOSE header."*

**It is false.** `base64url('{"') == "eyI="`, not `"eyJ"`. Base64 packs three input bytes into
four output characters, so two bytes cannot determine the third character. The third character is

    ((0x22 & 0x0F) << 2) | (next_byte >> 6)  =  8 | (next_byte >> 6)

and base64 index 9 is `J`, so the anchor holds exactly when `next_byte >> 6 == 1` — i.e. the byte
following `"` lies in `0x40`–`0x7F`, which every ASCII letter does. RFC 7515 §4 makes the JOSE
header a JSON object and every registered header parameter name (`alg`, `typ`, `kid`, `crit`,
`jku`, `jwk`, `x5u`, `x5c`, `x5t`, `cty`) begins with a letter, so the anchor **does** hold for
every conforming header whose first member is a registered parameter.

**The decision stands; only its stated reason was wrong.** The anchor remains spec-derived, and
therefore still auditable as non-fixture-shaped, which is what ADR-026 §2 requires of it.

**Narrow theoretical miss, now documented:** a header whose first key begins with a non-letter,
and a pretty-printed header — JSON permits whitespace after `{`, and `base64url('{ "alg"')` is
`eyIg…`, no anchor. Neither shape appears in any conforming library's output, but the bound is
real and is stated rather than left implicit.

The error was the adjudicator's, not the implementer's, and it was caught by an implementation
test asserting the justification rather than restating it. That test pair is retained as the
artifact: `test_rfc_7515_eyj_anchor_is_a_property_of_the_format` asserts the false literal **as
false**, then asserts the true condition across nine registered parameter names and the
whitespace bound.

### Amendment 1 — 2026-08-26: what the NANP `N ∈ [2–9]` constraint actually earns (resolves D2-nanp)

§2 above cites the NANP `N ∈ [2–9]` constraint, and 04 §2.5 claimed it "happens to reject the
digit runs that would otherwise false-positive." **In the composed detector it rejects nothing.**
v1's `_PHONE` pattern (`(?:\(\d{3}\)|\b\d{3})[-.\s]?\d{3}[-.\s]?\d{4}`, unconstrained
digits) is deliberately **retained** and evaluated **first**, matching the same extent, so
longest-match-wins hands it the span before either NANP row is consulted.

**The composition is kept as-is, and the description is corrected to match it.** Keeping it is
load-bearing: the v1 baseline's meaning depends on v2 being a **superset** of v1, and narrowing
`_PHONE` would change v1-derived behaviour, so the permanent precision-1.000 figure would no
longer describe any code that ships.

Corrected statement of what the constraint earns:

- it is **live only on shapes v1 did not cover** — chiefly the spaced-parenthesis variant
  `( 415 ) 555-0123`, which v1's `\(\d{3}\)` could not match;
- **elsewhere the pre-existing v1 pattern shadows it**;
- the two NANP rows therefore add **zero recall on this corpus**;
- the entire v2 phone gain is **E.164 plus the spaced-parenthesis variant**.

**`(115) 555-0123` firing is documented v1-superset behaviour, not a bug.** Precision hardening
of `_PHONE` is future work for a later freeze cycle, and must not ride along with a measurement.

### Amendment 2 — 2026-08-26: the §5 no-touch rule binds measurement, not presentation prose (resolves D2-q18-note)

**Context.** The single permitted re-measurement under §5 ran clean, and then the report it
produced turned out to state, in prose directly above the `numeric_claims` figures, that those
figures were gated from publication by **Q-18** — a gate **ADR-025 had already lifted** when it
made the citation-marker list normative in 04 §2.4.2. The note lived in `eval/run_all.py` and
predated ADR-025; nothing updated it when the gate lifted. §5 as written admitted no way to
correct a false sentence sitting on top of a correct number: the same clause that stops a number
being re-rolled also froze the prose wrapped around it.

**Ruling — the scope of §5's no-touch rule is clarified.** It binds **measurement-affecting
code**: scoring paths, matching logic, dataset handling, metric computation. It does **not** bind
**presentation prose** — notes, labels, rendering strings — provided that any post-measurement
prose correction:

- **(a)** is committed **separately** from any measurement-affecting change;
- **(b)** ships with a **figure-identity proof**: a committed diff between the pre-fix and
  post-fix reports showing every measured number byte-identical;
- **(c)** is **independently verified by the reviewer**; and
- **(d)** is **logged in the ledger each time it is used**.

**Rationale, for the record.** §5 exists to stop numbers being re-rolled until they look better.
A change that provably cannot move a number is outside that harm — but *the judgment that it
"provably cannot" is never the executor's alone*, which is exactly what (b) and (c) exist to
enforce. The proof is committed so a reader can check it, and a second pair of eyes checks it
before the artifact is cited. Without (b) and (c) this clarification would collapse into a
self-granted exception, which is the failure mode §5 was written against.

**Trade-off accepted.** Every use costs an extra commit, an artifact, and a reviewer pass — a
deliberately non-trivial price, so that the cheap path stays "get the prose right before
measuring" rather than "fix it afterwards under the amendment." Uses accumulate visibly in the
ledger under (d) for exactly that reason: a register with several entries is itself evidence that
the prose is being written carelessly.

**First use:** this one — the stale Q-18 note, corrected in `eval/run_all.py`, with the
figure-identity proof committed as `reports/eval_report_prose_fix.diff`.

**Docs touched:** this ADR, `eval/run_all.py` (note text only), `docs/08` (ledger entry + prose-fix
log), README claims rows citing the corrected report.

## ADR-027 — A detector fault is an operational event, not a content risk (resolves D5-detector-failure-signal-is-unconstructible)

**Context.** 04 §5 instructed the gateway to "synthesize" a signal carrying
`labels: ["_meta.detector_failure"]` on `DetectorTimeout`/`DetectorError`. `Signal` validates
its labels against the **closed** §1.1 taxonomy, which contains no `_meta.*` entry — so the
object §5 required was literally unconstructible. Implementing the failure path surfaced the
contradiction as a MAJOR deviation rather than a coding obstacle: two settled contracts
disagreed, and either could have been the one to bend.

**Ruling — Option B: the taxonomy stays closed and §5's wording is corrected.** A detector
fault is an **operational** event, not a content risk. It has **no span**, belongs to **no
plane**, is **not detector-emitted**, and is **not policy-mapped** — `fail_mode` governs it,
per detector class. It therefore does not belong in the §1.1 taxonomy at all, and `Signal` is
right to refuse it. The gateway synthesizes a distinct type instead:

```
DetectorFailureRecord {failure_id, detector, error_class, stage, fail_mode_applied, ts}
```

Four normative consequences:

1. **04 §5 rewritten.** Resolution semantics are **unchanged**: `fail_open` → proceed, record,
   increment `cp_detector_failures_total{detector,fail_mode}`; `fail_closed` → the record forces
   an **ESCALATE floor** on the unit's verdict, never a silent BLOCK.
2. **Audit representation (05 §3/§4).** `signals_json` stays **pure Signals**; a new
   `detector_failures_json` column carries the records. The §4.3 step-5 stamp extends to
   "contributing signal_ids **+ failure_record_ids**", so an ESCALATE with zero content signals
   is self-explaining in the audit.
3. **Review-queue visibility (05 §2).** An escalation caused by a failure record must be
   distinguishable from one caused by content when listed via the admin API: the reviewer sees
   "detector X failed under fail_closed", not a bare quarantine.
4. **The 06 §5 fault-injection harness reads `detector_failures_json`.**

**Rationale, for the record.** The alternative — widening §1.1 with an `_meta.*` namespace —
would have bought the same audit trail at the cost of making the taxonomy no longer a taxonomy
*of content risk*. Every downstream consumer that iterates labels (the label→action map, the
plane partition, the span logic, the dataset's `labels_expected`) would then have had to learn
that one family of labels means "nothing was found; something broke", and each of those is a
place the distinction could be forgotten. Keeping the two kinds of event in two types makes the
distinction structural instead of remembered.

**"Floor" is load-bearing.** A floor lifts a PASS or EDIT to ESCALATE but leaves a genuine
content BLOCK standing, because §4.2 severity ranks BLOCK above ESCALATE. An *override* would
have downgraded that BLOCK — releasing, on the strength of a detector outage, something the
policy had blocked. The existing convergence already implements the floor; no new logic was
introduced, which is what "resolution semantics unchanged" means in practice.

**Trade-off accepted.** Two shapes now flow out of the detection stage instead of one, so the
audit writer, the fault-injection harness and the review queue each handle both. That is a real
cost, paid to keep `signals_json` a set of content findings that a reader can trust without
filtering, and to keep an operational outage from ever being presentable as a policy violation.

**Docs touched:** this ADR, 04 §4.3 (step-5 stamp) and §5 (rewritten), 05 §2/§3/§4,
06 §5, `controlplane/policy/engine.py`, `docs/08` (D5 closed, M-3 logged).

### Amendment 1 (2026-08-26) — the step-5 stamp is STORED, not derived

**Context.** Consequence 2 above extended the §4.3 step-5 stamp to "contributing signal_ids **+
failure_record_ids**" and 05 §4 listed both as canonical-view keys, but **05 §3's own
`audit_records` DDL declared neither column**. The dataclass populated both from the verdict and
the write path then dropped them silently — verified by round-trip on a fresh DB: 19 columns,
neither list among them. Filed as `[D5-adr-027-stamp-has-no-column-in-the-05-3-ddl]` (BLOCKER)
while wiring the write path this ADR specified.

**Ruling — Option A: add the columns.**

```sql
contributing_signal_ids TEXT NOT NULL DEFAULT '[]',
failure_record_ids      TEXT NOT NULL DEFAULT '[]',
```

JSON arrays of ids. **Empty array when none contributed, never NULL:** `[]` is the fact "nothing
did", NULL would say "we did not record", and only the first is something a reviewer can act on.
`escalation_cause` in the admin API (05 §2) derives from these stored columns.

**Why derivation cannot substitute** — the non-derivability analysis from the deviation report,
ratified:

1. `detector_failures_json` is populated on **fail_open** too, so the presence of a failure record
   does not mean it contributed. A consumer filtering that column would credit a fault that
   decided nothing.
2. Filtering on `fail_mode_applied` misreports in the other direction: the escalate **floor**
   leaves a genuine content BLOCK standing, so a fail_closed record can sit in a row whose verdict
   was decided by content.
3. `contributing_signal_ids` is a **strict subset** of `signals_json` by design — the signals that
   *decided*, not the signals that *fired*. Nothing in the row recovers which were which.

Only an explicit write preserves any of these distinctions.

**Trade-off accepted.** Two more columns whose contents duplicate ids already present elsewhere in
the row. That redundancy is the point: the ids are cheap and the *relationship* they record —
which of the things that fired actually decided — is not reconstructible at any price.

**Prototype note.** No migration was written and none was needed: no `.db` file existed in the
tree, so the DDL change takes effect on the next `init_db()`. A prototype DB may be recreated
rather than migrated (ADR-006 is SQLite, single-file).

**Implementation note (not a contract).** The NFR-SEC-001 shape tripwire in `records.py` needed a
column-keyed UUID exemption for these two columns: a bare array element's leaf path is `[0]`, not
a field name, so the existing field-keyed `MINTED_ID_FIELDS` exemption never fires for it.
Measured: **24.9%** of single-uuid4 arrays (499/2000) contain a digit run the tripwire reads as a
raw value, so roughly one ESCALATE in four would have refused to write its own explanation. The
exemption is UUID-only — narrower than `MINTED_ID_FIELDS`, which also accepts ISO timestamps —
because a timestamp is not a signal id. Asserted in both directions:
`test_amendment1_the_uuid_exemption_is_not_a_laundering_channel` and
`test_amendment1_an_iso_timestamp_buys_no_exemption_in_the_stamp`.

**Docs touched:** this amendment, 05 §3 (DDL + the stored-not-derived note), 05 §2 (`escalation_cause`
reads stored columns), `controlplane/audit/db.py`, `controlplane/audit/records.py`,
`tests/test_audit_records.py` (+10), `docs/08` (D5 closed).

## ADR-028 — The usage-sanity canary's reference count is repo-local (resolves D1-usage-canary-has-no-independent-count-on-the-measured-class)

**Context.** FR-GW-006 specified a boot canary comparing `count_tokens` against the provider's
reported prompt-token count, failing a measured-class boot past `usage_sanity.max_token_delta`.
Implementing it surfaced that `count_tokens` is **not repo code** — it is a *provider endpoint*.
Keyless existence probes with a control row (2026-08-26) found it present on `kiro-local` (**dev**
→ warn) and absent on `groq` (**measured** → fail boot): the invariant was implementable exactly
where its consequence was a warning, and unimplementable where it refused boot.

**The defect is in the requirement, not the implementation.** Comparing one provider endpoint
against one provider field was never an independent check — **both sides belong to the party being
audited**. It appeared to work only because the shipped dev gateway inflates one side and not the
other.

**Ruling.**

1. **The reference is a LOCAL ESTIMATE computed by repo code.** No provider endpoint is ever the
   sole reference. Default estimator: a deterministic chars-based heuristic (~4 chars/token), or a
   local tokenizer where one is bundled. **The estimator's name is recorded in the canary result**
   (`chars-per-token-v1`), because changing the divisor changes every verdict the check has ever
   produced.
2. **The check is a ratio bound with an absolute floor,** both in config:

   ```yaml
   usage_sanity: {method: local_estimate, max_ratio: 2.0, min_delta_floor: 50}
   ```

   Fail when reported `prompt_tokens` falls outside `[estimate/max_ratio, estimate*max_ratio]`
   **AND** `|delta| > min_delta_floor`. Ratio rather than flat delta because tokenizer variance is
   bounded well under 2x while scaffold injection is multiplicative (5,074 reported vs ~14 real).

   **This invariant detects GROSS accounting corruption — its ADR-018 purpose — and explicitly
   does not claim a fine-grained accounting audit.** A local estimate cannot model a provider's
   server-side chat template; that residue is what `min_delta_floor` absorbs.
3. **Consequences unchanged:** measured-class fails boot, dev-class warns loudly and continues.
   A provider that *does* expose a genuine count endpoint MAY contribute a **supplementary
   cross-check row** in the canary output — never the primary reference. `CanaryResult.cross_checks`
   exists for that, so adding one later cannot be mistaken for changing the reference.

**On the filed options — no convergence to claim.** The deviation report recommended option B:
provider-internal self-consistency, one prompt sent twice (streaming vs non-streaming), comparing
the provider's *own* reported counts. **This ruling's rationale defeats B on exactly the ground it
defeats the original** — both sides of B are still provider-reported, so B replaced one
non-independent comparison with another. B would have caught the specific ADR-018 bug (whose
inflation happens to affect only the non-streaming path) while remaining blind to any error
consistent across both paths, which B's own trade-off line admitted. Recording this rather than
reading B as "substantially the ruling": the ruling supersedes the recommendation.

**Trade-off accepted.** A chars-based estimate is crude, so the check has no resolution below
~2x. That is the honest bound of a dependency-free local reference, and it is deliberately not
closed by adding a real tokenizer: a tokenizer is a new dependency (02 §8 requires an ADR note)
whose own systematic error against the provider's chat template would compete with the threshold —
the precise trade-off that made option A unattractive. The instrument is sized to the failure it
must catch: a 362x discrepancy.

**Implementation note (not a contract).** The canary prompt's **length** turned out to be
load-bearing and is pinned by a test. Because the conditions are ANDed, `max_ratio` only binds
where `estimate * (max_ratio - 1) > min_delta_floor` — above ~50 tokens at the shipped knobs.
Measured with a first-draft 31-char prompt (estimate 8): the band was [4, 16] yet nothing failed
until reported > 58, so a **5x inflation passed** and `max_ratio` was dead weight. The shipped
prompt estimates 64 tokens, which inverts the ordering and makes the ratio the binding constraint
— the regime this ruling's rationale assumes.
`test_the_ratio_bound_is_operative_at_the_shipped_prompt_length` fails if either is changed back.

**Docs touched:** this ADR, 01 §1 FR-GW-006 (rewritten), 05 §6.1 (`usage_sanity` schema + the
gross-vs-fine-grained scope statement), `config/gateway.yaml`,
`controlplane/gateway/canary.py` (new), `controlplane/gateway/config.py` (`UsageSanity`),
`tests/test_canary.py` (new, 38), `tests/test_gateway_config.py`, `docs/08` (D1 closed).

## ADR-029 — Groq tiers rebind to the gpt-oss pair; ADR-009's cascade premise is **ratio-parametric** (resolves `[D2-groq-tier-ids-shut-down-no-production-qwen-exists]`)

**Context:** both Groq ids bound by ADR-018 were **shut down on 2026-08-16** for free and developer-tier keys (announced 2026-06-17). ADR-018's own trade-off note predicted this exact failure mode — "preview ids can be discontinued without notice, which would break the demo silently" — and while it worried about the wrong tier of the catalogue, the *production* pair is what died, 11 days before we would have demoed. A dated note is appended to ADR-018 rather than editing it: the original text is the record of what was verified on 2026-08-25.

Probed live 2026-08-27, one request each, this repo's key:

| id | result | catalogue section |
|---|---|---|
| `llama-3.1-8b-instant` | **HTTP 404** `model_not_found` | (was production) |
| `llama-3.3-70b-versatile` | **HTTP 404** `model_not_found` | (was production) |
| `openai/gpt-oss-20b` | HTTP 200, usage present, id echoed | **production** |
| `openai/gpt-oss-120b` | HTTP 200, usage present, id echoed | **production** |
| `qwen/qwen3.6-27b` | HTTP 200, usage present, id echoed | **preview** |

The two 404s establish that this key is **not** on the exempt committed-spend contract, so the rebinding is forced rather than elective. Groq names `openai/gpt-oss-20b` as the 8B's replacement, and `openai/gpt-oss-120b` **or** `qwen/qwen3.6-27b` as the 70B's.

**Options:** (a) small=`gpt-oss-20b`, frontier=`qwen/qwen3.6-27b` — preserves a ~9.6× tier gap and so the old `>5×` test, but requires amending ADR-018's production-only rule; (b) small=`gpt-oss-20b`, frontier=`gpt-oss-120b` — both production, ADR-018 unamended, but the gap is only **2.0×**, which fails the shipped cascade test; (c) one model on both tiers — 1.0× gap, deletes the cost plane's effect.

**Decision: (b).** The deviation report recommended (a) and was **overruled**; the reasoning is recorded because it generalises. Option (a)'s frontier tier is *smaller, less capable, and 5× costlier per blended token* than `gpt-oss-120b` ($0.60/$3.00 vs $0.15/$0.60 per 1M) — a pair no rational deployment would ever choose, selected only to keep a test's ratio alive. **A number produced by an economically irrational configuration is harness-fitting by construction**, even when every individual figure in it is real: the config itself becomes the fitted parameter. Under (b) "escalate to the more capable model" is actually true, both ids are production, and ADR-018 stands unamended.

Two findings from the probe independently support the overrule, neither of which the deviation report had:

- **`qwen/qwen3.6-27b` emits its reasoning trace into the response body.** At `max_tokens: 8` it returned `"\n<think>\nHere's a thinking process:\n\n1"` as message content. That is not a usage-accounting quirk; it would push reasoning scaffolding through the sentence buffer into every output-lane detector and into `audit_records`, so option (a) would have contaminated the interception path itself.
- **The gpt-oss pair spends completion tokens on reasoning before emitting content.** Both sizes returned empty content with `finish_reason: length` and `reasoning_tokens: 6` at `max_tokens: 8`. Relevant to the latency benchmark and to any canary that asserts on response text.

### Amendment to ADR-009 — the cascade premise is ratio-parametric

ADR-009 was recorded when the tiers differed ~12×, and both ADR-022 and several docstrings inherited that figure as though it were architectural. It never was: **~12× was llama-era vendor pricing.** The premise is restated as:

> The cascade mechanism is *route cheap, escalate on low confidence*. It does not depend on the price ratio. Measured savings are a function of **(tier ratio × routing fraction)** and are reported **with the deployment's own measured ratio** beside them.

The shipped ratio is **2.0×**, and it is **exactly** 2.0× on input *and* on output ($0.075→$0.15, $0.30→$0.60 per 1M). That matters more than its size: the ratio is **blend-independent**, so no choice of input/output mix can move it and none can be cherry-picked to flatter the savings figure. `test_adr_029_the_tier_ratio_is_blend_independent` pins that property at the price level.

`test_adr_022_tier_prices_preserve_the_cascade_premise` asserted `frontier > small * 5`, which 2.0× fails. It is amended **in this same commit as this ADR** — the front door — to assert what the premise actually requires: the frontier tier is **strictly costlier** per blended token, and the ratio is **≥ 1.5×**. Both survive a genuine vendor price move; a copy-paste flattening both tiers to one figure fails both. This is deliberately *not* AGENTS.md §5.4's forbidden move: the specification changed first, by ruling, and the assertion follows it. Weakening `>5×` to `>1.5×` while leaving ADR-009 claiming ~12× would have been exactly that move.

**Cost reports must carry the ratio and one context line (06 §6).** A savings percentage without its ratio is unreadable. The context line is labelled *context, not our measurement*, and cites vendors' own price pages with a retrieval date.

> **The bracket named in the adjudication did not survive verification, and the measured figures are written instead.** The ruling asked for "typical cross-vendor flagship-vs-mini gaps run ~8–25×". Retrieved 2026-08-27 from the two vendors' own pages: OpenAI `gpt-5.6-sol` vs `gpt-5-nano` = **80× input / 50× output** (53× blended); Anthropic Claude Opus 5 vs Haiku 4.5 = **5.0×** on both. Neither vendor falls inside ~8–25×; the real range is roughly **5×–50×+**. Citing two price pages beside a bracket both of them refute would have been a fabricated figure with real citations attached, so 06 §6 carries the measured numbers. This *strengthens* the amendment rather than weakening it: 5.0× is a real vendor's real gap, and within a single lineup Opus 5 vs Sonnet 5 is **2.5×** — close to ours. The spread exists because the ratio depends entirely on which pair is chosen, which is the ratio-parametric point stated as data.

**Trade-offs:**

- **A 2.0× gap makes the cascade's headline savings smaller than a ~12× gap would.** That is the honest consequence of pricing that actually exists, and it is preferred to a larger number obtained from a configuration chosen for its ratio. The mechanism demonstrates identically; only the multiplier shrinks.
- **`price_table_version` bumped 1 → 2** (ADR-022's bump-on-change marker); `retrieved` is 2026-08-27.
- **The usage canary now passes with ~7 tokens of margin, and this is a measured fragility, not a comfortable pass.** At the shipped canary prompt (estimate 64), both gpt-oss sizes report `prompt_tokens: 121` — a **1.89×** ratio against `max_ratio: 2.0`, band [32, 128]. The delta (57) already clears `min_delta_floor` (50), so the ANDed condition rests entirely on the band leg. Measured across three prompt lengths, the cause is decomposable and is **not** the ADR-018 pathology: gpt-oss tokenizes this prose at ~5.1 chars/token (the estimator assumes 4.0) and adds ~**72 tokens** of fixed chat-template overhead; qwen adds ~11. Residual under 1 token at every length. Real scaffolding, correctly reported — but ADR-028's rationale assumed "tokenizer variance is well under 2×", and a 72-token fixed preamble against a 64-token estimate is not tokenizer variance. **No knob is changed here**, because changing a threshold to widen a margin during a rebinding is the move §5.4 forbids and nothing is currently failing. Logged as **M-15** in `docs/08` so it is visible rather than rediscovered at the canary step; if Groq's template grows, a measured-class provider will refuse to boot.

**Docs touched:** this ADR, ADR-018 (dated note appended, original preserved), ADR-022 + 05 §6.1 (the inherited ~12× rationale corrected to ratio-parametric), 05 §3/§4 (example record's `model_used`), 06 §6 (ratio-parametric reporting rules), `config/gateway.yaml` (tiers, prices, provenance, `price_table_version`), `controlplane/gateway/config.py` + `sse_proxy.py` (docstrings asserting ~12×), README (price-provenance bullet), `docs/08` (deviation closed, **SL-3 downgraded**, M-13 logged), `tests/test_gateway_config.py` (constants, production-id test, cascade test amended + blend-independence test added), `tests/test_sse_proxy.py`, `tests/test_canary.py`, `tests/test_audit_records.py` (fixture ids rebound).

## Minor resolutions log (review findings 6–8 — doc edits, no ADR needed)

- **F6:** Cost plane gets a live enforcement moment — demo beat 7b added (budget-exhaustion BLOCK, SC-2 now covered live).
- **F7:** Calibration n grown: `halluc.jsonl` 35→60, `borderline.jsonl` 10→20 (dataset ~265); 06 §3 now mandates printing calibration n + variance caveat next to the exchangeability caveat.
- **F8:** `gateway_overhead_ms` given a normative definition in 06 §4 (streaming: ingress+input lane + Σ per-sentence hold + finalization, upstream wait excluded; non-streaming: wall-clock − upstream duration; TTFB delta reported as a separate reference row).

## ADR-030 — NFR-P-001 is re-scoped to the user-perceived hold; the per-request sum is reported, not targeted (resolves `[D1-tier2-budgets-cannot-coexist-with-nfr-p-001]`)

**Status:** Accepted 2026-08-27. Front-door respecification of NFR-P-001, ruled after the
deviation was filed and before any Tier-2 measurement exists.

**Context.** `eval/bench_latency`'s forward projection showed that NFR-P-001 (streaming P50 < 40 /
P99 < 100 ms) and the 04 §2 per-sentence budget set cannot both hold once the documented detector
set is complete. 06 §4 defines the streaming figure as a **sum over per-sentence holds**, so a
per-sentence budget is paid once per sentence and the segment count multiplies it. Measured over
the frozen corpus with the shipped `Segmentation` (n=280): P50 **1** segment, P95 **3**, P99 **6**,
max **10**.

The motivating evidence, preserved verbatim from the deviation rather than re-derived:

| Segments | Sequential (as implemented) | Parallel (02 §3 intent) |
|---|---|---|
| P50 — 1 | 65 ms — under | 50 ms — under |
| P95 — 3 | 133 ms — **breach** | 100 ms — **breach** |
| P99 — 6 | 235 ms — **breach** | 175 ms — **breach** |
| max — 10 | 371 ms — **breach** | 275 ms — **breach** |

It breached under **both** readings, so the finding never rested on the sequential implementation.

**Decision.**

1. **NFR-P-001 is re-scoped to the user-perceived unit.** The targets attach to the two holds a
   user actually waits through — the **input-lane hold** (before dispatch) and each
   **per-sentence hold** (boundary arrival → release). A hold is the delay before *that* sentence
   appears, which is what ADR-002's sentence-level interception buys and therefore the unit a
   latency guarantee can honestly cover.
2. **The per-request sum keeps being published, and loses only its target.** It is renamed
   `total_attributable_overhead_ms` — same normative formula as `gateway_overhead_ms` (06 §4),
   new name because the old one read as *the* headline figure and it is no longer the targeted
   one. It appears in every latency report and in `latency_json`. **Nothing is withdrawn from
   publication by this ADR.**
3. **`added_time_to_last_byte_ms` is added as a measured, untargeted row** — the honest
   end-to-end quantity, and the one a user's stopwatch would agree with. Untargeted because it
   contains upstream token cadence, which the gateway does not control. *(Amendment 1 keeps this
   row and moves where it is measured: 06 §4's benchmark client, not `latency_json`. The
   gateway has no client vantage, which this item assumed without checking.)*
4. **The per-sentence lane goes parallel when Tier-2 lands** (below), not before.

### Derivation of the targets — from the documented budgets, not from convenience

Composed from `BUDGETS_MS` and `LANES` under the parallel execution model of (4). Every figure
below is arithmetic over the 04 §2 budgets plus the 5 ms engine line this ADR sets; none is a
measurement, because the detectors it turns on do not exist. The engine line is the one term with
a measurement *beside* it (below) rather than only a budget.

Two non-detector terms are inside every row, because 06 §4 puts them inside the hold: the
**engine step** (`cp.policy.evaluate` + `cp.action.apply`, 5 ms combined) and, on output holds
only, **enrichment** (10 ms aggregate per sentence). Both were gaps when this ADR was first
written; both are now ruled and are carried in the arithmetic rather than absorbed by it.

| Hold | Documented composition | Worst case |
|---|---|---|
| Input lane | `max(tier1_pii 2, tier1_blocklist 2, tier2_injection 25, cost_budget 1, loop_guard 1)` + engine 5 | **30 ms** |
| Per-sentence, typical | `max(tier1_pii 2, tier1_blocklist 2, tier2_toxicity 25, numeric_claims 5)` + engine 5 — `rag_grounding` skipped without context docs | **30 ms** |
| Per-sentence, typical, enriched | `+ entity_enricher 10` (**aggregate per sentence**, 04 §2.2) | **40 ms** |
| Per-sentence, with context docs | `max(30, rag_grounding 30)` + enrichment 10 + engine 5 | **45 ms** → **70 ms** (Amendment 3) |
| Per-sentence, `on_sampled` boundary compare | `max(30, fast_consistency 60)` + enrichment 10 + engine 5 | **75 ms** → **100 ms**, untargeted (Amendment 3) |

The enrichment term is now **flat, not `10k`** — that is the whole effect of the 04 §2.2 cap. The
input lane carries no enrichment term at all: enrichment is conditional on a span-bearing
`hallucination.*` signal (04 §2.2) and no input-lane detector emits one.

**Superseded by Amendment 3 — pool users serialize, so two of these rows were wrong.** The
paragraph below is kept as ruled; read it with the amendment's table beside it.

**Every row fits, and one adjacency is stated rather than glossed.** Worst cases 30 / 40 / 45 / 75
against P50 < 40 and P99 < 100: the input lane clears its P50 by 10 ms and its P99 by 20; the
per-sentence P99 clears by 25 ms at the `on_sampled` worst case. The **enriched typical row lands
at exactly 40.0 ms against a strict `< 40`** — zero margin. It is not a P50 breach, because the
P50 target judges the *median* hold and a median sentence is unenriched (enrichment requires a
span-bearing `hallucination.*` signal on that sentence; if the median sentence had one, over half
of all traffic would be hallucination-flagged). But it is the first place this derivation would
break under a budget change, so it is written down where a future budget edit will hit it.

**Targets:** input-lane hold **P50 < 40 ms, P99 < 50 ms**; per-sentence hold **P50 < 40 ms,
P99 < 100 ms**. Streaming pipelines only, as before. *(Amendment 2 scopes the input-lane
target to single-window inputs. Amendment 3 scopes the per-sentence P99 to holds with at most
one pool user besides enrichment and `rag_grounding`: the two `on_sampled` compositions it
re-derives, at 100 and 130 ms, are published **untargeted**.)*

Why these and not others. The input lane's *detector* composition is 25 ms and `tier2_injection`
runs on *every* request, so its P50 cannot be set below 25 — 30 ms once the engine step is
included, and 40/50 clears that without being loose enough to hide a regression. The per-sentence
P50 of 40 ms covers the typical 30 ms composition; the P99 of 100 ms covers the `on_sampled` worst
case of 75 ms.

**The two gaps this derivation surfaced are now closed** (ruled 2026-08-27). They are kept here
with their original finding intact, because the reason each was *logged rather than solved in
place* is the same reason the fit above is trustworthy: a target is not allowed to invent the
bound that makes it fit.

- **`entity_enricher` was unbounded per sentence** — at 10 ms per enriched span, `60 + 10k`
  crossed the 100 ms P99 at **k = 4**, so the per-sentence target was satisfiable only under a
  bound no doc stated. **Closed by the 04 §2.2 cap** (M-18): 10 ms *aggregate* per sentence, skip
  remaining spans on exceed, `cp_enrichment_skipped_total`. The fit above is therefore
  **unconditional** — the derivation no longer rests on an assumption about `k`, because `k` no
  longer enters the arithmetic. Ruled in 04 §2.2 rather than here, and after the composition it
  affects was already published, so the cap is a detector-budget decision that this target had to
  live with — not one written to make this target fit.
- **Policy evaluate + action apply were unbudgeted.** 06 §4 puts them inside the hold ("detector
  wait + policy + action") but 04 §2 budgets only detectors. **Closed with a combined 5 ms budget
  line** for `cp.policy.evaluate` + `cp.action.apply` (M-19), carried in every row of the table
  above. Both are deterministic work — a severity lookup over converged signals and a template
  transform — so a budget two orders of magnitude above the measurement is a tripwire, not an
  allowance.

  **Measured, now that the spans are actually emitted: combined P50 0.019 ms, P95 0.039 ms,
  P99 0.095 ms (n = 300, `reports/latency_report.md`)** — against the 5 ms budget, ~50x headroom
  at P99. Two caveats on that figure, both of which make it conservative rather than flattering:
  it is a per-*request* sum across every unit in the response (`merge_latency` accumulates), so it
  is an **upper bound** on any single hold's engine cost; and it is measured at the current
  detector set, where the engine converges few signals. A breach needs no new mechanism to
  surface — it lands in the per-hold series and trips `--check`, exactly as a detector breach
  does.

  Worth recording that these three spans (`cp.ingress` included) were in the 05 §5 vocabulary but
  **written by no code** when this ADR was first accepted, so the original "measured today at well
  under 1 ms" had no measurement behind it. The figure above is the first real one.

### Sampled consistency (04 §2.3) — explicitly bounded, not assumed away

`consistency: on_sampled` is the only mode that puts `fast_consistency` inside a per-sentence
hold, and its own **skip-on-lag** semantics bound it: the comparison happens *only if* sample-2
has ≥ 70% of the primary's released+buffered length, and otherwise the sentence proceeds without
the signal, audited `meta.consistency:"lagged"` and counted in `cp_consistency_lagged_total`. So
the 60 ms term is **paid only when the sample is actually ready** — a lagging sample costs the
alignment check, not the comparison. This is why the P99 target is set at the composition that
term dominates (75 ms, per the table above) rather than at some multiple of it: the mode cannot
queue up compares, it drops them.

`consistency: on` (UC-3, `streaming: false`) is untouched — it compares once, pre-delivery, in a
non-streaming pipeline that NFR-P-001 never covered.

### Execution model: sequential now, parallel at Tier-2

02 §3 has always said per-sentence detectors run concurrently (`asyncio.gather`).
`pipeline.run_lane` is sequential, and that was a *measurement* decision documented at
`run_lane`'s docstring records why: with three regex detectors at ~0.2 ms each, `gather` cannot overlap CPU-bound
work on one event loop and would only make each detector's recorded `latency_ms` include the
others'.

**Ruling — the trigger is the first Tier-2 detector landing.** At that point composition becomes
`~max` instead of `sum`, the concurrency is real (a transformer forward pass releases the loop),
and per-detector spans stay honest because `gather` preserves per-task timing. Until then the
sequential implementation **stays as-is**: switching now would change the conditions under which
the shipped measurement was taken, for no benefit at 0.2 ms per detector.

### Anti-laundering record (verbatim, as ruled)

This amendment moves a target, so the reasons it is not target-gaming are recorded rather than
left to inference:

- **It lands BEFORE any Tier-2 measurement exists.** `tier2_toxicity` and `tier2_injection` are
  unimplemented; nothing has been run against the old target and missed it.
- **The motivating evidence is a projection, preserved above in full** — including the rows that
  breach, and under both execution models rather than only the unfavourable one.
- **The old per-request quantity continues to be published** in every latency report as
  `total_attributable_overhead_ms`. It loses its target, not its visibility.
- **This is categorically distinct from ADR-026 §5**, which bars moving a target that a
  measurement has already missed. That bar is **untouched**: SL-1 (`tier1_pii` recall 0.8852 vs
  the 0.95 target) remains **unmet and unmoved**, and ADR-026 §5's single re-measurement stays
  consumed. The distinction is *when the number arrives* — a target respecified before any
  measurement is a specification decision; one respecified after a miss is laundering.

**Trade-off accepted.** A per-request guarantee is genuinely weaker: a 10-segment response may
hold ~600 ms in total while every individual sentence passes its target. That total is published
untargeted precisely so the weakening is legible rather than hidden, and
`added_time_to_last_byte_ms` gives the end-to-end figure alongside it.

### Implementation status — the contract lands now, the instrumentation with it

**Updated 2026-08-27 — the two targeted series now land; two untargeted quantities still do not.**

`input_hold_ms` and `sentence_holds_ms` are **emitted** on both delivery paths, so NFR-P-001 has
a real verdict rather than the third state. The input hold is `cp.ingress` + input-lane time
before dispatch, per 06 §4; the per-sentence series carries one entry per released unit, and on a
non-streaming pipeline one entry for the buffered response, which M-11 makes the unit there.
`--check` gates the two series and names the breaching subject and percentile; the gated
population is **holds, not requests** — a 10-segment response contributes 10 samples, which is
what a per-hold target means.

**Updated 2026-08-28 — the rename landed; one untargeted row remains.** `app.py`, `spans.py`'s
enforced vocabulary and the single 06 §4 formula implementation all carry
`total_attributable_overhead_ms`, and `pipeline.gateway_overhead_ms` was renamed **with** the key:
a helper still bearing the old name while writing the new one is precisely the drift **M-20**
records. The metric `cp_gateway_overhead_ms` is deliberately **not** renamed (05 §5) — renaming it
would orphan history for a figure whose definition did not change.

**Updated 2026-08-28 — M-20's remainder closes by re-siting, not by emission.** See
**Amendment 1**: `added_time_to_last_byte_ms` is not a `latency_json` key, because the gateway
cannot occupy the vantage its definition names. It stays published, from the benchmark client.

The gap that let the rename sit undetected is closed rather than noted: `latency_json` key names
are still not doc-parsed (`tests/test_telemetry.py` parses the 05 §5 **span** and **metric**
tables, and these keys are neither), so
`tests/review/test_checkpoint3_latency_keys.py` now asserts the doc and the enforced vocabulary
agree **in both directions** for the remaining key — re-pointed by Amendment 1 onto the re-siting,
since "documented but not yet emitted" stopped being a state that key can be in. That test is what fired on
this rename instead of letting the code drift from the persisted rows — the outcome a tripwire
exists for — and it was re-pointed rather than deleted (ADR-031 consequence 5's rule, applied to a
different tripwire for the same reason).

What the original caveat here said, kept because it is the reasoning the fix had to satisfy:
NFR-P-001 was `not measured` from this ADR until the instrumentation landed — the old per-request
target withdrawn, the new per-hold targets with no series yet, which is the third state
M-10 / ADR-027 Amendment 1 insists on: not "met", not "failed". A benchmark that kept gating the
sum would have reported a target the docs no longer contain; one that silently gated nothing would
have read as a pass. `nfr_p001_measurable()` decides which of those the report prints, so the
third state remains reachable — it is what a run with no streaming traffic still renders.

This is the ordinary spec-first order in this repo (docs precede code by design, AGENTS.md §2), so
the doc was not "ahead of" the code in a way that needed reconciling — but the **05 §5 vocabulary
is enforced at the write path** by `check_latency_keys`, so a key is documented as the contract and
marked not-yet-emitted until `app.py` writes it. `sentence_holds_ms` is the one **list** in that
vocabulary, and its shape is enforced there too: a scalar under it would read as a
single-sentence request, and a list under a scalar key would surface as a `TypeError` inside a
percentile far from the cause.

**Docs touched:** 01 (NFR-P-001 row), 02 §3 (parallel-at-Tier-2 trigger), 05 §3/§5 (`latency_json`
vocabulary: the rename plus the two new series), 06 §4 (formula gains the per-hold series and the
last-byte row; the sum retained under its new name), 08 (deviation closed; M-18/M-19 logged).

### Amendment 1 — 2026-08-28: `added_time_to_last_byte_ms` is a benchmark-client quantity, not a `latency_json` key (resolves `[D1-added-time-to-last-byte-has-no-server-side-vantage]`)

Item 3 above added this row and sited it in `latency_json`, a column the **gateway** writes. Its
own definition opens "client-observed". The gateway is not a client, and the deviation that found
this closed all four ways it might still have been reachable:

1. **A completed ASGI `send()` is handed-to-transport, not client-received.** Whatever the
   streaming generator measures after its final `yield` is a handoff delta. Publishing that under
   a name promising a client stopwatch overstates what was measured (AGENTS.md §7) — and it would
   overstate it *invisibly*, since the number is plausible either way.
2. **The buffered path writes the record before the response exists.** `app.py`'s audit write
   precedes `return JSONResponse(...)`, an ordering **M-13** established deliberately so a crash
   after content release still leaves a row.
3. **Deferring the write to obtain the figure reopens M-13.** The gap that ordering closed is
   exactly a request whose record is written after delivery and therefore not at all.
4. **The table is insert-only.** No `UPDATE audit_records` exists in `controlplane/`, and
   `record_status` is a crash marker, not a second phase — so there is no later moment in which a
   post-delivery figure could arrive.

**Ruling.** The figure is **re-sited, not withdrawn.** Nothing leaves publication:

1. **06 §4 becomes its normative home**, defined as a quantity of the benchmark client — the one
   process in this repo that genuinely holds the vantage. **Withdrawn from 05 §3/§5**, whose
   vocabulary is enforced at the write path, so the withdrawal is mechanical rather than editorial:
   `check_latency_keys` refuses the key.
2. **It aliases and absorbs `reference_delta_ms`**, the `wall − upstream` row `eval/bench_latency.py`
   already computed, rather than joining it as a second series. One subtraction under two names
   invites the reading that one of them is the uncontaminated version. Both of that row's caveats
   travel with the name and are non-negotiable: it is an **upper bound** (it carries `TestClient`
   ASGI transport cost a real client would not pay) and it is **never the headline number**.
3. **M-20's remainder closes here.** The rename landed in `ab06917`; this was the rest, and it
   closes as a specification correction rather than as an emission — which is the honest outcome,
   since the emission was never constructible.

**Why an amendment and not a new ADR.** It reverses no decision of ADR-030 — the row is still
published, still untargeted, still the end-to-end figure the trade-off paragraph leans on. What
moves is *which process measures it*, which ADR-030 assumed rather than chose. Recording that as a
separate ADR would leave item 3 reading correct in isolation.

**Not a target movement (ADR-026 §5).** This row never had a target. NFR-P-001's verdict is
untouched, and SL-1 stays unmet and unmoved.

**Consequence — the tripwire fired and was re-pointed for the second time.**
`tests/review/test_checkpoint3_latency_keys.py` asserted "05 §5 says not-yet-emitted" against
"absent from the enforced vocabulary". This amendment voids that premise rather than satisfying it,
so the test now pins the re-siting in both directions: the enforced vocabulary must not grow the key
back, **and** 06 §4 must keep defining it. Re-pointed rather than deleted, per ADR-031
consequence 5's rule — a tripwire's job outlives the transition it caught.

**Docs touched:** 05 §3/§4/§5 (key withdrawn from `latency_json`, the DDL comment and the record
example), 06 §4 (normative home; absorbs the reference row), 01 (NFR-P-001 row notes the vantage),
08 (deviation closed; M-20 closed).

---

### Amendment 2 — 2026-08-28: the input-hold target is scoped to single-window inputs; multi-window holds are an untargeted bucketed series (resolves `[D1-input-hold-target-cannot-survive-multi-window-injection]`)

**Status:** Accepted 2026-08-28. Recommendation A of the filed report, approved.

**This amendment formalizes a clause that was issued and then lost in transcription.** The
adjudication that produced **ADR-032** carried, as its item 3, the same scoping this amendment now
records — and it is absent from ADR-032's committed text. Verified rather than asserted: ADR-032
mentions `NFR-P-001` nowhere, and the strings `input_hold`, `input hold` and `input-lane` appear in
it only once, incidentally, inside its pre-dispatch clause ("the cost is therefore paid on the input
lane"). Its "Docs touched" line names 01's **NFR-P-002** row, 04 §2, 06 §4 and 08 — the input-hold
*target* is untouched. So the deviation this amendment closes was a real doc-versus-doc
contradiction in the committed record, not a re-litigation: what the ruling decided and what the
repo said had come apart.

**Process note, recorded because it generalises.** When an issued adjudication clause is absent from
the ADR transcribed from it, that is **drift**, and it is the same class of defect as a stale number
in a report: the decision of record and the decision actually taken disagree, and only one of them
is enforceable. Diff the issued ruling against the transcribed ADR **before** closing the deviation
it resolves. The cost of not doing so is exactly what happened here — a scoping decision that had
already been made was re-derived from scratch one detector later, by a reader who could only see the
committed text.

### The scoping

- **NFR-P-001's input-lane hold (P50 < 40 ms, P99 < 50 ms) is scoped to single-window inputs**
  (≤ 104 tokens, the ADR-032 window). There it is the derivation ADR-030 built: a 30 ms worst case
  whose dominant term is `tier2_injection`, measured at **12.59 ms P99** for one window — the
  worst of both columns at the 1-window rung (sequential 11.87), re-derived from the clean artifact
  by ADR-032 Correction 1; the withdrawn run read 13.01.
- **Multi-window input holds are published as an untargeted, window-count-bucketed series.** This is
  the **third use** of the per-request-sum precedent — `total_attributable_overhead_ms` was the
  first, ADR-032's NFR-P-002 window series the second — and the shape is deliberately identical, so
  a reader meets one convention rather than three.
- **`eval/bench_latency --check` gates only the single-window population.** The bucketed series is
  reported beside it with no verdict attached. A gate that stayed red on every long prompt would be
  indistinguishable from a broken gate, which is the failure mode the filed report's option B names.

### Anti-laundering record

This scopes a target, so it carries the same record ADR-030 did, and for the same reason.

**Filed and ruled from a projection over ADR-032's measured table, BEFORE the detector exists.**
That is the fact that distinguishes it from the laundering **ADR-026 §5** bars. §5 forbids moving a
target so that a measurement which *missed* it passes. Nothing has missed this target: `tier2_injection`
is not written, so no measurement of it exists to be rescued. What is projected is the
**composition** — that a multi-window scan lands inside `input_hold_ms` by 06 §4's own definition —
and the cost is not projected at all, it is ADR-032's measured series.

This is the precedent `[D1-tier2-budgets-cannot-coexist-with-nfr-p-001]` established and ADR-030
recorded: a specification decision taken before the code can embarrass it is a front-door
respecification, and the same decision taken afterwards is a moved goalpost. Ruling it now is the
last moment that distinction is available.

**SL-1 remains unmet and unmoved**, and ADR-026 §5's single re-measurement stays consumed. Nothing
in this amendment touches `tier1_pii`'s recall target or any figure already published.

### Consequences

1. `01 §5`'s NFR-P-001 row gains the single-window scope on its input-lane figure, worded to match
   the scope ADR-032 gave NFR-P-002 so the two read as one convention.
2. `06 §4` gains the window-count-bucketed `input_hold_ms` series beside the targeted one, and
   states that `--check` gates the single-window population only.
3. `eval/bench_latency.py` emits the bucketed series and narrows its NFR-P-001 assertion to
   single-window holds.
4. The deviation closes citing this amendment.

**Docs touched:** 01 §5 (NFR-P-001 input-lane scope), 06 §4 (the bucketed series + the `--check`
narrowing), 08 (deviation closed).

### Amendment 3 — 2026-08-30: pool users **serialize**, so a hold composes as `max(Σ pool, max(non-pool)) + engine` (resolves `[D1-per-hold-derivation-maxes-detectors-that-share-one-worker]`)

**Status:** Accepted 2026-08-30. Recommendation **A** of the filed report, approved: re-derive the
table with pool users composed as `sum`, keep `max_workers=1`, correct the `~max` prose.

**Context.** ADR-030's derivation composes every hold as `max(...)` over its lane. ADR-034 Part A,
ruled one day later, binds five *named* model detectors — `tier2_injection`, `tier2_toxicity`,
`rag_grounding`, `fast_consistency`'s embedding comparison, `entity_enricher` — to one shared
`max_workers=1` pool, and calls that setting load-bearing because it preserves the
one-inference-at-a-time conditions **SL-5** was measured under. Both cannot hold on a lane carrying
two pool users, and `LANES[output_sentence]` already names two of the five.

### Decision — one composition rule, stated as arithmetic

A hold is **`max(Σ pool users, max(non-pool detectors)) + engine 5`**.

Pool users **sum** because one worker serializes them. Non-pool detectors **overlap** the pool work
rather than adding to it: a forward pass in a worker thread releases the event loop, so the regex
emitters run inside the model's wall time. Enrichment carries no separate term in this rule — it is
a pool user (04 §2.2's 10 ms aggregate) and enters the Σ, which is why the rows that already
treated it additively do not move.

| Hold | Pool users (serialize) | Non-pool (overlap) | Worst case | Against the target |
|---|---|---|---|---|
| Input lane | `tier2_injection` 25 | 2 | **30 ms** | P99 < 50 — fits |
| Per-sentence, typical | `tier2_toxicity` 25 | 5 | **30 ms** | P50 < 40 — fits |
| Per-sentence, typical, enriched | 25 + `entity_enricher` 10 = 35 | 5 | **40 ms** | P50 < 40 — **zero margin, unchanged** |
| Per-sentence, with context docs | 25 + `rag_grounding` 30 + `entity_enricher` 10 = 65 | 5 | **70 ms** *(was 45)* | P99 < 100 — fits, 30 ms margin |
| Per-sentence, `on_sampled`, no context | 25 + `fast_consistency` 60 + `entity_enricher` 10 = 95 | 5 | **100 ms** *(was 75)* | **untargeted** (below) |
| Per-sentence, `on_sampled` + context | 25 + 30 + 60 + 10 = 125 | 5 | **130 ms** *(newly tabulated)* | **untargeted** (below) |

Three rows are unchanged, which is not a coincidence and is the reason the fix is narrow: a hold
with **one** pool user has nothing to serialize against, so `Σ` and `max` agree. Only rows 4-6
carry two or more.

**Row 6 was never tabulated.** ADR-030's table had no `on_sampled`-with-context-docs row at all, so
the worst case it published (75 ms) was not the worst case its own budgets allow. It is tabulated
here rather than left implicit — an omitted row is how a derivation stays fitting.

### Target disposition — the reachable rows fit, and the two that do not lose their target

1. **No target moves.** Input-lane P50 < 40 / P99 < 50 and per-sentence P50 < 40 / P99 < 100 all
   stand at their ADR-030 values. This was not the expected outcome when the ruling was issued, and
   it is stated plainly rather than dressed as a vindication: it holds only because the rows that
   breach are the two `fast_consistency` rows, and item 3 below makes them unreachable.
2. **The per-sentence P99's *scope* narrows.** It covers holds composed of at most one pool user
   plus enrichment plus `rag_grounding` — i.e. the reachable set. The two `on_sampled` rows
   (100 ms, 130 ms) are **published untargeted**, on the per-request-sum precedent this ADR
   established: a quantity that cannot honestly carry a target keeps its visibility and loses its
   target, rather than the target being loosened to admit it.
3. **`fast_consistency` is cut to roadmap** (same sweep, 2026-08-30), so rows 5-6 describe no
   shipped path today. **This is not what resolves them.** The cut is a scope decision and the
   untargeted publication is a specification one; landing `fast_consistency` later re-arms both
   rows at 100 and 130 ms against P99 < 100. Recording the untargeted status now is what keeps that
   from arriving as a surprise, so the rows stay in the table with their arithmetic intact.
4. **The enriched-typical row's zero margin is untouched** — still exactly 40.0 against a strict
   `< 40`, still argued not to be a P50 breach on the grounds that a median sentence is unenriched.
   Amendment 3 neither improves nor worsens it; it is repeated here only so a reader of the new
   table does not think the adjacency was resolved.

### Anti-laundering record

This amendment changes the scope of a target, so the same record ADR-030 and Amendment 2 carried:

- **It lands BEFORE any measurement of the affected rows exists.** `tier2_toxicity`,
  `rag_grounding` and `fast_consistency` are all unimplemented at the moment of ruling; nothing has
  been run against the old figures and missed them. The re-derivation is arithmetic over 04 §2
  budgets, exactly as ADR-030's original was.
- **The correction was found by reading the contracts, not by a measurement that failed.** It was
  filed while checking whether ADR-030's table survived ADR-034 — which is the honest order.
- **Every affected row keeps being published, including the two that lose targeting and the one
  that was never tabulated.** Nothing is withdrawn from publication.
- **Distinct from ADR-026 §5**, which bars moving a target a measurement has already missed. That
  bar is untouched: SL-1 (`tier1_pii` recall 0.8852 vs 0.95) remains unmet and unmoved, and ADR-026
  §5's single re-measurement stays consumed.
- **The old figures are not quietly overwritten.** 45 and 75 appear above as *(was 45)* / *(was 75)*
  so the movement is legible in the table itself.

### The `~max` prose is corrected where it lives

02 §4 promised that at Tier-2 "lane composition becomes `~max` rather than `sum`". That is true only
of the lane shape the trigger was written for — one pool user plus regex emitters. Both sites (02 §4
and this ADR's concurrency-trigger ruling) now state the two-part rule. The trigger itself is
**unchanged and still correct**: it fires on the first Tier-2 detector, and the concurrency it buys
is real for non-pool detectors.

The D1 report's `gather` diagnostics (model + 2 regex at 1.04x; model + model at 0.98x) are
**NOT citable** — `load1` 2.39 against `QUIET_LOAD1_MAX` 1.0 (06 §8) — and this amendment does not
rest on them. It rests on `max_workers=1`, which ADR-034 Part A rules load-bearing.

### Consequence — the derivation gains the guard it never had

The report's second finding was that **nothing in the repo detects this**: ADR-030's table had no
source artifact and no test, so two rows were arithmetically wrong against a later ADR while CI was
green. `eval.check_derivations` now re-derives this table from `BUDGETS_MS` and the pool-user set,
which makes the composition rule executable rather than prose. A future budget edit or a sixth pool
user moves the table or fails the gate.

**Docs touched:** 03 (this amendment), 02 §4 (the `~max` sentence), 04 §2 rule (a) (the composition
rule stated where the budgets live), 08 (deviation closed), README (NFR-P-001 projection row),
`eval/bench_latency.py` (the projection caveat now names the ruling instead of the open deviation).

---

## ADR-031 — Tier-2 checkpoints: `madhurjindal/Jailbreak-Detector` + `martin-ha/toxic-comment-model`, on ONNX Runtime (resolves Q-04)

**Status:** Accepted 2026-08-28. Closes **Q-04**, deferred 2026-08-24 pending an NFR-P-002 latency
spike. Q-04's own doc-rot note directs the result to "the next free ADR number" — ADR-011 was
already taken by the `privacy.person` producer decision — which is this one.

**Context.** 04 §2 gives both Tier-2 detectors a **<25 ms** budget (NFR-P-002) and specifies the
implementation as "small transformer, **CPU/ONNX**". No checkpoint was named. `eval/spike_tier2_models.py`
measures six published candidates — three per role — across three backends, five lengths and two
thread settings, on this hardware, and reports P50/P95/P99/max per cell.

**Selection is on latency only.** The spike never reads a corpus *label*, and no candidate was
scored for accuracy. That is deliberate: the eval corpus is frozen (06 §1) and choosing a model by
its performance on the same fixtures that later measure it is harness-fitting. Accuracy is measured
once, blind, by 06 §3 — on whichever checkpoint this ADR binds.

### Decision

| Role | Checkpoint | Params | Backend |
|---|---|---|---|
| `tier2_injection` | `madhurjindal/Jailbreak-Detector` | 65.8 M | ONNX Runtime, dynamic int8 |
| `tier2_toxicity` | `martin-ha/toxic-comment-model` | 67.0 M | ONNX Runtime, dynamic int8 |

Both emit a two-class probability, which is what 04 §2's `score = model prob` and
`score_kind="detection"` (ADR-012) require. `martin-ha` is `{non-toxic, toxic}`, so the
moderate/high split comes from the 04 §2 internal cutoffs (0.5/0.8, overridable via
`detector_params`) rather than from model classes — `unitary/toxic-bert`'s six-way head would have
supplied its own taxonomy and 04 §2 does not ask for one.

### Measurements

Ryzen 5 5600H (12 logical CPUs), Linux 7.1.2, Python 3.14.6, torch 2.13.0+cpu,
onnxruntime 1.29.0. `n=50` per cell (`n=30` crossover, `n=20` truncation probe). Raw:
`reports/spike_tier2_models.json`, `reports/spike_tier2_crossover.json`,
`reports/spike_tier2_crossover_runnerup.json`.

**1. Eager PyTorch never satisfies the budget across the reachable range** — at 6 threads, every
candidate breaches at the segmenter cap, and four breach at corpus-median length. This is **not a
D3**: eager was never the specified backend. 02 §8 names "one small **ONNX**/transformers
classifier" and 04 §2 says "CPU/ONNX", so measuring eager and finding it short measures something
the docs never claimed.

**2. Under ONNX Runtime the budget holds, with margin, at every length each stage can deliver**
(6 threads, int8, P50 / P99 ms):

| Role | Checkpoint | corpus P50 | corpus max | segmenter cap (240 ch) |
|---|---|---|---|---|
| injection | **madhurjindal** 65.8 M | 4.51 / 5.21 | 4.96 / 5.32 | 7.13 / 7.60 |
| injection | jackhhao 109.5 M | 7.32 / 8.17 | 9.20 / 10.55 | 13.34 / 15.48 |
| injection | protectai/deberta 184.4 M | 13.14 / 14.53 | 15.05 / 15.65 | 20.40 / 21.31 |
| toxicity | **martin-ha** 67.0 M | 2.74 / 2.91 | 4.07 / 4.92 | 9.04 / 9.93 |
| toxicity | unitary 109.5 M | 5.85 / 6.74 | 8.35 / 9.10 | 18.32 / 19.28 |
| toxicity | s-nlp 124.6 M | 6.89 / 13.91 | 10.26 / 12.82 | 20.41 / **28.31** |

fp32 also fits for both picks at output lengths (madhurjindal 13.84/14.45 at the cap; martin-ha
17.22/17.99), so int8 is chosen for **headroom**, not necessity — see the disclosure below.

**3. `protectai/deberta-v3-base-prompt-injection-v2` is rejected despite a FITS row.** It is the
only purpose-built injection model in the set, so it was probed a second time on the crossover
ladder: at 240 characters it measured **27.08 / 36.69 ms — BREACH**, against 20.40 / 21.31 FITS in
the sweep. The two runs compose 240 characters differently (whole corpus units vs hard-truncated
cycling), yielding 50 vs 61 tokens, and at 184 M parameters that 11-token difference crosses the
budget. A checkpoint whose verdict flips on tokenizer detail is **at** the line, not inside it.
Recorded rather than averaged away: the disagreement is the finding.

**4. Population correctness — a methodology error caught and corrected before any number here.**
The first sweep bucketed lengths over the *pooled* corpus (n=280), which put a 348-character
`kind:"conversation"` text in the longest bucket. No Tier-2 detector can receive it: the
conversation stage runs only `conv_tracker`. Every breach verdict on the surviving candidates came
from a length the architecture cannot deliver. Buckets are now **stage-scoped** to the 04 §2 Stage
column — `input` texts for injection, `output` texts segmented by the gateway's own `Segmentation`
for toxicity (imported, not reimplemented: two definitions of "one sentence" would eventually
disagree). Correcting it flipped `madhurjindal` from FITS to BREACH on eager, because the median
`input` case tokenizes at **1.94 chars/token** against **4.19** for the median output sentence —
62 characters becoming 32 tokens where 67 characters of prose become 16. Letter-spacing *is* the
evasion, so bucketing injection payloads by character count understates their cost. The density is
not uniform across the lane (1.94–4.31 ch/tok over the reachable input buckets), which is the
reason the buckets carry a measured `tokens` field rather than a conversion factor.

**5. Thread sensitivity is a real exposure, not a footnote.** At **1 thread** both picks breach at
the segmenter cap — madhurjindal **25.90 P50 / 26.20 P99**, martin-ha **34.48 / 35.50** — while
still fitting at corpus-typical lengths (17.81 / 10.62 P50). The budgets above are measured with 6 threads available to one inference. Under concurrent
load, per-request parallelism falls, and NFR-P-002 has no stated concurrency assumption. Logged as
**SL-5**; not tuned away and not treated as a passing figure.

**6. Int8 accuracy disclosure.** Dynamic quantization perturbs logits — ONNX fp32 reproduces torch
exactly, int8 differs in the third significant digit (3.002 vs 2.974 on a probe input). So a
shipped int8 detector's accuracy is **not** the published checkpoint's reported accuracy, and no
number from a model card may be presented as ours. 06 §3's blind eval measures what actually ships.

### Consequences

1. `controlplane/detectors/tier2_classifiers.py` loses its `STUB(phase-1-scaffold, Q-04 deferred)`
   and binds these two ids.
2. **Dependencies** (02 §8 "New deps require an ADR note"): the `ml` extra gains
   `onnxruntime==1.29.0` and an explicit `transformers==4.57.6` pin — transitive through
   `sentence-transformers` today, but a direct import once these detectors exist, and an unpinned
   direct dependency is how 4.57.6 silently became 4.53.3 once already this phase. Export tooling
   (`onnx`, `onnxscript`) is **dev-only**: it builds the graph, it does not serve it.
   `optimum` is deliberately **absent** — `optimum[onnxruntime]==1.27.0` fails on torch 2.13
   (`_attention_scale` import) and downgrades transformers as a side effect. `torch.onnx.export`
   plus `onnxruntime.quantization` covers the same ground with no version conflict.
3. Where the served graph comes from — exported on first use and cached, versus checked in — is an
   **implementation** decision inside this contract, not an ADR: a committed binary graph has
   provenance nobody can audit, so first-use export is the default unless startup cost forbids it.
4. **The budget does not hold across the full input range**, and the input stage applies no length
   cap. Filed as `[D3-tier2-injection-budget-cannot-hold-on-unbounded-input]` — this ADR binds the
   checkpoints, that deviation decides the input bound, and the pick does not depend on the ruling
   (`madhurjindal` is fastest at every length measured).
5. `tests/test_gateway_app.py::test_ovlp01_is_not_yet_wired` and
   `tests/test_fault_injection.py::test_tier2_is_not_yet_injectable` are both tripwires that fire
   when a Tier-2 detector lands. Landing these detectors must re-point them in the same commit, not
   delete them.

**Docs touched:** 08 (Q-04 closed with the pick; SL-5 added; the deviation filed), `pyproject.toml`
(the §2 dependency note), 04 §2 unchanged — the registry rows already say CPU/ONNX and this ADR
fills in which checkpoint.

---

## ADR-032 — `tier2_injection` scores the whole input as strided windows; the multi-window cost is published, not truncated away (resolves `[D3-tier2-injection-budget-cannot-hold-on-unbounded-input]` and `[D3-full-coverage-windows-cost-600ms-at-the-policy-bound]`)

**Status:** Accepted 2026-08-28.
**Context.** Two deviations, one subject. The first measured `tier2_injection`'s <25 ms budget
(04 §2, NFR-P-002) breaching between 400 and 600 characters, with nothing in the gateway bounding
input length and the tokenizer silently truncating at 512 tokens — so an injection payload past
token 512 was never scored at all. Prefix truncation (its option A, the recommendation) was
**overruled**: a documented "we score the first N tokens" is an evasion recipe, and the
interception guarantee is the product. Full coverage via strided windows was ruled instead, with
an explicit stop condition: *measure batched inference at the policy bound before concluding
anything, and if full coverage lands in the >500 ms class, stop and report rather than truncate
silently.* It did land there, which produced the second deviation. This ADR is that ruling
completed, with the measured cost accepted.

### Decision

1. **Window geometry: 104 tokens, overlap 26, step 76.** Every window is scored; no input is
   skipped and no prefix is privileged. 104 is the largest window that fits the budget as a
   single call, and small windows are *more* token-efficient than large ones — measured cost per
   content token is **0.111 ms** at 104 tokens against **0.187 ms** at 512, because attention is
   quadratic in sequence length. So no window geometry rescues the bound: full coverage of 4000
   tokens is inherently ~53 × ~12 ms. The overlap exists so a payload straddling a boundary is
   whole in some window.
2. **Aggregation is MAX over windows**, with `window_count` and the index of the max-scoring
   window in the signal meta. MAX and not mean: a mean over 53 windows dilutes a single malicious
   window below any threshold, which is padding-as-evasion by arithmetic.
3. **The position is pre-dispatch, and that is not negotiable.** Optimistic dispatch — call the
   provider while scoring — would deliver the payload upstream, which is the exact event the gate
   exists to prevent. The cost is therefore paid on the input lane, buffered, before the provider
   is called.
4. **`budget.per_request_max_tokens` is the escape valve, in policy rather than code.** A pipeline
   needing a hard input-latency ceiling lowers its own value; one needing 4000-token prompts
   raises it and accepts the published latency. 04 §9 puts thresholds in per-use-case config, and
   this is one.

### Measurement outcome — the ~600 ms bound case is accepted and published

`eval/spike_window_latency.py`, raw in `reports/spike_window_latency.json`. Ryzen 5 5600H
(12 logical CPUs), Linux 7.1.2, Python 3.14.6, onnxruntime 1.29.0, `madhurjindal/Jailbreak-Detector`
65.8 M on ONNX Runtime **int8**, synthetic deterministic filler (no corpus text), window 104/26/76,
**53** windows at the `per_request_max_tokens: 4000` bound (Correction 1 below). Every coverage label
is **derived** from the window geometry, never read off a filler token count. Measured at code
`445ca31dd087` (clean) on a host stamped **0.6 / 0.94 / 0.98 QUIET**, n=40 per ladder point, 0
contamination signals in either thread phase. P50 / P99 ms, 6 threads:

| windows | input tokens | sequential | batched (all in one call) |
|---|---|---|---|
| 1 | 102 | 10.92 / 11.87 | 11.27 / 12.59 |
| 2 | 178 | 22.81 / 24.76 | 21.21 / 22.53 |
| 4 | 330 | 45.98 / 48.77 | 43.09 / 46.71 |
| 8 | 634 | 94.00 / 96.99 | 91.03 / 97.42 |
| 16 | 1242 | 191.74 / 229.64 | 200.38 / 208.58 |
| 32 | 2458 | 391.66 / 401.56 | 450.09 / 506.82 |
| **53** | **4054** | **655.50 / 686.25** | **794.18 / 865.42** |

**The cost is accepted, with the reason recorded rather than left to inference.** It scales with
window count, and window count scales with input length — so the guard's cost concentrates
precisely on long inputs, which is where pad-then-inject attacks live. A typical single-window
prompt pays **10.92 ms P50 / 11.87 ms P99**. The pathological 4000-token prompt pays ~0.6 s, and it
is the shape an attacker uses to dilute or outrun a scanner. Spending the most time on the most
suspicious inputs is the correct allocation, not an unfortunate one.

**Relative context, stated once and not leaned on.** A 4000-token prompt takes an LLM multiple
seconds to answer; ~0.6 s of pre-dispatch scoring is a fraction of a wait the user already has.
This is context for the magnitude, **not** a target and not a claim the cost is negligible — the
figure is published in full and untargeted so a reader can judge it themselves.

**Hardware, stated once.** All figures are CPU int8 with **6 threads** available to one inference.
**SL-5's caveat applies in full**: at **1 thread** a *single* window costs **49.77 / 50.76 ms** —
NFR-P-002 breaches even single-window — and the bound case costs **2541.99 ms**. GPU or dedicated
serving hardware is roadmap, not claimed anywhere in this repo.

**Batching does not amortise, and past a small batch it hurts.** Measured at the bound
(6 threads, 53 windows, n=40 with percentiles resolved): batch **2 → 593.60 ms P50 / 615.79 ms
P99** (the minimum in *both* statistics), batch 4 → 599.28 / 685.98, batch 8 → 625.92 / 659.89,
batch 16 → 671.86 / 729.98, batch 32 → 728.96 / 783.58, all-53-in-one-call → **793.86 / 834.28** —
*worse* than 53 separate calls at 634.76 / 687.31. The cause is measurable rather than speculative:
one window costs 49.77 ms at 1 thread and 10.92 ms at 6, a **4.56×** speedup, so ONNX Runtime
already spreads a single window across the cores. There is no idle parallelism for a batch to
exploit; a larger tensor only queues more work at a saturated pipeline. **Bound batch size: 2** —
the measured minimum, in both statistics and at both thread settings (Correction 2 below records
the decision rule and the full curve).

#### Correction 2 — 2026-08-29: the batch size is 2, decided on a curve that can resolve a P99

Resolves `[D1-batch-4-justification-falsified-at-the-corrected-bound]` (MAJOR, filed 2026-08-29 by
Correction 1's own re-measurement). The ruling approved the harness change the filing named, fixed
the decision rule in advance, and delegated only the data: **lowest bound-case P99 among b2/b4/b8
wins; ties within 5% break toward the smaller batch** (memory and latency granularity).

**Withdrawn justification, preserved.** Until this Correction the paragraph above read:

> *"Measured at the bound (6 threads, 52 windows, P50): batch **2 → 599.20 ms** (the minimum),
> batch 4 → 602.66, batch 8 → 631.45, batch 16 → 667.03, batch 32 → 727.18, all-52-in-one-call →
> **800.58** — worse than 52 separate calls at 653.65. … **Bound batch size: 4.** Not 2, though 2
> is the nominal minimum: 599.20 and 602.66 differ by 0.6%, which is inside this harness's own
> run-to-run spread, so picking the minimum over-fits one run. Batch 4 sits in the same flat basin
> with half the call count, and costs ~0.6% at 1 thread where the curve is monotonically worse."*

**The re-measured curve** (`reports/spike_batch_curve.json`, commit `960a236fefca` clean, host load
**0.96 QUIET**, `curve_reps=40`, percentiles resolved at every point, 0 contamination signals):

| batch | calls | 6thr P50 | 6thr P99 | 6thr max/P50 | 1thr P50 | 1thr P99 |
|---|---|---|---|---|---|---|
| 1 | 53 | 634.76 | 687.31 | 1.084 | 2581.78 | 2619.06 |
| **2** | **27** | **593.60** | **615.79** | **1.054** | **2566.23** | **2577.48** |
| 4 | 14 | 599.28 | 685.98 | **1.200** | 2573.76 | 2761.72 |
| 8 | 7 | 625.92 | 659.89 | 1.096 | 2606.84 | 2641.12 |
| 16 | 4 | 671.86 | 729.98 | 1.185 | 2610.19 | 2642.64 |
| 32 | 2 | 728.96 | 783.58 | 1.128 | 2690.30 | 2728.35 |
| 53 | 1 | 793.86 | 834.28 | 1.146 | 2780.62 | 2801.15 |

**Applying the rule.** At 6 threads b2 is lowest and nothing is within the 5% tie band (b8 +7.2%,
b4 +11.4%), so the pick is b2. At 1 thread b2 is lowest, b8 is inside the band at +2.5% and b4 is
outside at +7.1%; the tie-break toward the smaller batch also picks b2. **The two columns agree**,
so the decision did not require choosing a column — worth stating, because the column choice is
itself a documented judgement call elsewhere in this ADR (M-30).

**Why the original reasoning failed, precisely.** Not because 0.6% was fabricated — at n=40 the
b2→b4 **P50** gap is **+0.96%**, close to what was claimed. The flat basin is real *in medians* and
absent *in tails*: the same pair differs by **+11.4% at P99**. The old paragraph read medians
because the curve could publish nothing else — every point was n=10, where
`_percentiles_are_distinct` is False and a "p99" is `samples[8]`. So a decision about a **tail**
was taken on the only statistic the instrument could resolve, and the batch size that looked
equivalent on medians is the curve's **least stable point** (max/P50 = 1.200, the worst of seven,
reproduced from the pre-correction run's 1.135). The filing's own diagnosis — *"the instrument
cannot settle it, and that is stated rather than worked around"* — was correct, and it is also why
the interim figure that filing reported (a ~6% P50 gap, from n=10) does not reproduce at n=40:
**an n=10 median was itself too noisy to quote**, in the direction that made the case look worse
rather than better. Both are now superseded by the resolved measurement.

**No contract moves.** ADR-034's ceiling is defined as *measured envelope × 2*, so it re-derives
from whichever batch is bound; `per_unit_ms` is grounded on the **ladder's** worst per-window P99
across both columns (52.78 ms), which this correction does not touch. Verified rather than assumed:
`ceiling_ms("tier2_injection", 53)` = 5611.32 ms clears the winning envelope by **9.11×** at 6
threads and **2.18×** at 1. `tier2_injection` builds on batch 2.

**Why the ladder was not re-rolled.** Only the curve was re-measured (`--no-ladder`). Re-rolling
the ladder would have invalidated the 33 figures Correction 1 had just re-derived against it,
forcing a second full re-cite of numbers that were not in question — and each re-cite is an
opportunity for exactly the transcription defect these corrections exist to remove. The curve is
therefore its **own artifact** with its own provenance stamp: one artifact carries one
`code.commit` and one `load_at_process_start`, so splicing two runs into one file would make that
stamp certify a moment that never happened (M-33). The cost is stated rather than hidden: with no
ladder, `contamination_signals`' **LOCAL SPIKE** and **CROSS-MEASUREMENT** checks have no input and
are recorded as `contamination_checks_inapplicable` — *unmeasurable*, not passing. TAIL DISPERSION
and COLD RATIO ran and returned clean.

#### Correction — the deviation's cross-validation note is wrong in both directions

`[D3-full-coverage-windows-cost-600ms-at-the-policy-bound]` states: *"ADR-031's crossover measured
this checkpoint on 104 tokens of real, ragged text at 14.27 ms; this harness measures 104 tokens of
synthetic, padded text at 11.30 ms — same order, and the padded figure is the conservative one per
window."* Two errors, corrected here rather than by rewriting a filed report:

- **11.30 is not the conservative figure**; it is the *faster* of the two, so it understates
  per-window cost.
- **The gap is not a synthetic-vs-real content effect.** Both harnesses time `sess.run` only, with
  tokenization outside the clock (`spike_window_latency._time_calls`, and the `t0` immediately before `sess.run` in `spike_tier2_models`), and
  at a fixed 104-token tensor shape a BERT-class encoder's FLOPs do not depend on which tokens
  fill it. Identical work measured at 11.30 and 14.27 ms in two separate runs is **run-to-run
  variance (~26%)** — thermal state, background load, a separate quantization pass — and is
  disclosed as a measurement band, not explained away as content.

Consequently the single-window figure this ADR treats as authoritative for the budget decision is
the **higher** one where they disagree, and the ~26% band applies to every figure in the table.
The conclusions are unchanged: 1 window fits with margin on either figure, 2 windows breach on
either, and the bound case is in the >500 ms class on either.

#### Correction 1 — 2026-08-29: the coverage labels were observed, not derived, and the bound case undercovered the bound (resolves `[D3-bound-case-window-count-undercovers-the-policy-bound]`)

**Status:** Accepted 2026-08-29. Option A of the filed report, approved. (Numbered "1" although this
ADR's other correction — the cross-validation note above — is unnumbered. That one predates the
numbering convention and is left as-is rather than renumbered, since it is cited by heading text
elsewhere; the format precedent it follows is the `eyJ` correction in ADR-026.)

**The withdrawn table, preserved rather than deleted:**

> | windows | input tokens | sequential | batched (all in one call) |
> |---|---|---|---|
> | 1 | 102 | 11.30 / 13.01 | 11.62 / 12.90 |
> | 2 | ~178 | 23.28 / **25.13** | 21.45 / **26.10** |
> | 4 | 330 | 47.20 / 51.40 | 43.52 / 54.13 |
> | 8 | 634 | 96.52 / 99.50 | 91.99 / 98.42 |
> | 16 | 1546 | 196.19 / 201.91 | 203.88 / 235.27 |
> | 32 | ~3100 | 397.39 / 409.54 | 457.89 / 474.63 |
> | **52** | **4082** | **651.41 / 657.04** | **800.75 / 819.96** |

(Blockquoted deliberately, and not struck: `eval/check_derivations.py` locates a table by its header
line and takes the **first** match, so a withdrawn table left as live markdown would be the one the
re-derivation check reads. A quoted table is invisible to it. The mechanical guard shapes how the
withdrawn evidence is preserved — which is the correct direction of influence.)

**The off-by-one, stated plainly.** The bound-case row claimed **4082 tokens** of coverage at **52
windows**. The geometry is `coverage_tokens(n) = 102 + (n-1)·76`, so 52 windows span **3978** tokens —
**22 short of the 4000-token bound**, and 4082 is not a figure 52 windows can produce at all. The row
therefore contradicted the ADR's own headline guarantee, *full coverage, no unscanned tail*, in the
one row where the guarantee matters most. `windows_for_tokens(4000) = 53`, spanning 4054.

**Where 4082 came from, and why the whole column was wrong in kind.** The labels were **observed**
rather than **derived**: the harness reported the token count of the *whole synthetic filler string*,
which overshoots the target by construction (it appends until it is at least long enough — 4082 for a
4000-token request). The 52-window row was then labelled with the filler's length rather than with
what 52 windows cover. Rungs 1/2/4/8 happened to agree with the geometry, which is exactly why the
defect survived review; **16 and 32 did not** — published as 1546 and ~3100 against a derived 1242 and
2458. Those two are not merely mislabelled but **underivable**: no combination of the harness's
geometry and filler produces them, and the ruling explicitly declined to reconstruct their provenance.
One sentence is the whole record: they were wrong, their origin is not recoverable from the artifact,
and they are replaced by derived values.

**Every label in the re-published table is now computed from the geometry**, in the artifact and in
the harness, and `filler_tokens` is recorded beside them **explicitly marked provenance, not a label**.

**This is a label correction plus a re-measurement — not a re-roll.** The same precedent the `eyJ`
correction set: *the decision stands; only its stated reason was wrong.* Every conclusion ADR-032
reached survives — the bound case is in the >500 ms class, cost concentrates on long inputs, the
512-token blind spot closes, single-window inputs fit NFR-P-002 with margin. What changed is that the
bound case is now measured **at** the bound (53 windows, 4054 tokens) instead of 22 tokens short of
it, and every label is derived. The re-measurement was required because the row's *subject* changed:
a corrected label on a 52-window measurement would still not be a measurement of the bound.

**Why the re-measured figures differ slightly from the withdrawn ones.** They are a different run on
the same host: ~2-4% lower across the ladder, within the ~26% run-to-run band the correction above
already discloses. The new run also carries provenance the old one could not: a clean code stamp
(`445ca31dd087`), a certified-quiet host stamp (**0.6 / 0.94 / 0.98**, `QUIET`), **0 contamination
signals** from `spike_window_latency.contamination_signals`, and **n=40 at every ladder rung** — the
last of which matters more than it looks. The old artifact ran reduced reps at its four largest rungs,
where `_percentiles_are_distinct(10)` is False: `int(0.95·9)` and `int(0.99·9)` are both 8, so those
rows' "P99" was `samples[8]`, the second-worst of ten, wearing a P99 label. The figures were real; the
**percentile they claimed was not**. The symptom was visible and had been dismissed — a bound-case
"P99" that moved 10.9% between two runs whose P50s agreed to 1.2%.

**Guards, so the harness cannot reproduce the defect.** (1) `spike_window_latency` refuses to run if
`coverage_tokens(max(WINDOW_COUNTS)) < POLICY_BOUND_TOKENS` — an import-time assertion, so an
under-covering ladder cannot be measured, let alone published. (2) `tests/test_window_coverage.py`
asserts every published label equals the formula's output, and that the artifact's top rung is 53 and
not 52. (3) ADR-034 Part C's exact-count rule is pinned by a test that the detector's window count at
the policy bound covers every token, leaving no unscanned tail. (4) `eval/check_derivations.py`
re-derives every derivation-claiming figure in ADR-032/034 from the artifact and is a pytest gate, so
CI fails on a figure whose stated derivation does not produce it.

**M-31 is vindicated, and the vindication is the point.** M-31 recorded that Part C's original
character-upper-bound clause was *"never checked against real text before being written down."* The
same sentence describes this defect exactly: a coverage label never checked against the geometry it
claimed to express. Both were sound-looking arithmetic that no one evaluated at the bound.

**Pattern observation, recorded because it has now happened twice in two sessions.** In both cases the
*measurement* falsified the *written text*, not the reverse — and in both cases the written text was
internally plausible and had survived review. The defect class is **"a figure described by a
derivation it doesn't come from"**, and its instances here are: coverage labels sourced from filler
token counts; unresolved percentiles published as P99; Part B's tokenization table, which no script in
this repo measured when it was published; `4080` labelled "bound" when it is 54 windows; and a ratio
re-derived from a different rung than the two cells beside it. The lesson is not "review harder" — all
of these passed review. It is that a derivation claim must be **executable**, which is why the guard
this correction lands is a script and not a convention. A third instance was found by the correction's
own re-measurement and is filed as
`[D1-batch-4-justification-falsified-at-the-corrected-bound]` (MAJOR, open).

### Budget respecification (04 §2 / NFR-P-002)

- **NFR-P-002's <25 ms is scoped to single-window inputs** (≤104 tokens), and the scope rests on
  **principle, not on a measured miss** — corrected below, resolving `[D1-two-window-budget-breach-not-reproduced-on-the-clean-artifact]` (MAJOR, filed
  2026-08-29, **ruled and closed 2026-08-29**, Option A). A per-detector budget is a
  **per-inference** quantity; multi-window cost is **length-parametric by construction**
  (ADR-034), so no flat per-call figure can describe it at *any* window count. That argument holds
  whichever side of 25 ms the two-window measurement happens to land on, which is exactly why it is
  now the stated ground and the measurement is not.
  Measured, for the record: one window **12.59 ms P99**; two windows **24.76 ms P99** — *inside*
  the 25 ms budget by **0.24 ms**. That margin is **smaller than this ADR's own disclosed
  run-to-run band** (~26%: identical single-window work measured 11.30 and 14.27 ms in two separate
  runs), so two windows is **indistinguishable from the budget line** rather than safely inside it.
  The first rung that breaches at 6 threads is **4** windows.

> **Withdrawn wording, preserved.** Until Correction 1 this bullet read:
>
> > *"**NFR-P-002's <25 ms is scoped to single-window inputs** (≤104 tokens), where it is measured
> > to hold at 13.01 ms P99. The boundary is not a conservative choice — it is exactly where the
> > measurement puts it: two windows measure **25.13 ms P99** against a 25 ms budget, so the target
> > fails at the first multi-window input."*
>
> Both figures came from the withdrawn 52-window run and **the conclusion was false**, not merely
> imprecise: on the clean artifact two windows pass in *both* columns (sequential 24.76, batched
> 22.53). This is the one direction §7's anti-laundering rule does not cover — not a target moved
> to hide a miss, but a **claimed miss that did not happen**, which had made the scope look
> compelled by measurement when it was in fact the more conservative choice. The scope did not
> move; only its reason did.
>
> **Re-scoping to ≤2 windows was considered and rejected.** Verbatim, as ratified: *B would widen a
> target on less evidence than the ADR already disclosed as insufficient, and in the
> self-flattering direction.* A boundary that flips on 0.24 ms should not be re-drawn on 0.24 ms —
> and a third run could flip it back, since the gap is between-run drift that no number of reps
> inside one run reduces.
- **Multi-window cost is published as a window-count-bucketed, length-parametric, untargeted
  series** — the table above is its shape — with the bound case stated as a figure, not a range.
- **Anti-laundering record.** This scopes a target *after* a measurement missed it, which is what
  ADR-026 §5 bars, so the distinction is recorded explicitly rather than asserted. What §5 forbids
  is moving a target so a missed measurement passes; NFR-P-002 is **not** moved: <25 ms stays
  exactly where it was for the inputs it was measured against, and every input that breached it
  still breaches it. What changes is that the breaching class is **published with its own figures
  instead of being hidden by truncation** — the alternative on offer was to make the number look
  better by scoring less, which is the laundering §5 exists to prevent. SL-1 remains unmet and
  unmoved; ADR-026 §5's single re-measurement stays consumed.

### Consequences

1. `tier2_injection` is unblocked and implementable: windowed 104/26/76, MAX aggregation, batch 2
   (Correction 2),
   `window_count` + max-window index in signal meta.
2. **The 512-token blind spot closes.** Full coverage is the point: an injection at token 3000 is
   now scored, where before it was outside the tokenizer's reach entirely.
3. `cost.request_too_large` remains unmapped in all three shipped policies. That is a **cost-plane
   gap (Phase 6)**, not this ADR's business — item 4 makes `per_request_max_tokens` the latency
   control, and a policy that lowers it needs the signal mapped to see a rejection. Logged as an
   M-row, not left implicit.
4. Both injection D3s close citing this ADR.
5. ADR-031 consequence 5 still binds: `test_ovlp01_is_not_yet_wired` and
   `test_tier2_is_not_yet_injectable` must be **re-pointed in the commit that lands these
   detectors, not deleted**.

**Docs touched:** 01 (NFR-P-002 gains the single-window scope), 04 §2 (`tier2_injection` row),
06 §4 (the untargeted window-count series joins the reported set), 08 (both D3s closed; the
`cost.request_too_large` M-row).

---

## ADR-033 — A detector has three lifecycle states, not two: "registered but unloadable" is a boot-time condition (resolves `[D1-not-run-vocabulary-cannot-say-dependency-absent]`)

**Status:** Accepted 2026-08-28.
**Context.** 05 §4 fixed `not_run[].reason` to a closed vocabulary with one member,
`not_implemented`, defined as *"the detector has no live implementation in this phase"*. That was
true while every model-backed detector was a stub. The moment one gains an implementation, a host
without the `[ml]` extra has **no truthful value to record**: the detector exists, so
`not_implemented` is a false statement, and it was the only member admitted. The host is not
hypothetical — `.github/workflows/ci.yml` installs `.[dev]` only and says the model stack is
*deliberately* absent. Worse, because 05 §4 states that a not-run entry is **not** a
`DetectorFailureRecord` ("no attempt was made, so there is no fault"), `finance_advisor`'s
`tier2: fail_closed` was **silently not honoured** on such a host: the request passed with a
coverage note and nothing resolved a fail mode. The gap is generic — `rag_grounding`
(sentence-transformers), `entity_enricher` (spaCy) and the Tier-2 pair (onnxruntime/transformers)
reach it identically.

### Decision — three states, each with its own record

| # | State | Record |
|---|---|---|
| (a) | **Not registered** for this stage or switched off by policy | absent from `ran`; absent from `not_run` — it was never expected (existing 05 §4 semantics) |
| (b) | **Loaded and ran** | `Signal`s, or a `DetectorFailureRecord` on runtime fault (existing 04 §5) |
| (c) | **Registered but unloadable** — dependency absent at load | **NEW**: boot manifest + `detectors.unavailable[]` on every affected record |

State (c) is a **boot-time condition**, and that is the whole of why it needs its own
representation. It is never a per-request `DetectorFailureRecord` — nothing ran, so there is no
fault, no `error_class` and no timestamp that means anything. And it is never a silent not-run,
because coverage **was** promised: a policy names the detector's class and a use case expects it.

### Semantics

1. **Boot-time load probe.** At startup each registered detector that declares a loader attempts
   it. Failures do not raise; they enter a **boot manifest** naming the detector and the missing
   dependency. A detector with no loader (every deterministic Tier-1 emitter) is trivially
   available.
2. **Enforcement mirrors FR-GW-006's canary**, which is the precedent for "a boot may refuse":
   - If **any active policy** maps an unavailable detector's class to **`fail_closed`** →
     **BOOT FAILS** with an error naming the detector, the missing dependency, and the policies
     that require it. You cannot promise fail-closed protection with the protector absent; a
     gateway that boots into that state is asserting a guarantee it structurally cannot keep.
   - If **every** policy using it is **`fail_open`** → boot proceeds with a **loud warning**;
     every affected request's audit record carries the detector in `detectors.unavailable[]`
     (distinct from `ran`, from `not_run`, and from `detector_failures`), and
     `cp_detector_unavailable_total{detector}` counts it.
3. **`eval/run_all` consumes the same state** rather than keeping a parallel notion of "skipped".
   Its skip-and-report already exists; what changes is that "no implementation" and "dependency
   absent" stop sharing one label.
4. **Test environments without the `[ml]` extra run via `fail_open`-configured policies or
   explicit registration stubs — never by faking a load.** A stubbed detector that reports itself
   loaded would make the boot check pass by lying, which is the failure this ADR exists to
   prevent, reintroduced one layer down.

### Consequences

1. **CI cannot boot the gateway against the shipped policies once the Tier-2 pair lands, and that
   is correct.** `finance_advisor.yaml` sets `tier2: fail_closed`; CI has no `onnxruntime`. Per
   rule 2 that boot must fail. Tests that boot against the real `policies/` directory are
   re-pointed at fail-open fixtures per rule 4 — **not** by installing a fake loader and **not**
   by relaxing `finance_advisor`. The alternative, a green CI booting a gateway whose fail-closed
   promise is void, is exactly the silent non-enforcement this deviation reported.
2. `05 §3`/`§4` gain `detectors.unavailable[]` (entries `{detector, missing}`); the write-path
   validator enforces it, and a detector may appear in **at most one** of `ran`, `not_run`,
   `unavailable` — the same trustworthiness rule the existing `ran`/`not_run` overlap check
   enforces, extended to three lists.
3. `05 §5` gains `cp_detector_unavailable_total{detector}`.
4. `04 §5` gains state (c) beside the fail-open/fail-closed resolution table, since a reader of the
   failure semantics needs to know that one case never reaches them.
5. **`not_implemented` keeps its exact meaning** and its place in the vocabulary. This ADR does not
   redefine it; it stops it being asked to carry a second meaning. `dependency_unavailable` is
   deliberately **not** added as a `not_run` reason — that would put a boot-time environment fact
   in a per-request coverage field, where every request restates it and no reader can tell whether
   the promise was ever keepable.
6. `entity_enricher` is the one detector with no `fail_mode` class at all (04 §2.2: enrichment
   failure skips and logs and never blocks, and `DETECTOR_FAIL_CLASS` omits it deliberately). It
   therefore can **never** trigger a boot failure — there is no class to map to `fail_closed` —
   and its unavailability is a warning plus a record entry, always. Stated because "no class"
   reads like an oversight until it is written down.

**Docs touched:** 04 §5 (state (c)), 05 §3 (the DDL comment), 05 §4 (the coverage contract and the
JSON view), 05 §5 (the metric), 08 (deviation closed).

---

## ADR-034 — CPU-bound model detectors run on a dedicated single-worker executor, and `tier2_injection`'s runner ceiling is length-parametric (resolves `[D1-windowed-injection-cannot-be-enforced-by-a-per-call-budget]`)

**Status:** Accepted 2026-08-28. Recommendation A of the filed report, approved and **extended** with
an execution-vehicle ruling that is deliberately generic rather than injection-specific.

**Context.** The deviation found that 04 §2 budgets `tier2_injection` **per 104-token window** while
`BUDGETS_MS` is a flat per-call scalar which `run_lane` then handed straight to
`asyncio.wait_for` (it now resolves a ceiling through `ceiling_ms`, which is what Part C below
rules) — so a detector *specified* to take ~651 ms at the
`per_request_max_tokens: 4000` bound is *enforced* at 25 ms. It further measured that the two viable
detector shapes fail in opposite directions: a loop-yielding implementation is cancelled at 25 ms,
while a loop-blocking one passes by stalling the event loop for the full duration. There is no third
shape **at that level of the design** — which is what this ADR changes, by ruling on the vehicle
rather than only on the number.

### Part A — Execution vehicle (generic: governs every CPU-bound model detector)

**Model inference runs on a dedicated single-worker `ThreadPoolExecutor`, awaited from the detector.
Never inline on the event loop.** This binds `tier2_injection`, `tier2_toxicity`, `rag_grounding`,
`fast_consistency`'s embedding comparison, `entity_enricher`, and any future CPU-bound model
detector. It is ruled once, generically, because three ad-hoc choices is how the same trap gets
re-entered per detector.

Two reasons, both recorded:

1. **ONNX Runtime releases the GIL during `sess.run`**, so the event loop stays live for concurrent
   requests while inference proceeds. The deviation's "sync shape stalls everything" is otherwise not
   a hypothetical — it is the production behaviour of the only shape that survives a flat `wait_for`.
2. **An awaited executor future is what makes `asyncio.wait_for` a real enforcement point** rather
   than a dead letter. Against inline CPU work the wrapper cannot interrupt anything and the timeout
   fires only once control returns, which `run_with_budget`'s own docstring already states. The
   budget mechanism only means something if the thing it wraps can actually yield.

**`max_workers=1` is load-bearing, not a default.** It serializes inference across concurrent
requests, which preserves the one-inference-at-a-time conditions **SL-5** measured under: a pool that
let four requests infer simultaneously would push per-request parallelism toward the 1-thread column
without any figure in this repo describing it. ~~**Queue wait counts inside the ceiling** — a request
that waits behind two others has genuinely waited, and a budget that excluded queueing would measure
the detector rather than the hold NFR-P-001 is about.~~ **SUPERSEDED by ADR-036 (front door).** The
first half is true and survives: a request that waits behind two others has genuinely waited. The
inference from it does not. Queue wait is real wait, but it is not *this detector's* wait, and
charging it to an NFR-P-002 budget made a detector's own figure depend on what else shared its lane.
The dichotomy in the last clause was false — excluding queueing does not leave the hold unmeasured,
because the **hold series measures it directly** and ADR-030 Amendment 3 already sums pool users to
do so. ADR-036 splits the two: the budget binds detector-attributable time, the hold keeps
wall-clock. Nothing is hidden by the change; one cost is charged once instead of twice.

**Caveat, recorded honestly because it is a real limitation and not a detail.** A timed-out executor
task is **abandoned, not killed**: Python cannot preempt a running thread, so `wait_for` stops
*waiting* for the future while the thread finishes its current `sess.run`. The request proceeds under
policy `fail_mode` immediately, and the orphaned thread's completion is discarded. The practical
consequence is that the worker may be busy for a short period after a timeout, which — with
`max_workers=1` — is itself queue wait for the next request, counted as above. Each abandonment
increments **`cp_detector_timeout_abandoned_total{detector}`**, so the condition is countable rather
than inferred from a latency histogram.

### Part B — `tier2_injection`'s runner ceiling is length-parametric

The ceiling the runner enforces is derived from ADR-032's measured series rather than chosen:

```
ceiling_ms(n_windows) = max(25.0, envelope_ms(n_windows) x 2.0)
```

floored at the flat **25 ms** for single-window inputs, where NFR-P-002 is scoped and measured to
hold (**12.59 ms P99**, worst of both columns at the 1-window rung — Correction 1; the withdrawn run
read 13.01). The ceiling's meaning changes with its shape: it now says **"materially slower
than its own measured envelope"** — a genuine anomaly worth a `DetectorTimeout` — instead of
"longer than one window's budget", which was a statement about input length wearing a budget's
clothes.

**This dissolves the fail-mode pathology the deviation identified.** `finance_advisor`'s
`tier2: fail_closed` no longer blocks every multi-window input, and `support_bot` / `hr_copilot`'s
`fail_open` no longer silently skips them — because a correctly-behaving detector never trips the
ceiling **by length alone**. That, and not the number, is the property being bought.

#### Which measured column grounds the envelope (resolved in place, logged as a MINOR resolution)

ADR-032 publishes **two** thread settings and SL-5 stands on the gap between them, so "the measured
series x 2" does not name a unique number until the column is chosen. The choice has consequences,
so it is recorded rather than left to the implementation:

| basis | per-window P99 | ceiling at 2 windows | actual cost at 1 thread | verdict |
|---|---|---|---|---|
| 6 threads (optimistic) | 12.38 ms | ~50 ms | 102.09 ms | **trips by contention alone** |
| 1 thread (pessimistic) | 51.05 ms | ~204 ms | 102.09 ms | holds |

Both per-window figures are the **P99 at the 2-window rung**, halved — same rung, same percentile, so
the two cells are comparable and the ratio below is derivable *from them*. Stating the rung is the
point: the withdrawn version of this paragraph quoted a ratio taken from the **1-window** rung while
displaying the 2-window cells (50.55 / 13.01 = 3.89), which is exactly the defect class Correction 1
exists to remove — a figure described by a derivation it does not come from.

**The envelope is grounded on the 1-thread column.** A ceiling built on the 6-thread figures is
*below* the 1-thread cost at every window count — the ratio is **4.12x** (51.05 / 12.38, both the P99 at the 2-window rung), not within a 2x safety
factor — so it would re-introduce the exact pathology this ADR exists to remove, merely relocated
from "any long input" to "any long input on a contended host". A gateway is a concurrent server, so
that is the normal operating case and not an edge. Choosing the conservative column is also the
low-risk direction in the only sense that matters here: a loose ceiling can fail to catch a mildly
slow detector, while a tight one causes false blocks and false skips on live traffic. The per-window
budget of 04 §2 is unchanged and unmoved — **NFR-P-002 is not restated by this ADR**, and SL-5's
disclosure that Tier-2 figures are low-concurrency figures is unchanged.

#### Tokenization is inside the ceiling, and it is not inside ADR-032's table

**ADR-032's entire published series times `sess.run` only** — tokenization sits outside the clock at
`eval.spike_window_latency._time_calls`, whose timed `one_pass` calls `sess.run` and nothing else, as its own
Correction section states. A detector pays both. The
envelope therefore carries a tokenization term. **When this table was first published, no script in this repo
measured it** — the figures were asserted, and they were wrong by ~3x. `eval/spike_window_latency.py`
now times the windowing pass (`_time_tokenize`, wrapping the same `_tokenize_windows` call the ladder
feeds from, so the figure covers the code a detector actually runs), and the table below is re-cited
from `reports/spike_window_latency.json` — measured on this host with the spike's own synthetic
filler and the same tokenizer (`madhurjindal/Jailbreak-Detector`, `AutoTokenizer`, window 104 /
overlap 26 / `padding="max_length"`, n=40, 6 threads, code `445ca31dd087` on a `QUIET` host):

| input | windows | tokenize + window P50 / P99 |
|---|---|---|
| 178 tokens | 2 | 0.37 / 0.41 ms |
| 634 tokens | 8 | 1.49 / 1.83 ms |
| 4000 tokens | 53 | 7.65 / 8.22 ms |

The bottom row **is** the policy bound: 4000 tokens is `per_request_max_tokens` and 53 windows is what
covers it (Correction 1). The withdrawn version of this table labelled its bottom row
**"4080 tokens | bound"**, wrong twice over — 4080 tokens needs **54** windows, so that row was neither
the bound nor labelled with a window count at all. The 1-thread column is within noise of this one
(0.38 / 1.50 / 7.83 P50), as expected: the windowing pass is single-threaded Python either way.

This is **not** a contradiction of ADR-032: no doc claims the two spans are equal, and 06 §4 defines
`input_hold_ms` as "ingress + input-lane time", which includes tokenization by construction. It is a
disclosure, and it is stated here because a reader comparing this repo's published window series
against ADR-032's table would otherwise conclude one of them is wrong. **Every `tier2_injection`
figure this repo publishes states which spans it covers.**

### Part C — `BUDGETS_MS` grows a shape for parametric entries

`BUDGETS_MS` values become `float | ParametricBudget`, where a parametric entry resolves a ceiling
from a window count. `run_lane` consumes the resolved value via `ceiling_ms(name, units)`; every other entry stays a flat
float and every existing call site is unchanged. **04 §2 records both halves** — the per-window
budget the detector enforces internally, and the parametric runner ceiling — because the deviation's
central finding was that a doc stating one of them while the code enforced the other is how the
contradiction stayed invisible.

**The cost is real and is stated rather than discovered later:** `run_with_budget`'s guarantee is now
explicitly **two-tier**. For flat-budget detectors it is unchanged. For a parametric one, the outer
wrapper enforces the envelope while the per-window budget is enforced inside the detector — so
"`BUDGETS_MS[name]` is the number `wait_for` gets" stops being universally true, and that is the
trade-off Recommendation A named when it was filed.

#### Where the window count comes from — corrected against measurement

This clause first specified the runner deriving its window count from a **cheap character upper
bound**, on the reasoning that the runner must not pay the tokenizer twice. The bound is *sound* for
a WordPiece tokenizer (`n_tokens <= n_chars`) but was measured to be far too loose to carry the
meaning Part B gives the ceiling, so it is **replaced here rather than left to be discovered in
implementation**. Measured chars-per-token on this tokenizer:

| population | chars/token | implied over-provision |
|---|---|---|
| frozen corpus, median (n=280) | 4.29 | ~4.3x |
| frozen corpus, minimum (base64/JWT-dense) | 1.42 | ~1.4x |
| punctuation run / CJK | 1.00 | ~1.0x (bound is tight) |
| unspaced letters, digits, emoji, combining marks | 400-800 | **~400-800x** |

At the 4000-token bound a 4.3x over-provision turns a ~5.5 s envelope into a ~24 s ceiling on
*typical* text, and the adversarial column is far worse. A ceiling that loose still catches a hung
detector but no longer catches "materially slower than its own measured envelope", which is the
condition Part B exists to detect. The bound also rests on the tokenizer being WordPiece: under
byte-level BPE a single character can yield several tokens and `n_tokens <= n_chars` fails outright,
so the guard would be silently unsound on a checkpoint swap.

**Ruled instead: the exact count is used, and tokenization is paid once.** `tier2_injection`
tokenizes its input **once**, obtains the true `window_count`, and enforces **both** its per-window
budget and its own total envelope from that exact figure — raising `DetectorTimeout` itself. The
runner's outer `wait_for` keeps a **backstop** ceiling derived from the policy's
`per_request_max_tokens`, which is a genuine hard bound the gateway can enforce and needs no
tokenization to read. So the two tiers become: an **exact** envelope check inside the detector, and a
**coarse** liveness backstop outside it. Nothing tokenizes twice, and the meaningful guard is exact
rather than approximate.

This keeps the ruling's stated shape intact — `BUDGETS_MS` values are `flat float | parametric on
window_count`, consumed by `run_lane` through `ceiling_ms` — and changes only *who* supplies the count. Logged as a
MINOR resolution in `08` per AGENTS.md §11.1, since it is an implementation-level correction inside a
contract this ADR itself settles.

### Consequences

1. `tier2_injection` is implementable as ADR-032 specifies — full-coverage windows, MAX aggregation,
   batch 2 (ADR-032 Correction 2) — without either stalling the event loop or being cancelled by
   its own runner.
2. **The execution-vehicle rule binds four further detectors** (`tier2_toxicity`, `rag_grounding`,
   `fast_consistency`, `entity_enricher`). None may run model inference inline on the loop, whatever
   its budget, and a flat 25 ms budget is not a licence to do so.
3. `05 §5` gains `cp_detector_timeout_abandoned_total{detector}`.
4. `04 §2` records the per-window budget and the parametric runner ceiling as two distinct
   mechanisms, with the tokenization-span disclosure attached to the published series.
5. The MINOR resolution above (envelope column) is logged in `08`'s MINOR-resolutions register, per
   AGENTS.md §11.1 — the count stays honest rather than merely low.
6. The deviation closes citing this ADR.

**Docs touched:** 04 §2 (both budget halves + the span disclosure), 05 §5 (the new counter), 08
(deviation closed; MINOR resolution logged).

---

## ADR-035 — The `ml` extra must build the graph it serves: `onnx` is a serve-path dependency, not a build-only one (resolves `[D2-tier2-served-graph-is-unbuildable-on-the-ml-extra]`)

**Status:** Accepted 2026-08-28. Option A of the filed report, approved and **extended** with a
testable invariant so the trap cannot be re-opened by a later edit.

**Context.** ADR-031 serves both Tier-2 checkpoints from ONNX Runtime int8, and deliberately checks
**no graph into the repo** — *"a checked-in graph would be a binary artifact whose provenance nobody
could check"*. ADR-033 then declared tier-2's dependency set as exactly `("onnxruntime",
"transformers")`, and `pyproject.toml` kept `onnx`/`onnxscript` in the `dev` extra on the reasoning
that they *build* the graph rather than serve it.

Three statements that cannot all hold, because **with no checked-in artifact, serving builds.** The
export and int8 quantization happen at first use, on the serving host, so the build toolchain sits on
the serve path by construction. `import onnxruntime` genuinely does not pull `onnx` — which is why
the `dev`-only comment read correctly in isolation and was still wrong in composition.

The failure lands **past ADR-033's stated boundary**, and that is where the harm is. ADR-033 says a
*"present package whose model graph fails to build at first use is a runtime fault (state (b)),
resolved by `fail_mode` like any other."* So an `.[ml]` host passes the `find_spec` probe for both
declared names, **boots clean**, and then converts a structurally unkeepable promise into a
per-request fault: under `finance_advisor` (`tier2: fail_closed`) a **BLOCK on every request**, under
`support_bot` / `hr_copilot` (`fail_open`) a **silent non-scan of every request**. ADR-033's boot
refusal — the mechanism that exists precisely so a fail-closed promise is never broken silently —
cannot fire, because the missing name is one nobody declared. It is invisible on the dev machine,
which is the reason it was ruled before an `.[ml]` host existed rather than after.

### Decision

1. **`onnx` moves from `dev` into `ml`, and both tier-2 `REQUIREMENTS` rows grow it.** The addition
   is **measured, not inferred from a dependency graph**: an interpreter was masked down to `.[ml]`'s
   declared closure and the real build was attempted (method and its two false starts below). `onnx`
   is the *only* addition needed — `ml_dtypes` arrives as `onnx`'s own requirement, so declaring it
   would be redundant, and `onnxscript` is not imported at all on this path.
2. **The invariant becomes a permanent test** — `tests/test_ml_extra_closure.py`. It derives both
   dependency closures **from `pyproject.toml` at run time** (never a hand-maintained copy, which
   would drift silently and test a stale set), masks the difference, and builds **both** checkpoints
   for real. This is what makes ADR-033's probe truthful *by construction*: move a build dependency
   out of `ml` and this fails in CI, before any `.[ml]` host boots into the per-request-fault trap.
   The test asserts its **own masking** first — a harness that quietly stopped masking would make the
   build pass for the wrong reason, on a full `.[dev,ml]` host.
3. **Resolution verified on both CI interpreters, py3.12 and py3.14** — identical resolved version
   sets, and adding `onnx` changes **no other pin**. This was checked rather than assumed because the
   `optimum` episode is exactly this failure mode: it resolved `transformers` *downward* as a side
   effect. Ruled in advance that a resolution failure would be a finding, not a pin to force; none
   occurred.
4. **Build-at-boot is kept; the cost is logged rather than cached.** Option B (build once into a
   cache directory outside the repo) is **declined for now**: build-at-boot is provenance-pure per
   ADR-031, and the boot cost is immaterial against a hackathon prototype's startup. The measured
   duration is logged at startup as one line beside the FR-GW-006 canary result, so the cost is
   *visible* rather than folded into an unexplained pause. B is recorded here as available, unchanged,
   if boot economics ever change — it is strictly an optimization on top of this ADR and answers no
   part of the deviation on its own.
5. **`onnxscript` stays in `dev`, and that is now an empirical claim rather than a guess.**
   `torch.onnx.export(..., dynamo=False)` uses the legacy TorchScript exporter, which does not import
   it; masking it out builds both checkpoints successfully. It is retained in `dev` as the escape
   hatch if that call ever moves to the dynamo exporter. Logged as **M-32** so the reason survives
   next to the pin.

### How the import set was measured — including two ways of faking absence that give wrong answers

Recorded because the permanent test rests on this method, and both mistakes produced a **confident,
plausible, wrong dependency list** before being caught:

1. **Raising from `find_spec` is wrong.** `transformers.utils.import_utils._is_package_available`
   *probes* for optional packages and expects `None` when absent
   (`import_utils.py:205`: `_pytest_available = _is_package_available("pytest")`). A finder that
   raises converts a graceful capability check into a hard failure — which reported **`pytest` as a
   tier-2 build dependency**. Absence means: `find_spec` returns `None`, and `import` raises from the
   import machinery itself.
2. **Wrapping finders without delegating `find_distributions` is wrong.** That hook is how
   `importlib.metadata` enumerates installed distributions, so wrapping without it broke metadata
   lookup for *every* package and reported **`tqdm`** — installed and unmasked — as missing.

A masked distribution must therefore be invisible in **both** channels: no importable module and no
metadata. The test asserts exactly that before trusting its own result.

### Measurement outcome

`madhurjindal/Jailbreak-Detector` and `martin-ha/toxic-comment-model`, Ryzen 5 5600H, Linux 7.1.2,
Python 3.14.6, onnxruntime 1.29.0, warm HuggingFace cache:

| host configuration | ADR-033 probe | actual graph build |
|---|---|---|
| `.[dev,ml]` | available | succeeds |
| `.[ml]` **before** this ADR | **available** | **`ModuleNotFoundError: No module named 'onnx'`** (requested 5×) |
| `.[ml]` **after** this ADR | available | **succeeds, both checkpoints** (66.2 MB / 67.3 MB int8) |

**Boot cost, corrected.** The deviation report cited *"~4.6 s (1.76 export + 2.85 quantize)"*. That is
the export-plus-quantize span only; the figure a booting host actually pays also includes
`from_pretrained` and opening the ORT session. Measured end-to-end per checkpoint: **9.6–10.1 s**
(export 1.86–1.95 s, quantize 2.98–3.10 s, remainder model load and session open), so **~20 s for
both** — roughly 4× the number quoted when Option B was declined. The ruling's conclusion is
unchanged and stands: ~20 s of prototype startup is still immaterial, and provenance purity is worth
it. The corrected figure is published here rather than left at the flattering one (AGENTS.md §7), and
it is the number item 4's startup log will print. A cold host additionally downloads the checkpoints.

### Consequences

1. `REQUIREMENTS` is a true statement about what tier-2 needs, so ADR-033's boot refusal works as
   designed on an `.[ml]` host — the D7 edge it closed at boot stays closed.
2. The `ml` extra now carries graph-build tooling on serving hosts. That is the accepted cost of
   ADR-031's no-artifact stance, stated plainly rather than discovered by a deployer.
3. **A new CI job installing `.[dev,ml]` is required for the guard in item 2 to have teeth** — the
   test skips where the model stack is absent, and a permanently-skipped invariant is not one. This
   settles the optional M-row left to discretion in the Phase-5 sweep: the second CI job is no longer
   an economics question, it is what makes this ADR enforceable.
4. `05 §6` / AGENTS.md §10 install guidance is unchanged: `.[dev,ml]` was already the documented
   full-stack line, and it still installs everything.
5. The provisioning seam the detectors were built around — one shared helper obtaining the int8
   session — is now fully ruled, and the ruling changed **one function** rather than two detectors.
6. The deviation closes citing this ADR. `onnxscript`'s retention is logged as M-32.

**Docs touched:** `pyproject.toml` (both extras, with the superseded comment preserved quoted),
`controlplane/detectors/availability.py` (`REQUIREMENTS`), `tests/test_ml_extra_closure.py` (new),
`08` (deviation closed; M-32 logged), CI workflow (the `.[dev,ml]` job).

---

## ADR-036 — An NFR-P-002 budget binds detector-**attributable** time; wall-clock keeps a hang backstop (resolves `[D3-toxicity-wallclock-vs-25ms]`)

**Status:** Accepted 2026-08-30. The filed report's Option A, approved with an attribution fix that
the report itself did not propose — the ruling is that the 2/30 spurious-fault rate was a
**misattribution defect, not a detector defect**, so the answer is to fix what the budget clocks
rather than to ship the noise or revert the detector.

**Context.** Wiring `tier2_toxicity` into `OUTPUT_SENTENCE` made 2 of 30 *control* fault-injection
probes — no fault injected — record `DetectorTimeout` for it. The detector was not slow: the model
measured **11.92 ms** p50 against a 25 ms budget. Enforcement was reading **wall-clock through the
event loop**, which for a pool detector includes pool queue wait, GIL contention with the three
asyncio detectors sharing its lane, and loop scheduling. The gap was ~8.5 ms and it was not the
detector's work. **SL-5's logged exposure materialized exactly as predicted** — it warned that the
Tier-2 <25 ms budget was measured with 6 threads free for one inference while NFR-P-002 states no
thread count — and that is worth recording as a hit for the practice of writing exposures down:
this arrived as a known risk with a name, not as a surprise.

**Ruling.**

1. **NFR-P-002 budgets bind detector-attributable time.** For a pool detector, enforcement clocks
   **in-thread execution**, measured inside the executor task around the model call. Scheduling,
   GIL contention and pool-queue wait belong to the **HOLD** series, where ADR-030 Amendment 3
   already sums pool users — they are lane-composition costs, and charging them to a detector made
   its budget depend on what else happened to share its lane.
2. **This supersedes ADR-034's "queue wait counts inside the ceiling" sentence, by the front door.**
   The sentence is struck in place, at its own site, with the reasoning preserved and marked rather
   than deleted. **Anti-laundering note, stated because the timing invites the suspicion:** this was
   ruled from a **diagnostic** that showed spurious *attribution*, before any citable bench existed,
   and the direction of the change is what distinguishes it from target-chasing. No published number
   is being pursued green. A budget was not widened — 25 ms is untouched, and item 3 adds a *new*
   wall-clock guard where there was one before. What changed is which of two clocks the word
   "budget" names, decided on the evidence that one of them was measuring other detectors' work.
   The honest tell: this ruling makes the *hold* rows harder to satisfy, not easier, because they
   still carry every cost the budget now excludes (item 5).
3. **Wall-clock does not go unguarded.** `run_with_budget` keeps `asyncio.wait_for`, retargeted from
   the budget to **`HANG_BACKSTOP_FACTOR = 2.0` x the (parametric) ceiling**, and firing it raises a
   distinct `DetectorHang` — never `DetectorTimeout`. The two are different findings and 04 §5 now
   records them as different `error_class` values: a budget breach says "this detector executed too
   long", a hang says "this call did not come back". Collapsing them would rebuild the exact
   misattribution this ADR removes, and would do it invisibly. 2x is deliberately loose: anything
   near 1x re-enforces the budget on wall-clock through the back door. This is ADR-034 Part B's own
   genuine-anomaly framing, applied to the failure vocabulary.
4. **Failure records carry the measured duration.** `DetectorFailureRecord` /
   `FailureOutcome.audit_entry()` gain **`attributable_ms`** — the in-thread figure when something
   measured it, `null` when nothing did (the normal case for a hang, whose worker never returned).
   The six-key shape 04 §5 and 05 §3 documented becomes **seven**. This extends ADR-034's
   abandoned-task caveat: a real breach and a scheduling artifact are now distinguishable in the
   audit **forever**, where before both arrived as `DetectorTimeout` with nothing to separate them.
   A duration is not content, so NFR-SEC-001 does not reach it.
5. **The published holds are recomputed from the stamped bench, not from this diagnostic.** The
   affected ADR-030 Amendment 3 rows are re-derived under corrected semantics from the quiet-host
   `bench_latency` artifact. Any row that cannot fit **publishes untargeted**, per the standing
   per-request-sum precedent. The hold series itself still measures **wall-clock**: nothing is
   hidden by item 1, only correctly attributed.

**The instrument is a PROVISIONAL departure from the ruling's own parenthetical — batch review at
phase end.** The ruling names `perf_counter` inside the executor task. Implemented literally, it
made the defect **worse**: `perf_counter` in a worker thread counts every microsecond that thread
sits blocked on the GIL while the asyncio detectors in its lane run, so it relocates the clock
without isolating anything.

| enforcement clock | spurious control faults | in-thread p50, quiet loop | in-thread p50, lane contention |
|---|---|---|---|
| wall-clock through the loop (pre-ruling) | 2/30 | — | — |
| `perf_counter` in-thread (ruling's parenthetical) | **18/30** | 12.04 ms | **229.26 ms** |
| `thread_time` in-thread (shipped) | **0/30** | 11.98 ms | 26.04 ms |

`attributable_ms` under `perf_counter` tracked wall-clock to within 0.3 ms in the gateway (31.02 vs
31.3; 48.76 vs 49.1) — the two were the same number. `time.thread_time()` is per-thread CPU time and
excludes GIL-wait, which is what the ruling's *intent* asks for in its own words: "scheduling, GIL
contention, and pool-queue wait belong to the HOLD series". **Every figure in this table is
DIAGNOSTIC** — ad-hoc script, n=30/40, host load1 above `QUIET_LOAD1_MAX` — and none of it is
citable; the citable figures come from the stamped `bench_latency` run.

**Caveat, recorded rather than smoothed.** ONNX Runtime's calling thread spin-waits on its intra-op
pool, so `thread_time` still **rises under real CPU competition**: 11.98 ms quiet against 26.04 ms
under lane contention. It is detector-attributable CPU, not a contention-free constant, and above
25 ms it is an honest breach rather than a misattribution — which is precisely what
`tier2_toxicity` does when the full test suite competes for the CPU, and why
`test_faults_are_counted_and_absent_means_zero` was re-anchored on a fault-free detector instead of
on an empty mapping (AGENTS.md §7: the harness is not made clean to satisfy a test).

**Consequences for the failure vocabulary.** A detector that merely `await`s burns no thread CPU, so
it **cannot** breach an NFR-P-002 budget — only the backstop can end it. Two liveness tests asserted
`DetectorTimeout` on exactly that shape and were re-pointed to `DetectorHang`; calling an awaiting
detector a budget breach *was* the misattribution. Because that narrows `DetectorTimeout` to a real
window — attributable CPU over budget while wall-clock stays under 2x — a companion test
(`test_run_with_budget_raises_detector_timeout_on_in_thread_overrun`) now pins it with CPU-bound
executor work, so budget enforcement is not left untested by the re-point.

**Also closed by this sweep.** SC-3's `performance`-for-`tier2` substitution is **retired**:
`tier2_toxicity` sits in `OUTPUT_SENTENCE`, so `faultable()` derives tier2 coverage with no harness
edit. 07 beat 7 needed no change — it always said `--inject-fault tier2`; the harness was the side
that deviated. The tripwire that guarded the substitution is inverted to guard the opposite risk
(tier2 silently *losing* its carrier), per its own docstring's instructions.

**Docs touched:** `controlplane/detectors/base.py` (`DetectorHang`, `HANG_BACKSTOP_FACTOR`,
`_ATTRIBUTABLE_MS`, in-thread clocking, the superseded queue-wait rationale),
`controlplane/policy/engine.py` + `controlplane/gateway/pipeline.py` (`attributable_ms` threaded),
`04` §5 and `05` §3/§4 (seven-key shape, `DetectorHang`), `03` (ADR-034 sentence struck in place;
this ADR), `08` (deviation closed; M-50), and five test files re-pointed rather than relaxed.
