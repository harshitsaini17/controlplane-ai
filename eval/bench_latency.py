"""Latency benchmark -> reports/latency_report.md.

Implements 06 §4, incl. the NORMATIVE `gateway_overhead_ms` definition and `--check`
assertion mode (the NFR-P-001/002 D3 tripwire).

**Every overhead figure is read back out of the audit record, never recomputed here.**
`controlplane.gateway.pipeline.gateway_overhead_ms` is the single implementation of the 06 §4
formula, and 06 §4 says that definition is used by "05 §5, the audit record, and every report
— no ad-hoc variants". A benchmark that re-derived the number from its own stopwatch would be
measuring a second, unspecified quantity that happened to look similar, and the two could
drift without either being wrong on its own terms. So this module fires requests and reads
`latency_json.gateway_overhead_ms` back out of `audit_records`.

**Streaming and non-streaming are tabulated separately because they are different
quantities**, not merely different configurations (06 §4): streaming sums measured hold
intervals, non-streaming subtracts the upstream call from wall-clock. NFR-P-001 is scoped in
its own wording to "**streaming pipelines** (per the normative definition in 06 §4)", so
`--check` gates the P50 < 40 ms / P99 < 100 ms thresholds on the streaming table only. The
non-streaming table is reported in full and gated by NFR-P-002 alone. Applying a streaming
threshold to a subtraction-derived figure would be inventing a requirement.

**The headline number is cadence-independent by construction, and that is verified rather
than asserted.** 06 §4 excludes upstream token wait from `gateway_overhead_ms`, so changing
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
from controlplane.detectors.base import BUDGETS_MS
from controlplane.gateway.app import Gateway, create_app
from controlplane.gateway.config import (
    TaintedDataError,
    load_gateway_config,
    require_measured_upstream,
)
from controlplane.gateway.ingress import HEADER_REQUEST_ID, HEADER_USE_CASE
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
NFR_P_001: dict[str, float] = {"p50": 40.0, "p99": 100.0}

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

    @property
    def reference_delta_ms(self) -> float:
        """`wall − upstream`: the 06 §4 reference row, explicitly NOT the headline number.

        For a streaming pipeline this exceeds `overhead_ms` by the relay and transport time
        that is neither a per-sentence hold nor a token wait. `pipeline.gateway_overhead_ms`
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
            overhead = latency.get("gateway_overhead_ms")
            if overhead is None:
                # Recorded as an error rather than skipped silently: a missing overhead value
                # means the audit write path changed, and a percentile computed over the
                # survivors would hide that behind a plausible number.
                batch.errors.append(f"{case['case_id']}/{use_case}: no gateway_overhead_ms")
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
    """NFR-P-001 against the **streaming** table only (06 §4 scope).

    Checked per use case *and* over the pooled streaming sample. Per use case because a policy
    with heavier detector work could breach while the pool stays under; pooled because
    NFR-P-001 is stated as one gateway-wide figure, not as a per-pipeline one.
    """
    violations: list[Violation] = []
    subjects: list[tuple[str, list[float]]] = [
        (f"{UC_LABEL[uc]} {uc}", batch.overheads(uc, streaming=True)) for uc in USE_CASES
    ]
    subjects.append(("all streaming pipelines", batch.overheads(streaming=True)))

    for subject, values in subjects:
        stats = Stats.of(values)
        if stats is None:
            continue
        for metric, target in NFR_P_001.items():
            measured = getattr(stats, metric)
            if measured >= target:
                violations.append(
                    Violation("NFR-P-001", subject, metric.upper(), target, measured)
                )
    return violations


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


def render(
    batch: Batch,
    *,
    dataset_dir: Path,
    provenance_note: str,
    cadence_ms: float,
    violations: Sequence[Violation],
    live_note: str,
    command: str = "python -m eval.bench_latency",
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
        "3. `gateway_overhead_ms` is read from each request's audit record. **Streaming and "
        "non-streaming are tabulated separately because they are different quantities** — "
        "streaming sums measured hold intervals, non-streaming subtracts the upstream call "
        "from wall-clock (06 §4).",
        "4. NFR-P-001 gates the **streaming** table only, per its own wording. The "
        "non-streaming table is reported in full and gated by NFR-P-002 alone; applying a "
        "streaming threshold to a subtraction-derived figure would invent a requirement.",
        "",
        "## `gateway_overhead_ms` — streaming pipelines (NFR-P-001 scope)",
        "",
        f"Target: **P50 < {NFR_P_001['p50']:.0f} ms, P99 < {NFR_P_001['p99']:.0f} ms** "
        "on demo hardware.",
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
        "## `gateway_overhead_ms` — non-streaming pipelines",
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
        "sits here rather than above. It exceeds `gateway_overhead_ms` by relay and "
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
    else:
        lines.append(
            "**No violation.** Every gated figure is inside its documented target. `--check` "
            "exits zero on this state and nonzero on any row above appearing."
        )

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
        "## Scope and limitations",
        "",
        "**The headline figure is cadence-independent by construction**, because 06 §4 excludes "
        "upstream token wait from `gateway_overhead_ms`. That is verified, not assumed: "
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
        command=" ".join(invocation),
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
