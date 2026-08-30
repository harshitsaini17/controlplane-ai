"""Policy store loading, atomic hot-reload and the 05 §2 payloads (FR-CFG-001/002).

Tests work on **copies** of `policies/` in a tmp dir wherever they mutate anything.
The shipped policies are demo-path artifacts (07) and a test that edited them in place
would corrupt the demo to prove a point about reloading.
"""

from __future__ import annotations

import shutil
import warnings
from pathlib import Path

import pytest

from controlplane.policy.store import (
    POLICY_DIR,
    PolicyLoadError,
    PolicyStore,
    PolicyVersionWarning,
    UnknownUseCase,
)

USE_CASES = ("support_bot", "hr_copilot", "finance_advisor")


def mutate(path: Path, old: str, new: str) -> None:
    """Rewrite `old`->`new`, asserting the file actually changed.

    A plain `.replace()` of a key that has drifted is a silent no-op: the test then
    proves nothing while passing. This turns that into a failure at the mutation site,
    naming the stale literal.
    """
    before = path.read_text()
    assert old in before, f"stale test literal {old!r} not present in {path.name}"
    after = before.replace(old, new)
    assert after != before, f"no-op mutation of {path.name}"
    path.write_text(after)


@pytest.fixture
def policy_copy(tmp_path: Path) -> Path:
    """A writable copy of the shipped policies."""
    target = tmp_path / "policies"
    target.mkdir()
    for path in POLICY_DIR.glob("*.yaml"):
        shutil.copy(path, target)
    return target


def test_fr_cfg_001_loads_every_shipped_policy() -> None:
    """The three 01 §3 use cases must load from the real directory."""
    versions = PolicyStore().load()
    assert set(versions) == set(USE_CASES)
    assert all(v >= 1 for v in versions.values())


def test_unknown_use_case_raises_with_the_known_set_named() -> None:
    """FR-GW-003: the gateway maps this to ERR-CFG-001/400 (05 §1.2)."""
    store = PolicyStore()
    store.load()
    with pytest.raises(UnknownUseCase) as excinfo:
        store.get("marketing_bot")
    assert excinfo.value.use_case == "marketing_bot"
    assert set(excinfo.value.known) == set(USE_CASES)


def test_filename_and_use_case_field_must_agree(policy_copy: Path) -> None:
    """Ingress resolves by name (05 §1.1); the engine stamps `use_case` into the audit.

    A disagreement would attribute one pipeline's decisions to another, which is why
    this is a load failure rather than a warning.
    """
    mutate(policy_copy / "hr_copilot.yaml", "use_case: hr_copilot", "use_case: support_bot")
    with pytest.raises(PolicyLoadError, match="misattributes decisions"):
        PolicyStore(policy_copy).load()


def test_invalid_policy_refuses_to_load_with_the_file_named(policy_copy: Path) -> None:
    """FR-CFG-001 says "precise error" — across near-identical files that means named."""
    (policy_copy / "support_bot.yaml").write_text("use_case: support_bot\nnot_a_key: 1\n")
    with pytest.raises(PolicyLoadError, match="support_bot.yaml"):
        PolicyStore(policy_copy).load()


def test_malformed_yaml_is_reported_as_yaml_not_as_a_schema_error(policy_copy: Path) -> None:
    (policy_copy / "support_bot.yaml").write_text("actions: [unclosed\n")
    with pytest.raises(PolicyLoadError, match="invalid YAML"):
        PolicyStore(policy_copy).load()


def test_empty_directory_refuses_to_load(tmp_path: Path) -> None:
    """A gateway with no policies can serve no use case (FR-GW-003)."""
    (tmp_path / "empty").mkdir()
    with pytest.raises(PolicyLoadError, match="no \\*.yaml files"):
        PolicyStore(tmp_path / "empty").load()


