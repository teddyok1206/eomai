from __future__ import annotations

import ast
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_api import mock_exam_production_cli as production_cli
from eom_api.services.mock_exam_production_application import (
    MockExamProductionApplicationError,
)
from eom_api.services.mock_exam_production_composition import MockExamProductionRuntime
from eom_catalog_contracts import (
    build_integrated_science_mock_exam_production_plan,
    load_integrated_science_editorial_outline,
    load_integrated_science_mock_exam_layout_policy,
    load_integrated_science_mock_exam_policy,
)
from eom_operator_identity import (
    ActorContext,
    ActorSource,
    ActorType,
    PermissionKey,
)
from typer.testing import CliRunner

RUNNER = CliRunner()


def _plan() -> Any:
    return build_integrated_science_mock_exam_production_plan(
        policy=load_integrated_science_mock_exam_policy(),
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        outline=load_integrated_science_editorial_outline(),
    )


def _actor() -> ActorContext:
    from datetime import UTC, datetime

    return ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id="operator_" + "a" * 32,
        session_id="apisession_" + "b" * 32,
        request_id="mock-exam-cli-test",
        authentication_time=datetime(2026, 9, 8, tzinfo=UTC),
        permissions=frozenset(PermissionKey),
        source=ActorSource.CLI,
    )


class _Application:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def inspect_plan(self, actor: ActorContext) -> Any:
        self.calls.append(("inspect-plan", (actor,)))
        return _plan()

    def get(self, execution_id: str, actor: ActorContext) -> Any:
        self.calls.append(("status", (execution_id, actor)))
        raise MockExamProductionApplicationError(
            "CHECKPOINT_EXECUTION_NOT_FOUND",
            "sensitive filesystem detail must not reach stdout",
        )

    def publish_graph(self, *_: Any) -> Any:
        raise AssertionError("invalid input must not reach the application service")


def _install_session(monkeypatch: pytest.MonkeyPatch, application: _Application) -> None:
    @contextmanager
    def session(_: Path, __: Path) -> Iterator[Any]:
        runtime = SimpleNamespace(application=application)
        yield SimpleNamespace(runtime=runtime, actor=_actor())

    monkeypatch.setattr(production_cli, "_operator_session", session)


def _token_file(tmp_path: Path) -> Path:
    path = tmp_path / "operator.token"
    path.write_text("opaque-access-token\n", encoding="ascii")
    path.chmod(0o600)
    return path


def test_cli_dispatches_plan_inspection_and_emits_only_typed_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _Application()
    _install_session(monkeypatch, application)
    token = _token_file(tmp_path)

    result = RUNNER.invoke(
        production_cli.mock_exam_production_app,
        ["inspect-plan", "--access-token-file", str(token)],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "SUCCEEDED"
    assert payload["data"]["item_count"] == 25
    assert payload["data"]["plan_sha256"].startswith("sha256:")
    assert "opaque-access-token" not in result.stdout
    assert [name for name, _ in application.calls] == ["inspect-plan"]


def test_cli_exposes_atomic_graph_phase_without_legacy_batch_command() -> None:
    result = RUNNER.invoke(production_cli.mock_exam_production_app, ["--help"])

    assert result.exit_code == 0
    assert "publish-graph" in result.stdout
    assert "retire-items" in result.stdout
    assert "publish-next-graph-batch" not in result.stdout
    assert "exact 25-Item cohort atomically" in result.stdout


def test_cli_sanitizes_application_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _Application()
    _install_session(monkeypatch, application)
    token = _token_file(tmp_path)

    result = RUNNER.invoke(
        production_cli.mock_exam_production_app,
        ["status", "productionexec_" + "c" * 32, "--access-token-file", str(token)],
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "error_code": "CHECKPOINT_EXECUTION_NOT_FOUND",
        "status": "FAILED",
    }
    assert "filesystem" not in result.stdout


def test_cli_rejects_invalid_pointer_document_before_application_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _Application()
    _install_session(monkeypatch, application)
    token = _token_file(tmp_path)
    publication = tmp_path / "publication.json"
    publication.write_text('{"item_content":"must-not-echo"}', encoding="utf-8")

    result = RUNNER.invoke(
        production_cli.mock_exam_production_app,
        [
            "publish-graph",
            "productionexec_" + "c" * 32,
            "--publication-input",
            str(publication),
            "--access-token-file",
            str(token),
        ],
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "error_code": "OPERATOR_POINTER_DOCUMENT_INVALID",
        "status": "FAILED",
    }
    assert "must-not-echo" not in result.stdout


def test_access_token_reader_requires_same_owner_regular_mode_0600_file(
    tmp_path: Path,
) -> None:
    token = _token_file(tmp_path)
    assert production_cli._read_access_token(token) == "opaque-access-token"

    token.chmod(0o640)
    with pytest.raises(production_cli.MockExamProductionCliInputError) as permissions:
        production_cli._read_access_token(token)
    assert permissions.value.code == "OPERATOR_ACCESS_TOKEN_FILE_INVALID"

    token.chmod(0o600)
    link = tmp_path / "operator-link.token"
    link.symlink_to(token)
    with pytest.raises(production_cli.MockExamProductionCliInputError) as symlink:
        production_cli._read_access_token(link)
    assert symlink.value.code == "OPERATOR_ACCESS_TOKEN_FILE_INVALID"

    oversized = tmp_path / "oversized.token"
    oversized.write_bytes(b"x" * 513)
    oversized.chmod(0o600)
    with pytest.raises(production_cli.MockExamProductionCliInputError) as size:
        production_cli._read_access_token(oversized)
    assert size.value.code == "OPERATOR_ACCESS_TOKEN_FILE_INVALID"


def test_bounded_reader_rejects_fifo_hardlink_and_mid_read_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fifo = tmp_path / "input.fifo"
    os.mkfifo(fifo)
    with pytest.raises(production_cli.MockExamProductionCliInputError):
        production_cli._read_bounded(fifo, 128)

    original = tmp_path / "pointer.json"
    original.write_text('{"pointer":"one"}', encoding="utf-8")
    hardlink = tmp_path / "pointer-hardlink.json"
    hardlink.hardlink_to(original)
    with pytest.raises(production_cli.MockExamProductionCliInputError):
        production_cli._read_bounded(original, 128)

    hardlink.unlink()
    actual_reader = production_cli._read_descriptor

    def mutate(descriptor: int, size: int, *, error_code: str) -> bytes:
        payload = actual_reader(descriptor, size, error_code=error_code)
        original.write_text('{"pointer":"two"}', encoding="utf-8")
        metadata = original.stat()
        os.utime(
            original,
            ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000_000),
        )
        return payload

    monkeypatch.setattr(production_cli, "_read_descriptor", mutate)
    with pytest.raises(production_cli.MockExamProductionCliInputError):
        production_cli._read_bounded(original, 128)


def test_cli_layer_has_no_database_worker_or_storage_adapter_dependency() -> None:
    source_path = Path(production_cli.__file__).resolve()
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )

    assert not any(name.startswith("sqlalchemy") for name in imports)
    assert not any(name.startswith("eom_orchestrator") for name in imports)
    assert not any(name.startswith("eom_catalog_service") for name in imports)
    assert not any(name.startswith("eom_hwpx_manager") for name in imports)
    assert "/mnt/nas" not in source
    assert "subprocess" not in imports


def test_composition_public_shape_remains_application_and_authenticator_only() -> None:
    annotations = MockExamProductionRuntime.__annotations__
    assert tuple(annotations) == ("application", "authenticator")
    assert cast(str, annotations["application"]).endswith("MockExamProductionApplicationService")
