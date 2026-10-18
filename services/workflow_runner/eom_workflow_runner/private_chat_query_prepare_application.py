"""Live private origin → original Workflow/START, finite drive and canonical completed read."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_catalog_contracts.private_chat_similarity import PrivateChatSimilarityContext
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    PrivateChatContextPreparation,
)
from eom_catalog_service.private_chat_similarity_service import (
    PrivateChatSimilarityApplicationService,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_orchestrator.database import build_session_factory
from eom_workflow.models import WorkflowId
from eom_workflow.private_chat_query_execution import (
    PrivateChatQueryWorkflowRequest,
    parse_private_chat_query_workflow_request,
)
from eom_workflow.private_chat_query_submission_context import (
    build_private_chat_query_submission_context,
)
from pydantic import TypeAdapter
from sqlalchemy import select

from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.models import WorkflowCommandRecord
from eom_workflow_runner.native_query_prepare_runner import (
    NativeQueryDriveOffer,
    require_private_chat_query_prepare_runner,
)
from eom_workflow_runner.private_chat_query_execution_port import PrivateChatQueryNativeExecutor
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
)
from eom_workflow_runner.private_chat_query_preparation import (
    prepare_and_start_private_chat_query_selection_in_session,
)
from eom_workflow_runner.private_chat_similarity_read import CatalogPrivateChatSimilarityRead
from eom_workflow_runner.repository import NativeCommandActorSelection


class PrivateChatQueryPrepareDrivePort(Protocol):
    def offer_private_chat_query(
        self, workflow_id: str, runner: WorkflowRunner
    ) -> NativeQueryDriveOffer: ...


@dataclass(frozen=True, slots=True)
class PreparedPrivateChatQueryWorkflow:
    """Owner-local observations, not a source grant, worker reply or persisted payload."""

    workflow_id: str
    request: PrivateChatQueryWorkflowRequest
    origin: ChatPrivateQueryOrigin
    status: Literal["PENDING", "READY", "FAILED"]
    context: PrivateChatSimilarityContext | None = None
    failure_code: Literal["PRIVATE_CHAT_QUERY_EXECUTION_FAILED", "QUERY_RESULT_INVALID"] | None = (
        None
    )

    def __post_init__(self) -> None:
        TypeAdapter(WorkflowId).validate_python(self.workflow_id, strict=True)
        request = parse_private_chat_query_workflow_request(self.request)
        origin = build_private_chat_query_submission_context(request, self.origin).origin
        if (
            type(self.status) is not str
            or self.status not in {"PENDING", "READY", "FAILED"}
            or (self.failure_code is not None and type(self.failure_code) is not str)
            or (self.status == "READY") != (self.context is not None)
            or (self.status == "FAILED") != (self.failure_code is not None)
            or self.failure_code
            not in {None, "PRIVATE_CHAT_QUERY_EXECUTION_FAILED", "QUERY_RESULT_INVALID"}
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_PREPARE_RESULT_INVALID")
        if self.context is not None:
            context = PrivateChatSimilarityContext.model_validate(self.context)
            if (
                context.request != request.context_request
                or context.status not in {"READY", "PARTIAL", "EMPTY"}
                or context.query_execution is None
            ):
                raise ValueError("PRIVATE_CHAT_QUERY_PREPARE_RESULT_INVALID")
            object.__setattr__(self, "context", context)
        object.__setattr__(self, "request", request)
        object.__setattr__(self, "origin", origin)


class NativePrivateChatQueryPreparation:
    """Operation-local application, no retained session, new key or second scheduler."""

    def __init__(
        self,
        *,
        owner: CatalogPrivateChatQueryOwnerAdmission,
        executor: PrivateChatQueryNativeExecutor,
        runner: WorkflowRunner,
        driver: PrivateChatQueryPrepareDrivePort,
    ) -> None:
        self.owner, self.executor, self.runner, self.driver = owner, executor, runner, driver
        self._runner_actor()
        self.sessions = build_session_factory(owner.catalog.engine)

    def _runner_actor(self) -> NativeCommandActorSelection:
        actor = require_private_chat_query_prepare_runner(self.runner)
        if (
            self.runner.private_chat_query_owner is not self.owner
            or self.runner.private_chat_query_executor is not self.executor
            or not callable(getattr(self.driver, "offer_private_chat_query", None))
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_PREPARE_COMPOSITION_INVALID")
        return actor

    def prepare(
        self, origin: ChatPrivateQueryOrigin, preparation: PrivateChatContextPreparation
    ) -> PreparedPrivateChatQueryWorkflow:
        actor = self._runner_actor()
        caller = EmbeddingRegistryCaller(actor.actor_id)
        with self.sessions.begin() as session:
            submitted = prepare_and_start_private_chat_query_selection_in_session(
                session,
                caller=caller,
                origin=origin,
                preparation=preparation,
                owner=self.owner,
                executor=self.executor,
            )
            workflow = submitted.workflow
            original = parse_private_chat_query_workflow_request(workflow.initial_request)
            origin = build_private_chat_query_submission_context(original, origin).origin
            workflow_id, state = workflow.workflow_id, workflow.state
            failure: Literal["PRIVATE_CHAT_QUERY_EXECUTION_FAILED", "QUERY_RESULT_INVALID"] | None
            if state not in {"REQUESTED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"}:
                failure = "QUERY_RESULT_INVALID"
            elif state == "COMPLETED":
                failure = None  # Only the canonical reader may accept completed work below.
            elif (
                state in {"FAILED", "CANCELLED"}
                or session.scalar(
                    select(WorkflowCommandRecord.command_id)
                    .where(
                        WorkflowCommandRecord.workflow_id == workflow_id,
                        WorkflowCommandRecord.state.in_(("FAILED", "CANCELLED")),
                    )
                    .limit(1)
                )
                is not None
            ):
                failure = "PRIVATE_CHAT_QUERY_EXECUTION_FAILED"
            else:
                failure = None
        # Original Workflow+START is committed before drive or another read root.
        # Never hold this transaction while waiting for a model/claim or result.
        if failure is not None:
            return PreparedPrivateChatQueryWorkflow(
                workflow_id, original, origin, "FAILED", failure_code=failure
            )
        if state != "COMPLETED":
            self.driver.offer_private_chat_query(workflow_id, self.runner)
            return PreparedPrivateChatQueryWorkflow(workflow_id, original, origin, "PENDING")
        read = CatalogPrivateChatSimilarityRead(self.owner.sources, request=original, origin=origin)
        context = PrivateChatSimilarityApplicationService(read).compose(
            caller, original.context_request
        )
        if context.status == "FAILED":
            assert context.error_code is not None
            raise SimilarityContextReadError(context.error_code)
        if context.status == "UNAVAILABLE" or context.query_execution is None:
            raise SimilarityContextReadError("QUERY_RESULT_INVALID")
        return PreparedPrivateChatQueryWorkflow(workflow_id, original, origin, "READY", context)
