"""Public role expectations → existing runner-only Catalog UDS; no runner NAS reads."""

from __future__ import annotations

import grp
import pwd
from pathlib import Path

from eom_catalog_contracts import CATALOG_APPLICATION_SOCKET_PATH
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.public_workflow_similarity_read import (
    PublicWorkflowSimilarityReadReply,
    PublicWorkflowSimilarityReadRequest,
    validate_public_workflow_similarity_reply,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    SupportedPublicSolutionSimilarityRequest,
)
from eom_catalog_contracts.workflow_similarity_read import (
    MAX_WORKFLOW_SIMILARITY_REPLY_BYTES,
    MAX_WORKFLOW_SIMILARITY_REQUEST_BYTES,
    WorkflowSimilarityRoleSelection,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    exchange_chat_frame,
)
from eom_orchestrator.similarity_materialization import SimilarityWorkspaceMaterials
from eom_workflow.public_similarity_control import (
    SupportedPublicSimilarityExecutionPlan,
    validate_public_similarity_original_source,
    validate_public_similarity_plan_context,
    validate_public_similarity_plan_request,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.orm import Session


class CatalogPublicRoleSimilarityMaterialsReader:
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
        plan: SupportedPublicSimilarityExecutionPlan,
        operator_id: str,
        request: SupportedPublicSolutionSimilarityRequest,
        original_source: PopulationSource,
        canonical_artifact_root: Path,
        authorized_artifact_revision_ids: frozenset[str],
    ) -> SimilarityWorkspaceMaterials:
        # Path/session are owner-local expectations, never dereferenced here.
        if (
            operator_id != self.expected_operator_id
            or plan.workflow_id != self.selection.workflow_id
            or plan.plan_id != self.selection.plan_id
            or plan.plan_sha256 != self.selection.plan_sha256
            or plan.similarity_delivery.context_member.artifact_revision_id
            not in authorized_artifact_revision_ids
        ):
            raise ControlPlaneError("CONTROL_SIMILARITY_CONTEXT_INVALID", "role pins differ")
        try:
            validate_public_similarity_plan_request(plan, request)
            wire = PublicWorkflowSimilarityReadRequest(
                schema_version="system-rag-workflow-similarity-read-request/2.0",
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
            reply = PublicWorkflowSimilarityReadReply.model_validate(raw)
            validate_public_workflow_similarity_reply(wire, reply, expected_operator_id=operator_id)
            if reply.status == "FAILED":
                raise ControlPlaneError(
                    "CONTROL_SIMILARITY_AUTHORITY_DENIED"
                    if reply.error_code in {"SOURCE_ACCESS_DENIED", "SOURCE_REVOKED"}
                    else "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE"
                    if reply.error_code
                    in {"AUTHORITY_UNAVAILABLE", "WORKFLOW_SIMILARITY_UNAVAILABLE"}
                    else "CONTROL_SIMILARITY_CONTEXT_INVALID",
                    "Catalog public role read unavailable",
                )
            assert reply.context is not None and reply.materials is not None
            validate_public_similarity_plan_context(plan, reply.context)
            validate_public_similarity_original_source(plan, reply.context, original_source)
            return SimilarityWorkspaceMaterials(
                canonical_json_bytes(reply.context.model_dump(mode="json")),
                canonical_json_bytes(reply.materials.model_dump(mode="json")),
            )
        except (ChatTransportError, KeyError, OSError):
            raise ControlPlaneError(
                "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE", "Catalog public role unavailable"
            ) from None
        except (ValueError, TypeError, SchemaError, RecursionError):
            raise ControlPlaneError(
                "CONTROL_SIMILARITY_CONTEXT_INVALID", "Catalog public role reply differs"
            ) from None
