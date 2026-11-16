"""Fixed protected Kakao runtime stage/verify; never install packages or activate services."""

from __future__ import annotations

import argparse
import fcntl
import grp
import hashlib
import importlib.metadata
import json
import os
import pwd
import re
import stat
import subprocess
import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

PREFIXES = {
    name: Path("/opt/eom/conda/envs") / f"eom-kakao-{name}" for name in ("browser", "remote", "pdf")
}
BROWSER = Path("/opt/eom/kakao-browser/playwright-1.65.2")
NOVNC = Path("/opt/eom/kakao-remote/releases/novnc-1.6.0/noVNC")
XVNC = Path("/usr/bin/Xtigervnc")
OWNER_DROPIN = Path(
    "/etc/systemd/system/eom-catalog-application-runner.service.d/50-eom-kakao-manual.conf"
)
PROXY_DROPIN = Path("/etc/systemd/system/caddy.service.d/50-eom-kakao-proxy.conf")
FRESH_RECEIPT = Path("/var/lib/eom-kakao-runtime/fresh-profile.json")
DROPIN_DIRECTORIES = frozenset({OWNER_DROPIN.parent, PROXY_DROPIN.parent})
PAYLOADS = {
    "eom-kakao-browser.service": Path("/etc/systemd/system/eom-kakao-browser.service"),
    "eom-kakao-remote.service": Path("/etc/systemd/system/eom-kakao-remote.service"),
    "eom-kakao-pdf@.service": Path("/etc/systemd/system/eom-kakao-pdf@.service"),
    "46-eom-kakao-runtime.rules": Path("/etc/polkit-1/rules.d/46-eom-kakao-runtime.rules"),
    "eom-kakao-runtime.conf": Path("/etc/tmpfiles.d/eom-kakao-runtime.conf"),
    "50-eom-kakao-manual.conf.in": OWNER_DROPIN,
    "50-eom-kakao-proxy.conf": PROXY_DROPIN,
}
USERS = ("eom-kakao", "eom-kakao-remote", "eom-kakao-render")
GROUPS = (*USERS, "eom-kakao-vnc", "eom-kakao-proxy", "eom-kakao-grant", "eom-kakao-control")
EXTRA_GROUPS = {
    "eom-kakao": {"eom-kakao-control"},
    "eom-kakao-remote": {"eom-kakao-vnc", "eom-kakao-proxy", "eom-kakao-grant"},
}
ROOT_UID = 0
ROOT_GID = 0
MAX_TOTAL = 8 * 1024**3
HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
RUNTIME_LOCKS = (
    (Path("/var/lib/eom-kakao-runtime/browser/control.lock"), "eom-catalog-manager", 0o600),
    (Path("/var/lib/eom-kakao-runtime/remote/control.lock"), "eom-catalog-manager", 0o600),
    (Path("/var/lib/eom-kakao/profile.lock"), "eom-kakao", 0o640),
)


class InstallError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise InstallError("KAKAO_INSTALL_" + code)


def protected(path: Path, *, directory: bool) -> os.stat_result:
    if not path.is_absolute() or ".." in path.parts:
        fail("PATH_INVALID")
    for parent in reversed(path.parents):
        info = parent.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid not in {0, ROOT_UID}
            or info.st_mode & 0o022
        ):
            fail("PARENT_UNTRUSTED")
    info = path.lstat()
    if (
        info.st_uid != ROOT_UID
        or info.st_mode & 0o6022
        or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
        or (not directory and info.st_nlink != 1)
    ):
        fail("MEMBER_UNTRUSTED")
    return info


def digest(path: Path, *, maximum: int = 1024**3) -> str:
    before = protected(path, directory=False)
    if not 0 <= before.st_size <= maximum:
        fail("MEMBER_SIZE_INVALID")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as stream:
        if os.fstat(stream.fileno()) != before:
            fail("MEMBER_CHANGED")
        result = hashlib.sha256()
        size = 0
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > before.st_size:
                fail("MEMBER_CHANGED")
            result.update(chunk)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode")
    if size != before.st_size or any(getattr(before, f) != getattr(after, f) for f in fields):
        fail("MEMBER_CHANGED")
    if any(getattr(after, f) != getattr(path.lstat(), f) for f in fields):
        fail("MEMBER_CHANGED")
    return "sha256:" + result.hexdigest()


