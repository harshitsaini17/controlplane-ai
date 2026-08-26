"""FR-GW-006 startup canary — ADR-028 usage-sanity invariant.

The load-bearing tests here are the ones that pin *why* the invariant is shaped the way it
is: the reference count must be repo-local (so it cannot be the provider's own endpoint),
the two conditions must be ANDed, and the canary prompt must be long enough that the ratio
bound actually binds. That last one is a real defect this suite caught — see
`test_the_ratio_bound_is_operative_at_the_shipped_prompt_length`.

No live network: `httpx.MockTransport` throughout, matching `test_sse_proxy.py`. Async tests
use bare `asyncio.run()` — `pytest_asyncio` is not a declared dependency (02 §8).
"""

from __future__ import annotations

import asyncio
import inspect
import re
import warnings
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from controlplane.gateway.canary import (
    CANARY_MESSAGES,
    CHARS_PER_TOKEN,
    ESTIMATOR_NAME,
    CanaryResult,
    UsageSanityError,
    UsageSanityWarning,
    canary_on_startup,
    enforce,
    estimate_prompt_tokens,
    evaluate_usage,
    run_canary,
)
from controlplane.gateway.config import UpstreamClass, UsageSanity, load_gateway_config
from controlplane.gateway.ingress import UpstreamError
from controlplane.gateway.sse_proxy import UpstreamDispatcher
from controlplane.telemetry.metrics import MetricsRegistry

DOC_01 = Path(__file__).resolve().parents[1] / "docs" / "01-requirements-and-scenarios.md"
DOC_05 = Path(__file__).resolve().parents[1] / "docs" / "05-api-and-data-contracts.md"


@pytest.fixture(scope="module")
def config():
    return load_gateway_config()


#: Fake, and it must never appear in output — the leak assertions in `test_sse_proxy.py`
#: cover the credential path itself; here it only needs to exist so dispatch proceeds.
CANARY_KEY = "sk-canary-fixture-not-a-real-key"


@pytest.fixture
def creds(monkeypatch):
    """`kiro-local` declares `key_env: UPSTREAM_API_KEY` (NFR-SEC-002).

    Without it `auth_headers` raises `UpstreamError` before the canary can dispatch, which
    would make every end-to-end test here fail for a reason unrelated to the invariant.
    """
    monkeypatch.setenv("UPSTREAM_API_KEY", CANARY_KEY)
    return CANARY_KEY


@pytest.fixture
def dev(config):
    return config.provider("kiro-local")


@pytest.fixture
def measured(config):
    return config.provider("groq")


def messages() -> list[dict[str, str]]:
    return [dict(m) for m in CANARY_MESSAGES]


