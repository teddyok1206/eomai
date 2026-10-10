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
from eom_workflow.codex_compatibility import CodexCompatibilityRuntime
from eom_workflow.control_plane import CodexCapabilitySnapshot, ModelCapability, ReasoningEffort
from eom_workflow.control_schemas import validate_control_contract
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import CodexAuthBindingRecord, CodexCapabilitySnapshotRecord
from eom_orchestrator.control_service import (
    ControlPlaneError,
    compute_control_document_hash,
    record_capability_snapshot,
)
from eom_orchestrator.models import WorkerSlotRecord
from eom_orchestrator.worker_auth import CLI_ENVIRONMENT, CODEX_BINARY, observe_codex_cli_version
from eom_orchestrator.worker_registry import FIXED_WORKER_SLOT_ROLES

MAX_POLICY_BYTES = 64 * 1024
COMPATIBILITY_SLOT_ROLES = FIXED_WORKER_SLOT_ROLES
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


class ReviewedCapabilityBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    binding_id: str = Field(pattern=r"^authbinding_[0-9a-f]{32}$")
    assignment_revision_id: str | None = Field(pattern=r"^authassignrev_[0-9a-f]{32}$")


class ReviewedCapabilityBindingV3(ReviewedCapabilityBinding):
    slot_id: Literal["01", "02", "03", "04", "05", "06"]
    role: Literal["authoring", "review", "image", "item_management", "support"]

    @model_validator(mode="after")
    def fixed_slot_role(self) -> ReviewedCapabilityBindingV3:
        if self.role != COMPATIBILITY_SLOT_ROLES[self.slot_id]:
            raise ValueError("V3 capability binding role must match its fixed slot")
        return self


class ReviewedModelCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)

    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    reasoning_efforts: tuple[ReasoningEffort, ...] = Field(min_length=1, max_length=5)
    bindings: tuple[ReviewedCapabilityBinding | ReviewedCapabilityBindingV3, ...] | None = Field(
        default=None, min_length=1, max_length=6
    )

    @model_validator(mode="after")
    def unique_efforts(self) -> ReviewedModelCapability:
        if len(self.reasoning_efforts) != len(set(self.reasoning_efforts)):
            raise ValueError("reviewed reasoning efforts must be unique")
        if self.bindings is not None and (
            len({item.binding_id for item in self.bindings}) != len(self.bindings)
            or self.bindings != tuple(sorted(self.bindings, key=lambda item: item.binding_id))
        ):
            raise ValueError("reviewed binding scopes must be unique and sorted")
        if self.bindings is not None:
            slots = [
                pin.slot_id for pin in self.bindings if isinstance(pin, ReviewedCapabilityBindingV3)
            ]
            if len(slots) != len(set(slots)):
                raise ValueError("V3 capability scope must have unique slots")
        return self


class ReviewedCapabilityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1, 2, 3]
    expected_codex_cli_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    models: tuple[ReviewedModelCapability, ...] = Field(min_length=1, max_length=32)
    compatibility_runtime: CodexCompatibilityRuntime | None = None

    @field_validator("version", mode="before")
    @classmethod
    def integer_policy_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("reviewed policy version must be an integer")
        return value

    @model_validator(mode="after")
    def unique_models(self) -> ReviewedCapabilityPolicy:
        if self.version == 1:
            names = [item.model for item in self.models]
            if (
                len(self.models) > 16
                or len(names) != len(set(names))
                or self.compatibility_runtime is not None
                or any(item.bindings is not None for item in self.models)
            ):
                raise ValueError("V1 reviewed models must be unique, global and runtime-unscoped")
        elif (
            self.compatibility_runtime is None
            or self.compatibility_runtime.cli_version != self.expected_codex_cli_version
            or len({(item.model, item.bindings) for item in self.models}) != len(self.models)
        ):
            raise ValueError(
                "scoped reviewed policy requires exact runtime and unique model scopes"
            )
        if self.version in {2, 3} and any(
            isinstance(pin, ReviewedCapabilityBindingV3) != (self.version == 3)
            for item in self.models
            for pin in item.bindings or ()
        ):
            raise ValueError("reviewed binding shape must match its policy version")
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
        if isinstance(value, dict) and value.get("version") in {2, 3}:
            validate_control_contract(
                f"codex-reviewed-capability-policy-v{value['version']}", value
            )
        return ReviewedCapabilityPolicy.model_validate(value)
    except (ValueError, JsonSchemaValidationError) as exc:
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