def test_duplicate_use_case_across_files_is_refused(policy_copy: Path) -> None:
    """Two files claiming one use case makes `policy_version` ambiguous in the audit."""
    shutil.copy(policy_copy / "support_bot.yaml", policy_copy / "support_bot_v2.yaml")
    with pytest.raises(PolicyLoadError, match="duplicate use_case|filename says"):
        PolicyStore(policy_copy).load()


def test_fr_cfg_002_reload_is_atomic_on_failure(policy_copy: Path) -> None:
    """★ A failed reload must be INERT — the demo edits policy live (07).

    A half-applied reload would leave two use cases new and one old, making
    `policy_version` no longer identify what judged a request.
    """
    store = PolicyStore(policy_copy)
    before = store.load()
    before_actions = store.get("support_bot").resolved_actions

    (policy_copy / "hr_copilot.yaml").write_text("use_case: hr_copilot\nbroken: [\n")
    with pytest.raises(PolicyLoadError):
        store.reload()

    assert store.versions() == before, "the active set changed despite a failed reload"
    assert store.get("support_bot").resolved_actions == before_actions
    assert store.get("hr_copilot").policy_version == before["hr_copilot"]


def test_reload_picks_up_a_valid_change(policy_copy: Path) -> None:
    """FR-CFG-002: behaviour changes with no code change (the policy-as-config thesis)."""
    store = PolicyStore(policy_copy)
    store.load()
    assert store.get("support_bot").policy_version == 3

    mutate(policy_copy / "support_bot.yaml", "policy_version: 3", "policy_version: 7")
    assert store.reload()["support_bot"] == 7
    assert store.get("support_bot").policy_version == 7


def test_content_change_without_a_version_bump_warns(policy_copy: Path) -> None:
    """04 §3: bump on every change, because the version is what the audit stamps.

    A warning, not an error: refusing would block the operator from fixing anything,
    and 07 edits policies live. But it cannot be silent — two records would otherwise
    claim the same policy judged them when it did not.
    """
    store = PolicyStore(policy_copy)
    store.load()
    mutate(policy_copy / "support_bot.yaml", "deep_audit_rate: 0.10", "deep_audit_rate: 0.20")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        store.reload()
    assert any(issubclass(w.category, PolicyVersionWarning) for w in caught), \
        "a silent content change makes policy_version a lie"


def test_version_bump_with_a_content_change_does_not_warn(policy_copy: Path) -> None:
    store = PolicyStore(policy_copy)
    store.load()
    target = policy_copy / "support_bot.yaml"
    mutate(target, "deep_audit_rate: 0.10", "deep_audit_rate: 0.20")
    mutate(target, "policy_version: 3", "policy_version: 4")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        store.reload()
    assert not [w for w in caught if issubclass(w.category, PolicyVersionWarning)]


def test_wildcards_expand_at_load_not_at_first_use() -> None:
    """04 §3: expansion happens at load, so a bad map fails the load, not a request."""
    store = PolicyStore()
    store.load()
    resolved = store.get("support_bot").resolved_actions
    assert resolved, "resolved_actions should be populated after load"
    assert not any(key.endswith(".*") for key in resolved), "wildcards should be expanded"


def test_describe_is_json_safe_and_omits_the_policy_body() -> None:
    """05 §2 `GET /admin/policies` is an inventory, not a config dump."""
    import json

    store = PolicyStore()
    store.load()
    rows = store.describe()
    json.dumps(rows)  # must not raise: enums have to be rendered as values

    assert {row["use_case"] for row in rows} == set(USE_CASES)
    for row in rows:
        assert isinstance(row["risk_appetite"], str)
        assert set(row) == {
            "use_case", "policy_version", "file", "digest", "streaming",
            "risk_appetite", "geography",
        }
        assert "actions" not in row and "messages" not in row


def test_uc3_is_non_streaming_in_the_inventory() -> None:
    """ADR-014: `finance_advisor` is the non-streaming pipeline; 07's beats rely on it."""
    store = PolicyStore()
    store.load()
    modes = {row["use_case"]: row["streaming"] for row in store.describe()}
    assert modes["finance_advisor"] is False
    assert modes["support_bot"] is True
