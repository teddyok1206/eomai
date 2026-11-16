"""Initial-only fixed Kakao prefix publication; no package installation or activation.

The operator independently approves and stages this helper and install_runtime.py
under root-private storage before invoking protected Python with -I -S -B.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import posixpath
import pwd
import re
import stat
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn

ROOT_UID = 0
ROOT_GID = 0
PUBLISH_ROOT = Path("/opt/eom")
RECEIPT = PUBLISH_ROOT / "kakao-runtime-publication.json"
LOCK = Path("/run/eom-kakao-install/install.lock")
HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
ROLE_NAMES = frozenset({"browser", "remote", "pdf"})


class PublicationError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise PublicationError("KAKAO_PUBLICATION_" + code)


def _signature(info: os.stat_result) -> tuple[int, ...]:
    return tuple(
        getattr(info, field)
        for field in (
            "st_dev",
            "st_ino",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
            "st_mode",
            "st_uid",
        )
    )


def _root_file(path: Path, expected: str) -> bytes:
    """Bootstrap only: verify helper/plan without importing candidate code or site startup."""
    if not HASH.fullmatch(expected) or not path.is_absolute() or ".." in path.parts:
        fail("INPUT_INVALID")
    for directory in reversed(path.parents):
        info = directory.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid not in {0, ROOT_UID}
            or info.st_mode & 0o022
        ):
            fail("PARENT_UNTRUSTED")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != ROOT_UID
            or before.st_mode & 0o6022
            or before.st_nlink != 1
            or before.st_size > 262144
        ):
            fail("INPUT_UNTRUSTED")
        raw = stream.read(262145)
        if _signature(before) != _signature(os.fstat(stream.fileno())):
            fail("INPUT_CHANGED")
    if (
        _signature(before) != _signature(path.lstat())
        or "sha256:" + hashlib.sha256(raw).hexdigest() != expected
    ):
        fail("INPUT_HASH_MISMATCH")
    return raw


def load_installer(path: Path, expected: str) -> ModuleType:
    raw = _root_file(path, expected)
    module = ModuleType("kakao_fixed_installer")
    module.__file__ = str(path)
    sys.modules[module.__name__] = module
    # Execute the checked bytes, not a second read of an operator-supplied path.
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail("DUPLICATE_KEY")
        result[key] = value
    return result


def load_plan(path: Path, expected: str) -> dict[str, Any]:
    value = json.loads(_root_file(path, expected), object_pairs_hook=_pairs)
    if (
        not isinstance(value, dict)
        or set(value)
        != {"schema_version", "install_manifest_sha256", "source_uid", "dependency_lock"}
        or value["schema_version"] != "kakao-runtime-publication/1.0"
        or not isinstance(value["install_manifest_sha256"], str)
        or not HASH.fullmatch(value["install_manifest_sha256"])
        or type(value["source_uid"]) is not int
        or not 0 < value["source_uid"] < 2**31
        or not isinstance(value["dependency_lock"], dict)
        or set(value["dependency_lock"]) != ROLE_NAMES
    ):
        fail("PLAN_INVALID")
    for packages in value["dependency_lock"].values():
        if not isinstance(packages, dict) or not 1 <= len(packages) <= 128:
            fail("LOCK_INVALID")
        for name, version in packages.items():
            if (
                not isinstance(name, str)
                or len(name) > 100
                or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
                or not isinstance(version, str)
                or not 1 <= len(version) <= 100
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+!-]*", version)
            ):
                fail("LOCK_INVALID")
    return value


def targets(installer: ModuleType) -> dict[str, Path]:
    return {**installer.PREFIXES, "playwright": installer.BROWSER, "novnc": installer.NOVNC}


def expected_trees(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        **manifest["runtime_sha256"],
        "playwright": manifest["browser_assets_sha256"],
        "novnc": manifest["novnc_assets_sha256"],
    }


def _check_member(info: os.stat_result, source_uid: int) -> None:
    if info.st_uid not in {0, source_uid} or info.st_mode & 0o6022:
        fail("SOURCE_MEMBER_UNTRUSTED")


def snapshot(source: Path, destination: Path | None, *, source_uid: int) -> str:
    """Bounded no-follow copy/hash. New files never retain source links or ownership."""
    if destination is not None:
        destination.mkdir(mode=0o700)
    fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    rows: list[tuple[str, bytes]] = []
    total = 0

    def walk(directory: int, relative: Path, output: Path | None) -> None:
        nonlocal total
        before = os.fstat(directory)
        _check_member(before, source_uid)
        for name in sorted(os.listdir(directory)):
            if any(ord(c) < 32 or ord(c) == 127 for c in name):
                fail("SOURCE_NAME_INVALID")
            member = relative / name
            label = "./" + member.as_posix()
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            target = output / name if output is not None else None
            if stat.S_ISLNK(info.st_mode):
                if info.st_uid not in {0, source_uid}:
                    fail("SOURCE_MEMBER_UNTRUSTED")
                link = os.readlink(name, dir_fd=directory)
                resolved = posixpath.normpath((relative / link).as_posix())
                if (
                    link.startswith("/")
                    or resolved == ".."
                    or resolved.startswith("../")
                    or any(ord(c) < 32 or ord(c) == 127 for c in link)
                ):
                    fail("SOURCE_LINK_ESCAPE")
                if target is not None:
                    os.symlink(link, target)
                    os.chown(target, ROOT_UID, ROOT_GID, follow_symlinks=False)
                data = f"L\0{label}\0{link}\0".encode()
            elif stat.S_ISDIR(info.st_mode):
                child = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=directory,
                )
                try:
                    if _signature(info) != _signature(os.fstat(child)):
                        fail("SOURCE_CHANGED")
                    if target is not None:
                        target.mkdir(mode=0o700)
                    walk(child, member, target)
                finally:
                    os.close(child)
                data = f"D\0{label}\0".encode()
            elif stat.S_ISREG(info.st_mode):
                _check_member(info, source_uid)
                total += info.st_size
                if total > 8 * 1024**3 or info.st_size > 1024**3:
                    fail("SOURCE_TOO_LARGE")
                member_fd = os.open(
                    name,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                    dir_fd=directory,
                )
                with os.fdopen(member_fd, "rb") as stream:
                    if _signature(info) != _signature(os.fstat(stream.fileno())):
                        fail("SOURCE_CHANGED")
                    out = target.open("xb") if target is not None else None
                    try:
                        digest, size = hashlib.sha256(), 0
                        while chunk := stream.read(1024 * 1024):
                            size += len(chunk)
                            if size > info.st_size:
                                fail("SOURCE_CHANGED")
                            digest.update(chunk)
                            if out is not None:
                                out.write(chunk)
                        if size != info.st_size or _signature(info) != _signature(
                            os.fstat(stream.fileno())
                        ):
                            fail("SOURCE_CHANGED")
                        if out is not None:
                            out.flush()
                            os.fsync(out.fileno())
                            os.fchown(out.fileno(), ROOT_UID, ROOT_GID)
                            os.fchmod(out.fileno(), 0o755 if info.st_mode & 0o111 else 0o644)
                    finally:
                        if out is not None:
                            out.close()
                data = f"F\0{label}\0{digest.hexdigest()}\0".encode()
            else:
                fail("SOURCE_MEMBER_UNTRUSTED")
            if _signature(info) != _signature(
                os.stat(name, dir_fd=directory, follow_symlinks=False)
            ):
                fail("SOURCE_CHANGED")
            rows.append((label, data))
            if len(rows) > 100000:
                fail("SOURCE_TOO_LARGE")
        if _signature(before) != _signature(os.fstat(directory)):
            fail("SOURCE_CHANGED")
        if output is not None:
            os.chown(output, ROOT_UID, ROOT_GID)
            output.chmod(0o755)
            output_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(output_fd)
            finally:
                os.close(output_fd)

    try:
        before = os.fstat(fd)
        if before.st_uid != source_uid:
            fail("SOURCE_OWNER_INVALID")
        walk(fd, Path(), destination)
        if _signature(before) != _signature(source.lstat()):
            fail("SOURCE_CHANGED")
    finally:
        os.close(fd)
    return "sha256:" + hashlib.sha256(b"".join(data for _, data in sorted(rows))).hexdigest()


def prepare(installer: ModuleType, *, source_uid: int, source_gid: int) -> None:
    for target in targets(installer).values():
        for parent in reversed((target, *target.parents)):
            if parent == target:
                continue
            if not os.path.lexists(parent):
                parent.mkdir(mode=0o755)
            installer.protected(parent, directory=True)
        if os.path.lexists(target):
            fail("TARGET_EXISTS")
    for target in targets(installer).values():
        target.mkdir(mode=0o700)
        os.chown(target, source_uid, source_gid)


@contextmanager
def publication_lock(installer: ModuleType) -> Iterator[None]:
    installer.exact_layout(installer.Layout(LOCK.parent, ROOT_UID, ROOT_GID, 0o700), create=True)
    installer.exact_layout(
        installer.Layout(LOCK, ROOT_UID, ROOT_GID, 0o600), create=True, content=b""
    )
    fd = os.open(LOCK, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with installer.existing_runtime_locks():
            installer.require_stopped()
            yield
    finally:
        os.close(fd)


BOOTSTRAP = r"""
import importlib.metadata,json,re,sys
from pathlib import Path
prefix=Path(sys.argv[1])
assert sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode
assert sys.version_info[:3]==(3,12,13)
assert Path(sys.prefix)==prefix and Path(sys.exec_prefix)==prefix
site=prefix/"lib/python3.12/site-packages"
sys.path.append(str(site))
from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version
distributions=list(importlib.metadata.distributions(path=[str(site)]))
observed={}
for distribution in distributions:
    name=canonicalize_name(distribution.metadata["Name"])
    assert name not in observed
    Version(distribution.version)
    observed[name]=distribution.version
