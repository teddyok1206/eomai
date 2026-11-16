"""Real lock exclusion and first-use receipt checks without reading browser credentials."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_kakao_archive_contracts.profile_installation import (
    SCHEMA_SHA256,
    parse_fresh_profile_installation,
)
from eom_orchestrator import kakao_profile_observation as profile
from eom_orchestrator.kakao_runtime_os import IdleRuntimeObservation

ROOT = Path(__file__).resolve().parents[2]
PROFILE_ID = "kakaoprofile_" + "1" * 32
HASH = "sha256:" + "2" * 64
BOOT = "12345678-1234-1234-1234-123456789abc"


def receipt():
    return dict(
        schema_version="kakao-profile-fresh-install/1.0",
        profile_id=PROFILE_ID,
        profile_device=1,
        profile_inode=2,
        profile_mtime_ns=3,
        profile_ctime_ns=4,
        install_manifest_sha256=HASH,
    )


def test_root_receipt_schema_is_canonical_and_mirrored():
    name = "fresh-profile-v1.schema.json"
    canonical = (ROOT / "schemas/kakao-archive" / name).read_bytes()
    mirror = (
        ROOT / "packages/kakao_archive_contracts/eom_kakao_archive_contracts/schemas" / name
    ).read_bytes()
    assert canonical == mirror and hashlib.sha256(canonical).hexdigest() == SCHEMA_SHA256
    assert parse_fresh_profile_installation(json.dumps(receipt()).encode()).profile_id == PROFILE_ID


@pytest.mark.parametrize(
    "case", ["duplicate", "extra", "boolean", "negative", "zero-inode", "oversized"]
)
def test_invalid_root_receipt_is_not_implicit_fresh_profile(case):
    value = receipt()
    if case == "extra":
        value["profile_path"] = "/other"
    if case == "boolean":
        value["profile_device"] = False
    if case == "negative":
        value["profile_ctime_ns"] = -1
    if case == "zero-inode":
        value["profile_inode"] = 0
    raw = json.dumps(value).encode()
    if case == "duplicate":
        raw = b'{"profile_inode":99,' + raw[1:]
    if case == "oversized":
        raw += b" " * 4096
    with pytest.raises(ValueError, match="RECEIPT_INVALID"):
        parse_fresh_profile_installation(raw)


@pytest.fixture
def observer(monkeypatch):
    owner = os.getuid() or 1000
    monkeypatch.setattr(profile.os, "geteuid", lambda: owner)
    monkeypatch.setattr(profile.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=owner))
    monkeypatch.setattr(
        profile.runtime_os, "read_protected", lambda *args, **kwargs: json.dumps(receipt()).encode()
    )
    metadata = SimpleNamespace(st_dev=1, st_ino=2, st_mtime_ns=3, st_ctime_ns=4)
    monkeypatch.setattr(profile, "_metadata", lambda: metadata)
    monkeypatch.setattr(profile, "profile_lock_released", lambda: True)
    browser, gateway = Mock(), Mock()
    for mock, unit in [(browser, "browser"), (gateway, "remote")]:
        mock.observe_idle.return_value = IdleRuntimeObservation(
            "eom-kakao-" + unit + ".service", BOOT, datetime.now(UTC), "EMPTY", True
        )
    return profile.InstalledKakaoProfileObserver(PROFILE_ID, HASH, browser, gateway), metadata


def test_fresh_proof_requires_both_closed_runtimes_exact_receipt_and_real_exclusion(observer):
    value, _ = observer
    result = value.observe()
    assert result.never_used and result.profile_empty and result.profile_lock_released
    assert result.browser_stopped and result.gateway_stopped
    value.browser.observe_idle.assert_called_once()
    value.gateway.observe_idle.assert_called_once()


@pytest.mark.parametrize("case", ["directory-used", "browser-used", "gateway-used", "lock-busy"])
def test_used_or_busy_profile_is_not_reassigned_as_fresh(observer, monkeypatch, case):
    value, metadata = observer
    if case == "directory-used":
        metadata.st_ctime_ns += 1
    elif case == "lock-busy":
        monkeypatch.setattr(profile, "profile_lock_released", lambda: False)
    else:
        target = value.browser if case == "browser-used" else value.gateway
        target.observe_idle.return_value = replace(
            target.observe_idle.return_value, never_dispatched=False
        )
    result = value.observe()
    assert not (result.never_used and result.profile_empty and result.profile_lock_released)


@pytest.mark.parametrize(
    "case", ["receipt-hash", "receipt-id", "stale", "boot", "unit", "changing"]
)
def test_wrong_installation_or_inconsistent_runtime_is_explicit(observer, monkeypatch, case):
    value, metadata = observer
    if case.startswith("receipt"):
        value = replace(
            value,
            **(
                {"profile_id": "kakaoprofile_" + "3" * 32}
                if case == "receipt-id"
                else {"install_manifest_sha256": "sha256:" + "3" * 64}
            ),
        )
    elif case == "changing":
        monkeypatch.setattr(
            profile,
            "_metadata",
            Mock(
                side_effect=[
                    metadata,
                    SimpleNamespace(st_dev=1, st_ino=2, st_mtime_ns=3, st_ctime_ns=5),
                ]
            ),
        )
    else:
        changes = {
            "stale": {"observed_at": datetime.now(UTC) - timedelta(seconds=6)},
            "boot": {"boot_id": "abcdefab-1234-1234-1234-123456789abc"},
            "unit": {"unit": "other.service"},
        }
        value.gateway.observe_idle.return_value = replace(
            value.gateway.observe_idle.return_value, **changes[case]
        )
    with pytest.raises(profile.KakaoProfileObservationError):
        value.observe()


def test_readonly_fd_flock_observes_real_other_process_without_touching_lock(monkeypatch):
    # Fixture under the private workspace, not a runtime lock and not browser cookies.
    with tempfile.TemporaryDirectory(prefix="kakao-profile-probe-", dir=ROOT / "staging") as name:
        path = Path(name) / "profile.lock"
        path.touch(mode=0o640)
        path.chmod(0o640)
        before = path.stat()
        monkeypatch.setattr(profile, "LOCK", path)
        monkeypatch.setattr(profile.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=os.getuid()))
        monkeypatch.setattr(profile.grp, "getgrnam", lambda _: SimpleNamespace(gr_gid=os.getgid()))
        real_directory = profile.runtime_os.protected_directory
        monkeypatch.setattr(
            profile.runtime_os,
            "protected_directory",
            lambda value, *, owners: real_directory(value, owners=frozenset({0, os.getuid()})),
        )
        assert profile.profile_lock_released()
        program = (
            "import fcntl,sys,time; f=open(sys.argv[1],'r');"
            "fcntl.flock(f,fcntl.LOCK_EX); print('held',flush=True); time.sleep(30)"
        )
        child = subprocess.Popen(
            [sys.executable, "-c", program, str(path)], stdout=subprocess.PIPE, text=True
        )
        try:
            assert child.stdout.readline().strip() == "held"
            assert not profile.profile_lock_released()
        finally:
            child.terminate()
            child.wait(timeout=3)
        assert profile.profile_lock_released()
        after = path.stat()
        assert (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
