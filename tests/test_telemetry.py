"""Telemetry vocabularies (05 §5) — parsed from the doc, not restated from the code.

The span and metric lists are **fixed vocabularies** in 05 §5, and both become
persisted contracts: span names are `audit_records.latency_json` keys, metric names
are what the dashboard and every report read. So these tests extract the vocabulary
from `docs/05-api-and-data-contracts.md` and compare the modules against it.

That direction matters. A test that asserted `ALL == (INGRESS, ...)` would restate the
implementation and pass forever, including when the doc says something else — the
tautology 06 §3.1 rule 3 forbids elsewhere in this repo. Parsing the doc makes these
differential tests: a name added to 05 §5 and not to the code fails here, and so does
a name invented in the code.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from controlplane.telemetry import spans
from controlplane.telemetry.metrics import (
    MAX_LABEL_VALUE_LEN,
    REGISTRY,
    MetricError,
    MetricsRegistry,
    percentile,
)

DOC_05 = Path(__file__).resolve().parents[1] / "docs" / "05-api-and-data-contracts.md"


def _doc_section_5() -> str:
    """The text of 05 §5 (`## 5. Telemetry names`), up to the next `## ` heading."""
    text = DOC_05.read_text()
    start = text.index("## 5. Telemetry names")
    end = text.index("\n## ", start + 1)
    return text[start:end]


def _doc_spans() -> set[str]:
    """Every `cp.*` span name 05 §5 lists."""
    return set(re.findall(r"\bcp\.[a-z0-9_.]+", _doc_section_5()))


def _doc_metrics() -> dict[str, set[str]]:
    """`{metric_name: {label keys}}` from the 05 §5 `name{labels}` forms."""
    out: dict[str, set[str]] = {}
    for name, labels in re.findall(r"\b(cp_[a-z0-9_]+)\{([^}]*)\}", _doc_section_5()):
        out[name] = {l.strip() for l in labels.split(",") if l.strip()}
    return out


# --------------------------------------------------------------------------
# Spans
# --------------------------------------------------------------------------


def test_span_vocabulary_matches_the_doc_exactly() -> None:
    """05 §5: the span list is fixed. Neither side may carry a name the other lacks."""
    assert set(spans.ALL) == _doc_spans()


def test_span_list_has_no_duplicates_and_is_doc_ordered() -> None:
    """Duplicates would silently collapse two intervals into one `latency_json` key."""
    assert len(spans.ALL) == len(set(spans.ALL))
    section = _doc_section_5()
    positions = [section.index(name) for name in spans.ALL]
    assert positions == sorted(positions), "ALL should follow the order 05 §5 lists"


def test_latency_keys_admit_the_two_derived_figures_only() -> None:
    """05 §3 lists `gateway_overhead_ms` + `upstream_ms` beside the per-detector spans.

    They are legal `latency_json` keys but not spans: `gateway_overhead_ms` is derived
    by the 06 §4 formula and `upstream_ms` is the provider wait, recorded so it can be
    subtracted. Anything else is a typo.
    """
    assert spans.LATENCY_EXTRA_KEYS == {"gateway_overhead_ms", "upstream_ms"}
    assert spans.LATENCY_KEYS == set(spans.ALL) | spans.LATENCY_EXTRA_KEYS


def test_unknown_latency_key_is_refused_with_an_actionable_message() -> None:
    spans.check_latency_keys({spans.INGRESS: 1.0, "gateway_overhead_ms": 2.0})
    with pytest.raises(ValueError, match="05 §5 span vocabulary"):
        spans.check_latency_keys({"cp.ingres": 1.0})  # transposed letter
    with pytest.raises(TypeError):
        spans.check_latency_keys([spans.INGRESS])


def test_missing_span_is_not_an_error() -> None:
    """A detector that did not run has no interval; absence is normal, invention is not."""
    spans.check_latency_keys({})


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


def test_metric_vocabulary_matches_the_doc_exactly() -> None:
    """05 §5 fixes both the names and each metric's label set."""
    doc = _doc_metrics()
    assert set(REGISTRY) == set(doc)
    for name, labels in doc.items():
        assert set(REGISTRY[name].labels) == labels, name


def test_undeclared_metric_is_refused_rather_than_created() -> None:
    """A metric invented at a call site is one no panel reads and no report can cite."""
    r = MetricsRegistry()
    with pytest.raises(MetricError, match="05 §5 metric vocabulary"):
        r.increment("cp_requests_totals", use_case="support_bot", verdict="pass")


def test_wrong_label_set_is_refused() -> None:
    r = MetricsRegistry()
    with pytest.raises(MetricError, match="fixes the label set"):
        r.increment("cp_requests_total", use_case="support_bot")          # missing verdict
    with pytest.raises(MetricError, match="fixes the label set"):
        r.increment("cp_requests_total", use_case="u", verdict="pass", extra="x")


