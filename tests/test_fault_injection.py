"""06 §5 fault-injection harness — FR-POL-006, feeds demo beat 7 / SC-3.

Two things are under test here, and they are different in kind. The **harness mechanics**
(does injection restore state, is coverage derived rather than listed, does a failed assertion
exit nonzero) are ordinary unit tests. The **tripwire** —
`test_tier2_is_not_yet_injectable` — is the opposite: it asserts a *limitation* and is
designed to fail when the limitation lifts. It is cited by name in the generated report, so it
must exist and must mean what the report says it means.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from controlplane.gateway import pipeline
from controlplane.policy.engine import DETECTOR_FAIL_CLASS
from controlplane.policy.store import PolicyStore
from eval import fault_injection as fi
from eval.validate_dataset import USE_CASES

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def store():
    s = PolicyStore()
    s.load()
    return s


@pytest.fixture(scope="module")
def text():
    return fi.probe_text()


# ---------------------------------------------------------------------------
# ★ Tripwire — cited by name in the report
# ---------------------------------------------------------------------------


def test_tier2_carries_sc3_on_the_class_the_docs_name() -> None:
    """★ SC-3 runs on `tier2`, the class 06 §5 and 07 beat 7 both name. Substitution retired.

    **Re-pointed twice, and this is the third and final form.** It first read "no tier2 detector
    is live" and fired when `tier2_injection` shipped; re-pointed to "no tier2 detector is
    *faultable*" — true for a narrower reason, since `tier2_injection` runs at `Stage.INPUT` and
    faults inject only at `FAULT_STAGES`. It fired again when `tier2_toxicity` landed in
    `OUTPUT_SENTENCE`, exactly as its own instructions said it would, and those instructions are
    now carried out: 07 beat 7 needed no edit (it always said `--inject-fault tier2` — the harness
    was the side that deviated), and the report's scope section names `tier2`.

    **The assertion is inverted, which is the point.** For two phases this test guarded against a
    temporary substitution becoming permanent. That risk is gone; the opposite one replaces it —
    tier2 silently *losing* its carrier and SC-3 sliding back onto `performance` without anyone
    noticing. So it now fails if tier2 is not carried, and additionally requires the carrier to be
    among the faultable tier2 detectors: a carrier that cannot actually be faulted would let the
    report claim a fault it can never inject, which is the over-reporting failure
    `test_a_live_tier2_detector_is_not_silently_counted_as_covering_tier2` exists for.
    """
    tier2 = [d for d, c in DETECTOR_FAIL_CLASS.items() if c == "tier2"]
    assert tier2, "the 04 §2 registry must still declare tier2 detectors"
    faultable = [d for d in tier2 if d in fi.faultable()]
    assert faultable, (
        "no tier2 detector is faultable, so SC-3 has silently fallen back to the `performance` "
        "substitution this test was re-pointed to retire. 06 §5 and 07 beat 7 both name `tier2`."
    )
    assert fi.class_carriers().get("tier2") in faultable, (
        f"tier2 is carried by {fi.class_carriers().get('tier2')!r}, which is not among the "
        f"faultable tier2 detectors {faultable} — the report would claim a fault it cannot inject"
    )


def test_a_live_tier2_detector_is_not_silently_counted_as_covering_tier2() -> None:
    """The failure mode the re-point above was found by: covered-on-paper, empty in practice.

    `class_carriers()` selecting on liveness alone put `tier2_injection` under `tier2`, so the
    report claimed the class was carried while every tier2 assertion failed with `failures=[]`.
    Over-reporting coverage is the mirror of the hardcoded map's under-reporting, and it is the
    worse half: under-reporting is visible in the report, over-reporting reads as success.
    """
    for fail_class, detector in fi.class_carriers().items():
        assert detector in fi.faultable(), (
            f"{detector} is claimed to carry `{fail_class}` but sits in no FAULT_STAGES lane, "
            "so its fault would never fire"
        )


def test_the_report_only_cites_tests_that_exist() -> None:
    """A scope note naming a nonexistent test is worse than no scope note (AGENTS.md §7)."""
    source = (ROOT / "eval" / "fault_injection.py").read_text()
    mine = (ROOT / "tests" / "test_fault_injection.py").read_text()
    assert "test_tier2_carries_sc3_on_the_class_the_docs_name" in source
    assert "def test_tier2_carries_sc3_on_the_class_the_docs_name" in mine


# ---------------------------------------------------------------------------
# Coverage is derived, not listed
# ---------------------------------------------------------------------------


def test_class_carriers_are_derived_from_the_live_registry() -> None:
    """The one way this harness could lie: under-report coverage while all asserts pass.

    A hardcoded map would keep calling `tier2` unexercisable after a tier2 detector shipped.
    Every carrier must therefore be a live detector whose 04 §2 class is the key it sits under.
    """
    carriers = fi.class_carriers()
    for fail_class, detector in carriers.items():
        assert detector in pipeline.LIVE, f"{detector} is claimed live but is not in LIVE"
        assert DETECTOR_FAIL_CLASS[detector] == fail_class


def test_a_new_live_detector_changes_coverage_without_a_source_edit(monkeypatch) -> None:
    """Proves derivation rather than asserting it: a detector appears, coverage follows.

    **Re-pointed by ADR-036's sweep.** It used to assert `"tier2" not in class_carriers()` and
    then monkeypatch a fake in — a precondition that stopped being true the moment
    `tier2_toxicity` went live, so the test failed for a reason unrelated to what it asserts.
    The absent-to-present structure is what has the evidentiary value, so it is preserved by
    *removing* the real carrier first rather than by finding a class that happens to be empty:
    `cost` is empty but its detectors sit in no `FAULT_STAGES` lane (04 §2), so faking one there
    would fabricate lane membership the spec denies and prove nothing about derivation.
    """
    carrier = fi.class_carriers()["tier2"]
    monkeypatch.delitem(pipeline.LIVE, carrier)
    assert "tier2" not in fi.class_carriers(), (
        "with the only tier2 carrier removed, coverage must report the class as absent"
    )

    class Fake:
        name = carrier

        async def detect(self, ctx):
            return []

    monkeypatch.setitem(pipeline.LIVE, carrier, Fake())
    assert fi.class_carriers().get("tier2") == carrier


def test_every_class_with_no_carrier_is_absent_rather_than_empty() -> None:
    """`{}` vs a falsey entry: an unexercisable class must not look like an exercised one."""
    carriers = fi.class_carriers()
    assert all(v for v in carriers.values())
    assert set(carriers) <= set(fi.FAIL_CLASSES)


# ---------------------------------------------------------------------------
# Injection hygiene
# ---------------------------------------------------------------------------


def test_injection_restores_the_live_registry(text) -> None:
    """A leaked `_Faulty` would make faults appear in later control runs.

    That symptom reads as a gateway bug rather than as harness contamination, which is why
    restoration is asserted on identity and not just on presence.
    """
    before = dict(pipeline.LIVE)
    fi.run_probe("support_bot", text, inject="numeric_claims")
    assert pipeline.LIVE == before
    assert pipeline.LIVE["numeric_claims"] is before["numeric_claims"]


def test_injection_restores_even_when_the_probe_raises(text, monkeypatch) -> None:
    """The `finally` is load-bearing, so it is tested rather than trusted."""
    before = dict(pipeline.LIVE)

    def boom(*a, **kw):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(fi, "canonical_view", boom)
    with pytest.raises(RuntimeError):
        fi.run_probe("support_bot", text, inject="numeric_claims")
    assert pipeline.LIVE["numeric_claims"] is before["numeric_claims"]


def test_injecting_into_a_dead_detector_is_refused(text) -> None:
    """Silently probing without a fault would report a control run as a faulted one.

    **The stand-in is derived, not named.** This test used to hardcode `tier2_injection`, which
    stopped being dead the moment that detector shipped — the test then failed for a reason
    having nothing to do with what it asserts. Any declared-but-not-live detector proves the
    same point, so it picks one; a synthetic name covers the case where none is left.
    """
    dead = next(
        (d for d in DETECTOR_FAIL_CLASS if d not in pipeline.LIVE),
        "no_such_detector_in_the_04_registry",
    )
    with pytest.raises(SystemExit):
        fi.run_probe("support_bot", text, inject=dead)


def test_injecting_into_a_live_but_unfaultable_detector_is_refused(text) -> None:
    """Live is necessary but not sufficient — the second half of `run_probe`'s guard.

    A detector outside every `FAULT_STAGES` lane can be wrapped without error, and the probe
    would come back stamped `injected=<name>` with an empty `failures` tuple: a control run
    labelled as a faulted one, the precise misreport the dead-detector guard prevents. Skips
    rather than passes vacuously when no such detector exists, so it never reports as coverage
    it did not provide.
    """
    unfaultable = [d for d in pipeline.LIVE if d not in fi.faultable()]
    if not unfaultable:
        pytest.skip("no live-but-unfaultable detector to exercise the guard with")
    with pytest.raises(SystemExit, match="live but not faultable"):
        fi.run_probe("support_bot", text, inject=unfaultable[0])


def test_the_input_lane_still_works_under_an_output_fault(text) -> None:
    """Output-only injection: an input-lane short-circuit must not be mistaken for a verdict.

    `tier1_pii` sits in both lanes. If injection faulted the input lane too, UC-1's escalate
    would come from 04 §4.5's pre-dispatch path rather than from an in-flight response, and
    06 §5's assertion is about the latter.
    """
    probe = fi.run_probe("support_bot", text, inject="tier1_pii")
    assert probe.failures == ("tier1_pii",), (
        "exactly one fault site expected; two means the input lane faulted as well"
    )


# ---------------------------------------------------------------------------
# ★ The SC-3 claim itself
# ---------------------------------------------------------------------------


def test_sc3_one_fault_two_opposite_outcomes(text) -> None:
    """★ FR-POL-006 / SC-3: identical fault, opposite verdicts, from config alone.

    The thesis of demo beat 7. Nothing differs between these two requests but the use-case
    header — same probe text, same injected fault, same code path.
    """
    uc1 = fi.run_probe("support_bot", text, inject="numeric_claims")
    uc3 = fi.run_probe("finance_advisor", text, inject="numeric_claims")

    assert (uc1.verdict, uc3.verdict) == ("pass", "escalate")
    assert (uc1.modes_applied, uc3.modes_applied) == (("fail_open",), ("fail_closed",))
    # ADR-027: recorded either way. A fail_open that dropped the record would be
    # indistinguishable from a detector that never faulted.
    assert "numeric_claims" in uc1.failures and "numeric_claims" in uc3.failures


def test_fail_open_records_the_fault_without_letting_it_contribute(text) -> None:
    """★ ADR-027 Amendment 1: present in one column, absent from the other.

    The distinction a single boolean could not carry — which is why the step-5 stamp is stored
    rather than reconstructed by filtering `detector_failures_json` on `fail_mode_applied`.
    """
    probe = fi.run_probe("support_bot", text, inject="numeric_claims")
    assert probe.failures == ("numeric_claims",)
    assert probe.failure_record_ids == ()
    assert probe.contributed is False


def test_fail_closed_stamps_the_fault_as_contributing(text) -> None:
    probe = fi.run_probe("finance_advisor", text, inject="numeric_claims")
    assert probe.failure_record_ids, "a fail_closed escalate must name what caused it"
    assert probe.contributed is True


def test_the_control_run_is_clean_so_the_faulted_run_means_something(text) -> None:
    """Without this, "UC-3 escalates under fault" is unfalsifiable."""
    for use_case in USE_CASES:
        probe = fi.run_probe(use_case, text)
        assert probe.verdict == "pass", f"{use_case} escalates with no fault injected"
        assert probe.failures == ()


def test_check_keys_on_configured_policy_not_on_the_observed_outcome(text) -> None:
    """The harness must follow config — that is the FR-POL-006 claim it tests.

    Asserting against `expect_mode` derived from the *policy* means a policy edit changes what
    is asserted. Deriving it from the outcome would make every run pass by construction.
    """
    probe = fi.run_probe("support_bot", text, inject="numeric_claims")
    wrong = fi.check(probe, "fail_closed")
    assert [a for a in wrong if not a.passed], (
        "asserting the wrong configured mode must FAIL; if it passes, the assertions are "
        "reading the outcome instead of the policy"
    )
    assert all(a.passed for a in fi.check(probe, "fail_open"))


# ---------------------------------------------------------------------------
# Report + entry point
# ---------------------------------------------------------------------------


def test_the_probe_text_comes_from_the_frozen_dataset(text) -> None:
    """AGENTS.md §9.7: no invented test strings. Also pins WHY this case.

    A faulted verdict is only attributable to the fault if the text is clean through every
    live detector — which is a property of this frozen case, not an assumption.
    """
    import json

    rows = [
        json.loads(line)
        for line in (ROOT / "eval" / "dataset" / "clean.jsonl").read_text().splitlines()
        if line.strip()
    ]
    row = next(r for r in rows if r["case_id"] == fi.PROBE_CASE)
    assert row["text"] == text
    assert row["labels_expected"] == [], "the probe case must carry no expected labels"


def test_a_missing_probe_case_is_a_hard_failure(tmp_path) -> None:
    """Dataset drift must surface here, not as a probe checking an empty string."""
    (tmp_path / "clean.jsonl").write_text('{"case_id": "OTHER", "text": "x"}\n')
    with pytest.raises(SystemExit):
        fi.probe_text(tmp_path)


def test_main_writes_a_report_and_exits_zero_when_the_invariants_hold(tmp_path) -> None:
    out = tmp_path / "fault.md"
    assert fi.main(["--out", str(out)]) == 0
    body = out.read_text()
    assert "Fail-open / fail-closed verification" in body
    assert "SC-3" in body


def test_main_exits_nonzero_when_an_assertion_fails(tmp_path, monkeypatch) -> None:
    """A broken 04 §5 invariant must break the build (the D3-tripwire shape of 06 §5)."""
    real = fi.check

    def sabotage(probe, expect_mode):
        return [*real(probe, expect_mode), fi.Assertion("injected failure", False, "n/a")]

    monkeypatch.setattr(fi, "check", sabotage)
    assert fi.main(["--out", str(tmp_path / "f.md")]) == 1


def test_the_report_carries_no_response_text(tmp_path) -> None:
    """NFR-SEC-001 at the report boundary: verdicts and ids, never the checked content.

    The probe case is benign, so this is not about *this* text — it is about the shape. A
    harness that printed the response would leak whatever a future probe case contained, and a
    leak in a committed report cannot be withdrawn.
    """
    out = tmp_path / "f.md"
    fi.main(["--out", str(out)])
    assert fi.probe_text() not in out.read_text()


def test_the_report_states_the_class_substitution(tmp_path) -> None:
    """The scope note must record that the `performance` substitution is retired, not silent.

    Asserted structurally rather than by quoting prose: a phrase match would break on any
    rewording while saying nothing about whether the report is actually honest. What must hold is
    that `tier2` is named, that its live carrier is named, that the retirement is stated, and
    that the guard is cited — a reader who saw the old note needs to see the change, since a
    report that quietly stops mentioning a two-phase caveat is indistinguishable from one whose
    caveat still applies.
    """
    out = tmp_path / "f.md"
    fi.main(["--out", str(out)])
    body = out.read_text()
    assert "tier2" in body
    assert "`tier2_toxicity`" in body, "the coverage table must name the live tier2 carrier"
    assert "substitution is retired" in body
    assert "test_tier2_carries_sc3_on_the_class_the_docs_name" in body


def test_the_report_shows_configured_modes_for_unexercisable_classes(tmp_path, store) -> None:
    """Config visibility must not depend on implementation status."""
    out = tmp_path / "f.md"
    fi.main(["--out", str(out)])
    body = out.read_text()
    for fail_class in fi.FAIL_CLASSES:
        assert f"`{fail_class}`" in body


# --- M-60 / Branch-B remedy: the reproducibility section ------------------------------------
#
# These pin a *claim shape*, not a measurement. The first published version of this section
# hardcoded "Every repetition ran on a quiet host" and printed it directly beside an end-of-run
# stamp reading NOT CITABLE — a claim contradicted by a premise on the same page, which is the
# defect class this repo keeps finding. Every assertion below exists so that one specific
# sentence cannot come back.


def _reps(*specs) -> tuple[fi.RepOutcome, ...]:
    """(passed, load1, load1_end, *failures) → RepOutcomes, total fixed at 39."""
    return tuple(
        fi.RepOutcome(passed=p, total=39, failures=tuple(f), load1=lo, load1_end=hi)
        for p, lo, hi, *f in specs
    )


def test_m60_the_quiet_host_claim_is_derived_from_the_stamps_not_asserted() -> None:
    """A rep above the 06 §8 threshold must disqualify itself, whatever the pass count says."""
    body = "\n".join(fi._reproducibility_section(_reps((39, 0.5, 0.6), (39, 0.9, 1.9))))
    assert "Not every repetition was measured on a quiet host" in body
    assert "**NO**" in body, "the loud repetition must be marked in the table"
    assert "not citable" in body.lower()
    assert "stayed within the 06 §8 quiet threshold" not in body, (
        "a run containing a loud repetition must never claim all of them were quiet"
    )


def test_m60_an_all_quiet_run_says_so_and_attributes_the_spread_to_the_system() -> None:
    body = "\n".join(fi._reproducibility_section(_reps((39, 0.5, 0.6), (39, 0.8, 0.9))))
    assert "stayed within the 06 §8 quiet threshold" in body
    assert "**NO**" not in body


def test_m60_an_unrecorded_load_is_not_reported_as_quiet() -> None:
    """Three-valued, like `host_load.is_quiet`: never-measured is not measured-and-passed."""
    body = "\n".join(fi._reproducibility_section(_reps((39, None, None), (39, 0.8, 0.9))))
    assert "not recorded" in body
    assert "stayed within the 06 §8 quiet threshold" not in body


def test_m60_a_clean_run_does_not_report_the_mechanism_as_gone() -> None:
    """The whole point of the row: 5/5 clean in one process is not a fixed invariant."""
    body = "\n".join(fi._reproducibility_section(_reps((39, 0.5, 0.6), (39, 0.8, 0.9))))
    assert "not the same as absent" in body
    assert "Mechanism, not noise" not in body, "no failure occurred; do not narrate one"


def test_m60_a_failing_repetition_names_the_mechanism_instead_of_calling_it_flake() -> None:
    body = "\n".join(fi._reproducibility_section(_reps((39, 0.5, 0.6), (38, 0.8, 0.9, "ctl"))))
    assert "Mechanism, not noise" in body
    assert "`ctl` — failed **1/2**" in body
    assert "not relaxed" in body, "§5.4: the assertion absorbs nothing"


def test_m60_the_in_process_warm_pool_limit_is_stated_not_omitted() -> None:
    """Reps 2..N reuse warmed models, so the rate understates the cold-path flake."""
    body = "\n".join(fi._reproducibility_section(_reps((39, 0.5, 0.6), (39, 0.8, 0.9))))
    assert "warmed steady state" in body
    assert "does **not** retire that mechanism" in body


def test_m60_the_superseded_claim_renders_as_a_real_blockquote() -> None:
    """It rendered as one line with inline `>` characters, which reads as a live claim."""
    lines = fi._reproducibility_section(_reps((39, 0.5, 0.6), (39, 0.8, 0.9)))
    i = lines.index("### Superseded single-run claim — preserved, not deleted")
    quoted = [ln for ln in lines[i:] if ln.strip()][1:]
    assert quoted, "the superseded claim must still be present"
    assert all(ln.startswith(">") for ln in quoted), (
        "every line of the preserved claim must carry its own `>` prefix"
    )


def test_m60_a_single_repetition_publishes_no_rate() -> None:
    """One run cannot state a rate — that was the original defect, not the fix."""
    assert fi._reproducibility_section(_reps((39, 0.5, 0.6))) == []


def test_m60_the_rate_does_not_soften_the_exit_contract(tmp_path, monkeypatch) -> None:
    """A failure in ANY repetition must still break the build (widened, not weakened)."""
    real = fi.check

    def sabotage(probe, expect_mode):
        return [*real(probe, expect_mode), fi.Assertion("injected failure", False, "n/a")]

    monkeypatch.setattr(fi, "check", sabotage)
    assert fi.main(["--out", str(tmp_path / "f.md"), "--reps", "2"]) == 1
