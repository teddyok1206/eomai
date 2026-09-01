"""Application service for immutable organization, occurrence, and item-origin records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NoReturn, Protocol

from eom_catalog_contracts import (
    AssessmentOccurrencePointer,
    AssessmentOccurrenceRevision,
    ItemOriginDerivation,
    ItemOriginProfile,
    ItemOriginProvenance,
    OrganizationRevision,
    OrganizationRevisionPointer,
    OriginArtifactMemberPointer,
    RightsPolicyPointer,
    validate_contract,
)
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.database import build_session_factory, transaction
from eom_workflow_runner.models import WorkflowInstanceRecord
from jsonschema import ValidationError as JsonSchemaValidationError
from sqlalchemy import Engine, or_, select, text
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.item_origin_models import (
    AssessmentOccurrenceRecord,
    AssessmentOccurrenceRevisionRecord,
    AssessmentOccurrenceSourceEvidenceRecord,
    ItemOriginDerivationRecord,
    ItemOriginOccurrenceRecord,
    ItemOriginProfileRecord,
    ItemOriginProvenanceRecord,
    OrganizationAliasRecord,
    OrganizationRecord,
    OrganizationRevisionRecord,
    OrganizationSourceEvidenceRecord,
)
from eom_catalog_service.legacy_assessment_models import (
    AssessmentSourceBundleRecord,
    AssessmentSourceBundleRevisionRecord,
    LegacyItemExtractionAcceptanceRecord,
)
from eom_catalog_service.models import (
    ContentIntakeBatchRecord,
    EducationalDocumentRecord,
    EducationalDocumentRevisionRecord,
    ItemProvenanceRecord,
    ItemRecord,
    ItemRevisionRecord,
)
from eom_catalog_service.settings import CatalogSettings

MAX_ORIGIN_EVIDENCE_BYTES = 16 * 1024 * 1024


class RightsPolicyResolver(Protocol):
    """Narrow boundary owned by the future rights-policy registry."""

    def verify(
        self,
        pointer: RightsPolicyPointer,
        *,
        intended_use: Literal["ORIGIN_REGISTRATION", "ASSESSMENT_CORPUS_ANALYSIS"],
    ) -> None: ...


class ItemOriginRegistrationError(RuntimeError):
    """Stable fail-closed error raised at the item-origin application boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class OriginRevisionRegistration:
    logical_id: str
    revision_id: str
    prior_revision_id: str | None
    created: bool


@dataclass(frozen=True)
class ItemOriginRegistration:
    item_origin_profile_id: str
    item_id: str
    item_revision_id: str
    created: bool


