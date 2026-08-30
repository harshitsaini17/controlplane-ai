"""Gateway upstream config tests — ADR-018 provenance + 05 §6.1 schema.

Covers: the shipped `config/gateway.yaml` loads and validates, the ADR-018 class ruling
survives transcription, the provider-graph rules, and the dev-class refusal that keeps
tainted numbers out of judge-facing artifacts (AGENTS.md §7).
"""

from __future__ import annotations

import copy
import re
import warnings
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from controlplane.gateway.config import (
    CONFIG_PATH,
    TAINT_MARKER,
    UNMETERED,
    GatewayConfig,
    PricingWarning,
    TaintedDataError,
    Tiers,
    UpstreamClass,
    load_gateway_config,
    require_measured_upstream,
    taint_output_path,
)

#: 05 §6.1's prose fixes the tier vocabulary; parsed rather than restated so drift on
#: either side fails (the same differential rule `test_telemetry.py` applies to §5).
DOC_05 = Path(__file__).resolve().parents[1] / "docs" / "05-api-and-data-contracts.md"
DOC_01 = Path(__file__).resolve().parents[1] / "docs" / "01-requirements-and-scenarios.md"
_TIER_SENTENCE = re.compile(r"\*\*Tier names are ((?:`[a-z_]+`(?:,? and )?)+)\*\*")

#: Concrete model ids the shipped Groq tiers bind (ADR-022 keys prices by these).
GROQ_SMALL = "openai/gpt-oss-20b"
GROQ_FRONTIER = "openai/gpt-oss-120b"


def load_raw() -> dict[str, Any]:
    """Parse the shipped gateway config into a plain dict (no validation)."""
    return yaml.safe_load(CONFIG_PATH.read_text())


@pytest.fixture
def valid_config_dict() -> dict[str, Any]:
    """The shipped config, mutated per test to trip one rule at a time."""
    return copy.deepcopy(load_raw())


# --------------------------------------------------------------------------
# The shipped artifact
# --------------------------------------------------------------------------


def test_shipped_gateway_config_loads_and_validates() -> None:
    assert load_gateway_config().price_table_version >= 1


def test_adr_018_class_ruling_survives_transcription() -> None:
    """The ADR-018 ruling named the class of each provider — pin all three.

    Flipping one of these silently changes whether data from that provider may carry a
    judge-facing number, which is the whole point of the field.
    """
    cfg = load_gateway_config()
    assert cfg.provider("kiro-local").upstream_class is UpstreamClass.DEV
    assert cfg.provider("groq").upstream_class is UpstreamClass.MEASURED
    assert cfg.provider("ollama-local").upstream_class is UpstreamClass.MEASURED


def test_groq_tiers_bind_the_verified_production_model_ids() -> None:
    """Both ids were verified first-party as *production* models (ADR-018, ADR-029).

    Preview ids can be discontinued without notice; a silently dead id fails at dispatch
    and forces the fallback path mid-demo, which is a BLOCKER dressed as a config typo.

    **ADR-018's own trade-off note predicted this and it came true.** The original pair
    (`llama-3.1-8b-instant`, `llama-3.3-70b-versatile`) was shut down 2026-08-16 for free
    and developer-tier keys — probed 2026-08-27, both return HTTP 404 `model_not_found` on
    this repo's key, so it is not on the exempt committed-spend contract. ADR-029 rebound
    the tiers to the gpt-oss pair, which Groq itself names as the replacements.

    `qwen/qwen3.6-27b` serves and was the other sanctioned frontier replacement, but it is
    a **preview** id — exactly what this test exists to keep out of the config.
    """
    groq = load_gateway_config().provider("groq")
    assert groq.tiers.small == GROQ_SMALL == "openai/gpt-oss-20b"
    assert groq.tiers.frontier == GROQ_FRONTIER == "openai/gpt-oss-120b"


