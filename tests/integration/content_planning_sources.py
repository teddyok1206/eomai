"""Synthetic file-free Intake pointers with real foreign keys and resolver metadata."""

from eom_catalog_service.external_item_models import (
    ExternalItemEditionDocumentRecord,
    ExternalItemImportRecord,
    ExternalItemSourceRecord,
    ExternalItemSourceRevisionRecord,
)
from eom_catalog_service.models import ContentIntakeBatchRecord, ContentIntakeSourceFileRecord
from eom_identifiers import content_sha256
from sqlalchemy.orm import Session

from tests.integration.test_content_planning_application import ident
from tests.item_registry.test_registry_persistence import _artifact
from tests.unit.content_planning_fixtures import SHA


def add_source(engine, number="10310", *, namespace=None):
    with Session(engine) as session, session.begin():
        artifact = _artifact(session)
        batch_id, file_id, import_id = ident("intake"), ident("sourcefile"), ident("extimport")
        source_id, revision_id = ident("extitem"), ident("extitemrev")
        namespace = namespace or ident("synthetic")
        session.add(
            ContentIntakeBatchRecord(
                intake_batch_id=batch_id,
                batch_name="Synthetic",
                state="ACCEPTED",
                purpose="content planning database tests",
                received_by="test",
                source_owner_type="HUMAN",
                source_owner_reference="test",
                source_fingerprint=content_sha256({"batch": batch_id}),
            )
        )
        session.flush()
        session.add(
            ContentIntakeSourceFileRecord(
                source_file_id=file_id,
                intake_batch_id=batch_id,
                original_filename=number + ".hwpx",
                normalized_filename=number + ".hwpx",
                relative_path="source/" + number + ".hwpx",
                media_type="application/vnd.hancom.hwpx",
                size_bytes=1,
                sha256=SHA,
                artifact_id=artifact.logical_artifact_id,
                artifact_revision_id=artifact.revision_id,
                declared_role="DATA",
                declared_description="synthetic",
            )
        )
        session.flush()
        session.add(
            ExternalItemImportRecord(
                import_id=import_id,
                source_namespace=namespace,
                request_sha256=content_sha256({"import": import_id}),
                workbook_artifact_id=artifact.logical_artifact_id,
                workbook_source_file_id=file_id,
                workbook_artifact_revision_id=artifact.revision_id,
                workbook_sha256=SHA,
                archive_sha256=SHA,
                mapping_revision_id=ident("extmappingrev"),
                mapping_sha256=SHA,
                mapping_document={},
                state="COMPLETED",
                row_count=1,
                created_by="test",
            )
        )
        session.add(
            ExternalItemSourceRecord(
                source_id=source_id,
                source_namespace=namespace,
                external_number=number,
                created_by="test",
            )
        )
        session.flush()
        session.add(
            ExternalItemSourceRevisionRecord(
                revision_id=revision_id,
                source_id=source_id,
                revision_number=1,
                import_id=import_id,
                external_number=number,
                worksheet_name="synthetic",
                row_number=2,
                observation_sha256=SHA,
                cells=[{} for _ in range(32)],
                match_status="MATCHED",
                selected_source_file_id=file_id,
                created_by="test",
            )
        )
        session.flush()
        session.add(
            ExternalItemEditionDocumentRecord(
                edition_document_id=ident("extitemdoc"),
                source_revision_id=revision_id,
                edition=3,
                match_status="MATCHED",
                source_file_id=file_id,
                document_sha256=SHA,
            )
        )
        session.get(ExternalItemSourceRecord, source_id).current_revision_id = revision_id
    return dict(
        placement_kind="EXTERNAL_SOURCE_DOCUMENT",
        source_id=source_id,
        source_revision_id=revision_id,
        observation_sha256=SHA,
        edition=3,
        source_format="HWPX",
    )
