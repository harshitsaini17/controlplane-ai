// Content slides for b24bb1029_ControlPlane.pptx, on the DESIGN-controlplane-deck.md system.
// Emits a staging deck; scripts/merge_deck_v2.py copies these shape trees into the locked
// template package. Slide numbers passed to shell() are FINAL deck positions.
// Every figure here is verified in docs/deck-plan.md (Addendum). No em-dashes (U+2014).
const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.defineLayout({ name: "AIC", width: 20, height: 11.25 });
pres.layout = "AIC";

const C = {
  canvas: "FFFFFF", ink: "17171C", body: "212121", green: "003C33", stone: "EEECE7",
  hair: "D9D9DD", muted: "93939F", slate: "75758A", bodyMuted: "616161",
  accent: "A100FF", accentLight: "C77DFF", onDarkSub: "B9B9C2",
  pass: "1F7A4D", edit: "1863DC", block: "17171C", esc: "A100FF",
};
const F = "Arial", M = "Courier New";
const MARGIN = 0.75;

function shell(slide, n, dark) {
  slide.addText("Copyright © 2026 Accenture. All rights reserved.", { x: 13.2, y: 10.7, w: 5.6, h: 0.3, fontFace: F, fontSize: 10, color: dark ? C.onDarkSub : C.muted, align: "right", isTextBox: true, margin: 0 });
  slide.addText(String(n), { x: 18.9, y: 10.7, w: 0.35, h: 0.3, fontFace: F, fontSize: 10, color: dark ? C.onDarkSub : C.muted, align: "right", isTextBox: true, margin: 0 });
}
function kicker(slide, text, dark) {
  slide.addText(text.toUpperCase(), { x: MARGIN, y: 0.75, w: 12, h: 0.3, fontFace: M, fontSize: 12, bold: true, charSpacing: 1.5, color: dark ? C.accentLight : C.accent, isTextBox: true, margin: 0 });
}
function title(slide, text, dark, w = 14) {
  slide.addText(text, { x: MARGIN, y: 1.1, w, h: 1.1, fontFace: F, fontSize: 40, charSpacing: -1, color: dark ? "FFFFFF" : C.ink, isTextBox: true, margin: 0, valign: "top" });
}
function lede(slide, text, dark, w = 12) {
  slide.addText(text, { x: MARGIN, y: 2.35, w, h: 0.8, fontFace: F, fontSize: 20, color: dark ? C.onDarkSub : C.bodyMuted, isTextBox: true, margin: 0, valign: "top" });
}
function footer(slide, parts, dark) {
  const runs = [];
  parts.forEach((p, i) => {
    runs.push({ text: p.t, options: { fontFace: p.mono ? M : F, fontSize: 12, color: dark ? C.onDarkSub : C.muted } });
    if (i < parts.length - 1) runs.push({ text: "  ·  ", options: { fontFace: F, fontSize: 12, color: dark ? C.onDarkSub : C.muted } });
  });
  slide.addText(runs, { x: MARGIN, y: 10.3, w: 17, h: 0.3, isTextBox: true, margin: 0 });
}
function statTile(slide, x, y, w, num, label, ref, dark) {
  const h = 2.1;
  slide.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.12, fill: { color: dark ? "23232A" : C.stone }, line: { color: dark ? "23232A" : C.stone, width: 0 } });
  slide.addText(num, { x: x + 0.35, y: y + 0.22, w: w - 0.7, h: 0.85, fontFace: F, fontSize: 44, charSpacing: -2, color: dark ? "FFFFFF" : C.ink, isTextBox: true, margin: 0, valign: "top" });
  slide.addText(label, { x: x + 0.35, y: y + 1.05, w: w - 0.7, h: 0.66, fontFace: F, fontSize: 14, color: dark ? C.onDarkSub : C.bodyMuted, isTextBox: true, margin: 0, valign: "top" });
  slide.addText(ref, { x: x + 0.35, y: y + 1.74, w: w - 0.7, h: 0.28, fontFace: M, fontSize: 11, bold: true, charSpacing: 1.5, color: C.muted, isTextBox: true, margin: 0 });
}
function chip(slide, x, y, verdict, color, w = 2.2) {
  slide.addShape(pres.ShapeType.roundRect, { x, y, w, h: 0.42, rectRadius: 0.21, fill: { color: "FFFFFF" }, line: { color: C.hair, width: 1 } });
  slide.addShape(pres.ShapeType.ellipse, { x: x + 0.2, y: y + 0.15, w: 0.12, h: 0.12, fill: { color }, line: { color, width: 0 } });
  slide.addText(verdict, { x: x + 0.42, y, w: w - 0.5, h: 0.42, fontFace: M, fontSize: 12, bold: true, charSpacing: 1.5, color: C.ink, isTextBox: true, margin: 0, valign: "middle" });
}
function hairTable(slide, x, y, colW, header, rows, opts = {}) {
  const rowH = opts.rowH || 0.55;
  const total = colW.reduce((a, b) => a + b, 0);
  let cx = x;
  header.forEach((h, i) => {
    const hp = (i > 0 && (opts.align?.[i] || "left") === "left") ? 0.35 : 0;
    slide.addText(h.toUpperCase(), { x: cx + hp, y, w: colW[i] - hp, h: 0.35, fontFace: M, fontSize: 11, bold: true, charSpacing: 1.5, color: C.slate, isTextBox: true, margin: 0, align: opts.align?.[i] || "left", valign: "middle" });
    cx += colW[i];
  });
  slide.addShape(pres.ShapeType.line, { x, y: y + 0.38, w: total, h: 0, line: { color: C.ink, width: 0.75 } });
  rows.forEach((r, ri) => {
    const ry = y + 0.45 + ri * rowH;
    let rx = x;
    r.forEach((cell, ci) => {
      const isObj = typeof cell === "object" && cell !== null && !Array.isArray(cell);
      if (isObj && cell.chip) chip(slide, rx, ry + 0.07, cell.chip, cell.color, 2.3);
      else {
        const pad = (ci > 0 && (opts.align?.[ci] || "left") === "left") ? 0.35 : 0;
        slide.addText(isObj ? cell.text : cell, { x: rx + pad, y: ry, w: colW[ci] - pad, h: rowH, fontFace: isObj && cell.mono ? M : (opts.mono?.[ci] ? M : F), fontSize: opts.pt || (ci === 0 ? 15 : 14), color: C.body, isTextBox: true, margin: 0, align: opts.align?.[ci] || "left", valign: "middle" });
      }
      rx += colW[ci];
    });
    slide.addShape(pres.ShapeType.line, { x, y: ry + rowH, w: total, h: 0, line: { color: C.hair, width: 0.75 } });
  });
}
function card(slide, x, y, w, h, label, head, bodyText, opts = {}) {
  slide.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.12, fill: { color: opts.fill || "FFFFFF" }, line: { color: opts.stroke || C.hair, width: 1 } });
  if (label) slide.addText(label.toUpperCase(), { x: x + 0.35, y: y + 0.28, w: w - 0.7, h: 0.3, fontFace: M, fontSize: 11, bold: true, charSpacing: 1.5, color: opts.labelColor || C.slate, isTextBox: true, margin: 0 });
  if (head) slide.addText(head, { x: x + 0.35, y: y + 0.66, w: w - 0.7, h: opts.headH || 0.8, fontFace: F, fontSize: opts.headPt || 28, charSpacing: -1, color: opts.headColor || C.ink, isTextBox: true, margin: 0, valign: "top" });
  if (bodyText) slide.addText(bodyText, { x: x + 0.35, y: y + (opts.bodyY || 1.55), w: w - 0.7, h: h - (opts.bodyY || 1.55) - 0.3, fontFace: F, fontSize: opts.bodyPt || 15, color: opts.bodyColor || C.bodyMuted, isTextBox: true, margin: 0, valign: "top", lineSpacingMultiple: 1.12 });
}
function divider(slide, num, head, sub) {
  slide.background = { color: C.ink };
  slide.addText(num.toUpperCase(), { x: MARGIN, y: 6.2, w: 12, h: 0.35, fontFace: M, fontSize: 12, bold: true, charSpacing: 1.5, color: C.accentLight, isTextBox: true, margin: 0 });
  slide.addText(head, { x: MARGIN, y: 6.7, w: 16, h: 2.3, fontFace: F, fontSize: 60, charSpacing: -2, lineSpacingMultiple: 1.0, color: "FFFFFF", isTextBox: true, margin: 0, valign: "top" });
  if (sub) slide.addText(sub, { x: MARGIN, y: 9.1, w: 15, h: 0.6, fontFace: F, fontSize: 20, color: C.onDarkSub, isTextBox: true, margin: 0 });
}
function rule(slide, y, w = 18.5) {
  slide.addShape(pres.ShapeType.line, { x: MARGIN, y, w, h: 0, line: { color: C.hair, width: 0.75 } });
}
const S = () => { const s = pres.addSlide(); s.background = { color: C.canvas }; return s; };

