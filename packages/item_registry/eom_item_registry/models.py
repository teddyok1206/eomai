"""Typed value contracts for deterministic registry operations."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RegistryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ComponentPointer(RegistryModel):
    component_type: Literal[
        "UPPER_STEM",
        "LOWER_STEM",
        "DATA",
        "TABLE",
        "IMAGE",
        "IMAGE_SPEC",
        "STATEMENTS",
        "CHOICES",
        "POINTS",
        "ANSWER",
        "AUTHORING_INTENT",
        "SOLUTION_OVERVIEW",
        "STATEMENT_EXPLANATIONS",
        "REVIEW_REPORT",
        "SOURCE_REFERENCE",
        "METADATA",
        "OTHER",
    ]
    ordinal: int = Field(ge=0, le=1000)
    schema_ref: str = Field(min_length=1, max_length=256)
    media_type: str = Field(pattern=r"^[a-z0-9.+-]+/[A-Za-z0-9.+-]+$")
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    logical_name: str = Field(min_length=1, max_length=128)
    required: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class RegistrationRequest(RegistryModel):
    mode: Literal["CREATE_ITEM", "REVISE_ITEM"]
    registration_key: str = Field(min_length=1, max_length=200)
    item_id: str | None = Field(default=None, pattern=r"^item_[0-9a-f]{32}$")
    base_revision_id: str | None = Field(default=None, pattern=r"^itemrev_[0-9a-f]{32}$")
    content_pack_release_id: str = Field(pattern=r"^packrel_[0-9a-f]{32}$")
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    workflow_definition_key: str = Field(min_length=1, max_length=128)
    workflow_definition_version: str = Field(min_length=1, max_length=32)
    source_workflow_step_run_id: str = Field(pattern=r"^steprun_[0-9a-f]{32}$")
    source_intake_batch_ids: tuple[Annotated[str, Field(pattern=r"^intake_[0-9a-f]{32}$")], ...]
    item_type_key: str = Field(min_length=1, max_length=128)
    primary_taxonomy_ref: str | None = Field(default=None, max_length=256)
    difficulty_band: str | None = Field(default=None, max_length=64)
    tag_keys: tuple[str, ...] = ()
    estimated_time_seconds: int | None = Field(default=None, ge=1, le=86400)
    metadata_schema_ref: str = Field(min_length=1, max_length=256)
    metadata: dict[str, Any]
    components: tuple[ComponentPointer, ...] = Field(min_length=1, max_length=100)
    created_by: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
