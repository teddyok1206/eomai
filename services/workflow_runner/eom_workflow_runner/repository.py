"""Transactional persistence operations for definitions, commands, and audit history."""

from __future__ import annotations

import secrets
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from eom_identifiers import content_sha256
from eom_workflow import (
    CompiledWorkflowDefinition,
    ContentTeamItemBriefV4,
    ContentTeamItemBriefV5,
    WorkflowRequest,
    workflow_admission,
    workflow_definition_is_admitted,
)
from eom_workflow.compiler import compile_definition_data
from eom_workflow.definition_execution_protocol import definition_execution_protocol
from eom_workflow.identifiers import (
    new_approval_request_id,
    new_command_id,
    new_definition_id,
    new_step_run_id,
    new_workflow_id,
)
from eom_workflow.inference_transfer import TRANSFER_PAIR_WORKFLOW_KEY
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequest
from eom_workflow.local_embedding_request import (
    LocalEmbeddingExecutableRequest,
    LocalEmbeddingServiceWorkflowRequest,
    LocalEmbeddingWorkflowRequestV11,
    parse_local_embedding_executable_request,
)
from eom_workflow.local_embedding_workflow import (
    LOCAL_EMBEDDING_EXECUTION_PROTOCOL,
    LOCAL_EMBEDDING_WORKFLOW_KEY,
)
from eom_workflow.reference_query_execution import (
    ReferenceQueryWorkflowRequest,
    parse_reference_query_workflow_request,
)
from eom_workflow.reference_query_workflow import (
    REFERENCE_QUERY_EXECUTION_PROTOCOL,
    REFERENCE_QUERY_RESULT_SCHEMA,
    REFERENCE_QUERY_WORKFLOW_KEY,
)
from eom_workflow.schemas import (
    result_schema_protocol,
    validate_inference_transfer_workflow_request,
    validate_inference_transfer_workflow_request_v11,
)
from sqlalchemy import func, not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.inference_transfer_admission import (
    InferenceTransferSubmissionContext,
    admit_inference_transfer_workflow_request,
)
from eom_workflow_runner.local_embedding_admission import (
    LocalEmbeddingOwnerAdmission,
    resolve_local_embedding_submission_controls,
    validate_local_embedding_runner_admission,
)
from eom_workflow_runner.local_embedding_execution_port import LocalEmbeddingNativeExecutor
from eom_workflow_runner.models import (
    ApprovalRequestRecord,
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.reference_query_admission import (
    ReferenceQueryOwnerAdmission,
    resolve_reference_query_submission_controls,
    validate_reference_query_runner_admission,
)
from eom_workflow_runner.reference_query_execution_port import ReferenceQueryNativeExecutor
from eom_workflow_runner.state_machine import (
    ACTIVE_WORKFLOW_STATES,
    ApprovalState,
    CommandState,
    StepState,
    WorkflowStage,
    WorkflowState,
    record_initial_workflow_event,
    transition_command,
    transition_step,
)


class CommandType(StrEnum):
    START_WORKFLOW = "START_WORKFLOW"
    ADVANCE_WORKFLOW = "ADVANCE_WORKFLOW"
    APPROVE_WORKFLOW = "APPROVE_WORKFLOW"
    REQUEST_REWORK = "REQUEST_REWORK"
    CANCEL_WORKFLOW = "CANCEL_WORKFLOW"
    RETRY_STEP = "RETRY_STEP"
    RECONCILE_WORKFLOW = "RECONCILE_WORKFLOW"


@dataclass(frozen=True)
class WorkflowDefinitionAdmissionStatus:
    definition_id: str
    definition_key: str
    definition_version: str
    role_protocol_version: str | None
    role_protocol_error: str | None
    active: bool
    admitted: bool

    @property
    def accepts_new_work(self) -> bool:
        admission = workflow_admission(self.definition_key, self.definition_version)
        return (
            self.active
            and admission is not None
            and self.role_protocol_version == admission.role_protocol_version
        )


@dataclass(frozen=True, slots=True)
class CommandLeaseIdentity:
    """Immutable fencing identity for one command acquisition."""

    command_id: str
    runner_id: str
    lease_token: str
    lease_generation: int


class CommandExecutionFamily(StrEnum):
    ROLE = "ROLE"
    LOCAL_EMBEDDING = "LOCAL_EMBEDDING"
    REFERENCE_QUERY = "REFERENCE_QUERY"


@dataclass(frozen=True, slots=True)
class CommandCandidate:
    """Read-only exact queue header, not a lease or cached authority decision."""

    family: CommandExecutionFamily
    command_id: str
    workflow_id: str
    command_type: str
    command_request_hash: str
    command_contents_hash: str
    command_state: str
    lease_generation: int
    attempts: int
    available_at: datetime
    lease_expires_at: datetime | None
    created_at: datetime
    definition_id: str
    definition_hash: str
    workflow_request_hash: str
    workflow_contents_hash: str
    current_step_key: str
    workflow_state: str
    workflow_lock_version: int
    native_request: LocalEmbeddingExecutableRequest | ReferenceQueryWorkflowRequest | None


def _native_workflow_filter() -> ColumnElement[bool]:
    """Total routing guard, including malformed native history; never authorization."""
    request_versions = (
        "local-embedding-workflow-request/1.0",
        "local-embedding-workflow-request/1.1",
        "reference-query-workflow-request/1.0",
    )
    native_keys = (LOCAL_EMBEDDING_WORKFLOW_KEY, REFERENCE_QUERY_WORKFLOW_KEY)
    native_protocols = (LOCAL_EMBEDDING_EXECUTION_PROTOCOL, REFERENCE_QUERY_EXECUTION_PROTOCOL)
    native_purposes = ("LOCAL_EMBEDDING", "REFERENCE_QUERY")
    definition = select(WorkflowDefinitionRecord.definition_id).where(
        WorkflowDefinitionRecord.definition_id == WorkflowInstanceRecord.definition_id,
        or_(
            WorkflowDefinitionRecord.definition_key.in_(native_keys),
            WorkflowDefinitionRecord.canonical_definition["definition_key"]
            .as_string()
            .in_(native_keys),
        ),
    )
    step = select(WorkflowStepRunRecord.step_run_id).where(
        WorkflowStepRunRecord.workflow_id == WorkflowInstanceRecord.workflow_id,
        or_(
            WorkflowStepRunRecord.step_type == "application",
            WorkflowStepRunRecord.step_key == "encode_reference_query",
            WorkflowStepRunRecord.result_schema.in_(
                ("incremental-embedding-result@1.0", REFERENCE_QUERY_RESULT_SCHEMA)
            ),
        ),
    )
    return func.coalesce(
        or_(
            WorkflowInstanceRecord.definition_key.in_(native_keys),
            WorkflowInstanceRecord.role_schema_version.in_(native_protocols),
            WorkflowInstanceRecord.stage == WorkflowStage.LOCAL_EMBEDDING.value,
            WorkflowInstanceRecord.initial_request["schema_version"]
            .as_string()
            .in_(request_versions),
            WorkflowInstanceRecord.request_payload["schema_version"]
            .as_string()
            .in_(request_versions),
            WorkflowInstanceRecord.initial_request["purpose"].as_string().in_(native_purposes),
            WorkflowInstanceRecord.request_payload["purpose"].as_string().in_(native_purposes),
            definition.exists(),
            step.exists(),
        ),
        False,
    )


def workflow_requires_local_embedding(session: Session, *, workflow_id: str) -> bool:
    """Read the SAME total routing predicate at one PK, including related native markers."""
    native = session.scalar(
        select(_native_workflow_filter()).where(WorkflowInstanceRecord.workflow_id == workflow_id)
    )
    if native is None:
        raise WorkflowError(WorkflowErrorCode.WORKFLOW_NOT_FOUND, "workflow routing target missing")
    if type(native) is not bool:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID, "workflow routing projection invalid"
        )
    return native


