"""Upstream dispatch: 05 §1.2 failure semantics, NFR-SEC-002 credential handling.

No live network: every test drives `httpx.MockTransport`. The URL-join expectations come
from keyless probes of the real providers (recorded in `upstream_url`'s docstring), so the
paths asserted here are the paths those hosts actually answer on.

Async tests use bare `asyncio.run()` — `pytest_asyncio` is not a declared dependency and
02 §8 bounds the dependency set.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from controlplane.gateway.config import load_gateway_config
from controlplane.gateway.ingress import UpstreamError
from controlplane.gateway.sse_proxy import (
    CHAT_COMPLETIONS,
    MAX_ATTEMPTS,
    UpstreamDispatcher,
    auth_headers,
    sse_text_delta,
    upstream_url,
)
from controlplane.telemetry.metrics import MetricsRegistry

SECRET = "sk-canary-do-not-leak-4242424242"
MESSAGES = [{"role": "user", "content": "What is the refund window?"}]


@pytest.fixture(scope="module")
def config():
    return load_gateway_config()


@pytest.fixture
def metrics() -> MetricsRegistry:
    """A private registry, so a test cannot pollute the process-wide default."""
    return MetricsRegistry()


def provider(config, name: str):
    return config.provider(name)


def dispatcher(config, handler, metrics: MetricsRegistry | None = None,
               ) -> UpstreamDispatcher:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return UpstreamDispatcher(config, client=client, metrics=metrics or MetricsRegistry())


def completion(text: str = "Thirty days.", *, model: str = "openai/gpt-oss-20b",
               prompt_tokens: int = 12, completion_tokens: int = 4) -> dict:
    return {
        "id": "cmpl-1", "model": model,
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


def sse(*deltas: str) -> bytes:
    frames = [
        f'data: {json.dumps({"choices": [{"delta": {"content": d}}]})}\n\n'
        for d in deltas
    ]
    return ("".join(frames) + "data: [DONE]\n\n").encode()


# --------------------------------------------------------------------------
# URL join — probe-verified against the real hosts
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name,expected", [
    ("kiro-local", "http://localhost:8000/v1/chat/completions"),
    ("groq", "https://api.groq.com/openai/v1/chat/completions"),
    ("ollama-local", "http://localhost:11434/v1/chat/completions"),
])
def test_the_v1_prefix_is_inserted_only_when_missing(config, name, expected) -> None:
    """★ The two shipped providers disagree about whether base_url carries `/v1`.

    Keyless probes: kiro-local answers 401 on /v1/chat/completions and 404 without it;
    groq is the exact inverse. A naive join or an unconditional prefix breaks one.
    """
    assert upstream_url(provider(config, name)) == expected


def test_a_trailing_slash_does_not_double_up(config) -> None:
    target = provider(config, "groq").model_copy(
        update={"base_url": "https://api.groq.com/openai/v1/"}
    )
    assert upstream_url(target) == "https://api.groq.com/openai/v1/chat/completions"
    assert "//chat" not in upstream_url(target)


def test_the_completion_path_is_the_openai_compatible_one() -> None:
    assert CHAT_COMPLETIONS == "chat/completions"


# --------------------------------------------------------------------------
# NFR-SEC-002 — the credential is read by name and never surfaced
# --------------------------------------------------------------------------


def test_key_env_is_read_from_the_environment_by_name(config, monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    headers = auth_headers(provider(config, "groq"))
    assert headers["Authorization"] == f"Bearer {SECRET}"
    assert headers["x-api-key"] == SECRET


def test_a_provider_needing_no_credential_yields_no_auth_header(config) -> None:
    """`key_env: null` is a valid state (a local daemon), not an error."""
    assert auth_headers(provider(config, "ollama-local")) == {}


def test_nfr_sec_002_an_unset_variable_names_the_variable_not_the_value(
    config, monkeypatch
) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(UpstreamError) as excinfo:
        auth_headers(provider(config, "groq"))
    assert "GROQ_API_KEY" in str(excinfo.value)
    assert SECRET not in str(excinfo.value)


def test_nfr_sec_002_a_provider_error_body_never_reaches_the_client(
    config, monkeypatch
) -> None:
    """★ A 401 body can echo a key prefix, so it is drained and discarded.

    The 05 §1.2 body is assembled from the class-level message, so provider detail
    cannot reach the caller even when it reaches the log.
    """
    monkeypatch.setenv("GROQ_API_KEY", SECRET)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": f"invalid key {SECRET[:12]}..."})

    with pytest.raises(UpstreamError) as excinfo:
        asyncio.run(dispatcher(config, handler).complete(
            MESSAGES, tier="small", provider=provider(config, "groq")))

    rendered = json.dumps(excinfo.value.body("req-1"))
    assert SECRET[:12] not in rendered
    assert "invalid key" not in rendered
    assert json.loads(rendered)["error"]["code"] == "ERR-UP-001"


def test_the_credential_is_sent_as_a_header_not_in_the_body(config, monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return httpx.Response(200, json=completion())

    asyncio.run(dispatcher(config, handler).complete(
        MESSAGES, tier="small", provider=provider(config, "groq")))
    assert SECRET not in seen["body"]


# --------------------------------------------------------------------------
# SSE frame parsing
# --------------------------------------------------------------------------


def test_a_text_delta_is_extracted() -> None:
    frame = 'data: {"choices": [{"delta": {"content": "Hello"}}]}'
    assert sse_text_delta(frame) == "Hello"


@pytest.mark.parametrize("line", [
    "", "   ", ": keep-alive comment", "data: [DONE]", "data:",
    "event: ping", "data: {not json",
    'data: {"choices": []}',
    'data: {"choices": [{"delta": {}}]}',
    'data: {"choices": [{"delta": {"content": ""}}]}',
    'data: "a bare string"',
])
def test_non_text_frames_yield_none(line: str) -> None:
    """★ A malformed frame must not abort a stream whose sentences were already checked.

    It carries no text, so tolerating it bypasses no detection — whereas raising would
    kill a response mid-flight over a provider's junk keep-alive.
    """
    assert sse_text_delta(line) is None


def test_a_role_only_opening_frame_yields_none() -> None:
    """OpenAI sends `delta: {role: assistant}` first; that is not text."""
    assert sse_text_delta('data: {"choices": [{"delta": {"role": "assistant"}}]}') is None


# --------------------------------------------------------------------------
# FR-GW-004 / ADR-014 — non-streaming dispatch
# --------------------------------------------------------------------------


def test_a_non_streaming_completion_is_parsed(config, monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", SECRET)

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is False
        return httpx.Response(200, json=completion("Thirty days from purchase."))

    result = asyncio.run(dispatcher(config, handler).complete(
        MESSAGES, tier="small", provider=provider(config, "groq")))
    assert result.text == "Thirty days from purchase."
    assert result.model_used == "openai/gpt-oss-20b"
    assert (result.prompt_tokens, result.completion_tokens) == (12, 4)
    assert result.finish_reason == "stop"


def test_model_used_records_what_actually_answered(config, monkeypatch) -> None:
    """05 §3 separates `tier_requested` from `model_used`; a provider may substitute."""
    monkeypatch.setenv("GROQ_API_KEY", SECRET)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=completion(model="openai/gpt-oss-20b-0125"))

    result = asyncio.run(dispatcher(config, handler).complete(
        MESSAGES, tier="small", provider=provider(config, "groq")))
    assert result.model_used == "openai/gpt-oss-20b-0125"


def test_absent_usage_stays_none_rather_than_zero(config, monkeypatch) -> None:
    """★ ADR-022's discipline: unknown is not zero. Zero tokens would be a fake count."""
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    payload = completion()
    del payload["usage"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    result = asyncio.run(dispatcher(config, handler).complete(
        MESSAGES, tier="small", provider=provider(config, "groq")))
    assert result.prompt_tokens is None and result.completion_tokens is None


def test_a_non_json_body_is_err_up_001(config, monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", SECRET)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>gateway timeout</html>")

    with pytest.raises(UpstreamError):
        asyncio.run(dispatcher(config, handler).complete(
            MESSAGES, tier="small", provider=provider(config, "groq")))


def test_gateway_extensions_are_not_forwarded_upstream(config, monkeypatch) -> None:
    """★ `controlplane.*` is our own surface (05 §1.1), not the provider's business."""
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=completion())

    asyncio.run(dispatcher(config, handler).complete(
        MESSAGES, tier="small", provider=provider(config, "groq"),
        extra={"controlplane": {"context": ["internal doc"]}, "temperature": 0.2}))
    assert "controlplane" not in seen["body"]
    assert seen["body"]["temperature"] == 0.2
    assert "internal doc" not in json.dumps(seen["body"])


