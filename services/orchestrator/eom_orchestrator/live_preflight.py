"""Non-usage-consuming readiness checks for the dedicated live worker boundary."""

from __future__ import annotations

import os
import site
import stat
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from eom_protocol.validation import load_schema

from eom_orchestrator.protocol import SCHEMA_NAMES
from eom_orchestrator.runtime_configuration import resolve_worker_configuration
from eom_orchestrator.settings import Settings
from eom_orchestrator.worker_registry import WorkerSlot
from eom_orchestrator.worker_systemd import (
    WorkerSystemdReadiness,
    inspect_worker_systemd_contract,
    probe_worker_systemd_authorization,
)


@dataclass(frozen=True)
class LiveWorkerPreflightCheck:
    name: str
    passed: bool
    code: str
    detail: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LiveWorkerPreflightReport:
    checks: tuple[LiveWorkerPreflightCheck, ...]

    @property
    def ready(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failed_codes(self) -> tuple[str, ...]:
        return tuple(check.code for check in self.checks if not check.passed)


SystemdCheck = Callable[[WorkerSlot], WorkerSystemdReadiness]


def _check(name: str, passed: bool, code: str, detail: str) -> LiveWorkerPreflightCheck:
    return LiveWorkerPreflightCheck(name, passed, "READY" if passed else code, detail)


def _installed_origin(*, package_roots: Sequence[Path] | None) -> LiveWorkerPreflightCheck:
    origin = Path(__file__).resolve()
    candidates = (
        package_roots
        if package_roots is not None
        else tuple(Path(value) for value in site.getsitepackages())
    )
    roots = tuple(root.resolve() for root in candidates)
    installed = any(origin.is_relative_to(root) for root in roots)
    return _check(
        "orchestrator_installed_package",
        installed,
        "ORCHESTRATOR_SOURCE_IMPORT_DETECTED",
        "site-packages" if installed else "outside installed package roots",
    )


def _runtime_directory(path: Path, *, writable: bool) -> bool:
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError:
        return False
    access = os.X_OK | (os.W_OK if writable else 0)
    return (
        path.is_absolute()
        and not path.is_symlink()
        and stat.S_ISDIR(metadata.st_mode)
        and resolved == path.absolute()
        and os.access(path, access)
    )


def _probe_staging(path: Path) -> bool:
    if not _runtime_directory(path, writable=True):
        return False
    probe = path / f".eom-live-preflight-{uuid4().hex}"
    try:
        probe.mkdir(mode=0o700, parents=False, exist_ok=False)
        return probe.is_dir() and not probe.is_symlink()
    except OSError:
        return False
    finally:
        with suppress(OSError):
            probe.rmdir()


def run_live_worker_preflight(
    settings: Settings,
    *,
    package_roots: Sequence[Path] | None = None,
    systemd_contract: SystemdCheck = inspect_worker_systemd_contract,
    authorization_probe: SystemdCheck = probe_worker_systemd_authorization,
) -> LiveWorkerPreflightReport:
    """Verify the installed worker boundary without submitting a job or invoking Codex."""
    checks: list[LiveWorkerPreflightCheck] = []
    checks.append(_installed_origin(package_roots=package_roots))
    try:
        resolved = resolve_worker_configuration(settings)
    except Exception as exc:
        checks.append(
            _check(
                "orchestrator_runtime_configuration",
                False,
                "WORKER_CONFIGURATION_INVALID",
                type(exc).__name__,
            )
        )
        return LiveWorkerPreflightReport(tuple(checks))

    checks.append(
        _check(
            "orchestrator_runtime_configuration",
            True,
            "WORKER_CONFIGURATION_INVALID",
            f"source={resolved.source.value}; version={resolved.registry.config.version}",
        )
    )
    slot = resolved.live_worker
    checks.append(
        _check(
            "live_worker_target",
            slot.enabled and slot.role == "authoring",
            "LIVE_WORKER_UNAVAILABLE",
            f"slot {slot.slot_id}",
        )
    )
    checks.append(
        _check(
            "orchestrator_staging",
            _probe_staging(settings.staging_root),
            "ORCHESTRATOR_STAGING_INVALID",
            "writable probe passed",
        )
    )
    workspace = settings.workspace_root / slot.linux_user
    checks.append(
        _check(
            "live_worker_workspace",
            _runtime_directory(workspace, writable=True),
            "LIVE_WORKER_WORKSPACE_INVALID",
            f"slot {slot.slot_id}",
        )
    )
    checks.append(
        _check(
            "codex_binary",
            settings.codex_binary.is_file() and os.access(settings.codex_binary, os.X_OK),
            "CODEX_BINARY_UNAVAILABLE",
            "configured executable",
        )
    )
    try:
        for schema_name in SCHEMA_NAMES:
            load_schema(schema_name)
        schemas_ready = True
        schema_detail = f"{len(SCHEMA_NAMES)} loaded"
    except Exception as exc:
        schemas_ready = False
        schema_detail = type(exc).__name__
    checks.append(
        _check(
            "result_protocol_schemas",
            schemas_ready,
            "RESULT_PROTOCOL_SCHEMAS_INVALID",
            schema_detail,
        )
    )
    contract = systemd_contract(slot)
    checks.append(
        _check("live_worker_systemd_template", contract.ready, contract.code, contract.detail)
    )
    authorization = authorization_probe(slot) if contract.ready else contract
    checks.append(
        _check(
            "live_worker_systemd_authorization",
            authorization.ready,
            authorization.code,
            authorization.detail,
        )
    )
    return LiveWorkerPreflightReport(tuple(checks))
