"""Bounded owner CLI tests; actual publication concurrency is tested at the existing owner."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import pwd
import stat
import sys
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_contracts.embedding_runtime_bundle import embedding_runtime_bundle_bytes
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator import database
from eom_orchestrator import embedding_bundle_publication_cli as cli
from eom_orchestrator import embedding_runtime_bundle_artifacts as publisher
from eom_orchestrator.settings import Settings

from tests.unit.embedding_native_runtime_config_fixtures import native_config_metadata


@pytest.mark.parametrize("fault", (None, "root", "uid", "saved_uid", "gid"))
def test_only_existing_unprivileged_artifact_owner_can_invoke(
    monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    monkeypatch.setattr(pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=1234, pw_gid=1235))
    monkeypatch.setattr(os, "getresuid", lambda: (1234, 1234, 1234))
    monkeypatch.setattr(os, "getresgid", lambda: (1235, 1235, 1235))
    if fault in {"root", "uid", "saved_uid"}:
        monkeypatch.setattr(
            os, "getresuid", lambda: (0, 0, 0) if fault == "root" else (1234, 1234, 0)
        )
    elif fault == "gid":
        monkeypatch.setattr(os, "getresgid", lambda: (1235, 1235, 0))
    if fault is None:
        cli._owner()
    else:
        with pytest.raises(ValueError, match="OWNER_REQUIRED"):
            cli._owner()


@dataclass
class Frame:
    raw: bytes
    output: bytes = b""
    position: int = 0
    events: list[str] | None = None

    def value(self, descriptor: int) -> Any:
        return SimpleNamespace(
            st_dev=1,
            st_ino=descriptor + 10,
            st_uid=0,
            st_gid=0,
            st_mode=stat.S_IFREG | 0o600,
            st_nlink=1,
            st_size=len(self.raw) if descriptor == 0 else len(self.output),
            st_mtime_ns=1,
            st_ctime_ns=1,
        )

    def read(self, descriptor: int, maximum: int) -> bytes:
        assert descriptor == 0 and maximum > 0
        block = self.raw[self.position : self.position + min(137, maximum)]
        self.position += len(block)
        return block

    def write(self, descriptor: int, raw: bytes) -> int:
        assert descriptor == 1
        block = bytes(raw[:83])
        self.output += block
        return len(block)


def _io(patch: pytest.MonkeyPatch, frame: Frame) -> None:
    patch.setattr(cli, "_owner", lambda: None)
    patch.setattr(os, "fstat", frame.value)
    patch.setattr(os, "lseek", lambda fd, *_: frame.position if fd == 0 else len(frame.output))
    patch.setattr(fcntl, "fcntl", lambda fd, _: os.O_RDONLY if fd == 0 else os.O_WRONLY)
    patch.setattr(os, "read", frame.read)
    patch.setattr(os, "write", frame.write)
    patch.setattr(os, "fsync", lambda fd: None)


@pytest.mark.parametrize(
    "fault", (None, "hash", "canonical", "output_exists", "publisher", "write")
)
def test_checked_input_precedes_db_and_original_publisher_owns_commit(
    monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    config, bundle, _ = native_config_metadata()
    raw = embedding_runtime_bundle_bytes(bundle)
    if fault == "canonical":
        raw += b"\n"
    frame = Frame(raw, b"existing" if fault == "output_exists" else b"")
    events: list[str] = []
    receipt = SimpleNamespace(
        owner_job_id="job_" + "a" * 32,
        bundle=config.bundle,
        manifest_sha256="sha256:" + "b" * 64,
    )
    engine = SimpleNamespace(dispose=lambda: events.append("dispose"))

    def create() -> Any:
        events.append("engine")
        return engine

    def publish(self: Any, actual: Any, *, created_at: Any) -> Any:
        events.append("publish")
        assert actual == bundle and self.source_commit == "a" * 40
        assert created_at.utcoffset().total_seconds() == 0
        if fault == "publisher":
            raise ValueError("synthetic actual publication failure")
        return receipt

    with monkeypatch.context() as patch:
        _io(patch, frame)
        patch.setattr(database, "build_engine", create)
        patch.setattr(Settings, "from_environment", lambda: Settings())
        patch.setattr(publisher, "ControlArtifactPublisher", lambda *_: object())
        # This is the same class imported by the CLI, not an alternate persistence implementation.
        import eom_orchestrator.control_artifacts as controls

        patch.setattr(controls, "ControlArtifactPublisher", lambda *_: object())
        patch.setattr(publisher.EmbeddingRuntimeBundleArtifactPublisher, "publish", publish)
        if fault == "write":
            patch.setattr(os, "write", lambda *_: 0)
        digest = "sha256:" + ("0" * 64 if fault == "hash" else hashlib.sha256(raw).hexdigest())
        if fault is None:
            cli.publish_installation_bundle("a" * 40, digest)
        else:
            with pytest.raises(ValueError):
                cli.publish_installation_bundle("a" * 40, digest)
    assert events == (
        [] if fault in {"hash", "canonical", "output_exists"} else ["engine", "publish", "dispose"]
    )
    if fault is None:
        expected = {
            "owner_job_id": receipt.owner_job_id,
            "bundle": receipt.bundle.model_dump(mode="json"),
            "manifest_sha256": receipt.manifest_sha256,
        }
        assert json.loads(frame.output) == expected and frame.output == canonical_json_bytes(
            expected
        )
    elif fault != "output_exists":
        assert not frame.output


@pytest.mark.parametrize("output", (False, True))
@pytest.mark.parametrize("fault", ("uid", "mode", "nlink", "type", "size", "position", "flags"))
def test_descriptor_shape_is_root_regular_fresh_bounded_and_directional(
    monkeypatch: pytest.MonkeyPatch, output: bool, fault: str
) -> None:
    frame = Frame(b"{}")
    descriptor = int(output)
    value = frame.value(descriptor)
    if fault in {"uid", "mode", "nlink", "type", "size"}:
        field, changed = {
            "uid": ("st_uid", 1234),
            "mode": ("st_mode", stat.S_IFREG | 0o644),
            "nlink": ("st_nlink", 2),
            "type": ("st_mode", stat.S_IFIFO | 0o600),
            "size": ("st_size", 1 if output else 65537),
        }[fault]
        setattr(value, field, changed)
    with monkeypatch.context() as patch:
        _io(patch, frame)
        patch.setattr(os, "fstat", lambda _: value)
        if fault == "position":
            patch.setattr(os, "lseek", lambda *_: 1)
        elif fault == "flags":
            patch.setattr(fcntl, "fcntl", lambda *_: os.O_RDWR)
        with pytest.raises(ValueError, match="DESCRIPTOR_INVALID"):
            cli._descriptor(descriptor, output=output)


def test_bad_cli_count_is_quiet_and_never_opens_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["fixed-module"])
    monkeypatch.setattr(cli, "_owner", lambda: pytest.fail("not admitted"))
    assert cli.main() == 1


def test_invalid_source_or_independent_pin_never_reads_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "_owner", lambda: None)
    monkeypatch.setattr(cli, "_descriptor", lambda *_args, **_kwargs: pytest.fail("no read"))
    for source, digest in (("latest", sha256_bytes(b"x")), ("a" * 40, "untrusted")):
        with pytest.raises(ValueError, match="PINS_INVALID"):
            cli.publish_installation_bundle(source, digest)
