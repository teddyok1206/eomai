"""Content shelving is reversible metadata, never deletion or a publication fact."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from eom_catalog_contracts.content_planning import DeliverableId, DeliverableRevisionId, EditionId
from eom_catalog_contracts.models import FrozenModel, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

type LifecycleState = Literal["ACTIVE", "ARCHIVED"]


class ContentLifecycleTarget(FrozenModel):
    target_kind: Literal["CONTENT"]
    target_id: DeliverableId


class EditionLifecycleTarget(FrozenModel):
    target_kind: Literal["EDITION"]
    target_id: EditionId


type LifecycleTarget = Annotated[
    ContentLifecycleTarget | EditionLifecycleTarget, Field(discriminator="target_kind")
]


class ReadContentLifecycle(FrozenModel):
    action_kind: Literal["READ_LIFECYCLE"]
    target: LifecycleTarget


class ListContentLifecycle(FrozenModel):
    action_kind: Literal["LIST_LIFECYCLE"]
    target_kind: Literal["CONTENT", "EDITION"]
    deliverable_id: DeliverableId | None
    lifecycle_state: Literal["ALL", "ACTIVE", "ARCHIVED"]
    after_id: DeliverableId | EditionId | None
    limit: int = Field(strict=True, ge=1, le=100)

    @model_validator(mode="after")
    def exact_scope(self) -> Self:
        if (self.target_kind == "CONTENT") != (self.deliverable_id is None):
            raise ValueError("edition listing requires its content owner")
        prefix = "deliverable_" if self.target_kind == "CONTENT" else "edition_"
        if self.after_id is not None and not self.after_id.startswith(prefix):
            raise ValueError("lifecycle cursor belongs to another target kind")
        return self


class ChangeContentLifecycle(FrozenModel):
    action_kind: Literal["CHANGE_LIFECYCLE"]
    target: LifecycleTarget
    expected_state: LifecycleState
    expected_version: int = Field(strict=True, ge=0)
    desired_state: LifecycleState
    reason: str = Field(
        min_length=1, max_length=2000, pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$"
    )

    @model_validator(mode="after")
    def meaningful_reason(self) -> Self:
        if not self.reason.strip():
            raise ValueError("lifecycle change requires a reason")
        return self


type ContentLifecycleAction = Annotated[
    ReadContentLifecycle | ListContentLifecycle | ChangeContentLifecycle,
    Field(discriminator="action_kind"),
]


class ContentLifecycleEntry(FrozenModel):
    target: LifecycleTarget
    deliverable_id: DeliverableId
    title: str = Field(min_length=1, max_length=256)
    lifecycle_state: LifecycleState
    version: int = Field(strict=True, ge=0)
    current_revision_id: DeliverableRevisionId | None
    parent_archived: bool


class ContentLifecycleEvent(FrozenModel):
    sequence: int = Field(strict=True, ge=1)
    prior_state: str = Field(max_length=32)
    new_state: str = Field(max_length=32)
    actor_id: str = Field(max_length=128)
    created_at: UtcDatetime
    reason: str = Field(max_length=2000)


class ContentLifecycleView(FrozenModel):
    result_kind: Literal["LIFECYCLE_VIEW"] = "LIFECYCLE_VIEW"
    entry: ContentLifecycleEntry
    events: tuple[ContentLifecycleEvent, ...] = Field(max_length=50)


class ContentLifecycleList(FrozenModel):
    result_kind: Literal["LIFECYCLE_LIST"] = "LIFECYCLE_LIST"
    rows: tuple[ContentLifecycleEntry, ...] = Field(max_length=100)
    next_id: DeliverableId | EditionId | None


class ContentLifecycleMutation(FrozenModel):
    result_kind: Literal["LIFECYCLE_MUTATION"] = "LIFECYCLE_MUTATION"
    entry: ContentLifecycleEntry
    replayed: bool
    disposition: Literal["CHANGED", "NO_CHANGE"]


type ContentLifecycleResult = Annotated[
    ContentLifecycleView | ContentLifecycleList | ContentLifecycleMutation,
    Field(discriminator="result_kind"),
]
_ACTION: TypeAdapter[ContentLifecycleAction] = TypeAdapter(ContentLifecycleAction)
_RESULT: TypeAdapter[ContentLifecycleResult] = TypeAdapter(ContentLifecycleResult)


def parse_content_lifecycle_action(value: dict[str, object]) -> ContentLifecycleAction:
    validate_contract("content-lifecycle-action-v1", value)
    return _ACTION.validate_python(value)


def parse_content_lifecycle_result(value: dict[str, object]) -> ContentLifecycleResult:
    validate_contract("content-lifecycle-result-v1", value)
    return _RESULT.validate_python(value)
