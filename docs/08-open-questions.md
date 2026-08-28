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
Deadline: before the consistency detector sprint (it needs the 2nd sample) — earlier if the cost plane is demoed. Status: **RESOLVED 2026-08-28** — option (a), on owner evidence.

**Ruling (2026-08-28).** `llama3.2:3b` serves the small tier of `ollama-local`; the assertion the
assumption was gated on **passed** — a manifest grep shows no `remote_host`, so it is local in the
sense ADR-018 requires and the `unmetered` claim holds (its tokens are billed to no one). `frontier`
stays null: exactly one local model is evidenced, and binding both tiers to one id would make the
cascade a no-op while looking configured. The `STUB` markers are removed from `config/gateway.yaml`
and **SL-4** is closed.

⚠ **The evidence is host-specific, and that is recorded rather than smoothed over.** It comes from
the **owner's** machine (Apple Silicon, Ollama **v0.33.0**): a direct probe served real usage counts
and the FR-GW-006 canary passed as measured-class. The **development host** these docs were written
on runs Ollama **v0.31.1** and serves exactly one model — `minimax-m2.7:cloud`, carrying
`remote_host: https://ollama.com:443`, the original SL-4 condition, re-confirmed 2026-08-28. So on
that host the bound id names nothing and a dispatch to this provider fails; `ollama pull llama3.2:3b`
is the whole fix. Neither report is wrong — they describe different hosts — which is why the binding
is recorded with the host it was verified on. Two consequences follow, and both are constraints
rather than caveats: **no test may depend on a live local dispatch** (the config-level assertion is
what `tests/test_gateway_config.py` pins), and **no fallback latency or cost figure from this
provider may be reported from the development host**, since it cannot produce one — the AGENTS.md §7
rule the original assumption stated, still in force for the same reason.

Kept in place rather than relocated to *Resolved*: the housekeeping note further down records
dependents being **stranded** under this very question's heading when it last moved, and this entry
now has more dependents than it had then, not fewer.

