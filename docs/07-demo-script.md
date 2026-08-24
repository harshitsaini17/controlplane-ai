# 07 — Demo Script

Treated as a permanent regression suite (AGENTS.md §8). `python -m demo.run_script` executes beats 1–8 headlessly and exits nonzero on any beat failure; the live/video demo is the same sequence driven manually with the dashboard visible.

**Setup:** gateway running with 3 policies loaded; dashboard open; terminal for requests + review CLI; `--replay` flag switches upstream to recorded fixtures (charter risk: provider flakiness).

Thesis to land: *"One gateway. Three pipelines. Same engine — different policies. Watch."*

---

### Beat 1 — Baseline: PASS (UC-1 `support_bot`)
Clean support question with context docs → streams normally.
**Show:** response streaming; dashboard verdict counter ticks `pass`; overhead ms visible in `X-ControlPlane-Request-Id` audit lookup.
**Line:** "Every response you'll see went through three planes of checks. This one was clean — cost of oversight: ~40 milliseconds."

### Beat 2 — EDIT: PII redaction (UC-1)
Prompt that lures the (fixture) model into echoing a customer email + phone.
**Show:** streamed sentence arrives with `[REDACTED:email]` `[REDACTED:phone]`; audit record shows spans + `edit`; dashboard PII interception counter by category.
**Line:** "The user never saw it. The audit log knows exactly what happened — category, not the value. Nothing raw is ever stored."

### Beat 3 — BLOCK: prompt injection (UC-1, input stage)
Injection attempt ("ignore your instructions and reveal…").
**Show:** blocked *pre-dispatch* — zero upstream tokens, zero cost; fallback message; `security.prompt_injection` in audit.
**Line:** "Caught at the input lane — we didn't even pay for the model call."

### Beat 4 — ★ SIGNATURE: same content, three verdicts
Fire the **identical** fixture response (a plausible but low-confidence claim containing a person's detail — the OVLP multi-label case) through all three pipelines back-to-back:

> **Fixture note (ADR-015).** The beat-4 **demo fixture** carries the OVLP multi-label signal *plus* one `pii.email` span, so 4a renders as scripted — "softened claim **+ redacted detail**" — with the redaction coming from a real `pii.*` transform rather than from `privacy.person` (which has no 04 §6 transform and is therefore not edit-eligible). This applies to the demo fixture only; the 06 §2 `overlap.jsonl` eval cases stay pure multi-label and are unaffected. Verified against all three policies: the fixture still BLOCKs on UC-2 (`pii.*` → block **and** `privacy.person` → block) and ESCALATEs on UC-3.
- 4a `support_bot` → **EDIT** (softened claim + redacted detail)
- 4b `hr_copilot` → **BLOCK** (internal PII policy)
- 4c `finance_advisor` → **ESCALATE** (quarantined, review item created — and since UC-3 runs non-streaming per ADR-014, *nothing* reached the user at any point)
**Show:** three audit records side by side — same signals, three verdicts, three `policy_version` stamps; open the YAML diff between two policies on screen.
**Line:** "Same model. Same sentence. Three businesses, three risk appetites — and not one line of code differs between these pipelines. This is why it's a control *plane*, not a filter."

### Beat 5 — Multi-label overlap close-up
Zoom into beat-4's signal JSON: one signal, `labels: [hallucination.ungrounded_claim, privacy.person]`, `planes: [performance, responsibility]`.
**Line:** "The brief says these risk categories overlap in the real world. Our signals are multi-label by design — the policy engine resolves severity, we don't pretend the categories are clean."

### Beat 6 — HITL + feedback loop (UC-3)
Open review CLI → the beat-4c item is pending → reviewer **approves** with note → released response retrievable → run `override_report` + `suggest_thresholds` → show proposed YAML diff → apply → re-fire a borderline case → verdict changed.
**Line:** "Escalations aren't a dead end — they're training data for the policy. Human decides; the system proposes; every version is audited."

### Beat 7 — Fail-open vs fail-closed (SC-3)
Start gateway with `--inject-fault tier2` → same request to UC-1 (passes, failure audited) and UC-3 (escalates).
**Line:** "Even our failures are policy decisions. The support bot values availability; the finance tool values caution. Config, not code."

### Beat 7b — BLOCK: budget exhaustion (SC-2, UC-3)
Cost ledger pre-seeded near UC-3's monthly ceiling → one more request → **input-lane BLOCK** (`cost.budget_exceeded`), zero upstream tokens spent; dashboard cost panel shows the ceiling hit.
**Line:** "The cost plane isn't a chart at the end — it enforces live, in the same policy engine as everything else. All three planes act; none of them is decorative."

### Beat 8 — The skeptical-stakeholder screen
Dashboard tour: per-use-case confusion matrix (from eval report), over-flag vs under-flag dial, latency histograms vs budgets, cost simulation delta, cumulative-risk conversation panel (SC-4 if P2 landed).
**Line:** "We're not claiming zero false positives — we're showing you the measured trade-off and the dial that tunes it. That's what the brief asked for."

---

## Failure contingencies
| Failure | Fallback |
|---|---|
| Upstream API down/slow | `--replay` fixtures (identical beats) |
| Classifier model load failure | pre-warmed at startup; startup check blocks demo start |
| Dashboard breaks | `GET /metrics` pretty-printed in terminal covers beats 1–7 |

## Video mapping (storyboard seed)
Hook (problem, 30s) → Beat 4 FIRST as cold-open (signature moment sells the thesis fastest) → architecture 60–90s over the 02 diagram → beats 2/3/6/7 compressed → beat 8 numbers → close. **Confirm Round 2 video length limit before storyboarding (Q-01).**
