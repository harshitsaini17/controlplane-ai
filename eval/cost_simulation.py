"""Cascade cost simulation -> `reports/cost_report.md` (06 §6, ADR-029 ratio-parametric).

Replays the **frozen** corpus (06 §1) through the two-tier cost model and reports RELATIVE
deltas. Three things this harness refuses to do, each because the alternative would be a
fabricated number (AGENTS.md §7):

1. **It does not claim a measured routing fraction.** ADR-009's cascade is *route cheap,
   escalate on low confidence*, and the thing that would pick the escalations —
   a confidence signal at `tau_route` — **does not exist in this build**: `fast_consistency`
   is CUT (SL-6) and no router reads `tau_route` (it appears in `policy/schema.py` and
   `audit/forensics.py` and nowhere else; `audit_records.cascade_escalated` is a column
   nothing writes). So the saving is published as a **curve over the routing fraction `f`**,
   with the break-even point named, and `f` itself is reported NOT COMPUTED. Picking a
   flattering `f` and calling it measured is the exact substitution §5.4 forbids.

2. **It does not price output tokens.** The frozen corpus carries request text and labels,
   not completions, so no measured `tokens_out` exists for it. The headline is therefore a
   **percentage**, which on this pair costs nothing in rigour — see `blend_independent`.

3. **It does not replay through the live gateway.** Cost is decided pre-dispatch, and the
   quantity here is arithmetic over token counts and a price table; running 280 x 3 requests
   would add detector latency and dispatch noise to a figure neither depends on.

06 §6's third artifact — the cascade quality proxy, "fraction of small-tier answers whose
fast-confidence cleared tau_route" — is NOT COMPUTED for the reason in (1): its input is the
cut detector. Reported as NOT COMPUTED rather than omitted, so the gap is visible in the
artifact instead of only in this docstring.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from controlplane.gateway.config import UNMETERED, load_gateway_config
from controlplane.gateway.pipeline import CHARS_PER_TOKEN, estimate_tokens
from eval.host_load import (
    code_commit_cell,
    git_stamp,
    load_stamp,
    quiet_verdict,
    reproducibility_verdict,
)
from eval.validate_dataset import (
    DATASET_DIR,
    FROZEN_COMMIT,
    FROZEN_SHA256,
    check_freeze,
    dataset_digest,
)

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
DEFAULT_OUT = REPORTS_DIR / "cost_report.md"

#: The two tiers, by their `config/gateway.yaml` names (ADR-029's bound pair).
SMALL_TIER, FRONTIER_TIER = "small", "frontier"

#: Routing fractions the curve is tabulated at. `f` is the share of requests the cascade
#: escalates to the frontier tier *after* paying for the small tier — so `f=0.0` is the
#: best case (nothing escalates) and `f=1.0` is strictly worse than not cascading at all.
CURVE = (0.0, 0.10, 0.25, 0.50, 0.75, 1.00)

#: Published cross-vendor gaps, retrieved 2026-08-27 (ADR-029 / 06 §6 item 2). CONTEXT,
#: explicitly not our measurement — carried as data so the report cannot paraphrase it into
#: a claim of our own.
CONTEXT_GAPS = (
    ("OpenAI", "gpt-5.6-sol vs gpt-5-nano", "80x input / 50x output"),
    ("Anthropic", "Claude Opus 5 vs Haiku 4.5", "5.0x on both"),
    ("Anthropic", "Claude Opus 5 vs Sonnet 5", "2.5x — closest to ours"),
)

NOT_COMPUTED = "NOT COMPUTED"


@dataclass(frozen=True)
class TierPrice:
    """One tier's bound model and its per-1K prices."""

    tier: str
    model_id: str
    per_1k_in: float
    per_1k_out: float


@dataclass(frozen=True)
class Corpus:
    """Estimated input-token totals over the frozen corpus."""

    cases: int
    est_input_tokens: int

    @property
    def mean_tokens(self) -> float:
        return self.est_input_tokens / self.cases if self.cases else 0.0