def test_metric_type_is_enforced() -> None:
    """A counter observed as a histogram would report a percentile over totals."""
    r = MetricsRegistry()
    with pytest.raises(MetricError, match="is a counter, not a histogram"):
        r.observe("cp_requests_total", 1.0, use_case="u", verdict="pass")
    with pytest.raises(MetricError, match="is a histogram, not a counter"):
        r.increment("cp_gateway_overhead_ms", use_case="u")


def test_nfr_sec_001_label_values_reject_raw_value_shapes() -> None:
    """`cp_pii_intercepts_total{category,...}` counts CATEGORIES, never values.

    A metric label is exactly where a raw value reaches a dashboard that is then
    screenshotted into a report, so the guard is shape-based and refuses digit runs.
    """
    r = MetricsRegistry()
    r.increment("cp_pii_intercepts_total", category="pii.ssn", use_case="support_bot")
    with pytest.raises(MetricError, match="raw PII"):
        r.increment("cp_pii_intercepts_total", category="001010001", use_case="support_bot")
    with pytest.raises(MetricError, match="dimension, not content"):
        r.increment("cp_pii_intercepts_total", category="x" * (MAX_LABEL_VALUE_LEN + 1),
                    use_case="support_bot")


def test_counters_cannot_decrease() -> None:
    r = MetricsRegistry()
    with pytest.raises(MetricError, match="cannot decrease"):
        r.increment("cp_requests_total", -1.0, use_case="u", verdict="pass")


def test_percentile_is_exact_and_interpolated() -> None:
    """06 §4 asks for P50/P95/P99; an approximation reported as a percentile is fabricated.

    Checked against hand-computable cases rather than against the implementation:
    linear interpolation between order statistics on 1..100 puts P99 at 99.01.
    """
    values = [float(i) for i in range(1, 101)]
    assert percentile(values, 50) == pytest.approx(50.5)
    assert percentile(values, 99) == pytest.approx(99.01)
    assert percentile(values, 0) == 1.0
    assert percentile(values, 100) == 100.0
    assert percentile([7.0], 99) == 7.0
    with pytest.raises(ValueError, match="undefined, not 0.0"):
        percentile([], 50)


def test_series_key_is_order_independent() -> None:
    """`{a,b}` and `{b,a}` are one series, or every panel double-counts."""
    r = MetricsRegistry()
    r.increment("cp_requests_total", use_case="support_bot", verdict="edit")
    r.increment("cp_requests_total", verdict="edit", use_case="support_bot")
    assert r.value_of("cp_requests_total", use_case="support_bot", verdict="edit") == 2.0


def test_unrecorded_series_raises_rather_than_reporting_zero() -> None:
    """"never happened" and "happened zero times" are different claims (AGENTS.md §7)."""
    r = MetricsRegistry()
    with pytest.raises(KeyError):
        r.value_of("cp_requests_total", use_case="hr_copilot", verdict="block")
    assert r.snapshot() == {}


def test_snapshot_reports_histogram_percentiles_and_marks_truncation() -> None:
    r = MetricsRegistry()
    for value in (10.0, 20.0, 30.0):
        r.observe("cp_gateway_overhead_ms", value, use_case="support_bot")
    series = r.snapshot()["cp_gateway_overhead_ms"]["series"][0]
    assert series["count"] == 3
    assert series["p50"] == pytest.approx(20.0)
    assert series["min"] == 10.0 and series["max"] == 30.0
    assert "truncated" not in series


def test_truncation_is_disclosed_not_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """A biased percentile that looks exact is worse than one labelled biased."""
    monkeypatch.setattr("controlplane.telemetry.metrics.MAX_OBSERVATIONS", 2)
    r = MetricsRegistry()
    for value in (1.0, 2.0, 3.0, 4.0):
        r.observe("cp_detector_latency_ms", value, detector="tier1_pii")
    series = r.snapshot()["cp_detector_latency_ms"]["series"][0]
    assert series["truncated"] is True
    assert series["count"] == 4, "the true count is still reported"


def test_gauge_holds_latest_not_sum() -> None:
    r = MetricsRegistry()
    r.set_gauge("cp_deep_audit_entropy", 0.4, use_case="finance_advisor")
    r.set_gauge("cp_deep_audit_entropy", 0.9, use_case="finance_advisor")
    assert r.value_of("cp_deep_audit_entropy", use_case="finance_advisor") == 0.9


def test_adr027_failure_metric_carries_the_fail_mode_dimension() -> None:
    """04 §5/ADR-027: faults are counted by detector AND resolution mode."""
    assert set(REGISTRY["cp_detector_failures_total"].labels) == {"detector", "fail_mode"}
    r = MetricsRegistry()
    r.increment("cp_detector_failures_total", detector="tier2_toxicity", fail_mode="fail_open")
    assert r.value_of(
        "cp_detector_failures_total", detector="tier2_toxicity", fail_mode="fail_open"
    ) == 1.0
