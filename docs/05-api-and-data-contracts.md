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
| body `stream: true|false` | no | must be compatible with policy `streaming` flag, else `ERR-CFG-002` |

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
| `GET /admin/review?status=pending` | list review items (quarantined responses; PII spans pre-redacted in the *listing view*) |
| `POST /admin/review/{review_id}` body `{decision: approve|reject, note}` | HITL override (FR-AUD-002); approve releases stored response via `GET /admin/review/{id}/released` |
| `POST /admin/policies/reload` | hot-reload YAML (FR-CFG-002); returns loaded versions |
| `GET /admin/policies` | active policies + versions |
| `GET /metrics` | metrics snapshot JSON (dashboard + doc-07 reveals read this) |

## 3. SQLite schema (ADR-006; WAL mode; append-only semantics for audit)

```sql
CREATE TABLE audit_records (
  request_id TEXT PRIMARY KEY, ts_utc TEXT, use_case TEXT, policy_version INTEGER,
  conversation_id TEXT NULL, stage_summary TEXT,          -- input|streamed|completed
  verdict TEXT CHECK(verdict IN ('pass','edit','block','escalate')),
  signals_json TEXT,            -- list[Signal] per 04 §1 (evidence fields only — no raw PII)
  actions_json TEXT,            -- transforms applied, spans, fallback used
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
Rule: nothing outside `review_items.quarantined_text` ever stores model output verbatim, and that column is written **post-masking** of Tier-1 PII spans (NFR-SEC-001).

## 4. Audit record — canonical JSON view

The proposal/README show this shape (assembled from `audit_records`):
```json
{
  "request_id": "…", "use_case": "finance_advisor", "policy_version": 3,
  "verdict": "escalate",
  "signals": [{"detector":"fast_consistency","labels":["hallucination.low_confidence"],
               "score":0.41,"stage":"output_full","latency_ms":38.2}],
  "actions": {"quarantined": true, "review_id":"…"},
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
    price_per_1k_in: <float> | null    # null = unmetered / no measured price exists
    price_per_1k_out: <float> | null
    tiers:                       # tier name → CONCRETE provider model id
      small: <model_id> | null
      frontier: <model_id> | null
active_provider: <provider name>
usage_sanity:                    # FR-GW-006
  canary_on_startup: <bool>
  max_token_delta: <int>
```

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

Env vars: `UPSTREAM_API_KEY`, `GROQ_API_KEY`, `REVIEW_WEBHOOK_URL` (optional), `CP_DB_PATH`. Never printed, never committed (NFR-SEC-002).