environment=default_environment()
lookup={canonicalize_name(d.metadata["Name"]):d for d in distributions}
pending=[(name,"") for name in observed]; checked=set()
for distribution in distributions:
    direct=distribution.read_text("direct_url.json")
    assert direct is None or not json.loads(direct).get("dir_info",{}).get("editable",False)
    python_requirement=distribution.metadata.get("Requires-Python")
    assert python_requirement is None or Version("3.12.13") in SpecifierSet(python_requirement)
while pending:
    source,extra=pending.pop()
    if (source,extra) in checked: continue
    checked.add((source,extra)); environment["extra"]=extra
    distribution=lookup[source]
    for text in distribution.requires or ():
        dependency=Requirement(text)
        assert dependency.url is None
        if dependency.marker is not None and not dependency.marker.evaluate(environment): continue
        name=canonicalize_name(dependency.name)
        assert name in observed and Version(observed[name]) in dependency.specifier
        pending.extend((name,extra) for extra in dependency.extras)
print(json.dumps(observed,sort_keys=True,separators=(",",":")))
"""


def verify(installer: ModuleType, manifest: dict[str, Any], plan: dict[str, Any]) -> None:
    for name, target in targets(installer).items():
        if installer.tree_digest(target) != expected_trees(manifest)[name]:
            fail("TREE_HASH_MISMATCH")
    for name, prefix in installer.PREFIXES.items():
        installer.check_versions(name, prefix)
        executable = prefix / "bin/python3.12"
        if not installer.protected(executable, directory=False).st_mode & 0o111:
            fail("BOOTSTRAP_INVALID")
        raw = installer.run(
            [str(executable), "-I", "-S", "-B", "-c", BOOTSTRAP, str(prefix)], capture=True
        )
        if json.loads(raw, object_pairs_hook=_pairs) != plan["dependency_lock"][name]:
            fail("DEPENDENCY_LOCK_MISMATCH")
    # A supposedly read-only probe must not mutate the installed reviewed bytes.
    for name, target in targets(installer).items():
        if installer.tree_digest(target) != expected_trees(manifest)[name]:
            fail("PROBE_MUTATED_RUNTIME")


def publish(
    installer: ModuleType, manifest: dict[str, Any], plan: dict[str, Any], plan_sha: str
) -> Path | None:
    expected = expected_trees(manifest)
    receipt = {
        "schema_version": "kakao-runtime-publication-receipt/1.0",
        "publication_sha256": plan_sha,
        "install_manifest_sha256": plan["install_manifest_sha256"],
    }
    if os.path.lexists(RECEIPT):
        installer.digest(RECEIPT, maximum=4096)
        if json.loads(RECEIPT.read_bytes(), object_pairs_hook=_pairs) != receipt:
            fail("EXISTING_PUBLICATION_CONFLICT")
        verify(installer, manifest, plan)
        return None
    installer.protected(PUBLISH_ROOT, directory=True)
    device = PUBLISH_ROOT.stat().st_dev
    originals = {}
    for name, target in targets(installer).items():
        installer.protected(target.parent, directory=True)
        info = target.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != plan["source_uid"]:
            fail("INITIAL_ONLY_RECONCILE_REQUIRED")
        if info.st_dev != device or target.parent.stat().st_dev != device:
            fail("CROSS_DEVICE_TARGET")
        originals[name] = info
    quarantine = Path(tempfile.mkdtemp(prefix=".kakao-runtime-publish-", dir=PUBLISH_ROOT))
    phase = quarantine / "phase-receipt"

    def record(value: str) -> None:
        with phase.open("ab") as stream:
            stream.write((value + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())

    record("COPYING")
    for name, target in targets(installer).items():
        if snapshot(target, quarantine / name, source_uid=plan["source_uid"]) != expected[name]:
            fail("TREE_HASH_MISMATCH")
        if installer.tree_digest(quarantine / name) != expected[name]:
            fail("PROTECTED_TREE_MISMATCH")
    record("SNAPSHOTS_VERIFIED")
    for name, target in targets(installer).items():
        installer.protected(target.parent, directory=True)
        current = target.lstat()
        if (current.st_dev, current.st_ino, current.st_uid) != (
            originals[name].st_dev,
            originals[name].st_ino,
            plan["source_uid"],
        ):
            fail("SOURCE_CHANGED")
        target.rename(quarantine / (name + "-builder-backup"))
        (quarantine / name).rename(target)
        parent = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
        record("PUBLISHED_" + name.upper())
    record("STAGED_NOT_ACTIVATED")
    verify(installer, manifest, plan)
    installer.exact_layout(
        installer.Layout(RECEIPT, ROOT_UID, ROOT_GID, 0o600),
        create=True,
        content=json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode(),
    )
    record("VERIFIED_NOT_ACTIVATED")
    return quarantine


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "fingerprint", "publish", "verify"))
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--installer-sha256", required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--install-manifest", type=Path)
    args = parser.parse_args()
    try:
        if os.geteuid() != ROOT_UID or not (
            sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode
        ):
            fail("PROTECTED_OPERATOR_REQUIRED")
        installer = load_installer(args.installer, args.installer_sha256)
        installer.protected(Path(__file__), directory=False)
        installer.protected(Path(sys.executable).resolve(strict=True), directory=False)
        if not Path(sys.prefix).is_relative_to("/opt/eom/conda/envs") or sys.version_info[:3] != (
            3,
            12,
            13,
        ):
            fail("PROTECTED_OPERATOR_REQUIRED")
        builder = pwd.getpwnam("eom")
        if not 0 < builder.pw_uid < 2**31 or builder.pw_gid == 0:
            fail("BUILDER_INVALID")
        with publication_lock(installer):
            if args.action == "prepare":
                prepare(installer, source_uid=builder.pw_uid, source_gid=builder.pw_gid)
            elif args.action == "fingerprint":
                for target in targets(installer).values():
                    installer.protected(target.parent, directory=True)
                print(
                    json.dumps(
                        {
                            name: snapshot(target, None, source_uid=builder.pw_uid)
                            for name, target in targets(installer).items()
                        },
                        sort_keys=True,
                    )
                )
            else:
                if (
                    args.manifest is None
                    or args.manifest_sha256 is None
                    or args.install_manifest is None
                ):
                    fail("INPUT_INVALID")
                plan = load_plan(args.manifest, args.manifest_sha256)
                if plan["source_uid"] != builder.pw_uid:
                    fail("BUILDER_INVALID")
                manifest = installer.load_manifest(
                    args.install_manifest, plan["install_manifest_sha256"]
                )
                if args.action == "publish":
                    quarantine = publish(installer, manifest, plan, args.manifest_sha256)
                    if quarantine is not None:
                        print("RETAINED_QUARANTINE=" + str(quarantine))
                else:
                    verify(installer, manifest, plan)
        print("KAKAO_PUBLICATION_" + args.action.upper() + "_PASS_NOT_ACTIVATED")
        return 0
    except Exception as error:
        print(
            str(error) if isinstance(error, PublicationError) else "KAKAO_PUBLICATION_REJECTED",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
