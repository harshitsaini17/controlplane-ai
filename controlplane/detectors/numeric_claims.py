"""`numeric_claims` heuristic detector.

Implements the 04 §2 registry row: stage `output_sentence`, budget <5 ms, emits
`hallucination.unsourced_numeric`, `score_kind="detection"` at 1.0 (ADR-012 — deterministic
emitters report 1.0 and band logic never applies).

The contract is 04 §2.4 as amended by **ADR-025**: a numeral fires iff it is
**quantity-shaped** (§2.4.1 — currency · percent · magnitude word or suffix · comma-grouped
thousands · attached unit), carries no citation marker (§2.4.2), and finds no match in
provided context. The final clause is policy and lives in `policies/*.yaml`, not here.

**v1's "large-number" rule is deleted, and that deletion is the whole point of ADR-025.**
The original row said "currency/percent/**large-number** patterns". Implemented faithfully
and measured blind, it returned **precision 0.267**: an SSN, a card number and a phone number
are all runs of digits, so a length-keyed rule classified **identifiers as statistics**
(deviation D8). The flaw was in the specified behaviour rather than the implementation of it,
which is why it needed a ruling. The v1 code is frozen in `_v1_numeric_claims.py` and still
runs, so that number stays reproducible rather than transcribed.

Two ordering facts worth knowing before editing anything below:

* the **identifier pre-filter runs first and is absolute** (§2.4.3). Not a post-hoc filter —
  an excluded span never reaches a shape branch, even when currency-adjacent, so behaviour
  cannot depend on match order.
* it is a **structural duplicate** of the `tier1_*` regexes, never a call into them. 04 §9.3
  keeps detectors independent, and a detector reading another's output would break it.

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
# v2 (ADR-025). Quantity shapes only — 04 §2.4.1.
#
# The v1 "large-number" rule (a bare run of 4+ digits) is DELETED. Measured blind it
# returned precision 0.267, because an SSN, a card number and a phone number are all runs
# of digits: the rule classified IDENTIFIERS AS STATISTICS. The frozen v1 implementation
# lives in `_v1_numeric_claims.py` and still runs, so that number stays reproducible.
#
# Magnitude words and units are ordered LONGEST-FIRST throughout. Regex alternation is
# leftmost-first, not longest-match: with `k|m|...|million` the bare `m` wins inside
# "million" and `$1.2 million` spans only `$1.2 m`. Span accuracy is load-bearing — 04 §6
# `soften` replaces exactly this extent — so the ordering is a correctness requirement.
# --------------------------------------------------------------------------

_NUM = r"\d+(?:\.\d+)?"
_GROUPED = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?"
_NUMBER = rf"(?:{_GROUPED}|{_NUM})"

#: 04 §2.4.1(c). Longest-first; `bn`/`k`/`m`/`b` are the suffix forms.
_MAGNITUDE = r"(?:trillion|thousand|billion|million|crore|lakh|bn|k|m|b)"

#: 04 §2.4.1(a). Symbols and ISO codes.
_CURRENCY_SYMBOL = r"[$£€¥₹]"
_ISO_CODE = r"(?:USD|EUR|GBP|JPY|INR|CAD|AUD|CHF|CNY)"

#: 04 §2.4.1(e) starter list — time · data · distance · mass · temperature. Longest-first
#: again (`min` before `mi` before `m`). Extension via `detector_params` is documented in
#: 04 §2.4.4 but NOT wired: the schema types that field `dict[str, dict[str, float]]`, which
#: cannot hold a list — filed as D2-detector-params-cannot-hold-list-values. The list here
#: is therefore the only source, and 04 §2.4.1(e) is normative for it.
_UNIT = r"(?:ms|min|hrs?|hours?|KB|MB|GB|TB|km|kg|lbs?|mi|°C|°F|s|m)"

#: (a) currency-adjacent.
_CURRENCY = re.compile(
    rf"""(?xi)
    {_CURRENCY_SYMBOL}\s?{_NUMBER}(?:\s?{_MAGNITUDE}\b)?
  | \b{_NUMBER}\s?(?:{_MAGNITUDE}\s)?{_ISO_CODE}\b
  | \b{_NUMBER}\s?(?:{_MAGNITUDE}\s)?(?:dollars?|euros?|pounds?|rupees?|yen)\b
    """
)

#: (b) percent. No trailing `\b` after `%`: `%` is not a word character, so a boundary
#: assertion there can only succeed before a letter or digit and fails on "22%." or
#: "22% of" — which in v1 left the branch unmatchable in ordinary prose.
_PERCENT = re.compile(
    rf"""(?xi)
    \b{_NUMBER}\s?%
  | \b{_NUMBER}\s?percent(?:age)?(?:\s+points?)?\b
    """
)

#: (c) magnitude word or suffix.
_MAGNITUDE_SHAPE = re.compile(rf"(?i)\b{_NUMBER}\s?{_MAGNITUDE}\b")

#: (d) comma-grouped thousands — the writing convention *for* a quantity.
_GROUPED_THOUSANDS = re.compile(rf"\b{_GROUPED}\b")

#: (e) attached measurement unit. Lookahead rather than `\b` so `°C`/`°F` behave.
_UNIT_SHAPE = re.compile(rf"\b{_NUMBER}\s?{_UNIT}(?![A-Za-z0-9])")

_NUMERAL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_CURRENCY, "currency"),
    (_PERCENT, "percent"),
    (_MAGNITUDE_SHAPE, "magnitude"),
    (_GROUPED_THOUSANDS, "grouped-thousands"),
    (_UNIT_SHAPE, "unit"),
)


# --------------------------------------------------------------------------
# Identifier exclusion — 04 §2.4.3. Pre-filter, FIRST and ABSOLUTE.
#
# Shares no code path, ordering dependency or output with `tier1_*`: the structures below
# are a deliberate STRUCTURAL DUPLICATE of those regexes, never a call into them, so 04 §9.3
# detector independence holds. An excluded candidate never reaches the shape branches above,
# even when currency- or percent-adjacent.
# --------------------------------------------------------------------------

_EXCL_SSN = re.compile(r"\b\d{3}[-.\s]\d{2}[-.\s]\d{4}\b")

#: 13-19 digits in optional groups, Luhn-checked below. Comma grouping is included because
#: 04 §2.4.3(1) names it, and because a comma-grouped card would otherwise be caught by
#: shape (d) — which is exactly the misclassification this exclusion exists to prevent.
_EXCL_CARD = re.compile(r"\b\d(?:[-.,\s]?\d){12,18}\b")

#: Phone forms per 04 §2.5 (E.164 + NANP), duplicated structurally.
_EXCL_PHONE = re.compile(
    r"""(?x)
    \+\d(?:[-.\s]?\d){6,14}\b                                  # E.164
  | \(\s?[2-9]\d{2}\s?\)[-.\s]?[2-9]\d{2}[-.\s]?\d{4}\b       # (NPA) NXX-XXXX
  | \b[2-9]\d{2}\.[2-9]\d{2}\.\d{4}\b                          # NPA.NXX.XXXX
  | \b(?:1[-.\s])?[2-9]\d{2}[-.\s][2-9]\d{2}[-.\s]\d{4}\b       # NPA-NXX-XXXX
    """
)

#: 04 §2.4.3(4) — a digit run inside an alphanumeric token (order ids, hashes, dashless
#: UUIDs, trace ids). Matched as any alnum token carrying both a digit and a letter.
_ALNUM_TOKEN = re.compile(r"\b[A-Za-z0-9]*\d[A-Za-z0-9]*\b")

#: A trailing magnitude suffix or unit does NOT make a numeral an identifier: `$5M` and
#: `250ms` are quantities, and the exclusion is written for "order IDs, hashes". So a token
#: is excluded only if letters survive stripping one recognised trailing suffix. This is an
#: interpretation of §2.4.3(4)'s intent, recorded here rather than left implicit — without
#: it the ABSOLUTE pre-filter would suppress shapes (c) and (e) entirely.
_TRAILING_SUFFIX = re.compile(rf"(?i)(?:{_MAGNITUDE}|{_UNIT})$")


def _luhn_ok(digits: str) -> bool:
    """Luhn mod-10. A structural discriminator, not a validity claim — it is what separates
    a card number from an arbitrary 16-digit run."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = ord(char) - 48
        if index % 2:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _identifier_spans(text: str) -> list[tuple[int, int]]:
    """Spans that are identifiers, not quantities (04 §2.4.3). Computed before any shape."""
    spans: list[tuple[int, int]] = []

    for match in _EXCL_SSN.finditer(text):
        spans.append(match.span())
    for match in _EXCL_PHONE.finditer(text):
        spans.append(match.span())
    for match in _EXCL_CARD.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            spans.append(match.span())
    for match in _ALNUM_TOKEN.finditer(text):
        token = match.group()
        if not any(char.isalpha() for char in token):
            continue
        stripped = _TRAILING_SUFFIX.sub("", token)
        if any(char.isalpha() for char in stripped):
            spans.append(match.span())

    return spans


