# Engineering notes

This file holds the detailed reasoning behind the README's summary claims, including the first-contact measurement story, dual-column v1/v2 evidence, demo decisions, status detail, M-23 rationale, and OVLP cut.

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
| Specification (`docs/00`–`08`) | complete — **36** ADRs ruled in `docs/03` (count pinned by `tests/test_readme_status.py`, not maintained by hand) |
| Policy schema + 3 use-case policies | implemented, validated, tested |
| Detector contract (`Signal`, budgets, failure vocabulary) | implemented, tested |
| Deterministic detectors — `tier1_pii`, `tier1_blocklist`, `numeric_claims` | implemented, tested (3 of the 11 rows in `docs/04` §2) |
| Live detector registry | **8 of the 11 `docs/04` §2 rows run in the gateway** — the three above plus `tier2_injection`, `tier2_toxicity`, `rag_grounding`, `cost_budget`, `loop_guard`, with `entity_enricher` live as the §2.2 enrichment stage |
| Labeled eval dataset (280 cases) | authored and **frozen**; passes the consistency gate, **label review pending** |
| Audit DB schema | implemented |
| Model-backed detectors — injection, toxicity, grounding, NER enrichment | implemented, tested — `fast_consistency` is **cut to roadmap** (SL-6), so it is the one model-backed row that does not ship |
| Gateway hot path — ingress lane, sentence buffer, buffered + streaming delivery, SSE proxy, startup canary | implemented, tested |
| Policy engine — Pass/Edit/Block/Escalate, band logic, fail-open/fail-closed resolution | implemented, tested |
| Cost detectors (`cost_budget`, `loop_guard`) | implemented, tested — deterministic, input-stage, 1 ms budget each. `cost.budget_exceeded` and `cost.loop_detected` are mapped to `block` by all three policies; `cost.request_too_large` is **mapped by none**, so it resolves to `default_action: pass` and is audit-visible only. Left unmapped rather than re-mapped to force a demo beat |
| Detector eval harness (`eval/run_all.py`) | implemented, tested — **5 of 11 detectors scored**; `rag_grounding` ships but is deliberately unscored there (its measurement is the calibration section — see `SL-7`) |
| Latency benchmark + fault-injection harness | implemented, tested — committed evidence in `reports/` |
| Demo runner (`demo/run_script.py`) | implemented, tested — beats 1-8 headless, **7 pass / 2 skipped / 0 fail** under `--replay`; the 2 skips are cut scope, named below |
| Console (`/console`) | implemented — three static pages (landing, verdict board, test chat) served same-origin by the gateway. Every static figure cites the committed report it came from. **Inherits the admin surface's documented lack of auth (`docs/05` §2: localhost/demo only) and widens it by nothing** |
| Cost plane — `cost_budget`, `loop_guard`, spend ledger, cost simulation | **enforces**, with one piece cut: the two detectors, the ledger they read and the simulation all ship, so all three planes now block on their own signals. Demo beat 7b blocks a budget-exhausted request **pre-dispatch, 0 upstream dispatches**. The **cascade router is not built** (`SL-10`), so the routing fraction the saving depends on is unmeasured — the simulation publishes a curve and names that gap rather than picking a point on it |
| PII-leak-scan harness, Streamlit dashboard | **not yet implemented** (the console above replaces the Streamlit plan for the demo) |

`python -m eval.validate_dataset` passes, and so does `python -m pytest`. There is
deliberately **no literal test count here.** One goes stale the moment a test is added, and
three stale copies of the same number is exactly what `docs/08` **M-23** was filed for — so
the count now lives where it cannot drift: `.github/workflows/ci.yml` runs the suite, the
dataset freeze gate, the fault-injection invariants and the latency tripwire on py3.12 and
py3.14. A gate's current result is whatever that run reports, not whatever this file last
claimed.

