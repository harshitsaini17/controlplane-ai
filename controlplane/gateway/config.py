"""Gateway upstream config: `config/gateway.yaml` loader + ADR-018 provenance guard.

Implements the amended 05 §6.1 schema (provider list, `upstream_class`, tier binding,
`usage_sanity`) and the ADR-018 rule that **dev-class data may never reach a
judge-facing artifact**. `eval/` and `demo/` call `require_measured_upstream()` before
producing output and `taint_output_path()` when `--allow-dev` overrides the refusal.

Why this lives in one module rather than in each entry point: the refusal is only worth
anything if it is impossible to forget. One import, one call, one test suite — rather
than the same three lines re-derived in five scripts (AGENTS.md §7).

STUB(FR-GW-006 canary not implemented here, phase-2): this module supplies the
`usage_sanity` knobs the boot canary reads, but the canary itself needs a live upstream
call and belongs with the gateway app.
"""

from __future__ import annotations

import datetime
import enum
import warnings
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "CONFIG_PATH",
    "TAINT_MARKER",
    "UNMETERED",
    "GatewayConfig",
    "ModelPrice",
    "PriceTable",
    "PricingWarning",
    "Provider",
    "TaintedDataError",
    "Tiers",
    "UpstreamClass",
    "UsageSanity",
    "load_gateway_config",
    "require_measured_upstream",
    "taint_output_path",
]

#: Repo-relative location of the upstream config (05 §6).
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "gateway.yaml"

#: Inserted into any filename produced from dev-class data. Deliberately shouty: the
#: point is that a tainted report cannot be mistaken for a measurement at a glance.
TAINT_MARKER = "DEV-TAINTED"

#: The literal scalar that may stand in place of a `pricing` block (ADR-022). It is an
#: *affirmative* claim that no per-token charge exists — local compute — and it yields
#: `est_cost_usd == 0.0`, a measurement. `pricing: null` is the different claim that no
#: price information exists, and yields `None`. Zero and unknown are not the same fact.
UNMETERED = "unmetered"


class PricingWarning(UserWarning):
    """A measured-class provider carries no price information at all (ADR-022).

    Legal — a provider can be declared before its prices are known — but it is warned by
    name at boot rather than discovered later in a report full of nulls.
    """


class UpstreamClass(str, enum.Enum):
    """ADR-018 provenance claim — see 05 §6.1.

    This is not a quality label. `MEASURED` asserts the provider's token accounting and
    prices are trustworthy, so data produced through it may carry judge-facing numbers.
    `DEV` asserts the opposite: convenient for development, but its usage accounting is
    **not a measurement**, and data from it is tainted.
    """

    DEV = "dev"
    MEASURED = "measured"


class Tiers(BaseModel):
    """Tier name -> concrete provider model id (ADR-009's two-tier cascade).

    `None` means the provider cannot serve that tier. Both-`None` is legal for a
    declared-but-not-yet-working provider (see `ollama-local`, Q-10) — but not for the
    active one, which `GatewayConfig` enforces.
    """

    model_config = ConfigDict(extra="forbid")

    small: str | None = None
    frontier: str | None = None

    def resolve(self, tier: str) -> str | None:
        """Concrete model id for `tier`, or None if this provider cannot serve it.

        Refuses a name outside 05 §6.1's vocabulary instead of answering it. A bare
        `getattr` returns a dict for `resolve("model_config")` and a bound method for
        `resolve("dict")`, and either would travel onward as the `model` field of a
        dispatch — a garbage value wearing the shape of a resolution. The vocabulary is
        read off the field set rather than restated, so it cannot drift from the two
        fields above it.

        `KeyError` follows `GatewayConfig.provider`'s treatment of an unknown name, and
        is the honest class for what this is: a caller bug. It is deliberately not an
        `UpstreamError` — that is ERR-UP-001, whose 502/retry-yes semantics (05 §1.2)
        would have a client retry a typo forever. It is also distinct from `None`, which
        is a real provider answering that it cannot serve a real tier.
        """
        if tier not in type(self).model_fields:
            raise KeyError(
                f"unknown tier {tier!r}; 05 §6.1 defines exactly "
                f"{sorted(type(self).model_fields)}"
            )
        return getattr(self, tier)


