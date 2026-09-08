"""Atomic local persistence for pointer-only mock-exam production checkpoints.

The immutable revision files are canonical. ``current.json`` is a validated materialized cache
updated with compare-and-swap semantics. This adapter stores no Item content or binary artifact.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Protocol

from eom_api_contracts.mock_exam_execution import MockExamProductionExecutionV1
from pydantic import ValidationError

_EXECUTION_ID = re.compile(r"^productionexec_[0-9a-f]{32}$")
_REVISION_ID = re.compile(r"^productionexecrev_[0-9a-f]{32}$")
_MAX_CHECKPOINT_BYTES = 2 * 1024 * 1024
_SAFE_DIRECTORY_MODES = frozenset({0o700, 0o750})
_SAFE_FILE_MODES = frozenset({0o600, 0o640})

_ITEM_STATE_TRANSITIONS: dict[str, frozenset[str]] = {
    # One reconciliation call may observe several already-committed service transitions.
    "PLANNED": frozenset(
        {
            "PLANNED",
            "START_UNCONFIRMED",
            "WORKFLOW_UNCONFIRMED",
            "WORKFLOW_ACTIVE",
            "REVIEW_BLOCKED",
            "APPROVAL_UNCONFIRMED",
            "APPROVAL_SUBMITTED",
            "REGISTERED",
            "FAILED",
        }
    ),
    "START_UNCONFIRMED": frozenset(
        {
            "START_UNCONFIRMED",
            "WORKFLOW_UNCONFIRMED",
            "WORKFLOW_ACTIVE",
            "REVIEW_BLOCKED",
            "APPROVAL_UNCONFIRMED",
            "APPROVAL_SUBMITTED",
            "REGISTERED",
            "FAILED",
        }
    ),
    "WORKFLOW_UNCONFIRMED": frozenset(
        {
            "WORKFLOW_UNCONFIRMED",
            "WORKFLOW_ACTIVE",
            "REVIEW_BLOCKED",
            "APPROVAL_UNCONFIRMED",
            "APPROVAL_SUBMITTED",
            "REGISTERED",
            "FAILED",
        }
    ),
    "WORKFLOW_ACTIVE": frozenset(
        {
            "WORKFLOW_ACTIVE",
            "WORKFLOW_UNCONFIRMED",
            "REVIEW_BLOCKED",
            "APPROVAL_UNCONFIRMED",
            "APPROVAL_SUBMITTED",
            "REGISTERED",
            "FAILED",
        }
    ),
    "REVIEW_BLOCKED": frozenset(
        {
            "REVIEW_BLOCKED",
            "APPROVAL_UNCONFIRMED",
            "APPROVAL_SUBMITTED",
            "WORKFLOW_ACTIVE",
            "REGISTERED",
            "FAILED",
        }
    ),
    "APPROVAL_UNCONFIRMED": frozenset(
        {
            "APPROVAL_UNCONFIRMED",
            "APPROVAL_SUBMITTED",
            "WORKFLOW_ACTIVE",
            "REGISTERED",
            "FAILED",
        }
    ),
    "APPROVAL_SUBMITTED": frozenset(
        {
            "APPROVAL_SUBMITTED",
            "APPROVAL_UNCONFIRMED",
            "WORKFLOW_ACTIVE",
            "REGISTERED",
            "FAILED",
        }
    ),
    "REGISTERED": frozenset(
        {
            "REGISTERED",
            "ANALYSIS_UNCONFIRMED",
            "ANALYSIS_ACTIVE",
            "ANALYSIS_REVIEW_REQUIRED",
            "ANALYSIS_ACCEPTED",
            "FAILED",
        }
    ),
    "ANALYSIS_UNCONFIRMED": frozenset(
        {
            "ANALYSIS_UNCONFIRMED",
            "ANALYSIS_ACTIVE",
            "ANALYSIS_REVIEW_REQUIRED",
            "ANALYSIS_ACCEPTED",
            "FAILED",
        }
    ),
    "ANALYSIS_ACTIVE": frozenset(
        {
            "ANALYSIS_ACTIVE",
            "ANALYSIS_UNCONFIRMED",
            "ANALYSIS_REVIEW_REQUIRED",
            "ANALYSIS_ACCEPTED",
            "FAILED",
        }
    ),
    "ANALYSIS_REVIEW_REQUIRED": frozenset(
        {"ANALYSIS_REVIEW_REQUIRED", "ANALYSIS_UNCONFIRMED", "ANALYSIS_ACCEPTED", "FAILED"}
    ),
    "ANALYSIS_ACCEPTED": frozenset({"ANALYSIS_ACCEPTED", "GRAPH_PUBLISHED", "FAILED"}),
    "GRAPH_PUBLISHED": frozenset({"GRAPH_PUBLISHED", "RATING_UNCONFIRMED", "RATED", "FAILED"}),
    "RATING_UNCONFIRMED": frozenset({"RATING_UNCONFIRMED", "RATED", "FAILED"}),
    "RATED": frozenset({"RATED", "FAILED"}),
    "FAILED": frozenset({"FAILED"}),
}

_ANALYSIS_STATE_TRANSITIONS: dict[str, frozenset[str]] = {
    "REQUESTED": frozenset(
        {
            "REQUESTED",
            "RESOLVED",
            "QUEUED",
            "RUNNING",
            "VALIDATING",
            "NEEDS_REVIEW",
            "ACCEPTED",
            "REJECTED",
            "FAILED",
            "CANCELLED",
        }
    ),
    "RESOLVED": frozenset(
        {
            "RESOLVED",
            "QUEUED",
            "RUNNING",
            "VALIDATING",
            "NEEDS_REVIEW",
            "ACCEPTED",
            "REJECTED",
            "FAILED",
            "CANCELLED",
        }
    ),
    "QUEUED": frozenset(
        {
            "QUEUED",
            "RUNNING",
            "VALIDATING",
            "NEEDS_REVIEW",
            "ACCEPTED",
            "REJECTED",
            "FAILED",
            "CANCELLED",
        }
    ),
    "RUNNING": frozenset(
        {
            "RUNNING",
            "VALIDATING",
            "NEEDS_REVIEW",
            "ACCEPTED",
            "REJECTED",
            "FAILED",
            "CANCELLED",
        }
    ),
    "VALIDATING": frozenset(
        {"VALIDATING", "NEEDS_REVIEW", "ACCEPTED", "REJECTED", "FAILED", "CANCELLED"}
    ),
    "NEEDS_REVIEW": frozenset({"NEEDS_REVIEW", "ACCEPTED", "REJECTED", "FAILED", "CANCELLED"}),
    "ACCEPTED": frozenset({"ACCEPTED"}),
    "REJECTED": frozenset({"REJECTED"}),
    "FAILED": frozenset({"FAILED"}),
    "CANCELLED": frozenset({"CANCELLED"}),
}

_HWPX_STATE_TRANSITIONS: dict[str, frozenset[str]] = {
    "REQUESTED": frozenset({"REQUESTED", "RUNNING", "VALIDATING", "SUCCEEDED", "FAILED"}),
    "RUNNING": frozenset({"RUNNING", "VALIDATING", "SUCCEEDED", "FAILED"}),
    "VALIDATING": frozenset({"VALIDATING", "SUCCEEDED", "FAILED"}),
    "SUCCEEDED": frozenset({"SUCCEEDED"}),
    "FAILED": frozenset({"FAILED"}),
}


class MockExamCheckpointStoreError(RuntimeError):
    """Stable persistence error without checkpoint payload or filesystem disclosure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class MockExamProductionCheckpointStore(Protocol):
    def create(
        self, checkpoint: MockExamProductionExecutionV1
    ) -> MockExamProductionExecutionV1: ...

    def load(self, execution_id: str) -> MockExamProductionExecutionV1: ...

    def compare_and_swap(
        self,
        expected_execution_revision_id: str,
        checkpoint: MockExamProductionExecutionV1,
    ) -> MockExamProductionExecutionV1: ...


