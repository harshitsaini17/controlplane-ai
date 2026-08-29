"""`rag_grounding` contract properties (04 §2, M-44, ADR-012, NFR-SEC-001).

`_score` is stubbed throughout, and that is not a mocked measurement (AGENTS.md §5.4): every
assertion here is about *shape* — span extent, score polarity, label, and what reaches the audit
log — none of which is a measured or computed figure. The real encoder is exercised end to end by
`tests/test_gateway_app.py` and `tests/test_fault_injection.py`, where it runs unstubbed. Keeping
the shape tests model-free is what stops a ~7 s checkpoint load landing in the unit suite.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from controlplane.detectors import rag_grounding as rg
from controlplane.detectors.base import DetectorContext, Plane, ScoreKind, Stage, budget_ms

DOCS = ["The refund window is 30 days from purchase."]
TEXT = "You can get a refund within 30 days."


def _stub(monkeypatch: pytest.MonkeyPatch, score: float, cosine: float | None = None) -> None:
    """Replace the encode+similarity step with a fixed result."""
    def fake(text: str, docs: tuple[str, ...]) -> dict[str, Any]:
        return {
            "score": max(0.0, cosine if cosine is not None else score),
            "cosine_raw": cosine if cosine is not None else score,
            "best_doc_index": 0,
            "docs_encoded": len(docs),
            "encode_ms": 1.0,
        }
    monkeypatch.setattr(rg, "_score", fake)


def _detect(text: str = TEXT, docs: list[str] | None = None,
            stage: Stage = Stage.OUTPUT_SENTENCE, **kw: Any) -> list:
    ctx = DetectorContext(
        text=text, stage=stage,
        context_docs=DOCS if docs is None else docs, **kw
    )
    return asyncio.run(rg.rag_grounding.detect(ctx))


def test_the_span_is_the_whole_sentence(monkeypatch) -> None:
    """M-44's ruling, and it is load-bearing rather than cosmetic.

    A grounding score is a property of the sentence as a unit — the embedding identifies no
    sub-extent as the ungrounded part. The span must still be present: 04 §4.3 step 4 promotes a
    span-less confidence signal to ESCALATE at every firing (the ADR-015 rule that makes
    `borderline_action: edit` inert for `fast_consistency`), so a `None` here would make
    `support_bot`'s documented `hallucination.ungrounded_claim: edit` unreachable.
    """
    _stub(monkeypatch, 0.4)
    signal = _detect()[0]
    assert signal.span is not None, "a span-less confidence signal is promoted, never softened"
    assert (signal.span.start, signal.span.end) == (0, len(TEXT))


def test_it_emits_the_04_contract_row(monkeypatch) -> None:
    _stub(monkeypatch, 0.4)
    signal = _detect()[0]
    assert signal.detector == "rag_grounding"
    assert signal.labels == ["hallucination.ungrounded_claim"]
    assert signal.planes == [Plane.PERFORMANCE]
    assert signal.score_kind is ScoreKind.CONFIDENCE
    assert signal.stage is Stage.OUTPUT_SENTENCE
    assert signal.meta["budget_ms"] == budget_ms("rag_grounding") == 30.0


def test_a_well_grounded_sentence_still_emits(monkeypatch) -> None:
    """ADR-012: higher is *better*, and the engine — not the detector — applies the band.

    04 §4.3 step 2 has an explicit `above_tau_high_dropped` branch for a score that clears
    `tau_high`. A detector-side cutoff would make that branch unreachable and would put a
    threshold in Python that §9.1 and 04 §3 place in per-use-case YAML.
    """
    _stub(monkeypatch, 0.99)
    signals = _detect()
    assert len(signals) == 1 and signals[0].score == pytest.approx(0.99)


def test_it_reads_no_detector_params(monkeypatch) -> None:
    """The one registry row whose "no tunables" is a consequence of the contract.

    `tau_low`/`tau_high` already are its thresholds (calibrated per 06 §3), so a policy that
    supplies junk under this detector's key must be inert rather than raising — unlike
    `tier2_toxicity`, which validates its two cutoffs and rejects a mistyped one.
    """
    _stub(monkeypatch, 0.4)
    signal = _detect(detector_params={"rag_grounding": {"cutoff": 0.9}})[0]
    assert signal.score == pytest.approx(0.4)


def test_evidence_carries_no_document_text_and_no_sentence_text(monkeypatch) -> None:
    """NFR-SEC-001 / §9.6: a context doc is caller-supplied and may carry PII.

    `evidence` is written to the audit log, so it names the document by index and quotes
    neither side. The doc here is a distinctive string precisely so a leak would be visible.
    """
    secret = "Ada Lovelace's account 4111111111111111 is past due."
    _stub(monkeypatch, 0.4)
    signal = _detect(text=TEXT, docs=[secret])[0]
    assert secret not in signal.evidence
    assert "Ada Lovelace" not in signal.evidence and "4111" not in signal.evidence
    assert TEXT not in signal.evidence
    assert "#0" in signal.evidence, "the doc should still be identified, just not quoted"


def test_a_negative_cosine_clamps_but_is_preserved_in_meta(monkeypatch) -> None:
    """`Signal.score` is [0, 1] while cosine is [-1, 1]; the clamp must be observable.

    Clamping cannot change a routing decision — both readings sit below any `tau_low` a policy
    could sanely set — but a silently clamped value would make the audit record unable to
    distinguish "barely ungrounded" from "opposite of the source".
    """
    _stub(monkeypatch, 0.0, cosine=-0.42)
    signal = _detect()[0]
    assert signal.score == 0.0
    assert signal.meta["cosine_raw"] == pytest.approx(-0.42)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"docs": []},
        {"docs": ["   "]},
        {"text": "   "},
        {"stage": Stage.INPUT},
        {"stage": Stage.OUTPUT_FULL},
    ],
)
def test_it_returns_nothing_when_there_is_nothing_to_score(monkeypatch, kwargs) -> None:
    """Context-gated per 04 §2, and stage-guarded because it holds one registry row.

    `pipeline.py` already gates the row on `request.context_docs`, so this is not the
    enforcement point — it is what keeps the detector correct when called directly, and what
    stops an empty doc list reaching `np.stack`, which raises on an empty sequence.
    """
    _stub(monkeypatch, 0.4)
    assert _detect(**kwargs) == []


def test_the_intra_op_pin_is_one_and_is_not_the_ort_constant() -> None:
    """Regression guard for the breach `eval.fault_injection`'s control probe surfaced.

    torch defaults to one thread per core and OpenMP busy-waits, so under `output_sentence`
    contention the calling thread's spin-wait landed in `time.thread_time()` as *attributable*
    CPU: 31.87 and 44.50 ms against a 30 ms budget, where the same call standalone measured
    13.9 ms. Raising this to the ORT serve constant would reintroduce that.

    The inequality is asserted deliberately: `onnx_models.SERVE_INTRA_OP_THREADS` is a
    *published measurement condition* (ADR-031/032's figures all read "6 threads available to
    one session"), so the two must not be collapsed into one knob.
    """
    from controlplane.detectors.onnx_models import SERVE_INTRA_OP_THREADS

    assert rg.GROUNDING_INTRA_OP_THREADS == 1
    assert rg.GROUNDING_INTRA_OP_THREADS != SERVE_INTRA_OP_THREADS
