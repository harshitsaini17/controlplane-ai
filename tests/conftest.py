"""Suite-wide collection rules.

Currently one: turn the `requires_ml` marker into a skip on hosts without the 02 §8 model
stack. The skip lives here rather than in the marker so the marker stays a pure *selector* —
`ml-closure` runs `-m requires_ml` and needs those tests to be collected AND executed, which a
`skipif` baked into the decorator would prevent on the very host that can run them.
"""

from __future__ import annotations

import pytest

from tests.ml_stack import MISSING_ML


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "requires_ml: needs the `.[ml]` model stack (spacy / onnxruntime / "
        "sentence_transformers); skipped where absent, run by the ml-closure CI job",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip `requires_ml` tests only when the stack is genuinely absent."""
    if not MISSING_ML:
        return
    skip = pytest.mark.skip(
        reason=f"needs the .[ml] model stack; missing: {', '.join(MISSING_ML)}"
    )
    for item in items:
        if "requires_ml" in item.keywords:
            item.add_marker(skip)
