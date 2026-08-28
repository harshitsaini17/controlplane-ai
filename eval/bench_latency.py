"""Latency benchmark -> reports/latency_report.md.

Implements 06 §4, incl. the NORMATIVE `total_attributable_overhead_ms` definition and `--check`
assertion mode (the NFR-P-001/002 D3 tripwire).

**Every overhead figure is read back out of the audit record, never recomputed here.**
`controlplane.gateway.pipeline.total_attributable_overhead_ms` is the single implementation of the 06 §4
formula, and 06 §4 says that definition is used by "05 §5, the audit record, and every report
— no ad-hoc variants". A benchmark that re-derived the number from its own stopwatch would be
measuring a second, unspecified quantity that happened to look similar, and the two could
drift without either being wrong on its own terms. So this module fires requests and reads
`latency_json.total_attributable_overhead_ms` back out of `audit_records`.

**Streaming and non-streaming are tabulated separately because they are different
quantities**, not merely different configurations (06 §4): streaming sums measured hold
intervals, non-streaming subtracts the upstream call from wall-clock. NFR-P-001 is scoped in
its own wording to "**streaming pipelines** (per the normative definition in 06 §4)", so
`--check` gates the P50 < 40 ms / P99 < 100 ms thresholds on the streaming table only. The
non-streaming table is reported in full and gated by NFR-P-002 alone. Applying a streaming
threshold to a subtraction-derived figure would be inventing a requirement.

**The headline number is cadence-independent by construction, and that is verified rather
than asserted.** 06 §4 excludes upstream token wait from `total_attributable_overhead_ms`, so changing
the stub's inter-token delay must not move the figure. `--cadence-ms` exists so that property
is testable (`test_overhead_is_independent_of_token_cadence`), which is also what makes a
fast default defensible: a slow "realistic" cadence would buy realism only in the one
component the metric excludes.

**No number here is provider-derived.** The upstream is a stub, so the ADR-018 gate is
evaluated and recorded as non-binding — the same scoping `run_all.py` states. The 30-request
real-provider row 06 §4 asks for is **opt-in** (`--live`) and reported as not-run otherwise:
the shipped active provider is dev-class, and a dev-class latency figure is not a publishable
measurement (ADR-018), so producing one silently would be worse than its absence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from controlplane.audit.records import canonical_view
from controlplane.detectors.base import BUDGETS_MS, Stage
from controlplane.gateway.app import Gateway, create_app
from controlplane.gateway.config import (
    TaintedDataError,
    load_gateway_config,
    require_measured_upstream,
)
from controlplane.gateway.ingress import HEADER_REQUEST_ID, HEADER_USE_CASE
from controlplane.gateway.pipeline import LANES, LIVE
from controlplane.gateway.sentence_buffer import Segmentation
from controlplane.gateway.sse_proxy import UpstreamResponse
from controlplane.policy.store import PolicyStore
from controlplane.telemetry.metrics import MetricsRegistry, percentile
from eval.validate_dataset import (
    DATASET_DIR,
    FROZEN_COMMIT,
    USE_CASES,
    check_freeze,
    dataset_digest,
)

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
DEFAULT_OUT = REPORTS_DIR / "latency_report.md"

#: 06 §4: "300 requests replayed from dataset traffic mix".
DEFAULT_REQUESTS = 300

#: 06 §4: "then 30 requests against the real provider for an end-to-end sanity row".
LIVE_REQUESTS = 30

#: Inter-token delay for the stub's canned SSE. Small by default — see the module docstring:
#: cadence lands entirely in the token wait that 06 §4 excludes, so a slow "realistic" value
#: would multiply runtime without moving the measured figure.
DEFAULT_CADENCE_MS = 0.5

#: NFR-P-001, streaming pipelines only, on demo hardware.
#: NFR-P-001 as **re-scoped by ADR-030**: the targets attach to the two holds a user actually
#: waits through, not to the per-request sum. Derived in ADR-030 from the 04 §2 budgets under the
#: parallel-at-Tier-2 execution model — `input_hold` P99 50 ms covers its 25 ms worst case,
#: `sentence_hold` P99 100 ms covers the 60 ms `on_sampled` composition.
NFR_P_001: dict[str, dict[str, float]] = {
    "input_hold_ms": {"p50": 40.0, "p99": 50.0},
    "sentence_holds_ms": {"p50": 40.0, "p99": 100.0},
}

#: Printed only when a run carries **no** per-hold series at all, which is the third state —
#: neither "met" nor "failed" (M-10 / ADR-027 Amendment 1). The gateway emits both series as of
#: M-20, so on a normal run this never appears; it survives for the case that would otherwise
#: be silent — a batch with no streaming samples, where an empty violation list would read as a
#: pass over a requirement nothing was measured against.
NFR_P_001_NOT_MEASURED = (
    "**NFR-P-001: `not measured`.** ADR-030 scopes it to `input_hold_ms` and "
    "`sentence_holds_ms` on **streaming** pipelines, and this run recorded neither — so it "
    "neither meets nor fails NFR-P-001, and the empty violation list above is not a pass. The "
    "previous per-request target is **withdrawn**, so nothing else here stands in for it."
)

#: 01 §3 pipeline labels, so the report speaks the docs' vocabulary.
UC_LABEL: dict[str, str] = {
    "support_bot": "UC-1",
    "hr_copilot": "UC-2",
    "finance_advisor": "UC-3",
}


def load_corpus(dataset_dir: Path = DATASET_DIR) -> list[dict[str, Any]]:
    """Every frozen case, in a deterministic order (filename, then file order).

    Sorted by filename so the replay sequence does not depend on directory iteration order —
    two runs on the same freeze must issue the same requests, or the percentiles are not
    comparable between them.
    """
    cases: list[dict[str, Any]] = []
    for path in sorted(dataset_dir.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                row["_file"] = path.name
                cases.append(row)
    if not cases:
        raise SystemExit(f"no cases found in {dataset_dir}")
    return cases


def traffic_mix(
    cases: Sequence[dict[str, Any]], requests: int, use_cases: Sequence[str] = USE_CASES
) -> list[tuple[str, dict[str, Any]]]:
    """`requests` (use_case, case) pairs replayed from the frozen corpus.

    06 §4 says "replayed from dataset traffic mix" without fixing the mapping, so this fills
    a gap rather than contradicting one (logged MINOR). Two properties are what the gap needs:

    * **Balanced across use cases.** Each pipeline gets `requests // len(use_cases)` requests,
      so a per-use-case percentile rests on an equal sample. An unbalanced mix would make the
      tables silently incomparable.
    * **Deterministic and cycling.** The corpus is 280 cases and the default run is 300
      requests, so the sequence cycles rather than sampling randomly — a random mix would make
      two runs on one freeze produce different numbers with no way to tell drift from noise.

    The whole corpus is used rather than a "realistic" subset: a mix weighted toward clean
    traffic would report the overhead of the cheap path as the headline figure, and the
    interesting cost is the detector work that risky content triggers.
    """
    if requests < len(use_cases):
        raise SystemExit(f"requests must be >= {len(use_cases)} to cover every use case")
    per = requests // len(use_cases)
    out: list[tuple[str, dict[str, Any]]] = []
    for index, use_case in enumerate(use_cases):
        # Offset per use case so the three pipelines do not all replay the same prefix —
        # otherwise a 100-request run would exercise only `borderline.jsonl` and part of
        # `clean.jsonl`, and `pii.jsonl` would never be reached.
        offset = (index * len(cases)) // len(use_cases)
        for i in range(per):
            out.append((use_case, cases[(offset + i) % len(cases)]))
    return out


class _StubStream:
    """A duck-typed `UpstreamDispatcher` streaming canned SSE at a set cadence (06 §4).

    Yields **word by word** rather than one blob: the streaming path's cost is per-sentence
    holds, and a single-chunk response would collapse every hold into one, reporting the
    overhead of a pipeline nobody runs.

    `cadence_ms` sleeps between chunks so sentence boundaries arrive over time as they do
    against a real provider. That wait is upstream time and 06 §4 excludes it from the
    headline figure — the sleep exists to make the *shape* realistic, not the number.
    """

    def __init__(self, text: str, *, cadence_ms: float = DEFAULT_CADENCE_MS) -> None:
        self.text = text
        self.cadence_ms = cadence_ms
        self.calls = 0

    def resolve_model(self, tier: str, provider: Any = None) -> str:
        return "stub-model"

    async def complete(self, messages, *, tier="small", provider=None, extra=None):
        self.calls += 1
        # A non-streaming provider still takes time, and 06 §4's non-streaming formula
        # subtracts exactly that. Sleeping the whole cadence budget at once is the closest
        # honest analogue of one blocking call.
        if self.cadence_ms:
            await asyncio.sleep(self.cadence_ms * len(self.text.split()) / 1000.0)
        return UpstreamResponse(
            text=self.text, model_used="stub-model", prompt_tokens=11, completion_tokens=22
        )

    async def stream_text(self, messages, *, tier="small", provider=None, extra=None):
        self.calls += 1
        for word in self.text.split(" "):
            if self.cadence_ms:
                await asyncio.sleep(self.cadence_ms / 1000.0)
            yield word + " "


@dataclass
class Sample:
    """One request's measured latency, as recorded by the gateway itself."""

    use_case: str
    case_id: str
    streaming: bool
    #: The 06 §4 figure, read back from `latency_json` — never recomputed here.
    overhead_ms: float
    upstream_ms: float
    #: This benchmark's OWN wall-clock around the call. Not a `latency_json` key and not
    #: comparable to `overhead_ms`: it includes `TestClient`'s ASGI transport cost, which is
    #: harness overhead a real client would not pay. Carried only to build 06 §4's separate
    #: reference row, and labelled as such wherever it is printed.
    wall_ms: float
    http_status: int
    verdict: str
    #: The ADR-030 per-hold series, read back from `latency_json` — one entry per sentence
    #: held. Emitted by the gateway as of M-20; still defaulted here, because empty means
    #: "not recorded" and never "zero holds": a streaming request that released a sentence
    #: necessarily held it, so a zero-length series is an absent measurement, not a fast one.
    hold_series: tuple[float, ...] = ()
    #: The ADR-030 input-lane hold. `None` for the same reason, kept distinct from 0.0.
    input_hold_ms: float | None = None

    @property
    def reference_delta_ms(self) -> float:
        """`wall − upstream`: the 06 §4 reference row, explicitly NOT the headline number.

        For a streaming pipeline this exceeds `overhead_ms` by the relay and transport time
        that is neither a per-sentence hold nor a token wait. `pipeline.total_attributable_overhead_ms`
        declines to clamp that gap away and says it belongs here as a reported row, so here it
        is — as an upper bound a reader can see, rather than a discrepancy they have to infer.
        """
        return max(0.0, self.wall_ms - self.upstream_ms)


