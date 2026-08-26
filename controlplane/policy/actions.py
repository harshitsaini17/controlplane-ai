"""Action application: PASS / EDIT / BLOCK / ESCALATE.

Implements 04 §6 EDIT transformations (`redact`, `soften` — deterministic templates,
never LLM-generated), the 04 §4.4 release/terminate behaviours, and 04 §4.5 /
ADR-020 input-stage semantics. Satisfies FR-POL-003/004/005.

Division of labour with `engine.py`, kept strict on purpose: the engine decides
*what* and *where* (verdict + `EditPlan` extents) and reads policy; this module
performs string transforms and reads **no** policy except the two message templates
it is handed. Neither module contains a use-case conditional (FR-POL-002).
"""

from __future__ import annotations

from dataclasses import dataclass

from controlplane.detectors.base import DetectorContext, Stage
from controlplane.detectors.tier1_patterns import tier1_pii
from controlplane.policy.engine import EditPlan, Verdict
from controlplane.policy.schema import Action, Policy

__all__ = [
    "REDACTION_TEMPLATE",
    "SOFTEN_PREFIX",
    "UNVERIFIED_MARKER",
    "AppliedEdit",
    "EditResult",
    "Outcome",
    "category_of",
    "redact_spans",
    "soften",
    "apply_edits",
    "apply_verdict",
    "apply_input_verdict",
]


# --------------------------------------------------------------------------
# Templates (04 §6 — deterministic and testable, never model-generated)
# --------------------------------------------------------------------------

#: 04 §6 writes `[REDACTED:{category}]`; 07 beat 4 renders `[REDACTED:email]`.
#: `category` is therefore the BARE category, matching the `"category:ssn pattern"`
#: convention `tier1_pii` already uses for `evidence` — not the full `pii.email`
#: label. The audit record keeps the full label (05 §4 `input_redactions.category`:
#: `"pii.ssn"`), so `AppliedEdit` carries both and neither doc has to bend.
REDACTION_TEMPLATE = "[REDACTED:{category}]"

#: The 04 §6 hedge, quoted from the doc: "Based on available information, … may …".
#: Only the prefix and the marker are mechanizable — rewriting the interior of a
#: sentence into a "may" form is exactly the LLM rewrite 04 §8 excludes from v1.
SOFTEN_PREFIX = "Based on available information, "
UNVERIFIED_MARKER = "⚠ unverified"


def category_of(label: str) -> str:
    """`pii.email` -> `email` (04 §6 / 07 beat 4 rendering)."""
    return label.split(".", 1)[1] if "." in label else label


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AppliedEdit:
    """One transform actually applied — the audit trail for 05 §3 `actions_json`.

    Carries the stage, the span and the category and **never the removed value**
    (NFR-SEC-001, and 05 §3 says so explicitly for the input case). That is enough
    to prove what was removed without storing what it was.
    """

    transform: str  # "redact" | "soften"
    label: str  # full taxonomy label, e.g. "pii.email"  (05 §4)
    category: str  # bare category, e.g. "email"          (04 §6 / 07 rendering)
    stage: Stage
    span: tuple[int, int] | None
    whole_sentence: bool = False


@dataclass(frozen=True)
class EditResult:
    """Result of applying every `EditPlan` for one unit of text."""

    text: str
    applied: tuple[AppliedEdit, ...]

    @property
    def changed(self) -> bool:
        return bool(self.applied)


@dataclass
class Outcome:
    """What the gateway should do with one unit, after the verdict is applied.

    `text` is `None` exactly when nothing may be released — BLOCK and ESCALATE — so
    a caller cannot accidentally emit withheld content by reading a field that
    happens to hold the original.
    """

    action: Action
    text: str | None
    user_message: str | None = None
    quarantined_text: str | None = None
    applied: tuple[AppliedEdit, ...] = ()
    promoted_to_escalate: bool = False
    rescan_findings: tuple[str, ...] = ()
    dispatch: bool = True  # input stage only: 04 §4.5 short-circuit
    notes: tuple[str, ...] = ()


# --------------------------------------------------------------------------
# 04 §6 transforms
# --------------------------------------------------------------------------


