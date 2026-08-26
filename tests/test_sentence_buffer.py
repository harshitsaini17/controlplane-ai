"""Sentence buffer: the FR-GW-002 interception guarantee and ADR-002 segmentation.

FR-GW-002 says that for a flagged sentence, **no part of it reaches the client**. That
guarantee is only as good as this module's refusal to emit an incomplete unit, so the
tests below are written against the ways it could silently fail — a final sentence never
checked, a unit released before its boundary arrived, text lost between chunks — rather
than against the happy path.
"""

from __future__ import annotations

import re

import pytest

from controlplane.gateway.sentence_buffer import (
    DEFAULT_MAX_CHARS,
    KNOWN_LIMITATIONS,
    Segment,
    Segmentation,
)

PROSE = "The refund window is 30 days. Contact support for help! Is that clear?"


def run(stream: str, *, chunk: int = 1, max_chars: int = DEFAULT_MAX_CHARS) -> list[Segment]:
    """Feed `stream` in fixed-size chunks, then flush — one full streaming pass."""
    buffer = Segmentation(max_chars=max_chars)
    out: list[Segment] = []
    for index in range(0, len(stream), chunk):
        out.extend(buffer.feed(stream[index:index + chunk]))
    out.extend(buffer.flush())
    return out


# --------------------------------------------------------------------------
# FR-GW-002 — a unit is never emitted before it is complete
# --------------------------------------------------------------------------


def test_fr_gw_002_no_segment_is_emitted_before_its_boundary_arrives() -> None:
    """★ Feeding one character at a time must not release a partial sentence.

    This is the interception guarantee in its rawest form: if the buffer ever emitted a
    prefix, a detector would score half a sentence and the other half would reach the
    client unchecked.
    """
    buffer = Segmentation()
    emitted: list[Segment] = []
    for index, char in enumerate(PROSE):
        for segment in buffer.feed(char):
            # Whatever came out must be a complete unit that ends at or before the text
            # fed so far — never a fragment awaiting more input.
            assert segment.end <= index + 1
            assert re.search(r"[.!?][\"')\]]*$", segment.text), \
                f"released a fragment: {segment.text!r}"
            emitted.append(segment)
    assert emitted, "nothing was emitted mid-stream; the check proved nothing"


def test_fr_gw_002_the_final_sentence_is_flushed_not_dropped() -> None:
    """★ `[.!?]\\s` cannot match at end-of-text, so the last sentence needs `flush()`.

    Without it, FR-GW-002 would hold for every sentence except the last — and the
    failure mode is a leak that looks like working software.
    """
    tail = "Your balance is 42 dollars"  # no terminator at all
    buffer = Segmentation()
    assert buffer.feed(tail) == [], "an unterminated tail must be held back"
    flushed = buffer.flush()
    assert [segment.text for segment in flushed] == [tail]
    assert flushed[0].reason == "flush"


def test_a_terminated_final_sentence_flushes_as_a_boundary() -> None:
    """"Ended properly, no trailing space" differs from "generation was cut off"."""
    buffer = Segmentation()
    buffer.feed("All set.")
    assert buffer.flush()[0].reason == "boundary"


def test_nothing_is_held_back_after_a_flush() -> None:
    buffer = Segmentation()
    buffer.feed(PROSE)
    buffer.flush()
    assert buffer.pending == ""


def test_pending_holds_the_unreleased_tail() -> None:
    """What the client has NOT seen yet must be inspectable, for mid-stream BLOCK."""
    buffer = Segmentation()
    buffer.feed("Done. Half a sen")
    assert buffer.pending == "Half a sen"


# --------------------------------------------------------------------------
# Conservation — no text is invented or silently lost
# --------------------------------------------------------------------------


@pytest.mark.parametrize("chunk", [1, 2, 3, 7, 13, 1000])
def test_segmentation_is_independent_of_how_the_stream_is_chunked(chunk: int) -> None:
    """★ A token split across two SSE frames must not change the units.

    Upstream chunk boundaries are arbitrary. If they influenced segmentation, the same
    response would be checked as different units run to run, and an eval number measured
    on one chunking would not describe the other.
    """
    assert [(s.text, s.start, s.end) for s in run(PROSE, chunk=chunk)] \
        == [(s.text, s.start, s.end) for s in run(PROSE, chunk=1)]


@pytest.mark.parametrize("stream", [
    PROSE,
    "One sentence only",
    "Trailing whitespace.   ",
    "  Leading whitespace is stripped.",
    "Multiple!!! Terminators??? Here.",
    "A very long unpunctuated run " * 20,
])
def test_no_text_is_lost_or_invented(stream: str) -> None:
    """Every non-whitespace character arrives exactly once, in order."""
    joined = "".join(segment.text for segment in run(stream, chunk=5))
    assert re.sub(r"\s+", "", joined) == re.sub(r"\s+", "", stream)


@pytest.mark.parametrize("stream", ["", "   ", "\n\n", "\t "])
def test_an_empty_or_whitespace_only_stream_yields_no_segments(stream: str) -> None:
    """An empty unit would be sent to detectors and audited as a checked sentence."""
    assert run(stream) == []


