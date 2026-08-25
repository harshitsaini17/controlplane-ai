"""Tests for the detector contract in `controlplane.detectors.base`.

Covers 04 §1 (signal model), 04 §1.2 / ADR-012 (score_kind), 04 §2 (common
contract + registry), NFR-P-002 (budget enforcement) and NFR-SEC-001 (evidence
never carries a raw value).

Async tests drive the event loop with `asyncio.run()` rather than pytest-asyncio:
adding a test dependency needs flagging per AGENTS.md §10, and the contract under
test is small enough that the plugin buys nothing.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from controlplane.detectors.base import (
    BUDGETS_MS,
    ENRICHED_LABELS_KEY,
    DetectorContext,
    ENRICHED_ONLY_LABELS,
    Detector,
    DetectorError,
    DetectorFailure,
    DetectorTimeout,
    Plane,
    ScoreKind,
    Signal,
    Span,
    Stage,
    clear_registry,
    get_detector,
    register,
    registered_names,
    run_with_budget,
)
from controlplane.policy.schema import TAXONOMY


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def make_signal(**overrides: object) -> Signal:
    """A minimal valid signal; override one field per negative test."""
    fields: dict[str, object] = {
        "detector": "tier1_pii",
        "planes": [Plane.RESPONSIBILITY],
        "labels": ["pii.ssn"],
        "score": 1.0,
        "score_kind": ScoreKind.DETECTION,
        "span": Span(start=112, end=123),
        "stage": Stage.OUTPUT_SENTENCE,
        "evidence": "category:ssn pattern",
        "latency_ms": 0.4,
    }
    fields.update(overrides)
    return Signal(**fields)  # type: ignore[arg-type]


class StubDetector:
    """Returns a fixed signal list. Structurally satisfies the 04 §2 contract."""

    def __init__(self, name: str = "tier1_pii", signals: list[Signal] | None = None) -> None:
        self.name = name
        self._signals = signals if signals is not None else []
        self.calls = 0

    async def detect(self, ctx: object) -> list[Signal]:
        self.calls += 1
        return list(self._signals)


@pytest.fixture(autouse=True)
def _isolate_registry() -> object:
    """The registry is module-level state; keep tests independent of each other."""
    clear_registry()
    yield
    clear_registry()


# --------------------------------------------------------------------------
# 04 §1 — the signal model
# --------------------------------------------------------------------------


def test_04_1_signal_round_trips_the_documented_example() -> None:
    """The 04 §1 JSON example must be constructible field-for-field."""
    signal = make_signal()
    assert signal.detector == "tier1_pii"
    assert signal.planes == [Plane.RESPONSIBILITY]
    assert signal.labels == ["pii.ssn"]
    assert signal.score_kind is ScoreKind.DETECTION
    assert signal.span is not None and (signal.span.start, signal.span.end) == (112, 123)
    assert signal.stage is Stage.OUTPUT_SENTENCE
    assert signal.meta == {}
    assert signal.signal_id  # auto-assigned


def test_signal_ids_are_unique_per_signal() -> None:
    """signal_id lands in audit as the contributing-signal reference (04 §4.3 step 5)."""
    assert make_signal().signal_id != make_signal().signal_id


def test_fr_det_005_signal_is_multi_label_across_planes() -> None:
    """FR-DET-005: one signal, several labels, several planes — the overlap case.

    This is the OVLP-01 shape, and post-ADR-019 it must declare `privacy.person` as
    enriched: the label reaches a signal only by the §2.2 enrichment stage, and 04 §4.3
    step 2 needs that provenance to know the label is *not* band-adjusted.
    """
    signal = make_signal(
        detector="rag_grounding",
        labels=["hallucination.ungrounded_claim", "privacy.person"],
        planes=[Plane.PERFORMANCE, Plane.RESPONSIBILITY],
        score=0.41,
        score_kind=ScoreKind.CONFIDENCE,
        evidence="category:ungrounded claim; PERSON entity in span window",
        meta={ENRICHED_LABELS_KEY: ["privacy.person"]},
    )
    assert len(signal.labels) == 2
    assert Plane.PERFORMANCE in signal.planes and Plane.RESPONSIBILITY in signal.planes


def test_rule_labels_outside_the_taxonomy_are_rejected() -> None:
    """04 §1.1 is a closed set, extended only via a doc change."""
    with pytest.raises(ValidationError, match="closed"):
        make_signal(labels=["pii.passport"])


def test_rule_duplicate_labels_are_rejected() -> None:
    """A repeated label would be counted twice by most-severe resolution (04 §4.3)."""
    with pytest.raises(ValidationError, match="duplicate"):
        make_signal(labels=["pii.ssn", "pii.ssn"])


def test_rule_empty_labels_rejected() -> None:
    with pytest.raises(ValidationError):
        make_signal(labels=[])


def test_rule_empty_planes_rejected() -> None:
    with pytest.raises(ValidationError):
        make_signal(planes=[])


@pytest.mark.parametrize("score", [-0.01, 1.01, 2.0])
def test_rule_score_must_be_in_unit_interval(score: float) -> None:
    """04 §1: score ∈ [0,1]."""
    with pytest.raises(ValidationError):
        make_signal(score=score)


def test_rule_unknown_signal_field_rejected() -> None:
    """Signals are serialized straight into audit; a typo'd field must not ride along."""
    with pytest.raises(ValidationError):
        make_signal(confidence=0.9)


