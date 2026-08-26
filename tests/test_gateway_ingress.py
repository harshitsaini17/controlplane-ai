"""Ingress: use-case resolution (FR-GW-003), threading (FR-GW-005), 05 §1.2 errors.

The leak tests here are the load-bearing ones. 05 §1.2 ends "Never include
prompt/response content in error bodies", and ingress is the one layer that sees the raw
prompt *and* emits 400s, so it is where that rule can most easily be broken.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from controlplane.gateway.ingress import (
    HEADER_CONVERSATION_ID,
    HEADER_USE_CASE,
    GatewayError,
    ResolvedRequest,
    StreamConflictError,
    UnknownUseCaseError,
    extract_context_docs,
    ingest,
    load_key_map,
    resolve_stream_flag,
    resolve_use_case,
)
from controlplane.policy.store import PolicyStore

#: A prompt carrying a marker plus PII shapes. If any of this reaches an error body,
#: the 05 §1.2 rule is broken and the audit/report surface inherits the leak.
SECRET_PROMPT = "CANARY-7f3a my ssn is 001-01-0001 and email a.b@example.com"
CANARY = "CANARY-7f3a"


@pytest.fixture(scope="module")
def store() -> PolicyStore:
    loaded = PolicyStore()
    loaded.load()
    return loaded


@pytest.fixture(scope="module")
def known(store: PolicyStore) -> tuple[str, ...]:
    return store.use_cases


def body(**kwargs) -> dict:
    return {"messages": [{"role": "user", "content": SECRET_PROMPT}], **kwargs}


# --------------------------------------------------------------------------
# FR-GW-003 — every request is tagged with a use case
# --------------------------------------------------------------------------


def test_fr_gw_003_header_resolves_a_loaded_pipeline(store: PolicyStore) -> None:
    resolved = ingest({HEADER_USE_CASE: "support_bot"}, body(), store)
    assert resolved.use_case == "support_bot"
    assert resolved.policy.use_case == "support_bot"
    assert resolved.policy_version == resolved.policy.policy_version
    assert resolved.request_id


def test_fr_gw_003_unknown_use_case_is_err_cfg_001_at_400(store: PolicyStore) -> None:
    with pytest.raises(UnknownUseCaseError) as excinfo:
        ingest({HEADER_USE_CASE: "marketing_bot"}, body(), store)
    assert (excinfo.value.code, excinfo.value.http_status) == ("ERR-CFG-001", 400)


def test_fr_gw_003_missing_header_is_rejected_not_defaulted(store: PolicyStore) -> None:
    """★ There is no default pipeline: an unrouted request must not silently get one.

    Defaulting would mean a request judged by a policy nobody chose for it — the exact
    opposite of the per-use-case thesis.
    """
    with pytest.raises(UnknownUseCaseError) as excinfo:
        ingest({}, body(), store)
    assert excinfo.value.use_case is None
    assert "missing" in str(excinfo.value)


def test_header_case_is_insensitive(store: PolicyStore) -> None:
    """HTTP header names are case-insensitive; ASGI lowercases them."""
    assert ingest({"x-controlplane-use-case": "hr_copilot"}, body(), store).use_case \
        == "hr_copilot"


def test_whitespace_only_header_is_treated_as_missing(store: PolicyStore, known) -> None:
    with pytest.raises(UnknownUseCaseError) as excinfo:
        resolve_use_case({HEADER_USE_CASE: "   "}, known=known)
    assert excinfo.value.use_case is None


def test_error_names_the_loaded_pipelines(store: PolicyStore, known) -> None:
    """Pipeline ids are repo-public config; naming them makes a 400 self-service."""
    with pytest.raises(UnknownUseCaseError) as excinfo:
        resolve_use_case({HEADER_USE_CASE: "nope"}, known=known)
    for use_case in known:
        assert use_case in str(excinfo.value)


# --------------------------------------------------------------------------
# 05 §1.2 — errors never carry request content
# --------------------------------------------------------------------------


def test_05_1_2_no_error_body_contains_prompt_content(store: PolicyStore) -> None:
    """★ Every reachable ingress error, checked against one canary prompt."""
    attempts = [
        ({}, body()),                                            # missing header
        ({HEADER_USE_CASE: "marketing_bot"}, body()),            # unknown
        ({HEADER_USE_CASE: SECRET_PROMPT}, body()),              # prompt AS the header
        ({HEADER_USE_CASE: "support_bot"}, body(stream=False)),  # stream conflict
        ({HEADER_USE_CASE: "support_bot"}, body(stream="yes")),  # malformed flag
    ]
    raised = 0
    for headers, payload in attempts:
        try:
            ingest(headers, payload, store)
        except GatewayError as exc:
            raised += 1
            rendered = repr(exc.body("req-1"))
            assert CANARY not in rendered
            assert "001-01-0001" not in rendered
            assert "a.b@example.com" not in rendered
    assert raised == len(attempts), "an attempt did not raise; the check proved nothing"


def test_a_malformed_header_is_not_quoted_back(store: PolicyStore, known) -> None:
    """An arbitrary header value must not become error-body text (05 §1.2)."""
    with pytest.raises(UnknownUseCaseError) as excinfo:
        resolve_use_case({HEADER_USE_CASE: SECRET_PROMPT}, known=known)
    assert "malformed" in str(excinfo.value)
    assert CANARY not in str(excinfo.value)


def test_error_body_has_exactly_the_documented_shape(store: PolicyStore, known) -> None:
    """05 §1.2: `{error:{code, message, request_id}}` — no extra keys to leak through."""
    try:
        resolve_use_case({}, known=known)
    except UnknownUseCaseError as exc:
        rendered = exc.body("req-42")
    assert set(rendered) == {"error"}
    assert set(rendered["error"]) == {"code", "message", "request_id"}
    assert rendered["error"]["request_id"] == "req-42"


# --------------------------------------------------------------------------
# 05 §1.1 — API-key map
# --------------------------------------------------------------------------


def test_absent_keys_file_is_an_empty_map_not_a_failure(tmp_path: Path) -> None:
    """`config/keys.yaml` is gitignored demo config; the header is the primary path."""
    assert load_key_map(tmp_path / "nope.yaml") == {}


def test_key_map_resolves_when_no_header_is_present(known) -> None:
    key_map = {"demo-key-1": "finance_advisor"}
    headers = {"Authorization": "Bearer demo-key-1"}
    assert resolve_use_case(headers, known=known, key_map=key_map) == "finance_advisor"


def test_header_wins_over_the_key_map(known) -> None:
    """The header is an explicit per-request statement; the key is an ambient default."""
    headers = {"Authorization": "Bearer demo-key-1", HEADER_USE_CASE: "hr_copilot"}
    resolved = resolve_use_case(headers, known=known,
                                key_map={"demo-key-1": "finance_advisor"})
    assert resolved == "hr_copilot"


def test_an_unrecognised_key_is_err_cfg_001_not_a_500(known) -> None:
    with pytest.raises(UnknownUseCaseError):
        resolve_use_case({"Authorization": "Bearer unknown"}, known=known, key_map={})


def test_key_map_pointing_at_an_unloaded_use_case_is_rejected(known) -> None:
    """A stale key map must not route to a pipeline that is not loaded (FR-GW-003)."""
    with pytest.raises(UnknownUseCaseError) as excinfo:
        resolve_use_case({"Authorization": "Bearer k"}, known=known,
                         key_map={"k": "retired_bot"})
    assert excinfo.value.use_case == "retired_bot"


def test_nfr_sec_002_a_malformed_key_map_never_echoes_the_key(tmp_path: Path) -> None:
    """★ The error must name the file, never the credential it contains."""
    path = tmp_path / "keys.yaml"
    path.write_text("keys:\n  super-secret-key-abc: 12345\n")
    with pytest.raises(ValueError) as excinfo:
        load_key_map(path)
    assert "super-secret-key-abc" not in str(excinfo.value)
    assert "keys.yaml" in str(excinfo.value)


def test_malformed_yaml_in_the_key_map_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "keys.yaml"
    path.write_text("keys: [unclosed\n")
    with pytest.raises(ValueError, match="not valid YAML"):
        load_key_map(path)


def test_key_map_accepts_a_bare_mapping_or_a_keys_block(tmp_path: Path) -> None:
    bare = tmp_path / "bare.yaml"
    bare.write_text("demo-1: support_bot\n")
    nested = tmp_path / "nested.yaml"
    nested.write_text("keys:\n  demo-1: support_bot\n")
    assert load_key_map(bare) == load_key_map(nested) == {"demo-1": "support_bot"}


# --------------------------------------------------------------------------
# 05 §1.1 — stream flag vs policy mode (ERR-CFG-002)
# --------------------------------------------------------------------------


def test_absent_stream_flag_adopts_the_policy_mode(store: PolicyStore) -> None:
    assert ingest({HEADER_USE_CASE: "support_bot"}, body(), store).stream is True
    assert ingest({HEADER_USE_CASE: "finance_advisor"}, body(), store).stream is False


@pytest.mark.parametrize("use_case,requested", [
    ("support_bot", False),       # streaming pipeline, client asks not to stream
    ("finance_advisor", True),    # ADR-014 non-streaming pipeline, client asks to stream
])
def test_err_cfg_002_fires_in_both_directions(store: PolicyStore, use_case, requested) -> None:
    """★ The policy owns the interception mode, so a downgrade is a conflict too.

    ADR-014 ties `consistency: on` to `streaming: false`; honouring a client's request
    to stream UC-3 would run a pipeline the policy does not describe.
    """
    with pytest.raises(StreamConflictError) as excinfo:
        ingest({HEADER_USE_CASE: use_case}, body(stream=requested), store)
    assert (excinfo.value.code, excinfo.value.http_status) == ("ERR-CFG-002", 400)


def test_a_non_boolean_stream_flag_does_not_claim_true_conflicts_with_true(
    store: PolicyStore,
) -> None:
    """`bool("yes")` is True, so coercing would emit a message conflicting with itself."""
    with pytest.raises(StreamConflictError) as excinfo:
        resolve_stream_flag({"stream": "yes"}, store.get("support_bot"))
    message = str(excinfo.value)
    assert "must be a boolean" in message
    assert "asked for stream=true" not in message


# --------------------------------------------------------------------------
# FR-GW-005 / 05 §1.1 body extensions
# --------------------------------------------------------------------------


def test_fr_gw_005_conversation_id_is_threaded_through(store: PolicyStore) -> None:
    resolved = ingest(
        {HEADER_USE_CASE: "support_bot", HEADER_CONVERSATION_ID: " conv-9 "}, body(), store
    )
    assert resolved.conversation_id == "conv-9"


def test_conversation_id_is_none_when_absent(store: PolicyStore) -> None:
    """None and empty string differ in the audit: absent vs "a conversation called ''"."""
    assert ingest({HEADER_USE_CASE: "support_bot"}, body(), store).conversation_id is None


def test_context_docs_enable_rag_grounding(store: PolicyStore) -> None:
    payload = body(controlplane={"context": ["doc one", "doc two", 7]})
    assert ingest({HEADER_USE_CASE: "support_bot"}, payload, store).context_docs \
        == ["doc one", "doc two"]


@pytest.mark.parametrize("payload", [
    {}, {"controlplane": None}, {"controlplane": {}}, {"controlplane": {"context": "no"}},
])
def test_absent_or_malformed_context_is_an_empty_list(payload) -> None:
    assert extract_context_docs(payload) == []


# --------------------------------------------------------------------------
# Binding
# --------------------------------------------------------------------------


def test_the_bound_policy_object_survives_a_later_reload(store: PolicyStore) -> None:
    """★ FR-CFG-002: the version that judged a request is the one bound at t0.

    Re-resolving downstream could pick up a hot-reloaded version mid-request, making
    `policy_version` in the audit fail to identify what actually decided.
    """
    resolved = ingest({HEADER_USE_CASE: "support_bot"}, body(), store)
    bound = resolved.policy
    store.reload()
    assert resolved.policy is bound


def test_missing_messages_is_an_empty_list_not_a_crash(store: PolicyStore) -> None:
    """Upstream validates the OpenAI body; ingress must not 500 before it gets there."""
    assert ingest({HEADER_USE_CASE: "support_bot"}, {}, store).messages == []


def test_request_id_is_accepted_or_minted(store: PolicyStore) -> None:
    supplied = ingest({HEADER_USE_CASE: "support_bot"}, body(), store, request_id="req-x")
    assert supplied.request_id == "req-x"
    minted = ingest({HEADER_USE_CASE: "support_bot"}, body(), store)
    assert minted.request_id and minted.request_id != "req-x"


def test_resolved_request_carries_no_verdict_surface() -> None:
    """Ingress binds and validates; it never decides. A verdict field would invite that."""
    assert not {"verdict", "action", "signals"} & set(ResolvedRequest.__dataclass_fields__)
