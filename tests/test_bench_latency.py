"""06 §4 latency benchmark — harness correctness, not a performance assertion.

**Nothing here asserts that the gateway is fast.** A test that pinned a latency number would
either be a duplicate of the `--check` tripwire or a threshold that passes on the author's
machine and fails on the bench host. What is tested is that the harness *reports honestly*:
that the figure comes from the audit record, that the streaming/non-streaming split follows
policy rather than guesswork, that an unmeasured series renders as "not measured" and never as
zero, and that the NFR gates fire on the requirement each one actually scopes.

One test is a **property** rather than a mechanic:
`test_overhead_is_independent_of_token_cadence`. 06 §4 excludes upstream token wait from
`total_attributable_overhead_ms`, so the headline figure must not move when the stub's cadence does. The
report cites this test by name as the evidence for that claim, so it must exist and must mean
what the report says.

Where a test needs a slow sample to exercise a gate, it **hand-builds a `Sample`** instead of
trying to make the real gateway slow. That is a double for the *input* to gate arithmetic, in
a unit test of gate arithmetic — not a substitute for a measurement in judge-facing output,
which AGENTS.md §7 forbids and which no test in this file produces.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from controlplane.detectors.base import BUDGETS_MS, Stage
from controlplane.gateway.pipeline import LANES, LIVE
from controlplane.policy.store import PolicyStore
from controlplane.telemetry.metrics import MetricsRegistry
from controlplane.telemetry.spans import LATENCY_KEYS
from eval import bench_latency as bl
from eval.validate_dataset import USE_CASES

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def store():
    s = PolicyStore()
    s.load()
    return s


@pytest.fixture(scope="module")
def corpus():
    return bl.load_corpus()


@pytest.fixture(scope="module")
def batch(corpus):
    """One real replay, shared: nine requests through the actual gateway.

    Module-scoped because every request writes an audit row and runs three detectors; a
    per-test batch would multiply that for no added coverage.
    """
    return bl.run_batch(bl.traffic_mix(corpus, 9))


def _sample(**kw) -> bl.Sample:
    base = dict(
        use_case="support_bot", case_id="X-000", streaming=True,
        overhead_ms=1.0, upstream_ms=10.0, wall_ms=12.0, http_status=200, verdict="pass",
    )
    base.update(kw)
    return bl.Sample(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ★ The property the report cites by name
# ---------------------------------------------------------------------------


def test_overhead_is_independent_of_token_cadence(corpus):
    """06 §4 excludes upstream token wait, so cadence must not move the headline figure.

    Asserted as a **ratio**, not an absolute bound: `Δoverhead` must be a small fraction of
    the `Δupstream` the cadence change produced. An absolute millisecond ceiling would encode
    this machine's speed and fail on a slower bench host for a reason unrelated to the
    property being tested.

    The first assertion is the one that keeps the test honest — it checks the cadence change
    actually lengthened upstream time. Without it, a stub that silently ignored `cadence_ms`
    would make the second assertion pass trivially, and the test would "prove" independence by
    never varying the input.
    """
    mix = bl.traffic_mix(corpus, 6)
    fast = bl.run_batch(mix, cadence_ms=0.5)
    slow = bl.run_batch(mix, cadence_ms=8.0)

    up_fast = bl.Stats.of([s.upstream_ms for s in fast.by_stream_mode(True)])
    up_slow = bl.Stats.of([s.upstream_ms for s in slow.by_stream_mode(True)])
    ov_fast = bl.Stats.of([s.overhead_ms for s in fast.by_stream_mode(True)])
    ov_slow = bl.Stats.of([s.overhead_ms for s in slow.by_stream_mode(True)])
    assert up_fast and up_slow and ov_fast and ov_slow

    delta_upstream = up_slow.p50 - up_fast.p50
    assert delta_upstream > 5.0, (
        f"cadence change did not lengthen upstream time ({up_fast.p50:.3f} -> "
        f"{up_slow.p50:.3f} ms); the stub is ignoring cadence_ms and this test would pass "
        "without varying anything"
    )
    delta_overhead = abs(ov_slow.p50 - ov_fast.p50)
    assert delta_overhead < 0.25 * delta_upstream, (
        f"total_attributable_overhead_ms tracked the token cadence ({ov_fast.p50:.3f} -> "
        f"{ov_slow.p50:.3f} ms against {delta_upstream:.1f} ms of added upstream wait); "
        "06 §4 excludes token wait from that figure"
    )


def test_the_report_only_cites_tests_that_exist():
    """Every test named in the generated prose must be a real test in this file.

    The fault-injection report earned the same guard. A report that cites a test by name is
    making a verifiable claim; if the name rots the claim becomes unfalsifiable, which is
    worse than having made no claim.
    """
    source = (ROOT / "eval" / "bench_latency.py").read_text()
    mine = (ROOT / "tests" / "test_bench_latency.py").read_text()
    for name in ("test_overhead_is_independent_of_token_cadence",):
        assert name in source
        assert f"def {name}(" in mine


# ---------------------------------------------------------------------------
# The figure's provenance: read back, never recomputed
# ---------------------------------------------------------------------------


def test_overhead_comes_from_the_audit_record_not_a_local_stopwatch(batch):
    """`overhead_ms` must differ from this harness's own `wall_ms`.

    If the two ever coincided it would mean the module had started deriving the figure itself,
    which 06 §4 forbids ("no ad-hoc variants"). They differ by relay and ASGI transport cost,
    so `wall` strictly exceeds `overhead` on every sample.
    """
    assert batch.samples
    for s in batch.samples:
        assert s.wall_ms > s.overhead_ms


def test_the_harness_reads_only_keys_in_the_05_5_vocabulary():
    """Every `latency_json` key this module names must be in the closed 05 §5 set.

    A structural guard against the defect this file's author actually shipped once: a
    plausible-looking key that `check_latency_keys` can never permit reads `0.0` forever and
    the report looks fine.
    """
    source = (ROOT / "eval" / "bench_latency.py").read_text()
    for key in ("total_attributable_overhead_ms", "upstream_ms"):
        assert f'"{key}"' in source
        assert key in LATENCY_KEYS
    # `wall_ms` is the harness's own stopwatch and must NOT be presented as a latency key.
    assert "wall_ms" not in LATENCY_KEYS


def test_a_missing_overhead_is_an_error_not_a_zero_sample():
    """A row without `total_attributable_overhead_ms` is recorded as an error, never sampled as 0.0.

    Structural, because provoking it needs a broken write path. A zero would be indexed into
    the percentiles as the fastest request in the run.
    """
    source = (ROOT / "eval" / "bench_latency.py").read_text()
    assert "no total_attributable_overhead_ms" in source
    assert 'overhead = latency.get("total_attributable_overhead_ms")' in source
    assert "if overhead is None:" in source


# ---------------------------------------------------------------------------
# The streaming / non-streaming split
# ---------------------------------------------------------------------------


def test_the_split_follows_policy_not_a_hardcoded_use_case_list(batch, store):
    """A sample's `streaming` flag must equal its policy's, for every sample.

    AGENTS.md §9.1: which pipeline streams is config, so a benchmark that hardcoded the set
    would tabulate the wrong table the moment a policy flipped.
    """
    assert batch.samples
    for s in batch.samples:
        assert s.streaming is bool(store.get(s.use_case).streaming)


def test_both_tables_are_populated_by_the_default_mix(batch):
    """The shipped policies must produce both a streaming and a non-streaming sample.

    Not a property of the harness but of the config it runs against — and worth pinning,
    because if every use case streamed, the non-streaming half of 06 §4's requirement would be
    silently untested while the report still printed its table.
    """
    assert batch.by_stream_mode(True), "no streaming samples — NFR-P-001 has nothing to gate"
    assert batch.by_stream_mode(False), "no buffered samples — 06 §4's second table is empty"


def test_the_per_request_sum_can_never_breach_nfr_p001():
    """The per-request sum is out of NFR-P-001's scope, so no sum can breach it.

    Before ADR-030 this asserted the opposite: a 5-second streaming sum *had* to breach. That
    assertion encoded the target ADR-030 withdrew, so it is re-authored rather than deleted —
    the property worth pinning is that the harness stops asserting a requirement the docs no
    longer contain. An absurd sum is used deliberately: if any threshold were still wired to
    this series, 5 seconds would trip it. The sum is still *published*; it is simply not gated.
    """
    absurd = bl.Batch(
        samples=[_sample(use_case="support_bot", streaming=True, overhead_ms=5_000.0)],
        store=PolicyStore(),
    )
    assert bl.check_nfr_p001(absurd) == []


def test_nfr_p001_now_gates_the_per_hold_series_and_names_the_breach():
    """M-20 landed, so the gate is real: a slow hold must produce a D3-shaped violation.

    This is the assertion the interim `return []` could not make. Both series are checked at
    both percentiles, and the `Violation` carries requirement/subject/metric/target/measured
    separately so `--check` and the report render the same fact.
    """
    slow = bl.Batch(
        samples=[_sample(streaming=True, input_hold_ms=60.0, hold_series=(150.0,))],
        store=PolicyStore(),
    )
    violations = bl.check_nfr_p001(slow)
    subjects = {(v.subject, v.metric) for v in violations}
    assert subjects == {
        ("input_hold_ms", "P50"), ("input_hold_ms", "P99"),
        ("sentence_holds_ms", "P50"), ("sentence_holds_ms", "P99"),
    }
    assert all(v.requirement == "NFR-P-001" for v in violations)
    assert {v.target for v in violations} == {40.0, 50.0, 100.0}

    fast = bl.Batch(
        samples=[_sample(streaming=True, input_hold_ms=0.4, hold_series=(0.3, 0.2))],
        store=PolicyStore(),
    )
    assert bl.check_nfr_p001(fast) == []


def test_the_gated_population_is_holds_not_requests():
    """One slow hold in a long response must breach, not be averaged away.

    This is the substance of ADR-030's re-scope: the target attaches to the hold a user waits
    through. Ten holds whose *mean* is comfortable but whose tail is 500 ms is a pass under
    per-request smoothing and a breach under the per-hold reading, so it separates the two.
    """
    lopsided = bl.Batch(
        samples=[_sample(streaming=True, input_hold_ms=1.0,
                         hold_series=(1.0,) * 9 + (500.0,))],
        store=PolicyStore(),
    )
    assert len(bl.Batch(samples=lopsided.samples).sentence_holds(streaming=True)) == 10
    breaches = {(v.subject, v.metric) for v in bl.check_nfr_p001(lopsided)}
    assert ("sentence_holds_ms", "P99") in breaches
    assert ("sentence_holds_ms", "P50") not in breaches, "the median hold is fast; only the tail breaches"


def test_non_streaming_holds_are_published_but_never_gated():
    """01 scopes NFR-P-001 to streaming pipelines, so the buffered hold cannot breach it.

    The non-streaming path records a one-element series (M-11: the response *is* the unit), and
    that entry is published. Gating it here would silently widen a requirement the docs scope.
    """
    buffered = bl.Batch(
        samples=[_sample(use_case="finance_advisor", streaming=False,
                         input_hold_ms=900.0, hold_series=(900.0,), overhead_ms=5_000.0)],
        store=PolicyStore(),
    )
    assert bl.check_nfr_p001(buffered) == []


def test_a_real_run_is_measurable_and_renders_a_verdict_not_the_third_state(batch):
    """The M-20 interim is over: a real replay carries both series, so the note retires.

    The staleness guard this replaces existed to make the interim note fail loudly once the
    instrumentation landed. It has now served its purpose, so what is pinned instead is the
    other direction — that the report does not keep printing "not measured" over series it
    actually has.
    """
    assert bl.nfr_p001_measurable(batch), "a real replay must emit the per-hold series"
    assert batch.input_holds(streaming=True), "input_hold_ms absent from a real run"
    assert batch.sentence_holds(streaming=True), "sentence_holds_ms absent from a real run"

    body = bl.render(batch, dataset_dir=bl.DATASET_DIR, provenance_note="", cadence_ms=0.5,
                     violations=[], live_note="")
    assert "**NFR-P-001: `not measured`.**" not in body
    assert "## NFR-P-001 — the targeted per-hold series (streaming)" in body
    assert "Both requirements were evaluated against emitted series" in body
    # The withdrawn target must not reappear as a live claim.
    assert "NFR-P-001 met" not in body
    assert "(NFR-P-001 scope)" not in body


def test_the_third_state_still_renders_when_a_run_carries_no_series(store):
    """An empty violation list over an unmeasured requirement is not a pass.

    Reachable without a time machine: a batch with no streaming samples has nothing NFR-P-001
    scopes to. The three states must stay distinct (M-10 / ADR-027 Amendment 1), so the report
    has to say which of "checked, clean" and "never checked" happened.
    """
    unmeasured = bl.Batch(
        samples=[_sample(use_case="finance_advisor", streaming=False, hold_series=())],
        store=store,
    )
    assert not bl.nfr_p001_measurable(unmeasured)
    body = bl.render(unmeasured, dataset_dir=bl.DATASET_DIR, provenance_note="", cadence_ms=0.5,
                     violations=[], live_note="")
    assert "**NFR-P-001: `not measured`.**" in body
    assert "neither meets nor fails NFR-P-001" in body
    assert "Both requirements were evaluated against emitted series" not in body


# ---------------------------------------------------------------------------
# Stats: absent is not zero
# ---------------------------------------------------------------------------


def test_an_empty_series_is_none_rather_than_a_row_of_zeros():
    """`Stats.of([])` is `None`. Zeros would read as "measured, and fast"."""
    assert bl.Stats.of([]) is None
    assert bl.Stats.of([1.0]).n == 1


def test_a_missing_series_renders_as_not_measured():
    """The rendered row for an absent series says so in words, and prints no number."""
    row = bl._row("UC-9 `nothing`", None)
    assert "not measured" in row
    assert "0.00" not in row


def test_stats_carry_their_sample_size(batch):
    """`n` travels with every percentile (AGENTS.md §7)."""
    stats = bl.Stats.of(batch.overheads(streaming=True))
    assert stats is not None and stats.n == len(batch.by_stream_mode(True))


def test_percentiles_come_from_the_one_shared_implementation():
    """`Stats` must use `telemetry.metrics.percentile`, not a second local definition.

    06 §4 fixes the percentile method, and the report stamps it in the provenance table. Two
    implementations could disagree at the same nominal percentile.
    """
    values = [float(i) for i in range(1, 101)]
    stats = bl.Stats.of(values)
    assert stats is not None
    from controlplane.telemetry.metrics import percentile

    assert stats.p50 == percentile(values, 50)
    assert stats.p99 == percentile(values, 99)


# ---------------------------------------------------------------------------
# Per-detector budgets
# ---------------------------------------------------------------------------


def test_detector_stats_are_read_from_the_registry_the_gateway_used(batch):
    """The three live detectors must appear, with observations."""
    stats = bl.detector_stats(batch)
    assert set(stats) >= {"tier1_pii", "tier1_blocklist"}
    for stat in stats.values():
        assert stat.n > 0


def test_nfr_p002_is_checked_on_p99_against_the_declared_budget():
    """A P99 at or above budget violates; one below does not."""
    budget = BUDGETS_MS["tier1_pii"]
    inside = {"tier1_pii": bl.Stats(n=50, p50=0.1, p95=0.2, p99=budget - 0.01,
                                    minimum=0.05, maximum=budget - 0.01)}
    outside = {"tier1_pii": bl.Stats(n=50, p50=0.1, p95=0.2, p99=budget + 1.0,
                                     minimum=0.05, maximum=budget + 1.0)}
    assert bl.check_nfr_p002(inside) == []
    violations = bl.check_nfr_p002(outside)
    assert [v.requirement for v in violations] == ["NFR-P-002"]
    assert violations[0].target == budget
    assert violations[0].metric == "P99"


def test_a_detector_with_no_budget_is_not_gated():
    """An unbudgeted detector is skipped, not compared against a default.

    Inventing a budget would be inventing an NFR; 04 §2 lists the ones that exist.
    """
    assert "invented_detector" not in BUDGETS_MS
    stats = {"invented_detector": bl.Stats(n=9, p50=1e6, p95=1e6, p99=1e6,
                                           minimum=1e6, maximum=1e6)}
    assert bl.check_nfr_p002(stats) == []


def test_unexercised_budgets_are_reported_as_untested_not_met(batch):
    """A detector that never ran must be named as untested (the M-10 distinction).

    `tier2_injection` has a budget and no implementation, so it is the standing example — and
    a report claiming its 25 ms budget was met would be the exact fabrication AGENTS.md §7
    forbids.
    """
    body = bl.render(
        batch, dataset_dir=bl.DATASET_DIR, provenance_note="", cadence_ms=0.5,
        violations=[], live_note="",
    )
    assert "tier2_injection" in body
    assert "untested rather than met" in body
    assert set(BUDGETS_MS) - set(bl.detector_stats(batch))


def test_faults_are_counted_and_absent_means_zero(batch):
    """The per-detector table's `Faults` column exists, and a clean run reports 0.

    Absent-means-zero is legitimate here and only here: a detector with latency observations
    demonstrably ran, so "no fault series" can only mean no fault. Contrast the latency table,
    where absent means never-checked.
    """
    assert bl.detector_faults(batch) == {}
    body = bl.render(
        batch, dataset_dir=bl.DATASET_DIR, provenance_note="", cadence_ms=0.5,
        violations=[], live_note="",
    )
    header = next(line for line in body.splitlines() if line.startswith("| Detector |"))
    columns = [c.strip() for c in header.strip("|").split("|")]
    assert "Faults" in columns, f"the promised Faults column is missing from {columns}"
    # Header and separator must agree in width, or every cell after the new column renders
    # one position left of its heading and the table silently lies about which number is which.
    separator = body.splitlines()[body.splitlines().index(header) + 1]
    assert len([c for c in separator.strip("|").split("|")]) == len(columns)
    row = next(line for line in body.splitlines() if line.startswith("| `tier1_pii`"))
    assert [c.strip() for c in row.strip("|").split("|")][columns.index("Faults")] == "0"


# ---------------------------------------------------------------------------
# Traffic mix
# ---------------------------------------------------------------------------


def test_the_mix_is_balanced_across_use_cases(corpus):
    mix = bl.traffic_mix(corpus, 300)
    counts = {uc: sum(1 for u, _ in mix if u == uc) for uc in USE_CASES}
    assert set(counts.values()) == {100}


def test_the_mix_is_deterministic(corpus):
    """Two builds on one freeze must be identical, or drift is indistinguishable from noise."""
    assert [(u, c["case_id"]) for u, c in bl.traffic_mix(corpus, 60)] == \
           [(u, c["case_id"]) for u, c in bl.traffic_mix(corpus, 60)]


def test_each_use_case_starts_at_a_different_offset(corpus):
    """Without the offset a short run would replay only the first file for all three."""
    mix = bl.traffic_mix(corpus, 30)
    firsts = {uc: next(c["case_id"] for u, c in mix if u == uc) for uc in USE_CASES}
    assert len(set(firsts.values())) == len(USE_CASES)


def test_a_short_run_still_spans_more_than_one_source_file(corpus):
    """The offset must reach beyond the first `.jsonl`, or whole risk classes go untimed."""
    mix = bl.traffic_mix(corpus, 30)
    assert len({c["_file"] for _, c in mix}) > 1


def test_the_mix_refuses_fewer_requests_than_use_cases(corpus):
    with pytest.raises(SystemExit):
        bl.traffic_mix(corpus, 2)


def test_the_mix_uses_the_whole_corpus_not_a_clean_subset(corpus):
    """A mix weighted to clean traffic would report the cheap path as the headline figure."""
    files = {c["_file"] for _, c in bl.traffic_mix(corpus, 300)}
    assert len(files) == len({c["_file"] for c in corpus})


# ---------------------------------------------------------------------------
# Report honesty
# ---------------------------------------------------------------------------


def test_render_refuses_a_batch_with_no_store(batch):
    """`render()` must not reconstruct the policy set — it would guess the table split."""
    orphan = bl.Batch(samples=list(batch.samples), metrics=batch.metrics, store=None)
    with pytest.raises(SystemExit):
        bl.render(orphan, dataset_dir=bl.DATASET_DIR, provenance_note="",
                  cadence_ms=0.5, violations=[], live_note="")


def test_render_refuses_an_unloaded_store(batch):
    """An empty `PolicyStore` is refused by name, not left to raise `UnknownUseCase`.

    The two failures are indistinguishable in effect — `render()` cannot know which pipelines
    stream — but only one of them says so. `UnknownUseCase` surfacing from a list comprehension
    would blame `support_bot` for a caller's mistake.
    """
    orphan = bl.Batch(samples=list(batch.samples), metrics=batch.metrics, store=PolicyStore())
    with pytest.raises(SystemExit, match="unloaded until"):
        bl.render(orphan, dataset_dir=bl.DATASET_DIR, provenance_note="",
                  cadence_ms=0.5, violations=[], live_note="")


def test_the_report_carries_no_response_text(batch, corpus):
    """No case text in the report — NFR-SEC-001, with force because reports are committed.

    The corpus includes synthetic PII fixtures. A leak into version history cannot be
    withdrawn, so this asserts on every case the run replayed rather than on a sample.
    """
    body = bl.render(batch, dataset_dir=bl.DATASET_DIR, provenance_note="",
                     cadence_ms=0.5, violations=[], live_note="")
    for case in corpus:
        text = case["text"]
        assert text not in body
        longest = max(text.split(), key=len, default="")
        if len(longest) > 12:
            assert longest not in body


def test_a_short_run_says_it_is_not_the_specified_benchmark(batch):
    """A sample smaller than 06 §4's 300 must be labelled as such in the provenance table."""
    body = bl.render(batch, dataset_dir=bl.DATASET_DIR, provenance_note="",
                     cadence_ms=0.5, violations=[], live_note="")
    assert f"06 §4 specifies {bl.DEFAULT_REQUESTS}" in body
    assert "not the specified benchmark" in body


