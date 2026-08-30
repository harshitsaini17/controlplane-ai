# ControlPlane.ai — Real-Time AI Oversight Gateway

A reverse proxy that checks every LLM response across performance, cost, and responsibility before deciding whether to pass, edit, block, or escalate it.

[![CI](https://github.com/harshitsaini17/controlplane-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/harshitsaini17/controlplane-ai/actions/workflows/ci.yml) ![Python 3.12 and 3.14](https://img.shields.io/badge/Python-3.12%20%7C%203.14-3776AB) ![README tests passing](https://img.shields.io/badge/README%20tests-passing-brightgreen) ![License not chosen](https://img.shields.io/badge/license-not%20chosen-lightgrey) ![Round 2 · AIC 2026](https://img.shields.io/badge/Round%202%20%C2%B7%20AIC-2026-6B46C1)

Point an OpenAI-compatible client at one URL and select a policy with one header. The same response can be edited for support, blocked for HR, and escalated for finance: the difference is YAML configuration, not application code.

## The 30-second demo

These are the live one-URL integration calls. Live upstream text is nondeterministic; the expected lines are the replay-verified audit verdicts when the scripted demo returns frozen fixture PII-001 as the upstream response.

~~~sh
PROMPT='Confirm the record on file.'

curl -sS http://localhost:8080/v1/chat/completions -H 'Content-Type: application/json' -H 'X-ControlPlane-Use-Case: support_bot' -d "{\"model\":\"small\",\"messages\":[{\"role\":\"user\",\"content\":\"$PROMPT\"}]}"
# expected audit output: verdict=edit; SSN rendered as [REDACTED:ssn]

curl -sS http://localhost:8080/v1/chat/completions -H 'Content-Type: application/json' -H 'X-ControlPlane-Use-Case: hr_copilot' -d "{\"model\":\"small\",\"messages\":[{\"role\":\"user\",\"content\":\"$PROMPT\"}]}"
# expected audit output: verdict=block; personal data withheld under hr_copilot policy

curl -sS http://localhost:8080/v1/chat/completions -H 'Content-Type: application/json' -H 'X-ControlPlane-Use-Case: finance_advisor' -d "{\"model\":\"small\",\"messages\":[{\"role\":\"user\",\"content\":\"$PROMPT\"}]}"
# expected audit output: verdict=escalate; request routed for additional verification
~~~

Same content. Three policies. Zero code difference.

<!-- SCREENSHOT: console verdict board -->
<!-- SCREENSHOT: chat page EDIT verdict -->

## Quick start

~~~sh
python -m venv .venv && .venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu && .venv/bin/pip install -e ".[dev,ml,dashboard]" && .venv/bin/python -m spacy download en_core_web_sm
cp .env.example .env && set -a; . ./.env; set +a          # add provider values; never commit them
.venv/bin/uvicorn --factory controlplane.gateway.app:create_live_app --port 8080
xdg-open http://localhost:8080/console                     # in another terminal
.venv/bin/python -m demo.run_script --replay               # in another terminal
~~~

The live factory requires a measured-class provider and its key. Replay remains the deterministic demo path.

## What it does

~~~text
client → ingress → input lane → dispatch → sentence buffer → detectors
                                                            ↓
HITL ← review queue ← audit ← verdict ← policy engine ←─────┘
                              performance · cost · responsibility
~~~

| Verdict | Effect |
|---|---|
| Pass | Release unchanged content. |
| Edit | Transform eligible spans, then release and audit. |
| Block | Withhold content and return the configured fallback. |
| Escalate | Quarantine content and place it in the human-review queue. |

| Pipeline | Posture | Signature verdict |
|---|---|---|
| support_bot | Redact-first, streaming | EDIT |
| hr_copilot | Privacy-strict, streaming | BLOCK |
| finance_advisor | Regulated, buffered, fail-closed | ESCALATE |

Deep contracts and lifecycle detail: [architecture](docs/02-architecture.md), [policy and detection specification](docs/04-policy-and-detection-spec.md), and [API/data contracts](docs/05-api-and-data-contracts.md).

## Key results

| Metric | Measured | Target | Reproduce with |
|---|---|---|---|
| Engine conformance | 840/840 decisions: 280 cases × 3 policies; perfect detection assumed | NFR-EVAL-002 ≥ 0.90 | .venv/bin/python -m eval.run_all |
| Tier-1 PII precision | 1.000 | Report honestly | .venv/bin/python -m eval.run_all |
| Tier-1 PII recall | 0.8852; 7/7 misses are the documented bare-7-digit exclusion | 0.95 — MISSED, target unmoved | .venv/bin/python -m eval.run_all |
| Injection detector | Precision 1.000 / recall 0.150; blind first contact | No numeric target | .venv/bin/python -m eval.run_all |
| End-to-end policy agreement | 0.851 / 0.851 / 0.825 over 194 of 280 cases; partial coverage and masked detector failures remain | ≥ 0.80 per pipeline — met | .venv/bin/python -m eval.run_all |
| Input-lane hold | P99 27.49 ms, n=200 | P99 < 50 ms — met | .venv/bin/python -m eval.bench_latency |
| Detector P99s | blocklist 0.020 ms; PII 0.133 ms; numeric 0.277 ms; toxicity 23.741 ms; injection 25.348 ms | Tier-1 < 1 ms; numeric < 5 ms; Tier-2 < 25 ms — injection MISSED | .venv/bin/python -m eval.bench_latency --check |
| Fault injection | In-process 5/5 runs at 39/39; separate processes 3/5 clean and two at 38/39 | All 39 invariants per run | .venv/bin/python -m eval.fault_injection --reps 5 |
| Cascade cost curve | +50% at f=0; +25% at f=0.25; break-even f=0.50; loss above it | No point target; f is NOT COMPUTED because the router does not ship | .venv/bin/python -m eval.cost_simulation |

Full claims table, derivations, historical columns, and sources: [engineering notes](docs/09-engineering-notes.md). Generated evidence: [evaluation](reports/eval_report.md), [latency](reports/latency_report.md), [fault injection](reports/fault_injection_report.md), and [cost](reports/cost_report.md).

## Why this is different

- One policy engine converges performance, cost, and responsibility signals into one verdict.
- Uncertainty bands and detector-failure posture are both per-use-case policy, including fail-open and fail-closed behavior.
- Signals are multi-label, so overlapping risks remain independent until convergence.
- The OpenAI-compatible boundary is provider-neutral and supports cloud, local, and air-gapped deployment shapes; local fallback is verified only on the owner host.
- Claims are auditable: the corpus is frozen, first contact is blind, revisions retain v1 columns, and misses remain published.

## What doesn't ship

This register makes prototype limits reviewable rather than presenting them as completed capability.

| ID | Limitation | Status / plan |
|---|---|---|
| SL-1 | PII recall is 0.8852 against 0.95. | Open; target unmoved. Seven known bare-7-digit misses trade recall for precision 1.000. |
| SL-2 | Invalid NANP area codes can still fire under the v1-superset phone behavior. | Open; precision hardening requires a new freeze cycle. |
| SL-3 | Price provenance requires submission-time re-verification. | Downgraded for the two bound Groq IDs; retired-model comparisons remain barred. |
| SL-4 | A genuinely local fallback was previously absent. | Closed on the owner host with llama3.2:3b; no fallback latency/cost claim is made from the development host. |
| SL-5 | Tier-2 latency evidence is low-concurrency. | Open; the published one-thread column shows breaches, and a proper load test is out of scope. |
| SL-6 | fast_consistency is specified but not implemented. | Cut to roadmap; context-free performance checking is the missing case. |
| SL-7 | The grounding band cannot be calibrated: tau_low 0.8365 ≥ tau_high 0.7157. | Open; the 56/78 oracle ceiling points to a detector-model change, not target tuning. |
| SL-8 | Injection attributable P99 is 25.348 ms against 25 ms. | Open measured breach; target unmoved. ORT tuning or serving hardware is roadmap. |
| SL-9 | The OVLP two-plane demo cut works for only 2 of 3 policies. | Cut from the demo path after 10 repetitions; PII-001 remains the deterministic signature beat. |
| SL-10 | The two-tier cascade router is not built. | Budget gating ships, but f has no producer; cost saving remains a curve with break-even at f=0.50. |

Detailed rationale and the beat-by-beat cut record: [engineering notes](docs/09-engineering-notes.md). The authoritative register is [docs/08-open-questions.md](docs/08-open-questions.md).

## Project structure

~~~text
controlplane/  gateway, detector, policy, audit, cost, and telemetry code
policies/      three validated per-use-case YAML policies
eval/          frozen corpus, scoring, latency, fault, cost, and derivation harnesses
demo/          headless scripted demo and replay fixtures
dashboard/     same-origin console pages served by the gateway
reports/       committed, reproducible evidence; not build output
docs/          contracts, ADRs, ledgers, testing guide, and engineering notes
tests/         contract, regression, evaluation, and demo-path gates
~~~

## Development and testing

~~~sh
.venv/bin/python -m pytest -q
.venv/bin/python -m eval.run_all
.venv/bin/python -m eval.bench_latency --check
.venv/bin/python -m eval.fault_injection --reps 5
.venv/bin/python -m eval.validate_dataset --freeze
.venv/bin/python -m eval.check_derivations
~~~

Do not run measurement harnesses beside tests, builds, or another spike. Evidence is citable only from a quiet host with the recorded start/end load inside the documented threshold. See [docs/TESTING.md](docs/TESTING.md). The suite count deliberately lives in [.github/workflows/ci.yml](.github/workflows/ci.yml), not in this README, so M-23 cannot make it stale.

## How it was built

The repository was built spec-first: contracts preceded code, AI agents worked under the binding [AGENTS.md](AGENTS.md), an independent AI review challenged each checkpoint, and humans adjudicated contract changes. The current ledger records **36** ADRs ruled, 32 deviations all ruled and closed, 64 logged minor resolutions, and ten registered SL IDs—SL-4 is closed, leaving nine active limitations.

- Requirements and schemas are the contract; code does not silently redefine them.
- AI implementation agents must stop or log conflicts under the deviation protocol.
- An independent reviewer produced adversarial findings before phase acceptance.
- Human rulings changed contracts through dated ADRs, never by weakening a failing test.

Read the [ADR log](docs/03-decisions.md), [public ledger](docs/08-open-questions.md), and [detailed engineering notes](docs/09-engineering-notes.md): the ledger is public; every ruling is dated.

## Team and submission

Team b24bb1029, Indian Institute of Technology Jodhpur.

| Member | Roll number | Branch |
|---|---|---|
| Priyanshu Pandey, lead | B24BB1029 | Bioengineering, third year |
| Harshit Saini | B24CS1031 | Computer Science, third year |
| Jayant Soni | B24CM1033 | Artificial Intelligence & Data Science, third year |

- [Business proposal PDF](b24bb1029_ControlPlane_Business_Proposal.pdf)
- README PDF: not present in the repository yet.
- Demo video: not present in the repository yet.
- License: not yet chosen; tracked in [docs/08-open-questions.md](docs/08-open-questions.md).
