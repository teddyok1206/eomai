"""Immutable contracts for reviewed legacy educational-source integration."""

from __future__ import annotations

import unicodedata
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from eom_identifiers import content_sha256 as canonical_content_sha256
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from eom_catalog_contracts.models import ActorId, Sha256


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must use UTC")
    return value


def _safe_relative_path(value: str) -> str:
    if value != unicodedata.normalize("NFC", value):
        raise ValueError("legacy relative path must use NFC normalization")
    if value != value.strip() or "\\" in value:
        raise ValueError("legacy relative path is not normalized")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("legacy relative path contains a control character")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or str(path) != value
    ):
        raise ValueError("legacy relative path must be safe and relative")
    return value


def _safe_artifact_member_path(value: str) -> str:
    _safe_relative_path(value)
    if len(PurePosixPath(value).parts) < 2:
        raise ValueError("artifact member path must include a reviewed root")
    return value


def _require_self_hash(model: BaseModel, field_name: str) -> None:
    expected = canonical_content_sha256(model.model_dump(mode="json", exclude={field_name}))
    if getattr(model, field_name) != expected:
        raise ValueError(f"{field_name} does not match canonical contract content")


UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
SafeRelativePath = Annotated[
    str,
    Field(min_length=1, max_length=500),
    AfterValidator(_safe_relative_path),
]
SafeArtifactMemberPath = Annotated[
    str,
    Field(min_length=3, max_length=512),
    AfterValidator(_safe_artifact_member_path),
]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class LegacyKnowledgeContractErrorCode(StrEnum):
    LEGACY_KNOWLEDGE_CONTRACT_INVALID = "LEGACY_KNOWLEDGE_CONTRACT_INVALID"
    LEGACY_KNOWLEDGE_UNSAFE_PATH = "LEGACY_KNOWLEDGE_UNSAFE_PATH"
    LEGACY_KNOWLEDGE_HASH_MISMATCH = "LEGACY_KNOWLEDGE_HASH_MISMATCH"
    LEGACY_KNOWLEDGE_DUPLICATE_ENTRY = "LEGACY_KNOWLEDGE_DUPLICATE_ENTRY"
    LEGACY_KNOWLEDGE_INVENTORY_STALE = "LEGACY_KNOWLEDGE_INVENTORY_STALE"
    LEGACY_KNOWLEDGE_POINTER_STALE = "LEGACY_KNOWLEDGE_POINTER_STALE"
    LEGACY_KNOWLEDGE_CLASS_INVALID = "LEGACY_KNOWLEDGE_CLASS_INVALID"
    LEGACY_KNOWLEDGE_RIGHTS_INVALID = "LEGACY_KNOWLEDGE_RIGHTS_INVALID"
    LEGACY_KNOWLEDGE_RELATION_INVALID = "LEGACY_KNOWLEDGE_RELATION_INVALID"
    LEGACY_KNOWLEDGE_PAGE_RANGE_INVALID = "LEGACY_KNOWLEDGE_PAGE_RANGE_INVALID"


class LegacyRootAlias(StrEnum):
    EOMIS_LEGACY_SOURCE = "EOMIS_LEGACY_SOURCE"
    EOM_AI_SERVER_LEGACY_SOURCE = "EOM_AI_SERVER_LEGACY_SOURCE"


class LegacySourceFamily(StrEnum):
    CURRICULUM = "CURRICULUM"
    TEXTBOOK = "TEXTBOOK"
    REFERENCE_BOOK = "REFERENCE_BOOK"
    GUIDANCE = "GUIDANCE"
    ITEM = "ITEM"
    USAGE_WORKBOOK = "USAGE_WORKBOOK"
    DERIVED_EVIDENCE = "DERIVED_EVIDENCE"
    EXCLUDED = "EXCLUDED"


class LegacySourceCanonicality(StrEnum):
    ORIGINAL = "ORIGINAL"
    DERIVED = "DERIVED"
    UNKNOWN = "UNKNOWN"