def tree_digest(root: Path) -> str:
    """Same sorted D/F/L byte-tree shape as the existing fixed numerical publisher."""
    protected(root, directory=True)
    entries: list[tuple[str, bytes]] = []
    total = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        protected(directory, directory=True)
        before = directory.stat()
        for path in directory.iterdir():
            relative = "./" + path.relative_to(root).as_posix()
            if any(ord(c) < 32 or ord(c) == 127 for c in relative):
                fail("TREE_NAME_INVALID")
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(path)
                if info.st_uid != ROOT_UID or not path.resolve(strict=True).is_relative_to(root):
                    fail("LINK_ESCAPE")
                if any(ord(c) < 32 or ord(c) == 127 for c in target):
                    fail("TREE_NAME_INVALID")
                data = f"L\0{relative}\0{target}\0".encode()
            elif stat.S_ISDIR(info.st_mode):
                pending.append(path)
                data = f"D\0{relative}\0".encode()
            else:
                total += info.st_size
                if total > MAX_TOTAL:
                    fail("TREE_TOO_LARGE")
                data = f"F\0{relative}\0{digest(path)[7:]}\0".encode()
            entries.append((relative, data))
            if len(entries) > 100000:
                fail("TREE_TOO_LARGE")
        after = directory.stat()
        if (before.st_ino, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_ino,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            fail("TREE_CHANGED")
    return "sha256:" + hashlib.sha256(b"".join(row for _, row in sorted(entries))).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail("MANIFEST_DUPLICATE")
        result[key] = value
    return result


def load_manifest(path: Path, expected: str) -> dict[str, Any]:
    if not HASH.fullmatch(expected) or digest(path, maximum=32768) != expected:
        fail("MANIFEST_HASH_MISMATCH")
    value = json.loads(path.read_bytes(), object_pairs_hook=_pairs)
    fields = {
        "schema_version",
        "source_commit",
        "profile_id",
        "runtime_sha256",
        "browser_assets_sha256",
        "novnc_assets_sha256",
        "chromium_member",
        "xvnc_sha256",
        "renderer_release_sha256",
        "payload_sha256",
    }
    if not isinstance(value, dict) or set(value) != fields:
        fail("MANIFEST_INVALID")
    if (
        value["schema_version"] != "kakao-runtime-install/1.0"
        or not isinstance(value["source_commit"], str)
        or not re.fullmatch(r"[0-9a-f]{40}", value["source_commit"])
    ):
        fail("MANIFEST_INVALID")
    for key, names in (("runtime_sha256", set(PREFIXES)), ("payload_sha256", set(PAYLOADS))):
        if not isinstance(value[key], dict) or set(value[key]) != names:
            fail("MANIFEST_INVALID")
    hashes = [
        value[k]
        for k in (
            "browser_assets_sha256",
            "novnc_assets_sha256",
            "xvnc_sha256",
            "renderer_release_sha256",
        )
    ]
    hashes += list(value["runtime_sha256"].values()) + list(value["payload_sha256"].values())
    if any(not isinstance(h, str) or not HASH.fullmatch(h) for h in hashes):
        fail("MANIFEST_INVALID")
    member = value["chromium_member"]
    if not isinstance(value["profile_id"], str) or not re.fullmatch(
        r"kakaoprofile_[0-9a-f]{32}", value["profile_id"]
    ):
        fail("MANIFEST_INVALID")
    if (
        not isinstance(member, str)
        or len(member) > 256
        or not re.fullmatch(r"chromium-[0-9]+/chrome-linux(64)?/chrome", member)
    ):
        fail("MANIFEST_INVALID")
    return value


def run(argv: list[str], *, capture: bool = False) -> bytes:
    result = subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
        timeout=30,
        check=False,
    )
    if result.returncode:
        fail("COMMAND_FAILED")
    if capture and len(result.stdout) > 524288:
        fail("OBSERVATION_TOO_LARGE")
    return result.stdout if capture else b""


