"""Explicit independent composition flag; source configuration is not activation."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service.exam_similarity_read_service import CatalogExamSimilarityReadService
from eom_catalog_service.similarity_read_runtime import (
    SimilarityReaderRuntimeError,
    build_catalog_exam_similarity_reads,
)
from eom_catalog_service.similarity_read_service import CatalogSimilarityContextReadService
from sqlalchemy import create_engine


def test_disabled_exam_read_consumes_no_reference_owner_or_io():
    unused = Mock()
    assert build_catalog_exam_similarity_reads(mode="DISABLED", context_reads=unused) is None
    assert not unused.mock_calls


@pytest.mark.parametrize(
    "mode,owner", (("AUTO", None), ("enabled", None), ("ENABLED", None), ("ENABLED", object()))
)
def test_exam_enable_requires_existing_admitted_owner_composition(mode, owner):
    with pytest.raises(SimilarityReaderRuntimeError):
        build_catalog_exam_similarity_reads(mode=mode, context_reads=owner)


def test_reference_enable_is_not_exam_enable():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    owner = SimpleNamespace(catalog=SimpleNamespace(engine=engine), identity=Mock())
    reference = CatalogSimilarityContextReadService(owner)
    try:
        assert build_catalog_exam_similarity_reads(mode="DISABLED", context_reads=reference) is None
        read = build_catalog_exam_similarity_reads(mode="ENABLED", context_reads=reference)
        assert type(read) is CatalogExamSimilarityReadService
        assert read.catalog is owner.catalog and read.identity is owner.identity
    finally:
        engine.dispose()
