"""`numeric_claims` tests — 04 §2 registry row.

Same discipline as `test_tier1_detectors.py`: **every value is authored here**, none copied
from the frozen corpus. The detector was built from the 04 §2 sentence and must never be
iterated against `eval/dataset/`, or Step 4's measurement stops being independent.

The row reads (as amended by ADR-025): *"**quantity-shaped** numerals only (§2.4 — the bare
large-digit-run rule is DELETED) with no citation marker (§2.4.2) and no match in provided
context; identifier structures are excluded by a pre-filter; high-stakes use cases map it to
ESCALATE."* The last clause is policy and is asserted in the policy tests, not here.

**Deleted behaviour is asserted here as deleted.** ADR-025 removed the bare digit-run rule and
narrowed the citation list; the tests that used to assert those now assert their absence, so a
silent re-introduction fails the suite instead of passing it.
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
from controlplane.detectors.numeric_claims import numeric_claims


def scan(
    text: str,
    context_docs: list[str] | None = None,
    stage: Stage = Stage.OUTPUT_SENTENCE,
) -> list[Signal]:
    ctx = DetectorContext(
        text=text, stage=stage, context_docs=context_docs or []
    )
    return asyncio.run(numeric_claims.detect(ctx))


def fired(text: str, context_docs: list[str] | None = None) -> list[str]:
    """The exact substrings that fired — reads spans back out of the text."""
    return [text[s.span.start : s.span.end] for s in scan(text, context_docs) if s.span]


# --------------------------------------------------------------------------
# Clause 1 — the three documented numeral shapes
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("The annual fee is $1,200 total.", "$1,200"),
        ("It costs $5 monthly.", "$5"),
        ("Revenue reached $1.2 million.", "$1.2 million"),
        ("We charge 450 USD upfront.", "450 USD"),
        ("The rebate is 30 dollars.", "30 dollars"),
    ],
)
def test_currency_shape_fires_with_an_exact_span(text: str, expected: str) -> None:
    assert fired(text) == [expected]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Growth hit 22%.", "22%"),
        ("Returns averaged 7.4 percent.", "7.4 percent"),
        ("Margins rose 3 percentage points.", "3 percentage points"),
        ("Adoption is 88 percent overall.", "88 percent"),
    ],
)
def test_percent_shape_fires_with_an_exact_span(text: str, expected: str) -> None:
    assert fired(text) == [expected]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Adoption reached 2.4 million users.", "2.4 million"),
        ("The backlog is 1,200 items.", "1,200"),
        ("It handles 3 billion events.", "3 billion"),
        ("We shipped 40k units.", "40k"),
    ],
)
def test_magnitude_and_grouped_shapes_fire_with_an_exact_span(
    text: str, expected: str
) -> None:
    """§2.4.1 shapes (c) magnitude word / k-M-B suffix and (d) comma-grouped thousands."""
    assert fired(text) == [expected]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Latency was 250 ms at peak.", "250 ms"),
        ("Backup is 1.5 GB total.", "1.5 GB"),
        ("The route is 12 km long.", "12 km"),
        ("Payload weighs 3 kg net.", "3 kg"),
        ("Chamber held 300 °C steady.", "300 °C"),
    ],
)
def test_unit_shape_fires_with_an_exact_span(text: str, expected: str) -> None:
    """§2.4.1 shape (e) — attached measurement unit from the starter list."""
    assert fired(text) == [expected]


@pytest.mark.parametrize(
    "text",
    [
        "We processed 15000 requests.",
        "The queue held 482913 messages.",
        "It returned 9000000 rows.",
    ],
)
def test_a_bare_digit_run_does_not_fire(text: str) -> None:
    """ADR-025 DELETED the bare large-digit-run rule, and this asserts the deletion.

    Measured against the labelled corpus that rule scored precision 0.267 (D8): an SSN, a
    card number and a phone number are all runs of digits, so it classified *identifiers as
    statistics*. A numeral is a claim only if §2.4.1 gives it a quantity shape. Asserted
    positively so re-introducing the rule fails the suite rather than quietly restoring the
    false-positive rate the ADR was written to remove.
    """
    assert scan(text) == []


def test_magnitude_word_is_inside_the_span() -> None:
    """Regression: alternation is leftmost-first, not longest, so an unordered
    `k|m|…|million` let the bare `m` win inside "million" and the span stopped at
    `$1.2 m`. 04 §6 `soften` replaces exactly this extent."""
    assert fired("Revenue reached $1.2 million.") == ["$1.2 million"]


def test_percent_span_includes_its_digits() -> None:
    """Regression: a trailing `\\b` after `%` is unmatchable before "." or a space, which
    left a fallback matching the bare `%` — a zero-digit span that also skipped the
    context check, so a fully-grounded percentage still fired."""
    assert fired("Growth hit 22%.") == ["22%"]
    assert fired("Up 22% of revenue.") == ["22%"]


def test_one_signal_per_numeral_not_per_matching_pattern() -> None:
    """`$1.2 million` is both currency and large-number; two signals would double-count
    one claim in the report and in 04 §4.3's resolution."""
    signals = scan("Revenue reached $1.2 million.")
    assert len(signals) == 1


