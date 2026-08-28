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
| Specification (`docs/00`–`08`) | complete — **31** ADRs ruled in `docs/03` (count pinned by `tests/test_readme_status.py`, not maintained by hand) |
| Policy schema + 3 use-case policies | implemented, validated, tested |
| Detector contract (`Signal`, budgets, failure vocabulary) | implemented, tested |
| Deterministic detectors — `tier1_pii`, `tier1_blocklist`, `numeric_claims` | implemented, tested (3 of the 11 rows in `docs/04` §2) |
| Labeled eval dataset (280 cases) | authored and **frozen**; passes the consistency gate, **label review pending** |
| Audit DB schema | implemented |
| Model-backed detectors — injection, toxicity, consistency, grounding, NER enrichment | **not yet implemented** |
| Gateway hot path — ingress lane, sentence buffer, buffered + streaming delivery, SSE proxy, startup canary | implemented, tested |
| Policy engine — Pass/Edit/Block/Escalate, band logic, fail-open/fail-closed resolution | implemented, tested |
| Cost detectors (`cost_budget`) | **not yet implemented** |
| Detector eval harness (`eval/run_all.py`) | implemented, tested — **3 of 11 detectors scored** |
| Latency benchmark + fault-injection harness | implemented, tested — committed evidence in `reports/` |
| Cost-simulation / PII-leak-scan harnesses, dashboard, demo runner | **not yet implemented** |

`python -m eval.validate_dataset` passes, and so does `python -m pytest`. There is
deliberately **no literal test count here.** One goes stale the moment a test is added, and
three stale copies of the same number is exactly what `docs/08` **M-23** was filed for — so
the count now lives where it cannot drift: `.github/workflows/ci.yml` runs the suite, the
dataset freeze gate, the fault-injection invariants and the latency tripwire on py3.12 and
py3.14. A gate's current result is whatever that run reports, not whatever this file last
claimed.

Nothing in `docs/07-demo-script.md` runs end to end yet.

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

**The policy engine now produces verdicts, so the artifact judges actually ask for exists — as
two matrices, not one.** They answer different questions and 06 §3.3 makes keeping them apart
normative:

| Matrix | Signals | Agreement | What it does **not** say |
|---|---|---:|---|
| **A. Engine conformance** | synthesized from ground truth | **1.000** over 280 × 3 | nothing about detection quality — it *assumes* perfect detection |
| **B. End-to-end (partial)** | real detector emissions | **0.981** over 159 of 280 | nothing about the 8 absent detectors |

Two things about those numbers are stated here rather than left for a reader to discover.

**A's perfect diagonal is exactly the result our own evaluation plan warns about**, so it is
falsified instead of asserted: `tests/test_policy_matrix.py` injects the defects the ADRs exist
to prevent — ADR-012 band scoping, ADR-019 enriched-label handling, the ADR-015 span-less
promotion, the 04 §4.2 severity order, 04 §4.3 step-1 resolution — and **requires** the matrix
to disagree with each. All five are caught, and the two narrow ones land where the ADRs predict
(ADR-019 only on `hr_copilot`, ADR-015 only on `support_bot`). Agreement is meaningful only
because disagreement was reachable; a mutation the matrix could not see would forfeit the claim.

