"""Upstream dispatcher and SSE relay.

Implements 02 §4 dispatch/stream steps; upstream failure semantics per 05 §1.2
(ERR-UP-001). Cascade probe mechanics per ADR-013 are **deferred to the cost-plane
phase** and deliberately absent here rather than stubbed — a probe that silently did
nothing would make `cascade_escalated` a field that is always false for the wrong reason.

**The credential is read by NAME and never travels anywhere but the request header.**
`Provider.key_env` holds an env var *name* (NFR-SEC-002); this module reads the value at
dispatch, puts it in one header, and never logs it, never puts it in an exception, and
never returns it. `UpstreamError` carries no provider response body for the same reason:
a 401 body from a provider can echo the key prefix.

**Retry is confined to the pre-first-byte window, and that is a correctness rule rather
than an optimisation.** 05 §1.2 allows one retry before ERR-UP-001. Once the first byte
of a stream has been relayed, the sentence pipeline may already have released text to the
client, and re-dispatching would duplicate it — ADR-002's no-recall rule means released
text cannot be taken back. So a mid-stream failure is terminal, always.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from controlplane.gateway.config import GatewayConfig, Provider
from controlplane.gateway.ingress import UpstreamError
from controlplane.telemetry.metrics import REGISTRY_DEFAULT, MetricsRegistry

#: The OpenAI-compatible completion path, appended to a provider's `base_url`.
CHAT_COMPLETIONS = "chat/completions"

#: SSE sentinel ending an OpenAI-compatible stream.
DONE = "[DONE]"

#: 05 §1.2 permits one retry before ERR-UP-001, so two attempts total.
MAX_ATTEMPTS = 2

#: Statuses worth a second attempt. A 4xx is excluded on purpose: a 401 or a malformed
#: body will fail identically the second time, and retrying it only doubles the latency
#: of an error the caller must fix anyway. 429 is included — it is explicitly transient.
_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


def upstream_url(provider: Provider, path: str = CHAT_COMPLETIONS) -> str:
    """Join `provider.base_url` and `path`, inserting the `/v1` prefix iff it is missing.

    05 §6.1 types `base_url` as a bare `<url>` and the two shipped providers disagree
    about whether it already carries the version segment. Probed keyless (no credential
    sent, so 401 = the path exists and 404 = it does not), 2026-08-26:

        kiro-local  http://localhost:8000            /chat/completions     -> 404
        kiro-local  http://localhost:8000            /v1/chat/completions  -> 401
        groq        https://api.groq.com/openai/v1   /chat/completions     -> 401
        groq        https://api.groq.com/openai/v1   /v1/chat/completions  -> 404

    So neither a naive join nor an unconditional `/v1` works for both. Logged as a MINOR
    resolution in docs/08 rather than as a deviation: 05 §6.1 does not state a joining
    rule, so this fills a gap instead of contradicting one.
    """
    base = provider.base_url.rstrip("/")
    prefix = "" if base.endswith("/v1") else "/v1"
    return f"{base}{prefix}/{path.lstrip('/')}"


def auth_headers(provider: Provider) -> dict[str, str]:
    """Build the auth header from the env var `provider.key_env` NAMES (NFR-SEC-002).

    A provider declaring `key_env: null` needs no credential (a local daemon), which is a
    valid state and not an error. A declared-but-unset variable *is* an error, raised
    naming the variable — the name is public config, the value is never touched.
    """
    if provider.key_env is None:
        return {}
    value = os.environ.get(provider.key_env)
    if not value:
        raise UpstreamError(
            f"provider {provider.name!r} declares key_env {provider.key_env} but that "
            "environment variable is unset; copy .env.example to .env (NFR-SEC-002)"
        )
    # Both shapes: OpenAI-compatible providers read `Authorization`, Anthropic-shaped
    # ones read `x-api-key`. Sending both costs nothing and keeps one code path.
    return {"Authorization": f"Bearer {value}", "x-api-key": value}


@dataclass
class UpstreamResponse:
    """A completed non-streaming upstream call (FR-GW-004 / ADR-014 path).

    `prompt_tokens`/`completion_tokens` are the provider's *self-reported* counts and are
    stored as such — ADR-018 is the reason they are not treated as measurements without a
    provider class to qualify them.
    """

    text: str
    model_used: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def _extract_text(payload: dict[str, Any]) -> str:
    """Pull assistant text out of an OpenAI-shaped completion body."""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    return ""


def _usage(payload: dict[str, Any]) -> tuple[int | None, int | None]:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None, None
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    return (prompt if isinstance(prompt, int) else None,
            completion if isinstance(completion, int) else None)


def sse_text_delta(line: str) -> str | None:
    """Text delta from one SSE line, or None for anything that is not one.

    Returns None for blank lines, comments, the `[DONE]` sentinel, and malformed JSON.
    Tolerating a malformed frame rather than raising is deliberate: a provider emitting
    one junk frame should not abort a response whose released sentences were already
    checked, and the frame carries no text so nothing bypasses detection.
    """
    if not line.startswith("data:"):
        return None
    body = line[len("data:"):].strip()
    if not body or body == DONE:
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    delta = first.get("delta")
    if isinstance(delta, dict):
        content = delta.get("content")
        if isinstance(content, str) and content:
            return content
    return None


def _body(
    messages: list[dict[str, Any]],
    model: str,
    *,
    stream: bool,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The OpenAI-compatible request body. Gateway extensions are NOT forwarded.

    `controlplane.*` keys and the `X-ControlPlane-*` headers are this system's own
    surface (05 §1.1); passing them upstream would leak our config into a third party's
    request log for no benefit.
    """
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
    for key, value in (extra or {}).items():
        if key not in {"model", "messages", "stream", "controlplane"}:
            payload[key] = value
    return payload


