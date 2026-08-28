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
| `tier1_pii` | input + output_sentence | <2 ms | `pii.*` | compiled regex + Aho-Corasick keyword sets; span-accurate for redaction. **Pattern set is normative in §2.5 (ADR-026), including two documented scope exclusions** |
| `tier1_blocklist` | input + output_sentence | <2 ms | `security.blocklist` | per-use-case extra terms via policy `blocklist_extra` |
| `tier2_injection` | input | <25 ms | `security.prompt_injection` | small transformer, CPU/ONNX; score = model prob |
| `tier2_toxicity` | output_sentence | <25 ms | `toxicity.*` | moderate vs high via detector-internal cutoffs (0.5/0.8 defaults; overridable in policy `detector_params`) |
| `fast_consistency` | output_full* | <60 ms | `hallucination.low_confidence` | 2nd sample at temperature; embedding cosine; *runs on accumulated response so far at each sentence boundary using the parallel-sample stream (see §2.3) |
| `rag_grounding` | output_sentence | <30 ms | `hallucination.ungrounded_claim` | only when request carries `context` docs; sentence-vs-context embedding entailment proxy |
| `numeric_claims` | output_sentence | <5 ms | `hallucination.unsourced_numeric` | **quantity-shaped** numerals only (§2.4, ADR-025 — the bare large-digit-run rule is DELETED) with no citation marker (§2.4.2) and no match in provided context; identifier structures are excluded by a pre-filter; high-stakes use cases map it to ESCALATE |
| `cost_budget` | input | <1 ms | `cost.*` | ledger lookup; token estimate via tokenizer count × price table |
| `loop_guard` | input | <1 ms | `cost.loop_detected` | sliding window per conversation |
| `conv_tracker` | conversation | <1 ms | `conversation.cumulative_risk` | running totals of pii/hallucination signals per conversation id — **`stage` ∈ {output_sentence, output_full, conversation} only** (ADR-021) |

**Stage names each detector's native granularity — the unit of text it consumes — not a whitelist of delivery modes:** a non-streaming pipeline buffers the full response and runs the `output_sentence` detectors over that buffered text (02 §4), so `output_full` marks the detectors that *cannot* work sentence-by-sentence rather than the only ones that run when a whole response is available (M-11, ratified 2026-08-27).

### 2.2 Enrichment stage — `entity_enricher` (ADR-011)

Runs after fast-path detection, before the policy engine. For each span-bearing `hallucination.*` signal: spaCy `en_core_web_sm` NER over the span (± its sentence window); a PERSON entity appends `privacy.person` to `labels` and `responsibility` to `planes` of the **same** signal (one-signal rule, FR-DET-005). Budget: **10 ms aggregate per sentence** (see below). Enrichment failure → skip + log; it never blocks and is not a policy `fail_mode` class.