class ItemOriginService:
    """Validate exact pointers, then append reviewed origin records transactionally."""

    def __init__(
        self,
        engine: Engine,
        *,
        rights: RightsPolicyResolver,
        settings: CatalogSettings | None = None,
        artifacts: CatalogArtifactService | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.rights = rights
        self.artifacts = artifacts or CatalogArtifactService(engine, settings)

    def register_organization(self, revision: OrganizationRevision) -> OriginRevisionRegistration:
        self._validate_contract("organization-revision", revision)
        if revision.revision_state != "REVIEWED":
            self._fail("ITEM_ORIGIN_STATE_INVALID", "new organization revision must be reviewed")
        self._verify_evidence(revision.source_evidence)
        self._verify_rights(revision.rights_policy)
        with transaction(self.sessions) as session:
            self._advisory_lock(session, f"organization:{revision.organization_key}")
            existing_revision = session.get(
                OrganizationRevisionRecord, revision.organization_revision_id
            )
            if existing_revision is not None:
                if (
                    existing_revision.organization_id != revision.organization_id
                    or existing_revision.revision_sha256 != revision.revision_sha256
                ):
                    self._fail("ITEM_ORIGIN_IDEMPOTENCY_CONFLICT", "organization revision differs")
                return OriginRevisionRegistration(
                    logical_id=revision.organization_id,
                    revision_id=revision.organization_revision_id,
                    prior_revision_id=revision.previous_revision_id,
                    created=False,
                )
            logical = session.scalar(
                select(OrganizationRecord)
                .where(
                    or_(
                        OrganizationRecord.organization_id == revision.organization_id,
                        OrganizationRecord.organization_key == revision.organization_key,
                    )
                )
                .with_for_update()
            )
            if logical is None:
                if revision.revision_number != 1 or revision.previous_revision_id is not None:
                    self._fail("ITEM_ORIGIN_REVISION_CONFLICT", "organization predecessor missing")
                logical = OrganizationRecord(
                    organization_id=revision.organization_id,
                    organization_key=revision.organization_key,
                    current_revision_id=None,
                    lifecycle_state="ACTIVE",
                    lock_version=1,
                    created_at=revision.created_at,
                    created_by=revision.created_by,
                )
                session.add(logical)
                session.flush()
            elif (
                logical.organization_id != revision.organization_id
                or logical.organization_key != revision.organization_key
                or logical.lifecycle_state != "ACTIVE"
            ):
                self._fail("ITEM_ORIGIN_IDENTITY_CONFLICT", "organization identity is unavailable")
            prior = self._require_next_organization_revision(session, logical, revision)
            session.add(self._organization_revision_record(revision))
            session.flush()
            for alias in revision.aliases:
                session.add(
                    OrganizationAliasRecord(
                        organization_revision_id=revision.organization_revision_id,
                        alias_kind=alias.alias_kind,
                        locale=alias.locale,
                        display_value=alias.display_value,
                        normalized_value=alias.normalized_value,
                    )
                )
            for evidence in revision.source_evidence:
                session.add(self._organization_evidence_record(revision, evidence))
            logical.current_revision_id = revision.organization_revision_id
            logical.lock_version += 1
            session.flush()
            return OriginRevisionRegistration(
                logical_id=revision.organization_id,
                revision_id=revision.organization_revision_id,
                prior_revision_id=prior,
                created=True,
            )

    def register_occurrence(
        self, revision: AssessmentOccurrenceRevision
    ) -> OriginRevisionRegistration:
        self._validate_contract("assessment-occurrence-revision", revision)
        if revision.revision_state != "REVIEWED":
            self._fail("ITEM_ORIGIN_STATE_INVALID", "new occurrence revision must be reviewed")
        self._verify_evidence(revision.source_evidence)
        self._verify_rights(revision.rights_policy)
        with transaction(self.sessions) as session:
            self._advisory_lock(session, f"occurrence:{revision.occurrence_key}")
            self._require_organization_pointer(session, revision.issuing_organization)
            existing_revision = session.get(
                AssessmentOccurrenceRevisionRecord,
                revision.assessment_occurrence_revision_id,
            )
            if existing_revision is not None:
                if (
                    existing_revision.assessment_occurrence_id != revision.assessment_occurrence_id
                    or existing_revision.revision_sha256 != revision.revision_sha256
                ):
                    self._fail("ITEM_ORIGIN_IDEMPOTENCY_CONFLICT", "occurrence revision differs")
                return OriginRevisionRegistration(
                    logical_id=revision.assessment_occurrence_id,
                    revision_id=revision.assessment_occurrence_revision_id,
                    prior_revision_id=revision.previous_revision_id,
                    created=False,
                )
            logical = session.scalar(
                select(AssessmentOccurrenceRecord)
                .where(
                    or_(
                        AssessmentOccurrenceRecord.assessment_occurrence_id
                        == revision.assessment_occurrence_id,
                        AssessmentOccurrenceRecord.occurrence_key == revision.occurrence_key,
                    )
                )
                .with_for_update()
            )
            if logical is None:
                if revision.revision_number != 1 or revision.previous_revision_id is not None:
                    self._fail("ITEM_ORIGIN_REVISION_CONFLICT", "occurrence predecessor missing")
                logical = AssessmentOccurrenceRecord(
                    assessment_occurrence_id=revision.assessment_occurrence_id,
                    occurrence_key=revision.occurrence_key,
                    current_revision_id=None,
                    lifecycle_state="ACTIVE",
                    lock_version=1,
                    created_at=revision.created_at,
                    created_by=revision.created_by,
                )
                session.add(logical)
                session.flush()
            elif (
                logical.assessment_occurrence_id != revision.assessment_occurrence_id
                or logical.occurrence_key != revision.occurrence_key
                or logical.lifecycle_state != "ACTIVE"
            ):
                self._fail("ITEM_ORIGIN_IDENTITY_CONFLICT", "occurrence identity is unavailable")
            prior = self._require_next_occurrence_revision(session, logical, revision)
            session.add(self._occurrence_revision_record(revision))
            session.flush()
            for evidence in revision.source_evidence:
                session.add(self._occurrence_evidence_record(revision, evidence))
            logical.current_revision_id = revision.assessment_occurrence_revision_id
            logical.lock_version += 1
            session.flush()
            return OriginRevisionRegistration(
                logical_id=revision.assessment_occurrence_id,
                revision_id=revision.assessment_occurrence_revision_id,
                prior_revision_id=prior,
                created=True,
            )

    def register_item_origin(self, profile: ItemOriginProfile) -> ItemOriginRegistration:
        self._validate_contract("item-origin-profile", profile)
        self._verify_rights(profile.rights_policy)
        with transaction(self.sessions) as session:
            self._advisory_lock(session, f"item-origin:{profile.item_revision.item_revision_id}")
            existing = session.get(ItemOriginProfileRecord, profile.item_origin_profile_id)
            by_item = session.scalar(
                select(ItemOriginProfileRecord).where(
                    ItemOriginProfileRecord.item_revision_id
                    == profile.item_revision.item_revision_id
                )
            )
            replay = existing or by_item
            if replay is not None:
                if (
                    replay.item_origin_profile_id != profile.item_origin_profile_id
                    or replay.profile_sha256 != profile.profile_sha256
                ):
                    self._fail("ITEM_ORIGIN_IDEMPOTENCY_CONFLICT", "item origin profile differs")
                return ItemOriginRegistration(
                    item_origin_profile_id=replay.item_origin_profile_id,
                    item_id=replay.item_id,
                    item_revision_id=replay.item_revision_id,
                    created=False,
                )
            self._require_item_revision(session, profile)
            organization = (
                self._require_organization_pointer(session, profile.source_organization)
                if profile.source_organization is not None
                else None
            )
            for occurrence_pointer in profile.assessment_occurrences:
                occurrence = self._require_occurrence_pointer(session, occurrence_pointer)
                if organization is not None and (
                    occurrence.issuing_organization_revision_id
                    != organization.organization_revision_id
                ):
                    self._fail(
                        "ITEM_ORIGIN_POINTER_MISMATCH",
                        "assessment occurrence issuer differs from source organization",
                    )
            for derivation in profile.derivations:
                self._require_derivation(session, profile, derivation)
            for provenance in profile.provenance:
                self._require_provenance(session, profile, provenance)
            session.add(self._profile_record(profile))
            session.flush()
            for occurrence_pointer in profile.assessment_occurrences:
                session.add(
                    ItemOriginOccurrenceRecord(
                        item_origin_profile_id=profile.item_origin_profile_id,
                        assessment_occurrence_id=occurrence_pointer.assessment_occurrence_id,
                        assessment_occurrence_revision_id=(
                            occurrence_pointer.assessment_occurrence_revision_id
                        ),
                        occurrence_revision_sha256=occurrence_pointer.occurrence_revision_sha256,
                    )
                )
            for derivation in profile.derivations:
                session.add(self._derivation_record(profile, derivation))
            for provenance in profile.provenance:
                session.add(self._provenance_record(profile, provenance))
            session.flush()
            return ItemOriginRegistration(
                item_origin_profile_id=profile.item_origin_profile_id,
                item_id=profile.item_revision.item_id,
                item_revision_id=profile.item_revision.item_revision_id,
                created=True,
            )

    def _verify_evidence(self, pointers: tuple[OriginArtifactMemberPointer, ...]) -> None:
        for pointer in pointers:
            try:
                self.artifacts.verify_member(
                    artifact_id=pointer.artifact_id,
                    revision_id=pointer.artifact_revision_id,
                    member_path=pointer.member_path,
                    sha256=pointer.sha256,
                    media_type=pointer.media_type,
                    schema_ref=pointer.schema_ref,
                    max_bytes=MAX_ORIGIN_EVIDENCE_BYTES,
                )
            except (OSError, ValueError) as exc:
                raise ItemOriginRegistrationError(
                    "ITEM_ORIGIN_ARTIFACT_POINTER_INVALID",
                    "origin evidence artifact pointer is invalid",
                ) from exc

    def _verify_rights(self, pointer: RightsPolicyPointer) -> None:
        try:
            self.rights.verify(pointer, intended_use="ORIGIN_REGISTRATION")
        except ItemOriginRegistrationError:
            raise
        except Exception as exc:
            raise ItemOriginRegistrationError(
                "ITEM_ORIGIN_RIGHTS_POLICY_INVALID",
                "rights policy pointer is unavailable or disallows registration",
            ) from exc

    @staticmethod
    def _validate_contract(
        name: str, value: OrganizationRevision | AssessmentOccurrenceRevision | ItemOriginProfile
    ) -> None:
        try:
            validate_contract(name, value.model_dump(mode="json"))
        except (JsonSchemaValidationError, ValueError) as exc:
            raise ItemOriginRegistrationError(
                "ITEM_ORIGIN_CONTRACT_INVALID", "item-origin contract is invalid"
            ) from exc

    @staticmethod
    def _advisory_lock(session: Session, key: str) -> None:
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key}
        )

    @staticmethod
    def _fail(code: str, message: str) -> NoReturn:
        raise ItemOriginRegistrationError(code, message)

    def _require_next_organization_revision(
        self,
        session: Session,
        logical: OrganizationRecord,
        revision: OrganizationRevision,
    ) -> str | None:
        prior = logical.current_revision_id
        if prior is None:
            if revision.revision_number != 1 or revision.previous_revision_id is not None:
                self._fail("ITEM_ORIGIN_REVISION_CONFLICT", "organization revision is not first")
            return None
        current = session.get(OrganizationRevisionRecord, prior)
        if (
            current is None
            or revision.previous_revision_id != prior
            or revision.revision_number != current.revision_number + 1
        ):
            self._fail("ITEM_ORIGIN_REVISION_CONFLICT", "organization revision is stale")
        return prior

    def _require_next_occurrence_revision(
        self,
        session: Session,
        logical: AssessmentOccurrenceRecord,
        revision: AssessmentOccurrenceRevision,
    ) -> str | None:
        prior = logical.current_revision_id
        if prior is None:
            if revision.revision_number != 1 or revision.previous_revision_id is not None:
                self._fail("ITEM_ORIGIN_REVISION_CONFLICT", "occurrence revision is not first")
            return None
        current = session.get(AssessmentOccurrenceRevisionRecord, prior)
        if (
            current is None
            or revision.previous_revision_id != prior
            or revision.revision_number != current.revision_number + 1
        ):
            self._fail("ITEM_ORIGIN_REVISION_CONFLICT", "occurrence revision is stale")
        return prior

    def _require_organization_pointer(
        self, session: Session, pointer: OrganizationRevisionPointer
    ) -> OrganizationRevisionRecord:
        logical = session.get(OrganizationRecord, pointer.organization_id)
        revision = session.get(OrganizationRevisionRecord, pointer.organization_revision_id)
        if (
            logical is None
            or revision is None
            or logical.lifecycle_state != "ACTIVE"
            or revision.organization_id != logical.organization_id
            or revision.revision_state not in {"REVIEWED", "SUPERSEDED"}
            or revision.revision_sha256 != pointer.revision_sha256
        ):
            self._fail("ITEM_ORIGIN_POINTER_STALE", "organization pointer does not resolve")
        return revision

    def _require_occurrence_pointer(
        self, session: Session, pointer: AssessmentOccurrencePointer
    ) -> AssessmentOccurrenceRevisionRecord:
        logical = session.get(AssessmentOccurrenceRecord, pointer.assessment_occurrence_id)
        revision = session.get(
            AssessmentOccurrenceRevisionRecord, pointer.assessment_occurrence_revision_id
        )
        if (
            logical is None
            or revision is None
            or logical.lifecycle_state != "ACTIVE"
            or revision.assessment_occurrence_id != logical.assessment_occurrence_id
            or revision.revision_state not in {"REVIEWED", "SUPERSEDED"}
            or revision.revision_sha256 != pointer.occurrence_revision_sha256
        ):
            self._fail("ITEM_ORIGIN_POINTER_STALE", "occurrence pointer does not resolve")
        return revision

    def _require_item_revision(self, session: Session, profile: ItemOriginProfile) -> None:
        pointer = profile.item_revision
        item = session.get(ItemRecord, pointer.item_id)
        revision = session.get(ItemRevisionRecord, pointer.item_revision_id)
        if (
            item is None
            or revision is None
            or item.lifecycle_state != "ACTIVE"
            or item.current_revision_id != revision.item_revision_id
            or revision.item_id != item.item_id
            or revision.revision_state != "APPROVED"
            or revision.manifest_sha256 != pointer.item_manifest_sha256
        ):
            self._fail(
                "ITEM_ORIGIN_POINTER_STALE", "target Item Revision is not current and approved"
            )

    def _require_derivation(
        self, session: Session, profile: ItemOriginProfile, pointer: ItemOriginDerivation
    ) -> None:
        if pointer.source_kind == "ITEM_REVISION":
            item = session.get(ItemRecord, pointer.logical_id)
            item_revision = session.get(ItemRevisionRecord, pointer.revision_id)
            valid = (
                item is not None
                and item_revision is not None
                and item.lifecycle_state in {"ACTIVE", "RETIRED"}
                and item_revision.item_id == item.item_id
                and item_revision.revision_state in {"APPROVED", "SUPERSEDED"}
                and item_revision.manifest_sha256 == pointer.manifest_sha256
                and item_revision.item_revision_id != profile.item_revision.item_revision_id
            )
        elif pointer.source_kind == "DOCUMENT_REVISION":
            document = session.get(EducationalDocumentRecord, pointer.logical_id)
            document_revision = session.get(EducationalDocumentRevisionRecord, pointer.revision_id)
            valid = (
                document is not None
                and document_revision is not None
                and document.lifecycle_state in {"ACTIVE", "RETIRED"}
                and document_revision.document_id == document.document_id
                and document_revision.revision_state == "APPROVED"
                and document_revision.revision_manifest_sha256 == pointer.manifest_sha256
            )
        else:
            bundle = session.get(AssessmentSourceBundleRecord, pointer.logical_id)
            bundle_revision = session.get(AssessmentSourceBundleRevisionRecord, pointer.revision_id)
            valid = (
                bundle is not None
                and bundle_revision is not None
                and bundle.lifecycle_state in {"ACTIVE", "RETIRED"}
                and bundle_revision.assessment_source_bundle_id
                == bundle.assessment_source_bundle_id
                and bundle_revision.state in {"REVIEWED", "SUPERSEDED"}
                and bundle_revision.bundle_manifest_sha256 == pointer.manifest_sha256
            )
        if not valid:
            self._fail("ITEM_ORIGIN_POINTER_STALE", "derivation pointer does not resolve")

    def _require_provenance(
        self, session: Session, profile: ItemOriginProfile, pointer: ItemOriginProvenance
    ) -> None:
        if pointer.provenance_kind == "WORKFLOW":
            workflow = session.get(WorkflowInstanceRecord, pointer.logical_id)
            plan = session.get(ResolvedExecutionPlanRecord, pointer.revision_id)
            valid = (
                workflow is not None
                and plan is not None
                and plan.workflow_id == workflow.workflow_id
                and workflow.state in {"REGISTERING", "COMPLETED"}
                and plan.plan_sha256 == pointer.evidence_sha256
            )
        elif pointer.provenance_kind == "CONTENT_INTAKE":
            intake = session.get(ContentIntakeBatchRecord, pointer.logical_id)
            valid = (
                intake is not None
                and intake.state in {"ACCEPTED", "IMPORTED"}
                and intake.source_manifest_artifact_revision_id == pointer.revision_id
                and intake.source_manifest_sha256 == pointer.evidence_sha256
            )
        elif pointer.provenance_kind == "ITEM_PROVENANCE":
            provenance = session.get(ItemProvenanceRecord, pointer.logical_id)
            valid = (
                provenance is not None
                and provenance.item_revision_id == profile.item_revision.item_revision_id
                and self._item_provenance_sha256(provenance) == pointer.evidence_sha256
            )
        else:
            acceptance = session.get(LegacyItemExtractionAcceptanceRecord, pointer.logical_id)
            valid = (
                acceptance is not None
                and acceptance.state in {"ACCEPTED", "ACCEPTED_WITH_CORRECTIONS"}
                and acceptance.acceptance_artifact_revision_id == pointer.revision_id
                and acceptance.acceptance_sha256 == pointer.evidence_sha256
            )
        if not valid:
            self._fail("ITEM_ORIGIN_POINTER_STALE", "provenance pointer does not resolve")

    @staticmethod
    def _item_provenance_sha256(record: ItemProvenanceRecord) -> str:
        return content_sha256(
            {
                "item_provenance_id": record.item_provenance_id,
                "item_revision_id": record.item_revision_id,
                "provenance_type": record.provenance_type,
                "source_key": record.source_key,
                "source_reference": record.source_reference,
                "source_intake_batch_id": record.source_intake_batch_id,
                "source_file_id": record.source_file_id,
                "source_artifact_id": record.source_artifact_id,
                "source_artifact_revision_id": record.source_artifact_revision_id,
                "source_sha256": record.source_sha256,
                "notes": record.notes,
            }
        )

    @staticmethod
    def _organization_revision_record(value: OrganizationRevision) -> OrganizationRevisionRecord:
        return OrganizationRevisionRecord(
            organization_revision_id=value.organization_revision_id,
            organization_id=value.organization_id,
            revision_number=value.revision_number,
            previous_revision_id=value.previous_revision_id,
            revision_state=value.revision_state,
            organization_class=value.organization_class,
            class_detail=value.class_detail,
            display_name=value.display_name,
            locale=value.locale,
            country_code=value.jurisdiction.country_code,
            jurisdiction_level=value.jurisdiction.level,
            jurisdiction_code=value.jurisdiction.jurisdiction_code,
            effective_from=value.effective_from,
            effective_to=value.effective_to,
            rights_policy_id=value.rights_policy.rights_policy_id,
            rights_policy_revision_id=value.rights_policy.rights_policy_revision_id,
            rights_policy_sha256=value.rights_policy.rights_policy_sha256,
            revision_sha256=value.revision_sha256,
            created_at=value.created_at,
            created_by=value.created_by,
        )

    @staticmethod
    def _organization_evidence_record(
        owner: OrganizationRevision, pointer: OriginArtifactMemberPointer
    ) -> OrganizationSourceEvidenceRecord:
        return OrganizationSourceEvidenceRecord(
            organization_revision_id=owner.organization_revision_id,
            artifact_id=pointer.artifact_id,
            artifact_revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            sha256=pointer.sha256,
        )

    @staticmethod
    def _occurrence_revision_record(
        value: AssessmentOccurrenceRevision,
    ) -> AssessmentOccurrenceRevisionRecord:
        return AssessmentOccurrenceRevisionRecord(
            assessment_occurrence_revision_id=value.assessment_occurrence_revision_id,
            assessment_occurrence_id=value.assessment_occurrence_id,
            revision_number=value.revision_number,
            previous_revision_id=value.previous_revision_id,
            revision_state=value.revision_state,
            issuing_organization_id=value.issuing_organization.organization_id,
            issuing_organization_revision_id=(value.issuing_organization.organization_revision_id),
            issuing_organization_revision_sha256=value.issuing_organization.revision_sha256,
            occurrence_kind=value.occurrence_kind,
            exam_family_key=value.exam_family_key,
            administration_year=value.administration_year,
            administration_date=value.administration_date,
            session_key=value.session_key,
            subject_key=value.subject_key,
            form_key=value.form_key,
            region_key=value.region_key,
            display_label=value.display_label,
            rights_policy_id=value.rights_policy.rights_policy_id,
            rights_policy_revision_id=value.rights_policy.rights_policy_revision_id,
            rights_policy_sha256=value.rights_policy.rights_policy_sha256,
            revision_sha256=value.revision_sha256,
            created_at=value.created_at,
            created_by=value.created_by,
        )

    @staticmethod
    def _occurrence_evidence_record(
        owner: AssessmentOccurrenceRevision, pointer: OriginArtifactMemberPointer
    ) -> AssessmentOccurrenceSourceEvidenceRecord:
        return AssessmentOccurrenceSourceEvidenceRecord(
            assessment_occurrence_revision_id=owner.assessment_occurrence_revision_id,
            artifact_id=pointer.artifact_id,
            artifact_revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            sha256=pointer.sha256,
        )

    @staticmethod
    def _profile_record(value: ItemOriginProfile) -> ItemOriginProfileRecord:
        organization = value.source_organization
        return ItemOriginProfileRecord(
            item_origin_profile_id=value.item_origin_profile_id,
            item_id=value.item_revision.item_id,
            item_revision_id=value.item_revision.item_revision_id,
            item_manifest_sha256=value.item_revision.item_manifest_sha256,
            source_domain=value.source_domain,
            creation_method=value.creation_method,
            source_organization_id=(None if organization is None else organization.organization_id),
            source_organization_revision_id=(
                None if organization is None else organization.organization_revision_id
            ),
            source_organization_revision_sha256=(
                None if organization is None else organization.revision_sha256
            ),
            rights_policy_id=value.rights_policy.rights_policy_id,
            rights_policy_revision_id=value.rights_policy.rights_policy_revision_id,
            rights_policy_sha256=value.rights_policy.rights_policy_sha256,
            profile_sha256=value.profile_sha256,
            created_at=value.created_at,
            created_by=value.created_by,
        )

    @staticmethod
    def _derivation_record(
        owner: ItemOriginProfile, value: ItemOriginDerivation
    ) -> ItemOriginDerivationRecord:
        return ItemOriginDerivationRecord(
            item_origin_profile_id=owner.item_origin_profile_id,
            source_kind=value.source_kind,
            logical_id=value.logical_id,
            revision_id=value.revision_id,
            manifest_sha256=value.manifest_sha256,
            relation=value.relation,
        )

    @staticmethod
    def _provenance_record(
        owner: ItemOriginProfile, value: ItemOriginProvenance
    ) -> ItemOriginProvenanceRecord:
        return ItemOriginProvenanceRecord(
            item_origin_profile_id=owner.item_origin_profile_id,
            provenance_kind=value.provenance_kind,
            logical_id=value.logical_id,
            revision_id=value.revision_id,
            evidence_sha256=value.evidence_sha256,
        )
