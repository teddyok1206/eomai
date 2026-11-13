"""Catalog UID starts one fixed unit; parser cannot choose commands, paths or authority."""

from __future__ import annotations

import io
import os
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_catalog_service import native_exam_preparer as adapter
from eom_catalog_service import native_exam_preparer_worker as worker
from eom_hwpx_contracts.native_exam_preparation import NativeExamFilePreparationRequest
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.test_material_native_preparation import SyntheticNativeTool

ROOT = Path(__file__).resolve().parents[2]
INSTANCE = "nativeexam_" + "1" * 32
PYTHON = Path("/opt/eom/native-exam/runtime/bin/python")


def case(tmp_path, monkeypatch):
    # Synthetic producer verifies fixed transport only; actual parser conservation
    # remains in the Builder's separately executed native corpus qualification.
    data = b"PK\x03\x04synthetic-native-source"
    request = NativeExamFilePreparationRequest(
        expected_source_sha256=sha256_bytes(data),
        source_format="HWPX",
        source_role="MAIN",
        expected_numbers=(1, 2),
        converter=None,
    )
    prepared = SyntheticNativeTool()(
        data, request=request, workspace=tmp_path / "produced", python=PYTHON
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in prepared.members:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100600 << 16
            archive.writestr(info, (prepared.workspace / name).read_bytes())
    result, payload = prepared.result, output.getvalue()
    tmp_path.chmod(0o700)
    monkeypatch.setattr(adapter, "require_native_exam_runtime_python", lambda path: PYTHON)
    monkeypatch.setattr(worker, "require_native_exam_runtime_python", lambda path: PYTHON)
    principals = adapter.NativeExamWorkspacePrincipals(os.geteuid(), os.geteuid(), os.getegid())
    monkeypatch.setattr(adapter, "native_exam_workspace_principals", lambda: principals)
    monkeypatch.setattr(worker, "native_exam_workspace_principals", lambda: principals)
    return data, request, result, payload


def test_catalog_adapter_starts_only_fixed_unit_then_validates_existing_transport(
    tmp_path, monkeypatch
):
    data, request, expected, payload = case(tmp_path, monkeypatch)
    calls = []
    root = tmp_path / "jobs"

    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        job = root / INSTANCE
        assert (job / "input.native").read_bytes() == data
        assert (job / "request.json").read_bytes() == canonical_json_bytes(
            request.model_dump(mode="json")
        )
        (job / "result.zip").write_bytes(payload)
        (job / "result.zip").chmod(0o640)
        return subprocess.CompletedProcess(arguments, 0, b"", b"")

    port = adapter.SystemdNativeExamFilePreparer(
        root=root, run=run, token_hex=lambda size: "1" * 32
    )
    result = port(data, request=request, workspace=tmp_path / "output", python=PYTHON)
    assert result.result == expected
    assert not (root / INSTANCE).exists()
    assert calls[0][0] == [
        "/usr/bin/systemctl",
        "--no-ask-password",
        "start",
        f"eom-native-exam-preparer@{INSTANCE}.service",
    ]
    assert calls[0][1]["timeout"] == 120
    assert not {"EOM_DATABASE_URL", "PGPASSWORD", "HOME"} & calls[0][1]["env"].keys()


@pytest.mark.parametrize("failure", ["timeout", "returncode", "changed", "bad_result", "symlink"])
def test_failed_or_unknown_start_retains_work_and_does_not_publish(tmp_path, monkeypatch, failure):
    data, request, _, payload = case(tmp_path, monkeypatch)
    root = tmp_path / "jobs"

    def run(arguments, **kwargs):
        job = root / INSTANCE
        if failure == "timeout":
            raise subprocess.TimeoutExpired(arguments, 120)
        if failure == "changed":
            (job / "input.native").write_bytes(data + b"changed")
        if failure == "symlink":
            (job / "result.zip").symlink_to(tmp_path / "outside")
        else:
            (job / "result.zip").write_bytes(b"invalid" if failure == "bad_result" else payload)
            (job / "result.zip").chmod(0o640)
        return subprocess.CompletedProcess(arguments, 1 if failure == "returncode" else 0, b"", b"")

    port = adapter.SystemdNativeExamFilePreparer(
        root=root, run=run, token_hex=lambda size: "1" * 32
    )
    with pytest.raises((ValueError, OSError)):
        port(data, request=request, workspace=tmp_path / "output", python=PYTHON)
    assert (root / INSTANCE).is_dir()
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("value", ["../escape", "1" * 31, "1" * 32 + ".service", "z" * 32])
def test_invalid_instance_cannot_select_a_unit_or_workspace(tmp_path, monkeypatch, value):
    data, request, _, _ = case(tmp_path, monkeypatch)
    run = Mock()
    port = adapter.SystemdNativeExamFilePreparer(
        root=tmp_path / "jobs", run=run, token_hex=lambda size: value
    )
    with pytest.raises(ValueError, match="INSTANCE_INVALID"):
        port(data, request=request, workspace=tmp_path / "output", python=PYTHON)
    run.assert_not_called()
    assert not (tmp_path / "jobs").exists()


def test_untrusted_or_changed_input_is_rejected_before_unit_start(tmp_path, monkeypatch):
    data, request, _, _ = case(tmp_path, monkeypatch)
    run = Mock()
    port = adapter.SystemdNativeExamFilePreparer(root=tmp_path / "jobs", run=run)
    with pytest.raises(ValueError, match="INPUT_INVALID"):
        port(data + b"changed", request=request, workspace=tmp_path / "output", python=PYTHON)
    run.assert_not_called()


def staged_worker(tmp_path, request, data):
    root = tmp_path / "jobs"
    root.mkdir(mode=0o700)
    job = root / INSTANCE
    job.mkdir(mode=0o770)
    job.chmod(0o770)
    for name, raw in (
        ("request.json", canonical_json_bytes(request.model_dump(mode="json"))),
        ("input.native", data),
    ):
        (job / name).write_bytes(raw)
        (job / name).chmod(0o640)
    return root, job


def test_fixed_worker_executes_protected_parser_with_clean_cpu_only_environment(
    tmp_path, monkeypatch
):
    data, request, _, payload = case(tmp_path, monkeypatch)
    root, job = staged_worker(tmp_path, request, data)
    captured = []

    def run(arguments, **kwargs):
        captured.append((arguments, kwargs))
        kwargs["stdout"].write(payload)
        return subprocess.CompletedProcess(arguments, 0, b"", b"")

    monkeypatch.setenv("PGPASSWORD", "not-forwarded")
    output = worker.prepare_workspace(INSTANCE, root=root, python=PYTHON, run=run)
    assert output == job / "result.zip" and output.read_bytes() == payload
    assert output.stat().st_nlink == 1 and output.stat().st_mode & 0o777 == 0o640
    arguments, options = captured[0]
    assert arguments[:6] == [
        str(PYTHON),
        "-I",
        "-B",
        "-m",
        "eom_hwpx_builder.native_exam_tool",
        "--request-json",
    ]
    assert options["input"] == data and options["stderr"] == subprocess.DEVNULL
    assert options["timeout"] == 105
    assert options["env"]["CUDA_VISIBLE_DEVICES"] == ""
    assert not {"PGPASSWORD", "EOM_DATABASE_URL", "CODEX_HOME"} & options["env"].keys()
    assert "systemd-run" not in arguments


@pytest.mark.parametrize(
    "kind", ["hash", "symlink", "permissions", "hardlink", "noncanonical", "unknownfield"]
)
def test_worker_invalid_local_inputs_never_invoke_parser(tmp_path, monkeypatch, kind):
    data, request, _, _ = case(tmp_path, monkeypatch)
    root, job = staged_worker(tmp_path, request, data)
    if kind == "hash":
        (job / "input.native").write_bytes(data + b"changed")
    elif kind == "symlink":
        (job / "input.native").unlink()
        (job / "input.native").symlink_to(tmp_path / "outside")
    elif kind == "permissions":
        (job / "input.native").chmod(0o644)
    elif kind == "hardlink":
        os.link(job / "input.native", job / "also-input")
    elif kind == "noncanonical":
        (job / "request.json").write_bytes((job / "request.json").read_bytes() + b"\n")
    else:
        (job / "request.json").write_bytes(
            canonical_json_bytes(request.model_dump(mode="json") | {"executable": "/bin/sh"})
        )
    run = Mock()
    with pytest.raises((ValueError, OSError)):
        worker.prepare_workspace(INSTANCE, root=root, python=PYTHON, run=run)
    run.assert_not_called()


def test_fixed_unit_and_polkit_have_no_arbitrary_root_or_storage_capability():
    unit = (ROOT / "infra/systemd/eom-native-exam-preparer@.service").read_text()
    rule = (ROOT / "infra/polkit/45-eom-native-exam-preparer.rules").read_text()
    assert "User=eom-image" in unit and "Group=eom-api" in unit
    assert "ProtectProc=invisible" in unit
    assert "InaccessiblePaths=/var/lib/eom-catalog-api" in unit
    assert (
        "BindPaths=/var/lib/eom-catalog-api/staging/native-exam/%i:/run/eom-native-exam/%i" in unit
    )
    for value in (
        "NoNewPrivileges=true",
        "PrivateNetwork=true",
        "PrivateDevices=true",
        "ProtectSystem=strict",
        "MemoryMax=2G",
        "CPUQuota=200%",
        "LimitFSIZE=536870912",
        "TimeoutStartSec=115",
        "KillMode=control-group",
    ):
        assert value in unit
    for denied in ("/mnt/nas", "/etc/eom", "/run/postgresql", "/run/eom", "/srv/eom/worker-homes"):
        assert denied in unit
    assert "systemd-run" not in unit and "sudo" not in unit
    assert 'subject.user === "eom-catalog-manager"' in rule
    assert 'action.lookup("verb") === "start"' in rule
    assert "nativeexam_[0-9a-f]{32}" in rule
    assert "manage-unit-files" not in rule and "manage-unit-transient" not in rule


def test_worker_failure_log_is_stable_and_does_not_expose_source_or_diagnostics(
    monkeypatch, capsys
):
    monkeypatch.setenv("EOM_NATIVE_EXAM_TOOL_PYTHON", str(PYTHON))
    monkeypatch.setattr(
        worker, "prepare_workspace", Mock(side_effect=ValueError("private source content"))
    )
    assert worker.main([INSTANCE]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "native_exam_preparer=FAILED code=NATIVE_EXAM_PREPARER_FAILED\n"
