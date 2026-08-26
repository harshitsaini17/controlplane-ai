"""SQLite bootstrap for audit + metrics storage.

Implements the schema in 05 §3 verbatim (ADR-006: SQLite in WAL mode, no
ClickHouse/Kafka/Redis). Tables: `audit_records`, `review_items`,
`deep_audit_results`, `metrics_events`, `cost_ledger`.

Append-only semantics for `audit_records` are a discipline of the writers in
`audit/records.py`, not a database constraint — SQLite cannot revoke UPDATE from
an in-process connection. The rule from 05 §3 still binds: nothing outside
`review_items.quarantined_text` ever stores model output verbatim, and that column
is written post-masking of Tier-1 PII spans (NFR-SEC-001).

The database path comes from the `CP_DB_PATH` env var (05 §6); its value is never
logged (NFR-SEC-002).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

#: Env var naming the SQLite file (05 §6).
DB_PATH_ENV = "CP_DB_PATH"

#: Used when `CP_DB_PATH` is unset — matches `.env.example`.
DEFAULT_DB_PATH = "./controlplane.db"

#: DDL transcribed from 05 §3. `IF NOT EXISTS` makes bootstrap idempotent so the
#: demo and eval entry points can each call `init_db()` safely.
SCHEMA_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS audit_records (
      request_id TEXT PRIMARY KEY, ts_utc TEXT, use_case TEXT, policy_version INTEGER,
      conversation_id TEXT NULL, stage_summary TEXT,          -- input|streamed|completed
      verdict TEXT CHECK(verdict IN ('pass','edit','block','escalate')),
      signals_json TEXT,            -- list[Signal] per 04 §1 (evidence fields only — no raw PII).
                                    -- PURE Signals: a detector fault is never one (ADR-027)
      detector_failures_json TEXT,  -- list[DetectorFailureRecord] per 04 §5 (ADR-027):
                                    -- {failure_id, detector, error_class, stage,
                                    --  fail_mode_applied, ts}. Operational events, not
                                    -- content risks: no span, no plane, no label, no text,
                                    -- so this column has no NFR-SEC-001 surface at all
      actions_json TEXT,            -- transforms applied, spans, fallback used
      -- Tier binding + provenance (05 §3 as amended by ADR-018 and the tier-mapping ruling).
      -- `tier_requested` is the tier the router picked PRE-dispatch; `model_used` is the
      -- CONCRETE provider model id that answered, so a tier name never masquerades as a
      -- model. `upstream_class` travels with the row because whether a number may be
      -- published is a property of the data, not of whoever reads it later (AGENTS.md §7).
      tier_requested TEXT CHECK(tier_requested IN ('small','frontier')),
      model_used TEXT,
      upstream_class TEXT CHECK(upstream_class IN ('dev','measured')),
      cascade_escalated INTEGER,
      tokens_in INTEGER, tokens_out INTEGER, est_cost_usd REAL,
      latency_json TEXT,            -- per-detector ms + gateway_overhead_ms + upstream_ms
      sampled_deep INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS review_items (
      review_id TEXT PRIMARY KEY, request_id TEXT REFERENCES audit_records,
      ts_created TEXT, quarantined_text TEXT,     -- stored ONLY here; PII spans masked at write time
      status TEXT CHECK(status IN ('pending','approved','rejected')),
      decision_ts TEXT NULL, reviewer_note TEXT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS deep_audit_results (
      request_id TEXT REFERENCES audit_records, ts TEXT,
      method TEXT,                  -- semantic_entropy | fairness_spot
      result_json TEXT              -- clusters, entropy value, or fairness check outcome
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS metrics_events (   -- flat event stream; dashboard aggregates
      ts TEXT, name TEXT, value REAL, labels_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cost_ledger (
      use_case TEXT, month TEXT, spent_usd REAL, PRIMARY KEY (use_case, month)
    )
    """,
)

#: Table names created by `SCHEMA_DDL`, in 05 §3 order.
TABLES: tuple[str, ...] = (
    "audit_records",
    "review_items",
    "deep_audit_results",
    "metrics_events",
    "cost_ledger",
)


def resolve_db_path() -> Path:
    """Database path from `CP_DB_PATH` (05 §6), falling back to `DEFAULT_DB_PATH`."""
    return Path(os.environ.get(DB_PATH_ENV) or DEFAULT_DB_PATH)


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a connection with the ADR-006 pragmas applied.

    WAL mode lets the dashboard read while the gateway writes (ADR-007 reads the
    same file); foreign keys are enabled because 05 §3 declares REFERENCES.
    """
    path = Path(db_path) if db_path is not None else resolve_db_path()
    if path.parent != Path("") and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")  # ADR-006
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Create the 05 §3 tables if absent and return the open connection.

    Idempotent: safe to call at gateway startup, in `demo/run_script.py`, and from
    each `eval/` entry point.
    """
    conn = connect(db_path)
    with conn:
        for ddl in SCHEMA_DDL:
            conn.execute(ddl)
    return conn
