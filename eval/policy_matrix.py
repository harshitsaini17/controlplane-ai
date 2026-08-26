"""Policy-level 4x4 confusion matrices — the NFR-EVAL-002 artifact (06 §3, §3.3).

Two matrices, and **the distinction between them is normative** (06 §3.3). They answer
different questions and must never be quoted as one number:

* **Engine conformance** — signals SYNTHESIZED from `labels_expected`, fed to
  `policy/engine.py`, tabulated against `action_expected`. It assumes perfect detection on
  purpose, so it measures the engine + policy layer alone. It is **not** a detection-quality
  metric and it is **not** an end-to-end claim.
* **End-to-end (partial)** — REAL detector emissions through the same engine, computed only
  over cases whose expected labels are fully covered by implemented detectors. Everything
  else is reported as skipped, with counts. This grows as detectors land.

Why the conformance matrix is legitimate where 06 §3.1 rule 3 forbade one. Rule 3 bars
deriving `action_taken` from `labels_expected` **and comparing it against a function of the
same ground truth** — that was `derive_action` on both sides of the table, whose diagonal is
guaranteed by construction. What runs here is different in kind: `engine.evaluate()` is an
independent implementation of 04 §4.3, and `action_expected` is pinned to
`validate_dataset.derive_action` by the freeze gate (`check_case`, every case x every
policy). Tabulating one against the other is therefore a **differential test of two
independent implementations of the same spec** — a disagreement is a real finding about one
of them, which is precisely what a construction-guaranteed diagonal could never surface.

That said, the circularity risk does not vanish, it **relocates** — into the synthesis step
below. If `synthesize()` reproduced `derive_action`'s reasoning, the two sides would collapse
back into one. So synthesis is built from the 04 §2 detector registry and the 04 §1.2
`score_kind` polarity — what a detector would *emit* — and never from the action-resolution
rules. It contains no policy lookup, no tau comparison, no severity ordering, and no
`borderline_action`. Those live in the engine, which is the thing under test.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from controlplane.detectors.base import (
    ENRICHED_LABELS_KEY,
    Plane,
    ScoreKind,
    Signal,
    Span,
    Stage,
)
from controlplane.policy.engine import evaluate
from controlplane.policy.schema import Action, Policy

#: Verdict order used for every row/column, most permissive first (04 §4.2).
ACTIONS: tuple[Action, ...] = (Action.PASS, Action.EDIT, Action.ESCALATE, Action.BLOCK)

# --------------------------------------------------------------------------
# The synthesis registry — transcribed from the 04 §2 table, nothing inferred
# --------------------------------------------------------------------------

#: label -> the 04 §2 detector that emits it. `privacy.person` is absent deliberately: it is
#: appended by `entity_enricher` onto another detector's signal and never emitted alone
#: (04 §1.1/§2.2, ADR-019), so it is handled by `_ENRICHED` below rather than as a host.
_EMITTER: dict[str, str] = {
    "pii.ssn": "tier1_pii",
    "pii.credit_card": "tier1_pii",
    "pii.email": "tier1_pii",
    "pii.phone": "tier1_pii",
    "pii.api_key": "tier1_pii",
    "pii.person_data": "tier1_pii",
    "security.blocklist": "tier1_blocklist",
    "security.prompt_injection": "tier2_injection",
    "toxicity.high": "tier2_toxicity",
    "toxicity.moderate": "tier2_toxicity",
    "hallucination.low_confidence": "fast_consistency",
    "hallucination.ungrounded_claim": "rag_grounding",
    "hallucination.unsourced_numeric": "numeric_claims",
    "conversation.cumulative_risk": "conv_tracker",
    "cost.budget_exceeded": "cost_budget",
    "cost.request_too_large": "cost_budget",
    "cost.loop_detected": "loop_guard",
}

#: Enriched labels, and the host they attach to when several are candidates (04 §1.1).
_ENRICHED: frozenset[str] = frozenset({"privacy.person"})

#: 04 §1.2 / ADR-012. Only these two are `confidence`-kind; everything else reports
#: "certainly present" at 1.0, exactly as the shipped deterministic emitters do.
_CONFIDENCE: frozenset[str] = frozenset(
    {"hallucination.ungrounded_claim", "hallucination.low_confidence"}
)

#: Span-less BY DESIGN, so the ADR-015 promotion is reproduced rather than assumed.
#: `fast_consistency` scores a whole response; `conv_tracker` scores a conversation;
#: the cost detectors score a request. None of them has a character extent to point at.
_SPAN_LESS: frozenset[str] = frozenset(
    {
        "hallucination.low_confidence",
        "conversation.cumulative_risk",
        "cost.budget_exceeded",
        "cost.request_too_large",
        "cost.loop_detected",
    }
)

_PLANE: dict[str, Plane] = {
    "pii": Plane.RESPONSIBILITY,
    "privacy": Plane.RESPONSIBILITY,
    "security": Plane.RESPONSIBILITY,
    "toxicity": Plane.RESPONSIBILITY,
    "hallucination": Plane.PERFORMANCE,
    "conversation": Plane.RESPONSIBILITY,
    "cost": Plane.COST,
}


def _stage_for(label: str, kind: str) -> Stage:
    """The stage the 04 §2 registry says this label's detector runs at.

    Driven by the REGISTRY, not by the case's `kind`, and the difference is load-bearing:
    `fast_consistency` is `output_full` and `conv_tracker` is `conversation` regardless of
    which file a case sits in, and those two stages are exactly what make their signals
    span-less — which is what triggers the ADR-015 promotion. Taking the stage from `kind`
    would quietly delete that behaviour from the matrix.
    """
    if label == "hallucination.low_confidence":
        return Stage.OUTPUT_FULL
    if label == "conversation.cumulative_risk":
        return Stage.CONVERSATION
    if kind == "input":
        return Stage.INPUT
    # A conversation-kind case's non-cumulative labels were breached at a turn, which
    # ADR-021 permits at `output_sentence`.
    return Stage.OUTPUT_SENTENCE


@dataclass(frozen=True)
class BandScores:
    """Where a synthesized confidence score sits relative to the shared band."""

    below_tau_low: float
    in_band: float
    above_tau_high: float


def shared_band(policies: Iterable[Policy]) -> BandScores:
    """Scores derived from the taus, requiring all policies to share them.

    The conformance matrix's central claim is that **one identical signal set** produces
    three different verdicts, so the scores may not vary by policy — otherwise the
    difference could be the input rather than the config, and the demonstration would prove
    nothing. All three shipped policies currently ship the same band (0.35/0.70), so this
    holds today.

    It raises rather than silently synthesizing per-policy scores if that ever stops being
    true — a calibration run (06 §3) is entitled to move taus apart, and the honest failure
    there is a loud one, because the alternative is a matrix whose caption has quietly
    become false.
    """
    bands = {(p.thresholds.tau_low, p.thresholds.tau_high) for p in policies}
    if len(bands) != 1:
        raise ValueError(
            f"policies no longer share a band ({sorted(bands)}), so one signal set cannot "
            "sit in the same band on all of them. The matrix caption 'identical signals, "
            "three policies' would be false — synthesize per policy and re-word it, or "
            "report the matrices separately."
        )
    tau_low, tau_high = bands.pop()
    return BandScores(
        below_tau_low=round(tau_low / 2, 4),
        in_band=round((tau_low + tau_high) / 2, 4),
        above_tau_high=round(tau_high + (1.0 - tau_high) / 2, 4),
    )


def synthesize(case: dict[str, Any], band: BandScores) -> list[Signal]:
    """Ground truth -> the signals a perfect detector fleet would have emitted.

    One signal per emitting detector, with enriched labels appended to a host signal rather
    than standing alone (04 §1.1 overlap rule, FR-DET-005) — the OVLP shape. Contains no
    policy lookup and no action reasoning by design; see the module docstring.
    """
    labels = list(case["labels_expected"])
    kind = case["kind"]
    text = case.get("text") or ""
    grounded = case.get("grounded")

    hosts = [label for label in labels if label not in _ENRICHED]
    enriched = [label for label in labels if label in _ENRICHED]

    # Group hosts by emitting detector: one detector emits one signal per checked unit.
    by_detector: dict[str, list[str]] = {}
    for label in hosts:
        by_detector.setdefault(_EMITTER[label], []).append(label)

    # The enriched label rides the host that carries a person claim. `rag_grounding` is
    # preferred when present because that is the documented SC-1 pairing (04 §1.1); the
    # fallback keeps synthesis total rather than dropping a labelled positive on the floor.
    enrich_target: str | None = None
    if enriched:
        for preferred in ("rag_grounding", "numeric_claims"):
            if preferred in by_detector:
                enrich_target = preferred
                break
        if enrich_target is None and by_detector:
            enrich_target = sorted(by_detector)[0]

    signals: list[Signal] = []
    for detector in sorted(by_detector):
        own = sorted(by_detector[detector])
        carried = enriched if detector == enrich_target else []
        all_labels = own + carried

        confidence = any(label in _CONFIDENCE for label in own)
        if confidence:
            # 04 §1.2: higher = MORE confident the content is fine. A case the corpus calls
            # ungrounded is a LOW score, which is why `no` maps below tau_low.
            score = band.in_band if grounded == "borderline" else band.below_tau_low
            score_kind = ScoreKind.CONFIDENCE
        else:
            score, score_kind = 1.0, ScoreKind.DETECTION

        stage = _stage_for(own[0], kind)
        span_less = any(label in _SPAN_LESS for label in own)
        span = None
        if not span_less and text:
            span = Span(start=0, end=min(8, len(text)))

        planes: list[Plane] = []
        for label in all_labels:
            plane = _PLANE[label.split(".", 1)[0]]
            if plane not in planes:
                planes.append(plane)

        meta: dict[str, Any] = {}
        if carried:
            meta[ENRICHED_LABELS_KEY] = list(carried)

        signals.append(
            Signal(
                detector=detector,
                planes=planes,
                labels=all_labels,
                score=score,
                score_kind=score_kind,
                span=span,
                stage=stage,
                # NFR-SEC-001: says where the signal came from, never what was matched.
                evidence="synthesized from labels_expected (06 §3.3 conformance matrix)",
                latency_ms=0.0,
                meta=meta,
            )
        )
    return signals


# --------------------------------------------------------------------------
# Tabulation
# --------------------------------------------------------------------------


@dataclass
class Mismatch:
    case_id: str
    use_case: str
    expected: Action
    taken: Action


@dataclass
class ConfusionMatrix:
    """A 4x4 `action_expected` (row) x `action_taken` (column) table for one use case."""

    use_case: str
    cells: Counter[tuple[Action, Action]] = field(default_factory=Counter)
    mismatches: list[Mismatch] = field(default_factory=list)

    def record(self, case_id: str, expected: Action, taken: Action) -> None:
        self.cells[(expected, taken)] += 1
        if expected is not taken:
            self.mismatches.append(Mismatch(case_id, self.use_case, expected, taken))

    @property
    def total(self) -> int:
        return sum(self.cells.values())

    @property
    def agreements(self) -> int:
        return sum(count for (e, t), count in self.cells.items() if e is t)

    @property
    def agreement_rate(self) -> float | None:
        return None if not self.total else self.agreements / self.total

    @property
    def over_flagging(self) -> tuple[int, int]:
        """(expected pass -> acted, expected-pass total) — 06 §3's over-flagging rate."""
        expected_pass = sum(c for (e, _), c in self.cells.items() if e is Action.PASS)
        acted = sum(
            c for (e, t), c in self.cells.items() if e is Action.PASS and t is not Action.PASS
        )
        return acted, expected_pass

    @property
    def under_flagging(self) -> tuple[int, int]:
        """(expected non-pass -> passed, expected-non-pass total) — the other half.

        Reported beside over-flagging on purpose (06 §3): each is trivially improvable at
        the other's expense, so a single number would hide the dial rather than show it.
        """
        expected_act = sum(c for (e, _), c in self.cells.items() if e is not Action.PASS)
        passed = sum(
            c for (e, t), c in self.cells.items() if e is not Action.PASS and t is Action.PASS
        )
        return passed, expected_act


