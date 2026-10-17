"""Disposable SQLite/filesystem proof; Chat/source/native authority stays synthetic."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from eom_catalog_service.local_embedding_completion_artifacts import (
    resolve_native_private_chat_query_completion,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator import file_set_control_artifacts as publication
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import ControlFileSetIdentity
from eom_orchestrator.local_embedding_completion_artifacts import NativeEmbeddingCompletionPublisher
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_workflow.private_chat_query_workflow import PrivateChatQueryWorkflowReceipt
from sqlalchemy import func, select, update

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_control_file_set_publication import _contains_bytes
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_workflow import completed as completed
from tests.unit.test_reference_query_completion_artifacts import owner


@pytest.fixture
def completion(tmp_path, completed):
    publisher = owner(tmp_path)
    identity = ControlFileSetIdentity(
        completed.receipt.receipt_owner_job_id,
        "artifact_" + "e" * 32,
        "rev_" + "e" * 32,
    )
    return (
        NativeEmbeddingCompletionPublisher(publisher, source_commit="a" * 40),
        completed.receipt,
        identity,
    )


def read(session, publisher, output, **kwargs):
    return resolve_native_private_chat_query_completion(
        session,
        CatalogSettings(nas_artifact_root=publisher.publisher.settings.nas_artifact_root),
        output,
        **kwargs,
    )


def test_private_completion_actual_canonical_commit_read_and_exact_replay(completion):
    publisher, receipt, identity = completion
    output = publisher.publish_private_chat_query(receipt, identity=identity)
    assert publisher.publish_private_chat_query(receipt, identity=identity) == output
    assert (
        output.receipt.sha256
        == sha256_bytes(canonical_json_bytes(receipt))
        != receipt.receipt_sha256
    )
    with publisher.publisher.sessions.begin() as session:
        assert read(session, publisher, output) == receipt
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        revision = session.get(ArtifactRevisionRecord, identity.artifact_revision_id)
        job = session.get(JobRecord, identity.job_id)
        assert job.status == "SUCCEEDED" and job.worker_slot_id is None
        assert not _contains_bytes(job.request) and not _contains_bytes(revision.result)
        assert TEXT.encode() not in canonical_json_bytes(job.request)
        assert TEXT.encode() not in canonical_json_bytes(revision.manifest)
        assert (Path(revision.nas_path) / "receipt.json").read_bytes() == canonical_json_bytes(
            receipt
        )
        assert len(revision.manifest["files"]) == 1
    assert tuple(publisher.publisher.settings.workspace_root.iterdir()) == ()


@pytest.mark.parametrize("fault", ["producer", "unapproved", "bytes", "missing", "type", "carrier"])
def test_private_completion_actual_read_denies_changed_provenance_and_members(completion, fault):
    publisher, receipt, identity = completion
    output = publisher.publish_private_chat_query(receipt, identity=identity)
    with publisher.publisher.sessions.begin() as session:
        revision = session.get(ArtifactRevisionRecord, identity.artifact_revision_id)
        if fault == "producer":
            session.get(JobRecord, identity.job_id).status = "RUNNING"
        elif fault == "unapproved":
            revision.approved = False
        elif fault == "bytes":
            (Path(revision.nas_path) / "receipt.json").write_bytes(b"corrupt")
        elif fault == "missing":
            (Path(revision.nas_path) / "receipt.json").unlink()
        elif fault == "type":
            session.get(
                ArtifactRecord, identity.artifact_id
            ).artifact_type = "control_reference_query_completion"
    if fault == "carrier":
        output = output.model_copy(update={"receipt_sha256": "sha256:" + "f" * 64})
    with publisher.publisher.sessions.begin() as session, pytest.raises(ValueError):
        read(session, publisher, output)


@pytest.mark.parametrize("fault", ["producer", "artifact", "revision"])
def test_invalid_original_producer_or_merged_file_set_fails_before_writes(completion, fault):
    publisher, receipt, identity = completion
    if fault == "producer":
        identity = replace(identity, job_id="job_" + "f" * 32)
    elif fault == "artifact":
        identity = replace(identity, artifact_id=receipt.execution_record.artifact_id)
    else:
        identity = replace(
            identity, artifact_revision_id=receipt.execution_record.artifact_revision_id
        )
    with pytest.raises(ValueError):
        publisher.publish_private_chat_query(receipt, identity=identity)
    with publisher.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0
    assert tuple(publisher.publisher.settings.workspace_root.iterdir()) == ()


@pytest.mark.parametrize("field", ["origin_sha256", "workflow_request_sha256", "published_at"])
def test_changed_intent_origin_or_time_cannot_create_another_original_key(completion, field):
    publisher, receipt, identity = completion
    original = publisher.publish_private_chat_query(receipt, identity=identity)
    body = receipt.model_dump(mode="json")
    body[field] = (
        ("sha256:" + "f" * 64)
        if field.endswith("sha256")
        else (receipt.published_at + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    )
    changed = PrivateChatQueryWorkflowReceipt.model_validate(seal(body, "receipt_sha256"))
    with pytest.raises(ControlPlaneError):
        publisher.publish_private_chat_query(changed, identity=identity)
    assert publisher.publish_private_chat_query(receipt, identity=identity) == original
    with publisher.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1


@pytest.mark.parametrize(
    "fault", ["none", "nested", "new", "dirty", "deleted", "reader_session", "reader_settings"]
)
def test_private_completion_read_retains_clean_current_root_and_reader_settings(completion, fault):
    publisher, receipt, identity = completion
    output = publisher.publish_private_chat_query(receipt, identity=identity)
    with publisher.publisher.sessions() as session, publisher.publisher.sessions() as other:
        kwargs = {}
        if fault != "none":
            session.begin()
        if fault == "nested":
            session.begin_nested()
        elif fault == "new":
            session.add(JobRecord(job_id="job_" + "f" * 32))
        elif fault == "dirty":
            session.get(JobRecord, identity.job_id).status = "RUNNING"
        elif fault == "deleted":
            session.delete(session.get(JobRecord, identity.job_id))
        elif fault in {"reader_session", "reader_settings"}:
            settings = CatalogSettings(
                nas_artifact_root=publisher.publisher.settings.nas_artifact_root
            )
            other.begin()
            kwargs["artifact_reader"] = PinnedArtifactReadContext(
                other if fault == "reader_session" else session,
                settings
                if fault == "reader_session"
                else replace(settings, nas_artifact_root=settings.nas_artifact_root / "other"),
            )
        with pytest.raises(ValueError):
            read(session, publisher, output, **kwargs)
        session.rollback()
    with publisher.publisher.sessions.begin() as session:
        assert read(session, publisher, output) == receipt


def test_commit_interruption_and_lost_observation_reuse_same_private_completion(
    completion, monkeypatch
):
    publisher, receipt, identity = completion
    original = publication.create_artifact_records

    def interrupted(*args, **kwargs):
        raise RuntimeError("synthetic before database commit")

    monkeypatch.setattr(publication, "create_artifact_records", interrupted)
    with pytest.raises(RuntimeError):
        publisher.publish_private_chat_query(receipt, identity=identity)
    monkeypatch.setattr(publication, "create_artifact_records", original)
    publish = publisher.publisher.publish_identified

    def lost(**kwargs):
        publish(**kwargs)
        raise RuntimeError("synthetic after commit observation lost")

    monkeypatch.setattr(publisher.publisher, "publish_identified", lost)
    with pytest.raises(RuntimeError):
        publisher.publish_private_chat_query(receipt, identity=identity)
    monkeypatch.setattr(publisher.publisher, "publish_identified", publish)
    output = publisher.publish_private_chat_query(receipt, identity=identity)
    with publisher.publisher.sessions.begin() as session:
        assert read(session, publisher, output) == receipt
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 1


@pytest.mark.parametrize("fault", ["job", "logical", "revision"])
def test_private_receipt_revoked_during_materialization_is_not_returned(
    completion, monkeypatch, fault
):
    publisher, receipt, identity = completion
    output = publisher.publish_private_chat_query(receipt, identity=identity)
    settings = CatalogSettings(nas_artifact_root=publisher.publisher.settings.nas_artifact_root)
    with publisher.publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext(session, settings)
        original = reader.read_pinned

        def revoke_after_read(**kwargs):
            member = original(**kwargs)
            statement = (
                update(JobRecord)
                .where(JobRecord.job_id == identity.job_id)
                .values(status="RUNNING")
                if fault == "job"
                else update(ArtifactRecord)
                .where(ArtifactRecord.logical_artifact_id == identity.artifact_id)
                .values(approved=False)
                if fault == "logical"
                else update(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.revision_id == identity.artifact_revision_id)
                .values(approved=False)
            )
            session.execute(statement.execution_options(synchronize_session=False))
            assert not session.dirty
            return member

        monkeypatch.setattr(reader, "read_pinned", revoke_after_read)
        with pytest.raises(ValueError):
            resolve_native_private_chat_query_completion(
                session, settings, output, artifact_reader=reader
            )
        session.rollback()