// ── 3. Executive summary (Evidence)
{
  const s = S();
  kicker(s, "Executive summary");
  title(s, "Oversight that ships, measured on its own misses.");
  lede(s, "One base-URL change puts every response through three planes of detection and exactly one policy verdict, before the user sees a word.");
  const tiles = [
    ["840/840", "policy verdicts correct, 280 frozen cases × 3 policies, perfect detection assumed", "[B-01]"],
    ["0.885", "tier-1 PII recall against a 0.95 target: missed, target unmoved", "[B-02]"],
    ["0.133 ms", "tier1_pii P99 at n=583, against a 2 ms budget", "[B-05]"],
    ["25.348 ms", "tier2_injection P99 against 25 ms: a breach we published", "[B-05]"],
  ];
  tiles.forEach((t, i) => statTile(s, MARGIN + i * 4.7, 3.45, 4.3, t[0], t[1], t[2]));
  hairTable(s, MARGIN, 6.05, [6.0, 6.2, 6.3],
    ["What is claimed", "What backs it", "How to reproduce"],
    [
      ["Policy governs, code does not", "A test fails if any use-case name reaches executable code", { text: "python -m eval.run_all", mono: true }],
      ["Verdicts land before delivery", "Sentence-buffered interception, input and hold percentiles", { text: "python -m eval.bench_latency", mono: true }],
      ["Failure posture is per use case", "Fault injection asserts every exercisable fail_mode class", { text: "python -m eval.fault_injection", mono: true }],
      ["Nothing here is a seed value", "Matrix pinned invariant across four threshold bands", { text: "pytest tests/test_policy_matrix.py", mono: true }],
    ], { rowH: 0.6 });
  footer(s, [{ t: "Source: reports/eval_report.md, reports/latency_report.md" }, { t: "[B-01] [B-02] [B-05]", mono: true }]);
  shell(s, 3);
}

// ── 4. Divider
{ const s = pres.addSlide(); divider(s, "01  ·  The problem", "Nothing supervises the AI\nat the moment it speaks.", "Observability reports after delivery. Guardrails filter one category. Neither decides."); shell(s, 4, true); }

// ── 6. Three failures, one root cause (Evidence)
{
  const s = S();
  kicker(s, "01 · The problem");
  title(s, "Three different failures. One identical root cause.");
  lede(s, "A bank runs three AI assistants. Three teams find three incidents, weeks later, in three different systems.");
  const cards = [
    ["Performance plane", "WRONG", "The customer chatbot states a loan approval that never happened. Found in a complaint, not a dashboard."],
    ["Responsibility plane", "LEAKY", "The HR assistant repeats an employee's phone number into a transcript that is retained."],
    ["Cost plane", "EXPENSIVE", "The advisory tool loops on a malformed integration and burns inference budget for a week."],
  ];
  cards.forEach((c, i) => card(s, MARGIN + i * 6.1, 3.5, 5.7, 3.2, c[0], c[1], c[2], { headPt: 34 }));
  rule(s, 7.35);
  s.addText("Each was discovered after the response had already been delivered.", { x: MARGIN, y: 7.6, w: 14, h: 0.6, fontFace: F, fontSize: 24, charSpacing: -0.5, color: C.ink, isTextBox: true, margin: 0 });
  s.addText("Enterprises average 5.0 production AI use cases and grow that count 101% year over year, against an 80%+ pilot failure rate. The gap is not model quality. It is that no component makes one accountable decision per response across quality, cost and responsibility together.", { x: MARGIN, y: 8.3, w: 16.5, h: 1.4, fontFace: F, fontSize: 16, color: C.bodyMuted, isTextBox: true, margin: 0, valign: "top", lineSpacingMultiple: 1.15 });
  footer(s, [{ t: "Source: McKinsey State of AI 2025, Gartner enterprise AI survey series" }, { t: "[M-03]", mono: true }]);
  shell(s, 6);
}

// ── 7. Regulatory clock (Comparison)
{
  const s = S();
  kicker(s, "01 · The problem");
  title(s, "The regulatory clock has already started.");
  lede(s, "Penalties are statutory, phase-in dates are fixed, and the obligation lands on the deploying enterprise.");
  hairTable(s, MARGIN, 3.5, [4.5, 5.4, 4.6, 4.0],
    ["Instrument", "Exposure", "Status", "Source"],
    [
      ["EU AI Act", "€35M or 7% of global turnover, top tier", "Phase-in through Dec 2027", { text: "[M-01]", mono: true }],
      ["EU AI Act, high-risk duties", "€15M or 3%; €7.5M or 1% for information duties", "In force, staged", { text: "[M-01]", mono: true }],
      ["India DPDP Act 2023", "Up to ₹250 crore per instance, security safeguards", "Rules notified Nov 2025", { text: "[M-02]", mono: true }],
      ["Classification burden", "18% of systems high-risk, 40% still unclassified", "Enterprise self-assessment", { text: "[M-12]", mono: true }],
      ["Recurring compliance cost", "€3.3 billion annually, EU-wide", "Estimated, 2026 study", { text: "[M-12]", mono: true }],
    ], { rowH: 0.62 });
  rule(s, 7.35);
  s.addText("40% of AI initiatives are cancelled where governance is absent.", { x: MARGIN, y: 7.6, w: 15, h: 0.6, fontFace: F, fontSize: 24, charSpacing: -0.5, color: C.ink, isTextBox: true, margin: 0 });
  s.addText("Governance is not the tax on shipping AI. Increasingly it is the precondition: the funnel jams at production, and unclassified systems cannot be signed off by anyone willing to carry the liability.", { x: MARGIN, y: 8.3, w: 16, h: 1.0, fontFace: F, fontSize: 16, color: C.bodyMuted, isTextBox: true, margin: 0, valign: "top", lineSpacingMultiple: 1.15 });
  footer(s, [{ t: "Source: Regulation (EU) 2024/1689; MeitY DPDP Rules 2025; appliedAI / DIGITALEUROPE" }, { t: "[M-01] [M-02] [M-12]", mono: true }]);
  shell(s, 7);
}

// ── 8. Divider
{ const s = pres.addSlide(); divider(s, "02  ·  The solution", "One URL change,\nexactly one verdict per response.", "Three planes of detection, converged by a deterministic policy engine, before delivery."); shell(s, 8, true); }

// ── 10. Request lifecycle (Flow)
{
  const s = S();
  kicker(s, "02 · The solution");
  title(s, "The request lifecycle, and where the decision happens.");
  lede(s, "A reverse proxy on the response path. The application changes one base URL and keeps its own SDK.");
  const steps = [
    ["01", "Application", "Calls the gateway instead of the provider. One base URL, no SDK change."],
    ["02", "Input lane", "Pre-dispatch redaction and injection screening. A block here costs zero upstream tokens."],
    ["03", "Sentence hold", "The response is buffered by sentence, not by token and not in full."],
    ["04", "Detection planes", "Deterministic matchers plus quantized CPU classifiers, each under its own budget."],
    ["05", "Policy engine", "Signals converge to one verdict under the use case's own YAML."],
    ["06", "Delivery", "Pass, edit, block or escalate. The verdict is stamped and audited."],
  ];
  const w = 2.85, gap = 0.24;
  steps.forEach((st, i) => {
    const x = MARGIN + i * (w + gap), y = 3.6;
    s.addShape(pres.ShapeType.roundRect, { x, y, w, h: 3.5, rectRadius: 0.12, fill: { color: i === 4 ? C.stone : "FFFFFF" }, line: { color: i === 4 ? C.stone : C.hair, width: 1 } });
    s.addText(st[0], { x: x + 0.3, y: y + 0.26, w: 1.2, h: 0.34, fontFace: M, fontSize: 12, bold: true, charSpacing: 1.5, color: i === 4 ? C.accent : C.slate, isTextBox: true, margin: 0 });
    s.addText(st[1], { x: x + 0.3, y: y + 0.66, w: w - 0.6, h: 0.9, fontFace: F, fontSize: 20, charSpacing: -0.5, color: C.ink, isTextBox: true, margin: 0, valign: "top" });
    s.addText(st[2], { x: x + 0.3, y: y + 1.6, w: w - 0.6, h: 1.6, fontFace: F, fontSize: 13, color: C.bodyMuted, isTextBox: true, margin: 0, valign: "top", lineSpacingMultiple: 1.12 });
    if (i < steps.length - 1) s.addShape(pres.ShapeType.line, { x: x + w + 0.03, y: y + 1.75, w: gap - 0.06, h: 0, line: { color: C.muted, width: 1, endArrowType: "triangle" } });
  });
  rule(s, 7.6);
  s.addText("The hot path holds nothing it cannot afford. Semantic entropy, fairness audits and LLM-judge scoring run on an async lane and are never awaited before delivery.", { x: MARGIN, y: 7.85, w: 16.5, h: 1.0, fontFace: F, fontSize: 16, color: C.bodyMuted, isTextBox: true, margin: 0, valign: "top", lineSpacingMultiple: 1.15 });
  footer(s, [{ t: "Source: docs/02-architecture.md, docs/04-policy-and-detection-spec.md" }, { t: "[B-06]", mono: true }]);
  shell(s, 10);
}

// ── 11. One signal, two labels, one verdict (Statement) — C1 rebuild
{
  const s = S();
  kicker(s, "02 · The solution");
  title(s, "One sentence can be two problems at once.");
  lede(s, "Detectors emit independent, multi-label signals. Only the policy engine converges them, so no plane can silence another.");
  s.addShape(pres.ShapeType.roundRect, { x: MARGIN, y: 3.5, w: 8.6, h: 1.5, rectRadius: 0.12, fill: { color: C.stone }, line: { color: C.stone, width: 0 } });
  s.addText("“I confirmed your refund with Priya on +91 98765 43210.”", { x: MARGIN + 0.35, y: 3.72, w: 7.9, h: 1.1, fontFace: F, fontSize: 20, color: C.ink, isTextBox: true, margin: 0, valign: "middle" });
  const labels = [
    ["hallucination.ungrounded_claim", "Performance plane", "rag_grounding: nothing in the provided context supports the confirmation. This signal carries the span."],
    ["privacy.person", "Responsibility plane", "entity_enricher appends this to the same signal and records that it did, so the engine cannot band-adjust it as a host label."],
    ["pii.phone", "Responsibility plane", "tier1_pii, deterministic e164 match, emitted independently of the other two."],
  ];
  labels.forEach((l, i) => {
    const y = 5.4 + i * 1.15;
    s.addText(l[0], { x: MARGIN, y, w: 5.4, h: 0.4, fontFace: M, fontSize: 14, bold: true, color: C.ink, isTextBox: true, margin: 0, valign: "middle" });
    s.addText(l[1], { x: MARGIN + 5.5, y, w: 3.0, h: 0.4, fontFace: M, fontSize: 11, bold: true, charSpacing: 1.5, color: C.slate, isTextBox: true, margin: 0, valign: "middle" });
    s.addText(l[2], { x: MARGIN, y: y + 0.42, w: 8.6, h: 0.5, fontFace: F, fontSize: 14, color: C.bodyMuted, isTextBox: true, margin: 0, valign: "top" });
    s.addShape(pres.ShapeType.line, { x: MARGIN, y: y + 1.0, w: 8.6, h: 0, line: { color: C.hair, width: 0.75 } });
  });
  card(s, 10.15, 3.5, 9.1, 5.4, "Why this matters", "Three signals, one decision.",
    "Suppressing one plane because another already fired is the failure this design refuses. The signals stay independent all the way to the engine, which applies the use case's own severity order and emits exactly one verdict for the sentence.\n\nThe provenance rule is enforced by the type, not by convention: a signal carrying an appended label that does not record where it came from is rejected before it can reach the engine.",
    { fill: "FFFFFF", headPt: 28, bodyPt: 15, bodyY: 1.6 });
  s.addText("A single sentence, three independent labels, exactly one verdict.", { x: MARGIN, y: 9.15, w: 16, h: 0.5, fontFace: F, fontSize: 20, charSpacing: -0.5, color: C.ink, isTextBox: true, margin: 0 });
  footer(s, [{ t: "Source: ADR-011, ADR-019, docs/04 §1.1 and §2.2" }, { t: "[B-01]", mono: true }]);
  shell(s, 11);
}

// ── 12. Signature: same content, three policies, three verdicts
{
  const s = S();
  kicker(s, "02 · The solution");
  title(s, "The same sentence. Three policies. Three verdicts.");
  lede(s, "Identical detector stack, identical content. Only the YAML differs, and there is no use-case name anywhere in executable code.");
  s.addShape(pres.ShapeType.roundRect, { x: MARGIN, y: 3.45, w: 18.5, h: 1.05, rectRadius: 0.12, fill: { color: C.stone }, line: { color: C.stone, width: 0 } });
  s.addText("“I confirmed your refund with Priya on +91 98765 43210.”", { x: MARGIN + 0.4, y: 3.45, w: 13.5, h: 1.05, fontFace: F, fontSize: 22, color: C.ink, isTextBox: true, margin: 0, valign: "middle" });
  s.addText([
    { text: "hallucination.ungrounded_claim", options: { fontFace: M, fontSize: 11, color: C.slate } },
    { text: "  +  ", options: { fontFace: F, fontSize: 11, color: C.muted } },
    { text: "privacy.person", options: { fontFace: M, fontSize: 11, color: C.slate } },
    { text: "  +  ", options: { fontFace: F, fontSize: 11, color: C.muted } },
    { text: "pii.phone", options: { fontFace: M, fontSize: 11, color: C.slate } },
  ], { x: 14.3, y: 3.45, w: 4.9, h: 1.05, isTextBox: true, margin: 0, valign: "middle", align: "right" });
  const cols = [
    ["support_bot", "EDIT", C.edit, ["pii.*: edit", "privacy.person: pass", "hallucination.ungrounded_claim: edit", "borderline_action: edit"],
      "The span is redacted and the claim softened. The customer still gets an answer."],
    ["hr_copilot", "BLOCK", C.block, ["pii.*: block", "privacy.person: block", "hallucination.*: pass", "borderline_action: pass"],
      "Employee personal data is not transformable here, so the response is replaced outright."],
    ["finance_advisor", "ESCALATE", C.esc, ["pii.*: escalate", "privacy.person: escalate", "hallucination.ungrounded_claim: escalate", "borderline_action: escalate"],
      "Quarantined for a human reviewer. Nothing reaches the client until someone decides."],
  ];
  cols.forEach((c, i) => {
    const x = MARGIN + i * 6.27, y = 4.95, w = 5.85;
    s.addText(c[0], { x, y, w, h: 0.35, fontFace: M, fontSize: 13, bold: true, color: C.ink, isTextBox: true, margin: 0 });
    chip(s, x, y + 0.45, c[1], c[2], 2.5);
    s.addShape(pres.ShapeType.roundRect, { x, y: y + 1.15, w, h: 2.3, rectRadius: 0.12, fill: { color: "F7F7F5" }, line: { color: C.hair, width: 1 } });
    s.addText(c[3].join("\n"), { x: x + 0.3, y: y + 1.35, w: w - 0.6, h: 1.95, fontFace: M, fontSize: 12, color: C.body, isTextBox: true, margin: 0, valign: "top", lineSpacingMultiple: 1.35 });
    s.addText(c[4], { x, y: y + 3.6, w, h: 0.55, fontFace: F, fontSize: 14, color: C.bodyMuted, isTextBox: true, margin: 0, valign: "top", lineSpacingMultiple: 1.15 });
  });
  s.addText("Verified by running the engine, not by reading the config: three verdicts from one set of signals.", { x: MARGIN, y: 9.3, w: 17, h: 0.45, fontFace: F, fontSize: 18, charSpacing: -0.5, color: C.ink, isTextBox: true, margin: 0 });
  footer(s, [{ t: "Source: policies/*.yaml via controlplane.policy.engine.evaluate" }, { t: "reports/eval_report.md §Policy-level" }, { t: "[B-01]", mono: true }]);
  shell(s, 12);
}

// ── 13. The console (Product, deep-green band)
{
  const s = pres.addSlide(); s.background = { color: C.green };
  kicker(s, "02 · The solution", true);
  s.addText("The oversight console.", { x: MARGIN, y: 1.1, w: 8, h: 1.0, fontFace: F, fontSize: 40, charSpacing: -1, color: "FFFFFF", isTextBox: true, margin: 0, valign: "top" });
  s.addText("Three pages served same-origin by the gateway itself: an overview, this verdict board, and a test chat. Every static figure on the page cites the committed report it came from.", { x: MARGIN, y: 2.3, w: 7.5, h: 1.6, fontFace: F, fontSize: 17, color: C.onDarkSub, isTextBox: true, margin: 0, valign: "top", lineSpacingMultiple: 1.18 });
  const facts = [
    ["Live counters", "cp_requests_total and cp_pii_intercepts_total, read from GET /metrics."],
    ["Category, never the value", "A PII interception is counted by category. The matched text is never stored or shown."],
    ["Human review queue", "Escalated responses are quarantined, never delivered, until a reviewer decides. The decision is one-shot and written into the audit lineage."],
    ["Counters read zero here", "This capture ran on the offline factory, whose provider is dev class. Populating them would publish figures ADR-018 forbids, so they stay empty rather than invented."],
  ];
  let fy = 4.15;
  facts.forEach((f) => {
    s.addText(f[0].toUpperCase(), { x: MARGIN, y: fy, w: 7.5, h: 0.3, fontFace: M, fontSize: 11, bold: true, charSpacing: 1.5, color: C.accentLight, isTextBox: true, margin: 0 });
    s.addText(f[1], { x: MARGIN, y: fy + 0.34, w: 7.4, h: 0.9, fontFace: F, fontSize: 14, color: C.onDarkSub, isTextBox: true, margin: 0, valign: "top", lineSpacingMultiple: 1.12 });
    fy += 1.42;
  });
  s.addImage({ path: "reports/deck-render/console-capture-dashboard.png", x: 8.75, y: 2.55, w: 10.5, h: 6.48 });
  footer(s, [{ t: "Live capture: uvicorn --factory controlplane.gateway.app:create_app --port 8099", mono: true }, { t: "docs/09 §Console" }], true);
  shell(s, 13, true);
}

// ── 14. Escalation ladder (Flow) — C2
{
  const s = S();
  kicker(s, "02 · The solution");
  title(s, "The cost ladder: what ships, and what is next.");
  lede(s, "Three rungs, and we are explicit about which one carries load today. The gate is built. The router is not.");
  const rungs = [
    ["Rung 1", "Cheap deterministic screening", "SHIPS", C.pass,
      "Input-stage matchers reject before dispatch. A blocked injection costs zero upstream tokens, because nothing is sent."],
    ["Rung 2", "Budget and loop enforcement", "SHIPS", C.pass,
      "cost_budget and loop_guard run live in the gateway pipeline at the input stage, each inside a 1 ms budget."],
    ["Rung 3", "Model cascade routing", "ROADMAP", C.esc,
      "Routing a request to a cheaper model and probing for agreement is specified and not built. It is tracked as SL-10, not presented as a capability."],
  ];
  rungs.forEach((r, i) => {
    const y = 3.6 + i * 1.95, h = 1.72;
    s.addShape(pres.ShapeType.roundRect, { x: MARGIN, y, w: 18.5, h, rectRadius: 0.12, fill: { color: i === 2 ? "FFFFFF" : C.stone }, line: { color: i === 2 ? C.hair : C.stone, width: 1 } });
    s.addText(r[0].toUpperCase(), { x: MARGIN + 0.4, y: y + 0.28, w: 2.0, h: 0.3, fontFace: M, fontSize: 11, bold: true, charSpacing: 1.5, color: C.slate, isTextBox: true, margin: 0 });
    s.addText(r[1], { x: MARGIN + 0.4, y: y + 0.62, w: 6.6, h: 0.75, fontFace: F, fontSize: 24, charSpacing: -0.5, color: C.ink, isTextBox: true, margin: 0, valign: "top" });
    chip(s, MARGIN + 7.5, y + 0.62, r[2], r[3], 2.35);
    s.addText(r[4], { x: MARGIN + 10.3, y: y + 0.35, w: 8.0, h: 1.1, fontFace: F, fontSize: 14, color: C.bodyMuted, isTextBox: true, margin: 0, valign: "middle", lineSpacingMultiple: 1.12 });
  });
  s.addText("A roadmap rung is drawn as a roadmap rung. The savings we quote come from the two that run.", { x: MARGIN, y: 9.35, w: 17, h: 0.45, fontFace: F, fontSize: 18, charSpacing: -0.5, color: C.ink, isTextBox: true, margin: 0 });
  footer(s, [{ t: "Source: controlplane/gateway/pipeline.py, docs/08 SL-10" }, { t: "ADR-013" }]);
  shell(s, 14);
}

// ── 15. Divider
{ const s = pres.addSlide(); divider(s, "03  ·  Evidence and scope", "We report what we measured,\nincluding where we fell short.", "Blind first contact on a frozen corpus. Targets were never moved to meet a result."); shell(s, 15, true); }