class ModelPrice(BaseModel):
    """USD per 1K tokens for one concrete model id.

    Split in/out because output tokens cost several times input tokens at every provider
    we price, and a single blended rate would misreport any workload whose ratio differs
    from whatever mix the blend assumed.
    """

    model_config = ConfigDict(extra="forbid")

    per_1k_in: float = Field(ge=0.0)
    per_1k_out: float = Field(ge=0.0)


class PriceTable(BaseModel):
    """Per-model prices plus their provenance (ADR-022, 05 §6.1).

    `source_url` and `retrieved` are required, not decorative. A price is a claim about
    the world that expires; an unattributed one cannot be re-checked, and a stale price
    is a wrong price. `source_url` must name a page that actually contains the figures —
    pointing at a canonical-but-empty pricing URL is worse than leaving it blank, because
    it manufactures confidence.
    """

    model_config = ConfigDict(extra="forbid")

    source_url: str = Field(min_length=1)
    retrieved: datetime.date
    models: dict[str, ModelPrice] = Field(min_length=1)


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    upstream_class: UpstreamClass
    base_url: str = Field(min_length=1)
    #: Env var *NAME* only — the value lives in `.env` and is never read into config
    #: (NFR-SEC-002). `None` for providers needing no credential.
    key_env: str | None = None
    #: One of the three ADR-022 states: a `PriceTable`, the literal `"unmetered"`, or
    #: `None`. The union is deliberately not collapsed to a nullable table — see
    #: `UNMETERED` for why the two non-table states mean different things.
    pricing: PriceTable | Literal["unmetered"] | None = None
    tiers: Tiers = Field(default_factory=Tiers)

    def price_for(self, model_id: str) -> ModelPrice | None:
        """Price for one concrete model id, or `None` when the price is UNKNOWN.

        `None` is returned for both `pricing: null` and a model absent from a declared
        `pricing.models` table — in each case no price information exists for this model,
        which is the state ADR-022 requires be propagated as null rather than guessed.

        `pricing: unmetered` resolves to a genuine zero for every model, because that is
        an affirmative claim about local compute rather than an absence. Callers must
        keep the distinction: 0.0 is a measurement, `None` is not a number at all.
        """
        if self.pricing is None:
            return None
        if self.pricing == UNMETERED:
            return ModelPrice(per_1k_in=0.0, per_1k_out=0.0)
        return self.pricing.models.get(model_id)

    def can_price(self, model_id: str) -> bool:
        """Whether a cost figure may be computed for `model_id` at all.

        Per-model, not per-provider: ADR-022 keys prices by concrete model id precisely
        because one provider serves both cascade tiers at ~12x different rates, so
        "can this provider price?" is not a well-formed question.

        Not a validation rule at runtime, deliberately — the boot ladder in
        `GatewayConfig` is where a missing price becomes loud. In the hot path the guard
        belongs where the number is produced: a caller computing cost must check this and
        record null rather than let an absence read as $0.00.
        """
        return self.price_for(model_id) is not None

    def est_cost_usd(self, model_id: str, tokens_in: int, tokens_out: int) -> float | None:
        """Cost for one request, or `None` when this model has no known price.

        Never estimated and never averaged across tiers (ADR-022): an average would erase
        the exact ~12x tier gap the cost plane exists to measure, and a fallback figure
        would be a fabricated measurement. `None` is the honest return, and the caller
        that receives it must write null into `est_cost_usd` and increment
        `cp_pricing_missing_total` (05 §5).

        STUB(the metric increment is the caller's, and `telemetry/metrics.py` is still a
        docstring stub — so nothing counts these yet. This function is the arithmetic
        only; wiring the counter belongs with the cost plane in phase 2.)
        """
        price = self.price_for(model_id)
        if price is None:
            return None
        return (tokens_in / 1000.0) * price.per_1k_in + (
            tokens_out / 1000.0
        ) * price.per_1k_out

    @property
    def priced_tier_models(self) -> dict[str, str]:
        """`{tier: model_id}` for tiers this provider actually binds."""
        return {
            tier: model
            for tier in ("small", "frontier")
            if (model := self.tiers.resolve(tier)) is not None
        }


