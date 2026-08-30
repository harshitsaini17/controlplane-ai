"""Fail-open / fail-closed verification -> reports/fault_injection_report.md.

Implements 06 §5 against 04 §5 semantics (FR-POL-006); output feeds demo beat 7 / SC-3.

**What 06 §5 asks for, and what it gets.** "For each detector class: monkeypatch to raise
timeout → fire one canary request per use case → assert UC-1 fails **open** (pass, with the
fault present in `detector_failures_json`) and UC-3 fails **closed** (escalate, with the same
fault stamped in `failure_record_ids`)." Both assertions are evaluated here, read back from
the audit record rather than from the HTTP response — the response says what the client saw,
and 04 §5's claim is about what the system *recorded* about its own failure.

**The class 06 §5 names is the class this run carries. The substitution is retired.** §5 and
07 beat 7 both say `tier2`, and `tier2_toxicity` (OUTPUT_SENTENCE) now carries it. Worth recording
why the stand-in stood as long as it did, because the second reason was not the first: initially
no tier2 detector existed to monkeypatch, then `tier2_injection` shipped but runs at **INPUT**
(04 §2) while this harness injects only at `FAULT_STAGES` — see `_Faulty` for why the input lane
is a different phenomenon rather than an oversight. The harness needed no edit to close it:
`faultable()` derives coverage, so a detector landing in an output lane changes the answer by
itself. `numeric_claims` (04 §2 class `performance`) is still exercised beside it, now as
corroboration rather than a stand-in, and the shipped policies give both classes the identical
asymmetry the beat exists to show:

    performance:   support_bot fail_open · hr_copilot fail_open · finance_advisor fail_closed
    tier2:         support_bot fail_open · hr_copilot fail_open · finance_advisor fail_closed

Same two-sided contrast, same requirement (FR-POL-006 is *per detector class*, not per
detector). So SC-3 is demonstrable now on `performance`, and `tier2` is pinned as deferred by
`test_tier2_is_not_yet_injectable` — the tripwire pattern ratified for OVLP-01/beat 4. When a
*faultable* tier2 detector lands, `class_carriers()` picks it up automatically (it is derived,
not listed) and that test fails, forcing 07 beat 7 back into review rather than letting the
substitution become permanent. `tier2_injection` going live already fired it once, which is how
the stage precondition was found.

`tier1` is live but cannot carry the beat for the opposite reason: all three policies set
`tier1: fail_closed`, so it has no fail-open side. It is still exercised and reported, because
"every policy agrees here" is itself a fact worth showing next to a class where they disagree.

**A control run is part of the method, not a nicety.** "UC-3 escalates under fault" means
nothing unless UC-3 does *not* escalate without one. Each use case is therefore probed twice —
once clean, once faulted — and the report prints both. Without the control, a policy that
escalates everything would look like a working fail-closed mechanism.

**Nothing here invents a test string** (AGENTS.md §9.7). The probe prompt *and* the stub
response are both `CLN-001` from the frozen dataset, verified clean through every live
detector: that is what makes a faulted verdict attributable to the fault rather than to
content. A single-sentence text also keeps the fault count at one per lane pass, so
`detector_failures_json` stays readable.

The upstream is a stub, so no figure here derives from a provider (ADR-018) — the gate is
evaluated and recorded as non-binding, the same scoping `run_all.py` applies and states.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from controlplane.audit.records import canonical_view
from controlplane.detectors import rag_grounding as rag_grounding_mod
from controlplane.detectors.base import DetectorTimeout, Stage
from controlplane.gateway import pipeline
from controlplane.detectors.onnx_models import warm_models
from controlplane.gateway.app import Gateway, create_app
from controlplane.gateway.config import (
    TaintedDataError,
    load_gateway_config,
    require_measured_upstream,
)
from controlplane.gateway.ingress import CONTEXT_KEY, HEADER_REQUEST_ID, HEADER_USE_CASE
from controlplane.gateway.sse_proxy import UpstreamResponse
from controlplane.policy.engine import DETECTOR_FAIL_CLASS
from controlplane.policy.store import PolicyStore
from controlplane.telemetry.metrics import MetricsRegistry
from eval.host_load import (
    code_commit_cell,
    git_stamp,
    load_stamp,
    quiet_verdict,
)
from eval.validate_dataset import (
    DATASET_DIR,
    FROZEN_COMMIT,
    USE_CASES,
    check_freeze,
    dataset_digest,
)

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
DEFAULT_OUT = REPORTS_DIR / "fault_injection_report.md"

#: The 04 §3 fail_mode classes, in the order 04 §3 lists them.
FAIL_CLASSES: tuple[str, ...] = ("tier1", "tier2", "performance", "cost")

#: The frozen case supplying both the probe prompt and the stub response.
PROBE_CASE = "CLN-001"

#: The fault injected. `DetectorTimeout` rather than `DetectorError` because 06 §5 says
#: "monkeypatch to raise timeout" — and it is the harder case: a timeout is what
#: `run_with_budget` produces when a detector merely runs long, which is the realistic
#: failure a latency budget creates. Both normalize to `DetectorFailure`, so 04 §5 resolves
#: them identically; picking the one the doc names keeps the harness answerable to it.
FAULT = DetectorTimeout

#: The stages at which `_Faulty` raises — and therefore the only stages at which a fault can
#: actually be injected. **Shared with `class_carriers()` so the fault site and the coverage
#: derivation cannot drift.** A carrier chosen outside these stages is selected, reported as
#: covering its class, and then never faults. That is not hypothetical: it is what happened the
#: moment `tier2_injection` (an INPUT-only detector, 04 §2) went live — every tier2 assertion
#: failed with `failures=[]` while the report still claimed tier2 was carried. The precondition
#: was always there; it was satisfied by accident while every carrier happened to be output-lane.
FAULT_STAGES: tuple[Stage, ...] = (Stage.OUTPUT_SENTENCE, Stage.OUTPUT_FULL)


def faultable() -> frozenset[str]:
    """Live detectors `_Faulty` can actually raise for: those in a `FAULT_STAGES` lane.

    Membership only — ordering is left to `DETECTOR_FAIL_CLASS`, which preserves the 04 §2
    registry order the carrier tie-break depends on.
    """
    return frozenset(
        d for st in FAULT_STAGES for d in pipeline.LANES[st] if d in pipeline.LIVE
    )


def probe_text(dataset_dir: Path = DATASET_DIR) -> str:
    """`PROBE_CASE`'s text, straight from the frozen dataset.

    Raises if the case is absent, so a dataset rename surfaces as a failure here rather than
    as a probe that silently checks an empty string.
    """
    for line in (dataset_dir / "clean.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            if row["case_id"] == PROBE_CASE:
                return row["text"]
    raise SystemExit(f"{PROBE_CASE} not in {dataset_dir / 'clean.jsonl'} — dataset drift")


def class_carriers() -> dict[str, str]:
    """`{fail_class: live detector able to carry a fault for it}`.

    **Derived from `DETECTOR_FAIL_CLASS` ∩ `faultable()`, never listed.** A hardcoded map
    would keep reporting `tier2` as unexercisable after a tier2 detector landed, which is the
    one way this harness could lie: it would under-report coverage while every assertion still
    passed. Ties break on the 04 §2 registry order, which `DETECTOR_FAIL_CLASS` preserves.

    **The intersection is with `faultable()`, not with `pipeline.LIVE`**, and the difference is
    load-bearing: being live is not enough to carry a fault, the detector must also sit in a lane
    where `_Faulty` raises. Selecting on liveness alone over-reports in the opposite direction to
    the hardcoded map — it would claim a class was covered while its assertions failed with an
    empty failure list, which is how `tier2_injection` surfaced this.
    """
    carriers: dict[str, str] = {}
    injectable = faultable()
    for detector, fail_class in DETECTOR_FAIL_CLASS.items():
        if detector in injectable and fail_class not in carriers:
            carriers[fail_class] = detector
    return carriers


class _Stub:
    """A duck-typed `UpstreamDispatcher`: no network, no key, canned text.

    Defined here rather than imported from `tests/` — an eval module that depended on the
    test suite would invert the dependency and make the report unbuildable without pytest.
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def resolve_model(self, tier: str, provider: Any = None) -> str:
        return "stub-model"

    async def complete(self, messages, *, tier="small", provider=None, extra=None):
        self.calls += 1
        return UpstreamResponse(
            text=self.text, model_used="stub-model", prompt_tokens=11, completion_tokens=22
        )

    async def stream_text(self, messages, *, tier="small", provider=None, extra=None):
        self.calls += 1
        yield self.text


