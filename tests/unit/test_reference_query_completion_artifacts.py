"""Temporary real publication/reads; numerical/source/IAM metadata is synthetic."""

from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_service.local_embedding_completion_artifacts import (
    resolve_native_reference_query_completion,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.embedding_artifact_store import EmbeddingArtifactStore
from eom_orchestrator.file_set_control_artifacts import ControlFileSetIdentity
from eom_orchestrator.local_embedding_completion_artifacts import NativeEmbeddingCompletionPublisher
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_workflow.reference_query_execution import (
    parse_reference_query_workflow_receipt,
    validate_reference_query_step_output,
)
from sqlalchemy import func, select

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_control_file_set_publication import _contains_bytes, _publisher
from tests.unit.test_embedding_reference_query_artifact_store import prepare, publish
from tests.unit.test_reference_query_execution_contracts import case


def owner(tmp_path: Path):
    publisher, _ = _publisher(tmp_path)
    workspace = tmp_path / "owner-workspace"
    workspace.mkdir(mode=0o700)
    publisher.settings = replace(publisher.settings, workspace_root=workspace)
    return publisher


def test_identified_query_four_members_and_receipt_round_trip_exact_replay(tmp_path):
    publisher = owner(tmp_path)
    current = case()
    value = prepare(tmp_path, current)
    value.store = EmbeddingArtifactStore(publisher, source_commit="a" * 40)
    query_identity = ControlFileSetIdentity(
        current.receipt.query_artifact_owner_job_id,
        current.receipt.query_input.artifact_id,
        current.receipt.query_input.artifact_revision_id,
    )
    published = publish(value, identity=query_identity)
    assert publish(value, identity=query_identity) == published
    receipt_body = current.receipt.model_dump(mode="json")
    receipt_body.update(
        query_artifact_owner_job_id=published.owner_job_id,
        query_input=published.input.model_dump(mode="json"),
        shard=published.shard.model_dump(mode="json"),
        binary=published.binary.model_dump(mode="json"),
    )
    receipt_body["query_execution"].update(
        result_member=published.result.model_dump(mode="json"),
        result_sha256=value.result.result_sha256,
    )
    receipt = parse_reference_query_workflow_receipt(seal(receipt_body, "receipt_sha256"))
    identity = ControlFileSetIdentity(
        receipt.receipt_owner_job_id,
        current.output.receipt.artifact_id,
        current.output.receipt.artifact_revision_id,
    )
    completion = NativeEmbeddingCompletionPublisher(publisher, source_commit="a" * 40)
    output = completion.publish_reference_query(receipt, identity=identity)
    assert completion.publish_reference_query(receipt, identity=identity) == output
    validate_reference_query_step_output(output, receipt)
    assert output.receipt.sha256 != receipt.receipt_sha256
    with publisher.sessions.begin() as session:
        assert (
            resolve_native_reference_query_completion(
                session,
                CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root),
                output,
            )
            == receipt
        )
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 2
        for job in session.scalars(select(JobRecord)):
            assert job.status == "SUCCEEDED"
            assert not _contains_bytes(job.request)
            assert b'"text"' not in canonical_json_bytes(job.request)
        for revision in session.scalars(select(ArtifactRevisionRecord)):
            assert not _contains_bytes(revision.result)
    assert tuple(publisher.settings.workspace_root.iterdir()) == ()


@pytest.mark.parametrize("fault", ["producer", "unapproved", "bytes", "carrier", "type", "missing"])
def test_canonical_receipt_read_denies_bad_provenance_and_bytes(tmp_path, fault):
    publisher = owner(tmp_path)
    value = case()
    receipt = value.receipt
    identity = ControlFileSetIdentity(
        receipt.receipt_owner_job_id,
        value.output.receipt.artifact_id,
        value.output.receipt.artifact_revision_id,
    )
    output = NativeEmbeddingCompletionPublisher(
        publisher, source_commit="a" * 40
    ).publish_reference_query(receipt, identity=identity)
    with publisher.sessions.begin() as session:
        job = session.get(JobRecord, identity.job_id)
        revision = session.get(ArtifactRevisionRecord, identity.artifact_revision_id)
        if fault == "producer":
            job.status = "RUNNING"
        if fault == "unapproved":
            revision.approved = False
        if fault == "bytes":
            Path(revision.nas_path, "receipt.json").write_bytes(b"corrupt")
        if fault == "missing":
            Path(revision.nas_path, "receipt.json").unlink()
        if fault == "type":
            from eom_orchestrator.models import ArtifactRecord

            session.get(
                ArtifactRecord, identity.artifact_id
            ).artifact_type = "control_local_embedding_completion"
    if fault == "carrier":
        output = output.model_copy(update={"receipt_sha256": "sha256:" + "0" * 64})
    with publisher.sessions.begin() as session, pytest.raises(ValueError):
        resolve_native_reference_query_completion(
            session, CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root), output
        )


def test_query_publisher_rejects_merged_producer_identity_before_any_write(tmp_path):
    publisher = owner(tmp_path)
    value = case()
    body = value.receipt.model_dump(mode="json")
    body["receipt_owner_job_id"] = body["query_artifact_owner_job_id"]
    receipt = parse_reference_query_workflow_receipt(seal(body, "receipt_sha256"))
    identity = ControlFileSetIdentity(
        receipt.receipt_owner_job_id, "artifact_" + "f" * 32, "rev_" + "f" * 32
    )
    with pytest.raises(ValueError, match="PRODUCER_MISMATCH"):
        NativeEmbeddingCompletionPublisher(
            publisher, source_commit="a" * 40
        ).publish_reference_query(receipt, identity=identity)
    with publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0


def test_identified_replay_cannot_substitute_a_different_query_owner(tmp_path):
    publisher = owner(tmp_path)
    value = prepare(tmp_path, case())
    value.store = EmbeddingArtifactStore(publisher, source_commit="a" * 40)
    first = ControlFileSetIdentity("job_" + "b" * 32, "artifact_" + "b" * 32, "rev_" + "b" * 32)
    original = publish(value, identity=first)
    other = ControlFileSetIdentity("job_" + "f" * 32, "artifact_" + "f" * 32, "rev_" + "f" * 32)
    with pytest.raises(ControlPlaneError) as error:
        publish(value, identity=other)
    assert error.value.code == "CONTROL_FILE_SET_IDENTITY_CONFLICT"
    assert publish(value, identity=first) == original
    with publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