# --------------------------------------------------------------------------
# 05 §1.2 — one retry, then ERR-UP-001
# --------------------------------------------------------------------------


def test_a_transient_failure_is_retried_once_then_err_up_001(config, monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    with pytest.raises(UpstreamError) as excinfo:
        asyncio.run(dispatcher(config, handler).complete(
            MESSAGES, tier="small", provider=provider(config, "groq")))
    assert calls["n"] == MAX_ATTEMPTS == 2
    assert excinfo.value.http_status == 502


def test_a_retry_that_succeeds_returns_the_completion(config, monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=completion("Recovered."))

    result = asyncio.run(dispatcher(config, handler).complete(
        MESSAGES, tier="small", provider=provider(config, "groq")))
    assert (result.text, calls["n"]) == ("Recovered.", 2)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_a_client_error_is_not_retried(config, monkeypatch, status: int) -> None:
    """★ A 401 fails identically twice; retrying only doubles the latency of the error."""
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(status)

    with pytest.raises(UpstreamError):
        asyncio.run(dispatcher(config, handler).complete(
            MESSAGES, tier="small", provider=provider(config, "groq")))
    assert calls["n"] == 1


def test_a_transport_error_is_retried_then_reported(config, monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("refused")

    with pytest.raises(UpstreamError):
        asyncio.run(dispatcher(config, handler).complete(
            MESSAGES, tier="small", provider=provider(config, "groq")))
    assert calls["n"] == MAX_ATTEMPTS


# --------------------------------------------------------------------------
# Streaming
# --------------------------------------------------------------------------


def test_stream_text_yields_only_text_deltas(config, monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", SECRET)

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, content=sse("The refund ", "window is ", "30 days."))

    async def collect() -> list[str]:
        return [chunk async for chunk in dispatcher(config, handler).stream_text(
            MESSAGES, tier="small", provider=provider(config, "groq"))]

    assert "".join(asyncio.run(collect())) == "The refund window is 30 days."


def test_a_refused_stream_is_err_up_001_without_the_body(config, monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", SECRET)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": f"rate limited for {SECRET[:10]}"})

    async def drain() -> None:
        async for _ in dispatcher(config, handler).stream_text(
            MESSAGES, tier="small", provider=provider(config, "groq")):
            pass

    with pytest.raises(UpstreamError) as excinfo:
        asyncio.run(drain())
    assert SECRET[:10] not in str(excinfo.value)
    assert excinfo.value.code == "ERR-UP-001"


def test_a_mid_stream_failure_is_not_retried(config, monkeypatch) -> None:
    """★ ADR-002 forbids recalling released text, so re-dispatch would duplicate it.

    Retry is confined to the pre-first-byte window as a correctness rule, not a
    performance choice.
    """
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500)

    async def drain() -> None:
        async for _ in dispatcher(config, handler).stream_text(
            MESSAGES, tier="small", provider=provider(config, "groq")):
            pass

    with pytest.raises(UpstreamError):
        asyncio.run(drain())
    assert calls["n"] == 1, "a stream was re-dispatched; released text cannot be recalled"


