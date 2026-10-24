"""Immutable reviewed capability policy values; no IO or admission side effects."""

from __future__ import annotations

from typing import Literal

from eom_workflow.codex_compatibility import CodexCompatibilityRuntime
from eom_workflow.control_plane import ReasoningEffort
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eom_orchestrator.worker_registry import FIXED_WORKER_SLOT_ROLES

COMPATIBILITY_SLOT_ROLES = FIXED_WORKER_SLOT_ROLES


class ReviewedCapabilityBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    binding_id: str = Field(pattern=r"^authbinding_[0-9a-f]{32}$")
    assignment_revision_id: str | None = Field(pattern=r"^authassignrev_[0-9a-f]{32}$")


class ReviewedCapabilityBindingV3(ReviewedCapabilityBinding):
    slot_id: Literal["01", "02", "03", "04", "05", "06"]
    role: Literal["authoring", "review", "image", "item_management", "support"]

    @model_validator(mode="after")
    def fixed_slot_role(self) -> ReviewedCapabilityBindingV3:
        if self.role != COMPATIBILITY_SLOT_ROLES[self.slot_id]:
            raise ValueError("V3 capability binding role must match its fixed slot")
        return self


class ReviewedModelCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)

    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    reasoning_efforts: tuple[ReasoningEffort, ...] = Field(min_length=1, max_length=5)
    bindings: tuple[ReviewedCapabilityBinding | ReviewedCapabilityBindingV3, ...] | None = Field(
        default=None, min_length=1, max_length=6
    )

    @model_validator(mode="after")
    def unique_efforts(self) -> ReviewedModelCapability:
        if len(self.reasoning_efforts) != len(set(self.reasoning_efforts)):
            raise ValueError("reviewed reasoning efforts must be unique")
        if self.bindings is not None and (
            len({item.binding_id for item in self.bindings}) != len(self.bindings)
            or self.bindings != tuple(sorted(self.bindings, key=lambda item: item.binding_id))
        ):
            raise ValueError("reviewed binding scopes must be unique and sorted")
        if self.bindings is not None:
            slots = [
                pin.slot_id for pin in self.bindings if isinstance(pin, ReviewedCapabilityBindingV3)
            ]
            if len(slots) != len(set(slots)):
                raise ValueError("V3 capability scope must have unique slots")
        return self


class ReviewedCapabilityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1, 2, 3]
    expected_codex_cli_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    models: tuple[ReviewedModelCapability, ...] = Field(min_length=1, max_length=32)
    compatibility_runtime: CodexCompatibilityRuntime | None = None

    @field_validator("version", mode="before")
    @classmethod
    def integer_policy_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("reviewed policy version must be an integer")
        return value

    @model_validator(mode="after")
    def unique_models(self) -> ReviewedCapabilityPolicy:
        if self.version == 1:
            names = [item.model for item in self.models]
            if (
                len(self.models) > 16
                or len(names) != len(set(names))
                or self.compatibility_runtime is not None
                or any(item.bindings is not None for item in self.models)
            ):
                raise ValueError("V1 reviewed models must be unique, global and runtime-unscoped")
        elif (
            self.compatibility_runtime is None
            or self.compatibility_runtime.cli_version != self.expected_codex_cli_version
            or len({(item.model, item.bindings) for item in self.models}) != len(self.models)
        ):
            raise ValueError(
                "scoped reviewed policy requires exact runtime and unique model scopes"
            )
        if self.version in {2, 3} and any(
            isinstance(pin, ReviewedCapabilityBindingV3) != (self.version == 3)
            for item in self.models
            for pin in item.bindings or ()
        ):
            raise ValueError("reviewed binding shape must match its policy version")
        return self