def redact_spans(text: str, spans: object) -> str:
    """Replace each span with `[REDACTED:{category}]`, **right-to-left**.

    Right-to-left is not a style choice: replacing left-to-right shifts every later
    offset by the length delta between the match and its marker, so the second span
    of a multi-PII sentence would be cut at the wrong place. Descending order keeps
    every not-yet-applied offset valid, which is why 04 §6 specifies it.

    Overlapping spans are the caller's problem — `tier1_pii` resolves overlaps
    before emitting (`_resolve_overlaps`), so by construction they do not arrive
    here.
    """
    out = text
    for start, end, category in sorted(spans, key=lambda item: item[0], reverse=True):
        out = out[:start] + REDACTION_TEMPLATE.format(category=category) + out[end:]
    return out


def soften(text: str, span: tuple[int, int] | None = None) -> str:
    """Hedge an assertive claim and mark it unverified (04 §6 `soften`).

    Deterministic and idempotent-guarded: applying it twice does not stack a second
    prefix or a second marker, because an EDIT verdict can legitimately carry two
    soften-mapped signals over the same sentence (a multi-label host signal, say),
    and a doubled hedge would read as a bug to a judge.

    Scope: the span when one is given, otherwise the whole sentence — the two cases
    04 §6 names. Whole-sentence scope is what makes `stage=output_sentence` span-less
    softening legal, per ADR-015.
    """
    target = text if span is None else text[span[0] : span[1]]

    hedged = target if target.startswith(SOFTEN_PREFIX) else SOFTEN_PREFIX + _lower_first(target)
    if UNVERIFIED_MARKER not in hedged:
        hedged = f"{hedged.rstrip()} {UNVERIFIED_MARKER}"

    if span is None:
        return hedged
    return text[: span[0]] + hedged + text[span[1] :]


def _lower_first(text: str) -> str:
    """Lower-case a leading capital so the hedge reads as one sentence.

    Only when the first word is not an acronym or proper-noun-shaped token: `"NASA
    reported"` must not become `"nASA reported"`. Cheap heuristic, deliberately —
    a real caser is not what 04 §6 asks for.
    """
    if not text or not text[0].isupper():
        return text
    first = text.split(" ", 1)[0].rstrip(".,;:")
    if len(first) > 1 and any(char.isupper() for char in first[1:]):
        return text  # ACRONYM or CamelCase — leave it alone
    return text[0].lower() + text[1:]


# --------------------------------------------------------------------------
# Plan application
# --------------------------------------------------------------------------


def apply_edits(text: str, edits: object, *, stage: Stage) -> EditResult:
    """Apply every `EditPlan` to one unit of text (04 §6, driven by 04 §4.3 step 4).

    Redactions are collected and applied together, right-to-left, so multi-span
    safety holds across *signals* and not merely within one. Softens are applied
    after, because a soften can rewrite a whole sentence and would otherwise
    invalidate the redaction offsets it spans.
    """
    redactions: list[tuple[int, int, str]] = []
    applied: list[AppliedEdit] = []
    softens: list[EditPlan] = []

    for plan in edits:
        for label in plan.labels:
            if label.startswith("pii."):
                if plan.span is None:
                    # Unreachable via the engine: 04 §6 requires a span for
                    # `redact`, and a span-less pii edit is promoted to ESCALATE at
                    # 04 §4.3 step 4 before it can reach here. Skipped rather than
                    # guessed, so a future caller cannot silently redact nothing.
                    continue
                redactions.append((plan.span[0], plan.span[1], category_of(label)))
                applied.append(
                    AppliedEdit(
                        transform="redact",
                        label=label,
                        category=category_of(label),
                        stage=stage,
                        span=plan.span,
                    )
                )
            elif label.startswith("hallucination."):
                softens.append(plan)
                applied.append(
                    AppliedEdit(
                        transform="soften",
                        label=label,
                        category=category_of(label),
                        stage=stage,
                        span=plan.span,
                        whole_sentence=plan.whole_sentence,
                    )
                )

    out = redact_spans(text, redactions)

    # Whole-sentence softens are applied once even if several signals request one:
    # the transform is idempotent-guarded, but re-running it per signal would also
    # re-scan the same text repeatedly for no gain.
    if any(plan.whole_sentence or plan.span is None for plan in softens):
        out = soften(out)
    else:
        for plan in sorted(softens, key=lambda p: p.span[0], reverse=True):
            out = soften(out, plan.span)

    return EditResult(text=out, applied=tuple(applied))


# --------------------------------------------------------------------------
# Post-edit guard (04 §6 last line, 04 §4.5)
# --------------------------------------------------------------------------


