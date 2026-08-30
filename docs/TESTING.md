# Testing & verification guide

How to run everything this repo can verify, in the order a newcomer should run it. Four
tiers, each self-contained: **unit → eval → latency → live gateway**. Tier 1 needs only
the light install and finishes in about ten seconds; the live tier is the only one that
touches a network.

This guide is *operational*. It does not restate contracts — where a command's meaning is
defined by a doc, the doc is cited and wins. Start with `AGENTS.md` §10 for the command
list in brief; this file is the same ground with the reasoning attached.

**Interpreters.** Verified on **Python 3.12.12 and 3.14.6**, full suite exit 0 on both.
`pyproject.toml` declares `>=3.11`; CI runs both ends of the range on every push
(`.github/workflows/ci.yml`). Two pins are floor-constrained by 3.14 and must not be
lowered: `pydantic>=2.13` and `spacy>=3.8.7`.

---

## Tier 0 — setup

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

That is enough for tiers 1–3. The `[ml]` extra (spaCy, sentence-transformers) is needed
only for the detectors that carry model weights, and **CPU-only torch must be installed
first** or pip resolves the multi-GB CUDA stack for no benefit — NFR-P-002 budgets are CPU
budgets:

```bash
.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -e ".[dev,ml]"
.venv/bin/python -m spacy download en_core_web_sm     # ADR-011 NER model
```

Secrets live in `.env` (gitignored; copy `.env.example`). The names are normative in
05 §6: `UPSTREAM_API_KEY`, `GROQ_API_KEY`, `REVIEW_WEBHOOK_URL`, `CP_DB_PATH`. Never
commit or print a value.

---

## Tier 1 — unit and contract suite

```bash
.venv/bin/python -m pytest -q
```

Expect **exit 0**. This is the gate for every other tier: if it fails, nothing below is
meaningful.

A large share of these are **differential** tests rather than assertions about code —
they parse a doc and compare the implementation against it, so that a contract changed in
prose fails here instead of drifting silently. `tests/test_telemetry.py` is the clearest
example: it extracts the span and metric vocabularies from 05 §5 and asserts set equality
with the registry, which means a metric invented at a call site and a metric added to the
doc alone both fail. When one of these breaks, read the doc first — the test is usually
reporting that code and contract disagree, not that the test is stale.

`tests/review/` holds reviewer-authored pins. They are **current-state-specific by
design**: they pin behaviour that is deliberately unfinished so that finishing it is a
visible, reviewable event. Update one only in the same commit as the transition it pins,
and say so in the commit message.

---

## Tier 2 — evaluation (accuracy, policy, failure semantics)

### The dataset is frozen — check that first

```bash
.venv/bin/python -m eval.validate_dataset            # internal consistency (06 §2.4)
.venv/bin/python -m eval.validate_dataset --freeze   # + byte-identity with the approved freeze
```

The 280-case labelled set is **frozen** (06 §1). `--freeze` asserts it is byte-identical
to the approved state, and `eval/run_all.py` runs that check before computing anything, so
a number cannot be produced against an edited corpus. A frozen case is **not** editable as
a fix — a correction is a new freeze cycle, which is a documented process, not a file edit.

### Accuracy and the policy matrices

```bash
.venv/bin/python -m eval.run_all                     # → reports/eval_report.md
```

Per-detector precision/recall/F1, the engine conformance matrix, and the end-to-end
matrix. Two things this prints that are supposed to look uncomfortable:

- **`NFR-EVAL-001: MISSED`** — `tier1_pii` recall is below its target. That is **SL-1**, a
  real unmet requirement, logged in `docs/08` and deliberately **not** tuned away. ADR-026
  §5 permits one re-measurement and it is already consumed; the target does not move.
- **End-to-end coverage below 100%** — the matrix covers the cases whose detectors exist.
  Coverage grows as detectors land; the figure is reported rather than the uncovered cases
  being dropped from the denominator.

Never iterate a pattern or a threshold against these fixtures to improve a number. First
contact with the frozen set is a blind measurement, and its value comes from being blind
(06 §3). A miss is filed, not fixed in place.

### Failure semantics under injected faults

```bash
.venv/bin/python -m eval.fault_injection             # → reports/fault_injection_report.md
```

Exits nonzero if any 04 §5 fail-open / fail-closed invariant breaks. Currently **27/27
assertions pass**. This is the harness that proves a detector timeout resolves by the
*policy's* declared `fail_mode` rather than by an engineering default — which is why
changing a fail-open to a fail-closed (or the reverse) is a D7-class change, not a
preference.

---

## Tier 3 — latency

```bash
.venv/bin/python -m eval.bench_latency               # → reports/latency_report.md
.venv/bin/python -m eval.bench_latency --check       # same, plus the NFR tripwire
```

`--check` exits nonzero on an NFR-P-001 or NFR-P-002 breach. Use it in CI and before any
claim about latency.

**What NFR-P-001 measures, since it is easy to get wrong.** ADR-030 re-scoped it onto the
two holds a user actually waits through — the input-lane hold before dispatch, and each
per-sentence hold — not the per-request sum. So the population is **holds, not requests**:
a ten-segment response contributes ten samples. The per-request sum is still published as
`total_attributable_overhead_ms`, with no target attached, which is how the respecification
withdrew a target without withdrawing a number.

