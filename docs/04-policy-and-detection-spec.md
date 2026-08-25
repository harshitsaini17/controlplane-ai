# 04 — Policy & Detection Specification

The center of gravity. Defines: detector contracts (§2), policy schema (§3), the verdict state machine (§4), failure semantics (§5), edit transformations (§6), feedback loop (§7).

---

## 1. Signal model

A **signal** is the only thing a detector may emit. Detectors never decide actions.

```json
{
  "signal_id": "uuid",
  "detector": "tier1_pii",              // registry name, §2
  "planes": ["responsibility"],          // one or more of: performance|cost|responsibility
  "labels": ["pii.ssn"],                 // taxonomy, §1.1 — multi-label allowed
  "score": 1.0,                          // [0,1]; semantics depend on score_kind — §1.2
  "score_kind": "detection",             // detection | confidence (ADR-012)
  "span": {"start": 112, "end": 123},    // char offsets in the checked text; null if request-level
  "stage": "output_sentence",            // input | output_sentence | output_full | conversation
  "evidence": "category:ssn pattern",    // NEVER the raw matched value (NFR-SEC-001)
  "latency_ms": 0.4,
  "meta": {}                             // detector-specific (e.g., method:"self_consistency")
}
```

### 1.1 Label taxonomy (extend only via doc change)

```
pii.ssn | pii.credit_card | pii.email | pii.phone | pii.api_key | pii.person_data
security.prompt_injection | security.blocklist
toxicity.high | toxicity.moderate
hallucination.low_confidence | hallucination.ungrounded_claim | hallucination.unsourced_numeric
privacy.person            // fabricated/exposed detail about an identifiable person
cost.budget_exceeded | cost.request_too_large | cost.loop_detected
conversation.cumulative_risk
```

**Overlap rule (FR-DET-005):** the fabricated-personal-detail case emits ONE signal with `labels:["hallucination.ungrounded_claim","privacy.person"]` and `planes:["performance","responsibility"]`. The policy engine resolves multi-label signals by taking the **most severe** mapped action across labels (§4.3). Producer: the `entity_enricher` stage (§2.2) appends `privacy.person` to the hallucination signal — no detector emits it directly. An appended label is recorded in `meta.enriched_labels` and its band behaviour differs from its host's: see §2.2 and §4.3 step 2 (ADR-019).

### 1.2 Score semantics (ADR-012 — polarity is normative, not stylistic)

| score_kind | Meaning | Higher = | Emitters | Band logic (§4.3 step 2) |
|---|---|---|---|---|
| `detection` | certainty the problem is present | worse | `tier1_*`, `tier2_injection`, `tier2_toxicity`, `numeric_claims`, `cost_*`, `loop_guard`, `conv_tracker` (deterministic emitters use 1.0) | **never applies** |
| `confidence` | confidence the content is correct/grounded | better | `fast_consistency`, `rag_grounding` | applies — and only here |

Confidence-kind detectors **always emit** their score signal (they stay policy-agnostic); the engine's band logic decides firing. Side effect: audit records carry confidence scores even on PASS — free calibration data for 06 §3.

## 2. Detector registry & contracts

Common contract: `async detect(ctx) -> list[Signal]`; must respect its latency budget; must raise `DetectorTimeout`/`DetectorError` rather than hang (gateway enforces `asyncio.wait_for`); must be stateless per call (conversation tracker excepted).

| Detector | Stage | Budget (NFR-P-002) | Emits | Notes |
|---|---|---|---|---|
| `tier1_pii` | input + output_sentence | <2 ms | `pii.*` | compiled regex + Aho-Corasick keyword sets; span-accurate for redaction |
| `tier1_blocklist` | input + output_sentence | <2 ms | `security.blocklist` | per-use-case extra terms via policy `blocklist_extra` |
| `tier2_injection` | input | <25 ms | `security.prompt_injection` | small transformer, CPU/ONNX; score = model prob |
| `tier2_toxicity` | output_sentence | <25 ms | `toxicity.*` | moderate vs high via detector-internal cutoffs (0.5/0.8 defaults; overridable in policy `detector_params`) |
| `fast_consistency` | output_full* | <60 ms | `hallucination.low_confidence` | 2nd sample at temperature; embedding cosine; *runs on accumulated response so far at each sentence boundary using the parallel-sample stream (see §2.3) |
| `rag_grounding` | output_sentence | <30 ms | `hallucination.ungrounded_claim` | only when request carries `context` docs; sentence-vs-context embedding entailment proxy |
| `numeric_claims` | output_sentence | <5 ms | `hallucination.unsourced_numeric` | heuristic: currency/percent/large-number patterns with no citation marker and no match in provided context; high-stakes use cases map it to ESCALATE |
| `cost_budget` | input | <1 ms | `cost.*` | ledger lookup; token estimate via tokenizer count × price table |
| `loop_guard` | input | <1 ms | `cost.loop_detected` | sliding window per conversation |
| `conv_tracker` | conversation | <1 ms | `conversation.cumulative_risk` | running totals of pii/hallucination signals per conversation id — **`stage` ∈ {output_sentence, output_full, conversation} only** (ADR-021) |