class LegacySourcePreliminaryClass(StrEnum):
    ORIGINAL_SOURCE_CANDIDATE = "ORIGINAL_SOURCE_CANDIDATE"
    DERIVED_MIGRATION_EVIDENCE = "DERIVED_MIGRATION_EVIDENCE"
    EXCLUDED_RUNTIME_STATE = "EXCLUDED_RUNTIME_STATE"


class LegacyRightsState(StrEnum):
    UNREVIEWED = "UNREVIEWED"
    CLEARED_INTERNAL = "CLEARED_INTERNAL"
    CLEARED_LICENSED = "CLEARED_LICENSED"
    RESTRICTED = "RESTRICTED"
    REJECTED = "REJECTED"


class LegacyFileObservation(StrEnum):
    REGULAR = "REGULAR"
    SYMLINK = "SYMLINK"
    HARDLINK = "HARDLINK"
    SPECIAL = "SPECIAL"
    UNREADABLE = "UNREADABLE"


class LegacyExclusionReason(StrEnum):
    SECRET_OR_CREDENTIAL = "SECRET_OR_CREDENTIAL"
    VERSION_CONTROL_METADATA = "VERSION_CONTROL_METADATA"
    RUNTIME_DATABASE_OR_INDEX = "RUNTIME_DATABASE_OR_INDEX"
    MODEL_OR_CHECKPOINT = "MODEL_OR_CHECKPOINT"
    CACHE_TEMP_OR_LOCK = "CACHE_TEMP_OR_LOCK"
    GENERATED_OUTPUT = "GENERATED_OUTPUT"
    UNSUPPORTED_MEDIA = "UNSUPPORTED_MEDIA"
    UNSAFE_PATH = "UNSAFE_PATH"
    SYMLINK = "SYMLINK"
    HARDLINK = "HARDLINK"
    SPECIAL_FILE = "SPECIAL_FILE"
    UNREADABLE = "UNREADABLE"
    SIZE_LIMIT = "SIZE_LIMIT"
    RIGHTS_REJECTED = "RIGHTS_REJECTED"
    OUTSIDE_ALLOWLIST = "OUTSIDE_ALLOWLIST"


class LegacyArtifactMemberPointer(FrozenModel):
    pointer_type: Literal["ARTIFACT_MEMBER"] = "ARTIFACT_MEMBER"
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: SafeArtifactMemberPath
    schema_ref: str = Field(pattern=r"^eom://schemas/[A-Za-z0-9._/-]{1,220}$")
    media_type: str = Field(pattern=r"^[a-z0-9][a-z0-9.+-]*/[A-Za-z0-9][A-Za-z0-9.+-]*$")
    sha256: Sha256


class LegacyInventoryEntryPointer(FrozenModel):
    pointer_type: Literal["INVENTORY_ENTRY"] = "INVENTORY_ENTRY"
    inventory_id: str = Field(pattern=r"^legacyinventory_[0-9a-f]{32}$")
    inventory_sha256: Sha256
    entry_key: str = Field(pattern=r"^legacyentry_[0-9a-f]{32}$")
    content_sha256: Sha256


LegacySourcePointer = Annotated[
    LegacyArtifactMemberPointer | LegacyInventoryEntryPointer,
    Field(discriminator="pointer_type"),
]


