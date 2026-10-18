"""Independent C5 DOCUMENT composition; installation/IAM observations are synthetic."""

from unittest.mock import Mock

import pytest
from eom_catalog_service import similarity_read_runtime as module
from eom_catalog_service.exam_similarity_read_service import CatalogExamSimilarityReadService
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_catalog_service.similarity_read_runtime import (
    SimilarityReaderRuntimeError,
    build_catalog_exam_similarity_reads,
    build_catalog_similarity_context_reads,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_identity_service import PostgresOperatorAuthorizationFence

from tests.unit.test_reference_query_execution_contracts import case
from tests.unit.test_similarity_read_runtime import install_seams
from tests.unit.test_similarity_reader_configuration import document


def test_disabled_exam_read_consumes_no_file_db_identity_or_reference_owner(monkeypatch):
    engine = Mock()
    read = Mock(side_effect=AssertionError("disabled exam file access"))
    reference = Mock(side_effect=AssertionError("reference config fallback"))
    monkeypatch.setattr(module, "read_exam_similarity_reader_configuration", read)
    monkeypatch.setattr(module, "read_similarity_reader_configuration", reference)
    assert (
        build_catalog_exam_similarity_reads(
            engine, mode="DISABLED", configuration_raw_sha256="unused"
        )
        is None
    )
    assert not engine.mock_calls
    read.assert_not_called()
    reference.assert_not_called()


@pytest.mark.parametrize("mode,sha", (("AUTO", None), ("enabled", None), ("ENABLED", None)))
def test_exam_enable_requires_own_explicit_hash_before_any_io(monkeypatch, mode, sha):
    read = Mock(side_effect=AssertionError("must not load config"))
    monkeypatch.setattr(module, "read_exam_similarity_reader_configuration", read)
    engine = Mock()
    with pytest.raises(SimilarityReaderRuntimeError):
        build_catalog_exam_similarity_reads(engine, mode=mode, configuration_raw_sha256=sha)
    read.assert_not_called()
    assert not engine.mock_calls


def exam_seams(monkeypatch, **values):
    value = install_seams(monkeypatch, **values)
    value.exam_read = Mock(return_value=value.raw)
    monkeypatch.setattr(module, "read_exam_similarity_reader_configuration", value.exam_read)
    value.read.side_effect = AssertionError("exam must not borrow reference configuration")
    return value


def test_enabled_exam_has_its_own_admitted_document_owner_not_reference_query(
    monkeypatch, tmp_path
):
    value = exam_seams(monkeypatch)
    reference = Mock(side_effect=AssertionError("exam must not construct QUERY owner"))
    monkeypatch.setattr(module, "CatalogReferenceQueryReadOwner", reference)
    settings = CatalogSettings(
        staging_root=tmp_path / "scratch", nas_artifact_root=tmp_path / "artifacts"
    )
    result = build_catalog_exam_similarity_reads(
        value.engine,
        mode="ENABLED",
        configuration_raw_sha256=sha256_bytes(value.raw),
        settings=settings,
    )
    assert type(result) is CatalogExamSimilarityReadService
    assert result.catalog.configuration.source_classes == ("APPROVED_ITEM", "PAST_EXAM")
    assert result.catalog.engine is value.engine and result.catalog.settings is settings
    assert type(result.identity) is PostgresOperatorAuthorizationFence
    assert result.catalog.identity_fence is result.identity
    value.exam_read.assert_called_once_with(sha256_bytes(value.raw))
    value.read.assert_not_called()
    value.inspect.assert_called_once_with(value.connection, result.identity.owner)
    reference.assert_not_called()
    assert not any(
        hasattr(result.catalog, name)
        for name in ("resolve_claim", "resolve_submission", "fence_mutation")
    )


def test_distinct_exam_classes_fix_cohort_scope_without_changing_past_only_reference(monkeypatch):
    value = install_seams(monkeypatch)
    past_only = document() | {"source_classes": ["PAST_EXAM"]}
    value.read.return_value = canonical_json_bytes(past_only)
    reference = build_catalog_similarity_context_reads(
        value.engine, mode="ENABLED", configuration_raw_sha256=sha256_bytes(value.read.return_value)
    )
    exam_configuration = document()
    exam_configuration["namespace"]["population_scope"] = "ALL_ADMITTED_GRAPH_ITEMS"
    exam_raw = canonical_json_bytes(exam_configuration)
    exam_read = Mock(return_value=exam_raw)
    monkeypatch.setattr(module, "read_exam_similarity_reader_configuration", exam_read)
    exam = build_catalog_exam_similarity_reads(
        value.engine, mode="ENABLED", configuration_raw_sha256=sha256_bytes(exam_raw)
    )
    assert reference is not None and exam is not None
    selection = case().request.context_request.views[0]
    classes = ("APPROVED_ITEM", "PAST_EXAM")
    with pytest.raises(SimilarityContextReadError, match="AUTHORITY_UNAVAILABLE"):
        reference.owner.catalog._document_view_owner(classes, selection, 25)
    selected = exam.catalog._document_view_owner(classes, selection, 25)
    assert selected.configuration.source_classes == classes
    assert selected.configuration.namespace.population_scope == "ALL_ADMITTED_GRAPH_ITEMS"
    assert reference.owner.catalog.configuration.source_classes == ("PAST_EXAM",)
    assert (
        reference.owner.catalog.configuration.namespace.population_scope
        == "OCCURRENCE_BACKED_PAST_EXAM"
    )
    assert exam.catalog is not reference.owner.catalog
    assert exam.identity is not reference.owner.identity
    assert value.inspect.call_count == value.connect.call_count == 2


def test_exam_configuration_does_not_implicitly_add_approved_item(monkeypatch):
    value = exam_seams(monkeypatch)
    value.exam_read.return_value = canonical_json_bytes(
        document() | {"source_classes": ["PAST_EXAM"]}
    )
    result = build_catalog_exam_similarity_reads(
        value.engine,
        mode="ENABLED",
        configuration_raw_sha256=sha256_bytes(value.exam_read.return_value),
    )
    assert result is not None
    assert result.catalog.configuration.source_classes == ("PAST_EXAM",)
    with pytest.raises(SimilarityContextReadError, match="AUTHORITY_UNAVAILABLE"):
        result.catalog._document_view_owner(
            ("APPROVED_ITEM", "PAST_EXAM"), case().request.context_request.views[0], 25
        )


@pytest.mark.parametrize(
    "fault", ("file", "invalid_config", "role", "dialect", "function", "wrong_owner")
)
def test_unadmitted_exam_selection_has_no_reference_fallback(monkeypatch, fault):
    value = exam_seams(
        monkeypatch,
        role="eom_api_runtime" if fault == "role" else "eom_catalog_manager_runtime",
        dialect="sqlite" if fault == "dialect" else "postgresql",
    )
    if fault == "file":
        value.exam_read.side_effect = OSError("private missing exam file")
    elif fault == "invalid_config":
        value.exam_read.return_value = b'{"operator":"ADMIN"}'
    elif fault == "function":
        value.inspect.side_effect = ValueError("private function mismatch")
    elif fault == "wrong_owner":
        value.exam_read.return_value = canonical_json_bytes(
            document()
            | {"database_owner": {"role_name": "eom_catalog_manager_runtime", "role_oid": 12345}}
        )
    constructor = Mock(side_effect=AssertionError("unadmitted exam owner"))
    monkeypatch.setattr(module, "CatalogEmbeddingRegistryVerifier", constructor)
    with pytest.raises(
        SimilarityReaderRuntimeError, match=r"^CATALOG_SIMILARITY_READ_UNAVAILABLE$"
    ):
        build_catalog_exam_similarity_reads(
            value.engine, mode="ENABLED", configuration_raw_sha256=sha256_bytes(value.raw)
        )
    constructor.assert_not_called()
    value.read.assert_not_called()
    if fault != "function":
        value.inspect.assert_not_called()