class AtomicJsonMockExamProductionCheckpointStore:
    """Append immutable JSON revisions and atomically replace one validated current cache."""

    def __init__(self, root: Path) -> None:
        if not root.is_absolute():
            raise MockExamCheckpointStoreError(
                "CHECKPOINT_ROOT_NOT_ABSOLUTE",
                "checkpoint root must be an absolute runtime path",
            )
        if root.is_symlink():
            raise MockExamCheckpointStoreError(
                "CHECKPOINT_ROOT_SYMLINK_FORBIDDEN",
                "checkpoint root cannot be a symbolic link",
            )
        resolved = root.resolve(strict=False)
        if any(_is_git_worktree_root(candidate) for candidate in (resolved, *resolved.parents)):
            raise MockExamCheckpointStoreError(
                "CHECKPOINT_ROOT_INSIDE_GIT",
                "checkpoint root must remain outside a Git worktree",
            )
        resolved.mkdir(mode=0o750, parents=True, exist_ok=True)
        self._root = resolved
        descriptor = _open_validated_directory(resolved, "CHECKPOINT_ROOT_INVALID")
        try:
            self._root_identity = _directory_identity(os.fstat(descriptor))
        finally:
            os.close(descriptor)

    def create(self, checkpoint: MockExamProductionExecutionV1) -> MockExamProductionExecutionV1:
        if checkpoint.checkpoint_sequence != 0:
            raise MockExamCheckpointStoreError(
                "CHECKPOINT_INITIAL_SEQUENCE_INVALID",
                "new execution must begin at checkpoint sequence zero",
            )
        with self._lock(checkpoint.execution_id, exclusive=True):
            directory = self._open_execution_directory(checkpoint.execution_id, create=True)
            os.close(directory)
            if self._entry_exists(checkpoint.execution_id, "current.json"):
                current = self._load_unlocked(checkpoint.execution_id)
                if current.checkpoint_sha256 == checkpoint.checkpoint_sha256:
                    return current
                raise MockExamCheckpointStoreError(
                    "CHECKPOINT_EXECUTION_ALREADY_EXISTS",
                    "another initial checkpoint already owns this execution",
                )
            payload = _checkpoint_bytes(checkpoint)
            self._append_revision(checkpoint, payload)
            self._replace_current(checkpoint.execution_id, payload)
            return checkpoint

    def load(self, execution_id: str) -> MockExamProductionExecutionV1:
        _require_execution_id(execution_id)
        with self._lock(execution_id, exclusive=False):
            return self._load_unlocked(execution_id)

    def compare_and_swap(
        self,
        expected_execution_revision_id: str,
        checkpoint: MockExamProductionExecutionV1,
    ) -> MockExamProductionExecutionV1:
        _require_revision_id(expected_execution_revision_id)
        if checkpoint.predecessor_execution_revision_id != expected_execution_revision_id:
            raise MockExamCheckpointStoreError(
                "CHECKPOINT_PREDECESSOR_MISMATCH",
                "successor does not pin the expected immutable checkpoint",
            )
        with self._lock(checkpoint.execution_id, exclusive=True):
            current = self._load_unlocked(checkpoint.execution_id)
            if current.execution_revision_id == checkpoint.execution_revision_id:
                return current
            if current.execution_revision_id != expected_execution_revision_id:
                raise MockExamCheckpointStoreError(
                    "CHECKPOINT_CONCURRENT_ADVANCE",
                    "execution advanced from a different checkpoint revision",
                )
            if (
                checkpoint.predecessor_checkpoint_sha256 != current.checkpoint_sha256
                or checkpoint.checkpoint_sequence != current.checkpoint_sequence + 1
                or checkpoint.execution_id != current.execution_id
                or checkpoint.production_request_id != current.production_request_id
                or checkpoint.production_plan_id != current.production_plan_id
                or checkpoint.production_plan_sha256 != current.production_plan_sha256
                or checkpoint.operator_id != current.operator_id
                or checkpoint.created_at != current.created_at
                or checkpoint.checkpointed_at < current.checkpointed_at
                or not _monotonic_successor(current, checkpoint)
            ):
                raise MockExamCheckpointStoreError(
                    "CHECKPOINT_SUCCESSOR_INVALID",
                    "successor changed an immutable execution identity or revision link",
                )
            payload = _checkpoint_bytes(checkpoint)
            self._append_revision(checkpoint, payload)
            self._replace_current(checkpoint.execution_id, payload)
            return checkpoint

    def _load_unlocked(self, execution_id: str) -> MockExamProductionExecutionV1:
        payload = self._read_bounded(execution_id, "current.json")
        checkpoint = _parse_checkpoint(payload)
        if checkpoint.execution_id != execution_id:
            raise MockExamCheckpointStoreError(
                "CHECKPOINT_EXECUTION_POINTER_MISMATCH",
                "current checkpoint belongs to another execution",
            )
        revision_payload = self._read_bounded(
            execution_id,
            f"{checkpoint.execution_revision_id}.json",
        )
        if revision_payload != payload:
            raise MockExamCheckpointStoreError(
                "CHECKPOINT_CURRENT_CACHE_MISMATCH",
                "current checkpoint differs from its immutable revision",
            )
        return checkpoint

    def _append_revision(
        self,
        checkpoint: MockExamProductionExecutionV1,
        payload: bytes,
    ) -> None:
        directory = self._open_execution_directory(checkpoint.execution_id, create=True)
        name = f"{checkpoint.execution_revision_id}.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(name, flags, 0o640, dir_fd=directory)
        except FileExistsError:
            os.close(directory)
            if self._read_bounded(checkpoint.execution_id, name) != payload:
                raise MockExamCheckpointStoreError(
                    "CHECKPOINT_IMMUTABLE_REVISION_CONFLICT",
                    "checkpoint revision already exists with different bytes",
                ) from None
            return
        except OSError as exc:
            os.close(directory)
            raise MockExamCheckpointStoreError(
                "CHECKPOINT_FILE_INVALID",
                "checkpoint revision is not a safe regular file",
            ) from exc
        try:
            opened = os.fstat(descriptor)
            _require_safe_file(opened)
            _write_all(descriptor, payload)
            os.fsync(descriptor)
            written = os.fstat(descriptor)
            if _static_file_identity(opened) != _static_file_identity(
                written
            ) or written.st_size != len(payload):
                raise MockExamCheckpointStoreError(
                    "CHECKPOINT_FILE_CHANGED",
                    "checkpoint revision changed while it was written",
                )
        finally:
            os.close(descriptor)
            os.fsync(directory)
            os.close(directory)

    def _replace_current(self, execution_id: str, payload: bytes) -> None:
        directory = self._open_execution_directory(execution_id, create=False)
        temporary = f".current.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(temporary, flags, 0o640, dir_fd=directory)
        except OSError as exc:
            os.close(directory)
            raise MockExamCheckpointStoreError(
                "CHECKPOINT_FILE_INVALID",
                "current checkpoint target is not a safe regular file",
            ) from exc
        try:
            opened = os.fstat(descriptor)
            _require_safe_file(opened)
            _write_all(descriptor, payload)
            os.fsync(descriptor)
            written = os.fstat(descriptor)
            if _static_file_identity(opened) != _static_file_identity(
                written
            ) or written.st_size != len(payload):
                raise MockExamCheckpointStoreError(
                    "CHECKPOINT_FILE_CHANGED",
                    "current checkpoint changed while it was written",
                )
        finally:
            os.close(descriptor)
        try:
            os.replace(
                temporary,
                "current.json",
                src_dir_fd=directory,
                dst_dir_fd=directory,
            )
            os.fsync(directory)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=directory)
            os.close(directory)

    @contextmanager
    def _lock(self, execution_id: str, *, exclusive: bool) -> Iterator[None]:
        _require_execution_id(execution_id)
        root = self._open_root()
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(f".{execution_id}.lock", flags, 0o640, dir_fd=root)
        except OSError as exc:
            os.close(root)
            raise MockExamCheckpointStoreError(
                "CHECKPOINT_LOCK_INVALID",
                "checkpoint lock is not a safe regular file",
            ) from exc
        try:
            _require_safe_file(os.fstat(descriptor))
            fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            os.close(root)

    def _open_root(self) -> int:
        descriptor = _open_validated_directory(self._root, "CHECKPOINT_ROOT_INVALID")
        if _directory_identity(os.fstat(descriptor)) != self._root_identity:
            os.close(descriptor)
            raise MockExamCheckpointStoreError(
                "CHECKPOINT_ROOT_CHANGED",
                "checkpoint root identity changed after store initialization",
            )
        return descriptor

    def _open_execution_directory(self, execution_id: str, *, create: bool) -> int:
        _require_execution_id(execution_id)
        root = self._open_root()
        try:
            if create:
                with suppress(FileExistsError):
                    os.mkdir(execution_id, 0o750, dir_fd=root)
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            try:
                descriptor = os.open(execution_id, flags, dir_fd=root)
            except FileNotFoundError as exc:
                raise MockExamCheckpointStoreError(
                    "CHECKPOINT_NOT_FOUND",
                    "checkpoint execution directory does not exist",
                ) from exc
            except OSError as exc:
                raise MockExamCheckpointStoreError(
                    "CHECKPOINT_DIRECTORY_INVALID",
                    "checkpoint execution directory is not safe",
                ) from exc
            try:
                _require_safe_directory(os.fstat(descriptor))
            except Exception:
                os.close(descriptor)
                raise
            return descriptor
        finally:
            os.close(root)

    def _entry_exists(self, execution_id: str, name: str) -> bool:
        directory = self._open_execution_directory(execution_id, create=False)
        try:
            try:
                os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                return False
            return True
        finally:
            os.close(directory)

    def _read_bounded(self, execution_id: str, name: str) -> bytes:
        if Path(name).name != name:
            raise MockExamCheckpointStoreError(
                "CHECKPOINT_FILE_INVALID", "checkpoint filename is invalid"
            )
        directory = self._open_execution_directory(execution_id, create=False)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            try:
                descriptor = os.open(name, flags, dir_fd=directory)
            except FileNotFoundError as exc:
                raise MockExamCheckpointStoreError(
                    "CHECKPOINT_NOT_FOUND", "checkpoint pointer does not exist"
                ) from exc
            except OSError as exc:
                raise MockExamCheckpointStoreError(
                    "CHECKPOINT_FILE_INVALID",
                    "checkpoint pointer is not a safe regular file",
                ) from exc
            try:
                before = os.fstat(descriptor)
                _require_safe_file(before)
                if not 0 < before.st_size <= _MAX_CHECKPOINT_BYTES:
                    raise MockExamCheckpointStoreError(
                        "CHECKPOINT_SIZE_INVALID",
                        "checkpoint pointer has an invalid byte length",
                    )
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
                    or len(chunks) != before.st_size
                    or _file_identity(before) != _file_identity(after)
                ):
                    raise MockExamCheckpointStoreError(
                        "CHECKPOINT_FILE_CHANGED",
                        "checkpoint pointer changed while it was read",
                    )
                return bytes(chunks)
            finally:
                os.close(descriptor)
        finally:
            os.close(directory)


