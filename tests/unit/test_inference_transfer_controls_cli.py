"""Thin CLI/source fixtures; no protected environment or actual owner invocation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.control_service import ControlPlaneError
from eomctl import inference_transfer_controls as cli
from eomctl.control_plane import control_plane_app
from typer.testing import CliRunner

from tests.unit.inference_transfer_bootstrap_fixtures import PLATFORM_BYTES, RUBRIC_BYTES
from tests.unit.inference_transfer_control_invocation_fixtures import (
    prepared_receipt,
    release_result,
)


def _file(tmp_path: Path, name: str, value: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(value)
    path.chmod(0o600)
    return path


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    receipt = prepared_receipt()
    return (
        _file(
            tmp_path,
            "manifest.json",
            canonical_json_bytes(receipt.manifest.model_dump(mode="json")),
        ),
        _file(tmp_path, "platform.md", PLATFORM_BYTES),
        _file(tmp_path, "rubric.md", RUBRIC_BYTES),
    )


def test_registered_explicit_commands_have_no_actor_token_endpoint_or_clock_override() -> None:
    runner = CliRunner()
    result = runner.invoke(control_plane_app, ["inference-transfer", "--help"])
    assert result.exit_code == 0
    assert "prepare" in result.output and "release" in result.output
    for command in ("prepare", "release"):
        result = runner.invoke(cli.inference_transfer_control_app, [command, "--help"])
        assert result.exit_code == 0
        assert "access-token-fd" in result.output
        for forbidden in (
            "--actor",
            "--operator",
            "--access-token TEXT",
            "--endpoint",
            "--observed-at",
        ):
            assert forbidden not in result.output


def test_prepare_renders_closed_receipt_only_and_disposes_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, platform, rubric = _inputs(tmp_path)
    events: list[str] = []
    receipt = prepared_receipt()
    monkeypatch.setattr(
        cli, "require_inference_transfer_control_owner", lambda: events.append("UID")
    )

    def prepare(value: Any, **kwargs: Any) -> Any:
        events.append("PREPARE")
        assert value == receipt.manifest
        assert kwargs == {"platform_payload": PLATFORM_BYTES, "rubric_payload": RUBRIC_BYTES}
        return receipt

    monkeypatch.setattr(
        cli,
        "_owner",
        lambda fd: (
            SimpleNamespace(dispose=lambda: events.append("DISPOSE")),
            SimpleNamespace(prepare=prepare, release=lambda *_args: pytest.fail()),
        ),
    )
    result = CliRunner().invoke(
        cli.inference_transfer_control_app,
        [
            "prepare",
            "--manifest-file",
            str(manifest),
            "--platform-file",
            str(platform),
            "--rubric-file",
            str(rubric),
            "--access-token-fd",
            "9",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == receipt.model_dump(mode="json")
    assert events == ["UID", "PREPARE", "DISPOSE"]
    assert PLATFORM_BYTES.decode().strip() not in result.output
    assert RUBRIC_BYTES.decode().strip() not in result.output


def test_explicit_release_takes_exact_receipt_and_does_not_retry_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = prepared_receipt()
    path = _file(tmp_path, "receipt.json", canonical_json_bytes(receipt.model_dump(mode="json")))
    events: list[str] = []
    monkeypatch.setattr(cli, "require_inference_transfer_control_owner", lambda: None)

    def release(request: Any) -> Any:
        events.append("RELEASE")
        assert request.receipt == receipt
        return release_result(request)

    monkeypatch.setattr(
        cli,
        "_owner",
        lambda fd: (
            SimpleNamespace(dispose=lambda: events.append("DISPOSE")),
            SimpleNamespace(release=release),
        ),
    )
    args = ["release", "--receipt-file", str(path), "--access-token-fd", "9"]
    result = CliRunner().invoke(cli.inference_transfer_control_app, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["scientific_evaluation"] == "NOT_EVALUATED"
    assert events == ["RELEASE", "DISPOSE"]

    def uncertain(_request: Any) -> None:
        events.append("RELEASE")
        raise ControlPlaneError("CONTROL_REVISION_CONFLICT", "eom_at_secret instruction bytes")

    monkeypatch.setattr(
        cli,
        "_owner",
        lambda fd: (
            SimpleNamespace(dispose=lambda: events.append("DISPOSE")),
            SimpleNamespace(release=uncertain),
        ),
    )
    events.clear()
    failed = CliRunner().invoke(cli.inference_transfer_control_app, args)
    assert failed.exit_code == 1
    assert json.loads(failed.output) == {
        "status": "FAILED",
        "error_code": "CONTROL_REVISION_CONFLICT",
    }
    assert "secret" not in failed.output and "instruction" not in failed.output
    assert events == ["RELEASE", "DISPOSE"]


def test_wrong_uid_precedes_files_credentials_and_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied() -> None:
        raise ControlPlaneError("CONTROL_OWNER_IDENTITY_REQUIRED", "synthetic")

    monkeypatch.setattr(cli, "require_inference_transfer_control_owner", denied)
    monkeypatch.setattr(cli, "_read_json", lambda *_args: pytest.fail())
    monkeypatch.setattr(cli, "build_engine", lambda *_args: pytest.fail())
    with pytest.raises(ControlPlaneError):
        cli._owner(9)
    result = CliRunner().invoke(
        cli.inference_transfer_control_app,
        ["release", "--receipt-file", str(tmp_path / "missing"), "--access-token-fd", "9"],
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "CONTROL_OWNER_IDENTITY_REQUIRED"


def test_input_regular_utf8_exact_bounded_bytes(tmp_path: Path) -> None:
    path = _file(tmp_path, "small", "시험지".encode())
    assert cli._read_local_input(path, 9) == "시험지".encode()
    with pytest.raises(ValueError):
        cli._read_local_input(path, 8)
    with pytest.raises(ValueError):
        cli._read_local_input(Path("relative"), 99)


@pytest.mark.parametrize(
    "case", ["SYMLINK", "HARDLINK", "WRITABLE", "EMPTY", "NOT_UTF8", "DIRECTORY"]
)
def test_input_rejects_unsafe_metadata_or_encoding(tmp_path: Path, case: str) -> None:
    path = _file(tmp_path, "source", b"{}")
    if case == "SYMLINK":
        other = tmp_path / "link"
        other.symlink_to(path)
        path = other
    elif case == "HARDLINK":
        os.link(path, tmp_path / "other")
    elif case == "WRITABLE":
        path.chmod(0o666)
    elif case == "EMPTY":
        path.write_bytes(b"")
    elif case == "NOT_UTF8":
        path.write_bytes(b"\xff")
    elif case == "DIRECTORY":
        path = tmp_path
    with pytest.raises((ValueError, OSError)):
        cli._read_local_input(path, 99)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'])
def test_local_json_duplicate_and_non_json_constants_fail(tmp_path: Path, raw: bytes) -> None:
    with pytest.raises(ValueError):
        cli._read_json(_file(tmp_path, "invalid.json", raw), 99)


def test_changed_named_inode_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _file(tmp_path, "source", b"{}")
    other = _file(tmp_path, "other", b"{}")
    original = os.stat

    def changed(value: Any, **kwargs: Any) -> os.stat_result:
        return original(other if value == path else value, **kwargs)

    monkeypatch.setattr(os, "stat", changed)
    with pytest.raises(ValueError, match="changed"):
        cli._read_local_input(path, 99)


def test_unknown_exception_output_has_no_raw_exception_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "require_inference_transfer_control_owner", lambda: None)
    monkeypatch.setattr(
        cli, "_read_json", lambda *_args: (_ for _ in ()).throw(RuntimeError("eom_at_secret"))
    )
    result = CliRunner().invoke(
        cli.inference_transfer_control_app,
        ["release", "--receipt-file", "/synthetic/file", "--access-token-fd", "9"],
    )
    assert result.exit_code == 1
    assert json.loads(result.output) == {
        "status": "FAILED",
        "error_code": "CONTROL_BOOTSTRAP_UNAVAILABLE",
    }
    assert "secret" not in result.output


def test_unrecognized_control_error_code_cannot_leak_through_cli_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "require_inference_transfer_control_owner", lambda: None)
    monkeypatch.setattr(
        cli,
        "_read_json",
        lambda *_args: (_ for _ in ()).throw(ControlPlaneError("eom_at_secret", "secret")),
    )
    result = CliRunner().invoke(
        cli.inference_transfer_control_app,
        ["release", "--receipt-file", "/synthetic/file", "--access-token-fd", "9"],
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "CONTROL_BOOTSTRAP_UNAVAILABLE"
    assert "secret" not in result.output


def test_optional_contract_absence_preserves_control_cli_and_closes_new_command() -> None:
    # New Python interpreter proves imports are not satisfied by pytest's cache.
    source = textwrap.dedent(
        """
        import importlib.abc
        import json
        import sys

        class MissingOptionalContract(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == 'eom_api_contracts' or fullname.startswith('eom_api_contracts.'):
                    raise ModuleNotFoundError('optional API contracts deliberately absent')
                return None

        sys.meta_path.insert(0, MissingOptionalContract())
        from eomctl.control_plane import control_plane_app as app
        from eomctl import inference_transfer_controls as cli
        from typer.testing import CliRunner

        def forbidden(*args, **kwargs):
            raise AssertionError('missing optional composition touched credential/input/DB')

        cli._read_json = forbidden
        cli.build_engine = forbidden
        runner = CliRunner()
        for args in (['--help'], ['codex-runtime', '--help'],
                     ['inference-transfer', '--help']):
            checked = runner.invoke(app, args)
            assert checked.exit_code == 0, checked.output
        failed = runner.invoke(app, ['inference-transfer', 'release',
                                     '--receipt-file', '/synthetic/receipt',
                                     '--access-token-fd', '9'])
        assert failed.exit_code == 1, failed.output
        assert json.loads(failed.output) == {
            'status': 'FAILED', 'error_code': 'CONTROL_BOOTSTRAP_UNAVAILABLE'}
        assert 'eom_orchestrator.inference_transfer_control_auth' not in sys.modules
        print('OPTIONAL_CONTRACT_ABSENCE_FAIL_CLOSED')
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", source],
        env={
            "PYTHONPATH": os.pathsep.join(
                str(Path(value).resolve()) for value in sys.path if value
            ),
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C.UTF-8",
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OPTIONAL_CONTRACT_ABSENCE_FAIL_CLOSED"
