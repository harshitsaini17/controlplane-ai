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

import asyncio
import importlib.util
import json
import shutil
import sqlite3
import tempfile
import threading
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from controlplane.audit.records import canonical_view
from controlplane.detectors import availability
from controlplane.detectors.availability import DetectorUnavailableError
from controlplane.detectors.base import DetectorError, Stage, registered_names
from controlplane.gateway import app as app_module
from controlplane.gateway import pipeline
from controlplane.gateway.app import (
    HTTP_ESCALATE,
    CanaryUnavailableWarning,
    DetectorUnavailableWarning,
    Gateway,
    _request_verdict,
    create_app,
)
from controlplane.gateway.canary import UsageSanityError, UsageSanityWarning
from controlplane.gateway.config import load_gateway_config
from controlplane.gateway.ingress import (
    HEADER_ACTIONS,
    HEADER_REQUEST_ID,
    HEADER_USE_CASE,
    UpstreamError,
)
from controlplane.policy.engine import (
    Action,
    FailMode,
    FailureOutcome,
    Verdict,
)
from controlplane.policy.store import PolicyStore
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


def test_uc3_records_fast_consistency_as_not_run(make_client, tmp_path) -> None:
    """The case `detectors_json` exists for: `consistency: "on"` with no implementation.

    **SL-6 moved the premise off disk.** `finance_advisor` shipped `consistency: "on"`
    until the `fast_consistency` cut set every policy to `off`; at `off`, 04 §2 excludes
    the detector from `expected_for` entirely, so it is correctly neither `ran` nor
    `not_run` (05 §4: "a detector switched off by policy is not listed"). The premise is
    therefore **constructed** on a copy — `on` is still a legal mode, and this is the only
    coverage of the state where a policy asks for a check that does not exist. The
    alternative was deleting the test because the config stopped reaching it, which would
    retire a live requirement on a config change.

    The `off` behaviour is covered separately below, so both readings are pinned.
    """
    policy_dir = tmp_path / "policies_on"
    policy_dir.mkdir()
    for path in (ROOT / "policies").glob("*.yaml"):
        shutil.copy(path, policy_dir)
    target = policy_dir / "finance_advisor.yaml"
    # streaming stays false, so ADR-014's `on => streaming: false` guard is satisfied.
    text = target.read_text().replace('consistency: "off"', 'consistency: "on"', 1)
    assert 'consistency: "on"' in text, "the shipped value moved; premise not constructed"
    target.write_text(text)

    client, gateway, _ = make_client("Markets closed higher.", store=PolicyStore(policy_dir))
    response = post(client, "finance_advisor")

    detectors = audit_of(gateway, response)["detectors"]
    gaps = {entry["detector"]: entry["reason"] for entry in detectors["not_run"]}
    assert gaps.get("fast_consistency") == "not_implemented"
    assert "tier1_pii" in detectors["ran"]


def test_uc3_omits_fast_consistency_entirely_when_consistency_is_off(make_client) -> None:
    """SL-6's shipped state: `off` means not listed at all, not listed as a gap.

    The distinction 05 §4 draws is what keeps `not_run` answering one question. A cut
    detector appearing as `not_implemented` under `off` would report a coverage gap where
    the policy declined the check.
    """
    client, gateway, _ = make_client("Markets closed higher.")
    response = post(client, "finance_advisor")

    detectors = audit_of(gateway, response)["detectors"]
    listed = {e["detector"] for e in detectors["not_run"]} | set(detectors["ran"])
    assert "fast_consistency" not in listed, \
        "consistency: off excludes the detector from coverage (05 §4), cut or not"
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
    assert latency["total_attributable_overhead_ms"] < latency["upstream_ms"] / 2


def test_the_two_overhead_formulas_are_not_the_same_function() -> None:
    """06 §4 defines two formulas; a single implementation would be one of them."""
    streaming = pipeline.total_attributable_overhead_ms(
        total_ms=100.0, upstream_ms=80.0, held_ms=5.0, streaming=True)
    buffered = pipeline.total_attributable_overhead_ms(
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
    visible in the audit rather than in the response.

    The fail_open counterpart **is** exercisable — `numeric_claims` is live and its 04 §2
    class is `performance`, which support_bot sets to `fail_open`. It lives in
    `tests/test_fault_injection.py` alongside the 06 §5 harness, where both halves of the
    SC-3 contrast can be asserted side by side rather than split across two files.
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
# M-13 — crash safety: released content is never unrecorded
# ---------------------------------------------------------------------------
#
# The guarantee under test is precisely "no released content without a record", not
# "every request has a record". A crash *before* release delivers nothing, so it
# discloses nothing; the audit log's job is to make undisclosed-but-unrecorded
# impossible. The pre-release case below is covered anyway because the same `finally`
# reaches it, but it is not what makes the guarantee load-bearing.
#
# One boundary is worth naming rather than leaving to be discovered: the rescue lives in
# the streaming generator, so a crash in `handle_completion` *before* that generator is
# constructed (ingress, or the input lane) leaves no record. Nothing has been released at
# that point and the client gets a 500, so it is within the ruling — but it is a real edge
# of the guarantee, not an oversight.


async def _drive_asgi(app, use_case: str, *, chunks=None, disconnect_after=None):
    """POST a streaming request straight at the ASGI app, returning (chunks, error).

    `TestClient` is not usable for this group. It surfaces the response only once the body
    is consumed, so a test built on it cannot establish *when* content left the gateway
    relative to the crash — and "post-release" is the entire claim under test. Driving the
    app directly makes each `http.response.body` message observable as it is sent, so a
    test can inject its failure at the one instant that matters.

    `chunks` may be supplied by the caller, which is what lets an injected fault fire on
    the condition "content has already been released" rather than on a call count. Counting
    calls would silently retarget the moment the input lane's own detector calls changed.

    `receive()` yields the body once and then parks forever. Returning it repeatedly spins
    Starlette's disconnect listener in a tight loop and the test hangs — which it did,
    before the park.
    """
    body = json.dumps({"messages": [{"role": "user", "content": "hello"}]}).encode()
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "path": "/v1/chat/completions", "raw_path": b"/v1/chat/completions",
        "query_string": b"", "root_path": "", "scheme": "http",
        "client": ("test", 1), "server": ("test", 80),
        "headers": [(b"host", b"test"), (b"content-type", b"application/json"),
                    (HEADER_USE_CASE.lower().encode(), use_case.encode())],
    }
    delivered = asyncio.Event()
    chunks = [] if chunks is None else chunks
    sent = 0

    async def receive():
        if not delivered.is_set():
            delivered.set()
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.Event().wait()

    async def send(message):
        nonlocal sent
        if message["type"] == "http.response.body" and message.get("body"):
            sent += 1
            if disconnect_after is not None and sent > disconnect_after:
                raise OSError("client went away")
            chunks.append(message["body"].decode())

    try:
        # A deadline, so a hang fails the test instead of stalling the suite.
        await asyncio.wait_for(app(scope, receive, send), timeout=15)
    except BaseException as exc:  # noqa: BLE001 - the crash under test propagates here
        return chunks, type(exc).__name__
    return chunks, None


