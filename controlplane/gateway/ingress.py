"""Ingress: use-case resolution, request binding, and the 05 §1.2 error contract.

Implements 02 §4 step t0 and 05 §1.1 header/key resolution; errors per 05 §1.2
(ERR-CFG-001, ERR-CFG-002). Satisfies FR-GW-003 and FR-GW-005.

**Nothing here ever puts request content in an error.** 05 §1.2 ends with "Never include
prompt/response content in error bodies", so `GatewayError.body()` is built from a fixed
triple — code, message, request_id — and cannot be handed the prompt to interpolate. The
error types carry no message the caller supplies either: a caller that could pass text
into `message` is one refactor away from passing the prompt.

**The API-key map is read for its keys and never echoes them.** `config/keys.yaml` is
gitignored (05 §6 calls it "demo keys only"), so it is normally absent; an absent file is
an empty map, not an error, because header-based resolution is the documented primary path
and refusing to boot without a secrets file would block the documented dev path.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from controlplane.policy.schema import Policy
from controlplane.policy.store import PolicyStore, UnknownUseCase

#: 05 §1.1 / §1.2 header vocabulary. Names are the contract — a typo here is a silently
#: unroutable request, so they are constants rather than inline literals.
HEADER_USE_CASE = "X-ControlPlane-Use-Case"
HEADER_CONVERSATION_ID = "X-ControlPlane-Conversation-Id"
HEADER_REQUEST_ID = "X-ControlPlane-Request-Id"
HEADER_ACTIONS = "X-ControlPlane-Actions"

#: 05 §6 names this file; .gitignore excludes it (NFR-SEC-002).
KEYS_PATH = Path(__file__).resolve().parents[2] / "config" / "keys.yaml"

#: 04 §3 `use_case` pattern. Used to decide whether a rejected header value is safe to
#: quote back. `str.isalnum()` was the first attempt and is too permissive: it accepts
#: full-width forms and Arabic-Indic digits, so arbitrary caller text could reach an
#: error string. Matching the documented pattern is both stricter and citable.
_USE_CASE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

#: Body extension per 05 §1.1: source documents that enable `rag_grounding`.
CONTEXT_KEY = "controlplane"


class GatewayError(Exception):
    """Base for the 05 §1.2 error table. Subclasses fix `code` and `http_status`.

    `message` is a class attribute, not a constructor argument, so no caller can route
    request text into an error body (05 §1.2). Subclasses that need detail build it from
    structured, non-content fields.
    """

    code = "ERR-GW-001"
    http_status = 500
    message = "internal gateway error"

    def body(self, request_id: str) -> dict[str, dict[str, str]]:
        """The 05 §1.2 error body: `{error:{code, message, request_id}}` and nothing else."""
        return {"error": {"code": self.code, "message": self.message,
                          "request_id": request_id}}


class UnknownUseCaseError(GatewayError):
    """ERR-CFG-001 / 400 — unknown or unloaded use case (FR-GW-003)."""

    code = "ERR-CFG-001"
    http_status = 400

    def __init__(self, use_case: str | None, known: tuple[str, ...]) -> None:
        self.use_case = use_case
        self.known = known
        # Pipeline ids are repo-public config, not secrets, and naming them turns a
        # 400 into a self-service fix. The *supplied* value is echoed only when it is
        # a syntactically plausible id (below) — never raw arbitrary header text.
        if use_case is None:
            detail = f"missing {HEADER_USE_CASE} header"
        elif _is_plausible_id(use_case):
            detail = f"unknown use case {use_case!r}"
        else:
            detail = f"malformed {HEADER_USE_CASE} header"
        self.message = f"{detail}; loaded pipelines: {', '.join(known) or 'none'}"
        super().__init__(self.message)


class StreamConflictError(GatewayError):
    """ERR-CFG-002 / 400 — request `stream` flag conflicts with the policy's mode."""

    code = "ERR-CFG-002"
    http_status = 400

    def __init__(
        self,
        use_case: str,
        requested: bool | None,
        policy_mode: bool,
        *,
        malformed: bool = False,
    ) -> None:
        self.requested = requested
        self.policy_mode = policy_mode
        configured = f"use case {use_case!r} is configured streaming={_yn(policy_mode)}"
        if malformed:
            # Not a reconciliation failure: coercing a non-bool would produce
            # "asked for stream=true" against "configured streaming=true" — an error
            # message claiming a value conflicts with itself.
            self.message = f"{configured}; `stream` must be a boolean"
        else:
            self.message = f"{configured}; request asked for stream={_yn(requested)}"
        super().__init__(self.message)


class UpstreamError(GatewayError):
    """ERR-UP-001 / 502 — upstream provider failed (after 1 retry). Retryable."""

    code = "ERR-UP-001"
    http_status = 502
    message = "upstream provider failure"


def _yn(value: bool | None) -> str:
    """Render a flag the way the JSON body spelled it, for error messages."""
    return "null" if value is None else str(value).lower()


def _is_plausible_id(value: str) -> bool:
    """Does `value` look like a use-case id (04 §3 pattern) rather than arbitrary text?

    Guards the one place a caller-supplied string reaches an error message. A header of
    500 bytes of prose is reported as "malformed", not quoted back.
    """
    return len(value) <= 64 and _USE_CASE_PATTERN.match(value) is not None


