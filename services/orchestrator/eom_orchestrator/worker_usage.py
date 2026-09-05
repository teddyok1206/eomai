"""Orchestrator adapter for one sanitized fixed-slot Codex usage observation."""

from __future__ import annotations

import json
import os
import pwd
import stat
from pathlib import Path

from eom_workflow import CodexUsageObservation, validate_control_contract
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

from eom_orchestrator.control_service import ControlPlaneError, compute_control_document_hash
from eom_orchestrator.worker_registry import WorkerSlot
from eom_orchestrator.worker_systemd import launch_worker_usage_unit

MAX_HANDOFF_BYTES = 128 * 1024
USAGE_INVALID_EXIT = 40
USAGE_AUTH_REQUIRED_EXIT = 41
USAGE_TIMEOUT_EXIT = 42


def observe_worker_usage(
    *, slot: WorkerSlot, command_id: str, binding_id: str
) -> CodexUsageObservation:
    """Return a schema-valid observation without exposing App Server account data."""

    handoff = Path(f"/run/eom-codex-usage-{slot.slot_id}") / f"{command_id}.json"
    existing = _read_handoff(slot=slot, path=handoff, missing_ok=True)
    if existing is not None:
        return _validate_observation(
            existing,
            slot=slot,
            command_id=command_id,
            binding_id=binding_id,
        )
    try:
        run = launch_worker_usage_unit(slot, command_id, binding_id)
    except (OSError, ValueError) as exc:
        raise ControlPlaneError(
            "CODEX_USAGE_UNAVAILABLE", "Codex usage observation is unavailable"
        ) from exc
    if run.exit_code != 0:
        code = {
            USAGE_AUTH_REQUIRED_EXIT: "CODEX_USAGE_AUTH_REQUIRED",
            USAGE_TIMEOUT_EXIT: "CODEX_USAGE_TIMEOUT",
            USAGE_INVALID_EXIT: "CODEX_USAGE_INVALID",
        }.get(run.exit_code, "CODEX_USAGE_UNAVAILABLE")
        raise ControlPlaneError(code, "Codex usage observation failed")
    raw = _read_handoff(slot=slot, path=handoff, missing_ok=False)
    if raw is None:
        raise ControlPlaneError("CODEX_USAGE_MISSING", "Codex usage handoff is missing")
    return _validate_observation(
        raw,
        slot=slot,
        command_id=command_id,
        binding_id=binding_id,
    )


def _read_handoff(*, slot: WorkerSlot, path: Path, missing_ok: bool) -> object | None:
    account = pwd.getpwnam(slot.linux_user)
    root = path.parent
    try:
        root_descriptor = os.open(
            root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    except FileNotFoundError:
        if missing_ok:
            return None
        raise ControlPlaneError(
            "CODEX_USAGE_MISSING", "Codex usage handoff directory is missing"
        ) from None
    try:
        root_metadata = os.fstat(root_descriptor)
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or root_metadata.st_uid != account.pw_uid
            or root_metadata.st_gid != account.pw_gid
            or stat.S_IMODE(root_metadata.st_mode) != 0o770
        ):
            raise ControlPlaneError("CODEX_USAGE_INVALID", "Codex usage handoff directory differs")
        try:
            descriptor = os.open(
                path.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=root_descriptor,
            )
        except FileNotFoundError:
            if missing_ok:
                return None
            raise ControlPlaneError(
                "CODEX_USAGE_MISSING", "Codex usage handoff is missing"
            ) from None
        try:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != account.pw_uid
                or before.st_gid != account.pw_gid
                or stat.S_IMODE(before.st_mode) != 0o640
                or before.st_nlink != 1
                or not 1 <= before.st_size <= MAX_HANDOFF_BYTES
            ):
                raise ControlPlaneError("CODEX_USAGE_INVALID", "Codex usage handoff differs")
            chunks = bytearray()
            while len(chunks) <= MAX_HANDOFF_BYTES:
                chunk = os.read(descriptor, min(8192, MAX_HANDOFF_BYTES + 1 - len(chunks)))
                if not chunk:
                    break
                chunks.extend(chunk)
            after = os.fstat(descriptor)
            before_identity = (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_uid,
                before.st_gid,
                before.st_nlink,
                before.st_size,
                before.st_mtime_ns,
            )
            after_identity = (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_uid,
                after.st_gid,
                after.st_nlink,
                after.st_size,
                after.st_mtime_ns,
            )
            if len(chunks) > MAX_HANDOFF_BYTES or before_identity != after_identity:
                raise ControlPlaneError("CODEX_USAGE_INVALID", "Codex usage handoff changed")
        finally:
            os.close(descriptor)
        os.unlink(path.name, dir_fd=root_descriptor)
        try:
            value: object = json.loads(chunks)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ControlPlaneError(
                "CODEX_USAGE_INVALID", "Codex usage handoff is malformed"
            ) from exc
        return value
    finally:
        os.close(root_descriptor)


def _validate_observation(
    value: object, *, slot: WorkerSlot, command_id: str, binding_id: str
) -> CodexUsageObservation:
    try:
        if not isinstance(value, dict):
            raise ValueError("usage handoff is not an object")
        validate_control_contract("codex-usage-observation", value)
        observation = CodexUsageObservation.model_validate(value)
    except (JsonSchemaValidationError, PydanticValidationError, ValueError) as exc:
        raise ControlPlaneError("CODEX_USAGE_INVALID", "Codex usage handoff is invalid") from exc
    if (
        observation.command_id != command_id
        or observation.binding_id != binding_id
        or observation.slot_key != f"slot{slot.slot_id}"
        or observation.observation_sha256
        != compute_control_document_hash(observation.model_dump(mode="json"), "observation_sha256")
    ):
        raise ControlPlaneError("CODEX_USAGE_INVALID", "Codex usage identity differs")
    return observation
