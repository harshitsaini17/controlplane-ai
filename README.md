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
| Deterministic detectors — `tier1_pii`, `tier1_blocklist`, `numeric_claims` | implemented, tested (3 of the 11 rows in `docs/04` §2) |
| Labeled eval dataset (280 cases) | authored and **frozen**; passes the consistency gate, **label review pending** |
| Audit DB schema | implemented |
| Model-backed detectors — injection, toxicity, consistency, grounding, NER enrichment | **not yet implemented** |
| Gateway hot path, policy engine, cost detectors | **not yet implemented** |
| Detector eval harness (`eval/run_all.py`) | implemented, tested — **3 of 11 detectors scored** |
| Latency / fault-injection / cost / leak-scan harnesses, dashboard, demo runner | **not yet implemented** |

`python -m eval.validate_dataset` passes. `python -m pytest` passes (433 collected: 431
pass, 2 `xfail`). Nothing in
`docs/07-demo-script.md` runs end to end yet.

**The three deterministic detectors were scored, two of them missed, and both were then
revised under disclosure rather than silently.** They were built from the `docs/04` §2
contracts and deliberately never iterated against the eval corpus, so the first scoring run was
genuine first contact with the labelled cases — and it went badly in two places. Both were
filed as deviations, ruled (ADR-025, ADR-026), revised from **named published specifications**,
and re-measured **exactly once**.

**The v1 figures are not overwritten and not deleted.** A detector revised *after* its failures
were measured is weaker evidence than one measured blind, however carefully the revision was
derived — so the report carries both columns, and the v1 baseline is **re-computed on every run**
from frozen `_v1_*.py` modules rather than transcribed from an older report:

| Detector | Metric | v1 (blind) | v2 (disclosed) | Status |
|---|---|---:|---:|---|
| `tier1_pii` | recall | 0.8361 | **0.8852** | target 0.95 **still MISSED** |
| `tier1_pii` | precision | 1.000 | **1.000** | no over-firing, either version |
| `numeric_claims` | precision | 0.2667 | **0.8571** | 33 false positives → 2 |
| `numeric_claims` | recall | 0.750 | 0.750 | unchanged — the gain is all precision |

- **`tier1_pii` still misses NFR-EVAL-001**, and the target was not moved to meet it.
  **Residual misses: 7/7 are the documented bare-7-digit scope exclusion (ADR-026 §3), verified
  programmatically — no unexplained failure.** That exclusion is a deliberate precision trade-off
  (a bare `NNN-NNNN` is indistinguishable from an order or ticket id) and it **costs known
  recall**, which is why it is named here and not only in the ADR. Tracked permanently under
  *Standing Limitations* in `docs/08`.
- **`numeric_claims` precision rose because a rule was deleted, not tuned.** ADR-025 removed the
  04 §2 "large-number" clause, which matched the digit runs inside SSNs, cards and phone numbers
  — 30 of its 33 false positives were `PII-*` cases. It classified **identifiers as statistics**:
  a flaw in the specified behaviour, not in the implementation of it, which is why it took a
  ruling rather than a patch. Recall did not move, so nothing was traded away for the gain.
- **`tier1_blocklist` reports every figure as `n/a`**, correctly: the shipped policies ship an
  empty `blocklist_extra` (its only documented term source, Q-15) and the corpus has no
  positives, so its recall is **undefined, not 1.0**.

The `numeric_claims` citation-marker list is now **normative** in `docs/04` §2.4.2 (ADR-025
closed Q-18; its Amendment 1 restricts `per` to attribution forms, so a rate like *"$4M per
year"* is no longer mistaken for a citation). The publication gate that question carried is
lifted: these figures are citable provided they are labelled v1 or v2.

## Setup

```sh
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q                       # 433: 431 pass, 2 xfail
.venv/bin/python -m eval.validate_dataset           # consistency gate (06 §2.4)
.venv/bin/python -m eval.validate_dataset --freeze  # + assert the dataset is the frozen one
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
| Tier-1 PII recall | `python -m eval.run_all` | `reports/eval_report.md` §NFR-EVAL-001 | v1 **0.8361** → v2 **0.8852** — target 0.95 **MISSED**, target unmoved (ADR-026 §5). Residual misses: 7/7 are the documented bare-7-digit scope exclusion (ADR-026 §3), verified programmatically — no unexplained failure. Standing Limitation, `docs/08` |
| Per-detector precision / recall / F1 | `python -m eval.run_all` | `reports/eval_report.md` §Detectors | **measured for 3 of 11 detectors**; 8 absent, reported as skipped. 136 of 218 labelled positives are unscored because their detector does not exist yet |
| Disclosed revision v1 → v2 (`tier1_pii`, `numeric_claims`) | `python -m eval.run_all` | `reports/eval_report.md` §Disclosed revision | `numeric_claims` precision **0.2667 → 0.8571** (recall flat at 0.750); `tier1_pii` recall **0.8361 → 0.8852** at precision 1.000 both. v1 columns are **re-computed every run** from frozen `_v1_*.py`, never transcribed |
| Per-use-case confusion matrix (FP/FN) | `python -m eval.run_all` | `reports/eval_report.md` §Policy-level confusion matrix | **not computed** — needs the policy engine; deriving it from labels alone would be circular |
| Calibrated τ + achieved rate | `python -m eval.run_all` | `reports/eval_report.md` §Threshold calibration | **not computed** — needs the confidence-kind detectors; τ stays `# SEED`, and a seed is never judge-facing |
| Fail-open / fail-closed behaviour | `python -m eval.fault_injection` | console + audit records | not yet measured |
| Cost saving from cascade (simulated) | `python -m eval.cost_simulation` | `reports/cost_simulation.md` | not yet measured |
| Feedback loop before/after | *(harness pending)* | `reports/feedback_loop_report.md` | not yet measured |
| No raw PII in logs/DB/reports | `python -m eval.pii_leak_scan` | console | not yet measured |

**The reports these rows cite are committed to this repository** (06 §8). A claims-table row
pointing at a file you cannot open is unverifiable, which defeats the only thing NFR-INT-001
promises — so a report travels in the same commit as the claim citing it. Reports are still
never hand-edited: re-run the command. `reports/eval_report.md` stamps the dataset digest, the
frozen-hash match, and the code commit that produced its numbers.

One report artifact is not a measurement: `reports/eval_report_prose_fix.diff` is the
**figure-identity proof** required by ADR-026 Amendment 2 clause (b). A stale sentence in the
report's own prose — claiming a publication gate that ADR-025 had already lifted — had to be
corrected *after* the single permitted re-measurement. The proof enumerates every one of the 3
differing lines out of 151 and shows all 276 numeric tokens on measurement-bearing lines
identical, so a reader can verify no figure moved instead of taking it on trust.

**The first three measured numbers landed with this commit; the rest are still blank on
purpose.** A placeholder number is worse than a blank, so a row flips only when a report
actually produces it, carrying its method and sample size. The detector rows above were
produced against the frozen 280-case dataset
(`b37d1909f5fb16db2b1fa38f5fbc64ceb70c3d02`), whose hash `eval/run_all.py` verifies before it
computes anything — so a number cannot be generated against a different corpus even by
accident. **Two of the three missed**, and they are reported as missed: see the paragraph
above and the two open deviations in `docs/08`.

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
tests/         433 tests, named against the requirement IDs they cover
tests/review/  independent checkpoint-review tests; its 2 xfail cases are documented
               limitations (Unicode homoglyph + zero-width email evasion), not
               pending fixes. The third was the comma-grouped-card false positive,
               which ADR-025 fixed — it is now a live regression assertion
reports/       committed measurement evidence — generated, never hand-edited (06 §8)
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
