"""Policy schema tests — FR-CFG-001 (04 §3 validation rules).

Covers: all three shipped policies load and validate, the doc-fixed values in the
04 §3 normative example survive transcription, wildcard expansion semantics, and
one failing case per validation rule listed in 04 §3.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from controlplane.policy.schema import (
    EDIT_ELIGIBLE_LABELS,
    TAXONOMY,
    Action,
    CascadeProbe,
    Consistency,
    FailMode,
    Policy,
    RiskAppetite,
    expand_actions,
)

POLICY_DIR = Path(__file__).resolve().parent.parent / "policies"

#: The three UC profiles in 01 §3.
POLICY_FILES = ("support_bot.yaml", "hr_copilot.yaml", "finance_advisor.yaml")


def load_raw(name: str) -> dict[str, Any]:
    """Parse a shipped policy file into a plain dict (no validation)."""
    return yaml.safe_load((POLICY_DIR / name).read_text())


@pytest.fixture
def valid_policy_dict() -> dict[str, Any]:
    """A known-valid policy dict, mutated per test to trip one rule at a time.

    Sourced from the normative 04 §3 example so the negative tests are anchored to
    the doc rather than to a hand-built fixture.
    """
    return copy.deepcopy(load_raw("finance_advisor.yaml"))


# --------------------------------------------------------------------------
# Valid loads — FR-CFG-001
# --------------------------------------------------------------------------


@pytest.mark.parametrize("filename", POLICY_FILES)
def test_fr_cfg_001_shipped_policies_load_and_validate(filename: str) -> None:
    """Every policy in `policies/` validates against the 04 §3 schema."""
    policy = Policy(**load_raw(filename))
    assert policy.schema_version == 1
    assert policy.use_case == filename.removesuffix(".yaml")


def test_fr_cfg_001_valid_policy_dict_fixture_is_actually_valid(
    valid_policy_dict: dict[str, Any],
) -> None:
    """Guard: the negative tests below are only meaningful if the base is valid."""
    assert Policy(**valid_policy_dict).use_case == "finance_advisor"


def test_finance_advisor_matches_doc_04_section_3_example() -> None:
    """UC-3 is transcribed from the normative 04 §3 example — verify key-by-key."""
    p = Policy(**load_raw("finance_advisor.yaml"))

    assert p.policy_version == 3
    assert p.geography == "EU"
    assert p.risk_appetite is RiskAppetite.LOW
    assert p.streaming is False
    assert p.sampling.deep_audit_rate == 0.25
    assert p.consistency is Consistency.ON
    assert p.cascade_probe is CascadeProbe.OFF
    assert (p.thresholds.tau_low, p.thresholds.tau_high, p.thresholds.tau_route) == (
        0.35,
        0.70,
        0.55,
    )
    assert p.budget.monthly_usd == 200
    assert p.budget.per_request_max_tokens == 4000
    assert p.budget.loop_max_requests_per_min == 10
    assert p.default_action is Action.PASS
    # 01 §3 UC-3: fail_closed everywhere.
    assert all(
        mode is FailMode.FAIL_CLOSED
        for mode in (
            p.fail_mode.tier1,
            p.fail_mode.tier2,
            p.fail_mode.performance,
            p.fail_mode.cost,
        )
    )
    assert p.escalation.quarantine_ttl_s == 3600
    assert p.escalation.notify == ["console", "webhook:${REVIEW_WEBHOOK_URL}"]


def test_uc_profiles_differ_in_delivery_mode_per_adr_014() -> None:
    """ADR-014: the three pipelines differ even in delivery mode."""
    policies = {name: Policy(**load_raw(name)) for name in POLICY_FILES}

    support = policies["support_bot.yaml"]
    hr = policies["hr_copilot.yaml"]
    finance = policies["finance_advisor.yaml"]

    assert (support.streaming, support.consistency) == (True, Consistency.ON_SAMPLED)
    assert (hr.streaming, hr.consistency) == (True, Consistency.OFF)
    assert (finance.streaming, finance.consistency) == (False, Consistency.ON)

    # ADR-013: probe on for the two lower-stakes pipelines, off for high stakes.
    assert support.cascade_probe is CascadeProbe.ON
    assert hr.cascade_probe is CascadeProbe.ON
    assert finance.cascade_probe is CascadeProbe.OFF

    # 01 §3 sampling rates.
    assert support.sampling.deep_audit_rate == 0.10
    assert hr.sampling.deep_audit_rate == 0.05
    assert finance.sampling.deep_audit_rate == 0.25


def test_fr_pol_002_pii_verdict_differs_by_policy_alone() -> None:
    """01 §3 / 07 beat 4: identical PII label, three different mapped actions.

    This is the config-not-code thesis expressed at the schema level: the same
    label resolves differently with no code branch involved (AGENTS.md §9.1).
    """
    actions = {
        name: Policy(**load_raw(name)).action_for("pii.email") for name in POLICY_FILES
    }
    assert actions["support_bot.yaml"] is Action.EDIT
    assert actions["hr_copilot.yaml"] is Action.BLOCK
    assert actions["finance_advisor.yaml"] is Action.ESCALATE


# --------------------------------------------------------------------------
# Ruled values (ADR-015 / ADR-016) — `policies/*.yaml` is the normative source,
# so these guard the demo path against a silent edit. Mapping-level only: the
# engine does not exist yet, so these assert label -> action resolution, not verdicts.
# --------------------------------------------------------------------------


def test_adr_016_budget_ordering_keeps_beat_7b_intact() -> None:
    """07 beat 7b exhausts UC-3's ceiling; 01 §3 gives UC-2 the highest.

    Ordering must hold as a real numeric relation, not a prose claim: $800 > $500 > $200.
    """
    ceilings = {
        name: Policy(**load_raw(name)).budget.monthly_usd for name in POLICY_FILES
    }
    assert ceilings["hr_copilot.yaml"] == 800
    assert ceilings["support_bot.yaml"] == 500
    assert ceilings["finance_advisor.yaml"] == 200
    assert (
        ceilings["hr_copilot.yaml"]
        > ceilings["support_bot.yaml"]
        > ceilings["finance_advisor.yaml"]
    )


def test_adr_016_toxicity_appetite_gradient_is_intentional() -> None:
    """ADR-016: `toxicity.moderate` runs pass -> pass -> escalate across UC-1/2/3."""
    mapped = {
        name: Policy(**load_raw(name)).action_for("toxicity.moderate")
        for name in POLICY_FILES
    }
    assert mapped["support_bot.yaml"] is Action.PASS
    assert mapped["hr_copilot.yaml"] is Action.PASS
    assert mapped["finance_advisor.yaml"] is Action.ESCALATE

    # toxicity.high is BLOCK everywhere — the gradient is on `moderate` alone.
    assert all(
        Policy(**load_raw(name)).action_for("toxicity.high") is Action.BLOCK
        for name in POLICY_FILES
    )


def test_adr_015_support_bot_maps_hallucination_labels_individually() -> None:
    """ADR-015 amendment: `fast_consistency` is output_full and span-less by design.

    A `hallucination.*` family map would send `low_confidence` to `edit`, which
    04 §4.3 step 4 then promotes to ESCALATE at *every* firing. UC-1 therefore maps
    the consequence explicitly instead of relying on promotion.
    """
    policy = Policy(**load_raw("support_bot.yaml"))
    assert policy.action_for("hallucination.ungrounded_claim") is Action.EDIT
    assert policy.action_for("hallucination.unsourced_numeric") is Action.EDIT
    assert policy.action_for("hallucination.low_confidence") is Action.ESCALATE

    # The explicit mapping must be in the file, not an artefact of expansion.
    assert "hallucination.*" not in load_raw("support_bot.yaml")["actions"]


def test_adr_015_privacy_person_is_never_edit_mapped() -> None:
    """`privacy.person` has no 04 §6 transform, so no policy may map it to edit."""
    for name in POLICY_FILES:
        assert Policy(**load_raw(name)).action_for("privacy.person") is not Action.EDIT


def test_beat_4_fixture_labels_resolve_to_three_distinct_actions() -> None:
    """07 beat 4 (★ signature) at the mapping level — the config-not-code thesis.

    The beat-4 demo fixture carries the OVLP multi-label signal
    (`hallucination.ungrounded_claim` + `privacy.person`) plus one `pii.email` span
    (ADR-015). Per 04 §4.3 the verdict is the most severe mapped action across the
    fixture's labels, so this asserts EDIT / BLOCK / ESCALATE without needing the engine.

    NOTE: this is necessary but not sufficient for the beat. Band adjustment
    (04 §4.3 step 2) can still move UC-1's EDIT once the engine exists — see the open
    DEVIATION REPORT [D1-band-logic-vs-beat-4b]. Extend this test to full verdicts
    when the engine lands.
    """
    fixture_labels = ["hallucination.ungrounded_claim", "privacy.person", "pii.email"]

    def most_severe(policy: Policy) -> Action:
        return max(
            (policy.action_for(label) for label in fixture_labels),
            key=lambda a: a.severity,
        )

    verdicts = {name: most_severe(Policy(**load_raw(name))) for name in POLICY_FILES}
    assert verdicts["support_bot.yaml"] is Action.EDIT       # beat 4a
    assert verdicts["hr_copilot.yaml"] is Action.BLOCK       # beat 4b
    assert verdicts["finance_advisor.yaml"] is Action.ESCALATE  # beat 4c

    # 4a must be *executable* as an edit: at least one contributing label needs a
    # 04 §6 transform, otherwise the "softened claim + redacted detail" is empty.
    support = Policy(**load_raw("support_bot.yaml"))
    editable = [
        label
        for label in fixture_labels
        if support.action_for(label) is Action.EDIT and label in EDIT_ELIGIBLE_LABELS
    ]
    assert "pii.email" in editable          # -> redact ("redacted detail")
    assert "hallucination.ungrounded_claim" in editable  # -> soften ("softened claim")


def test_beat_4b_block_survives_the_added_pii_span() -> None:
    """ADR-015 verification claim: the enriched fixture still BLOCKs on UC-2.

    Both `pii.*` and `privacy.person` map to block there, so the verdict is
    over-determined — adding the span cannot weaken it.
    """
    hr = Policy(**load_raw("hr_copilot.yaml"))
    assert hr.action_for("pii.email") is Action.BLOCK
    assert hr.action_for("privacy.person") is Action.BLOCK


def test_beat_4_per_label_mapped_actions_are_pinned(
) -> None:
    """ADR-017: beat 4 at *per-label* granularity, not just the aggregate.

    Band adjustment is applied per label (ADR-017), so the aggregate assertion in
    `test_beat_4_fixture_labels_resolve_to_three_distinct_actions` can hold while an
    individual label's mapping silently drifts. This pins each one.

    Scope limit: these are the **mapped** actions (04 §4.3 step 1) — before band
    adjustment and before the step-4 span check. The post-band expectations for the
    enriched `privacy.person` label are blocked on the open DEVIATION REPORT
    [D4-enriched-label-survival-semantics] and are deliberately absent here rather
    than guessed at.
    """
    expected: dict[str, dict[str, Action]] = {
        "support_bot.yaml": {
            "hallucination.ungrounded_claim": Action.EDIT,   # soften
            # `pass`, and beat 4a depends on it — see the guard test below. The
            # hallucination label carries the action on UC-1; the privacy label adds
            # no severity here (multi-label convergence, FR-DET-005 — not indifference
            # to persons).
            "privacy.person": Action.PASS,
            "pii.email": Action.EDIT,                        # redact (via `pii.*`)
        },
        "hr_copilot.yaml": {
            "hallucination.ungrounded_claim": Action.PASS,   # relaxed grounding
            "privacy.person": Action.BLOCK,                  # carries beat 4b
            "pii.email": Action.BLOCK,
        },
        "finance_advisor.yaml": {
            "hallucination.ungrounded_claim": Action.ESCALATE,
            "privacy.person": Action.ESCALATE,
            "pii.email": Action.ESCALATE,
        },
    }
    for filename, per_label in expected.items():
        policy = Policy(**load_raw(filename))
        for label, action in per_label.items():
            assert policy.action_for(label) is action, (
                f"{filename}: {label} mapped to {policy.action_for(label)}, expected {action}"
            )


def test_beat_4a_breaks_if_support_bot_hardens_privacy_person(
    valid_policy_dict: dict[str, Any],
) -> None:
    """Guard on a real trap: raising UC-1's `privacy.person` silently kills beat 4a.

    `support_bot` maps `privacy.person: pass`, which looks lax in isolation and invites
    a well-meaning "harden the privacy plane" edit. But beat 4a's verdict is the most
    severe action across the fixture's labels (04 §4.3), so any value above PASS
    dominates the EDIT that the signature beat needs — the demo would then show
    ESCALATE / BLOCK / ESCALATE and the config-not-code thesis would lose its contrast.

    UC-1 is not indifferent to persons: the same span still fires
    `hallucination.ungrounded_claim` → EDIT (soften) and `pii.*` → EDIT (redact). The
    privacy label adds no *additional* severity here, which is the multi-label
    convergence rule doing its job (FR-DET-005), not a gap.
    """
    fixture_labels = ["hallucination.ungrounded_claim", "privacy.person", "pii.email"]
    support_raw = load_raw("support_bot.yaml")

    def most_severe(policy: Policy) -> Action:
        return max(
            (policy.action_for(label) for label in fixture_labels),
            key=lambda a: a.severity,
        )

    assert most_severe(Policy(**support_raw)) is Action.EDIT  # beat 4a, as shipped

    for hardened in (Action.ESCALATE, Action.BLOCK):
        mutated = copy.deepcopy(support_raw)
        mutated["actions"]["privacy.person"] = hardened.value
        assert most_severe(Policy(**mutated)) is not Action.EDIT, (
            f"privacy.person={hardened.value} left beat 4a's EDIT intact — the coupling "
            "this test guards has moved; re-derive it before relaxing the test."
        )


# --------------------------------------------------------------------------
# ADR-017 — borderline_action
# --------------------------------------------------------------------------


def test_adr_017_ruled_borderline_actions_per_use_case() -> None:
    """The ADR-017 ruling named one value per UC; each matches that UC's 01 §3 posture.

    These are a *ruling*, not a preference — changing one is a policy-version bump and
    an ADR amendment, not an edit.
    """
    ruled = {
        "support_bot.yaml": Action.EDIT,          # soften-first posture
        "hr_copilot.yaml": Action.PASS,           # PASS-and-log posture
        "finance_advisor.yaml": Action.ESCALATE,  # escalation-heavy
    }
    for filename, action in ruled.items():
        assert Policy(**load_raw(filename)).borderline_action is action, filename


def test_adr_017_borderline_action_spans_three_distinct_actions() -> None:
    """The three UCs must not collapse to one value, or the band proves nothing.

    If all three agreed, `borderline_action` would be a constant wearing a config
    costume and the ADR-017 ruling would have bought nothing (FR-POL-002).
    """
    values = {Policy(**load_raw(name)).borderline_action for name in POLICY_FILES}
    assert len(values) == 3


def test_adr_017_borderline_action_rejects_unknown_value(
    valid_policy_dict: dict[str, Any],
) -> None:
    valid_policy_dict["borderline_action"] = "soften"
    with pytest.raises(ValidationError):
        Policy(**valid_policy_dict)


@pytest.mark.parametrize("action", [a.value for a in Action])
def test_adr_017_borderline_action_accepts_every_action_member(
    valid_policy_dict: dict[str, Any], action: str
) -> None:
    """04 §3: `borderline_action` ∈ {pass, edit, block, escalate} — the full set.

    Notably including `block`, which no shipped policy uses: the band is where a
    *confidence* signal lands, and a policy author may legitimately want a borderline
    ungrounded claim blocked outright.
    """
    valid_policy_dict["borderline_action"] = action
    assert Policy(**valid_policy_dict).borderline_action is Action(action)


def test_adr_017_borderline_action_edit_is_not_eligibility_checked_yet() -> None:
    """Characterization test for a deliberate gap — delete it when D4 is ruled.

    `support_bot` sets `borderline_action: edit`, and the schema does **not** verify
    that the labels which can reach the band have a 04 §6 transform. That check is
    withheld on purpose: the two confidence-kind emitters differ, so the correct
    validator depends on the unruled [D4-enriched-label-survival-semantics].

      - `rag_grounding`  → `hallucination.ungrounded_claim`, stage=output_sentence
        ⇒ whole-sentence soften applies; `edit` is executable.
      - `fast_consistency` → `hallucination.low_confidence`, output_full and span-less
        ⇒ no editable extent; 04 §4.3 step 4 promotes it to ESCALATE at every firing.

    So `edit` here is executable for one emitter and inert for the other. Adding a
    naive eligibility validator now would either reject a legitimate policy or bless
    a silently-promoted one.
    """
    support = Policy(**load_raw("support_bot.yaml"))
    assert support.borderline_action is Action.EDIT
    # The label that makes it executable does have a transform...
    assert "hallucination.ungrounded_claim" in EDIT_ELIGIBLE_LABELS
    # ...and so does the span-less one, which is exactly why label-set eligibility
    # alone cannot decide this (ADR-015: eligibility is necessary, not sufficient).
    assert "hallucination.low_confidence" in EDIT_ELIGIBLE_LABELS


def test_uc3_escalation_heavy_profile_holds_across_taxonomy() -> None:
    """01 §3 UC-3: escalation-heavy. Nothing in UC-3 may resolve to EDIT."""
    finance = Policy(**load_raw("finance_advisor.yaml"))
    assert all(action is not Action.EDIT for action in finance.resolved_actions.values())


# --------------------------------------------------------------------------
# Wildcard expansion — 04 §3 "wildcards expand at load; a specific key
# overrides its wildcard"
# --------------------------------------------------------------------------


def test_wildcard_expands_to_every_label_in_family() -> None:
    resolved = expand_actions({"pii.*": Action.BLOCK}, default_action=Action.PASS)
    pii_labels = [label for label in TAXONOMY if label.startswith("pii.")]
    assert pii_labels, "taxonomy should contain pii.* labels (04 §1.1)"
    assert all(resolved[label] is Action.BLOCK for label in pii_labels)


def test_unlisted_label_falls_back_to_default_action() -> None:
    resolved = expand_actions({"pii.*": Action.BLOCK}, default_action=Action.PASS)
    assert resolved["toxicity.high"] is Action.PASS
    # Every taxonomy label is represented after expansion.
    assert set(resolved) == set(TAXONOMY)


def test_specific_key_overrides_its_wildcard(valid_policy_dict: dict[str, Any]) -> None:
    """04 §3: `pii.email: edit` overrides `pii.*`, regardless of YAML key order."""
    valid_policy_dict["actions"]["pii.*"] = "escalate"
    valid_policy_dict["actions"]["pii.email"] = "edit"
    policy = Policy(**valid_policy_dict)

    assert policy.action_for("pii.email") is Action.EDIT
    assert policy.action_for("pii.ssn") is Action.ESCALATE


def test_severity_order_matches_doc_04_section_4_2() -> None:
    """04 §4.2: BLOCK > ESCALATE > EDIT > PASS."""
    ordered = sorted(Action, key=lambda a: a.severity)
    assert ordered == [Action.PASS, Action.EDIT, Action.ESCALATE, Action.BLOCK]


# --------------------------------------------------------------------------
# Rule 1 — action values ∈ {pass, edit, block, escalate}
# --------------------------------------------------------------------------


def test_rule_action_enum_rejects_unknown_action(valid_policy_dict: dict[str, Any]) -> None:
    valid_policy_dict["actions"]["toxicity.high"] = "quarantine"
    with pytest.raises(ValidationError):
        Policy(**valid_policy_dict)


def test_rule_action_enum_rejects_unknown_default_action(
    valid_policy_dict: dict[str, Any],
) -> None:
    valid_policy_dict["default_action"] = "warn"
    with pytest.raises(ValidationError):
        Policy(**valid_policy_dict)


# --------------------------------------------------------------------------
# Rule 2 — only span-emitting labels may map to `edit`
# --------------------------------------------------------------------------


def test_rule_edit_requires_span_emitting_label(valid_policy_dict: dict[str, Any]) -> None:
    """`toxicity.high: edit` has no 04 §6 transform, so it must be rejected."""
    valid_policy_dict["actions"]["toxicity.high"] = "edit"
    with pytest.raises(ValidationError, match="may not map to 'edit'"):
        Policy(**valid_policy_dict)


def test_rule_edit_check_sees_through_wildcards(valid_policy_dict: dict[str, Any]) -> None:
    """A wildcard must not smuggle `edit` onto an ineligible label.

    The specific `toxicity.*` keys are removed first: with them present the wildcard
    is fully shadowed by the specific-over-wildcard rule and legitimately resolves to
    nothing (pinned by `test_fully_shadowed_wildcard_is_inert` below).
    """
    for label in ("toxicity.high", "toxicity.moderate"):
        valid_policy_dict["actions"].pop(label, None)
    valid_policy_dict["actions"]["toxicity.*"] = "edit"
    with pytest.raises(ValidationError, match="may not map to 'edit'"):
        Policy(**valid_policy_dict)


def test_rule_edit_check_catches_partially_shadowed_wildcard(
    valid_policy_dict: dict[str, Any],
) -> None:
    """A wildcard leaking `edit` onto even one unlisted label must be rejected.

    UC-3 maps `cost.budget_exceeded` and `cost.loop_detected` but not
    `cost.request_too_large`, so `cost.*: edit` reaches exactly one ineligible label.
    """
    valid_policy_dict["actions"]["cost.*"] = "edit"
    with pytest.raises(ValidationError, match="may not map to 'edit'"):
        Policy(**valid_policy_dict)


def test_fully_shadowed_wildcard_is_inert(valid_policy_dict: dict[str, Any]) -> None:
    """04 §3 precedence: a wildcard whose every label is listed specifically does nothing.

    Not a loophole in the edit rule — the check runs on the *resolved* map, so an
    `edit` that never survives resolution also never takes effect.
    """
    valid_policy_dict["actions"]["toxicity.*"] = "edit"  # both toxicity labels are listed
    policy = Policy(**valid_policy_dict)

    assert policy.action_for("toxicity.high") is Action.BLOCK
    assert policy.action_for("toxicity.moderate") is Action.ESCALATE
    assert Action.EDIT not in policy.resolved_actions.values()


def test_rule_edit_check_sees_through_default_action(
    valid_policy_dict: dict[str, Any],
) -> None:
    """`default_action: edit` would apply edit to unlisted, ineligible labels."""
    valid_policy_dict["default_action"] = "edit"
    with pytest.raises(ValidationError, match="may not map to 'edit'"):
        Policy(**valid_policy_dict)


def test_rule_edit_allows_eligible_labels(valid_policy_dict: dict[str, Any]) -> None:
    """Positive side of the rule: `pii.*` and `hallucination.*` are edit-eligible (04 §6)."""
    valid_policy_dict["actions"]["pii.*"] = "edit"
    valid_policy_dict["actions"]["hallucination.low_confidence"] = "edit"
    policy = Policy(**valid_policy_dict)
    assert policy.action_for("pii.ssn") is Action.EDIT
    assert policy.action_for("hallucination.low_confidence") is Action.EDIT


def test_edit_eligible_set_is_exactly_the_04_section_6_transform_triggers() -> None:
    """04 §6 defines two transforms: redact (`pii.*`) and soften (`hallucination.*`)."""
    assert EDIT_ELIGIBLE_LABELS == frozenset(
        label for label in TAXONOMY if label.startswith(("pii.", "hallucination."))
    )


def test_fr_pol_004_5_input_stage_labels_cannot_map_to_edit(
    valid_policy_dict: dict[str, Any],
) -> None:
    """04 §4.5: input EDIT is unsupported in v1; input labels must not map to edit."""
    for input_label in ("security.prompt_injection", "cost.budget_exceeded"):
        mutated = copy.deepcopy(valid_policy_dict)
        mutated["actions"][input_label] = "edit"
        with pytest.raises(ValidationError, match="may not map to 'edit'"):
            Policy(**mutated)


# --------------------------------------------------------------------------
# Rule 3 — tau_low < tau_high
# --------------------------------------------------------------------------


def test_rule_tau_low_must_be_below_tau_high(valid_policy_dict: dict[str, Any]) -> None:
    valid_policy_dict["thresholds"]["tau_low"] = 0.80
    valid_policy_dict["thresholds"]["tau_high"] = 0.70
    with pytest.raises(ValidationError, match="must be strictly less than"):
        Policy(**valid_policy_dict)


def test_rule_tau_low_equal_to_tau_high_is_rejected(
    valid_policy_dict: dict[str, Any],
) -> None:
    """Equality would empty the 04 §4.3 borderline band — rejected, not tolerated."""
    valid_policy_dict["thresholds"]["tau_low"] = 0.70
    valid_policy_dict["thresholds"]["tau_high"] = 0.70
    with pytest.raises(ValidationError, match="must be strictly less than"):
        Policy(**valid_policy_dict)


def test_rule_thresholds_must_be_within_zero_one(valid_policy_dict: dict[str, Any]) -> None:
    """Scores are in [0,1] (04 §1), so thresholds over them must be too."""
    valid_policy_dict["thresholds"]["tau_high"] = 1.4
    with pytest.raises(ValidationError):
        Policy(**valid_policy_dict)


# --------------------------------------------------------------------------
# Rule 4 — consistency: on ⇒ streaming: false (ADR-014)
# --------------------------------------------------------------------------


def test_rule_consistency_on_requires_non_streaming(
    valid_policy_dict: dict[str, Any],
) -> None:
    valid_policy_dict["consistency"] = "on"
    valid_policy_dict["streaming"] = True
    with pytest.raises(ValidationError, match="requires streaming: false"):
        Policy(**valid_policy_dict)


@pytest.mark.parametrize("mode", ["on_sampled", "off"])
def test_rule_other_consistency_modes_allow_streaming(
    valid_policy_dict: dict[str, Any], mode: str
) -> None:
    """Only `on` constrains streaming (04 §2.3); the other two modes are free."""
    valid_policy_dict["consistency"] = mode
    valid_policy_dict["streaming"] = True
    assert Policy(**valid_policy_dict).streaming is True


def test_rule_consistency_rejects_unknown_mode(valid_policy_dict: dict[str, Any]) -> None:
    valid_policy_dict["consistency"] = "always"
    with pytest.raises(ValidationError):
        Policy(**valid_policy_dict)


# --------------------------------------------------------------------------
# Rule 5 — cascade_probe ∈ {on, off} (ADR-013)
# --------------------------------------------------------------------------


def test_rule_cascade_probe_enum_rejects_other_values(
    valid_policy_dict: dict[str, Any],
) -> None:
    valid_policy_dict["cascade_probe"] = "auto"
    with pytest.raises(ValidationError):
        Policy(**valid_policy_dict)


def test_rule_cascade_probe_rejects_yaml_boolean(valid_policy_dict: dict[str, Any]) -> None:
    """`cascade_probe: true` is a plausible YAML slip; the enum is {on, off}."""
    valid_policy_dict["cascade_probe"] = True
    with pytest.raises(ValidationError):
        Policy(**valid_policy_dict)


# --------------------------------------------------------------------------
# Rule 6 — unknown keys rejected
# --------------------------------------------------------------------------


def test_rule_unknown_top_level_key_rejected(valid_policy_dict: dict[str, Any]) -> None:
    valid_policy_dict["shadow_mode"] = True
    with pytest.raises(ValidationError):
        Policy(**valid_policy_dict)


@pytest.mark.parametrize(
    "section", ["sampling", "thresholds", "budget", "fail_mode", "messages", "escalation"]
)
def test_rule_unknown_nested_key_rejected(
    valid_policy_dict: dict[str, Any], section: str
) -> None:
    """Every nested section forbids extras, not just the top level."""
    valid_policy_dict[section]["surprise"] = 1
    with pytest.raises(ValidationError):
        Policy(**valid_policy_dict)


def test_rule_misspelled_key_is_rejected_not_defaulted(
    valid_policy_dict: dict[str, Any],
) -> None:
    """A typo must fail loudly rather than silently fall back (FR-CFG-001)."""
    valid_policy_dict["defalt_action"] = valid_policy_dict.pop("default_action")
    with pytest.raises(ValidationError):
        Policy(**valid_policy_dict)


@pytest.mark.parametrize(
    "required_key",
    [
        "schema_version",
        "use_case",
        "policy_version",
        "geography",
        "risk_appetite",
        "streaming",
        "sampling",
        "consistency",
        "cascade_probe",
        "thresholds",
        "budget",
        "actions",
        "default_action",
        "borderline_action",
        "fail_mode",
        "messages",
        "escalation",
    ],
)
def test_required_keys_have_no_silent_defaults(
    valid_policy_dict: dict[str, Any], required_key: str
) -> None:
    """A policy missing any governing key must refuse to load, not assume a value."""
    valid_policy_dict.pop(required_key)
    with pytest.raises(ValidationError):
        Policy(**valid_policy_dict)


# --------------------------------------------------------------------------
# Action-key hygiene — 04 §1.1 closed taxonomy, 04 §5 fail_mode separation
# --------------------------------------------------------------------------


def test_unknown_action_label_rejected(valid_policy_dict: dict[str, Any]) -> None:
    valid_policy_dict["actions"]["toxicity.extreme"] = "block"
    with pytest.raises(ValidationError, match="unknown label in action key"):
        Policy(**valid_policy_dict)


def test_unknown_wildcard_family_rejected(valid_policy_dict: dict[str, Any]) -> None:
    """`bias.*` matches nothing; a silent no-op would hide the typo."""
    valid_policy_dict["actions"]["bias.*"] = "block"
    with pytest.raises(ValidationError, match="unknown label family"):
        Policy(**valid_policy_dict)


def test_detector_failure_label_rejected_as_action_key(
    valid_policy_dict: dict[str, Any],
) -> None:
    """04 §5: detector failure is resolved by `fail_mode`, never by the actions map."""
    valid_policy_dict["actions"]["_meta.detector_failure"] = "block"
    with pytest.raises(ValidationError, match="not a valid action key"):
        Policy(**valid_policy_dict)


def test_fail_mode_enum_rejects_unknown_mode(valid_policy_dict: dict[str, Any]) -> None:
    valid_policy_dict["fail_mode"]["tier2"] = "fail_soft"
    with pytest.raises(ValidationError):
        Policy(**valid_policy_dict)


def test_fr_pol_004_block_fallback_must_be_non_empty(
    valid_policy_dict: dict[str, Any],
) -> None:
    """FR-POL-004: BLOCK returns the configured message, so it cannot be blank."""
    valid_policy_dict["messages"]["block_fallback"] = ""
    with pytest.raises(ValidationError):
        Policy(**valid_policy_dict)
