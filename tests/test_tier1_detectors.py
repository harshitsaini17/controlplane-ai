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


# --------------------------------------------------------------------------
# ADR-026 v2 pattern set — derived FROM THE SPECS, authored before the re-run
# --------------------------------------------------------------------------
#
# ADR-026 §4 requires these tests be written from the named specifications with no string
# copied from `eval/dataset/`. Every value below is authored here from the spec text:
#   ITU-T E.164   — country code + national number, 15 digits maximum
#   NANP          — (NPA) NXX-XXXX, N in [2-9] on both the area code and the exchange
#   RFC 7519/7515 — JWT as three dot-separated base64url segments, JOSE header a JSON object
#
# Safe by construction, same rules as 06 §2: the 555-01xx block is reserved for fiction, and
# country code 99 is unassigned, so no authored number here can reach a real subscriber. The
# JWT is not a sample at all — it is BUILT by base64url-encoding a JOSE header, so its
# provenance is RFC 7515 itself rather than any token anyone ever issued.


def _jose_jwt() -> str:
    """A JWT constructed from the specs rather than copied from anywhere.

    RFC 7515 §4 makes the JOSE header a JSON object and RFC 7519 §3 makes a JWS-form JWT
    three dot-separated base64url segments. Encoding the header here is what demonstrates the
    `eyJ` anchor is a property of the FORMAT: `{"` opens every JSON object, and base64url of
    `{"` is `eyJ`. Nothing about this string is fixture-shaped — it is derived.
    """
    import base64
    import json

    def segment(payload: dict[str, object]) -> str:
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = segment({"alg": "HS256", "typ": "JWT"})
    claims = segment({"sub": "0", "iat": 0})
    return f"{header}.{claims}.{'A' * 43}"


def test_rfc_7515_eyj_anchor_is_a_property_of_the_format() -> None:
    """ADR-026 permits the `eyJ` anchor on the grounds that it is spec-derived, and requires a
    written justification because that is what makes it auditable as non-fixture-shaped.

    The anchor IS spec-derived, but not by the arithmetic the ADR states. ADR-026 says `eyJ`
    "is the base64url encoding of `{"`" — it is not: base64 packs three bytes into four
    characters, so `{"` alone encodes to `eyI=`. The third output character straddles `"` and
    the byte that follows it:

        char 3 = ((0x22 & 0x0F) << 2) | (next_byte >> 6) = 8 | (next_byte >> 6)

    and base64 index 9 is `J`, so the anchor holds exactly when `next_byte >> 6 == 1`, i.e.
    the byte is in 0x40-0x7F — which every ASCII letter is. RFC 7515 §4 makes the header a
    JSON object and every registered parameter name begins with a letter, so the anchor holds
    for every conforming header whose first member is a registered parameter. The conclusion
    the ADR draws survives; only its stated derivation is imprecise, and the imprecision is
    filed rather than silently corrected in the ADR text.

    The limit this exposes is narrow and real: JSON permits whitespace after `{`, and
    `{ "alg"...` encodes to `eyIg` — no anchor. Asserted below so it is a known bound rather
    than a surprise.
    """
    import base64

    # The ADR's literal claim, recorded as false.
    assert base64.urlsafe_b64encode(b'{"') == b"eyI="

    # The true condition, and the reason it covers every conforming JOSE header.
    for parameter in (b"alg", b"jku", b"jwk", b"kid", b"x5u", b"x5c", b"x5t", b"typ", b"cty"):
        assert base64.urlsafe_b64encode(b'{"' + parameter).startswith(b"eyJ")

    # The documented bound: whitespace after `{` is legal JSON and defeats the anchor.
    assert not base64.urlsafe_b64encode(b'{ "alg"').startswith(b"eyJ")

    assert _jose_jwt().startswith("eyJ")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Call +1 415 555 0123 for help.", "+1 415 555 0123"),
        ("Dial +14155550123 now.", "+14155550123"),
        ("Try +99-912-345-6789 please.", "+99-912-345-6789"),
        ("Reach +999123456789012 today.", "+999123456789012"),  # 15 digits — E.164 maximum
    ],
)
def test_e164_international_form_matches(text: str, expected: str) -> None:
    """ITU-T E.164: leading `+`, country code, up to 15 digits, optional grouping.

    This is the shape v1 genuinely missed — v1's phone rule anchored on an optional `+1`, so
    every non-NANP international number was invisible to it.
    """
    assert (labels(text), matched(text)) == (["pii.phone"], [("pii.phone", expected)])


