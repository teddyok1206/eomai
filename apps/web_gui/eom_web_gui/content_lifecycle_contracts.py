"""Closed lifecycle wire values; Catalog owns shelving, permissions and CAS."""

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from eom_web_gui.content_planning_contracts import EditionId, ProductId, RevisionId
from eom_web_gui.contracts import UtcDatetime, WebModel


class ContentTarget(WebModel):
    target_kind: Literal["CONTENT"]
    target_id: ProductId


class EditionTarget(WebModel):
    target_kind: Literal["EDITION"]
    target_id: EditionId


LifecycleTarget = Annotated[ContentTarget | EditionTarget, Field(discriminator="target_kind")]
LifecycleState = Literal["ACTIVE", "ARCHIVED"]


class ReadLifecycle(WebModel):
    action_kind: Literal["READ_LIFECYCLE"]
    target: LifecycleTarget


class ListLifecycle(WebModel):
    action_kind: Literal["LIST_LIFECYCLE"]
    target_kind: Literal["CONTENT", "EDITION"]
    deliverable_id: ProductId | None
    lifecycle_state: Literal["ALL", "ACTIVE", "ARCHIVED"]
    after_id: ProductId | EditionId | None
    limit: int = Field(strict=True, ge=1, le=100)


class ChangeLifecycle(WebModel):
    action_kind: Literal["CHANGE_LIFECYCLE"]
    target: LifecycleTarget
    expected_state: LifecycleState
    expected_version: int = Field(strict=True, ge=0)
    desired_state: LifecycleState
    reason: str = Field(
        min_length=1, max_length=2000, pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$"
    )


LifecycleQuery = Annotated[ReadLifecycle | ListLifecycle, Field(discriminator="action_kind")]
LifecycleAction = Annotated[
    ReadLifecycle | ListLifecycle | ChangeLifecycle, Field(discriminator="action_kind")
]


class LifecycleEntry(WebModel):
    target: LifecycleTarget
    deliverable_id: ProductId
    title: str = Field(min_length=1, max_length=256)
    lifecycle_state: LifecycleState
    version: int = Field(strict=True, ge=0)
    current_revision_id: RevisionId | None
    parent_archived: bool


class LifecycleEvent(WebModel):
    sequence: int = Field(strict=True, ge=1)
    prior_state: str = Field(max_length=32)
    new_state: str = Field(max_length=32)
    actor_id: str = Field(max_length=128)
    created_at: UtcDatetime
    reason: str = Field(max_length=2000)


class LifecycleView(WebModel):
    result_kind: Literal["LIFECYCLE_VIEW"]
    entry: LifecycleEntry
    events: tuple[LifecycleEvent, ...] = Field(max_length=50)


class LifecycleList(WebModel):
    result_kind: Literal["LIFECYCLE_LIST"]
    rows: tuple[LifecycleEntry, ...] = Field(max_length=100)
    next_id: ProductId | EditionId | None


class LifecycleMutation(WebModel):
    result_kind: Literal["LIFECYCLE_MUTATION"]
    entry: LifecycleEntry
    replayed: bool
    disposition: Literal["CHANGED", "NO_CHANGE"]


LifecycleResult = Annotated[
    LifecycleView | LifecycleList | LifecycleMutation, Field(discriminator="result_kind")
]
LIFECYCLE_RESULT: TypeAdapter[LifecycleResult] = TypeAdapter(LifecycleResult)
