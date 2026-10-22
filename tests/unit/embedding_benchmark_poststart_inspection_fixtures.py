"""Synthetic protected ownership/machine snapshots only; never actual PID1 or root authority."""

from __future__ import annotations

import os
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_benchmark_handoff as handoff
from eom_catalog_service import embedding_benchmark_poststart_inspection as module
from eom_catalog_service.embedding_benchmark_cpu_driver import RootBenchmarkCpuRetirement
from eom_catalog_service.gpu_unit_terminal_observation import StoppedGpuUnit
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation
from eom_orchestrator.worker_systemd import FixedUnitStatus
from eom_workflow.embedding_benchmark_launch_control import (
    BenchmarkLaunchAssociation,
    BenchmarkLaunchCompleted,
    BenchmarkLaunchPrepared,
    benchmark_launch_control_bytes,
)

from tests.unit.embedding_benchmark_control_fixtures import association, completed, prepared
from tests.unit.embedding_benchmark_poststart_failure_fixtures import observation
from tests.unit.embedding_device_benchmark_fixtures import (
    owner_request,
    staged_inputs,
    worker_invocation,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_handoff import synthetic_root


@pytest.fixture
def staged_poststart(tmp_path, monkeypatch):
    root = synthetic_root(tmp_path, monkeypatch)
    request, invocation = owner_request(), worker_invocation(1)
    handoff.prepare_benchmark_handoff(request, invocation, staged_inputs())
    owner_root = tmp_path / "owner"
    owner_inputs = owner_root / invocation.execution_id / "inputs"
    owner_inputs.mkdir(parents=True, mode=0o700)
    for directory in (owner_root, owner_inputs.parent, owner_inputs):
        directory.chmod(0o700)
    body = association().model_dump(mode="json")
    body.update(owner_pid=2**30, expires_ns=1)
    associated = BenchmarkLaunchAssociation.model_validate(seal(body, "association_sha256"))
    path = owner_inputs / "association.json"
    path.write_bytes(benchmark_launch_control_bytes(associated))
    path.chmod(0o600)
    controller = observation().controller
    body = prepared(associated).model_dump(mode="json")
    body["controller_release"] = controller.source_commit
    before = BenchmarkLaunchPrepared.model_validate(seal(body, "prepared_sha256"))
    body = completed(associated, before).model_dump(mode="json")
    body.update(original_outcome="FAILED", started_ns=100000, completed_ns=300000)
    complete = BenchmarkLaunchCompleted.model_validate(seal(body, "completion_sha256"))
    execution = root / invocation.execution_id
    for name, value in (("root-prepared.json", before), ("root-completion.json", complete)):
        path = execution / name
        path.write_bytes(benchmark_launch_control_bytes(value))
        path.chmod(0o640)
    (execution / "outputs/cold-documents.f32").write_bytes(b"synthetic partial bytes")
    proof_root = tmp_path / "poststart-proof"
    proof_root.mkdir(mode=0o750)
    proof_root.chmod(0o750)
    for name, value in (
        ("BENCHMARK_HANDOFF_ROOT", root),
        ("BENCHMARK_OWNER_ROOT", owner_root),
        ("_PROOF_ROOT", proof_root),
        ("_ROOT_UID", os.getuid()),
        ("_ROOT_GID", os.getgid()),
    ):
        monkeypatch.setattr(module, name, value)
    monkeypatch.setattr(
        module, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.getuid(), os.getgid())
    )
    state = {
        "boot": "00000000-0000-0000-0000-000000000001",
        "epoch": 1,
        "retired": 1,
        "root_reads": 0,
        "controller_start_us": 50,
        "controller_end_us": 350,
    }

    @dataclass(frozen=True)
    class MachineObservation:
        boot_id: str
        epoch: int
        controller: tuple[tuple[str, str], ...]

        def snapshot_value(self):
            return {
                "boot_id": self.boot_id,
                "epoch": self.epoch,
                "controller": dict(self.controller),
            }

    class Machine:
        def __init__(
            self, _controller, *, execution_id, native_invocation_id, owner_pid, expires_ns
        ):
            assert execution_id == invocation.execution_id and native_invocation_id == "c" * 32
            assert owner_pid == 2**30 and expires_ns == 1

        def observe(self):
            return MachineObservation(
                state["boot"],
                state["epoch"],
                (
                    ("ExecMainStartTimestampMonotonic", str(state["controller_start_us"])),
                    ("ExecMainExitTimestampMonotonic", str(state["controller_end_us"])),
                ),
            )

    original = CpuUnitObservation(
        FixedUnitStatus("loaded", "failed", "failed", "timeout", 2, 15, 150, False),
        0,
        200,
        "c" * 32,
        "/etc/systemd/system/" + "eom-embedding-benchmark-cpu@.service",
        "",
    )
    retirement = RootBenchmarkCpuRetirement(
        original, StoppedGpuUnit("loaded", "", 0), "2026-10-22T12:00:00Z"
    )

    class RootRetirement:
        native_invocation_id = "c" * 32
        raw_sha256 = observation().terminal.retirement_raw_sha256

        def __init__(self):
            self.retirement = retirement

        def assert_current(self):
            assert state["retired"] == 1

    def retired(_request, _invocation):
        state["root_reads"] += 1
        return RootRetirement()

    monkeypatch.setattr(module, "CapturedBenchmarkPoststartMachine", Machine)
    monkeypatch.setattr(module, "read_root_poststart_retirement", retired)
    return SimpleNamespace(
        request=request,
        invocation=invocation,
        controller=controller,
        execution=execution,
        proof=proof_root / (invocation.execution_id + ".json"),
        association=owner_inputs / "association.json",
        state=state,
        retirement=retirement,
        root=root,
        owner_root=owner_root,
    )
