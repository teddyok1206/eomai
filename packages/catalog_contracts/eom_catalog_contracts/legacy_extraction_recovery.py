"""Exact, hash-pinned authorization for extraction validation recovery."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime

type ExtractionValidationDiagnosis = Literal[
    "DUPLICATE_STATEMENT_EXPLANATION_ID",
    "BODY_BLOCK_DISCRIMINATOR_MISMATCH",
    "NONE_VISUAL_RENDERING_CONFLICT",
]


class LegacyExtractionPresetPointer(FrozenModel):
    """Pinned extraction preset and every execution-bound dependency needed for replay."""

    preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    preset_revision_number: int = Field(ge=1)
    preset_sha256: Sha256
    preset_policy_sha256: Sha256
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    capacity_policy_sha256: Sha256
    instruction_bundle_id: str = Field(pattern=r"^instrbundle_[0-9a-f]{32}$")
    instruction_bundle_revision_id: str = Field(pattern=r"^instrrev_[0-9a-f]{32}$")
    instruction_revision_number: int = Field(ge=1)
    instruction_manifest_sha256: Sha256
    instruction_content_sha256: Sha256
    workflow_definition_id: str = Field(pattern=r"^wfdef_[0-9a-f]{32}$")
    workflow_definition_version: Literal["1.0.0"]
    workflow_definition_sha256: Sha256
    role_schema_version: Literal["workflow-role/1.14.0"]
    role_schema_sha256: Sha256


class LegacyExtractionValidationReplacement(FrozenModel):
    """One failed immutable work unit and its fresh continuation identities."""

    predecessor_work_unit_id: str = Field(pattern=r"^legacyworkunit_[0-9a-f]{32}$")
    predecessor_ordinal: int = Field(ge=0, le=999999)
    predecessor_extraction_request_id: str = Field(pattern=r"^itemextractreq_[0-9a-f]{32}$")
    predecessor_request_sha256: Sha256
    predecessor_bundle_revision_id: str = Field(pattern=r"^assessbundlerev_[0-9a-f]{32}$")
    predecessor_workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    predecessor_platform_job_id: str = Field(pattern=r"^job_[0-9a-f]{32}$")
    failure_code: Literal["LEGACY_ITEM_EXTRACTION_WORKFLOW_FAILED"]
    workflow_failure_code: Literal["WORKER_RESULT_INVALID"]
    job_error_code: Literal["WORKER_RESULT_INVALID"]
    failure_message_sha256: Sha256
    diagnosis_code: ExtractionValidationDiagnosis
    expected_item_numbers: tuple[int, ...] = Field(min_length=5, max_length=5)
    expected_item_numbers_sha256: Sha256
    successor_work_unit_id: str = Field(pattern=r"^legacyworkunit_[0-9a-f]{32}$")
    successor_ordinal: int = Field(ge=0, le=2)
    successor_extraction_request_id: str = Field(pattern=r"^itemextractreq_[0-9a-f]{32}$")

    @model_validator(mode="after")
    def exact_five_item_range(self) -> LegacyExtractionValidationReplacement:
        values = self.expected_item_numbers
        if values != tuple(range(values[0], values[0] + 5)):
            raise ValueError("recovery item numbers must be one ordered five-item range")
        if self.expected_item_numbers_sha256 != content_sha256({"item_numbers": list(values)}):
            raise ValueError("recovery item-number hash is invalid")
        if self.predecessor_extraction_request_id == self.successor_extraction_request_id:
            raise ValueError("recovery extraction request identity must be fresh")
        if self.predecessor_work_unit_id == self.successor_work_unit_id:
            raise ValueError("recovery work-unit identity must be fresh")
        return self


class LegacyItemExtractionValidationRecovery(FrozenModel):
    """Reviewed authorization to replace all three diagnosed failed extraction ranges."""

    schema_version: Literal["legacy-item-extraction-validation-recovery/1.0"]
    predecessor_batch_id: str = Field(pattern=r"^legacybatch_[0-9a-f]{32}$")
    predecessor_manifest_sha256: Sha256
    predecessor_preset: LegacyExtractionPresetPointer
    successor_batch_id: str = Field(pattern=r"^legacybatch_[0-9a-f]{32}$")
    successor_idempotency_key: str = Field(min_length=1, max_length=128)
    successor_preset: LegacyExtractionPresetPointer
    replacements: tuple[LegacyExtractionValidationReplacement, ...] = Field(
        min_length=3, max_length=3
    )
    created_at: UtcDatetime
    recovery_sha256: Sha256

    @model_validator(mode="after")
    def exact_closed_recovery(self) -> LegacyItemExtractionValidationRecovery:
        if self.predecessor_batch_id == self.successor_batch_id:
            raise ValueError("recovery batch identity must be fresh")
        if any(ord(character) < 0x20 for character in self.successor_idempotency_key):
            raise ValueError("recovery idempotency key contains a control character")

        predecessor_ordinals = tuple(value.predecessor_ordinal for value in self.replacements)
        successor_ordinals = tuple(value.successor_ordinal for value in self.replacements)
        if predecessor_ordinals != tuple(sorted(predecessor_ordinals)):
            raise ValueError("recovery predecessor ordinals must be ordered")
        if successor_ordinals != (0, 1, 2):
            raise ValueError("recovery successor ordinals must be contiguous")

        identity_groups = (
            tuple(value.predecessor_work_unit_id for value in self.replacements),
            tuple(value.predecessor_extraction_request_id for value in self.replacements),
            tuple(value.predecessor_workflow_id for value in self.replacements),
            tuple(value.predecessor_platform_job_id for value in self.replacements),
            tuple(value.successor_work_unit_id for value in self.replacements),
            tuple(value.successor_extraction_request_id for value in self.replacements),
        )
        if any(len(values) != len(set(values)) for values in identity_groups):
            raise ValueError("recovery identities must be unique within each identity type")
        if set(identity_groups[0]) & set(identity_groups[4]):
            raise ValueError("recovery work-unit identities must be fresh")
        if set(identity_groups[1]) & set(identity_groups[5]):
            raise ValueError("recovery extraction request identities must be fresh")

        diagnosis_codes = {value.diagnosis_code for value in self.replacements}
        if diagnosis_codes != {
            "DUPLICATE_STATEMENT_EXPLANATION_ID",
            "BODY_BLOCK_DISCRIMINATOR_MISMATCH",
            "NONE_VISUAL_RENDERING_CONFLICT",
        }:
            raise ValueError("recovery must cover each diagnosed validation category exactly once")
        item_occurrences = tuple(
            (replacement.predecessor_bundle_revision_id, number)
            for replacement in self.replacements
            for number in replacement.expected_item_numbers
        )
        if len(item_occurrences) != 15 or len(set(item_occurrences)) != 15:
            raise ValueError("recovery must cover exactly 15 unique scoped item occurrences")

        predecessor = self.predecessor_preset
        successor = self.successor_preset
        if predecessor.preset_id != successor.preset_id:
            raise ValueError("recovery preset logical identity must be stable")
        if predecessor.preset_revision_id == successor.preset_revision_id:
            raise ValueError("recovery preset revision must be a successor")
        if successor.preset_revision_number != predecessor.preset_revision_number + 2:
            raise ValueError("recovery released preset successor must follow its draft")
        if predecessor.preset_sha256 == successor.preset_sha256:
            raise ValueError("recovery preset content hash must change")
        if predecessor.preset_policy_sha256 == successor.preset_policy_sha256:
            raise ValueError("recovery preset policy hash must change")
        if predecessor.instruction_bundle_id != successor.instruction_bundle_id:
            raise ValueError("recovery instruction bundle logical identity must be stable")
        if predecessor.instruction_bundle_revision_id == successor.instruction_bundle_revision_id:
            raise ValueError("recovery instruction bundle revision must change")
        if successor.instruction_revision_number != predecessor.instruction_revision_number + 1:
            raise ValueError("recovery instruction bundle successor must be adjacent")
        if predecessor.instruction_manifest_sha256 == successor.instruction_manifest_sha256:
            raise ValueError("recovery instruction manifest hash must change")
        if predecessor.instruction_content_sha256 == successor.instruction_content_sha256:
            raise ValueError("recovery instruction content hash must change")
        stable_execution_fields = (
            "capacity_policy_revision_id",
            "capacity_policy_sha256",
            "workflow_definition_id",
            "workflow_definition_version",
            "workflow_definition_sha256",
            "role_schema_version",
            "role_schema_sha256",
        )
        if any(
            getattr(predecessor, field) != getattr(successor, field)
            for field in stable_execution_fields
        ):
            raise ValueError("recovery changed a non-instruction execution dependency")

        payload = self.model_dump(mode="json", exclude={"recovery_sha256"})
        if self.recovery_sha256 != content_sha256(payload):
            raise ValueError("recovery hash does not match canonical content")
        return self


__all__ = [
    "ExtractionValidationDiagnosis",
    "LegacyExtractionPresetPointer",
    "LegacyExtractionValidationReplacement",
    "LegacyItemExtractionValidationRecovery",
]