### 2.2 Enrichment stage — `entity_enricher` (ADR-011)

Runs after fast-path detection, before the policy engine. For each span-bearing `hallucination.*` signal: spaCy `en_core_web_sm` NER over the span (± its sentence window); a PERSON entity appends `privacy.person` to `labels` and `responsibility` to `planes` of the **same** signal (one-signal rule, FR-DET-005). Budget < 10 ms per enriched span. Enrichment failure → skip + log; it never blocks and is not a policy `fail_mode` class.

**`meta.enriched_labels` is a contract, not a note (ADR-019).** The enricher MUST record every label it appends in `meta.enriched_labels`. §4.3 step 2 partitions a signal's labels on exactly this list — a host label is band-adjusted, an appended one is not — so an unrecorded append is silently mis-adjusted, and a recorded label that is not actually in `labels` describes a signal that does not exist. Both directions are therefore rejected at `Signal` construction (`detectors/base.py`), not merely documented: an unrecorded `privacy.person`, and an `enriched_labels` entry missing from `labels`, are both construction errors. The check lives in the model so a malformed signal cannot be built at all, rather than in the engine where it would surface only on the paths that happen to run.

### 2.2.1 `conv_tracker` accumulation scope (ADR-021)

`conv_tracker` accumulates **output-stage and conversation-stage signals only**. Input-stage signals are excluded: the control plane exists to stop the *assistant* disclosing data, and a user quoting their own order number or email is the normal case, not the risk — accumulating it would make cumulative risk fire on ordinary support conversations and would measure user behaviour instead of model behaviour. Input-stage PII is not ignored, it is acted on immediately by its own policy mapping at the input stage (and redacted pre-dispatch where the policy maps it to edit, §4.5); it simply does not accumulate.

**Dataset consequence (normative for 06 §2).** A multi-turn case is labelled **per breach unit** — the breaching turn's own labels plus the conversation-stage signal — never as the union of every turn's labels. This follows §4.1, where the evaluated unit is one output sentence plus conversation-stage signals, so ground truth describes the unit where the verdict lands. Earlier turns' PII is already scored by its own `pii.jsonl` cases; unioning would inflate per-detector recall denominators without changing any verdict.

### 2.3 Consistency modes & sample-lag semantics (ADR-014)

- `consistency: on` **requires `streaming: false`** (schema-enforced). The full response and a parallel 2nd sample are compared once, pre-delivery — the check is always available and nothing reaches the user before the verdict. (UC-3.)
- `consistency: on_sampled` (streaming; UC-1 at deep-audit rate): the 2nd sample streams in parallel from dispatch; at each sentence boundary the aligned prefix is compared **only if** sample-2 has ≥ 70% of the primary's released+buffered length. Otherwise the sentence proceeds *without* the signal, audited as `meta.consistency:"lagged"` and counted in `cp_consistency_lagged_total`; deep audit is the backstop.
- `consistency: off`: `rag_grounding` covers the performance plane where context exists.

Cost: ~2× tokens wherever sampling occurs — a policy knob (coverage vs cost), said openly in the demo.

## 3. Policy schema (per-use-case YAML)

