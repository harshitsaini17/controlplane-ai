"""Gateway upstream config tests — ADR-018 provenance + 05 §6.1 schema.

Covers: the shipped `config/gateway.yaml` loads and validates, the ADR-018 class ruling
survives transcription, the provider-graph rules, and the dev-class refusal that keeps
tainted numbers out of judge-facing artifacts (AGENTS.md §7).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from controlplane.gateway.config import (
    CONFIG_PATH,
    TAINT_MARKER,
    GatewayConfig,
    TaintedDataError,
    UpstreamClass,
    load_gateway_config,
    require_measured_upstream,
    taint_output_path,
)


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
    """Both ids were verified first-party as *production* models (ADR-018).

    Preview ids can be discontinued without notice; a silently dead id fails at dispatch
    and forces the fallback path mid-demo, which is a BLOCKER dressed as a config typo.
    """
    groq = load_gateway_config().provider("groq")
    assert groq.tiers.small == "llama-3.1-8b-instant"
    assert groq.tiers.frontier == "llama-3.3-70b-versatile"


def test_q10_ollama_provider_is_declared_but_binds_no_model() -> None:
    """Characterization test for the open Q-10 gap — update it when a model lands.

    `ollama-local` is a declared shape, not a working provider: no genuinely local model
    is installed (the one present carries `remote_host`, so it is a cloud model reached
    through a local CLI). Both tiers are null, which is legal for a non-active provider
    and is what stops it being mistaken for a working fallback.
    """
    ollama = load_gateway_config().provider("ollama-local")
    assert ollama.tiers.small is None and ollama.tiers.frontier is None
    assert ollama.tiers.resolve("small") is None


def test_fr_gw_006_usage_sanity_knobs_present_with_documented_default() -> None:
    """FR-GW-006: the canary needs both knobs; 25 is the documented default delta."""
    sanity = load_gateway_config().usage_sanity
    assert sanity.canary_on_startup is True
    assert sanity.max_token_delta == 25


def test_dev_class_provider_carries_no_price() -> None:
    """The dev-class provider is unmetered, so `can_price` must be False.

    This is the structural reason its cost figures are not measurements: there is no
    price to multiply by, so any cost it "reports" would be an invention.
    """
    assert load_gateway_config().provider("kiro-local").can_price is False


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
    """A tier-less active provider can serve no request at all."""
    valid_config_dict["active_provider"] = "ollama-local"
    with pytest.raises(ValidationError, match="binds no tier"):
        GatewayConfig(**valid_config_dict)


def test_non_active_provider_may_bind_no_tier(valid_config_dict: dict[str, Any]) -> None:
    """The converse of the rule above — this is the shipped `ollama-local` case."""
    assert GatewayConfig(**valid_config_dict).provider("ollama-local").tiers.small is None


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
    valid_config_dict["providers"][1]["price_per_1k_in"] = -0.001
    with pytest.raises(ValidationError):
        GatewayConfig(**valid_config_dict)


def test_zero_price_is_a_measurement_not_an_absence(
    valid_config_dict: dict[str, Any],
) -> None:
    """A genuinely free provider is metered at 0.0 — distinct from null.

    `can_price` must stay True: 0.0 means "measured, and it costs nothing", whereas null
    means "no price exists". Collapsing the two would let a free provider be treated as
    unpriceable, or an unpriced one as free.
    """
    valid_config_dict["providers"][1]["price_per_1k_in"] = 0.0
    valid_config_dict["providers"][1]["price_per_1k_out"] = 0.0
    assert GatewayConfig(**valid_config_dict).provider("groq").can_price is True


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