def load_key_map(path: Path | str | None = None) -> dict[str, str]:
    """Load the `config/keys.yaml` api_key -> use_case map (05 §1.1, §6).

    An absent file yields an empty map: the file is gitignored demo config, and the
    header is the primary documented path, so its absence must not be a boot failure.
    A malformed file *is* an error — a silently empty map would make every key-authed
    request look like a missing header instead of a broken config.
    """
    target = Path(path) if path is not None else KEYS_PATH
    if not target.exists():
        return {}
    try:
        raw = yaml.safe_load(target.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{target.name} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{target.name} must be a mapping of api_key -> use_case")

    mapping = raw.get("keys", raw)
    if not isinstance(mapping, dict):
        raise ValueError(f"{target.name}: `keys` must be a mapping of api_key -> use_case")
    out: dict[str, str] = {}
    for key, use_case in mapping.items():
        if not isinstance(use_case, str):
            # The key itself is NEVER interpolated into the error (NFR-SEC-002).
            raise ValueError(f"{target.name}: every api_key must map to a use_case string")
        out[str(key)] = use_case
    return out


def _bearer(headers: dict[str, str]) -> str | None:
    """Extract the presented API key from an Authorization header, if any."""
    raw = headers.get("authorization") or headers.get("Authorization")
    if not raw:
        return None
    parts = raw.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return raw.strip()


def resolve_use_case(
    headers: dict[str, str],
    *,
    known: tuple[str, ...],
    key_map: dict[str, str] | None = None,
) -> str:
    """Resolve the pipeline id from headers (05 §1.1). Raises `UnknownUseCaseError`.

    Header wins over the key map when both are present, because the header is the
    explicit per-request statement while the key is an ambient default. A header naming
    a use case the key does not authorise is still resolved here — v1 has no authz
    (05 §2 states that limitation); this is routing, not authorisation, and pretending
    otherwise would imply a guarantee the system does not make.
    """
    lowered = {name.lower(): value for name, value in headers.items()}
    supplied = lowered.get(HEADER_USE_CASE.lower())
    if supplied is not None:
        supplied = supplied.strip()

    if not supplied:
        presented = _bearer(headers)
        mapped = (key_map or {}).get(presented) if presented else None
        if mapped is None:
            raise UnknownUseCaseError(None, known)
        supplied = mapped

    if supplied not in known:
        raise UnknownUseCaseError(supplied, known)
    return supplied


def resolve_stream_flag(body: dict[str, Any], policy: Policy) -> bool:
    """Reconcile the request's `stream` flag with the policy's mode (05 §1.1).

    Absent flag → the policy's mode. Present and disagreeing → ERR-CFG-002, in *either*
    direction: the policy owns the interception mode (ADR-014 ties `consistency: on` to
    non-streaming), and honouring a client's downgrade would make `stage_summary` stop
    matching the configured pipeline. Logged as a resolved ambiguity in docs/08.
    """
    requested = body.get("stream")
    if requested is None:
        return policy.streaming
    if not isinstance(requested, bool):
        raise StreamConflictError(
            policy.use_case, None, policy.streaming, malformed=True
        )
    if requested != policy.streaming:
        raise StreamConflictError(policy.use_case, requested, policy.streaming)
    return requested


def extract_context_docs(body: dict[str, Any]) -> list[str]:
    """`controlplane.context: [str]` per 05 §1.1 — source docs enabling `rag_grounding`."""
    block = body.get(CONTEXT_KEY)
    if not isinstance(block, dict):
        return []
    docs = block.get("context")
    if not isinstance(docs, list):
        return []
    return [doc for doc in docs if isinstance(doc, str)]


@dataclass
class ResolvedRequest:
    """Everything the lanes need, resolved once at t0 (02 §4).

    Carries the `Policy` object itself rather than a use-case name so no downstream
    stage can re-resolve and get a *different* version mid-request after a hot reload
    (FR-CFG-002). The version that judged the request is the one bound here.
    """

    request_id: str
    use_case: str
    policy: Policy
    stream: bool
    messages: list[dict[str, Any]] = field(default_factory=list)
    conversation_id: str | None = None
    context_docs: list[str] = field(default_factory=list)

    @property
    def policy_version(self) -> int:
        return self.policy.policy_version


def ingest(
    headers: dict[str, str],
    body: dict[str, Any],
    store: PolicyStore,
    *,
    key_map: dict[str, str] | None = None,
    request_id: str | None = None,
) -> ResolvedRequest:
    """Bind a request to its policy (02 §4 t0). Raises `GatewayError` subclasses only.

    Ordering is deliberate: the use case resolves *before* the stream flag is checked,
    because ERR-CFG-002 is defined relative to a policy — without one there is nothing
    for the flag to conflict with, and reporting a stream conflict for an unknown
    pipeline would send the caller to fix the wrong thing.
    """
    known = store.use_cases  # a property: already sorted
    use_case = resolve_use_case(headers, known=known, key_map=key_map)
    try:
        policy = store.get(use_case)
    except UnknownUseCase as exc:  # lost a race with a reload that dropped it
        raise UnknownUseCaseError(use_case, tuple(sorted(exc.known))) from exc

    lowered = {name.lower(): value for name, value in headers.items()}
    conversation_id = lowered.get(HEADER_CONVERSATION_ID.lower())
    messages = body.get("messages")

    return ResolvedRequest(
        request_id=request_id or str(uuid.uuid4()),
        use_case=use_case,
        policy=policy,
        stream=resolve_stream_flag(body, policy),
        messages=messages if isinstance(messages, list) else [],
        conversation_id=conversation_id.strip() if conversation_id else None,
        context_docs=extract_context_docs(body),
    )
