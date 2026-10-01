from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from eom_catalog_contracts import ApproveItemRevisionCommandV1, ItemRevisionApprovalReceiptV1
from eom_catalog_service.models import (
    ContentPackRecord,
    ContentPackReleaseRecord,
    ItemComponentRecord,
    ItemEventRecord,
    ItemMetadataSnapshotRecord,
    ItemRecord,
    ItemRevisionRecord,
)
from eom_catalog_service.registry_service import RegistryService
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, content_sha256, new_job_id
from eom_item_registry import RegistryError, RegistryErrorCode
from eom_item_registry.identifiers import new_item_component_id, new_item_metadata_id
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_orchestrator.repository import ensure_protocol_version
from eom_workflow import compile_definition
from eom_workflow_runner.models import (
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import import_workflow_definition
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

PROTOCOL_VERSION = "item-approval-integration/1.0"
PROTOCOL_SHA256 = "sha256:" + "a" * 64


@dataclass(frozen=True)
class ApprovalFixture:
    item_id: str
    item_revision_id: str
    manifest_artifact_id: str
    manifest_artifact_revision_id: str
    manifest_sha256: str
    hwpx_artifact_id: str
    hwpx_artifact_revision_id: str
    hwpx_sha256: str
    hwpx_build_id: str


def _opaque(prefix: str) -> str:
    return prefix + uuid4().hex


def _artifact(
    session: Session,
    root: Path,
    *,
    artifact_type: str,
    file_name: str,
    payload: bytes,
    manifest_extra: dict[str, object] | None = None,
    result: dict[str, object] | None = None,
) -> tuple[ArtifactRecord, ArtifactRevisionRecord]:
    job_id = new_job_id()
    artifact_id = _opaque("artifact_")
    revision_id = _opaque("rev_")
    content_hash = "sha256:" + hashlib.sha256(payload).hexdigest()
    artifact_root = root / revision_id
    artifact_root.mkdir(parents=True)
    (artifact_root / file_name).write_bytes(payload)
    manifest: dict[str, object] = {
        "manifest_version": "catalog-file-set/1.0",
        "artifact_type": artifact_type,
        "primary_file": file_name,
        "content_hash": content_hash,
        "files": [{"file_name": file_name, "sha256": content_hash, "bytes": len(payload)}],
        **(manifest_extra or {}),
    }
    job = JobRecord(
        job_id=job_id,
        protocol_version=PROTOCOL_VERSION,
        idempotency_key=f"item-approval-integration-{uuid4().hex}",
        request_hash=content_sha256({"job_id": job_id}),
        task_type=artifact_type,
        request={"fixture": True},
        status="SUCCEEDED",
        logical_artifact_id=artifact_id,
        revision_id=revision_id,
        completed_at=datetime.now(UTC),
    )
    artifact = ArtifactRecord(
        logical_artifact_id=artifact_id,
        job_id=job_id,
        artifact_type=artifact_type,
        approved=True,
    )
    revision = ArtifactRevisionRecord(
        revision_id=revision_id,
        logical_artifact_id=artifact_id,
        job_id=job_id,
        content_hash=content_hash,
        manifest_hash=content_sha256(manifest),
        content_bytes=len(payload),
        nas_path=str(artifact_root),
        manifest=manifest,
        result=result or {"status": "ok"},
        approved=True,
    )
    session.add(job)
    session.flush()
    session.add(artifact)
    session.flush()
    session.add(revision)
    session.flush()
    return artifact, revision


def _seed_fixture(
    engine: Engine,
    root: Path,
    *,
    manifest_pack_release_override: str | None = None,
) -> ApprovalFixture:
    sessions = build_session_factory(engine)
    with transaction(sessions) as session:
        ensure_protocol_version(session, PROTOCOL_VERSION, PROTOCOL_SHA256)
        session.flush()
        bundle_artifact, bundle_revision = _artifact(
            session,
            root,
            artifact_type="content-pack-bundle",
            file_name="pack.tar",
            payload=f"post-registration-pack-{uuid4().hex}".encode(),
        )
        component_artifact, component_revision = _artifact(
            session,
            root,
            artifact_type="assessment-item-content",
            file_name="item-content.json",
            payload=b'{"schema_version":"3.0"}',
        )
        item_id = _opaque("item_")
        item_revision_id = _opaque("itemrev_")
        workflow_id = _opaque("workflow_")
        step_run_id = _opaque("steprun_")
        pack_id = _opaque("contentpack_")
        pack_release_id = _opaque("packrel_")
        created_at = datetime.now(UTC)
        compiled = compile_definition(
            Path("config/workflows/generic-item-development.v1.16.yaml"),
            {"authoring", "image", "review", "item_management", "support"},
        )
        definition, _ = import_workflow_definition(session, compiled)
        workflow = WorkflowInstanceRecord(
            workflow_id=workflow_id,
            definition_id=definition.definition_id,
            definition_key=definition.definition_key,
            definition_version=definition.definition_version,
            definition_hash=definition.definition_hash,
            protocol_version="1.0.1",
            role_schema_version="1.24.0",
            state="COMPLETED",
            stage="COMPLETED",
            current_step_key="complete",
            request_payload={"fixture": True},
            initial_request={"fixture": True},
            runtime_context={},
            idempotency_key=f"approval-workflow-{uuid4().hex}",
            request_hash="sha256:" + "c" * 64,
            lock_version=1,
            rework_cycle_count=0,
            created_actor_type="human",
            created_actor_id="operator_review",
            created_at=created_at,
        )
        step = WorkflowStepRunRecord(
            step_run_id=step_run_id,
            workflow_id=workflow_id,
            step_key="registration",
            attempt=1,
            step_type="agent",
            worker_role="item_management",
            result_schema="registration-result@12.0",
            state="SUCCEEDED",
            platform_job_id=component_artifact.job_id,
            input_pointer_manifest={},
            output_pointer_manifest={},
        )
        pack = ContentPackRecord(
            content_pack_id=pack_id,
            pack_key=f"approval-pack-{uuid4().hex}",
            display_name="Approval integration pack",
            description="Post-registration approval fixture",
            locale="ko-KR",
            domain_key="INTEGRATED_SCIENCE",
        )
        release = ContentPackReleaseRecord(
            content_pack_release_id=pack_release_id,
            content_pack_id=pack_id,
            version="1.20.13",
            schema_version="1.1",
            state="RELEASED",
            source_tree_sha256="sha256:" + "d" * 64,
            bundle_sha256=bundle_revision.content_hash,
            manifest_sha256="sha256:" + "e" * 64,
            bundle_artifact_id=bundle_artifact.logical_artifact_id,
            bundle_artifact_revision_id=bundle_revision.revision_id,
            canonical_manifest_json={"fixture": True},
            compatibility_json={},
            lock_version=1,
        )
        metadata = {"subject": "통합과학"}
        metadata_sha256 = content_sha256(metadata)
        manifest_value = {
            "schema_version": "2.0",
            "item_id": item_id,
            "item_revision_id": item_revision_id,
            "revision_number": 1,
            "content_pack": {
                "release_id": manifest_pack_release_override or pack_release_id,
                "pack_key": pack.pack_key,
                "version": release.version,
                "sha256": release.bundle_sha256,
            },
            "source_intake": {"batch_ids": []},
            "workflow": {
                "workflow_id": workflow_id,
                "definition_key": definition.definition_key,
                "definition_version": definition.definition_version,
            },
            "components": [
                {
                    "component_type": "ITEM_CONTENT",
                    "ordinal": 0,
                    "schema_ref": "eom.assessment.item-content/3.0",
                    "media_type": "application/json",
                    "artifact_id": component_artifact.logical_artifact_id,
                    "artifact_revision_id": component_revision.revision_id,
                    "sha256": component_revision.content_hash,
                    "logical_name": "item-content.json",
                    "required": True,
                }
            ],
            "metadata": {
                "schema_ref": "eom://metadata/content-team-item@1.0",
                "sha256": metadata_sha256,
            },
            "provenance": [],
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "revision_state": "IN_REVIEW",
            "approval_policy": {
                "mode": "POST_REGISTRATION_HUMAN_REVIEW",
                "initial_revision_state": "IN_REVIEW",
                "required_review_artifact": "VALIDATED_HWPX",
            },
        }
        manifest_artifact, manifest_revision = _artifact(
            session,
            root,
            artifact_type="item-revision-manifest",
            file_name="item-revision-manifest.json",
            payload=canonical_json_bytes(manifest_value),
        )
        hwpx_build_id = _opaque("hwpxbuild_")
        hwpx_bytes = b"PK\x03\x04validated-review-hwpx"
        hwpx_sha256 = "sha256:" + hashlib.sha256(hwpx_bytes).hexdigest()
        hwpx_artifact, hwpx_revision = _artifact(
            session,
            root,
            artifact_type="hwpx-content-team-build",
            file_name="content-team-item.hwpx",
            payload=hwpx_bytes,
            manifest_extra={
                "manifest_version": "content-team-hwpx-artifact/1.0",
                "artifact_type": "hwpx-content-team-build",
                "content_hash": hwpx_sha256,
            },
            result={
                "builder_result": {
                    "status": "SUCCEEDED",
                    "build_id": hwpx_build_id,
                    "item_revision_id": item_revision_id,
                    "output_sha256": hwpx_sha256,
                }
            },
        )
        item = ItemRecord(
            item_id=item_id,
            lifecycle_state="ACTIVE",
            created_by="operator_review",
            lock_version=1,
        )
        session.add_all((workflow, step, pack, release, item))
        session.flush()
        revision = ItemRevisionRecord(
            item_revision_id=item_revision_id,
            item_id=item_id,
            revision_number=1,
            revision_state="IN_REVIEW",
            registration_key=f"approval-registration-{uuid4().hex}",
            content_pack_release_id=pack_release_id,
            workflow_id=workflow_id,
            workflow_definition_version="1.16.0",
            source_workflow_step_run_id=step_run_id,
            manifest_artifact_id=manifest_artifact.logical_artifact_id,
            manifest_artifact_revision_id=manifest_revision.revision_id,
            manifest_sha256=manifest_revision.content_hash,
            item_type_key="eom-template-multiple-choice",
            primary_taxonomy_ref="GENERAL_SCIENCE",
            difficulty_band="보통",
            metadata_json=metadata,
            metadata_sha256=metadata_sha256,
            created_by="operator_review",
            lock_version=1,
        )
        session.add(revision)
        session.flush()
        item.current_revision_id = item_revision_id
        session.add_all(
            (
                ItemComponentRecord(
                    item_component_id=new_item_component_id(),
                    item_revision_id=item_revision_id,
                    component_type="ITEM_CONTENT",
                    ordinal=0,
                    schema_ref="eom.assessment.item-content/3.0",
                    media_type="application/json",
                    artifact_id=component_artifact.logical_artifact_id,
                    artifact_revision_id=component_revision.revision_id,
                    sha256=component_revision.content_hash,
                    logical_name="item-content.json",
                    required=True,
                    metadata_json={},
                ),
                ItemMetadataSnapshotRecord(
                    item_metadata_snapshot_id=new_item_metadata_id(),
                    item_revision_id=item_revision_id,
                    schema_ref="eom://metadata/content-team-item@1.0",
                    schema_version="1.0",
                    taxonomy_refs=["GENERAL_SCIENCE"],
                    tag_keys=[],
                    difficulty_band="보통",
                    item_type_key="eom-template-multiple-choice",
                    estimated_time_seconds=None,
                    metadata_json=metadata,
                    metadata_sha256=metadata_sha256,
                ),
            )
        )
    return ApprovalFixture(
        item_id=item_id,
        item_revision_id=item_revision_id,
        manifest_artifact_id=manifest_artifact.logical_artifact_id,
        manifest_artifact_revision_id=manifest_revision.revision_id,
        manifest_sha256=manifest_revision.content_hash,
        hwpx_artifact_id=hwpx_artifact.logical_artifact_id,
        hwpx_artifact_revision_id=hwpx_revision.revision_id,
        hwpx_sha256=hwpx_revision.content_hash,
        hwpx_build_id=hwpx_build_id,
    )


def _command(
    fixture: ApprovalFixture, *, key: str, reason: str = "HWPX 검토 완료"
) -> ApproveItemRevisionCommandV1:
    body = {
        "operation": "APPROVE_ITEM_REVISION",
        "item_revision_id": fixture.item_revision_id,
        "expected_revision_version": 1,
        "hwpx_build_id": fixture.hwpx_build_id,
        "hwpx_output_artifact_id": fixture.hwpx_artifact_id,
        "hwpx_output_artifact_revision_id": fixture.hwpx_artifact_revision_id,
        "hwpx_output_sha256": fixture.hwpx_sha256,
        "reason": reason,
        "approved_by": "operator_review",
        "idempotency_key": key,
    }
    return ApproveItemRevisionCommandV1.model_validate(
        body | {"submission_sha256": content_sha256(body)}
    )


def _settings(tmp_path: Path) -> CatalogSettings:
    return CatalogSettings(
        staging_root=tmp_path / "staging",
        nas_artifact_root=tmp_path / "artifacts",
        intake_root=tmp_path / "intake",
    )


def test_approval_is_atomic_and_exact_replay_returns_one_receipt(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    fixture = _seed_fixture(integration_engine, tmp_path / "files")
    service = RegistryService(integration_engine, _settings(tmp_path))
    command = _command(fixture, key=f"approval-replay-{uuid4().hex}")

    first = service.approve_revision(command)
    replay = service.approve_revision(command)
    assert replay == first
    assert isinstance(first, ItemRevisionApprovalReceiptV1)

    sessions = build_session_factory(integration_engine)
    with sessions() as session:
        revision = session.get(ItemRevisionRecord, fixture.item_revision_id)
        assert revision is not None
        assert revision.revision_state == "APPROVED"
        assert revision.lock_version == 2
        events = tuple(
            session.scalars(
                select(ItemEventRecord).where(
                    ItemEventRecord.item_revision_id == fixture.item_revision_id,
                    ItemEventRecord.event_type == "ITEM_REVISION_APPROVED",
                )
            )
        )
        assert len(events) == 1
        assert events[0].payload["approval_receipt"]["receipt_sha256"] == first.receipt_sha256

    conflict = _command(fixture, key=command.idempotency_key, reason="다른 승인 입력")
    with pytest.raises(RegistryError) as captured:
        service.approve_revision(conflict)
    assert captured.value.code == RegistryErrorCode.ITEM_APPROVAL_RECEIPT_INVALID


def test_concurrent_approval_serializes_to_one_receipt(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    fixture = _seed_fixture(integration_engine, tmp_path / "files")
    service = RegistryService(integration_engine, _settings(tmp_path))
    commands = (
        _command(fixture, key=f"approval-concurrent-a-{uuid4().hex}"),
        _command(fixture, key=f"approval-concurrent-b-{uuid4().hex}"),
    )

    def approve(command: ApproveItemRevisionCommandV1) -> object:
        try:
            return service.approve_revision(command)
        except RegistryError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(approve, commands))
    assert sum(isinstance(result, ItemRevisionApprovalReceiptV1) for result in results) == 1
    errors = tuple(result for result in results if isinstance(result, RegistryError))
    assert len(errors) == 1
    assert errors[0].code == RegistryErrorCode.CATALOG_CONCURRENCY_CONFLICT

    sessions = build_session_factory(integration_engine)
    with sessions() as session:
        event_count = session.scalar(
            select(func.count())
            .select_from(ItemEventRecord)
            .where(
                ItemEventRecord.item_revision_id == fixture.item_revision_id,
                ItemEventRecord.event_type == "ITEM_REVISION_APPROVED",
            )
        )
        assert event_count == 1


def test_manifest_identity_drift_fails_before_approval_mutation(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    fixture = _seed_fixture(
        integration_engine,
        tmp_path / "files",
        manifest_pack_release_override=_opaque("packrel_"),
    )
    service = RegistryService(integration_engine, _settings(tmp_path))
    command = _command(fixture, key=f"approval-manifest-drift-{uuid4().hex}")

    with pytest.raises(RegistryError) as captured:
        service.approve_revision(command)
    assert captured.value.code == RegistryErrorCode.ITEM_MANIFEST_INVALID

    sessions = build_session_factory(integration_engine)
    with sessions() as session:
        revision = session.get(ItemRevisionRecord, fixture.item_revision_id)
        assert revision is not None
        assert revision.revision_state == "IN_REVIEW"
        assert revision.lock_version == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(ItemEventRecord)
                .where(
                    ItemEventRecord.item_revision_id == fixture.item_revision_id,
                    ItemEventRecord.event_type == "ITEM_REVISION_APPROVED",
                )
            )
            == 0
        )
