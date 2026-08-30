"""`cost_budget` — the 04 §2 input-stage cost detector (FR-DET-007).

Deterministic, no model, no I/O: **arithmetic over scalars the gateway projects into
`ctx.cost`**. Emits two of the three 04 §1.1 `cost.*` labels:

  * `cost.budget_exceeded`   — window spend has reached the policy ceiling.
  * `cost.request_too_large` — this request's estimated tokens exceed
                               `budget.per_request_max_tokens`.

Both are request-level, so both carry `span=None` — they are in `SPAN_LESS_LABELS`
(05 §3 / 04 §1) because a figure about a whole request indexes no extent of text.

**Why the ledger read is NOT in here, and what that costs.** 04 §2 describes this row as
"ledger lookup; token estimate via tokenizer count x price table", which reads as though
the SELECT belongs to the detector. It cannot: a ledger is keyed by use case, and
`DetectorContext` documents that a detector "stays unable to know which use case it is
serving" (base.py, AGENTS.md §9.1) — a detector holding a use case is one conditional away
from being the policy engine. So the gateway does the keyed lookup and hands this detector
plain numbers. The consequence is stated rather than hidden: **`cost_budget`'s measured
latency is the arithmetic only**, and the ledger read is a lane-level cost paid once per
request in `run_lane` (cached, `ledger.CACHE_TTL_S`). A reader comparing this detector's
p99 against 04 §2's <1 ms is therefore comparing against a narrower quantity than that row
describes. PROVISIONAL — batch review at phase end.

Cost is a signal plus a policy action, never a special-cased subsystem (02 §5): nothing
here knows what a ceiling breach *does*. All three shipped policies map
`cost.budget_exceeded` to `block`; **none maps `cost.request_too_large`**, so it resolves to
`default_action: pass` and is audit-visible only. That asymmetry is the policies' to change,
not this detector's (AGENTS.md §9.1) — 04 §2 gives this row `cost.*` and says nothing about
which of them a use case acts on.
"""

from __future__ import annotations

import time

from controlplane.detectors.base import (
    DetectorContext,
    Plane,
    ScoreKind,
    Signal,
)

NAME = "cost_budget"


class CostBudgetDetector:
    """`cost_budget` — 04 §2 row, `<1 ms`. Stateless; every input arrives on `ctx.cost`."""

    name = NAME

    async def detect(self, ctx: DetectorContext) -> list[Signal]:
        started = time.perf_counter()
        view = ctx.cost
        signals: list[Signal] = []

        # -- ceiling ------------------------------------------------------
        # `>=`, not `>`: at exactly the ceiling the budget is spent, and the next request is
        # the one that would exceed it. A ceiling that admits one more request is not a
        # ceiling, and 07 beat 7b pre-seeds UC-3 *near* its limit precisely so the boundary
        # is what gets exercised.
        #
        # A null ceiling means no policy figure reached us, and a null spend means no ledger
        # could be read (`ledger.spend_in_window` documents why that is not a raise). Either
        # way nothing has been *shown* to be breached, so nothing fires: a detector that
        # inferred a breach from missing evidence would manufacture the block it exists to
        # justify.
        ceiling = view.ceiling_usd
        if ceiling is not None and ceiling > 0.0 and view.spend_usd >= ceiling:
            signals.append(self._signal(
                ctx,
                label="cost.budget_exceeded",
                # Ratio and window, never a dollar figure and never a raw value. A ratio
                # is the quantity the verdict actually turned on, and it stays meaningful
                # in an audit record after the ceiling has been re-tuned.
                evidence=(
                    f"category:budget window=month spend_over_ceiling="
                    f"{min(view.spend_usd / ceiling, 99.0):.2f}x "
                    f"priced_requests={min(view.priced_requests, 999999)}"
                ),
                started=started,
            ))

        # -- per-request size --------------------------------------------
        # `>`, not `>=`: `per_request_max_tokens` is a maximum, so a request landing exactly
        # on it is inside its allowance.
        cap = view.per_request_max_tokens
        if cap is not None and cap > 0 and view.est_request_tokens > cap:
            signals.append(self._signal(
                ctx,
                label="cost.request_too_large",
                # `est_` is load-bearing in the evidence, not a hedge: `est_request_tokens`
                # is a character-derived estimate, not the tokenizer count 04 §2 names — see
                # `pipeline.estimate_tokens`. Recording it as measured would be the exact
                # substitution AGENTS.md §7 forbids.
                evidence=(
                    f"category:request_size est_over_cap="
                    f"{min(view.est_request_tokens / cap, 99.0):.2f}x "
                    f"cap_tokens={min(cap, 999999)} source=char_estimate"
                ),
                started=started,
            ))

        return signals

    @staticmethod
    def _signal(ctx: DetectorContext, *, label: str, evidence: str,
                started: float) -> Signal:
        return Signal(
            detector=NAME,
            planes=[Plane.COST],
            labels=[label],
            score=1.0,  # ADR-012: deterministic emitters report 1.0
            score_kind=ScoreKind.DETECTION,
            span=None,  # request-level (04 §1); both labels are in SPAN_LESS_LABELS
            stage=ctx.stage,
            evidence=evidence,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )


#: Module-level instance. Registration is the caller's, per `tier1_patterns`: `register()`
#: mutates a global, so importing must not have that side effect.
cost_budget = CostBudgetDetector()
