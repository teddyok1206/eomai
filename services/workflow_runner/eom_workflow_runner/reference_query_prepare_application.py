"""Authenticated reference preparation → original QUERY admission/read + finite drive offer."""

from __future__ import annotations

import logging
from typing import Literal, Protocol

from eom_catalog_contracts.embedding_reference_query import ReferenceQuerySpaces
from eom_catalog_contracts.inference_transfer_experiment import VIEWS
from eom_catalog_contracts.mixed_embedding_registry import MixedEmbeddingIndexNamespace
from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareErrorCode,
    ReferenceQueryPrepareReply,
    ReferenceQueryPrepareReplyV2,
    ReferenceQueryPrepareRequestV2,
    ReferenceQueryPrepareRequestV11,
    SupportedReferenceQueryPrepareReply,
    SupportedReferenceQueryPrepareRequest,
    parse_supported_reference_query_prepare_request,
)
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    ReferenceQueryContextPreparation,
    SelectedEmbeddingSources,
    validate_embedding_registry_actor,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.similarity_context_ports import (
    SimilarityContextReadError,
    similarity_context_error_from_registry,
)
from eom_identifiers import content_sha256
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.database import build_session_factory
from eom_workflow.reference_query_execution import parse_supported_reference_query_workflow_request
from sqlalchemy import select

from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.models import WorkflowCommandRecord
from eom_workflow_runner.native_query_prepare_runner import (
    NativeQueryDriveOffer as ReferenceQueryDriveOffer,
)
from eom_workflow_runner.native_query_prepare_runner import require_reference_query_prepare_runner
from eom_workflow_runner.reference_query_consumer_read import CatalogCompletedReferenceQueryRead
from eom_workflow_runner.reference_query_execution_port import ReferenceQueryNativeExecutor
from eom_workflow_runner.reference_query_owner_admission import CatalogReferenceQueryOwnerAdmission
from eom_workflow_runner.reference_query_preparation import (
    ReferenceQueryPreparationUnavailable,
    prepare_and_start_reference_query_selection_in_session,
)

_LOGGER = logging.getLogger(__name__)


class ReferenceQueryPrepareDrivePort(Protocol):
    """Application-owned finite offer boundary; not a queue or execution authority."""

    def offer(self, workflow_id: str, runner: WorkflowRunner) -> ReferenceQueryDriveOffer: ...


def reference_query_prepare_identity(operator_id: str, original_key: str) -> tuple[str, str]:
    """Stable native key/logical context ID, never authority or a content-hash identity."""
    validate_embedding_registry_actor(EmbeddingRegistryCaller(operator_id))
    scope = {"operator_id": operator_id, "original_key": original_key}
    native = content_sha256({"purpose": "REFERENCE_QUERY_PREPARE_KEY/1.0", **scope})
    logical = content_sha256({"purpose": "REFERENCE_QUERY_PREPARE_CONTEXT/1.0", **scope})
    return (
        "reference-query-prepare:" + native.removeprefix("sha256:"),
        "similarityrequest_" + logical.removeprefix("sha256:")[:32],
    )


def _reply(
    request: SupportedReferenceQueryPrepareRequest,
    *,
    status: Literal["READY", "FAILED", "PENDING", "UNAVAILABLE"],
    workflow_id: str | None = None,
    selection: CompletedSimilarityQuerySelection | None = None,
    error_code: ReferenceQueryPrepareErrorCode | None = None,
) -> SupportedReferenceQueryPrepareReply:
    family = "2.0" if isinstance(request, ReferenceQueryPrepareRequestV2) else "1.0"
    reply_type = ReferenceQueryPrepareReplyV2 if family == "2.0" else ReferenceQueryPrepareReply
    return reply_type.model_validate(
        dict(
            schema_version=f"system-rag-reference-query-prepare-reply/{family}",
            operation="PREPARE_REFERENCE_QUERY",
            operation_id=request.operation_id,
            request_sha256=request.request_sha256,
            status=status,
            workflow_id=workflow_id,
            selection=selection,
            error_code=error_code,
        )
    )


def _failure(
    request: SupportedReferenceQueryPrepareRequest,
    code: ReferenceQueryPrepareErrorCode,
) -> SupportedReferenceQueryPrepareReply:
    return _reply(request, status="FAILED", error_code=code)


