"""Fixed root staging and owner-only result materialization for one CPU experiment."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eom_catalog_contracts.inference_transfer_experiment import InferenceTransferExperimentRequest
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import canonical_json_bytes

from eom_orchestrator.inference_transfer_experiment_ports import LocalExperimentInput
from eom_orchestrator.inference_transfer_experiment_workspace import (
    MAX_EXPERIMENT_MEMBER_BYTES,
    ProtectedExperimentWorkspace,
)

OWNER_ROOT = Path("/var/lib/eom-workflow-runner/inference-transfer-experiments")
RUNTIME_ROOT = Path("/run/eom-embedding-experiments")
OWNER_USER = "eom-workflow-runner"
_ROOT_UID = 0
_EXECUTION = re.compile(r"embeddingexecution_[0-9a-f]{32}\Z", re.ASCII)


class CpuHandoffError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CpuHandoffIdentity:
    owner_uid: int
    owner_gid: int


def fixed_owner_identity() -> CpuHandoffIdentity:
    value = pwd.getpwnam(OWNER_USER)
    if value.pw_uid <= 0 or value.pw_gid <= 0:
        raise CpuHandoffError("INFERENCE_CPU_OWNER_IDENTITY_INVALID")
    return CpuHandoffIdentity(value.pw_uid, value.pw_gid)


def validate_cpu_execution_id(value: str) -> str:
    if not isinstance(value, str) or _EXECUTION.fullmatch(value) is None:
        raise CpuHandoffError("INFERENCE_CPU_EXECUTION_ID_INVALID")
    return value


def _directory_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


@contextmanager
def _directory(
    path: Path, *, owner: CpuHandoffIdentity, uid: int, mode: int, gid: int | None = None
) -> Iterator[int]:
    """Keep ancestor FDs until completion; PID1 never receives an owner-writable path."""
    if not path.is_absolute() or ".." in path.parts or Path("/mnt/nas") in (path, *path.parents):
        raise CpuHandoffError("INFERENCE_CPU_DIRECTORY_INVALID")
    opened: list[tuple[int, int | None, str, os.stat_result]] = []
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        descriptor = os.open(path.root, flags)
        opened.append((descriptor, None, path.root, os.fstat(descriptor)))
        for member in path.parts[1:]:
            parent = descriptor
            descriptor = os.open(member, flags, dir_fd=parent)
            opened.append((descriptor, parent, member, os.fstat(descriptor)))
        for _fd, _parent, _member, value in opened:
            sticky_root = value.st_uid == _ROOT_UID and bool(value.st_mode & stat.S_ISVTX)
            if (
                not stat.S_ISDIR(value.st_mode)
                or value.st_uid not in {_ROOT_UID, owner.owner_uid}
                or (value.st_mode & 0o022 and not sticky_root)
            ):
                raise CpuHandoffError("INFERENCE_CPU_DIRECTORY_INVALID")
        value = opened[-1][3]
        if (
            value.st_uid != uid
            or stat.S_IMODE(value.st_mode) != mode
            or (gid is not None and value.st_gid != gid)
        ):
            raise CpuHandoffError("INFERENCE_CPU_DIRECTORY_INVALID")
        yield descriptor
        for fd, parent_fd, member, initial in opened:
            named = os.stat(member, dir_fd=parent_fd, follow_symlinks=False)
            if _directory_identity(initial) != _directory_identity(
                os.fstat(fd)
            ) or _directory_identity(initial) != _directory_identity(named):
                raise CpuHandoffError("INFERENCE_CPU_DIRECTORY_CHANGED")
    except OSError as exc:
        raise CpuHandoffError("INFERENCE_CPU_DIRECTORY_INVALID") from exc
    finally:
        for fd, _parent, _member, _initial in reversed(opened):
            os.close(fd)


def _read_member(
    directory: int,
    name: str,
    *,
    uid: int,
    mode: int,
    gid: int | None = None,
    allow_empty: bool = False,
) -> bytes:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=directory
        )
        initial = os.fstat(descriptor)
        if (
            not stat.S_ISREG(initial.st_mode)
            or initial.st_nlink != 1
            or initial.st_uid != uid
            or (gid is not None and initial.st_gid != gid)
            or stat.S_IMODE(initial.st_mode) != mode
            or not (0 if allow_empty else 1) <= initial.st_size <= MAX_EXPERIMENT_MEMBER_BYTES
        ):
            raise CpuHandoffError("INFERENCE_CPU_MEMBER_INVALID")
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(descriptor, min(1024**2, initial.st_size + 1 - total)):
            total += len(chunk)
            if total > initial.st_size:
                raise CpuHandoffError("INFERENCE_CPU_MEMBER_CHANGED")
            chunks.append(chunk)
        final = os.fstat(descriptor)
        named = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if (
            total != initial.st_size
            or _file_identity(initial) != _file_identity(final)
            or _file_identity(final) != _file_identity(named)
        ):
            raise CpuHandoffError("INFERENCE_CPU_MEMBER_CHANGED")
        return b"".join(chunks)
    except OSError as exc:
        raise CpuHandoffError("INFERENCE_CPU_MEMBER_INVALID") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CpuHandoffError("INFERENCE_CPU_REQUEST_INVALID")
        result[key] = value
    return result


def _request(payload: bytes) -> InferenceTransferExperimentRequest:
    value = json.loads(payload, object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise CpuHandoffError("INFERENCE_CPU_REQUEST_INVALID")
    validate_contract("item-inference-transfer-experiment", value)
    request = InferenceTransferExperimentRequest.model_validate(value)
    if (
        payload != canonical_json_bytes(request.model_dump(mode="json"))
        or len(payload) > request.budget.maximum_input_bytes
    ):
        raise CpuHandoffError("INFERENCE_CPU_REQUEST_INVALID")
    return request


def _owner_request(execution_id: str, owner: CpuHandoffIdentity) -> tuple[bytes, str]:
    with (
        _directory(OWNER_ROOT, owner=owner, uid=owner.owner_uid, mode=0o700),
        _directory(
            OWNER_ROOT / execution_id, owner=owner, uid=owner.owner_uid, mode=0o700
        ) as directory,
    ):
        marker = _read_member(
            directory, ".launch-started", uid=owner.owner_uid, mode=0o600, allow_empty=True
        )
        if marker:
            raise CpuHandoffError("INFERENCE_CPU_LAUNCH_MARKER_INVALID")
        payload = _read_member(directory, "request.json", uid=owner.owner_uid, mode=0o600)
    request = _request(payload)
    return payload, request.request_sha256


def _create_root_member(
    directory: int, name: str, payload: bytes, *, owner_gid: int, mode: int
) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            mode,
            dir_fd=directory,
        )
        os.fchown(descriptor, _ROOT_UID, owner_gid)
        os.fchmod(descriptor, mode)
        remaining = memoryview(payload)
        while remaining:
            count = os.write(descriptor, remaining)
            if count <= 0:
                raise CpuHandoffError("INFERENCE_CPU_HANDOFF_WRITE_FAILED")
            remaining = remaining[count:]
        os.fsync(descriptor)
        initial = os.fstat(descriptor)
        named = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if (
            initial.st_uid != _ROOT_UID
            or initial.st_gid != owner_gid
            or stat.S_IMODE(initial.st_mode) != mode
            or initial.st_nlink != 1
            or initial.st_size != len(payload)
            or _file_identity(initial) != _file_identity(named)
        ):
            raise CpuHandoffError("INFERENCE_CPU_HANDOFF_WRITE_FAILED")
    except OSError as exc:
        raise CpuHandoffError("INFERENCE_CPU_HANDOFF_WRITE_FAILED") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def prepare_cpu_handoff(execution_id: str) -> None:
    """Root-only fixed prepare unit; partial/existing handoffs are never overwritten."""
    execution_id = validate_cpu_execution_id(execution_id)
    if os.geteuid() != _ROOT_UID:
        raise CpuHandoffError("INFERENCE_CPU_ROOT_REQUIRED")
    owner = fixed_owner_identity()
    payload, _semantic_sha = _owner_request(execution_id, owner)
    with _directory(
        RUNTIME_ROOT, owner=owner, uid=_ROOT_UID, gid=owner.owner_gid, mode=0o750
    ) as parent:
        try:
            os.mkdir(execution_id, mode=0o750, dir_fd=parent)
        except OSError as exc:
            raise CpuHandoffError("INFERENCE_CPU_HANDOFF_EXISTS_OR_UNAVAILABLE") from exc
        descriptor = os.open(
            execution_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent
        )
        try:
            os.fchown(descriptor, _ROOT_UID, owner.owner_gid)
            os.fchmod(descriptor, 0o750)
            _create_root_member(
                descriptor, "input.json", payload, owner_gid=owner.owner_gid, mode=0o600
            )
            _create_root_member(
                descriptor, "output.json", b"", owner_gid=owner.owner_gid, mode=0o640
            )
            os.fsync(descriptor)
            named = os.stat(execution_id, dir_fd=parent, follow_symlinks=False)
            if _directory_identity(os.fstat(descriptor)) != _directory_identity(named):
                raise CpuHandoffError("INFERENCE_CPU_DIRECTORY_CHANGED")
            os.fsync(parent)
        finally:
            os.close(descriptor)


def materialize_cpu_output(prepared: LocalExperimentInput) -> None:
    """Called only after confirmed unit termination; does not authorize or publish an Artifact."""
    execution_id = validate_cpu_execution_id(prepared.execution_id)
    owner = fixed_owner_identity()
    if os.geteuid() != owner.owner_uid or prepared.workspace != OWNER_ROOT / execution_id:
        raise CpuHandoffError("INFERENCE_CPU_OWNER_IDENTITY_INVALID")
    original, request_sha = _owner_request(execution_id, owner)
    if request_sha != prepared.request_sha256 or len(original) != prepared.request_bytes:
        raise CpuHandoffError("INFERENCE_CPU_REQUEST_PIN_MISMATCH")
    with (
        _directory(RUNTIME_ROOT, owner=owner, uid=_ROOT_UID, gid=owner.owner_gid, mode=0o750),
        _directory(
            RUNTIME_ROOT / execution_id,
            owner=owner,
            uid=_ROOT_UID,
            gid=owner.owner_gid,
            mode=0o750,
        ) as directory,
    ):
        # Root input is not owner-readable (0600). Verify the exact original input
        # using the output's validated request/result closure at the existing owner
        # boundary; PID1-only input bytes are admitted by root prepare above.
        payload = _read_member(
            directory, "output.json", uid=_ROOT_UID, gid=owner.owner_gid, mode=0o640
        )
    ProtectedExperimentWorkspace(OWNER_ROOT).materialize_cpu_result(prepared, payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-id", required=True)
    arguments = parser.parse_args()
    try:
        prepare_cpu_handoff(arguments.execution_id)
    except Exception:
        # No source content, validation payload or privileged path is logged.
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
