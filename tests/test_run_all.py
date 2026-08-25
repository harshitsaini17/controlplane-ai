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
from pathlib import Path

import pytest

from eval.run_all import (
    IMPLEMENTED,
    SKIPPED,
    DetectorResult,
    LabelScore,
    build_report,
    evaluate,
    load_cases,
    main,
)
from eval.validate_dataset import DATASET_DIR


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


def test_report_states_the_policy_matrix_is_not_computed() -> None:
    """06 §3's headline artifact must be reported absent, not approximated.

    Deriving it from `labels_expected` would compare ground truth against a function of
    ground truth and yield a meaningless perfect diagonal — a fabricated result.
    """
    cases = load_cases()
    results, excluded = evaluate(cases)
    report = build_report(results, cases, excluded, DATASET_DIR, "note")
    assert "NOT COMPUTED" in report
    assert "circular" in report
    assert "NFR-EVAL-002" in report


def test_report_names_every_unscored_detector_and_its_lost_positives() -> None:
    cases = load_cases()
    results, excluded = evaluate(cases)
    report = build_report(results, cases, excluded, DATASET_DIR, "note")
    for skipped in SKIPPED:
        assert f"`{skipped.name}`" in report
    assert "unscored" in report


def test_report_stamps_provenance() -> None:
    cases = load_cases()
    results, excluded = evaluate(cases)
    report = build_report(results, cases, excluded, DATASET_DIR, "note")
    assert "Dataset digest" in report
    assert "Python" in report
    assert "Platform" in report
    assert "python -m eval.run_all" in report


def test_report_declares_the_nfr_eval_001_verdict_explicitly() -> None:
    """A missed target must appear as MISSED with a D3 pointer, never be left for the
    reader to infer from a table (06 §1, AGENTS.md §7)."""
    cases = load_cases()
    results, excluded = evaluate(cases)
    report = build_report(results, cases, excluded, DATASET_DIR, "note")
    assert "NFR-EVAL-001" in report
    assert ("**MET**" in report) or ("**MISSED**" in report)
    if "**MISSED**" in report:
        assert "D3" in report


def test_report_marks_results_as_synthetic_and_not_a_production_claim() -> None:
    cases = load_cases()
    results, excluded = evaluate(cases)
    report = build_report(results, cases, excluded, DATASET_DIR, "note")
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
