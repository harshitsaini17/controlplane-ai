"""Re-derivation check: every derivation-claiming figure in ADR-032/034 vs the artifact.

**Why this exists.** ADR-031's landing ran a full re-derivation pass by hand — 36 figures, 0
mismatches — and it worked, but it was a one-off performed by a reader who chose to do it. Two
sessions later the same defect class appeared twice more: **a figure described by a derivation it
does not come from.** The coverage labels in ADR-032's table were read off the synthetic filler's
token count instead of the window geometry (Correction 1), and ADR-034 Part B's tokenization table
had no measuring script at all. Neither was a wrong *number* — both were correct measurements
wearing a wrong description, which is the failure a proofreader does not catch and arithmetic does.

**What it checks.** Each published figure must be **byte-identical** to the artifact field it
claims to come from. Exact, not approximate: these figures are transcriptions, and the whole point
is to catch transcription drift, so "close enough" would admit exactly the error being hunted.
Structural labels (coverage spans, window counts) are checked against the geometry instead, which
is arithmetic and admits no tolerance either.

**Values are parsed, never hand-copied.** A registry of expected numbers maintained beside the docs
would be one more copy to drift — the same reason ADR-035's closure test derives its dependency set
from `pyproject.toml` at run time. What *is* declared here is only the **mapping**: which artifact
rung, column and percentile a given table means. That cannot be inferred from prose, and it is the
part a human should have to state explicitly.

**Three verdicts, and the third is the point.** `OK` and `MISMATCH` are obvious. `NO SOURCE` means
the document claims a figure the artifact cannot produce — which under the Correction 1 ruling is
not a tolerable state: such a figure either gains a derivation or loses its derivation claim.

    python -m eval.check_derivations
    python -m eval.check_derivations --artifact reports/spike_window_latency.json

Exit status is nonzero on any MISMATCH or NO SOURCE, so it can gate a commit.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from eval.spike_tier2_models import _percentiles_are_distinct  # noqa: E402
from eval.spike_window_latency import (  # noqa: E402  (after sys.path)
    coverage_tokens,
    windows_for_tokens,
)

DECISIONS = REPO / "docs" / "03-decisions.md"
DEFAULT_ARTIFACT = REPO / "reports" / "spike_window_latency.json"

#: Strip markdown emphasis and approximation marks before reading a number. `~3100` and
#: `**651.41**` are the same kind of claim as `651.41`; the decoration is presentation.
_DECOR = re.compile(r"[*~`]")


def _unquoted(text: str) -> str:
    """`text` with blockquoted lines removed.

    Prose searches must run over this, never the raw document. Correction 1 preserves withdrawn
    tables and paragraphs **blockquoted**, and a regex over the raw text would happily find a
    retired figure and re-derive it against the current artifact — validating a number the doc
    explicitly withdrew, or failing on one it never claimed. Table lookups are already immune
    (they require a leading `|`); prose is not, and that asymmetry is easy to miss.
    """
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith(">"))


def _cells(line: str) -> list[str]:
    """Cells of a markdown table row, decoration removed."""
    return [_DECOR.sub("", c).strip() for c in line.strip().strip("|").split("|")]


def _table_after(text: str, header_fragment: str) -> list[list[str]]:
    """Body rows of the first markdown table whose header contains `header_fragment`.

    Located by header text rather than line number so the check survives edits above it — a
    line-number anchor would silently read the wrong table after any insertion.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if header_fragment in line and line.lstrip().startswith("|"):
            rows = []
            for row in lines[i + 2:]:                 # skip the |---| separator
                if not row.lstrip().startswith("|"):
                    break
                rows.append(_cells(row))
            return rows
    raise LookupError(f"no table with header containing {header_fragment!r}")


def _pair(cell: str) -> tuple[float, float] | None:
    """`"651.41 / 657.04"` -> (651.41, 657.04). None when the cell is not a P50/P99 pair."""
    nums = re.findall(r"\d+\.\d+", cell)
    return (float(nums[0]), float(nums[1])) if len(nums) == 2 else None


def _int(cell: str) -> int | None:
    m = re.search(r"\d+", cell)
    return int(m.group()) if m else None


def _num(cell: str) -> float | None:
    """The first decimal number in `cell`. `"12.56 ms"` -> 12.56."""
    m = re.search(r"\d+\.\d+", cell)
    return float(m.group()) if m else None


class Check:
    """One published figure, its claimed derivation, and the verdict."""

    def __init__(self, label: str, published: Any, derive: Callable[[], Any]) -> None:
        self.label = label
        self.published = published
        try:
            self.derived: Any = derive()
        except (KeyError, LookupError, TypeError, ZeroDivisionError):
            self.derived = None

    @property
    def verdict(self) -> str:
        if self.derived is None:
            return "NO SOURCE"
        return "OK" if self.published == self.derived else "MISMATCH"


