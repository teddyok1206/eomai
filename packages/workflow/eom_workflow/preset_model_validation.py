"""Pinned request for non-generating administrator model-policy acceptance."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator

from eom_workflow.control_plane import FrozenModel, Sha256, UtcDatetime


class PresetModelValidationRequest(FrozenModel):
    schema_version: Literal["preset-model-validation-request/1.0"] = (
        "preset-model-validation-request/1.0"
    )
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    preset_content_sha256: Sha256
    preset_policy_sha256: Sha256
    base_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    base_content_sha256: Sha256
    requested_by: str = Field(min_length=1, max_length=128)
    requested_at: UtcDatetime


class PresetModelAcceptanceCases(FrozenModel):
    """Small immutable provenance value, committed beside the evaluation report."""

    schema_version: Literal["preset-model-acceptance-cases/1.0"] = (
        "preset-model-acceptance-cases/1.0"
    )
    validation_id: str = Field(pattern=r"^job_[0-9a-f]{32}$")
    request_sha256: Sha256
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    preset_content_sha256: Sha256
    preset_policy_sha256: Sha256
    base_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    base_content_sha256: Sha256
    evaluator_source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    case_keys: tuple[str, ...] = Field(min_length=1, max_length=2048)
    completed_at: UtcDatetime
    cases_sha256: Sha256

    @field_validator("case_keys")
    @classmethod
    def unique_case_keys(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("acceptance cases must be unique")
        if any(len(key) > 128 or re.fullmatch(r"[A-Za-z0-9_:-]+", key) is None for key in value):
            raise ValueError("acceptance case key is invalid")
        return value
