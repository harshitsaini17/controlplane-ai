# 02 — System Architecture

Level-1/2 narrative only. Contracts and schemas live in 04/05; rationale lives in 03.

---

## 1. Architecture style

Single-process **FastAPI reverse proxy** (async) + background worker task queue, backed by SQLite (audit + metrics) and file-based YAML policies. Deliberately monolithic for the prototype (ADR-001, ADR-006); component boundaries are enforced at module level so the story generalizes to a deployed control plane.

```
                          ┌──────────────────────────────────────────────┐
                          │            CONTROLPLANE GATEWAY               │
   client apps            │                                              │
 (per use case)           │  ┌────────────┐   ┌───────────────────────┐  │
 ┌────────────┐  HTTPS    │  │  INGRESS   │   │   POLICY STORE        │  │
 │ support_bot├──────────►│  │ use-case   │◄──┤ policies/*.yaml       │  │
 │ hr_copilot │           │  │ resolution │   │ (versioned, validated)│  │
 │ finance_adv│           │  └─────┬──────┘   └───────────────────────┘  │
 └────────────┘           │        ▼                                     │
                          │  ┌────────────────────────────────────────┐  │
                          │  │ PRE-INFERENCE (input lane)             │  │
                          │  │ T1 PII/blocklist → T2 injection →      │  │
                          │  │ cost: budget gate + router/cascade     │  │
                          │  └─────┬──────────────────────────────────┘  │
                          │        ▼                                     │
                          │  ┌──────────────┐    upstream LLM API(s)     │
                          │  │  DISPATCHER  ├──────────────────────────► │
                          │  │  (streaming) │◄────────────────────────── │
                          │  └─────┬────────┘   SSE tokens               │
                          │        ▼                                     │
                          │  ┌────────────────────────────────────────┐  │
                          │  │ SENTENCE BUFFER (post-inference lane)  │  │
                          │  │ per sentence: T1 PII → T2 toxicity →   │  │
                          │  │ fast hallucination proxy (FR-DET-003)  │  │
                          │  └─────┬──────────────────────────────────┘  │
                          │        ▼                                     │
                          │  ┌──────────────┐   ┌─────────────────────┐  │
                          │  │ POLICY ENGINE│──►│ ACTIONS             │  │
                          │  │ converge     │   │ PASS: release        │  │
                          │  │ signals →    │   │ EDIT: redact/soften  │  │
                          │  │ verdict      │   │ BLOCK: fallback msg  │  │
                          │  └─────┬────────┘   │ ESCALATE: quarantine │  │
                          │        │            └─────────┬───────────┘  │
                          │        ▼                      ▼              │
                          │  ┌───────────┐        ┌──────────────┐       │
                          │  │ AUDIT LOG │        │ REVIEW QUEUE │◄─HITL │
                          │  │ (append)  │        │ + overrides  │       │
                          │  └─────┬─────┘        └──────┬───────┘       │
                          │        │   async lane        │               │
                          │  ┌─────▼─────────────────────▼────────────┐  │
                          │  │ DEEP AUDIT WORKERS (sampled)           │  │
                          │  │ semantic-entropy clustering · fairness │  │
                          │  │ spot checks · drift stats → dashboard  │  │
                          │  └─────────────────┬──────────────────────┘  │
                          │                    ▼                         │
                          │              ┌──────────┐                    │
                          │              │DASHBOARD │                    │
                          │              └──────────┘                    │
                          └──────────────────────────────────────────────┘
```

## 2. The three planes (logical view)

Planes are **signal families**, not separate services. Detectors emit multi-label signals; only the policy engine converges them (AGENTS.md §9.3).

| Plane | Fast path (sync, per sentence/request) | Slow path (async, sampled) |
|---|---|---|
| Performance | self-consistency score OR RAG grounding score | semantic-entropy clustering (N=5), drift stats |
| Cost | budget gate, token estimate, router/cascade choice | cost-per-outcome aggregation, loop analytics |
| Responsibility | T1 PII/blocklist, T2 injection (input) / toxicity (output) | fairness spot checks, safety-taxonomy sampling |

## 3. Fast path / slow path contract

