"""Independent Checkpoint-2 adversarial probes.

Hard assertions cover documented v1 behaviour.  ``xfail`` cases preserve known
limitations without converting undocumented evasion resistance into a contract.
No fixture below is copied from ``eval/dataset``; the first test enforces that.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from controlplane.detectors.base import DetectorContext, Stage
from controlplane.detectors.numeric_claims import numeric_claims
from controlplane.detectors.tier1_patterns import tier1_blocklist, tier1_pii


REVIEW_TEXTS = (
    "Notify audit.owner@example.test and then ring (555) 010-0166.",
    "Records 900 31 2468 and 666-72-1357 require separate handling.",
    "The prohibited phrase is cobalt (beta); cobalt is blocked, cobaltized is not.",
    "Revenue was $73.25 and margin was 18.6 percent.",
    "Per section 9, throughput reached 18,400 operations.",
    "Reach analyst＠example.test for the file.",
    "Reach analyst@exam​ple.test for the file.",
    "The customer supplied 4111,1111,1111,1111 as the card identifier.",
    "The displayed price is $555-0143 for the annual package.",
    "Use (115) 555-0123 for this independently authored review probe.",
)


def _ctx(
    text: str,
    *,
    context_docs: list[str] | None = None,
    blocklist_extra: list[str] | None = None,
) -> DetectorContext:
    return DetectorContext(
        text=text,
        stage=Stage.OUTPUT_SENTENCE,
        context_docs=context_docs or [],
        blocklist_extra=blocklist_extra or [],
    )


def _run(detector: object, ctx: DetectorContext):
    return asyncio.run(detector.detect(ctx))


def test_review_strings_are_not_frozen_dataset_fixtures() -> None:
    dataset_dir = Path(__file__).resolve().parents[2] / "eval" / "dataset"
    frozen = {
        json.loads(line)["text"]
        for path in dataset_dir.glob("*.jsonl")
        for line in path.read_text().splitlines()
        if line.strip()
    }
    assert not (set(REVIEW_TEXTS) & frozen)


def test_tier1_pii_multi_match_spans_are_exact() -> None:
    text = REVIEW_TEXTS[0]
    signals = _run(tier1_pii, _ctx(text))
    assert [signal.labels[0] for signal in signals] == ["pii.email", "pii.phone"]
    assert [text[s.span.start : s.span.end] for s in signals] == [
        "audit.owner@example.test",
        "(555) 010-0166",
    ]


def test_tier1_pii_spacing_and_dash_variants_keep_separate_spans() -> None:
    text = REVIEW_TEXTS[1]
    signals = _run(tier1_pii, _ctx(text))
    assert [signal.labels for signal in signals] == [["pii.ssn"], ["pii.ssn"]]
    assert [text[s.span.start : s.span.end] for s in signals] == [
        "900 31 2468",
        "666-72-1357",
    ]


def test_blocklist_escapes_terms_and_respects_word_boundaries() -> None:
    text = REVIEW_TEXTS[2]
    signals = _run(
        tier1_blocklist,
        _ctx(text, blocklist_extra=["cobalt (beta)", "cobalt"]),
    )
    assert [text[s.span.start : s.span.end] for s in signals] == [
        "cobalt (beta)",
        "cobalt",
    ]


def test_numeric_claims_multi_match_spans_are_exact() -> None:
    text = REVIEW_TEXTS[3]
    signals = _run(numeric_claims, _ctx(text))
    assert [text[s.span.start : s.span.end] for s in signals] == [
        "$73.25",
        "18.6 percent",
    ]


def test_numeric_citation_marker_suppresses_only_its_sentence() -> None:
    """The reviewer's property — a marker suppresses its own sentence and no later one — held
    with a marker the ruled list still recognises.

    REVIEW_TEXTS[4] ("Per section 9, ...") no longer carries a marker at all: ADR-025 dropped
    structural pointers from the list, and the D1 ruling removed the bare `per ` token that
    was incidentally catching this one. So the original fixture passed for a reason that no
    longer exists, and asserting on it would test nothing. Both facts are asserted below: the
    fixture's new behaviour, and the scoping property itself.
    """
    # Structural pointer is not a marker (ADR-025), so both figures fire.
    text = REVIEW_TEXTS[4] + " A later estimate was 27,600 operations."
    signals = _run(numeric_claims, _ctx(text))
    assert [text[s.span.start : s.span.end] for s in signals] == ["18,400", "27,600"]

    # The property, with a ruled determiner-form marker. Load-bearing under ADR-014: UC-3
    # buffers a whole response, so a text-wide search would let one citation in the opening
    # line silence every later figure — the highest-stakes use case getting the weakest check.
    scoped = "Throughput reached 18,400 operations per the filing. A later estimate was 27,600."
    scoped_signals = _run(numeric_claims, _ctx(scoped))
    assert [scoped[s.span.start : s.span.end] for s in scoped_signals] == ["27,600"]


def test_phone_shaped_price_remains_a_currency_claim() -> None:
    text = REVIEW_TEXTS[8]
    signals = _run(numeric_claims, _ctx(text))
    assert signals
    assert text[signals[0].span.start : signals[0].span.end] == "$555"


def test_invalid_nanp_area_code_fires_via_documented_v1_shadowing() -> None:
    """ADR-026 Amendment 1 / SL-2: accepted v1-superset behavior.

    The constrained NANP rows reject an NPA beginning with 1, but the retained broader v1
    phone pattern is evaluated first and shadows them. This is deliberately documented as
    shipping behavior, not asserted as NANP-valid syntax.
    """
    text = REVIEW_TEXTS[9]
    signals = _run(tier1_pii, _ctx(text))
    assert [signal.labels for signal in signals] == [["pii.phone"]]
    assert text[signals[0].span.start : signals[0].span.end] == "(115) 555-0123"


@pytest.mark.xfail(strict=True, reason="homoglyph normalization is outside the Tier-1 regex contract")
def test_tier1_pii_homoglyph_email_evasion_observation() -> None:
    assert _run(tier1_pii, _ctx(REVIEW_TEXTS[5]))


@pytest.mark.xfail(strict=True, reason="zero-width normalization is outside the Tier-1 regex contract")
def test_tier1_pii_zero_width_email_evasion_observation() -> None:
    assert _run(tier1_pii, _ctx(REVIEW_TEXTS[6]))


def test_numeric_claims_comma_grouped_card_is_not_a_quantity_observation() -> None:
    """C2-F3 — was `xfail(strict=True)` against v1; ADR-025 fixes it, so it is now a live
    regression assertion rather than a removed one.

    v2 suppresses this card *twice over*, and both mechanisms were confirmed by probe:
      1. §2.4.3's identifier pre-filter excludes the span, and
      2. no §2.4.1 shape matches it independently — `4111,1111,1111,1111` groups in FOURS,
         so the comma-grouped-**thousands** shape (d) never claims it either.
    The redundancy matters: the assertion does not rest on the pre-filter alone.
    """
    assert _run(numeric_claims, _ctx(REVIEW_TEXTS[7])) == []