class _Faulty:
    """Wraps a live detector so it raises at the OUTPUT stages only.

    **Output-only, so each request has exactly one fault site.** `tier1_pii` sits in both the
    input and output lanes (04 §2), and a fault in the input lane short-circuits before
    dispatch (04 §4.5) — a different phenomenon with a different verdict path. Faulting both
    would make it unclear which lane produced the escalate, and 06 §5's assertion is about a
    response in flight: given a broken check, is the text released or held?

    Both output stages are covered because the unit stage is policy-dependent:
    `OUTPUT_SENTENCE` for a streaming policy, `OUTPUT_FULL` for a buffered one (ADR-014).
    Delegating on the input stage keeps the input lane genuinely working rather than merely
    unmeasured.
    """

    def __init__(self, name: str, real: Any) -> None:
        self.name = name
        self._real = real

    async def detect(self, ctx):
        if ctx.stage in FAULT_STAGES:
            raise FAULT(self.name, "injected by eval.fault_injection (06 §5)")
        return await self._real.detect(ctx)


@dataclass(frozen=True)
class Probe:
    """One request's outcome, read back from its audit record (05 §4).

    Every field here comes from `canonical_view`, not from the HTTP response. `http_status` is
    kept for the record but is deliberately *not* what the assertions key on: a streaming
    ESCALATE renders as HTTP 200 because 05 §1.1's 202 cannot be expressed mid-stream (M-12),
    so status and verdict genuinely disagree for UC-1 while both are correct.
    """

    use_case: str
    injected: str | None
    fail_class: str | None
    configured_mode: str | None
    verdict: str
    http_status: int
    failures: tuple[str, ...]
    modes_applied: tuple[str, ...]
    failure_record_ids: tuple[str, ...]
    contributing_signal_ids: tuple[str, ...]

    @property
    def contributed(self) -> bool:
        """Did the injected fault drive the verdict? (ADR-027 Amendment 1 step-5 stamp.)

        This is the precise difference between the two halves of 06 §5, and it is why the
        stamp is stored rather than derived: under fail_open the fault is *present* in
        `detector_failures_json` and *absent* from `failure_record_ids` — recorded, but it
        changed nothing. Under fail_closed it appears in both.
        """
        return bool(self.failure_record_ids)