Status: **RESOLVED**


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
| `[D3-tier1-pii-recall-below-target]` | **MAJOR** | Step 4 | **CLOSED** — ruled by ADR-026 (disclosed revision), patterns re-derived from named published specs, re-measured **once**: recall **0.8361 → 0.8852**, precision 1.000 both. **NFR-EVAL-001 remains UNMET and the target was not moved.** The residual 7 misses are **7/7 the documented bare-7-digit scope exclusion** (ADR-026 §3), verified programmatically. Closing this deviation closes the *decision*, not the gap — the gap is tracked permanently as **SL-1** below |
| `[D8-numeric-claims-treats-identifiers-as-statistics]` | **MAJOR** | Step 4 | **CLOSED** — ruled by ADR-025: the 04 §2 bare large-digit-run clause was **deleted**, not tuned. Precision **0.2667 → 0.8571** with recall **unchanged at 0.750**, so nothing was traded for the gain. The deletion is asserted positively in `tests/test_numeric_claims.py`, so re-introducing the rule fails the suite |
| `[D2-detector-params-cannot-hold-list-values]` | MINOR | ADR-025 | **CLOSED** — ruled: `detector_params` widened to `dict[str, dict[str, ParamValue]]` where `ParamValue = str\|int\|float\|bool \| list[...]`. pydantic v2 smart mode preserves `1` as int and `True` as bool across the union; validation test added; 04 §3 records it |
| `[D1-citation-marker-per-matches-the-rate-preposition]` | **BLOCKER** | ADR-025 impl | **CLOSED** — ruled by ADR-025 Amendment 1 **before** the single permitted re-measurement, so ADR-026 §5 was not strained. Bare `per ` removed; three attribution forms added (`as per`, determiner, proper-noun). Verified on the corpus pre-measurement: HAL-049/052 no longer suppressed, CLN-062 still correctly suppressed |
| `[D2-nanp-n-constraint-rejects-nothing-as-composed]` | **MAJOR** | ADR-026 impl | **CLOSED** — ruled: keep the composition, correct the description (ADR-026 Amendment 1). v1's `_PHONE` is deliberately retained and shadows both NANP rows, which therefore add **zero recall**; the whole v2 phone gain is E.164 + the spaced-parenthesis variant. Narrowing `_PHONE` would break v2's superset property and orphan the permanent v1 baseline. Precision hardening → **SL-2** |
| `[D2-adr-026-eyj-derivation-is-arithmetically-wrong]` | MINOR | ADR-026 impl | **CLOSED** — correction ratified (the error was the adjudicator's). ADR-026 carries a dated Correction block **preserving the original false claim verbatim** before refuting it with the arithmetic. The test pair asserting the false literal *as false* is retained as the artifact |
| `[D2-report-emits-a-q18-publication-gate-adr-025-lifted]` | **MAJOR** | ADR-026 §5 run | **CLOSED** — ruled by **ADR-026 Amendment 2**: the §5 no-touch rule binds measurement-affecting code, not presentation prose, subject to four conditions. Note corrected; figure identity **PROVEN** and committed as `reports/eval_report_prose_fix.diff`. Logged under *Prose-fix log* below (clause (d)) |
| `[D5-detector-failure-signal-is-unconstructible]` | **MAJOR** | Phase 3 | **CLOSED** — ruled by **ADR-027**, Option B: a detector fault is an **operational event, not a content risk** (no span, no plane, not detector-emitted, not policy-mapped), so the closed 04 §1.1 taxonomy is right to reject it and `Signal` is right to refuse to construct it. 04 §5 rewritten around `DetectorFailureRecord`; `detector_failures_json` added to 05 §3/§4; the §4.3 step-5 stamp now names contributing signal_ids **+ failure_record_ids**; review-queue `escalation_cause` added to 05 §2; 06 §5 reads the new field. Resolution semantics unchanged — `fail_closed` is an **ESCALATE floor**, never an override, so a genuine content BLOCK still wins |
| `[D1-usage-canary-has-no-independent-count-on-the-measured-class]` | **BLOCKER** | Phase 4 | **CLOSED** — ruled by **ADR-028**: the reference count is **repo-local** (`method: local_estimate`, estimator named in the result), never a provider endpoint, because comparing `count_tokens` against `usage.prompt_tokens` put both sides of the check in the hands of the party being audited. Ratio bound + absolute floor, ANDed (`max_ratio: 2.0`, `min_delta_floor: 50`); consequences unchanged (measured fails boot, dev warns). Scope stated in 01/05: **gross** corruption, not a fine-grained accounting audit. **The filed recommendation (option B) was NOT adopted** — it compared two provider-reported counts, so the ruling's rationale defeats it too; recorded in the ADR rather than read as convergence |
| `[D5-adr-027-stamp-has-no-column-in-the-05-3-ddl]` | **BLOCKER** | Phase 4 | **CLOSED** — ruled by **ADR-027 Amendment 1**, Option A: two `TEXT NOT NULL DEFAULT '[]'` columns added to the 05 §3 DDL. The non-derivability analysis is ratified into the amendment — `detector_failures_json` carries fail_open records, the escalate floor leaves a content BLOCK standing, and `contributing_signal_ids` is a strict subset of `signals_json` by design — so the stamp is **stored, not derived**; `escalation_cause` derives from the stored columns. Round-trip verified (21 columns, `[]` not NULL when empty); 10 tests added, all 6 mutants killed including the one reproducing this defect. No migration needed: no `.db` existed |
| `[D2-groq-tier-ids-shut-down-no-production-qwen-exists]` | **MAJOR** | Phase 5 | **CLOSED** — ruled by **ADR-029**, Option B (`openai/gpt-oss-20b` / `openai/gpt-oss-120b`). Both previously-bound llama ids were shut down 2026-08-16; probed live 2026-08-27, both return **HTTP 404 `model_not_found`** on this repo's key, so it is not on the exempt committed-spend contract and the rebinding is forced. **The filed recommendation (option A, `qwen/qwen3.6-27b` frontier) was OVERRULED** — that pair's frontier tier is smaller, less capable and 5x costlier than the one chosen, so it existed only to preserve a test ratio, and a number from an economically irrational config is harness-fitting by construction. The probe independently justified the overrule: qwen emits its `<think>` trace into the response body, which would have pushed reasoning scaffolding through the sentence buffer into every output-lane detector. **ADR-009 amended in the same commit** — the cascade premise is now ratio-parametric (2.0x shipped, blend-independent) and the `>5x` assertion was amended through the front door, not loosened. `reports/` and `demo/` grepped: **no committed figure referenced either dead id**, so no published number moved |
| `[D1-tier2-budgets-cannot-coexist-with-nfr-p-001]` | **MAJOR** | Phase 5 | **CLOSED** — ruled by **ADR-030**, the Option A direction as a **front-door respecification**. NFR-P-001 is re-scoped onto the **user-perceived hold** (input-lane hold, and each per-sentence hold), with targets **derived from the 04 §2 budgets** rather than chosen to fit; the per-request sum keeps being published as `total_attributable_overhead_ms` with no target, and `added_time_to_last_byte_ms` is added as a measured untargeted row. Filed from a **projection**, never a measurement, and ruled **before any Tier-2 figure exists** — the anti-laundering record is verbatim in ADR-030, and ADR-026 §5's bar on moving a *missed* target is untouched (SL-1 stays unmet and unmoved). The derivation surfaced three gaps of its own rather than hiding them: **M-18**, **M-19**, **M-20** |
| `[D3-tier2-injection-budget-cannot-hold-on-unbounded-input]` | **MAJOR** | Phase 5 | **CLOSED 2026-08-28** — ruled by **ADR-032**. Prefix truncation (this report's own recommendation A) was **OVERRULED**: a documented "we score the first N tokens" is an evasion recipe, and the interception guarantee is the product. Full coverage via strided windows (104 tokens / overlap 26 / step 76, MAX over windows) instead — which also closes the **512-token blind spot** this report found, the more serious half of it: an injection at token 3000 was previously never scored at all. The budget question the report raised is answered by the same ADR: NFR-P-002's <25 ms is scoped to single-window inputs, where it is measured to hold at 13.01 ms P99 |
| `[D3-full-coverage-windows-cost-600ms-at-the-policy-bound]` | **MAJOR** | Phase 5 | **CLOSED 2026-08-28** — ruled by **ADR-032**; the measured cost is **ACCEPTED and PUBLISHED**, and full coverage stands. Recorded rationale: cost scales with window count, window count scales with input length, so the guard's cost concentrates on exactly the long inputs where pad-then-inject attacks live — a typical single-window prompt pays 11.30 ms P50 / 13.01 ms P99. Pre-dispatch position is non-negotiable (optimistic dispatch would deliver the payload upstream, which is the event the gate exists to prevent). Batch size bound to **4**, not the nominal minimum 2: 599.20 vs 602.66 ms differ by 0.6%, inside this harness's own run-to-run spread, so the minimum over-fits one run. This report's cross-validation note is **corrected** in ADR-032 — 11.30 ms is the *faster* figure, not the conservative one, and the 11.30-vs-14.27 gap is ~26% run-to-run variance, not a synthetic-vs-real content effect (both harnesses time `sess.run` only, and a fixed 104-token tensor costs the same FLOPs whatever fills it) |

| `[D1-not-run-vocabulary-cannot-say-dependency-absent]` | **MAJOR** | Phase 5 | **OPEN** — filed 2026-08-28 while landing `tier2_toxicity` (Phase 5 item 2), **before any detector code was written**. 05 §4 fixes `not_run[].reason` to a closed vocabulary whose single member `not_implemented` it defines as *"the detector has no live implementation in this phase"*, and `_check_detectors` enforces it — a probe confirms `dependency_unavailable` is refused outright. The moment a model-backed detector gains an implementation, a host without the `[ml]` extra has **no truthful value to record**: the detector exists, so `not_implemented` is a false statement, and it is the only member admitted. That host is not hypothetical — `.github/workflows/ci.yml` installs `.[dev]` only and says the model stack is *deliberately* absent, so CI is the case. Two further consequences: a binding import at module scope would break the gateway import there outright, and because 05 §4 states that a not-run entry is **not** a `DetectorFailureRecord` ("no attempt was made, so there is no fault"), `finance_advisor`'s `tier2: fail_closed` is **silently not honoured** on such a host — the request passes with a coverage note. Generic, not toxicity-specific: `rag_grounding` (sentence-transformers) and `entity_enricher` (spaCy) reach it identically, which is why it wants one ruling rather than three ad-hoc choices. **Filed D1 but carrying a D7 edge, stated so the ruling can weigh it:** "a fail-closed behaviour not honoured" is D7's own language. It is filed MAJOR rather than BLOCKER because the *behaviour* is not a regression — a detector that is not live does not honour `fail_closed` today either — so what breaks is the **record's truthfulness**, not a protection that currently works. If the ruling reads the silent non-enforcement as the primary harm rather than the record, this is a BLOCKER and the severity should be raised on that basis, not on mine |
| `[D1-added-time-to-last-byte-has-no-server-side-vantage]` | **MAJOR** | Phase 5 | **OPEN** — filed 2026-08-28 while closing out **M-20**'s remainder (Phase 5 item 10), **before any code was written**. 06 §4 defines `added_time_to_last_byte_ms` as *"client-observed last-byte time minus the same request's upstream duration"*, and 05 §3 puts it in `latency_json` — a column the **gateway** writes. The gateway has no such vantage on either path: the buffered write at `app.py:586` precedes `return JSONResponse(...)` at `:632` (an ordering **M-13** established deliberately, so "audit later" reopens a closed gap), and the streaming write at `:875` runs inside the generator after the final `yield`, where a completed ASGI `send()` means *handed to the transport*, not received. There is no second phase to carry a post-delivery figure — the table is insert-only (no `UPDATE audit_records` in `controlplane/`) and `record_status` is a crash marker. Meanwhile `eval/bench_latency.py:237` already computes 06 §4's formula client-side as `reference_delta_ms`, but publishes it as a contaminated **upper bound** (`TestClient` ASGI cost), "never the headline number" — so the two cannot be equated by a rename | Filed **D1**, not D3: nothing is targeted and nothing measured breached: the documented design is not constructible from where the doc sites it. MAJOR because the row is untargeted, so NFR-P-001 keeps its verdict and no other Phase-5 item waits on it; the §7 edge — emitting a handoff delta under a name that claims a client vantage — would justify rounding up |
**Open: two.** **22** deviations filed; **20** ruled and closed. Both remaining are Phase-5 filings, both MAJOR rather than BLOCKER, and neither touches the checkpoint decision, a fail-safe, or the demo path. The two that shared a subject — how much input `tier2_injection` may be asked to scan — **closed together** on 2026-08-28 under **ADR-032**, which is the shape that subject always had: one ruling reserved a branch for a measurement, the measurement fired it, and the second ruling accepted the cost rather than reducing coverage to hide it. What remains is what the audit record may truthfully say when a detector's dependency is absent, and a `latency_json` row the gateway has no vantage from which to measure. The nineteenth (`[D3-tier2-injection-budget-cannot-hold-on-unbounded-input]`, filed from the ADR-031 latency spike) is the first since Step 4 to leave this count above zero, and the first filed from a **measurement of a model this repo intends to ship** rather than of our own code; its ruling overruled prefix truncation in favour of full-coverage strided windows. The twentieth (`[D3-full-coverage-windows-cost-600ms-at-the-policy-bound]`) was then filed **by that ruling's own item 5**, which required a stop-and-report if full coverage measured in the >500 ms class. It did, at both thread settings. Worth stating plainly because it is unusual: the second deviation is not a re-litigation of the first, it is the branch the first ruling explicitly reserved for this measurement. The twenty-first (`[D1-not-run-vocabulary-cannot-say-dependency-absent]`) is a different subject and a different kind: it is about the **audit record**, not a budget, and it was found by reading the coverage contract before writing the detector the phase's next item asks for — the cheapest place to find it, since the alternative was a shipped record that says `not_implemented` about code that exists. The **twenty-second** (`[D1-added-time-to-last-byte-has-no-server-side-vantage]`) was found the same way, one item later: by reading 06 §4's definition against the write path before implementing it, rather than by shipping a row whose name claims a vantage the writer does not have. The eighteenth (`[D1-tier2-budgets-cannot-coexist-with-nfr-p-001]`, closed by **ADR-030**) is the only one filed from a *projection* rather than from a measurement or a doc reading: it reported that two documents cannot both hold in a **future** state, which is why it was a D1 and not the D3 its subject matter might suggest — and why it could be ruled as a specification decision rather than as a target moved after a miss. Its own derivation then logged **M-18/M-19/M-20**, so closing it left three gaps *stated* rather than a clean slate. The Phase-5 filing
(`[D2-groq-tier-ids-shut-down-no-production-qwen-exists]`) is the seventeenth, closed by **ADR-029**:
an external event, not a defect in our specs — Groq retired both bound model ids — and the one
filing so far whose *recommendation was overruled on economic-rationality grounds* rather than on a
doc reading. The two Phase-4 BLOCKERs closed
together: `[D5-adr-027-stamp-has-no-column-in-the-05-3-ddl]` by **ADR-027 Amendment 1** and
`[D1-usage-canary-has-no-independent-count-on-the-measured-class]` by **ADR-028**. Both were
defects in *settled contracts* rather than in code — the stamp one a gap in ADR-027's own audit
representation, found while wiring the write path that ADR specified; the canary one a
requirement whose independent reference did not exist, found by probing for it. Per the note
below, a low `Open:` count means **little undecided**, not little missing: **four** Standing
Limitations remain (SL-4 closed 2026-08-28 — five filed), and closing a deviation never closes the
gap it documented.

The **eight** filed from Step 4 up to that closure account as: **two** measured-accuracy findings
(D3, D8), **four** found while implementing the ADRs (`detector_params`, the `per` citation
marker, the NANP constraint, the `eyJ` derivation), **one** report-prose gate found after the
re-measurement, and **D5**. The **two** Phase-4 filings are the **ninth and tenth** from Step 4
onward and are **both now closed** — 10 closed + 0 open = 10, and 6 pre-Step-4 closures bring the
total to 16. The Phase-5 Groq rebinding is the **eleventh** from Step 4 onward, and the tier2
budget projection the **twelfth**. The ADR-031 spike filing is the **thirteenth** and the
measurement its ruling ordered is the **fourteenth**, and the coverage-vocabulary gap found
while landing `tier2_toxicity` is the **fifteenth**, and the last-byte vantage gap found while
closing out M-20 the **sixteenth**; all four are still open. That subtotal is **scoped to
Step-4-onward filings** — **14 closed + 2 open = 16** — and the 6 pre-Step-4 filings, all
closed, bring the whole table to **20 closed + 2 open = 22**. Both are stated because the
scoped figure alone, sitting a sentence after an unscoped "22 filed", reads as arithmetic
that cannot balance — it was reported that way once. The scope was the missing word, not the
sum. `tests/test_deviation_ledger.py` now parses this table and fails if either identity
does not balance, if the widest stated one disagrees with the rows, or if the `Open:`
headline drifts from the OPEN count — so a non-balancing count cannot ship again.
**Three of those eight were found by writing the ADR-026 spec-derived tests**, which is the
outcome that discipline exists to produce: tests authored from the specifications rather than
from the fixtures caught two defects in the ruled specs themselves and one in the implementer's
reading of them, *before* any number was computed. D5 was found the same way — by implementing
04 §5 literally and discovering the object it describes cannot exist.

⚠ **Open deviations and open questions are separate counts.** Five *questions* remain OPEN
above — **Q-01, Q-05, Q-06, Q-07, Q-08** (Q-10 **resolved 2026-08-28**) — while **two
deviations** are open, and the two
registers are deliberately kept apart: a deviation is a contradiction awaiting a ruling, a
question is a decision not yet needed. Collapsing them into one "open" number would hide which
kind of answer is owed. (The *gaps* left behind by closures are the
separate register below.)

**A closed deviation can still leave a gap.** "Ruled" means nothing is undecided, not that
nothing is missing: two of the closures above leave real gaps behind, and a decided gap is still a
gap. Every such item is carried permanently in the **Standing Limitations** register immediately
below, so the two numbers can never drift apart: a reader who reaches the end of the deviation
ledger — whatever it happens to count — sees the standing limitations in the same breath.

Also tracked as questions rather than deviations: **Q-10** (the local model — **resolved
2026-08-28**, **SL-4** closed with it, though the binding is verified on the owner's host only) and
the Groq price-provenance caveat under
**Q-02**, which constrains what the cost simulation may publish rather than blocking it (**SL-3** —
**downgraded 2026-08-27 by ADR-029**: first-party prices now exist for the two bound ids, so the
absolute-dollar gate is lifted for them).
**Q-18's publication gate is lifted** — ADR-025 made the citation-marker list normative in
04 §2.4.2, so a `numeric_claims` figure may now be published if labelled v1 or v2 (06 §3.2).

### MINOR resolutions (logged, not escalated)

Per the lightened protocol (AGENTS.md §11.1): a gap with one obvious low-risk answer is resolved
in place and logged here, so the open-deviation count above stays an *honest* count rather than
merely a low one. Sectioned by phase, because the lightened protocol is itself phase-scoped.

**Phase 3**

| # | Gap | Resolution | Why it is not a deviation |
|---|---|---|---|
| M-1 | 04 §3 defines `fail_mode` per detector **class** (`tier1`/`tier2`/`performance`/`cost`), but no doc maps each 04 §2 detector *to* its class, so `resolve_failure` had nothing to look up | `DETECTOR_FAIL_CLASS` in `controlplane/policy/engine.py`, transcribed from the 04 §2 registry rows. `entity_enricher` is deliberately **absent** (04 §2.2 makes enrichment failure skip-and-log, never blocking) and `fail_class_for()` **raises** on an unmapped detector rather than defaulting | The mapping is mechanical from the registry — every detector's class is unambiguous from its own §2 row. Refusing to invent a mode for an unmapped name is what keeps a future detector from silently inheriting `fail_open`. Pinned by `test_fail_class_covers_every_registry_detector_except_the_enricher` |
| M-2 | 04 §6 renders redactions as `[REDACTED:<category>]` (bare category, e.g. `email`) while 05 §4 records `category: "pii.ssn"` (full label) in `actions_json` | `AppliedEdit` carries **both**: `category` (bare, for the 04 §6 marker and the 07 beat-4 rendering) and `label` (full, for the 05 §4 audit field). Neither doc bends | Two consumers legitimately want different granularity; the only wrong answer was picking one and making the other doc inaccurate. Neither field ever holds the removed value (NFR-SEC-001), pinned by `test_applied_edit_records_category_and_span_but_never_the_value` |

**Phase 4** — M-3/M-4 arise from ADR-027 and are questions of *where* a ruled field lives,
not whether it exists. M-5/M-6 are gateway-surface gaps in 05 §1, found while implementing
ingress; M-7 is a 05 §6.1 gap found while implementing upstream dispatch, and M-8 a
05 §3-vs-§5 tension found while wiring per-detector timing. M-9 is the only one that is
not a doc gap at all — no doc is unclear, two code copies of a ruled list had drifted —
and it is logged here because the lightened protocol asks for every in-place resolution to
be written down, not only the ones that turned on a reading of a doc. M-10 is
downstream of the Phase-5 deferral recorded below: deferring two detectors made
*absence of coverage* a fact the audit record had no way to state. M-11 is the only row
here that resolves a **reading** of two docs rather than a gap in one, and was called out
in the phase report for that reason; it was **ratified** on 2026-08-27 and 04 §2 now carries
the rule explicitly. M-13 is the only row here that arose from a **defect found in flight**
rather than from reading a doc: it is logged as a resolution because the fix is a contract
addition (a new 05 §3 column), and the incident that motivated it is named in the row so the
guarantee is not mistaken for a precaution against something hypothetical.

| # | Gap | Resolution | Why it is not a deviation |
|---|---|---|---|
| M-3 | ADR-027 names `fail_mode_applied` as part of the `DetectorFailureRecord` shape, but the mode applied is unknowable at fault time — no policy has been consulted when the gateway synthesizes the record | The field is emitted by **`FailureOutcome.audit_entry()`**, at resolution, so the documented six-key shape (`failure_id, detector, error_class, stage, fail_mode_applied, ts`) exists at the **audit boundary** where 05 §3/§4 consumes it. `DetectorFailureRecord` carries the five facts known at fault time | Placement, not content: every ruled key reaches `detector_failures_json` exactly as ADR-027 specifies. Storing it on the record could only have held a placeholder until resolution overwrote it — a field whose value is a lie for part of its life. Pinned by `test_adr027_audit_entry_has_the_documented_shape_and_no_content` |
| M-4 | `failure_id`/`ts` are minted by the record, yet FR-POL-001 requires `evaluate()` to be a pure function of (signals, policy) with no clock and no randomness | Minted **at construction by the gateway**, exactly as `Signal.signal_id` already is (`default_factory`), and never read by the verdict computation | Determinism is a property of `evaluate()`, not of its inputs. Pinned by `test_adr027_record_mints_identity_without_making_the_engine_impure`, which asserts the guarantee that matters — two records for the same fault differ in id and yield identical verdicts — rather than merely that the fields exist |
| M-5 | 05 §1.1/§6 name `config/keys.yaml` normatively as the api_key→use_case map, but the file is **gitignored** (§6: "demo keys only") and so absent from a fresh clone. No doc says what its absence means | An absent file is an **empty map**, not a boot failure: the `X-ControlPlane-Use-Case` header is §1.1's primary path (marked `yes*`), and refusing to boot without a gitignored secrets file would block the documented dev path. A **malformed** file is still an error. `config/keys.yaml.example` added, mirroring the tracked `.env.example` convention | The doc specifies what the file contains, never that it must exist. The two wrong answers were boot-refusal (breaks a fresh clone) and treating a broken file as empty (every key-authed request would then look like a missing header). Pinned by `test_absent_keys_file_is_an_empty_map_not_a_failure` and `test_nfr_sec_002_a_malformed_key_map_never_echoes_the_key` |
| M-6 | 05 §1.1 says body `stream` "must be compatible with policy `streaming` flag, else `ERR-CFG-002`". "Compatible" admits a reading in which a client may *downgrade* a streaming pipeline to non-streaming — strictly safer buffering, so plausibly allowed | **Strict equality**: ERR-CFG-002 fires in *both* directions. A non-boolean flag gets its own message rather than being coerced (`bool("yes")` is True, which would emit "asked for stream=true" against "configured streaming=true" — an error claiming a value conflicts with itself) | The policy owns the interception mode: ADR-014 ties `consistency: on` to `streaming: false`, so a client-chosen mode would run a pipeline the policy does not describe while `stage_summary` recorded the configured one. Pinned by `test_err_cfg_002_fires_in_both_directions` |
| M-7 | 05 §6.1 types `base_url` as a bare `<url>` and states no rule for how a request path joins it. The two shipped providers disagree: `kiro-local` carries no version segment (`http://localhost:8000`), `groq` already ends in one (`https://api.groq.com/openai/v1`) | `upstream_url()` inserts `/v1` **iff** `base_url` does not already end in it. Resolved **empirically**, not by convention: both providers were probed keyless — no credential sent, so 401/403 means the path exists and is auth-gated while 404 means it is absent — with a `GET /v1/models` → 401 control row establishing that a 404 is a real absence rather than a network artefact. Probe table recorded in the `upstream_url` docstring with its date | Neither a naive join nor an unconditional `/v1` serves both providers, so *some* rule was required and the doc states none — a gap, not a contradiction. Deciding it by convention would have been a guess about two live endpoints when asking them was cheap. Pinned by `test_the_v1_prefix_is_inserted_only_when_missing`, parametrized over both shipped providers so a config change that moves the segment fails |
| M-8 | 05 §3 annotates `latency_json` as "per-**detector** ms", but 05 §5 records the same keys as a **fixed span vocabulary** — and that vocabulary has no entry for `numeric_claims`, one of 04 §2's seven detectors (ADR-025). `check_latency_keys` enforces the closed list at the write path, so a `numeric_claims` key is rejected. The detector appears in neither 05 nor 06 | 05 §5 is authoritative on the key vocabulary: it is the more specific statement and is explicitly labelled fixed. **Per-detector timing goes to `cp_detector_latency_ms{detector}`** — the detector-labelled channel 05 §5 already defines for exactly this, open by construction and the metric NFR-P-002 is measured by — while `latency_json` carries span keys only. `numeric_claims` therefore has no `latency_json` entry | Neither contract bends and NFR-P-002 stays measurable per detector. The two wrong answers were **inventing a span name** (`cp.out.numeric` is an undocumented addition to a vocabulary 05 §5 calls fixed — AGENTS.md §4 forbids it) and **folding it into `cp.out.grounding`** (a different detector on a different premise; the span would then misreport whose time it was). Spans are named for pipeline *stages* and already group detectors — `cp.out.tier1` covers both Tier-1 detectors — so a detector without its own span is the vocabulary working as designed, which `check_latency_keys`'s own docstring anticipates: "a per-detector span that is absent is normal" |
| M-9 | ADR-015 rules the span-less promotion, but no doc says **where the list of span-less labels lives**. `eval/policy_matrix` and `eval/validate_dataset` each reproduce the promotion rather than calling the engine, and each had grown its own copy — which had already diverged: the matrix's set held `cost.request_too_large`, the validator's did not, so the matrix applied the promotion where the validator skipped it | **One definition**: `SPAN_LESS_LABELS` in `controlplane/policy/schema.py`, imported by both consumers. The validator gains `cost.request_too_large`, which is genuinely span-less — it scores a whole request and has no extent to point at, so the validator was the side that was wrong. Guarded by `tests/test_span_less_single_source.py`, which walks the `controlplane/` and `eval/` ASTs for a third copy and asserts **identity** (`is`), not equality, on both imports | Nothing in any doc is contradicted or unclear: the promotion is ruled and both copies were trying to obey it. The defect was duplication, and the honest fix is structural — an `==` assertion would have passed for an equal-but-separate third copy, and a grep for the name would have missed this divergence entirely, since the two sets had **different names** (`_SPAN_LESS` and `SPAN_LESS_LABELS`). Freeze-adjacent and therefore re-verified rather than assumed: 280/280 unchanged, digest `6a3ecbbe75fd020b…` still matching, so a validator edit moved no number |
| M-10 | The Phase-5 amendment above creates a case no doc had a field for: `finance_advisor` sets `consistency: "on"`, but `fast_consistency` has no implementation this phase. A detector that runs and finds nothing emits no `Signal`, so a short `signals_json` cannot distinguish **checked-and-clean** from **never-checked** — and 05 §3/§4 recorded only signals, failures and the step-5 stamp, none of which answers *what was attempted* | **`detectors_json TEXT NOT NULL DEFAULT '{}'`** in the 05 §3 DDL, rendered as `detectors` in the §4 canonical view: `{ran: [name], not_run: [{detector, reason}]}`. `reason` is a fixed vocabulary with one member, `not_implemented`. Every string is validated against a closed set — detector names against `BUDGETS_MS` (the 04 §2 registry), reasons against `NOT_RUN_REASONS` — and a detector appearing in **both** lists is refused, since that contradiction is unresolvable by any reader. `{}` means *coverage not recorded* and stays distinct from `{"ran":[],"not_run":[]}` (*nothing ran, nothing expected*), the same `[]`-vs-NULL distinction as Amendment 1 | Nothing in any doc is contradicted: 05 had no coverage field because until this phase every detector in the registry was presumed present, so the question never arose. The field is **not** a `DetectorFailureRecord` and must not be read as one — a failure means *ran and broke* and carries `fail_mode_applied` because a policy resolved it, whereas a not-run entry means no attempt was made, so there is no fault, no fail mode, and nothing to resolve (ADR-027 stands unchanged). Deliberately outside `CONTENT_COLUMNS`: a value constrained to eleven known names cannot be a raw value, so the shape tripwire would add false positives and no safety. **Also closes a hole in the older guard** — the Amendment-1 differential named its two columns as literals, so when 05 §3 gained this column and `db.py` had not, the whole suite stayed green; the replacement compares the full column list in both directions and by order, and was mutation-probed on all three |
| M-11 | 04 §2's Stage column names `output_full` for **`fast_consistency` only**; every other output-lane row reads `output_sentence`. Read as an exhaustive whitelist, a non-streaming pipeline — which is the whole of UC-3 under ADR-014 — would run `fast_consistency` alone and **never scan a response for PII at all**, while 02 §4's non-streaming path says in terms: "buffer fully, run **all** checks incl. consistency, single verdict" | `pipeline.lane_members()` **composes** the full-response lane: the `output_sentence` rows **plus** `fast_consistency`. The Stage column is read as naming which *text* a detector consumes, not which delivery mode may consume it — `tier1_pii` over a whole response is the same regex pass over a longer string | Not a doc-vs-doc conflict needing the §3 precedence rule, because the strict reading is not a competing reading but an incoherent one: it contradicts 02 §4 in terms and would silently remove PII interception from the highest-stakes pipeline, which no requirement permits and no ADR contemplates. **Two pieces of already-ruled code settle it**: `review.mask_pii` runs `tier1_pii` at `OUTPUT_FULL` (05 §3's masking rule depends on it), and `Signal._check_span_stage_coherence` refuses a span only at `conversation` — so the schema, the one place a stage ban would be enforceable, does not ban this. Flagged in the phase report rather than buried: it is the one resolution this phase that turns on a reading of two docs rather than filling a gap, so it is the one most worth a human overruling if the strict reading was intended. **RATIFIED 2026-08-27**: the composed reading is correct and the strict reading is wrong — it would leave UC-3 unscanned for PII, inverting the risk gradient. The Stage column is per-detector native granularity, not a lane whitelist. 04 §2 now states the rule in prose rather than leaving it to be inferred |
| M-12 | 05 §1.1 fixes two renderings that a **streaming** response cannot produce: ESCALATE as **HTTP 202** with a `review_id`, and an edited response carrying the header `X-ControlPlane-Actions: edit`. Both are committed to the wire before the first sentence is ever checked — a status line and headers precede the body — so on the streaming path neither is reachable, while 04 §4.4 separately specifies terminate-and-notify for a mid-stream escalation | Read as **mode-specific rather than contradictory**: 05 §1.1's 202-and-header renderings govern the non-streaming path, where the verdict is reached before any byte is sent, and 04 §4.4 governs the streaming path. The streaming path carries the same two facts in its **final SSE frame's `controlplane` block** (`{verdict, review_id}`), so a client receives the `review_id` either way and nothing 05 §1.1 promises is actually withheld. **Narrowed 2026-08-28 (owner live-test finding).** The header half of this holds only for *output* edits, which is all the original reasoning covered: an **input-stage** redaction (ADR-020) is decided *before* dispatch, so it is known before the streaming response's status line exists, and the header is emitted there. Withholding it would have made the header unreachable in practice rather than mode-specific — `support_bot` is the only shipped policy mapping `pii.*` to `edit`, and it is `streaming: true`, so every reachable input EDIT took the one path that never set it. The 202 half is unchanged: an ESCALATE verdict is not available pre-dispatch on this path | Not a doc-vs-doc conflict: 04 §4.4 is the *more specific* statement about streaming and 05 §1.1 never claims its renderings are mode-independent — it describes one response shape at a time. The alternative readings are both worse and both testable as such: **buffering a streaming response** to keep the 202 available would delete FR-GW-002's release-as-you-go property and silently turn UC-1 into UC-3, and **omitting the review_id** from the stream would leave a user notified of a quarantine they cannot reference. `X-ControlPlane-Request-Id` is unaffected and present on both paths, since it is known at ingress |
| M-13 | **A request that released content could be delivered with no audit record at all.** The streaming handler yields checked sentences and writes its record *after* the last frame, but caught only `GatewayError` — so any other exception in between propagated past the write. Not hypothetical: `note_pii_intercepts` read `AppliedEdit.labels` where the field is `label`, and the resulting `AttributeError` fired mid-stream on a request whose sentences had already reached the client. ADR-002 forbids recalling released text, so the response could not be withdrawn and nothing recorded that it happened — the exact combination FR-AUD-001 exists to exclude. Client disconnect is the same hole reached by another route | Three parts. (a) **Crash-safe write path**: the streaming generator's release-and-audit region runs under `try/finally`, which covers all three ways a generator ends — a raise, a return, and the `GeneratorExit`/`CancelledError` of a disconnect. (b) **Partial-record marker**: `record_status TEXT NOT NULL DEFAULT 'complete' CHECK(record_status IN ('complete','partial'))` in the 05 §3 DDL, rendered in the §4 view. A **column** and not a JSON leaf, because every aggregate over this table must be able to exclude partials in its WHERE clause — a marker inside `actions_json` would let a crashed request's timings into a published number (AGENTS.md §7). (c) **Tests**: six, driving the ASGI app directly rather than through `TestClient`, which surfaces a response only once its body is consumed and so cannot establish *when* content left the gateway relative to the crash | Nothing in any doc is contradicted: 05 §3 says one row per request and never contemplated a handler dying part-way, so the gap was unstated rather than mis-stated. A partial row carries **real** measurements and is excluded by its status rather than by nulled fields — blanking them would make a crashed request look like a clean one that measured nothing. The rescue is **synchronous throughout**, because a `finally` reached by cancellation cannot reliably `await`: so the partial record is written and the review row is not, which is the right way round — a review item is recoverable from an audit record, an audit record is recoverable from nothing. Two boundaries stated rather than left to be found: a crash in `handle_completion` **before** the generator exists (ingress, input lane) leaves no record, which is within the guarantee since nothing was released; and a crash between minting a `review_id` and the review INSERT leaves an audit row naming a review item that does not exist, which is the honest record of what happened |
| M-14 | ADR-028 rules the FR-GW-006 canary's consequence by **upstream class** — `measured` fails boot, `dev` warns and continues — but both branches presuppose that the check *ran*. `run_canary` deliberately propagates `UpstreamError` so that "the provider is down" is never reported as "the provider miscounts", which leaves the startup hook holding a third outcome no doc names: the invariant was neither satisfied nor violated, because it could not be evaluated. A hook catching nothing would refuse boot through any provider outage, citing an invariant it never reached; a hook catching and ignoring would boot as though the check had passed | **Three states on `Gateway`, not two.** `canary` holds a `CanaryResult` when the check ran, `canary_error` names why it could not, and both `None` means it never ran (the knob is off, or nothing started the app). An unreachable provider warns under a **distinct** category — `CanaryUnavailableWarning`, separate from `UsageSanityWarning`, which means ran-and-failed on dev-class — and boots. `UsageSanityError` still propagates and refuses boot. Anything other than those two exceptions is left to propagate: swallowing it would hide a broken canary behind a clean boot log, which is the same failure in a quieter form. The hook lives in `lifespan` (FastAPI 0.115.6 deprecates `on_event`), so it fires under `with TestClient(app)` and not under a bare call — which is why the 872 pre-existing tests, whose stub reports a count that would *fail* the canary, were unaffected. **No `cp_*` metric was added**: none of the 13 in 05 §5 covers the canary, and inventing one is a contract change this wiring does not earn | Fills a gap rather than contradicting one. ADR-028 states the consequence of a *verdict* and is silent on the absence of one, and that silence is precisely what a boot hook must resolve. The shape is `canary.py`'s own rule — "a canary that always passes because it cannot run is worse than an absent one" — applied at the call site, and it is the same distinction M-10 and ADR-027 Amendment 1 already ruled: "verified" and "never checked" must not collapse into one value. Pinned by `test_an_unreachable_provider_is_recorded_as_unchecked_not_passed`, `test_a_measured_class_failure_refuses_boot` and `test_a_bare_testclient_does_not_run_the_canary` |
| M-15 | ADR-029's rebinding leaves the FR-GW-006 canary passing on the new measured-class pair with only **~7 tokens of margin**, and no doc states whether that is acceptable. At the shipped prompt (estimate 64) both gpt-oss sizes report `prompt_tokens: 121` — **1.89x** against `max_ratio: 2.0`, band [32, 128] — and the delta (57) already clears `min_delta_floor: 50`, so the ANDed condition rests entirely on the band leg | **Logged, no knob touched.** Measured across three prompt lengths (30 / 253 / 761 chars) the cause decomposes cleanly and is **not** the ADR-018 pathology: gpt-oss tokenizes this prose at ~5.1 chars/token where the estimator assumes 4.0, plus ~**72 tokens** of fixed chat-template overhead (qwen: ~11); residual under 1 token at every length. That is real scaffolding, correctly reported — an additive offset like ADR-018's, but two orders of magnitude smaller and *legitimate*. Recorded in ADR-029's trade-offs with the measurements | Nothing is failing, so there is nothing to contradict — and **widening `max_ratio` during a rebinding to buy margin is precisely the AGENTS.md §5.4 move**, since it would weaken the invariant to accommodate the provider it is meant to audit. ADR-028's rationale assumed "tokenizer variance well under 2x", which a 72-token fixed preamble against a 64-token estimate is not, so the honest options are a longer canary prompt (raising the estimate and shrinking the ratio) or an explicit template-overhead allowance — **both are ADR-028 amendments and neither is mine to make**. Logged here so the canary step finds it stated rather than rediscovers it as a boot failure |
| M-16 | 06 §5 and 07 beat 7 both specify the fault-injection demonstration on **`tier2`** ("assert UC-1 tier2 fails open"), and neither `tier2` detector is implemented — so a tier2 fault cannot be injected at all: there is nothing to monkeypatch. `cost` is in the same state. Left alone, SC-3 would be a P1 success criterion with no harness behind it, and 07 beat 7 would rehearse a fault the gateway cannot produce | **The requirement is verified on `performance` instead, and the report says so in its own scope section.** `numeric_claims` is live and its 04 §2 class is `performance`, which the shipped policies configure with the *identical* two-sided asymmetry `tier2` has (`fail_open` on UC-1/UC-2, `fail_closed` on UC-3) — so the contrast beat 7 exists to show is reproduced exactly. FR-POL-006 is stated per detector **class**, not per detector, so the requirement's own unit is satisfied. `eval/fault_injection.py` derives its coverage table from `DETECTOR_FAIL_CLASS ∩ pipeline.LIVE` rather than listing it, prints the unexercisable classes with their configured modes, and is pinned by `test_tier2_is_not_yet_injectable` — the OVLP-01 tripwire pattern ratified 2026-08-27 for deferred coverage. That test fails the moment a tier2 detector lands, forcing 07 beat 7 and the scope note back into review | Not a contradiction of any doc: 06 §5 states the eventual target and this defers one *instance* of it while satisfying the requirement it serves. The alternative readings are both worse and worth naming. Asserting tier2 anyway would need a fake tier2 detector existing only to break — a harness testing its own mock, which is the mocked-measurement shape AGENTS.md §5.4 forbids. Skipping SC-3 until Phase 5 would leave a P1 criterion unmeasured while the mechanism under it is fully working and demonstrably policy-driven. The substitution is visible in three places (this row, the report's scope section, the tripwire test), so it cannot quietly become permanent — which is the whole condition on which deferring is honest rather than convenient |
| M-17 | AGENTS.md §10 documented the gateway as `uvicorn controlplane.gateway.app:app --reload`, but `app.py` exposes **only** the `create_app()` factory — no module-level `app` — so the documented command cannot start the gateway at all (`Error loading ASGI app. Attribute "app" not found`). No doc states which of the two is wrong | **The command was corrected, not the code.** §10 is now `uvicorn --factory controlplane.gateway.app:create_app --reload`, verified by booting it and probing `/admin/policies` (200) and `/metrics`, with and without `--reload`. The entry also now warns off **port 8000**: `active_provider: kiro-local` has `base_url: http://localhost:8000`, so serving there makes the gateway proxy to itself — a trap the old line's `--port 8000` invocation walked straight into | Not a doc-vs-code contradiction needing a ruling: the line carried the `[Phase 2+]` marker, which §10 itself defines as "not runnable yet: the module exists as a docstring stub only", so it was an unverified placeholder written before the gateway spine landed (126d1ec) rather than a specification the code failed to meet. The factory-only shape is the **deliberate** side: the `Gateway` docstring rules it in terms — built once at startup "so a hot reload (FR-CFG-002) mutates the store the running app already holds, rather than leaving a stale copy behind a module global" — and every test injects through `create_app(gateway)`. Adding a module-level `app` to satisfy the stale line would have contradicted FR-CFG-002's hot reload and imported a `Gateway()` (policy load, `init_db`, dispatcher) as an import side effect |
| M-18 | **`entity_enricher` was unbounded inside a per-sentence hold.** 04 §2.2 budgeted it at < 10 ms **per enriched span** and capped the number of spans nowhere, so the composed hold was `60 + 10k`, crossing ADR-030's 100 ms P99 at **k = 4** | **RULED 2026-08-27 — closed.** 04 §2.2 now caps enrichment at **10 ms aggregate per sentence**, not per span. On exceed: skip remaining spans, log, increment `cp_enrichment_skipped_total{use_case,reason}` — semantics unchanged otherwise (never blocks, not a policy `fail_mode` class). ADR-030's derivation updates from *conditional on enrichment being capped* to **condition satisfied by the 04 §2.2 cap**: `k` leaves the arithmetic, the enriched typical row is a flat 40 ms, and every row fits | Never was a deviation — enrichment is unimplemented, so nothing measured could breach. It stayed logged rather than self-resolved because **the fix would have been a cap invented to make my own new target fit** (§5.4). The ruling came from the owner and lives in 04 §2.2 where the budget lives, not inside the target that needed it |
| M-19 | **Policy evaluate + action apply were inside a targeted quantity but unbudgeted.** 06 §4 puts them in the hold ("detector wait + policy + action"); 04 §2 budgets detectors only | **RULED 2026-08-27 — closed.** `cp.policy.evaluate` + `cp.action.apply` carry a **combined 5 ms budget** line in ADR-030's derivation, in every row. Measured, now that both spans are actually emitted: **combined P50 0.019 / P95 0.039 / P99 0.095 ms (n = 300)** — a per-request sum across units, so an upper bound on any single hold. Breach handling mirrors detectors: it surfaces in the per-hold series and trips `--check`, no new mechanism | Contradicted nothing — 04 §2 is a *detector* registry and never claimed the policy step. Worth recording that the three engine spans were in the 05 §5 vocabulary but **written by no code** when ADR-030 was accepted, so its original "measured well under 1 ms" had no measurement behind it; instrumenting them is what makes this row's figure real |
| M-20 | **ADR-030's `latency_json` changes were documented but not emitted — the rename included.** The write path wrote `gateway_overhead_ms`, and `input_hold_ms`, `sentence_holds_ms`, `added_time_to_last_byte_ms` existed as intervals in `app.py` but were **accumulated into one figure**, never recorded separately | **PARTLY CLOSED 2026-08-27 — the targeted half landed.** `input_hold_ms` and `sentence_holds_ms` are emitted on both delivery paths, `--check` gates both against NFR-P-001 naming the breaching subject and percentile, and the gated population is **holds, not requests**. So NFR-P-001 has a real verdict and the loud-stale note retires. **Rename landed 2026-08-28**: the write path, `spans.py`'s enforced vocabulary and the 06 §4 formula helper all carry `total_attributable_overhead_ms` (the metric `cp_gateway_overhead_ms` deliberately unchanged per 05 §5 — renaming it would orphan history for an unchanged definition). The checkpoint-3 review tripwire **fired on it**, which is what kept the code from drifting from the persisted rows, and was re-pointed rather than deleted. **Still open:** **`added_time_to_last_byte_ms`** alone — an untargeted publication row, so it does not gate NFR-P-001. As of **2026-08-28** that remainder is **contested rather than merely pending**: `[D1-added-time-to-last-byte-has-no-server-side-vantage]` reports that the gateway has no vantage from which 06 §4's client-observed quantity is measurable, so M-20 cannot be closed by emitting the key | Docs preceding code is this repo's design (§2). The residue is logged because **05 §5's vocabulary is enforced at the write path** by `check_latency_keys` while the `latency_json` key names are **not** doc-parsed by `tests/test_telemetry.py` (it parses the span and metric tables), so this particular divergence has no test holding it — a reader must be told, not left to infer |
| M-21 | **No continuous integration.** Every gate (suite, freeze, fault injection, latency tripwire) was runnable only by hand, so "passes on the author's machine" and "passes" were indistinguishable — and the repo became multi-machine at Checkpoint 3 | **RESOLVED 2026-08-27** — `.github/workflows/ci.yml`: matrix **py3.12 + py3.14**, running `pytest -q` → `validate_dataset --freeze` → `fault_injection` → `bench_latency --check`. **CI never writes to `reports/`**: both harnesses are redirected with `--out` and a final step asserts the directory is byte-identical, because a report from an ephemeral runner on unknown hardware would wear 06 §8 provenance it cannot support. The assertion exists because a comment promising it would not survive someone dropping the flag | Adds no contract and changes no behaviour — it executes commands AGENTS.md §10 already documents. Both matrix legs were **verified locally before the file was written** (py3.12.12 and py3.14.6, full suite exit 0, 0 failures), so the matrix is a measured claim rather than an aspiration |
| M-22 | **No onboarding path to verification.** AGENTS.md §10 lists the commands but not the order, the prerequisites, or what an uncomfortable-looking output means — so a newcomer could read `NFR-EVAL-001: MISSED` as a broken checkout rather than a logged, deliberately untuned target | **RESOLVED 2026-08-27** — `docs/TESTING.md`: four tiers (unit → eval → latency → live gateway), each self-contained, with the reasoning attached and the contracts cited rather than restated. Names the three pipelines and their `X-ControlPlane-Use-Case` values, the current measured-class `gpt-oss` tier ids, the `--factory` and port-8000 constraints, the frozen-dataset rule, and the stub inventory | Operational documentation, no contract. It **surfaced adjacent rot rather than working around it**: §10 still marked `eval.run_all` and `eval.bench_latency` `[Phase 2+]` — "not runnable, docstring stub only" — which both contradict (each was run to completion). Corrected in the same commit, since a guide saying *run these* beside a manual saying *these do not exist* is a doc-vs-doc conflict this repo would otherwise have to file |
| M-23 | **The README's status table had drifted from the docs it summarises — in the direction that overstates nothing and understates the build.** Three claims, three different ways of being wrong: it said **23 ADRs ruled** against a `03` holding **31**; it carried the literal suite count **`433`** in three places (status prose, quickstart comment, repo layout), each of which had to be right for the file to be right; and three rows read **not yet implemented** for the gateway hot path, the policy engine, and the latency + fault-injection harnesses — the code the prototype *is*, with committed evidence in `reports/`. The README is judge-facing, so this is an AGENTS.md §7 integrity problem rather than cosmetic doc rot, and it survived because nothing re-reads prose | Split by whether the number is **derivable**, because the two halves fail differently. The ADR count **is** derivable, so `tests/test_readme_status.py` now parses `03`'s level-2 `## ADR-NNN` headings and fails on any disagreement **in either direction** — a new ADR not reflected in the README, or a count the README invented. Counting `##` and not `###` is load-bearing and separately asserted: `03` carries **14** sub-headings (amendments, ADR-026's correction, ADR-030's derivations), and an amendment changes a decision rather than adding one, so counting them would inflate the total by over a third. The suite count is **not** derivable from any doc — it is a property of the run — so it was **removed** and pointed at `.github/workflows/ci.yml` (M-21), with a guard keeping literal 3-digit counts out; asserting the *correct* count would need editing on every commit that adds a test, which is the drift it was meant to prevent. The two conflated rows were **split** rather than flipped, since each mixed shipped code with real stubs (`cost_budget`, `cost_simulation`, `pii_leak_scan`, dashboard, demo runner are still unbuilt and still say so) | Not a deviation: the README is a **summary**, not a contract — `03`, `04` and `05` were correct throughout, and no reading of them was violated. Verified by mutation rather than by assertion alone: with the drifted README restored, **6 of the 8** new tests fail, naming the stale `23`, all three `433` copies and the understated rows; the 2 that pass read only `03` and are correctly independent of the README. **Provenance: owner adjudication, 2026-08-28 (Part 3), not the automated suite** |
| M-24 | **Policy `messages.*` templates were delivered to callers unrendered.** A live `hr_copilot` BLOCK returned the literal string `under {use_case} policy` — the judge-facing text on the most demonstrable beat in 07. 962 tests missed it because every assertion compared the served text against `policy.messages.block_fallback`, i.e. against the *same unrendered value the bug served*: a tautology that passes forever, in the exact shape 06 §3.1 rule 3 forbids elsewhere | Render both fields **once at load time** in `policy/schema.py`, not at the nine read sites. `{use_case}` is the only placeholder, `{{` escapes a literal brace, and every other form — including attribute access like `{use_case.__class__}`, which `str.format` would otherwise resolve into the object graph — is a **load-time** error, so a malformed template cannot reach a caller at all. Placeholders are validated *before* formatting, which is what makes that guarantee hold rather than merely usually hold. Regression assertions are now **properties** (no residual `{`/`}` in any shipped policy's rendered output), so they cannot be satisfied by the bug. 04 §4.3 records the rule; `fallback_used` in 05 §3 now stores rendered text | Not a deviation: no doc said templates were served raw. 05 §1.1 promises the caller the policy's fallback *text*, and a template is not text until it is rendered — the code simply did not do what the contract already required. **Provenance: found by owner testing (2026-08-28, first full manual run), not by the automated suite** |
| M-25 | **The request-level verdict was stamped from the output units alone.** An input-stage EDIT (ADR-020 pre-dispatch redaction) with a clean response stamped `verdict=pass`, so a request whose *prompt* was redacted was indistinguishable in the audit record, in `cp_requests_total{verdict}`, and to the caller from one where nothing happened — the gateway's most demonstrable privacy behaviour, unreported. 04 §4.3 steps 1–5 describe the stamp for **one evaluated unit** and never said how units combine, so neither side was contradicted | Owner ruling: the stamp is the **most severe action across every evaluated unit** (input lane, every output unit, conversation stage) under the §4.2 total order — added to 04 §4.3 as `Request-level aggregation`. The *evidence* is the **union** over units rather than the winning unit's row: `from_verdict` reads `detector_failures_json` off the stamped verdict, so picking one unit would drop a §5 fault whenever two units tied on severity (this regressed 4 of 27 fault-injection assertions and is why the union is not merely tidier). `contributing_signal_ids`/`failure_record_ids` still filter that union against the stamped action, keeping a `fail_open` fault under a PASS representable as *recorded but not contributing*. M-12's header half is narrowed in the same commit | Not a deviation but a **gap the ruling closed**: 04 §4.3 was silent on aggregation, so no reading of it was violated. Verified by mutation rather than by assertion alone — with the fix reverted, the new tests fail with `assert 'pass' == 'edit'`, the owner's exact observation. **Provenance: found by owner testing (2026-08-28), not by the automated suite** |
| M-26 | **A pre-dispatch terminal recorded its cost as unknown rather than as zero.** 04 §4.5 blocks before any upstream call, and the record left `tokens_*` and `est_cost_usd` null on the stated reasoning that a zero "would claim a free upstream call happened". That reasoning covers the *price* of an unpriceable model but not the *quantity* sent, which in this case is known exactly | Owner ruling: a short-circuited request records `tokens_in`/`tokens_out` = **0/0**, and on a `measured`-class provider `est_cost_usd` = **0.0** — a counted zero, not an estimate. `dev` class stays null (ADR-018: its accounting is not a measurement, so a 0.0 from it would be a barred figure in the column reports read), and `model_used` stays null on both, since no model answered. Added to 05 §3 as two `no dispatch` rows with the reason the null-not-zero rule inverts there, and pointed at from 04 §4.5 | Not a deviation: 04 §4.5 already said "no cost", so 0.0 is what the doc claimed and null was the weaker reading. The consequence is a real one for the cost plane — **null is excluded from an average**, so leaving it null made a pipeline that blocked half its traffic pre-dispatch report the same mean cost as one that blocked none, erasing exactly the saving the cost plane exists to show. Scoped by a test on the case the ruling did *not* touch: a **dispatched** request with an unpriceable model still records null, so the counted-zero branch cannot widen unnoticed. **Provenance: found by owner testing (2026-08-28), not by the automated suite** |
| M-27 | **Ingress rejections carried an empty `request_id`.** `ingest` minted the id on its own last line — *after* both rejections it can raise — so an ERR-CFG-001/002 body reached the caller as `"request_id": ""` with no `X-ControlPlane-Request-Id` header. 05 §1.1 already promised "All responses carry" that header, so this was non-compliant with an existing contract rather than an unspecified case | Mint in the handler before use-case resolution and pass it into `ingest` (which already accepted `request_id=`), publishing it to `request.state` immediately so the `GatewayError` handler finds it. Recorded in 05 §1.2. Both codes are tested because they fail at different points — ERR-CFG-001 before any policy resolves, ERR-CFG-002 relative to one — so a mint anywhere *inside* `ingest` would have fixed at most one | Not a deviation: no doc said the field could be empty, and §1.1 said the opposite. The failure mode worth naming is the one the fix could have introduced — **two** ids, one minted in the handler and one in `ingest`, would leave the header naming a request the audit table never heard of, which is worse than an empty string because an operator would follow it to a confident dead end. Pinned by a test asserting header == audit record id on the success path, plus a uniqueness test (a constant satisfies every other assertion here and correlates nothing). **Provenance: found by owner testing (2026-08-28), not by the automated suite** |
| M-28 | **`cost.request_too_large` is unmapped in all three shipped policies**, and ADR-032 item 4 makes `budget.per_request_max_tokens` the per-use-case **latency** control for `tier2_injection`. A policy that lowers it to cap input latency therefore has no mapped signal for the rejection it implies — the gate would bound the windows without anything user-facing saying why | **Logged, not fixed.** `cost_budget` is a Phase-6 stub and the label→action mapping belongs with it; ADR-032's escape valve works today for *raising* a ceiling, which is the direction a 4000-token pipeline needs. Filed so lowering it is known to be half-wired rather than discovered by a caller | Named in ADR-032 consequence 3 rather than left implicit: the escape valve is the ADR's answer to a 0.6 s worst case, so the fact that one direction of it is incomplete has to be visible beside the answer |

**Resolved 2026-08-26 under the Phase-4 ruling** (was: flagged, not fixed):
`SPAN_LESS_LABELS` in `eval/validate_dataset.py` contained `cost.runaway_loop`, which is **not in
the taxonomy** — the real label is `cost.loop_detected`. Corrected on instruction. The member was
provably dead: zero corpus cases carry it, and the validator's output is **byte-identical**
before and after (280/280, freeze digest `6a3ecbbe75fd020b…` still matching), so the edit to a
freeze-adjacent file moved no number.

**Closed 2026-08-26 by M-9** (was: flagged, not fixed): the divergence reported here — the matrix
including `cost.request_too_large` where the validator did not — is resolved by single-sourcing,
which the Phase-4 housekeeping ruling authorized. The consequence noted at the time still reads
correctly as the reason it mattered: had a `cost.request_too_large` case ever been labelled EDIT,
the validator would have skipped the ADR-015 promotion the matrix applies. It stayed dead
throughout (zero corpus cases), so nothing computed under the freeze was ever affected.

## Standing Limitations

**Purpose.** Permanent home for **decided-but-unmet** items: things ruled on, understood, and
consciously accepted — not open questions and not open deviations. Without this register, closing
a deviation whose gap survives would make the gap invisible, and a ledger reading `Open: zero`
would look like "nothing missing" when it only ever means "nothing undecided". An entry leaves only when the limitation
itself is gone, never because it stopped being newsworthy.

| ID | Limitation | Measured / stated | Why it stands | Where it is visible |
|---|---|---|---|---|
| **SL-1** | **NFR-EVAL-001 unmet** — `tier1_pii` recall below the 0.95 target | **0.8852** vs 0.95 (precision 1.000, so no over-firing). v1 baseline **0.8361** | **100% of the residual misses are the documented bare-7-digit scope exclusion** (ADR-026 §3) — 7/7, verified programmatically by stripping co-occurring SSN/card/email spans and measuring the phone candidates' digit length (all 7, none ≥10). A bare `NNN-NNNN` is indistinguishable from an order or ticket id, so matching it would trade the perfect precision away. **The target was not moved** (ADR-026 §5) | `reports/eval_report.md` §NFR-EVAL-001 + §Disclosed revision; README claims row *Tier-1 PII recall*; closed deviation `D3-tier1-pii-recall-below-target` |
| **SL-2** | **v1-superset phone behaviour**: an invalid NANP area code still fires — e.g. `(115) 555-0123` | Documented v1-superset behaviour, **not a bug** | v1's `_PHONE` is retained deliberately and evaluated first, so it shadows the NANP `N ∈ [2–9]` rows. Narrowing it would change v1-derived behaviour and the permanent precision-1.000 baseline would no longer describe code that ships. Precision hardening is a **later freeze cycle** and must not ride along with a measurement | ADR-026 Amendment 1; 04 §2.5; `tests/test_tier1_detectors.py::test_nanp_n_constraint_rejects_leading_0_and_1` (asserts at pattern level, docstring records the shadowing) |
| **SL-3** | **DOWNGRADED 2026-08-27 (ADR-029) — now a provenance-*freshness* reminder, no longer a publication gate.** First-party prices exist for both bound ids | `console.groq.com/docs/models` carries per-1M figures directly: `openai/gpt-oss-20b` **$0.075 in / $0.30 out**, `openai/gpt-oss-120b` **$0.15 in / $0.60 out**. Retrieved 2026-08-27. The retired llama pair now prices as "ContactSales" on that same page, which is why its old figures were never obtainable first-party | **Absolute dollar figures ARE publishable for these two ids**, carrying `source_url` + `retrieved`. Two limits stand: any comparison priced on the **retired llama pair remains barred** (never first-party, and the models no longer serve, so it can never be re-verified); and prices are **re-verified at submission packaging**, since a stale price is a wrong price. The entry stays open for that re-verification, not for a missing source | `config/gateway.yaml` (provider `groq`); ADR-022; **ADR-029**; README claims section; 06 §6 |
| **SL-4** | **CLOSED 2026-08-28 (owner evidence).** ~~No genuinely local fallback model installed~~ | `llama3.2:3b` is installed on the **owner's** host (Ollama v0.33.0) and passes the no-`remote_host` assertion, so it is genuinely local and `unmetered` holds. Bound to `ollama-local`'s **small** tier; `frontier` left null (one model evidenced — binding both would make the cascade a no-op while looking configured) | The limitation itself is gone, which is the only reason a row leaves this register. **But it is gone host-by-host:** the development host still serves only `minimax-m2.7:cloud` with `remote_host` (Ollama v0.31.1, re-confirmed 2026-08-28), so there a dispatch to this provider fails and no fallback latency or cost figure can be produced — AGENTS.md §7 still bars reporting one from that host. The row is kept and struck through rather than deleted, so the closure is auditable against the condition it closed | `config/gateway.yaml` (`ollama-local`, `small` bound, STUBs removed); Q-10 **RESOLVED**; `tests/test_gateway_config.py::test_sl4_ollama_binds_the_owner_verified_local_model` pins the config-level claim — deliberately not a live dispatch |
| **SL-5** | **The Tier-2 <25 ms budget is measured with 6 threads free for one inference**, and NFR-P-002 states no concurrency assumption | At **1 thread**, both ADR-031 picks breach at the output segmenter cap: `madhurjindal` **25.90 P50 / 26.20 P99**, `martin-ha` **34.48 / 35.50** (ONNX int8, n=50). Both still fit at corpus-typical lengths (**17.81 / 10.62 P50**) | Every Tier-2 figure this repo publishes is a **low-concurrency** figure: one inference gets the whole CPU on an idle laptop, and under concurrent requests per-request parallelism falls toward the 1-thread column, where the budget stops holding at the cap. Not tuned away and not reported as a passing number — the 1-thread column is published beside the 6-thread one so the exposure is visible rather than inferred. Bounding it properly needs a concurrency figure NFR-P-002 does not state and no harness here measures; a load test is **Phase 6+** and out of hackathon scope | ADR-031 §5; `reports/spike_tier2_models.json` (both `threads` sweeps); any Tier-2 latency claim in the README or 06 §4 |

### Prose-fix log — ADR-026 Amendment 2 clause (d)

Every post-measurement presentation-prose correction, logged on use. Amendment 2 requires the log
precisely so that uses **accumulate visibly**: a register with several entries is itself evidence
that report prose is being written carelessly, and the cheap path stays "get the prose right
before measuring".

| # | Date | What was corrected | Figure-identity proof | Verified |
|---|---|---|---|---|
| 1 | 2026-08-26 | `eval/run_all.py` `numeric_claims` note claimed a **Q-18 publication gate that ADR-025 had already lifted** — stale prose sitting directly above the figures it disclaimed | `reports/eval_report_prose_fix.diff` — **PROVEN**: 3 of 151 lines differ (run timestamp; `Code commit` stamp, which 06 §8 *requires* to change; the note itself). 276 numeric tokens on the 93 measurement-bearing lines identical in sequence; normalized SHA-256 identical; all 5 metric rows byte-identical; all 6 measurement inputs identical | **VERIFIED** 2026-08-26 (clause (c)) — `reviews/phase2-review.md` § *Publication-gate ruling* (committed as `554e0d0`, "review: record checkpoint 2 re-review"): the reviewer regenerated both reports independently from the archived source states `7c8261d` and `fbcfcf593552` and found **all 32 measurement/result rows byte-identical**, with no numeric delta. Clause (c) is satisfied because that is a second party's **reproduction from source**, not the executor's own identity check on its own artifact |

Note recorded against entry 1: the first identity check was written over *every* digit in the file
and **failed** — first divergence `18 → 04`, which is `Q-18` becoming `04 §2.4.2` inside the
rewritten sentence. The check was comparing document cross-references as if they were
measurements; its scope was wrong, not the artifact. The failure is disclosed in the proof itself
rather than dropped, because a check narrowed *after* it fails must show its working or the
narrowing is indistinguishable from evading it.
---

## Deferred scope (phase assignment)

**Purpose.** What is *planned but not yet built*, and which phase owns it. This is a third
register, distinct from the two above it: an **open question** is undecided, a **Standing
Limitation** is decided-and-permanently-unmet, and a deferred item is decided, understood, and
simply not reached yet. Without it, "not implemented" and "not required" are indistinguishable
from outside the code — and the whole point of AGENTS.md §7 is that a reader can tell coverage
from the absence of coverage.

**Amended 2026-08-27** (ruling, no ADR — no contract changes): `fast_consistency` and
`rag_grounding` move to **Phase 5** (the detector ML stack) alongside the Tier-2 classifiers.
Both were previously carried as if in scope for the gateway spine; neither is. The list now
matches the tree.

**Deferred coverage carries a tripwire test (ratified 2026-08-27).** Where a deferred detector
makes a spec artifact unreachable, the standard is to **assert the limitation** rather than delete
or weaken the case: `tests/test_gateway_app.py::test_ovlp01_is_not_yet_wired` pins that OVLP-01
yields `pass` and emits no signals today, so the moment `rag_grounding` or `entity_enricher` lands
the test fails and names what must be re-pointed. This is what keeps a deferral self-cancelling —
a deleted case is forgotten, an asserted limitation is not. PII-001 carries 07 beat 4 until then.

| Phase | Item | State in the tree |
|---|---|---|
| **5 — detector ML stack** | `tier2_injection`, `tier2_toxicity` | `detectors/tier2_classifiers.py`, `STUB(phase-1-scaffold, Q-04 deferred)`; checkpoints unpicked (Q-04) |
| **5 — detector ML stack** | `fast_consistency` | `detectors/consistency.py`, 7-line stub. Needs a second sample at temperature + embedding cosine (04 §2.3, ADR-014) |
| **5 — detector ML stack** | `rag_grounding` | **no module at all.** Needs sentence-vs-context embeddings (04 §2) |
| 5 | `entity_enricher` (ADR-011) | `detectors/entity_enricher.py` stub; needs spaCy `en_core_web_sm` |
| 6 — cost plane | `cost_budget`, `loop_guard`, cascade probe (ADR-013) | `detectors/cost.py` stub; `sse_proxy` carries no probe **by design**, not stubbed (a probe that silently did nothing would make `cascade_escalated` false for the wrong reason) |
| 6 | `conv_tracker` (FR-GW-005) | `detectors/conversation.py` stub |
| 7 — slow lane | deep audit: `entropy`, `fairness`, `sampler` | three stubs under `deep_audit/` |
| 7 | dashboard (ADR-007) | `dashboard/app.py` absent |

**Measured inventory, 2026-08-27** — 3 of the 11 detectors declared in
`detectors/base.BUDGETS_MS` are live, where "live" means a module exposes an instance whose
`.name` matches a budget entry and which has an `async detect`:

| | Detectors |
|---|---|
| **Live (3)** | `tier1_pii`, `tier1_blocklist`, `numeric_claims` |
| **Declared but absent (8)** | `tier2_injection`, `tier2_toxicity`, `fast_consistency`, `rag_grounding`, `entity_enricher`, `cost_budget`, `loop_guard`, `conv_tracker` |

`BUDGETS_MS` is deliberately **not** trimmed to the live three: `register()` refuses a detector
with no budget, so the table is the 04 §2 registry transcribed, and an entry there is a statement
about the spec rather than about today's tree.

**The consequence this creates is a requirement, not a caveat.** `finance_advisor` (UC-3) sets
`consistency: "on"`, so its policy asks for a check that no longer exists in this phase. A record
that listed only the detectors which *ran* would let a reader infer coverage that was never
attempted. Every audit record therefore carries what ran **and** what was expected but did not,
with a reason — see M-10 and 05 §3/§4 `detectors_json`. A registry gap is recorded as *not run*;
that is a different fact from a `DetectorFailureRecord`, which means a detector ran and broke.

## DEVIATION REPORT [D2-detector-params-cannot-hold-list-values]
Severity: MINOR
Doc & section: 04 §2.4.4 (ADR-025's extension point); 04 §3 policy schema `detector_params`
The doc says: ADR-025 makes `numeric_claims`' unit list and citation-marker list "extensible via
`detector_params.units` / `detector_params.citation_markers`".
Reality says: `Policy.detector_params` is typed `dict[str, dict[str, float]]` — a mapping of
detector name to **float** parameters, which is what `tier2_toxicity`'s cutoffs needed. A list of
strings cannot be stored in it, so the extension point ADR-025 describes does not exist yet.
`DetectorContext.params_for()` returns `dict[str, float]` for the same reason.
Impact if we ignore it: none immediately — 04 §2.4 carries the normative lists and the detector
reads those, so both detectors are fully implementable and no number is affected. The cost is that
a documented capability is not real, which is the kind of gap that gets discovered by whoever
first tries to use it.
Options:
  A) Widen to `dict[str, dict[str, float | list[str]]]` and have `params_for` return the union.
     Trade-off: every consumer must narrow the type; touches the detector contract in base.py.
  B) Add a separate `detector_lists: dict[str, list[str]]` field. Trade-off: two override
     mechanisms keyed by detector name, and a reader must know which one holds what.
  C) Drop the extension-point sentence from ADR-025 and keep 04 §2.4 as the only source.
     Trade-off: loses per-use-case tuning that a regulated UC might genuinely want (its own
     filing vocabulary as citation markers).
Recommendation: **A** — one mechanism, and the narrowing is local to the two detectors that read
lists. Not applied, because widening a core schema type to satisfy a doc sentence is exactly the
kind of change that should be ruled rather than assumed.
Blocked work: none. Filed because 04 §2.4.4 now cites this slug, and a slug in doc prose that is
absent from this ledger means the ledger is what is wrong (AGENTS.md §11).

## DEVIATION REPORT [D3-tier1-pii-recall-below-target]
Severity: MAJOR
Doc & section: 01 §2 NFR-EVAL-001 ("Tier-1 PII recall ≥ 0.95"); detector contract 04 §2 row 1
The doc says: Tier-1 PII recall ≥ 0.95 on the labeled set, measured by `eval/run_all.py`.
Reality says: **0.8361** micro recall (51 TP / 61 positive label occurrences) on the frozen
280-case corpus. Precision is **1.000** — zero false positives — so this is purely missed
coverage, not over-firing. 10 misses in two clusters:
  * **8 × `pii.phone`** — the NANP pattern requires a 10-digit form. Missed: 7-digit local
    (`NNN-NNNN`), E.164 with country code, dot-separated, and a parenthesised 7-digit form.
    5 of the 8 are multi-PII cases where the SSN/card/email span WAS caught, so the case is
    partially detected — the verdict would still fire, but per-label recall is short.
  * **2 × `pii.api_key`** — a JWT-shaped bearer token and a generic 32-char hex secret behind
    an `api_key=` assignment. Both fall outside the vendor-prefix rule, which was a
    documented deliberate choice (a generic high-entropy rule would fire on request ids).
Measurement verified before filing: each miss was re-run individually and confirmed to be a
real detector gap, not a harness artifact. `python -m eval.run_all` reproduces it.
Impact if we ignore it: NFR-EVAL-001 is the one detector target with a number attached, and
Tier-1 PII is the FR-DET-001 core. A 0.836 recall published against a 0.95 target is a missed
target; publishing 0.836 while *claiming* 0.95 would be fabrication (AGENTS.md §7).
Options:
  A) **Extend the patterns from the spec, not from these cases** — add 7-digit local and
     E.164 phone forms and a bounded generic-secret rule, derived from published format
     definitions, then re-measure. Trade-off: 7-digit runs and high-entropy strings are
     exactly `clean.jsonl`'s FP pressure, so precision (now a perfect 1.000) will drop. The
     honest version of this option accepts a precision cost and reports both numbers.
  B) **Accept 0.836 and report it as a missed target** with the cluster analysis above.
     Trade-off: the headline detector misses the stated bar, which a skeptical judge will
     read as the prototype's weakest claim — but it is defensible and true.
  C) Narrow NFR-EVAL-001's scope to the categories the vendor-prefix/10-digit rules cover.
     Trade-off: **rejected as target-gaming** — redefining the metric to match the result is
     precisely what AGENTS.md §7 forbids. Listed only to record that it was considered.
