"""Bounded public DTOs for orchestrated in-product customer support."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel, UtcDatetime


class CreateCustomerSupportCaseRequest(ApiModel):
    category: Literal["HOW_TO", "TECHNICAL_ERROR", "CONTENT_QUALITY", "FEATURE_REQUEST"]
    subject: str = Field(
        min_length=3,
        max_length=120,
        pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f]+$",
    )
    question: str = Field(
        min_length=10,
        max_length=4000,
        pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f]+$",
    )
    locale: Literal["ko-KR"] = "ko-KR"
    browser_route: str | None = Field(
        default=None,
        max_length=512,
        pattern=r"^/[^\x00-\x1f?#]*$",
    )
    inquiry_id: str | None = Field(default=None, pattern=r"^webreq_[0-9a-f]{24}$")
    stable_error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    web_release_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")


class CustomerSupportActionView(ApiModel):
    title: str = Field(min_length=1, max_length=80)
    instruction: str = Field(min_length=1, max_length=1000)


class CustomerSupportCaseView(ApiModel):
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    category: Literal["HOW_TO", "TECHNICAL_ERROR", "CONTENT_QUALITY", "FEATURE_REQUEST"]
    subject: str = Field(min_length=3, max_length=120)
    question: str = Field(min_length=10, max_length=4000)
    state: Literal["SUBMITTED", "DIAGNOSING", "ANSWERED", "FAILED"]
    classification: (
        Literal[
            "USAGE_GUIDANCE",
            "TRANSIENT_RUNTIME",
            "VALIDATION_ERROR",
            "PERMISSION_OR_SESSION",
            "CONTENT_QUALITY",
            "FEATURE_REQUEST",
            "UNKNOWN",
        ]
        | None
    ) = None
    answer_text: str | None = Field(default=None, min_length=1, max_length=6000)
    recommended_actions: tuple[CustomerSupportActionView, ...] = Field(default=(), max_length=5)
    needs_operator: bool = False
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    created_at: UtcDatetime
    updated_at: UtcDatetime
    resource_version: int = Field(ge=1)

    @model_validator(mode="after")
    def answer_matches_state(self) -> CustomerSupportCaseView:
        if self.state == "ANSWERED":
            if self.classification is None or self.answer_text is None:
                raise ValueError("answered customer-support case requires a classified answer")
        elif (
            self.classification is not None
            or self.answer_text is not None
            or self.recommended_actions
            or self.needs_operator
        ):
            raise ValueError("non-answered customer-support case cannot expose answer output")
        return self
