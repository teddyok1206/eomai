from __future__ import annotations

from eom_catalog_service.artifacts import CATALOG_ITEM_CONTENT_V2_PROTOCOL_VERSION
from eom_catalog_service.knowledge_analysis_service import (
    KNOWLEDGE_ANALYSIS_CATALOG_PROTOCOL,
    KNOWLEDGE_ANALYSIS_DOCUMENT_CATALOG_PROTOCOL,
)


def test_approved_item_analysis_has_distinct_immutable_catalog_protocol() -> None:
    """Different contract bundles must never compete for one protocol version key."""

    assert CATALOG_ITEM_CONTENT_V2_PROTOCOL_VERSION == "catalog/1.2"
    assert KNOWLEDGE_ANALYSIS_DOCUMENT_CATALOG_PROTOCOL == "catalog/1.3"
    assert KNOWLEDGE_ANALYSIS_CATALOG_PROTOCOL == "catalog/1.9"
    assert (
        len(
            {
                CATALOG_ITEM_CONTENT_V2_PROTOCOL_VERSION,
                KNOWLEDGE_ANALYSIS_DOCUMENT_CATALOG_PROTOCOL,
                KNOWLEDGE_ANALYSIS_CATALOG_PROTOCOL,
            }
        )
        == 3
    )
