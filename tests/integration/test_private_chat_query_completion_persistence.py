"""Guarded PostgreSQL completion commits; owned Chat/native admission is synthetic."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_service.local_embedding_completion_artifacts import (
    resolve_native_private_chat_query_completion,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator import file_set_control_artifacts as publication
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetIdentity,
    ControlFileSetPublisher,
)
from eom_orchestrator.local_embedding_completion_artifacts import NativeEmbeddingCompletionPublisher
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.settings import Settings
from eom_workflow.private_chat_query_publication import (
    PrivateChatQueryLaunchAssociation,
    validate_private_chat_query_launch,
)
from eom_workflow.private_chat_query_workflow import (
    PrivateChatQueryWorkflowReceipt,
    validate_private_chat_query_workflow_receipt,
)
from sqlalchemy import Engine, func, select, update
from sqlalchemy.exc import DBAPIError

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_workflow import completed as completed

pytestmark = pytest.mark.integration


@pytest.fixture
def private_completion(guarded_engine: Engine, tmp_path: Path, completed):
    assert guarded_engine.dialect.name == "postgresql"
    assert not tmp_path.is_relative_to(Path("/mnt/nas"))
    identity = ControlFileSetIdentity(
        "job_" + uuid4().hex, "artifact_" + uuid4().hex, "rev_" + uuid4().hex
    )
    launch = PrivateChatQueryLaunchAssociation.model_validate(
        seal(
            completed.launch.model_dump(mode="json")
            | {
                "workflow_id": "workflow_" + uuid4().hex,
                "step_run_id": "steprun_" + uuid4().hex,
                "original_command_id": "wfcmd_" + uuid4().hex,
            },
            "association_sha256",
        )
    )
    record = validate_private_chat_query_launch(
        launch, completed.request, completed.policy, completed.bundle, completed.native
    )
    body = completed.receipt.model_dump(mode="json") | {
        "workflow_id": launch.workflow_id,
        "step_run_id": launch.step_run_id,
        "receipt_owner_job_id": identity.job_id,
        "launch_association_sha256": launch.association_sha256,
        "execution_record": completed.receipt.execution_record.model_dump(mode="json")
        | {
            "sha256": sha256_bytes(canonical_json_bytes(record)),
        },
    }
    receipt = PrivateChatQueryWorkflowReceipt.model_validate(seal(body, "receipt_sha256"))
    validate_private_chat_query_workflow_receipt(
        receipt,
        completed.request,
        completed.policy,
        completed.bundle,
        launch,
        completed.native,
        completed.result,
        origin=completed.expected["origin"],
        workflow_id=launch.workflow_id,
        step_run_id=launch.step_run_id,
        query_artifact_owner_job_id=receipt.query_artifact_owner_job_id,
        receipt_owner_job_id=identity.job_id,
    )
    root, workspace = tmp_path / "artifacts", tmp_path / "workspaces"
    root.mkdir(mode=0o700)
    workspace.mkdir(mode=0o700)
    publisher = ControlFileSetPublisher(
        guarded_engine,
        Settings(
            staging_root=tmp_path / "staging", nas_artifact_root=root, workspace_root=workspace
        ),
    )
    return NativeEmbeddingCompletionPublisher(publisher, source_commit="a" * 40), receipt, identity


def assert_original(publisher, receipt, identity, output):
    with publisher.publisher.sessions.begin() as session:
        assert (
            resolve_native_private_chat_query_completion(
                session,
                CatalogSettings(nas_artifact_root=publisher.publisher.settings.nas_artifact_root),
                output,
            )
            == receipt
        )
        job = session.get(JobRecord, identity.job_id)
        revision = session.get(ArtifactRevisionRecord, identity.artifact_revision_id)
        assert job.status == "SUCCEEDED" and job.worker_slot_id is None
        assert revision.job_id == identity.job_id and revision.approved is True
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.job_id == identity.job_id)
            )
            == 1
        )
        assert TEXT.encode() not in canonical_json_bytes(job.request)
        assert TEXT.encode() not in canonical_json_bytes(revision.result)
        assert (Path(revision.nas_path) / "receipt.json").read_bytes() == canonical_json_bytes(
            receipt
        )
        assert len(revision.manifest["files"]) == 1
    assert tuple(publisher.publisher.settings.workspace_root.iterdir()) == ()


def test_two_postgres_publishers_commit_one_original_private_receipt(private_completion):
    publisher, receipt, identity = private_completion
    barrier = Barrier(2)

    def run(_ordinal):
        barrier.wait(timeout=20)
        return publisher.publish_private_chat_query(receipt, identity=identity)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = tuple(pool.map(run, range(2)))
    assert first == second == publisher.publish_private_chat_query(receipt, identity=identity)
    assert_original(publisher, receipt, identity, first)


@pytest.mark.parametrize("phase", ["before_commit", "after_commit"])
def test_private_receipt_interruption_never_reexecutes_or_reallocates(
    private_completion, monkeypatch, phase
):
    publisher, receipt, identity = private_completion
    original = (
        publication.create_artifact_records
        if phase == "before_commit"
        else publisher.publisher.publish_identified
    )

    def interrupted(*args, **kwargs):
        if phase == "after_commit":
            original(*args, **kwargs)
        raise RuntimeError("isolated private receipt observation interruption")

    target, name = (
        (publication, "create_artifact_records")
        if phase == "before_commit"
        else (publisher.publisher, "publish_identified")
    )
    monkeypatch.setattr(target, name, interrupted)
    with pytest.raises(RuntimeError):
        publisher.publish_private_chat_query(receipt, identity=identity)
    monkeypatch.setattr(target, name, original)
    output = publisher.publish_private_chat_query(receipt, identity=identity)
    assert_original(publisher, receipt, identity, output)


@pytest.mark.parametrize("fault", ["request", "origin", "time", "identity"])
def test_changed_private_intent_cannot_bypass_original_postgres_key(private_completion, fault):
    publisher, receipt, identity = private_completion
    first = publisher.publish_private_chat_query(receipt, identity=identity)
    body = receipt.model_dump(mode="json")
    selected = identity
    if fault == "identity":
        selected = ControlFileSetIdentity(
            "job_" + uuid4().hex, "artifact_" + uuid4().hex, "rev_" + uuid4().hex
        )
        body["receipt_owner_job_id"] = selected.job_id
    elif fault == "time":
        body["published_at"] = (
            (receipt.published_at + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        )
    else:
        body["workflow_request_sha256" if fault == "request" else "origin_sha256"] = (
            "sha256:" + "f" * 64
        )
    changed = PrivateChatQueryWorkflowReceipt.model_validate(seal(body, "receipt_sha256"))
    with pytest.raises(ControlPlaneError):
        publisher.publish_private_chat_query(changed, identity=selected)
    assert publisher.publish_private_chat_query(receipt, identity=identity) == first
    assert_original(publisher, receipt, identity, first)
    if fault == "identity":
        with publisher.publisher.sessions() as session:
            assert session.get(JobRecord, selected.job_id) is None


@pytest.mark.parametrize("fault", ["job", "revision"])
def test_private_read_rechecks_mutable_producer_and_preserves_immutable_artifacts(
    private_completion, monkeypatch, fault
):
    publisher, receipt, identity = private_completion
    output = publisher.publish_private_chat_query(receipt, identity=identity)
    settings = CatalogSettings(nas_artifact_root=publisher.publisher.settings.nas_artifact_root)
    with publisher.publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext(session, settings)
        original = reader.read_pinned

        def revoke_after_read(**kwargs):
            member = original(**kwargs)
            if fault == "job":
                with publisher.publisher.sessions.begin() as other:
                    other.execute(
                        update(JobRecord)
                        .where(JobRecord.job_id == identity.job_id)
                        .values(status="RUNNING")
                    )
            else:
                # PostgreSQL already forbids changing an approved Artifact revision.
                # Preserve that stronger invariant, rather than disabling its trigger.
                with (
                    pytest.raises(DBAPIError) as blocked,
                    publisher.publisher.sessions.begin() as other,
                ):
                    other.execute(
                        update(ArtifactRevisionRecord)
                        .where(ArtifactRevisionRecord.revision_id == identity.artifact_revision_id)
                        .values(approved=False)
                    )
                assert blocked.value.orig.sqlstate == "P0001"
                assert blocked.value.orig.diag.message_primary == (
                    "approved EOM artifacts and revisions are immutable"
                )
            return member

        monkeypatch.setattr(reader, "read_pinned", revoke_after_read)
        if fault == "job":
            with pytest.raises(ValueError):
                resolve_native_private_chat_query_completion(
                    session, settings, output, artifact_reader=reader
                )
        else:
            assert (
                resolve_native_private_chat_query_completion(
                    session, settings, output, artifact_reader=reader
                )
                == receipt
            )