**The budget is a per-sentence AGGREGATE, not a per-span allowance (ruled 2026-08-27; closes M-18).** The enricher gets **10 ms total per sentence**, however many spans that sentence carries. This replaces the earlier per-span reading, which could not bound a quantity NFR-P-001 attaches to: at 10 ms per span the composed per-sentence hold was `60 + 10k`, crossing the 100 ms P99 at **k = 4** (ADR-030's derivation). A budget that scales with span count is not a budget.

**On exceed:** stop — remaining spans are left unenriched — log, and increment `cp_enrichment_skipped_total{use_case,reason}` with `reason:"budget_exceeded"`. The same counter records the pre-existing failure path under `reason:"enrichment_failure"`, so "enrichment was skipped" is one countable fact with its cause attached rather than two half-visible ones. Semantics are deliberately identical to the failure path already specified above: it **never blocks**, and it is **not a policy `fail_mode` class** — a partly-enriched sentence proceeds to the policy engine exactly as an unenriched one does. Enrichment adds labels a policy may act on; its absence removes a possible escalation, never a delivery.

A skipped span is a legal signal, not a malformed one: ADR-019 rejects an *unrecorded* append and an `enriched_labels` entry with no matching label — neither describes a span that was never visited. The audit record is what makes the skip legible, which is why it is counted rather than silently absorbed.

**`meta.enriched_labels` is a contract, not a note (ADR-019).** The enricher MUST record every label it appends in `meta.enriched_labels`. §4.3 step 2 partitions a signal's labels on exactly this list — a host label is band-adjusted, an appended one is not — so an unrecorded append is silently mis-adjusted, and a recorded label that is not actually in `labels` describes a signal that does not exist. Both directions are therefore rejected at `Signal` construction (`detectors/base.py`), not merely documented: an unrecorded `privacy.person`, and an `enriched_labels` entry missing from `labels`, are both construction errors. The check lives in the model so a malformed signal cannot be built at all, rather than in the engine where it would surface only on the paths that happen to run.

### 2.2.1 `conv_tracker` accumulation scope (ADR-021)

`conv_tracker` accumulates **output-stage and conversation-stage signals only**. Input-stage signals are excluded: the control plane exists to stop the *assistant* disclosing data, and a user quoting their own order number or email is the normal case, not the risk — accumulating it would make cumulative risk fire on ordinary support conversations and would measure user behaviour instead of model behaviour. Input-stage PII is not ignored, it is acted on immediately by its own policy mapping at the input stage (and redacted pre-dispatch where the policy maps it to edit, §4.5); it simply does not accumulate.

**Dataset consequence (normative for 06 §2).** A multi-turn case is labelled **per breach unit** — the breaching turn's own labels plus the conversation-stage signal — never as the union of every turn's labels. This follows §4.1, where the evaluated unit is one output sentence plus conversation-stage signals, so ground truth describes the unit where the verdict lands. Earlier turns' PII is already scored by its own `pii.jsonl` cases; unioning would inflate per-detector recall denominators without changing any verdict.

### 2.3 Consistency modes & sample-lag semantics (ADR-014)

- `consistency: on` **requires `streaming: false`** (schema-enforced). The full response and a parallel 2nd sample are compared once, pre-delivery — the check is always available and nothing reaches the user before the verdict. (UC-3.)
- `consistency: on_sampled` (streaming; UC-1 at deep-audit rate): the 2nd sample streams in parallel from dispatch; at each sentence boundary the aligned prefix is compared **only if** sample-2 has ≥ 70% of the primary's released+buffered length. Otherwise the sentence proceeds *without* the signal, audited as `meta.consistency:"lagged"` and counted in `cp_consistency_lagged_total`; deep audit is the backstop.
- `consistency: off`: `rag_grounding` covers the performance plane where context exists.

Cost: ~2× tokens wherever sampling occurs — a policy knob (coverage vs cost), said openly in the demo.

### 2.4 `numeric_claims` — quantity shapes, identifier exclusion, citation markers (ADR-025)

The v1 contract read "currency/percent/**large-number** patterns". The bare large-digit-run
clause is **DELETED**: measured against the labelled corpus it produced precision 0.267,
because an SSN, a card number and a phone number are all runs of digits, so the clause
classified **identifiers as statistics** (D8). A numeral is now a claim only if it is shaped
like a *quantity*.

#### 2.4.1 Firing shapes — a numeral fires iff it carries at least one

| | shape | examples |
|---|---|---|
| (a) | adjacent currency symbol (`₹ $ € £ ¥`) or ISO code (`USD`, `EUR`, `INR`, `GBP`, …) | `$4,200`, `1200 USD` |
| (b) | percent sign, or the word "percent" | `34%`, `34 percent` |
| (c) | magnitude word or suffix in the same token group: `thousand`, `million`, `billion`, `trillion`, `lakh`, `crore`, or a `k`/`M`/`B` suffix on the numeral | `2.3 million`, `40k` |
| (d) | comma-grouped thousands separators | `1,234,567` — **subject to §2.4.3** |
| (e) | attached measurement unit from the starter list — time `ms/s/min/hr` · data `KB/MB/GB/TB` · distance `km/mi/m` · mass `kg/lb` · temperature `°C/°F` | `250 ms`, `1.5 GB` |

The unit list in (e) is a *starter* list, extensible per use case (§2.4.4).

#### 2.4.2 Citation marker — defined lexically (closes Q-18)

Searched in the **same sentence** as the numeral, case-insensitive. A marker suppresses the
signal. Lexical only by design: judging whether a citation actually *supports* the number is
entailment, which is `rag_grounding`'s job, not this detector's.

- attribution phrases: `according to`, `as per`, `reported by`, `as reported by`,
  `cited by`, `cited in`, `source:`, `based on`, `study by`, `survey by`, `data from`,
  `figures from`
- **`per` in an attribution form only** — three narrow shapes, never the bare token
  (D1 ruling, ADR-025 amendment 1):
  1. `as per` (retained from v1)
  2. determiner form — `per the`, `per this`, `per that`, `per its`, `per their`
  3. proper-noun form — `per` + a **capitalized** token: `per Gartner`, `per Reuters`
- a bracketed numeric reference — `[1]`-style
- a parenthetical author-year reference containing a 4-digit year — `(Chen 2024)`
- a URL — `http://`, `https://`, `www.`

**Why `per` is not a bare token.** ADR-025 first listed `"per "`. `per` in English is
overwhelmingly the **rate** preposition, so the bare token silenced every rate-shaped figure —
`$4 million per year`, `250 ms per request` — and rates are the shape financial and performance
claims most often take, on the detector whose UC-3 mapping is ESCALATE. Two frozen-corpus cases
labelled `unsourced_numeric` (HAL-049 `per day`, HAL-052 `per employee`) were suppressed by it.
The discriminator is grammatical: a rate takes a **lowercase common noun**; an attribution takes
**determiner + source** or a **proper noun**.

**Two documented edges of that discriminator, both stated rather than discovered later:**

| shape | behaviour | why it is the acceptable direction |
|---|---|---|
| sentence-initial `Per company filings, …` | **fires** (no marker — the object is a lowercase common noun) | a false positive on a cited claim: costs a softening or a review. The opposite error costs an unsourced figure reaching a user, and this label maps to EDIT/ESCALATE |
| capitalized unit or acronym rate — `per GB`, `per API call` | **suppressed** (reads as a proper noun) | a false negative, but measured exposure on the frozen corpus is **zero cases**, so it moves no number. Separating it from `per Gartner` needs a lexicon, which this lexical detector deliberately does not carry |

The case-sensitivity of shape 3 is **load-bearing**: the marker pattern is globally
case-insensitive, so that branch scopes the flag off. An unscoped `[A-Z]` would match lowercase
and readmit the rate preposition wholesale — reintroducing the defect while looking correct.

#### 2.4.3 Identifier exclusion — mechanism and precedence, normative

A **pre-filter inside `numeric_claims`**. It shares no code path, ordering dependency, or
output with `tier1_*` — §9.3's independent-detectors rule stays intact, and the phone/card
structures below are a deliberate *structural duplicate* of those regexes, never a call into
them. It runs **FIRST** and is **ABSOLUTE**: an excluded candidate never reaches the shape
branches above, even when currency- or percent-adjacent.

Excluded structures:

1. Luhn-valid 13–19 digit sequences, with or without space / dash / comma grouping
2. SSN shape `ddd-dd-dddd`
3. phone shapes per the §2.5 v2 pattern set (E.164 and NANP forms)
4. digit runs embedded inside alphanumeric tokens — order ids, hashes

**Accepted consequence, documented rather than discovered:** a currency-prefixed Luhn-valid
amount will not fire. Conservative silence is correct for a detector whose subject is unsourced
statistics — a false ESCALATE on UC-3 costs a human review cycle, and the exclusion is absolute
precisely so its behaviour is predictable rather than order-dependent.

#### 2.4.4 Extension point

`units` and `citation_markers` are extensible per use case via policy `detector_params`, whose
values are **scalars or lists of scalars** (§3; D2 ruling 2026-08-26). The field was originally
typed `dict[str, dict[str, float]]` — shaped by `tier2_toxicity`'s cutoffs, the only consumer
that existed when it was written — so this extension point could not be expressed until the
type was widened. It now can:

```yaml
detector_params:
  numeric_claims:
    units: [ms, s, GB, bps]              # replaces the §2.4.1(e) starter list
    citation_markers: ["per our filing"] # adds to the §2.4.2 list
```

The lists in §2.4.1(e) and §2.4.2 remain the **defaults**, and remain normative wherever a
policy does not override them.

### 2.5 `tier1_pii` v2 pattern set — spec-derived, with two scope exclusions (ADR-026)

Every v2 pattern derives from a **named published specification**, cited so the derivation is
auditable rather than asserted. This matters because the v1 measurement (recall 0.8361) was
taken *before* its failures were known: a pattern written afterwards could have been shaped to
the failing fixtures, and only a spec citation distinguishes a real format rule from a
test-fitted one.

| shape | specification | rule |
|---|---|---|
| phone, international | **ITU-T E.164** | leading `+`, country code, ≤ 15 digits total, optional space/dash grouping |
| phone, NANP parenthesized | **NANP** conventions | `(NPA) NXX-XXXX`, with the spec's `N ∈ [2–9]` constraint on the first digit of both area code and exchange |
| phone, NANP dot-separated | **NANP** conventions | `NPA.NXX.XXXX`, same `N ∈ [2–9]` constraint |
| JWT / bearer token | **RFC 7519** (JWT) + **RFC 7515** (JOSE) | three dot-separated base64url segments at minimum plausible lengths. Anchoring on the `eyJ` prefix is **permitted and spec-derived**, though not by the arithmetic ADR-026 first gave (see its 2026-08-26 Correction): `base64url('{"')` is `eyI=`, and the third character encodes the low bits of `"` plus the **high bits of the next byte**, which yields `J` for any following letter. RFC 7515 §4 makes the header a JSON object and every registered parameter name starts with a letter, so the prefix is a property of the format, not of any sample. Bound: a pretty-printed header (`{ "alg"`) encodes to `eyIg…` and is missed |
| hex secret, 32 / 64 chars | — | fires **only** with a credential cue word in the same sentence: `key`, `token`, `secret`, `api_key`, `apikey`, `bearer`, `credential`, `password` |

The `N ∈ [2–9]` constraint is **spec conformance, and on this corpus it earns no precision**
(ADR-026 Amendment 1). It is genuinely in the NANP definition, which is why it belongs in a
spec-derived pattern — but in the *composed* detector it rejects nothing: v1's broader `_PHONE`
row is deliberately retained and evaluated first, matching the same extent, so longest-match-wins
hands it the span before either NANP row is consulted. Precisely:

- the constraint is **live only on shapes v1 did not cover** — chiefly `( 415 ) 555-0123`, the
  spaced-parenthesis variant v1's `\(\d{3}\)` could not match;
- **elsewhere the v1 pattern shadows it**, so the two NANP rows add **zero recall on this corpus**;
- the whole v2 phone gain is **E.164 plus the spaced-parenthesis variant**.

`(115) 555-0123` firing — an invalid NANP area code — is therefore **documented v1-superset
behaviour, not a bug.** The superset property is what makes the permanent v1 baseline meaningful:
narrowing `_PHONE` would change v1-derived behaviour, leaving the precision-1.000 figure
describing no code that ships. Hardening it is future work for a later freeze cycle, never
alongside a measurement.

**Two scope exclusions, precision-grounded DLP trade-offs and not fixture avoidance:**

1. **Bare 7-digit local numbers** (NANP local form, no area code) are out of scope.
   Structurally indistinguishable from order numbers, ticket ids and record ids — exactly the
   false-positive pressure `clean.jsonl` exists to apply.
2. **Bare 32/64-hex without a credential cue** is out of scope. It collides with git SHAs,
   MD5/SHA digests, dashless UUIDs and trace ids, all of which appear in legitimate support
   and engineering text.

Both exclusions **cost known recall** on the labelled set, and that cost is reported rather
than hidden: see 06 §3's revision-methodology requirement.

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
detector_params: {}              # optional per-detector overrides, keyed by registry name.
                                 # Values are scalars or lists of scalars (D2 ruling): floats
                                 # for `tier2_toxicity` cutoffs, string lists for
                                 # `numeric_claims` units/citation_markers (§2.4.4). A nested
                                 # mapping is rejected — this is not a config dumping ground.
```

Validation: pydantic schema (`policy/schema.py`). Rules: action values ∈ {pass, edit, block, escalate}; `borderline_action` ∈ the same set and is **required** (ADR-017 — no default, because a silent default would decide the borderline band's behaviour for a policy author who never considered it); **only labels with a defined §6 transform may map to `edit`** — normatively `{pii.*, hallucination.*}`, derived from the §6 transform table as the single source and exported as `EDIT_ELIGIBLE_LABELS` (ADR-015); tau_low < tau_high; `consistency: on` ⇒ `streaming: false` (ADR-014); `cascade_probe` ∈ {on, off} (ADR-013); unknown keys rejected. Wildcards (`pii.*`) expand at load; a specific key (`pii.email: edit`) overrides its wildcard.

**YAML quoting (Q-09).** `consistency` and `cascade_probe` values **must be quoted** in policy files. PyYAML implements YAML 1.1, where the bare tokens `on`/`off`/`yes`/`no` resolve to *booleans* — so `cascade_probe: on` loads as `True` and fails validation. `streaming` is a genuine boolean and stays unquoted. The loader raises a targeted error for this case rather than a bare enum mismatch.

**Message templates (owner ruling, 2026-08-28).** Both `messages.*` values are **templates**, rendered once at load. The only permitted placeholder is `{use_case}`; a literal brace is written doubled (`{{`). Any other placeholder — an unknown name, a positional `{}` or `{0}`, or attribute/index access such as `{use_case.__class__}` — is a **load-time validation error**, not a runtime one: the alternatives are raising inside a BLOCK (turning a refusal into a 500) or serving the raw template to the caller. Rendering happens in the schema rather than at the use sites because the two strings are read from nine places (six verdict branches in `policy/actions.py`, three audit `fallback_used` sites in `gateway/app.py`), and a renderer at the use site is one a tenth call site can forget. Consequence for 05 §3: the audit record's `fallback_used` stores the **rendered** text the caller received, which is what that field already claimed to record and is still operator-authored config rather than model output. Found by manual gateway testing — a live `hr_copilot` BLOCK returned the literal `under {use_case} policy` — and pinned by the `messages.*` rendering tests in `tests/test_policy_schema.py`.

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
5. Stamp: verdict, contributing signal_ids **+ failure_record_ids** (ADR-027),
   policy_version → audit.
```

**Request-level aggregation (owner ruling, 2026-08-28).** Steps 1–5 evaluate **one unit**, but
05 §3 has one `verdict` column per request. The stamped verdict is therefore the **most severe
action across every evaluated unit** of that request — the input lane (§4.5), every output unit,
and the conversation stage — under the §4.2 total order. Not the last unit's, and not the output
lane's alone: a request whose *prompt* was redacted did not "pass" because its response happened
to be clean. So an input-stage EDIT with a clean output stamps `verdict=edit`, counts in
`cp_requests_total{verdict=edit}`, and renders `X-ControlPlane-Actions: edit` per 05 §1.1; an
input EDIT alongside an output BLOCK stamps `block`.

The **evidence** carried with that stamp is the *union* over units, not the winning unit's row:
`detector_failures_json` is read off the stamped verdict, so keeping one unit's record would drop
a §5 fault from another unit whenever the two tied on severity. `contributing_signal_ids` and
`failure_record_ids` still filter that union against the stamped action, which is what keeps
"recorded but not contributing" (a `fail_open` fault under a PASS) representable.

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

On `DetectorTimeout`/`DetectorError` the gateway synthesizes a **`DetectorFailureRecord`** —
a distinct type, **never a `Signal`** (ADR-027):
```
{failure_id, detector, error_class, stage, fail_mode_applied, ts}
```
A detector fault is an **operational event, not a content risk**: no span, no plane, not
detector-emitted, and not mapped by the label→action table — `fail_mode` governs it, per
detector class. It therefore has no place in the closed §1.1 taxonomy, and `Signal` is right to
refuse it. `error_class` is a class **name**, never an exception instance or message: a
traceback can quote the very content under check (NFR-SEC-001). `fail_mode_applied` is filled
at resolution — it is a property of the decision, not of the fault, and is unknowable at fault
time.

Resolution by policy `fail_mode` for that detector's class — **semantics unchanged**:
- **fail_open** → proceed without that detector's signals; record the fault and increment
  `cp_detector_failures_total{detector,fail_mode}` (05 §5). Never silent: a dropped detector
  that left no trace is indistinguishable from one that ran and found nothing.
- **fail_closed** → the record forces an **ESCALATE floor** on the unit's verdict (never a
  silent BLOCK — a human sees why). A *floor*, not an override: §4.2 severity still lets a
  genuine content BLOCK win, so failure handling can never downgrade a block into a release.

Records travel in `detector_failures_json`, never `signals_json` (05 §3/§4), and the §4.3
step-5 stamp names contributing signal_ids **and** failure_record_ids — so an ESCALATE with
zero content signals is self-explaining rather than a bare quarantine. Changing any fail_mode
is a policy-version change; changing the *mechanism* is AGENTS.md D7.

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
