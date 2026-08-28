"""README status claims (M-23) — derived from the docs, not restated beside them.

The README is judge-facing, so a wrong number in it is an integrity problem (AGENTS.md
§7) even when every unit test passes. M-23 was filed because three of its claims had
drifted: the ADR count said 23 against a log holding more, and a literal test count
appeared in three places, each stale.

Two different fixes, because they are two different failure modes:

- **The ADR count is derivable**, so it is *derived here* and compared. This test parses
  `docs/03-decisions.md` and fails if the README disagrees with it — in either direction.
  That makes it a differential test rather than the tautology 06 §3.1 rule 3 forbids: a
  new ADR appended to `03` and not to the README fails, and so does a count invented in
  the README. Hand-maintaining the number is what produced the drift; nothing here asks a
  human to maintain it again.
- **The test count is not derivable from any doc** — it is a property of the run, and any
  literal copy of it is stale the moment a test is added. So it was removed and pointed at
  CI, and the guard below keeps it removed. A test asserting a *correct* suite count would
  itself need editing on every commit that adds a test, which is the drift it was supposed
  to prevent.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
DOC_03 = ROOT / "docs" / "03-decisions.md"

# `## ADR-0NN — title`. Level-2 only, and that is the load-bearing part of this pattern:
# `03` carries 14 `###` sub-headings (ADR-025's amendment, ADR-026's correction and its two
# amendments, ADR-027's amendment, the ADR-009 amendment under ADR-029, ADR-030's
# derivation sections...). An amendment is a change *to* a decision, not an additional
# one, so counting `###` would inflate the total by more than a third.
ADR_HEADING = re.compile(r"^## ADR-(\d{3}) ", re.M)


def _adr_ids() -> list[int]:
    return [int(m) for m in ADR_HEADING.findall(DOC_03.read_text())]


def test_the_adr_log_is_a_countable_thing_before_anything_is_counted() -> None:
    """A duplicate or a gap would make any single total a wrong summary of the log.

    Checked first and separately: if two headings shared an id, the README could agree
    with a count that is nonetheless wrong, and this suite would call that a pass.
    """
    ids = _adr_ids()
    assert ids, "no `## ADR-NNN` headings found — the heading format changed, not the count"
    assert len(ids) == len(set(ids)), f"duplicate ADR ids: {sorted({i for i in ids if ids.count(i) > 1})}"
    missing = sorted(set(range(min(ids), max(ids) + 1)) - set(ids))
    assert not missing, f"gap in the ADR sequence: {missing}"
    assert min(ids) == 1, "the log should start at ADR-001"


def test_readme_adr_count_matches_the_log_it_summarises() -> None:
    """M-23's first drift: the README said 23 while `03` had ruled more."""
    claimed = re.search(r"\*\*(\d+)\*\* ADRs ruled", README.read_text())
    assert claimed, "the README status table no longer states an ADR count in the pinned form"
    assert int(claimed.group(1)) == len(_adr_ids())


def test_amendments_are_not_counted_as_decisions() -> None:
    """The discriminator this test rests on, asserted rather than assumed.

    If `03` ever promoted its amendments to `##`, the count above would silently jump and
    the README would be "corrected" to a number that overstates how many decisions exist.
    """
    text = DOC_03.read_text()
    assert re.search(r"^### Amendment", text, re.M), (
        "no `###` amendments left in 03 — if they moved to `##`, ADR_HEADING now overcounts"
    )


# `433 tests`, `433 collected`, `431 pass`, `990 passed`. Bounded to 3+ digits on purpose:
# this suite is in the hundreds, so a suite-wide total cannot be smaller, while the small
# counts the README legitimately carries are counts of *named* things (its two `xfail`
# cases are the Unicode-homoglyph and zero-width-email limitations, and 06 §3.1 wants those
# named) rather than a figure that moves whenever a test is added.
VOLATILE_COUNT = re.compile(
    r"\b\d{3,}\s*(?::\s*\d+\s*)?(?:unit\s+)?(?:tests?\b|collected\b|pass(?:e[sd])?\b)",
    re.I,
)


def test_no_literal_suite_count_returns_to_the_readme() -> None:
    """M-23's second drift, kept fixed. The count belongs to CI, not to prose.

    Three copies of `433` existed; each had to be right for the README to be right, so the
    honest fix was to stop asserting it in a file nothing re-runs.
    """
    offenders = [
        f"{i}: {line.strip()}"
        for i, line in enumerate(README.read_text().splitlines(), 1)
        if VOLATILE_COUNT.search(line)
    ]
    assert not offenders, (
        "literal suite counts are back in the README (M-23) — point at CI instead:\n"
        + "\n".join(offenders)
    )


def test_the_readme_points_at_the_gate_that_holds_the_count() -> None:
    """Removing the number is only honest if the reader is told where the real one is."""
    text = README.read_text()
    assert "ci.yml" in text, "the README dropped its test counts without naming the CI gate"
    assert (ROOT / ".github" / "workflows" / "ci.yml").exists(), (
        "the README points at a CI workflow that does not exist"
    )


@pytest.mark.parametrize("claim", ["Gateway hot path", "Policy engine", "Latency benchmark"])
def test_shipped_subsystems_are_no_longer_advertised_as_unbuilt(claim: str) -> None:
    """M-23's third drift: rows saying `not yet implemented` for code that ships.

    Understating is not the safe direction — the gateway, the policy engine and the two
    running harnesses are the prototype, and a README disowning them describes a different
    project than the one the repo holds.
    """
    for line in README.read_text().splitlines():
        if line.startswith("|") and claim in line:
            assert "not yet implemented" not in line, line.strip()
            return
    pytest.fail(f"no README status row for {claim!r}")