def dispatcher(config, prompt_tokens: int | None, *, model: str = "llama-3.1-8b-instant"):
    """A dispatcher whose upstream reports `prompt_tokens`, or no usage block at all."""
    def handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "id": "cmpl-canary", "model": model,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "ok"}}],
        }
        if prompt_tokens is not None:
            payload["usage"] = {"prompt_tokens": prompt_tokens, "completion_tokens": 2}
        return httpx.Response(200, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return UpstreamDispatcher(config, client=client, metrics=MetricsRegistry())


# --------------------------------------------------------------------------
# The estimator is repo-local (ADR-028's central ruling)
# --------------------------------------------------------------------------


def test_the_estimate_is_computed_locally_with_no_network_and_no_provider() -> None:
    """★ ADR-028: the reference count is repo code, never a provider endpoint.

    Asserted by construction — `estimate_prompt_tokens` takes only the messages. If this
    ever needed a provider, a client or an await, the invariant would be back to auditing
    the audited party with its own instrument.
    """
    assert estimate_prompt_tokens([{"role": "user", "content": "x" * 400}]) == 100
    assert not inspect.iscoroutinefunction(estimate_prompt_tokens)
    assert "provider" not in inspect.signature(estimate_prompt_tokens).parameters


def test_the_estimator_is_named_in_every_result(dev) -> None:
    """★ ADR-028 requires the estimator be NAMED in the canary result.

    Asserts the name has content and a version marker, not merely that it equals itself.
    Blanking `ESTIMATOR_NAME` to `""` survived the first version of this test — `"" ==
    ESTIMATOR_NAME` and `"" in reason` are both vacuously true — which is the tautological
    failure mode 06 §3.1 rule 3 warns about. A result whose estimator is unnamed cannot tell
    a reader which rule produced the verdict, and the divisor is versioned precisely because
    changing it changes every verdict this check has ever produced.
    """
    assert re.fullmatch(r"[a-z][a-z-]*-v\d+", ESTIMATOR_NAME), (
        f"the estimator name must identify a versioned rule, got {ESTIMATOR_NAME!r}"
    )
    result = evaluate_usage(provider=dev, estimate=64, reported=64,
                            max_ratio=2.0, min_delta_floor=50)
    assert result.estimator == ESTIMATOR_NAME
    assert ESTIMATOR_NAME in result.reason

    # And the failing branch names it too — a boot refusal is the case where the reader most
    # needs to know what produced the number.
    failed = evaluate_usage(provider=dev, estimate=14, reported=5074,
                            max_ratio=2.0, min_delta_floor=50)
    assert ESTIMATOR_NAME in failed.reason


def test_the_estimate_is_deterministic() -> None:
    """A boot check that varied run to run would make a boot failure irreproducible."""
    assert len({estimate_prompt_tokens(messages()) for _ in range(20)}) == 1


@pytest.mark.parametrize("chars,expected", [(0, 0), (1, 1), (3, 1), (4, 1), (5, 2), (400, 100)])
def test_the_estimate_rounds_up_and_never_returns_zero_for_real_text(
    chars: int, expected: int
) -> None:
    """Ceil, not floor: a fractional token is not something a provider can report.

    Zero for non-empty input would make the ratio undefined and hand the invariant an
    unusable reference.
    """
    assert estimate_prompt_tokens([{"role": "user", "content": "x" * chars}]) == expected


def test_the_estimate_reads_openai_content_parts() -> None:
    """The content-parts form is real OpenAI shape; missing it would undercount badly."""
    parts = [{"role": "user", "content": [{"type": "text", "text": "y" * 40},
                                          {"type": "text", "text": "z" * 40}]}]
    assert estimate_prompt_tokens(parts) == estimate_prompt_tokens(
        [{"role": "user", "content": "q" * 80}]
    )


@pytest.mark.parametrize("bad", ["a string", b"bytes", 12, None])
def test_a_non_sequence_of_messages_is_a_type_error(bad: object) -> None:
    """A bare string is iterable, so the permissive reading would count characters as messages."""
    with pytest.raises(TypeError, match="sequence of message dicts"):
        estimate_prompt_tokens(bad)


# --------------------------------------------------------------------------
# The fail condition — both halves, ANDed
# --------------------------------------------------------------------------


def test_the_adr018_documented_inflation_is_caught(dev) -> None:
    """★ The failure this requirement exists for: 5074 reported for a ~14-token prompt.

    Uses the figures recorded in ADR-018 / `config/gateway.yaml`, not invented ones.
    """
    result = evaluate_usage(provider=dev, estimate=14, reported=5074,
                            max_ratio=2.0, min_delta_floor=50)
    assert result.passed is False
    assert result.ratio is not None and result.ratio > 300
    assert "not trustworthy" in result.reason


def test_an_honest_count_passes(dev) -> None:
    result = evaluate_usage(provider=dev, estimate=64, reported=68,
                            max_ratio=2.0, min_delta_floor=50)
    assert result.passed is True
    assert "usage sanity OK" in result.reason


def test_outside_the_band_but_under_the_floor_passes(dev) -> None:
    """★ The AND is load-bearing: the floor absorbs chat-template overhead.

    Ratio 4.0x — far outside the band — but only 24 tokens apart, which is what a few role
    tokens on a short prompt look like. Failing this would refuse boot over nothing.
    """
    result = evaluate_usage(provider=dev, estimate=8, reported=32,
                            max_ratio=2.0, min_delta_floor=50)
    assert result.passed is True
    assert "<= floor" in result.reason


def test_over_the_floor_but_inside_the_band_passes(dev) -> None:
    """The other half of the AND: a big absolute delta on a big prompt is proportionate."""
    result = evaluate_usage(provider=dev, estimate=1000, reported=1400,
                            max_ratio=2.0, min_delta_floor=50)
    assert result.passed is True
    assert result.delta == 400, "delta far exceeds the floor, yet the ratio is only 1.4x"


def test_failing_requires_both_conditions(dev) -> None:
    """Neither condition alone fails; together they do."""
    only_ratio = evaluate_usage(provider=dev, estimate=8, reported=40,
                                max_ratio=2.0, min_delta_floor=50)
    only_delta = evaluate_usage(provider=dev, estimate=1000, reported=1400,
                               max_ratio=2.0, min_delta_floor=50)
    both = evaluate_usage(provider=dev, estimate=64, reported=200,
                          max_ratio=2.0, min_delta_floor=50)
    assert (only_ratio.passed, only_delta.passed, both.passed) == (True, True, False)


def test_a_low_report_is_caught_too(dev) -> None:
    """The band is two-sided. Under-reporting understates cost just as badly."""
    result = evaluate_usage(provider=dev, estimate=1000, reported=100,
                            max_ratio=2.0, min_delta_floor=50)
    assert result.passed is False


def test_the_ratio_bound_is_operative_at_the_shipped_prompt_length(config) -> None:
    """★ A short canary prompt silently disables half the invariant.

    The conditions are ANDed, so `max_ratio` only binds where the band's own width exceeds
    the absolute floor:

        estimate * (max_ratio - 1) > min_delta_floor

    Measured with a 31-char prompt (estimate 8) and the shipped knobs, a **5x** inflation
    passed: the band was [4, 16] but nothing failed until the delta cleared 50, so
    `max_ratio` was dead weight. This pins the inequality, so shortening the prompt or
    raising the floor fails here instead of quietly neutering the check.
    """
    sanity = config.usage_sanity
    estimate = estimate_prompt_tokens(messages())
    band_width = estimate * (sanity.max_ratio - 1)
    assert band_width > sanity.min_delta_floor, (
        f"canary prompt estimates {estimate} tokens, so the ratio band is only "
        f"{band_width:.0f} tokens wide against a floor of {sanity.min_delta_floor}; the "
        "ratio bound would never bind. Lengthen CANARY_MESSAGES (ADR-028)."
    )
    # And prove it end to end: a 2.5x inflation must fail at this prompt length.
    inflated = evaluate_usage(
        provider=config.provider("kiro-local"), estimate=estimate,
        reported=int(estimate * 2.5), max_ratio=sanity.max_ratio,
        min_delta_floor=sanity.min_delta_floor,
    )
    assert inflated.passed is False


def test_the_canary_prompt_carries_nothing_a_detector_would_flag() -> None:
    """A canary that tripped the policy engine would look like a boot failure."""
    text = " ".join(m["content"] for m in CANARY_MESSAGES)
    assert not re.search(r"\d", text), "digits could read as PII or an unsourced numeric"
    assert "@" not in text


# --------------------------------------------------------------------------
# Unverifiable is not the same as correct
# --------------------------------------------------------------------------


def test_a_provider_reporting_no_usage_fails_rather_than_passes(dev) -> None:
    """★ "A canary that always passes because it cannot run is worse than an absent one."

    This is the exact trap the deviation report named: an unverifiable provider must not
    render as a green check. `measured` is the claim that accounting is trustworthy.
    """
    result = evaluate_usage(provider=dev, estimate=64, reported=None,
                            max_ratio=2.0, min_delta_floor=50)
    assert result.passed is False
    assert result.ratio is None and result.delta is None
    assert "cannot be checked" in result.reason


def test_an_empty_estimate_fails_rather_than_dividing_by_zero(dev) -> None:
    result = evaluate_usage(provider=dev, estimate=0, reported=64,
                            max_ratio=2.0, min_delta_floor=50)
    assert result.passed is False
    assert "no reference" in result.reason


# --------------------------------------------------------------------------
# FR-GW-006 consequence by class (ADR-018) — unchanged by ADR-028
# --------------------------------------------------------------------------


def test_a_measured_class_failure_refuses_boot(measured) -> None:
    """★ FR-GW-006: measured-class fails boot. Its numbers may be published."""
    result = evaluate_usage(provider=measured, estimate=14, reported=5074,
                            max_ratio=2.0, min_delta_floor=50)
    assert result.upstream_class is UpstreamClass.MEASURED
    with pytest.raises(UsageSanityError, match="Boot is refused"):
        enforce(result)


def test_a_dev_class_failure_warns_loudly_and_continues(dev) -> None:
    """★ FR-GW-006: dev-class warns and continues — it is already barred from reports."""
    result = evaluate_usage(provider=dev, estimate=14, reported=5074,
                            max_ratio=2.0, min_delta_floor=50)
    with pytest.warns(UsageSanityWarning, match="no cost or token figure"):
        returned = enforce(result)
    assert returned is result, "enforce returns the result so a caller can still log it"


def test_a_passing_canary_neither_raises_nor_warns(measured) -> None:
    result = evaluate_usage(provider=measured, estimate=64, reported=64,
                            max_ratio=2.0, min_delta_floor=50)
    with warnings.catch_warnings():
        warnings.simplefilter("error")          # any warning at all fails this test
        assert enforce(result) is result


def test_the_error_is_not_an_upstream_error(measured) -> None:
    """ERR-UP-001 is 502/retry-yes (05 §1.2); retrying does not fix wrong accounting."""
    result = evaluate_usage(provider=measured, estimate=14, reported=5074,
                            max_ratio=2.0, min_delta_floor=50)
    with pytest.raises(UsageSanityError) as caught:
        enforce(result)
    assert not isinstance(caught.value, UpstreamError)


# --------------------------------------------------------------------------
# End to end against a mock upstream
# --------------------------------------------------------------------------


def test_run_canary_fires_one_request_and_evaluates_it(config, creds) -> None:
    estimate = estimate_prompt_tokens(messages())
    result = asyncio.run(run_canary(dispatcher(config, prompt_tokens=estimate)))
    assert result.passed is True
    assert result.estimate == estimate
    assert result.reported == estimate
    assert result.model_used == "llama-3.1-8b-instant"


def test_run_canary_catches_an_inflating_upstream(config, creds) -> None:
    """The ADR-018 bug, end to end through the real dispatcher."""
    result = asyncio.run(run_canary(dispatcher(config, prompt_tokens=5074)))
    assert result.passed is False


def test_run_canary_treats_a_missing_usage_block_as_unverifiable(config, creds) -> None:
    result = asyncio.run(run_canary(dispatcher(config, prompt_tokens=None)))
    assert result.passed is False and result.reported is None


def test_an_unreachable_upstream_is_not_a_usage_failure(config, creds) -> None:
    """★ "The provider is down" must not be reported as "the provider miscounts".

    ERR-UP-001 propagates; conflating the two would make a transient outage look like an
    accounting defect and (on a measured provider) refuse boot for the wrong reason.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    disp = UpstreamDispatcher(config, client=client, metrics=MetricsRegistry())
    with pytest.raises(UpstreamError):
        asyncio.run(run_canary(disp))


def test_canary_on_startup_respects_the_config_switch(config) -> None:
    disabled = config.model_copy(deep=True)
    disabled.usage_sanity.canary_on_startup = False
    assert asyncio.run(canary_on_startup(dispatcher(config, prompt_tokens=64),
                                         config=disabled)) is None


def test_canary_on_startup_enforces(config, creds) -> None:
    """The one call a startup hook needs: run, then enforce, in that order."""
    with pytest.warns(UsageSanityWarning):
        result = asyncio.run(canary_on_startup(dispatcher(config, prompt_tokens=5074)))
    assert result is not None and result.passed is False


# --------------------------------------------------------------------------
# The config contract (05 §6.1) — differential against the doc
# --------------------------------------------------------------------------


def test_the_usage_sanity_keys_match_05_6_1() -> None:
    """Differential: parse the doc's `usage_sanity` block, compare to the model's fields.

    Parses rather than restating the key list, so drift on either side fails.
    """
    block = DOC_05.read_text().split("usage_sanity:", 1)[1].split("```", 1)[0]
    documented = set(re.findall(r"^  ([a-z_]+):", block, re.M))
    assert documented == set(UsageSanity.model_fields), (
        f"05 §6.1 documents {sorted(documented)}, model has "
        f"{sorted(UsageSanity.model_fields)}"
    )


def test_method_admits_only_the_local_estimate() -> None:
    """★ ADR-028 made this structural: no provider endpoint is ever the sole reference."""
    with pytest.raises(ValidationError):
        UsageSanity(canary_on_startup=True, method="count_tokens",
                    max_ratio=2.0, min_delta_floor=50)


def test_max_ratio_must_exceed_one() -> None:
    """At exactly 1.0 the band collapses and any variance at all refuses boot."""
    with pytest.raises(ValidationError):
        UsageSanity(canary_on_startup=True, max_ratio=1.0, min_delta_floor=50)


def test_the_superseded_knob_is_gone_from_the_docs() -> None:
    """★ `max_token_delta` and the `count_tokens` reference are withdrawn, not merely unused.

    A doc still specifying the old comparison would leave the next implementer building the
    invariant ADR-028 rejected.
    """
    fr = next(line for line in DOC_01.read_text().splitlines() if "FR-GW-006" in line)
    assert "max_token_delta" not in fr
    assert "repo-local" in fr, "FR-GW-006 must state where the reference count comes from"

    schema = DOC_05.read_text().split("usage_sanity:", 1)[1].split("```", 1)[0]
    assert "max_token_delta" not in schema
