"""Temporary staging and explicit synthetic root-read seam; no OS/root acceptance."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_service.embedding_encoder_adapter import encode_incremental_batch
from eom_identifiers import canonical_json_bytes
from eom_orchestrator import native_embedding_index_handoff as handoff
from eom_orchestrator.inference_transfer_cpu_handoff import (
    CpuHandoffError,
    CpuHandoffIdentity,
    protected_cpu_handoff_directory,
    read_protected_cpu_handoff_member,
)
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.local_embedding_admission_fixtures import native_fixture
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend


def prepared() -> handoff.PreparedNativeIndex:
    fixture = native_fixture()
    return handoff.PreparedNativeIndex("a" * 32, fixture.association, fixture.native_input)


@pytest.fixture
def staged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> handoff.PreparedNativeIndex:
    owner_root = tmp_path / "owner"
    owner_root.mkdir(mode=0o700)
    monkeypatch.setattr(handoff, "OWNER_ROOT", owner_root)
    monkeypatch.setattr(handoff, "RUNTIME_ROOT", tmp_path / "runtime")
    monkeypatch.setattr(
        handoff, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.geteuid(), os.getegid())
    )
    value = prepared()
    handoff.stage_native_index(value)
    return value


def synthetic_output(
    staged: handoff.PreparedNativeIndex,
    monkeypatch: pytest.MonkeyPatch,
) -> bytes:
    # Translate root ownership only at the unit test's read boundary. Real
    # root/owner/worker isolation is independently exercised by privileged tests.
    actual_uid = os.geteuid()

    def directory(path: Path, **values: Any) -> Any:
        if values["uid"] == 0:
            values["uid"] = actual_uid
        return protected_cpu_handoff_directory(path, **values)

    def read(fd: int, name: str, **values: Any) -> bytes:
        if values["uid"] == 0:
            values["uid"] = actual_uid
        return read_protected_cpu_handoff_member(fd, name, **values)

    monkeypatch.setattr(handoff, "protected_cpu_handoff_directory", directory)
    monkeypatch.setattr(handoff, "read_protected_cpu_handoff_member", read)
    handoff.RUNTIME_ROOT.mkdir(mode=0o700)
    root = handoff.RUNTIME_ROOT / staged.execution_id
    root.mkdir(mode=0o750)
    root.chmod(0o750)
    backend = SyntheticNativeBackend(staged.request.space)
    backend.batch_size = backend.threads = 4
    encoded = encode_incremental_batch(staged.request, backend)
    for name, raw in (
        ("result.json", canonical_json_bytes(encoded.result.model_dump(mode="json"))),
        ("vectors.f32", encoded.vectors),
    ):
        path = root / name
        path.write_bytes(raw)
        path.chmod(0o640)
    return encoded.vectors


@pytest.mark.parametrize("value", ["", "../a", "A" * 32, "a" * 31, "a" * 33, "a" * 32 + ".service"])
def test_execution_id_cannot_select_other_paths(value: str) -> None:
    with pytest.raises(ValueError, match="EXECUTION_ID_INVALID"):
        handoff.validate_native_index_execution_id(value)


def test_staging_is_exact_idempotent_and_marker_is_separate(
    staged: handoff.PreparedNativeIndex,
) -> None:
    first = (staged.workspace / "input.json").stat().st_ino
    handoff.stage_native_index(staged)
    assert (staged.workspace / "input.json").stat().st_ino == first
    assert not (staged.workspace / ".launch-started").exists()
    handoff.mark_native_index_launch_started(staged)
    handoff.mark_native_index_launch_started(staged)
    assert (
        staged.workspace / ".launch-started"
    ).read_bytes() == staged.association.association_sha256.encode("ascii")


def test_partial_staging_cannot_be_overwritten(staged: handoff.PreparedNativeIndex) -> None:
    (staged.workspace / "input.json").write_bytes(b"{")
    with pytest.raises(ValueError, match="MEMBER_CONFLICT"):
        handoff.stage_native_index(staged)
    assert (staged.workspace / "input.json").read_bytes() == b"{"


def test_normal_owner_cannot_execute_root_prepare(staged: handoff.PreparedNativeIndex) -> None:
    assert os.geteuid() != 0
    with pytest.raises(ValueError, match="ROOT_REQUIRED"):
        handoff.prepare_native_index_handoff(staged.execution_id)


def test_valid_result_materializes_once_and_same_output_can_replay(
    staged: handoff.PreparedNativeIndex,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = synthetic_output(staged, monkeypatch)
    first = handoff.materialize_native_index_output(staged)
    inode = (staged.workspace / "vectors.f32").stat().st_ino
    assert handoff.materialize_native_index_output(staged) == first
    assert (staged.workspace / "vectors.f32").stat().st_ino == inode
    assert (staged.workspace / "vectors.f32").read_bytes() == binary
    assert first.request_sha256 == staged.request.request_sha256


@pytest.mark.parametrize("failure", ["hash", "mode", "symlink", "input_changed"])
def test_invalid_output_or_changed_input_never_materializes_success(
    staged: handoff.PreparedNativeIndex,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    synthetic_output(staged, monkeypatch)
    path = handoff.RUNTIME_ROOT / staged.execution_id / "vectors.f32"
    if failure == "hash":
        path.write_bytes(b"\x00" * path.stat().st_size)
    elif failure == "mode":
        path.chmod(0o644)
    elif failure == "symlink":
        path.rename(path.with_name("original.f32"))
        path.symlink_to(path.with_name("original.f32"))
    else:
        (staged.workspace / "input.json").write_bytes(b"{}")
    with pytest.raises((ValueError, CpuHandoffError, SchemaError)):
        handoff.materialize_native_index_output(staged)
    assert not (staged.workspace / "result.json").exists()


def test_public_reader_rejects_path_traversal_and_bounds_before_read(
    staged: handoff.PreparedNativeIndex,
) -> None:
    with protected_cpu_handoff_directory(
        staged.workspace,
        owner=CpuHandoffIdentity(os.geteuid(), os.getegid()),
        uid=os.geteuid(),
        gid=os.getegid(),
        mode=0o700,
    ) as directory:
        for name in ("../input.json", "/tmp/a", "..", "a\\b"):
            with pytest.raises(CpuHandoffError):
                read_protected_cpu_handoff_member(directory, name, uid=os.geteuid(), mode=0o600)
        with pytest.raises(CpuHandoffError):
            read_protected_cpu_handoff_member(
                directory, "input.json", uid=os.geteuid(), mode=0o600, maximum_bytes=1
            )
