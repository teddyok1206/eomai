#!/srv/eom/conda/envs/eom-api/bin/python
"""Check or explicitly install only committed live compatibility admission evidence.

Run with the installed explicit Conda interpreter. This command does not execute a
model, update Codex, or change a preset/Workflow/Content Pack/default/release.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml
from eom_identifiers import sha256_bytes
from eom_orchestrator.capability_observer import load_reviewed_capability_policy
from eom_orchestrator.codex_compatibility_policy import (
    current_admission_bindings,
    load_committed_compatibility_report,
    render_compatibility_policy,
)
from eom_orchestrator.codex_compatibility_runtime import observe_compatibility_runtime
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_engine
from eom_protocol.artifact_members import ArtifactMemberPointer

POLICY_TARGET = Path("/etc/eom/codex-capabilities.yaml")
POLICY_LIMIT = 64 * 1024
SHA_PATTERN = re.compile(r"\Asha256:[0-9a-f]{64}\Z", re.ASCII)


def _fail(code: str = "CONTROL_COMPATIBILITY_POLICY_TARGET_INVALID") -> ControlPlaneError:
    return ControlPlaneError(code, "protected compatibility policy operation refused")


def read_bounded_file(path: Path, *, limit: int, owner: tuple[int, int] | None = None) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= limit
            or (
                owner is not None
                and (before.st_uid, before.st_gid, stat.S_IMODE(before.st_mode)) != (*owner, 0o644)
            )
        ):
            raise _fail()
        payload = bytearray()
        while len(payload) <= limit:
            chunk = os.read(descriptor, limit + 1 - len(payload))
            if not chunk:
                break
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if len(payload) != before.st_size or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise _fail()
        return bytes(payload)
    except OSError as exc:
        raise _fail() from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _protected_parent(path: Path, *, uid: int) -> int:
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != uid
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise _fail()
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    actual = os.fstat(descriptor)
    if (metadata.st_dev, metadata.st_ino) != (actual.st_dev, actual.st_ino):
        os.close(descriptor)
        raise _fail()
    return descriptor


def _write_file(parent: int, name: str, payload: bytes, *, uid: int, gid: int) -> None:
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=parent,
    )
    try:
        os.fchown(descriptor, uid, gid)
        os.fchmod(descriptor, 0o644)
        offset = 0
        while offset < len(payload):
            count = os.write(descriptor, payload[offset:])
            if count <= 0:
                raise OSError("short policy write")
            offset += count
        os.fsync(descriptor)
    except Exception:
        os.unlink(name, dir_fd=parent)
        raise
    finally:
        os.close(descriptor)


def install_policy_bytes(
    payload: bytes, *, previous_sha256: str, uid: int = 0, gid: int = 0
) -> str:
    """Atomic exact-predecessor advance; keep a verified recoverable copy on disk."""

    if SHA_PATTERN.fullmatch(previous_sha256) is None or not 0 < len(payload) <= POLICY_LIMIT:
        raise _fail()
    parent = _protected_parent(POLICY_TARGET.parent, uid=uid)
    temporary = ".codex-capabilities." + uuid4().hex + ".yaml"
    staged = False
    try:
        fcntl.flock(parent, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous = read_bounded_file(POLICY_TARGET, limit=POLICY_LIMIT, owner=(uid, gid))
        if previous == payload:
            return "REPLAYED"
        if sha256_bytes(previous) != previous_sha256:
            raise _fail("CONTROL_COMPATIBILITY_POLICY_PREDECESSOR_CHANGED")
        backup = POLICY_TARGET.with_name(
            "codex-capabilities.previous." + previous_sha256.removeprefix("sha256:") + ".yaml"
        )
        if backup.exists() or backup.is_symlink():
            if read_bounded_file(backup, limit=POLICY_LIMIT, owner=(uid, gid)) != previous:
                raise _fail("CONTROL_COMPATIBILITY_POLICY_BACKUP_CONFLICT")
        else:
            _write_file(parent, backup.name, previous, uid=uid, gid=gid)
            os.fsync(parent)
        _write_file(parent, temporary, payload, uid=uid, gid=gid)
        staged = True
        if read_bounded_file(POLICY_TARGET, limit=POLICY_LIMIT, owner=(uid, gid)) != previous:
            raise _fail("CONTROL_COMPATIBILITY_POLICY_PREDECESSOR_CHANGED")
        os.replace(temporary, POLICY_TARGET.name, src_dir_fd=parent, dst_dir_fd=parent)
        staged = False
        os.fsync(parent)
        return "INSTALLED"
    except OSError as exc:
        raise _fail() from exc
    finally:
        if staged:
            os.unlink(temporary, dir_fd=parent)
        os.close(parent)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-pointer", required=True, type=Path)
    parser.add_argument("--previous-policy-sha256", required=True)
    parser.add_argument("--install", action="store_true", help="otherwise check without writing")
    arguments = parser.parse_args(argv)
    engine = None
    try:
        if os.geteuid() != 0:
            raise _fail("CONTROL_COMPATIBILITY_POLICY_REQUIRES_ROOT")
        if SHA_PATTERN.fullmatch(arguments.previous_policy_sha256) is None:
            raise _fail()
        # The sole target is fixed; do not follow an operator-provided target or its ancestors.
        for parent_path in POLICY_TARGET.parents:
            descriptor = _protected_parent(parent_path, uid=0)
            os.close(descriptor)
        pointer = ArtifactMemberPointer.model_validate_json(
            read_bounded_file(arguments.report_pointer, limit=16384)
        )
        prior = read_bounded_file(POLICY_TARGET, limit=POLICY_LIMIT, owner=(0, 0))
        baseline = load_reviewed_capability_policy(POLICY_TARGET)
        runtime = observe_compatibility_runtime()
        engine = build_engine()
        report = load_committed_compatibility_report(engine, pointer)
        now = datetime.now(UTC)
        bindings = current_admission_bindings(engine, runtime=runtime, now=now)
        policy = render_compatibility_policy(
            report, baseline_policy=baseline, current_runtime=runtime, bindings=bindings, now=now
        )
        payload = yaml.safe_dump(policy.model_dump(mode="json"), sort_keys=True).encode("utf-8")
        if prior != payload and sha256_bytes(prior) != arguments.previous_policy_sha256:
            raise _fail("CONTROL_COMPATIBILITY_POLICY_PREDECESSOR_CHANGED")
        # Recheck live pins immediately before the filesystem authority boundary.
        if (
            observe_compatibility_runtime() != runtime
            or current_admission_bindings(engine, runtime=runtime, now=datetime.now(UTC))
            != bindings
        ):
            raise _fail("CONTROL_COMPATIBILITY_POLICY_RUNTIME_CHANGED")
        status = "CHECKED"
        if arguments.install:
            status = install_policy_bytes(payload, previous_sha256=arguments.previous_policy_sha256)
        print(json.dumps({"status": status, "policy_sha256": sha256_bytes(payload)}))
        return 0
    except Exception as exc:
        # Never print DB URLs, provider content, report values or exception details.
        code = (
            exc.code
            if isinstance(exc, ControlPlaneError)
            else "CONTROL_COMPATIBILITY_POLICY_INVALID"
        )
        print(json.dumps({"status": "REFUSED", "error_code": code}), file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
