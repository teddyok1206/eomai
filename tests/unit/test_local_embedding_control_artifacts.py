"""Existing publisher on disposable SQLite/local temporary Artifacts, never NAS."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import CONTROL_FILE_SET_PROTOCOL
from eom_orchestrator.local_embedding_control_artifacts import (
    EXECUTION_POLICY_ARTIFACT_TYPE,
    OWNED_INPUT_ARTIFACT_TYPE,
    REFERENCE_QUERY_POLICY_ARTIFACT_TYPE,
    SOURCE_PLAN_ARTIFACT_TYPE,
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from sqlalchemy import func, select

from tests.unit.local_embedding_admission_fixtures import native_fixture
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_reference_query_execution_contracts import case as query_case

NOW = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)


def test_reference_query_policy_publication_replays_and_keeps_document_kind_separate(
    tmp_path: Path,
) -> None:
    policy = query_case().policy
    publisher, _engine = _publisher(tmp_path)
    publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    adapter = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    key = "synthetic-reference-policy:" + "c" * 32
    receipt = adapter.publish_reference_query_policy(policy, idempotency_key=key, created_at=NOW)
    assert (
        adapter.publish_reference_query_policy(policy, idempotency_key=key, created_at=NOW)
        == receipt
    )
    assert receipt.semantic_sha256 == policy.policy_sha256
    with publisher.sessions() as session, session.begin():
        pointer = receipt.member
        reader = PinnedArtifactReadContext(
            session, CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
        )
        reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
        member = reader.read_pinned(
            **pointer.model_dump(mode="python"),
            expected_artifact_types=(REFERENCE_QUERY_POLICY_ARTIFACT_TYPE,),
            expected_primary_file="policy.json",
            max_bytes=64 * 1024,
        )
        assert member.payload == canonical_json_bytes(policy.model_dump(mode="json"))
        job = session.scalar(select(JobRecord))
        assert job is not None
        assert b'"spaces"' not in canonical_json_bytes(job.request)
    with pytest.raises(ControlPlaneError):
        adapter.publish_policy(native_fixture().policy, idempotency_key=key, created_at=NOW)
    with pytest.raises(ValueError):
        adapter.publish_reference_query_policy(
            policy.model_copy(update={"policy_sha256": "sha256:" + "f" * 64}),
            idempotency_key=key + "bad",
            created_at=NOW,
        )


def test_plan_and_policy_publish_through_existing_owner_and_catalog_resolves_exact_members(
    tmp_path: Path,
) -> None:
    fixture = native_fixture()
    publisher, _engine = _publisher(tmp_path)
    workspace = tmp_path / "owner-workspace"
    workspace.mkdir()
    publisher.settings = replace(publisher.settings, workspace_root=workspace)
    adapter = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    plan = adapter.publish_source_plan(
        fixture.plan, idempotency_key="synthetic-native-plan:" + "a" * 32, created_at=NOW
    )
    policy = adapter.publish_policy(
        fixture.policy, idempotency_key="synthetic-native-policy:" + "a" * 32, created_at=NOW
    )
    assert (
        adapter.publish_source_plan(
            fixture.plan, idempotency_key="synthetic-native-plan:" + "a" * 32, created_at=NOW
        )
        == plan
    )
    assert plan.owner_job_id != policy.owner_job_id
    assert plan.semantic_sha256 == fixture.plan.plan_sha256
    assert policy.semantic_sha256 == fixture.policy.policy_sha256
    assert list(workspace.iterdir()) == []
    with publisher.sessions() as session, session.begin():
        reader = PinnedArtifactReadContext(
            session, CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
        )
        reader.prefetch(
            tuple((r.member.artifact_id, r.member.artifact_revision_id) for r in (plan, policy))
        )
        for receipt, value, artifact_type in (
            (plan, fixture.plan, SOURCE_PLAN_ARTIFACT_TYPE),
            (policy, fixture.policy, EXECUTION_POLICY_ARTIFACT_TYPE),
        ):
            pointer = receipt.member
            reader.require_file_set(
                pointer.artifact_id,
                pointer.artifact_revision_id,
                (pointer.member_path,),
                manifest_version=CONTROL_FILE_SET_PROTOCOL,
            )
            member = reader.read_pinned(
                **pointer.model_dump(mode="python"),
                expected_artifact_types=(artifact_type,),
                expected_primary_file=pointer.member_path,
                max_bytes=64 * 1024**2,
            )
            assert member.payload == canonical_json_bytes(value.model_dump(mode="json"))
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 2
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 2
        for job in session.scalars(select(JobRecord)):
            serialized = canonical_json_bytes(job.request)
            assert b'"sources"' not in serialized
            assert b'"profiles"' not in serialized
            assert b'"text"' not in serialized
            assert len(serialized) < 4096


def test_same_publication_key_cannot_switch_control_kind(tmp_path: Path) -> None:
    fixture = native_fixture()
    publisher, _engine = _publisher(tmp_path)
    publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    adapter = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    key = "synthetic-native-control:" + "b" * 32
    adapter.publish_source_plan(fixture.plan, idempotency_key=key, created_at=NOW)
    with pytest.raises(ControlPlaneError) as failure:
        adapter.publish_policy(fixture.policy, idempotency_key=key, created_at=NOW)
    assert failure.value.code == "CONTROL_FILE_SET_CONFLICT"
    with publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1


def test_invalid_policy_hash_rejected_before_any_publication(tmp_path: Path) -> None:
    fixture = native_fixture()
    publisher, _engine = _publisher(tmp_path)
    publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    adapter = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    with pytest.raises(ValueError):
        adapter.publish_policy(
            fixture.policy.model_copy(update={"policy_sha256": "sha256:" + "f" * 64}),
            idempotency_key="synthetic-native-control:" + "b" * 32,
            created_at=NOW,
        )
    with publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0


def test_owned_input_uses_exact_canonical_member_and_replays_without_copying_text_into_db(
    tmp_path: Path,
) -> None:
    fixture = native_fixture("a", "b", owned_seeds=("a",))
    publisher, _engine = _publisher(tmp_path)
    workspace = tmp_path / "owner-workspace"
    workspace.mkdir()
    publisher.settings = replace(publisher.settings, workspace_root=workspace)
    adapter = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    key = "synthetic-owned-input:" + "a" * 32
    receipt = adapter.publish_owned_input(fixture.native_input, idempotency_key=key, created_at=NOW)
    assert (
        adapter.publish_owned_input(fixture.native_input, idempotency_key=key, created_at=NOW)
        == receipt
    )
    assert receipt.semantic_sha256 == fixture.native_input.request_sha256
    assert receipt.member.member_path == "input.json"
    assert receipt.owner_job_id != fixture.native_input.job_id
    assert len(fixture.plan.demands) == 2 and len(fixture.native_input.rows) == 1
    assert list(workspace.iterdir()) == []
    with publisher.sessions() as session, session.begin():
        reader = PinnedArtifactReadContext(
            session, CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
        )
        pointer = receipt.member
        reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
        reader.require_file_set(
            pointer.artifact_id,
            pointer.artifact_revision_id,
            ("input.json",),
            manifest_version=CONTROL_FILE_SET_PROTOCOL,
        )
        raw = reader.read_pinned(
            **pointer.model_dump(mode="python"),
            expected_artifact_types=(OWNED_INPUT_ARTIFACT_TYPE,),
            expected_primary_file="input.json",
            max_bytes=64 * 1024**2,
        ).payload
        assert raw == canonical_json_bytes(fixture.native_input.model_dump(mode="json"))
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 1
        job = session.scalar(select(JobRecord))
        assert job is not None
        metadata = canonical_json_bytes(job.request)
        assert b'"text"' not in metadata and b'"rows"' not in metadata
        assert len(metadata) < 4096


def test_owned_input_cannot_replace_another_payload_under_same_key(tmp_path: Path) -> None:
    fixture = native_fixture("a")
    other = native_fixture("b")
    publisher, _engine = _publisher(tmp_path)
    publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    adapter = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    key = "synthetic-owned-input:" + "b" * 32
    first = adapter.publish_owned_input(fixture.native_input, idempotency_key=key, created_at=NOW)
    with pytest.raises(ControlPlaneError) as failure:
        adapter.publish_owned_input(other.native_input, idempotency_key=key, created_at=NOW)
    assert failure.value.code == "CONTROL_FILE_SET_CONFLICT"
    assert (
        adapter.publish_owned_input(fixture.native_input, idempotency_key=key, created_at=NOW)
        == first
    )


def test_owned_input_hash_is_validated_before_publication(tmp_path: Path) -> None:
    fixture = native_fixture()
    publisher, _engine = _publisher(tmp_path)
    publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    adapter = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    changed = fixture.native_input.model_copy(update={"request_sha256": "sha256:" + "f" * 64})
    with pytest.raises(ValueError):
        adapter.publish_owned_input(
            changed, idempotency_key="synthetic-owned-input:" + "c" * 32, created_at=NOW
        )
    with publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0
