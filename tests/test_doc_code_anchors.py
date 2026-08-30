"""Live doc prose must anchor to code by **symbol**, never by line number.

Found by rot, not by design. ADR-034 Part C named `pipeline.py:280` as the place the resolved
ceiling is consumed; wiring it moved that line to 312, and the citation silently became a pointer
to a docstring fragment. Worse, `pipeline.py:212` — ADR-030's anchor for the sequential-vs-`gather`
measurement decision — was **already** stale before that change, pointing at `Coverage.note_ran`.
Nothing noticed either, because a line number is not checkable by reading the sentence around it.

So the rule is mechanical: prose that states a *current* fact about the code cites a symbol
(`run_lane`, `ceiling_ms`, `_time_calls`), which either resolves or is a visible error, and which
survives every edit that does not rename it.

**History is exempt, deliberately.** A filed deviation report, a ledger closure row, and a
blockquoted withdrawn passage all record what was true when written; re-pointing them at today's
code would falsify the record — the opposite of the goal. That is why this checks *zones* rather
than the whole file, and why the exemption is the interesting half of the rule.

A fourth case is **opt-in**, not inferred: prose that *quotes a rotted citation as its evidence*.
The M-row logging this very rule has to name `pipeline.py:280` and `pipeline.py:212` — its claim is
that a doc named those lines and they went stale, so anchoring them by symbol would delete the
evidence. Such a line declares itself with a trailing `<!-- rot-evidence -->`. Opt-in rather than
zone-inferred because an M-row is only *half* history: its Gap column records a past defect, its
Resolution column states what is true now (M-35's names where the window geometry lives today), so
exempting the row wholesale would leave every future Resolution column unchecked.

**Known limitation, recorded rather than fixed:** the marker exempts its whole line, so a live
citation sharing a line with declared evidence would pass unseen. Line-level is what the existing
three zones already are; narrowing it to the individual citation buys precision the failure mode
does not justify.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"

#: `name.py:123`, with or without backticks and a leading path.
CITATION = re.compile(r"`?([\w./-]*?[\w-]+\.py):(\d+)`?")

#: Marks a line whose line-number citations ARE the evidence (see module docstring). Opt-in: a
#: writer quoting a stale pointer says so, which — unlike the pointer — is checkable by reading.
ROT_EVIDENCE = "<!-- rot-evidence -->"

#: Third-party files we cannot anchor by symbol. Each is pinned by an inline code quote instead,
#: which is what actually carries the claim — the line number is a convenience for the reader.
THIRD_PARTY = {"import_utils.py"}


def _live_lines(doc: Path) -> list[tuple[int, str]]:
    """Lines of `doc` that assert a current fact — history and quotations removed.

    Three exempt zones, inferred:
      * a `## DEVIATION REPORT` body, up to the next `## ` heading — as-filed evidence;
      * a ledger table row (starts `| ` and names a `[D…]` slug) — a closure record;
      * a blockquoted line — a withdrawn passage preserved verbatim.

    Plus one **declared**: a line carrying `ROT_EVIDENCE`, which quotes a rotted citation as the
    evidence for a claim about the rot itself. Declared, not inferred, so it cannot widen on its
    own the way a zone rule would.
    """
    out: list[tuple[int, str]] = []
    in_report = False
    for i, line in enumerate(doc.read_text().split("\n"), 1):
        if line.startswith("## DEVIATION REPORT"):
            in_report = True
            continue
        if line.startswith("## "):
            in_report = False
        stripped = line.lstrip()
        if in_report or stripped.startswith(">") or ROT_EVIDENCE in line:
            continue
        if stripped.startswith("|") and re.search(r"`\[D\d", line):
            continue
        out.append((i, line))
    return out


@pytest.mark.parametrize("doc", sorted(DOCS.glob("*.md")), ids=lambda p: p.name)
def test_live_prose_cites_code_by_symbol_not_line_number(doc: Path) -> None:
    """No `file.py:NNN` in prose that claims something about the code as it is now."""
    offenders = [
        f"{doc.name}:{i} cites {m.group(1)}:{m.group(2)}"
        for i, line in _live_lines(doc)
        for m in CITATION.finditer(line)
        if Path(m.group(1)).name not in THIRD_PARTY
    ]
    assert not offenders, (
        "line numbers rot silently on the next edit — cite the symbol instead "
        f"(`run_lane`, `ceiling_ms`, …):\n  " + "\n  ".join(offenders)
    )


def test_the_exempt_zones_are_real_and_still_populated() -> None:
    """The exemptions must be carrying weight, or the test above is passing for a hollow reason.

    If a refactor ever made `_live_lines` exclude everything, the rule would "hold" vacuously.
    This asserts the opposite direction: history still contains line numbers (that is the point of
    exempting it), and the live zones still contain substantial prose to police.
    """
    ledger = DOCS / "08-open-questions.md"
    all_lines = ledger.read_text().split("\n")
    live = _live_lines(ledger)

    assert len(live) > 200, f"live zone collapsed to {len(live)} lines — the filter is too broad"
    exempt = len(all_lines) - len(live)
    assert exempt > 50, f"only {exempt} lines exempted — history is not being recognised"

    live_nums = {i for i, _ in live}
    historical_citations = [
        i for i, line in enumerate(all_lines, 1)
        if i not in live_nums and CITATION.search(line)
    ]
    assert historical_citations, (
        "no line-number citations found in the exempt zones; either history was rewritten or "
        "the zone detection has stopped matching it"
    )


def test_the_rot_evidence_marker_is_load_bearing_and_never_decorative() -> None:
    """The opt-in exemption must be earning its keep — in both directions.

    An opt-in escape hatch is the one exemption that can be abused, because it takes only a
    comment to silence the guard on a live claim. Intent is not checkable, but two things are:
    every marked line must actually *contain* a citation (so the marker is never decoration
    carried along by a copy-paste), and removing the marker must make the guard fire (so the
    exemption is load-bearing rather than a no-op the rule no longer needs).
    """
    marked = [
        (doc.name, i, line)
        for doc in sorted(DOCS.glob("*.md"))
        for i, line in enumerate(doc.read_text().split("\n"), 1)
        if ROT_EVIDENCE in line
    ]
    assert marked, (
        f"no line declares {ROT_EVIDENCE} — if the rot-evidence prose was removed, drop the "
        "exemption from `_live_lines` too rather than leaving an unused escape hatch"
    )

    decorative = [f"{n}:{i}" for n, i, line in marked if not CITATION.search(line)]
    assert not decorative, (
        f"{ROT_EVIDENCE} on a line with no line-number citation — the marker exempts a whole "
        f"line, so a decorative one silently widens the exemption:\n  " + "\n  ".join(decorative)
    )

    # Load-bearing: with the marker stripped, each marked line has a citation the guard rejects.
    for name, i, line in marked:
        stripped = line.replace(ROT_EVIDENCE, "")
        assert any(
            Path(m.group(1)).name not in THIRD_PARTY for m in CITATION.finditer(stripped)
        ), f"{name}:{i} would pass without the marker — the exemption is doing nothing there"
