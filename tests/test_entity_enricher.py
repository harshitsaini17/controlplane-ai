"""`entity_enricher` — the 04 §2.2 enrichment stage (ADR-011, ADR-019, FR-DET-005).

The stage that had **no tests at all** before it had an implementation, in either
direction: `note_enrichment` recorded a coverage gap unconditionally and nothing checked
that the claim was true.

Fixtures come from the frozen corpus (06 §1), never invented strings: `privacy.person` is
the one label in the taxonomy with a single producer, so a hand-written case would be
testing this module against itself.
"""

from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

from controlplane.detectors import entity_enricher as ee
from controlplane.detectors import numeric_claims as nc_mod
from controlplane.detectors.base import (
    ENRICHED_LABELS_KEY,
    DetectorContext,
    Plane,
    Signal,
    Stage,
)
from controlplane.gateway import app as app_module
from controlplane.gateway import pipeline
from controlplane.gateway.ingress import ResolvedRequest
from controlplane.policy.store import PolicyStore
from controlplane.telemetry.metrics import MetricsRegistry

from tests.ml_stack import requires_ml

DATASET = pathlib.Path(__file__).resolve().parents[1] / "eval" / "dataset"

#: The one frozen `person_present: true` case whose host signal is produced by an
#: **implemented, live** detector. The other 15 depend on `rag_grounding` — see M-44.
OVLP_04 = "OVLP-04"


def _case(stem: str, case_id: str) -> dict:
    for line in (DATASET / f"{stem}.jsonl").read_text().splitlines():
        if line.strip() and json.loads(line)["case_id"] == case_id:
            return json.loads(line)
    raise AssertionError(f"{case_id} not in {stem}.jsonl — the frozen corpus moved")


@pytest.fixture
def policy():
    store = PolicyStore("policies")
    store.load()
    return store.get("hr_copilot")


@pytest.fixture
def request_obj(policy):
    return ResolvedRequest(
        request_id="r1",
        use_case="hr_copilot",
        policy=policy,
        stream=False,
        messages=[{"role": "user", "content": "hi"}],
        conversation_id=None,
        context_docs=(),
    )


def _host_signals(text: str) -> list[Signal]:
    """The real span-bearing `hallucination.*` signal, from the live producer."""
    ctx = DetectorContext(text=text, stage=Stage.OUTPUT_SENTENCE)
    signals = asyncio.run(nc_mod.numeric_claims.detect(ctx))
    assert signals, "numeric_claims emitted nothing — the fixture or detector moved"
    return signals


# --------------------------------------------------------------------------
# The stage itself
# --------------------------------------------------------------------------


@requires_ml
def test_a_person_outside_the_span_but_inside_the_sentence_still_enriches():
    """04 §2.2 reads "NER over the span (± its sentence window)", and the window half of
    that is load-bearing rather than decorative.

    In OVLP-04 the PERSON sits at chars 0-18 while the span covers `'94,000 EUR'` at
    (25,35) — **no overlap at all**. A span-only reading of §2.2 would enrich nothing here,
    and since `numeric_claims` is the only live producer of a span-bearing
    `hallucination.*` signal, it would make the whole stage unreachable while every unit
    test on the append logic still passed. The frozen corpus is what settles the reading.
    """
    case = _case("overlap", OVLP_04)
    text = case.get("response") or case["text"]
    signal = _host_signals(text)[0]

    assert signal.span is not None
    assert text[signal.span.start : signal.span.end] == "94,000 EUR"
    assert "Devendra Alagappan" not in text[signal.span.start : signal.span.end]
    assert "Devendra Alagappan" in ee._sentence_window(text, signal.span.start, signal.span.end)

    out = asyncio.run(ee.enrich([signal], text, use_case="hr_copilot"))
    assert ee.APPENDED_LABEL in out[0].labels


