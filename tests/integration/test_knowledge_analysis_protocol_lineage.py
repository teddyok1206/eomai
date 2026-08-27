from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from tests.integration.test_knowledge_analysis_batch_service import (
    _assert_v8_batch_executes_one_multimodal_range_exactly_once,
    _assert_v10_batch_executes_one_typed_identity_range_exactly_once,
)
from tests.integration.test_knowledge_analysis_service import (
    _assert_v7_document_analysis_pins_integrity_complete_contract_and_accepts,
    _assert_v8_multimodal_document_analysis_flows_through_graph_and_retrieval,
    _assert_v9_multimodal_document_analysis_uses_schema_closed_protocol,
    _assert_v10_multimodal_document_analysis_uses_typed_identity_protocol,
)

pytestmark = pytest.mark.integration


def test_knowledge_analysis_protocol_lineage_advances_without_backward_publication(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    """Exercise immutable revisions in publication order on one persistent test database."""

    def case(name: str) -> Path:
        path = tmp_path / name
        path.mkdir()
        return path

    _assert_v7_document_analysis_pins_integrity_complete_contract_and_accepts(
        integration_engine,
        case("v7"),
    )
    _assert_v8_multimodal_document_analysis_flows_through_graph_and_retrieval(
        integration_engine,
        case("v8-service"),
    )
    _assert_v8_batch_executes_one_multimodal_range_exactly_once(
        integration_engine,
        case("v8-batch"),
    )
    _assert_v9_multimodal_document_analysis_uses_schema_closed_protocol(
        integration_engine,
        case("v9"),
    )
    _assert_v10_multimodal_document_analysis_uses_typed_identity_protocol(
        integration_engine,
        case("v10-service"),
    )
    _assert_v10_batch_executes_one_typed_identity_range_exactly_once(
        integration_engine,
        case("v10-batch"),
    )