def _checkpoint_bytes(checkpoint: MockExamProductionExecutionV1) -> bytes:
    payload = checkpoint.model_dump_json(indent=2).encode("utf-8") + b"\n"
    if len(payload) > _MAX_CHECKPOINT_BYTES:
        raise MockExamCheckpointStoreError(
            "CHECKPOINT_TOO_LARGE",
            "pointer checkpoint exceeds the fixed storage bound",
        )
    return payload


def _open_validated_directory(path: Path, code: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise MockExamCheckpointStoreError(code, "checkpoint directory is not safe") from exc
    try:
        _require_safe_directory(os.fstat(descriptor))
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _require_safe_directory(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_gid != os.getegid()
        or stat.S_IMODE(metadata.st_mode) not in _SAFE_DIRECTORY_MODES
    ):
        raise MockExamCheckpointStoreError(
            "CHECKPOINT_DIRECTORY_INVALID",
            "checkpoint directory owner or mode is unsafe",
        )


def _require_safe_file(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_gid != os.getegid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) not in _SAFE_FILE_MODES
    ):
        raise MockExamCheckpointStoreError(
            "CHECKPOINT_FILE_INVALID",
            "checkpoint file owner, mode, type, or link count is unsafe",
        )


def _directory_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
    )


def _static_file_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
    )


