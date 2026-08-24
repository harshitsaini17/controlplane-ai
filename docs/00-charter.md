# 00 — Project Charter

**Project:** ControlPlane.ai — Real-Time AI Oversight Gateway
**Context:** Accenture Innovation Challenge 2026, Round 2 (Problem Track 1)
**One-liner:** A reverse-proxy control plane that watches every LLM response across Performance, Cost, and Responsibility — and decides Pass / Edit / Block / Escalate per use-case policy, before the user sees it.

---

## 1. Problem statement

Enterprises run many AI use cases at once (customer chatbots, internal copilots, decision-support in regulated workflows). Each carries a different risk signature, yet today's oversight is fragmented and after-the-fact: quality is evaluated offline weeks later, cost overruns surface at month-end, bias and data leakage appear in annual audits. There is no unified, real-time layer that inspects every response across accuracy, cost, and responsibility **before delivery** — and no way to vary that inspection per use case, geography, or risk appetite without rewriting code.

## 2. Why it matters (business case anchor)

- Regulatory pressure is operational now (EU AI Act obligations, Korea AI Framework Act, sector rules). Enterprises need **evidence of oversight** (audit trails), not policy PDFs.
- Hallucinated claims and PII leaks create liability at the moment of delivery; detection after user action is too late.
- Inference spend is unmanaged; routing + cascading demonstrably cuts 40–60% of cost in published work (FrugalGPT, RouteLLM) — a self-funding argument for adopting the gateway.

## 3. Target users

| User | Need |
|---|---|
| Platform/AI engineering team | Drop-in oversight without per-app SDK rewrites (change `base_url` only) |
| Risk / compliance officer | Per-use-case policies, audit trail, FP/FN reporting |
| Finance / FinOps | Per-tenant, per-use-case cost attribution and budget enforcement |
| Human reviewer (HITL) | Quarantine queue for escalated responses; override capture |

## 4. Goals (Round 2)

- G1. Working gateway prototype demonstrating the core mechanism end-to-end on simulated traffic.
- G2. **Per-use-case configurable policy layer** as the headline feature: identical content can receive different verdicts in different pipelines, purely via config.
- G3. Honest, measured evidence: FP/FN rates on a labeled dataset; latency overhead benchmark; cost simulation.
- G4. Judge-facing deliverables: business proposal, public GitHub repo, README, demo video.

## 5. Non-goals (scope firewall — violating these requires a charter change)

- NG1. No production-grade HA, autoscaling, Kubernetes, or multi-region anything.
- NG2. No inspection of model internals (weights/activations). We operate at the input/output layer only — matching the brief's "models consumed via API" constraint.
- NG3. No real enterprise or personal data. All traffic, PII, and documents are synthetic.
- NG4. No Go/Rust gateway. Python/FastAPI per ADR-001; performance claims are scoped accordingly.
- NG5. No training of custom models. We compose existing open models/classifiers and pattern matchers.
- NG6. No full agentic-action gating. We implement one lightweight conversation-level mechanism (cumulative risk tracking) as a differentiator, not a full agent firewall. (See Q-05.)
- NG7. No claim of "solving" hallucination. We detect, score, calibrate, and route under uncertainty.

## 6. Assumptions

- A1. Demo LLM traffic uses one cloud LLM API (or a local small model) with API keys available to the team; the gateway is provider-agnostic by design.
- A2. Judges evaluate governance depth, honesty of measurement, and demo clarity more than raw model quality.
- A3. Reference scale from the brief (tens of thousands of interactions/week) is simulated via replayed synthetic traffic, not live load.
- A4. Regulatory jurisdictions referenced (EU/US) are illustrative; policy layer treats geography as config data.

## 7. Constraints

- C1. Hackathon timeline; small team; agent-assisted ("vibe") coding governed by `AGENTS.md`.
- C2. Every judge-facing number must be reproducible by a script in the repo (AGENTS.md §7).
- C3. Deliverables: business proposal + prototype + public GitHub repo with demo video and README.

## 8. Success criteria

- S1. Demo script (doc 07) runs end-to-end without manual patching; signature moment (same response, two verdicts) works.
- S2. Gateway hot-path overhead measured and reported (target NFR-P-001: P99 < 100 ms in Python prototype; see 01).
- S3. Detector FP/FN report generated from the labeled dataset (doc 06) with a per-action confusion matrix.
- S4. At least one full feedback-loop cycle demonstrated: escalation → human override → threshold/config update → changed behavior, with audit trail.
- S5. All Round 2 deliverables submitted; README explains how to reproduce every number.

## 9. Key risks & mitigations

| Risk | Mitigation |
|---|---|
| Latency claims from Round 1 (<15 ms) unreachable in Python | Re-scope claims to measured Python numbers; keep the *architecture* story (fast/slow split) intact; note compiled-gateway path as roadmap (ADR-001) |
| Judge model / API flakiness during demo | Local fallback model + recorded traffic replay mode in demo script |
| Over-flagging makes demo look annoying | Tune thresholds on the labeled set; show the tuning dial explicitly (it's a brief requirement, not a bug) |
| Citation/stat credibility (Round 1 issues) | All citations verified against real venues; all stats sourced or removed (see 03-decisions ADR-008) |
| Scope creep via exciting ideas | Non-goals above + AGENTS.md D6 stop condition |

## 10. Glossary (project vocabulary)

- **Use case / pipeline** — a configured application consuming the gateway (e.g., `support_bot`), owning one policy profile.
- **Plane** — one of the three risk dimensions: Performance, Cost, Responsibility.
- **Signal** — a detector's structured output (multi-label; see 04 §2).
- **Verdict / action** — the policy engine's decision: PASS, EDIT, BLOCK, ESCALATE.
- **Fast path / hot path** — synchronous checks executed before a buffered sentence is released.
- **Slow path / deep audit** — asynchronous sampled analysis (semantic entropy, fairness) that never blocks a response.
- **Fail-open / fail-closed** — per-use-case behavior when a detector errors or times out (release vs. hold).