def test_rule_negative_latency_rejected() -> None:
    with pytest.raises(ValidationError):
        make_signal(latency_ms=-1.0)


# --------------------------------------------------------------------------
# NFR-SEC-001 — evidence never carries a raw matched value (D7 if it does)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("evidence", "why"),
    [
        ("matched alice@example.com", "email address"),
        ("value 123456789", "long digit run"),
        ("found 4111 1111 1111 1111", "grouped digits, credit-card shape"),
        ("ssn 123-45-6789", "grouped digits, SSN shape"),
    ],
)
def test_nfr_sec_001_evidence_rejects_raw_value_shapes(evidence: str, why: str) -> None:
    """Raw PII in a signal is D7: signals_json (05 §3) would persist it at rest."""
    with pytest.raises(ValidationError, match="raw value"):
        make_signal(evidence=evidence)
    assert why  # documents the intent of each case


@pytest.mark.parametrize(
    "evidence",
    [
        "category:ssn pattern",
        "category:email pattern",
        "category:credit_card pattern (Luhn ok)",
        "blocklist term matched, category:security",
        "method:self_consistency cosine below tau_low",
    ],
)
def test_nfr_sec_001_category_descriptors_are_accepted(evidence: str) -> None:
    """The guard must not block the documented evidence style from 04 §1."""
    assert make_signal(evidence=evidence).evidence == evidence


def test_evidence_cannot_be_empty() -> None:
    """An empty evidence string would make an audit record unexplainable."""
    with pytest.raises(ValidationError):
        make_signal(evidence="")


# --------------------------------------------------------------------------
# 04 §1 — spans
# --------------------------------------------------------------------------


def test_rule_span_start_must_precede_end() -> None:
    """An empty span has no extent for 04 §6 redact/soften to act on."""
    with pytest.raises(ValidationError, match="strictly less than"):
        Span(start=10, end=10)
    with pytest.raises(ValidationError, match="strictly less than"):
        Span(start=11, end=10)


def test_rule_negative_span_offsets_rejected() -> None:
    with pytest.raises(ValidationError):
        Span(start=-1, end=5)


def test_request_level_signal_may_omit_its_span() -> None:
    """04 §1: span is null if request-level."""
    signal = make_signal(detector="cost_budget", span=None, stage=Stage.INPUT,
                         labels=["cost.budget_exceeded"], planes=[Plane.COST],
                         evidence="category:budget ledger over monthly ceiling")
    assert signal.span is None


def test_rule_conversation_stage_cannot_carry_a_span() -> None:
    """A conversation signal describes accumulated state, not an extent (04 §1)."""
    with pytest.raises(ValidationError, match="cannot carry a span"):
        make_signal(
            detector="conv_tracker",
            stage=Stage.CONVERSATION,
            labels=["conversation.cumulative_risk"],
            span=Span(start=0, end=5),
            evidence="category:cumulative risk threshold crossed",
        )


# --------------------------------------------------------------------------
# ADR-012 — score_kind polarity is normative
# --------------------------------------------------------------------------