class UsageSanity(BaseModel):
    """FR-GW-006 knobs for the startup canary, as ruled by ADR-028.

    The reference count is **repo-local**. The superseded form of this invariant compared
    one provider endpoint (`count_tokens`) against another provider field
    (`usage.prompt_tokens`) — never an independent check, because both sides belong to the
    party being audited. It appeared to work only because the shipped dev provider inflates
    one side and not the other.
    """

    model_config = ConfigDict(extra="forbid")

    canary_on_startup: bool
    #: `Literal`, not an enum with room to grow, and that is the ruling made structural:
    #: ADR-028 says no provider endpoint is *ever* the sole reference, so there is no second
    #: value to offer. A provider count endpoint may appear only as a supplementary row in
    #: the canary result, which is not a `method`.
    method: Literal["local_estimate"] = "local_estimate"
    #: Multiplicative bound. Reported prompt tokens must land inside
    #: `[estimate / max_ratio, estimate * max_ratio]`. Ratio rather than a flat delta
    #: because tokenizer variance is bounded well under 2x while scaffold injection is
    #: multiplicative — the shipped dev provider reports 5074 for a ~14-token prompt.
    #: Must exceed 1.0: at exactly 1.0 the band collapses and any variance fails boot.
    max_ratio: float = Field(gt=1.0)
    #: Absolute floor, in tokens, on `|reported - estimate|`. Both conditions must hold to
    #: fail, so this is what stops a short canary prompt from failing on chat-template
    #: overhead — a few added role tokens can breach a 2x ratio while meaning nothing.
    min_delta_floor: int = Field(ge=0)


class GatewayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_table_version: int = Field(ge=1)
    providers: list[Provider] = Field(min_length=1)
    active_provider: str
    usage_sanity: UsageSanity

    @model_validator(mode="after")
    def _validate_provider_graph(self) -> GatewayConfig:
        names = [p.name for p in self.providers]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError(
                f"duplicate provider name(s): {', '.join(duplicates)}; "
                "`active_provider` would be ambiguous"
            )
        if self.active_provider not in names:
            raise ValueError(
                f"active_provider {self.active_provider!r} is not a declared provider "
                f"(declared: {', '.join(names)})"
            )
        self._check_price_coverage()
        active = next(p for p in self.providers if p.name == self.active_provider)
        if active.tiers.small is None and active.tiers.frontier is None:
            raise ValueError(
                f"active provider {active.name!r} binds no tier to a model id, so no "
                "request can be dispatched. A declared-but-unusable provider may sit in "
                "`providers` with null tiers, but it cannot be the active one."
            )
        return self

    def _check_price_coverage(self) -> None:
        """ADR-022 boot ladder: warn on an unpriced provider, refuse an unpriced route.

        **Scoped to measured-class providers, and that scope is load-bearing.** 05 §6.1
        lists the hard-failure row as "missing at boot *and* named in `tiers`", refining
        the warning row above it, which is measured-class. Read as class-agnostic instead,
        it would refuse to boot the shipped dev-class `kiro-local` — whose whole purpose
        under ADR-018 is to be usable *while* unpriceable, since its numbers are barred
        from judge-facing artifacts anyway. Bricking the documented development path to
        protect a report that can never be produced from it is the wrong trade, so
        ADR-018's dev-class semantics win here.

        For a measured-class provider the reasoning inverts: its data is allowed to carry
        judge-facing numbers, so an unpriced model on a routing path *will* answer real
        requests and mint audit records that can never be costed. That is a config bug
        discoverable at boot, and 05 §6.1 makes it fatal rather than let it surface as a
        column of nulls after the run.
        """
        for provider in self.providers:
            if provider.upstream_class is not UpstreamClass.MEASURED:
                continue
            unpriced = {
                tier: model
                for tier, model in provider.priced_tier_models.items()
                if not provider.can_price(model)
            }
            if unpriced:
                detail = ", ".join(
                    f"{tier}={model!r}" for tier, model in sorted(unpriced.items())
                )
                raise ValueError(
                    f"measured-class provider {provider.name!r} binds {detail} to a "
                    "model with no entry in `pricing.models`, so it sits on a routing "
                    "path and would answer requests that can never be costed "
                    "(ADR-022, 05 §6.1). Add the price, or bind the tier to a priced "
                    "model."
                )
            if provider.pricing is None:
                warnings.warn(
                    f"measured-class provider {provider.name!r} declares "
                    "`pricing: null`, so every cost figure from it will be null. Legal, "
                    "but note `unmetered` is the different — and affirmative — claim "
                    "that no per-token charge exists (ADR-022).",
                    PricingWarning,
                    stacklevel=2,
                )

    @property
    def active(self) -> Provider:
        """The provider that will serve requests."""
        return next(p for p in self.providers if p.name == self.active_provider)

    def provider(self, name: str) -> Provider:
        try:
            return next(p for p in self.providers if p.name == name)
        except StopIteration:
            raise KeyError(f"no provider named {name!r}") from None

    @property
    def is_measured(self) -> bool:
        """Whether data produced right now may carry judge-facing numbers (ADR-018)."""
        return self.active.upstream_class is UpstreamClass.MEASURED


