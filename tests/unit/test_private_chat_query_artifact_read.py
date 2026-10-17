"""Actual local four-member publication/read; origin and numerics are synthetic."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.private_chat_query_artifact_read import CatalogPrivateChatQueryArtifacts
from eom_catalog_service.settings import CatalogSettings
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_workflow.private_chat_query_workflow import PrivateChatQueryWorkflowReceipt

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_publication import prepare
from tests.unit.test_private_chat_query_workflow import completed as completed
from tests.unit.test_reference_query_completion_artifacts import owner


@pytest.fixture
def published(tmp_path, completed):
    publisher = owner(tmp_path)
    value = prepare(tmp_path, publisher=publisher)
    saved = value.store.publish_private_chat_query(**value.arguments)
    receipt = receipt_for_publication(completed, value, saved)
    return SimpleNamespace(
        publisher=publisher,
        value=value,
        receipt=receipt,
        completed=completed,
        saved=saved,
        settings=CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root),
    )


def receipt_for_publication(completed, value, saved):
    launch = value.arguments["launch"]
    body = completed.receipt.model_dump(mode="json") | {
        "workflow_id": launch.workflow_id,
        "step_run_id": launch.step_run_id,
        "launch_association_sha256": launch.association_sha256,
        "execution_record": saved.intent.model_dump(mode="json"),
        "query_artifact_owner_job_id": saved.owner_job_id,
        "shard": saved.shard.model_dump(mode="json"),
        "binary": saved.binary.model_dump(mode="json"),
    }
    body["query_execution"]["result_member"] = saved.result.model_dump(mode="json")
    return PrivateChatQueryWorkflowReceipt.model_validate(seal(body, "receipt_sha256"))


def read(value, session, *, reader=None, **overrides):
    arguments = dict(
        workflow_request=value.completed.request,
        policy=value.completed.policy,
        bundle=value.completed.bundle,
        launch=value.completed.launch,
        native_input=value.completed.native,
        receipt=value.receipt,
        origin=value.completed.expected["origin"],
        workflow_id=value.receipt.workflow_id,
        step_run_id=value.receipt.step_run_id,
        receipt_owner_job_id=value.receipt.receipt_owner_job_id,
        manifest_sha256=value.saved.manifest_sha256,
    )
    return CatalogPrivateChatQueryArtifacts(
        session, value.settings, artifact_reader=reader
    ).resolve_publication(**(arguments | overrides))


def test_private_four_member_read_and_replay_keep_question_only_in_original_source(published):
    with published.publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext(session, published.settings)
        first = read(published, session, reader=reader)
        assert read(published, session, reader=reader) == first
        assert (
            first.request == published.completed.native and first.result == published.value.result
        )
        assert first.publication_job_id == published.saved.owner_job_id
        assert TEXT not in repr(first)
        revision = session.get(ArtifactRevisionRecord, published.saved.intent.artifact_revision_id)
        assert not Path(revision.nas_path, "input.json").exists()
        assert len(revision.manifest["files"]) == 4


@pytest.mark.parametrize("member", ("intent.json", "result.json", "shard.json", "vectors.f32"))
@pytest.mark.parametrize("fault", ("missing", "bytes"))
def test_private_canonical_member_missing_or_changed_fails_without_text(published, member, fault):
    with published.publisher.sessions.begin() as session:
        revision = session.get(ArtifactRevisionRecord, published.saved.intent.artifact_revision_id)
        target = Path(revision.nas_path, member)
    if fault == "missing":
        target.unlink()
    else:
        target.write_bytes(b"PRIVATE_BYTES_NOT_FOR_LOGS")
    with published.publisher.sessions.begin() as session, pytest.raises(ValueError) as error:
        read(published, session)
    assert str(error.value) == "PRIVATE_CHAT_QUERY_ARTIFACT_READ_INVALID"
    assert "PRIVATE_BYTES_NOT_FOR_LOGS" not in str(error.value) and error.value.__suppress_context__


@pytest.mark.parametrize("fault", ("producer", "type", "approval", "manifest"))
def test_other_purpose_or_unapproved_private_publication_is_not_readable(published, fault):
    with published.publisher.sessions.begin() as session:
        if fault == "producer":
            session.get(JobRecord, published.saved.owner_job_id).status = "RUNNING"
        elif fault == "type":
            session.get(
                ArtifactRecord, published.saved.intent.artifact_id
            ).artifact_type = "control_embedding_reference_query"
        elif fault == "approval":
            session.get(
                ArtifactRevisionRecord, published.saved.intent.artifact_revision_id
            ).approved = False
    with published.publisher.sessions.begin() as session, pytest.raises(ValueError):
        read(
            published,
            session,
            **({"manifest_sha256": "sha256:" + "f" * 64} if fault == "manifest" else {}),
        )


@pytest.mark.parametrize("fault", ("origin", "input", "producer", "workflow"))
def test_private_result_cannot_be_rebound_to_another_origin_or_execution(published, fault):
    changes = {}
    if fault == "origin":
        changes["origin"] = ChatPrivateQueryOrigin.model_validate(
            seal(
                published.completed.expected["origin"].model_dump(mode="json")
                | {"runtime_id": "chatrt_" + "f" * 32},
                "origin_sha256",
            )
        )
    elif fault == "input":
        changes["native_input"] = published.completed.native.model_copy(
            update={"question": "PRIVATE_UNTRUSTED_QUESTION"}
        )
    elif fault == "producer":
        changes["receipt_owner_job_id"] = "job_" + "f" * 32
    else:
        changes["workflow_id"] = "workflow_" + "f" * 32
    with published.publisher.sessions.begin() as session, pytest.raises(ValueError) as error:
        read(published, session, **changes)
    assert str(error.value) == "PRIVATE_CHAT_QUERY_ARTIFACT_READ_INVALID"
    assert TEXT not in str(error.value) and "PRIVATE_UNTRUSTED_QUESTION" not in str(error.value)


@pytest.mark.parametrize("fault", ("none", "nested", "new", "dirty", "reader_root", "settings"))
def test_private_read_requires_same_clean_root_and_same_settings(published, fault):
    with published.publisher.sessions() as session, published.publisher.sessions() as other:
        reader = None
        if fault != "none":
            session.begin()
        if fault == "nested":
            session.begin_nested()
        elif fault == "new":
            session.add(JobRecord(job_id="job_" + "f" * 32))
        elif fault == "dirty":
            session.get(JobRecord, published.saved.owner_job_id).status = "RUNNING"
        elif fault == "reader_root":
            other.begin()
            reader = PinnedArtifactReadContext(other, published.settings)
        elif fault == "settings":
            reader = PinnedArtifactReadContext(
                session,
                CatalogSettings(nas_artifact_root=published.settings.nas_artifact_root / "other"),
            )
        with pytest.raises(ValueError):
            read(published, session, reader=reader)
        session.rollback()


def test_late_producer_withdrawal_is_rechecked_after_last_materialized_member(
    published, monkeypatch
):
    with published.publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext(session, published.settings)
        original = reader.read_pinned
        reads = []

        def late(**arguments):
            member = original(**arguments)
            reads.append(arguments["member_path"])
            if arguments["member_path"] == "vectors.f32":
                with published.publisher.sessions.begin() as writer:
                    writer.get(JobRecord, published.saved.owner_job_id).status = "RUNNING"
            return member

        monkeypatch.setattr(reader, "read_pinned", late)
        with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_ARTIFACT_READ_INVALID"):
            read(published, session, reader=reader)
        assert reads == ["intent.json", "result.json", "shard.json", "vectors.f32"]
