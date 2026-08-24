"""Pydantic models for the per-use-case policy YAML.

Implements the policy schema in 04 §3 and its validation rules verbatim:

  * action values ∈ {pass, edit, block, escalate}                    -> `Action`
  * `borderline_action` ∈ the same set (ADR-017)                     -> `borderline_action`
  * only span-emitting labels may map to `edit`                      -> `_check_edit_eligibility`
  * `tau_low` < `tau_high`                                           -> `Thresholds`
  * `consistency: on` ⇒ `streaming: false` (ADR-014)                 -> `_check_consistency_streaming`
  * `cascade_probe` ∈ {on, off} (ADR-013)                            -> `CascadeProbe`
  * unknown keys rejected                                            -> `extra="forbid"` everywhere
  * wildcards expand at load; a specific key overrides its wildcard  -> `expand_actions`

The action severity order (04 §4.2) lives here because it is a property of the
action vocabulary itself; the engine that consumes it is `policy/engine.py`.

This module contains no use-case conditionals and no policy values — every
threshold, mapping and failure mode is data loaded from `policies/*.yaml`
(FR-POL-002, ADR-003, AGENTS.md §9.1).
"""

from __future__ import annotations

from enum import Enum
from functools import cached_property
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

# --------------------------------------------------------------------------
# Label taxonomy (04 §1.1) — closed set; extend ONLY via a doc change.
# --------------------------------------------------------------------------

TAXONOMY: frozenset[str] = frozenset(
    {
        "pii.ssn",
        "pii.credit_card",
        "pii.email",
        "pii.phone",
        "pii.api_key",
        "pii.person_data",
        "security.prompt_injection",
        "security.blocklist",
        "toxicity.high",
        "toxicity.moderate",
        "hallucination.low_confidence",
        "hallucination.ungrounded_claim",
        "hallucination.unsourced_numeric",
        "privacy.person",
        "cost.budget_exceeded",
        "cost.request_too_large",
        "cost.loop_detected",
        "conversation.cumulative_risk",
    }
)

#: Label families that may legally appear as a `<family>.*` wildcard action key.
FAMILIES: frozenset[str] = frozenset(label.split(".", 1)[0] for label in TAXONOMY)

#: Labels that may map to `edit`.
#:
#: NORMATIVELY DERIVED from the 04 §6 transform table, which is the single source
#: (ADR-015). 04 §6 defines exactly two transforms — `redact` (trigger `pii.*`) and
#: `soften` (trigger `hallucination.*`) — so a label may map to `edit` only if a
#: transform exists to carry it out. The schema can therefore never admit an EDIT
#: verdict with no defined effect.
#:
#: Label eligibility is necessary but not sufficient: per ADR-015, an edit-mapped
#: *signal* must additionally carry a span OR be `stage="output_sentence"` (the
#: whole-sentence soften scope). A signal that satisfies neither is promoted to
#: ESCALATE by the engine at 04 §4.3 step 4 — that check is per-signal and so lives
#: in `policy/engine.py`, not here.
#:
#: This constant also enforces 04 §4.5 ("input labels must not map to edit;
#: schema-enforced") as a side effect: the input-only labels
#: (`security.prompt_injection`, `cost.*`) have no transform and are already excluded.
EDIT_ELIGIBLE_LABELS: frozenset[str] = frozenset(
    label for label in TAXONOMY if label.startswith(("pii.", "hallucination."))
)

#: Synthesized on detector timeout/error (04 §5). Resolution is governed by the
#: policy `fail_mode` for the detector's class, NOT by the `actions` map, so it is
#: rejected as an action key to keep the two mechanisms unambiguous.
DETECTOR_FAILURE_LABEL = "_meta.detector_failure"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class Action(str, Enum):
    """Policy verdict vocabulary (04 §3 validation rule 1, 04 §4.2)."""

    PASS = "pass"
    EDIT = "edit"
    BLOCK = "block"
    ESCALATE = "escalate"

    @property
    def severity(self) -> int:
        """Total order from 04 §4.2: BLOCK > ESCALATE > EDIT > PASS."""
        return _SEVERITY[self]


_SEVERITY: dict[Action, int] = {
    Action.PASS: 0,
    Action.EDIT: 1,
    Action.ESCALATE: 2,
    Action.BLOCK: 3,
}


