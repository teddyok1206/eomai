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
from eom_workflow.control_schemas import validate_control_contract
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import CodexAuthBindingRecord, CodexCapabilitySnapshotRecord
from eom_orchestrator.control_service import (
    ControlPlaneError,
    compute_control_document_hash,
    record_capability_snapshot,
)
from eom_orchestrator.models import WorkerSlotRecord
from eom_orchestrator.reviewed_capability_policy import (
    COMPATIBILITY_SLOT_ROLES as COMPATIBILITY_SLOT_ROLES,
)
from eom_orchestrator.reviewed_capability_policy import (
    ReviewedCapabilityBinding as ReviewedCapabilityBinding,
)
from eom_orchestrator.reviewed_capability_policy import (
    ReviewedCapabilityBindingV3 as ReviewedCapabilityBindingV3,
)
from eom_orchestrator.reviewed_capability_policy import (
    ReviewedCapabilityPolicy as ReviewedCapabilityPolicy,
)
from eom_orchestrator.reviewed_capability_policy import (
    ReviewedModelCapability as ReviewedModelCapability,
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


class UnverifiedCapabilityAssignment(ControlPlaneError):
    """The exact assignment has no admitted models; this is not an auth failure."""

    def __init__(self, *, binding_id: str, assignment_revision_id: str | None) -> None:
        super().__init__(
            "CONTROL_CAPABILITY_BINDING_UNVERIFIED",
            "no reviewed model capability is admitted for this binding assignment",
        )
        self.binding_id = binding_id
        self.assignment_revision_id = assignment_revision_id


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
    if not capabilities and binding is not None:
        from eom_orchestrator.auth_enrollment_capability_admission import (
            enrollment_verified_capabilities,
        )

        capabilities = enrollment_verified_capabilities(session, binding=binding, policy=policy)
    if not capabilities:
        raise UnverifiedCapabilityAssignment(
            binding_id=binding_id,
            assignment_revision_id=(
                binding.current_assignment_revision_id if binding is not None else None
            ),
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
