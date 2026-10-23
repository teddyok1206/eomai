"""Finite window is root-attested data, never a caller-provided retry grant."""

import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_benchmark_budget600_window_evidence as subject
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.embedding_device_benchmark_fixtures import owner_request


def _write(path: Path, value: object | bytes) -> None:
    raw = value if isinstance(value, bytes) else canonical_json_bytes(value)
    path.write_bytes(raw)
    path.chmod(0o400)


def _row(name: str, invocation: str, *, phase: str) -> dict[str, str]:
    active = phase == "RUNNING"
    return dict.fromkeys(subject._PROPERTIES, "") | {
        "Id": name,
        "LoadState": "loaded",
        "ActiveState": "active" if active else "inactive",
        "SubState": "running" if active else "dead",
        "Result": "success",
        "MainPID": "123" if active else "0",
        "ExecMainPID": "123" if active else "0",
        "ControlPID": "0",
        "ControlGroup": "/system.slice/" + name if active else "",
        "InvocationID": invocation,
        "FragmentPath": "/etc/systemd/system/" + name,
        "NeedDaemonReload": "no",
        "Restart": "no",
        "NRestarts": "0",
        "NFileDescriptorStore": "0",
        "User": "index" if name == subject.OWNER_UNITS[0] else "root",
        "Group": "index" if name == subject.OWNER_UNITS[0] else "root",
    }


@pytest.fixture
def window(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    root.chmod(0o755)
    retired = root / "retired-templates"
    retired.mkdir(mode=0o700)
    service, socket = b"service bytes", b"socket bytes"
    family = SimpleNamespace(
        service_template="eom-embedding-benchmark-cpu-budget600@.service",
        socket_template="eom-embedding-benchmark-cpu-budget600@.socket",
        service_sha256=sha256_bytes(service),
        socket_sha256=sha256_bytes(socket),
        timeout_seconds=600,
    )
    monkeypatch.setattr(subject, "benchmark_unit_family", lambda *_args: family)
    _write(retired / family.service_template, service)
    _write(retired / family.socket_template, socket)
    before = {name: _row(name, "a" * 32, phase="RUNNING") for name in subject.OWNER_UNITS}
    stopped = {name: _row(name, "a" * 32, phase="STOPPED") for name in subject.OWNER_UNITS}
    restored = {name: _row(name, "b" * 32, phase="RUNNING") for name in subject.OWNER_UNITS}
    _write(
        root / "window-before.json",
        {
            "schema_version": "finite-benchmark-window/1.0",
            "controller_unit": subject.CONTROLLER_UNIT,
            "invocation_id": "c" * 32,
            "before": before,
        },
    )
    _write(root / "window-stopped.json", stopped)
    _write(root / "window-restored.json", restored)
    return root, family


def _capture(window):
    root, _ = window
    return subject.capture_budget600_window(
        owner_request(), controller_invocation_id="c" * 32, root=root, owner_uid=os.getuid()
    )


def test_exact_root_window_and_retired_template_hashes_are_captured(window):
    value = _capture(window)
    assert value.before_raw_sha256 == sha256_bytes((window[0] / "window-before.json").read_bytes())
    assert value.retired_service_template_sha256 == window[1].service_sha256
    value.assert_current()


@pytest.mark.parametrize("fault", ("controller", "stopped", "restored", "template", "extra"))
def test_invalid_root_window_fails_before_attestation(window, fault):
    root, family = window
    if fault == "controller":
        path = root / "window-before.json"
        document = subject.parse_rootlocal_evidence_document(path.read_bytes(), 65536)
        document["invocation_id"] = "d" * 32
    elif fault in {"stopped", "restored"}:
        path = root / ("window-" + fault + ".json")
        document = subject.parse_rootlocal_evidence_document(path.read_bytes(), 65536)
        name = subject.OWNER_UNITS[0]
        document[name]["MainPID"] = "999"
    elif fault == "template":
        path = root / "retired-templates" / family.service_template
        document = b"different"
    else:
        path = root / "window-before.json"
        document = subject.parse_rootlocal_evidence_document(path.read_bytes(), 65536)
        document["unauthorized"] = "value"
    path.chmod(0o600)
    _write(path, document)
    with pytest.raises(ValueError):
        _capture(window)


def test_late_file_identity_change_invalidates_capture(window):
    value = _capture(window)
    path = window[0] / "window-stopped.json"
    path.chmod(0o600)
    path.write_bytes(path.read_bytes())
    path.chmod(0o400)
    with pytest.raises(ValueError):
        value.assert_current()


def test_reappearing_retired_load_path_invalidates_capture(window, tmp_path):
    value = _capture(window)
    load_path = tmp_path / "unexpected-unit.service"
    checked = replace(value, retired_load_paths=(load_path,))
    checked.assert_current()
    load_path.symlink_to(window[0] / "window-before.json")
    with pytest.raises(ValueError):
        checked.assert_current()