def test_sl4_ollama_binds_the_owner_verified_local_model() -> None:
    """SL-4/Q-10 closed 2026-08-28: a genuinely local model now serves the small tier.

    The predecessor of this test characterized the *gap* and said in its own docstring to
    update it when a model landed. `llama3.2:3b` passes the no-`remote_host` assertion, so
    it is local in the sense ADR-018 requires and the `unmetered` claim holds — its tokens
    are billed to no one.

    `frontier` stays null deliberately. Exactly one local model is evidenced, and binding
    both tiers to one id would make the cascade a no-op while looking configured — the
    ADR-009 substitution reached from the other direction.

    This asserts the *config*, not the daemon. The binding was verified on the owner's
    machine (Ollama v0.33.0); the development host serves only a `remote_host`-carrying
    cloud model, so a live dispatch there fails and no test may depend on one.
    """
    ollama = load_gateway_config().provider("ollama-local")
    assert ollama.tiers.small == "llama3.2:3b"
    assert ollama.tiers.frontier is None
    assert ollama.tiers.resolve("frontier") is None
    # `unmetered` is an affirmative measurement claim (ADR-022), not a missing price.
    assert ollama.est_cost_usd("llama3.2:3b", 1000, 1000) == 0.0


@pytest.mark.parametrize("attribute", ["model_config", "dict", "json", "copy"])
def test_resolve_refuses_a_non_tier_attribute_name(attribute: str) -> None:
    """★ `resolve` was a bare `getattr`, so any attribute name resolved to something.

    `resolve("model_config")` returned a dict and `resolve("dict")` a bound method, and
    either would have travelled onward as the `model` field of an upstream dispatch — a
    garbage value wearing the shape of a resolution. These four names are all real
    attributes of the pydantic model, so they are exactly the ones a bare `getattr`
    answered instead of refusing.
    """
    tiers = Tiers(small="m-small", frontier="m-frontier")
    with pytest.raises(KeyError, match="unknown tier"):
        tiers.resolve(attribute)


def test_an_unbound_but_real_tier_is_none_not_an_error() -> None:
    """The two negative answers stay distinct.

    `None` is a real provider reporting it cannot serve a real tier — a routing fact the
    dispatcher turns into ERR-UP-001. An unknown *name* is a caller bug. Collapsing them
    would either make a typo look like a capacity limit or make a legitimately unbound
    tier crash the request.
    """
    assert Tiers().resolve("small") is None
    assert Tiers(frontier="m").resolve("small") is None


def test_the_tier_vocabulary_matches_05_6_1() -> None:
    """Differential against the doc: a tier added on one side only must fail.

    Parsed out of 05 §6.1's prose rather than restated here, because restating the
    implementation's own literal would prove nothing (06 §3.1 rule 3).
    """
    match = _TIER_SENTENCE.search(DOC_05.read_text())
    assert match is not None, "05 §6.1's 'Tier names are …' sentence has moved"
    documented = set(re.findall(r"`([a-z_]+)`", match.group(1)))
    assert documented == set(Tiers.model_fields), (
        f"05 §6.1 documents {sorted(documented)}, Tiers declares "
        f"{sorted(Tiers.model_fields)}"
    )


def test_fr_gw_006_usage_sanity_knobs_match_the_documented_defaults() -> None:
    """FR-GW-006 as ruled by ADR-028: the shipped config carries the documented defaults.

    Differential — the two figures are read out of 01 FR-GW-006's own "(defaults 2.0 / 50)"
    rather than restated here, so changing the config without changing the requirement (or
    the reverse) fails. `max_token_delta` is deliberately absent: ADR-028 withdrew the
    count_tokens comparison it parametrised, and `UsageSanity` forbids extra keys.
    """
    sanity = load_gateway_config().usage_sanity
    assert sanity.canary_on_startup is True
    assert sanity.method == "local_estimate"

    fr = next(line for line in DOC_01.read_text().splitlines() if "FR-GW-006" in line)
    documented = re.search(r"defaults ([\d.]+) / (\d+)", fr)
    assert documented is not None, "01 FR-GW-006's '(defaults X / Y)' phrasing has moved"
    assert sanity.max_ratio == float(documented.group(1))
    assert sanity.min_delta_floor == int(documented.group(2))


def test_dev_class_provider_price_is_unknown_not_zero() -> None:
    """`kiro-local` declares `pricing: null` — UNKNOWN, which is not `unmetered`.

    It bills the operator nothing, but it proxies a hosted model whose tokens are charged
    to someone, so `unmetered` would be a false affirmative claim and 0.0 would be a
    fabricated measurement. ADR-022 keeps the two apart and this pins which one we chose.
    """
    kiro = load_gateway_config().provider("kiro-local")
    assert kiro.pricing is None
    assert kiro.can_price("claude-haiku-4.5") is False
    assert kiro.est_cost_usd("claude-haiku-4.5", 1000, 1000) is None


