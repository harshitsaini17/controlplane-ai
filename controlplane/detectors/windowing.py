"""Strided-window geometry for `tier2_injection` (ADR-032).

**Why this is production code and not part of the spike harness.** The geometry was first
written in `eval/spike_window_latency.py`, because measuring it came before implementing it.
Two consumers now need it — the detector (which slices the windows) and the runner (which
derives a liveness backstop from the policy's token bound, ADR-034 Part C) — so it has one home
and everything else imports it. Three reasons, in order of what they rest on:

1. **Dependency direction.** The harness exists to measure the implementation, so the
   implementation cannot depend on the harness. This reason holds whatever the import mechanics
   happen to be, which is why it is first.
2. **Importing the harness mutates `sys.path`** — measured, not assumed: `eval.spike_window_latency`
   and `eval.spike_tier2_models` each `sys.path.insert(0, REPO)` at module scope, so a gateway
   that imported either would silently prepend the source tree to the process's import path
   (twice), where it can shadow installed modules for every later import.
3. **One definition.** The alternative was writing `102 + (n-1) * 76` down twice, and two copies
   of a derivation agree only until one is corrected — the defect class this workstream is named
   for. `windows_for_tokens` has claimed this all along ("the harness and the detector agree by
   construction rather than by coincidence"); until now nothing made it true.

**What is deliberately NOT claimed here.** An earlier draft of this docstring said the harness
"imports the whole `ml` stack, so a gateway that reached for this arithmetic would fail to import
on an ml-less host". That is **false**, and it was checked only after being written: every `torch`
/ `onnx` / `onnxruntime` / `transformers` import in that chain is deferred inside a function, so
`import eval.spike_window_latency` succeeds with the entire `ml` stack masked. `eval` is also a
declared package in `pyproject.toml`, so "it would not be installed" fails as a fallback argument
too. The claim is removed rather than repaired because the reasons above do not need it — but
note that the harness's deferred-import structure is an unguarded implementation detail, not a
contract, so a future edit hoisting one of those imports to module scope would make the false
claim true without anything noticing. Recorded because writing down a plausible mechanism and
checking it afterwards is exactly the defect this repo keeps finding.

Deliberately dependency-free (`math` only). Anything here must be importable on a host with no
model stack, since the runner reads it on every request.

What stayed in the harness: `POLICY_BOUND_TOKENS`, `BOUND_WINDOWS` and `WINDOW_COUNTS`. Those
are *measurement* parameters — which bound we chose to publish a worst case for, and which rungs
we measured. In production the bound is per-use-case policy (`budget.per_request_max_tokens`:
4000 for `support_bot` and `finance_advisor`, 8000 for `hr_copilot`), so a module-level constant
would be a second source of truth for a value config already owns.
"""

from __future__ import annotations

import math

#: Window length in tokens, INCLUDING the tokenizer's two special tokens — this is the value
#: handed to `max_length`, so 104 here means 102 tokens of content. ADR-031 measured this length
#: at 14.27 / 22.80 ms, inside the 25 ms budget; 158 tokens breached at 33.57.
WINDOW_TOKENS = 104

#: Overlap in tokens (HF `stride`). 25% of the window per the ruling, making the step 76.
WINDOW_OVERLAP = 26

#: Content tokens per window — `WINDOW_TOKENS` less the tokenizer's two special tokens.
WINDOW_CONTENT_TOKENS = WINDOW_TOKENS - 2

#: Token step between consecutive window starts. Derived, never written down twice.
WINDOW_STEP = WINDOW_CONTENT_TOKENS - WINDOW_OVERLAP


def coverage_tokens(n_windows: int) -> int:
    """Content tokens spanned by `n_windows` strided windows. THE definition (ADR-032 §C1).

    `102 + (n-1) * 76`. Every published coverage label derives from here.

    ADR-032 **Correction 1** exists because the original table labelled its rungs from the
    *filler's* token count — the whole synthetic text — rather than from what the sliced
    windows actually span. The two coincide only while the filler is short. At the top rung
    they diverged: 4082 claimed against 3978 spanned, so the published bound case claimed a
    coverage it did not have, contradicting the ADR's own full-coverage guarantee. A label
    that is computed cannot drift from the geometry it describes; one that is observed can.
    """
    return 0 if n_windows < 1 else WINDOW_CONTENT_TOKENS + (n_windows - 1) * WINDOW_STEP


def windows_for_tokens(n_tokens: int) -> int:
    """Windows needed to cover `n_tokens` — the inverse of `coverage_tokens`.

    This is what ADR-034 Part C has the detector compute from its own single tokenization
    pass, so the harness and the detector agree by construction rather than by coincidence.
    Verified against the live tokenizer at 3978 / 4000 / 4080 tokens (52 / 53 / 54 windows,
    no unscanned tail in any case).
    """
    if n_tokens <= WINDOW_CONTENT_TOKENS:
        return 1
    return 1 + math.ceil((n_tokens - WINDOW_CONTENT_TOKENS) / WINDOW_STEP)
