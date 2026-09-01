"""Application service for reviewed legacy-assessment bundles and extraction evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, NoReturn

from eom_catalog_contracts import (
    AssessmentArtifactMemberPointer,
    AssessmentLayoutObservation,
    AssessmentLayoutObservationPointer,
    AssessmentSourceBundlePointer,
    AssessmentSourceBundleRevision,
    LegacyItemCorpusCoverage,
    LegacyItemExtractionAcceptance,
    LegacyItemExtractionResult,
    validate_contract,
)
from eom_orchestrator.database import build_session_factory, transaction
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine, or_, select, text
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.item_origin_models import (
    AssessmentOccurrenceRecord,
    AssessmentOccurrenceRevisionRecord,
)
from eom_catalog_service.item_origin_service import RightsPolicyResolver
from eom_catalog_service.legacy_assessment_models import (
    AssessmentLayoutObservationRecord,
    AssessmentSourceBundleMemberRecord,
    AssessmentSourceBundleRecord,
    AssessmentSourceBundleRevisionRecord,
    LegacyItemCorpusBundleCoverageRecord,
    LegacyItemCorpusCoverageRecord,
    LegacyItemExtractionAcceptanceRecord,
    LegacyItemExtractionDecisionRecord,
)
from eom_catalog_service.settings import CatalogSettings

MAX_ASSESSMENT_CONTROL_BYTES = 32 * 1024 * 1024
MAX_ASSESSMENT_SOURCE_MEMBER_BYTES = 512 * 1024 * 1024


class LegacyAssessmentRegistryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LegacyAssessmentRegistration:
    logical_id: str
    revision_id: str | None
    created: bool


class LegacyAssessmentRegistry:
    """Append only after schema, artifact, rights, and cross-pointer validation."""

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

    def register_bundle(
        self, revision: AssessmentSourceBundleRevision
    ) -> LegacyAssessmentRegistration:
        self._validate_contract("assessment-source-bundle", revision)
        if revision.state != "REVIEWED":
            self._fail("LEGACY_ASSESSMENT_STATE_INVALID", "new bundle revision must be reviewed")
        self._verify_member(revision.inventory_artifact, MAX_ASSESSMENT_CONTROL_BYTES)
        for member in revision.members:
            self._verify_member(member.source, MAX_ASSESSMENT_SOURCE_MEMBER_BYTES)
        self._verify_rights(revision)
        with transaction(self.sessions) as session:
            self._lock(session, f"assessment-bundle:{revision.bundle_key}")
            self._require_occurrence(session, revision)
            existing_revision = session.get(
                AssessmentSourceBundleRevisionRecord,
                revision.assessment_source_bundle_revision_id,
            )
            if existing_revision is not None:
                if (
                    existing_revision.assessment_source_bundle_id
                    != revision.assessment_source_bundle_id
                    or existing_revision.bundle_manifest_sha256 != revision.bundle_manifest_sha256
                ):
                    self._fail(
                        "LEGACY_ASSESSMENT_IDEMPOTENCY_CONFLICT",
                        "bundle revision identity differs",
                    )
                return LegacyAssessmentRegistration(
                    logical_id=revision.assessment_source_bundle_id,
                    revision_id=revision.assessment_source_bundle_revision_id,
                    created=False,
                )
            logical = session.scalar(
                select(AssessmentSourceBundleRecord)
                .where(
                    or_(
                        AssessmentSourceBundleRecord.assessment_source_bundle_id
                        == revision.assessment_source_bundle_id,
                        AssessmentSourceBundleRecord.bundle_key == revision.bundle_key,
                    )
                )
                .with_for_update()
            )
            if logical is None:
                if revision.revision_number != 1 or revision.previous_revision_id is not None:
                    self._fail(
                        "LEGACY_ASSESSMENT_REVISION_CONFLICT", "bundle predecessor is missing"
                    )
                logical = AssessmentSourceBundleRecord(
                    assessment_source_bundle_id=revision.assessment_source_bundle_id,
                    bundle_key=revision.bundle_key,
                    current_revision_id=None,
                    lifecycle_state="ACTIVE",
                    lock_version=1,
                    created_at=revision.reviewed_at,
                    created_by=revision.reviewed_by,
                )
                session.add(logical)
                session.flush()
            elif (
                logical.assessment_source_bundle_id != revision.assessment_source_bundle_id
                or logical.bundle_key != revision.bundle_key
                or logical.lifecycle_state != "ACTIVE"
            ):
                self._fail("LEGACY_ASSESSMENT_IDENTITY_CONFLICT", "bundle identity is unavailable")
            self._require_next_bundle_revision(session, logical, revision)
            session.add(self._bundle_revision_record(revision))
            session.flush()
            for ordinal, member in enumerate(revision.members):
                session.add(
                    AssessmentSourceBundleMemberRecord(
                        assessment_source_bundle_member_id=member.member_id,
                        assessment_source_bundle_revision_id=(
                            revision.assessment_source_bundle_revision_id
                        ),
                        ordinal=ordinal,
                        role=member.role,
                        source_artifact_id=member.source.artifact_id,
                        source_artifact_revision_id=member.source.artifact_revision_id,
                        source_member_path=member.source.member_path,
                        source_schema_ref=member.source.schema_ref,
                        source_media_type=member.source.media_type,
                        source_sha256=member.source.sha256,
                        inventory_id=member.inventory_source.inventory_id,
                        inventory_sha256=member.inventory_source.inventory_sha256,
                        inventory_entry_key=member.inventory_source.entry_key,
                        inventory_content_sha256=member.inventory_source.content_sha256,
                    )
                )
            logical.current_revision_id = revision.assessment_source_bundle_revision_id
            logical.lock_version += 1
            session.flush()
            return LegacyAssessmentRegistration(
                logical_id=revision.assessment_source_bundle_id,
                revision_id=revision.assessment_source_bundle_revision_id,
                created=True,
            )

    def register_layout(
        self, pointer: AssessmentLayoutObservationPointer
    ) -> LegacyAssessmentRegistration:
        value = self._load_member_json(pointer.artifact)
        self._validate_mapping("assessment-layout-observation", value)
        try:
            observation = AssessmentLayoutObservation.model_validate(value)
        except PydanticValidationError as exc:
            raise LegacyAssessmentRegistryError(
                "LEGACY_ASSESSMENT_CONTRACT_INVALID", "layout observation is invalid"
            ) from exc
        if (
            observation.assessment_layout_observation_id != pointer.assessment_layout_observation_id
            or observation.observation_sha256 != pointer.observation_sha256
        ):
            self._fail(
                "LEGACY_ASSESSMENT_POINTER_MISMATCH", "layout pointer differs from its document"
            )
        with transaction(self.sessions) as session:
            self._require_bundle_pointer(session, observation.bundle)
            existing = session.get(
                AssessmentLayoutObservationRecord,
                observation.assessment_layout_observation_id,
            )
            if existing is not None:
                if (
                    existing.observation_sha256 != observation.observation_sha256
                    or existing.artifact_revision_id != pointer.artifact.artifact_revision_id
                    or existing.artifact_member_path != pointer.artifact.member_path
                ):
                    self._fail(
                        "LEGACY_ASSESSMENT_IDEMPOTENCY_CONFLICT",
                        "layout observation identity differs",
                    )
                return LegacyAssessmentRegistration(
                    logical_id=observation.assessment_layout_observation_id,
                    revision_id=pointer.artifact.artifact_revision_id,
                    created=False,
                )
            session.add(
                AssessmentLayoutObservationRecord(
                    assessment_layout_observation_id=(observation.assessment_layout_observation_id),
                    assessment_source_bundle_id=(observation.bundle.assessment_source_bundle_id),
                    assessment_source_bundle_revision_id=(
                        observation.bundle.assessment_source_bundle_revision_id
                    ),
                    bundle_manifest_sha256=observation.bundle.bundle_manifest_sha256,
                    artifact_id=pointer.artifact.artifact_id,
                    artifact_revision_id=pointer.artifact.artifact_revision_id,
                    artifact_member_path=pointer.artifact.member_path,
                    artifact_schema_ref=pointer.artifact.schema_ref,
                    artifact_media_type=pointer.artifact.media_type,
                    artifact_sha256=pointer.artifact.sha256,
                    expected_item_count=len(observation.expected_item_numbers),
                    observation_sha256=observation.observation_sha256,
                    created_at=observation.created_at,
                )
            )
            session.flush()
            return LegacyAssessmentRegistration(
                logical_id=observation.assessment_layout_observation_id,
                revision_id=pointer.artifact.artifact_revision_id,
                created=True,
            )

    def register_acceptance(
        self,
        acceptance: LegacyItemExtractionAcceptance,
        *,
        acceptance_artifact: AssessmentArtifactMemberPointer,
    ) -> LegacyAssessmentRegistration:
        self._validate_contract("legacy-item-extraction-acceptance", acceptance)
        self._require_control_artifact_contract(
            acceptance_artifact,
            schema_ref=("eom://schemas/legacy-assessment/legacy-item-extraction-acceptance/1.0"),
        )
        raw_result = self._load_member_json(acceptance.extraction_result.artifact)
        self._validate_mapping("legacy-item-extraction-result", raw_result)
        raw_acceptance = self._load_member_json(acceptance_artifact)
        self._validate_mapping("legacy-item-extraction-acceptance", raw_acceptance)
        try:
            result = LegacyItemExtractionResult.model_validate(raw_result)
            persisted_acceptance = LegacyItemExtractionAcceptance.model_validate(raw_acceptance)
        except PydanticValidationError as exc:
            raise LegacyAssessmentRegistryError(
                "LEGACY_ASSESSMENT_CONTRACT_INVALID", "acceptance evidence is invalid"
            ) from exc
        if persisted_acceptance != acceptance:
            self._fail("LEGACY_ASSESSMENT_POINTER_MISMATCH", "acceptance Artifact content differs")
        if (
            result.extraction_result_id != acceptance.extraction_result.extraction_result_id
            or result.result_sha256 != acceptance.extraction_result.result_sha256
        ):
            self._fail(
                "LEGACY_ASSESSMENT_POINTER_MISMATCH", "result pointer differs from its document"
            )
        result_items = {(item.item_proposal_id, item.item_number) for item in result.items}
        decisions = {
            (decision.item_proposal_id, decision.item_number)
            for decision in acceptance.item_decisions
        }
        if result_items != decisions:
            self._fail(
                "LEGACY_ASSESSMENT_ACCEPTANCE_INCOMPLETE",
                "acceptance decisions must exactly cover extraction result items",
            )
        with transaction(self.sessions) as session:
            existing = session.get(LegacyItemExtractionAcceptanceRecord, acceptance.acceptance_id)
            if existing is not None:
                if (
                    existing.acceptance_sha256 != acceptance.acceptance_sha256
                    or existing.acceptance_artifact_revision_id
                    != acceptance_artifact.artifact_revision_id
                ):
                    self._fail(
                        "LEGACY_ASSESSMENT_IDEMPOTENCY_CONFLICT", "acceptance identity differs"
                    )
                return LegacyAssessmentRegistration(
                    logical_id=acceptance.acceptance_id,
                    revision_id=acceptance_artifact.artifact_revision_id,
                    created=False,
                )
            session.add(self._acceptance_record(acceptance, acceptance_artifact))
            session.flush()
            for decision in acceptance.item_decisions:
                session.add(
                    LegacyItemExtractionDecisionRecord(
                        acceptance_id=acceptance.acceptance_id,
                        item_proposal_id=decision.item_proposal_id,
                        item_number=decision.item_number,
                        decision=decision.decision,
                    )
                )
            session.flush()
            return LegacyAssessmentRegistration(
                logical_id=acceptance.acceptance_id,
                revision_id=acceptance_artifact.artifact_revision_id,
                created=True,
            )

    def register_coverage(
        self,
        coverage: LegacyItemCorpusCoverage,
        *,
        coverage_artifact: AssessmentArtifactMemberPointer,
    ) -> LegacyAssessmentRegistration:
        self._validate_contract("legacy-item-corpus-coverage", coverage)
        self._require_control_artifact_contract(
            coverage_artifact,
            schema_ref="eom://schemas/legacy-assessment/legacy-item-corpus-coverage/1.0",
        )
        raw = self._load_member_json(coverage_artifact)
        self._validate_mapping("legacy-item-corpus-coverage", raw)
        try:
            persisted = LegacyItemCorpusCoverage.model_validate(raw)
        except PydanticValidationError as exc:
            raise LegacyAssessmentRegistryError(
                "LEGACY_ASSESSMENT_CONTRACT_INVALID", "coverage evidence is invalid"
            ) from exc
        if persisted != coverage:
            self._fail("LEGACY_ASSESSMENT_POINTER_MISMATCH", "coverage Artifact content differs")
        with transaction(self.sessions) as session:
            existing = session.get(LegacyItemCorpusCoverageRecord, coverage.coverage_id)
            if existing is not None:
                if (
                    existing.coverage_sha256 != coverage.coverage_sha256
                    or existing.artifact_revision_id != coverage_artifact.artifact_revision_id
                ):
                    self._fail(
                        "LEGACY_ASSESSMENT_IDEMPOTENCY_CONFLICT", "coverage identity differs"
                    )
                return LegacyAssessmentRegistration(
                    logical_id=coverage.coverage_id,
                    revision_id=coverage_artifact.artifact_revision_id,
                    created=False,
                )
            for bundle in coverage.bundle_coverages:
                revision = self._require_bundle_pointer(session, bundle.bundle)
                if (
                    revision.inventory_id != coverage.inventory_id
                    or revision.inventory_sha256 != coverage.inventory_sha256
                ):
                    self._fail(
                        "LEGACY_ASSESSMENT_POINTER_MISMATCH",
                        "coverage bundles do not share the pinned inventory",
                    )
                for accepted in bundle.accepted_items:
                    decision = session.scalar(
                        select(LegacyItemExtractionDecisionRecord).where(
                            LegacyItemExtractionDecisionRecord.acceptance_id
                            == accepted.acceptance_id,
                            LegacyItemExtractionDecisionRecord.item_number == accepted.item_number,
                            LegacyItemExtractionDecisionRecord.decision.in_(
                                ("ACCEPT", "CORRECT_AND_ACCEPT")
                            ),
                        )
                    )
                    acceptance = session.get(
                        LegacyItemExtractionAcceptanceRecord, accepted.acceptance_id
                    )
                    if (
                        decision is None
                        or acceptance is None
                        or acceptance.acceptance_sha256 != accepted.acceptance_sha256
                    ):
                        self._fail(
                            "LEGACY_ASSESSMENT_POINTER_STALE",
                            "coverage accepted item does not resolve",
                        )
            session.add(self._coverage_record(coverage, coverage_artifact))
            session.flush()
            for bundle in coverage.bundle_coverages:
                session.add(
                    LegacyItemCorpusBundleCoverageRecord(
                        coverage_id=coverage.coverage_id,
                        assessment_source_bundle_id=bundle.bundle.assessment_source_bundle_id,
                        assessment_source_bundle_revision_id=(
                            bundle.bundle.assessment_source_bundle_revision_id
                        ),
                        bundle_manifest_sha256=bundle.bundle.bundle_manifest_sha256,
                        expected_item_count=len(bundle.expected_item_numbers),
                        accepted_item_count=len(bundle.accepted_items),
                        missing_item_count=len(bundle.missing_item_numbers),
                        conflict_item_count=len(bundle.conflict_item_numbers),
                    )
                )
            session.flush()
            return LegacyAssessmentRegistration(
                logical_id=coverage.coverage_id,
                revision_id=coverage_artifact.artifact_revision_id,
                created=True,
            )

    def _load_member_json(self, pointer: AssessmentArtifactMemberPointer) -> dict[str, Any]:
        try:
            raw = self.artifacts.read_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                media_type=pointer.media_type,
                schema_ref=pointer.schema_ref,
                max_bytes=MAX_ASSESSMENT_CONTROL_BYTES,
            )
            value = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=self._unique_json_object,
                parse_constant=self._reject_json_constant,
            )
        except (JsonSchemaValidationError, OSError, UnicodeError, ValueError) as exc:
            raise LegacyAssessmentRegistryError(
                "LEGACY_ASSESSMENT_ARTIFACT_INVALID", "JSON evidence cannot be loaded"
            ) from exc
        if not isinstance(value, dict):
            self._fail("LEGACY_ASSESSMENT_ARTIFACT_INVALID", "JSON evidence is not an object")
        return value

    def _verify_member(self, pointer: AssessmentArtifactMemberPointer, max_bytes: int) -> None:
        try:
            self.artifacts.verify_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                media_type=pointer.media_type,
                schema_ref=pointer.schema_ref,
                max_bytes=max_bytes,
            )
        except (OSError, ValueError) as exc:
            raise LegacyAssessmentRegistryError(
                "LEGACY_ASSESSMENT_ARTIFACT_INVALID", "artifact member pointer is invalid"
            ) from exc

    @staticmethod
    def _require_control_artifact_contract(
        pointer: AssessmentArtifactMemberPointer, *, schema_ref: str
    ) -> None:
        if pointer.schema_ref != schema_ref or pointer.media_type != "application/json":
            raise LegacyAssessmentRegistryError(
                "LEGACY_ASSESSMENT_ARTIFACT_INVALID", "control Artifact contract is invalid"
            )

    def _verify_rights(self, revision: AssessmentSourceBundleRevision) -> None:
        try:
            self.rights.verify(
                revision.rights_policy,
                intended_use="ASSESSMENT_CORPUS_ANALYSIS",
            )
        except LegacyAssessmentRegistryError:
            raise
        except Exception as exc:
            raise LegacyAssessmentRegistryError(
                "LEGACY_ASSESSMENT_RIGHTS_INVALID",
                "rights policy is unavailable or disallows corpus analysis",
            ) from exc

    @staticmethod
    def _validate_contract(
        name: str,
        value: AssessmentSourceBundleRevision
        | LegacyItemExtractionAcceptance
        | LegacyItemCorpusCoverage,
    ) -> None:
        LegacyAssessmentRegistry._validate_mapping(name, value.model_dump(mode="json"))

    @staticmethod
    def _validate_mapping(name: str, value: dict[str, Any]) -> None:
        try:
            validate_contract(name, value)
        except (JsonSchemaValidationError, ValueError) as exc:
            raise LegacyAssessmentRegistryError(
                "LEGACY_ASSESSMENT_CONTRACT_INVALID", "legacy assessment contract is invalid"
            ) from exc

    @staticmethod
    def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    @staticmethod
    def _reject_json_constant(_value: str) -> NoReturn:
        raise ValueError("non-finite JSON value")

    @staticmethod
    def _lock(session: Session, key: str) -> None:
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key}
        )

    @staticmethod
    def _fail(code: str, message: str) -> NoReturn:
        raise LegacyAssessmentRegistryError(code, message)

    def _require_occurrence(
        self, session: Session, revision: AssessmentSourceBundleRevision
    ) -> None:
        pointer = revision.occurrence
        logical = session.get(AssessmentOccurrenceRecord, pointer.assessment_occurrence_id)
        occurrence = session.get(
            AssessmentOccurrenceRevisionRecord, pointer.assessment_occurrence_revision_id
        )
        if (
            logical is None
            or occurrence is None
            or logical.lifecycle_state != "ACTIVE"
            or occurrence.assessment_occurrence_id != logical.assessment_occurrence_id
            or occurrence.revision_state not in {"REVIEWED", "SUPERSEDED"}
            or occurrence.revision_sha256 != pointer.occurrence_revision_sha256
        ):
            self._fail("LEGACY_ASSESSMENT_POINTER_STALE", "assessment occurrence pointer is stale")

    def _require_bundle_pointer(
        self, session: Session, pointer: AssessmentSourceBundlePointer
    ) -> AssessmentSourceBundleRevisionRecord:
        logical = session.get(AssessmentSourceBundleRecord, pointer.assessment_source_bundle_id)
        revision = session.get(
            AssessmentSourceBundleRevisionRecord,
            pointer.assessment_source_bundle_revision_id,
        )
        if (
            logical is None
            or revision is None
            or logical.lifecycle_state not in {"ACTIVE", "RETIRED"}
            or revision.assessment_source_bundle_id != logical.assessment_source_bundle_id
            or revision.state not in {"REVIEWED", "SUPERSEDED"}
            or revision.bundle_manifest_sha256 != pointer.bundle_manifest_sha256
        ):
            self._fail("LEGACY_ASSESSMENT_POINTER_STALE", "bundle pointer is stale")
        return revision

    def _require_next_bundle_revision(
        self,
        session: Session,
        logical: AssessmentSourceBundleRecord,
        revision: AssessmentSourceBundleRevision,
    ) -> None:
        prior_id = logical.current_revision_id
        if prior_id is None:
            if revision.revision_number != 1 or revision.previous_revision_id is not None:
                self._fail("LEGACY_ASSESSMENT_REVISION_CONFLICT", "bundle revision is not first")
            return
        prior = session.get(AssessmentSourceBundleRevisionRecord, prior_id)
        if (
            prior is None
            or revision.previous_revision_id != prior_id
            or revision.revision_number != prior.revision_number + 1
        ):
            self._fail("LEGACY_ASSESSMENT_REVISION_CONFLICT", "bundle revision is stale")

    @staticmethod
    def _bundle_revision_record(
        value: AssessmentSourceBundleRevision,
    ) -> AssessmentSourceBundleRevisionRecord:
        return AssessmentSourceBundleRevisionRecord(
            assessment_source_bundle_revision_id=value.assessment_source_bundle_revision_id,
            assessment_source_bundle_id=value.assessment_source_bundle_id,
            revision_number=value.revision_number,
            previous_revision_id=value.previous_revision_id,
            state=value.state,
            inventory_id=value.inventory_id,
            inventory_sha256=value.inventory_sha256,
            inventory_artifact_id=value.inventory_artifact.artifact_id,
            inventory_artifact_revision_id=value.inventory_artifact.artifact_revision_id,
            inventory_artifact_member_path=value.inventory_artifact.member_path,
            inventory_artifact_schema_ref=value.inventory_artifact.schema_ref,
            inventory_artifact_media_type=value.inventory_artifact.media_type,
            inventory_artifact_sha256=value.inventory_artifact.sha256,
            assessment_occurrence_id=value.occurrence.assessment_occurrence_id,
            assessment_occurrence_revision_id=(value.occurrence.assessment_occurrence_revision_id),
            occurrence_revision_sha256=value.occurrence.occurrence_revision_sha256,
            rights_policy_id=value.rights_policy.rights_policy_id,
            rights_policy_revision_id=value.rights_policy.rights_policy_revision_id,
            rights_policy_sha256=value.rights_policy.rights_policy_sha256,
            bundle_manifest_sha256=value.bundle_manifest_sha256,
            reviewed_at=value.reviewed_at,
            reviewed_by=value.reviewed_by,
        )

    @staticmethod
    def _acceptance_record(
        value: LegacyItemExtractionAcceptance,
        artifact: AssessmentArtifactMemberPointer,
    ) -> LegacyItemExtractionAcceptanceRecord:
        result = value.extraction_result
        return LegacyItemExtractionAcceptanceRecord(
            acceptance_id=value.acceptance_id,
            extraction_result_id=result.extraction_result_id,
            result_artifact_id=result.artifact.artifact_id,
            result_artifact_revision_id=result.artifact.artifact_revision_id,
            result_artifact_member_path=result.artifact.member_path,
            result_artifact_schema_ref=result.artifact.schema_ref,
            result_artifact_media_type=result.artifact.media_type,
            result_artifact_sha256=result.artifact.sha256,
            result_sha256=result.result_sha256,
            acceptance_artifact_id=artifact.artifact_id,
            acceptance_artifact_revision_id=artifact.artifact_revision_id,
            acceptance_artifact_member_path=artifact.member_path,
            acceptance_artifact_schema_ref=artifact.schema_ref,
            acceptance_artifact_media_type=artifact.media_type,
            acceptance_artifact_sha256=artifact.sha256,
            state=value.state,
            coverage_state=value.coverage_state,
            reviewed_at=value.reviewed_at,
            reviewed_by=value.reviewed_by,
            acceptance_sha256=value.acceptance_sha256,
        )

    @staticmethod
    def _coverage_record(
        value: LegacyItemCorpusCoverage,
        artifact: AssessmentArtifactMemberPointer,
    ) -> LegacyItemCorpusCoverageRecord:
        return LegacyItemCorpusCoverageRecord(
            coverage_id=value.coverage_id,
            inventory_id=value.inventory_id,
            inventory_sha256=value.inventory_sha256,
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.artifact_revision_id,
            artifact_member_path=artifact.member_path,
            artifact_schema_ref=artifact.schema_ref,
            artifact_media_type=artifact.media_type,
            artifact_sha256=artifact.sha256,
            expected_item_count=value.expected_item_count,
            accepted_item_count=value.accepted_item_count,
            missing_item_count=value.missing_item_count,
            conflict_item_count=value.conflict_item_count,
            state=value.state,
            created_at=value.created_at,
            coverage_sha256=value.coverage_sha256,
        )
