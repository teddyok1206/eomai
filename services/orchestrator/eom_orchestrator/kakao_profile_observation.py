"""Observe installed profile exclusion without reading its cookies or browser files."""

from __future__ import annotations

import fcntl
import grp
import os
import pwd
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from eom_catalog_contracts.kakao_manual import KakaoManualFreshProfile
from eom_kakao_archive_contracts.profile_installation import parse_fresh_profile_installation

from . import kakao_runtime_os as runtime_os
from .kakao_browser_runtime import FixedKakaoBrowserRuntime
from .kakao_gateway_runtime import FixedKakaoGatewayRuntime

PROFILE = Path("/var/lib/eom-kakao/profile")
LOCK = PROFILE.parent / "profile.lock"
RECEIPT = Path("/var/lib/eom-kakao-runtime/fresh-profile.json")


class KakaoProfileObservationError(ValueError):
    pass


def _metadata() -> os.stat_result:
    browser = pwd.getpwnam("eom-kakao")
    control_group = grp.getgrnam("eom-kakao-control").gr_gid
    with runtime_os.protected_directory(PROFILE.parent, owners=frozenset({0})) as directory:
        parent = os.fstat(directory)
        info = os.stat(PROFILE.name, dir_fd=directory, follow_symlinks=False)
        if (
            parent.st_gid != control_group
            or stat.S_IMODE(parent.st_mode) != 0o750
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != browser.pw_uid
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise KakaoProfileObservationError("KAKAO_PROFILE_DIRECTORY_UNTRUSTED")
        return info


def profile_lock_released() -> bool:
    """Read-only flock probe; contention is not proof of a specific browser owner."""
    browser = pwd.getpwnam("eom-kakao")
    control_group = grp.getgrnam("eom-kakao-control").gr_gid
    with runtime_os.protected_directory(LOCK.parent, owners=frozenset({0})) as directory:
        fd = os.open(
            LOCK.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory
        )
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != browser.pw_uid
                or info.st_gid != control_group
                or stat.S_IMODE(info.st_mode) != 0o640
                or info.st_nlink != 1
                or info.st_size
            ):
                raise KakaoProfileObservationError("KAKAO_PROFILE_LOCK_UNTRUSTED")
            released = True
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                released = False
            linked = os.stat(LOCK.name, dir_fd=directory, follow_symlinks=False)
            if (linked.st_dev, linked.st_ino) != (info.st_dev, info.st_ino):
                raise KakaoProfileObservationError("KAKAO_PROFILE_LOCK_UNTRUSTED")
            return released
        finally:
            os.close(fd)


@dataclass(frozen=True, slots=True)
class InstalledKakaoProfileObserver:
    profile_id: str
    install_manifest_sha256: str
    browser: FixedKakaoBrowserRuntime
    gateway: FixedKakaoGatewayRuntime

    def observe(self) -> KakaoManualFreshProfile:
        if (
            os.geteuid() == 0
            or os.geteuid() != pwd.getpwnam("eom-catalog-manager").pw_uid
            or re.fullmatch(r"kakaoprofile_[0-9a-f]{32}", self.profile_id) is None
            or re.fullmatch(r"sha256:[0-9a-f]{64}", self.install_manifest_sha256) is None
        ):
            raise KakaoProfileObservationError("KAKAO_PROFILE_OWNER_INVALID")
        raw = runtime_os.read_protected(RECEIPT, uid=0, maximum=4096, owners=frozenset({0}))
        receipt = parse_fresh_profile_installation(raw)
        if (
            receipt.profile_id != self.profile_id
            or receipt.install_manifest_sha256 != self.install_manifest_sha256
        ):
            raise KakaoProfileObservationError("KAKAO_PROFILE_INSTALLATION_MISMATCH")
        browser, gateway = self.browser.observe_idle(), self.gateway.observe_idle()
        before = _metadata()
        released = profile_lock_released()
        after = _metadata()
        fields = ("st_dev", "st_ino", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, key) != getattr(after, key) for key in fields):
            raise KakaoProfileObservationError("KAKAO_PROFILE_CHANGED")
        now = datetime.now(UTC)
        if (
            browser.unit != "eom-kakao-browser.service"
            or gateway.unit != "eom-kakao-remote.service"
            or browser.boot_id != gateway.boot_id
            or not all(
                timedelta(0) <= now - value.observed_at <= timedelta(seconds=5)
                for value in (browser, gateway)
            )
        ):
            raise KakaoProfileObservationError("KAKAO_PROFILE_OBSERVATION_STALE")
        unchanged = (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns) == (
            receipt.profile_device,
            receipt.profile_inode,
            receipt.profile_mtime_ns,
            receipt.profile_ctime_ns,
        )
        # A used directory cannot regain its root-pinned ctime. An unchanged empty
        # install proves first use only when no managed dispatch has ever existed.
        return KakaoManualFreshProfile(
            profile_id=self.profile_id,
            observed_at=min(browser.observed_at, gateway.observed_at),
            boot_id=browser.boot_id,
            never_used=unchanged and browser.never_dispatched and gateway.never_dispatched,
            profile_empty=unchanged,
            browser_stopped=True,
            gateway_stopped=True,
            profile_lock_released=released,
        )
