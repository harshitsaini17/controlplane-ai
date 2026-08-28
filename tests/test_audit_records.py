"""Audit writer: 05 §3 columns, 05 §4 canonical view, append-only, NFR-SEC-001.

The leak tests are the point of this file. Every upstream layer already refuses raw
values, so these assert the *last* line of defence — the one that matters most because
`audit_records` is the artifact that persists: a leak in a log line scrolls away, a leak
in the audit DB is still there when a report reads it.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from controlplane.audit.db import init_db
from controlplane.audit.records import (
    ID_LIST_COLUMNS,
    NOT_RUN_REASONS,
    AuditRecord,
    AuditWriteError,
    PiiLeakError,
    canonical_view,
    serialize_actions,
    serialize_detectors,
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
        model_used="openai/gpt-oss-20b",
        upstream_class="measured",
        tokens_in=812,
        tokens_out=344,
        est_cost_usd=0.0041,
        latency_json=json.dumps({spans.INGRESS: 1.0, "total_attributable_overhead_ms": 46.1,
                                 "upstream_ms": 1240.0}),
    ))
    view = canonical_view(conn, "req-1")

    # The 05 §4 nesting, not the flat columns.
    assert view["model"] == {"tier_requested": "small", "used": "openai/gpt-oss-20b",
                            "upstream_class": "measured", "cascade_escalated": False}
    assert view["cost"] == {"tokens_in": 812, "tokens_out": 344, "est_usd": 0.0041}
    assert view["latency"]["total_attributable_overhead_ms"] == 46.1
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
    ("tier_requested", "openai/gpt-oss-20b", "never a concrete model id"),
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


# --------------------------------------------------------------------------
# ADR-027 Amendment 1 — the §4.3 step-5 stamp is STORED, not derived
# --------------------------------------------------------------------------

#: uuid4 values whose *shape* trips `_raw_value_shape` (found by search, pinned as
#: literals so the test is deterministic rather than ~25%-of-the-time). The first has a
#: 7+ digit run, the second a grouped run the tripwire reads as SSN/credit-card shaped.
TRIPWIRE_SHAPED_UUIDS = (
    "3442569d-ff63-404b-befd-d0ba89c6bd0f",
    "85b828d2-c5dd-4b94-8642-795c30a45e2a",
)


def test_amendment1_the_stamp_round_trips_into_the_05_4_view(conn) -> None:
    """★ The columns 05 §4 lists as canonical keys must survive a write.

    This is the D5 regression: both keys were in the §4 view and derived by §2, while the
    §3 DDL declared neither column — so the writer dropped them silently.
    """
    sid, fid = str(uuid.uuid4()), str(uuid.uuid4())
    write_record(conn, base_record(
        verdict=Action.ESCALATE,
        contributing_signal_ids=(sid,),
        failure_record_ids=(fid,),
    ))
    view = canonical_view(conn, "req-1")
    assert view["contributing_signal_ids"] == [sid]
    assert view["failure_record_ids"] == [fid]


def test_amendment1_an_empty_stamp_is_an_empty_array_never_null(conn) -> None:
    """`[]` says "nothing contributed"; NULL would say "we did not record"."""
    write_record(conn, base_record())
    stored = conn.execute(
        "SELECT contributing_signal_ids, failure_record_ids FROM audit_records "
        "WHERE request_id = 'req-1'"
    ).fetchone()
    assert stored["contributing_signal_ids"] == "[]"
    assert stored["failure_record_ids"] == "[]"

    view = canonical_view(conn, "req-1")
    assert view["contributing_signal_ids"] == []
    assert view["failure_record_ids"] == []


@pytest.mark.parametrize("column", ["contributing_signal_ids", "failure_record_ids"])
def test_amendment1_a_bare_string_is_refused_not_iterated(conn, column: str) -> None:
    """★ `contributing_signal_ids="abc"` must not store three ids that never existed.

    A string is iterable, so the permissive reading of this slip is `["a","b","c"]` — and a
    reviewer would then read three contributing signals off the record.
    """
    with pytest.raises(AuditWriteError, match="must be a sequence of ids"):
        write_record(conn, base_record(**{column: "abc"}))


@pytest.mark.parametrize("bad", [123, None, {"a": 1}])
def test_amendment1_a_non_sequence_stamp_is_refused(conn, bad: object) -> None:
    with pytest.raises(AuditWriteError, match="must be a sequence of ids"):
        write_record(conn, base_record(contributing_signal_ids=bad))


def test_amendment1_an_empty_element_is_refused(conn) -> None:
    with pytest.raises(AuditWriteError, match="non-empty string id"):
        write_record(conn, base_record(failure_record_ids=("",)))


@pytest.mark.parametrize("minted", TRIPWIRE_SHAPED_UUIDS)
def test_amendment1_a_digit_heavy_id_in_the_stamp_is_not_a_leak(conn, minted: str) -> None:
    """★ The uuid4 false positive must not resurface in the new column shape.

    A bare array element's `_iter_strings` path is `[0]`, not a field name, so the
    field-keyed `MINTED_ID_FIELDS` exemption never fires for it. Measured before the fix:
    24.9% of single-uuid4 arrays were refused — one ESCALATE in four unable to write its
    own explanation.
    """
    write_record(conn, base_record(request_id=minted[:8], contributing_signal_ids=(minted,)))
    assert canonical_view(conn, minted[:8])["contributing_signal_ids"] == [minted]


@pytest.mark.parametrize("leak", ["001-01-0001", "4111111111111111"])
def test_amendment1_the_uuid_exemption_is_not_a_laundering_channel(conn, leak: str) -> None:
    """★ A real raw value in the stamp column is still refused.

    The exemption is conditional on the element actually parsing as a UUID, so it cannot
    become a hole for the mistake the tripwire exists to catch (NFR-SEC-001).
    """
    with pytest.raises(PiiLeakError):
        write_record(conn, base_record(contributing_signal_ids=(leak,)))


#: An ISO-8601 timestamp whose fractional part is a 7-digit run, so the shape tripwire
#: flags it. A plain `…T12:00:00.123456` is NOT flagged at all, which would make the test
#: below vacuous — the refusal has to be attributable to the narrowed exemption.
ISO_TS_TRIPPING_THE_SHAPE_CHECK = "2026-08-26T12:00:00.1234567"


def test_amendment1_an_iso_timestamp_buys_no_exemption_in_the_stamp(conn, uc3: Policy) -> None:
    """★ Narrower than `MINTED_ID_FIELDS` on purpose: UUID only, no timestamp branch.

    Differential, not just a refusal: the SAME string is exempt as a `ts` field, because
    that exemption is field-keyed and accepts ISO timestamps. In a stamp column it must be
    refused — a timestamp is not a signal id, and accepting one would widen the exemption
    past anything these columns can legitimately hold.
    """
    import dataclasses

    outcome = resolve_failure(
        DetectorFailureRecord(detector="tier1_pii", error_class="DetectorTimeout"), uc3,
    )
    exempt_as_ts = serialize_failures(
        [dataclasses.replace(outcome, ts=ISO_TS_TRIPPING_THE_SHAPE_CHECK)]
    )
    assert ISO_TS_TRIPPING_THE_SHAPE_CHECK in exempt_as_ts, (
        "precondition: this value is exempt in a `ts` field, so the refusal below is "
        "attributable to ID_LIST_COLUMNS being UUID-only"
    )

    with pytest.raises(PiiLeakError):
        write_record(conn, base_record(
            failure_record_ids=(ISO_TS_TRIPPING_THE_SHAPE_CHECK,)))


def test_amendment1_the_stamp_is_not_derivable_from_the_failures_column(conn) -> None:
    """★ Why the amendment stores rather than derives.

    A **fail_open** fault is recorded in `detector_failures_json` and contributes nothing to
    the verdict, so a consumer filtering that column would credit a failure that did not
    decide anything. The stored stamp is the only place the difference survives.
    """
    uc1 = Policy(**yaml.safe_load((POLICY_DIR / "support_bot.yaml").read_text()))
    record = DetectorFailureRecord(detector="tier2_toxicity", error_class="DetectorTimeout")
    outcome = resolve_failure(record, uc1)          # support_bot: tier2 -> fail_open
    assert outcome.action is None, "precondition: fail_open contributes no verdict action"
    write_record(conn, base_record(
        detector_failures_json=serialize_failures([outcome]),
        failure_record_ids=(),          # fail_open contributed nothing
    ))
    view = canonical_view(conn, "req-1")

    assert len(view["detector_failures"]) == 1, "the fault is recorded (ADR-027)"
    assert view["detector_failures"][0]["fail_mode_applied"] == "fail_open"
    assert view["failure_record_ids"] == [], (
        "a fail_open fault must not appear in the stamp; deriving the stamp by filtering "
        "detector_failures_json would credit it with the verdict"
    )


def test_amendment1_from_verdict_carries_the_engine_stamp_to_the_db(conn, uc3: Policy) -> None:
    """End to end: the engine's stamp, through `from_verdict`, into the stored row.

    Reads the ids off the *verdict* rather than restating literals, so a change to what the
    engine stamps fails here instead of passing against a hardcoded expectation.
    """
    signal = pii_signal()
    verdict = evaluate([signal], uc3)
    record = AuditRecord.from_verdict(
        request_id="req-e2e", verdict=verdict, stage_summary="input", signals=[signal],
    )
    write_record(conn, record)

    view = canonical_view(conn, "req-e2e")
    assert view["contributing_signal_ids"] == list(verdict.contributing_signal_ids)
    assert view["failure_record_ids"] == list(verdict.failure_record_ids)
    assert view["contributing_signal_ids"], "a PII signal that decided must be named"


def test_amendment1_the_ddl_declares_every_column_the_writer_stamps() -> None:
    """Differential against 05 §3: the doc's DDL must declare both stamp columns.

    Parses the doc rather than restating the column names, so drift on either side fails.
    """
    doc = (Path(__file__).resolve().parents[1]
           / "docs" / "05-api-and-data-contracts.md").read_text()
    ddl = doc.split("CREATE TABLE audit_records (", 1)[1].split(");", 1)[0]
    for column in ID_LIST_COLUMNS:
        assert f"{column} TEXT NOT NULL DEFAULT '[]'" in ddl, (
            f"05 §3 must declare {column} as a non-null JSON array (ADR-027 Amendment 1)"
        )


# --------------------------------------------------------------------------
# M-10 — the coverage column (`detectors_json`, 05 §3/§4)
# --------------------------------------------------------------------------

DOC_05 = (Path(__file__).resolve().parents[1] / "docs" / "05-api-and-data-contracts.md")


def _doc_audit_columns() -> list[str]:
    """Column names in 05 §3's `audit_records` DDL, in declared order."""
    ddl = DOC_05.read_text().split("CREATE TABLE audit_records (", 1)[1].split(");", 1)[0]
    names = []
    for line in ddl.splitlines():
        line = re.sub(r"--.*$", "", line).strip()
        for part in line.split(","):
            m = re.match(r"^([a-z_]+)\s+(?:TEXT|INTEGER|REAL)\b", part.strip())
            if m:
                names.append(m.group(1))
    return names