class LegacySourceRightsReview(FrozenModel):
    schema_version: Literal["legacy-source-rights-review/1.0"]
    rights_review_id: str = Field(pattern=r"^rightsreview_[0-9a-f]{32}$")
    rights_review_revision_id: str = Field(pattern=r"^rightsreviewrev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1, le=100000)
    previous_revision_id: str | None = Field(
        default=None, pattern=r"^rightsreviewrev_[0-9a-f]{32}$"
    )
    source_owner_reference: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    document_type: Literal[
        "CURRICULUM",
        "TEXTBOOK",
        "REFERENCE_BOOK",
        "GUIDANCE",
        "ASSESSMENT_ITEM",
        "USAGE_WORKBOOK",
    ]
    rights_state: Literal["CLEARED_INTERNAL", "CLEARED_LICENSED", "RESTRICTED", "REJECTED"]
    allowed_internal_processing: bool
    allowed_model_exposure: bool
    allowed_roles: tuple[
        Literal[
            "ADMIN",
            "RIGHTS_REVIEWER",
            "DATA_ANALYST_WORKER",
            "ITEM_AUTHORING_WORKER",
            "HUMAN_EDITOR",
        ],
        ...,
    ] = Field(max_length=5)
    allowed_excerpt_materialization: bool
    allowed_page_image_materialization: bool
    allowed_item_grounding: bool
    answer_bearing: bool
    retention_policy_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    withdrawal_behavior: Literal["RETIRE_FROM_NEW_RETRIEVAL", "BLOCK_ALL_NEW_USE"]
    evidence: tuple[LegacyArtifactMemberPointer, ...] = Field(min_length=1, max_length=20)
    reviewed_at: UtcDatetime
    reviewed_by: ActorId
    rights_review_sha256: Sha256

    @model_validator(mode="after")
    def coherent_rights(self) -> LegacySourceRightsReview:
        roles = tuple(self.allowed_roles)
        if len(roles) != len(set(roles)) or roles != tuple(sorted(roles)):
            raise ValueError("legacy rights roles must be unique and sorted")
        evidence_keys = tuple(
            (pointer.artifact_id, pointer.artifact_revision_id, pointer.member_path)
            for pointer in self.evidence
        )
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("legacy rights evidence pointers must be unique")
        worker_roles = {"DATA_ANALYST_WORKER", "ITEM_AUTHORING_WORKER"}
        if self.allowed_model_exposure != bool(worker_roles & set(roles)):
            raise ValueError("legacy rights model exposure must match allowed worker roles")
        if self.allowed_item_grounding and not self.allowed_model_exposure:
            raise ValueError("legacy rights item grounding requires model exposure")
        if (
            self.allowed_excerpt_materialization or self.allowed_page_image_materialization
        ) and not self.allowed_internal_processing:
            raise ValueError("legacy rights materialization requires internal processing")
        if self.rights_state == "REJECTED" and (
            self.allowed_internal_processing
            or self.allowed_model_exposure
            or roles
            or self.allowed_excerpt_materialization
            or self.allowed_page_image_materialization
            or self.allowed_item_grounding
        ):
            raise ValueError("rejected legacy rights cannot allow source use")
        _require_self_hash(self, "rights_review_sha256")
        return self


class LegacySourceInventoryEntry(FrozenModel):
    entry_key: str = Field(pattern=r"^legacyentry_[0-9a-f]{32}$")
    relative_path: SafeRelativePath
    file_observation: LegacyFileObservation
    size_bytes: int = Field(ge=0, le=1 << 50)
    media_type: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9.+-]*/[A-Za-z0-9][A-Za-z0-9.+-]*$",
    )
    content_sha256: Sha256 | None
    preliminary_class: LegacySourcePreliminaryClass
    source_family: LegacySourceFamily
    canonicality: LegacySourceCanonicality
    rights_state: LegacyRightsState
    relation_group_key: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    exclusion_reasons: tuple[LegacyExclusionReason, ...] = Field(max_length=16)

    @model_validator(mode="after")
    def coherent_classification(self) -> LegacySourceInventoryEntry:
        reasons = tuple(self.exclusion_reasons)
        if len(reasons) != len(set(reasons)):
            raise ValueError("legacy inventory exclusion reasons must be unique")
        if self.preliminary_class == LegacySourcePreliminaryClass.ORIGINAL_SOURCE_CANDIDATE:
            if (
                self.file_observation != LegacyFileObservation.REGULAR
                or self.content_sha256 is None
                or self.media_type is None
                or self.canonicality != LegacySourceCanonicality.ORIGINAL
                or self.source_family
                in {LegacySourceFamily.DERIVED_EVIDENCE, LegacySourceFamily.EXCLUDED}
                or reasons
            ):
                raise ValueError("original source candidate classification is inconsistent")
            if (
                self.source_family
                in {LegacySourceFamily.TEXTBOOK, LegacySourceFamily.REFERENCE_BOOK}
                and self.media_type != "application/pdf"
            ):
                raise ValueError("textbook and reference-book originals must be PDF")
        elif self.preliminary_class == LegacySourcePreliminaryClass.DERIVED_MIGRATION_EVIDENCE:
            if (
                self.file_observation != LegacyFileObservation.REGULAR
                or self.content_sha256 is None
                or self.media_type is None
                or self.canonicality != LegacySourceCanonicality.DERIVED
                or self.source_family != LegacySourceFamily.DERIVED_EVIDENCE
                or reasons
            ):
                raise ValueError("derived migration evidence classification is inconsistent")
        elif (
            self.source_family != LegacySourceFamily.EXCLUDED
            or self.canonicality == LegacySourceCanonicality.ORIGINAL
            or not reasons
        ):
            raise ValueError("excluded runtime-state classification is inconsistent")
        if (
            self.preliminary_class != LegacySourcePreliminaryClass.ORIGINAL_SOURCE_CANDIDATE
            and self.rights_state
            in {LegacyRightsState.CLEARED_INTERNAL, LegacyRightsState.CLEARED_LICENSED}
        ):
            raise ValueError("only original source candidates may carry cleared rights")
        return self