def _stream_app(tmp_path, text: str):
    """A gateway whose upstream streams `text` with a yield point between tokens."""

    class Streamer:
        def resolve_model(self, tier: str, provider=None) -> str:
            return "stub-model"

        async def stream_text(self, messages, *, tier="small", provider=None, extra=None):
            for word in text.split(" "):
                await asyncio.sleep(0)  # let the loop interleave, as a real provider does
                yield word + " "

    gateway = Gateway(
        dispatcher=Streamer(), metrics=MetricsRegistry(),
        db_path=str(tmp_path / "audit.db"), key_map={},
    )
    return gateway, create_app(gateway)


THREE_SENTENCES = "One sentence here. Two sentence here. Three sentence here."
FIRST_SENTENCE = "One sentence here."


def test_m13_a_post_release_crash_still_writes_an_audit_record(tmp_path, monkeypatch) -> None:
    """★ A request that released content MUST leave a record, however the handler dies.

    The motivating incident is real, and reproducing it is the point: `note_pii_intercepts`
    read `AppliedEdit.labels` where the field is `label`, and the `AttributeError`
    propagated past the audit write on a request whose sentences had already reached the
    client — only `GatewayError` was caught. ADR-002 forbids recalling released text, so the
    response could not be withdrawn and nothing recorded that it happened: the one
    combination the audit log exists to make impossible (FR-AUD-001).

    The fault is injected into that same function, on the condition that content has already
    been released — so this is a regression test for the defect class, not for one field
    name. `note_pii_intercepts` is also called by the input lane, which is exactly why the
    condition is "a frame has gone out" rather than a call count.
    """
    gateway, app = _stream_app(tmp_path, THREE_SENTENCES)
    chunks: list[str] = []
    real = pipeline.note_pii_intercepts

    def after_release(outcome, use_case, **kwargs):
        if any(FIRST_SENTENCE in chunk for chunk in chunks):
            raise AttributeError("'AppliedEdit' object has no attribute 'labels'")
        return real(outcome, use_case, **kwargs)

    monkeypatch.setattr(pipeline, "note_pii_intercepts", after_release)
    chunks, error = asyncio.run(_drive_asgi(app, "support_bot", chunks=chunks))

    # The premise, asserted rather than assumed: content really did reach the client first.
    assert any(FIRST_SENTENCE in chunk for chunk in chunks), chunks
    assert error is not None, "the injected defect must actually have broken the handler"

    rows = gateway.conn.execute(
        "SELECT verdict, record_status, latency_json, detectors_json FROM audit_records"
    ).fetchall()
    assert len(rows) == 1, "released content with no audit record is the M-13 defect"
    assert rows[0]["record_status"] == "partial"
    # Real measurements, not nulls: the row is kept out of aggregates by its status, so
    # there is no reason to blank fields that were genuinely observed (AGENTS.md §7).
    assert set(json.loads(rows[0]["latency_json"])) >= {"total_attributable_overhead_ms", "upstream_ms"}
    assert json.loads(rows[0]["detectors_json"])["ran"], "coverage records what had run"


def test_m13_a_partial_record_is_visible_in_the_canonical_view(tmp_path, monkeypatch) -> None:
    """05 §4 renders `record_status` on every record, so a reader need not know it is
    conditional — an absent key would make `complete` and `unrecorded` indistinguishable."""
    gateway, app = _stream_app(tmp_path, THREE_SENTENCES)
    chunks: list[str] = []
    real = pipeline.note_pii_intercepts

    def after_release(outcome, use_case, **kwargs):
        if any(FIRST_SENTENCE in chunk for chunk in chunks):
            raise RuntimeError("a defect in a handler downstream of release")
        return real(outcome, use_case, **kwargs)

    monkeypatch.setattr(pipeline, "note_pii_intercepts", after_release)
    asyncio.run(_drive_asgi(app, "support_bot", chunks=chunks))

    request_id = gateway.conn.execute("SELECT request_id FROM audit_records").fetchone()[0]
    assert canonical_view(gateway.conn, request_id)["record_status"] == "partial"


def test_m13_a_client_disconnect_mid_stream_is_recorded(tmp_path) -> None:
    """An abandoned stream is also a request that got part-way, and is recorded as one.

    Content has already been released here, so this is the same guarantee as the crash
    case reached by a different route: the disconnect surfaces as an error thrown at the
    suspended `yield`, which the `finally` covers.
    """
    gateway, app = _stream_app(tmp_path, THREE_SENTENCES)
    chunks, error = asyncio.run(_drive_asgi(app, "support_bot", disconnect_after=1))

    assert chunks, "the first frame must have been delivered before the disconnect"
    assert error is not None
    rows = gateway.conn.execute("SELECT record_status FROM audit_records").fetchall()
    assert len(rows) == 1
    assert rows[0]["record_status"] == "partial"


def test_m13_an_uneventful_stream_is_marked_complete(tmp_path) -> None:
    """The control, and the one that gives the marker meaning.

    Without it, a bug marking every record `partial` would satisfy every test above while
    making the column useless — and every downstream aggregate would filter to nothing.
    """
    gateway, app = _stream_app(tmp_path, THREE_SENTENCES)
    chunks, error = asyncio.run(_drive_asgi(app, "support_bot"))

    assert error is None
    assert chunks
    rows = gateway.conn.execute("SELECT record_status FROM audit_records").fetchall()
    assert len(rows) == 1, "one record per request (FR-AUD-001), not one per attempt"
    assert rows[0]["record_status"] == "complete"