@requires_ml
def test_enrichment_appends_to_the_same_signal_and_never_adds_one(request_obj):
    """FR-DET-005's one-signal rule, and the reason 04 §39 states it as a *shape*.

    A second signal carrying `privacy.person` would be a different claim: the policy
    engine converges per signal, so two signals are two verdicts to reconcile where the
    doc specifies one. Identity is checked by more than a length assertion — score,
    score_kind and span must survive, because a "same signal" that silently re-scored
    would satisfy a count check.
    """
    case = _case("overlap", OVLP_04)
    text = case.get("response") or case["text"]
    before = _host_signals(text)
    out = asyncio.run(ee.enrich(list(before), text, use_case="hr_copilot"))

    assert len(out) == len(before)
    assert out[0].labels == [*before[0].labels, ee.APPENDED_LABEL]
    assert Plane.RESPONSIBILITY in out[0].planes
    assert out[0].score == before[0].score
    assert out[0].score_kind == before[0].score_kind
    assert out[0].span == before[0].span
    assert out[0].detector == before[0].detector


@requires_ml
def test_the_appended_label_is_recorded_because_adr_019_makes_it_a_contract():
    """ADR-019 / 04 §2.2: §4.3 step 2 partitions labels on `meta.enriched_labels`.

    An unrecorded append is band-adjusted as if the host detector had scored it, which is
    the specific mis-adjustment the contract exists to prevent (a borderline grounding
    score must not soften `privacy.person` into a pass). The `Signal` validator rejects
    the malformed form outright — asserted here so that "the model enforces it" is a
    tested claim rather than a docstring, since this module is the only writer.
    """
    case = _case("overlap", OVLP_04)
    text = case.get("response") or case["text"]
    out = asyncio.run(ee.enrich(_host_signals(text), text, use_case="hr_copilot"))
    assert out[0].meta[ENRICHED_LABELS_KEY] == [ee.APPENDED_LABEL]

    host = _host_signals(text)[0]
    with pytest.raises(ValueError, match="enrichment stage"):
        Signal.model_validate(
            {
                **host.model_dump(),
                "labels": [*host.labels, ee.APPENDED_LABEL],
                "planes": [*host.planes, Plane.RESPONSIBILITY],
            }
        )


@requires_ml
def test_re_enriching_an_enriched_signal_appends_nothing():
    """Idempotent, because the streaming path can re-present a segment and because
    `enrich_lane` is called per unit rather than per request. A second `privacy.person`
    would double-count in the engine's per-label convergence."""
    case = _case("overlap", OVLP_04)
    text = case.get("response") or case["text"]
    once = asyncio.run(ee.enrich(_host_signals(text), text, use_case="hr_copilot"))
    twice = asyncio.run(ee.enrich(once, text, use_case="hr_copilot"))
    assert twice[0].labels.count(ee.APPENDED_LABEL) == 1
    assert twice[0].meta[ENRICHED_LABELS_KEY] == [ee.APPENDED_LABEL]


def test_signals_the_stage_does_not_visit_are_returned_untouched():
    """04 §2.2 visits span-bearing `hallucination.*` only. A `pii.*` signal with a span,
    and a `hallucination.*` signal without one, are both out of scope — and the second is
    the case M-44 is about, so it is pinned rather than assumed."""
    spanned_pii = Signal(
        signal_id="s1", detector="tier1_pii", planes=[Plane.RESPONSIBILITY],
        labels=["pii.email"], score=1.0, score_kind="detection",
        span={"start": 0, "end": 5},
        stage=Stage.OUTPUT_SENTENCE, evidence="regex", latency_ms=0.1,
    )
    spanless_halluc = Signal(
        signal_id="s2", detector="rag_grounding", planes=[Plane.PERFORMANCE],
        labels=["hallucination.ungrounded_claim"], score=0.4, score_kind="confidence",
        span=None, stage=Stage.OUTPUT_SENTENCE, evidence="entailment", latency_ms=1.0,
    )
    assert not ee.is_enrichment_target(spanned_pii)
    assert not ee.is_enrichment_target(spanless_halluc)

    text = "Priya Raghunathan handled it."
    out = asyncio.run(ee.enrich([spanned_pii, spanless_halluc], text, use_case="hr_copilot"))
    assert out == [spanned_pii, spanless_halluc]


