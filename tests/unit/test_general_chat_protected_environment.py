from __future__ import annotations

import os

import pytest
from eom_orchestrator.general_chat_protected_environment import (
    install_chat_environment,
    read_chat_environment,
)
from eom_orchestrator.general_chat_state import ChatError


def test_secret_first_install_is_durable_private_and_never_replaces_existing(tmp_path):
    target = tmp_path / "chat.env"
    payload = b"SYNTHETIC=private\n"
    install_chat_environment(target, payload, uid=os.getuid(), gid=os.getgid())
    assert read_chat_environment(target, uid=os.getuid(), gid=os.getgid(), mode=0o600) == {
        "SYNTHETIC": "private"
    }
    with pytest.raises(ChatError, match="INSTALL_FAILED"):
        install_chat_environment(target, b"SYNTHETIC=different\n", uid=os.getuid(), gid=os.getgid())
    assert target.read_bytes() == payload and list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("mode", [0o600, 0o644])
def test_intended_mode_is_complete_before_no_replace_publication(tmp_path, monkeypatch, mode):
    target = tmp_path / "prepared.conf"
    original_link = os.link
    seen = []

    def link(source, destination, **kwargs):
        assert source.stat().st_mode & 0o777 == mode
        assert source.stat().st_nlink == 1
        seen.append(mode)
        original_link(source, destination, **kwargs)

    monkeypatch.setattr(os, "link", link)
    previous = os.umask(0o077)
    try:
        install_chat_environment(
            target, b"SYNTHETIC=nonsecret\n", uid=os.getuid(), gid=os.getgid(), mode=mode
        )
    finally:
        os.umask(previous)
    assert seen == [mode] and target.stat().st_mode & 0o777 == mode


@pytest.mark.parametrize("mode", [True, 0o666, 0o777, "0644"])
def test_arbitrary_permission_modes_never_create_a_file(tmp_path, mode):
    with pytest.raises(ChatError, match="ENVIRONMENT_INVALID"):
        install_chat_environment(
            tmp_path / "no-file", b"X=y\n", uid=os.getuid(), gid=os.getgid(), mode=mode
        )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "change", ["mode", "symlink", "fifo", "oversize", "duplicate", "syntax", "encoding", "hardlink"]
)
def test_untrusted_environment_metadata_or_contents_fail_without_secret_leak(tmp_path, change):
    target = tmp_path / "chat.env"
    if change == "fifo":
        os.mkfifo(target, 0o600)
    else:
        target.write_bytes(b"PRIVATE=do-not-export\n")
        target.chmod(0o600)
    if change == "mode":
        target.chmod(0o644)
    elif change == "symlink":
        link = tmp_path / "link.env"
        link.symlink_to(target)
        target = link
    elif change == "oversize":
        target.write_bytes(b"X" * 16385)
    elif change == "duplicate":
        target.write_bytes(b"PRIVATE=a\nPRIVATE=b\n")
    elif change == "syntax":
        target.write_bytes(b"not-an-entry\n")
    elif change == "encoding":
        target.write_bytes(b"PRIVATE=\xff\n")
    elif change == "hardlink":
        os.link(target, tmp_path / "second.env")
    with pytest.raises(ChatError) as error:
        read_chat_environment(target, uid=os.getuid(), gid=os.getgid(), mode=0o600)
    assert str(error.value) == "GENERAL_CHAT_PROTECTED_ENVIRONMENT_INVALID"