def test_the_reference_row_is_labelled_as_not_the_headline(batch):
    """06 §4 requires the wall-minus-upstream row be reported and never headlined."""
    body = bl.render(batch, dataset_dir=bl.DATASET_DIR, provenance_note="",
                     cadence_ms=0.5, violations=[], live_note="")
    assert "never as the headline number" in body
    assert "upper bound" in body
    headline_at = body.index("`total_attributable_overhead_ms` — streaming pipelines")
    reference_at = body.index("Reference row")
    assert headline_at < reference_at, "the reference row must not precede the headline table"


def test_violations_render_as_a_d3_instruction_not_a_relaxed_target(batch):
    """A breach must point at the Deviation Protocol, and print the measured number."""
    body = bl.render(
        batch, dataset_dir=bl.DATASET_DIR, provenance_note="", cadence_ms=0.5, live_note="",
        violations=[bl.Violation("NFR-P-001", "all streaming pipelines", "P99", 100.0, 137.5)],
    )
    assert "D3" in body
    assert "137.500 ms" in body
    assert "never a relaxed threshold" in body


def test_excluded_requests_are_listed_not_dropped(store):
    """A run with errors must say so; percentiles over unexplained survivors are not data."""
    broken = bl.Batch(samples=[_sample()], store=store, requests_attempted=3,
                      errors=["X-001/support_bot: no request id (HTTP 500)"])
    body = bl.render(broken, dataset_dir=bl.DATASET_DIR, provenance_note="",
                     cadence_ms=0.5, violations=[], live_note="")
    assert "Requests excluded" in body
    assert "no request id" in body


