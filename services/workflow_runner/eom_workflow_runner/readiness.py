"""Read-only execution readiness checks for the production workflow runtime."""

from __future__ import annotations

import grp
import os
import pwd
import shutil
import stat
import sys
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from eom_catalog_service.settings import CatalogSettings
from eom_orchestrator.settings import Settings
from eom_orchestrator.worker_registry import WorkerRegistry, WorkerSlot
from eom_workflow import compile_definition
from eom_workflow.schemas import (
    RESULT_SCHEMA_FILES,
    load_definition_schema,
    load_role_input_schema,
    load_role_result_schema,
)

from eom_workflow_runner.settings import WorkflowSettings


class ReadinessStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class RuntimeReadinessCheck:
    name: str
    status: ReadinessStatus
    code: str
    detail: str

    @property
    def passed(self) -> bool:
        return self.status != ReadinessStatus.FAIL


@dataclass(frozen=True)
class RuntimeReadinessReport:
    checks: tuple[RuntimeReadinessCheck, ...]

    @property
    def ready(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failed_codes(self) -> tuple[str, ...]:
        return tuple(check.code for check in self.checks if not check.passed)


class WorkflowExecutionReadiness(Protocol):
    def evaluate(self) -> RuntimeReadinessReport: ...


class WorkflowRuntimeNotReady(RuntimeError):
    def __init__(self, report: RuntimeReadinessReport) -> None:
        self.report = report
        codes = ",".join(report.failed_codes) or "WORKFLOW_RUNTIME_NOT_READY"
        super().__init__(f"workflow runtime is not ready: {codes}")


class WorkflowRuntimeReadiness:
    """Evaluate prerequisites without claiming work or invoking a worker."""

    def __init__(
        self,
        *,
        workflow_settings: WorkflowSettings,
        platform_settings: Settings,
        catalog_settings: CatalogSettings,
        catalog_configured: bool,
        runner_user: str = "eom",
    ) -> None:
        self.workflow_settings = workflow_settings
        self.platform_settings = platform_settings
        self.catalog_settings = catalog_settings
        self.catalog_configured = catalog_configured
        self.runner_user = runner_user

    def evaluate(self) -> RuntimeReadinessReport:
        checks: list[RuntimeReadinessCheck] = []
        checks.append(
            _check(
                "catalog_adapter",
                self.catalog_configured,
                "CATALOG_ADAPTER_MISSING",
                "configured" if self.catalog_configured else "mandatory adapter unavailable",
            )
        )
        checks.append(self._catalog_staging())

        registry: WorkerRegistry | None = None
        try:
            registry = WorkerRegistry.load(self.platform_settings.worker_config)
            enabled = tuple(slot for slot in registry.config.slots if slot.enabled)
            checks.append(
                _check(
                    "worker_registry",
                    bool(enabled),
                    "WORKER_REGISTRY_INVALID",
                    f"{len(enabled)} enabled slots",
                )
            )
        except Exception as exc:
            checks.append(
                _failure("worker_registry", "WORKER_REGISTRY_INVALID", type(exc).__name__)
            )

        if registry is not None:
            checks.append(self._worker_role_mapping(registry))
            checks.append(self._worker_group_isolation(registry))
            for slot in sorted(
                (slot for slot in registry.config.slots if slot.enabled),
                key=lambda candidate: candidate.slot_id,
            ):
                checks.extend(self._worker(slot))

        checks.extend(self._runtime_packages(registry))
        return RuntimeReadinessReport(tuple(checks))

    def _worker_role_mapping(self, registry: WorkerRegistry) -> RuntimeReadinessCheck:
        required_roles = ("authoring", "review", "image", "item_management")
        try:
            selected = tuple(registry.select(role).linux_user for role in required_roles)
        except Exception as exc:
            return _failure(
                "worker_role_mapping", "WORKER_ROLE_MAPPING_INVALID", type(exc).__name__
            )
        return _success("worker_role_mapping", f"{len(selected)} required roles")

    def _worker_group_isolation(self, registry: WorkerRegistry) -> RuntimeReadinessCheck:
        enabled = tuple(slot for slot in registry.config.slots if slot.enabled)
        try:
            private_gids = {
                slot.linux_user: grp.getgrnam(slot.linux_user).gr_gid for slot in enabled
            }
            all_private_gids = set(private_gids.values())
            isolated = all(
                set(
                    os.getgrouplist(
                        slot.linux_user,
                        pwd.getpwnam(slot.linux_user).pw_gid,
                    )
                )
                & all_private_gids
                == {private_gids[slot.linux_user]}
                for slot in enabled
            )
        except (KeyError, OSError):
            isolated = False
        return _check(
            "worker_group_isolation",
            isolated,
            "WORKER_GROUP_ISOLATION_INVALID",
            "one private group per worker" if isolated else "cross-worker membership detected",
        )

    def _catalog_staging(self) -> RuntimeReadinessCheck:
        path = self.catalog_settings.staging_root
        try:
            metadata = path.lstat()
            runner = pwd.getpwnam(self.runner_user)
            mode = stat.S_IMODE(metadata.st_mode)
            valid = (
                not path.is_symlink()
                and stat.S_ISDIR(metadata.st_mode)
                and metadata.st_uid == runner.pw_uid
                and metadata.st_gid == runner.pw_gid
                and mode == 0o750
                and os.access(path, os.W_OK | os.X_OK)
            )
            if not valid:
                return _failure(
                    "catalog_staging",
                    "CATALOG_STAGING_INVALID",
                    "ownership, mode, or access does not match eom:0750",
                )
            _probe_directory(path, group_id=None, file_mode=0o600)
            return _success("catalog_staging", "writable probe passed")
        except (KeyError, OSError) as exc:
            return _failure("catalog_staging", "CATALOG_STAGING_UNWRITABLE", type(exc).__name__)

    def _worker(self, slot: WorkerSlot) -> list[RuntimeReadinessCheck]:
        prefix = f"worker_{slot.slot_id}"
        checks: list[RuntimeReadinessCheck] = []
        try:
            account = pwd.getpwnam(slot.linux_user)
            private_group = grp.getgrnam(slot.linux_user)
        except KeyError:
            return [_failure(prefix + "_identity", "WORKER_ACCOUNT_UNAVAILABLE", slot.linux_user)]

        identity_valid = account.pw_gid == private_group.gr_gid
        checks.append(
            _check(
                prefix + "_identity",
                identity_valid,
                "WORKER_PRIVATE_GROUP_INVALID",
                slot.linux_user,
            )
        )

        try:
            worker_groups = set(os.getgrouplist(slot.linux_user, account.pw_gid))
            launch_access = _identity_can_execute(
                self.platform_settings.codex_binary,
                user_id=account.pw_uid,
                group_ids=worker_groups,
            ) and _identity_can_execute(
                Path(sys.executable),
                user_id=account.pw_uid,
                group_ids=worker_groups,
            )
        except OSError:
            launch_access = False
        checks.append(
            _check(
                prefix + "_launch_access",
                launch_access,
                "WORKER_LAUNCH_ACCESS_INVALID",
                "runtime executables accessible" if launch_access else slot.linux_user,
            )
        )
        if not identity_valid:
            return checks

        try:
            runner = pwd.getpwnam(self.runner_user)
            configured_groups = set(os.getgrouplist(self.runner_user, runner.pw_gid))
        except (KeyError, OSError):
            configured_groups = set()
        process_groups = {*os.getgroups(), os.getgid()}
        configured = private_group.gr_gid in configured_groups
        current = private_group.gr_gid in process_groups
        membership_code = (
            "WORKER_GROUP_MEMBERSHIP_STALE"
            if configured and not current
            else "WORKER_GROUP_MEMBERSHIP_MISSING"
        )
        checks.append(
            _check(
                prefix + "_group_membership",
                configured and current,
                membership_code,
                "configured and active" if configured and current else slot.linux_user,
            )
        )

        workspace = self.platform_settings.workspace_root / slot.linux_user
        workspace_valid = _directory_matches(
            workspace,
            owner_id=account.pw_uid,
            group_id=private_group.gr_gid,
            mode=0o2770,
        )
        checks.append(
            _check(
                prefix + "_workspace",
                workspace_valid,
                "WORKER_WORKSPACE_INVALID",
                "private group setgid boundary" if workspace_valid else slot.linux_user,
            )
        )
        if workspace_valid and configured and current:
            try:
                _probe_directory(workspace, group_id=private_group.gr_gid, file_mode=0o640)
                checks.append(_success(prefix + "_workspace_probe", "handoff probe passed"))
            except OSError as exc:
                checks.append(
                    _failure(
                        prefix + "_workspace_probe",
                        "WORKER_WORKSPACE_UNWRITABLE",
                        type(exc).__name__,
                    )
                )

        home = self.platform_settings.worker_home_root / slot.linux_user
        home_valid = _directory_matches(
            home,
            owner_id=account.pw_uid,
            group_id=private_group.gr_gid,
            mode=0o700,
            require_access=False,
        )
        checks.append(
            _check(
                prefix + "_home",
                home_valid,
                "WORKER_HOME_INVALID",
                slot.linux_user,
            )
        )
        return checks

    def _runtime_packages(self, registry: WorkerRegistry | None) -> list[RuntimeReadinessCheck]:
        checks = [
            _check(
                "codex_binary",
                self.platform_settings.codex_binary.is_file()
                and os.access(self.platform_settings.codex_binary, os.X_OK),
                "CODEX_BINARY_UNAVAILABLE",
                self.platform_settings.codex_binary.name,
            ),
            _check(
                "systemd_run",
                shutil.which("systemd-run") is not None,
                "SYSTEMD_RUN_UNAVAILABLE",
                "available" if shutil.which("systemd-run") else "missing",
            ),
            _check(
                "runner_python",
                Path(sys.executable).is_file() and os.access(sys.executable, os.X_OK),
                "RUNNER_PYTHON_UNAVAILABLE",
                Path(sys.executable).name,
            ),
        ]
        try:
            load_definition_schema()
            for role in ("authoring", "image", "review", "item_management"):
                load_role_input_schema(role)
            for schema_id in RESULT_SCHEMA_FILES:
                load_role_result_schema(schema_id)
            checks.append(_success("workflow_schemas", "9 loaded"))
        except Exception as exc:
            checks.append(
                _failure("workflow_schemas", "WORKFLOW_SCHEMAS_INVALID", type(exc).__name__)
            )

        if registry is None:
            checks.append(
                _failure(
                    "generic_workflow_definition",
                    "WORKFLOW_DEFINITION_INVALID",
                    "worker registry unavailable",
                )
            )
        else:
            try:
                roles = {slot.role for slot in registry.config.slots if slot.enabled}
                compiled = compile_definition(self.workflow_settings.definition_path, roles)
                checks.append(
                    _success(
                        "generic_workflow_definition",
                        f"{compiled.definition.definition_key}@"
                        f"{compiled.definition.definition_version}",
                    )
                )
            except Exception as exc:
                checks.append(
                    _failure(
                        "generic_workflow_definition",
                        "WORKFLOW_DEFINITION_INVALID",
                        type(exc).__name__,
                    )
                )
        return checks


def _directory_matches(
    path: Path,
    *,
    owner_id: int,
    group_id: int,
    mode: int,
    require_access: bool = True,
) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return (
        not path.is_symlink()
        and stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid == owner_id
        and metadata.st_gid == group_id
        and stat.S_IMODE(metadata.st_mode) == mode
        and (not require_access or os.access(path, os.W_OK | os.X_OK))
    )


def _probe_directory(path: Path, *, group_id: int | None, file_mode: int) -> None:
    probe = path / f".eom-readiness-{uuid4().hex}"
    probe_file = probe / "probe"
    try:
        probe.mkdir(mode=0o700)
        if group_id is not None:
            os.chown(probe, -1, group_id)
            probe.chmod(0o2770)
        probe_file.write_bytes(b"ready\n")
        if group_id is not None:
            os.chown(probe_file, -1, group_id)
        probe_file.chmod(file_mode)
        metadata = probe_file.lstat()
        if probe_file.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise OSError("readiness probe is not a regular file")
    finally:
        try:
            probe_file.unlink(missing_ok=True)
        finally:
            with suppress(FileNotFoundError):
                probe.rmdir()


def _identity_can_execute(path: Path, *, user_id: int, group_ids: set[int]) -> bool:
    try:
        resolved = path.resolve(strict=True)
        for parent in reversed(resolved.parents):
            metadata = parent.stat()
            if not stat.S_ISDIR(metadata.st_mode) or not _has_permission(
                metadata, user_id=user_id, group_ids=group_ids, permission=0o1
            ):
                return False
        metadata = resolved.stat()
        return stat.S_ISREG(metadata.st_mode) and _has_permission(
            metadata, user_id=user_id, group_ids=group_ids, permission=0o1
        )
    except OSError:
        return False


def _has_permission(
    metadata: os.stat_result,
    *,
    user_id: int,
    group_ids: set[int],
    permission: int,
) -> bool:
    mode = stat.S_IMODE(metadata.st_mode)
    if metadata.st_uid == user_id:
        actual = (mode >> 6) & 0o7
    elif metadata.st_gid in group_ids:
        actual = (mode >> 3) & 0o7
    else:
        actual = mode & 0o7
    return actual & permission == permission


def _check(name: str, passed: bool, code: str, detail: str) -> RuntimeReadinessCheck:
    return RuntimeReadinessCheck(
        name=name,
        status=ReadinessStatus.PASS if passed else ReadinessStatus.FAIL,
        code="READY" if passed else code,
        detail=detail,
    )


def _success(name: str, detail: str) -> RuntimeReadinessCheck:
    return _check(name, True, "READY", detail)


def _failure(name: str, code: str, detail: str) -> RuntimeReadinessCheck:
    return _check(name, False, code, detail)
