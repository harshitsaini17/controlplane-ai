"""Detector + policy evaluation -> reports/eval_report.md.

Implements 06 §3 as far as the implemented components allow, and **reports the rest as not
computed rather than computing it badly**. Satisfies NFR-EVAL-001/002 for the detectors that
exist today.

Three rules govern every number this module emits (AGENTS.md §7):

1. **Measured or absent.** A detector that does not exist is listed as SKIPPED with its
   reason. It never contributes a 0.0, and it never contributes a 1.0.
2. **An empty denominator is not a score.** A label with no positive cases yields recall
   `n/a`, not 1.0. `security.blocklist` is exactly that case (Q-15) and is the reason this
   rule is stated first-class instead of left implicit.
3. **Provenance travels with the output.** The dataset digest, the freeze commit, the
   toolchain and the hardware are stamped into the report, so a number can always be traced
   to the state that produced it.

The policy-level 4x4 confusion matrix of 06 §3 is **deliberately not computed** — see
`_policy_section` for why computing it today would be circular rather than merely premature.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from controlplane.detectors._v1_numeric_claims import numeric_claims as v1_numeric_claims
from controlplane.detectors._v1_tier1_patterns import tier1_pii as v1_tier1_pii
from controlplane.detectors.availability import probe_availability
from controlplane.detectors import entity_enricher
from controlplane.detectors.base import DetectorContext, Signal, Stage
from controlplane.detectors.numeric_claims import numeric_claims
from controlplane.detectors.tier1_patterns import tier1_blocklist, tier1_pii
from controlplane.gateway.config import (
    TaintedDataError,
    load_gateway_config,
    require_measured_upstream,
    taint_output_path,
)
from controlplane.policy.schema import Policy
from eval.policy_matrix import (
    ConfusionMatrix,
    conformance_matrices,
    covered_cases,
    end_to_end_matrices,
    reconcile,
    render_matrix,
)
from eval.host_load import git_stamp
from eval.validate_dataset import (
    DATASET_DIR,
    FROZEN_COMMIT,
    USE_CASES,
    check_freeze,
    dataset_digest,
    load_policies,
)

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
DEFAULT_OUT = REPORTS_DIR / "eval_report.md"

#: Stage a case's `kind` maps to (06 §2.1). `output` scores at `output_sentence`: that is
#: the stage 04 §2 lists for all three implemented detectors, and it is the granularity
#: FR-GW-002 actually intercepts at.
_KIND_STAGE = {"input": Stage.INPUT, "output": Stage.OUTPUT_SENTENCE}


@dataclass(frozen=True)
class DetectorUnderTest:
    """One scorable detector: what it emits, and where it is allowed to run.

    `scope` is the detector's own slice of the 04 §1.1 taxonomy. Scoring is restricted to
    it in both directions — a `toxicity.high` case is neither a miss nor a false positive
    for `tier1_pii`, it is simply not that detector's question. Without this, every
    detector's recall would be diluted by every label it was never meant to emit.
    """

    name: str
    detector: Any
    scope: frozenset[str]
    stages: frozenset[Stage]
    note: str = ""
    #: `v1` = the blind first-contact implementation, frozen; `v2` = post-revision
    #: (ADR-026 §1). Both are scored by the same loop so the columns are comparable.
    variant: str = "v2"


@dataclass
class SkippedDetector:
    """A 04 §2 row that is reported but never scored (rule 1).

    Three distinct reasons reach this type, and the `reason` string is the only place the
    difference survives into the table: **no implementation** (a stub), **implemented but
    unloadable on this host** (ADR-033 state (c), built by `_demote_unloadable`), and
    **implemented and loadable but unreachable by any corpus case** (`entity_enricher` —
    its host-signal producer is absent). Scoring any of the three would publish a
    precision/recall of 0.0 for a detector that was never asked a question.
    """

    name: str
    labels: tuple[str, ...]
    reason: str


IMPLEMENTED: tuple[DetectorUnderTest, ...] = (
    DetectorUnderTest(
        name="tier1_pii",
        detector=tier1_pii,
        # `pii.person_data` is excluded deliberately: no 04 §2 row says how to detect it and
        # it has zero corpus cases (Q-16). Including it would add an all-zero row that looks
        # like a failure rather than an absence.
        scope=frozenset(
            {"pii.ssn", "pii.credit_card", "pii.email", "pii.phone", "pii.api_key"}
        ),
        stages=frozenset({Stage.INPUT, Stage.OUTPUT_SENTENCE}),
    ),
    DetectorUnderTest(
        name="tier1_blocklist",
        detector=tier1_blocklist,
        scope=frozenset({"security.blocklist"}),
        stages=frozenset({Stage.INPUT, Stage.OUTPUT_SENTENCE}),
        note=(
            "Emits nothing on the shipped policies: `blocklist_extra` is its only documented "
            "term source (Q-15) and all three ship it empty. The corpus has no "
            "`security.blocklist` positives either, so recall is **undefined, not 1.0** "
            "(rule 2)."
        ),
    ),
    DetectorUnderTest(
        name="numeric_claims",
        detector=numeric_claims,
        scope=frozenset({"hallucination.unsourced_numeric"}),
        stages=frozenset({Stage.OUTPUT_SENTENCE}),
        note=(
            # PROSE ONLY (ADR-026 Amendment 2). This string is rendered into the report and
            # read by nothing that scores; correcting it cannot move a figure. It previously
            # claimed a Q-18 publication gate that ADR-025 had already lifted.
            "The 'citation marker' list this detector suppresses on is **normative** in "
            "04 §2.4.2 — ADR-025 closed **Q-18**, and its Amendment 1 restricts `per` to "
            "attribution forms. It is lexical only, searched in the numeral's own sentence: "
            "judging whether a citation *supports* a figure is `rag_grounding`'s job, not "
            "this detector's. The figures below are publishable provided they are labelled "
            "v1 or v2 (06 §3.2) — see *Disclosed revision* below."
        ),
    ),
)

#: The frozen v1 detectors, re-scored every run so the permanent v1 numbers stay
#: **reproducible** rather than transcribed (ADR-026 §1).
#:
#: This is the whole reason `_v1_*.py` exists as runnable code. A v1 figure quoted from a
#: previous report would be unverifiable, and AGENTS.md §7 requires every judge-facing number
#: to be reproducible by a command in this repo — so the baseline is *computed*, not copied.
#: The modules are byte-identical to their source commit and carry a DO-NOT-EDIT banner.
#:
#: Only the two revised detectors appear here. `tier1_blocklist` was never revised, so a v1
#: column for it would restate the v2 column and imply a comparison that was never made.
V1_BASELINE: tuple[DetectorUnderTest, ...] = (
    DetectorUnderTest(
        name="tier1_pii",
        detector=v1_tier1_pii,
        scope=frozenset(
            {"pii.ssn", "pii.credit_card", "pii.email", "pii.phone", "pii.api_key"}
        ),
        stages=frozenset({Stage.INPUT, Stage.OUTPUT_SENTENCE}),
        variant="v1",
    ),
    DetectorUnderTest(
        name="numeric_claims",
        detector=v1_numeric_claims,
        scope=frozenset({"hallucination.unsourced_numeric"}),
        stages=frozenset({Stage.OUTPUT_SENTENCE}),
        variant="v1",
    ),
)


#: 04 §2 registry name of the enrichment stage, from the module that implements it.
ENRICHER_NAME = entity_enricher.NAME


def _enricher_reason() -> str:
    """Why `entity_enricher` is reported and not scored — read from this host, not typed.

    Two host configurations give two true answers, and the earlier single hand-written
    string ("not implemented — stub") went false the moment the stage landed while still
    rendering into `reports/eval_report.md`. That is the M-42/M-43 class — a claim
    described by a premise it no longer comes from — in a judge-facing generator, so the
    string is derived from the same probe every other row's comes from.

    Carries no figures deliberately. The count of unscored positives is computed by the
    report itself from `label_counts`; a number written into this sentence would be a
    second, unverifiable copy of it (AGENTS.md §7).
    """
    missing = probe_availability([ENRICHER_NAME])
    if missing:
        return (
            f"**implemented but unloadable on this host** — missing "
            f"`{missing[0].missing}` (ADR-033 state (c)). Not scored: a stage that could "
            f"not load answers no question"
        )
    return (
        "**implemented and loadable; not reachable by any corpus case** — 04 §2.2 appends "
        "`privacy.person` to a span-bearing `hallucination.*` host signal, and every "
        "corpus case carrying that label expects `hallucination.ungrounded_claim`, whose "
        "only producer (`rag_grounding`) is absent. Landing this stage therefore widens "
        "the end-to-end scorable set by nothing, and it emits on no scorable case — both "
        "measured, not assumed (M-44)"
    )


SKIPPED: tuple[SkippedDetector, ...] = (
    SkippedDetector("tier2_injection", ("security.prompt_injection",),
                    "not implemented — stub; Q-04 defers the checkpoint choice"),
    SkippedDetector("tier2_toxicity", ("toxicity.high", "toxicity.moderate"),
                    "not implemented — stub; Q-04 defers the checkpoint choice"),
    SkippedDetector("fast_consistency", ("hallucination.low_confidence",),
                    "not implemented — stub; the 2nd-sample provider is bound "
                    "(Q-10 resolved 2026-08-28), the detector is not"),
    SkippedDetector("rag_grounding", ("hallucination.ungrounded_claim",),
                    "not implemented — stub; needs sentence-transformers"),
    # Reason deferred to `_enricher_reason()`: the row was "not implemented — stub" until
    # the stage landed, and a hand-typed string cannot be right on both an ml-bearing and
    # an ml-less host. It stays in SKIPPED rather than becoming a `DetectorUnderTest`
    # because `_run` calls `detect(ctx)` and enrichment's entry point is
    # `enrich(signals, text, ...)` — giving it a `detect` to be scorable would be a type
    # lie, and it would still score 0.0 over an empty denominator.
    SkippedDetector("entity_enricher", ("privacy.person",), _enricher_reason()),
    SkippedDetector("conv_tracker", ("conversation.cumulative_risk",),
                    "not implemented — stub (ADR-021 scope is specified, code is not)"),
    SkippedDetector("cost_budget", ("cost.budget_exceeded", "cost.request_too_large"),
                    "not implemented — stub; the cost plane needs a priced provider"),
    SkippedDetector("loop_guard", ("cost.loop_detected",),
                    "not implemented — stub"),
)


#: `{detector: missing dependency}` on THIS host, from ADR-033's single declaration.
#: Probed once per process: `find_spec` is deterministic, and re-probing per case would ask
#: the same question a few thousand times.
UNLOADABLE: dict[str, str] = {
    entry.detector: entry.missing
    for entry in probe_availability(
        # `entity_enricher` is included although it is in neither list: 04 §2.2 makes
        # enrichment its own stage, so it is not a `DetectorUnderTest` (it has no
        # `detect`), yet its row still has to say whether *this* host could load it.
        # Probing it here keeps that answer in the same single declaration as every
        # other row's rather than hand-typing it beside a `REQUIREMENTS` entry.
        [dut.name for dut in (*IMPLEMENTED, *V1_BASELINE)] + [ENRICHER_NAME]
    )
}


def _demote_unloadable() -> tuple[
    tuple[DetectorUnderTest, ...], tuple[DetectorUnderTest, ...], tuple[SkippedDetector, ...]
]:
    """Partition the implemented detectors by whether this host can load them (ADR-033).

    This is rule 1 ("measured or absent") applied to a case it did not originally have a
    word for. A detector whose dependency is absent produces no signals, so scoring it
    would emit precision/recall of 0.0 — a **fabricated failing number** for a detector
    that was never asked a question. Reporting it beside the stubs is the honest handling,
    with one difference that has to survive into the table: its reason is a missing
    dependency, not a missing implementation.

    The reason string is built from the probe rather than typed, which is the "consumes the
    same state" part of the ruling. A hand-written "needs sentence-transformers" beside a
    `REQUIREMENTS` entry naming the same module is two declarations that can disagree, and
    the one in prose is the one nobody updates.
    """
    scored, demoted = [], []
    for dut in IMPLEMENTED:
        if dut.name in UNLOADABLE:
            demoted.append(dut)
        else:
            scored.append(dut)
    baselines = tuple(d for d in V1_BASELINE if d.name not in UNLOADABLE)
    rows = tuple(
        SkippedDetector(
            dut.name,
            tuple(sorted(dut.scope)),
            f"**implemented but unloadable on this host** — missing `{UNLOADABLE[dut.name]}` "
            f"(ADR-033 state (c)). Not scored: a detector that could not load answers no "
            f"question, and 0.0 would read as a failing detector",
        )
        for dut in demoted
    )
    return tuple(scored), baselines, rows


SCORED, SCORED_V1, DEMOTED = _demote_unloadable()


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


@dataclass
class LabelScore:
    """Case-level confusion for one label, per 06 §3 ("confusion listed per label")."""

    label: str
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def support(self) -> int:
        """Positive cases for this label — the recall denominator."""
        return self.tp + self.fn

    @property
    def precision(self) -> float | None:
        """None when nothing was predicted: undefined, not 1.0 (rule 2)."""
        predicted = self.tp + self.fp
        return self.tp / predicted if predicted else None

    @property
    def recall(self) -> float | None:
        """None when the label has no positive cases (rule 2)."""
        return self.tp / self.support if self.support else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or p + r == 0:
            return None
        return 2 * p * r / (p + r)


@dataclass
class DetectorResult:
    name: str
    note: str
    variant: str = "v2"
    cases_scored: int = 0
    cases_out_of_stage: int = 0
    labels: dict[str, LabelScore] = field(default_factory=dict)
    #: case_id -> (expected, got) for every disagreement. Listed in the report: an
    #: aggregate with no examples cannot be acted on.
    misses: list[tuple[str, str]] = field(default_factory=list)
    false_positives: list[tuple[str, str]] = field(default_factory=list)

    def score(self, label: str) -> LabelScore:
        return self.labels.setdefault(label, LabelScore(label))

    @property
    def micro(self) -> LabelScore:
        """Micro-averaged over the detector's own scope."""
        total = LabelScore("micro")
        for s in self.labels.values():
            total.tp += s.tp
            total.fp += s.fp
            total.fn += s.fn
        return total


