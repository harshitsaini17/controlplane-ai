"""ADR-033 state (c): registered but unloadable (`docs/04 §5`, `docs/05 §3/§4`).

The state exists because two *different* facts previously shared one silence. A detector
absent from `detectors_ran` could mean "this phase never wrote it" (state (a)) or "it
exists and this host cannot load it" (state (c)), and only the second breaks a coverage
promise the policy made. These tests pin the separation and the boot enforcement that
makes it non-optional.

**No test here fakes a load** (ADR-033 rule 4). Where an unloadable detector is needed,
the *requirement* is redirected at a module that genuinely does not exist, so the probe
reports a real absence. Installing a stub module to satisfy `find_spec` would test the
opposite of the invariant.
"""

from __future__ import annotations

import pytest

from controlplane.detectors import availability
from controlplane.detectors.availability import (
    REQUIREMENTS,
    DetectorUnavailableError,
    Unavailable,
    enforce_at_boot,
    policies_requiring_fail_closed,
    probe_availability,
)
from controlplane.policy.schema import Consistency
from controlplane.policy.store import PolicyStore

#: A module name that cannot resolve on any host. `find_spec` must report it absent rather
#: than raise, which is itself part of the contract.
ABSENT = "onnxruntime_absent_on_purpose"


@pytest.fixture
def policies():
    # `.load()` is explicit: `PolicyStore()` constructs empty and `Gateway.__init__` is what
    # normally loads it. A fixture that skipped this would hand every test an empty policy
    # set, and each enforcement assertion would pass by having nothing to object.
    store = PolicyStore()
    store.load()
    assert store.use_cases, "the shipped policies/ directory did not load"
    return [store.get(use_case) for use_case in store.use_cases]


def _policy(policies, use_case):
    return next(p for p in policies if p.use_case == use_case)


# --------------------------------------------------------------------------
# The probe
# --------------------------------------------------------------------------


def test_an_absent_dependency_is_reported_not_raised() -> None:
    """The finding is data. Raising here would conflate probing with enforcing."""
    manifest = probe_availability(requirements={"tier2_injection": (ABSENT,)})
    assert manifest == (Unavailable(detector="tier2_injection", missing=ABSENT),)


def test_a_present_dependency_produces_no_entry() -> None:
    """`sys` is importable everywhere; a manifest entry for it would be a false alarm."""
    assert probe_availability(requirements={"tier2_injection": ("sys",)}) == ()


def test_the_first_absent_dependency_is_the_one_named() -> None:
    """One name, not a list: the operator installs the first blocker and re-runs."""
    manifest = probe_availability(
        requirements={"tier2_injection": ("sys", ABSENT, "also_absent_xyz")}
    )
    assert manifest[0].missing == ABSENT


def test_a_dotted_name_with_no_parent_is_reported_absent_not_crashed() -> None:
    """`find_spec("a.b")` RAISES when `a` is missing — same answer, different channel.

    Left uncaught this would turn a missing dependency into a boot traceback from inside
    the probe, which is the one outcome the manifest exists to avoid.
    """
    manifest = probe_availability(requirements={"tier2_injection": (f"{ABSENT}.sub",)})
    assert manifest[0].missing == f"{ABSENT}.sub"


def test_the_probe_is_narrowed_by_the_detectors_passed() -> None:
    """A detector this process never bound cannot be a coverage gap for it."""
    reqs = {"tier2_injection": (ABSENT,), "tier2_toxicity": (ABSENT,)}
    manifest = probe_availability(["tier2_injection"], requirements=reqs)
    assert [entry.detector for entry in manifest] == ["tier2_injection"]


def test_a_detector_with_no_declared_requirement_is_trivially_available() -> None:
    """The Tier-1 regex emitters import nothing; a manifest row for them is noise."""
    manifest = probe_availability(["tier1_pii"], requirements={"tier2_injection": (ABSENT,)})
    assert manifest == ()


def test_the_shipped_requirements_name_only_detectors_with_budgets() -> None:
    """A requirement under a name 04 §2 does not list could never reach enforcement.

    `fail_class_for` would reject it and `policies_requiring_fail_closed` would skip it,
    so the dependency would be probed and then silently ignored.
    """
    from controlplane.detectors.base import BUDGETS_MS

    assert set(REQUIREMENTS) <= set(BUDGETS_MS)


def test_fast_consistency_declares_no_import_requirement() -> None:
    """It needs a *provider* (config), not a module — so it is not an ADR-033 case.

    Listing it here would make a policy-level configuration gap look like a missing
    install, and would refuse boots that are correctly configured.
    """
    assert "fast_consistency" not in REQUIREMENTS


