"""Bounded human-review values, not source or publication authorization.

The owner separately authenticates the current operator and reauthorizes every
exact source and Artifact read. A captured prepared_by/reviewer ID, comparison
state, or canonical hash does not grant permission or prove scientific quality.
"""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, model_validator

from eom_catalog_contracts.inference_transfer_invocation import (
    InferenceTransferPairSubmitRequest,
    InferenceTransferWorkflowReadResult,
    TransferWorkflowId,
)
from eom_catalog_contracts.inference_transfer_snapshot import InferenceTransferSnapshotRecord
from eom_catalog_contracts.item_inference_transfer import (
    HumanTransferEvaluation,
    InferenceTransferProfilePointer,
    validate_pair_comparison_references,
)
from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

MAX_HUMAN_REVIEW_BYTES = 2 * 1024**2
MAX_HUMAN_COMMAND_BYTES = 64 * 1024
HUMAN_REVIEW_BUNDLE_SCHEMA_REF = (
    "eom://schemas/knowledge/item-inference-transfer-human-review-bundle/1.0"
)
HUMAN_REVIEW_RECORD_SCHEMA_REF = (
    "eom://schemas/knowledge/item-inference-transfer-human-review-record/1.0"
)
type HumanBundleId = Annotated[str, Field(pattern=r"^transferreviewbundle_[0-9a-f]{32}$")]
type HumanBundleRevisionId = Annotated[
    str, Field(pattern=r"^transferreviewbundlerev_[0-9a-f]{32}$")
]


def _canonical_hash_and_bound(value: FrozenModel, hash_field: str, maximum: int) -> None:
    if getattr(value, hash_field) != content_sha256(
        value.model_dump(mode="json", exclude={hash_field})
    ):
        raise ValueError(f"{hash_field} differs from canonical human-review content")
    if len(canonical_json_bytes(value.model_dump(mode="json"))) > maximum:
        raise ValueError("human-review value exceeds its encoded byte budget")


def _bundle_member(value: ArtifactMemberPointer) -> ArtifactMemberPointer:
    checked = ArtifactMemberPointer.model_validate(value.model_dump(mode="json"))
    if (
        checked.member_path != "result.json"
        or checked.schema_ref != HUMAN_REVIEW_BUNDLE_SCHEMA_REF
        or checked.media_type != "application/json"
    ):
        raise ValueError("human evaluation must reference an exact human-review bundle member")
    return checked


class InferenceTransferHumanBundleCommand(FrozenModel):
    """Fixed caller metadata and exact selected pair, never an operator grant."""

    schema_version: Literal["item-inference-transfer-human-bundle-command/1.0"] = (
        "item-inference-transfer-human-bundle-command/1.0"
    )
    bundle_id: HumanBundleId
    bundle_revision_id: HumanBundleRevisionId
    created_at: UtcDatetime
    selection: InferenceTransferPairSubmitRequest
    workflow_id: TransferWorkflowId
    command_sha256: Sha256

    @model_validator(mode="after")
    def exact_command(self) -> InferenceTransferHumanBundleCommand:
        InferenceTransferPairSubmitRequest.model_validate(self.selection.model_dump(mode="json"))
        _canonical_hash_and_bound(self, "command_sha256", MAX_HUMAN_COMMAND_BYTES)
        return self


class InferenceTransferHumanReviewBundle(FrozenModel):
    """One bounded two-Item materialization with the model hypothesis kept separate.

    Sources retain their complete exact snapshot chain. Pure validation checks
    identity/ref closure; MEMBER_VERIFIED and prepared_by must come from the
    supported owner. This value cannot certify that PDF/PNG pixels were inspected.
    """

    schema_version: Literal["item-inference-transfer-human-review-bundle/1.0"] = (
        "item-inference-transfer-human-review-bundle/1.0"
    )
    command: InferenceTransferHumanBundleCommand
    prepared_by: ActorId
    comparison: InferenceTransferWorkflowReadResult
    sources: tuple[InferenceTransferSnapshotRecord, ...] = Field(min_length=2, max_length=2)
    bundle_sha256: Sha256

    @model_validator(mode="after")
    def exact_pair_materialization(self) -> InferenceTransferHumanReviewBundle:
        # JSON-mode reparsing also validates frozen instances made with unchecked
        # model_copy/model_construct; no nested instance is a validation shortcut.
        command = InferenceTransferHumanBundleCommand.model_validate(
            self.command.model_dump(mode="json")
        )
        comparison = InferenceTransferWorkflowReadResult.model_validate(
            self.comparison.model_dump(mode="json")
        )
        sources = tuple(
            InferenceTransferSnapshotRecord.model_validate(source.model_dump(mode="json"))
            for source in self.sources
        )
        if (
            comparison.workflow_state != "COMPLETED"
            or comparison.result_state != "MEMBER_VERIFIED"
            or comparison.result is None
        ):
            raise ValueError("human-review bundle requires a canonical member-verified comparison")
        if (
            command.workflow_id != comparison.workflow_id
            or command.selection.comparison != comparison.comparison
        ):
            raise ValueError("human-review comparison differs from the exact Workflow selection")
        prepare = command.selection.snapshot_prepare
        if (
            prepare.graph_snapshot != comparison.graph_snapshot
            or prepare.access_policy_revision_id != comparison.access_policy_revision_id
            or prepare.access_policy_sha256 != comparison.access_policy_sha256
        ):
            raise ValueError("human-review comparison differs from its Graph or policy pins")
        profiles = []
        for source in sources:
            entry = source.staged_entry
            if entry is None or entry.content is None or not entry.content.text.strip():
                raise ValueError("human-review source requires available canonical question text")
            profile = entry.profile
            if (
                profile.source_basis.graph_snapshot != prepare.graph_snapshot
                or source.source.source_class not in prepare.source_classes
                or profile.extraction.extractor_version != prepare.projection_version
            ):
                raise ValueError("human-review source differs from the pinned snapshot scope")
            profiles.append(profile)
        request = comparison.comparison
        if tuple(InferenceTransferProfilePointer.from_profile(profile) for profile in profiles) != (
            request.left_profile,
            request.right_profile,
        ):
            raise ValueError("human-review sources must follow the exact selected A-to-B order")
        validate_pair_comparison_references(request, comparison.result, profiles[0], profiles[1])
        _canonical_hash_and_bound(self, "bundle_sha256", MAX_HUMAN_REVIEW_BYTES)
        return self


