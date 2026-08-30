# Stale prose register

Created 2026-08-30 under AGENTS.md §11.1 credit-conservation mode. Prose **outside**
judge-facing reports is listed here for one final pass instead of being fixed inline.

**Scope boundary, because it is the whole point of the file:** prose *inside* a judge-facing
report is NOT listed here — it is a published claim and gets fixed where it is found. The two
entries below were therefore *not* stale prose; they were **stale artifacts awaiting a
measurement run**, recorded here only so the distinction is written down somewhere.

## Awaiting a measurement run (not prose — do not "fix" by editing) — BOTH CLEARED 2026-08-30

| Artifact | What was stale | Cleared by | Verified |
|---|---|---|---|
| `reports/eval_report.md` (~line 119) | The `entity_enricher` row read `"not implemented — stub; needs spaCy en_core_web_sm (ADR-011)"`. The stage landed 2026-08-29 and `eval/run_all.py` derives that string by probing the host (`_enricher_reason()`), so the code was correct and only the artifact predated it | `python -m eval.run_all`, quiet host, start stamp load1 = **1.00 QUIET** | The row now reads **"implemented and loadable; not reachable by any corpus case"** — a different claim, and the one the probe produces |
| `reports/latency_report.md` | Predated both the `tier2_injection` landing and the partitioned absent list (M-42/M-43 fixes) | `python -m eval.bench_latency`, quiet host, start stamp load1 = **0.95 QUIET** | `tier2_injection` carries a per-detector row, and the absent list is partitioned into **"Not exercised in this run"** (5 detectors) vs **"Implemented, but outside this harness"** (`entity_enricher`) |

Neither was edited by hand: doing so would substitute a typed value for a measured one
(AGENTS.md §5.4). Both were **regenerated**, and the rows are kept rather than deleted because
"cleared by a measurement run on a stamped quiet host" is the evidence, and an empty table
would not carry it.

## Stale prose (the actual list)

**Empty as of 2026-08-30**, at the end of the Phase-5 sweep. Stated explicitly rather than
left blank: nothing has been *found* and deferred. Every doc figure is re-derived clean by
`eval.check_derivations` (**72/72 OK** — the count was written here as `55/55` and was stale
in this file itself, which is the mildly funny failure mode a register like this invites; the
number is not hand-maintained anywhere else, `eval.check_derivations` prints it).

Two things found during the sweep are deliberately **not** listed here, because neither is
stale prose:

- The false claims in my own `SL-7` draft and in the `[D3-nfr-p002-gate-reads-the-clock-adr-036-rejected]`
  report were **corrected in place, in the same commit that found them** — a wrong claim about
  a measurement is not deferrable work.
- Two citability gaps are logged in `docs/08-open-questions.md` as **M-54** and **M-55**
  rather than fixed: `eval/fault_injection.py` emits no load stamp (and M-53 has since made
  that harness's outcomes load-sensitive), and `git_stamp` reports any untracked file as a
  dirty tree — including the sibling reports a measurement run writes, so read literally it
  disqualifies every artifact this repo emits. Both are real, both are in the M register the
  open count is enumerated from, and neither is prose. They were filed *because* this file
  asserted they were logged when they were not.

Add rows here as prose is found during other work — that is what the file is for.