def _query_workflow_filter() -> ColumnElement[bool]:
    """Query quarantine wins over contradictory INDEX markers; never a grant."""
    definition = select(WorkflowDefinitionRecord.definition_id).where(
        WorkflowDefinitionRecord.definition_id == WorkflowInstanceRecord.definition_id,
        or_(
            WorkflowDefinitionRecord.definition_key == REFERENCE_QUERY_WORKFLOW_KEY,
            WorkflowDefinitionRecord.canonical_definition["definition_key"].as_string()
            == REFERENCE_QUERY_WORKFLOW_KEY,
        ),
    )
    step = select(WorkflowStepRunRecord.step_run_id).where(
        WorkflowStepRunRecord.workflow_id == WorkflowInstanceRecord.workflow_id,
        or_(
            WorkflowStepRunRecord.step_key == "encode_reference_query",
            WorkflowStepRunRecord.result_schema == REFERENCE_QUERY_RESULT_SCHEMA,
        ),
    )
    return func.coalesce(
        or_(
            WorkflowInstanceRecord.definition_key == REFERENCE_QUERY_WORKFLOW_KEY,
            WorkflowInstanceRecord.role_schema_version == REFERENCE_QUERY_EXECUTION_PROTOCOL,
            WorkflowInstanceRecord.initial_request["schema_version"].as_string()
            == "reference-query-workflow-request/1.0",
            WorkflowInstanceRecord.request_payload["schema_version"].as_string()
            == "reference-query-workflow-request/1.0",
            WorkflowInstanceRecord.initial_request["purpose"].as_string() == "REFERENCE_QUERY",
            WorkflowInstanceRecord.request_payload["purpose"].as_string() == "REFERENCE_QUERY",
            definition.exists(),
            step.exists(),
        ),
        False,
    )


def _execution_family_filter(family: CommandExecutionFamily) -> ColumnElement[bool]:
    native, query = _native_workflow_filter(), _query_workflow_filter()
    if family is CommandExecutionFamily.ROLE:
        return not_(native)
    if family is CommandExecutionFamily.REFERENCE_QUERY:
        return native & query
    if family is CommandExecutionFamily.LOCAL_EMBEDDING:
        return native & not_(query)
    raise ValueError("WORKFLOW_COMMAND_EXECUTION_FAMILY_INVALID")


def _command_candidate(
    command: WorkflowCommandRecord,
    workflow: WorkflowInstanceRecord,
    family: CommandExecutionFamily,
) -> CommandCandidate:
    native_request: LocalEmbeddingExecutableRequest | ReferenceQueryWorkflowRequest | None = None
    query_marked = (
        family is CommandExecutionFamily.REFERENCE_QUERY
        or workflow.definition_key == REFERENCE_QUERY_WORKFLOW_KEY
        or workflow.role_schema_version == REFERENCE_QUERY_EXECUTION_PROTOCOL
        or any(
            isinstance(document, dict)
            and (
                document.get("schema_version") == "reference-query-workflow-request/1.0"
                or document.get("purpose") == "REFERENCE_QUERY"
            )
            for document in (workflow.initial_request, workflow.request_payload)
        )
    )
    if family is not CommandExecutionFamily.ROLE:
        # Invalid native metadata remains native/unavailable, never a role fallback.
        with suppress(ValueError):
            native_request = (
                parse_reference_query_workflow_request(workflow.initial_request)
                if query_marked
                else load_persisted_local_embedding_workflow_request(workflow.initial_request)
            )
    return CommandCandidate(
        family=family,
        command_id=command.command_id,
        workflow_id=workflow.workflow_id,
        command_type=command.command_type,
        command_request_hash=command.request_hash,
        command_contents_hash=content_sha256(
            {
                "workflow_id": command.workflow_id,
                "command_type": command.command_type,
                "payload": command.payload,
                "actor_type": command.actor_type,
                "actor_id": command.actor_id,
                "source": command.source,
            }
        ),
        command_state=command.state,
        lease_generation=command.lease_generation,
        attempts=command.attempts,
        available_at=command.available_at,
        lease_expires_at=command.lease_expires_at,
        created_at=command.created_at,
        definition_id=workflow.definition_id,
        definition_hash=workflow.definition_hash,
        workflow_request_hash=workflow.request_hash,
        workflow_contents_hash=content_sha256(
            {
                "definition_key": workflow.definition_key,
                "definition_version": workflow.definition_version,
                "role_schema_version": workflow.role_schema_version,
                "stage": workflow.stage,
                "initial_request": workflow.initial_request,
                "request_payload": workflow.request_payload,
            }
        ),
        current_step_key=workflow.current_step_key,
        workflow_state=workflow.state,
        workflow_lock_version=workflow.lock_version,
        native_request=native_request,
    )


def _compiled_role_protocol(compiled: CompiledWorkflowDefinition) -> str:
    try:
        return definition_execution_protocol(compiled.definition)
    except ValueError as exc:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID,
            "workflow definition has inconsistent role protocol versions",
        ) from exc


def _assert_admitted_protocol(compiled: CompiledWorkflowDefinition) -> None:
    definition = compiled.definition
    admission = workflow_admission(definition.definition_key, definition.definition_version)
    if admission is None:
        return
    if _compiled_role_protocol(compiled) != admission.role_protocol_version:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID,
            "admitted workflow definition has an unexpected role protocol version",
        )


def import_workflow_definition(
    session: Session, compiled: CompiledWorkflowDefinition
) -> tuple[WorkflowDefinitionRecord, bool]:
    definition = compiled.definition
    _assert_admitted_protocol(compiled)
    admitted = workflow_definition_is_admitted(
        definition.definition_key,
        definition.definition_version,
    )
    existing = session.scalar(
        select(WorkflowDefinitionRecord).where(
            WorkflowDefinitionRecord.definition_key == definition.definition_key,
            WorkflowDefinitionRecord.definition_version == definition.definition_version,
        )
    )
    if existing is not None:
        if existing.definition_hash != compiled.sha256:
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_DEFINITION_CONFLICT,
                "definition key and version already exist with a different hash",
            )
        return existing, False
    record = WorkflowDefinitionRecord(
        definition_id=new_definition_id(),
        definition_key=definition.definition_key,
        definition_version=definition.definition_version,
        schema_version=definition.schema_version,
        canonical_definition=compiled.as_dict(),
        definition_hash=compiled.sha256,
        active=admitted,
        source_path=compiled.source_path,
    )
    session.add(record)
    session.flush()
    return record, True


def workflow_definition_admission_statuses(
    session: Session,
) -> tuple[WorkflowDefinitionAdmissionStatus, ...]:
    records = tuple(
        session.scalars(
            select(WorkflowDefinitionRecord).order_by(
                WorkflowDefinitionRecord.definition_key,
                WorkflowDefinitionRecord.definition_version,
            )
        )
    )
    return _workflow_definition_admission_statuses(records)


def _stored_role_protocol(record: WorkflowDefinitionRecord) -> str:
    if record.definition_key in {LOCAL_EMBEDDING_WORKFLOW_KEY, REFERENCE_QUERY_WORKFLOW_KEY}:
        try:
            compiled = compile_definition_data(
                record.canonical_definition, record.source_path, set()
            )
            if (
                compiled.definition.definition_key != record.definition_key
                or compiled.definition.definition_version != record.definition_version
                or compiled.definition.schema_version != record.schema_version
                or compiled.sha256 != record.definition_hash
            ):
                raise ValueError("stored native definition differs")
            return _compiled_role_protocol(compiled)
        except ValueError as exc:
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID,
                "stored native definition execution protocol is invalid",
            ) from exc
    role_protocols = {
        result_schema_protocol(str(step["result_schema"]))
        for step in record.canonical_definition.get("steps", [])
        if isinstance(step, dict)
        and step.get("type") == "agent"
        and isinstance(step.get("result_schema"), str)
    }
    if not role_protocols:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID,
            "stored definition has no role protocol version",
        )
    if len(role_protocols) != 1:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID,
            "stored definition has inconsistent role protocol versions",
        )
    return next(iter(role_protocols))


