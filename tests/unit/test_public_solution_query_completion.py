"""Canonical QUERY2 receipt IO; numerical/source/Workflow evidence remains synthetic."""

from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_service.local_embedding_completion_artifacts import (
    resolve_native_public_solution_query_completion,
    resolve_native_reference_query_completion,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.file_set_control_artifacts import ControlFileSetIdentity
from eom_orchestrator.local_embedding_completion_artifacts import NativeEmbeddingCompletionPublisher
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from sqlalchemy import func, select

from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_public_solution_reference_query_execution import public_workflow_case
from tests.unit.test_reference_query_execution_contracts import case


def completion_case(tmp_path):
    owner, _ = _publisher(tmp_path)
    workspace = tmp_path / "receipt-workspace"
    workspace.mkdir(mode=0o700)
    owner.settings = replace(owner.settings, workspace_root=workspace)
    value = public_workflow_case()
    identity = ControlFileSetIdentity(
        value.receipt.receipt_owner_job_id,
        value.output.receipt.artifact_id,
        value.output.receipt.artifact_revision_id,
    )
    return NativeEmbeddingCompletionPublisher(owner, source_commit="a" * 40), value, identity


def test_query2_canonical_receipt_read_replay_and_legacy_entry_point_separation(tmp_path):
    publisher, value, identity = completion_case(tmp_path)
    output = publisher.publish_public_solution_reference_query(value.receipt, identity=identity)
    assert (
        publisher.publish_public_solution_reference_query(value.receipt, identity=identity)
        == output
    )
    assert output == value.output
    raw = canonical_json_bytes(value.receipt.model_dump(mode="json"))
    assert output.receipt.sha256 == sha256_bytes(raw) != output.receipt_sha256
    with publisher.publisher.sessions.begin() as session:
        settings = CatalogSettings(nas_artifact_root=publisher.publisher.settings.nas_artifact_root)
        assert (
            resolve_native_public_solution_query_completion(session, settings, output)
            == value.receipt
        )
        with pytest.raises(ValueError):
            resolve_native_reference_query_completion(session, settings, output)
        revision = session.get(ArtifactRevisionRecord, identity.artifact_revision_id)
        assert Path(revision.nas_path, "receipt.json").read_bytes() == raw
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
    assert tuple(publisher.publisher.settings.workspace_root.iterdir()) == ()


@pytest.mark.parametrize("fault", ["extra", "owner", "legacy", "hash"])
def test_query2_receipt_invalid_family_owner_or_raw_model_cannot_publish(tmp_path, fault):
    publisher, value, identity = completion_case(tmp_path)
    receipt = value.receipt
    if fault == "extra":
        receipt = receipt.model_copy(update={"authority": "ADMIN"})
    elif fault == "owner":
        identity = replace(identity, job_id="job_" + "f" * 32)
    elif fault == "legacy":
        receipt = case().receipt
    else:
        receipt = receipt.model_copy(update={"receipt_sha256": "sha256:" + "f" * 64})
    with pytest.raises(ValueError):
        publisher.publish_public_solution_reference_query(receipt, identity=identity)
    with publisher.publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0


@pytest.mark.parametrize("fault", ["unapproved", "producer", "bytes"])
def test_query2_completion_read_rechecks_canonical_lifecycle_producer_and_actual_file(
    tmp_path, fault
):
    publisher, value, identity = completion_case(tmp_path)
    output = publisher.publish_public_solution_reference_query(value.receipt, identity=identity)
    with publisher.publisher.sessions.begin() as session:
        revision = session.get(ArtifactRevisionRecord, identity.artifact_revision_id)
        if fault == "unapproved":
            revision.approved = False
        elif fault == "producer":
            session.get(JobRecord, identity.job_id).status = "RUNNING"
        else:
            Path(revision.nas_path, "receipt.json").write_bytes(b"corrupt disposable receipt")
    with publisher.publisher.sessions.begin() as session, pytest.raises(ValueError):
        resolve_native_public_solution_query_completion(
            session,
            CatalogSettings(nas_artifact_root=publisher.publisher.settings.nas_artifact_root),
            output,
        )
