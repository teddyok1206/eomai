"""An authenticated metadata upload selects existing native source receipts, never paths."""

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.material_learning import MaterialLearningUpload
from eom_catalog_contracts.material_learning_intake import (
    MaterialIdempotencyKey,
    MaterialLearningSourceSelection,
    MaterialOperatorId,
)
from eom_catalog_contracts.material_native_intake import _require_native_sources
from eom_catalog_contracts.models import FrozenModel, Sha256, _safe_text
from eom_catalog_contracts.validation import validate_contract

MATERIAL_NATIVE_UPLOAD_MEDIA_TYPE = "application/vnd.eom.native-exam"
MATERIAL_NATIVE_XLSX_MAX_BYTES = 8 * 1024 * 1024
MATERIAL_NATIVE_METADATA_MAX_BYTES = 64 * 1024
MATERIAL_NATIVE_UPLOAD_MAX_BYTES = (
    MATERIAL_NATIVE_XLSX_MAX_BYTES + MATERIAL_NATIVE_METADATA_MAX_BYTES + 1
)


class NativeMaterialExamUpload(FrozenModel):
    """Browser metadata has no authority or self-reported binary identity."""

    schema_version: Literal["material-native-exam-upload/1.0"]
    upload: MaterialLearningUpload
    sources: tuple[MaterialLearningSourceSelection, ...] = Field(min_length=2, max_length=2)
    source_namespace: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    exam_key: str = Field(min_length=1, max_length=256)
    workbook_filename: str = Field(min_length=1, max_length=255)

    _text = field_validator("exam_key", "workbook_filename")(_safe_text)

    @model_validator(mode="after")
    def explicit_upload_contract(self) -> Self:
        validate_contract("material-native-exam-upload-v1", self.model_dump(mode="json"))
        return self


class PrepareNativeMaterialExamCommand(FrozenModel):
    schema_version: Literal["material-native-exam-prepare/1.0"] = "material-native-exam-prepare/1.0"
    operation: Literal["PREPARE_NATIVE_MATERIAL_EXAM"] = "PREPARE_NATIVE_MATERIAL_EXAM"
    actor_id: MaterialOperatorId
    idempotency_key: MaterialIdempotencyKey
    upload: MaterialLearningUpload
    sources: tuple[MaterialLearningSourceSelection, ...] = Field(min_length=2, max_length=2)
    source_namespace: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    exam_key: str = Field(min_length=1, max_length=256)
    workbook_filename: str = Field(min_length=1, max_length=255)
    workbook_sha256: Sha256
    workbook_bytes: int = Field(strict=True, ge=8, le=8 * 1024 * 1024)

    _text = field_validator("exam_key", "workbook_filename")(_safe_text)

    @model_validator(mode="after")
    def exact_native_sources_and_owner(self) -> Self:
        _require_native_sources(self.sources, self.actor_id)
        validate_contract("material-native-exam-prepare-v1", self.model_dump(mode="json"))
        return self
