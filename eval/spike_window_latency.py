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
import math
import os
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

from eval.host_load import (  # noqa: E402  (after sys.path)
    QUIET_LOAD1_MAX,
    git_stamp,
    reproducibility_verdict,
    load_stamp,
    quiet_verdict,
)
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

#: Content tokens per window — `WINDOW_TOKENS` less the tokenizer's two special tokens.
WINDOW_CONTENT_TOKENS = WINDOW_TOKENS - 2

#: Token step between consecutive window starts. Derived, never written down twice.
WINDOW_STEP = WINDOW_CONTENT_TOKENS - WINDOW_OVERLAP


def coverage_tokens(n_windows: int) -> int:
    """Content tokens spanned by `n_windows` strided windows. THE definition (ADR-032 §C1).

    `102 + (n-1) * 76`. Every published coverage label derives from here.

    ADR-032 **Correction 1** exists because the original table labelled its rungs from the
    *filler's* token count — the whole synthetic text — rather than from what the sliced
    windows actually span. The two coincide only while the filler is short. At the top rung
    they diverged: 4082 claimed against 3978 spanned, so the published bound case claimed a
    coverage it did not have, contradicting the ADR's own full-coverage guarantee. A label
    that is computed cannot drift from the geometry it describes; one that is observed can.
    """
    return 0 if n_windows < 1 else WINDOW_CONTENT_TOKENS + (n_windows - 1) * WINDOW_STEP


def windows_for_tokens(n_tokens: int) -> int:
    """Windows needed to cover `n_tokens` — the inverse of `coverage_tokens`.

    This is what ADR-034 Part C has the detector compute from its own single tokenization
    pass, so the harness and the detector agree by construction rather than by coincidence.
    Verified against the live tokenizer at 3978 / 4000 / 4080 tokens (52 / 53 / 54 windows,
    no unscanned tail in any case).
    """
    if n_tokens <= WINDOW_CONTENT_TOKENS:
        return 1
    return 1 + math.ceil((n_tokens - WINDOW_CONTENT_TOKENS) / WINDOW_STEP)


#: Windows needed for FULL coverage of the policy bound: 53, not 52.
#:
#: The old 52 came from slicing a filler that overshot the bound, and 52 windows span 3978
#: tokens — a 22-token unscanned tail at a 4000-token bound. 53 is what the detector will
#: compute at the real bound, so 53 is what gets measured and published (Correction 1 item 1:
#: measure what the implementation will do, not what the harness used to do).
BOUND_WINDOWS = windows_for_tokens(POLICY_BOUND_TOKENS)

#: Window counts to measure. 1 is the single-window case the respecified budget still covers;
#: the top of the range is the full-coverage count for the policy bound. Powers of two in
#: between locate the batch-capacity knee without measuring 53 separate points.
WINDOW_COUNTS = (1, 2, 4, 8, 16, 32, BOUND_WINDOWS)

#: Batch sizes for the capacity curve, measured at the bound's window count.
BATCH_SIZES = (1, 2, 4, 8, 16, 32, BOUND_WINDOWS)

# ADR-032 Correction 1 item 3 — the guard that makes the defect unreproducible. A harness
# whose top rung under-covers the bound publishes a full-coverage claim it cannot support,
# which is exactly what shipped the first time. Checked at import so it fires before any
# measurement runs, not after the artifact is written.
if coverage_tokens(max(WINDOW_COUNTS)) < POLICY_BOUND_TOKENS:
    raise AssertionError(
        f"top rung {max(WINDOW_COUNTS)} windows spans "
        f"{coverage_tokens(max(WINDOW_COUNTS))} tokens < policy bound "
        f"{POLICY_BOUND_TOKENS}: the bound case would under-cover (ADR-032 Correction 1)"
    )