Recommendation: **A**, then re-measure and report whatever comes out, because the misses are
genuine format coverage rather than a threshold to tune — but it MUST be done from format
specifications with new tests authored independently, and I should not do it having now read
these case notes. If you'd rather protect the independence of the measurement entirely, B is
the honest fallback.
Blocked work: any publication of a Tier-1 PII recall number (README row, proposal, video).

## DEVIATION REPORT [D8-numeric-claims-treats-identifiers-as-statistics]
Severity: MAJOR
Doc & section: 04 §2 `numeric_claims` row — "currency/percent/large-number patterns with no
citation marker and no match in provided context"
The doc says: fire `hallucination.unsourced_numeric` on a large-number pattern that carries no
citation and no context match.
Reality says: implemented faithfully, that clause yields **precision 0.267** — 33 false
positives against 12 true positives. **30 of the 33 are `PII-*` cases.** The cause is
structural, not a tuning miss: an SSN, a credit-card number and a phone number are all runs of
digits, so the "large-number" clause classifies **identifiers as statistics**. Recall is 0.750,
so the clause works on real figures; it simply also fires on every identifier in the corpus.
Impact if we ignore it: a 0.267-precision detector mapped to **ESCALATE on UC-3** (01 §3) would
quarantine roughly three responses for every one that warranted it — the demo's escalation beat
becomes noise, and the eval report carries a number that invites exactly the skepticism 06 was
written to withstand. It also silently double-flags every PII case on the performance plane.
Options:
  A) **Exclude identifier-shaped runs in the detector** — suppress a large-number match whose
     span is inside, or adjacent to, a Tier-1 PII match. Trade-off: couples two detectors that
     04 §1 keeps independent, and detectors do not see each other's signals; it would need the
     engine to mediate, which is a real design change.
  B) **Narrow the "large-number" clause to quantity-shaped numerals** — require a magnitude
     word, thousands separators, or a unit/currency/percent context, and drop the bare
     "4+ consecutive digits" rule. Trade-off: loses bare statistics like "we processed 15000
     requests"; recall on genuinely unsourced bare integers drops. This is a **spec amendment**
     to the 04 §2 wording, not just a code change.
  C) Accept and report 0.267 with the cause stated. Trade-off: honest, but ships a detector
     whose ESCALATE mapping is not defensible on UC-3.