@dataclass
class Batch:
    """One benchmark run: the samples plus the registry the detectors reported into."""

    samples: list[Sample] = field(default_factory=list)
    metrics: MetricsRegistry = field(default_factory=MetricsRegistry)
    requests_attempted: int = 0
    errors: list[str] = field(default_factory=list)
    #: The very `PolicyStore` the requests were evaluated against. Carried rather than
    #: reconstructed in `render()`: a hot reload between the run and the report would
    #: otherwise let the tables be split streaming/non-streaming by a `streaming` flag no
    #: request ever saw. Same defect class as the one fixed in `eval/fault_injection.py`.
    store: PolicyStore | None = None

    def by_stream_mode(self, streaming: bool) -> list[Sample]:
        return [s for s in self.samples if s.streaming is streaming]

    def overheads(self, use_case: str | None = None, *, streaming: bool | None = None
                  ) -> list[float]:
        return [
            s.overhead_ms for s in self.samples
            if (use_case is None or s.use_case == use_case)
            and (streaming is None or s.streaming is streaming)
        ]

    def _matching(self, use_case: str | None, streaming: bool | None) -> list[Sample]:
        return [
            s for s in self.samples
            if (use_case is None or s.use_case == use_case)
            and (streaming is None or s.streaming is streaming)
        ]

    def input_holds(self, use_case: str | None = None, *, streaming: bool | None = None
                    ) -> list[float]:
        """The ADR-030 input-lane holds. One per request; `None` entries are dropped.

        Dropped rather than zero-filled: an absent `input_hold_ms` is a request whose hold was
        never recorded, and a zero would enter the percentile as a real, very fast hold.
        """
        return [s.input_hold_ms for s in self._matching(use_case, streaming)
                if s.input_hold_ms is not None]

    def sentence_holds(self, use_case: str | None = None, *, streaming: bool | None = None
                       ) -> list[float]:
        """Every per-sentence hold, **flattened across requests** (ADR-030).

        Flattening is the point rather than a convenience: NFR-P-001 targets each hold a user
        waits through, so the population is holds, not requests. Averaging per request first
        would let a 10-sentence response's slow hold hide behind its nine fast ones — exactly
        the per-request smoothing the re-scope exists to stop.
        """
        return [h for s in self._matching(use_case, streaming) for h in s.hold_series]


