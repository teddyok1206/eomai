"""Sanitized Codex authentication observations for exact fixed worker identities."""

from __future__ import annotations

import re
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from eom_workflow.control_plane import CodexAuthHealthView
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import CodexAuthBindingRecord
from eom_orchestrator.control_service import record_auth_health
from eom_orchestrator.worker_registry import WorkerSlot
from eom_orchestrator.worker_systemd import (
    WorkerAuthSystemdObservation,
    observe_worker_auth_systemd,
)

CODEX_BINARY = Path("/usr/local/bin/codex")
VERSION_PATTERN = re.compile(r"\Acodex-cli ([0-9]+\.[0-9]+\.[0-9]+)\s*\Z", re.ASCII)
CLI_ENVIRONMENT = {
    "HOME": "/var/empty",
    "LANG": "C.UTF-8",
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
}


@dataclass(frozen=True)
class WorkerAuthObservation:
    binding_id: str
    slot_key: str
    account_label: str
    state: str
    reason_code: str | None
    codex_cli_version: str
    observed_at: datetime
    valid_until: datetime
    probe_unit_name: str

    def document(self) -> dict[str, object]:
        return CodexAuthHealthView.model_validate(
            {
                "schema_version": "codex-auth-health-view/1.0",
                "binding_id": self.binding_id,
                "slot_key": self.slot_key,
                "account_label": self.account_label,
                "state": self.state,
                "reason_code": self.reason_code,
                "codex_cli_version": self.codex_cli_version,
                "observed_at": self.observed_at,
                "valid_until": self.valid_until,
            }
        ).model_dump(mode="json")


def observe_codex_cli_version() -> str | None:
    """Return only a validated semantic version from the root-owned global executable."""

    try:
        link = CODEX_BINARY.lstat()
        resolved = CODEX_BINARY.resolve(strict=True)
        metadata = resolved.stat()
        if (
            link.st_uid != 0
            or link.st_gid != 0
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != 0
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            return None
        completed = subprocess.run(
            (str(CODEX_BINARY), "--version"),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            env=CLI_ENVIRONMENT,
            timeout=15,
            text=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = VERSION_PATTERN.fullmatch(completed.stdout) if completed.returncode == 0 else None
    return match.group(1) if match is not None else None


def observe_worker_auth(
    *,
    slot: WorkerSlot,
    binding_id: str,
    account_label: str,
    observed_at: datetime,
    ttl: timedelta,
    probe: Callable[[WorkerSlot], WorkerAuthSystemdObservation] = observe_worker_auth_systemd,
    cli_version_observer: Callable[[], str | None] = observe_codex_cli_version,
) -> WorkerAuthObservation:
    """Observe exact identity health without returning raw subprocess output."""

    if ttl <= timedelta(0) or ttl > timedelta(hours=1):
        raise ValueError("authentication observation TTL is outside the reviewed bound")
    systemd_observation = probe(slot)
    cli_version = cli_version_observer()
    state = systemd_observation.state
    reason_code = systemd_observation.reason_code
    if cli_version is None:
        state = "DEGRADED"
        reason_code = "CODEX_CLI_UNAVAILABLE"
        cli_version = "0.0.0"
    return WorkerAuthObservation(
        binding_id=binding_id,
        slot_key=f"slot{slot.slot_id}",
        account_label=account_label,
        state=state,
        reason_code=reason_code,
        codex_cli_version=cli_version,
        observed_at=observed_at,
        valid_until=observed_at + ttl,
        probe_unit_name=systemd_observation.unit_name,
    )


def persist_worker_auth_observation(
    session: Session, observation: WorkerAuthObservation
) -> CodexAuthBindingRecord:
    """Persist only the schema-valid sanitized projection and append-only event."""

    return record_auth_health(session, document=observation.document())


def project_worker_auth_health(
    binding: CodexAuthBindingRecord, *, as_of: datetime
) -> CodexAuthHealthView:
    """Project an expired READY observation as STALE without mutating history."""

    if as_of.tzinfo is None or as_of.utcoffset() != timedelta(0):
        raise ValueError("authentication health projection time must use UTC")
    if (
        binding.codex_cli_version is None
        or binding.observed_at is None
        or binding.valid_until is None
    ):
        raise ValueError("authentication health evidence is incomplete")
    state = binding.state
    reason_code = binding.reason_code
    if state == "READY" and binding.valid_until <= as_of:
        state = "STALE"
        reason_code = "OBSERVATION_EXPIRED"
    return CodexAuthHealthView.model_validate(
        {
            "schema_version": "codex-auth-health-view/1.0",
            "binding_id": binding.binding_id,
            "slot_key": f"slot{binding.worker_slot_id}",
            "account_label": binding.account_label,
            "state": state,
            "reason_code": reason_code,
            "codex_cli_version": binding.codex_cli_version,
            "observed_at": binding.observed_at,
            "valid_until": binding.valid_until,
        }
    )
