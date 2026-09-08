"""Immutable publication of human-approved mock-exam Item ratings."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, NoReturn, Protocol, cast

from eom_catalog_contracts.assessment_assembly import (
    MockExamRatingPolicyV1,
    load_integrated_science_mock_exam_rating_policy,
)
from eom_catalog_contracts.assessment_item import (
    ASSESSMENT_ITEM_CONTENT_FILE_NAME,
    ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
    ASSESSMENT_ITEM_CONTENT_V2_SCHEMA_REF,
    AssessmentItemContentV2,
)
from eom_catalog_contracts.item_review import (
    MOCK_EXAM_ITEM_REVIEW_DECISION_FILE_NAME,
    MOCK_EXAM_ITEM_REVIEW_DECISION_SCHEMA,
    MOCK_EXAM_ITEM_REVIEW_DECISION_SCHEMA_REF,
    MOCK_EXAM_ITEM_REVIEW_PUBLICATION_COMMAND_SCHEMA,
    MOCK_EXAM_ITEM_REVIEW_PUBLICATION_RESULT_SCHEMA,
    MOCK_EXAM_REVIEW_ELIGIBILITY_QUERY_SCHEMA,
    MOCK_EXAM_REVIEW_ELIGIBILITY_RESULT_SCHEMA,
    InspectMockExamReviewEligibilityQuery,
    MockExamEligibilityFinding,
    MockExamEligibilityFindingCounts,
    MockExamHumanApprovalPointer,
    MockExamItemReviewDecisionV1,
    MockExamItemReviewPublicationResult,
    MockExamReviewEligibilityResult,
    MockExamReviewFindingCounts,
    MockExamSourceReviewPointer,
    PublishMockExamItemReviewCommand,
    mock_exam_item_review_decision_sha256,
)
from eom_catalog_contracts.mock_exam_production_plan import (
    validate_content_team_mock_exam_slot_output,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_protocol import ArtifactManifest
from eom_workflow import ArtifactPointer
from eom_workflow.models import (
    ContentTeamAuthoringRoleResultV7,
    ContentTeamAuthoringRoleResultV8,
    ContentTeamImageRoleResultV8,
    ContentTeamItemBrief,
    ContentTeamReviewRoleResultV7,
    ContentTeamReviewRoleResultV8,
    RoleResultBase,
    RoleWorkerInput,
    WorkflowRequest,
)
from eom_workflow.schemas import WorkflowSchemaError, validate_role_result
from eom_workflow_runner.models import (
    ApprovalRequestRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.models import (
    ItemComponentRecord,
    ItemRecord,
    ItemReviewRecord,
    ItemRevisionRecord,
)
from eom_catalog_service.settings import CatalogSettings

MAX_ITEM_CONTENT_BYTES = 4 * 1024 * 1024
MAX_REVIEW_RESULT_BYTES = 256 * 1024
MAX_ROLE_RESULT_BYTES = 4 * 1024 * 1024
IDEMPOTENCY_SCOPE = "mock-exam-item-review-publication/1.0"
ITEM_REVIEW_PROTOCOL_VERSION = "catalog/1.11"
ITEM_REVIEW_PROTOCOL_SCHEMA_HASH = content_sha256(
    {
        "protocol": ITEM_REVIEW_PROTOCOL_VERSION,
        "contracts": [
            "mock-exam-item-review-publication-command/1.0",
            "mock-exam-review-eligibility-query/1.0",
            "mock-exam-review-eligibility-result/1.0",
            "mock-exam-item-review-decision/1.0",
            "mock-exam-item-review-publication-result/1.0",
        ],
    }
)
WorkflowContracts = tuple[str, str | None, str, str, str]
SUPPORTED_WORKFLOWS: dict[str, WorkflowContracts] = {
    "1.7.0": (
        "authoring-result@7.0",
        None,
        "review-result@7.0",
        "registration-result@7.0",
        "workflow-role/1.15.0",
    ),
    "1.8.0": (
        "authoring-result@8.0",
        "image-result@8.0",
        "review-result@8.0",
        "registration-result@8.0",
        "workflow-role/1.17.0",
    ),
}


class _CommittedArtifact(Protocol):
    artifact_id: str
    revision_id: str
    content_hash: str


class ItemReviewArtifactStore(Protocol):
    """Small immutable-artifact surface required by this use case."""

    def read_member(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        member_path: str,
        sha256: str,
        media_type: str,
        schema_ref: str,
        max_bytes: int,
    ) -> bytes: ...

    def load_json_revision(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        content_hash: str,
        max_bytes: int = 1_048_576,
    ) -> dict[str, Any]: ...

    def commit_file_set(
        self,
        *,
        files: dict[str, Path],
        primary_file: str,
        artifact_type: str,
        idempotency_key: str,
        request: dict[str, Any],
        result: dict[str, Any],
        file_metadata: dict[str, dict[str, str]] | None = None,
        manifest_version: str = "catalog-file-set/1.0",
        protocol_version: str,
        protocol_schema_hash: str,
        expected_file_sha256: dict[str, str] | None = None,
    ) -> _CommittedArtifact: ...


class MockExamItemReviewPublicationError(RuntimeError):
    """Stable, content-free failure at the Item rating publication boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _PublicationEvidence:
    item_revision_id: str
    workflow_id: str
    review_step_run_id: str
    approval_request_id: str
    review_artifact_id: str
    review_artifact_revision_id: str
    review_sha256: str
    review_result_schema: Literal["review-result@7.0", "review-result@8.0"]
    finding_counts: MockExamReviewFindingCounts
    approval_resolved_at: datetime


@dataclass(frozen=True)
class _DecisionArtifactPointer:
    artifact_id: str
    revision_id: str
    content_hash: str


@dataclass(frozen=True)
class _ReviewChainEvidence:
    workflow: WorkflowInstanceRecord
    authoring_result: ContentTeamAuthoringRoleResultV7 | ContentTeamAuthoringRoleResultV8
    review_step: WorkflowStepRunRecord
    review_pointer: ArtifactPointer
    review_result: ContentTeamReviewRoleResultV7 | ContentTeamReviewRoleResultV8
    gate_upstream_pointers: tuple[ArtifactPointer, ...]