def load_prices(config_path: Path | None = None) -> tuple[TierPrice, TierPrice] | None:
    """The two bound tiers with their prices, or `None` when either cannot be priced.

    `None` is a reportable state, not an error: ADR-022 makes an unpriced model a legitimate
    configuration, and a simulation that invented a price for one would be worse than a
    simulation that declines to run.
    """
    config = load_gateway_config(config_path) if config_path else load_gateway_config()
    for provider in config.providers:
        bound = provider.priced_tier_models
        if SMALL_TIER not in bound or FRONTIER_TIER not in bound:
            continue
        if provider.pricing == UNMETERED or provider.pricing is None:
            # Unmetered is a real measurement (est_cost_usd 0.0) but it makes every ratio
            # undefined — 0/0 — so it cannot carry a *relative* saving.
            continue
        prices: dict[str, TierPrice] = {}
        for tier, model_id in bound.items():
            price = provider.price_for(model_id)
            if price is None:
                break
            prices[tier] = TierPrice(tier, model_id, price.per_1k_in, price.per_1k_out)
        if len(prices) == 2:
            return prices[SMALL_TIER], prices[FRONTIER_TIER]
    return None


def load_corpus_tokens(dataset_dir: Path = DATASET_DIR) -> Corpus:
    """Estimated input tokens over every frozen case.

    Uses `pipeline.estimate_tokens` — the same estimator the live `cost_budget` detector's
    view is built from — so the simulation and the enforcement path cannot disagree about
    what a token is. It is a **character-derived estimate** (`CHARS_PER_TOKEN`), and every
    figure derived from it is labelled as such in the report.
    """
    cases = 0
    tokens = 0
    for path in sorted(dataset_dir.glob("*.jsonl"), key=lambda p: p.name):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            text = row.get("text")
            if not isinstance(text, str):
                continue
            cases += 1
            tokens += estimate_tokens([{"role": "user", "content": text}])
    return Corpus(cases=cases, est_input_tokens=tokens)


def blend_independent(small: TierPrice, frontier: TierPrice) -> bool:
    """Whether the tier ratio is identical on input and output.

    **This is what lets the report publish a percentage without measured output tokens.**
    When input and output ratios agree, the saving is a function of the ratio alone and no
    input/output mix can move it — ADR-029's blend-independence, restated as a check rather
    than inherited as an assumption. If a future price edit breaks it, the report says so and
    the percentage becomes mix-dependent instead of silently staying published.
    """
    if small.per_1k_in <= 0 or small.per_1k_out <= 0:
        return False
    ratio_in = frontier.per_1k_in / small.per_1k_in
    ratio_out = frontier.per_1k_out / small.per_1k_out
    return abs(ratio_in - ratio_out) < 1e-9


def ratio_of(small: TierPrice, frontier: TierPrice) -> float | None:
    """The input-side tier ratio, or `None` when the small tier is free (undefined)."""
    if small.per_1k_in <= 0:
        return None
    return frontier.per_1k_in / small.per_1k_in


def savings_fraction(ratio: float, routed_fraction: float) -> float:
    """Relative cost saving of the cascade against an all-frontier baseline.

    Derivation, written out because the report cites it as a derivation:

        baseline(N)  = N * C_frontier
        cascade(N)   = N * C_small + f * N * C_frontier

    An escalated request pays **both** tiers — the small-tier attempt happened before the
    confidence check that rejected it — which is why the second term adds rather than
    replaces. With `r = C_frontier / C_small`, `C_small = C_frontier / r`, so:

        saving = 1 - (1/r + f)

    Break-even is therefore `f = 1 - 1/r`, independent of traffic volume and of token
    counts. Both are consequences of the model, not assumptions bolted onto it.
    """
    return 1.0 - (1.0 / ratio) - routed_fraction


def break_even(ratio: float) -> float:
    """The routing fraction at which the cascade stops saving: `1 - 1/r`."""
    return 1.0 - (1.0 / ratio)


def token_split(corpus: Corpus, routed_fraction: float) -> tuple[int, int]:
    """`(small_tier_tokens, frontier_tier_tokens)` under the cascade at `f`.

    Every request is attempted small, so the small-tier column is the whole corpus; the
    frontier column is the escalated share re-sent in full.
    """
    small = corpus.est_input_tokens
    frontier = round(corpus.est_input_tokens * routed_fraction)
    return small, frontier


