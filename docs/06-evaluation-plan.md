# 06 — Evaluation Plan

Purpose: produce every judge-facing number honestly and reproducibly (AGENTS.md §7), and answer the brief's "metrics & monitoring — FP/FN rates for a skeptical stakeholder" solutioning area directly.

Entry points:
```
python -m eval.run_all          # detector + policy evaluation → reports/eval_report.md
python -m eval.bench_latency    # NFR-P-001/002 → reports/latency_report.md
python -m eval.fault_injection  # fail-open/closed verification
python -m eval.pii_leak_scan    # NFR-SEC-001 sweep over logs/db/reports
python -m eval.cost_simulation  # cascade savings simulation (ADR-009 framing)
```

---

## 1. Principles

- All data synthetic (charter NG3). PII values are generated fakes (valid-format SSNs from the invalid-range pool, test credit card numbers passing Luhn from test BINs, example.com emails).
- Labels are assigned at authoring time and reviewed by a second teammate; label disputes → `08-open-questions`.
- **The dataset is FROZEN at `f162959f7d29ead32342fd8744bd10ed244369af`** — freeze 2, approved
  2026-08-26 with ADR-024, 280 cases, digest `6a3ecbbe75fd020b…`. From this point **no eval
  number in this repo is computed against any other state**, and a change under
  `eval/dataset/` requires a new freeze cycle through the second-teammate review above.
  Editing a frozen case is not a fix; it is a new freeze.

  **Freeze history, and why an old freeze still matters.** Freeze 1 (Checkpoint 1b,
  `b37d1909f5fb…`, digest `3b3931365a3c2918…`) is superseded but not irrelevant: it is the
  state the **v1 detector metrics were measured against**, and those numbers are permanent
  under ADR-026. ADR-024's bump changed seven `action_expected` entries and **no
  `labels_expected`**, so the v1 per-detector precision/recall/F1 remain valid over an
  *identical label set* — the quantity those metrics are computed from did not move. Only
  policy-level expectations did, and no policy-level number has been computed yet. A future
  bump touching a label would **not** inherit this reasoning: it would invalidate the v1
  metrics and require re-measurement.

  | freeze | commit | digest | cases | what it is |
  |---|---|---|---|---|
  | 1 | `b37d1909f5fb…` | `3b3931365a3c2918…` | 280 | Checkpoint 1b. The v1 detector-metric baseline |
  | 2 | `f162959f7d29…` | `6a3ecbbe75fd020b…` | 280 | ADR-024. Identical labels; 7 `action_expected` entries changed |

  **Convention (stated so it is unambiguous):** the hash names the commit whose tree holds the
  frozen cases — **not** the commit that recorded the hash, which is necessarily later and
  touches only docs. So the freeze is machine-checkable rather than a claim, and two different
  things are checked because they can fail independently:

  | check | what it catches | command |
  |---|---|---|
  | git provenance | the dataset was changed and committed | `git log -1 --format=%H -- eval/dataset/` equals the hash |
  | content digest | the dataset was changed and **not** committed | `python -m eval.validate_dataset --freeze` |

  A dirty working tree passes the first check and fails the second, which is the failure mode a
  git hash alone would miss. `--freeze` is what `eval/run_all.py` calls before it computes
  anything, so a number cannot be produced against an unfrozen dataset even by accident.
- Reports state method + hardware + sample size next to every number. A missed target is reported as missed + a D3 deviation — never tuned away silently.

## 2. Labeled dataset (`eval/dataset/*.jsonl`)

### 2.1 Case format

```json
{"case_id":"PII-012","kind":"output","use_case":"support_bot",
 "text":"…","context":null,
 "labels_expected":["pii.email"],
 "action_expected":{"support_bot":"edit","hr_copilot":"block","finance_advisor":"escalate"},
 "notes":"email embedded mid-sentence"}
```

`kind` ∈ {`input`, `output`, `conversation`} (Q-11). A `conversation` case encodes its turns
as `"user: …\nassistant: …"` lines inside `text` — the format gains no `turns` field.

