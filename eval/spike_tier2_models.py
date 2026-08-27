"""Q-04 spike — pick the two Tier-2 checkpoints by MEASURED CPU latency (→ ADR-031).

04 §2 budgets `tier2_injection` (input stage) and `tier2_toxicity` (output_sentence) at
**< 25 ms** each, "small transformer, CPU/ONNX". Q-04 deferred the checkpoint choice to
this spike. This script is the measurement behind that choice, kept in-repo so ADR-031's
figures are reproducible rather than asserted (AGENTS.md §7).

**What this measures, and what it deliberately does not.**

Latency only. No candidate's *predictions* are scored here, and no label from the frozen
corpus is read. Detector accuracy is a blind first-contact measurement over the frozen set
(06 §3), and a model selected because it scored well on those fixtures would make that
measurement worthless — the fixtures would have chosen the model. So selection uses one
criterion the eval cannot be contaminated by: does it fit the budget on this hardware.

The corpus supplies only **sequence lengths**. Real ones, because a transformer's cost is
driven by token count and a figure measured on invented strings would not predict the
budget.

**Lengths are drawn per stage, not from the pooled corpus.** A detector can only be timed
on input it can actually receive, and the 04 §2 Stage column decides that: `tier2_injection`
runs at `input`, so its population is the `kind:"input"` cases; `tier2_toxicity` runs at
`output_sentence`, so its population is the *segments* real output cases produce once run
through the gateway's own `Segmentation`. Pooling all 280 cases instead — the first cut of
this script — put a 348-character `kind:"conversation"` text in the `max` bucket and scored
both survivors BREACH on it. Nothing can receive that: the conversation stage runs
`conv_tracker` alone, a deterministic counter with no model in it. A budget verdict against
an unreachable length is not a measurement of anything.

The `cap240` bucket is an **architectural** worst case rather than the corpus's — one of
two, and the two differ in kind. For the output sentence that bound is real and known:
`sentence_buffer.DEFAULT_MAX_CHARS` (240) is the longest unit the segmenter can ever emit,
and the frozen corpus's longest segment is only 118 characters — so the corpus alone would
flatter the toxicity model by a factor of two in length. This bucket is *composed* from real
corpus sentences up to the cap, and is labelled as composed wherever it is reported: it
carries a real token distribution at a length the corpus does not happen to contain.

**The input stage's bound is different in kind, and it is the tokenizer.** No segmenter cap
applies before `tier2_injection`: 04 §3's `budget.per_request_max_tokens` (4000) is a *cost*
control that emits `cost.request_too_large`, and `cost_budget` sits in the same input lane
rather than ahead of it — so it flags a large prompt concurrently instead of trimming what
the classifier receives. What actually bounds the classifier is that every candidate here
declares `max_position_embeddings` 512 (514 for the RoBERTa), so the tokenizer truncates at
`max_length=512` and no longer sequence can reach the model at all. Latency is therefore
bounded, but by **512 tokens** — roughly eight times the token count of the `cap240` bucket,
so a FITS verdict measured on corpus-shaped lengths does not by itself cover the worst case
the architecture admits. The `tok512_trunc` bucket below measures that bound directly.

Truncation also has a **detection** consequence that is not this script's to resolve but must
not be discovered later: an injection payload placed beyond token 512 is never seen by the
classifier, so FR-DET-002's input check is length-limited by construction. Recorded here
because the latency bound and the coverage gap have the same cause.

**Two modes.** The default sweep scores every candidate on the five buckets above.
`--crossover` then walks ONE checkpoint per role up a character ladder (`CROSSOVER_CHARS`)
to locate where the budget actually breaks — a different question about the winner, not a
re-run of the selection, and the reason the `input`-lane finding rests on measurements
rather than on extrapolating from `cap240`. `--crossover-model ROLE=ID` points it at a
runner-up, so comparing two candidates is two measurements instead of one measurement and
one guess. `--render FILE` re-prints either artifact without measuring anything.

**Three backends, because 04 §2 says "CPU/ONNX" and those are different numbers.**
`torch` is PyTorch eager — the obvious implementation. `onnx_fp32` is the same weights under
ONNX Runtime, and `onnx_int8` is that graph with dynamically-quantized int8 weights, which is
the standard way a BERT-class encoder reaches a low-tens-of-milliseconds CPU budget. Measuring
only eager would let a budget be declared unreachable while the runtime the doc actually names
went untried.

`onnx_int8` carries one disclosure that belongs next to its latency: quantization perturbs the
model's outputs. On the probe sentence the fp32 ONNX logits matched eager exactly and int8
differed in the third digit — small, but not nothing. Selection here is still latency-only, so
this cannot bias the pick; what it means is that a shipped int8 detector's accuracy is **not**
the published checkpoint's accuracy, and the 06 §3 first-contact eval measures whatever is
actually shipped. Recorded so the ADR states it rather than implying fp32 accuracy.

**Two thread settings, both reported.** `torch` defaults to one thread per physical core
(6 here). A detector measured alone at 6 threads is optimistic about the gateway, where
ADR-030's parallel lane will run several detectors concurrently and they contend for the
same cores; a single-thread figure bounds the pessimistic end. A pick has to fit at the
setting the gateway will actually use, so both are recorded and the ADR reasons over both.

Cold start is reported separately from steady state. The first inference includes lazy
init and is not a percentile input, but it is not hidden either: it is what the first
request after a boot actually pays.

Usage:
    python -m eval.spike_tier2_models                 # both thread settings, all candidates
    python -m eval.spike_tier2_models --threads 1     # one setting
    python -m eval.spike_tier2_models --reps 100
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from controlplane.gateway.sentence_buffer import (  # noqa: E402  (after sys.path)
    DEFAULT_MAX_CHARS,
    Segmentation,
)

DATASET_DIR = REPO / "eval" / "dataset"
DEFAULT_OUT = REPO / "reports" / "spike_tier2_models.json"

#: Candidates per detector role. Published, downloadable sequence classifiers in the size
#: class 04 §2 calls "small transformer" — the family a 25 ms CPU budget can plausibly
#: admit. Ordered smallest-first within each role so the table reads as a size sweep.
#: A candidate that fails to download is a recorded outcome, not a crash: "we tried it and
#: could not get it" is information ADR-031 should carry.
CANDIDATES: dict[str, tuple[str, ...]] = {
    "tier2_injection": (
        "protectai/deberta-v3-base-prompt-injection-v2",
        "jackhhao/jailbreak-classifier",
        "madhurjindal/Jailbreak-Detector",
    ),
    "tier2_toxicity": (
        "martin-ha/toxic-comment-model",
        "s-nlp/roberta_toxicity_classifier",
        "unitary/toxic-bert",
    ),
}

BUDGET_MS = 25.0        # 04 §2, both rows

#: The backends 04 §2's "CPU/ONNX" admits. `torch` first so the table reads eager → runtime →
#: quantized, which is the order of increasing intervention on the published checkpoint.
BACKENDS: tuple[str, ...] = ("torch", "onnx_fp32", "onnx_int8")


#: 04 §2 Stage column → the corpus `kind` whose texts that stage actually receives.
#: This mapping is the whole correction: it is what stops a detector being scored against
#: a length its stage cannot hand it.
ROLE_POPULATION: dict[str, str] = {
    "tier2_injection": "input",          # 04 §2: stage `input`
    "tier2_toxicity": "output",          # 04 §2: stage `output_sentence` (segmented below)
}


def _texts_of_kind(kind: str) -> list[str]:
    """Every `text` in the frozen corpus whose `kind` is `kind`. Labels are never read."""
    out: list[str] = []
    for path in sorted(DATASET_DIR.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("kind") == kind and record.get("text"):
                out.append(record["text"])
    return out


def _units_for_role(role: str) -> list[str]:
    """The real interception units this detector's stage hands it, one string per unit.

    For the output sentence that is not the case text but the *segments* of it, produced by
    the gateway's own `Segmentation` rather than a second splitter written here — two
    definitions of "one sentence" would eventually disagree, and this figure is only
    meaningful if the unit matches the one the hot path will pass the model.
    """
    texts = _texts_of_kind(ROLE_POPULATION[role])
    if role != "tier2_toxicity":
        return texts
    units: list[str] = []
    for text in texts:
        segmentation = Segmentation()
        units.extend(seg.text for seg in segmentation.feed(text) + segmentation.flush())
    return units


def _compose_to_cap(units: list[str], cap: int) -> str:
    """A unit at the segmenter's cap, composed from real corpus sentences.

    Composed, not invented: the token distribution is the corpus's, only the length is
    chosen. Reported under a `cap<N>` bucket name so no reader mistakes it for a case.
    """
    parts: list[str] = []
    total = 0
    for unit in sorted(units, key=len, reverse=True):
        if total + len(unit) + 1 > cap:
            continue
        parts.append(unit)
        total += len(unit) + 1
    return " ".join(parts)[:cap]


#: Characters composed for the truncation-bound bucket. Deliberately far more than 512
#: tokens' worth under any tokenizer here (prose runs ~4-6 chars/token, and the densest
#: text measured — letter-spaced injection payloads — still runs ~1.9), so every candidate
#: truncates at its own `max_length` and the bucket lands exactly on the bound rather than
#: near it. The recorded `tokens` figure is what proves it did: it reads 512, not less.
TRUNCATION_PROBE_CHARS = 4000

#: Reps for the truncation bucket. Fewer, because one inference there costs roughly an
#: order of magnitude more than at corpus lengths and the 1-thread × 184M-param cell would
#: otherwise dominate the whole sweep. `n` is recorded per bucket so a percentile is never
#: read as if it came from the same sample size as the others.
TRUNCATION_PROBE_REPS = 20


#: Character lengths for the input-lane crossover probe (ADR-031). The `input` stage has
#: **no length cap**: `DEFAULT_MAX_CHARS` bounds the output segmenter (ADR-002), and nothing
#: bounds a user message before `tier2_injection` sees it — `Budget.per_request_max_tokens`
#: is a cost control in the same lane, not a gate. So the reachable input length runs from a
#: short prompt to the tokenizer's 512-token ceiling, and these lengths locate where the
#: 25 ms budget is actually crossed. Stated in characters because that is what the composer
#: controls; the measured token count is recorded per row and is the figure to cite.
CROSSOVER_CHARS = (240, 400, 600, 800, 1000, 1400, 2000, 4000)


def _compose_to_chars(units: list[str], target: int) -> str:
    """Concatenate real corpus units, cycling if needed, until `target` characters.

    Cycling is why this is honest at 4000 characters from a corpus whose longest unit is
    118: the token *distribution* stays the corpus's, and only the length is chosen. An
    invented filler string ("word word word…") would tokenize unlike real text and the
    figure would not predict anything.
    """
    if not units:
        raise RuntimeError("no units to compose from")
    parts: list[str] = []
    total = 0
    index = 0
    while total < target:
        unit = units[index % len(units)]
        parts.append(unit)
        total += len(unit) + 1
        index += 1
    return " ".join(parts)[:target]


def _buckets_for_role(role: str) -> dict[str, str]:
    """Five lengths for one role, cheapest first.

    Three are real corpus units (p50 / p95 / longest). Two are *composed*, and named so:
    `cap240` is the segmenter's ceiling (output stage only — see the module docstring), and
    `tok512_trunc` is the tokenizer truncation bound, the longest sequence that can reach
    any of these models at all.
    """
    units = _units_for_role(role)
    if not units:
        raise RuntimeError(f"no corpus units for role {role!r} — check ROLE_POPULATION")
    ordered = sorted(units, key=len)
    n = len(ordered)
    return {
        "p50": ordered[int(0.50 * (n - 1))],
        "p95": ordered[int(0.95 * (n - 1))],
        "corpus_max": ordered[-1],
        f"cap{DEFAULT_MAX_CHARS}": _compose_to_cap(units, DEFAULT_MAX_CHARS),
        "tok512_trunc": _compose_to_chars(units, TRUNCATION_PROBE_CHARS),
    }


def _reps_for_bucket(name: str, reps: int) -> int:
    """Rep count for one bucket — reduced only for the truncation probe."""
    if name == "tok512_trunc":
        return max(10, min(reps, TRUNCATION_PROBE_REPS))
    return reps


def _percentiles_are_distinct(n: int) -> bool:
    """Whether p95 and p99 land on different order statistics at this sample size.

    At n=20 both `int(0.95 * 19)` and `int(0.99 * 19)` are 18 — one measurement that would
    print as two percentiles. Rows where this is False report p50 and max instead, and `max`
    governs their verdict: the conservative reading when the tail is unresolved. Computed
    from n rather than compared against a constant so it stays correct under `--reps`.
    """
    return n >= 2 and int(0.95 * (n - 1)) != int(0.99 * (n - 1))


def _percentiles(samples: list[float], cold_ms: float, text: str, n_tokens: int) -> dict[str, Any]:
    """One bucket's row. Shared by every backend so the figures are computed identically."""
    samples = sorted(samples)
    reps = len(samples)
    return {
        "chars": len(text),
        "tokens": n_tokens,
        "n": reps,
        "cold_ms": round(cold_ms, 2),
        "p50": round(statistics.median(samples), 2),
        "p95": round(samples[int(0.95 * (reps - 1))], 2),
        "p99": round(samples[int(0.99 * (reps - 1))], 2),
        "max": round(samples[-1], 2),
    }


