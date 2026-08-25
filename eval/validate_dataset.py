"""Dataset freeze gate — `python -m eval.validate_dataset` (06 §2.4).

Checks the §2.1 case format, the 04 §1.1 closed taxonomy, `action_expected` key sets, the
ADR-023 causal-ground-truth fields, and — the part that earns the name — **re-derives every
expected action from ground truth plus the loaded policy** and compares it to what the case
asserts.

**It validates consistency, not label correctness.** Whether `HAL-047` really is an
unsourced numeric is a judgement call for the second-teammate review (06 §1); whether its
recorded expectation follows from its labels and the shipped YAML is arithmetic, and
arithmetic is what a gate can hold. Open judgement items live in
`eval/dataset/REVIEW_NEEDED.md` until ruled.

Why derive rather than trust the recorded action (ADR-023): for a confidence-kind label the
action depends on where the score falls against `tau_low`/`tau_high`, and 06 §3 calibration
is explicitly allowed to move both. A literal expectation would freeze the *seed* thresholds
into ground truth, and a calibration run would leave those cases asserting outcomes the
policy no longer produces — with nothing to notice the drift. Deriving turns that silence
into a failing gate, which is the F6 tripwire obtained for free.

Exit status: 0 = consistent, 1 = at least one violation. Prints counts it actually loaded;
**never asserts a total**, because an asserted total is a number that can rot.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from controlplane.policy.schema import TAXONOMY, Action, Policy

# --------------------------------------------------------------------------
# Locations + vocabulary
# --------------------------------------------------------------------------

DATASET_DIR = Path(__file__).resolve().parent / "dataset"
POLICY_DIR = Path(__file__).resolve().parents[1] / "policies"

#: The three UC pipelines (01 §3). `action_expected` must carry exactly these keys — a
#: missing one is an unstated expectation and a fourth is a use case that does not exist.
USE_CASES = ("support_bot", "hr_copilot", "finance_advisor")

#: 06 §2.1 / Q-11. A `conversation` case encodes its turns as "user: …\nassistant: …"
#: lines inside `text`; the format gains no `turns` field.
KINDS = ("input", "output", "conversation")

REQUIRED_KEYS = {
    "case_id", "kind", "use_case", "text", "context", "labels_expected",
    "action_expected", "notes",
}
#: ADR-023 adds exactly these two, and only to confidence-driven cases.
CAUSAL_KEYS = {"grounded", "person_present"}
GROUNDED_BANDS = ("yes", "no", "borderline")

#: Confidence-kind labels (ADR-012): higher score = better, so the band applies. Only
#: `fast_consistency` and `rag_grounding` are confidence-kind, and these are their labels.
CONFIDENCE_LABELS = frozenset(
    {"hallucination.ungrounded_claim", "hallucination.low_confidence"}
)

#: Appended by `entity_enricher`, never emitted directly (04 §1.1/§2.2). ADR-019 gives it
#: two branches and no third: dropped with its host at `score >= tau_high`, otherwise its
#: MAPPED action, unadjusted — `borderline_action` never reaches it.
ENRICHED_LABELS = frozenset({"privacy.person"})

#: Span-less by design, so an EDIT verdict has no extent to apply a 04 §6 transform to and
#: 04 §4.3 step 4 promotes it to ESCALATE (ADR-015).
#:
#: `hallucination.low_confidence` is the load-bearing member: `fast_consistency` scores a
#: whole response (`output_full`), so it can never carry a span. The others are here for
#: completeness — they map to escalate or block on all three shipped policies, so the
#: promotion is currently unobservable through them.
SPAN_LESS_LABELS = frozenset(
    {"hallucination.low_confidence", "conversation.cumulative_risk",
     "cost.budget_exceeded", "cost.runaway_loop"}
)

#: File stem -> the case-id prefix its cases must use. A case filed under the wrong stem
#: still validates in isolation but silently distorts the per-detector recall denominator
#: a reviewer reads off 06 §2.3.
ID_PREFIXES = {
    "clean": "CLN", "pii": "PII", "injection": "INJ", "toxicity": "TOX",
    "halluc": "HAL", "overlap": "OVLP", "borderline": "BRD", "conversation": "CONV",
}


# --------------------------------------------------------------------------
# Synthetic-safety patterns (charter NG3)
# --------------------------------------------------------------------------
# Safe by CONSTRUCTION, not by inspection: every value must come from a pool that cannot
# collide with a real person's identifier. Checked mechanically because "it looks fake" is
# not a property anyone can re-verify later.

#: Never-assigned SSN groups: area 000, 666 and 900-999 were never issued, and 987-65-432x
#: is the SSA's own published example range.
_SSN_RE = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")
#: NANP fictional block reserved for fiction: 555-0100 through 555-0199. Separator-agnostic
#: on purpose — `pii.jsonl` deliberately varies the separator (dash, dot, space, none,
#: parenthesised) to pressure the detector's pattern, and a checker that recognised only the
#: dashed form would flag its own test cases while missing an unreserved number written with
#: a dot.
_PHONE_555_RE = re.compile(r"\(?555\)?[-. ]?01\d{2}")
#: RFC 2606 reserved domains, plus .test/.invalid/.localhost.
_EMAIL_RE = re.compile(r"\b[\w.+-]+@([\w.-]+\.\w+)\b")
_RESERVED_DOMAINS = ("example.com", "example.org", "example.net", "example.edu")


def _domain_is_reserved(domain: str) -> bool:
    """RFC 2606 reserves a domain *and everything under it*.

    `mail.corp.example.com` is as unroutable as `example.com`, so an exact-match check would
    reject the multi-level-subdomain cases that exist to test span boundaries.
    """
    low = domain.lower().rstrip(".")
    if low.endswith((".example", ".test", ".invalid", ".localhost")):
        return True
    return any(low == d or low.endswith(f".{d}") for d in _RESERVED_DOMAINS)
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _luhn_ok(digits: str) -> bool:
    """Mod-10 check. A card number that fails Luhn is not a card number."""
    nums = [int(d) for d in re.sub(r"\D", "", digits)][::-1]
    total = 0
    for i, d in enumerate(nums):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return bool(nums) and total % 10 == 0


def _ssn_is_never_assigned(area: str, group: str, serial: str) -> bool:
    if area in ("000", "666") or area.startswith("9"):
        return True
    return (area, group) == ("987", "65") and serial.startswith("432")


def check_synthetic_safety(case: dict[str, Any]) -> list[str]:
    """Every identifier-shaped literal must come from a reserved/never-assigned pool."""
    problems: list[str] = []
    text = case["text"]

    for area, group, serial in _SSN_RE.findall(text):
        if not _ssn_is_never_assigned(area, group, serial):
            problems.append(
                f"SSN {area}-{group}-{serial} is not from a never-assigned range "
                "(000/666/9xx or 987-65-432x) — it could collide with a real number"
            )

    for domain in _EMAIL_RE.findall(text):
        if not _domain_is_reserved(domain):
            problems.append(f"email domain {domain!r} is not RFC 2606 reserved")

    if "pii.credit_card" in case["labels_expected"] and not any(
        _luhn_ok(m) for m in _CARD_RE.findall(text)
    ):
        problems.append(
            "case is labelled pii.credit_card but no Luhn-valid number is present, so a "
            "conforming detector would not fire and the case cannot measure recall"
        )

    if "pii.phone" in case["labels_expected"] and not _PHONE_555_RE.search(text):
        # Not fatal on its own — an international or spaced form is legitimate — so this is
        # reported as a note-worthy deviation from the documented pool rather than silence.
        if re.search(r"\d{3}[-. ]?\d{4}|\+\d", text) is None:
            problems.append(
                "case is labelled pii.phone but carries no phone-shaped literal at all"
            )
    return problems


# --------------------------------------------------------------------------
# ADR-023 derivation — the gate's centre of gravity
# --------------------------------------------------------------------------


def is_confidence_driven(case: dict[str, Any]) -> bool:
    """Whether the case's outcome depends on where a confidence score falls.

    Two ways in, and the second is the one that is easy to miss:

    1. it carries a confidence-kind label, so the band decides its action; or
    2. it carries **no** labels but is scored at the output stage — its expected PASS rests
       on the confidence score clearing `tau_high`. Recording that band is what keeps the
       PASS anchored: without it, a calibration change could start firing on the case with
       nothing to notice.

    Input-stage cases are excluded from (2): neither confidence detector runs on a prompt.
    """
    labels = set(case["labels_expected"])
    if labels & CONFIDENCE_LABELS:
        return True
    return not labels and case["kind"] in ("output", "conversation")


def derive_action(case: dict[str, Any], policy: Policy) -> Action:
    """Re-derive the expected verdict from ground truth + this policy.

    Implements 04 §4.3 steps 1-4 for the labels a case declares: mapped action, ADR-017/019
    band adjustment partitioned on host-vs-enriched, the ADR-015 span-less promotion, then
    most-severe convergence. Deliberately independent of `policy/engine.py` — which is still
    a stub, and which this must be able to disagree with.
    """
    grounded = case.get("grounded")
    surviving: list[Action] = []

    for label in case["labels_expected"]:
        mapped = policy.action_for(label)

        if label in ENRICHED_LABELS:
            # ADR-019: exactly two branches. Never `borderline_action`.
            if grounded == "yes":
                continue                      # dropped together with its host
            action = mapped
        elif label in CONFIDENCE_LABELS:
            if grounded == "yes":
                continue                      # score >= tau_high: not firing
            action = policy.borderline_action if grounded == "borderline" else mapped
        else:
            action = mapped                   # detection-kind bypasses the band (ADR-012)

        # ADR-015 / 04 §4.3 step 4: eligibility is necessary, not sufficient.
        if action is Action.EDIT and label in SPAN_LESS_LABELS:
            action = Action.ESCALATE

        surviving.append(action)

    if not surviving:
        return Action.PASS
    return max(surviving, key=lambda a: a.severity)


# --------------------------------------------------------------------------
# Structural checks
# --------------------------------------------------------------------------


def check_case(case: dict[str, Any], stem: str, policies: dict[str, Policy]) -> list[str]:
    problems: list[str] = []
    keys = set(case)

    missing = REQUIRED_KEYS - keys
    if missing:
        return [f"missing required key(s): {sorted(missing)}"]
    unexpected = keys - REQUIRED_KEYS - CAUSAL_KEYS
    if unexpected:
        problems.append(
            f"unexpected key(s) {sorted(unexpected)}: the 06 §2.1 format is closed, and a "
            "stray key is either a typo or an undocumented field"
        )

    prefix = ID_PREFIXES[stem]
    if not case["case_id"].startswith(f"{prefix}-"):
        problems.append(f"case_id should start with {prefix!r} in {stem}.jsonl")
    if case["kind"] not in KINDS:
        problems.append(f"kind {case['kind']!r} not in {KINDS}")
    if case["use_case"] not in USE_CASES:
        problems.append(f"use_case {case['use_case']!r} not in {USE_CASES}")
    if not case["text"].strip():
        problems.append("text is empty")
    if not str(case["notes"]).strip():
        problems.append(
            "notes is empty: the note is what a second reviewer reads to judge the label"
        )

    unknown = sorted(set(case["labels_expected"]) - TAXONOMY)
    if unknown:
        problems.append(f"labels {unknown} are outside the 04 §1.1 closed taxonomy")
    if len(set(case["labels_expected"])) != len(case["labels_expected"]):
        problems.append(f"duplicate labels in {case['labels_expected']}")

    if set(case["action_expected"]) != set(USE_CASES):
        problems.append(
            f"action_expected keys {sorted(case['action_expected'])} != {sorted(USE_CASES)}"
        )
    else:
        for uc, action in case["action_expected"].items():
            try:
                Action(action)
            except ValueError:
                problems.append(f"action_expected[{uc}] = {action!r} is not a verdict")

    if case["kind"] == "conversation" and "assistant:" not in case["text"]:
        problems.append(
            "a conversation case encodes its turns as 'user: …\\nassistant: …' lines "
            "inside text (06 §2.1) — no assistant turn is present"
        )
    # No check that an input case lacks `context`, deliberately. 05 §1.1 makes
    # `controlplane.context` a REQUEST field, and 06 §2.3 scopes `injection.jsonl` to direct
    # *and indirect* injection — an indirect payload rides in exactly that context doc at the
    # input stage. `is_confidence_driven` already excludes input kinds from band logic, which
    # is the invariant that actually matters here.

    # -- ADR-023 causal fields ------------------------------------------
    driven = is_confidence_driven(case)
    has_causal = bool(CAUSAL_KEYS & keys)
    if driven and not CAUSAL_KEYS <= keys:
        problems.append(
            f"confidence-driven case is missing {sorted(CAUSAL_KEYS - keys)}: its action "
            "depends on which band the score lands in, so a literal expectation would "
            "freeze the seed thresholds into ground truth (ADR-023)"
        )
    elif has_causal and not driven:
        problems.append(
            "case carries ADR-023 band fields but no confidence-kind label decides its "
            "action — a band that never applies (ADR-012 keeps detection-kind literal)"
        )

    if "grounded" in case:
        if case["grounded"] not in GROUNDED_BANDS:
            problems.append(f"grounded {case['grounded']!r} not in {GROUNDED_BANDS}")
        elif case["grounded"] == "yes" and set(case["labels_expected"]) & CONFIDENCE_LABELS:
            problems.append(
                "grounded='yes' means the score cleared tau_high, so the confidence label "
                f"{sorted(set(case['labels_expected']) & CONFIDENCE_LABELS)} cannot also be "
                "expected to fire"
            )
    if "person_present" in case:
        if not isinstance(case["person_present"], bool):
            problems.append("person_present must be a boolean")
        elif case["person_present"] != ("privacy.person" in case["labels_expected"]):
            problems.append(
                f"person_present={case['person_present']} disagrees with "
                "privacy.person in labels_expected: ADR-019 makes the entity "
                "outcome-relevant, so the two must agree"
            )

    problems.extend(check_synthetic_safety(case))

    # -- the derivation -------------------------------------------------
    if not problems:  # a malformed case would produce noise, not signal
        for uc, policy in policies.items():
            derived = derive_action(case, policy)
            recorded = Action(case["action_expected"][uc])
            if derived is not recorded:
                problems.append(
                    f"[{uc}] records {recorded.value!r} but ground truth + the loaded "
                    f"policy derive {derived.value!r}. Today that is a dataset error; "
                    "after calibration it is a drift alarm (ADR-023)"
                )
    return problems


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def load_policies() -> dict[str, Policy]:
    return {
        uc: Policy(**yaml.safe_load((POLICY_DIR / f"{uc}.yaml").read_text()))
        for uc in USE_CASES
    }


def validate(dataset_dir: Path = DATASET_DIR) -> tuple[int, list[str]]:
    """Returns (cases checked, violations). Counts are reported, never asserted."""
    policies = load_policies()
    violations: list[str] = []
    seen_ids: dict[str, str] = {}
    per_file: dict[str, tuple[int, int]] = {}
    label_counts: Counter[str] = Counter()
    total = 0

    for stem in sorted(ID_PREFIXES):
        path = dataset_dir / f"{stem}.jsonl"
        if not path.exists():
            violations.append(f"{stem}.jsonl is missing")
            continue
        positives = controls = 0
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if not line.strip():
                continue
            total += 1
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                violations.append(f"{stem}.jsonl:{lineno}: invalid JSON — {exc}")
                continue
            cid = case.get("case_id", f"<line {lineno}>")
            if cid in seen_ids:
                violations.append(
                    f"{stem}.jsonl:{lineno}: duplicate case_id {cid} "
                    f"(also in {seen_ids[cid]})"
                )
            seen_ids[cid] = f"{stem}.jsonl:{lineno}"
            if case.get("labels_expected"):
                positives += 1
                label_counts.update(case["labels_expected"])
            else:
                controls += 1
            for problem in check_case(case, stem, policies):
                violations.append(f"{stem}.jsonl:{lineno} [{cid}]: {problem}")
        per_file[stem] = (positives, controls)

    print(f"loaded {total} cases from {dataset_dir}")
    print(f"{'file':<16}{'positives':>11}{'controls':>10}")
    for stem, (pos, ctl) in per_file.items():
        print(f"{stem + '.jsonl':<16}{pos:>11}{ctl:>10}")
    print(f"{'TOTAL':<16}{sum(p for p, _ in per_file.values()):>11}"
          f"{sum(c for _, c in per_file.values()):>10}")
    print("\nlabel occurrences (positives only):")
    for label, n in sorted(label_counts.items()):
        print(f"  {label:<38}{n:>4}")
    return total, violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset-dir", type=Path, default=DATASET_DIR)
    args = parser.parse_args(argv)

    total, violations = validate(args.dataset_dir)
    if violations:
        print(f"\n{len(violations)} violation(s):", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        print(
            "\nFREEZE GATE: FAILED. This checks consistency, not label correctness — "
            "label judgement lives in eval/dataset/REVIEW_NEEDED.md (06 §1/§2.4).",
            file=sys.stderr,
        )
        return 1
    print(f"\nFREEZE GATE: PASSED for {total} cases (consistency only; label correctness "
          "is the second-teammate review, 06 §1).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