def require_stopped() -> None:
    # Do not reload a unit manager, stop a task, or infer closure from a stopped main PID.
    raw = run(
        [
            "/usr/bin/systemctl",
            "list-units",
            "--all",
            "--no-legend",
            "--plain",
            "--state=active,activating,deactivating,reloading",
            "eom-kakao-*",
        ],
        capture=True,
    )
    if raw.strip():
        fail("ACTIVE_RUNTIME")
    jobs = run(["/usr/bin/systemctl", "list-jobs", "--no-legend", "--plain"], capture=True)
    if b"eom-kakao-" in jobs:
        fail("PENDING_SYSTEMD_JOB")
    for name in ("eom-kakao-browser.service", "eom-kakao-remote.service"):
        populated = Path("/sys/fs/cgroup/system.slice") / name / "cgroup.events"
        if populated.exists() and "populated 1" in populated.read_text():
            fail("ACTIVE_RUNTIME")


def check_identities(*, required: bool) -> None:
    for name in USERS:
        try:
            user = pwd.getpwnam(name)
        except KeyError:
            if required:
                fail("IDENTITY_MISSING")
            continue
        base = grp.getgrnam(name)
        allowed = {name, *EXTRA_GROUPS.get(name, set())}
        actual = {grp.getgrgid(g).gr_name for g in os.getgrouplist(name, user.pw_gid)}
        if (
            user.pw_uid == 0
            or user.pw_gid != base.gr_gid
            or actual != allowed
            or user.pw_dir != "/nonexistent"
            or user.pw_shell != "/usr/sbin/nologin"
        ):
            fail("IDENTITY_OVERPRIVILEGED")
    if required:
        for name in GROUPS:
            if grp.getgrnam(name).gr_gid == 0:
                fail("IDENTITY_OVERPRIVILEGED")
    allowed_members = {name: {name} for name in USERS}
    allowed_members.update(
        {
            "eom-kakao-render": {"eom-kakao-render", "eom-catalog-manager"},
            "eom-kakao-vnc": {"eom-kakao", "eom-kakao-remote"},
            "eom-kakao-proxy": {"eom-kakao-remote", "caddy"},
            "eom-kakao-grant": {"eom-kakao-remote"},
            "eom-kakao-control": {"eom-kakao", "eom-catalog-manager"},
        }
    )
    for name, members in allowed_members.items():
        try:
            group = grp.getgrnam(name)
        except KeyError:
            continue
        if not set(group.gr_mem).issubset(members):
            fail("IDENTITY_OVERPRIVILEGED")


def prepare_identities() -> None:
    check_identities(required=False)
    for name in GROUPS:
        try:
            grp.getgrnam(name)
        except KeyError:
            run(["/usr/sbin/groupadd", "--system", name])
    for name in USERS:
        try:
            pwd.getpwnam(name)
        except KeyError:
            argv = [
                "/usr/sbin/useradd",
                "--system",
                "--gid",
                name,
                "--home-dir",
                "/nonexistent",
                "--no-create-home",
                "--shell",
                "/usr/sbin/nologin",
            ]
            if extra := EXTRA_GROUPS.get(name):
                argv += ["--groups", ",".join(sorted(extra))]
            run([*argv, name])
    # Catalog receives fixed-lock and isolated-render I/O groups. Worker identities
    # never gain Catalog/NAS access; no existing service is restarted here.
    owner = pwd.getpwnam("eom-catalog-manager")
    required_groups = ("eom-kakao-control", "eom-kakao-render")
    if any(
        grp.getgrnam(name).gr_gid not in os.getgrouplist(owner.pw_name, owner.pw_gid)
        for name in required_groups
    ):
        run(
            [
                "/usr/sbin/usermod",
                "--append",
                "--groups",
                ",".join(required_groups),
                "eom-catalog-manager",
            ]
        )
    check_identities(required=True)


