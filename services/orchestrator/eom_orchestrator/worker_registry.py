"""Validated worker slot configuration and deterministic role selection."""

from __future__ import annotations

from pathlib import Path

import yaml
from eom_protocol import ErrorCode
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from eom_orchestrator.errors import PlatformError


class SlotLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    global_codex_concurrency: int = Field(ge=1)
    gpu_concurrency: int = Field(ge=1)


class WorkerSlot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    slot_id: str = Field(pattern=r"^[0-9]{2}$")
    linux_user: str = Field(pattern=r"^eom-cdx-[0-9]{2}$")
    role: str = Field(min_length=1, max_length=64)
    enabled: bool
    gpu: bool = False

    @model_validator(mode="after")
    def slot_matches_linux_user(self) -> WorkerSlot:
        if not self.linux_user.endswith(self.slot_id):
            raise ValueError("slot_id must match linux_user suffix")
        return self


class WorkerSlotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1)
    limits: SlotLimits
    slots: tuple[WorkerSlot, ...]

    @model_validator(mode="after")
    def slot_ids_are_unique(self) -> WorkerSlotConfig:
        ids = [slot.slot_id for slot in self.slots]
        users = [slot.linux_user for slot in self.slots]
        if len(ids) != len(set(ids)) or len(users) != len(set(users)):
            raise ValueError("worker slot ids and linux users must be unique")
        return self


class WorkerRegistry:
    def __init__(self, config: WorkerSlotConfig) -> None:
        self.config = config

    @classmethod
    def load(cls, path: Path) -> WorkerRegistry:
        try:
            raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
            config = WorkerSlotConfig.model_validate(raw)
        except (OSError, yaml.YAMLError, ValidationError) as exc:
            raise PlatformError(ErrorCode.WORKER_UNAVAILABLE, "invalid worker slot config") from exc
        return cls(config)

    @property
    def global_codex_concurrency(self) -> int:
        return self.config.limits.global_codex_concurrency

    def select(self, role: str) -> WorkerSlot:
        candidates = sorted(
            (slot for slot in self.config.slots if slot.role == role and slot.enabled),
            key=lambda slot: slot.slot_id,
        )
        if not candidates:
            raise PlatformError(ErrorCode.WORKER_UNAVAILABLE, f"no enabled worker for role {role}")
        return candidates[0]
