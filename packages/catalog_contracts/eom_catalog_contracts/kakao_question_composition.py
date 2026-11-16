"""Small user selections for composing exact private questions; never source or authority."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from eom_catalog_contracts.kakao_archive import KakaoBindingId, KakaoRoomId
from eom_catalog_contracts.kakao_question import BlockId, QuestionId, QuestionRevisionId
from eom_catalog_contracts.models import FrozenModel
from eom_catalog_contracts.validation import validate_contract


class KakaoCompositionInput(FrozenModel):
    question_id: QuestionId
    question_revision_id: QuestionRevisionId
    resource_version: int = Field(strict=True, ge=1, le=2147483646)


class KakaoWholeBlockSelection(FrozenModel):
    kind: Literal["BLOCK"] = "BLOCK"
    block_id: BlockId


class KakaoTextSpanSelection(FrozenModel):
    kind: Literal["TEXT_SPAN"] = "TEXT_SPAN"
    block_id: BlockId
    start_codepoint: int = Field(strict=True, ge=0, le=65535)
    end_codepoint: int = Field(strict=True, ge=1, le=65536)

    @model_validator(mode="after")
    def nonempty_span(self) -> Self:
        if self.start_codepoint >= self.end_codepoint:
            raise ValueError("KAKAO_ARCHIVE_TEXT_SPAN_INVALID")
        return self


KakaoCompositionSelection = Annotated[
    KakaoWholeBlockSelection | KakaoTextSpanSelection, Field(discriminator="kind")
]
KakaoCompositionPartition = Annotated[
    tuple[KakaoCompositionSelection, ...], Field(min_length=1, max_length=230)
]


class KakaoQuestionSplit(FrozenModel):
    schema_version: Literal["kakao-question-compose/1.0"] = "kakao-question-compose/1.0"
    operation: Literal["SPLIT"] = "SPLIT"
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    input: KakaoCompositionInput
    partitions: tuple[KakaoCompositionPartition, ...] = Field(min_length=2, max_length=100)

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        validate_contract("kakao-question-compose-v1", self.model_dump(mode="json"))
        return self


class KakaoQuestionMerge(FrozenModel):
    schema_version: Literal["kakao-question-compose/1.0"] = "kakao-question-compose/1.0"
    operation: Literal["MERGE"] = "MERGE"
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    inputs: tuple[KakaoCompositionInput, ...] = Field(min_length=2, max_length=100)

    @model_validator(mode="after")
    def distinct_questions(self) -> Self:
        if len({item.question_id for item in self.inputs}) != len(self.inputs):
            raise ValueError("KAKAO_ARCHIVE_COMPOSITION_INPUT_DUPLICATED")
        validate_contract("kakao-question-compose-v1", self.model_dump(mode="json"))
        return self


KakaoQuestionComposition = Annotated[
    KakaoQuestionSplit | KakaoQuestionMerge, Field(discriminator="operation")
]
