"""Authenticated comparison submission and purpose-specific owner reads."""

from __future__ import annotations

from typing import Annotated

from eom_api_contracts import CommandResult, SingleResponse
from eom_api_contracts.inference_transfer import (
    InferenceTransferPairRetryRequestV1,
    InferenceTransferPairSubmitRequest,
    InferenceTransferPairSubmitRequestV11,
    InferenceTransferWorkflowReadRequest,
    InferenceTransferWorkflowReadRequestV11,
    InferenceTransferWorkflowReadResult,
    InferenceTransferWorkflowReadResultV11,
)
from eom_api_contracts.similarity_context import (
    SimilarityContextReadSelection,
    SimilarityContextReadSelectionV2,
    SimilarityContextReadSelectionV3,
)
from eom_catalog_contracts.inference_transfer_invocation import InferenceTransferWorkflowReadMode
from eom_catalog_contracts.inference_transfer_metadata import (
    MAX_METADATA_FRAME_BYTES,
    InferenceTransferMetadataResolveRequest,
    InferenceTransferMetadataResolveResult,
)
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotRequest,
    InferenceTransferSnapshotResult,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    SupportedPublicSolutionSimilarityContext,
)
from eom_catalog_contracts.similarity_context_v2 import SupportedSimilarityContext
from eom_identifiers import content_sha256
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Path, Query, Request, Response
from pydantic import Field, ValidationError
from starlette.concurrency import run_in_threadpool

from eom_api.dependencies import Auth, ExpectedVersion, IdempotencyKey, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import one, run_command
from eom_api.services.similarity_context_read import MAX_PUBLIC_SIMILARITY_SELECTOR_BYTES

router = APIRouter(tags=["inference-transfer"])
type CompletedSimilarityContext = Annotated[
    SupportedSimilarityContext | SupportedPublicSolutionSimilarityContext,
    Field(discriminator="schema_version"),
]


@router.post(
    "/knowledge/inference-transfer/similarity-context",
    operation_id="inference_transfer_similarity_context_read",
    response_model=SingleResponse[CompletedSimilarityContext],
    dependencies=[Depends(require_permission(PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE))],
    openapi_extra={
        "x-eom-read-only": True,
        "x-eom-additional-permissions": [
            PermissionKey.WORKFLOW_READ.value,
            PermissionKey.ITEM_READ.value,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ.value,
            PermissionKey.CONTENT_INTAKE_READ.value,
        ],
    },
)
async def read_similarity_context(
    request: Request,
    body: SimilarityContextReadSelection
    | SimilarityContextReadSelectionV2
    | SimilarityContextReadSelectionV3,
    response: Response,
    authentication: Auth,
) -> SingleResponse[CompletedSimilarityContext]:
    if len(await request.body()) > MAX_PUBLIC_SIMILARITY_SELECTOR_BYTES:
        raise ApiError(
            422,
            "SIMILARITY_CONTEXT_BUDGET_EXCEEDED",
            "Similarity selector too large",
            "The exact selector exceeds its fixed public byte budget.",
        )
    response.headers["Cache-Control"] = "no-store"
    reads = request.app.state.services.similarity_context_reads
    if isinstance(body, SimilarityContextReadSelectionV3):
        result = await run_in_threadpool(reads.read_public, authentication, body.exact_selection())
        return one(request, result)
    return one(
        request,
        reads.read_v2(authentication, body.exact_selection())
        if isinstance(body, SimilarityContextReadSelectionV2)
        else reads.read(authentication, body),
    )


@router.post(
    "/knowledge/inference-transfer/metadata",
    operation_id="inference_transfer_metadata_resolve",
    response_model=SingleResponse[InferenceTransferMetadataResolveResult],
    dependencies=[Depends(require_permission(PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE))],
    openapi_extra={
        "x-eom-read-only": True,
        "x-eom-additional-permissions": [
            PermissionKey.ITEM_READ.value,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ.value,
        ],
        "x-eom-conditional-permissions": {"PAST_EXAM": [PermissionKey.CONTENT_INTAKE_READ.value]},
    },
)
async def resolve_metadata(
    request: Request,
    body: InferenceTransferMetadataResolveRequest,
    authentication: Auth,
) -> SingleResponse[InferenceTransferMetadataResolveResult]:
    if len(await request.body()) > MAX_METADATA_FRAME_BYTES:
        raise ApiError(
            422,
            "INFERENCE_TRANSFER_METADATA_BUDGET_EXCEEDED",
            "Metadata request too large",
            "The exact metadata read request exceeds its fixed byte budget.",
        )
    return one(
        request,
        request.app.state.services.inference_transfer_metadata.resolve(authentication, body),
    )


