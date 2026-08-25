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
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from controlplane.detectors.base import DetectorContext, Signal, Stage
from controlplane.detectors.numeric_claims import numeric_claims
from controlplane.detectors.tier1_patterns import tier1_blocklist, tier1_pii
from controlplane.gateway.config import (
    TaintedDataError,
    load_gateway_config,
    require_measured_upstream,
    taint_output_path,
)
from eval.validate_dataset import (
    DATASET_DIR,
    FROZEN_COMMIT,
    check_freeze,
    dataset_digest,
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


@dataclass
class SkippedDetector:
    """A 04 §2 row with no implementation. Reported, never scored (rule 1)."""

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
            "The definition of a 'citation marker' this detector turns on is **not in the "
            "spec** — it is provisional and tracked as **Q-18**, which gates publication of "
            "the figures below (AGENTS.md §7)."
        ),
    ),
)

SKIPPED: tuple[SkippedDetector, ...] = (
    SkippedDetector("tier2_injection", ("security.prompt_injection",),
                    "not implemented — stub; Q-04 defers the checkpoint choice"),
    SkippedDetector("tier2_toxicity", ("toxicity.high", "toxicity.moderate"),
                    "not implemented — stub; Q-04 defers the checkpoint choice"),
    SkippedDetector("fast_consistency", ("hallucination.low_confidence",),
                    "not implemented — stub; needs the 2nd-sample provider (Q-10)"),
    SkippedDetector("rag_grounding", ("hallucination.ungrounded_claim",),
                    "not implemented — stub; needs sentence-transformers"),
    SkippedDetector("entity_enricher", ("privacy.person",),
                    "not implemented — stub; needs spaCy en_core_web_sm (ADR-011)"),
    SkippedDetector("conv_tracker", ("conversation.cumulative_risk",),
                    "not implemented — stub (ADR-021 scope is specified, code is not)"),
    SkippedDetector("cost_budget", ("cost.budget_exceeded", "cost.request_too_large"),
                    "not implemented — stub; the cost plane needs a priced provider"),
    SkippedDetector("loop_guard", ("cost.loop_detected",),
                    "not implemented — stub"),
)


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
    results = [DetectorResult(name=d.name, note=d.note) for d in IMPLEMENTED]
    excluded = sum(1 for c in cases if c["kind"] == "conversation")

    for dut, result in zip(IMPLEMENTED, results):
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


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=5, check=True
        ).stdout.strip()
    except Exception:
        return "unavailable"


def _provenance(cases: Sequence[dict[str, Any]], dataset_dir: Path) -> list[str]:
    digest = dataset_digest(dataset_dir)
    head = _git("rev-parse", "HEAD")
    dirty = _git("status", "--porcelain")
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
    out = [
        "## Detectors (06 §3)",
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


def _policy_section() -> list[str]:
    return [
        "## Policy-level confusion matrix (06 §3) — NOT COMPUTED",
        "",
        "06 §3 calls the per-use-case 4x4 `action_taken` vs `action_expected` matrix *the "
        "skeptical-stakeholder artifact*, and it is the one number a reader most wants here. "
        "It is absent because computing it today would be **circular, not merely premature**:",
        "",
        "- `controlplane/policy/engine.py` is a stub, so there is no `action_taken` to "
        "  tabulate. A verdict has never been produced by this repo.",
        "- The nearest available substitute is `eval/validate_dataset.derive_action`, and it "
        "  must not be used here. It derives the action from `labels_expected` — the ground "
        "  truth itself — so tabulating it against `action_expected` would compare ground "
        "  truth with a function of ground truth and produce a **perfect diagonal that means "
        "  nothing**. Publishing that as a confusion matrix would be a fabricated result "
        "  (AGENTS.md §5.4, §7).",
        "- Feeding real detector output into the derivation would not rescue it either: 8 of "
        "  11 detectors are absent, so the matrix would measure *which detectors are missing* "
        "  rather than whether the policy layer is correct.",
        "",
        "This section becomes computable when the policy engine lands. Until then "
        "NFR-EVAL-002 is **unmet and reported as unmet** rather than approximated.",
        "",
        "## Threshold calibration (06 §3) — NOT COMPUTED",
        "",
        "Calibration quantiles need non-conformity scores from the confidence-kind detectors "
        "(`fast_consistency`, `rag_grounding` — ADR-012), both stubs. The tau values in "
        "`policies/*.yaml` therefore remain `# SEED(pre-calibration)` (ADR-016), and per 06 "
        "§3 **a seed value is never judge-facing**: no number in this report derives from one.",
        "",
    ]


def build_report(
    results: Sequence[DetectorResult],
    cases: Sequence[dict[str, Any]],
    excluded: int,
    dataset_dir: Path,
    provenance_note: str,
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
    ]

    lines += _skipped_section()
    for skipped in SKIPPED:
        unscored = sum(label_counts.get(label, 0) for label in skipped.labels)
        labels = " · ".join(f"`{label}`" for label in skipped.labels)
        lines.append(f"| `{skipped.name}` | {labels} | {unscored} | {skipped.reason} |")
    total_unscored = sum(
        label_counts.get(label, 0) for s in SKIPPED for label in s.labels
    )
    lines += [
        "",
        f"**{total_unscored} labelled positives in the frozen corpus are unscored** because "
        f"the detector that would emit them does not exist yet. That is {total_unscored} of "
        f"{sum(label_counts.values())} label occurrences — read every number above as "
        "covering the deterministic slice only.",
        "",
    ]

    lines += _policy_section()

    # NFR-EVAL-001 verdict last: it is the one row with a documented target, so it must be
    # impossible to skim past.
    pii = next((r for r in results if r.name == "tier1_pii"), None)
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
            if recall < 0.95:
                lines.append(
                    "A missed target is reported as missed and raised as a **D3 deviation** "
                    "(AGENTS.md §5.1, 06 §1) — never tuned away by editing the detector "
                    "against these cases."
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
    report = build_report(results, cases, excluded, args.dataset_dir, provenance_note)

    out_path = taint_output_path(args.out, tainted=tainted)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)

    pii = next((r for r in results if r.name == "tier1_pii"), None)
    recall = pii.micro.recall if pii else None
    print(f"wrote {out_path}")
    print(f"  cases loaded      : {len(cases)}")
    print(f"  detectors scored  : {len(IMPLEMENTED)} of {len(IMPLEMENTED) + len(SKIPPED)}")
    print(f"  tier1_pii recall  : {_fmt(recall, digits=4)} (NFR-EVAL-001 target 0.95)")
    if recall is not None and recall < 0.95:
        print("  NFR-EVAL-001      : MISSED — file a D3 deviation (never tune the detector)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
