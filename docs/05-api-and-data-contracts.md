# 05 — API & Data Contracts

Any endpoint, schema, config key, metric, or log field used in code MUST exist here first (AGENTS.md §4). Signal + policy schemas live in 04 and are referenced, not duplicated.

---

## 1. Gateway API

### 1.1 `POST /v1/chat/completions` (proxy surface — FR-GW-001)

OpenAI-compatible request body, passed through with these gateway extensions:

| Field / header | Required | Meaning |
|---|---|---|
| header `X-ControlPlane-Use-Case` | yes* | pipeline id, must match a loaded policy (*or resolved from API-key→use-case map in `config/keys.yaml`) |
| header `X-ControlPlane-Conversation-Id` | no | enables conv_tracker (FR-GW-005) |
| body `controlplane.context: [str]` | no | source documents → enables `rag_grounding` |
| body `stream: true\|false` | no | must be compatible with policy `streaming` flag, else `ERR-CFG-002` |

**Responses**
- PASS/EDIT: standard OpenAI-shaped response / SSE stream. Edited responses include header `X-ControlPlane-Actions: edit` and, non-streaming, `controlplane.actions: [...]` metadata block.
- BLOCK: HTTP 200 with assistant message = policy `block_fallback`, `controlplane.verdict: "block"`, `finish_reason: "content_filter"`.
- ESCALATE: HTTP 202, body `{verdict:"escalate", review_id, message: escalate_user_notice}`.
- All responses carry `X-ControlPlane-Request-Id`.

### 1.2 Errors

| Code | HTTP | Meaning | Retry |
|---|---|---|---|
| ERR-CFG-001 | 400 | unknown/unloaded use case | no |
| ERR-CFG-002 | 400 | stream flag conflicts with policy | no |
| ERR-UP-001 | 502 | upstream provider failure (after 1 retry) | yes |
| ERR-GW-001 | 500 | internal gateway error | yes |
Error body: `{error:{code, message, request_id}}`. Never include prompt/response content in error bodies.

## 2. Admin API (localhost/demo only — no auth in v1, stated limitation)

| Endpoint | Purpose |
|---|---|
| `GET /admin/review?status=pending` | list review items (quarantined responses; PII spans pre-redacted in the *listing view*); each item carries `escalation_cause` per ADR-027 — see below |
| `POST /admin/review/{review_id}` body `{decision: approve\|reject, note}` | HITL override (FR-AUD-002); approve releases stored response via `GET /admin/review/{id}/released` |
| `POST /admin/policies/reload` | hot-reload YAML (FR-CFG-002); returns loaded versions |
| `GET /admin/policies` | active policies + versions |
| `GET /metrics` | metrics snapshot JSON (dashboard + doc-07 reveals read this) |

**An escalation caused by a detector fault is labelled as one (ADR-027).** Every listed review
item carries `escalation_cause ∈ {content, detector_failure, both}`, plus
`failure_summary: [{detector, error_class, fail_mode_applied}]` when a fault contributed. A
reviewer opening the queue sees "detector `tier2_toxicity` failed under fail_closed" rather than
a bare quarantine, which is the difference between a decision they can action and one they must
reverse-engineer.

The field is **derived, not stored**: it is computed from the referenced
`audit_records.detector_failures_json` and the step-5 stamp (§4 `contributing_signal_ids` /
`failure_record_ids`), so there is one source of truth for why a verdict happened. The *stamp
itself* is stored, not derived (ADR-027 Amendment 1) — it is `escalation_cause` that is computed,
by reading those columns. `both` is a
real case — a content signal and a fault can escalate the same unit — and is reported as `both`
rather than collapsed to either side.

## 3. SQLite schema (ADR-006; WAL mode; append-only semantics for audit)