# --------------------------------------------------------------------------
# Tier resolution + fallback visibility
# --------------------------------------------------------------------------


def test_an_unbound_tier_is_refused_not_substituted(config) -> None:
    """★ ADR-009's premise is that the frontier tier costs strictly more (ADR-029).

    Quietly serving `frontier` for an unbound `small` would corrupt the exact comparison
    the cost plane exists to make — and it would do so in the *flattering* direction, by
    pricing an escalation as if it had been routed cheap. `ollama-local` ships with both
    tiers null (SL-4). The ratio is deployment-specific (2.0x on the shipped gpt-oss pair,
    not the retired llama pair's ~12x); the substitution is wrong at any ratio.
    """
    with pytest.raises(UpstreamError, match="binds no model to tier"):
        UpstreamDispatcher(config).resolve_model("small", provider(config, "ollama-local"))


@pytest.mark.parametrize("tier,expected", [
    ("small", "openai/gpt-oss-20b"),
    ("frontier", "openai/gpt-oss-120b"),
])
def test_tiers_resolve_to_concrete_model_ids(config, tier, expected) -> None:
    resolved = UpstreamDispatcher(config).resolve_model(tier, provider(config, "groq"))
    assert resolved == expected


def test_fr_gw_006_a_fallback_is_never_silent(config, metrics: MetricsRegistry) -> None:
    """★ A silent fallback during the demo would look like success.

    Worse, if the target is dev-class every downstream figure is tainted (ADR-018), so
    the engagement has to be visible in metrics rather than inferred from a log.
    """
    UpstreamDispatcher(config, metrics=metrics).note_fallback(
        from_provider="groq", to_provider="kiro-local", reason="upstream_unreachable")
    assert metrics.value_of(
        "cp_fallback_engaged_total", from_provider="groq",
        to_provider="kiro-local", reason="upstream_unreachable") == 1.0


def test_the_dispatcher_holds_no_verdict_or_cascade_surface(config) -> None:
    """It moves bytes and reports what happened; ADR-013's probe is deferred, not stubbed.

    A stubbed probe would make `cascade_escalated` always false for the wrong reason —
    indistinguishable from a probe that ran and never escalated.
    """
    surface = set(dir(UpstreamDispatcher))
    assert not {"evaluate", "verdict", "apply_policy"} & surface
    assert not {"probe", "cascade", "run_probe"} & surface
