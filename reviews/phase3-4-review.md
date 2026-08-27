# Checkpoint 3 — Phases 3+4 Combined Review

**Reviewed range:** `554e0d0..6edf17a`  
**Reviewed commit:** `6edf17a9ae76fbe5bc6646c82572fd346a13dabc`  
**Review date:** 2026-08-27

## Gate

**BLOCKED — Phases 3–4 do not receive PASS from this review.** The policy-engine
differential is clean (840/840) and all seven semantic mutants were killed, but the requested
clean-venv full-suite `exit 0` and the long-running fault/latency closure executions could not be
certified: bounded aggregate runs reached the benchmark-heavy portion and ended without a
terminal success (one explicitly returned `124`; later runs were interrupted rather than
misreported as passes). This is a verification blocker, not evidence of a behavioral failure.

One expected non-blocking observation remains: M-20's old persisted latency key and absent
last-byte key are still explicitly documented as not emitted. A review regression test now pins
the four keys an audit row actually writes.

## Commits reviewed (oldest first)

1. `6ea321b` — policy engine + both NFR-EVAL-002 matrices.
2. `6dd3fec` — ADR-027 detector-failure event model.
3. `0b4a183` — ADR-026 cleanup and span-less label correction.
4. `e471922` — Phase 4 telemetry, policy store, and audit foundation.
5. `2943b16` — gateway ingress and error contract.
6. `888e524` — sentence buffer.
7. `452db52` — usage-canary deviation filing.
8. `31e5211` — tier-resolution hardening.
9. `ca183d3` — upstream dispatcher and SSE relay.
10. `0f8dd63` — ADR-027 stamp-column blocker filing.
11. `c966d33` — review queue and HITL overrides.
12. `bdbcb7d` — M-8 latency-key ruling.
13. `1c530d7` — ADR-027 Amendment 1 stamp columns.
14. `f4155e9` — ADR-028 local canary reference.
15. `e69ec11` — single-source span-less labels.
16. `7d021ed` — GFM table escaping.
17. `ede9a2d` — audit data-model diagram refresh.
18. `7e58443` — closed-blocker docstring corrections.
19. `62f186e` — documentation/diagram cleanup.
20. `7595c08` — Phase-5 deferral and detector-coverage column.
21. `126d1ec` — gateway spine.
22. `9c194d4` — M-13 crash-safe audit path.
23. `47d1439` — startup canary wiring.
24. `197265c` — 06 §5 fault-injection harness.
25. `1fab759` — 06 §4 latency benchmark.
26. `cf45d6b` — ADR-029 batch landing.
27. `9e59525` — forward projection and ADR-030 precursor deviation.
28. `3507dba` — fault-injection report commit (report commit 1).
29. `5161081` — latency report commit (report commit 2).
30. `149b00f` — ADR-030 NFR-P-001 re-scope.
31. `0c896eb` — ADR-030 latency/README regeneration (report commit 3).
32. `505c82d` — M-18/M-19/M-20 targeted-series closure work.
33. `6edf17a` — final regenerated latency/README claim update.

The range contains 33 commits. The three report-landings requested by the checkpoint are
`3507dba`, `5161081`, and `0c896eb`; `6edf17a` is the final report/README follow-up.

## Findings

### F1 — Required clean-suite and closure executions were not certified

- **Severity:** MAJOR (gate-blocking verification failure)
- **File:line:** `pyproject.toml:39` (pytest configuration); benchmark-heavy boundary begins
  in `tests/test_bench_latency.py:1`
- **Doc section:** 06 §4, 06 §5, 06 §8; checkpoint hygiene item 13
- **Evidence:** collection reports **961 tests on the reviewed tree** and **964 after adding
  this review's mandatory M-20 test and two reviewer-devised mutation tests**. The dataset freeze command completed successfully for
  280 cases. Direct engine/review tests completed successfully. However, bounded aggregate
  contract/full-suite runs did not return `0`; one bounded run returned `EXIT=124`, and later
  runs were interrupted after remaining non-terminal in the benchmark-heavy portion. The
  fault and full latency harnesses likewise did not yield terminal results during this review.
  Partial dot progress is not an exit code and is not counted as a pass.
- **Impact:** items 4–11 and 13 have strong code/test/report evidence, but this reviewer cannot
  independently certify their requested runtime closure or the clean-venv `exit 0` gate.
