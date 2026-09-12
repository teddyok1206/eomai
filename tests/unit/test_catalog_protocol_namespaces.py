from __future__ import annotations

from typing import cast

from eom_catalog_service.artifacts import (
    CATALOG_ITEM_CONTENT_V2_PROTOCOL_VERSION,
    CATALOG_ITEM_CONTENT_V3_PROTOCOL_VERSION,
    CATALOG_ITEM_CONTENT_V3_SCHEMA_HASH,
    CATALOG_PROTOCOL_VERSION,
)
from eom_catalog_service.knowledge_analysis_service import (
    KNOWLEDGE_ANALYSIS_CATALOG_PROTOCOL,
    KNOWLEDGE_ANALYSIS_DOCUMENT_CATALOG_PROTOCOL,
    KNOWLEDGE_ANALYSIS_DOCUMENT_CATALOG_SCHEMA_HASH,
    KNOWLEDGE_ANALYSIS_ENDPOINT_TYPED_DOCUMENT_CATALOG_PROTOCOL,
    KNOWLEDGE_ANALYSIS_INTEGRITY_DOCUMENT_CATALOG_PROTOCOL,
    KNOWLEDGE_ANALYSIS_MULTIMODAL_DOCUMENT_CATALOG_PROTOCOL,
    KNOWLEDGE_ANALYSIS_SOLUTION_CATALOG_PROTOCOL,
    KNOWLEDGE_ANALYSIS_STABLE_IDENTITY_CATALOG_PROTOCOL,
    KNOWLEDGE_ANALYSIS_TYPED_IDENTITY_CATALOG_PROTOCOL,
    KNOWLEDGE_ANALYSIS_VISUAL_ITEM_CATALOG_PROTOCOL,
)
from eom_catalog_service.mock_exam_item_review_publication_service import (
    ITEM_REVIEW_PROTOCOL_VERSION,
    ITEM_REVIEW_PROTOCOL_VERSION_V2,
    ITEM_REVIEW_PROTOCOL_VERSION_V3,
)
from eom_orchestrator.models import Base, ProtocolVersionRecord
from eom_orchestrator.repository import ensure_protocol_version
from sqlalchemy.orm import Session


class _ProtocolSession:
    def __init__(self, records: tuple[ProtocolVersionRecord, ...]) -> None:
        self.records = {record.version: record for record in records}

    def get(
        self, record_type: type[ProtocolVersionRecord], version: str
    ) -> ProtocolVersionRecord | None:
        assert record_type is ProtocolVersionRecord
        return self.records.get(version)

    def add(self, record: ProtocolVersionRecord) -> None:
        self.records[record.version] = record


def test_catalog_contract_bundles_have_unique_immutable_protocol_versions() -> None:
    """Different contract bundles must never compete for one protocol version key."""

    protocol_versions = (
        CATALOG_PROTOCOL_VERSION,
        CATALOG_ITEM_CONTENT_V2_PROTOCOL_VERSION,
        CATALOG_ITEM_CONTENT_V3_PROTOCOL_VERSION,
        KNOWLEDGE_ANALYSIS_DOCUMENT_CATALOG_PROTOCOL,
        KNOWLEDGE_ANALYSIS_ENDPOINT_TYPED_DOCUMENT_CATALOG_PROTOCOL,
        KNOWLEDGE_ANALYSIS_INTEGRITY_DOCUMENT_CATALOG_PROTOCOL,
        KNOWLEDGE_ANALYSIS_MULTIMODAL_DOCUMENT_CATALOG_PROTOCOL,
        KNOWLEDGE_ANALYSIS_TYPED_IDENTITY_CATALOG_PROTOCOL,
        KNOWLEDGE_ANALYSIS_STABLE_IDENTITY_CATALOG_PROTOCOL,
        KNOWLEDGE_ANALYSIS_CATALOG_PROTOCOL,
        KNOWLEDGE_ANALYSIS_VISUAL_ITEM_CATALOG_PROTOCOL,
        KNOWLEDGE_ANALYSIS_SOLUTION_CATALOG_PROTOCOL,
        ITEM_REVIEW_PROTOCOL_VERSION,
        ITEM_REVIEW_PROTOCOL_VERSION_V2,
        ITEM_REVIEW_PROTOCOL_VERSION_V3,
    )

    assert CATALOG_ITEM_CONTENT_V2_PROTOCOL_VERSION == "catalog/1.2"
    assert CATALOG_ITEM_CONTENT_V3_PROTOCOL_VERSION == "catalog/1.13"
    assert ITEM_REVIEW_PROTOCOL_VERSION_V3 == "catalog/1.14"
    assert CATALOG_ITEM_CONTENT_V3_SCHEMA_HASH == (
        "sha256:4e5fe407e576b68a4162c9105e8cf31f765cfd8fea21982f36be49503505f797"
    )
    assert KNOWLEDGE_ANALYSIS_DOCUMENT_CATALOG_PROTOCOL == "catalog/1.3"
    assert KNOWLEDGE_ANALYSIS_DOCUMENT_CATALOG_SCHEMA_HASH == (
        "sha256:5a915700a4160383401363952c0e542354d5a64b75e0cee799021a3abab53929"
    )
    assert KNOWLEDGE_ANALYSIS_CATALOG_PROTOCOL == "catalog/1.9"
    assert KNOWLEDGE_ANALYSIS_SOLUTION_CATALOG_PROTOCOL == "catalog/1.15"
    assert len(protocol_versions) == len(set(protocol_versions))


def test_repository_preserves_catalog_1_3_when_item_v3_successor_is_registered() -> None:
    knowledge_document = ProtocolVersionRecord(
        version=KNOWLEDGE_ANALYSIS_DOCUMENT_CATALOG_PROTOCOL,
        schema_sha256=KNOWLEDGE_ANALYSIS_DOCUMENT_CATALOG_SCHEMA_HASH,
    )
    session = _ProtocolSession((knowledge_document,))

    ensure_protocol_version(
        cast(Session, session),
        CATALOG_ITEM_CONTENT_V3_PROTOCOL_VERSION,
        CATALOG_ITEM_CONTENT_V3_SCHEMA_HASH,
    )

    assert session.records[KNOWLEDGE_ANALYSIS_DOCUMENT_CATALOG_PROTOCOL] is knowledge_document
    assert session.records[CATALOG_ITEM_CONTENT_V3_PROTOCOL_VERSION].schema_sha256 == (
        CATALOG_ITEM_CONTENT_V3_SCHEMA_HASH
    )


def test_direct_knowledge_analysis_service_registers_review_operator_table() -> None:
    """The CLI service path must resolve the review record's operator foreign key."""

    assert "operators" in Base.metadata.tables
