"""Authenticated owner command tests with synthetic files and fake composition only."""

from __future__ import annotations

import getpass
import json
import os
import stat
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_api import build_info
from eom_identifiers import canonical_json_bytes
from eom_orchestrator import (
    file_set_control_artifacts,
    inference_transfer_cpu_systemd,
    inference_transfer_experiment_artifacts,
    inference_transfer_owner_http,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.inference_transfer_experiment_execution import (
    CommittedInferenceTransferExperiment,
)
from eom_orchestrator.inference_transfer_experiment_ports import PublishedExperimentResult
from eom_orchestrator.inference_transfer_snapshot_staging import SnapshotReadFailure
from eom_orchestrator.settings import Settings
from eom_protocol.artifact_members import ArtifactMemberPointer
from eomctl import inference_transfer_controls as cli
from typer.testing import CliRunner

from tests.unit.inference_transfer_fixtures import embedding_model, sha
from tests.unit.inference_transfer_metadata_fixtures import metadata_request, metadata_result
from tests.unit.inference_transfer_snapshot_fixtures import (
    snapshot_header,
    snapshot_prepare,
    snapshot_prepare_result,
)
from tests.unit.test_inference_transfer_owner_http import ACTOR, principal


def local_file(tmp_path: Path, name: str, value: Any) -> Path:
    path = tmp_path / name
    path.write_bytes(canonical_json_bytes(value.model_dump(mode="json")))
    path.chmod(0o600)
    return path


def test_all_owner_commands_have_no_actor_secret_endpoint_clock_or_source_override() -> None:
    for command in ("inventory", "experiment", "metadata", "capacity", "prepare", "release"):
        result = CliRunner().invoke(cli.inference_transfer_control_app, [command, "--help"])
        assert result.exit_code == 0, result.output
        assert "access-token-fd" in result.output
        for forbidden in (
            "--actor",
            "--operator",
            "--password",
            "--endpoint",
            "--source-commit",
            "--observed-at",
        ):
            assert forbidden not in result.output


def test_non_tty_login_is_rejected_before_getpass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "require_inference_transfer_control_owner", lambda: None)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(getpass, "getpass", lambda *_args: pytest.fail("password requested"))
    with pytest.raises(ControlPlaneError) as caught:
        cli._session(None)
    assert caught.value.code == "CONTROL_AUTHORIZATION_REQUIRED"


def test_tty_getpass_fallback_warning_fails_without_sending_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "require_inference_transfer_control_owner", lambda: None)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

    def fallback(_prompt: str) -> str:
        warnings.warn("terminal unavailable", getpass.GetPassWarning, stacklevel=2)
        pytest.fail("echoing input fallback must not continue")

    monkeypatch.setattr(getpass, "getpass", fallback)
    monkeypatch.setattr(
        inference_transfer_owner_http.AuthenticatedInferenceTransferHttpSession,
        "login_guiadmin",
        lambda *_args: pytest.fail("login attempted"),
    )
    with pytest.raises(getpass.GetPassWarning):
        cli._session(None)


def test_tty_login_only_passes_secretstr_to_actual_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "require_inference_transfer_control_owner", lambda: None)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr(getpass, "getpass", lambda *_args: "synthetic-only")
    seen = []
    expected = object()

    def login(password: Any) -> Any:
        seen.append(password)
        return expected

    monkeypatch.setattr(
        inference_transfer_owner_http.AuthenticatedInferenceTransferHttpSession,
        "login_guiadmin",
        login,
    )
    assert cli._session(None) is expected
    assert seen[0].get_secret_value() == "synthetic-only" and "synthetic-only" not in repr(seen[0])