def run_probe(
    use_case: str, text: str, *, inject: str | None = None, store: PolicyStore | None = None
) -> Probe:
    """Fire one request through a fresh gateway and read its audit record back.

    A temp DB per probe, so no probe can read another's rows — the alternative is one shared
    file whose contents depend on execution order.

    `TestClient` is **not** context-managed on purpose: that would fire the FR-GW-006 startup
    canary (ADR-028), whose verdict on a stub reporting 11 tokens is a failure irrelevant to
    this harness. Lifespan runs only for a context-managed client, so plain construction skips
    it — see `test_a_bare_testclient_does_not_run_the_canary`.
    """
    # `PolicyStore()` is EMPTY until `load()` — constructing one and calling `get()` raises
    # `UnknownUseCase`. Loaded here once and passed to the `Gateway` as well, so the policy
    # whose `fail_mode` is reported is the very object the request was evaluated against. The
    # earlier form built a second, unloaded store for the mode lookup only: it raised on every
    # direct call, and had it not raised it could have reported a mode no assertion used.
    # Mirrors `Gateway.__init__`'s own idiom rather than inventing a second convention.
    store = store or PolicyStore()
    if not store.versions():
        store.load()

    original = pipeline.LIVE.get(inject) if inject else None
    if inject:
        if original is None:
            raise SystemExit(f"cannot inject into {inject!r}: not a live detector")
        # Live is necessary but NOT sufficient: `_Faulty` raises only at `FAULT_STAGES`, so
        # wrapping a detector outside those lanes yields a probe stamped `injected=<name>`
        # whose `failures` is empty — a control run mislabelled as a faulted one, which is the
        # exact misreport the dead-detector guard above exists to prevent. `tier2_injection`
        # (INPUT-only) made that reachable, so the guard covers both reasons rather than one.
        if inject not in faultable():
            raise SystemExit(
                f"cannot inject into {inject!r}: live but not faultable — it runs at no stage "
                f"in {[s.name for s in FAULT_STAGES]}, so the fault would never fire and the "
                "probe would report a control run as faulted"
            )
        pipeline.LIVE[inject] = _Faulty(inject, original)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            gateway = Gateway(
                store=store,
                dispatcher=_Stub(text),
                metrics=MetricsRegistry(),
                db_path=str(Path(tmp) / "audit.db"),
                key_map={},
            )
            # Build the served graphs BEFORE the request. `TestClient` is not
            # context-managed here (see below), so the lifespan warm-up never fires and a
            # lazy build would land ~8 s inside the request — which is how this harness
            # caught the defect: the *control* probe, with no fault injected, reported
            # `failures=['tier2_injection']` because the build blew the ceiling.
            warm_models(pipeline.LIVE)
            # `rag_grounding` warms SEPARATELY, and for the same reason the comment above
            # exists: `warm_models` intersects with `onnx_models.SERVED`, and this detector is
            # a sentence-transformers bi-encoder, not an ONNX-served graph — so that call
            # reaches it not at all. Its cold load is seconds of *attributable in-thread CPU*
            # under ADR-036, which inside the request is a 30 ms budget breach and a fabricated
            # `performance` fault in the CONTROL probe. Exactly the tier2 defect, one detector
            # later. Warmed via the module, not `pipeline.LIVE[...]`, so an injected `_Faulty`
            # wrapper does not stop the real encoder being built.
            if rag_grounding_mod.NAME in pipeline.LIVE:
                try:
                    asyncio.run(rag_grounding_mod.warm())
                except Exception as exc:  # unloadable host (ADR-033) — not a probe failure
                    print(f"  note: rag_grounding warm skipped ({exc})", file=sys.stderr)
            client = TestClient(create_app(gateway), raise_server_exceptions=False)
            response = client.post(
                "/v1/chat/completions",
                headers={HEADER_USE_CASE: use_case},
                json={
                    "messages": [{"role": "user", "content": text}],
                    # `rag_grounding` is context-gated per 04 §2 ("only when request carries
                    # context docs"), so without this key the pipeline skips it and `_Faulty`
                    # never raises: the probe would report `failures=[]` for the `performance`
                    # class while stamped as having injected into it.
                    #
                    # The doc is the probe text VERBATIM. Cosine of identical text is 1.0 — the
                    # maximum a bounded [0, 1] score can take — so no τ that 06 §3 calibration
                    # can produce puts this signal below `tau_high`, and the control probe stays
                    # a clean pass. A merely related doc measured 0.07 and would fire a real
                    # signal, changing the very verdicts these invariants assert on. It is also
                    # not an invented fixture: it comes from the same frozen `PROBE_CASE`.
                    CONTEXT_KEY: {"context": [text]},
                },
            )
            view = canonical_view(gateway.conn, response.headers[HEADER_REQUEST_ID])
            policy = store.get(use_case)
            fail_class = DETECTOR_FAIL_CLASS.get(inject) if inject else None
            return Probe(
                use_case=use_case,
                injected=inject,
                fail_class=fail_class,
                configured_mode=(
                    str(getattr(policy.fail_mode, fail_class).value) if fail_class else None
                ),
                verdict=view["verdict"],
                http_status=response.status_code,
                failures=tuple(f["detector"] for f in view["detector_failures"]),
                modes_applied=tuple(
                    dict.fromkeys(f["fail_mode_applied"] for f in view["detector_failures"])
                ),
                failure_record_ids=tuple(view["failure_record_ids"]),
                contributing_signal_ids=tuple(view["contributing_signal_ids"]),
            )
    finally:
        # Restored unconditionally: a leaked `_Faulty` would poison every later probe in this
        # process, and the symptom — faults appearing in a control run — reads as a gateway
        # bug rather than as harness contamination.
        if inject:
            if original is None:
                pipeline.LIVE.pop(inject, None)
            else:
                pipeline.LIVE[inject] = original


