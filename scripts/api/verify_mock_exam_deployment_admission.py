#!/srv/eom/conda/envs/eom-api/bin/python
"""Fail closed when a release would replace an active mock-exam production plan.

The deploy wrapper installs this file as a root-owned executable, then runs it as the
unprivileged ``eom-api`` account.  Checkpoint payloads are validated with the currently
installed API contract; repository Python is never imported by the admission check.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

CHECKPOINT_ROOT = Path("/var/lib/eom-api/mock-exam-production")
_EXECUTION_ID = re.compile(r"^productionexec_[0-9a-f]{32}$")
_EXECUTION_REVISION_ID = re.compile(r"^productionexecrev_[0-9a-f]{32}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_FAILURE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_MAX_CHECKPOINT_BYTES = 2 * 1024 * 1024
_SAFE_DIRECTORY_MODES = frozenset({0o700, 0o750})
_SAFE_FILE_MODES = frozenset({0o600, 0o640})

CheckpointValidator = Callable[[bytes], tuple[str, bool]]
RecoveryCheckpointValidator = Callable[[bytes], "RecoveryCheckpointObservation"]


class DeploymentAdmissionError(RuntimeError):
    """Stable deployment refusal without checkpoint content or filesystem disclosure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class DeploymentAdmissionResult:
    terminal_execution_count: int
    recovery_execution_id: str | None = None


@dataclass(frozen=True)
class ExactRetryableBlockedAdmission:
    """Operator-authorized identity for one exact resumable checkpoint."""

    execution_id: str
    execution_revision_id: str
    checkpoint_sha256: str
    failure_code: str

    def __post_init__(self) -> None:
        if (
            _EXECUTION_ID.fullmatch(self.execution_id) is None
            or _EXECUTION_REVISION_ID.fullmatch(self.execution_revision_id) is None
            or _SHA256.fullmatch(self.checkpoint_sha256) is None
            or _FAILURE_CODE.fullmatch(self.failure_code) is None
        ):
            raise DeploymentAdmissionError("RECOVERY_ARGUMENT_INVALID")


@dataclass(frozen=True)
class RecoveryCheckpointObservation:
    execution_id: str
    execution_revision_id: str
    state: str
    retryable: bool | None
    failure_code: str | None


def inspect_checkpoint_root(
    root: Path,
    *,
    validator: CheckpointValidator,
    expected_owner_uid: int,
    expected_owner_gid: int,
    recovery_admission: ExactRetryableBlockedAdmission | None = None,
    recovery_validator: RecoveryCheckpointValidator | None = None,
) -> DeploymentAdmissionResult:
    """Validate every current checkpoint and reject any resumable execution."""

    try:
        root_metadata = root.stat(follow_symlinks=False)
    except FileNotFoundError:
        if recovery_admission is not None:
            raise DeploymentAdmissionError("RECOVERY_EXECUTION_NOT_FOUND") from None
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
    recovery_execution_id: str | None = None
    try:
        if _directory_identity(os.fstat(root_descriptor)) != _directory_identity(root_metadata):
            raise DeploymentAdmissionError("CHECKPOINT_ROOT_CHANGED")
        for name in sorted(os.listdir(root_descriptor)):
            if not _EXECUTION_ID.fullmatch(name):
                continue
            terminal, recovery_match = _inspect_execution(
                root_descriptor,
                name,
                validator=validator,
                expected_owner_uid=expected_owner_uid,
                expected_owner_gid=expected_owner_gid,
                recovery_admission=recovery_admission,
                recovery_validator=recovery_validator,
            )
            terminal_count += terminal
            if recovery_match:
                if recovery_execution_id is not None:
                    raise DeploymentAdmissionError("RECOVERY_EXECUTION_DUPLICATE")
                recovery_execution_id = name
    finally:
        os.close(root_descriptor)
    if recovery_admission is not None and recovery_execution_id is None:
        raise DeploymentAdmissionError("RECOVERY_EXECUTION_NOT_FOUND")
    return DeploymentAdmissionResult(
        terminal_execution_count=terminal_count,
        recovery_execution_id=recovery_execution_id,
    )


def _inspect_execution(
    root_descriptor: int,
    execution_id: str,
    *,
    validator: CheckpointValidator,
    expected_owner_uid: int,
    expected_owner_gid: int,
    recovery_admission: ExactRetryableBlockedAdmission | None,
    recovery_validator: RecoveryCheckpointValidator | None,
) -> tuple[int, bool]:
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
    if terminal:
        return 1, False
    if recovery_admission is None or execution_id != recovery_admission.execution_id:
        raise DeploymentAdmissionError("NONTERMINAL_EXECUTION_PRESENT")
    if recovery_validator is None:
        raise DeploymentAdmissionError("RECOVERY_VALIDATOR_MISSING")
    payload_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
    if payload_sha256 != recovery_admission.checkpoint_sha256:
        raise DeploymentAdmissionError("RECOVERY_CHECKPOINT_MISMATCH")
    try:
        observation = recovery_validator(payload)
    except Exception as exc:
        raise DeploymentAdmissionError("RECOVERY_CHECKPOINT_INVALID") from exc
    if (
        observation.execution_id != recovery_admission.execution_id
        or observation.execution_revision_id != recovery_admission.execution_revision_id
        or observation.state != "BLOCKED"
        or observation.retryable is not True
        or observation.failure_code != recovery_admission.failure_code
    ):
        raise DeploymentAdmissionError("RECOVERY_CHECKPOINT_MISMATCH")
    return 0, True


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


def _installed_recovery_validator(payload: bytes) -> RecoveryCheckpointObservation:
    from eom_api_contracts.mock_exam_execution import MockExamProductionExecution
    from pydantic import TypeAdapter

    checkpoint: MockExamProductionExecution = TypeAdapter(
        MockExamProductionExecution
    ).validate_json(payload)
    failure = checkpoint.failure
    return RecoveryCheckpointObservation(
        execution_id=checkpoint.execution_id,
        execution_revision_id=checkpoint.execution_revision_id,
        state=checkpoint.state,
        retryable=failure.retryable if failure is not None else None,
        failure_code=failure.code if failure is not None else None,
    )


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
        recovery_admission: ExactRetryableBlockedAdmission | None = None
        arguments = sys.argv[1:]
        if arguments:
            if len(arguments) != 5 or arguments[0] != "--admit-exact-retryable-blocked":
                raise DeploymentAdmissionError("RECOVERY_ARGUMENT_INVALID")
            recovery_admission = ExactRetryableBlockedAdmission(
                execution_id=arguments[1],
                execution_revision_id=arguments[2],
                checkpoint_sha256=arguments[3],
                failure_code=arguments[4],
            )
        result = inspect_checkpoint_root(
            CHECKPOINT_ROOT,
            validator=_installed_contract_validator,
            expected_owner_uid=os.geteuid(),
            expected_owner_gid=os.getegid(),
            recovery_admission=recovery_admission,
            recovery_validator=(
                _installed_recovery_validator if recovery_admission is not None else None
            ),
        )
    except DeploymentAdmissionError as exc:
        print(f"ERROR: mock-exam deployment admission denied: {exc.code}", file=sys.stderr)
        return 1
    print(
        "mock_exam_deployment_admission=READY "
        f"terminal_execution_count={result.terminal_execution_count}"
        + (
            f" recovery_execution_id={result.recovery_execution_id}"
            if result.recovery_execution_id is not None
            else ""
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
