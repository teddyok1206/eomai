"""Application lifecycle for content-team/HwpQuestionEditor compatibility evidence."""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Final, NoReturn

from eom_catalog_contracts import (
    EditorialAuthorityPointer,
    HwpQuestionEditorProfilePointer,
    LegacyItemEditorialCompatibilityPolicy,
    LegacyItemEditorialCompatibilityProposal,
    LegacyItemEditorialCompatibilityRequest,
    LegacyItemEditorialCompatibilityResult,
    OriginArtifactMemberPointer,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.control_models import (
    ExecutionBundleRecord,
    ExecutionBundleRevisionRecord,
    ResolvedExecutionPlanRecord,
)
from eom_orchestrator.control_service import ControlPlaneError, compute_control_document_hash
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.execution_resolver import (
    resolve_legacy_item_editorial_compatibility_plan,
)
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_workflow import ReferenceBundleManifest, WorkflowRequest
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import (
    CommandType,
    create_workflow_instance,
    enqueue_command,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.item_origin_models import ItemOriginProfileRecord
from eom_catalog_service.legacy_assessment_models import (
    LegacyItemExtractionAcceptanceRecord,
)
from eom_catalog_service.legacy_item_editorial_validation import (
    LegacyItemEditorialDeterministicEvaluator,
)
from eom_catalog_service.legacy_item_learning_models import (
    LegacyItemEditorialCompatibilityEventRecord,
    LegacyItemEditorialCompatibilityPolicyRecord,
    LegacyItemEditorialCompatibilityRunRecord,
)
from eom_catalog_service.models import ItemComponentRecord, ItemRevisionRecord
from eom_catalog_service.settings import CatalogSettings

MAX_AUTHORITY_BYTES: Final = 2 * 1024 * 1024
MAX_PROPOSAL_BYTES: Final = 2 * 1024 * 1024
REFERENCE_BUNDLE_KEY: Final = "standard-item-authoring-guidance"
AUTHORITY_BINDINGS: Final = MappingProxyType(
    {
        "CONTENT_TEAM_PROMPT": (
            "content-team-integrated-science-authoring-v05",
            "5.0",
        ),
        "HWP_QUESTION_EDITOR_PROFILE": (
            "content-team-hwp-question-editor-handoff-v1",
            "1.0",
        ),
    }
)
ACTIVE_STATES: Final = frozenset({"REQUESTED", "RESOLVED", "QUEUED", "RUNNING", "VALIDATING"})
TERMINAL_STATES: Final = frozenset({"OPEN", "CLOSED", "FAILED", "CANCELLED"})
COMPATIBILITY_STEP_KEY: Final = "assess"
COMPATIBILITY_ROLE_RESULT_SCHEMA: Final = "legacy-item-editorial-compatibility-result@1.0"
COMPATIBILITY_WORKFLOW_KEY: Final = "legacy-item-editorial-compatibility"
COMPATIBILITY_WORKFLOW_VERSION: Final = "1.0.0"
COMPATIBILITY_WORKFLOW_PROTOCOL: Final = "workflow-role/1.16.0"
TRANSITIONS: Final = MappingProxyType(
    {
        "REQUESTED": frozenset({"RESOLVED", "FAILED", "CANCELLED"}),
        "RESOLVED": frozenset({"QUEUED", "FAILED", "CANCELLED"}),
        "QUEUED": frozenset({"RUNNING", "FAILED", "CANCELLED"}),
        "RUNNING": frozenset({"VALIDATING", "FAILED", "CANCELLED"}),
        "VALIDATING": frozenset({"OPEN", "CLOSED", "FAILED"}),
        "OPEN": frozenset(),
        "CLOSED": frozenset(),
        "FAILED": frozenset(),
        "CANCELLED": frozenset(),
    }
)


class LegacyItemEditorialCompatibilityError(RuntimeError):
    """Stable, content-free error at the editorial compatibility boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LegacyItemEditorialCompatibilityView:
    compatibility_run_id: str
    predecessor_compatibility_run_id: str | None
    compatibility_request_id: str
    request_sha256: str
    compatibility_key_sha256: str
    workflow_id: str | None
    plan_id: str | None
    platform_job_id: str | None
    state: str
    result_status: str | None
    result_artifact_id: str | None
    result_artifact_revision_id: str | None
    result_sha256: str | None
    lossless_projection: bool | None
    issue_count: int | None
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None


class LegacyItemEditorialCompatibilityService:
    """Persist exact authority-bound attempts without introducing EOM editorial rules."""

    def __init__(
        self,
        engine: Engine,
        settings: CatalogSettings | None = None,
        *,
        artifacts: CatalogArtifactService | None = None,
        deterministic_evaluator: LegacyItemEditorialDeterministicEvaluator | None = None,
    ) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.artifacts = artifacts or CatalogArtifactService(engine, self.settings)
        self.deterministic_evaluator = deterministic_evaluator or (
            LegacyItemEditorialDeterministicEvaluator(
                engine,
                self.settings,
                artifacts=self.artifacts,
            )
        )

    def release_policy(
        self, policy: LegacyItemEditorialCompatibilityPolicy
    ) -> LegacyItemEditorialCompatibilityPolicy:
        raw = policy.model_dump(mode="json")
        validate_contract("legacy-item-editorial-compatibility-policy", raw)
        with transaction(self.sessions) as session:
            existing = session.get(
                LegacyItemEditorialCompatibilityPolicyRecord,
                policy.compatibility_policy_revision_id,
            )
            if existing is not None:
                if (
                    existing.content_sha256 != policy.content_sha256
                    or existing.canonical_document != raw
                ):
                    self._raise(
                        "LEGACY_EDITORIAL_POLICY_IDENTITY_CONFLICT",
                        "editorial compatibility policy identity has different content",
                    )
                return policy
            session.add(
                LegacyItemEditorialCompatibilityPolicyRecord(
                    compatibility_policy_revision_id=policy.compatibility_policy_revision_id,
                    schema_version=policy.schema_version,
                    state=policy.state,
                    content_sha256=policy.content_sha256,
                    canonical_document=raw,
                    released_by=policy.released_by,
                    released_at=policy.released_at,
                )
            )
        return policy

    def create(
        self,
        request: LegacyItemEditorialCompatibilityRequest,
        *,
        idempotency_key: str,
        requested_by: str,
    ) -> LegacyItemEditorialCompatibilityView:
        self._require_idempotency_key(idempotency_key)
        raw = request.model_dump(mode="json")
        validate_contract("legacy-item-editorial-compatibility-request", raw)
        submission_sha256 = content_sha256({"request": raw, "requested_by": requested_by})
        compatibility_key_sha256 = self.compatibility_key(request)
        try:
            with transaction(self.sessions) as session:
                replay = session.scalar(
                    select(LegacyItemEditorialCompatibilityRunRecord)
                    .where(
                        LegacyItemEditorialCompatibilityRunRecord.idempotency_key == idempotency_key
                    )
                    .with_for_update()
                )
                if replay is not None:
                    if replay.submission_sha256 != submission_sha256:
                        self._raise(
                            "LEGACY_EDITORIAL_IDEMPOTENCY_CONFLICT",
                            "editorial compatibility idempotency key has different input",
                        )
                    return self._projection(replay)

                closed = session.scalar(
                    select(LegacyItemEditorialCompatibilityRunRecord)
                    .where(
                        LegacyItemEditorialCompatibilityRunRecord.compatibility_key_sha256
                        == compatibility_key_sha256,
                        LegacyItemEditorialCompatibilityRunRecord.state == "CLOSED",
                    )
                    .with_for_update()
                )
                if closed is not None:
                    return self._projection(closed)

                latest = session.scalar(
                    select(LegacyItemEditorialCompatibilityRunRecord)
                    .where(
                        LegacyItemEditorialCompatibilityRunRecord.compatibility_key_sha256
                        == compatibility_key_sha256
                    )
                    .order_by(
                        LegacyItemEditorialCompatibilityRunRecord.created_at.desc(),
                        LegacyItemEditorialCompatibilityRunRecord.compatibility_run_id.desc(),
                    )
                    .limit(1)
                    .with_for_update()
                )
                if latest is not None and latest.state in ACTIVE_STATES | {"OPEN"}:
                    if request.predecessor_compatibility_run_id is not None:
                        self._raise(
                            "LEGACY_EDITORIAL_ATTEMPT_EXISTS",
                            "editorial compatibility tuple already has current work or a result",
                        )
                    return self._projection(latest)
                self._validate_predecessor(request, latest)
                self._resolve_dependencies(session, request)
                created_at = request.created_at.astimezone(UTC)
                run = LegacyItemEditorialCompatibilityRunRecord(
                    compatibility_run_id=self._run_id(request.compatibility_request_id),
                    predecessor_compatibility_run_id=request.predecessor_compatibility_run_id,
                    compatibility_request_id=request.compatibility_request_id,
                    request_sha256=request.request_sha256,
                    submission_sha256=submission_sha256,
                    compatibility_key_sha256=compatibility_key_sha256,
                    idempotency_key=idempotency_key,
                    canonical_request=raw,
                    item_id=request.source.item_id,
                    item_revision_id=request.source.item_revision_id,
                    item_manifest_sha256=request.source.item_manifest_sha256,
                    item_content_artifact_id=request.source.item_content.artifact_id,
                    item_content_artifact_revision_id=(
                        request.source.item_content.artifact_revision_id
                    ),
                    item_content_member_path=request.source.item_content.member_path,
                    item_content_schema_ref=request.source.item_content.schema_ref,
                    item_content_media_type=request.source.item_content.media_type,
                    item_content_sha256=request.source.item_content.sha256,
                    extraction_acceptance_id=request.source.extraction_acceptance_id,
                    extraction_acceptance_sha256=(request.source.extraction_acceptance_sha256),
                    item_origin_profile_id=request.source.item_origin_profile_id,
                    item_origin_profile_sha256=request.source.item_origin_profile_sha256,
                    authoring_prompt_artifact_id=(
                        request.authorities[0].artifact_member.artifact_id
                    ),
                    authoring_prompt_artifact_revision_id=(
                        request.authorities[0].artifact_member.artifact_revision_id
                    ),
                    authoring_prompt_member_path=(
                        request.authorities[0].artifact_member.member_path
                    ),
                    authoring_prompt_sha256=request.authorities[0].artifact_member.sha256,
                    hwpx_profile_artifact_id=(request.authorities[1].artifact_member.artifact_id),
                    hwpx_profile_artifact_revision_id=(
                        request.authorities[1].artifact_member.artifact_revision_id
                    ),
                    hwpx_profile_member_path=(request.authorities[1].artifact_member.member_path),
                    hwpx_profile_sha256=request.authorities[1].artifact_member.sha256,
                    renderer_profile_artifact_id=request.renderer_profile.artifact_id,
                    renderer_profile_artifact_revision_id=(
                        request.renderer_profile.artifact_revision_id
                    ),
                    renderer_profile_archive_sha256=request.renderer_profile.archive_sha256,
                    renderer_profile_sha256=request.renderer_profile.profile_sha256,
                    compatibility_policy_revision_id=(request.compatibility_policy_revision_id),
                    compatibility_policy_sha256=request.compatibility_policy_sha256,
                    workflow_id=None,
                    plan_id=None,
                    platform_job_id=None,
                    proposal_artifact_id=None,
                    proposal_artifact_revision_id=None,
                    proposal_sha256=None,
                    result_artifact_id=None,
                    result_artifact_revision_id=None,
                    result_sha256=None,
                    result_status=None,
                    lossless_projection=None,
                    issue_count=None,
                    state="REQUESTED",
                    lock_version=1,
                    requested_by_operator_id=requested_by,
                    created_at=created_at,
                    started_at=None,
                    completed_at=None,
                    error_code=None,
                    error_summary=None,
                )
                session.add(run)
                session.flush()
                self._append_event(
                    session,
                    run,
                    event_type="COMPATIBILITY_REQUESTED",
                    prior_state=None,
                    actor_type="human",
                    actor_id=requested_by,
                    payload={
                        "request_sha256": request.request_sha256,
                        "compatibility_key_sha256": compatibility_key_sha256,
                        "predecessor_compatibility_run_id": (
                            request.predecessor_compatibility_run_id
                        ),
                    },
                )
                return self._projection(run)
        except LegacyItemEditorialCompatibilityError:
            raise
        except IntegrityError as exc:
            raise LegacyItemEditorialCompatibilityError(
                "LEGACY_EDITORIAL_CONCURRENCY_CONFLICT",
                "editorial compatibility request raced with another transaction",
            ) from exc
        except (JsonSchemaValidationError, PydanticValidationError, ValueError) as exc:
            raise LegacyItemEditorialCompatibilityError(
                "LEGACY_EDITORIAL_REQUEST_INVALID",
                "editorial compatibility request is invalid",
            ) from exc

    def bind_execution(
        self,
        compatibility_run_id: str,
        *,
        workflow_id: str,
        plan_id: str,
        actor_id: str,
    ) -> LegacyItemEditorialCompatibilityView:
        with transaction(self.sessions) as session:
            run = self._locked_run(session, compatibility_run_id)
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            plan = session.get(ResolvedExecutionPlanRecord, plan_id)
            if (
                run.state != "REQUESTED"
                or workflow is None
                or plan is None
                or plan.workflow_id != workflow_id
                or workflow.definition_key != "legacy-item-editorial-compatibility"
            ):
                self._raise(
                    "LEGACY_EDITORIAL_EXECUTION_INVALID",
                    "editorial compatibility execution pointers do not resolve",
                )
            run.workflow_id = workflow_id
            run.plan_id = plan_id
            self._transition(
                session,
                run,
                "RESOLVED",
                "COMPATIBILITY_EXECUTION_RESOLVED",
                actor_type="service",
                actor_id=actor_id,
                payload={"workflow_id": workflow_id, "plan_id": plan_id},
            )
            self._transition(
                session,
                run,
                "QUEUED",
                "COMPATIBILITY_WORKFLOW_QUEUED",
                actor_type="service",
                actor_id=actor_id,
                payload={"workflow_id": workflow_id},
            )
            return self._projection(run)

    def submit(
        self,
        request: LegacyItemEditorialCompatibilityRequest,
        *,
        idempotency_key: str,
        requested_by: str,
    ) -> LegacyItemEditorialCompatibilityView:
        """Create or replay one run, then transactionally bind its one-shot workflow."""

        view = self.create(
            request,
            idempotency_key=idempotency_key,
            requested_by=requested_by,
        )
        if view.state != "REQUESTED":
            return view
        workflow_key = f"legacy-editorial-workflow:{view.compatibility_run_id}"
        try:
            with transaction(self.sessions) as session:
                run = self._locked_run(session, view.compatibility_run_id)
                if run.state != "REQUESTED":
                    return self._projection(run)
                definition = session.scalar(
                    select(WorkflowDefinitionRecord).where(
                        WorkflowDefinitionRecord.definition_key == COMPATIBILITY_WORKFLOW_KEY,
                        WorkflowDefinitionRecord.definition_version
                        == COMPATIBILITY_WORKFLOW_VERSION,
                        WorkflowDefinitionRecord.active.is_(True),
                    )
                )
                if definition is None:
                    self._raise(
                        "LEGACY_EDITORIAL_WORKFLOW_UNAVAILABLE",
                        "editorial compatibility workflow definition is unavailable",
                    )
                workflow_request = WorkflowRequest(
                    request_name="LEGACY_ITEM_EDITORIAL_COMPATIBILITY_REQUEST",
                    image_mode="skip",
                    legacy_editorial_compatibility_request=request,
                )
                workflow, _created = create_workflow_instance(
                    session,
                    definition=definition,
                    request=workflow_request,
                    idempotency_key=workflow_key,
                    actor_type="human",
                    actor_id=requested_by,
                    runtime_context={
                        "legacy_editorial_compatibility_run_id": run.compatibility_run_id,
                        "legacy_editorial_compatibility_request_sha256": request.request_sha256,
                    },
                )
                if workflow.role_schema_version != COMPATIBILITY_WORKFLOW_PROTOCOL:
                    self._raise(
                        "LEGACY_EDITORIAL_WORKFLOW_INCOMPATIBLE",
                        "editorial compatibility workflow protocol is incompatible",
                    )
                plan = resolve_legacy_item_editorial_compatibility_plan(
                    session,
                    workflow_id=workflow.workflow_id,
                    workflow_definition_version=definition.definition_version,
                    workflow_definition_sha256=definition.definition_hash,
                    workflow_role_schema_version=workflow.role_schema_version,
                    request=request,
                )
                start, _command_created = enqueue_command(
                    session,
                    workflow_id=workflow.workflow_id,
                    command_type=CommandType.START_WORKFLOW,
                    payload={},
                    actor_type="human",
                    actor_id=requested_by,
                    source="legacy_item_editorial_compatibility",
                    idempotency_key=f"start:{workflow.workflow_id}",
                )
                run.workflow_id = workflow.workflow_id
                run.plan_id = plan.plan_id
                self._transition(
                    session,
                    run,
                    "RESOLVED",
                    "COMPATIBILITY_EXECUTION_RESOLVED",
                    actor_type="service",
                    actor_id="legacy-editorial-compatibility",
                    payload={
                        "workflow_id": workflow.workflow_id,
                        "plan_id": plan.plan_id,
                    },
                )
                self._transition(
                    session,
                    run,
                    "QUEUED",
                    "COMPATIBILITY_WORKFLOW_QUEUED",
                    actor_type="service",
                    actor_id="legacy-editorial-compatibility",
                    payload={
                        "workflow_id": workflow.workflow_id,
                        "start_command_id": start.command_id,
                    },
                )
                return self._projection(run)
        except LegacyItemEditorialCompatibilityError:
            raise
        except (ControlPlaneError, WorkflowError, IntegrityError) as exc:
            raise LegacyItemEditorialCompatibilityError(
                "LEGACY_EDITORIAL_SUBMISSION_FAILED",
                "editorial compatibility workflow could not be submitted",
            ) from exc

    def mark_running(
        self,
        compatibility_run_id: str,
        *,
        platform_job_id: str,
        actor_id: str,
    ) -> LegacyItemEditorialCompatibilityView:
        with transaction(self.sessions) as session:
            run = self._locked_run(session, compatibility_run_id)
            job = session.get(JobRecord, platform_job_id)
            if (
                run.state != "QUEUED"
                or run.workflow_id is None
                or job is None
                or job.request.get("workflow_id") != run.workflow_id
            ):
                self._raise(
                    "LEGACY_EDITORIAL_JOB_INVALID",
                    "editorial compatibility job does not bind its workflow",
                )
            run.platform_job_id = platform_job_id
            run.started_at = datetime.now(UTC)
            self._transition(
                session,
                run,
                "RUNNING",
                "COMPATIBILITY_WORKER_STARTED",
                actor_type="service",
                actor_id=actor_id,
                payload={"platform_job_id": platform_job_id},
            )
            return self._projection(run)

    def complete(
        self,
        compatibility_run_id: str,
        *,
        proposal_artifact: OriginArtifactMemberPointer,
        proposal: LegacyItemEditorialCompatibilityProposal,
        completed_at: datetime,
        actor_id: str,
    ) -> LegacyItemEditorialCompatibilityView:
        if completed_at.tzinfo is None or completed_at.utcoffset() is None:
            self._raise(
                "LEGACY_EDITORIAL_RESULT_INVALID",
                "editorial compatibility completion time must be timezone-aware",
            )
        with transaction(self.sessions) as session:
            run = self._locked_run(session, compatibility_run_id)
            if run.state == "OPEN" or run.state == "CLOSED":
                return self._projection(run)
            if run.state not in {"RUNNING", "VALIDATING"}:
                self._raise(
                    "LEGACY_EDITORIAL_STATE_INVALID",
                    "editorial compatibility run is not ready for validation",
                )
            request = LegacyItemEditorialCompatibilityRequest.model_validate(run.canonical_request)
            self._require_proposal(request, proposal)
            self._require_succeeded_worker_proposal(
                session,
                run=run,
                proposal_artifact=proposal_artifact,
            )
            if run.state == "RUNNING":
                self._transition(
                    session,
                    run,
                    "VALIDATING",
                    "COMPATIBILITY_PROPOSAL_RECEIVED",
                    actor_type="service",
                    actor_id=actor_id,
                    payload={"proposal_sha256": proposal.proposal_sha256},
                )

        proposal_bytes = self.artifacts.read_member(
            artifact_id=proposal_artifact.artifact_id,
            revision_id=proposal_artifact.artifact_revision_id,
            member_path=proposal_artifact.member_path,
            sha256=proposal_artifact.sha256,
            media_type=proposal_artifact.media_type,
            schema_ref=proposal_artifact.schema_ref,
            max_bytes=MAX_PROPOSAL_BYTES,
        )
        try:
            raw_proposal = json.loads(proposal_bytes)
            if not isinstance(raw_proposal, dict):
                raise ValueError("proposal is not an object")
            validate_contract("legacy-item-editorial-compatibility-proposal", raw_proposal)
            stored_proposal = LegacyItemEditorialCompatibilityProposal.model_validate(raw_proposal)
        except (
            UnicodeError,
            json.JSONDecodeError,
            JsonSchemaValidationError,
            PydanticValidationError,
            ValueError,
        ) as exc:
            self.fail(
                compatibility_run_id,
                error_code="LEGACY_EDITORIAL_PROPOSAL_INVALID",
                actor_id=actor_id,
            )
            raise LegacyItemEditorialCompatibilityError(
                "LEGACY_EDITORIAL_PROPOSAL_INVALID",
                "editorial proposal artifact is invalid",
            ) from exc
        if stored_proposal != proposal:
            self.fail(
                compatibility_run_id,
                error_code="LEGACY_EDITORIAL_PROPOSAL_MISMATCH",
                actor_id=actor_id,
            )
            self._raise(
                "LEGACY_EDITORIAL_PROPOSAL_MISMATCH",
                "editorial proposal does not match its immutable Artifact member",
            )

        try:
            assessment = self.deterministic_evaluator.evaluate(request)
        except ValueError as exc:
            self.fail(
                compatibility_run_id,
                error_code="LEGACY_EDITORIAL_DETERMINISTIC_CHECK_FAILED",
                actor_id=actor_id,
            )
            raise LegacyItemEditorialCompatibilityError(
                "LEGACY_EDITORIAL_DETERMINISTIC_CHECK_FAILED",
                "server-owned editorial compatibility validation failed",
            ) from exc

        result_data: dict[str, object] = {
            "schema_version": "legacy-item-editorial-compatibility-result/1.0",
            "compatibility_result_id": self._result_id(compatibility_run_id),
            "compatibility_request_id": proposal.compatibility_request_id,
            "request_sha256": proposal.request_sha256,
            "source": proposal.source.model_dump(mode="json"),
            "authorities": [
                authority.model_dump(mode="json") for authority in proposal.authorities
            ],
            "renderer_profile": proposal.renderer_profile.model_dump(mode="json"),
            "proposal_artifact": proposal_artifact.model_dump(mode="json"),
            "proposal_sha256": proposal.proposal_sha256,
            "status": proposal.status,
            "issues": [issue.model_dump(mode="json") for issue in proposal.issues],
            "deterministic_checks": [check.model_dump(mode="json") for check in assessment.checks],
            "lossless_projection": assessment.lossless_projection,
            "convergence_state": ("CLOSED" if proposal.status == "COMPATIBLE" else "OPEN"),
            "completed_at": (
                completed_at.astimezone(UTC)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z")
            ),
        }
        result_data["result_sha256"] = content_sha256(result_data)
        try:
            validate_contract("legacy-item-editorial-compatibility-result", result_data)
            result = LegacyItemEditorialCompatibilityResult.model_validate(result_data)
        except (JsonSchemaValidationError, PydanticValidationError, ValueError) as exc:
            self.fail(
                compatibility_run_id,
                error_code="LEGACY_EDITORIAL_DETERMINISTIC_CHECK_FAILED",
                actor_id=actor_id,
            )
            raise LegacyItemEditorialCompatibilityError(
                "LEGACY_EDITORIAL_DETERMINISTIC_CHECK_FAILED",
                "editorial proposal did not satisfy deterministic compatibility checks",
            ) from exc

        result_bytes = canonical_json_bytes(result.model_dump(mode="json"))
        result_artifact_sha256 = sha256_bytes(result_bytes)
        with tempfile.TemporaryDirectory(prefix="eom-editorial-compatibility-") as raw:
            source = Path(raw) / "result.json"
            source.write_bytes(result_bytes)
            artifact = self.artifacts.commit_file_set(
                files={"result.json": source},
                primary_file="result.json",
                artifact_type="legacy-item-editorial-compatibility-result",
                idempotency_key=f"legacy-editorial-result:{compatibility_run_id}",
                request={
                    "compatibility_run_id": compatibility_run_id,
                    "proposal_sha256": proposal.proposal_sha256,
                },
                result={
                    "compatibility_result_id": result.compatibility_result_id,
                    "result_sha256": result.result_sha256,
                },
                file_metadata={
                    "result.json": {
                        "schema_ref": (
                            "eom://schemas/legacy-assessment/"
                            "legacy-item-editorial-compatibility-result/1.0"
                        ),
                        "media_type": "application/json",
                    }
                },
                expected_file_sha256={"result.json": result_artifact_sha256},
            )

        with transaction(self.sessions) as session:
            run = self._locked_run(session, compatibility_run_id)
            if run.state in {"OPEN", "CLOSED"}:
                return self._projection(run)
            if (
                run.state != "VALIDATING"
                or run.request_sha256 != result.request_sha256
                or run.proposal_artifact_revision_id is not None
            ):
                self._raise(
                    "LEGACY_EDITORIAL_STATE_INVALID",
                    "editorial compatibility state changed during validation",
                )
            run.proposal_artifact_id = proposal_artifact.artifact_id
            run.proposal_artifact_revision_id = proposal_artifact.artifact_revision_id
            run.proposal_sha256 = proposal.proposal_sha256
            run.result_artifact_id = artifact.artifact_id
            run.result_artifact_revision_id = artifact.revision_id
            run.result_sha256 = result.result_sha256
            run.result_status = result.status
            run.lossless_projection = result.lossless_projection
            run.issue_count = len(result.issues)
            run.completed_at = result.completed_at
            terminal = "CLOSED" if result.convergence_state == "CLOSED" else "OPEN"
            self._transition(
                session,
                run,
                terminal,
                "COMPATIBILITY_CLOSED"
                if terminal == "CLOSED"
                else "COMPATIBILITY_ADAPTATION_REQUIRED",
                actor_type="service",
                actor_id=actor_id,
                payload={
                    "result_artifact_revision_id": artifact.revision_id,
                    "result_sha256": result.result_sha256,
                    "result_status": result.status,
                    "issue_count": len(result.issues),
                },
            )
            return self._projection(run)

    def inspect(self, compatibility_run_id: str) -> LegacyItemEditorialCompatibilityView:
        with self.sessions() as session:
            run = session.get(LegacyItemEditorialCompatibilityRunRecord, compatibility_run_id)
            if run is None:
                self._raise(
                    "LEGACY_EDITORIAL_RUN_NOT_FOUND",
                    "editorial compatibility run does not exist",
                )
            return self._projection(run)

    def reconcile(
        self,
        compatibility_run_id: str,
        *,
        actor_id: str,
    ) -> LegacyItemEditorialCompatibilityView:
        """Advance one run only from its exact persisted workflow evidence."""

        view = self.inspect(compatibility_run_id)
        if view.state in TERMINAL_STATES:
            return view
        with self.sessions() as session:
            run = session.get(LegacyItemEditorialCompatibilityRunRecord, compatibility_run_id)
            workflow = (
                session.get(WorkflowInstanceRecord, run.workflow_id)
                if run is not None and run.workflow_id is not None
                else None
            )
            step = (
                session.scalar(
                    select(WorkflowStepRunRecord)
                    .where(
                        WorkflowStepRunRecord.workflow_id == run.workflow_id,
                        WorkflowStepRunRecord.step_key == COMPATIBILITY_STEP_KEY,
                    )
                    .order_by(WorkflowStepRunRecord.attempt.desc())
                    .limit(1)
                )
                if run is not None and run.workflow_id is not None
                else None
            )
            job = (
                session.get(JobRecord, step.platform_job_id)
                if step is not None and step.platform_job_id is not None
                else None
            )
            workflow_terminal_failure = workflow is not None and workflow.state in {
                "FAILED",
                "CANCELLED",
            }
        if workflow_terminal_failure:
            return self.fail(
                compatibility_run_id,
                error_code="LEGACY_EDITORIAL_WORKFLOW_FAILED",
                actor_id=actor_id,
            )
        if view.state == "QUEUED" and job is not None:
            view = self.mark_running(
                compatibility_run_id,
                platform_job_id=job.job_id,
                actor_id=actor_id,
            )
        if view.state not in {"RUNNING", "VALIDATING"}:
            return view
        if (
            workflow is None
            or step is None
            or job is None
            or workflow.state != "COMPLETED"
            or workflow.stage != "COMPLETED"
            or step.state != "SUCCEEDED"
            or job.status != "SUCCEEDED"
        ):
            return view
        output = step.output_pointer_manifest
        if not isinstance(output, dict):
            self._raise(
                "LEGACY_EDITORIAL_PROPOSAL_PROVENANCE_INVALID",
                "completed compatibility step has no output pointer manifest",
            )
        try:
            proposal_artifact = OriginArtifactMemberPointer.model_validate(
                {
                    "artifact_id": output["logical_artifact_id"],
                    "artifact_revision_id": output["revision_id"],
                    "member_path": "result.json",
                    "schema_ref": (
                        "eom://schemas/legacy-assessment/"
                        "legacy-item-editorial-compatibility-proposal/1.0"
                    ),
                    "media_type": "application/json",
                    "sha256": output["content_hash"],
                }
            )
            proposal_bytes = self.artifacts.read_member(
                artifact_id=proposal_artifact.artifact_id,
                revision_id=proposal_artifact.artifact_revision_id,
                member_path=proposal_artifact.member_path,
                sha256=proposal_artifact.sha256,
                media_type=proposal_artifact.media_type,
                schema_ref=proposal_artifact.schema_ref,
                max_bytes=MAX_PROPOSAL_BYTES,
            )
            proposal_raw = json.loads(proposal_bytes)
            if not isinstance(proposal_raw, dict):
                raise ValueError("proposal is not an object")
            validate_contract("legacy-item-editorial-compatibility-proposal", proposal_raw)
            proposal = LegacyItemEditorialCompatibilityProposal.model_validate(proposal_raw)
        except (
            KeyError,
            UnicodeError,
            json.JSONDecodeError,
            JsonSchemaValidationError,
            PydanticValidationError,
            ValueError,
        ) as exc:
            self.fail(
                compatibility_run_id,
                error_code="LEGACY_EDITORIAL_PROPOSAL_INVALID",
                actor_id=actor_id,
            )
            raise LegacyItemEditorialCompatibilityError(
                "LEGACY_EDITORIAL_PROPOSAL_INVALID",
                "completed compatibility proposal is invalid",
            ) from exc
        completed_at = job.completed_at or step.finished_at or datetime.now(UTC)
        return self.complete(
            compatibility_run_id,
            proposal_artifact=proposal_artifact,
            proposal=proposal,
            completed_at=completed_at,
            actor_id=actor_id,
        )

    def fail(
        self,
        compatibility_run_id: str,
        *,
        error_code: str,
        actor_id: str,
    ) -> LegacyItemEditorialCompatibilityView:
        if re.fullmatch(r"[A-Z][A-Z0-9_]{2,95}", error_code) is None:
            self._raise(
                "LEGACY_EDITORIAL_FAILURE_INVALID",
                "editorial compatibility failure code is invalid",
            )
        with transaction(self.sessions) as session:
            run = self._locked_run(session, compatibility_run_id)
            if run.state in TERMINAL_STATES:
                return self._projection(run)
            run.error_code = error_code
            run.error_summary = "editorial compatibility attempt failed"
            run.completed_at = datetime.now(UTC)
            self._transition(
                session,
                run,
                "FAILED",
                "COMPATIBILITY_FAILED",
                actor_type="service",
                actor_id=actor_id,
                payload={"error_code": error_code},
            )
            return self._projection(run)

    @staticmethod
    def compatibility_key(request: LegacyItemEditorialCompatibilityRequest) -> str:
        return content_sha256(
            {
                "item_revision_id": request.source.item_revision_id,
                "item_content_sha256": request.source.item_content.sha256,
                "authoring_prompt_artifact_revision_id": (
                    request.authorities[0].artifact_member.artifact_revision_id
                ),
                "authoring_prompt_sha256": (request.authorities[0].artifact_member.sha256),
                "hwpx_profile_artifact_revision_id": (
                    request.authorities[1].artifact_member.artifact_revision_id
                ),
                "hwpx_profile_sha256": request.authorities[1].artifact_member.sha256,
                "renderer_profile_artifact_revision_id": (
                    request.renderer_profile.artifact_revision_id
                ),
                "renderer_profile_archive_sha256": request.renderer_profile.archive_sha256,
                "renderer_profile_sha256": request.renderer_profile.profile_sha256,
                "compatibility_policy_revision_id": (request.compatibility_policy_revision_id),
                "compatibility_policy_sha256": request.compatibility_policy_sha256,
            }
        )

    def _resolve_dependencies(
        self,
        session: Session,
        request: LegacyItemEditorialCompatibilityRequest,
    ) -> None:
        policy = session.get(
            LegacyItemEditorialCompatibilityPolicyRecord,
            request.compatibility_policy_revision_id,
        )
        if (
            policy is None
            or policy.state != "RELEASED"
            or policy.content_sha256 != request.compatibility_policy_sha256
        ):
            self._raise(
                "LEGACY_EDITORIAL_POLICY_STALE",
                "editorial compatibility policy does not resolve",
            )
        parsed_policy = LegacyItemEditorialCompatibilityPolicy.model_validate(
            policy.canonical_document
        )
        if (
            parsed_policy.content_sha256 != request.compatibility_policy_sha256
            or parsed_policy.required_checks != request.requested_checks
        ):
            self._raise(
                "LEGACY_EDITORIAL_POLICY_STALE",
                "editorial compatibility policy differs from the request",
            )
        self._resolve_source(session, request)
        self._resolve_authorities(session, request.authorities)
        self._resolve_renderer_profile(request.renderer_profile)

    def _require_succeeded_worker_proposal(
        self,
        session: Session,
        *,
        run: LegacyItemEditorialCompatibilityRunRecord,
        proposal_artifact: OriginArtifactMemberPointer,
    ) -> None:
        job = (
            session.get(JobRecord, run.platform_job_id) if run.platform_job_id is not None else None
        )
        workflow = (
            session.get(WorkflowInstanceRecord, run.workflow_id)
            if run.workflow_id is not None
            else None
        )
        step = (
            session.scalar(
                select(WorkflowStepRunRecord).where(
                    WorkflowStepRunRecord.workflow_id == run.workflow_id,
                    WorkflowStepRunRecord.step_key == COMPATIBILITY_STEP_KEY,
                    WorkflowStepRunRecord.platform_job_id == run.platform_job_id,
                )
            )
            if run.workflow_id is not None and run.platform_job_id is not None
            else None
        )
        revision = session.get(
            ArtifactRevisionRecord,
            proposal_artifact.artifact_revision_id,
        )
        output = step.output_pointer_manifest if step is not None else None
        if (
            job is None
            or workflow is None
            or step is None
            or revision is None
            or job.status != "SUCCEEDED"
            or workflow.state != "COMPLETED"
            or workflow.stage != "COMPLETED"
            or workflow.definition_key != "legacy-item-editorial-compatibility"
            or job.task_type != "workflow_support"
            or job.logical_artifact_id != proposal_artifact.artifact_id
            or job.revision_id != proposal_artifact.artifact_revision_id
            or job.request.get("workflow_id") != run.workflow_id
            or job.request.get("step_run_id") != step.step_run_id
            or job.request.get("role") != "support"
            or step.state != "SUCCEEDED"
            or step.worker_role != "support"
            or step.result_schema != COMPATIBILITY_ROLE_RESULT_SCHEMA
            or revision.logical_artifact_id != proposal_artifact.artifact_id
            or revision.job_id != job.job_id
            or not revision.approved
            or proposal_artifact.member_path != "result.json"
            or proposal_artifact.media_type != "application/json"
            or proposal_artifact.schema_ref
            != ("eom://schemas/legacy-assessment/legacy-item-editorial-compatibility-proposal/1.0")
            or not isinstance(output, dict)
            or output.get("logical_artifact_id") != proposal_artifact.artifact_id
            or output.get("revision_id") != proposal_artifact.artifact_revision_id
            or output.get("content_hash") != proposal_artifact.sha256
        ):
            self._raise(
                "LEGACY_EDITORIAL_PROPOSAL_PROVENANCE_INVALID",
                "editorial proposal is not the exact succeeded workflow output",
            )

    def _resolve_source(
        self,
        session: Session,
        request: LegacyItemEditorialCompatibilityRequest,
    ) -> None:
        source = request.source
        revision = session.get(ItemRevisionRecord, source.item_revision_id)
        component = session.scalar(
            select(ItemComponentRecord).where(
                ItemComponentRecord.item_revision_id == source.item_revision_id,
                ItemComponentRecord.component_type == "ITEM_CONTENT",
                ItemComponentRecord.ordinal == 0,
            )
        )
        acceptance = session.get(
            LegacyItemExtractionAcceptanceRecord, source.extraction_acceptance_id
        )
        origin = session.get(ItemOriginProfileRecord, source.item_origin_profile_id)
        if (
            revision is None
            or revision.item_id != source.item_id
            or revision.revision_state != "APPROVED"
            or revision.manifest_sha256 != source.item_manifest_sha256
            or component is None
            or component.artifact_id != source.item_content.artifact_id
            or component.artifact_revision_id != source.item_content.artifact_revision_id
            or component.logical_name != source.item_content.member_path
            or component.schema_ref != source.item_content.schema_ref
            or component.media_type != source.item_content.media_type
            or component.sha256 != source.item_content.sha256
            or acceptance is None
            or acceptance.acceptance_sha256 != source.extraction_acceptance_sha256
            or origin is None
            or origin.item_id != source.item_id
            or origin.item_revision_id != source.item_revision_id
            or origin.item_manifest_sha256 != source.item_manifest_sha256
            or origin.profile_sha256 != source.item_origin_profile_sha256
        ):
            self._raise(
                "LEGACY_EDITORIAL_SOURCE_STALE",
                "approved legacy Item source pointers do not resolve",
            )
        self.artifacts.verify_member(
            artifact_id=source.item_content.artifact_id,
            revision_id=source.item_content.artifact_revision_id,
            member_path=source.item_content.member_path,
            sha256=source.item_content.sha256,
            media_type=source.item_content.media_type,
            schema_ref=source.item_content.schema_ref,
            max_bytes=16 * 1024 * 1024,
        )

    def _resolve_authorities(
        self,
        session: Session,
        authorities: tuple[EditorialAuthorityPointer, ...],
    ) -> None:
        bundle = session.scalar(
            select(ExecutionBundleRecord).where(
                ExecutionBundleRecord.bundle_kind == "REFERENCE",
                ExecutionBundleRecord.bundle_key == REFERENCE_BUNDLE_KEY,
                ExecutionBundleRecord.state == "ACTIVE",
            )
        )
        revision = (
            session.get(ExecutionBundleRevisionRecord, bundle.current_revision_id)
            if bundle is not None and bundle.current_revision_id is not None
            else None
        )
        if (
            bundle is None
            or revision is None
            or revision.bundle_id != bundle.bundle_id
            or revision.bundle_kind != "REFERENCE"
            or revision.state != "RELEASED"
            or compute_control_document_hash(revision.canonical_document, "content_sha256")
            != revision.content_sha256
        ):
            self._raise(
                "LEGACY_EDITORIAL_AUTHORITY_BUNDLE_STALE",
                "content-team reference bundle is not released",
            )
        manifest = ReferenceBundleManifest.model_validate(revision.canonical_document)
        entries = {entry.reference_key: entry for entry in manifest.entries}
        for authority in authorities:
            expected_key, expected_revision = AUTHORITY_BINDINGS[authority.authority_kind]
            entry = entries.get(expected_key)
            pointer = authority.artifact_member
            if (
                authority.reference_key != expected_key
                or authority.reference_revision != expected_revision
                or entry is None
                or entry.artifact.artifact_id != pointer.artifact_id
                or entry.artifact.artifact_revision_id != pointer.artifact_revision_id
                or entry.artifact.logical_name != pointer.member_path
                or entry.artifact.schema_ref != pointer.schema_ref
                or entry.artifact.media_type != pointer.media_type
                or entry.artifact.sha256 != pointer.sha256
            ):
                self._raise(
                    "LEGACY_EDITORIAL_AUTHORITY_STALE",
                    "content-team editorial authority pointer is stale",
                )
            self.artifacts.verify_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                media_type=pointer.media_type,
                schema_ref=pointer.schema_ref,
                max_bytes=MAX_AUTHORITY_BYTES,
            )

    @staticmethod
    def _validate_predecessor(
        request: LegacyItemEditorialCompatibilityRequest,
        latest: LegacyItemEditorialCompatibilityRunRecord | None,
    ) -> None:
        predecessor_id = request.predecessor_compatibility_run_id
        if latest is None:
            if predecessor_id is not None:
                raise LegacyItemEditorialCompatibilityError(
                    "LEGACY_EDITORIAL_PREDECESSOR_INVALID",
                    "editorial compatibility predecessor does not exist",
                )
            return
        if latest.state in ACTIVE_STATES or latest.state in {"OPEN", "CLOSED"}:
            if predecessor_id is not None or latest.state in ACTIVE_STATES:
                raise LegacyItemEditorialCompatibilityError(
                    "LEGACY_EDITORIAL_ATTEMPT_EXISTS",
                    "editorial compatibility tuple already has current work or a result",
                )
            return
        if (
            latest.state != "FAILED"
            or predecessor_id != latest.compatibility_run_id
            or latest.compatibility_key_sha256
            != LegacyItemEditorialCompatibilityService.compatibility_key(request)
        ):
            raise LegacyItemEditorialCompatibilityError(
                "LEGACY_EDITORIAL_PREDECESSOR_INVALID",
                "reviewed retry must name the latest failed exact-tuple run",
            )

    @staticmethod
    def _require_proposal(
        request: LegacyItemEditorialCompatibilityRequest,
        proposal: LegacyItemEditorialCompatibilityProposal,
    ) -> None:
        if (
            proposal.compatibility_request_id != request.compatibility_request_id
            or proposal.request_sha256 != request.request_sha256
            or proposal.source != request.source
            or proposal.authorities != request.authorities
            or proposal.renderer_profile != request.renderer_profile
        ):
            raise LegacyItemEditorialCompatibilityError(
                "LEGACY_EDITORIAL_PROPOSAL_MISMATCH",
                "editorial proposal does not bind the exact request",
            )

    def _resolve_renderer_profile(self, profile: HwpQuestionEditorProfilePointer) -> None:
        self.artifacts.verify_member(
            artifact_id=profile.artifact_id,
            revision_id=profile.artifact_revision_id,
            member_path=profile.archive_member_path,
            sha256=profile.archive_sha256,
            media_type=profile.archive_media_type,
            schema_ref=profile.archive_schema_ref,
            max_bytes=64 * 1024 * 1024,
        )

    @staticmethod
    def _require_idempotency_key(value: str) -> None:
        if len(value) < 16 or len(value) > 128 or re.fullmatch(r"[\x21-\x7e]+", value) is None:
            raise LegacyItemEditorialCompatibilityError(
                "LEGACY_EDITORIAL_IDEMPOTENCY_INVALID",
                "editorial compatibility idempotency key is invalid",
            )

    @staticmethod
    def _run_id(compatibility_request_id: str) -> str:
        digest = content_sha256(
            {"compatibility_request_id": compatibility_request_id}
        ).removeprefix("sha256:")
        return f"editorialcompatrun_{digest[:32]}"

    @staticmethod
    def _result_id(compatibility_run_id: str) -> str:
        digest = content_sha256({"compatibility_run_id": compatibility_run_id}).removeprefix(
            "sha256:"
        )
        return f"editorialcompatresult_{digest[:32]}"

    @staticmethod
    def _locked_run(
        session: Session, compatibility_run_id: str
    ) -> LegacyItemEditorialCompatibilityRunRecord:
        run = session.scalar(
            select(LegacyItemEditorialCompatibilityRunRecord)
            .where(
                LegacyItemEditorialCompatibilityRunRecord.compatibility_run_id
                == compatibility_run_id
            )
            .with_for_update()
        )
        if run is None:
            raise LegacyItemEditorialCompatibilityError(
                "LEGACY_EDITORIAL_RUN_MISSING",
                "editorial compatibility run does not exist",
            )
        return run

    @staticmethod
    def _append_event(
        session: Session,
        run: LegacyItemEditorialCompatibilityRunRecord,
        *,
        event_type: str,
        prior_state: str | None,
        actor_type: str,
        actor_id: str,
        payload: dict[str, object],
    ) -> None:
        sequence = (
            session.scalar(
                select(
                    func.coalesce(
                        func.max(LegacyItemEditorialCompatibilityEventRecord.sequence),
                        0,
                    )
                ).where(
                    LegacyItemEditorialCompatibilityEventRecord.compatibility_run_id
                    == run.compatibility_run_id
                )
            )
            or 0
        ) + 1
        session.add(
            LegacyItemEditorialCompatibilityEventRecord(
                compatibility_run_id=run.compatibility_run_id,
                sequence=sequence,
                event_type=event_type,
                prior_state=prior_state,
                new_state=run.state,
                actor_type=actor_type,
                actor_id=actor_id,
                payload=payload,
            )
        )

    def _transition(
        self,
        session: Session,
        run: LegacyItemEditorialCompatibilityRunRecord,
        target: str,
        event_type: str,
        *,
        actor_type: str,
        actor_id: str,
        payload: dict[str, object],
    ) -> None:
        prior = run.state
        if target not in TRANSITIONS[prior]:
            self._raise(
                "LEGACY_EDITORIAL_TRANSITION_INVALID",
                "editorial compatibility state transition is invalid",
            )
        run.state = target
        run.lock_version += 1
        self._append_event(
            session,
            run,
            event_type=event_type,
            prior_state=prior,
            actor_type=actor_type,
            actor_id=actor_id,
            payload=payload,
        )

    @staticmethod
    def _projection(
        run: LegacyItemEditorialCompatibilityRunRecord,
    ) -> LegacyItemEditorialCompatibilityView:
        return LegacyItemEditorialCompatibilityView(
            compatibility_run_id=run.compatibility_run_id,
            predecessor_compatibility_run_id=run.predecessor_compatibility_run_id,
            compatibility_request_id=run.compatibility_request_id,
            request_sha256=run.request_sha256,
            compatibility_key_sha256=run.compatibility_key_sha256,
            workflow_id=run.workflow_id,
            plan_id=run.plan_id,
            platform_job_id=run.platform_job_id,
            state=run.state,
            result_status=run.result_status,
            result_artifact_id=run.result_artifact_id,
            result_artifact_revision_id=run.result_artifact_revision_id,
            result_sha256=run.result_sha256,
            lossless_projection=run.lossless_projection,
            issue_count=run.issue_count,
            error_code=run.error_code,
            created_at=run.created_at,
            completed_at=run.completed_at,
        )

    @staticmethod
    def _raise(code: str, message: str) -> NoReturn:
        raise LegacyItemEditorialCompatibilityError(code, message)
