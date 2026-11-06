"""Administrator-only Graph metadata browsing; no RAG execution or publication."""

from typing import Annotated

from eom_api_contracts import ProductionItemCandidateViewContract, SingleResponse
from eom_catalog_contracts.knowledge_map import KnowledgeMapView, MapEdgeId, MapHash, MapNodeId
from eom_catalog_contracts.knowledge_map_v2 import KnowledgeMapViewV2
from eom_catalog_service.knowledge_map_read import KnowledgeMapReadError
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalServiceError
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Path, Query, Request

from eom_api.dependencies import Auth, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import one

SOURCE_PERMISSIONS = (
    PermissionKey.KNOWLEDGE_ANALYSIS_READ,
    PermissionKey.ITEM_READ,
    PermissionKey.CONTENT_INTAKE_READ,
)


def _source_permissions(request: Request, authentication: Auth) -> None:
    for permission in SOURCE_PERMISSIONS:
        require_permission(permission)(request, authentication)


router = APIRouter(
    tags=["knowledge-map"],
    dependencies=[
        Depends(require_permission(PermissionKey.KNOWLEDGE_GRAPH_READ, admin_only=True)),
        Depends(_source_permissions),
    ],
)
SnapshotId = Annotated[str, Query(pattern=r"^graphrev_[0-9a-f]{32}$")]
MAP_READ_METADATA = {
    "x-eom-read-only": True,
    "x-eom-additional-permissions": [permission.value for permission in SOURCE_PERMISSIONS],
}


def _map_error(exc: KnowledgeMapReadError | KnowledgeRetrievalServiceError) -> ApiError:
    return ApiError(
        404 if exc.code.endswith(("NOT_FOUND", "UNAVAILABLE")) else 409,
        exc.code,
        "Graph view unavailable",
        "The exact published Graph reference is unavailable.",
    )


@router.get(
    "/knowledge-map",
    operation_id="knowledge_map_read",
    response_model=SingleResponse[KnowledgeMapView | KnowledgeMapViewV2],
    openapi_extra=MAP_READ_METADATA,
)
def read_map(
    request: Request,
    graph_snapshot_revision_id: SnapshotId | None = None,
    snapshot_sha256: Annotated[MapHash | None, Query()] = None,
    query: str = Query(default="", max_length=80),
    node_id: Annotated[MapNodeId | None, Query()] = None,
    edge_id: Annotated[MapEdgeId | None, Query()] = None,
) -> SingleResponse[KnowledgeMapView | KnowledgeMapViewV2]:
    try:
        value = request.app.state.services.queries.knowledge_map.read(
            graph_snapshot_revision_id=graph_snapshot_revision_id,
            snapshot_sha256=snapshot_sha256,
            query=query,
            node_id=node_id,
            edge_id=edge_id,
        )
    except (KnowledgeMapReadError, KnowledgeRetrievalServiceError) as exc:
        raise _map_error(exc) from exc
    return one(request, value)


@router.get(
    "/knowledge-map/items/{revision_id}",
    operation_id="knowledge_map_item_read",
    response_model=SingleResponse[ProductionItemCandidateViewContract],
    openapi_extra=MAP_READ_METADATA,
)
def read_map_item(
    request: Request,
    revision_id: Annotated[str, Path(pattern=r"^itemrev_[0-9a-f]{32}$")],
    graph_snapshot_revision_id: SnapshotId,
    snapshot_sha256: Annotated[MapHash, Query()],
    manifest_sha256: Annotated[MapHash, Query()],
) -> SingleResponse[ProductionItemCandidateViewContract]:
    queries = request.app.state.services.queries
    try:
        item_id = queries.knowledge_map.item_reference(
            graph_snapshot_revision_id,
            snapshot_sha256,
            revision_id,
            manifest_sha256,
        )
    except (KnowledgeMapReadError, KnowledgeRetrievalServiceError) as exc:
        raise _map_error(exc) from exc
    # Opening DB is a new read in its current Graph, not a mutation/rebase of
    # the explorer's old snapshot. Exact Item revision/hash are never replaced.
    page = queries.production_item_candidates(
        curriculum_unit_key=None,
        source_class=None,
        content_profile=None,
        eligible=None,
        item_type_key=None,
        difficulty_band=None,
        limit=1,
        cursor=None,
        selected_revision_id=revision_id,
    )
    value = page.data[0] if page.data else None
    if value is None or value.item_id != item_id or value.item_manifest_sha256 != manifest_sha256:
        raise ApiError(
            409,
            "KNOWLEDGE_MAP_ITEM_STALE",
            "Item unavailable",
            "The exact Item is unavailable in DB.",
        )
    return one(request, value)
