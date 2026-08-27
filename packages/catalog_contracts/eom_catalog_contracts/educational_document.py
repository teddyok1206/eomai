"""Contracts for source-bound educational documents and immutable revisions."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Literal, Self

from eom_identifiers import content_sha256
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from eom_catalog_contracts.legacy_knowledge import LegacyArtifactMemberPointer


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must use UTC")
    return value


def _safe_text(value: str) -> str:
    if value != value.strip() or any(
        ord(character) < 32 and character not in "\t\n\r" for character in value
    ):
        raise ValueError("text must be normalized and free of control characters")
    return value


def _require_self_hash(model: BaseModel, field_name: str) -> None:
    expected = content_sha256(model.model_dump(mode="json", exclude={field_name}))
    if getattr(model, field_name) != expected:
        raise ValueError(f"{field_name} does not match canonical contract content")


UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
ActorId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]
DocumentId = Annotated[str, Field(pattern=r"^edudoc_[0-9a-f]{32}$")]
DocumentRevisionId = Annotated[str, Field(pattern=r"^edudocrev_[0-9a-f]{32}$")]
RightsAttestationId = Annotated[str, Field(pattern=r"^edurights_[0-9a-f]{32}$")]
DocumentKey = Annotated[
    str,
    Field(pattern=r"^[a-z][a-z0-9-]{2,127}$", min_length=3, max_length=128),
]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class EducationalDocumentIdentity(FrozenModel):
    document_key: DocumentKey
    document_kind: Literal["TEXTBOOK", "REFERENCE_BOOK", "CURRICULUM", "GUIDANCE"]
    publisher_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    publisher_label: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    curriculum_volume: Literal["I", "II"] | None
    edition_label: str = Field(min_length=1, max_length=100)
    language: Literal["ko-KR"] = "ko-KR"

    _text = field_validator("publisher_label", "title", "edition_label")(_safe_text)

    @model_validator(mode="after")
    def textbook_has_volume(self) -> Self:
        if self.document_kind == "TEXTBOOK" and self.curriculum_volume is None:
            raise ValueError("textbook identity requires a curriculum volume")
        return self


class EducationalDocumentRightsAttestation(FrozenModel):
    schema_version: Literal["educational-document-rights-attestation/1.0"] = (
        "educational-document-rights-attestation/1.0"
    )
    rights_attestation_id: RightsAttestationId
    source_sha256: Sha256
    source_media_type: Literal["application/pdf"] = "application/pdf"
    rights_state: Literal["CLEARED_LICENSED"] = "CLEARED_LICENSED"
    basis: Literal["PURCHASED_AND_NEGOTIATED"] = "PURCHASED_AND_NEGOTIATED"
    permitted_uses: tuple[
        Literal[
            "INTERNAL_ARCHIVAL",
            "TEXT_EXTRACTION",
            "KNOWLEDGE_ANALYSIS",
            "GRAPH_INDEXING",
            "ITEM_AUTHORING_GROUNDING",
            "INTERNAL_REVIEW",
        ],
        ...,
    ] = Field(min_length=1, max_length=6)
    allowed_roles: tuple[
        Literal[
            "ADMIN",
            "RIGHTS_REVIEWER",
            "DATA_ANALYST_WORKER",
            "ITEM_AUTHORING_WORKER",
            "HUMAN_EDITOR",
        ],
        ...,
    ] = Field(min_length=1, max_length=5)
    answer_bearing: bool
    attribution_required: bool
    retention_policy_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    withdrawal_behavior: Literal["RETIRE_FROM_NEW_RETRIEVAL"] = "RETIRE_FROM_NEW_RETRIEVAL"
    confirmation_reference: str = Field(min_length=8, max_length=200)
    reviewed_at: UtcDatetime
    reviewed_by: ActorId
    rights_attestation_sha256: Sha256

    _text = field_validator("confirmation_reference")(_safe_text)

    @model_validator(mode="after")
    def coherent_attestation(self) -> Self:
        uses = tuple(self.permitted_uses)
        roles = tuple(self.allowed_roles)
        if uses != tuple(sorted(uses)) or len(uses) != len(set(uses)):
            raise ValueError("permitted uses must be sorted and unique")
        if roles != tuple(sorted(roles)) or len(roles) != len(set(roles)):
            raise ValueError("allowed roles must be sorted and unique")
        required_uses = {
            "INTERNAL_ARCHIVAL",
            "TEXT_EXTRACTION",
            "KNOWLEDGE_ANALYSIS",
            "GRAPH_INDEXING",
            "ITEM_AUTHORING_GROUNDING",
            "INTERNAL_REVIEW",
        }
        required_roles = {"ADMIN", "DATA_ANALYST_WORKER", "ITEM_AUTHORING_WORKER"}
        if set(uses) != required_uses or not required_roles.issubset(set(roles)):
            raise ValueError("licensed textbook attestation omits a required internal use or role")
        _require_self_hash(self, "rights_attestation_sha256")
        return self


class EducationalDocumentRegistrationRequest(FrozenModel):
    schema_version: Literal["educational-document-registration-request/1.0"] = (
        "educational-document-registration-request/1.0"
    )
    identity: EducationalDocumentIdentity
    expected_source_sha256: Sha256
    expected_source_size_bytes: int = Field(ge=1, le=1024 * 1024 * 1024)
    expected_source_page_count: int = Field(ge=1, le=100000)
    expected_analysis_manifest_sha256: Sha256
    rights: EducationalDocumentRightsAttestation
    registration_key: str = Field(min_length=16, max_length=200, pattern=r"^[\x21-\x7e]+$")
    registered_at: UtcDatetime
    registered_by: ActorId
    request_sha256: Sha256

    @model_validator(mode="after")
    def coherent_request(self) -> Self:
        if self.rights.source_sha256 != self.expected_source_sha256:
            raise ValueError("rights attestation does not bind the requested source")
        if self.rights.reviewed_by != self.registered_by:
            raise ValueError("rights reviewer and registering actor must match")
        _require_self_hash(self, "request_sha256")
        return self


class EducationalDocumentRegistrationRequestV2(EducationalDocumentRegistrationRequest):
    """Registration request for an analysis bundle with complete page-image coverage."""

    schema_version: Literal["educational-document-registration-request/2.0"] = (
        "educational-document-registration-request/2.0"  # type: ignore[assignment]
    )
    expected_analysis_schema_ref: Literal[
        "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/2.0"
    ] = "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/2.0"


class EducationalDocumentRevisionManifest(FrozenModel):
    schema_version: Literal["educational-document-revision-manifest/1.0"] = (
        "educational-document-revision-manifest/1.0"
    )
    document_id: DocumentId
    document_revision_id: DocumentRevisionId
    revision_number: int = Field(ge=1, le=100000)
    previous_revision_id: DocumentRevisionId | None
    identity: EducationalDocumentIdentity
    source: LegacyArtifactMemberPointer
    source_size_bytes: int = Field(ge=1, le=1024 * 1024 * 1024)
    source_page_count: int = Field(ge=1, le=100000)
    analysis_bundle_manifest: LegacyArtifactMemberPointer
    analysis_bundle_root: Literal["analysis"] = "analysis"
    rights_attestation: LegacyArtifactMemberPointer
    registered_at: UtcDatetime
    registered_by: ActorId
    registration_request_sha256: Sha256
    document_revision_sha256: Sha256

    @model_validator(mode="after")
    def coherent_revision(self) -> Self:
        if self.revision_number == 1 and self.previous_revision_id is not None:
            raise ValueError("first document revision cannot have a predecessor")
        if self.revision_number > 1 and self.previous_revision_id is None:
            raise ValueError("later document revision requires a predecessor")
        expected_analysis_schema = (
            "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/2.0"
            if isinstance(self, EducationalDocumentRevisionManifestV2)
            else "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/1.0"
        )
        if (
            self.source.media_type != "application/pdf"
            or self.source.schema_ref != "eom://schemas/educational-document/pdf-source/1.0"
            or self.analysis_bundle_manifest.media_type != "application/json"
            or self.analysis_bundle_manifest.schema_ref != expected_analysis_schema
            or self.rights_attestation.media_type != "application/json"
            or self.rights_attestation.schema_ref
            != "eom://schemas/educational-document/rights-attestation/1.0"
        ):
            raise ValueError("document revision Artifact member contract is invalid")
        _require_self_hash(self, "document_revision_sha256")
        return self


class EducationalDocumentRevisionManifestV2(EducationalDocumentRevisionManifest):
    schema_version: Literal["educational-document-revision-manifest/2.0"] = (
        "educational-document-revision-manifest/2.0"  # type: ignore[assignment]
    )


class EducationalDocumentRegistrationReceipt(FrozenModel):
    schema_version: Literal["educational-document-registration-receipt/1.0"] = (
        "educational-document-registration-receipt/1.0"
    )
    document_id: DocumentId
    document_revision_id: DocumentRevisionId
    revision_number: int = Field(ge=1, le=100000)
    registration_request_sha256: Sha256
    revision_manifest: LegacyArtifactMemberPointer
    source: LegacyArtifactMemberPointer
    analysis_bundle_manifest: LegacyArtifactMemberPointer
    rights_attestation: LegacyArtifactMemberPointer


class EducationalDocumentRegistrationReceiptV2(EducationalDocumentRegistrationReceipt):
    schema_version: Literal["educational-document-registration-receipt/2.0"] = (
        "educational-document-registration-receipt/2.0"  # type: ignore[assignment]
    )

    @model_validator(mode="after")
    def exact_multimodal_pointer_versions(self) -> EducationalDocumentRegistrationReceiptV2:
        if (
            self.analysis_bundle_manifest.schema_ref
            != "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/2.0"
            or self.revision_manifest.schema_ref
            != "eom://schemas/educational-document/revision-manifest/2.0"
        ):
            raise ValueError("multimodal document receipt pointer schema is inconsistent")
        return self
