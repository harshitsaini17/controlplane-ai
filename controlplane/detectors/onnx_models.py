"""Graph provisioning for the ONNX-served model detectors (ADR-031, ADR-035).

**One definition of "the served graph."** ADR-032's window figures have to describe the same
graph ADR-031 picked, and two export paths would eventually differ in opset, axes or quant
settings — at which point the two ADRs' numbers would silently stop being comparable. The
export lived in `eval/spike_tier2_models.py` because the harnesses were written first; it moves
here for the reason M-35 records for the window geometry: **the harness measures the
implementation, so the implementation cannot depend on the harness.** The spike now imports and
re-exports `build_onnx_session`, so both read one definition.

**Every ml import is deferred inside a function, deliberately.** An `.[dev]`-only host must be
able to *import* this module and register the detectors that need it — ADR-033's third lifecycle
state is "registered but unloadable", and `availability.probe_availability` is what turns that
into a boot manifest. A module-scope `import onnxruntime` here would turn an unloadable detector
into an unimportable gateway, which is the failure ADR-033 exists to avoid. Unguarded detail
worth knowing: nothing enforces the deferral in *this* module, so a future edit hoisting one
import would break the ml-less boot with nothing noticing until a bare-host run.

**No graph is cached in the repo** (ADR-031): a checked-in binary is an artifact whose
provenance nobody can check. ADR-035 item 4 keeps build-at-boot and **logs the cost** rather
than caching it, so `ModelHandle.build_ms` is measured and surfaced beside the FR-GW-006
canary line at startup.
"""

from __future__ import annotations

import logging
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

#: Intra-op threads for one served inference.
#:
#: **6, because that is the condition every budget in 04 §2 was measured under** — ADR-032
#: states it once for all its figures: "All figures are CPU int8 with 6 threads available to one
#: inference." The shared pool is `max_workers=1` (ADR-034 Part A), so exactly one inference is
#: in flight and it gets all six; serving at 1 would put the hot path on the column where a
#: *single* 104-token window costs 49.77 / 50.76 ms and breaches its own 25 ms per-window budget
#: outright. The pessimistic column is not thereby ignored — ADR-034 grounds the runner's
#: *ceiling* on it, so the two tiers disagree on purpose: the inner budget describes the
#: conditions we serve under, the outer ceiling survives losing them (SL-5).
SERVE_INTRA_OP_THREADS = 6

#: Kept alive for the process, not deleted after use like the harness's workdir: the session
#: mmaps its graph file, so unlinking it under a live `InferenceSession` is a use-after-free
#: waiting for a page fault. The harness can delete because it closes the session first.
_WORKDIRS: list[Any] = []
_CACHE: dict[tuple[str, int], "ModelHandle"] = {}
_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class ModelHandle:
    """A provisioned classifier: the session, its tokenizer, and the provenance to report."""

    model_id: str
    session: Any
    tokenizer: Any
    #: Input names the graph actually declares — `token_type_ids` is present for some
    #: checkpoints and absent for others, so feeding a fixed triple fails on half of them.
    fed: tuple[str, ...]
    #: Logit column meaning "the problem is present", resolved from `id2label` BY NAME.
    positive_index: int
    positive_label: str
    #: ADR-035 item 4's startup figure: the **end-to-end** build — `from_pretrained`, export,
    #: quantize AND session open, because this field wraps the whole of `build_onnx_session`.
    #: Named precisely because ADR-035 **withdrew** the narrower reading: its deviation report
    #: cited *"~4.6 s (1.76 export + 2.85 quantize)"*, and the correction records that the span a
    #: booting host actually pays "also includes `from_pretrained` and opening the ORT session"
    #: — measured **9.6-10.1 s per checkpoint**. Describing this as "export + quantize + session
    #: open" would have labelled it with the retracted span, which is how a figure loses its
    #: derivation while still looking sourced.
    build_ms: float
    params_m: float = 0.0
    graph_mb: float = 0.0
    labels: tuple[str, ...] = field(default_factory=tuple)