class LegacySourceInventoryClassSummary(FrozenModel):
    file_count: int = Field(ge=0, le=100000)
    byte_count: int = Field(ge=0, le=1 << 60)


class LegacySourceInventorySummary(FrozenModel):
    original_source_candidates: LegacySourceInventoryClassSummary
    derived_migration_evidence: LegacySourceInventoryClassSummary
    excluded_runtime_state: LegacySourceInventoryClassSummary
    total_file_count: int = Field(ge=0, le=100000)
    total_byte_count: int = Field(ge=0, le=1 << 60)


class LegacySourceInventory(FrozenModel):
    schema_version: Literal["legacy-source-inventory/1.0"]
    inventory_id: str = Field(pattern=r"^legacyinventory_[0-9a-f]{32}$")
    observed_at: UtcDatetime
    scanner_version: str = Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
    scanner_policy_revision_id: str = Field(pattern=r"^legacyinventorypolicyrev_[0-9a-f]{32}$")
    scanner_policy_sha256: Sha256
    root_alias: LegacyRootAlias
    root_configuration_sha256: Sha256
    entries: tuple[LegacySourceInventoryEntry, ...] = Field(max_length=100000)
    summary: LegacySourceInventorySummary
    inventory_sha256: Sha256

    @model_validator(mode="after")
    def deterministic_inventory(self) -> LegacySourceInventory:
        entry_keys = tuple(entry.entry_key for entry in self.entries)
        paths = tuple(entry.relative_path for entry in self.entries)
        collision_keys = tuple(path.casefold() for path in paths)
        if len(entry_keys) != len(set(entry_keys)) or len(collision_keys) != len(
            set(collision_keys)
        ):
            raise ValueError("legacy inventory contains duplicate entry keys or path collisions")
        if paths != tuple(sorted(paths, key=lambda value: (value.casefold(), value))):
            raise ValueError("legacy inventory entries must use deterministic path order")
        class_fields = {
            LegacySourcePreliminaryClass.ORIGINAL_SOURCE_CANDIDATE: (
                self.summary.original_source_candidates
            ),
            LegacySourcePreliminaryClass.DERIVED_MIGRATION_EVIDENCE: (
                self.summary.derived_migration_evidence
            ),
            LegacySourcePreliminaryClass.EXCLUDED_RUNTIME_STATE: (
                self.summary.excluded_runtime_state
            ),
        }
        for classification, expected in class_fields.items():
            matching = tuple(
                entry for entry in self.entries if entry.preliminary_class == classification
            )
            if expected.file_count != len(matching) or expected.byte_count != sum(
                entry.size_bytes for entry in matching
            ):
                raise ValueError("legacy inventory class summary does not match entries")
        if self.summary.total_file_count != len(
            self.entries
        ) or self.summary.total_byte_count != sum(entry.size_bytes for entry in self.entries):
            raise ValueError("legacy inventory total summary does not match entries")
        _require_self_hash(self, "inventory_sha256")
        return self


