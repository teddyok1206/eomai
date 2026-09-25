"""Immutable contracts for bounded local-image LoRA training."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    ImageEvaluationBoundingBox,
    ImageEvaluationSourceSnapshot,
    LocalImageModelPointer,
    Sha256,
    content_sha256,
    text_sha256,
)

AUTHORIZATION_SCHEMA_REF = "eom://schemas/image-provider/local-image-training-authorization/1.0"
DATASET_SCHEMA_REF = "eom://schemas/image-provider/local-image-training-dataset-manifest/1.0"
CANDIDATE_INVENTORY_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-training-candidate-inventory/1.0"
)
TRAINING_PLAN_SCHEMA_REF = "eom://schemas/image-provider/local-image-lora-training-plan/1.0"
ADAPTER_MANIFEST_SCHEMA_REF = "eom://schemas/image-provider/local-image-lora-adapter-manifest/1.0"
CHECKPOINT_MANIFEST_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-lora-checkpoint-manifest/1.0"
)
EVALUATION_PLAN_SCHEMA_REF = "eom://schemas/image-provider/local-image-quality-evaluation-plan/1.0"
ELIGIBILITY_REVIEW_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-training-eligibility-review/1.0"
)
CROP_PROPOSAL_SET_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-training-crop-proposal-set/1.0"
)
CROP_LOCATOR_COMMAND_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-crop-locator-command/1.0"
)
CROP_LOCATOR_RESULT_SCHEMA_REF = "eom://schemas/image-provider/local-image-crop-locator-result/1.0"


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must be UTC")
    return value


def _require_pointer(
    pointer: ImageEvaluationArtifactMember,
    *,
    schema_ref: str,
    member_path: str,
) -> None:
    if (
        pointer.schema_ref != schema_ref
        or pointer.media_type != "application/json"
        or pointer.member_path != member_path
    ):
        raise ValueError("artifact pointer contract mismatch")


class ImageTrainingRightsPolicy(FrozenModel):
    rights_policy_id: str = Field(pattern=r"^rightspolicy_[0-9a-f]{32}$")
    rights_policy_revision_id: str = Field(pattern=r"^rightspolicyrev_[0-9a-f]{32}$")
    rights_policy_sha256: Sha256


class LocalImageTrainingAuthorization(FrozenModel):
    schema_version: Literal["local-image-training-authorization/1.0"]
    authorization_id: str = Field(pattern=r"^imgtrainauth_[0-9a-f]{32}$")
    authorization_revision_id: str = Field(pattern=r"^imgtrainauthrev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1, le=100_000)
    previous_revision_id: str | None = Field(pattern=r"^imgtrainauthrev_[0-9a-f]{32}$")
    source_snapshot: ImageEvaluationSourceSnapshot
    rights_policies: tuple[ImageTrainingRightsPolicy, ...] = Field(
        min_length=1,
        max_length=100,
    )
    permitted_use: Literal["INTERNAL_LORA_TRAINING"]
    derivative_output: Literal["LORA_ADAPTER_ONLY"]
    state: Literal["APPROVED"]
    approved_at: datetime
    approved_by: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:@-]+$",
    )
    authorization_sha256: Sha256

    @field_validator("approved_at")
    @classmethod
    def utc_approval(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def revision_and_hash_are_coherent(self) -> LocalImageTrainingAuthorization:
        if (self.revision_number == 1) != (self.previous_revision_id is None):
            raise ValueError("training authorization revision chain is inconsistent")
        revision_ids = tuple(policy.rights_policy_revision_id for policy in self.rights_policies)
        if revision_ids != tuple(sorted(revision_ids)) or len(revision_ids) != len(
            set(revision_ids)
        ):
            raise ValueError("training rights policies must be uniquely sorted")
        expected = content_sha256(self.model_dump(mode="json", exclude={"authorization_sha256"}))
        if self.authorization_sha256 != expected:
            raise ValueError("training authorization hash mismatch")
        return self


ImageTrainingCropRepresentationKind = Literal[
    "APPARATUS",
    "COMPOSITE",
    "CROSS_SECTION",
    "DIAGRAM",
    "MAP",
    "PARTICLE_MODEL",
    "PHOTOGRAPH",
]
ImageTrainingCropVisualFeature = Literal[
    "ARROWS",
    "AXES",
    "BOUNDARY",
    "CALLOUT",
    "DATA_POINTS",
    "ERROR_BAR",
    "GRID",
    "LABELS",
    "LEADER_LINES",
    "LEGEND",
    "MULTIPLE_PANELS",
    "NUMBERED_STEPS",
    "PATTERN_FILL",
    "SCALE",
    "SYMBOL_KEY",
    "TRAJECTORY",
]
ImageTrainingCropOmissionReason = Literal[
    "ANSWER_EXPLANATION_SOURCE",
    "HOLDOUT_SOURCE",
    "NO_PAGE_INPUT",
    "NO_VISUAL_REGION",
    "SOURCE_POINTER_INVALID",
    "UNSUPPORTED_REPRESENTATION",
]
ImageTrainingCropExclusionReason = Literal[
    "ANSWER_OR_EXPLANATION_CONTENT",
    "AUTHORITATIVE_GEOMETRY",
    "HOLDOUT_OR_NEAR_DUPLICATE",
    "HUMAN_SUBJECT",
    "ITEM_NUMBER_OR_PUBLISHER_MARK",
    "NO_VALID_CROP",
    "OCR_REDACTION_INCOMPLETE",
    "TABLE_OR_GRAPH",
    "UNAUTHORIZED_SOURCE",
    "UNSUITABLE_OTHER",
]


def _box_key(value: ImageEvaluationBoundingBox) -> tuple[int, int, int, int]:
    return (value.top, value.left, value.bottom, value.right)


def _box_contains(
    outer: ImageEvaluationBoundingBox,
    inner: ImageEvaluationBoundingBox,
) -> bool:
    return (
        outer.left <= inner.left
        and outer.top <= inner.top
        and outer.right >= inner.right
        and outer.bottom >= inner.bottom
    )


class LocalImageTrainingCropProposal(FrozenModel):
    crop_proposal_id: str = Field(pattern=r"^imgcropproposal_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    extraction_result: ImageEvaluationArtifactMember
    source_anchor_id: str = Field(pattern=r"^assessmentanchor_[0-9a-f]{32}$")
    visual_pattern_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    source_page_image: ImageEvaluationArtifactMember
    physical_page: int = Field(ge=1, le=100_000)
    context_bounding_box: ImageEvaluationBoundingBox | None
    crop_bounding_box: ImageEvaluationBoundingBox
    redaction_boxes: tuple[ImageEvaluationBoundingBox, ...] = Field(max_length=64)
    rights_policy: ImageTrainingRightsPolicy
    representation_kind: ImageTrainingCropRepresentationKind
    rendering_mode: Literal["MIXED", "RASTER", "VECTOR_LIKE"]
    visual_features: tuple[ImageTrainingCropVisualFeature, ...] = Field(max_length=24)
    candidate_rank: int = Field(ge=1, le=8)
    ink_fraction_milli: int = Field(ge=1, le=1000)
    ocr_redaction_count: int = Field(ge=0, le=64)

    @model_validator(mode="after")
    def immutable_proposal_is_coherent(self) -> LocalImageTrainingCropProposal:
        if self.source_page_image.media_type != "image/png":
            raise ValueError("crop proposal source page must be PNG")
        if self.visual_pattern_ids != tuple(sorted(set(self.visual_pattern_ids))) or any(
            re.fullmatch(r"visualpattern_[0-9a-f]{32}", value) is None
            for value in self.visual_pattern_ids
        ):
            raise ValueError("crop proposal visual pattern IDs must be valid and sorted")
        if self.visual_features != tuple(sorted(set(self.visual_features))):
            raise ValueError("crop proposal visual features must be sorted and unique")
        if self.redaction_boxes != tuple(sorted(set(self.redaction_boxes), key=_box_key)):
            raise ValueError("crop proposal redaction boxes must be sorted and unique")
        if any(not _box_contains(self.crop_bounding_box, box) for box in self.redaction_boxes):
            raise ValueError("crop proposal redaction lies outside the visual crop")
        if self.ocr_redaction_count != len(self.redaction_boxes):
            raise ValueError("crop proposal OCR count does not match redaction boxes")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"crop_proposal_id"})
        ).removeprefix("sha256:")
        if self.crop_proposal_id != "imgcropproposal_" + identity[:32]:
            raise ValueError("crop proposal ID does not bind the proposal")
        return self


class LocalImageTrainingCropProposalOmission(FrozenModel):
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    extraction_result: ImageEvaluationArtifactMember
    source_anchor_id: str = Field(pattern=r"^assessmentanchor_[0-9a-f]{32}$")
    visual_pattern_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    reason: ImageTrainingCropOmissionReason

    @model_validator(mode="after")
    def immutable_omission_is_coherent(self) -> LocalImageTrainingCropProposalOmission:
        if self.visual_pattern_ids != tuple(sorted(set(self.visual_pattern_ids))) or any(
            re.fullmatch(r"visualpattern_[0-9a-f]{32}", value) is None
            for value in self.visual_pattern_ids
        ):
            raise ValueError("crop omission visual pattern IDs must be valid and sorted")
        return self


class LocalImageCropLocatorSource(FrozenModel):
    """One exact page materialization that the isolated locator may inspect."""

    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    extraction_result: ImageEvaluationArtifactMember
    source_anchor_id: str = Field(pattern=r"^assessmentanchor_[0-9a-f]{32}$")
    visual_pattern_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    source_page_image: ImageEvaluationArtifactMember
    staged_page_member: str = Field(pattern=r"^pages/[0-9a-f]{64}\.png$")
    physical_page: int = Field(ge=1, le=100_000)
    context_bounding_box: ImageEvaluationBoundingBox | None
    rights_policy: ImageTrainingRightsPolicy
    representation_kind: ImageTrainingCropRepresentationKind
    rendering_mode: Literal["MIXED", "RASTER", "VECTOR_LIKE"]
    visual_features: tuple[ImageTrainingCropVisualFeature, ...] = Field(max_length=24)

    @model_validator(mode="after")
    def staged_source_is_coherent(self) -> LocalImageCropLocatorSource:
        if self.source_page_image.media_type != "image/png":
            raise ValueError("crop locator source page must be PNG")
        expected_member = "pages/" + self.source_page_image.sha256.removeprefix("sha256:") + ".png"
        if self.staged_page_member != expected_member:
            raise ValueError("crop locator staged page does not bind the source hash")
        if self.visual_pattern_ids != tuple(sorted(set(self.visual_pattern_ids))) or any(
            re.fullmatch(r"visualpattern_[0-9a-f]{32}", value) is None
            for value in self.visual_pattern_ids
        ):
            raise ValueError("crop locator visual pattern IDs must be valid and sorted")
        if self.visual_features != tuple(sorted(set(self.visual_features))):
            raise ValueError("crop locator visual features must be sorted and unique")
        return self


class LocalImageCropLocatorCommand(FrozenModel):
    """Bounded, pointer-bound command for the isolated deterministic crop locator."""

    schema_version: Literal["local-image-crop-locator-command/1.0"]
    locator_run_id: str = Field(pattern=r"^imgcroplocator_[0-9a-f]{32}$")
    source_snapshot: ImageEvaluationSourceSnapshot
    training_authorization: ImageEvaluationArtifactMember
    holdout_evaluation_plan: ImageEvaluationArtifactMember
    holdout_sample_ids: tuple[str, ...] = Field(min_length=12, max_length=12)
    holdout_source_anchor_ids: tuple[str, ...] = Field(min_length=12, max_length=12)
    selection_query_revision: Literal["local-image-lora-crop-source-query/1.0"]
    locator_revision: Literal["local-image-visual-crop-locator/1.0"]
    sources: tuple[LocalImageCropLocatorSource, ...] = Field(min_length=1, max_length=4096)
    preliminary_omissions: tuple[LocalImageTrainingCropProposalOmission, ...] = Field(
        max_length=4096
    )
    created_at: datetime
    created_by: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:@-]+$",
    )
    output_member: Literal["outputs/crop-locator-result.json"]
    command_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_command_is_coherent(self) -> LocalImageCropLocatorCommand:
        _require_pointer(
            self.training_authorization,
            schema_ref=AUTHORIZATION_SCHEMA_REF,
            member_path="manifests/training-authorization.json",
        )
        _require_pointer(
            self.holdout_evaluation_plan,
            schema_ref=EVALUATION_PLAN_SCHEMA_REF,
            member_path="manifests/evaluation-plan.json",
        )
        for values, label in (
            (self.holdout_sample_ids, "crop locator holdout samples"),
            (self.holdout_source_anchor_ids, "crop locator holdout anchors"),
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{label} must be sorted and unique")
        source_anchors = tuple(value.source_anchor_id for value in self.sources)
        if source_anchors != tuple(sorted(set(source_anchors))):
            raise ValueError("crop locator sources must be sorted by unique source anchor")
        if set(source_anchors) & set(self.holdout_source_anchor_ids):
            raise ValueError("crop locator sources contain a holdout source anchor")
        omission_keys = tuple(
            (value.item_revision_id, value.source_anchor_id, value.reason)
            for value in self.preliminary_omissions
        )
        if omission_keys != tuple(sorted(set(omission_keys))):
            raise ValueError("crop locator omissions must be sorted and unique")
        if set(source_anchors) & {value.source_anchor_id for value in self.preliminary_omissions}:
            raise ValueError("crop locator sources and omissions must be disjoint")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"locator_run_id", "command_sha256"})
        ).removeprefix("sha256:")
        if self.locator_run_id != "imgcroplocator_" + identity[:32]:
            raise ValueError("crop locator run ID does not bind the command inputs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"command_sha256"}))
        if self.command_sha256 != expected:
            raise ValueError("crop locator command hash mismatch")
        return self


def training_crop_proposal_population_sha256(
    *,
    source_snapshot: ImageEvaluationSourceSnapshot,
    training_authorization: ImageEvaluationArtifactMember,
    holdout_evaluation_plan: ImageEvaluationArtifactMember,
    holdout_sample_ids: tuple[str, ...],
    holdout_source_anchor_ids: tuple[str, ...],
    selection_query_revision: str,
    locator_revision: str,
    proposals: tuple[LocalImageTrainingCropProposal, ...],
    omissions: tuple[LocalImageTrainingCropProposalOmission, ...],
) -> Sha256:
    return content_sha256(
        {
            "source_snapshot": source_snapshot.model_dump(mode="json"),
            "training_authorization": training_authorization.model_dump(mode="json"),
            "holdout_evaluation_plan": holdout_evaluation_plan.model_dump(mode="json"),
            "holdout_sample_ids": holdout_sample_ids,
            "holdout_source_anchor_ids": holdout_source_anchor_ids,
            "selection_query_revision": selection_query_revision,
            "locator_revision": locator_revision,
            "proposals": tuple(value.model_dump(mode="json") for value in proposals),
            "omissions": tuple(value.model_dump(mode="json") for value in omissions),
        }
    )


class LocalImageTrainingCropProposalSet(FrozenModel):
    schema_version: Literal["local-image-training-crop-proposal-set/1.0"]
    proposal_set_id: str = Field(pattern=r"^imgcropproposalset_[0-9a-f]{32}$")
    source_snapshot: ImageEvaluationSourceSnapshot
    training_authorization: ImageEvaluationArtifactMember
    holdout_evaluation_plan: ImageEvaluationArtifactMember
    holdout_sample_ids: tuple[str, ...] = Field(min_length=12, max_length=12)
    holdout_source_anchor_ids: tuple[str, ...] = Field(min_length=12, max_length=12)
    selection_query_revision: Literal["local-image-lora-crop-source-query/1.0"]
    locator_revision: Literal["local-image-visual-crop-locator/1.0"]
    proposals: tuple[LocalImageTrainingCropProposal, ...] = Field(
        min_length=1,
        max_length=4096,
    )
    omissions: tuple[LocalImageTrainingCropProposalOmission, ...] = Field(max_length=4096)
    proposal_population_sha256: Sha256
    created_at: datetime
    created_by: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:@-]+$",
    )
    proposal_set_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_set_is_coherent(self) -> LocalImageTrainingCropProposalSet:
        _require_pointer(
            self.training_authorization,
            schema_ref=AUTHORIZATION_SCHEMA_REF,
            member_path="manifests/training-authorization.json",
        )
        _require_pointer(
            self.holdout_evaluation_plan,
            schema_ref=EVALUATION_PLAN_SCHEMA_REF,
            member_path="manifests/evaluation-plan.json",
        )
        for values, label in (
            (self.holdout_sample_ids, "crop proposal holdout samples"),
            (self.holdout_source_anchor_ids, "crop proposal holdout anchors"),
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{label} must be sorted and unique")
        proposal_ids = tuple(value.crop_proposal_id for value in self.proposals)
        if proposal_ids != tuple(sorted(set(proposal_ids))):
            raise ValueError("crop proposals must be sorted and unique")
        grouped: dict[str, list[LocalImageTrainingCropProposal]] = {}
        for proposal in self.proposals:
            grouped.setdefault(proposal.source_anchor_id, []).append(proposal)
        if set(grouped) & set(self.holdout_source_anchor_ids):
            raise ValueError("crop proposals contain a holdout source anchor")
        for proposals in grouped.values():
            ranks = tuple(sorted(value.candidate_rank for value in proposals))
            if ranks != tuple(range(1, len(proposals) + 1)):
                raise ValueError("crop proposal ranks must be contiguous per anchor")
            first = proposals[0]
            stable = (
                first.item_revision_id,
                first.extraction_result,
                first.visual_pattern_ids,
                first.source_page_image,
                first.physical_page,
                first.context_bounding_box,
                first.rights_policy,
                first.representation_kind,
                first.rendering_mode,
                first.visual_features,
            )
            if any(
                (
                    value.item_revision_id,
                    value.extraction_result,
                    value.visual_pattern_ids,
                    value.source_page_image,
                    value.physical_page,
                    value.context_bounding_box,
                    value.rights_policy,
                    value.representation_kind,
                    value.rendering_mode,
                    value.visual_features,
                )
                != stable
                for value in proposals[1:]
            ):
                raise ValueError("crop proposals for one anchor have drifted source identity")
        omission_keys = tuple(
            (value.item_revision_id, value.source_anchor_id, value.reason)
            for value in self.omissions
        )
        if omission_keys != tuple(sorted(set(omission_keys))):
            raise ValueError("crop proposal omissions must be sorted and unique")
        if set(grouped) & {value.source_anchor_id for value in self.omissions}:
            raise ValueError("crop proposal anchors and omissions must be disjoint")
        population = training_crop_proposal_population_sha256(
            source_snapshot=self.source_snapshot,
            training_authorization=self.training_authorization,
            holdout_evaluation_plan=self.holdout_evaluation_plan,
            holdout_sample_ids=self.holdout_sample_ids,
            holdout_source_anchor_ids=self.holdout_source_anchor_ids,
            selection_query_revision=self.selection_query_revision,
            locator_revision=self.locator_revision,
            proposals=self.proposals,
            omissions=self.omissions,
        )
        if self.proposal_population_sha256 != population:
            raise ValueError("crop proposal population hash mismatch")
        if self.proposal_set_id != (
            "imgcropproposalset_" + population.removeprefix("sha256:")[:32]
        ):
            raise ValueError("crop proposal-set ID does not bind its population")
        expected = content_sha256(self.model_dump(mode="json", exclude={"proposal_set_sha256"}))
        if self.proposal_set_sha256 != expected:
            raise ValueError("crop proposal-set hash mismatch")
        return self


class LocalImageCropLocatorResult(FrozenModel):
    """Typed local result; canonical publication remains an Orchestrator responsibility."""

    schema_version: Literal["local-image-crop-locator-result/1.0"]
    locator_run_id: str = Field(pattern=r"^imgcroplocator_[0-9a-f]{32}$")
    command_sha256: Sha256
    status: Literal["SUCCEEDED", "FAILED"]
    proposal_set: LocalImageTrainingCropProposalSet | None
    error_code: str | None = Field(pattern=r"^IMAGE_TRAINING_[A-Z0-9_]{3,96}$")
    completed_at: datetime
    result_sha256: Sha256

    @field_validator("completed_at")
    @classmethod
    def utc_completion(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_result_is_coherent(self) -> LocalImageCropLocatorResult:
        if self.status == "SUCCEEDED":
            if self.proposal_set is None or self.error_code is not None:
                raise ValueError("successful crop locator result requires only a proposal set")
        elif self.proposal_set is not None or self.error_code is None:
            raise ValueError("failed crop locator result requires only an error code")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("crop locator result hash mismatch")
        return self


def validate_crop_locator_result(
    command: LocalImageCropLocatorCommand,
    result: LocalImageCropLocatorResult,
) -> None:
    if (
        result.locator_run_id != command.locator_run_id
        or result.command_sha256 != command.command_sha256
        or result.completed_at < command.created_at
    ):
        raise ValueError("crop locator result does not bind the command")
    if result.status != "SUCCEEDED" or result.proposal_set is None:
        return
    proposal_set = result.proposal_set
    if (
        proposal_set.source_snapshot != command.source_snapshot
        or proposal_set.training_authorization != command.training_authorization
        or proposal_set.holdout_evaluation_plan != command.holdout_evaluation_plan
        or proposal_set.holdout_sample_ids != command.holdout_sample_ids
        or proposal_set.holdout_source_anchor_ids != command.holdout_source_anchor_ids
        or proposal_set.selection_query_revision != command.selection_query_revision
        or proposal_set.locator_revision != command.locator_revision
        or proposal_set.created_at != command.created_at
        or proposal_set.created_by != command.created_by
    ):
        raise ValueError("crop locator proposal set does not bind the command")
    output_sources = {
        (
            value.item_revision_id,
            value.source_anchor_id,
            value.extraction_result,
            value.source_page_image,
        )
        for value in proposal_set.proposals
    }
    expected_sources = {
        (
            value.item_revision_id,
            value.source_anchor_id,
            value.extraction_result,
            value.source_page_image,
        )
        for value in command.sources
    }
    output_omissions = {
        content_sha256(value.model_dump(mode="json")) for value in proposal_set.omissions
    }
    preliminary = {
        content_sha256(value.model_dump(mode="json")) for value in command.preliminary_omissions
    }
    if not output_sources <= expected_sources or not preliminary <= output_omissions:
        raise ValueError("crop locator output contains an unbound source")
    output_anchor_ids = {value[1] for value in output_sources} | {
        value.source_anchor_id for value in proposal_set.omissions
    }
    expected_anchor_ids = {value.source_anchor_id for value in command.sources} | {
        value.source_anchor_id for value in command.preliminary_omissions
    }
    if output_anchor_ids != expected_anchor_ids:
        raise ValueError("crop locator output does not cover the command population")


class LocalImageTrainingCropReviewEntry(FrozenModel):
    source_anchor_id: str = Field(pattern=r"^assessmentanchor_[0-9a-f]{32}$")
    proposal_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
    decision: Literal["PENDING", "ELIGIBLE", "EXCLUDED"]
    selected_proposal_id: str | None = Field(pattern=r"^imgcropproposal_[0-9a-f]{32}$")
    exclusion_reasons: tuple[ImageTrainingCropExclusionReason, ...] = Field(max_length=16)
    caption_en: str | None = Field(
        min_length=3,
        max_length=180,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9 ,.'()/_-]{2,179}$",
    )
    caption_sha256: Sha256 | None

    @model_validator(mode="after")
    def decision_is_coherent(self) -> LocalImageTrainingCropReviewEntry:
        if self.proposal_ids != tuple(sorted(set(self.proposal_ids))) or any(
            re.fullmatch(r"imgcropproposal_[0-9a-f]{32}", value) is None
            for value in self.proposal_ids
        ):
            raise ValueError("crop review proposal IDs must be valid and sorted")
        if self.exclusion_reasons != tuple(sorted(set(self.exclusion_reasons))):
            raise ValueError("crop review exclusion reasons must be sorted and unique")
        if self.decision == "ELIGIBLE":
            if (
                self.selected_proposal_id not in self.proposal_ids
                or self.exclusion_reasons
                or self.caption_en is None
                or self.caption_sha256 != text_sha256(self.caption_en)
            ):
                raise ValueError("eligible crop review requires one selected proposal and caption")
        elif self.decision == "EXCLUDED":
            if (
                self.selected_proposal_id is not None
                or not self.exclusion_reasons
                or self.caption_en is not None
                or self.caption_sha256 is not None
            ):
                raise ValueError("excluded crop review requires only exclusion reasons")
        elif (
            self.selected_proposal_id is not None
            or self.exclusion_reasons
            or self.caption_en is not None
            or self.caption_sha256 is not None
        ):
            raise ValueError("pending crop review cannot carry a decision")
        return self


def _eligible_crop_review_sha256(
    entries: tuple[LocalImageTrainingCropReviewEntry, ...],
) -> Sha256:
    return content_sha256(
        [
            {
                "source_anchor_id": value.source_anchor_id,
                "selected_proposal_id": value.selected_proposal_id,
                "caption_en": value.caption_en,
                "caption_sha256": value.caption_sha256,
            }
            for value in entries
            if value.decision == "ELIGIBLE"
        ]
    )


class LocalImageTrainingCropReview(FrozenModel):
    schema_version: Literal["local-image-training-crop-review/1.0"]
    crop_review_id: str = Field(pattern=r"^imgcropreview_[0-9a-f]{32}$")
    review_state: Literal["DRAFT", "FINAL"]
    proposal_set: ImageEvaluationArtifactMember
    proposal_set_sha256: Sha256
    source_snapshot: ImageEvaluationSourceSnapshot
    proposal_population_sha256: Sha256
    entries: tuple[LocalImageTrainingCropReviewEntry, ...] = Field(
        min_length=1,
        max_length=4096,
    )
    eligible_proposal_set_sha256: Sha256
    reviewed_at: datetime
    reviewed_by: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:@-]+$",
    )
    review_sha256: Sha256

    @field_validator("reviewed_at")
    @classmethod
    def utc_review(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_review_is_coherent(self) -> LocalImageTrainingCropReview:
        _require_pointer(
            self.proposal_set,
            schema_ref=CROP_PROPOSAL_SET_SCHEMA_REF,
            member_path="manifests/crop-proposals.json",
        )
        anchors = tuple(value.source_anchor_id for value in self.entries)
        if anchors != tuple(sorted(set(anchors))):
            raise ValueError("crop review entries must be sorted by unique source anchor")
        if self.review_state == "FINAL" and any(
            value.decision == "PENDING" for value in self.entries
        ):
            raise ValueError("final crop review cannot contain pending entries")
        if self.eligible_proposal_set_sha256 != _eligible_crop_review_sha256(self.entries):
            raise ValueError("eligible crop proposal-set hash mismatch")
        identity = self.proposal_population_sha256.removeprefix("sha256:")
        if self.crop_review_id != "imgcropreview_" + identity[:32]:
            raise ValueError("crop review ID does not bind the proposal population")
        expected = content_sha256(self.model_dump(mode="json", exclude={"review_sha256"}))
        if self.review_sha256 != expected:
            raise ValueError("crop review hash mismatch")
        return self


def validate_training_crop_review(
    proposal_set: LocalImageTrainingCropProposalSet,
    review: LocalImageTrainingCropReview,
) -> None:
    if (
        review.source_snapshot != proposal_set.source_snapshot
        or review.proposal_population_sha256 != proposal_set.proposal_population_sha256
        or review.proposal_set_sha256 != proposal_set.proposal_set_sha256
        or review.proposal_set.sha256 != content_sha256(proposal_set.model_dump(mode="json"))
    ):
        raise ValueError("crop review does not bind the exact proposal set")
    grouped: dict[str, list[str]] = {}
    for proposal in proposal_set.proposals:
        grouped.setdefault(proposal.source_anchor_id, []).append(proposal.crop_proposal_id)
    expected = {anchor: tuple(sorted(proposal_ids)) for anchor, proposal_ids in grouped.items()}
    actual = {entry.source_anchor_id: entry.proposal_ids for entry in review.entries}
    if actual != expected:
        raise ValueError("crop review entries do not cover the exact proposal population")


class LocalImageTrainingCropMember(FrozenModel):
    member_path: str = Field(
        pattern=r"^samples/imgtrainsample_[0-9a-f]{32}\.png$",
    )
    media_type: Literal["image/png"]
    width_px: Literal[768]
    height_px: Literal[512]
    size_bytes: int = Field(ge=1, le=8 * 1024 * 1024)
    sha256: Sha256


class LocalImageTrainingSample(FrozenModel):
    training_sample_id: str = Field(pattern=r"^imgtrainsample_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    extraction_result: ImageEvaluationArtifactMember
    source_anchor_id: str = Field(pattern=r"^assessmentanchor_[0-9a-f]{32}$")
    visual_pattern_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    source_page_image: ImageEvaluationArtifactMember
    bounding_box: ImageEvaluationBoundingBox
    rights_policy: ImageTrainingRightsPolicy
    representation_kind: Literal["COMPOSITE", "PHOTOGRAPH"]
    rendering_mode: Literal["MIXED", "RASTER"]
    crop_member: LocalImageTrainingCropMember
    caption_en: str = Field(
        min_length=3,
        max_length=180,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9 ,.'()/_-]{2,179}$",
    )
    caption_sha256: Sha256
    perceptual_hash: str = Field(pattern=r"^[0-9a-f]{16}$")

    @model_validator(mode="after")
    def source_and_crop_are_coherent(self) -> LocalImageTrainingSample:
        if self.source_page_image.media_type != "image/png":
            raise ValueError("training source page image must be PNG")
        expected_member = f"samples/{self.training_sample_id}.png"
        if self.crop_member.member_path != expected_member:
            raise ValueError("training crop path does not bind the sample identity")
        if self.caption_sha256 != text_sha256(self.caption_en):
            raise ValueError("training caption hash mismatch")
        if self.visual_pattern_ids != tuple(sorted(set(self.visual_pattern_ids))) or any(
            re.fullmatch(r"visualpattern_[0-9a-f]{32}", value) is None
            for value in self.visual_pattern_ids
        ):
            raise ValueError("training visual pattern IDs must be valid, sorted, and unique")
        return self


class LocalImageTrainingCandidate(FrozenModel):
    candidate_id: str = Field(pattern=r"^imgtraincandidate_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    extraction_result: ImageEvaluationArtifactMember
    source_anchor_id: str = Field(pattern=r"^assessmentanchor_[0-9a-f]{32}$")
    visual_pattern_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    source_page_image: ImageEvaluationArtifactMember
    physical_page: int = Field(ge=1, le=100_000)
    bounding_box: ImageEvaluationBoundingBox
    rights_policy: ImageTrainingRightsPolicy
    representation_kind: Literal["COMPOSITE", "PHOTOGRAPH"]
    rendering_mode: Literal["MIXED", "RASTER"]
    caption_en: str = Field(
        min_length=3,
        max_length=180,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9 ,.'()/_-]{2,179}$",
    )
    caption_sha256: Sha256

    @model_validator(mode="after")
    def candidate_is_coherent(self) -> LocalImageTrainingCandidate:
        if self.source_page_image.media_type != "image/png":
            raise ValueError("training candidate source page image must be PNG")
        if self.caption_sha256 != text_sha256(self.caption_en):
            raise ValueError("training candidate caption hash mismatch")
        if self.visual_pattern_ids != tuple(sorted(set(self.visual_pattern_ids))) or any(
            re.fullmatch(r"visualpattern_[0-9a-f]{32}", value) is None
            for value in self.visual_pattern_ids
        ):
            raise ValueError("candidate visual pattern IDs must be valid, sorted, and unique")
        return self


ImageTrainingExclusionReason = Literal[
    "AMBIGUOUS_CROP",
    "ANSWER_OR_EXPLANATION_CONTENT",
    "AUTHORITATIVE_GEOMETRY",
    "EMBEDDED_LABEL_OR_VALUE",
    "FULL_PAGE",
    "HOLDOUT_OR_NEAR_DUPLICATE",
    "HUMAN_SUBJECT",
    "ITEM_NUMBER_OR_PUBLISHER_MARK",
    "TABLE_OR_GRAPH",
    "UNAUTHORIZED_SOURCE",
    "UNSUITABLE_OTHER",
]


class LocalImageTrainingEligibilityEntry(FrozenModel):
    candidate_id: str = Field(pattern=r"^imgtraincandidate_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    extraction_result: ImageEvaluationArtifactMember
    source_anchor_id: str = Field(pattern=r"^assessmentanchor_[0-9a-f]{32}$")
    visual_pattern_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    source_page_image: ImageEvaluationArtifactMember
    physical_page: int = Field(ge=1, le=100_000)
    bounding_box: ImageEvaluationBoundingBox
    rights_policy: ImageTrainingRightsPolicy
    representation_kind: Literal["COMPOSITE", "PHOTOGRAPH"]
    rendering_mode: Literal["MIXED", "RASTER"]
    decision: Literal["PENDING", "ELIGIBLE", "EXCLUDED"]
    exclusion_reasons: tuple[ImageTrainingExclusionReason, ...] = Field(max_length=16)
    caption_en: str | None = Field(
        min_length=3,
        max_length=180,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9 ,.'()/_-]{2,179}$",
    )
    caption_sha256: Sha256 | None

    @model_validator(mode="after")
    def decision_is_coherent(self) -> LocalImageTrainingEligibilityEntry:
        if self.source_page_image.media_type != "image/png":
            raise ValueError("eligibility source page image must be PNG")
        if self.exclusion_reasons != tuple(sorted(self.exclusion_reasons)) or len(
            self.exclusion_reasons
        ) != len(set(self.exclusion_reasons)):
            raise ValueError("eligibility exclusion reasons must be uniquely sorted")
        if self.visual_pattern_ids != tuple(sorted(set(self.visual_pattern_ids))) or any(
            re.fullmatch(r"visualpattern_[0-9a-f]{32}", value) is None
            for value in self.visual_pattern_ids
        ):
            raise ValueError("eligibility visual pattern IDs must be valid, sorted, and unique")
        if self.decision == "ELIGIBLE":
            if (
                self.exclusion_reasons
                or self.caption_en is None
                or self.caption_sha256 != text_sha256(self.caption_en)
            ):
                raise ValueError("eligible training image requires one exact caption")
        elif self.decision == "EXCLUDED" and (
            not self.exclusion_reasons
            or self.caption_en is not None
            or self.caption_sha256 is not None
        ):
            raise ValueError("excluded training image requires only exclusion reasons")
        elif self.decision == "PENDING" and (
            self.exclusion_reasons or self.caption_en is not None or self.caption_sha256 is not None
        ):
            raise ValueError("pending training image cannot carry a decision or caption")
        return self

    def candidate(self) -> LocalImageTrainingCandidate:
        if self.decision != "ELIGIBLE" or self.caption_en is None or self.caption_sha256 is None:
            raise ValueError("excluded review entry is not a training candidate")
        return LocalImageTrainingCandidate.model_validate(
            self.model_dump(
                mode="json",
                exclude={"decision", "exclusion_reasons"},
            )
        )


class LocalImageTrainingProjectionOmission(FrozenModel):
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    extraction_result: ImageEvaluationArtifactMember
    source_anchor_id: str = Field(pattern=r"^assessmentanchor_[0-9a-f]{32}$")
    visual_pattern_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    exclusion_reasons: tuple[ImageTrainingExclusionReason, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def omission_is_coherent(self) -> LocalImageTrainingProjectionOmission:
        if self.visual_pattern_ids != tuple(sorted(set(self.visual_pattern_ids))) or any(
            re.fullmatch(r"visualpattern_[0-9a-f]{32}", value) is None
            for value in self.visual_pattern_ids
        ):
            raise ValueError("omitted visual pattern IDs must be valid, sorted, and unique")
        if self.exclusion_reasons != tuple(sorted(set(self.exclusion_reasons))):
            raise ValueError("omission exclusion reasons must be sorted and unique")
        return self


def training_eligibility_population_sha256(
    *,
    source_snapshot: ImageEvaluationSourceSnapshot,
    holdout_evaluation_plan: ImageEvaluationArtifactMember,
    holdout_sample_ids: tuple[str, ...],
    holdout_source_anchor_ids: tuple[str, ...],
    selection_query_revision: str,
    eligibility_policy_revision: str,
    entries: tuple[LocalImageTrainingEligibilityEntry, ...],
    projection_omissions: tuple[LocalImageTrainingProjectionOmission, ...],
) -> Sha256:
    """Hash the immutable review population without mutable human decisions."""

    population_entries = tuple(
        entry.model_dump(
            mode="json",
            exclude={"decision", "exclusion_reasons", "caption_en", "caption_sha256"},
        )
        for entry in entries
    )
    return content_sha256(
        {
            "source_snapshot": source_snapshot.model_dump(mode="json"),
            "holdout_evaluation_plan": holdout_evaluation_plan.model_dump(mode="json"),
            "holdout_sample_ids": holdout_sample_ids,
            "holdout_source_anchor_ids": holdout_source_anchor_ids,
            "selection_query_revision": selection_query_revision,
            "eligibility_policy_revision": eligibility_policy_revision,
            "entries": population_entries,
            "projection_omissions": tuple(
                omission.model_dump(mode="json") for omission in projection_omissions
            ),
        }
    )


class LocalImageTrainingEligibilityReview(FrozenModel):
    schema_version: Literal["local-image-training-eligibility-review/1.0"]
    review_id: str = Field(pattern=r"^imgtrainreview_[0-9a-f]{32}$")
    review_state: Literal["DRAFT", "FINAL"]
    source_snapshot: ImageEvaluationSourceSnapshot
    holdout_evaluation_plan: ImageEvaluationArtifactMember
    holdout_sample_ids: tuple[str, ...] = Field(min_length=12, max_length=12)
    holdout_source_anchor_ids: tuple[str, ...] = Field(min_length=12, max_length=12)
    selection_query_revision: Literal["local-image-lora-candidate-query/1.0"]
    eligibility_policy_revision: Literal["local-image-lora-eligibility/1.0"]
    entries: tuple[LocalImageTrainingEligibilityEntry, ...] = Field(
        min_length=0,
        max_length=4096,
    )
    projection_omissions: tuple[LocalImageTrainingProjectionOmission, ...] = Field(max_length=4096)
    candidate_population_sha256: Sha256
    eligible_candidate_set_sha256: Sha256
    reviewed_at: datetime
    reviewed_by: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:@-]+$",
    )
    review_sha256: Sha256

    @field_validator("reviewed_at")
    @classmethod
    def utc_review(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_review_is_coherent(self) -> LocalImageTrainingEligibilityReview:
        _require_pointer(
            self.holdout_evaluation_plan,
            schema_ref=EVALUATION_PLAN_SCHEMA_REF,
            member_path="manifests/evaluation-plan.json",
        )
        for values, label in (
            (self.holdout_sample_ids, "holdout samples"),
            (self.holdout_source_anchor_ids, "holdout source anchors"),
        ):
            if values != tuple(sorted(values)) or len(values) != len(set(values)):
                raise ValueError(f"{label} must be uniquely sorted")
        candidate_ids = tuple(entry.candidate_id for entry in self.entries)
        anchors = tuple(entry.source_anchor_id for entry in self.entries)
        if candidate_ids != tuple(sorted(candidate_ids)) or len(candidate_ids) != len(
            set(candidate_ids)
        ):
            raise ValueError("eligibility entries must be uniquely sorted")
        if len(anchors) != len(set(anchors)):
            raise ValueError("eligibility source anchors must be unique")
        omission_keys = tuple(
            (omission.item_revision_id, omission.source_anchor_id)
            for omission in self.projection_omissions
        )
        if omission_keys != tuple(sorted(omission_keys)) or len(omission_keys) != len(
            set(omission_keys)
        ):
            raise ValueError("projection omissions must be uniquely sorted")
        if set(anchors) & {omission.source_anchor_id for omission in self.projection_omissions}:
            raise ValueError("reviewed and omitted source anchors must be disjoint")
        population_sha256 = training_eligibility_population_sha256(
            source_snapshot=self.source_snapshot,
            holdout_evaluation_plan=self.holdout_evaluation_plan,
            holdout_sample_ids=self.holdout_sample_ids,
            holdout_source_anchor_ids=self.holdout_source_anchor_ids,
            selection_query_revision=self.selection_query_revision,
            eligibility_policy_revision=self.eligibility_policy_revision,
            entries=self.entries,
            projection_omissions=self.projection_omissions,
        )
        if self.candidate_population_sha256 != population_sha256:
            raise ValueError("training candidate-population hash mismatch")
        if self.review_id != "imgtrainreview_" + population_sha256.removeprefix("sha256:")[:32]:
            raise ValueError("training review ID does not bind its candidate population")
        if self.review_state == "FINAL" and any(
            entry.decision == "PENDING" for entry in self.entries
        ):
            raise ValueError("final eligibility review cannot contain pending entries")
        eligible = [
            entry.candidate().model_dump(mode="json")
            for entry in self.entries
            if entry.decision == "ELIGIBLE"
        ]
        if self.eligible_candidate_set_sha256 != content_sha256(eligible):
            raise ValueError("eligible candidate-set hash mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"review_sha256"}))
        if self.review_sha256 != expected:
            raise ValueError("eligibility review hash mismatch")
        return self


class LocalImageTrainingCandidateInventory(FrozenModel):
    schema_version: Literal["local-image-training-candidate-inventory/1.0"]
    inventory_id: str = Field(pattern=r"^imgtraininventory_[0-9a-f]{32}$")
    source_snapshot: ImageEvaluationSourceSnapshot
    holdout_evaluation_plan: ImageEvaluationArtifactMember
    holdout_sample_ids: tuple[str, ...] = Field(min_length=12, max_length=12)
    holdout_source_anchor_ids: tuple[str, ...] = Field(min_length=12, max_length=12)
    candidates: tuple[LocalImageTrainingCandidate, ...] = Field(min_length=1, max_length=4096)
    created_at: datetime
    created_by: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:@-]+$",
    )
    inventory_sha256: Sha256

    @field_validator("holdout_sample_ids")
    @classmethod
    def valid_holdout_samples(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        pattern = re.compile(r"^imgsample_[0-9a-f]{32}$")
        if any(pattern.fullmatch(item) is None for item in value):
            raise ValueError("invalid holdout sample identity")
        return value

    @field_validator("holdout_source_anchor_ids")
    @classmethod
    def valid_holdout_anchors(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        pattern = re.compile(r"^assessmentanchor_[0-9a-f]{32}$")
        if any(pattern.fullmatch(item) is None for item in value):
            raise ValueError("invalid holdout source anchor identity")
        return value

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_inventory_is_coherent(self) -> LocalImageTrainingCandidateInventory:
        _require_pointer(
            self.holdout_evaluation_plan,
            schema_ref=EVALUATION_PLAN_SCHEMA_REF,
            member_path="manifests/evaluation-plan.json",
        )
        for values, label in (
            (self.holdout_sample_ids, "holdout samples"),
            (self.holdout_source_anchor_ids, "holdout source anchors"),
        ):
            if values != tuple(sorted(values)) or len(values) != len(set(values)):
                raise ValueError(f"{label} must be uniquely sorted")
        candidate_ids = tuple(candidate.candidate_id for candidate in self.candidates)
        if candidate_ids != tuple(sorted(candidate_ids)) or len(candidate_ids) != len(
            set(candidate_ids)
        ):
            raise ValueError("training candidates must be uniquely sorted")
        anchors = tuple(candidate.source_anchor_id for candidate in self.candidates)
        if len(anchors) != len(set(anchors)):
            raise ValueError("training candidate source anchors must be unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"inventory_sha256"}))
        if self.inventory_sha256 != expected:
            raise ValueError("training candidate inventory hash mismatch")
        return self


class LocalImageTrainingDatasetManifest(FrozenModel):
    schema_version: Literal["local-image-training-dataset-manifest/1.0"]
    dataset_id: str = Field(pattern=r"^imgdataset_[0-9a-f]{32}$")
    dataset_revision_id: str = Field(pattern=r"^imgdatasetrev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1, le=100_000)
    previous_revision_id: str | None = Field(pattern=r"^imgdatasetrev_[0-9a-f]{32}$")
    source_snapshot: ImageEvaluationSourceSnapshot
    training_authorization: ImageEvaluationArtifactMember
    eligibility_review: ImageEvaluationArtifactMember
    candidate_inventory: ImageEvaluationArtifactMember
    base_model: LocalImageModelPointer
    eligibility_policy_revision: Literal["local-image-lora-eligibility/1.0"]
    holdout_evaluation_plan: ImageEvaluationArtifactMember
    holdout_sample_ids: tuple[str, ...] = Field(min_length=12, max_length=12)
    holdout_source_anchor_ids: tuple[str, ...] = Field(min_length=12, max_length=12)
    samples: tuple[LocalImageTrainingSample, ...] = Field(min_length=100, max_length=200)
    sample_set_sha256: Sha256
    created_at: datetime
    created_by: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:@-]+$",
    )
    dataset_sha256: Sha256

    @field_validator("holdout_sample_ids")
    @classmethod
    def valid_holdout_samples(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        pattern = re.compile(r"^imgsample_[0-9a-f]{32}$")
        if any(pattern.fullmatch(item) is None for item in value):
            raise ValueError("invalid holdout sample identity")
        return value

    @field_validator("holdout_source_anchor_ids")
    @classmethod
    def valid_holdout_anchors(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        pattern = re.compile(r"^assessmentanchor_[0-9a-f]{32}$")
        if any(pattern.fullmatch(item) is None for item in value):
            raise ValueError("invalid holdout source anchor identity")
        return value

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_dataset_is_coherent(self) -> LocalImageTrainingDatasetManifest:
        if (self.revision_number == 1) != (self.previous_revision_id is None):
            raise ValueError("training dataset revision chain is inconsistent")
        _require_pointer(
            self.training_authorization,
            schema_ref=AUTHORIZATION_SCHEMA_REF,
            member_path="manifests/training-authorization.json",
        )
        _require_pointer(
            self.eligibility_review,
            schema_ref=ELIGIBILITY_REVIEW_SCHEMA_REF,
            member_path="manifests/eligibility-review.json",
        )
        _require_pointer(
            self.candidate_inventory,
            schema_ref=CANDIDATE_INVENTORY_SCHEMA_REF,
            member_path="manifests/training-candidates.json",
        )
        _require_pointer(
            self.holdout_evaluation_plan,
            schema_ref=EVALUATION_PLAN_SCHEMA_REF,
            member_path="manifests/evaluation-plan.json",
        )
        if self.holdout_sample_ids != tuple(sorted(self.holdout_sample_ids)) or len(
            self.holdout_sample_ids
        ) != len(set(self.holdout_sample_ids)):
            raise ValueError("holdout samples must be uniquely sorted")
        if self.holdout_source_anchor_ids != tuple(sorted(self.holdout_source_anchor_ids)) or len(
            self.holdout_source_anchor_ids
        ) != len(set(self.holdout_source_anchor_ids)):
            raise ValueError("holdout source anchors must be uniquely sorted")
        sample_ids = tuple(sample.training_sample_id for sample in self.samples)
        if sample_ids != tuple(sorted(sample_ids)) or len(sample_ids) != len(set(sample_ids)):
            raise ValueError("training samples must be uniquely sorted")
        source_anchors = tuple(sample.source_anchor_id for sample in self.samples)
        if len(source_anchors) != len(set(source_anchors)):
            raise ValueError("training source anchors must be unique")
        if set(source_anchors) & set(self.holdout_source_anchor_ids):
            raise ValueError("training dataset contains a holdout source anchor")
        crop_hashes = tuple(sample.crop_member.sha256 for sample in self.samples)
        if len(crop_hashes) != len(set(crop_hashes)):
            raise ValueError("training dataset contains duplicate crop bytes")
        expected_sample_set = content_sha256(
            [sample.model_dump(mode="json") for sample in self.samples]
        )
        if self.sample_set_sha256 != expected_sample_set:
            raise ValueError("training sample-set hash mismatch")
        expected_dataset = content_sha256(self.model_dump(mode="json", exclude={"dataset_sha256"}))
        if self.dataset_sha256 != expected_dataset:
            raise ValueError("training dataset hash mismatch")
        return self


class LocalImageTrainerDependencies(FrozenModel):
    python_version: str = Field(min_length=1, max_length=64)
    torch_version: str = Field(min_length=1, max_length=64)
    diffusers_version: str = Field(min_length=1, max_length=64)
    transformers_version: str = Field(min_length=1, max_length=64)
    accelerate_version: str = Field(min_length=1, max_length=64)
    peft_version: str = Field(min_length=1, max_length=64)
    bitsandbytes_version: str = Field(min_length=1, max_length=64)


class LocalImageLoraHyperparameters(FrozenModel):
    adapter_type: Literal["UNET_LORA"]
    rank: Literal[8]
    alpha: Literal[8]
    resolution_width: Literal[768]
    resolution_height: Literal[512]
    train_batch_size: Literal[1]
    gradient_accumulation_steps: Literal[4]
    gradient_checkpointing: Literal[True]
    mixed_precision: Literal["fp16"]
    optimizer: Literal["adamw_8bit"]
    learning_rate: Literal["1e-4"]
    max_train_steps: int = Field(ge=200, le=2000)
    checkpointing_steps: int = Field(ge=100, le=500)
    random_flip: Literal[False]
    train_text_encoders: Literal[False]
    train_vae: Literal[False]


class LocalImageLoraTrainingPlan(FrozenModel):
    schema_version: Literal["local-image-lora-training-plan/1.0"]
    training_plan_id: str = Field(pattern=r"^imgtrainplan_[0-9a-f]{32}$")
    dataset_manifest: ImageEvaluationArtifactMember
    base_model: LocalImageModelPointer
    trainer_contract: Literal["eom-local-image-lora-trainer/1.0"]
    dependencies: LocalImageTrainerDependencies
    hyperparameters: LocalImageLoraHyperparameters
    seed: int = Field(ge=0, le=2**32 - 1)
    created_at: datetime
    created_by: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:@-]+$",
    )
    plan_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_plan_is_coherent(self) -> LocalImageLoraTrainingPlan:
        _require_pointer(
            self.dataset_manifest,
            schema_ref=DATASET_SCHEMA_REF,
            member_path="manifests/training-dataset.json",
        )
        if self.hyperparameters.checkpointing_steps > self.hyperparameters.max_train_steps:
            raise ValueError("checkpoint interval exceeds total training steps")
        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("LoRA training plan hash mismatch")
        return self


class LocalImageLoraAdapterFile(FrozenModel):
    relative_path: Literal["adapter_config.json", "adapter_model.safetensors"]
    size_bytes: int = Field(ge=1, le=1024 * 1024 * 1024)
    sha256: Sha256


class LocalImageLoraAdapterManifest(FrozenModel):
    schema_version: Literal["local-image-lora-adapter-manifest/1.0"]
    adapter_id: str = Field(pattern=r"^imgadapter_[0-9a-f]{32}$")
    adapter_revision_id: str = Field(pattern=r"^imgadapterrev_[0-9a-f]{32}$")
    state: Literal["CANDIDATE"]
    base_model: LocalImageModelPointer
    dataset_manifest: ImageEvaluationArtifactMember
    training_plan: ImageEvaluationArtifactMember
    files: tuple[LocalImageLoraAdapterFile, ...] = Field(min_length=2, max_length=2)
    created_at: datetime
    manifest_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_adapter_is_coherent(self) -> LocalImageLoraAdapterManifest:
        _require_pointer(
            self.dataset_manifest,
            schema_ref=DATASET_SCHEMA_REF,
            member_path="manifests/training-dataset.json",
        )
        _require_pointer(
            self.training_plan,
            schema_ref=TRAINING_PLAN_SCHEMA_REF,
            member_path="manifests/training-plan.json",
        )
        paths = tuple(item.relative_path for item in self.files)
        if paths != ("adapter_config.json", "adapter_model.safetensors"):
            raise ValueError("LoRA adapter files must be exact and uniquely sorted")
        expected = content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected:
            raise ValueError("LoRA adapter manifest hash mismatch")
        return self


class LocalImageLoraCheckpointFile(FrozenModel):
    relative_path: Literal["adapter_model.safetensors", "optimizer-rng-state.pt"]
    size_bytes: int = Field(ge=1, le=2 * 1024 * 1024 * 1024)
    sha256: Sha256


class LocalImageLoraCheckpointManifest(FrozenModel):
    schema_version: Literal["local-image-lora-checkpoint-manifest/1.0"]
    training_run_id: str = Field(pattern=r"^imgtrainrun_[0-9a-f]{32}$")
    training_plan_sha256: Sha256
    attempt: int = Field(ge=1, le=10)
    completed_steps: int = Field(ge=100, le=2000)
    micro_steps: int = Field(ge=400, le=8000)
    files: tuple[LocalImageLoraCheckpointFile, ...] = Field(min_length=2, max_length=2)
    created_at: datetime
    manifest_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_checkpoint_is_coherent(self) -> LocalImageLoraCheckpointManifest:
        paths = tuple(item.relative_path for item in self.files)
        if paths != ("adapter_model.safetensors", "optimizer-rng-state.pt"):
            raise ValueError("LoRA checkpoint files must be exact and uniquely sorted")
        expected = content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected:
            raise ValueError("LoRA checkpoint manifest hash mismatch")
        return self


class LocalImageLoraTrainingRuntime(LocalImageTrainerDependencies):
    cuda_version: str = Field(min_length=1, max_length=128)
    gpu_name: str = Field(min_length=1, max_length=128)
    compute_capability: str = Field(pattern=r"^[0-9]+\.[0-9]+$")
    peak_gpu_memory_bytes: int = Field(ge=1)


class LocalImageLoraTrainingReceipt(FrozenModel):
    schema_version: Literal["local-image-lora-training-receipt/1.0"]
    training_run_id: str = Field(pattern=r"^imgtrainrun_[0-9a-f]{32}$")
    training_plan: ImageEvaluationArtifactMember
    attempt: int = Field(ge=1, le=10)
    status: Literal["SUCCEEDED", "FAILED", "CANCELLED"]
    adapter_manifest: ImageEvaluationArtifactMember | None
    error_code: str | None = Field(pattern=r"^[A-Z][A-Z0-9_]{2,95}$")
    runtime: LocalImageLoraTrainingRuntime | None
    completed_steps: int = Field(ge=0, le=2000)
    final_loss: float | None = Field(ge=0, le=1_000_000)
    started_at: datetime
    completed_at: datetime
    receipt_sha256: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def terminal_receipt_is_coherent(self) -> LocalImageLoraTrainingReceipt:
        _require_pointer(
            self.training_plan,
            schema_ref=TRAINING_PLAN_SCHEMA_REF,
            member_path="manifests/training-plan.json",
        )
        if self.completed_at < self.started_at:
            raise ValueError("LoRA training completion precedes start")
        if self.status == "SUCCEEDED":
            if self.adapter_manifest is None or self.error_code is not None or self.runtime is None:
                raise ValueError("successful LoRA training requires only an adapter manifest")
            _require_pointer(
                self.adapter_manifest,
                schema_ref=ADAPTER_MANIFEST_SCHEMA_REF,
                member_path="manifests/adapter-manifest.json",
            )
            if self.completed_steps < 200 or self.final_loss is None:
                raise ValueError("successful LoRA training receipt is incomplete")
        elif self.adapter_manifest is not None or self.error_code is None:
            raise ValueError("failed or cancelled LoRA training requires only an error code")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("LoRA training receipt hash mismatch")
        return self


class LocalImageLoraTrainingCommand(FrozenModel):
    schema_version: Literal["local-image-lora-training-command/1.0"]
    training_run_id: str = Field(pattern=r"^imgtrainrun_[0-9a-f]{32}$")
    training_plan_pointer: ImageEvaluationArtifactMember
    training_plan_sha256: Sha256
    training_plan: LocalImageLoraTrainingPlan
    attempt: int = Field(ge=1, le=10)
    staged_plan_member: Literal["inputs/training-plan.json"]
    staged_dataset_root: Literal["inputs/dataset"]
    output_root_member: Literal["outputs"]
    checkpoint_root_member: Literal["checkpoints"]
    timeout_seconds: int = Field(ge=600, le=86_400)
    command_sha256: Sha256

    @model_validator(mode="after")
    def command_is_coherent(self) -> LocalImageLoraTrainingCommand:
        _require_pointer(
            self.training_plan_pointer,
            schema_ref=TRAINING_PLAN_SCHEMA_REF,
            member_path="manifests/training-plan.json",
        )
        if self.training_plan_sha256 != self.training_plan.plan_sha256:
            raise ValueError("LoRA training command plan hash mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"command_sha256"}))
        if self.command_sha256 != expected:
            raise ValueError("LoRA training command hash mismatch")
        return self


class LocalImageLoraTrainingWorkerResult(FrozenModel):
    schema_version: Literal["local-image-lora-training-worker-result/1.0"]
    training_run_id: str = Field(pattern=r"^imgtrainrun_[0-9a-f]{32}$")
    training_plan_pointer: ImageEvaluationArtifactMember
    training_plan_sha256: Sha256
    attempt: int = Field(ge=1, le=10)
    status: Literal["SUCCEEDED", "FAILED", "CANCELLED"]
    adapter_manifest: LocalImageLoraAdapterManifest | None
    error_code: str | None = Field(pattern=r"^[A-Z][A-Z0-9_]{2,95}$")
    runtime: LocalImageLoraTrainingRuntime | None
    completed_steps: int = Field(ge=0, le=2000)
    final_loss: float | None = Field(ge=0, le=1_000_000)
    started_at: datetime
    completed_at: datetime
    result_sha256: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def worker_result_is_coherent(self) -> LocalImageLoraTrainingWorkerResult:
        _require_pointer(
            self.training_plan_pointer,
            schema_ref=TRAINING_PLAN_SCHEMA_REF,
            member_path="manifests/training-plan.json",
        )
        if self.completed_at < self.started_at:
            raise ValueError("LoRA worker completion precedes start")
        if self.status == "SUCCEEDED":
            if self.adapter_manifest is None or self.error_code is not None or self.runtime is None:
                raise ValueError("successful LoRA worker requires only an adapter manifest")
            if self.completed_steps < 200 or self.final_loss is None:
                raise ValueError("successful LoRA worker result is incomplete")
        elif self.adapter_manifest is not None or self.error_code is None:
            raise ValueError("failed or cancelled LoRA worker requires only an error code")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("LoRA worker result hash mismatch")
        return self


def validate_training_dataset_authorization(
    dataset: LocalImageTrainingDatasetManifest,
    authorization: LocalImageTrainingAuthorization,
) -> None:
    """Validate a dataset against the exact approved rights and source snapshot."""

    if dataset.source_snapshot != authorization.source_snapshot:
        raise ValueError("training dataset source snapshot is not authorized")
    authorized = {
        policy.rights_policy_revision_id: policy for policy in authorization.rights_policies
    }
    for sample in dataset.samples:
        if authorized.get(sample.rights_policy.rights_policy_revision_id) != sample.rights_policy:
            raise ValueError("training sample lacks an exact authorized rights policy")


def validate_training_dataset_inventory(
    dataset: LocalImageTrainingDatasetManifest,
    inventory: LocalImageTrainingCandidateInventory,
) -> None:
    """Validate that every dataset sample came from one exact candidate inventory."""

    if (
        dataset.source_snapshot != inventory.source_snapshot
        or dataset.holdout_evaluation_plan != inventory.holdout_evaluation_plan
        or dataset.holdout_sample_ids != inventory.holdout_sample_ids
        or dataset.holdout_source_anchor_ids != inventory.holdout_source_anchor_ids
    ):
        raise ValueError("training dataset and candidate inventory pins do not match")
    candidates = {candidate.source_anchor_id: candidate for candidate in inventory.candidates}
    for sample in dataset.samples:
        candidate = candidates.get(sample.source_anchor_id)
        if candidate is None:
            raise ValueError("training sample is absent from the candidate inventory")
        if (
            sample.item_revision_id != candidate.item_revision_id
            or sample.extraction_result != candidate.extraction_result
            or sample.visual_pattern_ids != candidate.visual_pattern_ids
            or sample.source_page_image != candidate.source_page_image
            or sample.bounding_box != candidate.bounding_box
            or sample.rights_policy != candidate.rights_policy
            or sample.representation_kind != candidate.representation_kind
            or sample.rendering_mode != candidate.rendering_mode
            or sample.caption_en != candidate.caption_en
            or sample.caption_sha256 != candidate.caption_sha256
        ):
            raise ValueError("training sample drifts from its candidate inventory")


def validate_training_inventory_review(
    inventory: LocalImageTrainingCandidateInventory,
    review: LocalImageTrainingEligibilityReview,
) -> None:
    """Require an inventory to be exactly the eligible subset of one reviewed population."""

    if review.review_state != "FINAL":
        raise ValueError("training inventory requires a final eligibility review")
    reviewed_candidates = tuple(
        entry.candidate() for entry in review.entries if entry.decision == "ELIGIBLE"
    )
    if (
        inventory.source_snapshot != review.source_snapshot
        or inventory.holdout_evaluation_plan != review.holdout_evaluation_plan
        or inventory.holdout_sample_ids != review.holdout_sample_ids
        or inventory.holdout_source_anchor_ids != review.holdout_source_anchor_ids
        or inventory.candidates != reviewed_candidates
    ):
        raise ValueError("training inventory does not match its eligibility review")


def validate_lora_training_plan(
    plan: LocalImageLoraTrainingPlan,
    dataset: LocalImageTrainingDatasetManifest,
) -> None:
    """Validate a plan against the exact immutable dataset and base model."""

    if plan.base_model != dataset.base_model:
        raise ValueError("LoRA training plan base model does not match the dataset")


def validate_lora_training_receipt(
    receipt: LocalImageLoraTrainingReceipt,
    plan: LocalImageLoraTrainingPlan,
    adapter: LocalImageLoraAdapterManifest | None,
) -> None:
    """Validate terminal receipt linkage without resolving implicit latest revisions."""

    if receipt.status == "SUCCEEDED":
        if adapter is None or adapter.base_model != plan.base_model:
            raise ValueError("LoRA adapter does not bind the training plan base model")
    elif adapter is not None:
        raise ValueError("non-successful LoRA training cannot publish an adapter")


def validate_lora_training_worker_result(
    command: LocalImageLoraTrainingCommand,
    result: LocalImageLoraTrainingWorkerResult,
) -> None:
    """Validate one worker result against its exact orchestrator command."""

    if (
        result.training_run_id != command.training_run_id
        or result.training_plan_pointer != command.training_plan_pointer
        or result.training_plan_sha256 != command.training_plan_sha256
        or result.attempt != command.attempt
    ):
        raise ValueError("LoRA worker result does not bind the exact command")
    if result.adapter_manifest is not None and (
        result.adapter_manifest.base_model != command.training_plan.base_model
        or result.adapter_manifest.dataset_manifest != command.training_plan.dataset_manifest
        or result.adapter_manifest.training_plan != command.training_plan_pointer
    ):
        raise ValueError("LoRA worker adapter manifest drifts from the command")


def validate_lora_checkpoint_manifest(
    checkpoint: LocalImageLoraCheckpointManifest,
    command: LocalImageLoraTrainingCommand,
) -> None:
    """Bind a resumable local checkpoint to one exact run, attempt, and plan."""

    plan = command.training_plan
    if (
        checkpoint.training_run_id != command.training_run_id
        or checkpoint.training_plan_sha256 != command.training_plan_sha256
        or checkpoint.attempt != command.attempt
        or checkpoint.completed_steps >= plan.hyperparameters.max_train_steps
        or checkpoint.completed_steps % plan.hyperparameters.checkpointing_steps != 0
        or checkpoint.micro_steps
        != checkpoint.completed_steps * plan.hyperparameters.gradient_accumulation_steps
    ):
        raise ValueError("LoRA checkpoint does not bind the exact resumable command state")
