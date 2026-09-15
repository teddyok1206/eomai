#!/usr/bin/env python3
"""Materialize or remove one exact bounded Workflow-runner accelerator."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import stat
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

BASE_UNIT_NAME = "eom-workflow-runner.service"
ACCELERATOR_UNIT_NAME = "eom-workflow-runner-accelerator.service"
BASE_UNIT_PATH = Path("/etc/systemd/system/eom-workflow-runner.service")
ACCELERATOR_UNIT_PATH = Path("/run/systemd/system/eom-workflow-runner-accelerator.service")
SYSTEMCTL = Path("/usr/bin/systemctl")
EXPECTED_UNIT_SHA256 = "sha256:1688c77a606ea647d498aacbb3f8f75265f459cf888e1495ae82a8d2887b2878"
MAX_UNIT_BYTES = 65_536
UNIT_MODE = 0o644
UNIT_OWNER = 0
UNIT_GROUP = 0
RUNTIME_UNIT_DIRECTORY_MODE = 0o755


class ScaleOutError(RuntimeError):
    """Fail-closed scale-out management error."""


@dataclass(frozen=True)
class FileIdentity:
    device: int
    inode: int
    mode: int
    uid: int
    gid: int
    links: int
    size: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> FileIdentity:
        return cls(
            device=value.st_dev,
            inode=value.st_ino,
            mode=stat.S_IMODE(value.st_mode),
            uid=value.st_uid,
            gid=value.st_gid,
            links=value.st_nlink,
            size=value.st_size,
        )


@dataclass(frozen=True)
class SafeFile:
    identity: FileIdentity
    content: bytes
    sha256: str


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _validate_regular_identity(
    value: os.stat_result,
    *,
    expected_mode: int,
    expected_uid: int,
    expected_gid: int,
) -> FileIdentity:
    identity = FileIdentity.from_stat(value)
    if not stat.S_ISREG(value.st_mode):
        raise ScaleOutError("Workflow runner unit is not a regular file")
    if identity.links != 1:
        raise ScaleOutError("Workflow runner unit link count is not one")
    if identity.mode != expected_mode:
        raise ScaleOutError("Workflow runner unit mode is not exact")
    if identity.uid != expected_uid or identity.gid != expected_gid:
        raise ScaleOutError("Workflow runner unit ownership is not exact")
    if identity.size < 1 or identity.size > MAX_UNIT_BYTES:
        raise ScaleOutError("Workflow runner unit size is outside the bound")
    return identity


def read_safe_unit(
    path: Path,
    *,
    expected_mode: int = UNIT_MODE,
    expected_uid: int = UNIT_OWNER,
    expected_gid: int = UNIT_GROUP,
) -> SafeFile:
    """Read one stable unit without following a final symlink."""

    try:
        before_path = path.lstat()
        before = _validate_regular_identity(
            before_path,
            expected_mode=expected_mode,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = _validate_regular_identity(
                os.fstat(descriptor),
                expected_mode=expected_mode,
                expected_uid=expected_uid,
                expected_gid=expected_gid,
            )
            if opened != before:
                raise ScaleOutError("Workflow runner unit changed before open")
            chunks: list[bytes] = []
            remaining = MAX_UNIT_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(remaining, 65_536))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            if len(content) > MAX_UNIT_BYTES:
                raise ScaleOutError("Workflow runner unit exceeded the read bound")
            after_fd = _validate_regular_identity(
                os.fstat(descriptor),
                expected_mode=expected_mode,
                expected_uid=expected_uid,
                expected_gid=expected_gid,
            )
            if after_fd != opened or len(content) != opened.size:
                raise ScaleOutError("Workflow runner unit changed during read")
        finally:
            os.close(descriptor)
        after_path = _validate_regular_identity(
            path.lstat(),
            expected_mode=expected_mode,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        if after_path != before:
            raise ScaleOutError("Workflow runner unit changed after read")
        return SafeFile(identity=before, content=content, sha256=_sha256(content))
    except (OSError, ValueError) as exc:
        if isinstance(exc, ScaleOutError):
            raise
        raise ScaleOutError("Workflow runner unit could not be read safely") from exc


def _validate_runtime_directory(
    path: Path,
    *,
    expected_uid: int = UNIT_OWNER,
    expected_gid: int = UNIT_GROUP,
    expected_mode: int = RUNTIME_UNIT_DIRECTORY_MODE,
) -> None:
    try:
        value = path.lstat()
    except OSError as exc:
        raise ScaleOutError("Runtime unit directory is unavailable") from exc
    if (
        not stat.S_ISDIR(value.st_mode)
        or path.is_symlink()
        or stat.S_IMODE(value.st_mode) != expected_mode
        or value.st_uid != expected_uid
        or value.st_gid != expected_gid
    ):
        raise ScaleOutError("Runtime unit directory identity is not exact")


def publish_runtime_unit(
    source: Path,
    target: Path,
    *,
    expected_sha256: str,
    expected_uid: int = UNIT_OWNER,
    expected_gid: int = UNIT_GROUP,
) -> Literal["CREATED", "ADOPTED_EXACT_EXISTING"]:
    """Publish exact source bytes without replacing an existing target."""

    _validate_runtime_directory(
        target.parent,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    source_value = read_safe_unit(
        source,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    if source_value.sha256 != expected_sha256:
        raise ScaleOutError("Canonical Workflow runner unit hash mismatch")
    if target.exists() or target.is_symlink():
        existing = read_safe_unit(
            target,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        if existing.content != source_value.content or existing.sha256 != expected_sha256:
            raise ScaleOutError("Conflicting Workflow runner accelerator unit exists")
        return "ADOPTED_EXACT_EXISTING"

    temporary = target.parent / f".{target.name}.{secrets.token_hex(16)}"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(temporary, flags, UNIT_MODE)
        os.fchmod(descriptor, UNIT_MODE)
        os.fchown(descriptor, expected_uid, expected_gid)
        view = memoryview(source_value.content)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count < 1:
                raise ScaleOutError("Workflow runner unit write did not progress")
            written += count
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        staged = read_safe_unit(
            temporary,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        if staged.content != source_value.content or staged.sha256 != expected_sha256:
            raise ScaleOutError("Staged Workflow runner accelerator unit mismatch")
        os.link(temporary, target, follow_symlinks=False)
        os.unlink(temporary)
        directory_descriptor = os.open(
            target.parent,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        published = read_safe_unit(
            target,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        if published.content != source_value.content or published.sha256 != expected_sha256:
            raise ScaleOutError("Published Workflow runner accelerator unit mismatch")
        return "CREATED"
    except FileExistsError as exc:
        raise ScaleOutError("Workflow runner accelerator target appeared concurrently") from exc
    except OSError as exc:
        raise ScaleOutError("Workflow runner accelerator publication failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def remove_runtime_unit(
    source: Path,
    target: Path,
    *,
    expected_sha256: str,
    expected_uid: int = UNIT_OWNER,
    expected_gid: int = UNIT_GROUP,
) -> Literal["REMOVED", "ALREADY_ABSENT"]:
    """Remove only a byte-exact accelerator after its service has stopped."""

    _validate_runtime_directory(
        target.parent,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    if not target.exists() and not target.is_symlink():
        return "ALREADY_ABSENT"
    source_value = read_safe_unit(
        source,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    target_value = read_safe_unit(
        target,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    if (
        source_value.sha256 != expected_sha256
        or target_value.sha256 != expected_sha256
        or target_value.content != source_value.content
    ):
        raise ScaleOutError("Workflow runner accelerator is not the exact reviewed unit")
    before = target_value.identity
    if FileIdentity.from_stat(target.lstat()) != before:
        raise ScaleOutError("Workflow runner accelerator changed before removal")
    try:
        target.unlink()
        directory_descriptor = os.open(
            target.parent,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        raise ScaleOutError("Workflow runner accelerator removal failed") from exc
    return "REMOVED"


def _systemctl(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        (str(SYSTEMCTL), *arguments),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if check and completed.returncode != 0:
        raise ScaleOutError("systemd operation failed closed")
    return completed


def _unit_properties(name: str) -> dict[str, str]:
    properties = (
        "LoadState",
        "FragmentPath",
        "DropInPaths",
        "User",
        "Group",
        "ActiveState",
        "SubState",
        "MainPID",
        "NRestarts",
        "ExecMainStatus",
    )
    completed = _systemctl(
        "show",
        name,
        "--no-pager",
        *(f"--property={property_name}" for property_name in properties),
    )
    values: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    if set(values) != set(properties):
        raise ScaleOutError("systemd property projection is incomplete")
    return values


def _active_transient_units() -> frozenset[str]:
    completed = _systemctl(
        "list-units",
        "--type=service",
        "--state=active,activating,reloading",
        "--all",
        "--plain",
        "--no-legend",
        "--no-pager",
        "eom-workflow-runner-*.service",
    )
    names = {line.split(maxsplit=1)[0] for line in completed.stdout.splitlines() if line.strip()}
    if any(not name.startswith("eom-workflow-runner-") for name in names):
        raise ScaleOutError("systemd returned an unexpected transient runner identity")
    return frozenset(names)


def _require_base(properties: dict[str, str]) -> None:
    if (
        properties["LoadState"] != "loaded"
        or properties["FragmentPath"] != str(BASE_UNIT_PATH)
        or properties["DropInPaths"]
        or properties["User"] != "eom-workflow-runner"
        or properties["Group"] != "eom"
        or properties["ActiveState"] != "active"
        or properties["SubState"] != "running"
        or int(properties["MainPID"]) < 1
        or int(properties["NRestarts"]) != 0
        or int(properties["ExecMainStatus"]) != 0
    ):
        raise ScaleOutError("Canonical Workflow runner service is not exact and healthy")


def _require_accelerator(properties: dict[str, str], *, base_pid: int) -> None:
    if (
        properties["LoadState"] != "loaded"
        or properties["FragmentPath"] != str(ACCELERATOR_UNIT_PATH)
        or properties["DropInPaths"]
        or properties["User"] != "eom-workflow-runner"
        or properties["Group"] != "eom"
        or properties["ActiveState"] != "active"
        or properties["SubState"] != "running"
        or int(properties["MainPID"]) < 1
        or int(properties["MainPID"]) == base_pid
        or int(properties["NRestarts"]) != 0
        or int(properties["ExecMainStatus"]) != 0
    ):
        raise ScaleOutError("Workflow runner accelerator is not exact and healthy")


def _require_staged_accelerator(properties: dict[str, str]) -> None:
    if (
        properties["LoadState"] != "loaded"
        or properties["FragmentPath"] != str(ACCELERATOR_UNIT_PATH)
        or properties["DropInPaths"]
        or properties["User"] != "eom-workflow-runner"
        or properties["Group"] != "eom"
        or properties["ActiveState"] != "inactive"
        or properties["SubState"] != "dead"
        or int(properties["MainPID"] or "0") != 0
        or int(properties["NRestarts"]) != 0
        or int(properties["ExecMainStatus"]) != 0
    ):
        raise ScaleOutError("Staged Workflow runner accelerator is not exact and inactive")


def _status() -> dict[str, object]:
    base_value = read_safe_unit(BASE_UNIT_PATH)
    if base_value.sha256 != EXPECTED_UNIT_SHA256:
        raise ScaleOutError("Installed canonical Workflow runner unit hash mismatch")
    base = _unit_properties(BASE_UNIT_NAME)
    _require_base(base)
    target_present = ACCELERATOR_UNIT_PATH.exists() or ACCELERATOR_UNIT_PATH.is_symlink()
    accelerator = _unit_properties(ACCELERATOR_UNIT_NAME)
    if target_present:
        target_value = read_safe_unit(ACCELERATOR_UNIT_PATH)
        if target_value.sha256 != EXPECTED_UNIT_SHA256:
            raise ScaleOutError("Installed Workflow runner accelerator unit hash mismatch")
    if accelerator["LoadState"] == "loaded":
        if accelerator["ActiveState"] == "active":
            _require_accelerator(accelerator, base_pid=int(base["MainPID"]))
            state = "ACTIVE"
        elif target_present:
            _require_staged_accelerator(accelerator)
            state = "STAGED"
        else:
            raise ScaleOutError("Loaded Workflow runner accelerator has no exact unit file")
    elif (
        accelerator["LoadState"] == "not-found"
        and accelerator["ActiveState"] == "inactive"
        and not target_present
    ):
        state = "ABSENT"
    elif (
        accelerator["LoadState"] == "not-found"
        and accelerator["ActiveState"] == "inactive"
        and target_present
    ):
        state = "STAGED_UNLOADED"
    else:
        raise ScaleOutError("Workflow runner accelerator state is not bounded")
    active_transients = _active_transient_units()
    expected_transients = frozenset({ACCELERATOR_UNIT_NAME}) if state == "ACTIVE" else frozenset()
    if active_transients != expected_transients:
        raise ScaleOutError("Foreign or missing active Workflow runner transient unit")
    return {
        "status": state,
        "base_unit_sha256": base_value.sha256,
        "base_main_pid": int(base["MainPID"]),
        "accelerator_main_pid": (int(accelerator["MainPID"]) if accelerator["MainPID"] else 0),
        "active_transient_units": sorted(active_transients),
    }


def _start() -> dict[str, object]:
    if os.geteuid() != 0:
        raise ScaleOutError("Scale-out mutation requires root")
    before = _status()
    if before["status"] == "ACTIVE":
        return before | {"action": "ADOPTED_ACTIVE"}
    publication = publish_runtime_unit(
        BASE_UNIT_PATH,
        ACCELERATOR_UNIT_PATH,
        expected_sha256=EXPECTED_UNIT_SHA256,
    )
    _systemctl("daemon-reload")
    _systemctl("start", ACCELERATOR_UNIT_NAME)
    after = _status()
    if after["status"] != "ACTIVE":
        raise ScaleOutError("Workflow runner accelerator did not become active")
    return after | {"action": publication}


def _stop() -> dict[str, object]:
    if os.geteuid() != 0:
        raise ScaleOutError("Scale-out mutation requires root")
    accelerator = _unit_properties(ACCELERATOR_UNIT_NAME)
    if accelerator["LoadState"] == "loaded" and accelerator["ActiveState"] != "inactive":
        _systemctl("stop", ACCELERATOR_UNIT_NAME)
    stopped = _unit_properties(ACCELERATOR_UNIT_NAME)
    if stopped["ActiveState"] != "inactive" or int(stopped["MainPID"] or "0") != 0:
        raise ScaleOutError("Workflow runner accelerator did not stop cleanly")
    removal = remove_runtime_unit(
        BASE_UNIT_PATH,
        ACCELERATOR_UNIT_PATH,
        expected_sha256=EXPECTED_UNIT_SHA256,
    )
    _systemctl("daemon-reload")
    after = _status()
    if after["status"] != "ABSENT":
        raise ScaleOutError("Workflow runner accelerator removal is incomplete")
    return after | {"action": removal}


def main() -> int:
    parser = argparse.ArgumentParser(prog="manage-runner-scale-out")
    parser.add_argument("action", choices=("status", "start", "stop"))
    arguments = parser.parse_args()
    try:
        result = (
            _status()
            if arguments.action == "status"
            else _start()
            if arguments.action == "start"
            else _stop()
        )
    except (ScaleOutError, subprocess.SubprocessError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "error_code": "WORKFLOW_RUNNER_SCALE_OUT_INVALID",
                    "detail": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
