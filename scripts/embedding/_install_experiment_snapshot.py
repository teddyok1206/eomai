"""Mechanical fixed-prefix installation checks; stdlib only, no model or pip execution.

Executed only by the independently fingerprinted root-owned fixed Conda interpreter.
The root shell bootstraps that interpreter without executing the developer prefix.
"""

from __future__ import annotations

import argparse
import base64
import csv
import grp
import hashlib
import io
import json
import os
import pwd
import re
import stat
import sys
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path
from typing import Final
from urllib.parse import unquote

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

# SFconvertbot's unmerged PR #130 is a reviewed experiment candidate, not a
# maintainer release. Root admission uses these independent pins, never the
# runtime versions or file inventory declared by an untrusted source manifest.
BGE_REPOSITORY: Final = "BAAI/bge-m3"
BGE_UPSTREAM_REVISION = "9a0624b896d81da7492a910ffa53731274b6cf3d"
BGE_RUNTIME_VERSIONS = (
    ("safetensors", "0.6.2"),
    ("tokenizers", "0.22.2"),
    ("torch", "2.7.1+cpu"),
    ("transformers", "4.56.2"),
)
BGE_FILES = (
    (
        "1_Pooling/config.json",
        191,
        "e54c164a07274f2eb45bb724f54a79d1efcc90c41573887cd9a29aeee0597352",
    ),
    ("config.json", 687, "26159e7ad065073448460117eb24b7a4572f6f4e78eadff65dc0a11c052449fa"),
    (
        "model.safetensors",
        2271064456,
        "993b2248881724788dcab8c644a91dfd63584b6e5604ff2037cb5541e1e38e7e",
    ),
    (
        "sentencepiece.bpe.model",
        5069051,
        "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865",
    ),
    (
        "special_tokens_map.json",
        964,
        "8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835",
    ),
    (
        "tokenizer.json",
        17098108,
        "21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08",
    ),
    (
        "tokenizer_config.json",
        444,
        "a62b2b6784f990259fddef5f16388693a8043be4f69179e6a5257eeb3f9abac4",
    ),
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _content_sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def reviewed_bge_model_spec() -> dict[str, object]:
    """The existing model-spec/1.0 recipe, reproducible without third-party imports."""
    recipe = {
        "schema_version": "item-local-embedding-model-spec/1.0",
        "provider_family": "transformers-local-dense/1.0",
        "upstream_repo": BGE_REPOSITORY,
        "upstream_revision": BGE_UPSTREAM_REVISION,
        "license_id": "MIT",
        "dimension": 1024,
        "maximum_tokens": 2048,
        "pooling": "CLS",
        "normalization": "L2",
        "dtype": "float32",
        "query_prefix": "",
        "document_prefix": "",
        "truncation": "REJECT_OVERFLOW",
        "files": [
            {"member_path": name, "size_bytes": size, "sha256": "sha256:" + digest}
            for name, size, digest in BGE_FILES
        ],
        "runtime_versions": [
            {"name": name, "version": version} for name, version in BGE_RUNTIME_VERSIONS
        ],
    }
    body = {
        **recipe,
        "model_id": "embeddingmodel_" + _content_sha256(BGE_REPOSITORY)[7:39],
        "model_revision_id": "embeddingmodelrev_" + _content_sha256(recipe)[7:39],
    }
    return {**body, "manifest_sha256": _content_sha256(body)}


BGE_SPEC = reviewed_bge_model_spec()
BGE_MODEL_ID = str(BGE_SPEC["model_id"])
BGE_MODEL_REVISION = str(BGE_SPEC["model_revision_id"])
BGE_MANIFEST_BYTES = _canonical(BGE_SPEC)
BGE_MANIFEST_RAW_SHA256 = hashlib.sha256(BGE_MANIFEST_BYTES).hexdigest()
BGE_MEMBERS: dict[str, tuple[int, str]] = {
    "manifest.json": (len(BGE_MANIFEST_BYTES), BGE_MANIFEST_RAW_SHA256),
    **{name: (size, digest) for name, size, digest in BGE_FILES},
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
    """Preserve the existing E5 full-installation entry and independently reviewed pins."""
    copy_reviewed_model_snapshot(
        source,
        target,
        model_id=MODEL_ID,
        model_revision=MODEL_REVISION,
        members=MODEL_MEMBERS,
        source_uid=source_uid,
        cpu_gid=cpu_gid,
    )


def copy_reviewed_model_snapshot(
    source: Path,
    target: Path,
    *,
    model_id: str,
    model_revision: str,
    members: dict[str, tuple[int, str]],
    source_uid: int,
    cpu_gid: int,
) -> None:
    """Strict source FD copy to root-only target, using independent fixed upstream pins."""
    allowed_members = {
        "manifest.json",
        "1_Pooling/config.json",
        "config.json",
        "model.safetensors",
        "sentencepiece.bpe.model",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
    }
    if (
        re.fullmatch(r"embeddingmodel_[0-9a-f]{32}", model_id) is None
        or re.fullmatch(r"embeddingmodelrev_[0-9a-f]{32}", model_revision) is None
        or not {"manifest.json", "1_Pooling/config.json"} <= members.keys() <= allowed_members
        or any(
            isinstance(size, bool)
            or not 0 < size <= 4 * 1024**3
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            for size, digest in members.values()
        )
        or source.name != model_revision
        or source.parent.name != model_id
        or target.name != model_revision
    ):
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
            *(name for name in members if "/" not in name),
        }:
            raise SnapshotInstallError("EMBEDDING_MODEL_MEMBERS_INVALID")
        target.mkdir(mode=0o700)
        (target / "1_Pooling").mkdir(mode=0o700)
        for member, (size, expected) in members.items():
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


def prepare_model_snapshot_parent(model_id: str, cpu_gid: int) -> Path:
    if re.fullmatch(r"embeddingmodel_[0-9a-f]{32}", model_id) is None:
        raise SnapshotInstallError("EMBEDDING_MODEL_PARENT_INVALID")
    require_root_path(MODEL_STORE)
    parent = MODEL_STORE / model_id
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


def _prepare_model_parent(cpu_gid: int) -> Path:
    return prepare_model_snapshot_parent(MODEL_ID, cpu_gid)


def model_only_main() -> int:
    """Add the one reviewed BGE snapshot; never reinstall runtime or reset CPU history."""
    parser = argparse.ArgumentParser(description="No-clobber reviewed BGE model-only admission")
    parser.add_argument("--model-source", type=Path, required=True)
    parser.add_argument("--manifest-raw-sha256", required=True)
    args = parser.parse_args()
    try:
        executable = Path(sys.executable)
        if (
            os.geteuid() != 0
            or not sys.flags.isolated
            or not sys.flags.no_site
            or executable not in (PREFIX / "bin/python", PREFIX / "bin/python3.12")
            or not executable.resolve(strict=True).is_relative_to(PREFIX)
            or args.manifest_raw_sha256 != BGE_MANIFEST_RAW_SHA256
        ):
            raise SnapshotInstallError("EMBEDDING_INSTALL_CONTEXT_INVALID")
        # The caller separately verifies this root-private helper SHA. These
        # checks never execute an interpreter, site package, post-link or model.
        require_root_path(executable.resolve(strict=True), directory=False)
        require_root_path(Path(__file__).resolve(strict=True), directory=False)
        cpu_gid = grp.getgrnam("eom-embedding-experiment").gr_gid
        source_uid = pwd.getpwnam("eom").pw_uid
        require_root_path(MODEL_STORE)
        store = MODEL_STORE.lstat()
        if store.st_gid != cpu_gid or stat.S_IMODE(store.st_mode) != 0o750:
            raise SnapshotInstallError("EMBEDDING_MODEL_PARENT_INVALID")
        model_parent = prepare_model_snapshot_parent(BGE_MODEL_ID, cpu_gid)
        copy_reviewed_model_snapshot(
            args.model_source,
            model_parent / BGE_MODEL_REVISION,
            model_id=BGE_MODEL_ID,
            model_revision=BGE_MODEL_REVISION,
            members=BGE_MEMBERS,
            source_uid=source_uid,
            cpu_gid=cpu_gid,
        )
        print("EMBEDDING_MODEL_ONLY_ADMISSION=PASS")
        print("RUNTIME_AND_HISTORY=UNCHANGED")
        return 0
    except Exception:
        print("EMBEDDING_MODEL_ONLY_ADMISSION_REJECTED", file=sys.stderr)
        return 1


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


_INDEX_PREFIXES: Final = {
    "CPU_INDEX_FP32": Path("/opt/eom/conda/envs/eom-embedding-index-cpu"),
    "CUDA_INDEX_FP32": Path("/opt/eom/conda/envs/eom-embedding-cuda"),
}
_INDEX_LOCK_SHA: Final = {
    "eom-embedding-protected-runtime.requirements.proposal.lock": (
        "974df998a3267b28fa4eadf54d69e7e14379e0b9e84683ab3bbca92d21cd5b04"
    ),
    "eom-embedding-index-cpu.requirements.proposal.lock": (
        "03b70b785820cdf61889690da2c82f8fb4a4560e5ea8034c4b647d55088ac71b"
    ),
    "eom-embedding-cuda.requirements.proposal.lock": (
        "1adaf2109971b4ed1eb23d7c5400a76ea59a06c2a9d059ba54a493ec33b52784"
    ),
    "common-numeric-runtime-wheels.lock": (
        "e2278a6253cd092c340091d08e5d20283e3a1e5052316c010c4c3cd12440513d"
    ),
    "cuda-runtime-wheels.lock": "1c1bf705f0a0af11f30ee669b870a60a786d3faa344b62fe2bc2095d1fd464ba",
}
_INDEX_ARCHIVE_ROOT = Path("/opt/eom/embedding-runtime-archives")
_INDEX_UID = 0
_INDEX_GID = 0
_INDEX_PUBLIC_BYTES: Final = {"CPU_INDEX_FP32": 266514328, "CUDA_INDEX_FP32": 3929095329}
_INDEX_PRIVATE_SOURCES: Final = {
    "eom-platform": (
        (
            "packages/catalog_contracts/eom_catalog_contracts/embedding_runtime_bundle.py",
            "eom_catalog_contracts/embedding_runtime_bundle.py",
        ),
        (
            "packages/catalog_contracts/eom_catalog_contracts/embedding_installed_runtime_proof.py",
            "eom_catalog_contracts/embedding_installed_runtime_proof.py",
        ),
        (
            "services/catalog_service/eom_catalog_service/embedding_native_stdio.py",
            "eom_catalog_service/embedding_native_stdio.py",
        ),
        (
            "services/catalog_service/eom_catalog_service/embedding_offline_backend.py",
            "eom_catalog_service/embedding_offline_backend.py",
        ),
        (
            "services/catalog_service/eom_catalog_service/embedding_installed_runtime_observer.py",
            "eom_catalog_service/embedding_installed_runtime_observer.py",
        ),
        (
            "services/catalog_service/eom_catalog_service/embedding_runtime_distribution.py",
            "eom_catalog_service/embedding_runtime_distribution.py",
        ),
        (
            "services/catalog_service/eom_catalog_service/embedding_registry_catalog_adapter.py",
            "eom_catalog_service/embedding_registry_catalog_adapter.py",
        ),
        (
            "packages/workflow/eom_workflow/local_embedding_request.py",
            "eom_workflow/local_embedding_request.py",
        ),
    ),
    "eom-gpu-lease": (
        ("packages/gpu_lease/eom_gpu_lease/__init__.py", "eom_gpu_lease/__init__.py"),
        ("packages/gpu_lease/eom_gpu_lease/lease.py", "eom_gpu_lease/lease.py"),
    ),
}


def index_runtime_locks(directory: Path, profile: str) -> dict[str, tuple[str, str, str]]:
    """Fixed reviewed include graph, not a resolver or arbitrary requirements reader."""
    if profile not in _INDEX_PREFIXES:
        raise SnapshotInstallError("EMBEDDING_INDEX_PROFILE_INVALID")
    documents = {}
    for name, digest in _INDEX_LOCK_SHA.items():
        target = directory / name
        require_root_path(target, directory=False)
        if target.stat().st_size > 128 * 1024 or _hash(target) != digest:
            raise SnapshotInstallError("EMBEDDING_INDEX_LOCK_HASH_MISMATCH")
        documents[name] = target.read_text(encoding="utf-8")
    parsed: dict[str, dict[str, tuple[str, str, str]]] = {}

    def parse(name: str) -> dict[str, tuple[str, str, str]]:
        if name in parsed:
            return parsed[name]
        rows: dict[str, tuple[str, str, str]] = {}
        for line in documents[name].splitlines():
            if not line or line.startswith("#"):
                continue
            if line.startswith("-r "):
                include = line[3:]
                allowed = {
                    "eom-embedding-protected-runtime.requirements.proposal.lock",
                    "../../scripts/embedding/common-numeric-runtime-wheels.lock",
                    "../../scripts/embedding/cuda-runtime-wheels.lock",
                }
                if include not in allowed:
                    raise SnapshotInstallError("EMBEDDING_INDEX_LOCK_INCLUDE_INVALID")
                incoming = parse(Path(include).name)
            else:
                match = re.fullmatch(
                    r"([a-z0-9-]+) @ (https://[^ ]+) --hash=sha256:([0-9a-f]{64})", line
                )
                if match is None:
                    raise SnapshotInstallError("EMBEDDING_INDEX_LOCK_INVALID")
                package, url, sha = match.groups()
                filename = unquote(url.rsplit("/", 1)[-1])
                parts = filename[:-4].split("-")
                if (
                    not filename.endswith(".whl")
                    or len(parts) != 5
                    or parts[0].replace("_", "-") != package
                ):
                    raise SnapshotInstallError("EMBEDDING_INDEX_WHEEL_IDENTITY_INVALID")
                incoming = {package: (parts[1], filename, sha)}
            for package, identity in incoming.items():
                if package in rows and rows[package] != identity:
                    raise SnapshotInstallError("EMBEDDING_INDEX_LOCK_CONFLICT")
                rows[package] = identity
        parsed[name] = rows
        return rows

    shared = parse("eom-embedding-protected-runtime.requirements.proposal.lock")
    selected = parse(
        "eom-embedding-index-cpu.requirements.proposal.lock"
        if profile == "CPU_INDEX_FP32"
        else "eom-embedding-cuda.requirements.proposal.lock"
    )
    if len(shared) != 54 or len(selected) != (55 if profile == "CPU_INDEX_FP32" else 70):
        raise SnapshotInstallError("EMBEDDING_INDEX_LOCK_CLOSURE_INVALID")
    return selected


def _index_close(descriptors: tuple[int, ...]) -> None:
    failure: OSError | None = None
    for descriptor in descriptors:
        try:
            os.close(descriptor)
        except OSError as error:
            if failure is None:
                failure = error
    if failure is not None:
        raise failure


def _index_source(path: Path) -> tuple[list[tuple[int, Path, tuple[int, ...]]], int]:
    if len(path.parts) < 4 or path.parts[1] != "tmp" or not path.parts[2].startswith("eom-"):
        raise SnapshotInstallError("EMBEDDING_INDEX_SOURCE_PATH_INVALID")
    handles = _open_source_directory(path.parent)
    opened: int | None = None
    try:
        private = handles[2][2]
        uid = private[3]
        if uid not in {_INDEX_UID, pwd.getpwnam("eom").pw_uid} or stat.S_IMODE(private[2]) != 0o700:
            raise SnapshotInstallError("EMBEDDING_INDEX_SOURCE_PATH_INVALID")
        for _fd, _name, epoch in handles[2:]:
            if epoch[3] != uid or epoch[2] & 0o022:
                raise SnapshotInstallError("EMBEDDING_INDEX_SOURCE_PATH_INVALID")
        opened = os.open(
            path.name,
            os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=handles[-1][0],
        )
        value = os.fstat(opened)
        if (
            not stat.S_ISREG(value.st_mode)
            or value.st_uid != uid
            or value.st_nlink != 1
            or value.st_mode & 0o6002
        ):
            raise SnapshotInstallError("EMBEDDING_INDEX_SOURCE_FILE_INVALID")
        return handles, opened
    except Exception:
        _index_close(
            (() if opened is None else (opened,)) + tuple(fd for fd, _, _ in reversed(handles))
        )
        raise


def retain_index_archive(source: Path, sha: str, basename: str, *, maximum: int) -> Path:
    """One streaming raw-byte materialization; interrupted reservations stay private evidence."""
    if (
        re.fullmatch(r"[0-9a-f]{64}", sha) is None
        or _relative(basename).as_posix() != basename
        or "/" in basename
    ):
        raise SnapshotInstallError("EMBEDDING_INDEX_ARCHIVE_IDENTITY_INVALID")
    require_root_path(_INDEX_ARCHIVE_ROOT)
    directory = _INDEX_ARCHIVE_ROOT / sha
    target = directory / basename
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        require_root_path(directory)
        if stat.S_IMODE(directory.stat().st_mode) != 0o755 or set(os.listdir(directory)) != {
            basename
        }:
            raise SnapshotInstallError("EMBEDDING_INDEX_ARCHIVE_INCOMPLETE") from None
        require_root_path(target, directory=False)
        if (
            stat.S_IMODE(target.stat().st_mode) != 0o644
            or target.stat().st_size > maximum
            or _hash(target) != sha
        ):
            raise SnapshotInstallError("EMBEDDING_INDEX_ARCHIVE_HASH_MISMATCH") from None
        return target
    handles, descriptor = _index_source(source)
    output: int | None = None
    try:
        before = os.fstat(descriptor)
        if not 0 < before.st_size <= maximum:
            raise SnapshotInstallError("EMBEDDING_INDEX_ARCHIVE_SIZE_INVALID")
        output = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
        )
        digest, count = hashlib.sha256(), 0
        while chunk := os.read(descriptor, 1024 * 1024):
            count += len(chunk)
            if count > before.st_size:
                raise SnapshotInstallError("EMBEDDING_INDEX_SOURCE_CHANGED")
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(output, view)
                if written <= 0:
                    raise SnapshotInstallError("EMBEDDING_INDEX_ARCHIVE_WRITE_FAILED")
                view = view[written:]
        if (
            count != before.st_size
            or digest.hexdigest() != sha
            or _epoch(before) != _epoch(os.fstat(descriptor))
            or _epoch(before)
            != _epoch(os.stat(source.name, dir_fd=handles[-1][0], follow_symlinks=False))
        ):
            raise SnapshotInstallError("EMBEDDING_INDEX_ARCHIVE_HASH_MISMATCH")
        for fd, named, initial in handles:
            if (
                _ancestor_identity(os.fstat(fd)) != initial[:5]
                or _ancestor_identity(named.lstat()) != initial[:5]
            ):
                raise SnapshotInstallError("EMBEDDING_INDEX_SOURCE_CHANGED")
        os.fsync(output)
        os.fchown(output, _INDEX_UID, _INDEX_GID)
        os.fchmod(output, 0o644)
        os.chown(directory, _INDEX_UID, _INDEX_GID)
        os.chmod(directory, 0o755)
        return target
    finally:
        _index_close(
            (() if output is None else (output,))
            + (descriptor,)
            + tuple(fd for fd, _, _ in reversed(handles))
        )


