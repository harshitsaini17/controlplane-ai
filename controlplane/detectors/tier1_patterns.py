"""Tier-1 deterministic detectors: `tier1_pii`, `tier1_blocklist`.

Implements the 04 §2 registry rows (stage `input + output_sentence`, budget <2 ms,
span-accurate) and satisfies FR-DET-001. Evidence carries the category and pattern name
only, never the matched value (NFR-SEC-001 — a raw value here would be D7).

Both detectors are `score_kind="detection"` at score 1.0: ADR-012 fixes deterministic
emitters at 1.0, and 04 §1.2 excludes detection-kind signals from band logic entirely. A
regex either matched or it did not; there is no confidence to report, and inventing a
graded score would make the band appear to apply to something it cannot.

Design note — **format, not validity.** These patterns match the *shape* of a value and
deliberately do not check whether it could be real. That is not laxity, it is required in
both directions:

  * 06 §2 builds the corpus from never-assigned SSN ranges, reserved `555-01xx` phone
    numbers and RFC 2606 domains precisely so no case can carry a live identifier. A
    detector that rejected never-assigned ranges as "not a real SSN" would score 0 recall
    on a corpus that is safe *by construction*.
  * Redaction is the point (FR-POL-003). A user pasting a mistyped SSN still pasted an
    SSN, and a gateway that forwarded it because a checksum failed would leak it.

The one exception is the credit-card row, where the Luhn checksum is a *structural*
discriminator rather than a validity claim — see `_luhn_ok`.

DOC GAPS logged here rather than improvised (AGENTS.md §5, MINOR — obvious low-risk
answers taken, recorded in `08-open-questions.md`):

  1. **No base blocklist is defined anywhere in the docs.** 04 §2 gives `tier1_blocklist`
     exactly one documented term source, policy `blocklist_extra`, described as "per-use-case
     *extra* terms" — wording that implies a base list the docs never specify. All three
     shipped policies set `blocklist_extra: []`, so on the shipped configuration this
     detector correctly emits nothing. Inventing a base list would be writing policy into
     Python, which is the AGENTS.md §9.1 trap; the empty result is the honest one.
  2. **`pii.person_data` has no documented pattern.** It is in the 04 §1.1 taxonomy and no
     04 §2 row says how to detect it — it is a category ("employee record", "date of
     birth"), not a shape. `tier1_pii` therefore never emits it. It also has zero cases in
     the frozen corpus, so nothing is left unmeasured by the omission.
  3. **04 §2 says "Aho-Corasick keyword sets"; this uses a compiled regex alternation.**
     `pyahocorasick` is not a declared dependency and adding one for term counts in the
     single digits would not pay for itself. The doc names a data structure, the
     requirement is the <2 ms budget, and the semantics (leftmost-longest matching over a
     fixed term set) are identical. `_compile_terms` is the single seam to swap if a
     blocklist ever grows enough to matter.
"""

from __future__ import annotations

import re
import time
from typing import Iterable

from controlplane.detectors.base import (
    DetectorContext,
    Plane,
    ScoreKind,
    Signal,
    Span,
    Stage,
)

__all__ = ["Tier1BlocklistDetector", "Tier1PiiDetector", "tier1_blocklist", "tier1_pii"]


# --------------------------------------------------------------------------
# PII patterns (FR-DET-001: SSN, credit card, email, phone, API key)
# --------------------------------------------------------------------------

# Separators permitted inside a grouped number. 06 §2.3 states the corpus carries
# "obfuscation-lite (spaces/dashes)", so tolerating them is a spec requirement, not a
# guess about what authors might have typed.
_SEP = r"[-.\s]?"

#: SSN — `NNN-NN-NNNN` with optional separators, and the bare 9-digit run.
#:
#: The bare form is included with its eyes open. It is genuinely ambiguous with order
#: numbers and internal ids, and `clean.jsonl` carries digit strings as deliberate
#: false-positive pressure (06 §2.3), so this choice can only cost precision. It is made
#: anyway because the graded alternative — matching bare runs only near a keyword like
#: "SSN" — fails on exactly the case that matters most, a bare identifier volunteered with
#: no label around it. Whatever it costs will appear in the measured FP rate rather than
#: being hidden; that is the trade this project prefers (AGENTS.md §7).
_SSN = re.compile(rf"\b\d{{3}}{_SEP}\d{{2}}{_SEP}\d{{4}}\b")