@router.post(
    "/knowledge/inference-transfer/snapshot",
    operation_id="inference_transfer_snapshot_read",
    response_model=SingleResponse[InferenceTransferSnapshotResult],
    dependencies=[Depends(require_permission(PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE))],
    openapi_extra={
        "x-eom-read-only": True,
        "x-eom-additional-permissions": [
            PermissionKey.ITEM_READ.value,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ.value,
        ],
        "x-eom-conditional-permissions": {"PAST_EXAM": [PermissionKey.CONTENT_INTAKE_READ.value]},
    },
)
def read_snapshot(
    request: Request,
    body: InferenceTransferSnapshotRequest,
    authentication: Auth,
) -> SingleResponse[InferenceTransferSnapshotResult]:
    return one(
        request,
        request.app.state.services.inference_transfer_snapshots.execute(authentication, body),
    )


@router.post(
    "/knowledge/inference-transfer/comparisons",
    operation_id="inference_transfer_pair_submit",
    status_code=202,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START))],
    openapi_extra={
        "x-eom-additional-permissions": [
            PermissionKey.ITEM_READ.value,
            PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE.value,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ.value,
        ],
        "x-eom-conditional-permissions": {"PAST_EXAM": [PermissionKey.CONTENT_INTAKE_READ.value]},
    },
)
def submit_pair(
    request: Request,
    body: InferenceTransferPairSubmitRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    return _submit_pair(request, body, authentication, idempotency_key)


@router.post(
    "/knowledge/inference-transfer/comparisons/v1.1",
    operation_id="inference_transfer_pair_submit_v11",
    status_code=202,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START))],
    openapi_extra={
        "x-eom-additional-permissions": [
            PermissionKey.ITEM_READ.value,
            PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE.value,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ.value,
        ],
        "x-eom-conditional-permissions": {"PAST_EXAM": [PermissionKey.CONTENT_INTAKE_READ.value]},
    },
)
def submit_pair_v11(
    request: Request,
    body: InferenceTransferPairSubmitRequestV11,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    return _submit_pair(request, body, authentication, idempotency_key)


def _submit_pair(
    request: Request,
    body: InferenceTransferPairSubmitRequest | InferenceTransferPairSubmitRequestV11,
    authentication: Auth,
    idempotency_key: str,
) -> SingleResponse[CommandResult]:
    services = request.app.state.services
    # run_command returns cached success before its callback. Current source
    # resolution must therefore precede the HTTP claim/replay boundary.
    submission = services.inference_transfer_submissions.authorize_submission(authentication, body)

    def execute() -> CommandResult:
        actor = request.state.request_context.actor()
        key = services.idempotency.submission_key(
            operator_id=actor.actor_id,
            endpoint_key=(
                "inference_transfer_pair_submit_v11"
                if isinstance(body, InferenceTransferPairSubmitRequestV11)
                else "inference_transfer_pair_submit"
            ),
            raw_key=idempotency_key,
        )
        command_id, workflow_id, version = services.inference_transfer_submissions.start(
            submission,
            actor,
            idempotency_key=key,
        )
        return CommandResult(
            command_id=command_id,
            resource_type="workflow",
            resource_id=workflow_id,
            status="ACCEPTED",
            resource_version=version,
            status_url=(
                f"/api/v1/knowledge/inference-transfer/workflows/{workflow_id}/v1.1"
                if isinstance(body, InferenceTransferPairSubmitRequestV11)
                else f"/api/v1/knowledge/inference-transfer/workflows/{workflow_id}"
            ),
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="workflow",
            callback=execute,
            response_status=202,
        ),
    )