Recommendation: **B** — the clause's *purpose* is unsourced statistics, and an identifier is
not a statistic under any reading; the bare-digit-run rule is the part that overreaches. It
needs a doc change to 04 §2 rather than a quiet code edit, which is why it is here and not
already applied. Note this interacts with **Q-18**: both shape the same precision figure.
Blocked work: any `numeric_claims` precision/F1 number, and the UC-3 escalation demo beat's
credibility.

---

## DEVIATION REPORT [D1-citation-marker-per-matches-the-rate-preposition]
Severity: BLOCKER
Doc & section: 04 §2.4.2 (citation-marker list, closing Q-18); ADR-025
The doc says: the citation-marker list includes the attribution phrase `"per "` — quoted with a
trailing space, alongside `"as per"`, `"according to"`, `"reported by"`.
Reality says: `per` in English is overwhelmingly the **rate** preposition, not an attribution.
Implemented literally, the marker suppresses every rate-shaped quantity:

| sentence | v2 signal |
|---|---|
| `Cost is $4 million per year.` | **none** |
| `Latency was 250 ms per request.` | **none** |
| `Throughput hit 22% per node.` | **none** |
| `We store 4 TB per tenant.` | **none** |

Measured corpus exposure on the current freeze: 6 cases contain a rate `per`, of which **2 are
labelled `unsourced_numeric` — HAL-049 (`per day`) and HAL-052 (`per employee`) — and both are
suppressed**, i.e. two guaranteed false negatives.

