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

import enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "CONFIG_PATH",
    "TAINT_MARKER",
    "GatewayConfig",
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
        """Concrete model id for `tier`, or None if this provider cannot serve it."""
        return getattr(self, tier, None)


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    upstream_class: UpstreamClass
    base_url: str = Field(min_length=1)
    #: Env var *NAME* only — the value lives in `.env` and is never read into config
    #: (NFR-SEC-002). `None` for providers needing no credential.
    key_env: str | None = None
    price_per_1k_in: float | None = Field(default=None, ge=0.0)
    price_per_1k_out: float | None = Field(default=None, ge=0.0)
    tiers: Tiers = Field(default_factory=Tiers)

    @property
    def can_price(self) -> bool:
        """Whether a cost figure may be computed from this provider at all.

        Not a validation rule, deliberately. 05 §6.1 documents `null` as "unmetered / no
        measured price exists" without restricting it by class, and a local model with
        trustworthy token accounting and no price list is exactly that case — so
        requiring prices of every `measured` provider would reject a legitimate config
        and, worse, advise reclassifying it as `dev` when its counts are fine.

        The guard belongs where the number is produced: a caller computing cost must
        check this and refuse rather than let a null read as $0.00. That path does not
        exist yet — the cost plane is blocked on
        `[D2-price-table-cannot-express-per-tier-cost]`, which has to be ruled before
        per-tier cost is expressible at all.
        """
        return self.price_per_1k_in is not None and self.price_per_1k_out is not None


class UsageSanity(BaseModel):
    """FR-GW-006 knobs for the startup canary."""

    model_config = ConfigDict(extra="forbid")

    canary_on_startup: bool
    #: Tokens. Delta above this between `count_tokens` and the provider's reported
    #: prompt-token count means the provider's accounting is untrustworthy: a
    #: measured-class provider fails boot, a dev-class one warns loudly (FR-GW-006).
    max_token_delta: int = Field(ge=0)


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
        active = next(p for p in self.providers if p.name == self.active_provider)
        if active.tiers.small is None and active.tiers.frontier is None:
            raise ValueError(
                f"active provider {active.name!r} binds no tier to a model id, so no "
                "request can be dispatched. A declared-but-unusable provider may sit in "
                "`providers` with null tiers, but it cannot be the active one."
            )
        return self

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
