"""The runner's parametric ceiling — ADR-034 Part C, wired at `pipeline.run_lane`.

ADR-034 Part C says "`pipeline.py:280` consumes the resolved value". It did not: it indexed
`BUDGETS_MS[name]` and handed the result to `asyncio.wait_for`, which for the one parametric
entry is a `ParametricBudget` **object**. The failure that produces is the nastiest available
shape — `DetectorError: detector 'tier2_injection' raised TypeError`, i.e. a wiring defect
wearing a detector fault's clothes, resolved under `fail_mode` like a real one. It was latent
only because `tier2_injection` is not in `LIVE` yet, so it would have fired on the first request
after the detector landed, not in any test that existed.

So the load-bearing test here is the **negative** one: a parametric detector placed in `LIVE`
must not fault. The rest pin the two-tier guarantee that makes the ceiling worth having.
"""

from __future__ import annotations

import asyncio

import pytest

from controlplane.detectors.base import (
    BUDGETS_MS,
    ParametricBudget,
    Signal,
    Stage,
    budget_ms,
    ceiling_ms,
)
from controlplane.detectors.windowing import windows_for_tokens
from controlplane.gateway import pipeline
from controlplane.gateway.ingress import ResolvedRequest
from controlplane.policy.store import PolicyStore

STORE = PolicyStore()
STORE.load()


def _request(use_case: str = "support_bot") -> ResolvedRequest:
    return ResolvedRequest(
        request_id="req-parametric-ceiling",
        use_case=use_case,
        policy=STORE.get(use_case),
        stream=False,
        messages=[{"role": "user", "content": "hello"}],
    )


class _Sleeper:
    """Stands in for `tier2_injection`: yields to the loop, so `wait_for` can act on it."""

    name = "tier2_injection"

    def __init__(self, sleep_ms: float) -> None:
        self._sleep_s = sleep_ms / 1000.0

    async def detect(self, ctx: object) -> list[Signal]:
        await asyncio.sleep(self._sleep_s)
        return []


def _run_input_lane(detector: object, monkeypatch: pytest.MonkeyPatch,
                    use_case: str = "support_bot") -> pipeline.LaneResult:
    monkeypatch.setitem(pipeline.LIVE, "tier2_injection", detector)
    return asyncio.run(
        pipeline.run_lane(Stage.INPUT, "hello", _request(use_case), pipeline.Coverage())
    )


def test_the_registry_entry_is_still_not_a_number() -> None:
    """The premise. If this ever becomes a float, every test below is theatre."""
    assert isinstance(BUDGETS_MS["tier2_injection"], ParametricBudget)


def test_a_parametric_detector_in_the_lane_does_not_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE regression. Indexing `BUDGETS_MS` here raised TypeError inside the wrapper.

    Asserted on `failures` rather than on the exception type, because that is what the defect
    actually produced: the wrapper normalizes everything into `DetectorError`, so the bug did
    not crash the request — it recorded a detector fault for a detector that worked, and let
    `fail_mode` act on it. `finance_advisor`'s `tier2: fail_closed` would have blocked every
    request carrying an input-lane injection scan.
    """
    result = _run_input_lane(_Sleeper(1.0), monkeypatch)
    assert result.failures == (), (
        f"parametric budget faulted the lane: {[f.error_class for f in result.failures]}"
    )


def test_the_ceiling_admits_a_multi_window_scan_that_a_flat_budget_would_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The substance of ADR-034, not just the absence of a crash.

    A detector slower than one window's 25 ms budget but far inside its length-scaled envelope
    must survive. If the runner ever regresses to the flat `nominal_ms`, this detector gets
    cancelled at 25 ms — which is the exact defect the ADR exists to remove, and it is
    invisible to a test that only checks the ceiling *number*.
    """
    slow = 40.0
    assert slow > budget_ms("tier2_injection"), "fixture no longer exceeds the per-window budget"
    result = _run_input_lane(_Sleeper(slow), monkeypatch)
    assert result.failures == (), "a within-envelope scan was cancelled by the runner ceiling"


def test_the_real_ceiling_is_finite_and_looser_than_the_per_window_budget() -> None:
    """The ceiling's *magnitude*, checked arithmetically rather than by sleeping through it.

    Split from the firing test below on purpose. At the `support_bot` bound the real ceiling is
    ~5.6 s, so proving it fires by sleeping past it would put a 6-second wait in every suite run
    — and 11 s for `hr_copilot`. The two properties are independent: this one says the number is
    right, the next says the mechanism works.
    """
    for bound in (4000, 8000):
        ceiling = ceiling_ms("tier2_injection", windows_for_tokens(bound))
        assert ceiling == pytest.approx(
            BUDGETS_MS["tier2_injection"].resolve(windows_for_tokens(bound))
        )
        assert budget_ms("tier2_injection") < ceiling < 60_000, (
            f"ceiling at the {bound}-token bound is {ceiling} ms — either tighter than one "
            "window's budget (false timeouts) or effectively absent"
        )