**The margin is currently enormous, and that is a statement about coverage, not speed.**
Only the Tier-1 regex detectors exist, so the measured holds are a fraction of a
millisecond against 40/100 ms targets. The report's *forward projection* section carries
what those figures become when the remaining hot-path detectors land — that section is
arithmetic over declared budgets and is labelled as such. Do not quote a projection as a
measurement.

### `reports/` is evidence, not build output

Committed reports are **version-controlled evidence** (06 §8). A report is citable only if
it carries the commit it was generated at and a clean-tree provenance stamp — so:

1. Commit the code first.
2. Regenerate the report from the resulting clean tree.
3. Commit the report together with any claim that cites it.

Generating from a dirty tree stamps `+ uncommitted changes` and the report is not citable.
The dirty check has no pathspec, so *any* pending file trips it — the ordering above is
load-bearing, not stylistic. **CI never writes to `reports/`**: it redirects both harnesses
with `--out` and then asserts the directory is untouched. Evidence comes from a human run
on real hardware.

---

## Tier 4 — the live gateway

```bash
.venv/bin/uvicorn --factory controlplane.gateway.app:create_app --port 8099 --reload
```

Two things about that command are not stylistic:

- **`--factory` is required.** `app.py` exposes `create_app()` and deliberately no
  module-level `app`, because a module global would leave a stale copy behind a hot reload.
- **Never serve on port 8000.** The `kiro-local` provider's `base_url` is
  `http://localhost:8000`, so a gateway on 8000 proxies to itself.

### The three pipelines

Policies are per-use-case YAML in `policies/`. The use case is the *only* thing that
differs between them at the gateway — there is no `if use_case == ...` anywhere in Python,
by design (that is the product thesis).

| # | `use_case` | Policy file | Delivery |
|---|---|---|---|
| UC-1 | `support_bot` | `policies/support_bot.yaml` | streaming |
| UC-2 | `hr_copilot` | `policies/hr_copilot.yaml` | streaming |
| UC-3 | `finance_advisor` | `policies/finance_advisor.yaml` | non-streaming |

Select one with the **`X-ControlPlane-Use-Case`** header:

```bash
curl -sN http://localhost:8099/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-ControlPlane-Use-Case: support_bot' \
  -d '{"messages":[{"role":"user","content":"hello"}]}'
```

Other request headers, all 05 §1.1: `X-ControlPlane-Conversation-Id`,
`X-ControlPlane-Request-Id`, `X-ControlPlane-Actions`.

**Use-case resolution.** The header is the primary path and wins when both are present. An
API key mapped in `config/keys.yaml` (gitignored; see `config/keys.yaml.example`) is an
ambient default. An *absent* keys file is an empty map and boots fine; a *malformed* one is
a hard error, so a broken config cannot masquerade as a missing header. Note that v1 has
**no authorization** (05 §2 states the limitation): that map is routing, not authz.

### Admin surface

```
GET  /admin/policies                  # loaded policies
POST /admin/policies/reload           # re-read from disk
GET  /admin/review                    # escalation queue
POST /admin/review/{id}               # {"decision":"approve"|"reject","note":"..."}
GET  /admin/review/{id}/released      # what was released after a decision
GET  /metrics                         # 05 §5 vocabulary
```

### Try the signature moment

Send the **same** prompt to two use cases and watch the verdicts diverge — passing in one
pipeline, blocked or edited in another, purely from policy config. That is the thesis of
the product, and `docs/07-demo-script.md` scripts it beat by beat.

### Upstream providers

`config/gateway.yaml` splits providers into two **classes**, and the class is a provenance
claim (ADR-018). `active_provider` ships as `kiro-local`, which is **dev class**: fine for
building, and its numbers may never appear in a report. The measured-class Groq tiers are
`openai/gpt-oss-20b` (small) and `openai/gpt-oss-120b` (frontier) — priced per concrete
model id, because a cascade whose premise is that the tiers cost differently cannot be
expressed by one price pair per provider (ADR-022).

---

## Not runnable yet

Stubs, marked `STUB(...)` in source. A stub must never satisfy a test, and no number may be
reported from one:

`eval.cost_simulation` · `eval.pii_leak_scan` · `eval.override_report` ·
`eval.suggest_thresholds` · `demo/run_script.py` · `dashboard/app.py`

`demo/run_script.py` being a stub has a consequence worth knowing: the demo path in
`docs/07-demo-script.md` currently has **no automated runner**, so "the demo still passes"
is established by the suite and the fault harness, not by replaying the sequence.

---

## Gotchas

- **YAML 1.1 booleans (Q-09).** PyYAML parses YAML 1.1, where bare `on`/`off` are
  booleans. In policy files, `consistency` and `cascade_probe` values must be **quoted**;
  `streaming` is a real boolean and stays unquoted.
- **No raw PII anywhere.** Log the *fact and category* of an interception, never the
  matched value — logs, traces, audit records, fixtures, reports. A leak in committed
  history cannot be withdrawn.
- **Never weaken a failing test or a missed target.** A failing benchmark is a finding to
  file, not a harness to adjust. This is what makes the numbers worth citing.