def admitted_workflow_definition(
    session: Session,
    *,
    definition_key: str,
    definition_version: str,
) -> WorkflowDefinitionRecord | None:
    """Resolve a stored definition only when both snapshot and current policy admit new work."""

    if not workflow_definition_is_admitted(definition_key, definition_version):
        return None
    record = session.scalar(
        select(WorkflowDefinitionRecord).where(
            WorkflowDefinitionRecord.definition_key == definition_key,
            WorkflowDefinitionRecord.definition_version == definition_version,
            WorkflowDefinitionRecord.active.is_(True),
        )
    )
    if record is None:
        return None
    admission = workflow_admission(definition_key, definition_version)
    if admission is None:  # guarded above; retain a fail-closed type boundary.
        return None
    if _stored_role_protocol(record) != admission.role_protocol_version:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID,
            "stored admitted definition has an unexpected role protocol version",
        )
    return record


def _workflow_definition_admission_statuses(
    records: tuple[WorkflowDefinitionRecord, ...],
) -> tuple[WorkflowDefinitionAdmissionStatus, ...]:
    values: list[WorkflowDefinitionAdmissionStatus] = []
    for record in records:
        admitted = workflow_definition_is_admitted(
            record.definition_key,
            record.definition_version,
        )
        try:
            role_protocol_version = _stored_role_protocol(record)
            role_protocol_error = None
        except WorkflowError as exc:
            # Immutable historical residue can predate the single-protocol invariant. It is still
            # audit history, but only an inactive identity outside the current policy may be
            # represented as invalid. Every active or admitted definition retains the strict gate.
            if record.active or admitted:
                raise
            role_protocol_version = None
            role_protocol_error = str(exc)
        values.append(
            WorkflowDefinitionAdmissionStatus(
                definition_id=record.definition_id,
                definition_key=record.definition_key,
                definition_version=record.definition_version,
                role_protocol_version=role_protocol_version,
                role_protocol_error=role_protocol_error,
                active=record.active,
                admitted=admitted,
            )
        )
    return tuple(values)


def workflow_business_fingerprint(
    definition: WorkflowDefinitionRecord, request: WorkflowRequest
) -> str:
    return content_sha256(
        {
            "definition_key": definition.definition_key,
            "definition_version": definition.definition_version,
            "definition_hash": definition.definition_hash,
            "request": request.model_dump(mode="json", exclude_none=True),
        }
    )


def workflow_request_storage_document(
    request: (
        WorkflowRequest
        | InferenceTransferWorkflowRequest
        | LocalEmbeddingExecutableRequest
        | ReferenceQueryWorkflowRequest
    ),
) -> dict[str, Any]:
    """Serialize a request without dropping schema-required nullable values."""
    if isinstance(request, ReferenceQueryWorkflowRequest):
        return parse_reference_query_workflow_request(request).model_dump(mode="json")
    if isinstance(
        request, (LocalEmbeddingWorkflowRequestV11, LocalEmbeddingServiceWorkflowRequest)
    ):
        checked = parse_local_embedding_executable_request(request)
        return checked.model_dump(mode="json")
    if isinstance(request, InferenceTransferWorkflowRequest):
        # Profiles' canonical hashes include explicit extraction/source nulls. This
        # bounded application snapshot is not the legacy exclude_none projection.
        return request.model_dump(mode="json")
    document = request.model_dump(mode="json", exclude_none=True)
    if request.analysis_request is not None:
        document["analysis_request"] = request.analysis_request.model_dump(mode="json")
    if request.pdf_document_review_request is not None:
        # The PDF pointer contract requires every page to carry an explicit nullable
        # text-layer member.  The generic exclude_none projection would otherwise
        # erase that field and make the immutable request impossible to reload.
        document["pdf_document_review_request"] = request.pdf_document_review_request.model_dump(
            mode="json"
        )
    if request.paired_document_review_request is not None:
        document["paired_document_review_request"] = (
            request.paired_document_review_request.model_dump(mode="json")
        )
    if isinstance(request.item_brief, ContentTeamItemBriefV4):
        stored_brief = request.item_brief.model_dump(mode="json", exclude_none=True)
        stored_material = dict(stored_brief["material_requirement"])
        stored_material["panel_count"] = request.item_brief.material_requirement.panel_count
        if isinstance(request.item_brief, ContentTeamItemBriefV5):
            stored_material["image_supporting_data"] = (
                request.item_brief.material_requirement.image_supporting_data
            )
        stored_brief["material_requirement"] = stored_material
        document["item_brief"] = stored_brief
    return document


def load_persisted_workflow_request(document: dict[str, Any]) -> WorkflowRequest:
    """Load persisted requests, repairing only the verified legacy null-omission defect."""
    normalized = dict(document)
    analysis = normalized.get("analysis_request")
    if (
        normalized.get("request_name") == "KNOWLEDGE_ANALYSIS_REQUEST"
        and isinstance(analysis, dict)
        and analysis.get("schema_version") == "knowledge-analysis-request/2.0"
    ):
        normalized_analysis = dict(analysis)
        normalized_analysis.setdefault("predecessor_analysis_run_id", None)
        normalized_analysis.setdefault("prior_graph_snapshot", None)
        normalized["analysis_request"] = normalized_analysis
    item_brief = normalized.get("item_brief")
    if isinstance(item_brief, dict) and item_brief.get("schema_version") in {"4.0", "5.0"}:
        material_requirement = item_brief.get("material_requirement")
        if isinstance(material_requirement, dict) and material_requirement.get("form") in {
            "AUTO",
            "TEXT",
            "DATA",
            "INQUIRY",
        }:
            normalized_material_requirement = dict(material_requirement)
            normalized_material_requirement.setdefault("panel_count", None)
            if item_brief.get("schema_version") == "5.0":
                normalized_material_requirement.setdefault("image_supporting_data", None)
            normalized_item_brief = dict(item_brief)
            normalized_item_brief["material_requirement"] = normalized_material_requirement
            normalized["item_brief"] = normalized_item_brief
    pdf_review = normalized.get("pdf_document_review_request")
    if normalized.get("request_name") == "PDF_DOCUMENT_REVIEW_REQUEST" and isinstance(
        pdf_review, dict
    ):
        pdf_document = pdf_review.get("document")
        pages = pdf_document.get("pages") if isinstance(pdf_document, dict) else None
        if isinstance(pdf_document, dict) and isinstance(pages, list):
            normalized_pages: list[object] = []
            for page in pages:
                if isinstance(page, dict):
                    normalized_page = dict(page)
                    normalized_page.setdefault("text_layer", None)
                    normalized_pages.append(normalized_page)
                else:
                    normalized_pages.append(page)
            normalized_document = dict(pdf_document)
            normalized_document["pages"] = normalized_pages
            normalized_pdf_review = dict(pdf_review)
            normalized_pdf_review["document"] = normalized_document
            normalized["pdf_document_review_request"] = normalized_pdf_review
    paired_review = normalized.get("paired_document_review_request")
    if normalized.get("request_name") == "PAIRED_DOCUMENT_REVIEW_REQUEST" and isinstance(
        paired_review, dict
    ):
        documents = paired_review.get("documents")
        if isinstance(documents, list):
            normalized_documents: list[object] = []
            for value in documents:
                paired_document = value.get("document") if isinstance(value, dict) else None
                paired_pages = (
                    paired_document.get("pages") if isinstance(paired_document, dict) else None
                )
                if (
                    isinstance(value, dict)
                    and isinstance(paired_document, dict)
                    and isinstance(paired_pages, list)
                ):
                    paired_normalized_pages: list[object] = []
                    for page in paired_pages:
                        if isinstance(page, dict):
                            normalized_page = dict(page)
                            normalized_page.setdefault("text_layer", None)
                            paired_normalized_pages.append(normalized_page)
                        else:
                            paired_normalized_pages.append(page)
                    normalized_document = dict(paired_document)
                    normalized_document["pages"] = paired_normalized_pages
                    normalized_value = dict(value)
                    normalized_value["document"] = normalized_document
                    normalized_documents.append(normalized_value)
                else:
                    normalized_documents.append(value)
            normalized_paired_review = dict(paired_review)
            normalized_paired_review["documents"] = normalized_documents
            normalized["paired_document_review_request"] = normalized_paired_review
    return WorkflowRequest.model_validate(normalized)