def reviewed_capabilities_for_binding(
    session: Session,
    *,
    binding_id: str,
    policy: ReviewedCapabilityPolicy,
    cli_observation: tuple[str, frozenset[str]],
) -> tuple[ModelCapability, ...]:
    """Read-only admission preflight, repeated at the final snapshot write boundary."""

    cli_version, flags = cli_observation
    if cli_version != policy.expected_codex_cli_version or flags != REQUIRED_EXEC_HELP_FLAGS:
        raise ControlPlaneError(
            "CONTROL_CAPABILITY_POLICY_MISMATCH", "reviewed capability policy differs from CLI"
        )
    if policy.version in {2, 3}:
        # A same-version binary/helper replacement also invalidates scoped live admission.
        from eom_orchestrator.codex_compatibility_runtime import observe_compatibility_runtime

        if observe_compatibility_runtime() != policy.compatibility_runtime:
            raise ControlPlaneError(
                "CONTROL_CAPABILITY_POLICY_MISMATCH", "compatibility runtime identity differs"
            )
    binding = session.get(CodexAuthBindingRecord, binding_id) if policy.version in {2, 3} else None
    if policy.version in {2, 3} and binding is None:
        raise ControlPlaneError("CONTROL_BINDING_NOT_FOUND", "Codex binding is unavailable")
    slot = None
    if policy.version == 3 and binding is not None:
        slot = session.get(WorkerSlotRecord, binding.worker_slot_id)
        if (
            slot is None
            or not slot.enabled
            or slot.role != COMPATIBILITY_SLOT_ROLES.get(slot.slot_id)
        ):
            raise ControlPlaneError(
                "CONTROL_CAPABILITY_BINDING_UNVERIFIED", "current binding slot role is unverified"
            )
    admitted: dict[str, set[ReasoningEffort]] = {}
    for item in policy.models:
        if (
            policy.version == 3
            and binding is not None
            and slot is not None
            and any(
                isinstance(pin, ReviewedCapabilityBindingV3)
                and pin.binding_id == binding_id
                and (pin.slot_id != binding.worker_slot_id or pin.role != slot.role)
                for pin in item.bindings or ()
            )
        ):
            raise ControlPlaneError(
                "CONTROL_CAPABILITY_BINDING_UNVERIFIED", "reviewed binding slot or role differs"
            )
        if item.bindings is None or any(
            pin.binding_id == binding_id
            and binding is not None
            and pin.assignment_revision_id == binding.current_assignment_revision_id
            for pin in item.bindings
        ):
            admitted.setdefault(item.model, set()).update(item.reasoning_efforts)
    capabilities = tuple(
        ModelCapability(
            model=model,
            reasoning_efforts=tuple(sorted(efforts)),
            state="AVAILABLE",
        )
        for model, efforts in sorted(admitted.items())
    )
    if not capabilities:
        raise ControlPlaneError(
            "CONTROL_CAPABILITY_BINDING_UNVERIFIED",
            "no reviewed model capability is admitted for this binding assignment",
        )
    if policy.version == 1:
        # Keep legacy policy ordering and snapshot hashes unchanged.
        capabilities = tuple(
            ModelCapability(
                model=item.model,
                reasoning_efforts=item.reasoning_efforts,
                state="AVAILABLE",
            )
            for item in policy.models
        )
    return capabilities


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
    capabilities = reviewed_capabilities_for_binding(
        session, binding_id=binding_id, policy=policy, cli_observation=cli_observation
    )
    document: dict[str, object] = {
        "schema_version": "codex-capability-snapshot/1.0",
        "capability_snapshot_id": new_capability_snapshot_id(),
        "binding_id": binding_id,
        "codex_cli_version": cli_observation[0],
        "source": source,
        "capabilities": [item.model_dump(mode="json") for item in capabilities],
        "observed_at": observed_at,
        "valid_until": observed_at + ttl,
        "snapshot_sha256": "sha256:" + "0" * 64,
    }
    normalized = CodexCapabilitySnapshot.model_validate(document).model_dump(mode="json")
    normalized["snapshot_sha256"] = compute_control_document_hash(normalized, "snapshot_sha256")
    return record_capability_snapshot(session, document=normalized)