def test_the_report_states_the_freeze_and_the_percentile_method(batch):
    """Both are required for the number to be reproducible (06 §8, AGENTS.md §7)."""
    body = bl.render(batch, dataset_dir=bl.DATASET_DIR, provenance_note="",
                     cadence_ms=0.5, violations=[], live_note="")
    assert bl.FROZEN_COMMIT[:12] in body
    assert "linear-interpolated" in body
    assert "Reproduce:" in body


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_the_freeze_gate_runs_before_any_measurement(tmp_path, capsys):
    """A dataset that is not the freeze must refuse to produce a report at all."""
    empty = tmp_path / "cases"
    empty.mkdir()
    out = tmp_path / "r.md"
    assert bl.main(["--dataset-dir", str(empty), "--out", str(out)]) == 1
    assert "FREEZE CHECK FAILED" in capsys.readouterr().err
    assert not out.exists(), "no report may be written when the freeze gate fails"


def test_a_clean_run_exits_zero_and_writes_the_report(tmp_path):
    """Assert on the SECTION HEADING, not the bare series name.

    The old form of this test asserted `"gateway_overhead_ms" in body`, which after
    ADR-030's rename passes on the Method section's prose *about* the rename — so it
    would have stayed green with the series itself gone. The heading is the structural
    thing: it exists only if the series was actually tabulated.
    """
    out = tmp_path / "latency.md"
    assert bl.main(["--requests", "6", "--out", str(out)]) == 0
    body = out.read_text()
    assert "## `total_attributable_overhead_ms` — streaming pipelines" in body
    assert "## `total_attributable_overhead_ms` — non-streaming pipelines" in body


