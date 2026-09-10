"""Release-specific exact-set contracts for the past-exam PDF learning completion proof."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath
from typing import Literal

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.knowledge import (
    ApprovedItemKnowledgeSourceV2,
    ApprovedPastExamItemKnowledgeSourceV3,
    AutomaticItemCurriculumAlignmentBinding,
    KnowledgeAnalysisProposalReceiptV8,
    KnowledgeAnalysisRequestV9,
    KnowledgeAnalysisResultV9,
    KnowledgeAnalysisSourceArtifactMemberV2,
    KnowledgeAnalysisWorkerProposalV7,
    KnowledgeArtifactMemberPointer,
    KnowledgeGraphProjections,
    KnowledgeGraphSnapshotManifestV8,
    KnowledgeGraphStructureManifestV5,
    validate_assessment_page_observation_anchors,
)
from eom_catalog_contracts.legacy_assessment import (
    AssessmentArtifactMemberPointer,
    AssessmentSourceBundleRevision,
    LegacyAssessmentItemProposal,
    LegacyItemCorpusCoverage,
    LegacyItemExtractionAcceptance,
    LegacyItemExtractionReceipt,
    LegacyItemExtractionRequest,
    LegacyItemExtractionResult,
    validate_legacy_item_extraction_result_for_request,
)
from eom_catalog_contracts.legacy_extraction_batch import (
    LegacyExtractionBatchWorkUnitV2,
    LegacyItemExtractionBatchManifestV2,
)
from eom_catalog_contracts.legacy_extraction_recovery import (
    LegacyItemExtractionValidationRecovery,
    derive_legacy_item_extraction_recovery_successor,
)
from eom_catalog_contracts.legacy_item_corpus_completion import (
    LegacyExtractionResultIdentityCollisionMember,
    LegacyExtractionResultIdentityCollisions,
    derive_legacy_extraction_result_identity_collisions,
)
from eom_catalog_contracts.legacy_knowledge import LegacySourceInventoryV2
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

SHA_PATTERN = r"^sha256:[0-9a-f]{64}$"
MAX_PDF_LEARNING_ANALYSIS_RECOVERIES = 32


class ArtifactMember(FrozenModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: str = Field(min_length=1, max_length=512)
    schema_ref: str = Field(pattern=r"^eom://schemas/[A-Za-z0-9._/-]{1,220}$")
    media_type: str = Field(pattern=r"^[a-z0-9][a-z0-9.+-]*/[A-Za-z0-9][A-Za-z0-9.+-]*$")
    sha256: str = Field(pattern=SHA_PATTERN)

    @field_validator("member_path")
    @classmethod
    def safe_member_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            value.startswith("/")
            or "\\" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or path.as_posix() != value
        ):
            raise ValueError("Artifact member path must be a safe relative POSIX path")
        return value


class SourceRelease(FrozenModel):
    git_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    git_tree: str = Field(pattern=r"^[0-9a-f]{40}$")
    git_archive_sha256: Sha256


class InventoryPointer(FrozenModel):
    inventory_id: str = Field(pattern=r"^legacyinventory_[0-9a-f]{32}$")
    inventory_sha256: str = Field(pattern=SHA_PATTERN)
    artifact: ArtifactMember

    @model_validator(mode="after")
    def exact_artifact_contract(self) -> InventoryPointer:
        if (
            self.artifact.schema_ref != "eom://schemas/legacy-knowledge/legacy-source-inventory/2.0"
            or self.artifact.media_type != "application/json"
        ):
            raise ValueError("inventory Artifact contract differs")
        return self


class BatchProof(FrozenModel):
    role: Literal["ORIGINAL_SCOPE", "VALIDATION_SUCCESSOR"]
    extraction_batch_id: str = Field(pattern=r"^legacybatch_[0-9a-f]{32}$")
    manifest_sha256: str = Field(pattern=SHA_PATTERN)
    manifest_artifact: ArtifactMember
    inventory_id: str = Field(pattern=r"^legacyinventory_[0-9a-f]{32}$")
    inventory_sha256: str = Field(pattern=SHA_PATTERN)
    state: Literal["COMPLETED_WITH_GAPS", "SUCCEEDED"]
    total_work_unit_count: int = Field(ge=0)
    accepted_work_unit_count: int = Field(ge=0)
    failed_work_unit_count: int = Field(ge=0)
    other_work_unit_count: int = Field(ge=0)

    @model_validator(mode="after")
    def exact_role_distribution(self) -> BatchProof:
        distribution = (
            self.state,
            self.total_work_unit_count,
            self.accepted_work_unit_count,
            self.failed_work_unit_count,
            self.other_work_unit_count,
        )
        expected = (
            ("COMPLETED_WITH_GAPS", 108, 105, 3, 0)
            if self.role == "ORIGINAL_SCOPE"
            else ("SUCCEEDED", 3, 3, 0, 0)
        )
        if distribution != expected:
            raise ValueError("batch role and terminal distribution differ")
        if (
            self.manifest_artifact.schema_ref
            != "eom://schemas/legacy-assessment/legacy-item-extraction-batch/1.1"
            or self.manifest_artifact.media_type != "application/json"
        ):
            raise ValueError("batch manifest Artifact contract differs")
        return self


class RecoveryAuthorization(FrozenModel):
    recovery_sha256: str = Field(pattern=SHA_PATTERN)
    artifact: ArtifactMember

    @model_validator(mode="after")
    def exact_artifact_contract(self) -> RecoveryAuthorization:
        if (
            self.artifact.schema_ref
            != "eom://schemas/legacy-assessment/legacy-item-extraction-validation-recovery/1.0"
            or self.artifact.media_type != "application/json"
        ):
            raise ValueError("recovery authorization Artifact contract differs")
        return self


class CorpusCoverage(FrozenModel):
    coverage_id: str = Field(pattern=r"^itemcoverage_[0-9a-f]{32}$")
    coverage_sha256: str = Field(pattern=SHA_PATTERN)
    artifact: ArtifactMember
    state: Literal["COMPLETE"]
    expected_item_count: Literal[520]
    accepted_item_count: Literal[520]
    missing_item_count: Literal[0]
    conflict_item_count: Literal[0]

    @model_validator(mode="after")
    def exact_artifact_contract(self) -> CorpusCoverage:
        if (
            self.artifact.schema_ref
            != "eom://schemas/legacy-assessment/legacy-item-corpus-coverage/1.0"
            or self.artifact.media_type != "application/json"
        ):
            raise ValueError("corpus coverage Artifact contract differs")
        return self


class PdfSource(FrozenModel):
    inventory_entry_key: str = Field(pattern=r"^legacyentry_[0-9a-f]{32}$")
    content_sha256: Sha256
    media_type: Literal["application/pdf"]
    bundle_revision_ids: tuple[str, ...] = Field(min_length=1, max_length=108)

    @field_validator("bundle_revision_ids")
    @classmethod
    def sorted_unique_bundle_revisions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(
            len(item) != 48
            or not item.startswith("assessbundlerev_")
            or any(character not in "0123456789abcdef" for character in item[16:])
            for item in value
        ):
            raise ValueError("PDF source bundle revision identity is invalid")
        if value != tuple(sorted(set(value))):
            raise ValueError("PDF source bundle revisions must be sorted and unique")
        return value


class EffectiveWorkUnit(FrozenModel):
    original_work_unit_id: str = Field(pattern=r"^legacyworkunit_[0-9a-f]{32}$")
    original_ordinal: int = Field(ge=0, le=107)
    effective_batch_id: str = Field(pattern=r"^legacybatch_[0-9a-f]{32}$")
    effective_work_unit_id: str = Field(pattern=r"^legacyworkunit_[0-9a-f]{32}$")
    effective_ordinal: int = Field(ge=0, le=107)
    recovered: bool
    bundle_id: str = Field(pattern=r"^assessbundle_[0-9a-f]{32}$")
    bundle_revision_id: str = Field(pattern=r"^assessbundlerev_[0-9a-f]{32}$")
    bundle_manifest_sha256: str = Field(pattern=SHA_PATTERN)
    occurrence_id: str = Field(pattern=r"^occurrence_[0-9a-f]{32}$")
    occurrence_revision_id: str = Field(pattern=r"^occurrev_[0-9a-f]{32}$")
    occurrence_revision_sha256: str = Field(pattern=SHA_PATTERN)
    expected_item_numbers: tuple[int, ...] = Field(min_length=1, max_length=8)
    expected_item_numbers_sha256: str = Field(pattern=SHA_PATTERN)
    extraction_request_id: str = Field(pattern=r"^itemextractreq_[0-9a-f]{32}$")
    request_sha256: str = Field(pattern=SHA_PATTERN)
    extraction_result_id: str = Field(pattern=r"^itemextractresult_[0-9a-f]{32}$")
    result_sha256: str = Field(pattern=SHA_PATTERN)
    result_artifact: ArtifactMember
    extraction_receipt_sha256: str = Field(pattern=SHA_PATTERN)
    acceptance_id: str = Field(pattern=r"^itemacceptance_[0-9a-f]{32}$")
    acceptance_sha256: str = Field(pattern=SHA_PATTERN)
    acceptance_artifact: ArtifactMember
    acceptance_state: Literal["ACCEPTED"]
    coverage_state: Literal["COMPLETE"]

    @model_validator(mode="after")
    def exact_expected_numbers_and_artifacts(self) -> EffectiveWorkUnit:
        if self.expected_item_numbers != tuple(sorted(set(self.expected_item_numbers))):
            raise ValueError("work-unit item numbers must be sorted and unique")
        expected_hash = content_sha256({"item_numbers": list(self.expected_item_numbers)})
        if self.expected_item_numbers_sha256 != expected_hash:
            raise ValueError("work-unit item-number hash differs")
        if (
            self.result_artifact.schema_ref
            != "eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0"
            or self.acceptance_artifact.schema_ref
            != "eom://schemas/legacy-assessment/legacy-item-extraction-acceptance/1.0"
            or any(
                pointer.media_type != "application/json"
                for pointer in (
                    self.result_artifact,
                    self.acceptance_artifact,
                )
            )
            or self.result_artifact.member_path != "result.json"
            or self.acceptance_artifact.member_path != "acceptance.json"
        ):
            raise ValueError("work-unit evidence Artifact contract differs")
        return self


class EffectiveExtractionDocuments(FrozenModel):
    """Resolved immutable documents for one effective accepted extraction row.

    ``extraction_receipt`` is loaded from ``ArtifactRevision.result`` JSONB; there is deliberately
    no invented receipt Artifact pointer.
    """

    effective_work_unit_id: str = Field(pattern=r"^legacyworkunit_[0-9a-f]{32}$")
    receipt_storage: Literal["ARTIFACT_REVISION_RESULT_JSONB"]
    result: LegacyItemExtractionResult
    extraction_receipt: LegacyItemExtractionReceipt
    acceptance: LegacyItemExtractionAcceptance


class EffectiveKnowledgeAnalysisDocuments(FrozenModel):
    """Exact V9 request/result/proposal evidence resolved for one accepted terminal leaf."""

    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    request_storage: Literal["KNOWLEDGE_ANALYSIS_RUN_CANONICAL_REQUEST_JSONB"]
    request: KnowledgeAnalysisRequestV9
    result_storage: Literal["ARTIFACT_REVISION_RESULT_JSONB_AND_MEMBER"]
    result: KnowledgeAnalysisResultV9
    proposal_receipt: KnowledgeAnalysisProposalReceiptV8
    proposal: KnowledgeAnalysisWorkerProposalV7


class AnalysisProof(FrozenModel):
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    predecessor_analysis_run_id: str | None = Field(
        default=None, pattern=r"^analysisrun_[0-9a-f]{32}$"
    )
    analysis_request_id: str = Field(pattern=r"^knowledgeanalysis_[0-9a-f]{32}$")
    request_sha256: str = Field(pattern=SHA_PATTERN)
    submission_sha256: str = Field(pattern=SHA_PATTERN)
    state: Literal["ACCEPTED"]
    successor_run_count: Literal[0]
    source_kind: Literal["APPROVED_ITEM_REVISION"]
    source_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    source_artifact: ArtifactMember
    preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    preset_sha256: str = Field(pattern=SHA_PATTERN)
    risk_policy_revision_id: str = Field(pattern=r"^analysisriskrev_[0-9a-f]{32}$")
    risk_policy_sha256: str = Field(pattern=SHA_PATTERN)
    accepted_result_artifact: ArtifactMember
    accepted_result_sha256: str = Field(pattern=SHA_PATTERN)

    @model_validator(mode="after")
    def exact_terminal_artifacts(self) -> AnalysisProof:
        if (
            self.source_artifact.schema_ref
            != "eom://schemas/item-registry/assessment-item-content-v1"
            or self.source_artifact.media_type != "application/json"
            or self.source_artifact.member_path != "assessment-item-content.json"
        ):
            raise ValueError("analysis source Artifact contract differs")
        if (
            self.accepted_result_artifact.schema_ref
            != "eom://schemas/knowledge/knowledge-analysis-result/9.0"
            or self.accepted_result_artifact.media_type != "application/json"
            or self.accepted_result_artifact.member_path != "evidence/accepted-result.json"
            or self.accepted_result_artifact.sha256 != self.accepted_result_sha256
        ):
            raise ValueError("analysis accepted-result Artifact pointer differs")
        return self


class GraphPlacement(FrozenModel):
    graph_id: str = Field(pattern=r"^graph_[0-9a-f]{32}$")
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    graph_snapshot_sha256: str = Field(pattern=SHA_PATTERN)
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_origin_profile_id: str = Field(pattern=r"^originprofile_[0-9a-f]{32}$")
    item_origin_profile_sha256: str = Field(pattern=SHA_PATTERN)
    extraction_acceptance_id: str = Field(pattern=r"^itemacceptance_[0-9a-f]{32}$")
    extraction_acceptance_sha256: str = Field(pattern=SHA_PATTERN)
    assessment_source_bundle_id: str = Field(pattern=r"^assessbundle_[0-9a-f]{32}$")
    assessment_source_bundle_revision_id: str = Field(pattern=r"^assessbundlerev_[0-9a-f]{32}$")
    assessment_source_bundle_sha256: str = Field(pattern=SHA_PATTERN)
    assessment_occurrence_id: str = Field(pattern=r"^occurrence_[0-9a-f]{32}$")
    assessment_occurrence_revision_id: str = Field(pattern=r"^occurrev_[0-9a-f]{32}$")
    assessment_occurrence_revision_sha256: str = Field(pattern=SHA_PATTERN)
    occurrence_display_label: str = Field(min_length=1, max_length=512)
    administration_year: int = Field(ge=1900, le=2200)
    administration_month: int = Field(ge=1, le=12)
    target_school_level: Literal["ELEMENTARY", "MIDDLE_SCHOOL", "HIGH_SCHOOL"]
    target_grade: int = Field(ge=1, le=6)
    subject_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    item_number: int = Field(ge=1, le=200)
    curriculum_unit_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
    placement_sha256: str = Field(pattern=SHA_PATTERN)
    membership_sha256: str = Field(pattern=SHA_PATTERN)

    @model_validator(mode="after")
    def exact_placement(self) -> GraphPlacement:
        maximum_grade = 6 if self.target_school_level == "ELEMENTARY" else 3
        if self.target_grade > maximum_grade:
            raise ValueError("Graph placement grade is outside its school level")
        if any(
            len(value) != 41
            or not value.startswith("currunit_")
            or any(character not in "0123456789abcdef" for character in value[9:])
            for value in self.curriculum_unit_ids
        ):
            raise ValueError("Graph placement curriculum-unit identity is invalid")
        if self.curriculum_unit_ids != tuple(sorted(set(self.curriculum_unit_ids))):
            raise ValueError("Graph placement curriculum units must be sorted and unique")
        placement_body = self.model_dump(
            mode="json",
            exclude={
                "graph_id",
                "graph_snapshot_revision_id",
                "graph_snapshot_sha256",
                "placement_sha256",
                "membership_sha256",
            },
        )
        if self.placement_sha256 != content_sha256(placement_body):
            raise ValueError("Graph placement hash does not match canonical content")
        membership_body = self.model_dump(mode="json", exclude={"membership_sha256"})
        if self.membership_sha256 != content_sha256(membership_body):
            raise ValueError("Graph placement membership hash does not match canonical content")
        return self


class RightsPolicyProof(FrozenModel):
    rights_policy_id: str = Field(pattern=r"^rightspolicy_[0-9a-f]{32}$")
    rights_policy_revision_id: str = Field(pattern=r"^rightspolicyrev_[0-9a-f]{32}$")
    rights_policy_sha256: str = Field(pattern=SHA_PATTERN)


class InstitutionalOriginProof(FrozenModel):
    item_origin_profile_id: str = Field(pattern=r"^originprofile_[0-9a-f]{32}$")
    item_origin_profile_sha256: str = Field(pattern=SHA_PATTERN)
    profile_item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    profile_item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    profile_item_manifest_sha256: str = Field(pattern=SHA_PATTERN)
    source_domain: Literal["EXTERNAL_INSTITUTION"]
    creation_method: Literal["UNKNOWN"]
    occurrence_relation_count: Literal[1]
    derivation_count: Literal[1]
    derivation_source_kind: Literal["ASSESSMENT_SOURCE_BUNDLE_REVISION"]
    derivation_relation: Literal["DIGITIZED_FROM"]
    assessment_source_bundle_id: str = Field(pattern=r"^assessbundle_[0-9a-f]{32}$")
    assessment_source_bundle_revision_id: str = Field(pattern=r"^assessbundlerev_[0-9a-f]{32}$")
    assessment_source_bundle_sha256: str = Field(pattern=SHA_PATTERN)
    bundle_revision_state: Literal["REVIEWED"]
    assessment_occurrence_id: str = Field(pattern=r"^occurrence_[0-9a-f]{32}$")
    assessment_occurrence_revision_id: str = Field(pattern=r"^occurrev_[0-9a-f]{32}$")
    assessment_occurrence_revision_sha256: str = Field(pattern=SHA_PATTERN)
    occurrence_schema_version: Literal["assessment-occurrence-revision/2.0"]
    occurrence_revision_state: Literal["REVIEWED"]
    occurrence_lifecycle_state: Literal["ACTIVE"]
    occurrence_current_revision_id: str = Field(pattern=r"^occurrev_[0-9a-f]{32}$")
    profile_rights_policy: RightsPolicyProof
    occurrence_rights_policy: RightsPolicyProof
    bundle_rights_policy: RightsPolicyProof

    @model_validator(mode="after")
    def exact_rights_and_current_occurrence(self) -> InstitutionalOriginProof:
        if not (
            self.profile_rights_policy == self.occurrence_rights_policy == self.bundle_rights_policy
        ):
            raise ValueError("institutional origin rights pointers differ")
        if self.occurrence_current_revision_id != self.assessment_occurrence_revision_id:
            raise ValueError("institutional origin occurrence is not current")
        return self


class ItemCompletion(FrozenModel):
    bundle_revision_id: str = Field(pattern=r"^assessbundlerev_[0-9a-f]{32}$")
    item_number: int = Field(ge=1, le=10000)
    effective_work_unit_id: str = Field(pattern=r"^legacyworkunit_[0-9a-f]{32}$")
    acceptance_id: str = Field(pattern=r"^itemacceptance_[0-9a-f]{32}$")
    acceptance_sha256: str = Field(pattern=SHA_PATTERN)
    item_proposal_id: str = Field(pattern=r"^itemproposal_[0-9a-f]{32}$")
    decision: Literal["ACCEPT"]
    promotion_registration_key: str = Field(
        pattern=r"^legacy-item-promotion:itemacceptance_[0-9a-f]{32}:itemproposal_[0-9a-f]{32}$"
    )
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_lifecycle_state: Literal["ACTIVE"]
    item_current_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_revision_state: Literal["APPROVED"]
    content_pack_release_id: str = Field(pattern=r"^packrel_[0-9a-f]{32}$")
    item_manifest_sha256: str = Field(pattern=SHA_PATTERN)
    item_manifest_artifact: ArtifactMember
    item_content_artifact: ArtifactMember
    item_origin_profile_id: str = Field(pattern=r"^originprofile_[0-9a-f]{32}$")
    item_origin_profile_sha256: str = Field(pattern=SHA_PATTERN)
    origin: InstitutionalOriginProof
    analysis: AnalysisProof
    graph_placement: GraphPlacement

    @model_validator(mode="after")
    def exact_item_artifacts(self) -> ItemCompletion:
        if self.promotion_registration_key != (
            f"legacy-item-promotion:{self.acceptance_id}:{self.item_proposal_id}"
        ):
            raise ValueError("promotion registration does not bind acceptance and proposal")
        if (
            self.item_manifest_artifact.schema_ref
            != "eom://schemas/item-registry/item-revision-manifest-v1"
            or self.item_manifest_artifact.media_type != "application/json"
            or self.item_manifest_artifact.member_path != "item-revision-manifest.json"
            or self.item_manifest_artifact.sha256 != self.item_manifest_sha256
        ):
            raise ValueError("Item Revision manifest Artifact pointer differs")
        if (
            self.item_content_artifact.schema_ref
            != "eom://schemas/item-registry/assessment-item-content-v1"
            or self.item_content_artifact.media_type != "application/json"
            or self.item_content_artifact.member_path != "assessment-item-content.json"
            or self.analysis.source_artifact != self.item_content_artifact
            or self.analysis.source_revision_id != self.item_revision_id
            or self.analysis.item_id != self.item_id
            or self.analysis.item_revision_id != self.item_revision_id
        ):
            raise ValueError("analysis source does not bind to the promoted Item Revision")
        origin = self.origin
        if (
            origin.item_origin_profile_id != self.item_origin_profile_id
            or origin.item_origin_profile_sha256 != self.item_origin_profile_sha256
            or origin.profile_item_id != self.item_id
            or origin.profile_item_revision_id != self.item_revision_id
            or origin.profile_item_manifest_sha256 != self.item_manifest_sha256
        ):
            raise ValueError("institutional origin does not bind to the promoted Item Revision")
        return self


class GraphSnapshot(FrozenModel):
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    corpus_key: Literal["integrated-science-textbooks"]
    corpus_lifecycle_state: Literal["ACTIVE"]
    corpus_revision_id: str = Field(pattern=r"^corpusrev_[0-9a-f]{32}$")
    corpus_source_set_sha256: str = Field(pattern=SHA_PATTERN)
    graph_id: str = Field(pattern=r"^graph_[0-9a-f]{32}$")
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    snapshot_state: Literal["PUBLISHED"]
    snapshot_sha256: str = Field(pattern=SHA_PATTERN)
    manifest_sha256: str = Field(pattern=SHA_PATTERN)
    manifest_artifact: KnowledgeArtifactMemberPointer
    projections: KnowledgeGraphProjections
    structure_manifest_sha256: str = Field(pattern=SHA_PATTERN)
    structure_manifest_artifact: KnowledgeArtifactMemberPointer
    snapshot_created_at: UtcDatetime
    observed_as_current: Literal[True]

    @model_validator(mode="after")
    def exact_artifacts(self) -> GraphSnapshot:
        if (
            self.manifest_artifact.member_path != "projections/manifest.json"
            or self.manifest_artifact.schema_ref
            != "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/8.0"
            or self.manifest_artifact.media_type != "application/json"
            or self.manifest_artifact.logical_name != "manifest.json"
            or self.manifest_artifact.sha256 != self.manifest_sha256
        ):
            raise ValueError("Graph snapshot manifest Artifact pointer differs")
        projection_values = (
            self.projections.nodes,
            self.projections.edges,
            self.projections.curriculum_closure,
            self.projections.markdown,
            self.projections.lexical_index,
        )
        if self.projections.curriculum_closure is None:
            raise ValueError("Graph V8 projection requires curriculum closure")
        concrete_projections = tuple(value for value in projection_values if value is not None)
        projection_paths = tuple(value.member_path for value in concrete_projections)
        if projection_paths != (
            "projections/nodes.jsonl",
            "projections/edges.jsonl",
            "projections/curriculum-closure.jsonl",
            "projections/graph.md",
            "projections/lexical-index.json",
        ):
            raise ValueError("Graph projection member set differs")
        projection_revisions = {
            (value.artifact_id, value.artifact_revision_id) for value in concrete_projections
        }
        if len(projection_revisions) != 1:
            raise ValueError("Graph projections do not share one Artifact Revision")
        if (
            any(
                value.schema_ref != "eom://schemas/knowledge/knowledge-graph-projection/4.0"
                for value in concrete_projections
                if value.member_path != "projections/graph.md"
            )
            or self.projections.markdown.schema_ref
            != ("eom://schemas/knowledge/knowledge-graph-markdown/1.0")
            or tuple(value.logical_name for value in concrete_projections)
            != (
                "nodes.jsonl",
                "edges.jsonl",
                "curriculum-closure.jsonl",
                "graph.md",
                "lexical-index.json",
            )
            or any(
                value.media_type != expected_media
                for value, expected_media in zip(
                    concrete_projections,
                    (
                        "application/x-ndjson",
                        "application/x-ndjson",
                        "application/x-ndjson",
                        "text/markdown",
                        "application/json",
                    ),
                    strict=True,
                )
            )
        ):
            raise ValueError("Graph projection Artifact contract differs")
        if (
            self.structure_manifest_artifact.member_path != "evidence/graph-structure-manifest.json"
            or self.structure_manifest_artifact.schema_ref
            != "eom://schemas/knowledge/knowledge-graph-structure-manifest/5.0"
            or self.structure_manifest_artifact.media_type != "application/json"
            or self.structure_manifest_artifact.logical_name != "graph-structure-manifest.json"
            or self.structure_manifest_artifact.sha256 != self.structure_manifest_sha256
        ):
            raise ValueError("Graph structure manifest Artifact pointer differs")
        revision_ids = {
            self.manifest_artifact.artifact_revision_id,
            self.projections.nodes.artifact_revision_id,
            self.structure_manifest_artifact.artifact_revision_id,
        }
        if len(revision_ids) != 3:
            raise ValueError("Graph Artifact Revision pointers must be distinct")
        return self


class GraphSnapshotDatabaseEvidence(FrozenModel):
    """Content-free projection of the current corpus/snapshot database rows.

    The application service must construct this value inside the same read-only transaction as
    the placement and snapshot-analysis evidence.  It intentionally contains no JSON payload or
    filesystem location.
    """

    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    corpus_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    corpus_lifecycle_state: Literal["ACTIVE"]
    current_corpus_revision_id: str = Field(pattern=r"^corpusrev_[0-9a-f]{32}$")
    current_graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    corpus_revision_id: str = Field(pattern=r"^corpusrev_[0-9a-f]{32}$")
    corpus_source_set_sha256: str = Field(pattern=SHA_PATTERN)
    graph_id: str = Field(pattern=r"^graph_[0-9a-f]{32}$")
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    snapshot_state: Literal["PUBLISHED"]
    ontology_version: Literal["education-knowledge-graph/1.1"]
    manifest_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    manifest_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    manifest_sha256: str = Field(pattern=SHA_PATTERN)
    projection_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    projection_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    snapshot_sha256: str = Field(pattern=SHA_PATTERN)
    created_at: UtcDatetime

    @model_validator(mode="after")
    def current_snapshot_is_exact(self) -> GraphSnapshotDatabaseEvidence:
        if (
            self.current_corpus_revision_id != self.corpus_revision_id
            or self.current_graph_snapshot_revision_id != self.graph_snapshot_revision_id
        ):
            raise ValueError("Graph database evidence is not the current corpus snapshot")
        return self


class GraphPlacementDatabaseEvidence(FrozenModel):
    """Exact columns of one ``assessment_item_occurrence_references`` row."""

    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    placement_node_id: str = Field(pattern=r"^knode_[a-z0-9][a-z0-9_-]{0,63}$")
    occurrence_node_id: str = Field(pattern=r"^knode_[a-z0-9][a-z0-9_-]{0,63}$")
    item_node_id: str = Field(pattern=r"^knode_[a-z0-9][a-z0-9_-]{0,63}$")
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    assessment_occurrence_id: str = Field(pattern=r"^occurrence_[0-9a-f]{32}$")
    assessment_occurrence_revision_id: str = Field(pattern=r"^occurrev_[0-9a-f]{32}$")
    assessment_occurrence_revision_sha256: str = Field(pattern=SHA_PATTERN)
    occurrence_display_label: str = Field(min_length=1, max_length=512)
    administration_year: int = Field(ge=1900, le=2200)
    administration_month: int = Field(ge=1, le=12)
    target_school_level: Literal["ELEMENTARY", "MIDDLE_SCHOOL", "HIGH_SCHOOL"]
    target_grade: int = Field(ge=1, le=6)
    subject_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    item_number: int = Field(ge=1, le=200)
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_origin_profile_id: str = Field(pattern=r"^originprofile_[0-9a-f]{32}$")
    extraction_acceptance_id: str = Field(pattern=r"^itemacceptance_[0-9a-f]{32}$")
    assessment_source_bundle_revision_id: str = Field(pattern=r"^assessbundlerev_[0-9a-f]{32}$")
    placement_sha256: str = Field(pattern=SHA_PATTERN)


class GraphSnapshotAnalysisDatabaseEvidence(FrozenModel):
    """Exact pointer columns of one ``knowledge_snapshot_analyses`` row."""

    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    source_kind: Literal["CONTENT_INTAKE_FILE", "APPROVED_ITEM_REVISION", "DOCUMENT_REVISION"]
    source_revision_id: str = Field(pattern=r"^(?:sourcefile|itemrev|edudocrev)_[0-9a-f]{32}$")
    source_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    source_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    source_sha256: str = Field(pattern=SHA_PATTERN)
    accepted_result_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    accepted_result_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    accepted_result_sha256: str = Field(pattern=SHA_PATTERN)


class GraphProjectionNodeEvidence(FrozenModel):
    """Only the two node projection fields needed to verify placement row node pointers."""

    node_id: str = Field(pattern=r"^knode_[a-z0-9][a-z0-9_-]{0,63}$")
    stable_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,191}$")


class Quiescence(FrozenModel):
    automation_mode: Literal["DISABLED"]
    volatile_auto_overlay_present: Literal[False]
    deployment_hold: Literal[False]
    missing_keys: Literal[0]
    conflict_keys: Literal[0]
    duplicate_expected_keys: Literal[0]
    extra_effective_keys: Literal[0]
    unpromoted_items: Literal[0]
    active_analysis_leaves: Literal[0]
    failed_analysis_leaves: Literal[0]
    duplicate_analysis_leaves: Literal[0]
    graph_missing_items: Literal[0]
    graph_duplicate_items: Literal[0]
    source_pending_work_units: Literal[0]
    promotion_pending_items: Literal[0]
    graph_pending_items: Literal[0]
    unaccounted_terminal_work_units: Literal[0]
    active_platform_jobs: Literal[0]
    active_workflows: Literal[0]
    active_workflow_commands: Literal[0]
    active_analysis_runs: Literal[0]
    slot05_held_leases: Literal[0]
    slot06_held_leases: Literal[0]


class AnalysisRecoveryLineage(FrozenModel):
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    predecessor_analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    predecessor_analysis_request_id: str = Field(pattern=r"^knowledgeanalysis_[0-9a-f]{32}$")
    predecessor_request_sha256: str = Field(pattern=SHA_PATTERN)
    predecessor_submission_sha256: str = Field(pattern=SHA_PATTERN)
    predecessor_state: Literal["FAILED"]
    predecessor_error_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    predecessor_accepted_result_present: Literal[False]
    predecessor_successor_count: Literal[1]
    successor_analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    successor_analysis_request_id: str = Field(pattern=r"^knowledgeanalysis_[0-9a-f]{32}$")
    successor_request_sha256: str = Field(pattern=SHA_PATTERN)
    successor_state: Literal["ACCEPTED"]
    lineage_sha256: str = Field(pattern=SHA_PATTERN)

    @model_validator(mode="after")
    def exact_lineage_hash(self) -> AnalysisRecoveryLineage:
        if self.predecessor_analysis_run_id == self.successor_analysis_run_id:
            raise ValueError("analysis recovery run identity was reused")
        body = self.model_dump(mode="json", exclude={"lineage_sha256"})
        if self.lineage_sha256 != content_sha256(body):
            raise ValueError("analysis recovery lineage hash differs")
        return self


class CompletionItemKey(FrozenModel):
    bundle_revision_id: str = Field(pattern=r"^assessbundlerev_[0-9a-f]{32}$")
    item_number: int = Field(ge=1, le=10000)


class PdfLearningItemCompletionShard(FrozenModel):
    """Bounded canonical component of the 520-chain completion map."""

    schema_version: Literal["eom-pdf-learning-item-completion-shard/1.0"]
    shard_index: int = Field(ge=0, le=31)
    first_key: CompletionItemKey
    last_key: CompletionItemKey
    item_count: int = Field(ge=1, le=64)
    items: tuple[ItemCompletion, ...] = Field(min_length=1, max_length=64)
    shard_sha256: Sha256

    @model_validator(mode="after")
    def exact_sorted_shard(self) -> PdfLearningItemCompletionShard:
        keys = tuple((item.bundle_revision_id, item.item_number) for item in self.items)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("completion shard item keys must be sorted and unique")
        if (
            self.item_count != len(self.items)
            or self.first_key
            != CompletionItemKey(bundle_revision_id=keys[0][0], item_number=keys[0][1])
            or self.last_key
            != CompletionItemKey(bundle_revision_id=keys[-1][0], item_number=keys[-1][1])
        ):
            raise ValueError("completion shard boundaries differ from its items")
        body = self.model_dump(mode="json", exclude={"shard_sha256"})
        if self.shard_sha256 != content_sha256(body):
            raise ValueError("completion shard self-hash differs")
        return self


class PdfLearningItemCompletionShardPointer(FrozenModel):
    """Small receipt pointer to one separately published immutable shard."""

    shard_index: int = Field(ge=0, le=31)
    first_key: CompletionItemKey
    last_key: CompletionItemKey
    item_count: int = Field(ge=1, le=64)
    shard_sha256: Sha256
    artifact: ArtifactMember

    @model_validator(mode="after")
    def exact_artifact_contract(self) -> PdfLearningItemCompletionShardPointer:
        if (
            self.artifact.member_path != f"item-completions/shard-{self.shard_index:02d}.json"
            or self.artifact.schema_ref
            != "eom://schemas/legacy-assessment/pdf-learning-item-completion-shard/1.0"
            or self.artifact.media_type != "application/json"
        ):
            raise ValueError("completion shard Artifact contract differs")
        return self


class PdfLearningCompletionReceipt(FrozenModel):
    schema_version: Literal[
        "eom-pdf-learning-completion/1.0",
        "eom-pdf-learning-completion/1.1",
        "eom-pdf-learning-completion/1.2",
    ]
    status: Literal["COMPLETE"]
    source_release: SourceRelease
    inventory: InventoryPointer
    original_batch: BatchProof
    successor_batch: BatchProof
    recovery_authorization: RecoveryAuthorization
    historical_result_identity_collisions: LegacyExtractionResultIdentityCollisions | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    corpus_coverage: CorpusCoverage
    pdf_sources: tuple[PdfSource, ...] = Field(min_length=50, max_length=50)
    effective_work_units: tuple[EffectiveWorkUnit, ...] = Field(min_length=108, max_length=108)
    item_count: Literal[520]
    item_shards: tuple[PdfLearningItemCompletionShardPointer, ...] = Field(
        min_length=9, max_length=9
    )
    graph_snapshot: GraphSnapshot
    analysis_recoveries: tuple[AnalysisRecoveryLineage, ...] = Field(
        min_length=1,
        max_length=MAX_PDF_LEARNING_ANALYSIS_RECOVERIES,
    )
    quiescence: Quiescence
    pdf_sources_sha256: str = Field(pattern=SHA_PATTERN)
    expected_item_keys_sha256: str = Field(pattern=SHA_PATTERN)
    coverage_accepted_map_sha256: str = Field(pattern=SHA_PATTERN)
    analysis_recovery_set_sha256: str = Field(pattern=SHA_PATTERN)
    completion_map_sha256: str = Field(pattern=SHA_PATTERN)
    observed_at_utc: UtcDatetime
    receipt_sha256: str = Field(pattern=SHA_PATTERN)

    @model_validator(mode="after")
    def exact_bijection_and_hashes(self) -> PdfLearningCompletionReceipt:
        if self.original_batch.role != "ORIGINAL_SCOPE":
            raise ValueError("original batch role differs")
        if self.successor_batch.role != "VALIDATION_SUCCESSOR":
            raise ValueError("successor batch role differs")
        if self.original_batch.extraction_batch_id == self.successor_batch.extraction_batch_id:
            raise ValueError("batch identities must be distinct")
        inventory_identity = (self.inventory.inventory_id, self.inventory.inventory_sha256)
        if any(
            (batch.inventory_id, batch.inventory_sha256) != inventory_identity
            for batch in (self.original_batch, self.successor_batch)
        ):
            raise ValueError("batch inventory pointer differs from completion inventory")

        pdf_keys = tuple(source.inventory_entry_key for source in self.pdf_sources)
        if pdf_keys != tuple(sorted(set(pdf_keys))):
            raise ValueError("PDF source entries must be sorted and unique")
        if self.pdf_sources_sha256 != content_sha256(
            [source.model_dump(mode="json") for source in self.pdf_sources]
        ):
            raise ValueError("PDF source-set hash differs")

        ordinals = tuple(unit.original_ordinal for unit in self.effective_work_units)
        if ordinals != tuple(range(108)):
            raise ValueError("effective work units must preserve all original ordinals")
        original_unit_ids = tuple(unit.original_work_unit_id for unit in self.effective_work_units)
        effective_unit_ids = tuple(
            unit.effective_work_unit_id for unit in self.effective_work_units
        )
        if len(set(original_unit_ids)) != 108 or len(set(effective_unit_ids)) != 108:
            raise ValueError("work-unit identities must be unique")
        try:
            identity_collisions = derive_legacy_extraction_result_identity_collisions(
                LegacyExtractionResultIdentityCollisionMember(
                    effective_batch_id=unit.effective_batch_id,
                    effective_work_unit_id=unit.effective_work_unit_id,
                    effective_ordinal=unit.effective_ordinal,
                    extraction_request_id=unit.extraction_request_id,
                    request_sha256=unit.request_sha256,
                    extraction_result_id=unit.extraction_result_id,
                    result_artifact=AssessmentArtifactMemberPointer.model_validate(
                        unit.result_artifact.model_dump(mode="json")
                    ),
                    result_sha256=unit.result_sha256,
                    extraction_receipt_sha256=unit.extraction_receipt_sha256,
                    acceptance_id=unit.acceptance_id,
                    acceptance_sha256=unit.acceptance_sha256,
                    acceptance_artifact=AssessmentArtifactMemberPointer.model_validate(
                        unit.acceptance_artifact.model_dump(mode="json")
                    ),
                )
                for unit in self.effective_work_units
            )
        except ValueError as exc:
            raise ValueError("effective non-result evidence pointers must be unique") from exc
        collision_version = self.schema_version != "eom-pdf-learning-completion/1.0"
        if collision_version != (self.historical_result_identity_collisions is not None):
            raise ValueError("completion receipt version and collision evidence differ")
        if (
            self.schema_version
            in {
                "eom-pdf-learning-completion/1.0",
                "eom-pdf-learning-completion/1.1",
            }
            and len(self.analysis_recoveries) != 4
        ):
            raise ValueError("legacy completion receipt requires exactly four analysis recoveries")
        if not collision_version and identity_collisions is not None:
            raise ValueError("effective work-unit evidence pointers must be unique")
        if identity_collisions is not None and (
            identity_collisions.collision_group_count,
            identity_collisions.collision_membership_count,
            identity_collisions.noncanonical_membership_count,
        ) != (3, 10, 7):
            raise ValueError("historical result identity collision cardinality differs")
        if identity_collisions != self.historical_result_identity_collisions:
            raise ValueError("effective result identity collisions differ from their attestation")
        recovered = tuple(unit for unit in self.effective_work_units if unit.recovered)
        if len(recovered) != 3:
            raise ValueError("exactly three original work units must be recovered")
        for unit in self.effective_work_units:
            expected_batch_id = (
                self.successor_batch.extraction_batch_id
                if unit.recovered
                else self.original_batch.extraction_batch_id
            )
            if unit.effective_batch_id != expected_batch_id:
                raise ValueError("effective work unit belongs to an unauthorized batch")
            if not unit.recovered and (
                unit.effective_work_unit_id != unit.original_work_unit_id
                or unit.effective_ordinal != unit.original_ordinal
            ):
                raise ValueError("non-recovered work unit changed identity")

        expected_keys = tuple(
            sorted(
                (unit.bundle_revision_id, item_number)
                for unit in self.effective_work_units
                for item_number in unit.expected_item_numbers
            )
        )
        if len(expected_keys) != 520 or len(set(expected_keys)) != 520:
            raise ValueError("effective work units do not define 520 unique expected keys")
        if self.expected_item_keys_sha256 != content_sha256(
            [
                {"bundle_revision_id": bundle_revision_id, "item_number": item_number}
                for bundle_revision_id, item_number in expected_keys
            ]
        ):
            raise ValueError("expected-item-key hash differs")

        covered_bundle_revisions = {unit.bundle_revision_id for unit in self.effective_work_units}
        pdf_bundle_revisions = {
            bundle_revision_id
            for source in self.pdf_sources
            for bundle_revision_id in source.bundle_revision_ids
        }
        if pdf_bundle_revisions != covered_bundle_revisions:
            raise ValueError("PDF-source and expected-bundle scopes differ")

        predecessor_ids = tuple(
            value.predecessor_analysis_run_id for value in self.analysis_recoveries
        )
        if predecessor_ids != tuple(sorted(set(predecessor_ids))):
            raise ValueError("analysis recovery predecessors must be sorted and unique")
        recovery_identity_groups = (
            tuple(value.predecessor_analysis_request_id for value in self.analysis_recoveries),
            tuple(value.successor_analysis_run_id for value in self.analysis_recoveries),
            tuple(value.successor_analysis_request_id for value in self.analysis_recoveries),
            tuple(value.item_revision_id for value in self.analysis_recoveries),
        )
        if any(len(values) != len(set(values)) for values in recovery_identity_groups):
            raise ValueError("analysis recovery lineage identities must be unique")
        if self.analysis_recovery_set_sha256 != content_sha256(
            [value.model_dump(mode="json") for value in self.analysis_recoveries]
        ):
            raise ValueError("analysis recovery set hash differs")

        shard_indices = tuple(shard.shard_index for shard in self.item_shards)
        shard_first_keys = tuple(
            (shard.first_key.bundle_revision_id, shard.first_key.item_number)
            for shard in self.item_shards
        )
        shard_last_keys = tuple(
            (shard.last_key.bundle_revision_id, shard.last_key.item_number)
            for shard in self.item_shards
        )
        if (
            shard_indices != tuple(range(9))
            or tuple(shard.item_count for shard in self.item_shards)
            != (64, 64, 64, 64, 64, 64, 64, 64, 8)
            or sum(shard.item_count for shard in self.item_shards) != self.item_count
            or any(
                first > last for first, last in zip(shard_first_keys, shard_last_keys, strict=True)
            )
            or any(
                left >= right
                for left, right in zip(shard_last_keys[:-1], shard_first_keys[1:], strict=True)
            )
            or len({shard.shard_sha256 for shard in self.item_shards}) != 9
            or len({shard.artifact.artifact_id for shard in self.item_shards}) != 9
            or len({shard.artifact.artifact_revision_id for shard in self.item_shards}) != 9
        ):
            raise ValueError("completion shard pointer set is not canonical")
        if self.observed_at_utc < self.graph_snapshot.snapshot_created_at:
            raise ValueError("completion observation predates the Graph snapshot")
        if self.receipt_sha256 != expected_receipt_sha256(self):
            raise ValueError("completion receipt self-hash differs")
        return self


def canonical_payload(receipt: PdfLearningCompletionReceipt) -> dict[str, object]:
    return receipt.model_dump(mode="json")


def expected_receipt_sha256(receipt: PdfLearningCompletionReceipt) -> str:
    payload = canonical_payload(receipt)
    return content_sha256({key: value for key, value in payload.items() if key != "receipt_sha256"})


def completion_identity_sha256(receipt: PdfLearningCompletionReceipt) -> str:
    """Return the semantic release identity, excluding mutable observation/publication details."""

    identity: dict[str, object] = {
        "source_release": receipt.source_release.model_dump(mode="json"),
        "inventory": receipt.inventory.model_dump(mode="json"),
        "original_batch": receipt.original_batch.model_dump(mode="json"),
        "successor_batch": receipt.successor_batch.model_dump(mode="json"),
        "recovery_authorization": receipt.recovery_authorization.model_dump(mode="json"),
        "corpus_coverage": receipt.corpus_coverage.model_dump(mode="json"),
        "pdf_sources_sha256": receipt.pdf_sources_sha256,
        "expected_item_keys_sha256": receipt.expected_item_keys_sha256,
        "coverage_accepted_map_sha256": receipt.coverage_accepted_map_sha256,
        "analysis_recovery_set_sha256": receipt.analysis_recovery_set_sha256,
        "completion_map_sha256": receipt.completion_map_sha256,
        "graph_snapshot": receipt.graph_snapshot.model_dump(mode="json"),
    }
    if receipt.historical_result_identity_collisions is not None:
        identity["historical_result_identity_collisions_sha256"] = (
            receipt.historical_result_identity_collisions.evidence_sha256
        )
    return content_sha256(identity)


def validate_payload(payload: dict[str, object]) -> PdfLearningCompletionReceipt:
    routes = {
        "eom-pdf-learning-completion/1.0": "pdf-learning-completion",
        "eom-pdf-learning-completion/1.1": "pdf-learning-completion-v2",
        "eom-pdf-learning-completion/1.2": "pdf-learning-completion-v3",
    }
    schema_version = payload.get("schema_version")
    route = (
        routes.get(schema_version, "pdf-learning-completion")
        if isinstance(schema_version, str)
        else "pdf-learning-completion"
    )
    validate_contract(route, payload)
    return PdfLearningCompletionReceipt.model_validate(payload)


def verify_completion_shards(
    receipt: PdfLearningCompletionReceipt,
    shards: tuple[PdfLearningItemCompletionShard, ...],
) -> tuple[ItemCompletion, ...]:
    """Resolve the bounded item components and prove the exact 520-chain bijection."""

    if tuple(shard.shard_index for shard in shards) != tuple(range(9)):
        raise ValueError("resolved completion shard order differs")
    by_index = {pointer.shard_index: pointer for pointer in receipt.item_shards}
    items: list[ItemCompletion] = []
    for shard in shards:
        pointer = by_index.get(shard.shard_index)
        payload = canonical_json_bytes(shard.model_dump(mode="json"))
        if (
            pointer is None
            or pointer.shard_sha256 != shard.shard_sha256
            or pointer.item_count != shard.item_count
            or pointer.first_key != shard.first_key
            or pointer.last_key != shard.last_key
            or pointer.artifact.sha256 != sha256_bytes(payload)
        ):
            raise ValueError("resolved completion shard differs from its receipt pointer")
        items.extend(shard.items)
    resolved = tuple(items)
    _verify_completion_items(receipt, resolved)
    return resolved


def _verify_completion_items(
    receipt: PdfLearningCompletionReceipt,
    items: tuple[ItemCompletion, ...],
) -> None:
    expected_keys = tuple(
        sorted(
            (unit.bundle_revision_id, item_number)
            for unit in receipt.effective_work_units
            for item_number in unit.expected_item_numbers
        )
    )
    item_keys = tuple((item.bundle_revision_id, item.item_number) for item in items)
    if len(items) != receipt.item_count or item_keys != expected_keys:
        raise ValueError("completion items are not the sorted expected-key bijection")

    work_units = {unit.effective_work_unit_id: unit for unit in receipt.effective_work_units}
    acceptance_proposals: set[tuple[str, str]] = set()
    item_ids: set[str] = set()
    item_revision_ids: set[str] = set()
    item_manifest_artifact_revisions: set[str] = set()
    item_content_artifact_revisions: set[str] = set()
    item_origin_profile_ids: set[str] = set()
    analysis_run_ids: set[str] = set()
    analysis_request_ids: set[str] = set()
    analysis_result_artifact_revisions: set[str] = set()
    graph_occurrence_keys: set[tuple[str, int]] = set()
    placement_hashes: set[str] = set()
    for item in items:
        unit = work_units.get(item.effective_work_unit_id)
        if (
            unit is None
            or unit.bundle_revision_id != item.bundle_revision_id
            or item.item_number not in unit.expected_item_numbers
            or unit.acceptance_id != item.acceptance_id
            or unit.acceptance_sha256 != item.acceptance_sha256
        ):
            raise ValueError("item does not resolve to its effective acceptance")
        graph = item.graph_placement
        origin = item.origin
        if (
            graph.graph_id != receipt.graph_snapshot.graph_id
            or graph.graph_snapshot_revision_id != receipt.graph_snapshot.graph_snapshot_revision_id
            or graph.graph_snapshot_sha256 != receipt.graph_snapshot.snapshot_sha256
            or graph.analysis_run_id != item.analysis.analysis_run_id
            or graph.item_id != item.item_id
            or graph.item_revision_id != item.item_revision_id
            or graph.item_origin_profile_id != item.item_origin_profile_id
            or graph.item_origin_profile_sha256 != item.item_origin_profile_sha256
            or graph.extraction_acceptance_id != item.acceptance_id
            or graph.extraction_acceptance_sha256 != item.acceptance_sha256
            or graph.assessment_source_bundle_id != unit.bundle_id
            or graph.assessment_source_bundle_revision_id != item.bundle_revision_id
            or graph.assessment_source_bundle_sha256 != unit.bundle_manifest_sha256
            or graph.assessment_occurrence_id != unit.occurrence_id
            or graph.assessment_occurrence_revision_id != unit.occurrence_revision_id
            or graph.assessment_occurrence_revision_sha256 != unit.occurrence_revision_sha256
            or graph.item_number != item.item_number
            or item.item_current_revision_id != item.item_revision_id
            or origin.assessment_source_bundle_id != unit.bundle_id
            or origin.assessment_source_bundle_revision_id != item.bundle_revision_id
            or origin.assessment_source_bundle_sha256 != unit.bundle_manifest_sha256
            or origin.assessment_occurrence_id != unit.occurrence_id
            or origin.assessment_occurrence_revision_id != unit.occurrence_revision_id
            or origin.assessment_occurrence_revision_sha256 != unit.occurrence_revision_sha256
        ):
            raise ValueError("Graph placement pointer drifts from the item chain")
        acceptance_proposals.add((item.acceptance_id, item.item_proposal_id))
        item_ids.add(item.item_id)
        item_revision_ids.add(item.item_revision_id)
        item_manifest_artifact_revisions.add(item.item_manifest_artifact.artifact_revision_id)
        item_content_artifact_revisions.add(item.item_content_artifact.artifact_revision_id)
        item_origin_profile_ids.add(item.item_origin_profile_id)
        analysis_run_ids.add(item.analysis.analysis_run_id)
        analysis_request_ids.add(item.analysis.analysis_request_id)
        analysis_result_artifact_revisions.add(
            item.analysis.accepted_result_artifact.artifact_revision_id
        )
        graph_occurrence_keys.add((graph.assessment_occurrence_revision_id, graph.item_number))
        placement_hashes.add(graph.placement_sha256)
    if any(
        len(values) != 520
        for values in (
            acceptance_proposals,
            item_ids,
            item_revision_ids,
            item_manifest_artifact_revisions,
            item_content_artifact_revisions,
            item_origin_profile_ids,
            analysis_run_ids,
            analysis_request_ids,
            analysis_result_artifact_revisions,
            graph_occurrence_keys,
            placement_hashes,
        )
    ):
        raise ValueError("completion mapping is not one-to-one")

    predecessor_ids = tuple(
        value.predecessor_analysis_run_id for value in receipt.analysis_recoveries
    )
    terminal_by_run = {item.analysis.analysis_run_id: item for item in items}
    for recovery in receipt.analysis_recoveries:
        recovered_item = terminal_by_run.get(recovery.successor_analysis_run_id)
        if (
            recovered_item is None
            or recovered_item.item_id != recovery.item_id
            or recovered_item.item_revision_id != recovery.item_revision_id
            or recovered_item.analysis.predecessor_analysis_run_id
            != recovery.predecessor_analysis_run_id
            or recovered_item.analysis.analysis_request_id != recovery.successor_analysis_request_id
            or recovered_item.analysis.request_sha256 != recovery.successor_request_sha256
        ):
            raise ValueError("analysis recovery lineage differs from its terminal leaf")
    observed_predecessors = tuple(
        sorted(
            item.analysis.predecessor_analysis_run_id
            for item in items
            if item.analysis.predecessor_analysis_run_id is not None
        )
    )
    if observed_predecessors != predecessor_ids:
        raise ValueError("analysis retry predecessor set differs from exact recovery lineage")
    if set(predecessor_ids) & set(terminal_by_run):
        raise ValueError("failed predecessor is also represented as a terminal leaf")

    accepted_map = [
        {
            "bundle_revision_id": item.bundle_revision_id,
            "item_number": item.item_number,
            "acceptance_id": item.acceptance_id,
            "acceptance_sha256": item.acceptance_sha256,
        }
        for item in items
    ]
    if receipt.coverage_accepted_map_sha256 != content_sha256(accepted_map):
        raise ValueError("coverage accepted-map hash differs")
    if receipt.completion_map_sha256 != content_sha256(
        [item.model_dump(mode="json") for item in items]
    ):
        raise ValueError("completion-map hash differs")


def verify_protocol_documents(
    receipt: PdfLearningCompletionReceipt,
    *,
    items: tuple[ItemCompletion, ...],
    effective_documents: tuple[EffectiveExtractionDocuments, ...],
    knowledge_documents: tuple[EffectiveKnowledgeAnalysisDocuments, ...],
    bundle_revisions: tuple[AssessmentSourceBundleRevision, ...],
    inventory: LegacySourceInventoryV2,
    original_manifest: LegacyItemExtractionBatchManifestV2,
    successor_manifest: LegacyItemExtractionBatchManifestV2,
    recovery: LegacyItemExtractionValidationRecovery,
    coverage: LegacyItemCorpusCoverage,
) -> None:
    """Cross-check already Pydantic-validated canonical protocol documents.

    All arguments are already schema-validated immutable contract values resolved by exact
    Artifact pointers; this function performs their release-specific cross-document comparison.
    """

    try:
        exact_successor = derive_legacy_item_extraction_recovery_successor(
            recovery, original_manifest
        )
    except ValueError as exc:
        raise ValueError("recovery successor cannot be derived exactly") from exc
    if successor_manifest != exact_successor:
        raise ValueError("successor manifest differs from the recovery-authorized derivation")

    inventory_identity = (inventory.inventory_id, inventory.inventory_sha256)
    if inventory_identity != (receipt.inventory.inventory_id, receipt.inventory.inventory_sha256):
        raise ValueError("inventory document identity differs from the receipt")
    if (
        receipt.inventory.artifact.member_path != "legacy-source-inventory.json"
        or receipt.inventory.artifact.sha256
        != sha256_bytes(canonical_json_bytes(inventory.model_dump(mode="json")) + b"\n")
    ):
        raise ValueError("inventory Artifact member bytes differ from the receipt")
    if receipt.inventory.artifact.model_dump(
        mode="json"
    ) != original_manifest.inventory_artifact.model_dump(mode="json"):
        raise ValueError("original manifest inventory Artifact differs from the receipt")
    if successor_manifest.inventory_artifact != original_manifest.inventory_artifact:
        raise ValueError("successor manifest inventory Artifact differs from original scope")
    for proof, manifest in (
        (receipt.original_batch, original_manifest),
        (receipt.successor_batch, successor_manifest),
    ):
        if (
            proof.extraction_batch_id != manifest.extraction_batch_id
            or proof.manifest_sha256 != manifest.manifest_sha256
            or proof.manifest_artifact.member_path != "legacy-item-extraction-batch.json"
            or proof.manifest_artifact.sha256
            != sha256_bytes(canonical_json_bytes(manifest.model_dump(mode="json")))
            or (proof.inventory_id, proof.inventory_sha256) != inventory_identity
            or (manifest.inventory_id, manifest.inventory_sha256) != inventory_identity
        ):
            raise ValueError("batch manifest identity differs from the receipt")

    bundle_by_revision = {
        bundle.assessment_source_bundle_revision_id: bundle for bundle in bundle_revisions
    }
    expected_bundle_revision_ids = {
        unit.request.bundle.assessment_source_bundle_revision_id
        for unit in original_manifest.work_units
    }
    if (
        len(bundle_by_revision) != len(bundle_revisions)
        or set(bundle_by_revision) != expected_bundle_revision_ids
    ):
        raise ValueError("resolved reviewed bundle revision set is not exact")
    inventory_by_entry = {entry.entry_key: entry for entry in inventory.entries}
    for unit in original_manifest.work_units:
        request = unit.request
        bundle = bundle_by_revision[request.bundle.assessment_source_bundle_revision_id]
        if (
            bundle.assessment_source_bundle_id != request.bundle.assessment_source_bundle_id
            or bundle.bundle_manifest_sha256 != request.bundle.bundle_manifest_sha256
            or bundle.state != "REVIEWED"
            or bundle.occurrence != request.occurrence
        ):
            raise ValueError("effective request differs from its reviewed bundle revision")
        member_by_id = {member.member_id: member for member in bundle.members}
        binding_by_id = {
            binding.bundle_member_id: binding for binding in unit.corpus_source_bindings
        }
        if len(member_by_id) != len(bundle.members) or set(member_by_id) != set(binding_by_id):
            raise ValueError("corpus bindings do not exactly cover the reviewed bundle")
        reviewed_members = {(member.role, member.source) for member in bundle.members}
        for page in request.page_inputs:
            if (page.source_role, page.source) not in reviewed_members:
                raise ValueError("request page source is outside its reviewed bundle")
        for materialization in request.source_materializations:
            if (
                materialization.source_role,
                materialization.source,
            ) not in reviewed_members:
                raise ValueError("request materialization is outside its reviewed bundle")
        for member_id, member in member_by_id.items():
            binding = binding_by_id[member_id]
            reviewed = binding.reviewed_inventory_source
            corpus = binding.corpus_inventory_source
            entry = inventory_by_entry.get(corpus.entry_key)
            if (
                reviewed != member.inventory_source
                or reviewed.inventory_id != bundle.inventory_id
                or reviewed.inventory_sha256 != bundle.inventory_sha256
                or member.source.sha256 != member.inventory_source.content_sha256
                or corpus.inventory_id != inventory.inventory_id
                or corpus.inventory_sha256 != inventory.inventory_sha256
                or entry is None
                or entry.content_sha256 != corpus.content_sha256
                or member.source.sha256 != corpus.content_sha256
            ):
                raise ValueError("corpus binding differs from immutable reviewed source evidence")

    if (
        recovery.predecessor_batch_id != receipt.original_batch.extraction_batch_id
        or recovery.predecessor_manifest_sha256 != receipt.original_batch.manifest_sha256
        or recovery.successor_batch_id != receipt.successor_batch.extraction_batch_id
        or recovery.recovery_sha256 != receipt.recovery_authorization.recovery_sha256
        or receipt.recovery_authorization.artifact.member_path != "validation-recovery.json"
        or receipt.recovery_authorization.artifact.sha256
        != sha256_bytes(canonical_json_bytes(recovery) + b"\n")
    ):
        raise ValueError("recovery authorization identity differs from batch lineage")

    original_units = tuple(original_manifest.work_units)
    successor_by_id = {unit.work_unit_id: unit for unit in successor_manifest.work_units}
    replacement_by_predecessor = {
        row.predecessor_work_unit_id: row for row in recovery.replacements
    }
    receipt_by_original = {
        unit.original_work_unit_id: unit for unit in receipt.effective_work_units
    }
    if len(original_units) != 108 or len(successor_by_id) != 3:
        raise ValueError("batch manifest work-unit cardinality differs")

    for original in original_units:
        observed = receipt_by_original.get(original.work_unit_id)
        if observed is None:
            raise ValueError("original work unit is missing from effective coverage")
        request = original.request
        if (
            observed.original_ordinal != original.ordinal
            or observed.bundle_id != request.bundle.assessment_source_bundle_id
            or observed.bundle_revision_id != request.bundle.assessment_source_bundle_revision_id
            or observed.bundle_manifest_sha256 != request.bundle.bundle_manifest_sha256
            or observed.expected_item_numbers != request.expected_item_numbers
            or observed.expected_item_numbers_sha256 != original.expected_item_numbers_sha256
        ):
            raise ValueError("effective work unit drifts from original expected scope")
        replacement = replacement_by_predecessor.get(original.work_unit_id)
        if (replacement is not None) != observed.recovered:
            raise ValueError("receipt recovery selection differs from authorization")
        effective = (
            successor_by_id.get(replacement.successor_work_unit_id) if replacement else original
        )
        if effective is None:
            raise ValueError("authorized successor work unit is absent")
        if replacement is not None and (
            replacement.predecessor_ordinal != original.ordinal
            or replacement.predecessor_extraction_request_id
            != original.request.extraction_request_id
            or replacement.predecessor_request_sha256 != original.request.request_sha256
            or replacement.predecessor_bundle_revision_id
            != original.request.bundle.assessment_source_bundle_revision_id
            or replacement.expected_item_numbers != original.request.expected_item_numbers
            or replacement.expected_item_numbers_sha256 != original.expected_item_numbers_sha256
            or replacement.successor_ordinal != effective.ordinal
            or replacement.successor_extraction_request_id
            != effective.request.extraction_request_id
        ):
            raise ValueError("recovery replacement drifts from original/successor manifests")
        if (
            observed.effective_work_unit_id != effective.work_unit_id
            or observed.effective_ordinal != effective.ordinal
            or observed.extraction_request_id != effective.request.extraction_request_id
            or observed.request_sha256 != effective.request.request_sha256
            or observed.bundle_revision_id
            != effective.request.bundle.assessment_source_bundle_revision_id
            or observed.expected_item_numbers != effective.request.expected_item_numbers
            or observed.expected_item_numbers_sha256 != effective.expected_item_numbers_sha256
        ):
            raise ValueError("effective extraction request differs from its manifest")

    documents_by_work_unit = {
        evidence.effective_work_unit_id: evidence for evidence in effective_documents
    }
    effective_receipt_ids = {unit.effective_work_unit_id for unit in receipt.effective_work_units}
    if (
        len(documents_by_work_unit) != len(effective_documents)
        or set(documents_by_work_unit) != effective_receipt_ids
    ):
        raise ValueError("effective extraction document set is not exact")
    manifest_units = {
        (manifest.extraction_batch_id, unit.work_unit_id): unit
        for manifest in (original_manifest, successor_manifest)
        for unit in manifest.work_units
    }
    completion_items_by_work_unit: dict[str, list[ItemCompletion]] = {}
    for completion_item in items:
        completion_items_by_work_unit.setdefault(completion_item.effective_work_unit_id, []).append(
            completion_item
        )
    result_revisions: set[str] = set()
    receipt_hashes: set[str] = set()
    acceptance_ids: set[str] = set()
    acceptance_revisions: set[str] = set()
    for observed in receipt.effective_work_units:
        evidence = documents_by_work_unit[observed.effective_work_unit_id]
        manifest_unit = manifest_units.get(
            (observed.effective_batch_id, observed.effective_work_unit_id)
        )
        if manifest_unit is None:
            raise ValueError("effective extraction manifest unit is missing")
        result = evidence.result
        extraction_receipt = evidence.extraction_receipt
        acceptance = evidence.acceptance
        try:
            validate_legacy_item_extraction_result_for_request(
                result=result, request=manifest_unit.request
            )
        except ValueError as exc:
            raise ValueError("effective result is outside its pinned request") from exc
        result_artifact_document = observed.result_artifact.model_dump(mode="json")
        if (
            evidence.receipt_storage != "ARTIFACT_REVISION_RESULT_JSONB"
            or result.extraction_result_id != observed.extraction_result_id
            or result.extraction_request_id != observed.extraction_request_id
            or result.request_sha256 != observed.request_sha256
            or result.result_sha256 != observed.result_sha256
            or observed.result_artifact.sha256 != sha256_bytes(canonical_json_bytes(result))
            or extraction_receipt.extraction_result_id != result.extraction_result_id
            or extraction_receipt.extraction_request_id != result.extraction_request_id
            or extraction_receipt.request_sha256 != result.request_sha256
            or extraction_receipt.result_artifact.model_dump(mode="json")
            != result_artifact_document
            or extraction_receipt.result_sha256 != result.result_sha256
            or extraction_receipt.observed_page_input_ids != result.observed_page_input_ids
            or extraction_receipt.item_numbers != tuple(item.item_number for item in result.items)
            or extraction_receipt.receipt_sha256 != observed.extraction_receipt_sha256
            or acceptance.acceptance_id != observed.acceptance_id
            or acceptance.acceptance_sha256 != observed.acceptance_sha256
            or acceptance.state != "ACCEPTED"
            or acceptance.coverage_state != "COMPLETE"
            or acceptance.extraction_result.artifact.model_dump(mode="json")
            != result_artifact_document
            or acceptance.extraction_result.extraction_result_id != result.extraction_result_id
            or acceptance.extraction_result.result_sha256 != result.result_sha256
            or observed.acceptance_artifact.sha256
            != sha256_bytes(canonical_json_bytes(acceptance.model_dump(mode="json")))
            or acceptance.reviewed_at < extraction_receipt.completed_at
        ):
            raise ValueError("effective result/receipt/acceptance chain differs")
        result_by_number = {item.item_number: item for item in result.items}
        decision_by_number = {
            decision.item_number: decision for decision in acceptance.item_decisions
        }
        completions = {
            item.item_number: item
            for item in completion_items_by_work_unit.get(observed.effective_work_unit_id, [])
        }
        expected_numbers = tuple(manifest_unit.request.expected_item_numbers)
        if (
            tuple(sorted(result_by_number)) != expected_numbers
            or tuple(sorted(decision_by_number)) != expected_numbers
            or tuple(sorted(completions)) != expected_numbers
            or len(result_by_number) != len(result.items)
            or len(decision_by_number) != len(acceptance.item_decisions)
        ):
            raise ValueError("effective proposal/decision/completion set is not exact")
        for item_number in expected_numbers:
            proposal = result_by_number[item_number]
            decision = decision_by_number[item_number]
            completion = completions[item_number]
            if (
                decision.decision != "ACCEPT"
                or decision.item_proposal_id != proposal.item_proposal_id
                or completion.item_proposal_id != proposal.item_proposal_id
                or completion.acceptance_id != acceptance.acceptance_id
                or completion.acceptance_sha256 != acceptance.acceptance_sha256
            ):
                raise ValueError("promotion does not bind the exact accepted proposal")
        result_revisions.add(observed.result_artifact.artifact_revision_id)
        receipt_hashes.add(extraction_receipt.receipt_sha256)
        acceptance_ids.add(acceptance.acceptance_id)
        acceptance_revisions.add(observed.acceptance_artifact.artifact_revision_id)
    if any(
        len(identity_set) != 108
        for identity_set in (
            result_revisions,
            receipt_hashes,
            acceptance_ids,
            acceptance_revisions,
        )
    ):
        raise ValueError("effective extraction document identities are not one-to-one")

    _verify_knowledge_analysis_documents(
        receipt,
        items=items,
        effective_documents=effective_documents,
        knowledge_documents=knowledge_documents,
        manifest_units=manifest_units,
    )

    pdf_bindings: dict[str, set[str]] = {}
    for unit in original_units:
        bundle_revision_id = unit.request.bundle.assessment_source_bundle_revision_id
        for binding in unit.corpus_source_bindings:
            pointer = binding.corpus_inventory_source
            entry = inventory_by_entry.get(pointer.entry_key)
            if (
                entry is None
                or pointer.inventory_id != inventory.inventory_id
                or pointer.inventory_sha256 != inventory.inventory_sha256
                or pointer.content_sha256 != entry.content_sha256
            ):
                raise ValueError("batch corpus binding does not resolve in the inventory")
            if entry.media_type == "application/pdf":
                pdf_bindings.setdefault(pointer.entry_key, set()).add(bundle_revision_id)
    expected_pdf_sources = tuple(
        (
            entry_key,
            inventory_by_entry[entry_key].content_sha256,
            tuple(sorted(bundle_revision_ids)),
        )
        for entry_key, bundle_revision_ids in sorted(pdf_bindings.items())
    )
    observed_pdf_sources = tuple(
        (
            source.inventory_entry_key,
            source.content_sha256,
            source.bundle_revision_ids,
        )
        for source in receipt.pdf_sources
    )
    if expected_pdf_sources != observed_pdf_sources or len(expected_pdf_sources) != 50:
        raise ValueError("receipt does not bind the exact 50 PDF inventory sources")

    if (
        coverage.inventory_id != receipt.inventory.inventory_id
        or coverage.inventory_sha256 != receipt.inventory.inventory_sha256
        or coverage.coverage_id != receipt.corpus_coverage.coverage_id
        or coverage.coverage_sha256 != receipt.corpus_coverage.coverage_sha256
        or coverage.state != "COMPLETE"
        or coverage.expected_item_count != 520
        or coverage.accepted_item_count != 520
        or coverage.missing_item_count != 0
        or coverage.conflict_item_count != 0
        or receipt.corpus_coverage.artifact.member_path != "coverage.json"
        or receipt.corpus_coverage.artifact.sha256 != sha256_bytes(canonical_json_bytes(coverage))
    ):
        raise ValueError("corpus coverage document is not the exact COMPLETE scope")
    bundle_coverages = tuple(coverage.bundle_coverages)
    if tuple(
        bundle.bundle.assessment_source_bundle_revision_id for bundle in bundle_coverages
    ) != tuple(
        sorted(bundle.bundle.assessment_source_bundle_revision_id for bundle in bundle_coverages)
    ):
        raise ValueError("corpus coverage bundles are not canonically sorted")
    coverage_expected = tuple(
        (bundle.bundle.assessment_source_bundle_revision_id, item_number)
        for bundle in bundle_coverages
        for item_number in bundle.expected_item_numbers
    )
    receipt_expected = tuple((item.bundle_revision_id, item.item_number) for item in items)
    if tuple(sorted(coverage_expected)) != receipt_expected:
        raise ValueError("corpus coverage expected keys differ from original scope")
    coverage_accepted = tuple(
        sorted(
            (
                bundle.bundle.assessment_source_bundle_revision_id,
                item.item_number,
                item.acceptance_id,
                item.acceptance_sha256,
            )
            for bundle in bundle_coverages
            for item in bundle.accepted_items
        )
    )
    receipt_accepted = tuple(
        (
            item.bundle_revision_id,
            item.item_number,
            item.acceptance_id,
            item.acceptance_sha256,
        )
        for item in items
    )
    if coverage_accepted != receipt_accepted:
        raise ValueError("corpus coverage acceptance map differs from completion chains")


def _verify_knowledge_analysis_documents(
    receipt: PdfLearningCompletionReceipt,
    *,
    items: tuple[ItemCompletion, ...],
    effective_documents: tuple[EffectiveExtractionDocuments, ...],
    knowledge_documents: tuple[EffectiveKnowledgeAnalysisDocuments, ...],
    manifest_units: Mapping[
        tuple[str, str],
        LegacyExtractionBatchWorkUnitV2,
    ],
) -> None:
    """Close each accepted V9 analysis source back to its own extraction and Item chain."""

    analysis_by_run = {value.analysis_run_id: value for value in knowledge_documents}
    item_by_run = {item.analysis.analysis_run_id: item for item in items}
    extraction_by_work_unit = {value.effective_work_unit_id: value for value in effective_documents}
    unit_by_work_unit = {
        value.effective_work_unit_id: value for value in receipt.effective_work_units
    }
    if (
        len(analysis_by_run) != len(knowledge_documents)
        or set(analysis_by_run) != set(item_by_run)
        or len(analysis_by_run) != 520
    ):
        raise ValueError("terminal knowledge-analysis document set is not exact")

    for run_id, item in item_by_run.items():
        evidence = analysis_by_run[run_id]
        request = evidence.request
        result = evidence.result
        proposal_receipt = evidence.proposal_receipt
        proposal = evidence.proposal
        analysis = item.analysis
        effective = unit_by_work_unit[item.effective_work_unit_id]
        extraction = extraction_by_work_unit[item.effective_work_unit_id]
        manifest_unit = manifest_units.get(
            (effective.effective_batch_id, effective.effective_work_unit_id)
        )
        if manifest_unit is None:
            raise ValueError("analysis extraction manifest request is missing")
        extraction_request = manifest_unit.request
        extraction_proposals = {value.item_number: value for value in extraction.result.items}
        extraction_proposal = extraction_proposals.get(item.item_number)
        source = request.source
        if extraction_proposal is None:
            raise ValueError("analysis source proposal is absent from extraction result")
        if (
            evidence.request_storage != "KNOWLEDGE_ANALYSIS_RUN_CANONICAL_REQUEST_JSONB"
            or evidence.result_storage != "ARTIFACT_REVISION_RESULT_JSONB_AND_MEMBER"
            or request.analysis_request_id != analysis.analysis_request_id
            or request.request_sha256 != analysis.request_sha256
            or request.predecessor_analysis_run_id != analysis.predecessor_analysis_run_id
            or request.execution_preset_id != analysis.preset_id
            or request.execution_preset_revision_id != analysis.preset_revision_id
            or request.execution_preset_sha256 != analysis.preset_sha256
            or request.risk_policy_revision_id != analysis.risk_policy_revision_id
            or result.analysis_request_id != request.analysis_request_id
            or result.analysis_request_sha256 != request.request_sha256
            or result.risk_policy_revision_id != request.risk_policy_revision_id
            or result.source != source
            or sha256_bytes(canonical_json_bytes(result.model_dump(mode="json")))
            != analysis.accepted_result_sha256
            or proposal_receipt.analysis_request_id != request.analysis_request_id
            or proposal_receipt.source != source
            or proposal_receipt.content_set_sha256 != result.proposal_content_set_sha256
            or sha256_bytes(canonical_json_bytes(proposal_receipt))
            != result.proposal_receipt.sha256
            or proposal_receipt.members.normalized_markdown.artifact_id
            != result.proposal_receipt.artifact_id
            or proposal_receipt.members.normalized_markdown.artifact_revision_id
            != result.proposal_receipt.artifact_revision_id
            or proposal.analysis_request_id != request.analysis_request_id
            or proposal.general_knowledge_used != result.general_knowledge_used
            or proposal_receipt.general_knowledge_used != result.general_knowledge_used
            or proposal_receipt.minimum_confidence_milli != result.minimum_confidence_milli
            or proposal_receipt.blocking_ambiguity_count != result.blocking_ambiguity_count
        ):
            raise ValueError("terminal knowledge-analysis request/result chain differs")
        _verify_past_exam_analysis_source(
            source,
            item=item,
            effective=effective,
            extraction_request=extraction_request,
            extraction_proposal=extraction_proposal,
        )
        counts = proposal_receipt.counts
        if (
            counts.anchors != len(proposal.anchors)
            or counts.nodes != len(proposal.nodes)
            or counts.edges != len(proposal.edges)
            or counts.claims != len(proposal.claims)
            or counts.component_observations != len(proposal.component_observations)
            or counts.page_image_observations != len(proposal.page_image_observations)
            or counts.ambiguities != len(proposal.unresolved_ambiguities)
            or result.counts != counts
        ):
            raise ValueError("terminal knowledge-analysis proposal counts differ")
        allowed_anchor_members = {
            (source.artifact_member.artifact_revision_id, source.artifact_member.member_path),
            *(
                (page.image.artifact_revision_id, page.image.member_path)
                for page in source.page_inputs
            ),
        }
        if any(
            (anchor.artifact_revision_id, anchor.member_path) not in allowed_anchor_members
            for anchor in proposal.anchors
        ):
            raise ValueError("terminal knowledge-analysis proposal anchor is outside its source")
        observed_pages = tuple(
            (
                value.page_input_id,
                value.source_role,
                value.physical_page,
                value.image_sha256,
            )
            for value in proposal.page_image_observations
        )
        expected_pages = tuple(
            (
                value.page_input_id,
                value.source_role,
                value.physical_page,
                value.image.sha256,
            )
            for value in source.page_inputs
        )
        if observed_pages != expected_pages:
            raise ValueError("terminal knowledge-analysis page observations differ")
        validate_assessment_page_observation_anchors(source, proposal)


def _verify_past_exam_analysis_source(
    source: ApprovedPastExamItemKnowledgeSourceV3,
    *,
    item: ItemCompletion,
    effective: EffectiveWorkUnit,
    extraction_request: LegacyItemExtractionRequest,
    extraction_proposal: LegacyAssessmentItemProposal,
) -> None:
    source_artifact = source.artifact_member
    item_artifact = item.item_content_artifact
    if (
        source.item_id != item.item_id
        or source.item_revision_id != item.item_revision_id
        or source.lifecycle_state != "APPROVED"
        or (
            source_artifact.artifact_id,
            source_artifact.artifact_revision_id,
            source_artifact.member_path,
            source_artifact.schema_ref,
            source_artifact.media_type,
            source_artifact.sha256,
        )
        != (
            item_artifact.artifact_id,
            item_artifact.artifact_revision_id,
            item_artifact.member_path,
            item_artifact.schema_ref,
            item_artifact.media_type,
            item_artifact.sha256,
        )
        or source.extraction_acceptance_id != item.acceptance_id
        or source.extraction_acceptance_sha256 != item.acceptance_sha256
        or source.extraction_acceptance_artifact.model_dump(mode="json")
        != effective.acceptance_artifact.model_dump(mode="json")
        or source.extraction_result_id != effective.extraction_result_id
        or source.extraction_result_sha256 != effective.result_sha256
        or source.extraction_result_artifact.model_dump(mode="json")
        != effective.result_artifact.model_dump(mode="json")
        or source.item_proposal_id != item.item_proposal_id
        or source.item_proposal_id != extraction_proposal.item_proposal_id
        or source.item_number != item.item_number
        or source.item_number != extraction_proposal.item_number
        or source.bundle != extraction_request.bundle
        or source.layout_observation != extraction_request.layout_observation
        or source.page_inputs != extraction_request.page_inputs
    ):
        raise ValueError("terminal knowledge-analysis V3 source differs from extraction chain")


def _member_pointer_identity(
    value: ArtifactMember
    | KnowledgeArtifactMemberPointer
    | KnowledgeAnalysisSourceArtifactMemberV2,
) -> tuple[str, str, str, str, str, str]:
    if value.schema_ref is None:
        raise ValueError("Graph Artifact member pointer schema is missing")
    return (
        value.artifact_id,
        value.artifact_revision_id,
        value.member_path,
        value.schema_ref,
        value.media_type,
        value.sha256,
    )


def verify_graph_past_exam_sources(
    *,
    items: tuple[ItemCompletion, ...],
    knowledge_documents: tuple[EffectiveKnowledgeAnalysisDocuments, ...],
    snapshot_manifest: KnowledgeGraphSnapshotManifestV8,
) -> None:
    """Bind each Graph V2 source projection to the exact full V3 accepted request source."""

    documents_by_run = {value.analysis_run_id: value for value in knowledge_documents}
    expected_run_ids = {item.analysis.analysis_run_id for item in items}
    if (
        len(documents_by_run) != len(knowledge_documents)
        or set(documents_by_run) != expected_run_ids
    ):
        raise ValueError("Graph knowledge-analysis source document set is not exact")
    expected_sources = {
        item.item_revision_id: documents_by_run[item.analysis.analysis_run_id].request.source
        for item in items
    }
    expected_item_ids = {item.item_id for item in items}
    expected_item_revision_ids = set(expected_sources)
    expected_artifact_ids = {
        source.artifact_member.artifact_id for source in expected_sources.values()
    }
    expected_artifact_revisions = {
        source.artifact_member.artifact_revision_id for source in expected_sources.values()
    }
    expected_hashes = {source.artifact_member.sha256 for source in expected_sources.values()}

    scoped: dict[str, ApprovedItemKnowledgeSourceV2] = {}
    for source in snapshot_manifest.source_revisions:
        member = source.artifact_member
        item_alias = isinstance(source, ApprovedItemKnowledgeSourceV2) and (
            source.item_id in expected_item_ids
            or source.item_revision_id in expected_item_revision_ids
        )
        artifact_alias = (
            member.artifact_id in expected_artifact_ids
            or member.artifact_revision_id in expected_artifact_revisions
            or member.sha256 in expected_hashes
        )
        if not item_alias and not artifact_alias:
            continue
        if not isinstance(source, ApprovedItemKnowledgeSourceV2):
            raise ValueError("Graph manifest contains a wrong-kind completion source alias")
        if source.item_revision_id in scoped:
            raise ValueError("Graph manifest contains duplicate completion sources")
        scoped[source.item_revision_id] = source
    if set(scoped) != expected_item_revision_ids:
        raise ValueError("Graph manifest completion source set is not exact")

    for revision_id, expected in expected_sources.items():
        projected = scoped[revision_id]
        if (
            projected.source_kind != expected.source_kind
            or projected.source_class != expected.source_class
            or projected.item_id != expected.item_id
            or projected.item_revision_id != expected.item_revision_id
            or projected.lifecycle_state != expected.lifecycle_state
            or projected.artifact_member != expected.artifact_member
        ):
            raise ValueError("Graph source projection differs from accepted V3 request source")


def _without_snapshot_membership(placement: GraphPlacement) -> dict[str, object]:
    return placement.model_dump(
        mode="json",
        exclude={
            "graph_id",
            "graph_snapshot_revision_id",
            "graph_snapshot_sha256",
            "membership_sha256",
        },
    )


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, member in pairs:
        if key in value:
            raise ValueError("Graph projection JSON contains a duplicate object key")
        value[key] = member
    return value


def _canonical_json_document(payload: bytes, *, label: str) -> dict[str, object]:
    try:
        decoded = payload.decode("utf-8")
        value: object = json.loads(decoded, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Graph {label} member is not canonical JSON") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != payload:
        raise ValueError(f"Graph {label} member is not canonical JSON")
    return value


def _canonical_ndjson_documents(payload: bytes, *, label: str) -> tuple[dict[str, object], ...]:
    if not payload:
        return ()
    if not payload.endswith(b"\n") or b"\r" in payload:
        raise ValueError(f"Graph {label} projection is not canonical NDJSON")
    documents: list[dict[str, object]] = []
    for line in payload.splitlines(keepends=True):
        body = line[:-1]
        try:
            decoded = body.decode("utf-8")
            value: object = json.loads(decoded, object_pairs_hook=_unique_json_object)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"Graph {label} projection is not canonical NDJSON") from exc
        if not isinstance(value, dict) or canonical_json_bytes(value) + b"\n" != line:
            raise ValueError(f"Graph {label} projection is not canonical NDJSON")
        documents.append(value)
    return tuple(documents)


def _graph_projection_pointers(
    graph: GraphSnapshot,
) -> tuple[KnowledgeArtifactMemberPointer, ...]:
    closure = graph.projections.curriculum_closure
    if closure is None:  # protected by GraphSnapshot validation; retained for type narrowing
        raise ValueError("Graph curriculum-closure projection is missing")
    return (
        graph.projections.nodes,
        graph.projections.edges,
        closure,
        graph.projections.markdown,
        graph.projections.lexical_index,
    )


def verify_graph_documents(
    receipt: PdfLearningCompletionReceipt,
    *,
    items: tuple[ItemCompletion, ...],
    snapshot_manifest: KnowledgeGraphSnapshotManifestV8,
    structure_manifest: KnowledgeGraphStructureManifestV5,
    projection_member_bytes: Mapping[str, bytes],
    snapshot_database: GraphSnapshotDatabaseEvidence,
    placement_database_rows: Iterable[GraphPlacementDatabaseEvidence],
    snapshot_analysis_database_rows: Iterable[GraphSnapshotAnalysisDatabaseEvidence],
) -> None:
    """Prove exact Graph membership from pinned members and one database snapshot.

    The adapter resolves all members and constructs database evidence in one read-only,
    repeatable-read transaction. This verifier hashes every projection member, recomputes the
    producer snapshot hash, and scopes aliases by every cohort identity dimension.
    ``observed_at_utc`` is the later observation time, not Graph creation time.
    """

    graph = receipt.graph_snapshot
    placements = tuple(placement_database_rows)
    snapshot_analyses = tuple(snapshot_analysis_database_rows)

    if (
        sha256_bytes(canonical_json_bytes(snapshot_manifest)) != graph.manifest_sha256
        or snapshot_manifest.graph_id != graph.graph_id
        or snapshot_manifest.graph_snapshot_revision_id != graph.graph_snapshot_revision_id
        or snapshot_manifest.state != graph.snapshot_state
        or snapshot_manifest.ontology_version != "education-knowledge-graph/1.1"
        or snapshot_manifest.snapshot_sha256 != graph.snapshot_sha256
        or snapshot_manifest.structure_manifest != graph.structure_manifest_artifact
        or snapshot_manifest.projections != graph.projections
    ):
        raise ValueError("Graph snapshot manifest differs from the pinned receipt")

    if sha256_bytes(
        canonical_json_bytes(structure_manifest)
    ) != graph.structure_manifest_sha256 or structure_manifest.manifest_sha256 != content_sha256(
        structure_manifest.model_dump(mode="json", exclude={"manifest_sha256"})
    ):
        raise ValueError("Graph structure manifest differs from the pinned Artifact member")

    projection_pointers = _graph_projection_pointers(graph)
    pointer_by_path = {pointer.member_path: pointer for pointer in projection_pointers}
    if set(projection_member_bytes) != set(pointer_by_path):
        raise ValueError("Graph projection member set differs from the snapshot manifest")
    descriptors: list[dict[str, object]] = []
    for member_path, payload in sorted(projection_member_bytes.items()):
        pointer = pointer_by_path[member_path]
        digest = sha256_bytes(payload)
        if digest != pointer.sha256:
            raise ValueError("Graph projection member bytes differ from their pinned pointer")
        descriptors.append({"member_path": member_path, "sha256": digest, "bytes": len(payload)})
    if (
        content_sha256(
            {
                "analysis_run_ids": list(structure_manifest.source_analysis_run_ids),
                "members": descriptors,
            }
        )
        != graph.snapshot_sha256
    ):
        raise ValueError("Graph snapshot hash does not match its complete projection file set")

    node_documents = _canonical_ndjson_documents(
        projection_member_bytes["projections/nodes.jsonl"], label="node"
    )
    edge_documents = _canonical_ndjson_documents(
        projection_member_bytes["projections/edges.jsonl"], label="edge"
    )
    _canonical_ndjson_documents(
        projection_member_bytes["projections/curriculum-closure.jsonl"],
        label="curriculum-closure",
    )
    _canonical_json_document(
        projection_member_bytes["projections/lexical-index.json"], label="lexical-index"
    )
    try:
        markdown = projection_member_bytes["projections/graph.md"].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Graph markdown projection is not UTF-8") from exc
    if not markdown.endswith("\n"):
        raise ValueError("Graph markdown projection is not canonical")
    if (
        len(node_documents) != snapshot_manifest.counts.nodes
        or len(edge_documents) != snapshot_manifest.counts.edges
        or len(snapshot_manifest.source_revisions) != len(snapshot_manifest.analysis_results)
        or len(snapshot_manifest.source_revisions)
        != len(structure_manifest.source_analysis_run_ids)
    ):
        raise ValueError("Graph manifest counts differ from resolved members and source set")

    projection_identity = {
        (pointer.artifact_id, pointer.artifact_revision_id) for pointer in projection_pointers
    }
    if len(projection_identity) != 1:
        raise ValueError("Graph projection pointers do not share one Artifact Revision")
    projection_artifact_id, projection_artifact_revision_id = next(iter(projection_identity))
    database = snapshot_database
    if (
        database.corpus_id != graph.corpus_id
        or database.corpus_key != graph.corpus_key
        or database.corpus_lifecycle_state != graph.corpus_lifecycle_state
        or database.corpus_revision_id != graph.corpus_revision_id
        or database.corpus_source_set_sha256 != graph.corpus_source_set_sha256
        or database.graph_id != graph.graph_id
        or database.graph_snapshot_revision_id != graph.graph_snapshot_revision_id
        or database.snapshot_state != graph.snapshot_state
        or database.snapshot_sha256 != graph.snapshot_sha256
        or database.manifest_sha256 != graph.manifest_sha256
        or database.manifest_artifact_id != graph.manifest_artifact.artifact_id
        or database.manifest_artifact_revision_id != graph.manifest_artifact.artifact_revision_id
        or database.projection_artifact_id != projection_artifact_id
        or database.projection_artifact_revision_id != projection_artifact_revision_id
        or database.created_at != graph.snapshot_created_at
        or snapshot_manifest.created_at != graph.snapshot_created_at
        or receipt.observed_at_utc < database.created_at
    ):
        raise ValueError("Graph current database snapshot differs from the receipt")

    expected_items = {(item.bundle_revision_id, item.item_number): item for item in items}
    if len(expected_items) != 520:
        raise ValueError("Graph verification requires the exact 520 completion items")
    expected_placements = tuple(item.graph_placement for item in items)
    expected_keys = set(expected_items)
    expected_run_ids = {item.analysis.analysis_run_id for item in items}
    expected_item_ids = {item.item_id for item in items}
    expected_item_revision_ids = {item.item_revision_id for item in items}
    expected_origin_ids = {item.item_origin_profile_id for item in items}
    expected_origin_hashes = {item.item_origin_profile_sha256 for item in items}
    expected_acceptance_ids = {item.acceptance_id for item in items}
    expected_acceptance_hashes = {item.acceptance_sha256 for item in items}
    expected_bundle_ids = {
        placement.assessment_source_bundle_id for placement in expected_placements
    }
    expected_bundle_revisions = {key[0] for key in expected_items}
    expected_bundle_hashes = {
        placement.assessment_source_bundle_sha256 for placement in expected_placements
    }
    expected_occurrence_ids = {
        placement.assessment_occurrence_id for placement in expected_placements
    }
    expected_occurrence_revisions = {
        placement.assessment_occurrence_revision_id for placement in expected_placements
    }
    expected_occurrence_hashes = {
        placement.assessment_occurrence_revision_sha256 for placement in expected_placements
    }
    expected_placement_hashes = {placement.placement_sha256 for placement in expected_placements}
    if not expected_run_ids.issubset(structure_manifest.source_analysis_run_ids):
        raise ValueError("completion analyses are absent from the Graph structure source set")

    scoped_structure: dict[tuple[str, int], dict[str, object]] = {}
    for binding in structure_manifest.assessment_item_occurrences:
        key = (binding.assessment_source_bundle_revision_id, binding.item_number)
        belongs_to_cohort = (
            key in expected_keys
            or binding.analysis_run_id in expected_run_ids
            or binding.item_id in expected_item_ids
            or binding.item_revision_id in expected_item_revision_ids
            or binding.item_origin_profile_id in expected_origin_ids
            or binding.item_origin_profile_sha256 in expected_origin_hashes
            or binding.extraction_acceptance_id in expected_acceptance_ids
            or binding.extraction_acceptance_sha256 in expected_acceptance_hashes
            or binding.assessment_source_bundle_id in expected_bundle_ids
            or binding.assessment_source_bundle_revision_id in expected_bundle_revisions
            or binding.assessment_source_bundle_sha256 in expected_bundle_hashes
            or binding.assessment_occurrence_id in expected_occurrence_ids
            or binding.assessment_occurrence_revision_id in expected_occurrence_revisions
            or binding.assessment_occurrence_revision_sha256 in expected_occurrence_hashes
            or binding.placement_sha256 in expected_placement_hashes
        )
        if not belongs_to_cohort:
            continue
        if key in scoped_structure:
            raise ValueError("Graph structure contains duplicate completion placement keys")
        scoped_structure[key] = binding.model_dump(mode="json")
    if set(scoped_structure) != expected_keys:
        raise ValueError("Graph structure completion placement set is not exact")
    for key, item in expected_items.items():
        if scoped_structure[key] != _without_snapshot_membership(item.graph_placement):
            raise ValueError("completion placement differs from pinned Graph structure content")

    expected_result_artifact_ids = {
        item.analysis.accepted_result_artifact.artifact_id for item in items
    }
    expected_result_artifact_revisions = {
        item.analysis.accepted_result_artifact.artifact_revision_id for item in items
    }
    expected_result_hashes = {item.analysis.accepted_result_sha256 for item in items}
    scoped_alignments: dict[str, AutomaticItemCurriculumAlignmentBinding] = {}
    expected_by_run = {item.analysis.analysis_run_id: item for item in items}
    for alignment in structure_manifest.automatic_item_curriculum_bindings:
        result = alignment.accepted_result
        belongs_to_cohort = (
            alignment.analysis_run_id in expected_run_ids
            or alignment.item_id in expected_item_ids
            or alignment.item_revision_id in expected_item_revision_ids
            or result.artifact_id in expected_result_artifact_ids
            or result.artifact_revision_id in expected_result_artifact_revisions
            or result.sha256 in expected_result_hashes
        )
        if not belongs_to_cohort:
            continue
        if alignment.analysis_run_id in scoped_alignments:
            raise ValueError("Graph structure contains duplicate completion alignments")
        scoped_alignments[alignment.analysis_run_id] = alignment
    if set(scoped_alignments) != expected_run_ids:
        raise ValueError("Graph automatic alignment completion set is not exact")
    for run_id, item in expected_by_run.items():
        alignment = scoped_alignments[run_id]
        if (
            alignment.item_id != item.item_id
            or alignment.item_revision_id != item.item_revision_id
            or _member_pointer_identity(alignment.accepted_result)
            != _member_pointer_identity(item.analysis.accepted_result_artifact)
            or alignment.curriculum_unit_ids != item.graph_placement.curriculum_unit_ids
        ):
            raise ValueError("Graph automatic alignment differs from completion analysis")

    nodes = tuple(
        GraphProjectionNodeEvidence.model_validate(
            {"node_id": document.get("node_id"), "stable_key": document.get("stable_key")}
        )
        for document in node_documents
    )
    node_by_stable_key: dict[str, str] = {}
    node_ids: set[str] = set()
    for node in nodes:
        if node.stable_key in node_by_stable_key or node.node_id in node_ids:
            raise ValueError("Graph node projection identities are not unique")
        node_by_stable_key[node.stable_key] = node.node_id
        node_ids.add(node.node_id)

    scoped_database_placements: dict[tuple[str, int], GraphPlacementDatabaseEvidence] = {}
    for row in placements:
        if row.graph_snapshot_revision_id != graph.graph_snapshot_revision_id:
            raise ValueError("Graph placement database row belongs to another snapshot")
        key = (row.assessment_source_bundle_revision_id, row.item_number)
        belongs_to_cohort = (
            key in expected_keys
            or row.analysis_run_id in expected_run_ids
            or row.item_id in expected_item_ids
            or row.item_revision_id in expected_item_revision_ids
            or row.item_origin_profile_id in expected_origin_ids
            or row.extraction_acceptance_id in expected_acceptance_ids
            or row.assessment_source_bundle_revision_id in expected_bundle_revisions
            or row.assessment_occurrence_id in expected_occurrence_ids
            or row.assessment_occurrence_revision_id in expected_occurrence_revisions
            or row.assessment_occurrence_revision_sha256 in expected_occurrence_hashes
            or row.placement_sha256 in expected_placement_hashes
        )
        if not belongs_to_cohort:
            continue
        if key in scoped_database_placements:
            raise ValueError("Graph database contains duplicate completion placement keys")
        scoped_database_placements[key] = row
    if set(scoped_database_placements) != expected_keys:
        raise ValueError("Graph database completion placement set is not exact")
    for key, item in expected_items.items():
        row = scoped_database_placements[key]
        placement = item.graph_placement
        expected_node_ids = (
            node_by_stable_key.get(
                "assessment-item-occurrence:"
                + placement.assessment_occurrence_revision_id
                + f":{placement.item_number}"
            ),
            node_by_stable_key.get(
                "assessment-occurrence-revision:" + placement.assessment_occurrence_revision_id
            ),
            node_by_stable_key.get("item-revision:" + placement.item_revision_id),
        )
        if None in expected_node_ids:
            raise ValueError("Graph placement nodes are absent from the pinned node projection")
        database_fields = (
            row.analysis_run_id,
            row.assessment_occurrence_id,
            row.assessment_occurrence_revision_id,
            row.assessment_occurrence_revision_sha256,
            row.occurrence_display_label,
            row.administration_year,
            row.administration_month,
            row.target_school_level,
            row.target_grade,
            row.subject_key,
            row.item_number,
            row.item_id,
            row.item_revision_id,
            row.item_origin_profile_id,
            row.extraction_acceptance_id,
            row.assessment_source_bundle_revision_id,
            row.placement_sha256,
            row.placement_node_id,
            row.occurrence_node_id,
            row.item_node_id,
        )
        expected_fields = (
            placement.analysis_run_id,
            placement.assessment_occurrence_id,
            placement.assessment_occurrence_revision_id,
            placement.assessment_occurrence_revision_sha256,
            placement.occurrence_display_label,
            placement.administration_year,
            placement.administration_month,
            placement.target_school_level,
            placement.target_grade,
            placement.subject_key,
            placement.item_number,
            placement.item_id,
            placement.item_revision_id,
            placement.item_origin_profile_id,
            placement.extraction_acceptance_id,
            placement.assessment_source_bundle_revision_id,
            placement.placement_sha256,
            *expected_node_ids,
        )
        if database_fields != expected_fields:
            raise ValueError(
                "Graph placement database row differs from pinned structure/projection"
            )

    expected_source_artifact_ids = {item.analysis.source_artifact.artifact_id for item in items}
    expected_source_artifact_revisions = {
        item.analysis.source_artifact.artifact_revision_id for item in items
    }
    expected_source_hashes = {item.analysis.source_artifact.sha256 for item in items}
    scoped_database_analyses: dict[str, GraphSnapshotAnalysisDatabaseEvidence] = {}
    for analysis_row in snapshot_analyses:
        if analysis_row.graph_snapshot_revision_id != graph.graph_snapshot_revision_id:
            raise ValueError("Graph snapshot-analysis row belongs to another snapshot")
        belongs_to_cohort = (
            analysis_row.analysis_run_id in expected_run_ids
            or analysis_row.source_revision_id in expected_item_revision_ids
            or analysis_row.source_artifact_id in expected_source_artifact_ids
            or analysis_row.source_artifact_revision_id in expected_source_artifact_revisions
            or analysis_row.source_sha256 in expected_source_hashes
            or analysis_row.accepted_result_artifact_id in expected_result_artifact_ids
            or analysis_row.accepted_result_artifact_revision_id
            in expected_result_artifact_revisions
            or analysis_row.accepted_result_sha256 in expected_result_hashes
        )
        if not belongs_to_cohort:
            continue
        if analysis_row.analysis_run_id in scoped_database_analyses:
            raise ValueError("Graph database contains duplicate completion analysis rows")
        scoped_database_analyses[analysis_row.analysis_run_id] = analysis_row
    if set(scoped_database_analyses) != expected_run_ids:
        raise ValueError("Graph database completion analysis set is not exact")

    scoped_manifest_sources: dict[str, ApprovedItemKnowledgeSourceV2] = {}
    for source in snapshot_manifest.source_revisions:
        if not isinstance(source, ApprovedItemKnowledgeSourceV2):
            continue
        member = source.artifact_member
        belongs_to_cohort = (
            source.item_id in expected_item_ids
            or source.item_revision_id in expected_item_revision_ids
            or member.artifact_id in expected_source_artifact_ids
            or member.artifact_revision_id in expected_source_artifact_revisions
            or member.sha256 in expected_source_hashes
        )
        if not belongs_to_cohort:
            continue
        if source.item_revision_id in scoped_manifest_sources:
            raise ValueError("Graph manifest contains duplicate completion sources")
        scoped_manifest_sources[source.item_revision_id] = source
    if set(scoped_manifest_sources) != expected_item_revision_ids:
        raise ValueError("Graph manifest completion source set is not exact")

    expected_result_identities = {
        _member_pointer_identity(item.analysis.accepted_result_artifact) for item in items
    }
    scoped_manifest_results: list[KnowledgeArtifactMemberPointer] = []
    for pointer in snapshot_manifest.analysis_results:
        belongs_to_cohort = (
            pointer.artifact_id in expected_result_artifact_ids
            or pointer.artifact_revision_id in expected_result_artifact_revisions
            or pointer.sha256 in expected_result_hashes
        )
        if belongs_to_cohort:
            scoped_manifest_results.append(pointer)
    result_identities = tuple(
        _member_pointer_identity(pointer) for pointer in scoped_manifest_results
    )
    if (
        len(result_identities) != 520
        or len(set(result_identities)) != 520
        or set(result_identities) != expected_result_identities
    ):
        raise ValueError("Graph manifest completion result set is not exact")

    for item in items:
        analysis = item.analysis
        database_analysis = scoped_database_analyses[analysis.analysis_run_id]
        source = scoped_manifest_sources[item.item_revision_id]
        if (
            source.source_kind != analysis.source_kind
            or source.source_class != "PAST_EXAM"
            or source.item_id != item.item_id
            or source.item_revision_id != item.item_revision_id
            or source.lifecycle_state != "APPROVED"
            or source.artifact_member.materialized_path != "source/item-content.json"
            or source.artifact_member.logical_name != "item-content.json"
            or _member_pointer_identity(source.artifact_member)
            != _member_pointer_identity(analysis.source_artifact)
            or database_analysis.source_kind != analysis.source_kind
            or database_analysis.source_revision_id != item.item_revision_id
            or (
                database_analysis.source_artifact_id,
                database_analysis.source_artifact_revision_id,
                database_analysis.source_sha256,
            )
            != (
                analysis.source_artifact.artifact_id,
                analysis.source_artifact.artifact_revision_id,
                analysis.source_artifact.sha256,
            )
            or (
                database_analysis.accepted_result_artifact_id,
                database_analysis.accepted_result_artifact_revision_id,
                database_analysis.accepted_result_sha256,
            )
            != (
                analysis.accepted_result_artifact.artifact_id,
                analysis.accepted_result_artifact.artifact_revision_id,
                analysis.accepted_result_sha256,
            )
        ):
            raise ValueError("Graph analysis evidence differs from the terminal accepted leaf")
