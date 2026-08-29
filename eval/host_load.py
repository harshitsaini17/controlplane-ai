"""Provenance stamps for measurement artifacts (ADR-032 Correction 1 item 2).

Two kinds, both answering "is this artifact citable": **host load** (was the machine quiet) and
**code identity** (which tree produced it). They live together because they are read together —
AGENTS.md §7 requires a published number be reproducible by a script in this repo, and neither
stamp alone establishes that. The module keeps the `host_load` filename it was created with;
`git_stamp` joined it rather than starting a third one-function module, on the same
one-definition-two-harnesses reasoning below.

**Why this module exists.** A batch-curve phase of `eval/spike_window_latency.py` was once
poisoned by ~20 s of competing multi-core work — a concurrent ONNX export running in the same
session — and the contamination was detectable only by *inference* afterwards: a p50 that came
in 25% above its own cold sample, and a curve whose shape stopped being monotone. That argument
was reconstructable, but only by a reader who thought to look. Recording the load turns it into
a mechanical check: 06 §8 makes an artifact whose recorded load contradicts a quiet host
**not citable**, and a stamp is what lets that rule be applied rather than merely stated.

**One definition, two harnesses.** Both `spike_window_latency` and `bench_latency` stamp with
this, so the rule reads the same field name in either artifact and a test can assert both carry
it. Same reasoning as `controlplane/gateway/config.py`: three lines re-derived in five scripts
is how two of them drift (AGENTS.md §7).

**Only ONE stamp per artifact certifies it: `load_at_process_start`.** Taken before any measured
work, once per process. Every other stamp is a diagnostic, and conflating them is a live trap
this module was caught by: the spike harness stamps once per *thread setting*, and because load
averages decay over ~60 s, the second phase's "start" reads back the first phase's own load —
measured at 6.66 on a host that was quiet throughout, which would have condemned a clean
artifact. Hence `load_at_phase_start` (per phase, diagnostic) is a different key from
`load_at_process_start` (per artifact, the verdict), and `load_at_end` is high by construction
because the harness has been saturating cores for minutes by then.

**A stamp cannot certify a measurement, only a moment.** A 20 s transient inside a 3-minute phase
poisons two rungs and leaves both bracketing stamps clean — which is exactly what happened. Load
stamps are necessary and not sufficient; `spike_window_latency.contamination_signals` reads the
measurement itself and is what actually caught the discarded run.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

#: `load1` above this at run start means the host was not quiet when measurement began.
#:
#: Strict on purpose. One extra runnable task on a 12-CPU host does not sound like much, but the
#: contamination this exists to catch moved a 10-rep percentile by 25% — the samples that break
#: are the expensive ones, where a single transient covers a whole point. A generous threshold
#: would have admitted exactly the artifact that had to be discarded.
QUIET_LOAD1_MAX = 1.0


def load_stamp() -> dict[str, Any]:
    """Load averages plus CPU count, for embedding in an artifact at a phase boundary.

    The 1-minute average is the informative one: a transient long enough to ruin a low-rep
    measurement point shows up in `load1` and is smoothed away by `load15`.

    `os.getloadavg()` is Unix-only. Where it is absent the keys are present and `None` rather
    than missing, so a consumer distinguishes *"not measurable on this platform"* from *"this
    artifact predates the stamp"* — the second is the one that must not be citable.
    """
    try:
        la1, la5, la15 = os.getloadavg()
    except (AttributeError, OSError):        # non-Unix, or /proc unavailable
        return {"load1": None, "load5": None, "load15": None, "cpus": os.cpu_count()}
    return {
        "load1": round(la1, 2),
        "load5": round(la5, 2),
        "load15": round(la15, 2),
        "cpus": os.cpu_count(),
    }


def is_quiet(stamp: dict[str, Any] | None) -> bool | None:
    """Whether `stamp` shows a quiet host. `None` when the question cannot be answered.

    Three-valued deliberately, and the third value is the point. `False` is a finding — the load
    was measured and it was too high. `None` means the load is unknown (an older artifact, or a
    platform without load averages), which 06 §8 treats the same way for citation purposes but
    which must not be *reported* as a contaminated run. Collapsing the two would either excuse
    real contamination or invent it.
    """
    if not stamp or stamp.get("load1") is None:
        return None
    return bool(stamp["load1"] <= QUIET_LOAD1_MAX)


def quiet_verdict(stamp: dict[str, Any] | None) -> str:
    """One-line rendering of `is_quiet`, shared so both reports word it identically."""
    quiet = is_quiet(stamp)
    if quiet is None:
        return "load not recorded — NOT CITABLE (06 §8)"
    return "QUIET" if quiet else "NOT QUIET — NOT CITABLE (06 §8)"


def git_stamp() -> dict[str, Any]:
    """The commit an artifact was measured at, and whether the tree was dirty.

    AGENTS.md §7: a judge-facing number must be reproducible by a script in this repo. A commit
    hash is what makes that checkable rather than asserted — and `dirty` is the load-bearing
    half. An artifact measured with uncommitted changes is not reproducible from anything, and
    that was a live defect: the first publication run of the spike was measured from a working
    tree whose harness edits were never committed, so the artifact recorded numbers no committed
    code could produce.

    Returns `{"commit": None, "dirty": None}` when git is unavailable rather than the string
    "unavailable" a caller might print as if it were a hash — the three-valued convention
    `is_quiet` uses, for the same reason: absent is not the same as bad.
    """
    def run(*args: str) -> str | None:
        try:
            return subprocess.run(
                # `cwd` AND `timeout` because this replaced FOUR hand-rolled copies that had
                # already drifted apart: two carried `cwd`, one carried `timeout=5`, and the one
                # missing `cwd` read whichever directory the process happened to start in. The
                # union is kept rather than any single copy's behaviour — a consolidation that
                # silently drops a safety property another copy had is a regression wearing a
                # cleanup's clothes.
                ["git", *args], capture_output=True, text=True, check=True, timeout=5,
                cwd=Path(__file__).resolve().parents[1],
            ).stdout.strip()
        except Exception:  # noqa: BLE001 — absent git is a missing stamp, not an error
            return None

    commit = run("rev-parse", "HEAD")
    porcelain = run("status", "--porcelain")
    return {
        "commit": commit,
        "dirty": None if porcelain is None else bool(porcelain),
    }


def reproducibility_verdict(stamp: dict[str, Any] | None) -> str:
    """06 §8 / AGENTS.md §7's call on whether the measuring code can be recovered."""
    if not stamp or stamp.get("commit") is None:
        return "commit not recorded — NOT CITABLE (AGENTS.md §7)"
    if stamp.get("dirty"):
        return f"{stamp['commit'][:12]} + UNCOMMITTED CHANGES — NOT CITABLE (AGENTS.md §7)"
    return f"{stamp['commit'][:12]} clean"