#: Credit card — 13–19 digits in groups, Luhn-checked. Length range covers Amex (15)
#: through the 19-digit maximum.
_CARD = re.compile(r"\b\d(?:[-.\s]?\d){12,18}\b")

#: Email — RFC-shaped rather than RFC-complete. 06 §2 uses RFC 2606 reserved domains, and
#: subdomains thereof, so nothing here needs to (or should) resolve.
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9](?:[A-Za-z0-9.\-]*[A-Za-z0-9])?\.[A-Za-z]{2,}\b")

#: Phone — NANP, optional +1 and parenthesised area code. Must match the reserved
#: `555-01xx` block, which is where every phone case in the corpus lives (06 §2).
_PHONE = re.compile(
    rf"(?:\+1{_SEP})?(?:\(\d{{3}}\){_SEP}|\b\d{{3}}{_SEP})\d{{3}}{_SEP}\d{{4}}\b"
)

#: API keys — published vendor prefix families. Prefix-anchored on purpose: a generic
#: "long random-looking token" rule would fire on request ids, hashes and base64 blobs,
#: and no documented requirement asks for it.
_API_KEY = re.compile(
    r"""(?x)
    \b(?:
        sk-ant-[A-Za-z0-9\-_]{8,}     # Anthropic
      | sk-[A-Za-z0-9\-_]{16,}        # OpenAI-style
      | gsk_[A-Za-z0-9]{16,}          # Groq
      | ghp_[A-Za-z0-9]{16,}          # GitHub PAT (classic)
      | github_pat_[A-Za-z0-9_]{16,}  # GitHub PAT (fine-grained)
      | xox[baprs]-[A-Za-z0-9\-]{10,} # Slack
      | AKIA[0-9A-Z]{16}              # AWS access key id
      | AIza[A-Za-z0-9\-_]{20,}       # Google API key
      | SG\.[A-Za-z0-9\-_]{16,}       # SendGrid
    )\b
    """
)

#: Evaluation order. Longest-match-wins resolves most overlaps (a 16-digit card contains
#: shapes that look like a phone), but where two patterns match the *same* extent this
#: order decides, so it runs specific → general.
_PII_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("pii.api_key", _API_KEY, "vendor-prefix"),
    ("pii.credit_card", _CARD, "grouped-digits+luhn"),
    ("pii.email", _EMAIL, "rfc-shaped"),
    ("pii.ssn", _SSN, "nnn-nn-nnnn"),
    ("pii.phone", _PHONE, "nanp"),
)


def _luhn_ok(digits: str) -> bool:
    """Luhn mod-10 check.

    Used as a **structural discriminator**, not a validity claim: it is what separates a
    card number from an arbitrary 16-digit run, which is why `clean.jsonl`'s digit-string
    pressure does not become a wall of false positives. 06 §2 guarantees the corpus uses
    "test credit card numbers passing Luhn from test BINs", so requiring it cannot cost
    recall on a conforming case.
    """
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = ord(char) - 48
        if index % 2:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


class Tier1PiiDetector:
    """`tier1_pii` — 04 §2 row 1. Compiled patterns, span-accurate, <2 ms.

    Emits **one signal per matched span**, each carrying a single `pii.*` label. Multi-PII
    text therefore yields several signals, which is the shape 04 §4.3 expects: the engine
    resolves across signals by most-severe mapped action, and `redact` (04 §6) replaces one
    span per signal. Collapsing several categories into one multi-label signal would be the
    FR-DET-005 overlap shape, which 04 §1.1 reserves for the enrichment case where the
    labels genuinely describe *one* span.
    """

    name = "tier1_pii"

    async def detect(self, ctx: DetectorContext) -> list[Signal]:
        started = time.perf_counter()
        text = ctx.text or ""

        # (start, end, label, pattern_name)
        candidates: list[tuple[int, int, str, str]] = []
        for label, pattern, pattern_name in _PII_PATTERNS:
            for match in pattern.finditer(text):
                if label == "pii.credit_card":
                    digits = re.sub(r"\D", "", match.group())
                    if not (13 <= len(digits) <= 19 and _luhn_ok(digits)):
                        continue
                candidates.append((match.start(), match.end(), label, pattern_name))

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return [
            Signal(
                detector=self.name,
                planes=[Plane.RESPONSIBILITY],
                labels=[label],
                score=1.0,  # ADR-012: deterministic emitters report 1.0
                score_kind=ScoreKind.DETECTION,
                span=Span(start=start, end=end),
                stage=ctx.stage,
                # Category + pattern name only. The matched text is never interpolated;
                # base.py's evidence guard would reject it, and that guard is a tripwire,
                # not the primary defence (NFR-SEC-001).
                evidence=f"category:{label.split('.', 1)[1]} pattern={pattern_name}",
                latency_ms=elapsed_ms,
            )
            for start, end, label, pattern_name in _resolve_overlaps(candidates)
        ]


