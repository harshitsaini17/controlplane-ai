"""Review queue and HITL overrides.

Implements 05 §3 `review_items` and the storage half of the 05 §2 admin review
endpoints (ADR-010: endpoints + CLI, no review web app). Satisfies FR-POL-005
(ESCALATE quarantines, records a review item, notifies) and FR-AUD-002 (overrides
append to the record lineage with a reviewer note).

**`quarantined_text` is masked here, by re-scanning the text being stored.** 05 §3
words this as "PII spans masked at write time", and the write path is the only place
that can do it correctly. The tempting alternative — reusing the spans the verdict's
signals already carry — is actively unsafe: a streaming pipeline scans per sentence,
so those offsets are sentence-relative, while ESCALATE quarantines the *entire*
response (04 §4.4). Applied to the full text they cut at the wrong place and leave the
original value in the row:

    "Your account is rea[REDACTED:ssn] on file is 001-01-0001."   <- raw SSN survives

Re-scanning the exact string about to be written has no such coupling. It costs one
Tier-1 pass (NFR-P-002: < 2 ms) off the hot path, since the row is written after the
verdict is already decided.

**Approving therefore releases the masked text**, and that is the documented behaviour
rather than a defect: 05 §3's rule is absolute — "nothing outside
`review_items.quarantined_text` ever stores model output verbatim, and that column is
written post-masking" — so the unmasked original is deliberately not retained anywhere
for the release to draw on. A reviewer approving a response quarantined for, say, a
low-confidence claim releases it with any Tier-1 PII spans redacted.

`review_items` is the one table that is legitimately mutable: a decision writes
`status`, `decision_ts` and `reviewer_note` onto an existing row, which is what
FR-AUD-002 asks for. The append-only discipline of 05 §3 binds `audit_records`, not
this table. A decision is still one-shot — `decide()` refuses an already-decided item
rather than overwriting it, so a reviewer's note cannot be silently replaced.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from controlplane.detectors.base import DetectorContext, Stage
from controlplane.detectors.tier1_patterns import tier1_pii
from controlplane.policy.actions import category_of, redact_spans
from controlplane.telemetry.metrics import REGISTRY_DEFAULT, MetricsRegistry

#: 05 §3 `review_items.status` CHECK vocabulary, restated so a bad value fails with a
#: message naming the column instead of a bare `IntegrityError`.
STATUSES: frozenset[str] = frozenset({"pending", "approved", "rejected"})

#: 05 §2 `POST /admin/review/{review_id}` body `{decision: approve|reject, note}`.
DECISIONS: dict[str, str] = {"approve": "approved", "reject": "rejected"}


class ReviewError(RuntimeError):
    """A review-queue operation that must not be silently absorbed.

    Deliberately not an HTTP concern: this module knows nothing about status codes. The
    admin layer maps it, so the storage rules stay testable without a web stack.
    """


@dataclass(frozen=True)
class ReviewItem:
    """One row of 05 §3 `review_items`, as read back for the admin listing.

    `escalation_cause` and `failure_summary` (05 §2) are **not on this type yet**, and the
    reason has changed. They were previously impossible: neither id list reached the
    database. ADR-027 Amendment 1 stores the §4.3 step-5 stamp as
    `audit_records.contributing_signal_ids` / `failure_record_ids`, so the derivation 05 §2
    specifies is now implementable, and the deviation that blocked it is closed.

    What remains is the derivation. 05 §2 computes both fields from those two columns plus
    `detector_failures_json` on the *referenced audit record* — a join this type's
    single-table reads do not perform. Deriving them from `detector_failures_json` alone
    would still misreport, because that column carries fail_open records, which are present
    without having contributed. So the fields stay absent until the join is written rather
    than being approximated from what one table happens to hold.
    """

    review_id: str
    request_id: str
    ts_created: str
    status: str
    quarantined_text: str
    decision_ts: str | None = None
    reviewer_note: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def mask_pii(text: str) -> str:
    """Redact Tier-1 PII spans in `text` (NFR-SEC-001, 05 §3).

    Scans `text` itself rather than trusting spans computed against some other string —
    see the module docstring for why that distinction is load-bearing. `stage` is
    `OUTPUT_FULL` because the quarantined unit is a whole response (04 §4.4), which is
    also the stage whose signals never carry sentence-relative offsets.

    Categories come from `category_of`, applied only to `pii.*` labels. `category_of` is
    a prefix stripper — it answers `high` for `toxicity.high` — so filtering by label
    family is what keeps a toxicity finding from being rendered as `[REDACTED:high]`.
    """
    signals = await tier1_pii.detect(DetectorContext(text=text, stage=Stage.OUTPUT_FULL))
    spans = [
        (s.span.start, s.span.end, category_of(s.labels[0]))
        for s in signals
        if s.span is not None and s.labels and s.labels[0].startswith("pii.")
    ]
    if not spans:
        return text
    return redact_spans(text, spans)


async def create_item(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    quarantined_text: str,
    use_case: str,
    metrics: MetricsRegistry | None = None,
) -> str:
    """Quarantine one response and return its `review_id` (FR-POL-005).

    The returned id is what 05 §1.1's HTTP 202 body carries, so the caller can hand the
    user a reference without ever echoing the quarantined content.

    Masking happens here, before the INSERT, so no code path can write the row without
    it — a caller who masks first is idempotent (the markers contain no PII to find),
    and a caller who forgets is still safe.
    """
    if not request_id:
        raise ReviewError("request_id is required; a review item must reference its audit record")

    review_id = str(uuid.uuid4())
    masked = await mask_pii(quarantined_text)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO review_items (
                  review_id, request_id, ts_created, quarantined_text, status,
                  decision_ts, reviewer_note
                ) VALUES (?,?,?,?,'pending',NULL,NULL)
                """,
                (review_id, request_id, _now(), masked),
            )
    except sqlite3.IntegrityError as exc:
        raise ReviewError(f"cannot create review item for {request_id!r}: {exc}") from exc

    (metrics or REGISTRY_DEFAULT).increment(
        "cp_review_items_total", use_case=use_case, status="pending"
    )
    return review_id