def _index_private_zip32(wheel: Path) -> None:
    """Bound actual ZIP metadata before ZipFile allocates its untrusted member inventory."""
    descriptor = os.open(wheel, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        invalid = "EMBEDDING_INDEX_PRIVATE_WHEEL_INVALID"
        if not stat.S_ISREG(before.st_mode) or not 22 <= before.st_size <= 64 * 1024**2:
            raise SnapshotInstallError(invalid)
        stream.seek(-22, os.SEEK_END)
        end = stream.read(22)

        def integer(raw: bytes, start: int, size: int) -> int:
            return int.from_bytes(raw[start : start + size], "little")

        count, central_size, central_start = (
            integer(end, 10, 2),
            integer(end, 12, 4),
            integer(end, 16, 4),
        )
        if (
            end[:4] != b"PK\x05\x06"
            or integer(end, 4, 2) != 0
            or integer(end, 6, 2) != 0
            or integer(end, 8, 2) != count
            or not 1 <= count <= 10000
            or not 46 <= central_size <= 8 * 1024**2
            or central_start == 0xFFFFFFFF
            or integer(end, 20, 2) != 0
            or central_start + central_size != before.st_size - 22
        ):
            raise SnapshotInstallError(invalid)

        def extras(raw: bytes) -> None:
            offset = 0
            while offset < len(raw):
                if offset + 4 > len(raw):
                    raise SnapshotInstallError(invalid)
                kind, size = integer(raw, offset, 2), integer(raw, offset + 2, 2)
                offset += 4 + size
                if kind == 1 or offset > len(raw):
                    raise SnapshotInstallError(invalid)

        position, actual = central_start, 0
        while position < central_start + central_size:
            actual += 1
            if actual > 10000:
                raise SnapshotInstallError(invalid)
            stream.seek(position)
            header = stream.read(46)
            name_size, extra_size, comment_size = (
                integer(header, 28, 2),
                integer(header, 30, 2),
                integer(header, 32, 2),
            )
            next_position = position + 46 + name_size + extra_size + comment_size
            local_position = integer(header, 42, 4)
            if (
                len(header) != 46
                or header[:4] != b"PK\x01\x02"
                or integer(header, 6, 2) >= 45
                or integer(header, 8, 2) & 0x2041
                or integer(header, 20, 4) == 0xFFFFFFFF
                or integer(header, 24, 4) == 0xFFFFFFFF
                or not name_size
                or comment_size
                or integer(header, 34, 2) != 0
                or local_position == 0xFFFFFFFF
                or local_position + 30 > central_start
                or next_position > central_start + central_size
            ):
                raise SnapshotInstallError(invalid)
            name = stream.read(name_size)
            extras(stream.read(extra_size))
            if name.endswith(b".pyc"):
                raise SnapshotInstallError("EMBEDDING_INDEX_PRIVATE_BYTECODE_FORBIDDEN")
            stream.seek(local_position)
            local = stream.read(30)
            local_name_size, local_extra_size = integer(local, 26, 2), integer(local, 28, 2)
            data_start = local_position + 30 + local_name_size + local_extra_size
            if (
                len(local) != 30
                or local[:4] != b"PK\x03\x04"
                or local[4:10] != header[6:12]
                or local_name_size != name_size
                or integer(local, 18, 4) == 0xFFFFFFFF
                or integer(local, 22, 4) == 0xFFFFFFFF
                or data_start + integer(header, 20, 4) > central_start
                or stream.read(local_name_size) != name
            ):
                raise SnapshotInstallError(invalid)
            extras(stream.read(local_extra_size))
            position = next_position
        if (
            actual != count
            or position != central_start + central_size
            or _epoch(before) != _epoch(os.fstat(stream.fileno()))
            or _epoch(before) != _epoch(wheel.lstat())
        ):
            raise SnapshotInstallError(invalid)


def _index_private_bytecode(prefix: Path) -> None:
    """Deny even unregistered bytecode throughout private EOM namespaces, not public deps."""
    site = prefix / "lib/python3.12/site-packages"
    count = 0
    for namespace in site.iterdir():
        if not namespace.name.startswith(("eom_", "eomctl")):
            continue
        if namespace.is_symlink():
            raise SnapshotInstallError("EMBEDDING_INDEX_PRIVATE_NAMESPACE_INVALID")
        if namespace.name.endswith(".pyc"):
            raise SnapshotInstallError("EMBEDDING_INDEX_PRIVATE_BYTECODE_FORBIDDEN")
        for parent, directories, files in os.walk(namespace, followlinks=False):
            count += len(directories) + len(files)
            if any((Path(parent) / name).is_symlink() for name in (*directories, *files)):
                raise SnapshotInstallError("EMBEDDING_INDEX_PRIVATE_NAMESPACE_INVALID")
            if count > 20000 or any(name.endswith(".pyc") for name in (*directories, *files)):
                raise SnapshotInstallError("EMBEDDING_INDEX_PRIVATE_BYTECODE_FORBIDDEN")


def _index_private_source(
    prefix: Path, wheel: Path, source: Path, commit: str, package: str
) -> None:
    """Private source leaves must be from the pinned Git archive, never a historical substitute."""
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None or package not in _INDEX_PRIVATE_SOURCES:
        raise SnapshotInstallError("EMBEDDING_INDEX_PRIVATE_SOURCE_INVALID")
    _index_private_zip32(wheel)
    with tarfile.open(source, mode="r:") as archive:
        if archive.pax_headers.get("comment") != commit:
            raise SnapshotInstallError("EMBEDDING_INDEX_PRIVATE_COMMIT_MISMATCH")
        entries = {}
        for number, member in enumerate(archive):
            if number >= 20000 or member.name in entries or member.size > 64 * 1024**2:
                raise SnapshotInstallError("EMBEDDING_INDEX_PRIVATE_SOURCE_INVALID")
            _relative(member.name)
            entries[member.name] = member
        with zipfile.ZipFile(wheel) as payload:
            names = payload.namelist()
            if len(names) > 10000 or len(names) != len(set(names)):
                raise SnapshotInstallError("EMBEDDING_INDEX_PRIVATE_WHEEL_INVALID")
            if package == "eom-gpu-lease":
                for entry in payload.infolist():
                    if entry.is_dir() or entry.filename.endswith(".dist-info/RECORD"):
                        continue
                    relative = _relative(entry.filename)
                    if (
                        relative.as_posix() != entry.filename
                        or "\\" in entry.filename
                        or ".data" in relative.parts
                        or entry.file_size > 1024 * 1024
                    ):
                        raise SnapshotInstallError("EMBEDDING_INDEX_PRIVATE_WHEEL_INVALID")
                    if (
                        _hash(prefix / "lib/python3.12/site-packages" / relative)
                        != hashlib.sha256(payload.read(entry)).hexdigest()
                    ):
                        raise SnapshotInstallError("EMBEDDING_INDEX_PRIVATE_INSTALLED_MISMATCH")
            for original, installed in _INDEX_PRIVATE_SOURCES[package]:
                selected_source = entries.get(original)
                if (
                    selected_source is None
                    or not selected_source.isfile()
                    or selected_source.size > 1024 * 1024
                ):
                    raise SnapshotInstallError("EMBEDDING_INDEX_PRIVATE_SOURCE_MISSING")
                stream = archive.extractfile(selected_source)
                if stream is None:
                    raise SnapshotInstallError("EMBEDDING_INDEX_PRIVATE_SOURCE_MISSING")
                with stream:
                    raw = stream.read(1024 * 1024 + 1)
                if (
                    installed not in names
                    or payload.getinfo(installed).file_size != len(raw)
                    or payload.read(installed) != raw
                ):
                    raise SnapshotInstallError("EMBEDDING_INDEX_PRIVATE_SOURCE_MISMATCH")
                if (
                    _hash(prefix / "lib/python3.12/site-packages" / installed)
                    != hashlib.sha256(raw).hexdigest()
                ):
                    raise SnapshotInstallError("EMBEDDING_INDEX_PRIVATE_INSTALLED_MISMATCH")


def _index_inventory(prefix: Path, expected: dict[str, str]) -> None:
    site = prefix / "lib/python3.12/site-packages"
    found = {}
    if any(site.glob("*.egg-info")):
        raise SnapshotInstallError("EMBEDDING_INDEX_DISTRIBUTION_LAYOUT_INVALID")
    for path in site.glob("*.dist-info/METADATA"):
        require_root_path(path, directory=False)
        if path.stat().st_size > 128 * 1024:
            raise SnapshotInstallError("EMBEDDING_INDEX_METADATA_TOO_LARGE")
        value = BytesParser().parsebytes(path.read_bytes())
        names, versions = value.get_all("Name", []), value.get_all("Version", [])
        if len(names) != 1 or len(versions) != 1:
            raise SnapshotInstallError("EMBEDDING_INDEX_METADATA_INVALID")
        name = re.sub(r"[-_.]+", "-", names[0]).lower()
        if name in found:
            raise SnapshotInstallError("EMBEDDING_INDEX_METADATA_DUPLICATE")
        found[name] = versions[0]
    if found != expected:
        raise SnapshotInstallError("EMBEDDING_INDEX_DISTRIBUTION_CLOSURE_INVALID")


def index_runtime_main() -> int:
    """No model/unit/factory/proof construction; installation is not authority."""
    parser = argparse.ArgumentParser(description="Fixed protected indexing snapshot bootstrap")
    parser.add_argument("--profile", choices=tuple(_INDEX_PREFIXES), required=True)
    parser.add_argument("--lock-directory", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, action="append", required=True)
    for name in ("platform", "lease"):
        parser.add_argument(f"--{name}-wheel", type=Path, required=name == "platform")
        parser.add_argument(f"--{name}-wheel-sha256", required=name == "platform")
        parser.add_argument(f"--{name}-source", type=Path, required=name == "platform")
        parser.add_argument(f"--{name}-source-sha256", required=name == "platform")
        parser.add_argument(f"--{name}-commit", required=name == "platform")
    args = parser.parse_args()
    try:
        prefix = _INDEX_PREFIXES[args.profile]
        if (
            os.geteuid() != 0
            or not sys.flags.isolated
            or not sys.flags.no_site
            or not sys.flags.dont_write_bytecode
            or Path(sys.executable) != prefix / "bin/python3.12"
            or sys.version_info[:3] != (3, 12, 13)
            or sys.platform != "linux"
            or os.uname().machine != "x86_64"
        ):
            raise SnapshotInstallError("EMBEDDING_INDEX_INSTALL_CONTEXT_INVALID")
        require_root_path(Path(__file__).resolve(strict=True), directory=False)
        validate_runtime_tree(prefix)
        selected = index_runtime_locks(args.lock_directory, args.profile)
        cpu = index_runtime_locks(args.lock_directory, "CPU_INDEX_FP32")
        cuda = index_runtime_locks(args.lock_directory, "CUDA_INDEX_FP32")
        known = {row[1] for row in (*cpu.values(), *cuda.values())}
        if not 1 <= len(args.wheelhouse) <= 4 or len(set(args.wheelhouse)) != len(args.wheelhouse):
            raise SnapshotInstallError("EMBEDDING_INDEX_WHEELHOUSE_INVALID")
        sources = {}
        for directory in args.wheelhouse:
            for name in os.listdir(directory):
                if name not in known or name in sources:
                    raise SnapshotInstallError("EMBEDDING_INDEX_WHEELHOUSE_INVENTORY_INVALID")
                sources[name] = directory / name
        if not {row[1] for row in selected.values()}.issubset(sources):
            raise SnapshotInstallError("EMBEDDING_INDEX_WHEELHOUSE_INCOMPLETE")
        required = (
            "lease_wheel",
            "lease_wheel_sha256",
            "lease_source",
            "lease_source_sha256",
            "lease_commit",
        )
        if (
            args.profile == "CUDA_INDEX_FP32"
            and any(getattr(args, name) is None for name in required)
        ) or (
            args.profile == "CPU_INDEX_FP32"
            and any(getattr(args, name) is not None for name in required)
        ):
            raise SnapshotInstallError("EMBEDDING_INDEX_PRIVATE_PINS_REQUIRED")
        for kind in ("platform", "lease") if args.profile == "CUDA_INDEX_FP32" else ("platform",):
            wheel_sha, source_sha, commit = (
                getattr(args, f"{kind}_wheel_sha256"),
                getattr(args, f"{kind}_source_sha256"),
                getattr(args, f"{kind}_commit"),
            )
            if (
                re.fullmatch(r"[0-9a-f]{64}", wheel_sha) is None
                or re.fullmatch(r"[0-9a-f]{64}", source_sha) is None
                or re.fullmatch(r"[0-9a-f]{40}", commit) is None
            ):
                raise SnapshotInstallError("EMBEDDING_INDEX_PRIVATE_PINS_REQUIRED")
        expected = {name: row[0] for name, row in selected.items()} | {"eom-platform": "0.1.0"}
        if args.profile == "CUDA_INDEX_FP32":
            expected["eom-gpu-lease"] = "0.1.0"
        _index_inventory(prefix, expected)
        count = 0
        for _version, basename, sha in sorted(selected.values(), key=lambda row: row[1]):
            retained = retain_index_archive(sources[basename], sha, basename, maximum=2 * 1024**3)
            count += retained.stat().st_size
        if count != _INDEX_PUBLIC_BYTES[args.profile]:
            raise SnapshotInstallError("EMBEDDING_INDEX_PUBLIC_BYTES_MISMATCH")
        for kind, package in (
            (("platform", "eom-platform"), ("lease", "eom-gpu-lease"))
            if args.profile == "CUDA_INDEX_FP32"
            else (("platform", "eom-platform"),)
        ):
            wheel = retain_index_archive(
                getattr(args, f"{kind}_wheel"),
                getattr(args, f"{kind}_wheel_sha256"),
                package.replace("-", "_") + "-0.1.0-py3-none-any.whl",
                maximum=64 * 1024**2,
            )
            source = retain_index_archive(
                getattr(args, f"{kind}_source"),
                getattr(args, f"{kind}_source_sha256"),
                f"source-{getattr(args, f'{kind}_commit')}.tar",
                maximum=256 * 1024**2,
            )
            _index_private_zip32(wheel)
            if kind == "platform":
                verify_platform_wheel(prefix, wheel, args.platform_wheel_sha256)
            _index_private_source(prefix, wheel, source, getattr(args, f"{kind}_commit"), package)
        _index_private_bytecode(prefix)
        print("EMBEDDING_INDEX_INSTALL_STATUS=INSTALLED_NOT_ADMITTED")
        print("EMBEDDING_INDEX_PROBE_STATUS=NOT_PROBED")
        print("EMBEDDING_INDEX_NUMERICAL_PROOF=OWNER_GATE_REQUIRED")
        return 0
    except Exception:
        print("EMBEDDING_INDEX_SNAPSHOT_REJECTED", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["index-runtime"]:
        del sys.argv[1]
        raise SystemExit(index_runtime_main())
    if sys.argv[1:2] == ["model-only"]:
        del sys.argv[1]
        raise SystemExit(model_only_main())
    raise SystemExit(main())
