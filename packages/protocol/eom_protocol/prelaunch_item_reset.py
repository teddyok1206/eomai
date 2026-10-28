"Bounded local-owner maintenance value contracts; never a worker permission grant."

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Annotated, Literal, Self

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ConfigDict, Field, model_validator

KEEP_ITEM_ID = "item_f913cf57d96a4fd287381b09eaf7f32e"
KEEP_REVISION_ID = "itemrev_2f962f0bb4db4718b6e7af7d6fc8982f"
TARGET_SHA256 = "fd53d8cae3e79069d3af824fbbbae91932eb3202724ae988a3d418492f5c3b6c"
BASE_GRAPH = "graphrev_7870b0fb03b7dfb64179e53182bf3999"
MIXED_GRAPHS = (
    "graphrev_c0e78b4e4ce6588de3d3b6c6f25fb3d9",
    "graphrev_8f3ff9b22d592ecf661fec7116a5cab9",
)
ASSEMBLY_REVISION = "assemblyrev_f42d6a195e07f21221d24baea250f0c4"
ASSEMBLY_ID = "assembly_f0aa37b8aa950bc601982919a415fafc"
FORM_ID = "form_46ecf96c87fc9531c03a026598723591"
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def reset_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


class ResetValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResetBackupPin(ResetValue):
    file_name: str = Field(pattern=r"^eom_[0-9]{8}T[0-9]{6}Z_[0-9a-f]{12}\.dump$")
    sha256: Hash
    size_bytes: int = Field(gt=0)


class ResetGraphPin(ResetValue):
    revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class CatalogResetObservation:
    item_ids: tuple[str, ...]
    item_revision_ids: tuple[str, ...]
    graph_pins: tuple[ResetGraphPin, ...]
    baseline_sha256: str
    protected_sha256: str


@dataclass(frozen=True, slots=True)
class WorkflowResetObservation:
    workflow_ids: tuple[str, ...]
    baseline_sha256: str


@dataclass(frozen=True, slots=True)
class ArtifactResetObservation:
    job_ids: tuple[str, ...]
    baseline_sha256: str
    protected_sha256: str


@dataclass(frozen=True, slots=True)
class BuildResetObservation:
    baseline_sha256: str
    protected_sha256: str


class PrelaunchItemResetPlan(ResetValue):
    schema_version: Literal["prelaunch-item-reset-plan/1.0"] = "prelaunch-item-reset-plan/1.0"
    scope: Literal["AI_PRELAUNCH_20261028"] = "AI_PRELAUNCH_20261028"
    database: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
    item_ids: tuple[str, ...] = Field(min_length=110, max_length=110)
    item_revision_ids: tuple[str, ...] = Field(min_length=111, max_length=111)
    workflow_ids: tuple[str, ...] = Field(min_length=170, max_length=2500)
    job_ids: tuple[str, ...] = Field(min_length=1, max_length=10000)
    graph_pins: tuple[ResetGraphPin, ...] = Field(min_length=3, max_length=3)
    protected_sha256: Hash
    baseline_sha256: Hash
    backup: ResetBackupPin
    created_at_utc: str
    plan_sha256: Hash

    @model_validator(mode="after")
    def exact_scope(self) -> Self:
        value = self.model_dump(mode="json")
        raw = files("eom_protocol").joinpath("schemas/prelaunch-item-reset-plan-v1.schema.json")
        Draft202012Validator(json.loads(raw.read_text()), format_checker=FormatChecker()).validate(
            value
        )
        for selected in (self.item_ids, self.item_revision_ids, self.workflow_ids, self.job_ids):
            if tuple(sorted(set(selected))) != selected:
                raise ValueError("reset IDs must be sorted and unique")
        if KEEP_ITEM_ID in self.item_ids or KEEP_REVISION_ID in self.item_revision_ids:
            raise ValueError("reset may not include the kept sample")
        if reset_digest(self.item_ids) != TARGET_SHA256:
            raise ValueError("reset target set differs from the exact user approval")
        if tuple(p.revision_id for p in self.graph_pins) != tuple(
            sorted((BASE_GRAPH, *MIXED_GRAPHS))
        ):
            raise ValueError("reset Graph pins differ from the exact approval")
        value.pop("plan_sha256")
        if reset_digest(value) != self.plan_sha256:
            raise ValueError("reset plan hash mismatch")
        return self


class PrelaunchItemResetReceipt(ResetValue):
    schema_version: Literal["prelaunch-item-reset-receipt/1.0"]
    plan_sha256: Hash
    database: str
    deleted_items: Literal[110]
    deleted_item_revisions: Literal[111]
    deleted_workflows: int
    candidate_jobs: int
    shared_jobs_preserved: int
    exclusive_jobs_deleted: int
    protected_sha256: Hash
    nas_action: Literal["PRESERVED"]
    outcome: Literal["COMPLETED"]

    @model_validator(mode="after")
    def exact_counts(self) -> Self:
        resource = files("eom_protocol").joinpath(
            "schemas/prelaunch-item-reset-receipt-v1.schema.json"
        )
        Draft202012Validator(json.loads(resource.read_text())).validate(
            self.model_dump(mode="json")
        )
        if self.candidate_jobs != self.shared_jobs_preserved + self.exclusive_jobs_deleted:
            raise ValueError("reset receipt Job counts do not balance")
        return self
