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
