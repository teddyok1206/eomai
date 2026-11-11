"""Current admission policy for new item authoring, not historical request decoding."""

from __future__ import annotations

from collections.abc import Mapping

from eom_image_contracts import SVG_LABEL_LAYOUT_PACK_BUNDLES
from eom_workflow import WorkflowRequest

from eom_api.errors import ApiError


def require_current_item_authoring_grounding(request: WorkflowRequest) -> None:
    """Run only after exact replay resolution and before any new authoring side effect."""

    if request.request_name != "GENERATED_KNOWLEDGE_ITEM_REQUEST":
        return
    retrieval = request.educational_retrieval
    if retrieval is None:
        raise ApiError(
            422,
            "WORKFLOW_GRAPH_GROUNDING_REQUIRED",
            "Graph-grounded authoring is required",
            "New item authoring requires textbook evidence through the authorized Graph retrieval.",
        )
    if retrieval.schema_version == "educational-retrieval-requirement/2.0":
        raise ApiError(
            422,
            "WORKFLOW_TEXTBOOK_REQUIRED",
            "Textbook evidence is required",
            "The current exact past-exam variation contract cannot combine textbook evidence. "
            "New variation authoring requires a compatible textbook-grounded contract.",
        )
    if "TEXTBOOK" not in retrieval.source_classes:
        raise ApiError(
            422,
            "WORKFLOW_TEXTBOOK_REQUIRED",
            "Textbook evidence is required",
            "New item authoring must include textbooks in its authorized Graph retrieval scope.",
        )


def require_current_item_authoring_pack(
    request: WorkflowRequest, runtime_context: Mapping[str, object] | None
) -> None:
    """Match the resolved immutable Pack, never a client-selected version or mutable default."""

    if request.request_name != "GENERATED_KNOWLEDGE_ITEM_REQUEST":
        return
    pack = runtime_context.get("content_pack") if runtime_context is not None else None
    if (
        not isinstance(pack, Mapping)
        or pack.get("pack_key") != "generated-knowledge-item"
        or pack.get("version") != "1.20.19"
        or pack.get("release_sha256") != SVG_LABEL_LAYOUT_PACK_BUNDLES["1.20.19"]
    ):
        raise ApiError(
            409,
            "WORKFLOW_TEXTBOOK_POLICY_NOT_READY",
            "Textbook-grounded authoring is not ready",
            "New item authoring requires the exact released mandatory-textbook Content Pack.",
        )
