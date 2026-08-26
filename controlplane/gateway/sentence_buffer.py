"""Sentence-level buffering of upstream tokens.

Implements 02 §4 (per-sentence loop) and ADR-002 (sentence-level interception, not
token-level, not full-response). Satisfies FR-GW-002.

**This module owns segmentation.** `detectors/tier1_patterns.py` and
`detectors/numeric_claims.py` each carry a local `_sentence_window` helper for the 04 §2
"same sentence" cue rules, and both say in comments that real segmentation belongs here.
They resolve a *window around a known match offset*; this resolves *where a stream may be
cut*. Those are different questions, which is why the duplication is deliberate rather
than drift — but there is exactly one answer to the second question, and it is here.

**The invariant, stated as the thing that can break.** FR-GW-002 says that for a flagged
sentence, no part of it reaches the client. This buffer therefore never emits a segment it
is not certain is complete, and `flush()` exists because the *last* sentence of a stream
usually has no boundary after it: `[.!?]\\s` cannot match at end-of-text. A buffer that
only emitted on a matched boundary would either drop the final sentence or leak it
unchecked — both are FR-GW-002 violations, and the second is the dangerous one because it
looks like working software.

**Segmentation is heuristic and that is ruled, not conceded** (ADR-002: "punctuation +
length cap; edge cases logged, not perfected"). Known imperfections are listed in
`KNOWN_LIMITATIONS` and surfaced by `Segmentation.limitations`, so they reach the audit
and the proposal instead of living in someone's memory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Sentence terminator followed by whitespace — the same shape the 04 §2 detectors use
#: for their cue windows, kept identical on purpose so "same sentence" means one thing.
#: Requiring the trailing whitespace is what makes `3.14` and `v1.2` not boundaries.
_BOUNDARY = re.compile(r"[.!?]+[\"')\]]*\s")

#: Terminator at the very end of the buffered text, with no following whitespace yet.
#: Only consulted by `flush()`: mid-stream, the next chunk may continue the token.
_TERMINAL = re.compile(r"[.!?]+[\"')\]]*$")

#: ADR-002's "length cap". A sentence that never terminates must still be released, or a
#: single unpunctuated response (a bulleted list, code, a runaway generation) stalls the
#: stream forever waiting for a boundary that will not come.
#:
#: 240 characters is a hackathon-grade choice, not a measured one: long enough that
#: ordinary prose is cut at punctuation rather than by the cap (so the cap does not become
#: the de-facto segmenter and distort the 04 §2 "same sentence" cue rules), short enough
#: that the Tier-1 <2 ms and Tier-2 <25 ms budgets are per-unit realistic. It is a
#: keyword argument because it is a tuning knob, not a contract.
DEFAULT_MAX_CHARS = 240

#: Where the cap may cut. Preferring a whitespace break keeps a redaction span from
#: starting mid-word, which would make `[REDACTED:...]` land inside a token.
_CAP_BREAK = re.compile(r"\s(?=\S*$)")

#: ADR-002's "edge cases logged, not perfected", enumerated so they are auditable.
KNOWN_LIMITATIONS: tuple[str, ...] = (
    "abbreviations ending in a period followed by a space (`Dr. Smith`, `U.S. law`) "
    "split into two units; each is still checked, so the interception guarantee holds "
    "and the cost is a possibly-odd unit boundary",
    "a sentence longer than max_chars is cut at the cap, at a whitespace break where "
    "one exists in the trailing window",
    "no locale awareness: `。`/`؟` and other non-ASCII terminators are not boundaries "
    "and such text is released by the cap instead",
)


@dataclass(frozen=True)
class Segment:
    """One unit of interception: the text plus where it sat in the whole response.

    `start`/`end` are offsets into the *concatenated* stream, so an audit record can say
    which part of a response an action applied to without storing the response
    (NFR-SEC-001). `reason` records whether punctuation or the cap ended it, because a
    cap-terminated unit is the case where segmentation was heuristic.
    """

    text: str
    start: int
    end: int
    reason: str  # "boundary" | "cap" | "flush"

    def __post_init__(self) -> None:
        if self.reason not in {"boundary", "cap", "flush"}:
            raise ValueError(f"unknown segment reason {self.reason!r}")


@dataclass
class Segmentation:
    """Accumulating segmenter. Feed chunks, take complete segments, flush at the end.

    Deliberately synchronous and free of policy: it decides *where a unit ends*, never
    what happens to one. The per-sentence detector/policy loop is `sse_proxy`'s job, and
    keeping the split here testable in isolation is what lets FR-GW-002 be pinned by
    tests that involve no upstream at all.
    """

    max_chars: int = DEFAULT_MAX_CHARS
    #: Unemitted tail, and the stream offset it begins at.
    _pending: str = ""
    _offset: int = 0
    #: Segments whose `reason` was "cap" — surfaced for the audit, since a cap cut is
    #: where the heuristic was doing the work rather than punctuation.
    cap_cuts: int = 0
    limitations: tuple[str, ...] = field(default=KNOWN_LIMITATIONS)

    def __post_init__(self) -> None:
        if self.max_chars < 1:
            raise ValueError("max_chars must be >= 1")

    def feed(self, chunk: str) -> list[Segment]:
        """Add streamed text; return every segment now certainly complete.

        Returns `[]` for a chunk that does not complete one — the normal case for a
        single token. A caller must therefore treat an empty list as "keep going", not
        as "nothing to check".
        """
        if chunk:
            self._pending += chunk
        return self._drain()

    def flush(self) -> list[Segment]:
        """End of stream: emit whatever remains, terminated or not.

        This is not a convenience. `[.!?]\\s` cannot match a sentence that ends the
        response, so without `flush()` the final sentence would never be checked —
        FR-GW-002's guarantee would hold for every sentence except the last one.
        """
        segments = self._drain()
        tail = self._pending
        if tail.strip():
            # `_TERMINAL` distinguishes "ended properly, just had no trailing space"
            # from "generation was cut off" — worth recording, and free to compute.
            reason = "boundary" if _TERMINAL.search(tail.rstrip()) else "flush"
            segments.append(self._take(len(tail), reason))
        else:
            self._advance(len(tail))
        return segments

    # -- internals ---------------------------------------------------------

    def _drain(self) -> list[Segment]:
        """Emit every complete segment currently in `_pending`."""
        out: list[Segment] = []
        while True:
            segment = self._next()
            if segment is None:
                return out
            out.append(segment)

    def _next(self) -> Segment | None:
        match = _BOUNDARY.search(self._pending)
        if match is not None and match.end() <= self.max_chars:
            return self._take(match.end(), "boundary")

        if len(self._pending) >= self.max_chars:
            # Cap. Prefer a whitespace break inside the capped window so the cut does
            # not land mid-word; fall back to a hard cut when there is no space at all
            # (a single very long token — a URL, a base64 blob).
            window = self._pending[: self.max_chars]
            break_at = _CAP_BREAK.search(window)
            cut = break_at.end() if break_at is not None and break_at.end() > 1 \
                else self.max_chars
            self.cap_cuts += 1
            return self._take(cut, "cap")

        # Nothing complete yet: no boundary has arrived and the cap is not reached, so
        # the caller keeps feeding. A boundary sitting *beyond* the cap cannot reach here
        # — `len(_pending) >= match.end() > max_chars` would have taken the cap branch
        # above — so this returns None only with no boundary in the buffer at all.
        return None

    def _take(self, upto: int, reason: str) -> Segment:
        """Cut `_pending[:upto]` out as a segment and advance the stream offset."""
        raw = self._pending[:upto]
        text = raw.strip()
        # `start` is the stream offset of `text[0]`, NOT of the raw slice: 04 §6 makes
        # span accuracy load-bearing for redaction, so a caller composing a detector's
        # in-segment span with this offset must land on the exact character. Counting the
        # stripped leading whitespace into `start` would shift every such span left.
        start = self._offset + (len(raw) - len(raw.lstrip()) if text else 0)
        self._advance(upto)
        return Segment(text=text, start=start, end=start + len(text), reason=reason)

    def _advance(self, upto: int) -> None:
        self._pending = self._pending[upto:]
        self._offset += upto

    @property
    def pending(self) -> str:
        """Text held back, not yet released to the client. Never empty mid-sentence."""
        return self._pending
