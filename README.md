# ControlPlane.ai — Real-Time AI Oversight Gateway

A reverse-proxy control plane that watches every LLM response across **Performance, Cost and
Responsibility** — and decides **Pass / Edit / Block / Escalate** per use-case policy, before
the user sees it.

The headline feature is that the decision is **configuration, not code**: the same response
passes on one use case, gets redacted on another, and is quarantined for human review on a
third, with no Python changed between them.

Built for the Accenture Innovation Challenge 2026, Round 2 (Problem Track 1).

---

## Status: spec-complete, implementation in progress

This is a **hackathon prototype**, and this README will not pretend otherwise while it is one.

| Area | State |
|---|---|
| Specification (`docs/00`–`08`) | complete — 23 ADRs ruled |
| Policy schema + 3 use-case policies | implemented, validated, tested |
| Detector contract (`Signal`, budgets, failure vocabulary) | implemented, tested |
| Labeled eval dataset (280 cases) | authored; passes the consistency gate, **label review pending** |
| Audit DB schema | implemented |
| Gateway hot path, detectors, policy engine | **not yet implemented** |
| Eval harness, dashboard, demo runner | **not yet implemented** |

`python -m eval.validate_dataset` passes. `python -m pytest` passes (234 tests). Nothing in
`docs/07-demo-script.md` runs end to end yet.

## Setup

```sh
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q             # 234 tests
.venv/bin/python -m eval.validate_dataset # dataset freeze gate (06 §2.4)
```

The full model stack (detectors, embeddings, NER) needs the CPU-only torch wheel installed
**first**, or pip pulls a multi-GB CUDA stack for no benefit — the latency budgets in
`docs/01` are CPU budgets. See AGENTS.md §10 for the exact sequence.

Secrets live in `.env` (gitignored); copy `.env.example` to start. Env var *names* are
normative in `docs/05` §6; values are never printed, logged, or committed.

## Reproducing every number (NFR-INT-001)

Each claim maps to one command that regenerates it. This is the project's integrity contract:
per AGENTS.md §7, no latency, accuracy, or cost figure appears in this README, the dashboard,
the business proposal, or the demo video unless it has a row here.

| Claim | Command | Report | Status |
|---|---|---|---|
| Gateway overhead P50/P95/P99 | `python -m eval.bench_latency` | `reports/latency_report.md` | not yet measured |
| Per-detector latency vs budget | `python -m eval.bench_latency` | `reports/latency_report.md` | not yet measured |
| Tier-1 PII recall | `python -m eval.run_all` | `reports/eval_report.md` §detectors | not yet measured |
| Per-detector precision / recall / F1 | `python -m eval.run_all` | `reports/eval_report.md` §detectors | not yet measured |
| Per-use-case confusion matrix (FP/FN) | `python -m eval.run_all` | `reports/eval_report.md` §policy | not yet measured |
| Calibrated τ + achieved rate | `python -m eval.run_all` | `reports/eval_report.md` §calibration | not yet measured |
| Fail-open / fail-closed behaviour | `python -m eval.fault_injection` | console + audit records | not yet measured |
| Cost saving from cascade (simulated) | `python -m eval.cost_simulation` | `reports/cost_simulation.md` | not yet measured |
| Feedback loop before/after | *(harness pending)* | `reports/feedback_loop_report.md` | not yet measured |
| No raw PII in logs/DB/reports | `python -m eval.pii_leak_scan` | console | not yet measured |

**There are no measured claims in this repo yet.** Every row above says so on purpose: the
harness that produces these numbers is not written, and a placeholder number is worse than a
blank. Rows flip to real figures as reports land, and each will carry its method, hardware,
and sample size next to the number.

Two provenance rules already constrain what may ever appear here:

- **Upstream class** (ADR-018) — the local development gateway's token accounting carries a
  fixed ~5000-token offset, so it is classed `dev` and `eval/` refuses to produce reports
  from it unless run with `--allow-dev`, which stamps `DEV-TAINTED` into the filename.
- **Price provenance** (ADR-022) — no first-party Groq price table is currently reachable, so
  the cost simulation may report a **relative** delta (robust to a proportional error in both
  tiers) but not an absolute dollar figure. See `docs/08` Q-02.

## Repository layout

```
docs/          the specification — 00 charter … 08 open questions. Read 00, 02, then 04.
controlplane/  gateway, detectors, policy engine, audit, telemetry
policies/      one YAML per use case — the behaviour lives here, not in Python
config/        upstream providers + price table (05 §6.1)
eval/          labeled dataset + evaluation harness (06)
tests/         234 tests, named against the requirement IDs they cover
AGENTS.md      binding operating manual for coding agents on this repo
```

## Reading the specification

`docs/` was written before the code, deliberately — the docs are the contract, and code that
disagrees with them is presumed wrong until a human rules otherwise. Start with
`docs/00-charter.md` (why), then `docs/02-architecture.md` (shape), then
`docs/04-policy-and-detection-spec.md` (the core: detector contracts, policy schema, and the
Pass/Edit/Block/Escalate state machine). `docs/03-decisions.md` records why each choice was
made, including the ones that were overruled.

## License

Not yet chosen — see `docs/08-open-questions.md`.