def test_check_exits_nonzero_on_a_violation(tmp_path, monkeypatch):
    """`--check` is the D3 tripwire. Exercised with a hand-built slow sample.

    The double stands in for the *input* to gate arithmetic in a unit test of that arithmetic.
    It produces no judge-facing figure: the report goes to `tmp_path` and is discarded.
    """
    real = bl.run_batch

    def slow(mix, *, cadence_ms=bl.DEFAULT_CADENCE_MS):
        batch = real(mix, cadence_ms=cadence_ms)
        # NFR-P-002, not NFR-P-001. ADR-030 left NFR-P-001 with no gateable series (M-20), so
        # a slow *sum* can no longer trip anything — a tripwire test built on it would pass by
        # asserting nothing. Overshooting `tier1_pii`'s 2 ms budget exercises the same
        # exit-code path against a requirement that is still live.
        batch.metrics.observe("cp_detector_latency_ms", 5_000.0, detector="tier1_pii")
        return batch

    monkeypatch.setattr(bl, "run_batch", slow)
    out = tmp_path / "latency.md"
    assert bl.main(["--requests", "6", "--out", str(out), "--check"]) == 1
    # Asserted against the violation TABLE, not the bare string "NFR-P-002": that name also
    # appears in the report's opening line, so a substring check would pass on a harness that
    # had stopped detecting anything at all.
    body = out.read_text()
    assert "| NFR-P-002 | tier1_pii | P99 | 2.0 ms |" in body
    assert "never a relaxed threshold" in body


