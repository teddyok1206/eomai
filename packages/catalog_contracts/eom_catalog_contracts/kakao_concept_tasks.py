"""Private recommendation intent and small task metadata, without Workflow imports."""

from typing import Annotated, Literal, Self

from eom_identifiers import canonical_json_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat_rag_knowledge import ChatRagScope
from pydantic import Field, model_validator

from .kakao_archive import KakaoBindingId, KakaoRoomId
from .kakao_question import QUESTION_REF, QuestionId, QuestionRevisionId
from .kakao_source import SOURCE_RESOLUTION_REF, SourceRevisionId
from .models import FrozenModel, Sha256, UtcDatetime
from .validation import validate_contract

CONCEPT_TASK_REF = "eom://schemas/kakao-archive/concept-task-store-v1/1.0"
MAX_CONCEPT_INTENT_BYTES = 4 * 1024 * 1024
ConceptTaskId = Annotated[str, Field(pattern=r"^kakaoconcepttask_[0-9a-f]{32}$")]


class KakaoConceptCreate(FrozenModel):
    schema_version: Literal["kakao-concept-create/1.0"] = "kakao-concept-create/1.0"
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    question_id: QuestionId
    question_revision_id: QuestionRevisionId
    expected_question_version: int = Field(strict=True, ge=1, le=2147483647)
    base_study_revision_id: str | None = Field(pattern=r"^kakaostudyrev_[0-9a-f]{32}$")
    additional_instructions: str = Field(max_length=6000, pattern=r"^[^\x00]*$")

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        validate_contract("kakao-concept-task-store-v1", self.model_dump(mode="json"))
        return self


class KakaoConceptSourcePin(FrozenModel):
    source_revision_id: SourceRevisionId
    normalization_revision_id: str = Field(pattern=r"^kakaonormalizationrev_[0-9a-f]{32}$")
    manifest: ArtifactMemberPointer
    closure: tuple[ArtifactMemberPointer, ...] = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def accepted_source(self) -> Self:
        if (
            self.manifest.schema_ref != SOURCE_RESOLUTION_REF
            or self.manifest.media_type != "application/json"
            or len(set(self.closure)) != len(self.closure)
        ):
            raise ValueError("KAKAO_CONCEPT_SOURCE_PIN_INVALID")
        return self


class KakaoConceptIntent(FrozenModel):
    schema_version: Literal["kakao-concept-intent/1.0"] = "kakao-concept-intent/1.0"
    task_id: ConceptTaskId
    request: KakaoConceptCreate
    question_manifest: ArtifactMemberPointer
    scope: ChatRagScope
    sources: tuple[KakaoConceptSourcePin, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def exact_sources(self) -> Self:
        if (
            self.question_manifest.schema_ref != QUESTION_REF
            or self.question_manifest.media_type != "application/json"
            or len({source.source_revision_id for source in self.sources}) != len(self.sources)
            or len({source.normalization_revision_id for source in self.sources})
            != len(self.sources)
            or len(
                {
                    pointer
                    for source in self.sources
                    for pointer in (source.manifest, *source.closure)
                }
            )
            > 8192
            or len(canonical_json_bytes(self)) > MAX_CONCEPT_INTENT_BYTES
        ):
            raise ValueError("KAKAO_CONCEPT_INTENT_INVALID")
        validate_contract("kakao-concept-task-store-v1", self.model_dump(mode="json"))
        return self


class KakaoConceptTask(FrozenModel):
    schema_version: Literal["kakao-concept-task/1.0"] = "kakao-concept-task/1.0"
    task_id: ConceptTaskId
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    question_id: QuestionId
    question_revision_id: QuestionRevisionId
    request_sha256: Sha256
    state: Literal["RESERVED", "PREPARED"]
    intent: ArtifactMemberPointer | None
    created_at: UtcDatetime

    @model_validator(mode="after")
    def exact_intent(self) -> Self:
        if (self.state == "RESERVED") != (self.intent is None) or (
            self.intent is not None
            and (
                self.intent.schema_ref != CONCEPT_TASK_REF
                or self.intent.media_type != "application/json"
            )
        ):
            raise ValueError("KAKAO_CONCEPT_TASK_INVALID")
        validate_contract("kakao-concept-task-store-v1", self.model_dump(mode="json"))
        return self


class KakaoConceptMutation(FrozenModel):
    schema_version: Literal["kakao-concept-mutation/1.0"] = "kakao-concept-mutation/1.0"
    task: KakaoConceptTask
    replayed: bool = Field(strict=True)

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        validate_contract("kakao-concept-task-store-v1", self.model_dump(mode="json"))
        return self
