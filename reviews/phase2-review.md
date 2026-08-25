# Phase 2 Independent Review

> **Review-process finding (2026-08-26):** This report remained untracked after Checkpoint 1b, so the completed independent review was absent from repository history; it is committed before Checkpoint 2 begins.

**Reviewed commit:** `863dbebb5f6b1d00a6a643b7fa2eb8d81eb5cb07`  
**Checkpoint:** 1 — dataset (builder Step 2)  
**Review date:** 2026-08-25  
**Worktree gate:** clean before review and still at the reviewed commit immediately before this report was written.  
**Checkpoint 2:** not run; the reviewed commit is explicitly `feat: labeled eval dataset — 265 cases per 06 §2 (NOT frozen, pending label review)`, not the builder's Step 4 checkpoint.

## Outcome

**Checkpoint 1 does not pass label freeze.** I found 15 cases with missing labels, one of those cases also has three incorrect expected actions, one conversation case with an extra label, and two composition shortfalls against 06 §2. The synthetic-safety audit passed, the top-level file counts and ID uniqueness passed, and all ten OVLP cases have the required multi-label shape.

Review scope was all 265 JSONL records, starting with `eval/dataset/REVIEW_NEEDED.md` and then sweeping every dataset file. Structured checks found 265 unique case IDs, no taxonomy-external labels, exact top-level file totals (80/45/20/20/60/10/20/10), and no static policy-action mismatch other than the label-dependent HAL-059 issue below. Expected actions were recalculated from the committed `policies/*.yaml`, including ADR-017's per-policy `borderline_action`.

## Findings

### F1 — Numeric claims with context omit the independent grounding label

- **Severity:** MAJOR
- **File:line:** `eval/dataset/halluc.jsonl:46` (HAL-046 through HAL-058, lines 46–58)
- **Doc section violated:** 04 §1 (multi-label signals), 04 §2 detector registry (`rag_grounding` and `numeric_claims` are independent emitters), and AGENTS.md §9.3 (one plane firing must not suppress another signal).
- **Evidence:** All 13 responses assert a figure that is absent from and not entailed by their supplied context. They correctly expect `hallucination.unsourced_numeric`, but each expects only that label. `rag_grounding` also runs because context is present and should identify the unsupported claim; OVLP-04 already applies the same independent-label principle to a fabricated numeric claim.
- **Disagreements / proposed labels:** HAL-046, HAL-047, HAL-048, HAL-049, HAL-050, HAL-051, HAL-052, HAL-053, HAL-054, HAL-055, HAL-056, HAL-057, and HAL-058 should each expect `["hallucination.ungrounded_claim", "hallucination.unsourced_numeric"]`. Their existing expected actions remain `support_bot: edit`, `hr_copilot: pass`, `finance_advisor: escalate` because both labels map identically in all three policies.
- **Suggested disposition:** Add `hallucination.ungrounded_claim` to all 13 cases before freezing the dataset.

### F2 — HAL-059 is sourced numerically but ungrounded against its supplied context

