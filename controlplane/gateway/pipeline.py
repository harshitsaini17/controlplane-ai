"""Lane orchestration — the fast path from 02 §4, over the detectors that exist.

This module is the *spine*: it runs detectors under their budgets, hands the signals to
the policy engine, applies the verdict, and records what happened. It holds **no policy**
of its own. Every threshold, action mapping and fail-mode comes from the `Policy` object
bound at ingress (AGENTS.md §9.1), and the only per-use-case branching here reads
documented policy *fields* — `consistency`, `streaming`, whether the request carried
context docs — never a use-case name.

**Lane composition is derived from the 04 §2 registry table, not hand-listed per pipeline.**
`LANES` transcribes that table's Stage column; `expected_for` narrows it by the conditions
04 §2 states ("only when request carries `context` docs", ADR-014's consistency modes). A
detector with no implementation this phase is therefore *expected and absent* rather than
forgotten, which is exactly the distinction `detectors_json` records (M-10).

Two things this module deliberately does not do:

* **It never awaits a slow-lane check.** 02 §4 and AGENTS.md §9.4 put semantic entropy,
  fairness and LLM-judge on the async lane; nothing here can reach them, because the only
  detectors it can run are the ones in `LANES`, and that table carries fast-path rows only.
* **It never recalls released text.** ADR-002. Once `stream_units` has yielded a segment,
  the caller has it; a later BLOCK terminates the stream and sends the fallback, but it
  cannot unsay what went out. That asymmetry is the documented cost of streaming
  interception (02 §4 "Key property"), and it is why the input lane fully buffers.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from controlplane.audit.records import serialize_detectors
from controlplane.detectors import numeric_claims as numeric_claims_mod
from controlplane.detectors import tier1_patterns
from controlplane.detectors.base import (
    BUDGETS_MS,
    Detector,
    DetectorContext,
    DetectorFailure,
    Signal,
    Stage,
    run_with_budget,
)
from controlplane.gateway.ingress import ResolvedRequest
from controlplane.policy.actions import Outcome, apply_input_verdict, apply_verdict, category_of
from controlplane.policy.engine import (
    DetectorFailureRecord,
    Verdict,
    evaluate,
)
from controlplane.policy.schema import Policy
from controlplane.telemetry import spans
from controlplane.telemetry.metrics import REGISTRY_DEFAULT, MetricsRegistry

#: The live detector instances, keyed by their 04 §2 registry name. Module-level
#: singletons, which is how `detectors/` already exposes them — `register()` exists for
#: the eval harness's benefit and the production path binds directly, so a registry that
#: happens to be empty at runtime cannot silently drop a lane.
LIVE: dict[str, Detector] = {
    "tier1_pii": tier1_patterns.tier1_pii,
    "tier1_blocklist": tier1_patterns.tier1_blocklist,
    "numeric_claims": numeric_claims_mod.numeric_claims,
}

#: 04 §2 Stage column, transcribed. Order within a stage is the table's order, so a
#: reader can diff this against the doc line by line.
LANES: dict[Stage, tuple[str, ...]] = {
    Stage.INPUT: (
        "tier1_pii",
        "tier1_blocklist",
        "tier2_injection",
        "cost_budget",
        "loop_guard",
    ),
    Stage.OUTPUT_SENTENCE: (
        "tier1_pii",
        "tier1_blocklist",
        "tier2_toxicity",
        "rag_grounding",
        "numeric_claims",
    ),
    Stage.OUTPUT_FULL: ("fast_consistency",),
    Stage.CONVERSATION: ("conv_tracker",),
}

#: `latency_json` key for each detector, from the 05 §5 closed vocabulary. Absent means
#: *no span key*, which is the M-8 ruling rather than an omission: 05 §5 is authoritative
#: on the vocabulary and has no entry for `numeric_claims`, whose per-detector timing goes
#: to `cp_detector_latency_ms{detector}` — the channel 05 §5 already defines for it.
SPAN_OF: dict[tuple[Stage, str], str] = {
    (Stage.INPUT, "tier1_pii"): spans.INPUT_TIER1,
    (Stage.INPUT, "tier1_blocklist"): spans.INPUT_TIER1,
    (Stage.INPUT, "tier2_injection"): spans.INPUT_TIER2,
    (Stage.INPUT, "cost_budget"): spans.COST_BUDGET,
    (Stage.INPUT, "loop_guard"): spans.COST_BUDGET,
    (Stage.OUTPUT_SENTENCE, "tier1_pii"): spans.OUT_TIER1,
    (Stage.OUTPUT_SENTENCE, "tier1_blocklist"): spans.OUT_TIER1,
    (Stage.OUTPUT_SENTENCE, "tier2_toxicity"): spans.OUT_TIER2,
    (Stage.OUTPUT_SENTENCE, "rag_grounding"): spans.OUT_GROUNDING,
    (Stage.OUTPUT_FULL, "fast_consistency"): spans.OUT_CONSISTENCY,
}

#: 05 §4 `not_run[].reason`, re-exported so a caller need not import two modules to build
#: one coverage entry. Single source stays `audit.records` (the M-9 lesson).
NOT_IMPLEMENTED = "not_implemented"


def lane_members(stage: Stage) -> tuple[str, ...]:
    """The registry rows that apply to a unit checked at `stage`.

    For `input`, `output_sentence` and `conversation` this is 04 §2's Stage column
    directly. **`output_full` is the composed one, and it is a reading worth stating**
    (M-11): 04 §2 declares `fast_consistency` alone at `output_full`, but 02 §4's
    non-streaming path says "buffer fully, run **all** checks incl. consistency, single
    verdict", and ADR-014 makes that the whole of UC-3. Returning only `fast_consistency`
    here would mean a non-streaming pipeline never ran `tier1_pii` — the one reading no
    doc supports, and one that would silently drop PII interception on the highest-stakes
    use case.

    So a full-response unit runs the output-sentence rows **plus** `fast_consistency`. The
    per-detector `stage` in 04 §2 says which *text* a detector is written to consume, not
    which delivery mode may use it; `tier1_pii` scanning a whole response is the same
    operation over a longer string, which is exactly what `review.mask_pii` already does
    at `OUTPUT_FULL`.
    """
    if stage is Stage.OUTPUT_FULL:
        return LANES[Stage.OUTPUT_SENTENCE] + LANES[Stage.OUTPUT_FULL]
    return LANES.get(stage, ())


def expected_for(stage: Stage, request: ResolvedRequest) -> tuple[str, ...]:
    """Detectors this request's configuration asks for at `stage` (04 §2 conditions).

    This is the denominator of coverage. A detector excluded here was never expected, so
    it is neither `ran` nor `not_run` — 05 §4's rule that "a detector switched off by
    policy is not listed", which keeps `not_run` answering one question instead of two.

    The three narrowings are all quoted from the docs rather than chosen:

    * `rag_grounding` — 04 §2, "only when request carries `context` docs".
    * `fast_consistency` — ADR-014 via `policy.consistency`; `off` means the check is not
      part of this pipeline at all, and 04 §2.3 says `rag_grounding` covers the plane
      instead.
    * `conv_tracker` — 04 §2 is per-conversation, so no conversation id means no lane.
    """
    policy = request.policy
    out: list[str] = []
    for name in lane_members(stage):
        if name == "rag_grounding" and not request.context_docs:
            continue
        if name == "fast_consistency" and str(policy.consistency) == "off":
            continue
        if name == "conv_tracker" and not request.conversation_id:
            continue
        out.append(name)
    return tuple(out)


@dataclass
class Coverage:
    """Accumulates the M-10 coverage claim across every unit of one request.

    `ran` is a **union across units** (05 §4): one request is one audit record
    (FR-AUD-001) but a streaming response is many sentences, so a per-unit list would be
    a list of lists answering a question nobody asks. The question coverage answers is
    "was this check ever applied to this response".
    """

    ran: set[str] = field(default_factory=set)
    missing: dict[str, str] = field(default_factory=dict)

    def note_ran(self, detector: str) -> None:
        self.ran.add(detector)
        # A detector that ran even once is not a gap, whatever an earlier unit recorded:
        # `not_run` must never contradict `ran`, which the audit writer refuses outright.
        self.missing.pop(detector, None)

    def note_missing(self, detector: str, reason: str = NOT_IMPLEMENTED) -> None:
        if detector not in self.ran:
            self.missing[detector] = reason

    def serialize(self) -> str:
        """The `detectors_json` value. Sorted, so two identical requests audit identically."""
        return serialize_detectors(
            ran=sorted(self.ran),
            not_run=sorted((d, r) for d, r in self.missing.items()),
        )


@dataclass
class LaneResult:
    """What one stage produced for one unit of text."""

    signals: tuple[Signal, ...] = ()
    failures: tuple[DetectorFailureRecord, ...] = ()
    #: `latency_json` span key -> ms, summed across the detectors sharing that span.
    latency: dict[str, float] = field(default_factory=dict)


async def run_lane(
    stage: Stage,
    text: str,
    request: ResolvedRequest,
    coverage: Coverage,
    *,
    metrics: MetricsRegistry | None = None,
) -> LaneResult:
    """Run every detector this request expects at `stage`, under its NFR-P-002 budget.

    Sequential rather than `asyncio.gather`, and that is a measurement decision, not an
    oversight. 02 §4 says "fast detectors (parallel)", which is a statement about the
    budget model: the lane's cost is the slowest detector, not the sum. The live three are
    CPU-bound regex passes with a combined budget of 9 ms, and `asyncio.gather` cannot
    overlap CPU-bound coroutines on one event loop — it would serialize them anyway while
    making each detector's measured `latency_ms` include the others' work. Sequential
    keeps `cp_detector_latency_ms{detector}` honest per detector (AGENTS.md §7). The
    parallelism 02 §4 describes becomes real when Tier-2 arrives, which is where the
    budgets are large enough for it to matter.

    A fault never propagates: `run_with_budget` normalizes timeout and crash into
    `DetectorFailure`, and this turns each into a `DetectorFailureRecord` for the engine
    to resolve under policy `fail_mode` (04 §5). Deciding fail_open from fail_closed here
    would put a policy decision in the runner, which is precisely what 04 §5 forbids.
    """
    registry = metrics or REGISTRY_DEFAULT
    ctx = DetectorContext(
        text=text,
        stage=stage,
        context_docs=request.context_docs,
        conversation_id=request.conversation_id,
        blocklist_extra=list(request.policy.blocklist_extra),
        detector_params=dict(request.policy.detector_params),
    )

    signals: list[Signal] = []
    failures: list[DetectorFailureRecord] = []
    latency: dict[str, float] = {}

    for name in expected_for(stage, request):
        detector = LIVE.get(name)
        if detector is None:
            coverage.note_missing(name)
            continue

        started = time.perf_counter()
        try:
            produced = await run_with_budget(detector, ctx, BUDGETS_MS[name])
        except DetectorFailure as exc:
            failures.append(
                DetectorFailureRecord(
                    detector=name, error_class=exc.error_class, stage=stage
                )
            )
        else:
            signals.extend(produced)
        finally:
            elapsed = (time.perf_counter() - started) * 1000.0
            # Recorded even when the detector faulted: a timeout consumed real wall-clock,
            # and hiding it would make the budget it breached invisible in the histogram.
            registry.observe("cp_detector_latency_ms", elapsed, detector=name)
            key = SPAN_OF.get((stage, name))
            if key is not None:
                latency[key] = latency.get(key, 0.0) + elapsed
            # `ran` means an attempt completed under the wrapper, fault included: the
            # detector was applied to this text. A fault is reported as a fault, in
            # `detector_failures_json`, and 05 §4 is explicit that the two are different
            # facts — calling a broken detector "not run" would erase the fault.
            coverage.note_ran(name)

    return LaneResult(tuple(signals), tuple(failures), latency)


def converge(
    lane: LaneResult, policy: Policy, *, metrics: MetricsRegistry | None = None
) -> Verdict:
    """Signals + faults -> one verdict (04 §4.3), recording each fault's resolved mode.

    The metric is emitted here rather than in `run_lane` because `fail_mode` is only known
    after a policy resolves the fault — 04 §5 puts `fail_mode_applied` at resolution, and
    `cp_detector_failures_total{detector,fail_mode}` carries that label.
    """
    registry = metrics or REGISTRY_DEFAULT
    # RAW records go to `evaluate`, never pre-resolved ones: `evaluate` resolves the
    # failures itself (04 §5), so resolving here first and passing the outcomes in made it
    # resolve them a second time — and `resolve_failure` on an already-resolved
    # `FailureOutcome` reads its `fail_class` str as the `fail_class()` method that only the
    # raw record has. Resolution lives in one place; this reads the result back off the
    # Verdict, which is also what keeps the metric label and the audit row agreeing.
    verdict = evaluate(lane.signals, policy, lane.failures)
    for outcome in verdict.failure_outcomes:
        registry.increment(
            "cp_detector_failures_total",
            detector=outcome.detector,
            fail_mode=outcome.fail_mode.value,
        )
    return verdict


def note_pii_intercepts(
    outcome: Outcome, use_case: str, *, metrics: MetricsRegistry | None = None
) -> None:
    """Count `pii.*` redactions by category (05 §5 `cp_pii_intercepts_total`).

    Counts the *category*, never the value — the whole point of NFR-SEC-001 and the reason
    this reads `AppliedEdit.label` rather than the text it replaced.

    One `AppliedEdit` carries exactly one `label` (a str), not a sequence: an edit is one
    transform applied to one span for one reason. Iterating it as a sequence walked the
    string's characters, and `"p".startswith("pii.")` is false, so a wrong reading here
    would have silently counted zero intercepts rather than failing — the metric would
    simply have been flat during the demo beat that exists to show it moving.
    """
    registry = metrics or REGISTRY_DEFAULT
    for edit in outcome.applied:
        if edit.label.startswith("pii."):
            registry.increment(
                "cp_pii_intercepts_total",
                category=category_of(edit.label),
                use_case=use_case,
            )


async def apply_output(text: str, verdict: Verdict, request: ResolvedRequest) -> Outcome:
    """Apply an output-stage verdict to one unit (04 §4.4), via the request's own policy.

    A thin wrapper, and the thinness is the point: it takes the `ResolvedRequest` rather
    than a `Policy`, so the policy applied is necessarily the one ingress bound to this
    request. A caller holding both could otherwise pass a policy that a hot reload changed
    mid-request (FR-CFG-002), and the applied transforms would then come from a different
    version than the verdict that ordered them — a mismatch no audit column could reveal,
    since the record stamps one `policy_version`.
    """
    return await apply_verdict(text, verdict, request.policy)


async def input_lane(
    request: ResolvedRequest,
    coverage: Coverage,
    *,
    metrics: MetricsRegistry | None = None,
) -> tuple[Verdict, Outcome, LaneResult]:
    """The 02 §4 `t0+` input lane, over the last user message (04 §4.5).

    Returns the verdict, the applied `Outcome` — whose `dispatch` flag is the
    short-circuit 04 §4.5 requires — and the raw lane result, so the caller can audit the
    signals without re-running anything.

    Scans the **last user message** rather than the whole transcript. 04 §4.5's unit is
    "the input", and in an OpenAI-shaped body earlier turns are prior context that was
    already scored on its own request; re-scanning them would re-charge old turns against
    this verdict and, under ADR-021's reasoning, measure user behaviour rather than model
    behaviour.
    """
    prompt = last_user_text(request.messages)
    lane = await run_lane(Stage.INPUT, prompt, request, coverage, metrics=metrics)
    verdict = converge(lane, request.policy, metrics=metrics)
    outcome = await apply_input_verdict(prompt, verdict, request.policy)
    note_pii_intercepts(outcome, request.use_case, metrics=metrics)
    return verdict, outcome, lane


def last_user_text(messages: Sequence[dict[str, Any]]) -> str:
    """Text of the last `role: user` message, or `""`.

    Tolerant of a missing or non-string `content`: an unusable message is checked as empty
    text rather than raising, because a malformed body is the upstream's contract to
    reject, and failing here would turn it into ERR-GW-001.
    """
    for message in reversed(list(messages)):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        # Some clients send content as a list of parts; concatenate the text ones.
        if isinstance(content, list):
            return "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
        return ""
    return ""


def redacted_messages(
    messages: Sequence[dict[str, Any]], redacted_prompt: str
) -> list[dict[str, Any]]:
    """`messages` with the last user turn replaced by its redacted text (ADR-020).

    Copies rather than mutating: the caller's body is also what the audit path may read,
    and an in-place edit would make the record describe a prompt that never existed as
    such. Only the scanned turn is replaced, because only it was scanned.
    """
    out = [dict(message) for message in messages]
    for message in reversed(out):
        if message.get("role") == "user":
            message["content"] = redacted_prompt
            break
    return out


def unit_stage(policy: Policy) -> Stage:
    """The output unit this policy checks: one sentence, or the whole response.

    `streaming: false` is ADR-014's non-streaming path, where 02 §4 buffers fully and
    reaches a single verdict — so the unit is `output_full`. Reading `streaming` rather
    than `consistency` is deliberate: the schema already enforces `consistency: on =>
    streaming: false`, and the *unit* is a property of how text is delivered.
    """
    return Stage.OUTPUT_SENTENCE if policy.streaming else Stage.OUTPUT_FULL


def gateway_overhead_ms(
    *, total_ms: float, upstream_ms: float, held_ms: float, streaming: bool
) -> float:
    """`gateway_overhead_ms` per the **normative** 06 §4 definition. Two formulas, two paths.

    * **non-streaming** — "total wall-clock − upstream call duration". A subtraction, and
      it is exact: the request is either our work or the one blocking call.
    * **streaming** — "ingress + input-lane time + Σ per-sentence hold ... upstream token
      wait time excluded". A **sum of measured intervals**, which is what `held_ms` carries.

    These are not the same number and the code must not pretend they are. `total − upstream`
    also captures relay time that is neither a hold nor a token wait, so it is an upper
    bound on the streaming figure rather than equal to it. Returning the subtraction for
    both would report an unmeasured residue as gateway overhead — inflating our own headline
    latency claim, which is the direction AGENTS.md §7 cares about least but still forbids:
    the number has to be the thing 06 §4 defines.

    The gap between the two is a real quantity, and `bench_latency` is where it belongs as a
    reported row; a caller wanting it subtracts. It is not clamped away here.
    """
    if not streaming:
        return max(0.0, total_ms - upstream_ms)
    return max(0.0, held_ms)


def note_enrichment(
    signals: Iterable[Signal], coverage: Coverage
) -> None:
    """Record `entity_enricher` coverage (04 §2.2, ADR-011).

    Not a lane member — 04 §2.2 makes enrichment its own stage between detection and the
    policy engine — so `LANES` rightly omits it and `expected_for` never yields it. But it
    is *expected* under a condition the doc states exactly: "for each span-bearing
    `hallucination.*` signal". When such a signal exists and the enricher is absent, that
    is a coverage gap a reader must see, because it changes verdicts rather than merely
    losing a label: `privacy.person` is enrichment-only (`ENRICHED_ONLY_LABELS`), and two
    of the three shipped policies map it to an action.

    When no span-bearing `hallucination.*` signal exists, enrichment was not expected and
    is therefore neither `ran` nor `not_run` — the same rule that keeps a policy-disabled
    detector out of the list (05 §4).
    """
    if any(
        signal.span is not None
        and any(label.startswith("hallucination.") for label in signal.labels)
        for signal in signals
    ):
        coverage.note_missing("entity_enricher")


def clamp_latency(latency: dict[str, float]) -> dict[str, float]:
    """Round span timings to microseconds for a byte-stable audit record.

    Rounding only. Keys are deliberately **not** filtered against the 05 §5 vocabulary:
    `spans.check_latency_keys` enforces that at the write path, and an unknown key must
    fail loudly there rather than disappear quietly here — a dropped key would turn a
    contract violation into a missing measurement.
    """
    return {key: round(value, 3) for key, value in latency.items()}


def merge_latency(into: dict[str, float], extra: Iterable[tuple[str, float]]) -> None:
    """Accumulate span timings across units, summing shared keys."""
    for key, value in extra:
        into[key] = into.get(key, 0.0) + value