@pytest.mark.parametrize(
    "command,flags",
    [
        ("inventory", ["--prepare-file", "/synthetic/missing"]),
        (
            "experiment",
            [
                "--prepare-file",
                "/synthetic/missing",
                "--model-spec-file",
                "/synthetic/model",
                "--experiment-id",
                "x",
                "--experiment-revision-id",
                "x",
                "--execution-id",
                "x",
            ],
        ),
        ("capacity", ["--capacity-revision-id", "capacityrev_" + "a" * 32]),
    ],
)
def test_owner_uid_precedes_all_inputs_credentials_settings_and_engine(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    flags: list[str],
) -> None:
    def denied() -> None:
        raise ControlPlaneError("CONTROL_OWNER_IDENTITY_REQUIRED", "synthetic")

    monkeypatch.setattr(cli, "require_inference_transfer_control_owner", denied)
    monkeypatch.setattr(cli, "_read_json", lambda *_args: pytest.fail("input read"))
    monkeypatch.setattr(cli, "_session", lambda *_args: pytest.fail("credential read"))
    monkeypatch.setattr(cli, "build_engine", lambda *_args: pytest.fail("engine created"))
    result = CliRunner().invoke(cli.inference_transfer_control_app, [command, *flags])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "CONTROL_OWNER_IDENTITY_REQUIRED"


