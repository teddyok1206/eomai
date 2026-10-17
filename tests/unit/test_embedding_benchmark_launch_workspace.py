"""Actual private temporary files; authorization/owner selection is explicitly synthetic."""

import os
import time

import pytest
from eom_orchestrator import embedding_benchmark_launch_workspace as stage
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkLaunchAuthorization
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity

from tests.unit.embedding_device_benchmark_fixtures import (
    owner_request,
    staged_inputs,
    worker_invocation,
)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "owner"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(stage, "BENCHMARK_OWNER_ROOT", root)
    monkeypatch.setattr(
        stage, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.getuid(), os.getgid())
    )
    calls = []
    monkeypatch.setattr(
        BenchmarkLaunchAuthorization, "assert_invocation", lambda _self, value: calls.append(value)
    )
    return root, object.__new__(BenchmarkLaunchAuthorization), calls


@pytest.mark.parametrize("ordinal", range(1, 7))
def test_original_stage_is_canonical_pinned_and_exact_replay_does_not_overwrite(workspace, ordinal):
    root, authorization, calls = workspace
    invocation = worker_invocation(ordinal)
    expires = time.monotonic_ns() + 60 * 10**9
    original = stage.stage_owner_benchmark_launch(
        owner_request(),
        invocation,
        staged_inputs(),
        authorization=authorization,
        expires_ns=expires,
    )
    assert (
        stage.read_owner_benchmark_launch(invocation.execution_id, expected=original.association)
        == original
    )
    location = root / invocation.execution_id / "inputs" / "association.json"
    inode = location.stat().st_ino
    replay = stage.stage_owner_benchmark_launch(
        owner_request(),
        invocation,
        staged_inputs(),
        authorization=authorization,
        expires_ns=expires,
    )
    assert replay == original and location.stat().st_ino == inode
    assert calls == [invocation] * 4


@pytest.mark.parametrize("fault", ("missing", "extra", "hash", "mode", "symlink"))
def test_missing_replaced_or_corrupt_input_is_not_resolved_or_repaired(workspace, fault):
    root, authorization, _ = workspace
    invocation = worker_invocation(4)
    original = stage.stage_owner_benchmark_launch(
        owner_request(),
        invocation,
        staged_inputs(),
        authorization=authorization,
        expires_ns=time.monotonic_ns() + 60 * 10**9,
    )
    location = root / invocation.execution_id / "inputs" / "benchmark-inputs.json"
    if fault == "missing":
        location.unlink()
    elif fault == "extra":
        (location.parent / "unexpected").write_bytes(b"unexpected")
    elif fault == "hash":
        location.write_bytes(b"{}")
    elif fault == "mode":
        location.chmod(0o644)
    else:
        location.rename(location.parent / "original")
        location.symlink_to("original")
    with pytest.raises((ValueError, RuntimeError)):
        stage.read_owner_benchmark_launch(invocation.execution_id, expected=original.association)


def test_revocation_happens_before_staging_and_path_is_not_worker_selected(workspace, monkeypatch):
    root, authorization, _ = workspace

    def revoked(*_):
        raise ValueError("synthetic source revoked")

    monkeypatch.setattr(BenchmarkLaunchAuthorization, "assert_invocation", revoked)
    with pytest.raises(ValueError, match="revoked"):
        stage.stage_owner_benchmark_launch(
            owner_request(),
            worker_invocation(),
            staged_inputs(),
            authorization=authorization,
            expires_ns=time.monotonic_ns() + 60 * 10**9,
        )
    assert not tuple(root.iterdir())
    for value in ("../escape", "a" * 31, True, "embeddingexecution_" + "a" * 32):
        with pytest.raises(ValueError):
            stage.read_owner_benchmark_launch(value)
