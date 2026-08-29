"""Detector contract, Signal model, budget enforcement, and the detector registry.

Implements:

  * 04 §1     — the signal model, verbatim field-for-field
  * 04 §1.1   — label taxonomy (imported, not re-declared; see `TAXONOMY` note below)
  * 04 §1.2   — `score_kind` polarity (ADR-012)
  * 04 §2     — the common detector contract: `async detect(ctx) -> list[Signal]`,
                raising `DetectorTimeout` / `DetectorError` rather than hanging,
                stateless per call (conv_tracker excepted)
  * NFR-P-002 — per-detector latency budgets, enforced by `run_with_budget`
  * NFR-SEC-001 — `evidence` never carries a raw matched value

Detectors emit signals; they never decide actions (04 §1). Nothing in this module
imports the policy engine, and no function here reads a policy — the asymmetry is
deliberate and is what keeps FR-POL-002 true.

This module contains no use-case conditionals (AGENTS.md §9.1). The budgets below are
*spec* constants from 04 §2 / NFR-P-002, identical for every use case; per-use-case
detector tuning travels in policy `detector_params`, which the engine passes through
`ctx` rather than baking in here.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

# The taxonomy is deliberately imported rather than restated. 04 §1.1 is one closed
# set; a second copy here would be a silent divergence waiting to happen the first
# time the doc adds a label. `policy.schema` happens to be where it landed first —
# that is a code-layout accident, not a claim that the taxonomy belongs to policy.
from controlplane.policy.schema import TAXONOMY, ParamValue

__all__ = [
    "BUDGETS_MS",
    "ParametricBudget",
    "DetectorContext",
    "ENRICHED_LABELS_KEY",
    "ENRICHED_ONLY_LABELS",
    "Detector",
    "DetectorError",
    "DetectorFailure",
    "DetectorTimeout",
    "Plane",
    "ScoreKind",
    "Signal",
    "Stage",
    "clear_registry",
    "get_detector",
    "budget_ms",
    "ceiling_ms",
    "shutdown_model_executor",
    "model_executor",
    "register",
    "registered_names",
    "run_in_executor",
    "run_with_budget",
]


#: `meta` key holding the labels the enrichment stage appended (04 §2.2, ADR-019).
#: A literal rather than an inline string: 04 §4.3 step 2 partitions a signal's labels on
#: exactly this key, so a typo on either side would silently produce an all-host partition
#: — the failure mode ADR-019 exists to prevent.
ENRICHED_LABELS_KEY = "enriched_labels"

#: Labels that can ONLY reach a signal by enrichment (04 §1.1: "no detector emits it
#: directly"; §2.2 names `entity_enricher` as the sole producer).
#:
#: This is what makes the first direction of the ADR-019 contract checkable at all. The
#: general rule "record every appended label" is unverifiable from a finished signal —
#: nothing distinguishes an appended label from a detector's own. For this set the
#: provenance is known a priori, so its presence without a matching `enriched_labels`
#: entry is a detectable contract violation rather than an unknowable one.
ENRICHED_ONLY_LABELS: frozenset[str] = frozenset({"privacy.person"})


# --------------------------------------------------------------------------
# Enumerations (04 §1)
# --------------------------------------------------------------------------


class Plane(str, Enum):
    """The three risk dimensions (00 §10 glossary, 04 §1)."""

    PERFORMANCE = "performance"
    COST = "cost"
    RESPONSIBILITY = "responsibility"


class ScoreKind(str, Enum):
    """04 §1.2 / ADR-012. Polarity is normative, not stylistic.

    `DETECTION`  — certainty the problem is present; higher = worse. Deterministic
                   emitters use 1.0. Band logic (04 §4.3 step 2) **never** applies.
    `CONFIDENCE` — confidence the content is correct/grounded; higher = better.
                   Band logic applies, and only here.
    """

    DETECTION = "detection"
    CONFIDENCE = "confidence"


class Stage(str, Enum):
    """Where in the request lifecycle the checked text came from (04 §1)."""

    INPUT = "input"
    OUTPUT_SENTENCE = "output_sentence"
    OUTPUT_FULL = "output_full"
    CONVERSATION = "conversation"


# --------------------------------------------------------------------------
# Exceptions (04 §2 contract, resolved by policy `fail_mode` per 04 §5)
# --------------------------------------------------------------------------


class DetectorFailure(Exception):
    """Base for detector faults. 04 §5 turns either subclass into a
    `DetectorFailureRecord` — a distinct type, **never a `Signal`** (ADR-027: a fault is
    an operational event, not a content risk, so it has no place in the closed §1.1
    taxonomy). Its resolution is the policy's `fail_mode` for that detector's class —
    never a decision made here."""

    def __init__(self, detector: str, message: str = "") -> None:
        self.detector = detector
        super().__init__(message or f"{type(self).__name__} in detector {detector!r}")

    @property
    def error_class(self) -> str:
        """Value for `DetectorFailureRecord.error_class` (04 §5, ADR-027).

        A class NAME, never the exception message: a traceback can quote the very text
        under check (NFR-SEC-001).
        """
        return type(self).__name__


class DetectorTimeout(DetectorFailure):
    """Detector exceeded its NFR-P-002 budget. Raised by `run_with_budget`."""


class DetectorError(DetectorFailure):
    """Detector raised. Wraps the original exception without leaking its text into
    a signal — an upstream traceback could contain the very content being checked
    (NFR-SEC-001), so only the class name travels."""


# --------------------------------------------------------------------------
# NFR-P-002 budgets, transcribed from the 04 §2 registry table
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ParametricBudget:
    """A budget whose runner ceiling scales with input length (ADR-034 Part B).

    Only `tier2_injection` carries one. 04 §2 budgets it **per 104-token window** while the
    runner has always handed `wait_for` a flat scalar, and the two cannot both be honoured by
    any implementation — the deviation that produced ADR-034. The resolution is two-tier:

    * the **per-window** budget (`nominal_ms`) is enforced *inside* the detector, window by
      window, and is what NFR-P-002 is scoped to (ADR-032: single-window inputs);
    * the **runner ceiling** is `resolve(units)`, a coarse liveness backstop meaning
      *"materially slower than its own measured envelope"* rather than *"longer than one
      window's budget"*. That distinction is what stops `fail_closed` blocking every long
      input and `fail_open` silently skipping it.

    `per_unit_ms` and `fixed_ms` are **transcribed from ADR-032's measured series**, the same
    way `BUDGETS_MS` is transcribed from the 04 §2 table — not fitted, and not read from
    `reports/` at runtime (production code must not depend on a report file). The
    transcription is not trusted either: a test re-derives both from the artifact and fails
    on drift, because "transcribed" is precisely how a figure loses its derivation.

    **The 1-thread column, deliberately** (ADR-034 M-30). ADR-032 publishes both thread
    settings and SL-5 stands on the gap: 12.38 ms vs 51.05 ms P99 per window at the
    2-window rung, a **4.12x**
    spread. A ceiling built on the optimistic column sits *below* the pessimistic cost, so it
    would fire on **contention** — which for a concurrent gateway is the normal case, not an
    edge. A loose ceiling can only fail to catch a mildly-slow detector; a tight one causes
    false blocks and false skips on live traffic.
    """

    #: The 04 §2 per-unit figure. What NFR-P-002 is compared against, and what every
    #: budget-reading consumer sees via `budget_ms()`.
    nominal_ms: float
    #: Measured cost per unit — ADR-032's 1-thread series, worst per-window P99 across
    #: **both** ladder columns (52.78 ms = 2797.44/53, the 53-window bound rung, sequential).
    #: Worst-across-both because the *bound* batch mode is not either ladder column: the ladder
    #: measures `sequential` and `batched (all in one call)`, while ADR-032 Correction 2 binds
    #: **batch 2**. Grounding on the envelope of both columns is therefore conservative by
    #: construction rather than by luck — batch 2 costs 48.63 ms/window at the 53-window rung
    #: (2577.48/53, 1-thread), *below* this figure, so the ceiling sits above real cost, which
    #: is the direction M-30 requires. ADR-034's own Correction 2 note says the same: this
    #: figure is grounded on the ladder and does not move with the bound batch.
    per_unit_ms: float
    #: Length-independent cost inside the same span — tokenization, which ADR-032's table
    #: excludes (it times `sess.run` only) and a detector cannot. Measured 8.32 ms P99 (1-thread) at the
    #: 4000-token bound; carried as a flat term because it is dwarfed by the per-unit sum.
    fixed_ms: float
    #: Multiplier over the measured envelope. 2.0 per the ruling.
    safety_factor: float = 2.0

    def resolve(self, units: int) -> float:
        """Ceiling for `units` windows, floored at `nominal_ms` for the single-unit case."""
        if units <= 1:
            return self.nominal_ms
        envelope = self.fixed_ms + self.per_unit_ms * units
        return max(self.nominal_ms, envelope * self.safety_factor)


#: Fast-path budget per detector, in milliseconds. Spec constants — NOT tunable per
#: use case. `entity_enricher` is listed for completeness but is NOT a policy
#: `fail_mode` class: 04 §2.2 says enrichment failure skips and logs, never blocks.
#:
#: Values are `float | ParametricBudget` (ADR-034 Part C). Read a comparable number with
#: `budget_ms(name)` and a runner ceiling with `ceiling_ms(name, units)`; indexing this
#: mapping directly for arithmetic is what the union is there to make visible.
BUDGETS_MS: dict[str, float | ParametricBudget] = {
    "tier1_pii": 2.0,
    "tier1_blocklist": 2.0,
    # ADR-034: per-window budget 25 ms (04 §2, NFR-P-002 single-window scope); runner
    # ceiling parametric on window count, grounded on ADR-032's 1-thread series.
    "tier2_injection": ParametricBudget(
        nominal_ms=25.0, per_unit_ms=52.78, fixed_ms=8.32
    ),
    "tier2_toxicity": 25.0,
    "fast_consistency": 60.0,
    "rag_grounding": 30.0,
    "numeric_claims": 5.0,
    "cost_budget": 1.0,
    "loop_guard": 1.0,
    "conv_tracker": 1.0,
    "entity_enricher": 10.0,
}


def budget_ms(name: str) -> float:
    """The comparable NFR-P-002 figure for `name` (ADR-034 Part C).

    For a flat entry this is the entry. For a parametric one it is `nominal_ms` — the 04 §2
    per-unit budget, which is what NFR-P-002 is scoped to and what a per-detector latency
    histogram must be compared against. It is deliberately **not** the runner ceiling: a
    report comparing measured latency against a length-scaled backstop would be comparing a
    detector's cost against a liveness guard and calling the result a budget verdict.
    """
    entry = BUDGETS_MS[name]
    return entry.nominal_ms if isinstance(entry, ParametricBudget) else entry


def ceiling_ms(name: str, units: int = 1) -> float:
    """The ceiling the runner's `wait_for` should receive for `name` at `units` units.

    Equal to `budget_ms(name)` for every flat entry and for the single-unit case, so a caller
    that never sees a multi-unit input cannot tell the difference — which is the point: only
    `tier2_injection` is parametric, and only above one window.
    """
    entry = BUDGETS_MS[name]
    return entry.resolve(units) if isinstance(entry, ParametricBudget) else entry


# --------------------------------------------------------------------------
# Execution vehicle for CPU-bound model detectors (ADR-034 Part A)
# --------------------------------------------------------------------------

#: One process-wide, single-worker pool shared by every model detector.
#:
#: `max_workers=1` is load-bearing rather than a default (ADR-034 Part A). It serializes
#: inference across concurrent requests, which preserves the one-inference-at-a-time
#: conditions **SL-5** measured under: a pool that let four requests infer at once would push
#: per-request parallelism toward ADR-032's 1-thread column, and no figure in this repo
#: describes that. Queue wait is therefore real wait, and it counts inside the ceiling —
#: a budget that excluded queueing would measure the detector rather than the hold
#: NFR-P-001 is about.
#:
#: Shared across detectors, not one pool each, for the same reason: two pools would each
#: believe they had the CPU to themselves.
_MODEL_EXECUTOR: ThreadPoolExecutor | None = None
_EXECUTOR_LOCK = threading.Lock()


def model_executor() -> ThreadPoolExecutor:
    """The shared single-worker inference pool, created on first use.

    Lazy so that importing this module on a host with no model stack costs nothing, and so
    that a process which never runs a model detector never spawns a thread.
    """
    global _MODEL_EXECUTOR
    with _EXECUTOR_LOCK:
        if _MODEL_EXECUTOR is None:
            _MODEL_EXECUTOR = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="cp-model"
            )
        return _MODEL_EXECUTOR


async def run_in_executor(fn: Any, /, *args: Any, detector: str = "") -> Any:
    """Await `fn(*args)` on the shared inference pool. The only sanctioned way to infer.

    Never call a model synchronously from a detector: ONNX Runtime releases the GIL during
    `sess.run`, so an awaited executor future keeps the event loop live for concurrent
    requests, and — the half that matters for budgets — it is what makes `asyncio.wait_for`
    an enforcement point instead of a dead letter. Against inline CPU work the timeout fires
    only once control returns, which is the trap ADR-034 was filed about.

    **A timed-out task is abandoned, not killed.** Python cannot preempt a running thread, so
    cancellation stops this coroutine *waiting* while the worker finishes its current call.
    The request proceeds under policy `fail_mode` immediately and the orphaned result is
    discarded; with one worker, that tail is queue wait for the next request. Each
    abandonment increments `cp_detector_timeout_abandoned_total{detector}` so the condition is
    countable rather than inferred from a latency histogram (ADR-034 Part A).
    """
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(model_executor(), fn, *args)
    except asyncio.CancelledError:
        if detector:
            # Imported here, not at module scope: `base` is the detector contract and must
            # not acquire a telemetry dependency for a counter on an exceptional path.
            from controlplane.telemetry.metrics import REGISTRY_DEFAULT

            REGISTRY_DEFAULT.increment(
                "cp_detector_timeout_abandoned_total", detector=detector
            )
        raise


def shutdown_model_executor() -> None:
    """Drop the shared pool. Test-support and clean-shutdown only."""
    global _MODEL_EXECUTOR
    with _EXECUTOR_LOCK:
        if _MODEL_EXECUTOR is not None:
            _MODEL_EXECUTOR.shutdown(wait=False)
            _MODEL_EXECUTOR = None


# --------------------------------------------------------------------------
# Evidence guard (NFR-SEC-001 / AGENTS.md §9.6 — raw PII anywhere is D7)
# --------------------------------------------------------------------------

# A defence-in-depth tripwire, not a proof. `evidence` is meant to carry a category
# descriptor ("category:ssn pattern"), so anything shaped like an actual value is a
# detector bug. Catching it at construction means the bad value never reaches the
# audit writer, where it would already be too late.
_EMAIL_SHAPE = re.compile(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}")
_LONG_DIGIT_RUN = re.compile(r"\d{7,}")
_GROUPED_DIGITS = re.compile(r"\d(?:[\s\-]?\d){8,}")  # 9+ digits w/ separators: SSN, CC


def _raw_value_shape(text: str) -> str | None:
    """Return the name of the leaked shape found in `text`, or None if it looks safe."""
    if _EMAIL_SHAPE.search(text):
        return "email address"
    if _LONG_DIGIT_RUN.search(text):
        return "7+ consecutive digits"
    if _GROUPED_DIGITS.search(text):
        return "9+ digits with separators (SSN/credit-card shape)"
    return None


# --------------------------------------------------------------------------
# Span
# --------------------------------------------------------------------------


class Span(BaseModel):
    """Character offsets into the checked text (04 §1). Half-open: [start, end).

    Span accuracy is load-bearing, not cosmetic: 04 §6 `redact` replaces exactly this
    extent, so an off-by-one leaves part of a matched PII value in the output.
    """

    model_config = ConfigDict(extra="forbid")

    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _check_order(self) -> "Span":
        if self.start >= self.end:
            raise ValueError(
                f"span start ({self.start}) must be strictly less than end ({self.end}); "
                "an empty span has no extent to redact or soften (04 §6)"
            )
        return self


# --------------------------------------------------------------------------
# Signal (04 §1)
# --------------------------------------------------------------------------


class Signal(BaseModel):
    """The only thing a detector may emit (04 §1). Detectors never decide actions.

    Multi-label by design (FR-DET-005): one signal can carry labels from several
    planes, and the policy engine — not the detector, and not this model — resolves
    them by most-severe mapped action (04 §4.3).
    """

    model_config = ConfigDict(extra="forbid")

    signal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    detector: Annotated[str, Field(min_length=1)]
    planes: Annotated[list[Plane], Field(min_length=1)]
    labels: Annotated[list[str], Field(min_length=1)]
    score: Annotated[float, Field(ge=0.0, le=1.0)]
    score_kind: ScoreKind
    span: Span | None = None
    stage: Stage
    evidence: Annotated[str, Field(min_length=1)]
    latency_ms: Annotated[float, Field(ge=0.0)]
    meta: dict[str, Any] = Field(default_factory=dict)

    # -- validators ------------------------------------------------------

    @model_validator(mode="after")
    def _check_labels_in_taxonomy(self) -> "Signal":
        """04 §1.1 is a closed set, extended only via a doc change."""
        unknown = sorted(set(self.labels) - TAXONOMY)
        if unknown:
            raise ValueError(
                f"labels {unknown} are not in the 04 §1.1 taxonomy, which is a closed "
                "set extended only via a doc change"
            )
        if len(set(self.labels)) != len(self.labels):
            raise ValueError(
                f"duplicate labels in {self.labels}: a repeated label would be counted "
                "twice by the engine's most-severe resolution (04 §4.3 step 1)"
            )
        return self

    @model_validator(mode="after")
    def _check_evidence_carries_no_raw_value(self) -> "Signal":
        """NFR-SEC-001: `evidence` is a category descriptor, never the matched value.

        Raw PII in a signal is D7 (AGENTS.md §5.1) — signals are serialized straight
        into `audit_records.signals_json` (05 §3), so a leak here is a leak at rest.
        """
        shape = _raw_value_shape(self.evidence)
        if shape is not None:
            raise ValueError(
                f"evidence appears to contain a raw value ({shape}): "
                "evidence carries the category and pattern name only, never the matched "
                "text (NFR-SEC-001). Use e.g. 'category:ssn pattern' — signals are "
                "written verbatim into audit_records.signals_json."
            )
        return self

    @model_validator(mode="after")
    def _check_span_stage_coherence(self) -> "Signal":
        """A span indexes the checked text, so request-level stages cannot carry one.

        04 §1 says span is "null if request-level". `conversation` spans nothing in
        particular — its signal is about accumulated state across turns, so an offset
        would have no text to index into.
        """
        if self.span is not None and self.stage is Stage.CONVERSATION:
            raise ValueError(
                f"stage={self.stage.value!r} cannot carry a span: a conversation-level "
                "signal describes accumulated state, not an extent in one checked text "
                "(04 §1)"
            )
        return self

    @model_validator(mode="after")
    def _check_enriched_labels_contract(self) -> "Signal":
        """ADR-019 / 04 §2.2: `meta.enriched_labels` is a contract, not a note.

        04 §4.3 step 2 partitions a signal's labels on this list — a host label is
        band-adjusted, an appended one is never — so the list is not annotation, it
        *selects the branch each label takes*. Both directions are rejected here:

        * an **unrecorded append** would be band-adjusted as though the detector had
          scored it, which is exactly the beat-4b failure ADR-019 rules out (a
          borderline grounding score must not soften `privacy.person` into a pass);
        * a **recorded label absent from `labels`** describes a signal that does not
          exist, and would silently shrink the host partition.

        The check lives in the model, not the engine: a malformed signal then cannot be
        constructed at all, rather than surfacing only on whichever paths happen to run.
        The engine may therefore trust the partition without re-validating it.
        """
        raw = self.meta.get(ENRICHED_LABELS_KEY)
        if raw is None:
            enriched: list[str] = []
        elif isinstance(raw, list) and all(isinstance(item, str) for item in raw):
            enriched = raw
        else:
            raise ValueError(
                f"meta[{ENRICHED_LABELS_KEY!r}] must be a list of label strings, got "
                f"{type(raw).__name__}: §4.3 step 2 partitions `labels` on this value, "
                "so a malformed one would silently yield an all-host partition and "
                "band-adjust an appended label (ADR-019)"
            )

        if len(set(enriched)) != len(enriched):
            raise ValueError(
                f"duplicate entries in meta[{ENRICHED_LABELS_KEY!r}]={enriched}: the "
                "list is a set of appended labels, and a repeat signals a double append"
            )

        # Direction 2 — recorded but not present.
        orphans = sorted(set(enriched) - set(self.labels))
        if orphans:
            raise ValueError(
                f"meta[{ENRICHED_LABELS_KEY!r}] records {orphans} which are absent from "
                f"labels={self.labels}: that describes a signal that does not exist, and "
                "would shrink the host partition of 04 §4.3 step 2 (ADR-019)"
            )

        # Direction 1 — present but unrecorded, checkable only for enricher-only labels.
        unrecorded = sorted((set(self.labels) & ENRICHED_ONLY_LABELS) - set(enriched))
        if unrecorded:
            raise ValueError(
                f"labels {unrecorded} can only be appended by the enrichment stage "
                f"(04 §2.2) but are missing from meta[{ENRICHED_LABELS_KEY!r}]: they "
                "would be treated as host labels and band-adjusted, which is precisely "
                "what ADR-019 forbids. The enricher must record every label it appends."
            )

        # A signal whose every label is enriched is an append with nothing to append to:
        # §2.2 has the enricher add to the *same* signal, which keeps its own labels, and
        # step 2 reads the score as the host's. Not a documented case — rejected so it
        # cannot arrive as one.
        if enriched and set(enriched) == set(self.labels):
            raise ValueError(
                f"every label in {self.labels} is marked enriched, leaving no host "
                "label: enrichment appends to an existing signal (04 §2.2), and the "
                "score 04 §4.3 step 2 reads belongs to that host"
            )

        # The enricher adds `responsibility` alongside `privacy.person` (04 §1.1/§2.2);
        # without it the signal misreports which plane fired to metrics and the dashboard.
        if "privacy.person" in enriched and Plane.RESPONSIBILITY not in self.planes:
            raise ValueError(
                "an enriched `privacy.person` must carry the `responsibility` plane: "
                "04 §2.2 appends label and plane together, and omitting the plane "
                f"misreports which plane fired (planes={[p.value for p in self.planes]})"
            )
        return self


# --------------------------------------------------------------------------
# Detector input (DOC GAP — 04 §2 names `ctx` but never defines it)
# --------------------------------------------------------------------------


class DetectorContext(BaseModel):
    """What a detector receives. 04 §2 writes `async detect(ctx) -> list[Signal]` and
    never says what `ctx` holds, so this is the minimal shape the *documented* detector
    rows actually require — logged as a doc gap for 04 §2 rather than invented freely:

    * `text` + `stage` — every row checks some text at some stage.
    * `context_docs` — `rag_grounding` ("only when request carries `context` docs") and
      `numeric_claims` ("no match in provided context"). Source: `controlplane.context`
      (05 §1.1).
    * `conversation_id` — `loop_guard` and `conv_tracker` are per-conversation (04 §2).
    * `blocklist_extra` / `detector_params` — the two policy fields 04 §2/§3 hand to a
      detector.

    **Policy values arrive as plain data, never as a `Policy` object.** base.py's stated
    asymmetry is that nothing here reads a policy, and it is what keeps FR-POL-002 true:
    a detector that could see the label→action map could start deciding actions. So the
    engine projects the two documented fields into `ctx` and the detector stays unable to
    know which use case it is serving (AGENTS.md §9.1).
    """

    model_config = ConfigDict(extra="forbid")

    text: str = ""
    stage: Stage
    context_docs: list[str] = Field(default_factory=list)
    conversation_id: str | None = None
    blocklist_extra: list[str] = Field(default_factory=list)
    detector_params: dict[str, dict[str, ParamValue]] = Field(default_factory=dict)

    def params_for(self, detector: str) -> dict[str, ParamValue]:
        """Per-detector overrides (04 §3 `detector_params`), empty when unset.

        Values are scalars or lists of scalars (D2 ruling, 2026-08-26). `ParamValue` is
        imported from `policy.schema` rather than redeclared here: this field mirrors
        `Policy.detector_params`, and two definitions of one contract eventually disagree. The
        import direction is the pre-existing one — this module already reads `TAXONOMY` from
        there and nothing in `policy/` imports detectors, so base.py's stated asymmetry (no
        function here reads a policy) is unchanged.

        A caller wanting a number must narrow, which is the point: the widened type makes the
        mismatch a type error at the call site instead of a surprise at runtime.
        """
        return self.detector_params.get(detector, {})


# --------------------------------------------------------------------------
# Detector protocol + registry (04 §2 "registry name")
# --------------------------------------------------------------------------


@runtime_checkable
class Detector(Protocol):
    """04 §2 common contract. Structural, so a detector needs no base class.

    Implementations must be stateless per call (conv_tracker excepted) and must let
    `run_with_budget` own timeout enforcement rather than sleeping on their own.
    """

    name: str

    async def detect(self, ctx: Any) -> list[Signal]: ...


_REGISTRY: dict[str, Detector] = {}


def register(detector: Detector) -> Detector:
    """Register a detector under its `name`. Returns it, so it also works as a decorator.

    A name with no 04 §2 budget is rejected: `run_with_budget` would have nothing to
    enforce, and an unbudgeted detector on the hot path is how NFR-P-001 regressions
    get in unnoticed.
    """
    name = getattr(detector, "name", None)
    if not name:
        raise ValueError("detector must have a non-empty `name` (04 §2 registry name)")
    if name not in BUDGETS_MS:
        raise ValueError(
            f"detector {name!r} has no NFR-P-002 budget in BUDGETS_MS; add it to the "
            "04 §2 registry table first (doc change), then here"
        )
    if name in _REGISTRY:
        raise ValueError(f"detector {name!r} is already registered")
    _REGISTRY[name] = detector
    return detector


def get_detector(name: str) -> Detector:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"no detector registered as {name!r}; registered: {sorted(_REGISTRY)}"
        ) from None


def registered_names() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def clear_registry() -> None:
    """Test-support only: drop all registrations so tests stay isolated."""
    _REGISTRY.clear()


# --------------------------------------------------------------------------
# Budget enforcement (04 §2 "gateway enforces asyncio.wait_for"; NFR-P-002)
# --------------------------------------------------------------------------


async def run_with_budget(
    detector: Detector,
    ctx: Any,
    budget_ms: float | None = None,
) -> list[Signal]:
    """Run one detector under its NFR-P-002 budget.

    Timeout and crash are normalized into `DetectorTimeout` / `DetectorError` so the
    caller has exactly one failure vocabulary to map onto policy `fail_mode` (04 §5).
    This function never consults a policy and never decides an action — it cannot tell
    fail_open from fail_closed, and that separation is the point.

    `latency_ms` is stamped here, on the measured wall-clock of the call, for any
    signal that left it at 0.0. Detectors are free to report their own finer-grained
    timing; this only fills the gap so no signal reaches the audit writer claiming an
    unmeasured 0.0 (AGENTS.md §7).

    Note on cancellation: a detector that blocks the event loop synchronously cannot be
    interrupted by `wait_for` — the timeout fires only once control returns. Enforcing
    budgets against CPU-bound detectors is therefore a property of how the detector is
    written (yield, or run in an executor), not something this wrapper can guarantee.
    """
    name = getattr(detector, "name", type(detector).__name__)
    if budget_ms is None:
        entry = BUDGETS_MS.get(name)
        if entry is None:
            raise ValueError(
                f"no budget for detector {name!r}: pass budget_ms explicitly or add it "
                "to BUDGETS_MS from the 04 §2 table"
            )
        if isinstance(entry, ParametricBudget):
            # Deliberately refused rather than defaulted to `nominal_ms`. A parametric
            # ceiling depends on how much input this request may carry, which only the
            # caller knows (04 §9 puts `per_request_max_tokens` in policy) — and defaulting
            # to the single-window figure would cancel every multi-window scan at 25 ms,
            # which is the exact defect ADR-034 exists to remove. Failing loudly here keeps
            # the two-tier guarantee visible at the call site.
            raise ValueError(
                f"detector {name!r} has a parametric budget (ADR-034): resolve a ceiling "
                "with `ceiling_ms(name, units)` and pass it explicitly. There is no safe "
                "default — `nominal_ms` would cancel every multi-unit input."
            )
        budget_ms = entry

    started = time.perf_counter()
    try:
        signals = await asyncio.wait_for(detector.detect(ctx), timeout=budget_ms / 1000.0)
    except asyncio.TimeoutError as exc:
        raise DetectorTimeout(
            name, f"detector {name!r} exceeded its {budget_ms} ms budget (NFR-P-002)"
        ) from exc
    except DetectorFailure:
        raise  # already in the right vocabulary; don't double-wrap
    except asyncio.CancelledError:
        raise  # cooperative cancellation is not a detector fault
    except Exception as exc:
        # Deliberately not interpolating `exc` — its text may quote the checked
        # content, and this message can reach a log (NFR-SEC-001).
        raise DetectorError(
            name, f"detector {name!r} raised {type(exc).__name__}"
        ) from exc

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if not isinstance(signals, list) or not all(isinstance(s, Signal) for s in signals):
        raise DetectorError(
            name, f"detector {name!r} must return list[Signal] (04 §2 contract)"
        )
    for signal in signals:
        if signal.latency_ms == 0.0:
            signal.latency_ms = elapsed_ms
    return signals
