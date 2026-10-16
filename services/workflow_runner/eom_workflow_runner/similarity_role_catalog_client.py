"""Ordinary runner adapter: exact local expectations → fixed Catalog materialization RPC."""

from __future__ import annotations

import grp
import pwd
from pathlib import Path

from eom_catalog_contracts import CATALOG_APPLICATION_SOCKET_PATH
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.similarity_context import SimilarityContextRequest
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_catalog_contracts.workflow_similarity_read import (
    MAX_WORKFLOW_SIMILARITY_REPLY_BYTES,
    MAX_WORKFLOW_SIMILARITY_REQUEST_BYTES,
    WorkflowSimilarityReadReply,
    WorkflowSimilarityReadRequest,
    WorkflowSimilarityRoleSelection,
    validate_workflow_similarity_read_reply,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    exchange_chat_frame,
)
from eom_orchestrator.similarity_materialization import (
    SimilarityMaterializationContext,
    SimilarityWorkspaceMaterials,
)
from eom_workflow.models import WorkerRequest
from eom_workflow.similarity_control import (
    SupportedSimilarityExecutionPlan,
    validate_similarity_original_source,
    validate_similarity_plan_context,
    validate_similarity_plan_request,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.orm import Session

from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.reference_query_consumer_read import (
    require_completed_query_selection_metadata,
)
from eom_workflow_runner.similarity_role_preparation import (
    SIMILARITY_QUERY_CONTEXT_KEY,
    _bind_role,
)


class CatalogRoleSimilarityMaterialsReader:
    """Operation-local pins, no cached source response, privileged engine or actor override."""

    def __init__(
        self,
        selection: WorkflowSimilarityRoleSelection,
        *,
        expected_operator_id: str,
        endpoint: ChatSocketEndpoint | None = None,
    ) -> None:
        self.selection = WorkflowSimilarityRoleSelection.model_validate(selection)
        self.expected_operator_id = expected_operator_id
        self.endpoint = endpoint

    def resolve(
        self,
        session: Session,
        *,
        plan: SupportedSimilarityExecutionPlan,
        operator_id: str,
        request: SimilarityContextRequest,
        original_source: PopulationSource,
        canonical_artifact_root: Path,
        authorized_artifact_revision_ids: frozenset[str],
    ) -> SimilarityWorkspaceMaterials:
        # The path is intentionally never dereferenced by this adapter. Catalog
        # resolves its own fixed canonical root and independently checks sources.
        if (
            operator_id != self.expected_operator_id
            or plan.workflow_id != self.selection.workflow_id
            or plan.plan_id != self.selection.plan_id
            or plan.plan_sha256 != self.selection.plan_sha256
            or plan.similarity_delivery.context_member.artifact_revision_id
            not in authorized_artifact_revision_ids
        ):
            raise ControlPlaneError(
                "CONTROL_SIMILARITY_CONTEXT_INVALID", "local role materialization differs"
            )
        try:
            validate_similarity_plan_request(plan, request)
            wire = WorkflowSimilarityReadRequest(
                schema_version="system-rag-workflow-similarity-read-request/1.0",
                operation="READ_WORKFLOW_SIMILARITY_MATERIALS",
                selection=self.selection,
            )
            endpoint = self.endpoint or ChatSocketEndpoint(
                Path(CATALOG_APPLICATION_SOCKET_PATH),
                pwd.getpwnam("eom-catalog-manager").pw_uid,
                grp.getgrnam("eom-api").gr_gid,
            )
            raw = exchange_chat_frame(
                endpoint,
                wire.model_dump(mode="json"),
                request_limit=MAX_WORKFLOW_SIMILARITY_REQUEST_BYTES,
                reply_limit=MAX_WORKFLOW_SIMILARITY_REPLY_BYTES,
                timeout=30.0,
            )
            reply = WorkflowSimilarityReadReply.model_validate(raw)
            validate_workflow_similarity_read_reply(wire, reply, expected_operator_id=operator_id)
            if reply.status == "FAILED":
                raise ControlPlaneError(
                    "CONTROL_SIMILARITY_AUTHORITY_DENIED"
                    if reply.error_code in {"SOURCE_ACCESS_DENIED", "SOURCE_REVOKED"}
                    else "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE"
                    if reply.error_code
                    in {"AUTHORITY_UNAVAILABLE", "WORKFLOW_SIMILARITY_UNAVAILABLE"}
                    else "CONTROL_SIMILARITY_CONTEXT_INVALID",
                    "Catalog current role materials unavailable",
                )
            assert reply.context is not None and reply.materials is not None
            validate_similarity_plan_context(plan, reply.context)
            validate_similarity_original_source(plan, reply.context, original_source)
            return SimilarityWorkspaceMaterials(
                canonical_json_bytes(reply.context.model_dump(mode="json")),
                canonical_json_bytes(reply.materials.model_dump(mode="json")),
            )
        except (ChatTransportError, KeyError, OSError):
            raise ControlPlaneError(
                "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE", "Catalog role reader unavailable"
            ) from None
        except (ValueError, TypeError, SchemaError, RecursionError):
            raise ControlPlaneError(
                "CONTROL_SIMILARITY_CONTEXT_INVALID", "Catalog role reply differs"
            ) from None


class CatalogSocketSimilarityRoleContextProvider:
    """Metadata expectations in the app root; actual source authority remains in Catalog."""

    def __init__(self, endpoint: ChatSocketEndpoint | None = None) -> None:
        self.endpoint = endpoint

    def prepare(
        self,
        session: Session,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: WorkerRequest,
    ) -> SimilarityMaterializationContext | None:
        binding = _bind_role(session, workflow, step, request)
        if binding is None:
            return None
        try:
            query = CompletedSimilarityQuerySelection.model_validate(
                binding.workflow.runtime_context[SIMILARITY_QUERY_CONTEXT_KEY]
            )
            caller = EmbeddingRegistryCaller(binding.workflow.created_actor_id)
            row = session.get(WorkflowInstanceRecord, query.workflow_id, populate_existing=True)
            original = require_completed_query_selection_metadata(row, caller, query)
            validate_similarity_plan_request(binding.plan, original.context_request)
            selection = WorkflowSimilarityRoleSelection(
                workflow_id=binding.workflow.workflow_id,
                step_run_id=step.step_run_id,
                plan_id=binding.plan.plan_id,
                plan_sha256=binding.plan.plan_sha256,
                query=query,
            )
            return SimilarityMaterializationContext(
                workflow_id=binding.workflow.workflow_id,
                operator_id=caller.operator_id,
                request=original.context_request,
                reader=CatalogRoleSimilarityMaterialsReader(
                    selection, expected_operator_id=caller.operator_id, endpoint=self.endpoint
                ),
            )
        except (
            ValueError,
            TypeError,
            KeyError,
            SchemaError,
            SimilarityContextReadError,
            EmbeddingRegistryError,
        ):
            raise ControlPlaneError(
                "CONTROL_SIMILARITY_CONTEXT_INVALID", "stored role/query expectations differ"
            ) from None
