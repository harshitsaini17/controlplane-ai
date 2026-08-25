"""`numeric_claims` heuristic detector.

Implements the 04 §2 registry row: stage `output_sentence`, budget <5 ms, emits
`hallucination.unsourced_numeric`, `score_kind="detection"` at 1.0 (ADR-012 — deterministic
emitters report 1.0 and band logic never applies).

The row specifies it in one sentence: *"currency/percent/large-number patterns with no
citation marker and no match in provided context; high-stakes use cases map it to
ESCALATE."* Three clauses, taken in order — a numeral shape, no marker, no context match.
The final clause is policy, and lives in `policies/*.yaml`, not here.

DOC GAP (MINOR, logged in `08-open-questions.md` rather than improvised): **"citation
marker" is not defined anywhere in the docs.** No 04 section, no ADR, and the only other
"citation" hits are ADR-008 and the charter, which govern *our* citations in the proposal,
not markers in model output. `_CITATION_MARKER` below is therefore a definition I am
supplying, kept deliberately narrow — the shapes a model actually produces when it attributes
a figure. Its exact membership is a judgement call and is the thing to challenge in review.

**A marker is not a verification.** It suppresses only this detector, whose question is
"was this figure attributed?" — not "is the attribution true?" That second question belongs
to `rag_grounding`, which scores the sentence against the context independently. So a
sentence carrying a plausible-looking citation for a figure the context never states is
*correctly* silent here and *correctly* flagged there. The two detectors are meant to
disagree on that shape, and 06's corpus contains exactly that pair as a deliberate control:
treating a citation marker as blanket absolution across both planes is the bug this note
exists to prevent.
"""

from __future__ import annotations

import re
import time

from controlplane.detectors.base import (
    DetectorContext,
    Plane,
    ScoreKind,
    Signal,
    Span,
)

__all__ = ["NumericClaimsDetector", "numeric_claims"]


# --------------------------------------------------------------------------
# The three numeral shapes named by 04 §2
# --------------------------------------------------------------------------

#: Currency. Symbol-prefixed or code-suffixed, with optional magnitude word. Any amount
#: counts — "$5" is as much a claim as "$5.2 billion", and the row says "currency", unqualified.
#:
#: Magnitude words are ordered LONGEST-FIRST and closed with `\b`. Regex alternation is
#: leftmost-first, not longest-match: with `k|m|…|million`, the bare `m` wins inside
#: "million" and `$1.2 million` spans only `$1.2 m`. Span accuracy is load-bearing (04 §6
#: `soften` replaces exactly this extent), so the ordering is a correctness requirement.
_CURRENCY = re.compile(
    r"""(?xi)
    (?:
        [$£€¥]\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:trillion|thousand|billion|million|bn|k|m)\b)?
      | \b\d[\d,]*(?:\.\d+)?\s?(?:trillion|thousand|billion|million|bn|k|m)?\s?
        (?:usd|eur|gbp|jpy|inr|dollars?|euros?|pounds?)\b
    )
    """
)

#: Percent, symbol or spelled. Includes "percentage points" — a delta is still a figure.
#:
#: No trailing `\b` on the `%` branch: `%` is not a word character, so a boundary assertion
#: after it can only succeed before a letter or digit and fails on "22%." or "22% of". That
#: made the branch unmatchable in ordinary prose and left a fallback matching the bare `%` —
#: a zero-digit span, which also skipped the context check below (an empty digit key matches
#: nothing), so a percentage the context fully supported still fired.
_PERCENT = re.compile(
    r"""(?xi)
    \b\d+(?:\.\d+)?\s?%                                  # 22%, 7.4 %
  | \b\d+(?:\.\d+)?\s?percent(?:age)?(?:\s+points?)?\b   # 22 percent, 3 percentage points
    """
)

#: "Large number". The row does not define the threshold, so the boundary is drawn where a
#: numeral stops being incidental prose and starts being a statistic:
#:
#:   * a magnitude word ("2.4 million") — unambiguous at any size;
#:   * thousands separators ("1,200") — the writing convention *for* a quantity;
#:   * a bare run of 4+ digits ("15000").
#:
#: 4+ digits excludes years (1999, 2026 are 4 digits — see `_YEAR_LIKE`), small counts and
#: ordinary integers. It is a heuristic, and 06 §2.3 puts deliberate false-positive pressure
#: against it in `clean.jsonl` (digit strings, grounded version numbers). Whatever it costs
#: shows up in the measured FP rate rather than being tuned away (AGENTS.md §7).
_LARGE_NUMBER = re.compile(
    r"""(?xi)
    \b(?:
        \d[\d,]*(?:\.\d+)?\s?(?:k|m|bn|thousand|million|billion|trillion)\b
      | \d{1,3}(?:,\d{3})+(?:\.\d+)?
      | \d{4,}(?:\.\d+)?
    )
    """
)

#: A bare 4-digit run in a year's range, not adjacent to a separator or decimal. Excluded
#: from `_LARGE_NUMBER`: "in 2024 we shipped" states a date, not a quantity, and 06 §2.3
#: ships grounded version numbers and years as explicit negative controls.
_YEAR_LIKE = re.compile(r"^(?:1[89]\d{2}|20\d{2}|21\d{2})$")

_NUMERAL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_CURRENCY, "currency"),
    (_PERCENT, "percent"),
    (_LARGE_NUMBER, "large-number"),
)


# --------------------------------------------------------------------------
# Citation marker — the undefined term (see module docstring)
# --------------------------------------------------------------------------

