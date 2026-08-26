# Architecture diagrams

Mermaid sources (`*.mmd`) are the authority. `images/` is **generated output** — edit a
source and re-run the renderer; never hand-edit an SVG.

```bash
docs/diagrams/render.sh          # all 10 diagrams -> images/*.svg + images/*.png
```

**Two diagrams intentionally have no tracked render**: `07-cascade-mechanics` and
`10-audit-data-model`. Their sources were updated for the ADR-018 tier/model split and the
ADR-027 Amendment 1 columns, and the previous renders named the retired `model_requested`
column. A tracked render showing a retired schema is worse than no render — a reader trusts
the picture over the DDL — so the renders were deleted rather than regenerated. Regeneration
happens once, at submission packaging, if at all. Absence here is a decision, not an
oversight; `render.sh` reproduces them at any time.

Each source's header comment names the doc sections it was derived from, so a diagram
that drifts from the spec is auditable. If a doc changes, the diagram is stale — treat it
like code, not decoration.

## The ten diagrams

Each carries exactly one claim. Ordered for explaining the system cold.

| # | Diagram | The one claim it makes | Derived from |
|---|---|---|---|
| 01 | `01-system-overview` | One process, three planes of checks, converging on **one** verdict per unit. | 02 §1, §5 |
| 02 | `02-request-lifecycle` | A flagged sentence is acted on **before any of it is released**. | 02 §4, ADR-013, ADR-014 |
| 03 | `03-policy-engine-algorithm` | One deterministic path from a set of signals to exactly one verdict. | 04 §4.3, ADR-012, ADR-015 |
| 04 | `04-signature-three-verdicts` | ★ Identical signal, three verdicts. The only thing that differs is YAML. | 07 beat 4, `policies/*.yaml` |
| 05 | `05-fast-slow-isolation` | The hot path never awaits the deep lane; deep findings change the future, not this response. | 02 §3, ADR-004, NFR-P-003 |
| 06 | `06-fail-modes-compared` | One identical fault, two opposite outcomes — even failures are policy decisions. | 04 §5, SC-3, 07 beat 7 |
| 07 | `07-cascade-mechanics` | The probe is fully buffered **because** mid-stream re-dispatch would break the no-recall rule. | ADR-013, ADR-009, ADR-002 |
| 08 | `08-signal-model-multilabel` | Risk categories overlap, so ONE signal carries many labels. Detectors never decide actions. | 04 §1, §1.2, §2.2, FR-DET-005 |
| 09 | `09-feedback-loop` | Escalations aren't a dead end. The system proposes; a human decides; every version is audited. | 02 §6, 04 §7, ADR-010 |
| 10 | `10-audit-data-model` | Exactly one column may hold verbatim model output, and it is masked before write. | 05 §3, ADR-006, NFR-SEC-001 |

## Suggested walkthrough order

Explaining the architecture to someone cold — roughly 10 minutes:

1. **04** first. The signature moment sells the thesis fastest: same input, three verdicts, zero code difference. (07's video mapping opens on this beat for the same reason.)
2. **01** for the shape — where the checks live and how a request traverses them.
3. **02** for the interception guarantee, which is the whole premise.
4. **03** for how a verdict is actually computed.
5. **08** → **06** → **07** for the three mechanisms that get questioned most: multi-label overlap, fail modes, and cost/cascade.
6. **05** → **09** → **10** to close the governance loop: isolation, feedback, audit integrity.

For a **judge Q&A**, 06 and 07 are the two that answer "what happens when it breaks" and
"what does oversight cost" — worth having open.

## Formats

- **SVG** — vector, for slides and the README. Scales without artefacts.
- **PNG** — 2× scale, for the video, the PPTX template, and anywhere SVG is awkward.

## Rendering notes

- `mermaid-cli` 11.x bundles `puppeteer-core`, which does **not** auto-resolve a browser.
  `render.sh` defaults to `/usr/bin/chromium`; override with `CP_CHROME=/path/to/chrome`.
- Avoid numeric HTML entities (`&#10007;`) in labels — mermaid escapes the ampersand and
  renders them literally. Use the glyph (`✗`) or a named entity (`&mdash;`).
- Keep flowcharts strictly top-to-bottom with no back-edges into subgraph members;
  mixing subgraph-level edges with long-distance edges makes dagre scatter the members.
