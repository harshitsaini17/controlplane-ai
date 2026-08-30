"""ADR-035 — the `.[ml]` extra must be able to BUILD the tier-2 graph, not just serve it.

`[D2-tier2-served-graph-is-unbuildable-on-the-ml-extra]`: ADR-031 keeps no checked-in graph, so
a serving host exports and int8-quantizes at first use. That puts the build toolchain on the
serve path — but `onnx` sat in `dev`, so an `.[ml]` host passed ADR-033's `find_spec` probe and
then failed on **every request**: `finance_advisor` (`tier2: fail_closed`) blocked everything,
`support_bot` / `hr_copilot` (`fail_open`) silently scanned nothing. The boot refusal that exists
to stop a fail-closed promise being broken silently could not fire, because the missing name was
one nobody had declared.

This test is the guard that makes ADR-033's probe truthful **by construction**: it masks the
interpreter down to exactly `.[ml]`'s declared dependency closure and builds both checkpoints for
real. Move a build dependency out of `ml` and this fails here — before any `.[ml]` host boots into
the per-request-fault trap.

**The closure is derived from `pyproject.toml` at run time, never hand-maintained** (the ruling's
requirement, and the same reason `REQUIREMENTS` and `BUDGETS_MS` are transcribed once): a copied
list would drift silently, and a guard that tests a stale copy of the dependency set tests nothing.

## Two ways to fake absence WRONGLY, both found by getting this wrong first

1. **Raising from `find_spec`.** `transformers.utils.import_utils._is_package_available` *probes*
   for optional packages and expects `None` for absent. A finder that raises turns a graceful
   capability check into a hard failure — that reported `pytest` as a tier-2 build dependency,
   which it is not. Absence means: `find_spec` returns `None`, and `import` raises from the import
   machinery itself.
2. **Wrapping finders without delegating `find_distributions`.** That hook is how
   `importlib.metadata` enumerates installed distributions. Wrapping without it broke metadata
   lookup for *every* package and reported `tqdm` — installed and unmasked — as missing.

So a masked distribution must be invisible in **both** channels: no importable module and no
metadata. The subprocess asserts that inline (`tqdm` visible, a masked name hidden) before it
trusts its own result, because a masking harness that silently stops masking would make this test
pass for the wrong reason.

Run in a **subprocess**, not in-process: masking `pluggy` / `_pytest` inside the test runner would
break pytest's own lazy imports, and a fresh interpreter also guarantees nothing under test is
already in `sys.modules`.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: What ADR-031 serves. Both, because the ruling says both — the two checkpoints are different
#: architectures (BERT / DistilBERT) and a build path can plausibly work for one and not the other.
CHECKPOINTS = (
    "madhurjindal/Jailbreak-Detector",
    "martin-ha/toxic-comment-model",
)

#: Names whose absence makes this test meaningless rather than failing. The whole stack must be
#: present to simulate a *subset* of it — this is a composition test, not an availability test.
_NEEDED = ("torch", "transformers", "onnxruntime", "onnx")

_missing = [m for m in _NEEDED if importlib.util.find_spec(m) is None]

pytestmark = pytest.mark.skipif(
    bool(_missing),
    reason=(
        f"needs the full .[dev,ml] stack to simulate .[ml]; missing {_missing}. "
        "This guard only has teeth on a host with the model stack installed — see the "
        "CI job that installs .[dev,ml] for exactly this reason (ADR-035)."
    ),
)


# The subprocess body. Derives both dependency closures from pyproject, masks the difference,
# self-checks that masking is real, then builds each checkpoint and prints one JSON line.
_SCRIPT = textwrap.dedent(
    '''
    import importlib, importlib.metadata as md, json, re, shutil, sys, tempfile, tomllib
    from importlib.metadata import PackageNotFoundError, packages_distributions, requires
    from pathlib import Path

    ROOT = Path(sys.argv[1])
    CHECKPOINTS = sys.argv[2].split(",")
    NAME_RE = re.compile(r"^\\s*([A-Za-z0-9._-]+)")
    norm = lambda n: re.sub(r"[-_.]+", "-", n or "").lower()

    def req_names(dist):
        """Mandatory (non-extra-gated) requirements of an installed distribution."""
        try:
            rs = requires(dist) or []
        except PackageNotFoundError:
            return []
        out = []
        for r in rs:
            head = r
            if ";" in r:
                head, marker = r.split(";", 1)
                if "extra" in marker:      # extra-gated: not installed by default
                    continue
            m = NAME_RE.match(head)
            if m:
                out.append(norm(m.group(1)))
        return out

    def closure(seeds):
        seen, stack = set(), [norm(s) for s in seeds]
        while stack:
            d = stack.pop()
            if d in seen:
                continue
            seen.add(d)
            stack.extend(req_names(d))
        return seen

    pp = tomllib.loads((ROOT / "pyproject.toml").read_text())
    def declared(key):
        raw = (pp["project"]["dependencies"] if key == "base"
               else pp["project"]["optional-dependencies"][key])
        return [NAME_RE.match(r).group(1) for r in raw]

    # An `.[ml]` host has base + ml (and their transitive requirements) and nothing else.
    keep = closure(declared("base") + declared("ml"))
    mask_dists = closure(declared("dev")) - keep

    mod_of = {}
    for mod, dists in packages_distributions().items():
        for d in dists:
            mod_of.setdefault(norm(d), set()).add(mod)
    mask_mods = set()
    for d in mask_dists:
        mask_mods |= mod_of.get(d, {d.replace("-", "_")})
    mask_mods.discard("controlplane")

    class Mask:
        """Faithful absence: find_spec -> None, and metadata hidden. See the module docstring."""
        def __init__(self, inner, mods, dists):
            self._inner, self._mods, self._dists = inner, mods, dists
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split(".")[0] in self._mods:
                return None
            f = getattr(self._inner, "find_spec", None)
            return f(fullname, path, target) if f else None
        def find_distributions(self, context=None):
            fd = getattr(self._inner, "find_distributions", None)
            if fd is None:
                return ()
            return (d for d in fd(context)
                    if norm((d.metadata or {}).get("Name")) not in self._dists)
        def __getattr__(self, item):
            return getattr(self._inner, item)

    for m in list(sys.modules):
        if m.split(".")[0] in mask_mods:
            del sys.modules[m]
    sys.meta_path[:] = [Mask(f, mask_mods, mask_dists) for f in sys.meta_path]
    importlib.invalidate_caches()

    # Self-check: the harness must be masking something, and must not be masking everything.
    probe = sorted(mask_dists)[0] if mask_dists else None
    self_check = {"masked_dists": len(mask_dists), "probe": probe}
    try:
        md.version("tqdm"); self_check["unmasked_metadata_ok"] = True
    except Exception as e:
        self_check["unmasked_metadata_ok"] = False
        self_check["unmasked_error"] = type(e).__name__
    if probe:
        try:
            md.version(probe); self_check["probe_hidden"] = False
        except Exception:
            self_check["probe_hidden"] = True

    sys.path.insert(0, str(ROOT))
    result = {"self_check": self_check, "builds": {}}
    try:
        from eval.spike_tier2_models import build_onnx_session
        for ckpt in CHECKPOINTS:
            wd = Path(tempfile.mkdtemp(prefix="mlclosure_"))
            try:
                built = build_onnx_session(ckpt, 1, wd, quantized=True)
                result["builds"][ckpt] = {"ok": True, "graph_mb": built["graph_mb"]}
            except BaseException as e:
                result["builds"][ckpt] = {
                    "ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}",
                    "missing": getattr(e, "name", None),
                }
            finally:
                shutil.rmtree(wd, ignore_errors=True)
    except BaseException as e:
        result["import_error"] = f"{type(e).__name__}: {str(e)[:300]}"

    print("RESULT_JSON " + json.dumps(result))
    '''
)


@pytest.fixture(scope="module")
def masked_build() -> dict:
    """Build both checkpoints in an interpreter masked down to `.[ml]`. Slow (~20 s), so once."""
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT, str(ROOT), ",".join(CHECKPOINTS)],
        capture_output=True, text=True, timeout=900, cwd=str(ROOT),
    )
    line = next(
        (ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT_JSON ")), None
    )
    assert line, (
        "masking subprocess produced no result line — it died before reporting.\n"
        f"exit={proc.returncode}\nstdout tail:\n{proc.stdout[-2000:]}\n"
        f"stderr tail:\n{proc.stderr[-2000:]}"
    )
    return json.loads(line[len("RESULT_JSON "):])


def test_adr035_masking_harness_actually_masks(masked_build: dict) -> None:
    """The guard's own precondition, asserted rather than assumed.

    A harness that stopped masking would make every other test in this file pass for the wrong
    reason — it would be building on a full `.[dev,ml]` host and calling that an `.[ml]` result.
    Both channels are checked: an unmasked distribution stays visible, a masked one disappears.
    """
    sc = masked_build["self_check"]
    assert sc["masked_dists"] > 0, "nothing was masked: dev adds no dists beyond ml's closure?"
    assert sc["unmasked_metadata_ok"], (
        f"masking broke metadata for an UNMASKED package ({sc.get('unmasked_error')}) — "
        "the find_distributions delegation regressed (see docstring, mistake 2)"
    )
    assert sc.get("probe_hidden") is True, (
        f"masked distribution {sc.get('probe')!r} is still visible to importlib.metadata"
    )


@pytest.mark.parametrize("checkpoint", CHECKPOINTS)
def test_adr035_ml_extra_can_build_the_served_graph(masked_build: dict, checkpoint: str) -> None:
    """THE invariant: `.[ml]` alone must build the int8 graph it is expected to serve.

    If this fails with `missing: onnx`, a build dependency has been moved out of the `ml` extra
    and the D2 trap is back — an `.[ml]` host will boot clean and then fault on every request.
    Fix the extra, not this test (AGENTS.md §5.4).
    """
    assert "import_error" not in masked_build, masked_build.get("import_error")
    got = masked_build["builds"][checkpoint]
    assert got["ok"], (
        f"{checkpoint} does not build under `.[ml]` alone: {got.get('error')}. "
        f"Missing import: {got.get('missing')!r}. ADR-035 requires every name the build path "
        "imports to be declared in the `ml` extra AND in `REQUIREMENTS`."
    )
    assert got["graph_mb"] > 10, f"suspiciously small graph: {got['graph_mb']} MB"


def test_adr035_requirements_declares_what_the_build_needs() -> None:
    """`REQUIREMENTS` must name `onnx` for both tier-2 rows, and `ml` must declare it.

    Cheap and independent of the slow build: this is the transcription half of ADR-035, and it is
    what ADR-033's boot probe actually reads. The build test above proves the set is *sufficient*;
    this proves the declaration matches it.
    """
    import tomllib

    from controlplane.detectors.availability import REQUIREMENTS

    for row in ("tier2_injection", "tier2_toxicity"):
        assert "onnx" in REQUIREMENTS[row], (
            f"REQUIREMENTS[{row!r}] omits 'onnx' — ADR-033's probe would pass on a host that "
            "cannot build the graph, which is exactly D2"
        )

    ml = tomllib.loads((ROOT / "pyproject.toml").read_text())
    ml_names = {
        r.split("#")[0].strip().split("==")[0].strip().replace("-", "_").lower()
        for r in ml["project"]["optional-dependencies"]["ml"]
    }
    assert "onnx" in ml_names, "the `ml` extra no longer declares onnx (ADR-035 regression)"
