# F1 certification — terminal clean-environment results

Response to **F1** of `reviews/phase3-4-review.md` (MAJOR, gate-blocking): the reviewer could
not certify the clean-venv `exit 0` gate or the two long-running harnesses, having seen one
bounded run return `EXIT=124` and later runs remain non-terminal in the benchmark-heavy portion.

**Finding: nothing in the suite is non-terminal.** `EXIT=124` is `timeout`'s exit code — a
budget expiring, not a hang. Every gate completes in seconds. Evidence below.

Produced at tree **`4c8e9d4`** (the reviewed tree, unmodified) in a **fresh virtualenv** built
from `pip install -e ".[dev]"`, run sequentially, before any Phase-5 dependency touched this
machine. That ordering is deliberate: installing the `[ml]` extra changes the environment, so
this certification would not have been reproducible afterwards.

## 1. Full suite — fresh venv, both interpreters

Run as CI runs it: plain `python -m pytest -q`, no plugin flags, no `-p` overrides.

| Interpreter | Command | Exit | Wall | Tests | FAILED/ERROR |
|---|---|---|---|---|---|
| CPython 3.14.6 | `python -m pytest -q` | **0** | 9 s | **964** | 0 |
| CPython 3.12.12 | `python -m pytest -q` | **0** | 7 s | **964** | 0 |

The **964** matches F1's own arithmetic exactly — 961 on the reviewed tree plus the review's
three added tests (the mandatory M-20 pin and two reviewer-devised mutation tests). Both
interpreters collect the same 964, so nothing is interpreter-gated.

Note on the earlier session's reporting: `pytest`'s summary line is suppressed by this repo's
configuration, so a count must be summed from the per-file collection output. Partial dot
progress is indeed not an exit code — the exit codes above are captured directly from `$?`.

## 2. Closure harnesses — terminal

| Harness | Command | Exit | Wall | Result |
|---|---|---|---|---|
| Fault injection (06 §5) | `python -m eval.fault_injection` | **0** | < 1 s | **27/27 assertions passed** |
| Latency tripwire (06 §4) | `python -m eval.bench_latency --check` | **0** | 4 s | no NFR-P-001/002 violation |
| Freeze gate (06 §1) | `python -m eval.validate_dataset --freeze` | **0** | 151 ms | 280 cases byte-identical to digest `6a3ecbbe75fd020b…` |
| Accuracy + matrices | `python -m eval.run_all --out <tmp>` | **0** | 1 s | conformance 1.0000; end-to-end 0.9811 over 159 covered; `NFR-EVAL-001: MISSED` (= SL-1, logged, untuned) |

`eval.run_all` is included beyond F1's ask because it was also uncertified; it too terminates.
It was run with `--out` to a temporary path, so `reports/eval_report.md` is untouched by this
certification.

Every wall time above is measured, not estimated. The whole verification surface — full suite
plus all four harnesses, on one interpreter — completes in **well under 30 seconds**. Whatever
consumed the reviewer's timeout budget, it was not the work itself.

## 3. Generated-artifact diffs

Both report harnesses write by default into `reports/`, so each run produces a diff. Every
differing line is provenance or measurement jitter — no structural or assertion change:

- `reports/fault_injection_report.md` — 14 changed lines: the UTC timestamp, the provenance
  commit stamp, and fresh per-run failure-record UUIDs. Assertion table identical, **27 PASS /
  0 FAIL** on both the committed and regenerated versions.
- `reports/latency_report.md` — 30 changed lines: timestamp, commit stamp, and percentile
  figures moving in the third decimal (e.g. `input_hold_ms` P99 0.26 → 0.27 ms;
  `sentence_holds_ms` P99 0.77 → 0.75 ms). Both sides pass every NFR-P-001 target by three
  orders of magnitude, so the jitter changes no verdict.

**Both files were reverted after each verification run.** The committed reports remain the ones
generated from a clean tree at the commits that carry their claims, per 06 §8 — a report
regenerated merely to prove a harness terminates is not new evidence, and committing it would
have replaced provenance-bearing evidence with a by-product.

## 4. Reproducing this

```bash
python3 -m venv /tmp/f1venv && /tmp/f1venv/bin/pip install -e ".[dev]"
/tmp/f1venv/bin/python -m pytest -q                     # exit 0
/tmp/f1venv/bin/python -m eval.validate_dataset --freeze # exit 0
/tmp/f1venv/bin/python -m eval.fault_injection           # exit 0, 27/27
/tmp/f1venv/bin/python -m eval.bench_latency --check      # exit 0
git checkout -- reports/                                 # discard the by-product
```

Hardware: single machine, Linux 7.1.2-arch3-1, x86_64 — the same class of prototype hardware
every published figure in `reports/` was measured on.

## 5. What this does and does not settle

**Settles:** F1's disposition. The clean-venv gate and both closure harnesses return terminal
`exit 0`, on both supported interpreters, at the reviewed tree.

**Does not settle:** F2, which remains open by design — the M-20 persisted-key rename and
`added_time_to_last_byte_ms` are still unemitted, and `tests/review/test_checkpoint3_latency_keys.py`
still pins the current key set. That transition is Phase-5 work and will update the pin
atomically, in one commit, citing F2.

**F2 closed 2026-08-30**, as this paragraph anticipated and by the route it named for one
half: the rename emitted in `ab06917` with the pin re-pointed in that same commit. The other
half closed by **specification correction** instead — ADR-030 Amendment 1 re-sited
`added_time_to_last_byte_ms` to 06 §4 as a benchmark-client figure, because no gateway
vantage for it exists. Full note in `reviews/phase3-4-review.md` F2.

**Standing consequence:** these gates now run per-push. `.github/workflows/ci.yml` (M-21)
executes this exact sequence on py3.12 and py3.14, so the class of uncertainty F1 identified —
"passes on the author's machine" being indistinguishable from "passes" — is closed structurally
rather than by this one attestation. CI redirects both harnesses with `--out` and asserts
`reports/` is untouched, so it can never author evidence.