# --------------------------------------------------------------------------
# Citation marker — 04 §2.4.2 (ADR-025 closed Q-18).
#
# Lexical only, and deliberately so: judging whether a citation actually SUPPORTS the figure
# is entailment, which is `rag_grounding`'s job. Hedges are absent — "roughly $4M" is an
# epistemic qualifier that 04 §6 `soften` handles, and admitting hedges would let an
# unsourced figure pass as attributed.
#
# This list is the RULED one, which is not the v1 provisional one. It drops structural
# pointers (`section 4`, `§ 12`), named filings (10-K, prospectus), bracketed author-year and
# the `ref:`/`see:` leaders; it adds `as per`, `cited by`, `based on`, `study by`,
# `survey by`, `data from`, `figures from`. Both directions move the FP rate, which is why
# the delta is recorded in docs/08 under Q-18 rather than left for someone to diff.
#
# `per` IS NOT A BARE TOKEN HERE (D1 ruling, ADR-025 amendment 1). ADR-025 first listed
# `"per "`, but `per` in English is overwhelmingly the RATE preposition, so a bare token
# silenced every rate-shaped figure — `$4 million per year` emitted nothing, and two corpus
# cases labelled `unsourced_numeric` were suppressed. The discriminator is grammatical: a
# rate takes a lowercase common noun (`per user`, `per month`); an attribution takes
# determiner + source (`per the filing`) or a proper noun (`per Gartner`). Hence three narrow
# forms instead of one broad one.
#
# `(?-i:[A-Z])` scopes case-sensitivity to that one branch. The pattern is globally `(?i)`,
# so a bare `[A-Z]` would match lowercase too and readmit the rate preposition wholesale —
# the exact bug this amendment exists to remove. The scoped flag is load-bearing, not style.
# --------------------------------------------------------------------------