def load_persisted_inference_transfer_workflow_request(
    document: dict[str, Any],
) -> InferenceTransferWorkflowRequest:
    """Read the exact successor snapshot; never repair nulls or replace source pins."""

    if document.get("schema_version") == "inference-transfer-workflow-request/1.1":
        return validate_inference_transfer_workflow_request_v11(document)
    return validate_inference_transfer_workflow_request(document)


def inference_transfer_business_fingerprint(
    definition: WorkflowDefinitionRecord,
    request: InferenceTransferWorkflowRequest,
    *,
    actor_type: str,
    actor_id: str,
) -> str:
    # Active equivalence is indexed only by request_hash. Including the actual
    # actor in this new purpose prevents cross-user reuse without changing the
    # released legacy fingerprint or adding a second queue/uniqueness rule.
    return content_sha256(
        {
            "definition_key": definition.definition_key,
            "definition_version": definition.definition_version,
            "definition_hash": definition.definition_hash,
            "request": request.model_dump(mode="json"),
            "actor": {"actor_type": actor_type, "actor_id": actor_id},
        }
    )


def load_persisted_local_embedding_workflow_request(
    document: dict[str, Any],
) -> LocalEmbeddingExecutableRequest:
    """Read exact supported1.1/1.2; never upgrade history, repair nulls or use latest."""
    return parse_local_embedding_executable_request(document)


def local_embedding_business_fingerprint(
    definition: WorkflowDefinitionRecord,
    request: LocalEmbeddingExecutableRequest,
    *,
    actor_type: str,
    actor_id: str,
) -> str:
    """Exact actor-bound equivalence, separate from per-encoding computation."""
    return content_sha256(
        {
            "definition_key": definition.definition_key,
            "definition_version": definition.definition_version,
            "definition_hash": definition.definition_hash,
            "request": workflow_request_storage_document(request),
            "actor": {"actor_type": actor_type, "actor_id": actor_id},
        }
    )


def validate_local_embedding_workflow_submission(
    session: Session,
    workflow: WorkflowInstanceRecord,
    *,
    definition: WorkflowDefinitionRecord,
    request: LocalEmbeddingExecutableRequest,
    actor_type: str,
    actor_id: str,
) -> WorkflowInstanceRecord:
    """Refresh exact immutable submission closure, not lifecycle/source authority."""
    current = session.scalar(
        select(WorkflowInstanceRecord)
        .where(WorkflowInstanceRecord.workflow_id == workflow.workflow_id)
        .execution_options(populate_existing=True)
    )
    expected_request = workflow_request_storage_document(request)
    if current is None or (
        current.definition_id != definition.definition_id
        or current.definition_key != definition.definition_key
        or current.definition_version != definition.definition_version
        or current.definition_hash != definition.definition_hash
        or current.protocol_version != "1.0.1"
        or current.role_schema_version != LOCAL_EMBEDDING_EXECUTION_PROTOCOL
        or current.created_actor_type != actor_type
        or current.created_actor_id != actor_id
        or current.initial_request != expected_request
        or current.request_payload != expected_request
        or current.request_hash
        != local_embedding_business_fingerprint(
            definition, request, actor_type=actor_type, actor_id=actor_id
        )
    ):
        raise ValueError("LOCAL_EMBEDDING_SUBMISSION_REPLAY_INVALID")
    return current


def reference_query_business_fingerprint(
    definition: WorkflowDefinitionRecord,
    request: ReferenceQueryWorkflowRequest,
    *,
    actor_type: str,
    actor_id: str,
) -> str:
    """Exact operator-bound QUERY identity, independent from a numerical encoding key."""
    return content_sha256(
        {
            "definition_key": definition.definition_key,
            "definition_version": definition.definition_version,
            "definition_hash": definition.definition_hash,
            "request": workflow_request_storage_document(request),
            "actor": {"actor_type": actor_type, "actor_id": actor_id},
        }
    )


def validate_reference_query_workflow_submission(
    session: Session,
    workflow: WorkflowInstanceRecord,
    *,
    definition: WorkflowDefinitionRecord,
    request: ReferenceQueryWorkflowRequest,
    actor_type: str,
    actor_id: str,
) -> WorkflowInstanceRecord:
    """Canonical submission closure, not authority from an old request or receipt."""
    request = parse_reference_query_workflow_request(request)
    current = session.scalar(
        select(WorkflowInstanceRecord)
        .where(WorkflowInstanceRecord.workflow_id == workflow.workflow_id)
        .execution_options(populate_existing=True)
    )
    expected = workflow_request_storage_document(request)
    if current is None or (
        actor_type != "human"
        or actor_id != request.operator_audit.operator_id
        or definition.definition_key != request.workflow_definition_key
        or definition.definition_version != request.workflow_definition_version
        or definition.definition_hash != request.workflow_definition_sha256
        or _stored_role_protocol(definition) != REFERENCE_QUERY_EXECUTION_PROTOCOL
        or current.definition_id != definition.definition_id
        or current.definition_key != definition.definition_key
        or current.definition_version != definition.definition_version
        or current.definition_hash != definition.definition_hash
        or current.protocol_version != "1.0.1"
        or current.role_schema_version != REFERENCE_QUERY_EXECUTION_PROTOCOL
        or current.created_actor_type != actor_type
        or current.created_actor_id != actor_id
        or current.initial_request != expected
        or current.request_payload != expected
        or current.request_hash
        != reference_query_business_fingerprint(
            definition, request, actor_type=actor_type, actor_id=actor_id
        )
    ):
        raise ValueError("REFERENCE_QUERY_SUBMISSION_REPLAY_INVALID")
    return current


def _matching_submission(
    session: Session, *, idempotency_key: str, request_hash: str
) -> WorkflowInstanceRecord | None:
    existing = session.scalar(
        select(WorkflowInstanceRecord).where(
            WorkflowInstanceRecord.idempotency_key == idempotency_key
        )
    )
    if existing is not None and existing.request_hash != request_hash:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_COMMAND_DUPLICATE,
            "workflow idempotency key was reused with different input",
        )
    return existing


def _active_equivalent(session: Session, request_hash: str) -> WorkflowInstanceRecord | None:
    return session.scalar(
        select(WorkflowInstanceRecord)
        .where(
            WorkflowInstanceRecord.request_hash == request_hash,
            WorkflowInstanceRecord.state.in_(
                tuple(state.value for state in ACTIVE_WORKFLOW_STATES)
            ),
        )
        .order_by(WorkflowInstanceRecord.created_at, WorkflowInstanceRecord.workflow_id)
        .limit(1)
    )