class InferenceTransferHumanRecordCommand(FrozenModel):
    schema_version: Literal["item-inference-transfer-human-record-command/1.0"] = (
        "item-inference-transfer-human-record-command/1.0"
    )
    bundle: ArtifactMemberPointer
    evaluation: HumanTransferEvaluation
    command_sha256: Sha256

    @model_validator(mode="after")
    def exact_command(self) -> InferenceTransferHumanRecordCommand:
        _bundle_member(self.bundle)
        HumanTransferEvaluation.model_validate(self.evaluation.model_dump(mode="json"))
        _canonical_hash_and_bound(self, "command_sha256", MAX_HUMAN_COMMAND_BYTES)
        return self


class InferenceTransferHumanReviewRecord(FrozenModel):
    """Small label + exact bundle pointer; no duplicated question or solution text."""

    schema_version: Literal["item-inference-transfer-human-review-record/1.0"] = (
        "item-inference-transfer-human-review-record/1.0"
    )
    bundle: ArtifactMemberPointer
    evaluation: HumanTransferEvaluation
    record_sha256: Sha256

    @model_validator(mode="after")
    def exact_record(self) -> InferenceTransferHumanReviewRecord:
        _bundle_member(self.bundle)
        HumanTransferEvaluation.model_validate(self.evaluation.model_dump(mode="json"))
        _canonical_hash_and_bound(self, "record_sha256", MAX_HUMAN_REVIEW_BYTES)
        return self


def parse_human_bundle_command(value: object) -> InferenceTransferHumanBundleCommand:
    if not isinstance(value, dict):
        raise ValueError("human-review bundle command must be a JSON object")
    validate_contract("item-inference-transfer-human-review", value)
    return InferenceTransferHumanBundleCommand.model_validate(value)


def parse_human_bundle(value: object) -> InferenceTransferHumanReviewBundle:
    if not isinstance(value, dict):
        raise ValueError("human-review bundle must be a JSON object")
    validate_contract("item-inference-transfer-human-review", value)
    return InferenceTransferHumanReviewBundle.model_validate(value)


def parse_human_record_command(value: object) -> InferenceTransferHumanRecordCommand:
    if not isinstance(value, dict):
        raise ValueError("human-review record command must be a JSON object")
    validate_contract("item-inference-transfer-human-review", value)
    return InferenceTransferHumanRecordCommand.model_validate(value)


def parse_human_record(value: object) -> InferenceTransferHumanReviewRecord:
    if not isinstance(value, dict):
        raise ValueError("human-review record must be a JSON object")
    validate_contract("item-inference-transfer-human-review", value)
    return InferenceTransferHumanReviewRecord.model_validate(value)


def validate_human_record_context(
    bundle: InferenceTransferHumanReviewBundle, evaluation: HumanTransferEvaluation
) -> None:
    """Exact pair/rubric/captured-reviewer identity only, not current authorization.

    Both publication and canonical-record read reuse this rule. The application
    must still compare the actual current operator, source access and time itself.
    """
    checked_bundle = parse_human_bundle(bundle.model_dump(mode="json"))
    checked_evaluation = HumanTransferEvaluation.model_validate(evaluation.model_dump(mode="json"))
    request = checked_bundle.command.selection.comparison
    if (
        checked_evaluation.left_profile != request.left_profile
        or checked_evaluation.right_profile != request.right_profile
        or checked_evaluation.direction != request.direction
        or checked_evaluation.rubric != request.rubric
        or checked_evaluation.reviewer_id != checked_bundle.prepared_by
    ):
        raise ValueError("human evaluation differs from its exact bundle pair, rubric or reviewer")