def test_without_check_a_violation_still_exits_zero(tmp_path, monkeypatch):
    """Absent `--check` this is a measurement run: the breach is reported, not enforced.

    The honest number plus a human ruling is what AGENTS.md §5.4 asks for; a run that always
    exited nonzero could not be used to *take* the measurement that a D3 report must quote.
    """
    real = bl.run_batch

    def slow(mix, *, cadence_ms=bl.DEFAULT_CADENCE_MS):
        batch = real(mix, cadence_ms=cadence_ms)
        batch.metrics.observe("cp_detector_latency_ms", 5_000.0, detector="tier1_pii")
        return batch

    monkeypatch.setattr(bl, "run_batch", slow)
    out = tmp_path / "latency.md"
    assert bl.main(["--requests", "6", "--out", str(out)]) == 0
    body = out.read_text()
    # The row, not the requirement name, and not the injected 5000.0 either: P99 is
    # linear-interpolated over the observations already in the registry, so the breach renders
    # at the interpolated value rather than at the number handed in.
    assert "| NFR-P-002 | tier1_pii | P99 | 2.0 ms |" in body
    assert "never a relaxed threshold" in body


def test_the_command_stamp_reproduces_the_actual_invocation(tmp_path):
    """The provenance `Command` must name the run that produced the numbers, not the default."""
    out = tmp_path / "latency.md"
    assert bl.main(["--requests", "6", "--out", str(out), "--cadence-ms", "2.0"]) == 0
    body = out.read_text()
    assert "--requests 6" in body
    assert "--cadence-ms 2.0" in body


