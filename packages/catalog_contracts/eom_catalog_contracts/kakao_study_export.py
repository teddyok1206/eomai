"""Saved-study source pins around the existing study-layout PDF export family."""

from typing import Literal, Self

from jsonschema.exceptions import ValidationError as JsonSchemaError
from pydantic import ConfigDict, Field, model_validator

from .kakao_archive import KakaoBindingId
from .kakao_export_store import KakaoExport
from .kakao_study_store import StudyId, StudyRevisionId
from .models import FrozenModel, Sha256
from .validation import validate_contract


class _StudyExportValue(FrozenModel):
    model_config = ConfigDict(hide_input_in_errors=True, revalidate_instances="always")

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        try:
            validate_contract("kakao-study-export-v1", self.model_dump(mode="json"))
        except JsonSchemaError:
            raise ValueError("KAKAO_STUDY_EXPORT_INVALID") from None
        return self


class KakaoStudyExportPin(_StudyExportValue):
    study_id: StudyId
    study_revision_id: StudyRevisionId
    manifest_sha256: Sha256


class KakaoStudyExportCreate(_StudyExportValue):
    schema_version: Literal["kakao-study-export-create/1.0"] = "kakao-study-export-create/1.0"
    source_binding_id: KakaoBindingId
    study: KakaoStudyExportPin


class KakaoStudyExport(_StudyExportValue):
    schema_version: Literal["kakao-study-export/1.0"] = "kakao-study-export/1.0"
    study: KakaoStudyExportPin
    export: KakaoExport


class KakaoStudyExportMutation(_StudyExportValue):
    schema_version: Literal["kakao-study-export-mutation/1.0"] = "kakao-study-export-mutation/1.0"
    result: KakaoStudyExport
    replayed: bool = Field(strict=True)
