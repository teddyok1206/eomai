"""Validate native encoding or index metadata; commit only through the existing owner."""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Annotated, Any

from eom_catalog_contracts.embedding_index_families import (
    SupportedEmbeddingIndex,
    parse_supported_embedding_index,
    validate_supported_embedding_index_references,
)
from eom_catalog_contracts.embedding_private_chat_query import (
    MAX_PRIVATE_CHAT_QUERY_BYTES,
    PRIVATE_CHAT_QUERY_RESULT_REF,
    EmbeddingPrivateChatQueryInput,
    EmbeddingPrivateChatQueryResult,
    validate_private_chat_query_result,
)
from eom_catalog_contracts.embedding_reference_query import (
    MAX_REFERENCE_QUERY_BYTES,
    REFERENCE_QUERY_RESULT_REF,
    parse_embedding_reference_query_result,
    raw_similarity_contract_value,
)
from eom_catalog_contracts.embedding_reference_query_v11 import (
    REFERENCE_QUERY_INPUT_V11_REF,
    EmbeddingReferenceQueryInputV11,
    parse_embedding_reference_query_input_v11,
    validate_reference_query_result_v11,
)
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingRuntimeBundle
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import (
    MAX_EMBEDDING_INPUT_BYTES,
    MAX_EMBEDDING_ROWS,
    RESULT_SCHEMA_REF,
    SHARD_SCHEMA_REF,
    EmbeddingIndexManifest,
    EmbeddingVectorShardManifest,
    IncrementalEmbeddingInput,
    parse_incremental_embedding_input,
    parse_incremental_embedding_result,
    validate_incremental_embedding_result,
)
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.mixed_embedding_index import (
    MixedEmbeddingIndexManifest,
)
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_catalog_contracts.public_solution_embedding_index import (
    MAX_PUBLIC_SOLUTION_SOURCES,
    PublicSolutionEmbeddingIndex,
)
from eom_catalog_contracts.public_solution_query import (
    PUBLIC_SOLUTION_QUERY_INPUT_REF,
    PUBLIC_SOLUTION_QUERY_RESULT_REF,
    PublicSolutionQueryInput,
    PublicSolutionQueryResult,
    validate_public_solution_query_result,
)
from eom_catalog_contracts.registered_public_solution_index import PublicSolutionEmbeddingIndexV4
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.models import ArtifactId, JobId, RevisionId
from eom_workflow.local_embedding_encoding_dispatch import (
    SupportedEmbeddingAssociation,
    parse_supported_embedding_association,
    validate_supported_embedding_association,
)
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingExecutablePolicy
from eom_workflow.local_embedding_request_v2 import (
    SupportedLocalEmbeddingRequest,
    parse_supported_local_embedding_request,
    validate_supported_local_embedding_request_references,
)
from eom_workflow.local_embedding_source_plan_dispatch import SupportedLocalEmbeddingSourcePlan
from eom_workflow.local_embedding_workflow import (
    LocalEmbeddingWorkflowRequest,
    parse_local_embedding_workflow_request,
)
from eom_workflow.private_chat_query_execution import (
    PrivateChatQueryExecutionPolicy,
    PrivateChatQueryWorkflowRequest,
)
from eom_workflow.private_chat_query_publication import (
    PRIVATE_CHAT_QUERY_RECORD_REF,
    PrivateChatQueryLaunchAssociation,
    validate_private_chat_query_launch,
)
from eom_workflow.reference_query_execution import (
    PublicReferenceQueryWorkflowRequest,
    ReferenceQueryExecutionPolicy,
    ReferenceQueryLaunchAssociation,
    SupportedReferenceQueryNativeInput,
    SupportedReferenceQueryNativeResult,
    SupportedReferenceQueryWorkflowIntent,
    SupportedReferenceQueryWorkflowRequest,
    parse_reference_query_execution_policy,
    parse_reference_query_launch_association,
    parse_supported_reference_query_workflow_intent,
    parse_supported_reference_query_workflow_request,
    validate_reference_query_launch_association,
)
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import Field, TypeAdapter

from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetIdentity,
    ControlFileSetMember,
    ControlFileSetPublisher,
    PublishedControlFileSet,
)

