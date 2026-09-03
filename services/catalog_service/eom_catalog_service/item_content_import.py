"""Reviewed canonical item-content import application use case."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eom_catalog_contracts import (
    ASSESSMENT_ITEM_CONTENT_FILE_NAME,
    ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
    ASSESSMENT_ITEM_CONTENT_SCHEMA_REF,
    ASSESSMENT_ITEM_CONTENT_V2_SCHEMA_REF,
    AssessmentItemContentContract,
    AssessmentItemContentV2,
    validate_contract,
)
from eom_hwpx_contracts import ContentTeamEditorialDraft, serialize_content_team_markdown
from eom_identifiers import content_sha256
from eom_item_registry import (
    ComponentPointer,
    ItemRevisionState,
    RegistrationRequest,
    RegistryError,
    RegistryErrorCode,
)
from eom_orchestrator.database import build_session_factory
from eom_workflow_runner.models import WorkflowInstanceRecord
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import (
    CATALOG_ITEM_CONTENT_V2_PROTOCOL_VERSION,
    CATALOG_ITEM_CONTENT_V2_SCHEMA_HASH,
    CatalogArtifactService,
)
from eom_catalog_service.models import (
    ItemComponentRecord,
    ItemMetadataSnapshotRecord,
    ItemProvenanceRecord,
    ItemRecord,
    ItemRevisionRecord,
)
from eom_catalog_service.registry_service import RegistryService
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.staging import (
    stage_content_team_item_materialization,
    stage_registry_item_content,
)


@dataclass(frozen=True)
class StructuredItemContentImport:
    item_id: str
    item_revision_id: str
    resource_version: int
    content_artifact_id: str
    content_artifact_revision_id: str
    content_sha256: str


class StructuredItemContentImportService:
    """Commit reviewed content and atomically revise its pinned logical Item."""

    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine, self.settings)
        self.registry = RegistryService(engine, self.settings)

    def import_reviewed(
        self,
        base_revision_id: str,
        content: AssessmentItemContentContract,
        *,
        reviewed_by: str,
        review_reason: str,
        expected_version: int,
    ) -> StructuredItemContentImport:
        content_data = content.model_dump(mode="json")
        is_content_team = isinstance(content, AssessmentItemContentV2)
        schema_name = "assessment-item-content-v2" if is_content_team else "assessment-item-content"
        schema_ref = (
            ASSESSMENT_ITEM_CONTENT_V2_SCHEMA_REF
            if is_content_team
            else ASSESSMENT_ITEM_CONTENT_SCHEMA_REF
        )
        validate_contract(schema_name, content_data)
        content_hash = content_sha256(content_data)
        review_hash = content_sha256(
            {"reviewed_by": reviewed_by, "review_reason": review_reason}
        ).removeprefix("sha256:")
        registration_key = (
            f"reviewed-item-content:{base_revision_id}:"
            f"{content_hash.removeprefix('sha256:')}:{review_hash}"
        )
        with self.sessions() as session:
            existing = session.scalar(
                select(ItemRevisionRecord).where(
                    ItemRevisionRecord.registration_key == registration_key
                )
            )
            if existing is not None:
                return self._existing_result(session, existing)
            base = session.get(ItemRevisionRecord, base_revision_id)
            if base is None:
                raise RegistryError(
                    RegistryErrorCode.ITEM_REVISION_NOT_FOUND,
                    "base item revision not found",
                )
            item = session.get(ItemRecord, base.item_id)
            if (
                base.lock_version != expected_version
                or item is None
                or item.current_revision_id != base.item_revision_id
            ):
                raise RegistryError(
                    RegistryErrorCode.CATALOG_CONCURRENCY_CONFLICT,
                    "base item revision is stale",
                )
            if base.revision_state != ItemRevisionState.APPROVED.value:
                raise RegistryError(
                    RegistryErrorCode.ITEM_REVISION_NOT_APPROVED,
                    "base item revision is not approved",
                )
            workflow = session.get(WorkflowInstanceRecord, base.workflow_id)
            metadata = session.scalar(
                select(ItemMetadataSnapshotRecord).where(
                    ItemMetadataSnapshotRecord.item_revision_id == base.item_revision_id
                )
            )
            components = tuple(
                session.scalars(
                    select(ItemComponentRecord)
                    .where(ItemComponentRecord.item_revision_id == base.item_revision_id)
                    .order_by(ItemComponentRecord.component_type, ItemComponentRecord.ordinal)
                )
            )
            provenance = tuple(
                session.scalars(
                    select(ItemProvenanceRecord).where(
                        ItemProvenanceRecord.item_revision_id == base.item_revision_id
                    )
                )
            )
            if workflow is None or metadata is None:
                raise RegistryError(
                    RegistryErrorCode.ITEM_REGISTRATION_FAILED,
                    "base item revision provenance is incomplete",
                )
            preserved = tuple(
                ComponentPointer.model_validate(
                    {
                        "component_type": component.component_type,
                        "ordinal": component.ordinal,
                        "schema_ref": component.schema_ref,
                        "media_type": component.media_type,
                        "artifact_id": component.artifact_id,
                        "artifact_revision_id": component.artifact_revision_id,
                        "sha256": component.sha256,
                        "logical_name": component.logical_name,
                        "required": component.required,
                        "metadata": component.metadata_json,
                    }
                )
                for component in components
                if component.component_type != "ITEM_CONTENT"
            )
            intake_ids = tuple(
                sorted(
                    {
                        row.source_intake_batch_id
                        for row in provenance
                        if row.source_intake_batch_id is not None
                    }
                )
            )
            registration_values: dict[str, Any] = {
                "item_id": base.item_id,
                "content_pack_release_id": base.content_pack_release_id,
                "workflow_id": base.workflow_id,
                "workflow_definition_key": workflow.definition_key,
                "workflow_definition_version": base.workflow_definition_version,
                "source_workflow_step_run_id": base.source_workflow_step_run_id,
                "source_intake_batch_ids": intake_ids,
                "item_type_key": base.item_type_key,
                "primary_taxonomy_ref": base.primary_taxonomy_ref,
                "difficulty_band": base.difficulty_band,
                "tag_keys": tuple(metadata.tag_keys),
                "estimated_time_seconds": metadata.estimated_time_seconds,
                "metadata_schema_ref": metadata.schema_ref,
                "metadata": base.metadata_json,
            }

        markdown_hash: str | None = None
        if is_content_team:
            editorial_data = dict(content_data)
            editorial_data.pop("schema_version")
            editorial = ContentTeamEditorialDraft.model_validate(editorial_data)
            markdown = serialize_content_team_markdown(editorial)
            staged, staged_hash, staged_markdown, markdown_hash = (
                stage_content_team_item_materialization(self.settings, content_data, markdown)
            )
            files = {
                ASSESSMENT_ITEM_CONTENT_FILE_NAME: staged,
                "content-team-item.md": staged_markdown,
            }
            file_metadata = {
                ASSESSMENT_ITEM_CONTENT_FILE_NAME: {
                    "schema_ref": schema_ref,
                    "media_type": ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
                },
                "content-team-item.md": {
                    "schema_ref": "eom://schemas/hwpx/content-team-editorial-markdown/1.0",
                    "media_type": "text/markdown",
                },
            }
            expected_file_sha256 = {
                ASSESSMENT_ITEM_CONTENT_FILE_NAME: content_hash,
                "content-team-item.md": markdown_hash,
            }
        else:
            staged, staged_hash = stage_registry_item_content(self.settings, content_data)
            files = {ASSESSMENT_ITEM_CONTENT_FILE_NAME: staged}
            file_metadata = {
                ASSESSMENT_ITEM_CONTENT_FILE_NAME: {
                    "schema_ref": schema_ref,
                    "media_type": ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
                }
            }
            expected_file_sha256 = None
        if staged_hash != content_hash:
            raise RegistryError(
                RegistryErrorCode.ITEM_COMPONENT_INVALID,
                "canonical content hash changed during staging",
            )
        artifact = self.artifacts.commit_file_set(
            files=files,
            primary_file=ASSESSMENT_ITEM_CONTENT_FILE_NAME,
            artifact_type="assessment-item-content",
            idempotency_key=f"reviewed-item-content-artifact:{content_hash}",
            request={
                "schema_ref": schema_ref,
                "content_sha256": content_hash,
            },
            result={
                "schema_ref": schema_ref,
                "content_sha256": content_hash,
                **(
                    {"editorial_markdown_sha256": markdown_hash}
                    if markdown_hash is not None
                    else {}
                ),
            },
            file_metadata=file_metadata,
            expected_file_sha256=expected_file_sha256,
            **(
                {
                    "protocol_version": CATALOG_ITEM_CONTENT_V2_PROTOCOL_VERSION,
                    "protocol_schema_hash": CATALOG_ITEM_CONTENT_V2_SCHEMA_HASH,
                }
                if is_content_team
                else {}
            ),
        )
        content_pointer = ComponentPointer(
            component_type="ITEM_CONTENT",
            ordinal=0,
            schema_ref=schema_ref,
            media_type=ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            sha256=artifact.content_hash,
            logical_name=ASSESSMENT_ITEM_CONTENT_FILE_NAME,
            required=True,
            metadata={
                "import_protocol": (
                    "reviewed-content-team-item/2.0"
                    if is_content_team
                    else "reviewed-structured-item-content/1.0"
                ),
                "reviewed_by": reviewed_by,
                "review_reason": review_reason,
                "base_revision_id": base_revision_id,
                **(
                    {
                        "editorial_markdown_member": "content-team-item.md",
                        "editorial_markdown_sha256": markdown_hash,
                    }
                    if markdown_hash is not None
                    else {}
                ),
            },
        )
        request = RegistrationRequest(
            mode="REVISE_ITEM",
            registration_key=registration_key,
            base_revision_id=base_revision_id,
            components=(*preserved, content_pointer),
            created_by=reviewed_by,
            **registration_values,
        )
        revision = self.registry.register(request)
        return StructuredItemContentImport(
            item_id=revision.item_id,
            item_revision_id=revision.item_revision_id,
            resource_version=revision.lock_version,
            content_artifact_id=artifact.artifact_id,
            content_artifact_revision_id=artifact.revision_id,
            content_sha256=artifact.content_hash,
        )

    @staticmethod
    def _existing_result(
        session: Session,
        revision: ItemRevisionRecord,
    ) -> StructuredItemContentImport:
        component = session.scalar(
            select(ItemComponentRecord).where(
                ItemComponentRecord.item_revision_id == revision.item_revision_id,
                ItemComponentRecord.component_type == "ITEM_CONTENT",
                ItemComponentRecord.ordinal == 0,
            )
        )
        if component is None:
            raise RegistryError(
                RegistryErrorCode.ITEM_COMPONENT_INVALID,
                "existing reviewed import has no canonical content component",
            )
        return StructuredItemContentImport(
            item_id=revision.item_id,
            item_revision_id=revision.item_revision_id,
            resource_version=revision.lock_version,
            content_artifact_id=component.artifact_id,
            content_artifact_revision_id=component.artifact_revision_id,
            content_sha256=component.sha256,
        )