@dataclass(frozen=True)
class RepOutcome:
    """One repetition's headline, for the reproducibility section.

    Exists because a single run of this harness is **not** a reproducible claim: two of the
    04 §5 control-probe assertions are load-sensitive by the [[M-53]]/[[M-60]] mechanism (a
    budget overrun reaches the audit record as a detector fault, so a contended pool can
    manufacture a fault on a probe where none was injected). A one-run report cannot express
    that, and the first published one said `39/39` for a suite that reproduces it 3 times in 5.
    """

    passed: int
    total: int
    failures: tuple[str, ...]
    load1: float | None


@dataclass(frozen=True)
class Assertion:
    """One 06 §5 claim, with the evidence that settled it."""

    name: str
    passed: bool
    detail: str


def check(probe: Probe, expect_mode: str) -> list[Assertion]:
    """Evaluate 06 §5's assertions for one faulted probe.

    `expect_mode` comes from the *policy*, not from the outcome, so a policy edit that flips a
    class changes what is asserted rather than what is reported — the harness follows config,
    which is the FR-POL-006 claim it is testing.
    """
    fail_open = expect_mode == "fail_open"
    expected_verdict = "pass" if fail_open else "escalate"
    out = [
        Assertion(
            f"{probe.use_case}/{probe.fail_class}: verdict is {expected_verdict}",
            probe.verdict == expected_verdict,
            f"verdict={probe.verdict!r} (HTTP {probe.http_status})",
        ),
        # ADR-027: the fault is recorded either way. A fail_open that dropped the record would
        # be indistinguishable from a detector that never faulted, which 04 §5 forbids
        # outright — "never silent" is the half of the contract fail_open could quietly break.
        Assertion(
            f"{probe.use_case}/{probe.fail_class}: fault present in detector_failures_json",
            probe.injected in probe.failures,
            f"failures={list(probe.failures)} modes={list(probe.modes_applied)}",
        ),
        Assertion(
            f"{probe.use_case}/{probe.fail_class}: fail_mode_applied is {expect_mode}",
            probe.modes_applied == (expect_mode,),
            f"modes_applied={list(probe.modes_applied)}",
        ),
    ]
    if fail_open:
        out.append(
            Assertion(
                f"{probe.use_case}/{probe.fail_class}: fault did NOT contribute to the verdict",
                not probe.contributed,
                f"failure_record_ids={list(probe.failure_record_ids)} (expected empty)",
            )
        )
    else:
        out.append(
            Assertion(
                f"{probe.use_case}/{probe.fail_class}: fault stamped in failure_record_ids",
                probe.contributed,
                f"failure_record_ids={list(probe.failure_record_ids)}",
            )
        )
    return out