def run_batch(
    mix: Sequence[tuple[str, dict[str, Any]]], *, cadence_ms: float = DEFAULT_CADENCE_MS
) -> Batch:
    """Replay `mix` against one gateway and collect what it recorded.

    **One gateway and one metrics registry across the whole batch**, because the per-detector
    histograms NFR-P-002 is checked against must aggregate over every request. A fresh
    registry per request would leave 300 single-observation series whose percentiles are
    meaningless.

    `TestClient` is not context-managed: that would fire the FR-GW-006 startup canary
    (ADR-028), whose stub verdict is irrelevant here and whose dispatch would be timed into
    the first request.
    """
    store = PolicyStore()
    store.load()
    batch = Batch(store=store)

    with tempfile.TemporaryDirectory() as tmp:
        gateway = Gateway(
            store=store,
            dispatcher=_StubStream("placeholder", cadence_ms=cadence_ms),
            metrics=batch.metrics,
            db_path=str(Path(tmp) / "bench.db"),
            key_map={},
        )
        client = TestClient(create_app(gateway), raise_server_exceptions=False)

        for use_case, case in mix:
            batch.requests_attempted += 1
            text = case["text"]
            # The stub echoes the case text, so the output lane sees the same content the
            # dataset labelled — the detector work being timed is the work that case implies.
            gateway.dispatcher.text = text
            wall_started = time.perf_counter()
            response = client.post(
                "/v1/chat/completions",
                headers={HEADER_USE_CASE: use_case},
                json={"messages": [{"role": "user", "content": text}]},
            )
            wall_ms = (time.perf_counter() - wall_started) * 1000.0
            request_id = response.headers.get(HEADER_REQUEST_ID)
            if request_id is None:
                batch.errors.append(f"{case['case_id']}/{use_case}: no request id (HTTP "
                                    f"{response.status_code})")
                continue
            try:
                view = canonical_view(gateway.conn, request_id)
            except Exception as exc:  # noqa: BLE001
                batch.errors.append(f"{case['case_id']}/{use_case}: {type(exc).__name__}")
                continue

            latency = view["latency"]
            overhead = latency.get("total_attributable_overhead_ms")
            if overhead is None:
                # Recorded as an error rather than skipped silently: a missing overhead value
                # means the audit write path changed, and a percentile computed over the
                # survivors would hide that behind a plausible number.
                batch.errors.append(f"{case['case_id']}/{use_case}: no total_attributable_overhead_ms")
                continue
            upstream = float(latency.get("upstream_ms", 0.0))
            batch.samples.append(
                Sample(
                    use_case=use_case,
                    case_id=case["case_id"],
                    streaming=bool(store.get(use_case).streaming),
                    overhead_ms=float(overhead),
                    upstream_ms=upstream,
                    wall_ms=wall_ms,
                    http_status=response.status_code,
                    verdict=view["verdict"],
                    # Read back rather than recomputed, like every other figure here: these
                    # are the gateway's own hold measurements (M-20). Absence stays absence —
                    # `nfr_p001_measurable()` reads it and the report prints the third state,
                    # so a batch with no streaming samples cannot render as a pass.
                    hold_series=tuple(
                        float(v) for v in (view["latency"].get("sentence_holds_ms") or ())
                    ),
                    input_hold_ms=(
                        float(view["latency"]["input_hold_ms"])
                        if view["latency"].get("input_hold_ms") is not None else None
                    ),
                )
            )
    return batch


# ---------------------------------------------------------------------------
# Percentiles and the NFR gates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Stats:
    """P50/P95/P99 over one series, with the sample size that produced them.

    `n` travels with the numbers because a percentile without its sample size is not a
    measurement (AGENTS.md §7) — a P99 over 12 samples is the max wearing a percentile's name.
    """

    n: int
    p50: float
    p95: float
    p99: float
    minimum: float
    maximum: float

    @classmethod
    def of(cls, values: Sequence[float]) -> Stats | None:
        """`None` for an empty series — never a row of zeros.

        Zeros would read as "measured, and fast", which is the opposite of "not measured".
        """
        if not values:
            return None
        ordered = list(values)
        return cls(
            n=len(ordered),
            p50=percentile(ordered, 50),
            p95=percentile(ordered, 95),
            p99=percentile(ordered, 99),
            minimum=min(ordered),
            maximum=max(ordered),
        )


@dataclass(frozen=True)
class Violation:
    """One NFR breach, in the shape a D3 deviation report needs.

    Carrying `requirement`, `target` and `measured` separately — rather than a formatted
    sentence — is what lets `--check` print a machine-checkable line and the report print a
    table row from the same fact. AGENTS.md §5.4: the response to one of these is a D3
    deviation with the honest number, never a relaxed threshold.
    """

    requirement: str
    subject: str
    metric: str
    target: float
    measured: float

    def line(self) -> str:
        return (f"{self.requirement} {self.subject} {self.metric}: "
                f"{self.measured:.3f} ms exceeds {self.target:.1f} ms")


def check_nfr_p001(batch: Batch) -> list[Violation]:
    """NFR-P-001 as ADR-030 scopes it: the two per-hold series, **streaming only**.

    Before ADR-030 this gated the per-request `gateway_overhead_ms` sum. That quantity is still
    published — as `total_attributable_overhead_ms` — but untargeted, and gating it here would
    assert a requirement the docs no longer contain.

    Two properties worth stating, because both are easy to get wrong in a way that flatters us:

    * **Streaming only.** 01's NFR-P-001 row scopes to streaming pipelines, so a non-streaming
      request's single buffered hold is published but never gated here.
    * **The population is holds, not requests** (see `Batch.sentence_holds`). A percentile over
      per-request means would let one slow hold hide behind a long response's fast ones.

    An empty return is a pass **only if** the series exist; when they do not,
    `nfr_p001_measurable()` is False and the report prints the third state instead. That
    distinction is the whole of M-10 / ADR-027 Amendment 1 applied here.
    """
    violations: list[Violation] = []
    for series, values in (
        ("input_hold_ms", batch.input_holds(streaming=True)),
        ("sentence_holds_ms", batch.sentence_holds(streaming=True)),
    ):
        stats = Stats.of(values)
        if stats is None:
            continue
        targets = NFR_P_001[series]
        for metric, measured in (("P50", stats.p50), ("P99", stats.p99)):
            target = targets[metric.lower()]
            if measured >= target:
                violations.append(Violation("NFR-P-001", series, metric, target, measured))
    return violations


def nfr_p001_measurable(batch: Batch) -> bool:
    """Whether this run carries the series ADR-030 targets.

    Reads the audit records rather than trusting a flag, so the day `app.py` starts emitting
    the holds this returns True without an edit here — and until then no amount of sample
    volume can make the report claim a verdict it has no series for.
    """
    return any(s.hold_series for s in batch.samples)


