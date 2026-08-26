"""Review queue + HITL override tests — 05 §2/§3, FR-POL-005, FR-AUD-002, NFR-SEC-001.

No pytest-asyncio: it is not a declared dependency (02 §8 bounds the set), and
`asyncio.run` in a sync test needs none.

The masking tests are the point of this file. `review_items.quarantined_text` is the one
column in the schema allowed to hold model output, so it is also the only place a raw PII
value could come to rest — 05 §3 requires it written post-masking, and a leak there is
D7.
"""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from pathlib import Path

import pytest

from controlplane.audit.db import init_db
from controlplane.audit.records import AuditRecord, canonical_view, write_record
from controlplane.audit.review import (
    DECISIONS,
    STATUSES,
    ReviewError,
    create_item,
    decide,
    get_item,
    list_items,
    mask_pii,
    released_text,
)
from controlplane.telemetry.metrics import MetricsRegistry

#: Fixed values, never generated. A masking test that passed by luck on one random
#: sample would be worse than no test — the guard would look green while the hole
#: stayed open (the lesson of the audit-writer tripwire defect).
SSN = "001-01-0001"
EMAIL = "a.b@example.com"
PHONE = "415-555-0142"


@pytest.fixture
def conn():
    with tempfile.TemporaryDirectory() as tmp:
        connection = init_db(Path(tmp) / "audit.db")
        yield connection


@pytest.fixture
def metrics() -> MetricsRegistry:
    """A private registry, so a test cannot pollute the process-wide default."""
    return MetricsRegistry()


def audit_row(conn: sqlite3.Connection, request_id: str = "req-1", **kwargs) -> str:
    """`review_items.request_id` REFERENCES `audit_records` and foreign_keys is ON."""
    write_record(conn, AuditRecord(
        request_id=request_id, use_case=kwargs.pop("use_case", "finance_advisor"),
        policy_version=3, verdict="escalate", stage_summary="completed", **kwargs))
    return request_id


def quarantine(conn, text: str, *, request_id: str = "req-1", **kwargs) -> str:
    return asyncio.run(create_item(
        conn, request_id=request_id, quarantined_text=text,
        use_case=kwargs.pop("use_case", "finance_advisor"), **kwargs))


def stored_text(conn: sqlite3.Connection, review_id: str) -> str:
    return conn.execute(
        "SELECT quarantined_text FROM review_items WHERE review_id = ?", (review_id,)
    ).fetchone()[0]


# --------------------------------------------------------------------------
# NFR-SEC-001 — masking at the write path
# --------------------------------------------------------------------------


def test_nfr_sec_001_no_raw_pii_reaches_the_row(conn) -> None:
    """★ The one column allowed to hold model output must not hold a raw PII value."""
    audit_row(conn)
    rid = quarantine(conn, f"Your SSN {SSN} qualifies. Email {EMAIL} or call {PHONE}.")

    text = stored_text(conn, rid)
    for raw in (SSN, EMAIL, PHONE):
        assert raw not in text, f"{raw!r} survived masking"
    for category in ("ssn", "email", "phone"):
        assert f"[REDACTED:{category}]" in text


def test_masking_rescans_and_does_not_trust_sentence_relative_offsets(conn) -> None:
    """★ Regression pin for a real hole: reused spans mask the wrong characters.

    A streaming pipeline scans per sentence, so its signal offsets are sentence-relative,
    while ESCALATE quarantines the entire response (04 §4.4). Applied to the full text
    those offsets cut at the wrong place and leave the original value intact — measured,
    before the fix:

        "Your account is rea[REDACTED:ssn] on file is 001-01-0001."

    Here the PII sits far from its sentence-relative offset, so any implementation that
    reused those spans instead of re-scanning would fail this test.
    """
    audit_row(conn)
    sentence = f"The SSN on file is {SSN}."
    full = f"Your account is ready. {sentence} Thanks for your patience."
    #: The offset the *sentence* scan would have reported, which points at unrelated
    #: characters of the full text — this is the trap, asserted rather than described.
    assert full[sentence.index(SSN):sentence.index(SSN) + len(SSN)] != SSN

    text = stored_text(conn, quarantine(conn, full))
    assert SSN not in text
    assert text == "Your account is ready. The SSN on file is [REDACTED:ssn]. Thanks for your patience."


def test_a_non_pii_label_is_not_rendered_as_a_redaction_marker() -> None:
    """`category_of` is a prefix stripper: it answers `high` for `toxicity.high`.

    Masking is therefore filtered to `pii.*`. Without that filter a toxicity or
    hallucination finding would be replaced by `[REDACTED:high]` — content destroyed for
    a signal that has nothing to redact, in the column a reviewer needs to read.
    """
    text = "This estimate is probably around 40% based on nothing in particular."
    assert asyncio.run(mask_pii(text)) == text


def test_masking_is_idempotent(conn) -> None:
    """A caller who masks first must not double-mask; the markers contain no PII."""
    once = asyncio.run(mask_pii(f"SSN {SSN} here"))
    assert asyncio.run(mask_pii(once)) == once


