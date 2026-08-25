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


⚠ A marker is **not** a verification. It suppresses only this detector, whose question is "was this figure attributed?" — never "is the attribution true?", which is `rag_grounding`'s independent question. The two are *meant* to disagree on a plausible citation for a figure the context never states; 06 keeps that pair as a control and `test_a_citation_is_not_a_verification` pins it.
Deadline: before any `numeric_claims` number reaches a report, the README, the proposal or the video. Status: **OPEN**

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
| `[D3-tier1-pii-recall-below-target]` | **MAJOR** | Step 4 | **OPEN** — measured micro recall **0.8361** vs NFR-EVAL-001 target 0.95. Precision 1.000 (zero FPs). 10 misses, all pattern-coverage gaps: 8 `pii.phone`, 2 `pii.api_key` |
| `[D8-numeric-claims-treats-identifiers-as-statistics]` | **MAJOR** | Step 4 | **OPEN** — measured precision **0.267** (33 FPs, 30 of them `PII-*` cases). The documented "large-number" clause matches digit runs inside SSNs, cards and phone numbers |
| `[D2-detector-params-cannot-hold-list-values]` | MINOR | ADR-025 | **OPEN** — ADR-025 makes `units`/`citation_markers` overridable via `detector_params`, but the schema types it `dict[str, dict[str, float]]`, which cannot hold a list of strings. No work blocked: 04 §2.4 lists are normative meanwhile |
| `[D1-citation-marker-per-matches-the-rate-preposition]` | **BLOCKER** | ADR-025 impl | **OPEN** — the ruled marker list contains the bare token `per `, which is the ordinary English *rate* preposition, so `$4 million per year` emits nothing. 2 corpus cases labelled `unsourced_numeric` are suppressed. **Gates the single permitted re-measurement** |
| `[D2-nanp-n-constraint-rejects-nothing-as-composed]` | **MAJOR** | ADR-026 impl | **OPEN** — 04 §2.5 claims the NANP `N ∈ [2-9]` narrowing "rejects the digit runs that would otherwise false-positive"; v1's retained `_PHONE` runs first and claims the same extent, so the constraint rejects nothing in the composed detector |
| `[D2-adr-026-eyj-derivation-is-arithmetically-wrong]` | MINOR | ADR-026 impl | **OPEN** — ADR-026 justifies the `eyJ` anchor as "the base64url encoding of `{\"`". It is not: that encodes to `eyI=`. The anchor is still spec-derived, by a different derivation. Conclusion survives; stated reason does not |

**Open: six.** Two are the Step-4 measured findings (D3, D8), **both ruled** (ADR-025/026) and
awaiting the re-measurement that closes them per ADR-026 §5. One is the `detector_params`
schema-type mismatch found while applying ADR-025. The remaining **three were found by writing
the ADR-026 spec-derived tests** — which is the outcome that discipline exists to produce: tests
authored from the specifications rather than from the fixtures caught two defects in the ruled
specs themselves and one in my own reading of them, before any number was computed.

**One of the three, `[D1-citation-marker-per-matches-the-rate-preposition]`, gates the
re-measurement and is why it has not been run.** ADR-026 §5 permits exactly one re-measurement
and forbids touching the harness afterwards, so running it against a marker list with a known
false-negative hole would bake two guaranteed misses into a permanent number. Halting is
cheaper than a number nobody can revise. The Step-4 findings were **measured, not predicted** —
they are the eval harness doing its job on its first real run. Full reports below.

Also still gating, tracked as questions rather than deviations: **Q-10** (no genuinely local
model installed — fallback and 2nd-sample duty unassigned) and the Groq price-provenance caveat
under Q-02, which constrains what the cost simulation may publish rather than blocking it.
**Q-18's publication gate is lifted** — ADR-025 made the citation-marker list normative in
04 §2.4.2, so a `numeric_claims` figure may now be published if labelled v1 or v2 (06 §3.2).

---

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

## Resolved
*(move items here with the ruling + date + ADR link)*

**Q-18 — What counts as a "citation marker" for `numeric_claims`?** — RESOLVED 2026-08-26 by **ADR-025**.
Ruling: **(c)** — written into 04 §2.4.2 as normative, so it is no longer an implementation detail. Lexical only, searched in the numeral's own sentence, case-insensitive: attribution phrases · bracketed numeric reference · parenthetical author-year · URL. Judging whether a citation *supports* the figure stays `rag_grounding`'s job.
**The ruled list is not the provisional one, and the delta moves the FP rate in both directions** — recorded because it is the reason the v2 `numeric_claims` precision is not comparable to v1's on the citation clause alone:
- **Dropped** (stop suppressing → can only raise FP): bracketed author-year `[Smith 2024]`; structural pointers (`section 4`, `clause 12`, `§ 4`, `table 3`); named regulatory documents (`10-K`, `prospectus`, `filing`); the `ref:` / `reference:` / `see:` leaders; `as stated/noted in`.
- **Added** (start suppressing → can only lower FP): `as per`, `cited by`, `based on`, `study by`, `survey by`, `data from`, `figures from`.
The publication gate this question carried is **lifted**: a `numeric_claims` FP/FN figure may now be published, provided it is labelled v1 or v2 per 06 §3.2.

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
