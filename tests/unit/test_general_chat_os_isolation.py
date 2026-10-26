"""Source-derived diagnostic sandbox; real systemd namespace is a separate gate."""

from __future__ import annotations

import ast
import inspect
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.chat import verify_runtime_isolation as isolation

ROOT = Path(__file__).resolve().parents[2]
COMMIT = "a" * 40


def source(component):
    return (ROOT / "infra/systemd" / isolation.UNITS[component]).read_text()


@pytest.mark.parametrize("component", ["owner", "worker"])
def test_security_properties_come_from_source_including_repeated_path_directives(component):
    body = source(component)
    values = isolation.sandbox_properties(body, component)
    assert values["User"] == isolation.USERS[component]
    assert values["NoNewPrivileges"] == "true"
    assert values["ProtectSystem"] == "strict" and values["ProtectHome"] == "true"
    assert values["CapabilityBoundingSet"] == values["AmbientCapabilities"] == ""
    for key in ("InaccessiblePaths", "ReadOnlyPaths", "ReadWritePaths", "Environment"):
        original = [
            line.split("=", 1)[1] for line in body.splitlines() if line.startswith(key + "=")
        ]
        if original:
            assert values[key] == " ".join(original)
    assert not isolation.OMITTED.intersection(values.keys()) - {"Restart", "TimeoutStopSec"}
    assert values["Restart"] == "no" and values["RuntimeMaxSec"] == "30"
    assert "ExecStartPre" not in values and "EnvironmentFile" not in values
    if component == "owner":
        assert values["SupplementaryGroups"] == "eom eom-cdx-chat eom-general-chat"
        assert values["IPAddressDeny"] == "any" and values["IPAddressAllow"] == "localhost"
    else:
        assert "SupplementaryGroups" not in values


@pytest.mark.parametrize(
    ("old", "new", "code"),
    [
        ("User=eom-cdx-chat", "User=root", "SOURCE_IDENTITY_INVALID"),
        ("StateDirectoryMode=0700", "StateDirectoryMode=0755", "SOURCE_IDENTITY_INVALID"),
        ("Environment=LANG=C.UTF-8", "Environment=TOKEN=synthetic", "ENVIRONMENT_UNREVIEWED"),
        ("PrivateTmp=true", "PrivateTmp=true\nRootDirectory=/unreviewed", "DIRECTIVE_UNREVIEWED"),
        ("PrivateTmp=true", "PrivateTmp=true\nPrivateTmp=false", "SOURCE_INVALID"),
        ("PrivateTmp=true", "PrivateTmp=true\\", "SOURCE_INVALID"),
    ],
)
def test_unreviewed_or_unsafe_source_is_not_silently_degraded(old, new, code):
    with pytest.raises(isolation.IsolationProbeError, match=code):
        isolation.sandbox_properties(source("worker").replace(old, new), "worker")


def test_unknown_component_is_rejected():
    with pytest.raises(isolation.IsolationProbeError, match="COMPONENT_INVALID"):
        isolation.sandbox_properties(source("worker"), "unknown")


@pytest.mark.parametrize("conflict", ["uid", "group", "mode", "symlink", "runtime_busy"])
def test_existing_private_state_is_never_reowned_or_cleared(monkeypatch, conflict):
    properties = isolation.sandbox_properties(source("worker"), "worker")
    monkeypatch.setattr(
        isolation.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=900, pw_gid=901)
    )
    monkeypatch.setattr(isolation.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=901))
    selected = "/run/" if conflict == "runtime_busy" else "/var/lib/"
    monkeypatch.setattr(isolation.Path, "exists", lambda path: str(path).startswith(selected))
    monkeypatch.setattr(isolation.Path, "is_symlink", lambda path: False)
    mode = 0o750 if selected == "/run/" else 0o700
    node = SimpleNamespace(st_uid=900, st_gid=901, st_mode=stat.S_IFDIR | mode)
    if conflict == "uid":
        node.st_uid = 0
    elif conflict == "group":
        node.st_gid = 0
    elif conflict == "mode":
        node.st_mode = stat.S_IFDIR | 0o777
    elif conflict == "symlink":
        node.st_mode = stat.S_IFLNK | 0o700
    monkeypatch.setattr(isolation.Path, "lstat", lambda path: node)
    monkeypatch.setattr(isolation.Path, "iterdir", lambda path: iter([Path("existing.sock")]))
    with pytest.raises(isolation.IsolationProbeError, match="EXISTING_STATE_CONFLICT"):
        isolation.probe_data(properties, "worker")