// ── 16. What ships today (Comparison) — C3 + C6. Two columns, no table over five rows.
{
  const s = S();
  kicker(s, "03 · Evidence and scope");
  title(s, "What ships today, and what does not.");
  lede(s, "The honest inventory. Nothing on the left is aspirational, and nothing on the right is hidden.");
  const ships = [
    ["Live detector registry", "8 of 11", "The three deterministic matchers plus injection, toxicity, grounding, budget and loop guard, with entity_enricher live as the enrichment stage."],
    ["Gateway hot path", "Implemented", "Ingress lane, sentence buffer, buffered and streaming delivery, SSE proxy, boot-time canary."],
    ["Policy engine", "Implemented", "All four verdicts, band logic, and per-use-case fail-open and fail-closed resolution."],
    ["Cost plane", "Enforces", "cost_budget, loop_guard and the spend ledger run live at the input stage."],
    ["Oversight console", "Implemented", "Three pages served same-origin, each static figure citing the report it came from."],
  ];
  const nots = [
    ["Scored by the eval harness", "5 of 11", "rag_grounding ships but is deliberately unscored. 101 of 218 labelled positives have no detector to emit them yet."],
    ["fast_consistency", "Cut to roadmap", "Tracked as SL-6. Not counted as a detector and not inside any figure we quote."],
    ["Bias and fairness auditing", "Not built", "The async lane is specified. No fairness number appears in this deck, because none has been measured."],
    ["Multi-turn and agent risk", "Stub", "conv_tracker has a specified scope and no implementation, so cumulative-risk escalation is not demonstrable."],
    ["pii_leak_scan, dashboard", "Not built", "The console replaces the dashboard plan. The leak-scan harness is unwritten, so no leak-rate figure is claimed."],
  ];
  [[ships, MARGIN, "Ships today", C.pass], [nots, 10.15, "Cut, stubbed or unmeasured", C.esc]].forEach(([rowsIn, x, head, dot]) => {
    const rows = rowsIn;
    s.addText(head.toUpperCase(), { x, y: 3.45, w: 9.1, h: 0.3, fontFace: M, fontSize: 11, bold: true, charSpacing: 1.5, color: C.slate, isTextBox: true, margin: 0 });
    s.addShape(pres.ShapeType.line, { x, y: 3.83, w: 9.1, h: 0, line: { color: C.ink, width: 0.75 } });
    rows.forEach((r, i) => {
      const y = 3.95 + i * 1.16;
      s.addShape(pres.ShapeType.ellipse, { x, y: y + 0.16, w: 0.11, h: 0.11, fill: { color: dot }, line: { color: dot, width: 0 } });
      s.addText(r[0], { x: x + 0.28, y, w: 5.1, h: 0.36, fontFace: F, fontSize: 16, color: C.ink, isTextBox: true, margin: 0, valign: "middle" });
      s.addText(r[1], { x: x + 5.4, y, w: 3.7, h: 0.36, fontFace: M, fontSize: 12, bold: true, color: dot, isTextBox: true, margin: 0, align: "right", valign: "middle" });
      s.addText(r[2], { x: x + 0.28, y: y + 0.38, w: 8.6, h: 0.66, fontFace: F, fontSize: 13, color: C.bodyMuted, isTextBox: true, margin: 0, valign: "top", lineSpacingMultiple: 1.08 });
      s.addShape(pres.ShapeType.line, { x, y: y + 1.06, w: 9.1, h: 0, line: { color: C.hair, width: 0.75 } });
    });
  });
  footer(s, [{ t: "Source: docs/09-engineering-notes.md §Build status" }, { t: "docs/08-open-questions.md ledger" }]);
  shell(s, 16);
}

// ── 17. Detection quality (Evidence) — C10 split 1/2
{
  const s = S();
  kicker(s, "03 · Evidence and scope");
  title(s, "Detection quality, including what we missed.");
  lede(s, "Blind first contact, revised once under disclosure. One target was missed and the target did not move.");
  hairTable(s, MARGIN, 3.45, [5.3, 2.5, 2.5, 1.9, 6.3],
    ["Detector and metric", "Blind", "Revised", "Target", "Standing"],
    [
      [{ text: "tier1_pii recall", mono: true }, "0.836", "0.885", "0.95", "MISSED, target unmoved. All 7 residual misses are the documented bare-digit exclusion"],
      [{ text: "tier1_pii precision", mono: true }, "1.000", "1.000", "none", "No over-firing in either version"],
      [{ text: "numeric_claims precision", mono: true }, "0.267", "0.857", "none", "A rule was deleted, not tuned (ADR-025). Recall flat at 0.750"],
      [{ text: "tier2_injection", mono: true }, "P 1.000 / R 0.150", "not tuned", "none", "Layered defence: blocks pre-dispatch at zero upstream tokens"],
      [{ text: "tier2_toxicity high", mono: true }, "P 0.400 / R 0.250", "not tuned", "none", "Reported blind. No threshold was moved to improve it"],
    ], { align: ["left", "right", "right", "right", "left"], rowH: 0.64 });
  rule(s, 7.35);
  const t2 = [
    ["5/5", "mutation classes the policy matrix is required to catch, one at a time", "[B-01]"],
    ["1.000", "policy conformance over 280 cases × 3 policies, perfect detection assumed", "[B-01]"],
    ["0.825 to 0.851", "end-to-end agreement over the 194 cases real detectors can reach", "[B-10]"],
  ];
  t2.forEach((t, i) => statTile(s, MARGIN + i * 6.27, 7.6, 5.85, t[0], t[1], t[2]));
  footer(s, [{ t: "Source: reports/eval_report.md" }, { t: "reproduce: python -m eval.run_all", mono: true }, { t: "[B-01] [B-02] [B-04] [B-10]", mono: true }]);
  shell(s, 17);
}

// ── 18. Latency and reliability (Evidence) — C10 split 2/2, C4 both runs
{
  const s = S();
  kicker(s, "03 · Evidence and scope");
  title(s, "Latency and failure behaviour, both measurements.");
  lede(s, "Budgets bind detector-attributable time, the same figure the runner enforces on. One detector breaches and we publish it.");
  hairTable(s, MARGIN, 3.4, [4.6, 1.8, 1.5, 2.0, 2.0, 6.6],
    ["Detector", "Budget", "n", "P50", "P99", "Verdict at P99"],
    [
      [{ text: "tier1_pii", mono: true }, "2 ms", "583", "0.053", "0.133", "Within budget"],
      [{ text: "tier1_blocklist", mono: true }, "2 ms", "583", "0.012", "0.020", "Within budget"],
      [{ text: "numeric_claims", mono: true }, "5 ms", "283", "0.077", "0.277", "Within budget"],
      [{ text: "tier2_toxicity", mono: true }, "25 ms", "283", "19.553", "23.741", "Within budget, 2 fail_open faults"],
      [{ text: "tier2_injection", mono: true }, "25 ms", "300", "20.032", "25.348", "BREACH, published, budget not moved"],
    ], { align: ["left", "right", "right", "right", "right", "left"], rowH: 0.6 });
  rule(s, 6.9);
  s.addText("Fault injection is a rate, not a run, and two measurements of it disagree.", { x: MARGIN, y: 7.15, w: 17, h: 0.45, fontFace: F, fontSize: 22, charSpacing: -0.5, color: C.ink, isTextBox: true, margin: 0 });
  const two = [
    ["In process, 5 repetitions", "5/5 reached 39/39", "Quiet host, load stamped per repetition. All five share one warmed model pool, so this measures the warmed steady state."],
    ["Five separate processes", "3/5 clean, two at 38/39", "Same control-probe assertion. Each process pays first-touch model initialization, so this reaches the cold path."],
  ];
  two.forEach((t, i) => {
    const x = MARGIN + i * 6.27;
    card(s, x, 7.75, 5.85, 1.95, t[0], t[1], t[2], { headPt: 20, bodyPt: 13, bodyY: 1.15, headH: 0.5 });
  });
  card(s, MARGIN + 12.54, 7.75, 5.85, 1.95, "Coverage and its limits", "3 of 4 fault classes",
    "cost has no live carrier, so its modes are untested rather than met. tier1 has no fail-open side to contrast.",
    { headPt: 20, bodyPt: 13, bodyY: 1.15, headH: 0.5 });
  footer(s, [{ t: "Source: reports/latency_report.md, reports/fault_injection_report.md, docs/09 §Verification" }, { t: "[B-05] [B-07]", mono: true }]);
  shell(s, 18);
}

