"""Native1.1 owned result publication through the existing test-local Artifact owner."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from eom_catalog_service.embedding_encoder_adapter import encode_incremental_batch
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.embedding_artifact_store import (
    EmbeddingArtifactStore,
    EmbeddingArtifactStoreError,
)
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher

from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.local_embedding_admission_fixtures import native_fixture
from tests.unit.test_embedding_artifact_store import FakePublisher
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend


def test_owned_subset_can_publish_replay_and_preserve_original_plan(tmp_path: Path) -> None:
    fixture = native_fixture("a", "b", owned_seeds=("a",))
    original = canonical_json_bytes(fixture.request.model_dump(mode="json"))
    backend = SyntheticNativeBackend(fixture.native_input.space)
    backend.batch_size = backend.threads = 4
    encoded = encode_incremental_batch(fixture.native_input, backend)
    tmp_path.chmod(0o700)
    for name, raw in (
        ("result.json", canonical_json_bytes(encoded.result.model_dump(mode="json"))),
        ("vectors.f32", encoded.vectors),
    ):
        path = tmp_path / name
        path.write_bytes(raw)
        path.chmod(0o600)
    owner = FakePublisher()
    store = EmbeddingArtifactStore(cast(ControlFileSetPublisher, owner), source_commit="a" * 40)
    values = dict(
        workflow_request=fixture.request,
        plan=fixture.plan,
        policy=fixture.policy,
        association=fixture.association,
        request=fixture.native_input,
        workspace=tmp_path,
        created_at=NOW,
    )
    first = store.publish_owned_batch(**values)
    assert store.publish_owned_batch(**values) == first
    assert len(owner.saved) == 1
    assert len(fixture.plan.demands) == 2 and encoded.result.shard.row_count == 1
    assert first.logical_encoder_job_id == fixture.association.intent.native_launch_job_id
    assert first.owner_job_id != first.logical_encoder_job_id
    assert canonical_json_bytes(fixture.request.model_dump(mode="json")) == original


def test_foreign_original_plan_is_rejected_before_output_or_publication(tmp_path: Path) -> None:
    fixture = native_fixture()
    other = native_fixture("c", "d")
    owner = FakePublisher()
    store = EmbeddingArtifactStore(cast(ControlFileSetPublisher, owner), source_commit="a" * 40)
    with pytest.raises(EmbeddingArtifactStoreError, match="CONTEXT_INVALID"):
        store.publish_owned_batch(
            workflow_request=fixture.request,
            plan=other.plan,
            policy=fixture.policy,
            association=fixture.association,
            request=fixture.native_input,
            workspace=tmp_path,
            created_at=NOW,
        )
    assert owner.calls == []
