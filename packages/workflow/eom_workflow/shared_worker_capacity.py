"""Shared ordinary-slot successor; physical account identities remain unchanged."""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import Literal, Self

from eom_identifiers import sha256_bytes
from pydantic import Field, model_validator

from eom_workflow.control_plane import RevisionState, WorkerRole
from eom_workflow.models import FrozenModel, Sha256, UtcDatetime

ORDINARY_SLOT_IDS = ("01", "02", "03", "04", "05")
ORDINARY_SLOT_KEYS = tuple("slot" + value for value in ORDINARY_SLOT_IDS)
PHYSICAL_ROLES = MappingProxyType(
    {
        "slot01": "authoring",
        "slot02": "review",
        "slot03": "image",
        "slot04": "item_management",
        "slot05": "support",
    }
)


class SharedWorkerPool(FrozenModel):
    pool_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    roles: tuple[WorkerRole, ...] = Field(min_length=1, max_length=5)
    slot_keys: tuple[Literal["slot01", "slot02", "slot03", "slot04", "slot05"], ...] = Field(
        min_length=5, max_length=5
    )
    max_active: int = Field(strict=True, ge=1, le=4)

    @model_validator(mode="after")
    def shared_membership(self) -> Self:
        if self.slot_keys != ORDINARY_SLOT_KEYS or len(set(self.roles)) != len(self.roles):
            raise ValueError("shared pool requires the five ordinary slots and unique roles")
        return self


class SharedWorkerCapacityPolicy(FrozenModel):
    schema_version: Literal["worker-capacity-policy/1.7"] = "worker-capacity-policy/1.7"
    purpose: Literal["SHARED_ORDINARY_SLOTS"] = "SHARED_ORDINARY_SLOTS"
    capacity_policy_id: str = Field(pattern=r"^capacity_[0-9a-f]{32}$")
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    revision_number: int = Field(strict=True, ge=1)
    state: RevisionState
    max_configured_slots: Literal[6] = 6
    max_active_codex: Literal[4] = 4
    max_active_per_slot: Literal[1] = 1
    max_active_gpu: Literal[1] = 1
    max_active_knowledge_analysis: Literal[4] = 4
    pools: tuple[SharedWorkerPool, ...] = Field(min_length=1, max_length=16)
    content_sha256: Sha256
    created_at: UtcDatetime

    @model_validator(mode="after")
    def unique_pools(self) -> Self:
        if len({pool.pool_key for pool in self.pools}) != len(self.pools):
            raise ValueError("capacity pool keys must be unique")
        return self

    def execution_roles_for_slot(
        self, *, pool_key: str, slot_key: str, native_role: str
    ) -> tuple[str, ...]:
        if PHYSICAL_ROLES.get(slot_key) != native_role:
            raise ValueError("physical slot identity differs")
        for pool in self.pools:
            if pool.pool_key == pool_key and slot_key in pool.slot_keys:
                return tuple(str(role) for role in pool.roles)
        raise ValueError("slot is absent from the shared pool")


def ordinary_slot_probe_order(job_id: str) -> tuple[str, ...]:
    """Stable open-addressing-style probe with no cursor table or randomized hash."""
    if re.fullmatch(r"job_[0-9a-f]{32}", job_id) is None:
        raise ValueError("a canonical job identity is required")
    start = int(sha256_bytes(job_id.encode("ascii"))[-8:], 16) % len(ORDINARY_SLOT_IDS)
    return ORDINARY_SLOT_IDS[start:] + ORDINARY_SLOT_IDS[:start]