```sql
CREATE TABLE audit_records (
  request_id TEXT PRIMARY KEY, ts_utc TEXT, use_case TEXT, policy_version INTEGER,
  conversation_id TEXT NULL, stage_summary TEXT,          -- input|streamed|completed
  verdict TEXT CHECK(verdict IN ('pass','edit','block','escalate')),
  signals_json TEXT,            -- list[Signal] per 04 §1 (evidence fields only — no raw PII).
                                -- PURE Signals: a detector fault is never one (ADR-027)
  detector_failures_json TEXT,  -- list[DetectorFailureRecord] per 04 §5 (ADR-027):
                                -- {failure_id, detector, error_class, stage,
                                --  fail_mode_applied, ts}. Operational events, not
                                -- content risks: no span, no plane, no label, no text
  -- The §4.3 step-5 stamp (ADR-027 Amendment 1). JSON arrays of ids; `[]` when none
  -- contributed, NEVER NULL — `[]` is the fact "nothing did", NULL would say "we did
  -- not record". STORED, not derived: see the note below the table for why.
  contributing_signal_ids TEXT NOT NULL DEFAULT '[]',
  failure_record_ids TEXT NOT NULL DEFAULT '[]',
  actions_json TEXT,            -- transforms applied, spans, fallback used. Input-stage
                                -- redaction (ADR-020) records its stage, spans and
                                -- categories here — never the values (NFR-SEC-001)
  tier_requested TEXT CHECK(tier_requested IN ('small','frontier')),  -- tier picked pre-dispatch
  model_used TEXT,              -- CONCRETE provider model id that answered (not a tier name)
  upstream_class TEXT CHECK(upstream_class IN ('dev','measured')),    -- ADR-018 provenance
  cascade_escalated INTEGER,
  tokens_in INTEGER, tokens_out INTEGER, est_cost_usd REAL,
  latency_json TEXT,            -- per-detector ms + gateway_overhead_ms + upstream_ms
  sampled_deep INTEGER DEFAULT 0
);
CREATE TABLE review_items (
  review_id TEXT PRIMARY KEY, request_id TEXT REFERENCES audit_records,
  ts_created TEXT, quarantined_text TEXT,     -- stored ONLY here; PII spans masked at write time
  status TEXT CHECK(status IN ('pending','approved','rejected')),
  decision_ts TEXT NULL, reviewer_note TEXT NULL
);
CREATE TABLE deep_audit_results (
  request_id TEXT REFERENCES audit_records, ts TEXT,
  method TEXT,                  -- semantic_entropy | fairness_spot
  result_json TEXT              -- clusters, entropy value, or fairness check outcome
);
CREATE TABLE metrics_events (   -- flat event stream; dashboard aggregates
  ts TEXT, name TEXT, value REAL, labels_json TEXT
);
CREATE TABLE cost_ledger (
  use_case TEXT, month TEXT, spent_usd REAL, PRIMARY KEY (use_case, month)
);
```
**Why both id lists are stamped (ADR-027).** An ESCALATE whose `contributing_signal_ids` is
empty and whose `failure_record_ids` has one entry is a detector outage under `fail_closed` —
not an unexplained quarantine. Without the second list, that record and a content escalation are
indistinguishable after the fact, and the reviewer has no way to tell which one they are looking
at. `detector_failures_json` is populated on **fail_open** too: a dropped detector that left no
trace is indistinguishable from one that ran and found nothing.

**The stamp is stored, not derived (ADR-027 Amendment 1).** It cannot be reconstructed by
filtering `detector_failures_json`, and the attempt misreports in both directions: that column
carries **fail_open** records too, so a filter would credit a failure that did not contribute;
and the ADR-027 escalate **floor** leaves a genuine content BLOCK standing, so a record can
hold both a fail_closed failure and a content-driven verdict at once. `contributing_signal_ids`
is likewise a strict subset of `signals_json` by design — the signals that *decided*, not the
signals that *fired*. Only an explicit write preserves any of these distinctions.

Rule: nothing outside `review_items.quarantined_text` ever stores model output verbatim, and that column is written **post-masking** of Tier-1 PII spans (NFR-SEC-001).

**Input EDIT leaves an audit trail, not a rewritten history (ADR-020).** Pre-dispatch
redaction mutates the prompt actually sent upstream, so the record must distinguish the
prompt *as received* from the prompt *as sent*. Neither is stored verbatim: `actions_json`
carries the stage, the spans and the categories only, which is enough to prove what was
removed without storing what it was.

