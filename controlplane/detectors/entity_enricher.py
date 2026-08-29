"""`entity_enricher` enrichment stage (ADR-011, 04 §2.2).

spaCy `en_core_web_sm` NER over span-bearing `hallucination.*` signals; a PERSON entity
appends `privacy.person` to `labels` and `responsibility` to `planes` of the **same**
signal (one-signal rule, FR-DET-005). Budget **10 ms aggregate per sentence**. Enrichment
failure skips and logs; it never blocks and is not a policy `fail_mode` class — which is
why `DETECTOR_FAIL_CLASS` omits it and `fail_class_for` raises on the name (ADR-033
consequence 6).

**Not a `Detector`, deliberately.** 04 §2.2 makes enrichment its own stage between
detection and the policy engine, so this module exposes `enrich()` rather than
`detect(ctx)`: it *consumes* signals and returns amended ones, where a detector produces
signals from text. `LANES` rightly has no row for it and `LIVE` no entry, and forcing it
into the `Detector` type to reach a boot-manifest side effect would be a type lie in
service of a side effect — `app._probe_scope()` names it explicitly instead.

**Every spaCy import is deferred inside a function.** An `.[dev]`-only host must be able to
import this module: ADR-033's third lifecycle state is "registered but unloadable", and a
module-scope `import spacy` would turn an unloadable stage into an unimportable gateway —
the failure ADR-033 exists to avoid. Same reasoning as `onnx_models`, and the same unguarded
detail: nothing enforces the deferral here, so a future edit hoisting the import would break
the ml-less boot with nothing noticing until a bare-host run.

**The load runs on the shared pool, not the event loop.** `import spacy` measured 1488 ms
and `spacy.load` a further 348 ms on the verified toolchain — three orders of magnitude past
a 10 ms budget. Doing that lazily on the loop is M-39 verbatim, so `_load_nlp` is only ever
called from inside an executor task, and `warm()` exists to pay it at boot instead of on a
request. A cold first sentence is therefore *slow but correct*: it exceeds, logs, counts and
skips, exactly as §2.2 specifies — it does not silently block the loop.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from controlplane.detectors.base import (
    BUDGETS_MS,
    ENRICHED_LABELS_KEY,
    Plane,
    Signal,
    run_in_executor,
)

_LOG = logging.getLogger(__name__)

#: 04 §2 registry name. The `REQUIREMENTS`, `BUDGETS_MS` and metric-label key.
NAME = "entity_enricher"

#: The host labels this stage visits (04 §2.2: "each span-bearing `hallucination.*` signal").
HOST_LABEL_PREFIX = "hallucination."

#: What a PERSON entity appends. In `ENRICHED_ONLY_LABELS`, so ADR-019 makes recording it in
#: `meta.enriched_labels` a construction-time requirement rather than a convention.
APPENDED_LABEL = "privacy.person"

#: The spaCy entity type that triggers the append. 04 §2.2 names PERSON and nothing else.
PERSON = "PERSON"

#: 04 §2.2 budget, read from the transcribed table rather than restated — a second copy of a
#: spec constant is a second thing to drift (M-35).
BUDGET_MS = BUDGETS_MS[NAME]

#: Reasons for `cp_enrichment_skipped_total{use_case,reason}` (04 §2.2, 05 §5). Two causes for
#: one countable fact — "enrichment was skipped" — rather than two half-visible ones.
REASON_BUDGET = "budget_exceeded"
REASON_FAILURE = "enrichment_failure"

#: Pipes excluded at load. NER is the only component 04 §2.2 uses, and excluding the rest is
#: strictly better on both axes that matter here: load 223 ms vs 310 ms and NER p50 3.45 ms vs
#: 4.23 ms on the verified toolchain, with PERSON entities identical. `ner` and `tok2vec` stay —
#: excluding `tok2vec` would leave NER without its features.
EXCLUDED_PIPES = ("parser", "tagger", "attribute_ruler", "lemmatizer", "senter")

_NLP: Any = None
_NLP_LOCK = threading.Lock()

#: Sentence terminator for the window. A **local** copy, like `tier1_patterns` and
#: `numeric_claims` each carry: the gateway's `sentence_buffer` owns real segmentation, and
#: three call sites agreeing by accident is a smaller risk than three modules coupled through
#: one.
_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")


def _sentence_window(text: str, start: int, end: int) -> str:
    """The sentence containing `[start, end)` — the "± its sentence window" of 04 §2.2."""
    left = 0
    for match in _SENTENCE_END.finditer(text, 0, start):
        left = match.end()
    right_match = _SENTENCE_END.search(text, end)
    right = right_match.end() if right_match else len(text)
    return text[left:right]


def is_enrichment_target(signal: Signal) -> bool:
    """Whether 04 §2.2 visits `signal`: span-bearing, with a `hallucination.*` label.

    Exported rather than inlined at each caller, and this is the one place in this module
    where sharing beats copying: `pipeline.enrich_lane` asks the *same* question to
    decide whether enrichment was **expected** (the 05 §4 coverage column). If the two
    predicates disagreed, the audit record would claim a gap for a signal the enricher
    visited, or stay silent about one it skipped — a column that lies rather than a helper
    that duplicates.
    """
    return signal.span is not None and any(
        label.startswith(HOST_LABEL_PREFIX) for label in signal.labels
    )


def _load_nlp() -> Any:
    """The process-wide NER pipeline, loaded once. **Executor-thread only** (see module doc).

    Cached because the load is hundreds of milliseconds against a 10 ms budget. The lock is
    held across the load, not just the assignment: two concurrent first calls would otherwise
    each build a pipeline, and serializing the slow path costs the second caller a wait it was
    going to pay anyway — the `load_classifier` precedent.
    """
    global _NLP
    with _NLP_LOCK:
        if _NLP is None:
            import spacy  # deferred: see module docstring

            _NLP = spacy.load("en_core_web_sm", exclude=list(EXCLUDED_PIPES))
        return _NLP


def _has_person(nlp: Any, window: str) -> bool:
    return any(ent.label_ == PERSON for ent in nlp(window).ents)


def _scan_windows(windows: tuple[str, ...]) -> tuple[tuple[bool, ...], int]:
    """PERSON-per-window, stopping when the aggregate budget is spent. Runs on the pool.

    Returns `(flags, skipped)` where `flags` aligns with the windows actually visited and
    `skipped` counts those left unenriched. **One executor task for the whole sentence**, the
    `tier2_injection._scan` shape: the budget is a per-sentence aggregate (M-18), so it has to
    be checked *between* windows, and doing that inside one task costs one queue wait instead
    of one per span.

    The budget is enforced here rather than by `asyncio.wait_for`, because 04 §2.2 specifies
    stop-and-log, not a raised fault: enrichment is not a `fail_mode` class, so there is
    nothing for a timeout to resolve *to*. Enforcing inline also means no abandoned-task tail
    — the ADR-034 hazard does not arise for this stage at all.

    The check is **after** each window, so the first span is always attempted: a budget that
    could enrich nothing at all would make the stage unreachable on a cold pipeline rather
    than merely slow. A window's own cost is unbounded by design — M-18 ruled the budget
    aggregate, which bounds the count, not any single inference.
    """
    started = time.perf_counter()
    nlp = _load_nlp()
    flags: list[bool] = []
    for index, window in enumerate(windows):
        flags.append(_has_person(nlp, window))
        spent_ms = (time.perf_counter() - started) * 1000.0
        remaining = len(windows) - (index + 1)
        if spent_ms >= BUDGET_MS and remaining:
            return tuple(flags), remaining
    return tuple(flags), 0


def _enriched(signal: Signal) -> Signal:
    """`signal` with `privacy.person` + `responsibility` appended and recorded (ADR-019).

    Rebuilt through `model_validate`, never `model_copy`: `model_copy` bypasses validation,
    and the ADR-019 contract check lives in the model precisely so a malformed enriched
    signal cannot be constructed. Copying past it would leave the one guarantee §4.3 step 2
    depends on — that every appended label is recorded — enforced nowhere.
    """
    payload = signal.model_dump()
    payload["labels"] = [*signal.labels, APPENDED_LABEL]
    if Plane.RESPONSIBILITY not in signal.planes:
        payload["planes"] = [*signal.planes, Plane.RESPONSIBILITY]
    recorded = list(signal.meta.get(ENRICHED_LABELS_KEY) or ())
    payload["meta"] = {**signal.meta, ENRICHED_LABELS_KEY: [*recorded, APPENDED_LABEL]}
    return Signal.model_validate(payload)


async def warm() -> float:
    """Load the pipeline and run one throwaway inference. Returns elapsed ms.

    Called at boot. **The throwaway inference is not optional:** the load alone leaves the
    first real NER call at a measured 11.76 ms, over the 10 ms budget on its own, because
    spaCy defers work to first use. Warming without it would move the cost rather than
    remove it, and the first enriched sentence of the process would exceed and skip.

    Runs on the shared pool for the same reason every other call here does, and returns the
    cost instead of logging it, so the caller can surface it beside the other boot timings
    (the ADR-035 item 4 shape: pay it at boot and *log* it, rather than pretend it is free).
    """
    def _warm() -> None:
        _has_person(_load_nlp(), "Ada Lovelace wrote the first program.")

    started = time.perf_counter()
    await run_in_executor(_warm, detector=NAME)
    return (time.perf_counter() - started) * 1000.0


async def enrich(
    signals: list[Signal], text: str, *, use_case: str, metrics: Any = None
) -> list[Signal]:
    """The 04 §2.2 stage. Returns `signals` with PERSON-bearing hosts enriched.

    Order and identity are preserved: an enriched signal is the *same* signal with two
    appends (FR-DET-005's one-signal rule), never an additional one. Signals this stage does
    not visit are returned untouched.

    Never raises. Any failure is caught, logged and counted under
    `cp_enrichment_skipped_total{reason="enrichment_failure"}`, and the original signals are
    returned — 04 §2.2 makes enrichment's absence remove a possible escalation, never a
    delivery. That includes an unloadable spaCy: this is the stage's ml-less behaviour, and
    it is a skip rather than a boot refusal because enrichment has no `fail_mode` class.

    Nothing derived from the checked text is logged — not the window, not the entity, not an
    exception message (NFR-SEC-001). Counts and the exception *class* only: a spaCy error can
    quote the very sentence under check, and this stage exists to label content about
    identifiable people.
    """
    targets = [(index, s) for index, s in enumerate(signals) if is_enrichment_target(s)]
    if not targets:
        return list(signals)

    windows = tuple(
        _sentence_window(text, s.span.start, s.span.end)  # type: ignore[union-attr]
        for _, s in targets
    )
    try:
        flags, skipped = await run_in_executor(_scan_windows, windows, detector=NAME)
    except Exception as exc:  # noqa: BLE001 — never blocks (04 §2.2)
        _LOG.warning(
            "entity_enricher skipped for %d signal(s): %s", len(targets), type(exc).__name__
        )
        _count_skip(metrics, use_case, REASON_FAILURE, len(targets))
        return list(signals)

    enriched = list(signals)
    for (index, signal), has_person in zip(targets, flags):
        if has_person and APPENDED_LABEL not in signal.labels:
            enriched[index] = _enriched(signal)

    if skipped:
        _LOG.info(
            "entity_enricher budget %.1f ms exhausted; %d span(s) left unenriched",
            BUDGET_MS,
            skipped,
        )
        _count_skip(metrics, use_case, REASON_BUDGET, skipped)
    return enriched


def _count_skip(metrics: Any, use_case: str, reason: str, count: int) -> None:
    """Increment `cp_enrichment_skipped_total{use_case,reason}` by the spans actually skipped.

    Counted per skipped span, not per sentence: "how much enrichment was lost" is the
    quantity 04 §2.2 attaches the counter to, and a per-call increment would report one
    sentence that lost eight spans identically to one that lost one.

    A run that overshoots the budget on its **last** span increments nothing, which is
    deliberate: this counter says *skipped*, and nothing was. The overshoot is still visible
    as latency; inventing a skip that did not happen would make the counter unusable as a
    coverage figure.
    """
    if metrics is None or not count:
        return
    metrics.increment(
        "cp_enrichment_skipped_total", float(count), use_case=use_case, reason=reason
    )
