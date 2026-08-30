"""In-process, thread-safe cost ledger over the 05 §3 audit tables.

Answers three questions for the input lane, and nothing else:

  * `spend_in_window(use_case, seconds)` — tokens / usd / requests over a rolling window.
  * `month_spend_usd(use_case)` — the figure `budget.monthly_usd` is a ceiling on.
  * `conversation_turns(conversation_id)` — turn count + token total for one conversation.

**No new table.** 05 §3 already declares `cost_ledger (use_case, month, spent_usd)` and
`audit_records` already carries `tokens_in`, `tokens_out` and `est_cost_usd`, so a SELECT
suffices and the ledger survives restart because the rows do.

**The two sources are added, not merged, and the split is deliberate.** `cost_ledger` is a
*carried baseline* — the state a deployment starts a month with, and what 07 beat 7b
pre-seeds to put UC-3 near its ceiling. `audit_records` is what this process has since
measured. Nothing in this repo writes `cost_ledger` from `audit_records`, which is what
keeps the sum from double-counting; if a writer is ever added it must replace the audit
term rather than accumulate beside it.

`est_cost_usd` is NULL for a dev-class provider by ADR-018/ADR-022, and SQLite's `SUM`
skips NULLs. That is the honest arithmetic — a dev-class row contributes no dollars
because its accounting is not a measurement — but it means a ledger read cannot
distinguish "spent nothing" from "spent an unknown amount", so `priced_requests` is
returned beside the total and a caller comparing against a ceiling can see the gap.

NFR-SEC-001: nothing here reads, returns or stores message text. `observe_turn` keeps a
salted hash of a normalized turn, in memory only, and the salt is per-process so a hash
cannot be dictionary-attacked out of a heap dump or carried between runs.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

#: Rolling window for the `loop_max_requests_per_min` check — the unit that field names.
LOOP_WINDOW_S = 60

#: Consecutive-turn hashes retained per conversation. Two is all `loop_guard`'s
#: near-identity rule needs (it compares against the immediately preceding turn); the
#: extra slot exists so a retry that repeats a turn twice is still visible.
TURN_RING = 4

#: How long a ledger read may be reused before the DB is asked again. The input lane runs
#: on every request and `cost_budget` has a <1 ms budget (04 §2), so an uncached SELECT per
#: request would put SQLite inside a 1 ms arithmetic budget. A budget ceiling is a
#: month-scale quantity, so a sub-second staleness cannot change a verdict that is not
#: already inside its own rounding error.
CACHE_TTL_S = 0.5

_NORMALIZE = re.compile(r"\s+")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def normalize_turn(text: str) -> str:
    """Casefold + collapse whitespace. The `loop_guard` near-identity unit."""
    return _NORMALIZE.sub(" ", text.strip().casefold())


@dataclass(frozen=True)
class Spend:
    """One window's spend. `usd` omits unpriced rows; `priced_requests` says how many."""

    tokens: int
    usd: float
    requests: int
    priced_requests: int

    def as_dict(self) -> dict[str, Any]:
        return {"tokens": self.tokens, "usd": self.usd, "requests": self.requests,
                "priced_requests": self.priced_requests}


@dataclass(frozen=True)
class Turns:
    """One conversation's totals."""

    requests: int
    tokens: int
    requests_in_window: int
    repeated_turn: bool

    def as_dict(self) -> dict[str, Any]:
        return {"requests": self.requests, "tokens": self.tokens,
                "requests_in_window": self.requests_in_window,
                "repeated_turn": self.repeated_turn}


@dataclass
class _Conversation:
    """Per-conversation in-process state. Hashes only — never text (NFR-SEC-001)."""

    hashes: deque[str] = field(default_factory=lambda: deque(maxlen=TURN_RING))
    seen_at: deque[float] = field(default_factory=lambda: deque(maxlen=256))