def _run(art: dict[str, Any], threads: int) -> dict[str, Any]:
    for r in art["runs"]:
        if r["threads"] == threads:
            return r
    raise LookupError(f"artifact has no threads={threads} run")


def _lad(art: dict[str, Any], threads: int, wins: int, mode: str) -> dict[str, Any]:
    return _run(art, threads)["ladder"][str(wins)][mode]


def _published_pair(art: dict[str, Any], threads: int, wins: int, mode: str
                    ) -> tuple[float, float]:
    """The (p50, p99) a document may publish for this rung — and nothing else.

    Refuses to hand back a p99 the sample size cannot resolve: below n=40 both percentiles land
    on one order statistic, so a "p99" from 10 samples is `samples[8]` wearing a p99 label. That
    is the third defect Correction 1's re-derivation pass found, and returning the number anyway
    would let this checker bless it.
    """
    b = _lad(art, threads, wins, mode)
    # Derived from `n` when the artifact predates the self-describing field — defaulting to
    # "resolved" would let exactly the artifacts that carry the defect pass unchallenged.
    resolved = b.get("percentiles_resolved")
    if resolved is None:
        resolved = _percentiles_are_distinct(b["n"])
    if not resolved:
        raise LookupError(f"n={b['n']} cannot resolve a p99 for {wins} windows {mode}")
    return (b["p50"], b["p99"])


def checks(art: dict[str, Any], text: str) -> list[Check]:
    out: list[Check] = []

    # --- ADR-032's measurement table: 6 threads, sequential + batched, P50/P99 ---------------
    for row in _table_after(text, "batched (all in one call)"):
        wins, covers, seq, bat = _int(row[0]), _int(row[1]), _pair(row[2]), _pair(row[3])
        if wins is None:
            continue
        out.append(Check(f"ADR-032 table: {wins}w coverage label",
                         covers, lambda w=wins: coverage_tokens(w)))
        if seq:
            out.append(Check(f"ADR-032 table: {wins}w sequential P50/P99", seq,
                             lambda w=wins: _published_pair(art, 6, w, "sequential")))
        if bat:
            out.append(Check(f"ADR-032 table: {wins}w batched P50/P99", bat,
                             lambda w=wins: _published_pair(art, 6, w, "batched")))

    # --- ADR-034 Part B tokenization table: input length -> windows, P50/P99 -----------------
    for row in _table_after(text, "tokenize + window P50 / P99"):
        toks, pair = _int(row[0]), _pair(row[2])
        if toks is None:
            continue
        # "bound" in the windows column is a claim about the policy bound, not a number, so it
        # is checked as one: the row's own token count must be what the bound needs.
        claimed_windows = _int(row[1])
        if claimed_windows is not None:
            out.append(Check(f"Part B tokenize: {toks}tok window count",
                             claimed_windows, lambda t=toks: windows_for_tokens(t)))
        else:
            out.append(Check(f"Part B tokenize: {toks}tok labelled {row[1]!r}",
                             row[1].lower(), lambda t=toks: (
                                 "bound" if t == art["window"]["policy_bound_tokens"]
                                 else f"{windows_for_tokens(t)} windows, NOT the bound")))
        if pair:
            out.append(Check(f"Part B tokenize: {toks}tok P50/P99", pair,
                             lambda t=toks: (art_tok(art, t)["p50"], art_tok(art, t)["p99"])))

    # --- ADR-034 Part B column-choice table: per-window P99 at the 2-window rung -------------
    for row in _table_after(text, "ceiling at 2 windows"):
        threads = 6 if row[0].startswith("6") else 1
        out.append(Check(f"Part B basis: {threads}thr per-window P99", _num(row[1]),
                         lambda t=threads: round(
                             _published_pair(art, t, 2, "sequential")[1] / 2, 2)))
        out.append(Check(f"Part B basis: {threads}thr row's 1-thread cost", _num(row[3]),
                         lambda: _published_pair(art, 1, 2, "sequential")[1]))

    # --- the batching paragraph's P50 figures ------------------------------------------------
    # Prose, not a table, and every one of them is a transcription from `batch_curve`. The
    # paragraph carries the "bound batch size" decision, so a stale figure here argues for a
    # batch size the measurement no longer supports.
    prose = _unquoted(text)
    for m in re.finditer(rf"batch \*{{0,2}}(\d+)\*{{0,2}} (?:{_ARROW}) \*{{0,2}}(\d+\.\d+)",
                         prose):
        batch, published = int(m.group(1)), float(m.group(2))
        out.append(Check(f"ADR-032 batching prose: batch {batch} P50", published,
                         lambda b=batch: _batch_p50(art, b)))
    for m in re.finditer(rf"all-(\d+)-in-one-call (?:{_ARROW}) \*{{0,2}}(\d+\.\d+)", prose):
        batch, published = int(m.group(1)), float(m.group(2))
        out.append(Check(f"ADR-032 batching prose: all-{batch}-in-one-call P50", published,
                         lambda b=batch: _batch_p50(art, b)))
    m = re.search(r"separate\s+calls at (\d+\.\d+)", prose)
    if m:
        out.append(Check("ADR-032 batching prose: sequential baseline (batch 1) P50",
                         float(m.group(1)), lambda: _batch_p50(art, 1)))

    # --- prose ratio claims -----------------------------------------------------------------
    # Ratios get their own anchors because a ratio names its OPERANDS, and that is precisely
    # what goes wrong with one: the spread written as 3.9x is the single-window P99 pairing,
    # while the table it sits in prints the 2-window per-window figures, whose ratio is 4.08.
    # A number can be right about arithmetic and wrong about what it divided.
    for anchor, derive in _RATIO_CLAIMS.items():
        m = re.search(anchor, prose)
        if m is None:
            out.append(Check(f"ratio claim {anchor!r}", "ABSENT", lambda: None))
            continue
        out.append(Check(f"ratio: {m.group(0)[:44]}", float(m.group(1)),
                         lambda d=derive: d(art)))
    return out


