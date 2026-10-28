"""Interactive preparation presentation with synthetic authentication/application ports."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from eom_api import build_info
from eom_api import settings as api_settings
from eom_catalog_contracts.external_item_learning_authorization import (
    ExternalItemLearningRoleSelection,
)
from eom_catalog_service.external_item_learning_preparation_service import (
    CreativeMaterializationCheck,
    PreparedExternalItemLearningSource,
)
from eom_operator_identity import PermissionKey
from eom_workflow_runner.external_item_learning_preparation import PreparedExternalItemLearning
from eom_workflow_runner.external_item_learning_start import StartedExternalItemLearning
from eomctl import creative_learning as cli
from jsonschema.exceptions import ValidationError
from pydantic import SecretStr
from typer.testing import CliRunner

from tests.unit.test_external_item_learning_work_contract import _work

ROOT = Path(__file__).resolve().parents[2]
OPERATOR = "operator_" + "a" * 32


def _case(monkeypatch, tmp_path):
    source = _work()["source"]
    request = {
        "schema_version": "external-item-learning-start/1.0",
        **{
            field: source[field]
            for field in (
                "import_id",
                "external_number",
                "source_revision_id",
                "observation_sha256",
                "selected_edition",
            )
        },
    }
    request_file = tmp_path / "selection.json"
    request_file.write_text(json.dumps(request))
    request_file.chmod(0o600)
    config_directory = tmp_path / "reviewed-config"
    (config_directory / "instructions").mkdir(parents=True)
    for name in ("platform.md", "external-item-learning.md"):
        member = config_directory / "instructions" / name
        member.write_bytes(
            (
                ROOT / "config/control-plane/external-item-learning-v1/instructions" / name
            ).read_bytes()
        )
        member.chmod(0o600)
    definition_file = tmp_path / "external-item-learning.yaml"
    definition_file.write_bytes(
        (ROOT / "config/workflows/external-item-learning.v1.yaml").read_bytes()
    )
    definition_file.chmod(0o600)
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(
        cli.pwd, "getpwnam", lambda _name: SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
    )
    password = Mock(return_value="synthetic-password-do-not-print")
    monkeypatch.setattr(cli.getpass, "getpass", password)
    monkeypatch.setattr(api_settings, "load_settings", lambda: api_settings.ApiSettings())
    monkeypatch.setattr(
        build_info, "get_build_info", lambda: SimpleNamespace(source_commit="a" * 40)
    )
    monkeypatch.setenv("EOM_RUNTIME_SOURCE_COMMIT", "a" * 40)
    monkeypatch.setattr(
        api_settings,
        "load_secrets",
        lambda: SimpleNamespace(
            database_url=SecretStr("postgresql+psycopg://test:test@127.0.0.1/test"),
            token_hash_key=SecretStr("synthetic-key-" * 4),
        ),
    )
    engine = Mock()
    engine.url = SimpleNamespace(host="127.0.0.1", port=5432, database="test")
    monkeypatch.setattr(cli, "build_engine", Mock(return_value=engine))
    auth = Mock()
    auth.login.return_value = SimpleNamespace(
        operator_id=OPERATOR,
        pair=SimpleNamespace(
            access_token="synthetic-access-do-not-print", session_id="apisession_" + "b" * 32
        ),
    )
    auth.authenticate_access.return_value = SimpleNamespace(
        operator=SimpleNamespace(operator_id=OPERATOR),
        session_id="apisession_" + "b" * 32,
        authenticated_at=datetime.now(UTC),
        password_change_required=False,
        permissions=frozenset({PermissionKey.EXECUTION_PRESET_MANAGE}),
    )
    monkeypatch.setattr(cli, "AuthService", Mock(return_value=auth))
    result = PreparedExternalItemLearningSource(
        "12345",
        "sha256:" + "0" * 64,
        PreparedExternalItemLearning(
            ExternalItemLearningRoleSelection(
                workflow_id="workflow_" + "1" * 32,
                step_run_id="steprun_" + "2" * 32,
                plan_id="execplan_" + "3" * 32,
                plan_sha256="sha256:" + "4" * 64,
                work_input_sha256="sha256:" + "0" * 64,
            ),
            True,
            True,
        ),
        CreativeMaterializationCheck(*(["sha256:" + "4" * 64] * 4), 4, 1024),
    )
    service = Mock()

    def construct(_engine, **kwargs):
        actual = kwargs["actor_provider"]()
        assert actual.operator_id == OPERATOR
        assert actual.session_id == auth.login.return_value.pair.session_id
        return service

    service.prepare.return_value = result
    monkeypatch.setattr(cli, "ExternalItemLearningPreparationService", construct)
    arguments = dict(
        request_file=request_file,
        config_directory=config_directory,
        definition_file=definition_file,
        source_commit="a" * 40,
        reviewed_at="2026-10-27T19:00:00Z",
        capacity_revision_id="capacityrev_" + "7" * 32,
        model="synthetic-reviewed-model",
        reasoning_effort="high",
        username="synthetic-operator",
        idempotency_key="synthetic-cli-prepare",
    )
    return SimpleNamespace(**locals())


def test_prepare_cli_uses_one_login_and_only_logs_out_its_own_session(
    monkeypatch, tmp_path, capsys
):
    value = _case(monkeypatch, tmp_path)
    cli.prepare_learning(**value.arguments)
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["status"] == "PREPARED_NOT_STARTED"
    assert report["model_invocations"] == 0 and report["test_session_logout"] == "PASS"
    assert value.auth.login.call_count == value.password.call_count == 1
    value.auth.logout.assert_called_once_with("apisession_" + "b" * 32, OPERATOR)
    assert value.service.prepare.call_count == 1
    assert "synthetic-password-do-not-print" not in output.out + output.err
    assert "synthetic-access-do-not-print" not in output.out + output.err


def test_prepare_failure_is_redacted_and_does_not_repeat_login(monkeypatch, tmp_path, capsys):
    value = _case(monkeypatch, tmp_path)
    value.service.prepare.side_effect = ValueError("synthetic-private-message")
    with pytest.raises(cli.typer.Exit):
        cli.prepare_learning(**value.arguments)
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["status"] == "FAILED" and report["test_session_logout"] == "PASS"
    assert value.auth.login.call_count == 1
    assert "synthetic-private-message" not in output.out + output.err


def test_noninteractive_input_cannot_capture_a_password(monkeypatch, tmp_path, capsys):
    value = _case(monkeypatch, tmp_path)
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    with pytest.raises(cli.typer.Exit):
        cli.prepare_learning(**value.arguments)
    assert json.loads(capsys.readouterr().out)["test_session_logout"] == "NOT_CREATED"
    value.password.assert_not_called()
    value.auth.login.assert_not_called()


def test_release_pin_mismatch_fails_before_login(monkeypatch, tmp_path, capsys):
    value = _case(monkeypatch, tmp_path)
    monkeypatch.setenv("EOM_RUNTIME_SOURCE_COMMIT", "b" * 40)
    with pytest.raises(cli.typer.Exit):
        cli.prepare_learning(**value.arguments)
    assert json.loads(capsys.readouterr().out)["status"] == "FAILED"
    value.password.assert_not_called()
    value.auth.login.assert_not_called()


def test_selection_rejects_authority_fields_and_unsafe_files(monkeypatch, tmp_path):
    value = _case(monkeypatch, tmp_path)
    request = json.loads(value.request_file.read_text())
    request["operator_id"] = OPERATOR
    value.request_file.write_text(json.dumps(request))
    with pytest.raises(ValidationError):
        cli._selection(value.request_file)
    value.request_file.chmod(0o666)
    with pytest.raises(ValueError):
        cli._read_reviewed(value.request_file, 16 * 1024)


def test_prepare_help_has_no_start_switch():
    result = CliRunner().invoke(cli.learning_app, ["prepare", "--help"])
    assert result.exit_code == 0
    assert "--request-file" in result.stdout and "--username" in result.stdout
    assert "--start" not in result.stdout


def test_start_is_a_separate_command_and_not_an_implicit_prepare_switch():
    result = CliRunner().invoke(cli.learning_app, ["start", "--help"])
    assert result.exit_code == 0
    assert "--selection-file" in result.stdout and "--username" in result.stdout
    assert "--config-directory" not in result.stdout


def test_start_cli_authenticates_actual_operator_and_does_not_accept_or_publish(
    monkeypatch, tmp_path, capsys
):
    value = _case(monkeypatch, tmp_path)
    selection = value.result.workflow.selection
    selected = tmp_path / "prepared-role.json"
    selected.write_text(selection.model_dump_json())
    selected.chmod(0o600)
    sessions = MagicMock()
    monkeypatch.setattr(cli, "build_session_factory", Mock(return_value=sessions))
    monkeypatch.setattr(cli, "ExternalItemPreviewProjectionService", Mock())
    monkeypatch.setattr(cli, "CatalogExternalItemLearningSourceAuthorizer", Mock())
    monkeypatch.setattr(cli, "ControlFileSetPublisher", Mock())
    authorize = Mock(return_value=OPERATOR)
    monkeypatch.setattr(cli, "authorize_external_creative_learning_preparation", authorize)
    start = Mock(
        return_value=StartedExternalItemLearning(selection, "wfcmd_" + "c" * 32, "PENDING", True)
    )
    monkeypatch.setattr(cli, "start_prepared_external_item_learning", start)
    cli.start_learning(selection_file=selected, username="synthetic-operator")
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["status"] == "START_COMMAND_STORED" and report["command_created"]
    assert report["item_acceptance"] == report["graph_publication"] == "NOT_PERFORMED"
    assert report["test_session_logout"] == "PASS"
    assert value.password.call_count == value.auth.login.call_count == 1
    assert authorize.call_count == value.auth.authenticate_access.call_count == 2
    assert start.call_args.kwargs["operator_id"] == OPERATOR
    assert start.call_args.kwargs["selection"] == selection
    value.service.prepare.assert_not_called()
    assert "synthetic-password-do-not-print" not in output.out + output.err
    assert "synthetic-access-do-not-print" not in output.out + output.err
