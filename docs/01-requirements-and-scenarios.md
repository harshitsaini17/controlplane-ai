# 01 — Requirements & Scenarios

ID conventions: `FR-<domain>-NNN` functional, `NFR-<domain>-NNN` non-functional.
Domains: GW gateway · DET detection · POL policy · CFG config · AUD audit · OBS observability · FBK feedback · EVAL evaluation · P performance.
Priorities: **P0** demo-critical · **P1** judged-differentiator · **P2** stretch.

---

## 1. Functional requirements

### Gateway (GW)

| ID | Pri | Requirement | Acceptance criteria |
|---|---|---|---|
| FR-GW-001 | P0 | Gateway exposes an OpenAI-compatible `/v1/chat/completions` endpoint and proxies to a configured upstream provider. | Existing OpenAI-SDK client works by changing only `base_url` + a `X-ControlPlane-Use-Case` header (or API-key mapping). |
| FR-GW-002 | P0 | Gateway supports streaming (SSE) responses with **sentence-level buffering**: tokens accumulate until sentence boundary, checks run, then the sentence is released or acted on. | For a flagged sentence, no part of it reaches the client. |
| FR-GW-003 | P0 | Every request is tagged with a use case; unknown use case → request rejected with a clear error. | 400 + `ERR-CFG-001`. |
| FR-GW-004 | P1 | Non-streaming mode supported (whole-response check) for batch-style use cases. | Config flag `streaming: false` per use case. |
| FR-GW-005 | P2 | Conversation ID accepted and threaded through for multi-turn tracking. | `X-ControlPlane-Conversation-Id` propagated to signals + audit. |

### Detection (DET)

| ID | Pri | Requirement | Acceptance criteria |
|---|---|---|---|
| FR-DET-001 | P0 | Tier-1 deterministic input+output scan: PII patterns (SSN, credit card, email, phone, API key) via compiled regex/Aho-Corasick; blocklist matching. | Detects all Tier-1 dataset cases; emits spans + labels; never logs raw matched values. |
| FR-DET-002 | P0 | Tier-2 prompt-injection classifier on input; toxicity classifier on output (small transformer, ONNX/CPU). | Scores in [0,1]; latency within NFR-P-002. |
| FR-DET-003 | P0 | Fast hallucination proxy: self-consistency score (2nd sampled completion, embedding cosine) **and/or** RAG grounding score when context is supplied. | Emits `hallucination.low_confidence` signal with score; method recorded in signal. |
| FR-DET-004 | P1 | Slow-path deep audit on sampled traffic: semantic-entropy style clustering (N=5 samples, NLI/embedding clusters) computed async; results land in audit + dashboard only. | Never blocks hot path (enforced by design; AGENTS.md §9.4). |
| FR-DET-005 | P1 | Signals are **multi-label**: one span can carry labels from multiple planes (e.g., fabricated fact about a person = `hallucination.*` + `privacy.person`). | Demonstrated by dataset case OVLP-01 in doc 06. |
| FR-DET-006 | P2 | Conversation-level cumulative tracking: running count/severity of PII and low-confidence signals per conversation; threshold breach emits `conversation.cumulative_risk`. | Demo beat 6 in doc 07. |
| FR-DET-007 | P1 | Cost detectors: per-request token/cost estimate; per-use-case budget check pre-dispatch; runaway-loop guard (max requests per conversation per minute). | Budget breach yields `cost.budget_exceeded` signal → policy decides. |

### Policy engine (POL)

| ID | Pri | Requirement | Acceptance criteria |
|---|---|---|---|
| FR-POL-001 | P0 | Policy engine converges all available signals and returns exactly one verdict: PASS, EDIT, BLOCK, ESCALATE, per the state machine in 04 §4. | Deterministic for identical inputs + policy version. |
| FR-POL-002 | P0 | Verdicts are driven **entirely by per-use-case YAML policy** (thresholds, label→action map, fail mode, geography flags). No use-case conditionals in code. | Changing YAML changes behavior with no code change; AGENTS.md §9.1. |
| FR-POL-003 | P0 | EDIT actions implemented: PII redaction (`[REDACTED:<category>]`) and epistemic softening of low-confidence claims (template-based). | Redacted output contains no span of the original match. |
| FR-POL-004 | P0 | BLOCK returns the use case's configured safe fallback message. | Message text from policy file. |
| FR-POL-005 | P0 | ESCALATE quarantines the response (not delivered), records a review item, and notifies (console/webhook stub acceptable). | Reviewer can approve (release) or reject (block) via admin endpoint. |
| FR-POL-006 | P1 | Detector timeout/error handled per policy `fail_mode` (fail_open vs fail_closed) — configurable per use case per detector class. | Fault-injection test in doc 06 §5. |

### Config (CFG)