### 2.2 Ground truth is causal, not literal (ADR-023)

For a **detection-kind** label (04 §1.2) the expected action is a lookup, so it is recorded
literally and that is exact. For a **confidence-kind** label — `hallucination.low_confidence`
from `fast_consistency`, `hallucination.ungrounded_claim` from `rag_grounding` — it is not:
the action depends on where the score falls against `tau_low`/`tau_high`, and §3 calibration is
explicitly allowed to move both. A literal string would silently freeze the *seed* thresholds
into ground truth, and a calibration run would leave those cases asserting outcomes the policy
no longer produces, with nothing to notice the drift.

Confidence-driven cases therefore carry two additional fields:

| Field | Values | Meaning |
|---|---|---|
| `grounded` | `yes` \| `no` \| `borderline` | band the confidence score should land in: `yes` ≥ `tau_high` (nothing fires) · `borderline` inside `[tau_low, tau_high)` · `no` < `tau_low` |
| `person_present` | `true` \| `false` | whether `entity_enricher` should append `privacy.person` — outcome-relevant under ADR-019 |

`grounded` is named for the dominant case; on a span-less `fast_consistency` case with no
context it denotes self-consistency confidence rather than context grounding.

`action_expected` is **retained**, and redefined as *the action expected at the v1 seeded
thresholds*. The harness **verifies** it against its own derivation from (ground truth + the
loaded policy + ADR-019's enriched-label branches + ADR-015's span-less rule). A mismatch is a
dataset error today and a **calibration-drift alarm** later — which is exactly the tripwire
F6 asked for, obtained for free. Detection-kind cases keep literal expectations only; adding a
band field there would imply a band that never applies to them (ADR-012).

**Multi-turn labelling is per breach unit (ADR-021), not the union of turns** — the breaching
turn's own labels plus the conversation-stage signal. Earlier turns' PII is already scored by
its own `pii.jsonl` cases; unioning would inflate per-detector recall denominators without
changing any verdict. A reviewer reading PII recall needs this convention to read the
denominator correctly.

### 2.3 Composition (v1)

Positives and negative controls are enumerated **separately**. Conflating them is what let a
non-firing control silently consume a positive slot in the v1 draft (review findings F4/F5): a
file can hit its target size while under-covering the thing it exists to measure. Negative
controls are not filler — a detector whose false-positive behaviour is untested cannot be
reported honestly — so they are counted, not hidden.

| File | Positives | Negative controls | Design intent |
|---|---|---|---|
| `clean.jsonl` | 0 | 80 | benign inputs/outputs across all three use cases; ~half are near-miss FP pressure (digit strings, violent technical verbs, sensitive-but-correct HR vocabulary) |
| `pii.jsonl` | 51 | 2 | output-stage: SSN · CC · email · phone · API key · multi-PII, varied placement, obfuscation-lite (spaces/dashes). Plus **input-stage** cases across categories (ADR-020: UC-1 redacts pre-dispatch, UC-2 blocks, UC-3 escalates) |
| `injection.jsonl` | 20 | 0 | direct + indirect prompt injection (input stage) |
| `toxicity.jsonl` | 15 | 5 | high / moderate / borderline-clean |
| `halluc.jsonl` | 41 | 21 | context+response pairs: ungrounded, unsourced-numeric. Subjects are organizations, products and policies — **never people** (a PERSON entity would invoke `entity_enricher` and belongs in `overlap.jsonl`) |
| `overlap.jsonl` | 15 | 0 | **OVLP-01…10** below `tau_low` (SC-1, multi-label `hallucination.* + privacy.person`); **OVLP-11…15** in-band, exercising ADR-019's unadjusted-enriched-label branch |
| `borderline.jsonl` | 20 | 0 | designed to land in `[tau_low, tau_high)` |
| `conversation.jsonl` | 7 | 3 | multi-turn cumulative-risk sequences (SC-4) |

**Totals are derived from the files by `eval/validate_dataset.py`, never asserted here.** An
asserted total is a number that can rot; a derived one cannot. The generated report states the
count it actually loaded.

