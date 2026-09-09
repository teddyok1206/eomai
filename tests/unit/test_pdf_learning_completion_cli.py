from __future__ import annotations

import json
from dataclasses import dataclass
from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_api.build_info import BuildInfoError
from eom_catalog_contracts import SourceRelease
from eomctl import legacy_assessment as cli
from eomctl.cli import app
from typer.testing import CliRunner

_COMMIT = "a" * 40
_TREE = "b" * 40
_ARCHIVE = "sha256:" + "c" * 64


class _Engine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class _Document:
    def __init__(self, value: dict[str, object]) -> None:
        self.value = value

    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return self.value


def _file(path: Path) -> Path:
    path.write_text("{}\n", encoding="utf-8")
    return path


def _patch_release_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_Engine, dict[str, Any], object, object]:
    engine = _Engine()
    calls: dict[str, Any] = {}
    catalog_settings = object()
    platform_settings = object()
    monkeypatch.setattr(cli, "build_engine", lambda: engine)
    monkeypatch.setattr(
        cli,
        "get_build_info",
        lambda: SimpleNamespace(
            source_commit=_COMMIT,
            source_tree=_TREE,
            source_archive_sha256=_ARCHIVE,
        ),
    )
    monkeypatch.setattr(
        cli,
        "CatalogSettings",
        SimpleNamespace(from_environment=lambda: catalog_settings),
    )
    monkeypatch.setattr(
        cli,
        "Settings",
        SimpleNamespace(from_environment=lambda: platform_settings),
    )

    def control_publisher(actual_engine: object, actual_settings: object) -> object:
        calls["control_publisher"] = (actual_engine, actual_settings)
        return "control-publisher"

    def assessment_publisher(
        publisher: object,
        *,
        source_release: SourceRelease,
    ) -> object:
        calls["assessment_publisher"] = (publisher, source_release)
        return "assessment-publisher"

    monkeypatch.setattr(cli, "ControlArtifactPublisher", control_publisher)
    monkeypatch.setattr(cli, "LegacyAssessmentControlArtifactPublisher", assessment_publisher)
    return engine, calls, catalog_settings, platform_settings


def test_completion_cli_exposes_only_pinned_input_and_location_authority() -> None:
    runner = CliRunner()
    batch = runner.invoke(
        app,
        ["legacy-assessment", "extraction-batch", "--help"],
        terminal_width=200,
    )
    corpus = runner.invoke(
        app,
        ["legacy-assessment", "extraction-batch", "complete-corpus", "--help"],
        terminal_width=200,
    )
    learning = runner.invoke(
        app,
        ["legacy-assessment", "learning", "--help"],
        terminal_width=200,
    )
    complete_pdf = runner.invoke(
        app,
        ["legacy-assessment", "learning", "complete-pdf", "--help"],
        terminal_width=200,
    )

    assert batch.exit_code == corpus.exit_code == learning.exit_code == complete_pdf.exit_code == 0
    assert "complete-corpus" in batch.stdout
    assert "--command-file" in corpus.stdout
    assert "complete-pdf" in learning.stdout
    assert tuple(signature(cli.learning_complete_pdf).parameters) == (
        "corpus_completion_receipt_file",
        "root_config_file",
        "graph_snapshot_revision_id",
        "graph_snapshot_sha256",
    )
    for option in (
        "--root-config-file",
        "--graph-snapshot-revision-id",
        "--graph-snapshot-sha256",
    ):
        assert option in complete_pdf.stdout
    for forbidden in ("--source-commit", "--source-tree", "--source-archive-sha256"):
        assert forbidden not in corpus.stdout
        assert forbidden not in complete_pdf.stdout


