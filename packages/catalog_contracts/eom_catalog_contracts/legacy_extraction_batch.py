"""Pointer-oriented contracts for resumable legacy extraction batches."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.legacy_assessment import (
    AssessmentArtifactMemberPointer,
    AssessmentInventoryEntryPointer,
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


class LegacyCorpusSourceBinding(FrozenModel):
    """Exact byte-equivalence edge from a reviewed member to the corpus inventory."""

    bundle_member_id: str = Field(pattern=r"^assessbundlemember_[0-9a-f]{32}$")
    reviewed_inventory_source: AssessmentInventoryEntryPointer
    corpus_inventory_source: AssessmentInventoryEntryPointer

    @model_validator(mode="after")
    def exact_content_identity(self) -> LegacyCorpusSourceBinding:
        if (
            self.reviewed_inventory_source.content_sha256
            != self.corpus_inventory_source.content_sha256
        ):
            raise ValueError("corpus source binding content hashes differ")
        return self


class LegacyExtractionBatchWorkUnitV2(LegacyExtractionBatchWorkUnit):
    """One reviewed work unit with full-corpus source membership evidence."""

    corpus_source_bindings: tuple[LegacyCorpusSourceBinding, ...] = Field(
        min_length=1, max_length=32
    )

    @model_validator(mode="after")
    def unique_source_bindings(self) -> LegacyExtractionBatchWorkUnitV2:
        member_ids = tuple(binding.bundle_member_id for binding in self.corpus_source_bindings)
        reviewed_entries = tuple(
            binding.reviewed_inventory_source.entry_key for binding in self.corpus_source_bindings
        )
        corpus_entries = tuple(
            binding.corpus_inventory_source.entry_key for binding in self.corpus_source_bindings
        )
        if (
            len(member_ids) != len(set(member_ids))
            or len(reviewed_entries) != len(set(reviewed_entries))
            or len(corpus_entries) != len(set(corpus_entries))
        ):
            raise ValueError("corpus source binding identities must be unique")
        return self


class LegacyItemExtractionBatchManifestV2(FrozenModel):
    """Immutable batch whose work is proven to belong to one corpus inventory."""

    schema_version: Literal["legacy-item-extraction-batch/1.1"]
    extraction_batch_id: str = Field(pattern=r"^legacybatch_[0-9a-f]{32}$")
    idempotency_key: str = Field(min_length=1, max_length=128)
    inventory_id: str = Field(pattern=r"^legacyinventory_[0-9a-f]{32}$")
    inventory_sha256: Sha256
    inventory_artifact: AssessmentArtifactMemberPointer
    failure_policy: Literal["CONTINUE_AND_COLLECT"] = "CONTINUE_AND_COLLECT"
    work_units: tuple[LegacyExtractionBatchWorkUnitV2, ...] = Field(min_length=1, max_length=10000)
    created_at: UtcDatetime
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def deterministic_manifest(self) -> LegacyItemExtractionBatchManifestV2:
        if (
            self.inventory_artifact.schema_ref
            != "eom://schemas/legacy-knowledge/legacy-source-inventory/2.0"
            or self.inventory_artifact.media_type != "application/json"
        ):
            raise ValueError("batch inventory Artifact contract is invalid")
        ordinals = tuple(unit.ordinal for unit in self.work_units)
        unit_ids = tuple(unit.work_unit_id for unit in self.work_units)
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
        if len(unit_ids) != len(set(unit_ids)) or len(identities) != len(set(identities)):
            raise ValueError("batch work-unit identities must be unique")
        for unit in self.work_units:
            if any(
                (
                    binding.corpus_inventory_source.inventory_id,
                    binding.corpus_inventory_source.inventory_sha256,
                )
                != (self.inventory_id, self.inventory_sha256)
                for binding in unit.corpus_source_bindings
            ):
                raise ValueError("corpus binding does not belong to the batch inventory")
        payload = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if self.manifest_sha256 != content_sha256(payload):
            raise ValueError("batch manifest hash does not match canonical content")
        return self


__all__ = [
    "LegacyCorpusSourceBinding",
    "LegacyExtractionAcceptancePointer",
    "LegacyExtractionBatchWorkUnit",
    "LegacyExtractionBatchWorkUnitV2",
    "LegacyItemExtractionBatchManifest",
    "LegacyItemExtractionBatchManifestV2",
]