def test_live_is_opt_in_and_reported_as_not_run(tmp_path):
    """The 30-request provider row is absent by default and says so — no substitute figure."""
    out = tmp_path / "latency.md"
    assert bl.main(["--requests", "6", "--out", str(out)]) == 0
    body = out.read_text()
    assert "End-to-end sanity row" in body
    assert "Not run" in body
    assert str(bl.LIVE_REQUESTS) in body


def test_live_against_a_dev_class_provider_produces_no_number(tmp_path):
    """ADR-018: a dev-class latency figure is not publishable, so `--live` yields prose."""
    out = tmp_path / "latency.md"
    assert bl.main(["--requests", "6", "--out", str(out), "--live"]) == 0
    body = out.read_text()
    assert "dev-class" in body
    assert "Not run" in body


def test_the_dev_class_note_scopes_the_taint_to_the_live_row(tmp_path):
    """The stub tables involve no provider, so the ADR-018 gate must not disclaim them."""
    out = tmp_path / "latency.md"
    assert bl.main(["--requests", "6", "--out", str(out)]) == 0
    body = out.read_text()
    assert "stub-upstream tables are unaffected" in body


def test_a_run_with_no_samples_writes_nothing(tmp_path, monkeypatch):
    """An empty batch must refuse the report rather than emit one full of "not measured"."""
    monkeypatch.setattr(
        bl, "run_batch",
        lambda mix, *, cadence_ms=bl.DEFAULT_CADENCE_MS: bl.Batch(
            store=PolicyStore(), requests_attempted=len(mix), errors=["boom"]
        ),
    )
    out = tmp_path / "latency.md"
    assert bl.main(["--requests", "6", "--out", str(out)]) == 1
    assert not out.exists()


