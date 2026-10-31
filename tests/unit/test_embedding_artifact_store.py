"""Local synthetic file-set publication with a fake owner, never NAS/DB/model execution."""

from __future__ import annotations

import ast
import json
import os
import stat
import struct
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_contracts.embedding_vector_binary import EmbeddingVectorBinaryError
from eom_catalog_contracts.inference_transfer_embedding import (
    INPUT_SCHEMA_REF,
    RESULT_SCHEMA_REF,
    SHARD_SCHEMA_REF,
    EmbeddingVectorShardManifest,
    IncrementalEmbeddingInput,
    IncrementalEmbeddingResult,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.embedding_artifact_store import (
    EmbeddingArtifactStore,
    EmbeddingArtifactStoreError,
    PublishedEmbeddingArtifacts,
)
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
    PublishedControlFileSet,
)
from eom_workflow.local_embedding_workflow import LocalEmbeddingWorkflowRequest

from tests.unit.inference_transfer_embedding_fixtures import (
    embedding_input,
    embedding_result,
    embedding_space,
    seal,
    vector_shard,
)
from tests.unit.inference_transfer_fixtures import NOW, profile, sha

SOURCE_COMMIT = "a" * 40


class FakePublisher:
    """Pure test-local owner metadata: the lock models replay, not real DB concurrency."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.saved: dict[str, tuple[str, PublishedControlFileSet]] = {}
        self.lock = threading.Lock()
        self.receipt_updates: dict[str, Any] = {}
        self.before_return: Callable[[], None] | None = None

    def publish(self, **kwargs: Any) -> PublishedControlFileSet:
        with self.lock:
            self.calls.append(kwargs)
            members: tuple[ControlFileSetMember, ...] = kwargs["members"]
            for member in members:
                payload = member.source.read_bytes()
                assert len(payload) == member.bytes
                assert sha256_bytes(payload) == member.sha256
            metadata = {
                name: value
                for name, value in kwargs.items()
                if name not in {"members", "idempotency_key"}
            } | {
                "members": [
                    {
                        "file_name": member.file_name,
                        "sha256": member.sha256,
                        "bytes": member.bytes,
                        "schema_ref": member.schema_ref,
                        "media_type": member.media_type,
                    }
                    for member in members
                ]
            }
            fingerprint = content_sha256(metadata)
            key = kwargs["idempotency_key"]
            if key in self.saved:
                existing_hash, receipt = self.saved[key]
                if existing_hash != fingerprint:
                    raise EmbeddingArtifactStoreError("SYNTHETIC_SAME_KEY_CONFLICT")
            else:
                primary = next(
                    member for member in members if member.file_name == kwargs["primary_file"]
                )
                receipt = PublishedControlFileSet(
                    job_id="job_" + "9" * 32,
                    artifact_id="artifact_" + "a" * 32,
                    artifact_revision_id="rev_" + "b" * 32,
                    primary_file=primary.file_name,
                    primary_sha256=primary.sha256,
                    manifest_sha256=sha("c"),
                    nas_path="synthetic-owner-only-not-an-actual-storage-location",
                )
                self.saved[key] = (fingerprint, receipt)
            if self.before_return is not None:
                self.before_return()
            return replace(receipt, **self.receipt_updates)


@dataclass
class Prepared:
    store: EmbeddingArtifactStore
    publisher: FakePublisher
    request: IncrementalEmbeddingInput
    workflow_request: LocalEmbeddingWorkflowRequest
    result: IncrementalEmbeddingResult
    workspace: Path
    binary: bytes


def _write(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def _workflow_request(request: IncrementalEmbeddingInput) -> LocalEmbeddingWorkflowRequest:
    body = {
        "schema_version": "local-embedding-workflow-request/1.0",
        "request_name": "LOCAL_EMBEDDING_WORKFLOW_REQUEST",
        "workflow_definition_key": "local-embedding-index",
        "workflow_definition_version": "1.0.0",
        "requested_by_operator_id": "operator_" + "1" * 32,
        "requester_permissions_sha256": sha("2"),
        "graph_snapshot": profile().source_basis.graph_snapshot.model_dump(mode="json"),
        "access_policy_revision_id": "accessrev_" + "3" * 32,
        "access_policy_sha256": sha("3"),
        "space": request.space.model_dump(mode="json"),
        "input_artifact": {
            "artifact_id": "artifact_" + "4" * 32,
            "artifact_revision_id": "rev_" + "5" * 32,
            "member_path": "input.json",
            "schema_ref": INPUT_SCHEMA_REF,
            "media_type": "application/json",
            "sha256": content_sha256(request.model_dump(mode="json")),
        },
        "input_set_sha256": request.input_set_sha256,
    }
    return LocalEmbeddingWorkflowRequest.model_validate(seal(body, "request_sha256"))


def prepared(
    tmp_path: Path, *, publisher: FakePublisher | None = None, basis_index: int = 0
) -> Prepared:
    request = embedding_input("첫째 합성 입력: 마찰이 없다.", "둘째 합성 입력: 단위는 km/h이다.")
    dimension = request.space.model_spec.dimension
    row = tuple(1.0 if index == basis_index else 0.0 for index in range(dimension))
    binary = struct.pack(f"<{dimension * len(request.rows)}f", *(row * len(request.rows)))
    shard_body = vector_shard(tuple(value.encoding for value in request.rows)).model_dump(
        mode="json"
    )
    shard_body["binary"]["sha256"] = sha256_bytes(binary)
    shard = EmbeddingVectorShardManifest.model_validate(seal(shard_body, "shard_sha256"))
    result = embedding_result(request, shard=shard)
    tmp_path.mkdir(mode=0o700, exist_ok=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700, parents=True)
    workspace.chmod(0o700)
    _write(workspace / "result.json", canonical_json_bytes(result.model_dump(mode="json")))
    _write(workspace / "vectors.f32", binary)
    owner = publisher or FakePublisher()
    return Prepared(
        EmbeddingArtifactStore(cast(ControlFileSetPublisher, owner), source_commit=SOURCE_COMMIT),
        owner,
        request,
        _workflow_request(request),
        result,
        workspace,
        binary,
    )


def publish(value: Prepared, *, created_at: datetime = NOW) -> PublishedEmbeddingArtifacts:
    return value.store.publish(
        workflow_request=value.workflow_request,
        request=value.request,
        workspace=value.workspace,
        created_at=created_at,
    )


def _replace_binary(value: Prepared, payload: bytes, *, update_hash: bool) -> None:
    _write(value.workspace / "vectors.f32", payload)
    if update_hash:
        body = value.result.model_dump(mode="json")
        body["shard"]["binary"]["sha256"] = sha256_bytes(payload)
        body["shard"] = seal(body["shard"], "shard_sha256")
        value.result = IncrementalEmbeddingResult.model_validate(seal(body, "result_sha256"))
        _write(
            value.workspace / "result.json",
            canonical_json_bytes(value.result.model_dump(mode="json")),
        )


def test_exact_three_members_use_existing_owner_and_return_pinned_distinct_identities(
    tmp_path: Path,
) -> None:
    value = prepared(tmp_path)
    original = (value.workspace / "result.json").read_bytes()
    result = publish(value)
    assert result.logical_encoder_job_id == value.request.job_id
    assert result.owner_job_id != value.request.job_id
    assert result.owner_job_id == "job_" + "9" * 32
    assert result.manifest_sha256 == sha("c")
    assert {pointer.artifact_id for pointer in (result.result, result.shard, result.binary)} == {
        "artifact_" + "a" * 32
    }
    assert {
        pointer.artifact_revision_id for pointer in (result.result, result.shard, result.binary)
    } == {"rev_" + "b" * 32}
    assert result.result.sha256 == sha256_bytes(original)
    assert result.shard.sha256 == content_sha256(value.result.shard.model_dump(mode="json"))
    assert result.binary.sha256 == sha256_bytes(value.binary)
    assert result.result.schema_ref == RESULT_SCHEMA_REF
    assert result.shard.schema_ref == SHARD_SCHEMA_REF
    assert result.binary.media_type == "application/octet-stream"
    assert (value.workspace / "result.json").read_bytes() == original
    assert (value.workspace / "shard.json").read_bytes() == canonical_json_bytes(
        value.result.shard.model_dump(mode="json")
    )
    assert stat.S_IMODE((value.workspace / "shard.json").stat().st_mode) == 0o600
    call = value.publisher.calls[0]
    assert tuple(member.file_name for member in call["members"]) == (
        "result.json",
        "shard.json",
        "vectors.f32",
    )
    assert all("#" not in member.schema_ref for member in call["members"])
    assert all(isinstance(member, ControlFileSetMember) for member in call["members"])
    assert not any(isinstance(member, bytes) for member in call.values())
    assert call["source_commit"] == SOURCE_COMMIT and call["created_at"] == NOW
    assert call["primary_file"] == "result.json"
    expected_key = (
        "embedding-artifact:"
        + content_sha256(
            {
                "logical_encoder_job_id": value.request.job_id,
                "native_request_sha256": value.request.request_sha256,
                "workflow_request_sha256": value.workflow_request.request_sha256,
            }
        )[7:]
    )
    assert call["idempotency_key"] == expected_key


def test_identical_replay_and_preexisting_shard_preserve_exact_owner_result(tmp_path: Path) -> None:
    value = prepared(tmp_path)
    first = publish(value)
    stat_before = (value.workspace / "shard.json").stat()
    assert publish(value) == first
    stat_after = (value.workspace / "shard.json").stat()
    assert stat_before.st_ino == stat_after.st_ino
    assert stat_before.st_mtime_ns == stat_after.st_mtime_ns
    assert len(value.publisher.saved) == 1


def test_publisher_request_contains_only_small_metadata_and_file_pointers(tmp_path: Path) -> None:
    value = prepared(tmp_path)
    publish(value)
    call = value.publisher.calls[0]
    assert set(call) == {
        "members",
        "primary_file",
        "artifact_type",
        "manifest_version",
        "idempotency_key",
        "source_commit",
        "created_at",
    }
    members = tuple(asdict(member) for member in call["members"])
    assert all(
        set(member) == {"file_name", "source", "sha256", "bytes", "schema_ref", "media_type"}
        for member in members
    )
    texts = tuple(row.text for row in value.request.rows)

    def assert_metadata_only(candidate: Any) -> None:
        assert not isinstance(candidate, (bytes, bytearray, memoryview))
        if isinstance(candidate, dict):
            for key, nested in candidate.items():
                assert_metadata_only(key)
                assert_metadata_only(nested)
        elif isinstance(candidate, (tuple, list)):
            for nested in candidate:
                assert_metadata_only(nested)
        elif isinstance(candidate, str):
            assert all(text not in candidate for text in texts)

    assert_metadata_only(call | {"members": members})


def test_store_source_has_no_parallel_database_network_process_or_git_boundary() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "services/orchestrator/eom_orchestrator/embedding_artifact_store.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        name
        for node in ast.walk(tree)
        for name in (
            tuple(alias.name for alias in node.names)
            if isinstance(node, ast.Import)
            else (node.module,)
            if isinstance(node, ast.ImportFrom)
            else ()
        )
    }
    assert imports <= {
        "__future__",
        "fcntl",  # existing local file-set lock, not another execution boundary
        "json",
        "os",
        "re",
        "stat",
        "collections.abc",
        "contextlib",
        "dataclasses",
        "datetime",
        "functools",  # bind an exact typed publisher identity; no new side-effect boundary
        "pathlib",
        "typing",
        "eom_catalog_contracts.embedding_reference_query",
        "eom_catalog_contracts.embedding_private_chat_query",
        "eom_catalog_contracts.embedding_reference_query_v11",
        "eom_catalog_contracts.embedding_runtime_bundle",
        "eom_catalog_contracts.embedding_index_families",
        "eom_catalog_contracts.embedding_vector_binary",
        "eom_catalog_contracts.inference_transfer_embedding",
        "eom_catalog_contracts.mixed_embedding_index",
        "eom_catalog_contracts.public_solution_embedding_index",
        "eom_catalog_contracts.public_solution_query",
        "eom_catalog_contracts.registered_public_solution_index",
        "eom_catalog_contracts.knowledge",
        "eom_catalog_contracts.models",
        "eom_identifiers",
        "eom_protocol.artifact_members",
        "eom_protocol.models",
        "eom_workflow.local_embedding_workflow",
        "eom_workflow.local_embedding_encoding_job",
        "eom_workflow.local_embedding_encoding_dispatch",
        "eom_workflow.local_embedding_execution_policy",
        "eom_workflow.local_embedding_request",
        "eom_workflow.local_embedding_request_v2",
        "eom_workflow.local_embedding_source_plan",
        "eom_workflow.local_embedding_source_plan_v2",
        "eom_workflow.local_embedding_source_plan_dispatch",
        "eom_workflow.reference_query_execution",
        "eom_workflow.private_chat_query_execution",
        "eom_workflow.private_chat_query_publication",
        "jsonschema.exceptions",
        "pydantic",
        "eom_orchestrator.file_set_control_artifacts",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in {"__import__", "eval", "exec"}
            elif isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"execute", "connect", "system", "popen", "spawn"}
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value != "git" and not node.value.startswith("git ")


def test_concurrent_replay_uses_one_fake_owner_identity_not_duplicate_artifacts(
    tmp_path: Path,
) -> None:
    value = prepared(tmp_path)
    _write(
        value.workspace / "shard.json",
        canonical_json_bytes(value.result.shard.model_dump(mode="json")),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _ordinal: publish(value), range(2)))
    assert results[0] == results[1]
    assert len(value.publisher.saved) == 1


def test_same_key_changed_numeric_result_is_conflict_not_replacement(tmp_path: Path) -> None:
    first = prepared(tmp_path / "first")
    result = publish(first)
    changed = prepared(tmp_path / "changed", publisher=first.publisher, basis_index=1)
    assert changed.request == first.request
    assert changed.workflow_request == first.workflow_request
    with pytest.raises(EmbeddingArtifactStoreError, match="SYNTHETIC_SAME_KEY_CONFLICT"):
        publish(changed)
    assert len(first.publisher.saved) == 1
    assert publish(first) == result


@pytest.mark.parametrize(
    "field", ["input_hash", "space", "input_set", "forged_request", "forged_workflow"]
)
def test_context_drift_or_model_copy_forgery_rejects_before_publisher(
    tmp_path: Path, field: str
) -> None:
    value = prepared(tmp_path)
    body = value.workflow_request.model_dump(mode="json")
    if field == "input_hash":
        body["input_artifact"]["sha256"] = sha("f")
    elif field == "space":
        body["space"] = embedding_space(device="CUDA").model_dump(mode="json")
    elif field == "input_set":
        body["input_set_sha256"] = sha("f")
    elif field == "forged_request":
        value.request = value.request.model_copy(update={"request_sha256": sha("f")})
    else:
        value.workflow_request = value.workflow_request.model_copy(
            update={"request_sha256": sha("f")}
        )
    if field in {"input_hash", "space", "input_set"}:
        value.workflow_request = LocalEmbeddingWorkflowRequest.model_validate(
            seal(body, "request_sha256")
        )
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_ARTIFACT_CONTEXT_INVALID"):
        publish(value)
    assert value.publisher.calls == []


@pytest.mark.parametrize(
    "field,value", [("job_id", "job_" + "f" * 32), ("request_sha256", sha("f"))]
)
def test_validly_hashed_result_must_match_exact_native_request(
    tmp_path: Path, field: str, value: str
) -> None:
    fixture = prepared(tmp_path)
    body = fixture.result.model_dump(mode="json") | {field: value}
    _write(fixture.workspace / "result.json", canonical_json_bytes(seal(body, "result_sha256")))
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_ARTIFACT_RESULT_INVALID"):
        publish(fixture)
    assert fixture.publisher.calls == []


@pytest.mark.parametrize("mutation", ["newline", "leading_space", "duplicate", "invalid_json"])
def test_noncanonical_or_duplicate_result_json_is_not_repaired(
    tmp_path: Path, mutation: str
) -> None:
    value = prepared(tmp_path)
    original = (value.workspace / "result.json").read_bytes()
    payload = {
        "newline": original + b"\n",
        "leading_space": b" " + original,
        "duplicate": b'{"job_id":'
        + json.dumps(value.request.job_id).encode()
        + b","
        + original[1:],
        "invalid_json": b'{"secret-shaped-input":',
    }[mutation]
    _write(value.workspace / "result.json", payload)
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_ARTIFACT_RESULT_INVALID"):
        publish(value)
    assert value.publisher.calls == []
    assert (value.workspace / "result.json").read_bytes() == payload


@pytest.mark.parametrize(
    "field,invalid",
    [
        ("primary_file", "shard.json"),
        ("primary_sha256", sha("f")),
        ("manifest_sha256", "not-a-hash"),
        ("job_id", "job_" + "a" * 31),
        ("artifact_id", "artifact_" + "a" * 31),
        ("artifact_revision_id", "rev_" + "a" * 31),
        ("job_id", "job_" + "1" * 32),
    ],
)
def test_invalid_owner_receipt_never_becomes_valid_pointer(
    tmp_path: Path, field: str, invalid: str
) -> None:
    value = prepared(tmp_path)
    value.publisher.receipt_updates[field] = invalid
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_ARTIFACT_RECEIPT_INVALID"):
        publish(value)
    assert len(value.publisher.calls) == 1


def test_null_publisher_receipt_is_explicit_failure(tmp_path: Path) -> None:
    class NullReceiptPublisher(FakePublisher):
        def publish(self, **kwargs: Any) -> PublishedControlFileSet:
            super().publish(**kwargs)
            return cast(PublishedControlFileSet, None)

    value = prepared(tmp_path, publisher=NullReceiptPublisher())
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_ARTIFACT_RECEIPT_INVALID"):
        publish(value)
    assert len(value.publisher.calls) == 1


@pytest.mark.parametrize("name", ["result.json", "vectors.f32"])
@pytest.mark.parametrize("failure", ["missing", "symlink", "hardlink", "mode", "directory"])
def test_source_members_require_regular_private_single_link_files(
    tmp_path: Path, name: str, failure: str
) -> None:
    value = prepared(tmp_path)
    source = value.workspace / name
    if failure == "missing":
        source.unlink()
    elif failure == "symlink":
        preserved = tmp_path / "preserved-member"
        source.rename(preserved)
        source.symlink_to(preserved)
    elif failure == "hardlink":
        os.link(source, tmp_path / "second-link")
    elif failure == "mode":
        source.chmod(0o640)
    else:
        source.unlink()
        source.mkdir(mode=0o700)
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_ARTIFACT_MEMBER_INVALID"):
        publish(value)
    assert value.publisher.calls == []


@pytest.mark.parametrize("failure", ["mode", "symlink", "relative"])
def test_workspace_requires_private_owned_no_follow_absolute_directory(
    tmp_path: Path, failure: str
) -> None:
    value = prepared(tmp_path)
    if failure == "mode":
        value.workspace.chmod(0o750)
    elif failure == "symlink":
        preserved = tmp_path / "preserved-workspace"
        value.workspace.rename(preserved)
        value.workspace.symlink_to(preserved, target_is_directory=True)
    else:
        value.workspace = Path("relative-workspace")
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_ARTIFACT_WORKSPACE_INVALID"):
        publish(value)
    assert value.publisher.calls == []


def test_foreign_file_ownership_is_rejected_without_changing_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = prepared(tmp_path)
    real_fstat = os.fstat

    def foreign_stat(descriptor: int) -> os.stat_result:
        actual = real_fstat(descriptor)
        if stat.S_ISREG(actual.st_mode):
            return cast(
                os.stat_result,
                SimpleNamespace(
                    **{
                        name: getattr(actual, name)
                        for name in dir(actual)
                        if name.startswith("st_")
                    }
                    | {"st_uid": os.geteuid() + 1}
                ),
            )
        return actual

    monkeypatch.setattr(os, "fstat", foreign_stat)
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_ARTIFACT_MEMBER_INVALID"):
        publish(value)
    assert value.publisher.calls == []


@pytest.mark.parametrize("failure", ["hash", "length", "zero", "nonunit", "nan"])
def test_binary_hash_shape_and_unit_values_are_validated_not_normalized(
    tmp_path: Path, failure: str
) -> None:
    value = prepared(tmp_path)
    element_count = value.result.shard.dimension * value.result.shard.row_count
    payload = (
        value.binary[:-4]
        if failure == "length"
        else struct.pack(
            f"<{element_count}f",
            *([float("nan")] * element_count if failure == "nan" else [0.0] * element_count),
        )
    )
    if failure in {"hash", "nonunit"}:
        payload = struct.pack(f"<{element_count}f", 2.0, *([0.0] * (element_count - 1)))
    _replace_binary(value, payload, update_hash=failure != "hash")
    with pytest.raises(EmbeddingVectorBinaryError):
        publish(value)
    assert value.publisher.calls == []
    assert (value.workspace / "vectors.f32").read_bytes() == payload


def test_conflicting_existing_shard_is_not_overwritten_or_published(tmp_path: Path) -> None:
    value = prepared(tmp_path)
    conflicting = canonical_json_bytes(value.result.shard.model_dump(mode="json")) + b"\n"
    _write(value.workspace / "shard.json", conflicting)
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_ARTIFACT_SHARD_CONFLICT"):
        publish(value)
    assert value.publisher.calls == []
    assert (value.workspace / "shard.json").read_bytes() == conflicting


def test_member_replaced_during_read_fails_fd_and_named_identity_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = prepared(tmp_path)
    real_read = os.read
    changed = False

    def replacement_read(descriptor: int, amount: int) -> bytes:
        nonlocal changed
        payload = real_read(descriptor, amount)
        if payload and not changed:
            changed = True
            original = value.workspace / "result.json"
            original.rename(tmp_path / "preserved-result")
            _write(original, canonical_json_bytes(value.result.model_dump(mode="json")))
        return payload

    monkeypatch.setattr(os, "read", replacement_read)
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_ARTIFACT_MEMBER_CHANGED"):
        publish(value)
    assert value.publisher.calls == []


def test_member_epoch_changed_during_publication_rejects_returned_receipt(tmp_path: Path) -> None:
    value = prepared(tmp_path)
    value.publisher.before_return = lambda: (value.workspace / "vectors.f32").chmod(0o640)
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_ARTIFACT_MEMBER_CHANGED"):
        publish(value)
    assert len(value.publisher.calls) == 1


def test_workspace_replaced_during_publication_is_not_adopted(tmp_path: Path) -> None:
    value = prepared(tmp_path)

    def replace_workspace() -> None:
        value.workspace.rename(tmp_path / "preserved-workspace")
        value.workspace.mkdir(mode=0o700)

    value.publisher.before_return = replace_workspace
    with pytest.raises(EmbeddingArtifactStoreError):
        publish(value)
    assert len(value.publisher.calls) == 1


@pytest.mark.parametrize("source_commit", ["a" * 39, "A" * 40, "main"])
def test_installed_source_pin_is_required(source_commit: str) -> None:
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_ARTIFACT_SOURCE_INVALID"):
        EmbeddingArtifactStore(
            cast(ControlFileSetPublisher, FakePublisher()), source_commit=source_commit
        )


@pytest.mark.parametrize(
    "created_at",
    [datetime(2026, 10, 12), datetime(2026, 10, 12, tzinfo=timezone(timedelta(hours=9)))],
)
def test_system_timestamp_must_be_aware_utc_before_publication(
    tmp_path: Path, created_at: datetime
) -> None:
    value = prepared(tmp_path)
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_ARTIFACT_CONTEXT_INVALID"):
        publish(value, created_at=created_at)
    assert value.publisher.calls == []
