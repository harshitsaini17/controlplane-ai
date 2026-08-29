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

`request_id` is **always populated**, including on the two ingress rejections above, and the
matching `X-ControlPlane-Request-Id` header is present per §1.1's "All responses carry" rule.
The id is therefore minted *before* use-case resolution: an id is a correlation handle for
one exchange, not a property of a successfully resolved policy, and the request an operator
most needs to look up is the one that was refused. It is the same id the audit record carries
whenever the request got far enough to produce one — a rejected request has no record, which
is why the id on a 400 correlates a log line rather than a row.

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
                                --  fail_mode_applied, ts, attributable_ms}. Operational
                                -- events, not content risks: no span, no plane, no label,
                                -- no text. `attributable_ms` = measured in-thread execution
                                -- (ADR-036 item 4), null when unmeasured; a duration is not
                                -- content, so NFR-SEC-001 does not reach it
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
  latency_json TEXT,            -- per-detector ms + total_attributable_overhead_ms +
                                --   upstream_ms + input_hold_ms + sentence_holds_ms[]
                                --   (ADR-030). All four ARE emitted. The vocabulary is CLOSED
                                --   and enforced here by check_latency_keys.
                                --   added_time_to_last_byte_ms is NOT a key of this column:
                                --   ADR-030 Amendment 1 re-sited it to 06 §4 as a
                                --   benchmark-client quantity, because "client-observed" names
                                --   a vantage the writer of this row does not have.
  -- Coverage: which detectors RAN for this request, and which were expected and did not
  -- (M-10). Absence of coverage is a fact a reader must be able to see, not infer from a
  -- short `signals_json`. `{}` means "coverage not recorded" and is distinct from
  -- `{"ran":[],"not_run":[]}` = "nothing ran and nothing was expected" — the same
  -- distinction ADR-027 Amendment 1 draws between `[]` and NULL. Any record the gateway
  -- writes for a completed request states both lists. **ADR-033 adds a third list,
  -- `unavailable[]`** ({detector, missing}): registered but unloadable at boot, which is
  -- neither a run nor an expected-and-skipped. A detector appears in AT MOST ONE of the
  -- three.
  detectors_json TEXT NOT NULL DEFAULT '{}',
  sampled_deep INTEGER DEFAULT 0,
  -- Crash-safety marker (M-13). `complete` = the lifecycle finished and `verdict` is final.
  -- `partial` = the handler died mid-flight after content was already released; the row
  -- records how far the request got. A column, not a JSON leaf: every aggregate over this
  -- table must be able to exclude partials, and a marker inside `actions_json` would let a
  -- crashed request's timings into a published number.
  record_status TEXT NOT NULL DEFAULT 'complete'
    CHECK(record_status IN ('complete','partial'))
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

The proposal/README show this shape (assembled from `audit_records`). The `fast_consistency`
signal below is **illustrative of the record shape, not of current behaviour**: SL-6 cut that
detector, so no signal carries `hallucination.low_confidence` today. The shape is what this
section specifies, and it is unchanged by which detectors happen to be implemented:
```json
{
  "request_id": "…", "use_case": "finance_advisor", "policy_version": 4,
  "verdict": "escalate",
  "signals": [{"detector":"fast_consistency","labels":["hallucination.low_confidence"],
               "score":0.41,"stage":"output_full","latency_ms":38.2}],
  "detector_failures": [{"failure_id":"…","detector":"tier2_toxicity",
                         "error_class":"DetectorTimeout","stage":"output_full",
                         "fail_mode_applied":"fail_closed","ts":"…",
                         "attributable_ms":27.4}],
  "contributing_signal_ids": ["…"], "failure_record_ids": ["…"],
  "actions": {"quarantined": true, "review_id":"…",
              "input_redactions": [{"stage":"input","category":"pii.ssn",
                                    "span":{"start":42,"end":53}}]},
  "model": {"tier_requested":"small","used":"openai/gpt-oss-120b",
            "upstream_class":"measured","cascade_escalated":true},
  "cost": {"tokens_in":812,"tokens_out":344,"est_usd":0.0041},
  "latency": {"total_attributable_overhead_ms":46.1,"upstream_ms":1240.0,
              "input_hold_ms":12.4,"sentence_holds_ms":[18.9,14.8]},
  "detectors": {"ran":["tier1_pii","numeric_claims"],
                "not_run":[{"detector":"fast_consistency","reason":"not_implemented"}],
                "unavailable":[{"detector":"tier2_toxicity","missing":"onnxruntime"}]},
  "record_status": "complete",
  "override": {"decision":"approve","note":"claim verified against filing","ts":"…"}
}
```

