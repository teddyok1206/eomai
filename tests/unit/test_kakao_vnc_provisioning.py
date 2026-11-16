"""Synthetic stdin tool seam only; no host identities or actual credentials."""

from unittest.mock import Mock

import pytest

from scripts.kakao import provision_vnc_password as provision


def test_vnc_secret_is_only_stdin_not_argv_or_output(monkeypatch, capsys):
    child = Mock(return_value=Mock(returncode=0, stdout=b"synthetic"[:8]))
    monkeypatch.setattr(provision.subprocess, "run", child)
    assert len(provision.encode_password("testVNC8")) == 8
    assert child.call_args.args == ((provision.TOOL, "-f"),)
    assert child.call_args.kwargs["input"] == b"testVNC8\n"
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "value", ["", "short", "longerthan8", "테스트12345", "1234567\n", "1234567 "]
)
def test_vnc_password_format_never_reaches_tool(monkeypatch, value):
    child = Mock()
    monkeypatch.setattr(provision.subprocess, "run", child)
    with pytest.raises(ValueError, match="8_ASCII"):
        provision.encode_password(value)
    child.assert_not_called()


def test_vnc_native_error_is_redacted(monkeypatch):
    monkeypatch.setattr(
        provision.subprocess, "run", Mock(return_value=Mock(returncode=1, stdout=b"private"))
    )
    with pytest.raises(ValueError, match=r"^VNC_PASSWORD_TOOL_FAILED$"):
        provision.encode_password("testVNC8")
