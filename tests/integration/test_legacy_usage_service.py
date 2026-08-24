from __future__ import annotations

import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import eom_identity_service.models  # noqa: F401
import pytest
from eom_catalog_contracts import (
    CommitLegacyUsageImportCommand,
    CreateLegacyUsageImportCommand,
    LegacyUsageMappingContractRevision,
    LegacyUsageSourcePointer,
    ReviewLegacyUsageRowCommand,
)
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.legacy_usage_models import (
    AssessmentFormRecord,
    LegacyUsageImportRecord,
    LegacyUsageRowReviewRecord,
    ProductUsageProjectionRecord,
    UsageRecordV1Record,
)
from eom_catalog_service.legacy_usage_service import LegacyUsageError, LegacyUsageService
from eom_catalog_service.models import (
    ContentIntakeBatchRecord,
    ContentIntakeSourceFileRecord,
    ContentPackRecord,
    ContentPackReleaseRecord,
    DeliverableRecord,
    DeliverableRevisionRecord,
    ItemRecord,
    ItemRevisionRecord,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import ArtifactRevisionRecord
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.integration

ACTOR = "operator_phase11"
NOW = datetime(2026, 8, 24, 10, 30, tzinfo=UTC)
XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HEADERS = (
    "source_row_key",
    "deliverable_id",
    "deliverable_revision_id",
    "assessment_form_id",
    "assessment_form_revision_id",
    "assessment_form_revision_number",
    "assessment_form_key",
    "assessment_form_ordinal",
    "assessment_form_label",
    "item_id",
    "item_revision_id",
    "item_manifest_sha256",
    "section_key",
    "section_ordinal",
    "position",
    "display_number",
    "points_milli",
    "usage_role",
    "publication_id",
    "publication_revision_id",
    "publication_revision_number",
    "publication_key",
    "publication_date",
)


def _column(index: int) -> str:
    value = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        value = chr(ord("A") + remainder) + value
    return value


def _workbook(path: Path, rows: tuple[tuple[str, ...], ...]) -> None:
    header_cells = "".join(
        f'<c r="{_column(index)}1" t="inlineStr"><is><t>{value}</t></is></c>'
        for index, value in enumerate(HEADERS, 1)
    )
    data_rows = "".join(
        f'<row r="{row_number}">'
        + "".join(
            f'<c r="{_column(index)}{row_number}" t="inlineStr"><is><t>{value}</t></is></c>'
            for index, value in enumerate(values, 1)
        )
        + "</row>"
        for row_number, values in enumerate(rows, 2)
    )
    members = {
        "[Content_Types].xml": (
            '<?xml version="1.0"?><Types '
            'xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/></Types>'
        ),
        "xl/workbook.xml": (
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="placements" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": (
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData><row r="1">{header_cells}</row>{data_rows}'
            "</sheetData></worksheet>"
        ),
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)


def _mapping(suffix: str) -> LegacyUsageMappingContractRevision:
    value = {
        "schema_version": "legacy-usage-mapping-contract/1.0",
        "mapping_contract_id": "legacymap_" + suffix,
        "mapping_contract_revision_id": "legacymaprev_" + suffix,
        "revision_number": 1,
        "state": "RELEASED",
        "workbook_media_type": XLSX_MEDIA,
        "worksheet_name": "placements",
        "header_row": 1,
        "first_data_row": 2,
        "maximum_rows": 100,
        "columns": {header: header for header in HEADERS},
        "normalization_policy": "legacy-usage-normalization/1.0",
        "contract_sha256": "sha256:" + "0" * 64,
        "released_at": NOW,
        "released_by": ACTOR,
    }
    mapping = LegacyUsageMappingContractRevision.model_validate(value)
    canonical = mapping.model_dump(mode="json", exclude={"contract_sha256"})
    return mapping.model_copy(update={"contract_sha256": content_sha256(canonical)})


def _seed(
    engine: Engine,
    tmp_path: Path,
    *,
    duplicate_source_row: bool = False,
    workbook_item_sha: str | None = None,
) -> tuple[LegacyUsageService, CreateLegacyUsageImportCommand]:
    suffix = uuid4().hex
    item_sha = "sha256:" + "a" * 64
    ids = {
        "deliverable": "deliverable_" + suffix,
        "deliverable_revision": "delivrev_" + suffix,
        "form": "form_" + suffix,
        "form_revision": "formrev_" + suffix,
        "item": "item_" + suffix,
        "item_revision": "itemrev_" + suffix,
        "publication": "publication_" + suffix,
        "publication_revision": "publicationrev_" + suffix,
    }
    workbook = tmp_path / f"usage-{suffix}.xlsx"
    values = (
        "row-001",
        ids["deliverable"],
        ids["deliverable_revision"],
        ids["form"],
        ids["form_revision"],
        "1",
        "form-01",
        "1",
        "1회",
        ids["item"],
        ids["item_revision"],
        workbook_item_sha or item_sha,
        "main",
        "1",
        "12",
        "12",
        "3000",
        "PRIMARY",
        ids["publication"],
        ids["publication_revision"],
        "1",
        "legacy-2026",
        "2026-08-24",
    )
    _workbook(workbook, (values, values) if duplicate_source_row else (values,))
    staging = tmp_path / f"staging-{suffix}"
    nas = tmp_path / f"nas-{suffix}"
    intake = tmp_path / f"intake-{suffix}"
    staging.mkdir()
    nas.mkdir()
    intake.mkdir()
    settings = CatalogSettings(
        staging_root=staging,
        nas_artifact_root=nas,
        intake_root=intake,
    )
    artifact = CatalogArtifactService(engine, settings).commit_file_set(
        files={"source/usage.xlsx": workbook},
        primary_file="source/usage.xlsx",
        artifact_type="content-intake-source",
        idempotency_key=f"phase11-source:{suffix}",
        request={"fixture": suffix},
        result={"fixture": suffix},
        file_metadata={
            "source/usage.xlsx": {
                "schema_ref": "eom://schemas/legacy-usage/workbook/1.0",
                "media_type": XLSX_MEDIA,
            }
        },
    )
    sessions = build_session_factory(engine)
    definition = WorkflowDefinitionRecord(
        definition_id="wfdef_" + suffix,
        definition_key=f"phase11-{suffix}",
        definition_version="1.0.0",
        schema_version="1.0",
        canonical_definition={"fixture": suffix},
        definition_hash="sha256:" + "b" * 64,
        active=True,
        source_path="phase11-fixture.yaml",
    )
    workflow = WorkflowInstanceRecord(
        workflow_id="workflow_" + suffix,
        definition_id=definition.definition_id,
        definition_key=definition.definition_key,
        definition_version=definition.definition_version,
        definition_hash=definition.definition_hash,
        protocol_version="1.0.1",
        role_schema_version="1.0",
        state="COMPLETED",
        stage="COMPLETED",
        current_step_key="complete",
        request_payload={"fixture": suffix},
        initial_request={"fixture": suffix},
        runtime_context={},
        idempotency_key=f"phase11-workflow:{suffix}",
        request_hash="sha256:" + "c" * 64,
        lock_version=1,
        rework_cycle_count=0,
        created_actor_type="human",
        created_actor_id=ACTOR,
    )
    step = WorkflowStepRunRecord(
        step_run_id="steprun_" + suffix,
        workflow_id=workflow.workflow_id,
        step_key="registration",
        attempt=1,
        step_type="agent",
        worker_role="item_management",
        result_schema="registration-result@1.0",
        state="SUCCEEDED",
        platform_job_id=artifact.job_id,
        input_pointer_manifest={},
        output_pointer_manifest={},
    )
    pack = ContentPackRecord(
        content_pack_id="contentpack_" + suffix,
        pack_key=f"phase11-{suffix}",
        display_name="Phase 11",
        description="Legacy usage integration fixture",
        locale="ko-KR",
        domain_key="INTEGRATION",
    )
    release = ContentPackReleaseRecord(
        content_pack_release_id="packrel_" + suffix,
        content_pack_id=pack.content_pack_id,
        version="1.0.0",
        schema_version="1.0",
        state="RELEASED",
        source_tree_sha256=content_sha256({"source_tree": suffix}),
        bundle_sha256=content_sha256({"bundle": suffix}),
        manifest_sha256=content_sha256({"manifest": suffix}),
        bundle_artifact_id=artifact.artifact_id,
        bundle_artifact_revision_id=artifact.revision_id,
        canonical_manifest_json={"fixture": suffix},
        compatibility_json={},
        lock_version=1,
    )
    item = ItemRecord(
        item_id=ids["item"],
        lifecycle_state="ACTIVE",
        current_revision_id=None,
        created_by=ACTOR,
        lock_version=1,
    )
    item_revision = ItemRevisionRecord(
        item_revision_id=ids["item_revision"],
        item_id=item.item_id,
        revision_number=1,
        revision_state="APPROVED",
        registration_key=f"phase11:{suffix}",
        content_pack_release_id=release.content_pack_release_id,
        workflow_id=workflow.workflow_id,
        workflow_definition_version=workflow.definition_version,
        source_workflow_step_run_id=step.step_run_id,
        manifest_artifact_id=artifact.artifact_id,
        manifest_artifact_revision_id=artifact.revision_id,
        manifest_sha256=item_sha,
        item_type_key="single-choice",
        primary_taxonomy_ref="science:earth",
        difficulty_band="medium",
        metadata_json={"fixture": suffix},
        metadata_sha256="sha256:" + "1" * 64,
        created_by=ACTOR,
        approved_at=NOW,
        approved_by=ACTOR,
        lock_version=1,
    )
    product = DeliverableRecord(
        deliverable_id=ids["deliverable"],
        deliverable_key=f"phase11-{suffix}",
        deliverable_type="MOCK_EXAM",
        title="Phase 11 Mock",
        edition="2026",
        lifecycle_state="RELEASED",
        created_by=ACTOR,
    )
    product_revision = DeliverableRevisionRecord(
        deliverable_revision_id=ids["deliverable_revision"],
        deliverable_id=product.deliverable_id,
        revision_number=1,
        state="RELEASED",
        metadata_json={"fixture": suffix},
        metadata_sha256="sha256:" + "2" * 64,
        released_at=NOW,
    )
    intake_batch_id = "intake_" + suffix
    source_file_id = "sourcefile_" + suffix
    batch = ContentIntakeBatchRecord(
        intake_batch_id=intake_batch_id,
        batch_name="Phase 11 workbook",
        state="ACCEPTED",
        purpose="legacy usage integration",
        received_by=ACTOR,
        source_owner_type="legacy_system",
        source_owner_reference="phase11",
        source_manifest_artifact_id=artifact.artifact_id,
        source_manifest_artifact_revision_id=artifact.revision_id,
        source_manifest_sha256=artifact.manifest_hash,
        source_fingerprint=content_sha256({"fixture": suffix}),
        accepted_at=NOW,
        lock_version=1,
    )
    source = ContentIntakeSourceFileRecord(
        source_file_id=source_file_id,
        intake_batch_id=intake_batch_id,
        original_filename=workbook.name,
        normalized_filename=workbook.name,
        relative_path="source/usage.xlsx",
        media_type=XLSX_MEDIA,
        size_bytes=workbook.stat().st_size,
        sha256=sha256_bytes(workbook.read_bytes()),
        artifact_id=artifact.artifact_id,
        artifact_revision_id=artifact.revision_id,
        declared_role="DATA",
        declared_description="Reviewed legacy usage workbook",
    )
    with transaction(sessions) as session:
        session.add(definition)
        session.flush()
        session.add_all((workflow, pack, product, batch))
        session.flush()
        session.add_all((step, release, product_revision, source, item))
        session.flush()
        session.add(item_revision)
        session.flush()
        item.current_revision_id = item_revision.item_revision_id
    service = LegacyUsageService(engine, settings=settings, clock=lambda: NOW)
    mapping = _mapping(suffix)
    service.release_mapping(f"legacy-{suffix}", mapping)
    pointer = LegacyUsageSourcePointer(
        intake_batch_id=intake_batch_id,
        source_file_id=source_file_id,
        artifact_id=artifact.artifact_id,
        artifact_revision_id=artifact.revision_id,
        member_path="source/usage.xlsx",
        schema_ref="eom://schemas/legacy-usage/workbook/1.0",
        media_type=XLSX_MEDIA,
        sha256=source.sha256,
    )
    value = {
        "source": pointer.model_dump(mode="json"),
        "mapping_contract_revision_id": mapping.mapping_contract_revision_id,
        "mapping_contract_sha256": mapping.contract_sha256,
        "requested_by": ACTOR,
    }
    command = CreateLegacyUsageImportCommand.model_validate(
        value
        | {
            "idempotency_key": f"phase11-import:{suffix}",
            "request_sha256": content_sha256(value),
        }
    )
    return service, command


def test_legacy_usage_import_review_commit_and_reverse_projection(
    integration_engine: Engine, tmp_path: Path
) -> None:
    service, command = _seed(integration_engine, tmp_path)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(service.create_import, (command, command)))
    assert results[0].manifest.legacy_usage_import_id == results[1].manifest.legacy_usage_import_id
    assert results[0].manifest.row_count == 1
    assert results[0].manifest.resolved_count == 1
    row = results[0].rows[0]
    assert row.proposal_state == "RESOLVED"
    review = ReviewLegacyUsageRowCommand(
        legacy_usage_row_id=row.legacy_usage_row_id,
        decision="APPROVE",
        actor_id=ACTOR,
        idempotency_key="phase11-review:" + row.legacy_usage_row_id,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        decisions = list(executor.map(service.review_row, (review, review)))
    assert decisions[0].legacy_usage_review_id == decisions[1].legacy_usage_review_id
    commit = CommitLegacyUsageImportCommand(
        legacy_usage_import_id=results[0].manifest.legacy_usage_import_id,
        actor_id=ACTOR,
        idempotency_key="phase11-commit:" + results[0].manifest.legacy_usage_import_id,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        committed = list(executor.map(service.commit_import, (commit, commit)))
    assert committed[0].commit_sha256 == committed[1].commit_sha256
    assert committed[0].usage_record_count == 1
    assert committed[0].projection == committed[1].projection
    sessions = build_session_factory(integration_engine)
    with sessions() as session:
        import_record = session.get(
            LegacyUsageImportRecord, results[0].manifest.legacy_usage_import_id
        )
        assert import_record is not None and import_record.state == "COMMITTED"
        usages = list(
            session.scalars(
                select(UsageRecordV1Record).where(
                    UsageRecordV1Record.item_revision_id == row.resolved.item_revision_id  # type: ignore[union-attr]
                )
            )
        )
        assert len(usages) == 1
        assert usages[0].legacy_usage_row_id == row.legacy_usage_row_id
        assert session.get(AssessmentFormRecord, row.resolved.assessment_form_id) is not None  # type: ignore[union-attr]
        assert (
            session.scalar(
                select(ProductUsageProjectionRecord).where(
                    ProductUsageProjectionRecord.legacy_usage_import_id
                    == import_record.legacy_usage_import_id
                )
            )
            is not None
        )
        assert (
            session.scalar(
                select(LegacyUsageRowReviewRecord).where(
                    LegacyUsageRowReviewRecord.legacy_usage_row_id == row.legacy_usage_row_id
                )
            )
            is not None
        )
    with integration_engine.connect() as connection:
        attempted_mutation = connection.begin()
        with pytest.raises(DBAPIError, match="immutable"):
            connection.execute(
                text(
                    "UPDATE app.usage_records_v1 SET points_milli = 0 "
                    "WHERE usage_record_id = :usage_record_id"
                ),
                {"usage_record_id": usages[0].usage_record_id},
            )
        attempted_mutation.rollback()
    with integration_engine.connect() as connection:
        attempted_mutation = connection.begin()
        with pytest.raises(DBAPIError, match="immutable fields"):
            connection.execute(
                text(
                    "UPDATE app.legacy_usage_imports SET source_sha256 = :sha256 "
                    "WHERE legacy_usage_import_id = :legacy_usage_import_id"
                ),
                {
                    "sha256": "sha256:" + "9" * 64,
                    "legacy_usage_import_id": results[0].manifest.legacy_usage_import_id,
                },
            )
        attempted_mutation.rollback()


def test_duplicate_source_rows_are_preserved_as_conflicts(
    integration_engine: Engine, tmp_path: Path
) -> None:
    service, command = _seed(integration_engine, tmp_path, duplicate_source_row=True)
    proposals = service.create_import(command)
    assert proposals.manifest.row_count == 2
    assert proposals.manifest.conflict_count == 2
    assert {row.proposal_state for row in proposals.rows} == {"CONFLICT"}
    assert len({row.legacy_usage_row_id for row in proposals.rows}) == 2
    assert {row.source_row_key for row in proposals.rows} == {"row-001"}
    with pytest.raises(LegacyUsageError) as captured:
        service.review_row(
            ReviewLegacyUsageRowCommand(
                legacy_usage_row_id=proposals.rows[0].legacy_usage_row_id,
                decision="APPROVE",
                actor_id=ACTOR,
                idempotency_key="phase11-invalid-review:" + proposals.rows[0].legacy_usage_row_id,
            )
        )
    assert captured.value.code == "LEGACY_USAGE_ROW_NOT_RESOLVED"


def test_rejected_hash_conflict_commits_no_canonical_usage(
    integration_engine: Engine, tmp_path: Path
) -> None:
    service, command = _seed(
        integration_engine,
        tmp_path,
        workbook_item_sha="sha256:" + "8" * 64,
    )
    proposals = service.create_import(command)
    assert proposals.manifest.conflict_count == 1
    row = proposals.rows[0]
    assert row.reason_codes == ("ITEM_HASH_MISMATCH",)
    service.review_row(
        ReviewLegacyUsageRowCommand(
            legacy_usage_row_id=row.legacy_usage_row_id,
            decision="REJECT",
            actor_id=ACTOR,
            idempotency_key="phase11-reject:" + row.legacy_usage_row_id,
        )
    )
    result = service.commit_import(
        CommitLegacyUsageImportCommand(
            legacy_usage_import_id=proposals.manifest.legacy_usage_import_id,
            actor_id=ACTOR,
            idempotency_key="phase11-empty-commit:" + proposals.manifest.legacy_usage_import_id,
        )
    )
    assert result.usage_record_count == 0
    assert result.projection.nodes == ()
    assert result.projection.edges == ()
    suffix = command.mapping_contract_revision_id.removeprefix("legacymaprev_")
    sessions = build_session_factory(integration_engine)
    with sessions() as session:
        assert not list(
            session.scalars(
                select(UsageRecordV1Record).where(
                    UsageRecordV1Record.legacy_usage_import_id
                    == proposals.manifest.legacy_usage_import_id
                )
            )
        )
        assert session.get(AssessmentFormRecord, "form_" + suffix) is None


def test_changed_canonical_workbook_fails_before_import(
    integration_engine: Engine, tmp_path: Path
) -> None:
    service, command = _seed(integration_engine, tmp_path)
    sessions = build_session_factory(integration_engine)
    with sessions() as session:
        revision = session.get(ArtifactRevisionRecord, command.source.artifact_revision_id)
        assert revision is not None
        source_path = Path(revision.nas_path) / command.source.member_path
    source_path.write_bytes(b"tampered disposable workbook")
    with pytest.raises(LegacyUsageError) as captured:
        service.create_import(command)
    assert captured.value.code == "LEGACY_USAGE_SOURCE_HASH_MISMATCH"
    with sessions() as session:
        assert (
            session.scalar(
                select(LegacyUsageImportRecord).where(
                    LegacyUsageImportRecord.source_file_id == command.source.source_file_id
                )
            )
            is None
        )