**B's 0.981 flatters the system, and the report says so with the mechanism.** Of 8 scored cases
carrying a detection failure only 3 produce a wrong verdict; the other 5 reach the right action
anyway — 4 because another label on the same case maps to an equally severe action, 1 because
most-severe convergence absorbed a false positive. Those failures are real and counted in the
detector section. B measures the **policy layer** honestly and would **overstate detection** if
read as a system score.
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
.venv/bin/python -m pytest -q                       # the suite; CI runs it on 3.12 + 3.14
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
| Gateway overhead P50/P95/P99 (`total_attributable_overhead_ms`) | `python -m eval.bench_latency` | `reports/latency_report.md` | **Measured, and deliberately not a verdict.** Streaming: P50 **0.25 ms** · P95 **0.48 ms** · P99 **1.46 ms** over 200 samples; non-streaming is a *different quantity*, tabulated apart at P99 **0.42 ms** (n=100). **ADR-030 withdrew this quantity's target**, so these figures carry no pass/fail — they are published exactly so a withdrawn target does not become a withdrawn number (the 06 §4 formula is unchanged, so they stay comparable to earlier runs). Client wall-clock − upstream (**4.14 ms** P99) is an upper bound only — it includes `TestClient` transport, which 06 §4 bars as the headline. **Measured with 3 of 11 detectors live** |
| Per-sentence and input-lane hold vs NFR-P-001 | `python -m eval.bench_latency` | `reports/latency_report.md` | **Met.** `input_hold_ms` P50 **0.13** / P99 **0.26** ms against < 40 / < 50 (n=200); `sentence_holds_ms` P50 **0.14** / P99 **0.77** ms against < 40 / < 100 (**n=238 holds**, not requests — a 10-segment response contributes 10 samples). ADR-030 re-scoped NFR-P-001 onto these two series and *derived* the targets from the 04 §2 budgets rather than fitting them. The margin is large because **only the Tier-1 regex detectors exist**: the same table's forward projection is what the figure becomes when Tier-2 lands, and it is arithmetic, not a measurement |
| Per-detector latency vs budget | `python -m eval.bench_latency` | `reports/latency_report.md` | **NFR-P-002 met for the 3 detectors that exist**, all with **0 timeout faults**: `tier1_pii` P99 **0.126 ms**/2 ms · `tier1_blocklist` **0.020 ms**/2 ms · `numeric_claims` **0.205 ms**/5 ms. The other **8 are not exercised** and their budgets are **untested, not met** — the report names them rather than showing zeros |
| Tier-1 PII recall | `python -m eval.run_all` | `reports/eval_report.md` §NFR-EVAL-001 | v1 **0.8361** → v2 **0.8852** — target 0.95 **MISSED**, target unmoved (ADR-026 §5). Residual misses: 7/7 are the documented bare-7-digit scope exclusion (ADR-026 §3), verified programmatically — no unexplained failure. Standing Limitation, `docs/08` |
| Per-detector precision / recall / F1 | `python -m eval.run_all` | `reports/eval_report.md` §Detectors | **measured for 3 of 11 detectors**; 8 absent, reported as skipped. 136 of 218 labelled positives are unscored because their detector does not exist yet |
| Disclosed revision v1 → v2 (`tier1_pii`, `numeric_claims`) | `python -m eval.run_all` | `reports/eval_report.md` §Disclosed revision | `numeric_claims` precision **0.2667 → 0.8571** (recall flat at 0.750); `tier1_pii` recall **0.8361 → 0.8852** at precision 1.000 both. v1 columns are **re-computed every run** from frozen `_v1_*.py`, never transcribed |
| Engine conformance matrix (**perfect detection assumed**) | `python -m eval.run_all` | `reports/eval_report.md` §Policy-level confusion matrices → A | **1.000** agreement on **280 cases × 3 use cases**. Measures the engine + policy layer *in isolation* — **not** a detection or end-to-end claim |
| That matrix's discriminating power | `python -m pytest tests/test_policy_matrix.py` | console | 5 injected ADR violations (ADR-012/019/015, 04 §4.2, 04 §4.3) — **all 5 detected**. A perfect diagonal is only evidence if disagreement was reachable |
| End-to-end matrix (**partial coverage**) | `python -m eval.run_all` | `reports/eval_report.md` §Policy-level confusion matrices → B | **0.981** (156/159) per use case, over the **159 of 280** cases whose every label a shipped detector can emit. **5 of 8 detection failures are masked** — invisible to the verdict, real in the detector section. NFR-EVAL-002 **met**, coverage limit stated |
| Calibrated τ + achieved rate | `python -m eval.run_all` | `reports/eval_report.md` §Threshold calibration | **not computed** — needs the confidence-kind detectors; τ stays `# SEED`, and a seed is never judge-facing |
| Fail-open / fail-closed behaviour | `python -m eval.fault_injection` | `reports/fault_injection_report.md` | **27/27 assertions passed.** SC-3 verified on a live class: one *identical* `numeric_claims` fault yields UC-1/UC-2 **pass** (`fail_open`, fault recorded but not verdict-driving) and UC-3 **escalate** (`fail_closed`) — the two facts stored separately per ADR-027 Amendment 1. No-fault controls included, so the escalation is falsifiable. **Coverage limit: 2 of 4 fault classes are exercisable** — `tier2` and `cost` have no live detector to carry a fault, so their configured modes are **untested, not met** |
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

