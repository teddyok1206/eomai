"""Protocol contracts for deterministic legacy item corpus coverage completion.

These models are generic: no release-specific 50/108/520 cardinality is embedded here. The
application service derives all counts and exact sets from pinned manifests and authorization.
"""

from __future__ import annotations

from typing import Literal

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from pydantic import Field, model_validator

from eom_catalog_contracts.legacy_assessment import AssessmentArtifactMemberPointer
from eom_catalog_contracts.legacy_extraction_recovery import (
    LegacyItemExtractionValidationRecovery,
)
from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256, UtcDatetime


class LegacyExtractionBatchManifestIdentity(FrozenModel):
    """Logical batch and immutable manifest content identity."""

    extraction_batch_id: str = Field(pattern=r"^legacybatch_[0-9a-f]{32}$")
    manifest_sha256: Sha256


class LegacyItemCorpusCompletionCommand(FrozenModel):
    """Caller intent containing only pinned source authority and authenticated actor."""

    schema_version: Literal["legacy-item-corpus-completion-command/1.0"]
    inventory_id: str = Field(pattern=r"^legacyinventory_[0-9a-f]{32}$")
    inventory_sha256: Sha256
    original_batch: LegacyExtractionBatchManifestIdentity
    successor_batch: LegacyExtractionBatchManifestIdentity
    recovery_sha256: Sha256
    recovery_artifact: AssessmentArtifactMemberPointer
    requested_by: ActorId
    command_sha256: Sha256

    @model_validator(mode="after")
    def exact_pointers_and_hash(self) -> LegacyItemCorpusCompletionCommand:
        if self.original_batch.extraction_batch_id == self.successor_batch.extraction_batch_id:
            raise ValueError("completion batch identities must be distinct")
        if (
            self.recovery_artifact.member_path != "validation-recovery.json"
            or self.recovery_artifact.schema_ref
            != "eom://schemas/legacy-assessment/legacy-item-extraction-validation-recovery/1.0"
            or self.recovery_artifact.media_type != "application/json"
        ):
            raise ValueError("completion recovery Artifact contract differs")
        if self.command_sha256 != expected_corpus_completion_command_sha256(self):
            raise ValueError("completion command hash does not match canonical content")
        return self


class LegacyExtractionBatchCompletionEvidence(FrozenModel):
    """Resolved terminal batch and exact immutable manifest pointer."""

    extraction_batch_id: str = Field(pattern=r"^legacybatch_[0-9a-f]{32}$")
    manifest_sha256: Sha256
    manifest_artifact: AssessmentArtifactMemberPointer
    state: Literal["COMPLETED_WITH_GAPS", "SUCCEEDED"]
    total_work_unit_count: int = Field(ge=0, le=10000)
    accepted_work_unit_count: int = Field(ge=0, le=10000)
    failed_work_unit_count: int = Field(ge=0, le=10000)
    other_work_unit_count: int = Field(ge=0, le=10000)

    @model_validator(mode="after")
    def exact_distribution(self) -> LegacyExtractionBatchCompletionEvidence:
        if self.total_work_unit_count != (
            self.accepted_work_unit_count + self.failed_work_unit_count + self.other_work_unit_count
        ):
            raise ValueError("completion batch counts do not form an exact partition")
        if (
            self.manifest_artifact.member_path != "legacy-item-extraction-batch.json"
            or self.manifest_artifact.schema_ref
            != "eom://schemas/legacy-assessment/legacy-item-extraction-batch/1.1"
            or self.manifest_artifact.media_type != "application/json"
        ):
            raise ValueError("completion batch manifest Artifact contract differs")
        return self