def test_clean_text_is_stored_unchanged(conn) -> None:
    """Masking must not perturb text that has no PII — a reviewer reads this column."""
    audit_row(conn)
    clean = "The quarterly figure could not be verified against any filing."
    assert stored_text(conn, quarantine(conn, clean)) == clean


# --------------------------------------------------------------------------
# FR-POL-005 — quarantine + queue
# --------------------------------------------------------------------------


def test_fr_pol_005_escalate_records_a_pending_item(conn, metrics) -> None:
    audit_row(conn)
    rid = quarantine(conn, "Unverified claim.", metrics=metrics)

    item = get_item(conn, rid)
    assert item.status == "pending"
    assert item.request_id == "req-1"
    assert item.decision_ts is None and item.reviewer_note is None
    assert metrics.value_of(
        "cp_review_items_total", use_case="finance_advisor", status="pending") == 1.0


def test_the_review_id_is_returned_so_the_202_body_needs_no_content(conn) -> None:
    """05 §1.1's ESCALATE body carries `review_id`, never the quarantined text."""
    audit_row(conn)
    rid = quarantine(conn, f"SSN {SSN}")
    assert rid and SSN not in rid
    assert get_item(conn, rid).review_id == rid


def test_an_item_cannot_orphan_from_its_audit_record(conn) -> None:
    """`REFERENCES audit_records` with foreign_keys=ON (05 §3, db.connect).

    A review item whose audit record does not exist is unreviewable: the reviewer has no
    verdict, no signals and no policy version to judge against.
    """
    with pytest.raises(ReviewError):
        quarantine(conn, "text", request_id="never-written")


def test_an_empty_request_id_is_refused(conn) -> None:
    with pytest.raises(ReviewError, match="request_id is required"):
        quarantine(conn, "text", request_id="")


# --------------------------------------------------------------------------
# FR-AUD-002 — overrides
# --------------------------------------------------------------------------


def test_fr_aud_002_a_decision_records_status_note_and_timestamp(conn, metrics) -> None:
    audit_row(conn)
    rid = quarantine(conn, "Unverified claim.")

    item = decide(conn, rid, decision="approve", note="claim verified against filing",
                  use_case="finance_advisor", metrics=metrics)
    assert item.status == "approved"
    assert item.reviewer_note == "claim verified against filing"
    assert item.decision_ts is not None
    assert metrics.value_of(
        "cp_review_items_total", use_case="finance_advisor", status="approved") == 1.0


def test_reject_maps_to_rejected(conn) -> None:
    audit_row(conn)
    rid = quarantine(conn, "Fabricated detail.")
    assert decide(conn, rid, decision="reject", note="not in the filing").status == "rejected"


def test_a_decision_is_one_shot_and_preserves_the_original_note(conn) -> None:
    """★ FR-AUD-002 keeps the reviewer's note; it does not replace it.

    The substantive assertion is the *second* one: refusing the call is only useful if
    the first decision actually survives it.
    """
    audit_row(conn)
    rid = quarantine(conn, "Unverified claim.")
    decide(conn, rid, decision="approve", note="first reviewer")

    with pytest.raises(ReviewError, match="already 'approved'"):
        decide(conn, rid, decision="reject", note="second reviewer")

    item = get_item(conn, rid)
    assert item.status == "approved" and item.reviewer_note == "first reviewer"


def test_already_decided_is_distinguished_from_absent(conn) -> None:
    """A single "not found" would hide a double-decision from the reviewer."""
    audit_row(conn)
    rid = quarantine(conn, "text")
    decide(conn, rid, decision="approve")

    with pytest.raises(ReviewError, match="already"):
        decide(conn, rid, decision="approve")
    with pytest.raises(ReviewError, match="no review item"):
        decide(conn, "does-not-exist", decision="approve")


@pytest.mark.parametrize("decision", ["maybe", "APPROVE", "approved", ""])
def test_an_unknown_decision_is_refused(conn, decision) -> None:
    """05 §2 fixes the body vocabulary at `approve|reject`.

    `approved` is included deliberately: it is the *stored status*, not the decision verb,
    and accepting it would let a caller's confusion write a valid-looking row.
    """
    audit_row(conn)
    rid = quarantine(conn, "text")
    with pytest.raises(ReviewError, match="not in"):
        decide(conn, rid, decision=decision)
    assert get_item(conn, rid).status == "pending"


def test_the_metric_is_optional_but_the_decision_is_not(conn) -> None:
    """`use_case` is absent when the caller has not joined the audit record.

    The decision must still be recorded — dropping it because a label was unavailable
    would lose the reviewer's ruling to a telemetry concern.
    """
    audit_row(conn)
    rid = quarantine(conn, "text")
    assert decide(conn, rid, decision="approve").status == "approved"


# --------------------------------------------------------------------------
# 05 §2 listing + release
# --------------------------------------------------------------------------


def test_the_queue_is_worked_oldest_first(conn) -> None:
    """A newest-first queue lets the oldest quarantine starve behind fresh arrivals."""
    for n in range(3):
        audit_row(conn, request_id=f"req-{n}")
    ids = [quarantine(conn, f"claim {n}", request_id=f"req-{n}") for n in range(3)]
    assert [i.review_id for i in list_items(conn)] == ids


