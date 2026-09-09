"""Protocol contracts for deterministic legacy item corpus coverage completion.

These models are generic: no release-specific 50/108/520 cardinality is embedded here. The
application service derives all counts and exact sets from pinned manifests and authorization.
"""

from __future__ import annotations

from collections.abc import Iterable
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


class LegacyExtractionResultIdentityCollisionMember(FrozenModel):
    """One exact effective chain participating in a historical logical-ID collision."""

    effective_batch_id: str = Field(pattern=r"^legacybatch_[0-9a-f]{32}$")
    effective_work_unit_id: str = Field(pattern=r"^legacyworkunit_[0-9a-f]{32}$")
    effective_ordinal: int = Field(ge=0, le=999999)
    extraction_request_id: str = Field(pattern=r"^itemextractreq_[0-9a-f]{32}$")
    request_sha256: Sha256
    extraction_result_id: str = Field(pattern=r"^itemextractresult_[0-9a-f]{32}$")
    result_artifact: AssessmentArtifactMemberPointer
    result_sha256: Sha256
    extraction_receipt_sha256: Sha256
    acceptance_id: str = Field(pattern=r"^itemacceptance_[0-9a-f]{32}$")
    acceptance_sha256: Sha256
    acceptance_artifact: AssessmentArtifactMemberPointer

    @model_validator(mode="after")
    def exact_artifact_contracts(self) -> LegacyExtractionResultIdentityCollisionMember:
        if (
            self.result_artifact.member_path != "result.json"
            or self.result_artifact.schema_ref
            != "eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0"
            or self.result_artifact.media_type != "application/json"
            or self.acceptance_artifact.member_path != "acceptance.json"
            or self.acceptance_artifact.schema_ref
            != "eom://schemas/legacy-assessment/legacy-item-extraction-acceptance/1.0"
            or self.acceptance_artifact.media_type != "application/json"
        ):
            raise ValueError("historical collision Artifact contract differs")
        return self


def _collision_member_sort_key(
    member: LegacyExtractionResultIdentityCollisionMember,
) -> tuple[str, str, int, str, str, str]:
    return (
        member.effective_batch_id,
        member.effective_work_unit_id,
        member.effective_ordinal,
        member.extraction_request_id,
        member.result_artifact.artifact_revision_id,
        member.acceptance_id,
    )


class LegacyExtractionResultIdentityCollisionGroup(FrozenModel):
    """All independent immutable chains that reused one result logical ID."""

    extraction_result_id: str = Field(pattern=r"^itemextractresult_[0-9a-f]{32}$")
    members: tuple[LegacyExtractionResultIdentityCollisionMember, ...] = Field(
        min_length=2, max_length=108
    )

    @model_validator(mode="after")
    def exact_group(self) -> LegacyExtractionResultIdentityCollisionGroup:
        if any(member.extraction_result_id != self.extraction_result_id for member in self.members):
            raise ValueError("historical collision group contains another result identity")
        if self.members != tuple(sorted(self.members, key=_collision_member_sort_key)):
            raise ValueError("historical collision members must use canonical order")
        membership_ids = tuple(
            (member.effective_batch_id, member.effective_work_unit_id) for member in self.members
        )
        if len(membership_ids) != len(set(membership_ids)):
            raise ValueError("historical collision contains duplicate memberships")
        return self


class LegacyExtractionResultIdentityCollisions(FrozenModel):
    """Bounded pointer-only evidence for immutable historical result-ID reuse."""

    schema_version: Literal["legacy-extraction-result-identity-collisions/1.0"]
    disposition: Literal["HISTORICAL_COLLISION_ATTESTED"]
    collision_group_count: int = Field(ge=1, le=108)
    collision_membership_count: int = Field(ge=2, le=108)
    noncanonical_membership_count: int = Field(ge=1, le=107)
    groups: tuple[LegacyExtractionResultIdentityCollisionGroup, ...] = Field(
        min_length=1, max_length=108
    )
    evidence_sha256: Sha256

    @model_validator(mode="after")
    def exact_counts_order_and_hash(self) -> LegacyExtractionResultIdentityCollisions:
        result_ids = tuple(group.extraction_result_id for group in self.groups)
        if result_ids != tuple(sorted(set(result_ids))):
            raise ValueError("historical collision groups must be sorted and unique")
        membership_count = sum(len(group.members) for group in self.groups)
        noncanonical_count = sum(len(group.members) - 1 for group in self.groups)
        if (
            self.collision_group_count != len(self.groups)
            or self.collision_membership_count != membership_count
            or self.noncanonical_membership_count != noncanonical_count
        ):
            raise ValueError("historical collision counts differ from their groups")
        members = tuple(member for group in self.groups for member in group.members)
        _require_non_result_evidence_uniqueness(members)
        if self.evidence_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"evidence_sha256"})
        ):
            raise ValueError("historical collision evidence hash differs")
        return self