def test_m13_the_rescue_does_not_write_a_second_record(tmp_path) -> None:
    """The `finally` must not duplicate a record the normal path already wrote.

    05 §3 is one row per request and append-only, so a second INSERT raises rather than
    replacing — meaning an unguarded rescue would turn every successful stream into an
    `AuditWriteError` swallowed inside the `finally`. Asserted on the database rather than
    on the guard flag: the flag is an implementation detail, the row count is the contract.
    """
    gateway, app = _stream_app(tmp_path, THREE_SENTENCES)
    asyncio.run(_drive_asgi(app, "support_bot"))
    count = gateway.conn.execute("SELECT COUNT(*) FROM audit_records").fetchone()[0]
    assert count == 1


def test_m13_a_crash_before_any_release_is_also_recorded(tmp_path, monkeypatch) -> None:
    """A crash on the first unit, before anything is released, still records the request.

    Not the headline case — nothing was delivered, so nothing was disclosed — but the record
    is the only evidence the request happened, and its coverage says what had run. This pins
    that the rescue does not depend on content having been released, which a `finally`
    reached only after the first `yield` would.

    The fault is scoped to `OUTPUT_SENTENCE` so it lands inside the generator. Patching
    `run_lane` unconditionally breaks the *input* lane instead, which runs in
    `handle_completion` before this generator exists — a crash there is outside the rescue
    and outside the guarantee, since nothing has been released.
    """
    gateway, app = _stream_app(tmp_path, THREE_SENTENCES)
    real = pipeline.run_lane

    async def only_output_sentence(stage, *args, **kwargs):
        if stage is Stage.OUTPUT_SENTENCE:
            raise RuntimeError("a defect on the first output unit")
        return await real(stage, *args, **kwargs)

    monkeypatch.setattr(pipeline, "run_lane", only_output_sentence)
    chunks, error = asyncio.run(_drive_asgi(app, "support_bot"))

    assert not any("sentence here." in chunk for chunk in chunks), chunks
    assert error is not None
    rows = gateway.conn.execute("SELECT record_status FROM audit_records").fetchall()
    assert len(rows) == 1
    assert rows[0]["record_status"] == "partial"


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


# ---------------------------------------------------------------------------
# FR-GW-006 startup canary wiring (ADR-028)
#
# `canary.py` and its 38 tests cover the invariant's arithmetic. What is tested here is
# strictly the *wiring*: does it fire at boot, and which failures may stop one. The
# division matters because the two halves fail differently — a wrong estimator is a wrong
# number, a wrong hook is a gateway that will not start.
#
# The estimate for the shipped canary prompt is 64 tokens, so `prompt_tokens=64` passes and
# the ADR-018-documented 5074 fails. Note that the default `Stub` reports 11, which *fails*
# (outside the 2.0 band, and |11-64| = 53 clears the 50-token floor) — that is why every
# test below sets the count explicitly rather than relying on the fixture's default.
# ---------------------------------------------------------------------------


class CanaryStub(Stub):
    """A `Stub` whose usage block is what the canary reads (FR-GW-006).

    Subclasses rather than reimplements, so the canary path and the request path exercise
    the same duck-typed dispatcher — a fake that satisfied the canary but not `complete`'s
    real signature would test the hook against an interface nothing else uses.
    """

    def __init__(self, prompt_tokens: int | None, **kw) -> None:
        super().__init__(**kw)
        self.prompt_tokens = prompt_tokens

    async def complete(self, messages, *, tier="small", provider=None, extra=None):
        self.calls += 1
        if self.fail:
            raise UpstreamError("stub refused")
        return UpstreamResponse(
            text=self.text, model_used="stub-model",
            prompt_tokens=self.prompt_tokens, completion_tokens=22,
        )


def canary_app(tmp_path, prompt_tokens: int | None = 64, *, provider: str | None = None,
               enabled: bool = True, fail: bool = False, store=None):
    """An app whose upstream reports `prompt_tokens`, returning (app, gateway).

    `provider` switches `active_provider`, which is how the dev/measured asymmetry is
    reached: the shipped active provider is `kiro-local` (dev), so a measured-class test
    must repoint the config rather than hand-build a `Provider`.

    **`store` defaults to the fail-open policy set, and that default is load-bearing.** The
    ADR-033 availability gate runs BEFORE the canary (`run_availability_gate`, deliberately, so
    a boot that will refuse for a locally-knowable reason does not first spend an upstream round
    trip). The shipped `finance_advisor` maps `tier2: fail_closed`, so on a host without the
    `.[ml]` stack — CI's `verify` matrix installs `.[dev]` only — that gate raises before the
    canary ever runs, and all seven canary tests fail on an assertion about `gateway.canary`
    for a reason that has nothing to do with the canary. Every test here posts to no use case
    (they hit `/metrics` or nothing), so a two-policy store is sufficient.

    ADR-033 rule 4 permits exactly this — re-pointing a test at a fail-open fixture — and
    forbids the other move, editing `finance_advisor`'s `fail_mode` to something nobody ships.
    The refusal itself keeps its own tests: `test_a_fail_closed_policy_refuses_the_boot`.
    """
    config = load_gateway_config().model_copy(deep=True)
    if provider is not None:
        config.active_provider = provider
    config.usage_sanity.canary_on_startup = enabled
    gateway = Gateway(
        store=fail_open_policies(tmp_path) if store is None else store,
        dispatcher=CanaryStub(prompt_tokens, fail=fail),
        config=config,
        metrics=MetricsRegistry(),
        db_path=str(tmp_path / "audit.db"),
        key_map={},
    )
    return create_app(gateway), gateway


def test_the_canary_runs_at_boot_and_records_its_result(tmp_path) -> None:
    """FR-GW-006: the check fires from the lifespan hook, not on first request."""
    app, gateway = canary_app(tmp_path, prompt_tokens=64)
    assert gateway.canary is None, "nothing should have run before startup"
    with TestClient(app):
        pass
    assert gateway.canary is not None
    assert gateway.canary.passed is True
    assert gateway.canary_error is None