- **Fast path** runs inside the request lifecycle. Detectors run concurrently per sentence buffer (asyncio.gather); each has a latency budget and a per-use-case `fail_mode` (04 §3.4).
  - **Concurrency trigger (ADR-030).** `pipeline.run_lane` is deliberately **sequential today** and goes parallel when the **first Tier-2 detector lands**. With three regex detectors at ~0.2 ms each, `gather` cannot overlap CPU-bound work on one event loop and would make each detector's recorded `latency_ms` include the others' — a measurement decision, documented at `pipeline.py:212`. A transformer forward pass releases the loop, so at Tier-2 the concurrency is real, lane composition becomes `~max` rather than `sum`, and per-task timing survives because `gather` preserves it. Until then, switching would change the conditions of the shipped measurement for no gain.
- **Slow path** consumes a sampled copy of (request, response, signals) from an in-process queue. It may enrich the audit record and dashboard; it may **never** alter a verdict already delivered, and nothing on the hot path awaits it (NFR-P-003). Its findings influence the future only via the feedback loop (thresholds/policy updates).

## 4. Request lifecycle (streaming, happy-ish path)

```
t0    ingress: resolve use case → load policy version
t0+   input lane: T1 scan → T2 injection → budget gate → router picks model tier
      policy cascade_probe:on → buffered small-tier probe; confidence ≥ τ_route ?
        deliver probe text via the sentence pipeline : re-dispatch frontier (ADR-013)
t1    dispatch upstream; tokens stream back
      (policy streaming:false → buffer fully, run all checks incl. consistency,
       single verdict, deliver whole response — ADR-014; UC-3 path)
per sentence s_i:
      buffer until boundary → fast detectors (parallel) → policy engine verdict
      PASS  → release s_i to client stream
      EDIT  → transform s_i, release, tag audit
      BLOCK → terminate stream, send fallback, close
      ESCALATE → terminate stream, quarantine full response, notify
tEnd  finalize audit record; sample? → enqueue deep audit
```

Key property: a flagged sentence is acted on **before any of it is released** (FR-GW-002). BLOCK/ESCALATE mid-stream means earlier, already-released clean sentences may have been seen — this is the documented trade-off of streaming interception (ADR-002) and is stated honestly in the proposal.

## 5. Cost plane placement

Routing is pre-dispatch (embedding intent → tier); the optional cascade probe (ADR-013) is fully buffered on the small tier — there is **never** a mid-stream re-dispatch. Budget enforcement is a *signal + policy action* like everything else (`cost.budget_exceeded` → typically BLOCK) — cost is not a special-cased subsystem, which is what makes the "one converged policy engine" claim true.

## 6. Feedback loop (closing the governance circle)

```
ESCALATE → review queue → human override (approve/reject + note)
        → override report per use case (FR-FBK-001)
        → threshold-suggestion utility (FR-FBK-002)
        → human applies → new policy VERSION (YAML diff, auditable)
        → behavior change demonstrable (charter S4)
```

## 7. Module layout (repo skeleton)

```
controlplane/
  gateway/        # FastAPI app, ingress, SSE proxy, sentence buffer
  detectors/      # tier1_patterns.py, tier2_classifiers.py, consistency.py, cost.py
  policy/         # schema.py (pydantic), engine.py, actions.py, store.py
  audit/          # records.py (append-only), review.py (queue + overrides)
  deep_audit/     # workers: entropy.py, fairness.py, sampler.py
  telemetry/      # metrics registry, OTel-style span names (05 §5)
policies/         # support_bot.yaml, hr_copilot.yaml, finance_advisor.yaml
eval/             # dataset/, run_all.py, bench_latency.py, pii_leak_scan.py
demo/             # run_script.py (doc 07), traffic fixtures, replay mode
dashboard/        # panels (tech per ADR-007)
docs/             # this hierarchy
```

## 8. External dependencies

Upstream LLM API (provider-agnostic; one configured + local fallback for demo resilience), sentence-transformers MiniLM (embeddings), spaCy `en_core_web_sm` (person-entity enrichment, ADR-011), one small ONNX/transformers classifier for injection + one for toxicity, SQLite, YAML. Everything else standard library / FastAPI ecosystem. New deps require an ADR note.
