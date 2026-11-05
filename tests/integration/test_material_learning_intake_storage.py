"""Real Artifact/Catalog durable intake, replay and progress on a guarded disposable DB."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eom_catalog_contracts.material_learning_intake import (
    CreateMaterialLearningCommand,
    GetMaterialLearningRunQuery,
    ListMaterialLearningRunsQuery,
    MaterialSourceUploadCommand,
)
from eom_catalog_service.material_learning_intake import MaterialLearningIntakeService
from eom_catalog_service.material_learning_read import MaterialLearningReadService
from eom_catalog_service.material_learning_source import (
    MaterialLearningSourceError,
    MaterialLearningSourceService,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import sha256_bytes
from eom_identity_service.models import OperatorRecord, OperatorRoleAssignmentRecord, RoleRecord
from eom_identity_service.repository import seed_builtin_rbac
from eom_orchestrator.repository import IdempotencyConflict
from sqlalchemy import select
from sqlalchemy.orm import Session

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def material_intake(creative_engine, tmp_path):
    actor = "operator_" + uuid4().hex
    with Session(creative_engine) as session, session.begin():
        seed_builtin_rbac(session)
        session.add(
            OperatorRecord(
                operator_id=actor,
                username=actor,
                normalized_username=actor,
                display_name="Synthetic intake owner",
                status="ACTIVE",
                must_change_password=False,
                role_version=1,
                created_by="disposable-material-test",
            )
        )
        session.flush()
        admin = session.scalar(select(RoleRecord).where(RoleRecord.role_key == "ADMIN"))
        assert admin is not None
        session.add(
            OperatorRoleAssignmentRecord(
                operator_role_assignment_id="roleassign_" + uuid4().hex,
                operator_id=actor,
                role_id=admin.role_id,
                assigned_by="disposable-material-test",
                assigned_at=datetime.now(UTC),
            )
        )
    staging = tmp_path / "staging"
    nas = tmp_path / "nas"
    staging.mkdir()
    nas.mkdir()
    settings = CatalogSettings(staging_root=staging, nas_artifact_root=nas)
    payload = b"%PDF-1.7\nsynthetic source; document parser not invoked in source intake\n"
    path = tmp_path / "source.pdf"
    path.write_bytes(payload)
    path.chmod(0o600)
    command = MaterialSourceUploadCommand(
        actor_id=actor,
        original_filename="test.pdf",
        source_format="PDF",
        media_type="application/pdf",
        content_length=len(payload),
        sha256=sha256_bytes(payload),
        rights_confirmed=True,
        idempotency_key="material-source-test-" + uuid4().hex,
    )
    return actor, settings, path, command


def test_raw_source_receipt_replay_and_exact_resolution(creative_engine, material_intake):
    actor, settings, path, command = material_intake
    owner = MaterialLearningSourceService(creative_engine, settings)
    first = owner.ingest(path, command)
    second = owner.ingest(path, command)
    assert first == second
    assert first.original.artifact_id == first.manifest.artifact_id
    assert owner.resolve(first, operator_id=actor).original.sha256 == command.sha256
    changed = command.model_copy(update={"original_filename": "different.pdf"})
    with pytest.raises(IdempotencyConflict):
        owner.ingest(path, changed)


def test_concurrent_create_registers_one_material_run_and_no_second_original(
    creative_engine, material_intake
):
    actor, settings, path, source_command = material_intake
    sources = MaterialLearningSourceService(creative_engine, settings)
    receipt = sources.ingest(path, source_command)
    command = CreateMaterialLearningCommand.model_validate(
        {
            "actor_id": actor,
            "idempotency_key": "material-submit-test-" + uuid4().hex,
            "upload": {
                "title": "문제와 설명 혼합 자료",
                "material_kind": "WORKBOOK",
                "source_description": "synthetic disposable fixture",
                "additional_instructions": "",
                "curriculum_unit_hints": [],
                "rights_confirmed": True,
            },
            "sources": [{"source_role": "MAIN", "source_upload": receipt.model_dump(mode="json")}],
        }
    )

    def submit(_):
        return MaterialLearningIntakeService(creative_engine, settings).create(command)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(submit, range(2)))
    assert results[0].run_id == results[1].run_id
    assert sorted(result.replayed for result in results) == [False, True]
    reads = MaterialLearningReadService(creative_engine)
    recent = reads.recent(ListMaterialLearningRunsQuery(actor_id=actor))
    assert len(recent.runs) == 1
    assert recent.runs[0].state == "RECEIVED"
    detail = reads.inspect(GetMaterialLearningRunQuery(actor_id=actor, run_id=results[0].run_id))
    assert detail.run == recent.runs[0]
    assert detail.tasks == () and detail.next_ordinal is None
    # Reuse the same original Artifact; intake/rights files contain only pointers.
    originals = tuple(settings.nas_artifact_root.rglob("original.pdf"))
    assert len(originals) == 1
    with Session(creative_engine) as session, session.begin():
        operator = session.get(OperatorRecord, actor)
        assert operator is not None
        operator.status = "DISABLED"
    with pytest.raises(MaterialLearningSourceError, match="PERMISSION_DENIED"):
        reads.inspect(GetMaterialLearningRunQuery(actor_id=actor, run_id=results[0].run_id))
