"""Mechanical fixed-prefix installation checks; stdlib only, no model or pip execution.

Executed only by the independently fingerprinted root-owned fixed Conda interpreter.
The root shell bootstraps that interpreter without executing the developer prefix.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import pwd
import re
import stat
import sys
import zipfile
from pathlib import Path

PREFIX = Path("/opt/eom/conda/envs/eom-embedding-experiment")
MODEL_STORE = Path("/opt/eom/embedding-models")
MODEL_ID = "embeddingmodel_f30c692a99476867e96f3567ae266036"
MODEL_REVISION = "embeddingmodelrev_82eace0bd4ceeacb31ced2e8e40bc293"
MODEL_MANIFEST = "sha256:f106f8df1ca01062a3900fa65f4c235d278294c34a113efe1cc1934432d0d9eb"
MODEL_MEMBERS: dict[str, tuple[int, str]] = {
    "manifest.json": (1812, "0f0c2c7c1a3b525cc41163e417ce632adb5bbd60327e007e15ccd09a03a8ad8e"),
    "1_Pooling/config.json": (
        200,
        "987f7a67a38fa564c849bb5d277c52ab9088a84368fc0be31a354125aebb12a0",
    ),
    "config.json": (655, "69137736cab8b8903a07fe8afaafdda25aac55415a12a55d1bffa9f581abf959"),
    "model.safetensors": (
        470641600,
        "1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477",
    ),
    "sentencepiece.bpe.model": (
        5069051,
        "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865",
    ),
    "special_tokens_map.json": (
        167,
        "d05497f1da52c5e09554c0cd874037a083e1dc1b9cfd48034d1c717f1afc07a7",
    ),
    "tokenizer.json": (
        17082730,
        "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
    ),
    "tokenizer_config.json": (
        443,
        "a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b",
    ),
}


class SnapshotInstallError(ValueError):
    pass


def _epoch(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _ancestor_identity(value: os.stat_result) -> tuple[int, ...]:
    # Shared ancestors such as /tmp may legitimately change unrelated directory entries.
    # Their inode/name/ownership/mode must remain fixed; selected source roots retain full epochs.
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid)


def _relative(value: str) -> Path:
    path = Path(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or any(ord(char) < 32 for char in value)
    ):
        raise SnapshotInstallError("EMBEDDING_SNAPSHOT_PATH_INVALID")
    return path


def require_root_path(path: Path, *, directory: bool = True) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise SnapshotInstallError("EMBEDDING_SNAPSHOT_PATH_INVALID")
    for component in (path, *path.parents):
        value = component.lstat()
        if stat.S_ISLNK(value.st_mode) or value.st_uid != 0 or value.st_mode & 0o022:
            raise SnapshotInstallError("EMBEDDING_SNAPSHOT_PATH_INVALID")
    value = path.lstat()
    if directory != stat.S_ISDIR(value.st_mode):
        raise SnapshotInstallError("EMBEDDING_SNAPSHOT_PATH_INVALID")


def _hash(path: Path) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise SnapshotInstallError("EMBEDDING_SNAPSHOT_FILE_INVALID")
        digest = hashlib.sha256()
        count = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            count += len(chunk)
            digest.update(chunk)
        if (
            count != before.st_size
            or _epoch(before) != _epoch(os.fstat(descriptor))
            or _epoch(before) != _epoch(path.lstat())
        ):
            raise SnapshotInstallError("EMBEDDING_SNAPSHOT_FILE_CHANGED")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def validate_runtime_tree(root: Path) -> None:
    """Independent full-tree hash precedes this check; reject execution-path escape."""
    require_root_path(root)
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in (*directories, *files):
            path = Path(parent) / name
            value = path.lstat()
            if value.st_uid != 0 or (not stat.S_ISLNK(value.st_mode) and value.st_mode & 0o6022):
                raise SnapshotInstallError("EMBEDDING_RUNTIME_OWNERSHIP_INVALID")
            if stat.S_ISLNK(value.st_mode):
                if not path.resolve(strict=True).is_relative_to(root):
                    raise SnapshotInstallError("EMBEDDING_RUNTIME_LINK_ESCAPE")
            elif not stat.S_ISDIR(value.st_mode) and not (
                stat.S_ISREG(value.st_mode) and value.st_nlink == 1
            ):
                raise SnapshotInstallError("EMBEDDING_RUNTIME_MEMBER_INVALID")
    site = root / "lib/python3.12/site-packages"
    for path in site.glob("*.pth"):
        # A reviewed, static setuptools shim is the one existing Conda exception.
        if path.name != "distutils-precedence.pth" or path.read_bytes() != (
            b"import os; var = 'SETUPTOOLS_USE_DISTUTILS'; "
            b"enabled = os.environ.get(var, 'local') == 'local'; "
            b"enabled and __import__('_distutils_hack').add_shim(); \n"
        ):
            raise SnapshotInstallError("EMBEDDING_RUNTIME_PTH_FORBIDDEN")
    if any((site / name).exists() for name in ("sitecustomize.py", "usercustomize.py")):
        raise SnapshotInstallError("EMBEDDING_RUNTIME_SITE_CUSTOMIZATION_FORBIDDEN")
    for path in site.glob("*.dist-info/direct_url.json"):
        value = json.loads(path.read_bytes())
        if value.get("dir_info", {}).get("editable") or "file:///home/eom/EOM" in value.get(
            "url", ""
        ):
            raise SnapshotInstallError("EMBEDDING_RUNTIME_EDITABLE_FORBIDDEN")


def verify_platform_wheel(root: Path, wheel: Path, expected_sha256: str) -> None:
    """Bind installed platform payload to an independently reviewed wheel, not its RECORD alone."""
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None or _hash(wheel) != expected_sha256:
        raise SnapshotInstallError("EMBEDDING_PLATFORM_WHEEL_HASH_MISMATCH")
    site = root / "lib/python3.12/site-packages"
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names) or len(names) > 10000:
            raise SnapshotInstallError("EMBEDDING_PLATFORM_WHEEL_INVALID")
        metadata = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata) != 1 or not metadata[0].startswith("eom_platform-"):
            raise SnapshotInstallError("EMBEDDING_PLATFORM_WHEEL_INVALID")
        for member in archive.infolist():
            relative = _relative(member.filename)
            if member.is_dir():
                continue
            if ".data" in relative.parts or member.file_size > 64 * 1024**2:
                raise SnapshotInstallError("EMBEDDING_PLATFORM_WHEEL_INVALID")
            if member.filename.endswith(".dist-info/RECORD"):
                continue
            target = site / relative
            if _hash(target) != hashlib.sha256(archive.read(member)).hexdigest():
                raise SnapshotInstallError("EMBEDDING_PLATFORM_INSTALLED_HASH_MISMATCH")
        record = site / metadata[0].rsplit("/", 1)[0] / "RECORD"
        for row in csv.reader(io.StringIO(record.read_text(encoding="utf-8"))):
            if len(row) != 3:
                raise SnapshotInstallError("EMBEDDING_PLATFORM_RECORD_INVALID")
            target = (site / row[0]).resolve(strict=True)
            if not target.is_relative_to(root):
                raise SnapshotInstallError("EMBEDDING_PLATFORM_RECORD_INVALID")
            if row[1]:
                if not row[1].startswith("sha256="):
                    raise SnapshotInstallError("EMBEDDING_PLATFORM_RECORD_INVALID")
                actual = base64.urlsafe_b64encode(bytes.fromhex(_hash(target))).decode().rstrip("=")
                if row[1] != "sha256=" + actual or row[2] != str(target.stat().st_size):
                    raise SnapshotInstallError("EMBEDDING_PLATFORM_RECORD_INVALID")
            elif not (row[0].endswith("/RECORD") or row[0].endswith(".pyc")):
                raise SnapshotInstallError("EMBEDDING_PLATFORM_RECORD_INVALID")


def _open_source_directory(path: Path) -> list[tuple[int, Path, tuple[int, ...]]]:
    if not path.is_absolute() or ".." in path.parts:
        raise SnapshotInstallError("EMBEDDING_MODEL_SOURCE_INVALID")
    handles: list[tuple[int, Path, tuple[int, ...]]] = []
    try:
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        handles.append((descriptor, Path("/"), _epoch(os.fstat(descriptor))))
        for name in path.parts[1:]:
            named = handles[-1][1] / name
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=handles[-1][0],
            )
            handles.append((descriptor, named, _epoch(os.fstat(descriptor))))
        return handles
    except Exception:
        for descriptor, _path, _initial in reversed(handles):
            os.close(descriptor)
        raise


def copy_reviewed_model(source: Path, target: Path, *, source_uid: int, cpu_gid: int) -> None:
    """Strict source FD copy to root-only target, using independent fixed upstream pins."""
    if source.name != MODEL_REVISION or source.parent.name != MODEL_ID:
        raise SnapshotInstallError("EMBEDDING_MODEL_SOURCE_INVALID")
    require_root_path(target.parent)
    if target.exists() or target.is_symlink():
        raise SnapshotInstallError("EMBEDDING_MODEL_TARGET_EXISTS")
    handles = _open_source_directory(source)
    try:
        source_fd = handles[-1][0]
        for descriptor, _name, _initial in handles[-3:]:
            value = os.fstat(descriptor)
            if value.st_uid != source_uid or stat.S_IMODE(value.st_mode) != 0o700:
                raise SnapshotInstallError("EMBEDDING_MODEL_SOURCE_INVALID")
        if set(os.listdir(source_fd)) != {
            "1_Pooling",
            *(name for name in MODEL_MEMBERS if "/" not in name),
        }:
            raise SnapshotInstallError("EMBEDDING_MODEL_MEMBERS_INVALID")
        target.mkdir(mode=0o700)
        (target / "1_Pooling").mkdir(mode=0o700)
        for member, (size, expected) in MODEL_MEMBERS.items():
            parent_fd = source_fd
            sub_fd = None
            if "/" in member:
                sub_fd = os.open(
                    "1_Pooling",
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=source_fd,
                )
                sub_info = os.fstat(sub_fd)
                if (
                    sub_info.st_uid != source_uid
                    or stat.S_IMODE(sub_info.st_mode) != 0o700
                    or set(os.listdir(sub_fd)) != {"config.json"}
                ):
                    raise SnapshotInstallError("EMBEDDING_MODEL_MEMBERS_INVALID")
                parent_fd = sub_fd
            descriptor = os.open(
                member.rsplit("/", 1)[-1],
                os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent_fd,
            )
            output = os.open(
                target / member, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600
            )
            try:
                before = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_uid != source_uid
                    or before.st_nlink != 1
                    or before.st_mode & 0o022
                    or before.st_size != size
                ):
                    raise SnapshotInstallError("EMBEDDING_MODEL_SOURCE_INVALID")
                digest = hashlib.sha256()
                count = 0
                while chunk := os.read(descriptor, 1024 * 1024):
                    count += len(chunk)
                    if count > size:
                        raise SnapshotInstallError("EMBEDDING_MODEL_SOURCE_CHANGED")
                    digest.update(chunk)
                    view = memoryview(chunk)
                    while view:
                        written = os.write(output, view)
                        if written <= 0:
                            raise SnapshotInstallError("EMBEDDING_MODEL_OUTPUT_WRITE_FAILED")
                        view = view[written:]
                named = os.stat(member.rsplit("/", 1)[-1], dir_fd=parent_fd, follow_symlinks=False)
                if (
                    count != size
                    or digest.hexdigest() != expected
                    or _epoch(before) != _epoch(os.fstat(descriptor))
                    or _epoch(before) != _epoch(named)
                ):
                    raise SnapshotInstallError("EMBEDDING_MODEL_HASH_MISMATCH")
                os.fsync(output)
            finally:
                os.close(output)
                os.close(descriptor)
                if sub_fd is not None:
                    os.close(sub_fd)
        for index, (descriptor, ancestor_path, ancestor_before) in enumerate(handles):
            observed_fd, observed_name = os.fstat(descriptor), ancestor_path.lstat()
            if index < len(handles) - 3:
                unchanged = (
                    _ancestor_identity(observed_fd)
                    == _ancestor_identity(observed_name)
                    == ancestor_before[:5]
                )
            else:
                unchanged = _epoch(observed_fd) == _epoch(observed_name) == ancestor_before
            if not unchanged:
                raise SnapshotInstallError("EMBEDDING_MODEL_SOURCE_CHANGED")
        # Exposure occurs only after all independently pinned files were copied and verified.
        for parent, _directories, files in os.walk(target):
            os.chown(parent, 0, cpu_gid)
            os.chmod(parent, 0o750)
            for file_name in files:
                os.chown(Path(parent) / file_name, 0, cpu_gid)
                os.chmod(Path(parent) / file_name, 0o440)
    finally:
        for descriptor, _path, _initial in reversed(handles):
            os.close(descriptor)


def ensure_owner_workspace() -> None:
    """Create only the fixed child using retained FDs; never follow an owner-controlled link."""
    parent = Path("/var/lib/eom-workflow-runner")
    child = "inference-transfer-experiments"
    identity = pwd.getpwnam("eom-workflow-runner")
    require_root_path(parent.parent)
    descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    child_fd: int | None = None
    try:
        before = os.fstat(descriptor)
        if (
            before.st_uid != identity.pw_uid
            or before.st_gid != identity.pw_gid
            or stat.S_IMODE(before.st_mode) != 0o700
        ):
            raise SnapshotInstallError("EMBEDDING_OWNER_PARENT_INVALID")
        try:
            os.mkdir(child, mode=0o700, dir_fd=descriptor)
            created = True
        except FileExistsError:
            created = False
        child_fd = os.open(
            child, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=descriptor
        )
        if created:
            os.fchown(child_fd, identity.pw_uid, identity.pw_gid)
            os.fchmod(child_fd, 0o700)
        value = os.fstat(child_fd)
        named = os.stat(child, dir_fd=descriptor, follow_symlinks=False)
        if (
            value.st_uid != identity.pw_uid
            or value.st_gid != identity.pw_gid
            or stat.S_IMODE(value.st_mode) != 0o700
            or _ancestor_identity(value) != _ancestor_identity(named)
            or _ancestor_identity(before) != _ancestor_identity(os.fstat(descriptor))
            or _ancestor_identity(before) != _ancestor_identity(parent.lstat())
        ):
            raise SnapshotInstallError("EMBEDDING_OWNER_WORKSPACE_INVALID")
    finally:
        if child_fd is not None:
            os.close(child_fd)
        os.close(descriptor)


def _prepare_model_parent(cpu_gid: int) -> Path:
    require_root_path(MODEL_STORE)
    parent = MODEL_STORE / MODEL_ID
    try:
        parent.mkdir(mode=0o750)
    except FileExistsError:
        pass
    else:
        os.chown(parent, 0, cpu_gid)
        # The root installer uses umask 077: mkdir(0750) alone becomes 0700 and prevents the
        # dedicated CPU group traversing the otherwise correctly exposed immutable revision.
        os.chmod(parent, 0o750)
    value = parent.lstat()
    if (
        not stat.S_ISDIR(value.st_mode)
        or value.st_uid != 0
        or value.st_gid != cpu_gid
        or stat.S_IMODE(value.st_mode) != 0o750
    ):
        raise SnapshotInstallError("EMBEDDING_MODEL_PARENT_INVALID")
    return parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--wheel-sha256", required=True)
    parser.add_argument("--model-source", type=Path, required=True)
    parser.add_argument("--source-uid", type=int, required=True)
    parser.add_argument("--cpu-gid", type=int, required=True)
    args = parser.parse_args()
    try:
        if os.geteuid() != 0 or args.runtime != PREFIX:
            raise SnapshotInstallError("EMBEDDING_INSTALL_CONTEXT_INVALID")
        validate_runtime_tree(args.runtime)
        verify_platform_wheel(args.runtime, args.wheel, args.wheel_sha256)
        model_parent = _prepare_model_parent(args.cpu_gid)
        copy_reviewed_model(
            args.model_source,
            model_parent / MODEL_REVISION,
            source_uid=args.source_uid,
            cpu_gid=args.cpu_gid,
        )
        ensure_owner_workspace()
        return 0
    except Exception:
        print("EMBEDDING_RUNTIME_PUBLICATION_REJECTED", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