def test_the_ceiling_is_still_a_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    """A liveness backstop that never fires is not a backstop.

    Kept alongside the admitting case deliberately: the two together say the ceiling is loose,
    not absent — either alone is satisfied by a bug (a ceiling of infinity passes the first, a
    ceiling of zero passes this one).

    Runs against a **scaled-down** parametric entry rather than the shipped ~5.6 s one, so the
    test costs milliseconds. What is under test is the wiring — `isinstance` -> `resolve(units)`
    -> `wait_for` — and that path is identical at any magnitude. The magnitude itself is pinned
    above, and by `test_detector_base.py`, which re-derives both grounding figures from the
    measurement artifact. Substituting a *smaller* budget cannot make a broken ceiling look like
    a working one: if the runner ignored the parametric entry it would fall back to a value that
    is larger, and this detector would pass rather than time out.
    """
    scaled = ParametricBudget(nominal_ms=5.0, per_unit_ms=0.1, fixed_ms=0.1)
    monkeypatch.setitem(BUDGETS_MS, "tier2_injection", scaled)
    ceiling = ceiling_ms("tier2_injection", windows_for_tokens(4000))
    assert ceiling < 50.0, f"scaled fixture is not cheap enough to sleep past: {ceiling} ms"

    result = _run_input_lane(_Sleeper(ceiling + 50.0), monkeypatch)
    # `DetectorHang`, not `DetectorTimeout`, since ADR-036: `_Sleeper` awaits, so it consumes no
    # attributable CPU and cannot breach an NFR-P-002 budget. The property under test is
    # unchanged and is the whole point of the test — the parametric ceiling still *stops* a
    # detector that runs past its envelope. Only the name of the finding moved, and it moved
    # toward the truth: this detector did not overrun a budget, it failed to come back.
    assert [f.error_class for f in result.failures] == ["DetectorHang"], (
        f"a detector past its envelope was not stopped: {result.failures}"
    )


def test_backstop_units_come_from_the_policy_bound_not_the_request() -> None:
    """ADR-034 Part C: the coarse tier reads `per_request_max_tokens`, per use case.

    Pinned per use case because the two shipped bounds differ (4000 / 8000), so a hardcoded 53
    would silently under-provision `hr_copilot` — halving its ceiling against its own measured
    envelope, which is the direction that causes false timeouts.
    """
    assert pipeline.backstop_units(_request("support_bot")) == 53
    assert pipeline.backstop_units(_request("hr_copilot")) == 105
    for use_case in STORE.use_cases:
        request = _request(use_case)
        assert pipeline.backstop_units(request) == windows_for_tokens(
            request.policy.budget.per_request_max_tokens
        )


def test_the_backstop_ignores_the_request_text_by_design() -> None:
    """Not an oversight — M-31. The runner must not tokenize, so it cannot know the real length.

    A character bound was the first draft and was withdrawn on measurement (chars/token 1.00 to
    800 against a corpus median of 4.29). Pinned so a later reader does not "tighten" this into
    the unsound version: the exact envelope belongs to the detector, which tokenizes once.
    """
    short, long = _request(), _request()
    long.messages = [{"role": "user", "content": "word " * 5000}]
    assert pipeline.backstop_units(short) == pipeline.backstop_units(long)


@pytest.mark.parametrize("name", [n for n, e in BUDGETS_MS.items()
                                 if not isinstance(e, ParametricBudget)])
def test_flat_budgets_are_untouched_by_the_unit_count(name: str) -> None:
    """Part C's compatibility claim: "every other entry stays a flat float".

    Every flat detector, not a sample — the claim is universal and the mapping is short enough
    to hold it to that.
    """
    assert ceiling_ms(name, 1) == ceiling_ms(name, 53) == budget_ms(name) == BUDGETS_MS[name]


def test_the_windowing_module_stays_importable_without_the_model_stack() -> None:
    """`windowing` is read on every request, so it must not acquire a heavy dependency.

    Enforced structurally rather than by importing under a mask: this module is already imported
    by the time any test runs, so a mask-and-reimport would prove nothing about *this* process.
    Reading the source's own import statements is what actually holds the property.
    """
    import ast
    from pathlib import Path

    src = Path(pipeline.__file__).parent.parent / "detectors" / "windowing.py"
    tree = ast.parse(src.read_text())
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert roots <= {"math", "__future__"}, (
        f"windowing.py grew dependencies beyond the stdlib: {sorted(roots - {'math', '__future__'})}"
    )


def test_the_harness_and_production_share_one_geometry_definition() -> None:
    """The point of the move: `102 + (n-1) * 76` exists once.

    Identity, not equality — the harness must re-export the production objects rather than define
    its own agreeing copy, because two copies that agree today are the defect this repo keeps
    finding. Compared by identity so a re-introduced duplicate fails even while it still agrees.
    """
    harness = pytest.importorskip("eval.spike_window_latency")
    from controlplane.detectors import windowing

    for name in ("WINDOW_TOKENS", "WINDOW_OVERLAP", "WINDOW_CONTENT_TOKENS", "WINDOW_STEP"):
        assert getattr(harness, name) == getattr(windowing, name)
    assert harness.coverage_tokens is windowing.coverage_tokens
    assert harness.windows_for_tokens is windowing.windows_for_tokens
