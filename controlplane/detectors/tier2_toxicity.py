"""`tier2_toxicity` — single-window toxicity classifier (04 §2, ADR-031/034).

Output-sentence stage only. Emits **one** signal carrying **one** `toxicity.*` label, chosen by
two detector-internal cutoffs — 04 §2's row says "moderate vs high", a choice between the tiers
rather than both at once. Below the lower cutoff nothing is emitted: this detector is
`detection`-kind, 04 §1.2 excludes those from band logic entirely, and all three policies map
`toxicity.high: block`, so a signal on every sentence would block every response.

**One window, and why that is not the injection detector's compromise.** `tier2_injection` scans
its input with full-coverage strided windows because an attacker controls the input and can pad
before injecting — scoring one window there is a guaranteed bypass. This detector runs at
`output_sentence`, whose units come from the sentence buffer, and ADR-002's length cap
(`sentence_buffer.DEFAULT_MAX_CHARS`, 240) bounds a unit *before* it reaches any detector. 240
characters cannot fill a 104-token window, so one window is full coverage here rather than a
prefix. That premise is **reported, not assumed**: the tokenizer is asked for overflow rows and
`window_count` goes into `meta`, so a unit that ever exceeded one window would be visible in the
record instead of silently half-scanned. The condition is unreachable through the shipped
segmenter and is instrumented anyway, because "unreachable" is a claim about today's config.

**The cutoffs are the documented ones.** 04 §2: "0.5/0.8 defaults; overridable in policy
`detector_params`". The *key names* are not specified anywhere, so `cutoff_moderate` /
`cutoff_high` are a MINOR resolution logged in `08-open-questions.md` (M-50) — chosen to read as
the tiers they gate, and validated: non-numeric, out-of-range, or inverted cutoffs raise rather
than falling back to defaults, because a use case that meant to loosen this and mistyped it would
otherwise run at a threshold its YAML does not state.

**Budget.** 04 §2 gives this detector <25 ms per call (flat, not parametric — the unit is already
bounded, so there is nothing for a length-parametric ceiling to track). Inference runs on the
shared single-worker pool via `run_in_executor`, never inline (04 §2.1(a)). ADR-031 measured this
checkpoint at the segmenter cap and at corpus lengths; **SL-5's concurrency caveat applies
unchanged** and is not restated here.

No span. `toxicity.*` is not in `EDIT_ELIGIBLE_LABELS` — 04 §6 defines no transform for it — so
there is nothing a span would be used to rewrite, and the unit scored *is* the sentence.
"""

from __future__ import annotations

import time
from typing import Any

from controlplane.detectors.base import (
    DetectorError,
    Plane,
    ScoreKind,
    Signal,
    Stage,
    budget_ms,
    run_in_executor,
)
from controlplane.detectors.onnx_models import SERVED, load_classifier
from controlplane.detectors.windowing import WINDOW_TOKENS

#: ADR-031's pick and its positive label name — read from `onnx_models.SERVED`, never restated.
#: `warm_models` builds from that table at boot, so a second copy here would be a checkpoint the
#: detector serves and the warm-up does not build.
MODEL_ID, POSITIVE_LABELS = SERVED["tier2_toxicity"]

#: 04 §2's documented defaults.
DEFAULT_CUTOFF_MODERATE = 0.5
DEFAULT_CUTOFF_HIGH = 0.8

#: Policy override keys inside `detector_params["tier2_toxicity"]` (04 §3). Names are M-50.
PARAM_MODERATE = "cutoff_moderate"
PARAM_HIGH = "cutoff_high"


