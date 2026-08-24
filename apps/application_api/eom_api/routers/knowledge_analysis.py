"""ADMIN knowledge-analysis commands and pointer-only read projections."""

from __future__ import annotations

from eom_api_contracts import CommandResult, ListResponse, SingleResponse
from eom_api_contracts.common import EmptyRequest
from eom_api_contracts.events import EventView
from eom_api_contracts.knowledge_analysis import (
    CreateKnowledgeAnalysisRequest,
    KnowledgeAnalysisReviewRequest,
    KnowledgeAnalysisRunView,
)
from eom_catalog_contracts import (
    ApprovedItemKnowledgeAnalysisSelection,
    ContentIntakeKnowledgeAnalysisSelection,
    CreateKnowledgeAnalysisCommand,
    ReconcileKnowledgeAnalysisCommand,
    ReviewKnowledgeAnalysisCommand,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Query, Request, Response

from eom_api.dependencies import Auth, ExpectedVersion, IdempotencyKey, etag, require_permission
from eom_api.routers.common import many, one, run_command

router = APIRouter(prefix="/knowledge-analyses", tags=["knowledge-analysis"])


@router.get(
    "",
    operation_id="knowledge_analysis_list",
    response_model=ListResponse[KnowledgeAnalysisRunView],
    dependencies=[
        Depends(
            require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_READ, fresh=True, admin_only=True)
        )
    ],
)
def list_knowledge_analyses(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, max_length=1024),
    state: str | None = Query(default=None, max_length=24),
) -> ListResponse[KnowledgeAnalysisRunView]:
    page = request.app.state.services.queries.list_knowledge_analyses(
        limit=limit, cursor=cursor, state=state
    )
    return many(
        request,
        page.data,
        limit=limit,
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.post(
    "",
    operation_id="knowledge_analysis_create",
    status_code=202,
    response_model=SingleResponse[CommandResult],
    dependencies=[
        Depends(
            require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_CREATE, fresh=True, admin_only=True)
        )
    ],
)
def create_knowledge_analysis(
    request: Request,
    body: CreateKnowledgeAnalysisRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    del authentication

    def execute() -> CommandResult:
        actor = request.state.request_context.actor()
        submission_key = request.app.state.services.idempotency.submission_key(
            operator_id=actor.actor_id,
            endpoint_key="knowledge_analysis_create",
            raw_key=idempotency_key,
        )
        source_data = body.source.model_dump(mode="json")
        source = (
            ContentIntakeKnowledgeAnalysisSelection.model_validate(source_data)
            if body.source.source_kind == "CONTENT_INTAKE_FILE"
            else ApprovedItemKnowledgeAnalysisSelection.model_validate(source_data)
        )
        result = request.app.state.services.catalog_application.create_knowledge_analysis(
            CreateKnowledgeAnalysisCommand(
                source=source,
                preset_key=body.preset_key,
                general_knowledge_mode=body.general_knowledge_mode,
                risk_policy_revision_id=body.risk_policy_revision_id,
                predecessor_analysis_run_id=body.predecessor_analysis_run_id,
                requested_by=actor.actor_id,
                idempotency_key=submission_key,
            )
        )
        return _command_result(result.analysis_run_id, result.resource_version)

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="knowledge_analysis",
            callback=execute,
            response_status=202,
        ),
    )


@router.get(
    "/{analysis_run_id}",
    operation_id="knowledge_analysis_get",
    response_model=SingleResponse[KnowledgeAnalysisRunView],
    dependencies=[
        Depends(
            require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_READ, fresh=True, admin_only=True)
        )
    ],
)
def get_knowledge_analysis(
    request: Request, analysis_run_id: str, response: Response
) -> SingleResponse[KnowledgeAnalysisRunView]:
    value = request.app.state.services.queries.knowledge_analysis(analysis_run_id)
    response.headers["ETag"] = etag(value.resource_version)
    return one(request, value)


@router.get(
    "/{analysis_run_id}/events",
    operation_id="knowledge_analysis_events",
    response_model=ListResponse[EventView],
    dependencies=[
        Depends(
            require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_READ, fresh=True, admin_only=True)
        )
    ],
)
def knowledge_analysis_events(request: Request, analysis_run_id: str) -> ListResponse[EventView]:
    values = request.app.state.services.queries.knowledge_analysis_events(analysis_run_id)
    return many(request, values, limit=200)


@router.post(
    "/{analysis_run_id}/reconcile",
    operation_id="knowledge_analysis_reconcile",
    response_model=SingleResponse[CommandResult],
    dependencies=[
        Depends(
            require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_CREATE, fresh=True, admin_only=True)
        )
    ],
)
def reconcile_knowledge_analysis(
    request: Request,
    analysis_run_id: str,
    body: EmptyRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    del authentication

    def execute() -> CommandResult:
        actor = request.state.request_context.actor()
        result = request.app.state.services.catalog_application.reconcile_knowledge_analysis(
            ReconcileKnowledgeAnalysisCommand(
                analysis_run_id=analysis_run_id,
                requested_by=actor.actor_id,
            )
        )
        return _command_result(result.analysis_run_id, result.resource_version)

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="knowledge_analysis",
            callback=execute,
        ),
    )


@router.post(
    "/{analysis_run_id}/reviews",
    operation_id="knowledge_analysis_review",
    response_model=SingleResponse[CommandResult],
    dependencies=[
        Depends(
            require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_REVIEW, fresh=True, admin_only=True)
        )
    ],
)
def review_knowledge_analysis(
    request: Request,
    analysis_run_id: str,
    body: KnowledgeAnalysisReviewRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected_version: ExpectedVersion,
) -> SingleResponse[CommandResult]:
    del authentication

    def execute() -> CommandResult:
        actor = request.state.request_context.actor()
        submission_key = request.app.state.services.idempotency.submission_key(
            operator_id=actor.actor_id,
            endpoint_key="knowledge_analysis_review",
            raw_key=idempotency_key,
        )
        result = request.app.state.services.catalog_application.review_knowledge_analysis(
            ReviewKnowledgeAnalysisCommand(
                analysis_run_id=analysis_run_id,
                expected_version=expected_version,
                decision=body.decision,
                notes=body.notes,
                decided_by=actor.actor_id,
                idempotency_key=submission_key,
            )
        )
        return _command_result(result.analysis_run_id, result.resource_version)

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="knowledge_analysis",
            callback=execute,
        ),
    )


def _command_result(analysis_run_id: str, resource_version: int) -> CommandResult:
    return CommandResult(
        command_id=f"knowledge-analysis-{analysis_run_id}",
        resource_type="knowledge_analysis",
        resource_id=analysis_run_id,
        status="ACCEPTED",
        resource_version=resource_version,
        status_url=f"/api/v1/knowledge-analyses/{analysis_run_id}",
    )
