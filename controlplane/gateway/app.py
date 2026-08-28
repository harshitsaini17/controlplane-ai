"""FastAPI application factory and route registration.

Implements 05 §1 (gateway API) and 05 §2 (admin API). The per-unit detector/policy work
lives in `pipeline.py`; this module owns the HTTP shapes, the two delivery paths, and the
audit write that closes every request.

**Both delivery paths reach the same verdict machinery over different units.** Streaming
checks one sentence at a time and releases as it goes (02 §4, FR-GW-002); non-streaming
buffers the whole response, checks once, and delivers atomically (ADR-014, UC-3). The
difference is the *unit*, not the policy — which is what lets the beat-4 signature moment be
a config difference rather than a code path.

**ESCALATE has two HTTP renderings, and the docs jointly fix which applies where.** 05 §1.1
specifies HTTP 202 with a `review_id`; 04 §4.4 specifies that a mid-stream escalation
terminates the stream and sends `escalate_user_notice`. Not a conflict — they describe
different delivery modes. A streaming response has already committed its status line by the
time the first sentence is checked, so 202 is physically unavailable there and 04 §4.4's
terminate-and-notify governs; non-streaming reaches its verdict before any byte is sent, so
it returns the 202. Same for `X-ControlPlane-Actions: edit` (05 §1.1): a header cannot be
added after the body has begun, so the streaming path carries the fact in its final frame's
`controlplane` block instead. Logged as M-12.

**The admin surface has no authentication, per 05 §2's own words: "localhost/demo only — no
auth in v1, stated limitation".** That is a documented decision, not an oversight here.
Anyone running this past a demo must put authentication in front of `/admin/*`: the review
queue serves quarantined model output, and `POST /admin/policies/reload` can change every
verdict the gateway will subsequently make.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
import warnings
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from controlplane.audit import review
from controlplane.audit.db import init_db
from controlplane.audit.records import (
    RECORD_STATUS_COMPLETE,
    RECORD_STATUS_PARTIAL,
    AuditRecord,
    serialize_actions,
    write_record,
)
from controlplane.detectors.base import Signal, Stage
from controlplane.gateway import pipeline
from controlplane.gateway.canary import CanaryResult, canary_on_startup
from controlplane.gateway.config import GatewayConfig, load_gateway_config
from controlplane.gateway.ingress import (
    HEADER_ACTIONS,
    HEADER_REQUEST_ID,
    GatewayError,
    UpstreamError,
    ingest,
    load_key_map,
)
from controlplane.gateway.sentence_buffer import Segmentation
from controlplane.gateway.sse_proxy import UpstreamDispatcher
from controlplane.policy.engine import Verdict, most_severe
from controlplane.policy.schema import Action
from controlplane.policy.store import PolicyStore
from controlplane.telemetry import spans
from controlplane.telemetry.metrics import REGISTRY_DEFAULT, MetricsRegistry

#: SSE sentinel closing an OpenAI-compatible stream.
DONE = "[DONE]"

#: 05 §1.1: a BLOCK is HTTP 200 whose `finish_reason` says what happened.
BLOCK_FINISH_REASON = "content_filter"

#: 05 §1.1 ESCALATE, non-streaming only (see the module docstring).
HTTP_ESCALATE = 202

#: 05 §3 `stage_summary` vocabulary.
STAGE_INPUT, STAGE_STREAMED, STAGE_COMPLETED = "input", "streamed", "completed"

#: The only tier this phase requests. The cost-plane router (ADR-013 cascade, tier
#: selection) is Phase 6, and recording a tier we did not choose would make
#: `tier_requested` fiction. "small" is what `_dispatch` actually asks for.
TIER = "small"


class CanaryUnavailableWarning(UserWarning):
    """The FR-GW-006 canary could not be evaluated this boot.

    Distinct from `UsageSanityWarning`, which means the invariant ran and FAILED on a
    dev-class provider. This one means it never ran, so the boot carries no verdict
    either way — a state the operator must be able to tell from a pass.
    """


def _sse(payload: dict[str, Any]) -> str:
    """One SSE frame. Compact separators, so a frame is byte-stable across runs."""
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _delta_frame(request_id: str, model: str, text: str) -> str:
    return _sse({
        "id": request_id, "object": "chat.completion.chunk", "model": model,
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    })


def _final_frame(
    request_id: str, model: str, reason: str, controlplane: dict[str, Any] | None = None
) -> str:
    frame: dict[str, Any] = {
        "id": request_id, "object": "chat.completion.chunk", "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": reason}],
    }
    if controlplane:
        frame["controlplane"] = controlplane
    return _sse(frame)


def _completion_body(
    request_id: str,
    model: str,
    text: str,
    *,
    finish_reason: str = "stop",
    controlplane: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """An OpenAI-shaped non-streaming body plus the 05 §1.1 gateway extensions."""
    body: dict[str, Any] = {
        "id": request_id, "object": "chat.completion", "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": finish_reason,
        }],
    }
    if controlplane:
        body["controlplane"] = controlplane
    return body


class Gateway:
    """Holds the long-lived collaborators. One instance per app.

    Built once at startup so a hot reload (FR-CFG-002) mutates the store the running app
    already holds, rather than leaving a stale copy behind a module global.
    """

    def __init__(
        self,
        *,
        store: PolicyStore | None = None,
        config: GatewayConfig | None = None,
        dispatcher: UpstreamDispatcher | None = None,
        metrics: MetricsRegistry | None = None,
        db_path: str | None = None,
        key_map: dict[str, str] | None = None,
    ) -> None:
        self.store = store or PolicyStore()
        # `versions()` is a method, not a property — calling it is what makes this an
        # emptiness check rather than a truthiness test on a bound method.
        if not self.store.versions():
            self.store.load()
        self.config = config or load_gateway_config()
        self.metrics = metrics or REGISTRY_DEFAULT
        self.dispatcher = dispatcher or UpstreamDispatcher(self.config, metrics=self.metrics)
        self.db_path = db_path
        self._local = threading.local()
        # Create the schema once, here, so a failure surfaces at startup rather than on
        # the first audited request. The connection is then discarded: `conn` hands out a
        # per-thread one, and holding this would be the very object that cannot be shared.
        init_db(db_path).close()
        # An empty key map is valid (header-only use-case resolution), so a `None` from the
        # loader is normalized once here rather than retried per request.
        self.key_map = key_map if key_map is not None else (load_key_map() or {})
        # FR-GW-006 canary state, filled by the startup hook. THREE states, not two, and the
        # third is the point: `canary` holds a result when the check actually ran,
        # `canary_error` names why it could not, and both `None` means it never ran (the
        # knob is off, or nothing started the app). A single boolean would make "verified"
        # and "never checked" the same value — the M-10 mistake in a different column.
        self.canary: CanaryResult | None = None
        self.canary_error: str | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        """A SQLite connection owned by the calling thread.

        **A `sqlite3.Connection` cannot cross threads** — the driver refuses it outright —
        and the gateway genuinely spans two: the `Gateway` is built at startup, while a
        `StreamingResponse` body runs as a task on the event-loop thread. Sharing one
        connection raised `ProgrammingError` *after* the first sentences had already been
        released, which is the worst shape for this failure: ADR-002 means the text cannot
        be recalled, so the request was delivered and its audit record was not written.
        FR-AUD-001 asks for one record per request, and a threading accident is not an
        acceptable reason to have none.

        Per-thread rather than one shared connection behind a lock, because multiple
        connections to this file are already the design: ADR-006 chose WAL mode precisely
        so the ADR-007 dashboard can read while the gateway writes, and that dashboard is
        a separate *process*. A second connection in-process is the same arrangement.

        `init_db` is idempotent by its own contract (`IF NOT EXISTS`), so a new thread
        bootstrapping is a no-op rather than a race.
        """
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = init_db(self.db_path)
            self._local.conn = conn
        return conn

    # -- audit -------------------------------------------------------------

    def audit(
        self,
        *,
        request,
        verdict: Verdict,
        stage_summary: str,
        signals: object,
        coverage: pipeline.Coverage,
        latency: dict[str, float],
        actions_json: str = "{}",
        model_used: str | None = None,
        tier_requested: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        record_status: str = RECORD_STATUS_COMPLETE,
    ) -> None:
        """Write the one record for this request (FR-AUD-001).

        `record_status` is `"partial"` only from a crash path (M-13); every ordinary write
        leaves the default. See `_stream_response` for why the default is the safe one.

        `est_cost_usd` stays `None` unless the active provider can price the model that
        actually answered — ADR-022's null-not-zero rule. A zero would read as "this was
        free" rather than "we cannot price this", and the cost plane would average it in.
        """
        est = None
        if model_used and tokens_in is not None and tokens_out is not None:
            est = self.config.active.est_cost_usd(model_used, tokens_in, tokens_out)

        record = AuditRecord.from_verdict(
            request_id=request.request_id,
            verdict=verdict,
            stage_summary=stage_summary,
            signals=signals,
            conversation_id=request.conversation_id,
            actions_json=actions_json,
            tier_requested=tier_requested,
            model_used=model_used,
            upstream_class=self.config.active.upstream_class.value,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            est_cost_usd=est,
            latency_json=json.dumps(pipeline.clamp_latency(latency)),
            detectors_json=coverage.serialize(),
            record_status=record_status,
        )
        write_record(self.conn, record)
        self.metrics.increment(
            "cp_requests_total", use_case=request.use_case, verdict=verdict.action.value
        )
        overhead = latency.get("gateway_overhead_ms")
        if overhead is not None:
            self.metrics.observe(
                "cp_gateway_overhead_ms", overhead, use_case=request.use_case
            )

    async def quarantine(self, request, text: str, review_id: str) -> str:
        """Create the review item an ESCALATE requires (FR-POL-005), returning its id.

        Async because `review.create_item` re-scans the text for Tier-1 PII before the
        INSERT — 05 §3's "masked at write time" rule, which is a detector call.

        **Must be called AFTER the audit record is written.** `review_items.request_id`
        REFERENCES `audit_records` and foreign keys are enabled (ADR-006), so quarantining
        first fails with `FOREIGN KEY constraint failed` — which it did, on every escalation
        path, until the order was fixed. `review_id` is passed in rather than minted here
        because `actions_json` names it, so the audit record needs it before it exists.
        """
        return await review.create_item(
            self.conn,
            request_id=request.request_id,
            quarantined_text=text,
            use_case=request.use_case,
            review_id=review_id,
            metrics=self.metrics,
        )


async def run_startup_canary(state: Gateway) -> None:
    """Fire the FR-GW-006 canary once at boot, recording the outcome on `state`.

    `canary_on_startup` owns the run/skip decision and the run-then-enforce ordering, so
    this adds exactly one thing: which failures may stop a boot.

    **`UsageSanityError` propagates and `UpstreamError` does not**, and the asymmetry is the
    whole substance of this function. The first is the documented consequence — a
    measured-class provider whose accounting is wrong would corrupt every judge-facing
    number, so refusing to start is the point. The second is ERR-UP-001: the provider is
    unreachable, which says nothing about how it counts. Conflating them would make the
    gateway refuse to boot through any provider outage, and would do it in the name of an
    invariant that was never evaluated.

    An unreachable provider is therefore recorded as **unchecked, not passed** —
    `canary.py`'s own rule that "a canary that always passes because it cannot run is worse
    than an absent one", applied at the call site. Anything other than those two exceptions
    is a genuine defect in the check and is left to propagate: swallowing it would hide a
    broken canary behind a clean boot log, which is the same failure in a quieter form.
    """
    try:
        state.canary = await canary_on_startup(state.dispatcher, config=state.config)
    except UpstreamError as exc:
        state.canary = None
        state.canary_error = str(exc)
        warnings.warn(
            f"usage-sanity canary could not run: {exc}. The gateway is starting anyway — "
            "an unreachable provider is ERR-UP-001, not an accounting failure (FR-GW-006) "
            "— but the invariant is UNVERIFIED for this boot, not satisfied.",
            CanaryUnavailableWarning,
            stacklevel=2,
        )


def create_app(gateway: Gateway | None = None) -> FastAPI:
    """Build the ASGI app. `gateway` is injectable so tests need no real upstream.

    The canary runs from a `lifespan` hook, which means it fires under `with TestClient(app)`
    and not under a bare `TestClient(app)` call — Starlette only runs lifespan for the
    former. That is the behaviour a test asserting boot refusal depends on, and the reason
    the existing suite is unaffected by adding it.
    """
    state = gateway or Gateway()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await run_startup_canary(state)
        yield

    app = FastAPI(title="ControlPlane.ai", version="1", lifespan=lifespan)
    app.state.gateway = state

    @app.exception_handler(GatewayError)
    async def _gateway_error(request: Request, exc: GatewayError) -> JSONResponse:
        """Map the 05 §1.2 error table. Carries no prompt or response content, ever."""
        request_id = getattr(request.state, "request_id", "") or ""
        return JSONResponse(
            status_code=exc.http_status,
            content=exc.body(request_id),
            headers={HEADER_REQUEST_ID: request_id} if request_id else None,
        )

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        return await handle_completion(state, request)

    # -- admin (05 §2; unauthenticated by documented decision — module docstring) --

    @app.get("/admin/review")
    async def list_review(status: str | None = "pending", limit: int = 100) -> Any:
        return [vars(item) for item in review.list_items(state.conn, status=status, limit=limit)]

    @app.post("/admin/review/{review_id}")
    async def decide_review(review_id: str, body: dict[str, Any]) -> Any:
        item = review.decide(
            state.conn, review_id,
            decision=body.get("decision", ""), note=body.get("note"),
            metrics=state.metrics,
        )
        return vars(item)

    @app.get("/admin/review/{review_id}/released")
    async def released(review_id: str) -> Any:
        return {"review_id": review_id, "text": review.released_text(state.conn, review_id)}

    @app.post("/admin/policies/reload")
    async def reload_policies() -> Any:
        return {"loaded": state.store.reload()}

    @app.get("/admin/policies")
    async def policies() -> Any:
        return {"policies": state.store.describe()}

    @app.get("/metrics")
    async def metrics() -> Any:
        return state.metrics.snapshot()

    return app


async def handle_completion(state: Gateway, http_request: Request) -> Response:
    """The full 02 §4 lifecycle for one request.

    The ordering is the doc's, and it is load-bearing: ingress binds the policy version
    that will judge this request (so a mid-request hot reload cannot change it), the input
    lane runs before dispatch (so an input BLOCK costs nothing — 04 §4.5), and the audit
    write is last (so it records what happened, not what was intended).
    """
    started = time.perf_counter()
    body = await http_request.json()
    # `cp.ingress` (02 §4 step t0) is resolve-use-case + load-policy — NOT the body read
    # above, which is client transport the gateway does not control and which 06 §4 keeps
    # out of the headline for the same reason it keeps the reference row separate.
    ingress_started = time.perf_counter()
    request = ingest(dict(http_request.headers), body, state.store, key_map=state.key_map)
    ingress_ms = (time.perf_counter() - ingress_started) * 1000.0
    http_request.state.request_id = request.request_id

    coverage = pipeline.Coverage()
    latency: dict[str, Any] = {spans.INGRESS: ingress_ms}

    input_started = time.perf_counter()
    verdict, outcome, lane = await pipeline.input_lane(request, coverage, metrics=state.metrics)
    pipeline.note_enrichment(lane.signals, coverage)
    # ADR-030 `input_hold_ms`: 06 §4 defines it as **ingress + input-lane time, before
    # dispatch**, so ingress is inside it. `held_ms` starts from the same point for the same
    # reason — the 06 §4 streaming formula also opens with "ingress + input-lane time", and
    # the previous accumulator started after ingest, under-reporting the sum by that
    # interval. Correcting it moves our own published figure UP, which is the only direction
    # a fidelity fix to a measurement may move it without needing an argument.
    input_hold_ms = ingress_ms + (time.perf_counter() - input_started) * 1000.0
    latency["input_hold_ms"] = input_hold_ms
    held_ms = input_hold_ms
    pipeline.merge_latency(latency, lane.latency.items())

    if not outcome.dispatch:
        return await _input_terminal(
            state, request, verdict, outcome, lane, coverage, latency,
            started=started, held_ms=held_ms,
        )

    messages = request.messages
    input_redactions = ()
    if outcome.action is Action.EDIT and outcome.text is not None:
        # ADR-020 pre-dispatch redaction: the provider never receives the raw value.
        messages = pipeline.redacted_messages(messages, outcome.text)
        input_redactions = outcome.applied

    common = dict(
        state=state, request=request, messages=messages, coverage=coverage,
        latency=latency, input_signals=lane.signals, input_redactions=input_redactions,
        input_verdict=verdict, started=started, held_ms=held_ms,
    )
    if request.policy.streaming:
        return await _stream_response(**common)
    return await _buffered_response(**common)


async def _input_terminal(
    state: Gateway, request, verdict: Verdict, outcome, lane, coverage, latency,
    *, started: float, held_ms: float,
) -> Response:
    """An input-stage BLOCK or ESCALATE: answered without ever calling a provider.

    `model_used`, `tokens_*` and `est_cost_usd` are all left null, which is the honest
    record of 04 §4.5: there was no dispatch, so there is no model and no cost. A zero
    would claim a free upstream call happened.
    """
    # Minted before either write, because the audit record's `actions_json` names it while
    # the review row REFERENCES the audit record — see `Gateway.quarantine`.
    review_id = str(uuid.uuid4()) if outcome.action is Action.ESCALATE else None

    total_ms = (time.perf_counter() - started) * 1000.0
    latency["gateway_overhead_ms"] = pipeline.gateway_overhead_ms(
        total_ms=total_ms, upstream_ms=0.0, held_ms=held_ms,
        streaming=request.policy.streaming,
    )
    state.audit(
        request=request, verdict=verdict, stage_summary=STAGE_INPUT,
        signals=lane.signals, coverage=coverage, latency=latency,
        actions_json=serialize_actions(
            input_redactions=outcome.applied,
            quarantined=outcome.action is Action.ESCALATE,
            review_id=review_id,
            fallback_used=(request.policy.messages.block_fallback
                           if outcome.action is Action.BLOCK else None),
            promoted_to_escalate=outcome.promoted_to_escalate,
            rescan_findings=outcome.rescan_findings,
            notes=outcome.notes,
        ),
    )
    if review_id is not None:
        await state.quarantine(request, outcome.quarantined_text or "", review_id)

    headers = {HEADER_REQUEST_ID: request.request_id}
    if outcome.action is Action.ESCALATE:
        return JSONResponse(
            status_code=HTTP_ESCALATE,
            content={"verdict": "escalate", "review_id": review_id,
                     "message": outcome.user_message},
            headers=headers,
        )
    return JSONResponse(
        status_code=200,
        content=_completion_body(
            request.request_id, "", outcome.user_message or "",
            finish_reason=BLOCK_FINISH_REASON, controlplane={"verdict": "block"},
        ),
        headers=headers,
    )


async def _buffered_response(
    *, state: Gateway, request, messages, coverage, latency, input_signals,
    input_redactions, input_verdict: Verdict, started: float, held_ms: float,
) -> Response:
    """The ADR-014 non-streaming path: buffer fully, check once, deliver atomically.

    This is UC-3's path and the one where 05 §1.1's ESCALATE-as-202 is reachable, because
    the verdict is known before any byte leaves. Nothing is released before the verdict, so
    ADR-002's no-recall problem does not arise here at all.
    """
    upstream_started = time.perf_counter()
    response = await state.dispatcher.complete(messages, tier=TIER)
    upstream_ms = (time.perf_counter() - upstream_started) * 1000.0
    latency["upstream_ms"] = round(upstream_ms, 3)

    unit_started = time.perf_counter()
    stage = pipeline.unit_stage(request.policy)
    lane = await pipeline.run_lane(stage, response.text, request, coverage,
                                  metrics=state.metrics)
    pipeline.note_enrichment(lane.signals, coverage)
    engine_started = time.perf_counter()
    verdict = pipeline.converge(lane, request.policy, metrics=state.metrics)
    policy_ms = (time.perf_counter() - engine_started) * 1000.0
    action_started = time.perf_counter()
    outcome = await pipeline.apply_output(response.text, verdict, request)
    action_ms = (time.perf_counter() - action_started) * 1000.0
    pipeline.note_pii_intercepts(outcome, request.use_case, metrics=state.metrics)
    unit_ms = (time.perf_counter() - unit_started) * 1000.0
    held_ms += unit_ms
    pipeline.merge_latency(latency, lane.latency.items())
    pipeline.merge_latency(latency, (
        (spans.POLICY_EVALUATE, policy_ms), (spans.ACTION_APPLY, action_ms),
    ))
    # One entry, because this path has exactly one unit: M-11 makes a non-streaming pipeline
    # buffer the whole response and run the `output_sentence` detectors over that buffer, so
    # the response IS the unit. Recorded as a one-element series rather than omitted, so the
    # key means the same thing on both paths — NFR-P-001 still scopes to streaming, and the
    # benchmark splits on `streaming` before taking any percentile.
    latency["sentence_holds_ms"] = [unit_ms]

    review_id = str(uuid.uuid4()) if outcome.action is Action.ESCALATE else None

    # The stamped verdict spans both units this path evaluates (04 §4.3 step 5). `verdict`
    # above is the OUTPUT unit's; an input-stage EDIT is invisible in it.
    stamped = _request_verdict([input_verdict, verdict], request)

    total_ms = (time.perf_counter() - started) * 1000.0
    latency["gateway_overhead_ms"] = pipeline.gateway_overhead_ms(
        total_ms=total_ms, upstream_ms=upstream_ms, held_ms=held_ms, streaming=False,
    )
    state.audit(
        request=request, verdict=stamped, stage_summary=STAGE_COMPLETED,
        signals=tuple(input_signals) + tuple(lane.signals),
        coverage=coverage, latency=latency,
        actions_json=serialize_actions(
            applied=outcome.applied, input_redactions=input_redactions,
            quarantined=outcome.action is Action.ESCALATE, review_id=review_id,
            fallback_used=(request.policy.messages.block_fallback
                           if outcome.action is Action.BLOCK else None),
            promoted_to_escalate=outcome.promoted_to_escalate,
            rescan_findings=outcome.rescan_findings, notes=outcome.notes,
        ),
        model_used=response.model_used, tier_requested=TIER,
        tokens_in=response.prompt_tokens, tokens_out=response.completion_tokens,
    )
    if review_id is not None:
        await state.quarantine(
            request, outcome.quarantined_text or response.text, review_id
        )

    headers = {HEADER_REQUEST_ID: request.request_id}
    if outcome.action is Action.ESCALATE:
        return JSONResponse(
            status_code=HTTP_ESCALATE,
            content={"verdict": "escalate", "review_id": review_id,
                     "message": outcome.user_message},
            headers=headers,
        )
    if outcome.action is Action.BLOCK:
        return JSONResponse(
            status_code=200,
            content=_completion_body(
                request.request_id, response.model_used, outcome.user_message or "",
                finish_reason=BLOCK_FINISH_REASON, controlplane={"verdict": "block"},
            ),
            headers=headers,
        )

    # 05 §1.1's `edit` rendering follows the STAMPED verdict, not the output unit's: a
    # prompt-only redaction is still an edited request, and the header is how a client
    # learns that without parsing the body.
    controlplane: dict[str, Any] = {"verdict": stamped.action.value}
    if outcome.applied or input_redactions:
        headers[HEADER_ACTIONS] = "edit"
        controlplane["actions"] = json.loads(serialize_actions(
            applied=outcome.applied, input_redactions=input_redactions))
    return JSONResponse(
        status_code=200,
        content=_completion_body(
            request.request_id, response.model_used, outcome.text or "",
            controlplane=controlplane,
        ),
        headers=headers,
    )


async def _stream_response(
    *, state: Gateway, request, messages, coverage, latency, input_signals,
    input_redactions, input_verdict: Verdict, started: float, held_ms: float,
) -> Response:
    """The 02 §4 streaming path: check each sentence, release as we go (FR-GW-002).

    The audit write happens **inside** the generator, after the last frame, because that is
    the only place that knows how the stream actually ended. A consequence worth naming:
    the HTTP status is committed before the first check runs, so a mid-stream BLOCK cannot
    become a 4xx and a mid-stream ESCALATE cannot become the 202 — 04 §4.4's
    terminate-and-notify is the documented behaviour for exactly this reason.

    **The record is written under `finally`, and this is the only handler that needs it
    (M-13).** `_input_terminal` and `_buffered_response` both audit *before* returning their
    response, so a throw there costs the client its answer but never leaves released content
    unrecorded. This generator is the inverse: it yields content and audits afterwards, so
    every line between the first `yield` and the write is a window in which a request can be
    delivered with no record of it. That window was not hypothetical — `note_pii_intercepts`
    read a field that did not exist, and the `AttributeError` propagated past the write on a
    request whose sentences had already reached the client (only `GatewayError` was caught).
    ADR-002 forbids recalling released text, so the response could not be taken back and
    nothing at all recorded that it happened.

    A crash-path record is marked `record_status='partial'`, because it describes how far the
    request got and not how it ended: its `verdict` is the most severe verdict reached so
    far, its coverage lists what had run by then. Client disconnect arrives as
    `GeneratorExit`/`CancelledError` thrown at the suspended `yield` and takes the same path,
    which is correct — an abandoned stream is also a request that got part-way.

    The rescue is **synchronous throughout** (`finalize_latency`, `state.audit` and the
    sqlite write underneath them), and that is a requirement rather than an accident: a
    `finally` reached by cancellation cannot reliably `await`, since the next suspension
    point raises `CancelledError` again. So the partial record is written and the review row
    is not — quarantining needs an await, and a review item is recoverable from the audit
    record while the audit record is recoverable from nothing.
    """
    model = state.dispatcher.resolve_model(TIER)

    async def body() -> AsyncIterator[str]:
        nonlocal held_ms
        # Two accumulators, and conflating them is an arithmetic error rather than a
        # simplification. `held_ms` is the 06 §4 streaming overhead — ingress + input lane
        # + every per-sentence hold — and arrives already carrying the input lane, which
        # ran BEFORE `stream_started`. `stream_hold_ms` counts only the holds inside the
        # stream window, which is the sole quantity that may be subtracted from the stream
        # duration to leave token-wait time. Using `held_ms` there subtracts the input lane
        # from an interval it was never part of, under-reporting `upstream_ms`.
        stream_hold_ms = 0.0
        # ADR-030's per-hold series: one entry per sentence, NOT an accumulator. It is the
        # per-hold detail `stream_hold_ms` sums away, and NFR-P-001 targets the entries
        # rather than the sum — which is precisely why both have to exist.
        sentence_holds: list[float] = []
        buffer = Segmentation()
        signals: list[Signal] = list(input_signals)
        actions: list[Any] = []
        verdicts: list[Verdict] = []
        terminal: tuple[Verdict, Any] | None = None
        released: list[str] = []
        seen: list[str] = []
        stream_started = time.perf_counter()
        # Guards against a double INSERT: 05 §3 is one row per request and append-only, so a
        # second write raises rather than replacing. The flag is set only after a write
        # returns, which means an audit write that ITSELF fails still leaves the crash path
        # free to try the smaller partial record.
        audited = False
        # Declared before the try, not at the terminal rendering below, because the rescue
        # path reads both: a crash before the rendering would otherwise raise
        # UnboundLocalError *inside* the finally and lose the record it exists to save.
        review_id: str | None = None
        quarantine_text = ""

        def finalize_latency() -> None:
            """The 06 §4 streaming figures. Both are well defined mid-flight: overhead is
            the sum of the holds that actually happened, and `upstream_ms` the stream
            duration minus those holds — so a partial record carries real measurements, and
            it is `record_status` rather than a missing key that keeps them out of a
            published aggregate.

            The ADR-030 per-hold series is written here for the same reason: on a crash path
            the holds that already happened are real measurements of real waits, and the
            series is the quantity NFR-P-001 targets. `input_hold_ms` is already in
            `latency` — it was recorded before dispatch, so it exists even for a request
            that dies mid-stream."""
            total_ms = (time.perf_counter() - started) * 1000.0
            stream_ms = (time.perf_counter() - stream_started) * 1000.0
            latency["upstream_ms"] = round(max(0.0, stream_ms - stream_hold_ms), 3)
            latency["gateway_overhead_ms"] = pipeline.gateway_overhead_ms(
                total_ms=total_ms, upstream_ms=latency["upstream_ms"],
                held_ms=held_ms, streaming=True,
            )
            # Written only when at least one sentence was held. An empty list would claim
            # "measured, zero holds" for a request that died before its first boundary,
            # which is the "not measured" vs "measured clean" collapse M-10 forbids — an
            # absent key already means not-recorded, and the bench reads it that way.
            if sentence_holds:
                latency["sentence_holds_ms"] = list(sentence_holds)

        def write_partial() -> None:
            """The M-13 fallback: record a request that died after releasing content.

            Marked `partial`, so the row is a statement about how far the request got. Every
            figure on it is real — the verdict is the most severe reached so far, the latency
            the holds that actually happened — and `record_status` is what keeps them out of
            a published aggregate, rather than nulling fields to make the row look harmless.

            `quarantined` is reported as whether an id was actually minted. If the crash
            landed between minting and the review INSERT, the audit says quarantined with a
            `review_id` naming a row that does not exist — which is the honest record of what
            happened, and is why the admin listing resolves review items by query rather than
            trusting an id from this column.
            """
            finalize_latency()
            state.audit(
                request=request, verdict=_final_verdict(terminal, verdicts, request),
                stage_summary=STAGE_STREAMED, signals=signals, coverage=coverage,
                latency=latency,
                actions_json=serialize_actions(
                    applied=actions, input_redactions=input_redactions,
                    quarantined=review_id is not None, review_id=review_id,
                ),
                model_used=model, tier_requested=TIER,
                record_status=RECORD_STATUS_PARTIAL,
            )

        async def check(segment_text: str) -> bool:
            """Check one unit. Returns False when the stream must stop (04 §4.4)."""
            nonlocal held_ms, stream_hold_ms, terminal
            unit_started = time.perf_counter()
            lane = await pipeline.run_lane(
                Stage.OUTPUT_SENTENCE, segment_text, request, coverage,
                metrics=state.metrics,
            )
            pipeline.note_enrichment(lane.signals, coverage)
            engine_started = time.perf_counter()
            verdict = pipeline.converge(lane, request.policy, metrics=state.metrics)
            policy_ms = (time.perf_counter() - engine_started) * 1000.0
            action_started = time.perf_counter()
            outcome = await pipeline.apply_output(segment_text, verdict, request)
            action_ms = (time.perf_counter() - action_started) * 1000.0
            pipeline.note_pii_intercepts(outcome, request.use_case, metrics=state.metrics)
            unit_ms = (time.perf_counter() - unit_started) * 1000.0
            held_ms += unit_ms
            stream_hold_ms += unit_ms
            # ADR-030: each hold is its own entry, because NFR-P-001 targets the hold a user
            # waits through. Appended even when this unit turns out to be terminal — the
            # sentence was still held for that long, and dropping it would make a blocked
            # response look like it held less than it did.
            sentence_holds.append(unit_ms)

            signals.extend(lane.signals)
            verdicts.append(verdict)
            actions.extend(outcome.applied)
            pipeline.merge_latency(latency, lane.latency.items())
            pipeline.merge_latency(latency, (
                (spans.POLICY_EVALUATE, policy_ms), (spans.ACTION_APPLY, action_ms),
            ))

            if outcome.action in (Action.BLOCK, Action.ESCALATE):
                terminal = (verdict, outcome)
                return False
            # PASS or EDIT: `text` is non-None by the Outcome contract, and this is the
            # only place text reaches the client.
            released.append(outcome.text or "")
            return True

        # M-13: from here on, content can reach the client, so no exit may skip the
        # record. `finally` covers all three ways this generator can end — a raise, a
        # return, and the GeneratorExit of a client disconnect.
        try:
            try:
                async for delta in state.dispatcher.stream_text(messages, tier=TIER):
                    seen.append(delta)
                    for segment in buffer.feed(delta):
                        if not await check(segment.text):
                            break
                        yield _delta_frame(request.request_id, model, released[-1])
                    if terminal is not None:
                        break

                if terminal is None:
                    for segment in buffer.flush():
                        if not await check(segment.text):
                            break
                        yield _delta_frame(request.request_id, model, released[-1])
            except GatewayError:
                # 05 §1.2 ERR-UP-001 mid-stream. The status line is already 200, so the error
                # cannot be re-rendered as a 502 — the stream ends and the record says why.
                # ADR-002: released text cannot be recalled, so there is nothing to undo.
                yield _final_frame(request.request_id, model, "error",
                                   {"error": {"code": "ERR-UP-001"}})
                terminal = terminal or None

            # -- terminal rendering (04 §4.4) ---------------------------------
            if terminal is not None:
                verdict, outcome = terminal
                if outcome.action is Action.BLOCK:
                    yield _delta_frame(request.request_id, model,
                                       request.policy.messages.block_fallback)
                    yield _final_frame(request.request_id, model, BLOCK_FINISH_REASON,
                                       {"verdict": "block"})
                else:
                    # 04 §4.4: the ENTIRE response is quarantined — released and unreleased
                    # alike — because the reviewer judges the response, not the remainder.
                    # The id is minted here so the frame below can name it, but the row is not
                    # written until after the audit record exists (FK, see `quarantine`).
                    review_id = str(uuid.uuid4())
                    quarantine_text = "".join(seen) + buffer.pending
                    yield _delta_frame(request.request_id, model,
                                       outcome.user_message or "")
                    yield _final_frame(request.request_id, model, "stop",
                                       {"verdict": "escalate", "review_id": review_id})
            else:
                # Same aggregation as the buffered path: the final frame reports the
                # request, and an input-stage redaction happened even if no sentence was
                # touched. Computed here so the frame and the audit record below cannot
                # disagree about what this request's verdict was.
                streamed = _request_verdict([input_verdict, *verdicts], request)
                # One source for the verdict. Reaching this branch means nothing terminated,
                # so the aggregate is `pass` or `edit` by construction — but deriving it from
                # the same helper the audit record uses is what keeps the frame and the record
                # from ever disagreeing, which a literal `"edit"` here would not.
                controlplane: dict[str, Any] = {"verdict": streamed.action.value}
                if actions or input_redactions:
                    controlplane["actions"] = json.loads(serialize_actions(
                        applied=actions, input_redactions=input_redactions))
                yield _final_frame(request.request_id, model, "stop", controlplane)

            yield f"data: {DONE}\n\n"

            # -- audit (one record per request, FR-AUD-001) -------------------
            final = _request_verdict(
                [input_verdict, _final_verdict(terminal, verdicts, request)], request)
            finalize_latency()
            state.audit(
                request=request, verdict=final, stage_summary=STAGE_STREAMED,
                signals=signals, coverage=coverage, latency=latency,
                actions_json=serialize_actions(
                    applied=actions, input_redactions=input_redactions,
                    quarantined=review_id is not None, review_id=review_id,
                    fallback_used=(request.policy.messages.block_fallback
                                   if final.action is Action.BLOCK else None),
                ),
                model_used=model, tier_requested=TIER,
            )
            audited = True
            if review_id is not None:
                await state.quarantine(request, quarantine_text, review_id)
        finally:
            if not audited:
                try:
                    write_partial()
                except Exception:  # noqa: BLE001
                    # Swallowed deliberately: this runs while another exception may be in
                    # flight, and raising here would REPLACE it — the operator would then
                    # see the rescue's failure instead of the defect that caused it.
                    pass

    # M-12 reads 05 §1.1's `X-ControlPlane-Actions` header as non-streaming-only, because a
    # header is committed to the wire before the first sentence is ever checked. That holds
    # for *output* edits — but an input-stage redaction (ADR-020) is decided BEFORE dispatch,
    # so it is known here, before this response's status line exists. Withholding it would
    # make the header unreachable in practice rather than mode-specific: `support_bot` is the
    # only shipped policy mapping `pii.*` to `edit`, and it is `streaming: true`.
    stream_headers = {HEADER_REQUEST_ID: request.request_id}
    if input_redactions:
        stream_headers[HEADER_ACTIONS] = "edit"

    return StreamingResponse(
        body(), media_type="text/event-stream", headers=stream_headers,
    )


def _request_verdict(candidates: list[Verdict], request) -> Verdict:
    """The one request-level verdict: most severe across **every** evaluated unit.

    04 §4.3 step 5 stamps one verdict per request, and 05 §3 has one `verdict` column, but a
    request is evaluated in several units — the input, then every output unit, plus the
    conversation stage once `conv_tracker` is wired. The stamp is the most severe of them
    (04 §4.2's total order), for the same reason `_final_verdict` takes the most severe
    sentence rather than the last: a request whose *prompt* was redacted did not "pass"
    because its response happened to be clean.

    Owner live-test finding, 2026-08-28: an input-stage EDIT (ADR-020 pre-dispatch
    redaction) with a clean output stamped `pass`, so the redaction was invisible to
    `cp_requests_total{verdict}` and to the caller — the gateway's most demonstrable
    privacy behaviour, unreported.

    The action is the severest across units, but the *evidence* is the union of all of
    them — not the winning unit's row. Picking one unit's Verdict would drop the other's
    `failure_outcomes`, and `from_verdict` reads `detector_failures_json` straight off the
    stamped verdict: a detector that failed `fail_open` during output scoring would vanish
    from the record whenever the input unit tied it on severity. 04 §5 requires the fault
    to be recorded whether or not it contributed, so the union is what makes
    "recorded but not contributing" representable at all.

    `contributing_signal_ids` and `failure_record_ids` then filter that union against the
    stamped action by themselves, which is why merging is safe: an input PASS's signals do
    not become contributors to an output BLOCK just by sharing a record.
    """
    present = [v for v in candidates if v is not None]
    if not present:
        return Verdict(action=Action.PASS, use_case=request.use_case,
                       policy_version=request.policy_version)
    if len(present) == 1:
        return present[0]
    return Verdict(
        action=most_severe(v.action for v in present),
        use_case=present[0].use_case,
        policy_version=present[0].policy_version,
        signal_outcomes=tuple(o for v in present for o in v.signal_outcomes),
        failure_outcomes=tuple(o for v in present for o in v.failure_outcomes),
        edits=tuple(e for v in present for e in v.edits),
    )


def _final_verdict(
    terminal: tuple[Verdict, Any] | None, verdicts: list[Verdict], request
) -> Verdict:
    """The one verdict for a streamed request's single audit record (FR-AUD-001).

    A stream produces one verdict per sentence but 05 §3 has one `verdict` column, so the
    record carries the **most severe** across units (04 §4.2's total order). Not the last
    one: a response whose third sentence was blocked did not "pass" because its fourth was
    never checked. A terminal verdict is by construction the most severe, since BLOCK and
    ESCALATE are what terminate.
    """
    if terminal is not None:
        return terminal[0]
    if not verdicts:
        # An empty upstream response. PASS is the truthful verdict — nothing was found
        # because there was nothing to check — and the coverage column is what tells a
        # reader that detectors ran at all.
        return Verdict(action=Action.PASS, use_case=request.use_case,
                       policy_version=request.policy_version)
    severest = most_severe(v.action for v in verdicts)
    for verdict in verdicts:
        if verdict.action is severest:
            return verdict
    return verdicts[-1]