def check_versions(name: str, prefix: Path) -> None:
    versions = {
        "eom-kakao-archive-contracts": "0.1.0",
        "pydantic": "2.13.4",
        "jsonschema": "4.25.1",
    }
    versions.update(
        {
            "browser": {"eom-kakao-archive-collector": "0.1.0", "playwright": "1.65.2"},
            "remote": {"eom-kakao-archive-gateway": "0.1.0", "websockify": "0.13.0"},
            "pdf": {"eom-kakao-archive-worker": "0.1.0", "PyMuPDF": "1.26.7", "Pillow": "11.3.0"},
        }[name]
    )
    observed: dict[str, str] = {}
    for distribution in importlib.metadata.distributions(
        path=[str(prefix / "lib/python3.12/site-packages")]
    ):
        key = distribution.metadata["Name"].lower().replace("_", "-")
        if key in observed:
            fail("DISTRIBUTION_DUPLICATE")
        observed[key] = distribution.version
    if any(observed.get(key.lower().replace("_", "-")) != value for key, value in versions.items()):
        fail("DEPENDENCY_VERSION_MISMATCH")
    if not (prefix / "bin/python").resolve(strict=True).is_relative_to(prefix):
        fail("INTERPRETER_INVALID")
    metadata = tuple((prefix / "conda-meta").glob("python-3.12.13-*.json"))
    if len(metadata) != 1:
        fail("PYTHON_VERSION_MISMATCH")
    value = json.loads(metadata[0].read_bytes())
    if value.get("name") != "python" or value.get("version") != "3.12.13":
        fail("PYTHON_VERSION_MISMATCH")


@dataclass(frozen=True)
class Layout:
    path: Path
    uid: int
    gid: int
    mode: int


@contextmanager
def layout_parent(entry: Layout) -> Iterator[int]:
    """Never traverse a link, including an owner-writable staging ancestor."""
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in entry.path.parent.parts[1:]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd
            )
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            if info.st_uid not in {0, ROOT_UID, entry.uid} or info.st_mode & 0o022:
                fail("LAYOUT_PARENT_UNTRUSTED")
        yield fd
    finally:
        os.close(fd)


def layout() -> tuple[Layout, ...]:
    browser, remote, owner = (
        pwd.getpwnam(n) for n in ("eom-kakao", "eom-kakao-remote", "eom-catalog-manager")
    )
    root = Path("/var/lib/eom-kakao-runtime")
    return (
        Layout(Path("/var/lib/eom-kakao"), 0, grp.getgrnam("eom-kakao-control").gr_gid, 0o750),
        Layout(Path("/var/lib/eom-kakao/profile"), browser.pw_uid, browser.pw_gid, 0o700),
        Layout(root, 0, 0, 0o755),
        Layout(root / "browser", owner.pw_uid, browser.pw_gid, 0o2750),
        Layout(root / "remote", owner.pw_uid, grp.getgrnam("eom-kakao-grant").gr_gid, 0o2750),
        Layout(Path("/run/eom-kakao-private"), browser.pw_uid, browser.pw_gid, 0o700),
        Layout(
            Path("/run/eom-kakao-vnc"), browser.pw_uid, grp.getgrnam("eom-kakao-vnc").gr_gid, 0o2750
        ),
        Layout(
            Path("/run/eom-kakao-remote"),
            remote.pw_uid,
            grp.getgrnam("eom-kakao-proxy").gr_gid,
            0o2750,
        ),
        Layout(
            Path("/var/lib/eom-catalog-api/staging/kakao-render"), owner.pw_uid, owner.pw_gid, 0o700
        ),
        Layout(
            Path("/var/lib/eom-catalog-api/staging/kakao-pdf-inputs"),
            owner.pw_uid,
            owner.pw_gid,
            0o700,
        ),
    )


def exact_layout(entry: Layout, *, create: bool, content: bytes | None = None) -> None:
    with layout_parent(entry) as parent:
        _exact_layout(entry, parent, create=create, content=content)


