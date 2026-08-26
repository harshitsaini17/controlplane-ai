"""Policy store: load, validate, version and hot-reload `policies/*.yaml`.

Implements 04 §3 loading against `policy.schema.Policy`, and serves 05 §2
`POST /admin/policies/reload` + `GET /admin/policies` (FR-CFG-001, FR-CFG-002).

Three properties this module exists to guarantee:

**Loading is all-or-nothing.** A reload validates every file and only then swaps the
active set. A half-applied reload — two use cases on the new policy, one on the old —
would make the audit trail unreadable, because `policy_version` would no longer
identify what judged a request. On failure the previous set stays active and the error
is returned to the caller (FR-CFG-001: "invalid policy refuses to load with a precise
error"; the demo's live policy edit in 07 depends on a failed edit being *inert*).

**Wildcards expand at load, not at first use.** 04 §3 says expansion happens at load,
and `Policy.resolved_actions` is a lazy property, so the store touches it once per
policy while loading. A malformed action map therefore fails the load rather than the
first request that happens to hit the bad label.

**The filename and the `use_case` field must agree.** Ingress resolves a use case by
name (05 §1.1) but the engine stamps `policy.use_case` into the audit record, so a
disagreement would silently attribute one pipeline's decisions to another.

Not here on purpose: HTTP concerns. The store raises `UnknownUseCase`; mapping that to
ERR-CFG-001/400 belongs to the gateway (05 §1.2).
"""

from __future__ import annotations

import hashlib
import threading
import warnings
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from controlplane.policy.schema import Policy

#: Repo-root `policies/`. Overridable per instance for tests and fixtures.
POLICY_DIR = Path(__file__).resolve().parents[2] / "policies"

#: Only `.yaml`; a stray `.yml` or `.yaml.bak` is not silently picked up, because
#: "which files are policies" must be answerable by looking at the directory.
POLICY_GLOB = "*.yaml"


class PolicyLoadError(ValueError):
    """A policy file is missing, malformed, or fails schema validation (FR-CFG-001)."""


class UnknownUseCase(KeyError):
    """No loaded policy for the requested use case → gateway maps to ERR-CFG-001."""

    def __init__(self, use_case: str, known: tuple[str, ...]) -> None:
        self.use_case = use_case
        self.known = known
        super().__init__(
            f"unknown use case {use_case!r}; loaded: {', '.join(known) or '(none)'}"
        )


class PolicyVersionWarning(UserWarning):
    """Policy content changed but `policy_version` did not (04 §3 says bump on change)."""


@dataclass(frozen=True)
class LoadedPolicy:
    """One validated policy plus the provenance needed to audit and reload it."""

    policy: Policy
    path: Path
    #: SHA-256 of the file's bytes — how "changed without a version bump" is detected.
    digest: str

    @property
    def use_case(self) -> str:
        return self.policy.use_case

    @property
    def version(self) -> int:
        return self.policy.policy_version


def _load_one(path: Path) -> LoadedPolicy:
    """Read, parse and validate one policy file, or raise `PolicyLoadError`.

    Every failure mode names the file, because the operator reading this error is
    looking at a directory of near-identical YAML.
    """
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise PolicyLoadError(f"{path.name}: cannot read ({exc})") from exc

    try:
        data = yaml.safe_load(raw_bytes.decode())
    except yaml.YAMLError as exc:
        raise PolicyLoadError(f"{path.name}: invalid YAML ({exc})") from exc

    if not isinstance(data, dict):
        raise PolicyLoadError(
            f"{path.name}: top level must be a mapping, got "
            f"{type(data).__name__ if data is not None else 'empty file'}"
        )

    try:
        policy = Policy(**data)
    except ValidationError as exc:
        # pydantic's rendering already names the field and the rule; prefixing the
        # filename is what makes it actionable across three similar files.
        raise PolicyLoadError(f"{path.name}: {exc}") from exc

    if policy.use_case != path.stem:
        raise PolicyLoadError(
            f"{path.name}: use_case is {policy.use_case!r} but the filename says "
            f"{path.stem!r}. Ingress resolves by name (05 §1.1) while the engine stamps "
            "use_case into the audit record, so a mismatch misattributes decisions"
        )

    # 04 §3: wildcards expand at load. `resolved_actions` is lazy, so touch it here
    # to surface an expansion failure now rather than on the request that trips it.
    try:
        policy.resolved_actions
    except Exception as exc:  # noqa: BLE001 - re-raised as a load error with the file named
        raise PolicyLoadError(f"{path.name}: action map cannot expand ({exc})") from exc

    return LoadedPolicy(
        policy=policy,
        path=path,
        digest=hashlib.sha256(raw_bytes).hexdigest(),
    )


