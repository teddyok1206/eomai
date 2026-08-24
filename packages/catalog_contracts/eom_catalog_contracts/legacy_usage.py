"""Immutable legacy Product/Usage intake and projection contracts."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256, UtcDatetime

StableKey = str


class LegacyUsageProposalState(StrEnum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    CONFLICT = "CONFLICT"
    REJECTED = "REJECTED"


class LegacyUsageReviewDecision(StrEnum):
    PENDING = "PENDING"
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class LegacyUsageColumnMap(FrozenModel):
    source_row_key: str = Field(min_length=1, max_length=128)
    deliverable_id: str = Field(min_length=1, max_length=128)
    deliverable_revision_id: str = Field(min_length=1, max_length=128)
    assessment_form_id: str = Field(min_length=1, max_length=128)
    assessment_form_revision_id: str = Field(min_length=1, max_length=128)
    assessment_form_revision_number: str = Field(min_length=1, max_length=128)
    assessment_form_key: str = Field(min_length=1, max_length=128)
    assessment_form_ordinal: str = Field(min_length=1, max_length=128)
    assessment_form_label: str = Field(min_length=1, max_length=128)
    item_id: str = Field(min_length=1, max_length=128)
    item_revision_id: str = Field(min_length=1, max_length=128)
    item_manifest_sha256: str = Field(min_length=1, max_length=128)
    section_key: str = Field(min_length=1, max_length=128)
    section_ordinal: str = Field(min_length=1, max_length=128)
    position: str = Field(min_length=1, max_length=128)
    display_number: str = Field(min_length=1, max_length=128)
    points_milli: str = Field(min_length=1, max_length=128)
    usage_role: str = Field(min_length=1, max_length=128)
    publication_id: str = Field(min_length=1, max_length=128)
    publication_revision_id: str = Field(min_length=1, max_length=128)
    publication_revision_number: str = Field(min_length=1, max_length=128)
    publication_key: str = Field(min_length=1, max_length=128)
    publication_date: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def unique_columns(self) -> LegacyUsageColumnMap:
        values = tuple(str(value) for value in self.__dict__.values())
        if len(values) != len(set(values)):
            raise ValueError("legacy usage mapping columns must be unique")
        return self


class LegacyUsageMappingContractRevision(FrozenModel):
    schema_version: Literal["legacy-usage-mapping-contract/1.0"]
    mapping_contract_id: str = Field(pattern=r"^legacymap_[0-9a-f]{32}$")
    mapping_contract_revision_id: str = Field(pattern=r"^legacymaprev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1)
    state: Literal["RELEASED"]
    workbook_media_type: Literal[
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ]
    worksheet_name: str = Field(min_length=1, max_length=128)
    header_row: int = Field(ge=1, le=1000)
    first_data_row: int = Field(ge=2, le=1001)
    maximum_rows: int = Field(ge=1, le=100000)
    columns: LegacyUsageColumnMap
    normalization_policy: Literal["legacy-usage-normalization/1.0"]
    contract_sha256: Sha256
    released_at: UtcDatetime
    released_by: ActorId

    @field_validator("worksheet_name")
    @classmethod
    def safe_sheet_name(cls, value: str) -> str:
        if any(ord(character) < 32 for character in value) or value != value.strip():
            raise ValueError("worksheet name is not normalized")
        return value

    @model_validator(mode="after")
    def coherent_rows(self) -> LegacyUsageMappingContractRevision:
        if self.first_data_row <= self.header_row:
            raise ValueError("first data row must follow the header row")
        return self


class LegacyUsageSourcePointer(FrozenModel):
    intake_batch_id: str = Field(pattern=r"^intake_[0-9a-f]{32}$")
    source_file_id: str = Field(pattern=r"^sourcefile_[0-9a-f]{32}$")
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: str = Field(pattern=r"^source/[A-Za-z0-9._()가-힣/-]{1,500}$")
    schema_ref: Literal["eom://schemas/legacy-usage/workbook/1.0"]
    media_type: Literal["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"]
    sha256: Sha256


class LegacyUsageImportManifest(FrozenModel):
    schema_version: Literal["legacy-usage-import-manifest/1.0"]
    legacy_usage_import_id: str = Field(pattern=r"^legacyimport_[0-9a-f]{32}$")
    source: LegacyUsageSourcePointer
    mapping_contract_revision_id: str = Field(pattern=r"^legacymaprev_[0-9a-f]{32}$")
    mapping_contract_sha256: Sha256
    request_sha256: Sha256
    state: Literal["PROPOSED", "REVIEWED", "COMMITTED", "FAILED"]
    row_count: int = Field(ge=0, le=100000)
    resolved_count: int = Field(ge=0, le=100000)
    unresolved_count: int = Field(ge=0, le=100000)
    conflict_count: int = Field(ge=0, le=100000)
    rejected_count: int = Field(ge=0, le=100000)
    created_at: UtcDatetime
    created_by: ActorId

    @model_validator(mode="after")
    def counts_sum(self) -> LegacyUsageImportManifest:
        if (
            self.resolved_count + self.unresolved_count + self.conflict_count + self.rejected_count
            != self.row_count
        ):
            raise ValueError("legacy usage import counts do not sum to row count")
        return self


class CreateLegacyUsageImportCommand(FrozenModel):
    source: LegacyUsageSourcePointer
    mapping_contract_revision_id: str = Field(pattern=r"^legacymaprev_[0-9a-f]{32}$")
    mapping_contract_sha256: Sha256
    requested_by: ActorId
    idempotency_key: str = Field(min_length=16, max_length=200, pattern=r"^[\x21-\x7e]+$")
    request_sha256: Sha256

    @model_validator(mode="after")
    def request_hash_matches(self) -> CreateLegacyUsageImportCommand:
        from eom_identifiers import content_sha256

        value = self.model_dump(mode="json", exclude={"idempotency_key", "request_sha256"})
        if content_sha256(value) != self.request_sha256:
            raise ValueError("legacy usage import request hash does not match canonical input")
        return self


class LegacyUsageResolvedPointers(FrozenModel):
    deliverable_id: str = Field(pattern=r"^deliverable_[0-9a-f]{32}$")
    deliverable_revision_id: str = Field(pattern=r"^delivrev_[0-9a-f]{32}$")
    assessment_form_id: str = Field(pattern=r"^form_[0-9a-f]{32}$")
    assessment_form_revision_id: str = Field(pattern=r"^formrev_[0-9a-f]{32}$")
    publication_id: str = Field(pattern=r"^publication_[0-9a-f]{32}$")
    publication_revision_id: str = Field(pattern=r"^publicationrev_[0-9a-f]{32}$")
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: Sha256


class LegacyUsagePlacementValue(FrozenModel):
    section_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    section_ordinal: int = Field(ge=1, le=10000)
    position: int = Field(ge=1, le=100000)
    display_number: str = Field(min_length=1, max_length=32)
    points_milli: int = Field(ge=0, le=1000000)
    usage_role: Literal["PRIMARY", "PRACTICE", "REVIEW", "EXAMPLE", "OTHER_REVIEWED"]


class LegacyUsageFormValue(FrozenModel):
    form_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    revision_number: int = Field(ge=1, le=100000)
    ordinal: int = Field(ge=1, le=10000)
    display_label: str = Field(min_length=1, max_length=128)


class LegacyUsagePublicationValue(FrozenModel):
    publication_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    revision_number: int = Field(ge=1, le=100000)
    publication_date: date


class LegacyUsageRowProposal(FrozenModel):
    schema_version: Literal["legacy-usage-row-proposal/1.0"]
    legacy_usage_row_id: str = Field(pattern=r"^legacyrow_[0-9a-f]{32}$")
    legacy_usage_import_id: str = Field(pattern=r"^legacyimport_[0-9a-f]{32}$")
    source_row_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    source_row_number: int = Field(ge=1, le=100001)
    normalized_row_sha256: Sha256
    proposal_state: LegacyUsageProposalState
    resolved: LegacyUsageResolvedPointers | None
    form: LegacyUsageFormValue | None
    placement: LegacyUsagePlacementValue | None
    publication: LegacyUsagePublicationValue | None
    candidate_revision_ids: tuple[str, ...] = Field(max_length=20)
    reason_codes: tuple[
        Literal[
            "MISSING_REQUIRED_VALUE",
            "INVALID_VALUE",
            "POINTER_NOT_FOUND",
            "POINTER_OWNERSHIP_MISMATCH",
            "ITEM_REVISION_NOT_APPROVED",
            "ITEM_HASH_MISMATCH",
            "DUPLICATE_SOURCE_ROW",
            "DUPLICATE_PLACEMENT",
            "AMBIGUOUS_POINTER",
            "CANONICAL_TARGET_ALREADY_EXISTS",
            "UNSUPPORTED_FORMULA",
        ],
        ...,
    ] = Field(max_length=20)
    review_decision: LegacyUsageReviewDecision = LegacyUsageReviewDecision.PENDING
    reviewed_at: UtcDatetime | None = None
    reviewed_by: ActorId | None = None

    @model_validator(mode="after")
    def coherent_resolution_and_review(self) -> LegacyUsageRowProposal:
        is_resolved = self.proposal_state == LegacyUsageProposalState.RESOLVED
        has_values = all(
            value is not None
            for value in (self.resolved, self.form, self.placement, self.publication)
        )
        if is_resolved != has_values:
            raise ValueError(
                "only resolved rows may carry canonical pointers and structural values"
            )
        if is_resolved and (self.reason_codes or self.candidate_revision_ids):
            raise ValueError("resolved rows cannot carry quarantine reasons or candidates")
        if not is_resolved and not self.reason_codes:
            raise ValueError("quarantined rows require a reason code")
        decided = self.review_decision != LegacyUsageReviewDecision.PENDING
        if decided != (self.reviewed_at is not None and self.reviewed_by is not None):
            raise ValueError("review identity and time must match decision state")
        if self.review_decision == LegacyUsageReviewDecision.APPROVE and not is_resolved:
            raise ValueError("only resolved rows can be approved")
        return self


class ItemPlacementV1(FrozenModel):
    placement_id: str = Field(pattern=r"^placement_[0-9a-f]{32}$")
    section_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    section_ordinal: int = Field(ge=1, le=10000)
    position: int = Field(ge=1, le=100000)
    display_number: str = Field(min_length=1, max_length=32)
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: Sha256
    points_milli: int = Field(ge=0, le=1000000)
    usage_role: Literal["PRIMARY", "PRACTICE", "REVIEW", "EXAMPLE", "OTHER_REVIEWED"]
    source_usage_plan_id: str | None = Field(default=None, pattern=r"^usageplan_[0-9a-f]{32}$")


class AssessmentAssemblyManifestV1(FrozenModel):
    schema_version: Literal["assessment-assembly-manifest/1.0"]
    assessment_assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    assessment_assembly_id: str = Field(pattern=r"^assembly_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1)
    previous_revision_id: str | None = Field(default=None, pattern=r"^assemblyrev_[0-9a-f]{32}$")
    assessment_form_id: str = Field(pattern=r"^form_[0-9a-f]{32}$")
    placements: tuple[ItemPlacementV1, ...] = Field(min_length=1, max_length=100000)
    total_points_milli: int = Field(ge=0)
    revision_state: Literal["RELEASED"]
    manifest_sha256: Sha256
    created_at: UtcDatetime
    created_by: ActorId

    @model_validator(mode="after")
    def deterministic_placements(self) -> AssessmentAssemblyManifestV1:
        order = tuple(
            (item.section_ordinal, item.position, item.placement_id) for item in self.placements
        )
        if order != tuple(sorted(order)) or len(order) != len(set(order)):
            raise ValueError("placements must be uniquely and deterministically ordered")
        section_positions = {(item.section_key, item.position) for item in self.placements}
        if len(section_positions) != len(self.placements):
            raise ValueError("assembly contains a duplicate section position")
        if sum(item.points_milli for item in self.placements) != self.total_points_milli:
            raise ValueError("assembly total points do not match placements")
        return self


class ProductUsageGraphNodeV1(FrozenModel):
    node_id: str = Field(pattern=r"^pnode_[0-9a-f]{32}$")
    node_type: Literal[
        "PRODUCT_REVISION",
        "FORM_REVISION",
        "ASSEMBLY_REVISION",
        "PUBLICATION_REVISION",
        "ITEM_REVISION",
        "USAGE_RECORD",
    ]
    logical_id: str = Field(min_length=1, max_length=64)
    revision_id: str = Field(min_length=1, max_length=64)
    source_sha256: Sha256


class ProductUsageGraphEdgeV1(FrozenModel):
    edge_id: str = Field(pattern=r"^pedge_[0-9a-f]{32}$")
    edge_type: Literal[
        "PRODUCT_HAS_FORM",
        "FORM_HAS_ASSEMBLY",
        "ASSEMBLY_PLACES_ITEM",
        "PUBLICATION_RELEASES_ASSEMBLY",
        "USAGE_RECORDS_ITEM",
        "USAGE_IN_PUBLICATION",
    ]
    from_node_id: str = Field(pattern=r"^pnode_[0-9a-f]{32}$")
    to_node_id: str = Field(pattern=r"^pnode_[0-9a-f]{32}$")
    source_record_id: str = Field(min_length=1, max_length=64)
    source_sha256: Sha256


class ProductUsageGraphProjectionV1(FrozenModel):
    schema_version: Literal["product-usage-graph-projection/1.0"]
    nodes: tuple[ProductUsageGraphNodeV1, ...] = Field(max_length=1000000)
    edges: tuple[ProductUsageGraphEdgeV1, ...] = Field(max_length=5000000)
    projection_sha256: Sha256
    created_at: UtcDatetime

    @model_validator(mode="after")
    def deterministic_graph(self) -> ProductUsageGraphProjectionV1:
        node_ids = tuple(item.node_id for item in self.nodes)
        edge_ids = tuple(item.edge_id for item in self.edges)
        if node_ids != tuple(sorted(node_ids)) or len(node_ids) != len(set(node_ids)):
            raise ValueError("product usage graph nodes must be sorted and unique")
        if edge_ids != tuple(sorted(edge_ids)) or len(edge_ids) != len(set(edge_ids)):
            raise ValueError("product usage graph edges must be sorted and unique")
        available = set(node_ids)
        if any(
            edge.from_node_id not in available or edge.to_node_id not in available
            for edge in self.edges
        ):
            raise ValueError("product usage graph contains a dangling edge")
        return self


class ReviewLegacyUsageRowCommand(FrozenModel):
    legacy_usage_row_id: str = Field(pattern=r"^legacyrow_[0-9a-f]{32}$")
    decision: Literal["APPROVE", "REJECT"]
    actor_id: ActorId
    idempotency_key: str = Field(min_length=16, max_length=200)


class CommitLegacyUsageImportCommand(FrozenModel):
    legacy_usage_import_id: str = Field(pattern=r"^legacyimport_[0-9a-f]{32}$")
    actor_id: ActorId
    idempotency_key: str = Field(min_length=16, max_length=200)
