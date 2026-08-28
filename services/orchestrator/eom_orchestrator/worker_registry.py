"""Validated worker slot configuration and deterministic role selection."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Literal

import yaml
from eom_protocol import ErrorCode
from eom_workflow import validate_control_contract
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from eom_orchestrator.errors import PlatformError

FIXED_WORKER_SLOT_IDS = ("01", "02", "03", "04", "05", "06")


class SlotLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    global_codex_concurrency: int = Field(ge=1)
    gpu_concurrency: int = Field(ge=1)


class WorkerSlot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    slot_id: Literal["01", "02", "03", "04", "05", "06"]
    linux_user: Literal[
        "eom-cdx-01",
        "eom-cdx-02",
        "eom-cdx-03",
        "eom-cdx-04",
        "eom-cdx-05",
        "eom-cdx-06",
    ]
    role: Literal["authoring", "review", "image", "item_management", "support"]
    enabled: bool
    gpu: bool = False

    @model_validator(mode="after")
    def slot_matches_linux_user(self) -> WorkerSlot:
        if not self.linux_user.endswith(self.slot_id):
            raise ValueError("slot_id must match linux_user suffix")
        return self


class WorkerSlotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1, 2]
    limits: SlotLimits
    slots: tuple[WorkerSlot, ...]

    @model_validator(mode="after")
    def slot_ids_are_unique(self) -> WorkerSlotConfig:
        ids = [slot.slot_id for slot in self.slots]
        users = [slot.linux_user for slot in self.slots]
        if not ids:
            raise ValueError("at least one worker slot is required")
        if len(ids) != len(set(ids)) or len(users) != len(set(users)):
            raise ValueError("worker slot ids and linux users must be unique")
        if self.limits.gpu_concurrency > self.limits.global_codex_concurrency:
            raise ValueError("GPU concurrency cannot exceed global Codex concurrency")
        if self.version == 1 and any(slot.slot_id == "06" for slot in self.slots):
            raise ValueError("worker inventory V1 cannot contain slot 06")
        if self.version == 2:
            expected = {
                "01": ("eom-cdx-01", "authoring", False),
                "02": ("eom-cdx-02", "review", False),
                "03": ("eom-cdx-03", "image", True),
                "04": ("eom-cdx-04", "item_management", False),
                "05": ("eom-cdx-05", "support", False),
                "06": ("eom-cdx-06", "support", False),
            }
            actual = {slot.slot_id: (slot.linux_user, slot.role, slot.gpu) for slot in self.slots}
            if (
                actual != expected
                or self.limits.global_codex_concurrency != 3
                or self.limits.gpu_concurrency != 1
            ):
                raise ValueError("worker inventory V2 differs from the reviewed fixed-host layout")
        return self


class WorkerRegistry:
    def __init__(self, config: WorkerSlotConfig) -> None:
        self.config = config

    @classmethod
    def load(cls, path: Path) -> WorkerRegistry:
        try:
            if not path.is_absolute():
                raise OSError("worker configuration path is not absolute")
            metadata = path.lstat()
            if (
                path.is_symlink()
                or not stat.S_ISREG(metadata.st_mode)
                or path.resolve(strict=True) != path.absolute()
                or not os.access(path, os.R_OK)
            ):
                raise OSError("worker configuration file is unsafe")
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, encoding="utf-8") as source:
                content = source.read(1_048_577)
            if len(content) > 1_048_576:
                raise OSError("worker configuration file is too large")
            raw: object = yaml.safe_load(content)
            if isinstance(raw, dict) and raw.get("version") == 2:
                validate_control_contract("worker-slot-inventory-v2", raw)
            config = WorkerSlotConfig.model_validate(raw)
        except (
            OSError,
            UnicodeError,
            yaml.YAMLError,
            JsonSchemaValidationError,
            ValidationError,
        ) as exc:
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
