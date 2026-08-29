"""`rag_grounding` — the 04 §2 performance-plane grounding check (FR-DET-003).

Embeds the sentence and the request's context documents with MiniLM and scores the sentence
by its **best** cosine similarity to any single document. 04 §2 asks for a "sentence-vs-context
embedding entailment proxy", and *proxy* is load-bearing: this is not an NLI model and does not
claim entailment, it claims lexical-semantic proximity to something the caller supplied as
source material. Budget **30 ms** per sentence, stage `output_sentence`, label
`hallucination.ungrounded_claim`, plane `performance`.

**Emits on every scored sentence, including well-grounded ones.** That is the ADR-012
confidence contract rather than an oversight: `score_kind="confidence"` means higher is
*better*, and 04 §4.3 step 2 gives the engine an explicit `above_tau_high_dropped` branch for a
score that clears `tau_high` (`policy/engine.py`). A detector-side cutoff would make that branch
unreachable and would put a threshold in Python that §9.1 and 04 §3 place in per-use-case YAML.
For the same reason this detector reads **no `detector_params`**: `tau_low`/`tau_high` already
are its thresholds, calibrated per 06 §3. It is the one registry row where "no tunables" is a
consequence of the contract instead of a gap in it.

**The span is the whole sentence** (M-44). A grounding score is a property of the sentence as a
unit — there is no sub-extent the embedding identifies as the ungrounded part — and 04 §6
`soften` rewrites exactly the span it is given. A span-less confidence signal would instead be
promoted to ESCALATE at every firing by 04 §4.3 step 4 (the ADR-015 rule that makes
`borderline_action: edit` inert for `fast_consistency`), which would make `support_bot`'s
documented `hallucination.ungrounded_claim: edit` unreachable. So the span is what makes that
policy row executable.

**Every `sentence_transformers` import is deferred inside a function**, for the ADR-033 reason
`entity_enricher` and `onnx_models` state at length: an `.[dev]`-only host must still be able to
import this module, and a module-scope import would turn "registered but unloadable" into an
unimportable gateway. Nothing enforces the deferral — a future edit hoisting it breaks the
ml-less boot with nothing noticing until a bare-host run.

**The load runs on the shared pool and is paid at boot.** `warm()` exists because a cold
`SentenceTransformer(...)` costs orders of magnitude more than 30 ms, and under ADR-036 that
cost is *attributable in-thread CPU* — a cold first sentence would breach the budget and take
the policy's `performance` fail mode. `warm_models` cannot do this: it intersects with
`onnx_models.SERVED` and this detector is not ONNX-served, so `app.py` warms it explicitly the
way it already warms `entity_enricher`.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import numpy as np

from controlplane.detectors.base import (
    DetectorError,
    Plane,
    ScoreKind,
    Signal,
    Span,
    Stage,
    budget_ms,
    run_in_executor,
)

__all__ = [
    "NAME",
    "GROUNDING_INTRA_OP_THREADS",
    "MODEL_ID",
    "LABEL",
    "RagGrounding",
    "rag_grounding",
    "warm",
    "reset_model_cache",
]

NAME = "rag_grounding"

#: 04 §2's label for this row. One label, one plane — multi-label convergence is the engine's
#: job (FR-DET-005), and a grounding score says nothing about any other plane.
LABEL = "hallucination.ungrounded_claim"

#: The MiniLM checkpoint. `02 §8` and `pyproject.toml` both say "MiniLM" without naming one,
#: which is M-51: resolved to the canonical sentence-transformers release rather than left to
#: the caller, because an unpinned name would let two hosts publish different numbers under one
#: figure. 384-dim, 6-layer — the smallest checkpoint that is a real bi-encoder, chosen for a
#: 30 ms CPU budget.
MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"

#: Context-document embeddings, keyed by exact document text. A response is many sentences over
#: one document set, so without this the docs are re-encoded per sentence and the budget pays
#: for the same work N times.
#:
#: Eviction is a full clear at the bound, not LRU. Crude on purpose: the access pattern is
#: "one doc set for the length of a request", so an LRU's bookkeeping would buy nothing that a
#: clear-and-refill does not, and the 30 ms budget has no room for cleverness. Nothing is
#: persisted or logged from here — it is process memory, the same place the model weights live.
_DOC_CACHE: dict[str, np.ndarray] = {}
_DOC_CACHE_MAX = 256

#: Intra-op threads for one grounding encode. **1, and the 6 next door is not a mistake.**
#:
#: torch defaults to one thread per core (6 measured here) and OpenMP busy-waits, so the
#: calling thread burns CPU while its workers spin. `output_sentence` runs five detectors over
#: a single-worker pool (ADR-030 Amendment 3: pool users serialize), and under that contention
#: the spin-wait lands in `time.thread_time()` as *attributable* CPU: `eval.fault_injection`'s
#: control probe measured `attributable_ms` 31.87 and 44.50 against this detector's 30 ms
#: budget, while the same call standalone measured 13.9 ms cold-doc and 6.6 ms warm-doc. Three
#: consecutive control probes came back clean at 1 thread.
#:
#: This is ADR-036's own documented caveat materializing — attributable CPU is not a
#: contention-free constant — and the fix is a thread count, not a looser budget. The budget
#: stays 30 ms and no assertion was weakened to accommodate it.
#:
#: **Deliberately NOT `onnx_models.SERVE_INTRA_OP_THREADS`.** That 6 is a *published
#: measurement condition* — ADR-031/032's figures all read "6 threads available to one
#: session" — so changing it would move numbers already in the docs. Pinning torch instead
#: costs nothing: ORT sessions take their thread count from `opts.intra_op_num_threads` and
#: are unaffected by torch's setting, and no published figure comes from this encoder yet.
#: The one cost is a marginally slower boot-time `torch.onnx.export`, which is not on a budget.
GROUNDING_INTRA_OP_THREADS = 1

_MODEL: Any = None
_LOCK = threading.Lock()


def _load_model() -> Any:
    """Return the process-wide encoder, loading it once.

    Only ever called from inside an executor task — see the module docstring. The lock makes a
    concurrent second first-call wait rather than build a second copy of the weights.
    """
    global _MODEL
    with _LOCK:
        if _MODEL is None:
            import torch  # deferred: ADR-033
            from sentence_transformers import SentenceTransformer  # deferred: ADR-033

            # Before the encoder exists, so the first encode already runs pinned. Process-global
            # and therefore stated rather than hidden — see `GROUNDING_INTRA_OP_THREADS` on why
            # that does not touch the ORT sessions or any published figure. Best-effort: torch
            # may ignore this once its pool is live (`eval/spike_tier2_models.py` records that
            # hazard), and `warm_models`' ONNX export runs first at boot, so the pin is verified
            # by `eval.fault_injection`'s control probe rather than assumed to have taken.
            torch.set_num_threads(GROUNDING_INTRA_OP_THREADS)
            _MODEL = SentenceTransformer(MODEL_ID)
        return _MODEL


def reset_model_cache() -> None:
    """Drop the encoder and the document embeddings. For tests; mirrors `onnx_models`."""
    global _MODEL
    with _LOCK:
        _MODEL = None
        _DOC_CACHE.clear()


def _encode(model: Any, texts: list[str]) -> np.ndarray:
    """Unit-normalised embeddings, one row per text.

    `normalize_embeddings=True` is what lets the similarity below be a plain dot product, so
    cosine needs no second pass and no torch tensors cross back onto the event loop.
    """
    return np.asarray(
        model.encode(texts, convert_to_numpy=True, normalize_embeddings=True),
        dtype=np.float32,
    )


def _score(text: str, docs: tuple[str, ...]) -> dict[str, Any]:
    """Best cosine similarity of `text` against any document. Runs in the executor.

    Cached documents are skipped; only the sentence and any unseen document are encoded, which
    is the difference between a first sentence and every later one.
    """
    model = _load_model()

    t0 = time.perf_counter()
    missing = [d for d in docs if d not in _DOC_CACHE]
    if missing:
        if len(_DOC_CACHE) + len(missing) > _DOC_CACHE_MAX:
            _DOC_CACHE.clear()
        for doc, row in zip(missing, _encode(model, missing)):
            _DOC_CACHE[doc] = row
    doc_matrix = np.stack([_DOC_CACHE[d] for d in docs])

    sentence = _encode(model, [text])[0]
    sims = doc_matrix @ sentence
    encode_ms = (time.perf_counter() - t0) * 1000.0

    best = int(np.argmax(sims))
    return {
        # Cosine of unit vectors is [-1, 1] while `Signal.score` is [0, 1]. A negative cosine
        # means "maximally ungrounded", and clamping cannot change a routing decision: both
        # readings sit below any `tau_low` a policy could sanely set, so the band resolves them
        # identically. The raw value is kept in `meta` so the clamp is observable, not implied.
        "score": max(0.0, float(sims[best])),
        "cosine_raw": float(sims[best]),
        "best_doc_index": best,
        "docs_encoded": len(missing),
        "encode_ms": round(encode_ms, 3),
    }


class RagGrounding:
    """04 §2 `rag_grounding`. Stateless per call; encoder and doc embeddings are process-cached."""

    name = NAME

    async def detect(self, ctx: Any) -> list[Signal]:
        """Score one sentence against the request's context documents.

        Returns `[]` when there is nothing to score against. `pipeline.py` already gates this
        row on `request.context_docs` per 04 §2 ("only when request carries context docs"), so
        the check here is not the enforcement point — it is what keeps the detector correct when
        called directly, and what stops an empty doc list from reaching `np.stack`, which raises
        on an empty sequence.
        """
        if ctx.stage is not Stage.OUTPUT_SENTENCE or not ctx.text.strip():
            return []
        docs = tuple(d for d in ctx.context_docs if d.strip())
        if not docs:
            return []

        started = time.perf_counter()
        try:
            result = await run_in_executor(_score, ctx.text, docs, detector=self.name)
        except DetectorError:
            raise
        except Exception as exc:  # load or encode failure is a runtime fault (ADR-033)
            raise DetectorError(self.name, f"grounding model unavailable: {exc}") from exc
        latency_ms = (time.perf_counter() - started) * 1000.0

        return [
            Signal(
                detector=self.name,
                planes=[Plane.PERFORMANCE],
                labels=[LABEL],
                score=round(result["score"], 4),
                score_kind=ScoreKind.CONFIDENCE,
                # Whole sentence (M-44): see the module docstring on why this is what makes
                # `hallucination.ungrounded_claim: edit` executable rather than promoted.
                span=Span(start=0, end=len(ctx.text)),
                stage=Stage.OUTPUT_SENTENCE,
                # No document text and no sentence text: a context doc is caller-supplied and
                # may carry PII, and evidence is written to the audit log (NFR-SEC-001 / §9.6 —
                # the fact and the category, never the matched value). An index identifies the
                # document without quoting it.
                evidence=(
                    f"model:{MODEL_ID} best cosine {result['cosine_raw']:.4f} "
                    f"against context doc #{result['best_doc_index']} of {len(docs)}"
                ),
                latency_ms=latency_ms,
                meta={
                    "context_docs": len(docs),
                    "best_doc_index": result["best_doc_index"],
                    "cosine_raw": round(result["cosine_raw"], 4),
                    # >0 only on a cold doc set; a steady-state sentence should read 0, which is
                    # how the cache's effect is visible in a live record rather than asserted.
                    "docs_encoded": result["docs_encoded"],
                    "encode_ms": result["encode_ms"],
                    "budget_ms": budget_ms(self.name),
                },
            )
        ]


async def warm() -> float:
    """Load the encoder and run one throwaway encode. Returns elapsed ms.

    Called at boot, for the reason the module docstring gives: under ADR-036 the load is
    attributable in-thread CPU, so paying it on the first request is a budget breach and a
    `fail_mode` firing rather than merely a slow sentence. Runs on the shared pool and returns
    the cost instead of logging it, so the caller can surface it beside the other boot timings
    (the ADR-035 item 4 shape: pay it at boot and *log* it, rather than pretend it is free).
    """
    started = time.perf_counter()
    await run_in_executor(_score, "The invoice total was thirty dollars.",
                          ("Invoices are billed monthly.",), detector=NAME)
    _DOC_CACHE.clear()  # the warm-up's document is not a caller's; do not hold it
    return (time.perf_counter() - started) * 1000.0


#: Module-level singleton, matching how `detectors/` already exposes its implementations.
rag_grounding = RagGrounding()