```yaml
# policies/finance_advisor.yaml
schema_version: 1
use_case: finance_advisor
policy_version: 3                # bump on every change; engine stamps it into audit
geography: EU                    # metadata usable by mappings; data not code
risk_appetite: low               # low | medium | high (informational + default pack selector)

streaming: false                 # consistency:on requires full buffering (ADR-014)
sampling:
  deep_audit_rate: 0.25
consistency: "on"                # on | on_sampled | off   (on ⇒ streaming:false)
cascade_probe: "off"             # ADR-013; high-stakes → always frontier tier

thresholds:                      # calibrated per 06 §3; conformal-style quantiles
  tau_low: 0.35                  # below → treat hallucination score as firing
  tau_high: 0.70                 # low..high band → borderline (ESCALATE-eligible)
  tau_route: 0.55                # cascade escalation threshold (ADR-009)

budget:
  monthly_usd: 200
  per_request_max_tokens: 4000
  loop_max_requests_per_min: 10

actions:                         # label → action map; unlisted label → default_action
  pii.*: escalate
  security.prompt_injection: block
  security.blocklist: block
  toxicity.high: block
  toxicity.moderate: escalate
  hallucination.low_confidence: escalate
  hallucination.ungrounded_claim: escalate
  hallucination.unsourced_numeric: escalate
  privacy.person: escalate
  cost.budget_exceeded: block
  cost.loop_detected: block
  conversation.cumulative_risk: escalate
default_action: pass
borderline_action: escalate      # ADR-017; action for a confidence-kind signal whose
                                 # score lands in [tau_low, tau_high). Per-label, and
                                 # per-policy — see §4.3 step 2.

fail_mode:                       # per detector class, when timeout/error (§5)
  tier1: fail_closed
  tier2: fail_closed
  performance: fail_closed
  cost: fail_closed

messages:
  block_fallback: "This request can't be completed under {use_case} policy. A specialist has been notified."
  escalate_user_notice: "Your request needs additional verification and has been routed for review."

escalation:
  notify: ["console", "webhook:${REVIEW_WEBHOOK_URL}"]
  quarantine_ttl_s: 3600

blocklist_extra: []
detector_params: {}              # optional per-detector overrides (e.g., toxicity cutoffs)
```