All data synthetic (charter NG3), and safe by *construction* rather than by inspection:
never-assigned SSN prefixes, Luhn-valid test BINs, the reserved `555-01xx` phone block, RFC
2606 domains, published documentation literals for API keys.

### 2.4 Freeze gate

`python -m eval.validate_dataset` is the freeze gate. It checks the §2.1 format, the 04 §1.1
closed taxonomy, `action_expected` key sets, and the ADR-023 derivation above. **It validates
consistency, not label correctness** — that is what the second-teammate review in §1 is for,
and its open items live in `eval/dataset/REVIEW_NEEDED.md` until ruled.

**Band membership is a hypothesis until measured (F6).** `borderline.jsonl`'s placement rests
on a semantic proxy — a claim whose core fact is supported but whose elaboration is not — since
no detector existed when the cases were authored and the τ values are `# SEED(pre-calibration)`.
Membership is **empirically re-verified after calibration, before any band-dependent number is
published.** Until then the file's *purpose* is unproven even where its expected actions are
robust.

## 3. Metrics computed

**Per detector:** precision, recall, F1 against `labels_expected`; confusion listed per label. Targets: NFR-EVAL-001 (Tier-1 PII recall ≥ 0.95; others reported without target).

**Per use case (policy level):** 4×4 confusion matrix `action_taken` vs `action_expected` — this is the skeptical-stakeholder artifact. Derived: over-flagging rate (expected pass → non-pass) and under-flagging rate (expected non-pass → pass), reported side by side to show the tuning dial.

**Threshold calibration (ADR-005):** the τ values shipped in `policies/*.yaml` are marked `# SEED(pre-calibration)` (ADR-016). They exist only so the policies load and the engine runs before a calibration set exists; **calibration below overwrites them, and a seed value is never judge-facing** — no seed-derived number appears in a report, the README, the proposal, or the video (AGENTS.md §7). τ_low/τ_high computed as quantiles of non-conformity scores on a held-out calibration split (70/30 split of `halluc.jsonl` + `borderline.jsonl`, ≈56 calibration points at v1 counts); report includes achieved-vs-target rate on the eval split. **Mandatory caveats printed with the numbers:** the exchangeability assumption, the calibration n, and a small-n variance note (quantile estimates at this n swing between runs; report a bootstrap CI or min/max over 5 reshuffles).

**Overlap correctness:** all OVLP cases must produce exactly one multi-label signal and the most-severe-action resolution (04 §4.3) — pass/fail listed per case.

### 3.1 Harness rules (normative — the report obeys these, not convenience)

1. **`n/a` over a fake 1.0.** An empty denominator is *undefined*, never perfect. A detector with
   no positives in the corpus reports `n/a`, because "recall 1.0 over zero cases" is the most
   flattering way to say nothing was measured.
2. **Skipped, never scored.** A detector that does not exist is reported as **skipped**, with its
   unscored label occurrences counted. Treating its labels as misses would blame absent code for
   a recall figure and make the number unreadable.
3. **No fabricated 4×4.** Deriving `action_taken` from `labels_expected` would compare ground
   truth against a function of ground truth and yield a perfect diagonal that means nothing.

   **Trigger fired (2026-08-26).** This rule read "**NOT COMPUTED** until the policy engine
   exists", and that condition is now satisfied: `controlplane/policy/engine.py` produces an
   `action_taken` independently of the ground truth, so the matrix is computed per §3.3. The
   prohibition itself is unchanged and still binding — it barred *deriving the verdict from the
   labels*, not the artifact. What replaces the absence is not merely a table but a table that
   **carries its own falsification** (§3.3), because a perfect diagonal is exactly what this
   rule warns about and an assurance of independence is not evidence of it. `derive_action`
   remains barred as an `action_taken` source, permanently.

### 3.2 Revision methodology — disclosed revision, dual columns (ADR-026)

A detector revised **after** its failures were measured produces weaker evidence than one
measured blind, however carefully the revision was derived. The report therefore never replaces a
number; it adds a column:

| column | meaning |
|---|---|
| **v1 (blind first contact)** | measured before the failing cases were known. Permanent — never overwritten, never deleted |
| **v2 (post-revision, disclosed)** | measured after a spec-derived revision, with the derivation cited |

Requirements on any v2 column:

- Each pattern cites a **named published specification** (04 §2.5). A pattern without a citation
  cannot appear in a v2 column.
- **Scope exclusions are stated with their recall cost**, not omitted. An exclusion that quietly
  removes hard cases is indistinguishable from tuning.
- **One re-measurement.** Iterating until a target is met is target-gaming; if v2 misses, the
  miss is reported and **the target does not move**.
- Precision movement is reported in the same table as recall. A revision that buys recall with
  precision must show both halves.

**v1 metric validity across a freeze bump.** ADR-024 bumped the freeze after v1 was measured. Its
seven changed cases altered `action_expected` only — **no `labels_expected`** — so per-detector
precision/recall/F1, which are computed against labels, remain valid over an identical label set
(freeze history in §1). A bump touching a label would invalidate them and force re-measurement.

### 3.3 The two policy matrices are different claims (normative)

`run_all` emits **two** 4×4 `action_expected` × `action_taken` matrices, and **quoting one as
the other is a reporting error**, not a simplification. Both take `action_taken` from
`controlplane/policy/engine.py`; they differ in where the *signals* come from.

| | A. Engine conformance | B. End-to-end (partial) |
|---|---|---|
| Signals | **synthesized** from `labels_expected` | **real** emissions from implemented detectors |
| Assumes | perfect detection, deliberately | nothing |
| Measures | the engine + policy layer in isolation | the shipping slice of the whole pipeline |
| Scope | every case | only cases whose every expected label is emittable today |
| Is **not** | a detection-quality or end-to-end claim | a claim about absent detectors |
| Grows when | the policy layer changes | a detector lands |

Requirements on the section, all enforced by tests:

- **A must justify its diagonal.** Conformance currently agrees on every case × policy.
  Agreement is a real finding *only* because `action_expected` is pinned to
  `validate_dataset.derive_action` by the freeze gate while the engine is an independent
  implementation of 04 §4.3 — a **differential test of two implementations of one spec**. That
  argument is not self-evident, so the matrix is **falsified**: `tests/test_policy_matrix.py`
  injects the defects the ADRs exist to prevent (ADR-012 band scoping, ADR-019 enriched
  handling, ADR-015 span-less promotion, 04 §4.2 severity order, 04 §4.3 step-1 resolution) and
  requires disagreement from each. **A mutation the matrix cannot see forfeits the diagonal's
  publishability** — rule 3 would then apply after all.
- **Synthesis may not reason about actions.** It reads the 04 §2 emitter registry and the 04
  §1.2 polarity only; no policy lookup, no τ comparison, no severity ordering, no
  `borderline_action`. Otherwise both sides of A collapse into one function of ground truth.
  Pinned structurally by `test_synthesis_never_consults_a_policy`.
- **No matrix figure may derive from a seed τ.** The shipped τ are `# SEED(pre-calibration)`
  and §3 bars a seed value from any judge-facing number. Synthesis places scores *relative* to
  the band, so every verdict is invariant under rescaling it — pinned across four bands.
- **B reports its own coverage and its own flattery.** The unscored counts are stated, split by
  reason. B's agreement rate is **higher** than the detector figures imply, because a detection
  failure whose case carries another label mapping to the same action changes no verdict. Those
  masked failures are counted and listed, split into masked misses and masked false positives,
  which hide by different mechanisms. Reporting B's rate without them would present blindness
  as accuracy (AGENTS.md §7).

NFR-EVAL-002 asks that the per-use-case matrix exist and sets no target; §3.3 is what satisfies
it, with the coverage limit stated rather than implied.

## 4. Latency benchmark (`bench_latency`)