def input_only_usd(tokens: int, price: TierPrice) -> float:
    """Input-token cost for `tokens` at `price`. **Input only** — see the module docstring."""
    return (tokens / 1000.0) * price.per_1k_in


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def render(corpus: Corpus, prices: tuple[TierPrice, TierPrice] | None,
           freeze_errors: Sequence[str], *, invocation: str) -> tuple[str, int]:
    """The report text and the process exit code."""
    code = git_stamp()
    load_start = load_stamp()
    lines: list[str] = [
        "# Cascade cost simulation",
        "",
        "**Simulation on the frozen synthetic corpus — not a production claim.** (06 §6.)",
        "",
        f"Generated by `{invocation}`. Every figure below is either derived from the price "
        "table in `config/gateway.yaml` and the frozen corpus, or marked "
        f"**{NOT_COMPUTED}**. Nothing here is a placeholder.",
        "",
        "## Provenance",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Dataset digest | `{dataset_digest()[:16]}…` |",
        f"| Frozen at | `{FROZEN_COMMIT[:12]}` — expected `{FROZEN_SHA256[:16]}…` |",
        f"| Freeze gate | {'PASS' if not freeze_errors else 'FAIL'} |",
        f"| Code commit | {code_commit_cell(code)} |",
        f"| Reproducibility | {reproducibility_verdict(code)} |",
        f"| Host load (start) | {load_start.get('load1')} / {load_start.get('load5')} / "
        f"{load_start.get('load15')} · {load_start.get('cpus')} CPUs — "
        f"**{quiet_verdict(load_start)}** |",
        "",
    ]

    if freeze_errors:
        lines += ["## Freeze gate FAILED", "",
                  "No figure is computed against an unfrozen dataset (06 §1).", ""]
        lines += [f"- {err}" for err in freeze_errors]
        return "\n".join(lines) + "\n", 1

    lines += [
        "## Corpus",
        "",
        "| Quantity | Value |",
        "|---|---:|",
        f"| Frozen cases replayed | {corpus.cases} |",
        f"| Estimated input tokens | {corpus.est_input_tokens:,} |",
        f"| Mean per case | {corpus.mean_tokens:.1f} |",
        "",
        f"Token counts are **character-derived estimates** (`CHARS_PER_TOKEN = "
        f"{CHARS_PER_TOKEN}`, the same estimator the live `cost_budget` view uses), not "
        "tokenizer counts. They set the *scale* of the token split below; the headline "
        "percentage does not depend on them at all.",
        "",
    ]

    if prices is None:
        lines += [
            "## Cost delta",
            "",
            f"**{NOT_COMPUTED}** — no provider in `config/gateway.yaml` binds *both* cascade "
            "tiers to models with known prices. ADR-022 makes an unpriced model a legal "
            "configuration, and inventing a price to fill this section would fabricate the "
            "measurement the section exists to report.",
            "",
        ]
        return "\n".join(lines) + "\n", 1

    small, frontier = prices
    ratio = ratio_of(small, frontier)
    blend_ok = blend_independent(small, frontier)

    lines += [
        "## The two tiers, and the ratio the saving is computed at",
        "",
        "| Tier | Model | $/1K in | $/1K out |",
        "|---|---|---:|---:|",
        f"| small | `{small.model_id}` | {small.per_1k_in:.6f} | {small.per_1k_out:.6f} |",
        f"| frontier | `{frontier.model_id}` | {frontier.per_1k_in:.6f} | "
        f"{frontier.per_1k_out:.6f} |",
        "",
    ]

    if ratio is None:
        lines += [
            "## Cost delta",
            "",
            f"**{NOT_COMPUTED}** — the small tier is priced at zero, so the tier ratio is "
            "undefined and a *relative* saving has no value to report.",
            "",
        ]
        return "\n".join(lines) + "\n", 1

    lines += [
        f"**Measured tier ratio: {ratio:.1f}x**"
        + (", exact on input **and** output, so the ratio is **blend-independent** — no "
           "input/output mix can move it, and none was chosen to flatter it."
           if blend_ok else
           f" on input, but the output ratio DIFFERS "
           f"({frontier.per_1k_out / small.per_1k_out:.3f}x). The ratio is therefore "
           "**mix-dependent** on this price table, and the percentage below is an "
           "input-side figure rather than the blend-independent quantity ADR-029 "
           "describes. This is a finding about the price table, reported rather than "
           "smoothed."),
        "",
        "## Cost delta — a curve, because the routing fraction is not measured",
        "",
        "`f` is the share of requests the cascade escalates to the frontier tier. An "
        "escalated request pays **both** tiers, so:",
        "",
        "```",
        "baseline(N) = N x C_frontier",
        "cascade(N)  = N x C_small + f x N x C_frontier",
        f"saving      = 1 - (1/r + f)          r = {ratio:.1f}",
        "```",
        "",
        "| `f` | small-tier tokens | frontier-tier tokens | cost delta |",
        "|---:|---:|---:|---:|",
    ]
    for f in CURVE:
        small_tok, front_tok = token_split(corpus, f)
        saving = savings_fraction(ratio, f)
        sign = "saves" if saving > 0 else ("break-even" if abs(saving) < 1e-9 else "COSTS")
        lines.append(
            f"| {f:.2f} | {small_tok:,} | {front_tok:,} | "
            f"**{saving * 100:+.1f}%** ({sign}) |"
        )

    be = break_even(ratio)
    best = savings_fraction(ratio, 0.0)
    lines += [
        "",
        f"**Break-even at `f = {be:.2f}`** — above that share of escalations the cascade "
        f"costs more than sending everything to the frontier tier. Best case (`f = 0`) is "
        f"**{best * 100:.1f}%**, which is `1 - 1/r` and cannot be exceeded at this ratio.",
        "",
        f"**`f` itself is {NOT_COMPUTED}.** ADR-009 escalates *on low confidence*, and the "
        "confidence signal that would pick the escalations does not exist in this build: "
        "`fast_consistency` is cut (SL-6), no code path reads `thresholds.tau_route`, and "
        "`audit_records.cascade_escalated` is a column nothing writes. A measured `f` needs "
        "a live cascade probe; until one ships, the row a reader should use is the one "
        "matching their own escalation rate.",
        "",
        f"**Cascade quality proxy (06 §6): {NOT_COMPUTED}** — \"fraction of small-tier "
        "answers whose fast-confidence cleared `tau_route`\" is computed from the cut "
        "detector, so it has no input.",
        "",
        "### Absolute dollars — input tokens only",
        "",
        "Permitted for these two ids only (first-party prices, SL-3 as downgraded). "
        "**Input-side only**: the frozen corpus carries request text, not completions, so no "
        "measured `tokens_out` exists for it and an output figure would be invented.",
        "",
        "| Path | input-token cost |",
        "|---|---:|",
        f"| baseline — all {corpus.cases} cases at frontier | "
        f"${input_only_usd(corpus.est_input_tokens, frontier):.6f} |",
        f"| cascade at `f = 0` | "
        f"${input_only_usd(corpus.est_input_tokens, small):.6f} |",
        f"| cascade at break-even `f = {be:.2f}` | "
        f"${input_only_usd(corpus.est_input_tokens, small) + input_only_usd(token_split(corpus, be)[1], frontier):.6f} |",
        "",
        "The figures are small because the corpus is 280 short cases; the **percentage** is "
        "the transferable quantity, which is why it is the headline.",
        "",
        "## Ratio-parametric caveat (ADR-029, 06 §6)",
        "",
        f"Savings scale with **(tier ratio x routing fraction)**. The {ratio:.1f}x above is "
        "*this deployment's* gap, and it sits at the **low end** of the industry range — at "
        "the flagship-vs-mini gaps published elsewhere the same routing saves "
        "proportionally more, because `1 - 1/r` rises with `r`.",
        "",
        "The following is **context, cited to each vendor's own price page (retrieved "
        "2026-08-27) — not our measurement**:",
        "",
        "| Vendor | Pair | Gap |",
        "|---|---|---|",
    ]
    lines += [f"| {v} | {pair} | {gap} |" for v, pair, gap in CONTEXT_GAPS]
    lines += [
        "",
        "The observed cross-vendor range is roughly **5x-50x+**, and it is wide because it "
        "depends entirely on which pair is chosen. That spread *is* the ratio-parametric "
        "point, not a caveat to it.",
        "",
        f"_Host load at end: {load_stamp().get('load1')} (1-min)._",
        "",
    ]
    return "\n".join(lines), 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help="where to write the report (CI redirects; 06 §8)")
    args = parser.parse_args(argv)

    invocation = "python -m eval.cost_simulation"
    if args.out != DEFAULT_OUT:
        invocation += f" --out {args.out}"

    freeze_errors = check_freeze()
    corpus = load_corpus_tokens()
    prices = load_prices()
    text, code = render(corpus, prices, freeze_errors, invocation=invocation)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)
    print(text)
    print(f"-> {args.out}")
    return code


if __name__ == "__main__":
    sys.exit(main())