## 4. Audit record — canonical JSON view

The proposal/README show this shape (assembled from `audit_records`):
```json
{
  "request_id": "…", "use_case": "finance_advisor", "policy_version": 3,
  "verdict": "escalate",
  "signals": [{"detector":"fast_consistency","labels":["hallucination.low_confidence"],
               "score":0.41,"stage":"output_full","latency_ms":38.2}],
  "detector_failures": [{"failure_id":"…","detector":"tier2_toxicity",
                         "error_class":"DetectorTimeout","stage":"output_full",
                         "fail_mode_applied":"fail_closed","ts":"…"}],
  "contributing_signal_ids": ["…"], "failure_record_ids": ["…"],
  "actions": {"quarantined": true, "review_id":"…",
              "input_redactions": [{"stage":"input","category":"pii.ssn",
                                    "span":{"start":42,"end":53}}]},
  "model": {"tier_requested":"small","used":"llama-3.3-70b-versatile",
            "upstream_class":"measured","cascade_escalated":true},
  "cost": {"tokens_in":812,"tokens_out":344,"est_usd":0.0041},
  "latency": {"gateway_overhead_ms":46.1,"upstream_ms":1240.0},
  "override": {"decision":"approve","note":"claim verified against filing","ts":"…"}
}
```

## 5. Telemetry names (fixed vocabulary)

Spans (recorded as latency_json keys + optional OTel export later):
```
cp.ingress  cp.input.tier1  cp.input.tier2  cp.cost.budget  cp.cost.route
cp.upstream  cp.out.tier1  cp.out.tier2  cp.out.consistency  cp.out.grounding
cp.policy.evaluate  cp.action.apply  cp.audit.write
```
Metrics (name → labels):
```
cp_requests_total{use_case,verdict}       cp_gateway_overhead_ms{use_case}   (histogram)
cp_detector_latency_ms{detector}          cp_detector_failures_total{detector,fail_mode}
cp_pii_intercepts_total{category,use_case}
cp_est_cost_usd_total{use_case,model}     cp_cascade_escalations_total{use_case}
cp_review_items_total{use_case,status}    cp_deep_audit_entropy{use_case}    (gauge)
cp_consistency_lagged_total{use_case}     cp_probe_rejections_total{use_case}
cp_fallback_engaged_total{from_provider,to_provider,reason}      # FR-GW-006
cp_pricing_missing_total{provider,model}                        # ADR-022
```
The definition of `cp_gateway_overhead_ms` / `latency_json.gateway_overhead_ms` is **normative in 06 §4** — implementations and dashboards must use that formula, not an ad-hoc one.

## 6. Config files

```
config/gateway.yaml   # see the amended schema below (ADR-018)
config/keys.yaml      # api_key → use_case map (demo keys only)
policies/*.yaml       # per 04 §3
eval/dataset/*.jsonl  # labeled cases per 06 §2
```

### 6.1 `config/gateway.yaml` schema (amended by ADR-018)

```yaml
price_table_version: 1           # bump whenever any price below changes
providers:
  - name: <str>                  # unique id, referenced by active_provider
    upstream_class: dev | measured    # ADR-018 — a provenance claim, see below
    base_url: <url>
    key_env: <ENV_NAME> | null   # env var NAME only; the value lives in .env
    pricing:                     # ADR-022 — keyed by CONCRETE model id, or `unmetered`
      source_url: <url>          # where these figures came from
      retrieved: <YYYY-MM-DD>    # when — a stale price is a wrong price
      models:
        <model_id>: {per_1k_in: <float>, per_1k_out: <float>}
    tiers:                       # tier name → CONCRETE provider model id
      small: <model_id> | null
      frontier: <model_id> | null
active_provider: <provider name>
usage_sanity:                    # FR-GW-006, as ruled by ADR-028
  canary_on_startup: <bool>
  method: local_estimate         # ONLY value — the reference count is repo-local; no
                                 # provider endpoint is ever the sole reference
  max_ratio: <float>             # > 1.0; reported must land in [est/max_ratio, est*max_ratio]
  min_delta_floor: <int>         # tokens; |reported - est| must ALSO exceed this to fail
```