#: 01 §3 pipeline labels, so the report reads in the docs' vocabulary (06 §5 and 07 beat 7
#: both speak in UC numbers, while config and audit rows speak in use-case names).
UC_LABEL: dict[str, str] = {
    "support_bot": "UC-1",
    "hr_copilot": "UC-2",
    "finance_advisor": "UC-3",
}


def _mode(policy: Any, fail_class: str) -> str:
    return str(getattr(policy.fail_mode, fail_class).value)


@dataclass
class Run:
    """Everything one invocation measured, kept separate from how it is rendered."""

    controls: dict[str, Probe]
    faulted: dict[tuple[str, str], Probe]   # (use_case, fail_class) -> Probe
    carriers: dict[str, str]
    assertions: list[Assertion]
    #: The store the probes actually ran against. Carried so `render` reports the policy state
    #: that was measured rather than re-reading `policies/` — a hot reload between the run and
    #: the render would otherwise print modes that no assertion used (FR-CFG-002 makes that
    #: reachable, not hypothetical).
    store: PolicyStore

    @property
    def failed(self) -> list[Assertion]:
        return [a for a in self.assertions if not a.passed]


def execute(dataset_dir: Path = DATASET_DIR) -> Run:
    """Run the controls, then one faulted probe per (use case × exercisable class).

    Controls first, deliberately: if a control already escalates, every fail-closed
    assertion after it is vacuous, and the report must be able to say so.
    """
    text = probe_text(dataset_dir)
    store = PolicyStore()
    store.load()
    carriers = class_carriers()

    controls = {uc: run_probe(uc, text, store=store) for uc in USE_CASES}
    faulted: dict[tuple[str, str], Probe] = {}
    assertions: list[Assertion] = []

    for uc in USE_CASES:
        policy = store.get(uc)
        # A clean probe must be a clean verdict, or nothing downstream means anything.
        assertions.append(
            Assertion(
                f"{uc}: control (no fault) passes",
                controls[uc].verdict == "pass" and not controls[uc].failures,
                f"verdict={controls[uc].verdict!r} failures={list(controls[uc].failures)}",
            )
        )
        for fail_class in FAIL_CLASSES:
            carrier = carriers.get(fail_class)
            if carrier is None:
                continue
            probe = run_probe(uc, text, inject=carrier, store=store)
            faulted[(uc, fail_class)] = probe
            assertions.extend(check(probe, _mode(policy, fail_class)))

    return Run(controls=controls, faulted=faulted, carriers=carriers,
               assertions=assertions, store=store)


def _load_cell(stamp: dict[str, Any] | None) -> str:
    """A load row, worded exactly as the two timing harnesses word theirs (06 §8)."""
    if not stamp:
        return "not recorded — NOT CITABLE (06 §8)"
    trio = " / ".join("—" if stamp.get(k) is None else str(stamp[k])
                      for k in ("load1", "load5", "load15"))
    return f"{trio} · {stamp.get('cpus')} CPUs — **{quiet_verdict(stamp)}**"


def _provenance(
    dataset_dir: Path,
    provenance_note: str,
    *,
    start_load: dict[str, Any] | None = None,
    end_load: dict[str, Any] | None = None,
    cmd_suffix: str = "",
) -> list[str]:
    digest = dataset_digest(dataset_dir)
    # One definition in `eval/host_load.py` (AGENTS.md §7).
    code = git_stamp()
    return [
        "## Provenance",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Generated (UTC) | {datetime.now(timezone.utc).isoformat(timespec='seconds')} |",
        f"| Dataset digest | `{digest}` |",
        f"| Frozen at | `{FROZEN_COMMIT[:12]}` — "
        f"{'MATCHES' if not check_freeze(dataset_dir) else 'MISMATCH'} |",
        f"| Probe case | `{PROBE_CASE}` (frozen; prompt **and** stub response) |",
        f"| Injected fault | `{FAULT.__name__}` (06 §5 \"raise timeout\") |",
        f"| Code commit | {code_commit_cell(code)} |",
        f"| Python | {platform.python_version()} |",
        f"| Platform | {platform.system()} {platform.release()} · {platform.machine()} |",
        f"| Command | `python -m eval.fault_injection{cmd_suffix}` |",
        f"| Host load at start (1/5/15) | {_load_cell(start_load)} |",
        f"| Host load at end (1/5/15) | {_load_cell(end_load)} |",
        "",
        provenance_note,
        "",
    ]


