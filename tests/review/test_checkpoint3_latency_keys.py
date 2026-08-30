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
    while `added_time_to_last_byte_ms` appears there only to say it is **not a key of this
    column** — so parsing every name out of it would be wrong in both directions at once.
    What *is* derived is the re-siting itself, asserted against the code in
    `test_the_last_byte_quantity_is_sited_where_the_vantage_exists` below.
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


def test_the_last_byte_quantity_is_sited_where_the_vantage_exists() -> None:
    """★ **This test fired on 2026-08-28 and was re-pointed — the second time.**

    Its previous premise was that `added_time_to_last_byte_ms` was documented-but-pending:
    a transition state, asserted as `doc_says_absent == code_says_absent` so that emitting
    the key would fail here until 05 §5 changed with it. **ADR-030 Amendment 1 voided that
    premise** rather than resolving it — the key is not a `latency_json` key at all now, so
    "not yet emitted" is no longer a state the doc can be in, and a test asserting that
    sentence exists would demand prose the ruling removed.

    Re-pointed, not deleted, for the reason ADR-031 consequence 5 gives: the tripwire's job
    survives the transition it detected. Its job now is that the re-siting holds on **both**
    sides and in **both** directions — the enforced vocabulary must not grow the key back
    (that would restore a row whose label promises a vantage the writer lacks), and 06 §4
    must keep defining it (silently dropping it would withdraw a published figure, which the
    amendment explicitly does not do).
    """
    from controlplane.telemetry import spans

    doc_05_says_not_a_key = (
        "`added_time_to_last_byte_ms` is **not a key of this column at all**"
        in _emission_paragraph()
    )
    code_says_not_a_key = "added_time_to_last_byte_ms" not in spans.LATENCY_KEYS
    assert doc_05_says_not_a_key == code_says_not_a_key, (
        f"05 §5 says added_time_to_last_byte_ms is not a latency_json key="
        f"{doc_05_says_not_a_key}, but spans.LATENCY_KEYS says={code_says_not_a_key} — "
        "ADR-030 Amendment 1's re-siting moved on one side only"
    )

    # Re-sited, NOT withdrawn: 06 §4 must still define it, and as a client quantity.
    doc_06 = (ROOT / "docs" / "06-evaluation-plan.md").read_text()
    assert "`added_time_to_last_byte_ms`" in doc_06, (
        "the amendment re-sites this figure into 06 §4; it must not vanish from publication"
    )
    assert "**A benchmark-client quantity, defined here and NOT a `latency_json` key**" in doc_06

    # And the rename's own half stays the opposite state, in the same enforced set.
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
