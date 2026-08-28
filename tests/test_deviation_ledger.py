"""The deviation ledger's counts must balance — parsed from 08, never restated here.

AGENTS.md §11 makes the `docs/08-open-questions.md` ledger table the thing an
open-deviation count is *enumerated from*. Any count stated in prose beside that table is
therefore a claim **about** the table, and one that does not balance has already shipped
once: a report stated "22 filed, 12 closed + 4 open = 16", where the subtotal was scoped to
Step-4-onward filings and the prose never said so. The arithmetic was right and the sentence
was unreadable, which is the same defect from the reader's side.

These tests are differential: every figure comes from the doc, and nothing asserts a literal
count. `assert open_rows == 4` would need editing on the next filing and would pass forever
in between — the tautology 06 §3.1 rule 3 forbids elsewhere in this repo.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOC_08 = Path(__file__).resolve().parents[1] / "docs" / "08-open-questions.md"

#: A ledger row: `| `[D<n>-slug]` | SEV | filed | status… |`. Anchored to the D-slug so the
#: MINOR (`M-<n>`) register and the Standing-Limitation table are not swept in — they are
#: different registers with different closure semantics.
LEDGER_ROW = re.compile(r"^\| `(\[D\d[^`]*\])` \|", re.M)

#: Every `N closed + M open = T` form in the file. Both the Step-4-onward subtotal and the
#: unscoped total are written this way, so the identity is checked wherever it is asserted.
IDENTITY = re.compile(r"\*\*(\d+) closed \+ (\d+) open = (\d+)\*\*")


def _doc() -> str:
    return DOC_08.read_text()


def _rows() -> list[str]:
    return [l for l in _doc().split("\n") if LEDGER_ROW.match(l)]


def _status(row: str) -> str:
    """CLOSED / OPEN, read from the status column only.

    Split past the `filed` column: a *rationale* mentioning the word "closed" is common and
    must not be read as a status ("closing a deviation never closes the gap it documented").
    """
    body = "|".join(row.split("|")[4:])
    closed, open_ = "**CLOSED" in body, "**OPEN**" in body
    if closed == open_:
        return "AMBIGUOUS"
    return "CLOSED" if closed else "OPEN"


def _counts() -> tuple[int, int, int]:
    rows = _rows()
    statuses = [_status(r) for r in rows]
    return len(rows), statuses.count("CLOSED"), statuses.count("OPEN")


def test_the_ledger_is_a_countable_table_before_anything_is_counted() -> None:
    """If the row regex silently matched nothing, every count below would trivially agree."""
    rows = _rows()
    assert len(rows) >= 20, f"only {len(rows)} ledger rows parsed — the row shape changed"


def test_every_row_carries_exactly_one_status() -> None:
    """A row that is both or neither makes the totals unrecoverable, not merely wrong."""
    bad = [LEDGER_ROW.match(r).group(1) for r in _rows() if _status(r) == "AMBIGUOUS"]
    assert not bad, f"rows with no single status: {bad}"


def test_closed_plus_open_equals_the_row_count() -> None:
    """The identity the recount ruling ordered: the table must account for every row."""
    total, closed, open_ = _counts()
    assert closed + open_ == total, (
        f"ledger does not balance: {closed} closed + {open_} open != {total} rows"
    )


def test_every_stated_identity_balances_on_its_own_terms() -> None:
    """Each `N closed + M open = T` in the prose must satisfy N + M == T.

    Scoped subtotals are legitimate — the Step-4-onward accounting is one — so this checks
    internal consistency rather than forcing every figure to the table's grand total.
    """
    found = IDENTITY.findall(_doc())
    assert found, "no `N closed + M open = T` identity found — did the prose change shape?"
    for closed, open_, total in found:
        assert int(closed) + int(open_) == int(total), (
            f"stated identity does not balance: {closed} + {open_} != {total}"
        )


def test_the_unscoped_identity_matches_the_table() -> None:
    """The largest stated total is the unscoped one, and it must equal the real counts.

    Without this, every scoped subtotal could balance while none described this repo.
    """
    total, closed, open_ = _counts()
    widest = max(IDENTITY.findall(_doc()), key=lambda m: int(m[2]))
    assert (int(widest[0]), int(widest[1]), int(widest[2])) == (closed, open_, total)


def test_the_headline_open_count_matches_the_open_rows() -> None:
    """`**Open: <word>.**` is what a STOP-point report quotes; a stale word misreports it."""
    words = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
             6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}
    _, _, open_ = _counts()
    stated = re.search(r"\*\*Open: (\w+)\.\*\*", _doc())
    assert stated, "the `**Open: N.**` headline is gone — §11 enumerates from it"
    assert stated.group(1) == words[open_], (
        f"headline says Open: {stated.group(1)}, table has {open_} open rows"
    )


def test_the_filed_total_matches_the_row_count() -> None:
    total, _, _ = _counts()
    stated = re.search(r"\*\*(\d+)\*\* deviations filed", _doc())
    assert stated, "the `**N** deviations filed` claim is gone"
    assert int(stated.group(1)) == total


def test_every_open_deviation_has_a_report_to_read() -> None:
    """An open row with no report is unenumerable: §11 asks the human to *act* on it."""
    doc = _doc()
    missing = [
        LEDGER_ROW.match(r).group(1)
        for r in _rows()
        if _status(r) == "OPEN"
        and f"## DEVIATION REPORT {LEDGER_ROW.match(r).group(1)}" not in doc
    ]
    assert not missing, f"open deviations with no report section: {missing}"


def test_no_slug_is_filed_twice() -> None:
    """Two rows for one slug would double-count in whichever direction they disagree."""
    slugs = [LEDGER_ROW.match(r).group(1) for r in _rows()]
    dupes = {s for s in slugs if slugs.count(s) > 1}
    assert not dupes, f"duplicate ledger rows: {dupes}"


@pytest.mark.parametrize("register", ["Deviation ledger", "Standing Limitations"])
def test_the_registers_stay_separate(register: str) -> None:
    """§11's count is the deviation table's. Merging the registers is how a low count lies."""
    assert f"## {register}" in _doc()
