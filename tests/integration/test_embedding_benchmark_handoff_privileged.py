"""Opt-in real DAC/ACL only, private /run fixtures; no Job/DB/NAS/GPU/model admission."""

from __future__ import annotations

import os
import pwd
import tempfile
from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_device_benchmark import benchmark_sample_program
from eom_catalog_service import embedding_benchmark_handoff as handoff
from eom_catalog_service import embedding_device_benchmark_files as capture
from eom_catalog_service.embedding_device_benchmark_files import BenchmarkWorkerLocalFiles
from eom_catalog_service.embedding_runtime_files import fixed_native_embedding_profile

from tests.unit.embedding_device_benchmark_fixtures import (
    owner_request,
    staged_inputs,
    worker_invocation,
)

pytestmark = pytest.mark.privileged


@pytest.mark.parametrize("ordinal", range(1, 7))
def test_real_native_uid_uses_inherited_input_and_only_precreated_outputs(
    monkeypatch: pytest.MonkeyPatch, ordinal: int
) -> None:
    if os.environ.get("EOM_RUN_BENCHMARK_HANDOFF_PRIVILEGED") != "1":
        pytest.skip("explicit private benchmark filesystem OS gate required")
    assert os.geteuid() == 0
    invocation = worker_invocation(ordinal)
    native = pwd.getpwnam(fixed_native_embedding_profile(invocation.runtime.profile).worker_user)
    other = pwd.getpwnam(
        "eom-embedding-cuda" if invocation.device == "CPU" else "eom-embedding-index-cpu"
    )
    with tempfile.TemporaryDirectory(prefix="eom-benchmark-handoff-os-", dir="/run") as directory:
        parent = Path(directory)
        parent.chmod(0o711)
        root = parent / "benchmark"
        root.mkdir(mode=0o711)
        root.chmod(0o711)
        monkeypatch.setattr(handoff, "_HANDOFF_ROOT", root)
        monkeypatch.setattr(capture, "_HANDOFF_ROOT", root)
        prepared = handoff.prepare_benchmark_handoff(owner_request(), invocation, staged_inputs())
        execution = root / invocation.execution_id
        borrowed = os.open(execution / "invocation.json", os.O_RDONLY | os.O_CLOEXEC)
        try:
            for account in (native, other):
                child = os.fork()
                if child == 0:
                    try:
                        os.setgroups([])
                        os.setgid(account.pw_gid)
                        os.setuid(account.pw_uid)
                        assert os.getuid() == os.geteuid() == account.pw_uid != 0
                        assert not os.getgroups()
                        with pytest.raises(PermissionError):
                            os.listdir(root)
                        with pytest.raises(PermissionError):
                            (execution / "invocation.json").read_bytes()
                        with pytest.raises(PermissionError):
                            (execution / "inputs/benchmark-inputs.json").open("wb")
                        with pytest.raises(PermissionError):
                            (execution / "outputs/extra.json").touch()
                        if account == other:
                            with pytest.raises(PermissionError):
                                os.listdir(execution)
                        else:
                            with BenchmarkWorkerLocalFiles(
                                borrowed,
                                profile=invocation.runtime.profile,
                                execution_id=invocation.execution_id,
                                invocation_raw_sha256=prepared.invocation_raw_sha256,
                            ) as files:
                                assert files.read_invocation() == invocation
                                assert files.read_inputs(invocation) == staged_inputs()
                                files.write_vectors(
                                    benchmark_sample_program(ordinal)[0], b"\0" * (6 * 4096)
                                )
                                files.assert_current()
                            with pytest.raises(PermissionError):
                                (execution / "outputs/cold-documents.f32").unlink()
                        os._exit(0)
                    except BaseException:
                        os._exit(1)
                _, status = os.waitpid(child, 0)
                assert os.waitstatus_to_exitcode(status) == 0
            assert os.lseek(borrowed, 0, os.SEEK_CUR) == 0
            assert (execution / "outputs/cold-documents.f32").stat().st_size == 6 * 4096
        finally:
            os.close(borrowed)