**The canary's reference count is repo-local (ADR-028).** The superseded form compared a
provider endpoint (`count_tokens`) against a provider field (`usage.prompt_tokens`) — both sides
owned by the party being audited, so it was never an independent check. The estimator is repo
code (a deterministic chars-per-token heuristic, or a bundled local tokenizer) and its name is
recorded in the canary result. Failure requires **both** conditions: outside the ratio band
**and** an absolute delta above `min_delta_floor`. Consequence is unchanged — measured-class
fails boot, dev-class warns loudly and continues.

This invariant detects **gross accounting corruption**, which is its ADR-018 purpose. It
**explicitly does not claim** a fine-grained accounting audit: a local estimate cannot model a
provider's server-side chat template, so small disagreements are expected and are what
`min_delta_floor` absorbs. Where a provider does expose a genuine token-count endpoint, it MAY
appear as a supplementary cross-check row in the canary output — never as the primary reference.

**`upstream_class` is a provenance claim, not a label.** `measured` means the provider's
token accounting and prices are trustworthy, so data produced through it may carry
judge-facing numbers (AGENTS.md §7). `dev` means convenient for development but its usage
accounting is **not a measurement** — data from it is tainted and must never reach a
report, the README, the proposal, or the video. The class is stamped onto every audit
record and fixture (§3, §4) so provenance travels with the data instead of living in
someone's memory; `eval/` and `demo/` refuse dev-class data unless run with `--allow-dev`,
which taints output filenames.

**Tier names are `small` and `frontier`** — the two tiers of ADR-009's cascade. `tiers`
binds each to a concrete model id, which is why `audit_records` records `tier_requested`
(the pre-dispatch routing decision) *and* `model_used` (the concrete id that answered)
rather than conflating them under one "model" column.

**Pricing is keyed by model id, and is never estimated (ADR-022).** One price pair per
provider could not express a two-tier cascade whose whole premise is that the tiers cost
~12× differently, so `pricing.models` is keyed by the same concrete ids `tiers` binds and
`audit_records.model_used` records — no new join, and re-pointing a tier keeps costs correct.
`est_cost_usd` resolves through `model_used` and is **never averaged across tiers**: an
average would erase the exact effect the cost plane exists to measure. Three behaviours keep
a gap loud rather than silent:

| situation | behaviour |
|---|---|
| model missing from `pricing.models` at runtime | `est_cost_usd` = **null** (not 0.0, not a guess) + `cp_pricing_missing_total` |
| provider declares `pricing: null`, `measured` class | boot **warning** naming the provider |
| model missing at boot **and** named in `tiers`, `measured` class | **hard boot failure** — it is on a routing path, so it will answer requests and produce unpriceable audit records |

Both boot rows are **measured-class only**, and that scope is load-bearing rather than an
omission. A `dev`-class provider exists under ADR-018 precisely to be usable *while*
unpriceable — its numbers are barred from every judge-facing artifact anyway — so applying
the fatal row to it would refuse to boot the documented development path in order to
protect a report that path can never produce. The shipped `kiro-local` is exactly that
case: `pricing: null` with both tiers bound.

`pricing: unmetered` (the literal scalar, in place of the block) stays valid and is an
**affirmative claim** that no per-token charge exists — local compute. It yields
`est_cost_usd: 0.0`, which is a *measurement*. That is deliberately distinct from a missing
entry, which yields `null` because the cost is **unknown**: zero and unknown are different
facts and the schema keeps them apart. `price_table_version` is retained as a coarse
bump-on-change marker, but per-provider `retrieved` is the finer and more honest provenance.

Env vars: `UPSTREAM_API_KEY`, `GROQ_API_KEY`, `REVIEW_WEBHOOK_URL` (optional), `CP_DB_PATH`. Never printed, never committed (NFR-SEC-002).
