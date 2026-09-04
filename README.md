# ControlPlane.ai — Real-Time AI Oversight Gateway

A reverse proxy that checks every LLM response across performance, cost, and responsibility before deciding whether to pass, edit, block, or escalate it.

[![CI](https://github.com/harshitsaini17/controlplane-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/harshitsaini17/controlplane-ai/actions/workflows/ci.yml) ![Python 3.12 and 3.14](https://img.shields.io/badge/Python-3.12%20%7C%203.14-3776AB) ![README tests passing](https://img.shields.io/badge/README%20tests-passing-brightgreen) ![License not chosen](https://img.shields.io/badge/license-not%20chosen-lightgrey) ![Round 2 · AIC 2026](https://img.shields.io/badge/Round%202%20%C2%B7%20AIC-2026-6B46C1)

Point an OpenAI-compatible client at one URL and select a policy with one header. The same response can be edited for support, blocked for HR, and escalated for finance: the difference is YAML configuration, not application code.

**Contents** · [30-second demo](#the-30-second-demo) · [Quick start](#quick-start) · [What it does](#what-it-does) · [Architecture](#architecture) · [The policy engine](#the-policy-engine) · [Detectors and signals](#detectors-and-signals) · [Interfaces](#interfaces) · [Audit and evidence](#audit-and-evidence) · [Key results](#key-results) · [Why this is different](#why-this-is-different) · [What doesn't ship](#what-doesnt-ship) · [Structure](#project-structure) · [Testing](#development-and-testing) · [How it was built](#how-it-was-built) · [Team](#team-and-submission)

## The 30-second demo

These are the live one-URL integration calls. Live upstream text is nondeterministic; the expected lines are the replay-verified audit verdicts when the scripted demo returns frozen fixture PII-001 as the upstream response.

~~~sh
PROMPT='Confirm the record on file.'

curl -sS http://localhost:8080/v1/chat/completions -H 'Content-Type: application/json' -H 'X-ControlPlane-Use-Case: support_bot' -d "{\"model\":\"small\",\"messages\":[{\"role\":\"user\",\"content\":\"$PROMPT\"}]}"
# expected audit output: verdict=edit; SSN rendered as [REDACTED:ssn]

curl -sS http://localhost:8080/v1/chat/completions -H 'Content-Type: application/json' -H 'X-ControlPlane-Use-Case: hr_copilot' -d "{\"model\":\"small\",\"messages\":[{\"role\":\"user\",\"content\":\"$PROMPT\"}]}"
# expected audit output: verdict=block; personal data withheld under hr_copilot policy

curl -sS http://localhost:8080/v1/chat/completions -H 'Content-Type: application/json' -H 'X-ControlPlane-Use-Case: finance_advisor' -d "{\"model\":\"small\",\"messages\":[{\"role\":\"user\",\"content\":\"$PROMPT\"}]}"
# expected audit output: verdict=escalate; request routed for additional verification
~~~

Same content. Three policies. Zero code difference.

<!-- SCREENSHOT: console verdict board -->
<!-- SCREENSHOT: chat page EDIT verdict -->

## Quick start

~~~sh
python -m venv .venv && .venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu && .venv/bin/pip install -e ".[dev,ml,dashboard]" && .venv/bin/python -m spacy download en_core_web_sm
cp .env.example .env && set -a; . ./.env; set +a          # add provider values; never commit them
.venv/bin/uvicorn --factory controlplane.gateway.app:create_live_app --port 8080
xdg-open http://localhost:8080/console                     # in another terminal
.venv/bin/python -m demo.run_script --replay               # in another terminal
~~~

The live factory requires a measured-class provider and its key. Replay remains the deterministic demo path.

Three details that cost people time. The CPU-only `torch` line comes first, or pip pulls a multi-gigabyte CUDA stack for budgets that are CPU budgets. Nothing in the repo loads `.env`, so the `set -a` line is not optional. And port 8000 is unavailable by construction: a local provider is configured there, so serving on it would make the gateway proxy to itself. Full environment notes are in [AGENTS.md §10](AGENTS.md).

## What it does

Every response crosses one gateway, and that gateway holds it long enough to judge it.

~~~mermaid
flowchart TB
  subgraph CLIENTS["CLIENT APPS — one policy profile each"]
    direction LR
    C1["support_bot"]
    C2["hr_copilot"]
    C3["finance_advisor"]
  end

  ING["<b>INGRESS</b><br/>resolve use case · bind policy_version<br/>unknown use case → 400 ERR-CFG-001"]
  PS[("<b>POLICY STORE</b><br/>policies/*.yaml<br/>versioned + schema-validated")]

  subgraph INLANE["INPUT LANE — pre-inference, before any upstream cost"]
    direction LR
    T1I["tier1_pii<br/>tier1_blocklist"]
    T2I["tier2_injection"]
    CST["cost_budget<br/>loop_guard"]
    RTR["router<br/>picks model tier"]
    T1I --> T2I --> CST --> RTR
  end

  DSP["<b>DISPATCHER</b><br/>streaming, or fully buffered when streaming:false"]
  UP["<b>Upstream LLM API</b><br/>small tier · frontier tier"]
  SB["<b>SENTENCE BUFFER</b><br/>accumulate tokens to a sentence boundary<br/>not token-level, not full-response"]

  subgraph OUTLANE["OUTPUT LANE — per buffered sentence"]
    direction LR
    T1O["tier1_pii<br/><i>responsibility</i>"]
    T2O["tier2_toxicity<br/><i>responsibility</i>"]
    PERF["rag_grounding<br/>numeric_claims<br/><i>performance</i>"]
  end

  ENR["<b>entity_enricher</b><br/>appends privacy.person to the same signal"]
  PE{{"<b>POLICY ENGINE</b><br/>converge all signals → most severe wins<br/>zero use-case conditionals"}}

  A1["<b>PASS</b>"]
  A2["<b>EDIT</b>"]
  A3["<b>BLOCK</b>"]
  A4["<b>ESCALATE</b>"]

  AUD[("<b>AUDIT LOG</b><br/>append-only · no raw PII")]
  RQ[("<b>REVIEW QUEUE</b><br/>+ human overrides")]
  DEEP["<b>DEEP AUDIT</b><br/>async, sampled, never awaited"]
  DASH["<b>CONSOLE</b>"]

  C1 --> ING
  C2 -->|"HTTPS · X-ControlPlane-Use-Case"| ING
  C3 --> ING
  PS -.->|"thresholds · action map · fail modes"| ING
  ING --> T1I
  RTR -->|"input verdict PASS"| DSP
  RTR -.->|"BLOCK / ESCALATE short-circuits here:<br/><b>zero upstream tokens, zero cost</b>"| PE
  DSP --> UP
  UP -->|"SSE tokens"| SB
  SB --> T1O
  SB --> T2O
  SB --> PERF
  T1O --> ENR
  T2O --> ENR
  PERF --> ENR
  ENR -->|"signals — multi-label, multi-plane"| PE
  PS -.->|"the policy for this use case"| PE
  PE --> A1
  PE --> A2
  PE --> A3
  PE --> A4
  A1 --> AUD
  A2 --> AUD
  A3 --> AUD
  A4 --> RQ
  A4 --> AUD
  AUD -.->|"sampled copy"| DEEP
  DEEP -.->|"enriches only — never alters<br/>a delivered verdict"| AUD
  AUD --> DASH
  RQ --> DASH

  classDef resp fill:#fff1f2,stroke:#be123c,color:#111827
  classDef perf fill:#eff6ff,stroke:#1d4ed8,color:#111827
  classDef cost fill:#fffbeb,stroke:#b45309,color:#111827
  classDef ctrl fill:#eef2ff,stroke:#4338ca,color:#111827
  classDef store fill:#f3f4f6,stroke:#4b5563,color:#111827
  classDef ext fill:#ffffff,stroke:#9ca3af,color:#374151
  classDef vpass fill:#ecfdf5,stroke:#047857,color:#111827
  classDef vedit fill:#fef3c7,stroke:#b45309,color:#111827
  classDef vblock fill:#fee2e2,stroke:#b91c1c,color:#111827
  classDef vesc fill:#ffedd5,stroke:#c2410c,color:#111827
  classDef deep fill:#f5f3ff,stroke:#6d28d9,color:#111827
  class T1I,T2I,T1O,T2O,ENR resp
  class PERF perf
  class CST,RTR,C1,C2,C3 cost
  class ING,DSP,SB ctrl
  class PE ctrl
  class PS,AUD,RQ store
  class UP,DASH ext
  class A1 vpass
  class A2 vedit
  class A3 vblock
  class A4 vesc
  class DEEP deep
~~~

| Verdict | Effect |
|---|---|
| Pass | Release unchanged content. |
| Edit | Transform eligible spans, then release and audit. |
| Block | Withhold content and return the configured fallback. |
| Escalate | Quarantine content and place it in the human-review queue. |

| Pipeline | Posture | Signature verdict |
|---|---|---|
| support_bot | Redact-first, streaming | EDIT |
| hr_copilot | Privacy-strict, streaming | BLOCK |
| finance_advisor | Regulated, buffered, fail-closed | ESCALATE |

Deep contracts and lifecycle detail: [architecture](docs/02-architecture.md), [policy and detection specification](docs/04-policy-and-detection-spec.md), and [API/data contracts](docs/05-api-and-data-contracts.md).

## Architecture

One FastAPI process, three planes of checks, one verdict per unit of text. The planes are **signal families, not separate services** — detectors emit independent signals and only the policy engine converges them.

| Plane | Fast path (sync, per sentence or request) | Slow path (async, sampled) |
|---|---|---|
| Performance | RAG grounding score, numeric-claim check | semantic-entropy clustering, drift statistics |
| Cost | budget gate, token estimate, router and cascade choice | cost-per-outcome aggregation, loop analytics |
| Responsibility | Tier-1 PII and blocklist, Tier-2 injection on input and toxicity on output | fairness spot checks, safety-taxonomy sampling |

### Interception granularity

Checks run on a **sentence buffer** — not token-by-token, and not on the finished response. Both alternatives are cheaper to build and both break something load-bearing: token-level checking cannot see a claim, and full-response checking cannot stop a flagged sentence that has already streamed. The guarantee is that for a flagged sentence, no part of it reaches the client.

~~~mermaid
sequenceDiagram
  autonumber
  participant CL as Client app
  participant IN as Ingress
  participant IL as Input lane
  participant UP as Upstream LLM
  participant SBUF as Sentence buffer
  participant PE as Policy engine
  participant AU as Audit + review

  CL->>IN: POST /v1/chat/completions<br/>X-ControlPlane-Use-Case
  IN->>IN: resolve use case, bind policy_version
  IN->>IL: input stage

  rect rgb(255, 251, 235)
    note over IL: input lane — before any upstream cost
    IL->>IL: tier1_pii, tier1_blocklist
    IL->>IL: tier2_injection
    IL->>IL: cost_budget, loop_guard
    IL->>PE: input-stage signals
    alt input verdict is BLOCK or ESCALATE
      PE-->>CL: short-circuit before dispatch<br/>zero upstream tokens, zero cost
      PE->>AU: audit record, stage_summary = input
    else input verdict PASS
      IL->>IL: router picks model tier (pre-dispatch)
    end
  end

  rect rgb(239, 246, 255)
    note over UP,PE: streaming path — support_bot, hr_copilot
    loop for each sentence
      UP-->>SBUF: tokens
      SBUF->>SBUF: accumulate to sentence boundary
      SBUF->>PE: fast detectors, then converge
      alt PASS or EDIT
        PE-->>CL: release the sentence, transformed if edited
      else BLOCK or ESCALATE
        PE-->>CL: terminate stream, send fallback or notice
        PE->>AU: quarantine and create a review item on escalate
      end
    end
  end

  rect rgb(243, 244, 246)
    note over UP,PE: non-streaming path — finance_advisor
    UP-->>SBUF: full response buffered
    SBUF->>PE: all checks, single verdict
    note over PE: nothing reaches the user before the verdict
    PE-->>CL: whole response, or fallback / notice
  end

  PE->>AU: finalize: verdict, signal ids, policy_version,<br/>latencies, model, cost
~~~

### Fast lane and deep lane

Expensive analysis is real oversight, but it cannot be on the hot path. The split is enforced rather than intended: nothing on the request lifecycle awaits the deep lane, and the deep lane may never alter a verdict already delivered. Its findings change the *next* request, through the feedback loop.

~~~mermaid
flowchart LR
  REQ(["Request"])
  subgraph FAST["FAST LANE — synchronous, inside the request lifecycle"]
    direction TB
    FD["detectors run per unit,<br/>each with a latency budget"]
    FV["policy engine verdict"]
    FD --> FV
  end
  DEL(["Response delivered"])
  QUEUE[["in-process queue<br/>sampled copy of request, response, signals<br/>10% · 5% · 25% per policy"]]
  subgraph SLOW["DEEP LANE — asynchronous, sampled, unbudgeted"]
    direction TB
    SE["semantic entropy<br/>seconds, not milliseconds"]
    SF["fairness spot checks"]
    SD["drift statistics"]
  end
  ENRICH[("enrich the audit record<br/>+ console panels")]
  FEED{{"feedback loop<br/>threshold and policy proposals"}}
  FORBID["<b>✗ FORBIDDEN</b><br/>no hot-path await on the deep lane;<br/>no post-hoc change to a delivered verdict"]

  REQ --> FD
  FV --> DEL
  FV -.->|"fire and forget<br/><b>never awaited</b>"| QUEUE
  QUEUE --> SE
  QUEUE --> SF
  QUEUE --> SD
  SE --> ENRICH
  SF --> ENRICH
  SD --> ENRICH
  ENRICH --> FEED
  FEED -.->|"next policy version"| REQ
  SLOW -.-x FORBID

  classDef fast fill:#eff6ff,stroke:#1d4ed8,color:#111827
  classDef slow fill:#f5f3ff,stroke:#6d28d9,color:#111827
  classDef gate fill:#f3f4f6,stroke:#4b5563,color:#111827
  classDef bad fill:#fee2e2,stroke:#b91c1c,color:#7f1d1d
  classDef term fill:#ecfdf5,stroke:#047857,color:#111827
  class FD,FV fast
  class SE,SF,SD,FEED slow
  class QUEUE,ENRICH gate
  class FORBID bad
  class REQ,DEL term
~~~

## The policy engine

One deterministic path from a set of signals to exactly one verdict, with no use-case conditionals anywhere in the code.

~~~mermaid
flowchart TB
  START(["All fast-path signals for one unit<br/>input stage, or one output sentence"])
  S1["<b>STEP 1 — map labels to actions</b><br/>specific &gt; wildcard &gt; default_action<br/>signal action = most severe across its labels"]
  KIND{"<b>STEP 2</b><br/>score_kind?"}
  BYPASS["<b>detection</b> kind — higher is worse<br/>tier1_*, tier2_*, numeric_claims, cost_*<br/><b>band logic never applies</b>"]
  BAND{"<b>confidence</b> kind — higher is better<br/>rag_grounding, fast_consistency<br/>compare score to thresholds"}
  B1["score ≥ tau_high<br/><b>drop signal</b>"]
  B2["tau_low ≤ score &lt; tau_high<br/><b>borderline band</b><br/>action from borderline_action"]
  B3["score &lt; tau_low<br/>use the mapped action"]
  S3{"<b>STEP 3</b> — most severe surviving action<br/>BLOCK &gt; ESCALATE &gt; EDIT &gt; PASS"}
  VPASS["<b>PASS</b>"]
  VEDIT["<b>EDIT</b>"]
  VBLOCK["<b>BLOCK</b>"]
  VESC["<b>ESCALATE</b>"]
  S4{"<b>STEP 4</b> — is the edit-mapped signal<br/>actually editable?<br/>has a span, or stage = output_sentence"}
  APPLY["apply transforms<br/><b>redact</b> at pii.* spans<br/><b>soften</b> a hallucination claim<br/>re-run tier1_pii as a guard"]
  PROMOTE["no editable extent<br/>promote to ESCALATE"]
  S5["<b>STEP 5 — stamp the audit record</b><br/>verdict, contributing signal ids, policy_version"]
  DONE(["Exactly one verdict,<br/>deterministic for identical inputs"])

  START --> S1 --> KIND
  KIND -->|"detection"| BYPASS
  KIND -->|"confidence"| BAND
  BAND --> B1
  BAND --> B2
  BAND --> B3
  BYPASS --> S3
  B1 -.->|"signal removed"| S3
  B2 --> S3
  B3 --> S3
  S3 -->|"none survived"| VPASS
  S3 --> VEDIT
  S3 --> VBLOCK
  S3 --> VESC
  VEDIT --> S4
  S4 -->|"yes"| APPLY
  S4 -->|"no"| PROMOTE
  PROMOTE --> VESC
  VPASS --> S5
  APPLY --> S5
  VBLOCK --> S5
  VESC --> S5
  S5 --> DONE

  classDef step fill:#eef2ff,stroke:#4338ca,color:#111827
  classDef det fill:#fffbeb,stroke:#b45309,color:#111827
  classDef conf fill:#eff6ff,stroke:#1d4ed8,color:#111827
  classDef vpass fill:#ecfdf5,stroke:#047857,color:#111827
  classDef vedit fill:#fef3c7,stroke:#b45309,color:#111827
  classDef vblock fill:#fee2e2,stroke:#b91c1c,color:#111827
  classDef vesc fill:#ffedd5,stroke:#c2410c,color:#111827
  classDef term fill:#f3f4f6,stroke:#4b5563,color:#111827
  class S1,S3,S4,S5,APPLY step
  class BYPASS det
  class BAND,B1,B2,B3,KIND conf
  class VPASS vpass
  class VEDIT vedit
  class VBLOCK vblock
  class VESC,PROMOTE vesc
  class START,DONE term
~~~

Two details in that flow are the ones reviewers ask about. **Score polarity is typed**, so a deterministic regex hit scoring 1.0 can never be silently dropped by a confidence threshold — band logic applies to confidence-kind signals only. And an **EDIT that has nothing to edit is promoted, never downgraded**: a span-less signal mapped to `edit` becomes `escalate` rather than passing through.

### Policy as configuration

Thresholds, the label-to-action map, failure posture, geography, and budgets all live in per-use-case YAML. This is the headline feature, so the constraint is strict: an `if use_case == ...` in Python would be a defect, not an implementation detail.

~~~yaml
# policies/support_bot.yaml — abridged
use_case: support_bot
policy_version: 3
geography: EU
risk_appetite: medium
streaming: true

thresholds:
  tau_low: 0.35
  tau_high: 0.70

budget:
  monthly_usd: 500
  per_request_max_tokens: 4000
  loop_max_requests_per_min: 20

actions:
  pii.*: edit                             # redact, then release
  pii.api_key: block                      # a typed credential is already compromised
  security.prompt_injection: block
  toxicity.high: block
  toxicity.moderate: pass
  hallucination.ungrounded_claim: edit    # soften
  cost.budget_exceeded: block
default_action: pass
borderline_action: edit                   # action inside [tau_low, tau_high)

fail_mode:
  tier1: fail_closed                      # never release unscanned personal data
  tier2: fail_open                        # availability over strictness
~~~

The three shipped policies differ only as data:

| | `support_bot` | `hr_copilot` | `finance_advisor` |
|---|---|---|---|
| `policy_version` | 3 | 1 | 4 |
| `streaming` | true | true | **false** — nothing precedes the verdict |
| `pii.*` | `edit` | `block` | `escalate` |
| `borderline_action` | `edit` | `pass` | `escalate` |
| `fail_mode.tier1` | fail_closed | fail_closed | fail_closed |
| `fail_mode.tier2` | fail_open | fail_open | **fail_closed** |
| Monthly budget | $500 | $800 | strict |

### The signature moment

One identical response, one identical signal set, one identical build — three verdicts.

~~~mermaid
flowchart TB
  FIX["<b>ONE IDENTICAL RESPONSE</b><br/>a low-confidence claim about a person,<br/>carrying one pii.email span"]
  SIG["<b>ONE MULTI-LABEL SIGNAL</b><br/>labels: hallucination.ungrounded_claim + privacy.person<br/>planes: performance + responsibility"]
  ENGINE{{"<b>THE SAME POLICY ENGINE</b><br/>same code, same build, same algorithm"}}

  subgraph P1["policies/support_bot.yaml"]
    direction TB
    M1["pii.* → <b>edit</b><br/>hallucination.ungrounded_claim → <b>edit</b><br/>privacy.person → pass"]
    V1["<b>EDIT</b><br/>softened claim + redacted detail"]
    M1 --> V1
  end
  subgraph P2["policies/hr_copilot.yaml"]
    direction TB
    M2["pii.* → <b>block</b><br/>hallucination.* → pass<br/>privacy.person → <b>block</b>"]
    V2["<b>BLOCK</b><br/>configured fallback message"]
    M2 --> V2
  end
  subgraph P3["policies/finance_advisor.yaml"]
    direction TB
    M3["pii.* → <b>escalate</b><br/>hallucination.* → <b>escalate</b><br/>privacy.person → <b>escalate</b>"]
    V3["<b>ESCALATE</b><br/>quarantined, review item created;<br/>non-streaming, so nothing reached the user"]
    M3 --> V3
  end

  AUD[("<b>THREE AUDIT RECORDS, SIDE BY SIDE</b><br/>same signals · three verdicts · three policy_version stamps")]
  NOTE["<i>Not one line of code differs between these pipelines.<br/>This is why it is a control plane, not a filter.</i>"]

  FIX --> SIG --> ENGINE
  ENGINE -->|"reads UC-1 policy"| M1
  ENGINE -->|"reads UC-2 policy"| M2
  ENGINE -->|"reads UC-3 policy"| M3
  V1 --> AUD
  V2 --> AUD
  V3 --> AUD
  AUD --- NOTE

  classDef fixture fill:#f3f4f6,stroke:#4b5563,color:#111827
  classDef signal fill:#fdf4ff,stroke:#a21caf,color:#111827
  classDef engine fill:#eef2ff,stroke:#4338ca,color:#111827
  classDef map fill:#ffffff,stroke:#9ca3af,color:#374151
  classDef vedit fill:#fef3c7,stroke:#b45309,color:#111827
  classDef vblock fill:#fee2e2,stroke:#b91c1c,color:#111827
  classDef vesc fill:#ffedd5,stroke:#c2410c,color:#111827
  classDef note fill:#ffffff,stroke:#ffffff,color:#4b5563
  class FIX fixture
  class SIG signal
  class ENGINE engine
  class M1,M2,M3 map
  class V1 vedit
  class V2 vblock
  class V3 vesc
  class AUD fixture
  class NOTE note
~~~

### Even the failures are policy

When a detector times out or crashes, what happens next is a per-use-case decision, not an engineering preference. The gateway synthesizes an operational failure record — never a content signal — and the policy's `fail_mode` for that detector class decides.

~~~mermaid
flowchart TB
  FAULT["<b>IDENTICAL INJECTED FAULT</b><br/>--inject-fault tier2<br/>tier2_toxicity raises DetectorTimeout"]
  SYN["<b>gateway records one failure event</b><br/>detector, error_class, fail_mode_applied<br/><i>an operational event, never a Signal</i>"]
  LOOKUP{"look up <b>fail_mode</b> for that<br/>detector class in <b>this</b> use case's policy"}

  subgraph UC1["support_bot — fail_mode.tier2: fail_open"]
    direction TB
    O1["log + metric<br/>cp_detector_failures_total"]
    O2["proceed without that detector's signals"]
    O3["<b>response PASSES</b><br/>failure recorded in the audit trail<br/><i>availability over strictness</i>"]
    O1 --> O2 --> O3
  end
  subgraph UC3["finance_advisor — fail_mode.tier2: fail_closed"]
    direction TB
    C1["synthesized failure maps to ESCALATE"]
    C2["<i>never a silent BLOCK —<br/>a human sees why</i>"]
    C3["<b>response QUARANTINED</b><br/>review item labelled detector_failure<br/><i>caution over availability</i>"]
    C1 --> C2 --> C3
  end

  NOTE["<i>Same fault, same code, same engine — different YAML line.<br/>Changing a fail_mode is a policy-version change.<br/>Changing the mechanism is a protocol deviation.</i>"]

  FAULT --> SYN --> LOOKUP
  LOOKUP -->|"policies/support_bot.yaml"| O1
  LOOKUP -->|"policies/finance_advisor.yaml"| C1
  O3 --- NOTE
  C3 --- NOTE

  classDef fault fill:#fee2e2,stroke:#b91c1c,color:#111827
  classDef syn fill:#f3f4f6,stroke:#4b5563,color:#111827
  classDef gate fill:#eef2ff,stroke:#4338ca,color:#111827
  classDef open fill:#ecfdf5,stroke:#047857,color:#111827
  classDef closed fill:#ffedd5,stroke:#c2410c,color:#111827
  classDef note fill:#ffffff,stroke:#ffffff,color:#4b5563
  class FAULT fault
  class SYN syn
  class LOOKUP gate
  class O1,O2,O3 open
  class C1,C2,C3 closed
  class NOTE note
~~~

Reproduce it with `.venv/bin/python -m eval.fault_injection`, which asserts the documented invariants and exits nonzero if any of them breaks.

## Detectors and signals

Detectors emit evidence. They never decide actions — that separation is what keeps policy in configuration.

| Detector | Stage | Plane | Emits |
|---|---|---|---|
| `tier1_pii` | input + output sentence | responsibility | `pii.*` — span-accurate, for redaction |
| `tier1_blocklist` | input + output sentence | responsibility | `security.blocklist` |
| `tier2_injection` | input | responsibility | `security.prompt_injection` — ONNX classifier, max over strided windows, full input coverage |
| `tier2_toxicity` | output sentence | responsibility | `toxicity.moderate` / `toxicity.high` |
| `rag_grounding` | output sentence | performance | `hallucination.ungrounded_claim` — only when the request carries context documents |
| `numeric_claims` | output sentence | performance | `hallucination.unsourced_numeric` — quantity-shaped numerals with no citation marker |
| `fast_consistency` | output full | performance | `hallucination.low_confidence` — **specified, not shipped (SL-6)** |
| `cost_budget` | input | cost | `cost.*` — ledger lookup plus a token estimate |
| `loop_guard` | input | cost | `cost.loop_detected` |
| `conv_tracker` | conversation | responsibility | `conversation.cumulative_risk` |
| `entity_enricher` | enrichment | responsibility | appends `privacy.person` to an existing signal |

Per-detector latency budgets are normative in [04 §2](docs/04-policy-and-detection-spec.md); measured P99s are in [Key results](#key-results) and [reports/latency_report.md](reports/latency_report.md). What each detector actually ran, and what was expected and did not run, is recorded per request — absence of coverage is a fact a reader can see rather than infer.

### Signals are multi-label

A single sentence can be a fabrication *and* a privacy exposure at once. The naive design emits two signals and correlates them later, which double-counts. Instead one signal carries labels from multiple planes, and enrichment appends to it rather than emitting alongside it.

~~~mermaid
flowchart TB
  TEXT["<b>one output sentence</b><br/><i>a fabricated detail about an identifiable person</i>"]
  D1["<b>rag_grounding</b><br/>score_kind: confidence"]
  D2["<b>numeric_claims</b><br/>score_kind: detection"]
  SIG1["<b>SIGNAL A</b><br/>labels: [hallucination.ungrounded_claim]<br/>planes: [performance]<br/>span + stage; evidence is category only,<br/>never the raw value"]
  SIG2["<b>SIGNAL B</b><br/>labels: [hallucination.unsourced_numeric]<br/>planes: [performance]"]
  ENR{{"<b>entity_enricher</b><br/>NER over the span and its sentence window<br/>PERSON found → append to the <b>same</b> signal"}}
  SIG1E["<b>SIGNAL A — enriched</b><br/>labels: [hallucination.ungrounded_claim, <b>privacy.person</b>]<br/>planes: [performance, <b>responsibility</b>]<br/><i>two planes, one signal</i>"]
  PE{{"<b>POLICY ENGINE</b><br/>the only component that decides"}}

  TEXT --> D1
  TEXT --> D2
  D1 --> SIG1
  D2 --> SIG2
  SIG1 -->|"span-bearing hallucination.*"| ENR
  ENR --> SIG1E
  SIG1E --> PE
  SIG2 --> PE

  classDef text fill:#f3f4f6,stroke:#4b5563,color:#111827
  classDef det fill:#eff6ff,stroke:#1d4ed8,color:#111827
  classDef sig fill:#ffffff,stroke:#9ca3af,color:#374151
  classDef enr fill:#fff1f2,stroke:#be123c,color:#111827
  classDef merged fill:#fdf4ff,stroke:#a21caf,color:#111827
  classDef engine fill:#eef2ff,stroke:#4338ca,color:#111827
  class TEXT text
  class D1,D2 det
  class SIG1,SIG2 sig
  class ENR enr
  class SIG1E merged
  class PE engine
~~~

## Interfaces

The integration surface is deliberately one line of client change: a `base_url` and a header.

| Surface | Purpose |
|---|---|
| `POST /v1/chat/completions` | OpenAI-compatible proxy. Header `X-ControlPlane-Use-Case` selects the policy; `X-ControlPlane-Conversation-Id` enables conversation tracking; body `controlplane.context` supplies source documents for grounding. |
| `GET /metrics` | Metrics snapshot the console and demo reveals read. |
| `GET /admin/review?status=pending` | The quarantine queue, with PII spans pre-redacted in the listing and each item labelled by escalation cause. |
| `POST /admin/review/{review_id}` | Human override — approve releases the stored response, reject confirms the catch. Both append to the audit lineage with a reviewer note. |
| `GET /admin/requests` · `GET /admin/requests/{request_id}` | Read-only forensic trace for one request. |
| `GET /admin/policies` · `POST /admin/policies/reload` | Active policy versions, and hot reload so behavior changes live. |
| `GET /console` | Same-origin console pages served by the gateway. |

Response shapes carry the verdict explicitly: an edited response is flagged in a header, a block returns HTTP 200 with the policy's fallback and `finish_reason: content_filter`, and an escalation returns HTTP 202 with a `review_id`. Errors never include prompt or response content. Full contracts, including the error codes referenced in the diagrams, are in [05](docs/05-api-and-data-contracts.md). **The admin API has no authentication in v1** — it is a localhost demo surface, and that is a stated limitation rather than an oversight.

## Audit and evidence

Oversight that cannot be inspected afterwards is not oversight. Every request writes one append-only record naming which signals drove the verdict, which policy version judged it, and what it cost.

~~~mermaid
erDiagram
  audit_records {
    TEXT request_id PK "one record per request, append-only"
    TEXT use_case "which pipeline"
    INTEGER policy_version "which YAML version judged it"
    TEXT verdict "pass | edit | block | escalate"
    TEXT signals_json "evidence fields only, NO raw PII"
    TEXT detector_failures_json "operational events, never Signals"
    TEXT contributing_signal_ids "which signals drove the verdict"
    TEXT failure_record_ids "which faults forced a floor"
    TEXT actions_json "transforms applied, spans, fallback used"
    TEXT tier_requested "small | frontier - the routing decision"
    TEXT model_used "concrete provider model id, never a tier name"
    TEXT upstream_class "dev | measured - provenance travels with the row"
    TEXT detectors_json "ran | not_run | unavailable per detector"
    TEXT latency_json "per-detector ms + the per-hold series"
    TEXT record_status "complete | partial - crash safety"
  }
  review_items {
    TEXT review_id PK
    TEXT request_id FK "lineage back to the audit record"
    TEXT quarantined_text "THE ONLY verbatim output column - PII masked at write time"
    TEXT status "pending | approved | rejected"
    TEXT reviewer_note "the override rationale"
  }
  deep_audit_results {
    TEXT request_id FK "enriches, never alters the verdict"
    TEXT method "semantic_entropy | fairness_spot"
    TEXT result_json "clusters, entropy value, or check outcome"
  }
  cost_ledger {
    TEXT use_case PK "composite key with month"
    TEXT month PK
    REAL spent_usd "read pre-dispatch by cost_budget"
  }
  audit_records ||--o| review_items : "ESCALATE creates one"
  audit_records ||--o{ deep_audit_results : "if sampled"
  audit_records }o--|| cost_ledger : "debits monthly spend"
~~~

Three invariants hold across that schema. **Exactly one column may hold verbatim model output**, and PII is masked before it is written. **A detector fault is never a content signal** — conflating the two would let an operational event look like a risk finding. And **the stamp of what drove a verdict is stored, not recomputed**, so an audit read cannot quietly disagree with the decision it describes. Abridged here; the full DDL is in [05 §3](docs/05-api-and-data-contracts.md).

### The loop closes

An escalation is not a dead end: a human decides, the decision is aggregated per label, and a threshold utility proposes a YAML diff. Nothing is ever auto-applied — a human applies the diff, `policy_version` bumps, and the diff itself is the audit trail.

## Key results

| Metric | Measured | Target | Reproduce with |
|---|---|---|---|
| Engine conformance | 840/840 decisions: 280 cases × 3 policies; perfect detection assumed | NFR-EVAL-002 ≥ 0.90 | .venv/bin/python -m eval.run_all |
| Tier-1 PII precision | 1.000 | Report honestly | .venv/bin/python -m eval.run_all |
| Tier-1 PII recall | 0.8852; 7/7 misses are the documented bare-7-digit exclusion | 0.95 — MISSED, target unmoved | .venv/bin/python -m eval.run_all |
| Injection detector | Precision 1.000 / recall 0.150; blind first contact | No numeric target | .venv/bin/python -m eval.run_all |
| End-to-end policy agreement | 0.851 / 0.851 / 0.825 over 194 of 280 cases; partial coverage and masked detector failures remain | ≥ 0.80 per pipeline — met | .venv/bin/python -m eval.run_all |
| Input-lane hold | P99 27.49 ms, n=200 | P99 < 50 ms — met | .venv/bin/python -m eval.bench_latency |
| Detector P99s | blocklist 0.020 ms; PII 0.133 ms; numeric 0.277 ms; toxicity 23.741 ms; injection 25.348 ms | Tier-1 < 1 ms; numeric < 5 ms; Tier-2 < 25 ms — injection MISSED | .venv/bin/python -m eval.bench_latency --check |
| Fault injection | In-process 5/5 runs at 39/39; separate processes 3/5 clean and two at 38/39 | All 39 invariants per run | .venv/bin/python -m eval.fault_injection --reps 5 |
| Cascade cost curve | +50% at f=0; +25% at f=0.25; break-even f=0.50; loss above it | No point target; f is NOT COMPUTED because the router does not ship | .venv/bin/python -m eval.cost_simulation |

Two of those rows are misses, and they are published as misses. That is the rule the numbers rest on: **first contact is blind, nothing is tuned toward a target, and a target is never moved to accommodate a result.** Measurement runs also require a quiet host — every harness stamps host load at start and end, and an artifact whose load stamp exceeds the documented threshold is not citable.

Full claims table, derivations, historical columns, and sources: [engineering notes](docs/09-engineering-notes.md). Generated evidence: [evaluation](reports/eval_report.md), [latency](reports/latency_report.md), [fault injection](reports/fault_injection_report.md), and [cost](reports/cost_report.md).

## Why this is different

- One policy engine converges performance, cost, and responsibility signals into one verdict.
- Uncertainty bands and detector-failure posture are both per-use-case policy, including fail-open and fail-closed behavior.
- Signals are multi-label, so overlapping risks remain independent until convergence.
- Interception is at the sentence boundary, so a flagged sentence is acted on before any part of it is released — and the input lane can refuse a request before it costs an upstream token.
- The OpenAI-compatible boundary is provider-neutral and supports cloud, local, and air-gapped deployment shapes; local fallback is verified only on the owner host.
- Claims are auditable: the corpus is frozen, first contact is blind, revisions retain v1 columns, and misses remain published.

## What doesn't ship

This register makes prototype limits reviewable rather than presenting them as completed capability.

| ID | Limitation | Status / plan |
|---|---|---|
| SL-1 | PII recall is 0.8852 against 0.95. | Open; target unmoved. Seven known bare-7-digit misses trade recall for precision 1.000. |
| SL-2 | Invalid NANP area codes can still fire under the v1-superset phone behavior. | Open; precision hardening requires a new freeze cycle. |
| SL-3 | Price provenance requires submission-time re-verification. | Downgraded for the two bound Groq IDs; retired-model comparisons remain barred. |
| SL-4 | A genuinely local fallback was previously absent. | Closed on the owner host with llama3.2:3b; no fallback latency/cost claim is made from the development host. |
| SL-5 | Tier-2 latency evidence is low-concurrency. | Open; the published one-thread column shows breaches, and a proper load test is out of scope. |
| SL-6 | fast_consistency is specified but not implemented. | Cut to roadmap; context-free performance checking is the missing case. |
| SL-7 | The grounding band cannot be calibrated: tau_low 0.8365 ≥ tau_high 0.7157. | Open; the 56/78 oracle ceiling points to a detector-model change, not target tuning. |
| SL-8 | Injection attributable P99 is 25.348 ms against 25 ms. | Open measured breach; target unmoved. ORT tuning or serving hardware is roadmap. |
| SL-9 | The OVLP two-plane demo cut works for only 2 of 3 policies. | Cut from the demo path after 10 repetitions; PII-001 remains the deterministic signature beat. |
| SL-10 | The two-tier cascade router is not built. | Budget gating ships, but f has no producer; cost saving remains a curve with break-even at f=0.50. |

Detailed rationale and the beat-by-beat cut record: [engineering notes](docs/09-engineering-notes.md). The authoritative register is [docs/08-open-questions.md](docs/08-open-questions.md).

## Project structure

~~~text
controlplane/  gateway, detector, policy, audit, cost, and telemetry code
policies/      three validated per-use-case YAML policies
eval/          frozen corpus, scoring, latency, fault, cost, and derivation harnesses
demo/          headless scripted demo and replay fixtures
dashboard/     same-origin console pages served by the gateway
reports/       committed, reproducible evidence; not build output
docs/          contracts, ADRs, ledgers, testing guide, and engineering notes
tests/         contract, regression, evaluation, and demo-path gates
~~~

## Development and testing

~~~sh
.venv/bin/python -m pytest -q
.venv/bin/python -m eval.run_all
.venv/bin/python -m eval.bench_latency --check
.venv/bin/python -m eval.fault_injection --reps 5
.venv/bin/python -m eval.validate_dataset --freeze
.venv/bin/python -m eval.check_derivations
~~~

Four verification tiers, in the order they catch things: unit and contract tests, the evaluation suite over the frozen corpus, the latency benchmark, and the live gateway. The reasoning behind each is in [docs/TESTING.md](docs/TESTING.md).

Two of those commands are unusual enough to explain. `validate_dataset --freeze` asserts the labeled corpus is byte-identical to its approved state — a frozen case is not editable as a fix, only through a new freeze cycle. And `check_derivations` re-derives every figure a document claims to have derived, reporting three outcomes rather than two: OK, MISMATCH, and **NO SOURCE** — a document claiming a figure its artifacts cannot produce. Such a figure gains a derivation or loses the claim.

Do not run measurement harnesses beside tests, builds, or another spike. Evidence is citable only from a quiet host with the recorded start/end load inside the documented threshold. The suite count deliberately lives in [.github/workflows/ci.yml](.github/workflows/ci.yml), not in this README, so it cannot go stale here.

## How it was built

The repository was built spec-first: contracts preceded code, AI agents worked under the binding [AGENTS.md](AGENTS.md), an independent AI review challenged each checkpoint, and humans adjudicated contract changes. The current ledger records **36** ADRs ruled, 32 deviations all filed and closed with none open, and ten registered SL IDs — SL-4 is closed, leaving nine active limitations. Every minor resolution is logged in the ledger too, so the open-deviation count stays honest rather than merely low.

- Requirements and schemas are the contract; code does not silently redefine them.
- AI implementation agents must stop or log conflicts under the deviation protocol.
- An independent reviewer produced adversarial findings before phase acceptance.
- Human rulings changed contracts through dated ADRs, never by weakening a failing test.

Zero open deviations is not a health score. It means nothing is *undecided* — what is missing is stated in the SL register above and in the ledger, and it is substantial.

Read the [ADR log](docs/03-decisions.md), [public ledger](docs/08-open-questions.md), and [detailed engineering notes](docs/09-engineering-notes.md): the ledger is public; every ruling is dated.

### Diagram sources

The diagrams above are README-scale simplifications. The authority is the mermaid source in [docs/diagrams/](docs/diagrams/), where each file names the doc sections it was derived from, so a diagram that drifts from the spec is auditable.

| # | Source | The one claim it makes |
|---|---|---|
| 01 | `01-system-overview` | One process, three planes of checks, converging on one verdict per unit. |
| 02 | `02-request-lifecycle` | A flagged sentence is acted on before any of it is released. |
| 03 | `03-policy-engine-algorithm` | One deterministic path from a set of signals to exactly one verdict. |
| 04 | `04-signature-three-verdicts` | ★ Identical signal, three verdicts. The only thing that differs is YAML. |
| 05 | `05-fast-slow-isolation` | The hot path never awaits the deep lane. |
| 06 | `06-fail-modes-compared` | One identical fault, two opposite outcomes — even failures are policy. |
| 07 | `07-cascade-mechanics` | The probe is fully buffered because mid-stream re-dispatch would break the no-recall rule. |
| 08 | `08-signal-model-multilabel` | Risk categories overlap, so one signal carries many labels. |
| 09 | `09-feedback-loop` | Escalations aren't a dead end: the system proposes, a human decides. |
| 10 | `10-audit-data-model` | Exactly one column may hold verbatim model output, and it is masked before write. |

Two sources have no tracked render on purpose — theirs named a since-retired schema column, and a picture showing a retired schema is worse than no picture. [`docs/diagrams/render.sh`](docs/diagrams/render.sh) reproduces them at any time.

## Team and submission

Team b24bb1029, Indian Institute of Technology Jodhpur.

| Member | Roll number | Branch |
|---|---|---|
| Priyanshu Pandey, lead | B24BB1029 | Bioengineering, third year |
| Harshit Saini | B24CS1031 | Computer Science, third year |
| Jayant Soni | B24CM1033 | Artificial Intelligence & Data Science, third year |

- [Business proposal PDF](b24bb1029_ControlPlane_Business_Proposal.pdf)
- [README PDF](b24bb1029_ControlPlane_README.pdf)
- Demo video: not present in the repository yet.
- License: not yet chosen; tracked in [docs/08-open-questions.md](docs/08-open-questions.md).