class TaintedDataError(RuntimeError):
    """Raised when an artifact would be produced from dev-class data without consent.

    Deliberately a hard error rather than a warning: AGENTS.md §7 makes an unmeasured
    number in a judge-facing artifact a correctness failure, and a warning printed into
    a long eval log is not a control.
    """


def load_gateway_config(path: Path | str | None = None) -> GatewayConfig:
    """Load and validate `config/gateway.yaml` (05 §6.1).

    Raises `FileNotFoundError` if absent and `pydantic.ValidationError` with a precise
    message if invalid — FR-CFG-001's "refuses to load with a precise error" discipline,
    applied to the gateway config for the same reason it applies to policies.
    """
    config_path = Path(path) if path is not None else CONFIG_PATH
    raw: Any = yaml.safe_load(config_path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(
            f"{config_path} did not parse to a mapping (got {type(raw).__name__})"
        )
    return GatewayConfig(**raw)


def require_measured_upstream(
    *,
    allow_dev: bool = False,
    config: GatewayConfig | None = None,
    artifact: str = "this artifact",
) -> GatewayConfig:
    """Gate judge-facing output on upstream provenance (ADR-018).

    Call this before writing any report, fixture, or demo transcript. Returns the loaded
    config so callers can stamp `upstream_class` onto what they emit — provenance should
    travel with the data, not stop at the gate.

    Raises `TaintedDataError` when the active provider is dev-class and `allow_dev` is
    False. With `allow_dev=True` the caller must route every output path through
    `taint_output_path()`.
    """
    cfg = config if config is not None else load_gateway_config()
    if cfg.is_measured or allow_dev:
        return cfg
    raise TaintedDataError(
        f"active provider {cfg.active.name!r} is upstream_class=dev, so {artifact} "
        "would rest on token/cost accounting that is not a measurement (ADR-018, "
        "AGENTS.md §7). Switch `active_provider` in config/gateway.yaml to a "
        "measured-class provider, or re-run with --allow-dev to produce an output "
        f"explicitly marked {TAINT_MARKER}."
    )


def taint_output_path(path: Path | str, *, tainted: bool = True) -> Path:
    """Mark an output filename as resting on dev-class data.

    `reports/eval_report.md` -> `reports/eval_report.DEV-TAINTED.md`. The marker goes in
    the filename rather than only inside the file because artifacts get attached to
    emails and dropped into slide decks stripped of their context.

    Idempotent, so a path can be passed through more than one layer safely.
    """
    p = Path(path)
    if not tainted or f".{TAINT_MARKER}" in p.suffixes or p.stem.endswith(TAINT_MARKER):
        return p
    return p.with_name(f"{p.stem}.{TAINT_MARKER}{p.suffix}")