This is not an implementation choice I can narrow away. v1 scoped the same clause as
`\bper\ (?:the|our|your|section|clause|§)\b` — attribution only — and ADR-025 replaced it with
the bare token. There is no reading of a literal `"per "` that excludes `per year`.
Impact if we ignore it: rate-expressed figures are the shape financial and performance claims
most often take, and this is the detector whose UC-3 mapping is **ESCALATE** — so the miss lands
on the highest-stakes path. Worse, ADR-026 §5 permits **one** re-measurement and forbids
adjusting anything afterwards, so measuring now makes the two known misses permanent and
unrevisable.
Options:
  A) Re-scope the marker to attribution contexts, e.g. `per (?:the|our|your|section|clause|§|
     annex|exhibit|filing)` — v1's shape, which is the precedent. Trade-off: `per Smith 2024`
     and other bare-noun attributions are missed, raising firing on genuinely-cited figures.
     Direction is safe: it can only *raise* the firing rate, never hide an unsourced number.
  B) Drop `per` from the list entirely and rely on `as per`, which is unambiguously
     attributive. Trade-off: `per the filing` stops being a marker; strictly more firing than A.
  C) Keep the list literally as ruled and accept the two misses. Trade-off: a documented,
     spec-mandated false negative on the ESCALATE path, permanently baked into the v2 number.