- Method: 300 requests replayed from dataset traffic mix against the gateway with a **stub upstream** (canned SSE at realistic token cadence) so gateway overhead is isolated from provider variance; then 30 requests against the real provider for an end-to-end sanity row.
- **Normative definition of `gateway_overhead_ms`** (used by 05 §5, the audit record, and every report — no ad-hoc variants): *streaming pipelines* = ingress + input-lane time + Σ per-sentence hold (measured from sentence-boundary arrival to release: detector wait + policy + action) + finalization; upstream token wait time excluded. *Non-streaming pipelines* = total wall-clock − upstream call duration. TTFB delta vs stub-direct is reported as a separate reference row, never as the headline number.
- Report: P50/P95/P99 `gateway_overhead_ms` per use case (streaming and non-streaming tabulated separately per NFR-P-001 scope); per-detector latency histograms vs NFR-P-002 budgets; hardware + Python version + run date stamped.
- Assertion mode: `--check` exits nonzero if NFR-P-001/002 violated → used in CI and as the D3 tripwire.

## 5. Fault injection (`fault_injection`)

For each detector class: monkeypatch to raise timeout → fire one canary request per use case → assert UC-1 tier2 fails **open** (pass + `_meta.detector_failure` audited) and UC-3 fails **closed** (escalate). Output feeds demo beat SC-3.

## 6. Cost simulation (`cost_simulation`)

Replay demo traffic pricing both paths: (a) all-frontier baseline, (b) cascade per ADR-009. Report absolute $ + % delta with the label **"simulation on synthetic demo traffic — not a production claim."** Also reports cascade quality proxy: fraction of small-tier answers whose fast-confidence cleared τ_route.

## 7. Feedback-loop evaluation (charter S4)

Scripted sequence: run borderline cases through UC-3 → generate escalations → apply scripted reviewer decisions → `override_report` → `suggest_thresholds` proposes diff → apply → re-run borderline set → report before/after action distribution. Output: `reports/feedback_loop_report.md` (used directly in proposal + video).

## 8. Report bundle → README mapping

**Reports are committed evidence, not build output.** `reports/` is under version control, and
a report is committed in the **same change** that adds or updates any README claim citing it. A
claims-table row pointing at a file absent from the tree is an **NFR-INT-001 violation**: the
number is then unverifiable by the one thing NFR-INT-001 promises, a reader with the repo. This
is why the rule is structural rather than a habit — the failure mode is a README that looks
fully sourced while sourcing nothing.

Three consequences, stated so they are not rediscovered later:

- **A report is still never hand-edited.** Committing it does not make it a document; it stays
  the output of its entry point, and the way to change it is to re-run that command.
- **`DEV-TAINTED` artifacts stay gitignored.** ADR-018 defines them as resting on accounting
  that is not a measurement, so committing one would place a non-publishable number in the
  evidence tree — the precise opposite of the intent.
- **The `Code commit` stamp names the commit whose code produced the numbers, not the commit
  that records the report** — necessarily one earlier, since the recording commit's hash cannot
  exist while its own contents are being generated. This is the same convention §1 uses for the
  frozen dataset hash, for the same reason. A report generated from a dirty tree stamps
  `+ uncommitted changes` and is **not** citable evidence; regenerate from a clean tree first.

Cited section names must match the report's actual headings, so a citation can be resolved by
searching the file:

| README claim | Source |
|---|---|
| Gateway overhead P50/P99 | `reports/latency_report.md` |
| PII recall / per-detector F1 | `reports/eval_report.md` §Detectors |
| Engine conformance matrix (perfect detection assumed) | `reports/eval_report.md` §Policy-level confusion matrices → A |
| End-to-end matrix (partial coverage) + masked-failure reconciliation | `reports/eval_report.md` §Policy-level confusion matrices → B |
| Conformance-matrix discriminating power (mutation set) | `tests/test_policy_matrix.py` |
| Calibrated τ + achieved rate | `reports/eval_report.md` §Threshold calibration |
| Tier-1 PII recall vs NFR-EVAL-001 | `reports/eval_report.md` §NFR-EVAL-001 |
| Cost savings (simulated) | `reports/cost_simulation.md` |
| Feedback loop before/after | `reports/feedback_loop_report.md` |
No number appears in README/proposal/video without a row here.