def _resolve_overlaps(
    candidates: Iterable[tuple[int, int, str, str]],
) -> list[tuple[int, int, str, str]]:
    """Leftmost-longest, non-overlapping.

    Overlap resolution is not cosmetic here: two signals covering the same characters
    would double-count in `cp_pii_intercepts_total{category}` and produce two redactions
    over one extent, the second operating on offsets the first already invalidated.

    Longest-wins is what makes a 16-digit card beat the phone-shaped run inside it. Ties
    at equal extent fall to `_PII_PATTERNS` order via the stable sort.
    """
    accepted: list[tuple[int, int, str, str]] = []
    for candidate in sorted(candidates, key=lambda c: (c[0], -(c[1] - c[0]))):
        start, end, _, _ = candidate
        if any(start < acc_end and acc_start < end for acc_start, acc_end, _, _ in accepted):
            continue
        accepted.append(candidate)
    return sorted(accepted, key=lambda c: c[0])


# --------------------------------------------------------------------------
# Blocklist
# --------------------------------------------------------------------------


def _compile_terms(terms: Iterable[str]) -> re.Pattern[str] | None:
    """Compile a term set into one leftmost-longest alternation.

    Terms are sorted longest-first so the alternation prefers the longest match at a given
    position, which is the property Aho-Corasick would give (see module docstring, gap 3).
    Each term is `re.escape`d — a blocklist is data from a policy file, and a stray `(` in
    it must be a literal, not a syntax error at load time.
    """
    unique = sorted({term for term in terms if term}, key=len, reverse=True)
    if not unique:
        return None
    return re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(term) for term in unique) + r")(?!\w)",
        re.IGNORECASE,
    )


class Tier1BlocklistDetector:
    """`tier1_blocklist` — 04 §2 row 2. Terms from policy `blocklist_extra`, <2 ms.

    Emits nothing on the shipped policies, all three of which set `blocklist_extra: []`.
    That is correct behaviour for the documented configuration, not an unfinished
    implementation: `blocklist_extra` is the only term source 04 §2 defines, and the base
    list its wording implies is specified nowhere (module docstring, gap 1). The detector
    is wired, budgeted and tested; it has no terms to match because the policies ship none.

    Consequence for the report, stated rather than buried: `security.blocklist` has **zero
    positives** in the frozen corpus, so this detector's recall is *undefined* — not 1.0.
    `eval/run_all.py` reports it as no-cases rather than letting an empty denominator
    render as a perfect score.
    """

    name = "tier1_blocklist"

    async def detect(self, ctx: DetectorContext) -> list[Signal]:
        started = time.perf_counter()
        pattern = _compile_terms(ctx.blocklist_extra)
        if pattern is None:
            return []

        text = ctx.text or ""
        matches = list(pattern.finditer(text))
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return [
            Signal(
                detector=self.name,
                planes=[Plane.RESPONSIBILITY],
                labels=["security.blocklist"],
                score=1.0,
                score_kind=ScoreKind.DETECTION,
                span=Span(start=match.start(), end=match.end()),
                stage=ctx.stage,
                # The term is policy-authored, not user content — but it is still not
                # echoed. A blocklist can encode slurs or embargoed product names, and
                # `evidence` lands in `audit_records.signals_json` (05 §3).
                evidence=f"category:blocklist pattern=term-match len={match.end() - match.start()}",
                latency_ms=elapsed_ms,
            )
            for match in matches
        ]


#: Module-level instances. Registration is the caller's (`register()` mutates a global,
#: so importing a module must not have that side effect — it would make test isolation
#: depend on import order).
tier1_pii = Tier1PiiDetector()
tier1_blocklist = Tier1BlocklistDetector()

# Stage note: neither detector filters on `ctx.stage`; both stamp whatever stage they are
# handed. 04 §2 lists them at `input + output_sentence`, and under ADR-014 UC-3 buffers a
# whole response, so `output_full` is a legitimate fourth caller. Which stages run a
# detector is the gateway's decision (02 §4); a detector enforcing it here would duplicate
# that wiring in a second place and disagree with it eventually.