#: Column order for every read in this module, so one mapper serves them all and a
#: column added to 05 §3 cannot silently shift an index. Positional access is used
#: deliberately: `db.connect` sets `row_factory = sqlite3.Row`, but a caller passing a
#: bare `sqlite3.connect()` would then get tuples, and positional works for both.
_SELECT = """SELECT review_id, request_id, ts_created, status, quarantined_text,
                    decision_ts, reviewer_note
             FROM review_items"""


def _to_item(row: object) -> ReviewItem:
    return ReviewItem(
        review_id=row[0],       # type: ignore[index]
        request_id=row[1],      # type: ignore[index]
        ts_created=row[2],      # type: ignore[index]
        status=row[3],          # type: ignore[index]
        quarantined_text=row[4],  # type: ignore[index]
        decision_ts=row[5],     # type: ignore[index]
        reviewer_note=row[6],   # type: ignore[index]
    )


def list_items(
    conn: sqlite3.Connection, *, status: str | None = "pending", limit: int = 100
) -> list[ReviewItem]:
    """Rows for `GET /admin/review?status=…` (05 §2), oldest first.

    Oldest-first because a review queue is worked front to back; a newest-first listing
    would let the oldest quarantine starve behind fresh arrivals.
    """
    if status is not None and status not in STATUSES:
        raise ReviewError(f"status {status!r} not in {sorted(STATUSES)} (05 §3)")
    if limit < 1:
        raise ReviewError(f"limit must be positive, got {limit}")

    sql = _SELECT
    params: tuple[object, ...] = ()
    if status is not None:
        sql += " WHERE status = ?"
        params = (status,)
    # `review_id` breaks ties: two items quarantined in the same clock tick would
    # otherwise come back in an order SQLite is free to vary between runs, which would
    # make a paged listing non-deterministic.
    sql += " ORDER BY ts_created ASC, review_id ASC LIMIT ?"
    params += (limit,)

    return [_to_item(row) for row in conn.execute(sql, params).fetchall()]


def get_item(conn: sqlite3.Connection, review_id: str) -> ReviewItem:
    """One item by id, or `ReviewError` if it does not exist.

    A primary-key lookup, not a filtered listing: `review_id` is the PK in 05 §3, so
    this is one index seek regardless of queue depth.
    """
    row = conn.execute(f"{_SELECT} WHERE review_id = ?", (review_id,)).fetchone()
    if row is None:
        raise ReviewError(f"no review item {review_id!r}")
    return _to_item(row)


def decide(
    conn: sqlite3.Connection,
    review_id: str,
    *,
    decision: str,
    note: str | None = None,
    use_case: str | None = None,
    metrics: MetricsRegistry | None = None,
) -> ReviewItem:
    """Record a reviewer's approve/reject with their note (FR-AUD-002, 05 §2).

    One-shot: an already-decided item is refused rather than re-decided. The audit
    lineage is meant to show what the reviewer concluded, and silently overwriting a
    prior note would erase exactly the thing FR-AUD-002 exists to keep. Reversing a
    decision is a new decision on a new item, not a rewrite of this one.

    The UPDATE is guarded by `status = 'pending'` in SQL rather than by a read-then-write,
    so two concurrent decisions cannot both succeed — the second matches no row.
    """
    if decision not in DECISIONS:
        raise ReviewError(f"decision {decision!r} not in {sorted(DECISIONS)} (05 §2)")

    new_status = DECISIONS[decision]
    with conn:
        cursor = conn.execute(
            """UPDATE review_items
                  SET status = ?, decision_ts = ?, reviewer_note = ?
                WHERE review_id = ? AND status = 'pending'""",
            (new_status, _now(), note, review_id),
        )
        if cursor.rowcount == 0:
            # Distinguish "no such item" from "already decided": the reviewer needs to
            # know which, and a single "not found" would hide a double-decision.
            existing = conn.execute(
                "SELECT status FROM review_items WHERE review_id = ?", (review_id,)
            ).fetchone()
            if existing is None:
                raise ReviewError(f"no review item {review_id!r}")
            raise ReviewError(
                f"review item {review_id!r} is already {existing[0]!r}; a decision is "
                "one-shot (FR-AUD-002 keeps the reviewer's note, it does not replace it)"
            )

    if use_case is not None:
        (metrics or REGISTRY_DEFAULT).increment(
            "cp_review_items_total", use_case=use_case, status=new_status
        )
    return get_item(conn, review_id)


def released_text(conn: sqlite3.Connection, review_id: str) -> str:
    """Text for `GET /admin/review/{id}/released` (05 §2) — approved items only.

    Returns the **masked** text, because that is the only version stored (see the module
    docstring). A rejected or still-pending item releases nothing: serving its content
    would defeat the quarantine that a BLOCK-equivalent rejection just confirmed.
    """
    item = get_item(conn, review_id)
    if item.status != "approved":
        raise ReviewError(
            f"review item {review_id!r} is {item.status!r}; only an approved item releases "
            "its response (05 §2)"
        )
    return item.quarantined_text