def test_adr_012_both_score_kinds_exist_and_are_distinct() -> None:
    assert ScoreKind.DETECTION.value == "detection"
    assert ScoreKind.CONFIDENCE.value == "confidence"
    assert ScoreKind.DETECTION is not ScoreKind.CONFIDENCE


def test_adr_012_deterministic_detector_emits_detection_kind_at_1_0() -> None:
    """04 §1.2: deterministic emitters use 1.0 and bypass band logic entirely."""
    signal = make_signal(
        detector="numeric_claims",
        labels=["hallucination.unsourced_numeric"],
        planes=[Plane.PERFORMANCE],
        score=1.0,
        score_kind=ScoreKind.DETECTION,
        evidence="category:unsourced numeric, no citation marker",
    )
    assert signal.score == 1.0 and signal.score_kind is ScoreKind.DETECTION


# --------------------------------------------------------------------------
# 04 §2 — registry
# --------------------------------------------------------------------------


def test_04_2_register_and_retrieve_by_registry_name() -> None:
    detector = StubDetector(name="tier1_pii")
    assert register(detector) is detector
    assert get_detector("tier1_pii") is detector
    assert registered_names() == ("tier1_pii",)


def test_registry_rejects_a_detector_with_no_nfr_p_002_budget() -> None:
    """An unbudgeted hot-path detector is how latency regressions get in unnoticed."""
    with pytest.raises(ValueError, match="no NFR-P-002 budget"):
        register(StubDetector(name="tier1_teleporter"))


def test_registry_rejects_duplicate_registration() -> None:
    register(StubDetector(name="tier1_pii"))
    with pytest.raises(ValueError, match="already registered"):
        register(StubDetector(name="tier1_pii"))


def test_registry_rejects_nameless_detector() -> None:
    with pytest.raises(ValueError, match="non-empty `name`"):
        register(StubDetector(name=""))


def test_unknown_detector_lookup_names_what_is_registered() -> None:
    register(StubDetector(name="tier1_pii"))
    with pytest.raises(KeyError, match="tier1_pii"):
        get_detector("tier2_toxicity")


def test_stub_detector_satisfies_the_protocol_structurally() -> None:
    """04 §2's contract is structural — no base class required."""
    assert isinstance(StubDetector(), Detector)


# --------------------------------------------------------------------------
# NFR-P-002 — budgets transcribed from the 04 §2 registry table
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("detector", "budget_ms"),
    [
        ("tier1_pii", 2.0),
        ("tier1_blocklist", 2.0),
        ("tier2_injection", 25.0),
        ("tier2_toxicity", 25.0),
        ("fast_consistency", 60.0),
        ("rag_grounding", 30.0),
        ("numeric_claims", 5.0),
        ("cost_budget", 1.0),
        ("loop_guard", 1.0),
        ("conv_tracker", 1.0),
        ("entity_enricher", 10.0),
    ],
)
def test_nfr_p_002_budget_matches_the_doc_table(detector: str, budget_ms: float) -> None:
    """Transcription check against 04 §2 / 04 §2.2 — a drifted budget is a silent NFR change."""
    assert BUDGETS_MS[detector] == budget_ms


def test_budget_table_covers_exactly_the_documented_detectors() -> None:
    """Guards against a detector being added to code without a doc budget, or vice versa."""
    assert set(BUDGETS_MS) == {
        "tier1_pii", "tier1_blocklist", "tier2_injection", "tier2_toxicity",
        "fast_consistency", "rag_grounding", "numeric_claims",
        "cost_budget", "loop_guard", "conv_tracker", "entity_enricher",
    }


# --------------------------------------------------------------------------
# 04 §2 / 04 §5 — budget enforcement and failure vocabulary
# --------------------------------------------------------------------------


def test_run_with_budget_returns_signals_on_the_happy_path() -> None:
    detector = StubDetector(signals=[make_signal()])
    signals = asyncio.run(run_with_budget(detector, ctx=None))
    assert len(signals) == 1 and detector.calls == 1