def _successful_equivalent(
    session: Session,
    request_hash: str,
    *,
    actor_type: str,
    actor_id: str,
    completed_preset_revision_id: str | None = None,
) -> WorkflowInstanceRecord | None:
    query = (
        select(WorkflowInstanceRecord)
        .where(
            WorkflowInstanceRecord.request_hash == request_hash,
            WorkflowInstanceRecord.state == WorkflowState.COMPLETED.value,
            WorkflowInstanceRecord.created_actor_type == actor_type,
            WorkflowInstanceRecord.created_actor_id == actor_id,
        )
        .order_by(
            WorkflowInstanceRecord.created_at.desc(),
            WorkflowInstanceRecord.workflow_id.desc(),
        )
        .limit(1)
    )
    if completed_preset_revision_id is not None:
        # Keep the canonical request hash unchanged: only completed-result reuse depends on
        # the admission's selected preset. Missing historical pointers cannot match this pin.
        query = query.where(
            WorkflowInstanceRecord.runtime_context["execution_plan"][
                "preset_revision_id"
            ].as_string()
            == completed_preset_revision_id
        )
    return session.scalar(query)


def create_workflow_instance(
    session: Session,
    *,
    definition: WorkflowDefinitionRecord,
    request: (
        WorkflowRequest
        | InferenceTransferWorkflowRequest
        | LocalEmbeddingExecutableRequest
        | ReferenceQueryWorkflowRequest
    ),
    idempotency_key: str,
    actor_type: str,
    actor_id: str,
    runtime_context: dict[str, Any] | None = None,
    completed_preset_revision_id: str | None = None,
    inference_transfer_context: InferenceTransferSubmissionContext | None = None,
    local_embedding_owner: LocalEmbeddingOwnerAdmission | None = None,
    local_embedding_executor: LocalEmbeddingNativeExecutor | None = None,
    reference_query_owner: ReferenceQueryOwnerAdmission | None = None,
    reference_query_executor: ReferenceQueryNativeExecutor | None = None,
) -> tuple[WorkflowInstanceRecord, bool]:
    if (
        isinstance(request, ReferenceQueryWorkflowRequest)
        or definition.definition_key == REFERENCE_QUERY_WORKFLOW_KEY
    ):
        if (
            not isinstance(request, ReferenceQueryWorkflowRequest)
            or definition.definition_key != REFERENCE_QUERY_WORKFLOW_KEY
        ):
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_REQUEST_INVALID,
                "workflow request kind does not match reference query purpose",
            )
        # No installed QUERY owner is inferred from the INDEX/ROLE configuration.
        if reference_query_owner is None or reference_query_executor is None:
            raise WorkflowError(
                WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
                "reference query requires its actual QUERY owner and executor",
            )
        if (
            runtime_context is not None
            or completed_preset_revision_id is not None
            or inference_transfer_context is not None
            or local_embedding_owner is not None
            or local_embedding_executor is not None
        ):
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_REQUEST_INVALID,
                "reference query cannot accept another purpose's execution context",
            )
        scope_query = resolve_reference_query_submission_controls(
            session,
            definition=definition,
            request=request,
            actor_type=actor_type,
            actor_id=actor_id,
            owner=reference_query_owner,
            executor=reference_query_executor,
        )
        with session.begin_nested():
            result = _persist_workflow_instance(
                session,
                definition=definition,
                request=scope_query.request,
                idempotency_key=idempotency_key,
                actor_type=actor_type,
                actor_id=actor_id,
            )
            workflow = validate_reference_query_workflow_submission(
                session,
                result[0],
                definition=definition,
                request=scope_query.request,
                actor_type=actor_type,
                actor_id=actor_id,
            )
            late_query = resolve_reference_query_submission_controls(
                session,
                definition=definition,
                request=scope_query.request,
                actor_type=actor_type,
                actor_id=actor_id,
                owner=reference_query_owner,
                executor=reference_query_executor,
            )
            if late_query != scope_query:
                raise ValueError("REFERENCE_QUERY_SUBMISSION_CONTEXT_INVALID")
            return workflow, result[1]
    if reference_query_owner is not None or reference_query_executor is not None:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_REQUEST_INVALID,
            "reference query owner cannot admit another workflow purpose",
        )
    if (
        isinstance(
            request, (LocalEmbeddingWorkflowRequestV11, LocalEmbeddingServiceWorkflowRequest)
        )
        or definition.definition_key == LOCAL_EMBEDDING_WORKFLOW_KEY
    ):
        if (
            not isinstance(
                request, (LocalEmbeddingWorkflowRequestV11, LocalEmbeddingServiceWorkflowRequest)
            )
            or definition.definition_key != LOCAL_EMBEDDING_WORKFLOW_KEY
        ):
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_REQUEST_INVALID,
                "workflow request kind does not match local embedding purpose",
            )
        if (
            runtime_context is not None
            or completed_preset_revision_id is not None
            or inference_transfer_context is not None
        ):
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_REQUEST_INVALID,
                "local embedding does not accept another purpose's execution context",
            )
        scope = resolve_local_embedding_submission_controls(
            session,
            definition=definition,
            request=request,
            actor_type=actor_type,
            actor_id=actor_id,
            owner=local_embedding_owner,
            executor=local_embedding_executor,
        )
        validate_local_embedding_runner_admission(
            scope,
            compile_definition_data(definition.canonical_definition, definition.source_path, set()),
            actor_type=actor_type,
            actor_id=actor_id,
        )
        with session.begin_nested():
            result = _persist_workflow_instance(
                session,
                definition=definition,
                request=scope.request,
                idempotency_key=idempotency_key,
                actor_type=actor_type,
                actor_id=actor_id,
            )
            workflow = validate_local_embedding_workflow_submission(
                session,
                result[0],
                definition=definition,
                request=scope.request,
                actor_type=actor_type,
                actor_id=actor_id,
            )
            late = resolve_local_embedding_submission_controls(
                session,
                definition=definition,
                request=scope.request,
                actor_type=actor_type,
                actor_id=actor_id,
                owner=local_embedding_owner,
                executor=local_embedding_executor,
            )
            if late != scope:
                raise ValueError("LOCAL_EMBEDDING_SUBMISSION_CONTEXT_INVALID")
            return workflow, result[1]
    if local_embedding_owner is not None or local_embedding_executor is not None:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_REQUEST_INVALID,
            "local embedding owner cannot admit another workflow purpose",
        )
    request = admit_inference_transfer_workflow_request(
        definition_key=definition.definition_key,
        definition_version=definition.definition_version,
        role_protocol_version=(
            _stored_role_protocol(definition)
            if definition.definition_key == TRANSFER_PAIR_WORKFLOW_KEY
            and isinstance(request, InferenceTransferWorkflowRequest)
            else None
        ),
        request=request,
        actor_type=actor_type,
        actor_id=actor_id,
        submission_context=inference_transfer_context,
    )
    return _persist_workflow_instance(
        session,
        definition=definition,
        request=request,
        idempotency_key=idempotency_key,
        actor_type=actor_type,
        actor_id=actor_id,
        runtime_context=runtime_context,
        completed_preset_revision_id=completed_preset_revision_id,
    )


