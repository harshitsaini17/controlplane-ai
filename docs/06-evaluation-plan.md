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
- Reports state method + hardware + sample size next to every number. A missed target is reported as missed + a D3 deviation — never tuned away silently.

## 2. Labeled dataset (`eval/dataset/*.jsonl`)

Case format:
```json
{"case_id":"PII-012","kind":"output","use_case":"support_bot",
 "text":"…","context":null,
 "labels_expected":["pii.email"],
 "action_expected":{"support_bot":"edit","hr_copilot":"block","finance_advisor":"escalate"},
 "notes":"email embedded mid-sentence"}
```

Composition (~265 cases, v1):

| File | Cases | Contents |
|---|---|---|
| `clean.jsonl` | 80 | benign inputs/outputs across all three use cases (FP pressure) |
| `pii.jsonl` | 45 | SSN(8), CC(8), email(10), phone(9), API keys(5), multi-PII(5) — varied placement, obfuscation-lite (spaces/dashes) |
| `injection.jsonl` | 20 | direct + indirect prompt injection attempts (input stage) |
| `toxicity.jsonl` | 20 | high(8) / moderate(7) / borderline-clean(5) |
| `halluc.jsonl` | 60 | context+response pairs: grounded(20), ungrounded(25), unsourced-numeric(15) |
| `overlap.jsonl` | 10 | **OVLP-01…10**: fabricated details about identifiable people → expect multi-label `hallucination.* + privacy.person` (SC-1) |
| `borderline.jsonl` | 20 | designed to land in [τ_low, τ_high) → expect ESCALATE on UC-3 |
| `conversation.jsonl` | 10 | multi-turn sequences for cumulative-risk (SC-4) |

## 3. Metrics computed

**Per detector:** precision, recall, F1 against `labels_expected`; confusion listed per label. Targets: NFR-EVAL-001 (Tier-1 PII recall ≥ 0.95; others reported without target).

**Per use case (policy level):** 4×4 confusion matrix `action_taken` vs `action_expected` — this is the skeptical-stakeholder artifact. Derived: over-flagging rate (expected pass → non-pass) and under-flagging rate (expected non-pass → pass), reported side by side to show the tuning dial.

**Threshold calibration (ADR-005):** the τ values shipped in `policies/*.yaml` are marked `# SEED(pre-calibration)` (ADR-016). They exist only so the policies load and the engine runs before a calibration set exists; **calibration below overwrites them, and a seed value is never judge-facing** — no seed-derived number appears in a report, the README, the proposal, or the video (AGENTS.md §7). τ_low/τ_high computed as quantiles of non-conformity scores on a held-out calibration split (70/30 split of `halluc.jsonl` + `borderline.jsonl`, ≈56 calibration points at v1 counts); report includes achieved-vs-target rate on the eval split. **Mandatory caveats printed with the numbers:** the exchangeability assumption, the calibration n, and a small-n variance note (quantile estimates at this n swing between runs; report a bootstrap CI or min/max over 5 reshuffles).

**Overlap correctness:** all OVLP cases must produce exactly one multi-label signal and the most-severe-action resolution (04 §4.3) — pass/fail listed per case.

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

| README claim | Source |
|---|---|
| Gateway overhead P50/P99 | `reports/latency_report.md` |
| PII recall / per-detector F1 | `reports/eval_report.md` §detectors |
| Per-use-case confusion matrix | `reports/eval_report.md` §policy |
| Calibrated τ + achieved rate | `reports/eval_report.md` §calibration |
| Cost savings (simulated) | `reports/cost_simulation.md` |
| Feedback loop before/after | `reports/feedback_loop_report.md` |
No number appears in README/proposal/video without a row here.
