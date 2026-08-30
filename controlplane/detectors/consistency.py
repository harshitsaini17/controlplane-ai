"""`fast_consistency` — the 04 §2 self-consistency row (04 §2.3, ADR-014).

STUB(sl-6-cut-to-roadmap): **not implemented, deliberately.** SL-6 cut this detector to the
roadmap; it stays in `BUDGETS_MS`, `POOL_USERS` and the `output_full` lane as ADR-033's third
lifecycle state — registered, so the audit trail reports it as a gap rather than omitting it.

`rag_grounding` was named here when this file was a scaffold for both performance-plane rows. It
ships in `controlplane/detectors/rag_grounding.py` — its own module, because this file is named
for a mechanism it does not share: consistency resamples the *model* (a second provider call,
ADR-014), where grounding embeds the *request's* context docs and calls no provider at all.
"""