def conformance_matrices(
    cases: Sequence[dict[str, Any]], policies: dict[str, Policy]
) -> dict[str, ConfusionMatrix]:
    """Synthesized signals -> engine -> verdict, over every case and every policy."""
    band = shared_band(policies.values())
    matrices = {name: ConfusionMatrix(use_case=name) for name in policies}
    for case in cases:
        signals = synthesize(case, band)
        for name, policy in policies.items():
            taken = evaluate(signals, policy).action
            expected = Action(case["action_expected"][name])
            matrices[name].record(case["case_id"], expected, taken)
    return matrices


def covered_cases(
    cases: Sequence[dict[str, Any]], implemented_labels: frozenset[str]
) -> tuple[list[dict[str, Any]], int, int]:
    """Split the corpus into (end-to-end scorable, uncovered, conversation-excluded).

    A case is scorable end-to-end only if **every** label it expects is emittable by a
    detector that exists. A case with one covered and one absent label would score its
    verdict against a ground truth that assumed both fired, so it would measure the missing
    detector rather than the policy layer.

    Conversation-kind cases are excluded for the same ADR-021 reason the per-detector
    section excludes them: the text carries every turn while the labels describe one breach
    unit, so real detectors legitimately find PII the ground truth does not list.
    """
    scorable: list[dict[str, Any]] = []
    conversation = 0
    uncovered = 0
    for case in cases:
        if case["kind"] == "conversation":
            conversation += 1
            continue
        if set(case["labels_expected"]) <= implemented_labels:
            scorable.append(case)
        else:
            uncovered += 1
    return scorable, uncovered, conversation


def end_to_end_matrices(
    cases: Sequence[dict[str, Any]],
    policies: dict[str, Policy],
    emissions: dict[str, list[Signal]],
) -> dict[str, ConfusionMatrix]:
    """Real detector emissions -> engine -> verdict, over the covered cases only.

    `emissions` maps case_id -> the signals the implemented detectors actually produced, so
    this function performs no detection itself: the caller owns the one place detectors run.
    """
    matrices = {name: ConfusionMatrix(use_case=name) for name in policies}
    for case in cases:
        signals = emissions.get(case["case_id"], [])
        for name, policy in policies.items():
            taken = evaluate(signals, policy).action
            expected = Action(case["action_expected"][name])
            matrices[name].record(case["case_id"], expected, taken)
    return matrices


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def render_matrix(matrix: ConfusionMatrix) -> list[str]:
    header = "| expected ↓ / taken → | " + " | ".join(a.value for a in ACTIONS) + " | row total |"
    lines = [
        f"**`{matrix.use_case}`** — {matrix.agreements}/{matrix.total} agree"
        + (f" ({matrix.agreement_rate:.3f})" if matrix.agreement_rate is not None else ""),
        "",
        header,
        "|---|" + "---:|" * (len(ACTIONS) + 1),
    ]
    for expected in ACTIONS:
        row = [matrix.cells.get((expected, taken), 0) for taken in ACTIONS]
        cells = " | ".join(
            f"**{n}**" if expected is ACTIONS[i] and n else str(n) for i, n in enumerate(row)
        )
        lines.append(f"| `{expected.value}` | {cells} | {sum(row)} |")
    col_totals = [
        sum(matrix.cells.get((e, taken), 0) for e in ACTIONS) for taken in ACTIONS
    ]
    lines.append(
        "| **col total** | " + " | ".join(str(n) for n in col_totals) + f" | {matrix.total} |"
    )
    over, over_n = matrix.over_flagging
    under, under_n = matrix.under_flagging
    lines += [
        "",
        f"Over-flagging: **{over}/{over_n}** expected-`pass` cases were acted on"
        + (f" ({over / over_n:.3f})" if over_n else " (n/a)")
        + f" · under-flagging: **{under}/{under_n}** expected-action cases passed"
        + (f" ({under / under_n:.3f})" if under_n else " (n/a)"),
        "",
    ]
    return lines


# --------------------------------------------------------------------------
# Reconciliation — why the end-to-end agreement rate beats the detection rate
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Reconciliation:
    """Detection failures vs verdict failures on the same cases.

    The end-to-end agreement rate is **higher** than the per-detector figures would suggest,
    and the reason is not favourable. Two distinct mechanisms hide a detection failure from
    the verdict, and they are counted separately because they are not the same fact:

    * a **masked miss** — the case carries another label that maps to an action at least as
      severe, so a missed phone number in a sentence that also holds a detected SSN moves
      nothing;
    * a **masked false positive** — the spurious label's action was never more severe than
      the one a genuine label already drove, so most-severe convergence absorbed it.

    Either way the failure is real and counted in the detector section; the matrix cannot
    see it. Reporting only the agreement rate would present that blindness as accuracy
    (AGENTS.md §7).
    """

    failing_cases: int
    exposed: int
    masked_misses: tuple[str, ...]
    masked_false_positives: tuple[str, ...]

    @property
    def masked(self) -> int:
        return len(self.masked_misses) + len(self.masked_false_positives)

    @property
    def masked_case_ids(self) -> tuple[str, ...]:
        return tuple(sorted({*self.masked_misses, *self.masked_false_positives}))


def reconcile(
    miss_case_ids: Iterable[str],
    false_positive_case_ids: Iterable[str],
    matrices: dict[str, ConfusionMatrix],
) -> Reconciliation:
    """Split cases with a detection failure into verdict-exposed vs verdict-masked.

    A case is *exposed* when at least one policy returned the wrong verdict for it. Taking
    the union across policies rather than any single one is the conservative choice: a
    failure visible on one use case is a visible failure.
    """
    mismatched: set[str] = {
        m.case_id for matrix in matrices.values() for m in matrix.mismatches
    }
    misses = set(miss_case_ids)
    false_positives = set(false_positive_case_ids)
    failing = misses | false_positives
    return Reconciliation(
        failing_cases=len(failing),
        exposed=len(failing & mismatched),
        masked_misses=tuple(sorted(misses - mismatched)),
        masked_false_positives=tuple(sorted(false_positives - mismatched - misses)),
    )
