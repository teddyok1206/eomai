"""Bounded administrator model selection and asynchronous acceptance views."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel, Sha256, UtcDatetime
from eom_api_contracts.control_plane import ModelCandidateInput


class PresetModelEvaluationRequest(ApiModel):
    base_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")


class PresetRoleModelOptions(ApiModel):
    role: Literal["authoring", "image", "review", "item_management", "support"]
    worker_pool_key: str
    candidates: tuple[ModelCandidateInput, ...] = Field(max_length=320)


class PresetModelOptionsView(ApiModel):
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    roles: tuple[PresetRoleModelOptions, ...] = Field(min_length=1, max_length=5)
    catalog_is_entitlement: Literal[False] = False


class PresetModelValidationView(ApiModel):
    model_config = ApiModel.model_config | {
        "json_schema_extra": {
            "allOf": [
                {
                    "if": {"properties": {"status": {"enum": ["SUCCEEDED", "FAILED"]}}},
                    "then": {
                        "properties": {"completed_at": {"type": "string"}},
                        "required": ["completed_at"],
                    },
                    "else": {
                        "properties": {
                            "completed_at": {"type": "null"},
                            "cases_total": {"const": 0},
                            "cases_passed": {"const": 0},
                        }
                    },
                },
                {
                    "if": {"properties": {"status": {"const": "SUCCEEDED"}}},
                    "then": {
                        "properties": {
                            "evaluation_id": {"type": "string"},
                            "error_code": {"type": "null"},
                            "cases_total": {"minimum": 1},
                            "cases_passed": {"minimum": 1},
                        },
                        "required": ["evaluation_id", "cases_total", "cases_passed"],
                    },
                    "else": {"properties": {"evaluation_id": {"type": "null"}}},
                },
                {
                    "if": {"properties": {"status": {"const": "FAILED"}}},
                    "then": {
                        "properties": {"error_code": {"type": "string"}},
                        "required": ["error_code"],
                    },
                    "else": {"properties": {"error_code": {"type": "null"}}},
                },
            ]
        }
    }

    validation_id: str = Field(pattern=r"^job_[0-9a-f]{32}$")
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    base_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    preset_policy_sha256: Sha256
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED"]
    scope: Literal["NON_LIVE"] = "NON_LIVE"
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,95}$")
    evaluation_id: str | None = Field(default=None, pattern=r"^preseteval_[0-9a-f]{32}$")
    quality_evaluated: Literal[False] = False
    cases_total: int = Field(default=0, ge=0, le=10000)
    cases_passed: int = Field(default=0, ge=0, le=10000)
    completed_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def honest_terminal_result(self) -> PresetModelValidationView:
        if self.cases_passed > self.cases_total:
            raise ValueError("passed cases exceed executed cases")
        terminal = self.status in {"SUCCEEDED", "FAILED"}
        if terminal != (self.completed_at is not None):
            raise ValueError("terminal validation requires completion time")
        if not terminal and (self.cases_total != 0 or self.cases_passed != 0):
            raise ValueError("unfinished validation cannot claim completed cases")
        if self.status == "SUCCEEDED" and (
            self.error_code is not None
            or self.evaluation_id is None
            or self.cases_total == 0
            or self.cases_passed != self.cases_total
        ):
            raise ValueError("successful validation requires exact passing evaluation")
        if self.status != "SUCCEEDED" and self.evaluation_id is not None:
            raise ValueError("unfinished or failed validation cannot claim accepted evidence")
        if (self.status == "FAILED") != (self.error_code is not None):
            raise ValueError("only failed validation has an error code")
        return self
