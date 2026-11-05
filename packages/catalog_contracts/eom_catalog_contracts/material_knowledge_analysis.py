"""Uploaded-document source successor; stable knowledge proposal semantics are reused."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from eom_catalog_contracts.knowledge import (
    EducationalDocumentKnowledgeSourceV4,
    KnowledgeAnalysisDocumentDependencyV3,
    KnowledgeAnalysisOriginalSourceMemberV3,
    KnowledgeAnalysisSourceV3,
    KnowledgeGraphSnapshotManifestV9,
    KnowledgeProposalCountsV2,
    KnowledgeProposalMembersV2,
    _KnowledgeAnalysisProposalReceiptBase,
    _KnowledgeAnalysisRequestBase,
    _KnowledgeAnalysisResultBase,
    validate_multimodal_knowledge_members,
)
from eom_catalog_contracts.material_learning import (
    MaterialArtifactMember,
    MaterialSourceRegion,
    SourceRole,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

MaterialCurriculumKey = Annotated[
    str,
    Field(pattern=(r"^(1-\([1-4]\)|2-\([1-6]\)|3-\([1-7]\)|4-\([1-7]\)|5-\([1-7]\)|6-\([1-4]\))$")),
]


class MaterialKnowledgeAnalysisSelection(FrozenModel):
    source_kind: Literal["DOCUMENT_REVISION"] = "DOCUMENT_REVISION"
    source_class: Literal["TEXTBOOK", "INTERNAL_GUIDE"]
    document_revision_id: str = Field(pattern=r"^edudocrev_[0-9a-f]{32}$")
    first_physical_page: int = Field(strict=True, ge=1, le=2000)
    last_physical_page: int = Field(strict=True, ge=1, le=2000)
    selected_regions: tuple[MaterialSourceRegion, ...] = Field(min_length=1, max_length=128)
    curriculum_unit_keys: tuple[MaterialCurriculumKey, ...] = Field(max_length=16)

    @model_validator(mode="after")
    def selected_range(self) -> Self:
        if (
            not 1 <= self.last_physical_page - self.first_physical_page + 1 <= 32
            or self.curriculum_unit_keys != tuple(sorted(set(self.curriculum_unit_keys)))
            or any(
                not self.first_physical_page <= region.physical_page <= self.last_physical_page
                for region in self.selected_regions
            )
            or len({region.source_role for region in self.selected_regions}) != 1
        ):
            raise ValueError("MATERIAL_KNOWLEDGE_SELECTION_INVALID")
        return self


class CreateMaterialKnowledgeAnalysisCommand(FrozenModel):
    operation: Literal["CREATE_MATERIAL_KNOWLEDGE_ANALYSIS"] = "CREATE_MATERIAL_KNOWLEDGE_ANALYSIS"
    source: MaterialKnowledgeAnalysisSelection
    preset_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    general_knowledge_mode: Literal["DISABLED"] = "DISABLED"
    risk_policy_revision_id: str = Field(pattern=r"^analysisriskrev_[0-9a-f]{32}$")
    predecessor_analysis_run_id: str | None = Field(
        default=None, pattern=r"^analysisrun_[0-9a-f]{32}$"
    )
    requested_by: str = Field(pattern=r"^[a-zA-Z0-9_][a-zA-Z0-9_.:-]{0,127}$")
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[\x21-\x7e]+$")

    @model_validator(mode="after")
    def validate_wire(self) -> Self:
        validate_contract("create-material-knowledge-analysis-v1", self.model_dump(mode="json"))
        return self


class MaterialKnowledgePageMember(FrozenModel):
    member_kind: Literal["PAGE_TEXT", "PAGE_IMAGE"]
    physical_page: int = Field(strict=True, ge=1, le=2000)
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: str = Field(
        pattern=r"^analysis/(?:pages/page-[0-9]{6}\.md|images/page-[0-9]{6}\.png)$", max_length=80
    )
    materialized_path: str = Field(
        pattern=r"^source/document/(?:pages/page-[0-9]{6}\.md|images/page-[0-9]{6}\.png)$",
        max_length=80,
    )
    sha256: Sha256
    bytes: int = Field(strict=True, ge=1, le=16 * 1024 * 1024)
    schema_ref: Literal[
        "eom://schemas/material-learning/page-text/1.0",
        "eom://schemas/educational-document/page-image/1.0",
    ]
    media_type: Literal["text/markdown", "image/png"]
    logical_name: str = Field(pattern=r"^page-[0-9]{6}\.(?:md|png)$", max_length=32)
    width_pixels: int | None = Field(strict=True, ge=1, le=10000)
    height_pixels: int | None = Field(strict=True, ge=1, le=10000)

    @model_validator(mode="after")
    def exact_page_member(self) -> Self:
        image = self.member_kind == "PAGE_IMAGE"
        suffix, directory = ("png", "images") if image else ("md", "pages")
        name = f"page-{self.physical_page:06d}.{suffix}"
        if (
            self.member_path != f"analysis/{directory}/{name}"
            or self.materialized_path != f"source/document/{directory}/{name}"
            or self.logical_name != name
            or self.media_type != ("image/png" if image else "text/markdown")
            or self.schema_ref
            != (
                "eom://schemas/educational-document/page-image/1.0"
                if image
                else "eom://schemas/material-learning/page-text/1.0"
            )
            or (
                not image
                and (
                    self.bytes > 2 * 1024 * 1024
                    or self.width_pixels is not None
                    or self.height_pixels is not None
                )
            )
            or (
                image
                and (self.bytes < 24 or self.width_pixels is None or self.height_pixels is None)
            )
        ):
            raise ValueError("MATERIAL_KNOWLEDGE_PAGE_MEMBER_INVALID")
        return self


class EducationalDocumentKnowledgeSourceV5(FrozenModel):
    source_kind: Literal["DOCUMENT_REVISION"] = "DOCUMENT_REVISION"
    source_profile: Literal["UPLOADED_MATERIAL_V1"] = "UPLOADED_MATERIAL_V1"
    source_class: Literal["TEXTBOOK", "INTERNAL_GUIDE"]
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    source_role: SourceRole
    document_id: str = Field(pattern=r"^edudoc_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^edudocrev_[0-9a-f]{32}$")
    lifecycle_state: Literal["APPROVED"] = "APPROVED"
    document_manifest: MaterialArtifactMember
    original_source: MaterialArtifactMember
    artifact_member: KnowledgeAnalysisOriginalSourceMemberV3
    analysis_bundle_manifest: KnowledgeAnalysisDocumentDependencyV3
    rights_attestation: KnowledgeAnalysisDocumentDependencyV3
    first_physical_page: int = Field(strict=True, ge=1, le=2000)
    last_physical_page: int = Field(strict=True, ge=1, le=2000)
    selected_regions: tuple[MaterialSourceRegion, ...] = Field(min_length=1, max_length=128)
    curriculum_unit_keys: tuple[MaterialCurriculumKey, ...] = Field(max_length=16)
    chunk_manifests: tuple[MaterialArtifactMember, ...] = Field(min_length=1, max_length=32)
    materialization_members: tuple[MaterialKnowledgePageMember, ...] = Field(
        min_length=2, max_length=64
    )
    materialization_bytes: int = Field(strict=True, ge=2, le=128 * 1024 * 1024)
    page_image_count: int = Field(strict=True, ge=1, le=32)

    @model_validator(mode="after")
    def exact_material_document_range(self) -> Self:
        validate_contract("educational-document-knowledge-source-v5", self.model_dump(mode="json"))
        pages = tuple(range(self.first_physical_page, self.last_physical_page + 1))
        texts = tuple(
            member for member in self.materialization_members if member.member_kind == "PAGE_TEXT"
        )
        images = tuple(
            member for member in self.materialization_members if member.member_kind == "PAGE_IMAGE"
        )
        if (
            not 1 <= len(pages) <= 32
            or self.page_image_count != len(pages)
            or tuple(member.physical_page for member in texts) != pages
            or tuple(member.physical_page for member in images) != pages
            or self.materialization_members != (*texts, *images)
            or self.materialization_bytes
            != sum(member.bytes for member in self.materialization_members)
            or self.curriculum_unit_keys != tuple(sorted(set(self.curriculum_unit_keys)))
            or any(
                region.source_role != self.source_role or region.physical_page not in pages
                for region in self.selected_regions
            )
        ):
            raise ValueError("MATERIAL_KNOWLEDGE_PAGE_COVERAGE_INVALID")
        identities = {
            (member.artifact_id, member.artifact_revision_id) for member in self.chunk_manifests
        }
        members = {
            (member.artifact_id, member.artifact_revision_id)
            for member in self.materialization_members
        }
        if len(identities) != len(self.chunk_manifests) or identities != members:
            raise ValueError("MATERIAL_KNOWLEDGE_CHUNK_MEMBERSHIP_INVALID")
        if (
            any(
                pointer.member_path != "analysis/chunk.json"
                or pointer.schema_ref != "eom://schemas/material-learning/page-chunk/1.0"
                or pointer.media_type != "application/json"
                for pointer in self.chunk_manifests
            )
            or self.document_manifest.schema_ref
            != "eom://schemas/material-learning/document-revision/1.0"
            or self.document_manifest.member_path != "document/document-revision.json"
            or self.document_manifest.media_type != "application/json"
            or self.analysis_bundle_manifest.schema_ref
            != "eom://schemas/material-learning/page-bundle/1.0"
            or self.analysis_bundle_manifest.member_path != "analysis/manifest.json"
            or self.rights_attestation.schema_ref != "eom://schemas/material-learning/rights/1.0"
            or self.rights_attestation.member_path != "rights/attestation.json"
        ):
            raise ValueError("MATERIAL_KNOWLEDGE_PROVENANCE_INVALID")
        return self


class KnowledgeAnalysisRequestV12(_KnowledgeAnalysisRequestBase):
    schema_version: Literal["knowledge-analysis-request/12.0"] = "knowledge-analysis-request/12.0"
    source: EducationalDocumentKnowledgeSourceV5
    worker_proposal_schema_ref: Literal[
        "eom://schemas/knowledge/knowledge-analysis-worker-proposal/6.0"
    ] = "eom://schemas/knowledge/knowledge-analysis-worker-proposal/6.0"
    accepted_result_schema_ref: Literal[
        "eom://schemas/knowledge/knowledge-analysis-result/12.0"
    ] = "eom://schemas/knowledge/knowledge-analysis-result/12.0"
    general_knowledge_mode: Literal["DISABLED"] = "DISABLED"
    requested_outputs: tuple[
        Literal[
            "NORMALIZED_MARKDOWN",
            "SOURCE_ANCHORS",
            "NODES",
            "EDGES",
            "CLAIMS",
            "COMPONENT_OBSERVATIONS",
            "PAGE_IMAGE_OBSERVATIONS",
            "UNRESOLVED_AMBIGUITIES",
        ],
        ...,
    ] = Field(min_length=8, max_length=8)

    @model_validator(mode="after")
    def installed_contract(self) -> Self:
        validate_contract("knowledge-analysis-request-v12", self.model_dump(mode="json"))
        return self


class KnowledgeAnalysisProposalReceiptV11(_KnowledgeAnalysisProposalReceiptBase):
    schema_version: Literal["knowledge-analysis-proposal-receipt/11.0"] = (
        "knowledge-analysis-proposal-receipt/11.0"
    )
    source: EducationalDocumentKnowledgeSourceV5
    members: KnowledgeProposalMembersV2
    counts: KnowledgeProposalCountsV2

    @model_validator(mode="after")
    def stable_material_knowledge(self) -> Self:
        validate_contract("knowledge-analysis-proposal-receipt-v11", self.model_dump(mode="json"))
        validate_multimodal_knowledge_members(
            self.members,
            counts=self.counts,
            expected_page_count=self.source.page_image_count,
            node_schema_ref="eom://schemas/knowledge/proposed-node/4.0",
            edge_schema_ref="eom://schemas/knowledge/proposed-edge/4.0",
        )
        return self


class KnowledgeAnalysisResultV12(_KnowledgeAnalysisResultBase):
    schema_version: Literal["knowledge-analysis-result/12.0"] = "knowledge-analysis-result/12.0"
    source: EducationalDocumentKnowledgeSourceV5
    counts: KnowledgeProposalCountsV2

    @model_validator(mode="after")
    def source_bound_receipt(self) -> Self:
        validate_contract("knowledge-analysis-result-v12", self.model_dump(mode="json"))
        if (
            self.proposal_receipt.schema_ref
            != "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/11.0"
            or self.counts.page_image_observations != self.source.page_image_count
        ):
            raise ValueError("MATERIAL_KNOWLEDGE_ACCEPTED_RECEIPT_INVALID")
        return self


class KnowledgeGraphSnapshotManifestV10(KnowledgeGraphSnapshotManifestV9):
    """Same shared Graph/projections/structure; an explicit new source family."""

    schema_version: Literal["knowledge-graph-snapshot-manifest/10.0"] = (
        "knowledge-graph-snapshot-manifest/10.0"  # type: ignore[assignment]
    )
    source_revisions: tuple[
        KnowledgeAnalysisSourceV3
        | EducationalDocumentKnowledgeSourceV4
        | EducationalDocumentKnowledgeSourceV5,
        ...,
    ] = Field(min_length=1, max_length=10000)  # type: ignore[assignment]

    @model_validator(mode="after")
    def exact_uploaded_source_manifest(self) -> Self:
        validate_contract("knowledge-graph-snapshot-manifest-v10", self.model_dump(mode="json"))
        return self
