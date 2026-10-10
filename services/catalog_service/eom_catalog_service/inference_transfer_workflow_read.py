"""Catalog-owned current authorization and exact comparison-result resolution.

The fixed API peer supplies the actual operator. A Workflow ID or its generic
read permission is not authority to read the underlying sources. The stored
result JSON is metadata: only the official Artifact loader materializes the
canonical structured member. This optional leaf makes no writes or latest
lookups and does not confer educational approval on machine hypotheses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

from eom_catalog_contracts.inference_transfer_invocation import (
    MAX_TRANSFER_WORKFLOW_READ_BYTES,
    TRANSFER_RESULT_MEMBER_SCHEMA,
    InferenceTransferWorkflowReadRequest,
    InferenceTransferWorkflowReadResult,
    parse_workflow_read_request,
    parse_workflow_read_result,
    validate_workflow_read_result_context,
)
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    PairComparisonResult,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_identity_service.repository import effective_permissions
from eom_operator_identity import PermissionKey
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.inference_transfer_resolution import read_inference_transfer_execution_plan
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.models import ArtifactManifest
from eom_protocol.validation import validate_message
from eom_workflow import AgentStep, compile_definition_data
from eom_workflow.inference_transfer import (
    TRANSFER_PAIR_PROTOCOL,
    TRANSFER_PAIR_RESULT_SCHEMA,
    TRANSFER_PAIR_WORKFLOW_KEY,
    TRANSFER_PAIR_WORKFLOW_VERSION,
    validate_inference_transfer_worker_result,
)
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequest
from eom_workflow.models import ArtifactPointer, InferenceTransferPairRoleResult, RoleWorkerInput
from eom_workflow.schemas import (
    validate_inference_transfer_workflow_request,
    validate_role_input,
    validate_role_result,
)
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import inference_transfer_business_fingerprint
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.inference_transfer_catalog_adapter import (
    CatalogInferenceTransferSourceAdapter,
)
from eom_catalog_service.inference_transfer_service import (
    InferenceTransferSearchCommand,
    InferenceTransferServiceError,
)
from eom_catalog_service.inference_transfer_worker_preparation import (
    prepare_inference_transfer_worker_comparison,
)
from eom_catalog_service.settings import CatalogSettings


class ComparisonPairSourcePort(Protocol):
    def authorize_pair(
        self,
        command: InferenceTransferSearchCommand,
        left: InferenceTransferProfile,
        right: InferenceTransferProfile,
    ) -> None: ...


class ComparisonResultArtifactPort(Protocol):
    def load_json_revision(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        content_hash: str,
        max_bytes: int,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class _ComparisonReadContext:
    workflow_id: str
    workflow_state: Literal["REQUESTED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
    resource_version: int
    request: InferenceTransferWorkflowRequest
    result_member: ArtifactMemberPointer | None = None
    worker_input: RoleWorkerInput | None = None
    content_bytes: int | None = None
    manifest_sha256: str | None = None


class CatalogInferenceTransferWorkflowReadService:
    """Read-only, own-creator comparison use case on existing indexed relations."""

    def __init__(
        self,
        engine: Engine,
        settings: CatalogSettings | None = None,
        *,
        source: ComparisonPairSourcePort | None = None,
        artifacts: ComparisonResultArtifactPort | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.source = source or CatalogInferenceTransferSourceAdapter(engine, settings)
        self.artifacts = artifacts or CatalogArtifactService(engine, settings)

    def read(
        self, actor_id: str, request: InferenceTransferWorkflowReadRequest
    ) -> InferenceTransferWorkflowReadResult:
        try:
            request = parse_workflow_read_request(request.model_dump(mode="json"))
        except (ValueError, SchemaError) as exc:
            raise InferenceTransferServiceError(
                "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID"
            ) from exc
        try:
            if re.fullmatch(r"operator_[0-9a-f]{32}", actor_id) is None:
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_FORBIDDEN")
            context = self._read_context(actor_id, request.workflow_id)
            self._authorize_sources(actor_id, context.request)
            result = None
            if context.workflow_state == "COMPLETED" and request.mode == "CANONICAL_RESULT":
                result = self._load_result(context)
            # Observe the exact lineage/lifecycle again after materialization.
            # Neither a successful first read nor the initial permission digest
            # is a reusable authority token when rights or sources are revoked.
            if self._read_context(actor_id, request.workflow_id) != context:
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_WORKFLOW_CHANGED")
            self._authorize_sources(actor_id, context.request)
            graph = context.request.left_profile.source_basis.graph_snapshot
            body = {
                "schema_version": "inference-transfer-workflow-read-result/1.0",
                "workflow_id": context.workflow_id,
                "workflow_state": context.workflow_state,
                "resource_version": context.resource_version,
                "comparison": context.request.comparison.model_dump(mode="json"),
                "graph_snapshot": graph.model_dump(mode="json"),
                "access_policy_revision_id": context.request.access_policy_revision_id,
                "access_policy_sha256": context.request.access_policy_sha256,
                "result_state": (
                    "PENDING"
                    if context.workflow_state in {"REQUESTED", "RUNNING"}
                    else "NO_RESULT"
                    if context.workflow_state in {"FAILED", "CANCELLED"}
                    else "POINTER_ONLY"
                    if result is None
                    else "MEMBER_VERIFIED"
                ),
                "result_artifact": (
                    None
                    if context.result_member is None
                    else context.result_member.model_dump(mode="json")
                ),
                "result": None if result is None else result.model_dump(mode="json"),
                # Technical histories remain in their original owner. Do not
                # echo arbitrary persisted failure text or code into this read.
                "failure_code": (
                    "INFERENCE_TRANSFER_EXECUTION_FAILED"
                    if context.workflow_state == "FAILED"
                    else "INFERENCE_TRANSFER_EXECUTION_CANCELLED"
                    if context.workflow_state == "CANCELLED"
                    else None
                ),
            }
            response = parse_workflow_read_result(body | {"result_sha256": content_sha256(body)})
            validate_workflow_read_result_context(request, response)
            return response
        except InferenceTransferServiceError:
            raise
        except (ValueError, SchemaError) as exc:
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_RESULT_INVALID") from exc

    def _authorize_sources(self, actor_id: str, request: InferenceTransferWorkflowRequest) -> None:
        command = InferenceTransferSearchCommand(
            actor_id=actor_id,
            graph_snapshot=request.left_profile.source_basis.graph_snapshot,
            access_policy_revision_id=request.access_policy_revision_id,
            access_policy_sha256=request.access_policy_sha256,
            query_item_revision_id=request.left_profile.source_basis.source.item_revision_id,
            source_classes=cast(
                tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...],
                tuple(
                    sorted(
                        {
                            request.left_profile.source_basis.source.source_class,
                            request.right_profile.source_basis.source.source_class,
                        }
                    )
                ),
            ),
            maximum_candidates=2,
            top_k=2,
        )
        self.source.authorize_pair(command, request.left_profile, request.right_profile)

    def _read_context(self, actor_id: str, workflow_id: str) -> _ComparisonReadContext:
        with self.sessions() as session:
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            if PermissionKey.WORKFLOW_READ not in effective_permissions(session, actor_id):
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_FORBIDDEN")
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            if workflow is None:
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_WORKFLOW_NOT_FOUND")
            if workflow.created_actor_type != "human" or workflow.created_actor_id != actor_id:
                raise InferenceTransferServiceError("INFERENCE_TRANSFER_FORBIDDEN")
            request = validate_inference_transfer_workflow_request(workflow.initial_request)
            _validate_workflow(session, workflow, request)
            state = cast(
                Literal["REQUESTED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"],
                workflow.state,
            )
            context = _ComparisonReadContext(workflow_id, state, workflow.lock_version, request)
            if state != "COMPLETED":
                if workflow.runtime_context.get("execution_plan") is not None:
                    _validate_execution_plan(session, workflow, None, request)
                return context
            return _completed_context(session, workflow, context)

    def _load_result(self, context: _ComparisonReadContext) -> PairComparisonResult:
        member, worker = context.result_member, context.worker_input
        if member is None or worker is None:
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_RESULT_INVALID")
        document = self.artifacts.load_json_revision(
            artifact_id=member.artifact_id,
            revision_id=member.artifact_revision_id,
            content_hash=member.sha256,
            max_bytes=MAX_TRANSFER_WORKFLOW_READ_BYTES,
        )
        encoded = canonical_json_bytes(document)
        if len(encoded) != context.content_bytes or content_sha256(document) != member.sha256:
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_RESULT_INVALID")
        role_result = validate_role_result(document, "support", TRANSFER_PAIR_RESULT_SCHEMA)
        if not isinstance(role_result, InferenceTransferPairRoleResult) or (
            role_result.job_id != worker.job_id
            or role_result.workflow_id != worker.workflow_id
            or role_result.step_run_id != worker.step_run_id
            or role_result.artifact != worker.artifact
        ):
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_RESULT_INVALID")
        validate_inference_transfer_worker_result(
            context.request.worker_request(), role_result.output
        )
        return role_result.output


def _validate_workflow(
    session: Session,
    workflow: WorkflowInstanceRecord,
    request: InferenceTransferWorkflowRequest,
) -> None:
    definition = session.get(WorkflowDefinitionRecord, workflow.definition_id)
    if definition is None:
        raise InferenceTransferServiceError("INFERENCE_TRANSFER_RESULT_INVALID")
    compiled = compile_definition_data(
        definition.canonical_definition, definition.source_path, {"support"}
    )
    step = compiled.steps_by_key.get("compare_pair")
    expected_request_hash = inference_transfer_business_fingerprint(
        definition, request, actor_type="human", actor_id=workflow.created_actor_id
    )
    if (
        workflow.definition_key != TRANSFER_PAIR_WORKFLOW_KEY
        or workflow.definition_version != TRANSFER_PAIR_WORKFLOW_VERSION
        or workflow.protocol_version != "1.0.1"
        or workflow.role_schema_version != TRANSFER_PAIR_PROTOCOL
        or definition.definition_key != workflow.definition_key
        or definition.definition_version != workflow.definition_version
        or compiled.definition.definition_key != workflow.definition_key
        or compiled.definition.definition_version != workflow.definition_version
        or compiled.sha256 != workflow.definition_hash
        or definition.definition_hash != workflow.definition_hash
        or workflow.request_payload != request.model_dump(mode="json")
        or workflow.request_hash != expected_request_hash
        or not isinstance(step, AgentStep)
        or step.worker_role != "support"
        or step.result_schema != TRANSFER_PAIR_RESULT_SCHEMA
        or compiled.definition.limits.max_step_attempts != 1
        or compiled.definition.limits.max_rework_cycles != 0
        or workflow.state not in {"REQUESTED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"}
        or workflow.lock_version < 1
        or workflow.rework_cycle_count != 0
        or (
            workflow.state in {"REQUESTED", "RUNNING"}
            and (
                workflow.stage != "INFERENCE_TRANSFER"
                or workflow.current_step_key != "compare_pair"
            )
        )
        or (
            workflow.state == "COMPLETED"
            and (workflow.stage != "COMPLETED" or workflow.current_step_key != "complete")
        )
    ):
        raise InferenceTransferServiceError("INFERENCE_TRANSFER_RESULT_INVALID")


def _completed_context(
    session: Session,
    workflow: WorkflowInstanceRecord,
    context: _ComparisonReadContext,
) -> _ComparisonReadContext:
    # This released definition allows one attempt. Never choose a guessed latest
    # result if the exact step history has been changed or duplicated.
    steps = tuple(
        session.scalars(
            select(WorkflowStepRunRecord)
            .where(
                WorkflowStepRunRecord.workflow_id == workflow.workflow_id,
                WorkflowStepRunRecord.step_key == "compare_pair",
            )
            .limit(2)
        )
    )
    if len(steps) != 1:
        raise InferenceTransferServiceError("INFERENCE_TRANSFER_RESULT_INVALID")
    step = steps[0]
    pointer = ArtifactPointer.model_validate(step.output_pointer_manifest)
    if (
        step.attempt != 1
        or step.step_type != "agent"
        or step.worker_role != "support"
        or step.result_schema != TRANSFER_PAIR_RESULT_SCHEMA
        or step.state != "SUCCEEDED"
        or step.superseded_by_step_run_id is not None
        or step.platform_job_id != pointer.job_id
        or pointer.step_key != step.step_key
        or pointer.attempt != step.attempt
        or pointer.result_schema != step.result_schema
        or step.input_pointer_manifest.get("upstream_artifacts") != []
    ):
        raise InferenceTransferServiceError("INFERENCE_TRANSFER_RESULT_INVALID")
    final = workflow.runtime_context.get("final_pointer_manifest")
    pointer_document = pointer.model_dump(mode="json")
    if not isinstance(final, dict) or (
        final.get("workflow_id") != workflow.workflow_id
        or final.get("definition_hash") != workflow.definition_hash
        or final.get("artifact_pointers") != [pointer_document]
        or final.get("comparison_result") != pointer_document
        or final.get("registration") is not None
        or final.get("analysis_proposal") is not None
        or workflow.runtime_context.get("artifact_pointers") != [pointer_document]
    ):
        raise InferenceTransferServiceError("INFERENCE_TRANSFER_RESULT_INVALID")
    job = session.get(JobRecord, pointer.job_id)
    if job is None:
        raise InferenceTransferServiceError("INFERENCE_TRANSFER_RESULT_INVALID")
    worker = RoleWorkerInput.model_validate(job.request)
    validate_role_input(job.request, "support", TRANSFER_PAIR_PROTOCOL)
    if (
        job.status != "SUCCEEDED"
        or job.task_type != "workflow_support"
        or job.protocol_version != TRANSFER_PAIR_PROTOCOL
        or job.job_id != worker.job_id
        or job.job_id != pointer.job_id
        or job.logical_artifact_id != pointer.logical_artifact_id
        or job.revision_id != pointer.revision_id
        or job.completed_at is None
        or worker.workflow_id != workflow.workflow_id
        or worker.step_run_id != step.step_run_id
        or worker.attempt != step.attempt
        or worker.upstream_artifacts
        or worker.request != context.request.worker_request()
        or worker.artifact.logical_artifact_id != pointer.logical_artifact_id
        or worker.artifact.revision_id != pointer.revision_id
        or job.request_hash
        != content_sha256(
            {
                "protocol_version": job.protocol_version,
                "task_type": job.task_type,
                "request": job.request,
            }
        )
    ):
        raise InferenceTransferServiceError("INFERENCE_TRANSFER_RESULT_INVALID")
    _validate_execution_plan(session, workflow, step, context.request)
    artifact = session.get(ArtifactRecord, pointer.logical_artifact_id)
    revision = session.get(ArtifactRevisionRecord, pointer.revision_id)
    if artifact is None or revision is None:
        raise InferenceTransferServiceError("INFERENCE_TRANSFER_RESULT_INVALID")
    validate_message("artifact-manifest", revision.manifest)
    manifest = ArtifactManifest.model_validate(revision.manifest)
    if (
        not artifact.approved
        or not revision.approved
        or artifact.logical_artifact_id != pointer.logical_artifact_id
        or artifact.job_id != pointer.job_id
        or artifact.artifact_type != "workflow_support"
        or revision.revision_id != pointer.revision_id
        or revision.logical_artifact_id != pointer.logical_artifact_id
        or revision.job_id != pointer.job_id
        or revision.content_hash != pointer.content_hash
        or manifest.job_id != pointer.job_id
        or manifest.logical_artifact_id != pointer.logical_artifact_id
        or manifest.revision_id != pointer.revision_id
        or manifest.content_hash != pointer.content_hash
        or manifest.content_bytes != revision.content_bytes
        or manifest.worker_slot != job.worker_slot_id
        or content_sha256(revision.manifest) != revision.manifest_hash
        or not 1 <= revision.content_bytes <= MAX_TRANSFER_WORKFLOW_READ_BYTES
    ):
        raise InferenceTransferServiceError("INFERENCE_TRANSFER_RESULT_INVALID")
    return _ComparisonReadContext(
        context.workflow_id,
        context.workflow_state,
        context.resource_version,
        context.request,
        ArtifactMemberPointer(
            artifact_id=pointer.logical_artifact_id,
            artifact_revision_id=pointer.revision_id,
            member_path="result.json",
            schema_ref=TRANSFER_RESULT_MEMBER_SCHEMA,
            media_type="application/json",
            sha256=pointer.content_hash,
        ),
        worker,
        revision.content_bytes,
        revision.manifest_hash,
    )


def _validate_execution_plan(
    session: Session,
    workflow: WorkflowInstanceRecord,
    step: WorkflowStepRunRecord | None,
    request: InferenceTransferWorkflowRequest,
) -> None:
    prepared = prepare_inference_transfer_worker_comparison(
        request.comparison, left=request.left_profile, right=request.right_profile
    )
    prompt_pin = {
        "prompt_version": prepared.prompt_version,
        "core_prompt_sha256": prepared.core_prompt_sha256,
        "prompt_sha256": prepared.prompt_sha256,
        "workflow_request_sha256": request.request_sha256,
    }
    stored_pin = workflow.runtime_context.get("execution_plan")
    if (
        not isinstance(stored_pin, dict)
        or set(stored_pin) != {"plan_id", "plan_sha256", "preset_id", "preset_revision_id"}
        or not isinstance(stored_pin.get("plan_id"), str)
        or (step is not None and step.input_pointer_manifest.get("transfer_prompt") != prompt_pin)
    ):
        raise InferenceTransferServiceError("INFERENCE_TRANSFER_RESULT_INVALID")
    try:
        plan = read_inference_transfer_execution_plan(
            session,
            plan_id=stored_pin["plan_id"],
            workflow_id=workflow.workflow_id,
            workflow_definition_sha256=workflow.definition_hash,
            workflow_request=request,
            core_prompt_sha256=prepared.core_prompt_sha256,
            prompt_sha256=prepared.prompt_sha256,
        )
    except ControlPlaneError as exc:
        raise InferenceTransferServiceError("INFERENCE_TRANSFER_RESULT_INVALID") from exc
    if stored_pin != {
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "preset_id": plan.preset_id,
        "preset_revision_id": plan.preset_revision_id,
    }:
        raise InferenceTransferServiceError("INFERENCE_TRANSFER_RESULT_INVALID")
