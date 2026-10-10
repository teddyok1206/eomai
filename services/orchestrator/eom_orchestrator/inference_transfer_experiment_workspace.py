"""One protected temporary experiment handoff, not a job registry or source ACL."""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from eom_catalog_contracts.inference_transfer_experiment import (
    InferenceTransferExperimentRequest,
    InferenceTransferExperimentResult,
    validate_experiment_result,
)
from eom_catalog_contracts.models import UtcDatetime
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import canonical_json_bytes, sha256_bytes
from pydantic import TypeAdapter

from eom_orchestrator.inference_transfer_experiment_ports import (
    LocalExperimentInput,
    LocalExperimentPublication,
)

MAX_EXPERIMENT_MEMBER_BYTES = 64 * 1024**2
RESULT_SCHEMA = "eom://schemas/knowledge/item-inference-transfer-experiment/1.0"
_EXECUTION = re.compile(r"embeddingexecution_[0-9a-f]{32}\Z")
_HASH = re.compile(rb"sha256:[0-9a-f]{64}\Z")
_MEMBERS = frozenset(
    {
        "request.json",
        "result.json",
        "publication-result.json",
        ".launch-started",
        ".launch-completed",
        ".launch-failed",
    }
)


class ExperimentWorkspaceError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _epoch(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _location(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts or Path("/mnt/nas") in (path, *path.parents):
        raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_LOCAL_WORKSPACE_REQUIRED")
    for node in (path, *path.parents):
        value = node.lstat()
        sticky_root = value.st_uid == 0 and bool(value.st_mode & stat.S_ISVTX)
        if (
            not stat.S_ISDIR(value.st_mode)
            or value.st_uid not in {0, os.geteuid()}
            or (value.st_mode & 0o022 and not sticky_root)
        ):
            raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_WORKSPACE_INVALID")


class ProtectedExperimentWorkspace:
    """FD identity checks mirror the existing protected materializer boundary."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @contextmanager
    def _directory(self, path: Path, *, private: bool) -> Iterator[int]:
        descriptor: int | None = None
        try:
            _location(path)
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            initial = os.fstat(descriptor)
            if (
                initial.st_uid != os.geteuid()
                or initial.st_mode & 0o022
                or (private and stat.S_IMODE(initial.st_mode) != 0o700)
            ):
                raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_WORKSPACE_INVALID")
            yield descriptor
            final = path.lstat()
            if (
                (initial.st_dev, initial.st_ino) != (final.st_dev, final.st_ino)
                or final.st_uid != os.geteuid()
                or (private and stat.S_IMODE(final.st_mode) != 0o700)
            ):
                raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_WORKSPACE_CHANGED")
            _location(path)
        except OSError as exc:
            raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_WORKSPACE_INVALID") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _path(self, prepared: LocalExperimentInput) -> Path:
        if (
            _EXECUTION.fullmatch(prepared.execution_id) is None
            or prepared.workspace != self.root / prepared.execution_id
        ):
            raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_WORKSPACE_INVALID")
        return prepared.workspace

    def _read(
        self, path: Path, name: str, *, maximum_bytes: int, allow_empty: bool = False
    ) -> bytes:
        if name not in _MEMBERS:
            raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_MEMBER_INVALID")
        descriptor: int | None = None
        try:
            with self._directory(path, private=True) as directory:
                descriptor = os.open(
                    name,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                    dir_fd=directory,
                )
                before = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_uid != os.geteuid()
                    or before.st_nlink != 1
                    or stat.S_IMODE(before.st_mode) != 0o600
                    or not (0 if allow_empty else 1) <= before.st_size <= maximum_bytes
                ):
                    raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_MEMBER_INVALID")
                chunks: list[bytes] = []
                total = 0
                while chunk := os.read(descriptor, min(1024**2, before.st_size + 1 - total)):
                    total += len(chunk)
                    if total > before.st_size:
                        raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_MEMBER_CHANGED")
                    chunks.append(chunk)
                after = os.fstat(descriptor)
                named = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if (
                    total != before.st_size
                    or _epoch(before) != _epoch(after)
                    or _epoch(after) != _epoch(named)
                ):
                    raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_MEMBER_CHANGED")
                return b"".join(chunks)
        except OSError as exc:
            raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_MEMBER_INVALID") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _exists(self, path: Path, name: str) -> bool:
        if name not in _MEMBERS:
            raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_MEMBER_INVALID")
        with self._directory(path, private=True) as directory:
            try:
                os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                return False
            return True

    def _write(self, path: Path, name: str, payload: bytes) -> None:
        if name not in _MEMBERS or len(payload) > MAX_EXPERIMENT_MEMBER_BYTES:
            raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_MEMBER_INVALID")
        descriptor: int | None = None
        try:
            with self._directory(path, private=True) as directory:
                descriptor = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=directory,
                )
                os.fchmod(descriptor, 0o600)
                remaining = memoryview(payload)
                while remaining:
                    written = os.write(descriptor, remaining)
                    if written <= 0:
                        raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_MEMBER_WRITE_FAILED")
                    remaining = remaining[written:]
                os.fsync(descriptor)
                current = os.fstat(descriptor)
                named = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if (
                    current.st_size != len(payload)
                    or _epoch(current) != _epoch(named)
                    or current.st_nlink != 1
                    or current.st_uid != os.geteuid()
                    or stat.S_IMODE(current.st_mode) != 0o600
                ):
                    raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_MEMBER_CHANGED")
                os.fsync(directory)
        except FileExistsError as exc:
            raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_MEMBER_ALREADY_EXISTS") from exc
        except OSError as exc:
            raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_MEMBER_WRITE_FAILED") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def prepare(
        self,
        request: InferenceTransferExperimentRequest,
        *,
        execution_id: str,
        created_at: datetime,
    ) -> LocalExperimentInput:
        request = InferenceTransferExperimentRequest.model_validate(request.model_dump(mode="json"))
        validate_contract("item-inference-transfer-experiment", request.model_dump(mode="json"))
        timestamp = TypeAdapter(UtcDatetime).validate_python(created_at)
        if _EXECUTION.fullmatch(execution_id) is None:
            raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_EXECUTION_ID_INVALID")
        payload = canonical_json_bytes(request.model_dump(mode="json"))
        if len(payload) > min(MAX_EXPERIMENT_MEMBER_BYTES, request.budget.maximum_input_bytes):
            raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_INPUT_BUDGET_EXCEEDED")
        path = self.root / execution_id
        with self._directory(self.root, private=False) as directory:
            try:
                os.mkdir(execution_id, mode=0o700, dir_fd=directory)
                created = True
            except FileExistsError:
                created = False
        if created:
            self._write(path, "request.json", payload)
        elif (
            self._read(path, "request.json", maximum_bytes=request.budget.maximum_input_bytes)
            != payload
        ):
            raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_INPUT_PIN_MISMATCH")
        return LocalExperimentInput(
            path, execution_id, timestamp, request.request_sha256, len(payload)
        )

    def state(
        self, prepared: LocalExperimentInput
    ) -> Literal["NOT_STARTED", "COMPLETED", "KNOWN_FAILED", "UNCERTAIN"]:
        path = self._path(prepared)
        started = self._exists(path, ".launch-started")
        completed = self._exists(path, ".launch-completed")
        failed = self._exists(path, ".launch-failed")
        if not started:
            if completed or failed or self._exists(path, "result.json"):
                raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_EXECUTION_STATE_INVALID")
            return "NOT_STARTED"
        self._read(path, ".launch-started", maximum_bytes=0, allow_empty=True)
        if completed and failed:
            raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_EXECUTION_STATE_INVALID")
        if failed:
            self._read(path, ".launch-failed", maximum_bytes=0, allow_empty=True)
            return "KNOWN_FAILED"
        if completed:
            digest = self._read(path, ".launch-completed", maximum_bytes=71)
            if _HASH.fullmatch(digest) is None:
                raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_EXECUTION_STATE_INVALID")
            return "COMPLETED"
        return "UNCERTAIN"

    def claim(
        self, prepared: LocalExperimentInput, request: InferenceTransferExperimentRequest
    ) -> None:
        request = InferenceTransferExperimentRequest.model_validate(request.model_dump(mode="json"))
        path = self._path(prepared)
        expected = canonical_json_bytes(request.model_dump(mode="json"))
        if (
            self._read(path, "request.json", maximum_bytes=request.budget.maximum_input_bytes)
            != expected
        ):
            raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_INPUT_PIN_MISMATCH")
        self._write(path, ".launch-started", b"")

    def failed(self, prepared: LocalExperimentInput) -> None:
        self._write(self._path(prepared), ".launch-failed", b"")

    def materialize_cpu_result(self, prepared: LocalExperimentInput, payload: bytes) -> None:
        """One explicit temporary worker-output boundary, not validation or publication."""
        self._write(self._path(prepared), "result.json", payload)

    def validate_result(
        self,
        prepared: LocalExperimentInput,
        request: InferenceTransferExperimentRequest,
        *,
        completed: bool,
    ) -> tuple[InferenceTransferExperimentResult, LocalExperimentPublication]:
        path = self._path(prepared)
        # The result cannot certify that a mutable local input stayed intact.
        # This separate post-run FD boundary detects a broken read-only handoff
        # even when its JSON semantic hash would survive whitespace changes.
        if self._read(
            path, "request.json", maximum_bytes=request.budget.maximum_input_bytes
        ) != canonical_json_bytes(request.model_dump(mode="json")):
            raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_INPUT_PIN_MISMATCH")
        payload = self._read(path, "result.json", maximum_bytes=MAX_EXPERIMENT_MEMBER_BYTES)
        raw = json.loads(payload, object_pairs_hook=_unique_object)
        if not isinstance(raw, dict):
            raise ValueError("experiment result must be an object")
        validate_contract("item-inference-transfer-experiment", raw)
        result = InferenceTransferExperimentResult.model_validate(raw)
        validate_experiment_result(request, result)
        canonical = canonical_json_bytes(raw)
        if (
            payload not in (canonical, canonical + b"\n")
            or result.execution_id != prepared.execution_id
            or result.backend_kind != "PINNED_MODEL"
            or result.actual_model_manifest_sha256 != request.model_spec.manifest_sha256
        ):
            raise ValueError("experiment output identity or provenance differs")
        if completed:
            observed = self._read(path, ".launch-completed", maximum_bytes=71)
            if observed.decode("ascii") != sha256_bytes(payload):
                raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_RESULT_CHANGED")
        if self._exists(path, "publication-result.json"):
            if (
                self._read(
                    path, "publication-result.json", maximum_bytes=MAX_EXPERIMENT_MEMBER_BYTES
                )
                != canonical
            ):
                raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_RESULT_CHANGED")
        else:
            self._write(path, "publication-result.json", canonical)
        if not completed:
            # A completion observation is created only after the publication
            # materialization is itself intact. Partial writes remain failed,
            # never a completed marker accompanied by a failure marker.
            self._write(path, ".launch-completed", sha256_bytes(payload).encode("ascii"))
        return result, LocalExperimentPublication(
            prepared.execution_id,
            result.created_at,
            result.result_sha256,
            path / "publication-result.json",
            sha256_bytes(canonical),
            len(canonical),
        )
