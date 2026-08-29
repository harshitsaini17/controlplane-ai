"""`tier2_injection` — strided-window prompt-injection classifier (04 §2, ADR-031/032/034).

Input stage only. Scores the **whole** input by slicing it into overlapping 104-token windows
and taking the **MAX** over them, so no prefix is privileged and there is no 512-token blind
spot: scoring only the first window would make pad-then-inject a guaranteed bypass, which is the
attack the full-coverage geometry (ADR-032) exists to close.

**Why a cutoff exists at all, and where it comes from.** This detector is `detection`-kind, and
04 §1.2 is explicit that band logic **never applies** to those — `evaluate()` reads
`banded = signal.score_kind is ScoreKind.CONFIDENCE`, so the engine never consults a
detection-kind score. All three shipped policies map `security.prompt_injection: block`.
A detector that emitted a signal for every input would therefore **block every request**,
including every benign beat of the demo. So the firing decision has to live here. 04 §2's row
for this detector does not state a cutoff, but the row *directly beside it* does for the same
class of model — `tier2_toxicity`: "detector-internal cutoffs (0.5/0.8 defaults; overridable in
policy `detector_params`)". That is the precedent this follows: `DEFAULT_CUTOFF = 0.5`,
overridable per use case. Logged as a MINOR resolution rather than invented freely.

**The per-window budget is enforced structurally, not by a timer.** 04 §2 budgets this detector
at "<25 ms **per 104-token window**, enforced **inside** the detector". The enforcement is the
windowing itself: cost is fixed by tensor *shape*, not by which words fill it (ADR-032's series
is measured on synthetic filler for exactly that reason), so handing the model a 104-token window
is what keeps one inference inside its budgeted cost. A timer here would be the wrong instrument
twice over — Python cannot preempt a running `sess.run` (04 §2.1(a): a timed-out task is
"abandoned, not killed"), so a per-window deadline could only ever fire *after* the window it
was meant to bound; and ADR-034 already assigns the fault path to the **runner's** parametric
ceiling, whose stated meaning is "materially slower than its own measured envelope". Adding a
second, tighter timer inside would re-introduce the fail-mode pathology ADR-034 dissolved —
under contention SL-5 measures a single window at 49.77 ms, so an inner 25 ms deadline would
fault *every* request, blocking everything under `fail_closed` and skipping everything under
`fail_open`. Per-window cost is therefore **measured and reported** (`meta`, and
`cp_detector_latency_ms`), and the ceiling is what faults. The alternative reading — inner
deadline raising `DetectorTimeout` — is recorded in `08-open-questions.md` as the rejected one.

**Batch 2**, per ADR-032 Correction 2: the resolved minimum at the 4000-token bound in both
statistics and at both thread settings. The earlier batch-4 binding was withdrawn when the
justifying gap turned out to be real in medians (+0.96%) and absent in tails (+11.4%).

**6 intra-op threads**, per `onnx_models.SERVE_INTRA_OP_THREADS` — the condition ADR-032 states
once for every figure it publishes. SL-5's caveat is unchanged and is not restated here.
"""

from __future__ import annotations

import time
from typing import Any

from controlplane.detectors.base import (
    Plane,
    ScoreKind,
    Signal,
    Stage,
    budget_ms,
    run_in_executor,
)
from controlplane.detectors.base import DetectorError
from controlplane.detectors.onnx_models import SERVED, load_classifier
from controlplane.detectors.windowing import WINDOW_OVERLAP, WINDOW_TOKENS

#: ADR-031's pick and the label names meaning "injection is present" — **read from
#: `onnx_models.SERVED`, not restated here.** Both are spec constants on the same footing as a
#: budget (04 §2 says "small transformer, CPU/ONNX"; ADR-031 resolved *which* one), so they
#: belong in one transcribed table the way `BUDGETS_MS`, `REQUIREMENTS` and
#: `DETECTOR_FAIL_CLASS` each do. `warm_models` builds from that table at boot, and a second
#: copy here would be a checkpoint the detector serves but the warm-up does not build — the
#: lazy-build defect back in a quieter form. The positive set is a **set** because ADR-031's
#: four injection candidates disagree on vocabulary (`['benign','jailbreak']` vs
#: `['SAFE','INJECTION']`); `onnx_models.positive_index_for` explains why resolving by position
#: would be a silent inversion rather than a crash.
MODEL_ID, POSITIVE_LABELS = SERVED["tier2_injection"]

#: Rows per `sess.run` call. ADR-032 Correction 2.
BATCH_ROWS = 2

#: Firing cutoff on the MAX-over-windows probability. `tier2_toxicity`'s documented default,
#: applied to this detector's single label — see the module docstring for the precedent.
DEFAULT_CUTOFF = 0.5

#: Policy override key inside `detector_params["tier2_injection"]` (04 §3).
CUTOFF_PARAM = "cutoff"


def _softmax_positive(logits: Any, index: int) -> list[float]:
    """Per-row probability of the positive class. Stable softmax over the last axis."""
    import numpy as np

    arr = np.asarray(logits, dtype=np.float64)
    shifted = arr - arr.max(axis=-1, keepdims=True)
    exp = np.exp(shifted)
    probs = exp / exp.sum(axis=-1, keepdims=True)
    return [float(p) for p in probs[:, index]]