def test_e164_stops_at_the_fifteen_digit_maximum() -> None:
    """E.164 caps a number at 15 digits, so a 16-digit run is not an E.164 number.

    Asserted because the bound is the spec's, not a tuning choice: without it the pattern
    would drift toward matching any long `+`-prefixed digit run.
    """
    assert scan("Reach +9991234567890123 today.") == []


def test_nanp_paren_form_allows_spaces_inside_the_parentheses() -> None:
    """`( 415 ) 555-0123` — the variant v1's `\\(\\d{3}\\)` could not match."""
    text = "Ring ( 415 ) 555-0123 at noon."
    assert matched(text) == [("pii.phone", "( 415 ) 555-0123")]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Ring (415) 555-0123 at noon.", "(415) 555-0123"),
        ("Ring (415)555-0123 at noon.", "(415)555-0123"),
        ("Ring 415.555.0123 at noon.", "415.555.0123"),
    ],
)
def test_nanp_paren_and_dot_forms_match(text: str, expected: str) -> None:
    assert matched(text) == [("pii.phone", expected)]


@pytest.mark.parametrize(
    "bad",
    ["(115) 555-0123", "(015) 555-0123", "(415) 155-0123", "415.055.0123", "415.155.0123"],
)
def test_nanp_n_constraint_rejects_leading_0_and_1(bad: str) -> None:
    """NANP reserves a leading 0 or 1 on the area code (NPA) and the exchange (NXX) for
    operator and long-distance signalling, so `N ∈ [2-9]` is the spec's own constraint.

    Asserted against the **v2 patterns**, which is the extent of what can honestly be claimed
    today: the composed detector still fires on these values because v1's broader `_PHONE`
    rule is retained (deliberately — narrowing it would move the precision-1.000 v1 baseline)
    and shadows them at equal extent. That gap between 04 §2.5's precision claim and the
    composed behaviour is filed as an open deviation; this test asserts the constraint where
    it genuinely exists and does not pre-judge how the shadowing is resolved.
    """
    from controlplane.detectors.tier1_patterns import (
        _PHONE_NANP_DOT,
        _PHONE_NANP_PAREN,
    )

    assert not _PHONE_NANP_PAREN.search(bad)
    assert not _PHONE_NANP_DOT.search(bad)


def test_scope_exclusion_1_bare_seven_digit_local_number() -> None:
    """ADR-026 exclusion #1, a precision-grounded DLP trade-off and not fixture avoidance.

    A bare 7-digit local number is structurally identical to an order number, a ticket id or
    a record id — the false-positive pressure `clean.jsonl` exists to apply. It costs known
    recall, and the cost is reported rather than hidden (06 §3).
    """
    assert scan("Order 555-0123 shipped today.") == []


def test_rfc_7519_jwt_matches_as_an_api_key() -> None:
    text = f"Use {_jose_jwt()} as the bearer."
    assert matched(text) == [("pii.api_key", _jose_jwt())]


def test_three_base64url_segments_without_the_jose_anchor_do_not_match() -> None:
    """The anchor is what separates a JWT from any dotted token triple — a version string, a
    package coordinate, a dotted path. Without `eyJ` the shape is not a JOSE header."""
    assert scan("Use abcdefghij.klmnopqrst.uvwxyz1234 as the bearer.") == []


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "The api_key is 0123456789abcdef0123456789abcdef here.",
            "0123456789abcdef0123456789abcdef",
        ),
        ("Secret: " + "ab" * 32 + " rotated.", "ab" * 32),
    ],
)
def test_hex_secret_fires_only_with_a_credential_cue(text: str, expected: str) -> None:
    assert matched(text) == [("pii.api_key", expected)]


@pytest.mark.parametrize(
    "text",
    [
        "The build id is 0123456789abcdef0123456789abcdef exactly.",
        "Digest " + "ab" * 32 + " matched the archive.",
    ],
)
def test_scope_exclusion_2_bare_hex_without_a_cue(text: str) -> None:
    """ADR-026 exclusion #2. A bare 32/64-hex run collides with git SHAs, MD5/SHA digests,
    dashless UUIDs and trace ids, all of which appear in legitimate engineering text."""
    assert scan(text) == []


def test_hex_secret_length_is_exactly_32_or_64() -> None:
    """A range would readmit the collisions the cue requirement exists to exclude — a 40-char
    hex run is the git SHA-1 length, which is why it is not a secret shape."""
    assert scan("The token is " + "0123456789abcdef0123456789abcdef0123" + " here.") == []


def test_credential_cue_must_be_in_the_same_sentence() -> None:
    """Sentence scoping, for the same reason `numeric_claims` scopes its markers: a cue
    anywhere in a buffered UC-3 response would otherwise credentialize every digest in it."""
    assert scan("Rotate the api_key. Digest " + "ab" * 32 + " matched.") == []