// ── 19. Why the misses are the point (Statement)
{
  const s = S();
  kicker(s, "03 · Evidence and scope");
  title(s, "Why we lead with the numbers that look worst.");
  lede(s, "An oversight product that cannot be honest about its own blind spots is not oversight. It is marketing with a latency budget.");
  const items = [
    ["The end-to-end score fell as coverage rose", "From 0.981 over 159 cases to 0.825 to 0.851 over 194. The system did not get worse. The measurement got harder, and we report the harder one."],
    ["A perfect score is treated as suspect", "The 1.000 conformance figure is falsified rather than trusted: five defect classes are injected one at a time and the matrix is required to disagree with each."],
    ["A missed target stays missed", "Tier-1 PII recall is 0.885 against a 0.95 target. The target was not moved, the patterns were re-derived from published sources, and the residual misses are named."],
    ["A breach is published as a breach", "The injection detector exceeds its 25 ms budget at P99. The budget stands, the figure is printed, and the mitigation is described rather than assumed."],
  ];
  items.forEach((it, i) => {
    const x = MARGIN + (i % 2) * 9.35, y = 3.6 + Math.floor(i / 2) * 2.75;
    card(s, x, y, 8.9, 2.45, null, it[0], it[1], { headPt: 22, headH: 0.45, bodyPt: 15, bodyY: 1.15 });
  });
  rule(s, 9.25);
  s.addText("Every figure in this deck is reproducible by a command in the repository.", { x: MARGIN, y: 9.45, w: 17, h: 0.45, fontFace: F, fontSize: 18, charSpacing: -0.5, color: C.ink, isTextBox: true, margin: 0 });
  footer(s, [{ t: "Source: AGENTS.md §7, docs/06-evaluation-plan.md" }, { t: "docs/08-open-questions.md ledger" }]);
  shell(s, 19);
}

// ── 20. Divider
{ const s = pres.addSlide(); divider(s, "04  ·  Market and business", "A category forming now,\nsized two very different ways.", "We quote both analyst estimates and explain the 4.08× gap rather than picking the flattering one."); shell(s, 20, true); }

// ── 21. Two analyst estimates (Evidence)
{
  const s = S();
  kicker(s, "04 · Market and business");
  title(s, "Two analyst estimates, and why they differ.");
  lede(s, "The divergence is definitional, not a disagreement about growth. Quoting only the larger number would be the easy mistake.");
  hairTable(s, MARGIN, 3.5, [5.0, 2.9, 3.0, 2.0, 5.6],
    ["Source", "Base", "Forecast", "CAGR", "What the scope includes"],
    [
      ["MarketsandMarkets", "$0.89B (2024)", "$5.78B (2029)", "45.3%", "Broad: absorbs MLOps, LLMOps and privacy software"],
      ["Grand View Research", "$0.308B (2025)", "$1.42B (2030)", "35.7%", "Narrow: pure-play governance software and third-party auditing"],
    ], { align: ["left", "right", "right", "right", "left"], rowH: 0.62 });
  const tiles = [
    ["4.08×", "the gap between the two estimates, driven by scope rather than growth", "[M-04]"],
    ["72%", "of organisations now use generative AI in at least one business function", "[M-03]"],
    ["€3.3B", "estimated recurring EU-wide AI compliance cost, annually", "[M-12]"],
  ];
  tiles.forEach((t, i) => statTile(s, MARGIN + i * 6.27, 5.5, 5.85, t[0], t[1], t[2]));
  rule(s, 8.05);
  s.addText("The funnel jams at production, and that is where we sell.", { x: MARGIN, y: 8.3, w: 15, h: 0.5, fontFace: F, fontSize: 22, charSpacing: -0.5, color: C.ink, isTextBox: true, margin: 0 });
  s.addText("Enterprises average 5.0 production use cases against an 80%+ pilot failure rate, and 40% of initiatives are cancelled where governance is absent. We are not selling a nice-to-have layer on a working pipeline. We are selling the thing that lets a blocked pipeline ship.", { x: MARGIN, y: 8.95, w: 17, h: 0.9, fontFace: F, fontSize: 15, color: C.bodyMuted, isTextBox: true, margin: 0, valign: "top", lineSpacingMultiple: 1.15 });
  footer(s, [{ t: "Source: MarketsandMarkets; Grand View Research; McKinsey; appliedAI / DIGITALEUROPE" }, { t: "[M-03] [M-04] [M-12]", mono: true }]);
  shell(s, 21);
}

// ── 22. Competitive position + the retraction (Comparison)
{
  const s = S();
  kicker(s, "04 · Market and business");
  title(s, "Where we sit, and the claim we withdrew.");
  lede(s, "Our own market research contradicted a differentiation claim we had made. We retracted it and rebuilt the positioning.");
  hairTable(s, MARGIN, 3.45, [3.7, 4.3, 5.3, 5.2],
    ["Player", "Funding", "What they do", "Where they stop"],
    [
      ["Portkey", "$18.1M raised, $15M Series A Feb 2026", "Unified AI gateway with observability and routing", "Gateway-first: routing and visibility, thin convergence"],
      ["Lakera", "$30M to $40M raised", "Real-time AI application firewall, 97.6%+ true-positive blocking claimed", "Security plane only: no quality or cost convergence, no human loop"],
      ["Arize AI", "$131M raised, ~$1B valuation", "Enterprise observability and evaluation at scale", "Post-hoc by architecture: observes, cannot gate delivery"],
    ], { rowH: 0.78, pt: 14 });
  card(s, MARGIN, 6.7, 9.1, 2.95, "The retraction", "We claimed hyperscalers lacked per-use-case policy and fail-posture control.",
    "They document both. The claim was wrong, so it is gone rather than softened. What survives is narrower and defensible: convergence of three planes into one verdict, with a human-in-the-loop escalation path and an append-only lineage.",
    { headPt: 19, headH: 1.1, bodyPt: 14, bodyY: 1.75 });
  card(s, 10.15, 6.7, 9.1, 2.95, "Why the retraction is the asset", "A timestamped record of how we behave when we are wrong.",
    "We cannot show enterprise references. We can show something a regulated buyer arguably values more: a public, dated record of a claim we removed the moment the evidence went against it. That is the same discipline the detection numbers are reported under.",
    { headPt: 19, headH: 1.1, bodyPt: 14, bodyY: 1.75 });
  footer(s, [{ t: "Source: Tracxn, Crunchbase, AWS / Microsoft / NVIDIA documentation; OWASP GenAI" }, { t: "[M-05] [M-07]", mono: true }]);
  shell(s, 22);
}

// ── 23. Who feels the pain, who signs (Comparison)
{
  const s = S();
  kicker(s, "04 · Market and business");
  title(s, "Who feels the pain, and who signs the cheque.");
  lede(s, "The buyer carries the liability. The user carries the incident. They are rarely the same person, so the product answers to both.");
  const roles = [
    ["Chief risk and compliance", "Signs", "Needs evidence that a control existed at the moment of delivery, not a report that an incident happened. Append-only lineage is the artifact they can hand to an auditor."],
    ["Platform and ML engineering", "Adopts", "Will not accept a rewrite. One base-URL change, their own SDK, and a latency budget they can see measured per detector."],
    ["Product owners", "Feels the pain", "Blocked from shipping by a governance sign-off they cannot obtain. A per-pipeline policy is what unblocks them without a central committee."],
    ["Reviewers and ops", "Lives in it", "Escalated responses are quarantined rather than delivered. One decision, one-shot, written into the record."],
  ];
  roles.forEach((r, i) => {
    const x = MARGIN + (i % 2) * 9.35, y = 3.5 + Math.floor(i / 2) * 2.95;
    s.addShape(pres.ShapeType.roundRect, { x, y, w: 8.9, h: 2.6, rectRadius: 0.12, fill: { color: "FFFFFF" }, line: { color: C.hair, width: 1 } });
    s.addText(r[1].toUpperCase(), { x: x + 0.35, y: y + 0.28, w: 4.0, h: 0.3, fontFace: M, fontSize: 11, bold: true, charSpacing: 1.5, color: C.accent, isTextBox: true, margin: 0 });
    s.addText(r[0], { x: x + 0.35, y: y + 0.66, w: 8.2, h: 0.6, fontFace: F, fontSize: 24, charSpacing: -0.5, color: C.ink, isTextBox: true, margin: 0, valign: "top" });
    s.addText(r[2], { x: x + 0.35, y: y + 1.35, w: 8.2, h: 1.05, fontFace: F, fontSize: 14, color: C.bodyMuted, isTextBox: true, margin: 0, valign: "top", lineSpacingMultiple: 1.14 });
  });
  s.addText("Serviceable segment: regulated verticals plus roughly 1,600 to 1,700 Indian GCCs employing 1.6 million professionals, over 70% with genAI roadmaps.", { x: MARGIN, y: 9.4, w: 17.5, h: 0.5, fontFace: F, fontSize: 15, color: C.bodyMuted, isTextBox: true, margin: 0 });
  footer(s, [{ t: "Source: NASSCOM / MeitY GCC ecosystem reporting" }, { t: "[M-09]", mono: true }]);
  shell(s, 23);
}

