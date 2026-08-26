"""Append-only audit record writer and the 05 §4 canonical JSON view.

Implements 05 §3 `audit_records` writes and the 05 §4 record shape (FR-AUD-001).

**Append-only is a discipline here, not a constraint.** SQLite cannot revoke UPDATE
from an in-process connection (see `audit/db.py`), so this module is the enforcement
point: it exposes `write_record` and `canonical_view`, and nothing that rewrites a
row. A reviewer decision reaches the *lineage* (FR-AUD-002) as a `review_items` row,
never by editing the audit row it refers to — `canonical_view` reads that row back
into the `override` block, so the decision is visible without the record mutating.

**NFR-SEC-001 holds at the write path, and that is deliberate placement.** Every
upstream layer already refuses raw values — `Signal` validates `evidence`,
`AppliedEdit` carries category+span only, `DetectorFailureRecord` has no content
surface at all (ADR-027). This module re-checks anyway, because the audit DB is the
one artifact that *persists*: a leak in a log line scrolls away, a leak in
`audit_records` is still there when the row is read into a report. `_check_no_raw_values`
walks the string leaves of every content-bearing column and raises rather than writes.

The tripwire is imported from `detectors.base` rather than reimplemented. It is a
module-private name, and reaching for it is the lesser evil: two independent
definitions of "what a leaked value looks like" would drift, and the one that drifts
weaker becomes the hole. One definition, one place to strengthen.

Not this module's job: masking `review_items.quarantined_text` (that is
`audit/review.py`, which owns the only column allowed to hold verbatim output), and
computing `est_cost_usd` (ADR-022 — the writer records what it is given and refuses
to invent a number).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from controlplane.detectors.base import Signal, _raw_value_shape
from controlplane.policy.engine import FailureOutcome, Verdict
from controlplane.policy.schema import Action
from controlplane.telemetry import spans

#: 05 §3 `stage_summary`. The DDL carries this as a comment, not a CHECK, so it is
#: validated here — an undeclared value would silently become a new category that no
#: dashboard groups by.
STAGE_SUMMARIES: frozenset[str] = frozenset({"input", "streamed", "completed"})

#: 05 §3 CHECK vocabularies, restated so a bad value fails with a useful message
#: instead of a bare `IntegrityError` naming no column.
TIERS: frozenset[str] = frozenset({"small", "frontier"})
UPSTREAM_CLASSES: frozenset[str] = frozenset({"dev", "measured"})

#: Columns whose string leaves are scanned for raw values before the row is written.
#: Deliberately excludes `request_id`, `ts_utc` and the model/provider names: a UUID
#: or an ISO timestamp can contain a long digit run and would false-positive, while
#: carrying no content by construction.
CONTENT_COLUMNS = ("signals_json", "detector_failures_json", "actions_json", "latency_json")

#: Leaf field names inside the scanned columns whose values the *system* mints rather
#: than deriving from content: uuid4 identifiers and ISO-8601 timestamps.
#:
#: Scanning them was a real defect, not a theoretical one. A uuid4 contains a 7+ digit
#: run (or an SSN-shaped grouped run) about 24% of the time, so ~1 write in 4 carrying a
#: `Signal` refused a perfectly clean record — a false positive that breaks FR-AUD-001
#: ("every request writes one audit record") while proving nothing about PII. It also
#: failed nondeterministically, which is the worst way for a safety guard to be wrong.
#:
#: The exemption is CONDITIONAL, not blanket: the value must actually parse as a UUID or
#: an ISO timestamp (`_is_minted_identifier`). A field named `signal_id` holding free
#: text is scanned like any other leaf, so this cannot become a laundering channel for
#: the mistake the tripwire exists to catch.
MINTED_ID_FIELDS: frozenset[str] = frozenset({
    "signal_id", "failure_id", "review_id", "ts",
})

#: The two 04 §4.3 step-5 stamp columns (ADR-027 Amendment 1). Their elements are ids the
#: system minted, so they get the same conditional exemption as `MINTED_ID_FIELDS` — but
#: keyed on the COLUMN, because a bare array element's `_iter_strings` path is `[0]`, not a
#: field name, so the field-keyed exemption never fires for it.
#:
#: This is the pre-existing uuid4 false-positive resurfacing in a new column shape, not a
#: new theory: measured here, 24.9% of single-uuid4 arrays (499/2000) contain a digit run
#: the shape tripwire reads as a raw value. Left unexempted, roughly one ESCALATE in four
#: would refuse to write its own explanation.
#:
#: NARROWER than `MINTED_ID_FIELDS` on purpose: UUID only, no ISO-timestamp branch. A
#: timestamp is not a signal id, so accepting one here would widen the exemption past
#: anything these columns can legitimately hold.
ID_LIST_COLUMNS: tuple[str, ...] = ("contributing_signal_ids", "failure_record_ids")


class AuditWriteError(ValueError):
    """The record is malformed — bad enum value, unknown latency key, missing id."""


class PiiLeakError(AuditWriteError):
    """A raw value reached the write path (NFR-SEC-001). The row is NOT written."""


def _iter_strings(value: object, path: str = "") -> list[tuple[str, str]]:
    """Every string leaf in a nested JSON-safe structure, with its path.

    Only strings are yielded. Integers are skipped on purpose: spans are integers, and
    a span like `{"start": 1234567}` would otherwise read as a seven-digit run and trip
    the tripwire on a document that contains no PII at all.
    """
    out: list[tuple[str, str]] = []
    if isinstance(value, str):
        out.append((path or "<root>", value))
    elif isinstance(value, dict):
        for key, item in value.items():
            out.extend(_iter_strings(item, f"{path}.{key}" if path else str(key)))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            out.extend(_iter_strings(item, f"{path}[{index}]"))
    return out


def _is_minted_identifier(key: str, text: str) -> bool:
    """True if `key` is a system-minted field AND `text` really is such a value.

    The second half is what keeps the exemption honest — see `MINTED_ID_FIELDS`.
    """
    if key not in MINTED_ID_FIELDS:
        return False
    try:
        uuid.UUID(text)
        return True
    except ValueError:
        pass
    if "-" not in text:
        #: `fromisoformat` also accepts ISO *basic* format, so a bare "20250101" would
        #: parse and buy an exemption. Everything this project mints comes from
        #: `.isoformat()`, which always emits extended format, so requiring a separator
        #: costs nothing and closes an 8-digit window (a YYYYMMDD date of birth).
        return False
    try:
        datetime.fromisoformat(text)
        return True
    except ValueError:
        return False


def _is_uuid(text: str) -> bool:
    try:
        uuid.UUID(text)
        return True
    except ValueError:
        return False


def _check_id_list(column: str, ids: object) -> None:
    """Validate one step-5 id list. Raises, or returns nothing.

    Refuses a bare string outright. `contributing_signal_ids="abc"` is a plausible slip and
    would otherwise be *iterable* — the row would store `["a","b","c"]`, three ids that
    never existed, and a reviewer would read three contributing signals off it.

    Elements that are not uuid4 still pass, because `Signal.signal_id` is typed `str` and a
    caller may set its own; they are simply scanned by the shape tripwire like any other
    string, which is what keeps this from being a hole.
    """
    if isinstance(ids, str) or not isinstance(ids, (list, tuple)):
        raise AuditWriteError(
            f"{column} must be a sequence of ids, got {type(ids).__name__}. A bare string "
            "would be stored one character per id (ADR-027 Amendment 1)."
        )
    values = []
    for index, value in enumerate(ids):
        if not isinstance(value, str) or not value:
            raise AuditWriteError(
                f"{column}[{index}] must be a non-empty string id, got {value!r}"
            )
        values.append(value)
    # Scanned as a list so `_iter_strings` walks the elements; serialization for the row
    # itself belongs to `write_record`, which is where the write concern lives.
    _check_no_raw_values(column, values)


def _check_no_raw_values(column: str, payload: object) -> None:
    """Raise `PiiLeakError` if any string leaf of `payload` looks like a raw value.

    Shape-based, so it cannot prove the payload is clean — that is what the
    category-not-value discipline upstream is for. It catches the mistake this project
    is actually exposed to: a detector or an action stuffing the matched text into
    `evidence`, `meta`, or a note "just for debugging".
    """
    for path, text in _iter_strings(payload):
        if column in ID_LIST_COLUMNS:
            # Column-keyed, UUID-only — see `ID_LIST_COLUMNS`. Still conditional: a value
            # that is not a UUID falls through to the tripwire below.
            if _is_uuid(text):
                continue
        elif _is_minted_identifier(path.rsplit(".", 1)[-1], text):
            continue
        shape = _raw_value_shape(text)
        if shape is not None:
            raise PiiLeakError(
                f"{column} at {path} appears to contain a raw value ({shape}); "
                "audit records store the category and span, never the value "
                "(NFR-SEC-001). The row was not written."
            )


# --------------------------------------------------------------------------
# Serialization (05 §3 columns)
# --------------------------------------------------------------------------


def serialize_signals(signals: object) -> str:
    """`signals_json`: `list[Signal]` per 04 §1 — **pure Signals** (ADR-027).

    A detector fault is never in here; it belongs to `detector_failures_json`. Keeping
    the two apart is what lets a consumer count risks off this column without first
    filtering out things that are not risks.
    """
    payload = []
    for signal in signals:
        if not isinstance(signal, Signal):
            raise AuditWriteError(
                f"signals_json takes Signal objects, got {type(signal).__name__}. A "
                "detector fault goes in detector_failures_json (ADR-027)."
            )
        payload.append(signal.model_dump(mode="json"))
    _check_no_raw_values("signals_json", payload)
    return json.dumps(payload, sort_keys=True)


def serialize_failures(failure_outcomes: object) -> str:
    """`detector_failures_json`: the ADR-027 records, via `FailureOutcome.audit_entry()`.

    Written even when the fault failed *open*: a dropped detector that left no trace is
    indistinguishable from one that ran and found nothing, which is the ambiguity
    `cp_detector_failures_total` and this column jointly exist to remove.
    """
    payload = []
    for outcome in failure_outcomes:
        if not isinstance(outcome, FailureOutcome):
            raise AuditWriteError(
                f"detector_failures_json takes FailureOutcome objects, got "
                f"{type(outcome).__name__}"
            )
        payload.append(outcome.audit_entry())
    _check_no_raw_values("detector_failures_json", payload)
    return json.dumps(payload, sort_keys=True)


def serialize_actions(
    *,
    applied: object = (),
    input_redactions: object = (),
    fallback_used: str | None = None,
    quarantined: bool = False,
    review_id: str | None = None,
    promoted_to_escalate: bool = False,
    rescan_findings: object = (),
    notes: object = (),
) -> str:
    """`actions_json`: transforms applied, spans, fallback used (05 §3/§4).

    `input_redactions` is separate from `applied` because ADR-020 makes the input stage
    a distinct claim: the prompt *as sent upstream* differed from the prompt *as
    received*. 05 §3 requires the record to distinguish them while storing neither
    verbatim — so each entry carries stage, span and category only.

    `fallback_used` is the *fact* that the policy's `block_fallback` was sent, recorded
    as its text because that text is policy config the operator wrote, not model output.
    """
    def _edits(items: object, default_stage: str | None = None) -> list[dict[str, Any]]:
        rows = []
        for edit in items:
            row: dict[str, Any] = {
                "transform": edit.transform,
                "label": edit.label,
                "category": edit.category,
                "stage": edit.stage.value if hasattr(edit.stage, "value") else edit.stage,
                "span": list(edit.span) if edit.span is not None else None,
                "whole_sentence": edit.whole_sentence,
            }
            if default_stage is not None:
                row["stage"] = default_stage
            rows.append(row)
        return rows

    payload: dict[str, Any] = {
        "applied": _edits(applied),
        "input_redactions": _edits(input_redactions, default_stage="input"),
        "quarantined": quarantined,
    }
    if fallback_used is not None:
        payload["fallback_used"] = fallback_used
    if review_id is not None:
        payload["review_id"] = review_id
    if promoted_to_escalate:
        payload["promoted_to_escalate"] = True
    if rescan_findings:
        payload["rescan_findings"] = list(rescan_findings)
    if notes:
        payload["notes"] = list(notes)

    _check_no_raw_values("actions_json", payload)
    return json.dumps(payload, sort_keys=True)


# --------------------------------------------------------------------------
# The record
# --------------------------------------------------------------------------


@dataclass
class AuditRecord:
    """One `audit_records` row (05 §3), assembled over a request's lifetime.

    `est_cost_usd` is `float | None` and the None is load-bearing: ADR-022 says a model
    absent from `pricing.models` yields **null, not 0.0 and not a guess**, because zero
    and unknown are different facts. `write_record` refuses to coerce.
    """

    request_id: str
    use_case: str
    policy_version: int
    verdict: Action | str
    stage_summary: str
    ts_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    conversation_id: str | None = None

    signals_json: str = "[]"
    detector_failures_json: str = "[]"
    actions_json: str = "{}"

    tier_requested: str | None = None
    model_used: str | None = None
    upstream_class: str | None = None
    cascade_escalated: bool = False

    tokens_in: int | None = None
    tokens_out: int | None = None
    est_cost_usd: float | None = None

    latency_json: str = "{}"
    sampled_deep: bool = False

    #: The 04 §4.3 step-5 stamp, stamped on EVERY verdict by `from_verdict` — not only on
    #: an ESCALATE. Empty tuple means "nothing contributed", which is a fact; it is stored
    #: as `[]` and never as NULL (ADR-027 Amendment 1).
    contributing_signal_ids: tuple[str, ...] = ()
    failure_record_ids: tuple[str, ...] = ()

    @classmethod
    def from_verdict(
        cls,
        *,
        request_id: str,
        verdict: Verdict,
        stage_summary: str,
        signals: object = (),
        **kwargs: Any,
    ) -> "AuditRecord":
        """Build a record from an engine `Verdict`, stamping both 04 §4.3 step-5 id lists.

        Taking `use_case`/`policy_version` from the verdict rather than from the caller
        is what keeps the record honest about *which policy actually judged this*: the
        engine read them off the `Policy` object it evaluated, so they cannot drift from
        the decision they explain.
        """
        return cls(
            request_id=request_id,
            use_case=verdict.use_case,
            policy_version=verdict.policy_version,
            verdict=verdict.action,
            stage_summary=stage_summary,
            signals_json=serialize_signals(signals),
            detector_failures_json=serialize_failures(verdict.failure_outcomes),
            contributing_signal_ids=verdict.contributing_signal_ids,
            failure_record_ids=verdict.failure_record_ids,
            **kwargs,
        )


def _validate(record: AuditRecord) -> str:
    """Check enum vocabularies and latency keys; return the verdict as its DB value."""
    if not record.request_id:
        raise AuditWriteError("request_id is required (05 §3 PRIMARY KEY)")

    verdict = record.verdict.value if isinstance(record.verdict, Action) else record.verdict
    if verdict not in {a.value for a in Action}:
        raise AuditWriteError(f"verdict {verdict!r} is not in the 04 §4.2 vocabulary")

    if record.stage_summary not in STAGE_SUMMARIES:
        raise AuditWriteError(
            f"stage_summary {record.stage_summary!r} not in {sorted(STAGE_SUMMARIES)} (05 §3)"
        )
    if record.tier_requested is not None and record.tier_requested not in TIERS:
        raise AuditWriteError(
            f"tier_requested {record.tier_requested!r} not in {sorted(TIERS)}; tier names "
            "are `small`/`frontier` (05 §6.1), never a concrete model id"
        )
    if record.upstream_class is not None and record.upstream_class not in UPSTREAM_CLASSES:
        raise AuditWriteError(
            f"upstream_class {record.upstream_class!r} not in {sorted(UPSTREAM_CLASSES)} "
            "(ADR-018)"
        )
    if record.est_cost_usd is not None and record.est_cost_usd < 0:
        raise AuditWriteError(f"est_cost_usd cannot be negative, got {record.est_cost_usd}")

    for column in ID_LIST_COLUMNS:
        _check_id_list(column, getattr(record, column))

    for column in CONTENT_COLUMNS:
        raw = getattr(record, column)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuditWriteError(f"{column} is not valid JSON ({exc})") from exc
        if column == "latency_json":
            # Re-raised as AuditWriteError so the write path has ONE exception type:
            # a caller handling a malformed record must not have to catch ValueError
            # for one column and AuditWriteError for the rest.
            try:
                spans.check_latency_keys(parsed)
            except (ValueError, TypeError) as exc:
                raise AuditWriteError(f"latency_json: {exc}") from exc
        _check_no_raw_values(column, parsed)

    return verdict


def write_record(conn: sqlite3.Connection, record: AuditRecord) -> None:
    """Append one audit row (FR-AUD-001). Never updates; raises before writing on any fault.

    One row per request is the 05 §3 contract, so a duplicate `request_id` surfaces as
    `AuditWriteError` rather than as a silently replaced row — `INSERT OR REPLACE` here
    would quietly make the log rewritable, which is the one property it must not have.
    """
    verdict = _validate(record)
    # Safe to dump unchecked: `_validate` has already refused a non-sequence, a bare string
    # and any element that looks like a raw value. NOT sorted — the stamp is a record of
    # what the engine converged, and reordering it would misrepresent that order as
    # canonical.
    id_lists = tuple(json.dumps(list(getattr(record, c))) for c in ID_LIST_COLUMNS)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO audit_records (
                  request_id, ts_utc, use_case, policy_version, conversation_id,
                  stage_summary, verdict, signals_json, detector_failures_json,
                  contributing_signal_ids, failure_record_ids,
                  actions_json, tier_requested, model_used, upstream_class,
                  cascade_escalated, tokens_in, tokens_out, est_cost_usd,
                  latency_json, sampled_deep
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    record.request_id, record.ts_utc, record.use_case,
                    record.policy_version, record.conversation_id, record.stage_summary,
                    verdict, record.signals_json, record.detector_failures_json,
                    *id_lists,
                    record.actions_json, record.tier_requested, record.model_used,
                    record.upstream_class, int(record.cascade_escalated),
                    record.tokens_in, record.tokens_out, record.est_cost_usd,
                    record.latency_json, int(record.sampled_deep),
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise AuditWriteError(
            f"cannot append audit record {record.request_id!r}: {exc}. 05 §3 is one row "
            "per request and append-only; an existing row is never replaced."
        ) from exc


def canonical_view(conn: sqlite3.Connection, request_id: str) -> dict[str, Any]:
    """The 05 §4 canonical JSON view, assembled from `audit_records` (+ any override).

    Groups the flat columns into the documented nesting (`model`, `cost`, `latency`) so
    the README/proposal shape and the stored shape cannot drift apart. `override` is
    present only when a reviewer has decided, because an absent key and a null decision
    say different things.
    """
    row = conn.execute(
        "SELECT * FROM audit_records WHERE request_id = ?", (request_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"no audit record {request_id!r}")

    view: dict[str, Any] = {
        "request_id": row["request_id"],
        "ts_utc": row["ts_utc"],
        "use_case": row["use_case"],
        "policy_version": row["policy_version"],
        "verdict": row["verdict"],
        "signals": json.loads(row["signals_json"]),
        "detector_failures": json.loads(row["detector_failures_json"]),
        # Top-level in 05 §4, alongside `signals`/`detector_failures` rather than nested in
        # either: the stamp is a claim about which of BOTH lists decided the verdict, so it
        # cannot sit inside one of them.
        "contributing_signal_ids": json.loads(row["contributing_signal_ids"]),
        "failure_record_ids": json.loads(row["failure_record_ids"]),
        "actions": json.loads(row["actions_json"]),
        "model": {
            "tier_requested": row["tier_requested"],
            "used": row["model_used"],
            "upstream_class": row["upstream_class"],
            "cascade_escalated": bool(row["cascade_escalated"]),
        },
        "cost": {
            "tokens_in": row["tokens_in"],
            "tokens_out": row["tokens_out"],
            # Stays null when unknown (ADR-022): `or 0.0` here would convert "we could
            # not price this" into "it was free" — the exact conflation the ADR forbids.
            "est_usd": row["est_cost_usd"],
        },
        "latency": json.loads(row["latency_json"]),
        "sampled_deep": bool(row["sampled_deep"]),
    }
    if row["conversation_id"] is not None:
        view["conversation_id"] = row["conversation_id"]

    review = conn.execute(
        """SELECT review_id, status, decision_ts, reviewer_note FROM review_items
           WHERE request_id = ? AND status != 'pending'
           ORDER BY decision_ts DESC LIMIT 1""",
        (request_id,),
    ).fetchone()
    if review is not None:
        view["override"] = {
            "decision": "approve" if review["status"] == "approved" else "reject",
            "note": review["reviewer_note"],
            "ts": review["decision_ts"],
            "review_id": review["review_id"],
        }
    return view