def test_adr_022_prices_are_keyed_by_concrete_model_id() -> None:
    """The whole point of ADR-022: each tier's model id carries its own price."""
    groq = load_gateway_config().provider("groq")
    assert groq.price_for(GROQ_SMALL) is not None
    assert groq.price_for(GROQ_FRONTIER) is not None


def test_adr_022_tier_prices_preserve_the_cascade_premise() -> None:
    """The cascade premise, as restated RATIO-PARAMETRIC by ADR-029 amending ADR-009.

    The old bound was `> small * 5`, written when the tiers were the llama pair at ~12x.
    The shipped gpt-oss pair is exactly **2.0x**, so that bound now fails. It is amended
    here **in the same commit as ADR-029** — a front-door change to a ruled contract, not
    a harness loosened to fit a number (AGENTS.md §5.4). The "~12x" was llama-era vendor
    pricing, never architecture: the mechanism is route-cheap-escalate-on-low-confidence,
    and measured savings scale with (ratio x routing fraction), reported with the
    deployment's own ratio.

    Two things must still hold, and a flattening fails both:
      1. the frontier tier is **strictly costlier per blended token** — otherwise
         "escalate" carries no cost meaning and the cost plane measures nothing;
      2. the ratio is **>= 1.5x**, which a copy-paste collapsing both tiers to one figure
         cannot satisfy.

    `est_cost_usd(id, 1000, 1000)` is the blended measure: equal input and output tokens.
    For this pair the ratio is **blend-independent** — 120b is exactly 2.0x 20b on input
    *and* on output — so no input/output mix can move it and none can be cherry-picked to
    flatter it. `test_adr_029_the_tier_ratio_is_blend_independent` pins that separately.
    """
    groq = load_gateway_config().provider("groq")
    small = groq.est_cost_usd(GROQ_SMALL, 1000, 1000)
    frontier = groq.est_cost_usd(GROQ_FRONTIER, 1000, 1000)
    assert small is not None and frontier is not None
    assert frontier > small, "escalation must cost more, or the cost plane measures nothing"
    assert frontier / small >= 1.5, "a flattened pair erases the effect being measured"


def test_adr_029_the_tier_ratio_is_blend_independent() -> None:
    """The 2.0x gap holds on input and output separately, so no blend can be cherry-picked.

    This is what makes the ratio publishable next to a savings figure: a ratio that moved
    with the input/output mix would invite picking the mix that flatters it. Asserted at
    the price level rather than through `est_cost_usd`, because that is where the property
    actually lives.
    """
    groq = load_gateway_config().provider("groq")
    small, frontier = groq.price_for(GROQ_SMALL), groq.price_for(GROQ_FRONTIER)
    assert small is not None and frontier is not None
    in_ratio = frontier.per_1k_in / small.per_1k_in
    out_ratio = frontier.per_1k_out / small.per_1k_out
    assert in_ratio == out_ratio, (
        f"input ratio {in_ratio} != output ratio {out_ratio}; the ratio reported beside a "
        "savings figure would then depend on the blend chosen to compute it"
    )
    assert in_ratio == 2.0


def test_price_provenance_fields_are_populated() -> None:
    """ADR-022 requires attribution: an unattributed price cannot be re-checked.

    Deliberately asserts only presence, not the specific URL — the figures currently rest
    on secondary aggregators because no first-party Groq price table is reachable, and the
    STUB in `config/gateway.yaml` records that. Pinning the URL here would just have to be
    edited when the honest source improves.
    """
    pricing = load_gateway_config().provider("groq").pricing
    assert pricing is not None and pricing != UNMETERED
    assert pricing.source_url.startswith("http")
    assert pricing.retrieved.year >= 2026


def test_unmetered_is_an_affirmative_zero_for_any_model() -> None:
    """`ollama-local` claims local compute levies no charge, so 0.0 IS the measurement.

    Contrast with the dev-class test above: same "no money changes hands" intuition,
    opposite recorded fact, because only one of them can be asserted about the world.
    """
    ollama = load_gateway_config().provider("ollama-local")
    assert ollama.pricing == UNMETERED
    assert ollama.est_cost_usd("any-local-model", 1000, 1000) == 0.0
    assert ollama.can_price("any-local-model") is True