// ── 24. Open core and what a pipeline costs (Comparison) — V1: no callout over a table
{
  const s = S();
  kicker(s, "04 · Market and business");
  title(s, "Open core, priced per governed pipeline.");
  lede(s, "Revenue tracks the customer's own AI adoption curve, because the unit of value is a pipeline under policy.");
  hairTable(s, MARGIN, 3.45, [4.6, 4.9, 8.9],
    ["Assumption", "Value", "Basis"],
    [
      ["Blended ACV", "US$35,000 to 50,000", "One enterprise logo is three to five paid pipelines plus pack and SLA uplift"],
      ["Gross margin", "~85%", "Software plus thin sampling. The customer pays their own model spend"],
      ["CAC, partner-led", "US$10,000 to 18,000", "SI-attached deals and open-source inbound, no outbound sales team in years one and two"],
      ["Payback", "Under 6 months", "ACV divided by CAC at the figures above"],
      ["Expansion", "1 pipeline to 4 to 6", "Within 12 to 18 months, tracking documented enterprise use-case growth"],
    ], { align: ["left", "right", "left"], rowH: 0.62 });
  rule(s, 6.9);
  card(s, MARGIN, 7.15, 9.1, 2.5, "What we deliberately do not claim", "No absolute savings figure.",
    "Published pricing shows a 15× to 25× premium for flagship over small models, with one documented pair at 20.0× on input. We do not convert that into a dollar saving, because the cascade router that would produce it is roadmap. Quoting a number we have not measured would break the rule the rest of this deck follows.",
    { headPt: 20, headH: 0.55, bodyPt: 13, bodyY: 1.15 });
  card(s, 10.15, 7.15, 9.1, 2.5, "The projection label is deliberate", "Every figure on this slide is a model.",
    "These are assumptions with a stated basis, not measurements, and they are labelled that way. The measured figures in this deck all come from a committed report and name the command that regenerates them. Mixing the two categories is how a business case stops being checkable.",
    { headPt: 20, headH: 0.55, bodyPt: 13, bodyY: 1.15 });
  footer(s, [{ t: "Projection, not measurement: assumptions per proposal §10" }, { t: "OpenAI published pricing" }, { t: "[M-03] [M-06]", mono: true }]);
  shell(s, 24);
}

// ── 25. Go-to-market and roadmap (Flow)
{
  const s = S();
  kicker(s, "04 · Market and business");
  title(s, "How this reaches production, and in what order.");
  lede(s, "Design partners first, then a systems-integrator channel. Each phase has an exit criterion rather than a date.");
  const phases = [
    ["P0", "Now", "Prototype complete", "Gateway, policy engine, eight live detectors, console, committed evidence in reports/."],
    ["P1", "2 to 6 months", "Design partners", "Three to five pilots across Indian BFSI and GCCs plus one EU-exposed SaaS. Exit: one pipeline in production."],
    ["P2", "6 to 18 months", "Partner-led channel", "Systems-integrator motion. Accenture alone has committed $3 billion over three years to Data and AI, with 80,000 specialists."],
    ["P3", "Beyond", "Close the scope gaps", "Cascade routing, fairness auditing, multi-turn risk, the leak-scan harness. Each is named in the ledger today."],
  ];
  const w = 4.4, gap = 0.28;
  phases.forEach((p, i) => {
    const x = MARGIN + i * (w + gap), y = 3.55;
    s.addShape(pres.ShapeType.roundRect, { x, y, w, h: 3.9, rectRadius: 0.12, fill: { color: i === 0 ? C.stone : "FFFFFF" }, line: { color: i === 0 ? C.stone : C.hair, width: 1 } });
    s.addText(p[0], { x: x + 0.32, y: y + 0.28, w: 1.4, h: 0.34, fontFace: M, fontSize: 13, bold: true, charSpacing: 1.5, color: i === 0 ? C.accent : C.slate, isTextBox: true, margin: 0 });
    s.addText(p[1], { x: x + 1.6, y: y + 0.28, w: w - 1.9, h: 0.34, fontFace: M, fontSize: 11, color: C.muted, isTextBox: true, margin: 0, align: "right" });
    s.addText(p[2], { x: x + 0.32, y: y + 0.72, w: w - 0.64, h: 1.0, fontFace: F, fontSize: 21, charSpacing: -0.5, color: C.ink, isTextBox: true, margin: 0, valign: "top" });
    s.addText(p[3], { x: x + 0.32, y: y + 1.82, w: w - 0.64, h: 1.85, fontFace: F, fontSize: 13, color: C.bodyMuted, isTextBox: true, margin: 0, valign: "top", lineSpacingMultiple: 1.13 });
    if (i < phases.length - 1) s.addShape(pres.ShapeType.line, { x: x + w + 0.04, y: y + 1.95, w: gap - 0.08, h: 0, line: { color: C.muted, width: 1, endArrowType: "triangle" } });
  });
  rule(s, 7.75);
  s.addText("The roadmap is the ledger, read forward.", { x: MARGIN, y: 8.0, w: 15, h: 0.5, fontFace: F, fontSize: 22, charSpacing: -0.5, color: C.ink, isTextBox: true, margin: 0 });
  s.addText("Everything in P3 appears in this deck as a stated gap, with its tracking identifier. A roadmap built from an existing limitations register is harder to inflate than one built from ambition, and it is checkable by anyone who reads the repository.", { x: MARGIN, y: 8.65, w: 17, h: 0.9, fontFace: F, fontSize: 15, color: C.bodyMuted, isTextBox: true, margin: 0, valign: "top", lineSpacingMultiple: 1.15 });
  footer(s, [{ t: "Source: proposal §11; Accenture Newsroom; NASSCOM" }, { t: "[M-01] [M-09] [M-10]", mono: true }]);
  shell(s, 25);
}