def test_several_numerals_yield_several_signals() -> None:
    text = "Fees are $1,200 and growth hit 22%."
    assert fired(text) == ["$1,200", "22%"]


def test_no_numerals_emits_nothing() -> None:
    assert scan("There is no figure in this sentence at all.") == []


# --------------------------------------------------------------------------
# Years and small integers — deliberate exclusions
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "In 2024 revenue rose sharply.",
        "The policy dates from 1998.",
        "We expect this in 2026.",
        "Version 2.4.13 is current.",
        "We resolved 4 of 5 tickets.",
        "Room 204 on floor 3.",
    ],
)
def test_dates_versions_and_small_counts_stay_silent(text: str) -> None:
    """06 §2.3 ships grounded version numbers and years as explicit negative controls: a
    numeral is not automatically a statistic."""
    assert scan(text) == []


def test_year_exclusion_is_a_known_heuristic_limit() -> None:
    """Stated rather than hidden: a 4-digit *quantity* in a year's range is missed.

    "2024 units" is a real count and the detector stays silent, because nothing separates
    it from "in 2024" without parsing. The trade is deliberate — years appear in ordinary
    prose constantly and quantities in exactly that range are rare — and it is asserted here
    so the limitation is visible in the suite rather than discovered from a report.
    """
    assert scan("We shipped 2024 units last quarter.") == []


# --------------------------------------------------------------------------
# Clause 2 — citation markers
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Revenue was $4 million [2].",
        "Revenue was $4 million (Smith, 2024).",
        "Revenue was $4 million (2024).",
        "According to the report, revenue was $4 million.",
        "Revenue was $4 million as reported by the auditor.",
        "Per the filing, revenue was $4 million.",
        "Source: revenue was $4 million.",
        "Revenue was $4 million, see https://example.com/report.",
    ],
)
def test_a_citation_marker_suppresses_the_signal(text: str) -> None:
    assert scan(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "As per the auditor, revenue was $4 million.",
        "Per the filing, revenue was $4 million.",
        "Per this report, revenue was $4 million.",
        "Per that analysis, revenue was $4 million.",
        "Per its own disclosure, revenue was $4 million.",
        "Per their guidance, revenue was $4 million.",
        "Per Gartner, revenue was $4 million.",
        "Revenue was $4 million per Reuters.",
    ],
)
def test_per_in_an_attribution_form_is_a_marker(text: str) -> None:
    """The D1 ruling's three narrow forms: `as per`, determiner, proper noun (04 §2.4.2)."""
    assert scan(text) == []


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Cost is $4 million per year.", "$4 million"),
        ("Latency was 250 ms per request.", "250 ms"),
        ("Throughput hit 22% per node.", "22%"),
        ("We store 4 TB per tenant.", "4 TB"),
        ("That is 30k per employee.", "30k"),
        ("Roughly 1,200 events per day.", "1,200"),
    ],
)
def test_per_as_the_rate_preposition_is_not_a_marker(text: str, expected: str) -> None:
    """The D1 regression, asserted so it cannot come back.

    ADR-025 first listed the bare token `"per "`. `per` in English is overwhelmingly the
    **rate** preposition, so the bare token silenced every rate-shaped figure — and rates are
    the shape financial and performance claims most often take, on the detector whose UC-3
    mapping is ESCALATE. Two frozen-corpus cases labelled `unsourced_numeric` were suppressed
    by it. The discriminator is grammatical: a rate takes a lowercase common noun, an
    attribution takes determiner + source or a proper noun.
    """
    assert fired(text) == [expected]


