"""Tier-1 detector tests — `tier1_pii`, `tier1_blocklist` (FR-DET-001, 04 §2).

**Every value in this file is authored here.** Not one is copied from
`eval/dataset/*.jsonl`: the detectors were built from 04 §2 and must never be iterated
against the frozen corpus, or the eval measurement stops being independent of the thing it
measures. These tests assert the *documented contract*; whether that contract scores well on
the corpus is Step 4's question, answered by `eval/run_all.py` and reported as measured.

Safe-by-construction, same rules as 06 §2: never-assigned SSN ranges (000/666/9xx), Luhn-valid
test BINs, RFC 2606 domains, the reserved 555-01xx block, published documentation key literals.

No pytest-asyncio: it is not a declared dependency and `asyncio.run` in a sync test needs no
plugin (AGENTS.md §9.8, simplest stack wins).
"""

from __future__ import annotations

import asyncio

import pytest

from controlplane.detectors.base import (
    BUDGETS_MS,
    DetectorContext,
    Plane,
    ScoreKind,
    Signal,
    Stage,
    run_with_budget,
)
from controlplane.detectors.tier1_patterns import (
    _luhn_ok,
    tier1_blocklist,
    tier1_pii,
)


def scan(text: str, stage: Stage = Stage.OUTPUT_SENTENCE, **kwargs: object) -> list[Signal]:
    ctx = DetectorContext(text=text, stage=stage, **kwargs)  # type: ignore[arg-type]
    return asyncio.run(tier1_pii.detect(ctx))


def labels(text: str, **kwargs: object) -> list[str]:
    return sorted(s.labels[0] for s in scan(text, **kwargs))


def matched(text: str) -> list[tuple[str, str]]:
    """(label, exact matched substring) — reads the span back out of the text."""
    return [(s.labels[0], text[s.span.start : s.span.end]) for s in scan(text) if s.span]


# --------------------------------------------------------------------------
# FR-DET-001 — the five documented categories
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Member SSN 000-12-3456 verified.", "pii.ssn"),
        ("Card 4111 1111 1111 1111 on file.", "pii.credit_card"),
        ("Reach me at agent@example.com today.", "pii.email"),
        ("Dial 202-555-0142 for support.", "pii.phone"),
        ("Token sk-ant-api03-AAAAAAAAAAAAAAAA rotated.", "pii.api_key"),
    ],
)
def test_fr_det_001_detects_each_documented_category(text: str, expected: str) -> None:
    assert labels(text) == [expected]


def test_fr_det_001_multi_pii_yields_one_signal_per_span() -> None:
    """One signal per span, not one multi-label signal.

    04 §4.3 resolves across signals and 04 §6 `redact` replaces one span per signal;
    the multi-label shape is reserved for the FR-DET-005 enrichment case, where the
    labels describe a single span.
    """
    text = "Contact agent@example.com or 202-555-0142 about SSN 000-12-3456."
    signals = scan(text)
    assert len(signals) == 3
    assert all(len(s.labels) == 1 for s in signals)
    assert sorted(s.labels[0] for s in signals) == [
        "pii.email",
        "pii.phone",
        "pii.ssn",
    ]


# --------------------------------------------------------------------------
# Format, not validity — the property the frozen corpus depends on
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ssn",
    ["000-12-3456", "666-12-3456", "900-12-3456", "987-65-4320"],
)
def test_never_assigned_ssn_ranges_still_match(ssn: str) -> None:
    """06 §2 builds the corpus from ranges the SSA never assigns, so the dataset is safe
    by construction. A detector that rejected them as "not real" would score 0 recall on
    every PII case — and would forward a mistyped SSN in production."""
    assert labels(f"on file: {ssn}") == ["pii.ssn"]


def test_reserved_phone_block_matches() -> None:
    """555-01xx is the fictional block every corpus phone case uses (06 §2)."""
    assert labels("call 202-555-0100 please") == ["pii.phone"]


@pytest.mark.parametrize(
    "phone",
    ["202-555-0142", "(202) 555-0142", "202.555.0142", "+1 202-555-0142", "2025550142"],
)
def test_phone_separator_variants(phone: str) -> None:
    """06 §2.3 states the corpus carries "obfuscation-lite (spaces/dashes)", so tolerating
    separators is a spec requirement rather than a guess."""
    assert "pii.phone" in labels(f"reach {phone} now")


def test_subdomain_of_reserved_domain_matches() -> None:
    assert labels("write a.b+c@mail.corp.example.com") == ["pii.email"]


# --------------------------------------------------------------------------
# Luhn as a structural discriminator
# --------------------------------------------------------------------------


