"""Native file attachment to existing material registration, not another Item registry."""

from collections.abc import Callable, Mapping
from typing import Any

from eom_catalog_contracts.material_learning import MaterialArtifactMember, MaterialExtractionWork
from eom_catalog_contracts.material_native_files import (
    MATERIAL_NATIVE_BINDING_REF,
    MaterialImportedNativeItemMetadata,
    MaterialNativeItemBinding,
    material_native_printed_number,
    require_material_native_binding_for_work,
    require_material_native_metadata_binding,
)
from eom_catalog_contracts.material_native_intake import (
    MaterialNativeLearningIntakeManifest,
    bind_native_exam_items,
)
from eom_identifiers import content_sha256
from eom_item_registry import ComponentPointer
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.material_intake_read import material_intake_pointer, read_material_intake
from eom_catalog_service.material_learning_artifacts import read_material_metadata
from eom_catalog_service.material_learning_models import LearningMaterialRevisionRecord
from eom_catalog_service.material_native_resolution import read_material_native_bundle
from eom_catalog_service.material_task_results import ResolvedMaterialTask
from eom_catalog_service.models import (
    ItemComponentRecord,
    ItemMetadataSnapshotRecord,
    ItemRevisionRecord,
)

NATIVE_ITEM_PACK_METADATA_REF = "eom://metadata/uploaded-material-item@2.0"
NATIVE_BINDING_MEMBER = "native/binding.json"


def resolve_native_material_registration_binding(
    session: Session,
    artifacts: CatalogArtifactService,
    resolved: ResolvedMaterialTask,
    *,
    authorize: Callable[[], None],
) -> MaterialNativeItemBinding | None:
    """Read the actual actor's committed intake; absent material is never a legacy fallback."""
    authorize()
    work = resolved.work
    if not isinstance(work, MaterialExtractionWork):
        raise ValueError("MATERIAL_ITEM_QUESTION_TASK_REQUIRED")
    revision = session.get(LearningMaterialRevisionRecord, work.material_revision_id)
    if (
        revision is None
        or revision.material_id != work.material_id
        or revision.created_by != resolved.operator_id
    ):
        raise ValueError("MATERIAL_NATIVE_REGISTRATION_SOURCE_MISSING")
    pointer = material_intake_pointer(
        session,
        artifact_id=revision.manifest_artifact_id,
        revision_id=revision.manifest_artifact_revision_id,
        sha256=revision.manifest_sha256,
    )
    intake = read_material_intake(artifacts, pointer, authorize=authorize)
    if not isinstance(intake, MaterialNativeLearningIntakeManifest):
        return None
    if (intake.material_id, intake.material_revision_id, intake.requested_by) != (
        work.material_id,
        work.material_revision_id,
        resolved.operator_id,
    ):
        raise ValueError("MATERIAL_NATIVE_REGISTRATION_SOURCE_MISMATCH")
    bundle = read_material_native_bundle(
        artifacts,
        intake.native_bundle,
        sources=intake.sources,
        operator_id=resolved.operator_id,
        authorize=authorize,
    )
    number = material_native_printed_number(work.question.printed_label)
    (binding,) = bind_native_exam_items(
        bundle,
        material_id=work.material_id,
        material_revision_id=work.material_revision_id,
        units={number: (work.unit_key, work.question.printed_label or "")},
    )
    require_material_native_binding_for_work(binding, work)
    authorize()
    return binding


def native_material_components(
    binding: MaterialNativeItemBinding, pointer: MaterialArtifactMember
) -> tuple[ComponentPointer, ...]:
    """Each document is already a canonical primary Artifact; never republish its bytes."""
    return (
        ComponentPointer(
            component_type="METADATA",
            ordinal=0,
            **pointer.model_dump(
                include={
                    "schema_ref",
                    "media_type",
                    "artifact_id",
                    "artifact_revision_id",
                    "sha256",
                }
            ),
            logical_name=pointer.member_path,
            metadata={"metadata_kind": "NATIVE_ITEM_SOURCE_BINDING_V1"},
        ),
        *tuple(
            ComponentPointer(
                component_type="OTHER",
                ordinal=ordinal,
                **file.document.model_dump(
                    include={
                        "schema_ref",
                        "media_type",
                        "artifact_id",
                        "artifact_revision_id",
                        "sha256",
                    }
                ),
                logical_name=file.document.member_path,
                metadata={"document_role": file.source_role},
            )
            for ordinal, file in enumerate((binding.question, binding.solution))
        ),
    )


def native_material_metadata(
    base: Mapping[str, Any], binding: MaterialNativeItemBinding, pointer: MaterialArtifactMember
) -> MaterialImportedNativeItemMetadata:
    return MaterialImportedNativeItemMetadata.model_validate(
        {
            **base,
            "schema_version": "material-imported-native-item-metadata/2.0",
            "native_binding": pointer.model_dump(mode="json"),
            "item_number": binding.item_number,
            **binding.source_metadata.model_dump(mode="json"),
        }
    )


def verify_registered_native_material(
    session: Session,
    artifacts: CatalogArtifactService,
    revision: ItemRevisionRecord,
    components: Mapping[tuple[str, int], ItemComponentRecord],
    binding: MaterialNativeItemBinding,
) -> None:
    """Replay checks the exact committed binding/metadata and both native member pointers."""
    metadata = MaterialImportedNativeItemMetadata.model_validate(revision.metadata_json)
    require_material_native_metadata_binding(metadata, binding)
    pointer = metadata.native_binding
    actual = read_material_metadata(
        artifacts,
        pointer,
        MaterialNativeItemBinding,
        schema_ref=MATERIAL_NATIVE_BINDING_REF,
        member_path=NATIVE_BINDING_MEMBER,
        maximum_bytes=4 * 1024 * 1024,
    )
    snapshot = session.scalar(
        select(ItemMetadataSnapshotRecord).where(
            ItemMetadataSnapshotRecord.item_revision_id == revision.item_revision_id
        )
    )
    if (
        actual != binding
        or snapshot is None
        or snapshot.schema_ref != NATIVE_ITEM_PACK_METADATA_REF
        or snapshot.metadata_json != revision.metadata_json
        or snapshot.metadata_sha256 != revision.metadata_sha256
        or revision.metadata_sha256 != content_sha256(revision.metadata_json)
    ):
        raise ValueError("MATERIAL_ITEM_REGISTRATION_REPLAY_CONFLICT")
    for expected in native_material_components(binding, pointer):
        component = components.get((expected.component_type, expected.ordinal))
        if (
            component is None
            or any(
                getattr(component, field) != getattr(expected, field)
                for field in (
                    "schema_ref",
                    "media_type",
                    "artifact_id",
                    "artifact_revision_id",
                    "sha256",
                    "logical_name",
                    "required",
                )
            )
            or component.metadata_json != expected.metadata
        ):
            raise ValueError("MATERIAL_ITEM_REGISTRATION_REPLAY_CONFLICT")