def _tokenize_windows(text: str, tokenizer: Any) -> Any:
    """Slice `text` into padded, overlapping windows — the same call the harness times.

    `padding="max_length"` keeps every batch rectangular (a ragged batch cannot be one tensor)
    and makes each window cost what a full one costs. That is deliberately the worst case: a real
    last window is shorter and cheaper, so the measured figures never flatter the implementation.
    """
    return tokenizer(
        text,
        truncation=True,
        max_length=WINDOW_TOKENS,
        stride=WINDOW_OVERLAP,
        return_overflowing_tokens=True,
        padding="max_length",
        return_tensors="np",
    )


def _scan(handle: Any, text: str) -> dict[str, Any]:
    """Tokenize, run every window in batches of `BATCH_ROWS`, and return the MAX.

    Runs **on the shared single-worker pool** via the caller's `run_in_executor` — never inline
    on the event loop (04 §2.1(a)). One function per call so the whole scan is one executor task:
    handing the pool one task per batch would interleave two requests' windows and put each on
    conditions no figure in this repo describes.
    """
    import numpy as np

    t0 = time.perf_counter()
    enc = _tokenize_windows(text, handle.tokenizer)
    tokenize_ms = (time.perf_counter() - t0) * 1000.0

    rows = int(enc["input_ids"].shape[0])
    scores: list[float] = []
    infer_ms = 0.0
    for start in range(0, rows, BATCH_ROWS):
        feed = {
            name: enc[name][start : start + BATCH_ROWS].astype(np.int64)
            for name in handle.fed
            if name in enc
        }
        t1 = time.perf_counter()
        logits = handle.session.run(None, feed)[0]
        infer_ms += (time.perf_counter() - t1) * 1000.0
        scores.extend(_softmax_positive(logits, handle.positive_index))

    if not scores:
        # Unreachable for non-empty text (a tokenizer always emits at least CLS/SEP), but a
        # bare `max(range(0))` would surface as an opaque ValueError rather than something the
        # 04 §5 fail_mode path can resolve. Faulting names the condition.
        raise DetectorError("tier2_injection", "tokenizer produced no windows for non-empty text")
    best = max(range(len(scores)), key=scores.__getitem__)
    return {
        "window_count": rows,
        "max_window_index": best,
        "score": scores[best],
        "tokenize_ms": round(tokenize_ms, 3),
        "infer_ms": round(infer_ms, 3),
        "per_window_ms": round(infer_ms / rows, 3) if rows else 0.0,
    }


class Tier2Injection:
    """04 §2 `tier2_injection`. Stateless per call; the graph is process-cached."""

    name = "tier2_injection"

    def _cutoff(self, ctx: Any) -> float:
        """Resolved cutoff. Narrows the widened `ParamValue` union at the call site.

        A non-numeric override is a **policy** error, not something to silently fall back
        from: a use case that meant to loosen this and typed it wrong would otherwise run at
        the default while its YAML claimed otherwise.
        """
        raw = ctx.params_for(self.name).get(CUTOFF_PARAM, DEFAULT_CUTOFF)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise DetectorError(
                self.name,
                f"detector_params[{self.name!r}][{CUTOFF_PARAM!r}] must be a number, "
                f"got {type(raw).__name__}",
            )
        if not 0.0 <= float(raw) <= 1.0:
            raise DetectorError(
                self.name,
                f"cutoff {raw} is outside [0, 1]: the score it gates is a probability",
            )
        return float(raw)

    async def detect(self, ctx: Any) -> list[Signal]:
        """Score the input; emit at most one signal, and only at or above the cutoff."""
        if ctx.stage is not Stage.INPUT or not ctx.text.strip():
            return []

        cutoff = self._cutoff(ctx)
        started = time.perf_counter()
        try:
            handle = load_classifier(MODEL_ID, POSITIVE_LABELS)
        except Exception as exc:                     # graph build is a runtime fault (ADR-033)
            raise DetectorError(self.name, f"model unavailable: {exc}") from exc

        result = await run_in_executor(_scan, handle, ctx.text, detector=self.name)
        latency_ms = (time.perf_counter() - started) * 1000.0

        if result["score"] < cutoff:
            return []

        return [
            Signal(
                detector=self.name,
                planes=[Plane.RESPONSIBILITY],
                labels=["security.prompt_injection"],
                score=round(result["score"], 4),
                score_kind=ScoreKind.DETECTION,
                span=None,                            # 04 §2 puts the location in `meta`
                stage=Stage.INPUT,
                evidence=(
                    f"model:{MODEL_ID} window {result['max_window_index'] + 1}"
                    f"/{result['window_count']} at or above cutoff {cutoff}"
                ),
                latency_ms=latency_ms,
                meta={
                    # 04 §2 registry row, verbatim: "window_count + max-window index in meta".
                    "window_count": result["window_count"],
                    "max_window_index": result["max_window_index"],
                    "cutoff": cutoff,
                    # Per-window inference cost — the **mean** over this request's windows,
                    # NOT a percentile. One request yields one sample per window and a P99 needs
                    # a population, so this makes the 04 §2 budget observable from a live record
                    # without claiming to be the statistic the budget is stated in. Tokenization
                    # is reported separately because ADR-032's table excludes it (it times
                    # `sess.run` only) and 04 §2.1's span disclosure requires any published
                    # figure for this detector to state which spans it covers.
                    "per_window_ms": result["per_window_ms"],
                    "tokenize_ms": result["tokenize_ms"],
                    "budget_per_window_ms": budget_ms(self.name),
                },
            )
        ]


#: Module-level singleton, matching how `detectors/` already exposes its implementations.
tier2_injection = Tier2Injection()