**`docs/07-demo-script.md` now runs headlessly** — `python -m demo.run_script --replay` executes beats 1-8 and
exits nonzero on any beat failure: **7 pass, 2 skipped, 0 fail**. The two skips are reported as skips rather
than passes, with their reason, because a green beat over unbuilt scope would be a fabricated capability:
**beat 6** (the feedback cycle) needs `eval/override_report.py`, still a stub, and **beat 7b** (budget
exhaustion) needs the cost plane. Its expectations come from the **frozen dataset**, never from what the run
observes — a suite that asserted whatever the gateway produced would pass unconditionally, and a test pins
that it can fail. Verdicts are read from the audit record rather than the HTTP body, because two of the three
policies stream and a JSON read would report a correct gateway as broken.

**The signature beat runs on PII-001, not the multi-label OVLP case.** The OVLP two-plane moment measured
10× on a quiet host at 2 of 3 policies correct, so it was **cut to roadmap** (`SL-9`) rather than scripted:
the demo never rests on an unreliable beat. PII-001 carries the property that matters — one identical
response, three verdicts, from configuration alone — and holds it deterministically, 3/3.

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
| **B. End-to-end (partial)** | real detector emissions | **0.851** / **0.851** / **0.825** over 194 of 280 | nothing about the 5 absent detectors |

Two things about those numbers are stated here rather than left for a reader to discover.

**A's perfect diagonal is exactly the result our own evaluation plan warns about**, so it is
falsified instead of asserted: `tests/test_policy_matrix.py` injects the defects the ADRs exist
to prevent — ADR-012 band scoping, ADR-019 enriched-label handling, the ADR-015 span-less
promotion, the 04 §4.2 severity order, 04 §4.3 step-1 resolution — and **requires** the matrix
to disagree with each. All five are caught, and the two narrow ones land where the ADRs predict
(ADR-019 only on `hr_copilot`, ADR-015 only on `support_bot`). Agreement is meaningful only
because disagreement was reachable; a mutation the matrix could not see would forfeit the claim.

**B's coverage grew from 159 to 194 cases, and its agreement fell — which is the honest direction.**
Three model-backed detectors joining the lanes made 35 more cases scorable, and those cases are
harder than the deterministic ones, so a rate computed over a broader and more demanding
population is *lower* and means *more*. The earlier 0.981 over 159 was not wrong; it covered less.
A rising coverage figure and a rising agreement figure would be the pair to distrust.

**B still flatters the system, and the report says so with the mechanism.** Of the **39** scored
cases carrying a detection failure, **34** produce a wrong verdict; the other **5** reach the
expected action anyway — **4** because another label on the same case maps to an action at least as
severe (a missed phone number beside a detected SSN moves no verdict), **1** because most-severe
convergence absorbed a false positive. Those failures are real and counted in the detector section.
B measures the **policy layer** honestly and would **overstate detection** if read as a system
score.
- **`numeric_claims` precision rose because a rule was deleted, not tuned.** ADR-025 removed the
  04 §2 "large-number" clause, which matched the digit runs inside SSNs, cards and phone numbers
  — 30 of its 33 false positives were `PII-*` cases. It classified **identifiers as statistics**:
  a flaw in the specified behaviour, not in the implementation of it, which is why it took a
  ruling rather than a patch. Recall did not move, so nothing was traded away for the gain.
- **`tier1_blocklist` reports every figure as `n/a`**, correctly: the shipped policies ship an
  empty `blocklist_extra` (its only documented term source, Q-15) and the corpus has no
  positives, so its recall is **undefined, not 1.0**.

**The injection detector fires precisely and rarely: precision 1.000, recall 0.150.** Blind first
contact on the frozen corpus (AGENTS.md §11.1 item 3) — measured once, against ADR-031's checkpoint,
with nothing tuned toward any number. It caught 3 of 20 labelled injections and produced **zero**
false positives over 50 scored cases.

