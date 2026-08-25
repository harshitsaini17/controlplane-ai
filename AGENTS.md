# AGENTS.md — Agent Operating Manual for ControlPlane.ai

> **Audience:** Any coding agent working in this repo (Claude Code, Codex, etc.).
> **Status:** Binding. If anything here conflicts with your general habits, this file wins.
> **Claude Code note:** `CLAUDE.md` at repo root imports this file. Codex reads this file directly. Keep this file as the single source of truth — never maintain two diverging copies.

---

## 1. What you are building (30-second context)

ControlPlane.ai is a **real-time AI oversight gateway** — a reverse proxy between an app and its LLM provider that checks every response across three planes (**Performance / Cost / Responsibility**) and routes each response through a policy decision: **Pass / Edit / Block / Escalate**. Policies are **configurable per use case** (that's the headline feature — see §9).

This is a **hackathon Round 2 prototype** (Accenture Innovation Challenge 2026), not a production system:

- Prototype-grade is acceptable. **Fabricated results are not.** Every number we present (latency, FP/FN rates, cost savings) must come from an actual measurement in this repo.
- The judged deliverables are: working prototype, business proposal, public GitHub repo, demo video, README. The **demo path is sacred** (see §8).
- Deadline pressure is real. Prefer the simplest implementation that satisfies the spec. Do not gold-plate.

---

## 2. Prime directive: the docs are the contract

This project is **spec-first**. The `docs/` folder was written *before* the code deliberately. Your job is to implement the documented system — not the system you would have designed.

**Therefore:**

1. Code serves the docs. When code and docs disagree, the docs are presumed correct until a human rules otherwise.
2. You never silently change either side to make them agree. Mismatches go through the **Deviation Protocol** (§5).
3. If a doc doesn't answer a question you need answered, that's a **doc gap** — also §5, not an invitation to improvise.

---

## 3. The doc map — what to read, and when

| Doc | Answers | Read it when… |
|---|---|---|
| `docs/00-charter.md` | Why this exists; goals, **non-goals**, assumptions, success criteria | Session start; any time you suspect scope creep |
| `docs/01-requirements-and-scenarios.md` | FR/NFR requirements (FR-xxx / NFR-xxx IDs); the 3 demo use cases | Before starting any feature; when writing tests |
| `docs/02-architecture.md` | System shape: planes, fast/slow path, policy engine placement, request lifecycle | Before touching anything cross-component |
| `docs/03-decisions.md` | ADR log — every "why did we choose X" | Before proposing a different library/approach/pattern |
| `docs/04-policy-and-detection-spec.md` | Detector contracts + latency budgets; policy YAML schema; Pass/Edit/Block/Escalate state machine; fail-open/fail-closed rules | Before touching any detector or the policy engine — this is the core spec |
| `docs/05-api-and-data-contracts.md` | Gateway API surface; policy config schema; audit-log record schema; telemetry/OTel spans | Before adding/modifying any endpoint, schema, log record, or metric |
| `docs/06-evaluation-plan.md` | Labeled test dataset design; FP/FN methodology; latency benchmark method | Before writing tests; before reporting any measured number |
| `docs/07-demo-script.md` | The beat-by-beat judge demo | Before merging anything — could this break a demo beat? |
| `docs/08-open-questions.md` | Known unknowns and their current working assumptions | When blocked on ambiguity — check here **before** raising a deviation |

**Minimum reading before writing any code in a session:** `00`, `02`, and the specific doc(s) covering the component you're touching. Do not skim `04` — it is the center of gravity of this system.

### Precedence when docs conflict with each other

1. `03-decisions.md` (an accepted ADR) beats prose in any other doc.
2. `04` and `05` (contracts/schemas) beat `02` (narrative architecture).
3. `00-charter.md` non-goals beat everything — if a task requires violating a non-goal, stop.
4. Any remaining conflict between docs → **Deviation Report** (§5). Do not pick a side yourself.

---

## 4. Standard task workflow

**Before coding:**
1. Restate the task in one sentence and identify the requirement ID(s) it serves (FR-xxx / NFR-xxx). If no requirement covers it, stop → §5 (scope gap).
2. Read the relevant docs (per the map above).
3. State your plan briefly. For anything touching the policy engine, a detector contract, a schema, or the demo path — wait for human confirmation before implementing.

**While coding:**
- Reference requirement IDs in commit messages and test names (e.g., `test_fr012_pii_edit_action`).
- New config keys, endpoints, metrics, or log fields **must** already exist in `05` — if they don't, that's a doc gap, not a green light.
- Stubs/placeholders are allowed but must be marked `# STUB(reason, owner-decision-needed?)` and listed in your end-of-task summary. Never let a stub silently satisfy a test.

**After coding:**
1. Run the relevant slice of the eval suite (`06`). Detector or policy changes → always run the FP/FN eval and the latency benchmark.
2. Confirm the demo script (`07`) still passes end-to-end if you touched anything on its path.
3. Summarize: what changed, which requirements it satisfies, any stubs left, any doc updates made, any deviations raised.

---

## 5. THE DEVIATION PROTOCOL (most important section)

### 5.1 Stop conditions — you MUST halt and report before proceeding when:

- **D1 — Architecture contradiction.** Implementation or testing reveals the documented design doesn't work as specified (e.g., the sentence-buffer interception can't meet the documented latency budget; a documented library doesn't support a documented behavior; the cascade logic as specified produces wrong routing).
- **D2 — Contract mismatch.** A real API/library/schema differs from what `05` documents (field names, response shapes, streaming behavior, error semantics).
- **D3 — Budget breach.** A measured number violates a documented NFR (latency budget per detector, gateway P99 overhead, FP/FN targets). A failing benchmark is a deviation, not a test to weaken.
- **D4 — Spec ambiguity with consequences.** Two reasonable readings of a doc lead to materially different implementations, and `08-open-questions.md` doesn't resolve it.
- **D5 — Doc-vs-doc conflict** not resolved by the precedence rules in §3.
- **D6 — Scope gap.** The task requires functionality no requirement covers, or that touches a charter non-goal.
- **D7 — Security/safety surprise.** Anything that would log or persist raw PII, disable a fail-closed behavior, weaken input validation, or embed a secret.
- **D8 — Test-revealed design flaw.** A test can only pass by contradicting the spec, or the spec itself is untestable as written.

### 5.2 What "halt" means

Finish nothing that depends on the contested point. You may continue **unrelated** work in the same session, but clearly flag that the deviation is open.

### 5.3 Deviation Report format (use exactly this)

```
## DEVIATION REPORT [D<type>-<short-slug>]
Severity: BLOCKER | MAJOR | MINOR
Doc & section: <e.g., 04 §3.2 "Fast-path self-consistency scorer">
The doc says: <quote or tight paraphrase>
Reality says: <what you found — include the actual error/measurement/evidence>
Impact if we ignore it: <one or two lines>
Options:
  A) <option> — trade-off: <…>
  B) <option> — trade-off: <…>
Recommendation: <A or B, one line of reasoning>
Blocked work: <what waits on this decision>
```

One report per issue. One decision request at a time. Do not bundle five deviations into a paragraph of prose.

### 5.4 What you must NEVER do

- Never edit a doc to match the code without an approved deviation.
- Never edit code to quietly diverge from a doc "because it works."
- Never weaken, skip, or delete a failing test to get green.
- Never substitute a hardcoded/mocked value where the docs specify a measured or computed one — especially in anything that produces judge-facing numbers.
- Never resolve a deviation by choosing your own recommendation without an explicit human "approved."

### 5.5 After a deviation is approved

In the **same commit/PR** as the code change:
1. Update the affected doc(s).
2. Append an ADR entry to `03-decisions.md`: context (link the deviation), the ruling, the trade-off accepted.
3. If it invalidated an assumption, update `00-charter.md` assumptions and/or close the item in `08-open-questions.md`.

Docs and code move together, always. A PR that changes behavior without touching docs is incomplete by definition.

---

## 6. Severity guide

| Severity | Meaning | Agent behavior |
|---|---|---|
| **BLOCKER** | Contradicts an ADR, a core architecture element, a fail-safe behavior, or the demo path | Full stop on that workstream; report immediately |
| **MAJOR** | Contract/schema mismatch, NFR breach, consequential ambiguity | Report before implementing anything dependent on it |
| **MINOR** | Doc gap with an obvious low-risk answer (naming, trivial detail) | Proceed with the obvious answer **and** log it in the report queue + `08-open-questions.md` in the same session |

When unsure which severity applies, round **up**.

---

## 7. Measured-numbers policy (judge-facing integrity)

This project's credibility with judges depends on real numbers. Rules:

- Any latency, FP/FN rate, cost figure, or interception count that appears in the README, dashboard, business proposal, or demo must be reproducible by a script in this repo (per `06-evaluation-plan.md`).
- Benchmarks report the measurement method alongside the number (hardware, sample size, percentile).
- If a documented target isn't met, the honest measured number + a D3 deviation is the correct output. Never "adjust" the harness to hit a target.

---

## 8. Demo-path protection

`docs/07-demo-script.md` defines an exact request sequence the judges will see. Treat it as a permanent regression suite:

- Any change touching the gateway hot path, policy engine, detectors, config loading, or dashboard requires re-running the demo sequence before the task is "done."
- A broken demo beat is automatically **BLOCKER** severity, even if all unit tests pass.
- The signature demo moment — *the identical response passing in one use-case pipeline and being blocked in another, purely due to policy config* — must work at all times once implemented. It is the thesis of the product.

---

## 9. Project-specific traps (things agents predictably get wrong here)

1. **Don't hardcode policy.** Every threshold, action mapping, geography rule, and fail-open/fail-closed choice lives in per-use-case YAML per the schema in `04`/`05`. If you find yourself writing an `if use_case == "support_bot"` in Python, stop — that logic belongs in config.
2. **Don't "fix" fail-closed to fail-open (or vice versa).** Failure behavior when a detector times out or crashes is a *per-use-case documented decision*, not an engineering preference. Changing it is D7.
3. **Risk signals are multi-label.** A single sentence can be simultaneously a hallucination and a privacy leak. Detectors emit independent signals; only the policy engine converges them. Don't build early-exit logic that suppresses one plane's signal because another already fired — unless the spec says so.
4. **Respect the fast/slow split.** Nothing async-lane (semantic entropy, fairness audits, LLM-judge) may ever be awaited on the hot path, no matter how convenient. Conversely, don't quietly demote a documented hot-path check to async to hit a latency number — that's D3.
5. **Sentence buffer, not token-by-token and not full-response.** Interception granularity is specified in `04`. Both "simpler" alternatives break either latency claims or the interception guarantee.
6. **Audit log is append-only and PII-safe.** Log the *fact and category* of a PII interception, never the raw matched value. Raw PII in any log/trace/fixture output is D7.
7. **The eval dataset is a spec artifact.** Test cases and labels come from `06`. Don't invent ad-hoc test strings for detector accuracy claims — additions to the labeled set go through the docs.
8. **Simplest stack wins.** FastAPI/Python per the ADRs. Do not propose Go/Rust rewrites, Kubernetes, or message brokers beyond what `03-decisions.md` accepted — hackathon non-goal.

---

## 10. Environment & commands

> Keep this section current — agents rely on it. Commands marked **[Phase 2+]** are not
> runnable yet: the module exists as a docstring stub only. Do not report a number from a
> stub (AGENTS.md §7).

```
Setup (light — schema, policies, audit DB, tests):
  python -m venv .venv
  .venv/bin/pip install -e ".[dev]"

Setup (full — adds the 02 §8 model stack; do the torch step FIRST):
  .venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
  .venv/bin/pip install -e ".[dev,ml,dashboard]"
  .venv/bin/python -m spacy download en_core_web_sm      # ADR-011 NER model
  # Skipping the CPU-only torch line makes pip pull the full CUDA stack (multi-GB) for
  # no benefit — NFR-P-002 budgets are CPU budgets.

Unit tests:   .venv/bin/python -m pytest -q
Audit DB:     bootstrapped via controlplane.audit.db.init_db() (idempotent; 05 §3)
Freeze gate:  .venv/bin/python -m eval.validate_dataset            # consistency (06 §2.4)
              .venv/bin/python -m eval.validate_dataset --freeze   # + Checkpoint 1b digest
              The dataset is FROZEN (06 §1). --freeze asserts it is byte-identical to the
              approved state and is what eval/run_all.py calls before computing anything.
              A frozen case is not editable as a fix — that is a new freeze cycle.

Run gateway:  [Phase 2+] .venv/bin/uvicorn controlplane.gateway.app:app --reload
Eval suite:   [Phase 2+] .venv/bin/python -m eval.run_all         → reports/eval_report.md
              [Phase 2+] .venv/bin/python -m eval.bench_latency   → reports/latency_report.md
              [Phase 2+] .venv/bin/python -m eval.fault_injection | .cost_simulation | .pii_leak_scan
Demo:         [Phase 2+] .venv/bin/python -m demo.run_script      (07; nonzero exit on beat failure)
Dashboard:    [Phase 2+] .venv/bin/streamlit run dashboard/app.py (ADR-007)

Secrets:      via .env (gitignored). NEVER commit keys. NEVER print env values.
              Names are normative in 05 §6: UPSTREAM_API_KEY, REVIEW_WEBHOOK_URL, CP_DB_PATH.
              Copy .env.example → .env to start.
```

**Verified toolchain (2026-08-24):** Python 3.14.6 on Arch Linux. Two pins in `pyproject.toml`
are floor-constrained by that interpreter and must not be lowered: `pydantic>=2.13`
(earlier `pydantic-core` has no cp314 wheel and its PyO3 build caps at 3.13) and
`spacy>=3.8.7` (earlier releases declare `Requires-Python <3.13`). `spacy` and
`sentence-transformers` are dependency-resolved on 3.14 but **not yet installed or
imported** — treat their runtime behaviour as unverified until the first detector sprint.

**YAML gotcha (Q-09):** in policy files, `consistency` and `cascade_probe` values must be
**quoted** — PyYAML parses YAML 1.1, where bare `on`/`off` are booleans. `streaming` is a
real boolean and stays unquoted.

---

## 11. Communication style with the human

- Lead with the decision needed, not the narrative of how you got there.
- Deviation reports use the §5.3 format, verbatim.
- End-of-task summaries: what changed / requirements satisfied / stubs remaining / docs touched / deviations open.
- **STOP-point reports must enumerate EVERY open deviation, including ones filed in earlier sessions — not only the ones this task raised.** State the count explicitly, and state it even when it is zero. A report listing three new deviations while two older ones sit unruled reads as "three decisions needed" when it is five, and the human cannot approve work whose blockers they cannot see. The ledger in `docs/08-open-questions.md` is the source to enumerate from; if a slug appears in code or doc prose but not in that table, the table is the thing that is wrong.
- If you notice something wrong outside your current task (doc rot, a latent bug, a risk to the demo), flag it in one line — don't fix it unprompted.

---

*Last updated: [date]. When this file changes, note it in the session summary so the human knows the agent contract shifted.*