def test_missing_model_entry_yields_unknown_not_a_guess(
    valid_config_dict: dict[str, Any],
) -> None:
    """A model absent from `pricing.models` costs `None` — never an averaged fallback.

    Removing the small tier's price would make the cascade cheap-side unpriceable; the
    tempting repair is to fall back to the other tier's rate, which would report the
    cascade as saving nothing. ADR-022 forbids that: unknown propagates as null.
    """
    del valid_config_dict["providers"][1]["pricing"]["models"][GROQ_SMALL]
    valid_config_dict["providers"][1]["tiers"]["small"] = None  # keep it off the route
    groq = GatewayConfig(**valid_config_dict).provider("groq")
    assert groq.price_for(GROQ_SMALL) is None
    assert groq.est_cost_usd(GROQ_SMALL, 1_000_000, 1_000_000) is None


# --------------------------------------------------------------------------
# ADR-022 boot ladder
# --------------------------------------------------------------------------


def test_measured_provider_with_unpriced_routed_model_fails_boot(
    valid_config_dict: dict[str, Any],
) -> None:
    """The hard-failure row of 05 §6.1: unpriced *and* on a routing path.

    Such a model will answer real requests and mint audit records that can never be
    costed. Discoverable at boot, so it fails at boot rather than surfacing as a column of
    nulls after an eval run.
    """
    del valid_config_dict["providers"][1]["pricing"]["models"][GROQ_FRONTIER]
    with pytest.raises(ValidationError, match="never be costed"):
        GatewayConfig(**valid_config_dict)


def test_boot_failure_names_the_tier_and_the_model(
    valid_config_dict: dict[str, Any],
) -> None:
    """A config error nobody can locate gets worked around (FR-CFG-001 spirit)."""
    del valid_config_dict["providers"][1]["pricing"]["models"][GROQ_FRONTIER]
    with pytest.raises(ValidationError) as exc:
        GatewayConfig(**valid_config_dict)
    message = str(exc.value)
    assert "groq" in message
    assert "frontier" in message
    assert GROQ_FRONTIER in message


def test_measured_provider_with_null_pricing_warns_by_name(
    valid_config_dict: dict[str, Any],
) -> None:
    """The warning row of 05 §6.1: legal, but never silent.

    The shape under test is measured-class + unpriced + **no tier on a routing path**: that
    combination warns, while binding a tier to an unpriceable model is the *fatal* row. The
    two must stay distinguishable, so this test constructs the shape rather than borrowing
    it — since SL-4 closed, `ollama-local` binds `small`, and merely nulling its pricing
    now trips the fatal rule instead of this one (which is itself the correct behaviour).
    """
    valid_config_dict["providers"][2]["pricing"] = None
    valid_config_dict["providers"][2]["tiers"] = {"small": None, "frontier": None}
    with pytest.warns(PricingWarning, match="ollama-local"):
        GatewayConfig(**valid_config_dict)


def test_dev_class_provider_may_boot_unpriced_on_a_routing_path() -> None:
    """The scope decision behind `_check_price_coverage`, pinned as a test.

    `kiro-local` is dev-class with `pricing: null` and BOTH tiers bound. Read
    class-agnostically, the fatal rule above would brick it — yet ADR-018 exists so a
    dev-class provider can be used *while* unpriceable, since its numbers are barred from
    judge-facing artifacts anyway. So the ladder is measured-only, and the documented
    development path keeps working.

    Addressed by NAME rather than through `cfg.active`, which is what it read until
    `active_provider` was switched to `groq` (2026-08-30, for a working upstream). The
    subject here is the dev-class **allowance**, and that holds whether or not the
    dev-class provider is the one currently serving traffic — so reading it off the active
    slot made this test fail on a change it has no opinion about, while also quietly
    scoping it to one deployment choice. Naming the provider pins the rule itself.
    """
    cfg = load_gateway_config()
    dev = cfg.provider("kiro-local")
    assert dev.upstream_class is UpstreamClass.DEV
    assert dev.pricing is None
    assert set(dev.priced_tier_models) == {"small", "frontier"}


