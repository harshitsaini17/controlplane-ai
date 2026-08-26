"""Discriminating-power proof for the engine conformance matrix (06 §3.3).

The conformance matrix currently agrees with `action_expected` on every case and every
policy. A perfect diagonal is exactly what 06 §3.1 rule 3 warns about, and "trust it, the
two sides are independent" is an assertion, not evidence. So this module **falsifies** the
matrix instead: it injects, one at a time, the specific defects the ADRs exist to prevent,
and requires the matrix to disagree.

A mutation the matrix cannot see is a mutation the matrix would not have caught in the
engine either — the diagonal would then be measuring nothing, and rule 3 would apply after
all. These tests are the reason the 1.000 in the report is publishable, so they are cited
there by name (NFR-INT-001: a claim needs a command).

Mutations patch `policy/engine.py` internals deliberately. Testing through the public
surface could not distinguish "the engine is correct" from "the matrix is blind", which is
the one question here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

import controlplane.policy.engine as eng
from controlplane.detectors.base import ScoreKind
from controlplane.policy.schema import Action, Policy
from eval import policy_matrix as pm

ROOT = Path(__file__).resolve().parents[1]
POLICY_NAMES = ("support_bot", "hr_copilot", "finance_advisor")


def _load_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted((ROOT / "eval" / "dataset").glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if line.strip():
                cases.append(json.loads(line))
    return cases


CASES = _load_cases()
POLICIES = {
    name: Policy(**yaml.safe_load((ROOT / "policies" / f"{name}.yaml").read_text()))
    for name in POLICY_NAMES
}


def mismatch_total() -> int:
    matrices = pm.conformance_matrices(CASES, POLICIES)
    return sum(len(m.mismatches) for m in matrices.values())


# --------------------------------------------------------------------------
# Baseline
# --------------------------------------------------------------------------


def test_baseline_engine_agrees_with_the_frozen_expectations() -> None:
    """The differential result itself: engine vs freeze-pinned `action_expected`.

    `action_expected` is pinned to `validate_dataset.derive_action` for every case x policy
    by the freeze gate, and `engine.evaluate()` is an independent implementation of the same
    04 §4.3 spec. Agreement across all three policies is therefore a real finding — given
    the falsification tests below establish that disagreement was reachable.
    """
    matrices = pm.conformance_matrices(CASES, POLICIES)
    for name, matrix in matrices.items():
        assert matrix.total == len(CASES), name
        assert matrix.mismatches == [], f"{name}: {matrix.mismatches[:5]}"


def test_synthesis_never_consults_a_policy() -> None:
    """The anti-circularity constraint, asserted structurally.

    If `synthesize()` reasoned about actions, the two sides of the matrix would collapse
    into one function of ground truth and the diagonal would be guaranteed. Synthesis may
    read the taxonomy and the band; it may not resolve, order, or map an action.
    """
    source = (ROOT / "eval" / "policy_matrix.py").read_text()
    body = source.split("def synthesize(", 1)[1].split("\ndef ", 1)[0]
    for forbidden in ("action_for", "borderline_action", "default_action", "severity"):
        assert forbidden not in body, f"synthesize() consults {forbidden}"


# --------------------------------------------------------------------------
# Falsification — each mutation must be visible
# --------------------------------------------------------------------------


def test_mutation_adr012_band_scoping_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-012: reading a deterministic 1.0 through the confidence band drops tier-1 PII."""
    monkeypatch.setattr(
        eng, "ScoreKind", type("K", (), {"CONFIDENCE": ScoreKind.DETECTION})
    )
    assert mismatch_total() > 0


def test_mutation_adr019_enriched_follows_host_is_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-019: the rejected reading — enriched labels taking `borderline_action`.

    Asserted to land on `hr_copilot` specifically, because that is the only shipped policy
    where the rejected reading changes an outcome (`privacy.person: block` meeting
    `borderline_action: pass`). A mutation detected on the wrong policy would mean the
    matrix caught something, but not this.
    """
    original = eng._band_outcome
    monkeypatch.setattr(
        eng,
        "_band_outcome",
        lambda *, enriched, mapped, score, policy: original(
            enriched=False, mapped=mapped, score=score, policy=policy
        ),
    )
    matrices = pm.conformance_matrices(CASES, POLICIES)
    assert len(matrices["hr_copilot"].mismatches) > 0
    assert matrices["hr_copilot"].mismatches[0].expected is Action.BLOCK


def test_mutation_adr015_spanless_promotion_is_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-015: claiming every signal has an editable extent removes the promotion.

    Lands on `support_bot`, the only shipped policy that maps a span-less label to `edit`.
    """
    monkeypatch.setattr(eng, "_edit_extent", lambda signal: (True, None, True))
    matrices = pm.conformance_matrices(CASES, POLICIES)
    assert len(matrices["support_bot"].mismatches) > 0


def test_mutation_severity_order_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    """04 §4.2: least-severe convergence — the failure mode that silently under-protects."""
    monkeypatch.setattr(
        eng,
        "most_severe",
        lambda actions: min(actions, key=lambda a: a.severity, default=Action.PASS),
    )
    assert mismatch_total() > 0


