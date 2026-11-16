"""Immutable composition adoption receipt, separate from a request or source payload."""

from typing import Literal, Self

from jsonschema import ValidationError as SchemaValidationError
from pydantic import Field, model_validator

from eom_catalog_contracts.kakao_archive import KakaoBindingId, KakaoRoomId
from eom_catalog_contracts.kakao_question_composition import KakaoCompositionInput
from eom_catalog_contracts.kakao_question_store import KakaoStoredQuestion
from eom_catalog_contracts.models import FrozenModel
from eom_catalog_contracts.validation import validate_contract


class KakaoQuestionCompositionResult(FrozenModel):
    schema_version: Literal["kakao-question-composition-result/1.0"] = (
        "kakao-question-composition-result/1.0"
    )
    composition_id: str = Field(pattern=r"^kakaocomposition_[0-9a-f]{32}$")
    operation: Literal["SPLIT", "MERGE"]
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    inputs: tuple[KakaoCompositionInput, ...] = Field(min_length=1, max_length=100)
    outputs: tuple[KakaoStoredQuestion, ...] = Field(min_length=1, max_length=100)
    replayed: bool = Field(strict=True)

    @model_validator(mode="after")
    def exact_adoption(self) -> Self:
        try:
            validate_contract("kakao-question-composition-result-v1", self.model_dump(mode="json"))
        except SchemaValidationError:
            raise ValueError("KAKAO_ARCHIVE_COMPOSITION_RESULT_INVALID") from None
        inputs = {item.question_id for item in self.inputs}
        outputs = {item.question_id for item in self.outputs}
        if (
            len(inputs) != len(self.inputs)
            or len(outputs) != len(self.outputs)
            or inputs.intersection(outputs)
            or len({item.question_revision_id for item in self.outputs}) != len(self.outputs)
            or self.outputs[0].student is None
            or any(
                item.source_binding_id != self.source_binding_id
                or item.room_id != self.room_id
                or item.resource_version != 1
                or item.previous_revision_id is not None
                or item.review_state != "UNREVIEWED"
                or item.student != self.outputs[0].student
                or item.created_at != self.outputs[0].created_at
                for item in self.outputs
            )
        ):
            raise ValueError("KAKAO_ARCHIVE_COMPOSITION_RESULT_INVALID")
        return self