**10 of the 14 rows above carry a measured figure; the remaining 4 are blank on purpose, and
they are blank for different reasons that this table keeps apart.** A placeholder number
is worse than a blank, so a row flips only when a report actually produces it, carrying its
method and sample size. `not yet measured` means the harness does not exist yet (3 rows);
`not computed` means the inputs do not exist yet (τ needs the confidence-kind detectors).

The third state proper — `not measured`, where the harness **runs** and deliberately returns
**no verdict** — currently occupies **no row**: NFR-P-001 vacated it when the per-hold series
landed. It stays reachable rather than retired, which is the point of building it: a benchmark
run carrying no streaming traffic still renders `not measured` for NFR-P-001 instead of
reporting a pass over an empty population. Reading any blank as a pass is the specific failure
this table is built to prevent.

The detector rows above were produced against the frozen 280-case dataset at **freeze 2** —
commit `f162959f7d29ead32342fd8744bd10ed244369af`, digest `6a3ecbbe75fd020b…` — whose hash
`eval/run_all.py` verifies before it computes anything, so a number cannot be generated against
a different corpus even by accident. Freeze 1 (`b37d1909f5fb…`, digest `3b3931365a3c2918…`) is
**superseded** and is not what any figure here was computed against; it survives in 06 §2 as the
origin of the v1 baseline, and the v1 columns are re-computed each run from frozen `_v1_*.py`
against the *current* freeze rather than transcribed from that one. **Two of the three missed**, and they are reported as missed: see the paragraph
above. Both were filed as deviations and are now **ruled and closed** (ADR-026) — closing them
did not make the misses go away, it recorded them as **Standing Limitations** in `docs/08`,
where `SL-1` is the PII recall target that remains unmet and, per ADR-026 §5, unmoved.

Two provenance rules already constrain what may ever appear here:

- **Upstream class** (ADR-018) — the local development gateway's token accounting carries a
  fixed ~5000-token offset, so it is classed `dev` and `eval/` refuses to produce reports
  from it unless run with `--allow-dev`, which stamps `DEV-TAINTED` into the filename.
- **Price provenance** (ADR-022, amended by ADR-029) — the bound Groq models now carry
  **first-party** per-1M figures on Groq's own models page, so absolute dollar figures are
  publishable **for those two ids** (`openai/gpt-oss-20b`, `openai/gpt-oss-120b`) with their
  `source_url` and retrieval date. Any comparison priced on the retired llama pair stays
  barred — those figures were never first-party and the models no longer serve. Prices are
  re-verified at submission packaging. See `docs/08` **SL-3**.

## Repository layout

```
docs/          the specification — 00 charter … 08 open questions. Read 00, 02, then 04.
controlplane/  gateway, detectors, policy engine, audit, telemetry
policies/      one YAML per use case — the behaviour lives here, not in Python
config/        upstream providers + price table (05 §6.1)
eval/          labeled dataset + evaluation harness (06)
tests/         named against the requirement IDs they cover (`test_fr012_…`)
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
