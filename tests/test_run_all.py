"""`eval/run_all.py` tests — the harness that produces judge-facing numbers (06 §3).

The harness's own correctness is what makes a reported number trustworthy, so the rules it
enforces are tested as behaviour rather than trusted as intent:

  1. measured or absent — an unimplemented detector is never scored;
  2. an empty denominator is `n/a`, never 1.0;
  3. provenance travels with the output.

Nothing here asserts a specific accuracy figure. A test that pinned `tier1_pii` recall would
have to be edited whenever the detector changed, which is how a suite starts certifying
whatever the code currently does (AGENTS.md §5.4). The measured value belongs in the report;
what belongs here is that the arithmetic producing it is right.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from eval.policy_matrix import (
    conformance_matrices,
    covered_cases,
    end_to_end_matrices,
    reconcile,
)
from eval.run_all import (
    DEMOTED,
    IMPLEMENTED,
    IMPLEMENTED_LABELS,
    SCORED,
    SCORED_V1,
    SKIPPED,
    UNLOADABLE,
    V1_BASELINE,
    _demote_unloadable,
    DetectorResult,
    LabelScore,
    _revision_section,
    build_report,
    collect_emissions,
    detection_failure_case_ids,
    evaluate,
    load_cases,
    main,
)
from eval.validate_dataset import DATASET_DIR, load_policies

#: The 06 §3.3 matrices are identical for every test in this module, and computing them runs
#: three detectors over the corpus. Cached so the suite pays for that once.
_MATRICES: dict[str, object] = {}


def _matrix_args(results, cases):
    if not _MATRICES:
        policies = load_policies()
        scorable, uncovered, conversation = covered_cases(cases, IMPLEMENTED_LABELS)
        _MATRICES.update(
            conformance=conformance_matrices(cases, policies),
            end_to_end=end_to_end_matrices(
                scorable, policies, collect_emissions(scorable)
            ),
            coverage=(len(scorable), uncovered, conversation),
            scorable_ids={case["case_id"] for case in scorable},
        )
    missed, false_positives = detection_failure_case_ids(results)
    ids = _MATRICES["scorable_ids"]
    recon = reconcile(missed & ids, false_positives & ids, _MATRICES["end_to_end"])
    return (
        _MATRICES["conformance"],
        _MATRICES["end_to_end"],
        recon,
        _MATRICES["coverage"],
    )


def _report(results, cases, excluded, note: str = "note") -> str:
    """`build_report` with the 06 §3.3 matrix arguments supplied."""
    return build_report(
        results, cases, excluded, DATASET_DIR, note, *_matrix_args(results, cases)
    )


# --------------------------------------------------------------------------
# Rule 2 — an empty denominator is not a score
# --------------------------------------------------------------------------


def test_recall_is_none_when_a_label_has_no_positive_cases() -> None:
    """`security.blocklist` is exactly this case (Q-15). Reporting 1.0 for a detector that
    was never asked a question would be a fabricated number (AGENTS.md §7)."""
    assert LabelScore("x").recall is None


def test_precision_is_none_when_nothing_was_predicted() -> None:
    assert LabelScore("x", fn=3).precision is None


def test_f1_is_none_when_either_component_is_undefined() -> None:
    assert LabelScore("x").f1 is None
    assert LabelScore("x", fn=3).f1 is None


def test_f1_is_none_rather_than_zero_division_when_both_are_zero() -> None:
    """p = r = 0 is a real state: predictions were made, all wrong."""
    assert LabelScore("x", tp=0, fp=2, fn=2).f1 is None


def test_metrics_are_correct_on_a_known_confusion() -> None:
    score = LabelScore("x", tp=8, fp=2, fn=2)
    assert score.support == 10
    assert score.precision == pytest.approx(0.8)
    assert score.recall == pytest.approx(0.8)
    assert score.f1 == pytest.approx(0.8)


def test_perfect_and_zero_scores_are_representable() -> None:
    assert LabelScore("x", tp=5).recall == 1.0
    assert LabelScore("x", fn=5).recall == 0.0


def test_micro_average_sums_the_confusion_not_the_ratios() -> None:
    """Averaging per-label ratios would weight a 2-case label like a 50-case one."""
    result = DetectorResult(name="d", note="")
    result.labels["a"] = LabelScore("a", tp=1, fp=0, fn=1)   # recall 0.5
    result.labels["b"] = LabelScore("b", tp=48, fp=0, fn=0)  # recall 1.0
    assert result.micro.recall == pytest.approx(49 / 50)


# --------------------------------------------------------------------------
# Rule 1 — measured or absent
# --------------------------------------------------------------------------


def test_no_detector_is_both_implemented_and_skipped() -> None:
    assert not {d.name for d in IMPLEMENTED} & {s.name for s in SKIPPED}


def test_every_skipped_detector_states_a_reason() -> None:
    assert all(s.reason for s in SKIPPED)


def test_skipped_labels_are_disjoint_from_implemented_scopes() -> None:
    """Otherwise a label could be silently claimed by an absent detector."""
    scoped = {label for d in IMPLEMENTED for label in d.scope}
    skipped = {label for s in SKIPPED for label in s.labels}
    assert not scoped & skipped


def test_all_eleven_documented_rows_are_accounted_for() -> None:
    """04 §2 lists 11 detector rows plus `entity_enricher`. Every one is either scored or
    explicitly listed as absent — a row appearing in neither list would vanish from the
    report without anyone noticing it was never measured."""
    from controlplane.detectors.base import BUDGETS_MS

    covered = {d.name for d in IMPLEMENTED} | {s.name for s in SKIPPED}
    assert covered == set(BUDGETS_MS)


def test_scopes_are_inside_the_closed_taxonomy() -> None:
    from controlplane.policy.schema import TAXONOMY

    for dut in IMPLEMENTED:
        assert dut.scope <= TAXONOMY


# --------------------------------------------------------------------------
# Scoping — a detector is only asked its own question
# --------------------------------------------------------------------------


def test_out_of_scope_labels_are_neither_miss_nor_false_positive() -> None:
    """A toxicity case is not a `tier1_pii` miss. Without scoping, every detector's recall
    would be diluted by every label it was never meant to emit."""
    cases = [
        {
            "case_id": "T-001",
            "kind": "output",
            "text": "no pii here at all",
            "labels_expected": ["toxicity.high"],
            "context": None,
        }
    ]
    results, _ = evaluate(cases)
    pii = next(r for r in results if r.name == "tier1_pii")
    assert pii.misses == []
    assert pii.false_positives == []
    assert pii.micro.support == 0


def test_a_detector_is_not_scored_outside_its_documented_stages() -> None:
    """`numeric_claims` is `output_sentence` only (04 §2); an input case is out of stage,
    counted separately rather than silently dropped."""
    cases = [
        {
            "case_id": "I-001",
            "kind": "input",
            "text": "The fee is $1,200.",
            "labels_expected": [],
            "context": None,
        }
    ]
    results, _ = evaluate(cases)
    numeric = next(r for r in results if r.name == "numeric_claims")
    assert numeric.cases_scored == 0
    assert numeric.cases_out_of_stage == 1


def test_conversation_cases_are_excluded_and_counted() -> None:
    """ADR-021 labels a multi-turn case per breach unit while its text holds every turn, so
    scanning the whole text would score false positives against a convention that excluded
    them by design. Which turn breached is not a recorded field, so exclusion — reported with
    its count — is the honest handling."""
    cases = [
        {
            "case_id": "C-001",
            "kind": "conversation",
            "text": "user: my ssn is 000-12-3456\nassistant: noted",
            "labels_expected": ["conversation.cumulative_risk"],
            "context": None,
        }
    ]
    results, excluded = evaluate(cases)
    assert excluded == 1
    assert all(r.cases_scored == 0 for r in results)


# --------------------------------------------------------------------------
# Scoring mechanics
# --------------------------------------------------------------------------


def test_a_detected_expected_label_is_a_true_positive() -> None:
    cases = [
        {
            "case_id": "P-001",
            "kind": "output",
            "text": "SSN 000-12-3456 on file.",
            "labels_expected": ["pii.ssn"],
            "context": None,
        }
    ]
    results, _ = evaluate(cases)
    pii = next(r for r in results if r.name == "tier1_pii")
    assert pii.labels["pii.ssn"].tp == 1
    assert pii.misses == []


def test_an_undetected_expected_label_is_a_miss_and_is_listed() -> None:
    """Aggregates without examples cannot be acted on, so misses are named in the report."""
    cases = [
        {
            "case_id": "P-002",
            "kind": "output",
            "text": "nothing resembling an identifier",
            "labels_expected": ["pii.ssn"],
            "context": None,
        }
    ]
    results, _ = evaluate(cases)
    pii = next(r for r in results if r.name == "tier1_pii")
    assert pii.labels["pii.ssn"].fn == 1
    assert pii.misses == [("P-002", "pii.ssn")]


def test_an_unexpected_detection_is_a_false_positive_and_is_listed() -> None:
    cases = [
        {
            "case_id": "P-003",
            "kind": "output",
            "text": "SSN 000-12-3456 leaked.",
            "labels_expected": [],
            "context": None,
        }
    ]
    results, _ = evaluate(cases)
    pii = next(r for r in results if r.name == "tier1_pii")
    assert pii.false_positives == [("P-003", "pii.ssn")]


def test_context_docs_reach_the_detector() -> None:
    """158 frozen cases carry a `context` list, and `numeric_claims`'s third clause depends
    on it — dropping it would manufacture false positives across the corpus."""
    case = {
        "case_id": "N-001",
        "kind": "output",
        "text": "The fee is $1,200 annually.",
        "labels_expected": [],
        "context": ["The annual fee is 1200 dollars."],
    }
    results, _ = evaluate([case])
    numeric = next(r for r in results if r.name == "numeric_claims")
    assert numeric.false_positives == []

    case_without = dict(case, case_id="N-002", context=None)
    results, _ = evaluate([case_without])
    numeric = next(r for r in results if r.name == "numeric_claims")
    assert numeric.false_positives == [("N-002", "hallucination.unsourced_numeric")]


# --------------------------------------------------------------------------
# The frozen corpus loads, and the report is honest about it
# --------------------------------------------------------------------------


def test_the_frozen_corpus_loads_and_is_counted_not_asserted() -> None:
    cases = load_cases()
    assert cases
    assert all("case_id" in c and "kind" in c for c in cases)


def test_report_computes_both_policy_matrices_and_keeps_them_separate() -> None:
    """06 §3.3. **Supersedes** this module's former `..._is_not_computed` assertion.

    That test required the matrix to be absent, which was correct while
    `policy/engine.py` was a stub: the only available `action_taken` was
    `derive_action`, and tabulating it against `action_expected` would have compared
    ground truth with a function of ground truth (06 §3.1 rule 3). The engine now
    exists, so an independent `action_taken` exists and the artifact is computable.

    The assertions are replaced rather than dropped, and the substantive half of rule 3
    is kept live below: the report must still *justify* that its diagonal is not the
    fabricated one, and must still separate the two matrices — a reader who merged them
    would credit the system with detection it does not have.
    """
    cases = load_cases()
    results, excluded = evaluate(cases)
    report = _report(results, cases, excluded)

    # The artifact exists, and NFR-EVAL-002 is claimed against it.
    assert "NFR-EVAL-002" in report
    assert "## Policy-level confusion matrices" in report

    # Both matrices are present and labelled as different claims (06 §3.3, normative).
    assert "### A. Engine conformance" in report
    assert "### B. End-to-end (partial)" in report
    assert "the distinction is normative" in report
    assert "detection-quality metric" in report

    # Rule 3 is answered, not ignored: the diagonal's independence is argued.
    assert "differential test of two independent implementations" in report

    # End-to-end coverage is stated as a limit rather than implied.
    assert "not scored" in report
    assert "grows as detectors land" in report

    # The flattering reading is pre-empted with its mechanism.
    assert "Reconciliation" in report
    assert "masked" in report

    # Calibration remains genuinely absent — the rule still binds where it applies.
    assert "## Threshold calibration (06 §3) — NOT COMPUTED" in report


def test_report_names_every_unscored_detector_and_its_lost_positives() -> None:
    cases = load_cases()
    results, excluded = evaluate(cases)
    report = _report(results, cases, excluded)
    for skipped in SKIPPED:
        assert f"`{skipped.name}`" in report
    assert "unscored" in report


def test_report_stamps_provenance() -> None:
    cases = load_cases()
    results, excluded = evaluate(cases)
    report = _report(results, cases, excluded)
    assert "Dataset digest" in report
    assert "Python" in report
    assert "Platform" in report
    assert "python -m eval.run_all" in report


def test_report_declares_the_nfr_eval_001_verdict_explicitly() -> None:
    """A missed target must appear as MISSED with a D3 pointer, never be left for the
    reader to infer from a table (06 §1, AGENTS.md §7)."""
    cases = load_cases()
    results, excluded = evaluate(cases)
    report = _report(results, cases, excluded)
    assert "NFR-EVAL-001" in report
    assert ("**MET**" in report) or ("**MISSED**" in report)
    if "**MISSED**" in report:
        assert "D3" in report


def test_report_marks_results_as_synthetic_and_not_a_production_claim() -> None:
    cases = load_cases()
    results, excluded = evaluate(cases)
    report = _report(results, cases, excluded)
    assert "not a production claim" in report


# --------------------------------------------------------------------------
# Gate 1 — the freeze (06 §1)
# --------------------------------------------------------------------------


def test_run_refuses_to_compute_against_an_unfrozen_dataset(tmp_path: Path) -> None:
    """The point of the freeze: a number computed against an edited corpus is not
    comparable to any other number in the repo."""
    ds = tmp_path / "ds"
    ds.mkdir()
    for path in DATASET_DIR.glob("*.jsonl"):
        (ds / path.name).write_bytes(path.read_bytes())
    target = ds / "pii.jsonl"
    target.write_text(target.read_text().replace("PII-001", "PII-001x", 1))

    out = tmp_path / "report.md"
    assert main(["--dataset-dir", str(ds), "--out", str(out)]) == 1
    assert not out.exists()


def test_run_writes_a_report_on_the_frozen_dataset(tmp_path: Path) -> None:
    out = tmp_path / "eval_report.md"
    assert main(["--out", str(out)]) == 0
    text = out.read_text()
    assert "# Evaluation report" in text
    assert "tier1_pii" in text


# --------------------------------------------------------------------------
# Disclosed revision — dual v1/v2 columns (ADR-026 §1, 06 §3.2)
# --------------------------------------------------------------------------
#
# Still nothing here pins an accuracy figure, per this module's opening note. These tests
# assert the *mechanism* that keeps the v1 baseline honest: that it is re-measured rather
# than transcribed, that it is reported beside v2 rather than instead of it, and that the
# NFR target is graded against the detector that actually ships.


def _scored(name: str, variant: str, *, tp: int, fp: int, fn: int) -> DetectorResult:
    result = DetectorResult(name=name, note="", variant=variant)
    score = result.score("pii.ssn")
    score.tp, score.fp, score.fn = tp, fp, fn
    return result


def test_v1_baseline_covers_exactly_the_revised_detectors() -> None:
    """`tier1_blocklist` was never revised, so a v1 column for it would restate the v2 column
    and imply a comparison nobody made."""
    assert {d.name for d in V1_BASELINE} == {"tier1_pii", "numeric_claims"}
    assert all(d.variant == "v1" for d in V1_BASELINE)
    assert all(d.variant == "v2" for d in IMPLEMENTED)


def test_v1_baseline_scores_a_distinct_detector_object() -> None:
    """The frozen modules must be separate implementations, not aliases of the live ones —
    otherwise the 'v1' column would silently report v2 twice."""
    live = {d.name: d.detector for d in IMPLEMENTED}
    for frozen in V1_BASELINE:
        assert frozen.detector is not live[frozen.name]


def test_evaluate_returns_both_variants_and_they_are_distinguishable() -> None:
    cases = load_cases()
    results, _ = evaluate(cases)
    pairs = {(r.name, r.variant) for r in results}
    assert ("tier1_pii", "v1") in pairs
    assert ("tier1_pii", "v2") in pairs
    assert ("numeric_claims", "v1") in pairs
    assert ("numeric_claims", "v2") in pairs


def test_v1_and_v2_are_scored_over_the_same_denominator() -> None:
    """A comparison across different denominators is not a comparison. Support is fixed by
    the corpus and the scope, so it must be identical in both columns."""
    results, _ = evaluate(load_cases())
    for name in ("tier1_pii", "numeric_claims"):
        v1 = next(r for r in results if r.name == name and r.variant == "v1")
        v2 = next(r for r in results if r.name == name and r.variant == "v2")
        assert v1.micro.support == v2.micro.support
        assert v1.cases_scored == v2.cases_scored


def test_revision_section_reports_precision_beside_recall() -> None:
    """06 §3.2: a revision that buys recall with precision must show both halves."""
    section = "\n".join(
        _revision_section(
            [
                _scored("tier1_pii", "v1", tp=5, fp=0, fn=5),
                _scored("tier1_pii", "v2", tp=9, fp=3, fn=1),
            ]
        )
    )
    assert "v1 (blind first contact)" in section
    assert "v2 (post-revision, disclosed)" in section
    assert "precision" in section and "recall" in section
    # recall 0.500 -> 0.900, precision 1.000 -> 0.750: both movements shown, signed.
    assert "+0.400" in section
    assert "-0.250" in section


def test_revision_section_states_the_exclusions_and_their_cost() -> None:
    """An exclusion that quietly removes hard cases is indistinguishable from tuning, so the
    report names them rather than leaving them in the ADR only."""
    section = "\n".join(
        _revision_section(
            [
                _scored("tier1_pii", "v1", tp=1, fp=0, fn=1),
                _scored("tier1_pii", "v2", tp=1, fp=0, fn=1),
            ]
        )
    )
    assert "7-digit" in section
    assert "credential cue" in section
    assert "cost recall" in section
    assert "One re-measurement" in section


def test_revision_section_is_empty_without_a_v1_baseline() -> None:
    assert _revision_section([_scored("tier1_pii", "v2", tp=1, fp=0, fn=0)]) == []


def test_report_grades_nfr_eval_001_against_the_shipping_variant() -> None:
    """The load-bearing selector. Two results now share the name `tier1_pii`, and the target
    applies to the one that ships — so selection must be by variant, never by list position.

    The v1 result is placed FIRST here deliberately: a positional or name-only lookup would
    grade the frozen baseline against NFR-EVAL-001 and report the wrong verdict.
    """
    cases = load_cases()
    results = [
        _scored("tier1_pii", "v1", tp=5, fp=0, fn=5),    # recall 0.50 — would read MISSED
        _scored("tier1_pii", "v2", tp=10, fp=0, fn=0),   # recall 1.00 — the shipping figure
    ]
    report = _report(results, cases, 0)
    assert "**MET**" in report
    assert "**MISSED**" not in report
    assert "1.0000" in report
    # and the baseline is still in the record, not discarded
    assert "0.5000" in report


def test_report_renders_one_table_per_shipping_detector_only() -> None:
    """Two same-named `### `tier1_pii`` tables would leave a reader guessing which ships."""
    cases = load_cases()
    results, excluded = evaluate(cases)
    report = _report(results, cases, excluded)
    assert report.count("### `tier1_pii`") == 1
    assert report.count("### `numeric_claims`") == 1


def test_report_says_the_v1_column_is_computed_not_transcribed() -> None:
    """ADR-026 §1's permanence claim only holds if the number is reproducible (AGENTS.md §7).
    A reader has to be able to tell a re-measurement from a quotation."""
    cases = load_cases()
    results, excluded = evaluate(cases)
    report = _report(results, cases, excluded)
    assert "computed, not transcribed" in report
    assert "_v1_" in report


def test_frozen_v1_modules_are_byte_identical_to_their_source_commit() -> None:
    """The mechanical guard on ADR-026 §1: `_v1_*.py` must never drift.

    They exist so the permanent v1 figures stay re-derivable. An edit — even a well-meant
    lint fix — would silently change what "v1" means in every future report, so the property
    is asserted rather than trusted to the DO-NOT-EDIT banner.
    """
    source = "4b056e869ce4892bbd848d259336f166dfcd5795"
    root = Path(__file__).resolve().parents[1]
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{source}^{{commit}}"],
            cwd=root, check=True, capture_output=True, timeout=10,
        )
    except Exception:  # pragma: no cover - shallow clone or no git
        pytest.skip(f"commit {source[:7]} not available in this checkout")

    for original, frozen in (
        ("numeric_claims", "_v1_numeric_claims"),
        ("tier1_patterns", "_v1_tier1_patterns"),
    ):
        was = subprocess.run(
            ["git", "show", f"{source}:controlplane/detectors/{original}.py"],
            cwd=root, check=True, capture_output=True, text=True, timeout=10,
        ).stdout
        now = (root / "controlplane" / "detectors" / f"{frozen}.py").read_text()
        assert "DO NOT EDIT" in now
        assert now.endswith(was), (
            f"{frozen}.py no longer contains {original}.py from {source[:7]} verbatim — "
            "the v1 baseline has drifted and every v1 figure is now unreproducible"
        )


# ---------------------------------------------------------------------------
# ADR-033 state (c) — implemented but unloadable, reported not scored
# ---------------------------------------------------------------------------


def test_the_partition_loses_no_detector_and_duplicates_none() -> None:
    """`SCORED` ⊎ `DEMOTED` must reconstruct `IMPLEMENTED` exactly.

    Rule 1 is "measured or absent", and a detector that fell out of both lists would be
    neither: silently dropped from the report while every stated total still balanced.
    """
    assert [d.name for d in SCORED] + [d.name for d in DEMOTED] == [
        d.name for d in IMPLEMENTED
    ]
    assert not {d.name for d in SCORED} & {d.name for d in DEMOTED}


def test_this_host_scores_everything_it_implements() -> None:
    """Documents the local truth and guards the inert case.

    The three shipped detectors are regex passes that import nothing, so a non-empty
    `DEMOTED` here would mean the probe is inventing absences and suppressing real
    measurements — a silent loss of coverage in the eval report.
    """
    assert UNLOADABLE == {}
    assert DEMOTED == ()
    assert [d.name for d in SCORED_V1] == [d.name for d in V1_BASELINE]


def test_an_unloadable_detector_is_demoted_out_of_scoring(monkeypatch) -> None:
    """★ The branch, exercised in the only direction a healthy host can exercise it.

    `UNLOADABLE` is patched — the probe's *result*, not the import system. That is the
    opposite direction from what ADR-033 rule 4 forbids: rule 4 bars faking a load to make
    an absent detector look present, which would launder a coverage claim. Declaring a
    present detector absent cannot launder anything, and the probe itself is tested against
    a genuinely missing module in `tests/test_detector_availability.py`.
    """
    monkeypatch.setattr("eval.run_all.UNLOADABLE", {"tier1_pii": "some_dependency"})
    scored, baselines, rows = _demote_unloadable()

    assert "tier1_pii" not in {d.name for d in scored}
    assert "tier1_pii" not in {d.name for d in baselines}, "the v1 baseline goes too"
    assert [r.name for r in rows] == ["tier1_pii"]


def test_the_demotion_reason_names_the_dependency_and_not_a_missing_implementation(
    monkeypatch,
) -> None:
    """The two states must not collapse into one sentence in the report.

    "not implemented" would be false — the detector exists and was scored on the last host
    — and a reader comparing two reports would conclude the code regressed rather than that
    the environment differs.
    """
    monkeypatch.setattr("eval.run_all.UNLOADABLE", {"numeric_claims": "sentence_transformers"})
    _, _, rows = _demote_unloadable()

    assert "sentence_transformers" in rows[0].reason
    assert "unloadable" in rows[0].reason.lower()
    assert "not implemented" not in rows[0].reason.lower()


def test_the_demotion_reason_is_built_from_the_probe_not_typed(monkeypatch) -> None:
    """"Consumes the same state" (Ruling 2 semantics 3), pinned.

    A hand-written dependency name beside `REQUIREMENTS` is two declarations that can
    disagree, and the prose one is the one nobody updates.
    """
    monkeypatch.setattr("eval.run_all.UNLOADABLE", {"tier1_blocklist": "a_renamed_package"})
    _, _, rows = _demote_unloadable()
    assert "a_renamed_package" in rows[0].reason


def test_demoted_labels_are_not_claimed_as_covered() -> None:
    """`IMPLEMENTED_LABELS` gates the end-to-end matrix's covered slice.

    Derived from `SCORED`, so a host missing a dependency cannot report a matrix over labels
    no detector could emit that run — which would score every one of them as a miss.
    """
    assert IMPLEMENTED_LABELS == frozenset(
        label for dut in SCORED for label in dut.scope
    )
    assert not {label for dut in DEMOTED for label in dut.scope} & IMPLEMENTED_LABELS