def detector_stats(batch: Batch) -> dict[str, Stats]:
    """Per-detector latency percentiles, read from the registry the gateway reported into."""
    snapshot = batch.metrics.snapshot()
    series = snapshot.get("cp_detector_latency_ms", {}).get("series", [])
    out: dict[str, Stats] = {}
    for row in series:
        detector = row["labels"]["detector"]
        if row.get("count"):
            out[detector] = Stats(
                n=int(row["count"]),
                p50=float(row["p50"]), p95=float(row["p95"]), p99=float(row["p99"]),
                minimum=float(row["min"]), maximum=float(row["max"]),
            )
    return out


def detector_faults(batch: Batch) -> dict[str, dict[str, float]]:
    """Per-detector fault counts by `fail_mode`, from `cp_detector_failures_total`.

    An absent series here reads as **zero**, not as "never checked" — and that is the one
    place in this module where the M-10 three-state distinction legitimately collapses to
    two. A detector with latency observations demonstrably ran, so "no fault series" can only
    mean no fault occurred. Contrast the latency table, where an absent detector means the
    budget is untested rather than met.
    """
    snapshot = batch.metrics.snapshot()
    series = snapshot.get("cp_detector_failures_total", {}).get("series", [])  # type: ignore[union-attr]
    out: dict[str, dict[str, float]] = {}
    for row in series:
        labels = row["labels"]
        out.setdefault(labels["detector"], {})[labels["fail_mode"]] = float(row["value"])
    return out


def check_nfr_p002(stats: dict[str, Stats]) -> list[Violation]:
    """NFR-P-002 per-detector budgets, gated on **P99**.

    06 §4 asks for "per-detector latency histograms vs NFR-P-002 budgets" without naming the
    percentile the assertion uses, so this fills a gap (logged MINOR): P99, matching the
    percentile NFR-P-001 states explicitly, since a budget is a tail guarantee — a detector
    inside budget at the median and over it at P99 is one that breaches under load.

    Note the budgets are *also* enforced at runtime: `run_with_budget` cancels past the budget
    and raises `DetectorTimeout`. So a P99 at the budget usually means timeouts fired rather
    than that a call ran long, which is why the report prints the fault count beside these
    rows — the two readings need different responses.
    """
    violations: list[Violation] = []
    for detector, stat in sorted(stats.items()):
        budget = BUDGETS_MS.get(detector)
        if budget is None:
            continue
        if stat.p99 >= budget:
            violations.append(Violation("NFR-P-002", detector, "P99", budget, stat.p99))
    return violations


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def sentence_counts(cases: Sequence[dict[str, Any]]) -> list[int]:
    """Segments per case, via the real `Segmentation` — the multiplier the projection needs.

    Measured rather than assumed, because 06 §4's streaming formula is a **sum over
    per-sentence holds**: a per-sentence budget is paid once per sentence, so the sentence
    count is a multiplier on any lane-cost projection, not a footnote to it.
    """
    counts: list[int] = []
    for case in cases:
        seg = Segmentation()
        n = 0
        for word in str(case["text"]).split(" "):
            n += len(seg.feed(word + " "))
        n += len(seg.flush())
        counts.append(max(n, 1))
    return counts