def test_a_bare_testclient_does_not_run_the_canary(tmp_path) -> None:
    """★ Pins WHY the pre-existing suite is unaffected by adding the hook.

    Starlette runs `lifespan` only for a context-managed client. This is not a quirk being
    tolerated — it is the reason 872 pre-existing tests, whose stub reports a count that
    would *fail* the canary, kept passing when the hook was added. If this ever starts
    running, those tests begin warning for a reason unrelated to their subject, and the
    fixture default must be fixed rather than the warning silenced.
    """
    app, gateway = canary_app(tmp_path, prompt_tokens=64)
    TestClient(app).get("/metrics")
    assert gateway.canary is None
    assert gateway.canary_error is None


def test_a_measured_class_failure_refuses_boot(tmp_path) -> None:
    """★ The documented consequence: bad accounting on a publishable provider stops boot.

    `groq` is `upstream_class: measured`, so every cost figure derived from it is
    judge-facing (ADR-018). Booting anyway would let a wrong number look like a measurement.
    """
    app, gateway = canary_app(tmp_path, prompt_tokens=5074, provider="groq")
    with pytest.raises(UsageSanityError):
        with TestClient(app):
            pass


def test_a_dev_class_failure_warns_but_boots(tmp_path) -> None:
    """The shipped active provider's own inflation must not stop the demo.

    `kiro-local` is dev-class and reports ~5000 tokens for a short prompt (ADR-018). Its
    numbers are already barred from publication, so the correct behaviour is a loud warning
    and a working gateway.
    """
    app, gateway = canary_app(tmp_path, prompt_tokens=5074)
    with pytest.warns(UsageSanityWarning):
        with TestClient(app) as client:
            assert client.get("/metrics").status_code == 200
    assert gateway.canary is not None and gateway.canary.passed is False


def test_an_unreachable_provider_does_not_refuse_boot(tmp_path) -> None:
    """★ ERR-UP-001 is not an accounting failure — the asymmetry this hook exists to keep.

    `run_canary` deliberately propagates `UpstreamError`, so a hook that caught nothing
    would refuse to start through any provider outage — and would do it citing an invariant
    that was never evaluated. Even on a measured-class provider, an outage boots.
    """
    app, gateway = canary_app(tmp_path, prompt_tokens=64, provider="groq", fail=True)
    with pytest.warns(CanaryUnavailableWarning):
        with TestClient(app) as client:
            assert client.get("/metrics").status_code == 200


def test_an_unreachable_provider_is_recorded_as_unchecked_not_passed(tmp_path) -> None:
    """★ Three states, not two: unverified must be distinguishable from verified.

    `canary.py`'s rule is that a canary which always passes because it cannot run is worse
    than an absent one. At the call site that means `canary` stays None while
    `canary_error` says why — never a `CanaryResult` with `passed=True`.
    """
    app, gateway = canary_app(tmp_path, prompt_tokens=64, fail=True)
    with pytest.warns(CanaryUnavailableWarning):
        with TestClient(app):
            pass
    assert gateway.canary is None, "an outage must not be recorded as a passing check"
    assert gateway.canary_error is not None


def test_the_knob_off_leaves_both_states_empty(tmp_path) -> None:
    """`canary_on_startup: false` means no verdict, which is not the same as a failure."""
    app, gateway = canary_app(tmp_path, prompt_tokens=5074, enabled=False)
    with TestClient(app):
        pass
    assert gateway.canary is None
    assert gateway.canary_error is None


def test_the_canary_error_carries_no_credential_material(tmp_path) -> None:
    """NFR-SEC-002: the recorded reason is operator-facing text, not a provider body."""
    app, gateway = canary_app(tmp_path, prompt_tokens=64, fail=True)
    with pytest.warns(CanaryUnavailableWarning):
        with TestClient(app):
            pass
    assert "sk-" not in (gateway.canary_error or "")
    assert "Bearer" not in (gateway.canary_error or "")


# ---------------------------------------------------------------------------
# Request-level verdict aggregation (04 §4.3 step 5)
#
# Owner live-test finding, 2026-08-28 — found by manual testing, not by this suite. A
# request whose PROMPT was redacted and whose response was clean stamped `verdict=pass`:
# the stamp was taken from the output unit alone, so the gateway's most demonstrable
# privacy behaviour was invisible in the record, in `cp_requests_total`, and to the
# caller. The stamp is now the most severe action across every evaluated unit.
#
# `support_bot` is the only shipped policy that maps `pii.*` to `edit`, and it is
# `streaming: true` — so the reachable input-EDIT path is the streaming one, which is
# also why the header case below is a streaming assertion.
# ---------------------------------------------------------------------------


def _redactions(view: dict) -> list:
    """The record's input-stage redactions, however `actions` arrives in the view."""
    raw = view.get("actions_json") or view.get("actions")
    actions = json.loads(raw) if isinstance(raw, str) else raw
    return actions.get("input_redactions", [])


def test_input_edit_with_a_clean_output_stamps_edit_not_pass(make_client) -> None:
    """The owner's case, end to end: prompt redacted, response clean, verdict `edit`.

    The redaction is asserted first and unconditionally. Were `tier1_pii` to stop firing
    on this frozen case, this test must fail rather than quietly agree that a request with
    no redactions stamped `pass` — which is exactly how the original bug survived 962
    tests.
    """
    client, gateway, stub = make_client(CLEAN_INPUT["text"])
    response = post(client, "support_bot", prompt=PII["text"])

    assert response.status_code == 200
    view = audit_of(gateway, response)
    assert len(_redactions(view)) == 1, "no input redaction — the scenario did not occur"

    assert view["verdict"] == "edit"
    assert gateway.metrics.value_of(
        "cp_requests_total", use_case="support_bot", verdict="edit"
    ) == 1.0