def test_case_sensitivity_of_the_proper_noun_form_is_load_bearing() -> None:
    """The marker pattern is globally `(?i)`, so the proper-noun branch scopes it off with
    `(?-i:[A-Z])`. An unscoped `[A-Z]` would match lowercase under the global flag and
    readmit the rate preposition wholesale — reintroducing D1 while looking correct.
    """
    from controlplane.detectors.numeric_claims import _CITATION_MARKER

    assert _CITATION_MARKER.search("per Gartner")
    assert not _CITATION_MARKER.search("per gartner")
    assert not _CITATION_MARKER.search("per user")


def test_documented_edge_sentence_initial_per_plus_common_noun() -> None:
    """A stated bound of the D1 ruling, asserted rather than left to be discovered.

    `Per company filings, ...` is a real attribution whose object is a lowercase common noun,
    so no form matches and the figure fires — a false positive on a cited claim. That is the
    **safe** direction for a label mapped to EDIT/ESCALATE: it costs a softening or a review,
    where the opposite error costs an unsourced figure reaching a user.
    """
    assert fired("Per company filings, revenue was $4 million.") == ["$4 million"]


def test_capitalized_unit_rates_are_a_known_bound_of_the_proper_noun_form() -> None:
    """The other side of the same bound: a capitalized *unit* reads as a proper noun.

    `per GB` and `per API call` are rates, but the proper-noun branch cannot tell them from
    `per Gartner` without a lexicon. Measured exposure on the frozen corpus is **zero** cases,
    so it moves no number; it is asserted so the limit is visible in the suite rather than
    found later in a report.
    """
    assert scan("Storage costs $4 million per GB.") == []


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Revenue was $4 million [Smith 2024].", "$4 million"),
        ("See section 4: revenue was $4 million.", "$4 million"),
        ("The 10-K states revenue was $4 million.", "$4 million"),
        ("Revenue was $4 million per § 12.", "$4 million"),
    ],
)
def test_shapes_dropped_from_the_ruled_marker_list_still_fire(
    text: str, expected: str
) -> None:
    """Q-18 closed with a *lexical* marker list (§2.4.2), and these three shapes are not on
    it: a bracketed author-year, a structural pointer into the document, and a named filing.

    v1 recognised all three. Their removal can only *raise* the firing rate, never lower it,
    so it cannot flatter a recall number — which is why the direction is recorded rather than
    just the change. Asserted positively so the narrowing is visible in the suite instead of
    being inferable only from a report diff.
    """
    assert fired(text) == [expected]


@pytest.mark.parametrize(
    "text",
    [
        "Roughly $4 million, I think.",
        "Approximately 22% of users.",
        "About 15,000 requests, give or take.",
        "Somewhere near $1.2 million.",
    ],
)
def test_a_hedge_is_not_a_citation(text: str) -> None:
    """A hedge is an epistemic qualifier; 04 §6 `soften` handles those. Treating one as an
    attribution would let "roughly $4M" pass as sourced."""
    assert len(scan(text)) == 1


def test_marker_scope_is_the_sentence_not_the_whole_text() -> None:
    """Load-bearing under ADR-014: UC-3 buffers a whole response at `output_full`, so a
    text-wide search would let one citation in the opening line silence every later figure
    — the highest-stakes use case getting the weakest check."""
    text = "Fees are $1,200 [1]. Growth hit 22%."
    assert fired(text) == ["22%"]


def test_marker_in_a_later_sentence_does_not_reach_backwards() -> None:
    text = "Growth hit 22%. Fees are $1,200 [1]."
    assert fired(text) == ["22%"]


def test_output_full_and_output_sentence_agree_per_sentence() -> None:
    """Consequence of sentence scoping, and what keeps the streaming and non-streaming
    eval rows comparable (06 §4)."""
    text = "Fees are $1,200. Growth hit 22%."
    assert fired(text) == ["$1,200", "22%"]
    per_sentence = [s for part in ("Fees are $1,200.", "Growth hit 22%.") for s in fired(part)]
    assert per_sentence == ["$1,200", "22%"]


# --------------------------------------------------------------------------
# Clause 3 — context matching
# --------------------------------------------------------------------------


def test_a_figure_present_in_context_does_not_fire() -> None:
    assert scan("The fee is $1,200 annually.", ["The annual fee is 1200 dollars."]) == []


def test_separators_do_not_defeat_the_context_match() -> None:
    """Digit-identity ignores separators, so "2,400" matches a context saying "2400"."""
    assert scan("We processed 2,400 items.", ["Processed 2400 items."]) == []


