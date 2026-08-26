"""FR-GW-006 startup canary — usage-sanity invariant, as ruled by ADR-028.

One canary request at boot, comparing the provider's reported `prompt_tokens` against a
**repo-local estimate**. Measured-class provider fails boot; dev-class warns loudly and
continues (ADR-018).

**The reference is local by ruling, and that is the whole point of ADR-028.** The superseded
form of this invariant compared a provider *endpoint* (`count_tokens`) against a provider
*field* (`usage.prompt_tokens`) — both sides owned by the party being audited, so it was
never an independent check. It also happened to be unimplementable exactly where it
mattered: probed keyless with a control row, `count_tokens` exists on the shipped dev
provider (whose consequence is a warning) and is absent on the shipped measured one (whose
consequence is boot refusal).

**What this detects: gross accounting corruption. What it does not claim: a fine-grained
accounting audit.** A local estimate cannot model a provider's server-side chat template, so
small disagreements are expected and are what `min_delta_floor` absorbs. The failure this
exists to catch is multiplicative — the shipped dev gateway reports 5074 prompt tokens for a
~14-token prompt, a 362x inflation that would corrupt every cost figure derived from it.
Tokenizer variance does not reach 2x; scaffold injection does.

Both conditions must hold to fail, and the conjunction is load-bearing in both directions:
the ratio alone would fail a short prompt over a few chat-template role tokens, and the
absolute floor alone would pass a long prompt whose count was inflated proportionally.

STUB(none — this module is complete. `run_canary` needs a live upstream, so the *call* is
wired by whoever owns app startup; nothing here is deferred.)
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any

from controlplane.gateway.config import GatewayConfig, Provider, UpstreamClass
from controlplane.gateway.ingress import UpstreamError

#: Recorded in every `CanaryResult` (ADR-028 requires the estimator be named in the result).
#: Versioned because changing the divisor changes every verdict this check has ever produced,
#: and a result carrying a bare "estimate" would not say which rule produced it.
ESTIMATOR_NAME = "chars-per-token-v1"

#: The ~4 chars/token heuristic ADR-028 names as the default estimator. Deliberately NOT a
#: real tokenizer: a tokenizer would be a new dependency (02 §8 requires an ADR note) and,
#: more to the point, would not help — its own systematic error against the provider's chat
#: template competes with the threshold, which is precisely the trade-off that made option A
#: unattractive in the deviation report. A crude, dependency-free, deterministic estimate is
#: the right instrument for detecting a 362x discrepancy.
CHARS_PER_TOKEN = 4.0

#: The canary prompt. Fixed, English, and deliberately boring: it must contain nothing a
#: detector would flag — no digits, no addresses, no names — since a canary that tripped the
#: policy engine would confuse a boot failure with a content verdict.
#:
#: **Its LENGTH is load-bearing, and a short prompt silently disables half the invariant.**
#: The two conditions are ANDed, so the ratio bound only ever binds where the band's own
#: width exceeds the absolute floor:
#:
#:     estimate * (max_ratio - 1) > min_delta_floor
#:     estimate * (2.0 - 1)       > 50        ->  estimate > 50 tokens  ->  ~200+ chars
#:
#: Measured with a 31-char prompt (estimate 8) and the shipped knobs: the band is [4, 16],
#: yet nothing failed until reported > 58 — a **5x** inflation passed, because the floor
#: dominated every comparison and `max_ratio` was dead weight. At the length below the
#: ordering inverts and the ratio is what binds, which is the regime ADR-028's rationale
#: assumes ("tokenizer variance is bounded well under 2x").
#:
#: `test_the_ratio_bound_is_operative_at_the_shipped_prompt_length` pins the inequality, so
#: shortening this prompt or raising the floor fails loudly instead of quietly neutering the
#: check.
CANARY_MESSAGES: tuple[dict[str, str], ...] = (
    {
        "role": "user",
        "content": (
            "This is a startup health check for an internal service. Please reply with a "
            "short, plain confirmation that you received this message. Do not add any "
            "extra commentary, formatting, lists, or explanation. A single brief sentence "
            "is all that is needed here."
        ),
    },
)


class UsageSanityWarning(UserWarning):
    """A dev-class provider failed the usage-sanity invariant (FR-GW-006).

    Follows `PricingWarning`'s precedent in `config.py`: loud, named, and raised at boot
    rather than discovered later in a report full of impossible numbers.
    """


class UsageSanityError(RuntimeError):
    """A measured-class provider failed the invariant, so boot is refused (FR-GW-006).

    Deliberately not an `UpstreamError`: that is ERR-UP-001 with 502/retry-yes semantics
    (05 §1.2), and retrying does not fix a provider whose accounting is wrong. This is a
    refusal to start, not a failed request.
    """


def estimate_prompt_tokens(messages: object) -> int:
    """Repo-local prompt-token estimate (ADR-028). Deterministic, no dependency, no network.

    Counts the characters of every message's `content` and divides. Role names and the
    provider's chat-template scaffolding are *not* modelled — that residue is real, bounded
    at a few tokens per message, and is what `min_delta_floor` exists to absorb.

    Rounds up, and never returns less than 1 for non-empty input: a fractional token is not
    a thing a provider can report, and returning 0 would make the ratio undefined.
    """
    if isinstance(messages, (str, bytes)) or not isinstance(messages, (list, tuple)):
        raise TypeError(
            f"messages must be a sequence of message dicts, got {type(messages).__name__}"
        )
    chars = 0
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            chars += len(content)
        elif isinstance(content, (list, tuple)):
            # OpenAI content-parts form: [{"type": "text", "text": "…"}, …]
            for part in content:
                text = part.get("text") if isinstance(part, dict) else None
                if isinstance(text, str):
                    chars += len(text)
    if chars == 0:
        return 0
    return max(1, -(-chars // int(CHARS_PER_TOKEN)))    # ceil, integer-only


@dataclass(frozen=True)
class CanaryResult:
    """One canary outcome. `passed is False` is what the caller acts on.

    Carries the estimator name and both raw numbers rather than only the verdict, so a boot
    log or a report can show *why* — a bare "canary failed" would send the reader back to
    the provider to guess which side was wrong.
    """

    provider: str
    upstream_class: UpstreamClass
    estimator: str
    estimate: int
    #: `None` when the provider reported no usage at all — a distinct state from a wrong
    #: count, and handled as `unverifiable` rather than as a pass. See `evaluate_usage`.
    reported: int | None
    passed: bool
    reason: str
    #: Supplementary cross-checks (ADR-028 allows a provider count endpoint here, never as
    #: the primary reference). Empty on both shipped providers; the field exists so adding
    #: one later cannot be mistaken for changing the reference.
    cross_checks: tuple[dict[str, Any], ...] = ()
    model_used: str | None = None

    @property
    def ratio(self) -> float | None:
        """Reported ÷ estimate, or None when either side is unusable."""
        if self.reported is None or self.estimate <= 0:
            return None
        return self.reported / self.estimate

    @property
    def delta(self) -> int | None:
        if self.reported is None:
            return None
        return abs(self.reported - self.estimate)


def evaluate_usage(
    *,
    provider: Provider,
    estimate: int,
    reported: int | None,
    max_ratio: float,
    min_delta_floor: int,
    model_used: str | None = None,
    cross_checks: tuple[dict[str, Any], ...] = (),
) -> CanaryResult:
    """Apply the ADR-028 fail condition. Pure: no network, no clock, no I/O.

    Split from `run_canary` so the invariant is testable without a provider — the arithmetic
    is the part that must be right, and it should not need a mock transport to exercise.

    Fails only when the reported count is outside `[estimate/max_ratio, estimate*max_ratio]`
    **and** `|reported - estimate| > min_delta_floor`.

    Two states are refusals rather than passes, and neither is in the ruling's fail
    condition because neither is a *miscount*:

    - **No usage reported at all.** A provider that reports nothing cannot be audited, and
      `measured` is precisely the claim that its accounting is trustworthy. Treating an
      absent count as a pass would produce the green check the deviation warned about — a
      canary that always passes because it cannot run is worse than an absent one.
    - **An empty estimate.** The canary prompt is repo-owned and non-empty, so this can only
      mean the estimator was handed nothing; the ratio would be undefined.
    """
    if estimate <= 0:
        return CanaryResult(
            provider=provider.name, upstream_class=provider.upstream_class,
            estimator=ESTIMATOR_NAME, estimate=estimate, reported=reported,
            passed=False, model_used=model_used, cross_checks=cross_checks,
            reason=(
                "the local estimate is zero, so the invariant has no reference to compare "
                "against; the canary prompt must be non-empty (ADR-028)"
            ),
        )
    if reported is None:
        return CanaryResult(
            provider=provider.name, upstream_class=provider.upstream_class,
            estimator=ESTIMATOR_NAME, estimate=estimate, reported=None,
            passed=False, model_used=model_used, cross_checks=cross_checks,
            reason=(
                "the provider reported no prompt-token usage, so its accounting cannot be "
                "checked at all. Unverifiable is not the same as correct, and "
                "`upstream_class: measured` is the claim being checked (ADR-018)"
            ),
        )

    low, high = estimate / max_ratio, estimate * max_ratio
    within_band = low <= reported <= high
    delta = abs(reported - estimate)

    if within_band or delta <= min_delta_floor:
        detail = (
            f"reported {reported} within [{low:.1f}, {high:.1f}]" if within_band
            else f"reported {reported} outside [{low:.1f}, {high:.1f}] but delta {delta} "
                 f"<= floor {min_delta_floor}"
        )
        return CanaryResult(
            provider=provider.name, upstream_class=provider.upstream_class,
            estimator=ESTIMATOR_NAME, estimate=estimate, reported=reported,
            passed=True, model_used=model_used, cross_checks=cross_checks,
            reason=f"usage sanity OK: {detail} (estimate {estimate}, {ESTIMATOR_NAME})",
        )

    return CanaryResult(
        provider=provider.name, upstream_class=provider.upstream_class,
        estimator=ESTIMATOR_NAME, estimate=estimate, reported=reported,
        passed=False, model_used=model_used, cross_checks=cross_checks,
        reason=(
            f"reported prompt_tokens {reported} is {reported / estimate:.1f}x the local "
            f"estimate {estimate} ({ESTIMATOR_NAME}), outside [{low:.1f}, {high:.1f}], and "
            f"the delta {delta} exceeds the floor {min_delta_floor}. The provider's token "
            "accounting is not trustworthy (FR-GW-006, ADR-028)"
        ),
    )


def enforce(result: CanaryResult) -> CanaryResult:
    """Apply the FR-GW-006 consequence by upstream class. Returns the result, or raises.

    `measured` fails boot, `dev` warns loudly and continues. The asymmetry is ADR-018's: a
    measured-class provider that miscounts would silently corrupt every judge-facing number,
    while a dev-class one is already barred from producing them.
    """
    if result.passed:
        return result
    if result.upstream_class is UpstreamClass.MEASURED:
        raise UsageSanityError(
            f"provider {result.provider!r} is upstream_class=measured and failed the "
            f"usage-sanity canary: {result.reason}. Boot is refused — a measured-class "
            "provider whose accounting is wrong would corrupt every cost figure derived "
            "from it (FR-GW-006). Switch `active_provider`, or reclassify it as `dev` and "
            "accept that its numbers may not be published (ADR-018)."
        )
    warnings.warn(
        f"provider {result.provider!r} (upstream_class=dev) failed the usage-sanity "
        f"canary: {result.reason}. Continuing, because dev-class data is already barred "
        "from judge-facing artifacts (ADR-018) — but no cost or token figure from this "
        "provider is a measurement.",
        UsageSanityWarning,
        stacklevel=2,
    )
    return result


async def run_canary(
    dispatcher: Any,
    *,
    config: GatewayConfig | None = None,
    provider: Provider | None = None,
    tier: str = "small",
) -> CanaryResult:
    """Fire one canary request and evaluate it (FR-GW-006). Does NOT enforce — see `enforce`.

    Separated from `enforce` so a caller can log the result before acting on it, and so a
    test can assert the arithmetic without catching an exception.

    An upstream that cannot be reached at all is **not** a usage-sanity failure: it is
    ERR-UP-001, and conflating "the provider is down" with "the provider miscounts" would
    have a transient outage look like an accounting defect. `UpstreamError` propagates.
    """
    cfg = config if config is not None else dispatcher.config
    target = provider or cfg.active
    messages = [dict(m) for m in CANARY_MESSAGES]

    response = await dispatcher.complete(messages, tier=tier, provider=target)
    return evaluate_usage(
        provider=target,
        estimate=estimate_prompt_tokens(messages),
        reported=response.prompt_tokens,
        max_ratio=cfg.usage_sanity.max_ratio,
        min_delta_floor=cfg.usage_sanity.min_delta_floor,
        model_used=response.model_used,
    )


async def canary_on_startup(dispatcher: Any, *, config: GatewayConfig | None = None
                            ) -> CanaryResult | None:
    """Run + enforce, honouring `usage_sanity.canary_on_startup`. Returns None when disabled.

    The single call an app-startup hook needs. Kept here rather than in `app.py` so the
    ordering — run, then enforce — cannot be got wrong by a caller who only wants the check.
    """
    cfg = config if config is not None else dispatcher.config
    if not cfg.usage_sanity.canary_on_startup:
        return None
    return enforce(await run_canary(dispatcher, config=cfg))
