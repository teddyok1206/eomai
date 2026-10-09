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


@pytest.mark.parametrize("state,pid", [("active", "1"), ("activating", "0"), ("failed", "1")])
def test_both_services_must_be_stopped_before_staging(monkeypatch, state, pid):
    monkeypatch.setattr(installation.os, "geteuid", lambda: 0)
    replies = iter([COMMIT, "", "inactive", "0", state, pid])
    monkeypatch.setattr(installation, "output", lambda *_: next(replies))
    with pytest.raises(ChatError, match="MUST_BE_STOPPED"):
        installation.require_source(COMMIT, MODEL)


def test_quiescent_failed_startup_can_be_replaced_without_erasing_failure_history(monkeypatch):
    monkeypatch.setattr(installation.os, "geteuid", lambda: 0)
    replies = iter([COMMIT, "", "inactive", "0", "failed", "0"])
    monkeypatch.setattr(installation, "output", lambda *_: next(replies))
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


def test_rag_configuration_pins_shared_protocol_and_exact_policy_without_credentials():
    from tests.unit.general_chat_rag_fixtures import scope

    values = installation.configuration_payloads(COMMIT, MODEL, rag_policy=scope().policy)
    payload = values[installation.CONFIG_ROOT / "general-chat-model.env"]
    assert payload.decode().splitlines() == [
        "EOM_GENERAL_CHAT_MODEL=synthetic-model",
        "EOM_GENERAL_CHAT_PROTOCOL_VERSION=4",
        f"EOM_GENERAL_CHAT_RAG_POLICY_REVISION_ID={scope().policy.access_policy_revision_id}",
        f"EOM_GENERAL_CHAT_RAG_POLICY_SHA256={scope().policy.sha256}",
    ]
    assert set(values) == set(installation.configuration_payloads(COMMIT, MODEL))


@pytest.mark.parametrize("kind", ["model", "unit"])
def test_prepared_configuration_update_checks_exact_predecessor_before_atomic_replace(
    monkeypatch, tmp_path, kind
):
    from eom_identifiers import sha256_bytes

    monkeypatch.setattr(installation, "CONFIG_ROOT", tmp_path)
    monkeypatch.setattr(installation, "UNIT_ROOT", tmp_path)
    target = tmp_path / ("general-chat-model.env" if kind == "model" else installation.UNITS[0])
    mode = 0o600 if kind == "model" else 0o644
    old, new = b"nonsecret-old\n", b"nonsecret-new\n"
    target.write_bytes(old)
    target.chmod(mode)
    original_read, original_install = (
        installation.read_chat_preparation_file,
        installation.install_chat_environment,
    )
    monkeypatch.setattr(
        installation,
        "read_chat_preparation_file",
        lambda path, **kw: original_read(
            path, uid=target.stat().st_uid, gid=target.stat().st_gid, mode=kw["mode"]
        ),
    )
    monkeypatch.setattr(
        installation,
        "install_chat_environment",
        lambda path, payload, **kw: original_install(
            path, payload, uid=target.stat().st_uid, gid=target.stat().st_gid
        ),
    )
    with pytest.raises(ChatError, match="TARGET_CONFLICT"):
        installation.update_prepared_configuration(
            target, new, digest="sha256:" + "b" * 64, mode=mode
        )
    assert target.read_bytes() == old and list(tmp_path.iterdir()) == [target]
    installation.update_prepared_configuration(target, new, digest=sha256_bytes(old), mode=mode)
    assert target.read_bytes() == new and stat.S_IMODE(target.stat().st_mode) == mode
    assert list(tmp_path.iterdir()) == [target]


def test_predecessor_update_cannot_replace_credentials_or_arbitrary_files(monkeypatch, tmp_path):
    monkeypatch.setattr(installation, "CONFIG_ROOT", tmp_path)
    monkeypatch.setattr(
        installation,
        "read_chat_preparation_file",
        lambda *_a, **_kw: pytest.fail("must reject target before reading"),
    )
    for name in ("secrets/general-chat.env", "other.env", "general-chat-release.env"):
        with pytest.raises(ChatError, match="TARGET_CONFLICT"):
            installation.require_configuration_predecessor(
                tmp_path / name, digest="sha256:" + "a" * 64, mode=0o600
            )


@pytest.mark.parametrize("previous", ["main", COMMIT])
def test_release_update_never_resolves_an_unpinned_or_same_predecessor(monkeypatch, previous):
    monkeypatch.setattr(installation, "require_replay", lambda *a, **k: pytest.fail("no lookup"))
    with pytest.raises(ChatError, match="SOURCE_MISMATCH"):
        installation.require_release_update(
            installation.CONFIG_ROOT / "general-chat-release.env",
            previous=previous,
            selected=COMMIT,
        )


def test_atomic_nonsecret_release_update_requires_exact_existing_predecessor(monkeypatch, tmp_path):
    target = tmp_path / "general-chat-release.env"
    previous = "b" * 40
    old = f"EOM_RUNTIME_SOURCE_COMMIT={previous}\n".encode()
    new = f"EOM_RUNTIME_SOURCE_COMMIT={COMMIT}\n".encode()
    target.write_bytes(old)
    target.chmod(0o600)
    original_read = installation.read_chat_preparation_file
    original_install = installation.install_chat_environment
    monkeypatch.setattr(
        installation,
        "read_chat_preparation_file",
        lambda path, **kw: original_read(
            path, uid=target.stat().st_uid, gid=target.stat().st_gid, mode=0o600
        ),
    )
    monkeypatch.setattr(
        installation,
        "install_chat_environment",
        lambda path, payload, **kw: original_install(
            path, payload, uid=target.stat().st_uid, gid=target.stat().st_gid
        ),
    )
    with pytest.raises(ChatError, match="TARGET_CONFLICT"):
        installation.update_release_pin(target, new, previous="c" * 40, selected=COMMIT)
    assert target.read_bytes() == old and list(tmp_path.iterdir()) == [target]
    installation.update_release_pin(target, new, previous=previous, selected=COMMIT)
    assert target.read_bytes() == new and stat.S_IMODE(target.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [target]


def test_explicit_release_update_is_not_a_missing_file_install(monkeypatch, tmp_path):
    with pytest.raises(ChatError, match="TARGET_CONFLICT"):
        installation.require_release_update(
            tmp_path / "missing.env", previous="b" * 40, selected=COMMIT
        )


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
