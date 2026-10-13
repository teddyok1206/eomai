"""Opt-in real UID/DAC handoff using only test-owned files; no DB/NAS/model call."""

from __future__ import annotations

import os
import pwd
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from eom_catalog_service.embedding_encoder_adapter import encode_incremental_batch
from eom_identifiers import canonical_json_bytes
from eom_orchestrator import native_embedding_index_handoff as handoff

from tests.unit.local_embedding_admission_fixtures import native_fixture
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend

pytestmark = pytest.mark.privileged


@contextmanager
def effective_identity(name: str) -> Iterator[None]:
    account = pwd.getpwnam(name)
    uid, gid, groups = os.geteuid(), os.getegid(), os.getgroups()
    assert uid == 0
    os.setgroups([account.pw_gid])
    os.setegid(account.pw_gid)
    os.seteuid(account.pw_uid)
    try:
        yield
    finally:
        os.seteuid(uid)
        os.setegid(gid)
        os.setgroups(groups)


@pytest.fixture
def materialized(monkeypatch: pytest.MonkeyPatch) -> Iterator[handoff.PreparedNativeIndex]:
    if os.environ.get("EOM_RUN_NATIVE_INDEX_HANDOFF_PRIVILEGED") != "1":
        pytest.skip("explicit native handoff OS gate required")
    assert os.geteuid() == 0
    owner = pwd.getpwnam("eom-workflow-runner")
    with tempfile.TemporaryDirectory(prefix="eom-native-index-os-") as directory:
        root = Path(directory)
        root.chmod(0o755)
        stage, runtime = root / "owner", root / "runtime"
        stage.mkdir(mode=0o700)
        os.chown(stage, owner.pw_uid, owner.pw_gid)
        runtime.mkdir(mode=0o750)
        os.chown(runtime, 0, owner.pw_gid)
        monkeypatch.setattr(handoff, "OWNER_ROOT", stage)
        monkeypatch.setattr(handoff, "RUNTIME_ROOT", runtime)
        fixture = native_fixture()
        prepared = handoff.PreparedNativeIndex("b" * 32, fixture.association, fixture.native_input)
        with effective_identity("eom-workflow-runner"):
            handoff.stage_native_index(prepared)
            handoff.mark_native_index_launch_started(prepared)
        handoff.prepare_native_index_handoff(prepared.execution_id)
        yield prepared


def test_actual_root_modes_and_owner_worker_dac(materialized: handoff.PreparedNativeIndex) -> None:
    directory = handoff.RUNTIME_ROOT / materialized.execution_id
    for name, mode in (("input.json", 0o600), ("result.json", 0o640), ("vectors.f32", 0o640)):
        value = (directory / name).stat()
        assert value.st_uid == 0 and value.st_nlink == 1 and value.st_mode & 0o777 == mode
    with effective_identity("eom-workflow-runner"):
        with pytest.raises(PermissionError):
            (directory / "input.json").read_bytes()
        assert (directory / "result.json").read_bytes() == b""
        with pytest.raises(PermissionError):
            (directory / "result.json").write_bytes(b"bad")
    with effective_identity("eom-embedding-index-cpu"):
        with pytest.raises(PermissionError):
            (directory / "input.json").read_bytes()
        with pytest.raises(PermissionError):
            (materialized.workspace / "input.json").read_bytes()


def test_root_handoff_cannot_recreate_or_overwrite(
    materialized: handoff.PreparedNativeIndex,
) -> None:
    original = (handoff.RUNTIME_ROOT / materialized.execution_id / "input.json").stat().st_ino
    with pytest.raises(handoff.NativeIndexHandoffError, match="HANDOFF_EXISTS"):
        handoff.prepare_native_index_handoff(materialized.execution_id)
    assert (
        handoff.RUNTIME_ROOT / materialized.execution_id / "input.json"
    ).stat().st_ino == original


def test_real_owner_reads_valid_binary_and_preserves_root_result(
    materialized: handoff.PreparedNativeIndex,
) -> None:
    backend = SyntheticNativeBackend(materialized.request.space)
    backend.batch_size = backend.threads = 4
    encoded = encode_incremental_batch(materialized.request, backend)
    directory = handoff.RUNTIME_ROOT / materialized.execution_id
    for name, raw in (
        ("result.json", canonical_json_bytes(encoded.result.model_dump(mode="json"))),
        ("vectors.f32", encoded.vectors),
    ):
        # Root simulates completed worker descriptors; no ML backend is loaded.
        with (directory / name).open("wb") as output:
            output.write(raw)
    with effective_identity("eom-workflow-runner"):
        assert handoff.materialize_native_index_output(materialized) == encoded.result
        assert (materialized.workspace / "vectors.f32").read_bytes() == encoded.vectors
    assert (directory / "vectors.f32").read_bytes() == encoded.vectors