# --------------------------------------------------------------------------
# Budget and failure — 04 §2.2 specifies skip-and-count, never a raise
# --------------------------------------------------------------------------


@requires_ml
def test_exhausting_the_aggregate_budget_skips_the_rest_and_counts_the_spans(monkeypatch):
    """M-18's ruling: 10 ms **per sentence**, however many spans it carries.

    The budget is patched to zero rather than the clock being faked — the mechanism under
    test is "stop between windows and report how many were left", not the constant. The
    first span is still attempted, which is deliberate: a budget that could enrich nothing
    would make the stage unreachable on a cold pipeline rather than merely degraded.

    The counter is asserted at the **span** count, not one per call: "how much enrichment
    was lost" is the quantity 04 §2.2 attaches it to, and a per-call increment would
    report a sentence that lost eight spans identically to one that lost one.
    """
    monkeypatch.setattr(ee, "BUDGET_MS", 0.0)
    text = (
        "Devendra Alagappan earns 94,000 EUR and 88,000 EUR and 77,000 EUR, "
        "which is above the band for his role."
    )
    signals = _host_signals(text)
    assert len(signals) >= 2, "fixture text must carry multiple spans for this test to bite"

    metrics = MetricsRegistry()
    out = asyncio.run(ee.enrich(signals, text, use_case="hr_copilot", metrics=metrics))

    assert len(out) == len(signals), "a skipped span is still a signal (04 §2.2)"
    series = metrics.snapshot()["cp_enrichment_skipped_total"]["series"]
    assert len(series) == 1
    assert series[0]["labels"] == {"reason": ee.REASON_BUDGET, "use_case": "hr_copilot"}
    assert series[0]["value"] == float(len(signals) - 1)


def test_a_failing_enricher_returns_the_signals_and_counts_instead_of_raising(monkeypatch):
    """04 §2.2: enrichment "never blocks and is not a policy `fail_mode` class".

    So there is nothing for a raise to resolve *to* — a propagating exception would take
    down a request over a stage whose absence is specified to remove a possible escalation
    and nothing else.
    """
    def _boom() -> object:
        raise ImportError("no spacy")

    monkeypatch.setattr(ee, "_load_nlp", _boom)
    case = _case("overlap", OVLP_04)
    text = case.get("response") or case["text"]
    signals = _host_signals(text)

    metrics = MetricsRegistry()
    out = asyncio.run(ee.enrich(signals, text, use_case="hr_copilot", metrics=metrics))

    assert out == signals
    assert ee.APPENDED_LABEL not in out[0].labels
    series = metrics.snapshot()["cp_enrichment_skipped_total"]["series"]
    assert series[0]["labels"] == {"reason": ee.REASON_FAILURE, "use_case": "hr_copilot"}


def test_no_checked_text_reaches_a_log_record(monkeypatch, caplog):
    """NFR-SEC-001 / AGENTS.md §9.6. This stage labels content about identifiable people,
    so its own diagnostics are the last place a name should appear — including via an
    exception message, which is why the handler logs `type(exc).__name__` and not `exc`.
    """
    def _boom() -> object:
        raise RuntimeError("failed on 'Devendra Alagappan earns 94,000 EUR'")

    monkeypatch.setattr(ee, "_load_nlp", _boom)
    case = _case("overlap", OVLP_04)
    text = case.get("response") or case["text"]

    with caplog.at_level("INFO"):
        asyncio.run(ee.enrich(_host_signals(text), text, use_case="hr_copilot"))

    assert "Devendra" not in caplog.text
    assert "94,000" not in caplog.text
    assert "RuntimeError" in caplog.text


# --------------------------------------------------------------------------
# Coverage — the 05 §4 column, and the ADR-033 state it must not misreport
# --------------------------------------------------------------------------


