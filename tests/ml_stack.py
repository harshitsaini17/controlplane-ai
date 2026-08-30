"""`requires_ml` — the marker for tests that need the 02 §8 model stack (`.[ml]`).

CI's `verify` job installs the light `[dev]` extra deliberately (see `.github/workflows/ci.yml`),
so `spacy`, `onnxruntime` and `sentence_transformers` are absent there. A test that boots the
gateway against the shipped policies, or that asserts an enrichment actually happened, cannot
pass on such a host: `finance_advisor` maps the Tier-2 classes to `fail_closed`, and ADR-033
then *correctly* refuses the boot. That refusal is the product working, not a bug to route
around — so these tests are **skipped where the stack is absent and RUN where it is present**,
rather than weakened to pass in both places (AGENTS.md §5.4).

The marker is a real one rather than a bare `skipif` because it has to be *selectable*: the
`ml-closure` job runs `-m requires_ml` on a host that installed `[dev,ml]`, which is what keeps
this from becoming a permanently-skipped invariant — the failure mode the workflow's own comment
calls out ("a skipped invariant is not an invariant"). Skipping here and running nowhere would
be strictly worse than the red build it replaced.

`MISSING_ML` is derived from `availability.REQUIREMENTS` — ADR-033's single declaration of which
import each detector needs — and probed with the same `find_spec` the boot manifest uses. A
hand-typed module list here would be a second declaration free to drift from the first.
"""

from __future__ import annotations

import importlib.util

import pytest

from controlplane.detectors.availability import REQUIREMENTS


def _absent(module: str) -> bool:
    """`find_spec`, with its two documented failure modes treated as absence (04 §2, ADR-033)."""
    try:
        return importlib.util.find_spec(module) is None
    except (ImportError, ValueError):
        return True


#: Import names the `ml` extra provides that this host cannot resolve. Empty on an ml host.
MISSING_ML: tuple[str, ...] = tuple(
    sorted({module for modules in REQUIREMENTS.values() for module in modules if _absent(module)})
)

#: Applied per-test. Selected with `-m requires_ml`; skipped by `pytest_collection_modifyitems`
#: in `conftest.py` when `MISSING_ML` is non-empty.
requires_ml = pytest.mark.requires_ml
