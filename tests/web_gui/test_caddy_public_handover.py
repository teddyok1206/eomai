from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CADDYFILE = ROOT / "config" / "caddy" / "Caddyfile"
DROP_IN = ROOT / "config" / "systemd" / "caddy.service.d" / "eom-security.conf"
INSTALLER = ROOT / "scripts" / "web_gui" / "install_public_handover.sh"


def test_caddy_admin_is_bound_to_a_protected_unix_socket() -> None:
    config = CADDYFILE.read_text(encoding="utf-8")
    drop_in = DROP_IN.read_text(encoding="utf-8")

    assert "admin unix//run/caddy-admin/admin.sock" in config
    assert "localhost:2019" not in config
    assert "127.0.0.1:2019" not in config
    assert "RuntimeDirectory=caddy-admin" in drop_in
    assert "RuntimeDirectoryMode=0700" in drop_in
    assert "UMask=0077" in drop_in
    assert "--address unix//run/caddy-admin/admin.sock" in drop_in


def test_public_handover_keeps_only_the_studio_proxy() -> None:
    config = CADDYFILE.read_text(encoding="utf-8")

    assert "eomai.duckdns.org" in config
    assert "redir @root /studio/ 308" in config
    assert "reverse_proxy @studio 127.0.0.1:8790" in config
    assert 'Strict-Transport-Security "max-age=31536000"' in config
    for internal_port in ("8000", "8765", "8780"):
        assert internal_port not in config


def test_installer_verifies_both_admin_access_boundaries() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    assert "http://127.0.0.1:2019/config/" in script
    assert "--unix-socket /run/caddy-admin/admin.sock" in script
    assert "runuser -u eom-cdx-01 -g eom-cdx-01" in script
    assert "systemctl reload caddy.service" in script
    assert "caddy:caddy:200" in script
    assert "unlink /run/caddy-admin/admin.sock" in script