def project_tier2(cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Budget-based forward projection for the two unimplemented tier2 detectors.

    **A projection, not a measurement**, and derived rather than written down: lane
    membership comes from `LANES` and every figure from `BUDGETS_MS`, so a budget or lane
    change moves this section instead of leaving a stale paragraph behind.

    Both readings of lane cost are reported. `run_lane` is **sequential today** and says so
    deliberately (CPU-bound regex passes cannot overlap on one event loop, and `gather` would
    serialize them anyway while corrupting per-detector attribution), so the lane costs the
    **sum**. 02 §4's "fast detectors (parallel)" is a statement about the budget model whose
    parallelism, that same docstring says, "becomes real when Tier-2 arrives" — under which
    the lane would cost the **max**. Reporting both is what makes the conclusion robust: it
    does not depend on which way the implementation goes.

    `rag_grounding` (30 ms/sentence) is excluded — `expected_for` skips it without context
    docs, and no dataset case carries any. Its absence is stated in the rendered section
    rather than silently improving the projection.
    """
    counts = sorted(sentence_counts(cases))
    sen_lane = [d for d in LANES[Stage.OUTPUT_SENTENCE] if d != "rag_grounding"]
    inp_lane = list(LANES[Stage.INPUT])
    live_sen = [d for d in sen_lane if d in LIVE]
    live_inp = [d for d in inp_lane if d in LIVE]

    def cost(names: Sequence[str], mode: str) -> float:
        budgets = [BUDGETS_MS[n] for n in names]
        if not budgets:
            return 0.0
        return sum(budgets) if mode == "sum" else max(budgets)

    rows: list[dict[str, Any]] = []
    for label, mode in (("sequential (as implemented)", "sum"), ("parallel (02 §4 intent)", "max")):
        inp, sen = cost(inp_lane, mode), cost(sen_lane, mode)
        rows.append({
            "label": label,
            #: Which reading this row is, as data rather than a substring of `label`: a test
            #: matching on prose would pass a renamed label that had changed meaning.
            "mode_is_sum": mode == "sum",
            "input_ms": inp,
            "sentence_ms": sen,
            "live_input_ms": cost(live_inp, mode),
            "live_sentence_ms": cost(live_sen, mode),
            #: The ADR-030 verdicts: each hold against its own P99, which is the comparison
            #: NFR-P-001 now makes. Derived from the same budgets as the sum above, so the
            #: respecification changes which number is judged, never the arithmetic.
            "input_within": inp < NFR_P_001["input_hold_ms"]["p99"],
            "sentence_within": sen < NFR_P_001["sentence_holds_ms"]["p99"],
            "points": [
                # `over_withdrawn_sum`, not `breach`. The per-request sum is exactly what
                # ADR-030 removed from NFR-P-001's scope, so comparing it to 100 ms no longer
                # yields a verdict — the number is retained and published, the comparison is
                # not. Renamed rather than reinterpreted so nothing reading this key keeps a
                # meaning it lost.
                {"pct": name, "sentences": n, "total_ms": inp + n * sen,
                 "over_withdrawn_sum": (inp + n * sen) >= 100.0}
                for name, n in (("P50", int(percentile(counts, 50))),
                                ("P95", int(percentile(counts, 95))),
                                ("P99", int(percentile(counts, 99))),
                                ("max", counts[-1]))
            ],
        })
    return {
        "counts": {"n": len(counts), "p50": percentile(counts, 50), "p95": percentile(counts, 95),
                   "p99": percentile(counts, 99), "max": counts[-1]},
        "pending": [d for d in inp_lane + sen_lane if d not in LIVE],
        "rows": rows,
    }


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True,
            cwd=Path(__file__).resolve().parents[1],
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unavailable"


def _row(label: str, stats: Stats | None) -> str:
    if stats is None:
        return f"| {label} | — | not measured | not measured | not measured | — | — |"
    return (f"| {label} | {stats.n} | {stats.p50:.2f} | {stats.p95:.2f} | {stats.p99:.2f} "
            f"| {stats.minimum:.2f} | {stats.maximum:.2f} |")


def _hold_row(label: str, targets: dict[str, float], stats: Stats | None) -> str:
    """One row of the NFR-P-001 table: the targets beside the measurement.

    A breaching figure is **bolded**, so the table itself shows the breach rather than relying
    on the reader to compare two columns. `not measured` fills the cells when the series is
    absent — never zeros, which would read as "measured, and instant".
    """
    p50_t, p99_t = targets["p50"], targets["p99"]
    if stats is None:
        return (f"| {label} | < {p50_t:.0f} ms | < {p99_t:.0f} ms | — "
                "| not measured | not measured | not measured | — | — |")

    def cell(value: float, target: float | None) -> str:
        return (f"**{value:.2f}**" if target is not None and value >= target
                else f"{value:.2f}")

    return (f"| {label} | < {p50_t:.0f} ms | < {p99_t:.0f} ms | {stats.n} "
            f"| {cell(stats.p50, p50_t)} | {cell(stats.p95, None)} "
            f"| {cell(stats.p99, p99_t)} | {stats.minimum:.2f} | {stats.maximum:.2f} |")


def render(
    batch: Batch,
    *,
    dataset_dir: Path,
    provenance_note: str,
    cadence_ms: float,
    violations: Sequence[Violation],
    live_note: str,
    command: str = "python -m eval.bench_latency",
    cases: Sequence[dict[str, Any]] | None = None,
) -> str:
    # Both halves of one guard. An unset store would make `render()` guess the policy set;
    # an EMPTY one is the same defect wearing a different shape — `PolicyStore()` is unloaded
    # until `.load()`, so `get()` would raise `UnknownUseCase` from inside a list
    # comprehension and blame the use case rather than the caller. Refused here by name.
    store = batch.store
    if store is None:
        raise SystemExit("Batch.store is unset; render() must not guess the policy set")
    if not store.versions():
        raise SystemExit(
            "Batch.store is empty (a PolicyStore is unloaded until .load()); render() cannot "
            "split the streaming and non-streaming tables without the policies the requests "
            "were evaluated against"
        )
    dstats = detector_stats(batch)
    stream_stats = Stats.of(batch.overheads(streaming=True))
    projection = project_tier2(cases if cases is not None else load_corpus(dataset_dir))
    head = _git("rev-parse", "HEAD")
    dirty = _git("status", "--porcelain")

    lines: list[str] = [
        "# Gateway latency benchmark (06 §4)",
        "",
        "NFR-P-001 (gateway hot-path overhead, **streaming pipelines**) and NFR-P-002 "
        "(per-detector fast-path budgets). Every overhead figure below is read back out of "
        "`audit_records.latency_json` — the gateway's own recording under the **normative** "
        "06 §4 definition — never recomputed by this harness.",
        "",
        "## Provenance",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Generated (UTC) | {datetime.now(timezone.utc).isoformat(timespec='seconds')} |",
        f"| Dataset digest | `{dataset_digest(dataset_dir)}` |",
        f"| Frozen at | `{FROZEN_COMMIT[:12]}` — "
        f"{'MATCHES' if not check_freeze(dataset_dir) else 'MISMATCH'} |",
        f"| Requests attempted | {batch.requests_attempted}"
        + ("" if batch.requests_attempted == DEFAULT_REQUESTS else
           f" — **06 §4 specifies {DEFAULT_REQUESTS}; this run is a smaller sample and not "
           f"the specified benchmark**")
        + " |",
        f"| Samples recorded | {len(batch.samples)} |",
        f"| Stub cadence | {cadence_ms} ms/token |",
        f"| Code commit | `{head[:12]}`{' + uncommitted changes' if dirty else ''} |",
        f"| Python | {platform.python_version()} |",
        f"| Platform | {platform.system()} {platform.release()} · {platform.machine()} |",
        f"| CPU | {platform.processor() or 'unreported'} |",
        f"| Percentile method | linear-interpolated (`telemetry.metrics.percentile`) |",
        f"| Command | `{command}` |",
        "",
        provenance_note,
        "",
        "## Method",
        "",
        f"1. {batch.requests_attempted} requests replayed from the frozen corpus, balanced "
        "across the three pipelines and cycling deterministically — two runs on one freeze "
        "issue the identical sequence, so a change in these numbers is drift rather than noise.",
        "2. Upstream is a **stub** emitting canned SSE word-by-word at the cadence above, so "
        "gateway overhead is isolated from provider variance (06 §4). Word-by-word matters: a "
        "single-chunk response would collapse every per-sentence hold into one and report the "
        "overhead of a pipeline nobody runs.",
        "3. `total_attributable_overhead_ms` is read from each request's audit record. **Streaming and "
        "non-streaming are tabulated separately because they are different quantities** — "
        "streaming sums measured hold intervals, non-streaming subtracts the upstream call "
        "from wall-clock (06 §4).",
        "4. **ADR-030 re-scoped NFR-P-001 onto the per-hold series**, so the requirement is "
        "gated on `input_hold_ms` and `sentence_holds_ms` — the two holds a user actually waits "
        "through — and **not** on the per-request sum, which is retained and published under its "
        "new name, untargeted. The per-sentence population is **holds, not requests**: a "
        "percentile over per-request means would let one slow hold hide behind a long response's "
        "fast ones.",
        "",
        "## NFR-P-001 — the targeted per-hold series (streaming)",
        "",
        "These two series are what NFR-P-001 targets after ADR-030, whose targets were *derived* "
        "from the 04 §2 budgets rather than fitted to a measurement. `sentence_holds_ms` is "
        "tabulated **over holds**, so `n` is the number of sentences held, not the number of "
        "requests. Non-streaming pipelines record one buffered hold each and are published below "
        "but never gated here — 01's NFR-P-001 row scopes to streaming.",
        "",
        "| Series | Target P50 | Target P99 | n | P50 | P95 | P99 | min | max |",
        "|---|---|---|---|---|---|---|---|---|",
        _hold_row("`input_hold_ms`", NFR_P_001["input_hold_ms"],
                  Stats.of(batch.input_holds(streaming=True))),
        _hold_row("`sentence_holds_ms` (per hold)", NFR_P_001["sentence_holds_ms"],
                  Stats.of(batch.sentence_holds(streaming=True))),
        "",
        "## `total_attributable_overhead_ms` — streaming pipelines (published, no target)",
        "",
        "Renamed by **ADR-030** from `gateway_overhead_ms`; **the 06 §4 formula is unchanged**, so "
        "these figures are comparable to every previously published run. What changed is its "
        "standing: it is no longer the quantity NFR-P-001 targets, and it keeps being published "
        "precisely so the respecification withdraws a target without withdrawing a number.",
        "",
        "| Pipeline | n | P50 | P95 | P99 | min | max |",
        "|---|---|---|---|---|---|---|",
    ]
    streaming_ucs = [uc for uc in USE_CASES if store.get(uc).streaming]
    for uc in streaming_ucs:
        lines.append(_row(f"{UC_LABEL[uc]} `{uc}`", Stats.of(batch.overheads(uc, streaming=True))))
    lines.append(_row("**all streaming**", Stats.of(batch.overheads(streaming=True))))

    lines += [
        "",
        "## `total_attributable_overhead_ms` — non-streaming pipelines",
        "",
        "Reported separately and **not** gated by NFR-P-001, whose scope is streaming "
        "pipelines. `total wall-clock − upstream duration` per 06 §4.",
        "",
        "| Pipeline | n | P50 | P95 | P99 | min | max |",
        "|---|---|---|---|---|---|---|",
    ]
    buffered_ucs = [uc for uc in USE_CASES if not store.get(uc).streaming]
    for uc in buffered_ucs:
        lines.append(_row(f"{UC_LABEL[uc]} `{uc}`", Stats.of(batch.overheads(uc, streaming=False))))
    lines.append(_row("**all non-streaming**", Stats.of(batch.overheads(streaming=False))))

    ref = Stats.of([s.reference_delta_ms for s in batch.by_stream_mode(True)])
    lines += [
        "",
        "### Reference row — client wall-clock − upstream (streaming)",
        "",
        "06 §4 requires this be reported **separately and never as the headline number**, so it "
        "sits here rather than above. It exceeds `total_attributable_overhead_ms` by relay and "
        "`TestClient` ASGI transport time — neither a per-sentence hold nor a token wait, and "
        "the harness's own cost rather than the gateway's. Treat it as an upper bound.",
        "",
        "| Series | n | P50 | P95 | P99 | min | max |",
        "|---|---|---|---|---|---|---|",
        _row("wall − upstream (upper bound)", ref),
        "",
        "## Per-detector latency vs NFR-P-002 budgets",
        "",
        "Budgets are also enforced at runtime: `run_with_budget` cancels past budget and raises "
        "`DetectorTimeout`. A P99 sitting at the budget therefore usually means timeouts fired, "
        "not that a call ran long — the two need different responses, so the fault count is "
        "shown beside the percentiles.",
        "",
        "| Detector | Budget | n | P50 | P95 | P99 | max | Faults | Within budget (P99) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    faults = detector_faults(batch)
    for detector, stat in sorted(dstats.items()):
        budget = BUDGETS_MS.get(detector)
        verdict = "—" if budget is None else ("yes" if stat.p99 < budget else "**NO**")
        modes = faults.get(detector, {})
        fault_cell = (
            "0" if not modes
            else f"{int(sum(modes.values()))} ("
                 + ", ".join(f"{m} ×{int(v)}" for m, v in sorted(modes.items())) + ")"
        )
        lines.append(
            f"| `{detector}` | {f'{budget:.0f} ms' if budget else '—'} | {stat.n} "
            f"| {stat.p50:.3f} | {stat.p95:.3f} | {stat.p99:.3f} | {stat.maximum:.3f} "
            f"| {fault_cell} | {verdict} |"
        )
    absent = sorted(set(BUDGETS_MS) - set(dstats))
    if absent:
        lines += [
            "",
            f"**Not exercised in this run:** {', '.join(f'`{d}`' for d in absent)}. These are "
            "unimplemented or policy-gated detectors, so their budgets are untested rather "
            "than met — the distinction M-10 draws between \"checked, clean\" and \"never "
            "checked\", applied to a benchmark.",
        ]

    lines += [
        "",
        "## NFR verdict",
        "",
    ]
    if violations:
        lines += [
            f"**{len(violations)} violation(s).** Per AGENTS.md §5.4 the response is a **D3 "
            "deviation** carrying the honest measured number — never a relaxed threshold.",
            "",
            "| Requirement | Subject | Metric | Target | Measured |",
            "|---|---|---|---|---|",
        ]
        for v in violations:
            lines.append(
                f"| {v.requirement} | {v.subject} | {v.metric} | {v.target:.1f} ms "
                f"| **{v.measured:.3f} ms** |"
            )
    elif nfr_p001_measurable(batch):
        lines.append(
            "**No violation.** Both requirements were evaluated against emitted series: "
            "NFR-P-001 on the two per-hold series above (ADR-030 scope), NFR-P-002 on the "
            "per-detector budgets. `--check` exits zero on this state and nonzero on any row "
            "above appearing. **Coverage is what bounds this, not the verdict:** the budgets "
            "the projection below composes belong to detectors that do not exist yet, so this "
            "is a pass at the current detector set, not a pass at the documented one."
        )
    else:
        lines.append(
            "**No violation of any requirement this run can evaluate.** `--check` exits zero on "
            "this state and nonzero on any row above appearing. That covers NFR-P-002 only — see "
            "the NFR-P-001 note below, which is a *third* state and not a pass."
        )
    if not nfr_p001_measurable(batch):
        lines += ["", NFR_P_001_NOT_MEASURED]

    if batch.errors:
        lines += [
            "",
            "## Requests excluded",
            "",
            f"{len(batch.errors)} of {batch.requests_attempted} produced no usable sample. "
            "Listed rather than dropped: a percentile over the survivors of an unexplained "
            "failure is not a measurement.",
            "",
            *[f"- `{e}`" for e in batch.errors[:20]],
        ]
        if len(batch.errors) > 20:
            lines.append(f"- …and {len(batch.errors) - 20} more")

    lines += [
        "",
        "## End-to-end sanity row (real provider)",
        "",
        live_note,
        "",
        "## Forward projection — what happens when the remaining hot-path detectors land",
        "",
        "**This section is a PROJECTION, not a measurement.** Every figure is arithmetic over "
        "the 04 §2 declared budgets, not an observation: `tier2_toxicity` and `tier2_injection` "
        "are unimplemented, so nothing here has been run. It is derived from `LANES` and "
        "`BUDGETS_MS` rather than written down, so a budget or lane change moves it.",
        "",
        "This section is also **the evidence that motivated ADR-030**, which re-scoped NFR-P-001 "
        "onto the per-hold series after this arithmetic showed the old per-request target could "
        "not survive the documented detector set. It is kept here, unshortened, so the ruling's "
        "basis stays visible in the artefact that produced it.",
        "",
        f"Pending detectors on the hot-path lanes: "
        f"{', '.join(f'`{d}`' for d in projection['pending']) or 'none'}. `rag_grounding` "
        "(30 ms/sentence) is **excluded** — `expected_for` skips it without context docs and no "
        "dataset case carries any; with them, add that per sentence.",
        "",
        "The multiplier matters more than the per-detector cost. "
        "`total_attributable_overhead_ms` is a **sum over per-sentence holds**, so a per-sentence "
        "budget is paid once per sentence — which is precisely why ADR-030 stopped targeting the "
        "sum and started targeting the hold. "
        "Segment counts measured over the frozen corpus with the real `Segmentation` "
        f"(n={projection['counts']['n']}): P50 **{projection['counts']['p50']:.0f}**, "
        f"P95 **{projection['counts']['p95']:.0f}**, P99 **{projection['counts']['p99']:.0f}**, "
        f"max **{projection['counts']['max']}**.",
        "",
    ]
    for row in projection["rows"]:
        lines += [
            f"**Lane cost, {row['label']}** — input {row['input_ms']:.0f} ms once, "
            f"{row['sentence_ms']:.0f} ms per sentence "
            f"(today: {row['live_input_ms']:.0f} ms / {row['live_sentence_ms']:.0f} ms).",
            "",
            f"NFR-P-001 as ADR-030 scopes it: input-lane hold "
            f"**{'within' if row['input_within'] else 'OVER'}** its "
            f"{NFR_P_001['input_hold_ms']['p99']:.0f} ms P99, per-sentence hold "
            f"**{'within' if row['sentence_within'] else 'OVER'}** its "
            f"{NFR_P_001['sentence_holds_ms']['p99']:.0f} ms P99.",
            "",
            "| Segments | Projected `total_attributable_overhead_ms` | vs the **withdrawn** "
            "100 ms per-request target |",
            "|---|---|---|",
        ]
        for pt in row["points"]:
            note = "would have breached" if pt["over_withdrawn_sum"] else "would have been under"
            lines.append(f"| {pt['pct']} — {pt['sentences']} | {pt['total_ms']:.0f} ms | {note} |")
        lines.append("")

    # Derived, never written down. The first version of this sentence asserted "three orders of
    # magnitude" and was wrong by more than one — 100 ms against a ~1.5 ms P99 is ~66x. A prose
    # constant would also rot on the next machine, so the factor tracks the same series the
    # streaming table above reports. Absent and unresolvable are named rather than collapsed into
    # a number (M-10 / ADR-027 Amendment 1: "measured", "not measured" and "too small to resolve"
    # are three states).
    # Derived, never written down. An earlier version of this sentence asserted "three orders of
    # magnitude" and was wrong by more than one, and a prose constant describes only the machine
    # that produced it. It no longer quotes a *factor*, because ADR-030 withdrew the target this
    # series was compared against and a ratio against a withdrawn target would be arithmetic
    # about nothing. Absent and unresolvable stay named rather than collapsed into a number
    # (M-10: "measured", "not measured" and "too small to resolve" are three states).
    if stream_stats is None:
        headroom = "no streaming series was measured in this run, so there is nothing to compare"
    elif stream_stats.p99 <= 0.0:
        headroom = (
            f"the measured sum rounds to 0.00 ms P99 over {stream_stats.n} samples — smaller than "
            "this run can resolve, let alone than any projected figure above"
        )
    else:
        headroom = (
            f"the measured sum is {stream_stats.p99:.2f} ms P99 over {stream_stats.n} samples, "
            f"against a smallest projected figure of "
            f"{min(pt['total_ms'] for r in projection['rows'] for pt in r['points']):.0f} ms"
        )

    lines += [
        "**Under ADR-030's scope the composition fits, under both readings; under the withdrawn "
        "per-request target it did not, under either.** That is the whole content of the "
        "respecification: the arithmetic is unchanged and every budget is unchanged — what "
        "changed is which quantity NFR-P-001 judges. The per-request sum still grows with the "
        "segment count exactly as tabulated above, and is still published, so the trade-off is "
        "legible rather than hidden.",
        "",
        "**The trade-off ADR-030 accepted, stated plainly:** a long response can hold "
        f"~{max(pt['total_ms'] for r in projection['rows'] for pt in r['points']):.0f} ms in "
        "total while *every individual sentence* passes its target. A per-hold guarantee is "
        "genuinely weaker than a per-request one. It is the guarantee that matches what "
        "sentence-level interception promises — each hold is the delay before *that* sentence "
        "appears — and the total is published untargeted beside it so a reader can see both.",
        "",
        "**The fit is now unconditional (M-18 / M-19 closed).** It was conditional when ADR-030 "
        "was accepted: `entity_enricher` was budgeted per *span*, so a heavily-enriched sentence "
        "composed to `60 + 10k` and crossed the 100 ms per-sentence P99 at **k = 4**, with no doc "
        "bounding `k`. 04 §2.2 now caps enrichment at **10 ms aggregate per sentence**, so `k` "
        "leaves the arithmetic entirely, and the policy+action step carries a **combined 5 ms "
        "budget** instead of sitting untracked inside a targeted quantity. Worst cases become "
        "30 / 40 / 45 / 75 ms and every row fits. Both caps were ruled where the budget lives "
        "(04 §2.2) rather than inside the target that needed them — inventing a bound to make "
        "one's own target fit is the move AGENTS.md §5.4 forbids.",
        "",
        "One adjacency ADR-030 records rather than rounds away: the **enriched typical** row "
        "lands at exactly **40.0 ms** against a strict `< 40` P50. It is not a breach, because "
        "the P50 judges the *median* hold and a median sentence is unenriched — enrichment "
        "requires a span-bearing `hallucination.*` signal, so a median enriched sentence would "
        "mean over half of all traffic is hallucination-flagged. It is written down because it is "
        "the first place a future budget change would break the derivation.",
        "",
        "Three things this does **not** say. It is not a measurement, so it is not a D3 — a D3 "
        f"needs an observed breach, and nothing here was observed: {headroom}. "
        "It is not a claim that the budgets are wrong: 04 §2 declares "
        "them and `run_with_budget` enforces them, so a detector at budget is a detector "
        "behaving as specified. And it is not a prediction that tier2 will actually cost its "
        "full budget — a fast classifier well inside 25 ms changes the arithmetic entirely.",
        "",
        "## Scope and limitations",
        "",
        "**The headline figure is cadence-independent by construction**, because 06 §4 excludes "
        "upstream token wait from `total_attributable_overhead_ms`. That is verified, not assumed: "
        "`test_overhead_is_independent_of_token_cadence` runs the same mix at two cadences and "
        "asserts the figure does not track the change.",
        "",
        "**`TestClient` transport is in the reference row, not the headline.** The in-process "
        "ASGI round trip is harness cost a real client would not pay, which is precisely why "
        "the headline reads the gateway's own recording instead of this harness's stopwatch.",
        "",
        "**Prototype hardware, single machine, no warm-up discard.** The first requests include "
        "one-off import and compile cost, which inflates the maximum rather than the "
        "percentiles. Stated instead of trimmed: discarding a warm-up window without saying so "
        "would improve the number by choosing which measurements count.",
        "",
        "Reproduce: `python -m eval.validate_dataset --freeze && python -m eval.bench_latency`",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset-dir", type=Path, default=DATASET_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--requests", type=int, default=DEFAULT_REQUESTS,
                        help=f"total requests to replay (06 §4 specifies {DEFAULT_REQUESTS})")
    parser.add_argument("--cadence-ms", type=float, default=DEFAULT_CADENCE_MS,
                        help="stub inter-token delay; lands in the token wait 06 §4 excludes")
    parser.add_argument("--check", action="store_true",
                        help="exit nonzero if NFR-P-001/002 is violated (the D3 tripwire)")
    parser.add_argument("--live", action="store_true",
                        help=f"also run {LIVE_REQUESTS} requests against the real provider "
                             "(06 §4 sanity row). Refused on a dev-class upstream unless "
                             "--allow-dev, since a dev-class latency figure is not publishable")
    parser.add_argument("--allow-dev", action="store_true")
    args = parser.parse_args(argv)

    violations_freeze = check_freeze(args.dataset_dir)
    if violations_freeze:
        print("FREEZE CHECK FAILED — refusing to measure:", file=sys.stderr)
        for v in violations_freeze:
            print(f"  {v}", file=sys.stderr)
        return 1

    try:
        cfg = require_measured_upstream(allow_dev=args.allow_dev, artifact="the latency report")
        provenance_note = (
            f"> **Upstream provenance:** active provider `{cfg.active.name}` is "
            f"`{cfg.active.upstream_class}`-class (ADR-018)."
        )
        dev_class = False
    except TaintedDataError:
        cfg = load_gateway_config()
        dev_class = True
        provenance_note = (
            f"> **Upstream provenance:** the active provider `{cfg.active.name}` is "
            f"**dev-class**, which `require_measured_upstream()` refuses for judge-facing "
            f"output (ADR-018). **The stub-upstream tables are unaffected:** they involve no "
            f"provider call at all — that is the point of a stub, and 06 §4 chose one so "
            f"gateway overhead is isolated from provider variance. The gate binds only the "
            f"end-to-end sanity row, which is reported as not-run below."
        )

    if args.live and dev_class and not args.allow_dev:
        live_note = (
            f"**Not run.** `--live` was requested but the active provider `{cfg.active.name}` "
            f"is dev-class, so its latency is not a publishable measurement (ADR-018). Re-run "
            f"with a measured-class `active_provider`, or with `--allow-dev` to produce an "
            f"explicitly tainted figure."
        )
    elif args.live:
        # Deliberately not implemented rather than faked: a real dispatch needs a credential
        # and network, and inventing a number here would be exactly the fabrication AGENTS.md
        # §7 forbids. The stub tables above are the measured deliverable of this run.
        live_note = (
            f"**Not run — STUB(live-dispatch, needs a credentialled provider on the bench "
            f"host).** 06 §4 asks for {LIVE_REQUESTS} requests against the real provider as an "
            f"end-to-end sanity row. It is not produced here, and no substitute figure is "
            f"printed: a fabricated end-to-end number is worse than a stated absence "
            f"(AGENTS.md §7)."
        )
    else:
        live_note = (
            f"**Not run** (`--live` not passed). 06 §4's {LIVE_REQUESTS}-request sanity row is "
            f"opt-in because the shipped active provider is dev-class and its numbers are not "
            f"publishable (ADR-018)."
        )

    # Reconstructed from the parsed args rather than hardcoded: a report that stamps the
    # default command while having run with `--requests 12` names an invocation that would
    # not reproduce its own numbers, which is the reproducibility claim of 06 §8 in reverse.
    invocation = ["python", "-m", "eval.bench_latency"]
    if args.dataset_dir != DATASET_DIR:
        invocation += ["--dataset-dir", str(args.dataset_dir)]
    if args.out != DEFAULT_OUT:
        invocation += ["--out", str(args.out)]
    if args.requests != DEFAULT_REQUESTS:
        invocation += ["--requests", str(args.requests)]
    if args.cadence_ms != DEFAULT_CADENCE_MS:
        invocation += ["--cadence-ms", str(args.cadence_ms)]
    if args.check:
        invocation.append("--check")
    if args.live:
        invocation.append("--live")
    if args.allow_dev:
        invocation.append("--allow-dev")

    cases = load_corpus(args.dataset_dir)
    mix = traffic_mix(cases, args.requests)
    batch = run_batch(mix, cadence_ms=args.cadence_ms)
    if not batch.samples:
        print("no samples recorded — refusing to write a report", file=sys.stderr)
        for e in batch.errors[:10]:
            print(f"  {e}", file=sys.stderr)
        return 1

    violations = [*check_nfr_p001(batch), *check_nfr_p002(detector_stats(batch))]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(
        batch, dataset_dir=args.dataset_dir, provenance_note=provenance_note,
        cadence_ms=args.cadence_ms, violations=violations, live_note=live_note,
        command=" ".join(invocation), cases=cases,
    ))

    stream_stats = Stats.of(batch.overheads(streaming=True))
    if stream_stats is not None:
        print(f"{args.out}: streaming overhead P50 {stream_stats.p50:.2f} ms · "
              f"P99 {stream_stats.p99:.2f} ms over {stream_stats.n} samples")
    else:
        print(f"{args.out}: no streaming samples recorded")
    for v in violations:
        print(f"  VIOLATION {v.line()}", file=sys.stderr)

    # Nonzero only under --check. Without it this is a measurement run: a breach is reported
    # honestly in the report and left for a human to rule on as a D3, which is what AGENTS.md
    # §5.4 requires. With it, this is the CI tripwire 06 §4 specifies.
    return 1 if (args.check and violations) else 0


if __name__ == "__main__":
    raise SystemExit(main())