# --------------------------------------------------------------------------
# Enforcement (ADR-033 rule 2)
# --------------------------------------------------------------------------


def test_an_empty_manifest_neither_refuses_nor_warns(policies) -> None:
    assert enforce_at_boot((), policies) == ()


def test_a_fail_closed_policy_refuses_the_boot(policies) -> None:
    """★ The ruling's core: you cannot promise fail_closed with the protector absent.

    `finance_advisor` maps `tier2: fail_closed`, so an unloadable `tier2_injection` must
    stop the process rather than start one whose audit column quietly records reduced
    coverage on every request.
    """
    manifest = (Unavailable(detector="tier2_injection", missing=ABSENT),)
    with pytest.raises(DetectorUnavailableError) as exc:
        enforce_at_boot(manifest, policies)

    message = str(exc.value)
    assert "tier2_injection" in message, "the detector must be named"
    assert ABSENT in message, "the missing dependency must be named"
    assert "finance_advisor" in message, "the objecting policy must be named"


def test_a_fail_open_only_policy_set_warns_and_proceeds(policies) -> None:
    """Availability over strictness is a documented per-use-case choice (04 §5)."""
    fail_open = [_policy(policies, "support_bot"), _policy(policies, "hr_copilot")]
    lines = enforce_at_boot(
        (Unavailable(detector="tier2_injection", missing=ABSENT),), fail_open
    )

    assert len(lines) == 1
    assert "UNLOADABLE" in lines[0]
    assert "REDUCED" in lines[0], "a warning that reads as healthy is worse than none"


def test_the_refusal_names_every_objecting_policy(policies) -> None:
    """One policy named out of two leaves the operator guessing which to change."""
    blocking = policies_requiring_fail_closed(
        (Unavailable(detector="tier1_pii", missing=ABSENT),), policies
    )
    # All three ship `tier1: fail_closed` — 01 §3 makes that the one universal choice.
    assert blocking["tier1_pii"] == ["finance_advisor", "hr_copilot", "support_bot"]


def test_a_detector_with_no_fail_mode_class_can_never_refuse_a_boot(policies) -> None:
    """ADR-033 consequence 6. `entity_enricher` is omitted from `DETECTOR_FAIL_CLASS`.

    Deliberately, per 04 §2.2: enrichment failure skips and logs, never blocks. With no
    class there is no mode to read, so there is nothing that could be promised and broken
    — and "no class" reads like an oversight until a test says otherwise.
    """
    manifest = (Unavailable(detector="entity_enricher", missing=ABSENT),)
    assert policies_requiring_fail_closed(manifest, policies) == {}
    assert len(enforce_at_boot(manifest, policies)) == 1, "still warned, never fatal"


def test_consistency_off_is_the_one_policy_level_narrowing(policies) -> None:
    """ADR-014 makes `consistency: off` "not part of this pipeline at all".

    Every other 04 §2 narrowing is per-request (context docs, conversation id) and so is
    unknowable at boot — erring toward "uses it" there is what keeps a fail-closed
    guarantee from being lost by the first qualifying request.
    """
    off = [p for p in policies if p.consistency is Consistency.OFF]
    # Asserted, not skipped. The first draft of this test filtered with
    # `str(p.consistency) == "off"` — which is never true for a `(str, Enum)` mixin — so it
    # skipped, and a skip is what let the identical mistake in `_uses` look tested.
    assert sorted(p.use_case for p in off) == \
        ["finance_advisor", "hr_copilot", "support_bot"], \
        "SL-6 cut fast_consistency, so every shipped policy now reads `off` (was hr only)"
    manifest = (Unavailable(detector="fast_consistency", missing=ABSENT),)
    assert policies_requiring_fail_closed(manifest, off) == {}
    # And the narrowing must actually be doing the work: hr_copilot maps
    # `performance: fail_open`, so flip that read to prove the empty dict above came from
    # `_uses` rather than from the fail-mode lookup agreeing by accident.
    assert availability._uses(off[0], "fast_consistency") is False
    assert availability._uses(off[0], "rag_grounding") is True


def test_the_live_host_manifest_is_reported_not_assumed() -> None:
    """Documents what this host actually is, without asserting either answer.

    A test demanding `()` would fail on a CI box without the `[ml]` extra; one demanding a
    non-empty manifest would fail on a developer's full install. Both would be testing the
    environment rather than the code.
    """
    manifest = probe_availability()
    assert all(isinstance(entry, Unavailable) for entry in manifest)
    assert {e.detector for e in manifest} <= set(REQUIREMENTS)