def _code_audit_columns() -> list[str]:
    """Column names in `db.SCHEMA_DDL`'s `audit_records`, in declared order."""
    from controlplane.audit.db import SCHEMA_DDL

    body = SCHEMA_DDL[0].split("(", 1)[1]
    names = []
    for line in body.splitlines():
        line = re.sub(r"--.*$", "", line).strip()
        for part in line.split(","):
            m = re.match(r"^([a-z_]+)\s+(?:TEXT|INTEGER|REAL)\b", part.strip())
            if m:
                names.append(m.group(1))
    return names


def test_m10_the_doc_ddl_and_the_code_ddl_declare_the_same_columns() -> None:
    """★ The guard whose absence let a doc-only column ship unnoticed.

    The pre-existing differential named the two Amendment-1 columns as literals, so it could
    only ever catch drift in *those two*. When 05 §3 gained `detectors_json` and `db.py` had
    not, the whole suite stayed green — a doc declaring a column the database does not have
    is exactly the contract mismatch AGENTS.md §5 calls D2.

    This compares the full column list, in order, in BOTH directions, so any future column
    added to one side alone fails here regardless of its name.
    """
    doc, code = _doc_audit_columns(), _code_audit_columns()
    assert doc == code, (
        f"05 §3 and db.SCHEMA_DDL disagree.\n"
        f"  doc-only : {[c for c in doc if c not in code]}\n"
        f"  code-only: {[c for c in code if c not in doc]}\n"
        f"  order differs: {doc != code and sorted(doc) == sorted(code)}"
    )