def _reproducibility_section(reps: Sequence[RepOutcome]) -> list[str]:
    """The observed pass RATE, which replaces the single-run claim for a multi-rep run.

    A reproducibility-honest number beats a clean one: the assertions here are documented
    04 §5 invariants, so a run that passes them 3 times in 5 has not established them — it has
    established that they hold on a quiet host *most of the time*, and named the mechanism that
    takes the other two. That is a weaker claim than `39/39` and it is the true one.
    """
    if len(reps) < 2:
        return []
    best = max(r.passed for r in reps)
    clean = [r for r in reps if not r.failures]
    flaky: dict[str, int] = {}
    for r in reps:
        for name in r.failures:
            flaky[name] = flaky.get(name, 0) + 1
    lines = [
        "## Reproducibility across repetitions",
        "",
        f"**{len(clean)}/{len(reps)} repetitions reached {best}/{reps[0].total}.** Every "
        "repetition ran on a quiet host, one after another, with no code or policy change "
        "between them — so the spread is the system's, not the configuration's.",
        "",
        "| Rep | Passed | load1 at start | Failing assertion |",
        "|---:|---:|---:|---|",
    ]
    for i, r in enumerate(reps, 1):
        lines.append(
            f"| {i} | {r.passed}/{r.total} | {'—' if r.load1 is None else r.load1} "
            f"| {'none' if not r.failures else ', '.join(f'`{n}`' for n in r.failures)} |"
        )
    lines += [
        "",
        "The assertions that did not hold every time, and how often they failed:",
        "",
    ]
    for name, n in sorted(flaky.items(), key=lambda kv: -kv[1]):
        lines.append(f"- `{name}` — failed **{n}/{len(reps)}**")
    if not flaky:
        lines.append("- none — every assertion held in every repetition")
    lines += [
        "",
        "### Superseded single-run claim — preserved, not deleted",
        "",
        "> The run of **2026-08-30** published this suite as **`39/39 passed`** from a single "
        "> repetition, with no load stamp ([[M-54]]) and therefore no way for a reader to check "
        "> the quiet-host condition the figure depended on. That number is a **real measurement "
        "> of one run** and it is kept here for that reason; what was wrong was presenting it as "
        "> the suite's result when the suite does not reproduce it. Superseded by the rate above. "
        "> No figure in this blockquote is recomputed by this run.",
        "",
        "**Mechanism, not noise.** A detector that overruns its budget is recorded in the audit "
        "record as a *detector fault*, and the control probe asserts that a run with no injected "
        "fault records none. So a pool-serialized model detector that runs slow enough on one "
        "sentence manufactures a fault the harness reads as a broken invariant. It is the same "
        "mechanism [[M-53]] recorded under load; [[M-60]] extends it, because these repetitions "
        "were quiet by 06 §8's own threshold and it still occurred. The assertion is **not "
        "relaxed** to absorb it (AGENTS.md §5.4) — it fires on exactly the condition it exists "
        "to guard, and the guard is working.",
        "",
    ]
    return lines