def test_run_with_budget_raises_detector_timeout_past_its_budget() -> None:
    """04 §2: a detector must not hang; the gateway enforces asyncio.wait_for."""

    class Slow:
        name = "tier1_pii"

        async def detect(self, ctx: object) -> list[Signal]:
            await asyncio.sleep(0.5)  # 500 ms vs a 2 ms budget
            return []

    with pytest.raises(DetectorTimeout) as excinfo:
        asyncio.run(run_with_budget(Slow(), ctx=None))
    assert excinfo.value.detector == "tier1_pii"
    assert excinfo.value.error_class == "DetectorTimeout"
    assert "NFR-P-002" in str(excinfo.value)


def test_run_with_budget_wraps_a_raise_as_detector_error() -> None:
    class Broken:
        name = "tier1_pii"

        async def detect(self, ctx: object) -> list[Signal]:
            raise RuntimeError("upstream exploded")

    with pytest.raises(DetectorError) as excinfo:
        asyncio.run(run_with_budget(Broken(), ctx=None))
    assert excinfo.value.detector == "tier1_pii"
    assert excinfo.value.error_class == "DetectorError"


def test_nfr_sec_001_wrapped_error_text_does_not_leak_the_original_message() -> None:
    """A traceback can quote the very content being checked, so only the class travels."""
    secret = "alice@example.com"

    class Leaky:
        name = "tier1_pii"

        async def detect(self, ctx: object) -> list[Signal]:
            raise RuntimeError(f"failed while scanning {secret}")

    with pytest.raises(DetectorError) as excinfo:
        asyncio.run(run_with_budget(Leaky(), ctx=None))
    assert secret not in str(excinfo.value)
    assert "RuntimeError" in str(excinfo.value)


def test_detector_failure_is_not_double_wrapped() -> None:
    """A detector that already speaks the 04 §5 vocabulary passes through unchanged."""
    original = DetectorTimeout("tier1_pii", "self-reported timeout")

    class SelfReporting:
        name = "tier1_pii"

        async def detect(self, ctx: object) -> list[Signal]:
            raise original

    with pytest.raises(DetectorTimeout) as excinfo:
        asyncio.run(run_with_budget(SelfReporting(), ctx=None))
    assert excinfo.value is original


def test_cancellation_is_not_treated_as_a_detector_fault() -> None:
    """Cooperative cancellation must not synthesize a _meta.detector_failure signal."""

    class Cancelled:
        name = "tier1_pii"

        async def detect(self, ctx: object) -> list[Signal]:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_with_budget(Cancelled(), ctx=None))


def test_run_with_budget_rejects_a_non_signal_return() -> None:
    """04 §2 contract: detect returns list[Signal], nothing else."""

    class WrongShape:
        name = "tier1_pii"

        async def detect(self, ctx: object) -> list[Signal]:
            return ["not a signal"]  # type: ignore[list-item]

    with pytest.raises(DetectorError, match="list\\[Signal\\]"):
        asyncio.run(run_with_budget(WrongShape(), ctx=None))


def test_run_with_budget_stamps_measured_latency_when_detector_reports_zero() -> None:
    """No signal may reach audit claiming an unmeasured 0.0 (AGENTS.md §7)."""
    detector = StubDetector(signals=[make_signal(latency_ms=0.0)])
    signals = asyncio.run(run_with_budget(detector, ctx=None))
    assert signals[0].latency_ms > 0.0


def test_run_with_budget_preserves_a_detector_reported_latency() -> None:
    """A detector's own finer-grained timing wins over the wrapper's wall-clock."""
    detector = StubDetector(signals=[make_signal(latency_ms=0.25)])
    signals = asyncio.run(run_with_budget(detector, ctx=None))
    assert signals[0].latency_ms == 0.25


def test_run_with_budget_needs_a_budget_from_somewhere() -> None:
    class Unbudgeted:
        name = "tier1_teleporter"

        async def detect(self, ctx: object) -> list[Signal]:
            return []

    with pytest.raises(ValueError, match="no budget"):
        asyncio.run(run_with_budget(Unbudgeted(), ctx=None))


def test_explicit_budget_overrides_the_table() -> None:
    """Lets bench_latency probe a detector at a non-spec budget without mutating BUDGETS_MS."""
    detector = StubDetector(signals=[make_signal()])
    assert asyncio.run(run_with_budget(detector, ctx=None, budget_ms=500.0))


