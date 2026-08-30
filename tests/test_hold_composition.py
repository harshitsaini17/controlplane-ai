"""ADR-030 Amendment 3's composition rule, pinned against the docs it transcribes.

`eval.check_derivations` re-derives the *published table* from `BUDGETS_MS`. It cannot
check the thing that table rests on: that `POOL_USERS` still names what 04 §2 rule (a)
says it names. The roster is **declared, not derived** (three of the five detectors do not
exist, so a set built by inspecting `run_on_model_pool` callers would be silently short),
and a short roster makes every hold wrong in the safe-looking direction — smaller. Nothing
would fail.

Written because `base.py` claimed this file existed before it did (M-49).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from controlplane.detectors.base import (
    ENGINE_STEP_MS,
    POOL_USERS,
    budget_ms,
    compose_hold,
)

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "docs" / "04-policy-and-detection-spec.md"
DECISIONS = REPO / "docs" / "03-decisions.md"

#: The six holds ADR-030 Amendment 3 publishes, as (roster, worst case).
#: Duplicated from `eval/check_derivations.py` ON PURPOSE: that module locates rosters by
#: matching the doc's Hold column, so it and the doc share a failure mode — a renamed row
#: silently matches nothing. These are written out, so the arithmetic is pinned even if the
#: table's prose moves.
HOLDS: tuple[tuple[str, tuple[str, ...], float], ...] = (
    ("input lane", ("tier1_pii", "tier1_blocklist", "tier2_injection", "cost_budget",
                    "loop_guard"), 30.0),
    ("typical", ("tier1_pii", "tier1_blocklist", "tier2_toxicity", "numeric_claims"), 30.0),
    ("enriched", ("tier1_pii", "tier1_blocklist", "tier2_toxicity", "numeric_claims",
                  "entity_enricher"), 40.0),
    ("context docs", ("tier1_pii", "tier1_blocklist", "tier2_toxicity", "numeric_claims",
                      "rag_grounding", "entity_enricher"), 70.0),
    ("no context", ("tier1_pii", "tier1_blocklist", "tier2_toxicity", "numeric_claims",
                    "fast_consistency", "entity_enricher"), 100.0),
    ("both", ("tier1_pii", "tier1_blocklist", "tier2_toxicity", "numeric_claims",
              "rag_grounding", "fast_consistency", "entity_enricher"), 130.0),
)


def test_pool_users_matches_04_section_2_rule_a() -> None:
    """The roster is the spec's sentence, not a guess about which detectors use the pool.

    04 §2 rule (a) names the CPU-bound model detectors in prose. If a sixth is added there
    — or one is dropped — every published hold changes, so the two must be read together.
    """
    text = SPEC.read_text()
    start = text.index("CPU-bound model detector")
    sentence = text[start:text.index("runs its inference", start)]
    named = set(re.findall(r"`([a-z0-9_]+)`", sentence))

    assert named == set(POOL_USERS), (
        "04 §2 rule (a) and POOL_USERS disagree — every ADR-030 Amendment 3 hold "
        f"derives from this set. doc={sorted(named)} code={sorted(POOL_USERS)}"
    )
    assert len(POOL_USERS) == 5, "rule (a) names five; a sixth changes the published table"


def test_the_engine_step_is_the_number_adr_030_states() -> None:
    """5 ms, and it is a *combined* policy+action budget rather than a detector's."""
    assert ENGINE_STEP_MS == 5.0
    assert "5 ms" in DECISIONS.read_text(), "ADR-030's engine step left the doc"


@pytest.mark.parametrize(("label", "roster", "worst"), HOLDS,
                         ids=[h[0] for h in HOLDS])
def test_each_published_hold_composes(label: str, roster: tuple[str, ...],
                                      worst: float) -> None:
    assert compose_hold(roster) == worst


def test_pool_users_sum_rather_than_overlapping() -> None:
    """The whole content of Amendment 3: one worker serializes, so budgets ADD.

    Asserted as an inequality against the `max` reading, because that is the specific
    error the amendment corrected — a table composed as `max` over the whole lane.
    """
    two_pool = ("tier2_toxicity", "rag_grounding")
    assert compose_hold(two_pool) == 25.0 + 30.0 + ENGINE_STEP_MS
    assert compose_hold(two_pool) > max(budget_ms(n) for n in two_pool) + ENGINE_STEP_MS, \
        "two pool users composed as `max` — the pre-Amendment-3 defect"


def test_non_pool_detectors_overlap_rather_than_summing() -> None:
    """The other half: a regex detector releases nothing, but three of them run concurrently."""
    regexes = ("tier1_pii", "tier1_blocklist", "numeric_claims")
    assert compose_hold(regexes) == max(budget_ms(n) for n in regexes) + ENGINE_STEP_MS
    assert compose_hold(regexes) < sum(budget_ms(n) for n in regexes) + ENGINE_STEP_MS


def test_a_lane_is_the_larger_of_the_two_readings_not_their_sum() -> None:
    """`max(Σ pool, max(non-pool))` — the two groups overlap each other.

    A pool user's forward pass and a regex scan genuinely run at once, so adding the two
    group totals would over-state the hold. Pinned with a deliberately lopsided lane: the
    regex side is chosen larger than the pool side so the `max` actually selects it.
    """
    lane = ("tier1_pii", "fast_consistency")          # 2 non-pool, 60 pool
    assert compose_hold(lane) == 60.0 + ENGINE_STEP_MS
    lopsided = ("numeric_claims", "entity_enricher")  # 5 non-pool, 10 pool
    assert compose_hold(lopsided) == 10.0 + ENGINE_STEP_MS
    assert compose_hold(("numeric_claims",)) == 5.0 + ENGINE_STEP_MS


def test_an_empty_lane_still_pays_the_engine_step() -> None:
    """`max(non-pool)` over nothing is 0, not a ValueError — the engine step always runs."""
    assert compose_hold(()) == ENGINE_STEP_MS