Two things follow, and the second is the one that matters. **NFR-EVAL-001 sets no numeric target
here** — it requires injection/toxicity F1 "reported honestly (no target-gaming)", and Tier-1 PII
recall is the only accuracy figure in this repo with a threshold attached. So 0.150 is not a missed
target; it is a measured capability, and reporting it as a miss would invent a target that no
requirement states. **And it is one layer of a layered defense, not the defense.** What the 1.000
precision buys is that every fire is real, so the detector can be wired to **block pre-dispatch**
without an availability cost — demo beat 3 shows exactly that, blocked at the input lane for **0
upstream tokens**. What the 0.150 recall costs is that injection is not *solved* by this layer, and
the honest description of the system is that a determined injection attempt gets through this
detector 85% of the time and is then subject to every output-side check the response passes through.
Raising recall means moving the classifier's threshold, which trades precision away — the sweep that
would price that trade runs through the feedback loop, and the feedback loop is roadmap
(`eval/override_report.py` is a stub). So the trade is **named and unpriced**, not quietly made.

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
| Gateway overhead P50/P95/P99 (`total_attributable_overhead_ms`) | `python -m eval.bench_latency` | `reports/latency_report.md` | **Measured, and deliberately not a verdict.** Streaming: P50 **42.18 ms** · P95 **59.07 ms** · P99 **107.79 ms** over 200 samples; non-streaming is a *different quantity*, tabulated apart at P99 **20.41 ms** (n=100). These rose roughly 40× when the three model-backed detectors joined the lanes — a sum over per-sentence holds pays each per-sentence budget once per sentence, which is why ADR-030 stopped targeting this quantity and started targeting the hold. **ADR-030 withdrew this quantity's target**, so these figures carry no pass/fail — they are published exactly so a withdrawn target does not become a withdrawn number (the 06 §4 formula is unchanged, so they stay comparable to earlier runs). Client wall-clock − upstream (**110.57 ms** P99, n=200) is an upper bound only — it includes `TestClient` transport, which 06 §4 bars as the headline. **Measured with 6 of 11 detectors live** |
| Per-sentence and input-lane hold vs NFR-P-001 | `python -m eval.bench_latency` | `reports/latency_report.md` | **Met.** `input_hold_ms` P50 **20.86** / P99 **26.68** ms against < 40 / < 50 (n=200); `sentence_holds_ms` P50 **20.70** / P99 **31.40** ms against < 40 / < 100 (**n=231 holds**, not requests — a 10-segment response contributes 10 samples). ADR-030 re-scoped NFR-P-001 onto these two series and *derived* the targets from the 04 §2 budgets rather than fitting them. **This is now measured with Tier-2 live rather than projected**, which is the material change: the earlier sub-millisecond figures were taken with only the Tier-1 regex detectors, and the forward projection is what they were expected to become. They landed inside both targets, at roughly half the P99 budget for each series |
| Per-detector latency vs budget | `python -m eval.bench_latency` | `reports/latency_report.md` | **Five detectors measured on the instrument the runner actually enforces (ADR-036 Amendment 1); four inside budget, one breaching.** `tier1_blocklist` P99 **0.020 ms**/1 ms · `tier1_pii` **0.133 ms**/1 ms · `numeric_claims` **0.277 ms**/5 ms · `tier2_toxicity` **23.741 ms**/25 ms (n=283, 2 fail_open faults) — the rest with **0 faults**. `tier2_injection` P99 **25.348 ms**/25 ms (n=300, **0 faults**) reads **NO**: a genuine attributable breach, unit-clean because every frozen case is single-window, so the flat per-unit budget is the right comparand. Filed as `[D3-tier2-injection-attributable-p99-exceeds-25ms]` and published as measured — nothing tuned toward the target (AGENTS.md §7). The **previously published 25.569 / 25.114 ms** rows were rendered on wall-clock, the clock ADR-036 rejected; they are superseded, and preserved blockquoted in the report rather than deleted. Quiet host (load1 0.84), n=300. The remaining **5 are not exercised** — untested, not met |
| Tier-1 PII recall | `python -m eval.run_all` | `reports/eval_report.md` §NFR-EVAL-001 | v1 **0.8361** → v2 **0.8852** — target 0.95 **MISSED**, target unmoved (ADR-026 §5). Residual misses: 7/7 are the documented bare-7-digit scope exclusion (ADR-026 §3), verified programmatically — no unexplained failure. Standing Limitation, `docs/08` |
| Per-detector precision / recall / F1 | `python -m eval.run_all` | `reports/eval_report.md` §Detectors | **measured for 5 of 11 detectors**; 6 reported as skipped. 101 of 218 labelled positives are unscored because their detector does not exist yet. `rag_grounding` ships and is **deliberately not scored here**: raw-emission P/R/F1 would measure the corpus's grounded fraction, and post-band scoring needs the τ that 06 §3 bars |
| Disclosed revision v1 → v2 (`tier1_pii`, `numeric_claims`) | `python -m eval.run_all` | `reports/eval_report.md` §Disclosed revision | `numeric_claims` precision **0.2667 → 0.8571** (recall flat at 0.750); `tier1_pii` recall **0.8361 → 0.8852** at precision 1.000 both. v1 columns are **re-computed every run** from frozen `_v1_*.py`, never transcribed |
| Engine conformance matrix (**perfect detection assumed**) | `python -m eval.run_all` | `reports/eval_report.md` §Policy-level confusion matrices → A | **1.000** agreement on **280 cases × 3 use cases**. Measures the engine + policy layer *in isolation* — **not** a detection or end-to-end claim |
| That matrix's discriminating power | `python -m pytest tests/test_policy_matrix.py` | console | 5 injected ADR violations (ADR-012/019/015, 04 §4.2, 04 §4.3) — **all 5 detected**. A perfect diagonal is only evidence if disagreement was reachable |
| End-to-end matrix (**partial coverage**) | `python -m eval.run_all` | `reports/eval_report.md` §Policy-level confusion matrices → B | **0.851** (165/194) for `support_bot` and `hr_copilot`, **0.825** (160/194) for `finance_advisor`, over the **194 of 280** cases whose every label a shipped detector can emit. Of **39** scored cases carrying a detection failure, **5 reach the expected action anyway** — masked, invisible to the verdict, real in the detector section. NFR-EVAL-002 **met**, coverage limit stated |
| Calibrated τ + achieved rate | `python -m eval.run_all` | `reports/eval_report.md` §Threshold calibration | **Measured, and the band INVERTS** — τ_low **0.8365** ≥ τ_high **0.7157** at α=0.10, at **5 of 5** reshuffle seeds, which the policy schema rejects. So no calibrated τ ships, τ stays `# SEED(pre-calibration)`, and a seed is never judge-facing. Mechanism is tail overlap, not class order: AUC(`yes` vs `no`) **0.8751** with the class medians correctly ascending, but an oracle band fitted with every label visible places only **56/78 = 0.718** — an α-independent ceiling. `SL-7`; α was **not** re-picked to un-invert it |
| Fail-open / fail-closed behaviour | `python -m eval.fault_injection --reps 5` | `reports/fault_injection_report.md` | **A rate, not a single run — and two measurements of it disagree, so both are published.** In-process: **5/5 repetitions at 39/39**, quiet host (load1 0.52 start / 0.81 end), load stamped per repetition. Across five **separate** processes at comparable load: **3/5 clean**, the other two at 38/39 on the same control-probe assertion. The candidate explanation is model warmth — one process pays first-touch ONNX initialization once, five pay it five times — which is **plausible and not established**, so the report states that an in-process rate measures the *warmed steady state* rather than the cold path. SC-3 verified on `tier2`, the class 06 §5 and 07 beat 7 both name: one *identical* `tier2_toxicity` fault yields UC-1/UC-2 **pass** (`fail_open`, fault recorded but not verdict-driving) and UC-3 **escalate** (`fail_closed`) — two facts stored separately per ADR-027 Amendment 1. Coverage **3 of 4 fault classes**; `cost` has no live carrier, so its modes are **untested, not met**. **Root cause of the flake, named rather than tuned away:** a budget overrun reaches the audit record as a *detector fault*, so any pool-serialized detector running slow manufactures a fault on a probe where none was injected — and it occurs on a **quiet** host, so "passes when quiet" was too strong a reading (`M-60`). The assertion is **not relaxed**; CI retries once at the CI level, never with a test-level tolerance. The superseded single-run **39/39** claim is preserved blockquoted in the report, not deleted |
| Demo beats 1-8 end to end | `python -m demo.run_script --replay` | console (nonzero exit on any beat failure) | **8 pass / 1 skipped / 0 fail.** Expectations come from the frozen dataset's `action_expected`, never from the run's own observations, and `tests/test_demo_script.py` pins that the suite can fail. Beat 4 asserts **3/3** verdicts on PII-001 (edit / block / escalate from policy config alone). Beat 3 confirms the 04 §4.5 short-circuit with **0 upstream calls** for the blocked request — measured as a delta so the FR-GW-006 boot canary's own dispatch is not miscounted as spend. Beat 7b blocks a budget-exhausted UC-3 request seeded to its exact $200 ceiling, with **0 upstream dispatches** during the request — and carries a **control arm**, the identical request under the real ledger, which passes. Without that arm a block could not be attributed to the ceiling rather than to UC-3 refusing everything. The one remaining skip is cut scope (beat 6), listed with its reason, and **not counted as a pass**. `--replay` fixtures are dataset-derived, so **no latency or token figure from this path is a measurement** — fixtures report `prompt_tokens=None`, never 0 |
| Cost saving from cascade (simulated) | `python -m eval.cost_simulation` | `reports/cost_report.md` | **A curve, not a point — because the routing fraction is not measured.** Tier ratio **2.0×**, exact on input *and* output, so it is **blend-independent**: no input/output mix can move it and none was chosen to flatter it. At that ratio the saving is `1 − (1/r + f)`, giving **+50.0%** at `f=0`, **+40.0%** at `f=0.10`, **+25.0%** at `f=0.25`, **break-even at `f=0.50`**, and a *loss* above it. 280 frozen cases, 5,453 estimated input tokens (character-derived, `CHARS_PER_TOKEN = 4` — not tokenizer counts, and the percentage does not depend on them). **`f` itself is NOT COMPUTED**: ADR-009 escalates on low confidence, and that signal does not exist here — `fast_consistency` is cut (`SL-6`), nothing reads `thresholds.tau_route`, and `cascade_escalated` is a column nothing writes (`SL-10`). So a reader uses the row matching their own escalation rate. 2.0× sits at the **low end** of the published cross-vendor range; the vendor table in the report is cited to each price page and labelled **context, not our measurement** |
| Feedback loop before/after | *(harness half-built)* | `reports/feedback_loop_report.md` | not yet measured — and the two halves fail differently. The **review** half ships and is reachable (`/admin/review`, approve/reject, released-response lookup, wired into the console). `eval/suggest_thresholds.py` ships too, but `SL-7` records that its band **inverts**, so it proposes nothing applicable. `eval/override_report.py` is still a stub, so no end-to-end cycle can be driven — which is why demo beat 6 reports **SKIPPED** rather than passing |
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