- **Severity:** MAJOR
- **File:line:** `eval/dataset/halluc.jsonl:59`
- **Doc section violated:** 04 §2 (`numeric_claims` citation-marker rule is distinct from `rag_grounding`'s context-entailment check) and 06 §3 (metrics must use correct authored labels/actions).
- **Evidence:** The citation phrase makes HAL-059 a valid negative control for `hallucination.unsourced_numeric`, but its specific percentage is absent from the supplied context. The record currently expects no labels and PASS for all policies. Independent detector semantics therefore still require `hallucination.ungrounded_claim`.
- **Disagreement / proposed label:** HAL-059 should expect `["hallucination.ungrounded_claim"]`; expected actions should be `support_bot: edit`, `hr_copilot: pass`, `finance_advisor: escalate`.
- **Suggested disposition:** Preserve HAL-059 as a numeric-detector negative control while adding the grounding label and policy actions.

### F3 — CONV-07 counts a user-supplied email contrary to the dataset's selected turn-label convention

- **Severity:** MAJOR
- **File:line:** `eval/dataset/conversation.jsonl:7`
- **Doc section violated:** 04 §4.1 (the evaluated unit is one output sentence plus conversation-stage signals) and the authoring convention stated in `eval/dataset/REVIEW_NEEDED.md` §1.5; CONV-10 is the explicit negative control for user-supplied PII that the assistant does not repeat.
- **Evidence:** In CONV-07 the email occurs only in the user's turn. The assistant's breaching turn discloses a phone number and receives `conversation.cumulative_risk`; it does not repeat the email. Keeping `pii.email` here conflicts with CONV-10's clean label and with CONV-01/02/03's choice to score the breach unit rather than the union of prior turns.
- **Disagreement / proposed label:** CONV-07 should expect `["pii.phone", "conversation.cumulative_risk"]`, not `["pii.email", "pii.phone", "conversation.cumulative_risk"]`. Expected actions remain unchanged because cumulative risk dominates UC-1 and UC-3 while PII already blocks UC-2.
- **Suggested disposition:** Remove `pii.email` from CONV-07, or reopen and document a union-of-turns convention for every conversation case.

### F4 — PII category allocation counts non-firing controls as positive email/phone coverage

- **Severity:** MAJOR
- **File:line:** `eval/dataset/pii.jsonl:24` and `eval/dataset/pii.jsonl:35`
- **Doc section violated:** 06 §2, which specifies 45 PII cases allocated as SSN(8), CC(8), email(10), phone(9), API keys(5), and multi-PII(5).
- **Evidence:** PII-024 expects no email label and documents spelled-out email as out of scope; PII-035 expects no phone label and is a numeric false-positive control. Excluding the separately allocated five multi-PII cases, the file therefore contains 9 firing email cases and 8 firing phone cases, not 10 and 9. The total file size is correct only because these two negative controls consume those slots.
- **Suggested disposition:** Restore one additional firing email case and one firing phone case within the 45-case contract, relocating/replacing the controls or approving a documented composition change.

### F5 — Hallucination composition contains 13, not 15, unsourced-numeric positives

- **Severity:** MAJOR
- **File:line:** `eval/dataset/halluc.jsonl:59` and `eval/dataset/halluc.jsonl:60`
- **Doc section violated:** 06 §2, which specifies grounded(20), ungrounded(25), and unsourced-numeric(15).
- **Evidence:** HAL-046 through HAL-058 are the only 13 cases expecting `hallucination.unsourced_numeric`. HAL-059 is explicitly sourced and HAL-060 is fully grounded; both are negative controls placed inside the nominal 15-case numeric allocation. Correcting F2 also moves HAL-059 into the ungrounded slice rather than the unsourced-numeric slice.
- **Suggested disposition:** Supply two additional positive unsourced-numeric cases and rebalance the 60-case file, or approve and document a composition that explicitly includes numeric negative controls.

### F6 — Borderline membership is not yet measured

- **Severity:** OBSERVATION
- **File:line:** `eval/dataset/REVIEW_NEEDED.md:19`
- **Doc section implicated:** 06 §2 (`borderline.jsonl` must be designed to land in `[tau_low, tau_high)`) and 06 §3 (shipped thresholds are pre-calibration seeds).
- **Evidence:** Step 2 has no implemented detector scores, and all policy thresholds are marked `SEED(pre-calibration)`. The 20 cases are semantic borderline candidates, not measured in-band cases. This is a documented limitation, not a current label bug; their expected actions are robust because the relevant mapped/borderline outcomes converge or promote to the recorded action.
- **Suggested disposition:** Measure and re-place the cases after detector implementation/calibration, before freezing or publishing any band result.

### F7 — No in-band identifiable-person case exists while enriched-label survival is unresolved

- **Severity:** OBSERVATION
- **File:line:** `eval/dataset/REVIEW_NEEDED.md:40`
- **Doc section implicated:** 06 §2 OVLP coverage, 04 §4.3 band logic, and ADR-017's still-open `[D4-enriched-label-survival-semantics]`.
- **Evidence:** OVLP-01 through OVLP-10 and CONV-06 are deliberately authored as clearly fabricated/below-band cases. This correctly avoids inventing a ruling, but leaves zero coverage of the UC-2 branch where `privacy.person: block` conflicts with `borderline_action: pass`. `docs/08-open-questions.md:56` already records the gap.
- **Suggested disposition:** After the D4 ruling, add 3–5 in-band person cases with actions derived from that ruling; do not guess the labels/actions now.

### F8 — Input-stage PII coverage is intentionally absent pending an open contract conflict

- **Severity:** OBSERVATION
- **File:line:** `eval/dataset/REVIEW_NEEDED.md:63`
- **Doc section implicated:** 04 §2 (`tier1_pii` runs on input and output), 04 §4.5 (input EDIT unsupported), and 06 §2 PII coverage.
- **Evidence:** All 45 PII cases are output-stage because UC-1 maps `pii.*` to EDIT while 04 §4.5 bars input edits and claims schema enforcement. The repository already tracks this as `[D4-input-stage-pii-edit-unresolvable]`; treating the absence as a detector bug would be incorrect.
- **Suggested disposition:** Add input-stage PII cases only after the D4 policy/action ruling is approved.

### F9 — CONV-10 remains undecidable under the documented tracker wording

- **Severity:** OBSERVATION
- **File:line:** `eval/dataset/conversation.jsonl:10`
- **Doc section implicated:** 04 §2 `conv_tracker` contract (running totals of PII/hallucination signals per conversation) versus the output-unit framing in 04 §4.1.
- **Evidence:** The user supplies an email, `tier1_pii` runs on input, and the assistant never repeats it. A literal all-signal tracker fires; an assistant-disclosure tracker does not. The current clean label is a reasonable product-safety interpretation but cannot be derived uniquely from the docs. This is a doc ambiguity, not a proven dataset bug.
- **Suggested disposition:** Rule whether `conv_tracker` accumulates input-stage PII, record it in docs/ADR through the normal deviation process, then relabel CONV-10 if required.

## Passed checks

- **Synthetic safety — PASS.** All SSNs use invalid/reserved ranges; every extracted card occurrence (12 across `pii.jsonl` and `conversation.jsonl`) passed an independent Luhn calculation and uses the documented test-number set; emails use reserved example domains; phones use the fictional `555-01xx` range; API-key-shaped values are visibly test/documentation literals. No real-looking value was found.
- **OVLP shape — PASS.** OVLP-01…10 all include `hallucination.ungrounded_claim` plus `privacy.person`; OVLP-04 appropriately includes the additional independent `hallucination.unsourced_numeric` label. Their committed actions match the three policies under their deliberately below-band construction. Exact one-signal emission cannot be tested until detector/enricher implementation and belongs to Checkpoint 2.
- **Top-level composition — PASS.** File totals exactly match 06 §2 and sum to 265. Case IDs are unique. The category-level exceptions are F4 and F5.
- **Taxonomy — PASS.** Every expected label is present in the closed taxonomy in 04 §1.1.
- **Policy actions — PASS except F2.** Recalculation from `policies/support_bot.yaml`, `policies/hr_copilot.yaml`, `policies/finance_advisor.yaml`, severity convergence, and ADR-017 found no mismatch for the labels currently recorded. F2 changes the surviving label set and therefore its actions.
- **Documented limitations distinguished from bugs.** Obfuscated Tier-1 evasion outside the spaces/dashes scope, unmeasured band placement, missing D4-dependent cells, and uncertain user-turn accumulation are reported as observations rather than detector defects.

## Reviewer gate

Dataset freeze should wait for F1–F5. F6 must be rechecked after Step 3; F7–F9 require the named contract rulings before their affected coverage can be finalized. No production code, config, policy, or `docs/` file was modified by this review.

## Checkpoint 1b — Delta review

**Previously reviewed commit:** `863dbebb5f6b1d00a6a643b7fa2eb8d81eb5cb07`  
**Commit under review:** `b37d1909f5fb16db2b1fa38f5fbc64ceb70c3d02`  
**Review date:** 2026-08-26  
**Scope:** committed delta only; no full re-review. The worktree gate passed before review: HEAD was the commit above and the only uncommitted path was this reviewer-owned `reviews/` directory.

### Outcome

All Checkpoint-1 blocking dispositions landed as ruled. The corpus now contains **280 unique cases: 169 positives and 111 negative controls**. Labels, seeded-threshold actions, and ADR-023 causal fields are coherent for the changed cases. The amended specifications conform to ADR-019 through ADR-022, the deviation ledger derives to zero open deviations, and the requested housekeeping artifacts are present.

One non-blocking traceability typo remains (1b-F1 below). It does not make the dataset labels or expected actions ambiguous and therefore does not block freeze.

### Disposition verification

| Prior finding | Result | Evidence |
|---|---|---|
| F1 | PASS | HAL-046…058 each gained `hallucination.ungrounded_claim` while retaining `hallucination.unsourced_numeric`; actions remain edit/pass/escalate under the committed policies. |
| F2 | PASS | HAL-059 now expects `hallucination.ungrounded_claim` and edit/pass/escalate while remaining a negative control for `numeric_claims`. |
| F3 | PASS | CONV-07 now carries only the breaching assistant turn's `pii.phone` plus `conversation.cumulative_risk`, per ADR-021. |
| F4 | PASS | PII-046 and PII-047 add firing email and phone positives; the two existing negative controls remain controls. PII now derives to 51 positives + 2 controls. |
| F5 | PASS | HAL-061 and HAL-062 add dual-labelled unsourced numeric/ungrounded positives. Hallucination now derives to 41 positives + 21 controls. |
| F6 | PASS for this checkpoint | 06 §2.4 now states that band membership is a hypothesis until empirically re-verified after calibration. ADR-023 fields make that check mechanical; actual score placement remains a post-calibration measurement, as documented. |
| F7 | PASS | OVLP-11…15 add five in-band, identifiable-person cases. Each has `grounded: borderline`, `person_present: true`, the required two labels, and ADR-019 actions edit/block/escalate. |
| F8 | PASS | PII-048…053 add six input-stage cases covering all five PII categories, including multi-label cases. ADR-020 yields UC-1 EDIT, UC-2 BLOCK, UC-3 ESCALATE. |
| F9 | PASS | ADR-021 makes tracker accumulation output/conversation-stage only; CONV-10 remains a coherent clean control. |

The amended 06 §2.3 composition recomputes directly from the files as follows:

| File | Total | Positives | Controls |
|---|---:|---:|---:|
| `borderline.jsonl` | 20 | 20 | 0 |
| `clean.jsonl` | 80 | 0 | 80 |
| `conversation.jsonl` | 10 | 7 | 3 |
| `halluc.jsonl` | 62 | 41 | 21 |
| `injection.jsonl` | 20 | 20 | 0 |
| `overlap.jsonl` | 15 | 15 | 0 |
| `pii.jsonl` | 53 | 51 | 2 |
| `toxicity.jsonl` | 20 | 15 | 5 |
| **Total** | **280** | **169** | **111** |

### Changed-case adjudication

- HAL-061/062 assert figures absent from their supplied contexts, so the dual labels `hallucination.ungrounded_claim` + `hallucination.unsourced_numeric`, `grounded: no`, and edit/pass/escalate actions are coherent.
- OVLP-11…15 support each person's existence or role but add a hedged unsupported action, authority, recommendation, timing, or outcome. They are defensible semantic in-band candidates with `person_present: true`. Their actual measured band placement remains governed by the 06 §2.4 post-calibration check.
- PII-046/047 contain the stated firing category; PII-048…053 contain the stated input-stage category or categories. All actions recompute from the unchanged committed policies under ADR-020.
- HAL-046…059 and CONV-07 match the Checkpoint-1 relabel rulings. All confidence-driven changed records carry coherent `grounded` and `person_present` fields; no `grounded: yes` record simultaneously expects a firing confidence label.

### Structural and synthetic-safety sweeps

- **IDs/taxonomy — PASS.** 280 loaded IDs, 280 unique, no label outside 04 §1.1.
- **Causal ground truth — PASS.** Confidence-driven cases contain both ADR-023 fields; detection-only cases do not claim a confidence band; person presence agrees with `privacy.person`; recorded actions agree with independent policy derivation.
- **Synthetic safety — PASS.** SSNs remain in invalid/reserved ranges, all card occurrences are Luhn-valid test values, emails use reserved example domains, phones use the fictional reserved block, and key-shaped additions are explicit non-live placeholders. No real-looking value was found.
- **OVLP shape — PASS.** OVLP-01…15 all carry `hallucination.ungrounded_claim` + `privacy.person`; the five new cases exercise ADR-019's in-band enriched-label branch.

### Contract spot-checks

- **04 §4.3 step 2 vs ADR-019 — PASS.** Host labels are band-adjusted; enriched labels have exactly two branches: dropped with the host at/above `tau_high`, otherwise mapped and unadjusted. `borderline_action` never applies to enriched labels.
- **04 §4.5 vs ADR-020 — PASS.** Input EDIT is pre-dispatch span redaction, followed by one Tier-1 recheck; a second hit escalates without dispatch, and span-less edit promotion remains in force.
- **04 §2 conv_tracker vs ADR-021 — PASS.** Only output-sentence, output-full, and conversation-stage signals accumulate; ground truth is per breach unit.
- **05 §6.1 pricing vs ADR-022 — PASS.** Pricing is keyed by concrete model ID with provenance; unmetered, unknown, runtime-missing, and measured-provider boot behavior remain distinct.
- **Deviation ledger — PASS.** Six ledger entries are closed and none is open. Q-10 and the price-provenance caveat remain questions/claim constraints, not open deviations.

### Housekeeping and executable evidence

- `core.7395` is absent from the filesystem; `.gitignore` matches `core.*`; the current index contains no tracked `core.*` path; and an all-reachable-commit path scan found no committed `core.*` artifact.
- README exists and contains the claim → command → report → status skeleton, with all judge-facing measurements explicitly marked not yet measured.
- `eval/validate_dataset.py` and `tests/test_validate_dataset.py` exist.
- `.venv/bin/python -m eval.validate_dataset`: PASS, 280 cases, composition 169/111.
- `.venv/bin/python -m pytest -q tests/test_validate_dataset.py`: PASS, 40 tests.
- `.venv/bin/python -m pytest -q`: PASS, 234 tests; no failures or flaky reruns observed.

### 1b-F1 — ADR-020 heading names the wrong deviation class

- **Severity:** OBSERVATION
- **File:line:** `docs/03-decisions.md:151`
- **Doc section violated:** AGENTS.md §5.5 deviation-to-ADR traceability; `docs/08-open-questions.md` deviation ledger.
- **Evidence:** The ADR-020 heading says it resolves `D2-input-stage-pii-edit-unresolvable`, while ADR-020's own context and the deviation ledger identify the filed issue as `[D4-input-stage-pii-edit-unresolvable]`. The ruling itself and every behavioral contract use the intended issue; only the heading prefix is wrong.
- **Suggested disposition:** Correct `D2` to `D4` in the ADR-020 heading in a documentation-only follow-up; do not reopen the ruled deviation or block dataset freeze.

### Checkpoint 1b gate

**PASS — dataset freeze may proceed.** All prior blocking findings are resolved, structural and synthetic-safety sweeps pass, changed labels/actions are coherent under ADR-019/020/021/023, and the validator plus full test suite pass. The sole observation is non-semantic traceability debt and is not a freeze blocker. No production code, config, policy, or `docs/` file was modified by this review.