def _fmt(value: float | None, *, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


# --------------------------------------------------------------------------
# Dataset
# --------------------------------------------------------------------------


def load_cases(dataset_dir: Path = DATASET_DIR) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(dataset_dir.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if line.strip():
                case = json.loads(line)
                case["_file"] = path.name
                cases.append(case)
    return cases


async def _run(dut: DetectorUnderTest, case: dict[str, Any]) -> list[Signal]:
    ctx = DetectorContext(
        text=case.get("text", ""),
        stage=_KIND_STAGE[case["kind"]],
        context_docs=list(case.get("context") or []),
    )
    return await dut.detector.detect(ctx)


#: Every label an implemented detector can emit — the coverage test for the end-to-end
#: matrix. Derived from the `IMPLEMENTED` scopes rather than restated, so landing a detector
#: widens the matrix automatically and cannot drift from what is actually scored.
#: `SCORED`, not `IMPLEMENTED`: on a host missing a dependency the end-to-end matrix must
#: not claim to cover labels no detector can emit this run (ADR-033).
IMPLEMENTED_LABELS: frozenset[str] = frozenset(
    label for dut in SCORED for label in dut.scope
)


def collect_emissions(cases: Sequence[dict[str, Any]]) -> dict[str, list[Signal]]:
    """case_id -> the signals the SHIPPING detectors actually emitted (06 §3.3, end-to-end).

    v1 baselines are excluded deliberately: the end-to-end matrix describes the system as it
    ships, and mixing a frozen baseline into it would report a verdict no deployment can
    produce.
    """
    emissions: dict[str, list[Signal]] = {}
    for case in cases:
        stage = _KIND_STAGE[case["kind"]]
        signals: list[Signal] = []
        for dut in SCORED:
            if stage not in dut.stages:
                continue
            signals.extend(asyncio.run(_run(dut, case)))
        emissions[case["case_id"]] = signals
    return emissions


def detection_failure_case_ids(
    results: Sequence[DetectorResult],
) -> tuple[set[str], set[str]]:
    """Cases where a SHIPPING detector missed a label, or emitted one it should not have.

    Returned as `(missed, false_positive)` rather than a union: a masked miss and a masked
    false positive are hidden from the verdict by different mechanisms, and the
    reconciliation reports them separately instead of blurring both into one count.
    """
    missed: set[str] = set()
    false_positive: set[str] = set()
    for result in results:
        if result.variant != "v2":
            continue
        missed.update(case_id for case_id, _ in result.misses)
        false_positive.update(case_id for case_id, _ in result.false_positives)
    return missed, false_positive


def evaluate(cases: Sequence[dict[str, Any]]) -> tuple[list[DetectorResult], int]:
    """Score every implemented detector. Returns (results, conversation cases excluded).

    **Conversation-kind cases are excluded from per-detector scoring**, and the exclusion is
    a correctness requirement rather than a shortcut. ADR-021 labels a multi-turn case *per
    breach unit* — the breaching turn's own labels — while the case text holds every turn,
    user turns included. Scanning the whole text would surface PII the ground truth
    deliberately does not list, scoring real false positives against a convention that
    excluded them by design. Which turn breached is not a field, so it cannot be recovered
    mechanically; the honest handling is to exclude and say so with the count.
    """
    scored = (*SCORED, *SCORED_V1)
    results = [
        DetectorResult(name=d.name, note=d.note, variant=d.variant) for d in scored
    ]
    excluded = sum(1 for c in cases if c["kind"] == "conversation")

    for dut, result in zip(scored, results):
        for case in cases:
            if case["kind"] == "conversation":
                continue
            if _KIND_STAGE[case["kind"]] not in dut.stages:
                result.cases_out_of_stage += 1
                continue

            result.cases_scored += 1
            expected = set(case["labels_expected"]) & dut.scope
            got = {label for s in asyncio.run(_run(dut, case)) for label in s.labels} & dut.scope

            for label in sorted(expected | got | dut.scope):
                if label not in dut.scope:
                    continue
                score = result.score(label)
                if label in expected and label in got:
                    score.tp += 1
                elif label in expected:
                    score.fn += 1
                    result.misses.append((case["case_id"], label))
                elif label in got:
                    score.fp += 1
                    result.false_positives.append((case["case_id"], label))
    return results, excluded


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def _provenance(cases: Sequence[dict[str, Any]], dataset_dir: Path) -> list[str]:
    digest = dataset_digest(dataset_dir)
    # One definition in `eval/host_load.py`; this copy lacked `cwd`, so it read whichever
    # directory the process started in rather than the repo.
    code = git_stamp()
    head = code["commit"] or "unavailable"
    dirty = code["dirty"]
    return [
        "## Provenance",
        "",
        "Every number below is reproducible from this state (NFR-INT-001).",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Generated (UTC) | {datetime.now(timezone.utc).isoformat(timespec='seconds')} |",
        f"| Dataset digest | `{digest}` |",
        f"| Frozen at | `{FROZEN_COMMIT[:12]}` — {'MATCHES' if digest == dataset_digest(DATASET_DIR) and not check_freeze(dataset_dir) else 'MISMATCH'} |",
        f"| Cases loaded | {len(cases)} (derived from the files, never asserted) |",
        f"| Code commit | `{head[:12]}`{' + uncommitted changes' if dirty else ''} |",
        f"| Python | {platform.python_version()} |",
        f"| Platform | {platform.system()} {platform.release()} · {platform.machine()} |",
        f"| Command | `python -m eval.run_all` |",
        "",
    ]


def _detector_section(results: Sequence[DetectorResult], excluded: int) -> list[str]:
    """The live detectors. Frozen v1 baselines are rendered by `_revision_section` instead, so
    a reader is never handed two same-named tables and left to work out which one ships."""
    out = [
        "## Detectors (06 §3)",
        "",
        "These are the **shipping** implementations. The two detectors revised under ADR-026 "
        "also carry a frozen v1 baseline, re-measured every run and tabulated against these "
        "figures in *Disclosed revision* below.",
        "",
        "Precision / recall / F1 per label, case-level, scored **only against each "
        "detector's own slice of the 04 §1.1 taxonomy** — a toxicity case is not a miss for "
        "`tier1_pii`. `n/a` means the denominator was empty: undefined, never 1.0.",
        "",
        f"Conversation-kind cases excluded from this section: **{excluded}**. ADR-021 labels "
        "a multi-turn case per *breach unit*, while its text carries every turn — scanning "
        "the whole text would score false positives against a convention that excluded them "
        "by design, and which turn breached is not a recorded field.",
        "",
    ]
    for result in results:
        if result.variant != "v2":
            continue
        micro = result.micro
        out += [
            f"### `{result.name}`",
            "",
            f"Cases scored: **{result.cases_scored}** "
            f"(out-of-stage, not scored: {result.cases_out_of_stage})",
            "",
        ]
        if result.note:
            out += [f"> {result.note}", ""]
        out += [
            "| Label | Support | TP | FP | FN | Precision | Recall | F1 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for label in sorted(result.labels):
            s = result.labels[label]
            out.append(
                f"| `{label}` | {s.support} | {s.tp} | {s.fp} | {s.fn} | "
                f"{_fmt(s.precision)} | {_fmt(s.recall)} | {_fmt(s.f1)} |"
            )
        out.append(
            f"| **micro** | {micro.support} | {micro.tp} | {micro.fp} | {micro.fn} | "
            f"{_fmt(micro.precision)} | {_fmt(micro.recall)} | {_fmt(micro.f1)} |"
        )
        out.append("")
        if result.misses:
            listed = ", ".join(f"{cid} (`{label}`)" for cid, label in result.misses[:25])
            more = "" if len(result.misses) <= 25 else f" … +{len(result.misses) - 25} more"
            out += [f"**Missed ({len(result.misses)}):** {listed}{more}", ""]
        if result.false_positives:
            listed = ", ".join(
                f"{cid} (`{label}`)" for cid, label in result.false_positives[:25]
            )
            more = (
                ""
                if len(result.false_positives) <= 25
                else f" … +{len(result.false_positives) - 25} more"
            )
            out += [f"**False positives ({len(result.false_positives)}):** {listed}{more}", ""]
    return out


def _revision_section(results: Sequence[DetectorResult]) -> list[str]:
    """ADR-026 §1 / 06 §3.2 — the report adds a column, it never replaces a number."""
    pairs = [
        (v1, next((r for r in results if r.name == v1.name and r.variant == "v2"), None))
        for v1 in results
        if v1.variant == "v1"
    ]
    if not pairs:
        return []

    out = [
        "## Disclosed revision — v1 vs v2 (ADR-026, 06 §3.2)",
        "",
        "A detector revised **after** its failures were measured produces weaker evidence than "
        "one measured blind, however carefully the revision was derived. So the v1 figures are "
        "not overwritten and not deleted — they are re-measured here alongside v2, every run.",
        "",
        "**The v1 columns are computed, not transcribed.** `controlplane/detectors/_v1_*.py` "
        "hold the original implementations, byte-identical to the commit that produced the "
        "blind measurement and carrying a DO-NOT-EDIT banner. A v1 number quoted from an older "
        "report would be unverifiable, and AGENTS.md §7 requires every judge-facing number to "
        "be reproducible by a command in this repo — so the baseline is re-derived on every "
        "run instead.",
        "",
        "| Detector | Metric | v1 (blind first contact) | v2 (post-revision, disclosed) | Δ |",
        "|---|---|---:|---:|---:|",
    ]

    def delta(before: float | None, after: float | None) -> str:
        if before is None or after is None:
            return "n/a"
        diff = after - before
        return f"{diff:+.3f}" if abs(diff) >= 0.0005 else "±0.000"

    for v1, v2 in pairs:
        if v2 is None:
            continue
        a, b = v1.micro, v2.micro
        rows = (
            ("precision", _fmt(a.precision), _fmt(b.precision), delta(a.precision, b.precision)),
            ("recall", _fmt(a.recall), _fmt(b.recall), delta(a.recall, b.recall)),
            ("F1", _fmt(a.f1), _fmt(b.f1), delta(a.f1, b.f1)),
            ("TP", str(a.tp), str(b.tp), f"{b.tp - a.tp:+d}"),
            ("FP", str(a.fp), str(b.fp), f"{b.fp - a.fp:+d}"),
            ("FN", str(a.fn), str(b.fn), f"{b.fn - a.fn:+d}"),
        )
        for i, (metric, before, after, d) in enumerate(rows):
            name = f"`{v1.name}`" if i == 0 else ""
            out.append(f"| {name} | {metric} | {before} | {after} | {d} |")

    out += [
        "",
        "**Precision movement is shown next to recall on purpose** (06 §3.2): a revision that "
        "buys recall with precision has to show both halves, or the table flatters it.",
        "",
        "### Derivation and scope exclusions, restated with their cost",
        "",
        "- **`tier1_pii` v2** derives every pattern from a named published specification, cited "
        "  in 04 §2.5: ITU-T E.164, NANP conventions, RFC 7519/7515. Two scope exclusions are "
        "  deliberate precision-grounded DLP trade-offs, and **both cost recall**: bare 7-digit "
        "  local numbers (indistinguishable from order and ticket ids) and bare 32/64-hex "
        "  without a credential cue (collides with git SHAs, digests, dashless UUIDs). An "
        "  exclusion that quietly removed hard cases would be indistinguishable from tuning, "
        "  which is why they are named here rather than only in the ADR.",
        "- **The NANP `N ∈ [2–9]` constraint adds no recall on this corpus** (ADR-026 "
        "  Amendment 1). v1's broader phone pattern is deliberately retained and evaluated "
        "  first, so it shadows both NANP rows at equal extent. The entire v2 phone gain is "
        "  **E.164 plus the spaced-parenthesis variant**. v2 is kept a strict *superset* of v1 "
        "  because that is what makes the permanent v1 baseline describe code that still ships.",
        "- **`numeric_claims` v2** deletes the bare large-digit-run rule (ADR-025): measured "
        "  blind it scored precision 0.267, with 30 of 33 false positives on `PII-*` cases, "
        "  because an SSN, a card and a phone number are all runs of digits. A numeral now "
        "  fires only on a quantity shape, and an identifier pre-filter runs first and absolute.",
        "- **One re-measurement.** ADR-026 §5 permits exactly one, and forbids touching the "
        "  harness afterwards. If v2 misses a target the miss stands and **the target does not "
        "  move**.",
        "",
        "### v1 metric validity across the freeze bump",
        "",
        "ADR-024 bumped the freeze after v1 was first measured. Its seven changed cases altered "
        "`action_expected` only — **no `labels_expected`** — so per-detector precision, recall "
        "and F1, which are computed against labels, remain valid over an identical label set "
        "(freeze history in 06 §1). A bump touching a label would have invalidated them.",
        "",
    ]
    return out


def _skipped_section() -> list[str]:
    out = [
        "## Not measured (rule 1: measured or absent)",
        "",
        "These 04 §2 rows have no implementation. They are listed rather than scored: a "
        "missing detector contributing 0.0 would read as a failing detector, and one "
        "contributing 1.0 would be a fabricated number.",
        "",
        "| Detector | Labels it would emit | Corpus positives unscored | Reason |",
        "|---|---|---:|---|",
    ]
    return out


def _ordered(matrices: dict[str, ConfusionMatrix]) -> list[ConfusionMatrix]:
    """UC-1, UC-2, UC-3 — the 01 §3 order, not alphabetical.

    A reader meets these use cases in a fixed sequence across 01 §3, the policy files and the
    demo script; sorting by name would present them back as UC-3, UC-2, UC-1. Any policy not
    in `USE_CASES` still renders, appended in sorted order, so an added use case cannot vanish
    from the report.
    """
    known = [matrices[name] for name in USE_CASES if name in matrices]
    extra = [matrices[name] for name in sorted(set(matrices) - set(USE_CASES))]
    return known + extra


def _policy_section(
    conformance: dict[str, ConfusionMatrix],
    end_to_end: dict[str, ConfusionMatrix],
    recon: Any,
    *,
    scored: int,
    uncovered: int,
    conversation: int,
    total: int,
) -> list[str]:
    """The NFR-EVAL-002 artifact: two matrices, and the distinction between them.

    06 §3.3 makes the separation normative. They are different claims and a reader who
    merged them would conclude the system detects far better than it does.
    """
    out = [
        "## Policy-level confusion matrices (06 §3, §3.3) — NFR-EVAL-002",
        "",
        "Two matrices, and **the distinction is normative** (06 §3.3): they answer different "
        "questions and neither may be quoted as the other. Both tabulate `action_expected` "
        "(rows) against the `action_taken` this repo's policy engine actually returned "
        "(columns) — a verdict per case per use case, from `controlplane/policy/engine.py`.",
        "",
        "### A. Engine conformance — perfect detection assumed",
        "",
        "Signals **synthesized from `labels_expected`** and fed to the engine. This measures "
        "the **engine + policy layer alone**: it assumes every detector fired correctly, "
        "which is exactly why it is *not* a detection-quality metric and *not* an end-to-end "
        "claim. Its value is that it isolates one layer — a disagreement here is a policy or "
        "engine defect, with detection held constant.",
        "",
    ]
    for matrix in _ordered(conformance):
        out += render_matrix(matrix)

    agreements = {m.agreements for m in conformance.values()}
    totals = {m.total for m in conformance.values()}
    perfect = agreements == totals

    out += [
        "**Why this is not the fabricated matrix 06 §3.1 rule 3 forbids.** Rule 3 bars "
        "deriving `action_taken` from `labels_expected` and comparing it against a function "
        "of that same ground truth — a diagonal guaranteed by construction. What runs here "
        "is structurally different: `policy/engine.py` is an **independent implementation** "
        "of 04 §4.3, while `action_expected` is pinned to `validate_dataset.derive_action` "
        "for every case × policy by the freeze gate. The table is therefore a "
        "**differential test of two independent implementations of one spec**, and a "
        "disagreement would be a real finding about one of them.",
        "",
    ]
    if perfect:
        out += [
            "**The diagonal is perfect, so the burden of proof is on this section, not the "
            "reader.** An agreement rate of 1.000 is precisely the result rule 3 warns "
            "about, and \"the two sides are independent\" is an assertion. So the matrix is "
            "**falsified rather than trusted**: `tests/test_policy_matrix.py` injects, one "
            "at a time, the defects the ADRs exist to prevent — ADR-012 band scoping, "
            "ADR-019 enriched-label handling, the ADR-015 span-less promotion, the 04 §4.2 "
            "severity order, and 04 §4.3 step-1 resolution — and **requires** the matrix to "
            "disagree. Every one is detected, and the two narrow ones land where the ADRs "
            "predict: ADR-019 only on `hr_copilot` (the sole policy where "
            "`privacy.person: block` meets `borderline_action: pass`) and ADR-015 only on "
            "`support_bot`. A mutation the matrix could not see would mean the diagonal "
            "measured nothing; none is invisible, which is what makes the 1.000 "
            "publishable.",
            "",
            "**No figure here derives from a seed τ.** The shipped τ are "
            "`# SEED(pre-calibration)` (ADR-016) and 06 §3 rules that a seed value is never "
            "judge-facing. Synthesis places each score *relative* to the band, so rescaling "
            "the band moves the scores with it and every verdict is unchanged — pinned "
            "across four bands from (0.10, 0.90) to (0.45, 0.80) by "
            "`test_matrix_is_invariant_to_the_seed_tau_values`.",
            "",
        ]

    out += [
        "### B. End-to-end (partial) — real detector emissions",
        "",
        f"The same engine, fed the signals the **shipping detectors actually emitted**. "
        f"Scored over **{scored} of {total}** cases: a case qualifies only when *every* "
        f"label it expects is emittable by a detector that exists, because a case with one "
        f"covered and one absent label would measure the missing detector rather than the "
        f"policy layer.",
        "",
        f"| Disposition | Cases |",
        f"|---|---:|",
        f"| scored end-to-end | {scored} |",
        f"| not scored — expects a label no implemented detector emits | {uncovered} |",
        f"| not scored — conversation-kind (ADR-021, as in the detector section) | {conversation} |",
        f"| **total** | **{scored + uncovered + conversation}** |",
        "",
        "This is the artifact that **grows as detectors land**. Today it covers the "
        "deterministic slice only, so read it as a floor on the whole system rather than a "
        "measurement of it.",
        "",
    ]
    for matrix in _ordered(end_to_end):
        out += render_matrix(matrix)

    out += [
        "**Reconciliation — this rate flatters the system, and here is the mechanism.** "
        "The end-to-end agreement rate is *higher* than the detector section's figures would "
        f"imply, and the reason is not favourable. Of the **{recon.failing_cases}** scored "
        f"cases carrying a detection failure, only **{recon.exposed}** produce a wrong "
        f"verdict. The other **{recon.masked}** reach their expected action anyway, by two "
        "distinct mechanisms that are counted separately because they are not the same fact:",
        "",
        f"- **{len(recon.masked_misses)} masked miss(es)** — the case carries another label "
        "mapping to an action at least as severe, so a missed phone number in a sentence "
        "that also holds a detected SSN moves no verdict"
        + (f": {', '.join(recon.masked_misses)}" if recon.masked_misses else ""),
        f"- **{len(recon.masked_false_positives)} masked false positive(s)** — the spurious "
        "label's action was never more severe than one a genuine label already drove, so "
        "most-severe convergence (04 §4.2) absorbed it"
        + (
            f": {', '.join(recon.masked_false_positives)}"
            if recon.masked_false_positives
            else ""
        ),
        "",
        "Every one of those failures is real and is counted in the detector section above. "
        "The matrix cannot see them, and reporting the agreement rate alone would present "
        "that blindness as accuracy.",
        "",
        "Stated plainly: matrix B measures the **policy layer** honestly and would "
        "**overstate detection** if read as a system score. That is why both counts appear "
        "here instead of the flattering one alone (AGENTS.md §7).",
        "",
        "**NFR-EVAL-002** asks for the per-use-case matrix to exist and sets no target — "
        "**met** by this section, with the coverage limit above stated rather than implied.",
        "",
        "## Threshold calibration (06 §3) — NOT COMPUTED",
        "",
        "Calibration quantiles need non-conformity scores from the confidence-kind detectors "
        "(`fast_consistency`, `rag_grounding` — ADR-012), both stubs. The tau values in "
        "`policies/*.yaml` therefore remain `# SEED(pre-calibration)` (ADR-016), and per 06 "
        "§3 **a seed value is never judge-facing**: no number in this report derives from one "
        "— including the matrices above, whose τ-invariance is pinned by a test.",
        "",
    ]
    return out


def build_report(
    results: Sequence[DetectorResult],
    cases: Sequence[dict[str, Any]],
    excluded: int,
    dataset_dir: Path,
    provenance_note: str,
    conformance: dict[str, ConfusionMatrix],
    end_to_end: dict[str, ConfusionMatrix],
    recon: Any,
    coverage: tuple[int, int, int],
) -> str:
    label_counts = Counter(
        label for case in cases for label in case["labels_expected"]
    )
    lines = [
        "# Evaluation report — detectors",
        "",
        "Generated by `python -m eval.run_all` (06 §3). **Prototype measurements on a "
        "synthetic corpus — not a production claim.**",
        "",
        provenance_note,
        "",
        *_provenance(cases, dataset_dir),
        *_detector_section(results, excluded),
        *_revision_section(results),
    ]

    lines += _skipped_section()
    for skipped in (*SKIPPED, *DEMOTED):
        unscored = sum(label_counts.get(label, 0) for label in skipped.labels)
        labels = " · ".join(f"`{label}`" for label in skipped.labels)
        lines.append(f"| `{skipped.name}` | {labels} | {unscored} | {skipped.reason} |")
    total_unscored = sum(
        label_counts.get(label, 0) for s in (*SKIPPED, *DEMOTED) for label in s.labels
    )
    lines += [
        "",
        f"**{total_unscored} labelled positives in the frozen corpus are unscored** because "
        f"the detector that would emit them does not exist yet. That is {total_unscored} of "
        f"{sum(label_counts.values())} label occurrences — read every number above as "
        "covering the deterministic slice only.",
        "",
    ]

    scored_n, uncovered_n, conversation_n = coverage
    lines += _policy_section(
        conformance,
        end_to_end,
        recon,
        scored=scored_n,
        uncovered=uncovered_n,
        conversation=conversation_n,
        total=len(cases),
    )

    # NFR-EVAL-001 verdict last: it is the one row with a documented target, so it must be
    # impossible to skim past.
    # Variant is explicit, never positional: two results now share the name `tier1_pii`, and
    # the target applies to the one that ships. Selecting by name alone would let list order
    # decide which number is graded against NFR-EVAL-001.
    pii = next((r for r in results if r.name == "tier1_pii" and r.variant == "v2"), None)
    pii_v1 = next((r for r in results if r.name == "tier1_pii" and r.variant == "v1"), None)
    lines += ["## NFR-EVAL-001 — Tier-1 PII recall ≥ 0.95", ""]
    if pii is None:
        lines.append("Not evaluated.")
    else:
        recall = pii.micro.recall
        if recall is None:
            lines.append("Recall undefined (no positive cases) — target not evaluable.")
        else:
            verdict = "**MET**" if recall >= 0.95 else "**MISSED**"
            lines += [
                f"Measured micro recall: **{recall:.4f}** over {pii.micro.support} "
                f"positive label occurrences. Target 0.95 → {verdict}.",
                "",
            ]
            if pii_v1 is not None and pii_v1.micro.recall is not None:
                lines += [
                    f"The permanent v1 baseline is **{pii_v1.micro.recall:.4f}** "
                    f"(blind first contact, ADR-026 §1), re-measured on this run rather than "
                    f"quoted. Both numbers stand in the record.",
                    "",
                ]
            if recall < 0.95:
                lines.append(
                    "A missed target is reported as missed and raised as a **D3 deviation** "
                    "(AGENTS.md §5.1, 06 §1) — never tuned away by editing the detector "
                    "against these cases. Under ADR-026 §5 this is the single permitted "
                    "re-measurement: the target does not move and the harness is not touched."
                )
    lines += [
        "",
        "---",
        "",
        "Reproduce: `python -m eval.validate_dataset --freeze && python -m eval.run_all`",
        "",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset-dir", type=Path, default=DATASET_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--allow-dev",
        action="store_true",
        help="permit dev-class upstream provenance; taints the output filename (ADR-018)",
    )
    args = parser.parse_args(argv)

    # Gate 1 — the freeze. No number may be computed against an unfrozen dataset (06 §1).
    violations = check_freeze(args.dataset_dir)
    if violations:
        print("FREEZE CHECK FAILED — refusing to compute:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        return 1

    # Gate 2 — upstream provenance (ADR-018).
    #
    # Scoped, and the scope is stated in the report rather than hidden here. Every detector
    # implemented today is a local deterministic matcher: no upstream call, no token
    # accounting, so no figure below rests on the provider's usage reporting. Failing the
    # run — or stamping DEV-TAINTED onto a filename whose numbers are provider-independent —
    # would teach a reader that the taint marker is noise, which is worse than not having it.
    # The gate is still evaluated and its result recorded, and it becomes binding the moment
    # a section consumes upstream-derived data (cost, latency-with-provider, consistency).
    tainted = False
    try:
        cfg = require_measured_upstream(
            allow_dev=args.allow_dev, artifact="the eval report"
        )
        provenance_note = (
            f"> **Upstream provenance:** active provider `{cfg.active.name}` is "
            f"`{cfg.active.upstream_class}`-class (ADR-018)."
        )
    except TaintedDataError as exc:
        cfg = load_gateway_config()
        tainted = args.allow_dev
        provenance_note = (
            f"> **Upstream provenance:** the active provider `{cfg.active.name}` is "
            f"**dev-class**, so `require_measured_upstream()` refuses it for judge-facing "
            f"output (ADR-018).\n"
            f">\n"
            f"> **This report is unaffected, and here is why rather than a bare assertion.** "
            f"Every detector scored below (`tier1_pii`, `tier1_blocklist`, `numeric_claims`) "
            f"is a local deterministic matcher: it makes no upstream call, consumes no "
            f"tokens, and reads no usage accounting. No figure here derives from the "
            f"provider, so the gate is **evaluated and non-binding for this section set**. "
            f"It becomes binding the moment cost, end-to-end latency, or consistency "
            f"sampling is reported — none of which this run produces.\n"
            f">\n"
            f"> Gate message, recorded verbatim rather than summarized: {exc}"
        )

    cases = load_cases(args.dataset_dir)
    if not cases:
        print(f"no cases found in {args.dataset_dir}", file=sys.stderr)
        return 1

    results, excluded = evaluate(cases)

    # -- the two 06 §3.3 matrices ------------------------------------------
    # Conformance runs over EVERY case: it assumes perfect detection, so no case is out of
    # its reach. End-to-end runs only over the covered slice, and the excluded counts are
    # reported rather than dropped.
    policies = load_policies()
    conformance = conformance_matrices(cases, policies)
    scorable, uncovered_n, conversation_n = covered_cases(cases, IMPLEMENTED_LABELS)
    emissions = collect_emissions(scorable)
    end_to_end = end_to_end_matrices(scorable, policies, emissions)
    scorable_ids = {c["case_id"] for c in scorable}
    missed_ids, fp_ids = detection_failure_case_ids(results)
    recon = reconcile(missed_ids & scorable_ids, fp_ids & scorable_ids, end_to_end)

    report = build_report(
        results,
        cases,
        excluded,
        args.dataset_dir,
        provenance_note,
        conformance,
        end_to_end,
        recon,
        (len(scorable), uncovered_n, conversation_n),
    )

    out_path = taint_output_path(args.out, tainted=tainted)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)

    def _micro(name: str, variant: str) -> LabelScore | None:
        found = next(
            (r for r in results if r.name == name and r.variant == variant), None
        )
        return found.micro if found else None

    pii_v2, pii_v1 = _micro("tier1_pii", "v2"), _micro("tier1_pii", "v1")
    num_v2, num_v1 = _micro("numeric_claims", "v2"), _micro("numeric_claims", "v1")
    recall = pii_v2.recall if pii_v2 else None
    print(f"wrote {out_path}")
    print(f"  cases loaded      : {len(cases)}")
    print(f"  detectors scored  : {len(SCORED)} of"
          f" {len(SCORED) + len(SKIPPED) + len(DEMOTED)}"
          f" (+{len(SCORED_V1)} frozen v1 baselines)")
    for name, missing in sorted(UNLOADABLE.items()):
        print(f"  UNLOADABLE        : {name} (missing {missing}) — reported, not scored")
    print(f"  tier1_pii recall  : v1 {_fmt(pii_v1.recall if pii_v1 else None, digits=4)}"
          f" -> v2 {_fmt(recall, digits=4)} (NFR-EVAL-001 target 0.95)")
    print(f"  tier1_pii prec.   : v1 {_fmt(pii_v1.precision if pii_v1 else None, digits=4)}"
          f" -> v2 {_fmt(pii_v2.precision if pii_v2 else None, digits=4)}")
    print(f"  numeric precision : v1 {_fmt(num_v1.precision if num_v1 else None, digits=4)}"
          f" -> v2 {_fmt(num_v2.precision if num_v2 else None, digits=4)}")
    conf_rates = sorted({m.agreement_rate for m in conformance.values() if m.agreement_rate})
    e2e_rates = sorted({m.agreement_rate for m in end_to_end.values() if m.agreement_rate})
    print(f"  conformance matrix: {'/'.join(f'{r:.4f}' for r in conf_rates)}"
          f" over {len(cases)} cases x {len(conformance)} policies (perfect detection assumed)")
    print(f"  end-to-end matrix : {'/'.join(f'{r:.4f}' for r in e2e_rates)}"
          f" over {len(scorable)} covered cases"
          f" ({recon.masked} detection failures masked by co-occurring labels)")
    if recall is not None and recall < 0.95:
        print("  NFR-EVAL-001      : MISSED — file a D3 deviation (never tune the detector)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