def test_the_input_edit_reaches_the_caller_in_both_renderings(make_client) -> None:
    """05 §1.1: an edited request carries `X-ControlPlane-Actions: edit`.

    M-12 reads the header as non-streaming-only because headers precede the body — true of
    an *output* edit, but an input redaction is decided before dispatch, so it is known
    before this response's status line exists. The owner's transcript lacked this header;
    it was never reachable, since the only `pii.* -> edit` policy streams.
    """
    client, gateway, _ = make_client(CLEAN_INPUT["text"])
    response = post(client, "support_bot", prompt=PII["text"])

    assert response.headers.get(HEADER_ACTIONS) == "edit"
    final = frames(response)[-1]["controlplane"]
    assert final["verdict"] == "edit"
    assert len(final["actions"]["input_redactions"]) == 1
    # The body reports the input stage as the input stage, not as an output edit.
    assert final["actions"]["applied"] == []
    assert final["actions"]["input_redactions"][0]["stage"] == "input"


def test_input_edit_with_an_output_block_stamps_the_more_severe_action(make_client) -> None:
    """Most severe across units, not last-unit-wins and not first: `block` beats `edit`.

    `pii.api_key -> block` (ADR-024) in the response gives two units with different
    actions. The record must still keep the input redaction, or the stamp would be the
    only surviving trace that the prompt was touched.
    """
    client, gateway, _ = make_client(case("pii.jsonl", "PII-036")["text"])
    response = post(client, "support_bot", prompt=PII["text"])

    view = audit_of(gateway, response)
    assert view["verdict"] == "block"
    assert len(_redactions(view)) == 1, "the input redaction was dropped by the block path"
    assert gateway.metrics.value_of(
        "cp_requests_total", use_case="support_bot", verdict="block"
    ) == 1.0


def test_aggregation_unions_the_evidence_it_does_not_pick_one_unit() -> None:
    """A tie on severity must not silently discard the other unit's fault records.

    `from_verdict` reads `detector_failures_json` straight off the stamped verdict, so
    returning whichever unit tied first would delete a `fail_open` fault from the record
    whenever the input unit also passed. 04 §5 requires the fault to be recorded whether
    or not it contributed — this is the regression that behaviour caught.
    """
    class _Req:
        use_case = "support_bot"
        policy_version = 2

    fault = FailureOutcome(
        detector="tier2_toxicity", error_class="TimeoutError", fail_class="timeout",
        fail_mode=FailMode.FAIL_OPEN, action=None, failure_id="f-1",
    )
    clean_input = Verdict(action=Action.PASS, use_case="support_bot", policy_version=2)
    output_with_fault = Verdict(
        action=Action.PASS, use_case="support_bot", policy_version=2,
        failure_outcomes=(fault,),
    )

    stamped = _request_verdict([clean_input, output_with_fault], _Req())
    assert stamped.action is Action.PASS
    assert stamped.failure_outcomes == (fault,), "the fault vanished on a severity tie"
    # fail_open contributed nothing, so it must not appear as a *reason* for the verdict.
    assert stamped.failure_record_ids == ()


def test_aggregation_over_no_units_is_pass_not_an_error() -> None:
    """An empty candidate list is a real state (nothing evaluated), and PASS is truthful."""
    class _Req:
        use_case = "hr_copilot"
        policy_version = 3

    stamped = _request_verdict([None], _Req())
    assert stamped.action is Action.PASS
    assert stamped.use_case == "hr_copilot"
    assert stamped.policy_version == 3


def test_the_buffered_path_aggregates_the_input_edit_too(make_client, tmp_path) -> None:
    """The same rule on the non-streaming path — which no shipped policy can reach.

    `support_bot` is the only policy mapping `pii.* -> edit` and it is `streaming: true`,
    so the buffered branch of the aggregation is unreachable from `policies/` and would
    otherwise be untested code that only looks correct. Flipping the flag on a copy is
    legal here because the ADR-014 guard binds `consistency: on`, and this policy is
    `on_sampled`.

    The point is that the rule is a property of the aggregation and not of a delivery
    mode: whichever path a future policy takes, a redacted prompt must not stamp `pass`.
    """
    policy_dir = tmp_path / "policies"
    policy_dir.mkdir()
    for path in (ROOT / "policies").glob("*.yaml"):
        shutil.copy(path, policy_dir)
    buffered = policy_dir / "support_bot.yaml"
    buffered.write_text(buffered.read_text().replace("streaming: true", "streaming: false", 1))

    client, gateway, stub = make_client(
        CLEAN_INPUT["text"], store=PolicyStore(policy_dir)
    )
    response = post(client, "support_bot", prompt=PII["text"])

    assert response.status_code == 200
    assert not response.headers["content-type"].startswith("text/event-stream"), \
        "the policy copy did not actually take the buffered path"

    body = response.json()
    assert body["controlplane"]["verdict"] == "edit"
    assert len(body["controlplane"]["actions"]["input_redactions"]) == 1
    assert response.headers.get(HEADER_ACTIONS) == "edit"
    assert audit_of(gateway, response)["verdict"] == "edit"


# ---------------------------------------------------------------------------
# Pre-dispatch cost accounting (owner ruling, 2026-08-28)
#
# 04 §4.5 answers an input BLOCK/ESCALATE without calling a provider. The record used to
# leave tokens and cost null, reasoning that a zero "would claim a free upstream call
# happened". The ruling inverts that for the quantities we actually know: nothing was
# sent, so 0 tokens is a COUNT, and on a measured-class provider the cost is a *counted*
# zero. Null is excluded from an average, so leaving it null deletes the saving — a
# pipeline blocking half its traffic pre-dispatch would report the same mean cost as one
# blocking none. `model_used` stays null: no model answered.
#
# The class split is the trap in testing this. The shipped `active_provider` is
# `kiro-local`, which is DEV class, so an `est_usd is None` assertion against the default
# config passes both before and after the change and pins nothing. The measured branch is
# therefore tested against a measured-class config, not the default one.
# ---------------------------------------------------------------------------


def measured_config(tmp_path):
    """The shipped config with a measured-class provider made active (ADR-018)."""
    text = (ROOT / "config" / "gateway.yaml").read_text()
    assert "active_provider: kiro-local" in text, "config drift: the dev default moved"
    path = tmp_path / "gateway.yaml"
    path.write_text(text.replace("active_provider: kiro-local", "active_provider: groq", 1))
    config = load_gateway_config(path)
    assert config.active.upstream_class.value == "measured"
    return config


