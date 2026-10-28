"""Presentation-only compatibility commands; no model, PostgreSQL or systemd execution."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
import typer
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.errors import PlatformError
from eom_orchestrator.settings import Settings, SettingsError
from eom_protocol import ErrorCode
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.codex_compatibility import CodexCompatibilityRequest, load_compatibility_request
from eom_workflow.codex_compatibility_matrix import load_compatibility_matrix
from eom_workflow.control_plane import ReasoningEffort
from eomctl import codex_runtime as cli
from eomctl.cli import app
from sqlalchemy import Engine
from typer.testing import CliRunner

COMMIT = "a" * 40
RUNNER = CliRunner()


def test_supported_cli_hierarchy_exposes_maintenance_without_running_it() -> None:
    result = RUNNER.invoke(app, ["control-plane", "codex-runtime", "--help"])
    assert result.exit_code == 0, result.output
    for command in (
        "check-update",
        "prepare-compatibility",
        "maintenance-preflight",
        "scoped-preflight",
        "restoration-preflight",
        "verify",
        "verify-scoped",
    ):
        assert command in result.output


def _request() -> CodexCompatibilityRequest:
    now = datetime.now(UTC)
    return load_compatibility_request(
        {
            "schema_version": "codex-compatibility-request/1.0",
            "run_id": "codexcompat_" + "1" * 32,
            "source_commit": COMMIT,
            "created_at": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
            "max_model_calls": 1,
            "cases": [
                {
                    "case_id": "compatcase_" + "2" * 32,
                    "slot_id": "01",
                    "binding_id": "authbinding_" + "3" * 32,
                    "assignment_revision_id": None,
                    "expected_resource_version": 1,
                    "model": "gpt-6.1-sol",
                    "reasoning_effort": "medium",
                }
            ],
        }
    )


def _file(tmp_path: Path) -> Path:
    path = tmp_path / "request.json"
    cli._write_request_file(path, _request())
    return path


def _database(monkeypatch: pytest.MonkeyPatch) -> Mock:
    engine = Mock(spec=Engine)
    monkeypatch.setattr(cli, "build_engine", lambda: cast(Engine, engine))
    monkeypatch.setattr(
        Settings,
        "from_environment",
        lambda: Settings(runtime_source_commit=COMMIT),
    )
    return engine


def _arguments(command: str, path: Path) -> list[str]:
    return [command, "--request-file", str(path), "--source-commit", COMMIT]


def test_check_update_only_calls_non_generating_observers(monkeypatch: pytest.MonkeyPatch) -> None:
    surface = Mock(return_value=("0.160.0", frozenset({"--output-schema", "--image"})))
    observation = Mock()
    observation.model_dump.return_value = {"status": "CURRENT", "latest_version": "0.160.0"}
    distribution = Mock(return_value=observation)
    monkeypatch.setattr(cli, "observe_codex_cli_surface", surface)
    monkeypatch.setattr(cli, "check_codex_distribution_update", distribution)
    database = Mock(side_effect=AssertionError("update must not query database"))
    model = Mock(side_effect=AssertionError("update must not execute a model"))
    monkeypatch.setattr(cli, "build_engine", database)
    monkeypatch.setattr(cli, "run_codex_compatibility", model)
    result = RUNNER.invoke(cli.codex_runtime_app, ["check-update"])
    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value["installation_changed"] is False
    assert value["model_defaults_changed"] is False
    assert value["installed_required_flags"] == ["--image", "--output-schema"]
    assert distribution.call_args.kwargs["installed_version"] == "0.160.0"
    database.assert_not_called()
    model.assert_not_called()


def test_prepare_passes_exact_defaults_and_writes_private_exclusive_typed_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _database(monkeypatch)
    request = _request()
    prepare = Mock(return_value=request)
    monkeypatch.setattr(cli, "prepare_codex_compatibility_request", prepare)
    path = tmp_path / "prepared.json"
    result = RUNNER.invoke(
        cli.codex_runtime_app,
        [
            "prepare-compatibility",
            "--model",
            "gpt-6.1-sol",
            "--source-commit",
            COMMIT,
            "--output-file",
            str(path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert prepare.call_args.args == (engine,)
    assert prepare.call_args.kwargs["models"] == ("gpt-6.1-sol",)
    assert prepare.call_args.kwargs["reasoning_efforts"] == (ReasoningEffort.MEDIUM,)
    assert prepare.call_args.kwargs["slot_ids"] == ("01", "02")
    assert cli.read_compatibility_request_file(path) == request
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(result.output)["model_calls"] == 0
    engine.dispose.assert_called_once()
    original = path.read_bytes()
    with pytest.raises(typer.BadParameter, match="existing files remain"):
        cli._write_request_file(path, request)
    assert path.read_bytes() == original


def test_prepare_repeated_explicit_choices_do_not_include_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _database(monkeypatch)
    prepare = Mock(return_value=_request())
    monkeypatch.setattr(cli, "prepare_codex_compatibility_request", prepare)
    result = RUNNER.invoke(
        cli.codex_runtime_app,
        [
            "prepare-compatibility",
            "--model",
            "gpt-6.1-sol",
            "--model",
            "gpt-6-sol",
            "--effort",
            "high",
            "--effort",
            "xhigh",
            "--slot",
            "03",
            "--source-commit",
            COMMIT,
            "--output-file",
            str(tmp_path / "request.json"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert prepare.call_args.kwargs["models"] == ("gpt-6.1-sol", "gpt-6-sol")
    assert prepare.call_args.kwargs["reasoning_efforts"] == (
        ReasoningEffort.HIGH,
        ReasoningEffort.XHIGH,
    )
    assert prepare.call_args.kwargs["slot_ids"] == ("03",)


def _matrix_file(tmp_path: Path) -> Path:
    path = tmp_path / "matrix.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "codex-compatibility-matrix/1.0",
                "selections": [
                    {"slot_id": "02", "model": "candidate-model", "reasoning_effort": "medium"},
                    {"slot_id": "06", "model": "gpt-5.6-terra", "reasoning_effort": "xhigh"},
                    {"slot_id": "01", "model": "candidate-model", "reasoning_effort": "high"},
                ],
            }
        )
    )
    path.chmod(0o600)
    return path


def test_prepare_matrix_file_preserves_exact_selection_without_cartesian_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _database(monkeypatch)
    path = _matrix_file(tmp_path)
    expected = load_compatibility_matrix(json.loads(path.read_bytes()))
    request = _request()
    prepare = Mock(return_value=request)
    cartesian = Mock(side_effect=AssertionError("matrix must not expand into Cartesian defaults"))
    monkeypatch.setattr(cli, "prepare_codex_compatibility_matrix_request", prepare)
    monkeypatch.setattr(cli, "prepare_codex_compatibility_request", cartesian)
    output = tmp_path / "prepared.json"
    result = RUNNER.invoke(
        cli.codex_runtime_app,
        [
            "prepare-compatibility",
            "--matrix-file",
            str(path),
            "--source-commit",
            COMMIT,
            "--output-file",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert prepare.call_args.args == (engine,)
    assert prepare.call_args.kwargs["matrix"] == expected
    assert prepare.call_args.kwargs["source_commit"] == COMMIT
    assert cli.read_compatibility_request_file(output) == request
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(result.output)["model_calls"] == 0
    cartesian.assert_not_called()
    engine.dispose.assert_called_once()


@pytest.mark.parametrize(
    "flag", [("--model", "candidate-model"), ("--effort", "medium"), ("--slot", "01")]
)
def test_matrix_cannot_mix_even_explicit_default_cartesian_flags_before_database(
    flag: tuple[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _matrix_file(tmp_path)
    database = Mock(side_effect=AssertionError("mixed presentation must not query database"))
    monkeypatch.setattr(cli, "build_engine", database)
    result = RUNNER.invoke(
        cli.codex_runtime_app,
        [
            "prepare-compatibility",
            "--matrix-file",
            str(path),
            *flag,
            "--source-commit",
            COMMIT,
            "--output-file",
            str(tmp_path / "prepared.json"),
        ],
    )
    assert result.exit_code == 2
    assert "cannot be combined" in result.output
    database.assert_not_called()


def test_missing_model_and_matrix_refuses_before_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Mock(side_effect=AssertionError("missing selection must not query database"))
    monkeypatch.setattr(cli, "build_engine", database)
    result = RUNNER.invoke(
        cli.codex_runtime_app,
        [
            "prepare-compatibility",
            "--source-commit",
            COMMIT,
            "--output-file",
            str(tmp_path / "prepared.json"),
        ],
    )
    assert result.exit_code == 2
    assert "provide --model or --matrix-file" in result.output
    database.assert_not_called()


@pytest.mark.parametrize(
    "boundary", ["relative", "symlink", "hardlink", "mode", "large", "fifo", "owner"]
)
def test_matrix_files_reuse_private_bounded_nofollow_boundary(
    boundary: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _matrix_file(tmp_path)
    if boundary == "relative":
        path = Path("matrix.json")
    elif boundary == "symlink":
        link = tmp_path / "link.json"
        link.symlink_to(path)
        path = link
    elif boundary == "hardlink":
        os.link(path, tmp_path / "hard.json")
    elif boundary == "mode":
        path.chmod(0o640)
    elif boundary == "large":
        path.write_bytes(b" " * (cli._MAX_MATRIX_BYTES + 1))
    elif boundary == "fifo":
        path = tmp_path / "fifo"
        os.mkfifo(path, 0o600)
    else:
        monkeypatch.setattr(cli.os, "geteuid", lambda: path.stat().st_uid + 1)
    with pytest.raises(typer.BadParameter):
        cli.read_compatibility_matrix_file(path)


@pytest.mark.parametrize(
    "bad_kind", ["duplicate-json", "nan", "authority", "duplicate-triple", "over-budget"]
)
def test_invalid_matrix_stops_before_database_and_does_not_expose_input(
    bad_kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _matrix_file(tmp_path)
    document = json.loads(path.read_bytes())
    if bad_kind == "duplicate-json":
        path.write_bytes(b'{"selections":[],"selections":[]}')
    elif bad_kind == "nan":
        path.write_bytes(b'{"selections":NaN}')
    else:
        if bad_kind == "authority":
            document["selections"][0]["binding_id"] = "private-untrusted-authority"
        elif bad_kind == "duplicate-triple":
            document["selections"].append(document["selections"][0])
        else:
            document["selections"] = [
                {"slot_id": "01", "model": f"candidate-{index}", "reasoning_effort": "medium"}
                for index in range(65)
            ]
        path.write_text(json.dumps(document))
    database = Mock(side_effect=AssertionError("invalid matrix must not query database"))
    monkeypatch.setattr(cli, "build_engine", database)
    result = RUNNER.invoke(
        cli.codex_runtime_app,
        [
            "prepare-compatibility",
            "--matrix-file",
            str(path),
            "--source-commit",
            COMMIT,
            "--output-file",
            str(tmp_path / "prepared.json"),
        ],
    )
    assert result.exit_code == 2
    assert "private-untrusted-authority" not in result.output
    database.assert_not_called()


@pytest.mark.parametrize("effort", ["ultra", "default", "HIGH"])
def test_prepare_unknown_effort_never_calls_application(
    effort: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare = Mock()
    monkeypatch.setattr(cli, "prepare_codex_compatibility_request", prepare)
    result = RUNNER.invoke(
        cli.codex_runtime_app,
        [
            "prepare-compatibility",
            "--model",
            "gpt-6-sol",
            "--effort",
            effort,
            "--source-commit",
            COMMIT,
            "--output-file",
            str(tmp_path / "request.json"),
        ],
    )
    assert result.exit_code == 2
    prepare.assert_not_called()


@pytest.mark.parametrize("boundary", ["relative", "symlink", "hardlink", "mode", "large", "fifo"])
def test_request_files_fail_closed_without_waiting_or_following_links(
    boundary: str, tmp_path: Path
) -> None:
    path = _file(tmp_path)
    if boundary == "relative":
        path = Path("request.json")
    elif boundary == "symlink":
        target = tmp_path / "link.json"
        target.symlink_to(path)
        path = target
    elif boundary == "hardlink":
        os.link(path, tmp_path / "hard.json")
    elif boundary == "mode":
        path.chmod(0o640)
    elif boundary == "large":
        path.write_bytes(b" " * (cli._MAX_REQUEST_BYTES + 1))
    elif boundary == "fifo":
        path = tmp_path / "fifo"
        os.mkfifo(path, 0o600)
    with pytest.raises(typer.BadParameter):
        cli.read_compatibility_request_file(path)


@pytest.mark.parametrize(
    "payload", [b'{"run_id":"x","run_id":"y"}', b'{"value":NaN}', b"[]", b"not json", b"\xff"]
)
def test_strict_json_loader_rejects_ambiguous_or_non_schema_payload(
    payload: bytes, tmp_path: Path
) -> None:
    path = _file(tmp_path)
    path.write_bytes(payload)
    with pytest.raises(typer.BadParameter):
        cli.read_compatibility_request_file(path)


@pytest.mark.parametrize("status", ["PASS", "FAIL", "NOT_RUN"])
@pytest.mark.parametrize("command", ["verify", "verify-scoped"])
def test_verify_renders_only_bounded_summary_and_validated_artifact_pointer(
    status: str, command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _database(monkeypatch)
    path = _file(tmp_path)
    request = cli.read_compatibility_request_file(path)
    report = SimpleNamespace(
        request=request,
        request_sha256="sha256:" + "4" * 64,
        runtime=SimpleNamespace(cli_version="0.160.0"),
        cases=(SimpleNamespace(status=status, raw_log="sensitive worker output"),),
        model_calls=1,
    )
    artifact = SimpleNamespace(
        job_id="job_" + "5" * 32,
        artifact_id="artifact_" + "6" * 32,
        artifact_revision_id="rev_" + "7" * 32,
        primary_file="report.json",
        primary_sha256="sha256:" + "8" * 64,
        manifest_sha256="sha256:" + "9" * 64,
        nas_path="/mnt/nas/private-path-not-public",
    )
    run = Mock(return_value=SimpleNamespace(report=report, artifact=artifact))
    target = (
        "run_codex_slot_compatibility" if command == "verify-scoped" else "run_codex_compatibility"
    )
    monkeypatch.setattr(cli, target, run)
    result = RUNNER.invoke(cli.codex_runtime_app, _arguments(command, path))
    assert result.exit_code == (0 if status == "PASS" else 1), result.output
    value = json.loads(result.output)
    assert value["artifact"]["revision_id"] == artifact.artifact_revision_id
    pointer = ArtifactMemberPointer.model_validate(value["report_pointer"])
    assert pointer.artifact_id == artifact.artifact_id
    assert pointer.artifact_revision_id == artifact.artifact_revision_id
    assert pointer.member_path == artifact.primary_file
    assert pointer.sha256 == artifact.primary_sha256
    assert pointer.schema_ref == "eom://schemas/workflow/codex-compatibility-report/1.0"
    assert pointer.media_type == "application/json"
    assert value["educational_quality"] == "NOT_EVALUATED"
    assert value["production_policy_changed"] is False
    assert "sensitive" not in result.output
    assert "/mnt/nas" not in result.output
    assert run.call_args.args == (engine, request)
    assert run.call_args.kwargs["settings"].runtime_source_commit == COMMIT
    engine.dispose.assert_called_once()


def test_verify_does_not_apply_expiry_preflight_to_completed_report_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _database(monkeypatch)
    path = _file(tmp_path)
    preflight = Mock(side_effect=AssertionError("application owns replay"))
    run = Mock(side_effect=ControlPlaneError("SAFE_RESULT", "sensitive error content"))
    monkeypatch.setattr(cli, "validate_codex_compatibility_preflight", preflight)
    monkeypatch.setattr(cli, "run_codex_compatibility", run)
    result = RUNNER.invoke(cli.codex_runtime_app, _arguments("verify", path))
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "SAFE_RESULT"
    assert "sensitive" not in result.output
    preflight.assert_not_called()


def test_verify_source_mismatch_fails_before_database_or_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _file(tmp_path)
    monkeypatch.setattr(
        Settings, "from_environment", lambda: Settings(runtime_source_commit="b" * 40)
    )
    database = Mock()
    run = Mock()
    monkeypatch.setattr(cli, "build_engine", database)
    monkeypatch.setattr(cli, "run_codex_compatibility", run)
    result = RUNNER.invoke(cli.codex_runtime_app, _arguments("verify", path))
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "CONTROL_COMPATIBILITY_RELEASE_MISMATCH"
    database.assert_not_called()
    run.assert_not_called()


def test_settings_failures_do_not_expose_environment_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _file(tmp_path)
    settings = Mock(side_effect=SettingsError("sensitive protected path"))
    monkeypatch.setattr(Settings, "from_environment", settings)
    result = RUNNER.invoke(cli.codex_runtime_app, _arguments("verify", path))
    assert result.exit_code == 1
    assert "sensitive" not in result.output
    assert json.loads(result.output)["error_code"] == "CONTROL_COMPATIBILITY_FAILED"


def test_artifact_publication_errors_expose_only_the_stable_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _database(monkeypatch)
    path = _file(tmp_path)
    run = Mock(side_effect=PlatformError(ErrorCode.ARTIFACT_COMMIT_FAILED, "sensitive NAS content"))
    monkeypatch.setattr(cli, "run_codex_compatibility", run)
    result = RUNNER.invoke(cli.codex_runtime_app, _arguments("verify", path))
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "ARTIFACT_COMMIT_FAILED"
    assert "sensitive" not in result.output
    engine.dispose.assert_called_once()


def test_maintenance_preflight_only_checks_owned_application_and_existing_readers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _database(monkeypatch)
    path = _file(tmp_path)
    events: list[str] = []
    application = Mock(side_effect=lambda *_args, **_kwargs: events.append("application"))
    database = Mock(side_effect=lambda *_args: events.append("database"))
    workers = Mock(side_effect=lambda: events.append("workers"))
    model = Mock(side_effect=AssertionError("preflight grants no execution"))
    monkeypatch.setattr(cli, "validate_codex_compatibility_preflight", application)
    monkeypatch.setattr(cli, "assert_codex_compatibility_database_quiescent", database)
    monkeypatch.setattr(cli, "assert_codex_workers_quiescent", workers)
    monkeypatch.setattr(cli, "run_codex_compatibility", model)
    result = RUNNER.invoke(cli.codex_runtime_app, _arguments("maintenance-preflight", path))
    assert result.exit_code == 0, result.output
    assert events == ["application", "database", "workers"]
    assert json.loads(result.output)["execution_authorized"] is False
    assert json.loads(result.output)["services_changed"] is False
    engine.dispose.assert_called_once()
    model.assert_not_called()


def test_scoped_preflight_excludes_unrelated_gpu_jobs_but_checks_worker_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _database(monkeypatch)
    path = _file(tmp_path)
    events: list[str] = []
    monkeypatch.setattr(
        cli,
        "validate_codex_compatibility_preflight",
        Mock(side_effect=lambda *_args, **_kwargs: events.append("application")),
    )
    monkeypatch.setattr(
        cli,
        "assert_codex_slot_compatibility_database_quiescent",
        Mock(side_effect=lambda *_args: events.append("scoped-database")),
    )
    global_reader = Mock(side_effect=AssertionError("global gate is not scoped"))
    monkeypatch.setattr(cli, "assert_codex_compatibility_database_quiescent", global_reader)
    monkeypatch.setattr(
        cli, "assert_codex_workers_quiescent", Mock(side_effect=lambda: events.append("workers"))
    )
    result = RUNNER.invoke(cli.codex_runtime_app, _arguments("scoped-preflight", path))
    assert result.exit_code == 0, result.output
    assert events == ["application", "scoped-database", "workers"]
    assert json.loads(result.output)["scope"] == "FIXED_SLOTS"
    assert json.loads(result.output)["execution_authorized"] is False
    global_reader.assert_not_called()
    engine.dispose.assert_called_once()


def test_expired_preflight_stops_before_database_work_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _database(monkeypatch)
    path = _file(tmp_path)
    application = Mock(
        side_effect=ControlPlaneError("CONTROL_COMPATIBILITY_REQUEST_EXPIRED", "private content")
    )
    database = Mock()
    monkeypatch.setattr(cli, "validate_codex_compatibility_preflight", application)
    monkeypatch.setattr(cli, "assert_codex_compatibility_database_quiescent", database)
    result = RUNNER.invoke(cli.codex_runtime_app, _arguments("maintenance-preflight", path))
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "CONTROL_COMPATIBILITY_REQUEST_EXPIRED"
    assert "private content" not in result.output
    database.assert_not_called()
    engine.dispose.assert_called_once()


def test_restoration_preflight_accepts_expired_request_without_database_or_binding_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        Settings, "from_environment", lambda: Settings(runtime_source_commit=COMMIT)
    )
    document = _request().model_dump(mode="json")
    now = datetime.now(UTC)
    document["created_at"] = (now - timedelta(hours=6)).isoformat().replace("+00:00", "Z")
    document["expires_at"] = (now - timedelta(hours=5)).isoformat().replace("+00:00", "Z")
    path = tmp_path / "expired-request.json"
    cli._write_request_file(path, load_compatibility_request(document))
    database = Mock(side_effect=AssertionError("restoration must not need PostgreSQL"))
    bindings = Mock(side_effect=AssertionError("restoration must not need fresh bindings/TTL"))
    workers = Mock()
    monkeypatch.setattr(cli, "build_engine", database)
    monkeypatch.setattr(cli, "validate_codex_compatibility_preflight", bindings)
    monkeypatch.setattr(cli, "assert_codex_workers_quiescent", workers)
    result = RUNNER.invoke(cli.codex_runtime_app, _arguments("restoration-preflight", path))
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["restoration_safe"] is True
    assert json.loads(result.output)["model_calls"] == 0
    database.assert_not_called()
    bindings.assert_not_called()
    workers.assert_called_once()


def test_restoration_preflight_busy_worker_fails_with_only_stable_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _database(monkeypatch)
    path = _file(tmp_path)
    workers = Mock(
        side_effect=ControlPlaneError("CODEX_COMPATIBILITY_WORKER_BUSY", "private worker log")
    )
    monkeypatch.setattr(cli, "assert_codex_workers_quiescent", workers)
    result = RUNNER.invoke(cli.codex_runtime_app, _arguments("restoration-preflight", path))
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "CODEX_COMPATIBILITY_WORKER_BUSY"
    assert "private worker log" not in result.output


def test_restoration_source_mismatch_does_not_claim_quiescence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _file(tmp_path)
    monkeypatch.setattr(
        Settings, "from_environment", lambda: Settings(runtime_source_commit="b" * 40)
    )
    workers = Mock()
    monkeypatch.setattr(cli, "assert_codex_workers_quiescent", workers)
    result = RUNNER.invoke(cli.codex_runtime_app, _arguments("restoration-preflight", path))
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "CONTROL_COMPATIBILITY_RELEASE_MISMATCH"
    workers.assert_not_called()
