"""ADR-032 evidence — full-coverage strided windows for `tier2_injection`, measured.

The `[D3-tier2-injection-budget-cannot-hold-on-unbounded-input]` ruling overruled prefix
truncation: scoring only the first window would make pad-then-inject a guaranteed bypass, and
a public repo documenting the window size would publish the recipe. So `tier2_injection` scores
the **whole** input as overlapping windows and takes the MAX score. That trades a coverage hole
for scaled latency, and this harness is the measurement that says what the latency actually is.

**Window geometry, and why these numbers.** ADR-031's crossover ladder measured the pick
(`madhurjindal/Jailbreak-Detector`) FITS at 104 tokens (14.27 / 22.80 ms P50/P99) and BREACH at
158 (23.51 / 33.57). So the window is **104 tokens** — the longest measured length that fits the
04 §2 budget — and *not* the model's architectural 512, which measured 95.31 / 99.72 and never
had a chance. The ruling's 25% overlap makes the step 76 tokens, which is also what puts the
4000-token policy bound at ~52 windows, the figure the ruling itself cites.

Overlap exists for one reason: a payload straddling a window boundary must appear **whole** in
at least one window, or the split is itself an evasion. 26 tokens of overlap bounds the length of
payload that splitting can hide.

**HuggingFace's `stride` is the overlap, not the step** — verified rather than assumed, because
reading it the other way silently produces 26-token steps, 4x the windows and a harness that
measures a system nobody would ship.

**Filler is synthetic, and that is a hard constraint rather than a convenience.** The 06 §3
detector eval is a blind first-contact measurement over the frozen corpus; a latency harness that
read corpus text would not contaminate the *scores*, but the ruling asked for synthetic filler and
the reason generalises — the less this repo's measurement code touches the frozen set, the less
there is to argue about later. It costs nothing here: a transformer's cost is driven by sequence
length and batch shape, not by which words fill the tensor. Every window is padded to exactly 104
tokens, so what is timed is the worst case at each window count rather than a ragged average.

**What "batch capacity" means here.** Batching amortises per-call overhead, so k windows in one
`sess.run` cost less than k separate calls. But the gain saturates: past some batch size the call
is compute-bound and total time grows linearly again. The ADR's parametric budget is
`ceil(windows / capacity) x cost-per-batch`, so the capacity has to come from a measured curve
rather than a guess. This harness measures a batch grid and reports per-window marginal cost, and
`--render` re-prints the artifact without measuring.

Both thread settings are reported for the same reason ADR-031 reports both: 6 threads is what one
detector alone gets, 1 thread bounds the pessimistic end where ADR-030's parallel lane has several
detectors contending. SL-5 already stands on that gap and this harness must not quietly narrow it.

Usage:
    python -m eval.spike_window_latency                    # both thread settings
    python -m eval.spike_window_latency --threads 6
    python -m eval.spike_window_latency --reps 30
    python -m eval.spike_window_latency --render reports/spike_window_latency.json
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from eval.spike_tier2_models import (  # noqa: E402  (after sys.path)
    BUDGET_MS,
    build_onnx_session,
    _percentiles_are_distinct,
)

#: The pick ADR-031 bound for the input stage. Windowing is an `input`-lane concern only:
#: `tier2_toxicity` reads output sentences, which the segmenter caps at 240 characters.
MODEL_ID = "madhurjindal/Jailbreak-Detector"

#: Window length in tokens, INCLUDING the tokenizer's two special tokens — this is the value
#: handed to `max_length`, so 104 here means 102 tokens of content. ADR-031 measured this length
#: at 14.27 / 22.80 ms, inside the 25 ms budget; 158 tokens breached at 33.57.
WINDOW_TOKENS = 104

#: Overlap in tokens (HF `stride`). 25% of the window per the ruling, making the step 76.
WINDOW_OVERLAP = 26

#: 04 §3 `budget.per_request_max_tokens`. The ruling designates this the input bound and item 4
#: makes lowering it the per-use-case latency ceiling, so the published worst case sits here.
POLICY_BOUND_TOKENS = 4000

#: Window counts to measure. 1 is the single-window case the respecified budget still covers;
#: the top of the range is the policy bound. Powers of two in between locate the batch-capacity
#: knee without measuring 52 separate points.
WINDOW_COUNTS = (1, 2, 4, 8, 16, 32, 52)

#: Batch sizes for the capacity curve, measured at the bound's window count.
BATCH_SIZES = (1, 2, 4, 8, 16, 32, 52)

#: Reps scale down as the work per rep grows — 52 sequential windows at 1 thread is ~4 s each.
def _reps_for(n_windows: int, reps: int) -> int:
    if n_windows >= 32:
        return max(5, reps // 4)
    if n_windows >= 8:
        return max(10, reps // 2)
    return reps


def synthetic_filler(target_tokens: int, tok: Any) -> str:
    """Deterministic synthetic prose that tokenizes to at least `target_tokens`.

    Not corpus text and not an injection payload — see the module docstring. Deterministic so the
    artifact is reproducible: no RNG, no clock. The vocabulary is ordinary English so the token
    density lands in the normal prose range rather than at the pathological end; the point is a
    representative tensor shape, and the shape is then pinned exactly by padding.
    """
    words = ("the", "system", "will", "process", "each", "request", "through", "a", "series",
             "of", "checks", "before", "returning", "any", "content", "to", "the", "caller")
    parts: list[str] = []
    i = 0
    while True:
        parts.append(words[i % len(words)])
        i += 1
        if i % 12 == 0:
            parts.append("and then it continues.")
        if i % 64 == 0 and len(tok(" ".join(parts))["input_ids"]) >= target_tokens:
            break
        if i > target_tokens * 4:            # guard: cannot happen, but never loop forever
            break
    return " ".join(parts)


def _windows_for(text: str, tok: Any, n_windows: int) -> Any:
    """Tokenize `text` into padded windows and return the first `n_windows` of them.

    Every window is padded to exactly `WINDOW_TOKENS` so a batch is rectangular and each window
    costs the same as a full one. That is deliberately the worst case: a real last window is
    shorter and cheaper, and reporting the cheaper figure would understate the bound.
    """
    enc = tok(text, truncation=True, max_length=WINDOW_TOKENS, stride=WINDOW_OVERLAP,
              return_overflowing_tokens=True, padding="max_length", return_tensors="np")
    have = enc["input_ids"].shape[0]
    if have < n_windows:
        raise RuntimeError(f"filler yielded {have} windows, need {n_windows}")
    return {k: v[:n_windows] for k, v in enc.items() if k != "overflow_to_sample_mapping"}


def _time_calls(sess: Any, feeds: list[dict[str, Any]], reps: int) -> dict[str, Any]:
    """Time `reps` repetitions of running every feed in `feeds` once (the whole request)."""
    def one_pass() -> None:
        for feed in feeds:
            sess.run(None, feed)

    t0 = time.perf_counter()
    one_pass()
    cold_ms = (time.perf_counter() - t0) * 1000.0
    for _ in range(2):
        one_pass()
    samples: list[float] = []
    for _ in range(reps):
        t0 = time.perf_counter()
        one_pass()
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    n = len(samples)
    return {
        "n": n,
        "calls": len(feeds),
        "cold_ms": round(cold_ms, 2),
        "p50": round(statistics.median(samples), 2),
        "p95": round(samples[int(0.95 * (n - 1))], 2),
        "p99": round(samples[int(0.99 * (n - 1))], 2),
        "max": round(samples[-1], 2),
    }


def _feeds(win: dict[str, Any], fed: list[str], batch: int) -> list[dict[str, Any]]:
    """Split `win`'s windows into batched feeds of at most `batch` rows each."""
    import numpy as np
    total = win["input_ids"].shape[0]
    out: list[dict[str, Any]] = []
    for start in range(0, total, batch):
        out.append({k: win[k][start:start + batch].astype(np.int64)
                    for k in fed if k in win})
    return out