Recommendation: **A** — it restores the clause to the only sense in which it is an attribution,
matches the v1 precedent so the two columns stay comparable in kind, and its error direction is
the safe one. Not applied: the list is normative in a ruled ADR, and editing it is a ruling.
Blocked work: the ADR-026 §5 re-measurement, and therefore the closure of **D3 and D8**, the
dual-column report, and the README claims rows that cite it.

## DEVIATION REPORT [D2-nanp-n-constraint-rejects-nothing-as-composed]
Severity: MAJOR
Doc & section: 04 §2.5 (`tier1_pii` v2 pattern set, ADR-026)
The doc says: the NANP `N ∈ [2-9]` constraint on the first digit of the area code and exchange
"is a **spec-justified narrowing that also protects precision** — … it happens to reject the
digit runs that would otherwise false-positive."
Reality says: it rejects nothing in the composed detector. v1's `_PHONE`
(`(?:\(\d{3}\)|\b\d{3})[-.\s]?\d{3}[-.\s]?\d{4}`) is **retained** and runs **first** in
`_PII_PATTERNS`, matching the same extent, so longest-match-wins hands it the span:

    (115) 555-0123  -> fires (via _PHONE)      NPA starts with 1 — invalid NANP
    (015) 555-0123  -> fires (via _PHONE)      NPA starts with 0 — invalid NANP
    (415) 155-0123  -> fires (via _PHONE)      NXX starts with 1 — invalid NANP
    415.055.0123    -> fires (via _PHONE)      NXX starts with 0 — invalid NANP

A second measured consequence, worth stating because it changes what the v2 column will show:
`_PHONE` already matched both the parenthesized and dot-separated 10-digit forms, so the two new
NANP rows add **no recall at all**. The v2 phone gain comes from **E.164 alone**, plus the
`( 415 ) 555-0123` spaced-parenthesis variant.
Impact if we ignore it: a precision claim in a contract doc that the code cannot support. It does
not block the re-measurement — recall can only rise — but it means the doc describes a
discrimination the detector does not make.
Options:
  A) Narrow `_PHONE` to `[2-9]` on both groups, making v1's rule NANP-conformant. Trade-off:
     changes v1-derived behaviour, so the v1 precision-1.000 baseline no longer describes the
     shipped code — exactly what ADR-026's permanence rule exists to prevent.
  B) Retire `_PHONE` in v2 in favour of the three spec-derived rows. Trade-off: same permanence
     objection, larger; also drops the bare `\b\d{3}` 10-digit form, which is real coverage.
  C) Amend 04 §2.5 to drop the precision sentence, keeping `[2-9]` as spec conformance only.
     Trade-off: the constraint stays inert — honest, but it earns nothing.
Recommendation: **C** — the constraint is genuinely in the NANP definition and belongs in a
spec-derived pattern; the false part is the precision claim, not the pattern. A is defensible in
a later freeze cycle but must not ride along with a measurement.
Blocked work: none. `tests/test_tier1_detectors.py::test_nanp_n_constraint_rejects_leading_0_and_1`
asserts the constraint at the **pattern** level, where it is real, and records the shadowing in
its docstring rather than pre-judging this ruling.

## DEVIATION REPORT [D2-adr-026-eyj-derivation-is-arithmetically-wrong]
Severity: MINOR
Doc & section: ADR-026 §2 (JWT pattern justification); 04 §2.5 JWT row
The doc says: anchoring on `eyJ` is permitted and spec-derived because "it is the base64url
encoding of `{\"`, the mandatory start of every JOSE header — that written justification is what
makes it auditable as non-fixture-shaped."
Reality says: `base64url({\") == "eyI="`, not `"eyJ"`. Base64 packs three input bytes into four
output characters, so two bytes cannot determine the third character. The third character is

    ((0x22 & 0x0F) << 2) | (next_byte >> 6)  =  8 | (next_byte >> 6)

and base64 index 9 is `J`, so the anchor holds exactly when `next_byte >> 6 == 1` — i.e. the
byte after `"` is in `0x40`–`0x7F`, which every ASCII letter is. RFC 7515 §4 makes the header a
JSON object and every registered parameter name (`alg`, `typ`, `kid`, `crit`, …) begins with a
letter, so the anchor does hold for every conforming header whose first member is a registered
parameter. **The ADR's conclusion is correct; only its stated derivation is wrong.**
It also exposes one real bound the ADR's version hides: JSON permits whitespace after `{`, and
`base64url({ \"alg\") == "eyIg…"` — no anchor. A pretty-printed JOSE header is missed.
Impact if we ignore it: the pattern is fine and no number moves. The cost is specific to
ADR-026's own purpose — the written justification is what makes the anchor auditable rather than
fixture-shaped, and an auditor who checks the arithmetic finds it false, which discredits a
correct decision.
Options:
  A) Amend ADR-026's justification to the true derivation and record the whitespace bound.
     Trade-off: none beyond editing a ruled ADR, which requires this ruling.
  B) Leave it and rely on the test docstring, which already carries the correct derivation.
     Trade-off: the ADR — the auditable artifact — stays wrong.
Recommendation: **A**.
Blocked work: none. `test_rfc_7515_eyj_anchor_is_a_property_of_the_format` asserts the ADR's
literal claim **as false**, asserts the true condition across nine registered header parameters,
and asserts the whitespace bound, so the correction is executable rather than only prose.

## DEVIATION REPORT [D5-detector-failure-signal-is-unconstructible]
Severity: MAJOR
Doc & section: 04 §5 "Failure semantics (fail-open / fail-closed) — FR-POL-006", against 04 §1.1 (label taxonomy) and 05 §3/§4 (`signals_json`)
The doc says: on `DetectorTimeout`/`DetectorError` "the gateway **synthesizes**: `labels: ["_meta.detector_failure"], meta: {detector, error_class}`", and fail_closed means "**synthesized signal** maps to ESCALATE". `controlplane/detectors/base.py` calls it "a synthesized `_meta.detector_failure` signal" in the same terms.
Reality says: that object cannot be constructed. `_meta.detector_failure` is not in `TAXONOMY`, and `Signal._check_labels_in_taxonomy` rejects it — verified: `Signal(...labels=["_meta.detector_failure"]...)` raises `1 validation error for Signal`. The two rules are individually correct and jointly unsatisfiable: 04 §1.1 is a **closed** taxonomy of *content risks*, and a detector fault is not a content risk, so the label has nowhere legitimate to live in it.
Impact if we ignore it: three concrete consequences, not one aesthetic one. (1) 05 §3 `signals_json` is documented as `list[Signal]`, so a failure that is not a `Signal` has no defined place in the audit record — yet 04 §5 requires the fault to be visible to a human. (2) Anything reading `signals_json` to count risks would have to special-case a pseudo-label, or a `_meta.*` entry would be counted as a detected risk and inflate `cp_pii_intercepts_total`-style aggregates. (3) The fail_closed path is FR-POL-006 and SC-3 — a demo beat — so leaving the representation undecided leaves a demo artifact undecided.
Options:
  A) Add `_meta.detector_failure` to the taxonomy as an explicitly non-content namespace — trade-off: makes the doc literally true and `signals_json` uniform, but punctures the "taxonomy = content risks" invariant, and every consumer must now exclude `_meta.*` or over-count. The invariant is load-bearing in 04 §1.1 and in the detector tests.
  B) Keep faults off the `Signal` type (what ships today: `DetectorFailureRecord`, a frozen dataclass resolved by `resolve_failure`) and amend 04 §5 to describe a **failure record** rather than a synthesized signal, with its own audit field — trade-off: one more field in the audit schema (05 §3/§4), and 04 §5's wording plus the `base.py` docstring must change. Keeps the taxonomy clean and makes miscounting structurally impossible rather than merely discouraged.
  C) Represent the fault as a `Signal` carrying a real label from the affected detector's own scope — trade-off: rejected on sight; it would be indistinguishable from a genuine detection and is the one option that could produce a fabricated risk figure.
Recommendation: **B** — the taxonomy's closure is what makes label-derived counts trustworthy, and a fault is a different kind of fact from a finding; the cost is a schema field and two sentences of doc, which is cheaper than teaching every consumer to filter a pseudo-label.
Blocked work: nothing is blocked *today* — `evaluate()`/`resolve_failure()` implement 04 §5's **semantics** correctly (fail_open proceeds and is recorded; fail_closed escalates and never silently blocks; both unit-tested, including the never-BLOCK guarantee swept across every policy × detector × error class). What waits on the ruling is the **audit representation**: the gateway's `signals_json`/`actions_json` write path for detector faults, and the 06 §5 fault-injection harness that will read it back.

## DEVIATION REPORT [D1-usage-canary-has-no-independent-count-on-the-measured-class]
Severity: BLOCKER
Doc & section: 01 §1 FR-GW-006; 05 §6.1 `usage_sanity`; ADR-018 (Context)
The doc says: at boot, one canary request "compares `count_tokens` against the provider's
reported prompt-token count. Delta > `usage_sanity.max_token_delta` (default 25) ⇒ the
provider's accounting is untrustworthy: **measured-class fails boot**, **dev-class warns
loudly and continues**."
Reality says: `count_tokens` is **not repo code** — it appears nowhere in the tree, and no
tokenizer is declared in `pyproject.toml` (02 §8's dependency list does not name one). It is a
**provider endpoint** (Anthropic-shaped `POST /v1/messages/count_tokens`), which is where
ADR-018's `14 / 75 / 5074` figures came from. Keyless existence probes — **no credential sent**,
so 401/403 = "exists, auth-gated" and 404 = absent — run 2026-08-26:

| provider | class | probe | result |
|---|---|---|---|
| `kiro-local` | dev | `POST /v1/messages/count_tokens` | **401 — EXISTS** |
| `groq` | measured | `POST /v1/messages/count_tokens` | **404 — ABSENT** |
| `groq` | measured | `POST /v1/tokenize` | 404 — ABSENT |
| `groq` | measured | `POST /v1/messages/count_tokens` (Anthropic path) | 404 — ABSENT |
| `groq` | measured | `GET /v1/models` *(control)* | 401 — host reachable, auth-gated paths do answer |

The control row is what makes the 404s meaningful rather than a network artifact. So the
independent count this invariant compares against exists **only on the class whose consequence
is a warning**, and is **absent on the class whose consequence is boot refusal**. The mechanism
is implementable exactly where it does not matter and unimplementable where it does.
Impact if we ignore it: the boot-time guard protecting every judge-facing number (AGENTS.md §7)
degrades to a no-op on the measured class, so the ~5000-token-offset class of bug ADR-018
documents would reach a report unchallenged. A canary that always passes **because it cannot
run** is worse than an absent one — it reads as a green check.
Options:
  A) Local tokenizer as the independent source (new dep — `tokenizers`/`transformers` plus the
     Llama tokenizer; **ADR note required per 02 §8**) — trade-off: a local tokenizer does not
     model Groq's server-side chat template, so its systematic error competes directly with
     `max_token_delta: 25`. Too tight and a measured-class provider is refused boot over a
     template mismatch; too loose and it stops being a check. The error budget is unquantified
     until measured, so the threshold has no meaning yet.
  B) Redefine the invariant as a **provider-internal self-consistency** check: one identical
     canary prompt sent twice, streaming and non-streaming, comparing the provider's *own*
     reported `prompt_tokens`. Needs no external count and works on every provider — and it is
     precisely the comparison that would have caught ADR-018's bug (75 streaming vs 5074
     non-streaming, delta 4999 ≫ 25 ⇒ dev-class warn, exactly FR-GW-006's specified behaviour).
     Trade-off: a different invariant from the one 01 §1 states, so FR-GW-006 and 05 §6.1 change;
     it cannot catch an error that is *consistent* across both paths.
  C) Scope FR-GW-006 to providers exposing a token-count endpoint, and make its absence on a
     measured-class provider a loud boot **WARNING** naming the provider — trade-off: honest and
     cheap, but the measured path keeps no automated guard; the protection becomes a Standing
     Limitation rather than a mechanism.
Recommendation: **B.** It adds no dependency, applies uniformly to both classes, and is the only
option demonstrated to catch the exact failure the requirement was written in response to — on
the two shipped providers it yields the right verdict in both directions (kiro-local warns, a
consistent provider passes). A's error budget could refuse to boot the measured path, which is
the one path that produces publishable numbers; C removes the guard precisely where it matters.
Blocked work: Phase 4 item 5's **canary half only** — provider dispatch itself is unaffected, and
items 2/3/9 proceed against the stub upstream the latency benchmark needs regardless.

---

## Resolved
*(move items here with the ruling + date + ADR link)*

**Q-18 — What counts as a "citation marker" for `numeric_claims`?** — RESOLVED 2026-08-26 by **ADR-025**.
Ruling: **(c)** — written into 04 §2.4.2 as normative, so it is no longer an implementation detail. Lexical only, searched in the numeral's own sentence, case-insensitive: attribution phrases · bracketed numeric reference · parenthetical author-year · URL. Judging whether a citation *supports* the figure stays `rag_grounding`'s job.
**The ruled list is not the provisional one, and the delta moves the FP rate in both directions** — recorded because it is the reason the v2 `numeric_claims` precision is not comparable to v1's on the citation clause alone:
- **Dropped** (stop suppressing → can only raise FP): bracketed author-year `[Smith 2024]`; structural pointers (`section 4`, `clause 12`, `§ 4`, `table 3`); named regulatory documents (`10-K`, `prospectus`, `filing`); the `ref:` / `reference:` / `see:` leaders; `as stated/noted in`.
- **Added** (start suppressing → can only lower FP): `as per`, `cited by`, `based on`, `study by`, `survey by`, `data from`, `figures from`.
The publication gate this question carried is **lifted**: a `numeric_claims` FP/FN figure may now be published, provided it is labelled v1 or v2 per 06 §3.2.

⚠ A marker is **not** a verification. It suppresses only this detector, whose question is "was this figure attributed?" — never "is the attribution true?", which is `rag_grounding`'s independent question. The two are *meant* to disagree on a plausible citation for a figure the context never states; 06 keeps that pair as a control and `test_a_citation_is_not_a_verification` pins it.

*Housekeeping, 2026-08-26:* the caveat above and a `Status: **OPEN**` deadline line reading "before any `numeric_claims` number reaches a report, the README…" were left stranded under **Q-10**'s heading when this question moved to *Resolved*. That line asserted the very gate ADR-025 lifted — the **same stale-gate defect** as `[D2-report-emits-a-q18-publication-gate-adr-025-lifted]`, from the same root cause (a question moved; its dependents did not), in a second file. It is removed under that deviation's ruling rather than filed again, and the caveat it was stranded with is **relocated here, not deleted** — it is unique in the repo and `tests/test_numeric_claims.py::test_a_citation_is_not_a_verification` pins it. Amendment 2's proof machinery is not engaged: this is a markdown doc read by no code, so it cannot move a figure.

