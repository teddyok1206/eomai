"""Read-only reauthorization for a persisted material role, not worker authority."""

from typing import Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

MATERIAL_AUTHORIZATION_MAX_BYTES = 16_384


class MaterialLearningAuthorizationRequest(FrozenModel):
    schema_version: Literal["material-learning-authorization-request/1.0"] = (
        "material-learning-authorization-request/1.0"
    )
    operation: Literal["AUTHORIZE_MATERIAL_LEARNING_INPUT"] = "AUTHORIZE_MATERIAL_LEARNING_INPUT"
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    step_run_id: str = Field(pattern=r"^steprun_[0-9a-f]{32}$")
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    plan_sha256: Sha256
    input_sha256: Sha256

    @model_validator(mode="after")
    def installed_contract(self) -> Self:
        validate_contract(
            "material-learning-authorization-request-v1", self.model_dump(mode="json")
        )
        return self


class MaterialLearningAuthorizationReply(FrozenModel):
    schema_version: Literal["material-learning-authorization-reply/1.0"] = (
        "material-learning-authorization-reply/1.0"
    )
    operation: Literal["AUTHORIZE_MATERIAL_LEARNING_INPUT"] = "AUTHORIZE_MATERIAL_LEARNING_INPUT"
    status: Literal["SUCCESS", "FAILED"]
    request_sha256: Sha256
    input_sha256: Sha256 | None
    error_code: (
        Literal[
            "MATERIAL_LEARNING_AUTHORIZATION_FAILED", "MATERIAL_LEARNING_AUTHORIZATION_UNAVAILABLE"
        ]
        | None
    )

    @model_validator(mode="after")
    def coherent_reply(self) -> Self:
        validate_contract("material-learning-authorization-reply-v1", self.model_dump(mode="json"))
        if self.status == "SUCCESS":
            if self.input_sha256 is None or self.error_code is not None:
                raise ValueError("MATERIAL_LEARNING_AUTHORIZATION_REPLY_INVALID")
        elif self.input_sha256 is not None or self.error_code is None:
            raise ValueError("MATERIAL_LEARNING_AUTHORIZATION_REPLY_INVALID")
        return self

    def validate_for(self, request: MaterialLearningAuthorizationRequest) -> None:
        if self.request_sha256 != content_sha256(request.model_dump(mode="json")) or (
            self.status == "SUCCESS" and self.input_sha256 != request.input_sha256
        ):
            raise ValueError("MATERIAL_LEARNING_AUTHORIZATION_REPLY_MISMATCH")
