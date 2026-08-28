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


def _emission_paragraph() -> str:
    """05 §5's statement of which `latency_json` keys the code actually writes today."""
    text = DOC_05.read_text()
    return next(
        p for p in text.split("\n\n")
        if "ADR-030 renamed that key" in p and "emitted" in p
    )


def _documented_current_keys() -> set[str]:
    """The keys 05 §5 says are emitted **now** — not ADR-030's full vocabulary.

    **This helper fired on 2026-08-28 and was re-pointed, which is the outcome it exists
    for.** It previously returned `gateway_overhead_ms`; the M-20 rename landed, the write
    path now carries `total_attributable_overhead_ms`, and this test failed rather than
    letting the code drift from the persisted rows. Re-pointing it is the documented
    workflow, and the set below still trails the doc rather than leading it.

    The set stays explicit instead of being scraped from the paragraph, because the
    paragraph is prose about a transition and does not enumerate the emitted keys:
    `upstream_ms` never appears in it (it predates ADR-030 and was never in question),
    while `added_time_to_last_byte_ms` does appear and is **not** emitted — so parsing
    every name out of it would be wrong in both directions at once. What *is* derived is
    the transition state itself, asserted against the code in `test_the_last_m20_key_is_
    still_absent_from_the_enforced_vocabulary` below.
    """
    paragraph = _emission_paragraph()
    rename = "`gateway_overhead_ms` → `total_attributable_overhead_ms`"
    assert rename in paragraph, "05 §5 must still record what the key was renamed from"
    assert "The **rename is emitted**" in paragraph, (
        "05 §5 no longer states the rename as emitted — if it was reverted, revert this set too"
    )
    return {
        "total_attributable_overhead_ms",
        "upstream_ms",
        "input_hold_ms",
        "sentence_holds_ms",
    }


def test_the_last_m20_key_is_still_absent_from_the_enforced_vocabulary() -> None:
    """The other half of M-20, kept tripwired the same way the rename was.

    `added_time_to_last_byte_ms` is documented by ADR-030 and 05 §3 but is still not
    written, so it is deliberately absent from `check_latency_keys`' enforced set. This
    asserts the doc's claim and the code agree **in both directions**: when that key lands,
    this test fails and points at the sentence in 05 §5 that has to change with it.
    """
    from controlplane.telemetry import spans

    paragraph = _emission_paragraph()
    doc_says_absent = "`added_time_to_last_byte_ms` is **still not emitted**" in paragraph
    code_says_absent = "added_time_to_last_byte_ms" not in spans.LATENCY_KEYS
    assert doc_says_absent == code_says_absent, (
        f"05 §5 says added_time_to_last_byte_ms is unemitted={doc_says_absent}, but "
        f"spans.LATENCY_KEYS says unemitted={code_says_absent} — M-20's remaining half "
        "moved on one side only"
    )
    # And the rename's own half is now the opposite state, in the same enforced set.
    assert "total_attributable_overhead_ms" in spans.LATENCY_EXTRA_KEYS
    assert "gateway_overhead_ms" not in spans.LATENCY_KEYS


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