class UpstreamDispatcher:
    """Dispatches to the configured provider. One instance per app.

    Holds no policy and makes no verdict: it moves bytes and reports what happened. The
    per-sentence detector/policy loop consumes `stream_text()` and is the caller's job,
    which is what keeps `sentence_buffer` and this module independently testable.
    """

    def __init__(
        self,
        config: GatewayConfig,
        *,
        client: httpx.AsyncClient | None = None,
        metrics: MetricsRegistry | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.config = config
        self.metrics = metrics or REGISTRY_DEFAULT
        self._client = client
        self._timeout = timeout

    # -- provider selection ------------------------------------------------

    def resolve_model(self, tier: str, provider: Provider | None = None) -> str:
        """Concrete model id for `tier` (05 §6.1 `tiers`), or raise.

        Refuses rather than substituting the other tier: ADR-009's premise is that the
        tiers differ ~12x in cost, so quietly serving `frontier` for an unbound `small`
        would corrupt the cost plane's central comparison.

        An unknown tier *name* is refused by `Tiers.resolve` itself, which raises
        `KeyError`: that is a caller bug and belongs in ERR-GW-001, not in the
        502/retry-yes `UpstreamError` an unbound-but-real tier earns.
        """
        target = provider or self.config.active
        model = target.tiers.resolve(tier)
        if model is None:
            raise UpstreamError(
                f"provider {target.name!r} binds no model to tier {tier!r} "
                "(config/gateway.yaml `tiers`); it cannot serve this request"
            )
        return model

    def note_fallback(self, *, from_provider: str, to_provider: str, reason: str) -> None:
        """Record a provider fallback. Never silent (FR-GW-006).

        A silent fallback during the demo would look like success while the numbers came
        from a different provider than the one on screen — and if the target is dev-class,
        every figure downstream is tainted (ADR-018).
        """
        self.metrics.increment(
            "cp_fallback_engaged_total",
            from_provider=from_provider, to_provider=to_provider, reason=reason,
        )

    # -- dispatch ----------------------------------------------------------

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tier: str = "small",
        provider: Provider | None = None,
        extra: dict[str, Any] | None = None,
    ) -> UpstreamResponse:
        """Non-streaming dispatch: the FR-GW-004 / ADR-014 whole-response path."""
        target = provider or self.config.active
        model = self.resolve_model(tier, target)
        payload = _body(messages, model, stream=False, extra=extra)

        response = await self._post(target, payload)
        try:
            parsed = response.json()
        except ValueError as exc:
            raise UpstreamError(
                f"provider {target.name!r} returned a non-JSON completion body"
            ) from exc

        prompt_tokens, completion_tokens = _usage(parsed)
        choices = parsed.get("choices")
        finish = (choices[0].get("finish_reason")
                  if isinstance(choices, list) and choices and isinstance(choices[0], dict)
                  else None)
        return UpstreamResponse(
            text=_extract_text(parsed),
            # The CONCRETE id that answered, per 05 §3 `model_used`. Falling back to the
            # requested id when the provider omits it keeps the column non-null, and the
            # two agreeing is the normal case.
            model_used=parsed.get("model") if isinstance(parsed.get("model"), str) else model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=finish,
            raw=parsed if isinstance(parsed, dict) else {},
        )

    async def stream_text(
        self,
        messages: list[dict[str, Any]],
        *,
        tier: str = "small",
        provider: Provider | None = None,
        extra: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Yield text deltas from a streaming dispatch (02 §4 t1).

        Yields *text only*: the caller feeds these into `sentence_buffer` and decides what
        reaches the client. Nothing here writes to a client socket, which is what makes
        FR-GW-002 testable without a live connection.
        """
        target = provider or self.config.active
        model = self.resolve_model(tier, target)
        payload = _body(messages, model, stream=True, extra=extra)
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        owns_client = self._client is None

        try:
            async with client.stream(
                "POST", upstream_url(target), json=payload, headers=auth_headers(target),
            ) as response:
                if response.status_code >= 400:
                    # Read and DISCARD the body: it is drained so the connection can be
                    # reused, but never surfaced — a provider error body can echo a key
                    # prefix (NFR-SEC-002).
                    await response.aread()
                    raise UpstreamError(
                        f"provider {target.name!r} refused the stream "
                        f"(HTTP {response.status_code})"
                    )
                async for line in response.aiter_lines():
                    delta = sse_text_delta(line)
                    if delta is not None:
                        yield delta
        except httpx.HTTPError as exc:
            # No retry here by design — see the module docstring. Bytes may already have
            # reached the client, and ADR-002 forbids recalling released text.
            raise UpstreamError(
                f"stream from provider {target.name!r} failed: {type(exc).__name__}"
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

    async def _post(self, provider: Provider, payload: dict[str, Any]) -> httpx.Response:
        """POST with one retry on a transient failure, then ERR-UP-001 (05 §1.2)."""
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        owns_client = self._client is None
        url = upstream_url(provider)
        headers = auth_headers(provider)
        last: str = "no attempt was made"

        try:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    response = await client.post(url, json=payload, headers=headers)
                except httpx.HTTPError as exc:
                    last = type(exc).__name__
                else:
                    if response.status_code < 400:
                        return response
                    last = f"HTTP {response.status_code}"
                    if response.status_code not in _RETRYABLE_STATUS:
                        break
                # No `if attempt == MAX_ATTEMPTS: break` — `range(1, MAX_ATTEMPTS + 1)`
                # exits on its own, so that guard would be dead code.
            raise UpstreamError(
                f"provider {provider.name!r} failed after {MAX_ATTEMPTS} attempt(s): {last}"
            )
        finally:
            if owns_client:
                await client.aclose()
