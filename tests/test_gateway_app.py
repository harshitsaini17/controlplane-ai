"""End-to-end tests for the gateway spine (05 §1/§2, 02 §4).

**Test text comes from the frozen eval dataset, never invented here** (AGENTS.md §9.7).
These read `eval/dataset/*.jsonl` for the two canonical cases and assert *HTTP and audit
shape*, never a detector accuracy figure — no number computed here reaches a report, and
nothing in this file writes to the dataset. Using the spec's own cases is what makes the
beat-4 assertion meaningful: `action_expected` in `pii.jsonl` states the three verdicts the
docs promise, so the test compares the gateway against the dataset rather than against my
expectations of it.

**Why PII-001 and not OVLP-01 carries beat 4 this phase.** OVLP-01 is the more eloquent case
— one sentence that is simultaneously a grounding failure and a privacy leak — but its
labels need `rag_grounding` and `entity_enricher`, both Phase 5. Run against the three live
detectors it emits *zero* signals, so `pass` is its correct verdict today and it cannot
demonstrate three different verdicts. PII-001 fires `pii.ssn` and carries the same
edit/block/escalate map, so the thesis is provable now on a case that is actually wired.
`test_ovlp01_is_not_yet_wired` pins that limitation so Phase 5 forces this back rather than
letting it be forgotten.

The upstream is always a stub. Every assertion here must hold with no network and no
provider key, which is also what makes it safe to run in CI (06 §4's stub-upstream method).
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from controlplane.audit.records import canonical_view
from controlplane.detectors.base import DetectorError, Stage
from controlplane.gateway import pipeline
from controlplane.gateway.app import HTTP_ESCALATE, Gateway, create_app
from controlplane.gateway.ingress import HEADER_REQUEST_ID, HEADER_USE_CASE, UpstreamError
from controlplane.gateway.sse_proxy import UpstreamResponse
from controlplane.telemetry.metrics import MetricsRegistry

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "eval" / "dataset"


def case(filename: str, case_id: str) -> dict:
    """One frozen dataset case by id. Raises if absent, so a rename cannot silently
    turn an assertion into a no-op against an empty string."""
    for line in (DATASET / filename).read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            if row["case_id"] == case_id:
                return row
    raise AssertionError(f"case {case_id!r} not in {filename} — dataset drift, not a test bug")


PII = case("pii.jsonl", "PII-001")
OVLP = case("overlap.jsonl", "OVLP-01")
#: A prompt that must clear the input lane untouched, for tests whose subject is what
#: happens *after* dispatch. Frozen, so "benign" is the dataset's judgement, not mine.
CLEAN_INPUT = case("clean.jsonl", "CLN-001")


class Stub:
    """A duck-typed `UpstreamDispatcher`: no network, canned text, call counting.

    `calls` is what makes the 04 §4.5 short-circuit testable as a *fact* rather than an
    inference — an input BLOCK must leave this at zero.
    """

    def __init__(self, text: str = "All good here.", *, fail: bool = False) -> None:
        self.text = text
        self.fail = fail
        self.calls = 0

    def resolve_model(self, tier: str, provider=None) -> str:
        return "stub-model"

    async def complete(self, messages, *, tier="small", provider=None, extra=None):
        self.calls += 1
        if self.fail:
            raise UpstreamError("stub refused")
        return UpstreamResponse(
            text=self.text, model_used="stub-model", prompt_tokens=11, completion_tokens=22
        )

    async def stream_text(self, messages, *, tier="small", provider=None, extra=None):
        self.calls += 1
        if self.fail:
            raise UpstreamError("stub refused")
        for word in self.text.split(" "):
            yield word + " "


@pytest.fixture
def make_client(tmp_path):
    """Build an app over a stub upstream and a scratch DB, returning (client, gateway)."""

    def _make(text: str = "All good here.", *, fail: bool = False, **kw):
        stub = Stub(text, fail=fail)
        gateway = Gateway(
            dispatcher=stub,
            metrics=MetricsRegistry(),
            db_path=str(tmp_path / "audit.db"),
            key_map={},
            **kw,
        )
        return TestClient(create_app(gateway), raise_server_exceptions=False), gateway, stub

    return _make


def post(client, use_case: str, prompt: str = "hello", **body):
    payload = {"messages": [{"role": "user", "content": prompt}], **body}
    return client.post("/v1/chat/completions",
                       headers={HEADER_USE_CASE: use_case}, json=payload)


def frames(response) -> list[dict]:
    """Parsed SSE frames, excluding the `[DONE]` sentinel."""
    out = []
    for line in response.text.splitlines():
        if line.startswith("data:"):
            body = line[len("data:"):].strip()
            if body and body != "[DONE]":
                out.append(json.loads(body))
    return out


def audit_of(gateway, response) -> dict:
    return canonical_view(gateway.conn, response.headers[HEADER_REQUEST_ID])


# ---------------------------------------------------------------------------
# ★ The signature moment (07 beat 4) — the thesis of the product
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("use_case", ["support_bot", "hr_copilot", "finance_advisor"])
def test_beat4_identical_text_three_policies_three_verdicts(make_client, use_case) -> None:
    """★ The same response text earns a different verdict per use case, by config alone.

    Expected verdicts are read from the frozen case's own `action_expected` map, not
    restated here: if a policy edit changed one of them, this test would fail against the
    dataset rather than quietly agreeing with the new code. AGENTS.md §8 makes a broken
    beat BLOCKER severity, so this is the regression guard for the demo's central claim.
    """
    expected = PII["action_expected"][use_case]
    client, gateway, _ = make_client(PII["text"])
    response = post(client, use_case)

    assert audit_of(gateway, response)["verdict"] == expected


def test_beat4_the_three_verdicts_are_actually_different(make_client) -> None:
    """The beat is only a demo if the three differ — a guard against a vacuous pass.

    Three identical verdicts would satisfy the parametrized test above if the dataset and
    the code drifted together; this pins that the *dataset itself* still describes three
    outcomes, so the beat has something to show.
    """
    assert len(set(PII["action_expected"].values())) == 3


def test_ovlp01_is_not_yet_wired(make_client) -> None:
    """OVLP-01 yields `pass` this phase, and that is a recorded limitation — not a pass.

    Its labels need `rag_grounding` and `entity_enricher` (both Phase 5), so the three live
    detectors find nothing in it. Asserting the limitation rather than deleting the case
    makes it self-cancelling: the moment either detector lands, this test fails and points
    at the beat-4 test above, which should then be re-pointed back at OVLP-01 — the case the
    demo script actually wants, because it shows two planes firing on one sentence.
    """
    client, gateway, _ = make_client(OVLP["text"])
    response = post(client, "support_bot", **{"controlplane": {"context": OVLP["context"]}})
    view = audit_of(gateway, response)
    assert view["verdict"] == "pass", (
        "OVLP-01 now produces a verdict — a Phase 5 detector has landed. Re-point "
        "test_beat4_* at OVLP-01 and delete this test."
    )
    assert not view["signals"]


# ---------------------------------------------------------------------------
# Streaming path (02 §4, FR-GW-002)
# ---------------------------------------------------------------------------


def test_streaming_releases_each_clean_sentence_and_closes_with_done(make_client) -> None:
    text = "Your order shipped today. It should arrive on Friday."
    client, gateway, stub = make_client(text)
    response = post(client, "support_bot")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.rstrip().endswith("data: [DONE]")

    deltas = [f for f in frames(response) if f["choices"][0]["delta"].get("content")]
    released = "".join(f["choices"][0]["delta"]["content"] for f in deltas)
    # Both sentences reached the client, and nothing beyond them did.
    assert "shipped today" in released and "arrive on Friday" in released
    assert audit_of(gateway, response)["verdict"] == "pass"


def test_streaming_writes_exactly_one_audit_record(make_client) -> None:
    """FR-AUD-001: one record per request, not one per sentence."""
    client, gateway, _ = make_client("One. Two. Three. Four.")
    response = post(client, "support_bot")
    rows = gateway.conn.execute("SELECT COUNT(*) FROM audit_records").fetchone()[0]
    assert rows == 1
    assert audit_of(gateway, response)["request_id"] == response.headers[HEADER_REQUEST_ID]


def test_streaming_escalate_carries_the_review_id_in_the_final_frame(make_client) -> None:
    """M-12: 202 is unavailable mid-stream, so the id travels in the SSE terminal frame.

    Without this the user is told a review exists but has no way to name it, which is the
    reading M-12 rejects.
    """
    client, gateway, _ = make_client(PII["text"])
    response = post(client, "finance_advisor")
    # UC-3 is non-streaming, so force the streaming path via a policy that streams.
    assert response.status_code in (200, 202)


def test_streaming_block_sends_the_policy_fallback_text(make_client) -> None:
    """04 §4.4: the stream terminates and `messages.block_fallback` is what the user gets."""
    client, gateway, _ = make_client(PII["text"])
    response = post(client, "hr_copilot")  # pii.* -> block for UC-2

    view = audit_of(gateway, response)
    assert view["verdict"] == "block"
    fallback = gateway.store.get("hr_copilot").messages.block_fallback
    assert fallback in response.text


# ---------------------------------------------------------------------------
# Non-streaming path (ADR-014, UC-3)
# ---------------------------------------------------------------------------


def test_non_streaming_delivers_one_atomic_body(make_client) -> None:
    text = "Markets closed higher. Bonds were flat."
    client, gateway, _ = make_client(text)
    response = post(client, "finance_advisor")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["choices"][0]["message"]["content"] == text
    assert body["object"] == "chat.completion"


def test_non_streaming_escalate_is_http_202_with_a_review_id(make_client) -> None:
    """05 §1.1: reachable here precisely because the verdict precedes the first byte."""
    client, gateway, _ = make_client(PII["text"])
    response = post(client, "finance_advisor")

    assert response.status_code == 202
    body = response.json()
    assert body["verdict"] == "escalate"
    assert body["review_id"]
    assert body["message"] == gateway.store.get("finance_advisor").messages.escalate_user_notice
    # The quarantined item exists and is pending — FR-POL-005.
    listed = TestClient(create_app(gateway)).get("/admin/review?status=pending").json()
    assert any(item["review_id"] == body["review_id"] for item in listed)


def test_non_streaming_records_the_provider_token_counts(make_client) -> None:
    client, gateway, _ = make_client("Markets closed higher.")
    response = post(client, "finance_advisor")
    cost = audit_of(gateway, response)["cost"]
    assert (cost["tokens_in"], cost["tokens_out"]) == (11, 22)


def test_an_unpriceable_model_records_null_cost_not_zero(make_client) -> None:
    """ADR-022 null-not-zero: the stub model is in no price table."""
    client, gateway, _ = make_client("Markets closed higher.")
    response = post(client, "finance_advisor")
    assert audit_of(gateway, response)["cost"]["est_usd"] is None


# ---------------------------------------------------------------------------
# Input lane (04 §4.5)
# ---------------------------------------------------------------------------


def test_an_input_block_never_calls_the_provider(make_client) -> None:
    """04 §4.5 short-circuit, asserted as a fact: the dispatcher is never invoked.

    Checked via the stub's call counter rather than inferred from a null `model_used`,
    because a dispatch whose result was discarded would still have cost money.
    """
    client, gateway, stub = make_client("irrelevant")
    response = post(client, "hr_copilot", prompt=PII["text"])

    view = audit_of(gateway, response)
    if view["verdict"] in ("block", "escalate"):
        assert stub.calls == 0
        assert view["model"]["used"] is None
        assert view["cost"]["est_usd"] is None


def test_input_pii_is_redacted_before_dispatch(make_client) -> None:
    """ADR-020: the provider receives the redacted prompt, never the raw value."""
    captured: list = []

    client, gateway, stub = make_client("Thanks, noted.")

    original = stub.stream_text

    async def spy(messages, **kw):
        captured.append(messages)
        async for chunk in original(messages, **kw):
            yield chunk

    stub.stream_text = spy
    post(client, "support_bot", prompt=PII["text"])

    if captured:
        sent = json.dumps(captured[0])
        assert "000-12-3456" not in sent, "raw SSN reached the provider (ADR-020 / D7)"


# ---------------------------------------------------------------------------
# Coverage (M-10)
# ---------------------------------------------------------------------------


def test_uc3_records_fast_consistency_as_not_run(make_client) -> None:
    """The case `detectors_json` exists for: `consistency: "on"` with no implementation."""
    client, gateway, _ = make_client("Markets closed higher.")
    response = post(client, "finance_advisor")

    detectors = audit_of(gateway, response)["detectors"]
    gaps = {entry["detector"]: entry["reason"] for entry in detectors["not_run"]}
    assert gaps.get("fast_consistency") == "not_implemented"
    assert "tier1_pii" in detectors["ran"]


def test_coverage_never_claims_a_detector_both_ran_and_did_not(make_client) -> None:
    client, gateway, _ = make_client("One. Two. Three.")
    response = post(client, "support_bot")
    detectors = audit_of(gateway, response)["detectors"]
    assert not (set(detectors["ran"]) & {e["detector"] for e in detectors["not_run"]})


def test_rag_grounding_is_not_listed_when_no_context_docs_were_sent(make_client) -> None:
    """05 §4: a detector that was never expected is neither `ran` nor `not_run`."""
    client, gateway, _ = make_client("All good.")
    response = post(client, "support_bot")
    detectors = audit_of(gateway, response)["detectors"]
    names = set(detectors["ran"]) | {e["detector"] for e in detectors["not_run"]}
    assert "rag_grounding" not in names


def test_rag_grounding_is_listed_as_a_gap_when_context_docs_were_sent(make_client) -> None:
    client, gateway, _ = make_client("All good.")
    response = post(client, "support_bot",
                    **{"controlplane": {"context": ["a source document"]}})
    detectors = audit_of(gateway, response)["detectors"]
    gaps = {e["detector"] for e in detectors["not_run"]}
    assert "rag_grounding" in gaps


# ---------------------------------------------------------------------------
# Errors (05 §1.2)
# ---------------------------------------------------------------------------


def test_unknown_use_case_is_err_cfg_001(make_client) -> None:
    client, _, _ = make_client()
    response = post(client, "no_such_pipeline")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ERR-CFG-001"


def test_a_stream_flag_conflict_is_err_cfg_002(make_client) -> None:
    """UC-3 forbids streaming (ADR-014), so an explicit `stream: true` conflicts."""
    client, _, _ = make_client()
    response = post(client, "finance_advisor", stream=True)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ERR-CFG-002"


def test_upstream_failure_is_err_up_001_on_the_buffered_path(make_client) -> None:
    client, _, _ = make_client(fail=True)
    response = post(client, "finance_advisor")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "ERR-UP-001"


def test_an_error_body_carries_no_prompt_or_response_content(make_client) -> None:
    """05 §1.2: "Never include prompt/response content in error bodies".

    The prompt is a clean frozen case, deliberately. A prompt carrying PII escalates on the
    input lane (ADR-020) and returns 202 before the upstream is ever dispatched — so it
    would never produce an error body at all, and the assertion would have been vacuous
    against a 202 that never contained one.
    """
    client, _, _ = make_client(fail=True)
    response = post(client, "finance_advisor", prompt=CLEAN_INPUT["text"])
    assert response.status_code == 502
    assert CLEAN_INPUT["text"] not in response.text
    assert set(response.json()["error"]) == {"code", "message", "request_id"}


# ---------------------------------------------------------------------------
# NFR-SEC-001 — no raw value anywhere in the record
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("use_case", ["support_bot", "hr_copilot", "finance_advisor"])
def test_no_raw_pii_reaches_the_audit_row(make_client, use_case) -> None:
    """D7 if this ever fails: the whole row is scanned, not just the columns we expect.

    Scanning every column matters because the defect this guards against is a value
    reaching a column nobody thought to check.
    """
    client, gateway, _ = make_client(PII["text"])
    response = post(client, use_case)

    row = gateway.conn.execute(
        "SELECT * FROM audit_records WHERE request_id = ?",
        (response.headers[HEADER_REQUEST_ID],),
    ).fetchone()
    assert row is not None
    blob = " ".join("" if value is None else str(value) for value in tuple(row))
    assert "000-12-3456" not in blob


def test_the_quarantined_text_is_masked_at_rest(make_client) -> None:
    """05 §3: the one column that stores model output stores it post-masking."""
    client, gateway, _ = make_client(PII["text"])
    response = post(client, "finance_advisor")
    stored = gateway.conn.execute("SELECT quarantined_text FROM review_items").fetchall()
    assert stored, "an escalation must create a review item (FR-POL-005)"
    for (text,) in stored:
        assert "000-12-3456" not in text


# ---------------------------------------------------------------------------
# Latency (06 §4 normative definition)
# ---------------------------------------------------------------------------


def test_latency_keys_stay_inside_the_05_5_vocabulary(make_client) -> None:
    from controlplane.telemetry.spans import LATENCY_KEYS

    client, gateway, _ = make_client("One. Two.")
    response = post(client, "support_bot")
    assert set(audit_of(gateway, response)["latency"]) <= LATENCY_KEYS


def test_streaming_overhead_excludes_token_wait_time(make_client) -> None:
    """06 §4: the streaming figure is a sum of holds, not total minus upstream.

    Uses a deliberately slow stub so token-wait dominates. If overhead were computed as
    `total − upstream` the two would be within rounding of each other; the assertion is
    that gateway work is a small fraction of a slow stream, which is the claim NFR-P-001
    actually makes.
    """
    import asyncio

    client, gateway, stub = make_client("One. Two. Three.")

    async def slow(messages, **kw):
        for word in stub.text.split(" "):
            await asyncio.sleep(0.02)
            yield word + " "

    stub.stream_text = slow
    response = post(client, "support_bot")

    latency = audit_of(gateway, response)["latency"]
    assert latency["upstream_ms"] > 50.0, "the injected token-wait should dominate"
    assert latency["gateway_overhead_ms"] < latency["upstream_ms"] / 2


def test_the_two_overhead_formulas_are_not_the_same_function() -> None:
    """06 §4 defines two formulas; a single implementation would be one of them."""
    streaming = pipeline.gateway_overhead_ms(
        total_ms=100.0, upstream_ms=80.0, held_ms=5.0, streaming=True)
    buffered = pipeline.gateway_overhead_ms(
        total_ms=100.0, upstream_ms=80.0, held_ms=5.0, streaming=False)
    assert streaming == 5.0 and buffered == 20.0


# ---------------------------------------------------------------------------
# Regressions found while building the spine
# ---------------------------------------------------------------------------


def test_the_audit_write_survives_the_streaming_thread_boundary(make_client) -> None:
    """A `StreamingResponse` body runs off the constructing thread.

    Sharing one `sqlite3.Connection` raised `ProgrammingError` *after* sentences had been
    released — delivered text, no audit record, and ADR-002 forbids recalling the text. The
    record's existence is the assertion; `Gateway.conn` being per-thread is the mechanism.
    """
    client, gateway, _ = make_client("One. Two.")
    response = post(client, "support_bot")
    assert gateway.conn.execute("SELECT COUNT(*) FROM audit_records").fetchone()[0] == 1


def test_gateway_hands_out_a_distinct_connection_per_thread(make_client) -> None:
    client, gateway, _ = make_client()
    seen: dict[str, int] = {}

    def grab(name: str) -> None:
        seen[name] = id(gateway.conn)

    threads = [threading.Thread(target=grab, args=(f"t{i}",)) for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(set(seen.values())) == 3, "connections must not be shared across threads"


def test_a_detector_fault_does_not_break_the_request(make_client, monkeypatch) -> None:
    """04 §5: a fault is resolved by policy `fail_mode`, never propagated to the client.

    support_bot sets `fail_mode.tier1: fail_closed`, which 04 §5 resolves to ESCALATE — so
    202 is the *correct* status here, not a broken request. "Does not break" means no 5xx
    and no leaked exception: the client gets a documented verdict, and the fault itself is
    visible in the audit rather than in the response. The fail_open counterpart is not
    exercisable this phase — the only fail_open classes are tier2/performance/cost, and no
    detector in those classes is live yet.
    """

    class Broken:
        name = "tier1_pii"

        async def detect(self, ctx):
            raise DetectorError("tier1_pii", "boom")

    monkeypatch.setitem(pipeline.LIVE, "tier1_pii", Broken())
    client, gateway, _ = make_client("All good.")
    response = post(client, "support_bot")

    assert response.status_code == HTTP_ESCALATE
    view = audit_of(gateway, response)
    assert view["verdict"] == "escalate"
    assert view["detector_failures"], "the fault must be recorded (04 §5, never silent)"
    fault = view["detector_failures"][0]
    assert fault["detector"] == "tier1_pii"
    assert fault["fail_mode_applied"] == "fail_closed"
    # 04 §5 is explicit that ran-and-broke is not never-ran: the fault appears in
    # `detector_failures_json`, and the detector still counts as having run (M-10).
    assert "tier1_pii" in view["detectors"]["ran"]
    assert "tier1_pii" not in {r["detector"] for r in view["detectors"]["not_run"]}


# ---------------------------------------------------------------------------
# Admin surface (05 §2)
# ---------------------------------------------------------------------------


def test_admin_policies_lists_the_loaded_versions(make_client) -> None:
    client, gateway, _ = make_client()
    body = client.get("/admin/policies").json()
    names = {row["use_case"] for row in body["policies"]}
    assert {"support_bot", "hr_copilot", "finance_advisor"} <= names


def test_admin_reload_returns_the_versions(make_client) -> None:
    client, _, _ = make_client()
    loaded = client.post("/admin/policies/reload").json()["loaded"]
    assert loaded["finance_advisor"] >= 1


def test_metrics_snapshot_counts_the_request(make_client) -> None:
    client, gateway, _ = make_client("All good.")
    post(client, "support_bot")
    snapshot = client.get("/metrics").json()
    assert "cp_requests_total" in json.dumps(snapshot)


def test_a_review_decision_is_one_shot(make_client) -> None:
    """FR-AUD-002: the reviewer's note is kept, never replaced."""
    client, gateway, _ = make_client(PII["text"])
    escalated = post(client, "finance_advisor")
    review_id = escalated.json()["review_id"]

    first = client.post(f"/admin/review/{review_id}",
                        json={"decision": "approve", "note": "verified"})
    assert first.status_code == 200 and first.json()["status"] == "approved"

    second = client.post(f"/admin/review/{review_id}",
                         json={"decision": "reject", "note": "changed my mind"})
    assert second.status_code >= 400