def test_shipped_config_emits_no_pricing_warning() -> None:
    """Every measured-class provider in the shipped config states its price position."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", PricingWarning)
        load_gateway_config()


# --------------------------------------------------------------------------
# Provider-graph rules
# --------------------------------------------------------------------------


def test_active_provider_must_be_declared(valid_config_dict: dict[str, Any]) -> None:
    valid_config_dict["active_provider"] = "gpt-fictional"
    with pytest.raises(ValidationError, match="not a declared provider"):
        GatewayConfig(**valid_config_dict)


def test_duplicate_provider_names_rejected(valid_config_dict: dict[str, Any]) -> None:
    """Two providers sharing a name make `active_provider` ambiguous."""
    clone = copy.deepcopy(valid_config_dict["providers"][1])
    clone["name"] = valid_config_dict["providers"][0]["name"]
    valid_config_dict["providers"].append(clone)
    with pytest.raises(ValidationError, match="duplicate provider name"):
        GatewayConfig(**valid_config_dict)


def test_active_provider_must_bind_at_least_one_tier(
    valid_config_dict: dict[str, Any],
) -> None:
    """A tier-less active provider can serve no request at all.

    The tier-less provider is constructed here: every provider in the shipped config now
    binds at least one tier, so this rule has no ready-made subject left. Nulling the tiers
    first is what keeps the assertion about the rule rather than about the config.
    """
    valid_config_dict["providers"][2]["tiers"] = {"small": None, "frontier": None}
    valid_config_dict["active_provider"] = "ollama-local"
    with pytest.raises(ValidationError, match="binds no tier"):
        GatewayConfig(**valid_config_dict)


def test_non_active_provider_may_bind_no_tier(valid_config_dict: dict[str, Any]) -> None:
    """The converse of the rule above: only the *active* provider must bind a tier.

    No longer the shipped `ollama-local` case — SL-4 closed and it binds `small` — so the
    permission is asserted on a constructed provider. It is still worth pinning: it is what
    lets a declared-but-unused provider sit in the config without blocking boot.
    """
    valid_config_dict["providers"][2]["tiers"] = {"small": None, "frontier": None}
    config = GatewayConfig(**valid_config_dict)
    assert config.provider("ollama-local").tiers.small is None
    assert config.active_provider != "ollama-local"


def test_unknown_key_rejected(valid_config_dict: dict[str, Any]) -> None:
    """`extra="forbid"`: a typo'd key must fail loudly, not be ignored (FR-CFG-001)."""
    valid_config_dict["active_povider"] = "groq"
    with pytest.raises(ValidationError):
        GatewayConfig(**valid_config_dict)


def test_unknown_provider_key_rejected(valid_config_dict: dict[str, Any]) -> None:
    valid_config_dict["providers"][0]["price_per_1k"] = 0.5
    with pytest.raises(ValidationError):
        GatewayConfig(**valid_config_dict)


def test_unknown_upstream_class_rejected(valid_config_dict: dict[str, Any]) -> None:
    """Only the two ADR-018 classes exist; a third would have undefined provenance."""
    valid_config_dict["providers"][0]["upstream_class"] = "staging"
    with pytest.raises(ValidationError):
        GatewayConfig(**valid_config_dict)


def test_negative_price_rejected(valid_config_dict: dict[str, Any]) -> None:
    """Reaches into `pricing.models` on purpose: post-ADR-022 a top-level
    `price_per_1k_in` is merely an unknown key, so setting it there would pass this test
    via `extra="forbid"` without the price bound ever being exercised."""
    valid_config_dict["providers"][1]["pricing"]["models"][GROQ_SMALL][
        "per_1k_in"
    ] = -0.001
    with pytest.raises(ValidationError):
        GatewayConfig(**valid_config_dict)


def test_pre_adr_022_provider_price_keys_are_now_rejected(
    valid_config_dict: dict[str, Any],
) -> None:
    """The pre-ADR-022 flat keys must not be silently ignored if a config lags behind.

    `extra="forbid"` makes a stale `price_per_1k_in:` a loud failure rather than a field
    that quietly does nothing while the cost plane reports nulls.
    """
    valid_config_dict["providers"][1]["price_per_1k_in"] = 0.00005
    with pytest.raises(ValidationError):
        GatewayConfig(**valid_config_dict)