EMBEDDING_INDEX_ARTIFACT_TYPE = "control_embedding_index"
EMBEDDING_RESULT_ARTIFACT_TYPE = "control_incremental_embedding"
EMBEDDING_REFERENCE_QUERY_ARTIFACT_TYPE = "control_embedding_reference_query"
EMBEDDING_PRIVATE_CHAT_QUERY_ARTIFACT_TYPE = "control_embedding_private_chat_query"
EMBEDDING_INDEX_MANIFEST_VERSION = CONTROL_FILE_SET_PROTOCOL
EMBEDDING_INDEX_PRIMARY_MEMBER = "index.json"
EMBEDDING_INDEX_MEMBER_NAMES = (EMBEDDING_INDEX_PRIMARY_MEMBER,)
_MEMBERS = frozenset(
    {
        "input.json",
        "intent.json",
        "result.json",
        "shard.json",
        "vectors.f32",
        EMBEDDING_INDEX_PRIMARY_MEMBER,
    }
)
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


@dataclass(frozen=True, slots=True)
class PublishedReferenceQueryArtifacts:
    """Publication pointers only; not a current authorization or genuine producer proof."""

    owner_job_id: str
    logical_query_job_id: str
    input: ArtifactMemberPointer
    result: ArtifactMemberPointer
    shard: ArtifactMemberPointer
    binary: ArtifactMemberPointer
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class PublishedPrivateChatQueryArtifacts:
    """Private pointer-only publication; the original message remains canonical text."""

    owner_job_id: str
    logical_query_job_id: str
    intent: ArtifactMemberPointer
    result: ArtifactMemberPointer
    shard: ArtifactMemberPointer
    binary: ArtifactMemberPointer
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class EmbeddingIndexPublicationScope:
    """Expected immutable metadata only; the official caller owns current authorization."""

    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str
    policy_sha256: str


@dataclass(frozen=True, slots=True)
class PublishedEmbeddingIndexArtifacts:
    owner_job_id: str
    index_id: str
    index_revision_id: str
    index_manifest: ArtifactMemberPointer
    index_sha256: str
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


