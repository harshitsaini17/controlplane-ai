"""`/admin/requests` + `/admin/requests/{id}` — the per-request forensic projection.

Two kinds of test here, deliberately separated:

* **End-to-end**, through the real HTTP surface, for the claims that only hold if the whole
  lifecycle wrote what the projection reads — the NFR-SEC-001 leak hunt above all.
* **Unit**, calling the projection directly with synthetic coverage, for the four-state
  vocabulary. Reaching `UNAVAILABLE` end-to-end needs a genuinely unloadable dependency and
  a fail-open policy set; the state *distinction* is projection logic, and testing it here
  keeps the assertion on the thing that can actually regress.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from controlplane.audit import forensics
from controlplane.detectors.base import DetectorError, Stage
from controlplane.gateway import pipeline
from controlplane.gateway.app import Gateway, create_app
from demo.run_script import FixtureDispatcher

from tests.ml_stack import requires_ml

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "eval" / "dataset"

#: The frozen case whose text carries two raw PII values, and those values. Read from the
#: dataset rather than restated, so a re-freeze cannot leave this test hunting a string the
#: request no longer contains — which would pass forever while asserting nothing.
LEAK_CASE = "PII-041"

#: Delivery mode per policy (ADR-014): two of three pipelines stream, UC-3 does not. NOT a
#: free parameter — M-6 makes a body/policy mismatch a strict ERR-CFG-002 in *both*
#: directions, so passing the wrong flag here gets the request rejected at ingress, writes
#: no audit record, and makes the trace 404. That failure mode is why `fire()` asserts a
#: record exists: the first version of this file sent `hr_copilot` non-streaming, and the
#: leak hunt below "passed" against an error body containing no PII — a test asserting
#: nothing while reporting green.
STREAMS: dict[str, bool] = {
    "support_bot": True,
    "hr_copilot": True,
    "finance_advisor": False,
}


def case(filename: str, case_id: str) -> dict:
    for line in (DATASET / filename).read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            if row["case_id"] == case_id:
                return row
    raise AssertionError(f"{case_id} not in {filename}")


def fire(tmp_path, *, use_case: str, text: str, stream: bool | None = None,
         reply: str = "Here you go."):
    """One real request, returning (client, gateway, request_id, listing, trace).

    `stream` defaults to the policy's own mode via `STREAMS`. The two assertions after the
    POST are the guard rails: an ingress rejection (ERR-CFG-001/002) never reaches the
    pipeline, so it writes no record — and every assertion downstream of it would then be
    checking an error body rather than a trace.
    """
    if stream is None:
        stream = STREAMS[use_case]
    gateway = Gateway(dispatcher=FixtureDispatcher(reply), db_path=str(tmp_path / "audit.db"))
    with TestClient(create_app(gateway), raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": text}], "stream": stream},
            headers={"X-ControlPlane-Use-Case": use_case},
        )
        request_id = response.headers.get("x-controlplane-request-id")
        assert request_id, "05 §1.1: every response carries a correlation id"
        assert response.status_code != 400, (
            f"ingress rejected this request ({response.text[:120]}) — it never reached the "
            "pipeline, so nothing downstream of here is testing what it claims to test"
        )
        yield_client = client
        listing = client.get("/admin/requests?limit=10").json()
        trace = client.get(f"/admin/requests/{request_id}").json()
        assert "identity" in trace, f"no trace for {request_id}: {trace}"
    return yield_client, gateway, request_id, listing, trace


# ---------------------------------------------------------------------------
# NFR-SEC-001 — the leak hunt the task requires
# ---------------------------------------------------------------------------


@requires_ml
@pytest.mark.parametrize("use_case", ["support_bot", "hr_copilot", "finance_advisor"])
def test_no_raw_pii_value_reaches_either_endpoint(tmp_path, use_case) -> None:
    """★ A known synthetic PII value must appear ZERO times in both endpoints' JSON.

    Run across all three pipelines because each takes a different path to a different
    verdict, and the one that matters most is `finance_advisor`: it ESCALATES, which is the
    only path that writes content to `review_items.quarantined_text`. The projection joins
    that table for the review block and must not select that column — this is the assertion
    that keeps it that way.

    Hunts the raw values *and* their digit-only form, because a phone number stripped of
    punctuation is still the number.
    """
    row = case("pii.jsonl", LEAK_CASE)
    email = "jordan.blake@example.com"
    phone_digits = "5550100142"
    assert email in row["text"], "dataset drift: this test's premise is gone"

    _, _, _, listing, trace = fire(tmp_path, use_case=use_case, text=row["text"])
    for name, payload in (("list", listing), ("trace", trace)):
        blob = json.dumps(payload)
        assert email not in blob, f"{name}: raw email leaked"
        assert "010-0142" not in blob, f"{name}: raw phone leaked"
        assert phone_digits not in "".join(c for c in blob if c.isdigit()), (
            f"{name}: phone leaked with punctuation stripped"
        )
        # The request text itself must never be echoed, in whole or in a long slice.
        assert row["text"][:40] not in blob, f"{name}: prompt text leaked"


@requires_ml
def test_the_trace_does_not_select_quarantined_text(tmp_path) -> None:
    """The review block is metadata only; released text has its own audited endpoint."""
    row = case("pii.jsonl", LEAK_CASE)
    _, _, _, _, trace = fire(
        tmp_path, use_case="finance_advisor", text=row["text"]
    )
    review = trace["review"]
    assert review is not None and review["status"] == "pending"
    assert "quarantined_text" not in json.dumps(review)
    assert set(review) == {
        "review_id", "ts_created", "status", "decision_ts", "reviewer_note", "note"
    }


# ---------------------------------------------------------------------------
# The four ADR-033 states stay distinct
# ---------------------------------------------------------------------------


def _rows(**kw):
    base = dict(
        signals=[], coverage={"ran": [], "not_run": []}, failures=[], latency={},
        reached={"input_lane"}, policy=None,
        lanes={Stage.INPUT: ("tier1_pii",)}, span_of={},
    )
    base.update(kw)
    return forensics._detector_rows(**base)


def test_the_four_detector_states_are_all_distinguishable() -> None:
    """★ The point of the grid: "did not look" is not "looked and found nothing".

    Four inputs that a coarser projection would collapse into two. `UNAVAILABLE` outranks
    `FAILED` outranks fired: a detector whose dependency is missing never ran, so a fault
    row for it would describe an attempt that did not happen.
    """
    clean = _rows(coverage={"ran": ["tier1_pii"], "not_run": []})[0]
    assert clean["state"] == forensics.RAN_CLEAN

    fired = _rows(
        coverage={"ran": ["tier1_pii"], "not_run": []},
        signals=[{"detector": "tier1_pii", "stage": "input", "labels": ["pii.email"],
                  "score": 1.0, "score_kind": "detection", "planes": ["responsibility"],
                  "signal_id": "s1", "latency_ms": 0.3, "span": {"start": 0, "end": 5},
                  "evidence": "category:email pattern=rfc5322"}],
    )[0]
    assert fired["state"] == forensics.RAN_FIRED
    assert fired["labels"] == ["pii.email"] and fired["score"] == 1.0

    faulted = _rows(
        coverage={"ran": ["tier1_pii"], "not_run": []},
        failures=[{"detector": "tier1_pii", "stage": "input", "error_class": "DetectorError",
                   "fail_mode_applied": "fail_closed", "failure_id": "f1"}],
    )[0]
    assert faulted["state"] == forensics.FAILED
    assert faulted["state_detail"] == "DetectorError"
    assert faulted["fail_mode_applied"] == "fail_closed"

    absent = _rows(coverage={"ran": [], "not_run": [],
                             "unavailable": [{"detector": "tier1_pii", "missing": "onnxruntime"}]})[0]
    assert absent["state"] == forensics.UNAVAILABLE
    assert absent["state_detail"] == "onnxruntime"

    never = _rows(coverage={"ran": [], "not_run": [{"detector": "tier1_pii",
                                                   "reason": "not_implemented"}]})[0]
    assert never["state"] == forensics.NOT_RUN
    assert never["state_detail"] == "not_implemented"

    states = {clean["state"], fired["state"], faulted["state"], absent["state"], never["state"]}
    assert len(states) == 5, "two states collapsed — the grid's whole claim is the distinction"


def test_an_unavailable_detector_is_never_reported_as_a_fault() -> None:
    """ADR-033: a missing dependency is host-level absence, not a per-request fault."""
    row = _rows(
        coverage={"ran": [], "not_run": [],
                  "unavailable": [{"detector": "tier1_pii", "missing": "onnxruntime"}]},
        failures=[{"detector": "tier1_pii", "stage": "input", "error_class": "ImportError",
                   "fail_mode_applied": "fail_closed", "failure_id": "f1"}],
    )[0]
    assert row["state"] == forensics.UNAVAILABLE


# ---------------------------------------------------------------------------
# The three defects found by running this against real requests
# ---------------------------------------------------------------------------


@requires_ml
def test_a_dispatched_request_does_not_report_dispatch_as_skipped(tmp_path) -> None:
    """★ Regression: the dispatch node read `cp.upstream`, which is never written.

    The provider wait is recorded as `upstream_ms` (a LATENCY_EXTRA_KEYS entry — 06 §4 needs
    it *subtractable*). Reading the span name made every dispatched request render its most
    visible stage as "skipped" while the timing sat in the row.
    """
    _, _, _, _, trace = fire(
        tmp_path, use_case="support_bot", text=case("clean.jsonl", "CLN-001")["text"],
    )
    dispatch = next(n for n in trace["timeline"] if n["key"] == "dispatch")
    assert dispatch["state"] != "skipped", "a request that dispatched must not read skipped"
    assert dispatch["elapsed_ms"] is not None
    assert "upstream_ms" in dispatch["spans_present"]


@requires_ml
def test_a_pre_dispatch_block_does_report_dispatch_as_skipped_with_a_reason(tmp_path) -> None:
    """The other half: grey is a *fact* about this request, and it names itself."""
    _, _, _, _, trace = fire(
        tmp_path, use_case="hr_copilot", text=case("pii.jsonl", LEAK_CASE)["text"],
    )
    dispatch = next(n for n in trace["timeline"] if n["key"] == "dispatch")
    assert dispatch["state"] == "skipped"
    assert dispatch["reason"] == "blocked pre-dispatch — upstream never called"
    assert trace["identity"]["stream_mode"] == "blocked-pre-dispatch"


def test_a_shared_span_never_produces_a_breach_verdict() -> None:
    """★ The two-clock defect ADR-036 exists to end, caught on this surface.

    `cp.out.tier2` is an aggregate over every sentence; `tier2_toxicity`'s budget is
    per-window. Comparing them rendered 38.9 ms vs 25.0 ms as a breach on a request where
    nothing breached. `breach` is None — *not comparable* — whenever the figure is shared.
    """
    row = _rows(
        lanes={Stage.OUTPUT_SENTENCE: ("tier2_toxicity",)},
        span_of={(Stage.OUTPUT_SENTENCE, "tier2_toxicity"): "cp.out.tier2"},
        reached={"output_lane"},
        coverage={"ran": ["tier2_toxicity"], "not_run": []},
        latency={"cp.out.tier2": 38.856},
    )[0]
    assert row["attributable_ms"] == 38.856
    assert row["attributable_shared_span"] is True
    assert row["breach"] is None, "an aggregate must not be judged against a per-call budget"
    assert "ADR-036" in row["breach_note"]


def test_a_per_invocation_measurement_does_produce_a_breach_verdict() -> None:
    """The negative control: without this, the fix above could be "never report a breach"."""
    row = _rows(
        coverage={"ran": ["tier1_pii"], "not_run": []},
        signals=[{"detector": "tier1_pii", "stage": "input", "labels": ["pii.email"],
                  "score": 1.0, "score_kind": "detection", "planes": ["responsibility"],
                  "signal_id": "s1", "latency_ms": 99.0, "span": None,
                  "evidence": "category:email pattern=rfc5322"}],
    )[0]
    assert row["attributable_shared_span"] is False
    assert row["breach"] is True, "a per-invocation figure over budget IS a breach"


@requires_ml
def test_the_audit_node_does_not_claim_it_was_skipped(tmp_path) -> None:
    """A record cannot time its own write, and must not report that as a missing stage."""
    _, _, _, _, trace = fire(
        tmp_path, use_case="support_bot", text=case("clean.jsonl", "CLN-001")["text"],
    )
    audit = next(n for n in trace["timeline"] if n["key"] == "audit")
    assert audit["state"] == "clean"
    assert audit["elapsed_ms"] is None
    assert "not recordable" in audit["reason"]


# ---------------------------------------------------------------------------
# Convergence arithmetic + honesty rules
# ---------------------------------------------------------------------------


@requires_ml
def test_the_signature_moment_is_derived_not_asserted(tmp_path) -> None:
    """★ One label map, three verdicts — the product thesis, shown as arithmetic.

    The same `pii.*` wildcard resolves to a different action in each pipeline, and the
    convergence panel must name the rule that did it rather than only the answer.
    """
    text = case("pii.jsonl", LEAK_CASE)["text"]
    seen = {}
    for use_case in STREAMS:
        _, _, _, _, trace = fire(tmp_path / use_case, use_case=use_case, text=text)
        conv = trace["convergence"]
        rows = [r for r in conv["label_resolution"] if r["label"] == "pii.email"]
        assert rows, f"{use_case}: no resolution row for the label that fired"
        assert rows[0]["matched_rule"] == "actions['pii.*'] (wildcard)"
        assert rows[0]["action"] == trace["identity"]["verdict"]
        winning = [l for l in conv["severity_ladder"] if l["winning"]]
        assert len(winning) == 1 and winning[0]["action"] == trace["identity"]["verdict"]
        seen[use_case] = trace["identity"]["verdict"]

    assert len(set(seen.values())) == 3, f"the signature moment collapsed: {seen}"


@requires_ml
def test_the_cross_pipeline_note_is_labelled_a_projection(tmp_path) -> None:
    """Rule G: derived-from-config is offered as such, never as a simulated verdict."""
    _, _, _, _, trace = fire(
        tmp_path, use_case="support_bot", text=case("pii.jsonl", LEAK_CASE)["text"],
    )
    ctx = trace["policy_context"]
    assert set(ctx["cross_pipeline_projection"]) == {
        "support_bot", "hr_copilot", "finance_advisor"
    }
    caveat = ctx["cross_pipeline_caveat"]
    assert "not a re-run" in caveat and "thresholds" in caveat


@requires_ml
def test_a_clean_request_offers_no_cross_pipeline_projection(tmp_path) -> None:
    """No labels raised means nothing to project, so the key is absent rather than empty.

    Part F says "IF AND ONLY IF it can be derived" — an empty projection would invite the
    reader to conclude the other pipelines would have passed it too, which this evidence
    does not establish.
    """
    _, _, _, _, trace = fire(
        tmp_path, use_case="support_bot", text=case("clean.jsonl", "CLN-001")["text"],
    )
    assert trace["policy_context"]["labels_raised"] == []
    assert "cross_pipeline_projection" not in trace["policy_context"]


@requires_ml
def test_an_unknown_request_id_is_404_not_500(tmp_path) -> None:
    gateway = Gateway(dispatcher=FixtureDispatcher("hi"), db_path=str(tmp_path / "a.db"))
    with TestClient(create_app(gateway), raise_server_exceptions=False) as client:
        response = client.get("/admin/requests/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ERR-ADM-404"


@requires_ml
def test_a_dev_class_row_says_why_its_cost_is_null(tmp_path) -> None:
    """ADR-018 travels with the row: null cost is a provenance rule, not a missing number."""
    _, _, _, _, trace = fire(
        tmp_path, use_case="support_bot", text=case("clean.jsonl", "CLN-001")["text"],
    )
    identity = trace["identity"]
    assert identity["upstream_class"] == "dev"
    assert identity["est_cost_usd"] is None
    assert "ADR-018" in identity["cost_note"]


@requires_ml
def test_a_detector_fault_appears_in_the_trace_with_its_fail_mode(tmp_path, monkeypatch) -> None:
    """04 §5: the fault is visible in the forensic view, with the mode policy applied."""
    class Broken:
        name = "tier1_pii"

        async def detect(self, ctx):
            raise DetectorError("tier1_pii", "boom")

    monkeypatch.setitem(pipeline.LIVE, "tier1_pii", Broken())
    _, _, _, _, trace = fire(
        tmp_path, use_case="support_bot", text=case("clean.jsonl", "CLN-001")["text"],
    )
    faults = trace["failures"]
    assert faults, "a fault must never be silent in the record"
    assert faults[0]["detector"] == "tier1_pii"
    assert faults[0]["fail_mode_applied"] == "fail_closed"
    assert faults[0]["fail_class"] == "tier1"
    # No measured interval exists for a raise, and the payload says so rather than 0.0.
    assert faults[0]["attributable_ms"] is None
    grid = [r for r in trace["detectors"] if r["detector"] == "tier1_pii"
            and r["state"] == forensics.FAILED]
    assert grid, "the grid must show the faulted detector as FAILED"
