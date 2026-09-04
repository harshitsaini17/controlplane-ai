# ControlPlane
## The real-time oversight gateway for enterprise AI

**Business Proposal · Accenture Innovation Challenge 2026 · Round 2 (Prototype Development)**

---

> **[GRAPHIC 1 — Cover architecture strip]** Six boxes, left to right, joined by arrows: `APP (one URL change)` → `INPUT LANE (PII scrub · injection screen)` → `MODEL (any provider, tiered)` → `SENTENCE BUFFER (checks before release)` → **`POLICY ENGINE (one verdict)`** [filled navy #071829, white text] → `AUDIT + HITL (evidence · review)`. Beneath: four outlined pill chips — **PASS** (#003c33), **EDIT** (#ff7759), **BLOCK** (#b30000), **ESCALATE** (#9b60aa). Caption: "Four verdicts. One accountable decision per response."

**Submitted by**

| Team b24bb1029 — Indian Institute of Technology Jodhpur | | |
|---|---|---|
| **Priyanshu Pandey** (Team Lead) | B24BB1029 | Bioengineering · 3rd year |
| **Harshit Saini** | B24CS1031 | Computer Science · 3rd year |
| **Jayant Soni** | B24CM1033 | Artificial Intelligence & Data Science · 3rd year |

**Date of submission:** 30 August 2026
**Repository:** *[insert public GitHub URL]* · **Companion deliverables:** README (PDF), demonstration video

**Citation convention used throughout this document.** Every quantitative claim carries a tag. `[B-nn]` denotes a **measurement from our own prototype**, reproducible by a named command in the public repository. `[M-nn]` denotes an **external source**, listed with publisher, date, URL, and our confidence assessment in Appendix C. Claims we could not source are marked `[model]` and stated as assumptions. This convention is not decoration — it is the operating principle of the product described here.

---

## Cover letter

To the evaluation panel,

Round 1 asked for a vision. Round 2 asks whether that vision survives contact with engineering reality. Ours did, and it kept the receipts.

What follows is the business case around software that runs today: a gateway you can start with one command, attack with a hostile prompt, audit down to the individual verdict, and reconfigure per business unit by editing a text file. Not a mockup, not a storyboard — a working prototype with 1,200+ passing tests, a frozen evaluation corpus, and a published ledger of every engineering decision and deviation made along the way.

We ask you to notice one thing in particular. During the preparation of this proposal, our market research returned a finding that **contradicted a differentiation claim we had made in an earlier draft**: hyperscaler guardrail engines do support per-use-case policies and fail-open/fail-closed configuration `[M-07]`. We deleted the claim and rebuilt our positioning on ground that survives the evidence — Section 6.4 documents the retraction in full. We did this three weeks before anyone would have checked, because the entire premise of our product is that claims about AI behaviour should be auditable. That includes ours.

Our PII detector's first blind score was 0.836 against our own 0.95 target `[B-02]`. It is printed on page after page of this document, next to the improved figure, because a company selling trust in AI cannot begin by hiding a number.

We would be glad to answer any question you have, and to run any test you would like to see.

Sincerely,
**Priyanshu Pandey**, on behalf of Team b24bb1029
Indian Institute of Technology Jodhpur

---

## Table of contents

| § | Section | What it answers |
|---|---|---|
| 1 | Executive summary | The proposition in one page |
| 2 | Introduction | Who we are, and what we set out to do |
| 3 | Problem statement and needs assessment | Why this problem is urgent and expensive |
| 4 | Proposed solution | What ControlPlane is and how it behaves |
| 5 | Methodology and approach | How it works technically, and how AI enables it |
| 6 | Scope of work and market position | What ships, what does not, and where we sit |
| 7 | Target users and buyers | Who feels the pain and who signs |
| 8 | Evaluation and measurement | Every number, with its source |
| 9 | Risk analysis | What can go wrong, including our own weak results |
| 10 | Budget, pricing, and business case | Model, unit economics, and the funding ask |
| 11 | Phased roadmap | P0 through P3, with exit criteria |
| 12 | Qualifications and experience | The team and its delivery record |
| 13 | Portfolio evidence | The prototype as its own case study |
| 14 | Benefits and value proposition | Why this, why us, why now |
| 15 | Conclusion and call to action | What we are asking for |
| 16 | Appendices | Reproduction commands, limitations register, sources |

**Suggested reading paths.** Evaluators: §1, §4, §8, §14. Investors: §1, §3, §6, §10, §14. Technical reviewers: §4, §5, §8, §16 plus the repository.

*— end of front matter —*

---

# 1 · Executive summary

Enterprises have adopted generative AI faster than they can supervise it. **72% of organisations now use generative AI in at least one business function, up from 33% a year earlier, yet over 80% of pilots never reach production, and only 6% report material EBIT impact** `[M-03]`. The blockers are not model quality. They are security, privacy, reliability, and the absence of production-grade controls `[M-03]`.

Meanwhile the regulatory clock has started. The EU AI Act carries penalties up to **€35 million or 7% of global turnover**, with GPAI obligations and administrative fines already active since August 2025 `[M-01]`. India's DPDP Act exposes enterprises to **up to ₹250 crore per instance** for failure to maintain reasonable security safeguards, with implementing rules now notified `[M-02]`. Gartner reports a **40% cancellation rate for advanced AI projects lacking governance frameworks** `[M-12]`.

**ControlPlane is a reverse-proxy oversight gateway.** Applications change one base URL. Every request and response then passes through detection lanes that score across three planes — performance, cost, and responsibility — and a single policy engine converges those signals into exactly one verdict: **Pass, Edit, Block, or Escalate**. The governing policy is a YAML file per business pipeline. Three pipelines can return three different verdicts on identical content with zero code difference `[B-01]`.

**The prototype works and its claims are checkable.**

> **[GRAPHIC 2 — KPI strip]** Five stone-filled cards: **840/840** policy-engine verdicts correct across the frozen corpus × 3 policies `[B-01]` · **1.000** PII precision, zero false alarms `[B-02]` · **0.133 ms** tier-1 PII detector P99 against a 2 ms budget `[B-05]` · **39/39** fault-injection assertions across 5 independent quiet-host runs `[B-07]` · **1,200+** tests green on two machines and CI `[B-09]`.

Two external comparisons make those numbers legible. Microsoft Presidio, the standard open-source PII detector, benchmarks at **0.431 span recall** on the AI4Privacy corpus `[M-08]`; our tier-1 pattern layer reaches **0.885 recall at 1.000 precision** on our frozen corpus `[B-02]` — different corpora, so not a head-to-head, but the gap is instructive and a like-for-like comparison is scheduled in P1. And published guidance puts the acceptable added latency for inline guardrails at **under 20–50 ms** `[M-11]`; our user-perceived input hold measures **27.49 ms P99** with the full detection stack live `[B-06]`.

**What we are asking for.** The challenge's backing, and an indicative pre-seed of **INR 1.6 crore (~US$190,000)** to convert this prototype into three design-partner pilots within two quarters (§10, §15).

*— end of section 1 —*

---

# 2 · Introduction

## 2.1 · Who we are

We are three third-year undergraduates at the Indian Institute of Technology Jodhpur, from bioengineering, computer science, and artificial intelligence backgrounds. We built ControlPlane over six weeks for this challenge.

The team has no prior enterprise software track record to present. In place of one, we offer something we believe is more informative: a **complete public engineering record** of how this system was built — 36 architecture decision records, 32 formally adjudicated engineering deviations, an independent AI reviewer that blocked releases four times, and a standing register of every limitation we did not resolve `[B-09]`. A reviewer can inspect our judgement directly rather than inferring it from a résumé.

## 2.2 · Our operating principle

We adopted one rule at the start and did not break it under deadline pressure: **no number ships unless a command in the repository reproduces it, and no unflattering number is removed once measured.** The evaluation corpus was authored, independently reviewed, and frozen *before* any detector was tuned. First measurements were taken blind. Revisions had to derive from published format specifications, never from the list of cases we failed.

This discipline cost us. It is why this document reports a missed target (§8), a detector with 0.150 recall (§8), and a calibration procedure that failed on our own data (§9). We kept them because a governance product whose own claims cannot be audited is a contradiction.

## 2.3 · The opportunity we are addressing

Enterprise AI governance is currently assembled from point tools: observability platforms that report after delivery, guardrail engines that filter single categories of harm, and gateways that route traffic. None of them makes one accountable, policy-governed decision per response across all three risk planes at once — and that is the layer enterprises need in order to move pilots into production under regulatory scrutiny `[M-03][M-12]`.

*— end of section 2 —*

---

# 3 · Problem statement and needs assessment

## 3.1 · The problem, concretely

A bank runs three AI assistants. The customer chatbot confidently states a loan approval that never happened — **wrong**. The internal HR assistant repeats an employee's phone number into a chat transcript — **leaky**. The advisory tool loops on a malformed integration and burns inference budget for a week — **expensive**. Three teams discover three incidents, weeks later, from three different systems.

The failures differ. The root cause is identical: **nothing is supervising the AI at the moment it speaks.**

## 3.2 · Evidence that the problem is real and large

| Evidence | Figure | Source |
|---|---|---|
| Enterprises using genAI in at least one function | 72%, up from 33% the prior year | `[M-03]` |
| Enterprise genAI pilots that never reach production | over 80% | `[M-03]` |
| Enterprises reporting >5% EBIT impact from genAI | 6% | `[M-03]` |
| Average production genAI use cases per large enterprise | 5.0, up 101% year over year | `[M-03]` |
| Documented (largely unvalidated) use cases per large enterprise | ~211 | `[M-03]` |
| Advanced AI projects cancelled for lack of governance | 40% | `[M-12]` |
| Enterprise AI systems classified high-risk / unclassified grey area | 18% / 40% | `[M-12]` |
| Estimated recurring EU-wide AI compliance cost | €3.3 billion annually | `[M-12]` |
| Unshielded production LLM endpoints vulnerable to automated adversarial injection | up to 80%+ | `[M-05]` |

The shape of the market is a **funnel that jams at production**. Enterprises have hundreds of ideas, five live use cases, and an 80% pilot failure rate `[M-03]`. Governance is not the only reason, but it is a named one — and it is the reason that a 40% cancellation statistic attaches to directly `[M-12]`.

## 3.3 · The regulatory forcing function

| Regime | Exposure | Status | Source |
|---|---|---|---|
| **EU AI Act** (Reg. (EU) 2024/1689) | €35M / 7% turnover (prohibited practices); €15M / 3% (high-risk, GPAI, transparency); €7.5M / 1% (misrepresentation) | In force; prohibited-practice ban since Feb 2025; GPAI obligations and administrative fines active since Aug 2025; Annex III high-risk deferred to Dec 2027 by Reg. (EU) 2026/1744 | `[M-01]` |
| **India DPDP Act 2023** | Up to **₹250 crore** per instance for failure of reasonable security safeguards; ₹200 crore for breach-notification failure; ₹150 crore for significant-data-fiduciary duties | Rules notified; Data Protection Board adjudication framework operational | `[M-02]` |
| **Sectoral regimes** (RBI/SEBI expectations, HIPAA, model-risk governance) | Licence, audit, and reputational exposure | Ongoing | `[M-12]` |

Two features of this landscape shape our design directly. First, **obligations vary by use case and jurisdiction** — the same model serving a customer chatbot and a credit-decision tool sits in two different risk classes. Any system that hard-codes one global policy is already wrong. Second, **compliance is becoming a procurement requirement**: buyers now demand automated logging, dataset lineage, and risk-tier evidence in vendor RFPs `[M-12]`.

## 3.4 · The security dimension

The OWASP GenAI LLM Top 10 ranks **prompt injection as the #1 risk (LLM01)** and **sensitive-information disclosure as #6 (LLM06)** `[M-05]`. Both are response-path problems. Neither is solvable by an offline evaluation report, because by the time the report runs, the response has been delivered.

## 3.5 · The needs assessment in one line

Enterprises need a **single, configurable, auditable decision point** in the AI delivery path — one that acts before the user sees the response, varies by business context, and produces the evidence a regulator will ask for.

*— end of section 3 —*

---

# 4 · Proposed solution

## 4.1 · What ControlPlane is

ControlPlane is a **reverse proxy between an application and its LLM provider**. Integration is one line: change the base URL. The application's code, prompts, and provider relationship are untouched.

Every request then flows through a governed pipeline:

1. **Ingress** resolves which business pipeline this request belongs to (an HTTP header or key mapping) and loads that pipeline's policy version.
2. **Input lane** — pattern detectors and a prompt-injection classifier run *before* the provider is called. PII in the prompt is redacted pre-dispatch, so **the model provider never receives the raw value**. An injection attempt is blocked at zero upstream token cost.
3. **Dispatch** — the request goes to the configured provider (cloud or fully local), with tiered model routing and a boot-time canary that sanity-checks the provider's own token accounting against a local estimate.
4. **Output lane** — streamed responses are buffered and checked **sentence by sentence**, so a flagged sentence never partially reaches the user. High-stakes pipelines run non-streaming and buffer fully, so nothing at all precedes the verdict.
5. **Policy engine** — all signals converge into exactly one verdict, by documented severity order.
6. **Audit and human review** — an append-only record is written (categories, never raw values); escalations enter a review queue for a human decision, with full lineage.

## 4.2 · The four verdicts

| Verdict | Meaning | User experience |
|---|---|---|
| **Pass** | No plane raised a signal above threshold | Response delivered unchanged |
| **Edit** | A transformable breach was found | Response delivered with the span redacted or the claim softened |
| **Block** | A non-transformable breach was found | Policy fallback message delivered instead of model output |
| **Escalate** | Ambiguous or high-stakes | Nothing delivered; quarantined for human review |

## 4.3 · The signature behaviour: same content, three verdicts

An assistant response repeating a customer's SSN produces:

- **support_bot** → **EDIT** — the span is redacted, the customer keeps their answer
- **hr_copilot** → **BLOCK** — internal policy says personal data does not pass, at all
- **finance_advisor** → **ESCALATE** — HTTP 202, quarantined, human review before anything is delivered

Identical detector stack. Identical content. **Only the YAML differs.** Verified across the frozen corpus at 840/840 verdicts `[B-01]`, and enforced structurally by a test that fails if any use-case name appears in executable code `[B-01]`.

## 4.4 · An illustrative day (composed entirely of behaviours that ship today)

**09:10** — Compliance edits the EU pipeline's policy file: one line, one reload call, policy v14 stamped onto every subsequent audit record. No deployment, no engineer. **11:32** — A customer pastes a card number; the model never sees it, the reply arrives redacted mid-stream, the audit logs the category and never the value. **14:05** — The advisory assistant produces an impressive but unsourced growth figure; the response is quarantined before delivery, an analyst approves it with a note after checking the filing, and the override joins the evidence trail. **16:40** — A scanning model times out under load; the support pipeline fails open with the gap itself audited, while the finance pipeline escalates to a human — one fault, two postures, both of them policy. **Friday** — The console exports the week per pipeline: verdicts, interception categories, latencies. The risk review's evidence pack, produced as a by-product of operating.

*— end of section 4 —*

---

# 5 · Methodology and approach

## 5.1 · How AI enables the solution

AI sits on both sides of the gateway.

**The watched side.** ControlPlane is provider-neutral. It speaks the OpenAI-compatible API, so it fronts commercial providers or a fully local model. Our demonstration runs against Groq-hosted open models and, as fallback, a local Ollama deployment — which is also the air-gapped deployment story for enterprises that cannot send data to a cloud provider.

**The watching side** is a deliberately tiered stack, because latency is a hard constraint — published guidance puts acceptable inline guardrail overhead at under 20–50 ms `[M-11]`:

| Layer | Mechanism | Measured performance |
|---|---|---|
| Deterministic patterns (PII, blocklist) | Compiled patterns derived from published format specifications (E.164, NANP, RFC 7515 JWT, Luhn) | P99 **0.133 ms** and **0.020 ms** against 2 ms budgets `[B-05]` |
| Lexical quality checks | Quantity-shape and citation-marker analysis for unsourced numeric claims | P99 **0.277 ms** against a 5 ms budget `[B-05]` |
| Quantized transformer classifiers | Prompt-injection and toxicity models, int8 on ONNX Runtime, CPU-only | P99 **25.348 ms** and **23.741 ms** against 25 ms budgets `[B-05]` |
| Embedding-based grounding + NER enrichment | Sentence-vs-context entailment; named-entity attachment for the overlapping-risk case | Within per-sentence hold budget `[B-06]` |

**No LLM sits in the decision path.** The verdict layer is deterministic — same signals plus same policy version always produce the same verdict. This is a design choice with a commercial rationale: a governance decision that cannot be explained or reproduced is not usable as compliance evidence.

## 5.2 · Three architectural decisions worth explaining

**Multi-label signals, because real risks overlap.** A fabricated claim about a named person is simultaneously a hallucination and a privacy exposure. Our data model emits **one signal carrying both labels** rather than two competing signals, and the policy engine — not the detector — resolves severity. Stacked-filter architectures cannot express this.

**Full-coverage windowing on the injection scanner.** A classifier with a fixed input window can be bypassed by padding the attack past the scored region. Our injection detector scores the **entire input** via overlapping strided windows and takes the worst-scoring window. This costs measurable latency on long inputs, and we publish that cost rather than truncating silently — relevant given prompt injection's OWASP #1 ranking `[M-05]`.

**Attribution-correct budget enforcement.** During development we discovered that measuring detector time by wall-clock caused event-loop scheduling noise to be charged to the detector, manufacturing spurious faults on roughly 7% of sentences under load — enough to flip a verdict in a fail-closed pipeline. We rebuilt enforcement to clock **detector-attributable CPU time**, which reduced spurious faults from 2-in-30 to **0-in-30** in the same test `[B-08]`. The wall-clock series is still published, just no longer used for enforcement.

## 5.3 · The development methodology

The system was built by AI coding agents operating under a binding engineering contract, with an independent AI reviewer and human adjudication of every departure from specification. The mechanics: documentation preceded code; any contradiction between spec and reality had to be **filed as a formal deviation and ruled on**, never silently resolved; measurement integrity rules forbade adjusting a target after a miss.

The record: **36 architecture decision records, 32 deviations filed and all 32 closed, 61 minor resolutions logged, 9 standing limitations published** `[B-09]`. The reviewer blocked the build four times. On four occasions the process corrected the human adjudicator's own errors — those are in the ledger too.

We describe this not as process theatre but because it is **directly transferable to the product's customers**: the discipline that produces auditable claims about our software is the same discipline enterprises need to produce auditable claims about their AI.

*— end of section 5 —*

---

# 6 · Scope of work and market position

## 6.1 · What ships in the prototype (P0 — complete)

| Deliverable | Status |
|---|---|
| Reverse-proxy gateway, OpenAI-compatible, streaming and non-streaming | Shipped |
| Three production-shaped pipeline policies (support / HR / regulated advisory) | Shipped |
| Input-lane pre-dispatch PII redaction and injection blocking | Shipped |
| Sentence-buffered output interception | Shipped |
| Six live detectors across the performance and responsibility planes | Shipped |
| Deterministic policy engine, four verdicts, multi-label convergence | Shipped |
| Per-pipeline fail-open / fail-closed failure posture | Shipped |
| Append-only audit store; human review queue with decision lineage | Shipped |
| Governance console, landing page, and live test-chat interface | Shipped |
| Frozen 280-case evaluation corpus + full measurement harness | Shipped |
| Scripted eight-beat demonstration with offline replay | Shipped |
| CI on two Python versions; two-machine runtime certification | Shipped |

## 6.2 · What does not ship (published as standing limitations, not omitted)

| Gap | Status | Plan |
|---|---|---|
| Cost-plane enforcement detectors | Policy schema and tiered routing ship; enforcement detectors are stubs | P1 |
| Override-driven threshold automation | Review decisions are captured with full lineage; the automated proposal script is a stub | P1 |
| Self-consistency scorer | Specified, unimplemented; the regulated pipeline's quality plane is covered by grounding instead | P1 |
| Calibrated thresholds | Calibration ran and **inverted** on our corpus; seeded thresholds ship, labelled as such (see §9) | P1, on partner traffic |
| Conversation-level tracking, deep-audit lane | Specified, unbuilt | P2 |

## 6.3 · Market size

> **[GRAPHIC 3 — Market bars]** Two horizontal bar pairs comparing the two analyst estimates: MarketsandMarkets **$0.89B (2024) → $5.78B (2029), 45.3% CAGR**; Grand View Research **$0.308B (2025) → $1.42B (2030), 35.7% CAGR**. Annotate the 4.08× divergence as a scope difference, not a contradiction.

| Analyst | Base | Terminal | CAGR | Scope | Source |
|---|---|---|---|---|---|
| MarketsandMarkets | $0.89B (2024) | **$5.78B (2029)** | 45.3% | Broad — includes MLOps/LLMOps and privacy software | `[M-04]` |
| Grand View Research | $0.308B (2025) | **$1.42B (2030)** | 35.7% | Narrow — pure-play governance software and third-party auditing | `[M-04]` |

The estimates differ by 4.08×, and the reason is definitional rather than a disagreement about growth: the broader figure absorbs adjacent developer tooling `[M-04]`. We quote both and use the **narrower** figure as our planning basis, because ControlPlane is pure-play governance middleware. Both sources agree on the direction: a mid-to-high-thirties-percent-plus CAGR through the end of the decade `[M-04]`.

**Our serviceable segment.** Regulated verticals plus India's Global Capability Centers — approximately **1,600–1,700 GCCs employing 1.6 million professionals, with over 70% running active generative-AI roadmaps** `[M-09]`. This segment carries direct DPDP exposure `[M-02]` alongside EU and US obligations for their parent organisations `[M-09]`, which makes per-jurisdiction policy governance a requirement rather than a preference.

## 6.4 · Competitive position — including a claim we retracted

> **[GRAPHIC 4 — 2×2 positioning map]** X-axis: *Post-hoc observation → Pre-delivery decision*. Y-axis: *Single-plane point tool → Converged multi-plane governance*. Plot: Arize, Langfuse, Datadog (upper-left); LangSmith (mid-left); Portkey, Kong, LiteLLM (mid-right); AWS Bedrock Guardrails, Azure Content Safety, NeMo Guardrails, Lakera (lower-right); Presidio, Google DLP (lower-mid). ControlPlane marked with a coral star in the upper-right quadrant.

| Player | Capitalisation / status | Strength | Where ControlPlane differs |
|---|---|---|---|
| **Portkey** | $18.1M raised; $15M Series A, Feb 2026 `[M-07]` | Unified AI gateway with observability and routing `[M-07]` | Gateway-first: routing and visibility, thin converged decision layer |
| **Lakera** | $30–40M raised `[M-07]` | Real-time AI application firewall; 97.6%+ true-positive blocking claimed `[M-05]` | Security plane only; no quality/cost convergence, no HITL verdict lineage |
| **Arize AI** | $131M raised; ~$1B valuation `[M-07]` | Enterprise observability and evaluation at scale `[M-07]` | Post-hoc by architecture — observes, cannot gate delivery |
| **Langfuse** | Acquired by ClickHouse, Jan 2026 `[M-07]` | Open-source tracing and prompt management `[M-07]` | Same post-hoc limitation; consolidation signals category maturation |
| **Robust Intelligence** | Acquired by Cisco `[M-07]` | Automated AI risk testing `[M-07]` | Testing-time, not delivery-path |
| **AWS Bedrock Guardrails / Azure AI Content Safety / NVIDIA NeMo** | Hyperscaler-native `[M-07]` | **Per-use-case policy configuration: yes. Fail-open/fail-closed: yes** `[M-07]` | Cloud-locked or single-plane; content-safety focus rather than converged quality+cost+responsibility verdicts; no cross-provider or air-gapped neutrality |
| **Microsoft Presidio / Google DLP** | Open source / cloud service | Broad PII category coverage; 0.431 span recall baseline on AI4Privacy `[M-08]` | Not a delivery-path decision system; we intend to integrate rather than compete (P1) |

### The retraction

An earlier draft of this proposal claimed that per-use-case policy configuration and configurable fail-open/fail-closed posture were unique to ControlPlane. **Primary-source research showed that claim to be false**: AWS Bedrock Guardrails, Azure AI Content Safety, and NVIDIA NeMo Guardrails all document both capabilities `[M-07]`. We removed the claim.

What survives the evidence, and what we now assert:

1. **Convergence across three planes into one verdict.** The hyperscaler engines are content-safety systems. None converges quality (grounding, unsourced claims), cost (budget, loop detection), and responsibility (PII, injection, toxicity) into a single accountable decision per response.
2. **Multi-label overlapping risk.** One signal carrying both a hallucination and a privacy label, resolved by the engine rather than by filter order.
3. **Provider and deployment neutrality.** Cross-provider by construction, including fully local and air-gapped operation — structurally unavailable from a cloud-native guardrail service.
4. **Evidence as a product surface.** Frozen corpus, blind-first measurement, published misses, and a claim-to-command map. No competitor in this table publishes an auditable accuracy claim about its own detectors.
5. **A process record that cannot be reconstructed retroactively.** The adjudication ledger accrues in the order it was created.

We would rather present five defensible differentiators than six, one of which fails on inspection.

*— end of section 6 —*

---

# 7 · Target users and buyers

| Persona | Pain today | What ControlPlane provides | Evidence of pain |
|---|---|---|---|
| **Head of Platform / AI Engineering** | Every new use case re-solves oversight; N apps × M providers × ad-hoc guardrails | One gateway, one policy schema; a new pipeline is one YAML file and one header | 5.0 production use cases and ~211 documented ones per large enterprise `[M-03]` |
| **CISO / DPO / Compliance** | Cannot evidence AI oversight to auditors; direct statutory exposure | Append-only audit trail, per-jurisdiction policy packs, HITL decision lineage | ₹250 crore DPDP exposure `[M-02]`; €35M / 7% EU exposure `[M-01]` |
| **Risk / model governance (BFSI)** | Regulator expects demonstrable human-in-the-loop supervision | Escalation queue, fail-closed posture, versioned policy diffs as change evidence | 18% of AI systems high-risk, 40% unclassified `[M-12]` |
| **FinOps / engineering finance** | Inference spend unattributed and unmanaged | Per-pipeline budget policy and tiered routing (enforcement in P1) | 15–25× flagship-to-mini price premium `[M-06]` |
| **Head of AI programme** | Pilots stall before production; projects cancelled | Governance as a precondition rather than an afterthought | 80%+ pilot failure `[M-03]`; 40% cancellation without governance `[M-12]` |

**Initial ideal customer profile.** Mid-to-large enterprises running three or more production genAI use cases in regulated or brand-sensitive contexts — BFSI, healthcare, telecommunications — and India's Global Capability Centers, where **1,600+ centres** `[M-09]` sit at the intersection of DPDP obligations `[M-02]` and their parents' EU/US obligations `[M-01]`. We start there deliberately: it is the segment we can reach, and the segment where the regulatory clock is loudest.

*— end of section 7 —*

---

# 8 · Evaluation and measurement

This section is the core of our proposal. Every figure below is produced by a command in the public repository and committed as a report artifact.

## 8.1 · Correctness of the decision layer

| Metric | Result | Tag |
|---|---|---|
| Policy-engine conformance | **840/840** verdicts correct (280 frozen cases × 3 policies) | `[B-01]` |
| Falsification of that result | **7/7** deliberately injected defects detected by the same harness | `[B-01]` |
| Structural governance guarantee | Test fails if any use-case name reaches executable code | `[B-01]` |

A perfect score is suspicious by default, so we required it to be falsifiable: we injected seven defects that violate documented decisions and confirmed the harness catches every one `[B-01]`.

## 8.2 · Detection quality — including what we missed

| Detector | Blind (first contact) | After disclosed revision | Target | Tag |
|---|---|---|---|---|
| Tier-1 PII — recall | 0.836 | **0.885** | 0.95 — **MISSED** | `[B-02]` |
| Tier-1 PII — precision | 1.000 | **1.000** | none set | `[B-02]` |
| Unsourced numeric claims — precision | 0.267 | **0.857** | none set | `[B-03]` |
| Prompt injection (blind) | P **1.000**, R **0.150** | not tuned | none set | `[B-04]` |
| Toxicity, high band (blind) | P **0.400**, R **0.250** | not tuned | none set | `[B-04]` |
| End-to-end verdict accuracy | — | **0.825–0.851** over 194 covered cases (up from 159) | none set | `[B-10]` |

Four things to read carefully here.

**The PII target was missed and the target did not move.** All seven residual misses fall into a single documented scope exclusion. The blind figure ships permanently next to the revised one `[B-02]`. For external context, Microsoft Presidio benchmarks at **0.431 span recall** on the AI4Privacy corpus `[M-08]`; fine-tuned transformer approaches reach 0.855 there `[M-08]`. Different corpus, so this is not a head-to-head claim — the like-for-like comparison against Presidio on our frozen corpus is a P1 commitment.

**The numeric-claims precision jump came from fixing our specification, not our code.** The original rule classified identifier-shaped numbers as statistical claims. We corrected the specification and re-measured `[B-03]`.

**Injection recall of 0.150 is weak, and we publish it.** No target was set for this detector and no tuning was performed against the frozen corpus, by protocol. It is a first-contact number for an untuned model layer sitting behind a pattern layer that already stops overt attacks. Given prompt injection's OWASP #1 status `[M-05]`, this is our most important P1 work — and the honest statement is that our defence here is layered and incomplete, not solved.

**The end-to-end score fell as coverage rose.** From 0.981 over 159 cases to **0.825–0.851 over 194 cases** `[B-10]`. The system did not get worse; the measurement got broader, admitting the hardest classes. Reporting the improvement without the coverage change would have been misleading.

## 8.3 · Latency

| Series | Measured | Target | Verdict | Tag |
|---|---|---|---|---|
| Input hold (user-perceived) | P50 21.58 / **P99 27.49 ms** | < 40 / < 50 ms | Met | `[B-06]` |
| Sentence hold (user-perceived) | P50 21.00 / **P99 39.59 ms** | < 40 / < 100 ms | Met | `[B-06]` |
| tier1_blocklist | P99 **0.020 ms** | 2 ms | Met | `[B-05]` |
| tier1_pii | P99 **0.133 ms** | 2 ms | Met | `[B-05]` |
| numeric_claims | P99 **0.277 ms** | 5 ms | Met | `[B-05]` |
| tier2_toxicity | P99 **23.741 ms** | 25 ms | Met | `[B-05]` |
| tier2_injection | P99 **25.348 ms** | 25 ms | **BREACH — published** | `[B-05]` |

Published guidance places acceptable inline guardrail overhead at **under 20–50 ms** `[M-11]`. Our user-perceived holds sit inside that band with the full stack live `[B-06]`. One detector exceeds its own internal budget by 0.348 ms at P99; we publish the breach and did not move the budget `[B-05]`.

## 8.4 · Reliability

| Property | Result | Tag |
|---|---|---|
| Fault-injection assertions | **39/39** across 5 independent quiet-host runs | `[B-07]` |
| Fail-closed behaviour | Never silently blocks — always escalates to a human | `[B-07]` |
| Same fault, different pipelines | Passes under fail-open policies, escalates under fail-closed | `[B-07]` |
| Spurious faults after enforcement fix | 2/30 → **0/30** | `[B-08]` |
| Raw PII present anywhere in audit evidence | **0 occurrences**, verified by direct database search | `[B-11]` |

## 8.5 · Engineering base

| Property | Result | Tag |
|---|---|---|
| Automated tests | **1,200+**, green on Linux and Apple Silicon, plus CI on Python 3.12 and 3.14 | `[B-09]` |
| Evaluation corpus | 280 cases, independently reviewed, frozen before tuning, digest-verified each run | `[B-09]` |
| Decision records / deviations / limitations | 36 ADRs · 32 deviations, all closed · 9 standing limitations | `[B-09]` |
| Published figures re-derived from source artifacts | **72/72** verified | `[B-09]` |

*— end of section 8 —*

---

# 9 · Risk analysis

We lead with our own weakest results, because a risk section that omits them would be the first thing a diligent investor discovers.

| # | Risk | Honest reality | Mitigation |
|---|---|---|---|
| 1 | **Detection quality is incomplete** | Injection recall 0.150 blind `[B-04]`; toxicity high-band recall 0.250 `[B-04]` | Layered defence: deterministic patterns already stop overt attacks at microsecond cost `[B-05]`. Thresholds are designed to be tuned on real traffic through the feedback loop — the paid enterprise motion. Publishing these numbers is what makes the improved ones credible. |
| 2 | **Calibration failed on our own data** | The conformal threshold procedure **inverted** (τ_low ≥ τ_high) at every α tried, across 5 seeds `[B-12]`. Seeded thresholds ship, labelled | The harness worked — it detected that the grounding confidence signal does not yet separate classes on a synthetic corpus. We did not re-pick α to force a clean result, because selecting a parameter after seeing it fail is tuning toward an outcome. Real-traffic calibration in P1. |
| 3 | **Hyperscaler bundling** | AWS, Azure, and NVIDIA ship guardrail engines with per-use-case policies and fail posture `[M-07]` | Compete on convergence, neutrality, and evidence (§6.4), not on features they already have. Cross-provider and air-gapped operation is structurally unavailable to them. |
| 4 | **Latency objections** | One detector breaches its budget at P99 `[B-05]`; full-coverage injection windowing costs more on long inputs | Deterministic tier is three orders of magnitude inside budget `[B-05]`; user-perceived holds meet published expectations `[M-11]`. Compiled data plane in P2; per-pipeline token bound is the policy-level pressure valve. |
| 5 | **Synthetic-corpus overfit critique** | Fair for any self-built evaluation. Our corpus is ours | Frozen before tuning; blind-first protocol; independently reviewed. P1 commits to a Presidio head-to-head `[M-08]` on the same corpus and calibration on partner traffic. |
| 6 | **Provider churn** | A model tier we depended on was deprecated 11 days before this submission | It failed **loudly, not silently** — provenance-classed providers and the accounting canary are shipped features that exist because of this class of event. Both replacements were verified live before rebinding. |
| 7 | **Market timing / category risk** | Analyst estimates diverge 4.08× on market size `[M-04]`; consolidation is already underway (Cisco/Robust Intelligence, ClickHouse/Langfuse) `[M-07]` | Consolidation validates the category. Open-core distribution reduces dependence on any single analyst forecast; both estimates agree on 35%+ CAGR `[M-04]`. |
| 8 | **Team capacity** | Three third-year undergraduates, no enterprise delivery history | A complete public delivery record most professional teams cannot produce `[B-09]`. Funding converts documented process into hired capacity. The SI channel `[M-10]` supplies deployment scale. |
| 9 | **Open-core monetisation** | Free tier could cannibalise paid | Paid surfaces are the ones enterprises cannot self-serve: compliance policy packs, audit retention, per-customer calibration, SLAs. The gateway itself being free is what drives the adoption we monetise. |

*— end of section 9 —*

---

# 10 · Budget, pricing, and the business case

## 10.1 · Revenue model — open core

| Tier | What is included | Price posture |
|---|---|---|
| **Open source** (Apache-2.0) | Gateway, policy engine, detectors, audit schema, evaluation harness — the full prototype lineage | Free — adoption, community, credibility |
| **Team** | Governance Console (hardened), SSO, retention, alerting | US$500–1,000 per production pipeline per month `[model]` |
| **Enterprise** | Compliance policy packs (EU AI Act, DPDP, RBI/SEBI, HIPAA), audit export, air-gapped and local-model deployment, SLAs, calibration on customer traffic | US$40,000–120,000 ACV `[model]` |

Per-pipeline pricing means revenue tracks the customer's own AI adoption curve — currently averaging 5.0 production use cases and growing 101% year over year `[M-03]`.

## 10.2 · Unit economics `[model]`

| Metric | Assumption | Basis |
|---|---|---|
| Blended ACV | US$35,000–50,000 | One enterprise logo ≈ 3–5 paid pipelines plus pack/SLA uplift |
| Gross margin | ~85% | Software plus thin sampling; the customer pays their own model spend |
| CAC (partner-led) | US$10,000–18,000 | SI-attached deals and OSS inbound; no outbound sales team in years 1–2 |
| Payback | < 6 months | ACV ÷ CAC at the above |
| Expansion | 1 pipeline → 4–6 within 12–18 months | Tracks documented enterprise use-case growth `[M-03]` |

**Three-year outline `[model]`:** Year 1, 4–6 pilot conversions (~US$150–250k ARR). Year 2, partner-led repeatability (~US$1–1.5M ARR). Year 3, 120–180 accounts at blended ACV (US$5–8M ARR) — which is between 0.35% and 0.56% of the narrower analyst market estimate for 2030 `[M-04]`, a deliberately modest share assumption.

## 10.3 · The cost argument

Published pricing shows a **15× to 25× premium for flagship models over small models**, with a specific documented pair at 20.0× on input and 16.67× on output `[M-06]`. ControlPlane's tiered routing sends routine traffic to the small tier and reserves the frontier tier for genuine escalations. Our own demonstration configuration runs a 2.0× tier gap, so we report savings as **relative** rather than absolute, and note that they scale with the deployment's own ratio `[B-13]` — at the industry-typical 15–25× gap `[M-06]`, identical routing decisions save proportionally more.

**We do not publish an absolute savings figure**, because the cost-plane enforcement detectors are P1 (§6.2). Claiming a dollar number we have not measured would violate the principle this document is built on.

## 10.4 · The funding ask

**Indicative pre-seed: INR 1.6 crore (~US$190,000) for 12 months** `[model]`.

> **[GRAPHIC 5 — Use of funds]** One stacked horizontal bar: navy **60% — founding team plus one senior engineer**; green **20% — pilot infrastructure and compliance advisory (DPDP / AI Act policy-pack review)**; coral **20% — GTM, developer relations, and open-source community**.

| Quarter | Milestone gate |
|---|---|
| Q1 | Open-source launch; 3 design-partner pilots signed; Console GA track scoped |
| Q2 | 3 pilots live; first partner-traffic calibration cycles; expanded-corpus recall target met or explained |
| Q3 | Threshold and quality targets met on partner traffic; first paid conversions |
| Q4 | SOC 2 kickoff; repeatable SI-attached deal template; year-2 plan grounded in pilot data |

## 10.5 · Go-to-market

| Phase | Motion | Proof point |
|---|---|---|
| **Launch** (0–3 mo) | Open-source release plus the build-in-public story — the adjudication ledger and blind-measurement discipline are genuinely distinctive developer content; conference submissions on "AI built under AI oversight" | Top-of-funnel attention; inbound design-partner pipeline |
| **Design partners** (2–6 mo) | 3–5 pilots across Indian BFSI/GCC `[M-09]` plus one EU-exposed SaaS `[M-01]`; success is defined as one pipeline in production with audit evidence accepted by the partner's risk function | Reference architecture; first case studies; calibration playbook |
| **Partner-led** (6–18 mo) | Systems-integrator channel. Accenture alone has committed **$3 billion over three years** to Data & AI and doubled its practice to **80,000 specialists** with Responsible AI frameworks across 19 industries `[M-10]` | Repeatable SI-attached deals; first US$1M ARR `[model]` |

The flywheel: open-source adoption produces policy patterns and calibration data; patterns become packaged compliance packs; packs make SI deployments faster; SI deployments produce references that pull further adoption.

*— end of section 10 —*

---

# 11 · Phased roadmap

> **[GRAPHIC 6 — Roadmap timeline]** Horizontal line, four milestones: **P0 Prototype** (green, "DONE — this submission") → **P1 Pilot-ready** ("0–3 months") → **P2 Product** ("3–9 months") → **P3 Scale** ("9–18 months").

| Phase | Scope | Exit criteria |
|---|---|---|
| **P0 · Prototype** — complete | Gateway, six live detectors, policy engine, audit and HITL, console, demo, full evidence pipeline | This submission `[B-09]` |
| **P1 · Pilot-ready** (0–3 mo) | Cost-plane enforcement and override-driven threshold automation (the two disclosed gaps); expanded PII categories including Indic locales; threshold tuning on partner traffic; self-consistency scorer; **Presidio head-to-head on the frozen corpus** `[M-08]`; conversation-level cumulative risk | Recall ≥ 0.95 on the expanded corpus or a documented explanation; 3 pilots live |
| **P2 · Product** (3–9 mo) | Governance Console GA; compliance policy packs mapped to AI Act and DPDP obligations `[M-01][M-02]`; compiled data plane for sub-millisecond holds at scale; multi-tenant isolation; SOC 2 programme | First paid conversions; latency targets held at 10× load |
| **P3 · Scale** (9–18 mo) | Kubernetes sidecar and service-mesh deployment; agent-action gating (tool-call firewall for agentic workflows, per OWASP indirect-injection risk `[M-05]`); cloud-marketplace listings; certified policy packs with SI partners | Partner-led revenue; US$1M ARR `[model]` |

**Our roadmap is our limitations register.** Each P1 item corresponds to a numbered standing limitation published in the repository. We are not proposing features we imagined; we are proposing to close gaps we measured.

*— end of section 11 —*

---

# 12 · Qualifications and experience

## 12.1 · The team

| Member | Role | Background |
|---|---|---|
| **Priyanshu Pandey** (B24BB1029) | Team lead — architecture, adjudication, product | Bioengineering, 3rd year, IIT Jodhpur |
| **Harshit Saini** (B24CS1031) | Systems and engineering | Computer Science, 3rd year, IIT Jodhpur |
| **Jayant Soni** (B24CM1033) | Detection stack, evaluation, data | Artificial Intelligence & Data Science, 3rd year, IIT Jodhpur |

## 12.2 · What we demonstrated in six weeks

- A working reverse-proxy gateway with streaming interception, three governed pipelines, and six live detectors `[B-09]`
- 1,200+ tests, certified on two independent machines and CI across two Python versions `[B-09]`
- A 280-case corpus authored, independently reviewed, and frozen before any tuning `[B-09]`
- 36 architecture decision records; 32 deviations filed and adjudicated to closure `[B-09]`
- 72 of 72 published figures independently re-derived from their source artifacts `[B-09]`
- Discovery and correction of a real accounting anomaly in a third-party gateway that was injecting roughly 5,000 hidden prompt tokens per request — caught by our own canary `[B-14]`

## 12.3 · Why this substitutes for a track record

We cannot show enterprise references. We can show something an enterprise buyer arguably values more: **a complete, timestamped record of how we behave when we are wrong.** The ledger contains four occasions where an independent reviewer blocked our build and was right; four where the process caught the human adjudicator's own errors; and one where market research contradicted a claim in this very document and we retracted it (§6.4).

For a company whose product is trust in AI systems, that record is the qualification.

*— end of section 12 —*

---

# 13 · Portfolio evidence — the prototype as its own case study

We have no prior clients. Instead, we offer the prototype as a documented case study in the exact problem we sell into.

**Situation.** Build an AI oversight system in six weeks with three student engineers and no prior enterprise codebase.

**Approach.** Rather than write code first, we specified the system, then had AI coding agents implement it under a binding engineering contract with an independent AI reviewer and human adjudication of every deviation.

**Complications encountered, and resolved on the record.**

| Incident | Resolution | Product consequence |
|---|---|---|
| A third-party gateway silently injected ~5,000 hidden prompt tokens per request, corrupting every cost measurement | Detected by a boot-time canary comparing provider accounting against a local estimate `[B-14]` | Provenance-classed providers and the accounting canary became shipped features |
| A model tier we depended on was deprecated 11 days before submission | The canary and provenance classes made it fail loudly; replacements verified live and rebound | Validated the design decision under real conditions |
| Wall-clock budget enforcement manufactured spurious detector faults under load, enough to flip a verdict in a fail-closed pipeline | Rebuilt enforcement around detector-attributable CPU time; spurious faults 2/30 → 0/30 `[B-08]` | Attribution-correct enforcement, a differentiator in §6.4 |
| Our calibration procedure inverted on our own corpus | Published as a standing limitation; α was not re-picked to force a clean result `[B-12]` | Honest threshold labelling; real-traffic calibration became the P1 paid motion |
| Market research contradicted our own differentiation claim | Claim retracted, positioning rebuilt (§6.4) `[M-07]` | A more defensible five-point differentiation |

**Result.** A working system, a complete evidence trail, and — we would argue — a demonstration that the governance model we are selling actually works when applied to real engineering under real deadline pressure.

*— end of section 13 —*

---

# 14 · Benefits and value proposition

## 14.1 · For the enterprise buyer

| Benefit | Mechanism | Supporting evidence |
|---|---|---|
| **Prevent incidents rather than discover them** | Verdicts are issued before delivery; a flagged sentence never partially reaches the user | 840/840 conformance `[B-01]`; sentence-buffered interception `[B-06]` |
| **Provider never sees regulated data** | Input-lane PII redaction happens pre-dispatch | Live behaviour; 0 raw values in audit evidence `[B-11]` |
| **Evidence for the regulator, as a by-product** | Append-only records, categories not values, HITL decision lineage, policy version stamped per record | Direct response to AI Act oversight duties `[M-01]` and DPDP safeguards `[M-02]` |
| **Governance without redeployment** | Policies are versioned YAML, hot-reloadable, per pipeline and per jurisdiction | Three pipelines diverge with zero code difference `[B-01]` |
| **Failure has a defined posture** | Fail-open versus fail-closed is a policy field; fail-closed escalates to a human and never silently blocks | 39/39 fault assertions across 5 runs `[B-07]` |
| **Cost control at the gate** | Budget policy and tiered routing; enforcement in P1 | 15–25× flagship-to-mini price premium makes routing material `[M-06]` |
| **No cloud lock-in** | Provider-neutral, including fully local and air-gapped operation | Demonstrated against both a cloud provider and a local model |

## 14.2 · Why now

Three clocks are running simultaneously. **Regulatory:** GPAI obligations and administrative fines are already active; Annex III high-risk obligations land December 2027 `[M-01]`; DPDP rules are notified `[M-02]`. **Market:** 35–45% CAGR through 2029–30 `[M-04]`, with consolidation already underway `[M-07]`. **Operational:** 80%+ of pilots stall before production `[M-03]` and 40% of ungoverned advanced-AI projects are cancelled `[M-12]`.

The window in which a converged governance layer can establish itself as the category standard is open now and will not stay open.

## 14.3 · Why us

We are not the best-capitalised team in this space — Arize alone has raised $131 million `[M-07]`. We are, as far as our research could determine, **the only team of any size publishing auditable accuracy claims about its own detectors, including the failures.** In a market whose entire product is trust, that is the asset that compounds.

*— end of section 14 —*

---

# 15 · Conclusion and call to action

Enterprises are deploying AI faster than they can supervise it. 72% use it; 80%+ of pilots die before production; the regulatory penalties are now measured in tens of millions of euros and hundreds of crores of rupees `[M-01][M-02][M-03]`. The supervision layer they need — one accountable, configurable, evidence-producing decision per response — does not exist as a converged product.

**We built it, and it runs.** 840/840 verdicts correct on a frozen corpus `[B-01]`. Sub-millisecond deterministic detection `[B-05]`. Human-in-the-loop escalation with full lineage. 1,200+ tests on two machines `[B-09]`. Nine published limitations, because the ones we did not solve are documented rather than hidden.

**What we ask of this panel:**

1. **Select ControlPlane** to advance in the Accenture Innovation Challenge 2026.
2. **Open the design-partner conversation** inside Accenture's responsible-AI practice — a practice backed by a $3 billion commitment and 80,000 specialists `[M-10]`, and the exact channel through which a governance layer reaches enterprise clients.
3. **Consider the indicative pre-seed of INR 1.6 crore** (§10.4) to convert this prototype into three live pilots within two quarters.

**And we invite the test we think matters most:** clone the repository, run one command, and check any number in this document. We built it so that you could.

> *Every company is deploying AI faster than it can supervise it. We built the supervision — configurable per business context, honest about its numbers, and proven by the way it was built.*

## **ControlPlane: oversight for AI, built under oversight.**

**Team b24bb1029** · Priyanshu Pandey · Harshit Saini · Jayant Soni
Indian Institute of Technology Jodhpur · 30 August 2026

*— end of section 15 —*

---

# 16 · Appendices

## Appendix A — Reproduction commands for every `[B-nn]` claim

| Tag | Claim | Command | Artifact |
|---|---|---|---|
| B-01 | Policy-engine conformance 840/840; 7/7 mutation kill; no use-case name in code | `python -m eval.run_all` | `reports/eval_report.md` |
| B-02 | PII precision 1.000; recall 0.836 → 0.885 | `python -m eval.run_all` | `reports/eval_report.md` |
| B-03 | Numeric-claims precision 0.267 → 0.857 | `python -m eval.run_all` | `reports/eval_report.md` |
| B-04 | Injection P 1.000 / R 0.150; toxicity high P 0.400 / R 0.250 (blind) | `python -m eval.run_all` | `reports/eval_report.md` |
| B-05 | Per-detector latency and the published breach | `python -m eval.bench_latency --check` | `reports/latency_report.md` |
| B-06 | Input and sentence hold percentiles | `python -m eval.bench_latency` | `reports/latency_report.md` |
| B-07 | Fault injection 39/39 across 5 runs | `python -m eval.fault_injection --reps 5` | `reports/fault_injection_report.md` |
| B-08 | Spurious-fault reduction 2/30 → 0/30 | Recorded in the decision record for attribution-correct enforcement | `docs/03-decisions.md` |
| B-09 | Test count, corpus freeze, ADR and deviation counts, 72/72 re-derivation | `python -m pytest -q` · `python -m eval.validate_dataset --freeze` · `python -m eval.check_derivations` | `docs/`, CI |
| B-10 | End-to-end 0.825–0.851 over 194 cases | `python -m eval.run_all` | `reports/eval_report.md` |
| B-11 | Zero raw PII in audit evidence | Security test in the suite; manual DB search documented in `docs/TESTING.md` | test suite |
| B-12 | Calibration band inversion across 5 seeds | `python -m eval.run_all` (calibration section) | `reports/eval_report.md` |
| B-13 | Relative cost-cascade framing and tier ratio | Tier pricing in `config/gateway.yaml`; simulation is P1 | `config/`, roadmap |
| B-14 | Hidden-token injection detected by the accounting canary | Decision record for provenance-classed providers | `docs/03-decisions.md` |

Full manual walkthrough, including the same-content-three-verdicts test from a terminal: `docs/TESTING.md`.

## Appendix B — Standing limitations (the full honest register)

1. **SL-1** — Tier-1 PII recall 0.885 against a 0.95 target. Missed; target not moved. All seven residual misses are one documented scope exclusion.
2. **SL-2** — Phone-number pattern behaves as a superset of the v1 specification.
3. **SL-3** — Provider pricing provenance requires re-verification at each release.
4. **SL-4** — Local fallback model dependency (resolved during this phase).
5. **SL-5** — Detector latency budgets measured with multiple threads free; single-thread contention degrades them.
6. **SL-6** — Self-consistency scorer specified but unimplemented; the regulated pipeline's quality plane is covered by grounding.
7. **SL-7** — Calibration band inverts on the frozen corpus at every α tried; seeded thresholds ship, labelled.
8. **SL-8** — Injection detector P99 25.348 ms against a 25 ms budget. Published as a breach; budget not moved.
9. **SL-9** — Cost-plane enforcement detectors and override-driven threshold automation are not built; the three-planes claim is qualified accordingly.

## Appendix C — External sources `[M-nn]`

| Tag | Claim used | Source | Date | Confidence |
|---|---|---|---|---|
| M-01 | EU AI Act penalty tiers (€35M/7%, €15M/3%, €7.5M/1%) and phase-in through Dec 2027 | Regulation (EU) 2024/1689; Regulation (EU) 2026/1744 — eur-lex.europa.eu | Jul 2024 / Jul 2026 | High |
| M-02 | DPDP Act penalties up to ₹250 crore; rules notified | MeitY / PIB, DPDP Rules 2025 notification | Aug 2023 / Nov 2025 | High |
| M-03 | 72% adoption; 80%+ pilot failure; 6% EBIT impact; 5.0 production use cases | McKinsey *State of AI 2025*; Gartner enterprise AI survey series | 2025 | High (secondary aggregator used for retrieval — verify against McKinsey original before external distribution) |
| M-04 | Market $0.89B→$5.78B at 45.3% CAGR; $0.308B→$1.42B at 35.7% CAGR | MarketsandMarkets; Grand View Research | Jan 2025 / Sep 2024 | High (4.08× scope divergence noted in text) |
| M-05 | OWASP LLM01 prompt injection, LLM06 sensitive-information disclosure; 80%+ endpoint vulnerability | OWASP GenAI LLM Top 10; Lakera security benchmark | Aug 2026 | High |
| M-06 | 15–25× flagship-to-mini price premium; 20.0× input / 16.67× output on a documented pair | OpenAI published API pricing | Aug 2026 | High |
| M-07 | Competitor funding; hyperscaler per-use-case and fail-posture support (**basis for our §6.4 retraction**) | Tracxn, Crunchbase, AWS / Microsoft / NVIDIA official documentation | Feb 2026 | High |
| M-08 | Presidio 0.431 span recall on AI4Privacy; fine-tuned transformers 0.855 | arXiv:2608.02616v1 | Aug 2026 | High |
| M-09 | ~1,600–1,700 Indian GCCs; 1.6M professionals; 70%+ with genAI roadmaps | NASSCOM / MeitY GCC ecosystem reporting | Nov 2025 | Medium |
| M-10 | Accenture $3B Data & AI investment; 80,000 specialists; 19 industries | Accenture Newsroom | Jun 2023 (programme confirmed active in 2025 releases) | High (base release >24 months old) |
| M-11 | Inline guardrail overhead budget of <20–50 ms | Lakera architecture guidance; AWS Bedrock CloudWatch guardrail metrics | 2024 / Aug 2026 | High |
| M-12 | 18% high-risk / 40% unclassified; €3.3B EU compliance cost; 40% cancellation without governance | appliedAI / DIGITALEUROPE compliance study; Gartner | Jul 2026 | High |

**Citation integrity note.** Three sources above carry caveats we state rather than conceal: M-03 was retrieved through a secondary aggregator and should be verified against the McKinsey original before external distribution; M-09 rests partly on a base document older than 24 months; M-10's founding press release is from 2023, though the programme is confirmed active in 2025 releases. We apply the same disclosure standard to our sources that we apply to our own measurements.

## Appendix D — Production notes for PDF conversion *(delete this appendix before export)*

- **Palette:** navy `#071829` (section bands, headers) · deep green `#003c33` · coral `#ff7759` (accents, retraction callouts) · stone `#eeece7` (card fills) · red `#b30000` · violet `#9b60aa` · hairline `#d9d9dd`.
- **Type:** headings in a clean grotesk (Space Grotesk or similar), weight 400–700; body Inter or Helvetica at 9.5–10.5 pt; all figures tabular-numeral.
- **Section openers:** each `# N ·` heading starts a new page with a full-width navy band — large section number at left, title and italic tagline at right in white. Each `*— end of section N —*` line renders small, centred, grey.
- **Six graphics** are specified inline as `[GRAPHIC N]` blocks with complete build instructions. All six exist pre-rendered in `b24bb1029_ControlPlane_Business_Proposal_v2.pdf` and can be screenshotted directly.
- **Recommended additions:** a screenshot of the console's verdict board in §4.3; a chat-page screenshot showing a live EDIT verdict with visible redaction in §4.2; team photographs on the cover; a QR code to the public repository in §15.
- **Do not remove:** any `[B-nn]` or `[M-nn]` tag, the `[model]` markers, the §6.4 retraction, or Appendix B. They are the argument, not the hedging.
