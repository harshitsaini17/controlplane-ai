"""Checkpoint 3 tripwire for the documented current latency_json key names."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from controlplane import policy as policy_package
from controlplane.audit.db import init_db
from controlplane.audit.records import AuditRecord, write_record
from controlplane.policy.schema import TAXONOMY, Action, Policy
from eval import policy_matrix as pm
from tests.test_policy_matrix import CASES, POLICIES, mismatch_total


ROOT = Path(__file__).resolve().parents[2]
DOC_05 = ROOT / "docs" / "05-api-and-data-contracts.md"


def _documented_current_keys() -> set[str]:
    """Read the current-emission statement, not ADR-030's deferred vocabulary."""
    text = DOC_05.read_text()
    paragraph = next(
        p for p in text.split("\n\n")
        if "ADR-030 renamed that key" in p and "not yet emitted" in p
    )
    rename = "`gateway_overhead_ms` → `total_attributable_overhead_ms`"
    assert rename in paragraph, "05 §5 must state the current-to-deferred key rename"
    return {"gateway_overhead_ms", "upstream_ms", "input_hold_ms", "sentence_holds_ms"}


def test_documented_current_latency_keys_round_trip_through_a_real_audit_write(tmp_path) -> None:
    """M-20: a rename must fail here instead of silently drifting from persisted rows."""
    keys = _documented_current_keys()
    values = {key: [0.3, 0.4] if key == "sentence_holds_ms" else 0.2 for key in keys}
    conn = init_db(tmp_path / "audit.db")
    try:
        write_record(
            conn,
            AuditRecord(
                request_id="checkpoint3-latency-keys",
                use_case="support_bot",
                policy_version=1,
                verdict=Action.PASS,
                stage_summary="completed",
                latency_json=json.dumps(values),
            ),
        )
        stored = json.loads(
            conn.execute(
                "SELECT latency_json FROM audit_records WHERE request_id = ?",
                ("checkpoint3-latency-keys",),
            ).fetchone()[0]
        )
    finally:
        conn.close()

    assert set(stored) == keys


def test_mutation_wildcard_beats_specific_is_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reviewer mutant 1: reverse specific > wildcard precedence."""
    original = Policy.action_for

    def wildcard_first(self: Policy, label: str) -> Action:
        prefix = label.split(".", 1)[0] + ".*"
        return self.actions.get(prefix, original(self, label))

    monkeypatch.setattr(Policy, "action_for", wildcard_first)
    assert mismatch_total() > 0


def test_mutation_default_beats_wildcard_is_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reviewer mutant 2: erase wildcard-only resolutions back to default."""
    original = Policy.action_for
    wildcard_only = {
        label
        for policy in POLICIES.values()
        for label in TAXONOMY
        if label not in policy.actions
        and any(
            key.endswith(".*") and label.startswith(key[:-1])
            for key in policy.actions
        )
    }

    def default_first(self: Policy, label: str) -> Action:
        return self.default_action if label in wildcard_only else original(self, label)

    monkeypatch.setattr(Policy, "action_for", default_first)
    assert mismatch_total() > 0