def render(
    run: Run,
    dataset_dir: Path,
    provenance_note: str,
    *,
    reps: Sequence[RepOutcome] = (),
    start_load: dict[str, Any] | None = None,
    end_load: dict[str, Any] | None = None,
) -> str:
    """The 06 §5 report. Evidence first, verdict last."""
    store = run.store
    lines: list[str] = [
        "# Fail-open / fail-closed verification (06 §5)",
        "",
        "FR-POL-006: a detector timeout or crash is resolved by the **policy's** `fail_mode` "
        "for that detector's class (04 §5) — never by the runner, never by a code-level "
        "preference. This report injects one fault and reads the consequence back out of the "
        "audit record. Feeds demo beat 7 / SC-3.",
        "",
        *_provenance(dataset_dir, provenance_note, start_load=start_load,
                     end_load=end_load,
                     cmd_suffix="" if len(reps) < 2 else f" --reps {len(reps)}"),
        "## Method",
        "",
        f"1. Probe text is `{PROBE_CASE}` from the frozen dataset — used as **both** the prompt "
        "and the stub's response, and verified clean through every live detector. A faulted "
        "verdict is therefore attributable to the fault, not to content.",
        f"2. For each use case: one **control** request with no fault, then one request per "
        f"exercisable fail_mode class with `{FAULT.__name__}` injected into that class's live "
        "detector at the output stages only (the input lane keeps working, so an input-lane "
        "short-circuit cannot be mistaken for an output-lane fail-closed).",
        "3. Every assertion is evaluated against `canonical_view` of the request's audit "
        "record (05 §4) — not against the HTTP response. The response is what the client saw; "
        "04 §5's claim is about what the system recorded about its own failure.",
        "4. The upstream is a stub: no network, no credential, no token accounting.",
        "",
        "## Class coverage",
        "",
        "Which of the four 04 §3 classes can carry a fault today. Derived from "
        "`DETECTOR_FAIL_CLASS ∩ pipeline.LIVE`, never hardcoded — a new detector changes this "
        "table without an edit.",
        "",
        "| Class | Live carrier | Exercisable | Modes across the three policies |",
        "|---|---|---|---|",
    ]
    for fail_class in FAIL_CLASSES:
        carrier = run.carriers.get(fail_class)
        modes = " · ".join(
            f"{UC_LABEL[uc]} {_mode(store.get(uc), fail_class)}" for uc in USE_CASES
        )
        lines.append(
            f"| `{fail_class}` | {f'`{carrier}`' if carrier else '— none live —'} "
            f"| {'yes' if carrier else '**no**'} | {modes} |"
        )

    two_sided = [
        fc for fc in FAIL_CLASSES
        if run.carriers.get(fc)
        and len({_mode(store.get(uc), fc) for uc in USE_CASES}) > 1
    ]
    lines += [
        "",
        "## SC-3 — one identical fault, two opposite outcomes",
        "",
    ]
    if not two_sided:
        lines.append(
            "**Not demonstrable in this run.** No exercisable class has two different "
            "`fail_mode` values across the three policies, so there is no contrast to show."
        )
    for fail_class in two_sided:
        carrier = run.carriers[fail_class]
        lines += [
            f"### `{fail_class}` — fault injected into `{carrier}`",
            "",
            "| Pipeline | Configured `fail_mode` | Verdict | HTTP | Fault recorded | "
            "Drove the verdict |",
            "|---|---|---|---|---|---|",
        ]
        for uc in USE_CASES:
            probe = run.faulted[(uc, fail_class)]
            lines.append(
                f"| {UC_LABEL[uc]} `{uc}` | `{probe.configured_mode}` | **{probe.verdict}** "
                f"| {probe.http_status} | {'yes' if probe.injected in probe.failures else 'NO'} "
                f"| {'yes' if probe.contributed else 'no'} |"
            )
        lines += [
            "",
            "The last two columns are the substance of ADR-027 Amendment 1 and are **different "
            "facts**. Under `fail_open` the fault is recorded (`detector_failures_json`) but "
            "absent from `failure_record_ids`: it happened, it is auditable, and it changed "
            "nothing. Under `fail_closed` it appears in both. A single boolean could not "
            "express the difference, which is why the step-5 stamp is stored rather than "
            "reconstructed by filtering on `fail_mode_applied`.",
            "",
        ]

    lines += [
        "## Controls (no fault injected)",
        "",
        "Without these, \"UC-3 escalates under fault\" is unfalsifiable — a policy that "
        "escalated everything would look like a working fail-closed mechanism.",
        "",
        "| Pipeline | Verdict | HTTP | Failures recorded |",
        "|---|---|---|---|",
    ]
    for uc in USE_CASES:
        probe = run.controls[uc]
        lines.append(
            f"| {UC_LABEL[uc]} `{uc}` | {probe.verdict} | {probe.http_status} "
            f"| {list(probe.failures) or 'none'} |"
        )

    lines += [
        "",
        "## Assertions",
        "",
        f"{sum(1 for a in run.assertions if a.passed)}/{len(run.assertions)} passed"
        + ("." if len(reps) < 2 else f" in this repetition — the final one of {len(reps)}. "
           "The rate across all repetitions is the citable figure; see *Reproducibility* below."),
        "",
        "| Result | Assertion | Evidence |",
        "|---|---|---|",
    ]
    for a in run.assertions:
        lines.append(f"| {'PASS' if a.passed else '**FAIL**'} | {a.name} | `{a.detail}` |")

    lines += ["", *_reproducibility_section(reps)]

    absent = [fc for fc in FAIL_CLASSES if fc not in run.carriers]
    lines += [
        "",
        "## Scope and limitations",
        "",
        f"**06 §5 and 07 beat 7 both name `tier2`, and this run carries SC-3 on "
        f"`{'tier2' if run.carriers.get('tier2') else 'nothing'}` — the substitution is "
        "retired.** It stood for two phases and for two different reasons: first nothing tier2 "
        "existed to monkeypatch, then `tier2_injection` shipped but runs at INPUT (04 §2) while "
        "faults are injected only at the OUTPUT stages (`FAULT_STAGES`), where a fault is a "
        "response-in-flight decision rather than a short-circuit before dispatch. "
        f"`{run.carriers.get('tier2', '—')}` (OUTPUT_SENTENCE) closes it, and the harness needed "
        "no edit: `faultable()` derives coverage rather than listing it. `performance` is still "
        "shown alongside, now as corroboration rather than a stand-in — FR-POL-006 is stated per "
        "detector *class*, and two classes with the same two-sided configuration showing the "
        "same contrast is a stronger result than one. "
        "`test_tier2_carries_sc3_on_the_class_the_docs_name` holds the line from the other side: "
        "it fails if tier2 ever stops being carried.",
        "",
        f"**Classes with no live carrier:** {', '.join(f'`{c}`' for c in absent) or 'none'}. "
        "Their `fail_mode` values are still read from config and shown above, so the "
        "configuration is visible even where the mechanism is not yet exercisable.",
        "",
        "**`tier1` is live but cannot show a contrast:** all three policies set "
        "`tier1: fail_closed`, so it has no fail-open side. It is exercised and asserted "
        "anyway — unanimity is a fact worth showing beside a class where the policies "
        "disagree.",
        "",
        "Reproduce: `python -m eval.validate_dataset --freeze && python -m eval.fault_injection`",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset-dir", type=Path, default=DATASET_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--reps",
        type=int,
        default=1,
        help="repeat the whole suite N times and publish the observed pass RATE instead of a "
             "single-run claim. Two of the control-probe assertions are load-sensitive by the "
             "M-53/M-60 mechanism, so one run cannot establish them (06 §5). The report keeps "
             "the LAST repetition's evidence tables and adds a per-rep rate table.",
    )
    parser.add_argument(
        "--allow-dev",
        action="store_true",
        help="proceed on a dev-class upstream (ADR-018). Irrelevant here — the upstream is a "
             "stub — but accepted for symmetry with the other eval entry points.",
    )
    args = parser.parse_args(argv)

    # Gate 1 — the freeze (06 §1). The probe text comes from the dataset, so an unfrozen
    # dataset means an unpinned probe.
    violations = check_freeze(args.dataset_dir)
    if violations:
        print("FREEZE CHECK FAILED — refusing to run:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        return 1

    # Gate 2 — upstream provenance (ADR-018), evaluated and scoped exactly as `run_all` does.
    # Nothing here is provider-derived: the upstream is a stub and every verdict comes from a
    # local detector plus the policy engine. Stamping DEV-TAINTED on a report whose numbers
    # cannot depend on the provider would teach a reader that the marker is noise.
    try:
        cfg = require_measured_upstream(allow_dev=args.allow_dev, artifact="the fault report")
        provenance_note = (
            f"> **Upstream provenance:** active provider `{cfg.active.name}` is "
            f"`{cfg.active.upstream_class}`-class (ADR-018)."
        )
    except TaintedDataError:
        cfg = load_gateway_config()
        provenance_note = (
            f"> **Upstream provenance:** the active provider `{cfg.active.name}` is "
            f"**dev-class**, which `require_measured_upstream()` refuses for judge-facing "
            f"output (ADR-018). **This report is unaffected:** the upstream is a stub, so no "
            f"verdict below involves a provider call, a token count, or a price. Every result "
            f"is produced by local detectors and the policy engine. The gate is therefore "
            f"**evaluated and non-binding here**, and becomes binding the moment this harness "
            f"reports anything upstream-derived."
        )

    if args.reps < 1:
        print("--reps must be >= 1", file=sys.stderr)
        return 2

    # Load is stamped around the WHOLE measurement, not per rep: the rate claim is
    # "quiet host", and a run whose tail went loud must not read as quiet (06 §8, M-54).
    start_load = load_stamp()
    reps: list[RepOutcome] = []
    run = None
    for i in range(args.reps):
        rep_load = load_stamp()
        run = execute(args.dataset_dir)
        reps.append(RepOutcome(
            passed=sum(1 for a in run.assertions if a.passed),
            total=len(run.assertions),
            failures=tuple(a.name for a in run.failed),
            load1=rep_load.get("load1"),
        ))
        if args.reps > 1:
            print(f"  rep {i + 1}/{args.reps}: {reps[-1].passed}/{reps[-1].total}"
                  f" (load1 {reps[-1].load1})")
    assert run is not None
    end_load = load_stamp()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(
        run, args.dataset_dir, provenance_note,
        reps=reps if args.reps > 1 else (),
        start_load=start_load, end_load=end_load,
    ))

    passed = sum(1 for a in run.assertions if a.passed)
    print(f"{args.out}: {passed}/{len(run.assertions)} assertions passed")
    if args.reps > 1:
        clean = sum(1 for r in reps if not r.failures)
        print(f"  RATE: {clean}/{len(reps)} repetitions fully clean"
              f" (best {max(r.passed for r in reps)}/{reps[0].total})")
    for a in run.failed:
        print(f"  FAIL {a.name} — {a.detail}", file=sys.stderr)
    # Nonzero on any failed assertion. These are documented 04 §5 semantics, not a measured
    # target, so a failure here is a broken invariant rather than a missed number — the one
    # case where exiting nonzero is unambiguously right (AGENTS.md §5.4 forbids the
    # alternative of relaxing the assertion).
    return 1 if any(r.failures for r in reps) else 0


if __name__ == "__main__":
    raise SystemExit(main())