class CostLedger:
    """Thread-safe reader over `audit_records` + `cost_ledger`, with a hot-path cache.

    One `threading.Lock` guards both the cache and the per-conversation rings. The
    connection is used under that lock too: `sqlite3` connections are not safe to share
    across threads by default, and the gateway's audit connection is process-wide.
    """

    def __init__(self, conn: sqlite3.Connection | None = None, *,
                 db_path: str | Path | None = None,
                 cache_ttl_s: float = CACHE_TTL_S) -> None:
        self._explicit_conn = conn
        self._db_path = db_path
        self._local = threading.local()
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, ...], tuple[float, Any]] = {}
        self._cache_ttl_s = cache_ttl_s
        self._conversations: dict[str, _Conversation] = {}
        self._read_errors = 0
        self._last_read_error: str | None = None
        # Per-process, never persisted: a turn hash must not be comparable across runs.
        self._salt = os.urandom(16)

    # -- binding ---------------------------------------------------------

    def bind(self, conn: sqlite3.Connection | None = None, *,
             db_path: str | Path | None = None) -> None:
        """Point the ledger at a database. Resets everything derived from the old one.

        **Two binding modes, and the difference is threading.** `db_path` is the production
        mode: the ledger opens **one connection per calling thread**, which is the same
        arrangement `Gateway.conn` documents (ADR-006 chose WAL precisely so several
        connections to one file are safe). A single shared connection would be the bug that
        pattern exists to avoid — `sqlite3` rejects cross-thread use, and because
        `_query` treats a read failure as absence of evidence, the cost plane would fail
        **silently** rather than loudly. `conn` is the test/eval mode: an explicit
        connection, including `:memory:`, which per-thread opening cannot share.

        **Conversation state is cleared too, and that is the point rather than tidiness.** A
        new database is a new deployment's view of history, so turn hashes accumulated
        against a different one describe conversations this ledger cannot see. Carrying them
        over would let `loop_guard` fire on a "repeat" whose first turn lives in another DB —
        and, because each gateway binds at startup, it is also what stops one test's turns
        from becoming the next test's loop (a process-global ledger otherwise makes
        `repeated_turn` order-dependent).
        """
        with self._lock:
            self._explicit_conn = conn
            self._db_path = db_path
            self._local = threading.local()
            self._cache.clear()
            self._conversations.clear()

    @property
    def bound(self) -> bool:
        return self._explicit_conn is not None or self._db_path is not None

    @property
    def read_errors(self) -> tuple[int, str | None]:
        """`(count, last_error_class)` for reads that failed.

        Exposed because `_query` deliberately fails soft, and a fail-soft path with no
        counter is indistinguishable from one that never ran. The class name only — never a
        message, which can quote the row it failed on (NFR-SEC-001).
        """
        with self._lock:
            return (self._read_errors, self._last_read_error)

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()

    # -- reads -----------------------------------------------------------

    def spend_in_window(self, use_case: str, seconds: int) -> Spend:
        """Tokens / usd / requests for `use_case` over the last `seconds`.

        An unbound ledger returns an empty `Spend` rather than raising: a cost ceiling that
        no ledger can evidence has not been shown to be breached, and `cost_budget` reports
        no signal. A detector that raised here would be resolved by policy `fail_mode`,
        which on UC-3 (`cost: fail_closed`) turns a missing DB into an escalate — a failure
        of the *harness* wearing a policy decision's clothes.
        """
        cutoff = _iso(_now() - timedelta(seconds=seconds))
        return self._cached(("spend", use_case, str(seconds)),
                            lambda: self._read_spend(use_case, cutoff))

    def month_spend_usd(self, use_case: str, *, month: str | None = None) -> float:
        """Carried `cost_ledger` baseline + measured `audit_records` spend this month."""
        key = month or _iso(_now())[:7]
        return self._cached(("month", use_case, key),
                            lambda: self._read_month(use_case, key))

    def conversation_turns(self, conversation_id: str) -> Turns:
        """Turn count + token total for one conversation, plus its in-window rate."""
        cutoff = _iso(_now() - timedelta(seconds=LOOP_WINDOW_S))
        totals = self._cached(("conv", conversation_id),
                              lambda: self._read_conversation(conversation_id, cutoff))
        with self._lock:
            state = self._conversations.get(conversation_id)
            repeated = bool(state and len(state.hashes) >= 2
                            and state.hashes[-1] == state.hashes[-2])
            in_process = self._window_count(state) if state else 0
        persisted, tokens, persisted_window = totals
        # In-process turns are counted beside persisted ones because a blocked request
        # never reaches the audit writer with usage, yet it is exactly the traffic a loop
        # produces. `max` rather than a sum: the same turn may appear in both.
        return Turns(requests=max(persisted, in_process), tokens=tokens,
                     requests_in_window=max(persisted_window, in_process),
                     repeated_turn=repeated)

    def observe_turn(self, conversation_id: str | None, text: str) -> bool:
        """Record one turn's normalized hash; True if it repeats the previous turn.

        Called once per request from the input lane, before the detector runs, so
        `loop_guard` sees the current turn. Idempotent per call site, not per text: two
        genuinely identical consecutive turns are the signal, so de-duplicating them here
        would delete what the detector is looking for.
        """
        if not conversation_id:
            return False
        digest = hashlib.blake2b(
            normalize_turn(text).encode("utf-8"), key=self._salt, digest_size=16
        ).hexdigest()
        with self._lock:
            state = self._conversations.setdefault(conversation_id, _Conversation())
            repeated = bool(state.hashes) and state.hashes[-1] == digest
            state.hashes.append(digest)
            state.seen_at.append(time.monotonic())
            return repeated

    def forget(self, conversation_id: str | None = None) -> None:
        """Drop in-process conversation state (all of it when `conversation_id` is None)."""
        with self._lock:
            if conversation_id is None:
                self._conversations.clear()
            else:
                self._conversations.pop(conversation_id, None)
            self._cache.clear()

    # -- internals -------------------------------------------------------

    @staticmethod
    def _window_count(state: _Conversation) -> int:
        floor = time.monotonic() - LOOP_WINDOW_S
        return sum(1 for seen in state.seen_at if seen >= floor)

    def _connection(self) -> sqlite3.Connection | None:
        """This thread's connection, or the explicitly bound one. `None` when unbound.

        Opened lazily per thread — see `bind` for why one shared connection is wrong here.
        """
        if self._explicit_conn is not None:
            return self._explicit_conn
        if self._db_path is None:
            return None
        conn = getattr(self._local, "conn", None)
        if conn is None:
            from controlplane.audit.db import connect

            try:
                conn = connect(self._db_path)
            except sqlite3.Error as exc:
                self._note_read_error(exc)
                return None
            self._local.conn = conn
        return conn

    def _note_read_error(self, exc: BaseException) -> None:
        self._read_errors += 1
        self._last_read_error = type(exc).__name__

    def _cached(self, key: tuple[str, ...], compute: Any) -> Any:
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and now - hit[0] < self._cache_ttl_s:
                return hit[1]
        value = compute() if self.bound else _EMPTY[key[0]]
        with self._lock:
            self._cache[key] = (now, value)
        return value

    def _query(self, sql: str, params: tuple[Any, ...]) -> sqlite3.Row | None:
        """One read. Returns `None` — not a raise — when the DB cannot answer.

        Fail-soft for the reason `spend_in_window` documents: an unreadable ledger has not
        *shown* a breach, and raising here would be resolved by policy `fail_mode`, turning a
        harness problem into UC-3's escalate. The failure is counted in `read_errors` so it
        stays discoverable rather than silent.
        """
        conn = self._connection()
        if conn is None:
            return None
        try:
            with self._lock:
                return conn.execute(sql, params).fetchone()
        except sqlite3.Error as exc:
            # A missing table, a locked DB, or a cross-thread handle. Absence of evidence.
            with self._lock:
                self._note_read_error(exc)
            return None

    def _read_spend(self, use_case: str, cutoff: str) -> Spend:
        row = self._query(
            """
            SELECT COALESCE(SUM(COALESCE(tokens_in, 0) + COALESCE(tokens_out, 0)), 0) AS tokens,
                   COALESCE(SUM(est_cost_usd), 0.0) AS usd,
                   COUNT(*) AS requests,
                   SUM(CASE WHEN est_cost_usd IS NOT NULL THEN 1 ELSE 0 END) AS priced
              FROM audit_records
             WHERE use_case = ? AND ts_utc >= ?
            """,
            (use_case, cutoff),
        )
        if row is None:
            return _EMPTY_SPEND
        return Spend(tokens=int(row["tokens"] or 0), usd=float(row["usd"] or 0.0),
                     requests=int(row["requests"] or 0),
                     priced_requests=int(row["priced"] or 0))

    def _read_month(self, use_case: str, month: str) -> float:
        carried = self._query(
            "SELECT COALESCE(SUM(spent_usd), 0.0) AS usd FROM cost_ledger "
            "WHERE use_case = ? AND month = ?",
            (use_case, month),
        )
        measured = self._query(
            "SELECT COALESCE(SUM(est_cost_usd), 0.0) AS usd FROM audit_records "
            "WHERE use_case = ? AND substr(ts_utc, 1, 7) = ?",
            (use_case, month),
        )
        total = 0.0
        if carried is not None:
            total += float(carried["usd"] or 0.0)
        if measured is not None:
            total += float(measured["usd"] or 0.0)
        return total

    def _read_conversation(self, conversation_id: str, cutoff: str) -> tuple[int, int, int]:
        row = self._query(
            """
            SELECT COUNT(*) AS requests,
                   COALESCE(SUM(COALESCE(tokens_in, 0) + COALESCE(tokens_out, 0)), 0) AS tokens,
                   SUM(CASE WHEN ts_utc >= ? THEN 1 ELSE 0 END) AS windowed
              FROM audit_records
             WHERE conversation_id = ?
            """,
            (cutoff, conversation_id),
        )
        if row is None:
            return (0, 0, 0)
        return (int(row["requests"] or 0), int(row["tokens"] or 0), int(row["windowed"] or 0))