def _reps_for(n_windows: int, reps: int) -> int:
    """Reps for the **batch curve**, scaled down as the work per rep grows.

    The batch curve publishes **p50 only** (ADR-032's batching paragraph reads medians), and a
    median of 10 samples is a median, so its points stay cheap.

    **The ladder deliberately does not use this** — ADR-032 Correction 1 item 3. The ladder
    publishes percentiles, and `_percentiles_are_distinct` is False below n=40: at n=10 both
    `int(0.95*9)` and `int(0.99*9)` are 8, so a "p99" from 10 samples is `samples[8]`, the
    second-worst of ten, wearing a p99 label. ADR-032's first table did exactly that at its four
    largest rungs — the figures were real, the percentile they claimed was not, and the symptom
    was a bound-case "P99" that moved 10.9% between two runs whose p50s agreed to 1.2%. The
    ladder therefore runs full `reps` at every rung and pays the wall-clock for it.
    """
    if n_windows >= 32:
        return max(5, reps // 4)
    if n_windows >= 8:
        return max(10, reps // 2)
    return reps


# `load_stamp`, `QUIET_LOAD1_MAX` and `quiet_verdict` live in `eval/host_load.py` — one
# definition shared with `bench_latency`, so 06 §8's quiet-host rule reads the same field in
# either artifact instead of two harnesses drifting apart (AGENTS.md §7).


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


def _tokenize_windows(text: str, tok: Any) -> Any:
    """THE windowing call. Timed by `_time_tokenize` and sliced by `_windows_for`, so the
    tokenization figure this harness publishes measures the same code the ladder feeds from.
    """
    return tok(text, truncation=True, max_length=WINDOW_TOKENS, stride=WINDOW_OVERLAP,
               return_overflowing_tokens=True, padding="max_length", return_tensors="np")


#: A word that costs exactly one WordPiece token, for padding filler to an exact token count.
#: Asserted at use rather than trusted: `_filler_of_exactly` fails loudly if the count is off.
PAD_WORD = "a"


def _filler_of_exactly(target_tokens: int, tok: Any) -> str:
    """Filler trimmed to **exactly** `target_tokens` tokens.

    `synthetic_filler` overshoots — it length-checks every 64 words, so asking for 4000 yields
    4082. That overshoot is the whole provenance of the Correction 1 coverage defect, and it
    matters again here: the tokenization figure ADR-034 Part B labels "bound" must be measured
    at the **policy bound of 4000 tokens**, not at a filler that happens to reach 4082 and needs
    54 windows. Trimmed word-by-word from a text known to overshoot, then asserted exact.
    """
    words = synthetic_filler(target_tokens, tok).split()
    lo, hi = 0, len(words)                          # largest prefix at or under the target
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(tok(" ".join(words[:mid]))["input_ids"]) <= target_tokens:
            lo = mid
        else:
            hi = mid - 1
    parts = words[:lo]
    # No word boundary need land on `target_tokens` — words carry 1-3 tokens each — so the
    # remainder is padded with a word known to cost exactly one token. Verified, not assumed:
    # the exact-count assertion below is what makes the label "4000 tokens" true.
    while len(tok(" ".join(parts))["input_ids"]) < target_tokens:
        parts.append(PAD_WORD)
    text = " ".join(parts)
    have = len(tok(text)["input_ids"])
    if have != target_tokens:
        raise RuntimeError(f"cannot hit {target_tokens} tokens exactly; nearest is {have}")
    return text


def _windows_for(text: str, tok: Any, n_windows: int) -> Any:
    """Tokenize `text` into padded windows and return the first `n_windows` of them.

    Every window is padded to exactly `WINDOW_TOKENS` so a batch is rectangular and each window
    costs the same as a full one. That is deliberately the worst case: a real last window is
    shorter and cheaper, and reporting the cheaper figure would understate the bound.
    """
    enc = _tokenize_windows(text, tok)
    have = enc["input_ids"].shape[0]
    if have < n_windows:
        raise RuntimeError(f"filler yielded {have} windows, need {n_windows}")
    return {k: v[:n_windows] for k, v in enc.items() if k != "overflow_to_sample_mapping"}


def _time_passes(one_pass: Any, reps: int, calls: int) -> dict[str, Any]:
    """Time `reps` repetitions of `one_pass`, after one cold pass and two warmups.

    One definition of the timing protocol, shared by inference and tokenization so the two
    figures are comparable rather than merely adjacent.
    """
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
        "calls": calls,
        "cold_ms": round(cold_ms, 2),
        "p50": round(statistics.median(samples), 2),
        "p95": round(samples[int(0.95 * (n - 1))], 2),
        "p99": round(samples[int(0.99 * (n - 1))], 2),
        "max": round(samples[-1], 2),
        # Self-describing so the re-derivation check is mechanical rather than a reader's
        # arithmetic: False means p95 and p99 are ONE order statistic and neither may be
        # published as a percentile (ADR-032 Correction 1 item 3).
        "percentiles_resolved": _percentiles_are_distinct(n),
    }


def _time_calls(sess: Any, feeds: list[dict[str, Any]], reps: int) -> dict[str, Any]:
    """Time `reps` whole-request passes: every feed in `feeds` run once."""
    def one_pass() -> None:
        for feed in feeds:
            sess.run(None, feed)

    return _time_passes(one_pass, reps, len(feeds))


def _time_tokenize(text: str, tok: Any, reps: int) -> dict[str, Any]:
    """Time the windowing tokenization ADR-032's table excludes and a detector cannot.

    ADR-034 Part B publishes a tokenization table and **no script in this repo measured it** —
    the figures had no derivable source, and one of them (`fixed_ms`) grounds a production
    ceiling. This is that source (Correction 1 item 3: a figure gains a derivation or loses the
    claim). Single-threaded work regardless of the ONNX thread setting, so it is measured under
    both settings as a cross-check rather than because it should differ.
    """
    def one_pass() -> None:
        _tokenize_windows(text, tok)

    return _time_passes(one_pass, reps, 1)


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
    """One thread setting: window-count ladder + batch curve + tokenization curve.

    Three load stamps bracket the phases (Correction 1 item 2). `load_before_batch_curve` is
    not decoration: the batch curve is the phase a concurrent export poisoned, and it is the
    phase whose points are cheapest (10 reps), so it is the one a transient can ruin whole.
    """
    run: dict[str, Any] = {"threads": threads, "reps": reps}
    # A DIAGNOSTIC, not the citability stamp. `_measure` runs once per thread setting, and load
    # averages decay over ~60 s, so the second call's "start" reads back the first call's own
    # load — measured at 6.66 on a host that was quiet, which under `QUIET_LOAD1_MAX` would
    # condemn a clean run. The stamp that certifies the host is taken once, before any phase,
    # at the artifact's top level (`load_at_process_start`).
    run["load_at_phase_start"] = load_stamp()
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
        run["window_step"] = WINDOW_STEP
        run["window_content_tokens"] = WINDOW_CONTENT_TOKENS
        run["bound_windows"] = BOUND_WINDOWS
        run["bound_coverage_tokens"] = coverage_tokens(BOUND_WINDOWS)

        # Tokenization — the span ADR-032's table excludes and ADR-034 Part B publishes.
        # Lengths are DERIVED (the coverage of 2 and 8 windows, and the policy bound itself),
        # and the bound row is measured at exactly 4000 tokens rather than at whatever the
        # filler happens to reach. Part B's old "4080 tokens | bound" row was neither: 4080
        # needs 54 windows, so it labelled a past-the-bound measurement as the bound.
        run["tokenize"] = {}
        for target in (coverage_tokens(2), coverage_tokens(8), POLICY_BOUND_TOKENS):
            try:
                exact = _filler_of_exactly(target, tok)
            except RuntimeError as exc:            # no word boundary lands on `target`
                run["tokenize"][str(target)] = {"error": str(exc)}
                continue
            row = _time_tokenize(exact, tok, reps)
            row["tokens"] = target
            row["chars"] = len(exact)
            row["windows"] = windows_for_tokens(target)     # derived, not observed
            run["tokenize"][str(target)] = row

        # The ladder runs FULL reps at every rung — see `_reps_for`. A p99 published from 10
        # samples is `samples[8]` wearing a p99 label, which is the defect class Correction 1
        # exists to remove, so the wall-clock is paid instead.
        run["ladder"] = {}
        for n_windows in WINDOW_COUNTS:
            win = _windows_for(text, tok, n_windows)
            row: dict[str, Any] = {
                "windows": n_windows,
                # DERIVED from the geometry, never from `filler_tokens` (Correction 1).
                "covers_tokens": coverage_tokens(n_windows),
            }
            row["sequential"] = _time_calls(sess, _feeds(win, fed, 1), reps)
            row["batched"] = _time_calls(sess, _feeds(win, fed, n_windows), reps)
            run["ladder"][str(n_windows)] = row

        run["load_before_batch_curve"] = load_stamp()
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
    # Taken after the work, so it is high by construction — `load_at_process_start` is the stamp
    # that certifies a quiet host; `eval/host_load.py` says so where a reader will look.
    run["load_at_end"] = load_stamp()
    return run


def contamination_signals(
    run: dict[str, Any],
    *,
    spike_tolerance: float = 0.08,
    cross_tolerance: float = 0.12,
    cross_deficit: float = 0.15,
    dispersion_max: float = 1.25,
    cold_floor: float = 0.90,
) -> list[str]:
    """Rungs whose numbers disagree with the rest of THIS artifact.

    Load stamps cannot certify a measurement. Load averages lag by ~60 s, so a 20 s transient
    inside a 3-minute phase poisons two rungs and leaves both bracketing stamps clean — which is
    exactly what happened to the first publication run. These checks read the *measurement*
    instead of the machine.

    A first version of this asserted per-window cost is non-increasing in window count. That was
    a derivation the measurement does not have, i.e. the very defect Correction 1 exists to
    remove, so it is recorded here rather than quietly dropped. Two ways it was wrong:

    * The batched column at rung `n` is ONE call at batch size `n`. Window count and batch size
      are the same axis there, so per-window cost rising with `n` is the batch-efficiency curve
      ADR-032 set out to measure, not contamination.
    * The sequential column is not flat either: at 6 threads per-window cost climbs ~11% across
      the ladder in every run measured (a rung feeding 53 distinct tensors has worse cache
      locality than one reusing a single tensor). Reproducible, therefore not a defect.

    What survives is that the *shape* reproduces. Three checks, each with its own blind spot:

    1. LOCAL SPIKE (sequential): an interior rung more than `spike_tolerance` above the mean of
       its two neighbours. Blind to the endpoints and to a transient long enough to lift a whole
       neighbourhood.
    2. CROSS-MEASUREMENT: ladder-batched at rung `n` and `batch_curve` at batch `n` time the same
       op from different loop structures. Beyond `cross_tolerance` one of them was disturbed.
       Expect a systematic *negative* offset at low `n` — the curve's p50 covers a full top-rung
       sweep including remainder handling, the ladder's a single call — so only excess above the
       tolerance is reported, and the batch curve's smaller rep count makes its p50 the noisier
       of the two.
    3. TAIL DISPERSION: p99/p50 above `dispersion_max`. The WEAKEST of the four and stated as
       such: clean artifacts here reach 1.191 while the contaminated run reached 1.245, so the
       bands nearly touch and this check did NOT catch it (1.245 < 1.25 — checks 1 and 2 did).
       It is retained as a backstop for a gross tail blowup, not as a discriminator, and the
       threshold is deliberately NOT tuned down to 1.22 to claim the catch: that would be a
       cutoff fitted to two samples.
    4. COLD RATIO: `cold_ms / p50` below `cold_floor`. NOT the physical law it looks like — a
       first call genuinely can beat the median, because thermal and frequency drift over the
       reps lifts the median above it; clean artifacts here bottom out at 0.926. It is an
       outlier test, and it is the only one of the four that catches an inflated `batch_curve`
       p50 whose own rungs stay self-consistent (the committed artifact: 0.800 at batch 2).

    Tolerances are empirical, from three artifacts of this harness on this host: clean adjacent
    rungs agree to ~2% and clean cross-measurement to ~6%, while the contamination they must
    catch showed up at 21% and 18%. They are not derived from anything, and this docstring is
    the whole of their provenance.
    """
    out: list[str] = []
    ladder = run.get("ladder", {})
    keys = sorted(ladder, key=int)

    per_window = [(ladder[k]["windows"], ladder[k]["sequential"]["p50"] / ladder[k]["windows"])
                  for k in keys]
    for i in range(1, len(per_window) - 1):
        (_, lo), (w, mid), (_, hi) = per_window[i - 1], per_window[i], per_window[i + 1]
        neighbours = (lo + hi) / 2
        if mid > neighbours * (1.0 + spike_tolerance):
            out.append(
                f"LOCAL SPIKE sequential {w}w: {mid:.2f} ms/window is "
                f"{(mid / neighbours - 1) * 100:+.0f}% vs its neighbours' mean {neighbours:.2f}"
            )

    curve = run.get("batch_curve", {})
    if curve and keys:
        top = max(int(k) for k in keys)
        for k in keys:
            row = ladder[k]; n = row["windows"]
            point = curve.get(str(n))
            if point is None:
                continue
            lad, cv = row["batched"]["p50"] / n, point["p50"] / top
            if lad > cv * (1.0 + cross_tolerance):
                out.append(
                    f"CROSS-MEASUREMENT {n}w: ladder-batched {lad:.2f} ms/window exceeds "
                    f"batch_curve's {cv:.2f} by {(lad / cv - 1) * 100:+.0f}%"
                )
            elif lad < cv * (1.0 - cross_deficit):
                # Attributed to the CURVE, not the ladder: across three artifacts the ladder's
                # batched p50 at a given rung agrees to ~2% while the curve's is what moves.
                out.append(
                    f"CROSS-MEASUREMENT {n}w: batch_curve's {cv:.2f} ms/window exceeds "
                    f"ladder-batched {lad:.2f} by {(cv / lad - 1) * 100:+.0f}% — the curve "
                    f"point looks inflated (expected deficit is <=9%, from the top rung's "
                    f"remainder handling)"
                )

    for k in keys:
        row = ladder[k]
        for mode in ("sequential", "batched"):
            p50, p99 = row[mode]["p50"], row[mode]["p99"]
            if p50 > 0 and p99 / p50 > dispersion_max:
                out.append(
                    f"TAIL DISPERSION {row['windows']}w {mode}: p99/p50 = {p99 / p50:.3f}"
                )

    for section in ("ladder", "batch_curve"):
        for key in sorted(run.get(section, {}), key=int):
            entry = run[section][key]
            cells = ([("", entry)] if "p50" in entry
                     else [(m, entry[m]) for m in ("sequential", "batched") if m in entry])
            for mode, cell in cells:
                cold, p50 = cell.get("cold_ms"), cell.get("p50")
                if cold and p50 and cold / p50 < cold_floor:
                    where = f"{section}/{key}" + (f"/{mode}" if mode else "")
                    out.append(
                        f"COLD RATIO {where}: cold_ms/p50 = {cold / p50:.3f} — the median "
                        f"exceeds the first call by more than any clean run here"
                    )
    return out


def _render(art: dict[str, Any]) -> str:
    """Human-readable table. `—` where p95 and p99 are one order statistic (ADR-031's rule).

    Takes the whole artifact rather than just `runs`, because the stamp that certifies the host is
    artifact-level — one per process — and for one revision of this file it was therefore printed
    NOWHERE. A citability rule a reader cannot see in the report is a rule nobody applies, so the
    verdict leads the output.
    """
    lines: list[str] = []
    certifying = art.get("load_at_process_start")
    lines.append(f"{'=' * 96}")
    lines.append(f"code: {reproducibility_verdict(art.get('code'))}")
    if certifying is None:
        lines.append("host load at process start: NOT RECORDED — artifact predates the stamp, "
                     "NOT CITABLE (06 §8)")
    else:
        lines.append(
            f"host load at process start: {certifying['load1']} / {certifying['load5']} / "
            f"{certifying['load15']} (1/5/15)  cpus={certifying.get('cpus', '?')}  "
            f"quiet_max={QUIET_LOAD1_MAX}  [{quiet_verdict(certifying)}]")
    for run in art.get("runs", []):
        lines.append(f"\n{'=' * 96}")
        lines.append(f"threads={run['threads']}  model={MODEL_ID}  int8"
                     f"  window={run.get('window_tokens')}tok"
                     f"  overlap={run.get('window_overlap')}"
                     f"  step={run.get('window_step')}")
        if "error" in run:
            lines.append(f"  ERROR {run['error']}")
            continue
        # `filler_tokens` is PROVENANCE, not a coverage label. Labelling rungs from it is
        # the ADR-032 Correction 1 defect: the filler overshoots the target (it length-checks
        # every 64 words), so its token count exceeds what the sliced windows span. Coverage
        # is printed per rung below, derived from the geometry.
        lines.append(f"filler: {run['filler_tokens']} tokens / {run['filler_chars']} chars"
                     f"   (synthetic — no corpus text; provenance only, NOT a coverage label)")
        bw, bc = run.get("bound_windows"), run.get("bound_coverage_tokens")
        if bw is not None:
            lines.append(f"policy bound {POLICY_BOUND_TOKENS} tokens -> {bw} windows "
                         f"spanning {bc} tokens (full coverage, no tail)")
        phase, mid = run.get("load_at_phase_start"), run.get("load_before_batch_curve")
        if phase is not None:
            lines.append(f"  phase-start load {phase['load1']} · before batch curve "
                         f"{mid['load1'] if mid else '?'} — DIAGNOSTIC ONLY (this process is "
                         f"itself the load by now; citability reads load_at_process_start)")
        for signal in contamination_signals(run):
            lines.append(f"  !! {signal}")
        lines.append(f"{'=' * 96}")
        lines.append(f"  budget {BUDGET_MS} ms is a PER-WINDOW figure; totals below are "
                     f"whole-request")
        lines.append("")
        if run.get("tokenize"):
            lines.append("  tokenization (windowing pass only; ADR-032's table excludes it):")
            lines.append(f"  {'tokens':>7} {'wins':>5} {'chars':>7} {'n':>3} {'p50':>8} "
                         f"{'p99':>8}")
            for key in sorted(run["tokenize"], key=int):
                t = run["tokenize"][key]
                if "error" in t:
                    lines.append(f"  {int(key):>7}   ERROR {t['error'][:60]}")
                    continue
                p99 = f"{t['p99']:8.2f}" if t.get("percentiles_resolved") else f"{'—':>8}"
                lines.append(f"  {t['tokens']:>7} {t['windows']:>5} {t['chars']:>7} "
                             f"{t['n']:>3} {t['p50']:8.2f} {p99}")
            lines.append("")
        lines.append(f"  {'wins':>5} {'covers':>7} {'mode':<11} {'calls':>5} {'n':>3} "
                     f"{'p50':>8} {'p95':>8} {'p99':>8} {'max':>8}  {'per-win p50':>11}")
        for key in sorted(run["ladder"], key=int):
            row = run["ladder"][key]
            for mode in ("sequential", "batched"):
                b = row[mode]
                distinct = _percentiles_are_distinct(b["n"])
                p95 = f"{b['p95']:8.2f}" if distinct else f"{'—':>8}"
                p99 = f"{b['p99']:8.2f}" if distinct else f"{'—':>8}"
                per = b["p50"] / row["windows"]
                covers = row.get("covers_tokens", coverage_tokens(row["windows"]))
                lines.append(f"  {row['windows']:>5} {covers:>7} {mode:<11} {b['calls']:>5} "
                             f"{b['n']:>3} {b['p50']:8.2f} {p95} {p99} {b['max']:8.2f}  "
                             f"{per:11.2f}")
        lines.append("")
        lines.append(f"  batch capacity curve at {max(WINDOW_COUNTS)} windows "
                     f"({coverage_tokens(max(WINDOW_COUNTS))} tokens covered):")
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
    # 40, not 20: `_percentiles_are_distinct` is False below 40, so a default run of this
    # harness used to publish ladder "P99"s that were `samples[8]` — the exact defect ADR-032
    # Correction 1 exists to remove, reachable by invoking the fixed harness with no arguments.
    # A cheaper smoke run is still available via `--reps`; `percentiles_resolved` and
    # `eval.check_derivations` are what stop one being published.
    ap.add_argument("--reps", type=int, default=40)
    ap.add_argument("--out", default="reports/spike_window_latency.json")
    ap.add_argument("--render", metavar="FILE",
                    help="re-render an existing artifact; measures nothing")
    args = ap.parse_args(argv)

    if args.render:
        art = json.loads(Path(args.render).read_text())
        print(_render(art))
        return 0

    import onnxruntime as ort
    # Taken BEFORE any measurement work, and this is the one 06 §8 reads: it is the only stamp
    # whose value is about the host rather than about this harness's own earlier phases.
    process_start_load = load_stamp()
    art: dict[str, Any] = {
        "spike": "ADR-032 — full-coverage strided windows for tier2_injection",
        "model_id": MODEL_ID,
        "budget_ms": BUDGET_MS,
        "backend": "onnx_int8",
        "filler": "synthetic (deterministic); no corpus text",
        "window": {"tokens": WINDOW_TOKENS, "overlap": WINDOW_OVERLAP,
                   "policy_bound_tokens": POLICY_BOUND_TOKENS},
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "onnxruntime": ort.__version__,
        "load_at_process_start": process_start_load,
        "code": git_stamp(),
        "runs": [],
    }
    for threads in (args.threads or [6, 1]):
        art["runs"].append(_measure(threads, args.reps))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(art, indent=2) + "\n")
    print(_render(art))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