class MockExamItemReviewPublicationService:
    """Append one policy-pinned rating after resolving its complete immutable evidence chain.

    The dominant access pattern is exact primary-key/foreign-key lookup with one bounded scan of
    workflow step attempts. A deterministic primary key derived from the caller's idempotency key
    provides concurrent replay safety without changing the existing ItemReviewRecord table.
    """

    def __init__(
        self,
        engine: Engine,
        settings: CatalogSettings | None = None,
        *,
        artifacts: ItemReviewArtifactStore | None = None,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self.sessions = session_factory or build_session_factory(engine)
        # CatalogArtifactService intentionally owns the infrastructure boundary; this cast keeps
        # the application service coupled only to the narrow structural surface above.
        self.artifacts = artifacts or cast(
            ItemReviewArtifactStore,
            CatalogArtifactService(engine, settings),
        )

    def inspect_eligibility(
        self,
        query: InspectMockExamReviewEligibilityQuery,
    ) -> MockExamReviewEligibilityResult:
        """Return one exact, human-readable review snapshot before workflow approval."""

        try:
            validate_contract(
                MOCK_EXAM_REVIEW_ELIGIBILITY_QUERY_SCHEMA,
                query.model_dump(mode="json"),
            )
        except JsonSchemaValidationError as exc:
            raise MockExamItemReviewPublicationError(
                "ITEM_REVIEW_ELIGIBILITY_QUERY_INVALID",
                "Item review eligibility query is invalid",
            ) from exc
        with self.sessions() as session:
            return self._inspect_eligibility_in_session(
                session,
                session.get(WorkflowInstanceRecord, query.workflow_id),
            )

    def inspect_eligibility_batch(
        self,
        queries: tuple[InspectMockExamReviewEligibilityQuery, ...],
    ) -> tuple[MockExamReviewEligibilityResult, ...]:
        """Resolve an ordered, bounded eligibility set in one database session."""

        if not queries or len(queries) > 25 or len({row.workflow_id for row in queries}) != len(
            queries
        ):
            self._fail(
                "ITEM_REVIEW_ELIGIBILITY_BATCH_INVALID",
                "review eligibility batch must contain 1 to 25 unique Workflows",
            )
        try:
            for query in queries:
                validate_contract(
                    MOCK_EXAM_REVIEW_ELIGIBILITY_QUERY_SCHEMA,
                    query.model_dump(mode="json"),
                )
        except JsonSchemaValidationError as exc:
            raise MockExamItemReviewPublicationError(
                "ITEM_REVIEW_ELIGIBILITY_QUERY_INVALID",
                "Item review eligibility query is invalid",
            ) from exc
        workflow_ids = tuple(row.workflow_id for row in queries)
        with self.sessions() as session:
            workflows = tuple(
                session.scalars(
                    select(WorkflowInstanceRecord).where(
                        WorkflowInstanceRecord.workflow_id.in_(workflow_ids)
                    )
                )
            )
            workflow_by_id = {row.workflow_id: row for row in workflows}
            definition_ids = {row.definition_id for row in workflows}
            # Keep these rows strongly referenced so `_require_supported_workflow` resolves its
            # exact definition through the Session identity map instead of an N+1 query.
            definitions = tuple(
                session.scalars(
                    select(WorkflowDefinitionRecord).where(
                        WorkflowDefinitionRecord.definition_id.in_(definition_ids)
                    )
                )
            )
            if len(definitions) != len(definition_ids):
                self._fail(
                    "ITEM_REVIEW_WORKFLOW_INVALID",
                    "one or more Workflow definitions do not resolve",
                )
            return tuple(
                self._inspect_eligibility_in_session(
                    session,
                    workflow_by_id.get(query.workflow_id),
                )
                for query in queries
            )

    def _inspect_eligibility_in_session(
        self,
        session: Session,
        workflow: WorkflowInstanceRecord | None,
    ) -> MockExamReviewEligibilityResult:
        workflow, contracts = self._require_supported_workflow(
            session,
            workflow,
            expected_state="INSPECTABLE",
        )
        chain = self._resolve_review_chain(session, workflow, contracts=contracts)
        if workflow.state == "AWAITING_HUMAN_APPROVAL":
            approval = self._resolve_pending_approval(
                session,
                workflow=workflow,
                gate_upstream_pointers=chain.gate_upstream_pointers,
            )
            approval_state: Literal["PENDING", "APPROVED"] = "PENDING"
            reviewer_operator_id = None
            approved_at = None
        else:
            approval = self._resolve_human_approval(
                session,
                workflow_id=workflow.workflow_id,
                reviewer_operator_id=None,
                gate_upstream_pointers=chain.gate_upstream_pointers,
            )
            approval_state = "APPROVED"
            reviewer_operator_id = approval.resolved_actor_id
            approved_at = approval.resolved_at
        findings = tuple(
            MockExamEligibilityFinding.model_validate(row.model_dump(mode="json"))
            for row in chain.review_result.output.review.findings
        )
        finding_counts = MockExamEligibilityFindingCounts(
            info=sum(row.severity == "info" for row in findings),
            warning=sum(row.severity == "warning" for row in findings),
            blocking=sum(row.severity == "blocking" for row in findings),
        )
        eligible = finding_counts.blocking == 0
        result = MockExamReviewEligibilityResult(
            workflow_id=workflow.workflow_id,
            workflow_lock_version=workflow.lock_version,
            approval_state=approval_state,
            approval_request_id=approval.approval_request_id,
            approval_lock_version=approval.lock_version,
            reviewer_operator_id=reviewer_operator_id,
            approved_at=approved_at,
            review_step_run_id=chain.review_step.step_run_id,
            review_artifact_id=chain.review_pointer.logical_artifact_id,
            review_artifact_revision_id=chain.review_pointer.revision_id,
            review_sha256=chain.review_pointer.content_hash,
            review_result_schema=cast(
                Literal["review-result@7.0", "review-result@8.0"],
                chain.review_step.result_schema,
            ),
            decision="ready_for_human",
            review_summary=chain.review_result.output.review.summary,
            findings=findings,
            finding_counts=finding_counts,
            eligible=eligible,
            eligibility_reason=("ELIGIBLE" if eligible else "REVIEW_BLOCKING_FINDINGS"),
        )
        validate_contract(
            MOCK_EXAM_REVIEW_ELIGIBILITY_RESULT_SCHEMA,
            result.model_dump(mode="json"),
        )
        return result

    def publish(
        self, command: PublishMockExamItemReviewCommand
    ) -> MockExamItemReviewPublicationResult:
        """Validate all pinned evidence and append, or replay, exactly one review row."""

        try:
            validate_contract(
                MOCK_EXAM_ITEM_REVIEW_PUBLICATION_COMMAND_SCHEMA,
                command.model_dump(mode="json"),
            )
        except JsonSchemaValidationError as exc:
            raise MockExamItemReviewPublicationError(
                "ITEM_REVIEW_COMMAND_INVALID",
                "Item review publication command is invalid",
            ) from exc
        policy = self._resolve_rating_policy(command)
        item_review_record_id, idempotency_key_sha256 = self._idempotency_identity(command)

        # Resolve under the Item row lock first. An existing rating is either this exact replay or
        # a permanent competing decision; no artifact is created in either case.
        with transaction(self.sessions) as session:
            evidence = self._resolve_evidence(session, command)
            decision = self._decision(
                command,
                policy=policy,
                evidence=evidence,
                item_review_record_id=item_review_record_id,
                idempotency_key_sha256=idempotency_key_sha256,
            )
            existing = self._single_existing_review(session, command.item_revision_id)
            if existing is not None:
                self._require_existing_identity(existing, item_review_record_id)
                decision_artifact = self._resolve_decision_artifact(
                    session,
                    record=existing,
                    expected=decision,
                )
                severity_summary = self._severity_summary(
                    command,
                    evidence,
                    decision=decision,
                    idempotency_key_sha256=idempotency_key_sha256,
                )
                self._require_exact_replay(
                    existing,
                    command=command,
                    evidence=evidence,
                    decision_artifact=decision_artifact,
                    severity_summary=severity_summary,
                )
                return self._result(
                    existing,
                    evidence=evidence,
                    command=command,
                    decision=decision,
                    created=False,
                )

        # Artifact commit is its own idempotent saga boundary. If the Item changes before the
        # second locked transaction, the decision remains immutable but is never published.
        decision_artifact = self._commit_decision_artifact(decision)
        try:
            with transaction(self.sessions) as session:
                current_evidence = self._resolve_evidence(session, command)
                current_decision = self._decision(
                    command,
                    policy=policy,
                    evidence=current_evidence,
                    item_review_record_id=item_review_record_id,
                    idempotency_key_sha256=idempotency_key_sha256,
                )
                if current_decision != decision:
                    self._fail(
                        "ITEM_REVIEW_EVIDENCE_STALE",
                        "Item review evidence changed during publication",
                    )
                verified_artifact = self._resolve_committed_decision_artifact(
                    session,
                    pointer=decision_artifact,
                    expected=decision,
                )
                severity_summary = self._severity_summary(
                    command,
                    current_evidence,
                    decision=decision,
                    idempotency_key_sha256=idempotency_key_sha256,
                )
                existing = self._single_existing_review(session, command.item_revision_id)
                if existing is not None:
                    self._require_existing_identity(existing, item_review_record_id)
                    self._require_exact_replay(
                        existing,
                        command=command,
                        evidence=current_evidence,
                        decision_artifact=verified_artifact,
                        severity_summary=severity_summary,
                    )
                    return self._result(
                        existing,
                        evidence=current_evidence,
                        command=command,
                        decision=decision,
                        created=False,
                    )
                record = ItemReviewRecord(
                    item_review_record_id=item_review_record_id,
                    item_revision_id=command.item_revision_id,
                    workflow_id=current_evidence.workflow_id,
                    review_artifact_id=verified_artifact.artifact_id,
                    review_artifact_revision_id=verified_artifact.revision_id,
                    review_sha256=verified_artifact.content_hash,
                    decision=policy.review_decision,
                    severity_summary=severity_summary,
                    reviewer_actor_id=command.reviewer_operator_id,
                )
                session.add(record)
                session.flush()
                return self._result(
                    record,
                    evidence=current_evidence,
                    command=command,
                    decision=decision,
                    created=True,
                )
        except IntegrityError as exc:
            # The Item row lock serializes in-service writers; the deterministic primary key also
            # protects exact replay if a caller bypassed that serialization boundary.
            with transaction(self.sessions) as session:
                concurrent_evidence = self._resolve_evidence(session, command)
                concurrent_decision = self._decision(
                    command,
                    policy=policy,
                    evidence=concurrent_evidence,
                    item_review_record_id=item_review_record_id,
                    idempotency_key_sha256=idempotency_key_sha256,
                )
                if concurrent_decision != decision:
                    self._fail(
                        "ITEM_REVIEW_EVIDENCE_STALE",
                        "Item review evidence changed during concurrent publication",
                    )
                verified_artifact = self._resolve_committed_decision_artifact(
                    session,
                    pointer=decision_artifact,
                    expected=decision,
                )
                concurrent = self._single_existing_review(
                    session,
                    command.item_revision_id,
                )
                if concurrent is None:
                    raise MockExamItemReviewPublicationError(
                        "ITEM_REVIEW_PERSISTENCE_FAILED",
                        "Item review publication could not be persisted",
                    ) from exc
                self._require_existing_identity(concurrent, item_review_record_id)
                concurrent_summary = self._severity_summary(
                    command,
                    concurrent_evidence,
                    decision=decision,
                    idempotency_key_sha256=idempotency_key_sha256,
                )
                self._require_exact_replay(
                    concurrent,
                    command=command,
                    evidence=concurrent_evidence,
                    decision_artifact=verified_artifact,
                    severity_summary=concurrent_summary,
                )
                return self._result(
                    concurrent,
                    evidence=concurrent_evidence,
                    command=command,
                    decision=decision,
                    created=False,
                )

    def _require_supported_workflow(
        self,
        session: Session,
        workflow: WorkflowInstanceRecord | None,
        *,
        expected_state: Literal["AWAITING_HUMAN_APPROVAL", "INSPECTABLE", "COMPLETED"],
    ) -> tuple[WorkflowInstanceRecord, WorkflowContracts]:
        contracts = (
            SUPPORTED_WORKFLOWS.get(workflow.definition_version)
            if workflow is not None
            else None
        )
        definition = (
            session.get(WorkflowDefinitionRecord, workflow.definition_id)
            if workflow is not None
            else None
        )
        if (
            workflow is None
            or contracts is None
            or definition is None
            or workflow.definition_key != "generic-item-development"
            or definition.definition_key != workflow.definition_key
            or definition.definition_version != workflow.definition_version
            or definition.definition_hash != workflow.definition_hash
            or definition.definition_hash != content_sha256(definition.canonical_definition)
            or workflow.role_schema_version != contracts[4]
        ):
            self._fail(
                "ITEM_REVIEW_WORKFLOW_INVALID",
                "Workflow does not resolve to a supported immutable content-team definition",
            )
        assert workflow is not None
        pending = (
            workflow.state == "AWAITING_HUMAN_APPROVAL"
            and workflow.stage == "AWAITING_HUMAN_APPROVAL"
            and workflow.current_step_key == "human_approval"
            and workflow.completed_at is None
        )
        approved_active = (
            workflow.state in {"APPROVED", "REGISTERING"}
            and workflow.stage == "REGISTERING"
            and workflow.current_step_key == "registration"
            and workflow.completed_at is None
        )
        completed = (
            workflow.state == "COMPLETED"
            and workflow.stage == "COMPLETED"
            and workflow.current_step_key == "complete"
            and workflow.completed_at is not None
        )
        valid_state = (
            completed
            if expected_state == "COMPLETED"
            else pending
            if expected_state == "AWAITING_HUMAN_APPROVAL"
            else pending or approved_active or completed
        )
        if not valid_state:
            self._fail(
                "ITEM_REVIEW_WORKFLOW_STATE_INVALID",
                "Workflow is not at the required review lifecycle boundary",
            )
        try:
            source_request = WorkflowRequest.model_validate(workflow.initial_request)
        except PydanticValidationError as exc:
            raise MockExamItemReviewPublicationError(
                "ITEM_REVIEW_WORKFLOW_INVALID",
                "Item workflow source is invalid",
            ) from exc
        if (
            workflow.request_payload != workflow.initial_request
            or workflow.request_hash != content_sha256(workflow.initial_request)
            or source_request.request_name != "GENERATED_KNOWLEDGE_ITEM_REQUEST"
            or source_request.content_pack is None
            or source_request.content_pack.pack_key != "generated-knowledge-item"
            or source_request.registry_intent is None
            or source_request.registry_intent.mode != "CREATE_ITEM"
            or not isinstance(source_request.item_brief, ContentTeamItemBrief)
            or source_request.item_brief.mock_exam_slot is None
            or source_request.execution_preset_key != "knowledge-grounded-item"
        ):
            self._fail(
                "ITEM_REVIEW_WORKFLOW_INVALID",
                "Workflow is not one fresh production-plan mock-exam Item request",
            )
        return workflow, contracts

    def _resolve_review_chain(
        self,
        session: Session,
        workflow: WorkflowInstanceRecord,
        *,
        contracts: WorkflowContracts,
    ) -> _ReviewChainEvidence:
        authoring_step = self._single_active_step(
            session,
            workflow_id=workflow.workflow_id,
            step_key="authoring",
        )
        if (
            authoring_step.state != "SUCCEEDED"
            or authoring_step.step_type != "agent"
            or authoring_step.worker_role != "authoring"
            or authoring_step.result_schema != contracts[0]
        ):
            self._fail(
                "ITEM_REVIEW_AUTHORING_STEP_INVALID",
                "Authoring step is stale or does not satisfy its pinned contract",
            )
        authoring_pointer, authoring_result = self._resolve_role_result(
            session,
            workflow=workflow,
            step=authoring_step,
            role="authoring",
            expected_schema=contracts[0],
            expected_types=(
                ContentTeamAuthoringRoleResultV7
                if workflow.definition_version == "1.7.0"
                else ContentTeamAuthoringRoleResultV8,
            ),
            max_bytes=MAX_ROLE_RESULT_BYTES,
        )
        if not isinstance(
            authoring_result,
            ContentTeamAuthoringRoleResultV7 | ContentTeamAuthoringRoleResultV8,
        ):
            self._fail(
                "ITEM_REVIEW_AUTHORING_RESULT_INVALID",
                "Authoring result is not a supported content-team result",
            )
        request = WorkflowRequest.model_validate(workflow.initial_request)
        assert isinstance(request.item_brief, ContentTeamItemBrief)
        assert request.item_brief.mock_exam_slot is not None
        try:
            validate_content_team_mock_exam_slot_output(
                slot=request.item_brief.mock_exam_slot,
                content=authoring_result.output.draft,
                authoring_difficulty=authoring_result.output.metadata.difficulty,
            )
        except ValueError as exc:
            raise MockExamItemReviewPublicationError(
                "ITEM_REVIEW_AUTHORING_RESULT_INVALID",
                "Authoring result differs from its immutable mock-exam slot",
            ) from exc
        supporting_pointers: list[ArtifactPointer] = [authoring_pointer]
        image_schema = contracts[1]
        if image_schema is None:
            rogue_steps = tuple(
                session.scalars(
                    select(WorkflowStepRunRecord).where(
                        WorkflowStepRunRecord.workflow_id == workflow.workflow_id,
                        WorkflowStepRunRecord.step_key.in_(("image_decision", "image")),
                        WorkflowStepRunRecord.superseded_by_step_run_id.is_(None),
                    )
                )
            )
            if rogue_steps:
                self._fail(
                    "ITEM_REVIEW_IMAGE_STEP_INVALID",
                    "Non-image workflow contains an active image branch",
                )
        else:
            assert isinstance(authoring_result, ContentTeamAuthoringRoleResultV8)
            decision_step = self._single_active_step(
                session,
                workflow_id=workflow.workflow_id,
                step_key="image_decision",
            )
            image_step = self._single_active_step(
                session,
                workflow_id=workflow.workflow_id,
                step_key="image",
            )
            if (
                decision_step.state != "SUCCEEDED"
                or decision_step.step_type != "decision"
                or decision_step.worker_role is not None
                or decision_step.result_schema is not None
                or decision_step.platform_job_id is not None
                or decision_step.output_pointer_manifest is not None
                or decision_step.input_pointer_manifest
                != {"field": "/output/draft/visuals"}
                or image_step.step_type != "agent"
                or image_step.worker_role != "image"
                or image_step.result_schema != image_schema
            ):
                self._fail(
                    "ITEM_REVIEW_IMAGE_STEP_INVALID",
                    "Image decision branch does not satisfy its pinned workflow contract",
                )
            image_ordinals = tuple(
                index
                for index, visual in enumerate(authoring_result.output.draft.visuals)
                if visual.kind == "IMAGE"
            )
            if not image_ordinals:
                if (
                    image_step.state != "SKIPPED"
                    or image_step.input_pointer_manifest != {"decision": "skip"}
                    or image_step.platform_job_id is not None
                    or image_step.output_pointer_manifest is not None
                ):
                    self._fail(
                        "ITEM_REVIEW_IMAGE_STEP_INVALID",
                        "Image-free Item does not bind the deterministic skipped image step",
                    )
            else:
                if image_step.state != "SUCCEEDED":
                    self._fail(
                        "ITEM_REVIEW_IMAGE_STEP_INVALID",
                        "Image-bearing Item has no succeeded image step",
                    )
                image_pointer, image_result = self._resolve_role_result(
                    session,
                    workflow=workflow,
                    step=image_step,
                    role="image",
                    expected_schema=image_schema,
                    expected_types=(ContentTeamImageRoleResultV8,),
                    max_bytes=MAX_ROLE_RESULT_BYTES,
                )
                assert isinstance(image_result, ContentTeamImageRoleResultV8)
                actual_image_ordinals = tuple(
                    row.visual_ordinal for row in image_result.output.drawings
                )
                if actual_image_ordinals != image_ordinals:
                    self._fail(
                        "ITEM_REVIEW_IMAGE_RESULT_INVALID",
                        "Image result does not cover the authoring IMAGE slots exactly",
                    )
                supporting_pointers.append(image_pointer)

        review_step = self._resolve_review_step(
            session,
            workflow_id=workflow.workflow_id,
            expected_result_schema=contracts[2],
        )
        if self._input_pointers(review_step, code="ITEM_REVIEW_STEP_INVALID") != tuple(
            supporting_pointers
        ):
            self._fail(
                "ITEM_REVIEW_STEP_INVALID",
                "Review step does not bind the exact authoring/image evidence chain",
            )
        review_pointer, review_result = self._resolve_review_result(
            session,
            workflow=workflow,
            step=review_step,
        )
        return _ReviewChainEvidence(
            workflow=workflow,
            authoring_result=authoring_result,
            review_step=review_step,
            review_pointer=review_pointer,
            review_result=review_result,
            gate_upstream_pointers=(*supporting_pointers, review_pointer),
        )

    def _single_active_step(
        self,
        session: Session,
        *,
        workflow_id: str,
        step_key: str,
    ) -> WorkflowStepRunRecord:
        rows = tuple(
            session.scalars(
                select(WorkflowStepRunRecord).where(
                    WorkflowStepRunRecord.workflow_id == workflow_id,
                    WorkflowStepRunRecord.step_key == step_key,
                    WorkflowStepRunRecord.superseded_by_step_run_id.is_(None),
                )
            )
        )
        if len(rows) != 1:
            self._fail(
                "ITEM_REVIEW_STEP_INVALID",
                "Workflow does not have one active step for the required evidence chain",
            )
        return rows[0]

    def _input_pointers(
        self,
        step: WorkflowStepRunRecord,
        *,
        code: str,
    ) -> tuple[ArtifactPointer, ...]:
        values = step.input_pointer_manifest.get("upstream_artifacts")
        if not isinstance(values, list):
            self._fail(code, "Workflow step input pointer manifest is invalid")
        try:
            return tuple(ArtifactPointer.model_validate(value) for value in values)
        except PydanticValidationError as exc:
            raise MockExamItemReviewPublicationError(
                code,
                "Workflow step input pointer manifest is invalid",
            ) from exc

    def _resolve_evidence(
        self,
        session: Session,
        command: PublishMockExamItemReviewCommand,
    ) -> _PublicationEvidence:
        item_row = session.execute(
            select(ItemRecord, ItemRevisionRecord)
            .join(ItemRevisionRecord, ItemRevisionRecord.item_id == ItemRecord.item_id)
            .where(ItemRevisionRecord.item_revision_id == command.item_revision_id)
            .with_for_update()
        ).one_or_none()
        if item_row is None:
            self._fail("ITEM_REVIEW_ITEM_NOT_FOUND", "Item revision does not exist")
        item, revision = item_row
        if (
            item.lifecycle_state != "ACTIVE"
            or item.current_revision_id != revision.item_revision_id
            or revision.revision_state != "APPROVED"
            or revision.superseded_at is not None
            or revision.superseded_by_revision_id is not None
        ):
            self._fail(
                "ITEM_REVIEW_ITEM_STALE",
                "Item revision is not the current active approved revision",
            )

        if revision.workflow_id != command.expected_workflow_id:
            self._fail(
                "ITEM_REVIEW_WORKFLOW_MISMATCH",
                "Item revision belongs to a different generated workflow",
            )
        workflow = session.get(WorkflowInstanceRecord, command.expected_workflow_id)
        workflow, contracts = self._require_supported_workflow(
            session,
            workflow,
            expected_state="COMPLETED",
        )
        if revision.workflow_definition_version != workflow.definition_version:
            self._fail(
                "ITEM_REVIEW_WORKFLOW_INVALID",
                "Item revision workflow version differs from its immutable workflow",
            )

        self._require_registration_step(
            session,
            revision=revision,
            expected_result_schema=contracts[3],
        )
        registered_content = self._require_v2_item_content(
            session,
            revision.item_revision_id,
        )
        chain = self._resolve_review_chain(session, workflow, contracts=contracts)
        if registered_content != chain.authoring_result.output.draft:
            self._fail(
                "ITEM_REVIEW_ITEM_CONTENT_POINTER_INVALID",
                "Registered V2 content differs from the reviewed authoring result",
            )
        findings = chain.review_result.output.review.findings
        counts = MockExamReviewFindingCounts(
            info=sum(finding.severity == "info" for finding in findings),
            warning=sum(finding.severity == "warning" for finding in findings),
            blocking=0,
        )
        if any(finding.severity == "blocking" for finding in findings):
            self._fail(
                "ITEM_REVIEW_BLOCKING_FINDINGS",
                "Review result contains blocking findings",
            )
        approval = self._resolve_human_approval(
            session,
            workflow_id=workflow.workflow_id,
            reviewer_operator_id=command.reviewer_operator_id,
            gate_upstream_pointers=chain.gate_upstream_pointers,
        )
        return _PublicationEvidence(
            item_revision_id=revision.item_revision_id,
            workflow_id=workflow.workflow_id,
            review_step_run_id=chain.review_step.step_run_id,
            approval_request_id=approval.approval_request_id,
            review_artifact_id=chain.review_pointer.logical_artifact_id,
            review_artifact_revision_id=chain.review_pointer.revision_id,
            review_sha256=chain.review_pointer.content_hash,
            review_result_schema=cast(
                Literal["review-result@7.0", "review-result@8.0"],
                chain.review_step.result_schema,
            ),
            finding_counts=counts,
            approval_resolved_at=cast(datetime, approval.resolved_at),
        )

    def _require_v2_item_content(
        self,
        session: Session,
        item_revision_id: str,
    ) -> AssessmentItemContentV2:
        components = tuple(
            session.scalars(
                select(ItemComponentRecord).where(
                    ItemComponentRecord.item_revision_id == item_revision_id,
                    ItemComponentRecord.component_type == "ITEM_CONTENT",
                )
            )
        )
        if len(components) != 1:
            self._fail(
                "ITEM_REVIEW_ITEM_NOT_V2",
                "Item revision does not have one canonical V2 content component",
            )
        component = components[0]
        artifact = session.get(ArtifactRecord, component.artifact_id)
        artifact_revision = session.get(
            ArtifactRevisionRecord,
            component.artifact_revision_id,
        )
        job = (
            session.get(JobRecord, artifact_revision.job_id)
            if artifact_revision is not None
            else None
        )
        manifest = artifact_revision.manifest if artifact_revision is not None else {}
        if (
            component.ordinal != 0
            or not component.required
            or component.schema_ref != ASSESSMENT_ITEM_CONTENT_V2_SCHEMA_REF
            or component.media_type != ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE
            or component.logical_name != ASSESSMENT_ITEM_CONTENT_FILE_NAME
            or artifact is None
            or artifact_revision is None
            or job is None
            or not artifact.approved
            or not artifact_revision.approved
            or artifact.artifact_type != "assessment-item-content"
            or artifact.job_id != artifact_revision.job_id
            or artifact_revision.logical_artifact_id != artifact.logical_artifact_id
            or artifact_revision.content_hash != component.sha256
            or artifact_revision.manifest_hash != content_sha256(manifest)
            or manifest.get("logical_artifact_id") != component.artifact_id
            or manifest.get("revision_id") != component.artifact_revision_id
            or manifest.get("job_id") != job.job_id
            or manifest.get("artifact_type") != "assessment-item-content"
            or manifest.get("primary_file") != ASSESSMENT_ITEM_CONTENT_FILE_NAME
            or manifest.get("content_hash") != component.sha256
            or job.status != "SUCCEEDED"
            or job.task_type != "assessment-item-content"
            or job.logical_artifact_id != component.artifact_id
            or job.revision_id != component.artifact_revision_id
        ):
            self._fail(
                "ITEM_REVIEW_ITEM_CONTENT_POINTER_INVALID",
                "V2 Item content pointer does not resolve to approved immutable evidence",
            )
        try:
            raw = self.artifacts.read_member(
                artifact_id=component.artifact_id,
                revision_id=component.artifact_revision_id,
                member_path=ASSESSMENT_ITEM_CONTENT_FILE_NAME,
                sha256=component.sha256,
                media_type=ASSESSMENT_ITEM_CONTENT_MEDIA_TYPE,
                schema_ref=ASSESSMENT_ITEM_CONTENT_V2_SCHEMA_REF,
                max_bytes=MAX_ITEM_CONTENT_BYTES,
            )
            if sha256_bytes(raw) != component.sha256:
                raise ValueError("V2 content bytes differ from their pointer")
            value: object = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("V2 Item content is not an object")
            validate_contract("assessment-item-content-v2", value)
            content = AssessmentItemContentV2.model_validate(value)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            JsonSchemaValidationError,
            PydanticValidationError,
            ValueError,
        ) as exc:
            raise MockExamItemReviewPublicationError(
                "ITEM_REVIEW_ITEM_CONTENT_INVALID",
                "V2 Item content failed immutable contract validation",
            ) from exc
        return content

    def _require_registration_step(
        self,
        session: Session,
        *,
        revision: ItemRevisionRecord,
        expected_result_schema: str,
    ) -> None:
        step = session.get(WorkflowStepRunRecord, revision.source_workflow_step_run_id)
        job = (
            session.get(JobRecord, step.platform_job_id)
            if step is not None and step.platform_job_id is not None
            else None
        )
        if (
            step is None
            or job is None
            or step.workflow_id != revision.workflow_id
            or step.step_key != "registration"
            or step.step_type != "agent"
            or step.worker_role != "item_management"
            or step.result_schema != expected_result_schema
            or step.state != "SUCCEEDED"
            or step.superseded_by_step_run_id is not None
            or job.status != "SUCCEEDED"
            or job.job_id != step.platform_job_id
        ):
            self._fail(
                "ITEM_REVIEW_REGISTRATION_INVALID",
                "Item revision registration step is stale or incomplete",
            )

    def _resolve_review_step(
        self,
        session: Session,
        *,
        workflow_id: str,
        expected_result_schema: str,
    ) -> WorkflowStepRunRecord:
        active_succeeded = tuple(
            session.scalars(
                select(WorkflowStepRunRecord).where(
                    WorkflowStepRunRecord.workflow_id == workflow_id,
                    WorkflowStepRunRecord.step_key == "review",
                    WorkflowStepRunRecord.state == "SUCCEEDED",
                    WorkflowStepRunRecord.superseded_by_step_run_id.is_(None),
                )
            )
        )
        if len(active_succeeded) != 1:
            self._fail(
                "ITEM_REVIEW_STEP_INVALID",
                "Workflow does not have one unsuperseded succeeded review step",
            )
        step = active_succeeded[0]
        if (
            step.step_type != "agent"
            or step.worker_role != "review"
            or step.result_schema != expected_result_schema
            or step.platform_job_id is None
            or step.output_pointer_manifest is None
        ):
            self._fail(
                "ITEM_REVIEW_STEP_INVALID",
                "Workflow review step does not satisfy the supported contract",
            )
        return step

    def _resolve_review_result(
        self,
        session: Session,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
    ) -> tuple[ArtifactPointer, ContentTeamReviewRoleResultV7 | ContentTeamReviewRoleResultV8]:
        expected_type: type[RoleResultBase] = (
            ContentTeamReviewRoleResultV7
            if step.result_schema == "review-result@7.0"
            else ContentTeamReviewRoleResultV8
        )
        pointer, parsed = self._resolve_role_result(
            session,
            workflow=workflow,
            step=step,
            role="review",
            expected_schema=cast(str, step.result_schema),
            expected_types=(expected_type,),
            max_bytes=MAX_REVIEW_RESULT_BYTES,
        )
        if not isinstance(
            parsed,
            ContentTeamReviewRoleResultV7 | ContentTeamReviewRoleResultV8,
        ):
            self._fail(
                "ITEM_REVIEW_RESULT_INVALID",
                "Review result is not a supported content-team review",
            )
        if parsed.output.review.decision != "ready_for_human":
            self._fail(
                "ITEM_REVIEW_RESULT_INVALID",
                "Review result is not ready for human approval",
            )
        return pointer, parsed

    def _resolve_role_result(
        self,
        session: Session,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        role: Literal["authoring", "image", "review"],
        expected_schema: str,
        expected_types: tuple[type[RoleResultBase], ...],
        max_bytes: int,
    ) -> tuple[ArtifactPointer, RoleResultBase]:
        try:
            pointer = ArtifactPointer.model_validate(step.output_pointer_manifest)
        except PydanticValidationError as exc:
            raise MockExamItemReviewPublicationError(
                "ITEM_REVIEW_ARTIFACT_POINTER_INVALID",
                "Workflow role output pointer is invalid",
            ) from exc
        artifact = session.get(ArtifactRecord, pointer.logical_artifact_id)
        revision = session.get(ArtifactRevisionRecord, pointer.revision_id)
        job = session.get(JobRecord, pointer.job_id)
        try:
            artifact_manifest = (
                ArtifactManifest.model_validate(revision.manifest)
                if revision is not None
                else None
            )
            worker_input = RoleWorkerInput.model_validate(job.request) if job is not None else None
        except PydanticValidationError as exc:
            raise MockExamItemReviewPublicationError(
                "ITEM_REVIEW_ARTIFACT_POINTER_INVALID",
                "Workflow role artifact provenance is invalid",
            ) from exc
        if (
            artifact is None
            or revision is None
            or job is None
            or artifact_manifest is None
            or worker_input is None
        ):
            self._fail(
                "ITEM_REVIEW_ARTIFACT_POINTER_INVALID",
                "Workflow role artifact pointer does not resolve",
            )
        assert artifact is not None
        assert revision is not None
        assert job is not None
        assert artifact_manifest is not None
        assert worker_input is not None
        if (
            pointer.step_key != step.step_key
            or pointer.attempt != step.attempt
            or pointer.job_id != step.platform_job_id
            or pointer.result_schema != expected_schema
            or step.result_schema != expected_schema
            or artifact.logical_artifact_id != pointer.logical_artifact_id
            or artifact.job_id != pointer.job_id
            or artifact.artifact_type != f"workflow_{role}"
            or not artifact.approved
            or revision.revision_id != pointer.revision_id
            or revision.logical_artifact_id != pointer.logical_artifact_id
            or revision.job_id != pointer.job_id
            or revision.content_hash != pointer.content_hash
            or revision.manifest_hash != content_sha256(revision.manifest)
            or revision.content_bytes != artifact_manifest.content_bytes
            or not revision.approved
            or artifact_manifest.job_id != pointer.job_id
            or artifact_manifest.logical_artifact_id != pointer.logical_artifact_id
            or artifact_manifest.revision_id != pointer.revision_id
            or artifact_manifest.content_hash != pointer.content_hash
            or artifact_manifest.file_name != "result.json"
            or artifact_manifest.media_type != "application/json"
            or job.status != "SUCCEEDED"
            or job.task_type != f"workflow_{role}"
            or job.logical_artifact_id != pointer.logical_artifact_id
            or job.revision_id != pointer.revision_id
            or job.worker_slot_id is None
            or job.worker_slot_id != artifact_manifest.worker_slot
            or job.protocol_version != workflow.role_schema_version
            or worker_input.job_id != pointer.job_id
            or worker_input.workflow_id != workflow.workflow_id
            or worker_input.step_run_id != step.step_run_id
            or worker_input.attempt != step.attempt
            or worker_input.role != role
            or worker_input.protocol_version != job.protocol_version
            or worker_input.upstream_artifacts
            != self._input_pointers(step, code="ITEM_REVIEW_ARTIFACT_POINTER_INVALID")
            or worker_input.artifact.logical_artifact_id != pointer.logical_artifact_id
            or worker_input.artifact.revision_id != pointer.revision_id
        ):
            self._fail(
                "ITEM_REVIEW_ARTIFACT_POINTER_INVALID",
                "Workflow role artifact does not resolve to the exact succeeded step",
            )
        try:
            raw = self.artifacts.load_json_revision(
                artifact_id=pointer.logical_artifact_id,
                revision_id=pointer.revision_id,
                content_hash=pointer.content_hash,
                max_bytes=max_bytes,
            )
            if raw != revision.result or content_sha256(raw) != pointer.content_hash:
                raise ValueError("role result differs from its immutable database projection")
            parsed = validate_role_result(raw, role, expected_schema)
        except (
            OSError,
            WorkflowSchemaError,
            PydanticValidationError,
            ValueError,
        ) as exc:
            raise MockExamItemReviewPublicationError(
                "ITEM_REVIEW_RESULT_INVALID",
                "Workflow role result failed its exact contract",
            ) from exc
        if not isinstance(parsed, expected_types):
            self._fail(
                "ITEM_REVIEW_RESULT_INVALID",
                "Workflow role result type differs from its definition",
            )
        if (
            parsed.workflow_id != workflow.workflow_id
            or parsed.step_run_id != step.step_run_id
            or parsed.job_id != pointer.job_id
            or getattr(parsed, "role", None) != role
            or parsed.artifact.logical_artifact_id != pointer.logical_artifact_id
            or parsed.artifact.revision_id != pointer.revision_id
            or parsed.protocol_version != job.protocol_version
        ):
            self._fail(
                "ITEM_REVIEW_RESULT_INVALID",
                "Workflow role result identity does not match its evidence",
            )
        return pointer, cast(RoleResultBase, parsed)

    def _resolve_pending_approval(
        self,
        session: Session,
        *,
        workflow: WorkflowInstanceRecord,
        gate_upstream_pointers: tuple[ArtifactPointer, ...],
    ) -> ApprovalRequestRecord:
        approvals = tuple(
            session.scalars(
                select(ApprovalRequestRecord).where(
                    ApprovalRequestRecord.workflow_id == workflow.workflow_id,
                    ApprovalRequestRecord.status == "PENDING",
                )
            )
        )
        if len(approvals) != 1:
            self._fail(
                "ITEM_REVIEW_APPROVAL_INVALID",
                "Workflow does not have one active human approval request",
            )
        approval = approvals[0]
        gate = session.get(WorkflowStepRunRecord, approval.step_run_id)
        if (
            gate is None
            or gate.workflow_id != workflow.workflow_id
            or gate.step_key != "human_approval"
            or gate.step_type != "human_gate"
            or gate.state != "WAITING_FOR_HUMAN"
            or gate.superseded_by_step_run_id is not None
            or approval.decision is not None
            or approval.resolved_at is not None
            or approval.resolved_actor_type is not None
            or approval.resolved_actor_id is not None
            or "reviewer" not in approval.allowed_roles
            or self._input_pointers(gate, code="ITEM_REVIEW_APPROVAL_INVALID")
            != gate_upstream_pointers
        ):
            self._fail(
                "ITEM_REVIEW_APPROVAL_INVALID",
                "Pending human approval does not bind the exact review evidence chain",
            )
        return approval

    def _resolve_human_approval(
        self,
        session: Session,
        *,
        workflow_id: str,
        reviewer_operator_id: str | None,
        gate_upstream_pointers: tuple[ArtifactPointer, ...],
    ) -> ApprovalRequestRecord:
        approvals = tuple(
            session.scalars(
                select(ApprovalRequestRecord).where(
                    ApprovalRequestRecord.workflow_id == workflow_id,
                    ApprovalRequestRecord.status == "APPROVED",
                )
            )
        )
        resolved_reviewer = approvals[0].resolved_actor_id if len(approvals) == 1 else None
        operator = (
            session.get(OperatorRecord, resolved_reviewer)
            if isinstance(resolved_reviewer, str)
            else None
        )
        if len(approvals) != 1 or operator is None:
            self._fail(
                "ITEM_REVIEW_APPROVAL_INVALID",
                "Workflow human approval does not resolve",
            )
        approval = approvals[0]
        gate = session.get(WorkflowStepRunRecord, approval.step_run_id)
        if (
            approval.decision != "APPROVED"
            or approval.resolved_at is None
            or approval.resolved_actor_type != "human"
            or not isinstance(approval.resolved_actor_id, str)
            or (
                reviewer_operator_id is not None
                and approval.resolved_actor_id != reviewer_operator_id
            )
            or gate is None
            or gate.workflow_id != workflow_id
            or gate.step_key != "human_approval"
            or gate.step_type != "human_gate"
            or gate.state != "SUCCEEDED"
            or gate.superseded_by_step_run_id is not None
            or "reviewer" not in approval.allowed_roles
        ):
            self._fail(
                "ITEM_REVIEW_APPROVAL_INVALID",
                "Workflow human approval is stale or belongs to another reviewer",
            )
        if (
            self._input_pointers(gate, code="ITEM_REVIEW_APPROVAL_INVALID")
            != gate_upstream_pointers
        ):
            self._fail(
                "ITEM_REVIEW_APPROVAL_INVALID",
                "Human approval does not bind the exact review evidence chain",
            )
        return approval

    @staticmethod
    def _decision(
        command: PublishMockExamItemReviewCommand,
        *,
        policy: MockExamRatingPolicyV1,
        evidence: _PublicationEvidence,
        item_review_record_id: str,
        idempotency_key_sha256: str,
    ) -> MockExamItemReviewDecisionV1:
        human_approval = MockExamHumanApprovalPointer(
            approval_request_id=evidence.approval_request_id,
            reviewer_operator_id=command.reviewer_operator_id,
            approved_at=evidence.approval_resolved_at,
        ).model_dump(mode="json")
        unsigned: dict[str, Any] = {
            "schema_version": "mock-exam-item-review-decision/1.0",
            "item_review_record_id": item_review_record_id,
            "item_revision_id": evidence.item_revision_id,
            "workflow_id": evidence.workflow_id,
            "source_review": MockExamSourceReviewPointer(
                step_run_id=evidence.review_step_run_id,
                artifact_id=evidence.review_artifact_id,
                artifact_revision_id=evidence.review_artifact_revision_id,
                sha256=evidence.review_sha256,
                result_schema=evidence.review_result_schema,
                worker_decision="ready_for_human",
                finding_counts=evidence.finding_counts,
            ).model_dump(mode="json"),
            "human_approval": human_approval,
            "decision": policy.review_decision,
            "final_rating": command.final_rating,
            "rating_policy_key": policy.rating_policy_key,
            "rating_policy_revision_id": command.rating_policy_revision_id,
            "rating_policy_sha256": command.rating_policy_sha256,
            "idempotency_key_sha256": idempotency_key_sha256,
            # Hash the exact JSON representation that will be written to the artifact.
            "decided_at": human_approval["approved_at"],
        }
        decision = MockExamItemReviewDecisionV1.model_validate(
            {
                **unsigned,
                "decision_sha256": mock_exam_item_review_decision_sha256(unsigned),
            }
        )
        validate_contract(
            MOCK_EXAM_ITEM_REVIEW_DECISION_SCHEMA,
            decision.model_dump(mode="json"),
        )
        return decision

    def _commit_decision_artifact(
        self,
        decision: MockExamItemReviewDecisionV1,
    ) -> _DecisionArtifactPointer:
        payload = canonical_json_bytes(decision)
        expected_content_hash = sha256_bytes(payload)
        try:
            with tempfile.TemporaryDirectory(prefix="eom-item-review-decision-") as directory:
                path = Path(directory) / MOCK_EXAM_ITEM_REVIEW_DECISION_FILE_NAME
                path.write_bytes(payload)
                path.chmod(0o640)
                committed = self.artifacts.commit_file_set(
                    files={MOCK_EXAM_ITEM_REVIEW_DECISION_FILE_NAME: path},
                    primary_file=MOCK_EXAM_ITEM_REVIEW_DECISION_FILE_NAME,
                    artifact_type="mock-exam-item-review-decision",
                    idempotency_key=(
                        f"mock-exam-item-review-decision:{decision.item_review_record_id}"
                    ),
                    request=self._decision_artifact_request(decision),
                    result=self._decision_artifact_result(decision),
                    file_metadata={
                        MOCK_EXAM_ITEM_REVIEW_DECISION_FILE_NAME: {
                            "schema_ref": MOCK_EXAM_ITEM_REVIEW_DECISION_SCHEMA_REF,
                            "media_type": "application/json",
                        }
                    },
                    protocol_version=ITEM_REVIEW_PROTOCOL_VERSION,
                    protocol_schema_hash=ITEM_REVIEW_PROTOCOL_SCHEMA_HASH,
                    expected_file_sha256={
                        MOCK_EXAM_ITEM_REVIEW_DECISION_FILE_NAME: expected_content_hash
                    },
                )
        except (OSError, RuntimeError, ValueError) as exc:
            raise MockExamItemReviewPublicationError(
                "ITEM_REVIEW_DECISION_ARTIFACT_FAILED",
                "Item review decision artifact could not be committed",
            ) from exc
        if committed.content_hash != expected_content_hash:
            self._fail(
                "ITEM_REVIEW_DECISION_ARTIFACT_INVALID",
                "Committed Item review decision hash differs",
            )
        return _DecisionArtifactPointer(
            artifact_id=committed.artifact_id,
            revision_id=committed.revision_id,
            content_hash=committed.content_hash,
        )

    def _resolve_decision_artifact(
        self,
        session: Session,
        *,
        record: ItemReviewRecord,
        expected: MockExamItemReviewDecisionV1,
    ) -> _DecisionArtifactPointer:
        return self._resolve_committed_decision_artifact(
            session,
            pointer=_DecisionArtifactPointer(
                artifact_id=record.review_artifact_id,
                revision_id=record.review_artifact_revision_id,
                content_hash=record.review_sha256,
            ),
            expected=expected,
            mismatch_code="ITEM_REVIEW_IDEMPOTENCY_CONFLICT",
        )

    def _resolve_committed_decision_artifact(
        self,
        session: Session,
        *,
        pointer: _DecisionArtifactPointer,
        expected: MockExamItemReviewDecisionV1,
        mismatch_code: str = "ITEM_REVIEW_DECISION_ARTIFACT_INVALID",
    ) -> _DecisionArtifactPointer:
        artifact = session.get(ArtifactRecord, pointer.artifact_id)
        revision = session.get(ArtifactRevisionRecord, pointer.revision_id)
        job = session.get(JobRecord, revision.job_id) if revision is not None else None
        manifest = revision.manifest if revision is not None else {}
        files = manifest.get("files")
        matching = (
            [
                member
                for member in files
                if isinstance(member, dict)
                and member.get("file_name") == MOCK_EXAM_ITEM_REVIEW_DECISION_FILE_NAME
            ]
            if isinstance(files, list)
            else []
        )
        member = matching[0] if len(matching) == 1 else None
        if (
            artifact is None
            or revision is None
            or job is None
            or member is None
            or not isinstance(files, list)
            or len(files) != 1
            or not artifact.approved
            or artifact.artifact_type != "mock-exam-item-review-decision"
            or artifact.job_id != revision.job_id
            or revision.logical_artifact_id != pointer.artifact_id
            or revision.content_hash != pointer.content_hash
            or revision.manifest_hash != content_sha256(manifest)
            or not revision.approved
            or manifest.get("job_id") != job.job_id
            or manifest.get("logical_artifact_id") != pointer.artifact_id
            or manifest.get("revision_id") != pointer.revision_id
            or manifest.get("artifact_type") != "mock-exam-item-review-decision"
            or manifest.get("primary_file") != MOCK_EXAM_ITEM_REVIEW_DECISION_FILE_NAME
            or manifest.get("content_hash") != pointer.content_hash
            or manifest.get("content_bytes") != revision.content_bytes
            or member.get("sha256") != pointer.content_hash
            or member.get("bytes") != revision.content_bytes
            or member.get("media_type") != "application/json"
            or member.get("schema_ref") != MOCK_EXAM_ITEM_REVIEW_DECISION_SCHEMA_REF
            or job.status != "SUCCEEDED"
            or job.task_type != "mock-exam-item-review-decision"
            or job.protocol_version != ITEM_REVIEW_PROTOCOL_VERSION
            or job.logical_artifact_id != pointer.artifact_id
            or job.revision_id != pointer.revision_id
            or job.request != self._decision_artifact_request(expected)
            or revision.result != self._decision_artifact_result(expected)
        ):
            self._fail(
                "ITEM_REVIEW_DECISION_ARTIFACT_INVALID",
                "Item review decision artifact pointer does not resolve",
            )
        try:
            raw = self.artifacts.read_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.revision_id,
                member_path=MOCK_EXAM_ITEM_REVIEW_DECISION_FILE_NAME,
                sha256=pointer.content_hash,
                media_type="application/json",
                schema_ref=MOCK_EXAM_ITEM_REVIEW_DECISION_SCHEMA_REF,
                max_bytes=MAX_REVIEW_RESULT_BYTES,
            )
            if sha256_bytes(raw) != pointer.content_hash:
                raise ValueError("decision artifact bytes differ from their pointer")
            value: object = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("decision artifact is not an object")
            validate_contract(MOCK_EXAM_ITEM_REVIEW_DECISION_SCHEMA, value)
            parsed = MockExamItemReviewDecisionV1.model_validate(value)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            JsonSchemaValidationError,
            PydanticValidationError,
            ValueError,
        ) as exc:
            raise MockExamItemReviewPublicationError(
                "ITEM_REVIEW_DECISION_ARTIFACT_INVALID",
                "Item review decision artifact failed immutable validation",
            ) from exc
        if parsed != expected:
            self._fail(
                mismatch_code,
                "Item review decision artifact differs from the requested decision",
            )
        return pointer

    @staticmethod
    def _decision_artifact_request(
        decision: MockExamItemReviewDecisionV1,
    ) -> dict[str, Any]:
        return {
            "item_review_record_id": decision.item_review_record_id,
            "item_revision_id": decision.item_revision_id,
            "workflow_id": decision.workflow_id,
            "decision_sha256": decision.decision_sha256,
            "idempotency_key_sha256": decision.idempotency_key_sha256,
        }

    @staticmethod
    def _decision_artifact_result(
        decision: MockExamItemReviewDecisionV1,
    ) -> dict[str, Any]:
        return {
            "item_review_record_id": decision.item_review_record_id,
            "decision": decision.decision,
            "final_rating": decision.final_rating,
            "rating_policy_revision_id": decision.rating_policy_revision_id,
            "rating_policy_sha256": decision.rating_policy_sha256,
            "decision_sha256": decision.decision_sha256,
        }

    def _single_existing_review(
        self,
        session: Session,
        item_revision_id: str,
    ) -> ItemReviewRecord | None:
        rows = tuple(
            session.scalars(
                select(ItemReviewRecord)
                .where(ItemReviewRecord.item_revision_id == item_revision_id)
                .with_for_update()
            )
        )
        if len(rows) > 1:
            self._fail(
                "ITEM_REVIEW_CURRENT_STATE_INVALID",
                "Item revision has multiple published review decisions",
            )
        return rows[0] if rows else None

    def _require_existing_identity(
        self,
        record: ItemReviewRecord,
        expected_record_id: str,
    ) -> None:
        if record.item_review_record_id != expected_record_id:
            self._fail(
                "ITEM_REVIEW_ALREADY_PUBLISHED",
                "Item revision already has an immutable review decision",
            )

    @staticmethod
    def _resolve_rating_policy(
        command: PublishMockExamItemReviewCommand,
    ) -> MockExamRatingPolicyV1:
        try:
            policy = load_integrated_science_mock_exam_rating_policy()
        except (OSError, ValueError) as exc:
            raise MockExamItemReviewPublicationError(
                "ITEM_REVIEW_POLICY_INVALID",
                "Packaged Item rating policy is unavailable or invalid",
            ) from exc
        if (
            command.rating_policy_revision_id != policy.rating_policy_revision_id
            or command.rating_policy_sha256 != content_sha256(policy.model_dump(mode="json"))
            or command.final_rating not in policy.eligible_ratings
        ):
            raise MockExamItemReviewPublicationError(
                "ITEM_REVIEW_POLICY_STALE",
                "Item rating policy pointer is stale",
            )
        return policy

    @staticmethod
    def _idempotency_identity(
        command: PublishMockExamItemReviewCommand,
    ) -> tuple[str, str]:
        key_sha256 = content_sha256(
            {
                "scope": IDEMPOTENCY_SCOPE,
                "idempotency_key": command.idempotency_key,
            }
        )
        return f"itemreview_{key_sha256.removeprefix('sha256:')[:32]}", key_sha256

    @staticmethod
    def _severity_summary(
        command: PublishMockExamItemReviewCommand,
        evidence: _PublicationEvidence,
        *,
        decision: MockExamItemReviewDecisionV1,
        idempotency_key_sha256: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": "mock-exam-item-review-severity-summary/1.0",
            "final_rating": command.final_rating,
            "finding_counts": evidence.finding_counts.model_dump(mode="json"),
            "rating_policy_revision_id": command.rating_policy_revision_id,
            "rating_policy_sha256": command.rating_policy_sha256,
            "review_result_schema": evidence.review_result_schema,
            "review_step_run_id": evidence.review_step_run_id,
            "source_review_artifact_id": evidence.review_artifact_id,
            "source_review_artifact_revision_id": evidence.review_artifact_revision_id,
            "source_review_sha256": evidence.review_sha256,
            "human_approval_request_id": evidence.approval_request_id,
            "decision_sha256": decision.decision_sha256,
            "idempotency_key_sha256": idempotency_key_sha256,
        }

    def _require_exact_replay(
        self,
        record: ItemReviewRecord,
        *,
        command: PublishMockExamItemReviewCommand,
        evidence: _PublicationEvidence,
        decision_artifact: _DecisionArtifactPointer,
        severity_summary: dict[str, Any],
    ) -> None:
        if (
            record.item_revision_id != command.item_revision_id
            or record.workflow_id != evidence.workflow_id
            or record.review_artifact_id != decision_artifact.artifact_id
            or record.review_artifact_revision_id != decision_artifact.revision_id
            or record.review_sha256 != decision_artifact.content_hash
            or record.decision != "APPROVE"
            or record.severity_summary != severity_summary
            or record.reviewer_actor_id != command.reviewer_operator_id
        ):
            self._fail(
                "ITEM_REVIEW_IDEMPOTENCY_CONFLICT",
                "Item review idempotency key was used with different input",
            )

    def _result(
        self,
        record: ItemReviewRecord,
        *,
        evidence: _PublicationEvidence,
        command: PublishMockExamItemReviewCommand,
        decision: MockExamItemReviewDecisionV1,
        created: bool,
    ) -> MockExamItemReviewPublicationResult:
        result = MockExamItemReviewPublicationResult(
            item_review_record_id=record.item_review_record_id,
            item_revision_id=record.item_revision_id,
            workflow_id=record.workflow_id,
            review_step_run_id=evidence.review_step_run_id,
            human_approval_request_id=evidence.approval_request_id,
            review_artifact_id=record.review_artifact_id,
            review_artifact_revision_id=record.review_artifact_revision_id,
            review_sha256=record.review_sha256,
            decision_sha256=decision.decision_sha256,
            review_result_schema=evidence.review_result_schema,
            decision="APPROVE",
            final_rating=command.final_rating,
            finding_counts=evidence.finding_counts,
            reviewer_operator_id=record.reviewer_actor_id,
            rating_policy_revision_id=command.rating_policy_revision_id,
            rating_policy_sha256=command.rating_policy_sha256,
            created=created,
        )
        validate_contract(
            MOCK_EXAM_ITEM_REVIEW_PUBLICATION_RESULT_SCHEMA,
            result.model_dump(mode="json"),
        )
        return result

    @staticmethod
    def _fail(code: str, message: str) -> NoReturn:
        raise MockExamItemReviewPublicationError(code, message)
