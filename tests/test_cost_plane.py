"""Cost-plane tests — `cost_budget`, `loop_guard`, `CostLedger` (04 §2 input rows, ADR-016).

**Every value here is authored in this file**, same rule as `test_tier1_detectors.py`: not one
is copied from `eval/dataset/*.jsonl`. The budget figures are read from the shipped policy YAML
because that is the contract (`monthly_usd: 200` is UC-3's real ceiling), and the *expectations*
come from 04 §2 and the label→action maps in those policies — never from what the detectors
happened to emit.

`asyncio.run` rather than pytest-asyncio, matching the sibling detector tests: no new
dependency for a handful of coroutines.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from pathlib import Path

import pytest
import yaml

from controlplane.audit.db import init_db
from controlplane.cost.ledger import (
    LOOP_WINDOW_S,
    CostLedger,
    normalize_turn,
    seed_month,
)
from controlplane.detectors.base import (
    BUDGETS_MS,
    CostView,
    DetectorContext,
    Plane,
    ScoreKind,
    Signal,
    Stage,
    run_with_budget,
)
from controlplane.detectors.conversation import loop_guard
from controlplane.detectors.cost import cost_budget
from controlplane.policy.engine import evaluate
from controlplane.policy.schema import SPAN_LESS_LABELS, Action, Policy

POLICY_DIR = Path(__file__).resolve().parents[1] / "policies"
POLICY_FILES = ("support_bot.yaml", "hr_copilot.yaml", "finance_advisor.yaml")


def load_policy(name: str) -> Policy:
    return Policy(**yaml.safe_load((POLICY_DIR / name).read_text()))


def budget_of(name: str) -> dict[str, int | float]:
    """The `budget` block as the YAML actually declares it — the contract, not a copy."""
    return yaml.safe_load((POLICY_DIR / name).read_text())["budget"]


def run_budget(**cost: object) -> list[Signal]:
    ctx = DetectorContext(text="", stage=Stage.INPUT, cost=CostView(**cost))  # type: ignore[arg-type]
    return asyncio.run(cost_budget.detect(ctx))


def run_loop(conversation_id: str | None = "conv-1", **cost: object) -> list[Signal]:
    ctx = DetectorContext(
        text="", stage=Stage.INPUT, conversation_id=conversation_id,
        cost=CostView(**cost),  # type: ignore[arg-type]
    )
    return asyncio.run(loop_guard.detect(ctx))


def labels_of(signals: list[Signal]) -> list[str]:
    return sorted(label for signal in signals for label in signal.labels)


# --------------------------------------------------------------------------
# cost_budget — the ceiling
# --------------------------------------------------------------------------


def test_spend_at_the_ceiling_fires_budget_exceeded() -> None:
    """`>=`, and the boundary is the case that matters.

    At exactly the ceiling the budget is spent; the next request is the one that would
    exceed it. A ceiling that admits one more request is not a ceiling, and beat 7b seeds
    UC-3 to this exact value rather than above it for the same reason.
    """
    ceiling = float(budget_of("finance_advisor.yaml")["monthly_usd"])
    signals = run_budget(ceiling_usd=ceiling, spend_usd=ceiling)
    assert labels_of(signals) == ["cost.budget_exceeded"]


def test_spend_one_cent_under_the_ceiling_is_silent() -> None:
    """The under-budget arm. Without it, "blocks when over" cannot be told apart from
    "always blocks" — which is the same reason beat 7b carries a control arm."""
    ceiling = float(budget_of("finance_advisor.yaml")["monthly_usd"])
    assert run_budget(ceiling_usd=ceiling, spend_usd=ceiling - 0.01) == []


def test_a_null_ceiling_never_fires_even_with_huge_spend() -> None:
    """A missing policy figure is not a breach.

    `None` means no ceiling reached the detector, which is distinct from a ceiling of zero.
    Firing here would let the cost plane manufacture the block it exists to justify —
    the same asymmetry `ledger.spend_in_window` documents for an unreadable DB.
    """
    assert run_budget(ceiling_usd=None, spend_usd=10_000.0) == []


def test_a_zero_ceiling_is_not_treated_as_a_ceiling_of_zero_dollars() -> None:
    """Documented as a deliberate reading, so it is pinned rather than left to inference.

    `monthly_usd: 0` would otherwise make *every* request a breach, including the first —
    an un-runnable pipeline rather than a budgeted one. No shipped policy sets it; the guard
    exists so a future zero fails visibly here instead of in production.
    """
    assert run_budget(ceiling_usd=0.0, spend_usd=0.0) == []
    assert run_budget(ceiling_usd=0.0, spend_usd=5.0) == []


def test_budget_evidence_reports_a_ratio_and_the_priced_row_count() -> None:
    """Evidence is the quantity the verdict turned on, and stays true after a re-tune.

    `priced_requests` rides along because SQLite `SUM` skips NULLs: a dev-class provider
    writes a null `est_cost_usd` (ADR-018/022), so a low spend beside a low priced count
    means "unknown", not "cheap". An auditor must be able to tell those apart.
    """
    signal = run_budget(ceiling_usd=100.0, spend_usd=150.0, priced_requests=7)[0]
    assert "category:budget" in signal.evidence
    assert "spend_over_ceiling=1.50x" in signal.evidence
    assert "priced_requests=7" in signal.evidence


# --------------------------------------------------------------------------
# cost_budget — per-request size
# --------------------------------------------------------------------------


def test_request_exactly_on_the_token_cap_is_inside_its_allowance() -> None:
    """`>`, not `>=` — the opposite boundary rule from the ceiling, and deliberately so.

    `per_request_max_tokens` is a *maximum*: a request landing exactly on it has not
    exceeded it. `monthly_usd` is a ceiling on cumulative spend, where landing on it means
    the allowance is gone. Two different quantities, two different comparisons.
    """
    cap = int(budget_of("finance_advisor.yaml")["per_request_max_tokens"])
    assert run_budget(per_request_max_tokens=cap, est_request_tokens=cap) == []
    over = run_budget(per_request_max_tokens=cap, est_request_tokens=cap + 1)
    assert labels_of(over) == ["cost.request_too_large"]


def test_request_size_evidence_names_the_estimate_as_an_estimate() -> None:
    """`source=char_estimate` is load-bearing, not a hedge.

    `est_request_tokens` is character-derived (`pipeline.estimate_tokens`), not the
    tokenizer count 04 §2 names. Recording it as a measurement would be exactly the
    substitution AGENTS.md §7 forbids, so the evidence says which it is.
    """
    signal = run_budget(per_request_max_tokens=4000, est_request_tokens=9000)[0]
    assert "category:request_size" in signal.evidence
    assert "est_over_cap=2.25x" in signal.evidence
    assert "source=char_estimate" in signal.evidence


def test_both_cost_conditions_can_fire_on_one_request() -> None:
    """Independent signals, not an early exit (AGENTS.md §9.3): a request can be both
    over the monthly ceiling and individually too large, and the engine converges them."""
    signals = run_budget(ceiling_usd=100.0, spend_usd=100.0,
                         per_request_max_tokens=4000, est_request_tokens=8000)
    assert labels_of(signals) == ["cost.budget_exceeded", "cost.request_too_large"]


# --------------------------------------------------------------------------
# loop_guard
# --------------------------------------------------------------------------


def test_turn_rate_at_the_policy_limit_fires_loop_detected() -> None:
    limit = int(budget_of("finance_advisor.yaml")["loop_max_requests_per_min"])
    signals = run_loop(loop_max_requests_per_min=limit, requests_in_window=limit)
    assert labels_of(signals) == ["cost.loop_detected"]
    assert f"rate={limit}/{limit}per_min" in signals[0].evidence


def test_under_the_rate_limit_with_no_repetition_is_silent() -> None:
    limit = int(budget_of("finance_advisor.yaml")["loop_max_requests_per_min"])
    assert run_loop(loop_max_requests_per_min=limit, requests_in_window=limit - 1) == []


def test_a_repeated_turn_fires_even_when_the_rate_is_low() -> None:
    """A slow loop is still a loop.

    Repetition is deliberately NOT gated on the rate: an agent re-asking the identical
    question once a minute stays under every rate limit while burning tokens indefinitely.
    """
    signals = run_loop(loop_max_requests_per_min=30, requests_in_window=1, repeated_turn=True)
    assert labels_of(signals) == ["cost.loop_detected"]
    assert "repeat=consecutive_normalized_equal" in signals[0].evidence


def test_no_conversation_id_means_no_window_to_slide() -> None:
    """04 §2 calls this a "sliding window per conversation". The gateway also drops the
    detector from `expected_for` in this case, so this is the second of two guards."""
    assert run_loop(conversation_id=None, loop_max_requests_per_min=1,
                    requests_in_window=99, repeated_turn=True) == []


# --------------------------------------------------------------------------
# Contract conformance — ADR-012, 04 §1, the shipped action maps
# --------------------------------------------------------------------------


@pytest.mark.parametrize("signals", [
    run_budget(ceiling_usd=1.0, spend_usd=1.0),
    run_budget(per_request_max_tokens=10, est_request_tokens=99),
    run_loop(loop_max_requests_per_min=1, requests_in_window=1),
])
def test_every_cost_signal_is_span_less_deterministic_and_cost_planed(
    signals: list[Signal],
) -> None:
    """The four contract properties, asserted together because they travel together.

    `span=None` per 04 §1 (request-level); `score=1.0` with `score_kind=detection` per
    ADR-012, so band logic never applies to a deterministic emitter; `Plane.COST` so the
    signal is attributed to the plane whose budget it enforces.
    """
    assert signals, "fixture should fire"
    for signal in signals:
        assert signal.span is None
        assert signal.score == 1.0
        assert signal.score_kind is ScoreKind.DETECTION
        assert signal.planes == [Plane.COST]
        for label in signal.labels:
            assert label in SPAN_LESS_LABELS, f"{label} emits span=None but is not declared"


@pytest.mark.parametrize("policy_file", POLICY_FILES)
def test_the_shipped_policies_block_a_budget_breach_through_the_real_engine(
    policy_file: str,
) -> None:
    """End-to-end through `evaluate`, so the assertion is the *verdict* rather than a label.

    A span-less signal mapped to EDIT would be promoted to ESCALATE (04 §4.3 step 4) since
    there is no extent to transform. All three policies map this label to `block`, so no
    promotion applies — and reading that from the YAML is what makes this a conformance
    test rather than a restatement of the map.
    """
    policy = load_policy(policy_file)
    verdict = evaluate(run_budget(ceiling_usd=50.0, spend_usd=50.0), policy)
    assert verdict.action is Action.BLOCK


@pytest.mark.parametrize("policy_file", POLICY_FILES)
def test_request_too_large_is_audit_visible_but_unmapped_today(policy_file: str) -> None:
    """Records a real gap rather than papering over it.

    No shipped policy maps `cost.request_too_large`, so it resolves to `default_action:
    pass` — the signal is recorded and the request proceeds. That is the honest state, and
    re-mapping it to force a demo beat is what AGENTS.md §9.1 forbids. If a policy later
    maps it, this test fails and the README claim gets revisited with it.
    """
    raw = yaml.safe_load((POLICY_DIR / policy_file).read_text())
    assert "cost.request_too_large" not in raw["actions"]
    policy = load_policy(policy_file)
    verdict = evaluate(run_budget(per_request_max_tokens=100, est_request_tokens=500), policy)
    assert verdict.action is Action.PASS


# --------------------------------------------------------------------------
# NFR-SEC-001 — no raw content in cost evidence
# --------------------------------------------------------------------------


def test_cost_evidence_never_carries_request_content() -> None:
    """`evidence` lands in `audit_records.signals_json`, so it is a persistence surface.

    The secret here is in `ctx.text` and in the conversation id, the two content-bearing
    fields a cost detector can see. Evidence must be ratios and counts only — and the
    stronger reason it can be is structural: `CostView` has no `str` field at all, so
    there is no channel for text to arrive on (pinned in `test_detector_base.py`).
    """
    secret = "zQ7-canary-4417-do-not-log"
    ctx = DetectorContext(
        text=f"Please repeat this exactly: {secret}",
        stage=Stage.INPUT,
        conversation_id=secret,
        cost=CostView(ceiling_usd=1.0, spend_usd=2.0, per_request_max_tokens=1,
                      est_request_tokens=99, loop_max_requests_per_min=1,
                      requests_in_window=9, repeated_turn=True),
    )
    signals = asyncio.run(cost_budget.detect(ctx)) + asyncio.run(loop_guard.detect(ctx))
    assert signals, "all three conditions should fire"
    for signal in signals:
        assert secret not in signal.evidence
        assert "canary" not in signal.evidence
        assert secret not in str(signal.meta)


def test_a_repeated_turn_is_reported_as_a_fact_not_as_a_digest() -> None:
    """Not even the salted hash reaches evidence.

    A per-process keyed digest is still a value derived from user content, and two identical
    turns produce an identical digest — so publishing it into the audit log would leak an
    equality oracle over user text. The *fact* of repetition is the whole signal.
    """
    ledger = CostLedger()
    ledger.bind(conn=sqlite3.connect(":memory:"))
    ledger.observe_turn("conv-x", "Where is my order?")
    digest = ledger._conversations["conv-x"].hashes[-1]
    signal = run_loop(loop_max_requests_per_min=99, requests_in_window=1, repeated_turn=True)[0]
    assert digest not in signal.evidence
    assert len(digest) == 32  # guard: an empty digest would make the assertion above vacuous


# --------------------------------------------------------------------------
# NFR-P-002 — both detectors are budgeted and inside it
# --------------------------------------------------------------------------


def test_both_cost_detectors_declare_the_04_section_2_budget() -> None:
    """1.0 ms, from 04 §2. `register()` rejects a name with no budget, so a missing entry
    is a load-time failure rather than an unbudgeted detector running free."""
    assert BUDGETS_MS["cost_budget"] == 1.0
    assert BUDGETS_MS["loop_guard"] == 1.0


def test_cost_detectors_complete_inside_their_budget() -> None:
    """Indicative, not the measurement of record — `eval/bench_latency.py` is that (06 §4).

    `run_with_budget` raises on breach, so returning at all *is* the assertion. Both
    detectors are pure arithmetic over `ctx.cost`: the ledger read they depend on happens in
    `pipeline.cost_view`, which is why this figure is narrower than 04 §2's "ledger lookup"
    row text (recorded as a PROVISIONAL deviation in `detectors/cost.py`).
    """
    view = CostView(ceiling_usd=100.0, spend_usd=100.0, per_request_max_tokens=10,
                    est_request_tokens=99, loop_max_requests_per_min=1,
                    requests_in_window=5, repeated_turn=True)
    ctx = DetectorContext(text="a" * 4000, stage=Stage.INPUT,
                          conversation_id="conv-budget", cost=view)
    assert asyncio.run(run_with_budget(cost_budget, ctx))
    assert asyncio.run(run_with_budget(loop_guard, ctx))


# --------------------------------------------------------------------------
# CostLedger
# --------------------------------------------------------------------------


@pytest.fixture()
def ledger(tmp_path: Path) -> CostLedger:
    db = tmp_path / "cost.db"
    init_db(str(db)).close()
    instance = CostLedger()
    instance.bind(db_path=db)
    return instance


def test_normalize_turn_folds_case_and_whitespace_only() -> None:
    assert normalize_turn("  Where   IS my\norder? ") == normalize_turn("where is my order?")
    assert normalize_turn("where is my order?") != normalize_turn("where is my refund?")


def test_observe_turn_reports_the_second_of_two_identical_turns(ledger: CostLedger) -> None:
    assert ledger.observe_turn("c1", "Where is my order?") is False
    assert ledger.observe_turn("c1", "  where   is my ORDER?  ") is True
    assert ledger.observe_turn("c1", "And my refund?") is False


def test_turns_are_scoped_to_their_conversation(ledger: CostLedger) -> None:
    ledger.observe_turn("c1", "Same question")
    assert ledger.observe_turn("c2", "Same question") is False, "cross-conversation leak"


def test_bind_clears_conversation_state(ledger: CostLedger, tmp_path: Path) -> None:
    """The regression this exists for was observable: a process-global ledger made
    `repeated_turn` order-dependent, so one test's turns became the next test's loop and
    forensics verdicts changed depending on execution order."""
    ledger.observe_turn("c1", "Where is my order?")
    other = tmp_path / "other.db"
    init_db(str(other)).close()
    ledger.bind(db_path=other)
    assert ledger.observe_turn("c1", "Where is my order?") is False


def test_an_unbound_ledger_returns_empty_rather_than_raising() -> None:
    """A raise here would be resolved by policy `fail_mode`, and UC-3 sets `cost:
    fail_closed` — turning a missing database into an escalate. That would be a harness
    failure wearing a policy decision's clothes, so absence reads as absence."""
    unbound = CostLedger()
    assert unbound.bound is False
    assert unbound.spend_in_window("finance_advisor", 60).usd == 0.0
    assert unbound.month_spend_usd("finance_advisor") == 0.0
    assert unbound.conversation_turns("c1").requests == 0


