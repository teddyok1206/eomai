"""Promote one reviewed legacy extraction proposal into the canonical Item registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, NoReturn

from eom_catalog_contracts import (
    ASSESSMENT_ITEM_CONTENT_FILE_NAME,
    ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
    AssessmentOccurrencePointer,
    ItemOriginDerivation,
    ItemOriginProfile,
    ItemOriginProvenance,
    LegacyItemExtractionAcceptance,
    LegacyItemExtractionRequest,
    LegacyItemExtractionResult,
    LegacyItemPromotionRequest,
    LegacyLearnedItemPointer,
    OrganizationRevisionPointer,
    OriginArtifactMemberPointer,
    OriginItemRevisionPointer,
    RightsPolicyPointer,
    validate_contract,
)
from eom_identifiers import content_sha256, item_origin_profile_id_for_revision
from eom_item_registry import ComponentPointer, RegistrationRequest, RegistryError
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import ArtifactRevisionRecord
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.item_origin_models import (
    AssessmentOccurrenceRevisionRecord,
    OrganizationRevisionRecord,
)
from eom_catalog_service.item_origin_service import ItemOriginService, RightsPolicyResolver
from eom_catalog_service.legacy_assessment_models import (
    AssessmentSourceBundleRevisionRecord,
    LegacyItemExtractionAcceptanceRecord,
)
from eom_catalog_service.models import (
    ContentPackRecord,
    ContentPackReleaseRecord,
    ItemComponentRecord,
    ItemRevisionRecord,
)
from eom_catalog_service.registry_service import RegistryService
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.staging import stage_registry_item_content

MAX_LEGACY_PROMOTION_DOCUMENT_BYTES = 16 * 1024 * 1024
LEGACY_PROMOTION_PACK_KEY = "legacy-approved-item"
LEGACY_PROMOTION_ITEM_TYPE = "legacy-approved-multiple-choice"
LEGACY_PROMOTION_METADATA_SCHEMA = "eom://metadata/legacy-approved-item@1.0"
LEGACY_PROMOTION_ITEM_SCHEMA_REF = "eom://schemas/item-registry/assessment-item-content-v1"


class LegacyItemPromotionError(RuntimeError):
    """Stable, content-free failure at the reviewed promotion boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LegacyItemPromotion:
    source: LegacyLearnedItemPointer
    item_created: bool
    origin_created: bool


@dataclass(frozen=True)
class _PromotionSource:
    acceptance: LegacyItemExtractionAcceptance
    result: LegacyItemExtractionResult
    proposal_index: int
    workflow_id: str
    workflow_definition_key: str
    workflow_definition_version: str
    source_step_run_id: str
    plan_id: str
    plan_sha256: str
    acceptance_artifact_revision_id: str
    bundle_revision: AssessmentSourceBundleRevisionRecord
    occurrence_revision: AssessmentOccurrenceRevisionRecord
    organization_revision: OrganizationRevisionRecord


