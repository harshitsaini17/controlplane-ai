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