def _measure(threads: int, reps: int) -> dict[str, Any]:
    """One thread setting: the window-count ladder (sequential and batched) + the batch curve."""
    run: dict[str, Any] = {"threads": threads, "reps": reps}
    workdir = Path(tempfile.mkdtemp(prefix="spike_win_"))
    try:
        built = build_onnx_session(MODEL_ID, threads, workdir, quantized=True)
        sess, tok, fed = built.pop("session"), built.pop("tokenizer"), built.pop("fed")
        run.update({k: v for k, v in built.items() if k != "labels"})

        text = synthetic_filler(POLICY_BOUND_TOKENS, tok)
        run["filler_tokens"] = len(tok(text)["input_ids"])
        run["filler_chars"] = len(text)
        run["window_tokens"] = WINDOW_TOKENS
        run["window_overlap"] = WINDOW_OVERLAP
        run["window_step"] = WINDOW_TOKENS - 2 - WINDOW_OVERLAP

        run["ladder"] = {}
        for n_windows in WINDOW_COUNTS:
            win = _windows_for(text, tok, n_windows)
            r = _reps_for(n_windows, reps)
            row: dict[str, Any] = {"windows": n_windows}
            row["sequential"] = _time_calls(sess, _feeds(win, fed, 1), r)
            row["batched"] = _time_calls(sess, _feeds(win, fed, n_windows), r)
            run["ladder"][str(n_windows)] = row

        run["batch_curve"] = {}
        win = _windows_for(text, tok, max(WINDOW_COUNTS))
        for batch in BATCH_SIZES:
            feeds = _feeds(win, fed, batch)
            run["batch_curve"][str(batch)] = _time_calls(
                sess, feeds, _reps_for(max(WINDOW_COUNTS), reps))
    except Exception as exc:                       # noqa: BLE001 — recorded, not raised
        run["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return run


def _render(runs: list[dict[str, Any]]) -> str:
    """Human-readable table. `—` where p95 and p99 are one order statistic (ADR-031's rule)."""
    lines: list[str] = []
    for run in runs:
        lines.append(f"\n{'=' * 96}")
        lines.append(f"threads={run['threads']}  model={MODEL_ID}  int8"
                     f"  window={run.get('window_tokens')}tok"
                     f"  overlap={run.get('window_overlap')}"
                     f"  step={run.get('window_step')}")
        if "error" in run:
            lines.append(f"  ERROR {run['error']}")
            continue
        lines.append(f"filler: {run['filler_tokens']} tokens / {run['filler_chars']} chars"
                     f"   (synthetic — no corpus text)")
        lines.append(f"{'=' * 96}")
        lines.append(f"  budget {BUDGET_MS} ms is a PER-WINDOW figure; totals below are "
                     f"whole-request")
        lines.append("")
        lines.append(f"  {'wins':>5} {'mode':<11} {'calls':>5} {'n':>3} {'p50':>8} {'p95':>8} "
                     f"{'p99':>8} {'max':>8}  {'per-win p50':>11}")
        for key in sorted(run["ladder"], key=int):
            row = run["ladder"][key]
            for mode in ("sequential", "batched"):
                b = row[mode]
                distinct = _percentiles_are_distinct(b["n"])
                p95 = f"{b['p95']:8.2f}" if distinct else f"{'—':>8}"
                p99 = f"{b['p99']:8.2f}" if distinct else f"{'—':>8}"
                per = b["p50"] / row["windows"]
                lines.append(f"  {row['windows']:>5} {mode:<11} {b['calls']:>5} {b['n']:>3} "
                             f"{b['p50']:8.2f} {p95} {p99} {b['max']:8.2f}  {per:11.2f}")
        lines.append("")
        lines.append(f"  batch capacity curve at {max(WINDOW_COUNTS)} windows:")
        lines.append(f"  {'batch':>5} {'calls':>5} {'p50':>8} {'p99':>8} {'per-win p50':>11}")
        for key in sorted(run["batch_curve"], key=int):
            b = run["batch_curve"][key]
            distinct = _percentiles_are_distinct(b["n"])
            p99 = f"{b['p99']:8.2f}" if distinct else f"{'—':>8}"
            per = b["p50"] / max(WINDOW_COUNTS)
            lines.append(f"  {int(key):>5} {b['calls']:>5} {b['p50']:8.2f} {p99} {per:11.2f}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--threads", type=int, action="append",
                    help="thread setting (repeatable); default 6 and 1")
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--out", default="reports/spike_window_latency.json")
    ap.add_argument("--render", metavar="FILE",
                    help="re-render an existing artifact; measures nothing")
    args = ap.parse_args(argv)

    if args.render:
        art = json.loads(Path(args.render).read_text())
        print(_render(art["runs"]))
        return 0

    import onnxruntime as ort
    art: dict[str, Any] = {
        "spike": "ADR-032 — full-coverage strided windows for tier2_injection",
        "model_id": MODEL_ID,
        "budget_ms": BUDGET_MS,
        "backend": "onnx_int8",
        "filler": "synthetic (deterministic); no corpus text",
        "window": {"tokens": WINDOW_TOKENS, "overlap": WINDOW_OVERLAP,
                   "policy_bound_tokens": POLICY_BOUND_TOKENS},
        "platform": platform.platform(),
        "cpu_count": __import__("os").cpu_count(),
        "python": platform.python_version(),
        "onnxruntime": ort.__version__,
        "runs": [],
    }
    for threads in (args.threads or [6, 1]):
        art["runs"].append(_measure(threads, args.reps))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(art, indent=2) + "\n")
    print(_render(art["runs"]))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