def positive_index_for(id2label: dict[int, str], positive_names: frozenset[str]) -> tuple[int, str]:
    """Resolve the positive logit column by **label name**, never by position.

    ADR-031 evaluated four injection checkpoints and they do not agree on vocabulary:
    `madhurjindal` and `jackhhao` report `['benign', 'jailbreak']`, `protectai` reports
    `['SAFE', 'INJECTION']`. Both happen to put the positive class at index 1 *today*, which is
    exactly what makes a hardcoded `1` dangerous — it would keep working, silently, right up
    until a checkpoint that orders them the other way inverts the detector into a
    machine that flags benign traffic and passes attacks. A wrong answer here is not a crash,
    it is a plausible-looking score, so this raises on anything ambiguous rather than guessing.
    """
    matches = [(i, name) for i, name in sorted(id2label.items()) if name.lower() in positive_names]
    if not matches:
        raise ValueError(
            f"none of {sorted(positive_names)} appears in id2label={id2label}: the positive "
            "class cannot be resolved by name, and positional guessing would silently invert "
            "the detector"
        )
    if len(matches) > 1:
        raise ValueError(
            f"{[m[1] for m in matches]} all match {sorted(positive_names)} in id2label="
            f"{id2label}: ambiguous, so no column can be called *the* positive one"
        )
    return matches[0]


def build_onnx_session(model_id: str, threads: int, workdir: Path,
                       quantized: bool = True) -> dict[str, Any]:
    """Export `model_id` to ONNX, optionally int8-quantize, and open a CPU session.

    Extracted so that **one** definition of "the served graph" covers every harness that
    measures these checkpoints, and now the serve path too. Two export paths would eventually
    differ in opset, axes or quant settings, and ADR-031's pick and ADR-032's window series
    would stop describing the same object.

    The export happens here rather than being cached in the repo: a checked-in graph would be a
    binary artifact whose provenance nobody could check, and the export costs ~2 s. **Callers
    own `workdir`** — the harness deletes it after closing its session (six fp32 graphs are
    ~1.6 GB and the measuring machine has less), the serve path keeps it for the process
    lifetime because a live session mmaps the file it was opened from.

    Returns the session and tokenizer alongside the provenance an artifact should record
    (parameter count, graph size, export and quantization cost).
    """
    import onnxruntime as ort
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    out: dict[str, Any] = {"model_id": model_id}
    tok = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForSequenceClassification.from_pretrained(model_id)
    model.eval()
    out["params_m"] = round(sum(p.numel() for p in model.parameters()) / 1e6, 1)
    out["id2label"] = dict(getattr(model.config, "id2label", {}))
    out["labels"] = list(out["id2label"].values())[:6]

    sample = tok("a sentence long enough to trace the graph", return_tensors="pt")
    names = [n for n in ("input_ids", "attention_mask", "token_type_ids") if n in sample]
    axes: dict[str, dict[int, str]] = {n: {0: "b", 1: "s"} for n in names}
    axes["logits"] = {0: "b"}

    fp32 = workdir / "model.onnx"
    t0 = time.perf_counter()
    torch.onnx.export(
        model, tuple(sample[n] for n in names), str(fp32),
        input_names=names, output_names=["logits"], dynamic_axes=axes,
        opset_version=17, do_constant_folding=True, dynamo=False,
    )
    out["export_s"] = round(time.perf_counter() - t0, 2)

    graph = fp32
    if quantized:
        int8 = workdir / "model_int8.onnx"
        t0 = time.perf_counter()
        quantize_dynamic(str(fp32), str(int8), weight_type=QuantType.QInt8)
        out["quantize_s"] = round(time.perf_counter() - t0, 2)
        fp32.unlink()                      # peak disk: one graph at a time
        graph = int8
    out["graph_mb"] = round(graph.stat().st_size / 1e6, 1)

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = 1
    out["session"] = ort.InferenceSession(str(graph), opts, providers=["CPUExecutionProvider"])
    out["tokenizer"] = tok
    out["fed"] = [i.name for i in out["session"].get_inputs()]
    return out


