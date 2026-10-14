"""Runtime composition with explicit synthetic installation/DB/ownership observations."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service import similarity_read_runtime as module
from eom_catalog_service.similarity_read_runtime import (
    SimilarityReaderRuntimeError,
    build_catalog_similarity_context_reads,
)
from eom_catalog_service.similarity_read_service import CatalogSimilarityContextReadService
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_identity_service import PostgresOperatorAuthorizationFence
from eom_workflow_runner.reference_query_source_read import CatalogReferenceQueryReadOwner
from sqlalchemy import create_engine

from tests.unit.test_similarity_reader_configuration import document


def install_seams(monkeypatch, *, role="eom_catalog_manager_runtime", dialect="postgresql"):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    connection = SimpleNamespace(
        dialect=SimpleNamespace(name=dialect), scalar=Mock(return_value=role)
    )
    connect = Mock(return_value=nullcontext(connection))
    monkeypatch.setattr(engine, "connect", connect)
    raw = canonical_json_bytes(document())
    read = Mock(return_value=raw)
    inspect = Mock()
    monkeypatch.setattr(module, "read_similarity_reader_configuration", read)
    monkeypatch.setattr(module, "require_operator_authorization_fence_installation", inspect)
    return SimpleNamespace(
        engine=engine, connection=connection, connect=connect, raw=raw, read=read, inspect=inspect
    )


def test_disabled_mode_reads_no_file_db_capture_model_or_runtime(monkeypatch):
    read = Mock(side_effect=AssertionError("disabled file access"))
    monkeypatch.setattr(module, "read_similarity_reader_configuration", read)
    engine = Mock()
    assert (
        build_catalog_similarity_context_reads(
            engine, mode="DISABLED", configuration_raw_sha256="staged-but-unused"
        )
        is None
    )
    assert not engine.mock_calls
    read.assert_not_called()


@pytest.mark.parametrize("mode,sha", (("AUTO", None), ("enabled", None), ("ENABLED", None)))
def test_invalid_or_incomplete_enable_fails_before_any_io(monkeypatch, mode, sha):
    read = Mock(side_effect=AssertionError("must not load"))
    monkeypatch.setattr(module, "read_similarity_reader_configuration", read)
    engine = Mock()
    with pytest.raises(SimilarityReaderRuntimeError):
        build_catalog_similarity_context_reads(engine, mode=mode, configuration_raw_sha256=sha)
    read.assert_not_called()
    assert not engine.mock_calls


def test_enabled_composes_actual_read_only_owner_after_independent_installation_inspection(
    monkeypatch,
):
    value = install_seams(monkeypatch)
    raw_sha = sha256_bytes(value.raw)
    result = build_catalog_similarity_context_reads(
        value.engine, mode="ENABLED", configuration_raw_sha256=raw_sha
    )
    assert isinstance(result, CatalogSimilarityContextReadService)
    assert type(result.owner) is CatalogReferenceQueryReadOwner
    assert type(result.owner.identity) is PostgresOperatorAuthorizationFence
    assert result.owner.identity.owner.role_name == "synthetic_database_owner"
    assert result.owner.identity.owner.role_oid == 12345
    assert not any(
        hasattr(result.owner, name)
        for name in ("resolve_claim", "resolve_submission", "fence_mutation")
    )
    value.read.assert_called_once_with(raw_sha)
    value.inspect.assert_called_once_with(value.connection, result.owner.identity.owner)
    value.connect.assert_called_once_with()
    assert value.connection.scalar.call_count == 1


@pytest.mark.parametrize(
    "fault", ("file", "invalid_config", "role", "dialect", "function", "wrong_owner")
)
def test_unadmitted_configuration_or_actual_role_never_constructs_a_read_owner(monkeypatch, fault):
    value = install_seams(
        monkeypatch,
        role="eom_api_runtime" if fault == "role" else "eom_catalog_manager_runtime",
        dialect="sqlite" if fault == "dialect" else "postgresql",
    )
    if fault == "file":
        value.read.side_effect = OSError("private file path")
    elif fault == "invalid_config":
        value.read.return_value = b'{"operator":"ADMIN"}'
    elif fault == "function":
        value.inspect.side_effect = ValueError("private function body")
    elif fault == "wrong_owner":
        body = document()
        body["database_owner"]["role_name"] = "eom_catalog_manager_runtime"
        value.read.return_value = canonical_json_bytes(body)
    constructor = Mock(side_effect=AssertionError("must not construct owner"))
    monkeypatch.setattr(module, "CatalogReferenceQueryReadOwner", constructor)
    with pytest.raises(SimilarityReaderRuntimeError) as caught:
        build_catalog_similarity_context_reads(
            value.engine, mode="ENABLED", configuration_raw_sha256=sha256_bytes(value.raw)
        )
    assert str(caught.value) == "CATALOG_SIMILARITY_READ_UNAVAILABLE"
    constructor.assert_not_called()
    if fault in {"role", "dialect", "file", "invalid_config", "wrong_owner"}:
        value.inspect.assert_not_called()