def _batch_p50(art: dict[str, Any], batch: int) -> float:
    """`batch_curve[batch].p50` at 6 threads — the column ADR-032's batching paragraph reads.

    p50 only, deliberately: the batch curve runs few reps per point, so it has no publishable
    p99, and the paragraph correctly quotes medians. Asking this for a p99 should fail rather
    than round up to `max`.
    """
    curve = _run(art, 6)["batch_curve"]
    if str(batch) not in curve:
        raise LookupError(f"artifact has no batch_curve point at batch {batch}")
    return curve[str(batch)]["p50"]


def _ratio(art: dict[str, Any], threads_hi: int, threads_lo: int, wins: int, pct: int) -> float:
    """Cross-thread ratio at one rung and one percentile — stated, never inferred."""
    hi = _published_pair(art, threads_hi, wins, "sequential")[1 if pct == 99 else 0]
    lo = _published_pair(art, threads_lo, wins, "sequential")[1 if pct == 99 else 0]
    return round(hi / lo, 2)


#: Prose ratio claims: regex capturing the published figure -> how to derive it.
#: The mapping is declared (which rung, which percentile); the value is parsed from the doc.
#: Both arrow forms the docs use: a literal Unicode arrow and an ASCII `->`.
_ARROW = r"\u2192|->"

#: `[x\u00d7]` because the docs use BOTH: ADR-032 writes `4.41\u00d7` with the Unicode
#: multiplication sign and 08 writes `4.41x` with an ASCII ex. An anchor matching one silently
#: reports the other ABSENT, which reads as "no such claim" when the claim is right there.
_TIMES = r"[x\u00d7]"

_RATIO_CLAIMS: dict[str, Callable[[dict[str, Any]], float]] = {
    rf"a \*\*(\d+\.\d+){_TIMES}\*\* speedup": lambda a: _ratio(a, 1, 6, 1, 50),
    rf"the ratio is \*\*(\d+\.\d+){_TIMES}\*\*": lambda a: _ratio(a, 1, 6, 2, 99),
}


def art_tok(art: dict[str, Any], tokens: int) -> dict[str, Any]:
    """The tokenization row for exactly `tokens` tokens, or raise."""
    tokz = _run(art, 6).get("tokenize") or {}
    row = tokz.get(str(tokens))
    if row is None or "error" in row:
        raise LookupError(f"artifact has no tokenization measurement at {tokens} tokens")
    resolved = row.get("percentiles_resolved")
    if resolved is None:
        resolved = _percentiles_are_distinct(row["n"])
    if not resolved:
        raise LookupError(f"n={row['n']} cannot resolve a p99 at {tokens} tokens")
    return row


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    ap.add_argument("--decisions", type=Path, default=DECISIONS)
    args = ap.parse_args(argv)

    art = json.loads(args.artifact.read_text())
    results = checks(art, args.decisions.read_text())

    width = max(len(c.label) for c in results)
    print(f"re-derivation check — {args.decisions.name} vs {args.artifact.name}\n")
    for c in results:
        flag = "" if c.verdict == "OK" else "  <<<"
        print(f"  {c.label:<{width}}  published {str(c.published):<22} "
              f"derived {str(c.derived):<22} {c.verdict}{flag}")

    bad = [c for c in results if c.verdict != "OK"]
    counts = {v: sum(1 for c in results if c.verdict == v)
              for v in ("OK", "MISMATCH", "NO SOURCE")}
    print(f"\n{len(results)} figures checked: " +
          ", ".join(f"{n} {v}" for v, n in counts.items() if n))
    if bad:
        print("\nEvery non-OK figure either gains a derivation or loses its derivation claim "
              "(ADR-032 Correction 1) — there is no third state.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
