"""Reviewed Codex capability policy plus non-generating local CLI observation."""

from __future__ import annotations

import os
import stat
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import yaml
from eom_identifiers import new_capability_snapshot_id
from eom_workflow.control_plane import CodexCapabilitySnapshot, ModelCapability, ReasoningEffort
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import CodexCapabilitySnapshotRecord
from eom_orchestrator.control_service import (
    ControlPlaneError,
    compute_control_document_hash,
    record_capability_snapshot,
)
from eom_orchestrator.worker_auth import CLI_ENVIRONMENT, CODEX_BINARY, observe_codex_cli_version

MAX_POLICY_BYTES = 64 * 1024
REQUIRED_EXEC_HELP_FLAGS = frozenset(
    {
        "--model",
        "--config",
        "--ephemeral",
        "--ignore-user-config",
        "--output-schema",
        "--image",
    }
)


class ReviewedModelCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)

    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    reasoning_efforts: tuple[ReasoningEffort, ...] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def unique_efforts(self) -> ReviewedModelCapability:
        if len(self.reasoning_efforts) != len(set(self.reasoning_efforts)):
            raise ValueError("reviewed reasoning efforts must be unique")
        return self


class ReviewedCapabilityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1, le=1)
    expected_codex_cli_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    models: tuple[ReviewedModelCapability, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def unique_models(self) -> ReviewedCapabilityPolicy:
        names = [item.model for item in self.models]
        if len(names) != len(set(names)):
            raise ValueError("reviewed capability models must be unique")
        return self


def load_reviewed_capability_policy(
    path: Path, *, require_root_owned: bool = True
) -> ReviewedCapabilityPolicy:
    """Load one bounded protected operator policy without accepting ambient paths."""

    try:
        if not path.is_absolute():
            raise OSError("capability policy path is not absolute")
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or path.resolve(strict=True) != path
            or metadata.st_size > MAX_POLICY_BYTES
            or metadata.st_mode & 0o002
            or (require_root_owned and (metadata.st_uid != 0 or metadata.st_gid != 0))
        ):
            raise OSError("capability policy file is unsafe")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, encoding="utf-8") as source:
            value: object = yaml.safe_load(source.read(MAX_POLICY_BYTES + 1))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ControlPlaneError(
            "CONTROL_CAPABILITY_POLICY_INVALID", "reviewed capability policy is unavailable"
        ) from exc
    try:
        return ReviewedCapabilityPolicy.model_validate(value)
    except ValueError as exc:
        raise ControlPlaneError(
            "CONTROL_CAPABILITY_POLICY_INVALID", "reviewed capability policy is invalid"
        ) from exc


def observe_codex_cli_surface() -> tuple[str, frozenset[str]]:
    """Observe only a sanitized version and required option membership from local help."""

    version = observe_codex_cli_version()
    if version is None:
        raise ControlPlaneError(
            "CONTROL_CAPABILITY_OBSERVATION_FAILED", "Codex CLI version is unavailable"
        )
    try:
        completed = subprocess.run(
            (str(CODEX_BINARY), "exec", "--help"),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            env=CLI_ENVIRONMENT,
            timeout=15,
            text=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ControlPlaneError(
            "CONTROL_CAPABILITY_OBSERVATION_FAILED", "Codex CLI help is unavailable"
        ) from exc
    if completed.returncode != 0:
        raise ControlPlaneError("CONTROL_CAPABILITY_OBSERVATION_FAILED", "Codex CLI help failed")
    flags = frozenset(flag for flag in REQUIRED_EXEC_HELP_FLAGS if flag in completed.stdout)
    if flags != REQUIRED_EXEC_HELP_FLAGS:
        raise ControlPlaneError(
            "CONTROL_CAPABILITY_OBSERVATION_FAILED", "Codex CLI surface is incompatible"
        )
    return version, flags


def record_reviewed_capability_snapshot(
    session: Session,
    *,
    binding_id: str,
    policy: ReviewedCapabilityPolicy,
    observed_at: datetime,
    ttl: timedelta,
    cli_observation: tuple[str, frozenset[str]],
    source: Literal["LOCAL_OBSERVATION", "OPERATOR_ASSERTED"] = "OPERATOR_ASSERTED",
) -> CodexCapabilitySnapshotRecord:
    """Persist exact reviewed model/effort pairs only after CLI compatibility observation."""

    if ttl <= timedelta(0) or ttl > timedelta(hours=1):
        raise ValueError("capability snapshot TTL is outside the reviewed bound")
    cli_version, flags = cli_observation
    if cli_version != policy.expected_codex_cli_version or flags != REQUIRED_EXEC_HELP_FLAGS:
        raise ControlPlaneError(
            "CONTROL_CAPABILITY_POLICY_MISMATCH", "reviewed capability policy differs from CLI"
        )
    capabilities = [
        ModelCapability(
            model=item.model,
            reasoning_efforts=item.reasoning_efforts,
            state="AVAILABLE",
        ).model_dump(mode="json")
        for item in policy.models
    ]
    document: dict[str, object] = {
        "schema_version": "codex-capability-snapshot/1.0",
        "capability_snapshot_id": new_capability_snapshot_id(),
        "binding_id": binding_id,
        "codex_cli_version": cli_version,
        "source": source,
        "capabilities": capabilities,
        "observed_at": observed_at,
        "valid_until": observed_at + ttl,
        "snapshot_sha256": "sha256:" + "0" * 64,
    }
    normalized = CodexCapabilitySnapshot.model_validate(document).model_dump(mode="json")
    normalized["snapshot_sha256"] = compute_control_document_hash(normalized, "snapshot_sha256")
    return record_capability_snapshot(session, document=normalized)
