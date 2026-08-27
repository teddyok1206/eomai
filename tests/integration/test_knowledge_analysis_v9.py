from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from tests.integration.test_knowledge_analysis_service import (
    _assert_v9_multimodal_document_analysis_uses_schema_closed_protocol,
)

pytestmark = pytest.mark.integration


def test_v9_multimodal_document_analysis_uses_schema_closed_protocol(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    _assert_v9_multimodal_document_analysis_uses_schema_closed_protocol(
        integration_engine,
        tmp_path,
    )
