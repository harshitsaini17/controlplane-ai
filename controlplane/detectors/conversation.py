"""Conversation-scoped detectors: `loop_guard` now, `conv_tracker` still a stub.

`loop_guard` — 04 §2 input row, `<1 ms`, `cost.loop_detected`, "sliding window per
conversation". Deterministic, no model, no I/O: arithmetic over the scalars the gateway
projects into `ctx.cost`, for the reason `detectors/cost.py` states at length (a detector
may not know its use case, so the keyed ledger read is the gateway's).

Two independent firing conditions, per 04 §2's "sliding window" plus the loop shape a rate
alone cannot see:

  * **Rate** — requests for this conversation in the trailing minute reach
    `budget.loop_max_requests_per_min`.
  * **Repetition** — this turn is near-identical to the one before it, normalized by
    `ledger.normalize_turn` (casefold + collapsed whitespace). No ML, no ratio: an
    equality over normalized text, which is what makes it explainable in an audit record.

A slow loop is still a loop, which is why repetition is not gated on the rate: an agent
retrying the same prompt every few seconds never trips a per-minute ceiling and is exactly
the runaway the cost plane exists to stop.

`conv_tracker` (04 §2 conversation-stage row, `conversation.cumulative_risk`, FR-DET-006 /
Q-05) remains
STUB(phase-1-scaffold): not implemented. It is a **different** detector at a different
stage — P2 scope, and absent from `LIVE` — so nothing here should be read as covering it.
"""

from __future__ import annotations

import time

from controlplane.detectors.base import (
    DetectorContext,
    Plane,
    ScoreKind,
    Signal,
)

NAME = "loop_guard"


class LoopGuardDetector:
    """`loop_guard` — 04 §2 row, `<1 ms`. Stateless: the sliding window lives in the ledger.

    Stateless per call is the 04 §2 contract (`conv_tracker` is the one documented
    exception), so the window itself is `CostLedger`'s — this detector only reads the
    counts it is handed. That is also what keeps it correct under the gateway's thread
    pool: two concurrent turns of one conversation would race a detector-local ring.
    """

    name = NAME

    async def detect(self, ctx: DetectorContext) -> list[Signal]:
        started = time.perf_counter()
        view = ctx.cost

        # No conversation id means no conversation to loop: the gateway also drops this
        # detector from `expected_for` in that case, so this is the second of two guards
        # rather than the only one.
        if not ctx.conversation_id:
            return []

        reasons: list[str] = []
        limit = view.loop_max_requests_per_min
        if limit is not None and limit > 0 and view.requests_in_window >= limit:
            reasons.append(f"rate={min(view.requests_in_window, 9999)}/{min(limit, 9999)}per_min")
        if view.repeated_turn:
            # The *fact* of repetition, never the repeated text, and not its hash either:
            # a per-process salted digest is still a value derived from user content, and
            # `evidence` lands in `audit_records.signals_json` (NFR-SEC-001).
            reasons.append("repeat=consecutive_normalized_equal")

        if not reasons:
            return []

        return [Signal(
            detector=NAME,
            planes=[Plane.COST],
            labels=["cost.loop_detected"],
            score=1.0,  # ADR-012: deterministic emitters report 1.0
            score_kind=ScoreKind.DETECTION,
            span=None,  # request-level (04 §1); in SPAN_LESS_LABELS
            stage=ctx.stage,
            evidence="category:loop " + " ".join(reasons),
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )]


#: Module-level instance; registration is the caller's (see `tier1_patterns`).
loop_guard = LoopGuardDetector()
