"""A bounded explicit successor command, not permission to reopen FAILED history."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from eom_identifiers import canonical_json_bytes, content_sha256
from pydantic import ConfigDict, Field, field_validator, model_validator

from eom_catalog_contracts.inference_transfer_invocation_v11 import (
    InferenceTransferPairSubmitRequestV11,
    parse_pair_submit_request_v11,
)
from eom_catalog_contracts.item_inference_transfer import TransferText
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

MAX_TRANSFER_RETRY_BYTES = 40 * 1024
type FailedComparisonStepId = Annotated[str, Field(pattern=r"^steprun_[0-9a-f]{32}$")]


class InferenceTransferPairRetryRequestV1(FrozenModel):
    """Same logical pair; the HTTP path and If-Match bind the exact parent execution."""

    model_config = ConfigDict(revalidate_instances="always")

    schema_version: Literal["inference-transfer-pair-retry/1.0"] = (
        "inference-transfer-pair-retry/1.0"
    )
    failed_step_run_id: FailedComparisonStepId
    failed_attempt: Literal[1]
    selection: InferenceTransferPairSubmitRequestV11
    reason: TransferText = Field(min_length=1, max_length=512)
    retry_sha256: Sha256

    @field_validator("failed_attempt", mode="before")
    @classmethod
    def strict_attempt(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("failed_attempt must be the exact integer one")
        return value

    @model_validator(mode="after")
    def exact_retry_identity(self) -> InferenceTransferPairRetryRequestV1:
        if type(self.failed_attempt) is not int or self.failed_attempt != 1:
            raise ValueError("failed_attempt must be the exact integer one")
        parse_pair_submit_request_v11(self.selection.model_dump(mode="json"))
        if not self.reason.strip():
            raise ValueError("retry reason cannot be whitespace")
        if self.retry_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"retry_sha256"})
        ):
            raise ValueError("retry_sha256 differs from canonical retry command")
        if len(canonical_json_bytes(self.model_dump(mode="json"))) > MAX_TRANSFER_RETRY_BYTES:
            raise ValueError("retry command exceeds its fixed byte budget")
        return self


def parse_pair_retry_request_v1(value: dict[str, Any]) -> InferenceTransferPairRetryRequestV1:
    validate_contract("item-inference-transfer-retry", value)
    return InferenceTransferPairRetryRequestV1.model_validate(value)