@contextmanager
def existing_runtime_locks() -> Iterator[None]:
    """Exclude owner starts and a physically held profile during a staged update."""
    with ExitStack() as stack:
        for path, name, mode in RUNTIME_LOCKS:
            if not os.path.lexists(path):
                continue
            user = pwd.getpwnam(name)
            parent = stack.enter_context(
                layout_parent(Layout(path, user.pw_uid, user.pw_gid, mode))
            )
            fd = os.open(
                path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent
            )
            stack.callback(os.close, fd)
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != user.pw_uid
                or info.st_size
                or stat.S_IMODE(info.st_mode) != mode
            ):
                fail("RUNTIME_LOCK_UNTRUSTED")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                fail("RUNTIME_BUSY")
            linked = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if (linked.st_dev, linked.st_ino) != (info.st_dev, info.st_ino):
                fail("RUNTIME_LOCK_UNTRUSTED")
        yield


def _exact_layout(entry: Layout, parent: int, *, create: bool, content: bytes | None) -> None:
    try:
        info = os.stat(entry.path.name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        if not create:
            fail("LAYOUT_MISSING")
        if content is None:
            os.mkdir(entry.path.name, mode=0o700, dir_fd=parent)
        else:
            fd = os.open(
                entry.path.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        os.chown(entry.path.name, entry.uid, entry.gid, dir_fd=parent, follow_symlinks=False)
        os.chmod(entry.path.name, entry.mode, dir_fd=parent, follow_symlinks=False)
        info = os.stat(entry.path.name, dir_fd=parent, follow_symlinks=False)
        os.fsync(parent)
    kind = stat.S_ISDIR(info.st_mode) if content is None else stat.S_ISREG(info.st_mode)
    if not kind or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (
        entry.uid,
        entry.gid,
        entry.mode,
    ):
        fail("LAYOUT_CONFLICT")
    if content is not None:
        if info.st_nlink != 1 or info.st_size != len(content):
            fail("PAYLOAD_CONFLICT")
        fd = os.open(entry.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            if (
                os.fstat(stream.fileno()).st_ino != info.st_ino
                or stream.read(len(content) + 1) != content
            ):
                fail("PAYLOAD_CONFLICT")


def preflight(
    manifest: dict[str, Any], payload: Path, *, manifest_sha256: str
) -> dict[Path, bytes]:
    if not HASH.fullmatch(manifest_sha256):
        fail("MANIFEST_HASH_MISMATCH")
    protected(payload, directory=True)
    if {p.name for p in payload.iterdir()} != set(PAYLOADS):
        fail("PAYLOAD_SET_INVALID")
    for name, path in PREFIXES.items():
        if tree_digest(path) != manifest["runtime_sha256"][name]:
            fail("RUNTIME_HASH_MISMATCH")
        executable = path / "bin/python3.12"
        if not protected(executable, directory=False).st_mode & 0o111:
            fail("INTERPRETER_INVALID")
        check_versions(name, path)
    for path, expected in (
        (BROWSER, manifest["browser_assets_sha256"]),
        (NOVNC, manifest["novnc_assets_sha256"]),
    ):
        if tree_digest(path) != expected:
            fail("ASSET_HASH_MISMATCH")
    if digest(XVNC) != manifest["xvnc_sha256"]:
        fail("XVNC_HASH_MISMATCH")
    for name in ("vnc.html", "app/ui.js", "core/rfb.js", "LICENSE.txt"):
        digest(NOVNC / name, maximum=8 * 1024**2)
    files: dict[Path, bytes] = {}
    for name, target in PAYLOADS.items():
        if digest(payload / name, maximum=65536) != manifest["payload_sha256"][name]:
            fail("PAYLOAD_HASH_MISMATCH")
        files[target] = (payload / name).read_bytes()
    driver = PREFIXES["browser"] / "bin/eom-kakao-browser-driver"
    gateway_supervisor = (
        PREFIXES["remote"] / "lib/python3.12/site-packages/eom_kakao_archive_gateway/supervisor.py"
    )
    chromium = BROWSER / manifest["chromium_member"]
    for executable in (driver, chromium, XVNC):
        if not protected(executable, directory=False).st_mode & 0o111:
            fail("EXECUTABLE_INVALID")
    files[Path("/etc/eom/kakao-browser.env")] = (
        f"EOM_KAKAO_BROWSER_DRIVER_SHA256={digest(driver)}\n".encode()
    )
    files[Path("/etc/eom/kakao-browser-driver.env")] = (
        f"EOM_KAKAO_XVNC_SHA256={manifest['xvnc_sha256']}\nEOM_KAKAO_CHROMIUM_SHA256={digest(chromium)}\n".encode()
    )
    files[Path("/etc/eom/kakao-pdf.env")] = (
        f"EOM_KAKAO_RENDER_RELEASE_SHA256={manifest['renderer_release_sha256']}\n".encode()
    )
    # The template is independently hash-pinned above. Substitutions are only exact trusted
    # identities, never operator-supplied paths, arbitrary environment names or shell commands.
    pins = {
        "profile_id": manifest["profile_id"],
        "browser_template_sha256": manifest["payload_sha256"]["eom-kakao-browser.service"],
        "browser_driver_sha256": digest(driver),
        "gateway_template_sha256": manifest["payload_sha256"]["eom-kakao-remote.service"],
        "gateway_supervisor_sha256": digest(gateway_supervisor),
        "initial_profile_manifest_sha256": (
            fresh_receipt_manifest(FRESH_RECEIPT, profile_id=manifest["profile_id"])
            or manifest_sha256
        ),
    }
    try:
        files[OWNER_DROPIN] = files[OWNER_DROPIN].decode("ascii").format_map(pins).encode("ascii")
    except (ValueError, KeyError, UnicodeError):
        fail("OWNER_TEMPLATE_INVALID")
    require_stopped()
    check_identities(required=False)
    return files


def fresh_receipt_manifest(target: Path, *, profile_id: str) -> str | None:
    """Read the protected original installation fact, never the current release pin."""
    if target.exists() or target.is_symlink():
        digest(target, maximum=4096)
        metadata = target.lstat()
        if metadata.st_gid != ROOT_GID or stat.S_IMODE(metadata.st_mode) != 0o644:
            fail("FRESH_RECEIPT_CONFLICT")
        value = json.loads(target.read_bytes(), object_pairs_hook=_pairs)
        expected_keys = {
            "schema_version",
            "profile_id",
            "profile_device",
            "profile_inode",
            "profile_mtime_ns",
            "profile_ctime_ns",
            "install_manifest_sha256",
        }
        if (
            not isinstance(value, dict)
            or set(value) != expected_keys
            or value["schema_version"] != "kakao-profile-fresh-install/1.0"
            or value["profile_id"] != profile_id
            or not isinstance(value["install_manifest_sha256"], str)
            or HASH.fullmatch(value["install_manifest_sha256"]) is None
        ):
            fail("FRESH_RECEIPT_CONFLICT")
        for name in ("profile_device", "profile_inode", "profile_mtime_ns", "profile_ctime_ns"):
            if type(value[name]) is not int or value[name] < (1 if name == "profile_inode" else 0):
                fail("FRESH_RECEIPT_CONFLICT")
        return str(value["install_manifest_sha256"])
    return None


def fresh_receipt(
    profile: Path, target: Path, *, profile_id: str, manifest_sha256: str, created: bool
) -> str:
    initial_manifest = fresh_receipt_manifest(target, profile_id=profile_id)
    if initial_manifest is not None:
        return initial_manifest  # Preserve the original fact after profile use or a new release.
    if not created:
        fail("FRESH_PROFILE_RECONCILE_REQUIRED")
    fd = os.open(profile, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        if os.listdir(fd):
            fail("FRESH_PROFILE_NOT_EMPTY")
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            fail("FRESH_PROFILE_CHANGED")
        value = {
            "schema_version": "kakao-profile-fresh-install/1.0",
            "profile_id": profile_id,
            "profile_device": after.st_dev,
            "profile_inode": after.st_ino,
            "profile_mtime_ns": after.st_mtime_ns,
            "profile_ctime_ns": after.st_ctime_ns,
            "install_manifest_sha256": manifest_sha256,
        }
        payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        exact_layout(Layout(target, ROOT_UID, ROOT_GID, 0o644), create=True, content=payload)
    finally:
        os.close(fd)
    return manifest_sha256


def apply_layout(
    files: dict[Path, bytes], *, create: bool, profile_id: str, manifest_sha256: str
) -> None:
    if create:
        prepare_identities()
    else:
        check_identities(required=True)
    entries = layout()
    profile_created = create and not os.path.lexists(entries[1].path)
    for entry in entries:
        exact_layout(entry, create=create)
    for entry in (
        Layout(
            Path("/var/lib/eom-kakao/profile.lock"),
            entries[1].uid,
            grp.getgrnam("eom-kakao-control").gr_gid,
            0o640,
        ),
        Layout(
            Path("/var/lib/eom-kakao-runtime/browser/control.lock"),
            entries[3].uid,
            entries[3].gid,
            0o600,
        ),
        Layout(
            Path("/var/lib/eom-kakao-runtime/remote/control.lock"),
            entries[4].uid,
            entries[4].gid,
            0o600,
        ),
    ):
        exact_layout(entry, create=create, content=b"")
    initial_manifest = fresh_receipt(
        entries[1].path,
        FRESH_RECEIPT,
        profile_id=profile_id,
        manifest_sha256=manifest_sha256,
        created=profile_created,
    )
    # Preflight precedes the install/runtime locks. Recheck the initial pin under those
    # locks before publishing any config, including a previously missing owner drop-in.
    prefix = b"Environment=EOM_KAKAO_INITIAL_PROFILE_MANIFEST_SHA256="
    actual = [line for line in files.get(OWNER_DROPIN, b"").splitlines() if line.startswith(prefix)]
    if actual != [prefix + initial_manifest.encode("ascii")]:
        fail("FRESH_RECEIPT_CONFLICT")
    for target, data in files.items():
        if target.parent in DROPIN_DIRECTORIES:
            exact_layout(Layout(target.parent, 0, 0, 0o755), create=create)
        protected(target.parent, directory=True)
        exact_layout(Layout(target, 0, 0, 0o644), create=create, content=data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "stage", "verify"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--payload", type=Path, required=True)
    args = parser.parse_args()
    try:
        if os.geteuid() != 0 or not (
            sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode
        ):
            fail("PROTECTED_OPERATOR_REQUIRED")
        protected(Path(__file__), directory=False)
        if not Path(sys.prefix).is_relative_to("/opt/eom/conda/envs") or sys.version_info[:3] != (
            3,
            12,
            13,
        ):
            fail("PROTECTED_OPERATOR_REQUIRED")
        protected(Path(sys.executable).resolve(strict=True), directory=False)
        manifest = load_manifest(args.manifest, args.manifest_sha256)
        files = preflight(manifest, args.payload, manifest_sha256=args.manifest_sha256)
        if args.action != "preflight":
            lock = Path("/run/eom-kakao-install/install.lock")
            exact_layout(Layout(lock.parent, 0, 0, 0o700), create=args.action == "stage")
            protected(lock.parent, directory=True)
            exact_layout(Layout(lock, 0, 0, 0o600), create=args.action == "stage", content=b"")
            fd = os.open(lock, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with existing_runtime_locks():
                    require_stopped()
                    apply_layout(
                        files,
                        create=args.action == "stage",
                        profile_id=manifest["profile_id"],
                        manifest_sha256=args.manifest_sha256,
                    )
            finally:
                os.close(fd)
        print("KAKAO_RUNTIME_" + args.action.upper() + "_PASS_NOT_ACTIVATED")
        print(
            "CREDENTIALS=NOT_PROVISIONED_BY_INSTALLER; MANUAL_MODE=DISABLED; "
            "CADDY_ROUTES=UNCHANGED; DAEMON_RELOAD=NOT_RUN"
        )
        return 0
    except Exception as error:
        print(
            str(error) if isinstance(error, InstallError) else "KAKAO_INSTALL_REJECTED",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
