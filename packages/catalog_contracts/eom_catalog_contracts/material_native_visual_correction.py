"""Exact reviewed insertion of one existing Native picture-use pointer.

These values identify a correction, not permission, semantic review or Graph
publication. The Catalog application resolves all supplied identities again.
"""

from typing import Literal, Self

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, model_validator

from eom_catalog_contracts.assessment_item import (
    ASSESSMENT_ITEM_CONTENT_SCHEMA_REF,
    ImageBlock,
)
from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_native_visual_preparation import (
    MaterialNativeQuestionVisualScope,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract


def native_visual_correction_block_id(picture_use_id: str) -> str:
    """One deterministic image identity; the application validates the actual use."""
    return "block_native_visual_" + picture_use_id.removeprefix("officeobj_")


class MaterialNativeVisualCorrectionCommand(FrozenModel):
    schema_version: Literal["material-native-visual-correction-command/1.0"] = (
        "material-native-visual-correction-command/1.0"
    )
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    base_item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    base_item_manifest_sha256: Sha256
    expected_version: int = Field(strict=True, ge=1)
    picture_use_id: str = Field(pattern=r"^officeobj_[0-9a-f]{32}$")
    insert_after_block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")

    @model_validator(mode="after")
    def declared_command(self) -> Self:
        validate_contract(
            "material-native-visual-correction-command-v1", self.model_dump(mode="json")
        )
        return self


class MaterialNativeVisualCorrectionPrepared(FrozenModel):
    schema_version: Literal["material-native-visual-correction-prepared/1.0"] = (
        "material-native-visual-correction-prepared/1.0"
    )
    command: MaterialNativeVisualCorrectionCommand
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    source_task_id: str = Field(pattern=r"^materialtask_[0-9a-f]{32}$")
    source_lineage: MaterialArtifactMember
    native_binding: MaterialArtifactMember
    catalog: MaterialArtifactMember
    scope: MaterialNativeQuestionVisualScope
    base_content: ArtifactMemberPointer
    image: ImageBlock
    corrected_content_sha256: Sha256
    corrected_content_bytes: int = Field(strict=True, ge=1, le=2 * 1024 * 1024)
    preserved_components_sha256: Sha256
    prepared_sha256: Sha256

    @model_validator(mode="after")
    def exact_preparation(self) -> Self:
        expected = (
            (
                self.source_lineage,
                "eom://schemas/material-learning/item-lineage/1.0",
                "lineage.json",
            ),
            (
                self.native_binding,
                "eom://schemas/material-learning/native-item-binding/1.0",
                "native/binding.json",
            ),
            (
                self.catalog,
                "eom://schemas/image-provider/office-picture-use-catalog/1.0",
                "picture-use-catalog.json",
            ),
            (self.base_content, ASSESSMENT_ITEM_CONTENT_SCHEMA_REF, "assessment-item-content.json"),
        )
        if any(
            pointer.schema_ref != schema
            or pointer.member_path != member
            or pointer.media_type != "application/json"
            for pointer, schema, member in expected
        ) or (
            self.scope.source_catalog_sha256 != self.catalog.sha256
            or self.command.picture_use_id not in self.scope.allowed_picture_use_ids
            or self.image.block_id != native_visual_correction_block_id(self.command.picture_use_id)
            or self.image.artifact.artifact_id != self.catalog.artifact_id
            or self.image.artifact.artifact_revision_id != self.catalog.artifact_revision_id
            or self.image.artifact.media_type != "image/png"
            or self.prepared_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"prepared_sha256"}))
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_PREPARATION_INVALID")
        validate_contract(
            "material-native-visual-correction-prepared-v1", self.model_dump(mode="json")
        )
        return self


class MaterialNativeVisualCorrectionResult(FrozenModel):
    schema_version: Literal["material-native-visual-correction-result/1.0"] = (
        "material-native-visual-correction-result/1.0"
    )
    state: Literal["IMPORTED"] = "IMPORTED"
    prepared: MaterialNativeVisualCorrectionPrepared
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: Sha256
    resource_version: int = Field(strict=True, ge=1)
    content: ArtifactMemberPointer
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def exact_successor(self) -> Self:
        if (
            self.item_revision_id == self.prepared.command.base_item_revision_id
            or self.content.schema_ref != ASSESSMENT_ITEM_CONTENT_SCHEMA_REF
            or self.content.media_type != "application/json"
            or self.content.member_path != "assessment-item-content.json"
            or self.content.sha256 != self.prepared.corrected_content_sha256
            or self.receipt_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_CORRECTION_RESULT_INVALID")
        validate_contract(
            "material-native-visual-correction-result-v1", self.model_dump(mode="json")
        )
        return self