def test_mutation_label_action_map_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    """04 §4.3 step 1: ignoring the map collapses every label onto `default_action`."""
    monkeypatch.setattr(Policy, "action_for", lambda self, label: self.default_action)
    assert mismatch_total() > 0


def test_baseline_is_restored_after_mutation() -> None:
    """Guards the suite itself: a leaked patch would make later runs meaningless."""
    assert mismatch_total() == 0


# --------------------------------------------------------------------------
# Synthesis invariants
# --------------------------------------------------------------------------


def test_shared_band_refuses_to_synthesize_across_diverged_taus() -> None:
    """The matrix caption claims ONE signal set across three policies.

    If calibration (06 §3) ever moves the taus apart, that caption becomes false. This
    asserts the harness fails loudly instead of quietly synthesizing per-policy scores.
    """
    raw = yaml.safe_load((ROOT / "policies" / "support_bot.yaml").read_text())
    raw["thresholds"]["tau_low"] = 0.40
    diverged = Policy(**raw)
    with pytest.raises(ValueError, match="no longer share a band"):
        pm.shared_band([diverged, POLICIES["hr_copilot"]])


def test_synthesized_scores_sit_in_the_intended_bands() -> None:
    band = pm.shared_band(POLICIES.values())
    policy = POLICIES["support_bot"]
    assert band.below_tau_low < policy.thresholds.tau_low
    assert policy.thresholds.tau_low <= band.in_band < policy.thresholds.tau_high
    assert band.above_tau_high >= policy.thresholds.tau_high


def test_synthesis_places_enriched_labels_on_a_host_signal() -> None:
    """04 §1.1 / FR-DET-005: `privacy.person` never stands alone as its own signal."""
    band = pm.shared_band(POLICIES.values())
    ovlp = next(c for c in CASES if c["case_id"] == "OVLP-01")
    signals = pm.synthesize(ovlp, band)
    assert len(signals) == 1
    signal = signals[0]
    assert set(signal.labels) == {"hallucination.ungrounded_claim", "privacy.person"}
    assert signal.meta["enriched_labels"] == ["privacy.person"]


def test_synthesis_covers_every_label_in_the_corpus() -> None:
    """A label absent from `_EMITTER` would be silently dropped, deflating the matrix."""
    corpus = {label for case in CASES for label in case["labels_expected"]}
    known = set(pm._EMITTER) | set(pm._ENRICHED)
    assert corpus <= known, f"unsynthesizable labels: {sorted(corpus - known)}"


def test_synthesis_reproduces_every_expected_label() -> None:
    """Whatever the synthesis emits must carry the whole ground truth, or the matrix is
    scoring a verdict against labels that were never presented to the engine."""
    band = pm.shared_band(POLICIES.values())
    for case in CASES:
        emitted = {label for signal in pm.synthesize(case, band) for label in signal.labels}
        assert emitted == set(case["labels_expected"]), case["case_id"]


def test_end_to_end_split_is_exhaustive_and_disjoint() -> None:
    implemented = frozenset(
        {"pii.ssn", "pii.credit_card", "pii.email", "pii.phone", "pii.api_key",
         "security.blocklist", "hallucination.unsourced_numeric"}
    )
    scorable, uncovered, conversation = pm.covered_cases(CASES, implemented)
    assert len(scorable) + uncovered + conversation == len(CASES)
    for case in scorable:
        assert set(case["labels_expected"]) <= implemented
        assert case["kind"] != "conversation"


def test_matrix_is_invariant_to_the_seed_tau_values() -> None:
    """★ The condition that makes these figures publishable at all (06 §3).

    The shipped taus are `# SEED(pre-calibration)` (ADR-016) and 06 §3 rules that **a seed
    value is never judge-facing**. Synthesis reads those taus, so the matrix would inherit
    the prohibition unless its output is independent of them.

    It is, and by construction rather than by luck: synthesis places each score *relative*
    to the band (below / inside / above), so rescaling the band moves the scores with it and
    every band-position — hence every verdict — is unchanged. This test pins that property
    across bands far wider and narrower than the shipped one, so no figure in the matrix
    section derives from a seed value.
    """
    baseline: dict[str, dict[tuple[Action, Action], int]] | None = None
    for tau_low, tau_high in [(0.35, 0.70), (0.20, 0.60), (0.45, 0.80), (0.10, 0.90)]:
        policies = {}
        for name in POLICY_NAMES:
            raw = yaml.safe_load((ROOT / "policies" / f"{name}.yaml").read_text())
            raw["thresholds"]["tau_low"] = tau_low
            raw["thresholds"]["tau_high"] = tau_high
            raw["thresholds"]["tau_route"] = round((tau_low + tau_high) / 2, 4)
            policies[name] = Policy(**raw)
        cells = {
            name: dict(matrix.cells)
            for name, matrix in pm.conformance_matrices(CASES, policies).items()
        }
        if baseline is None:
            baseline = cells
        else:
            assert cells == baseline, f"matrix moved with taus ({tau_low}, {tau_high})"
