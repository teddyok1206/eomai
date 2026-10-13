"""Bounded approved installation metadata publication as the existing Artifact owner."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import pwd
import re
import stat
import sys
from datetime import UTC, datetime


def _epoch(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _owner() -> None:
    owner = pwd.getpwnam("eom-workflow-runner")
    if (
        owner.pw_uid <= 0
        or owner.pw_gid <= 0
        or os.getresuid() != (owner.pw_uid,) * 3
        or os.getresgid() != (owner.pw_gid,) * 3
    ):
        raise ValueError("EMBEDDING_BUNDLE_PUBLICATION_OWNER_REQUIRED")


def _descriptor(number: int, *, output: bool) -> os.stat_result:
    value = os.fstat(number)
    flags = fcntl.fcntl(number, fcntl.F_GETFL)
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != 0
        or value.st_nlink != 1
        or stat.S_IMODE(value.st_mode) != 0o600
        or flags & os.O_ACCMODE != (os.O_WRONLY if output else os.O_RDONLY)
        or flags & (os.O_APPEND | os.O_NONBLOCK)
        or os.lseek(number, 0, os.SEEK_CUR) != 0
        or (value.st_size != 0 if output else not 0 < value.st_size <= 64 * 1024)
    ):
        raise ValueError("EMBEDDING_BUNDLE_PUBLICATION_DESCRIPTOR_INVALID")
    return value


def publish_installation_bundle(source_commit: str, expected_bundle_raw_sha256: str) -> None:
    """Owner-approved pins are not accepted from the bundle; do not launch or grant access."""
    _owner()
    if (
        type(source_commit) is not str
        or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
        or type(expected_bundle_raw_sha256) is not str
        or re.fullmatch(r"sha256:[0-9a-f]{64}", expected_bundle_raw_sha256) is None
    ):
        raise ValueError("EMBEDDING_BUNDLE_PUBLICATION_PINS_INVALID")
    before, output = _descriptor(0, output=False), _descriptor(1, output=True)
    if (before.st_dev, before.st_ino) == (output.st_dev, output.st_ino):
        raise ValueError("EMBEDDING_BUNDLE_PUBLICATION_DESCRIPTOR_ALIAS")
    raw = bytearray()
    while block := os.read(0, before.st_size + 1 - len(raw)):
        raw.extend(block)
        if len(raw) > before.st_size:
            raise ValueError("EMBEDDING_BUNDLE_PUBLICATION_INPUT_CHANGED")
    if (
        len(raw) != before.st_size
        or _epoch(os.fstat(0)) != _epoch(before)
        or "sha256:" + hashlib.sha256(raw).hexdigest() != expected_bundle_raw_sha256
    ):
        raise ValueError("EMBEDDING_BUNDLE_PUBLICATION_INPUT_CHANGED")

    from eom_catalog_contracts.embedding_runtime_bundle import (
        embedding_runtime_bundle_bytes,
        parse_embedding_runtime_bundle,
    )
    from eom_identifiers import canonical_json_bytes

    from eom_orchestrator.control_artifacts import ControlArtifactPublisher
    from eom_orchestrator.database import build_engine
    from eom_orchestrator.embedding_runtime_bundle_artifacts import (
        EmbeddingRuntimeBundleArtifactPublisher,
    )
    from eom_orchestrator.settings import Settings

    bundle = parse_embedding_runtime_bundle(json.loads(raw))
    if embedding_runtime_bundle_bytes(bundle) != raw:
        raise ValueError("EMBEDDING_BUNDLE_PUBLICATION_INPUT_INVALID")
    if _epoch(os.fstat(0)) != _epoch(before) or _epoch(_descriptor(1, output=True)) != _epoch(
        output
    ):
        raise ValueError("EMBEDDING_BUNDLE_PUBLICATION_HANDOFF_CHANGED")
    engine = build_engine()
    try:
        published = EmbeddingRuntimeBundleArtifactPublisher(
            ControlArtifactPublisher(engine, Settings.from_environment()),
            source_commit=source_commit,
        ).publish(bundle, created_at=datetime.now(UTC))
    finally:
        engine.dispose()
    if _epoch(os.fstat(0)) != _epoch(before) or _epoch(_descriptor(1, output=True)) != _epoch(
        output
    ):
        raise ValueError("EMBEDDING_BUNDLE_PUBLICATION_HANDOFF_CHANGED")
    payload = canonical_json_bytes(
        {
            "owner_job_id": published.owner_job_id,
            "bundle": published.bundle.model_dump(mode="json"),
            "manifest_sha256": published.manifest_sha256,
        }
    )
    remaining = memoryview(payload)
    while remaining:
        count = os.write(1, remaining)
        if not 0 < count <= len(remaining):
            raise ValueError("EMBEDDING_BUNDLE_PUBLICATION_OUTPUT_FAILED")
        remaining = remaining[count:]
    os.fsync(1)
    final = os.fstat(1)
    if (
        _epoch(final)[:6] != _epoch(output)[:6]
        or final.st_size != len(payload)
        or os.lseek(1, 0, os.SEEK_CUR) != len(payload)
        or _epoch(os.fstat(0)) != _epoch(before)
    ):
        raise ValueError("EMBEDDING_BUNDLE_PUBLICATION_OUTPUT_CHANGED")


def main() -> int:
    try:
        if len(sys.argv) != 3:
            raise ValueError("EMBEDDING_BUNDLE_PUBLICATION_ARGUMENTS_INVALID")
        publish_installation_bundle(sys.argv[1], sys.argv[2])
        return 0
    except Exception:
        # A failed receipt write can follow a real commit. Preserve history and replay same key.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