def build_onnx_session(model_id: str, threads: int, workdir: Path,
                       quantized: bool = True) -> dict[str, Any]:
    """Export `model_id` to ONNX, optionally int8-quantize, and open a CPU session.

    Extracted so that **one** definition of "the served graph" covers every harness that
    measures these checkpoints. ADR-032's window figures have to describe the same graph
    ADR-031 picked, and two export paths would eventually differ in opset, axes or quant
    settings — at which point the two ADRs' numbers would silently stop being comparable.

    The export happens here rather than being cached in the repo: a checked-in graph would be a
    binary artifact whose provenance nobody could check, and the export costs ~2 s. The caller
    owns `workdir` and deletes it after measuring — six fp32 graphs are ~1.6 GB and this
    machine has less, so callers keep one at a time.

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
    out["labels"] = list(getattr(model.config, "id2label", {}).values())[:6]

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


def _measure_onnx(model_id: str, buckets: dict[str, str], reps: int, threads: int,
                  quantized: bool) -> dict[str, Any]:
    """Time one checkpoint on every bucket under ONNX Runtime."""
    import numpy as np

    out: dict[str, Any] = {"model_id": model_id}
    workdir = Path(tempfile.mkdtemp(prefix="spike_onnx_"))
    try:
        built = build_onnx_session(model_id, threads, workdir, quantized=quantized)
        sess, tok, fed = built.pop("session"), built.pop("tokenizer"), built.pop("fed")
        out.update(built)

        out["buckets"] = {}
        for name, text in buckets.items():
            bucket_reps = _reps_for_bucket(name, reps)
            enc = tok(text, return_tensors="np", truncation=True, max_length=512)
            feed = {k: enc[k].astype(np.int64) for k in fed if k in enc}
            n_tokens = int(enc["input_ids"].shape[1])

            t0 = time.perf_counter()
            sess.run(None, feed)
            cold_ms = (time.perf_counter() - t0) * 1000.0
            for _ in range(3):
                sess.run(None, feed)
            samples = []
            for _ in range(bucket_reps):
                t0 = time.perf_counter()
                sess.run(None, feed)
                samples.append((time.perf_counter() - t0) * 1000.0)
            out["buckets"][name] = _percentiles(samples, cold_ms, text, n_tokens)
    except Exception as exc:                       # noqa: BLE001 — recorded, not raised
        out["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return out


def _measure_one(model_id: str, buckets: dict[str, str], reps: int) -> dict[str, Any]:
    """Load one checkpoint and time `reps` inferences per length bucket."""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    out: dict[str, Any] = {"model_id": model_id}
    try:
        t0 = time.perf_counter()
        tok = AutoTokenizer.from_pretrained(model_id)
        model = AutoModelForSequenceClassification.from_pretrained(model_id)
        model.eval()
        out["load_s"] = round(time.perf_counter() - t0, 2)
    except Exception as exc:                       # noqa: BLE001 — recorded, not raised
        out["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        return out

    out["params_m"] = round(sum(p.numel() for p in model.parameters()) / 1e6, 1)
    out["labels"] = list(getattr(model.config, "id2label", {}).values())[:6]
    out["buckets"] = {}

    for name, text in buckets.items():
        bucket_reps = _reps_for_bucket(name, reps)
        enc = tok(text, return_tensors="pt", truncation=True, max_length=512)
        n_tokens = int(enc["input_ids"].shape[1])

        with torch.inference_mode():
            t0 = time.perf_counter()
            model(**enc)                            # cold: includes lazy init
            cold_ms = (time.perf_counter() - t0) * 1000.0
            for _ in range(3):                      # warm-up, excluded
                model(**enc)
            samples: list[float] = []
            for _ in range(bucket_reps):
                t0 = time.perf_counter()
                model(**enc)
                samples.append((time.perf_counter() - t0) * 1000.0)

        out["buckets"][name] = _percentiles(samples, cold_ms, text, n_tokens)
    return out


def _sweep(threads: int, reps: int, backends: tuple[str, ...] = BACKENDS) -> dict[str, Any]:
    """One full sweep at a fixed thread count, across every requested backend."""
    import torch

    torch.set_num_threads(threads)
    result: dict[str, Any] = {
        "threads": threads,
        "reps": reps,
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "population": dict(ROLE_POPULATION),
        "buckets": {},
        "roles": {},
    }
    for role, models in CANDIDATES.items():
        buckets = _buckets_for_role(role)
        result["buckets"][role] = {k: {"chars": len(v)} for k, v in buckets.items()}
        result["roles"][role] = []
        for model_id in models:
            for backend in backends:
                print(f"  [{threads}t/{backend}] {role}: {model_id} …",
                      file=sys.stderr, flush=True)
                if backend == "torch":
                    entry = _measure_one(model_id, buckets, reps)
                else:
                    entry = _measure_onnx(model_id, buckets, reps, threads,
                                          quantized=(backend == "onnx_int8"))
                entry["backend"] = backend
                result["roles"][role].append(entry)
    return result


#: The checkpoints the 5-bucket × 3-backend sweep selected, which `--crossover` then
#: characterises further. The ordering is deliberate and not circular: the *pick* is decided
#: by the sweep (every backend, every reachable length), and the crossover probe answers a
#: different question about the winner — at what input length its budget stops holding.
CROSSOVER_MODELS: dict[str, str] = {
    "tier2_injection": "madhurjindal/Jailbreak-Detector",
    "tier2_toxicity": "martin-ha/toxic-comment-model",
}


def _crossover(threads: int, reps: int,
               models: dict[str, str] | None = None) -> dict[str, Any]:
    """Locate where the 25 ms budget is crossed, per role, for the selected checkpoint.

    Only `tier2_injection` has an unbounded population — the `input` stage applies no length
    cap, so any length up to the tokenizer's 512-token ceiling is reachable. `tier2_toxicity`
    is measured over the same ladder for contrast, but lengths above `DEFAULT_MAX_CHARS` are
    **not reachable** on its stage: the segmenter cuts first. That asymmetry is the point of
    running both.

    Timing reuses `_measure_onnx` unchanged rather than re-implementing a loop, so a crossover
    figure and a sweep figure are the same measurement taken at a different length.
    """
    import torch

    torch.set_num_threads(threads)
    result: dict[str, Any] = {
        "threads": threads, "reps": reps, "backend": "onnx_int8",
        "torch": torch.__version__, "roles": {},
    }
    for role, model_id in (models or CROSSOVER_MODELS).items():
        units = _units_for_role(role)
        buckets = {f"c{n}": _compose_to_chars(units, n) for n in CROSSOVER_CHARS}
        print(f"  [{threads}t/crossover] {role}: {model_id} …", file=sys.stderr, flush=True)
        entry = _measure_onnx(model_id, buckets, reps, threads, quantized=True)
        entry["backend"] = "onnx_int8"
        entry["stage_capped_at_chars"] = (
            DEFAULT_MAX_CHARS if role == "tier2_toxicity" else None
        )
        result["roles"][role] = entry
    return result


def _render_crossover(runs: list[dict[str, Any]]) -> str:
    lines = ["", "=" * 100,
             f"Q-04 CROSSOVER — where the {BUDGET_MS:.0f} ms budget breaks (onnx_int8, selected picks)",
             "=" * 100]
    for run in runs:
        lines += ["", f"--- threads = {run['threads']}  (reps={run['reps']}) ---"]
        for role, e in run["roles"].items():
            cap = e.get("stage_capped_at_chars")
            reach = (f"stage caps input at {cap} chars — longer rows are UNREACHABLE"
                     if cap else "stage applies NO length cap — every row is reachable")
            lines += ["", f"  {role}: {e.get('model_id','?')}  ({reach})"]
            if "error" in e:
                lines.append(f"    UNAVAILABLE: {e['error'][:80]}")
                continue
            lines.append(f"    {'chars':>6} {'tok':>4} {'n':>4} {'P50':>8} {'P95':>8} "
                         f"{'P99':>8} {'max':>8}  verdict")
            for bname, b in e["buckets"].items():
                distinct = _percentiles_are_distinct(b.get("n", 0))
                governing = b["p99"] if distinct else b["max"]
                mark = "" if cap is None or b["chars"] <= cap else "  (unreachable)"
                lines.append(
                    f"    {b['chars']:6} {b['tokens']:4} {b.get('n',0):4} {b['p50']:8.2f} "
                    f"{b['p95']:8.2f} {b['p99']:8.2f} {b['max']:8.2f}  "
                    f"{'FITS' if governing < BUDGET_MS else 'BREACH'}{mark}"
                )
    lines += ["", "=" * 100, ""]
    return "\n".join(lines)


def _render(sweeps: list[dict[str, Any]]) -> str:
    lines = ["", "=" * 100, "Q-04 SPIKE — Tier-2 checkpoint latency (04 §2 budget: < 25 ms)", "=" * 100]
    for sw in sweeps:
        lines += ["", f"--- torch threads = {sw['threads']}  (reps={sw['reps']}, "
                      f"torch {sw['torch']}, cuda={sw['cuda_available']}) ---"]
        for role, entries in sw["roles"].items():
            pop = sw.get("population", {}).get(role, "?")
            shape = "  ".join(f"{k}={v['chars']}ch"
                              for k, v in sw.get("buckets", {}).get(role, {}).items())
            lines += ["", f"  {role}  (budget < {BUDGET_MS:.0f} ms; "
                          f"units from kind:{pop!r})", f"    {shape}"]
            lines.append(f"    {'model':34} {'backend':10} {'bucket':>12} {'tok':>4} "
                         f"{'n':>4} {'P50':>7} {'P95':>7} {'P99':>7} {'max':>8} "
                         f"{'cold':>8}  verdict")
            for e in entries:
                if "error" in e:
                    lines.append(f"    {e['model_id'][:34]:34} {e.get('backend',''):10} "
                                 f"UNAVAILABLE: {e['error'][:56]}")
                    continue
                for bname, b in e["buckets"].items():
                    # Which statistic decides is a function of the sample size, not a
                    # preference: where p95 and p99 are the same order statistic, printing
                    # both would present one measurement as two, so the row falls back to
                    # p50 + max and `max` carries the verdict.
                    distinct = _percentiles_are_distinct(b.get("n", 0))
                    governing = b["p99"] if distinct else b["max"]
                    fits = "FITS" if governing < BUDGET_MS else "BREACH"
                    p95 = f"{b['p95']:7.2f}" if distinct else f"{'—':>7}"
                    p99 = f"{b['p99']:7.2f}" if distinct else f"{'—':>7}"
                    lines.append(
                        f"    {e['model_id'][:34]:34} {e.get('backend',''):10} {bname:>12} "
                        f"{b['tokens']:4} {b.get('n', 0):4} {b['p50']:7.2f} {p95} "
                        f"{p99} {b['max']:8.2f} {b['cold_ms']:8.1f}  {fits}"
                    )
    lines += [
        "",
        f"verdict: governing statistic < {BUDGET_MS:.0f} ms (04 §2). Governing = P99, except",
        "rows where n is too small for P95 and P99 to be distinct order statistics — those",
        "print '—' for both and are judged on max, the conservative reading of an unresolved tail.",
        "=" * 100, "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--threads", type=int, action="append",
                        help="torch thread count (repeatable; default: 6 and 1)")
    parser.add_argument("--reps", type=int, default=50)
    parser.add_argument("--backend", action="append", choices=BACKENDS,
                        help="repeatable; default: all three")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--crossover", action="store_true",
                        help="probe the selected picks along CROSSOVER_CHARS instead of sweeping")
    parser.add_argument("--render", type=Path,
                        help="re-render an existing results JSON; measures nothing")
    parser.add_argument("--crossover-model", action="append", metavar="ROLE=MODEL_ID",
                        help="override the crossover checkpoint for one role (repeatable). "
                             "Lets a runner-up be characterised on the same ladder, so a "
                             "comparison between two candidates is two measurements rather "
                             "than one measurement and one interpolation.")
    parser.add_argument("--_worker-threads", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    # Each thread setting runs in its own process: `torch.set_num_threads` after a pool
    # has spun up does not reliably resize it, and a stale pool would silently make the
    # second sweep a copy of the first.
    backends = tuple(args.backend) if args.backend else BACKENDS
    if args.render is not None:
        prior = json.loads(args.render.read_text())
        print(_render_crossover(prior["runs"]) if "runs" in prior
              else _render(prior["sweeps"]))
        return 0

    overrides: dict[str, str] = {}
    for spec in args.crossover_model or []:
        role, _, model_id = spec.partition("=")
        if role not in CANDIDATES or not model_id:
            print(f"--crossover-model: expected ROLE=MODEL_ID with ROLE in "
                  f"{sorted(CANDIDATES)}, got {spec!r}", file=sys.stderr)
            return 2
        overrides[role] = model_id

    if args._worker_threads is not None:
        payload = (_crossover(args._worker_threads, args.reps, overrides or None)
                   if args.crossover
                   else _sweep(args._worker_threads, args.reps, backends))
        json.dump(payload, sys.stdout)
        return 0

    thread_settings = args.threads or [6, 1]
    sweeps: list[dict[str, Any]] = []
    for t in thread_settings:
        proc = subprocess.run(
            [sys.executable, "-m", "eval.spike_tier2_models",
             "--_worker-threads", str(t), "--reps", str(args.reps),
             *(f"--backend={b}" for b in backends),
             *(["--crossover"] if args.crossover else []),
             *(f"--crossover-model={r}={m}" for r, m in overrides.items())],
            cwd=REPO, capture_output=True, text=True,
            env={**os.environ, "OMP_NUM_THREADS": str(t), "MKL_NUM_THREADS": str(t)},
        )
        sys.stderr.write(proc.stderr)
        if proc.returncode != 0:
            print(f"sweep at threads={t} failed (exit {proc.returncode})", file=sys.stderr)
            return proc.returncode
        sweeps.append(json.loads(proc.stdout))

    if args.crossover:
        report = {
            "spike": "Q-04 crossover — budget-break length for the selected picks",
            "budget_ms": BUDGET_MS,
            "models": overrides or dict(CROSSOVER_MODELS),
            "chars_ladder": list(CROSSOVER_CHARS),
            "platform": f"{platform.system()} {platform.release()} · {platform.machine()}",
            "cpu_count": os.cpu_count(),
            "python": platform.python_version(),
            "runs": sweeps,
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n")
        print(_render_crossover(sweeps))
        print(f"{args.out}: raw measurements")
        return 0

    report = {
        "spike": "Q-04 tier-2 checkpoints",
        "budget_ms": BUDGET_MS,
        "backends": list(backends),
        "platform": f"{platform.system()} {platform.release()} · {platform.machine()}",
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "sweeps": sweeps,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(_render(sweeps))
    print(f"{args.out}: raw measurements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
