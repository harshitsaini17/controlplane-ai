"""Audit writer: 05 §3 columns, 05 §4 canonical view, append-only, NFR-SEC-001.

The leak tests are the point of this file. Every upstream layer already refuses raw
values, so these assert the *last* line of defence — the one that matters most because
`audit_records` is the artifact that persists: a leak in a log line scrolls away, a leak
in the audit DB is still there when a report reads it.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from controlplane.audit.db import init_db
from controlplane.audit.records import (
    AuditRecord,
    AuditWriteError,
    PiiLeakError,
    canonical_view,
    serialize_actions,
    serialize_failures,
    serialize_signals,
    write_record,
)
from controlplane.detectors.base import Plane, ScoreKind, Signal, Span, Stage
from controlplane.policy.actions import AppliedEdit
from controlplane.policy.engine import DetectorFailureRecord, evaluate, resolve_failure
from controlplane.policy.schema import Action, Policy
from controlplane.telemetry import spans

POLICY_DIR = Path(__file__).resolve().parents[1] / "policies"


@pytest.fixture
def conn():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        connection = init_db(Path(tmp) / "audit.db")
        yield connection
        connection.close()


@pytest.fixture
def uc3() -> Policy:
    return Policy(**yaml.safe_load((POLICY_DIR / "finance_advisor.yaml").read_text()))


def pii_signal(label: str = "pii.ssn") -> Signal:
    return Signal(
        detector="tier1_pii",
        planes=[Plane.RESPONSIBILITY],
        labels=[label],
        score=1.0,
        score_kind=ScoreKind.DETECTION,
        span=Span(start=4, end=15),
        stage=Stage.INPUT,
        evidence="category:ssn pattern=nnn-nn-nnnn",
        latency_ms=1.1,
    )


def base_record(**kwargs) -> AuditRecord:
    defaults = dict(
        request_id="req-1",
        use_case="finance_advisor",
        policy_version=3,
        verdict=Action.PASS,
        stage_summary="completed",
    )
    return AuditRecord(**{**defaults, **kwargs})


# --------------------------------------------------------------------------
# FR-AUD-001 — one append-only record per request
# --------------------------------------------------------------------------


def test_fr_aud_001_writes_one_record_readable_as_the_05_4_view(conn) -> None:
    write_record(conn, base_record(
        signals_json=serialize_signals([pii_signal()]),
        tier_requested="small",
        model_used="llama-3.1-8b-instant",
        upstream_class="measured",
        tokens_in=812,
        tokens_out=344,
        est_cost_usd=0.0041,
        latency_json=json.dumps({spans.INGRESS: 1.0, "gateway_overhead_ms": 46.1,
                                 "upstream_ms": 1240.0}),
    ))
    view = canonical_view(conn, "req-1")

    # The 05 §4 nesting, not the flat columns.
    assert view["model"] == {"tier_requested": "small", "used": "llama-3.1-8b-instant",
                            "upstream_class": "measured", "cascade_escalated": False}
    assert view["cost"] == {"tokens_in": 812, "tokens_out": 344, "est_usd": 0.0041}
    assert view["latency"]["gateway_overhead_ms"] == 46.1
    assert view["signals"][0]["labels"] == ["pii.ssn"]
    assert "override" not in view, "an absent override must not render as a null decision"


def test_append_only_a_duplicate_request_id_is_refused(conn) -> None:
    """★ 05 §3 is append-only. `INSERT OR REPLACE` would make the log rewritable."""
    write_record(conn, base_record())
    with pytest.raises(AuditWriteError, match="append-only"):
        write_record(conn, base_record(verdict=Action.BLOCK))
    row = conn.execute("SELECT verdict FROM audit_records WHERE request_id='req-1'").fetchone()
    assert row["verdict"] == "pass", "the original row was overwritten"


def test_no_executed_statement_can_rewrite_a_row() -> None:
    """Append-only is this module's discipline; an update path would undo it.

    Inspects the SQL actually passed to `execute*` via the AST rather than grepping the
    source, so a docstring explaining why `INSERT OR REPLACE` is *not* used cannot fail
    the test — the earlier version of this check did exactly that.
    """
    import ast

    import controlplane.audit.records as module

    tree = ast.parse(Path(module.__file__).read_text())
    statements = [
        node.args[0].value.upper()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"execute", "executemany", "executescript"}
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]
    assert statements, "no literal SQL found — the AST probe has drifted"
    for sql in statements:
        assert "OR REPLACE" not in sql
        assert "UPDATE AUDIT_RECORDS" not in sql
        assert "DELETE FROM AUDIT_RECORDS" not in sql


# --------------------------------------------------------------------------
# NFR-SEC-001 — the write path is the last line of defence
# --------------------------------------------------------------------------


@pytest.mark.parametrize("leak", [
    "matched 001-01-0001 in the prompt",
    "found a.b@example.com",
    "card 4111111111111111",
])
def test_nfr_sec_001_raw_values_are_refused_at_the_write_path(leak: str) -> None:
    with pytest.raises(PiiLeakError, match="never the value"):
        serialize_actions(notes=(leak,))


def test_nfr_sec_001_a_leaking_record_is_not_written(conn) -> None:
    """The row must be absent, not present-and-redacted: refusal beats repair."""
    with pytest.raises(PiiLeakError):
        write_record(conn, base_record(
            actions_json=json.dumps({"notes": ["ssn 001-01-0001"]})
        ))
    assert conn.execute("SELECT COUNT(*) c FROM audit_records").fetchone()["c"] == 0


def test_legitimate_edit_metadata_passes_the_tripwire() -> None:
    """Category + span + stage is exactly what 05 §3 asks for — it must not false-positive."""
    payload = serialize_actions(input_redactions=[AppliedEdit(
        transform="redact", label="pii.ssn", category="ssn",
        stage=Stage.INPUT, span=(4, 15),
    )])
    parsed = json.loads(payload)["input_redactions"][0]
    assert parsed == {"transform": "redact", "label": "pii.ssn", "category": "ssn",
                      "stage": "input", "span": [4, 15], "whole_sentence": False}


def test_integer_spans_do_not_trip_the_digit_tripwire() -> None:
    """A span offset is an int, not a string; scanning ints would false-positive."""
    serialize_actions(applied=[AppliedEdit(
        transform="redact", label="pii.email", category="email",
        stage=Stage.OUTPUT_SENTENCE, span=(1234567, 1234599),
    )])


# --------------------------------------------------------------------------
# ADR-020 — prompt as received vs prompt as sent
# --------------------------------------------------------------------------


def test_adr020_input_redactions_are_recorded_separately_from_output_edits() -> None:
    """05 §3: the record distinguishes the two stages while storing neither verbatim."""
    payload = json.loads(serialize_actions(
        applied=[AppliedEdit("soften", "hallucination.low_confidence", "low_confidence",
                             Stage.OUTPUT_SENTENCE, None, whole_sentence=True)],
        input_redactions=[AppliedEdit("redact", "pii.email", "email", Stage.INPUT, (0, 15))],
    ))
    assert payload["input_redactions"][0]["stage"] == "input"
    assert payload["applied"][0]["stage"] == "output_sentence"
    assert all("value" not in row and "text" not in row
               for row in payload["applied"] + payload["input_redactions"])


# --------------------------------------------------------------------------
# ADR-027 — failures are a separate column from signals
# --------------------------------------------------------------------------


def test_adr027_failures_are_written_to_their_own_column(conn, uc3: Policy) -> None:
    """★ An ESCALATE with zero content signals must be self-explaining in the audit."""
    record = DetectorFailureRecord(detector="tier1_pii", error_class="DetectorTimeout",
                                   stage=Stage.INPUT)
    verdict = evaluate([], uc3, failures=[record])
    write_record(conn, AuditRecord.from_verdict(
        request_id="req-esc", verdict=verdict, stage_summary="input",
    ))
    view = canonical_view(conn, "req-esc")

    assert view["verdict"] == "escalate"
    assert view["signals"] == []
    entry = view["detector_failures"][0]
    assert entry["fail_mode_applied"] == "fail_closed"
    assert entry["detector"] == "tier1_pii"
    assert entry["failure_id"] == record.failure_id


def test_adr027_fail_open_faults_are_still_recorded(conn) -> None:
    """A dropped detector that left no trace is indistinguishable from one that found nothing."""
    uc1 = Policy(**yaml.safe_load((POLICY_DIR / "support_bot.yaml").read_text()))
    record = DetectorFailureRecord(detector="tier2_toxicity", error_class="DetectorError")
    verdict = evaluate([], uc1, failures=[record])
    write_record(conn, AuditRecord.from_verdict(
        request_id="req-open", verdict=verdict, stage_summary="completed",
    ))
    view = canonical_view(conn, "req-open")
    assert view["verdict"] == "pass"
    assert len(view["detector_failures"]) == 1


def test_signals_column_takes_only_signals() -> None:
    """`signals_json` stays pure Signals (ADR-027) so risk counts need no filtering."""
    outcome = resolve_failure(
        DetectorFailureRecord(detector="tier1_pii", error_class="DetectorTimeout"),
        Policy(**yaml.safe_load((POLICY_DIR / "finance_advisor.yaml").read_text())),
    )
    with pytest.raises(AuditWriteError, match="detector_failures_json"):
        serialize_signals([outcome])
    with pytest.raises(AuditWriteError, match="FailureOutcome"):
        serialize_failures([pii_signal()])


def test_from_verdict_stamps_both_id_lists(uc3: Policy) -> None:
    """04 §4.3 step 5 as amended by ADR-027."""
    record = DetectorFailureRecord(detector="tier1_pii", error_class="DetectorTimeout")
    verdict = evaluate([], uc3, failures=[record])
    built = AuditRecord.from_verdict(request_id="r", verdict=verdict, stage_summary="input")
    assert built.failure_record_ids == (record.failure_id,)
    assert built.contributing_signal_ids == ()
    assert built.use_case == uc3.use_case and built.policy_version == uc3.policy_version


# --------------------------------------------------------------------------
# Vocabulary + ADR-022 null cost
# --------------------------------------------------------------------------


@pytest.mark.parametrize("field,value,match", [
    ("stage_summary", "streaming", "stage_summary"),
    ("tier_requested", "llama-3.1-8b-instant", "never a concrete model id"),
    ("upstream_class", "local", "upstream_class"),
    ("verdict", "allow", "04 §4.2 vocabulary"),
])
def test_column_vocabularies_are_enforced(conn, field: str, value: str, match: str) -> None:
    with pytest.raises(AuditWriteError, match=match):
        write_record(conn, base_record(**{field: value}))


def test_unknown_latency_key_is_an_audit_write_error(conn) -> None:
    """One exception type at the write path, or a caller must catch two."""
    with pytest.raises(AuditWriteError, match="05 §5 span vocabulary"):
        write_record(conn, base_record(latency_json=json.dumps({"cp.ingres": 1.0})))


def test_adr022_missing_price_stays_null_and_is_never_coerced_to_zero(conn) -> None:
    """★ ADR-022: zero and unknown are different facts and the schema keeps them apart."""
    write_record(conn, base_record(request_id="unpriced", est_cost_usd=None,
                                   model_used="some-unpriced-model"))
    assert canonical_view(conn, "unpriced")["cost"]["est_usd"] is None

    write_record(conn, base_record(request_id="free", est_cost_usd=0.0))
    assert canonical_view(conn, "free")["cost"]["est_usd"] == 0.0


def test_negative_cost_is_refused(conn) -> None:
    with pytest.raises(AuditWriteError, match="negative"):
        write_record(conn, base_record(est_cost_usd=-0.01))


def test_missing_record_raises_keyerror(conn) -> None:
    with pytest.raises(KeyError):
        canonical_view(conn, "never-written")


# --------------------------------------------------------------------------
# NFR-SEC-001 vs FR-AUD-001 — the tripwire must not refuse clean records
# --------------------------------------------------------------------------

#: uuid4s chosen because they trip each `_raw_value_shape` pattern. A uuid4 does this
#: ~24% of the time, so the defect these pin failed NONDETERMINISTICALLY — these tests
#: are fixed values precisely so they cannot pass by luck.
TRIPPING_UUIDS = (
    "f7865025-9402-4c14-8895-51f06de8c155",  # 7+ consecutive digits
    "168d5d48-2904-436c-9765-d0e636a77cbf",  # 9+ digits with separators (SSN shape)
)


@pytest.mark.parametrize("minted", TRIPPING_UUIDS)
def test_a_digit_heavy_signal_id_does_not_look_like_a_leak(minted: str) -> None:
    """★ A minted id is not content. Refusing it breaks FR-AUD-001 and proves nothing.

    Every request writes one audit record; a guard that rejects ~1 in 4 clean records
    because a random uuid4 contains digits destroys the audit trail it protects.
    """
    signal = pii_signal()
    signal.signal_id = minted
    assert json.loads(serialize_signals([signal]))[0]["signal_id"] == minted


@pytest.mark.parametrize("minted", TRIPPING_UUIDS)
def test_a_digit_heavy_failure_id_does_not_look_like_a_leak(conn, minted: str) -> None:
    record = DetectorFailureRecord(
        detector="tier1_pii", error_class="DetectorTimeout", failure_id=minted,
    )
    uc3 = Policy(**yaml.safe_load((POLICY_DIR / "finance_advisor.yaml").read_text()))
    write_record(conn, AuditRecord.from_verdict(
        request_id="req-minted", verdict=evaluate([], uc3, failures=[record]),
        stage_summary="input",
    ))
    assert canonical_view(conn, "req-minted")["detector_failures"][0]["failure_id"] == minted


def test_the_exemption_is_conditional_not_a_laundering_channel() -> None:
    """★ The field name alone must not buy an exemption — only a real minted value does.

    Otherwise the fix would become the very hole the tripwire exists to close: anything
    could reach the audit by being named `signal_id`.
    """
    signal = pii_signal()
    signal.signal_id = "ssn 001-01-0001 matched in prompt"
    with pytest.raises(PiiLeakError, match="never the value"):
        serialize_signals([signal])


def test_an_iso_timestamp_is_not_a_leak() -> None:
    record = DetectorFailureRecord(detector="tier1_pii", error_class="DetectorTimeout")
    uuid.UUID(record.failure_id)  # minted, so exempt
    datetime.fromisoformat(record.ts)  # ditto
    uc3 = Policy(**yaml.safe_load((POLICY_DIR / "finance_advisor.yaml").read_text()))
    entry = json.loads(serialize_failures([resolve_failure(record, uc3)]))[0]
    assert entry["ts"] == record.ts


@pytest.mark.parametrize("basic", ["20250101", "00010101"])
def test_iso_basic_format_does_not_buy_a_ts_exemption(basic: str) -> None:
    """`fromisoformat` accepts basic format; nothing here mints it, so it stays scanned.

    Closes an 8-digit window — a YYYYMMDD date of birth is content, not a timestamp.
    """
    from controlplane.audit.records import _is_minted_identifier

    assert not _is_minted_identifier("ts", basic)


def test_every_minted_value_this_project_actually_produces_is_exempt() -> None:
    """The tightening must not reject what the system really mints (FR-AUD-001)."""
    from controlplane.audit.records import _is_minted_identifier

    record = DetectorFailureRecord(detector="tier1_pii", error_class="DetectorTimeout")
    assert _is_minted_identifier("ts", record.ts)
    assert _is_minted_identifier("failure_id", record.failure_id)
    assert _is_minted_identifier("signal_id", pii_signal().signal_id)
