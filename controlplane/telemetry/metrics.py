"""Metrics registry — the fixed vocabulary of 05 §5.

Implements the metric list in 05 §5 exactly and serves 05 §2 `GET /metrics`
(FR-OBS-001). Every name and every label key is declared in `REGISTRY` below; a
name or label that is not declared is **rejected**, not created on the fly. The
reason is the same one that makes the span list a contract: a metric invented at a
call site is a metric no dashboard panel reads and no report can cite, so it looks
like "nothing happened" rather than like a bug.

`cp_gateway_overhead_ms` observations MUST be computed with the normative 06 §4
formula. This module cannot verify that — it receives a float — so the obligation
sits with the caller, and `eval/bench_latency.py` is the one place that formula is
implemented (06 §4: "no ad-hoc variants").

**NFR-SEC-001 at the label boundary.** `cp_pii_intercepts_total{category,use_case}`
counts interceptions by *category* — `pii.ssn`, never the matched digits. A label
value is a low-cardinality dimension by construction, so `check_label_values`
refuses anything long or digit-dense: a metric label is exactly the kind of place a
raw value leaks into a dashboard that is then screenshotted into a report.

Percentiles are computed from **all** retained observations rather than a sketch or
a reservoir sample, because these figures are judge-facing (AGENTS.md §7): an
approximate P99 reported as a P99 is a fabricated number. Retention is bounded by
`MAX_OBSERVATIONS`; on overflow the histogram records the fact and
`snapshot()` marks the series `truncated: true` instead of silently reporting a
biased percentile.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

MetricType = Literal["counter", "histogram", "gauge"]

#: Observations retained per histogram series before the series is marked truncated.
#: 300 requests is the 06 §4 benchmark size, so this holds ~33 full benchmark runs
#: per series — far beyond demo scale, while still bounded.
MAX_OBSERVATIONS = 10_000


@dataclass(frozen=True)
class MetricSpec:
    """One declared metric: its type and the exact set of label keys 05 §5 gives it."""

    name: str
    type: MetricType
    labels: tuple[str, ...]
    doc: str


#: Transcribed from 05 §5. The label tuples are exact — `cp_requests_total` takes
#: `use_case` and `verdict`, not "whatever the call site felt like adding".
REGISTRY: dict[str, MetricSpec] = {
    spec.name: spec
    for spec in (
        MetricSpec("cp_requests_total", "counter", ("use_case", "verdict"),
                   "one per request, by verdict (FR-OBS-001 verdict mix)"),
        MetricSpec("cp_gateway_overhead_ms", "histogram", ("use_case",),
                   "hot-path overhead; 06 §4 formula is normative (NFR-P-001)"),
        MetricSpec("cp_detector_latency_ms", "histogram", ("detector",),
                   "per-detector latency vs the NFR-P-002 budgets"),
        MetricSpec("cp_detector_failures_total", "counter", ("detector", "fail_mode"),
                   "detector faults by resolution mode (04 §5, ADR-027)"),
        MetricSpec("cp_pii_intercepts_total", "counter", ("category", "use_case"),
                   "PII interceptions by CATEGORY — never the value (NFR-SEC-001)"),
        MetricSpec("cp_est_cost_usd_total", "counter", ("use_case", "model"),
                   "estimated spend by concrete model id (ADR-022)"),
        MetricSpec("cp_cascade_escalations_total", "counter", ("use_case",),
                   "small-tier probe rejected, re-dispatched frontier (ADR-013)"),
        MetricSpec("cp_review_items_total", "counter", ("use_case", "status"),
                   "review queue volume by status (FR-POL-005)"),
        MetricSpec("cp_deep_audit_entropy", "gauge", ("use_case",),
                   "latest semantic-entropy value from the slow lane"),
        MetricSpec("cp_consistency_lagged_total", "counter", ("use_case",),
                   "2nd sample lagged, released without the signal (ADR-014)"),
        MetricSpec("cp_probe_rejections_total", "counter", ("use_case",),
                   "cascade probe below tau_route (ADR-013)"),
        MetricSpec("cp_fallback_engaged_total", "counter",
                   ("from_provider", "to_provider", "reason"),
                   "provider fallback — never silent (FR-GW-006)"),
        MetricSpec("cp_pricing_missing_total", "counter", ("provider", "model"),
                   "model absent from pricing.models; est_cost is null (ADR-022)"),
        # `reason` carries the cause the way `cp_detector_failures_total{detector,fail_mode}`
        # does: "enrichment was skipped" is one countable fact, and a skip whose cause is
        # invisible cannot be told from a sentence that simply had no spans to enrich.
        MetricSpec("cp_enrichment_skipped_total", "counter", ("use_case", "reason"),
                   "enrichment stopped early — 10 ms/sentence aggregate cap or a "
                   "failure (04 §2.2); never blocks, not a fail_mode class"),
        # ADR-033 state (c). No `use_case` label, deliberately: unloadability is a
        # property of the PROCESS, identical for every request this boot, so a per-use-case
        # breakdown would multiply one boot-time fact across the dashboard as if it varied.
        MetricSpec("cp_detector_timeout_abandoned_total", "counter", ("detector",),
                   "executor task abandoned after a budget timeout (ADR-034 Part A): "
                   "Python cannot preempt a thread, so the worker finishes while the "
                   "request proceeds under fail_mode"),
        MetricSpec("cp_detector_unavailable_total", "counter", ("detector",),
                   "registered but unloadable at boot — dependency absent (ADR-033); "
                   "counted per affected request, never a fault record"),
    )
}

#: A label value must be a short, low-cardinality dimension. These bounds are what
#: make "a raw value ended up in a label" a loud failure rather than a silent leak.
MAX_LABEL_VALUE_LEN = 64
_DIGIT_RUN = re.compile(r"\d{5,}")


class MetricError(ValueError):
    """Raised on an undeclared metric, an undeclared label, or an unsafe label value."""


def check_label_values(name: str, labels: dict[str, str]) -> None:
    """Refuse label values that could carry content (NFR-SEC-001).

    Two rules, both about shape rather than meaning: a value longer than
    `MAX_LABEL_VALUE_LEN` is not a dimension, and a run of 5+ digits is what an SSN,
    a card number or a phone number looks like. Neither test can prove a value is
    safe — that is what the category-not-value discipline at the call site is for —
    but both catch the mistake this project is most exposed to.
    """
    for key, value in labels.items():
        if len(value) > MAX_LABEL_VALUE_LEN:
            raise MetricError(
                f"{name}: label {key!r} value is {len(value)} chars (max "
                f"{MAX_LABEL_VALUE_LEN}); a metric label is a dimension, not content "
                "(NFR-SEC-001)"
            )
        if _DIGIT_RUN.search(value):
            raise MetricError(
                f"{name}: label {key!r} contains a 5+ digit run, which is what raw "
                "PII looks like; label by CATEGORY, never by value (NFR-SEC-001)"
            )


def _key(labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
    """Canonical, order-independent series key: `{a:1,b:2}` and `{b:2,a:1}` are one series."""
    return tuple(sorted(labels.items()))


@dataclass
class _Series:
    """One label combination of one metric."""

    value: float = 0.0                      # counter total / gauge latest
    observations: list[float] = field(default_factory=list)   # histogram only
    count: int = 0
    truncated: bool = False                 # observations were dropped; see MAX_OBSERVATIONS


def percentile(values: list[float], p: float) -> float:
    """Exact linear-interpolated percentile over `values` (`p` in [0,100]).

    Linear interpolation between order statistics — the same definition
    `statistics.quantiles(method="inclusive")` uses — so a P99 over 300 samples is a
    real interpolated P99 rather than "the 297th value". Chosen over a t-digest or a
    bucketed histogram because these numbers are judge-facing and the sample sizes
    are small enough that exactness is free (AGENTS.md §7).
    """
    if not values:
        raise ValueError("percentile of an empty series is undefined, not 0.0")
    if not 0.0 <= p <= 100.0:
        raise ValueError(f"percentile p must be in [0,100], got {p}")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (p / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


class MetricsRegistry:
    """In-process metric aggregates, optionally mirrored to `metrics_events` (05 §3).

    Thread-safe because uvicorn may serve concurrently and the deep lane writes from
    its own task; the lock is uncontended in practice and cheap enough that a
    lock-free design would be premature.

    The DB mirror is the flat event stream 05 §3 specifies ("dashboard aggregates").
    It is optional so `eval/` and unit tests can measure without a database, and it
    is append-only: this module never UPDATEs a metrics row.
    """

    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        self._series: dict[str, dict[tuple[tuple[str, str], ...], _Series]] = {}
        self._lock = threading.Lock()
        self._conn = conn

    # -- recording ---------------------------------------------------------

    def _validate(self, name: str, labels: dict[str, str], expect: MetricType) -> MetricSpec:
        spec = REGISTRY.get(name)
        if spec is None:
            raise MetricError(
                f"{name!r} is not in the 05 §5 metric vocabulary; add it to 05 §5 "
                "first (AGENTS.md §4), then to REGISTRY"
            )
        if spec.type != expect:
            raise MetricError(
                f"{name} is a {spec.type}, not a {expect}; use the matching method"
            )
        if set(labels) != set(spec.labels):
            raise MetricError(
                f"{name} takes labels {sorted(spec.labels)}, got {sorted(labels)}; "
                "05 §5 fixes the label set"
            )
        check_label_values(name, labels)
        return spec

    def _record_event(self, name: str, value: float, labels: dict[str, str]) -> None:
        if self._conn is None:
            return
        # Append-only (05 §3). One row per observation: the dashboard aggregates,
        # so pre-aggregating here would throw away the distribution.
        self._conn.execute(
            "INSERT INTO metrics_events (ts, name, value, labels_json) VALUES (?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), name, float(value),
             json.dumps(labels, sort_keys=True)),
        )

    def increment(self, name: str, /, value: float = 1.0, **labels: str) -> None:
        """Add to a counter (05 §5). `value` is 1.0 except for summed quantities."""
        self._validate(name, labels, "counter")
        if value < 0:
            raise MetricError(f"{name}: a counter cannot decrease (got {value})")
        with self._lock:
            series = self._series.setdefault(name, {}).setdefault(_key(labels), _Series())
            series.value += float(value)
            series.count += 1
            self._record_event(name, value, labels)

    def observe(self, name: str, value: float, /, **labels: str) -> None:
        """Record one histogram observation (e.g. a latency in ms)."""
        self._validate(name, labels, "histogram")
        if not math.isfinite(value):
            raise MetricError(f"{name}: observation must be finite, got {value!r}")
        with self._lock:
            series = self._series.setdefault(name, {}).setdefault(_key(labels), _Series())
            series.count += 1
            if len(series.observations) < MAX_OBSERVATIONS:
                series.observations.append(float(value))
            else:
                # Never silently bias a percentile: the series is marked, and
                # `snapshot()` reports `truncated` alongside the figures.
                series.truncated = True
            self._record_event(name, value, labels)

    def set_gauge(self, name: str, value: float, /, **labels: str) -> None:
        """Set a gauge to its latest value (05 §5: `cp_deep_audit_entropy`)."""
        self._validate(name, labels, "gauge")
        with self._lock:
            series = self._series.setdefault(name, {}).setdefault(_key(labels), _Series())
            series.value = float(value)
            series.count += 1
            self._record_event(name, value, labels)

    # -- reading -----------------------------------------------------------

    def snapshot(self) -> dict[str, object]:
        """The 05 §2 `GET /metrics` payload: every recorded series, JSON-safe.

        Counters and gauges report `value`; histograms report count/min/max and
        P50/P95/P99 (the percentiles 06 §4 asks for). A histogram whose retention
        overflowed carries `truncated: true` so a reader is never handed a biased
        percentile that looks exact.

        Only *recorded* series appear. An absent series means nothing was observed,
        which is different from zero — a detector that never ran has no latency, and
        rendering that as 0 ms would be a fabricated measurement.
        """
        out: dict[str, object] = {}
        with self._lock:
            for name, series_map in sorted(self._series.items()):
                spec = REGISTRY[name]
                rows: list[dict[str, object]] = []
                for key, series in sorted(series_map.items()):
                    row: dict[str, object] = {"labels": dict(key)}
                    if spec.type == "histogram":
                        obs = series.observations
                        row.update(
                            count=series.count,
                            min=min(obs) if obs else None,
                            max=max(obs) if obs else None,
                            p50=percentile(obs, 50) if obs else None,
                            p95=percentile(obs, 95) if obs else None,
                            p99=percentile(obs, 99) if obs else None,
                        )
                        if series.truncated:
                            row["truncated"] = True
                    else:
                        row.update(value=series.value)
                    rows.append(row)
                out[name] = {"type": spec.type, "doc": spec.doc, "series": rows}
        return out

    def value_of(self, name: str, **labels: str) -> float:
        """One counter/gauge total, for tests and the demo's reveal lines.

        Raises `KeyError` for a series that was never recorded rather than returning
        0.0: "never happened" and "happened zero times" are different claims, and the
        demo asserts on these.
        """
        spec = REGISTRY.get(name)
        if spec is None:
            raise MetricError(f"{name!r} is not in the 05 §5 metric vocabulary")
        with self._lock:
            series = self._series.get(name, {}).get(_key(labels))
        if series is None:
            raise KeyError(f"no recorded series {name}{labels or ''}")
        if spec.type == "histogram":
            return float(series.count)
        return series.value

    def reset(self) -> None:
        """Drop all in-process aggregates (test isolation only; never in serving)."""
        with self._lock:
            self._series.clear()


#: Process-wide registry used by the gateway. Tests construct their own instance so
#: they never depend on, or pollute, this one.
REGISTRY_DEFAULT = MetricsRegistry()