def test_price_table_requires_its_provenance(valid_config_dict: dict[str, Any]) -> None:
    """`source_url` and `retrieved` are required — a price you cannot re-check is a
    liability, and a stale price is a wrong price (ADR-022)."""
    del valid_config_dict["providers"][1]["pricing"]["retrieved"]
    with pytest.raises(ValidationError):
        GatewayConfig(**valid_config_dict)


def test_empty_price_table_rejected(valid_config_dict: dict[str, Any]) -> None:
    """A `pricing` block with no models is a null wearing a table's clothes — say null."""
    valid_config_dict["providers"][1]["pricing"]["models"] = {}
    with pytest.raises(ValidationError):
        GatewayConfig(**valid_config_dict)


def test_arbitrary_pricing_scalar_rejected(valid_config_dict: dict[str, Any]) -> None:
    """`unmetered` is the ONLY legal scalar; a typo must not read as an affirmative claim."""
    valid_config_dict["providers"][2]["pricing"] = "unmeterd"
    with pytest.raises(ValidationError):
        GatewayConfig(**valid_config_dict)


def test_zero_price_is_a_measurement_not_an_absence(
    valid_config_dict: dict[str, Any],
) -> None:
    """An explicit 0.0 in a price table is a measurement — distinct from null.

    `can_price` must stay True: 0.0 means "priced, and it costs nothing", whereas null
    means "no price exists". Collapsing the two would let a free model be treated as
    unpriceable, or an unpriced one as free — and 06 §6 prints the difference.
    """
    models = valid_config_dict["providers"][1]["pricing"]["models"]
    models[GROQ_SMALL] = {"per_1k_in": 0.0, "per_1k_out": 0.0}
    groq = GatewayConfig(**valid_config_dict).provider("groq")
    assert groq.can_price(GROQ_SMALL) is True
    assert groq.est_cost_usd(GROQ_SMALL, 5000, 5000) == 0.0


def test_unknown_provider_lookup_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        load_gateway_config().provider("nope")