Validation: pydantic schema (`policy/schema.py`). Rules: action values ∈ {pass, edit, block, escalate}; `borderline_action` ∈ the same set and is **required** (ADR-017 — no default, because a silent default would decide the borderline band's behaviour for a policy author who never considered it); **only labels with a defined §6 transform may map to `edit`** — normatively `{pii.*, hallucination.*}`, derived from the §6 transform table as the single source and exported as `EDIT_ELIGIBLE_LABELS` (ADR-015); tau_low < tau_high; `consistency: on` ⇒ `streaming: false` (ADR-014); `cascade_probe` ∈ {on, off} (ADR-013); unknown keys rejected. Wildcards (`pii.*`) expand at load; a specific key (`pii.email: edit`) overrides its wildcard.

**YAML quoting (Q-09).** `consistency` and `cascade_probe` values **must be quoted** in policy files. PyYAML implements YAML 1.1, where the bare tokens `on`/`off`/`yes`/`no` resolve to *booleans* — so `cascade_probe: on` loads as `True` and fails validation. `streaming` is a genuine boolean and stays unquoted. The loader raises a targeted error for this case rather than a bare enum mismatch.

**Stage rule (ADR-015).** Label eligibility is necessary but not sufficient, and it is the only part of the rule a *schema* can check. An edit-mapped **signal** must additionally carry a `span` **or** be `stage: output_sentence` (the whole-sentence soften scope of §6). A signal satisfying neither has no editable extent, and §4.3 step 4 promotes it to ESCALATE. This is a per-signal runtime check in `policy/engine.py`, not a schema check. Consequence worth stating explicitly: `fast_consistency` is `output_full` and span-less by design, so mapping `hallucination.low_confidence: edit` yields ESCALATE at every firing — policies should map that label to its real consequence rather than rely on promotion (see `policies/support_bot.yaml`).

## 4. The policy engine — verdict state machine

### 4.1 Inputs
All fast-path signals for the current unit (input stage, or one output sentence + conversation-stage signals), plus policy, plus running verdict context.

### 4.2 Severity order (total order, fixed)
`BLOCK > ESCALATE > EDIT > PASS`

### 4.3 Algorithm (deterministic — FR-POL-001)
```
1. For each signal, for each label → look up action in policy.actions
     (specific > wildcard > default_action).
2. Band adjustment — applied PER LABEL (ADR-017), and ONLY to signals whose
   score_kind == "confidence" (ADR-012). detection-kind signals (including the
   deterministic numeric_claims at 1.0) BYPASS this step entirely.

   First partition the signal's labels using meta.enriched_labels (ADR-019):
     HOST     = labels absent from meta.enriched_labels   (the detector's own)
     ENRICHED = labels present in meta.enriched_labels    (appended by §2.2)

   HOST labels — by the signal's score:
     score >= tau_high            → drop the label (not firing)
     tau_low <= score < tau_high  → use policy.borderline_action        # ADR-017
     score < tau_low              → use the mapped action as-is

   ENRICHED labels — exactly two branches, and no third (ADR-019):
     score >= tau_high            → dropped, together with the HOST labels
     score < tau_high             → mapped action, UNADJUSTED.
                                    borderline_action NEVER applies here.

   A signal whose every label was dropped does not survive.
   Signal action = most severe among its SURVIVING labels.   # multi-label rule
3. Verdict = most severe action across surviving signals; none → PASS.
4. EDIT verdict: apply §6 transforms to every edit-mapped signal — at its span, or
   over the whole sentence when the signal is stage=output_sentence without a span;
   if an edit-mapped signal lacks a span AND is not stage=output_sentence
   → promote that signal to ESCALATE (safe upgrade — no editable extent; ADR-015).
5. Stamp: verdict, contributing signal_ids, policy_version → audit.
```

### 4.4 Streaming interaction
- PASS/EDIT: sentence (possibly transformed) is released; stream continues.
- BLOCK: stream terminated; `messages.block_fallback` sent; remaining upstream tokens drained & discarded (still audited).
- ESCALATE: stream terminated; **entire response** (released + unreleased parts) quarantined as a review item; user gets `escalate_user_notice`.

### 4.5 Input-stage verdicts
Input BLOCK/ESCALATE short-circuits before dispatch (no upstream call, no cost).

**Input EDIT is supported, as pre-dispatch redaction (ADR-020).** Spans are replaced in the prompt *before* the upstream call, the categories are audited, and dispatch proceeds — so the provider never receives the raw value. The input is fully buffered before dispatch, so this is strictly simpler than the mid-stream output-sentence case: no partial release, no recall problem, no latency race.

Two guards, both carried over rather than invented:
- the redacted prompt **re-runs `tier1_pii` once** before dispatch (the same transform-error guard §6 applies to edited output); a second failure promotes to ESCALATE and does **not** dispatch;
- the ADR-015 span-less rule applies at input too — an edit-mapped input signal carrying neither a span nor whole-sentence scope has no editable extent and is promoted to ESCALATE (§4.3 step 4).

This supersedes the v1 ban, which was unenforceable as written: it claimed schema enforcement, but `tier1_pii` runs at input **and** output (§2), so an edit-mapped `pii.*` label is legitimately edit-eligible at one stage and was silently barred at the other. A schema sees labels, not stages, and so could never have caught it.

## 5. Failure semantics (fail-open / fail-closed) — FR-POL-006

On `DetectorTimeout`/`DetectorError`, the gateway synthesizes:
```
labels: ["_meta.detector_failure"], meta: {detector, error_class}
```
Resolution by policy `fail_mode` for that detector's class:
- **fail_open** → log + metric `detector_failures_total`; proceed without that detector's signals.
- **fail_closed** → synthesized signal maps to ESCALATE (never silent BLOCK — a human sees why).
Changing any fail_mode is a policy-version change; changing the *mechanism* is AGENTS.md D7.

## 6. EDIT transformations

This table is the **single normative source for edit eligibility** (ADR-015): the set of
labels that may map to `edit` in §3 is derived from the trigger column, not maintained
separately. Adding a transform here is what makes a new label edit-eligible.

| Transform | Trigger labels | Behavior |
|---|---|---|
| `redact` | `pii.*` (span required) | replace span with `[REDACTED:{category}]`; multi-span safe (apply right-to-left). Applies at **both** stages: on an output sentence before release, and on the prompt before dispatch (input EDIT, §4.5 / ADR-020) |
| `soften` | `hallucination.*` (span, **or** stage=output_sentence → whole-sentence scope) | template rewrite: assertive claim → hedged form ("Based on available information, … may …") + append `⚠ unverified` marker; template list in `policy/actions.py`, not LLM-generated (deterministic, testable) |
Edited text re-runs `tier1_pii` once (guard against transform errors); a second failure promotes to ESCALATE. This applies to an edited output sentence before release **and** to a redacted prompt before dispatch — in the input case the promotion means the request is never dispatched at all.

## 7. Feedback loop mechanics (FR-FBK-001/002)

1. Review decisions: `approve` (release quarantined response; mark signals as FP candidates) / `reject` (confirm; TP).
2. `eval/override_report.py`: per use case, per label — fire counts, override rates, reviewer notes.
3. `eval/suggest_thresholds.py`: recompute τ_low/τ_high as conformal-style quantiles over (labeled-set ∪ override-adjudicated) non-conformity scores at the policy's target rate; output = **proposed YAML diff**.
4. Human applies diff → `policy_version` bump → demo shows changed behavior (charter S4). No auto-apply, ever.

## 8. Explicit exclusions (v1)
Token-level redaction inside a released sentence; recall of released sentences; LLM-generated rewrites; cross-use-case policy inheritance (each YAML standalone); deep-lane verdict changes.