def test_luhn_valid_test_bin_matches() -> None:
    assert labels("card 4111111111111111") == ["pii.credit_card"]


def test_luhn_invalid_run_is_not_a_card() -> None:
    """What keeps `clean.jsonl`'s digit-string pressure from becoming false positives."""
    assert "pii.credit_card" not in labels("ref 4111111111111112")


def test_luhn_helper_agrees_with_known_vectors() -> None:
    assert _luhn_ok("4111111111111111")
    assert _luhn_ok("378282246310005")  # Amex test number, 15 digits
    assert not _luhn_ok("4111111111111112")


@pytest.mark.parametrize("digits", ["411111111111", "41111111111111111111"])
def test_card_length_bounds_enforced(digits: str) -> None:
    """13-19 digits (Amex 15 through the 19-digit maximum). Outside that, not a card."""
    assert "pii.credit_card" not in labels(f"ref {digits}")


# --------------------------------------------------------------------------
# False-positive pressure (06 §2.3 designs for this; it is measured, not assumed)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Your order 12345678 shipped today.",
        "Invoice 1234567 is settled.",
        "Version 2.4.13 is current.",
        "We resolved 4 of 5 tickets.",
        "Meeting at 3pm in room 204.",
    ],
)
def test_benign_text_emits_nothing(text: str) -> None:
    assert scan(text) == []


def test_api_key_rule_is_prefix_anchored() -> None:
    """A generic "long random token" rule would fire on request ids and hashes, and no
    documented requirement asks for one."""
    assert scan("request id 9f8e7d6c5b4a39281706f5e4d3c2b1a0") == []


# --------------------------------------------------------------------------
# Span accuracy (04 §1) — load-bearing for FR-POL-003 redaction
# --------------------------------------------------------------------------


def test_spans_are_exact_so_redaction_leaves_no_residue() -> None:
    text = "SSN 000-12-3456 confirmed."
    assert matched(text) == [("pii.ssn", "000-12-3456")]


def test_longest_match_wins_over_contained_shape() -> None:
    """A 16-digit card contains a phone-shaped run; two overlapping signals would
    double-count the interception metric and redact one extent twice."""
    text = "card 4111 1111 1111 1111 stored"
    assert matched(text) == [("pii.credit_card", "4111 1111 1111 1111")]


def test_no_two_signals_overlap() -> None:
    text = "SSN 000-12-3456 card 4111111111111111 mail x@example.com call 202-555-0142"
    spans = sorted((s.span.start, s.span.end) for s in scan(text) if s.span)
    assert all(spans[i][1] <= spans[i + 1][0] for i in range(len(spans) - 1))


def test_signals_are_ordered_by_position() -> None:
    text = "mail a@example.com then call 202-555-0142"
    starts = [s.span.start for s in scan(text) if s.span]
    assert starts == sorted(starts)


# --------------------------------------------------------------------------
# NFR-SEC-001 — evidence never carries the value
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,value",
    [
        ("SSN 000-12-3456 here", "000-12-3456"),
        ("mail agent@example.com here", "agent@example.com"),
        ("card 4111111111111111 here", "4111111111111111"),
        ("call 202-555-0142 here", "202-555-0142"),
    ],
)
def test_nfr_sec_001_evidence_excludes_the_matched_value(text: str, value: str) -> None:
    """Signals serialize verbatim into `audit_records.signals_json` (05 §3), so a leak in
    `evidence` is a leak at rest — D7 (AGENTS.md §5.1/§9.6)."""
    for signal in scan(text):
        assert value not in signal.evidence
        assert value.replace("-", "") not in signal.evidence
        assert "category:" in signal.evidence


def test_nfr_sec_001_evidence_names_the_category_and_pattern() -> None:
    signal = scan("SSN 000-12-3456 here")[0]
    assert signal.evidence == "category:ssn pattern=nnn-nn-nnnn"


# --------------------------------------------------------------------------
# ADR-012 / 04 §1 signal shape
# --------------------------------------------------------------------------


def test_adr_012_deterministic_emitters_report_detection_at_1_0() -> None:
    """04 §1.2: deterministic emitters use 1.0, and band logic never applies to
    detection-kind. A graded score here would make the band look applicable."""
    signal = scan("SSN 000-12-3456 here")[0]
    assert signal.score == 1.0
    assert signal.score_kind is ScoreKind.DETECTION


def test_pii_signals_carry_the_responsibility_plane() -> None:
    assert scan("SSN 000-12-3456")[0].planes == [Plane.RESPONSIBILITY]