def test_a_figure_absent_from_context_still_fires() -> None:
    assert fired("The fee is $1,900 annually.", ["The annual fee is 1200 dollars."]) == [
        "$1,900"
    ]


def test_context_matching_is_digit_identity_not_magnitude() -> None:
    """A stated limitation, asserted so it is visible.

    "2.4 million" does not match a context saying "2,400,000" — the digit keys differ. The
    error is one-directional: it can only over-flag a supported figure, never miss an
    unsupported one. For a detector whose high-stakes mapping is ESCALATE, an over-flag
    costs a review and an under-flag costs a fabricated number reaching a user, so the
    asymmetry sits on the safe side. Semantic magnitude matching is `rag_grounding`'s job.
    """
    assert fired("Adoption hit 2.4 million.", ["Adoption reached 2,400,000 users."]) == [
        "2.4 million"
    ]


def test_no_context_docs_means_nothing_is_grounded() -> None:
    assert len(scan("The fee is $1,200.", [])) == 1


# --------------------------------------------------------------------------
# The detector pair that must disagree
# --------------------------------------------------------------------------


def test_a_citation_is_not_a_verification() -> None:
    """The shape 06 keeps as a deliberate control: a figure carrying a plausible citation
    that the context never states.

    `numeric_claims` is correctly silent — its question is "was this attributed?" —  while
    `rag_grounding` scores the same sentence independently and is expected to flag it.
    Treating a marker as blanket absolution across both planes is the bug this pins.
    """
    text = "Revenue was $9,400 last year [2]."
    assert scan(text, ["Revenue figures are not disclosed in this document."]) == []


# --------------------------------------------------------------------------
# Signal shape, NFR-SEC-001, NFR-P-002
# --------------------------------------------------------------------------


def test_adr_012_detection_kind_at_1_0() -> None:
    signal = scan("The fee is $1,200.")[0]
    assert signal.score == 1.0
    assert signal.score_kind is ScoreKind.DETECTION


def test_label_and_plane_match_the_registry_row() -> None:
    signal = scan("The fee is $1,200.")[0]
    assert signal.labels == ["hallucination.unsourced_numeric"]
    assert signal.planes == [Plane.PERFORMANCE]


def test_nfr_sec_001_evidence_excludes_the_figure() -> None:
    """A salary or balance is personal data, and evidence lands in
    `audit_records.signals_json` (05 §3)."""
    for text, digits in [
        ("Your balance is $84,250 today.", "84250"),
        ("Salary band tops out at $195,000.", "195000"),
    ]:
        signals = scan(text)
        # Guard against a vacuous pass: under the v2 shapes a bare digit run no longer
        # fires, so the original "195000" case ran this loop zero times and asserted
        # nothing. A currency shape keeps the NFR-SEC-001 check live.
        assert signals, f"no signal to inspect for {text!r}"
        for signal in signals:
            assert digits not in signal.evidence
            assert digits[:4] not in signal.evidence
            assert "category:unsourced_numeric" in signal.evidence


def test_evidence_reports_shape_and_digit_length_only() -> None:
    signal = scan("The fee is $1,200.")[0]
    assert signal.evidence == (
        "category:unsourced_numeric shape=currency digits=4 context_docs=0"
    )


def test_signal_carries_no_enriched_labels_key() -> None:
    assert scan("The fee is $1,200.")[0].meta == {}


@pytest.mark.parametrize("stage", [Stage.OUTPUT_SENTENCE, Stage.OUTPUT_FULL])
def test_stage_is_stamped_as_given(stage: Stage) -> None:
    assert scan("The fee is $1,200.", stage=stage)[0].stage is stage


def test_latency_is_stamped_on_every_signal() -> None:
    """AGENTS.md §7: no signal reaches the audit writer claiming an unmeasured 0.0."""
    signals = scan("Fees are $1,200 and growth hit 22%.")
    assert len(signals) == 2
    assert all(s.latency_ms > 0.0 for s in signals)


def test_nfr_p_002_completes_within_its_5ms_budget() -> None:
    """Indicative tripwire, not the measurement of record — that is 06 §4."""
    text = (
        "Thanks for the question. The plan covers standard support and the usual "
        "response windows, with no additional charge for the first three requests. "
    ) * 3
    assert asyncio.run(
        run_with_budget(numeric_claims, DetectorContext(text=text, stage=Stage.OUTPUT_SENTENCE))
    ) == []


def test_budget_is_registered() -> None:
    assert BUDGETS_MS["numeric_claims"] == 5.0