| ID | Pri | Requirement |
|---|---|---|
| FR-CFG-001 | P0 | Policies are versioned YAML files validated against the schema in 04 §3; invalid policy refuses to load with a precise error. |
| FR-CFG-002 | P1 | Policy hot-reload (or one-command reload) so the demo can change behavior live. |
| FR-CFG-003 | P1 | Policy files carry `geography` and `risk_appetite` metadata used by label→action mapping (policies are data, not code — brief's "rigid rules age quickly"). |

### Audit & observability (AUD/OBS)

| ID | Pri | Requirement |
|---|---|---|
| FR-AUD-001 | P0 | Every request writes one append-only audit record (schema in 05 §4): signals, verdict, policy version, latencies, model, cost. Raw PII never stored. |
| FR-AUD-002 | P1 | Overrides (reviewer decisions) append to the same record lineage with reviewer note. |
| FR-OBS-001 | P0 | Metrics exposed: verdict counts by use case, detector latency histograms, gateway overhead, PII interception count by category, est. cost per use case. |
| FR-OBS-002 | P1 | Dashboard renders the doc-07 panels (verdict mix, latency, cost, interceptions) from live data. |

### Feedback loop (FBK)

| ID | Pri | Requirement |
|---|---|---|
| FR-FBK-001 | P1 | Reviewer overrides are aggregated into a per-use-case override report (which labels are over/under-firing). |
| FR-FBK-002 | P1 | A threshold-suggestion utility proposes new τ values from override history + labeled set; applying them = new policy version (human approves; closes the loop for charter S4). |

---

## 2. Non-functional requirements

| ID | Requirement | Target | Measured by |
|---|---|---|---|
| NFR-P-001 | Gateway hot-path overhead (everything except LLM inference), **streaming pipelines** (per the normative definition in 06 §4) | **P50 < 40 ms, P99 < 100 ms** on demo hardware (Python prototype; compiled-gateway roadmap in ADR-001). Non-streaming pipelines (UC-3, ADR-014) reported separately, no target | `eval/bench_latency.py`, method in 06 §4 |
| NFR-P-002 | Per-detector fast-path budgets | Tier-1 < 2 ms · Tier-2 < 25 ms · self-consistency < 60 ms (incl. 2nd-sample amortization strategy per 04 §2.3) | same |
| NFR-P-003 | Slow-path isolation | 0 hot-path awaits on async lane (static check + runtime assertion) | code review + test |
| NFR-EVAL-001 | Detector quality on labeled set | Tier-1 PII recall ≥ 0.95; injection/toxicity F1 reported honestly (no target-gaming — AGENTS.md §7) | `eval/run_all.py` |
| NFR-EVAL-002 | Policy-level confusion matrix (action taken vs action labeled) reported per use case | Report exists; no fixed target | same |
| NFR-SEC-001 | No raw PII in logs, traces, audit, fixtures output | grep-based CI check | `eval/pii_leak_scan.py` |
| NFR-SEC-002 | Secrets via env only; never committed | gitleaks or equivalent pre-commit | CI |
| NFR-INT-001 | Every judge-facing number reproducible by one repo command | README table maps number → command | manual check |

---

## 3. Demo scenarios (the three use cases)

These are simultaneously requirements, policy fixtures, and demo content. Full policies live in `policies/` per 04 §3.

**Normative UC values live in `policies/*.yaml` (ADR-016); this section lists distinguishing highlights only.** Where a value appears in both, the YAML is authoritative — do not treat an omission here as an unset value.

### UC-1 `support_bot` — customer-facing RAG support assistant
- Profile: external users, low latency, moderate strictness, EU geography.
- Policy highlights: PII → **EDIT** (redact); toxicity high → BLOCK, moderate → PASS; ungrounded/unsourced-numeric claim → **EDIT** (soften), low-confidence → ESCALATE (span-less by design, ADR-015); injection → BLOCK; deep-audit sampling 10%; budget $500/mo; `fail_mode: fail_closed` for Tier-1, `fail_open` for Tier-2 (availability over strictness), performance and cost.
- Demo role: shows EDIT actions and latency story.

### UC-2 `hr_copilot` — internal employee knowledge assistant
- Profile: internal users, relaxed grounding, **strict on personal-data exposure** (employee PII), US geography.
- Policy highlights: PII → BLOCK (not redact — internal policy choice); `privacy.person` → BLOCK (carries demo beat 4b); low-confidence → PASS with logged flag; toxicity moderate → PASS; `risk_appetite: medium`; highest budget ceiling of the three ($800/mo); sampling 5%; `fail_mode: fail_closed` for Tier-1 only, `fail_open` elsewhere.
- Demo role: shows the *same PII content* getting a different verdict than UC-1 → policy-as-config beat #4a.

### UC-3 `finance_advisor` — regulated decision-support tool
- Profile: high stakes, escalation-heavy, `fail_mode: fail_closed` everywhere, sampling 25%, **non-streaming** (`streaming: false` — full-response buffering so nothing precedes the verdict; ADR-014).
- Policy highlights: low-confidence claim → **ESCALATE** (quarantine + review); any PII → ESCALATE; unsourced numeric claims → ESCALATE; strict budget.
- Demo role: the signature moment — the identical low-confidence response that UC-1 *edits* is *escalated* here (beat #4b); also the override/feedback beat.

### Cross-cutting scenario requirements
- SC-1 (P0): One request whose response trips **two planes at once** (fabricated detail about a person → hallucination + privacy) resolved by multi-label convergence, not double-processing. (FR-DET-005)
- SC-2 (P1): Budget exhaustion mid-demo on UC-3 → BLOCK with cost fallback message. (FR-DET-007; live in demo beat 7b)
- SC-3 (P1): Detector fault injection → UC-1 fails open, UC-3 fails closed, side by side. (FR-POL-006)
- SC-4 (P2): Multi-turn conversation crossing cumulative-PII threshold. (FR-DET-006)