class RiskAppetite(str, Enum):
    """04 §3: `low | medium | high` — informational + default pack selector."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Consistency(str, Enum):
    """04 §2.3 consistency modes (ADR-014)."""

    ON = "on"
    ON_SAMPLED = "on_sampled"
    OFF = "off"


class CascadeProbe(str, Enum):
    """04 §3 validation rule 5 — `cascade_probe` ∈ {on, off} (ADR-013)."""

    ON = "on"
    OFF = "off"


class FailMode(str, Enum):
    """04 §5 failure semantics (FR-POL-006)."""

    FAIL_OPEN = "fail_open"
    FAIL_CLOSED = "fail_closed"


# --------------------------------------------------------------------------
# Nested sections
# --------------------------------------------------------------------------

Probability = Annotated[float, Field(ge=0.0, le=1.0)]


class _Section(BaseModel):
    """Base for every policy section: unknown keys are rejected (04 §3)."""

    model_config = ConfigDict(extra="forbid")


class Sampling(_Section):
    deep_audit_rate: Probability


class Thresholds(_Section):
    """Calibrated per 06 §3; scores are in [0,1] (04 §1)."""

    tau_low: Probability
    tau_high: Probability
    tau_route: Probability

    @model_validator(mode="after")
    def _check_band_order(self) -> "Thresholds":
        """04 §3 validation rule 3: `tau_low` < `tau_high`.

        Equality is rejected too: it would collapse the borderline band of
        04 §4.3 step 2 to nothing, silently disabling ESCALATE-eligibility.
        """
        if self.tau_low >= self.tau_high:
            raise ValueError(
                f"tau_low ({self.tau_low}) must be strictly less than "
                f"tau_high ({self.tau_high}); an empty [tau_low, tau_high) band "
                "would disable the borderline/ESCALATE-eligible band (04 §4.3)"
            )
        return self


class Budget(_Section):
    monthly_usd: Annotated[float, Field(gt=0.0)]
    per_request_max_tokens: Annotated[int, Field(gt=0)]
    loop_max_requests_per_min: Annotated[int, Field(gt=0)]


class FailModes(_Section):
    """Per detector class (04 §3 `fail_mode`); classes are those named in 04 §3."""

    tier1: FailMode
    tier2: FailMode
    performance: FailMode
    cost: FailMode


class Messages(_Section):
    """User-facing text; FR-POL-004 requires it to come from the policy file."""

    block_fallback: Annotated[str, Field(min_length=1)]
    escalate_user_notice: Annotated[str, Field(min_length=1)]


class Escalation(_Section):
    notify: list[Annotated[str, Field(min_length=1)]]
    quarantine_ttl_s: Annotated[int, Field(gt=0)]


# --------------------------------------------------------------------------
# Action-map expansion (04 §3: "wildcards expand at load; a specific key
# overrides its wildcard")
# --------------------------------------------------------------------------


def expand_actions(actions: dict[str, Action], default_action: Action) -> dict[str, Action]:
    """Resolve the sparse YAML action map into a full label -> action map.

    Precedence, per 04 §3 and 04 §4.3 step 1: specific label > wildcard > default.
    Every label in `TAXONOMY` is present in the result.
    """
    resolved: dict[str, Action] = {label: default_action for label in TAXONOMY}

    for key, action in actions.items():
        if key.endswith(".*"):
            prefix = key[:-1]  # "pii.*" -> "pii."
            for label in TAXONOMY:
                if label.startswith(prefix):
                    resolved[label] = action

    # Specific keys applied second so they override their wildcard.
    for key, action in actions.items():
        if not key.endswith(".*"):
            resolved[key] = action

    return resolved


# --------------------------------------------------------------------------
# The policy
# --------------------------------------------------------------------------


class Policy(_Section):
    """One per-use-case policy file (04 §3). Loaded and versioned by `policy/store.py`."""

    schema_version: Literal[1]
    use_case: Annotated[str, Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")]
    policy_version: Annotated[int, Field(ge=1)]
    geography: Annotated[str, Field(min_length=1)]
    risk_appetite: RiskAppetite

    streaming: bool
    sampling: Sampling
    consistency: Consistency
    cascade_probe: CascadeProbe

    thresholds: Thresholds
    budget: Budget

    actions: dict[str, Action]
    default_action: Action

    #: Action for a signal whose score lands in the borderline band
    #: [tau_low, tau_high) — ADR-017. Per-label and policy-configurable, which is
    #: what dissolved the "cap/floor" contradiction in the original 04 §4.3 step 2:
    #: a cap downgraded BLOCK->ESCALATE (breaking beat 4b) while a floor upgraded
    #: EDIT->ESCALATE (breaking beat 4a). Naming the band's action per policy means
    #: neither direction is hardcoded.
    #:
    #: Only reachable by `score_kind == "confidence"` signals (ADR-012); detection-kind
    #: signals bypass the band entirely, so this never applies to them.
    #:
    #: NOT edit-eligibility-checked here, deliberately. The labels the band can reach
    #: depend on the unresolved enriched-label survival rule
    #: ([D4-enriched-label-survival-semantics]): confidence-kind emitters are
    #: `fast_consistency` and `rag_grounding`, both `hallucination.*` and both
    #: edit-eligible — but an enriched `privacy.person` rides on a `rag_grounding`
    #: signal and is NOT edit-eligible. Whether `borderline_action: edit` can therefore
    #: reach an untransformable label is exactly what that report asks. Adding a
    #: validator now would bake in one reading.
    borderline_action: Action

    fail_mode: FailModes
    messages: Messages
    escalation: Escalation

    blocklist_extra: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)
    detector_params: dict[str, dict[str, float]] = Field(default_factory=dict)

    # -- validators ------------------------------------------------------

    @field_validator("consistency", "cascade_probe", mode="before")
    @classmethod
    def _reject_yaml_boolean(cls, value: object, info: ValidationInfo) -> object:
        """Catch the YAML 1.1 `on`/`off` → bool trap with an actionable error.

        PyYAML implements YAML 1.1, where the bare tokens `on`, `off`, `yes` and `no`
        resolve to booleans. Both of these fields are *string* enums whose members
        include `on`/`off` (04 §3, ADR-013, ADR-014), so an unquoted value silently
        arrives here as `True`/`False`. The default enum error ("Input should be 'on'
        or 'off'", input_value=True) is technically correct but reads as nonsense to
        whoever wrote `cascade_probe: on`. FR-CFG-001 requires a precise error.
        """
        if isinstance(value, bool):
            raise ValueError(
                f"{info.field_name}: got the boolean {value!r}, not a string. In YAML 1.1 "
                "(what PyYAML parses) the bare tokens on/off/yes/no are booleans, so "
                f'write {info.field_name}: "on" — quoted — instead of {info.field_name}: on. '
                "Note `streaming` IS a real boolean and must stay unquoted."
            )
        return value

    @model_validator(mode="after")
    def _check_action_keys(self) -> "Policy":
        """Action keys must be taxonomy labels (04 §1.1) or `<family>.*` wildcards.

        A wildcard whose family does not exist matches nothing and would silently
        do nothing, so it is rejected as a typo.
        """
        for key in self.actions:
            if key == DETECTOR_FAILURE_LABEL:
                raise ValueError(
                    f"{key!r} is not a valid action key: detector-failure handling is "
                    "governed by `fail_mode` for the detector's class (04 §5), not by "
                    "the actions map"
                )
            if key.endswith(".*"):
                family = key[:-2]
                if family not in FAMILIES:
                    raise ValueError(
                        f"unknown label family in action key {key!r}; "
                        f"known families: {sorted(FAMILIES)} (04 §1.1)"
                    )
            elif key not in TAXONOMY:
                raise ValueError(
                    f"unknown label in action key {key!r}; the taxonomy in 04 §1.1 is "
                    "a closed set and is extended only via a doc change"
                )
        return self

    @model_validator(mode="after")
    def _check_edit_eligibility(self) -> "Policy":
        """04 §3: only span-emitting labels may map to `edit`.

        Checked against the *resolved* map so a wildcard (`security.*: edit`) or
        `default_action: edit` cannot smuggle in an ineligible label.
        See `EDIT_ELIGIBLE_LABELS` for the allowlist and its derivation.
        """
        offenders = sorted(
            label
            for label, action in self.resolved_actions.items()
            if action is Action.EDIT and label not in EDIT_ELIGIBLE_LABELS
        )
        if offenders:
            raise ValueError(
                f"labels {offenders} may not map to 'edit': only span-emitting labels "
                f"with a defined 04 §6 transform are edit-eligible "
                f"({sorted(EDIT_ELIGIBLE_LABELS)}). An 'edit' verdict on any other "
                "label would apply no transform. Input-stage labels are additionally "
                "barred from edit by 04 §4.5."
            )
        return self

    @model_validator(mode="after")
    def _check_consistency_streaming(self) -> "Policy":
        """04 §2.3 / 04 §3 / ADR-014: `consistency: on` ⇒ `streaming: false`."""
        if self.consistency is Consistency.ON and self.streaming:
            raise ValueError(
                "consistency: 'on' requires streaming: false (ADR-014) — the full "
                "response and its parallel second sample are compared once, "
                "pre-delivery, so nothing reaches the user before the verdict. Use "
                "consistency: 'on_sampled' for a streaming pipeline."
            )
        return self

    # -- derived views ---------------------------------------------------

    @cached_property
    def resolved_actions(self) -> dict[str, Action]:
        """Full label -> action map with wildcards expanded (04 §3)."""
        return expand_actions(self.actions, self.default_action)

    def action_for(self, label: str) -> Action:
        """Action for one label: specific > wildcard > `default_action` (04 §4.3 step 1)."""
        return self.resolved_actions.get(label, self.default_action)