def test_listing_filters_by_status_and_none_means_all(conn) -> None:
    for n in range(3):
        audit_row(conn, request_id=f"req-{n}")
    ids = [quarantine(conn, f"claim {n}", request_id=f"req-{n}") for n in range(3)]
    decide(conn, ids[0], decision="approve")
    decide(conn, ids[1], decision="reject")

    assert [i.review_id for i in list_items(conn, status="pending")] == [ids[2]]
    assert [i.review_id for i in list_items(conn, status="approved")] == [ids[0]]
    assert len(list_items(conn, status=None)) == 3


def test_listing_respects_its_limit(conn) -> None:
    for n in range(4):
        audit_row(conn, request_id=f"req-{n}")
        quarantine(conn, f"claim {n}", request_id=f"req-{n}")
    assert len(list_items(conn, limit=2)) == 2


@pytest.mark.parametrize("bad", ["bogus", "pending ", "Approved"])
def test_an_unknown_listing_status_is_refused(conn, bad) -> None:
    with pytest.raises(ReviewError, match="not in"):
        list_items(conn, status=bad)


def test_a_nonpositive_limit_is_refused(conn) -> None:
    with pytest.raises(ReviewError, match="limit must be positive"):
        list_items(conn, limit=0)


def test_only_an_approved_item_releases_its_response(conn) -> None:
    """★ A rejected item releasing content would defeat the quarantine.

    Rejection is the reviewer confirming the BLOCK-equivalent outcome; serving the text
    afterwards would make the review decision cosmetic.
    """
    audit_row(conn)
    rid = quarantine(conn, "Unverified claim.")

    with pytest.raises(ReviewError, match="only an approved item"):
        released_text(conn, rid)

    decide(conn, rid, decision="reject")
    with pytest.raises(ReviewError, match="only an approved item"):
        released_text(conn, rid)


def test_release_returns_the_masked_text_which_is_the_only_version_stored(conn) -> None:
    """Documented consequence of 05 §3, asserted so it cannot be mistaken for a bug.

    The unmasked original is deliberately retained nowhere, so approval releases the
    masked text. A test asserting the raw value came back would be asserting a D7 leak.
    """
    audit_row(conn)
    rid = quarantine(conn, f"Approved figure for SSN {SSN}.")
    decide(conn, rid, decision="approve")

    text = released_text(conn, rid)
    assert SSN not in text
    assert text == "Approved figure for SSN [REDACTED:ssn]."


def test_missing_item_raises_rather_than_returning_empty(conn) -> None:
    with pytest.raises(ReviewError, match="no review item"):
        get_item(conn, "nope")


# --------------------------------------------------------------------------
# Lineage + vocabulary
# --------------------------------------------------------------------------


def test_the_override_reaches_the_05_4_canonical_view(conn) -> None:
    """★ FR-AUD-002 lineage: the decision must be readable from the audit record.

    This is what makes the loop auditable end to end — `records.canonical_view` joins
    `review_items`, so a decision recorded here surfaces on the request it judged.
    """
    audit_row(conn)
    rid = quarantine(conn, "Unverified claim.")
    decide(conn, rid, decision="approve", note="verified against filing")

    override = canonical_view(conn, "req-1")["override"]
    assert override["decision"] == "approve"
    assert override["note"] == "verified against filing"
    assert override["review_id"] == rid
    assert override["ts"] is not None


def test_a_pending_item_contributes_no_override(conn) -> None:
    """An absent key and a null decision say different things (05 §4)."""
    audit_row(conn)
    quarantine(conn, "Unverified claim.")
    assert "override" not in canonical_view(conn, "req-1")


def test_the_vocabularies_match_the_05_3_check_constraint(conn) -> None:
    """Differential against the DDL SQLite is actually enforcing.

    Restating the module's own literal would prove nothing; this reads the CHECK clause
    off the live schema, so a status added on one side only fails.
    """
    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'review_items'").fetchone()[0]
    for status in STATUSES:
        assert f"'{status}'" in ddl, f"{status!r} is not in the 05 §3 CHECK constraint"
    assert set(DECISIONS.values()) <= STATUSES


def test_the_escalation_cause_enrichment_is_absent_by_construction(conn) -> None:
    """Documents the open BLOCKER rather than papering over it.

    05 §2 requires `escalation_cause` / `failure_summary` on every listed item, both
    derived from the §4.3 step-5 stamp. `[D5-adr-027-stamp-has-no-column-in-the-05-3-ddl]`
    establishes the stamp never reaches the database, so synthesizing the field here
    would misreport — a fail_open record is present without having contributed. This test
    fails once the deviation is ruled and the field lands, which is the intended prompt to
    update it.
    """
    audit_row(conn)
    quarantine(conn, "Unverified claim.")
    item = list_items(conn)[0]
    assert not hasattr(item, "escalation_cause")
    assert not hasattr(item, "failure_summary")
