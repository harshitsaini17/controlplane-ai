# Round 2 discussion prep — ControlPlane.ai

Answers are written the way you should say them: short claim, one number, one honest caveat.
Every number is in `reports/` or `docs/09`; if a judge asks, name the command.

**Numbers to have cold**

| Figure | Value | Source |
|---|---|---|
| Engine conformance | 840/840 (280 cases × 3 policies) | `python -m eval.run_all` |
| End-to-end agreement | 0.851 / 0.851 / 0.825, over 194 of 280 cases | same |
| Tier-1 PII recall / precision | 0.885 (target 0.95, **missed**) / 1.000 | same |
| Injection blind recall | 0.150, published untuned | same |
| Input-lane hold P99 | 27.49 ms (target 50) | `python -m eval.bench_latency --check` |
| Per-sentence hold P99 | 39.59 ms (target 100) | same |
| `tier1_pii` P99 | 0.133 ms (budget 2 ms) | same |
| `tier2_injection` P99 | 25.348 ms (budget 25, **breach published**) | same |
| Fault injection | 39/39 in-process, 5/5 runs; 3/5 clean across separate processes | `python -m eval.fault_injection` |
| Detectors running | 8 of 11 spec rows | `docs/09` build status |
| Demo | 8 pass / 1 skipped (beat 6, feedback loop) / 0 fail | `python -m demo.run_script` |
| Cost saving | a curve, `saving = 1 − (1/2 + f)`; `f` not computed | `reports/cost_report.md` |
| Record | 36 ADRs, 32 deviations closed, 9 standing limitations | `docs/03`, `docs/08` |

---

## 1. Understanding of the problem statement

**Q: In one sentence, what problem are you solving?**
Enterprises run many AI use cases at once, each with a different risk signature, and today's oversight is fragmented and after the fact. We put one decision point in front of every response, before delivery, and let the decision differ per use case without changing code.

**Q: Why is per-use-case the centre of your design rather than better detection?**
Because the brief's first complexity is that one-size-fits-all checking fails. A customer chatbot should redact and continue; an HR tool should refuse; a regulated advisor should escalate to a human. Same content, three correct answers. Detection quality matters, but the *decision* layer is where the unmet need is.

**Q: The brief says bias, hallucination and privacy overlap. How do you handle that?**
Signals are multi-label. One span can carry `hallucination.ungrounded_claim` and `privacy.person` at once; the engine resolves by most-severe action rather than running two filters in sequence. Honest caveat: the live demo of that overlap case passed on two of three policies and we cut it from the scripted demo (SL-9) rather than ship a beat that fails one time in three.

**Q: What about "no reliable ground truth"?**
We don't claim to solve it. We score confidence three ways: retrieval grounding when context exists, unsourced-numeric-claim detection, and a self-consistency proxy that we specified and then cut (SL-6) because we couldn't calibrate it honestly. The charter's non-goal NG7 says "no claim of solving hallucination"; we detect, score and route under uncertainty.

**Q: Over-flagging versus under-flagging?**
We publish both directions per pipeline as a 4×4 action confusion matrix, and every policy has a `borderline_action` so the ambiguous band resolves to that use case's posture. The tuning dial exists; the calibration procedure currently inverts on our corpus (SL-7), so we show the dial and say it isn't yet turned.

---

## 2. Approach and methodology

**Q: Walk me through a request.**
Header names the use case → policy loads → input lane (PII regex, blocklist, injection classifier, budget gate) → dispatch → tokens buffered to sentence boundaries → per-sentence detectors → policy engine converges to one of PASS / EDIT / BLOCK / ESCALATE → sentence released, transformed, stream cut, or quarantined → one append-only audit record. Non-streaming pipelines buffer the whole response so nothing precedes the verdict.

**Q: Why sentence-level buffering?**
It's the smallest unit you can act on without ruining streaming latency. Guarantee: no part of a flagged sentence is ever released. Trade-off, stated: earlier clean sentences were seen. That's why `finance_advisor` runs non-streaming; the policy chooses the guarantee.

**Q: How did you decide what to build first?**
Charter priorities P0/P1/P2 tied to demo beats. P0 was the gateway, Tier-1 detection, the engine, YAML policies, audit, escalation. Everything is traced: requirement ID → ADR → test → report. 36 ADRs record every decision and reversal.

**Q: How did you evaluate?**
A 280-case labelled synthetic corpus, byte-frozen before first measurement. First contact is blind; misses are filed, not tuned away. When we did revise a detector we publish v1 and v2 columns side by side. Targets can only be re-scoped before a measurement exists, with an anti-laundering note in the ADR.

**Q: You used AI-assisted coding. How did you keep control?**
`AGENTS.md` governs the agent: no use-case conditionals in code, no raw PII anywhere, no number without a command, stop conditions for scope creep. The agent's own errors are in the record: an AI reviewer blocked the build four times; a hidden ~5,000-token injection by a provider was caught by a boot-time accounting canary we then shipped as a feature (FR-GW-006).

---

## 3. Feasibility, scalability, real-world applicability

**Q: Python at tens of thousands of interactions a week — is that realistic?**
Yes for that volume: it's under one request per second averaged. Our measured gateway overhead is 27 ms at the input hold and 40 ms per sentence at P99, against the 20–50 ms band published guidance considers acceptable. What we haven't done is a concurrent load test (SL-5); Tier-2 numbers are single-thread. Compiled gateway is the roadmap (ADR-001), and the architecture — fast path in the request, slow path sampled and async — is the part that transfers.

**Q: Where does this sit in an existing stack?**
Drop-in: change `base_url`, add one header. OpenAI-compatible endpoint, provider-agnostic upstream. No SDK changes per app.