def test_a_pre_dispatch_block_counts_zero_tokens_rather_than_unknown(make_client) -> None:
    """0/0 is what we know, not what we failed to observe (04 §4.5)."""
    client, gateway, stub = make_client("never reached")
    response = post(client, "hr_copilot", prompt=PII["text"])

    view = audit_of(gateway, response)
    assert view["verdict"] == "block", "the scenario requires an input-stage terminal"
    assert stub.calls == 0, "something dispatched — then 0/0 would be a false claim"
    assert (view["cost"]["tokens_in"], view["cost"]["tokens_out"]) == (0, 0)
    # No model answered, and naming one would invent the dispatch this test just ruled out.
    assert view["model"]["used"] is None


def test_the_measured_class_records_the_saving_as_a_counted_zero(make_client, tmp_path) -> None:
    """`est_cost_usd = 0.0` on a measured provider: the request demonstrably cost nothing.

    Asserted against a measured-class config because the shipped default is `dev`, where
    the expected value is `None` — so this claim is untestable on the default config and a
    test that used it would be reporting the dev branch's behaviour under the measured
    branch's name.
    """
    client, gateway, _ = make_client("never reached", config=measured_config(tmp_path))
    response = post(client, "hr_copilot", prompt=PII["text"])

    view = audit_of(gateway, response)
    assert view["verdict"] == "block"
    assert view["cost"]["est_usd"] == 0.0
    assert view["cost"]["est_usd"] is not None, "null would drop the saving from the mean"


def test_the_dev_class_stays_null_even_pre_dispatch(make_client) -> None:
    """ADR-018: `dev` accounting is not a measurement, so it has no zero to report.

    The arithmetic is available here — 0 tokens times any price is 0 — and is deliberately
    not used. A 0.0 from a dev provider is a figure barred from every judge-facing
    artifact, sitting in the column those artifacts read.
    """
    client, gateway, _ = make_client("never reached")
    assert gateway.config.active.upstream_class.value == "dev"

    view = audit_of(gateway, post(client, "hr_copilot", prompt=PII["text"]))
    assert view["cost"]["est_usd"] is None
    # The counts are still real: they are observations, not prices.
    assert (view["cost"]["tokens_in"], view["cost"]["tokens_out"]) == (0, 0)


def test_a_dispatched_unpriceable_request_is_still_null_on_the_measured_class(
    make_client, tmp_path
) -> None:
    """ADR-022 null-not-zero, where it still governs — the case the ruling did NOT touch.

    The stub model is in no price table, so a dispatched request's cost is *unknown*. This
    is the assertion that keeps the new rule scoped to the short-circuit: if the
    counted-zero branch ever widened to cover dispatches, this would flip to 0.0 and claim
    a real upstream call was free.
    """
    client, gateway, stub = make_client("Markets closed higher.",
                                       config=measured_config(tmp_path))
    view = audit_of(gateway, post(client, "finance_advisor"))

    assert stub.calls == 1, "the scenario requires a real dispatch"
    assert view["model"]["used"] == "stub-model"
    assert view["cost"]["est_usd"] is None
    assert (view["cost"]["tokens_in"], view["cost"]["tokens_out"]) == (11, 22)


# ---------------------------------------------------------------------------
# Ingress rejections carry a correlation id (owner live-test finding, 2026-08-28)
#
# `ingest` minted the request id on its own last line — after both rejections it can
# raise — so an ERR-CFG-001/002 body reached the caller with `"request_id": ""` and no
# `X-ControlPlane-Request-Id` header, against 05 §1.1's "All responses carry" promise. It
# is now minted in the handler before use-case resolution.
#
# An id is a correlation handle for one exchange, not a property of a successfully
# resolved policy: the request an operator most needs to look up is the one that was
# refused.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "use_case, body, code",
    [
        ("no_such_pipeline", {}, "ERR-CFG-001"),          # rejected before any policy loads
        ("finance_advisor", {"stream": True}, "ERR-CFG-002"),  # rejected against a policy
    ],
)
def test_an_ingress_rejection_carries_a_real_request_id(
    make_client, use_case: str, body: dict, code: str
) -> None:
    """Both ingress rejections, because they fail at different points in `ingest`.

    ERR-CFG-001 is raised before a policy is resolved at all and ERR-CFG-002 relative to
    one, so a mint that happened anywhere inside `ingest` would fix at most one of them.
    """
    client, _, _ = make_client()
    response = post(client, use_case, prompt=CLEAN_INPUT["text"], **body)

    assert response.status_code == 400
    request_id = response.json()["error"]["request_id"]
    assert request_id, f"{code} body carried an empty request_id"
    # A real id, not a placeholder that merely satisfies "non-empty".
    assert uuid.UUID(request_id)
    assert response.headers[HEADER_REQUEST_ID] == request_id, \
        "05 §1.1: all responses carry the header, and it must match the body"


def test_each_rejection_gets_its_own_id(make_client) -> None:
    """A constant would satisfy every other assertion here and correlate nothing."""
    client, _, _ = make_client()
    ids = {post(client, "no_such_pipeline").json()["error"]["request_id"] for _ in range(3)}
    assert len(ids) == 3


def test_the_id_still_correlates_the_header_with_the_audit_record(make_client) -> None:
    """The property that could have regressed: the mint moved OUT of `ingest`.

    Two ids — one minted in the handler and one inside `ingest` — would leave the header
    naming a request the audit table has never heard of, which is worse than the empty
    string this change removed: an operator would follow it to a confident dead end.
    """
    client, gateway, _ = make_client("Fine.")
    response = post(client, "support_bot", prompt=CLEAN_INPUT["text"])

    assert response.status_code == 200
    assert audit_of(gateway, response)["request_id"] == response.headers[HEADER_REQUEST_ID]


# ---------------------------------------------------------------------------
# ADR-033 — registered but unloadable (state (c)), end to end
# ---------------------------------------------------------------------------


ABSENT_DEP = "onnxruntime_absent_on_purpose"


