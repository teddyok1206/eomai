"""Closed presentation adapter for the API's reference-start reply, no business authority."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from eom_web_gui.contracts import WebModel


class ReferenceItemStartCommand(WebModel):
    command_id: str = Field(min_length=1, max_length=128)
    resource_type: Literal["workflow"]
    resource_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    status: Literal["ACCEPTED"]
    resource_version: int = Field(strict=True, ge=1)
    status_url: str = Field(pattern=r"^/api/v1/workflows/workflow_[0-9a-f]{32}$")

    @model_validator(mode="after")
    def exact_target(self) -> Self:
        if self.status_url != f"/api/v1/workflows/{self.resource_id}":
            raise ValueError("reference command target differs")
        return self


class ReferenceItemStartReply(WebModel):
    schema_version: Literal["workflow-reference-start-reply/1.0"]
    status: Literal["PENDING", "ACCEPTED"]
    reference_query_workflow_id: str | None = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    command: ReferenceItemStartCommand | None

    @model_validator(mode="after")
    def pending_is_not_an_item(self) -> Self:
        if self.status == "PENDING":
            if self.reference_query_workflow_id is None or self.command is not None:
                raise ValueError("pending preparation has no accepted Item")
        elif self.reference_query_workflow_id is not None or self.command is None:
            raise ValueError("accepted Item requires its exact command")
        return self


class ReferenceQueryPreparationPointer(WebModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: Literal["preparation.json"]
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    schema_ref: Literal["eom://schemas/workflow/reference-query-routed-preparation/1.0"]
    media_type: Literal["application/json"]


class ReferenceItemPreparationPending(WebModel):
    schema_version: Literal["workflow-reference-start-reply/2.0"]
    status: Literal["PENDING"]
    reference_query_workflow_id: str | None = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    reference_query_preparation: ReferenceQueryPreparationPointer
    reference_query_parent_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    command: None


type SupportedReferenceItemStartReply = Annotated[
    ReferenceItemStartReply | ReferenceItemPreparationPending,
    Field(discriminator="schema_version"),
]


def parse_reference_item_start_reply(value: object) -> SupportedReferenceItemStartReply:
    return TypeAdapter(SupportedReferenceItemStartReply).validate_python(value)
