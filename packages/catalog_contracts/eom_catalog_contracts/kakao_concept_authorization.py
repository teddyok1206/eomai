"""Runner-only source reauthorization; the saved task, not the caller, owns authority."""

from typing import Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from .models import FrozenModel, Sha256
from .validation import validate_contract

CONCEPT_AUTHORIZATION_MAX_BYTES = 16_384
CONCEPT_AUTHORIZATION_OPERATION = "AUTHORIZE_KAKAO_CONCEPT_INPUT"


class KakaoConceptAuthorizationRequest(FrozenModel):
    schema_version: Literal["kakao-concept-authorization-request/1.0"] = (
        "kakao-concept-authorization-request/1.0"
    )
    operation: Literal["AUTHORIZE_KAKAO_CONCEPT_INPUT"] = "AUTHORIZE_KAKAO_CONCEPT_INPUT"
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    step_run_id: str = Field(pattern=r"^steprun_[0-9a-f]{32}$")
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    plan_sha256: Sha256
    work_sha256: Sha256

    @model_validator(mode="after")
    def installed_contract(self) -> Self:
        validate_contract("kakao-concept-authorization-v1", self.model_dump(mode="json"))
        return self


class KakaoConceptAuthorizationReply(FrozenModel):
    schema_version: Literal["kakao-concept-authorization-reply/1.0"] = (
        "kakao-concept-authorization-reply/1.0"
    )
    operation: Literal["AUTHORIZE_KAKAO_CONCEPT_INPUT"] = "AUTHORIZE_KAKAO_CONCEPT_INPUT"
    status: Literal["SUCCESS", "FAILED"]
    request_sha256: Sha256
    work_sha256: Sha256 | None
    error_code: (
        Literal["KAKAO_CONCEPT_AUTHORIZATION_FAILED", "KAKAO_CONCEPT_AUTHORIZATION_UNAVAILABLE"]
        | None
    )

    @model_validator(mode="after")
    def coherent_reply(self) -> Self:
        validate_contract("kakao-concept-authorization-v1", self.model_dump(mode="json"))
        return self

    def validate_for(self, request: KakaoConceptAuthorizationRequest) -> None:
        if self.request_sha256 != content_sha256(request) or (
            self.status == "SUCCESS" and self.work_sha256 != request.work_sha256
        ):
            raise ValueError("KAKAO_CONCEPT_AUTHORIZATION_REPLY_MISMATCH")
