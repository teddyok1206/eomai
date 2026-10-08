"""Fixed chat-only rollout guards and real file replay; no live activation."""

from __future__ import annotations

import stat
from types import SimpleNamespace

import pytest
from eom_orchestrator.general_chat_state import ChatError

from scripts.chat import install_runtime as installation

COMMIT = "a" * 40
MODEL = "synthetic-model"


def test_nonroot_cannot_inspect_source_or_protected_state(monkeypatch):
    monkeypatch.setattr(installation.os, "geteuid", lambda: 123)
    monkeypatch.setattr(installation, "output", lambda *_: pytest.fail("no protected work"))
    with pytest.raises(ChatError, match="REQUIRES_ROOT"):
        installation.require_source(COMMIT, MODEL)


@pytest.mark.parametrize("commit,model", [("main", MODEL), (COMMIT, "model; command")])
def test_invalid_source_and_model_precede_system_operations(monkeypatch, commit, model):
    monkeypatch.setattr(installation.os, "geteuid", lambda: 0)
    monkeypatch.setattr(installation, "output", lambda *_: pytest.fail("no protected work"))
    with pytest.raises(ChatError, match="SOURCE_MISMATCH"):
        installation.require_source(commit, model)


@pytest.mark.parametrize("head,dirty", [("b" * 40, ""), (COMMIT, "M file")])
def test_changed_checkout_is_rejected(monkeypatch, head, dirty):
    monkeypatch.setattr(installation.os, "geteuid", lambda: 0)
    replies = iter([head, dirty])
    monkeypatch.setattr(installation, "output", lambda *_: next(replies))
    with pytest.raises(ChatError, match="SOURCE_MISMATCH"):
        installation.require_source(COMMIT, MODEL)


@pytest.mark.parametrize("state", ["active", "activating", "failed"])
def test_both_services_must_be_stopped_before_staging(monkeypatch, state):
    monkeypatch.setattr(installation.os, "geteuid", lambda: 0)
    replies = iter([COMMIT, "", "inactive", state])
    monkeypatch.setattr(installation, "output", lambda *_: next(replies))
    with pytest.raises(ChatError, match="MUST_BE_STOPPED"):
        installation.require_source(COMMIT, MODEL)


@pytest.mark.parametrize(
    "kind,uid,mode", [(stat.S_IFLNK, 0, 0o755), (stat.S_IFDIR, 1, 0o755), (stat.S_IFDIR, 0, 0o775)]
)
def test_protected_parent_does_not_accept_symlinks_or_writers(kind, uid, mode):
    path = SimpleNamespace(lstat=lambda: SimpleNamespace(st_mode=kind | mode, st_uid=uid))
    with pytest.raises(ChatError, match="TARGET_INVALID"):
        installation.require_root_directory(path)


def test_replay_retains_exact_bytes_and_rejects_changed_configuration(monkeypatch, tmp_path):
    target = tmp_path / "config.env"
    assert installation.require_replay(target, b"MODEL=same\n", mode=0o600) is False
    target.write_bytes(b"MODEL=same\n")
    # File parser has separate real metadata coverage; retain this test's own UID.
    original = installation.read_chat_preparation_file
    monkeypatch.setattr(
        installation,
        "read_chat_preparation_file",
        lambda path, **kw: original(
            path, uid=target.stat().st_uid, gid=target.stat().st_gid, mode=0o600
        ),
    )
    target.chmod(0o600)
    assert installation.require_replay(target, b"MODEL=same\n", mode=0o600) is True
    with pytest.raises(ChatError, match="TARGET_CONFLICT"):
        installation.require_replay(target, b"MODEL=other\n", mode=0o600)
    assert target.read_bytes() == b"MODEL=same\n"


def test_configuration_is_fixed_small_nonsecret_values():
    values = installation.configuration_payloads(COMMIT, MODEL)
    assert {path.name for path in values} == {"general-chat-model.env", "general-chat-release.env"}
    assert all(path.parent == installation.CONFIG_ROOT for path in values)
    assert b"EOM_GENERAL_CHAT_MODEL=synthetic-model\n" in values.values()
    assert all(b"API_KEY" not in value and b"TOKEN" not in value for value in values.values())


def test_activation_reads_admission_then_enables_only_the_two_chat_services(monkeypatch):
    calls = []
    monkeypatch.setattr(
        installation.subprocess, "run", lambda command, **kw: calls.append((command, kw))
    )
    installation.activate()
    assert calls[0][0] == ["systemctl", "start", *installation.UNITS]
    assert calls[1][0][:6] == ["runuser", "-u", "eom-api", "--", installation.PYTHON, "-I"]
    assert ".slot().state == 'READY'" in calls[1][0][-1]
    assert calls[2][0] == ["systemctl", "enable", *installation.UNITS]
    assert not any("eom-workflow-runner.service" in command for command, _ in calls)


def test_failed_admission_stops_only_new_services_without_enabling_or_mutating_history(monkeypatch):
    calls = []

    def run(command, **kw):
        calls.append(command)
        if command[0] == "runuser":
            raise OSError("private diagnostic must not escape")

    monkeypatch.setattr(installation.subprocess, "run", run)
    with pytest.raises(ChatError, match="ACTIVATION_FAILED"):
        installation.activate()
    assert calls[-1] == ["systemctl", "stop", *installation.UNITS]
    assert not any("enable" in command or "reset-failed" in command for command in calls)


def test_installed_verification_uses_isolated_interpreter_without_user_environment(monkeypatch):
    calls = []
    monkeypatch.setattr(
        installation.subprocess, "run", lambda command, **kw: calls.append((command, kw))
    )
    installation.require_installed_release(COMMIT)
    command, options = calls[0]
    assert command[:3] == [installation.PYTHON, "-I", "-c"] and command[-1] == COMMIT
    assert options["env"] == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    assert "get_build_info().source_commit" in command[3]
    assert "installer = pwd.getpwnam('eom')" in command[3]
    assert "(installer.pw_uid, installer.pw_gid)" in command[3]


def test_helper_only_revision_retains_explicit_runtime_pin_after_full_boundary_diff(monkeypatch):
    calls = []
    deployed = "b" * 40
    monkeypatch.setattr(
        installation.subprocess, "run", lambda command, **kw: calls.append((command, kw))
    )
    monkeypatch.setattr(installation, "require_installed_release", lambda pin: calls.append(pin))
    installation.require_compatible_runtime(COMMIT, deployed)
    command, options = calls[0]
    assert command[3:7] == ["diff", "--quiet", deployed, COMMIT]
    assert {
        "apps/application_api",
        "packages/protocol",
        "services/orchestrator",
        "infra/systemd",
    } <= set(command)
    assert options["check"] is True and calls[-1] == deployed


def test_runtime_boundary_change_rejects_release_without_certifying_installed_bytes(monkeypatch):
    def changed(*args, **kwargs):
        raise installation.subprocess.CalledProcessError(1, "git diff")

    monkeypatch.setattr(installation.subprocess, "run", changed)
    monkeypatch.setattr(
        installation, "require_installed_release", lambda pin: pytest.fail("not compatible")
    )
    with pytest.raises(installation.subprocess.CalledProcessError):
        installation.require_compatible_runtime(COMMIT, "b" * 40)


def test_unpinned_runtime_is_not_resolved_to_latest(monkeypatch):
    monkeypatch.setattr(
        installation.subprocess, "run", lambda *args, **kw: pytest.fail("no unpinned lookup")
    )
    with pytest.raises(ChatError, match="SOURCE_MISMATCH"):
        installation.require_compatible_runtime(COMMIT, "main")
