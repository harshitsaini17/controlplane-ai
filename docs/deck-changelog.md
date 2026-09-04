# Deck changelog — `b24bb1029_ControlPlane.pptx`

Rebuild of the Round-2 business-proposal deck onto the design system in
`DESIGN-controlplane-deck.md` v1.0. One row per finding: what was wrong, which slides
changed, and where the replacement number or claim comes from.

**Scope rule applied throughout (AGENTS.md §7):** no number appears in this deck unless a
committed report or doc in this repo produces it, and no unflattering number was removed.
Where a claim could not be sourced it was **cut and logged**, never softened into vagueness
that keeps the claim alive.

- Canvas 20 × 11.25 in (18288000 × 10287000 EMU). 30 slides.
- Locked template shell retained on slides 1 (cover), 2 (team), 5 and 9 (the two mandated
  200-word slides), 29 (video), 30 (thank you). The template's
  *"Instructions — remove before submission"* slide is **deleted**.
- Fonts: Arial 489 runs, Courier New 211 runs, nothing else. Em/en dashes: zero.
- QA renders in `reports/deck-render/slide-01.png` … `slide-30.png`. **These are QA
  artifacts — do not cite them.**

---

## Content findings

| # | Finding | Slide(s) | What changed | Source of the replacement |
|---|---|---|---|---|
| **C1** | Old slide 11 described a **cut** mechanism: a three-plane fan-out resting on `fast_consistency`. | 11 | Rebuilt around what ships: **one multi-label signal** carrying `hallucination.ungrounded_claim` + `privacy.person`, converged by the engine's most-severe rule. The three-plane fan-out is not kept even as a labelled target — that would keep a cut claim alive. | `docs/08-open-questions.md` SL-6 (`fast_consistency` CUT) and SL-7 (grounding band *inverts at 5 of 5 reshuffle seeds*); ADR-011, ADR-019; `docs/04-policy-and-detection-spec.md` §1.1 |
| **C2** | **"Tiered routing" claimed as shipped.** The cascade router is not built. | 9, 14, 20, 24 | Reworded everywhere to *"budget gate ships and enforces; cascade router is P1."* Ladder redrawn: Rungs 1–2 carry green `SHIPS` verdict dots, **Rung 3 is a hairline-outlined roadmap node** with a purple `ROADMAP` dot and text naming SL-10. | `docs/08-open-questions.md` SL-10 (cascade router not built; `f` has no producer; `cascade_escalated` is a column nothing writes); `controlplane/gateway/pipeline.py`; ADR-013 |
| **C3** | **Stale status, understated in our own favour** — "six live detectors", "cost-plane enforcement detectors are stubs". | 16 | Corrected **upward**: 8 of the 11 `docs/04` §2 rows run in the gateway; 5 of 11 are scored (`rag_grounding` ships deliberately unscored); the **cost plane enforces**; `fast_consistency` is the one cut to roadmap; console implemented; demo runner 7 pass / 2 skipped / 0 fail under `--replay`; genuinely not implemented: `pii_leak_scan` harness and the Streamlit dashboard. | `docs/09-engineering-notes.md` §Build status (:29, :32, :36, :38, :39, :40, :41, :184) |
| **C4** | **Fault injection reported one-sided** (only the flattering in-process result). | 18, 26 | Both measurements ship, labelled by what each measures: in-process `--reps 5` → **5/5 repetitions at 39/39** (warmed steady state, one shared model pool); five **separate** processes → **3/5 clean, two at 38/39** on the same control-probe assertion (cold path). **39/39 never appears alone.** Travelling disclosures also on-slide: coverage is **3 of 4** fault classes (`cost` has no live carrier, so **untested, not met**); `tier1` cannot show a contrast (all three policies set `fail_closed`); root cause **M-60** named rather than tuned away, and the assertion was **not relaxed**. | `docs/09-engineering-notes.md`:191; `reports/fault_injection_report.md`:152, :154; regenerate with `python -m eval.fault_injection` |
| **C5a** | **`7/7 injected defects caught`** — a conflation of two unrelated facts, and it reused an *unflattering* number as a flattering one. | 17 | Split and corrected. **`5/5` mutation classes** the policy matrix is required to disagree with. The separate `7/7` is the **residual PII miss** count (the documented bare-7-digit scope exclusion) and is stated as such on the same slide. | `tests/test_policy_matrix.py` carries exactly five `test_mutation_*` functions (:95 ADR-012 band scoping, :103 ADR-019 enriched-label, :126 ADR-015 span-less promotion, :138 severity order, :148 label-action map), matching the five named at `reports/eval_report.md`:196-202. The `7/7`: `docs/09-engineering-notes.md`:85, ADR-026 §3 |
| **C5b** | **"1,200+ tests"** — a literal count this repo deliberately refuses to print, and inflated besides. | cut from 3 tiles | **Cut.** Replaced by the citable claim: CI verifies on Python 3.12 and 3.14. | `docs/08-open-questions.md` M-23 (removed the literal suite count from judge-facing material *and* added a guard keeping literal 3-digit counts out); `.github/workflows/ci.yml`:57-65 |
| **C5c** | **"two machines" / "Apple Silicon"** in the latency method. | cut | **Cut — no source anywhere** in `docs/`, `reports/`, `README.md` or `.github/`. CI is one platform. Only the Python-version matrix survives, because only it is citable. | `.github/workflows/ci.yml`:54 (`runs-on: ubuntu-latest`) |
| **C5d** | **`0.133 ms`** sourced but under-specified — a bare number with no method beside it. | 18 | Always rendered as **`P99 0.133 ms · n=583`**, never bare. | `reports/latency_report.md`:81 (`tier1_pii`, budget 2 ms, n=583, P50 0.053 / P95 0.093 / P99 0.133 / max 0.266); regenerate with `python -m eval.bench_latency` |
| **C6** | **Brief coverage gaps** — bias, multi-turn/agent risk, geography — unaddressed. | 16, 25 | One honest line each. *Bias:* nothing ships; charter references bias only as an annual-audit concern. *Multi-turn/agent:* `conv_tracker` is specified but is **not** among the 8 rows that run (P2); charter **NG6** declines full agentic action gating by design. *Geography:* *"carried as policy metadata for audit; no mapping keys read it yet"* — **no per-jurisdiction behaviour is claimed**. | `docs/00-charter.md`:11, NG6 :42, A4 :50; `docs/01-requirements-and-scenarios.md`:51 (`FR-CFG-003` is P1); `docs/04-policy-and-detection-spec.md`:301 (`geography: EU  # metadata`); ADR-021 |
| **C7** | **Reference tags resolved nowhere** — 25 `[B-nn]`/`[M-nn]` tags in use with no key in the deck. | 27 (new) | One references slide, two hairline-separated columns, 14 pt, presented as a single reference block (**approved decision 1**). Tag hygiene verified: 25 used, 26 defined, **zero used-but-undefined**; `B-03` defined and unused. | Proposal appendix provenance table, `b24bb1029_ControlPlane_Business_Proposal_FINAL.md`:645-652 |
| **C8** | **No product image** — nothing showed the thing running. | 13 | Real `/console` captured from a **live gateway on port 8099** (never 8000 — `kiro-local`'s `base_url` is `localhost:8000`, so the gateway would proxy to itself). `playwright` is absent; `/usr/bin/chromium` is present and the console is static HTML served same-origin, so it was captured headless. **The live counters read 0 and that is the correct artifact to ship.** Driving traffic to populate them was attempted and abandoned: `create_app`'s `active_provider` is `kiro-local`, **dev class**, which ADR-018 forbids in judge-facing figures, and this provider's non-streaming `input_tokens` carries a fixed offset, so its counters are not measurements. No `console-mockup` fallback and no "values illustrative" caveat was needed — the values are **absent rather than invented**. | `controlplane/gateway/app.py`:633; `config/gateway.yaml`:58, :185; ADR-018. Reproduce: `.venv/bin/uvicorn --factory controlplane.gateway.app:create_app --port 8099` then `chromium --headless --screenshot=… http://localhost:8099/console/dashboard.html` |
| **C9** | **Placeholder team photos.** | 2 | Template placeholders **retained unchanged**. No team photos exist in the repo (no `assets/`; the only images are `docs/diagrams/images/*` and `scripts/readme_pdf/*`). **Nothing fabricated.** The three remaining "Photo" strings on slide 2 are the template's own and are deliberate. Open item: **TODO photos**. | — (absence verified by search) |
| **C10** | **Density** — one old slide carried two tables; tables ran past five rows and under 14 pt. | 17, 18 (split), 26 | Old slide 21 split into 17 and 18. **No table over five rows or under 14 pt anywhere.** Risks trimmed to five rows with the remainder cited to the proposal appendix. Verified: zero runs below 10 pt deck-wide. | `DESIGN-controlplane-deck.md`:297 (minimum 14 pt tables, 12 pt footers, nothing below 10 pt) |
| **C11** | **New finding, raised during figure verification.** `840/840` is real but **misquoted**. `reports/eval_report.md`:153 makes the A/B split normative — *"they answer different questions and neither may be quoted as the other"* — and the old deck offered this §A *perfect-detection-assumed* figure as support for end-to-end claims ("prevent incidents rather than discover them", "verdicts correct on a frozen corpus"). | 3, 17, 28 | Every §A citation now carries **`perfect detection assumed`** inline. End-to-end claims cite **§B** instead: `165/194`, `165/194`, `160/194` = **0.851 / 0.851 / 0.825**. | `reports/eval_report.md`:157 (§A, `280/280 agree (1.000)` per policy), :153 (the normative split), :203-250 (§B); `docs/09-engineering-notes.md`:97 |

### Carried unflattering, deliberately

| Claim | Slide(s) | Why it stays |
|---|---|---|
| `tier2_injection` **P99 25.348 ms against a 25 ms budget — BREACH** | 18, 26 | A measured NFR-P-002 miss. Published, not tuned away. `reports/latency_report.md`:82, :124; SL-8 |
| **NFR-EVAL-001: MISSED** — `tier1_pii` recall 0.836 blind / 0.885 revised against a 0.95 target, target unmoved | 17, 19 | SL-1. A real unmet target, reported on first contact. `reports/eval_report.md`; `python -m eval.run_all` |
| `tier2_injection` recall **0.150**, `tier2_toxicity` high-band recall **0.250**, both reported blind and untuned | 17, 26 | Blind first contact; no threshold was moved to improve them. `reports/eval_report.md` |
| `numeric_claims` precision 0.267 → 0.857 by **deleting a rule, not tuning** | 17 | ADR-025; recall stayed flat at 0.750 |
| **9 standing limitations** open | 16, 19 | 10 SL rows, SL-4 closed |
| **No absolute cost-savings figure** | 24 | The cascade router that would produce it is roadmap. Quoting a number we have not measured would break the rule the rest of the deck follows |

---

## Visual findings

| # | Finding | Slide(s) | What changed | Verification |
|---|---|---|---|---|
| **V1** | Callout overlapped a table on old slide 25. | 17, 18 | Slide split (see C10); stat tiles sit below the table on their own band, no overlap. | Geometry check + render inspection, zero overlaps |
| **V2** | Banner overlapped the last table row on old slide 30. | 26 | Table trimmed to five rows; no banner. Nothing overlaps. | Render inspection |
| **V3** | Old slide 33: tagline collided with ask #3, and `A100FF` on ink was unreadable. | 28 | Ask rebuilt as three cards with the close *"We built it, and it runs."* clearing them. Kicker and numerals use **`accent-light` `C77DFF`** on ink. | Contrast probe over all dark grounds: **59 runs, worst 4.61:1, `C77DFF` only — `A100FF` appears on no dark ground anywhere** |
| **V4** | Purple fills / purple headers / purple text on dark on content slides. | all | **0 real violations.** The 7 purple fills that exist are all ≤0.12 in **verdict dots**, which the design system explicitly permits. | Deck-wide fill and colour scan |
| **V5** | Bold titles, underlines, accent bars, drop shadows, zebra striping, verdicts as filled colour blocks. | all | **0 violations.** Verdicts render as `verdict-chip`s — a dot plus thin outline, never a filled block. PASS green, EDIT blue, BLOCK ink, ESCALATE purple. Four verdicts merged into the signature slide (**approved decision 2**). | Deck-wide scan |
| **V6** | Every content slide needs a mono kicker, an evidence footer wherever a number appears, and nothing below y = 9.9 in. | all | Satisfied. **Zero body-content items below y = 9.9 in.** The 76 shapes in that band classify as 28 page numbers, 25 template copyright lines, 22 evidence footers (the design system *places* these at y = 10.35), and one template-inherited *"All fields are mandatory"* on slide 2 — identical name, coordinates and size in the untouched template, differing only by the sanctioned font substitution. | Classifier over every shape with `top > 9.9in`; `DESIGN-controlplane-deck.md`:356 |
| **V7** | No slide over ~60 % or under ~35 % body fill; move content between slides rather than shrinking type. | 5, 9 | Slides 5 and 9 had a **18.5 in body measure at 16 pt** — ~142 characters per line, bottoming out at y = 4.74 with two-thirds of the slide empty. Rebuilt at the design system's **12 in cap with `body-large` 20 pt**: ~85 characters per line, ending at y ≈ 7.3. **Type grew rather than shrank.** | `DESIGN-controlplane-deck.md`:151 (`lede.width: "≤ 12in"`); wrap measured with Liberation Sans (metric-compatible with Arial) before the change |

### Two defects found by the render pass that geometry checking could not see

| Defect | Slide(s) | Cause and fix |
|---|---|---|
| **All 24 content-slide backgrounds were silently dropped in the merge** — the five ink dividers and the green product band shipped **white text on white**. | 4, 8, 13, 15, 20, 28 | `set_background()` in `scripts/merge_deck_v2.py` searched for `p:bg` one level too high. `p:bg` is a child of `p:cSld`, never of `p:sld`, so the lookup returned `None` for every slide and the function returned early every time. Fixed, plus schema-order handling (`p:bg` must precede `p:spTree`) and a **transfer-count assertion** that now fails the build if any background does not carry across. |
| **Team-slide roll numbers were unreadable** — grey on the template's dark-green hill art. | 2 | The roll number was a second line inside the picture-filled name plate. Moved to the white detail block below, where it measures 21:1 / 5.3:1. The plate is BOTTOM-anchored, so a spacer line was required: dropping the line outright slid the names off the light sky band and into the green. |

---

## Verification performed

| Gate | Result |
|---|---|
| `python <pptx-skill>/scripts/office/validate.py b24bb1029_ControlPlane.pptx --original assets/AIC_Talent-Brand_PPT-Template.pptx` | **All validations PASSED!** |
| Every slide rendered and **visually inspected** (all 30) | Zero overflow, zero overlap, zero contrast defects, zero leftover placeholders beyond the deliberate C9 ones |
| Layout-defect scan | **1 flagged: slide 30 "Thank you", 120 pt in a 1.43 in box.** Proved **inherited** — the group is byte-identical to the template's own thank-you slide (modulo the sanctioned font substitution) and the untouched template renders the identical overflow and the identical stray white box |
| Slide 30 contrast, measured from rendered pixels | Title `FFFFFF` 25.5 pt bold **4.78:1**, subtitle `E6BFFF` 18 pt **3.02:1** against the lightest gradient pixel (13.05:1 and 8.24:1 against the modal ground). Both clear the 3.0:1 large-text threshold |
| Fonts | Arial 489, Courier New 211, **nothing else** |
| Em / en dashes | **zero** |
| Runs below 10 pt | **zero** |
| Slide count / filename / instruction slide | 30 slides ≤ 30; `b24bb1029_ControlPlane.pptx` per the template's `Team name_Idea Name.pptx`; instruction slide **removed** |
| Locked shell slides byte-compared against the template | Slides 5, 9 title groups and slide 29 verified structurally identical (modulo the font substitution) |

**Files this task changed:** `b24bb1029_ControlPlane.pptx`, `docs/deck-plan.md`, this file,
`reports/deck-render/*.png` (the brief's mandated QA artifacts), and the deck build scripts
under `scripts/`. Nothing under `eval/`, `controlplane/`, or `docs/0*.md` was modified.

---

## Could not source or fix — three items, flagged rather than papered over

1. **The demo video.** `README.md`:159 — *"Demo video: not present in the repository yet."*
   The mandated Video slide (29) keeps the template's own art and carries no URL. **No link
   was invented.**
2. **Team photos.** None exist in the repo. The template's three "Photo" placeholders on
   slide 2 stay as they are. **Nothing fabricated** (C9).
3. **Tooling gaps in this environment, which changed the QA route.** `markitdown` is not
   installed — the old deck was extracted with python-pptx instead. **LibreOffice is
   absent**, so the brief's PDF → PNG route was unavailable; rendering went through the
   repo's existing chromium + SVG path (`scripts/render_check.py`) straight to
   `reports/deck-render/slide-NN.png`. That renderer measures text with **Liberation Sans**,
   metric-compatible with Arial but not identical, and it does not resolve gradient fills
   or every glyph (the `₹` on slide 7 renders with a wide gap that is **not** in the text —
   verified as U+20B9 followed by a single space). Slide geometry, colour and contrast
   conclusions hold; exact glyph rasterisation in PowerPoint may differ slightly.
