"""Synthetic mixed metadata uses the existing owner, not NAS, vectors or model IO."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSourceBinding
from eom_catalog_contracts.mixed_embedding_index import (
    MIXED_EMBEDDING_INDEX_SCHEMA_REF,
    MixedEmbeddingIndexManifest,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.embedding_artifact_store import (
    EmbeddingArtifactStore,
    EmbeddingArtifactStoreError,
    EmbeddingIndexPublicationScope,
)
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher

from tests.unit.inference_transfer_embedding_fixtures import index_manifest, seal
from tests.unit.mixed_embedding_fixtures import mixed_embedding_case
from tests.unit.test_embedding_artifact_store import FakePublisher


def prepared(tmp_path: Path) -> tuple:
    _entry, review, shard, pointer, original = mixed_embedding_case()
    # The Artifact boundary requires one publication frame, but does not claim
    # this synthetic source/accepted-analysis/role provenance is authorized.
    bindings = []
    for binding in original.bindings:
        if isinstance(binding, EmbeddingSourceBinding):
            body = binding.model_dump(mode="json") | {
                "graph_snapshot": review.graph_snapshot.model_dump(mode="json"),
                "policy_revision_id": review.policy_revision_id,
                "policy_sha256": review.policy_sha256,
            }
            binding = EmbeddingSourceBinding.model_validate(seal(body, "binding_sha256"))
        bindings.append(binding)
    body = original.model_dump(mode="json") | {
        "bindings": [value.model_dump(mode="json") for value in bindings]
    }
    index = MixedEmbeddingIndexManifest.model_validate(seal(body, "index_sha256"))
    publisher = FakePublisher()
    store = EmbeddingArtifactStore(cast(ControlFileSetPublisher, publisher), source_commit="a" * 40)
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    scope = EmbeddingIndexPublicationScope(
        review.graph_snapshot, review.policy_revision_id, review.policy_sha256
    )
    return store, publisher, workspace, index, ((pointer, shard),), scope


def test_mixed_index_reuses_canonical_owner_and_internal_schema_pointer(tmp_path: Path) -> None:
    store, publisher, workspace, index, shards, scope = prepared(tmp_path)
    result = store.publish_index(
        index=index, shards=shards, previous=None, scope=scope, workspace=workspace
    )
    assert result.index_manifest.schema_ref == MIXED_EMBEDDING_INDEX_SCHEMA_REF
    assert result.index_manifest.sha256 == sha256_bytes(
        canonical_json_bytes(index.model_dump(mode="json"))
    )
    assert result.index_sha256 == index.index_sha256 != result.index_manifest.sha256
    assert tuple(path.name for path in workspace.iterdir()) == ("index.json",)
    assert (
        store.read_staged_mixed_index(
            workspace=workspace, expected_sha256=result.index_manifest.sha256
        )
        == index
    )
    assert publisher.calls[0]["members"][0].schema_ref == MIXED_EMBEDDING_INDEX_SCHEMA_REF
    with pytest.raises(EmbeddingArtifactStoreError):
        store.read_staged_index(workspace=workspace, expected_sha256=result.index_manifest.sha256)


def test_same_mixed_publication_replays_without_rewriting_local_member(tmp_path: Path) -> None:
    store, _publisher, workspace, index, shards, scope = prepared(tmp_path)
    arguments = dict(index=index, shards=shards, previous=None, scope=scope, workspace=workspace)
    first = store.publish_index(**arguments)
    initial = (workspace / "index.json").stat()
    assert store.publish_index(**arguments) == first
    final = (workspace / "index.json").stat()
    assert (initial.st_ino, initial.st_mtime_ns) == (final.st_ino, final.st_mtime_ns)


@pytest.mark.parametrize("fault", ("copied_extra", "wrong_scope", "missing_shard", "fake_parent"))
def test_mixed_context_failure_never_invokes_the_commit_owner(tmp_path: Path, fault: str) -> None:
    store, publisher, workspace, index, shards, scope = prepared(tmp_path)
    previous = None
    if fault == "copied_extra":
        index = index.model_copy(update={"undeclared": "forbidden"})
    elif fault == "wrong_scope":
        scope = replace(scope, policy_sha256="sha256:" + "f" * 64)
    elif fault == "missing_shard":
        shards = ()
    else:
        previous = (shards[0][0], index)
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_INDEX_CONTEXT_INVALID"):
        store.publish_index(
            index=index, shards=shards, previous=previous, scope=scope, workspace=workspace
        )
    assert publisher.calls == []
    assert tuple(workspace.iterdir()) == ()


def test_mixed_staging_reader_does_not_silently_upgrade_a_legacy_index(tmp_path: Path) -> None:
    store, _publisher, workspace, _index, _shards, _scope = prepared(tmp_path)
    legacy = index_manifest()
    store.stage_index_manifest(index=legacy, workspace=workspace)
    digest = sha256_bytes(canonical_json_bytes(legacy.model_dump(mode="json")))
    assert store.read_staged_index(workspace=workspace, expected_sha256=digest) == legacy
    with pytest.raises(EmbeddingArtifactStoreError):
        store.read_staged_mixed_index(workspace=workspace, expected_sha256=digest)


def test_mixed_staging_preserves_the_exact_schema2_bytes(tmp_path: Path) -> None:
    store, publisher, workspace, index, _shards, _scope = prepared(tmp_path)
    store.stage_index_manifest(index=index, workspace=workspace)
    payload = canonical_json_bytes(index.model_dump(mode="json"))
    assert (workspace / "index.json").read_bytes() == payload
    assert (
        store.read_staged_mixed_index(workspace=workspace, expected_sha256=sha256_bytes(payload))
        == index
    )
    assert publisher.calls == []