class NativeReferenceQueryPreparation:
    """One current capture, trusted numerical settings and existing atomic use case.

    This object is operation-local. Only the service-owned driver is shared; it
    never turns an Actor, stored metadata or prior success into authority.
    """

    def __init__(
        self,
        *,
        owner: CatalogReferenceQueryOwnerAdmission,
        executor: ReferenceQueryNativeExecutor,
        runner: WorkflowRunner,
        driver: ReferenceQueryPrepareDrivePort,
        spaces: ReferenceQuerySpaces,
    ) -> None:
        require_reference_query_prepare_runner(runner)
        spaces = ReferenceQuerySpaces.model_validate(spaces)
        if (
            runner.reference_query_owner is not owner
            or runner.reference_query_executor is not executor
            or spaces.document != owner.configuration.registry.space
            or not callable(getattr(driver, "offer", None))
        ):
            raise ValueError("REFERENCE_QUERY_PREPARE_COMPOSITION_INVALID")
        self.owner, self.executor, self.runner = owner, executor, runner
        self.driver, self.spaces = driver, spaces
        self.sessions = build_session_factory(owner.catalog.engine)

    def prepare(
        self, request: SupportedReferenceQueryPrepareRequest
    ) -> SupportedReferenceQueryPrepareReply:
        request = parse_supported_reference_query_prepare_request(request)
        caller = EmbeddingRegistryCaller(self.owner.identity.capture.operator_id)
        key, context_id = reference_query_prepare_identity(
            caller.operator_id, request.idempotency_key
        )
        config = self.owner.configuration.registry
        if isinstance(request, ReferenceQueryPrepareRequestV2) != isinstance(
            config.namespace, MixedEmbeddingIndexNamespace
        ):
            return _failure(request, "AUTHORITY_UNAVAILABLE")
        preparation = ReferenceQueryContextPreparation(
            context_id,
            SelectedEmbeddingSources(
                EmbeddingRegistryLookup(
                    config.corpus_id,
                    config.namespace,
                    request.graph_snapshot,
                    request.policy_revision_id,
                    request.policy_sha256,
                    1024,
                ),
                (request.source_item_revision_id,),
            ),
            self.spaces,
            VIEWS,
            "OPTIONAL",
            8,
            consumer_purpose=(
                request.consumer_purpose
                if isinstance(
                    request, (ReferenceQueryPrepareRequestV11, ReferenceQueryPrepareRequestV2)
                )
                else "PAST_EXAM_VARIATION"
            ),
        )
        try:
            with self.sessions.begin() as session:
                submitted = prepare_and_start_reference_query_selection_in_session(
                    session,
                    caller=caller,
                    preparation=preparation,
                    idempotency_key=key,
                    owner=self.owner,
                    executor=self.executor,
                )
                workflow = submitted.workflow
                original = parse_supported_reference_query_workflow_request(
                    workflow.initial_request
                )
                selection = None
                error_code: ReferenceQueryPrepareErrorCode | None = None
                status: Literal["READY", "FAILED", "PENDING"]
                if workflow.state == "COMPLETED":
                    reader = PinnedArtifactReadContext.for_session(session, self.owner.settings)
                    catalog = self.owner.catalog.for_pinned_similarity_request_in_session(
                        session, caller, original.context_request, artifact_reader=reader
                    )
                    prepared = catalog.prepare_reference_query_anchor_in_session(
                        session, caller, original.context_request, artifact_reader=reader
                    )
                    CatalogCompletedReferenceQueryRead(
                        self.owner,
                        workflow_id=workflow.workflow_id,
                        request=original,
                        artifact_reader=reader,
                    ).resolve_reference_query_in_session(
                        session, caller, original.context_request, prepared
                    )
                    selection = CompletedSimilarityQuerySelection(
                        workflow_id=workflow.workflow_id,
                        workflow_request_sha256=original.request_sha256,
                        context_request_sha256=original.context_request.request_sha256,
                    )
                    status = "READY"
                elif workflow.state not in {"REQUESTED", "RUNNING", "FAILED", "CANCELLED"}:
                    status, error_code = "FAILED", "QUERY_RESULT_INVALID"
                elif (
                    workflow.state in {"FAILED", "CANCELLED"}
                    or session.scalar(
                        select(WorkflowCommandRecord.command_id)
                        .where(
                            WorkflowCommandRecord.workflow_id == workflow.workflow_id,
                            WorkflowCommandRecord.state.in_(("FAILED", "CANCELLED")),
                        )
                        .limit(1)
                    )
                    is not None
                ):
                    status, error_code = "FAILED", "REFERENCE_QUERY_EXECUTION_FAILED"
                else:
                    status = "PENDING"
                reply = _reply(
                    request,
                    status=status,
                    workflow_id=workflow.workflow_id,
                    selection=selection,
                    error_code=error_code,
                )
            # The atomic Workflow/START root is closed before physical dispatch.
            # A busy/unavailable driver does not erase or re-key queued work.
            if reply.status == "PENDING":
                assert reply.workflow_id is not None
                self.driver.offer(reply.workflow_id, self.runner)
            return reply
        except ReferenceQueryPreparationUnavailable as absent:
            return _reply(
                request,
                status="UNAVAILABLE",
                error_code=absent.code,
            )
        except SimilarityContextReadError as error:
            _LOGGER.warning("REFERENCE_QUERY_PREPARATION_REJECTED boundary=SIMILARITY")
            return _failure(request, error.code)
        except EmbeddingRegistryError as error:
            _LOGGER.warning("REFERENCE_QUERY_PREPARATION_REJECTED boundary=CATALOG")
            return _failure(request, similarity_context_error_from_registry(error).code)
        except OperatorAuthorizationFenceError as error:
            # Public failure stays deliberately broad. The owner needs the
            # closed local reason to distinguish a context defect from denial;
            # never log the capture, exception body, SQL or an arbitrary code.
            reason = (
                error.code
                if type(error.code) is str
                and error.code
                in {
                    "OPERATOR_AUTHORIZATION_FENCE_CONFIGURATION_INVALID",
                    "OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID",
                    "OPERATOR_AUTHORIZATION_FENCE_OPERATOR_INVALID",
                    "OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN",
                    "OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE",
                }
                else "UNCLASSIFIED"
            )
            _LOGGER.warning(
                "REFERENCE_QUERY_PREPARATION_REJECTED boundary=IDENTITY reason=%s", reason
            )
            return _failure(request, "AUTHORITY_UNAVAILABLE")