**Q-17 — 04 §2 names "Aho-Corasick keyword sets"; the implementation uses a compiled regex alternation.** — RESOLVED 2026-08-26 (MINOR gap, AGENTS.md §6; agent-resolved).
Why: `pyahocorasick` is not a declared dependency, and the documented term source (`blocklist_extra`) ships **empty** in all three policies — so the structure would be carrying zero terms.
Ruling: **compiled regex alternation, sorted longest-first.** The doc names a data structure in a Notes column; the *requirement* is the <2 ms NFR-P-002 budget, and the semantics (leftmost-longest over a fixed term set, word-boundary anchored) are identical at this size. `_compile_terms` is the single seam to swap.
⚠ Offered rather than assumed: if the data structure is considered **normative**, this is a D2 and I will swap the implementation — it is one function, and no other code depends on the choice.

**Q-16 — Who detects `pii.person_data`?** — RESOLVED 2026-08-26 (MINOR gap, AGENTS.md §6; agent-resolved).
Why: the label is in the 04 §1.1 taxonomy and **no 04 §2 row says how to detect it.** It is a category ("employee record", "date of birth"), not a shape a Tier-1 pattern can match.
Ruling: **`tier1_pii` never emits it.** It also has **zero cases in the frozen corpus**, so the omission leaves nothing unmeasured; the label stays in the taxonomy for the policy files that already map it. If it should ever fire, that needs a documented detector row first (doc change), not a regex invented here.

**Q-15 — What is `tier1_blocklist`'s base term list?** — RESOLVED 2026-08-26 (MINOR gap, AGENTS.md §6; agent-resolved).
Why: 04 §2 describes `blocklist_extra` as "per-use-case **extra** terms", wording that implies a base list the docs specify **nowhere**.
Ruling: **there is no base list; `blocklist_extra` is the only term source.** All three shipped policies set it to `[]`, so the detector correctly emits nothing on the documented configuration — wired, budgeted and tested, with no terms to match. Inventing a base list would be writing policy into Python, the AGENTS.md §9.1 trap.
⚠ **Reporting consequence, stated rather than buried:** `security.blocklist` therefore has **zero positives** in the frozen corpus, so this detector's recall is **undefined — not 1.0**. `eval/run_all.py` must report it as no-cases; an empty denominator rendering as a perfect score would be a fabricated number (AGENTS.md §7).

**Q-14 — What does a detector receive as `ctx`?** — RESOLVED 2026-08-26 (MINOR gap, AGENTS.md §6; agent-resolved).
Why: 04 §2 fixes the contract as `async detect(ctx) -> list[Signal]` and **never says what `ctx` holds**, so no detector could be written against it.
Ruling: `DetectorContext` in `detectors/base.py`, containing only what the *documented* rows require — `text` + `stage` (every row), `context_docs` (`rag_grounding`, `numeric_claims`; source `controlplane.context` per 05 §1.1), `conversation_id` (`loop_guard`, `conv_tracker`), and the two policy fields 04 §2/§3 hand to a detector (`blocklist_extra`, `detector_params`).
⚠ Not a 05 addition: 05 governs endpoints, persisted schemas, config keys, metrics and log fields. `DetectorContext` is an internal call shape, none of those.
⚠ Load-bearing detail: **policy values arrive as plain data, never a `Policy` object.** base.py's stated asymmetry is that nothing there reads a policy, and it is what keeps FR-POL-002 true — a detector that could see the label→action map could start deciding actions. The engine projects the two documented fields in, and the detector stays unable to tell which use case it is serving (AGENTS.md §9.1).


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
Supersedes the 2026-08-24 ruling (upstream = Anthropic API / `claude-sonnet-4-6`), which is now moot — including its ⚠ note about that id not matching Anthropic's published naming. That concern was well-founded and the same class of failure is now caught at boot rather than by inspection: FR-GW-006's canary refuses a measured-class boot whose reported token accounting disagrees grossly with a **repo-local estimate** (ADR-028 — the earlier `count_tokens` / `max_token_delta` form of this sentence named a mechanism that ruling withdrew).
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

**Q-04 — Tier-2 model picks (injection + toxicity classifiers)** — **CLOSED 2026-08-28 by ADR-031.**
Original ruling (2026-08-24): **defer the checkpoint choice**; stub the detector interfaces now (`detectors/tier2_classifiers.py`), pick real checkpoints later via the NFR-P-002 latency spike.
Ruling: **`madhurjindal/Jailbreak-Detector`** (injection) and **`martin-ha/toxic-comment-model`** (toxicity), both served on **ONNX Runtime with dynamic int8**. Six published candidates measured by `eval/spike_tier2_models.py` across three backends × five stage-reachable lengths × two thread settings; **selection on latency only**, no corpus label ever read, because picking a model by its score on the frozen fixtures that later measure it is harness-fitting. Eager PyTorch misses the budget for every candidate at the segmenter cap — **not a D3**, since 02 §8 and 04 §2 both specify ONNX and eager was never the documented backend. `protectai/deberta-v3-base-prompt-injection-v2` is rejected despite one FITS row: re-probed on the crossover ladder it measured **36.69 ms P99 at the same 240 characters** it passed at in the sweep (61 vs 50 tokens — the two composers build that length differently), and a verdict that flips on tokenizer detail is *at* the budget, not inside it. Full measurements, the population-correctness fix, and the int8 accuracy disclosure are in **ADR-031**.
⚠ Doc-rot note (now discharged): the original Q-04 said to record the eventual choice "as ADR-011", but ADR-011 is already the `privacy.person` producer decision. The spike result took the **next free ADR number** — **ADR-031**.
⚠ **This closure is not the whole story.** The picks satisfy the budget at every length their stages can *deliver*, but the `input` stage applies no length cap, so `tier2_injection` has reachable inputs it cannot serve in 25 ms. Filed as `[D3-tier2-injection-budget-cannot-hold-on-unbounded-input]` — **OPEN** in the ledger below. Thread sensitivity is logged as **SL-5**.