_EMPTY_SPEND = Spend(tokens=0, usd=0.0, requests=0, priced_requests=0)

#: What an unbound (or unreadable) ledger reports per query kind — see `spend_in_window`.
_EMPTY: dict[str, Any] = {"spend": _EMPTY_SPEND, "month": 0.0, "conv": (0, 0, 0)}


#: Process-wide default, bound by the gateway at startup. A module-level singleton for the
#: same reason `pipeline.LIVE` is one: the input lane needs a ledger without threading a
#: handle through every caller, and the eval harnesses need to bind their own DB.
LEDGER = CostLedger()


def seed_month(conn: sqlite3.Connection, use_case: str, spent_usd: float,
               *, month: str | None = None) -> None:
    """Set the carried `cost_ledger` baseline for one use case and month.

    Test and demo support (07 beat 7b pre-seeds UC-3 near its ceiling). Not called on the
    request path: the gateway measures spend into `audit_records`, and a second writer
    accumulating into `cost_ledger` would double-count against `month_spend_usd`.
    """
    key = month or _iso(_now())[:7]
    with conn:
        conn.execute(
            "INSERT INTO cost_ledger (use_case, month, spent_usd) VALUES (?,?,?) "
            "ON CONFLICT(use_case, month) DO UPDATE SET spent_usd = excluded.spent_usd",
            (use_case, key, float(spent_usd)),
        )
    LEDGER.invalidate()