class LegacyRightsReviewPointer(LegacyArtifactMemberPointer):
    schema_ref: Literal["eom://schemas/legacy-knowledge/rights-review/1.0"]
    media_type: Literal["application/json"]


class LegacySelectedOriginalSource(FrozenModel):
    entry_key: str = Field(pattern=r"^legacyentry_[0-9a-f]{32}$")
    content_sha256: Sha256
    canonicality: Literal["ORIGINAL"]
    reviewed_source_family: Literal[
        "CURRICULUM", "TEXTBOOK", "REFERENCE_BOOK", "GUIDANCE", "ITEM", "USAGE_WORKBOOK"
    ]
    declared_intake_role: Literal["REFERENCE", "GUIDELINE", "DATA", "ASSET", "OTHER"]
    intended_corpus_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    source_owner_reference: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    rights_state: Literal["CLEARED_INTERNAL", "CLEARED_LICENSED", "RESTRICTED"]
    rights_review: LegacyRightsReviewPointer


class LegacySelectedComparisonEvidence(FrozenModel):
    entry_key: str = Field(pattern=r"^legacyentry_[0-9a-f]{32}$")
    content_sha256: Sha256
    canonicality: Literal["DERIVED"]


class LegacySourceSelection(FrozenModel):
    schema_version: Literal["legacy-source-selection/1.0"]
    selection_id: str = Field(pattern=r"^legacyselection_[0-9a-f]{32}$")
    inventory_id: str = Field(pattern=r"^legacyinventory_[0-9a-f]{32}$")
    inventory_sha256: Sha256
    selected_sources: tuple[LegacySelectedOriginalSource, ...] = Field(min_length=1, max_length=500)
    comparison_evidence: tuple[LegacySelectedComparisonEvidence, ...] = Field(max_length=500)
    reviewed_at: UtcDatetime
    reviewed_by: ActorId
    selection_sha256: Sha256

    @model_validator(mode="after")
    def deterministic_selection(self) -> LegacySourceSelection:
        source_keys = tuple(source.entry_key for source in self.selected_sources)
        evidence_keys = tuple(evidence.entry_key for evidence in self.comparison_evidence)
        if len(source_keys) != len(set(source_keys)) or len(evidence_keys) != len(
            set(evidence_keys)
        ):
            raise ValueError("legacy selection entries must be unique")
        if set(source_keys) & set(evidence_keys):
            raise ValueError("original sources and comparison evidence cannot overlap")
        if source_keys != tuple(sorted(source_keys)) or evidence_keys != tuple(
            sorted(evidence_keys)
        ):
            raise ValueError("legacy selection entries must use deterministic key order")
        _require_self_hash(self, "selection_sha256")
        return self


class LegacySourcePageRange(FrozenModel):
    first_page: int = Field(ge=1, le=100000)
    last_page: int = Field(ge=1, le=100000)

    @model_validator(mode="after")
    def ordered_range(self) -> LegacySourcePageRange:
        if self.last_page < self.first_page:
            raise ValueError("legacy source page range is reversed")
        return self


class LegacyTransformationDescriptor(FrozenModel):
    implementation: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    version: str = Field(min_length=1, max_length=64)
    options_sha256: Sha256


