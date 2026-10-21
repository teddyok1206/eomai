"""Opt-in private root/owner/native DAC proof boundary; machine/PID1 claims are synthetic."""

from __future__ import annotations

import os
import pwd
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest
from eom_catalog_service import embedding_benchmark_handoff as handoff
from eom_catalog_service import embedding_benchmark_prelaunch_inspection as inspection
from eom_catalog_service import embedding_device_benchmark_files as local_files
from eom_workflow.embedding_benchmark_launch_control import (
    BenchmarkLaunchAssociation,
    benchmark_launch_control_bytes,
)

from tests.unit.embedding_benchmark_control_fixtures import association, uncertain
from tests.unit.embedding_benchmark_prelaunch_failure_fixtures import observation
from tests.unit.embedding_device_benchmark_fixtures import (
    owner_request,
    staged_inputs,
    worker_invocation,
)
from tests.unit.inference_transfer_embedding_fixtures import seal

pytestmark = pytest.mark.privileged


def test_actual_owner_captures_only_root_produced_proof_without_question_read(monkeypatch):
    """No service/Job/DB/NAS/model/auth; only newly created private /run test paths."""
    if os.environ.get("EOM_RUN_BENCHMARK_PRELAUNCH_PROOF_PRIVILEGED") != "1":
        pytest.skip("explicit private restricted-root proof filesystem gate required")
    assert os.getresuid() == (0, 0, 0) and os.getresgid() == (0, 0, 0)
    fields = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    assert fields["NoNewPrivs"].strip() == "1"
    assert int(fields["CapEff"].strip(), 16) & (1 << 2)  # DAC_READ_SEARCH, never write bypass.
    assert not int(fields["CapEff"].strip(), 16) & (1 << 1)
    owner = pwd.getpwnam("eom-workflow-runner")
    native = pwd.getpwnam("eom-embedding-index-cpu")
    assert owner.pw_uid != native.pw_uid and owner.pw_uid > 0 and native.pw_uid > 0

    @dataclass(frozen=True)
    class MachineObservation:
        boot_id: str = "00000000-0000-0000-0000-000000000001"

        def snapshot_value(self):
            return {"boot_id": self.boot_id, "synthetic_machine": True}

    class Machine:
        def __init__(self, *_args, **_kwargs):
            pass

        def observe(self):
            return MachineObservation()

    # Real OS/machine drift tests belong to the separate observer suite. This fixture
    # deliberately grants no actual failed-controller or never-started-unit assertion.
    monkeypatch.setattr(inspection, "CapturedBenchmarkPrelaunchMachine", Machine)
    monkeypatch.setattr(
        local_files.BenchmarkRootStagedFiles,
        "read_inputs",
        lambda *_a: pytest.fail("no question text read"),
    )
    request, invocation = owner_request(), worker_invocation(1)
    with tempfile.TemporaryDirectory(prefix="eom-prelaunch-proof-dac-", dir="/run") as temporary:
        parent = Path(temporary)
        os.chown(parent, 0, owner.pw_gid)
        parent.chmod(0o750)
        handoff_root = parent / "benchmark"
        handoff_root.mkdir(mode=0o711)
        recovery = parent / "recovery"
        recovery.mkdir(mode=0o750)
        os.chown(recovery, 0, owner.pw_gid)
        owner_root = parent / "owner"
        workspace = owner_root / invocation.execution_id
        owner_inputs = workspace / "inputs"
        owner_inputs.mkdir(parents=True, mode=0o700)
        body = association().model_dump(mode="json", exclude={"association_sha256"})
        body.update(owner_pid=2**30, expires_ns=1)
        associated = BenchmarkLaunchAssociation.model_validate(seal(body, "association_sha256"))
        member = owner_inputs / "association.json"
        member.write_bytes(benchmark_launch_control_bytes(associated))
        member.chmod(0o600)
        os.chown(member, owner.pw_uid, owner.pw_gid)
        for directory in (owner_inputs, workspace, owner_root):
            directory.chmod(0o700)
            os.chown(directory, owner.pw_uid, owner.pw_gid)
        monkeypatch.setattr(handoff, "_HANDOFF_ROOT", handoff_root)
        monkeypatch.setattr(local_files, "_HANDOFF_ROOT", handoff_root)
        monkeypatch.setattr(inspection, "BENCHMARK_HANDOFF_ROOT", handoff_root)
        monkeypatch.setattr(inspection, "BENCHMARK_OWNER_ROOT", owner_root)
        monkeypatch.setattr(inspection, "_PROOF_ROOT", recovery)
        handoff.prepare_benchmark_handoff(request, invocation, staged_inputs())
        execution = handoff_root / invocation.execution_id
        member = execution / "root-uncertain.json"
        member.write_bytes(benchmark_launch_control_bytes(uncertain(associated)))
        os.chown(member, 0, owner.pw_gid)
        member.chmod(0o640)
        for path in (execution / "outputs").iterdir():
            assert path.stat().st_uid == native.pw_uid and path.stat().st_size == 0
        before = inspection._layout_snapshot(invocation)
        minted = inspection.mint_benchmark_prelaunch_observation(
            request, invocation, controller=observation().controller
        )
        proof = recovery / (invocation.execution_id + ".json")
        assert (proof.stat().st_uid, proof.stat().st_gid, proof.stat().st_mode & 0o777) == (
            0,
            owner.pw_gid,
            0o440,
        )

        def owner_child(*, trusted: bool) -> None:
            child = os.fork()
            if child == 0:
                try:
                    os.setgroups([])
                    os.setresgid(owner.pw_gid, owner.pw_gid, owner.pw_gid)
                    os.setresuid(owner.pw_uid, owner.pw_uid, owner.pw_uid)
                    assert not os.getgroups() and os.getresuid() == (owner.pw_uid,) * 3
                    with pytest.raises(PermissionError):
                        (execution / "invocation.json").read_bytes()
                    with pytest.raises(PermissionError):
                        proof.open("wb")
                    with pytest.raises(
                        inspection.BenchmarkPrelaunchInspectionError, match="ROOT_REQUIRED"
                    ):
                        inspection.mint_benchmark_prelaunch_observation(
                            request, invocation, controller=observation().controller
                        )
                    adapter = inspection.FixedBenchmarkPrelaunchInspection(
                        invocation.execution_id, minted.raw_sha256
                    )
                    if trusted:
                        with adapter.capture(request, invocation) as captured:
                            assert captured.observation == minted.observation
                            captured.assert_current()
                    else:
                        with (
                            pytest.raises(inspection.BenchmarkPrelaunchInspectionError),
                            adapter.capture(request, invocation),
                        ):
                            pytest.fail("owner-produced proof is not authority")
                    os._exit(0)
                except BaseException:
                    os._exit(1)
            _, status = os.waitpid(child, 0)
            assert os.waitstatus_to_exitcode(status) == 0

        owner_child(trusted=True)
        assert inspection._layout_snapshot(invocation) == before
        # Same bytes/hash/mode, different producer: the real owner reader must reject it.
        os.chown(proof, owner.pw_uid, owner.pw_gid)
        owner_child(trusted=False)
        assert inspection._layout_snapshot(invocation) == before