class LegacyItemPromotionService:
    """Preserve reviewed provenance while bridging accepted items into Graph-eligible Items."""

    def __init__(
        self,
        engine: Engine,
        *,
        rights: RightsPolicyResolver,
        settings: CatalogSettings | None = None,
        artifacts: CatalogArtifactService | None = None,
        registry: RegistryService | None = None,
        origins: ItemOriginService | None = None,
    ) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.artifacts = artifacts or CatalogArtifactService(engine, self.settings)
        self.registry = registry or RegistryService(engine, self.settings)
        self.origins = origins or ItemOriginService(
            engine,
            rights=rights,
            settings=self.settings,
            artifacts=self.artifacts,
        )

    def promote(self, command: LegacyItemPromotionRequest) -> LegacyItemPromotion:
        self._validate_promotion_request(command)
        with self.sessions() as session:
            source = self._resolve_source(session, command)
            proposal = source.result.items[source.proposal_index]
            self._require_pack(session, command.content_pack_release_id)
            registration_key = self._registration_key(source.acceptance, proposal.item_proposal_id)
            existing = session.scalar(
                select(ItemRevisionRecord).where(
                    ItemRevisionRecord.registration_key == registration_key
                )
            )
            item_created = existing is None

        content_data = proposal.item_content.model_dump(mode="json")
        validate_contract("assessment-item-content", content_data)
        content_hash = content_sha256(content_data)
        staged, staged_sha256 = stage_registry_item_content(self.settings, content_data)
        if staged_sha256 != content_hash:
            self._fail(
                "LEGACY_ITEM_PROMOTION_CONTENT_MISMATCH",
                "accepted item content changed during canonical staging",
            )
        content_artifact = self.artifacts.commit_file_set(
            files={ASSESSMENT_ITEM_CONTENT_FILE_NAME: staged},
            primary_file=ASSESSMENT_ITEM_CONTENT_FILE_NAME,
            artifact_type="assessment-item-content",
            idempotency_key=(
                f"legacy-item-content:{source.acceptance.acceptance_id}:{proposal.item_proposal_id}"
            ),
            request={
                "acceptance_id": source.acceptance.acceptance_id,
                "acceptance_sha256": source.acceptance.acceptance_sha256,
                "item_proposal_id": proposal.item_proposal_id,
                "content_sha256": content_hash,
            },
            result={
                "schema_ref": LEGACY_PROMOTION_ITEM_SCHEMA_REF,
                "content_sha256": content_hash,
            },
            file_metadata={
                ASSESSMENT_ITEM_CONTENT_FILE_NAME: {
                    "schema_ref": LEGACY_PROMOTION_ITEM_SCHEMA_REF,
                    "media_type": ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
                }
            },
            expected_file_sha256={ASSESSMENT_ITEM_CONTENT_FILE_NAME: content_hash},
        )
        component = ComponentPointer(
            component_type="ITEM_CONTENT",
            ordinal=0,
            schema_ref=LEGACY_PROMOTION_ITEM_SCHEMA_REF,
            media_type=ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
            artifact_id=content_artifact.artifact_id,
            artifact_revision_id=content_artifact.revision_id,
            sha256=content_artifact.content_hash,
            logical_name=ASSESSMENT_ITEM_CONTENT_FILE_NAME,
            metadata={
                "promotion_protocol": "legacy-item-promotion/1.0",
                "acceptance_id": source.acceptance.acceptance_id,
                "item_proposal_id": proposal.item_proposal_id,
            },
        )
        metadata = {
            "item_type_key": LEGACY_PROMOTION_ITEM_TYPE,
            "source_kind": "PAST_EXAM",
            "extraction_acceptance_id": source.acceptance.acceptance_id,
            "extraction_result_id": source.result.extraction_result_id,
            "item_proposal_id": proposal.item_proposal_id,
            "item_number": proposal.item_number,
        }
        registration = RegistrationRequest(
            mode="CREATE_ITEM",
            registration_key=registration_key,
            content_pack_release_id=command.content_pack_release_id,
            workflow_id=source.workflow_id,
            workflow_definition_key=source.workflow_definition_key,
            workflow_definition_version=source.workflow_definition_version,
            source_workflow_step_run_id=source.source_step_run_id,
            source_intake_batch_ids=(),
            item_type_key=LEGACY_PROMOTION_ITEM_TYPE,
            primary_taxonomy_ref=command.primary_taxonomy_ref,
            difficulty_band=command.difficulty_band,
            metadata_schema_ref=LEGACY_PROMOTION_METADATA_SCHEMA,
            metadata=metadata,
            components=(component,),
            created_by=command.requested_by,
        )
        try:
            revision = self.registry.register(registration)
        except RegistryError as exc:
            raise LegacyItemPromotionError(
                "LEGACY_ITEM_PROMOTION_REGISTRATION_FAILED",
                "accepted legacy item registration failed",
            ) from exc
        self._verify_registered_revision(revision, registration, component)

        profile = self._origin_profile(
            command=command,
            source=source,
            revision=revision,
        )
        origin = self.origins.register_item_origin(profile)
        learned = LegacyLearnedItemPointer(
            item_id=revision.item_id,
            item_revision_id=revision.item_revision_id,
            item_manifest_sha256=revision.manifest_sha256,
            item_content=OriginArtifactMemberPointer(
                artifact_id=component.artifact_id,
                artifact_revision_id=component.artifact_revision_id,
                member_path=ASSESSMENT_ITEM_CONTENT_FILE_NAME,
                schema_ref=LEGACY_PROMOTION_ITEM_SCHEMA_REF,
                media_type=ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
                sha256=component.sha256,
            ),
            extraction_acceptance_id=source.acceptance.acceptance_id,
            extraction_acceptance_sha256=source.acceptance.acceptance_sha256,
            item_origin_profile_id=origin.item_origin_profile_id,
            item_origin_profile_sha256=profile.profile_sha256,
        )
        return LegacyItemPromotion(
            source=learned,
            item_created=item_created,
            origin_created=origin.created,
        )

    def _resolve_source(
        self,
        session: Session,
        command: LegacyItemPromotionRequest,
    ) -> _PromotionSource:
        row = session.get(LegacyItemExtractionAcceptanceRecord, command.acceptance_id)
        if row is None or row.acceptance_sha256 != command.acceptance_sha256:
            self._fail(
                "LEGACY_ITEM_PROMOTION_ACCEPTANCE_STALE",
                "reviewed extraction acceptance does not resolve",
            )
        acceptance_raw = self._read_json(
            artifact_id=row.acceptance_artifact_id,
            revision_id=row.acceptance_artifact_revision_id,
            member_path=row.acceptance_artifact_member_path,
            sha256=row.acceptance_artifact_sha256,
            media_type=row.acceptance_artifact_media_type,
            schema_ref=row.acceptance_artifact_schema_ref,
        )
        result_raw = self._read_json(
            artifact_id=row.result_artifact_id,
            revision_id=row.result_artifact_revision_id,
            member_path=row.result_artifact_member_path,
            sha256=row.result_artifact_sha256,
            media_type=row.result_artifact_media_type,
            schema_ref=row.result_artifact_schema_ref,
        )
        try:
            validate_contract("legacy-item-extraction-acceptance", acceptance_raw)
            validate_contract("legacy-item-extraction-result", result_raw)
            acceptance = LegacyItemExtractionAcceptance.model_validate(acceptance_raw)
            result = LegacyItemExtractionResult.model_validate(result_raw)
        except (JsonSchemaValidationError, PydanticValidationError, ValueError) as exc:
            raise LegacyItemPromotionError(
                "LEGACY_ITEM_PROMOTION_EVIDENCE_INVALID",
                "reviewed extraction evidence is invalid",
            ) from exc
        if (
            acceptance.acceptance_id != row.acceptance_id
            or acceptance.acceptance_sha256 != row.acceptance_sha256
            or acceptance.extraction_result.extraction_result_id != row.extraction_result_id
            or acceptance.extraction_result.result_sha256 != row.result_sha256
            or result.extraction_result_id != row.extraction_result_id
            or result.result_sha256 != row.result_sha256
        ):
            self._fail(
                "LEGACY_ITEM_PROMOTION_EVIDENCE_MISMATCH",
                "acceptance and extraction result identities differ",
            )
        proposal_index = self._accepted_proposal_index(acceptance, result, command)
        result_revision = session.get(ArtifactRevisionRecord, row.result_artifact_revision_id)
        step = (
            session.scalar(
                select(WorkflowStepRunRecord).where(
                    WorkflowStepRunRecord.platform_job_id == result_revision.job_id
                )
            )
            if result_revision is not None
            else None
        )
        workflow = (
            session.get(WorkflowInstanceRecord, step.workflow_id) if step is not None else None
        )
        plan = (
            session.scalar(
                select(ResolvedExecutionPlanRecord).where(
                    ResolvedExecutionPlanRecord.workflow_id == workflow.workflow_id
                )
            )
            if workflow is not None
            else None
        )
        if (
            result_revision is None
            or step is None
            or workflow is None
            or plan is None
            or not result_revision.approved
            or step.state != "SUCCEEDED"
            or step.step_key != "extract"
            or workflow.state != "COMPLETED"
            or workflow.stage != "COMPLETED"
            or workflow.definition_key != "legacy-item-extraction"
            or step.output_pointer_manifest is None
            or step.output_pointer_manifest.get("revision_id") != result_revision.revision_id
            or step.output_pointer_manifest.get("content_hash") != result_revision.content_hash
        ):
            self._fail(
                "LEGACY_ITEM_PROMOTION_WORKFLOW_INVALID",
                "extraction workflow provenance is incomplete",
            )
        try:
            extraction = LegacyItemExtractionRequest.model_validate(
                workflow.initial_request["legacy_extraction_request"]
            )
        except (KeyError, PydanticValidationError, TypeError) as exc:
            raise LegacyItemPromotionError(
                "LEGACY_ITEM_PROMOTION_WORKFLOW_INVALID",
                "extraction request provenance is invalid",
            ) from exc
        if (
            extraction.extraction_request_id != result.extraction_request_id
            or extraction.request_sha256 != result.request_sha256
        ):
            self._fail(
                "LEGACY_ITEM_PROMOTION_WORKFLOW_INVALID",
                "extraction result does not bind its workflow request",
            )
        bundle = session.get(
            AssessmentSourceBundleRevisionRecord,
            extraction.bundle.assessment_source_bundle_revision_id,
        )
        occurrence = session.get(
            AssessmentOccurrenceRevisionRecord,
            extraction.occurrence.assessment_occurrence_revision_id,
        )
        organization = (
            session.get(OrganizationRevisionRecord, occurrence.issuing_organization_revision_id)
            if occurrence is not None
            else None
        )
        if (
            bundle is None
            or occurrence is None
            or organization is None
            or bundle.assessment_source_bundle_id != extraction.bundle.assessment_source_bundle_id
            or bundle.bundle_manifest_sha256 != extraction.bundle.bundle_manifest_sha256
            or bundle.assessment_occurrence_revision_id
            != extraction.occurrence.assessment_occurrence_revision_id
            or occurrence.assessment_occurrence_id != extraction.occurrence.assessment_occurrence_id
            or occurrence.revision_sha256 != extraction.occurrence.occurrence_revision_sha256
            or bundle.rights_policy_id != occurrence.rights_policy_id
            or bundle.rights_policy_revision_id != occurrence.rights_policy_revision_id
            or bundle.rights_policy_sha256 != occurrence.rights_policy_sha256
        ):
            self._fail(
                "LEGACY_ITEM_PROMOTION_SOURCE_STALE",
                "pinned bundle or occurrence provenance does not resolve",
            )
        return _PromotionSource(
            acceptance=acceptance,
            result=result,
            proposal_index=proposal_index,
            workflow_id=workflow.workflow_id,
            workflow_definition_key=workflow.definition_key,
            workflow_definition_version=workflow.definition_version,
            source_step_run_id=step.step_run_id,
            plan_id=plan.plan_id,
            plan_sha256=plan.plan_sha256,
            acceptance_artifact_revision_id=row.acceptance_artifact_revision_id,
            bundle_revision=bundle,
            occurrence_revision=occurrence,
            organization_revision=organization,
        )

    @staticmethod
    def _accepted_proposal_index(
        acceptance: LegacyItemExtractionAcceptance,
        result: LegacyItemExtractionResult,
        command: LegacyItemPromotionRequest,
    ) -> int:
        decisions = [
            value
            for value in acceptance.item_decisions
            if value.item_proposal_id == command.item_proposal_id
            and value.item_number == command.item_number
        ]
        proposals = [
            (index, value)
            for index, value in enumerate(result.items)
            if value.item_proposal_id == command.item_proposal_id
            and value.item_number == command.item_number
        ]
        if len(decisions) != 1 or len(proposals) != 1:
            raise LegacyItemPromotionError(
                "LEGACY_ITEM_PROMOTION_ITEM_MISSING",
                "accepted item proposal does not resolve uniquely",
            )
        decision = decisions[0]
        _, proposal = proposals[0]
        accepted_paths = {value.content_path for value in proposal.content_anchor_map}
        if (
            acceptance.state != "ACCEPTED"
            or decision.decision != "ACCEPT"
            or decision.rejected_content_paths
            or decision.required_corrections
            or set(decision.accepted_content_paths) != accepted_paths
        ):
            raise LegacyItemPromotionError(
                "LEGACY_ITEM_PROMOTION_REVIEW_INCOMPLETE",
                "only a fully reviewed, uncorrected accepted proposal may be promoted",
            )
        return proposals[0][0]

    def _read_json(self, **pointer: str) -> dict[str, Any]:
        try:
            raw = self.artifacts.read_member(
                **pointer,
                max_bytes=MAX_LEGACY_PROMOTION_DOCUMENT_BYTES,
            )
            value = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=self._unique_json_object,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("non-finite JSON")),
            )
            if not isinstance(value, dict):
                raise ValueError("promotion evidence must be an object")
            return value
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise LegacyItemPromotionError(
                "LEGACY_ITEM_PROMOTION_EVIDENCE_INVALID",
                "promotion evidence cannot be resolved",
            ) from exc

    @staticmethod
    def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON object key")
            value[key] = item
        return value

    @staticmethod
    def _registration_key(
        acceptance: LegacyItemExtractionAcceptance,
        item_proposal_id: str,
    ) -> str:
        return f"legacy-item-promotion:{acceptance.acceptance_id}:{item_proposal_id}"

    @staticmethod
    def _require_pack(session: Session, release_id: str) -> None:
        release = session.get(ContentPackReleaseRecord, release_id)
        pack = (
            session.get(ContentPackRecord, release.content_pack_id) if release is not None else None
        )
        if (
            release is None
            or pack is None
            or release.state not in {"RELEASED", "DEPRECATED"}
            or pack.pack_key != LEGACY_PROMOTION_PACK_KEY
        ):
            raise LegacyItemPromotionError(
                "LEGACY_ITEM_PROMOTION_PACK_INVALID",
                "legacy promotion content pack is not released",
            )

    def _verify_registered_revision(
        self,
        revision: ItemRevisionRecord,
        request: RegistrationRequest,
        component: ComponentPointer,
    ) -> None:
        with self.sessions() as session:
            persisted = session.get(ItemRevisionRecord, revision.item_revision_id)
            content = session.scalar(
                select(ItemComponentRecord).where(
                    ItemComponentRecord.item_revision_id == revision.item_revision_id,
                    ItemComponentRecord.component_type == "ITEM_CONTENT",
                    ItemComponentRecord.ordinal == 0,
                )
            )
            if (
                persisted is None
                or content is None
                or persisted.revision_state != "APPROVED"
                or persisted.registration_key != request.registration_key
                or persisted.content_pack_release_id != request.content_pack_release_id
                or persisted.workflow_id != request.workflow_id
                or persisted.source_workflow_step_run_id != request.source_workflow_step_run_id
                or persisted.item_type_key != request.item_type_key
                or persisted.primary_taxonomy_ref != request.primary_taxonomy_ref
                or persisted.difficulty_band != request.difficulty_band
                or persisted.metadata_json != request.metadata
                or content.artifact_id != component.artifact_id
                or content.artifact_revision_id != component.artifact_revision_id
                or content.sha256 != component.sha256
            ):
                self._fail(
                    "LEGACY_ITEM_PROMOTION_IDEMPOTENCY_CONFLICT",
                    "existing promoted Item differs from the reviewed request",
                )

    @staticmethod
    def _origin_profile(
        *,
        command: LegacyItemPromotionRequest,
        source: _PromotionSource,
        revision: ItemRevisionRecord,
    ) -> ItemOriginProfile:
        occurrence = source.occurrence_revision
        organization = source.organization_revision
        bundle = source.bundle_revision
        values: dict[str, Any] = {
            "schema_version": "item-origin-profile/1.0",
            "item_origin_profile_id": item_origin_profile_id_for_revision(
                revision.item_revision_id
            ),
            "item_revision": OriginItemRevisionPointer(
                item_id=revision.item_id,
                item_revision_id=revision.item_revision_id,
                item_manifest_sha256=revision.manifest_sha256,
            ),
            "source_domain": "EXTERNAL_INSTITUTION",
            "creation_method": "UNKNOWN",
            "source_organization": OrganizationRevisionPointer(
                organization_id=organization.organization_id,
                organization_revision_id=organization.organization_revision_id,
                revision_sha256=organization.revision_sha256,
            ),
            "assessment_occurrences": (
                AssessmentOccurrencePointer(
                    assessment_occurrence_id=occurrence.assessment_occurrence_id,
                    assessment_occurrence_revision_id=occurrence.assessment_occurrence_revision_id,
                    occurrence_revision_sha256=occurrence.revision_sha256,
                ),
            ),
            "derivations": (
                ItemOriginDerivation(
                    source_kind="ASSESSMENT_SOURCE_BUNDLE_REVISION",
                    logical_id=bundle.assessment_source_bundle_id,
                    revision_id=bundle.assessment_source_bundle_revision_id,
                    manifest_sha256=bundle.bundle_manifest_sha256,
                    relation="DIGITIZED_FROM",
                ),
            ),
            "rights_policy": RightsPolicyPointer(
                rights_policy_id=bundle.rights_policy_id,
                rights_policy_revision_id=bundle.rights_policy_revision_id,
                rights_policy_sha256=bundle.rights_policy_sha256,
            ),
            "provenance": (
                ItemOriginProvenance(
                    provenance_kind="WORKFLOW",
                    logical_id=source.workflow_id,
                    revision_id=source.plan_id,
                    evidence_sha256=source.plan_sha256,
                ),
                ItemOriginProvenance(
                    provenance_kind="EXTRACTION_ACCEPTANCE",
                    logical_id=source.acceptance.acceptance_id,
                    revision_id=source.acceptance_artifact_revision_id,
                    evidence_sha256=source.acceptance.acceptance_sha256,
                ),
            ),
            "created_at": source.acceptance.reviewed_at,
            "created_by": command.requested_by,
        }
        values["profile_sha256"] = content_sha256(values)
        return ItemOriginProfile.model_validate(values)

    @staticmethod
    def _validate_promotion_request(command: LegacyItemPromotionRequest) -> None:
        try:
            validate_contract("legacy-item-promotion-request", command.model_dump(mode="json"))
        except (JsonSchemaValidationError, ValueError) as exc:
            raise LegacyItemPromotionError(
                "LEGACY_ITEM_PROMOTION_REQUEST_INVALID",
                "legacy Item promotion request is invalid",
            ) from exc

    @staticmethod
    def _fail(code: str, message: str) -> NoReturn:
        raise LegacyItemPromotionError(code, message)