def test_complete_corpus_composes_source_registry_and_installed_release(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine, calls, catalog_settings, platform_settings = _patch_release_composition(monkeypatch)
    command = object()
    receipt_document: dict[str, object] = {
        "schema_version": "legacy-item-corpus-completion-receipt/1.0",
        "status": "COMPLETE",
    }
    monkeypatch.setattr(cli, "load_strict_json", lambda _path: {"command": "pinned"})
    monkeypatch.setattr(
        cli,
        "validate_contract",
        lambda route, raw: calls.setdefault("validated", (route, raw)),
    )
    monkeypatch.setattr(
        cli,
        "LegacyItemCorpusCompletionCommand",
        SimpleNamespace(model_validate=lambda _raw: command),
    )

    def source(actual_engine: object, settings: object) -> object:
        calls["corpus_source"] = (actual_engine, settings)
        return "corpus-source"

    def rights(actual_engine: object) -> object:
        calls["rights"] = actual_engine
        return "rights"

    def registry(
        actual_engine: object,
        *,
        rights: object,
        settings: object,
    ) -> object:
        calls["registry"] = (actual_engine, rights, settings)
        return "registry"

    class Service:
        def __init__(self, *, source: object, artifacts: object, registry: object) -> None:
            calls["service"] = (source, artifacts, registry)

        def complete(self, actual_command: object) -> _Document:
            calls["command"] = actual_command
            return _Document(receipt_document)

    monkeypatch.setattr(cli, "PostgresLegacyItemCorpusCompletionSource", source)
    monkeypatch.setattr(cli, "RegisteredAssessmentRightsPolicyResolver", rights)
    monkeypatch.setattr(cli, "LegacyAssessmentRegistry", registry)
    monkeypatch.setattr(cli, "LegacyItemCorpusCompletionService", Service)

    result = CliRunner().invoke(
        app,
        [
            "legacy-assessment",
            "extraction-batch",
            "complete-corpus",
            "--command-file",
            str(_file(tmp_path / "command.json")),
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == receipt_document
    assert calls["validated"] == (
        "legacy-item-corpus-completion-command",
        {"command": "pinned"},
    )
    assert calls["corpus_source"] == (engine, catalog_settings)
    assert calls["rights"] is engine
    assert calls["registry"] == (engine, "rights", catalog_settings)
    assert calls["service"] == ("corpus-source", "assessment-publisher", "registry")
    assert calls["command"] is command
    assert calls["control_publisher"] == (engine, platform_settings)
    assert calls["assessment_publisher"] == (
        "control-publisher",
        SourceRelease(
            git_commit=_COMMIT,
            git_tree=_TREE,
            git_archive_sha256=_ARCHIVE,
        ),
    )
    assert engine.disposed is True


def test_complete_pdf_passes_protected_roots_and_same_installed_release(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine, calls, catalog_settings, platform_settings = _patch_release_composition(monkeypatch)
    corpus_completion = object()
    pdf_roots = object()
    request = object()
    receipt = _Document({"schema_version": "eom-pdf-learning-completion/1.0"})
    receipt_artifact = _Document({"artifact_revision_id": "revision"})
    publication = SimpleNamespace(
        completion_identity_sha256="sha256:" + "d" * 64,
        receipt_artifact=receipt_artifact,
        receipt=receipt,
    )
    monkeypatch.setattr(cli, "load_strict_json", lambda _path: {"receipt": "pinned"})
    monkeypatch.setattr(
        cli,
        "validate_contract",
        lambda route, raw: calls.setdefault("validated", (route, raw)),
    )
    monkeypatch.setattr(
        cli,
        "LegacyItemCorpusCompletionReceipt",
        SimpleNamespace(model_validate=lambda _raw: corpus_completion),
    )

    def load_roots(path: Path) -> object:
        calls["root_config_path"] = path
        return pdf_roots

    def completion_request(**values: object) -> object:
        calls["request_values"] = values
        return request

    def source(
        actual_engine: object,
        *,
        pdf_roots: object,
        settings: object,
    ) -> object:
        calls["pdf_source"] = (actual_engine, pdf_roots, settings)
        return "pdf-source"

    class Service:
        def __init__(
            self,
            *,
            source: object,
            artifacts: object,
            source_release: SourceRelease,
        ) -> None:
            calls["service"] = (source, artifacts, source_release)

        def complete(self, actual_request: object) -> object:
            calls["request"] = actual_request
            return publication

    monkeypatch.setattr(cli, "load_root_configuration", load_roots)
    monkeypatch.setattr(cli, "PdfLearningCompletionRequest", completion_request)
    monkeypatch.setattr(cli, "PostgresPdfLearningCompletionSource", source)
    monkeypatch.setattr(cli, "PdfLearningCompletionService", Service)
    receipt_path = _file(tmp_path / "corpus-receipt.json")
    roots_path = _file(tmp_path / "roots.json")

    result = CliRunner().invoke(
        app,
        [
            "legacy-assessment",
            "learning",
            "complete-pdf",
            "--corpus-completion-receipt-file",
            str(receipt_path),
            "--root-config-file",
            str(roots_path),
            "--graph-snapshot-revision-id",
            "graphrev_" + "1" * 32,
            "--graph-snapshot-sha256",
            "sha256:" + "2" * 64,
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "status": "SUCCEEDED",
        "completion_identity_sha256": "sha256:" + "d" * 64,
        "receipt_artifact": {"artifact_revision_id": "revision"},
        "receipt": {"schema_version": "eom-pdf-learning-completion/1.0"},
    }
    assert calls["validated"] == (
        "legacy-item-corpus-completion-receipt",
        {"receipt": "pinned"},
    )
    assert calls["root_config_path"] == roots_path.resolve()
    assert calls["request_values"] == {
        "corpus_completion": corpus_completion,
        "graph_snapshot_revision_id": "graphrev_" + "1" * 32,
        "graph_snapshot_sha256": "sha256:" + "2" * 64,
    }
    assert calls["pdf_source"] == (engine, pdf_roots, catalog_settings)
    expected_release = SourceRelease(
        git_commit=_COMMIT,
        git_tree=_TREE,
        git_archive_sha256=_ARCHIVE,
    )
    assert calls["service"] == ("pdf-source", "assessment-publisher", expected_release)
    assert calls["request"] is request
    assert calls["control_publisher"] == (engine, platform_settings)
    assert calls["assessment_publisher"] == ("control-publisher", expected_release)
    assert engine.disposed is True


@dataclass(frozen=True)
class _RecoveryResult:
    created: bool
    recovery_artifact: _Document


def test_recovery_injects_the_same_installed_authorization_publisher(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine, calls, _catalog_settings, _platform_settings = _patch_release_composition(monkeypatch)
    recovery = object()
    monkeypatch.setattr(cli, "load_strict_json", lambda _path: {"recovery": "pinned"})
    monkeypatch.setattr(cli, "validate_contract", lambda _route, _raw: None)
    monkeypatch.setattr(
        cli,
        "LegacyItemExtractionValidationRecovery",
        SimpleNamespace(model_validate=lambda _raw: recovery),
    )

    class Service:
        def __init__(self, actual_engine: object, *, authorizations: object) -> None:
            calls["recovery_service"] = (actual_engine, authorizations)

        def create(self, command: object) -> _RecoveryResult:
            calls["recovery_command"] = command
            return _RecoveryResult(
                created=True,
                recovery_artifact=_Document(
                    {
                        "artifact_id": "artifact_" + "1" * 32,
                        "artifact_revision_id": "rev_" + "2" * 32,
                        "sha256": "sha256:" + "3" * 64,
                    }
                ),
            )

    monkeypatch.setattr(cli, "LegacyItemExtractionRecoveryService", Service)
    result = CliRunner().invoke(
        app,
        [
            "legacy-assessment",
            "extraction-batch",
            "recover-validation-failures",
            "--recovery-file",
            str(_file(tmp_path / "recovery.json")),
            "--actor-id",
            "operator-test",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "status": "SUCCEEDED",
        "created": True,
        "recovery_artifact": {
            "artifact_id": "artifact_" + "1" * 32,
            "artifact_revision_id": "rev_" + "2" * 32,
            "sha256": "sha256:" + "3" * 64,
        },
    }
    assert calls["recovery_service"] == (engine, "assessment-publisher")
    command = calls["recovery_command"]
    assert command.recovery is recovery
    assert command.requested_by == "operator-test"
    assert engine.disposed is True


def test_invalid_embedded_release_fails_before_completion_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = _Engine()
    monkeypatch.setattr(cli, "build_engine", lambda: engine)
    monkeypatch.setattr(cli, "load_strict_json", lambda _path: {"command": "pinned"})
    monkeypatch.setattr(cli, "validate_contract", lambda _route, _raw: None)
    monkeypatch.setattr(
        cli,
        "LegacyItemCorpusCompletionCommand",
        SimpleNamespace(model_validate=lambda _raw: object()),
    )
    monkeypatch.setattr(
        cli,
        "get_build_info",
        lambda: (_ for _ in ()).throw(BuildInfoError("invalid release")),
    )
    monkeypatch.setattr(
        cli,
        "LegacyItemCorpusCompletionService",
        lambda **_values: pytest.fail("invalid installed identity must fail before the service"),
    )

    result = CliRunner().invoke(
        app,
        [
            "legacy-assessment",
            "extraction-batch",
            "complete-corpus",
            "--command-file",
            str(_file(tmp_path / "command.json")),
        ],
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "status": "FAILED",
        "error_code": "LEGACY_ITEM_OPERATION_FAILED",
    }
    assert engine.disposed is True
