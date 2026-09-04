"""Immutable Organization, Assessment Occurrence, and Item Origin contracts."""

from __future__ import annotations

from datetime import date
from pathlib import PurePosixPath
from typing import Annotated, Literal

from eom_identifiers import content_sha256
from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256, UtcDatetime, _safe_text

StableKey = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")]


def _require_hash(model: FrozenModel, field_name: str) -> None:
    expected = content_sha256(model.model_dump(mode="json", exclude={field_name}))
    if getattr(model, field_name) != expected:
        raise ValueError(f"{field_name} does not match canonical content")


class OriginArtifactMemberPointer(FrozenModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: str = Field(min_length=1, max_length=512)
    schema_ref: str = Field(pattern=r"^eom://schemas/[A-Za-z0-9._/-]{1,220}$")
    media_type: str = Field(pattern=r"^[a-z0-9][a-z0-9.+-]*/[A-Za-z0-9][A-Za-z0-9.+-]*$")
    sha256: Sha256

    @field_validator("member_path")
    @classmethod
    def safe_member_path(cls, value: str) -> str:
        member = PurePosixPath(value)
        if (
            value.startswith("/")
            or "\\" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or member.as_posix() != value
        ):
            raise ValueError("artifact member path must be a safe relative POSIX path")
        return value


class RightsPolicyPointer(FrozenModel):
    rights_policy_id: str = Field(pattern=r"^rightspolicy_[0-9a-f]{32}$")
    rights_policy_revision_id: str = Field(pattern=r"^rightspolicyrev_[0-9a-f]{32}$")
    rights_policy_sha256: Sha256


class OrganizationRevisionPointer(FrozenModel):
    organization_id: str = Field(pattern=r"^org_[0-9a-f]{32}$")
    organization_revision_id: str = Field(pattern=r"^orgrev_[0-9a-f]{32}$")
    revision_sha256: Sha256


class AssessmentOccurrencePointer(FrozenModel):
    assessment_occurrence_id: str = Field(pattern=r"^occurrence_[0-9a-f]{32}$")
    assessment_occurrence_revision_id: str = Field(pattern=r"^occurrev_[0-9a-f]{32}$")
    occurrence_revision_sha256: Sha256


class OriginItemRevisionPointer(FrozenModel):
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: Sha256


class OrganizationJurisdiction(FrozenModel):
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    level: Literal[
        "NATIONAL",
        "PROVINCE",
        "METROPOLITAN",
        "CITY",
        "COUNTY",
        "DISTRICT",
        "INSTITUTION",
        "OTHER",
    ]
    jurisdiction_code: str | None = Field(default=None, max_length=64)

    _text = field_validator("jurisdiction_code")(
        lambda value: None if value is None else _safe_text(value)
    )


class OrganizationAlias(FrozenModel):
    alias_kind: Literal["OFFICIAL", "ABBREVIATION", "FORMER", "LEGACY_SOURCE"]
    locale: str = Field(pattern=r"^[a-z]{2}-[A-Z]{2}$")
    display_value: str = Field(min_length=1, max_length=256)
    normalized_value: str = Field(min_length=1, max_length=256)

    _text = field_validator("display_value", "normalized_value")(_safe_text)


class OrganizationRevision(FrozenModel):
    schema_version: Literal["organization-revision/1.0"]
    organization_id: str = Field(pattern=r"^org_[0-9a-f]{32}$")
    organization_revision_id: str = Field(pattern=r"^orgrev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1)
    previous_revision_id: str | None = Field(default=None, pattern=r"^orgrev_[0-9a-f]{32}$")
    organization_key: StableKey
    revision_state: Literal["REVIEWED", "SUPERSEDED", "RETIRED"]
    organization_class: Literal[
        "EOM_INTERNAL",
        "NATIONAL_ASSESSMENT_AGENCY",
        "EDUCATION_AUTHORITY",
        "SCHOOL",
        "UNIVERSITY",
        "PUBLISHER",
        "PRIVATE_EDUCATION_PROVIDER",
        "OTHER_REVIEWED",
    ]
    class_detail: str | None = Field(default=None, max_length=256)
    display_name: str = Field(min_length=1, max_length=256)
    locale: str = Field(pattern=r"^[a-z]{2}-[A-Z]{2}$")
    jurisdiction: OrganizationJurisdiction
    aliases: tuple[OrganizationAlias, ...] = Field(max_length=64)
    effective_from: date | None
    effective_to: date | None
    source_evidence: tuple[OriginArtifactMemberPointer, ...] = Field(min_length=1, max_length=64)
    rights_policy: RightsPolicyPointer
    created_at: UtcDatetime
    created_by: ActorId
    revision_sha256: Sha256

    _text = field_validator("class_detail", "display_name")(
        lambda value: None if value is None else _safe_text(value)
    )

    @model_validator(mode="after")
    def closed_revision(self) -> OrganizationRevision:
        if (self.revision_number == 1) != (self.previous_revision_id is None):
            raise ValueError("organization predecessor must be null only for revision one")
        if (self.organization_class == "OTHER_REVIEWED") != (self.class_detail is not None):
            raise ValueError("only OTHER_REVIEWED organization requires class detail")
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("organization effective interval is reversed")
        aliases = tuple((value.locale, value.normalized_value.casefold()) for value in self.aliases)
        if len(aliases) != len(set(aliases)):
            raise ValueError("organization aliases must be unique within a locale")
        evidence = tuple(
            (value.artifact_revision_id, value.member_path) for value in self.source_evidence
        )
        if len(evidence) != len(set(evidence)):
            raise ValueError("organization source evidence pointers must be unique")
        _require_hash(self, "revision_sha256")
        return self


class AssessmentOccurrenceRevision(FrozenModel):
    schema_version: Literal["assessment-occurrence-revision/1.0"]
    assessment_occurrence_id: str = Field(pattern=r"^occurrence_[0-9a-f]{32}$")
    assessment_occurrence_revision_id: str = Field(pattern=r"^occurrev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1)
    previous_revision_id: str | None = Field(default=None, pattern=r"^occurrev_[0-9a-f]{32}$")
    occurrence_key: StableKey
    revision_state: Literal["REVIEWED", "SUPERSEDED", "WITHDRAWN"]
    issuing_organization: OrganizationRevisionPointer
    occurrence_kind: Literal[
        "NATIONAL_ENTRANCE",
        "NATIONAL_ACHIEVEMENT",
        "EDUCATION_AUTHORITY_EXAM",
        "SCHOOL_EXAM",
        "INSTITUTIONAL_EXAM",
        "OTHER_REVIEWED",
    ]
    exam_family_key: StableKey
    administration_year: int = Field(ge=1900, le=2200)
    administration_date: date | None
    session_key: StableKey | None
    subject_key: StableKey
    form_key: StableKey | None
    region_key: StableKey | None
    display_label: str = Field(min_length=1, max_length=512)
    source_evidence: tuple[OriginArtifactMemberPointer, ...] = Field(min_length=1, max_length=64)
    rights_policy: RightsPolicyPointer
    created_at: UtcDatetime
    created_by: ActorId
    revision_sha256: Sha256

    _text = field_validator("display_label")(_safe_text)

    @model_validator(mode="after")
    def closed_revision(self) -> AssessmentOccurrenceRevision:
        if (self.revision_number == 1) != (self.previous_revision_id is None):
            raise ValueError("occurrence predecessor must be null only for revision one")
        if (
            self.administration_date is not None
            and self.administration_date.year != self.administration_year
        ):
            raise ValueError("occurrence date must match administration year")
        evidence = tuple(
            (value.artifact_revision_id, value.member_path) for value in self.source_evidence
        )
        if len(evidence) != len(set(evidence)):
            raise ValueError("occurrence source evidence pointers must be unique")
        _require_hash(self, "revision_sha256")
        return self


class ItemOriginDerivation(FrozenModel):
    source_kind: Literal["ITEM_REVISION", "DOCUMENT_REVISION", "ASSESSMENT_SOURCE_BUNDLE_REVISION"]
    logical_id: str = Field(pattern=r"^[a-z][a-z0-9]*_[0-9a-f]{32}$")
    revision_id: str = Field(pattern=r"^[a-z][a-z0-9]*_[0-9a-f]{32}$")
    manifest_sha256: Sha256
    relation: Literal["DERIVED_FROM", "TRANSLATED_FROM", "DIGITIZED_FROM", "RECONSTRUCTED_FROM"]

    @model_validator(mode="after")
    def typed_source_pointer(self) -> ItemOriginDerivation:
        expected_prefixes = {
            "ITEM_REVISION": ("item_", "itemrev_"),
            "DOCUMENT_REVISION": ("edudoc_", "edudocrev_"),
            "ASSESSMENT_SOURCE_BUNDLE_REVISION": ("assessbundle_", "assessbundlerev_"),
        }
        logical_prefix, revision_prefix = expected_prefixes[self.source_kind]
        if not self.logical_id.startswith(logical_prefix) or not self.revision_id.startswith(
            revision_prefix
        ):
            raise ValueError("item origin derivation kind does not match its pointer identity")
        return self


class ItemOriginProvenance(FrozenModel):
    provenance_kind: Literal[
        "WORKFLOW",
        "CONTENT_INTAKE",
        "ITEM_PROVENANCE",
        "MANUAL_REVIEW",
        "EXTRACTION_ACCEPTANCE",
    ]
    logical_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
    revision_id: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
    evidence_sha256: Sha256

    @model_validator(mode="after")
    def typed_evidence_pointer(self) -> ItemOriginProvenance:
        required_prefixes = {
            "WORKFLOW": ("workflow_", "execplan_"),
            "CONTENT_INTAKE": ("intake_", "rev_"),
            "MANUAL_REVIEW": ("itemacceptance_", "rev_"),
            "EXTRACTION_ACCEPTANCE": ("itemacceptance_", "rev_"),
        }
        if self.provenance_kind == "ITEM_PROVENANCE":
            if not self.logical_id.startswith("provenance_") or self.revision_id is not None:
                raise ValueError("item provenance evidence must reference its immutable row")
            return self
        logical_prefix, revision_prefix = required_prefixes[self.provenance_kind]
        if (
            not self.logical_id.startswith(logical_prefix)
            or self.revision_id is None
            or not self.revision_id.startswith(revision_prefix)
        ):
            raise ValueError("item origin provenance kind does not match its evidence pointer")
        return self


class ItemOriginProfile(FrozenModel):
    schema_version: Literal["item-origin-profile/1.0"]
    item_origin_profile_id: str = Field(pattern=r"^originprofile_[0-9a-f]{32}$")
    item_revision: OriginItemRevisionPointer
    source_domain: Literal[
        "INTERNAL_EOM", "EXTERNAL_INSTITUTION", "EXTERNAL_INDIVIDUAL", "LEGACY_UNKNOWN"
    ]
    creation_method: Literal[
        "HUMAN_AUTHORED", "AI_ASSISTED", "AI_GENERATED", "IMPORTED", "ADAPTED", "UNKNOWN"
    ]
    source_organization: OrganizationRevisionPointer | None
    assessment_occurrences: tuple[AssessmentOccurrencePointer, ...] = Field(max_length=32)
    derivations: tuple[ItemOriginDerivation, ...] = Field(max_length=64)
    rights_policy: RightsPolicyPointer
    provenance: tuple[ItemOriginProvenance, ...] = Field(min_length=1, max_length=64)
    created_at: UtcDatetime
    created_by: ActorId
    profile_sha256: Sha256

    @model_validator(mode="after")
    def coherent_profile(self) -> ItemOriginProfile:
        if self.source_domain in {"INTERNAL_EOM", "EXTERNAL_INSTITUTION"} and (
            self.source_organization is None
        ):
            raise ValueError("institutional origin requires a source organization")
        if self.source_domain == "LEGACY_UNKNOWN" and self.creation_method not in {
            "IMPORTED",
            "UNKNOWN",
        }:
            raise ValueError("legacy-unknown origin supports only imported or unknown creation")
        provenance_kinds = {value.provenance_kind for value in self.provenance}
        if self.creation_method in {"AI_ASSISTED", "AI_GENERATED"} and (
            "WORKFLOW" not in provenance_kinds
        ):
            raise ValueError("AI origin requires workflow provenance")
        if self.creation_method == "IMPORTED" and "CONTENT_INTAKE" not in provenance_kinds:
            raise ValueError("imported origin requires Content Intake provenance")
        if self.creation_method == "ADAPTED" and not self.derivations:
            raise ValueError("adapted origin requires a derivation pointer")
        if self.source_domain == "EXTERNAL_INDIVIDUAL" and not provenance_kinds.intersection(
            {"MANUAL_REVIEW", "EXTRACTION_ACCEPTANCE", "CONTENT_INTAKE"}
        ):
            raise ValueError("individual origin requires reviewed source provenance")
        occurrences = tuple(
            value.assessment_occurrence_revision_id for value in self.assessment_occurrences
        )
        if occurrences != tuple(sorted(set(occurrences))):
            raise ValueError("assessment occurrence pointers must be sorted and unique")
        derivations = tuple(
            (value.source_kind, value.logical_id, value.revision_id) for value in self.derivations
        )
        if len(derivations) != len(set(derivations)):
            raise ValueError("item origin derivation pointers must be unique")
        provenance = tuple(
            (value.provenance_kind, value.logical_id, value.revision_id)
            for value in self.provenance
        )
        if len(provenance) != len(set(provenance)):
            raise ValueError("item origin provenance pointers must be unique")
        _require_hash(self, "profile_sha256")
        return self