def test_offsets_index_the_original_stream_exactly() -> None:
    """★ 04 §6 redaction replaces an exact extent, so `start + span.start` must land.

    An off-by-one here leaves part of a matched PII value in the released text — the
    failure `Span`'s own docstring calls out as load-bearing.
    """
    for segment in run(PROSE, chunk=4):
        assert PROSE[segment.start:segment.end] == segment.text


def test_offsets_skip_leading_whitespace_rather_than_counting_it() -> None:
    stream = "First.    Second."
    second = run(stream)[1]
    assert stream[second.start] == "S"
    assert second.text == "Second."


# --------------------------------------------------------------------------
# ADR-002 — punctuation plus a length cap
# --------------------------------------------------------------------------


def test_adr002_boundaries_split_on_terminators() -> None:
    assert [s.text for s in run(PROSE)] == [
        "The refund window is 30 days.",
        "Contact support for help!",
        "Is that clear?",
    ]


def test_closing_quotes_and_brackets_stay_with_their_sentence() -> None:
    """Cutting before a closing quote would put stray punctuation on the next unit."""
    assert [s.text for s in run('He said "no thanks." Then he left.')] == [
        'He said "no thanks."',
        "Then he left.",
    ]


@pytest.mark.parametrize("stream", [
    "Growth was 3.14 percent this year.",
    "Upgrade to v1.2 now.",
    "The rate is 0.5 and holds.",
])
def test_decimals_and_versions_are_not_boundaries(stream: str) -> None:
    """★ Requiring whitespace after the terminator is what makes this work.

    Splitting `3.14` would hand `numeric_claims` the fragment `3.` and destroy the
    quantity shape its 04 §2.4 rule depends on.
    """
    assert [s.text for s in run(stream)] == [stream]


def test_adr002_the_cap_releases_an_unpunctuated_run() -> None:
    """Without a cap, a bulleted list or code block stalls the stream forever."""
    stream = "word " * 200
    segments = run(stream, max_chars=50)
    assert len(segments) > 1
    assert all(len(segment.text) <= 50 for segment in segments)
    assert any(segment.reason == "cap" for segment in segments)


def test_the_cap_prefers_a_whitespace_break() -> None:
    """A mid-word cut would let `[REDACTED:...]` land inside a token."""
    for segment in run("alpha beta gamma delta epsilon zeta", max_chars=12):
        if segment.reason == "cap":
            assert not segment.text.endswith(("alph", "bet", "gamm")), \
                f"cut mid-word: {segment.text!r}"


def test_a_single_oversized_token_is_hard_cut() -> None:
    """A URL or base64 blob has no whitespace to break on; it must still be released."""
    segments = run("x" * 300, max_chars=100)
    assert len(segments) == 3
    assert all(segment.reason == "cap" for segment in segments)


def test_cap_cuts_are_counted_for_the_audit() -> None:
    """A cap cut is where the heuristic did the work; that is worth recording."""
    buffer = Segmentation(max_chars=20)
    buffer.feed("no terminators here at all just words and more words")
    buffer.flush()
    assert buffer.cap_cuts > 0


def test_a_boundary_beyond_the_cap_still_yields_capped_units() -> None:
    """The cap wins over a distant boundary — proven unreachable as a stall state."""
    segments = run("a" * 80 + ". Next.", max_chars=30)
    assert segments[0].reason == "cap"
    assert "Next." in [segment.text for segment in segments]


# --------------------------------------------------------------------------
# Contract surface
# --------------------------------------------------------------------------


def test_adr002_known_limitations_are_enumerated_not_hidden() -> None:
    """ADR-002 rules segmentation heuristic with "edge cases logged, not perfected"."""
    assert len(KNOWN_LIMITATIONS) >= 3
    assert Segmentation().limitations == KNOWN_LIMITATIONS


def test_the_documented_abbreviation_limitation_is_real_and_still_checked() -> None:
    """Honesty test: `Dr. Smith` does split — and both halves are still intercepted.

    Asserting the *actual* heuristic behaviour, so the limitation entry cannot drift
    into a claim the code does not make.
    """
    texts = [segment.text for segment in run("Dr. Smith called.")]
    assert texts == ["Dr.", "Smith called."]
    assert "".join(texts).replace(" ", "") == "Dr.Smithcalled."


def test_an_unknown_segment_reason_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown segment reason"):
        Segment(text="hi", start=0, end=2, reason="guess")


@pytest.mark.parametrize("cap", [0, -1])
def test_a_nonsense_cap_is_refused(cap: int) -> None:
    with pytest.raises(ValueError, match="max_chars"):
        Segmentation(max_chars=cap)


def test_the_buffer_holds_no_policy_surface() -> None:
    """It decides where a unit ends, never what happens to one (02 §4 separation)."""
    assert not {"verdict", "policy", "evaluate", "action"} & set(vars(Segmentation()))