class PolicyStore:
    """The active set of policies, swapped atomically on reload.

    Thread-safe: uvicorn may serve requests while an admin reload runs. Readers take
    the lock only to copy one dict reference, so serving is never blocked behind a
    file read — `_load_all` does its I/O and validation *outside* the lock and the
    lock covers just the swap.
    """

    def __init__(self, policy_dir: Path | str | None = None) -> None:
        self._dir = Path(policy_dir) if policy_dir is not None else POLICY_DIR
        self._loaded: dict[str, LoadedPolicy] = {}
        self._lock = threading.Lock()

    # -- loading -----------------------------------------------------------

    def _load_all(self) -> dict[str, LoadedPolicy]:
        """Validate every policy file. Raises on the first failure; mutates nothing."""
        if not self._dir.is_dir():
            raise PolicyLoadError(f"policy directory not found: {self._dir}")

        paths = sorted(self._dir.glob(POLICY_GLOB))
        if not paths:
            raise PolicyLoadError(
                f"no {POLICY_GLOB} files in {self._dir}; the gateway cannot serve any "
                "use case without at least one policy (FR-GW-003)"
            )

        loaded: dict[str, LoadedPolicy] = {}
        for path in paths:
            entry = _load_one(path)
            if entry.use_case in loaded:
                raise PolicyLoadError(
                    f"{path.name}: duplicate use_case {entry.use_case!r} (also in "
                    f"{loaded[entry.use_case].path.name})"
                )
            loaded[entry.use_case] = entry
        return loaded

    def load(self) -> dict[str, int]:
        """Initial load. Returns `{use_case: policy_version}`; raises `PolicyLoadError`."""
        fresh = self._load_all()
        with self._lock:
            self._loaded = fresh
        return {uc: entry.version for uc, entry in sorted(fresh.items())}

    def reload(self) -> dict[str, int]:
        """Hot-reload (FR-CFG-002). Atomic: on failure the active set is untouched.

        Warns when a file's bytes changed while `policy_version` did not. 04 §3 says
        "bump on every change" precisely because the version is what the audit record
        stamps: same version + different behaviour makes two records claim to have been
        judged by the same policy when they were not. A warning rather than an error —
        refusing the reload would block the operator from fixing anything, and the
        demo edits policies live (07).
        """
        fresh = self._load_all()          # outside the lock; raises before any swap
        with self._lock:
            previous = self._loaded
            self._loaded = fresh
        for use_case, entry in sorted(fresh.items()):
            old = previous.get(use_case)
            if old is not None and old.digest != entry.digest and old.version == entry.version:
                warnings.warn(
                    f"{entry.path.name}: content changed but policy_version is still "
                    f"{entry.version}; audit records cannot distinguish the two "
                    "(04 §3 requires a bump on every change)",
                    PolicyVersionWarning,
                    stacklevel=2,
                )
        return {uc: entry.version for uc, entry in sorted(fresh.items())}

    # -- reading -----------------------------------------------------------

    def get(self, use_case: str) -> Policy:
        """The active policy for `use_case`, or raise `UnknownUseCase` (→ ERR-CFG-001)."""
        with self._lock:
            loaded = self._loaded
        entry = loaded.get(use_case)
        if entry is None:
            raise UnknownUseCase(use_case, tuple(sorted(loaded)))
        return entry.policy

    def has(self, use_case: str) -> bool:
        with self._lock:
            return use_case in self._loaded

    @property
    def use_cases(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._loaded))

    def versions(self) -> dict[str, int]:
        """`{use_case: policy_version}` — the `POST /admin/policies/reload` payload."""
        with self._lock:
            return {uc: e.version for uc, e in sorted(self._loaded.items())}

    def describe(self) -> list[dict[str, object]]:
        """The 05 §2 `GET /admin/policies` payload: active policies + versions.

        Includes the file digest so an operator can tell two same-version loads apart,
        and the delivery mode because 07's beats turn on UC-3 being non-streaming
        (ADR-014). Never includes the policy body: fallback texts and thresholds are
        config, but this endpoint is an inventory, not a config dump.
        """
        with self._lock:
            entries = sorted(self._loaded.items())
        return [
            {
                "use_case": uc,
                "policy_version": e.version,
                "file": e.path.name,
                "digest": e.digest[:16],
                "streaming": e.policy.streaming,
                "risk_appetite": e.policy.risk_appetite.value,
                "geography": e.policy.geography,
            }
            for uc, e in entries
        ]
