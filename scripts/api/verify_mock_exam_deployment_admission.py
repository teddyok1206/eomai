#!/srv/eom/conda/envs/eom-api/bin/python
"""Fail closed when a release would replace an active mock-exam production plan.

The deploy wrapper installs this file as a root-owned executable, then runs it as the
unprivileged ``eom-api`` account.  Checkpoint payloads are validated with the currently
installed API contract; repository Python is never imported by the admission check.
"""

from __future__ import annotations

import os
import re
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

CHECKPOINT_ROOT = Path("/var/lib/eom-api/mock-exam-production")
_EXECUTION_ID = re.compile(r"^productionexec_[0-9a-f]{32}$")
_MAX_CHECKPOINT_BYTES = 2 * 1024 * 1024
_SAFE_DIRECTORY_MODES = frozenset({0o700, 0o750})
_SAFE_FILE_MODES = frozenset({0o600, 0o640})

CheckpointValidator = Callable[[bytes], tuple[str, bool]]


class DeploymentAdmissionError(RuntimeError):
    """Stable deployment refusal without checkpoint content or filesystem disclosure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class DeploymentAdmissionResult:
    terminal_execution_count: int


def inspect_checkpoint_root(
    root: Path,
    *,
    validator: CheckpointValidator,
    expected_owner_uid: int,
    expected_owner_gid: int,
) -> DeploymentAdmissionResult:
    """Validate every current checkpoint and reject any resumable execution."""

    try:
        root_metadata = root.stat(follow_symlinks=False)
    except FileNotFoundError:
        return DeploymentAdmissionResult(terminal_execution_count=0)
    except OSError as exc:
        raise DeploymentAdmissionError("CHECKPOINT_ROOT_UNREADABLE") from exc
    if (
        stat.S_ISLNK(root_metadata.st_mode)
        or not stat.S_ISDIR(root_metadata.st_mode)
        or root_metadata.st_uid != expected_owner_uid
        or root_metadata.st_gid != expected_owner_gid
        or stat.S_IMODE(root_metadata.st_mode) not in _SAFE_DIRECTORY_MODES
    ):
        raise DeploymentAdmissionError("CHECKPOINT_ROOT_INVALID")

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        root_descriptor = os.open(root, flags)
    except OSError as exc:
        raise DeploymentAdmissionError("CHECKPOINT_ROOT_UNREADABLE") from exc
    terminal_count = 0
    try:
        if _directory_identity(os.fstat(root_descriptor)) != _directory_identity(root_metadata):
            raise DeploymentAdmissionError("CHECKPOINT_ROOT_CHANGED")
        for name in sorted(os.listdir(root_descriptor)):
            if not _EXECUTION_ID.fullmatch(name):
                continue
            terminal_count += _inspect_execution(
                root_descriptor,
                name,
                validator=validator,
                expected_owner_uid=expected_owner_uid,
                expected_owner_gid=expected_owner_gid,
            )
    finally:
        os.close(root_descriptor)
    return DeploymentAdmissionResult(terminal_execution_count=terminal_count)


def _inspect_execution(
    root_descriptor: int,
    execution_id: str,
    *,
    validator: CheckpointValidator,
    expected_owner_uid: int,
    expected_owner_gid: int,
) -> int:
    try:
        metadata = os.stat(execution_id, dir_fd=root_descriptor, follow_symlinks=False)
    except OSError as exc:
        raise DeploymentAdmissionError("EXECUTION_DIRECTORY_UNREADABLE") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != expected_owner_uid
        or metadata.st_gid != expected_owner_gid
        or stat.S_IMODE(metadata.st_mode) not in _SAFE_DIRECTORY_MODES
    ):
        raise DeploymentAdmissionError("EXECUTION_DIRECTORY_INVALID")

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        directory = os.open(execution_id, flags, dir_fd=root_descriptor)
    except OSError as exc:
        raise DeploymentAdmissionError("EXECUTION_DIRECTORY_UNREADABLE") from exc
    try:
        if _directory_identity(os.fstat(directory)) != _directory_identity(metadata):
            raise DeploymentAdmissionError("EXECUTION_DIRECTORY_CHANGED")
        payload = _read_current_checkpoint(
            directory,
            expected_owner_uid=expected_owner_uid,
            expected_owner_gid=expected_owner_gid,
        )
    finally:
        os.close(directory)
    try:
        actual_execution_id, terminal = validator(payload)
    except Exception as exc:
        raise DeploymentAdmissionError("CHECKPOINT_CONTRACT_INVALID") from exc
    if actual_execution_id != execution_id:
        raise DeploymentAdmissionError("CHECKPOINT_EXECUTION_ID_MISMATCH")
    if not terminal:
        raise DeploymentAdmissionError("NONTERMINAL_EXECUTION_PRESENT")
    return 1


def _read_current_checkpoint(
    directory: int,
    *,
    expected_owner_uid: int,
    expected_owner_gid: int,
) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open("current.json", flags, dir_fd=directory)
    except OSError as exc:
        raise DeploymentAdmissionError("CURRENT_CHECKPOINT_UNREADABLE") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != expected_owner_uid
            or metadata.st_gid != expected_owner_gid
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) not in _SAFE_FILE_MODES
            or metadata.st_size <= 0
            or metadata.st_size > _MAX_CHECKPOINT_BYTES
        ):
            raise DeploymentAdmissionError("CURRENT_CHECKPOINT_INVALID")
        chunks = bytearray()
        saw_eof = False
        while len(chunks) <= _MAX_CHECKPOINT_BYTES:
            chunk = os.read(
                descriptor,
                min(64 * 1024, _MAX_CHECKPOINT_BYTES + 1 - len(chunks)),
            )
            if not chunk:
                saw_eof = True
                break
            chunks.extend(chunk)
        after = os.fstat(descriptor)
        if (
            not saw_eof
            or len(chunks) != metadata.st_size
            or _file_identity(metadata) != _file_identity(after)
        ):
            raise DeploymentAdmissionError("CURRENT_CHECKPOINT_CHANGED")
        return bytes(chunks)
    finally:
        os.close(descriptor)


def _installed_contract_validator(payload: bytes) -> tuple[str, bool]:
    # Isolated Python resolves this import only from the installed wheel. If an older
    # installation lacks the contract, a non-empty checkpoint root fails closed.
    from eom_api_contracts.mock_exam_execution import (
        MockExamProductionExecution,
        mock_exam_production_is_terminal,
    )
    from pydantic import TypeAdapter

    checkpoint: MockExamProductionExecution = TypeAdapter(
        MockExamProductionExecution
    ).validate_json(payload)
    return checkpoint.execution_id, mock_exam_production_is_terminal(checkpoint)


def _directory_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
    )


def _file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        *_directory_identity(metadata),
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def main() -> int:
    try:
        result = inspect_checkpoint_root(
            CHECKPOINT_ROOT,
            validator=_installed_contract_validator,
            expected_owner_uid=os.geteuid(),
            expected_owner_gid=os.getegid(),
        )
    except DeploymentAdmissionError as exc:
        print(f"ERROR: mock-exam deployment admission denied: {exc.code}", file=sys.stderr)
        return 1
    print(
        "mock_exam_deployment_admission=READY "
        f"terminal_execution_count={result.terminal_execution_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