def test_detector_failure_hierarchy_is_catchable_as_one_class() -> None:
    """04 §5 resolves both faults through the same fail_mode path."""
    assert issubclass(DetectorTimeout, DetectorFailure)
    assert issubclass(DetectorError, DetectorFailure)


# --------------------------------------------------------------------------
# Cross-module coherence
# --------------------------------------------------------------------------


def test_taxonomy_is_shared_with_policy_schema_not_duplicated() -> None:
    """One closed set (04 §1.1). A second copy would diverge on the next doc change."""
    from controlplane.detectors import base

    assert base.TAXONOMY is TAXONOMY


def test_every_taxonomy_label_can_appear_on_a_signal() -> None:
    """No label in 04 §1.1 is unreachable through the signal model.

    `ENRICHED_ONLY_LABELS` are reachable only as an append onto a host signal (04 §2.2
    — no detector emits them directly), so they are built that way here. That is not an
    exemption from the claim but the precise form the claim takes for them.
    """
    for label in sorted(TAXONOMY):
        if label in ENRICHED_ONLY_LABELS:
            signal = make_signal(
                labels=["hallucination.ungrounded_claim", label],
                planes=[Plane.PERFORMANCE, Plane.RESPONSIBILITY],
                score=0.41,
                score_kind=ScoreKind.CONFIDENCE,
                evidence=f"category:ungrounded claim; category:{label.split('.')[-1]}",
                meta={ENRICHED_LABELS_KEY: [label]},
            )
            assert label in signal.labels
            continue
        signal = make_signal(labels=[label], evidence=f"category:{label.split('.')[-1]}")
        assert signal.labels == [label]


# --------------------------------------------------------------------------
# ADR-019 — meta.enriched_labels as a construction-time contract (04 §2.2)
# --------------------------------------------------------------------------


def _enriched_signal(**overrides: object) -> Signal:
    """The canonical enriched overlap signal: hallucination host + appended person."""
    fields: dict[str, object] = {
        "detector": "rag_grounding",
        "labels": ["hallucination.ungrounded_claim", "privacy.person"],
        "planes": [Plane.PERFORMANCE, Plane.RESPONSIBILITY],
        "score": 0.41,
        "score_kind": ScoreKind.CONFIDENCE,
        "evidence": "category:ungrounded claim; PERSON entity in span window",
        "meta": {ENRICHED_LABELS_KEY: ["privacy.person"]},
    }
    fields.update(overrides)
    return make_signal(**fields)


def test_adr_019_enriched_label_declares_its_provenance() -> None:
    """The happy path: the partition 04 §4.3 step 2 computes is readable off the signal."""
    signal = _enriched_signal()
    enriched = set(signal.meta[ENRICHED_LABELS_KEY])
    host = set(signal.labels) - enriched
    assert enriched == {"privacy.person"}
    assert host == {"hallucination.ungrounded_claim"}


def test_adr_019_unrecorded_append_is_rejected() -> None:
    """Direction 1 — and the reason the guard exists at all.

    An unrecorded `privacy.person` would be partitioned as a HOST label and so
    band-adjusted by the host's grounding score. On `hr_copilot` (`borderline_action:
    pass`) that silently turns beat 4b's BLOCK into a PASS — a calibration change
    breaking the demo's thesis with nothing to notice it.
    """
    with pytest.raises(ValidationError, match="missing from meta"):
        _enriched_signal(meta={})


def test_adr_019_unrecorded_append_rejected_even_with_the_key_present() -> None:
    """A present-but-incomplete list is the likelier bug than a missing key."""
    with pytest.raises(ValidationError, match="missing from meta"):
        _enriched_signal(meta={ENRICHED_LABELS_KEY: []})


def test_adr_019_recorded_label_absent_from_labels_is_rejected() -> None:
    """Direction 2: it describes a signal that does not exist, and shrinks the host set."""
    with pytest.raises(ValidationError, match="absent from labels"):
        make_signal(
            labels=["pii.ssn"],
            meta={ENRICHED_LABELS_KEY: ["privacy.person"]},
        )


def test_adr_019_malformed_enriched_labels_value_is_rejected() -> None:
    """A non-list would make the partition silently all-host — the exact failure mode."""
    with pytest.raises(ValidationError, match="must be a list"):
        _enriched_signal(meta={ENRICHED_LABELS_KEY: "privacy.person"})