def _persist_workflow_instance(
    session: Session,
    *,
    definition: WorkflowDefinitionRecord,
    request: (
        WorkflowRequest
        | InferenceTransferWorkflowRequest
        | LocalEmbeddingExecutableRequest
        | ReferenceQueryWorkflowRequest
    ),
    idempotency_key: str,
    actor_type: str,
    actor_id: str,
    runtime_context: dict[str, Any] | None = None,
    completed_preset_revision_id: str | None = None,
) -> tuple[WorkflowInstanceRecord, bool]:
    request_data = workflow_request_storage_document(request)
    request_hash = (
        reference_query_business_fingerprint(
            definition, request, actor_type=actor_type, actor_id=actor_id
        )
        if isinstance(request, ReferenceQueryWorkflowRequest)
        else local_embedding_business_fingerprint(
            definition, request, actor_type=actor_type, actor_id=actor_id
        )
        if isinstance(
            request, (LocalEmbeddingWorkflowRequestV11, LocalEmbeddingServiceWorkflowRequest)
        )
        else inference_transfer_business_fingerprint(
            definition, request, actor_type=actor_type, actor_id=actor_id
        )
        if isinstance(request, InferenceTransferWorkflowRequest)
        else workflow_business_fingerprint(definition, request)
    )
    existing = _matching_submission(
        session, idempotency_key=idempotency_key, request_hash=request_hash
    )
    if existing is not None:
        return existing, False
    active = _active_equivalent(session, request_hash)
    if active is not None:
        return active, False
    successful = _successful_equivalent(
        session,
        request_hash,
        actor_type=actor_type,
        actor_id=actor_id,
        completed_preset_revision_id=completed_preset_revision_id,
    )
    if successful is not None:
        return successful, False
    canonical_definition = definition.canonical_definition
    start_step = canonical_definition.get("start_step")
    if not isinstance(start_step, str):
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID,
            "stored definition has no start step",
        )
    if isinstance(
        request,
        (
            LocalEmbeddingWorkflowRequestV11,
            LocalEmbeddingServiceWorkflowRequest,
            ReferenceQueryWorkflowRequest,
        ),
    ):
        role_schema_version = _stored_role_protocol(definition)
    else:
        role_protocols = {
            result_schema_protocol(str(step["result_schema"]))
            for step in canonical_definition.get("steps", [])
            if isinstance(step, dict) and step.get("type") == "agent"
        }
        if len(role_protocols) != 1:
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID,
                "stored definition has inconsistent role protocol versions",
            )
        role_schema_version = next(iter(role_protocols))
    initial_context = dict(runtime_context or {})
    initial_context["artifact_pointers"] = []
    workflow = WorkflowInstanceRecord(
        workflow_id=new_workflow_id(),
        definition_id=definition.definition_id,
        definition_key=definition.definition_key,
        definition_version=definition.definition_version,
        definition_hash=definition.definition_hash,
        protocol_version="1.0.1",
        role_schema_version=role_schema_version,
        state=WorkflowState.REQUESTED.value,
        stage=(
            WorkflowStage.LOCAL_EMBEDDING.value
            if isinstance(
                request,
                (
                    LocalEmbeddingWorkflowRequestV11,
                    LocalEmbeddingServiceWorkflowRequest,
                    ReferenceQueryWorkflowRequest,
                ),
            )
            else WorkflowStage.INFERENCE_TRANSFER.value
            if isinstance(request, InferenceTransferWorkflowRequest)
            else WorkflowStage.DOCUMENT_REVIEW.value
            if request.request_name
            in {"PDF_DOCUMENT_REVIEW_REQUEST", "PAIRED_DOCUMENT_REVIEW_REQUEST"}
            else WorkflowStage.CUSTOMER_SUPPORT.value
            if request.request_name == "CUSTOMER_SUPPORT_REQUEST"
            else WorkflowStage.KNOWLEDGE_ANALYSIS.value
            if request.request_name
            in {
                "KNOWLEDGE_ANALYSIS_REQUEST",
                "LEGACY_ITEM_EXTRACTION_REQUEST",
                "LEGACY_ITEM_EDITORIAL_COMPATIBILITY_REQUEST",
            }
            else WorkflowStage.AUTHORING.value
        ),
        current_step_key=start_step,
        request_payload=request_data,
        initial_request=request_data,
        runtime_context=initial_context,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        lock_version=1,
        rework_cycle_count=0,
        created_actor_type=actor_type,
        created_actor_id=actor_id,
    )
    try:
        with session.begin_nested():
            session.add(workflow)
            session.flush()
    except IntegrityError:
        existing = _matching_submission(
            session, idempotency_key=idempotency_key, request_hash=request_hash
        )
        if existing is not None:
            return existing, False
        active = _active_equivalent(session, request_hash)
        if active is not None:
            return active, False
        raise
    record_initial_workflow_event(session, workflow, actor_type=actor_type, actor_id=actor_id)
    return workflow, True


def command_business_fingerprint(
    *,
    workflow_id: str,
    command_type: CommandType,
    payload: dict[str, Any],
    actor_type: str,
    actor_id: str,
    source: str,
) -> str:
    """Canonical stored command identity; validation and creation share one recipe."""
    return content_sha256(
        {
            "workflow_id": workflow_id,
            "command_type": command_type.value,
            "payload": payload,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "source": source,
        }
    )