@router.post(
    "/knowledge/inference-transfer/workflows/{workflow_id}/retries/v1.1",
    operation_id="inference_transfer_pair_retry_v11",
    status_code=202,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START))],
    openapi_extra={
        "x-eom-additional-permissions": [
            PermissionKey.WORKFLOW_READ.value,
            PermissionKey.ITEM_READ.value,
            PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE.value,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ.value,
        ],
        "x-eom-conditional-permissions": {"PAST_EXAM": [PermissionKey.CONTENT_INTAKE_READ.value]},
    },
)
def retry_pair_v11(
    request: Request,
    workflow_id: Annotated[str, Path(pattern=r"^workflow_[0-9a-f]{32}$")],
    body: InferenceTransferPairRetryRequestV1,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected_version: ExpectedVersion,
) -> SingleResponse[CommandResult]:
    services = request.app.state.services
    # A cached accepted reply is not current creator/source authorization.
    authorized = services.inference_transfer_retries.authorize_retry(
        authentication, workflow_id, body
    )

    def execute() -> CommandResult:
        actor = request.state.request_context.actor()
        key = services.idempotency.submission_key(
            operator_id=actor.actor_id,
            endpoint_key="inference_transfer_pair_retry_v11",
            raw_key=idempotency_key,
        )
        command_id, child_workflow_id, version = services.inference_transfer_retries.retry(
            authorized, actor, expected_version=expected_version, idempotency_key=key
        )
        return CommandResult(
            command_id=command_id,
            resource_type="workflow",
            resource_id=child_workflow_id,
            status="ACCEPTED",
            resource_version=version,
            status_url=f"/api/v1/knowledge/inference-transfer/workflows/{child_workflow_id}/v1.1",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body={
                "parent_workflow_id": workflow_id,
                "expected_resource_version": expected_version,
                "retry_request": body.model_dump(mode="json"),
            },
            resource_type="workflow",
            callback=execute,
            response_status=202,
        ),
    )


@router.get(
    "/knowledge/inference-transfer/workflows/{workflow_id}",
    operation_id="inference_transfer_workflow_read",
    response_model=SingleResponse[InferenceTransferWorkflowReadResult],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
    openapi_extra={
        "x-eom-read-only": True,
        "x-eom-additional-permissions": [
            PermissionKey.ITEM_READ.value,
            PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE.value,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ.value,
        ],
        "x-eom-conditional-permissions": {"PAST_EXAM": [PermissionKey.CONTENT_INTAKE_READ.value]},
    },
)
def read_comparison(
    request: Request,
    workflow_id: str,
    authentication: Auth,
    mode: Annotated[InferenceTransferWorkflowReadMode, Query()] = "STATUS_ONLY",
) -> SingleResponse[InferenceTransferWorkflowReadResult]:
    body = {
        "schema_version": "inference-transfer-workflow-read-request/1.0",
        "workflow_id": workflow_id,
        "mode": mode,
    }
    try:
        query = InferenceTransferWorkflowReadRequest.model_validate(
            body | {"read_sha256": content_sha256(body)}
        )
    except ValidationError as exc:
        raise ApiError(
            422,
            "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID",
            "Invalid comparison read",
            "An exact Workflow identity is required.",
        ) from exc
    return one(
        request,
        request.app.state.services.inference_transfer_workflow_reads.execute(
            authentication,
            query,
        ),
    )


@router.get(
    "/knowledge/inference-transfer/workflows/{workflow_id}/v1.1",
    operation_id="inference_transfer_workflow_read_v11",
    response_model=SingleResponse[InferenceTransferWorkflowReadResultV11],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
    openapi_extra={
        "x-eom-read-only": True,
        "x-eom-additional-permissions": [
            PermissionKey.ITEM_READ.value,
            PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE.value,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ.value,
        ],
        "x-eom-conditional-permissions": {"PAST_EXAM": [PermissionKey.CONTENT_INTAKE_READ.value]},
    },
)
def read_comparison_v11(
    request: Request,
    workflow_id: str,
    authentication: Auth,
    mode: Annotated[InferenceTransferWorkflowReadMode, Query()] = "STATUS_ONLY",
) -> SingleResponse[InferenceTransferWorkflowReadResultV11]:
    body = {
        "schema_version": "inference-transfer-workflow-read-request/1.1",
        "workflow_id": workflow_id,
        "mode": mode,
    }
    try:
        query = InferenceTransferWorkflowReadRequestV11.model_validate(
            body | {"read_sha256": content_sha256(body)}
        )
    except ValidationError as exc:
        raise ApiError(
            422,
            "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID",
            "Invalid comparison read",
            "An exact Workflow identity is required.",
        ) from exc
    return one(
        request,
        request.app.state.services.inference_transfer_workflow_reads_v11.execute(
            authentication, query
        ),
    )
