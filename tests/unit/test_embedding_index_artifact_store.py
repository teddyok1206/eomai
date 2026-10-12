"""Synthetic index metadata publication; no source authority, DB, NAS or inference."""

from __future__ import annotations

import errno
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_contracts.inference_transfer_embedding import (
    INDEX_SCHEMA_REF,
    EmbeddingIndexManifest,
    EmbeddingSourceBinding,
    EmbeddingVectorShardManifest,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator import embedding_artifact_store as module
from eom_orchestrator.embedding_artifact_store import (
    EMBEDDING_INDEX_ARTIFACT_TYPE,
    EMBEDDING_INDEX_MANIFEST_VERSION,
    EMBEDDING_INDEX_MEMBER_NAMES,
    EMBEDDING_INDEX_PRIMARY_MEMBER,
    EmbeddingArtifactStore,
    EmbeddingArtifactStoreError,
    EmbeddingIndexPublicationScope,
    PublishedEmbeddingIndexArtifacts,
)
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetPublisher,
    PublishedControlFileSet,
)
from eom_protocol.artifact_members import ArtifactMemberPointer

from tests.unit.inference_transfer_embedding_fixtures import (
    index_manifest,
    index_pointer,
    seal,
    source_binding,
    vector_shard,
)
from tests.unit.inference_transfer_fixtures import NOW, sha
from tests.unit.test_embedding_artifact_store import FakePublisher

SOURCE_COMMIT = "a" * 40


@dataclass
class PreparedIndex:
    store: EmbeddingArtifactStore
    publisher: FakePublisher
    index: EmbeddingIndexManifest
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...]
    previous: tuple[ArtifactMemberPointer, EmbeddingIndexManifest] | None
    scope: EmbeddingIndexPublicationScope
    workspace: Path


def prepared(tmp_path: Path, *, publisher: FakePublisher | None = None) -> PreparedIndex:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp_path.chmod(0o700)
    binding = source_binding()
    index = index_manifest(binding)
    shard = vector_shard((binding.encoding,), space=index.space)
    owner = publisher or FakePublisher()
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    return PreparedIndex(
        EmbeddingArtifactStore(cast(ControlFileSetPublisher, owner), source_commit=SOURCE_COMMIT),
        owner,
        index,
        ((binding.row_ref.shard_manifest, shard),),
        None,
        EmbeddingIndexPublicationScope(
            binding.graph_snapshot, binding.policy_revision_id, binding.policy_sha256
        ),
        workspace,
    )


def publish(value: PreparedIndex) -> PublishedEmbeddingIndexArtifacts:
    return value.store.publish_index(
        index=value.index,
        shards=value.shards,
        previous=value.previous,
        scope=value.scope,
        workspace=value.workspace,
    )


