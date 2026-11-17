"""Small presentation projections; source/Workflow rules remain with Catalog."""

from typing import Annotated, Literal

from pydantic import Field

from .contracts import UtcDatetime, WebModel
from .kakao_question_contracts import BindingId, QuestionId, RevisionId, RoomId

ConceptTaskId = Annotated[str, Field(pattern=r"^kakaoconcepttask_[0-9a-f]{32}$")]
PageKey = Annotated[str, Field(pattern=r"^E[1-3]P[1-9][0-9]{0,4}$")]


class ConceptCreate(WebModel):
    schema_version: Literal["kakao-concept-create/1.0"]
    source_binding_id: BindingId
    room_id: RoomId
    question_id: QuestionId
    question_revision_id: RevisionId
    expected_question_version: int = Field(strict=True, ge=1, le=2147483647)
    base_study_revision_id: str | None = Field(pattern=r"^kakaostudyrev_[0-9a-f]{32}$")
    additional_instructions: str = Field(max_length=6000, pattern=r"^[^\x00]*$")


class ConceptSummary(WebModel):
    task_id: ConceptTaskId
    source_binding_id: BindingId
    question_id: QuestionId
    question_revision_id: RevisionId
    created_at: UtcDatetime


class ConceptStarted(WebModel):
    schema_version: Literal["kakao-concept-started/1.0"]
    task: ConceptSummary
    replayed: bool = Field(strict=True)


class ConceptHistory(WebModel):
    schema_version: Literal["kakao-concept-history/1.0"]
    items: tuple[ConceptSummary, ...] = Field(max_length=100)
    next_cursor: ConceptTaskId | None


class ConceptCitation(WebModel):
    title: str = Field(min_length=1, max_length=256)
    location: str = Field(min_length=1, max_length=256)
    kind: Literal["APPROVED_ANALYSIS_NOT_VERBATIM_SOURCE", "ORIGINAL_PASSAGE"]
    quote: str | None = Field(min_length=1, max_length=1000)


class ConceptRectangle(WebModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class ConceptCapture(WebModel):
    page_key: PageKey
    physical_page: int = Field(strict=True, ge=1, le=100000)
    rectangle: ConceptRectangle
    reason: str = Field(min_length=1, max_length=500)
    source_title: str = Field(min_length=1, max_length=256)


class ConceptBlock(WebModel):
    title: str = Field(min_length=1, max_length=128)
    relevance: str = Field(min_length=1, max_length=1000)
    explanation: str = Field(min_length=1, max_length=8000)
    citations: tuple[ConceptCitation, ...] = Field(min_length=1, max_length=6)
    captures: tuple[ConceptCapture, ...] = Field(max_length=4)


class ConceptView(WebModel):
    schema_version: Literal["kakao-concept-view/1.0"]
    task: ConceptSummary
    state: Literal[
        "PREPARING",
        "PLAN_PENDING",
        "PLAN_RUNNING",
        "SEARCHING",
        "COMPOSE_PENDING",
        "COMPOSE_RUNNING",
        "COMPLETED",
        "NEEDS_INPUT",
        "FAILED",
        "CANCELLED",
    ]
    result_sha256: str | None = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    focus_summary: str = Field(max_length=1000)
    blocks: tuple[ConceptBlock, ...] = Field(max_length=6)
    staff_checks: tuple[Annotated[str, Field(min_length=1, max_length=2200)], ...] = Field(
        max_length=6
    )
    limitations: tuple[Annotated[str, Field(min_length=1, max_length=256)], ...] = Field(
        max_length=24
    )