def test_m10_the_coverage_column_is_declared_in_both_ddls() -> None:
    """Named explicitly, so a deletion is a failure and not merely a silent absence."""
    assert "detectors_json" in _doc_audit_columns()
    assert "detectors_json" in _code_audit_columns()


def test_m10_the_reason_vocabulary_matches_the_doc() -> None:
    """★ Differential: parse the vocabulary out of 05 §4 rather than restating the code.

    Blanking `NOT_RUN_REASONS` or adding an undocumented member fails, and so does adding a
    reason to the doc without implementing it.
    """
    doc = DOC_05.read_text()
    para = re.search(r"`reason` vocabulary(.*?)\n\n", doc, re.S)
    assert para, "05 §4 must state the `reason` vocabulary"
    documented = set(re.findall(r"\*\*`([a-z_]+)`\*\*", para.group(1)))
    assert documented, "no bolded reason tokens found in 05 §4"
    assert documented == set(NOT_RUN_REASONS), (
        f"05 §4 documents {sorted(documented)}, code has {sorted(NOT_RUN_REASONS)}"
    )


def test_m10_coverage_round_trips_through_the_canonical_view(conn) -> None:
    """What the gateway writes is what 05 §4 renders."""
    write_record(conn, AuditRecord(
        request_id="cov-1", use_case="finance_advisor", policy_version=3,
        verdict="escalate", stage_summary="completed",
        detectors_json=serialize_detectors(
            ran=["tier1_pii", "numeric_claims"],
            not_run=[("fast_consistency", "not_implemented")],
        ),
    ))
    view = canonical_view(conn, "cov-1")["detectors"]
    assert view["ran"] == ["tier1_pii", "numeric_claims"]
    assert view["not_run"] == [
        {"detector": "fast_consistency", "reason": "not_implemented"}
    ]


