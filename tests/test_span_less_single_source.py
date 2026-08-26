"""The span-less label set has exactly one definition (M-9).

`eval/policy_matrix.py` and `eval/validate_dataset.py` each reproduce the ADR-015
promotion rather than calling the engine, and each had grown its own copy of "which labels
cannot carry a span". They had already diverged: the matrix's set included
`cost.request_too_large` and the validator's did not, so the matrix applied the promotion
where the validator skipped it. Dead today (zero corpus cases), latent tomorrow.

This file is the guard that a third copy cannot appear quietly. It is structural — an AST
walk, not a grep for a name — because the divergence that happened was between two sets
with *different names*, so a name-based check would have missed it entirely.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from controlplane.policy.schema import SPAN_LESS_LABELS

ROOT = Path(__file__).resolve().parents[1]

#: The one file allowed to define it.
SOURCE = ROOT / "controlplane" / "policy" / "schema.py"

#: Scope: the production and eval trees — the two places the copies lived. `tests/` is
#: deliberately excluded: a test may legitimately enumerate labels to pin one case, and
#: forbidding that would make this guard obstruct the coverage it protects.
SEARCH_DIRS = ("controlplane", "eval")

#: The load-bearing member. A set is a span-less copy if it names this AND at least one
#: request-level `cost.*` label — the combination no other concept in this codebase has.
#: `eval/run_all.py` lists two `cost.*` labels for its skipped-detector table and is
#: correctly NOT matched, because span-less-ness is not what that tuple is about.
MARKER = "hallucination.low_confidence"


#: Literal containers a set-like value can be spelled as.
_LITERALS = (ast.Set, ast.Tuple, ast.List)


def _literal_string_sets(tree: ast.AST) -> list[tuple[int, set[str]]]:
    """Every set/frozenset/tuple/list literal of plain strings, with its line number.

    `frozenset({...})` is reported ONCE, as the call. The inner `ast.Set` is skipped
    because it is the same value spelled twice, not a second definition — counting both
    made the positive control below report `[1, 1]` for a one-line copy, and would have
    made a real offender's line numbers read as duplicates.
    """
    # Two passes: find the literals a frozenset/set call wraps, then walk and skip them.
    # Identity, not line number — two distinct literals can share a line.
    wrapped: set[int] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in {"frozenset", "set"} and node.args
                and isinstance(node.args[0], _LITERALS)):
            wrapped.add(id(node.args[0]))

    found: list[tuple[int, set[str]]] = []
    for node in ast.walk(tree):
        elements: list[ast.expr] | None = None
        if isinstance(node, _LITERALS):
            if id(node) in wrapped:
                continue
            elements = list(node.elts)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id in {"frozenset", "set"} and node.args
              and isinstance(node.args[0], _LITERALS)):
            elements = list(node.args[0].elts)
        if elements is None:
            continue
        values = {e.value for e in elements
                  if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        if values:
            found.append((getattr(node, "lineno", 0), values))
    return found


def _span_less_copies(path: Path) -> list[int]:
    """Line numbers in `path` holding something shaped like the span-less set."""
    tree = ast.parse(path.read_text())
    return [
        line for line, values in _literal_string_sets(tree)
        if MARKER in values and any(v.startswith("cost.") for v in values)
    ]


def _python_files() -> list[Path]:
    return sorted(
        p for directory in SEARCH_DIRS for p in (ROOT / directory).rglob("*.py")
    )


def test_the_set_is_defined_exactly_once() -> None:
    """★ No second definition of the span-less label set anywhere in the scanned tree."""
    offenders = {
        path.relative_to(ROOT).as_posix(): lines
        for path in _python_files()
        if path != SOURCE and (lines := _span_less_copies(path))
    }
    assert not offenders, (
        "span-less label set redefined outside policy/schema.py: "
        + "; ".join(f"{f} (line{'s' if len(l) > 1 else ''} {l})"
                    for f, l in sorted(offenders.items()))
        + ". Import SPAN_LESS_LABELS instead — two copies is one copy plus a latent "
          "divergence (M-9)."
    )


def test_the_detector_finds_a_planted_copy(tmp_path: Path) -> None:
    """★ Positive control: prove the AST walk would actually catch a third copy.

    Without this, `test_the_set_is_defined_exactly_once` passing would be equally
    consistent with a detector that matches nothing at all.
    """
    planted = tmp_path / "sneaky.py"
    planted.write_text(
        "_MY_OWN_SPANLESS = frozenset({\n"
        '    "hallucination.low_confidence",\n'
        '    "cost.budget_exceeded",\n'
        "})\n"
    )
    assert _span_less_copies(planted) == [1]


def test_the_detector_does_not_flag_unrelated_label_groups(tmp_path: Path) -> None:
    """A `cost.*` grouping that is not about spans must not be a false positive.

    This is `eval/run_all.py`'s skipped-detector table, reduced. Flagging it would push a
    future author to import `SPAN_LESS_LABELS` for a purpose it does not serve.
    """
    unrelated = tmp_path / "fine.py"
    unrelated.write_text(
        'SKIPPED = ("cost.budget_exceeded", "cost.request_too_large")\n'
    )
    assert _span_less_copies(unrelated) == []


def test_the_scan_actually_reads_the_files_it_claims_to() -> None:
    """Guards the guard: an empty file list would make the assertion vacuous."""
    files = _python_files()
    assert len(files) > 15, f"only {len(files)} files scanned; the walk is not finding them"
    assert SOURCE in files, "the single source itself must be inside the scanned scope"
    assert _span_less_copies(SOURCE), "the source's own definition must be detectable"


@pytest.mark.parametrize(
    "module", ["eval.policy_matrix", "eval.validate_dataset"]
)
def test_both_consumers_bind_the_same_object(module: str) -> None:
    """★ Identity, not equality: an equal-but-separate copy would pass an `==` check.

    This is the assertion that would have failed before M-9 — the two sets were not equal
    then, and an author fixing that by editing one literal to match the other would have
    left the two-copies problem exactly as it was.
    """
    import importlib

    assert importlib.import_module(module).SPAN_LESS_LABELS is SPAN_LESS_LABELS


def test_request_too_large_is_a_member() -> None:
    """The divergence itself: it is genuinely span-less (request-level), so it belongs.

    The matrix had it, the validator did not. The validator was the one that was wrong —
    `cost.request_too_large` scores a whole request and has no extent to point at.
    """
    assert "cost.request_too_large" in SPAN_LESS_LABELS
