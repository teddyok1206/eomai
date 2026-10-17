"""Scoped root image-runtime metadata preparation, preserving shared Conda inodes.

Caller owns the coordinated entry drain/fence. No package/model execution,
unrelated environment contents, user membership or service state is changed.
"""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

_PARENT = Path("/srv/eom/conda/envs")
_PREFIXES = (_PARENT / "eom-image", _PARENT / "eom-image-trainer")
_WORKSPACE_ROOT = Path("/opt/eom/image-runtime-preparations")


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("IMAGE_GPU_RUNTIME_PERMISSION_PREPARATION_INVALID")


def _epoch(value: os.stat_result, directory: bool) -> tuple[int, ...]:
    fields = (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode)
    return (
        fields
        if directory
        else (*fields, value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    )


@dataclass(frozen=True, slots=True)
class RuntimePermissionMember:
    path: Path
    kind: Literal["DIRECTORY", "REGULAR"]
    before: tuple[int, ...]
    target_mode: int
    sha256: str | None
    privatize: bool


def _scope() -> tuple[tuple[Path, bool], ...]:
    directories, regular = {_PARENT}, set()
    for prefix in _PREFIXES:
        site = prefix / "lib/python3.11/site-packages"
        directories.update((prefix, prefix / "bin", prefix / "lib", site.parent, site))
        regular.add(prefix / "bin/python3.11")
        entries = tuple(site.glob("*.dist-info"))
        _require(len(entries) <= 512)
        for info in entries:
            _require(info.parent == site and not info.is_symlink())
            directories.add(info)
            regular.update((info / "METADATA", info / "RECORD"))
    return tuple(
        (path, True)
        for path in sorted(directories, key=lambda value: (len(value.parts), str(value)))
    ) + tuple((path, False) for path in sorted(regular))


def _require_parent() -> None:
    for path in _PARENT.parents:
        value = path.lstat()
        _require(stat.S_ISDIR(value.st_mode) and value.st_uid == 0 and not value.st_mode & 0o022)


def capture_gpu_runtime_permission_plan() -> tuple[RuntimePermissionMember, ...]:
    """Bounded read-only metadata/byte capture; no repair or code execution."""
    _require(os.getresuid() == (0, 0, 0))
    _require_parent()
    owner = pwd.getpwnam("eom").pw_uid
    _require(owner > 0)
    output = []
    for path, directory in _scope():
        value = path.lstat()
        _require(value.st_uid in {0, owner} and not stat.S_ISLNK(value.st_mode))
        _require(stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode))
        mode = stat.S_IMODE(value.st_mode)
        _require(mode & 0o7000 == 0)
        changes = value.st_uid != 0 or bool(mode & 0o022)
        privatize = not directory and changes and value.st_nlink > 1
        digest = None
        if not directory:
            maximum = 64 * 1024**2 if path.name == "python3.11" else 8 * 1024**2
            _require(0 < value.st_size <= maximum and not (privatize and path.name == "python3.11"))
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
            try:
                _require(_epoch(os.fstat(descriptor), False) == _epoch(value, False))
                hashed = hashlib.sha256()
                count = 0
                while chunk := os.read(descriptor, min(65536, maximum + 1 - count)):
                    count += len(chunk)
                    _require(count <= maximum)
                    hashed.update(chunk)
                _require(
                    count == value.st_size
                    and _epoch(os.fstat(descriptor), False) == _epoch(value, False)
                )
                digest = hashed.hexdigest()
            finally:
                os.close(descriptor)
        _require(_epoch(path.lstat(), directory) == _epoch(value, directory))
        output.append(
            RuntimePermissionMember(
                path,
                "DIRECTORY" if directory else "REGULAR",
                _epoch(value, directory),
                mode & ~0o022,
                digest,
                privatize,
            )
        )
    return tuple(output)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _save(workspace: Path, name: str, value: object) -> None:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    descriptor = os.open(
        workspace / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o400
    )
    try:
        remaining = memoryview(raw)
        while remaining:
            count = os.write(descriptor, remaining)
            _require(count > 0)
            remaining = remaining[count:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _sync_directory(workspace)


def prepare_gpu_runtime_permissions(
    plan: tuple[RuntimePermissionMember, ...],
    *,
    workspace: Path,
) -> None:
    """One no-replay preparation after caller's drain/fence; preserve intent and alias bytes.

    On partial failure the original backup/intent remains for explicit recovery;
    this function never retries, deletes evidence or adjusts a plan to current state.
    """
    _require(os.getresuid() == (0, 0, 0) and type(plan) is tuple)
    _require_parent()
    _require(all(type(member) is RuntimePermissionMember for member in plan))
    _require(
        workspace.parent == _WORKSPACE_ROOT
        and re.fullmatch(r"imageprep_[0-9a-f]{32}", workspace.name) is not None
    )
    _require(tuple((member.path, member.kind == "DIRECTORY") for member in plan) == _scope())
    for member in plan:
        value = member.path.lstat()
        _require(_epoch(value, member.kind == "DIRECTORY") == member.before)
        _require(member.target_mode == stat.S_IMODE(value.st_mode) & ~0o022)
        _require(
            member.privatize
            == (
                member.kind == "REGULAR"
                and value.st_nlink > 1
                and (value.st_uid != 0 or bool(value.st_mode & 0o022))
            )
        )
    for path in (workspace, *workspace.parents):
        value = path.lstat()
        _require(stat.S_ISDIR(value.st_mode) and value.st_uid == 0 and not value.st_mode & 0o022)
    _require(stat.S_IMODE(workspace.lstat().st_mode) == 0o700)
    # Rename-based identity preservation requires a same-filesystem rollback
    # workspace. Refuse before any permission mutation rather than copying away
    # an original shared inode implicitly.
    _require(
        all(not member.privatize or member.before[0] == workspace.lstat().st_dev for member in plan)
    )
    alias_epochs: dict[tuple[int, int], tuple[int, ...]] = {}
    for member in plan:
        if member.kind == "REGULAR":
            key = (member.before[0], member.before[1])
            _require(alias_epochs.setdefault(key, member.before) == member.before)
    # Atomic reservation prevents two coordinators applying a captured plan.
    workspace = workspace / "permissions"
    workspace.mkdir(mode=0o700)
    _sync_directory(workspace.parent)
    _save(
        workspace, "intent.json", [asdict(member) | {"path": str(member.path)} for member in plan]
    )
    observations = []
    for index, member in enumerate(plan):
        path, directory = member.path, member.kind == "DIRECTORY"
        expected = (
            member.before if directory else alias_epochs[(member.before[0], member.before[1])]
        )
        _require(_epoch(path.lstat(), directory) == expected)
        if member.before[2] == 0 and not member.before[4] & 0o022:
            continue
        if member.privatize:
            backup = workspace / f"member-{index:04d}.original"
            _require(not backup.exists())
            os.rename(path, backup)
            _sync_directory(path.parent)
            _sync_directory(workspace)
            renamed = _epoch(backup.lstat(), False)
            _require(renamed[:-1] == expected[:-1])
            # Renaming our entry can update ctime on other still-shared aliases.
            # Track only this known effect; UID/mode/link-count/content epochs
            # must remain unchanged, and external drift still fails explicitly.
            alias_epochs[(member.before[0], member.before[1])] = renamed
            original = os.open(backup, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            descriptor = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
            )
            try:
                before = _epoch(os.fstat(original), False)
                hashed = hashlib.sha256()
                count = 0
                while chunk := os.read(original, 65536):
                    count += len(chunk)
                    _require(count <= 8 * 1024**2)
                    hashed.update(chunk)
                    remaining = memoryview(chunk)
                    while remaining:
                        written = os.write(descriptor, remaining)
                        _require(written > 0)
                        remaining = remaining[written:]
                _require(
                    hashed.hexdigest() == member.sha256
                    and _epoch(os.fstat(original), False) == before
                )
                os.fchown(descriptor, 0, member.before[3])
                os.fchmod(descriptor, member.target_mode)
                os.fsync(descriptor)
            finally:
                os.close(original)
                os.close(descriptor)
        else:
            descriptor = os.open(
                path,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | (os.O_DIRECTORY if directory else 0),
            )
            try:
                _require(_epoch(os.fstat(descriptor), directory) == member.before)
                os.fchown(descriptor, 0, member.before[3])
                os.fchmod(descriptor, member.target_mode)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        observed = path.lstat()
        _require(observed.st_uid == 0 and stat.S_IMODE(observed.st_mode) == member.target_mode)
        _sync_directory(path.parent)
        observations.append(
            {
                "path": str(path),
                "after": _epoch(observed, directory),
                "backup": f"member-{index:04d}.original" if member.privatize else None,
            }
        )
    _save(
        workspace,
        "result.json",
        {
            "status": "PREPARED_NOT_DEPLOYED",
            "members": len(plan),
            "privatized": sum(member.privatize for member in plan),
            "observations": observations,
        },
    )