**Q: How does a new use case or a new regulation get onboarded?**
A new YAML file. Thresholds, label→action map, fail mode, geography and risk-appetite metadata, budget. Versioned, diffable, hot-reloadable. Honest caveat: geography is carried as metadata for audit today; no mapping keys on it yet.

**Q: What does it cost to run, and what does it save?**
Deterministic tier is sub-millisecond; Tier-2 classifiers are small CPU models. On savings we publish the arithmetic, not a headline: at a 2× tier price ratio the ceiling is 50 %, break-even at 50 % escalation. The router that would set the escalation fraction isn't built (SL-10), so we don't quote a dollar figure.

**Q: Hyperscalers already ship guardrails. Why you?**
We retracted the claim that they lack per-use-case policy; they have it. What survives: convergence of quality, cost and responsibility into one accountable verdict per response, human-in-the-loop escalation with lineage, provider neutrality including fully local operation, and evidence as a product surface — frozen corpus, published misses, claim-to-command map.

**Q: Who buys it?**
Head of platform (one gateway instead of N × M guardrails), CISO/DPO (audit lineage under EU AI Act and DPDP), FinOps (per-pipeline budget enforcement). Beachhead: Indian BFSI and GCCs serving EU/US parents. Open core; paid tier is the compliance surface.

---

## 4. Challenges and how you addressed them

Pick three and tell them as stories.

**The PII recall miss.** Target 0.95, blind measurement 0.836, one disclosed revision to 0.885. All seven remaining misses are bare seven-digit phone numbers — a documented exclusion that buys precision of exactly 1.000. We kept the target, filed SL-1, and published both columns. Regex over a wider net would have hit 0.95 and destroyed precision.

**`numeric_claims` at 0.267 precision.** It was classifying SSNs and card numbers as statistics. We didn't tune it; we deleted the "long run of digits" rule and wrote a quantity-shape rule plus an identifier pre-filter (ADR-025). 0.857 precision. Old numbers stay in the report.

**The calibration that inverted.** Conformal quantiles gave `tau_low` 0.8365 above `tau_high` 0.7157 on five of five seeds. The harness worked: it told us the grounding signal doesn't separate the classes, and the ceiling is the detector model, not the thresholds. We left the band uncalibrated and visible (SL-7) rather than hand-pick.

**The provider that lied about tokens.** A third-party gateway silently injected ~5,000 hidden prompt tokens per request, corrupting every cost number. We caught it with a boot-time canary comparing reported counts to a local estimate, classed providers as measured vs development, and barred development-class numbers from any report (ADR-018). The canary shipped as a feature.

**The budget gate that manufactured faults.** Wall-clock enforcement under load produced spurious detector faults — 2 in 30 — enough to flip a fail-closed verdict. Rebuilt around detector-attributable CPU time: 0 in 30. That's a differentiator now.

**The signature beat that failed one time in three.** The overlap case passed on `finance_advisor` where it should escalate, ten times in a row, undiagnosed. We moved the demo to a PII case that is 3/3 and logged SL-9. A beat that sometimes works isn't a demo.

**The claim we withdrew.** Our market research falsified our own "hyperscalers don't do this" differentiator three weeks before anyone would have checked. It's gone, dated, in the record.

---

## 5. Explaining and justifying the solution

**Q: Why a reverse proxy and not a library or a post-hoc auditor?**
A library needs every app rewritten and gives no single audit point. Post-hoc can't change what the user saw. A proxy is one integration, one decision point, one evidence trail — and it works with models consumed via API, which the brief says is the real constraint.

**Q: Why exactly four verdicts?**
They are the four things you can do to a response before delivery: release it, change it, replace it, or hold it for a person. Every one maps to a concrete action and a policy line; the brief's "allow / edit / flag for review / block" is the same set.

**Q: Why is failure behaviour a policy setting?**
Because "detector timed out" has no engineering-correct default. A support bot values availability and fails open on Tier-2; a finance tool values caution and fails closed everywhere. We prove this with fault injection: 39 invariants, the verdict follows the policy's `fail_mode`, never a code default.

**Q: Why no automatic threshold updates?**
A system that retunes its own risk appetite from its own review history is one where nobody can say who decided. The tool proposes a YAML diff; a human applies it; the version number is the receipt. Honest caveat: the override report and threshold tool are not implemented yet, so demo beat 6 is currently skipped. The review queue, decisions and lineage are live.

**Q: What's the one thing you'd want us to check?**
Clone the repo, run `python -m eval.run_all`, and compare any number in the deck. The unflattering ones are there too.

**Q: If you had another month?**
In order: the feedback-loop utilities (beat 6), a concurrent load test to retire SL-5, the cascade router so `f` becomes a measurement, then the fairness deep-audit so bias stops being roadmap.

---

## Questions to expect that the tutorial currently answers wrong

Say the correct version aloud even if a judge quotes the tutorial back at you.

| Judge might ask | Tutorial implies | Say instead |
|---|---|---|
| "Show me the feedback loop." | §14: `override_report.py` and `suggest_thresholds.py` produce reports and recompute thresholds | Queue, decisions and lineage are live; the two aggregation utilities are stubs; beat 6 is skipped. |
| "How do you enforce no-PII-in-logs?" | §13: `pii_leak_scan.py` scans output, "enforced rather than promised" | Enforced by the audit schema, detector tests and review; the grep harness `pii_leak_scan` is not yet written. |
| "Do you handle multi-turn risk?" | §8 lists `conv_tracker` among detectors | Specified, not implemented (P2); cumulative-risk escalation is not demonstrable. |
| "Is there a dashboard?" | §15 installs a `dashboard` extra; §13 says the dashboard filters records | Three console pages served by the gateway replace the Streamlit dashboard plan. |
