# 08 — Open Questions

Format: Question / Why it matters / Options / Current assumption / Deadline / Status.
Agents: check here before raising a D4 deviation; MINOR gaps you resolve get logged here (AGENTS.md §6).

---

**Q-01 — Round 2 video length limit?**
Why: Round 1 limit was 3 min; the drafted script ran 5:00; Round 2 brief (our copy) doesn't state a limit.
Options: (a) confirm from portal/organizer email, (b) assume 3 min and cut.
Assumption: **3 minutes until confirmed** — storyboard must be cuttable to 3:00.
Deadline: before storyboarding. Status: OPEN

**Q-05 — Include conversation-level cumulative tracking (P2) in demo?**
Why: strong differentiator (brief's multi-turn/agentic complexity) but last-priority build item.
Assumption: build FR-DET-006 only after all P0+P1 green; demo beat 8 mentions it as roadmap if not landed.
Deadline: final week triage. Status: OPEN

**Q-06 — Team details for submission template**
Why: Accenture PPTX template requires names/college/stream/photos; repo must be public — decide what personal info goes where.
Assumption: template gets full details; public repo README gets names only (no photos/emails).
Deadline: before submission packaging. Status: OPEN

**Q-07 — Semantic-entropy deep audit: real NLI clustering or embedding-cluster approximation?**
Why: true NLI pairwise entailment on 5 samples may be slow/heavy for the worker; embedding clustering is a documented approximation.
Options: (a) NLI model pairwise, (b) embedding + agglomerative clustering labeled as approximation.
Assumption: (b), honestly labeled in report + proposal ("entropy over embedding-similarity clusters, an approximation of Farquhar et al.").
Deadline: deep-lane sprint. Status: OPEN

**Q-08 — Hosting for judges (live URL vs local-only)?**
Why: public repo is required; a live demo URL is not — but might impress.
Assumption: local-only + demo video; revisit only with time surplus (respect charter NG1).
Deadline: final week. Status: OPEN

**Q-10 — Which genuinely local model serves fallback + second-sample duty?** (reopened from Q-02 by ADR-018)
Why: three things lean on it — the `fail_open` path when the upstream is unreachable mid-demo, the parallel 2nd sample `fast_consistency` needs (04 §2.3, ~2× tokens wherever sampling occurs), and `--replay` recording generation. It is also the only provider that could be `measured` at zero marginal cost, which is what makes the cost plane demonstrable without spending real money.
Evidence closing the previous ruling: Q-02 named `llama-3.2-3b via Ollama`, but **no such model is installed**. The single model present is `minimax-m2.7:cloud`, whose manifest carries `remote_host: https://ollama.com:443` — a cloud model reached through a local CLI, so it fails the no-`remote_host` assertion and cannot honestly be classed local. `config/gateway.yaml`'s `ollama-local` entry is therefore `STUB`-marked with both `tiers` null: it is a declared shape, not a working provider.
Options: (a) `ollama pull` a small genuinely-local model (~2 GB) and assert no `remote_host` in its manifest before classing it; (b) drop the local provider and accept that fail-open has no fallback target and consistency sampling costs real Groq tokens; (c) keep the entry declared-but-null and let FR-GW-006's loud-fallback rule surface the gap at boot.
Assumption: **(a)**, gated on the assertion actually passing — the entry stays `STUB` until then. Until it passes, treat fallback as unavailable rather than as working, and never report a fallback latency or cost number from it (AGENTS.md §7).
Deadline: before the consistency detector sprint (it needs the 2nd sample) — earlier if the cost plane is demoed. Status: **OPEN**

---

## Deviation ledger

Every deviation report filed against this repo, and its current status. **This table is what
AGENTS.md §11's "enumerate every open deviation" rule is enumerated from** — before this,
slugs lived scattered across doc prose, YAML comments, docstrings and test notes, which made
"is anything still open?" a question only a full-tree grep could answer.

| Slug | Sev | Filed | Status |
|---|---|---|---|
| `[D1-band-logic-vs-beat-4b]` | BLOCKER | Phase 1 | **CLOSED** — ADR-017 (per-label band + required `borderline_action`) |
| `[D4-enriched-label-survival-semantics]` | BLOCKER | Step 2 | **CLOSED** — ADR-019 (two branches; the band never reaches an enriched label) |
| `[D4-input-stage-pii-edit-unresolvable]` | MAJOR | Step 2 | **CLOSED** — ADR-020 (input EDIT = pre-dispatch redaction; overruled the report's own recommendation) |
| `[D2-nonstreaming-token-counts-inflated]` | MAJOR | Step 1 | **CLOSED** — ADR-018 root-caused it as a provenance problem; the dev/measured split is the structural answer and FR-GW-006's canary catches recurrences at boot |
| `[D2-upstream-price-table-absent]` | MINOR | Step 1 | **CLOSED** — ADR-022 makes `pricing: null` a legitimate, documented state meaning UNKNOWN (distinct from `unmetered`, which is an affirmative zero) |
| `[D2-price-table-cannot-express-per-tier-cost]` | MAJOR | Step 2 | **CLOSED** — ADR-022 (prices keyed by concrete model id) |

**Open: none.** Two non-deviation items still gate work and are tracked as questions, not
deviations: **Q-10** (no genuinely local model installed — fallback and 2nd-sample duty
unassigned) and the Groq price-provenance caveat under Q-02, which constrains what the cost
simulation may publish rather than blocking it.

---

## Resolved
*(move items here with the ruling + date + ADR link)*

**Q-13 — Does the ADR-022 hard-boot-failure rule apply to a `dev`-class provider?** — RESOLVED 2026-08-25 (MINOR gap, AGENTS.md §6; agent-resolved).
Why: 05 §6.1's table said "model missing at boot **and** named in `tiers` ⇒ hard boot failure" without naming a class. Read literally that refuses to boot the shipped `active_provider: kiro-local`, which is `dev`-class with `pricing: null` and both tiers bound — i.e. the documented development path would not start.
Ruling: **both boot rows are measured-class only.** The fatal row refines the `measured` warning row directly above it, and ADR-018 exists precisely so a dev-class provider is usable *while* unpriceable — its numbers are barred from every judge-facing artifact anyway, so bricking that path protects a report it can never produce. For a `measured` provider the reasoning inverts and the failure stays fatal: its data may carry judge-facing numbers, so an unpriced model on a routing path will answer real requests and mint uncostable audit records.
Applied to: 05 §6.1 (scope paragraph added), `GatewayConfig._check_price_coverage`, and `test_dev_class_provider_may_boot_unpriced_on_a_routing_path` — which pins the decision so a later "tighten the guard" edit fails loudly rather than silently breaking `make run`.

**Q-12 — What is the dataset freeze gate, concretely?** — RESOLVED 2026-08-25 (MINOR gap, AGENTS.md §6; agent-resolved).
Why: 06 §2 required labels to be reviewed and frozen but named no command, so "frozen" had no mechanical meaning and nothing could fail.
Ruling: `python -m eval.validate_dataset` is the gate, named in 06 §2.4. It checks the §2.1 format, the 04 §1.1 closed taxonomy, `action_expected` key sets, the ADR-023 causal fields, synthetic-safety construction (never-assigned SSN ranges, Luhn, RFC 2606, the 555-01xx block), and — the substantive part — **re-derives every expected action** from ground truth + the loaded policy and compares. It validates **consistency, not label correctness**; label judgement stays with the second-teammate review (06 §1) and its open items live in `eval/dataset/REVIEW_NEEDED.md`.
⚠ Scope note: the derivation is deliberately independent of `policy/engine.py` (still a stub). When the engine lands, the two must agree — and the gate is the artifact that will notice if they don't.

**Q-02 — Upstream provider choice** — RESOLVED 2026-08-24, **RE-RESOLVED 2026-08-25 (ADR-018)**. The fallback half is **reopened as Q-10**.
Ruling (current): provider set is classed by provenance, not picked as a single winner — **`measured` = {`groq`, `ollama-local`}**, **`dev` = {`kiro-local`}**; `active_provider: kiro-local` for development. Both Groq ids were verified first-party as *production* models (`llama-3.1-8b-instant` small, `llama-3.3-70b-versatile` frontier). Written to `config/gateway.yaml` per the amended 05 §6.1 schema.
Supersedes the 2026-08-24 ruling (upstream = Anthropic API / `claude-sonnet-4-6`), which is now moot — including its ⚠ note about that id not matching Anthropic's published naming. That concern was well-founded and the same class of failure is now caught at boot rather than by inspection: FR-GW-006's canary refuses a measured-class boot whose token accounting disagrees with `count_tokens` by more than `usage_sanity.max_token_delta`.
⚠ Price provenance remains the weak link, not the ids. The schema half is now fixed — ADR-022 keys prices by concrete model id, so the two-tier cascade is expressible and `[D2-price-table-cannot-express-per-tier-cost]` is CLOSED. The *provenance* half is not, and re-checking live on 2026-08-25 made it worse rather than better: `groq.com/pricing` 308-redirects to a homepage carrying no price content, `console.groq.com/docs/pricing` 404s, `console.groq.com/settings/billing` is authenticated with no public table, and the per-model doc pages contain zero dollar figures. **No first-party Groq price table is reachable at all**, so every figure in `config/gateway.yaml` rests on secondary aggregators plus a stale December-2024 blog post. ADR-022's `source_url`/`retrieved` fields now carry that admission in the config itself rather than in a comment. Consequence for AGENTS.md §7: the 06 §6 cost simulation may publish a **relative** delta (which survives a proportional error in both tiers) but **not an absolute dollar figure** until a first-party table exists.

**Q-11 — Multi-turn case encoding in `eval/dataset/conversation.jsonl`** — RESOLVED 2026-08-25 (MINOR gap, AGENTS.md §6; agent-resolved, obvious low-risk answer).
Why: 06 §2 specifies a case format with a single `text` string, but also specifies a file of "multi-turn sequences" (SC-4 / FR-DET-006). The format has no field for turns, and 06 §2's example shows only `"kind":"output"` without enumerating the legal values.
Ruling: encode turns as `"user: …\nassistant: …"` lines **inside** `text`, and use `kind: "conversation"` — a value borrowed from 04 §1's `stage` vocabulary, where `conversation` is already a documented stage. Chosen over adding a `turns` field because a new field is an undocumented schema change and the prefix convention needs no format edit; chosen over reusing `kind:"output"` because the conversation stage is genuinely distinct and `conv_tracker` is stage-scoped.
Consequence: `kind` now has three observed values (`input`, `output`, `conversation`). If a future validator or loader enumerates them, it must accept all three.
✓ The two related items flagged here as **not** MINOR are now both ruled, and both dataset coverage gaps are closed: `[D4-enriched-label-survival-semantics]` → **ADR-019**, unblocking `OVLP-11…15` (in-band, person-bearing); `[D4-input-stage-pii-edit-unresolvable]` → **ADR-020**, unblocking `PII-048…053` (input-stage, all five categories). See the deviation ledger below.

**Q-09 — YAML 1.1 boolean coercion of `consistency` / `cascade_probe`** — RESOLVED 2026-08-24 (MINOR gap, AGENTS.md §6; agent-resolved, obvious low-risk answer).
Why: PyYAML implements YAML 1.1, where bare `on`/`off`/`yes`/`no` resolve to **booleans**. Both fields are string enums whose members are literally `on`/`off` (04 §3, ADR-013, ADR-014), so the spec's own example — `cascade_probe: off` — loads as `False` and fails validation. Found when all three policies failed to load.
Ruling: the intended vocabulary is unambiguous across three docs, so only the quoting was wrong. Values are now quoted in all three policy files **and in the 04 §3 example** (which is the template people copy). `streaming` is a genuine boolean and stays unquoted. `policy/schema.py` raises a targeted error naming the trap instead of a bare enum mismatch (FR-CFG-001 "precise error").
No behavioural change; no ADR needed.

**Q-03 — Dashboard tech** — RESOLVED 2026-08-24. Ruling: **Streamlit**. ADR-007 flipped Proposed → Accepted; `streamlit` recorded as an optional `dashboard` extra in `pyproject.toml`.

**Q-04 — Tier-2 model picks (injection + toxicity classifiers)** — RESOLVED 2026-08-24 (deferred by decision).
Ruling: **defer the checkpoint choice**; stub the detector interfaces now (`detectors/tier2_classifiers.py`), pick real checkpoints later via the NFR-P-002 latency spike. The interface stub carries `STUB(phase-1-scaffold, Q-04 deferred)`.
⚠ Doc-rot note: the original Q-04 said to record the eventual choice "as ADR-011", but ADR-011 is already the `privacy.person` producer decision. The spike result gets the **next free ADR number**, not ADR-011.