class LegacySourceRelation(FrozenModel):
    relation_id: str = Field(pattern=r"^legacyrelation_[0-9a-f]{32}$")
    relation_kind: Literal[
        "DERIVED_FROM",
        "RENDERS_PAGE_FROM",
        "EXTRACTS_TEXT_FROM",
        "NORMALIZES_FROM",
        "LEGACY_ITEM_REPRESENTATION_OF",
        "EVALUATION_BASELINE_FOR",
    ]
    original: LegacySourcePointer
    derived: LegacySourcePointer
    transformation: LegacyTransformationDescriptor | None
    source_page_range: LegacySourcePageRange | None
    confidence_milli: int = Field(ge=0, le=1000)
    review_state: Literal["CONFIRMED", "UNRESOLVED", "REJECTED"]

    @model_validator(mode="after")
    def coherent_relation(self) -> LegacySourceRelation:
        if self.original == self.derived:
            raise ValueError("legacy source relation cannot point to itself")
        if self.relation_kind == "RENDERS_PAGE_FROM" and (
            self.source_page_range is None
            or self.source_page_range.first_page != self.source_page_range.last_page
        ):
            raise ValueError("rendered page relation requires exactly one source page")
        return self


class LegacySourceRelationManifest(FrozenModel):
    schema_version: Literal["legacy-source-relation-manifest/1.0"]
    relation_manifest_id: str = Field(pattern=r"^legacyrelationmanifest_[0-9a-f]{32}$")
    inventory_id: str = Field(pattern=r"^legacyinventory_[0-9a-f]{32}$")
    inventory_sha256: Sha256
    relations: tuple[LegacySourceRelation, ...] = Field(min_length=1, max_length=10000)
    reviewed_at: UtcDatetime
    reviewed_by: ActorId
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def deterministic_relations(self) -> LegacySourceRelationManifest:
        relation_ids = tuple(relation.relation_id for relation in self.relations)
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("legacy source relation IDs must be unique")
        if relation_ids != tuple(sorted(relation_ids)):
            raise ValueError("legacy source relations must use deterministic ID order")
        _require_self_hash(self, "manifest_sha256")
        return self


class PdfPageRangeMaterialization(FrozenModel):
    first_page: int = Field(ge=1, le=100000)
    last_page: int = Field(ge=1, le=100000)
    child: LegacyArtifactMemberPointer
    size_bytes: int = Field(ge=1, le=100 * 1024 * 1024)

    @model_validator(mode="after")
    def valid_child(self) -> PdfPageRangeMaterialization:
        if self.last_page < self.first_page:
            raise ValueError("PDF materialization page range is reversed")
        if self.child.media_type != "application/pdf":
            raise ValueError("PDF page-range child must use application/pdf")
        return self


class PdfPageRangeMaterializationManifest(FrozenModel):
    schema_version: Literal["pdf-page-range-materialization-manifest/1.0"]
    materialization_id: str = Field(pattern=r"^pdfmaterialization_[0-9a-f]{32}$")
    original: LegacyArtifactMemberPointer
    original_size_bytes: int = Field(ge=1, le=1 << 50)
    source_page_count: int = Field(ge=1, le=100000)
    renderer_implementation: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    renderer_version: str = Field(min_length=1, max_length=64)
    rendering_options_sha256: Sha256
    page_ranges: tuple[PdfPageRangeMaterialization, ...] = Field(min_length=1, max_length=10000)
    created_at: UtcDatetime
    created_by: ActorId
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def complete_page_coverage(self) -> PdfPageRangeMaterializationManifest:
        if self.original.media_type != "application/pdf":
            raise ValueError("PDF materialization original must use application/pdf")
        expected_first_page = 1
        child_identities: set[tuple[str, str, str]] = set()
        for page_range in self.page_ranges:
            if page_range.first_page != expected_first_page:
                raise ValueError("PDF materialization ranges must be contiguous and ordered")
            expected_first_page = page_range.last_page + 1
            identity = (
                page_range.child.artifact_id,
                page_range.child.artifact_revision_id,
                page_range.child.member_path,
            )
            if identity in child_identities:
                raise ValueError("PDF materialization child pointers must be unique")
            child_identities.add(identity)
        if expected_first_page != self.source_page_count + 1:
            raise ValueError("PDF materialization ranges must cover every source page")
        _require_self_hash(self, "manifest_sha256")
        return self
