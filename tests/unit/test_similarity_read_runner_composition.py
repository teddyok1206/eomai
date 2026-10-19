"""Existing entrypoint composition with synthetic boot dependencies; no live service."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service import application_runner as entry
from eom_catalog_service.similarity_read_runtime import SimilarityReaderRuntimeError
from sqlalchemy import create_engine


@pytest.mark.parametrize("mode", ("DISABLED", "ENABLED", "INVALID"))
@pytest.mark.parametrize("exam_mode", ("DISABLED", "ENABLED", "INVALID"))
@pytest.mark.parametrize("mixed_hash", (None, "sha256:" + "c" * 64))
def test_actual_runner_passes_explicit_read_service_or_fails_before_socket(
    monkeypatch, capsys, mode, exam_mode, mixed_hash
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(entry, "build_engine", lambda: engine)
    monkeypatch.setattr(entry, "catalog_runtime_privileges_ready", lambda _connection: True)
    monkeypatch.setattr(entry.signal, "signal", lambda *_args: None)
    monkeypatch.setenv("EOM_LEGACY_ITEM_AUTOMATION_MODE", "DISABLED")
    monkeypatch.setenv("EOM_SIMILARITY_READ_MODE", mode)
    monkeypatch.setenv("EOM_EXAM_SIMILARITY_READ_MODE", exam_mode)
    monkeypatch.setenv("EOM_ITEM_SIMILARITY_PUBLICATION_MODE", "DISABLED")
    monkeypatch.setenv("EOM_WORKFLOW_SIMILARITY_READ_MODE", "DISABLED")
    if mixed_hash is None:
        monkeypatch.delenv("EOM_MIXED_SIMILARITY_READ_CONFIG_SHA256", raising=False)
    else:
        monkeypatch.setenv("EOM_MIXED_SIMILARITY_READ_CONFIG_SHA256", mixed_hash)
    exam_hash = "sha256:" + "b" * 64 if exam_mode == "ENABLED" else None
    if exam_hash is None:
        monkeypatch.delenv("EOM_EXAM_SIMILARITY_READ_CONFIG_SHA256", raising=False)
    else:
        monkeypatch.setenv("EOM_EXAM_SIMILARITY_READ_CONFIG_SHA256", exam_hash)
    if mode == "ENABLED":
        monkeypatch.setenv("EOM_SIMILARITY_READ_CONFIG_SHA256", "sha256:" + "a" * 64)
    else:
        monkeypatch.delenv("EOM_SIMILARITY_READ_CONFIG_SHA256", raising=False)
    optional = object() if mode == "ENABLED" else None
    build = Mock(return_value=optional)
    if mode == "INVALID":
        build.side_effect = SimilarityReaderRuntimeError()
    monkeypatch.setattr(entry, "build_catalog_similarity_context_reads", build)
    exam_optional = object() if exam_mode == "ENABLED" else None
    exam_build = Mock(return_value=exam_optional)
    if exam_mode == "INVALID":
        exam_build.side_effect = SimilarityReaderRuntimeError()
    monkeypatch.setattr(entry, "build_catalog_exam_similarity_reads", exam_build)
    for name in (
        "KnowledgeAnalysisApplicationService",
        "KnowledgeAnalysisBatchService",
        "LegacyItemExtractionBatchService",
        "KnowledgeRetrievalApplicationService",
        "StructuredItemContentImportService",
        "RegistryService",
        "CatalogInferenceTransferMetadataService",
        "InferenceTransferSnapshotApplicationService",
        "CatalogInferenceTransferSnapshotSourceAdapter",
        "CatalogInferenceTransferWorkflowReadService",
        "ApprovedItemGraphPublicationService",
        "MockExamItemReviewPublicationService",
        "MockExamAssemblyService",
        "PdfDocumentReviewIntakeService",
        "OfficeDocumentReviewIntakeService",
        "DocumentReviewHwpxCorrectionService",
        "DocumentReviewPdfAnnotationService",
        "DocumentReviewEvidenceService",
    ):
        monkeypatch.setattr(entry, name, Mock())
    server = Mock()
    factory = Mock(return_value=server)
    monkeypatch.setattr(entry, "CatalogApplicationServer", factory)
    thread = SimpleNamespace(start=Mock(), is_alive=lambda: False, join=Mock())
    monkeypatch.setattr(
        entry,
        "threading",
        SimpleNamespace(
            Event=lambda: SimpleNamespace(set=Mock(), wait=lambda **_kwargs: True),
            Thread=Mock(return_value=thread),
        ),
    )
    invalid = mode == "INVALID" or exam_mode == "INVALID"
    assert entry.serve() == (1 if invalid else 0)
    mixed_args = {} if mixed_hash is None else {"mixed_configuration_raw_sha256": mixed_hash}
    build.assert_called_once_with(
        engine,
        mode=mode,
        configuration_raw_sha256="sha256:" + "a" * 64 if mode == "ENABLED" else None,
        **mixed_args,
    )
    if mode == "INVALID":
        exam_build.assert_not_called()
    else:
        exam_build.assert_called_once_with(
            engine, mode=exam_mode, configuration_raw_sha256=exam_hash
        )
    if invalid:
        factory.assert_not_called()
        thread.start.assert_not_called()
        assert capsys.readouterr().out == "CATALOG_SIMILARITY_READ_UNAVAILABLE\n"
    else:
        assert factory.call_args.kwargs["similarity_context_reads"] is optional
        assert factory.call_args.kwargs["exam_similarity_reads"] is exam_optional
        thread.start.assert_called_once()
        assert capsys.readouterr().out == ""