@requires_ml
def test_a_ran_enricher_is_recorded_as_ran(request_obj):
    case = _case("overlap", OVLP_04)
    text = case.get("response") or case["text"]
    lane = pipeline.LaneResult(signals=tuple(_host_signals(text)))
    coverage = pipeline.Coverage()

    asyncio.run(pipeline.enrich_lane(lane, text, request_obj, coverage))

    assert json.loads(coverage.serialize())["ran"] == [ee.NAME]
    assert ee.APPENDED_LABEL in lane.signals[0].labels, "enrich_lane must write back"


def test_an_unloadable_enricher_is_unavailable_and_never_not_implemented(request_obj):
    """ADR-033's third state, in the column it actually reaches.

    `entity_enricher` is in no `LANES` row, so it never passes through `run_lane`'s
    loadability check — its only route to the coverage column is this stage. Before
    `_probe_scope()` named it, the boot manifest omitted it and this path recorded
    `not_implemented`: "this phase never wrote the detector", said about code that exists.
    That is a false statement in an append-only table, which is precisely the confusion
    ADR-033's third state was created to end (and M-41 predicted for the first
    dependency-bearing detector to go live).
    """
    case = _case("overlap", OVLP_04)
    text = case.get("response") or case["text"]
    lane = pipeline.LaneResult(signals=tuple(_host_signals(text)))
    coverage = pipeline.Coverage(unloadable={ee.NAME: "spacy"})

    asyncio.run(pipeline.enrich_lane(lane, text, request_obj, coverage))

    recorded = json.loads(coverage.serialize())
    assert recorded["unavailable"] == [{"detector": ee.NAME, "missing": "spacy"}]
    assert recorded["not_run"] == []
    assert ee.APPENDED_LABEL not in lane.signals[0].labels


def test_no_enrichable_signal_means_neither_ran_nor_not_run(request_obj):
    """05 §4: a stage that was not expected is not a gap. Same rule that keeps a
    policy-disabled detector out of the list."""
    lane = pipeline.LaneResult(signals=())
    coverage = pipeline.Coverage()
    asyncio.run(pipeline.enrich_lane(lane, "nothing numeric here", request_obj, coverage))
    recorded = json.loads(coverage.serialize())
    assert recorded == {"ran": [], "not_run": []}


def test_the_probe_scope_names_the_enricher():
    """It is reachable through neither `LIVE` nor `_REGISTRY` — 04 §2.2 makes enrichment
    its own stage — so an explicit term is the only honest route. A `LIVE` entry would be
    the cheaper edit and the wrong one: `LIVE` is `dict[str, Detector]` keyed by lane
    membership, so the entry would be executionally inert and the type would misdescribe
    the value to buy a side effect in this function."""
    assert ee.NAME in app_module._probe_scope()
    assert ee.NAME not in pipeline.LIVE
    assert not any(ee.NAME in names for names in pipeline.LANES.values())


# --------------------------------------------------------------------------
# The removed input-stage call site
# --------------------------------------------------------------------------


def test_no_input_stage_detector_can_produce_an_enrichable_signal():
    """Why `enrich_lane` is called at the two output sites and not at the input one.

    `input_lane` converges internally, so an enrichment call after it returns would append
    labels the verdict was already computed without — a label that reaches the audit
    record having influenced nothing. That is safe today only because no input-stage
    detector emits `hallucination.*`, and ADR-030's derivation table agrees (enrichment
    appears in the per-sentence rows, never the input row).

    Asserted from the 04 §2 registry rather than from `LIVE`, so it fails when the *spec*
    gains such a detector rather than when someone implements one.
    """
    doc = (pathlib.Path(__file__).resolve().parents[1]
           / "docs" / "04-policy-and-detection-spec.md").read_text()
    for name in pipeline.LANES[Stage.INPUT]:
        rows = [l for l in doc.splitlines() if l.startswith(f"| `{name}`")]
        assert rows, f"no 04 §2 registry row for {name}"
        assert "hallucination." not in rows[0].split("|")[4], (
            f"{name} now emits a `hallucination.*` label, so the input stage can carry an "
            "enrichable signal — enrichment must move inside `input_lane`, before its "
            "`converge`, rather than being called after it returns"
        )