// ── 26. Risks (Comparison) — V2: no banner over the last row
{
  const s = S();
  kicker(s, "04 · Market and business");
  title(s, "Risks, led by our own weakest numbers.");
  lede(s, "Five of the eight risks in the register. The remaining three, including team capacity, are in the proposal appendix.");
  hairTable(s, MARGIN, 3.45, [5.0, 6.4, 7.1],
    ["Risk", "The evidence against us", "What reduces it"],
    [
      ["Detection quality is incomplete", "Injection recall 0.150 blind, toxicity high-band recall 0.250", "Layered defence: deterministic patterns block pre-dispatch at zero upstream tokens"],
      ["Latency objections", "One detector breaches its 25 ms budget at P99, at 25.348 ms", "The deterministic tier runs three orders of magnitude inside budget; windowing is tunable"],
      ["Market timing and category risk", "Analyst estimates diverge 4.08× on size; consolidation already underway", "We sell into a blocked funnel rather than a forecast"],
      ["Cold-path reliability", "Three of five separate processes clean, two at 38/39", "Root cause named rather than tuned away; the assertion was not relaxed"],
      ["Coverage of failure classes", "Three of four fault classes covered; cost has no live carrier", "Reported as untested rather than met, and tracked in the ledger"],
    ], { rowH: 0.78, pt: 14 });
  footer(s, [{ t: "Source: reports/eval_report.md, reports/latency_report.md, reports/fault_injection_report.md" }, { t: "[B-04] [B-05] [B-07] [M-04]", mono: true }]);
  shell(s, 26);
}

// ── 27. References (two columns, hairline) — C7
{
  const s = S();
  kicker(s, "Appendix");
  title(s, "Every tag in this deck, and what backs it.");
  lede(s, "B tags are figures this repository produces. M tags are external sources, with the date we read them.");
  const B = [
    ["B-01", "Policy conformance, 5 mutation classes, no use-case name in code"],
    ["B-02", "PII precision 1.000; recall 0.836 to 0.885"],
    ["B-04", "Injection P 1.000 / R 0.150; toxicity high P 0.400 / R 0.250, blind"],
    ["B-05", "Per-detector latency and the published breach"],
    ["B-06", "Input-lane and per-sentence hold percentiles"],
    ["B-07", "Fault injection, both the in-process and separate-process rates"],
    ["B-08", "Spurious-fault reduction, 2/30 to 0/30"],
    ["B-09", "Corpus freeze, ADR and deviation counts, re-derivation gate"],
    ["B-10", "End-to-end agreement 0.825 to 0.851 over 194 cases"],
    ["B-11", "Zero raw PII in audit evidence"],
    ["B-12", "Calibration band inversion across five seeds"],
    ["B-14", "Hidden-token injection caught by the accounting canary"],
  ];
  const Mrows = [
    ["M-01", "EU AI Act penalties and phase-in. eur-lex, Jul 2024 / Jul 2026"],
    ["M-02", "DPDP Act penalties; rules notified. MeitY / PIB, Nov 2025"],
    ["M-03", "Adoption, pilot failure, 5.0 use cases. McKinsey / Gartner, 2025"],
    ["M-04", "Market size and CAGR, both estimates. MnM; Grand View"],
    ["M-05", "OWASP LLM01 and LLM06; Lakera benchmark. Aug 2026"],
    ["M-06", "Flagship to mini price premium. OpenAI pricing, Aug 2026"],
    ["M-07", "Competitor funding; hyperscaler support. Tracxn, Crunchbase"],
    ["M-08", "Presidio 0.431 vs fine-tuned 0.855. arXiv:2608.02616v1"],
    ["M-09", "Indian GCC ecosystem scale. NASSCOM / MeitY, Nov 2025"],
    ["M-10", "Accenture Data and AI investment. Accenture Newsroom"],
    ["M-11", "Inline guardrail overhead budget. Lakera; AWS Bedrock"],
    ["M-12", "High-risk share and EU compliance cost. appliedAI / DIGITALEUROPE"],
  ];
  [[B, MARGIN, "Measured in this repository"], [Mrows, 10.15, "External sources"]].forEach(([rows, x, head]) => {
    s.addText(head.toUpperCase(), { x, y: 3.4, w: 9.1, h: 0.3, fontFace: M, fontSize: 11, bold: true, charSpacing: 1.5, color: C.slate, isTextBox: true, margin: 0 });
    s.addShape(pres.ShapeType.line, { x, y: 3.78, w: 9.1, h: 0, line: { color: C.ink, width: 0.75 } });
    rows.forEach((r, i) => {
      const y = 3.86 + i * 0.47;
      s.addText(r[0], { x, y, w: 1.1, h: 0.44, fontFace: M, fontSize: 12, bold: true, color: C.ink, isTextBox: true, margin: 0, valign: "middle" });
      s.addText(r[1], { x: x + 1.15, y, w: 7.95, h: 0.44, fontFace: F, fontSize: 14, color: C.body, isTextBox: true, margin: 0, valign: "middle" });
      s.addShape(pres.ShapeType.line, { x, y: y + 0.45, w: 9.1, h: 0, line: { color: C.hair, width: 0.75 } });
    });
  });
  footer(s, [{ t: "B tags: python -m eval.run_all, eval.bench_latency, eval.fault_injection", mono: true }, { t: "B-03 and B-13 are cited in the proposal, not in this deck" }]);
  shell(s, 27);
}

// ── 28. The ask (Close, ink band) — V3: tagline clear of the asks, accent-light on dark
{
  const s = pres.addSlide(); s.background = { color: C.ink };
  kicker(s, "The ask", true);
  s.addText("Back it, and we put it in front of\nthree design partners.", { x: MARGIN, y: 1.15, w: 16, h: 2.2, fontFace: F, fontSize: 54, charSpacing: -2, lineSpacingMultiple: 1.0, color: "FFFFFF", isTextBox: true, margin: 0, valign: "top" });
  const asks = [
    ["01", "The challenge's backing", "Advance ControlPlane on the strength of a working prototype whose every number is reproducible from the repository."],
    ["02", "An indicative pre-seed", "INR 1.6 crore, about US$190,000, for twelve months. A projection with a stated basis, not a measurement."],
    ["03", "Three design partners", "One EU-exposed SaaS and two Indian BFSI or GCC pipelines. Success is one pipeline in production under policy."],
  ];
  asks.forEach((a, i) => {
    const x = MARGIN + i * 6.27;
    s.addShape(pres.ShapeType.roundRect, { x, y: 4.15, w: 5.85, h: 3.0, rectRadius: 0.12, fill: { color: "23232A" }, line: { color: "23232A", width: 0 } });
    s.addText(a[0], { x: x + 0.35, y: 4.42, w: 1.2, h: 0.32, fontFace: M, fontSize: 12, bold: true, charSpacing: 1.5, color: C.accentLight, isTextBox: true, margin: 0 });
    s.addText(a[1], { x: x + 0.35, y: 4.82, w: 5.15, h: 0.95, fontFace: F, fontSize: 24, charSpacing: -0.5, color: "FFFFFF", isTextBox: true, margin: 0, valign: "top" });
    s.addText(a[2], { x: x + 0.35, y: 5.85, w: 5.15, h: 1.1, fontFace: F, fontSize: 14, color: C.onDarkSub, isTextBox: true, margin: 0, valign: "top", lineSpacingMultiple: 1.14 });
  });
  s.addShape(pres.ShapeType.line, { x: MARGIN, y: 7.7, w: 18.5, h: 0, line: { color: "3A3A44", width: 0.75 } });
  s.addText("We built it, and it runs.", { x: MARGIN, y: 7.95, w: 12, h: 0.7, fontFace: F, fontSize: 34, charSpacing: -1, color: "FFFFFF", isTextBox: true, margin: 0, valign: "top" });
  s.addText("A frozen corpus, one verdict per response, and the misses left on the record. Every figure in this deck names the command that regenerates it, and the numbers that went against us are still here.", { x: MARGIN, y: 8.75, w: 13.5, h: 1.0, fontFace: F, fontSize: 16, color: C.onDarkSub, isTextBox: true, margin: 0, valign: "top", lineSpacingMultiple: 1.15 });
  footer(s, [{ t: "Reproduce everything: python -m eval.run_all", mono: true }, { t: "github.com/harshitsaini17/controlplane-ai" }], true);
  shell(s, 28, true);
}

pres.writeFile({ fileName: "/tmp/cap/deck_v2_content.pptx" }).then(() => console.log("staged content deck written"));