- **Disposition:** rerun in a fresh venv, sequentially, capture `pytest -q` showing the 961-test
  reviewed-tree baseline (or 964 with this review's three tests) and `exit 0`, then run
  `python -m eval.fault_injection` and `python -m eval.bench_latency --check` to terminal
  completion. Attach stdout, wall time, and generated-artifact diffs. No production fix is
  proposed from timeout evidence alone.

### F2 — M-20 persisted-key rename remains deliberately unfinished

- **Severity:** OBSERVATION
- **File:line:** `docs/05-api-and-data-contracts.md:87`,
  `docs/05-api-and-data-contracts.md:243`, `controlplane/telemetry/spans.py:70`
- **Doc section:** 05 §3/§5; ADR-030; M-20
- **Evidence:** 05 explicitly says code still writes `gateway_overhead_ms`, not
  `total_attributable_overhead_ms`, and does not emit `added_time_to_last_byte_ms`. The new
  `tests/review/test_checkpoint3_latency_keys.py` parses that current/deferred statement, writes
  a real SQLite audit row, reads `latency_json` back, and pins the exact current key set:
  `gateway_overhead_ms`, `upstream_ms`, `input_hold_ms`, `sentence_holds_ms`. It passes.
- **Disposition:** keep the observation open until production emits the ADR-030 replacement
  and last-byte row; update the test atomically with that implementation/doc transition.

## Requested checks

### 1–2. Engine, matrices, Q-12 tripwire — VERIFIED

- `Policy.action_for` is backed by load-time expansion in which default is installed first,
  wildcard second, and specific labels last: **specific > wildcard > default**.
- `engine.evaluate` applies the confidence band only to `ScoreKind.CONFIDENCE`; detection
  signals bypass it. `meta.enriched_labels` partitions host/enriched outcomes. ADR-019 has
  exactly two enriched arms; ADR-015 promotes edit-without-extent; convergence uses
  PASS < EDIT < ESCALATE < BLOCK.
- The direct test command completed: **18 passed**. This includes the frozen-corpus baseline
  (**280 cases × 3 policies = 840/840**) and all mutation tests.
- Builder mutants killed: band leakage, enriched-follows-host, missing span-less promotion,
  reversed severity, and default-only action mapping. Reviewer mutants killed: wildcard beats
  specific, and default beats wildcard. **Kill rate: 7/7 = 100%.**
- `eval/policy_matrix.py` does not import/call `validate_dataset.derive_action`; synthesis is
  structurally barred from action resolution. The freeze gate independently completed for 280
  cases. No Q-12 disagreement was found.
- Artifact B's reconciliation implementation consumes raw miss/false-positive case-id lists
  and unions mismatches across policies. Its published reconciliation was inspected, but a new
  terminal `run_all` result was not obtained in this review; that runtime certification remains
  covered by F1.

### 3. ADR-027 audit and failure semantics — CODE/TEST EVIDENCE PASS; runtime recertification F1

`serialize_signals` rejects non-`Signal` values, so a `DetectorFailureRecord` cannot enter
`signals_json`. `AuditRecord.from_verdict` stamps both id lists, `write_record` persists them,
and `canonical_view` reads them. Review-queue `escalation_cause` distinguishes content, failure,
and both. Existing constructed tests cover failure-only and content-only records. Independent
aggregate execution did not reach a terminal result, so F1 prevents a runtime-certified PASS.

### 4. Gateway and failure semantics — CODE/TEST EVIDENCE PASS; runtime recertification F1

Sentence-buffer code releases only completed units; existing adversarial coverage includes a
flagged sentence split across chunks. ADR-020 records spans/categories rather than received/sent
raw text. Audit writes and review-item masking contain NFR-SEC-001 guards. ESCALATE stores masked
quarantine text for both release states. The M-13 post-release path writes a partial audit row in
`finally`. These are present and specifically tested; the requested fresh end-to-end constructed
run was not terminally certified (F1).

### 5. ADR-028 canary — CODE/TEST EVIDENCE PASS; runtime recertification F1

The reference is `local_estimate`, named in `CanaryResult`; no provider endpoint is the sole
reference. The canary refuses measured-class boot on gross inflation and records unreachable
checks as `UNCHECKED`, not passed. The +5,000-token scaffold and unreachable cases exist in the
test suite. F1 covers the missing fresh terminal aggregate result.

### 6. ADR-029 landing — INSPECTION PASS

`cf45d6b` is coherent as one batch: dead llama probes and serving gpt-oss probes are recorded;
tiers bind `openai/gpt-oss-20b` / `openai/gpt-oss-120b`; ADR-009 and the ADR-022 test amendment
land together; prices carry first-party `source_url` and retrieval date; SL-3 is narrowed to
the two bound ids. No stale llama id was found in `reports/` or `demo/`. The commit history
preserves the filing, overrule, and batch landing rather than rewriting the audit trail.

### 7. Fault injection — DOCUMENT/TEST EVIDENCE PASS; execution BLOCKED by F1

The harness asserts fail-closed never silently BLOCKs, reads both SC-3 outcomes from audit, and
states the honest **2-of-4** fault-class coverage limit (`tier1`/`performance` live; `tier2`/`cost`
untested). The committed report states 27/27 assertions. A new terminal harness result was not
obtained, so this cannot independently close under this review.

### 8. ADR-030 target derivation — ARITHMETIC/INSPECTION PASS

Independent arithmetic from `BUDGETS_MS`/`LANES` under parallel Tier-2 execution matches ADR-030:
input 25 + engine 5 = **30 ms**; typical sentence 25 + engine 5 = **30 ms**; enriched typical
25 + enrichment 10 + engine 5 = **40 ms**; context 30 + 10 + 5 = **45 ms**; sampled boundary
60 + 10 + 5 = **75 ms**. Every row fits P99 50/100; the exact **40.0 ms** strict-P50 adjacency is
recorded. The target derivation predates Tier-2 measurements, preserves the original projection,
distinguishes itself from ADR-026 §5, and leaves SL-1 untouched. No sign of result-fitting was
found.

### 9. ADR-030 closure — REPORT/CODE EVIDENCE PASS; execution BLOCKED by F1

The committed report publishes `input_hold_ms` n=200 and `sentence_holds_ms` n=238, explicitly
using **holds**, not requests; max segmentation is 10. It keeps total attributable overhead
untargeted. Code writes `cp.ingress`, `cp.policy.evaluate`, and `cp.action.apply`; ADR-030 records
that the original 0.095 ms engine claim was previously unsourced and now traces it to those spans.
The re-anchored series-row mutation is covered in `tests/test_bench_latency.py`. Independent raw
span recomputation and mutation execution did not complete terminally in this review (F1).

### 10. Honesty state / M-18 — INSPECTION PASS

The 10 ms enrichment cap is documented as a specification ruling; the enricher remains a stub and
judge-facing prose does not claim live enforcement. `cp_enrichment_skipped_total` appears in both
the code registry and 05 §5. The set-equality vocabulary test exists; fresh aggregate execution is
subject to F1.

### 11. README integrity — INSPECTION PASS

The freeze citation matches 06 §2's corrected freeze history (`f162959`, digest prefix
`6a3ecbbe…`). The claims table has the documented blank-state split: 10 figure-bearing rows, three
not-yet-measured rows, and one not-computed row. Figure rows point to committed reports; no claim
row cites this review's dirty/uncommitted artifact.

### 12. M-20 residue — OBSERVATION + TEST ADDED

See F2. The new test is intentionally current-state-specific: it prevents a silent persisted-key
rename while 05 still declares the rename deferred.

### 13. Hygiene — BLOCKED by F1

- Freeze: **PASS**, 280 cases, digest match.
- Collection: **961** tests on reviewed tree; **964** after this review's three tests.
- Ledger: inspection confirms **18/18 closed**, open count zero.
- SL-3 and prose-fix log: current on inspection.
- Policy/config governing-ADR scan: no divergence found.
- Adversarial ingress cases are present (unknown use case, conflicting stream flags, malformed
  reload, oversized bodies), but the requested clean full-suite terminal `exit 0` was not obtained.

## Reviewer disposition

Do not mark Phases 3–4 closed from this review. Resolve F1 by producing terminal clean-environment
results for the full suite and both long-running evaluation harnesses; then this report can be
re-reviewed without changing the substantive engine conclusion. F2 is non-blocking, intentional
residue and now has a regression tripwire.

No production code, policy, config, report, or governing document was modified by this review.
