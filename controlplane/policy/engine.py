"""Policy engine: signal convergence -> exactly one verdict.

Implements 04 §4 (verdict state machine, deterministic per FR-POL-001), 04 §4.3
algorithm incl. ADR-012 band-logic scoping and ADR-017/ADR-019 label partitioning,
04 §4.5 input-stage verdicts, and 04 §5 fail-open/fail-closed (FR-POL-006).

**Contains zero use-case conditionals** (FR-POL-002, AGENTS.md §9.1). Every
per-use-case difference — thresholds, label->action map, borderline action, fail
modes, fallback text — arrives as data on `Policy`. There is no `if use_case ==`
anywhere in this module, and the beat-4 tests are what prove the claim: one signal
set, three policies, three verdicts, no branch in this file.

Determinism (FR-POL-001): the verdict is a pure function of (signals, policy). No
clock, no randomness, no I/O, no mutation of the inputs. Label iteration follows
each signal's own `labels` order and signals are processed in the order given, so
the *explanation* is stable too, not merely the verdict.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from controlplane.detectors.base import (
    ENRICHED_LABELS_KEY,
    ScoreKind,
    Signal,
    Stage,
)
from controlplane.policy.schema import Action, FailMode, Policy

__all__ = [
    "DETECTOR_FAIL_CLASS",
    "DetectorFailureRecord",
    "LabelOutcome",
    "SignalOutcome",
    "FailureOutcome",
    "Verdict",
    "evaluate",
    "most_severe",
]


# --------------------------------------------------------------------------
# Detector -> policy `fail_mode` class (04 §5 "fail_mode for that detector's class")
# --------------------------------------------------------------------------

#: 04 §5 resolves a detector fault "by policy `fail_mode` for that detector's
#: class", and 04 §3 names the four classes (`tier1`, `tier2`, `performance`,
#: `cost`) — but no doc binds a detector NAME to one of them. Transcribed here from
#: the 04 §2 registry table the same way `BUDGETS_MS` was, so the binding lives in
#: exactly one place instead of being re-derived at each call site.
#:
#: Logged as a MINOR resolution in `docs/08` rather than filed as a deviation: the
#: mapping is mechanical for ten of eleven rows (name prefix, or the plane the
#: emitted labels belong to).
#:
#: `conv_tracker` is the one judgment call and is called out as such. It emits
#: `conversation.cumulative_risk`, which belongs to no `tier*`/`cost` class, so it
#: lands in `performance` by elimination. The choice is close to inconsequential
#: today — all three shipped policies set the same mode for `performance` as for
#: the class a reader might otherwise expect — but it is recorded as a decision
#: rather than left to look like a derivation.
#:
#: `entity_enricher` is deliberately ABSENT, not forgotten: 04 §2.2 says enrichment
#: failure skips and logs and never blocks, so it has no `fail_mode` class at all
#: (the same note `BUDGETS_MS` carries). Looking it up is a programming error, and
#: `fail_class_for` raises rather than inventing a mode for it.
DETECTOR_FAIL_CLASS: dict[str, str] = {
    "tier1_pii": "tier1",
    "tier1_blocklist": "tier1",
    "tier2_injection": "tier2",
    "tier2_toxicity": "tier2",
    "fast_consistency": "performance",
    "rag_grounding": "performance",
    "numeric_claims": "performance",
    "cost_budget": "cost",
    "loop_guard": "cost",
    "conv_tracker": "performance",
}


def fail_class_for(detector: str) -> str:
    """The policy `fail_mode` class for one detector name (04 §5)."""
    try:
        return DETECTOR_FAIL_CLASS[detector]
    except KeyError:
        raise ValueError(
            f"no fail_mode class for detector {detector!r}; add it to "
            "DETECTOR_FAIL_CLASS from the 04 §2 registry table. "
            "(`entity_enricher` has none by design — 04 §2.2: enrichment failure "
            "skips and logs, never blocks.)"
        ) from None


# --------------------------------------------------------------------------
# Detector failure input (04 §5)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DetectorFailureRecord:
    """One detector fault awaiting `fail_mode` resolution (04 §5, ADR-027).

    **Deliberately not a `Signal` — and per ADR-027 that is now the contract, not a
    workaround.** A detector fault is an *operational* event, not a content risk: it
    has no span, belongs to no plane, is not emitted by a detector, and is not
    mapped by the label->action table (`fail_mode` governs it, per detector class).
    It therefore does not belong in the closed 04 §1.1 taxonomy, and `Signal` is
    right to refuse it. `signals_json` stays pure Signals; these records travel in
    `detector_failures_json` (05 §3).

    `error_class` is a class NAME, never an exception instance or message: an
    upstream traceback can quote the very content being checked (NFR-SEC-001), which
    is the same reason `run_with_budget` refuses to interpolate the exception.

    `failure_id` and `ts` are minted **at construction by the gateway**, exactly as
    `Signal.signal_id` is, and neither ever reaches the verdict computation — so
    `evaluate()` stays the pure function FR-POL-001 requires. They exist to make an
    ESCALATE with zero content signals self-explaining in the audit (05 §4).

    ADR-027 names `fail_mode_applied` as part of the recorded shape; it is not a
    field here because it is a property of the *resolution*, unknowable at fault
    time. `FailureOutcome.audit_entry()` emits it, so the documented six-key shape
    exists at the audit boundary where the ruling places it. Logged as M-3 in
    `docs/08-open-questions.md`.
    """

    detector: str
    error_class: str
    stage: Stage = Stage.OUTPUT_FULL
    failure_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def fail_class(self) -> str:
        return fail_class_for(self.detector)


# --------------------------------------------------------------------------
# Explanation records — why a verdict is what it is
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LabelOutcome:
    """What 04 §4.3 steps 1-2 did to ONE label of one signal.

    Kept because a verdict without its derivation is unauditable: 05 §4 records the
    contributing signal ids, and a reviewer looking at an ESCALATE needs to see
    which label survived, at what action, and why — particularly when the answer is
    `borderline_action` or an ADR-019 branch rather than the mapped action.
    """

    label: str
    enriched: bool
    mapped: Action
    action: Action | None  # None == dropped by the band; the label is not firing
    rule: str  # short, stable id of the branch taken


@dataclass(frozen=True)
class SignalOutcome:
    """Per-signal result of 04 §4.3 steps 1-2 (+ the step-4 promotion)."""

    signal_id: str
    detector: str
    labels: tuple[LabelOutcome, ...]
    action: Action | None  # None == every label dropped; the signal does not survive
    promoted_spanless: bool = False

    @property
    def surviving_labels(self) -> tuple[LabelOutcome, ...]:
        return tuple(outcome for outcome in self.labels if outcome.action is not None)


@dataclass(frozen=True)
class FailureOutcome:
    """Resolution of one detector fault under 04 §5."""

    detector: str
    error_class: str
    fail_class: str
    fail_mode: FailMode
    action: Action | None  # None == fail_open: proceed, audit only
    failure_id: str = ""
    stage: Stage = Stage.OUTPUT_FULL
    ts: str = ""

    def audit_entry(self) -> dict[str, str]:
        """The `detector_failures_json` element for this fault (05 §3/§4, ADR-027).

        This is where `fail_mode_applied` becomes a recorded fact. It is emitted here
        rather than stored on `DetectorFailureRecord` because the mode applied is a
        property of the resolution, not of the fault: at fault time no policy has been
        consulted yet, so a field there could only ever hold a placeholder.

        Carries no span, no plane, no label and no text — a fault is an operational
        event, and there is nothing about it that could leak checked content
        (NFR-SEC-001). `error_class` is a class name by construction.
        """
        return {
            "failure_id": self.failure_id,
            "detector": self.detector,
            "error_class": self.error_class,
            "stage": self.stage.value,
            "fail_mode_applied": self.fail_mode.value,
            "ts": self.ts,
        }


@dataclass(frozen=True)
class EditPlan:
    """One edit-mapped signal's transform target (04 §6, applied by `actions.py`).

    `whole_sentence` is the 04 §6 soften scope for a span-less
    `stage=output_sentence` signal; `engine` decides scope, `actions` performs the
    transform. Splitting it this way keeps the state machine free of string work and
    keeps the transforms free of policy.
    """

    signal_id: str
    detector: str
    labels: tuple[str, ...]
    span: tuple[int, int] | None
    whole_sentence: bool


@dataclass(frozen=True)
class Verdict:
    """Exactly one verdict, plus everything needed to audit it (FR-POL-001, 05 §4)."""

    action: Action
    use_case: str
    policy_version: int
    signal_outcomes: tuple[SignalOutcome, ...] = ()
    failure_outcomes: tuple[FailureOutcome, ...] = ()
    edits: tuple[EditPlan, ...] = ()

    @property
    def contributing_signal_ids(self) -> tuple[str, ...]:
        """Signals whose surviving action equals the verdict (05 §4 `signals`).

        Only the signals that actually *determined* the verdict, not every signal
        that survived: a PASS-mapped signal alongside a BLOCK is audited, but it did
        not contribute to the decision.
        """
        return tuple(
            outcome.signal_id
            for outcome in self.signal_outcomes
            if outcome.action is self.action
        )

    @property
    def failure_record_ids(self) -> tuple[str, ...]:
        """Failure records whose resolved action equals the verdict (05 §4, ADR-027).

        The companion to `contributing_signal_ids`, and the reason the 04 §4.3 step-5
        stamp names both: an ESCALATE with an empty `contributing_signal_ids` and one
        entry here is a detector outage under `fail_closed`, not an unexplained
        quarantine. A reviewer can tell those apart without re-running anything.
        """
        return tuple(
            outcome.failure_id
            for outcome in self.failure_outcomes
            if outcome.action is self.action
        )


def most_severe(actions: object) -> Action:
    """Most severe action, or PASS over an empty set (04 §4.2/§4.3 step 3)."""
    candidates = [action for action in actions if action is not None]
    if not candidates:
        return Action.PASS
    return max(candidates, key=lambda action: action.severity)


# --------------------------------------------------------------------------
# 04 §4.3 step 2 — band adjustment
# --------------------------------------------------------------------------


def _band_outcome(
    *, enriched: bool, mapped: Action, score: float, policy: Policy
) -> tuple[Action | None, str]:
    """Band adjustment for ONE label of a confidence-kind signal (04 §4.3 step 2).

    Two partitions, per ADR-019, and the enriched branch has exactly two arms with
    no third — `borderline_action` can never reach it. The rationale, worth keeping
    next to the code: a grounding confidence of 0.5 says "this claim is
    half-supported", not "this person is half-identifiable". Interpolating a
    borderline action for an appended label would be invention.

    This is also what keeps demo beat 4b intact on `hr_copilot`, where
    `privacy.person: block` meets `borderline_action: pass` — the one cell where the
    three candidate readings disagree.
    """
    tau_low = policy.thresholds.tau_low
    tau_high = policy.thresholds.tau_high

    if enriched:
        if score >= tau_high:
            # Not a special case for the enriched label: the host claim is
            # supported, so there is no fabrication for a person to be the subject
            # of. The host signal ceasing to exist takes the append with it.
            return None, "adr019.enriched.dropped_with_host"
        return mapped, "adr019.enriched.mapped_unadjusted"

    if score >= tau_high:
        return None, "band.host.above_tau_high_dropped"
    if score >= tau_low:
        return policy.borderline_action, "adr017.host.borderline_action"
    return mapped, "band.host.below_tau_low_mapped"


# --------------------------------------------------------------------------
# 04 §4.3 step 4 — edit extent
# --------------------------------------------------------------------------


def _edit_extent(signal: Signal) -> tuple[bool, tuple[int, int] | None, bool]:
    """Does this edit-mapped signal have an editable extent? (04 §4.3 step 4, ADR-015)

    Returns `(has_extent, span, whole_sentence)`. Eligibility of the LABEL is a
    schema concern (`EDIT_ELIGIBLE_LABELS`); this is the per-signal runtime half
    that a schema provably cannot check, because a schema sees labels and not stages.

    `fast_consistency` is the load-bearing case: it scores a whole response
    (`output_full`) and so can never carry a span, which is why mapping
    `hallucination.low_confidence: edit` yields ESCALATE at every firing rather than
    silently editing nothing.
    """
    if signal.span is not None:
        return True, (signal.span.start, signal.span.end), False
    if signal.stage is Stage.OUTPUT_SENTENCE:
        return True, None, True  # 04 §6 whole-sentence soften scope
    return False, None, False


# --------------------------------------------------------------------------
# The state machine
# --------------------------------------------------------------------------


def evaluate(
    signals: object,
    policy: Policy,
    failures: object = (),
) -> Verdict:
    """Converge signals + detector faults into exactly one verdict (04 §4.3).

    Pure: no clock, no randomness, no I/O, and the inputs are not mutated.
    Identical (signals, policy) always yields an identical verdict AND an identical
    explanation (FR-POL-001).

    Step order follows the doc, with one clarification the doc leaves implicit: §4.3
    lists the verdict at step 3 and the span-less promotion at step 4, but a
    promotion can only raise EDIT to ESCALATE, so the verdict is computed AFTER
    promotions. Computing it before would let a promoted signal report ESCALATE
    while the verdict said EDIT — the two would disagree inside one record. The
    ordering is therefore equivalent to the doc's for every input, and strictly
    more coherent for the promoted ones.
    """
    signal_outcomes: list[SignalOutcome] = []
    edits: list[EditPlan] = []

    for signal in signals:
        enriched_labels = frozenset(signal.meta.get(ENRICHED_LABELS_KEY, ()) or ())
        banded = signal.score_kind is ScoreKind.CONFIDENCE

        label_outcomes: list[LabelOutcome] = []
        for label in signal.labels:
            mapped = policy.action_for(label)
            is_enriched = label in enriched_labels

            if banded:
                action, rule = _band_outcome(
                    enriched=is_enriched,
                    mapped=mapped,
                    score=signal.score,
                    policy=policy,
                )
            else:
                # ADR-012: detection-kind signals BYPASS the band entirely,
                # including the deterministic emitters that report 1.0. Their score
                # is a certainty that the problem is present, so a "borderline"
                # reading of it would invert the polarity.
                action, rule = mapped, "adr012.detection.band_bypassed"

            label_outcomes.append(
                LabelOutcome(
                    label=label,
                    enriched=is_enriched,
                    mapped=mapped,
                    action=action,
                    rule=rule,
                )
            )

        surviving = [outcome.action for outcome in label_outcomes if outcome.action is not None]
        if not surviving:
            # "A signal whose every label was dropped does not survive."
            signal_outcomes.append(
                SignalOutcome(
                    signal_id=signal.signal_id,
                    detector=signal.detector,
                    labels=tuple(label_outcomes),
                    action=None,
                )
            )
            continue

        signal_action = most_severe(surviving)  # multi-label rule (FR-DET-005)
        promoted = False

        if signal_action is Action.EDIT:
            has_extent, span, whole_sentence = _edit_extent(signal)
            if has_extent:
                edit_labels = tuple(
                    outcome.label
                    for outcome in label_outcomes
                    if outcome.action is Action.EDIT
                )
                edits.append(
                    EditPlan(
                        signal_id=signal.signal_id,
                        detector=signal.detector,
                        labels=edit_labels,
                        span=span,
                        whole_sentence=whole_sentence,
                    )
                )
            else:
                # Safe upgrade, not a failure: there is no extent to transform, so
                # releasing the text unchanged would be strictly worse than review.
                signal_action = Action.ESCALATE
                promoted = True

        signal_outcomes.append(
            SignalOutcome(
                signal_id=signal.signal_id,
                detector=signal.detector,
                labels=tuple(label_outcomes),
                action=signal_action,
                promoted_spanless=promoted,
            )
        )

    failure_outcomes = tuple(resolve_failure(record, policy) for record in failures)

    verdict_action = most_severe(
        [outcome.action for outcome in signal_outcomes]
        + [outcome.action for outcome in failure_outcomes]
    )

    # An EDIT plan is only meaningful if EDIT is the verdict. On a BLOCK or ESCALATE
    # the text is never released, so a stale plan would invite a caller to transform
    # and emit something the verdict withheld.
    if verdict_action is not Action.EDIT:
        edits = []

    return Verdict(
        action=verdict_action,
        use_case=policy.use_case,
        policy_version=policy.policy_version,
        signal_outcomes=tuple(signal_outcomes),
        failure_outcomes=failure_outcomes,
        edits=tuple(edits),
    )


def resolve_failure(record: DetectorFailureRecord, policy: Policy) -> FailureOutcome:
    """Resolve one detector fault by policy `fail_mode` (04 §5, FR-POL-006).

    `fail_open`  -> no verdict contribution; proceed without that detector's signals.
                    The fault is still recorded, because a silently dropped detector
                    is indistinguishable from a detector that found nothing.
    `fail_closed`-> ESCALATE. **Never a silent BLOCK** — 04 §5 is explicit, and the
                    reason is that a human has to be able to see *why* the request
                    stopped. A BLOCK here would present a detector outage to the
                    caller as a policy violation.

    Which mode applies is a per-use-case documented decision, never an engineering
    preference: changing a `fail_mode` value is a policy-version change, and
    changing this mechanism is AGENTS.md D7.
    """
    fail_class = record.fail_class()
    mode: FailMode = getattr(policy.fail_mode, fail_class)
    action = Action.ESCALATE if mode is FailMode.FAIL_CLOSED else None
    return FailureOutcome(
        detector=record.detector,
        error_class=record.error_class,
        fail_class=fail_class,
        fail_mode=mode,
        action=action,
        failure_id=record.failure_id,
        stage=record.stage,
        ts=record.ts,
    )
