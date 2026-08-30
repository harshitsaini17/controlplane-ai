"""Per-request forensic trace, assembled from the existing audit record (05 §3/§4).

Read-only and additive: no new table, no new column, no new write path. Everything here
is a *projection* of `audit_records` (+ the `review_items` join `canonical_view` already
performs), which is what makes it safe to add at this stage — a bug in this module can
misreport, but it cannot corrupt an append-only row.

Three rules govern every function below, and they are the reason this is a module rather
than a dict comprehension in the route:

1. **NFR-SEC-001.** Categories, labels, counts and span *offsets* travel; matched text
   never does. The audit columns are already scrubbed at write time
   (`records._check_no_raw_values`), so the discipline here is narrower but real: do not
   join to `review_items.quarantined_text`, which is the one column holding content, and
   do not add a field whose value is text the user typed.

2. **Derived is labelled as derived.** Several things a reader wants are not stored:
   per-sentence attribution of an output signal, per-stage attribution of coverage, the
   per-detector share of a shared span. Where this module computes such a thing it says
   so in the payload (`"derivation"`, `"attribution"`, `notes`), and where it cannot it
   returns `None` and lets the UI render "not recorded". A forensic view that quietly
   interpolates is worse than one with holes, because the holes are where a reader would
   otherwise form a false belief.

3. **The lane map is injected, never imported.** `LANES` lives in
   `controlplane.gateway.pipeline`, which imports `controlplane.audit.records` — so
   importing it here would invert the layering and pull the entire detector stack (and its
   ONNX/torch imports) into every consumer of `audit`, including eval harnesses that only
   want to read rows. The route passes `pipeline.LANES` in. There is deliberately **no
   default**: a local copy of the lane map would be a second source of truth for which
   detector runs where, and it would drift silently the first time a lane changed. The same
   applies to `SPAN_OF`, which is how a per-detector latency is attributed to the right span.

4. **The policy is read live and may not be the one that ran.** `policy_version` is
   stored on the row; the `Policy` object is fetched from the store now. When they differ
   the payload says so rather than presenting today's label map as the one that decided
   this verdict.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from controlplane.detectors.base import BUDGETS_MS, Stage, budget_ms
from controlplane.policy.engine import DETECTOR_FAIL_CLASS
from controlplane.policy.schema import Action, Policy, expand_actions
from controlplane.telemetry import spans

__all__ = ["list_requests", "trace", "SOURCE_LIVE", "SOURCE_NOT_RECORDED"]

#: Provenance strings for the G honesty rule. Every figure the payload carries names one.
SOURCE_LIVE = "live process telemetry (audit_records, this gateway process)"
SOURCE_NOT_RECORDED = "not recorded"

#: Detector state vocabulary — the four ADR-033 states, kept distinct on purpose. The
#: distinction is the point of the grid: `NOT_RUN` and `UNAVAILABLE` both mean "no result",
#: and only one of them means the system knows it could not look.
RAN_CLEAN = "RAN-CLEAN"
RAN_FIRED = "RAN-FIRED"
FAILED = "FAILED"
UNAVAILABLE = "UNAVAILABLE"
NOT_RUN = "NOT-RUN"

#: Human labels for the timeline nodes, in lifecycle order (02 §4).
_STAGE_NODES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ingress", "Ingress", (spans.INGRESS,)),
    ("input_lane", "Input lane", (spans.INPUT_TIER1, spans.INPUT_TIER2)),
    ("cost", "Cost gate + routing", (spans.COST_BUDGET, spans.COST_ROUTE)),
    # `upstream_ms` and not `spans.UPSTREAM`: the gateway records the provider wait under
    # the LATENCY_EXTRA_KEYS name (it must be *subtractable* per 06 §4), and `cp.upstream`
    # is never written. Reading the span key here reported "skipped" on every request that
    # actually dispatched — a false claim about the most visible stage on the timeline.
    ("dispatch", "Upstream dispatch", ("upstream_ms",)),
    ("output_lane", "Output lane", (spans.OUT_TIER1, spans.OUT_TIER2,
                                    spans.OUT_CONSISTENCY, spans.OUT_GROUNDING)),
    ("convergence", "Convergence", (spans.POLICY_EVALUATE,)),
    ("verdict", "Actions applied", (spans.ACTION_APPLY,)),
    ("audit", "Audit write", (spans.AUDIT_WRITE,)),
)

#: Which `Stage` each timeline node carries detectors for. Nodes with no lane are absent.
_NODE_STAGE: dict[str, Stage] = {
    "input_lane": Stage.INPUT,
    "output_lane": Stage.OUTPUT_SENTENCE,
}


def _loads(value: Any, default: Any) -> Any:
    """Tolerant JSON read. A malformed column must not 500 the forensic view.

    The audit writer validates on the way in, so this should never fire — but this module
    is the thing an operator opens *when something already went wrong*, and a view that
    dies on the row it exists to explain is the wrong failure mode.
    """
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _stream_mode(stage_summary: str | None) -> str:
    """Delivery mode, derived from the stored `stage_summary` (05 §3).

    Not a stored field: `streaming` is a policy property and `stage_summary` records how
    far this request actually got, which is the more useful of the two here — a streaming
    policy that blocks pre-dispatch never streamed anything.
    """
    return {
        "input": "blocked-pre-dispatch",
        "streamed": "streaming",
        "completed": "non-streaming",
    }.get(stage_summary or "", "not recorded")


def list_requests(conn: sqlite3.Connection, *, limit: int = 50) -> list[dict[str, Any]]:
    """Newest-first request list for the picker (Part 1.1).

    `labels` is categories only — the taxonomy strings from the signals, deduped and
    sorted. `detectors_ran_count` counts the coverage column's `ran` list rather than the
    signals, because a detector that ran and found nothing emits no signal and would
    otherwise be invisible (the M-10 distinction this column exists for).
    """
    limit = max(1, min(int(limit), 500))
    rows = conn.execute(
        """SELECT request_id, ts_utc, use_case, policy_version, verdict, stage_summary,
                  signals_json, detectors_json, latency_json, upstream_class,
                  est_cost_usd, record_status
             FROM audit_records ORDER BY ts_utc DESC, rowid DESC LIMIT ?""",
        (limit,),
    ).fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        signals = _loads(row["signals_json"], [])
        coverage = _loads(row["detectors_json"], {})
        latency = _loads(row["latency_json"], {})
        labels = sorted({lab for s in signals for lab in (s.get("labels") or [])})
        out.append({
            "request_id": row["request_id"],
            "ts_utc": row["ts_utc"],
            "use_case": row["use_case"],
            "policy_version": row["policy_version"],
            "verdict": row["verdict"],
            "stream_mode": _stream_mode(row["stage_summary"]),
            "labels": labels,
            "detectors_ran_count": len(coverage.get("ran") or []),
            # The ADR-030 attributable series, which is the figure NFR-P-001 targets.
            # Absent rather than zero when unrecorded: 0.0 would read as "instant".
            "total_hold_ms": latency.get("total_attributable_overhead_ms"),
            "upstream_class": row["upstream_class"],
            "est_cost_usd": row["est_cost_usd"],
            "record_status": row["record_status"],
        })
    return out


def _threshold_applied(signal: dict[str, Any], policy: Policy | None) -> dict[str, Any]:
    """What band/threshold governed this signal — or why none did (04 §4.3 step 2).

    ADR-012 makes polarity normative: band logic applies to `confidence` scores ONLY.
    Reporting a tau band beside a `detection` score would invent a comparison the engine
    never performed, so the detection branch returns the reason instead of the numbers.
    """
    if signal.get("score_kind") != "confidence":
        return {
            "kind": "none",
            "reason": "detection-kind score — band logic never applies (04 §4.3 step 2, ADR-012)",
        }
    if policy is None:
        return {"kind": "band", "tau_low": None, "tau_high": None,
                "reason": "policy not loadable now — band not recoverable"}
    return {
        "kind": "band",
        "tau_low": policy.thresholds.tau_low,
        "tau_high": policy.thresholds.tau_high,
        "borderline_action": policy.borderline_action.value,
    }


def _detector_rows(
    *,
    signals: list[dict[str, Any]],
    coverage: dict[str, Any],
    failures: list[dict[str, Any]],
    latency: dict[str, Any],
    reached: set[str],
    policy: Policy | None,
    lanes: dict[Stage, tuple[str, ...]],
    span_of: dict[tuple[Stage, str], str],
) -> list[dict[str, Any]]:
    """One row per (stage, detector) the policy could have run — the Part C grid.

    Enumerated from the injected lane map rather than from the signals, which is what lets the grid show
    absence: a detector that never ran has no signal to enumerate, and the whole purpose
    of the four-state distinction is to make "we did not look here" visible.

    Two attributions are **derived, not stored**, and each row says which:
    * `ran` in the coverage column is request-level, so a detector in two lanes cannot be
      attributed to one of them from that column alone. A signal pins the stage; without
      one the row reports `stage_attribution: "derived"`.
    * `latency_json` spans are per-*span*, and `cp.input.tier1` covers both tier1
      detectors. `attributable_ms` therefore prefers the signal's own `latency_ms` (a
      per-invocation measurement) and falls back to the shared span with `shared: True`.

    The shared-span fallback reads the injected `SPAN_OF` map rather than picking the first
    span present on the node. That distinction is load-bearing: the output node carries four
    span keys, so "first present" would charge `rag_grounding` with `cp.out.tier1`'s time.
    A detector absent from `SPAN_OF` has **no span key by ruling** (M-8: 05 §5 is the closed
    vocabulary and has no entry for `numeric_claims`), so it reports `None` — not another
    detector's number.
    """
    ran = set(coverage.get("ran") or [])
    not_run = {e["detector"]: e.get("reason") for e in (coverage.get("not_run") or [])}
    unavailable = {e["detector"]: e.get("missing") for e in (coverage.get("unavailable") or [])}
    failed: dict[tuple[str, str], dict[str, Any]] = {
        (f.get("stage", ""), f.get("detector", "")): f for f in failures
    }
    by_stage_detector: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for sig in signals:
        by_stage_detector.setdefault((sig.get("stage", ""), sig.get("detector", "")), []).append(sig)

    rows: list[dict[str, Any]] = []
    for node_key, stage in _NODE_STAGE.items():
        if node_key not in reached:
            continue
        for detector in lanes.get(stage, ()):
            fired = by_stage_detector.get((stage.value, detector), [])
            fault = failed.get((stage.value, detector))
            budget = budget_ms(detector) if detector in BUDGETS_MS else None

            if detector in unavailable:
                state, note = UNAVAILABLE, unavailable[detector]
            elif fault is not None:
                state, note = FAILED, fault.get("error_class")
            elif fired:
                state, note = RAN_FIRED, None
            elif detector in ran:
                state, note = RAN_CLEAN, None
            else:
                state, note = NOT_RUN, not_run.get(detector) or SOURCE_NOT_RECORDED

            span_key = span_of.get((stage, detector))
            attributable = None
            shared = False
            if fired and fired[0].get("latency_ms") is not None:
                attributable = fired[0]["latency_ms"]
            elif span_key is not None and span_key in latency:
                attributable = latency.get(span_key)
                shared = True

            row: dict[str, Any] = {
                "stage": stage.value,
                "node": node_key,
                "detector": detector,
                "plane": sorted({p for s in fired for p in (s.get("planes") or [])}) or None,
                "fail_class": DETECTOR_FAIL_CLASS.get(detector),
                "state": state,
                "state_detail": note,
                "score": fired[0].get("score") if fired else None,
                "score_kind": fired[0].get("score_kind") if fired else None,
                "threshold": _threshold_applied(fired[0], policy) if fired else None,
                "labels": sorted({l for s in fired for l in (s.get("labels") or [])}),
                # Offsets only — never the matched text (NFR-SEC-001). `evidence` is a
                # `category:… pattern=…` string built by the detector, not user content.
                "spans": [s["span"] for s in fired if s.get("span")],
                "evidence": [s.get("evidence") for s in fired] or None,
                "signal_ids": [s.get("signal_id") for s in fired],
                "attributable_ms": attributable,
                "attributable_shared_span": shared,
                "span_key": span_key if shared else None,
                "budget_ms": budget,
                # Computed ONLY from a per-invocation measurement. A shared span
                # (`cp.out.tier2` covers every sentence; `cp.input.tier1` covers both tier1
                # detectors) is an aggregate over invocations, and comparing it to a
                # per-window budget is the two-clock defect ADR-036 exists to end — it
                # rendered `tier2_toxicity` 38.9 ms vs 25 ms as a breach when nothing had
                # breached. `None` here means "not comparable", not "within budget".
                "breach": (
                    None if attributable is None or budget is None or shared
                    else attributable > budget
                ),
                "breach_note": (
                    "shared span — aggregate over invocations, not comparable to a "
                    "per-invocation budget (ADR-036)" if shared and budget is not None
                    else None
                ),
                "stage_attribution": "recorded" if fired else "derived",
            }
            if fault is not None:
                row["fail_mode_applied"] = fault.get("fail_mode_applied")
                row["failure_id"] = fault.get("failure_id")
            rows.append(row)
    return rows


def _timeline(
    *,
    latency: dict[str, Any],
    verdict: str | None,
    stage_summary: str | None,
    signals: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    actions: dict[str, Any],
    coverage: dict[str, Any],
    span_of: dict[tuple[Stage, str], str],
) -> tuple[list[dict[str, Any]], set[str]]:
    """The Part B stage timeline, plus the set of nodes the request actually reached.

    Reached-ness is derived from the latency keys present: a span is written when the
    interval is measured, so an absent span is the record's own statement that the stage
    did not run. The pre-dispatch block is the case that makes this worth stating — the
    reason a node is grey ("upstream never called") is a *fact about this request*, not a
    UI default.

    Streaming expands into one node per hold in `sentence_holds_ms`. Which sentence raised
    which signal is **not stored**, so each sentence node carries its hold only, and the
    signals stay on the aggregate output-lane node with `per_unit_attribution: null`.
    """
    holds = latency.get(spans_series := "sentence_holds_ms")
    holds = holds if isinstance(holds, list) else []
    blocked_pre_dispatch = spans.UPSTREAM not in latency and (stage_summary == "input")

    nodes: list[dict[str, Any]] = []
    reached: set[str] = set()
    for key, label, span_keys in _STAGE_NODES:
        present = [k for k in span_keys if k in latency]
        elapsed = sum(float(latency[k]) for k in present) if present else None
        if present:
            reached.add(key)

        if key == "dispatch" and not present:
            state, reason = "skipped", (
                "blocked pre-dispatch — upstream never called"
                if blocked_pre_dispatch else "no upstream span recorded"
            )
        elif not present:
            state, reason = "skipped", "no span recorded for this stage"
        elif key == "input_lane" and any(s.get("stage") == "input" for s in signals):
            state, reason = "signal", None
        elif key == "output_lane" and any(
            s.get("stage", "").startswith("output") for s in signals
        ):
            state, reason = "signal", None
        elif any(f.get("stage") == key for f in failures):
            state, reason = "failed", None
        else:
            state, reason = "clean", None

        node: dict[str, Any] = {
            "key": key, "label": label, "state": state, "reason": reason,
            "elapsed_ms": elapsed, "spans_present": present,
            "source": SOURCE_LIVE if present else SOURCE_NOT_RECORDED,
        }
        if key == "output_lane":
            node["units"] = [
                {"index": i + 1, "of": len(holds), "hold_ms": h,
                 "per_unit_attribution": None}
                for i, h in enumerate(holds)
            ]
            node["unit_note"] = (
                "per-sentence hold is recorded; which sentence raised which signal is not "
                f"stored (no unit index in the 05 §3 schema) — {spans_series}"
            ) if holds else None
        if key == "audit" and not present:
            # Structural, not a gap in the record: the duration of the write cannot be
            # inside the row being written. The row's existence is the evidence the stage
            # ran, so saying "skipped" here would contradict the document reporting it.
            node["state"] = "clean"
            node["reason"] = (
                "row exists, so the write completed; its own duration is not recordable "
                "inside the record it writes"
            )
            node["source"] = "evidenced by this record existing"
        if key == "cost" and not present:
            # DERIVED, and that is the correction rather than a nicety. This said "cost plane
            # unbuilt — cost_budget and loop_guard are stubs" until those two shipped, which
            # made it false for every record written afterwards. A forensic view reads
            # *history*: a fixed sentence about the build's state is a claim about the reader's
            # present tense stamped onto a row from the past, so the only version that cannot
            # rot is one read out of the record in hand.
            cost_detectors = sorted(
                name for (_stage, name), span in span_of.items()
                if span in span_keys
            )
            ran = set(coverage.get("ran") or [])
            not_run = {e["detector"]: e.get("reason")
                       for e in (coverage.get("not_run") or [])}
            unavailable = {e["detector"]: e.get("missing")
                           for e in (coverage.get("unavailable") or [])}
            listed = [d for d in cost_detectors
                      if d in ran or d in not_run or d in unavailable]
            if any(d in ran for d in cost_detectors):
                # Should be unreachable: `run_lane` writes the span for a detector it ran.
                # Reported rather than smoothed over, because a coverage column and a
                # latency column disagreeing is exactly what an operator opened this for.
                node["reason"] = (
                    "coverage says "
                    + ", ".join(f"`{d}`" for d in cost_detectors if d in ran)
                    + " ran, yet no cost span was recorded — the two columns disagree"
                )
            elif not_run and any(d in not_run for d in cost_detectors):
                node["reason"] = "; ".join(
                    f"`{d}` not run ({not_run[d] or 'no reason recorded'})"
                    for d in cost_detectors if d in not_run
                )
            elif any(d in unavailable for d in cost_detectors):
                node["reason"] = "; ".join(
                    f"`{d}` unavailable ({unavailable[d] or 'no dependency named'})"
                    for d in cost_detectors if d in unavailable
                )
            elif not listed:
                # Ambiguous BY CONSTRUCTION, and said so instead of guessed at: 05 §4 omits a
                # policy-disabled detector from the column entirely, so absence here reads
                # identically to a record written before the cost plane existed. Naming one
                # cause would be inventing evidence the column does not carry (M-10).
                node["reason"] = (
                    "no cost span, and no cost detector is listed in this record's coverage "
                    "column — either policy switched them off for this use case or the record "
                    "predates the cost plane; 05 §4 omits a disabled detector, so the column "
                    "cannot separate those two"
                )
            if spans.COST_ROUTE not in latency:
                # The surviving cost-plane gap (SL-10): nothing writes this span
                # because no cascade router exists. Kept as its own field so the routing
                # gap does not get mistaken for a fact about the budget gate.
                node["routing"] = (
                    "not evaluated — no cascade router is implemented, so `cp.cost.route` is "
                    "never written (SL-10)"
                )
        if key == "verdict":
            node["verdict"] = verdict
            node["fallback_substituted"] = bool(actions.get("fallback_used"))
            node["quarantined"] = bool(actions.get("quarantined"))
        nodes.append(node)
    return nodes, reached


def _convergence(
    *,
    signals: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    contributing_signal_ids: list[str],
    failure_record_ids: list[str],
    verdict: str | None,
    policy: Policy | None,
    actions: dict[str, Any],
) -> dict[str, Any]:
    """The Part D decision arithmetic: label → matched rule → action, then the ladder.

    Shows *why* rather than *what*. The per-label action comes from `expand_actions`, the
    same resolution the engine performs, so the precedence shown (specific > wildcard >
    default) is the real one rather than a re-implementation.

    The escalate floor is a separate contributing input, not a label row: ADR-027 makes it
    a consequence of a *fault*, which has no label and no plane, and folding it into the
    label ladder would misattribute a verdict to content that did not cause it.
    """
    resolved = expand_actions(policy.actions, policy.default_action) if policy else {}
    contributing = set(contributing_signal_ids)

    label_rows: list[dict[str, Any]] = []
    for sig in signals:
        for label in sig.get("labels") or []:
            rule = "not recoverable"
            if policy is not None:
                if label in policy.actions:
                    rule = f"actions['{label}'] (specific)"
                else:
                    wildcard = next(
                        (k for k in policy.actions
                         if k.endswith(".*") and label.startswith(k[:-1])), None)
                    rule = f"actions['{wildcard}'] (wildcard)" if wildcard else "default_action"
            label_rows.append({
                "label": label,
                "detector": sig.get("detector"),
                "signal_id": sig.get("signal_id"),
                "matched_rule": rule,
                "action": resolved.get(label, {}).value if hasattr(
                    resolved.get(label, {}), "value") else None,
                "contributed": sig.get("signal_id") in contributing,
                "score": sig.get("score"),
                "score_kind": sig.get("score_kind"),
            })

    floor_rows = [{
        "failure_id": f.get("failure_id"),
        "detector": f.get("detector"),
        "error_class": f.get("error_class"),
        "fail_mode_applied": f.get("fail_mode_applied"),
        "contributed": f.get("failure_id") in set(failure_record_ids),
        "forced_escalate_floor": f.get("failure_id") in set(failure_record_ids)
                                 and bool(actions.get("promoted_to_escalate")),
    } for f in failures]

    ladder = [
        {"action": a.value, "severity": a.severity, "winning": a.value == verdict}
        for a in sorted(Action, key=lambda a: a.severity, reverse=True)
    ]
    winners = sorted({r["label"] for r in label_rows
                      if r["contributed"] and r["action"] == verdict})
    return {
        "label_resolution": label_rows,
        "failure_inputs": floor_rows,
        "severity_ladder": ladder,
        "verdict": verdict,
        "won_by_labels": winners,
        "won_by_escalate_floor": bool(actions.get("promoted_to_escalate")),
        "contributing_signal_ids": contributing_signal_ids,
        "failure_record_ids": failure_record_ids,
        "note": (
            "severity order is BLOCK > ESCALATE > EDIT > PASS (04 §4.2); a verdict with no "
            "winning label row and no escalate floor was decided by the default action"
        ),
        "source": SOURCE_LIVE,
    }


def _policy_context(
    *, policy: Policy | None, stored_version: int | None, signals: list[dict[str, Any]],
    all_policies: dict[str, Policy] | None,
) -> dict[str, Any]:
    """Part F strip. Includes the cross-pipeline projection ONLY as what it actually is.

    The "what would the other pipelines have done?" line is a **label-map projection**:
    the other policies' `actions` maps resolved over exactly the labels this request
    raised. That is derivable from committed policy config, so it is included — but it is
    not a re-run, and it is named accordingly. It ignores per-policy thresholds, band
    logic, detector coverage and delivery mode, any of which can change the real verdict.
    Presenting it as a simulated verdict would be the fabrication this section forbids.
    """
    labels = sorted({l for s in signals for l in (s.get("labels") or [])})
    ctx: dict[str, Any] = {
        "policy_version_recorded": stored_version,
        "policy_version_loaded_now": policy.policy_version if policy else None,
        "policy_matches_record": bool(
            policy and stored_version is not None and policy.policy_version == stored_version
        ),
        "labels_raised": labels,
        "source": "committed policy config (config/policies/*.yaml), read live",
    }
    if policy is not None:
        resolved = expand_actions(policy.actions, policy.default_action)
        ctx.update({
            "governing_rules": {l: resolved[l].value for l in labels if l in resolved},
            "default_action": policy.default_action.value,
            "borderline_action": policy.borderline_action.value,
            "thresholds": {"tau_low": policy.thresholds.tau_low,
                           "tau_high": policy.thresholds.tau_high,
                           "tau_route": policy.thresholds.tau_route},
            "fail_mode": {"tier1": policy.fail_mode.tier1.value,
                          "tier2": policy.fail_mode.tier2.value,
                          "performance": policy.fail_mode.performance.value,
                          "cost": policy.fail_mode.cost.value},
            "streaming": policy.streaming,
            "geography": policy.geography,
            "risk_appetite": policy.risk_appetite.value,
        })
    if all_policies and labels:
        projection = {}
        for name, other in all_policies.items():
            other_resolved = expand_actions(other.actions, other.default_action)
            acts = [other_resolved[l] for l in labels if l in other_resolved]
            projection[name] = {
                "per_label": {l: other_resolved[l].value for l in labels if l in other_resolved},
                "most_severe": max(acts, key=lambda a: a.severity).value if acts else None,
                "policy_version": other.policy_version,
            }
        ctx["cross_pipeline_projection"] = projection
        ctx["cross_pipeline_caveat"] = (
            "LABEL-MAP PROJECTION, not a re-run: each policy's action map resolved over the "
            "labels this request raised. It ignores that policy's thresholds, band logic, "
            "detector coverage and delivery mode, any of which can change the real verdict."
        )
    return ctx


def trace(
    conn: sqlite3.Connection,
    request_id: str,
    *,
    lanes: dict[Stage, tuple[str, ...]],
    span_of: dict[tuple[Stage, str], str],
    policy: Policy | None = None,
    all_policies: dict[str, Policy] | None = None,
) -> dict[str, Any]:
    """The full per-request trace (Part 1.2). Raises `KeyError` if the row is absent.

    Every field is read from the row or derived from it with the derivation named. Nothing
    is backfilled: a quantity the schema does not store comes back `None` so the UI can
    render "not recorded" rather than a plausible number.
    """
    row = conn.execute(
        "SELECT * FROM audit_records WHERE request_id = ?", (request_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"no audit record {request_id!r}")

    signals = _loads(row["signals_json"], [])
    failures = _loads(row["detector_failures_json"], [])
    actions = _loads(row["actions_json"], {})
    latency = _loads(row["latency_json"], {})
    coverage = _loads(row["detectors_json"], {})

    timeline, reached = _timeline(
        latency=latency, verdict=row["verdict"], stage_summary=row["stage_summary"],
        signals=signals, failures=failures, actions=actions,
        coverage=coverage, span_of=span_of,
    )

    review: dict[str, Any] | None = None
    item = conn.execute(
        """SELECT review_id, ts_created, status, decision_ts, reviewer_note
             FROM review_items WHERE request_id = ?
             ORDER BY ts_created DESC LIMIT 1""",
        (request_id,),
    ).fetchone()
    if item is not None:
        # `quarantined_text` is deliberately NOT selected: it is the one column holding
        # content, and /admin/review/{id}/released is the audited surface for it.
        review = {
            "review_id": item["review_id"], "ts_created": item["ts_created"],
            "status": item["status"], "decision_ts": item["decision_ts"],
            "reviewer_note": item["reviewer_note"],
            "note": "quarantined text is not exposed here; use /admin/review/{id}/released",
        }

    return {
        "identity": {
            "request_id": row["request_id"],
            "ts_utc": row["ts_utc"],
            "use_case": row["use_case"],
            "policy_version": row["policy_version"],
            "conversation_id": row["conversation_id"],
            "stage_summary": row["stage_summary"],
            "stream_mode": _stream_mode(row["stage_summary"]),
            "verdict": row["verdict"],
            "record_status": row["record_status"],
            "sampled_deep": bool(row["sampled_deep"]),
            "upstream_class": row["upstream_class"],
            "tier_requested": row["tier_requested"],
            "model_used": row["model_used"],
            "cascade_escalated": bool(row["cascade_escalated"]),
            "tokens_in": row["tokens_in"],
            "tokens_out": row["tokens_out"],
            "est_cost_usd": row["est_cost_usd"],
            "cost_note": (
                None if row["upstream_class"] == "measured" else
                "dev-class upstream — token counts are not a measurement and est_cost_usd "
                "stays null by ADR-018"
            ),
            "source": SOURCE_LIVE,
        },
        "timeline": timeline,
        "detectors": _detector_rows(
            signals=signals, coverage=coverage, failures=failures, latency=latency,
            reached=reached, policy=policy, lanes=lanes, span_of=span_of,
        ),
        "coverage_raw": coverage,
        "failures": [{
            "failure_id": f.get("failure_id"), "detector": f.get("detector"),
            "error_class": f.get("error_class"), "stage": f.get("stage"),
            "fail_mode_applied": f.get("fail_mode_applied"), "ts": f.get("ts"),
            "fail_class": DETECTOR_FAIL_CLASS.get(f.get("detector", "")),
            "forced_escalate_floor": bool(actions.get("promoted_to_escalate")),
            # A fault has no measured interval of its own in the schema: the detector
            # raised rather than returned, so there is no per-invocation latency to read.
            "attributable_ms": None,
            "source": SOURCE_LIVE,
        } for f in failures],
        "convergence": _convergence(
            signals=signals, failures=failures,
            contributing_signal_ids=_loads(row["contributing_signal_ids"], []),
            failure_record_ids=_loads(row["failure_record_ids"], []),
            verdict=row["verdict"], policy=policy, actions=actions,
        ),
        "actions": {
            "applied": actions.get("applied") or [],
            "input_redactions": actions.get("input_redactions") or [],
            "quarantined": bool(actions.get("quarantined")),
            "fallback_substituted": bool(actions.get("fallback_used")),
            "promoted_to_escalate": bool(actions.get("promoted_to_escalate")),
            "review_id": actions.get("review_id"),
            "notes": actions.get("notes") or [],
            "delivery": (
                "quarantined — nothing delivered" if actions.get("quarantined")
                else "fallback substituted" if actions.get("fallback_used")
                else "delivered"
            ),
            "source": SOURCE_LIVE,
        },
        "latency_raw": latency,
        "review": review,
        "policy_context": _policy_context(
            policy=policy, stored_version=row["policy_version"], signals=signals,
            all_policies=all_policies,
        ),
    }
