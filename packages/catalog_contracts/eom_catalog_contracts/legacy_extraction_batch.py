"""Pointer-oriented contracts for resumable legacy extraction batches."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.legacy_assessment import (
    LegacyExtractionResultPointer,
    LegacyItemExtractionRequest,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime


class LegacyExtractionAcceptancePointer(FrozenModel):
    """Exact accepted result that a continuation may reuse."""

    acceptance_id: str = Field(pattern=r"^itemacceptance_[0-9a-f]{32}$")
    acceptance_sha256: Sha256
    extraction_result: LegacyExtractionResultPointer


class LegacyExtractionBatchWorkUnit(FrozenModel):
    """One deterministic request in a batch manifest."""

    work_unit_id: str = Field(pattern=r"^legacyworkunit_[0-9a-f]{32}$")
    ordinal: int = Field(ge=0, le=999999)
    request: LegacyItemExtractionRequest
    expected_item_numbers_sha256: Sha256
    execution_mode: Literal["EXECUTE", "REUSE_ACCEPTED"] = "EXECUTE"
    reuse_accepted: LegacyExtractionAcceptancePointer | None = None

    @model_validator(mode="after")
    def coherent_work_unit(self) -> LegacyExtractionBatchWorkUnit:
        expected = tuple(self.request.expected_item_numbers)
        if self.request.work_unit_ordinal != self.ordinal:
            raise ValueError("work-unit ordinal must match its extraction request")
        if self.expected_item_numbers_sha256 != content_sha256({"item_numbers": list(expected)}):
            raise ValueError("work-unit expected item-number hash is invalid")
        if self.execution_mode == "EXECUTE" and self.reuse_accepted is not None:
            raise ValueError("execute work unit cannot carry a reuse pointer")
        if self.execution_mode == "REUSE_ACCEPTED" and self.reuse_accepted is None:
            raise ValueError("reuse work unit requires an accepted pointer")
        return self


class LegacyItemExtractionBatchManifest(FrozenModel):
    """Immutable, ordered manifest for continue-and-collect execution."""

    schema_version: Literal["legacy-item-extraction-batch/1.0"]
    extraction_batch_id: str = Field(pattern=r"^legacybatch_[0-9a-f]{32}$")
    idempotency_key: str = Field(min_length=1, max_length=128)
    inventory_id: str = Field(pattern=r"^legacyinventory_[0-9a-f]{32}$")
    inventory_sha256: Sha256
    failure_policy: Literal["CONTINUE_AND_COLLECT"] = "CONTINUE_AND_COLLECT"
    work_units: tuple[LegacyExtractionBatchWorkUnit, ...] = Field(min_length=1, max_length=10000)
    created_at: UtcDatetime
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def deterministic_manifest(self) -> LegacyItemExtractionBatchManifest:
        ordinals = tuple(unit.ordinal for unit in self.work_units)
        ids = tuple(unit.work_unit_id for unit in self.work_units)
        identities = tuple(
            (
                unit.request.bundle.assessment_source_bundle_revision_id,
                unit.ordinal,
                unit.expected_item_numbers_sha256,
            )
            for unit in self.work_units
        )
        if ordinals != tuple(range(len(ordinals))):
            raise ValueError("batch work units must use contiguous ordered ordinals")
        if len(ids) != len(set(ids)) or len(identities) != len(set(identities)):
            raise ValueError("batch work-unit identities must be unique")
        payload = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if self.manifest_sha256 != content_sha256(payload):
            raise ValueError("batch manifest hash does not match canonical content")
        return self


__all__ = [
    "LegacyExtractionAcceptancePointer",
    "LegacyExtractionBatchWorkUnit",
    "LegacyItemExtractionBatchManifest",
]
