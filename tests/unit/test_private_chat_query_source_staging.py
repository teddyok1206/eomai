"""Real local metadata/no-replace files; root/tmpfiles effects are explicit fakes."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_orchestrator.general_chat_protected_environment import (
    install_chat_environment,
    read_chat_preparation_file,
)
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint, ChatTransportError
from eom_orchestrator.general_chat_state import ChatError

from scripts.chat import install_runtime as installation

COMMIT = "a" * 40
PAYLOAD = (
    Path(__file__).resolve().parents[2] / "infra/tmpfiles/eom-general-chat-query-read.conf"
).read_bytes()


@pytest.fixture
def source_stage(monkeypatch, tmp_path):
    configuration = tmp_path / "tmpfiles.d"
    configuration.mkdir()
    target = configuration / "eom-general-chat-query-read.conf"
    endpoint = ChatSocketEndpoint(tmp_path / "runtime" / "source.sock", os.getuid(), os.getgid())
    actions = []
    monkeypatch.setattr(installation, "SOURCE_TMPFILE", target)
    monkeypatch.setattr(installation, "source_endpoint", lambda: endpoint)
    monkeypatch.setattr(installation, "require_root_directory", lambda _: None)

    def source(command, **kwargs):
        assert command == [
            "git",
            "-C",
            str(installation.REPOSITORY),
            "show",
            f"{COMMIT}:infra/tmpfiles/eom-general-chat-query-read.conf",
        ]
        return PAYLOAD

    monkeypatch.setattr(installation.subprocess, "check_output", source)

    def read(path, **kwargs):
        assert kwargs["uid"] == kwargs["gid"] == 0
        return read_chat_preparation_file(
            path, uid=os.getuid(), gid=os.getgid(), mode=kwargs["mode"]
        )

    monkeypatch.setattr(installation, "read_chat_preparation_file", read)

    def install(path, payload, **kwargs):
        assert path == target and kwargs == {"uid": 0, "gid": 0, "mode": 0o644}
        actions.append("install-policy")
        install_chat_environment(path, payload, uid=os.getuid(), gid=os.getgid(), mode=0o644)

    monkeypatch.setattr(installation, "install_chat_environment", install)

    def run(command, **kwargs):
        assert command == ["systemd-tmpfiles", "--create", str(target)]
        assert target.read_bytes() == PAYLOAD and target.stat().st_mode & 0o777 == 0o644
        actions.append("tmpfiles")
        endpoint.path.parent.mkdir(mode=0o750)

    monkeypatch.setattr(installation.subprocess, "run", run)
    return SimpleNamespace(target=target, endpoint=endpoint, actions=actions)


def test_preflight_is_read_only_then_fixed_policy_provisions_only_one_parent(source_stage):
    value = source_stage
    payload, present = installation.source_endpoint_preflight(COMMIT)
    assert payload == PAYLOAD and present is False and value.actions == []
    assert not value.target.exists() and not value.endpoint.path.parent.exists()
    installation.stage_source_endpoint(payload, present=present)
    assert value.actions == ["install-policy", "tmpfiles"]
    value.endpoint.require_parent()
    assert not value.endpoint.path.exists()


@pytest.mark.parametrize("kind", ["wrong-mode", "symlink", "endpoint-file", "endpoint-link"])
def test_source_parent_or_endpoint_conflict_never_repairs_or_reclaims(source_stage, kind):
    value = source_stage
    parent = value.endpoint.path.parent
    if kind == "symlink":
        parent.symlink_to(value.target.parent, target_is_directory=True)
    else:
        parent.mkdir(mode=0o700 if kind == "wrong-mode" else 0o750)
        if kind == "endpoint-file":
            value.endpoint.path.write_bytes(b"not a socket")
        elif kind == "endpoint-link":
            value.endpoint.path.symlink_to(value.target)
    with pytest.raises((ChatError, ChatTransportError)):
        installation.source_endpoint_preflight(COMMIT)
    assert value.actions == [] and not value.target.exists()
    if kind == "endpoint-file":
        assert value.endpoint.path.read_bytes() == b"not a socket"
    elif kind == "endpoint-link":
        assert value.endpoint.path.is_symlink()


def test_foreign_tmpfiles_bytes_are_rejected_without_overwrite(source_stage):
    value = source_stage
    value.target.write_bytes(b"d /unrelated 0777 root root - -\n")
    value.target.chmod(0o644)
    with pytest.raises(ChatError, match="TARGET_CONFLICT"):
        installation.source_endpoint_preflight(COMMIT)
    assert value.actions == [] and b"/unrelated" in value.target.read_bytes()


def test_fixed_template_and_owner_sandbox_do_not_expand_worker_authority():
    root = Path(__file__).resolve().parents[2]
    assert [line for line in PAYLOAD.decode().splitlines() if not line.startswith("#")] == [
        "d /run/eom-general-chat-query-read 0750 eom-general-chat eom - -"
    ]
    owner = (root / "infra/systemd/eom-general-chat.service").read_text()
    worker = (root / "infra/systemd/eom-general-chat-worker.service").read_text()
    assert "ReadWritePaths=-/run/eom-general-chat-query-read\n" in owner
    assert "query-read" not in worker and "SupplementaryGroups=" not in worker