def test_m10_unrecorded_is_distinct_from_nothing_ran(conn) -> None:
    """★ `{}` and `{"ran":[],"not_run":[]}` are different facts, and both are storable.

    The same distinction ADR-027 Amendment 1 draws between `[]` and NULL: one is a claim
    about the request, the other about the recording. A writer that normalised `{}` into
    empty lists would assert coverage was measured when it was not.
    """
    write_record(conn, AuditRecord(
        request_id="cov-default", use_case="hr_copilot", policy_version=1,
        verdict="pass", stage_summary="completed"))
    assert canonical_view(conn, "cov-default")["detectors"] == {}

    write_record(conn, AuditRecord(
        request_id="cov-empty", use_case="hr_copilot", policy_version=1,
        verdict="pass", stage_summary="completed",
        detectors_json=serialize_detectors()))
    assert canonical_view(conn, "cov-empty")["detectors"] == {"ran": [], "not_run": []}


@pytest.mark.parametrize("payload, fragment", [
    ({"ran": ["not_a_detector"]}, "04 §2 registry"),
    ({"not_run": [{"detector": "nope", "reason": "not_implemented"}]}, "04 §2 registry"),
    ({"not_run": [{"detector": "tier1_pii", "reason": "because"}]}, "not in"),
    ({"ran": "tier1_pii"}, "must be a list"),
    ({"not_run": [{"detector": "tier1_pii"}]}, "exactly"),
    ({"ran": [], "surprise": []}, "unknown key"),
    ([], "must be a JSON object"),
])
def test_m10_a_malformed_coverage_value_is_refused(conn, payload, fragment) -> None:
    """Every field is checked against a closed vocabulary, with a message naming the column."""
    with pytest.raises(AuditWriteError, match=re.escape(fragment)):
        write_record(conn, AuditRecord(
            request_id="bad", use_case="u", policy_version=1, verdict="pass",
            stage_summary="completed", detectors_json=json.dumps(payload)))