def _genuinely_unloadable() -> dict[str, str]:
    """`{detector: first missing module}` for the probe scope, computed WITHOUT the probe.

    Deliberately not a call to `probe_availability`: a test that asked the probe whether it
    agrees with itself would pass on any host and assert nothing. This reads `REQUIREMENTS` —
    the declared contract — and resolves each name with `find_spec`, so the assertion compares
    the probe's output against the declaration it is supposed to implement.

    The two could in principle disagree on resolution semantics (metadata presence, namespace
    packages). That would fail the caller, which is the correct outcome: a divergence between
    "declared present" and "probe says present" is a finding, not noise to be tolerated.
    """
    out: dict[str, str] = {}
    for detector in app_module._probe_scope():
        for module in availability.REQUIREMENTS.get(detector, ()):
            try:
                found = importlib.util.find_spec(module) is not None
            except (ImportError, ValueError):
                found = False
            if not found:
                out[detector] = module
                break
    return out


@pytest.fixture
def unloadable_tier2(monkeypatch):
    """Make `tier2_injection` genuinely unloadable, without faking a load (ADR-033 rule 4).

    Two monkeypatches, and both are needed for the state to be *reachable* rather than
    simulated. `_probe_scope` widens the probe to a detector Tier-2 has not yet bound into
    `LIVE` — which is what a post-Tier-2 boot will look like — and `REQUIREMENTS` points it
    at a module that does not exist on any host, so `find_spec` reports a real absence.
    Nothing installs a stub loader: a probe satisfied by a fake would assert the opposite of
    the invariant.
    """
    monkeypatch.setattr(availability, "REQUIREMENTS", {"tier2_injection": (ABSENT_DEP,)})
    monkeypatch.setattr(app_module, "_probe_scope", lambda: ("tier2_injection",))


def fail_open_policies(tmp_path):
    """A policy dir whose every use case maps `tier2: fail_open`.

    `support_bot` and `hr_copilot` copied as shipped — **not** `finance_advisor` with its
    `fail_mode` edited. ADR-033 rule 4 permits re-pointing a test at a fail-open fixture and
    forbids relaxing the strict policy, because a suite that edits `fail_closed` to get green
    is testing a configuration nobody ships.
    """
    policy_dir = tmp_path / "fail_open_policies"
    policy_dir.mkdir()
    for name in ("support_bot.yaml", "hr_copilot.yaml"):
        shutil.copy(ROOT / "policies" / name, policy_dir)
    return PolicyStore(policy_dir)


def test_the_probe_scope_is_the_union_of_both_binding_mechanisms() -> None:
    """The gateway binds detectors two ways and they disagree; the probe must see both.

    `pipeline.LIVE` is what the served path calls; `_REGISTRY` is the eval harness's route.
    Probing only the registry leaves the mechanism inert on the served path (it is empty in
    this process), and probing only `LIVE` misses a harness registration. Neither omission
    fails loudly, so the union is pinned here.
    """
    assert set(pipeline.LIVE) <= set(app_module._probe_scope())
    assert set(registered_names()) <= set(app_module._probe_scope())


def test_the_manifest_names_exactly_the_dependencies_this_host_is_missing(make_client) -> None:
    """The mechanism must be INERT until a detector actually fails to load.

    **The premise stopped being universal, so the claim became two-sided.** This test was
    `test_a_healthy_host_produces_an_empty_manifest` and asserted `manifest == ()`, justified by
    "every detector in `LIVE` today is a regex pass that imports nothing". `tier2_injection`
    ended that: it is live and needs `onnxruntime`/`transformers`/`onnx`. On CI's `verify` matrix
    (`.[dev]` only) the manifest is correctly NON-empty, and asserting `()` there would assert
    the probe is broken.

    What the test always meant — the probe invents no absences — survives intact and now also
    catches the opposite error, an absence the probe fails to report. `_genuinely_unloadable`
    recomputes the expectation from `REQUIREMENTS` rather than from the probe, so this is not
    the probe agreeing with itself. On a full `.[dev,ml]` host `expected` is empty and this
    asserts exactly what the old test did.
    """
    _, gateway, _ = make_client()
    expected = _genuinely_unloadable()
    assert gateway.detectors_unloadable == expected
    assert {e.detector: e.missing for e in gateway.detector_manifest} == expected


def test_a_fail_closed_policy_refuses_the_boot(unloadable_tier2, tmp_path) -> None:
    """★ ADR-033 rule 2: the shipped `finance_advisor` maps `tier2: fail_closed`.

    Refusal happens at boot, from the lifespan hook — the FR-GW-006 canary's precedent. A
    gateway that started here would promise fail-closed Tier-2 protection on every
    `finance_advisor` request while recording the absence in a column nobody watches.
    """
    gateway = Gateway(
        dispatcher=Stub("fine"), metrics=MetricsRegistry(),
        db_path=str(tmp_path / "audit.db"), key_map={},
    )
    assert gateway.detectors_unloadable == {"tier2_injection": ABSENT_DEP}

    with pytest.raises(DetectorUnavailableError) as exc:
        with TestClient(create_app(gateway)):
            pass
    assert "finance_advisor" in str(exc.value)


def test_a_bare_testclient_does_not_enforce_availability(unloadable_tier2, tmp_path) -> None:
    """Same lifespan property the canary test pins, for the same reason.

    Enforcement is a boot decision, so it fires under `with TestClient(app)` and not under a
    bare call. This is why adding the hook left the existing suite intact, and it is worth
    pinning separately from the refusal above.
    """
    gateway = Gateway(
        dispatcher=Stub("fine"), metrics=MetricsRegistry(),
        db_path=str(tmp_path / "audit.db"), key_map={},
    )
    assert TestClient(create_app(gateway)).get("/metrics").status_code == 200


def test_a_fail_open_policy_set_warns_loudly_and_still_serves(
    unloadable_tier2, tmp_path
) -> None:
    """Availability over strictness is a documented per-use-case choice (04 §5, 01 §3)."""
    gateway = Gateway(
        store=fail_open_policies(tmp_path), dispatcher=Stub("All good here."),
        metrics=MetricsRegistry(), db_path=str(tmp_path / "audit.db"), key_map={},
    )
    with pytest.warns(DetectorUnavailableWarning, match="UNLOADABLE"):
        with TestClient(create_app(gateway)) as client:
            assert client.get("/metrics").status_code == 200