#: Shapes that constitute an attribution. Narrow by design: each either names a source or
#: points at one. Hedges ("roughly", "about", "I think") are deliberately absent — a hedge
#: is an epistemic qualifier, and 04 §6 `soften` is what handles those. Confusing the two
#: would let "roughly $4M" pass as sourced.
_CITATION_MARKER = re.compile(
    r"""(?xi)
    \[\d+\]                                   # [1] — numeric footnote
  | \[[A-Za-z][A-Za-z\s.\-]{1,30}\d{4}\]      # [Smith 2024]
  | \((?:[A-Z][A-Za-z.\-]+(?:\s+(?:et\s+al\.?|and|&)\s+[A-Za-z.\-]+)?[,\s]+)?
        (?:19|20)\d{2}[a-z]?\)                # (Smith, 2024) / (2024)
  | https?://\S+ | \bwww\.\S+\.\w{2,}         # a link is a source
  | \baccording\ to\b | \bas\ reported\ (?:by|in)\b | \bas\ (?:stated|noted)\ in\b
  | \bper\ (?:the|our|your|section|clause|§)\b
  | \b(?:source|sources|ref|refs|reference|citation|cited\ in|see)\s*[:§]
  | \b(?:section|clause|article|page|table|figure|exhibit|appendix)\s+\d+
  | §\s?\d+                                   # § 4 / §4.3
  | \b(?:filing|prospectus|10-K|10-Q|8-K)\b   # named regulatory documents
    """
)

#: Sentence-boundary scan. A local helper, not a general splitter: the gateway's
#: `sentence_buffer` (04 §2) owns real segmentation, and a second implementation here would
#: eventually disagree with it.
_SENTENCE_END = re.compile(r"[.!?]\s")


def _sentence_window(text: str, start: int, end: int) -> str:
    """The sentence containing `[start, end)`.

    Marker search is scoped to the sentence rather than the whole text, and the reason is
    `output_full`: under ADR-014 UC-3 buffers an entire response, so a text-wide search
    would let one citation in the opening line silence every unsourced figure that followed
    — the highest-stakes use case getting the weakest check. Scoping to the sentence makes
    `output_sentence` and `output_full` behave identically, which is also what keeps the
    streaming and non-streaming eval rows comparable.
    """
    left = 0
    for match in _SENTENCE_END.finditer(text, 0, start):
        left = match.end()
    right_match = _SENTENCE_END.search(text, end)
    right = right_match.end() if right_match else len(text)
    return text[left:right]


def _digit_key(fragment: str) -> str:
    """Digits of a numeral, separators dropped: `$1,200.00` → `120000`.

    Comparison key for the context check. Crude on purpose — see the class docstring on
    what it does not catch.
    """
    return re.sub(r"\D", "", fragment)


class NumericClaimsDetector:
    """`numeric_claims` — 04 §2. Fires on a numeral with no marker and no context match.

    **Context matching is digit-identity, and its limits are stated rather than hidden.**
    A figure counts as grounded when its digits appear in a context doc. So "2,400" matches
    a context saying "2400", but "2.4 million" does **not** match a context saying
    "2,400,000" — the digit keys differ. That error is one-directional: it can only cause
    a *false positive* (flagging a figure the context does support), never a false negative
    (missing an unsupported one). For a detector whose high-stakes mapping is ESCALATE, an
    over-flag costs a review and an under-flag costs a fabricated number reaching a user,
    so the asymmetry is deliberately on the safe side. Semantic magnitude matching is
    `rag_grounding`'s job, and it scores the same sentence independently.

    Emits one signal per unsourced numeral, each span-accurate — `soften` (04 §6) needs the
    extent, and 04 §4.3's most-severe resolution works across signals.
    """

    name = "numeric_claims"

    async def detect(self, ctx: DetectorContext) -> list[Signal]:
        started = time.perf_counter()
        text = ctx.text or ""

        context_digits = {
            key
            for doc in ctx.context_docs
            for key in (_digit_key(fragment) for fragment in re.findall(r"[\d,.]+", doc))
            if key
        }

        candidates: list[tuple[int, int, str]] = []
        for pattern, shape in _NUMERAL_PATTERNS:
            for match in pattern.finditer(text):
                fragment = match.group().strip()
                if shape == "large-number" and _YEAR_LIKE.match(fragment):
                    continue
                candidates.append((match.start(), match.start() + len(fragment), shape))

        signals: list[Signal] = []
        claimed: list[tuple[int, int]] = []
        for start, end, shape in sorted(candidates, key=lambda c: (c[0], -(c[1] - c[0]))):
            # One signal per numeral: `$1.2 million` matches both currency and
            # large-number, and two signals would double-count one claim.
            if any(start < seen_end and seen_start < end for seen_start, seen_end in claimed):
                continue
            claimed.append((start, end))

            if _CITATION_MARKER.search(_sentence_window(text, start, end)):
                continue
            digit_key = _digit_key(text[start:end])
            if digit_key and digit_key in context_digits:
                continue

            signals.append(
                Signal(
                    detector=self.name,
                    planes=[Plane.PERFORMANCE],
                    labels=["hallucination.unsourced_numeric"],
                    score=1.0,
                    score_kind=ScoreKind.DETECTION,
                    span=Span(start=start, end=end),
                    stage=ctx.stage,
                    # Shape name and digit LENGTH only. The figure itself is not echoed:
                    # a salary or an account balance is personal data, and `evidence` is
                    # serialized into `audit_records.signals_json` (05 §3, NFR-SEC-001).
                    evidence=(
                        f"category:unsourced_numeric shape={shape} "
                        f"digits={len(digit_key)} context_docs={len(ctx.context_docs)}"
                    ),
                    latency_ms=0.0,  # stamped below, once, for the whole pass
                )
            )

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        for signal in signals:
            signal.latency_ms = elapsed_ms
        return signals


#: Module-level instance; registration is the caller's (see tier1_patterns).
numeric_claims = NumericClaimsDetector()