def load_classifier(model_id: str, positive_names: frozenset[str], *,
                    threads: int = SERVE_INTRA_OP_THREADS) -> ModelHandle:
    """Provision `model_id` once per process and return the cached handle.

    Cached because the build is seconds and the graph is immutable; keyed on `threads` too, so a
    harness asking for the 1-thread column never receives the serve-path session by accident —
    the whole of SL-5 is the gap between those two columns.

    The lock is held across the *build*, not just the dict write. Two concurrent first requests
    would otherwise each export ~250 MB of fp32 graph and race on the same workdir; serializing
    the slow path costs the second caller a wait it was going to pay anyway.
    """
    key = (model_id, threads)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return cached

        workdir = tempfile.TemporaryDirectory(prefix="cp_onnx_")
        _WORKDIRS.append(workdir)          # lifetime = process; the session mmaps its graph
        t0 = time.perf_counter()
        built = build_onnx_session(model_id, threads, Path(workdir.name), quantized=True)
        build_ms = (time.perf_counter() - t0) * 1000.0

        index, label = positive_index_for(built["id2label"], positive_names)
        handle = ModelHandle(
            model_id=model_id,
            session=built["session"],
            tokenizer=built["tokenizer"],
            fed=tuple(built["fed"]),
            positive_index=index,
            positive_label=label,
            build_ms=round(build_ms, 1),
            params_m=built["params_m"],
            graph_mb=built["graph_mb"],
            labels=tuple(built["labels"]),
        )
        _CACHE[key] = handle

    # ADR-035 item 4: build-at-boot is kept and the cost is LOGGED rather than cached away.
    _LOG.info(
        "graph built for %s: %.0f ms (%.1f M params, %.1f MB int8, %d threads, positive=%r)",
        model_id, handle.build_ms, handle.params_m, handle.graph_mb, threads,
        handle.positive_label,
    )
    return handle


#: Every model detector this module can provision: name -> (checkpoint, positive label names).
#: Read by `warm_models`, so a new ONNX-served detector joins the boot warm-up by appearing
#: here rather than by someone remembering to add a call.
SERVED: dict[str, tuple[str, frozenset[str]]] = {
    "tier2_injection": (
        "madhurjindal/Jailbreak-Detector",
        frozenset({"jailbreak", "injection", "unsafe"}),
    ),
}


def warm_models(detectors: object = None) -> dict[str, float]:
    """Build every served graph **before** the first request. Returns `{detector: build_ms}`.

    **Provisioning must not happen inside a budgeted call, and this is why the function
    exists.** The build measures ~7.8 s for `tier2_injection` on this host (ADR-035 records
    9.6-10.1 s end-to-end per checkpoint). A lazy build inside `detect()` therefore lands an
    8000 ms first request against a 25 ms per-window budget and a 5611 ms bound-case ceiling —
    it breaches both — and it does so **inline on the event loop**, where `wait_for` cannot fire
    until control returns. That is precisely the trap ADR-034 was filed about, and ADR-035 item 4
    already rules the answer: build at boot, log the duration "as one line beside the FR-GW-006
    canary result". Found by wiring the detector into the lane and watching the *control* request
    of `eval.fault_injection` fault with no fault injected.

    **Absent dependencies are skipped, not raised.** On an `.[dev]`-only host `import onnxruntime`
    would fail, and a crash here would replace ADR-033's designed outcome — a clean boot refusal
    under `fail_closed`, a loud warning under `fail_open` — with an ImportError traceback that
    says nothing about policy. The probe is the same one the boot manifest uses, so both read one
    definition of "available".

    **Never called from `Gateway.__init__`.** Construction happens in every test that builds a
    gateway, most of which send no request at all; a build there would put ~8 s of graph export
    into unit-test collection. Boot (the lifespan hook) and the measurement harnesses are the two
    places that genuinely need a warm graph, and both call this explicitly.
    """
    from controlplane.detectors.availability import probe_availability

    names = sorted(SERVED) if detectors is None else sorted(set(detectors) & set(SERVED))
    unloadable = {u.detector for u in probe_availability(names)}
    built: dict[str, float] = {}
    for name in names:
        if name in unloadable:
            continue
        model_id, positive = SERVED[name]
        built[name] = load_classifier(model_id, positive).build_ms
    return built


def provisioned() -> tuple[ModelHandle, ...]:
    """Handles built so far. Startup logging reads this; nothing else should mutate it."""
    with _CACHE_LOCK:
        return tuple(_CACHE.values())


def reset_model_cache() -> None:
    """Drop cached handles and their graphs. Test-support and clean-shutdown only."""
    with _CACHE_LOCK:
        _CACHE.clear()
        while _WORKDIRS:
            _WORKDIRS.pop().cleanup()
