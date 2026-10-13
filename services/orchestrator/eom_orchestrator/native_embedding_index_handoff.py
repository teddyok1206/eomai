"""Fixed native INDEX staging and three-file root handoff; no source or launch authority."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import (
    MAX_EMBEDDING_INPUT_BYTES,
    IncrementalEmbeddingInput,
    IncrementalEmbeddingResult,
    parse_incremental_embedding_input,
    parse_incremental_embedding_result,
    validate_incremental_embedding_result,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.local_embedding_encoding_job import (
    LocalEmbeddingLaunchAssociation,
    parse_embedding_encoding_job_message,
)

from eom_orchestrator.inference_transfer_cpu_handoff import (
    CpuHandoffIdentity,
    create_protected_cpu_handoff_member,
    fixed_owner_identity,
    protected_cpu_handoff_directory,
    read_protected_cpu_handoff_member,
)

OWNER_ROOT = Path("/var/lib/eom-workflow-runner/incremental-embeddings/index")
RUNTIME_ROOT = Path("/run/eom-embedding-native-index")
MAX_BINARY_BYTES = 16 * 1024**2
_EXECUTION = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)


class NativeIndexHandoffError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def validate_native_index_execution_id(value: str) -> str:
    if type(value) is not str or _EXECUTION.fullmatch(value) is None:
        raise NativeIndexHandoffError("NATIVE_INDEX_EXECUTION_ID_INVALID")
    return value


def _canonical_value(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise NativeIndexHandoffError("NATIVE_INDEX_CANONICAL_INPUT_INVALID")
    return value


def _checked_batch(
    association: LocalEmbeddingLaunchAssociation, request: IncrementalEmbeddingInput
) -> tuple[LocalEmbeddingLaunchAssociation, IncrementalEmbeddingInput]:
    association_value = parse_embedding_encoding_job_message(association.model_dump(mode="json"))
    request = parse_incremental_embedding_input(request.model_dump(mode="json"))
    if not isinstance(association_value, LocalEmbeddingLaunchAssociation):
        raise NativeIndexHandoffError("NATIVE_INDEX_ASSOCIATION_INVALID")
    association = association_value
    if (
        request.space.runtime.device != "CPU"
        or request.batch_size != 4
        or request.threads != 4
        or request.job_id != association.intent.native_launch_job_id
        or request.space != association.owned_jobs[0].request.space
        or tuple(row.encoding for row in request.rows)
        != tuple(job.request.encoding for job in association.owned_jobs)
        or request.request_sha256 != association.owned_input_request_sha256
        or request.input_set_sha256 != association.owned_input_set_sha256
        or sha256_bytes(canonical_json_bytes(request.model_dump(mode="json")))
        != association.owned_input.sha256
    ):
        raise NativeIndexHandoffError("NATIVE_INDEX_ASSOCIATION_INPUT_MISMATCH")
    return association, request


@dataclass(frozen=True, slots=True)
class PreparedNativeIndex:
    """Explicit local materialization, not source permission or a launch grant."""

    execution_id: str
    association: LocalEmbeddingLaunchAssociation
    request: IncrementalEmbeddingInput

    def __post_init__(self) -> None:
        validate_native_index_execution_id(self.execution_id)
        association, request = _checked_batch(self.association, self.request)
        object.__setattr__(self, "association", association)
        object.__setattr__(self, "request", request)

    @property
    def workspace(self) -> Path:
        return OWNER_ROOT / self.execution_id


def _owner() -> CpuHandoffIdentity:
    owner = fixed_owner_identity()
    if os.geteuid() != owner.owner_uid:
        raise NativeIndexHandoffError("NATIVE_INDEX_OWNER_REQUIRED")
    return owner


def _write_owner_member(
    directory: int, name: str, payload: bytes, owner: CpuHandoffIdentity
) -> None:
    """Same exact bytes may replay; partial or changed files never get overwritten."""
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory,
        )
    except FileExistsError:
        existing = read_protected_cpu_handoff_member(
            directory, name, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o600
        )
        if existing != payload:
            raise NativeIndexHandoffError("NATIVE_INDEX_OWNER_MEMBER_CONFLICT") from None
        return
    try:
        os.fchmod(descriptor, 0o600)
        remaining = memoryview(payload)
        while remaining:
            count = os.write(descriptor, remaining)
            if count <= 0:
                raise NativeIndexHandoffError("NATIVE_INDEX_OWNER_WRITE_FAILED")
            remaining = remaining[count:]
        os.fsync(descriptor)
        actual = os.fstat(descriptor)
        named = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if (
            not stat.S_ISREG(actual.st_mode)
            or actual.st_uid != owner.owner_uid
            or actual.st_gid != owner.owner_gid
            or actual.st_nlink != 1
            or stat.S_IMODE(actual.st_mode) != 0o600
            or actual.st_size != len(payload)
            or (actual.st_dev, actual.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise NativeIndexHandoffError("NATIVE_INDEX_OWNER_WRITE_FAILED")
        os.fsync(directory)
    finally:
        os.close(descriptor)


def ensure_native_index_owner_workspace(execution_id: str) -> Path:
    """Durable fixed owner-local commit workspace, including a borrowed-only execution."""
    execution_id = validate_native_index_execution_id(execution_id)
    owner = _owner()
    with protected_cpu_handoff_directory(
        OWNER_ROOT, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as parent:
        try:
            os.mkdir(execution_id, mode=0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
    workspace = OWNER_ROOT / execution_id
    with protected_cpu_handoff_directory(
        workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ):
        pass
    return workspace


def stage_native_index(prepared: PreparedNativeIndex) -> None:
    prepared = PreparedNativeIndex(prepared.execution_id, prepared.association, prepared.request)
    owner = _owner()
    ensure_native_index_owner_workspace(prepared.execution_id)
    with protected_cpu_handoff_directory(
        prepared.workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        _write_owner_member(
            directory,
            "input.json",
            canonical_json_bytes(prepared.request.model_dump(mode="json")),
            owner,
        )
        _write_owner_member(
            directory,
            "association.json",
            canonical_json_bytes(prepared.association.model_dump(mode="json")),
            owner,
        )


def _read_prepared(execution_id: str, owner: CpuHandoffIdentity) -> PreparedNativeIndex:
    execution_id = validate_native_index_execution_id(execution_id)
    with protected_cpu_handoff_directory(
        OWNER_ROOT / execution_id, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        request = parse_incremental_embedding_input(
            _canonical_value(
                read_protected_cpu_handoff_member(
                    directory, "input.json", uid=owner.owner_uid, gid=owner.owner_gid, mode=0o600
                )
            )
        )
        association = parse_embedding_encoding_job_message(
            _canonical_value(
                read_protected_cpu_handoff_member(
                    directory,
                    "association.json",
                    uid=owner.owner_uid,
                    gid=owner.owner_gid,
                    mode=0o600,
                )
            )
        )
        if not isinstance(association, LocalEmbeddingLaunchAssociation):
            raise NativeIndexHandoffError("NATIVE_INDEX_ASSOCIATION_INVALID")
    return PreparedNativeIndex(execution_id, association, request)


def mark_native_index_launch_started(prepared: PreparedNativeIndex) -> None:
    """Caller must first bind the launch and commit its fresh command/source fence."""
    owner = _owner()
    if _read_prepared(prepared.execution_id, owner) != prepared:
        raise NativeIndexHandoffError("NATIVE_INDEX_STAGED_INPUT_CHANGED")
    with protected_cpu_handoff_directory(
        prepared.workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        _write_owner_member(
            directory,
            ".launch-started",
            prepared.association.association_sha256.encode("ascii"),
            owner,
        )


def prepare_native_index_handoff(execution_id: str) -> None:
    """Root prepare checks trusted staging provenance, never a DTO-supplied actor."""
    if os.geteuid() != 0:
        raise NativeIndexHandoffError("NATIVE_INDEX_ROOT_REQUIRED")
    owner = fixed_owner_identity()
    prepared = _read_prepared(execution_id, owner)
    with protected_cpu_handoff_directory(
        prepared.workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        marker = read_protected_cpu_handoff_member(
            directory, ".launch-started", uid=owner.owner_uid, gid=owner.owner_gid, mode=0o600
        )
        if marker != prepared.association.association_sha256.encode("ascii"):
            raise NativeIndexHandoffError("NATIVE_INDEX_LAUNCH_MARKER_INVALID")
    with protected_cpu_handoff_directory(
        RUNTIME_ROOT, owner=owner, uid=0, gid=owner.owner_gid, mode=0o750
    ) as parent:
        try:
            os.mkdir(prepared.execution_id, mode=0o750, dir_fd=parent)
        except FileExistsError:
            raise NativeIndexHandoffError("NATIVE_INDEX_HANDOFF_EXISTS") from None
        directory = os.open(
            prepared.execution_id,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent,
        )
        try:
            os.fchown(directory, 0, owner.owner_gid)
            os.fchmod(directory, 0o750)
            create_protected_cpu_handoff_member(
                directory,
                "input.json",
                canonical_json_bytes(prepared.request.model_dump(mode="json")),
                owner_gid=owner.owner_gid,
                mode=0o600,
            )
            for name in ("result.json", "vectors.f32"):
                create_protected_cpu_handoff_member(
                    directory, name, b"", owner_gid=owner.owner_gid, mode=0o640
                )
            os.fsync(directory)
            named = os.stat(prepared.execution_id, dir_fd=parent, follow_symlinks=False)
            actual = os.fstat(directory)
            if (named.st_dev, named.st_ino, named.st_uid, named.st_gid, named.st_mode) != (
                actual.st_dev,
                actual.st_ino,
                actual.st_uid,
                actual.st_gid,
                actual.st_mode,
            ):
                raise NativeIndexHandoffError("NATIVE_INDEX_ROOT_DIRECTORY_CHANGED")
            os.fsync(parent)
        finally:
            os.close(directory)


def materialize_native_index_output(prepared: PreparedNativeIndex) -> IncrementalEmbeddingResult:
    """Call only after exact-unit termination; validate before owner Artifact publication."""
    owner = _owner()
    if _read_prepared(prepared.execution_id, owner) != prepared:
        raise NativeIndexHandoffError("NATIVE_INDEX_STAGED_INPUT_CHANGED")
    with protected_cpu_handoff_directory(
        RUNTIME_ROOT / prepared.execution_id, owner=owner, uid=0, gid=owner.owner_gid, mode=0o750
    ) as directory:
        result_raw = read_protected_cpu_handoff_member(
            directory, "result.json", uid=0, gid=owner.owner_gid, mode=0o640
        )
        vectors = read_protected_cpu_handoff_member(
            directory,
            "vectors.f32",
            uid=0,
            gid=owner.owner_gid,
            mode=0o640,
            maximum_bytes=MAX_BINARY_BYTES,
        )
    if len(result_raw) > MAX_EMBEDDING_INPUT_BYTES or len(vectors) > MAX_BINARY_BYTES:
        raise NativeIndexHandoffError("NATIVE_INDEX_OUTPUT_TOO_LARGE")
    result = parse_incremental_embedding_result(_canonical_value(result_raw))
    validate_incremental_embedding_result(prepared.request, result)
    read_unit_vectors(
        vectors,
        dimension=result.shard.dimension,
        row_count=result.shard.row_count,
        expected_sha256=result.shard.binary.sha256,
    )
    with protected_cpu_handoff_directory(
        prepared.workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        _write_owner_member(directory, "vectors.f32", vectors, owner)
        _write_owner_member(directory, "result.json", result_raw, owner)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("execution_id")
    arguments = parser.parse_args()
    try:
        prepare_native_index_handoff(arguments.execution_id)
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