def test_inventory_only_returns_actual_index_no_engine_or_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare = snapshot_prepare(query_item_revision_ids=())
    prepared = snapshot_prepare_result(header=snapshot_header(prepare=prepare, actor_id=ACTOR))
    path = local_file(tmp_path, "prepare.json", prepare)
    seen: list[Any] = []
    monkeypatch.setattr(cli, "require_inference_transfer_control_owner", lambda: None)

    def read(actor: str, request: Any) -> Any:
        seen.append((actor, request))
        return prepared

    monkeypatch.setattr(cli, "_session", lambda fd: SimpleNamespace(read=principal, execute=read))
    monkeypatch.setattr(cli, "build_engine", lambda *_args: pytest.fail("engine created"))
    result = CliRunner().invoke(
        cli.inference_transfer_control_app, ["inventory", "--prepare-file", str(path)]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == prepared.model_dump(mode="json")
    assert seen == [(ACTOR, prepare)]
    assert "속력" not in result.output and "마찰" not in result.output


def test_metadata_calls_official_session_once_without_engine_or_source_synthesis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, response = metadata_request(), metadata_result()
    path = local_file(tmp_path, "metadata.json", request)
    calls: list[Any] = []
    monkeypatch.setattr(cli, "require_inference_transfer_control_owner", lambda: None)

    def resolve(value: Any) -> Any:
        calls.append(value)
        return response

    monkeypatch.setattr(cli, "_session", lambda fd: SimpleNamespace(resolve_metadata=resolve))
    monkeypatch.setattr(cli, "build_engine", lambda *_args: pytest.fail("engine created"))
    result = CliRunner().invoke(
        cli.inference_transfer_control_app,
        [
            "metadata",
            "--request-file",
            str(path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == response.model_dump(mode="json") and calls == [request]


def test_new_commands_preserve_optional_absence_fail_closed_before_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess
    import textwrap

    # A separate interpreter, not pytest's cached API contracts, checks the optional boundary.
    source = textwrap.dedent("""
        import importlib.abc
        import json
        import sys
        class Missing(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == 'eom_api_contracts' or fullname.startswith('eom_api_contracts.'):
                    raise ModuleNotFoundError('optional API contracts absent')
                return None
        sys.meta_path.insert(0, Missing())
        from eomctl.control_plane import control_plane_app
        from eomctl import inference_transfer_controls as cli
        from typer.testing import CliRunner
        def forbidden(*args, **kwargs):
            raise AssertionError('missing optional composition read file/credential/DB')
        cli._read_json = forbidden
        cli.build_engine = forbidden
        cli.getpass.getpass = forbidden
        runner = CliRunner()
        for command in ('inventory', 'experiment', 'metadata', 'capacity'):
            help_result = runner.invoke(cli.inference_transfer_control_app, [command, '--help'])
            assert help_result.exit_code == 0, help_result.output
        cases = [
            ['inventory', '--prepare-file', '/synthetic/prepare'],
            ['metadata', '--request-file', '/synthetic/metadata'],
            ['capacity', '--capacity-revision-id', 'capacityrev_' + 'a' * 32],
            ['experiment', '--prepare-file', '/synthetic/prepare',
             '--model-spec-file', '/synthetic/model', '--experiment-id', 'x',
             '--experiment-revision-id', 'x', '--execution-id', 'x']]
        for args in cases:
            denied = runner.invoke(cli.inference_transfer_control_app, args)
            assert denied.exit_code == 1, denied.output
            assert json.loads(denied.output) == {
                'status': 'FAILED', 'error_code': 'CONTROL_BOOTSTRAP_UNAVAILABLE'}
        print('OPTIONAL_AUTHENTICATED_OWNER_FAIL_CLOSED')
    """)
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
    assert result.stdout.strip() == "OPTIONAL_AUTHENTICATED_OWNER_FAIL_CLOSED"


def metadata(*, uid: int = 0, gid: int = 0, mode: int = 0o644, size: int = 66) -> Any:
    return SimpleNamespace(
        st_dev=1,
        st_ino=2,
        st_size=size,
        st_mode=stat.S_IFREG | mode,
        st_uid=uid,
        st_gid=gid,
        st_nlink=1,
        st_mtime_ns=5,
        st_ctime_ns=6,
    )


def identity_boundary(monkeypatch: pytest.MonkeyPatch, *, payload: bytes, info: Any) -> list[int]:
    closed: list[int] = []
    monkeypatch.setattr(
        build_info, "get_build_info", lambda: SimpleNamespace(source_commit="a" * 40)
    )

    def opened(path: Path, flags: int) -> int:
        assert path == Path("/etc/eom/workflow-runtime.env")
        assert flags & os.O_NOFOLLOW and flags & os.O_NONBLOCK
        return 73

    monkeypatch.setattr(os, "open", opened)
    monkeypatch.setattr(os, "fstat", lambda _fd: info)
    monkeypatch.setattr(os, "stat", lambda _path, **_kw: info)
    monkeypatch.setattr(os, "read", lambda _fd, _maximum: payload)
    monkeypatch.setattr(os, "close", lambda fd: closed.append(fd))
    return closed


def test_installed_embedded_identity_matches_protected_record_not_ambient_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"EOM_RUNTIME_SOURCE_COMMIT=" + b"a" * 40 + b"\n"
    closed = identity_boundary(monkeypatch, payload=payload, info=metadata(size=len(payload)))
    monkeypatch.setenv("EOM_RUNTIME_SOURCE_COMMIT", "b" * 40)
    assert cli._installed_source_commit() == "a" * 40 and closed == [73]


@pytest.mark.parametrize("changes", [{"uid": 990}, {"gid": 990}, {"mode": 0o664}, {"mode": 0o600}])
def test_protected_record_root_identity_and_exact_mode_are_required(
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, Any],
) -> None:
    payload = b"EOM_RUNTIME_SOURCE_COMMIT=" + b"a" * 40 + b"\n"
    closed = identity_boundary(
        monkeypatch, payload=payload, info=metadata(size=len(payload), **changes)
    )
    with pytest.raises(ValueError):
        cli._installed_source_commit()
    assert closed == [73]


@pytest.mark.parametrize(
    "payload",
    [
        b"EOM_RUNTIME_SOURCE_COMMIT=" + b"b" * 40 + b"\n",
        b"EOM_RUNTIME_SOURCE_COMMIT=" + b"a" * 40,
        b"EOM_RUNTIME_SOURCE_COMMIT=" + b"a" * 40 + b"\nOTHER=x\n",
    ],
)
def test_runtime_commit_drift_extra_lines_or_uncanonical_bytes_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
) -> None:
    closed = identity_boundary(monkeypatch, payload=payload, info=metadata(size=len(payload)))
    with pytest.raises(ValueError):
        cli._installed_source_commit()
    assert closed == [73]


def committed() -> CommittedInferenceTransferExperiment:
    return CommittedInferenceTransferExperiment(
        execution_id="embeddingexecution_" + "d" * 32,
        request_sha256=sha("a"),
        result_sha256=sha("b"),
        cpu_launch_count=0,
        published=PublishedExperimentResult(
            job_id="job_" + "c" * 32,
            manifest_sha256=sha("c"),
            result=ArtifactMemberPointer(
                artifact_id="artifact_" + "a" * 32,
                artifact_revision_id="rev_" + "b" * 32,
                member_path="result.json",
                schema_ref="eom://schemas/knowledge/item-inference-transfer-experiment/1.0",
                media_type="application/json",
                sha256=sha("b"),
            ),
        ),
    )


@pytest.mark.parametrize("failure", [False, True])
def test_explicit_experiment_composes_existing_owners_once_and_disposes_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: bool,
) -> None:
    prepare = local_file(tmp_path, "prepare.json", snapshot_prepare())
    model = local_file(tmp_path, "model.json", embedding_model())
    events: list[str] = []
    monkeypatch.setattr(
        cli, "require_inference_transfer_control_owner", lambda: events.append("UID")
    )
    monkeypatch.setattr(cli, "_session", lambda fd: SimpleNamespace(read=principal))
    monkeypatch.setattr(cli, "_installed_source_commit", lambda: "a" * 40)
    monkeypatch.setattr(
        Settings, "from_environment", lambda: Settings(runtime_source_commit="a" * 40)
    )
    engine = SimpleNamespace(dispose=lambda: events.append("DISPOSE"))
    monkeypatch.setattr(cli, "build_engine", lambda: engine)
    monkeypatch.setattr(
        file_set_control_artifacts, "ControlFileSetPublisher", lambda *_args: object()
    )
    monkeypatch.setattr(
        inference_transfer_cpu_systemd, "FixedCpuExperimentLauncher", lambda: object()
    )

    def execute(actor: Any, command: Any, **parameters: Any) -> Any:
        events.append("EXECUTE")
        assert actor.actor_id == ACTOR
        assert command.budget.maximum_queries == 4 and command.budget.top_k == 8
        assert parameters["execution_id"] == "embeddingexecution_" + "d" * 32
        if failure:
            raise SnapshotReadFailure("INFERENCE_TRANSFER_FORBIDDEN")
        return committed()

    def compose(**values: Any) -> Any:
        events.append("COMPOSE")
        assert values["source_commit"] == "a" * 40
        return SimpleNamespace(execute=execute)

    monkeypatch.setattr(
        inference_transfer_experiment_artifacts, "compose_inference_transfer_experiment", compose
    )
    result = CliRunner().invoke(
        cli.inference_transfer_control_app,
        [
            "experiment",
            "--prepare-file",
            str(prepare),
            "--model-spec-file",
            str(model),
            "--experiment-id",
            "inferenceexperiment_" + "a" * 32,
            "--experiment-revision-id",
            "inferenceexperimentrev_" + "a" * 32,
            "--execution-id",
            "embeddingexecution_" + "d" * 32,
        ],
    )
    assert result.exit_code == int(failure), result.output
    body = json.loads(result.output)
    if failure:
        assert body == {"status": "FAILED", "error_code": "INFERENCE_TRANSFER_FORBIDDEN"}
    else:
        assert body["status"] == "COMMITTED" and body["cpu_launch_count"] == 0
        assert body["human_transfer_evaluation"] == "NOT_EVALUATED"
        assert "records" not in body and "source_commit" not in body
    assert events == ["UID", "COMPOSE", "EXECUTE", "DISPOSE"]


def test_capacity_calls_public_owner_read_once_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[Any] = []
    expected = SimpleNamespace(
        model_dump=lambda **_kw: {"capacity_revision_id": "capacityrev_" + "a" * 32}
    )
    monkeypatch.setattr(cli, "require_inference_transfer_control_owner", lambda: None)

    def capacity(revision: str) -> Any:
        events.append(revision)
        return expected

    monkeypatch.setattr(
        cli,
        "_owner",
        lambda fd: (
            SimpleNamespace(dispose=lambda: events.append("DISPOSE")),
            SimpleNamespace(read_capacity_pin=capacity),
        ),
    )
    result = CliRunner().invoke(
        cli.inference_transfer_control_app,
        [
            "capacity",
            "--capacity-revision-id",
            "capacityrev_" + "a" * 32,
        ],
    )
    assert result.exit_code == 0, result.output
    assert events == ["capacityrev_" + "a" * 32, "DISPOSE"]
