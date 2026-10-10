"""Synthetic CLI composition only: no authentication, database, NAS or models."""

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
from eom_catalog_contracts.inference_transfer_human_review import (
    HUMAN_REVIEW_BUNDLE_SCHEMA_REF,
    HUMAN_REVIEW_RECORD_SCHEMA_REF,
    MAX_HUMAN_COMMAND_BYTES,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator import (
    inference_transfer_human_review,
    inference_transfer_human_review_artifacts,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.settings import Settings
from eom_protocol.artifact_members import ArtifactMemberPointer
from eomctl import inference_transfer_controls as cli
from typer.testing import CliRunner

from tests.unit.inference_transfer_human_review_fixtures import SOURCE_COMMIT, Harness, member

COMMANDS = ("human-bundle", "human-evaluate", "human-read")


def local_file(tmp_path: Path, name: str, value: Any) -> Path:
    path = tmp_path / name
    path.write_bytes(canonical_json_bytes(value))
    path.chmod(0o600)
    return path


def fake_composition(monkeypatch: pytest.MonkeyPatch, harness: Harness, events: list[str]) -> None:
    monkeypatch.setattr(
        cli, "require_inference_transfer_control_owner", lambda: events.append("UID")
    )
    monkeypatch.setattr(
        cli,
        "_human_owner",
        lambda _fd: (
            SimpleNamespace(dispose=lambda: events.append("DISPOSE")),
            harness.owner,
            SOURCE_COMMIT,
        ),
    )


@pytest.mark.parametrize("command", COMMANDS)
def test_human_help_exposes_no_authority_secret_or_source_override(command: str) -> None:
    result = CliRunner().invoke(cli.inference_transfer_control_app, [command, "--help"])
    assert result.exit_code == 0, result.output
    assert "access-token-fd" in result.output
    for forbidden in ("--actor", "--operator", "--password", "--endpoint", "--source-commit"):
        assert forbidden not in result.output


@pytest.mark.parametrize("command", COMMANDS)
def test_human_wrong_uid_precedes_input_auth_and_engine(
    command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied() -> None:
        raise ControlPlaneError("CONTROL_OWNER_IDENTITY_REQUIRED", "synthetic private content")

    monkeypatch.setattr(cli, "require_inference_transfer_control_owner", denied)
    monkeypatch.setattr(cli, "_read_json", lambda *_args: pytest.fail("input read"))
    monkeypatch.setattr(cli, "_session", lambda *_args: pytest.fail("authentication"))
    monkeypatch.setattr(cli, "build_engine", lambda: pytest.fail("database"))
    option = "--pointer-file" if command == "human-read" else "--command-file"
    result = CliRunner().invoke(
        cli.inference_transfer_control_app,
        [command, option, "/synthetic/missing", "--access-token-fd", "9"],
    )
    assert result.exit_code == 1
    assert json.loads(result.output) == {
        "status": "FAILED",
        "error_code": "CONTROL_OWNER_IDENTITY_REQUIRED",
    }
    assert "private" not in result.output


@pytest.mark.parametrize("command", COMMANDS)
def test_invalid_human_input_fails_before_composition(
    command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = local_file(tmp_path, "invalid.json", {"caller_role": "ADMIN", "private": "secret"})
    monkeypatch.setattr(cli, "require_inference_transfer_control_owner", lambda: None)
    monkeypatch.setattr(cli, "_human_owner", lambda *_args: pytest.fail("owner composition"))
    option = "--pointer-file" if command == "human-read" else "--command-file"
    result = CliRunner().invoke(cli.inference_transfer_control_app, [command, option, str(path)])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "INFERENCE_TRANSFER_HUMAN_INPUT_INVALID"
    assert "secret" not in result.output


def test_human_bundle_publishes_once_and_returns_roundtrip_member_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = Harness()
    events: list[str] = []
    fake_composition(monkeypatch, harness, events)
    path = local_file(tmp_path, "bundle-command.json", harness.command.model_dump(mode="json"))
    result = CliRunner().invoke(
        cli.inference_transfer_control_app,
        ["human-bundle", "--command-file", str(path), "--access-token-fd", "9"],
    )
    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    pointer = ArtifactMemberPointer.model_validate(value["artifact"])
    assert value["status"] == "COMMITTED"
    assert pointer.member_path == "result.json"
    assert pointer.schema_ref == HUMAN_REVIEW_BUNDLE_SCHEMA_REF
    assert "logical_name" not in value["artifact"]
    assert len(harness.publisher.calls) == 1
    assert harness.publisher.calls[0]["source_commit"] == SOURCE_COMMIT
    assert set(value) == {"status", "job_id", "artifact", "manifest_sha256"}
    assert events == ["UID", "DISPOSE"]


def test_human_evaluation_publishes_submitted_label_without_printing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = Harness()
    events: list[str] = []
    bundle = member(harness.owner.publish_bundle(harness.command, source_commit=SOURCE_COMMIT))
    command = harness.record_command(bundle)
    fake_composition(monkeypatch, harness, events)
    path = local_file(tmp_path, "record-command.json", command.model_dump(mode="json"))
    result = CliRunner().invoke(
        cli.inference_transfer_control_app, ["human-evaluate", "--command-file", str(path)]
    )
    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    pointer = ArtifactMemberPointer.model_validate(value["artifact"])
    assert pointer.schema_ref == HUMAN_REVIEW_RECORD_SCHEMA_REF
    assert len(harness.publisher.calls) == 2
    assert command.evaluation.reason not in result.output
    assert command.evaluation.label not in result.output
    assert events == ["UID", "DISPOSE"]


@pytest.mark.parametrize("kind", ["BUNDLE", "RECORD"])
def test_human_read_returns_only_current_authorized_canonical_document(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = Harness()
    events: list[str] = []
    bundle = member(harness.owner.publish_bundle(harness.command, source_commit=SOURCE_COMMIT))
    pointer = bundle
    if kind == "RECORD":
        pointer = member(
            harness.owner.publish_evaluation(
                harness.record_command(bundle), source_commit=SOURCE_COMMIT
            )
        )
    fake_composition(monkeypatch, harness, events)
    path = local_file(tmp_path, "pointer.json", pointer.model_dump(mode="json"))
    result = CliRunner().invoke(
        cli.inference_transfer_control_app, ["human-read", "--pointer-file", str(path)]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == json.loads(
        harness.artifacts.payloads[(pointer.artifact_id, pointer.artifact_revision_id)]
    )
    assert events == ["UID", "DISPOSE"]


def test_human_read_rejects_other_artifact_schema_before_authentication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
        member_path="result.json",
        schema_ref="eom://schemas/knowledge/inference-transfer-experiment-result/1.0",
        media_type="application/json",
        sha256="sha256:" + "c" * 64,
    )
    path = local_file(tmp_path, "pointer.json", pointer.model_dump(mode="json"))
    monkeypatch.setattr(cli, "require_inference_transfer_control_owner", lambda: None)
    monkeypatch.setattr(cli, "_human_owner", lambda *_args: pytest.fail("owner composition"))
    result = CliRunner().invoke(
        cli.inference_transfer_control_app, ["human-read", "--pointer-file", str(path)]
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "INFERENCE_TRANSFER_HUMAN_INPUT_INVALID"


@pytest.mark.parametrize("changed", [{"member_path": "other.json"}, {"media_type": "text/plain"}])
def test_human_read_known_schema_wrong_member_or_media_precedes_auth_and_database(
    changed: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
        member_path="result.json",
        schema_ref=HUMAN_REVIEW_BUNDLE_SCHEMA_REF,
        media_type="application/json",
        sha256="sha256:" + "c" * 64,
    )
    path = local_file(tmp_path, "pointer.json", pointer.model_dump(mode="json") | changed)
    monkeypatch.setattr(cli, "require_inference_transfer_control_owner", lambda: None)
    monkeypatch.setattr(cli, "_human_owner", lambda *_args: pytest.fail("owner composition"))
    monkeypatch.setattr(cli, "_session", lambda *_args: pytest.fail("authentication"))
    monkeypatch.setattr(cli, "build_engine", lambda: pytest.fail("database"))
    result = CliRunner().invoke(
        cli.inference_transfer_control_app, ["human-read", "--pointer-file", str(path)]
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "INFERENCE_TRANSFER_HUMAN_INPUT_INVALID"


@pytest.mark.parametrize("kind", ["BUNDLE", "RECORD"])
def test_human_read_revocation_withholds_document_and_disposes_engine(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = Harness()
    events: list[str] = []
    bundle = member(harness.owner.publish_bundle(harness.command, source_commit=SOURCE_COMMIT))
    pointer = bundle
    if kind == "RECORD":
        pointer = member(
            harness.owner.publish_evaluation(
                harness.record_command(bundle), source_commit=SOURCE_COMMIT
            )
        )
    harness.principal.value = harness.principal.value.model_copy(
        update={"effective_permissions": ()}
    )
    fake_composition(monkeypatch, harness, events)
    path = local_file(tmp_path, "pointer.json", pointer.model_dump(mode="json"))
    result = CliRunner().invoke(
        cli.inference_transfer_control_app, ["human-read", "--pointer-file", str(path)]
    )
    assert result.exit_code == 1
    assert json.loads(result.output) == {
        "status": "FAILED",
        "error_code": "INFERENCE_TRANSFER_HUMAN_AUTHORIZATION_REQUIRED",
    }
    assert "sources" not in result.output and "evaluation" not in result.output
    assert events == ["UID", "DISPOSE"]


@pytest.mark.parametrize("failure", ["KNOWN", "UNKNOWN"])
def test_human_publication_failure_is_not_retried_or_printed_raw(
    failure: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = Harness()
    events: list[str] = []
    fake_composition(monkeypatch, harness, events)

    def rejected(_command: Any, *, source_commit: str) -> None:
        assert source_commit == SOURCE_COMMIT
        events.append("PUBLISH")
        if failure == "KNOWN":
            raise ControlPlaneError("INFERENCE_TRANSFER_HUMAN_SOURCE_CHANGED", "private secret")
        raise ControlPlaneError("eom_at_secret", "private secret")

    monkeypatch.setattr(harness.owner, "publish_bundle", rejected)
    path = local_file(tmp_path, "command.json", harness.command.model_dump(mode="json"))
    result = CliRunner().invoke(
        cli.inference_transfer_control_app, ["human-bundle", "--command-file", str(path)]
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == (
        "INFERENCE_TRANSFER_HUMAN_SOURCE_CHANGED"
        if failure == "KNOWN"
        else "INFERENCE_TRANSFER_HUMAN_UNAVAILABLE"
    )
    assert events == ["UID", "PUBLISH", "DISPOSE"]
    assert "secret" not in result.output and "private" not in result.output


def test_human_input_is_bounded_before_auth_or_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "oversized.json"
    path.write_bytes(b" " * (MAX_HUMAN_COMMAND_BYTES + 1))
    path.chmod(0o600)
    monkeypatch.setattr(cli, "require_inference_transfer_control_owner", lambda: None)
    monkeypatch.setattr(cli, "_human_owner", lambda *_args: pytest.fail("owner composition"))
    result = CliRunner().invoke(
        cli.inference_transfer_control_app, ["human-bundle", "--command-file", str(path)]
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "INFERENCE_TRANSFER_HUMAN_INPUT_INVALID"


def test_human_composition_reuses_one_http_session_and_existing_owner_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    engine = SimpleNamespace(dispose=lambda: events.append("DISPOSE"))
    session, artifacts, publisher, owner = object(), object(), object(), object()
    monkeypatch.setattr(
        cli, "require_inference_transfer_control_owner", lambda: events.append("UID")
    )
    monkeypatch.setattr(cli, "_installed_source_commit", lambda: SOURCE_COMMIT)
    monkeypatch.setattr(
        Settings,
        "from_environment",
        lambda: SimpleNamespace(runtime_source_commit=SOURCE_COMMIT),
    )

    def observed_session(fd: int | None) -> object:
        assert fd == 9
        events.append("AUTH")
        return session

    def observed_engine() -> SimpleNamespace:
        events.append("ENGINE")
        return engine

    monkeypatch.setattr(cli, "_session", observed_session)
    monkeypatch.setattr(cli, "build_engine", observed_engine)
    monkeypatch.setattr(cli, "ControlArtifactPublisher", lambda _engine, _settings: publisher)
    monkeypatch.setattr(
        inference_transfer_human_review_artifacts,
        "OwnedHumanReviewArtifacts",
        lambda _engine: artifacts,
    )

    def compose(**kwargs: Any) -> Any:
        assert kwargs == {
            "principal": session,
            "snapshots": session,
            "comparisons": session,
            "artifacts": artifacts,
            "publisher": publisher,
        }
        return owner

    monkeypatch.setattr(
        inference_transfer_human_review, "AuthenticatedInferenceTransferHumanReviewOwner", compose
    )
    actual_engine, actual_owner, actual_commit = cli._human_owner(9)
    assert id(actual_engine) == id(engine)
    assert actual_owner is owner
    assert actual_commit == SOURCE_COMMIT
    assert events == ["UID", "AUTH", "ENGINE"]


def test_human_composition_failure_disposes_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(cli, "require_inference_transfer_control_owner", lambda: None)
    monkeypatch.setattr(cli, "_installed_source_commit", lambda: SOURCE_COMMIT)
    monkeypatch.setattr(
        Settings,
        "from_environment",
        lambda: SimpleNamespace(runtime_source_commit=SOURCE_COMMIT),
    )
    monkeypatch.setattr(cli, "_session", lambda _fd: object())
    monkeypatch.setattr(
        cli, "build_engine", lambda: SimpleNamespace(dispose=lambda: events.append("DISPOSE"))
    )

    def failed(*_args: Any) -> None:
        raise RuntimeError("synthetic constructor failure")

    monkeypatch.setattr(cli, "ControlArtifactPublisher", failed)
    with pytest.raises(RuntimeError):
        cli._human_owner(9)
    assert events == ["DISPOSE"]


def test_human_installed_identity_mismatch_precedes_authentication_and_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "require_inference_transfer_control_owner", lambda: None)
    monkeypatch.setattr(cli, "_installed_source_commit", lambda: SOURCE_COMMIT)
    monkeypatch.setattr(
        Settings, "from_environment", lambda: SimpleNamespace(runtime_source_commit="f" * 40)
    )
    monkeypatch.setattr(cli, "_session", lambda _fd: pytest.fail("authentication"))
    monkeypatch.setattr(cli, "build_engine", lambda: pytest.fail("database"))
    with pytest.raises(ControlPlaneError) as error:
        cli._human_owner(9)
    assert error.value.code == "INFERENCE_TRANSFER_HUMAN_INPUT_INVALID"


def test_optional_human_contract_absence_preserves_help_and_fails_before_input() -> None:
    source = textwrap.dedent("""
        import importlib.abc
        import json
        import sys
        class Missing(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == 'eom_catalog_contracts.inference_transfer_human_review':
                    raise ModuleNotFoundError('optional human contract absent')
                return None
        sys.meta_path.insert(0, Missing())
        from eomctl import inference_transfer_controls as cli
        from typer.testing import CliRunner
        def forbidden(*args, **kwargs):
            raise AssertionError('optional absence touched input/auth/DB')
        cli.require_inference_transfer_control_owner = lambda: None
        cli._read_json = forbidden
        cli._session = forbidden
        cli.build_engine = forbidden
        runner = CliRunner()
        assert runner.invoke(cli.inference_transfer_control_app, ['--help']).exit_code == 0
        for command in ('human-bundle', 'human-evaluate', 'human-read'):
            option = '--pointer-file' if command == 'human-read' else '--command-file'
            failed = runner.invoke(cli.inference_transfer_control_app,
                                   [command, option, '/synthetic/input'])
            assert failed.exit_code == 1, failed.output
            assert json.loads(failed.output) == {
                'status': 'FAILED', 'error_code': 'INFERENCE_TRANSFER_HUMAN_UNAVAILABLE'}
        print('HUMAN_OPTIONAL_ABSENCE_FAIL_CLOSED')
    """)
    result = subprocess.run(
        [sys.executable, "-c", source],
        env={
            "PYTHONPATH": os.pathsep.join(str(Path(path).resolve()) for path in sys.path if path),
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C.UTF-8",
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "HUMAN_OPTIONAL_ABSENCE_FAIL_CLOSED"