class LegacyItemCorpusCompletionReceipt(FrozenModel):
    """Small immutable proof that exact derived coverage was committed and registered."""

    schema_version: Literal["legacy-item-corpus-completion-receipt/1.0"]
    status: Literal["COMPLETE"]
    requested_by: ActorId
    command_sha256: Sha256
    inventory_id: str = Field(pattern=r"^legacyinventory_[0-9a-f]{32}$")
    inventory_sha256: Sha256
    inventory_artifact: AssessmentArtifactMemberPointer
    original_batch: LegacyExtractionBatchCompletionEvidence
    successor_batch: LegacyExtractionBatchCompletionEvidence
    recovery_sha256: Sha256
    recovery_artifact: AssessmentArtifactMemberPointer
    coverage_id: str = Field(pattern=r"^itemcoverage_[0-9a-f]{32}$")
    coverage_sha256: Sha256
    coverage_artifact: AssessmentArtifactMemberPointer
    original_work_unit_count: int = Field(ge=1, le=10000)
    effective_work_unit_count: int = Field(ge=1, le=10000)
    # Recovery V1 authorizes exactly three replacements. Corpus/item cardinalities remain derived.
    recovered_work_unit_count: Literal[3]
    expected_item_count: int = Field(ge=1, le=10_000_000)
    accepted_item_count: int = Field(ge=1, le=10_000_000)
    missing_item_count: Literal[0]
    conflict_item_count: Literal[0]
    expected_item_keys_sha256: Sha256
    accepted_item_map_sha256: Sha256
    created_at: UtcDatetime
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def exact_completion(self) -> LegacyItemCorpusCompletionReceipt:
        original = self.original_batch
        successor = self.successor_batch
        if original.extraction_batch_id == successor.extraction_batch_id:
            raise ValueError("completion batch evidence identities must be distinct")
        if self.original_work_unit_count != original.total_work_unit_count:
            raise ValueError("completion original work-unit count differs")
        if self.effective_work_unit_count != self.original_work_unit_count:
            raise ValueError("completion must replace work units one-for-one")
        if self.recovered_work_unit_count != successor.total_work_unit_count:
            raise ValueError("completion successor count differs from recovery count")
        if (
            original.state != "COMPLETED_WITH_GAPS"
            or original.failed_work_unit_count != self.recovered_work_unit_count
            or original.accepted_work_unit_count + original.failed_work_unit_count
            != original.total_work_unit_count
            or original.other_work_unit_count != 0
            or successor.state != "SUCCEEDED"
            or successor.accepted_work_unit_count != successor.total_work_unit_count
            or successor.failed_work_unit_count != 0
            or successor.other_work_unit_count != 0
        ):
            raise ValueError("completion batch evidence is not the exact recovered partition")
        if self.expected_item_count != self.accepted_item_count:
            raise ValueError("completion expected and accepted item counts differ")
        if (
            self.inventory_artifact.member_path != "legacy-source-inventory.json"
            or self.inventory_artifact.schema_ref
            != "eom://schemas/legacy-knowledge/legacy-source-inventory/2.0"
            or self.inventory_artifact.media_type != "application/json"
        ):
            raise ValueError("completion inventory Artifact contract differs")
        if (
            self.coverage_artifact.member_path != "coverage.json"
            or self.coverage_artifact.schema_ref
            != "eom://schemas/legacy-assessment/legacy-item-corpus-coverage/1.0"
            or self.coverage_artifact.media_type != "application/json"
        ):
            raise ValueError("completion coverage Artifact contract differs")
        if (
            self.recovery_artifact.member_path != "validation-recovery.json"
            or self.recovery_artifact.schema_ref
            != "eom://schemas/legacy-assessment/legacy-item-extraction-validation-recovery/1.0"
            or self.recovery_artifact.media_type != "application/json"
        ):
            raise ValueError("completion recovery Artifact contract differs")
        if self.receipt_sha256 != expected_corpus_completion_receipt_sha256(self):
            raise ValueError("completion receipt hash does not match canonical content")
        return self


def expected_corpus_completion_command_sha256(
    command: LegacyItemCorpusCompletionCommand,
) -> str:
    """Return the canonical command self-hash without mutating the value object."""

    return content_sha256(command.model_dump(mode="json", exclude={"command_sha256"}))


def expected_corpus_completion_receipt_sha256(
    receipt: LegacyItemCorpusCompletionReceipt,
) -> str:
    """Return the canonical receipt self-hash without mutating the value object."""

    return content_sha256(receipt.model_dump(mode="json", exclude={"receipt_sha256"}))


def verify_corpus_completion_recovery_authority(
    command: LegacyItemCorpusCompletionCommand,
    recovery: LegacyItemExtractionValidationRecovery,
) -> None:
    """Resolve the independent recovery Artifact without embedding it in the command."""

    if (
        recovery.predecessor_batch_id != command.original_batch.extraction_batch_id
        or recovery.predecessor_manifest_sha256 != command.original_batch.manifest_sha256
        or recovery.successor_batch_id != command.successor_batch.extraction_batch_id
        or recovery.recovery_sha256 != command.recovery_sha256
        or command.recovery_artifact.sha256 != sha256_bytes(canonical_json_bytes(recovery) + b"\n")
    ):
        raise ValueError("completion recovery authority differs from its pinned Artifact")


def verify_corpus_completion_receipt_command(
    receipt: LegacyItemCorpusCompletionReceipt,
    command: LegacyItemCorpusCompletionCommand,
) -> None:
    """Cross-bind a receipt to the exact command and raw recovery Artifact member."""

    if (
        receipt.command_sha256 != command.command_sha256
        or receipt.requested_by != command.requested_by
        or receipt.inventory_id != command.inventory_id
        or receipt.inventory_sha256 != command.inventory_sha256
        or receipt.original_batch.extraction_batch_id != command.original_batch.extraction_batch_id
        or receipt.original_batch.manifest_sha256 != command.original_batch.manifest_sha256
        or receipt.successor_batch.extraction_batch_id
        != command.successor_batch.extraction_batch_id
        or receipt.successor_batch.manifest_sha256 != command.successor_batch.manifest_sha256
        or receipt.recovery_sha256 != command.recovery_sha256
        or receipt.recovery_artifact != command.recovery_artifact
    ):
        raise ValueError("completion receipt differs from its exact command authority")


__all__ = [
    "LegacyExtractionBatchCompletionEvidence",
    "LegacyExtractionBatchManifestIdentity",
    "LegacyItemCorpusCompletionCommand",
    "LegacyItemCorpusCompletionReceipt",
    "expected_corpus_completion_command_sha256",
    "expected_corpus_completion_receipt_sha256",
    "verify_corpus_completion_receipt_command",
    "verify_corpus_completion_recovery_authority",
]
