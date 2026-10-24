"""Opt-in real root DAC/concurrency in private /run fixtures; no DB/NAS/unit/model calls."""

from __future__ import annotations

import os
import pwd
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_gpu_control import embedding_gpu_control_bytes
from eom_catalog_service import embedding_gpu_batch_handoff as handoff
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffError

from tests.unit.test_embedding_gpu_batch_launch import launch_pins
from tests.unit.test_embedding_gpu_control import control_case

pytestmark = pytest.mark.privileged


@pytest.fixture
def materialized(monkeypatch):
    if os.environ.get("EOM_RUN_GPU_BATCH_HANDOFF_PRIVILEGED") != "1":
        pytest.skip("explicit test-owned root filesystem gate required")
    assert os.getresuid() == (0, 0, 0)
    account = pwd.getpwnam("eom-workflow-runner")
    with tempfile.TemporaryDirectory(prefix="eom-gpu-batch-os-", dir="/run") as directory:
        root = Path(directory) / "runtime"
        root.mkdir(mode=0o750)
        os.chown(root, 0, account.pw_gid)
        monkeypatch.setattr(handoff, "GPU_BATCH_RUNTIME_ROOT", root)
        case = control_case(expires_ns=time.monotonic_ns() + 30 * 10**9)
        pins = replace(
            launch_pins(),
            root_pid=os.getpid(),
            allocation_raw_sha256=sha256_bytes(embedding_gpu_control_bytes(case[0])),
            resource_profile_sha256=case[6].resource_profile_sha256,
        )
        prepared = handoff.prepare_embedding_gpu_batch_handoff(pins, case[0])
        yield prepared, case, root / pins.attempt_hex


def test_original_root_modes_and_same_inherited_empty_inode_is_filled_once(
    materialized, monkeypatch
):
    prepared, case, directory = materialized
    for name, mode in (
        ("allocation.json", 0o600),
        ("launch.env", 0o600),
        ("input.json", 0o600),
        ("result.json", 0o640),
        ("vectors.f32", 0o640),
    ):
        value = (directory / name).stat()
        assert value.st_uid == 0 and value.st_nlink == 1 and value.st_mode & 0o777 == mode
    inherited = os.open(directory / "input.json", os.O_RDONLY | os.O_CLOEXEC)
    try:
        initial = os.fstat(inherited)
        assert initial.st_size == 0
        handoff.bind_embedding_gpu_batch_handoff(prepared, case[3], case[6])
        raw = canonical_json_bytes(case[6].model_dump(mode="json"))
        assert os.fstat(inherited).st_ino == initial.st_ino
        assert os.lseek(inherited, 0, os.SEEK_CUR) == 0
        assert os.read(inherited, len(raw) + 1) == raw
        before = (directory / "input.json").stat()
        handoff.bind_embedding_gpu_batch_handoff(prepared, case[3], case[6])
        after = (directory / "input.json").stat()
        assert (before.st_ino, before.st_mtime_ns, before.st_ctime_ns) == (
            after.st_ino,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
    finally:
        os.close(inherited)


def test_original_attempt_cannot_be_recreated_or_clobbered(materialized):
    prepared, case, directory = materialized
    inode = (directory / "input.json").stat().st_ino
    with pytest.raises(CpuHandoffError, match="HANDOFF_EXISTS"):
        handoff.prepare_embedding_gpu_batch_handoff(prepared.launch, case[0])
    assert (directory / "input.json").stat().st_ino == inode


def test_partial_write_and_intent_are_preserved_without_automatic_repair(materialized, monkeypatch):
    prepared, case, directory = materialized
    write = os.write
    inode = (directory / "input.json").stat().st_ino

    def broken(fd, payload):
        if os.fstat(fd).st_ino == inode:
            write(fd, payload[:7])
            raise OSError("synthetic original input write failure")
        return write(fd, payload)

    monkeypatch.setattr(os, "write", broken)
    # Existing protected-directory adapter deliberately translates body IO errors.
    with pytest.raises(CpuHandoffError) as error:
        handoff.bind_embedding_gpu_batch_handoff(prepared, case[3], case[6])
    assert isinstance(error.value.__cause__, OSError)
    original = (directory / "input.json").read_bytes()
    assert len(original) == 7 and (directory / "input-grant.json").exists()
    with pytest.raises(ValueError):
        handoff.bind_embedding_gpu_batch_handoff(prepared, case[3], case[6])
    assert (directory / "input.json").read_bytes() == original
    assert (directory / "input.json").stat().st_ino == inode


def test_concurrent_binding_has_one_writer_and_exact_completed_replay(materialized, monkeypatch):
    prepared, case, directory = materialized
    inode = (directory / "input.json").stat().st_ino
    writes = []
    write = os.write

    def tracked(fd, payload):
        if os.fstat(fd).st_ino == inode:
            writes.append(len(payload))
        return write(fd, payload)

    monkeypatch.setattr(os, "write", tracked)

    def bind():
        try:
            handoff.bind_embedding_gpu_batch_handoff(prepared, case[3], case[6])
            return "EXACT"
        except (ValueError, CpuHandoffError):
            return "ORIGINAL_IN_PROGRESS_OR_UNCERTAIN"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: bind(), range(2)))
    assert "EXACT" in outcomes
    raw = canonical_json_bytes(case[6].model_dump(mode="json"))
    assert writes == [len(raw)] and (directory / "input.json").read_bytes() == raw
    handoff.bind_embedding_gpu_batch_handoff(prepared, case[3], case[6])
    assert writes == [len(raw)]


def test_forged_grant_does_not_create_intent_or_write_numerical_input(materialized):
    prepared, case, directory = materialized
    grant = case[3].model_copy(update={"batch_input_raw_sha256": "sha256:" + "b" * 64})
    with pytest.raises(ValueError):
        handoff.bind_embedding_gpu_batch_handoff(prepared, grant, case[6])
    assert not (directory / "input-grant.json").exists()
    assert (directory / "input.json").read_bytes() == b""


def test_native_worker_cannot_read_staged_paths_but_an_inherited_descriptor_is_readable(
    materialized,
):
    _, _, directory = materialized
    account = pwd.getpwnam("eom-embedding-cuda")
    borrowed = os.open(directory / "allocation.json", os.O_RDONLY | os.O_CLOEXEC)
    child = os.fork()
    if child == 0:
        try:
            os.setgroups([])
            os.setgid(account.pw_gid)
            os.setuid(account.pw_uid)
            for name in ("allocation.json", "input.json", "result.json", "vectors.f32"):
                with pytest.raises(PermissionError):
                    (directory / name).read_bytes()
            assert os.read(borrowed, 32 * 1024)
            os._exit(0)
        except BaseException:
            os._exit(1)
    try:
        _, status = os.waitpid(child, 0)
        assert os.waitstatus_to_exitcode(status) == 0
    finally:
        os.close(borrowed)