def test_missing_config_file_raises_filenotfound(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_gateway_config(tmp_path / "absent.yaml")


def test_non_mapping_config_rejected(tmp_path: Path) -> None:
    """A YAML list or scalar must fail with a clear message, not an attribute error."""
    path = tmp_path / "gateway.yaml"
    path.write_text("- just\n- a list\n")
    with pytest.raises(ValueError, match="did not parse to a mapping"):
        load_gateway_config(path)


# --------------------------------------------------------------------------
# ADR-018 dev-class refusal — the control that keeps tainted numbers out
# --------------------------------------------------------------------------


def _config_with_active(raw: dict[str, Any], name: str) -> GatewayConfig:
    mutated = copy.deepcopy(raw)
    mutated["active_provider"] = name
    return GatewayConfig(**mutated)


def test_dev_class_upstream_refuses_to_produce_an_artifact(
    valid_config_dict: dict[str, Any],
) -> None:
    """The core ADR-018 control: dev-class data cannot reach a report by accident."""
    cfg = _config_with_active(valid_config_dict, "kiro-local")
    assert cfg.is_measured is False
    with pytest.raises(TaintedDataError, match="upstream_class=dev"):
        require_measured_upstream(config=cfg, artifact="the eval report")


def test_measured_class_upstream_passes_the_gate(
    valid_config_dict: dict[str, Any],
) -> None:
    cfg = _config_with_active(valid_config_dict, "groq")
    assert cfg.is_measured is True
    assert require_measured_upstream(config=cfg) is cfg


def test_allow_dev_overrides_the_refusal(valid_config_dict: dict[str, Any]) -> None:
    """`--allow-dev` is an explicit, consenting override — not a silent bypass."""
    cfg = _config_with_active(valid_config_dict, "kiro-local")
    assert require_measured_upstream(config=cfg, allow_dev=True) is cfg


def test_refusal_message_names_the_provider_and_both_ways_out(
    valid_config_dict: dict[str, Any],
) -> None:
    """A refusal nobody can act on gets worked around; name the fix (FR-CFG-001 spirit)."""
    cfg = _config_with_active(valid_config_dict, "kiro-local")
    with pytest.raises(TaintedDataError) as exc:
        require_measured_upstream(config=cfg, artifact="the latency report")
    message = str(exc.value)
    assert "kiro-local" in message           # which provider
    assert "the latency report" in message   # which artifact
    assert "active_provider" in message      # fix 1: switch provider
    assert "--allow-dev" in message          # fix 2: consent explicitly
    assert TAINT_MARKER in message           # and what that costs you


def test_gate_returns_config_so_provenance_can_be_stamped(
    valid_config_dict: dict[str, Any],
) -> None:
    """ADR-018: provenance travels with the data, so the gate hands back the class."""
    cfg = _config_with_active(valid_config_dict, "groq")
    returned = require_measured_upstream(config=cfg)
    assert returned.active.upstream_class.value == "measured"


# --------------------------------------------------------------------------
# Filename tainting
# --------------------------------------------------------------------------


def test_taint_output_path_marks_the_filename() -> None:
    """The marker goes in the *name*: artifacts travel stripped of their context."""
    assert taint_output_path("reports/eval_report.md") == Path(
        f"reports/eval_report.{TAINT_MARKER}.md"
    )


def test_taint_output_path_preserves_directory_and_extension() -> None:
    tainted = taint_output_path("reports/nested/latency_report.md")
    assert tainted.parent == Path("reports/nested")
    assert tainted.suffix == ".md"


def test_taint_output_path_is_idempotent() -> None:
    """Two layers both tainting a path must not double-stamp it."""
    once = taint_output_path("reports/eval_report.md")
    assert taint_output_path(once) == once


def test_taint_output_path_handles_extensionless_name() -> None:
    assert TAINT_MARKER in taint_output_path("reports/summary").name


def test_taint_output_path_noop_when_not_tainted() -> None:
    """Measured runs keep the clean filename — the marker must mean something."""
    assert taint_output_path("reports/eval_report.md", tainted=False) == Path(
        "reports/eval_report.md"
    )


# ---------------------------------------------------------------------------
# The `active_provider` override (2026-08-30) — see [[M-62]].
#
# One YAML key had three consumers: which upstream serves, the ADR-018 provenance class
# `require_measured_upstream()` gates reports on, and the class OFFLINE paths inherit when
# they build a `Gateway` with no config. A fixture upstream reports no prompt tokens, which
# is boot-fatal for a measured provider (FR-GW-006) — so promoting the shipped default to
# measured made tests and `--replay` refuse to boot while claiming a provenance a fixture
# cannot have. The serving path names its provider instead.
# ---------------------------------------------------------------------------


def test_the_shipped_default_is_dev_class_so_offline_paths_inherit_dev() -> None:
    """★ The invariant the split exists to protect.

    Not a style preference: `make_client`, `demo.run_script --replay` and
    `eval.fault_injection` all construct a `Gateway` with no config and inherit this key. A
    fixture reports no prompt-token usage, and for a measured-class provider the FR-GW-006
    canary makes that boot-fatal — so a measured default breaks every offline path at once.
    """
    assert load_gateway_config().active.upstream_class.value == "dev"


def test_the_override_yields_a_measured_provider_for_the_serving_path() -> None:
    """The other half: live traffic runs measured, so its cost figures are citable."""
    assert load_gateway_config(active="groq").active.upstream_class.value == "measured"


def test_the_override_is_validated_not_merely_assigned() -> None:
    """★ Why the override goes through the constructor rather than attribute assignment.

    `model_copy(deep=True)` + `cfg.active_provider = name` is the shorter route and skips
    the provider-graph and pricing validators — precisely the checks that must run on a
    provider about to serve real traffic. An unknown name must be refused, not stored.
    """
    with pytest.raises(ValidationError, match="not a declared provider"):
        load_gateway_config(active="no-such-provider")


def test_the_override_does_not_leak_into_the_next_load() -> None:
    """The override is per-call. A sticky one would silently re-class judge-facing output."""
    load_gateway_config(active="groq")
    assert load_gateway_config().active.name == "kiro-local"


def test_the_live_factory_serves_measured_while_create_app_stays_dev() -> None:
    """★ The two factories differ in provenance class, which is the whole point.

    `create_app` is the injectable/offline factory; `create_live_app` is what serves. Built
    without `with TestClient(...)`, so no lifespan and no canary fires here — this asserts
    the wiring, not the upstream.
    """
    from controlplane.gateway.app import LIVE_PROVIDER, Gateway, create_live_app

    create_live_app()  # must construct without a key present
    assert load_gateway_config(active=LIVE_PROVIDER).is_measured
    assert Gateway().config.active.upstream_class.value == "dev"
