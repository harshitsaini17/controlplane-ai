"""Policy engine + action tests — 04 §4 state machine, §5 failure semantics, §6 EDIT.

Test-authoring rule followed here, same as the ADR-026 detector tests: expectations are
derived from the DOCS (04 §4.3 steps, ADR-012/015/017/019/020/024) and from the shipped
policy YAML, never from the engine's own output. A test that recorded what the
implementation happened to do would only prove it agrees with itself.

`asyncio.run` rather than a pytest-asyncio plugin, matching `tests/test_detector_base.py`
— no new dependency for four coroutines.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest
import yaml

from controlplane.detectors.base import (
    ENRICHED_LABELS_KEY,
    Plane,
    ScoreKind,
    Signal,
    Span,
    Stage,
)
from controlplane.policy import actions as act
from controlplane.policy.engine import (
    DETECTOR_FAIL_CLASS,
    DetectorFailureRecord,
    evaluate,
    fail_class_for,
    most_severe,
    resolve_failure,
)
from controlplane.policy.schema import Action, FailMode, Policy

POLICY_DIR = Path(__file__).resolve().parents[1] / "policies"
POLICY_FILES = ("support_bot.yaml", "hr_copilot.yaml", "finance_advisor.yaml")


def load_policy(name: str) -> Policy:
    return Policy(**yaml.safe_load((POLICY_DIR / name).read_text()))


ALL_POLICIES = {name: load_policy(name) for name in POLICY_FILES}


# --------------------------------------------------------------------------
# Signal builders — every field explicit, so a test never depends on a default
# --------------------------------------------------------------------------


def pii_signal(label: str = "pii.email", *, start: int = 10, end: int = 24,
               stage: Stage = Stage.OUTPUT_SENTENCE) -> Signal:
    """A deterministic tier-1 emission: detection kind at 1.0 (ADR-012)."""
    return Signal(
        detector="tier1_pii",
        planes=[Plane.RESPONSIBILITY],
        labels=[label],
        score=1.0,
        score_kind=ScoreKind.DETECTION,
        span=Span(start=start, end=end),
        stage=stage,
        evidence=f"category:{label.split('.', 1)[1]} pattern",
        latency_ms=0.4,
    )


def ovlp_signal(score: float, *, stage: Stage = Stage.OUTPUT_SENTENCE,
                span: Span | None = None) -> Signal:
    """The FR-DET-005 overlap signal: ONE signal, host + enriched label (04 §1.1).

    `privacy.person` must appear in `meta.enriched_labels` or `Signal` refuses to be
    constructed — the bidirectional ADR-019 guard.
    """
    return Signal(
        detector="rag_grounding",
        planes=[Plane.PERFORMANCE, Plane.RESPONSIBILITY],
        labels=["hallucination.ungrounded_claim", "privacy.person"],
        score=score,
        score_kind=ScoreKind.CONFIDENCE,
        span=span,
        stage=stage,
        evidence="grounding cosine below threshold; entity appended",
        latency_ms=12.0,
        meta={ENRICHED_LABELS_KEY: ["privacy.person"]},
    )


def consistency_signal(score: float) -> Signal:
    """`fast_consistency`: `output_full`, span-less BY DESIGN (ADR-015)."""
    return Signal(
        detector="fast_consistency",
        planes=[Plane.PERFORMANCE],
        labels=["hallucination.low_confidence"],
        score=score,
        score_kind=ScoreKind.CONFIDENCE,
        span=None,
        stage=Stage.OUTPUT_FULL,
        evidence="self-consistency cosine across 2 samples",
        latency_ms=38.2,
        meta={"method": "self_consistency"},
    )


# ==========================================================================
# 04 §4.3 step 1 — per-label action resolution
# ==========================================================================


def test_step1_resolution_precedence_specific_beats_wildcard() -> None:
    """ADR-024: `pii.*: edit` with `pii.api_key: block` on support_bot.

    The specific key must win, which is the whole mechanism ADR-024 relies on — a typed
    credential is already compromised, and redact-and-continue would leave the leaked key
    valid while hiding the incident from the one person who can rotate it.
    """
    policy = ALL_POLICIES["support_bot.yaml"]
    assert evaluate([pii_signal("pii.email")], policy).action is Action.EDIT
    assert evaluate([pii_signal("pii.api_key")], policy).action is Action.BLOCK


def test_step1_unlisted_label_falls_to_default_action() -> None:
    """A label no key mentions resolves to `default_action` (04 §3/§4.3 step 1)."""
    policy = ALL_POLICIES["support_bot.yaml"]
    # `pii.person_data` is in the taxonomy and matched only by the `pii.*` wildcard.
    assert policy.action_for("pii.person_data") is Action.EDIT
    # `toxicity.moderate` is explicitly `pass` on this policy, not defaulted.
    assert policy.action_for("toxicity.moderate") is Action.PASS


# ==========================================================================
# 04 §4.3 step 2 — band adjustment (ADR-012 scoping, ADR-017, ADR-019)
# ==========================================================================


def test_step2_detection_kind_bypasses_the_band_entirely() -> None:
    """ADR-012: the band applies ONLY to `score_kind=confidence`.

    A deterministic emitter reports 1.0 as "certainly present". Reading 1.0 through a band
    calibrated for a *confidence that content is correct* would invert the polarity — and
    since 1.0 >= tau_high on every shipped policy, it would DROP every tier-1 PII signal.
    That is the failure this test exists to prevent, so it asserts the consequence and not
    merely the rule.
    """
    for name, policy in ALL_POLICIES.items():
        assert 1.0 >= policy.thresholds.tau_high, name  # the trap is live
        verdict = evaluate([pii_signal("pii.ssn")], policy)
        assert verdict.action is not Action.PASS, f"{name}: tier-1 PII was dropped by the band"
        outcome = verdict.signal_outcomes[0]
        assert outcome.labels[0].rule == "adr012.detection.band_bypassed"


@pytest.mark.parametrize(
    ("name", "expected_host"),
    [("support_bot.yaml", Action.EDIT), ("hr_copilot.yaml", Action.PASS),
     ("finance_advisor.yaml", Action.ESCALATE)],
)
def test_step2_in_band_host_label_uses_borderline_action(name: str, expected_host: Action) -> None:
    """ADR-017: an in-band host label takes the policy's `borderline_action`.

    Expected values come from the ADR's ruled table, which matches each use case's
    documented 01 §3 posture — not from reading the code back.
    """
    policy = ALL_POLICIES[name]
    signal = ovlp_signal(0.41)  # 0.35 <= 0.41 < 0.70 on all three
    verdict = evaluate([signal], policy)
    host = next(o for o in verdict.signal_outcomes[0].labels if not o.enriched)
    assert host.action is expected_host
    assert host.rule == "adr017.host.borderline_action"
    assert host.action is policy.borderline_action


def test_step2_below_tau_low_uses_the_mapped_action_not_the_band() -> None:
    """`score < tau_low` -> mapped action as-is (04 §4.3 step 2)."""
    policy = ALL_POLICIES["support_bot.yaml"]
    verdict = evaluate([ovlp_signal(0.10)], policy)
    host = next(o for o in verdict.signal_outcomes[0].labels if not o.enriched)
    assert host.action is policy.action_for("hallucination.ungrounded_claim")
    assert host.rule == "band.host.below_tau_low_mapped"


def test_step2_above_tau_high_drops_every_label_and_the_signal() -> None:
    """`score >= tau_high` -> host dropped, and ADR-019 takes the enriched label with it.

    "A signal whose every label was dropped does not survive" — so a well-grounded
    sentence that merely names someone yields PASS, on every policy. Rejecting ADR-019
    option (b) is exactly what makes this true.
    """
    for name, policy in ALL_POLICIES.items():
        verdict = evaluate([ovlp_signal(0.85)], policy)
        assert verdict.action is Action.PASS, name
        outcome = verdict.signal_outcomes[0]
        assert outcome.action is None
        assert [o.action for o in outcome.labels] == [None, None]
        assert outcome.surviving_labels == ()


def test_step2_enriched_label_never_takes_the_borderline_action() -> None:
    """★ ADR-019, the cell where the three candidate readings disagree.

    On `hr_copilot`, `privacy.person: block` meets `borderline_action: pass`. A
    follows-host rule would PASS a borderline fabrication about a named employee on the
    one use case whose strictness is spent precisely on personal data — and it would let a
    06 §3 calibration run silently break demo beat 4b by moving tau.
    """
    policy = ALL_POLICIES["hr_copilot.yaml"]
    assert policy.borderline_action is Action.PASS  # the trap is live
    verdict = evaluate([ovlp_signal(0.41)], policy)
    enriched = next(o for o in verdict.signal_outcomes[0].labels if o.enriched)
    assert enriched.action is Action.BLOCK
    assert enriched.action is policy.action_for("privacy.person")
    assert enriched.rule == "adr019.enriched.mapped_unadjusted"
    assert enriched.action is not policy.borderline_action


def test_step2_enriched_partition_is_driven_by_meta_not_by_label_name() -> None:
    """ADR-019 made `meta.enriched_labels` load-bearing; this asserts the engine reads it.

    Same label, same score — but presented as a HOST label, it must go through the band
    and pick up `borderline_action`. If the engine special-cased the string
    `privacy.person` instead of consulting `meta`, both cases would agree and the
    partition would be decorative.

    `model_construct` bypasses the `Signal` guard deliberately: the guard's whole purpose
    is to make this shape unconstructible in production, and the point here is that the
    engine's partition follows `meta` rather than the label name.
    """
    policy = ALL_POLICIES["hr_copilot.yaml"]
    host_shaped = Signal.model_construct(
        signal_id="fixed-id-1",
        detector="rag_grounding",
        planes=[Plane.RESPONSIBILITY],
        labels=["privacy.person"],
        score=0.41,
        score_kind=ScoreKind.CONFIDENCE,
        span=None,
        stage=Stage.OUTPUT_SENTENCE,
        evidence="hypothetical host-shaped emission",
        latency_ms=1.0,
        meta={},  # NOT recorded as enriched
    )
    outcome = evaluate([host_shaped], policy).signal_outcomes[0]
    assert outcome.labels[0].enriched is False
    assert outcome.labels[0].action is policy.borderline_action  # PASS, via the band
    assert outcome.labels[0].rule == "adr017.host.borderline_action"

    enriched = evaluate([ovlp_signal(0.41)], policy).signal_outcomes[0]
    person = next(o for o in enriched.labels if o.label == "privacy.person")
    assert person.enriched is True
    assert person.action is Action.BLOCK  # mapped, unadjusted — the opposite outcome


# ==========================================================================
# 04 §4.3 step 3 — convergence, and §4.2 severity
# ==========================================================================


def test_step3_severity_order_is_block_escalate_edit_pass() -> None:
    """04 §4.2 total order, asserted as a property of every pair."""
    order = [Action.PASS, Action.EDIT, Action.ESCALATE, Action.BLOCK]
    for lower_index, lower in enumerate(order):
        for higher in order[lower_index + 1:]:
            assert higher.severity > lower.severity
            assert most_severe([lower, higher]) is higher


def test_step3_no_surviving_signal_yields_pass() -> None:
    assert evaluate([], ALL_POLICIES["finance_advisor.yaml"]).action is Action.PASS


def test_step3_multi_label_signal_takes_its_most_severe_surviving_label() -> None:
    """FR-DET-005 convergence: ONE signal, two planes, most-severe wins — not
    double-processing, which AGENTS.md §9.3 warns against."""
    policy = ALL_POLICIES["hr_copilot.yaml"]
    outcome = evaluate([ovlp_signal(0.41)], policy).signal_outcomes[0]
    assert {o.label: o.action for o in outcome.labels} == {
        "hallucination.ungrounded_claim": Action.PASS,   # band -> borderline_action
        "privacy.person": Action.BLOCK,                   # mapped, unadjusted
    }
    assert outcome.action is Action.BLOCK


def test_step3_verdict_is_most_severe_across_signals() -> None:
    policy = ALL_POLICIES["support_bot.yaml"]
    verdict = evaluate(
        [pii_signal("pii.email"), pii_signal("pii.api_key", start=40, end=70)], policy
    )
    assert verdict.action is Action.BLOCK  # BLOCK beats the EDIT-mapped email


def test_contributing_signal_ids_name_only_the_deciding_signals() -> None:
    """05 §4 records contributing signals; a PASS-mapped bystander did not decide."""
    policy = ALL_POLICIES["support_bot.yaml"]
    deciding = pii_signal("pii.api_key")               # -> BLOCK
    bystander = pii_signal("pii.email", start=50, end=64)  # -> EDIT
    verdict = evaluate([deciding, bystander], policy)
    assert verdict.action is Action.BLOCK
    assert verdict.contributing_signal_ids == (deciding.signal_id,)


# ==========================================================================
# 04 §4.3 step 4 — span-less promotion (ADR-015)
# ==========================================================================


def test_step4_spanless_edit_mapped_signal_is_promoted_to_escalate() -> None:
    """ADR-015: no editable extent -> ESCALATE, a safe upgrade rather than a silent pass.

    Built with a policy mutated ONLY at the one key under test, so the promotion is
    observable: all three shipped policies map `hallucination.low_confidence` to escalate
    or pass, which would make the promotion indistinguishable from the mapped action.
    """
    raw = yaml.safe_load((POLICY_DIR / "support_bot.yaml").read_text())
    raw["actions"]["hallucination.low_confidence"] = "edit"
    policy = Policy(**raw)
    assert policy.action_for("hallucination.low_confidence") is Action.EDIT

    verdict = evaluate([consistency_signal(0.10)], policy)  # below tau_low -> mapped EDIT
    assert verdict.action is Action.ESCALATE
    assert verdict.signal_outcomes[0].promoted_spanless is True
    assert verdict.edits == ()  # nothing to transform, so no plan may be emitted


def test_step4_spanless_output_sentence_signal_keeps_edit_via_whole_sentence_scope() -> None:
    """04 §6: `stage=output_sentence` gives soften a whole-sentence extent, so an
    otherwise span-less signal is still editable — the other half of ADR-015."""
    policy = ALL_POLICIES["support_bot.yaml"]
    verdict = evaluate([ovlp_signal(0.41, stage=Stage.OUTPUT_SENTENCE, span=None)], policy)
    assert verdict.action is Action.EDIT
    assert verdict.signal_outcomes[0].promoted_spanless is False
    assert len(verdict.edits) == 1
    assert verdict.edits[0].whole_sentence is True


def test_edit_plans_are_dropped_when_the_verdict_is_not_edit() -> None:
    """A stale plan on a BLOCK would invite a caller to emit text the verdict withheld."""
    policy = ALL_POLICIES["support_bot.yaml"]
    verdict = evaluate(
        [ovlp_signal(0.41), pii_signal("pii.api_key", start=80, end=110)], policy
    )
    assert verdict.action is Action.BLOCK
    assert verdict.edits == ()


# ==========================================================================
# FR-POL-001 — determinism
# ==========================================================================


def test_verdict_is_deterministic_including_its_explanation() -> None:
    """Identical inputs + policy version -> identical verdict AND identical derivation."""
    policy = ALL_POLICIES["finance_advisor.yaml"]
    signals = [ovlp_signal(0.41), pii_signal("pii.ssn")]
    first = evaluate(signals, policy)
    for _ in range(25):
        assert evaluate(signals, policy) == first


def test_evaluate_does_not_mutate_its_inputs() -> None:
    """Purity is what makes the audit record reproducible from stored signals."""
    policy = ALL_POLICIES["support_bot.yaml"]
    signal = ovlp_signal(0.41)
    before = signal.model_dump()
    evaluate([signal], policy)
    assert signal.model_dump() == before


def test_verdict_stamps_use_case_and_policy_version() -> None:
    """04 §4.3 step 5 / 05 §4: the record must name the policy that decided."""
    for name, policy in ALL_POLICIES.items():
        verdict = evaluate([pii_signal()], policy)
        assert verdict.use_case == policy.use_case
        assert verdict.policy_version == policy.policy_version


def _docstring_constants(tree: ast.AST) -> set[int]:
    """Ids of the `Constant` nodes that are docstrings — module, class and function."""
    exempt: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                exempt.add(id(body[0].value))
    return exempt


def test_no_use_case_name_reaches_executable_code() -> None:
    """FR-POL-002 / AGENTS.md §9.1, asserted structurally rather than by inspection.

    This guards the product thesis: behaviour changes with YAML alone. A single
    `if use_case == "support_bot"` would make that claim false while every other test in
    this file still passed, so the check has to be structural.

    Scoped by AST rather than by grep, for two reasons. It is *stricter* — a name reaching
    an identifier, an attribute, or an f-string fragment is caught regardless of line
    formatting, which a line-oriented grep can be split across. And it is *correctly*
    scoped: docstrings and comments are exempt because neither can branch, and the ADRs
    this engine implements are unquotable without naming the use case they were ruled for
    (ADR-019's rationale is precisely about `hr_copilot`). Excluding prose is not a
    loophole here — prose that named a use case while the code did not is exactly the
    situation FR-POL-002 wants.
    """
    use_cases = ("support_bot", "hr_copilot", "finance_advisor")
    for module in ("engine.py", "actions.py"):
        path = Path(__file__).resolve().parents[1] / "controlplane" / "policy" / module
        tree = ast.parse(path.read_text())
        exempt = _docstring_constants(tree)
        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                haystack = "" if id(node) in exempt else node.value
            elif isinstance(node, ast.Name):
                haystack = node.id
            elif isinstance(node, ast.Attribute):
                haystack = node.attr
            elif isinstance(node, ast.arg):
                haystack = node.arg
            else:
                continue
            for name in use_cases:
                if name in haystack:
                    offenders.append(f"{module}:{getattr(node, 'lineno', '?')} -> {name}")
        assert not offenders, f"use-case name in executable code: {offenders}"


# ==========================================================================
# 04 §5 — failure semantics (FR-POL-006)
# ==========================================================================


def test_fail_class_covers_every_registry_detector_except_the_enricher() -> None:
    """04 §2 registry vs the 04 §3 `fail_mode` classes.

    `entity_enricher` is excluded BY DESIGN (04 §2.2: enrichment failure skips and logs,
    never blocks), so its absence is asserted as intent — and looking it up raises rather
    than inventing a mode.
    """
    from controlplane.detectors.base import BUDGETS_MS

    assert set(DETECTOR_FAIL_CLASS) == set(BUDGETS_MS) - {"entity_enricher"}
    assert set(DETECTOR_FAIL_CLASS.values()) == {"tier1", "tier2", "performance", "cost"}
    with pytest.raises(ValueError, match="entity_enricher"):
        fail_class_for("entity_enricher")


def test_fail_closed_maps_a_detector_fault_to_escalate() -> None:
    """04 §5: fail_closed -> ESCALATE. All three policies are fail_closed on tier1."""
    for name, policy in ALL_POLICIES.items():
        assert policy.fail_mode.tier1 is FailMode.FAIL_CLOSED, name
        record = DetectorFailureRecord(detector="tier1_pii", error_class="DetectorTimeout")
        outcome = resolve_failure(record, policy)
        assert outcome.action is Action.ESCALATE
        assert outcome.fail_class == "tier1"
        assert evaluate([], policy, failures=[record]).action is Action.ESCALATE


def test_fail_open_contributes_no_verdict_but_is_still_recorded() -> None:
    """04 §5: fail_open proceeds without that detector's signals — and is NOT silent.

    A dropped detector that left no trace is indistinguishable from a detector that ran
    and found nothing, which is exactly the ambiguity `cp_detector_failures_total` exists
    to remove (05 §5).
    """
    policy = ALL_POLICIES["support_bot.yaml"]
    assert policy.fail_mode.tier2 is FailMode.FAIL_OPEN
    record = DetectorFailureRecord(detector="tier2_toxicity", error_class="DetectorError")
    verdict = evaluate([], policy, failures=[record])
    assert verdict.action is Action.PASS
    assert len(verdict.failure_outcomes) == 1
    assert verdict.failure_outcomes[0].action is None
    assert verdict.failure_outcomes[0].fail_mode is FailMode.FAIL_OPEN
    assert verdict.failure_outcomes[0].error_class == "DetectorError"


def test_a_detector_fault_never_produces_a_silent_block() -> None:
    """04 §5 is explicit: "never silent BLOCK — a human sees why".

    Swept across every policy and every detector, because the guarantee is universal: a
    BLOCK here would present a detector outage to the caller as a policy violation.
    """
    for policy in ALL_POLICIES.values():
        for detector in DETECTOR_FAIL_CLASS:
            for error_class in ("DetectorTimeout", "DetectorError"):
                record = DetectorFailureRecord(detector=detector, error_class=error_class)
                assert resolve_failure(record, policy).action is not Action.BLOCK
                assert evaluate([], policy, failures=[record]).action is not Action.BLOCK


def test_uc1_fails_open_where_uc3_fails_closed_side_by_side() -> None:
    """SC-3 (01 §3) at the engine level: the same fault, two documented behaviours.

    Full fault injection needs the gateway (06 §5); this is the policy-resolution half,
    which is the part that is testable today.
    """
    record = DetectorFailureRecord(detector="tier2_toxicity", error_class="DetectorTimeout")
    assert resolve_failure(record, ALL_POLICIES["support_bot.yaml"]).action is None
    assert (
        resolve_failure(record, ALL_POLICIES["finance_advisor.yaml"]).action is Action.ESCALATE
    )


def test_failures_converge_with_signals_under_the_same_severity_rule() -> None:
    """A fail_closed ESCALATE must not mask a BLOCK from a real signal."""
    policy = ALL_POLICIES["finance_advisor.yaml"]
    record = DetectorFailureRecord(detector="tier1_pii", error_class="DetectorTimeout")
    blocking = Signal(
        detector="tier2_injection",
        planes=[Plane.RESPONSIBILITY],
        labels=["security.prompt_injection"],
        score=0.97,
        score_kind=ScoreKind.DETECTION,
        span=None,
        stage=Stage.INPUT,
        evidence="injection classifier probability",
        latency_ms=18.0,
    )
    assert policy.action_for("security.prompt_injection") is Action.BLOCK
    assert evaluate([blocking], policy, failures=[record]).action is Action.BLOCK


# ==========================================================================
# ★ Beat 4 — FULL VERDICTS through all three policies (07 beat 4, build item 4)
# ==========================================================================

BEAT_4_SCORE = 0.41  # the 05 §4 reference score, inside the band on all three policies


def test_beat_4_full_verdicts_edit_block_escalate() -> None:
    """★ THE SIGNATURE MOMENT — one identical signal, three verdicts, config alone.

    This is the full-verdict form: previous tests asserted mapped actions and post-band
    per-label actions, but the product claim is about the VERDICT a caller receives. The
    signal is byte-identical across the three evaluations — same labels, same score, same
    stage, same meta — so nothing but the YAML can explain the difference.
    """
    signal = ovlp_signal(BEAT_4_SCORE)
    verdicts = {name: evaluate([signal], policy).action for name, policy in ALL_POLICIES.items()}
    assert verdicts == {
        "support_bot.yaml": Action.EDIT,          # 4a — soften, borderline_action: edit
        "hr_copilot.yaml": Action.BLOCK,          # 4b — privacy.person, unadjusted
        "finance_advisor.yaml": Action.ESCALATE,  # 4c — quarantine + review
    }
    assert len(set(verdicts.values())) == 3  # the thesis: three DISTINCT verdicts


def test_beat_4_grounded_person_case_passes_everywhere() -> None:
    """The control for beat 4: well-grounded text that merely names someone.

    Without this, "BLOCK on UC-2" could be a detector that fires on any named person.
    ADR-019's `>= tau_high` branch is what makes PASS the answer on all three.
    """
    signal = ovlp_signal(0.85)
    for name, policy in ALL_POLICIES.items():
        assert evaluate([signal], policy).action is Action.PASS, name


def test_beat_4_api_key_blocks_on_support_bot_adr_024() -> None:
    """ADR-024: `pii.api_key` -> BLOCK even on the redact-first use case.

    Asserted next to `pii.email` -> EDIT on the same policy, because the point is the
    DIVERGENCE: a typed credential is already compromised, so redact-and-continue would
    hide the incident from the only person who can rotate the key.
    """
    policy = ALL_POLICIES["support_bot.yaml"]
    assert evaluate([pii_signal("pii.api_key")], policy).action is Action.BLOCK
    assert evaluate([pii_signal("pii.email")], policy).action is Action.EDIT


def test_beat_4a_edit_is_executable_as_both_transforms() -> None:
    """07 beat 4a renders "softened claim + redacted detail" — so both must be planned.

    The demo fixture carries the OVLP signal PLUS a `pii.email` span (07 §fixture note),
    and this asserts the engine emits a plan for each rather than one standing in for both.
    """
    policy = ALL_POLICIES["support_bot.yaml"]
    verdict = evaluate([ovlp_signal(BEAT_4_SCORE), pii_signal("pii.email")], policy)
    assert verdict.action is Action.EDIT
    planned = {label for plan in verdict.edits for label in plan.labels}
    assert planned == {"hallucination.ungrounded_claim", "pii.email"}


# ==========================================================================
# 04 §6 — EDIT transforms
# ==========================================================================


def test_redact_replaces_every_span_and_leaves_no_original_text() -> None:
    """FR-POL-003 acceptance: "redacted output contains no span of the original match"."""
    email, phone = "casey@example.org", "415-555-0123"
    text = f"Reach me at {email} or {phone} today."
    spans = [
        (text.index(email), text.index(email) + len(email), "email"),
        (text.index(phone), text.index(phone) + len(phone), "phone"),
    ]
    out = act.redact_spans(text, spans)
    assert email not in out
    assert phone not in out
    assert out == "Reach me at [REDACTED:email] or [REDACTED:phone] today."


def test_redact_is_multi_span_safe_because_it_applies_right_to_left() -> None:
    """04 §6 specifies right-to-left, and this is why: left-to-right would shift offsets.

    Asserted by giving the spans in ASCENDING order — the order a naive implementation
    would iterate — and requiring both to land exactly.
    """
    text = "aaaa BBBB cccc DDDD eeee"
    out = act.redact_spans(text, [(5, 9, "ssn"), (15, 19, "phone")])
    assert out == "aaaa [REDACTED:ssn] cccc [REDACTED:phone] eeee"


def test_redact_marker_uses_the_bare_category_per_04_6_and_07_beat_4() -> None:
    """`[REDACTED:email]`, not `[REDACTED:pii.email]` (04 §6 template, 07 beat 4)."""
    out = act.redact_spans("x a@b.com y", [(2, 9, act.category_of("pii.email"))])
    assert "[REDACTED:email]" in out


def test_soften_hedges_and_marks_unverified_deterministically() -> None:
    """04 §6: template-based, never LLM-generated — so it is byte-stable."""
    first = act.soften("Revenue grew 40% last year.")
    assert first.startswith(act.SOFTEN_PREFIX)
    assert first.endswith(act.UNVERIFIED_MARKER)
    for _ in range(5):
        assert act.soften("Revenue grew 40% last year.") == first


def test_soften_does_not_stack_when_applied_twice() -> None:
    """Two soften-mapped labels on one sentence must not double the hedge."""
    once = act.soften("Revenue grew 40%.")
    assert act.soften(once) == once
    assert once.count(act.SOFTEN_PREFIX) == 1
    assert once.count(act.UNVERIFIED_MARKER) == 1


def test_soften_leaves_acronyms_uppercase() -> None:
    assert "NASA" in act.soften("NASA reported 40% growth.")


def test_apply_edits_plans_both_transforms_over_one_sentence() -> None:
    """A multi-signal EDIT: redactions first, then the whole-sentence soften.

    Order matters — a whole-sentence soften rewrites the string, so softening before
    redacting would invalidate the spans the redaction still has to hit.
    """
    policy = ALL_POLICIES["support_bot.yaml"]
    text = "Your rep casey@example.org confirmed the 40% refund rate."
    email_start = text.index("casey@example.org")
    signals = [
        ovlp_signal(BEAT_4_SCORE),
        pii_signal("pii.email", start=email_start, end=email_start + len("casey@example.org")),
    ]
    verdict = evaluate(signals, policy)
    result = act.apply_edits(text, verdict.edits, stage=Stage.OUTPUT_SENTENCE)
    assert "casey@example.org" not in result.text
    assert "[REDACTED:email]" in result.text
    assert result.text.startswith(act.SOFTEN_PREFIX)
    assert result.text.rstrip().endswith(act.UNVERIFIED_MARKER)
    assert {a.transform for a in result.applied} == {"redact", "soften"}


def test_applied_edit_records_category_and_span_but_never_the_value() -> None:
    """NFR-SEC-001 / 05 §3: the audit trail proves WHAT was removed, not what it was."""
    text = "SSN 000-12-3456 on file."
    signals = [pii_signal("pii.ssn", start=4, end=15)]
    verdict = evaluate(signals, ALL_POLICIES["support_bot.yaml"])
    result = act.apply_edits(text, verdict.edits, stage=Stage.OUTPUT_SENTENCE)
    record = result.applied[0]
    assert record.label == "pii.ssn" and record.category == "ssn"
    assert record.span == (4, 15)
    for field_value in vars(record).values():
        assert "000-12-3456" not in str(field_value)


# ==========================================================================
# 04 §6 / §4.5 — post-edit re-scan guard and its promotion
# ==========================================================================


def test_rescan_passes_on_correctly_redacted_text() -> None:
    findings = asyncio.run(act.rescan_pii("Reach [REDACTED:email] today.", stage=Stage.OUTPUT_SENTENCE))
    assert findings == ()


def test_rescan_finds_pii_a_broken_transform_left_behind() -> None:
    """The guard's reason for existing: a transform that ran but did not work."""
    findings = asyncio.run(
        act.rescan_pii("SSN 000-12-3456 survived the edit.", stage=Stage.OUTPUT_SENTENCE)
    )
    assert "pii.ssn" in findings


def test_second_failure_promotes_an_output_edit_to_escalate_and_withholds_text() -> None:
    """04 §6 last line. The span is deliberately WRONG so the transform misses.

    This is the only honest way to test the guard: a correct engine plan cannot leave PII
    behind, so the failure has to be injected at the plan level rather than by weakening
    the detector or the assertion.
    """
    policy = ALL_POLICIES["support_bot.yaml"]
    text = "Member SSN 000-12-3456 is on file."
    verdict = evaluate([pii_signal("pii.ssn", start=0, end=6)], policy)  # redacts "Member"
    outcome = asyncio.run(act.apply_verdict(text, verdict, policy))
    assert outcome.action is Action.ESCALATE
    assert outcome.promoted_to_escalate is True
    assert "pii.ssn" in outcome.rescan_findings
    assert outcome.text is None                       # nothing may be released
    assert outcome.quarantined_text == text
    assert outcome.user_message == policy.messages.escalate_user_notice


# ==========================================================================
# 04 §4.4 — release / terminate behaviours
# ==========================================================================


def test_pass_releases_text_unchanged() -> None:
    policy = ALL_POLICIES["hr_copilot.yaml"]
    outcome = asyncio.run(act.apply_verdict("All good.", evaluate([], policy), policy))
    assert outcome.action is Action.PASS and outcome.text == "All good."


def test_block_withholds_text_and_returns_the_policy_fallback() -> None:
    """FR-POL-004: the message comes from the policy file, not from code."""
    policy = ALL_POLICIES["hr_copilot.yaml"]
    verdict = evaluate([pii_signal("pii.ssn")], policy)
    outcome = asyncio.run(act.apply_verdict("SSN on file.", verdict, policy))
    assert outcome.action is Action.BLOCK
    assert outcome.text is None
    assert outcome.user_message == policy.messages.block_fallback


def test_escalate_quarantines_the_text_and_notifies_the_user() -> None:
    """FR-POL-005: quarantined (not delivered) + the policy's notice."""
    policy = ALL_POLICIES["finance_advisor.yaml"]
    verdict = evaluate([ovlp_signal(BEAT_4_SCORE)], policy)
    outcome = asyncio.run(act.apply_verdict("A claim about someone.", verdict, policy))
    assert outcome.action is Action.ESCALATE
    assert outcome.text is None
    assert outcome.quarantined_text == "A claim about someone."
    assert outcome.user_message == policy.messages.escalate_user_notice


def test_edit_releases_transformed_text() -> None:
    policy = ALL_POLICIES["support_bot.yaml"]
    text = "Mail casey@example.org for the refund."
    start = text.index("casey@example.org")
    verdict = evaluate([pii_signal("pii.email", start=start, end=start + 17)], policy)
    outcome = asyncio.run(act.apply_verdict(text, verdict, policy))
    assert outcome.action is Action.EDIT
    assert outcome.text is not None and "casey@example.org" not in outcome.text


# ==========================================================================
# 04 §4.5 / ADR-020 — input-stage semantics
# ==========================================================================


def test_input_edit_redacts_the_prompt_before_dispatch() -> None:
    """ADR-020: the provider never receives the raw value, and dispatch still proceeds.

    FR-POL-003's acceptance criterion in full: the redacted prompt carries no span of the
    original match AND the pre-dispatch re-scan finds nothing.
    """
    policy = ALL_POLICIES["support_bot.yaml"]
    prompt = "My email is casey@example.org, please resend the invoice."
    start = prompt.index("casey@example.org")
    verdict = evaluate(
        [pii_signal("pii.email", start=start, end=start + 17, stage=Stage.INPUT)], policy
    )
    outcome = asyncio.run(act.apply_input_verdict(prompt, verdict, policy))
    assert outcome.action is Action.EDIT
    assert outcome.dispatch is True
    assert outcome.text is not None
    assert "casey@example.org" not in outcome.text
    assert asyncio.run(act.rescan_pii(outcome.text, stage=Stage.INPUT)) == ()
    assert outcome.applied[0].stage is Stage.INPUT


def test_input_block_short_circuits_before_any_upstream_call() -> None:
    """04 §4.5: no upstream call, so no cost. `dispatch` states it rather than implying."""
    policy = ALL_POLICIES["hr_copilot.yaml"]
    verdict = evaluate([pii_signal("pii.ssn", stage=Stage.INPUT)], policy)
    outcome = asyncio.run(act.apply_input_verdict("SSN 000-12-3456", verdict, policy))
    assert outcome.action is Action.BLOCK
    assert outcome.dispatch is False
    assert outcome.text is None


def test_input_escalate_short_circuits_and_quarantines_the_prompt() -> None:
    policy = ALL_POLICIES["finance_advisor.yaml"]
    verdict = evaluate([pii_signal("pii.ssn", stage=Stage.INPUT)], policy)
    outcome = asyncio.run(act.apply_input_verdict("SSN 000-12-3456", verdict, policy))
    assert outcome.action is Action.ESCALATE
    assert outcome.dispatch is False
    assert outcome.quarantined_text == "SSN 000-12-3456"


def test_input_rescan_failure_means_the_request_is_never_dispatched() -> None:
    """04 §4.5's stronger consequence: promotion at input blocks dispatch entirely."""
    policy = ALL_POLICIES["support_bot.yaml"]
    prompt = "Card 4111111111111111 on file."
    verdict = evaluate(
        [pii_signal("pii.credit_card", start=0, end=4, stage=Stage.INPUT)], policy
    )  # redacts "Card", leaving the number
    outcome = asyncio.run(act.apply_input_verdict(prompt, verdict, policy))
    assert outcome.action is Action.ESCALATE
    assert outcome.promoted_to_escalate is True
    assert outcome.dispatch is False
    assert outcome.text is None


# --------------------------------------------------------------------------
# ADR-027 — a detector fault is an operational event, not a content risk
# --------------------------------------------------------------------------


def test_adr027_failure_record_is_not_a_signal_and_carries_no_content_surface() -> None:
    """ADR-027: no span, no plane, no label — so there is nothing that could leak.

    The point of the ruling is structural, so the test is structural: the record must
    not have grown the fields that would make it a content-risk object, because that
    is what would put it back in the closed 04 §1.1 taxonomy it was excluded from.
    """
    record = DetectorFailureRecord(detector="tier1_pii", error_class="DetectorTimeout")
    assert not isinstance(record, Signal)
    for forbidden in ("span", "planes", "labels", "score", "text", "evidence"):
        assert not hasattr(record, forbidden), forbidden


def test_adr027_record_mints_identity_without_making_the_engine_impure() -> None:
    """ADR-027: `failure_id`/`ts` are minted at construction, as `Signal.signal_id` is.

    Determinism (FR-POL-001) is a property of `evaluate()`, not of the inputs: two
    records for the same fault differ in id, yet must produce identical verdicts. That
    is the actual guarantee, so it is what gets asserted — not merely that the fields
    exist.
    """
    policy = ALL_POLICIES["finance_advisor.yaml"]
    first = DetectorFailureRecord(detector="tier1_pii", error_class="DetectorTimeout")
    second = DetectorFailureRecord(detector="tier1_pii", error_class="DetectorTimeout")
    assert first.failure_id != second.failure_id
    assert first.ts and first.failure_id
    assert evaluate([], policy, failures=[first]).action is (
        evaluate([], policy, failures=[second]).action
    )


def test_adr027_fail_closed_is_an_escalate_floor_not_an_override() -> None:
    """ADR-027 item 1: the record forces an ESCALATE *floor* on the unit's verdict.

    A floor and an override differ exactly where a real content BLOCK is present: an
    override would *downgrade* it to ESCALATE, quietly releasing something the policy
    blocked. The 04 §4.2 severity order is what makes the floor correct, so both
    directions are asserted.
    """
    policy = ALL_POLICIES["finance_advisor.yaml"]
    assert policy.fail_mode.tier1 is FailMode.FAIL_CLOSED
    record = DetectorFailureRecord(detector="tier1_pii", error_class="DetectorTimeout")

    # Floor: a PASS-only unit is lifted to ESCALATE.
    assert evaluate([], policy, failures=[record]).action is Action.ESCALATE

    # Not an override: a blocking signal still wins.
    blocking = Signal(
        detector="tier2_injection",
        planes=[Plane.RESPONSIBILITY],
        labels=["security.prompt_injection"],
        score=0.97,
        score_kind=ScoreKind.DETECTION,
        span=None,
        stage=Stage.INPUT,
        evidence="injection classifier probability",
        latency_ms=18.0,
    )
    assert policy.action_for("security.prompt_injection") is Action.BLOCK
    assert evaluate([blocking], policy, failures=[record]).action is Action.BLOCK


def test_adr027_escalate_with_no_content_signals_is_self_explaining() -> None:
    """ADR-027 item 2: the step-5 stamp names signal_ids *and* failure_record_ids.

    This is the case the ruling exists for: an ESCALATE whose `contributing_signal_ids`
    is empty is otherwise an unexplained quarantine. With the failure ids stamped, a
    reviewer can tell a detector outage from a content decision without re-running.
    """
    policy = ALL_POLICIES["finance_advisor.yaml"]
    record = DetectorFailureRecord(detector="tier1_pii", error_class="DetectorTimeout")
    verdict = evaluate([], policy, failures=[record])

    assert verdict.action is Action.ESCALATE
    assert verdict.contributing_signal_ids == ()
    assert verdict.failure_record_ids == (record.failure_id,)


def test_adr027_fail_open_failure_is_recorded_but_does_not_contribute() -> None:
    """A fail_open fault is audited (05 §5) yet stamps no id: it decided nothing."""
    policy = ALL_POLICIES["support_bot.yaml"]
    assert policy.fail_mode.tier2 is FailMode.FAIL_OPEN
    record = DetectorFailureRecord(detector="tier2_toxicity", error_class="DetectorError")
    verdict = evaluate([], policy, failures=[record])

    assert verdict.action is Action.PASS
    assert verdict.failure_record_ids == ()
    assert len(verdict.failure_outcomes) == 1


def test_adr027_audit_entry_has_the_documented_shape_and_no_content() -> None:
    """05 §3/§4: `detector_failures_json` elements carry exactly the seven ruled keys.

    Six until ADR-036 item 4 added `attributable_ms` — the measured in-thread duration that
    makes a real NFR-P-002 breach distinguishable from a scheduling artifact after the fact.
    Still an EXACT set: a seventh key was ruled, an eighth is a contract change. The type rule
    is per key rather than "all strings", because a duration is a number and asserting
    otherwise would have forced the value into a string to satisfy the test.
    """
    policy = ALL_POLICIES["finance_advisor.yaml"]
    record = DetectorFailureRecord(
        detector="tier1_pii", error_class="DetectorTimeout", stage=Stage.INPUT
    )
    entry = resolve_failure(record, policy).audit_entry()

    assert set(entry) == {
        "failure_id", "detector", "error_class", "stage", "fail_mode_applied", "ts",
        "attributable_ms",
    }
    assert entry["fail_mode_applied"] == "fail_closed"
    assert entry["stage"] == "input"
    assert entry["failure_id"] == record.failure_id
    assert all(
        isinstance(v, str) for k, v in entry.items() if k != "attributable_ms"
    ), "every key but the ADR-036 duration is a string"
    assert entry["attributable_ms"] is None, "unmeasured stays null, never 0.0"
