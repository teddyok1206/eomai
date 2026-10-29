"""Explicit failed-result successor link, never permission to rewrite a failed Job."""

from typing import Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract


class CreativeResultRecovery(FrozenModel):
    schema_version: Literal["creative-result-recovery/1.0"] = "creative-result-recovery/1.0"
    predecessor_workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    predecessor_step_run_id: str = Field(pattern=r"^steprun_[0-9a-f]{32}$")
    predecessor_job_id: str = Field(pattern=r"^job_[0-9a-f]{32}$")
    successor_workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    definition_sha256: Sha256
    work_input_sha256: Sha256
    reason: Literal["INVALID_RESULT_BEFORE_COMMIT"] = "INVALID_RESULT_BEFORE_COMMIT"
    record_sha256: Sha256

    @model_validator(mode="after")
    def exact_link(self) -> Self:
        validate_contract("creative-result-recovery-v1", self.model_dump(mode="json"))
        if self.predecessor_workflow_id == self.successor_workflow_id or self.record_sha256 != (
            content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        ):
            raise ValueError("CREATIVE_RESULT_RECOVERY_LINK_INVALID")
        return self
