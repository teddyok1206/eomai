"""No live privileges: exact chat-layout ownership transition and bytes preservation."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_orchestrator.general_chat_state import ChatError

from scripts.chat import install_runtime as installation


@pytest.fixture
def layout(monkeypatch, tmp_path):
    worker_uid, worker_gid = os.getuid(), os.getgid()
    previous_uid, previous_gid = worker_uid + 100, worker_gid + 100
    workspace = tmp_path / "workspace"
    state = tmp_path / "state"
    native_config = tmp_path / "native.toml"
    slot_config = tmp_path / "slot.toml"
    for path, mode in (
        (workspace, 0o750),
        (workspace / "native", 0o750),
        (state, 0o700),
        (state / "handoff", 0o700),
    ):
        path.mkdir(mode=mode)
        path.chmod(mode)
    pending = state / "handoff" / ("chatclaim_" + "a" * 32 + ".pending.json")
    result = state / "handoff" / ("chatclaim_" + "a" * 32 + ".result.json")
    for path in (pending, result):
        path.write_bytes(b"synthetic immutable receipt")
        path.chmod(0o400)
    owners = {
        workspace: (0, previous_gid),
        workspace / "native": (0, previous_gid),
        state: (previous_uid, previous_gid),
        state / "handoff": (previous_uid, previous_gid),
        pending: (previous_uid, previous_gid),
        result: (previous_uid, previous_gid),
    }
    monkeypatch.setattr(installation, "WORKSPACE", workspace)
    monkeypatch.setattr(installation, "WORKER_STATE", state)
    monkeypatch.setattr(installation, "CHAT_CONFIG_SOURCE", native_config)
    monkeypatch.setattr(installation, "CHAT_CONFIG", slot_config)
    monkeypatch.setattr(installation, "require_chat_services_stopped", lambda: None)
    monkeypatch.setattr(installation, "require_root_directory", lambda _: None)
    monkeypatch.setattr(
        installation.pwd,
        "getpwnam",
        lambda name: SimpleNamespace(
            pw_uid=previous_uid if name == "eom-cdx-chat" else worker_uid,
            pw_gid=previous_gid if name == "eom-cdx-chat" else worker_gid,
        ),
    )
    real_lstat, real_fstat = Path.lstat, os.fstat

    def metadata(path, node):
        if path not in owners:
            return node
        values = {key: getattr(node, key) for key in dir(node) if key.startswith("st_")}
        values["st_uid"], values["st_gid"] = owners[path]
        return SimpleNamespace(**values)

    monkeypatch.setattr(Path, "lstat", lambda path: metadata(path, real_lstat(path)))
    monkeypatch.setattr(
        os, "fstat", lambda fd: metadata(Path(os.readlink(f"/proc/self/fd/{fd}")), real_fstat(fd))
    )
    mutations = []

    def chown(fd, uid, gid):
        path = Path(os.readlink(f"/proc/self/fd/{fd}"))
        mutations.append(path)
        owners[path] = (uid, gid)

    monkeypatch.setattr(os, "fchown", chown)
    real_link = os.link

    def link(source, destination, **kwargs):
        real_link(source, destination, **kwargs)
        if Path(source) in owners:
            owners[Path(destination)] = owners[Path(source)]

    monkeypatch.setattr(os, "link", link)
    return SimpleNamespace(
        workspace=workspace,
        state=state,
        pending=pending,
        result=result,
        config=slot_config,
        native_config=native_config,
        owners=owners,
        mutations=mutations,
        uid=worker_uid,
        gid=worker_gid,
    )


def test_layout_transition_preserves_handoff_and_existing_slot_configuration(layout, capsys):
    layout.config.write_bytes(b"# existing operator configuration\n")
    layout.config.chmod(0o600)
    before = {path: path.read_bytes() for path in (layout.config, layout.pending, layout.result)}
    targets = installation.worker_layout_preflight()
    assert not layout.mutations
    installation.stage_worker_layout(targets)
    assert {path: path.read_bytes() for path in before} == before
    assert layout.owners[layout.pending] == (layout.uid, layout.gid)
    assert layout.owners[layout.result] == (layout.uid, layout.gid)
    assert layout.owners[layout.workspace] == (0, layout.gid)
    assert layout.native_config.read_bytes() == installation.CHAT_CONFIG_BYTES
    assert layout.config not in layout.mutations
    receipt = capsys.readouterr().out
    assert '"chat_slot06_ownership_preflight"' in receipt
    assert '"previous_uid"' in receipt and '"selected_uid"' in receipt
    assert '"inode"' in receipt and "synthetic immutable receipt" not in receipt
    # Completed transition is replayable, with no deletion or re-generation.
    installation.stage_worker_layout(installation.worker_layout_preflight())
    assert capsys.readouterr().out == ""


def test_absent_slot_config_gets_only_comment_mountpoint_with_exact_receipt(layout, capsys):
    installation.stage_worker_layout(installation.worker_layout_preflight())
    assert layout.config.read_bytes() == installation.MOUNTPOINT_BYTES
    assert all(line.startswith(b"#") for line in layout.config.read_bytes().splitlines())
    output = capsys.readouterr().out
    assert '"chat_slot06_mountpoint_created"' in output and '"inode"' in output
    installation.stage_worker_layout(installation.worker_layout_preflight())
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("problem", ["symlink", "hardlink", "foreign", "wrong_owner", "workspace"])
def test_untrusted_or_unrelated_state_fails_before_any_ownership_change(layout, problem):
    if problem == "symlink":
        layout.result.unlink()
        layout.result.symlink_to(layout.pending)
    elif problem == "hardlink":
        os.link(layout.pending, layout.state / "outside")
    elif problem == "foreign":
        (layout.state / "handoff" / "auth.json").write_bytes(b"not a handoff")
    elif problem == "wrong_owner":
        layout.owners[layout.pending] = (77777, 77777)
    else:
        (layout.workspace / "native" / "unrelated.txt").write_text("unrelated")
    with pytest.raises(ChatError, match="TARGET_CONFLICT"):
        installation.worker_layout_preflight()
    assert not layout.mutations


def test_layout_race_between_preflight_and_install_prevents_mutation(layout):
    targets = installation.worker_layout_preflight()
    layout.pending.chmod(0o600)
    with pytest.raises(ChatError, match="TARGET_CONFLICT"):
        installation.stage_worker_layout(targets)
    assert not layout.mutations


def test_active_chat_service_prevents_layout_transition(layout, monkeypatch):
    targets = installation.worker_layout_preflight()

    def active():
        raise ChatError("GENERAL_CHAT_INSTALL_MUST_BE_STOPPED")

    monkeypatch.setattr(installation, "require_chat_services_stopped", active)
    with pytest.raises(ChatError, match="MUST_BE_STOPPED"):
        installation.stage_worker_layout(targets)
    assert not layout.mutations