**`detectors` — coverage, and why it is not derivable from `signals` (M-10).** A detector that
runs and finds nothing emits no signal, so a short `signals` list is indistinguishable from a
check that never happened. `ran` lists every detector that executed; `not_run` lists every
detector the policy's configuration would have exercised for this request but which did not,
each with a `reason`.

**`record_status` — crash safety (M-13).** `complete` means the lifecycle finished and
`verdict` is final. `partial` means the handler died mid-flight **after** content had already
been released to the client: ADR-002 forbids recalling released text, so the honest record is
one that says how far the request got. On a `partial` row `verdict`, `latency` and `detectors`
are all as-far-as-it-got and **must not be aggregated as if complete** — the latency benchmark,
the FP/FN eval and the dashboard all filter `record_status = 'complete'`. It is a column rather
than a key inside `actions` precisely so that filter is expressible in SQL.

`reason` vocabulary — **`not_implemented`** (the detector has no live implementation in this
phase; see the deferred-scope register in 08). Extending this list is a doc change, as for any
other fixed vocabulary here.

**`unavailable` — registered but unloadable (ADR-033).** Entries are `{detector, missing}`, where
`missing` names the absent dependency (an import name, never a traceback). This is the third
lifecycle state and it is a **boot-time** fact: the detector has an implementation, so
`not_implemented` would be a false statement, and nothing ran, so it is **not** a
`DetectorFailureRecord` either. `dependency_unavailable` is deliberately **not** a `not_run`
reason — that would restate an environment fact once per request while leaving unanswerable
whether the coverage promise was ever keepable. A detector may appear in **at most one** of
`ran`, `not_run`, `unavailable`; the write path enforces that, as it already does for the first
two. Enforcement is at **boot**, mirroring FR-GW-006: any active policy mapping that detector's
class to `fail_closed` refuses the boot outright (04 §5).

**`{}` means "coverage not recorded"**, and is deliberately distinct from
`{"ran":[],"not_run":[]}`, which asserts that nothing ran and nothing was expected. This is the
same distinction ADR-027 Amendment 1 draws between `[]` and NULL: one is a fact about the
request, the other a fact about the recording. Every record the gateway writes for a completed
request states both lists; `{}` is what a record written outside that path carries.

Three properties of the field are load-bearing:

- **A not-run entry is not a `DetectorFailureRecord`.** A failure record means a detector ran
  and broke, and carries a `fail_mode_applied` because a policy resolved it. A not-run entry
  means no attempt was made, so there is no fault, no fail mode, and nothing for a policy to
  resolve. Collapsing the two would either invent failures that never occurred or hide gaps.
- **A detector switched off by policy is not listed**, because it was never expected. `not_run`
  answers "what did this configuration ask for and not get", and mixing deliberate
  configuration into it would make the field mean two things at once.
- **`ran` is a union across units.** One request is one record (FR-AUD-001) but a streaming
  response is many sentence units, so a per-unit list would be a list of lists answering a
  question nobody asks. The coverage question is "was this check ever applied to this
  response", and the union answers exactly that.

