"""Validate one local native result; only the existing publisher commits its file set."""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import (
    MAX_EMBEDDING_INPUT_BYTES,
    RESULT_SCHEMA_REF,
    SHARD_SCHEMA_REF,
    IncrementalEmbeddingInput,
    parse_incremental_embedding_input,
    parse_incremental_embedding_result,
    validate_incremental_embedding_result,
)
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.models import JobId
from eom_workflow.local_embedding_workflow import (
    LocalEmbeddingWorkflowRequest,
    parse_local_embedding_workflow_request,
)
from pydantic import TypeAdapter

from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)

_MEMBERS = frozenset({"result.json", "shard.json", "vectors.f32"})
_MAX_BINARY_BYTES = 16 * 1024**2
_BINARY_SCHEMA_REF = "eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0"


class EmbeddingArtifactStoreError(ValueError):
    """Content-free boundary failure; it does not assert publication never occurred."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PublishedEmbeddingArtifacts:
    owner_job_id: str
    logical_encoder_job_id: str
    result: ArtifactMemberPointer
    shard: ArtifactMemberPointer
    binary: ArtifactMemberPointer
    manifest_sha256: str


def _directory_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode


def _file_identity(value: os.stat_result) -> tuple[int, ...]:
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
def _directory(path: Path) -> Iterator[int]:
    """Reuse the protected handoff pattern: retain no-follow ancestor FDs until done."""
    if not path.is_absolute() or ".." in path.parts or Path("/mnt/nas") in (path, *path.parents):
        raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_WORKSPACE_INVALID")
    opened: list[tuple[int, int | None, str, os.stat_result]] = []
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        descriptor = os.open(path.root, flags)
        opened.append((descriptor, None, path.root, os.fstat(descriptor)))
        for member in path.parts[1:]:
            parent = descriptor
            descriptor = os.open(member, flags, dir_fd=parent)
            opened.append((descriptor, parent, member, os.fstat(descriptor)))
        for _fd, _parent, _name, value in opened:
            sticky_root = value.st_uid == 0 and bool(value.st_mode & stat.S_ISVTX)
            if (
                not stat.S_ISDIR(value.st_mode)
                or value.st_uid not in {0, os.geteuid()}
                or (value.st_mode & 0o022 and not sticky_root)
            ):
                raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_WORKSPACE_INVALID")
        value = opened[-1][3]
        if value.st_uid != os.geteuid() or stat.S_IMODE(value.st_mode) != 0o700:
            raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_WORKSPACE_INVALID")
        yield descriptor
        for fd, parent_fd, member, initial in opened:
            named = os.stat(member, dir_fd=parent_fd, follow_symlinks=False)
            if _directory_identity(initial) != _directory_identity(
                os.fstat(fd)
            ) or _directory_identity(initial) != _directory_identity(named):
                raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_WORKSPACE_CHANGED")
    except OSError as exc:
        raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_WORKSPACE_INVALID") from exc
    finally:
        for fd, _parent, _member, _initial in reversed(opened):
            os.close(fd)


@contextmanager
def _member(directory: int, name: str, maximum_bytes: int) -> Iterator[bytes]:
    """Hold the validated FD across publication; atime is not content identity."""
    if name not in _MEMBERS:
        raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_MEMBER_INVALID")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=directory
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 1 <= before.st_size <= maximum_bytes
        ):
            raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_MEMBER_INVALID")
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(descriptor, min(1024**2, before.st_size + 1 - total)):
            total += len(chunk)
            if total > before.st_size:
                raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_MEMBER_CHANGED")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        named = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if (
            total != before.st_size
            or _file_identity(before) != _file_identity(after)
            or _file_identity(after) != _file_identity(named)
        ):
            raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_MEMBER_CHANGED")
        payload = b"".join(chunks)
        chunks.clear()
        yield payload
        if _file_identity(before) != _file_identity(os.fstat(descriptor)) or _file_identity(
            before
        ) != _file_identity(os.stat(name, dir_fd=directory, follow_symlinks=False)):
            raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_MEMBER_CHANGED")
    except OSError as exc:
        raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_MEMBER_INVALID") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _materialize_shard(directory: int, payload: bytes) -> None:
    """Create once; a partial or conflicting preexisting file is never overwritten."""
    descriptor: int | None = None
    try:
        descriptor = os.open(
            "shard.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory,
        )
        os.fchmod(descriptor, 0o600)
        remaining = memoryview(payload)
        while remaining:
            count = os.write(descriptor, remaining)
            if count <= 0:
                raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_MEMBER_WRITE_FAILED")
            remaining = remaining[count:]
        os.fsync(descriptor)
        current = os.fstat(descriptor)
        if (
            current.st_uid != os.geteuid()
            or current.st_nlink != 1
            or stat.S_IMODE(current.st_mode) != 0o600
            or current.st_size != len(payload)
            or _file_identity(current)
            != _file_identity(os.stat("shard.json", dir_fd=directory, follow_symlinks=False))
        ):
            raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_MEMBER_CHANGED")
        os.fsync(directory)
    except FileExistsError:
        return
    except OSError as exc:
        raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_MEMBER_WRITE_FAILED") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for name, member in pairs:
        if name in value:
            raise ValueError("duplicate JSON member")
        value[name] = member
    return value


class EmbeddingArtifactStore:
    """No DB or direct NAS access; current source authorization belongs to the caller."""

    def __init__(self, publisher: ControlFileSetPublisher, *, source_commit: str) -> None:
        if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
            raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_SOURCE_INVALID")
        self.publisher = publisher
        self.source_commit = source_commit

    def publish(
        self,
        *,
        workflow_request: LocalEmbeddingWorkflowRequest,
        request: IncrementalEmbeddingInput,
        workspace: Path,
        created_at: datetime,
    ) -> PublishedEmbeddingArtifacts:
        try:
            workflow_request = parse_local_embedding_workflow_request(
                workflow_request.model_dump(mode="json")
            )
            request = parse_incremental_embedding_input(request.model_dump(mode="json"))
            timestamp = TypeAdapter(UtcDatetime).validate_python(created_at)
            if (
                workflow_request.input_artifact.sha256
                != content_sha256(request.model_dump(mode="json"))
                or workflow_request.space != request.space
                or workflow_request.input_set_sha256 != request.input_set_sha256
            ):
                raise ValueError("Workflow and materialized native input differ")
        except Exception:
            raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_CONTEXT_INVALID") from None
        key = content_sha256(
            {
                "logical_encoder_job_id": request.job_id,
                "native_request_sha256": request.request_sha256,
                "workflow_request_sha256": workflow_request.request_sha256,
            }
        ).removeprefix("sha256:")
        with (
            _directory(workspace) as directory,
            _member(directory, "result.json", MAX_EMBEDDING_INPUT_BYTES) as result_bytes,
            _member(directory, "vectors.f32", _MAX_BINARY_BYTES) as binary_bytes,
        ):
            try:
                document = json.loads(result_bytes, object_pairs_hook=_unique_object)
                if not isinstance(document, dict):
                    raise ValueError("result root differs")
                result = parse_incremental_embedding_result(document)
                validate_incremental_embedding_result(request, result)
                if result_bytes != canonical_json_bytes(result.model_dump(mode="json")):
                    raise ValueError("result member is not exact canonical JSON")
            except Exception:
                raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_RESULT_INVALID") from None
            shard = result.shard
            read_unit_vectors(
                binary_bytes,
                dimension=shard.dimension,
                row_count=shard.row_count,
                expected_sha256=shard.binary.sha256,
            )
            shard_bytes = canonical_json_bytes(shard.model_dump(mode="json"))
            _materialize_shard(directory, shard_bytes)
            with _member(directory, "shard.json", MAX_EMBEDDING_INPUT_BYTES) as saved_shard:
                if saved_shard != shard_bytes:
                    raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_SHARD_CONFLICT")
                members = (
                    ControlFileSetMember(
                        "result.json",
                        workspace / "result.json",
                        sha256_bytes(result_bytes),
                        len(result_bytes),
                        RESULT_SCHEMA_REF,
                        "application/json",
                    ),
                    ControlFileSetMember(
                        "shard.json",
                        workspace / "shard.json",
                        sha256_bytes(shard_bytes),
                        len(shard_bytes),
                        SHARD_SCHEMA_REF,
                        "application/json",
                    ),
                    ControlFileSetMember(
                        "vectors.f32",
                        workspace / "vectors.f32",
                        shard.binary.sha256,
                        len(binary_bytes),
                        _BINARY_SCHEMA_REF,
                        "application/octet-stream",
                    ),
                )
                receipt = self.publisher.publish(
                    members=members,
                    primary_file="result.json",
                    artifact_type="control_incremental_embedding",
                    manifest_version="control-file-set/1.0",
                    idempotency_key="embedding-artifact:" + key,
                    source_commit=self.source_commit,
                    created_at=timestamp,
                )
                try:
                    owner_job_id = TypeAdapter(JobId).validate_python(receipt.job_id)
                    manifest_sha256 = TypeAdapter(Sha256).validate_python(receipt.manifest_sha256)
                    if (
                        receipt.primary_file != "result.json"
                        or receipt.primary_sha256 != members[0].sha256
                        or owner_job_id == request.job_id
                    ):
                        raise ValueError("owner receipt identity differs")
                    pointers = tuple(
                        ArtifactMemberPointer(
                            artifact_id=receipt.artifact_id,
                            artifact_revision_id=receipt.artifact_revision_id,
                            member_path=member.file_name,
                            schema_ref=member.schema_ref,
                            media_type=member.media_type,
                            sha256=member.sha256,
                        )
                        for member in members
                    )
                    return PublishedEmbeddingArtifacts(
                        owner_job_id,
                        request.job_id,
                        pointers[0],
                        pointers[1],
                        pointers[2],
                        manifest_sha256,
                    )
                except Exception:
                    raise EmbeddingArtifactStoreError(
                        "EMBEDDING_ARTIFACT_RECEIPT_INVALID"
                    ) from None
