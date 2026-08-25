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
    text = REVIEW_TEXTS[4] + " A later estimate was 27,600 operations."
    signals = _run(numeric_claims, _ctx(text))
    assert [text[s.span.start : s.span.end] for s in signals] == ["27,600"]


def test_phone_shaped_price_remains_a_currency_claim() -> None:
    text = REVIEW_TEXTS[8]
    signals = _run(numeric_claims, _ctx(text))
    assert signals
    assert text[signals[0].span.start : signals[0].span.end] == "$555"


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
