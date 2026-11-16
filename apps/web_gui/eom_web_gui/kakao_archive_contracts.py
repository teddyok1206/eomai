"""Strict browser wire values; Catalog alone owns private binding rules and state."""

from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_web_gui.contracts import UtcDatetime, WebModel

BindingId = Annotated[str, Field(pattern=r"^kakaobinding_[0-9a-f]{32}$")]
PolicyRevisionId = Annotated[str, Field(pattern=r"^kakaopolicyrev_[0-9a-f]{32}$")]
ResourceVersion = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
Label = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[^\x00-\x1f\x7f]*\S[^\x00-\x1f\x7f]*$")
]


class CollectionPolicy(WebModel):
    interval_minutes: int = Field(strict=True, ge=60, le=10080)
    include_images: Literal[True]
    source_timezone: Literal["unknown", "Asia/Seoul"]
    question_rule_version: Literal["turn_v1"]

    @field_validator("include_images", mode="before")
    @classmethod
    def literal_boolean(cls, value: object) -> object:
        if value is not True:
            raise ValueError("include_images must be true")
        return value


class PolicyRevision(WebModel):
    source_binding_id: BindingId
    policy_revision_id: PolicyRevisionId
    previous_revision_id: PolicyRevisionId | None
    revision_number: ResourceVersion
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    policy: CollectionPolicy
    created_at: UtcDatetime


class BindingCreate(WebModel):
    schema_version: Literal["kakao-binding-create/1.0"]
    action: Literal["CREATE"]
    display_name: Label
    policy: CollectionPolicy


class BindingUpdatePolicy(WebModel):
    schema_version: Literal["kakao-binding-command/1.0"]
    action: Literal["UPDATE_COLLECTION_POLICY"]
    parent_policy_revision_id: PolicyRevisionId
    expected_resource_version: ResourceVersion
    policy: CollectionPolicy


class BindingRetire(WebModel):
    schema_version: Literal["kakao-binding-command/1.0"]
    action: Literal["RETIRE"]
    parent_policy_revision_id: PolicyRevisionId
    expected_resource_version: ResourceVersion


BindingCommand = Annotated[BindingUpdatePolicy | BindingRetire, Field(discriminator="action")]


class SourceBinding(WebModel):
    schema_version: Literal["kakao-source-binding/1.0"]
    source_binding_id: BindingId
    display_name: Label
    state: Literal["DRAFT", "RETIRED"]
    resource_version: ResourceVersion
    policy_revision: PolicyRevision
    schedule_enabled: Literal[False]
    capability_state: Literal["NOT_VERIFIED"]
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @field_validator("schedule_enabled", mode="before")
    @classmethod
    def literal_boolean(cls, value: object) -> object:
        if value is not False:
            raise ValueError("unverified binding cannot enable collection")
        return value

    @model_validator(mode="after")
    def exact_policy_binding(self) -> Self:
        if self.policy_revision.source_binding_id != self.source_binding_id:
            raise ValueError("policy belongs to a different binding")
        return self


class BindingPage(WebModel):
    items: tuple[SourceBinding, ...] = Field(max_length=100)
    next_cursor: BindingId | None


class BindingMutation(WebModel):
    binding: SourceBinding
    replayed: bool = Field(strict=True)