def _materialize_manifest(directory: int, name: str, payload: bytes) -> None:
    """Serialize local create/fsync; never expose our own partial manifest to a replay.

    The retained owner directory FD is the lock identity. It is released before
    publication/DB locks; canonical uniqueness still belongs to the commit owner.
    A partial or conflicting file left by an earlier crash is never overwritten.
    """
    if name not in {"intent.json", "shard.json", EMBEDDING_INDEX_PRIMARY_MEMBER}:
        raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_MEMBER_INVALID")
    descriptor: int | None = None
    locked = False
    try:
        fcntl.flock(directory, fcntl.LOCK_EX)
        locked = True
        descriptor = os.open(
            name,
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
            != _file_identity(os.stat(name, dir_fd=directory, follow_symlinks=False))
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
        if locked:
            fcntl.flock(directory, fcntl.LOCK_UN)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for name, member in pairs:
        if name in value:
            raise ValueError("duplicate JSON member")
        value[name] = member
    return value


def owned_embedding_publication_key(
    association: SupportedEmbeddingAssociation, *, workflow_request_sha256: str
) -> str:
    """Exact original output lookup identity, not source or publication authority."""
    association = parse_supported_embedding_association(association)
    workflow_request_sha256 = TypeAdapter(Sha256).validate_python(workflow_request_sha256)
    if association.intent.workflow_request_sha256 != workflow_request_sha256:
        raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_CONTEXT_INVALID")
    return "embedding-artifact:" + content_sha256(
        {
            "logical_encoder_job_id": association.intent.native_launch_job_id,
            "native_request_sha256": association.owned_input_request_sha256,
            "launch_association_sha256": association.association_sha256,
            "workflow_request_sha256": workflow_request_sha256,
        }
    ).removeprefix("sha256:")


class EmbeddingArtifactStore:
    """No DB or direct NAS access; current source authorization belongs to the caller."""

    def __init__(self, publisher: ControlFileSetPublisher, *, source_commit: str) -> None:
        if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
            raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_SOURCE_INVALID")
        self.publisher = publisher
        self.source_commit = source_commit

    def publish_reference_query(
        self,
        *,
        workflow_request: SupportedReferenceQueryWorkflowRequest,
        policy: ReferenceQueryExecutionPolicy,
        bundle: EmbeddingRuntimeBundle,
        launch: ReferenceQueryLaunchAssociation,
        request: EmbeddingReferenceQueryInputV11,
        workspace: Path,
        created_at: datetime,
        identity: ControlFileSetIdentity | None = None,
        expected_result_sha256: str | None = None,
    ) -> PublishedReferenceQueryArtifacts:
        """Commit supplied QUERY closure; the calling owner retains current auth/lease checks."""
        try:
            workflow_request = parse_supported_reference_query_workflow_request(workflow_request)
            request = parse_embedding_reference_query_input_v11(request)
        except (ValueError, TypeError, JsonSchemaValidationError):
            raise EmbeddingArtifactStoreError("EMBEDDING_REFERENCE_QUERY_CONTEXT_INVALID") from None
        return self.publish_supported_reference_query(
            workflow_request=workflow_request,
            policy=policy,
            bundle=bundle,
            launch=launch,
            request=request,
            workspace=workspace,
            created_at=created_at,
            identity=identity,
            expected_result_sha256=expected_result_sha256,
        )

    def publish_public_solution_reference_query(
        self,
        *,
        workflow_request: PublicReferenceQueryWorkflowRequest,
        policy: ReferenceQueryExecutionPolicy,
        bundle: EmbeddingRuntimeBundle,
        launch: ReferenceQueryLaunchAssociation,
        request: PublicSolutionQueryInput,
        workspace: Path,
        created_at: datetime,
        identity: ControlFileSetIdentity | None = None,
        expected_result_sha256: str | None = None,
    ) -> PublishedReferenceQueryArtifacts:
        """QUERY2 bytes through the same canonical commit owner, never a source/lease grant."""
        try:
            checked_workflow = parse_supported_reference_query_workflow_intent(workflow_request)
            if not isinstance(checked_workflow, PublicReferenceQueryWorkflowRequest):
                raise ValueError("public QUERY metadata family differs")
            workflow_request = checked_workflow
            request = PublicSolutionQueryInput.model_validate(request)
        except (ValueError, TypeError, JsonSchemaValidationError):
            raise EmbeddingArtifactStoreError("EMBEDDING_REFERENCE_QUERY_CONTEXT_INVALID") from None
        return self.publish_supported_reference_query(
            workflow_request=workflow_request,
            policy=policy,
            bundle=bundle,
            launch=launch,
            request=request,
            workspace=workspace,
            created_at=created_at,
            identity=identity,
            expected_result_sha256=expected_result_sha256,
        )

    def publish_supported_reference_query(
        self,
        *,
        workflow_request: SupportedReferenceQueryWorkflowIntent,
        policy: ReferenceQueryExecutionPolicy,
        bundle: EmbeddingRuntimeBundle,
        launch: ReferenceQueryLaunchAssociation,
        request: SupportedReferenceQueryNativeInput,
        workspace: Path,
        created_at: datetime,
        identity: ControlFileSetIdentity | None,
        expected_result_sha256: str | None,
    ) -> PublishedReferenceQueryArtifacts:
        try:
            # Parse raw instances before serialization so model_copy cannot discard bad extras.
            workflow_request = parse_supported_reference_query_workflow_intent(workflow_request)
            policy = parse_reference_query_execution_policy(policy)
            launch = parse_reference_query_launch_association(launch)
            if isinstance(workflow_request, PublicReferenceQueryWorkflowRequest):
                request = PublicSolutionQueryInput.model_validate(request)
                input_ref, result_ref = (
                    PUBLIC_SOLUTION_QUERY_INPUT_REF,
                    PUBLIC_SOLUTION_QUERY_RESULT_REF,
                )
            else:
                request = parse_embedding_reference_query_input_v11(request)
                input_ref, result_ref = REFERENCE_QUERY_INPUT_V11_REF, REFERENCE_QUERY_RESULT_REF
            validate_reference_query_launch_association(
                launch, workflow_request, policy, bundle, request
            )
            if expected_result_sha256 is not None:
                TypeAdapter(Sha256).validate_python(expected_result_sha256, strict=True)
            if identity is not None:
                if (
                    type(identity) is not ControlFileSetIdentity
                    or identity.job_id == request.job_id
                ):
                    raise ValueError("QUERY publication identity differs")
                identity = ControlFileSetIdentity(
                    identity.job_id, identity.artifact_id, identity.artifact_revision_id
                )
            timestamp = TypeAdapter(UtcDatetime).validate_python(created_at, strict=True)
            if timestamp < launch.launched_at:
                raise ValueError("publication precedes its launch association")
            input_bytes = canonical_json_bytes(request.model_dump(mode="json"))
        except (ValueError, TypeError, JsonSchemaValidationError):
            raise EmbeddingArtifactStoreError("EMBEDDING_REFERENCE_QUERY_CONTEXT_INVALID") from None
        key = "embedding-reference-query-artifact:" + content_sha256(
            {
                "logical_query_job_id": request.job_id,
                "native_request_sha256": request.request_sha256,
                "workflow_request_sha256": workflow_request.request_sha256,
                "launch_association_sha256": launch.association_sha256,
            }
        ).removeprefix("sha256:")
        with (
            _directory(workspace) as directory,
            _member(directory, "input.json", MAX_REFERENCE_QUERY_BYTES) as saved_input,
            _member(directory, "result.json", MAX_REFERENCE_QUERY_BYTES) as result_bytes,
            _member(directory, "vectors.f32", _MAX_BINARY_BYTES) as binary_bytes,
        ):
            if saved_input != input_bytes:
                raise EmbeddingArtifactStoreError("EMBEDDING_REFERENCE_QUERY_INPUT_INVALID")
            try:
                document = json.loads(result_bytes, object_pairs_hook=_unique_object)
                result: SupportedReferenceQueryNativeResult
                if isinstance(request, PublicSolutionQueryInput):
                    result = PublicSolutionQueryResult.model_validate(document)
                    validate_public_solution_query_result(request, result)
                else:
                    result = parse_embedding_reference_query_result(document)
                    validate_reference_query_result_v11(request, result)
                if (
                    expected_result_sha256 is not None
                    and result.result_sha256 != expected_result_sha256
                ):
                    raise ValueError("QUERY result differs from the actual completion observation")
                if result_bytes != canonical_json_bytes(result.model_dump(mode="json")):
                    raise ValueError("QUERY result is not exact canonical JSON")
            except (ValueError, TypeError, JsonSchemaValidationError, RecursionError):
                raise EmbeddingArtifactStoreError(
                    "EMBEDDING_REFERENCE_QUERY_RESULT_INVALID"
                ) from None
            shard = result.shard
            read_unit_vectors(
                binary_bytes,
                dimension=shard.dimension,
                row_count=shard.row_count,
                expected_sha256=shard.binary.sha256,
            )
            shard_bytes = canonical_json_bytes(shard.model_dump(mode="json"))
            _materialize_manifest(directory, "shard.json", shard_bytes)
            with _member(directory, "shard.json", MAX_REFERENCE_QUERY_BYTES) as saved_shard:
                if saved_shard != shard_bytes:
                    raise EmbeddingArtifactStoreError("EMBEDDING_REFERENCE_QUERY_SHARD_CONFLICT")
                members = (
                    ControlFileSetMember(
                        "input.json",
                        workspace / "input.json",
                        sha256_bytes(saved_input),
                        len(saved_input),
                        input_ref,
                        "application/json",
                    ),
                    ControlFileSetMember(
                        "result.json",
                        workspace / "result.json",
                        sha256_bytes(result_bytes),
                        len(result_bytes),
                        result_ref,
                        "application/json",
                    ),
                    ControlFileSetMember(
                        "shard.json",
                        workspace / "shard.json",
                        sha256_bytes(saved_shard),
                        len(saved_shard),
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
                receipt = self._publish_query_members(
                    members=members,
                    artifact_type=EMBEDDING_REFERENCE_QUERY_ARTIFACT_TYPE,
                    idempotency_key=key,
                    created_at=timestamp,
                    logical_query_job_id=request.job_id,
                    identity=identity,
                    receipt_error="EMBEDDING_REFERENCE_QUERY_RECEIPT_INVALID",
                )
                pointers = self._query_member_pointers(receipt, members)
                return PublishedReferenceQueryArtifacts(
                    receipt.job_id, request.job_id, *pointers, receipt.manifest_sha256
                )

    def _publish_query_members(
        self,
        *,
        members: tuple[ControlFileSetMember, ...],
        artifact_type: str,
        idempotency_key: str,
        created_at: datetime,
        logical_query_job_id: str,
        identity: ControlFileSetIdentity | None,
        receipt_error: str,
    ) -> PublishedControlFileSet:
        """One commit/receipt rule for two distinct QUERY file-set contracts."""
        if len(members) != 4 or members[1].file_name != "result.json":
            raise EmbeddingArtifactStoreError(receipt_error)
        publish = (
            self.publisher.publish
            if identity is None
            else partial(self.publisher.publish_identified, identity=identity)
        )
        receipt = publish(
            members=members,
            primary_file="result.json",
            artifact_type=artifact_type,
            manifest_version=CONTROL_FILE_SET_PROTOCOL,
            idempotency_key=idempotency_key,
            source_commit=self.source_commit,
            created_at=created_at,
        )
        try:
            if not isinstance(receipt, PublishedControlFileSet):
                raise ValueError("QUERY owner receipt type differs")
            TypeAdapter(JobId).validate_python(receipt.job_id)
            TypeAdapter(Sha256).validate_python(receipt.manifest_sha256)
            # Validate Artifact IDs even when the existing publisher allocated them.
            TypeAdapter(ArtifactId).validate_python(receipt.artifact_id, strict=True)
            TypeAdapter(RevisionId).validate_python(receipt.artifact_revision_id, strict=True)
            if (
                receipt.primary_file != "result.json"
                or receipt.primary_sha256 != members[1].sha256
                or (
                    identity is not None
                    and (
                        (receipt.job_id, receipt.artifact_id, receipt.artifact_revision_id)
                        != (identity.job_id, identity.artifact_id, identity.artifact_revision_id)
                        or receipt.job_id == logical_query_job_id
                    )
                )
            ):
                raise ValueError("QUERY owner receipt differs")
        except (ValueError, TypeError):
            raise EmbeddingArtifactStoreError(receipt_error) from None
        return receipt

    @staticmethod
    def _query_member_pointers(
        receipt: PublishedControlFileSet, members: tuple[ControlFileSetMember, ...]
    ) -> tuple[
        ArtifactMemberPointer, ArtifactMemberPointer, ArtifactMemberPointer, ArtifactMemberPointer
    ]:
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
        return pointers[0], pointers[1], pointers[2], pointers[3]

    def publish_private_chat_query(
        self,
        *,
        workflow_request: PrivateChatQueryWorkflowRequest,
        policy: PrivateChatQueryExecutionPolicy,
        bundle: EmbeddingRuntimeBundle,
        launch: PrivateChatQueryLaunchAssociation,
        request: EmbeddingPrivateChatQueryInput,
        workspace: Path,
        created_at: datetime,
        identity: ControlFileSetIdentity,
        expected_result_sha256: str,
    ) -> PublishedPrivateChatQueryArtifacts:
        """Commit text-free provenance and vectors, not another copy of the owned question.

        This store validates supplied values only. Actual owned-message/session,
        command/lease and native execution admission remain the calling owner's duty.
        """
        try:
            request = EmbeddingPrivateChatQueryInput.model_validate(
                raw_similarity_contract_value(request)
            )
            record = validate_private_chat_query_launch(
                launch, workflow_request, policy, bundle, request
            )
            TypeAdapter(Sha256).validate_python(expected_result_sha256, strict=True)
            if type(identity) is not ControlFileSetIdentity:
                raise ValueError("private QUERY publication identity differs")
            identity = ControlFileSetIdentity(
                TypeAdapter(JobId).validate_python(identity.job_id, strict=True),
                TypeAdapter(ArtifactId).validate_python(identity.artifact_id, strict=True),
                TypeAdapter(RevisionId).validate_python(identity.artifact_revision_id, strict=True),
            )
            if identity.job_id == request.job_id:
                raise ValueError("private QUERY publication identity differs")
            timestamp = TypeAdapter(UtcDatetime).validate_python(created_at, strict=True)
            if timestamp < record.launch.launched_at:
                raise ValueError("private QUERY publication precedes launch")
            input_bytes = canonical_json_bytes(request)
            intent_bytes = canonical_json_bytes(record)
        except (ValueError, TypeError, JsonSchemaValidationError):
            raise EmbeddingArtifactStoreError(
                "EMBEDDING_PRIVATE_CHAT_QUERY_CONTEXT_INVALID"
            ) from None
        key = "embedding-private-chat-query-artifact:" + content_sha256(
            {
                "logical_query_job_id": request.job_id,
                "native_request_sha256": request.request_sha256,
                "workflow_request_sha256": record.workflow_request.request_sha256,
                "launch_association_sha256": record.launch.association_sha256,
            }
        ).removeprefix("sha256:")
        with (
            _directory(workspace) as directory,
            _member(directory, "input.json", MAX_PRIVATE_CHAT_QUERY_BYTES) as saved_input,
            _member(directory, "result.json", MAX_PRIVATE_CHAT_QUERY_BYTES) as result_bytes,
            _member(
                directory, "vectors.f32", request.spaces.query.model_spec.dimension * 4
            ) as binary_bytes,
        ):
            if saved_input != input_bytes:
                raise EmbeddingArtifactStoreError("EMBEDDING_PRIVATE_CHAT_QUERY_INPUT_INVALID")
            try:
                result = EmbeddingPrivateChatQueryResult.model_validate(
                    json.loads(result_bytes, object_pairs_hook=_unique_object)
                )
                validate_private_chat_query_result(request, result)
                if (
                    result.result_sha256 != expected_result_sha256
                    or result_bytes != canonical_json_bytes(result)
                ):
                    raise ValueError("private QUERY actual result differs")
            except (ValueError, TypeError, JsonSchemaValidationError, RecursionError):
                raise EmbeddingArtifactStoreError(
                    "EMBEDDING_PRIVATE_CHAT_QUERY_RESULT_INVALID"
                ) from None
            shard = result.shard
            read_unit_vectors(
                binary_bytes,
                dimension=shard.dimension,
                row_count=1,
                expected_sha256=shard.binary.sha256,
            )
            shard_bytes = canonical_json_bytes(shard)
            _materialize_manifest(directory, "intent.json", intent_bytes)
            _materialize_manifest(directory, "shard.json", shard_bytes)
            with (
                _member(directory, "intent.json", 64 * 1024) as saved_intent,
                _member(directory, "shard.json", MAX_PRIVATE_CHAT_QUERY_BYTES) as saved_shard,
            ):
                if saved_intent != intent_bytes or saved_shard != shard_bytes:
                    raise EmbeddingArtifactStoreError(
                        "EMBEDDING_PRIVATE_CHAT_QUERY_MEMBER_CONFLICT"
                    )
                members = (
                    ControlFileSetMember(
                        "intent.json",
                        workspace / "intent.json",
                        sha256_bytes(saved_intent),
                        len(saved_intent),
                        PRIVATE_CHAT_QUERY_RECORD_REF,
                        "application/json",
                    ),
                    ControlFileSetMember(
                        "result.json",
                        workspace / "result.json",
                        sha256_bytes(result_bytes),
                        len(result_bytes),
                        PRIVATE_CHAT_QUERY_RESULT_REF,
                        "application/json",
                    ),
                    ControlFileSetMember(
                        "shard.json",
                        workspace / "shard.json",
                        sha256_bytes(saved_shard),
                        len(saved_shard),
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
                receipt = self._publish_query_members(
                    members=members,
                    artifact_type=EMBEDDING_PRIVATE_CHAT_QUERY_ARTIFACT_TYPE,
                    idempotency_key=key,
                    created_at=timestamp,
                    logical_query_job_id=request.job_id,
                    identity=identity,
                    receipt_error="EMBEDDING_PRIVATE_CHAT_QUERY_RECEIPT_INVALID",
                )
                pointers = self._query_member_pointers(receipt, members)
                return PublishedPrivateChatQueryArtifacts(
                    receipt.job_id, request.job_id, *pointers, receipt.manifest_sha256
                )

    def publish_index(
        self,
        *,
        index: SupportedEmbeddingIndex,
        shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...],
        previous: tuple[ArtifactMemberPointer, SupportedEmbeddingIndex] | None,
        scope: EmbeddingIndexPublicationScope,
        workspace: Path,
        identity: ControlFileSetIdentity | None = None,
    ) -> PublishedEmbeddingIndexArtifacts:
        """Commit one pinned metadata index; no source access, vectors or head mutation."""
        try:
            index = parse_supported_embedding_index(index)
            graph = TypeAdapter(KnowledgeGraphSnapshotPointer).validate_python(
                raw_similarity_contract_value(scope.graph_snapshot)
            )
            policy_revision_id: str = TypeAdapter(
                Annotated[str, Field(pattern=r"^accessrev_[0-9a-f]{32}$")]
            ).validate_python(scope.policy_revision_id)
            policy_sha256 = TypeAdapter(Sha256).validate_python(scope.policy_sha256)
            if (
                graph.manifest_artifact.sha256 != graph.manifest_sha256
                or not isinstance(shards, tuple)
                or not 1
                <= len(shards)
                <= (
                    MAX_PUBLIC_SOLUTION_SOURCES
                    if isinstance(
                        index, PublicSolutionEmbeddingIndex | PublicSolutionEmbeddingIndexV4
                    )
                    else MAX_EMBEDDING_ROWS
                )
                or any(not isinstance(value, tuple) or len(value) != 2 for value in shards)
                or (
                    previous is not None and (not isinstance(previous, tuple) or len(previous) != 2)
                )
                or any(
                    binding.graph_snapshot != graph
                    or binding.policy_revision_id != policy_revision_id
                    or binding.policy_sha256 != policy_sha256
                    for binding in index.bindings
                )
            ):
                raise ValueError("index publication frame or pinned scope differs")
            schema_ref = "eom://schemas/knowledge/" + index.schema_version
            validate_supported_embedding_index_references(index, shards, previous)
            timestamp = TypeAdapter(UtcDatetime).validate_python(index.created_at)
            payload = canonical_json_bytes(index.model_dump(mode="json"))
        except Exception:
            raise EmbeddingArtifactStoreError("EMBEDDING_INDEX_CONTEXT_INVALID") from None

        # Content belongs to the immutable request, not to a second same-revision key.
        key = "embedding-index-artifact:" + content_sha256(
            {"index_id": index.index_id, "index_revision_id": index.index_revision_id}
        ).removeprefix("sha256:")
        with _directory(workspace) as directory:
            _materialize_manifest(directory, EMBEDDING_INDEX_PRIMARY_MEMBER, payload)
            with _member(
                directory, EMBEDDING_INDEX_PRIMARY_MEMBER, MAX_EMBEDDING_INPUT_BYTES
            ) as saved:
                if saved != payload:
                    raise EmbeddingArtifactStoreError("EMBEDDING_INDEX_MEMBER_CONFLICT")
                member = ControlFileSetMember(
                    EMBEDDING_INDEX_PRIMARY_MEMBER,
                    workspace / EMBEDDING_INDEX_PRIMARY_MEMBER,
                    sha256_bytes(saved),
                    len(saved),
                    schema_ref,
                    "application/json",
                )
                publish = (
                    self.publisher.publish
                    if identity is None
                    else partial(self.publisher.publish_identified, identity=identity)
                )
                receipt = publish(
                    members=(member,),
                    primary_file=EMBEDDING_INDEX_PRIMARY_MEMBER,
                    artifact_type=EMBEDDING_INDEX_ARTIFACT_TYPE,
                    manifest_version=EMBEDDING_INDEX_MANIFEST_VERSION,
                    idempotency_key=key,
                    source_commit=self.source_commit,
                    created_at=timestamp,
                )
                try:
                    owner_job_id = TypeAdapter(JobId).validate_python(receipt.job_id)
                    manifest_sha256 = TypeAdapter(Sha256).validate_python(receipt.manifest_sha256)
                    if (
                        receipt.primary_file != EMBEDDING_INDEX_PRIMARY_MEMBER
                        or receipt.primary_sha256 != member.sha256
                        or (
                            identity is not None
                            and (receipt.job_id, receipt.artifact_id, receipt.artifact_revision_id)
                            != (
                                identity.job_id,
                                identity.artifact_id,
                                identity.artifact_revision_id,
                            )
                        )
                    ):
                        raise ValueError("index owner receipt differs")
                    pointer = ArtifactMemberPointer(
                        artifact_id=receipt.artifact_id,
                        artifact_revision_id=receipt.artifact_revision_id,
                        member_path=EMBEDDING_INDEX_PRIMARY_MEMBER,
                        schema_ref=schema_ref,
                        media_type="application/json",
                        sha256=member.sha256,
                    )
                    return PublishedEmbeddingIndexArtifacts(
                        owner_job_id,
                        index.index_id,
                        index.index_revision_id,
                        pointer,
                        index.index_sha256,
                        manifest_sha256,
                    )
                except Exception:
                    raise EmbeddingArtifactStoreError("EMBEDDING_INDEX_RECEIPT_INVALID") from None

    def stage_index_manifest(self, *, index: SupportedEmbeddingIndex, workspace: Path) -> None:
        """Fixed durable local materialization before its small checkpoint; no NAS write."""
        index = parse_supported_embedding_index(index)
        with _directory(workspace) as directory:
            _materialize_manifest(
                directory,
                EMBEDDING_INDEX_PRIMARY_MEMBER,
                canonical_json_bytes(index.model_dump(mode="json")),
            )

    def read_staged_index(self, *, workspace: Path, expected_sha256: str) -> EmbeddingIndexManifest:
        index = self._read_staged_index(workspace=workspace, expected_sha256=expected_sha256)
        if not isinstance(index, EmbeddingIndexManifest):
            raise EmbeddingArtifactStoreError("EMBEDDING_INDEX_CONTEXT_INVALID")
        return index

    def read_staged_mixed_index(
        self, *, workspace: Path, expected_sha256: str
    ) -> MixedEmbeddingIndexManifest:
        index = self._read_staged_index(workspace=workspace, expected_sha256=expected_sha256)
        if not isinstance(index, MixedEmbeddingIndexManifest):
            raise EmbeddingArtifactStoreError("EMBEDDING_INDEX_CONTEXT_INVALID")
        return index

    def read_staged_public_index(
        self, *, workspace: Path, expected_sha256: str
    ) -> PublicSolutionEmbeddingIndex:
        index = self._read_staged_index(workspace=workspace, expected_sha256=expected_sha256)
        if not isinstance(index, PublicSolutionEmbeddingIndex):
            raise EmbeddingArtifactStoreError("EMBEDDING_INDEX_CONTEXT_INVALID")
        return index

    def read_staged_registered_public_index(
        self, *, workspace: Path, expected_sha256: str
    ) -> PublicSolutionEmbeddingIndexV4:
        index = self._read_staged_index(
            workspace=workspace, expected_sha256=expected_sha256, maximum_bytes=64 * 1024**2
        )
        if not isinstance(index, PublicSolutionEmbeddingIndexV4):
            raise EmbeddingArtifactStoreError("EMBEDDING_INDEX_CONTEXT_INVALID")
        return index

    def _read_staged_index(
        self,
        *,
        workspace: Path,
        expected_sha256: str,
        maximum_bytes: int = MAX_EMBEDDING_INPUT_BYTES,
    ) -> SupportedEmbeddingIndex:
        """Read the exact checkpointed local bytes; never regenerate from current/latest."""
        with (
            _directory(workspace) as directory,
            _member(directory, EMBEDDING_INDEX_PRIMARY_MEMBER, maximum_bytes) as raw,
        ):
            if sha256_bytes(raw) != TypeAdapter(Sha256).validate_python(expected_sha256):
                raise EmbeddingArtifactStoreError("EMBEDDING_INDEX_MEMBER_CONFLICT")
            body = json.loads(raw)
            if canonical_json_bytes(body) != raw:
                raise EmbeddingArtifactStoreError("EMBEDDING_INDEX_MEMBER_CONFLICT")
            return parse_supported_embedding_index(body)

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
        return self._publish_result(
            request=request,
            workspace=workspace,
            timestamp=timestamp,
            publication_key="embedding-artifact:" + key,
        )

    def publish_owned_batch(
        self,
        *,
        workflow_request: SupportedLocalEmbeddingRequest,
        plan: SupportedLocalEmbeddingSourcePlan,
        policy: LocalEmbeddingExecutablePolicy,
        association: SupportedEmbeddingAssociation,
        request: IncrementalEmbeddingInput,
        workspace: Path,
        created_at: datetime,
    ) -> PublishedEmbeddingArtifacts:
        """Publish the separately owned subset while preserving the exact original intent.

        The current source/command owner authorizes this use case. Pure value
        checks here cannot replace that authority or establish launch provenance.
        """
        try:
            workflow_request = parse_supported_local_embedding_request(workflow_request)
            validate_supported_local_embedding_request_references(workflow_request, plan, policy)
            request = parse_incremental_embedding_input(request.model_dump(mode="json"))
            validate_supported_embedding_association(
                association,
                plan,
                request,
                workflow_request.resource_profile,
                workflow_request.request_sha256,
            )
            timestamp = TypeAdapter(UtcDatetime).validate_python(created_at)
        except Exception:
            raise EmbeddingArtifactStoreError("EMBEDDING_ARTIFACT_CONTEXT_INVALID") from None
        return self._publish_result(
            request=request,
            workspace=workspace,
            timestamp=timestamp,
            publication_key=owned_embedding_publication_key(
                association, workflow_request_sha256=workflow_request.request_sha256
            ),
        )

    def _publish_result(
        self,
        *,
        request: IncrementalEmbeddingInput,
        workspace: Path,
        timestamp: datetime,
        publication_key: str,
    ) -> PublishedEmbeddingArtifacts:
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
            _materialize_manifest(directory, "shard.json", shard_bytes)
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
                    artifact_type=EMBEDDING_RESULT_ARTIFACT_TYPE,
                    manifest_version="control-file-set/1.0",
                    idempotency_key=publication_key,
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
