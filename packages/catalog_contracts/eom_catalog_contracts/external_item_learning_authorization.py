"""Runner-only current source authorization; no caller-supplied operator authority."""

from __future__ import annotations

import json
from typing import Literal

from eom_identifiers import canonical_json_bytes, content_sha256
from pydantic import BaseModel, ConfigDict, Field, model_validator

from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

EXTERNAL_ITEM_LEARNING_AUTHORIZATION_OPERATION = "AUTHORIZE_EXTERNAL_ITEM_LEARNING_INPUT"
MAX_EXTERNAL_ITEM_LEARNING_AUTHORIZATION_BYTES = 4096
type ExternalItemLearningAuthorizationErrorCode = Literal[
    "EXTERNAL_CREATIVE_AUTHORIZATION_REQUEST_INVALID",
    "EXTERNAL_CREATIVE_AUTHORIZATION_BINDING_INVALID",
    "EXTERNAL_CREATIVE_AUTHORIZATION_PERMISSION_DENIED",
    "EXTERNAL_CREATIVE_AUTHORIZATION_SOURCE_STALE",
    "EXTERNAL_CREATIVE_AUTHORIZATION_UNAVAILABLE",
]


class ExternalItemLearningRoleSelection(FrozenModel):
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    step_run_id: str = Field(pattern=r"^steprun_[0-9a-f]{32}$")
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    plan_sha256: Sha256
    work_input_sha256: Sha256


class _AuthorizationMessage(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        if not isinstance(value, dict):
            raise ValueError("EXTERNAL_CREATIVE_AUTHORIZATION_REQUEST_INVALID")
        try:
            payload = canonical_json_bytes(value)
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError("EXTERNAL_CREATIVE_AUTHORIZATION_REQUEST_INVALID") from exc
        if len(payload) >= MAX_EXTERNAL_ITEM_LEARNING_AUTHORIZATION_BYTES:
            raise ValueError("EXTERNAL_CREATIVE_AUTHORIZATION_REQUEST_INVALID")
        document = json.loads(payload)
        validate_contract("external-item-learning-authorization-v1", document)
        return document


class ExternalItemLearningAuthorizationRequest(_AuthorizationMessage):
    schema_version: Literal["external-item-learning-authorization-request/1.0"]
    operation: Literal["AUTHORIZE_EXTERNAL_ITEM_LEARNING_INPUT"]
    selection: ExternalItemLearningRoleSelection


class ExternalItemLearningAuthorizationReply(_AuthorizationMessage):
    schema_version: Literal["external-item-learning-authorization-reply/1.0"]
    operation: Literal["AUTHORIZE_EXTERNAL_ITEM_LEARNING_INPUT"]
    status: Literal["SUCCESS", "FAILED"]
    request_sha256: Sha256 | None
    source_input_sha256: Sha256 | None
    error_code: ExternalItemLearningAuthorizationErrorCode | None


def validate_external_item_learning_authorization_reply(
    request: ExternalItemLearningAuthorizationRequest,
    reply: ExternalItemLearningAuthorizationReply,
    *,
    expected_source_input_sha256: str,
) -> None:
    request = ExternalItemLearningAuthorizationRequest.model_validate(request)
    reply = ExternalItemLearningAuthorizationReply.model_validate(reply)
    if reply.request_sha256 != content_sha256(request.model_dump(mode="json")) or (
        reply.status == "SUCCESS" and reply.source_input_sha256 != expected_source_input_sha256
    ):
        raise ValueError("EXTERNAL_CREATIVE_AUTHORIZATION_BINDING_INVALID")
