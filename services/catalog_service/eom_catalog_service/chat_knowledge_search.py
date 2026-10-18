"""Actor-authorized discovery through the same indexed reader as manual search."""

from __future__ import annotations

from typing import Literal, cast

from eom_api_contracts.chat_knowledge import ChatKnowledgeRequest, ChatKnowledgeSelection
from eom_api_contracts.items import ItemApprovalView
from eom_protocol.general_chat_grounding import ChatKnowledgeItem, ChatKnowledgeSnapshot, read_agent
from eom_protocol.general_chat_tools import (
    ChatDiscoveryCard,
    ChatSearchCatalogReply,
    ChatSearchCatalogRequest,
    ChatToolOutcome,
    failed_tool,
)
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.chat_knowledge_discovery import (
    ChatDiscoveryError,
    ChatKnowledgeQueryAdapter,
)
from eom_catalog_service.item_approval_projection import project_item_approval
from eom_catalog_service.models import ItemEventRecord, ItemRevisionRecord


def discovery_approvals(
    session: Session, rows: tuple[ItemRevisionRecord, ...]
) -> dict[str, ItemApprovalView]:
    ids = tuple(row.item_revision_id for row in rows)
    events = {}
    if ids:
        for event in session.scalars(
            select(ItemEventRecord).where(
                ItemEventRecord.item_revision_id.in_(ids),
                ItemEventRecord.event_type == "ITEM_REVISION_APPROVED",
            )
        ):
            if event.item_revision_id in events:
                raise ChatDiscoveryError(
                    503,
                    "CHAT_KNOWLEDGE_POINTER_INVALID",
                    "Invalid approval",
                    "Duplicate canonical approval event",
                )
            events[event.item_revision_id] = event
    return {
        row.item_revision_id: project_item_approval(row, events.get(row.item_revision_id))
        for row in rows
    }


class ChatKnowledgeSearchService:
    def __init__(self, engine: Engine) -> None:
        self.reader = ChatKnowledgeQueryAdapter(engine, discovery_approvals)

    def search(self, request: ChatSearchCatalogRequest) -> ChatSearchCatalogReply:
        request = read_agent(
            "CatalogRequest", request.model_dump(mode="json"), ChatSearchCatalogRequest
        )
        try:
            # The permission check shares the discovery transaction; no TOCTOU
            # authorization window or unrestricted metadata/title side channel.
            result = self.reader.search(chat_search_query(request), actor_id=request.actor_id)
            outcome = chat_search_outcome(result)
        except ChatDiscoveryError as error:
            outcome = failed_tool(
                "CHAT_KNOWLEDGE_FORBIDDEN"
                if error.code == "CHAT_KNOWLEDGE_FORBIDDEN"
                else "CHAT_KNOWLEDGE_POINTER_INVALID"
            )
        except ValueError:
            outcome = failed_tool("CHAT_KNOWLEDGE_QUERY_INVALID")
        return read_agent(
            "CatalogReply",
            ChatSearchCatalogReply(outcome=outcome).model_dump(mode="json"),
            ChatSearchCatalogReply,
        )


def chat_search_outcome(result: ChatKnowledgeSelection) -> ChatToolOutcome:
    """One shared card projection; never elevate approval or manufacture source content."""
    cards = tuple(
        ChatDiscoveryCard(
            item=ChatKnowledgeItem.model_validate(
                card.model_dump(
                    mode="json", include={"item_id", "item_revision_id", "manifest_sha256"}
                )
            ),
            display_name=card.display_name,
            approval=cast(Literal["APPROVED", "PENDING"], card.approval.status),
            source_kind=card.source_kind,
            graph_membership=card.graph_membership,
        )
        for card in result.values
    )
    outcome = ChatToolOutcome(
        status="SUCCEEDED" if cards else "EMPTY",
        cards=cards,
        snapshot=None
        if result.snapshot is None
        else ChatKnowledgeSnapshot(
            graph_snapshot_revision_id=result.snapshot.graph_snapshot_revision_id,
            sha256=result.snapshot.snapshot_sha256,
        ),
        truncated=result.truncated,
        context=None,
        error_code=None,
    )
    return outcome


def chat_search_query(request: ChatSearchCatalogRequest) -> ChatKnowledgeRequest:
    args = request.arguments
    if args.kind == "TOPIC":
        query = {"kind": args.kind, "terms": args.terms, "source": args.source}
    elif args.kind == "RECENT":
        query = {"kind": args.kind, "source": args.source}
    else:
        query = args.model_dump(exclude={"terms", "source"})
    return ChatKnowledgeRequest.model_validate(
        {
            "query": query,
            "limit": 6,
            "snapshot": None
            if request.snapshot is None
            else {
                "graph_snapshot_revision_id": request.snapshot.graph_snapshot_revision_id,
                "snapshot_sha256": request.snapshot.sha256,
            },
        }
    )
