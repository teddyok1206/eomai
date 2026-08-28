"""Fresh-authorized Knowledge Analysis batch creation and pointer-only projections."""

from __future__ import annotations

from typing import Literal

from eom_api_contracts import CommandResult, ListResponse, SingleResponse
from eom_api_contracts.knowledge_analysis import (
    CreateKnowledgeAnalysisBatchRequest,
    ExecuteKnowledgeAnalysisBatchRangeInput,
    KnowledgeAnalysisBatchRangeView,
    KnowledgeAnalysisBatchView,
)
from eom_catalog_contracts import (
    CreateKnowledgeAnalysisBatchCommand,
    ExecuteKnowledgeAnalysisRange,
    KnowledgeAnalysisBatchRangeRequestV2,
    KnowledgeAnalysisBatchRequestV3,
    KnowledgeAnalysisBatchRequestV4,
    KnowledgeAnalysisBatchSourceRangeV2,
    ReuseAcceptedKnowledgeAnalysisRange,
)
from eom_identifiers import content_sha256
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Query, Request

from eom_api.dependencies import Auth, IdempotencyKey, require_permission
from eom_api.routers.common import many, one, run_command

router = APIRouter(prefix="/knowledge-analysis-batches", tags=["knowledge-analysis-batches"])


@router.post(
    "",
    operation_id="knowledge_analysis_batch_create",
    status_code=202,
    response_model=SingleResponse[CommandResult],
    dependencies=[
        Depends(
            require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_CREATE, fresh=True, admin_only=True)
        )
    ],
)
def create_knowledge_analysis_batch(
    request: Request,
    body: CreateKnowledgeAnalysisBatchRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    del authentication

    def execute() -> CommandResult:
        context = request.state.request_context
        actor = context.actor()
        submission_key = request.app.state.services.idempotency.submission_key(
            operator_id=actor.actor_id,
            endpoint_key="knowledge_analysis_batch_create",
            raw_key=idempotency_key,
        )
        ranges: list[KnowledgeAnalysisBatchRangeRequestV2] = []
        for item in body.ranges:
            execution = item.execution
            ranges.append(
                KnowledgeAnalysisBatchRangeRequestV2(
                    ordinal=item.ordinal,
                    source=KnowledgeAnalysisBatchSourceRangeV2(
                        document_revision_id=item.source.document_revision_id,
                        first_physical_page=item.source.first_physical_page,
                        last_physical_page=item.source.last_physical_page,
                        curriculum_unit_keys=item.source.curriculum_unit_keys,
                    ),
                    execution=(
                        ExecuteKnowledgeAnalysisRange(
                            predecessor_analysis_run_id=(execution.predecessor_analysis_run_id)
                        )
                        if isinstance(execution, ExecuteKnowledgeAnalysisBatchRangeInput)
                        else ReuseAcceptedKnowledgeAnalysisRange(
                            accepted_analysis_run_id=execution.accepted_analysis_run_id
                        )
                    ),
                )
            )
        batch_request = (
            KnowledgeAnalysisBatchRequestV4(
                preset_key=body.preset_key,
                general_knowledge_mode=body.general_knowledge_mode,
                risk_policy_revision_id=body.risk_policy_revision_id,
                review_policy=body.review_policy,
                range_failure_policy=body.range_failure_policy,
                scheduling_mode="BOUNDED_PARALLEL",
                max_in_flight=2,
                ranges=tuple(ranges),
            )
            if body.max_in_flight == 2
            else KnowledgeAnalysisBatchRequestV3(
                preset_key=body.preset_key,
                general_knowledge_mode=body.general_knowledge_mode,
                risk_policy_revision_id=body.risk_policy_revision_id,
                review_policy=body.review_policy,
                range_failure_policy=body.range_failure_policy,
                ranges=tuple(ranges),
            )
        )
        canonical = {
            "request": batch_request.model_dump(mode="json"),
            "requested_by": actor.actor_id,
        }
        result = request.app.state.services.catalog_application.create_knowledge_analysis_batch(
            CreateKnowledgeAnalysisBatchCommand(
                request=batch_request,
                requested_by=actor.actor_id,
                authorized_at=context.started_at,
                idempotency_key=submission_key,
                submission_sha256=content_sha256(canonical),
            )
        )
        return CommandResult(
            command_id=f"knowledge-analysis-batch-{result.batch_id}",
            resource_type="knowledge_analysis_batch",
            resource_id=result.batch_id,
            status="ACCEPTED",
            resource_version=result.resource_version,
            status_url=f"/api/v1/knowledge-analysis-batches/{result.batch_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="knowledge_analysis_batch",
            callback=execute,
            response_status=202,
        ),
    )


@router.get(
    "",
    operation_id="knowledge_analysis_batch_list",
    response_model=ListResponse[KnowledgeAnalysisBatchView],
    dependencies=[
        Depends(require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_READ, admin_only=True))
    ],
)
def list_knowledge_analysis_batches(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, max_length=1024),
    state: Literal["QUEUED", "RUNNING", "BLOCKED", "SUCCEEDED", "CANCELLED"] | None = Query(
        default=None
    ),
) -> ListResponse[KnowledgeAnalysisBatchView]:
    page = request.app.state.services.queries.list_knowledge_analysis_batches(
        limit=limit,
        cursor=cursor,
        state=state,
    )
    return many(
        request,
        page.data,
        limit=limit,
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get(
    "/{batch_id}",
    operation_id="knowledge_analysis_batch_get",
    response_model=SingleResponse[KnowledgeAnalysisBatchView],
    dependencies=[
        Depends(require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_READ, admin_only=True))
    ],
)
def get_knowledge_analysis_batch(
    request: Request,
    batch_id: str,
) -> SingleResponse[KnowledgeAnalysisBatchView]:
    return one(request, request.app.state.services.queries.knowledge_analysis_batch(batch_id))


@router.get(
    "/{batch_id}/ranges",
    operation_id="knowledge_analysis_batch_ranges",
    response_model=ListResponse[KnowledgeAnalysisBatchRangeView],
    dependencies=[
        Depends(require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_READ, admin_only=True))
    ],
)
def knowledge_analysis_batch_ranges(
    request: Request,
    batch_id: str,
    limit: int = Query(default=200, ge=1, le=200),
    cursor: str | None = Query(default=None, max_length=1024),
) -> ListResponse[KnowledgeAnalysisBatchRangeView]:
    page = request.app.state.services.queries.knowledge_analysis_batch_ranges(
        batch_id,
        limit=limit,
        cursor=cursor,
    )
    return many(
        request,
        page.data,
        limit=limit,
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )
