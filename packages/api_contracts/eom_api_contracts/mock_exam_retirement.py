"""Typed contracts for retiring one exact mock-exam production occurrence."""

from __future__ import annotations

from typing import Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel, Sha256, UtcDatetime

WorkflowRetirementSourceState = Literal[
    "REQUESTED",
    "RUNNING",
    "AWAITING_HUMAN_APPROVAL",
    "REWORK_REQUESTED",
    "APPROVED",
    "REGISTERING",
    "FAILED",
    "CANCELLED",
]


class MockExamProductionRetirementBindingV1(ApiModel):
    """CAS binding for one Workflow belonging to the exact 25-call occurrence."""

    position: int = Field(ge=1, le=25)
    workflow_call_id: str = Field(pattern=r"^workflowcall_[0-9a-f]{32}$")
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    start_command_id: str = Field(min_length=1, max_length=128)
    expected_workflow_resource_version: int = Field(ge=1)
    observed_workflow_state: WorkflowRetirementSourceState


class MockExamProductionRetirementCommandV1(ApiModel):
    """Self-hashed, exact-cohort command prepared before the retirement transaction."""

    schema_version: Literal["mock-exam-production-retirement-command/1.0"]
    retirement_id: str = Field(pattern=r"^productionretire_[0-9a-f]{32}$")
    execution_id: str = Field(pattern=r"^productionexec_[0-9a-f]{32}$")
    execution_revision_id: str = Field(pattern=r"^productionexecrev_[0-9a-f]{32}$")
    checkpoint_sha256: Sha256
    production_request_id: str = Field(pattern=r"^productionreq_[0-9a-f]{32}$")
    production_plan_id: str = Field(pattern=r"^productionplan_[0-9a-f]{32}$")
    production_plan_sha256: Sha256
    operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    reason_code: Literal["SUPERSEDED_BY_CORRECTED_PROTOCOL"]
    authorized_at: UtcDatetime
    bindings: tuple[MockExamProductionRetirementBindingV1, ...] = Field(
        min_length=25,
        max_length=25,
    )
    command_sha256: Sha256

    @model_validator(mode="after")
    def exact_ordered_cohort_and_hash(self) -> Self:
        positions = tuple(binding.position for binding in self.bindings)
        if positions != tuple(range(1, 26)):
            raise ValueError("retirement bindings must preserve positions 1 through 25")
        if len({binding.workflow_call_id for binding in self.bindings}) != 25:
            raise ValueError("retirement workflow-call bindings must be unique")
        if len({binding.workflow_id for binding in self.bindings}) != 25:
            raise ValueError("retirement Workflow bindings must be unique")
        if len({binding.start_command_id for binding in self.bindings}) != 25:
            raise ValueError("retirement start-command bindings must be unique")
        if self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("retirement command SHA-256 does not match")
        return self


class MockExamProductionRetirementOutcomeV1(ApiModel):
    """Durable audit/event evidence for one member of the retired cohort."""

    position: int = Field(ge=1, le=25)
    workflow_call_id: str = Field(pattern=r"^workflowcall_[0-9a-f]{32}$")
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    expected_workflow_resource_version: int = Field(ge=1)
    retirement_workflow_resource_version: int = Field(ge=2)
    retirement_event_sequence: int = Field(ge=2)
    prior_workflow_state: WorkflowRetirementSourceState
    disposition: Literal["CANCEL_QUEUED", "UNSUCCESSFUL_TERMINAL_PRESERVED"]
    cancel_command_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def command_matches_disposition(self) -> Self:
        if (self.disposition == "CANCEL_QUEUED") != (self.cancel_command_id is not None):
            raise ValueError("only queued cancellation outcomes carry a command pointer")
        if self.disposition == "UNSUCCESSFUL_TERMINAL_PRESERVED" and (
            self.prior_workflow_state not in {"FAILED", "CANCELLED"}
        ):
            raise ValueError("only unsuccessful terminal Workflows may be preserved")
        if self.retirement_workflow_resource_version != (
            self.expected_workflow_resource_version + 1
        ):
            raise ValueError("retirement audit must advance the Workflow resource version once")
        return self


class MockExamProductionRetirementReceiptV1(ApiModel):
    """Pointer-only proof that all old commands were atomically fenced before restart."""

    schema_version: Literal["mock-exam-production-retirement-receipt/1.0"]
    retirement_id: str = Field(pattern=r"^productionretire_[0-9a-f]{32}$")
    command_sha256: Sha256
    execution_id: str = Field(pattern=r"^productionexec_[0-9a-f]{32}$")
    execution_revision_id: str = Field(pattern=r"^productionexecrev_[0-9a-f]{32}$")
    checkpoint_sha256: Sha256
    production_request_id: str = Field(pattern=r"^productionreq_[0-9a-f]{32}$")
    production_plan_id: str = Field(pattern=r"^productionplan_[0-9a-f]{32}$")
    production_plan_sha256: Sha256
    operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    reason_code: Literal["SUPERSEDED_BY_CORRECTED_PROTOCOL"]
    retired_at: UtcDatetime
    outcomes: tuple[MockExamProductionRetirementOutcomeV1, ...] = Field(
        min_length=25,
        max_length=25,
    )
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def exact_ordered_cohort_and_hash(self) -> Self:
        positions = tuple(outcome.position for outcome in self.outcomes)
        if positions != tuple(range(1, 26)):
            raise ValueError("retirement outcomes must preserve positions 1 through 25")
        if len({outcome.workflow_call_id for outcome in self.outcomes}) != 25:
            raise ValueError("retirement outcome workflow calls must be unique")
        if len({outcome.workflow_id for outcome in self.outcomes}) != 25:
            raise ValueError("retirement outcome Workflows must be unique")
        if self.receipt_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"receipt_sha256"})
        ):
            raise ValueError("retirement receipt SHA-256 does not match")
        return self