def _score(handle: Any, text: str) -> dict[str, Any]:
    """Tokenize to one window, run one inference, return the positive-class probability.

    One executor task for the whole call, matching `tier2_injection`: handing the pool a task
    per step would interleave two requests' work and put each on conditions no figure in this
    repo describes.
    """
    import numpy as np

    t0 = time.perf_counter()
    enc = handle.tokenizer(
        text,
        truncation=True,
        max_length=WINDOW_TOKENS,
        return_overflowing_tokens=True,   # counted, not scored — see the module docstring
        padding="max_length",
        return_tensors="np",
    )
    tokenize_ms = (time.perf_counter() - t0) * 1000.0

    window_count = int(enc["input_ids"].shape[0])
    if window_count == 0:
        # A tokenizer always emits at least CLS/SEP for non-empty text, so this is unreachable;
        # a bare index would surface as an opaque error rather than something the 04 §5 fail_mode
        # path can resolve. Faulting names the condition.
        raise DetectorError("tier2_toxicity", "tokenizer produced no windows for non-empty text")

    feed = {
        name: enc[name][0:1].astype(np.int64) for name in handle.fed if name in enc
    }
    t1 = time.perf_counter()
    logits = handle.session.run(None, feed)[0]
    infer_ms = (time.perf_counter() - t1) * 1000.0

    arr = np.asarray(logits, dtype=np.float64)
    shifted = arr - arr.max(axis=-1, keepdims=True)
    exp = np.exp(shifted)
    probs = exp / exp.sum(axis=-1, keepdims=True)

    return {
        "score": float(probs[0, handle.positive_index]),
        "window_count": window_count,
        "tokenize_ms": round(tokenize_ms, 3),
        "infer_ms": round(infer_ms, 3),
    }


class Tier2Toxicity:
    """04 §2 `tier2_toxicity`. Stateless per call; the graph is process-cached."""

    name = "tier2_toxicity"

    def _cutoffs(self, ctx: Any) -> tuple[float, float]:
        """Resolved (moderate, high). Raises on anything a policy could mean but mistype."""
        params = ctx.params_for(self.name)
        out: list[float] = []
        for key, default in ((PARAM_MODERATE, DEFAULT_CUTOFF_MODERATE),
                             (PARAM_HIGH, DEFAULT_CUTOFF_HIGH)):
            raw = params.get(key, default)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise DetectorError(
                    self.name,
                    f"detector_params[{self.name!r}][{key!r}] must be a number, "
                    f"got {type(raw).__name__}",
                )
            if not 0.0 <= float(raw) <= 1.0:
                raise DetectorError(
                    self.name,
                    f"{key} {raw} is outside [0, 1]: the score it gates is a probability",
                )
            out.append(float(raw))
        moderate, high = out
        if moderate > high:
            raise DetectorError(
                self.name,
                f"{PARAM_MODERATE} ({moderate}) exceeds {PARAM_HIGH} ({high}): the tiers "
                "would invert, and every sentence above the lower bar would be labelled high",
            )
        return moderate, high

    async def detect(self, ctx: Any) -> list[Signal]:
        """Score one sentence; emit at most one signal, labelled by the tier it reaches."""
        if ctx.stage is not Stage.OUTPUT_SENTENCE or not ctx.text.strip():
            return []

        moderate, high = self._cutoffs(ctx)
        started = time.perf_counter()
        try:
            handle = load_classifier(MODEL_ID, POSITIVE_LABELS)
        except Exception as exc:                     # graph build is a runtime fault (ADR-033)
            raise DetectorError(self.name, f"model unavailable: {exc}") from exc

        result = await run_in_executor(_score, handle, ctx.text, detector=self.name)
        latency_ms = (time.perf_counter() - started) * 1000.0

        score = result["score"]
        if score < moderate:
            return []
        label = "toxicity.high" if score >= high else "toxicity.moderate"

        return [
            Signal(
                detector=self.name,
                planes=[Plane.RESPONSIBILITY],
                labels=[label],
                score=round(score, 4),
                score_kind=ScoreKind.DETECTION,
                span=None,                # not edit-eligible; the unit scored is the sentence
                stage=Stage.OUTPUT_SENTENCE,
                evidence=(
                    f"model:{MODEL_ID} score at or above "
                    f"{'high' if score >= high else 'moderate'} cutoff "
                    f"{high if score >= high else moderate}"
                ),
                latency_ms=latency_ms,
                meta={
                    "cutoff_moderate": moderate,
                    "cutoff_high": high,
                    # 1 under the ADR-002 segmenter cap. Recorded so the single-window premise
                    # is observable in a live record rather than trusted.
                    "window_count": result["window_count"],
                    "infer_ms": result["infer_ms"],
                    "tokenize_ms": result["tokenize_ms"],
                    "budget_ms": budget_ms(self.name),
                },
            )
        ]


#: Module-level singleton, matching how `detectors/` already exposes its implementations.
tier2_toxicity = Tier2Toxicity()