## DEVIATION REPORT [D5-adr-027-stamp-has-no-column-in-the-05-3-ddl]
Severity: BLOCKER
Doc & section: 05 §3 (`audit_records` DDL) vs 05 §4 (canonical view) and 05 §2
(`escalation_cause`); ADR-027 consequences 2 and 3
The doc says: 05 §4's canonical JSON view carries `"contributing_signal_ids": ["…"],
"failure_record_ids": ["…"]` as top-level keys, and 05 §2 states `escalation_cause` is
"**derived, not stored**: it is computed from the referenced `audit_records.detector_failures_json`
and the step-5 stamp (§4 `contributing_signal_ids` / `failure_record_ids`), so there is one source
of truth for why a verdict happened." ADR-027 consequence 2: the stamp extends to "contributing
signal_ids **+ failure_record_ids**, so an ESCALATE with zero content signals is self-explaining
in the audit."
Reality says: **05 §3's own `audit_records` DDL declares neither column** — it ends at
`sampled_deep`, and `db.py` plus `write_record`'s 19-column `INSERT` are faithful to it. The two
fields exist on the `AuditRecord` dataclass and are populated correctly from the verdict
(`records.py:318-319`), then **silently dropped at the write boundary**. Verified by round-trip
on a fresh DB: `PRAGMA table_info(audit_records)` returns 19 columns, neither list among them,
and `canonical_view()` — which reads back via `SELECT * FROM audit_records` — emits neither key,
despite its docstring calling itself "The 05 §4 canonical JSON view". No test asserts either list
survives a write; the existing coverage
(`test_audit_records.py:258-259`, `test_policy_engine.py:889-912`) stops at the in-memory build,
which is why this reached the write path unnoticed.

**Neither list is recoverable by derivation**, so this cannot be closed by computing them at read
time:
- `detector_failures_json` is populated on **fail_open** too (05 §3, "a dropped detector that left
  no trace is indistinguishable from one that ran and found nothing"), so the presence of a
  failure record does not mean it *contributed*. Filtering on `fail_mode_applied` also misreports:
  ADR-027's floor "lifts a PASS or EDIT to ESCALATE but leaves a genuine content BLOCK standing",
  so a fail_closed record can be present without having decided the verdict.
- `contributing_signal_ids` is a strict subset of `signals_json` by design — pinned by
  `test_contributing_signal_ids_name_only_the_deciding_signals` — so it cannot be reconstructed as
  "all signal ids".
- 05 §2 requires `both` to be "reported as `both` rather than collapsed to either side", which is
  exactly the distinction that needs both lists present.
Impact if we ignore it: 05 §2's `escalation_cause` is unimplementable, taking ADR-027
consequence 3 with it — the reviewer sees "a bare quarantine" rather than "detector `tier2_toxicity`
failed under fail_closed", which the doc calls "the difference between a decision they can action
and one they must reverse-engineer". 05 §3's stated rationale ("Without the second list, that
record and a content escalation are indistinguishable after the fact") describes the state the
schema is currently in. Blocks Phase-4 item 7's review-queue listing. Item 8 (fault injection) is
**not** blocked — ADR-027 consequence 4 reads `detector_failures_json`, which is stored.
Options:
  A) Add two `TEXT` columns to 05 §3's DDL (`contributing_signal_ids`, `failure_record_ids`),
     JSON arrays, written by `write_record` and read by `canonical_view` — trade-off: a schema
     change, and the ids also appear inside `signals_json`/`detector_failures_json`, so the columns
     are a denormalized index. Mirrors the existing `*_json` convention and leaves 05 §4 and §2
     exactly as written.
  B) One `stamp_json` column holding both lists as an object — trade-off: fewer columns, but 05 §4
     shows the two keys at top level, so the view assembly gains a remapping step, and a future
     third id list would silently change the column's shape rather than the table's.
  C) Mark contributing signals inline (a `contributed: true` flag inside `signals_json` and
     `detector_failures_json`) and derive both lists at read time — trade-off: no new columns, but
     it edits the two payloads ADR-027 deliberately keeps as "pure Signals" and pure operational
     records, and the flag is a policy conclusion stored inside a detector's output.
Recommendation: **A** — the smallest change that makes §3 consistent with §4 and §2, it needs no
edit to either consumer's documented shape, and it keeps `signals_json` pure per ADR-027. The
duplication is an index, not a second source of truth: both lists are computed by the engine, and
the DDL is the only place they currently go missing.
Blocked work: Phase-4 item 7's `GET /admin/review?status=pending` (`escalation_cause` +
`failure_summary`). The audit write path itself is unblocked — records write correctly today, minus
the stamp — so items 1, 3, 4 and 6 proceed, and any ESCALATE they record will be missing the stamp
until this is ruled.

## DEVIATION REPORT [D1-tier2-budgets-cannot-coexist-with-nfr-p-001]
Severity: MAJOR
Doc & section: 01 NFR-P-001 (gateway overhead P50 < 40 ms, P99 < 100 ms, streaming pipelines) vs
04 §2 detector registry budgets (`tier2_toxicity` 25 ms at `OUTPUT_SENTENCE`, `tier2_injection`
25 ms at `INPUT`), read together with 06 §4's normative streaming formula.

The doc says: 06 §4 defines streaming `gateway_overhead_ms` as "ingress + input-lane time +
Σ per-sentence hold intervals", a **sum over holds**. 04 §2 budgets each per-sentence detector
individually. NFR-P-001 caps the total at 100 ms P99. Each doc is self-consistent.

Reality says: a per-sentence budget is paid **once per sentence**, so the segment count is a
multiplier on lane cost — and the multiplier is not 1. Measured over the frozen corpus (280
cases, the shipped `Segmentation`): P50 **1** segment, P95 **3**, P99 **6**, max **10**.
Projecting the two unimplemented tier2 detectors at their declared budgets, `rag_grounding`
excluded (no case carries context docs):

| Segments | Sequential (as implemented) | Parallel (02 §4 intent) |
|---|---|---|
| P50 — 1 | 65 ms — under | 50 ms — under |
| P95 — 3 | 133 ms — **breach** | 100 ms — **breach** |
| P99 — 6 | 235 ms — **breach** | 175 ms — **breach** |
| max — 10 | 371 ms — **breach** | 275 ms — **breach** |

It fails under **both** readings, so the finding does not depend on `run_lane` being sequential
today (it is, by the documented measurement decision at `pipeline.py:212`); 02 §4's parallelism
arriving with Tier-2 does not rescue it. The **measured** figures pass with room to spare — the
margin is a derived factor in `reports/latency_report.md`, not repeated here, because a number
copied into doc prose is machine-specific and rots on the next run — which is why this is filed
as a D1 doc-vs-doc contradiction and **not** a D3: there is no observed breach, and reporting a
projection as a measured one would be the fabrication AGENTS.md §7 forbids.

Impact if we ignore it: NFR-P-001 becomes unmeetable the moment FR-DET-002 is satisfied, and the
discovery would land during the tier2 sprint — the point of least schedule slack — rather than
now. The published latency claim would also need withdrawing after the fact, which is worse than
qualifying it in advance.

Options:
  A) Rule NFR-P-001 **per-sentence** rather than per-request, i.e. the hold interval is what the
     budget caps — trade-off: honest to the interception model and to what a user perceives
     (each hold is the delay before *that* sentence appears), but it stops being a whole-request
     guarantee, and a 10-segment response could hold 340 ms in total while every sentence
     "passes".
  B) Keep NFR-P-001 per-request and cut the 04 §2 tier2 budgets to fit the measured P99 segment
     count (~11 ms each at 6 segments) — trade-off: 25 ms was chosen as achievable for a real
     transformer classifier on CPU; 11 ms probably is not, so this risks specifying a detector
     nobody can build, or forcing a smaller model and trading detection accuracy for latency.
  C) Make `run_lane` genuinely parallel by offloading CPU-bound detectors to a thread pool —
     trade-off: helps least of the three (it only closes the sum/max gap, and the parallel column
     above still breaches), adds real complexity to the hot path, and would make each detector's
     recorded `latency_ms` include contention it did not cause.
  D) Scope NFR-P-001 explicitly to the **implemented** detector set and re-baseline it when
     tier2 lands — trade-off: keeps today's measured claim honest and publishable, defers the
     real decision rather than making it, and leaves the target soft at exactly the moment it
     would start to bind.

Recommendation: **A**, with the per-request total reported alongside as an observed figure rather
than a target. It is the only option that neither weakens a budget toward unbuildability (B) nor
defers the contradiction (D), and it matches what the interception model actually promises —
ADR-002 buys sentence-level granularity, so a sentence-level latency guarantee is the one that
follows from it. If A is taken, NFR-P-001's wording needs "per hold interval" and 06 §4 needs a
second reported row for the per-request sum.

Blocked work: nothing today — the benchmark, its report, and the current measured claim all
stand, and `--check` passes. It blocks the **tier2 detector sprint** (FR-DET-002), which should
not begin against a budget set that a ruling may move.

Ruling: **CLOSED 2026-08-27 by ADR-030** — Option A's direction, taken as a front-door
respecification rather than a patch. NFR-P-001 attaches to the **user-perceived hold**; the
per-request sum stays published, untargeted, as `total_attributable_overhead_ms`;
`added_time_to_last_byte_ms` joins it as a measured untargeted row. Targets are **derived from the
04 §2 budgets** in the ADR, and the derivation logged three gaps of its own rather than smoothing
them over — all three now ruled (2026-08-27): **M-18** enrichment capped at 10 ms *aggregate* per
sentence in 04 §2.2, **M-19** a combined 5 ms engine budget with a real measurement behind it, and
**M-20** the two targeted per-hold series emitted and, on 2026-08-28, the untargeted rename, leaving only the
last-byte row. The lane goes parallel **when
Tier-2 lands**, not now — switching earlier would change the conditions of the shipped
measurement. ADR-026 §5's bar on moving an already-missed target is untouched.

---

## DEVIATION REPORT [D3-tier2-injection-budget-cannot-hold-on-unbounded-input]
Severity: MAJOR
Doc & section: 04 §2 registry, `tier2_injection` row ("| `tier2_injection` | input | <25 ms |");
01 §5 NFR-P-002 ("Tier-2 < 25 ms"); 04 §3 `budget.per_request_max_tokens: 4000`
The doc says: `tier2_injection` runs at stage `input` under a **<25 ms** budget. NFR-P-002 states
that budget with **no length qualifier and no concurrency qualifier** — it reads as a property of
the detector, holding for whatever the stage hands it.
Reality says: it holds only up to a length the stage does not enforce. Measured on the ADR-031 pick
(`madhurjindal/Jailbreak-Detector`, ONNX int8, 6 threads, n=30,
`reports/spike_tier2_crossover.json`):

| input | tokens | P50 | P99 | verdict |
|---|---|---|---|---|
| 240 ch | 68 | 8.82 | 14.84 | FITS |
| 400 ch | 104 | 14.27 | 22.80 | FITS |
| 600 ch | 158 | 23.51 | **33.57** | **BREACH** |
| 1000 ch | 247 | 46.88 | **54.82** | **BREACH** |
| 4000 ch | 512 | 95.31 | **99.72** | **BREACH** |

The crossing lies between **400 and 600 characters (104–158 tokens)**; the exact point was not
measured. This is the *fastest* of six candidates — the runner-up breaches at 240 characters — so
no checkpoint choice avoids it.

**Nothing bounds the input length.** Verified rather than assumed: `DEFAULT_MAX_CHARS = 240` bounds
the **output** segmenter only (ADR-002, `sentence_buffer.py`); the request schema declares no
`max_length` on message content; `app.py` sets no body-size cap. `Budget.per_request_max_tokens`
(`policy/schema.py:251`, 04 §3 value 4000) is **read by nothing** — `cost_budget` is still a stub —
and by its own contract it is a *cost* control in the **same input lane**, emitting
`cost.request_too_large`, which is **unmapped in all three shipped policies**. So even fully
implemented it flags concurrently with the classifier rather than gating what the classifier sees.

A second consequence has the same cause: the tokenizer truncates at **512 tokens**
(`max_position_embeddings`), so an injection payload beyond token 512 is **never seen by the
classifier at all**. FR-DET-002's input check is length-limited by construction, independently of
latency.
Impact if we ignore it: NFR-P-002 is silently unmet for a reachable input class, and the miss lands
where it is most expensive — the input lane is fully buffered before dispatch, so this time is
**pure added latency** and feeds ADR-030's `input_hold_ms` target (P50 < 40 / P99 < 50), which a
600-character prompt breaches on the detector alone. It is also an evasion path: padding a prompt
past the crossing degrades the check, and past token 512 removes it.
Options:
  A) **Bound the scored window inside the detector** — score the first N tokens (N set so measured
     P99 < 25 ms; the data puts N ≈ 104), and record truncation on the signal plus a counter —
     trade-off: content past N is unscored, which makes the existing 512-token blind spot larger
     and more common. Bounded and disclosed rather than silent, but it *is* a coverage reduction.
  B) **Window the input and score every window**, taking the max score — trade-off: the 25 ms
     budget is per detector call, so k windows cost ≈k×; it breaks the budget at k ≥ 2 unless the
     windows run concurrently, and 04 §2 has no notion of a chunked detector.
  C) **Enforce a real input length bound before the lane** — implement `per_request_max_tokens` as a
     gate and map `cost.request_too_large` in all three policies — trade-off: repurposes a cost
     control as a safety gate, and rejects long-but-legitimate prompts, which changes the gateway's
     request semantics for every use case.
  D) **Re-scope NFR-P-002 to a stated input envelope** ("<25 ms up to N tokens") — trade-off: honest
     and cheap, but it is a target gaining a qualifier *after* a measured miss, so it needs
     ADR-026 §5's anti-laundering treatment or it reads as tuning the target to the result.
Recommendation: **A**, with the coverage loss logged as a Standing Limitation in the same commit.
It keeps the budget a real bound on the hot path, needs no change to request semantics or to any
policy, and converts a silent degradation into a counted one. C is the right *eventual* answer but
belongs to the cost plane (Phase 6), and D should not be reached for while a measured option holds
the documented number.
Blocked work: the `tier2_injection` implementation — specifically its behaviour on inputs above the
crossing. The **checkpoint choice is not blocked**: ADR-031 stands under every option here, since
the pick is fastest at every length measured. `tier2_toxicity` is unaffected — its stage caps input
at 240 characters, where it measures 8.58 ms P99.


## DEVIATION REPORT [D3-full-coverage-windows-cost-600ms-at-the-policy-bound]
Severity: MAJOR
Doc & section: the `[D3-tier2-injection-budget-cannot-hold-on-unbounded-input]` ruling (2026-08-28,
to become ADR-032), items 2, 3 and 5; 04 §2 `tier2_injection` budget; ADR-030's input-hold target.
The doc says: full coverage via strided windows, MAX over windows; "MEASURE batched ONNX inference
before concluding anything: score all windows in one (or few) batched calls; measure at the policy
bound (`per_request_max_tokens` 4000 ≈ ~50 windows)"; and item 5 — "if batched full coverage
measures grossly unacceptable at the bound (>500 ms class), STOP and report with figures — do not
truncate silently."
Reality says: it is in that class at both thread settings. `eval/spike_window_latency.py`, window
104 tokens / overlap 26 / step 76 (52 windows at the bound), synthetic filler, ONNX int8, P50 ms:

| windows | input tokens | 6 threads seq | 6 threads batched | 1 thread seq |
|---|---|---|---|---|
| 1 | 102 | 11.30 | 11.62 | 49.81 |
| 4 | 330 | 47.20 | 43.52 | 198.00 |
| 8 | 634 | 96.52 | 91.99 | 393.78 |
| 16 | 1546 | 196.19 | 203.88 | 788.30 |
| **52** | **4082** | **651.41** | **800.75** | **2566.68** |

**Batching does not amortise, and past batch=2 it hurts.** Best configuration at the bound is
batch=2 → **599 ms** (8% better than sequential); batch=52 is **801 ms**, *worse* than issuing 52
separate calls. The cause is measurable rather than speculative: a single window at 1 thread costs
49.81 ms and at 6 threads 11.30 ms — a **4.41x** speedup, so ONNX Runtime already spreads one
window across the cores. There is no idle parallelism for a batch to exploit, and batching only
adds a larger tensor to a saturated pipeline. Per-window marginal cost is flat across the whole
ladder (11.30 → 12.53 ms at 6 threads; 49.2 → 49.8 at 1), which is the signature of a
compute-bound stage.

Two checks that this is not a harness artefact. **Cross-validation:** ADR-031's crossover measured
this checkpoint on 104 tokens of *real, ragged* text at 14.27 ms; this harness measures 104 tokens
of *synthetic, padded* text at 11.30 ms — same order, and the padded figure is the conservative one
per window. **Window size is not the lever:** cost per content token is **0.111 ms** at a 104-token
window against **0.187 ms** at 512, because attention is quadratic in sequence length. Smaller
windows are more token-efficient, so no window geometry rescues the bound; full coverage of 4000
tokens is inherently ~52 x ~12 ms.
Impact if we ignore it: a 4000-token prompt pays ~**0.6 s** of input hold with all six cores free,
and ~**2.6 s** under the contention ADR-030's parallel lane creates — on the *input* lane, before
the provider is even called, so it is added latency the user waits through with nothing streaming.
Publishing that as an untargeted length-parametric series (the ruling's item 3) would be honest but
would leave the gateway's own worst case an order of magnitude past every latency figure this repo
currently reports. Silently truncating instead is the one thing both the ruling and AGENTS.md §5.4
forbid.
Options:
  A) **Lower `per_request_max_tokens` in the shipped policies to a measured, stated ceiling** — the
     ruling's item 4 already designates this the per-use-case latency control, so this uses existing
     config rather than new mechanism. Measured ceilings at 6 threads: 634 tokens ≈ 8 windows ≈ 97 ms;
     1546 ≈ 20 windows ≈ 250 ms — trade-off: `cost.request_too_large` is currently **unmapped in all
     three shipped policies**, so mapping it is required and long-but-legitimate prompts start being
     refused; it also repurposes a cost control as a latency gate.
  B) **Accept and publish the scaled figure untargeted**, exactly as the ruling's item 3 specifies,
     with the worst case at the bound stated as 599 ms / 2558 ms — trade-off: no code beyond the
     windowing itself, full coverage preserved, but the published worst case is ~0.6–2.6 s and
     nothing in the product prevents a caller from reaching it.
  C) **Shard windows across cores instead of within them** — the measurement implies this is the more
     efficient use of the same six cores: 6 windows at 1 thread each would complete in ~49.8 ms wall
     (~8.3 ms/window effective) against 11.30 ms/window under intra-op parallelism, projecting ~448 ms
     at the bound — trade-off: **projected, not measured** (I have not run concurrent single-thread
     sessions), it competes for the very cores ADR-030's parallel detector lane needs, and it would
     make SL-5's contention exposure the normal case rather than the pessimistic one.
  D) **Cap by policy AND publish the parametric series** — A for the shipped default, B's disclosure
     for anything above it — trade-off: two mechanisms and two numbers to explain, but no silent
     ceiling and no unbounded hold.
Recommendation: **D**, with A's ceiling set from the measured table rather than chosen. It keeps full
coverage (no evasion recipe, which is what the first ruling bought), keeps the honest worst case
published rather than hidden, and puts the actual limit in per-use-case config where 04 §9 says
thresholds belong — a pipeline that needs 4000-token prompts can raise its own ceiling and accept
the published latency. C is worth measuring before committing to any number, since it would change
the table it rests on, but it should not be adopted on a projection.
Blocked work: **ADR-032 itself.** Its items 1, 2 and 4 are settled and implementable today (window
geometry 104/26/76, MAX aggregation, `window_count` + max-window index in signal meta, policy
ceiling as the per-use-case control). What cannot be written is item 3's budget respecification,
because the figure it would publish is the one this deviation is about. `tier2_injection` is
therefore still blocked; **`tier2_toxicity` is not** — output sentences are segmenter-bounded at 240
characters, one window, 8.58 ms P99.

## DEVIATION REPORT [D1-added-time-to-last-byte-has-no-server-side-vantage]
Severity: MAJOR
Doc & section: 06 §4's normative definition of `added_time_to_last_byte_ms` — "client-observed
last-byte time minus the same request's upstream duration" — read against 05 §3, which places that
key inside `latency_json`, a column **the gateway writes**, and against ADR-030 consequence 3:
"the honest end-to-end quantity, and the one a user's stopwatch would agree with."

The doc says: the row is a *client* observation, and it is persisted per request in the audit
record. 05 §5 lists it in the vocabulary `check_latency_keys` enforces at the write path, and
05 §3's DDL comment marks it "not yet (the last of M-20's remainder)" — i.e. an emission gap, a
thing left to do rather than a thing to decide.

Reality says: the writer has no vantage from which that quantity is observable, on either
delivery path, and the record cannot be amended once written.

- **Buffered path.** `state.audit(...)` is called at `app.py:586`; `return JSONResponse(...)` is
  at `app.py:632`. The body is not serialized, let alone sent, at write time. This ordering is
  not incidental — **M-13** put the write before the return precisely so a crash cannot deliver
  content with no record, so "audit later" reopens a closed gap.
- **Streaming path.** `state.audit(...)` at `app.py:875` follows the final
  `yield f"data: {DONE}\n\n"` at `app.py:869`, but it runs **inside the generator**. A completed
  ASGI `send()` means "handed to the transport", not "received by the client"; the bytes may sit
  in kernel or proxy buffers. The closest honest server-side name for what is knowable there is
  *last-frame handoff*, which is not what the key is called.
- **No second phase exists to carry a post-delivery figure.** The table is insert-only: there is
  no `UPDATE audit_records` anywhere in `controlplane/`. `record_status` is a crash marker
  (`records.py:50`: `partial` "is written ONLY by the crash path"), not a two-phase write.
- **The quantity is already computed, client-side, under another name.**
  `eval/bench_latency.py:237-245` returns `max(0.0, self.wall_ms - self.upstream_ms)` as
  `reference_delta_ms` — 06 §4's formula exactly. But its own field comment (`:221-224`) says
  `wall_ms` "includes `TestClient`'s ASGI transport cost, which is harness overhead a real client
  would not pay", and the report prose (`:810-816`) publishes it as an **upper bound**, "never the
  headline number". So the two cannot simply be equated: 06 §4 asks for an honest figure and the
  existing client-side one is a contaminated bound. That is a ruling, not a rename.

This is filed as a **D1** and not a D3: there is no measured breach, and nothing here is a target.
It is the documented design not being constructible from where the doc puts it.

Impact if we ignore it: the two available failure modes are both bad in a way this repo has
already named. Emitting a server-side handoff delta **under the name
`added_time_to_last_byte_ms`** publishes a number whose label claims a vantage it does not have —
the AGENTS.md §7 problem, and worse here than a missing row, because the name is what a reader
would trust. Leaving it unemitted makes 05 §3's "not yet" permanent and keeps a promise in the
contract that no report can satisfy, which is the doc rot the M-row register exists to prevent.
Untargeted status limits the blast radius but does not remove it: NFR-P-001 keeps its verdict
either way, so this is MAJOR rather than BLOCKER — not on the demo path, no fail-safe implication,
and no other Phase-5 item depends on it. Rounding up would be defensible on the §7 edge alone.

Options:
  A) **Respecify 06 §4 to the server-side quantity** — "last-frame handoff − upstream duration" —
     and emit it, renaming the key to match (`added_time_to_last_handoff_ms` or similar). On the
     buffered path this needs the body serialized before the audit call, which is doable without
     moving the write. Trade-off: emittable and honest **once renamed**; but it silently drops
     network egress to a real client, so it is not the stopwatch figure ADR-030 asked for, and
     ADR-030 consequence 3 has to be amended rather than implemented.
  B) **Withdraw the key from `latency_json` and site the quantity in the benchmark**, where a
     client vantage actually exists, with the transport-cost caveat stated in the row. Trade-off:
     honest vantage, no new key, M-13 untouched, and the code already computes it; but the audit
     record can then never carry an end-to-end figure per request, and the benchmark's version
     needs its `TestClient` overhead either subtracted or disclosed for the row to be more than
     the upper bound it is today.
  C) **Have the client write it** — benchmark/demo harness reports its own last-byte time back
     for the request id. Trade-off: the only option that yields a genuinely client-observed
     per-request number; cost is a second write against an append-only table (a schema change
     AGENTS.md §9.6 constrains) plus client-supplied timing inside an audit record, which is a
     trust boundary this repo has not crossed anywhere else.
  D) **Leave it documented and unemitted.** Trade-off: zero work and zero risk of a mislabelled
     number; the contract keeps a row nothing produces, indefinitely.

Recommendation: **B.** It is the only option that neither labels a quantity as something it is not
(A), nor puts unverifiable client timing into the audit record (C), nor leaves the contract
promising a row forever (D) — and the vantage question answers itself: the benchmark *is* a
client, and the gateway is not. The disclosure work it implies is smaller than the rename A forces
through ADR-030.

Blocked work: **item 10's second half — the whole of M-20's remainder.** Nothing else waits on it:
the row is untargeted, so NFR-P-001's verdict, `--check`, and every other Phase-5 item are
unaffected.
