"""Atomic Catalog admission of externally sourced rows, never Item revisions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import uuid4

from eom_catalog_contracts import (
    EXTERNAL_ITEM_IMPORT_MANIFEST_SCHEMA,
    ExternalItemImportManifest,
    validate_contract,
)
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.external_item_models import (
    USABLE_EXTERNAL_ITEM_INTAKE_STATES,
    ExternalItemEditionDocumentRecord,
    ExternalItemImportRecord,
    ExternalItemSourceRecord,
    ExternalItemSourceRevisionRecord,
)
from eom_catalog_service.external_item_observations import (
    ExternalItemWorkbookPointer,
    bind_external_item_observation,
    external_item_search_facets,
)
from eom_catalog_service.external_item_xlsx import read_external_item_rows_bytes
from eom_catalog_service.intake_service import INTAKE_SOURCE_FILE_SCHEMA_REF
from eom_catalog_service.models import (
    ContentIntakeBatchRecord,
    ContentIntakeSourceFileRecord,
)

_DOCUMENT_NUMBER = re.compile(r"_([0-9]{5})\.(?:hwp|hwpx)$", re.IGNORECASE)
_MATCHED = frozenset({"MATCHED", "MATCHED_DETECTED_HWPX", "MATCHED_IDENTICAL_COPIES"})


class ExternalItemImportError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ExternalItemImportResult:
    import_id: str
    request_sha256: str
    row_count: int
    matched_count: int
    created: bool


class ExternalItemImportService:
    """Register one complete workbook observation under a namespace lock."""

    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine)

    def commit(self, manifest: ExternalItemImportManifest) -> ExternalItemImportResult:
        manifest = ExternalItemImportManifest.model_validate(manifest)
        validate_contract(EXTERNAL_ITEM_IMPORT_MANIFEST_SCHEMA, manifest.model_dump(mode="json"))
        with transaction(self.sessions) as session:
            # Namespace-local serialization plus unique constraints cover concurrent
            # first creation, reimport and exact replay without row-by-row races.
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:namespace))"),
                {"namespace": manifest.source_namespace},
            )
            existing = session.scalar(
                select(ExternalItemImportRecord).where(
                    ExternalItemImportRecord.request_sha256 == manifest.request_sha256
                )
            )
            if existing is not None:
                if existing.state != "COMPLETED" or existing.row_count != len(manifest.rows):
                    raise ExternalItemImportError(
                        "EXTERNAL_ITEM_IMPORT_REPLAY_CONFLICT", "prior import is not complete"
                    )
                return ExternalItemImportResult(
                    import_id=existing.import_id,
                    request_sha256=existing.request_sha256,
                    row_count=existing.row_count,
                    matched_count=sum(row.match_status in _MATCHED for row in manifest.rows),
                    created=False,
                )
            source_files = _resolve_source_files(session, manifest)
            self._verify_workbook_rows(manifest, source_files[manifest.workbook_source_file_id])
            _publish_rows(session, manifest)
            return ExternalItemImportResult(
                import_id=_import_id(manifest.request_sha256),
                request_sha256=manifest.request_sha256,
                row_count=len(manifest.rows),
                matched_count=sum(row.match_status in _MATCHED for row in manifest.rows),
                created=True,
            )

    def _verify_workbook_rows(
        self, manifest: ExternalItemImportManifest, source: ContentIntakeSourceFileRecord
    ) -> None:
        try:
            payload = self.artifacts.read_member(
                artifact_id=source.artifact_id,
                revision_id=source.artifact_revision_id,
                member_path=source.relative_path,
                sha256=source.sha256,
                media_type=source.media_type,
                schema_ref=INTAKE_SOURCE_FILE_SCHEMA_REF,
                max_bytes=100 * 1024 * 1024,
            )
            actual = read_external_item_rows_bytes(payload, manifest.mapping)
        except ValueError as exc:
            raise ExternalItemImportError(
                "EXTERNAL_ITEM_WORKBOOK_UNAVAILABLE", "pinned workbook could not be verified"
            ) from exc
        if len(actual) != len(manifest.rows):
            raise ExternalItemImportError(
                "EXTERNAL_ITEM_WORKBOOK_ROW_MISMATCH", "workbook row count differs"
            )
        pointer = ExternalItemWorkbookPointer(
            artifact_id=manifest.workbook_artifact_id,
            artifact_revision_id=manifest.workbook_artifact_revision_id,
            sha256=manifest.workbook_sha256,
        )
        for decoded, supplied in zip(actual, manifest.rows, strict=True):
            observed = bind_external_item_observation(
                decoded, mapping=manifest.mapping, workbook=pointer
            )
            if observed != supplied.observation:
                raise ExternalItemImportError(
                    "EXTERNAL_ITEM_WORKBOOK_ROW_MISMATCH", "workbook row content differs"
                )


def _import_id(request_sha256: str) -> str:
    # Deterministic import identity makes exact replay obvious in audit traces.
    return "extimport_" + request_sha256.removeprefix("sha256:")[:32]


def _resolve_source_files(
    session: Session, manifest: ExternalItemImportManifest
) -> dict[str, ContentIntakeSourceFileRecord]:
    required_ids = (
        {manifest.workbook_source_file_id}
        | {
            row.selected_source_file_id
            for row in manifest.rows
            if row.selected_source_file_id is not None
        }
        | {
            link.selected_source_file_id
            for row in manifest.rows
            for link in row.edition_links
            if link.selected_source_file_id is not None
        }
    )
    sources = {
        source.source_file_id: source
        for source in session.scalars(
            select(ContentIntakeSourceFileRecord).where(
                ContentIntakeSourceFileRecord.source_file_id.in_(required_ids)
            )
        )
    }
    if set(sources) != required_ids:
        raise ExternalItemImportError("EXTERNAL_ITEM_SOURCE_MISSING", "source file is missing")
    batch_ids = {source.intake_batch_id for source in sources.values()}
    batches = {
        batch.intake_batch_id: batch
        for batch in session.scalars(
            select(ContentIntakeBatchRecord).where(
                ContentIntakeBatchRecord.intake_batch_id.in_(batch_ids)
            )
        )
    }
    revision_ids = {source.artifact_revision_id for source in sources.values()}
    revisions = {
        revision.revision_id: revision
        for revision in session.scalars(
            select(ArtifactRevisionRecord).where(
                ArtifactRevisionRecord.revision_id.in_(revision_ids)
            )
        )
    }
    artifacts = {
        artifact.logical_artifact_id: artifact
        for artifact in session.scalars(
            select(ArtifactRecord).where(
                ArtifactRecord.logical_artifact_id.in_(
                    {source.artifact_id for source in sources.values()}
                )
            )
        )
    }
    jobs = {
        job.job_id: job
        for job in session.scalars(
            select(JobRecord).where(
                JobRecord.job_id.in_({value.job_id for value in revisions.values()})
            )
        )
    }
    for source in sources.values():
        batch = batches.get(source.intake_batch_id)
        revision = revisions.get(source.artifact_revision_id)
        artifact = artifacts.get(source.artifact_id)
        job = jobs.get(revision.job_id) if revision is not None else None
        if (
            batch is None
            or batch.state not in USABLE_EXTERNAL_ITEM_INTAKE_STATES
            or artifact is None
            or not artifact.approved
            or artifact.artifact_type != "content-intake-source"
            or revision is None
            or not revision.approved
            or job is None
            or job.status != "SUCCEEDED"
            or artifact.job_id != revision.job_id
            or job.logical_artifact_id != source.artifact_id
            or job.revision_id != source.artifact_revision_id
            or revision.logical_artifact_id != source.artifact_id
            or batch.source_manifest_artifact_id != source.artifact_id
            or batch.source_manifest_artifact_revision_id != source.artifact_revision_id
            or batch.source_manifest_sha256 != revision.content_hash
            or content_sha256(revision.manifest) != revision.manifest_hash
            or revision.manifest.get("manifest_version") != "catalog-file-set/1.0"
            or revision.manifest.get("artifact_type") != "content-intake-source"
        ):
            raise ExternalItemImportError(
                "EXTERNAL_ITEM_SOURCE_POINTER_INVALID", "source Artifact pointer differs"
            )
        members = revision.manifest.get("files")
        if (
            not isinstance(members, list)
            or sum(
                isinstance(member, dict)
                and member.get("file_name") == source.relative_path
                and member.get("sha256") == source.sha256
                and member.get("bytes") == source.size_bytes
                and member.get("media_type") == source.media_type
                for member in members
            )
            != 1
        ):
            raise ExternalItemImportError(
                "EXTERNAL_ITEM_SOURCE_MEMBER_INVALID", "source Artifact member differs"
            )
    workbook = sources[manifest.workbook_source_file_id]
    if (
        workbook.artifact_id != manifest.workbook_artifact_id
        or workbook.artifact_revision_id != manifest.workbook_artifact_revision_id
        or workbook.sha256 != manifest.workbook_sha256
        or not workbook.original_filename.lower().endswith(".xlsx")
    ):
        raise ExternalItemImportError(
            "EXTERNAL_ITEM_WORKBOOK_POINTER_INVALID", "workbook pointer differs"
        )
    for row in manifest.rows:
        bindings = (
            (row.selected_source_file_id, row.selected_document_sha256),
            *(
                (link.selected_source_file_id, link.selected_document_sha256)
                for link in row.edition_links
            ),
        )
        for source_file_id, expected_sha256 in bindings:
            if source_file_id is None:
                continue
            source = sources[source_file_id]
            match = _DOCUMENT_NUMBER.search(source.original_filename)
            if (
                match is None
                or match.group(1) != row.observation.external_number
                or source.sha256 != expected_sha256
            ):
                raise ExternalItemImportError(
                    "EXTERNAL_ITEM_DOCUMENT_POINTER_INVALID", "selected document differs"
                )
    return sources


def _publish_rows(
    session: Session,
    manifest: ExternalItemImportManifest,
) -> None:
    import_id = _import_id(manifest.request_sha256)
    session.add(
        ExternalItemImportRecord(
            import_id=import_id,
            source_namespace=manifest.source_namespace,
            request_sha256=manifest.request_sha256,
            workbook_source_file_id=manifest.workbook_source_file_id,
            workbook_artifact_id=manifest.workbook_artifact_id,
            workbook_artifact_revision_id=manifest.workbook_artifact_revision_id,
            workbook_sha256=manifest.workbook_sha256,
            archive_sha256=manifest.archive_sha256,
            mapping_revision_id=manifest.mapping.mapping_revision_id,
            mapping_sha256=manifest.mapping.mapping_sha256,
            mapping_document=manifest.mapping.model_dump(mode="json"),
            state="COMPLETED",
            row_count=len(manifest.rows),
            created_by=manifest.actor_id,
        )
    )
    numbers = [row.observation.external_number for row in manifest.rows]
    existing_sources = {
        source.external_number: source
        for source in session.scalars(
            select(ExternalItemSourceRecord)
            .where(
                ExternalItemSourceRecord.source_namespace == manifest.source_namespace,
                ExternalItemSourceRecord.external_number.in_(numbers),
            )
            .order_by(ExternalItemSourceRecord.external_number)
            .with_for_update()
        )
    }
    previous_ids = {
        source.current_revision_id
        for source in existing_sources.values()
        if source.current_revision_id is not None
    }
    prior_revisions = {
        revision.revision_id: revision
        for revision in session.scalars(
            select(ExternalItemSourceRevisionRecord).where(
                ExternalItemSourceRevisionRecord.revision_id.in_(previous_ids)
            )
        )
    }
    new_revisions: list[ExternalItemSourceRevisionRecord] = []
    edition_documents: list[ExternalItemEditionDocumentRecord] = []
    publication_pointers: list[tuple[ExternalItemSourceRecord, str]] = []
    for row in manifest.rows:
        number = row.observation.external_number
        if number not in existing_sources:
            existing_sources[number] = ExternalItemSourceRecord(
                source_id="extitem_" + uuid4().hex,
                source_namespace=manifest.source_namespace,
                external_number=number,
                current_revision_id=None,
                created_by=manifest.actor_id,
            )
            session.add(existing_sources[number])
    session.flush()
    for row in manifest.rows:
        observation = row.observation
        source = existing_sources[observation.external_number]
        previous_id = source.current_revision_id
        previous = prior_revisions.get(previous_id) if previous_id else None
        if previous_id is not None and previous is None:
            raise ExternalItemImportError(
                "EXTERNAL_ITEM_PREDECESSOR_MISSING", "current source revision is missing"
            )
        facets = external_item_search_facets(observation)
        revision = ExternalItemSourceRevisionRecord(
            revision_id="extitemrev_" + uuid4().hex,
            source_id=source.source_id,
            revision_number=(previous.revision_number + 1 if previous else 1),
            previous_revision_id=previous_id,
            import_id=import_id,
            external_number=observation.external_number,
            worksheet_name=observation.worksheet_name,
            row_number=observation.row_number,
            observation_sha256=observation.observation_sha256,
            cells=[cell.model_dump(mode="json") for cell in observation.cells],
            match_status=row.match_status,
            selected_source_file_id=row.selected_source_file_id,
            unit_major=facets.major_unit,
            unit_minor=facets.minor_unit,
            field_label=facets.field,
            grade_label=facets.grade,
            author_label=facets.author,
            created_by=manifest.actor_id,
        )
        new_revisions.append(revision)
        edition_documents.extend(
            ExternalItemEditionDocumentRecord(
                edition_document_id="extitemdoc_" + uuid4().hex,
                source_revision_id=revision.revision_id,
                edition=link.edition,
                match_status=link.match_status,
                source_file_id=link.selected_source_file_id,
                document_sha256=link.selected_document_sha256,
            )
            for link in row.edition_links
        )
        publication_pointers.append((source, revision.revision_id))
    session.add_all([*new_revisions, *edition_documents])
    session.flush()
    for source, revision_id in publication_pointers:
        source.current_revision_id = revision_id
