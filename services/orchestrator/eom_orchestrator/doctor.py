"""Runtime prerequisite checks for eomctl system doctor."""

from __future__ import annotations

import os
import pwd
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from alembic.runtime.migration import MigrationContext
from eom_protocol.validation import load_schema
from sqlalchemy import Engine, text

from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from eom_orchestrator.protocol import SCHEMA_NAMES
from eom_orchestrator.runtime_configuration import resolve_worker_configuration
from eom_orchestrator.settings import Settings
from eom_orchestrator.worker_systemd import (
    inspect_worker_systemd_contract,
    probe_worker_systemd_authorization,
)

EOM_API_RUNTIME_PREFIX = Path("/srv/eom/conda/envs/eom-api")


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def runtime_configuration_check(settings: Settings) -> DoctorCheck:
    """Inspect explicit worker configuration without starting a worker or probing Codex."""
    try:
        resolved = resolve_worker_configuration(settings)
    except Exception as exc:
        return DoctorCheck("orchestrator_runtime_configuration", False, type(exc).__name__)
    return DoctorCheck(
        "orchestrator_runtime_configuration",
        True,
        f"source={resolved.source.value}; version={resolved.registry.config.version}",
    )


def runtime_environment_check(prefix: Path | None = None) -> DoctorCheck:
    """Verify that eomctl is running from its deployed application runtime."""
    actual_prefix = (prefix or Path(sys.prefix)).resolve()
    return DoctorCheck(
        "eom_api_environment",
        actual_prefix == EOM_API_RUNTIME_PREFIX,
        str(actual_prefix),
    )


def run_doctor(engine: Engine, settings: Settings) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            revision = MigrationContext.configure(connection).get_current_revision()
        checks.append(DoctorCheck("postgresql", True, "connected"))
        checks.append(
            DoctorCheck(
                "migration_revision",
                revision == CURRENT_MIGRATION_REVISION,
                revision or "not migrated",
            )
        )
    except Exception as exc:  # doctor must report all independent checks
        checks.append(DoctorCheck("postgresql", False, type(exc).__name__))
        checks.append(DoctorCheck("migration_revision", False, "unavailable"))

    nas_mount = Path("/mnt/nas")
    checks.append(DoctorCheck("nas_mount", os.path.ismount(nas_mount), str(nas_mount)))
    checks.append(
        DoctorCheck(
            "nas_artifact_root",
            settings.nas_artifact_root.is_dir(),
            str(settings.nas_artifact_root),
        )
    )
    checks.append(
        DoctorCheck(
            "codex_binary",
            settings.codex_binary.is_file() and os.access(settings.codex_binary, os.X_OK),
            str(settings.codex_binary),
        )
    )
    checks.append(
        DoctorCheck(
            "systemctl",
            Path("/usr/bin/systemctl").is_file() and os.access("/usr/bin/systemctl", os.X_OK),
            "/usr/bin/systemctl",
        )
    )
    for index in range(1, 6):
        user = f"eom-cdx-{index:02d}"
        try:
            pwd.getpwnam(user)
            found = True
        except KeyError:
            found = False
        checks.append(DoctorCheck(f"worker_user_{index:02d}", found, user))
    configuration = runtime_configuration_check(settings)
    checks.append(configuration)
    try:
        resolved = resolve_worker_configuration(settings)
        registry = resolved.registry
        authoring = registry.select("authoring")
        detail = f"authoring={authoring.linux_user},global={registry.global_codex_concurrency}"
        checks.append(DoctorCheck("worker_slot_config", True, detail))
        for slot in sorted(
            (candidate for candidate in registry.config.slots if candidate.enabled),
            key=lambda candidate: candidate.slot_id,
        ):
            contract = inspect_worker_systemd_contract(slot)
            checks.append(
                DoctorCheck(
                    f"worker_systemd_template_{slot.slot_id}",
                    contract.ready,
                    contract.detail,
                )
            )
            authorization = probe_worker_systemd_authorization(slot) if contract.ready else contract
            checks.append(
                DoctorCheck(
                    f"worker_systemd_authorization_{slot.slot_id}",
                    authorization.ready,
                    authorization.detail,
                )
            )
    except Exception as exc:
        checks.append(DoctorCheck("worker_slot_config", False, type(exc).__name__))
    checks.append(runtime_environment_check())
    checks.append(
        DoctorCheck(
            "staging_directory",
            settings.staging_root.is_dir() and os.access(settings.staging_root, os.W_OK),
            str(settings.staging_root),
        )
    )
    try:
        for name in SCHEMA_NAMES:
            load_schema(name)
        checks.append(DoctorCheck("protocol_schemas", True, f"{len(SCHEMA_NAMES)} loaded"))
    except Exception as exc:
        checks.append(DoctorCheck("protocol_schemas", False, type(exc).__name__))
    return checks