def test_namespace_body_has_no_native_or_repository_dependency_or_secret_byte_read():
    body = inspect.getsource(isolation.probe)
    tree = ast.parse(body)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imports == {"errno", "os", "stat", "socket", "tempfile"}
    assert "os.read(" not in body and ".read(" not in body and ".read_bytes(" not in body
    assert "os.O_TRUNC" not in body and "os.replace" not in body
    assert "connection.connect(docker_path)" in body  # Connect only; no Docker API request.
    assert "effective_ids=True" in body  # NAS permissions only; no NAS file creation.
    compile("from __future__ import annotations\nimport json\n" + body, "inline-probe", "exec")


@pytest.fixture
def invocation(monkeypatch):
    calls = []
    replies = iter([COMMIT, "", "inactive", "inactive", source("owner"), source("worker")])
    monkeypatch.setattr(isolation.sys, "argv", ["verify", COMMIT])
    monkeypatch.setattr(isolation.os, "geteuid", lambda: 0)
    monkeypatch.setattr(isolation.subprocess, "check_output", lambda *_a, **_k: next(replies))
    monkeypatch.setattr(isolation, "probe_data", lambda *_a: {})

    def execute(command, **kwargs):
        calls.append((command, kwargs))
        component = "owner" if "owner" in command[5] else "worker"
        return SimpleNamespace(
            returncode=0,
            stdout="CHAT_ISOLATION_NAMESPACE_PASS " + component + "\n",
            stderr="discarded-private-error-body",
        )

    monkeypatch.setattr(isolation.subprocess, "run", execute)
    return calls


def test_root_driver_uses_only_inline_conda_program_and_bounded_source_property_args(
    invocation, capsys
):
    assert isolation.main() == 0
    assert len(invocation) == 2
    for command, options in invocation:
        assert command[0] == "systemd-run" and "--wait" in command and "--collect" in command
        assert command[-4:-1] == [isolation.PYTHON, "-I", "-c"]
        assert "def probe(" in command[-1] and "from __future__ import annotations" in command[-1]
        assert not any(value.startswith("--property=EnvironmentFile") for value in command)
        assert not any(value.startswith("--property=ExecStart") for value in command)
        assert options["timeout"] == 50 and options["stdin"] == isolation.subprocess.DEVNULL
    output = capsys.readouterr()
    assert "CHAT_OS_ISOLATION=PASS" in output.out
    assert "private-error" not in output.out + output.err


def test_nonroot_rejection_precedes_source_or_service_inspection(monkeypatch, capsys):
    monkeypatch.setattr(isolation.sys, "argv", ["verify", COMMIT])
    monkeypatch.setattr(isolation.os, "geteuid", lambda: 1000)

    def forbidden(*args, **kwargs):
        raise AssertionError("not admitted")

    monkeypatch.setattr(isolation.subprocess, "check_output", forbidden)
    assert isolation.main() == 1
    assert capsys.readouterr().err == "CHAT_ISOLATION_REQUIRES_ROOT\n"


@pytest.mark.parametrize("values", [["b" * 40], [COMMIT, " M changes"], [COMMIT, "", "active"]])
def test_wrong_source_or_active_host_prevents_transient_execution(monkeypatch, capsys, values):
    monkeypatch.setattr(isolation.sys, "argv", ["verify", COMMIT])
    monkeypatch.setattr(isolation.os, "geteuid", lambda: 0)
    replies = iter(values)
    monkeypatch.setattr(isolation.subprocess, "check_output", lambda *_a, **_k: next(replies))
    monkeypatch.setattr(isolation.subprocess, "run", lambda *_a, **_k: pytest.fail("must not run"))
    assert isolation.main() == 1
    assert "CHAT_ISOLATION_" in capsys.readouterr().err


def test_success_exit_without_namespace_attestation_is_not_pass(invocation, monkeypatch, capsys):
    monkeypatch.setattr(
        isolation.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="unrelated", stderr="private"),
    )
    assert isolation.main() == 1
    output = capsys.readouterr()
    assert output.err == "CHAT_ISOLATION_NAMESPACE_FAILED\n" and output.out == ""