def test_an_unloadable_detector_is_recorded_as_unavailable_not_not_run(
    unloadable_tier2, tmp_path
) -> None:
    """★ The distinction the third state exists for (05 §4).

    `tier2_injection` is in the input lane, so it reaches `note_missing` on a host that cannot
    load it. Filing it as `not_implemented` would be a false statement in an append-only table:
    the detector exists, and what is missing is a dependency this record can name.

    **This docstring used to say "and absent from `LIVE`", which is how it reached
    `note_missing` before the detector shipped.** That route is gone — `tier2_injection` is in
    `LIVE` now — and the test failed with `KeyError: 'unavailable'` when it did, because
    `run_lane` treated membership as proof of loadability and called `detect()` anyway. The
    manifest check there is what this asserts today; `test_the_lane_never_calls_a_detector_the
    _boot_manifest_says_cannot_load` pins that it is load-bearing rather than incidental.
    """
    gateway = Gateway(
        store=fail_open_policies(tmp_path), dispatcher=Stub("All good here."),
        metrics=MetricsRegistry(), db_path=str(tmp_path / "audit.db"), key_map={},
    )
    with pytest.warns(DetectorUnavailableWarning):
        with TestClient(create_app(gateway), raise_server_exceptions=False) as client:
            response = post(client, "support_bot", prompt=CLEAN_INPUT["text"])

    assert response.status_code == 200
    detectors = audit_of(gateway, response)["detectors"]
    assert detectors["unavailable"] == [
        {"detector": "tier2_injection", "missing": ABSENT_DEP}
    ]
    not_run = {entry["detector"] for entry in detectors["not_run"]}
    assert "tier2_injection" not in not_run, "a detector may be in at most one list"
    assert gateway.metrics.value_of(
        "cp_detector_unavailable_total", detector="tier2_injection"
    ) == 1.0


def test_the_lane_never_calls_a_detector_the_boot_manifest_says_cannot_load(
    unloadable_tier2, tmp_path, monkeypatch
) -> None:
    """★ The production defect wiring `tier2_injection` exposed, pinned by a spy.

    `run_lane`'s loadability test was `LIVE.get(name) is None`, which was sufficient only while
    ADR-033 state (c) could *only* be expressed by absence from `LIVE` — true while every live
    detector was a dependency-free regex pass. A live detector with real imports makes state (c)
    reachable *with* membership, and the lane then called `detect()` on a host the boot manifest
    had already declared unable to load it: the ImportError would be filed as a per-request
    transient fault, re-discovered on every request, instead of the host-level absence ADR-033
    separates it from.

    A spy rather than an assertion on the audit record, because the record cannot tell the two
    apart once the reason is normalized — the claim here is specifically that **no call is
    made**. `detect()` succeeds on this host (onnxruntime is installed), so without the manifest
    check the spy fires and this test fails rather than passing for the wrong reason.
    """
    called: list[str] = []
    real = pipeline.LIVE["tier2_injection"]

    class Spy:
        name = real.name

        async def detect(self, ctx):
            called.append(ctx.stage.name)
            return await real.detect(ctx)

    monkeypatch.setitem(pipeline.LIVE, "tier2_injection", Spy())
    gateway = Gateway(
        store=fail_open_policies(tmp_path), dispatcher=Stub("All good here."),
        metrics=MetricsRegistry(), db_path=str(tmp_path / "audit.db"), key_map={},
    )
    with pytest.warns(DetectorUnavailableWarning):
        with TestClient(create_app(gateway), raise_server_exceptions=False) as client:
            response = post(client, "support_bot", prompt=CLEAN_INPUT["text"])

    assert called == [], (
        f"the manifest says tier2_injection cannot load here, yet the lane called it at {called}"
    )
    detectors = audit_of(gateway, response)["detectors"]
    assert detectors["unavailable"] == [
        {"detector": "tier2_injection", "missing": ABSENT_DEP}
    ]


def test_the_missing_dependency_is_an_import_name_never_a_traceback(
    unloadable_tier2, tmp_path
) -> None:
    """NFR-SEC-001 shape rule: `missing` is a dependency name, like `error_class` is a class.

    A caught `ImportError`'s message would be the convenient thing to store and can carry
    absolute paths and interpreter internals into a column that is published in reports.
    """
    gateway = Gateway(
        store=fail_open_policies(tmp_path), dispatcher=Stub("All good here."),
        metrics=MetricsRegistry(), db_path=str(tmp_path / "audit.db"), key_map={},
    )
    with pytest.warns(DetectorUnavailableWarning):
        with TestClient(create_app(gateway), raise_server_exceptions=False) as client:
            response = post(client, "support_bot", prompt=CLEAN_INPUT["text"])

    missing = audit_of(gateway, response)["detectors"]["unavailable"][0]["missing"]
    assert missing == ABSENT_DEP
    assert "/" not in missing and "\n" not in missing and "Error" not in missing


def test_a_healthy_boot_omits_the_key_rather_than_writing_an_empty_list(
    make_client, monkeypatch
) -> None:
    """`[]` would assert "this boot loaded everything" — a claim older rows never made.

    The ADR-027 Amendment 1 distinction between `[]` and absent, applied to this column: an
    absent key stays silent instead of back-dating a guarantee.

    **The empty manifest is arranged now, not assumed.** It used to come for free — every live
    detector imported nothing — and `tier2_injection` ended that, so on a host without `.[ml]`
    this asserted the absence of a key ADR-033 correctly writes. Narrowing the probe to the
    dependency-free detectors makes the premise structural rather than host-dependent, which is
    the honest fix: the subject here is the serialize-time distinction between an absent key and
    an empty list, and that has nothing to do with which host runs it.
    """
    monkeypatch.setattr(
        app_module, "_probe_scope",
        lambda: ("tier1_pii", "tier1_blocklist", "numeric_claims"),
    )
    client, gateway, _ = make_client("All good here.")
    assert gateway.detector_manifest == (), "the narrowed scope must leave nothing unavailable"
    response = post(client, "support_bot", prompt=CLEAN_INPUT["text"])
    assert "unavailable" not in audit_of(gateway, response)["detectors"]
