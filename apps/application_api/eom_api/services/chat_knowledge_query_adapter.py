"""API presentation adapter over the shared Catalog discovery implementation."""

from collections.abc import Callable

from eom_api_contracts.chat_knowledge import ChatKnowledgeRequest, ChatKnowledgeSelection
from eom_api_contracts.items import ItemRevisionView
from eom_catalog_service.chat_knowledge_discovery import (
    ChatDiscoveryError,
)
from eom_catalog_service.chat_knowledge_discovery import (
    ChatKnowledgeQueryAdapter as CatalogDiscoveryReader,
)
from eom_catalog_service.chat_knowledge_discovery import (
    DiscoveryOrigin as DiscoveryOrigin,
)
from eom_catalog_service.chat_knowledge_discovery import (
    candidate_statement as candidate_statement,
)
from eom_catalog_service.chat_knowledge_discovery import (
    discovery_origin_statement as discovery_origin_statement,
)
from eom_catalog_service.chat_knowledge_discovery import (
    topic_source_statement as topic_source_statement,
)
from eom_catalog_service.models import ItemRevisionRecord
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from eom_api.errors import ApiError


class ChatKnowledgeQueryAdapter:
    def __init__(
        self,
        engine: Engine,
        project_revisions: Callable[
            [Session, tuple[ItemRevisionRecord, ...]], dict[str, ItemRevisionView]
        ],
    ) -> None:
        self.reader = CatalogDiscoveryReader(
            engine,
            lambda session, rows: {
                key: value.approval for key, value in project_revisions(session, rows).items()
            },
        )

    def search(self, request: ChatKnowledgeRequest) -> ChatKnowledgeSelection:
        try:
            return self.reader.search(request)
        except ChatDiscoveryError as error:
            raise ApiError(error.status, error.code, error.title, error.detail) from None
