"""Catalog transport for one fixed, sandboxed native-exam preparation instance.

No parser runs in the Catalog API process. Failed/uncertain unit workspaces remain
local for diagnosis; successful temporary transport files are removed after the
existing ZIP/identity/preservation validator has accepted them.
"""

from __future__ import annotations

import grp
import os
import pwd
import re
import secrets
import shutil
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from eom_hwpx_contracts.native_exam_preparation import (
    NATIVE_EXAM_REQUEST_LIMIT,
    NATIVE_EXAM_SOURCE_LIMIT,
    NATIVE_EXAM_ZIP_LIMIT,
    NativeExamFilePreparationRequest,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.native_exam_preparation import (
    PreparedNativeExamFiles,
    require_native_exam_runtime_python,
    unpack_native_exam_file_preparation,
)

NATIVE_EXAM_PREPARER_ROOT = Path("/var/lib/eom-catalog-api/staging/native-exam")
NATIVE_EXAM_WORKER_ROOT = Path("/run/eom-native-exam")
NATIVE_EXAM_INSTANCE = re.compile(r"^nativeexam_[0-9a-f]{32}$")
NATIVE_EXAM_UNIT_TEMPLATE = "eom-native-exam-preparer@{instance}.service"
SYSTEMCTL = Path("/usr/bin/systemctl")


@dataclass(frozen=True, slots=True)
class NativeExamWorkspacePrincipals:
    manager_uid: int
    worker_uid: int
    group_gid: int


def native_exam_workspace_principals() -> NativeExamWorkspacePrincipals:
    principals = NativeExamWorkspacePrincipals(
        pwd.getpwnam("eom-catalog-manager").pw_uid,
        pwd.getpwnam("eom-image").pw_uid,
        grp.getgrnam("eom-api").gr_gid,
    )
    if principals.manager_uid == principals.worker_uid:
        raise ValueError("NATIVE_EXAM_PREPARER_IDENTITY_INVALID")
    return principals


def _stable_file_identity(value: os.stat_result) -> tuple[int, ...]:
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


def require_native_exam_workspace(
    root: Path,
    instance: str,
    *,
    root_owner_uid: int,
    workspace_owner_uid: int,
    group_gid: int,
) -> Path:
    if not root.is_absolute() or NATIVE_EXAM_INSTANCE.fullmatch(instance) is None:
        raise ValueError("NATIVE_EXAM_PREPARER_WORKSPACE_INVALID")
    for path, owner, mode in (
        (root, root_owner_uid, 0o700),
        (root / instance, workspace_owner_uid, 0o770),
    ):
        metadata = path.lstat()
        if (
            path.is_symlink()
            or path.resolve() != path
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != owner
            or metadata.st_gid != group_gid
            or stat.S_IMODE(metadata.st_mode) != mode
        ):
            raise ValueError("NATIVE_EXAM_PREPARER_WORKSPACE_INVALID")
    return root / instance


def read_native_exam_workspace_file(
    path: Path,
    *,
    maximum: int,
    owner_uid: int,
    group_gid: int,
) -> bytes:
    """One bounded descriptor read; symlinks, hardlinks and in-read changes fail closed."""
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != owner_uid
            or before.st_gid != group_gid
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o640
            or not 0 < before.st_size <= maximum
        ):
            raise ValueError("NATIVE_EXAM_PREPARER_FILE_INVALID")
        chunks = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("NATIVE_EXAM_PREPARER_FILE_CHANGED")
            chunks.append(chunk)
            remaining -= len(chunk)
        extra = os.read(descriptor, 1)
        after = os.fstat(descriptor)
        if extra or _stable_file_identity(before) != _stable_file_identity(after):
            raise ValueError("NATIVE_EXAM_PREPARER_FILE_CHANGED")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _write_input(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
    os.fchmod(descriptor, 0o640)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


class SystemdNativeExamFilePreparer:
    """StartUnit for a fixed template, never privileged transient unit creation."""

    def __init__(
        self,
        *,
        root: Path = NATIVE_EXAM_PREPARER_ROOT,
        run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
        token_hex: Callable[[int], str] = secrets.token_hex,
    ) -> None:
        self.root = root
        self.run = run
        self.token_hex = token_hex

    def __call__(
        self,
        source_bytes: bytes,
        *,
        request: NativeExamFilePreparationRequest,
        workspace: Path,
        python: Path,
    ) -> PreparedNativeExamFiles:
        request = NativeExamFilePreparationRequest.model_validate(request.model_dump(mode="json"))
        principals = native_exam_workspace_principals()
        if os.geteuid() != principals.manager_uid or os.getegid() != principals.group_gid:
            raise ValueError("NATIVE_EXAM_PREPARER_IDENTITY_INVALID")
        require_native_exam_runtime_python(python)
        encoded = canonical_json_bytes(request.model_dump(mode="json"))
        if (
            not 0 < len(source_bytes) <= NATIVE_EXAM_SOURCE_LIMIT
            or sha256_bytes(source_bytes) != request.expected_source_sha256
            or len(encoded) > NATIVE_EXAM_REQUEST_LIMIT
            or not workspace.is_absolute()
            or os.path.lexists(workspace)
        ):
            raise ValueError("NATIVE_EXAM_PREPARATION_INPUT_INVALID")
        signature = (
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" if request.source_format == "HWP" else b"PK\x03\x04"
        )
        if not source_bytes.startswith(signature):
            raise ValueError("NATIVE_EXAM_PREPARATION_SOURCE_FORMAT_INVALID")
        instance = "nativeexam_" + self.token_hex(16)
        if NATIVE_EXAM_INSTANCE.fullmatch(instance) is None:
            raise ValueError("NATIVE_EXAM_PREPARER_INSTANCE_INVALID")
        parent = self.root.parent
        parent_metadata = parent.lstat()
        if (
            parent.resolve() != parent
            or not stat.S_ISDIR(parent_metadata.st_mode)
            or parent_metadata.st_uid != os.geteuid()
            or parent_metadata.st_mode & 0o022
        ):
            raise ValueError("NATIVE_EXAM_PREPARER_WORKSPACE_INVALID")
        self.root.mkdir(mode=0o700, exist_ok=True)
        root_metadata = self.root.lstat()
        if (
            self.root.is_symlink()
            or self.root.resolve() != self.root
            or not stat.S_ISDIR(root_metadata.st_mode)
            or root_metadata.st_uid != os.geteuid()
            or root_metadata.st_gid != principals.group_gid
            or stat.S_IMODE(root_metadata.st_mode) != 0o700
        ):
            raise ValueError("NATIVE_EXAM_PREPARER_WORKSPACE_INVALID")
        job = self.root / instance
        job.mkdir(mode=0o770)
        job.chmod(0o770)
        require_native_exam_workspace(
            self.root,
            instance,
            root_owner_uid=principals.manager_uid,
            workspace_owner_uid=principals.manager_uid,
            group_gid=principals.group_gid,
        )
        _write_input(job / "request.json", encoded)
        _write_input(job / "input.native", source_bytes)
        unit = NATIVE_EXAM_UNIT_TEMPLATE.format(instance=instance)
        try:
            completed = self.run(
                [str(SYSTEMCTL), "--no-ask-password", "start", unit],
                check=False,
                capture_output=True,
                timeout=120.0,
                env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            # Do not delete a workspace while StartUnit completion is unknown.
            raise ValueError("NATIVE_EXAM_PREPARER_EXECUTION_UNCONFIRMED") from exc
        if completed.returncode or len(completed.stdout) > 65536 or len(completed.stderr) > 65536:
            raise ValueError("NATIVE_EXAM_PREPARER_EXECUTION_FAILED")
        require_native_exam_workspace(
            self.root,
            instance,
            root_owner_uid=principals.manager_uid,
            workspace_owner_uid=principals.manager_uid,
            group_gid=principals.group_gid,
        )

        def read_input(name: str, maximum: int) -> bytes:
            return read_native_exam_workspace_file(
                job / name,
                maximum=maximum,
                owner_uid=principals.manager_uid,
                group_gid=principals.group_gid,
            )

        if (
            read_input("request.json", NATIVE_EXAM_REQUEST_LIMIT) != encoded
            or sha256_bytes(read_input("input.native", NATIVE_EXAM_SOURCE_LIMIT))
            != request.expected_source_sha256
        ):
            raise ValueError("NATIVE_EXAM_PREPARER_INPUT_CHANGED")
        payload = read_native_exam_workspace_file(
            job / "result.zip",
            maximum=NATIVE_EXAM_ZIP_LIMIT,
            owner_uid=principals.worker_uid,
            group_gid=principals.group_gid,
        )
        result = unpack_native_exam_file_preparation(payload, request=request, workspace=workspace)
        shutil.rmtree(job)
        return result
