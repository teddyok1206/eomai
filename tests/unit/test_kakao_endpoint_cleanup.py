"""Real local sockets/locks; synthetic unit identity and no host-resource mutation."""

import fcntl
import os
import socket
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_kakao_archive_collector import endpoint_cleanup as browser
from eom_kakao_archive_gateway import endpoint_cleanup as gateway

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(params=["browser", "gateway"])
def endpoint(request, monkeypatch):
    uid, gid = os.getuid(), os.getgid()
    with tempfile.TemporaryDirectory(prefix="endpoint-cleanup-", dir=ROOT / "staging") as name:
        directory = Path(name)
        directory.chmod(0o2750)
        path = directory / "endpoint.sock"
        module = browser if request.param == "browser" else gateway
        monkeypatch.setattr(
            module.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=uid, pw_gid=gid)
        )
        monkeypatch.setattr(module.grp, "getgrnam", lambda _: SimpleNamespace(gr_gid=gid))
        lock = directory / "profile.lock"
        lock.write_bytes(b"")
        lock.chmod(0o640)
        if module is browser:
            monkeypatch.setattr(browser.setup, "VNC_SOCKET", path)
            monkeypatch.setattr(browser, "LOCK", lock)
            monkeypatch.setattr(
                browser.setup, "_kernel_read", lambda _: browser.setup.CGROUP.encode()
            )
            original = browser.profile_lock

            def local_lock(path, **kwargs):
                return original(path, **{**kwargs, "parent_uids": frozenset({0, uid})})

            monkeypatch.setattr(browser, "profile_lock", local_lock)
        else:
            monkeypatch.setattr(gateway, "LISTENER", path)
            monkeypatch.setattr(gateway, "_cgroup", lambda: gateway.CGROUP)
        yield SimpleNamespace(module=module, path=path, lock=lock)


def test_two_real_start_close_cleanup_cycles_and_missing_noop(endpoint):
    for _ in range(2):
        child = socket.socket(socket.AF_UNIX)
        child.bind(str(endpoint.path))
        child.listen(1)
        endpoint.path.chmod(0o660)
        try:
            with pytest.raises(ValueError, match="ENDPOINT_LIVE"):
                endpoint.module.cleanup_stopped_endpoint()
            assert endpoint.path.exists()
        finally:
            child.close()
        endpoint.module.cleanup_stopped_endpoint()
        assert not endpoint.path.exists()
        endpoint.module.cleanup_stopped_endpoint()


def test_cleanup_never_unlinks_symlink_or_target(endpoint):
    target = endpoint.path.with_name("unrelated.txt")
    target.write_text("preserve")
    endpoint.path.symlink_to(target)
    with pytest.raises(ValueError, match="ENDPOINT_UNSAFE"):
        endpoint.module.cleanup_stopped_endpoint()
    assert endpoint.path.is_symlink() and target.read_text() == "preserve"


def test_cleanup_never_unlinks_wrong_mode_socket(endpoint):
    child = socket.socket(socket.AF_UNIX)
    child.bind(str(endpoint.path))
    child.close()
    endpoint.path.chmod(0o600)
    with pytest.raises(ValueError, match="ENDPOINT_UNSAFE"):
        endpoint.module.cleanup_stopped_endpoint()
    assert endpoint.path.exists()


def test_cleanup_never_unlinks_hardlinked_socket(endpoint):
    child = socket.socket(socket.AF_UNIX)
    child.bind(str(endpoint.path))
    child.close()
    endpoint.path.chmod(0o660)
    alias = endpoint.path.with_name("alias.sock")
    os.link(endpoint.path, alias)
    with pytest.raises(ValueError, match="ENDPOINT_UNSAFE"):
        endpoint.module.cleanup_stopped_endpoint()
    assert endpoint.path.exists() and alias.exists()


def test_cleanup_allows_only_exact_stop_control_subgroup(endpoint, monkeypatch):
    if endpoint.module is browser:
        monkeypatch.setattr(
            browser.setup, "_kernel_read", lambda _: (browser.setup.CGROUP + "/.control").encode()
        )
    else:
        monkeypatch.setattr(gateway, "_cgroup", lambda: gateway.CGROUP + "/.control")
    endpoint.module.cleanup_stopped_endpoint()


def test_cleanup_never_unlinks_regular_file(endpoint):
    endpoint.path.write_text("preserve")
    endpoint.path.chmod(0o660)
    with pytest.raises(ValueError, match="ENDPOINT_UNSAFE"):
        endpoint.module.cleanup_stopped_endpoint()
    assert endpoint.path.read_text() == "preserve"


def test_cleanup_requires_its_fixed_unit_scope(endpoint, monkeypatch):
    if endpoint.module is browser:
        monkeypatch.setattr(browser.setup, "_kernel_read", lambda _: b"0::/wrong-unit")
    else:
        monkeypatch.setattr(gateway, "_cgroup", lambda: "0::/wrong-unit")
    with pytest.raises(ValueError, match="SCOPE_INVALID"):
        endpoint.module.cleanup_stopped_endpoint()


def test_browser_cleanup_requires_released_profile_lock(endpoint):
    if endpoint.module is not browser:
        return
    with endpoint.lock.open("rb") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="PROFILE_BUSY"):
            endpoint.module.cleanup_stopped_endpoint()