# ---------------------------------------------------------------------------
# Batch hygiene
# ---------------------------------------------------------------------------


def test_one_registry_aggregates_the_whole_batch(batch):
    """Per-detector percentiles need every request in one registry, not 300 of size one."""
    assert isinstance(batch.metrics, MetricsRegistry)
    tier1 = bl.detector_stats(batch).get("tier1_pii")
    assert tier1 is not None and tier1.n >= len(batch.samples)


def test_every_attempted_request_is_either_a_sample_or_an_error(batch):
    """No request may vanish: the two buckets must account for the attempt count."""
    assert len(batch.samples) + len(batch.errors) == batch.requests_attempted


# ---------------------------------------------------------------------------
# Forward projection (a projection, never a measurement)
# ---------------------------------------------------------------------------


def test_sentence_counts_use_the_real_segmentation(corpus):
    """The multiplier must come from the shipped buffer, not a split on '.'.

    06 §4's streaming figure sums per-sentence holds, so the segment count multiplies any
    lane-cost projection. A local approximation would make the projection disagree with the
    pipeline it is projecting.
    """
    counts = bl.sentence_counts(corpus[:40])
    assert len(counts) == 40
    assert all(c >= 1 for c in counts), "a case with no boundary still holds one segment"

    from controlplane.gateway.sentence_buffer import Segmentation

    seg = Segmentation()
    expected = len(seg.feed("One. Two! Three? ")) + len(seg.flush())
    assert bl.sentence_counts([{"text": "One. Two! Three? "}]) == [expected]


def test_the_projection_is_derived_from_the_registry_not_written_down():
    """Lane membership and every figure must come from `LANES` / `BUDGETS_MS`.

    Pinned so a budget change moves the report instead of leaving a stale paragraph. The
    guard is a real substitution: raising a budget must raise the projected total.
    """
    cases = [{"text": "One sentence only."}]
    before = bl.project_tier2(cases)
    seq = next(r for r in before["rows"] if r["mode_is_sum"])
    assert seq["sentence_ms"] == sum(
        BUDGETS_MS[d] for d in LANES[Stage.OUTPUT_SENTENCE] if d != "rag_grounding"
    )
    assert set(before["pending"]) == {
        d for d in (*LANES[Stage.INPUT], *LANES[Stage.OUTPUT_SENTENCE])
        if d not in LIVE and d != "rag_grounding"
    }


def test_rag_grounding_is_excluded_and_the_exclusion_is_stated(batch, corpus):
    """Excluding a 30 ms/sentence detector improves the projection, so it must be disclosed.

    `expected_for` skips `rag_grounding` without context docs and no dataset case carries any,
    which makes the exclusion correct — but an undisclosed exclusion that flatters the number
    is the shape AGENTS.md §7 exists to prevent.
    """
    projection = bl.project_tier2(corpus[:20])
    assert "rag_grounding" not in projection["pending"]
    body = bl.render(batch, dataset_dir=bl.DATASET_DIR, provenance_note="", cadence_ms=0.5,
                     violations=[], live_note="", cases=corpus[:20])
    assert "rag_grounding" in body
    assert "excluded" in body


