"""Prepare/review one missing Native image through the existing revision owner.

PREPARE only reads canonical sources (the protected parser may use its temporary
workspace). IMPORT creates one reviewed Item successor. It does not change old
Material tasks, reports, analyses, Graphs, images, source files or model work.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from eom_catalog_contracts.assessment_item import (
    AssessmentItemContent,
    ImageBlock,
    MediaArtifactPointer,
)
from eom_catalog_contracts.creative_source_visuals import CREATIVE_SOURCE_VISUAL_IMAGE_REF
from eom_catalog_contracts.material_item_lineage import (
    MATERIAL_ITEM_LINEAGE_REF,
    MaterialItemLineage,
)
from eom_catalog_contracts.material_learning import MaterialArtifactMember, MaterialExtractionWork
from eom_catalog_contracts.material_native_files import (
    MATERIAL_NATIVE_BINDING_REF,
    MaterialImportedNativeItemMetadata,
    MaterialNativeItemBinding,
    require_material_native_binding_for_work,
)
from eom_catalog_contracts.material_native_item_read import MaterialNativeItemReadRequest
from eom_catalog_contracts.material_native_visual_correction import (
    MaterialNativeVisualCorrectionCommand,
    MaterialNativeVisualCorrectionPrepared,
    MaterialNativeVisualCorrectionResult,
    native_visual_correction_block_id,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_identity_service.repository import effective_permissions
from eom_image_contracts.office_picture_uses import (
    OFFICE_PICTURE_USE_CATALOG_REF,
    OfficePictureUseCatalog,
)
from eom_item_registry import ComponentPointer
from eom_operator_identity import PermissionKey
from eom_orchestrator.database import build_session_factory
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.item_content_import import StructuredItemContentImportService
from eom_catalog_service.material_learning_artifacts import (
    pin_material_primary,
    read_material_metadata,
)
from eom_catalog_service.material_learning_authorization import (
    CatalogMaterialLearningSourceAuthorizer,
)
from eom_catalog_service.material_learning_models import MaterialLearningRunRecord
from eom_catalog_service.material_native_item_read import (
    MaterialNativeItemReadService,
    authorize_native_material_read,
)
from eom_catalog_service.material_native_visual_preparation import (
    MaterialNativeVisualPreparationService,
)
from eom_catalog_service.models import ItemComponentRecord, ItemRecord, ItemRevisionRecord
from eom_catalog_service.registry_service import RegistryService
from eom_catalog_service.settings import CatalogSettings

_COMPONENTS = frozenset(
    {
        ("ITEM_CONTENT", 0),
        ("SOURCE_REFERENCE", 0),
        ("REVIEW_REPORT", 0),
        ("METADATA", 0),
        ("OTHER", 0),
        ("OTHER", 1),
    }
)
_TERMINAL_RUNS = ("COMPLETED", "COMPLETED_WITH_EXCEPTIONS", "FAILED", "CANCELLED")


def insert_native_visual_image(
    content: AssessmentItemContent, *, image: ImageBlock, insert_after_block_id: str
) -> AssessmentItemContent:
    """Only insert one block; every existing value and body order stays exact."""
    content = AssessmentItemContent.model_validate(content.model_dump(mode="json"))
    image = ImageBlock.model_validate(image.model_dump(mode="json"))
    positions = {block.block_id: index for index, block in enumerate(content.body)}
    if insert_after_block_id not in positions:
        raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_INSERTION_INVALID")
    if image.block_id in positions or any(
        isinstance(block, ImageBlock) and block.artifact == image.artifact for block in content.body
    ):
        raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_ALREADY_REPRESENTED")
    value = content.model_dump(mode="json")
    value["body"].insert(positions[insert_after_block_id] + 1, image.model_dump(mode="json"))
    return AssessmentItemContent.model_validate(value)


def _component_value(component: ItemComponentRecord) -> ComponentPointer:
    return ComponentPointer.model_validate(
        dict(
            component_type=component.component_type,
            ordinal=component.ordinal,
            schema_ref=component.schema_ref,
            media_type=component.media_type,
            artifact_id=component.artifact_id,
            artifact_revision_id=component.artifact_revision_id,
            sha256=component.sha256,
            logical_name=component.logical_name,
            required=component.required,
            metadata=component.metadata_json,
        )
    )


def _component_pointer(component: ComponentPointer) -> ArtifactMemberPointer:
    return ArtifactMemberPointer(
        artifact_id=component.artifact_id,
        artifact_revision_id=component.artifact_revision_id,
        member_path=component.logical_name,
        schema_ref=component.schema_ref,
        media_type=component.media_type,
        sha256=component.sha256,
    )


def _preserved_sha256(components: tuple[ComponentPointer, ...]) -> str:
    return content_sha256(
        [
            value.model_dump(mode="json")
            for value in components
            if value.component_type != "ITEM_CONTENT"
        ]
    )


@dataclass(frozen=True, slots=True)
class _ResolvedCorrection:
    prepared: MaterialNativeVisualCorrectionPrepared
    content: AssessmentItemContent
    metadata: MaterialImportedNativeItemMetadata


class MaterialNativeVisualCorrectionService:
    """No generic editor or new registry: Native source proofs + reviewed import."""

    def __init__(
        self,
        engine: Engine,
        *,
        native_visuals: MaterialNativeVisualPreparationService,
        settings: CatalogSettings | None = None,
    ) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine, self.settings)
        self.native_sources = MaterialNativeItemReadService(engine, self.settings)
        self.sources = CatalogMaterialLearningSourceAuthorizer(engine, self.settings)
        self.registry = RegistryService(engine, self.settings)
        self.imports = StructuredItemContentImportService(engine, self.settings)
        self.native_visuals = native_visuals

    @staticmethod
    def _authorize(session: Session, actor_id: str) -> None:
        authorize_native_material_read(session, actor_id)
        if PermissionKey.ITEM_STRUCTURED_CONTENT_IMPORT not in effective_permissions(
            session, actor_id
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_PERMISSION_DENIED")

    @staticmethod
    def _require_terminal(session: Session, material_revision_id: str) -> None:
        if (
            session.scalar(
                select(MaterialLearningRunRecord.run_id)
                .where(
                    MaterialLearningRunRecord.material_revision_id == material_revision_id,
                    MaterialLearningRunRecord.state.not_in(_TERMINAL_RUNS),
                )
                .limit(1)
            )
            is not None
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_MATERIAL_ACTIVE")

    @staticmethod
    def _components(session: Session, revision_id: str) -> tuple[ComponentPointer, ...]:
        rows = tuple(
            session.scalars(
                select(ItemComponentRecord)
                .where(ItemComponentRecord.item_revision_id == revision_id)
                .order_by(ItemComponentRecord.component_type, ItemComponentRecord.ordinal)
            )
        )
        if len(rows) != 6 or {(row.component_type, row.ordinal) for row in rows} != _COMPONENTS:
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_COMPONENTS_INVALID")
        return tuple(_component_value(row) for row in rows)

    def prepare(
        self, command: MaterialNativeVisualCorrectionCommand
    ) -> MaterialNativeVisualCorrectionPrepared:
        return self._resolve(command, require_current=True).prepared

    def _resolve(
        self, command: MaterialNativeVisualCorrectionCommand, *, require_current: bool
    ) -> _ResolvedCorrection:
        command = MaterialNativeVisualCorrectionCommand.model_validate(
            command.model_dump(mode="json")
        )
        with self.sessions() as session:
            self._authorize(session, command.actor_id)
            revision = session.get(
                ItemRevisionRecord, command.base_item_revision_id, populate_existing=True
            )
            item = (
                session.get(ItemRecord, revision.item_id, populate_existing=True)
                if revision
                else None
            )
            if (
                revision is None
                or item is None
                or item.lifecycle_state != "ACTIVE"
                or revision.manifest_sha256 != command.base_item_manifest_sha256
                or revision.revision_state not in {"APPROVED", "SUPERSEDED"}
                or (
                    revision.revision_state == "APPROVED"
                    and revision.lock_version != command.expected_version
                )
                or (
                    require_current
                    and (
                        item.current_revision_id != revision.item_revision_id
                        or revision.revision_state != "APPROVED"
                        or revision.lock_version != command.expected_version
                    )
                )
            ):
                raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_BASE_STALE")
            metadata = MaterialImportedNativeItemMetadata.model_validate(revision.metadata_json)
            self._require_terminal(session, metadata.material_revision_id)
            components = self._components(session, revision.item_revision_id)
            indexed = {(value.component_type, value.ordinal): value for value in components}
            base_pointer = _component_pointer(indexed["ITEM_CONTENT", 0])
            lineage_pointer = pin_material_primary(
                session, _component_pointer(indexed["SOURCE_REFERENCE", 0])
            ).pointer
            item_id = revision.item_id
        lineage = read_material_metadata(
            self.artifacts,
            lineage_pointer,
            MaterialItemLineage,
            schema_ref=MATERIAL_ITEM_LINEAGE_REF,
            member_path="lineage.json",
            maximum_bytes=64 * 1024,
        )
        work = read_material_metadata(
            self.artifacts,
            lineage.work_input,
            MaterialExtractionWork,
            schema_ref="eom://schemas/material-learning/extraction-work/1.0",
            member_path="material/work.json",
        )
        if (
            (
                lineage.material_id,
                lineage.material_revision_id,
                lineage.unit_key,
                lineage.task_id,
                lineage.requested_by,
            )
            != (
                metadata.material_id,
                metadata.material_revision_id,
                metadata.unit_key,
                work.task_id,
                command.actor_id,
            )
            or (work.material_id, work.material_revision_id, work.unit_key)
            != (metadata.material_id, metadata.material_revision_id, metadata.unit_key)
            or lineage.lineage_sha256 != metadata.lineage_sha256
            or lineage.input_sha256 != work.input_sha256
            or lineage.registered_content_sha256 != base_pointer.sha256
            or _component_pointer(indexed["REVIEW_REPORT", 0]) != lineage.role_result
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_SOURCE_MISMATCH")

        def authorize() -> None:
            with self.sessions() as session:
                self._authorize(session, command.actor_id)
                self._require_terminal(session, metadata.material_revision_id)
                self.sources.reauthorize(session, operator_id=command.actor_id, work=work)

        authorize()
        source = self.native_sources.read_source(
            MaterialNativeItemReadRequest(
                operation="GET_NATIVE_MATERIAL_ITEM_SOURCE",
                actor_id=command.actor_id,
                item_revision_id=command.base_item_revision_id,
                item_manifest_sha256=command.base_item_manifest_sha256,
            )
        )
        binding = read_material_metadata(
            self.artifacts,
            metadata.native_binding,
            MaterialNativeItemBinding,
            schema_ref=MATERIAL_NATIVE_BINDING_REF,
            member_path="native/binding.json",
            maximum_bytes=4 * 1024 * 1024,
        )
        require_material_native_binding_for_work(binding, work)
        selected = work.sources[0]
        if (
            source.metadata != metadata
            or source.question != binding.question.document
            or source.solution != binding.solution.document
            or source.workbook != binding.workbook
            or selected.source_role != "MAIN"
            or selected.actual_format == "PDF"
            or selected.office_catalog is None
            or selected.original.sha256 != binding.question.original_source_sha256
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_SOURCE_MISMATCH")
        catalog_pointer = selected.office_catalog
        catalog = read_material_metadata(
            self.artifacts,
            catalog_pointer,
            OfficePictureUseCatalog,
            schema_ref=OFFICE_PICTURE_USE_CATALOG_REF,
            member_path="picture-use-catalog.json",
            maximum_bytes=8 * 1024 * 1024,
        )
        scope = self.native_visuals.question_scope(
            binding.question,
            item_number=metadata.item_number,
            catalog=catalog,
            catalog_pointer=catalog_pointer,
            authorize=authorize,
        )
        if (
            scope.item_number != metadata.item_number
            or scope.question_document != binding.question.document
            or scope.split_evidence != binding.question.split_evidence
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_SOURCE_MISMATCH")
        if command.picture_use_id not in scope.allowed_picture_use_ids:
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_USE_OUT_OF_SCOPE")
        view = next(
            (value for value in catalog.rendered_uses if value.use_id == command.picture_use_id),
            None,
        )
        if view is None:
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_USE_UNRESOLVED")
        image_pointer = MaterialArtifactMember(
            artifact_id=catalog_pointer.artifact_id,
            artifact_revision_id=catalog_pointer.artifact_revision_id,
            member_path=view.member_path,
            sha256=view.sha256,
            bytes=view.content_length,
            schema_ref=CREATIVE_SOURCE_VISUAL_IMAGE_REF,
            media_type="image/png",
        )
        raw = self.artifacts.read_member(
            artifact_id=image_pointer.artifact_id,
            revision_id=image_pointer.artifact_revision_id,
            member_path=image_pointer.member_path,
            sha256=image_pointer.sha256,
            schema_ref=image_pointer.schema_ref,
            media_type=image_pointer.media_type,
            max_bytes=image_pointer.bytes,
        )
        if (
            len(raw) != image_pointer.bytes
            or len(raw) < 24
            or raw[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            or struct.unpack(">II", raw[16:24]) != (view.width_px, view.height_px)
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_PNG_INVALID")
        image = ImageBlock(
            block_id=native_visual_correction_block_id(command.picture_use_id),
            purpose="stimulus",
            artifact=MediaArtifactPointer(
                artifact_id=image_pointer.artifact_id,
                artifact_revision_id=image_pointer.artifact_revision_id,
                artifact_member=image_pointer.member_path,
                sha256=image_pointer.sha256,
                media_type="image/png",
            ),
            alt_text="원문 본문 그림",
            width_px=view.width_px,
            height_px=view.height_px,
        )
        canonical = self.registry.load_item_content(command.base_item_revision_id)
        if (
            not isinstance(canonical, AssessmentItemContent)
            or content_sha256(canonical.model_dump(mode="json")) != base_pointer.sha256
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_CONTENT_INVALID")
        corrected = insert_native_visual_image(
            canonical, image=image, insert_after_block_id=command.insert_after_block_id
        )
        encoded = canonical_json_bytes(corrected.model_dump(mode="json"))
        body = dict(
            schema_version="material-native-visual-correction-prepared/1.0",
            command=command.model_dump(mode="json"),
            item_id=item_id,
            material_id=metadata.material_id,
            material_revision_id=metadata.material_revision_id,
            source_task_id=lineage.task_id,
            source_lineage=lineage_pointer.model_dump(mode="json"),
            native_binding=metadata.native_binding.model_dump(mode="json"),
            catalog=catalog_pointer.model_dump(mode="json"),
            scope=scope.model_dump(mode="json"),
            base_content=base_pointer.model_dump(mode="json"),
            image=image.model_dump(mode="json"),
            corrected_content_sha256=content_sha256(corrected.model_dump(mode="json")),
            corrected_content_bytes=len(encoded),
            preserved_components_sha256=_preserved_sha256(components),
        )
        prepared = MaterialNativeVisualCorrectionPrepared.model_validate(
            {**body, "prepared_sha256": content_sha256(body)}
        )
        authorize()
        return _ResolvedCorrection(prepared, corrected, metadata)

    def import_reviewed(
        self,
        command: MaterialNativeVisualCorrectionCommand,
        *,
        prepared: MaterialNativeVisualCorrectionPrepared,
    ) -> MaterialNativeVisualCorrectionResult:
        """Explicit operator review; old immutable base is read only for exact replay.

        The existing import owner checks its deterministic replay key before its
        current-base CAS. Historical resolution here cannot authorize a new write
        against a superseded base.
        """
        prepared = MaterialNativeVisualCorrectionPrepared.model_validate(
            prepared.model_dump(mode="json")
        )
        resolved = self._resolve(command, require_current=False)
        if resolved.prepared != prepared:
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_PREPARATION_CHANGED")
        imported = self.imports.import_reviewed(
            command.base_item_revision_id,
            resolved.content,
            reviewed_by=command.actor_id,
            review_reason="Reviewed Native image-only insertion: " + prepared.prepared_sha256,
            expected_version=command.expected_version,
        )
        with self.sessions() as session:
            self._authorize(session, command.actor_id)
            row = session.get(ItemRevisionRecord, imported.item_revision_id, populate_existing=True)
            components = self._components(session, imported.item_revision_id)
            component = next(
                value for value in components if value.component_type == "ITEM_CONTENT"
            )
            if (
                row is None
                or row.item_id != prepared.item_id
                or row.metadata_json != resolved.metadata.model_dump(mode="json")
                or _preserved_sha256(components) != prepared.preserved_components_sha256
                or component.sha256 != prepared.corrected_content_sha256
                or imported.content_sha256 != prepared.corrected_content_sha256
            ):
                raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_IMPORT_MISMATCH")
            manifest_sha256 = row.manifest_sha256
        self.native_sources.read_source(
            MaterialNativeItemReadRequest(
                operation="GET_NATIVE_MATERIAL_ITEM_SOURCE",
                actor_id=command.actor_id,
                item_revision_id=imported.item_revision_id,
                item_manifest_sha256=manifest_sha256,
            )
        )
        body = dict(
            schema_version="material-native-visual-correction-result/1.0",
            state="IMPORTED",
            prepared=prepared.model_dump(mode="json"),
            item_revision_id=imported.item_revision_id,
            item_manifest_sha256=manifest_sha256,
            resource_version=imported.resource_version,
            content=_component_pointer(component).model_dump(mode="json"),
        )
        return MaterialNativeVisualCorrectionResult.model_validate(
            {**body, "receipt_sha256": content_sha256(body)}
        )

    def validate_applied(
        self, receipt: MaterialNativeVisualCorrectionResult, *, actor_id: str
    ) -> MaterialNativeVisualCorrectionPrepared:
        """Reauthorize an actual reviewed successor; receipt hashes alone confer no authority.

        The original source/Native files are resolved by this owner again. Canonical
        content must equal its independently reconstructed image-only insertion;
        no model report, old task pin, Item or Graph is written here.
        """
        receipt = MaterialNativeVisualCorrectionResult.model_validate(
            receipt.model_dump(mode="json")
        )
        if actor_id != receipt.prepared.command.actor_id:
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_PERMISSION_DENIED")
        resolved = self._resolve(receipt.prepared.command, require_current=False)
        if resolved.prepared != receipt.prepared:
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_PREPARATION_CHANGED")
        with self.sessions() as session:
            self._require_applied_current(session, receipt, resolved, actor_id)
        current = self.registry.load_item_content(receipt.item_revision_id)
        if (
            not isinstance(current, AssessmentItemContent)
            or current != resolved.content
            or content_sha256(current.model_dump(mode="json")) != receipt.content.sha256
            or len(canonical_json_bytes(current.model_dump(mode="json")))
            != receipt.prepared.corrected_content_bytes
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_CONTENT_INVALID")
        self.native_sources.read_source(
            MaterialNativeItemReadRequest(
                operation="GET_NATIVE_MATERIAL_ITEM_SOURCE",
                actor_id=actor_id,
                item_revision_id=receipt.item_revision_id,
                item_manifest_sha256=receipt.item_manifest_sha256,
            )
        )
        with self.sessions() as session:
            self._require_applied_current(session, receipt, resolved, actor_id)
        return resolved.prepared

    def _require_applied_current(
        self,
        session: Session,
        receipt: MaterialNativeVisualCorrectionResult,
        resolved: _ResolvedCorrection,
        actor_id: str,
    ) -> None:
        self._authorize(session, actor_id)
        self._require_terminal(session, receipt.prepared.material_revision_id)
        row = session.get(ItemRevisionRecord, receipt.item_revision_id, populate_existing=True)
        base = session.get(
            ItemRevisionRecord,
            receipt.prepared.command.base_item_revision_id,
            populate_existing=True,
        )
        item = session.get(ItemRecord, receipt.prepared.item_id, populate_existing=True)
        if (
            row is None
            or base is None
            or item is None
            or item.lifecycle_state != "ACTIVE"
            or item.current_revision_id != receipt.item_revision_id
            or row.item_id != receipt.prepared.item_id
            or row.revision_state != "APPROVED"
            or row.manifest_sha256 != receipt.item_manifest_sha256
            or row.lock_version != receipt.resource_version
            or row.created_by != actor_id
            or row.approved_by != actor_id
            or base.revision_state != "SUPERSEDED"
            or base.superseded_by_revision_id != receipt.item_revision_id
            or row.content_pack_release_id != base.content_pack_release_id
            or row.metadata_json != resolved.metadata.model_dump(mode="json")
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_APPLIED_STALE")
        components = self._components(session, receipt.item_revision_id)
        content = next(value for value in components if value.component_type == "ITEM_CONTENT")
        provenance = {
            "import_protocol": "reviewed-structured-item-content/1.0",
            "reviewed_by": actor_id,
            "review_reason": "Reviewed Native image-only insertion: "
            + receipt.prepared.prepared_sha256,
            "base_revision_id": receipt.prepared.command.base_item_revision_id,
        }
        if (
            _preserved_sha256(components) != receipt.prepared.preserved_components_sha256
            or _component_pointer(content) != receipt.content
            or any(content.metadata.get(key) != value for key, value in provenance.items())
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_IMPORT_MISMATCH")