**13 of the 15 rows above carry a measured figure; the remaining 2 are blank on purpose.** A
placeholder number is worse than a blank, so a row flips only when a report actually produces it,
carrying its method and sample size. Cost simulation flipped by shipping — and it is worth naming
*how* it flipped, because the harness could have produced a single flattering percentage instead:
the quantity it cannot measure (`f`, the routing fraction) is published as **NOT COMPUTED** beside
the curve rather than assumed, so the row states a parametric result and the gap that bounds it.
Both remaining blanks are `not yet measured` — the harness does not exist, or not all of it: the
PII leak scan is a stub, and the feedback loop has a shipping review half but a stubbed
`override_report`. The `not computed` state (inputs absent) now
occupies **no row**: τ moved out of it by being measured, and what it measured was a **failure** —
the band inverts, so the honest output is a published inversion rather than a blank.

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

## Standing Limitations — what this prototype does not do

Decided, understood, and consciously accepted: things that were ruled on and still fall short. The
full rows live in `docs/08-open-questions.md`; this is the register so no closure hides a gap. A
ledger reading `Open: zero` only ever means "nothing undecided" — never "nothing missing".

| | Limitation | State |
|---|---|---|
| **SL-1** | `tier1_pii` recall **0.8852** vs the NFR-EVAL-001 target **0.95** | Target **unmoved** (ADR-026 §5). All 7 residual misses are the documented bare-7-digit scope exclusion, verified programmatically — a deliberate trade for precision 1.000 |
| **SL-2** | An invalid NANP area code still fires (v1-superset phone behaviour) | Deliberate: narrowing it would change the v1-derived baseline that every comparison rests on. Precision hardening is a later freeze cycle |
| **SL-3** | Price provenance must be re-verified at submission packaging | Downgraded — both bound Groq ids now carry first-party per-1M figures. Comparisons priced on the retired llama pair stay **barred** |
| **SL-4** | ~~No genuinely local fallback model~~ — **closed**, host by host | Closed on the owner's host (`llama3.2:3b`, genuinely local). The development host still has no local model, so no fallback latency or cost figure may be reported from it |
| **SL-5** | Every Tier-2 latency figure is a **low-concurrency** figure | At 1 thread both picks breach at the output segmenter cap. The 1-thread column is published beside the 6-thread one rather than omitted. Bounding it properly needs a load test — out of scope |
| **SL-6** | `fast_consistency` is **cut** — specified in `docs/04` §2.3, never implemented | UC-3's performance plane is covered by `rag_grounding` where context exists; the context-free case is what the cut gives up |
| **SL-7** | τ **cannot be calibrated** — the band inverts at every α | Not a tuning failure: an oracle band fitted with every label visible places only **56/78 = 0.718**, an α-independent ceiling. Root cause is that a cosine proxy cannot see hedging; the fix is an entailment model, a **detector** change. α was **not** re-picked to un-invert it |
| **SL-8** | NFR-P-002 **unmet** for `tier2_injection`: attributable P99 **25.348 ms** vs **25 ms** | Published as a measured breach; target unmoved. p50 inside budget, tail breach. ADR-034's enforcement ceiling is a **distinct quantity** and unaffected. Roadmap: ORT intra-op tuning, serving hardware |
| **SL-9** | The two-plane OVLP demo moment is **cut** from the demo path | Measured 10× on a quiet host: 2 of 3 policies correct (`edit` 10/10, `block` 10/10, but UC-3 passes where escalate is expected). Beat 4 stays on PII-001. UC-3's zero-signal pass is recorded as **owed diagnosis**, not guessed at |
| **SL-10** | The **two-tier cascade router is not built**, so the cost *saving* is parametric rather than measured | The budget **gate** ships and enforces; the router does not. `f` — the share of requests a cascade escalates — has no producer: `fast_consistency` is cut (`SL-6`), nothing reads `thresholds.tau_route`, and `cascade_escalated` is a column nothing writes. `reports/cost_report.md` therefore publishes the saving as a curve in `f` with **`f` itself NOT COMPUTED**, plus a **break-even at `f = 0.50`** above which the cascade *costs more*. The 06 §6 cascade-quality proxy is NOT COMPUTED for the same reason — its input is the cut detector |

**All three planes now enforce, and the cost plane's remaining gap is the router, not the gate.**
`cost_budget` and `loop_guard` run in the gateway on the input stage, reading a spend ledger over the
audit DB, so a budget-exhausted request is blocked **before dispatch** — demo beat 7b, previously
SKIPPED, passes with **0 upstream dispatches** and a control arm that passes under the real ledger.
What is *not* built is the **two-tier cascade router** (`SL-10`): no code path reads
`thresholds.tau_route`, and `audit_records.cascade_escalated` is a column nothing writes. So the
routing fraction the cascade saving depends on is unmeasured, and `eval/cost_simulation.py` publishes
a **curve over that fraction with the fraction itself marked NOT COMPUTED** rather than choosing a
flattering point on it. Said here rather than left to be inferred from a table.

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
