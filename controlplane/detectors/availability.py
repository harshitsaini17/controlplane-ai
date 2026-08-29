"""Detector lifecycle state (c): registered but unloadable (ADR-033).

04 §2 registers eleven detectors; 04 §5 resolves the ones that *run and fault*. Between those
sits a third state with no representation before ADR-033: a detector that has an implementation
but whose **dependency is absent from this host**. It cannot be recorded as `not_implemented` —
that would be a false statement about code that exists — and it cannot be a
`DetectorFailureRecord`, because nothing ran, so there is no `error_class` and no fail mode to
resolve. It is a property of the **process**, decided once at boot.

Two rules follow, and both are the point of this module rather than details of it:

* **A fail-closed promise with the protector absent refuses the boot.** If any active policy maps
  an unavailable detector's class to `fail_closed`, the gateway must not start: it would be
  asserting a guarantee it structurally cannot keep, and — because 05 §4 says a not-run entry is
  not a failure record — it would do so silently, passing every request with a coverage note.
  This mirrors FR-GW-006's startup canary, which is this repo's precedent for a boot that refuses.
* **Under fail_open, boot proceeds loudly.** The absence is warned at startup, carried in each
  affected record's `detectors.unavailable[]`, and counted by `cp_detector_unavailable_total`.
  A dropped detector that left no trace is indistinguishable from one that ran and found nothing.

**What the probe proves, and what it does not.** `importlib.util.find_spec` answers "is this
importable" without importing it — deliberately, because a module-scope binding import in a
detector would break the gateway's *import* on a host without the extra, which is a worse failure
than the one being prevented. So this module detects an **absent dependency**, not a broken one: a
present package whose model graph fails to build at first use is a runtime fault (state (b)),
resolved by `fail_mode` like any other. The boundary is deliberate and is the honest limit of a
boot-time check.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass

from controlplane.detectors.base import BUDGETS_MS
from controlplane.policy.engine import fail_class_for
from controlplane.policy.schema import Consistency, FailMode, Policy

__all__ = [
    "REQUIREMENTS",
    "Unavailable",
    "DetectorUnavailableError",
    "probe_availability",
    "policies_requiring_fail_closed",
    "enforce_at_boot",
]


#: Detector name -> the import names its implementation needs (02 §8 model stack).
#:
#: Transcribed from the ADRs that bound each dependency, the same way `BUDGETS_MS` and
#: `DETECTOR_FAIL_CLASS` were transcribed from the 04 §2 table: one place, so a new detector
#: cannot half-declare itself across three call sites.
#:
#: `fast_consistency` is deliberately **absent**. Its second sample needs a *provider*, which is
#: configuration (ADR-014, and the `ollama-local` binding Q-10 settled) rather than an import —
#: an unreachable provider is a runtime fault, not an unloadable detector. Every deterministic
#: Tier-1 emitter is absent for the plainer reason that it needs nothing but the standard library.
REQUIREMENTS: dict[str, tuple[str, ...]] = {
    # ADR-031 picks the checkpoints, ADR-032 the windowing; both serve on ONNX Runtime and
    # tokenize with transformers.
    #
    # `onnx` is here per **ADR-035**, and it is not a build-time entry that leaked onto a
    # runtime list. ADR-031 keeps no checked-in graph, so a serving host EXPORTS and quantizes
    # at first use — `torch.onnx.export` and `quantize_dynamic` both import `onnx`, while
    # `import onnxruntime` alone does not pull it. Declaring only the serve-time names is what
    # let an `.[ml]` host pass this probe and then fail every request
    # (`[D2-tier2-served-graph-is-unbuildable-on-the-ml-extra]`): fail_closed pipelines blocked
    # everything, fail_open ones silently scanned nothing. The set is MEASURED, not read off a
    # dependency graph — see `tests/test_ml_extra_closure.py`, which masks the interpreter down
    # to `.[ml]`'s declared closure and builds both checkpoints for real.
    "tier2_injection": ("onnxruntime", "transformers", "onnx"),
    "tier2_toxicity": ("onnxruntime", "transformers", "onnx"),
    # 04 §2 embedding-similarity grounding.
    "rag_grounding": ("sentence_transformers",),
    # ADR-011 names the NER model, and the model is a separate installable from spaCy itself —
    # so it is listed separately, because `import spacy` succeeding proves nothing about it.
    "entity_enricher": ("spacy", "en_core_web_sm"),
}

_unknown = sorted(set(REQUIREMENTS) - set(BUDGETS_MS))
if _unknown:                                            # pragma: no cover - import-time guard
    raise RuntimeError(
        f"REQUIREMENTS names {_unknown} which are not detectors in the 04 §2 registry; "
        "add the row to the doc and BUDGETS_MS first"
    )


@dataclass(frozen=True)
class Unavailable:
    """One boot-manifest entry: a registered detector and the first dependency found missing.

    `missing` is the **first** absent name rather than all of them, and the choice matters for
    the operator reading it: installing `onnxruntime` when `transformers` is also absent produces
    a second, identical-looking boot failure. Listing one name per line keeps each message
    actionable; the manifest is re-probed on the next boot, so the second name surfaces then.
    """

    detector: str
    missing: str

    def as_entry(self) -> tuple[str, str]:
        """The `(detector, missing)` pair `serialize_detectors(unavailable=...)` takes."""
        return (self.detector, self.missing)


class DetectorUnavailableError(RuntimeError):
    """A fail-closed policy names a detector this host cannot load. The boot must not proceed.

    A `RuntimeError` subclass for the same reason `UsageSanityError` is one: it is raised from a
    lifespan hook, where the contract is "raise to refuse the boot", and it must not be caught by
    a handler looking for configuration errors.
    """


def _missing_dependency(names: tuple[str, ...]) -> str | None:
    """The first name in `names` that is not importable, or `None` if all are.

    `find_spec` raises `ModuleNotFoundError` when a *parent* package is absent (probing
    `a.b` with no `a`), which is the same answer as returning `None` — so it is caught and
    reported rather than escaping as a boot crash.
    """
    for name in names:
        try:
            if importlib.util.find_spec(name) is None:
                return name
        except (ImportError, ValueError):
            return name
    return None


def probe_availability(
    detectors: object = None, *, requirements: dict[str, tuple[str, ...]] | None = None
) -> tuple[Unavailable, ...]:
    """Probe each named detector's dependencies. Returns the boot manifest, sorted.

    `detectors` defaults to every name in `requirements` — a detector with no declared
    requirement is trivially available and never appears here. Passing an explicit iterable
    narrows the probe to what this process actually registered.

    Never raises for an absent dependency: that is the finding, not an error. Enforcement is a
    separate decision, taken by `enforce_at_boot` against the active policies, because the same
    manifest is a refusal under one policy set and a warning under another.
    """
    reqs = REQUIREMENTS if requirements is None else requirements
    names = sorted(reqs) if detectors is None else sorted(set(detectors) & set(reqs))
    found = []
    for name in names:
        missing = _missing_dependency(reqs[name])
        if missing is not None:
            found.append(Unavailable(detector=name, missing=missing))
    return tuple(found)


def _uses(policy: Policy, detector: str) -> bool:
    """Whether `policy` could ask for `detector` on some request.

    Deliberately **could**, not **will**. 04 §2's other narrowings are per-request —
    `rag_grounding` needs context docs, `conv_tracker` a conversation id — and neither is
    knowable at boot, so a policy that might send such a request counts as using the detector.
    Erring the other way would let a boot succeed and the first qualifying request silently lose
    a fail-closed guarantee, which is the failure this whole state exists to prevent.

    `consistency: off` is the one exception, and the one narrowing that *is* policy-level:
    ADR-014 makes it "not part of this pipeline at all", the same test `expected_for` applies.
    """
    if detector == "fast_consistency":
        # `is not Consistency.OFF`, NOT `str(policy.consistency) != "off"`. `Consistency` is
        # a `(str, Enum)` mixin, so `str(member)` is `'Consistency.OFF'` and that comparison
        # is never true — the narrowing would silently never fire, and an `off` policy would
        # be counted as requiring a detector it disabled.
        return policy.consistency is not Consistency.OFF
    return True


def policies_requiring_fail_closed(
    manifest: tuple[Unavailable, ...], policies: object
) -> dict[str, list[str]]:
    """`{detector: [use_case, ...]}` for unavailable detectors under a `fail_closed` policy.

    Empty means every policy that could use these detectors resolves them `fail_open`, so the
    boot may proceed with a warning.

    A detector with no `fail_mode` class cannot appear: `entity_enricher` is the case (04 §2.2 —
    enrichment failure skips and logs and never blocks, so `DETECTOR_FAIL_CLASS` omits it
    deliberately), and with no class there is no mode to read and nothing to refuse. Recorded as
    ADR-033 consequence 6 because "no class" reads like an oversight until it is written down.
    """
    blocking: dict[str, list[str]] = {}
    for entry in manifest:
        try:
            fail_class = fail_class_for(entry.detector)
        except ValueError:
            continue
        for policy in policies:
            if not _uses(policy, entry.detector):
                continue
            if getattr(policy.fail_mode, fail_class) is FailMode.FAIL_CLOSED:
                blocking.setdefault(entry.detector, []).append(policy.use_case)
    return {d: sorted(u) for d, u in blocking.items()}


def enforce_at_boot(
    manifest: tuple[Unavailable, ...], policies: object
) -> tuple[str, ...]:
    """Apply ADR-033 rule 2. Returns warning lines, or raises `DetectorUnavailableError`.

    Raising is the whole mechanism: a gateway that starts having logged "I cannot load the
    detector your policy requires fail-closed" has converted a refusal into a log line nobody
    reads. The error names the detector, the missing dependency and the policies that require it,
    because those three facts are what an operator needs to either install something or change a
    policy — and a message that omits the policy list leaves them guessing which use case objected.
    """
    if not manifest:
        return ()

    blocking = policies_requiring_fail_closed(manifest, policies)
    if blocking:
        missing_by_detector = {e.detector: e.missing for e in manifest}
        detail = "; ".join(
            f"{detector} (missing {missing_by_detector[detector]}) is fail_closed for "
            f"{', '.join(use_cases)}"
            for detector, use_cases in sorted(blocking.items())
        )
        raise DetectorUnavailableError(
            f"refusing to boot: {detail}. A fail_closed policy promises the protection this "
            "host cannot load, and 05 §4 makes an unrun detector a coverage note rather than a "
            "failure — so the promise would be broken silently, on every request. Install the "
            "dependency (`pip install -e \".[ml]\"`, plus `spacy download` for the NER model) or "
            "set that detector class to fail_open in the named policies (ADR-033)."
        )

    return tuple(
        f"detector {e.detector!r} is registered but UNLOADABLE (missing {e.missing!r}): every "
        f"policy using it is fail_open, so the gateway is starting without it. Affected requests "
        f"record it in detectors.unavailable[] — coverage is REDUCED for this boot, not satisfied."
        for e in manifest
    )