def _write(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def _index_update(index: EmbeddingIndexManifest, **updates: Any) -> EmbeddingIndexManifest:
    return EmbeddingIndexManifest.model_validate(
        seal(index.model_dump(mode="json") | updates, "index_sha256")
    )


def test_index_is_sole_fixed_member_and_receipt_keeps_all_identities_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = prepared(tmp_path)

    def no_vectors(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("index publication must not materialize numerical vectors")

    monkeypatch.setattr(module, "read_unit_vectors", no_vectors)
    receipt = publish(value)
    payload = canonical_json_bytes(value.index.model_dump(mode="json"))
    assert isinstance(receipt, PublishedEmbeddingIndexArtifacts)
    assert receipt.owner_job_id.startswith("job_")
    assert receipt.index_id == value.index.index_id
    assert receipt.index_revision_id == value.index.index_revision_id
    assert (
        len(
            {
                receipt.owner_job_id,
                receipt.index_id,
                receipt.index_revision_id,
                receipt.index_manifest.artifact_id,
                receipt.index_manifest.artifact_revision_id,
            }
        )
        == 5
    )
    assert receipt.index_manifest.member_path == EMBEDDING_INDEX_PRIMARY_MEMBER == "index.json"
    assert receipt.index_manifest.schema_ref == INDEX_SCHEMA_REF
    assert receipt.index_manifest.media_type == "application/json"
    assert receipt.index_manifest.sha256 == sha256_bytes(payload)
    assert receipt.index_sha256 == value.index.index_sha256 != receipt.index_manifest.sha256
    assert receipt.manifest_sha256 == sha("c")
    assert set(path.name for path in value.workspace.iterdir()) == {"index.json"}
    assert (value.workspace / "index.json").read_bytes() == payload
    assert stat.S_IMODE((value.workspace / "index.json").stat().st_mode) == 0o600
    call = value.publisher.calls[0]
    assert call["artifact_type"] == EMBEDDING_INDEX_ARTIFACT_TYPE == "control_embedding_index"
    assert call["manifest_version"] == EMBEDDING_INDEX_MANIFEST_VERSION == "control-file-set/1.0"
    assert tuple(member.file_name for member in call["members"]) == EMBEDDING_INDEX_MEMBER_NAMES
    assert call["primary_file"] == "index.json"
    assert call["created_at"] == value.index.created_at and call["source_commit"] == SOURCE_COMMIT
    assert (
        call["idempotency_key"]
        == "embedding-index-artifact:"
        + content_sha256(
            {"index_id": value.index.index_id, "index_revision_id": value.index.index_revision_id}
        )[7:]
    )
    assert set(call) == {
        "members",
        "primary_file",
        "artifact_type",
        "manifest_version",
        "idempotency_key",
        "source_commit",
        "created_at",
    }
    with pytest.raises(FrozenInstanceError):
        cast(Any, receipt).index_id = "changed"
    with pytest.raises(FrozenInstanceError):
        cast(Any, value.scope).policy_sha256 = sha("f")


def test_replay_preserves_one_materialization_and_publisher_identity(tmp_path: Path) -> None:
    value = prepared(tmp_path)
    first = publish(value)
    before = (value.workspace / "index.json").stat()
    assert publish(value) == first
    after = (value.workspace / "index.json").stat()
    assert (before.st_ino, before.st_mtime_ns, before.st_size) == (
        after.st_ino,
        after.st_mtime_ns,
        after.st_size,
    )
    assert len(value.publisher.saved) == 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert tuple(pool.map(lambda ordinal: publish(value), range(2))) == (first, first)


@pytest.mark.parametrize("changed", ["timestamp", "source_commit", "policy"])
def test_changed_same_revision_intent_conflicts_under_original_key(
    tmp_path: Path, changed: str
) -> None:
    value = prepared(tmp_path / "first")
    first = publish(value)
    successor = prepared(tmp_path / "changed", publisher=value.publisher)
    if changed == "timestamp":
        successor.index = _index_update(
            successor.index,
            created_at=(NOW + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        )
    elif changed == "source_commit":
        successor.store = EmbeddingArtifactStore(
            cast(ControlFileSetPublisher, value.publisher), source_commit="b" * 40
        )
    else:
        binding = EmbeddingSourceBinding.model_validate(
            seal(
                successor.index.bindings[0].model_dump(mode="json") | {"policy_sha256": sha("f")},
                "binding_sha256",
            )
        )
        successor.index = index_manifest(binding)
        successor.scope = replace(successor.scope, policy_sha256=sha("f"))
    with pytest.raises(EmbeddingArtifactStoreError, match="SYNTHETIC_SAME_KEY_CONFLICT"):
        publish(successor)
    assert (
        value.publisher.calls[0]["idempotency_key"] == value.publisher.calls[-1]["idempotency_key"]
    )
    assert len(value.publisher.saved) == 1 and publish(value) == first


@pytest.mark.parametrize(
    "invalid",
    [
        "scope_revision",
        "scope_hash",
        "scope_graph",
        "forged_graph",
        "forged_index",
        "missing_shards",
        "duplicate_shard",
        "large_frame",
        "missing_row",
        "changed_shard",
        "initial_previous",
        "missing_previous",
        "changed_previous",
    ],
)
def test_exact_scope_shard_row_and_predecessor_closure_fails_before_publication(
    tmp_path: Path, invalid: str
) -> None:
    value = prepared(tmp_path)
    if invalid == "scope_revision":
        value.scope = replace(value.scope, policy_revision_id="accessrev_" + "f" * 32)
    elif invalid == "scope_hash":
        value.scope = replace(value.scope, policy_sha256="not-a-hash")
    elif invalid in {"scope_graph", "forged_graph"}:
        field = "graph_id" if invalid == "scope_graph" else "manifest_sha256"
        candidate = "graph_" + "f" * 32 if field == "graph_id" else sha("f")
        value.scope = replace(
            value.scope,
            graph_snapshot=value.scope.graph_snapshot.model_copy(update={field: candidate}),
        )
    elif invalid == "forged_index":
        value.index = value.index.model_copy(update={"index_sha256": sha("f")})
    elif invalid == "missing_shards":
        value.shards = ()
    elif invalid == "duplicate_shard":
        value.shards *= 2
    elif invalid == "large_frame":
        value.shards *= 1025
    elif invalid == "missing_row":
        binding = value.index.bindings[0]
        row_ref = binding.row_ref.model_dump(mode="json") | {"row_index": 999}
        binding = EmbeddingSourceBinding.model_validate(
            seal(binding.model_dump(mode="json") | {"row_ref": row_ref}, "binding_sha256")
        )
        value.index = index_manifest(binding)
    elif invalid == "changed_shard":
        pointer, shard = value.shards[0]
        value.shards = ((pointer.model_copy(update={"sha256": sha("f")}), shard),)
    else:
        parent = index_manifest(revision_seed="1")
        pointer = index_pointer(parent)
        value.previous = (pointer, parent)
        if invalid != "initial_previous":
            value.index = index_manifest(previous_manifest=pointer)
        if invalid == "missing_previous":
            value.previous = None
        elif invalid == "changed_previous":
            value.previous = (pointer, parent.model_copy(update={"index_sha256": sha("f")}))
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_INDEX_CONTEXT_INVALID"):
        publish(value)
    assert value.publisher.calls == []
    assert not (value.workspace / "index.json").exists()


def test_exact_predecessor_is_retained_without_latest_resolution(tmp_path: Path) -> None:
    value = prepared(tmp_path)
    parent = index_manifest(revision_seed="1")
    pointer = index_pointer(parent)
    value.index = index_manifest(previous_manifest=pointer)
    value.previous = (pointer, parent)
    assert publish(value).index_revision_id == value.index.index_revision_id
    assert value.index.previous_manifest == pointer


@pytest.mark.parametrize("payload", [b"", b"{", b"{}", b"{}\n"])
def test_partial_or_conflicting_preexisting_index_is_never_overwritten(
    tmp_path: Path, payload: bytes
) -> None:
    value = prepared(tmp_path)
    path = value.workspace / "index.json"
    _write(path, payload)
    before = path.stat()
    with pytest.raises(EmbeddingArtifactStoreError):
        publish(value)
    assert path.read_bytes() == payload and path.stat().st_ino == before.st_ino
    assert value.publisher.calls == []


@pytest.mark.parametrize(
    "invalid", ["mode", "symlink", "hardlink", "fifo", "foreign_owner", "oversized"]
)
def test_index_file_admission_is_private_regular_single_link_and_owned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    value = prepared(tmp_path)
    path = value.workspace / "index.json"
    _write(path, canonical_json_bytes(value.index.model_dump(mode="json")))
    if invalid == "mode":
        path.chmod(0o644)
    elif invalid == "symlink":
        path.rename(tmp_path / "preserved-index")
        path.symlink_to(tmp_path / "preserved-index")
    elif invalid == "hardlink":
        os.link(path, tmp_path / "hardlink")
    elif invalid == "fifo":
        path.rename(tmp_path / "preserved-index")
        os.mkfifo(path, mode=0o600)
    else:
        original = os.fstat

        def foreign_stat(descriptor: int) -> os.stat_result:
            actual = original(descriptor)
            if stat.S_ISREG(actual.st_mode):
                return cast(
                    os.stat_result,
                    SimpleNamespace(
                        **{
                            name: getattr(actual, name)
                            for name in dir(actual)
                            if name.startswith("st_")
                        }
                        | (
                            {"st_uid": os.geteuid() + 1}
                            if invalid == "foreign_owner"
                            else {"st_size": 64 * 1024**2 + 1}
                        )
                    ),
                )
            return actual

        monkeypatch.setattr(os, "fstat", foreign_stat)
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_ARTIFACT_MEMBER_INVALID"):
        publish(value)
    assert value.publisher.calls == []


@pytest.mark.parametrize("invalid", ["private_mode", "symlink", "relative"])
def test_index_workspace_admission_is_the_existing_owner_boundary(
    tmp_path: Path, invalid: str
) -> None:
    value = prepared(tmp_path)
    if invalid == "private_mode":
        value.workspace.chmod(0o750)
    elif invalid == "relative":
        value.workspace = Path("relative-index-workspace")
    else:
        value.workspace.rename(tmp_path / "preserved-workspace")
        value.workspace.symlink_to(tmp_path / "preserved-workspace", target_is_directory=True)
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_ARTIFACT_WORKSPACE_INVALID"):
        publish(value)
    assert value.publisher.calls == []


@pytest.mark.parametrize(
    "field,invalid",
    [
        ("primary_file", "result.json"),
        ("primary_sha256", sha("f")),
        ("manifest_sha256", "invalid"),
        ("job_id", "embeddingindex_" + "1" * 32),
        ("artifact_id", "invalid"),
        ("artifact_revision_id", "invalid"),
    ],
)
def test_invalid_owner_receipt_does_not_become_an_index_pointer(
    tmp_path: Path, field: str, invalid: str
) -> None:
    value = prepared(tmp_path)
    value.publisher.receipt_updates[field] = invalid
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_INDEX_RECEIPT_INVALID"):
        publish(value)
    assert len(value.publisher.saved) == 1  # Failure is not proof that publication never happened.


def test_named_inode_replacement_during_read_is_rejected_before_publisher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = prepared(tmp_path)
    original_read = os.read
    changed = False

    def replace_during_read(descriptor: int, amount: int) -> bytes:
        nonlocal changed
        raw = original_read(descriptor, amount)
        if raw and not changed:
            changed = True
            path = value.workspace / "index.json"
            path.rename(tmp_path / "preserved-index")
            _write(path, raw)
        return raw

    monkeypatch.setattr(os, "read", replace_during_read)
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_ARTIFACT_MEMBER_CHANGED"):
        publish(value)
    assert value.publisher.calls == []


def test_member_descriptor_is_retained_through_publication_and_closed_afterwards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = prepared(tmp_path)
    original_open = os.open
    descriptors: set[int] = set()

    def tracked_open(*args: Any, **kwargs: Any) -> int:
        descriptor = original_open(*args, **kwargs)
        descriptors.add(descriptor)
        return descriptor

    def check_held_member() -> None:
        assert any(stat.S_ISREG(os.fstat(fd).st_mode) for fd in descriptors)

    monkeypatch.setattr(os, "open", tracked_open)
    value.publisher.before_return = check_held_member
    publish(value)
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


@pytest.mark.parametrize("changed", ["file_mode", "workspace"])
def test_epoch_drift_after_simulated_commit_is_failure_not_uncommitted_claim(
    tmp_path: Path, changed: str
) -> None:
    value = prepared(tmp_path)

    def mutate() -> None:
        if changed == "file_mode":
            (value.workspace / "index.json").chmod(0o640)
        else:
            value.workspace.rename(tmp_path / "preserved-workspace")
            value.workspace.mkdir(mode=0o700)

    value.publisher.before_return = mutate
    with pytest.raises(EmbeddingArtifactStoreError):
        publish(value)
    assert len(value.publisher.saved) == 1


def test_partial_write_preserved_and_all_retained_descriptors_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = prepared(tmp_path)
    original_open, original_write = os.open, os.write
    descriptors: list[int] = []

    def tracked_open(*args: Any, **kwargs: Any) -> int:
        descriptor = original_open(*args, **kwargs)
        descriptors.append(descriptor)
        return descriptor

    def short_then_failed_write(descriptor: int, payload: Any) -> int:
        original_write(descriptor, payload[:7])
        raise OSError(errno.ENOSPC, "synthetic write failure")

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "write", short_then_failed_write)
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_ARTIFACT_MEMBER_WRITE_FAILED"):
        publish(value)
    assert (value.workspace / "index.json").read_bytes() == canonical_json_bytes(
        value.index.model_dump(mode="json")
    )[:7]
    assert value.publisher.calls == []
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    monkeypatch.setattr(os, "write", original_write)
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_INDEX_MEMBER_CONFLICT"):
        publish(value)


@pytest.mark.parametrize("phase", ["before", "after"])
def test_publisher_failure_recovery_is_same_pointer_without_reencode(
    tmp_path: Path, phase: str
) -> None:
    class FailingPublisher(FakePublisher):
        failure: str | None = phase

        def publish(self, **kwargs: Any) -> PublishedControlFileSet:
            if self.failure == "before":
                raise RuntimeError("synthetic precommit failure")
            receipt = super().publish(**kwargs)
            if self.failure == "after":
                raise RuntimeError("synthetic postcommit failure")
            return receipt

    owner = FailingPublisher()
    value = prepared(tmp_path, publisher=owner)
    with pytest.raises(RuntimeError):
        publish(value)
    before = (value.workspace / "index.json").stat()
    owner.failure = None
    receipt = publish(value)
    assert publish(value) == receipt and len(owner.saved) == 1
    assert (value.workspace / "index.json").stat().st_ino == before.st_ino