def enqueue_command(
    session: Session,
    *,
    workflow_id: str,
    command_type: CommandType,
    payload: dict[str, Any],
    actor_type: str,
    actor_id: str,
    source: str,
    idempotency_key: str,
    available_at: datetime | None = None,
) -> tuple[WorkflowCommandRecord, bool]:
    request_hash = command_business_fingerprint(
        workflow_id=workflow_id,
        command_type=command_type,
        payload=payload,
        actor_type=actor_type,
        actor_id=actor_id,
        source=source,
    )
    existing = session.scalar(
        select(WorkflowCommandRecord).where(
            WorkflowCommandRecord.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_COMMAND_DUPLICATE,
                "command idempotency key was reused with different input",
            )
        return existing, False
    if session.get(WorkflowInstanceRecord, workflow_id) is None:
        raise WorkflowError(WorkflowErrorCode.WORKFLOW_NOT_FOUND, "workflow does not exist")
    command = WorkflowCommandRecord(
        command_id=new_command_id(),
        workflow_id=workflow_id,
        command_type=command_type.value,
        payload=payload,
        actor_type=actor_type,
        actor_id=actor_id,
        source=source,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        state=CommandState.PENDING.value,
        attempts=0,
        available_at=available_at or datetime.now(UTC),
    )
    session.add(command)
    session.flush()
    return command, True


def claim_next_command(
    session: Session,
    *,
    runner_id: str,
    lease_seconds: int,
    workflow_id: str | None = None,
) -> WorkflowCommandRecord | None:
    now = datetime.now(UTC)
    query = (
        select(WorkflowCommandRecord)
        .join(WorkflowInstanceRecord)
        .where(_claimable_command_filter(now), not_(_native_workflow_filter()))
        .order_by(WorkflowCommandRecord.created_at, WorkflowCommandRecord.command_id)
        .with_for_update(skip_locked=True, of=WorkflowCommandRecord)
        .limit(1)
    )
    if workflow_id is not None:
        query = query.where(WorkflowCommandRecord.workflow_id == workflow_id)
    command = session.execute(query).scalar_one_or_none()
    if command is None:
        return None
    _assign_command_lease(session, command, runner_id, lease_seconds, now)
    return command


def _assign_command_lease(
    session: Session,
    command: WorkflowCommandRecord,
    runner_id: str,
    lease_seconds: int,
    now: datetime,
) -> None:
    if command.state != CommandState.PENDING.value:
        transition_command(command, CommandState.PENDING)
    transition_command(command, CommandState.LEASED)
    command.attempts += 1
    command.lease_owner = runner_id
    command.lease_token = f"wflease_{secrets.token_hex(16)}"
    command.lease_generation += 1
    command.lease_expires_at = now + timedelta(seconds=lease_seconds)
    session.flush()


def peek_command_candidate(
    session: Session,
    *,
    family: CommandExecutionFamily,
    workflow_id: str | None = None,
) -> CommandCandidate | None:
    """One nonlocking FIFO header per fixed purpose; no owner/readiness call."""
    if not isinstance(family, CommandExecutionFamily):
        raise ValueError("WORKFLOW_COMMAND_EXECUTION_FAMILY_INVALID")
    predicate = _execution_family_filter(family)
    query = (
        select(WorkflowCommandRecord, WorkflowInstanceRecord)
        .join(WorkflowInstanceRecord)
        .where(
            _claimable_command_filter(datetime.now(UTC)),
            predicate,
        )
        .order_by(WorkflowCommandRecord.created_at, WorkflowCommandRecord.command_id)
        .limit(1)
        .execution_options(populate_existing=True)
    )
    if workflow_id is not None:
        query = query.where(WorkflowCommandRecord.workflow_id == workflow_id)
    row = session.execute(query).one_or_none()
    if row is None:
        return None
    command, workflow = row
    return _command_candidate(command, workflow, family)


def claim_command_candidate(
    session: Session,
    candidate: CommandCandidate,
    *,
    runner_id: str,
    lease_seconds: int,
    local_embedding_owner: LocalEmbeddingOwnerAdmission | None = None,
    local_embedding_executor: LocalEmbeddingNativeExecutor | None = None,
    reference_query_owner: ReferenceQueryOwnerAdmission | None = None,
    reference_query_executor: ReferenceQueryNativeExecutor | None = None,
) -> WorkflowCommandRecord | None:
    """Exact-ID root claim; never replace a changed or locked FIFO candidate.

    The owner must independently admit any expired native acquisition, including
    supported linked uncertain-outcome recovery, before a generation is assigned.
    A persisted request, candidate header or readiness report cannot do so.
    """
    if not isinstance(candidate, CommandCandidate) or not isinstance(
        candidate.family, CommandExecutionFamily
    ):
        raise ValueError("WORKFLOW_COMMAND_EXECUTION_FAMILY_INVALID")
    native = candidate.family is not CommandExecutionFamily.ROLE
    query_request = (
        candidate.native_request
        if isinstance(candidate.native_request, ReferenceQueryWorkflowRequest)
        else None
    )
    if native and (
        (candidate.family is CommandExecutionFamily.REFERENCE_QUERY) != (query_request is not None)
    ):
        raise WorkflowError(
            WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
            "native candidate request does not match its exact execution family",
        )
    if (
        native
        and query_request is not None
        and (
            reference_query_owner is None
            or reference_query_executor is None
            or not workflow_definition_is_admitted(
                query_request.workflow_definition_key, query_request.workflow_definition_version
            )
        )
    ):
        raise WorkflowError(
            WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
            "QUERY claim requires its admitted definition and actual owner/executor",
        )
    if (
        native
        and query_request is None
        and (local_embedding_owner is None or local_embedding_executor is None)
    ):
        raise WorkflowError(
            WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
            "native claim requires the actual owner and executor",
        )
    if native and candidate.native_request is None:
        raise WorkflowError(
            WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
            "native claim exact supported request unavailable",
        )
    root = session.get_transaction()
    if (
        not session.is_active
        or root is None
        or not root.is_active
        or session.in_nested_transaction()
    ):
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
            "exact claim requires an active root transaction",
        )
    predicate = _execution_family_filter(candidate.family)
    workflow = session.scalar(
        select(WorkflowInstanceRecord)
        .where(
            WorkflowInstanceRecord.workflow_id == candidate.workflow_id,
            predicate,
        )
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if workflow is None:
        return None
    command = session.scalar(
        select(WorkflowCommandRecord)
        .where(
            WorkflowCommandRecord.command_id == candidate.command_id,
            WorkflowCommandRecord.workflow_id == candidate.workflow_id,
            _claimable_command_filter(datetime.now(UTC)),
        )
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if (
        command is None
        or _command_candidate(command, workflow, candidate.family) != candidate
        or not _command_is_claimable(command, datetime.now(UTC))
    ):
        return None
    if native:
        definition = session.scalar(
            select(WorkflowDefinitionRecord)
            .where(WorkflowDefinitionRecord.definition_id == workflow.definition_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if definition is None or definition.definition_hash != workflow.definition_hash:
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID,
                "native exact definition is unavailable",
            )
        if not isinstance(definition.canonical_definition, dict):
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID,
                "native exact definition snapshot is not an object",
            )
        if query_request is not None:
            assert reference_query_owner is not None
            request_query = parse_reference_query_workflow_request(workflow.initial_request)
            if definition.definition_key != REFERENCE_QUERY_WORKFLOW_KEY:
                raise WorkflowError(
                    WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
                    "QUERY claim definition purpose differs",
                )
            scope_query = reference_query_owner.resolve_claim(
                session, command=command, workflow=workflow, request=request_query
            )
            scope_query = validate_reference_query_runner_admission(
                scope_query,
                compile_definition_data(
                    definition.canonical_definition, definition.source_path, set()
                ),
                actor_type=workflow.created_actor_type,
                actor_id=workflow.created_actor_id,
            )
            if (
                scope_query.request != request_query
                or definition.definition_hash != request_query.workflow_definition_sha256
                or command.request_hash != candidate.command_contents_hash
            ):
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_REQUEST_INVALID,
                    "QUERY exact candidate closure differs",
                )
            validate_reference_query_workflow_submission(
                session,
                workflow,
                definition=definition,
                request=request_query,
                actor_type=workflow.created_actor_type,
                actor_id=workflow.created_actor_id,
            )
        else:
            assert local_embedding_owner is not None
            request = load_persisted_local_embedding_workflow_request(workflow.initial_request)
            _validate_local_embedding_claim(
                session, candidate, command, workflow, definition, request, local_embedding_owner
            )
    _assign_command_lease(session, command, runner_id, lease_seconds, datetime.now(UTC))
    if native:
        if query_request is not None:
            assert reference_query_owner is not None
            reference_query_owner.fence_mutation(
                session, query_request, command_lease_identity(command)
            )
        else:
            assert local_embedding_owner is not None
            assert isinstance(
                candidate.native_request,
                (LocalEmbeddingWorkflowRequestV11, LocalEmbeddingServiceWorkflowRequest),
            )
            local_embedding_owner.fence_mutation(
                session, candidate.native_request, command_lease_identity(command)
            )
    require_command_lease(session, command_lease_identity(command), for_update=True)
    return command


def _validate_local_embedding_claim(
    session: Session,
    candidate: CommandCandidate,
    command: WorkflowCommandRecord,
    workflow: WorkflowInstanceRecord,
    definition: WorkflowDefinitionRecord,
    request: LocalEmbeddingExecutableRequest,
    owner: LocalEmbeddingOwnerAdmission,
) -> None:
    if (
        definition.definition_key != LOCAL_EMBEDDING_WORKFLOW_KEY
        or definition.canonical_definition.get("definition_key") == REFERENCE_QUERY_WORKFLOW_KEY
    ):
        raise WorkflowError(
            WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
            "native claim definition purpose is not supported",
        )
    scope = owner.resolve_claim(session, command=command, workflow=workflow, request=request)
    scope = validate_local_embedding_runner_admission(
        scope,
        compile_definition_data(definition.canonical_definition, definition.source_path, set()),
        actor_type=workflow.created_actor_type,
        actor_id=workflow.created_actor_id,
    )
    if (
        scope.request != request
        or definition.definition_hash != scope.request.workflow_definition_sha256
        or command.request_hash != candidate.command_contents_hash
    ):
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_REQUEST_INVALID,
            "native exact candidate closure differs",
        )
    validate_local_embedding_workflow_submission(
        session,
        workflow,
        definition=definition,
        request=request,
        actor_type=workflow.created_actor_type,
        actor_id=workflow.created_actor_id,
    )


