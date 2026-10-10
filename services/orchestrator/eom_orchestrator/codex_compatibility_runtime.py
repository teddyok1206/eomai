"""Protected executable identity for maintenance-only Codex compatibility evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eom_workflow.codex_compatibility import (
    CodexCompatibilityRuntime,
    compatibility_contract_sha256,
)

from eom_orchestrator.capability_observer import observe_codex_cli_surface
from eom_orchestrator.codex_cli_identity import (
    native_binary_path,
    protected_launcher_target,
)
from eom_orchestrator.codex_cli_identity import (
    protected_file_hash as _protected_hash,
)
from eom_orchestrator.codex_cli_identity import (
    protected_file_identity as _identity,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.worker_auth import CODEX_BINARY
from eom_orchestrator.worker_systemd import WORKER_EXECUTABLE, WORKER_EXECUTABLE_SHA256

_DISTRIBUTION_ROOT = Path("/usr/local/lib/node_modules/@openai/codex")


def _native_binary() -> Path:
    try:
        return native_binary_path(_DISTRIBUTION_ROOT)
    except ValueError as exc:
        raise ControlPlaneError(
            "CONTROL_COMPATIBILITY_RUNTIME_INVALID", "unsupported Codex installation layout"
        ) from exc


@dataclass(frozen=True, slots=True)
class CodexCompatibilityRuntimeGuard:
    """One hash pass per epoch; O(1) immutable file-identity checks before each launch."""

    runtime: CodexCompatibilityRuntime
    launcher: Path
    native_binary: Path
    identities: tuple[tuple[int, int, int, int, int, int], ...]

    def assert_current(self) -> None:
        try:
            if (
                protected_launcher_target(CODEX_BINARY) != self.launcher
                or tuple(
                    _identity(path)
                    for path in (self.launcher, self.native_binary, WORKER_EXECUTABLE)
                )
                != self.identities
            ):
                raise ValueError("Codex runtime changed")
        except (OSError, ValueError) as exc:
            raise ControlPlaneError(
                "CONTROL_COMPATIBILITY_RUNTIME_CHANGED", "Codex runtime changed during maintenance"
            ) from exc


def observe_compatibility_runtime_guard() -> CodexCompatibilityRuntimeGuard:
    try:
        launcher = protected_launcher_target(CODEX_BINARY)
        binary = _native_binary()
        paths = (launcher, binary, WORKER_EXECUTABLE)
        before = tuple(_identity(path) for path in paths)
        # Version/help observation belongs inside the same immutable file epoch as hashing.
        version, _flags = observe_codex_cli_surface()
        hashes = tuple(_protected_hash(path) for path in paths)
        after = tuple(_identity(path) for path in paths)
        if before != after or hashes[2] != "sha256:" + WORKER_EXECUTABLE_SHA256:
            raise ValueError("installed worker executable differs from released adapter")
        runtime = CodexCompatibilityRuntime(
            cli_version=version,
            cli_launcher_sha256=hashes[0],
            cli_binary_sha256=hashes[1],
            worker_exec_sha256=hashes[2],
            contract_sha256=compatibility_contract_sha256(),
        )
        guard = CodexCompatibilityRuntimeGuard(runtime, launcher, binary, after)
        guard.assert_current()
        return guard
    except (OSError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_COMPATIBILITY_RUNTIME_INVALID", "protected Codex runtime is unavailable"
        ) from exc


def observe_compatibility_runtime() -> CodexCompatibilityRuntime:
    """Public root-installer observation; never infer identity from a version string alone."""

    return observe_compatibility_runtime_guard().runtime
