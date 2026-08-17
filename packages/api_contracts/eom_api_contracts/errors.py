"""RFC 9457 Problem Details contracts."""

from pydantic import Field

from eom_api_contracts.common import ApiModel, RequestId


class ValidationIssue(ApiModel):
    pointer: str
    code: str
    detail: str


class ProblemDetails(ApiModel):
    type: str = Field(pattern=r"^urn:eom:problem:[a-z0-9-]+$")
    title: str = Field(min_length=1, max_length=160)
    status: int = Field(ge=400, le=599)
    detail: str = Field(min_length=1, max_length=1000)
    instance: str = Field(pattern=r"^urn:eom:request:[A-Za-z0-9_.-]+$")
    error_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    request_id: RequestId
    errors: tuple[ValidationIssue, ...] = ()