def _require_non_result_evidence_uniqueness(
    members: tuple[LegacyExtractionResultIdentityCollisionMember, ...],
) -> None:
    identity_groups = (
        tuple((member.effective_batch_id, member.effective_work_unit_id) for member in members),
        tuple(member.extraction_request_id for member in members),
        tuple(member.result_artifact.artifact_revision_id for member in members),
        tuple(member.extraction_receipt_sha256 for member in members),
        tuple(member.acceptance_id for member in members),
        tuple(member.acceptance_artifact.artifact_revision_id for member in members),
    )
    if any(len(values) != len(set(values)) for values in identity_groups):
        raise ValueError("effective non-result evidence identities must be one-to-one")


def derive_legacy_extraction_result_identity_collisions(
    members: Iterable[LegacyExtractionResultIdentityCollisionMember],
) -> LegacyExtractionResultIdentityCollisions | None:
    """Return canonical collision evidence while retaining all other one-to-one invariants."""

    values = tuple(members)
    _require_non_result_evidence_uniqueness(values)
    by_result_id: dict[str, list[LegacyExtractionResultIdentityCollisionMember]] = {}
    for member in values:
        by_result_id.setdefault(member.extraction_result_id, []).append(member)
    groups = tuple(
        LegacyExtractionResultIdentityCollisionGroup(
            extraction_result_id=result_id,
            members=tuple(sorted(group_members, key=_collision_member_sort_key)),
        )
        for result_id, group_members in sorted(by_result_id.items())
        if len(group_members) > 1
    )
    if not groups:
        return None
    document: dict[str, object] = {
        "schema_version": "legacy-extraction-result-identity-collisions/1.0",
        "disposition": "HISTORICAL_COLLISION_ATTESTED",
        "collision_group_count": len(groups),
        "collision_membership_count": sum(len(group.members) for group in groups),
        "noncanonical_membership_count": sum(len(group.members) - 1 for group in groups),
        "groups": [group.model_dump(mode="json") for group in groups],
        "evidence_sha256": "sha256:" + "0" * 64,
    }
    document["evidence_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "evidence_sha256"}
    )
    return LegacyExtractionResultIdentityCollisions.model_validate(document)


class LegacyItemCorpusCompletionCommand(FrozenModel):
    """Caller intent containing only pinned source authority and authenticated actor."""

    schema_version: Literal[
        "legacy-item-corpus-completion-command/1.0",
        "legacy-item-corpus-completion-command/1.1",
    ]
    inventory_id: str = Field(pattern=r"^legacyinventory_[0-9a-f]{32}$")
    inventory_sha256: Sha256
    original_batch: LegacyExtractionBatchManifestIdentity
    successor_batch: LegacyExtractionBatchManifestIdentity
    recovery_sha256: Sha256
    recovery_artifact: AssessmentArtifactMemberPointer
    historical_result_identity_collisions: LegacyExtractionResultIdentityCollisions | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    requested_by: ActorId
    command_sha256: Sha256

    @model_validator(mode="after")
    def exact_pointers_and_hash(self) -> LegacyItemCorpusCompletionCommand:
        collision_version = self.schema_version == "legacy-item-corpus-completion-command/1.1"
        if collision_version != (self.historical_result_identity_collisions is not None):
            raise ValueError("completion command version and collision evidence differ")
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

    schema_version: Literal[
        "legacy-item-corpus-completion-receipt/1.0",
        "legacy-item-corpus-completion-receipt/1.1",
    ]
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
    historical_result_identity_collisions: LegacyExtractionResultIdentityCollisions | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
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
        collision_version = self.schema_version == "legacy-item-corpus-completion-receipt/1.1"
        if collision_version != (self.historical_result_identity_collisions is not None):
            raise ValueError("completion receipt version and collision evidence differ")
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
        (receipt.schema_version.endswith("/1.1")) != (command.schema_version.endswith("/1.1"))
        or receipt.command_sha256 != command.command_sha256
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
        or receipt.historical_result_identity_collisions
        != command.historical_result_identity_collisions
    ):
        raise ValueError("completion receipt differs from its exact command authority")


__all__ = [
    "LegacyExtractionBatchCompletionEvidence",
    "LegacyExtractionBatchManifestIdentity",
    "LegacyExtractionResultIdentityCollisionGroup",
    "LegacyExtractionResultIdentityCollisionMember",
    "LegacyExtractionResultIdentityCollisions",
    "LegacyItemCorpusCompletionCommand",
    "LegacyItemCorpusCompletionReceipt",
    "derive_legacy_extraction_result_identity_collisions",
    "expected_corpus_completion_command_sha256",
    "expected_corpus_completion_receipt_sha256",
    "verify_corpus_completion_receipt_command",
    "verify_corpus_completion_recovery_authority",
]