def test_adr_019_duplicate_enriched_entries_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate entries"):
        _enriched_signal(
            meta={ENRICHED_LABELS_KEY: ["privacy.person", "privacy.person"]}
        )


def test_adr_019_all_enriched_leaves_no_host_label() -> None:
    """Enrichment appends to an existing signal (§2.2); the step-2 score is the host's."""
    with pytest.raises(ValidationError, match="no host label"):
        make_signal(
            labels=["privacy.person"],
            meta={ENRICHED_LABELS_KEY: ["privacy.person"]},
        )


def test_adr_019_enriched_person_must_carry_the_responsibility_plane() -> None:
    """§2.2 appends label and plane together; omitting the plane misreports the firing."""
    with pytest.raises(ValidationError, match="responsibility"):
        _enriched_signal(planes=[Plane.PERFORMANCE])


def test_adr_019_ordinary_signal_needs_no_meta_key() -> None:
    """The overwhelmingly common case stays boilerplate-free: no key means no appends."""
    assert make_signal().meta == {}


def test_adr_019_unrelated_meta_keys_are_untouched() -> None:
    """`meta` is a free-form bag (04 §1); only the one reserved key is constrained."""
    signal = make_signal(meta={"method": "embedding_cosine", "samples": 2})
    assert signal.meta["method"] == "embedding_cosine"


# --------------------------------------------------------------------------
# DetectorContext — the shape 04 §2 names as `ctx` but never defines (Q-14)
# --------------------------------------------------------------------------


def test_ctx_requires_a_stage() -> None:
    """Every 04 §2 row checks some text at some stage; the stage is never implicit."""
    with pytest.raises(ValidationError):
        DetectorContext(text="hello")  # type: ignore[call-arg]


def test_ctx_defaults_are_empty_not_absent() -> None:
    """A detector reads `context_docs` and `blocklist_extra` unconditionally, so the
    unset case must be an empty container rather than None."""
    ctx = DetectorContext(stage=Stage.INPUT)
    assert ctx.text == ""
    assert ctx.context_docs == []
    assert ctx.blocklist_extra == []
    assert ctx.detector_params == {}
    assert ctx.conversation_id is None


def test_ctx_rejects_unknown_fields() -> None:
    """`extra="forbid"` so a typo'd field name fails loudly instead of being silently
    ignored by the detector that expected to read it."""
    with pytest.raises(ValidationError):
        DetectorContext(stage=Stage.INPUT, contextdocs=["oops"])  # type: ignore[call-arg]


def test_ctx_params_for_returns_the_detectors_own_overrides() -> None:
    """04 §3 `detector_params` is keyed by detector name (e.g. toxicity cutoffs)."""
    ctx = DetectorContext(
        stage=Stage.OUTPUT_SENTENCE,
        detector_params={"tier2_toxicity": {"moderate": 0.4, "high": 0.75}},
    )
    assert ctx.params_for("tier2_toxicity") == {"moderate": 0.4, "high": 0.75}


def test_ctx_params_for_is_empty_for_a_detector_with_no_overrides() -> None:
    ctx = DetectorContext(stage=Stage.INPUT, detector_params={"tier2_toxicity": {"high": 0.9}})
    assert ctx.params_for("tier1_pii") == {}


def test_fr_pol_002_ctx_carries_no_policy_and_no_action_map() -> None:
    """The load-bearing property, pinned so a later convenience edit fails loudly.

    base.py's stated asymmetry is that nothing in it reads a policy, and that is what keeps
    FR-POL-002 true: a detector able to see the label→action map could start deciding
    actions, which 04 §1 reserves to the engine. So the engine projects in exactly the two
    documented policy fields as plain data — never a `Policy` object — and the detector
    cannot tell which use case it is serving (AGENTS.md §9.1).

    Asserting the whole field set rather than "no policy field" is deliberate: it also
    catches the subtler version, where someone adds `use_case` or `label_actions` for
    convenience and re-opens the door a different way.
    """
    assert set(DetectorContext.model_fields) == {
        "text",
        "stage",
        "context_docs",
        "conversation_id",
        "blocklist_extra",
        "detector_params",
    }