def _file_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int, int, int, int, int]:
    return (
        *_static_file_identity(metadata),
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _parse_checkpoint(payload: bytes) -> MockExamProductionExecutionV1:
    try:
        value = json.loads(payload.decode("utf-8"))
        return MockExamProductionExecutionV1.model_validate(value)
    except (UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise MockExamCheckpointStoreError(
            "CHECKPOINT_CONTRACT_INVALID",
            "checkpoint failed schema or immutable-hash validation",
        ) from exc


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        offset += os.write(descriptor, payload[offset:])


def _require_execution_id(value: str) -> None:
    if _EXECUTION_ID.fullmatch(value) is None:
        raise MockExamCheckpointStoreError(
            "CHECKPOINT_EXECUTION_ID_INVALID", "execution identity is invalid"
        )


def _require_revision_id(value: str) -> None:
    if _REVISION_ID.fullmatch(value) is None:
        raise MockExamCheckpointStoreError(
            "CHECKPOINT_REVISION_ID_INVALID", "checkpoint revision identity is invalid"
        )


def _is_git_worktree_root(path: Path) -> bool:
    marker = path / ".git"
    return marker.is_file() or (marker.is_dir() and (marker / "HEAD").is_file())


def _monotonic_successor(
    current: MockExamProductionExecutionV1,
    successor: MockExamProductionExecutionV1,
) -> bool:
    for field in (
        "generation_block_resolution",
        "analysis_policy",
        "analysis_general_knowledge_mode",
        "rating_authorization",
        "assembly_intent",
        "assembly_plan",
        "assembly",
    ):
        before = getattr(current, field)
        if before is not None and getattr(successor, field) != before:
            return False
    before_graph_authorization = current.graph_publication_authorization
    after_graph_authorization = successor.graph_publication_authorization
    if before_graph_authorization != after_graph_authorization:
        if after_graph_authorization is None:
            return False
        if (
            successor.graph_publications != current.graph_publications
            or successor.item_runs != current.item_runs
        ):
            # Authorization and publication evidence must never enter the same CAS revision.
            return False
        if before_graph_authorization is None:
            if (
                after_graph_authorization.supersedes_authorization_sha256 is not None
                or successor.failure != current.failure
            ):
                return False
        elif (
            current.graph_publications
            or current.failure is None
            or current.failure.stage != "GRAPH_PUBLICATION"
            or current.failure.code != "KNOWLEDGE_GRAPH_STALE_CURRENT"
            or after_graph_authorization.supersedes_authorization_sha256
            != before_graph_authorization.authorization_sha256
            or after_graph_authorization.access_policy_revision_id
            != before_graph_authorization.access_policy_revision_id
            or after_graph_authorization.access_policy_sha256
            != before_graph_authorization.access_policy_sha256
            or successor.failure is not None
        ):
            return False
    if (
        len(successor.analysis_review_authorizations)
        not in {
            len(current.analysis_review_authorizations),
            len(current.analysis_review_authorizations) + 1,
        }
        or successor.analysis_review_authorizations[: len(current.analysis_review_authorizations)]
        != current.analysis_review_authorizations
        or (
            current.analysis_review_authorizations
            and len(successor.analysis_review_authorizations)
            > len(current.analysis_review_authorizations)
            and successor.analysis_review_authorizations[-1].authorized_at
            < current.analysis_review_authorizations[-1].authorized_at
        )
    ):
        return False
    if successor.graph_publications[: len(current.graph_publications)] != (
        current.graph_publications
    ):
        return False
    if current.hwpx_build is not None:
        after_hwpx = successor.hwpx_build
        if (
            after_hwpx is None
            or after_hwpx.build_id != current.hwpx_build.build_id
            or after_hwpx.assessment_assembly_id != current.hwpx_build.assessment_assembly_id
            or after_hwpx.assessment_assembly_revision_id
            != current.hwpx_build.assessment_assembly_revision_id
            or after_hwpx.assembly_manifest_sha256 != current.hwpx_build.assembly_manifest_sha256
            or after_hwpx.policy_revision_id != current.hwpx_build.policy_revision_id
            or after_hwpx.policy_sha256 != current.hwpx_build.policy_sha256
            or after_hwpx.graph_snapshot_revision_id
            != current.hwpx_build.graph_snapshot_revision_id
            or after_hwpx.graph_snapshot_sha256 != current.hwpx_build.graph_snapshot_sha256
            or after_hwpx.item_set_sha256 != current.hwpx_build.item_set_sha256
            or after_hwpx.item_revision_ids != current.hwpx_build.item_revision_ids
            or after_hwpx.renderer != current.hwpx_build.renderer
            or after_hwpx.renderer_version != current.hwpx_build.renderer_version
            or after_hwpx.created_by_operator_id != current.hwpx_build.created_by_operator_id
            or after_hwpx.created_at != current.hwpx_build.created_at
            or after_hwpx.resource_version < current.hwpx_build.resource_version
            or after_hwpx.state not in _HWPX_STATE_TRANSITIONS[current.hwpx_build.state]
            or (
                after_hwpx != current.hwpx_build
                and after_hwpx.resource_version <= current.hwpx_build.resource_version
            )
        ):
            return False
        for field in (
            "output_artifact_id",
            "output_artifact_revision_id",
            "output_sha256",
            "completed_at",
        ):
            before_value = getattr(current.hwpx_build, field)
            if before_value is not None and getattr(after_hwpx, field) != before_value:
                return False
    for before, after in zip(current.item_runs, successor.item_runs, strict=True):
        if (before.workflow_call_id, before.position) != (
            after.workflow_call_id,
            after.position,
        ):
            return False
        if after.state not in _ITEM_STATE_TRANSITIONS[before.state]:
            return False
        for field in (
            "start_command_id",
            "workflow_id",
            "knowledge_provenance",
            "approval_command_id",
            "human_approval",
            "registration",
            "graph_publication_id",
            "rating",
        ):
            value = getattr(before, field)
            if value is not None and getattr(after, field) != value:
                return False
        if before.workflow_resource_version is not None and (
            after.workflow_resource_version is None
            or after.workflow_resource_version < before.workflow_resource_version
        ):
            return False
        if before.review is not None:
            if after.review is None:
                return False
            before_review = before.review.model_dump(exclude={"approval_resource_version"})
            after_review = after.review.model_dump(exclude={"approval_resource_version"})
            if (
                before_review != after_review
                or after.review.approval_resource_version < before.review.approval_resource_version
                or (
                    after.review.approval_resource_version > before.review.approval_resource_version
                    and after.human_approval is None
                )
            ):
                return False
        if before.analysis is not None:
            if after.analysis is None:
                return False
            for field in (
                "analysis_run_id",
                "source_item_revision_id",
                "request_sha256",
                "risk_policy_revision_id",
                "risk_policy_sha256",
            ):
                if getattr(before.analysis, field) != getattr(after.analysis, field):
                    return False
            if after.analysis.resource_version < before.analysis.resource_version:
                return False
            if after.analysis.state not in _ANALYSIS_STATE_TRANSITIONS[before.analysis.state]:
                return False
            if (
                after.analysis != before.analysis
                and after.analysis.resource_version <= before.analysis.resource_version
            ):
                return False
    return True