def command_lease_identity(command: WorkflowCommandRecord) -> CommandLeaseIdentity:
    if command.lease_owner is None or command.lease_token is None:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
            "workflow command does not have a complete lease identity",
        )
    return CommandLeaseIdentity(
        command_id=command.command_id,
        runner_id=command.lease_owner,
        lease_token=command.lease_token,
        lease_generation=command.lease_generation,
    )


def require_command_lease(
    session: Session,
    identity: CommandLeaseIdentity,
    *,
    observed_at: datetime | None = None,
    for_update: bool = False,
) -> WorkflowCommandRecord:
    query = (
        select(WorkflowCommandRecord)
        .where(WorkflowCommandRecord.command_id == identity.command_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        query = query.with_for_update()
    command = session.execute(query).scalar_one_or_none()
    now = observed_at or datetime.now(UTC)
    if (
        command is None
        or command.state not in {CommandState.LEASED.value, CommandState.PROCESSING.value}
        or command.lease_owner != identity.runner_id
        or command.lease_token != identity.lease_token
        or command.lease_generation != identity.lease_generation
        or command.lease_expires_at is None
        or command.lease_expires_at <= now
    ):
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
            "workflow command lease ownership was lost",
        )
    return command


def renew_command_lease(
    session: Session,
    identity: CommandLeaseIdentity,
    *,
    lease_seconds: int,
    observed_at: datetime | None = None,
) -> datetime:
    now = observed_at or datetime.now(UTC)
    command = require_command_lease(session, identity, observed_at=now)
    expires_at = now + timedelta(seconds=lease_seconds)
    command.lease_expires_at = expires_at
    session.flush()
    return expires_at


def claimable_command_exists(session: Session, *, workflow_id: str | None = None) -> bool:
    """Check for pending or reclaimable work without locking or changing it."""
    query = (
        select(WorkflowCommandRecord.command_id)
        .join(WorkflowInstanceRecord)
        .where(_claimable_command_filter(datetime.now(UTC)), not_(_native_workflow_filter()))
        .order_by(WorkflowCommandRecord.created_at, WorkflowCommandRecord.command_id)
        .limit(1)
    )
    if workflow_id is not None:
        query = query.where(WorkflowCommandRecord.workflow_id == workflow_id)
    return session.scalar(query) is not None


def _claimable_command_filter(now: datetime) -> ColumnElement[bool]:
    return or_(
        (
            (WorkflowCommandRecord.state == CommandState.PENDING.value)
            & (WorkflowCommandRecord.available_at <= now)
        ),
        (
            WorkflowCommandRecord.state.in_(
                [CommandState.LEASED.value, CommandState.PROCESSING.value]
            )
            & (WorkflowCommandRecord.lease_expires_at < now)
        ),
    )


def _command_is_claimable(command: WorkflowCommandRecord, now: datetime) -> bool:
    return (command.state == CommandState.PENDING.value and command.available_at <= now) or (
        command.state in {CommandState.LEASED.value, CommandState.PROCESSING.value}
        and command.lease_expires_at is not None
        and command.lease_expires_at < now
    )


def create_step_run(
    session: Session,
    *,
    workflow_id: str,
    step_key: str,
    step_type: str,
    worker_role: str | None,
    result_schema: str | None,
    input_pointer_manifest: dict[str, Any],
    max_attempts: int,
) -> WorkflowStepRunRecord:
    latest_attempt = session.scalar(
        select(func.coalesce(func.max(WorkflowStepRunRecord.attempt), 0)).where(
            WorkflowStepRunRecord.workflow_id == workflow_id,
            WorkflowStepRunRecord.step_key == step_key,
        )
    )
    attempt = int(latest_attempt or 0) + 1
    if attempt > max_attempts:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_REWORK_LIMIT_EXCEEDED,
            "workflow step attempt limit exceeded",
        )
    step = WorkflowStepRunRecord(
        step_run_id=new_step_run_id(),
        workflow_id=workflow_id,
        step_key=step_key,
        attempt=attempt,
        step_type=step_type,
        worker_role=worker_role,
        result_schema=result_schema,
        state=StepState.PENDING.value,
        input_pointer_manifest=input_pointer_manifest,
    )
    session.add(step)
    session.flush()
    previous = session.scalar(
        select(WorkflowStepRunRecord)
        .where(
            WorkflowStepRunRecord.workflow_id == workflow_id,
            WorkflowStepRunRecord.step_key == step_key,
            WorkflowStepRunRecord.state == StepState.SUPERSEDED.value,
            WorkflowStepRunRecord.superseded_by_step_run_id.is_(None),
        )
        .order_by(WorkflowStepRunRecord.attempt.desc())
        .limit(1)
    )
    if previous is not None:
        previous.superseded_by_step_run_id = step.step_run_id
    transition_step(step, StepState.READY)
    return step


def link_superseded_attempts(session: Session, workflow_id: str) -> None:
    superseded = list(
        session.scalars(
            select(WorkflowStepRunRecord).where(
                WorkflowStepRunRecord.workflow_id == workflow_id,
                WorkflowStepRunRecord.state == StepState.SUPERSEDED.value,
                WorkflowStepRunRecord.superseded_by_step_run_id.is_(None),
            )
        )
    )
    for previous in superseded:
        replacement = session.scalar(
            select(WorkflowStepRunRecord)
            .where(
                WorkflowStepRunRecord.workflow_id == workflow_id,
                WorkflowStepRunRecord.step_key == previous.step_key,
                WorkflowStepRunRecord.attempt > previous.attempt,
                WorkflowStepRunRecord.state != StepState.SUPERSEDED.value,
            )
            .order_by(WorkflowStepRunRecord.attempt)
            .limit(1)
        )
        if replacement is not None:
            previous.superseded_by_step_run_id = replacement.step_run_id


def create_approval_request(
    session: Session,
    *,
    workflow_id: str,
    step_run_id: str,
    allowed_roles: tuple[str, ...],
    allowed_rework_targets: tuple[str, ...],
) -> ApprovalRequestRecord:
    active = active_approval(session, workflow_id, for_update=True)
    if active is not None:
        raise WorkflowError(
            WorkflowErrorCode.APPROVAL_STALE,
            "workflow already has an active approval request",
        )
    approval = ApprovalRequestRecord(
        approval_request_id=new_approval_request_id(),
        workflow_id=workflow_id,
        step_run_id=step_run_id,
        status=ApprovalState.PENDING.value,
        lock_version=1,
        allowed_roles=list(allowed_roles),
        allowed_rework_targets=list(allowed_rework_targets),
    )
    session.add(approval)
    session.flush()
    return approval


def active_approval(
    session: Session, workflow_id: str, *, for_update: bool = False
) -> ApprovalRequestRecord | None:
    query = select(ApprovalRequestRecord).where(
        ApprovalRequestRecord.workflow_id == workflow_id,
        ApprovalRequestRecord.status == ApprovalState.PENDING.value,
    )
    if for_update:
        query = query.with_for_update()
    return session.execute(query).scalar_one_or_none()


def list_workflow_events(session: Session, workflow_id: str) -> list[WorkflowEventRecord]:
    return list(
        session.scalars(
            select(WorkflowEventRecord)
            .where(WorkflowEventRecord.workflow_id == workflow_id)
            .order_by(WorkflowEventRecord.sequence)
        )
    )


def list_step_runs(session: Session, workflow_id: str) -> list[WorkflowStepRunRecord]:
    return list(
        session.scalars(
            select(WorkflowStepRunRecord)
            .where(WorkflowStepRunRecord.workflow_id == workflow_id)
            .order_by(
                WorkflowStepRunRecord.attempt,
                WorkflowStepRunRecord.step_run_id,
            )
        )
    )