def test_both_lane_readings_are_reported(corpus):
    """Sequential and parallel are both shown, so the conclusion holds either way.

    `run_lane` is sequential today by a documented measurement decision; 02 §4's parallelism
    "becomes real when Tier-2 arrives". Reporting only one reading would make the finding
    contingent on an implementation detail that is expected to change.
    """
    rows = bl.project_tier2(corpus[:20])["rows"]
    assert len(rows) == 2
    assert [r["mode_is_sum"] for r in rows] == [True, False]
    seq, par = rows
    assert seq["sentence_ms"] > par["sentence_ms"], "the sum must exceed the max"
    assert par["sentence_ms"] == max(
        BUDGETS_MS[d] for d in LANES[Stage.OUTPUT_SENTENCE] if d != "rag_grounding"
    )


def test_the_projection_is_labelled_a_projection_and_not_a_d3(batch, corpus):
    """It must say it is not a measurement, and must not present itself as a breach.

    Today's measured figures pass. A projected breach filed as a D3 would spend a human
    decision on an event that has not happened, and would put an unobserved number next to
    measured ones — AGENTS.md §7 in the other direction.
    """
    body = bl.render(batch, dataset_dir=bl.DATASET_DIR, provenance_note="", cadence_ms=0.5,
                     violations=[], live_note="", cases=corpus[:20])
    section = body[body.index("## Forward projection"):body.index("## Scope and limitations")]
    assert "PROJECTION, not a measurement" in section
    assert "not a D3" in section
    assert "unimplemented" in section
    # It must not claim the budgets are wrong, nor that tier2 will cost its full budget.
    assert "not a claim that the budgets are wrong" in section
    assert "not a prediction that tier2 will actually cost its full budget" in section


def test_the_projection_states_the_measured_multiplier(batch, corpus):
    """The segment distribution is the load-bearing input, so it must be printed."""
    body = bl.render(batch, dataset_dir=bl.DATASET_DIR, provenance_note="", cadence_ms=0.5,
                     violations=[], live_note="", cases=corpus)
    section = body[body.index("## Forward projection"):body.index("## Scope and limitations")]
    assert "Segment counts measured over the frozen corpus" in section
    assert f"n={len(corpus)}" in section


def test_a_single_segment_response_stays_inside_the_target(corpus):
    """The projection must not overstate: one sentence is projected inside 100 ms.

    Guards the finding against inflation. If every row breached, the section would read as
    "tier2 is impossible", which the arithmetic does not support.
    """
    rows = bl.project_tier2([{"text": "One sentence only."}])["rows"]
    for row in rows:
        first = row["points"][0]
        assert first["sentences"] == 1
        assert not first["over_withdrawn_sum"], "one sentence was inside even the old target"
        # The quantities NFR-P-001 actually targets after ADR-030. These hold for every segment
        # count, not just one, because a per-hold target does not accumulate — which is the
        # substance of the respecification and the reason it resolves the contradiction.
        assert row["input_within"], "input-lane hold must fit its derived P99"
        assert row["sentence_within"], "per-sentence hold must fit its derived P99"


def test_the_headroom_factor_is_derived_from_the_measured_series(batch, corpus):
    """The "today's figures pass" margin must track the streaming table, not a written number.

    The first version of this sentence asserted "three orders of magnitude" and was wrong by
    more than one. A prose constant is also machine-specific: it would read as measured while
    describing someone else's hardware. So the factor is recomputed here from the same series
    the streaming table reports, and must appear verbatim in the rendered section.
    """
    body = bl.render(batch, dataset_dir=bl.DATASET_DIR, provenance_note="", cadence_ms=0.5,
                     violations=[], live_note="", cases=corpus[:20])
    section = body[body.index("## Forward projection"):body.index("## Scope and limitations")]

    stats = bl.Stats.of(batch.overheads(streaming=True))
    assert stats is not None and stats.p99 > 0.0, "fixture must produce a resolvable series"
    assert f"the measured sum is {stats.p99:.2f} ms P99 over {stats.n} samples" in section
    # Compared against the smallest PROJECTED figure, not against a target: ADR-030 withdrew
    # the 100 ms per-request threshold, and a ratio against a withdrawn target is arithmetic
    # about nothing.
    smallest = min(pt["total_ms"] for r in bl.project_tier2(corpus[:20])["rows"]
                   for pt in r["points"])
    assert f"smallest projected figure of {smallest:.0f} ms" in section
    # Neither claim this sentence has already got wrong may survive anywhere in the report.
    assert "orders of magnitude" not in body
    assert "a factor of" not in body


def test_an_unmeasured_streaming_series_states_that_rather_than_a_factor(store, corpus):
    """No samples is "not measured", never a margin of zero or infinity.

    Third state, per M-10 / ADR-027 Amendment 1: a report that printed a factor here would be
    asserting a comparison it never made.
    """
    empty = bl.Batch(store=store)
    body = bl.render(empty, dataset_dir=bl.DATASET_DIR, provenance_note="", cadence_ms=0.5,
                     violations=[], live_note="", cases=corpus[:20])
    section = body[body.index("## Forward projection"):body.index("## Scope and limitations")]
    assert "no streaming series was measured in this run" in section
    assert "a factor of" not in section