async def rescan_pii(text: str, *, stage: Stage) -> tuple[str, ...]:
    """Re-run `tier1_pii` once over edited text; return the labels still found.

    04 §6: "Edited text re-runs `tier1_pii` once (guard against transform errors); a
    second failure promotes to ESCALATE." Once, not until clean — an edit loop could
    mask a broken transform by grinding the text down, and the promotion is the
    documented response to a transform that did not work.

    Empty tuple means the guard passed.
    """
    signals = await tier1_pii.detect(DetectorContext(text=text, stage=stage))
    return tuple(sorted({label for signal in signals for label in signal.labels}))


# --------------------------------------------------------------------------
# Verdict application
# --------------------------------------------------------------------------


async def apply_verdict(text: str, verdict: Verdict, policy: Policy) -> Outcome:
    """Apply an OUTPUT-stage verdict to one unit of text (04 §4.4, FR-POL-003/004/005).

    PASS     -> release unchanged.
    EDIT     -> transform, then the 04 §6 re-scan; a second failure promotes to
                ESCALATE and the text is **not** released.
    BLOCK    -> nothing released; `messages.block_fallback` goes to the caller.
    ESCALATE -> nothing released; the unit is quarantined and the caller gets
                `messages.escalate_user_notice`.
    """
    if verdict.action is Action.PASS:
        return Outcome(action=Action.PASS, text=text)

    if verdict.action is Action.BLOCK:
        # 04 §4.4: stream terminated, fallback sent, remaining tokens drained and
        # discarded — still audited, which is the engine's `signal_outcomes`.
        return Outcome(
            action=Action.BLOCK,
            text=None,
            user_message=policy.messages.block_fallback,
        )

    if verdict.action is Action.ESCALATE:
        return Outcome(
            action=Action.ESCALATE,
            text=None,
            user_message=policy.messages.escalate_user_notice,
            quarantined_text=text,
        )

    result = apply_edits(text, verdict.edits, stage=Stage.OUTPUT_SENTENCE)
    findings = await rescan_pii(result.text, stage=Stage.OUTPUT_SENTENCE)
    if findings:
        # The transform ran and PII survived it. Promotion, not a retry.
        return Outcome(
            action=Action.ESCALATE,
            text=None,
            user_message=policy.messages.escalate_user_notice,
            quarantined_text=text,
            applied=result.applied,
            promoted_to_escalate=True,
            rescan_findings=findings,
            notes=("04 §6 re-scan found PII in edited text; promoted to ESCALATE",),
        )

    return Outcome(action=Action.EDIT, text=result.text, applied=result.applied)


async def apply_input_verdict(prompt: str, verdict: Verdict, policy: Policy) -> Outcome:
    """Apply an INPUT-stage verdict before dispatch (04 §4.5, ADR-020).

    BLOCK / ESCALATE **short-circuit**: no upstream call, so no cost. `dispatch` is
    False and `text` is None — the two facts a caller needs, neither inferred.

    EDIT is pre-dispatch redaction: spans are replaced in the prompt *before* the
    upstream call, so the provider never receives the raw value. The same 04 §6
    re-scan guard applies, and here a second failure means the request is **never
    dispatched at all** rather than merely withheld from the user.

    Simpler than the output case by construction: the input is fully buffered before
    dispatch, so there is no partial release, no recall problem and no latency race.
    """
    if verdict.action is Action.PASS:
        return Outcome(action=Action.PASS, text=prompt, dispatch=True)

    if verdict.action is Action.BLOCK:
        return Outcome(
            action=Action.BLOCK,
            text=None,
            user_message=policy.messages.block_fallback,
            dispatch=False,
            notes=("04 §4.5 input short-circuit: no upstream call, no cost",),
        )

    if verdict.action is Action.ESCALATE:
        return Outcome(
            action=Action.ESCALATE,
            text=None,
            user_message=policy.messages.escalate_user_notice,
            quarantined_text=prompt,
            dispatch=False,
            notes=("04 §4.5 input short-circuit: no upstream call, no cost",),
        )

    result = apply_edits(prompt, verdict.edits, stage=Stage.INPUT)
    findings = await rescan_pii(result.text, stage=Stage.INPUT)
    if findings:
        return Outcome(
            action=Action.ESCALATE,
            text=None,
            user_message=policy.messages.escalate_user_notice,
            quarantined_text=prompt,
            applied=result.applied,
            promoted_to_escalate=True,
            rescan_findings=findings,
            dispatch=False,
            notes=(
                "04 §4.5 re-scan found PII in redacted prompt; promoted to ESCALATE "
                "and NOT dispatched",
            ),
        )

    return Outcome(action=Action.EDIT, text=result.text, applied=result.applied, dispatch=True)
