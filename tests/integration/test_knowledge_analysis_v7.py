from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from tests.integration.test_knowledge_analysis_service import (
    _assert_v7_document_analysis_pins_integrity_complete_contract_and_accepts,
)

pytestmark = pytest.mark.integration


def test_v7_document_analysis_pins_integrity_complete_contract_and_accepts(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    _assert_v7_document_analysis_pins_integrity_complete_contract_and_accepts(
        integration_engine,
        tmp_path,
    )