@pytest.mark.parametrize(
    "stage", [Stage.INPUT, Stage.OUTPUT_SENTENCE, Stage.OUTPUT_FULL]
)
def test_stage_is_stamped_as_given(stage: Stage) -> None:
    """04 §2 lists `input + output_sentence`; ADR-014 adds `output_full` (UC-3 buffers the
    whole response). Which stages run a detector is the gateway's wiring (02 §4) — a
    detector enforcing it here would duplicate that decision and eventually disagree."""
    assert scan("SSN 000-12-3456", stage=stage)[0].stage is stage


def test_signal_carries_no_enriched_labels_key() -> None:
    """Only `entity_enricher` appends (04 §2.2, ADR-019)."""
    assert scan("SSN 000-12-3456")[0].meta == {}


# --------------------------------------------------------------------------
# NFR-P-002 — <2 ms
# --------------------------------------------------------------------------


def test_nfr_p_002_pii_completes_within_budget() -> None:
    """Indicative, not the benchmark: `eval/bench_latency.py` is the measurement of
    record (06 §4). This is the tripwire that catches a catastrophic regression in CI."""
    text = (
        "Thanks for reaching out about your account. Your order 12345678 shipped and "
        "tracking is available now. If anything looks wrong, reply to this message and "
        "an agent will follow up within one business day. "
    ) * 3
    signals = asyncio.run(
        run_with_budget(tier1_pii, DetectorContext(text=text, stage=Stage.OUTPUT_SENTENCE))
    )
    assert signals == []


def test_budget_is_registered_for_both_tier1_detectors() -> None:
    assert BUDGETS_MS["tier1_pii"] == 2.0
    assert BUDGETS_MS["tier1_blocklist"] == 2.0


# --------------------------------------------------------------------------
# tier1_blocklist
# --------------------------------------------------------------------------


def block(text: str, terms: list[str] | None = None) -> list[Signal]:
    ctx = DetectorContext(
        text=text, stage=Stage.OUTPUT_SENTENCE, blocklist_extra=terms or []
    )
    return asyncio.run(tier1_blocklist.detect(ctx))


def test_blocklist_is_silent_on_the_shipped_policies() -> None:
    """All three policies ship `blocklist_extra: []`, and `blocklist_extra` is the only
    term source 04 §2 defines. Emitting nothing is correct for the documented config —
    inventing a base list would be writing policy into Python (AGENTS.md §9.1)."""
    assert block("any text at all, however unpleasant") == []


def test_blocklist_matches_a_policy_supplied_term() -> None:
    signals = block("Please use the internal codename Fizzbuzz here.", ["Fizzbuzz"])
    assert len(signals) == 1
    assert signals[0].labels == ["security.blocklist"]
    assert signals[0].score == 1.0
    assert signals[0].score_kind is ScoreKind.DETECTION


def test_blocklist_span_is_exact() -> None:
    text = "codename Fizzbuzz confirmed"
    signal = block(text, ["Fizzbuzz"])[0]
    assert text[signal.span.start : signal.span.end] == "Fizzbuzz"


def test_blocklist_is_case_insensitive() -> None:
    assert len(block("codename FIZZBUZZ", ["fizzbuzz"])) == 1


def test_blocklist_respects_word_boundaries() -> None:
    """Substring matching would fire "cat" inside "concatenate"."""
    assert block("we concatenate the rows", ["cat"]) == []
    assert len(block("the cat sat", ["cat"])) == 1


def test_blocklist_prefers_the_longest_term_at_one_position() -> None:
    signals = block("project fizzbuzz alpha ships", ["fizzbuzz", "fizzbuzz alpha"])
    assert len(signals) == 1
    assert signals[0].span.end - signals[0].span.start == len("fizzbuzz alpha")


def test_blocklist_term_with_regex_metacharacters_is_literal() -> None:
    """Terms are policy data. A stray `(` must be a literal, not a load-time crash."""
    assert len(block("codename c++ (beta) here", ["c++ (beta)"])) == 1
    assert block("codename cxx beta", ["c++ (beta)"]) == []


def test_nfr_sec_001_blocklist_evidence_excludes_the_term() -> None:
    """A blocklist can encode slurs or embargoed names, and evidence is persisted."""
    signal = block("codename Fizzbuzz", ["Fizzbuzz"])[0]
    assert "Fizzbuzz" not in signal.evidence
    assert "fizzbuzz" not in signal.evidence.lower()


def test_blocklist_emits_one_signal_per_occurrence() -> None:
    assert len(block("Fizzbuzz then Fizzbuzz again", ["Fizzbuzz"])) == 2
