"""Native visual successors pin new catalogs without replacing base document sources.

These immutable values are not permission or pixel-match evidence. The existing
Catalog owner resolves every pointer and verifies the catalogs and native files.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_image_contracts.office_picture_uses import OfficeObjectId
from pydantic import Field, model_validator

from eom_catalog_contracts.material_learning import (
    MaterialArtifactMember,
    MaterialPreparedSource,
    SourceRole,
)
from eom_catalog_contracts.material_native_files import (
    NATIVE_ITEM_DOCUMENT_REF,
    NATIVE_ITEM_SPLIT_EVIDENCE_REF,
    NativeNumber,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

if TYPE_CHECKING:
    from eom_catalog_contracts.material_native_intake import MaterialNativePreparedArtifact

MATERIAL_NATIVE_VISUAL_PREPARED_REF = "eom://schemas/material-learning/prepared/3.0"
_CATALOG_REF = "eom://schemas/image-provider/office-picture-use-catalog/1.0"
_HWPX_MEDIA = frozenset({"application/vnd.hancom.hwpx", "application/hwp+zip"})
_MAX_METADATA = 4 * 1024 * 1024


def _require_json_pointer(
    pointer: MaterialArtifactMember,
    *,
    schema_ref: str,
    maximum_bytes: int,
    member_path: str | None = None,
) -> None:
    if (
        pointer.schema_ref != schema_ref
        or pointer.media_type != "application/json"
        or pointer.bytes > maximum_bytes
        or (member_path is not None and pointer.member_path != member_path)
    ):
        raise ValueError("MATERIAL_NATIVE_VISUAL_POINTER_INVALID")


def _member_identity(pointer: MaterialArtifactMember) -> tuple[str, str]:
    return pointer.artifact_revision_id, pointer.member_path


class MaterialNativeVisualCatalogSupplement(FrozenModel):
    source_role: SourceRole
    base_catalog: MaterialArtifactMember
    catalog: MaterialArtifactMember

    @model_validator(mode="after")
    def exact_catalog_successor(self) -> Self:
        for pointer in (self.base_catalog, self.catalog):
            _require_json_pointer(
                pointer,
                schema_ref=_CATALOG_REF,
                maximum_bytes=8 * 1024 * 1024,
                member_path="picture-use-catalog.json",
            )
        if (
            _member_identity(self.base_catalog) == _member_identity(self.catalog)
            and self.base_catalog != self.catalog
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_CATALOG_POINTER_CONFLICT")
        return self


class MaterialNativeQuestionVisualScope(FrozenModel):
    item_number: NativeNumber
    question_document: MaterialArtifactMember
    split_evidence: MaterialArtifactMember
    source_catalog_sha256: Sha256
    allowed_picture_use_ids: tuple[OfficeObjectId, ...] = Field(max_length=64)

    @model_validator(mode="after")
    def exact_native_question_scope(self) -> Self:
        if (
            self.question_document.schema_ref != NATIVE_ITEM_DOCUMENT_REF
            or self.question_document.media_type not in _HWPX_MEDIA
            or self.question_document.bytes > 256 * 1024 * 1024
            or _member_identity(self.question_document) == _member_identity(self.split_evidence)
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_QUESTION_POINTER_INVALID")
        _require_json_pointer(
            self.split_evidence,
            schema_ref=NATIVE_ITEM_SPLIT_EVIDENCE_REF,
            maximum_bytes=_MAX_METADATA,
        )
        if self.allowed_picture_use_ids != tuple(sorted(set(self.allowed_picture_use_ids))):
            raise ValueError("MATERIAL_NATIVE_VISUAL_USE_IDS_INVALID")
        return self


class MaterialNativeVisualPreparationProfile(FrozenModel):
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    office_tool_source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    parser_implementation_sha256: Sha256
    options_sha256: Sha256
    profile_sha256: Sha256

    @model_validator(mode="after")
    def exact_visual_profile(self) -> Self:
        if self.profile_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"profile_sha256"})
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_PROFILE_HASH_MISMATCH")
        return self


class MaterialNativeVisualPreparedArtifact(FrozenModel):
    schema_version: Literal["material-learning-prepared/3.0"] = "material-learning-prepared/3.0"
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    intake_manifest: MaterialArtifactMember
    profile_sha256: Sha256
    sources: tuple[MaterialPreparedSource, ...] = Field(min_length=2, max_length=2)
    native_bundle: MaterialArtifactMember
    base_prepared: MaterialArtifactMember
    visual_profile: MaterialNativeVisualPreparationProfile
    catalog_supplements: tuple[MaterialNativeVisualCatalogSupplement, ...] = Field(
        min_length=1, max_length=2
    )
    question_visual_scopes: tuple[MaterialNativeQuestionVisualScope, ...] = Field(
        min_length=1, max_length=10000
    )
    prepared_sha256: Sha256

    @model_validator(mode="after")
    def exact_visual_preparation(self) -> Self:
        _require_json_pointer(
            self.intake_manifest,
            schema_ref="eom://schemas/material-learning/intake/2.0",
            maximum_bytes=_MAX_METADATA,
            member_path="material/intake.json",
        )
        _require_json_pointer(
            self.native_bundle,
            schema_ref="eom://schemas/material-learning/native-exam-bundle/1.0",
            maximum_bytes=_MAX_METADATA,
        )
        _require_json_pointer(
            self.base_prepared,
            schema_ref="eom://schemas/material-learning/prepared/2.0",
            maximum_bytes=_MAX_METADATA,
            member_path="material/prepared.json",
        )
        if (
            tuple(source.source_role for source in self.sources) != ("MAIN", "SOLUTIONS")
            or any(source.actual_format not in {"HWP", "HWPX"} for source in self.sources)
            or len({source.document_revision_id for source in self.sources}) != 2
            or len({source.original.sha256 for source in self.sources}) != 2
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_BASE_SOURCE_INVALID")
        sources = {source.source_role: source for source in self.sources}
        roles = tuple(supplement.source_role for supplement in self.catalog_supplements)
        if roles not in {("MAIN",), ("SOLUTIONS",), ("MAIN", "SOLUTIONS")} or any(
            supplement.base_catalog != sources[supplement.source_role].office_catalog
            for supplement in self.catalog_supplements
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_CATALOG_CHAIN_MISMATCH")
        catalogs = {
            supplement.source_role: supplement.catalog for supplement in self.catalog_supplements
        }
        main_catalog = catalogs.get("MAIN", sources["MAIN"].office_catalog)
        assert main_catalog is not None
        scopes = self.question_visual_scopes
        numbers = tuple(scope.item_number for scope in scopes)
        if (
            numbers != tuple(sorted(set(numbers)))
            or len({_member_identity(scope.question_document) for scope in scopes}) != len(scopes)
            or len({_member_identity(scope.split_evidence) for scope in scopes}) != len(scopes)
            or any(scope.source_catalog_sha256 != main_catalog.sha256 for scope in scopes)
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_QUESTION_SCOPE_MISMATCH")
        value = self.model_dump(mode="json")
        if len(canonical_json_bytes(value)) > _MAX_METADATA:
            raise ValueError("MATERIAL_NATIVE_VISUAL_PREPARED_METADATA_TOO_LARGE")
        if self.prepared_sha256 != content_sha256(
            {key: entry for key, entry in value.items() if key != "prepared_sha256"}
        ):
            raise ValueError("MATERIAL_LEARNING_PREPARATION_HASH_MISMATCH")
        validate_contract("material-learning-prepared-v3", value)
        return self


def require_native_visual_prepared_base(
    prepared: MaterialNativeVisualPreparedArtifact,
    *,
    base: MaterialNativePreparedArtifact,
    base_pointer: MaterialArtifactMember,
) -> None:
    """Compare a resolved base; the caller still owns current actor and Artifact authorization."""
    base_value = base.model_dump(mode="json")
    if (
        base.schema_version != "material-learning-prepared/2.0"
        or prepared.base_prepared != base_pointer
        or base_pointer.sha256 != content_sha256(base_value)
        or base_pointer.bytes != len(canonical_json_bytes(base_value))
        or any(
            getattr(prepared, field) != getattr(base, field)
            for field in (
                "material_id",
                "material_revision_id",
                "intake_manifest",
                "profile_sha256",
                "sources",
                "native_bundle",
            )
        )
    ):
        raise ValueError("MATERIAL_NATIVE_VISUAL_PREPARED_BASE_MISMATCH")