_CITATION_MARKER = re.compile(
    r"""(?xi)
    \baccording\ to\b
  | \bas\ per\b                                  # retained from v1: unambiguously attributive
  | \bper\s+(?:the|this|that|its|their)\b       # determiner form -> a source is named
  | \bper\s+(?-i:[A-Z])                          # proper-noun form: "per Gartner"
  | \bas\ reported\ by\b | \breported\ by\b
  | \bcited\ by\b | \bcited\ in\b
  | \bsource:
  | \bbased\ on\b | \bstudy\ by\b | \bsurvey\ by\b
  | \bdata\ from\b | \bfigures\ from\b
  | \[\d+\]                                    # bracketed numeric reference
  | \([^)]*(?:19|20)\d{2}[^)]*\)               # parenthetical author-year
  | https?://\S+ | \bwww\.\S+
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

        # 04 §2.4.3: the identifier pre-filter runs FIRST and is ABSOLUTE. Computed once,
        # before any shape is considered, so no shape branch can ever see an excluded span
        # — not even a currency-adjacent one. Ordering is the whole point: making this a
        # post-hoc filter would leave behaviour dependent on match order.
        identifier_spans = _identifier_spans(text)

        candidates: list[tuple[int, int, str]] = []
        for pattern, shape in _NUMERAL_PATTERNS:
            for match in pattern.finditer(text):
                fragment = match.group().strip()
                start, end = match.start(), match.start() + len(fragment)
                if any(start < id_end and id_start < end for id_start, id_end in identifier_spans):
                    continue
                candidates.append((start, end, shape))

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