def test_m10_a_detector_cannot_both_run_and_not_run(conn) -> None:
    """★ The check that makes the column trustworthy as coverage.

    Every other rule can be satisfied by a record asserting both, which no reader could
    resolve — so the contradiction is refused at the write path rather than left to whoever
    reads the row.
    """
    with pytest.raises(AuditWriteError, match="both"):
        write_record(conn, AuditRecord(
            request_id="contradiction", use_case="u", policy_version=1, verdict="pass",
            stage_summary="completed",
            detectors_json=serialize_detectors(
                ran=["tier1_pii"], not_run=[("tier1_pii", "not_implemented")])))


def test_m10_a_not_run_entry_is_not_a_detector_failure(conn) -> None:
    """★ ADR-027 boundary: ran-and-broke and never-ran are independent columns.

    A record can carry a not-run entry with an empty failures column — the case this field
    exists for. Were the two conflated, a Phase-5 gap would appear in the audit as a
    detector fault that never occurred, and `cp_detector_failures_total` would count it.
    """
    write_record(conn, AuditRecord(
        request_id="gap-only", use_case="finance_advisor", policy_version=3,
        verdict="pass", stage_summary="completed",
        detectors_json=serialize_detectors(
            ran=["tier1_pii"], not_run=[("fast_consistency", "not_implemented")])))
    view = canonical_view(conn, "gap-only")
    assert view["detectors"]["not_run"][0]["detector"] == "fast_consistency"
    assert view["detector_failures"] == []
    # And nothing in the coverage entry carries a fail mode: there was no policy resolution.
    assert "fail_mode_applied" not in view["detectors"]["not_run"][0]


def test_m10_the_uc3_case_this_field_exists_for(conn) -> None:
    """★ The concrete requirement: UC-3 asks for consistency, and it is not there.

    `finance_advisor` sets `consistency: "on"`, so a reader seeing no
    `hallucination.low_confidence` signal must be able to tell "checked, clean" from "never
    checked". Reads the flag out of the shipped policy rather than hardcoding it, so this
    test follows the config.
    """
    policy = yaml.safe_load((POLICY_DIR / "finance_advisor.yaml").read_text())
    assert policy["consistency"] == "on", "UC-3 is the case this field exists for"

    write_record(conn, AuditRecord(
        request_id="uc3", use_case="finance_advisor", policy_version=3,
        verdict="pass", stage_summary="completed", signals_json="[]",
        detectors_json=serialize_detectors(
            ran=["tier1_pii", "numeric_claims"],
            not_run=[("fast_consistency", "not_implemented")])))

    view = canonical_view(conn, "uc3")
    assert view["signals"] == []
    absent = {e["detector"] for e in view["detectors"]["not_run"]}
    assert "fast_consistency" in absent, (
        "a consistency-free verdict under consistency:on must say the check did not run"
    )