def test_seed_month_is_read_back_as_month_spend(ledger: CostLedger, tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "cost.db"))
    try:
        seed_month(conn, "finance_advisor", 123.45)
        ledger.invalidate()
        assert ledger.month_spend_usd("finance_advisor") == pytest.approx(123.45)
    finally:
        conn.close()


def test_reads_work_from_a_thread_other_than_the_one_that_bound(ledger: CostLedger) -> None:
    """The failure mode this guards is *silence*, which is why it is worth a test.

    `sqlite3` refuses a cross-thread connection, and `_query` treats a read failure as
    absence of evidence — so a shared connection would make `cost_budget` quietly stop
    firing instead of erroring. The gateway genuinely spans threads (`Gateway.conn` says
    why), so the ledger opens one connection per thread.
    """
    results: list[int] = []
    errors: list[str] = []

    def read() -> None:
        try:
            results.append(ledger.spend_in_window("finance_advisor", LOOP_WINDOW_S).requests)
        except Exception as exc:  # noqa: BLE001 - the point is that nothing escapes
            errors.append(f"{type(exc).__name__}: {exc}")

    workers = [threading.Thread(target=read) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert errors == []
    assert results == [0, 0, 0, 0]
    assert ledger.read_errors == (0, None), "a swallowed read error is a silent cost plane"