The concrete case this exists for: `finance_advisor` sets `consistency: "on"`, and
`fast_consistency` is Phase 5. Its records say so, in the record, rather than presenting a
consistency-free verdict as though the check had passed.

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
cp_enrichment_skipped_total{use_case,reason}                    # 04 §2.2 cap
cp_detector_unavailable_total{detector}                         # ADR-033 state (c)
cp_detector_timeout_abandoned_total{detector}                    # ADR-034 Part A
```
The definition of `cp_gateway_overhead_ms` / `latency_json.total_attributable_overhead_ms` is **normative in 06 §4** — implementations and dashboards must use that formula, not an ad-hoc one.

**ADR-030 renamed that key** (`gateway_overhead_ms` → `total_attributable_overhead_ms`; same formula, no longer the targeted figure) and added two series: `input_hold_ms` and `sentence_holds_ms` (a **list**, one entry per sentence — the only non-scalar in this vocabulary, because NFR-P-001 now takes percentiles over holds rather than over requests). This vocabulary is **enforced at the audit write path** by `check_latency_keys`, so these are the contract here. `input_hold_ms` and `sentence_holds_ms` **are emitted** on both delivery paths (ADR-030's targeted series; the list carries one entry per released unit, and one for the buffered response on a non-streaming pipeline per M-11). The **rename is emitted** as of 2026-08-28: the write path, `spans.py`'s enforced vocabulary and the single 06 §4 formula implementation all carry `total_attributable_overhead_ms`, and the function computing it was renamed with the key — a helper still called `gateway_overhead_ms` while writing the new key is the drift **M-20** was filed for. `added_time_to_last_byte_ms` is **not a key of this column at all**, and that is a decision rather than a pending item: **ADR-030 Amendment 1** re-sited it to **06 §4** as a benchmark-client quantity. Its definition begins "client-observed", and the gateway has no client vantage on either delivery path — a completed ASGI `send()` means *handed to the transport*, not received, the buffered write precedes the response by M-13's deliberate ordering, and the table is insert-only, so there is no later phase in which a post-delivery figure could arrive. Emitting a handoff delta under a name that promises a client stopwatch would have published a number whose label overstates it (AGENTS.md §7). It remains **published**, in the latency report, where the process holding the stopwatch is the one that measures it. **M-20's remainder closes with that re-siting**, not with an emission. The metric name `cp_gateway_overhead_ms` is **unchanged**: renaming a metric would orphan history for a figure whose definition did not change.

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
**differently** — ~12× when ADR-022 was written, 2.0× on the pair shipped since ADR-029,
which changes the size of the gap but not the need for the key — so `pricing.models` is
keyed by the same concrete ids `tiers` binds and
`audit_records.model_used` records — no new join, and re-pointing a tier keeps costs correct.
`est_cost_usd` resolves through `model_used` and is **never averaged across tiers**: an
average would erase the exact effect the cost plane exists to measure. Three behaviours keep
a gap loud rather than silent:

| situation | behaviour |
|---|---|
| model missing from `pricing.models` at runtime | `est_cost_usd` = **null** (not 0.0, not a guess) + `cp_pricing_missing_total` |
| **no dispatch** (04 §4.5 short-circuit), `measured` class | `tokens_in`/`tokens_out` = **0/0** and `est_cost_usd` = **0.0** — a *counted* zero, not an estimate; `model_used` stays null |
| **no dispatch**, `dev` class | `tokens_in`/`tokens_out` = **0/0**, `est_cost_usd` = **null** |
| provider declares `pricing: null`, `measured` class | boot **warning** naming the provider |
| model missing at boot **and** named in `tiers`, `measured` class | **hard boot failure** — it is on a routing path, so it will answer requests and produce unpriceable audit records |

The two **no dispatch** rows are the one place the null-not-zero rule inverts, and it
inverts because the quantity changes rather than the policy (owner ruling, 2026-08-28).
Row 1 is null because the cost is *unknown*; a short-circuited request sent nothing, so 0
tokens is a **count** and — on a provider whose accounting is trustworthy — 0.0 is a
**measurement** of what blocking before dispatch saved. Null there would delete the saving:
null is excluded from an average, so a pipeline blocking half its traffic pre-dispatch
would report the same mean cost as one blocking none. `dev` class stays null for the
ADR-018 reason and not for want of arithmetic — its figures are barred from every
judge-facing artifact, so a 0.0 from it would sit in the column those artifacts read.
`model_used` is null on both rows: no model answered, and naming one would invent a
dispatch.

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
