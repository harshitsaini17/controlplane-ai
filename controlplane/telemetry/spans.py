"""Span name constants — the fixed vocabulary of 05 §5.

Implements the span list in 05 §5 exactly. These names are the keys of
`audit_records.latency_json` (05 §3), so they are a **persisted contract**: renaming
one silently orphans every historical record that used the old key, and a typo
creates a second key that no dashboard reads. That is why this module exports names
rather than letting call sites write string literals, and why `check_latency_keys`
exists — a misspelled key is caught at the write path instead of surfacing as a
missing panel three days later.

Two names are deliberately NOT here:

* `gateway_overhead_ms` and `upstream_ms` are `latency_json` keys but not spans —
  05 §3 lists them alongside "per-detector ms", and `gateway_overhead_ms` is a
  *derived* figure with a normative formula in 06 §4, not a measured interval.
  `LATENCY_EXTRA_KEYS` holds them so the write-path check knows they are legal.
* There is no span for the deep lane. Nothing on the hot path awaits it
  (NFR-P-003), so it contributes no hot-path interval; its timings live in
  `deep_audit_results` (05 §3).
"""

from __future__ import annotations

#: Ingress: resolve use case -> load policy version (02 §4 step t0).
INGRESS = "cp.ingress"

#: Input lane (02 §4 step t0+), before dispatch.
INPUT_TIER1 = "cp.input.tier1"
INPUT_TIER2 = "cp.input.tier2"

#: Cost plane, pre-dispatch (02 §5): budget gate, then tier routing.
COST_BUDGET = "cp.cost.budget"
COST_ROUTE = "cp.cost.route"

#: The upstream provider call. Excluded from `gateway_overhead_ms` by 06 §4 —
#: provider variance is not gateway overhead.
UPSTREAM = "cp.upstream"

#: Output lane, per sentence (streaming) or once over the full response (ADR-014).
OUT_TIER1 = "cp.out.tier1"
OUT_TIER2 = "cp.out.tier2"
OUT_CONSISTENCY = "cp.out.consistency"
OUT_GROUNDING = "cp.out.grounding"

#: Convergence and delivery.
POLICY_EVALUATE = "cp.policy.evaluate"
ACTION_APPLY = "cp.action.apply"
AUDIT_WRITE = "cp.audit.write"

#: Every span in 05 §5, in the order that doc lists them.
ALL: tuple[str, ...] = (
    INGRESS,
    INPUT_TIER1,
    INPUT_TIER2,
    COST_BUDGET,
    COST_ROUTE,
    UPSTREAM,
    OUT_TIER1,
    OUT_TIER2,
    OUT_CONSISTENCY,
    OUT_GROUNDING,
    POLICY_EVALUATE,
    ACTION_APPLY,
    AUDIT_WRITE,
)

#: `latency_json` keys that are legal but are not spans (see the module docstring).
#: `gateway_overhead_ms` is derived per the 06 §4 formula; `upstream_ms` is the
#: provider wait, recorded because it must be *subtractable*, not because it is ours.
LATENCY_EXTRA_KEYS: frozenset[str] = frozenset({"gateway_overhead_ms", "upstream_ms"})

#: Everything that may appear as a `latency_json` key (05 §3).
LATENCY_KEYS: frozenset[str] = frozenset(ALL) | LATENCY_EXTRA_KEYS


def check_latency_keys(latency: object) -> None:
    """Raise `ValueError` if `latency` carries a key outside the 05 §5 vocabulary.

    Called by the audit write path. A per-detector span that is absent is normal —
    a detector that did not run has no interval — so this checks for *unknown*
    keys, never for missing ones.
    """
    if not isinstance(latency, dict):
        raise TypeError(f"latency_json must be a mapping, got {type(latency).__name__}")
    unknown = sorted(set(latency) - LATENCY_KEYS)
    if unknown:
        raise ValueError(
            f"latency_json keys {unknown} are not in the 05 §5 span vocabulary; "
            "add the span to 05 §5 first (AGENTS.md §4), then to this module"
        )
