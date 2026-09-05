"""Application use cases for one immutable source-grounded knowledge analysis."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from eom_catalog_contracts import (
    ApprovedItemKnowledgeAnalysisSelection,
    ApprovedItemKnowledgeSourceV2,
    ContentIntakeKnowledgeAnalysisSelection,
    ContentIntakeKnowledgeSourceV2,
    CreateKnowledgeAnalysisCommand,
    EducationalDocumentKnowledgeAnalysisSelection,
    EducationalDocumentKnowledgeSourceV3,
    EducationalDocumentKnowledgeSourceV4,
    KnowledgeAnalysisApplicationResult,
    KnowledgeAnalysisProposalReceipt,
    KnowledgeAnalysisProposalReceiptV2,
    KnowledgeAnalysisProposalReceiptV3,
    KnowledgeAnalysisProposalReceiptV4,
    KnowledgeAnalysisProposalReceiptV5,
    KnowledgeAnalysisProposalReceiptV6,
    KnowledgeAnalysisProposalReceiptV7,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisRequestV3,
    KnowledgeAnalysisRequestV4,
    KnowledgeAnalysisRequestV5,
    KnowledgeAnalysisRequestV6,
    KnowledgeAnalysisRequestV7,
    KnowledgeAnalysisRequestV8,
    KnowledgeAnalysisResultV2,
    KnowledgeAnalysisResultV3,
    KnowledgeAnalysisResultV4,
    KnowledgeAnalysisResultV5,
    KnowledgeAnalysisResultV6,
    KnowledgeAnalysisResultV7,
    KnowledgeAnalysisResultV8,
    KnowledgeAnalysisReviewDecision,
    KnowledgeAnalysisRiskPolicy,
    KnowledgeArtifactMemberPointer,
    KnowledgeProposalArtifactMember,
    ReconcileKnowledgeAnalysisCommand,
    ReviewKnowledgeAnalysisCommand,
    validate_contract,
    validate_knowledge_analysis_proposal_ontology,
)
from eom_identifiers import (
    canonical_json_bytes,
    content_sha256,
    new_knowledge_analysis_decision_id,
    new_knowledge_analysis_request_id,
    new_knowledge_analysis_run_id,
    sha256_bytes,
)
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.execution_resolver import resolve_knowledge_analysis_plan
from eom_orchestrator.knowledge_analysis_models import (
    KnowledgeAnalysisEventRecord,
    KnowledgeAnalysisReviewRecord,
    KnowledgeAnalysisRiskPolicyRevisionRecord,
    KnowledgeAnalysisRunRecord,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_workflow import ArtifactPointer, WorkflowRequest
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow_runner.models import WorkflowInstanceRecord
from eom_workflow_runner.repository import (
    CommandType,
    admitted_workflow_definition,
    create_workflow_instance,
    enqueue_command,
)
from eom_workflow_runner.state_machine import WorkflowState
from pydantic import ValidationError
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifact, CatalogArtifactService
from eom_catalog_service.knowledge_analysis_risk import evaluate_knowledge_analysis_risk
from eom_catalog_service.knowledge_analysis_sources import (
    KnowledgeAnalysisSourceError,
    resolve_approved_item_source,
    resolve_content_intake_source,
    resolve_educational_document_source,
)
from eom_catalog_service.knowledge_proposal_resolution import (
    KnowledgeProposalResolutionError,
    resolve_knowledge_analysis_proposal,
)
from eom_catalog_service.settings import CatalogSettings

KNOWLEDGE_ANALYSIS_WORKFLOW_VERSION = "1.0.0"
KNOWLEDGE_ANALYSIS_DOCUMENT_WORKFLOW_VERSION = "2.0.0"
KNOWLEDGE_ANALYSIS_ENDPOINT_TYPED_DOCUMENT_WORKFLOW_VERSION = "3.0.0"
KNOWLEDGE_ANALYSIS_INTEGRITY_DOCUMENT_WORKFLOW_VERSION = "4.0.0"
KNOWLEDGE_ANALYSIS_MULTIMODAL_DOCUMENT_WORKFLOW_VERSION = "5.0.0"
KNOWLEDGE_ANALYSIS_SCHEMA_CLOSED_MULTIMODAL_WORKFLOW_VERSION = "6.0.0"
KNOWLEDGE_ANALYSIS_TYPED_IDENTITY_MULTIMODAL_WORKFLOW_VERSION = "7.0.0"
KNOWLEDGE_ANALYSIS_STABLE_IDENTITY_MULTIMODAL_WORKFLOW_VERSION = "8.0.0"
# ``catalog/1.2`` is the immutable Item-content V2 protocol in production.  Approved-Item
# knowledge-analysis review/result artifacts have a different contract set, so they need their
# own protocol identity instead of attempting to reuse that version with another schema hash.
KNOWLEDGE_ANALYSIS_CATALOG_PROTOCOL = "catalog/1.9"
KNOWLEDGE_ANALYSIS_CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": KNOWLEDGE_ANALYSIS_CATALOG_PROTOCOL,
        "contracts": [
            "knowledge-analysis-request/2.0",
            "knowledge-analysis-proposal-receipt/1.0",
            "knowledge-analysis-risk-policy/1.0",
            "knowledge-analysis-review-decision/1.0",
            "knowledge-analysis-result/2.0",
        ],
    }
)
KNOWLEDGE_ANALYSIS_DOCUMENT_CATALOG_PROTOCOL = "catalog/1.3"
KNOWLEDGE_ANALYSIS_DOCUMENT_CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": KNOWLEDGE_ANALYSIS_DOCUMENT_CATALOG_PROTOCOL,
        "contracts": [
            "knowledge-analysis-request/3.0",
            "knowledge-analysis-proposal-receipt/2.0",
            "knowledge-analysis-risk-policy/1.0",
            "knowledge-analysis-review-decision/1.0",
            "knowledge-analysis-result/3.0",
        ],
    }
)
KNOWLEDGE_ANALYSIS_ENDPOINT_TYPED_DOCUMENT_CATALOG_PROTOCOL = "catalog/1.4"
KNOWLEDGE_ANALYSIS_ENDPOINT_TYPED_DOCUMENT_CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": KNOWLEDGE_ANALYSIS_ENDPOINT_TYPED_DOCUMENT_CATALOG_PROTOCOL,
        "contracts": [
            "knowledge-analysis-request/4.0",
            "knowledge-analysis-worker-proposal/2.0",
            "knowledge-analysis-proposal-receipt/3.0",
            "knowledge-analysis-risk-policy/1.0",
            "knowledge-analysis-review-decision/1.0",
            "knowledge-analysis-result/4.0",
        ],
    }
)
KNOWLEDGE_ANALYSIS_INTEGRITY_DOCUMENT_CATALOG_PROTOCOL = "catalog/1.5"
KNOWLEDGE_ANALYSIS_INTEGRITY_DOCUMENT_CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": KNOWLEDGE_ANALYSIS_INTEGRITY_DOCUMENT_CATALOG_PROTOCOL,
        "contracts": [
            "knowledge-analysis-request/5.0",
            "knowledge-analysis-worker-proposal/3.0",
            "knowledge-analysis-proposal-receipt/4.0",
            "knowledge-analysis-risk-policy/1.0",
            "knowledge-analysis-review-decision/1.0",
            "knowledge-analysis-result/5.0",
        ],
    }
)
KNOWLEDGE_ANALYSIS_MULTIMODAL_DOCUMENT_CATALOG_PROTOCOL = "catalog/1.6"
KNOWLEDGE_ANALYSIS_MULTIMODAL_DOCUMENT_CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": KNOWLEDGE_ANALYSIS_MULTIMODAL_DOCUMENT_CATALOG_PROTOCOL,
        "contracts": [
            "knowledge-analysis-request/6.0",
            "knowledge-analysis-worker-proposal/4.0",
            "knowledge-analysis-proposal-receipt/5.0",
            "knowledge-analysis-risk-policy/1.0",
            "knowledge-analysis-review-decision/1.0",
            "knowledge-analysis-result/6.0",
        ],
    }
)
KNOWLEDGE_ANALYSIS_TYPED_IDENTITY_CATALOG_PROTOCOL = "catalog/1.7"
KNOWLEDGE_ANALYSIS_TYPED_IDENTITY_CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": KNOWLEDGE_ANALYSIS_TYPED_IDENTITY_CATALOG_PROTOCOL,
        "contracts": [
            "knowledge-analysis-request/7.0",
            "knowledge-analysis-worker-proposal/5.0",
            "knowledge-analysis-proposal-receipt/6.0",
            "knowledge-analysis-risk-policy/1.0",
            "knowledge-analysis-review-decision/1.0",
            "knowledge-analysis-result/7.0",
        ],
    }
)
KNOWLEDGE_ANALYSIS_STABLE_IDENTITY_CATALOG_PROTOCOL = "catalog/1.8"
KNOWLEDGE_ANALYSIS_STABLE_IDENTITY_CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": KNOWLEDGE_ANALYSIS_STABLE_IDENTITY_CATALOG_PROTOCOL,
        "contracts": [
            "knowledge-analysis-request/8.0",
            "knowledge-analysis-worker-proposal/6.0",
            "knowledge-analysis-proposal-receipt/7.0",
            "knowledge-analysis-risk-policy/1.0",
            "knowledge-analysis-review-decision/1.0",
            "knowledge-analysis-result/8.0",
        ],
    }
)
REQUESTED_OUTPUTS = (
    "NORMALIZED_MARKDOWN",
    "SOURCE_ANCHORS",
    "NODES",
    "EDGES",
    "CLAIMS",
    "COMPONENT_OBSERVATIONS",
    "UNRESOLVED_AMBIGUITIES",
)
MULTIMODAL_REQUESTED_OUTPUTS = (
    *REQUESTED_OUTPUTS[:-1],
    "PAGE_IMAGE_OBSERVATIONS",
    REQUESTED_OUTPUTS[-1],
)
TERMINAL_RUN_STATES = frozenset({"ACCEPTED", "REJECTED", "FAILED", "CANCELLED"})
type KnowledgeAnalysisRequestContract = (
    KnowledgeAnalysisRequestV2
    | KnowledgeAnalysisRequestV3
    | KnowledgeAnalysisRequestV4
    | KnowledgeAnalysisRequestV5
    | KnowledgeAnalysisRequestV6
    | KnowledgeAnalysisRequestV7
    | KnowledgeAnalysisRequestV8
)
type KnowledgeAnalysisReceiptContract = (
    KnowledgeAnalysisProposalReceipt
    | KnowledgeAnalysisProposalReceiptV2
    | KnowledgeAnalysisProposalReceiptV3
    | KnowledgeAnalysisProposalReceiptV4
    | KnowledgeAnalysisProposalReceiptV5
    | KnowledgeAnalysisProposalReceiptV6
    | KnowledgeAnalysisProposalReceiptV7
)
type KnowledgeAnalysisResultContract = (
    KnowledgeAnalysisResultV2
    | KnowledgeAnalysisResultV3
    | KnowledgeAnalysisResultV4
    | KnowledgeAnalysisResultV5
    | KnowledgeAnalysisResultV6
    | KnowledgeAnalysisResultV7
    | KnowledgeAnalysisResultV8
)
type KnowledgeAnalysisSourceContract = (
    ContentIntakeKnowledgeSourceV2
    | ApprovedItemKnowledgeSourceV2
    | EducationalDocumentKnowledgeSourceV3
    | EducationalDocumentKnowledgeSourceV4
)


def _utc_json_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("knowledge analysis timestamps must be timezone-aware")
    # Match Pydantic's JSON-mode datetime representation because self-hash
    # validators hash their model_dump(mode="json") value.
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _analysis_request(value: dict[str, Any]) -> KnowledgeAnalysisRequestContract:
    version = value.get("schema_version")
    if version == "knowledge-analysis-request/2.0":
        return KnowledgeAnalysisRequestV2.model_validate(value)
    if version == "knowledge-analysis-request/3.0":
        return KnowledgeAnalysisRequestV3.model_validate(value)
    if version == "knowledge-analysis-request/4.0":
        return KnowledgeAnalysisRequestV4.model_validate(value)
    if version == "knowledge-analysis-request/5.0":
        return KnowledgeAnalysisRequestV5.model_validate(value)
    if version == "knowledge-analysis-request/6.0":
        return KnowledgeAnalysisRequestV6.model_validate(value)
    if version == "knowledge-analysis-request/7.0":
        return KnowledgeAnalysisRequestV7.model_validate(value)
    if version == "knowledge-analysis-request/8.0":
        return KnowledgeAnalysisRequestV8.model_validate(value)
    raise KnowledgeAnalysisServiceError(
        "KNOWLEDGE_ANALYSIS_REQUEST_INVALID", "knowledge analysis request schema is unsupported"
    )


def _document_contract(value: KnowledgeAnalysisRequestContract) -> bool:
    return isinstance(
        value,
        (
            KnowledgeAnalysisRequestV3,
            KnowledgeAnalysisRequestV4,
            KnowledgeAnalysisRequestV5,
            KnowledgeAnalysisRequestV6,
            KnowledgeAnalysisRequestV7,
            KnowledgeAnalysisRequestV8,
        ),
    ) and isinstance(
        value.source, (EducationalDocumentKnowledgeSourceV3, EducationalDocumentKnowledgeSourceV4)
    )


def _endpoint_typed_document_contract(value: KnowledgeAnalysisRequestContract) -> bool:
    return isinstance(
        value,
        (
            KnowledgeAnalysisRequestV4,
            KnowledgeAnalysisRequestV5,
            KnowledgeAnalysisRequestV6,
            KnowledgeAnalysisRequestV7,
            KnowledgeAnalysisRequestV8,
        ),
    )


def _integrity_document_contract(value: KnowledgeAnalysisRequestContract) -> bool:
    return isinstance(
        value,
        (
            KnowledgeAnalysisRequestV5,
            KnowledgeAnalysisRequestV6,
            KnowledgeAnalysisRequestV7,
            KnowledgeAnalysisRequestV8,
        ),
    )


def _multimodal_document_contract(value: KnowledgeAnalysisRequestContract) -> bool:
    return isinstance(
        value, (KnowledgeAnalysisRequestV6, KnowledgeAnalysisRequestV7, KnowledgeAnalysisRequestV8)
    )


def _typed_identity_multimodal_contract(value: KnowledgeAnalysisRequestContract) -> bool:
    return isinstance(value, KnowledgeAnalysisRequestV7)


def _stable_identity_multimodal_contract(value: KnowledgeAnalysisRequestContract) -> bool:
    return isinstance(value, KnowledgeAnalysisRequestV8)


def _proposal_result_schema(
    value: KnowledgeAnalysisRequestContract, *, workflow_version: str | None = None
) -> str:
    if _stable_identity_multimodal_contract(value):
        return "knowledge-analysis-proposal-result@8.0"
    if _typed_identity_multimodal_contract(value):
        return "knowledge-analysis-proposal-result@7.0"
    if _multimodal_document_contract(value):
        return (
            "knowledge-analysis-proposal-result@6.0"
            if workflow_version == KNOWLEDGE_ANALYSIS_SCHEMA_CLOSED_MULTIMODAL_WORKFLOW_VERSION
            else "knowledge-analysis-proposal-result@5.0"
        )
    if _integrity_document_contract(value):
        return "knowledge-analysis-proposal-result@4.0"
    if _endpoint_typed_document_contract(value):
        return "knowledge-analysis-proposal-result@3.0"
    if _document_contract(value):
        return "knowledge-analysis-proposal-result@2.0"
    return "knowledge-analysis-proposal-result@1.0"


def _proposal_receipt_schema(value: KnowledgeAnalysisRequestContract) -> tuple[str, str]:
    if _stable_identity_multimodal_contract(value):
        return (
            "knowledge-analysis-proposal-receipt-v7",
            "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/7.0",
        )
    if _typed_identity_multimodal_contract(value):
        return (
            "knowledge-analysis-proposal-receipt-v6",
            "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/6.0",
        )
    if _multimodal_document_contract(value):
        return (
            "knowledge-analysis-proposal-receipt-v5",
            "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/5.0",
        )
    if _integrity_document_contract(value):
        return (
            "knowledge-analysis-proposal-receipt-v4",
            "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/4.0",
        )
    if _endpoint_typed_document_contract(value):
        return (
            "knowledge-analysis-proposal-receipt-v3",
            "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/3.0",
        )
    if _document_contract(value):
        return (
            "knowledge-analysis-proposal-receipt-v2",
            "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/2.0",
        )
    return (
        "knowledge-analysis-proposal-receipt",
        "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/1.0",
    )


def _receipt_contract(
    value: dict[str, Any], request: KnowledgeAnalysisRequestContract
) -> KnowledgeAnalysisReceiptContract:
    if _stable_identity_multimodal_contract(request):
        validate_contract("knowledge-analysis-proposal-receipt-v7", value)
        return KnowledgeAnalysisProposalReceiptV7.model_validate(value)
    if _typed_identity_multimodal_contract(request):
        validate_contract("knowledge-analysis-proposal-receipt-v6", value)
        return KnowledgeAnalysisProposalReceiptV6.model_validate(value)
    if _multimodal_document_contract(request):
        validate_contract("knowledge-analysis-proposal-receipt-v5", value)
        return KnowledgeAnalysisProposalReceiptV5.model_validate(value)
    if _integrity_document_contract(request):
        validate_contract("knowledge-analysis-proposal-receipt-v4", value)
        return KnowledgeAnalysisProposalReceiptV4.model_validate(value)
    if _endpoint_typed_document_contract(request):
        validate_contract("knowledge-analysis-proposal-receipt-v3", value)
        return KnowledgeAnalysisProposalReceiptV3.model_validate(value)
    if _document_contract(request):
        validate_contract("knowledge-analysis-proposal-receipt-v2", value)
        return KnowledgeAnalysisProposalReceiptV2.model_validate(value)
    validate_contract("knowledge-analysis-proposal-receipt", value)
    return KnowledgeAnalysisProposalReceipt.model_validate(value)


def _catalog_protocol(request: KnowledgeAnalysisRequestContract) -> tuple[str, str]:
    if _stable_identity_multimodal_contract(request):
        return (
            KNOWLEDGE_ANALYSIS_STABLE_IDENTITY_CATALOG_PROTOCOL,
            KNOWLEDGE_ANALYSIS_STABLE_IDENTITY_CATALOG_SCHEMA_HASH,
        )
    if _typed_identity_multimodal_contract(request):
        return (
            KNOWLEDGE_ANALYSIS_TYPED_IDENTITY_CATALOG_PROTOCOL,
            KNOWLEDGE_ANALYSIS_TYPED_IDENTITY_CATALOG_SCHEMA_HASH,
        )
    if _multimodal_document_contract(request):
        return (
            KNOWLEDGE_ANALYSIS_MULTIMODAL_DOCUMENT_CATALOG_PROTOCOL,
            KNOWLEDGE_ANALYSIS_MULTIMODAL_DOCUMENT_CATALOG_SCHEMA_HASH,
        )
    if _integrity_document_contract(request):
        return (
            KNOWLEDGE_ANALYSIS_INTEGRITY_DOCUMENT_CATALOG_PROTOCOL,
            KNOWLEDGE_ANALYSIS_INTEGRITY_DOCUMENT_CATALOG_SCHEMA_HASH,
        )
    if _endpoint_typed_document_contract(request):
        return (
            KNOWLEDGE_ANALYSIS_ENDPOINT_TYPED_DOCUMENT_CATALOG_PROTOCOL,
            KNOWLEDGE_ANALYSIS_ENDPOINT_TYPED_DOCUMENT_CATALOG_SCHEMA_HASH,
        )
    if _document_contract(request):
        return (
            KNOWLEDGE_ANALYSIS_DOCUMENT_CATALOG_PROTOCOL,
            KNOWLEDGE_ANALYSIS_DOCUMENT_CATALOG_SCHEMA_HASH,
        )
    return KNOWLEDGE_ANALYSIS_CATALOG_PROTOCOL, KNOWLEDGE_ANALYSIS_CATALOG_SCHEMA_HASH


class KnowledgeAnalysisServiceError(RuntimeError):
    """Stable, bounded error at the knowledge-analysis application boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class KnowledgeAnalysisApplicationService:
    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine, self.settings)

    def create(self, command: CreateKnowledgeAnalysisCommand) -> KnowledgeAnalysisApplicationResult:
        return self._create(command, pinned_preset=None)

    def create_with_pinned_preset(
        self,
        command: CreateKnowledgeAnalysisCommand,
        *,
        preset_id: str,
        preset_revision_id: str,
    ) -> KnowledgeAnalysisApplicationResult:
        """Create through the ordinary use case while preserving an authorized preset revision."""

        return self._create(
            command,
            pinned_preset=(preset_id, preset_revision_id),
        )

    def _create(
        self,
        command: CreateKnowledgeAnalysisCommand,
        *,
        pinned_preset: tuple[str, str] | None,
    ) -> KnowledgeAnalysisApplicationResult:
        submission = command.model_dump(mode="json", exclude={"operation", "idempotency_key"})
        submission_sha256 = content_sha256(submission)
        try:
            with transaction(self.sessions) as session:
                existing = session.scalar(
                    select(KnowledgeAnalysisRunRecord)
                    .where(KnowledgeAnalysisRunRecord.idempotency_key == command.idempotency_key)
                    .with_for_update()
                )
                if existing is not None:
                    if existing.submission_sha256 != submission_sha256:
                        raise KnowledgeAnalysisServiceError(
                            "KNOWLEDGE_ANALYSIS_IDEMPOTENCY_CONFLICT",
                            "knowledge analysis idempotency key has different input",
                        )
                    return self._projection(existing)

                source = self._resolve_source(session, command)
                predecessor = self.retry_predecessor(session, command, source)
                policy = self.risk_policy(session, command.risk_policy_revision_id)
                if pinned_preset is not None:
                    preset_logical, preset_revision = self.pinned_preset(
                        session,
                        preset_key=command.preset_key,
                        preset_id=pinned_preset[0],
                        preset_revision_id=pinned_preset[1],
                    )
                    if predecessor is not None and (
                        predecessor.preset_id != preset_logical.preset_id
                        or predecessor.preset_revision_id != preset_revision.preset_revision_id
                    ):
                        raise KnowledgeAnalysisServiceError(
                            "KNOWLEDGE_ANALYSIS_RETRY_INVALID",
                            "knowledge analysis retry preset differs from the predecessor",
                        )
                elif predecessor is None:
                    preset_logical, preset_revision = self.published_preset(
                        session, command.preset_key
                    )
                else:
                    preset_logical, preset_revision = self.pinned_preset(
                        session,
                        preset_key=command.preset_key,
                        preset_id=predecessor.preset_id,
                        preset_revision_id=predecessor.preset_revision_id,
                    )
                is_document_source = isinstance(
                    source,
                    (EducationalDocumentKnowledgeSourceV3, EducationalDocumentKnowledgeSourceV4),
                )
                multimodal_document = isinstance(source, EducationalDocumentKnowledgeSourceV4)
                typed_identity_multimodal = multimodal_document and (
                    "workflow-role/1.10.0" in preset_revision.compatible_workflow_protocols
                )
                stable_identity_multimodal = multimodal_document and (
                    "workflow-role/1.11.0" in preset_revision.compatible_workflow_protocols
                )
                schema_closed_multimodal = multimodal_document and (
                    "workflow-role/1.9.0" in preset_revision.compatible_workflow_protocols
                )
                if (
                    multimodal_document
                    and not schema_closed_multimodal
                    and ("workflow-role/1.8.0" not in preset_revision.compatible_workflow_protocols)
                ):
                    raise KnowledgeAnalysisServiceError(
                        "KNOWLEDGE_ANALYSIS_PRESET_INCOMPATIBLE",
                        "multimodal document analysis requires a compatible multimodal protocol",
                    )
                integrity_document = is_document_source and (
                    "workflow-role/1.7.0" in preset_revision.compatible_workflow_protocols
                )
                endpoint_typed_document = is_document_source and (
                    "workflow-role/1.6.0" in preset_revision.compatible_workflow_protocols
                )
                if stable_identity_multimodal:
                    workflow_version = (
                        KNOWLEDGE_ANALYSIS_STABLE_IDENTITY_MULTIMODAL_WORKFLOW_VERSION
                    )
                elif typed_identity_multimodal:
                    workflow_version = KNOWLEDGE_ANALYSIS_TYPED_IDENTITY_MULTIMODAL_WORKFLOW_VERSION
                elif schema_closed_multimodal:
                    workflow_version = KNOWLEDGE_ANALYSIS_SCHEMA_CLOSED_MULTIMODAL_WORKFLOW_VERSION
                elif multimodal_document:
                    workflow_version = KNOWLEDGE_ANALYSIS_MULTIMODAL_DOCUMENT_WORKFLOW_VERSION
                elif integrity_document:
                    workflow_version = KNOWLEDGE_ANALYSIS_INTEGRITY_DOCUMENT_WORKFLOW_VERSION
                elif endpoint_typed_document:
                    workflow_version = KNOWLEDGE_ANALYSIS_ENDPOINT_TYPED_DOCUMENT_WORKFLOW_VERSION
                elif is_document_source:
                    workflow_version = KNOWLEDGE_ANALYSIS_DOCUMENT_WORKFLOW_VERSION
                else:
                    workflow_version = KNOWLEDGE_ANALYSIS_WORKFLOW_VERSION
                definition = admitted_workflow_definition(
                    session,
                    definition_key="knowledge-analysis",
                    definition_version=workflow_version,
                )
                if definition is None:
                    raise KnowledgeAnalysisServiceError(
                        "KNOWLEDGE_ANALYSIS_WORKFLOW_UNAVAILABLE",
                        "knowledge analysis workflow definition is unavailable",
                    )
                created_at = datetime.now(UTC)
                request_document: dict[str, Any] = {
                    "schema_version": (
                        "knowledge-analysis-request/8.0"
                        if stable_identity_multimodal
                        else (
                            "knowledge-analysis-request/7.0"
                            if typed_identity_multimodal
                            else (
                                "knowledge-analysis-request/6.0"
                                if multimodal_document
                                else (
                                    "knowledge-analysis-request/5.0"
                                    if integrity_document
                                    else (
                                        "knowledge-analysis-request/4.0"
                                        if endpoint_typed_document
                                        else (
                                            "knowledge-analysis-request/3.0"
                                            if is_document_source
                                            else "knowledge-analysis-request/2.0"
                                        )
                                    )
                                )
                            )
                        )
                    ),
                    "analysis_request_id": new_knowledge_analysis_request_id(),
                    "source": source.model_dump(mode="json"),
                    "execution_preset_id": preset_logical.preset_id,
                    "execution_preset_revision_id": preset_revision.preset_revision_id,
                    "execution_preset_sha256": preset_revision.content_sha256,
                    "worker_proposal_schema_ref": (
                        "eom://schemas/knowledge/knowledge-analysis-worker-proposal/6.0"
                        if stable_identity_multimodal
                        else (
                            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/5.0"
                            if typed_identity_multimodal
                            else (
                                "eom://schemas/knowledge/knowledge-analysis-worker-proposal/4.0"
                                if multimodal_document
                                else (
                                    "eom://schemas/knowledge/knowledge-analysis-worker-proposal/3.0"
                                    if integrity_document
                                    else (
                                        "eom://schemas/knowledge/knowledge-analysis-worker-proposal/2.0"
                                        if endpoint_typed_document
                                        else "eom://schemas/knowledge/knowledge-analysis-worker-proposal/1.0"
                                    )
                                )
                            )
                        )
                    ),
                    "accepted_result_schema_ref": (
                        "eom://schemas/knowledge/knowledge-analysis-result/8.0"
                        if stable_identity_multimodal
                        else (
                            "eom://schemas/knowledge/knowledge-analysis-result/7.0"
                            if typed_identity_multimodal
                            else (
                                "eom://schemas/knowledge/knowledge-analysis-result/6.0"
                                if multimodal_document
                                else (
                                    "eom://schemas/knowledge/knowledge-analysis-result/5.0"
                                    if integrity_document
                                    else (
                                        "eom://schemas/knowledge/knowledge-analysis-result/4.0"
                                        if endpoint_typed_document
                                        else (
                                            "eom://schemas/knowledge/knowledge-analysis-result/3.0"
                                            if is_document_source
                                            else "eom://schemas/knowledge/knowledge-analysis-result/2.0"
                                        )
                                    )
                                )
                            )
                        )
                    ),
                    "predecessor_analysis_run_id": command.predecessor_analysis_run_id,
                    "prior_graph_snapshot": None,
                    "requested_outputs": list(
                        MULTIMODAL_REQUESTED_OUTPUTS if multimodal_document else REQUESTED_OUTPUTS
                    ),
                    "general_knowledge_mode": command.general_knowledge_mode,
                    "risk_policy_revision_id": policy.risk_policy_revision_id,
                    "created_at": _utc_json_timestamp(created_at),
                    "request_sha256": "sha256:" + "0" * 64,
                }
                request_document["request_sha256"] = content_sha256(
                    {
                        key: value
                        for key, value in request_document.items()
                        if key != "request_sha256"
                    }
                )
                request: KnowledgeAnalysisRequestContract
                if stable_identity_multimodal:
                    validate_contract("knowledge-analysis-request-v8", request_document)
                    request = KnowledgeAnalysisRequestV8.model_validate(request_document)
                elif typed_identity_multimodal:
                    validate_contract("knowledge-analysis-request-v7", request_document)
                    request = KnowledgeAnalysisRequestV7.model_validate(request_document)
                elif multimodal_document:
                    validate_contract("knowledge-analysis-request-v6", request_document)
                    request = KnowledgeAnalysisRequestV6.model_validate(request_document)
                elif integrity_document:
                    validate_contract("knowledge-analysis-request-v5", request_document)
                    request = KnowledgeAnalysisRequestV5.model_validate(request_document)
                elif endpoint_typed_document:
                    validate_contract("knowledge-analysis-request-v4", request_document)
                    request = KnowledgeAnalysisRequestV4.model_validate(request_document)
                elif is_document_source:
                    validate_contract("knowledge-analysis-request-v3", request_document)
                    request = KnowledgeAnalysisRequestV3.model_validate(request_document)
                else:
                    validate_contract("knowledge-analysis-request-v2", request_document)
                    request = KnowledgeAnalysisRequestV2.model_validate(request_document)
                workflow_request = WorkflowRequest(
                    request_name="KNOWLEDGE_ANALYSIS_REQUEST",
                    image_mode="skip",
                    analysis_request=request,
                )
                workflow, created = create_workflow_instance(
                    session,
                    definition=definition,
                    request=workflow_request,
                    idempotency_key=(f"knowledge-analysis:{request.analysis_request_id}"),
                    actor_type="human",
                    actor_id=command.requested_by,
                    runtime_context={"knowledge_analysis_request_sha256": request.request_sha256},
                )
                if not created:
                    raise KnowledgeAnalysisServiceError(
                        "KNOWLEDGE_ANALYSIS_CONCURRENCY_CONFLICT",
                        "knowledge analysis workflow identity already exists",
                    )
                plan = resolve_knowledge_analysis_plan(
                    session,
                    workflow_id=workflow.workflow_id,
                    workflow_definition_version=definition.definition_version,
                    workflow_definition_sha256=definition.definition_hash,
                    workflow_role_schema_version=workflow.role_schema_version,
                    request=request,
                    resolved_at=created_at,
                )
                context = dict(workflow.runtime_context)
                context["execution_plan"] = {
                    "plan_id": plan.plan_id,
                    "plan_sha256": plan.plan_sha256,
                    "preset_id": plan.preset_id,
                    "preset_revision_id": plan.preset_revision_id,
                }
                workflow.runtime_context = context
                run = KnowledgeAnalysisRunRecord(
                    analysis_run_id=new_knowledge_analysis_run_id(),
                    analysis_request_id=request.analysis_request_id,
                    predecessor_analysis_run_id=command.predecessor_analysis_run_id,
                    request_sha256=request.request_sha256,
                    submission_sha256=submission_sha256,
                    idempotency_key=command.idempotency_key,
                    canonical_request=request.model_dump(mode="json"),
                    source_kind=source.source_kind,
                    source_revision_id=(
                        source.source_file_id
                        if isinstance(source, ContentIntakeKnowledgeSourceV2)
                        else (
                            source.document_revision_id
                            if isinstance(
                                source,
                                (
                                    EducationalDocumentKnowledgeSourceV3,
                                    EducationalDocumentKnowledgeSourceV4,
                                ),
                            )
                            else source.item_revision_id
                        )
                    ),
                    source_file_id=getattr(source, "source_file_id", None),
                    item_id=getattr(source, "item_id", None),
                    item_revision_id=getattr(source, "item_revision_id", None),
                    educational_document_id=getattr(source, "document_id", None),
                    educational_document_revision_id=getattr(source, "document_revision_id", None),
                    source_artifact_id=source.artifact_member.artifact_id,
                    source_artifact_revision_id=source.artifact_member.artifact_revision_id,
                    source_sha256=source.artifact_member.sha256,
                    workflow_id=workflow.workflow_id,
                    plan_id=plan.plan_id,
                    platform_job_id=None,
                    preset_id=preset_logical.preset_id,
                    preset_revision_id=preset_revision.preset_revision_id,
                    risk_policy_revision_id=policy.risk_policy_revision_id,
                    risk_policy_sha256=policy.content_sha256,
                    state="REQUESTED",
                    lock_version=1,
                    created_by_operator_id=command.requested_by,
                    created_at=created_at,
                )
                session.add(run)
                session.flush()
                session.add(
                    KnowledgeAnalysisEventRecord(
                        analysis_run_id=run.analysis_run_id,
                        sequence=1,
                        event_type="ANALYSIS_REQUESTED",
                        prior_state=None,
                        new_state="REQUESTED",
                        actor_type="human",
                        actor_id=command.requested_by,
                        payload={
                            "request_sha256": request.request_sha256,
                            "predecessor_analysis_run_id": command.predecessor_analysis_run_id,
                        },
                    )
                )
                session.flush()
                self._transition(
                    session,
                    run,
                    "RESOLVED",
                    "ANALYSIS_REQUEST_RESOLVED",
                    actor_type="human",
                    actor_id=command.requested_by,
                    payload={"plan_id": plan.plan_id, "plan_sha256": plan.plan_sha256},
                )
                self._transition(
                    session,
                    run,
                    "QUEUED",
                    "ANALYSIS_WORKFLOW_QUEUED",
                    actor_type="human",
                    actor_id=command.requested_by,
                    payload={"workflow_id": workflow.workflow_id},
                )
                enqueue_command(
                    session,
                    workflow_id=workflow.workflow_id,
                    command_type=CommandType.START_WORKFLOW,
                    payload={},
                    actor_type="human",
                    actor_id=command.requested_by,
                    source="knowledge_analysis",
                    idempotency_key=f"start:{workflow.workflow_id}",
                )
                return self._projection(run)
        except KnowledgeAnalysisServiceError:
            raise
        except KnowledgeAnalysisSourceError as exc:
            raise KnowledgeAnalysisServiceError(exc.code, str(exc)) from exc
        except ControlPlaneError as exc:
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_PRESET_INCOMPATIBLE",
                "knowledge analysis execution plan could not be resolved",
            ) from exc
        except IntegrityError as exc:
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_CONCURRENCY_CONFLICT",
                "knowledge analysis request raced with another transaction",
            ) from exc
        except (ValidationError, ValueError) as exc:
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_REQUEST_INVALID",
                "knowledge analysis request could not be persisted",
            ) from exc

    def reconcile(
        self, command: ReconcileKnowledgeAnalysisCommand
    ) -> KnowledgeAnalysisApplicationResult:
        with transaction(self.sessions) as session:
            run = self._locked_run(session, command.analysis_run_id)
            if run.state in TERMINAL_RUN_STATES or run.state == "NEEDS_REVIEW":
                return self._projection(run)
            workflow = session.get(WorkflowInstanceRecord, run.workflow_id)
            if workflow is None:
                return self._fail(
                    session,
                    run,
                    "KNOWLEDGE_ANALYSIS_WORKFLOW_MISSING",
                    command.requested_by,
                )
            if workflow.state == WorkflowState.FAILED.value:
                return self._fail(
                    session,
                    run,
                    "KNOWLEDGE_ANALYSIS_WORKER_FAILED",
                    command.requested_by,
                )
            if workflow.state == WorkflowState.CANCELLED.value:
                self._transition(
                    session,
                    run,
                    "CANCELLED",
                    "ANALYSIS_CANCELLED",
                    actor_type="system",
                    actor_id=command.requested_by,
                )
                run.completed_at = datetime.now(UTC)
                return self._projection(run)
            if workflow.state != WorkflowState.COMPLETED.value:
                if workflow.state == WorkflowState.RUNNING.value and run.state == "QUEUED":
                    run.started_at = run.started_at or datetime.now(UTC)
                    self._transition(
                        session,
                        run,
                        "RUNNING",
                        "ANALYSIS_WORKFLOW_STARTED",
                        actor_type="system",
                        actor_id=command.requested_by,
                    )
                return self._projection(run)
            try:
                receipt, pointer = self._completed_proposal(session, run, workflow)
                policy = self.risk_policy(session, run.risk_policy_revision_id)
            except KnowledgeAnalysisServiceError as exc:
                return self._fail(session, run, exc.code, command.requested_by)
            if run.state != "VALIDATING":
                if run.state == "QUEUED":
                    self._transition(
                        session,
                        run,
                        "RUNNING",
                        "ANALYSIS_WORKFLOW_COMPLETED",
                        actor_type="system",
                        actor_id=command.requested_by,
                    )
                self._apply_proposal(run, receipt, pointer)
            try:
                proposal = resolve_knowledge_analysis_proposal(self.artifacts, receipt)
            except KnowledgeProposalResolutionError as exc:
                return self._fail(
                    session,
                    run,
                    (
                        "KNOWLEDGE_ANALYSIS_POINTER_INVALID"
                        if exc.kind == "POINTER_INVALID"
                        else "KNOWLEDGE_ANALYSIS_PROPOSAL_INVALID"
                    ),
                    command.requested_by,
                )
            try:
                validate_knowledge_analysis_proposal_ontology(proposal)
            except ValueError:
                return self._fail(
                    session,
                    run,
                    "KNOWLEDGE_ANALYSIS_ONTOLOGY_INVALID",
                    command.requested_by,
                )
            if run.state != "VALIDATING":
                self._transition(
                    session,
                    run,
                    "VALIDATING",
                    "ANALYSIS_PROPOSAL_VALIDATED",
                    actor_type="system",
                    actor_id=command.requested_by,
                    payload={
                        "proposal_artifact_revision_id": pointer.revision_id,
                        "content_set_sha256": receipt.content_set_sha256,
                    },
                )
            evaluation = evaluate_knowledge_analysis_risk(receipt, policy)
            if evaluation.requires_review:
                self._transition(
                    session,
                    run,
                    "NEEDS_REVIEW",
                    "ANALYSIS_REVIEW_REQUIRED",
                    actor_type="system",
                    actor_id=command.requested_by,
                    payload={"reason_codes": list(evaluation.reason_codes)},
                )
                return self._projection(run)
            run_id = run.analysis_run_id
        return self._accept(
            run_id,
            acceptance_mode="AUTO_POLICY",
            review_pointer=None,
            actor_id=command.requested_by,
        )

    def review(self, command: ReviewKnowledgeAnalysisCommand) -> KnowledgeAnalysisApplicationResult:
        submission_sha256 = content_sha256(
            command.model_dump(mode="json", exclude={"operation", "idempotency_key"})
        )
        replay = self._replay_review(command, submission_sha256)
        if replay is not None:
            return replay
        with transaction(self.sessions) as session:
            run = self._locked_run(session, command.analysis_run_id)
            existing = session.scalar(
                select(KnowledgeAnalysisReviewRecord).where(
                    KnowledgeAnalysisReviewRecord.idempotency_key == command.idempotency_key
                )
            )
            if existing is not None:
                if (
                    existing.analysis_run_id != run.analysis_run_id
                    or existing.submission_sha256 != submission_sha256
                ):
                    raise KnowledgeAnalysisServiceError(
                        "KNOWLEDGE_ANALYSIS_REVIEW_CONFLICT",
                        "knowledge analysis review idempotency key conflicts",
                    )
                return self._projection(run)
            if run.lock_version != command.expected_version:
                raise KnowledgeAnalysisServiceError(
                    "KNOWLEDGE_ANALYSIS_CONCURRENCY_CONFLICT",
                    "knowledge analysis run version is stale",
                )
            if run.state != "NEEDS_REVIEW":
                raise KnowledgeAnalysisServiceError(
                    "KNOWLEDGE_ANALYSIS_REVIEW_CONFLICT",
                    "knowledge analysis run is not awaiting review",
                )
            prior = session.scalar(
                select(KnowledgeAnalysisReviewRecord).where(
                    KnowledgeAnalysisReviewRecord.analysis_run_id == run.analysis_run_id
                )
            )
            if prior is not None:
                raise KnowledgeAnalysisServiceError(
                    "KNOWLEDGE_ANALYSIS_REVIEW_CONFLICT",
                    "knowledge analysis run already has a decision",
                )
            reviewer = session.get(OperatorRecord, command.decided_by)
            if reviewer is None or reviewer.status != "ACTIVE":
                raise KnowledgeAnalysisServiceError(
                    "KNOWLEDGE_ANALYSIS_REVIEWER_INVALID",
                    "knowledge analysis reviewer is absent or inactive",
                )
            policy = self.risk_policy(session, run.risk_policy_revision_id)
            request = _analysis_request(run.canonical_request)
            receipt = self._stored_receipt(session, run)
            decided_at = datetime.now(UTC)
            decision_data: dict[str, Any] = {
                "schema_version": "knowledge-analysis-review-decision/1.0",
                "decision_id": new_knowledge_analysis_decision_id(),
                "analysis_request_id": request.analysis_request_id,
                "proposal_artifact_id": run.proposal_artifact_id,
                "proposal_artifact_revision_id": run.proposal_artifact_revision_id,
                "proposal_content_set_sha256": receipt.content_set_sha256,
                "risk_policy_revision_id": policy.risk_policy_revision_id,
                "decision": command.decision,
                "decided_by_operator_id": command.decided_by,
                "notes": command.notes,
                "decided_at": _utc_json_timestamp(decided_at),
                "decision_sha256": "sha256:" + "0" * 64,
            }
            decision_data["decision_sha256"] = content_sha256(
                {key: value for key, value in decision_data.items() if key != "decision_sha256"}
            )
            validate_contract("knowledge-analysis-review-decision", decision_data)
            decision = KnowledgeAnalysisReviewDecision.model_validate(decision_data)
            run_id = run.analysis_run_id
        decision_artifact = self._commit_json_artifact(
            relative_path="evidence/review-decision.json",
            schema_ref="eom://schemas/knowledge/knowledge-analysis-review-decision/1.0",
            artifact_type="knowledge-analysis-review-decision",
            idempotency_key=f"knowledge-analysis-review:{run_id}",
            request={
                "analysis_run_id": run_id,
                "submission_sha256": submission_sha256,
            },
            result=decision.model_dump(mode="json"),
            protocol=_catalog_protocol(request),
        )
        stored_decision = self._artifact_result(
            decision_artifact,
            KnowledgeAnalysisReviewDecision,
            "knowledge-analysis-review-decision",
        )
        assert isinstance(stored_decision, KnowledgeAnalysisReviewDecision)
        if (
            stored_decision.analysis_request_id != decision.analysis_request_id
            or stored_decision.proposal_artifact_id != decision.proposal_artifact_id
            or stored_decision.proposal_artifact_revision_id
            != decision.proposal_artifact_revision_id
            or stored_decision.proposal_content_set_sha256 != decision.proposal_content_set_sha256
            or stored_decision.risk_policy_revision_id != decision.risk_policy_revision_id
            or stored_decision.decision != command.decision
            or stored_decision.decided_by_operator_id != command.decided_by
            or stored_decision.notes != command.notes
        ):
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_REVIEW_CONFLICT",
                "stored knowledge analysis decision differs from the reviewed input",
            )
        with transaction(self.sessions) as session:
            run = self._locked_run(session, run_id)
            policy = self.risk_policy(session, run.risk_policy_revision_id)
            existing = session.scalar(
                select(KnowledgeAnalysisReviewRecord).where(
                    KnowledgeAnalysisReviewRecord.analysis_run_id == run_id
                )
            )
            if existing is None:
                session.add(
                    KnowledgeAnalysisReviewRecord(
                        decision_id=stored_decision.decision_id,
                        analysis_run_id=run_id,
                        decision=stored_decision.decision,
                        idempotency_key=command.idempotency_key,
                        submission_sha256=submission_sha256,
                        decided_by_operator_id=stored_decision.decided_by_operator_id,
                        risk_policy_revision_id=policy.risk_policy_revision_id,
                        risk_policy_sha256=policy.content_sha256,
                        decision_sha256=stored_decision.decision_sha256,
                        decision_artifact_id=decision_artifact.artifact_id,
                        decision_artifact_revision_id=decision_artifact.revision_id,
                        decided_at=stored_decision.decided_at,
                    )
                )
                session.flush()
            elif existing.submission_sha256 != submission_sha256:
                raise KnowledgeAnalysisServiceError(
                    "KNOWLEDGE_ANALYSIS_REVIEW_CONFLICT",
                    "knowledge analysis review already has a different decision",
                )
            if stored_decision.decision == "REJECT":
                self._transition(
                    session,
                    run,
                    "REJECTED",
                    "ANALYSIS_REJECTED",
                    actor_type="human",
                    actor_id=command.decided_by,
                    payload={"decision_artifact_revision_id": decision_artifact.revision_id},
                )
                run.completed_at = stored_decision.decided_at
                return self._projection(run)
            review_pointer = KnowledgeArtifactMemberPointer(
                artifact_id=decision_artifact.artifact_id,
                artifact_revision_id=decision_artifact.revision_id,
                sha256=decision_artifact.content_hash,
                schema_ref="eom://schemas/knowledge/knowledge-analysis-review-decision/1.0",
                media_type="application/json",
                logical_name="review-decision.json",
                member_path="evidence/review-decision.json",
            )
        return self._accept(
            run_id,
            acceptance_mode="HUMAN_APPROVED",
            review_pointer=review_pointer,
            actor_id=command.decided_by,
        )

    def _replay_review(
        self,
        command: ReviewKnowledgeAnalysisCommand,
        submission_sha256: str,
    ) -> KnowledgeAnalysisApplicationResult | None:
        with self.sessions() as session:
            run = session.get(KnowledgeAnalysisRunRecord, command.analysis_run_id)
            existing = session.scalar(
                select(KnowledgeAnalysisReviewRecord).where(
                    KnowledgeAnalysisReviewRecord.idempotency_key == command.idempotency_key
                )
            )
            if existing is None:
                return None
            if (
                run is None
                or existing.analysis_run_id != run.analysis_run_id
                or existing.submission_sha256 != submission_sha256
            ):
                raise KnowledgeAnalysisServiceError(
                    "KNOWLEDGE_ANALYSIS_REVIEW_CONFLICT",
                    "knowledge analysis review idempotency key conflicts",
                )
            projection = self._projection(run)
            if existing.decision != "APPROVE" or run.state != "NEEDS_REVIEW":
                return projection
            revision = session.get(
                ArtifactRevisionRecord,
                existing.decision_artifact_revision_id,
            )
            if (
                revision is None
                or not revision.approved
                or revision.logical_artifact_id != existing.decision_artifact_id
                or revision.result.get("decision_sha256") != existing.decision_sha256
                or revision.manifest.get("artifact_type") != "knowledge-analysis-review-decision"
                or revision.manifest.get("primary_file") != "evidence/review-decision.json"
            ):
                raise KnowledgeAnalysisServiceError(
                    "KNOWLEDGE_ANALYSIS_REVIEW_CONFLICT",
                    "knowledge analysis review Artifact pointer is stale",
                )
            pointer = KnowledgeArtifactMemberPointer(
                artifact_id=existing.decision_artifact_id,
                artifact_revision_id=existing.decision_artifact_revision_id,
                sha256=revision.content_hash,
                schema_ref="eom://schemas/knowledge/knowledge-analysis-review-decision/1.0",
                media_type="application/json",
                logical_name="review-decision.json",
                member_path="evidence/review-decision.json",
            )
            actor_id = existing.decided_by_operator_id
        return self._accept(
            command.analysis_run_id,
            acceptance_mode="HUMAN_APPROVED",
            review_pointer=pointer,
            actor_id=actor_id,
        )

    def accept_validated_without_review(
        self,
        *,
        analysis_run_id: str,
        requested_by: str,
    ) -> KnowledgeAnalysisApplicationResult:
        """Accept a canonically valid proposal under the explicit automation policy.

        The run can reach this boundary only after proposal pointer, schema, Pydantic,
        and ontology validation.  It records a system policy action and never creates
        a human review decision.
        """

        return self._accept(
            analysis_run_id,
            acceptance_mode="AUTO_POLICY",
            review_pointer=None,
            actor_id=requested_by,
            auto_policy_review_override=True,
        )

    def _accept(
        self,
        run_id: str,
        *,
        acceptance_mode: Literal["AUTO_POLICY", "HUMAN_APPROVED"],
        review_pointer: KnowledgeArtifactMemberPointer | None,
        actor_id: str,
        auto_policy_review_override: bool = False,
    ) -> KnowledgeAnalysisApplicationResult:
        with self.sessions() as session:
            run = session.get(KnowledgeAnalysisRunRecord, run_id)
            if run is None:
                raise KnowledgeAnalysisServiceError(
                    "KNOWLEDGE_ANALYSIS_SOURCE_MISSING", "knowledge analysis run is missing"
                )
            if run.state == "ACCEPTED":
                return self._projection(run)
            allowed_states = (
                frozenset({"VALIDATING", "NEEDS_REVIEW"})
                if acceptance_mode == "AUTO_POLICY" and auto_policy_review_override
                else frozenset(
                    {"VALIDATING" if acceptance_mode == "AUTO_POLICY" else "NEEDS_REVIEW"}
                )
            )
            if run.state not in allowed_states:
                raise KnowledgeAnalysisServiceError(
                    "KNOWLEDGE_ANALYSIS_CONCURRENCY_CONFLICT",
                    "knowledge analysis acceptance state changed",
                )
            request = _analysis_request(run.canonical_request)
            receipt = self._stored_receipt(session, run)
            proposal_receipt_pointer = self._proposal_receipt_pointer(session, run)
            policy = self.risk_policy(session, run.risk_policy_revision_id)
            accepted_at = receipt.completed_at
            if acceptance_mode == "HUMAN_APPROVED":
                review = session.scalar(
                    select(KnowledgeAnalysisReviewRecord).where(
                        KnowledgeAnalysisReviewRecord.analysis_run_id == run_id
                    )
                )
                review_artifact = (
                    session.get(
                        ArtifactRevisionRecord,
                        review.decision_artifact_revision_id,
                    )
                    if review is not None
                    else None
                )
                if (
                    review is None
                    or review.decision != "APPROVE"
                    or review_pointer is None
                    or review.decision_artifact_id != review_pointer.artifact_id
                    or review.decision_artifact_revision_id != review_pointer.artifact_revision_id
                    or review_artifact is None
                    or not review_artifact.approved
                    or review_artifact.logical_artifact_id != review_pointer.artifact_id
                    or review_artifact.content_hash != review_pointer.sha256
                ):
                    raise KnowledgeAnalysisServiceError(
                        "KNOWLEDGE_ANALYSIS_REVIEW_CONFLICT",
                        "knowledge analysis approval pointer is inconsistent",
                    )
                accepted_at = review.decided_at
        stable_result_seed = content_sha256(
            {
                "analysis_request_id": request.analysis_request_id,
                "proposal_content_set_sha256": receipt.content_set_sha256,
                "risk_policy_revision_id": policy.risk_policy_revision_id,
                "acceptance_mode": acceptance_mode,
                "review_artifact_revision_id": (
                    review_pointer.artifact_revision_id if review_pointer is not None else None
                ),
            }
        ).removeprefix("sha256:")[:32]
        document_contract = _document_contract(request)
        endpoint_typed_document = _endpoint_typed_document_contract(request)
        integrity_document = _integrity_document_contract(request)
        multimodal_document = _multimodal_document_contract(request)
        typed_identity_multimodal = _typed_identity_multimodal_contract(request)
        stable_identity_multimodal = _stable_identity_multimodal_contract(request)
        result_data: dict[str, Any] = {
            "schema_version": (
                "knowledge-analysis-result/8.0"
                if stable_identity_multimodal
                else (
                    "knowledge-analysis-result/7.0"
                    if typed_identity_multimodal
                    else (
                        "knowledge-analysis-result/6.0"
                        if multimodal_document
                        else (
                            "knowledge-analysis-result/5.0"
                            if integrity_document
                            else (
                                "knowledge-analysis-result/4.0"
                                if endpoint_typed_document
                                else (
                                    "knowledge-analysis-result/3.0"
                                    if document_contract
                                    else "knowledge-analysis-result/2.0"
                                )
                            )
                        )
                    )
                )
            ),
            "analysis_result_id": f"knowledgeanalysisresult_{stable_result_seed}",
            "analysis_request_id": request.analysis_request_id,
            "analysis_request_sha256": request.request_sha256,
            "source": request.source.model_dump(mode="json"),
            "status": "ACCEPTED",
            "proposal_receipt": proposal_receipt_pointer.model_dump(mode="json"),
            "proposal_content_set_sha256": receipt.content_set_sha256,
            "risk_policy_revision_id": policy.risk_policy_revision_id,
            "acceptance_mode": acceptance_mode,
            "review_decision": (
                review_pointer.model_dump(mode="json") if review_pointer is not None else None
            ),
            "counts": receipt.counts.model_dump(mode="json"),
            "general_knowledge_used": receipt.general_knowledge_used,
            "minimum_confidence_milli": receipt.minimum_confidence_milli,
            "blocking_ambiguity_count": receipt.blocking_ambiguity_count,
            "accepted_at": _utc_json_timestamp(accepted_at),
            "result_sha256": "sha256:" + "0" * 64,
        }
        result_data["result_sha256"] = content_sha256(
            {key: value for key, value in result_data.items() if key != "result_sha256"}
        )
        if stable_identity_multimodal:
            result_schema_name = "knowledge-analysis-result-v8"
            result_schema_ref = "eom://schemas/knowledge/knowledge-analysis-result/8.0"
        elif typed_identity_multimodal:
            result_schema_name = "knowledge-analysis-result-v7"
            result_schema_ref = "eom://schemas/knowledge/knowledge-analysis-result/7.0"
        elif multimodal_document:
            result_schema_name = "knowledge-analysis-result-v6"
            result_schema_ref = "eom://schemas/knowledge/knowledge-analysis-result/6.0"
        elif integrity_document:
            result_schema_name = "knowledge-analysis-result-v5"
            result_schema_ref = "eom://schemas/knowledge/knowledge-analysis-result/5.0"
        elif endpoint_typed_document:
            result_schema_name = "knowledge-analysis-result-v4"
            result_schema_ref = "eom://schemas/knowledge/knowledge-analysis-result/4.0"
        elif document_contract:
            result_schema_name = "knowledge-analysis-result-v3"
            result_schema_ref = "eom://schemas/knowledge/knowledge-analysis-result/3.0"
        else:
            result_schema_name = "knowledge-analysis-result-v2"
            result_schema_ref = "eom://schemas/knowledge/knowledge-analysis-result/2.0"
        validate_contract(result_schema_name, result_data)
        result: KnowledgeAnalysisResultContract
        if stable_identity_multimodal:
            result = KnowledgeAnalysisResultV8.model_validate(result_data)
        elif typed_identity_multimodal:
            result = KnowledgeAnalysisResultV7.model_validate(result_data)
        elif multimodal_document:
            result = KnowledgeAnalysisResultV6.model_validate(result_data)
        elif integrity_document:
            result = KnowledgeAnalysisResultV5.model_validate(result_data)
        elif endpoint_typed_document:
            result = KnowledgeAnalysisResultV4.model_validate(result_data)
        elif document_contract:
            result = KnowledgeAnalysisResultV3.model_validate(result_data)
        else:
            result = KnowledgeAnalysisResultV2.model_validate(result_data)
        artifact = self._commit_json_artifact(
            relative_path="evidence/accepted-result.json",
            schema_ref=result_schema_ref,
            artifact_type="knowledge-analysis-accepted-result",
            idempotency_key=f"knowledge-analysis-accepted:{run_id}",
            request={
                "analysis_run_id": run_id,
                "analysis_request_sha256": request.request_sha256,
                "proposal_content_set_sha256": receipt.content_set_sha256,
                "acceptance_mode": acceptance_mode,
                "review_artifact_revision_id": (
                    review_pointer.artifact_revision_id if review_pointer is not None else None
                ),
            },
            result=result.model_dump(mode="json"),
            protocol=_catalog_protocol(request),
        )
        result_model: (
            type[KnowledgeAnalysisResultV2]
            | type[KnowledgeAnalysisResultV3]
            | type[KnowledgeAnalysisResultV4]
            | type[KnowledgeAnalysisResultV5]
            | type[KnowledgeAnalysisResultV6]
            | type[KnowledgeAnalysisResultV7]
            | type[KnowledgeAnalysisResultV8]
        )
        if stable_identity_multimodal:
            result_model = KnowledgeAnalysisResultV8
        elif typed_identity_multimodal:
            result_model = KnowledgeAnalysisResultV7
        elif multimodal_document:
            result_model = KnowledgeAnalysisResultV6
        elif integrity_document:
            result_model = KnowledgeAnalysisResultV5
        elif endpoint_typed_document:
            result_model = KnowledgeAnalysisResultV4
        elif document_contract:
            result_model = KnowledgeAnalysisResultV3
        else:
            result_model = KnowledgeAnalysisResultV2
        stored_result = self._artifact_result(artifact, result_model, result_schema_name)
        assert isinstance(
            stored_result,
            (
                KnowledgeAnalysisResultV2,
                KnowledgeAnalysisResultV3,
                KnowledgeAnalysisResultV4,
                KnowledgeAnalysisResultV5,
                KnowledgeAnalysisResultV6,
                KnowledgeAnalysisResultV7,
                KnowledgeAnalysisResultV8,
            ),
        )
        if (
            stored_result.analysis_request_sha256 != request.request_sha256
            or stored_result.proposal_content_set_sha256 != receipt.content_set_sha256
            or stored_result.acceptance_mode != acceptance_mode
        ):
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_ARTIFACT_COMMIT_FAILED",
                "accepted result Artifact does not match the pinned analysis",
            )
        with transaction(self.sessions) as session:
            run = self._locked_run(session, run_id)
            if run.state == "ACCEPTED":
                if run.accepted_result_artifact_revision_id != artifact.revision_id:
                    raise KnowledgeAnalysisServiceError(
                        "KNOWLEDGE_ANALYSIS_REVIEW_CONFLICT",
                        "knowledge analysis accepted result pointer conflicts",
                    )
                return self._projection(run)
            expected_states = (
                frozenset({"VALIDATING", "NEEDS_REVIEW"})
                if acceptance_mode == "AUTO_POLICY" and auto_policy_review_override
                else frozenset(
                    {"VALIDATING" if acceptance_mode == "AUTO_POLICY" else "NEEDS_REVIEW"}
                )
            )
            if run.state not in expected_states:
                raise KnowledgeAnalysisServiceError(
                    "KNOWLEDGE_ANALYSIS_CONCURRENCY_CONFLICT",
                    "knowledge analysis changed during accepted result commit",
                )
            run.accepted_result_artifact_id = artifact.artifact_id
            run.accepted_result_artifact_revision_id = artifact.revision_id
            run.accepted_result_sha256 = artifact.content_hash
            run.completed_at = stored_result.accepted_at
            self._transition(
                session,
                run,
                "ACCEPTED",
                "ANALYSIS_ACCEPTED",
                actor_type=("system" if acceptance_mode == "AUTO_POLICY" else "human"),
                actor_id=actor_id,
                payload={
                    "acceptance_mode": acceptance_mode,
                    "review_requirement_overridden": auto_policy_review_override,
                    "accepted_result_artifact_revision_id": artifact.revision_id,
                },
            )
            return self._projection(run)

    def _commit_json_artifact(
        self,
        *,
        relative_path: str,
        schema_ref: str,
        artifact_type: str,
        idempotency_key: str,
        request: dict[str, Any],
        result: dict[str, Any],
        protocol: tuple[str, str] = (
            KNOWLEDGE_ANALYSIS_CATALOG_PROTOCOL,
            KNOWLEDGE_ANALYSIS_CATALOG_SCHEMA_HASH,
        ),
    ) -> CatalogArtifact:
        try:
            with tempfile.TemporaryDirectory(
                prefix="knowledge-analysis.", dir=self.settings.staging_root
            ) as raw_directory:
                root = Path(raw_directory)
                source = root / Path(relative_path).name
                source.write_bytes(canonical_json_bytes(result))
                source.chmod(0o640)
                return self.artifacts.commit_file_set(
                    files={relative_path: source},
                    primary_file=relative_path,
                    artifact_type=artifact_type,
                    idempotency_key=idempotency_key,
                    request=request,
                    result=result,
                    file_metadata={
                        relative_path: {
                            "schema_ref": schema_ref,
                            "media_type": "application/json",
                        }
                    },
                    manifest_version="knowledge-analysis-file-set/1.0",
                    protocol_version=protocol[0],
                    protocol_schema_hash=protocol[1],
                )
        except KnowledgeAnalysisServiceError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_ARTIFACT_COMMIT_FAILED",
                "knowledge analysis Artifact commit failed",
            ) from exc

    def _artifact_result(
        self,
        artifact: CatalogArtifact,
        model: type[
            KnowledgeAnalysisReviewDecision
            | KnowledgeAnalysisResultV2
            | KnowledgeAnalysisResultV3
            | KnowledgeAnalysisResultV4
            | KnowledgeAnalysisResultV5
            | KnowledgeAnalysisResultV6
            | KnowledgeAnalysisResultV7
            | KnowledgeAnalysisResultV8
        ],
        schema_name: str,
    ) -> (
        KnowledgeAnalysisReviewDecision
        | KnowledgeAnalysisResultV2
        | KnowledgeAnalysisResultV3
        | KnowledgeAnalysisResultV4
        | KnowledgeAnalysisResultV5
        | KnowledgeAnalysisResultV6
        | KnowledgeAnalysisResultV7
        | KnowledgeAnalysisResultV8
    ):
        with self.sessions() as session:
            revision = session.get(ArtifactRevisionRecord, artifact.revision_id)
            if (
                revision is None
                or revision.logical_artifact_id != artifact.artifact_id
                or revision.content_hash != artifact.content_hash
                or not revision.approved
            ):
                raise KnowledgeAnalysisServiceError(
                    "KNOWLEDGE_ANALYSIS_ARTIFACT_COMMIT_FAILED",
                    "knowledge analysis Artifact pointer does not resolve",
                )
            validate_contract(schema_name, revision.result)
            return model.model_validate(revision.result)

    def _completed_proposal(
        self,
        session: Session,
        run: KnowledgeAnalysisRunRecord,
        workflow: WorkflowInstanceRecord,
    ) -> tuple[KnowledgeAnalysisReceiptContract, ArtifactPointer]:
        final = workflow.runtime_context.get("final_pointer_manifest")
        raw_pointer = final.get("analysis_proposal") if isinstance(final, dict) else None
        try:
            pointer = ArtifactPointer.model_validate(raw_pointer)
        except ValidationError as exc:
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_POINTER_INVALID",
                "completed workflow has no valid analysis proposal pointer",
            ) from exc
        request = _analysis_request(run.canonical_request)
        expected_result_schema = _proposal_result_schema(
            request, workflow_version=workflow.definition_version
        )
        if pointer.result_schema != expected_result_schema:
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_POINTER_INVALID",
                "completed workflow proposal schema is incompatible",
            )
        logical = session.get(ArtifactRecord, pointer.logical_artifact_id)
        revision = session.get(ArtifactRevisionRecord, pointer.revision_id)
        job = session.get(JobRecord, pointer.job_id)
        _, receipt_schema_ref = _proposal_receipt_schema(request)
        if (
            logical is None
            or revision is None
            or job is None
            or not logical.approved
            or not revision.approved
            or revision.logical_artifact_id != pointer.logical_artifact_id
            or revision.job_id != pointer.job_id
            or job.status != "SUCCEEDED"
            or revision.content_hash != pointer.content_hash
            or revision.manifest.get("artifact_type") != "knowledge-analysis-proposal"
            or revision.manifest.get("primary_file") != "normalized/proposal-receipt.json"
        ):
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_POINTER_INVALID",
                "analysis proposal Artifact pointer is stale",
            )
        files = revision.manifest.get("files")
        entries = (
            [
                value
                for value in files
                if isinstance(value, dict)
                and value.get("file_name") == "normalized/proposal-receipt.json"
            ]
            if isinstance(files, list)
            else []
        )
        if (
            len(entries) != 1
            or entries[0].get("sha256") != pointer.content_hash
            or entries[0].get("media_type") != "application/json"
            or entries[0].get("schema_ref") != receipt_schema_ref
        ):
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_POINTER_INVALID",
                "analysis proposal receipt member is invalid",
            )
        receipt = _receipt_contract(revision.result, request)
        if (
            receipt.analysis_request_id != run.analysis_request_id
            or receipt.source != request.source
        ):
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_POINTER_INVALID",
                "analysis proposal receipt does not match its request",
            )
        return receipt, pointer

    def _stored_receipt(
        self, session: Session, run: KnowledgeAnalysisRunRecord
    ) -> KnowledgeAnalysisReceiptContract:
        if (
            run.proposal_artifact_id is None
            or run.proposal_artifact_revision_id is None
            or run.proposal_content_set_sha256 is None
        ):
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_POINTER_INVALID", "analysis proposal pointer is incomplete"
            )
        revision = session.get(ArtifactRevisionRecord, run.proposal_artifact_revision_id)
        if (
            revision is None
            or not revision.approved
            or revision.logical_artifact_id != run.proposal_artifact_id
            or revision.manifest.get("artifact_type") != "knowledge-analysis-proposal"
            or revision.manifest.get("primary_file") != "normalized/proposal-receipt.json"
        ):
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_POINTER_INVALID", "analysis proposal pointer is stale"
            )
        request = _analysis_request(run.canonical_request)
        receipt = _receipt_contract(revision.result, request)
        if (
            sha256_bytes(canonical_json_bytes(receipt)) != revision.content_hash
            or receipt.analysis_request_id != run.analysis_request_id
            or receipt.analysis_request_id != request.analysis_request_id
            or receipt.source != request.source
            or receipt.content_set_sha256 != run.proposal_content_set_sha256
        ):
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_POINTER_INVALID", "analysis proposal receipt hash differs"
            )
        return receipt

    def _proposal_receipt_pointer(
        self, session: Session, run: KnowledgeAnalysisRunRecord
    ) -> KnowledgeProposalArtifactMember:
        assert run.proposal_artifact_id is not None
        assert run.proposal_artifact_revision_id is not None
        revision = session.get(ArtifactRevisionRecord, run.proposal_artifact_revision_id)
        if (
            revision is None
            or not revision.approved
            or revision.logical_artifact_id != run.proposal_artifact_id
            or revision.manifest.get("artifact_type") != "knowledge-analysis-proposal"
            or revision.manifest.get("primary_file") != "normalized/proposal-receipt.json"
        ):
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_POINTER_INVALID", "proposal receipt Artifact is missing"
            )
        files = revision.manifest.get("files")
        entries = (
            [
                value
                for value in files
                if isinstance(value, dict)
                and value.get("file_name") == "normalized/proposal-receipt.json"
            ]
            if isinstance(files, list)
            else []
        )
        if len(entries) != 1:
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_POINTER_INVALID", "proposal receipt member is missing"
            )
        entry = entries[0]
        request = _analysis_request(run.canonical_request)
        _, receipt_schema_ref = _proposal_receipt_schema(request)
        if (
            entry.get("sha256") != revision.content_hash
            or entry.get("bytes") != revision.content_bytes
            or entry.get("schema_ref") != receipt_schema_ref
            or entry.get("media_type") != "application/json"
        ):
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_POINTER_INVALID",
                "proposal receipt member metadata is inconsistent",
            )
        return KnowledgeProposalArtifactMember(
            artifact_id=run.proposal_artifact_id,
            artifact_revision_id=run.proposal_artifact_revision_id,
            member_path="normalized/proposal-receipt.json",
            sha256=revision.content_hash,
            bytes=revision.content_bytes,
            schema_ref=receipt_schema_ref,
            media_type="application/json",
            logical_name="proposal-receipt.json",
        )

    def _resolve_source(
        self, session: Session, command: CreateKnowledgeAnalysisCommand
    ) -> KnowledgeAnalysisSourceContract:
        if isinstance(command.source, ContentIntakeKnowledgeAnalysisSelection):
            return resolve_content_intake_source(
                session,
                intake_batch_id=command.source.intake_batch_id,
                source_file_id=command.source.source_file_id,
                source_class=command.source.source_class,
            )
        if isinstance(command.source, ApprovedItemKnowledgeAnalysisSelection):
            return resolve_approved_item_source(
                session,
                item_revision_id=command.source.item_revision_id,
                source_class=command.source.source_class,
            )
        if isinstance(command.source, EducationalDocumentKnowledgeAnalysisSelection):
            return resolve_educational_document_source(
                session,
                self.artifacts,
                document_revision_id=command.source.document_revision_id,
                source_class=command.source.source_class,
                first_physical_page=command.source.first_physical_page,
                last_physical_page=command.source.last_physical_page,
                curriculum_unit_keys=command.source.curriculum_unit_keys,
            )
        raise KnowledgeAnalysisSourceError(
            "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE", "knowledge analysis source kind is invalid"
        )

    @staticmethod
    def retry_predecessor(
        session: Session,
        command: CreateKnowledgeAnalysisCommand,
        source: KnowledgeAnalysisSourceContract,
    ) -> KnowledgeAnalysisRunRecord | None:
        predecessor_id = command.predecessor_analysis_run_id
        if predecessor_id is None:
            return None
        predecessor = session.scalar(
            select(KnowledgeAnalysisRunRecord)
            .where(KnowledgeAnalysisRunRecord.analysis_run_id == predecessor_id)
            .with_for_update()
        )
        if predecessor is None:
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_SOURCE_MISSING",
                "knowledge analysis predecessor does not exist",
            )
        if predecessor.state not in {"FAILED", "REJECTED", "CANCELLED"}:
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_RETRY_INVALID",
                "knowledge analysis predecessor is not retryable",
            )
        prior_request = _analysis_request(predecessor.canonical_request)
        if (
            prior_request.source != source
            or prior_request.general_knowledge_mode != command.general_knowledge_mode
            or prior_request.risk_policy_revision_id != command.risk_policy_revision_id
        ):
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_RETRY_INVALID",
                "knowledge analysis retry dependencies differ from the predecessor",
            )
        return predecessor

    @staticmethod
    def published_preset(
        session: Session, preset_key: str
    ) -> tuple[ExecutionPresetRecord, ExecutionPresetRevisionRecord]:
        logical = session.scalar(
            select(ExecutionPresetRecord).where(ExecutionPresetRecord.preset_key == preset_key)
        )
        if logical is None or logical.state != "ACTIVE" or logical.current_revision_id is None:
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_PRESET_INCOMPATIBLE",
                "knowledge analysis preset is not published",
            )
        revision = session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
        if (
            revision is None
            or revision.preset_id != logical.preset_id
            or revision.state != "RELEASED"
        ):
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_PRESET_INCOMPATIBLE",
                "knowledge analysis preset pointer is stale",
            )
        preset = ExecutionPresetRevision.model_validate(revision.canonical_document)
        if preset.content_sha256 != revision.content_sha256:
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_PRESET_INCOMPATIBLE",
                "knowledge analysis preset hash differs",
            )
        return logical, revision

    @staticmethod
    def pinned_preset(
        session: Session,
        *,
        preset_key: str,
        preset_id: str,
        preset_revision_id: str,
    ) -> tuple[ExecutionPresetRecord, ExecutionPresetRevisionRecord]:
        logical = session.get(ExecutionPresetRecord, preset_id)
        revision = session.get(ExecutionPresetRevisionRecord, preset_revision_id)
        if (
            logical is None
            or logical.preset_key != preset_key
            or logical.state != "ACTIVE"
            or revision is None
            or revision.preset_id != preset_id
            or revision.state != "RELEASED"
        ):
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_PRESET_INCOMPATIBLE",
                "knowledge analysis retry preset pointer is stale",
            )
        preset = ExecutionPresetRevision.model_validate(revision.canonical_document)
        if preset.content_sha256 != revision.content_sha256:
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_PRESET_INCOMPATIBLE",
                "knowledge analysis retry preset hash differs",
            )
        return logical, revision

    @staticmethod
    def risk_policy(session: Session, revision_id: str) -> KnowledgeAnalysisRiskPolicy:
        record = session.get(KnowledgeAnalysisRiskPolicyRevisionRecord, revision_id)
        if record is None or record.state != "RELEASED":
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_POLICY_MISSING",
                "knowledge analysis risk policy is unavailable",
            )
        validate_contract("knowledge-analysis-risk-policy", record.canonical_document)
        policy = KnowledgeAnalysisRiskPolicy.model_validate(record.canonical_document)
        if policy.content_sha256 != record.content_sha256:
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_POLICY_STALE",
                "knowledge analysis risk policy hash differs",
            )
        return policy

    @staticmethod
    def _apply_proposal(
        run: KnowledgeAnalysisRunRecord,
        receipt: KnowledgeAnalysisReceiptContract,
        pointer: ArtifactPointer,
    ) -> None:
        run.platform_job_id = pointer.job_id
        run.proposal_artifact_id = pointer.logical_artifact_id
        run.proposal_artifact_revision_id = pointer.revision_id
        run.proposal_content_set_sha256 = receipt.content_set_sha256
        run.anchor_count = receipt.counts.anchors
        run.node_count = receipt.counts.nodes
        run.edge_count = receipt.counts.edges
        run.claim_count = receipt.counts.claims
        run.component_count = receipt.counts.component_observations
        run.ambiguity_count = receipt.counts.ambiguities

    def _fail(
        self,
        session: Session,
        run: KnowledgeAnalysisRunRecord,
        code: str,
        actor_id: str,
    ) -> KnowledgeAnalysisApplicationResult:
        run.error_code = code
        run.error_summary = "knowledge analysis execution failed"
        run.completed_at = datetime.now(UTC)
        self._transition(
            session,
            run,
            "FAILED",
            "ANALYSIS_FAILED",
            actor_type="system",
            actor_id=actor_id,
            payload={"error_code": code},
        )
        return self._projection(run)

    @staticmethod
    def _locked_run(session: Session, run_id: str) -> KnowledgeAnalysisRunRecord:
        run = session.scalar(
            select(KnowledgeAnalysisRunRecord)
            .where(KnowledgeAnalysisRunRecord.analysis_run_id == run_id)
            .with_for_update()
        )
        if run is None:
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_RUN_NOT_FOUND", "knowledge analysis run does not exist"
            )
        return run

    @staticmethod
    def _transition(
        session: Session,
        run: KnowledgeAnalysisRunRecord,
        new_state: str,
        event_type: str,
        *,
        actor_type: str,
        actor_id: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        prior = run.state
        if prior == new_state:
            return
        allowed = {
            "REQUESTED": {"RESOLVED", "FAILED", "CANCELLED"},
            "RESOLVED": {"QUEUED", "FAILED", "CANCELLED"},
            "QUEUED": {"RUNNING", "FAILED", "CANCELLED"},
            "RUNNING": {"VALIDATING", "FAILED", "CANCELLED"},
            "VALIDATING": {"NEEDS_REVIEW", "ACCEPTED", "FAILED", "CANCELLED"},
            "NEEDS_REVIEW": {"ACCEPTED", "REJECTED", "FAILED", "CANCELLED"},
            "ACCEPTED": set(),
            "REJECTED": set(),
            "FAILED": set(),
            "CANCELLED": set(),
        }
        if new_state not in allowed.get(prior, set()):
            raise KnowledgeAnalysisServiceError(
                "KNOWLEDGE_ANALYSIS_CONCURRENCY_CONFLICT",
                "knowledge analysis state transition is invalid",
            )
        # The aggregate may already carry state-dependent fields (for example
        # accepted-result pointers). Keep those changes pending until state,
        # lock version, and the append-only event are ready for one flush.
        with session.no_autoflush:
            sequence = session.scalar(
                select(func.coalesce(func.max(KnowledgeAnalysisEventRecord.sequence), 0)).where(
                    KnowledgeAnalysisEventRecord.analysis_run_id == run.analysis_run_id
                )
            )
        run.state = new_state
        run.lock_version += 1
        session.add(
            KnowledgeAnalysisEventRecord(
                analysis_run_id=run.analysis_run_id,
                sequence=int(sequence or 0) + 1,
                event_type=event_type,
                prior_state=prior,
                new_state=new_state,
                actor_type=actor_type,
                actor_id=actor_id,
                payload=payload or {},
            )
        )
        session.flush()

    @staticmethod
    def _projection(run: KnowledgeAnalysisRunRecord) -> KnowledgeAnalysisApplicationResult:
        return KnowledgeAnalysisApplicationResult(
            analysis_run_id=run.analysis_run_id,
            workflow_id=run.workflow_id,
            state=cast(
                Literal[
                    "REQUESTED",
                    "RESOLVED",
                    "QUEUED",
                    "RUNNING",
                    "VALIDATING",
                    "NEEDS_REVIEW",
                    "ACCEPTED",
                    "REJECTED",
                    "FAILED",
                    "CANCELLED",
                ],
                run.state,
            ),
            resource_version=run.lock_version,
            proposal_artifact_revision_id=run.proposal_artifact_revision_id,
            accepted_result_artifact_revision_id=run.accepted_result_artifact_revision_id,
        )
