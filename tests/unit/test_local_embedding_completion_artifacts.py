"""Actual file-set commit/replay, not current IAM or installed runtime acceptance."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_service.local_embedding_completion_artifacts import (
    resolve_native_embedding_completion,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import sha256_bytes
from eom_orchestrator import file_set_control_artifacts as publication
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import ControlFileSetIdentity
from eom_orchestrator.local_embedding_completion_artifacts import (
    NativeEmbeddingCompletionPublisher,
)
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_workflow.local_embedding_workflow_receipt import (
    local_embedding_workflow_receipt_bytes,
    validate_local_embedding_step_output,
)
from sqlalchemy import func, select

from tests.unit.local_embedding_workflow_receipt_fixtures import receipt_fixture
from tests.unit.test_control_file_set_publication import _contains_bytes, _publisher


def completion_publisher(tmp_path: Path):
    owner, _engine = _publisher(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    owner.settings = replace(owner.settings, workspace_root=workspace)
    publisher = NativeEmbeddingCompletionPublisher(owner, source_commit="a" * 40)
    receipt = receipt_fixture().receipt
    identity = ControlFileSetIdentity(
        receipt.receipt_owner_job_id, "artifact_" + "e" * 32, "rev_" + "e" * 32
    )
    return publisher, receipt, identity


def test_actual_producer_commit_raw_hash_and_exact_replay(tmp_path: Path) -> None:
    publisher, receipt, identity = completion_publisher(tmp_path)
    output = publisher.publish(receipt, identity=identity)
    assert publisher.publish(receipt, identity=identity) == output
    assert validate_local_embedding_step_output(output, receipt) == output
    assert output.receipt_owner_job_id == identity.job_id
    assert output.receipt.artifact_id == identity.artifact_id
    raw = local_embedding_workflow_receipt_bytes(receipt)
    assert output.receipt.sha256 == sha256_bytes(raw) != receipt.receipt_sha256
    with publisher.publisher.sessions() as session:
        producer = session.get(JobRecord, identity.job_id)
        revision = session.get(ArtifactRevisionRecord, identity.artifact_revision_id)
        assert producer is not None and revision is not None
        assert producer.status == "SUCCEEDED" and revision.job_id == producer.job_id
        assert Path(revision.nas_path, "receipt.json").read_bytes() == raw
        assert not _contains_bytes(producer.request) and not _contains_bytes(revision.result)
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
    with publisher.publisher.sessions.begin() as session:
        assert (
            resolve_native_embedding_completion(
                session,
                CatalogSettings(nas_artifact_root=publisher.publisher.settings.nas_artifact_root),
                output,
            )
            == receipt
        )
    assert tuple(publisher.publisher.settings.workspace_root.iterdir()) == ()


@pytest.mark.parametrize("fault", ["producer", "unapproved", "bytes", "owner"])
def test_actual_completion_read_rejects_false_producer_lifecycle_or_hash(
    tmp_path: Path, fault: str
) -> None:
    publisher, receipt, identity = completion_publisher(tmp_path)
    output = publisher.publish(receipt, identity=identity)
    with publisher.publisher.sessions.begin() as session:
        job = session.get(JobRecord, identity.job_id)
        revision = session.get(ArtifactRevisionRecord, identity.artifact_revision_id)
        if fault == "producer":
            job.status = "RUNNING"
        if fault == "unapproved":
            revision.approved = False
        if fault == "bytes":
            Path(revision.nas_path, "receipt.json").write_bytes(b"corrupt")
    if fault == "owner":
        from eom_workflow.local_embedding_workflow_receipt import (
            parse_local_embedding_workflow_receipt,
        )

        from tests.unit.inference_transfer_embedding_fixtures import seal

        body = receipt.model_dump(mode="json")
        body["receipt_owner_job_id"] = "job_" + "f" * 32
        forged = parse_local_embedding_workflow_receipt(seal(body, "receipt_sha256"))
        # Publish a real committed file set whose bytes falsely name another producer.
        from eom_orchestrator.file_set_control_artifacts import ControlFileSetMember

        raw = local_embedding_workflow_receipt_bytes(forged)
        path = tmp_path / "forged.json"
        path.write_bytes(raw)
        path.chmod(0o600)
        saved = publisher.publisher.publish(
            members=(
                ControlFileSetMember(
                    "receipt.json",
                    path,
                    sha256_bytes(raw),
                    len(raw),
                    output.receipt_schema,
                    "application/json",
                ),
            ),
            primary_file="receipt.json",
            artifact_type="control_local_embedding_completion",
            manifest_version="control-file-set/1.0",
            idempotency_key="synthetic-wrong-producer",
            source_commit="a" * 40,
            created_at=receipt.registration_observed_at,
        )
        from eom_workflow.local_embedding_workflow_receipt import parse_local_embedding_step_output

        body = output.model_dump(mode="json")
        body.update(
            receipt_owner_job_id=forged.receipt_owner_job_id,
            receipt_sha256=forged.receipt_sha256,
            receipt={
                **body["receipt"],
                "artifact_id": saved.artifact_id,
                "artifact_revision_id": saved.artifact_revision_id,
                "sha256": sha256_bytes(raw),
            },
        )
        output = parse_local_embedding_step_output(seal(body, "output_sha256"))
    with publisher.publisher.sessions.begin() as session, pytest.raises(ValueError):
        resolve_native_embedding_completion(
            session,
            CatalogSettings(nas_artifact_root=publisher.publisher.settings.nas_artifact_root),
            output,
        )


def test_wrong_producer_rejected_before_mutation(tmp_path: Path) -> None:
    publisher, receipt, identity = completion_publisher(tmp_path)
    with pytest.raises(ValueError, match="PRODUCER_MISMATCH"):
        publisher.publish(receipt, identity=replace(identity, job_id="job_" + "f" * 32))
    with publisher.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0


def test_changed_receipt_cannot_replace_existing_same_operation(tmp_path: Path) -> None:
    publisher, receipt, identity = completion_publisher(tmp_path)
    first = publisher.publish(receipt, identity=identity)
    changed = receipt_fixture(historical=True).receipt
    with pytest.raises(ControlPlaneError, match="publication replay differs"):
        publisher.publish(changed, identity=identity)
    assert publisher.publish(receipt, identity=identity) == first


def test_nas_commit_interruption_recovers_same_producer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher, receipt, identity = completion_publisher(tmp_path)
    original = publication.create_artifact_records
    interrupted = False

    def fail_once(*args: object, **kwargs: object) -> object:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise RuntimeError("isolated commit interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(publication, "create_artifact_records", fail_once)
    with pytest.raises(RuntimeError, match="isolated commit interruption"):
        publisher.publish(receipt, identity=identity)
    output = publisher.publish(receipt, identity=identity)
    assert output.receipt_owner_job_id == identity.job_id
    with publisher.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 1
