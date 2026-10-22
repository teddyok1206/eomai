"""Opt-in private root/owner/native DAC only; machine/retirement facts remain synthetic."""

from __future__ import annotations

import os
import pwd
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_benchmark_handoff as handoff
from eom_catalog_service import embedding_benchmark_poststart_inspection as inspection
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

pytestmark = pytest.mark.privileged


def test_actual_owner_can_capture_root_proof_but_not_forge_or_write_it(monkeypatch):
    """No service, DB, NAS, source text, model or authentication; new private /run fixture only."""
    if os.environ.get("EOM_RUN_BENCHMARK_POSTSTART_PROOF_PRIVILEGED") != "1":
        pytest.skip("explicit private restricted-root poststart proof DAC gate required")
    assert os.getresuid() == (0, 0, 0) and os.getresgid() == (0, 0, 0)
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    assert status["NoNewPrivs"].strip() == "1"
    assert int(status["CapEff"].strip(), 16) & (1 << 2)
    assert not int(status["CapEff"].strip(), 16) & (1 << 1)
    owner, native = (
        pwd.getpwnam(name) for name in ("eom-workflow-runner", "eom-embedding-index-cpu")
    )
    assert owner.pw_uid > 0 and native.pw_uid > 0 and owner.pw_uid != native.pw_uid
    request, invocation = owner_request(), worker_invocation(1)
    controller = observation().controller

    @dataclass(frozen=True)
    class MachineObservation:
        boot_id: str = "00000000-0000-0000-0000-000000000001"
        controller: tuple[tuple[str, str], ...] = (
            ("ExecMainStartTimestampMonotonic", "50"),
            ("ExecMainExitTimestampMonotonic", "350"),
        )

        def snapshot_value(self):
            return {
                "boot_id": self.boot_id,
                "synthetic_machine": True,
                "controller": dict(self.controller),
            }

    class Machine:
        def __init__(self, *_args, **_kwargs):
            pass

        def observe(self):
            return MachineObservation()

    monkeypatch.setattr(inspection, "CapturedBenchmarkPoststartMachine", Machine)
    retired = SimpleNamespace(
        native_invocation_id="c" * 32,
        raw_sha256=observation().terminal.retirement_raw_sha256,
        retirement=SimpleNamespace(
            original_terminal=SimpleNamespace(
                status=SimpleNamespace(exec_main_started_monotonic=150), exited_monotonic=200
            )
        ),
        assert_current=lambda: None,
    )
    # OS and original-record semantics are covered independently by the observer tests.
    monkeypatch.setattr(inspection, "read_root_poststart_retirement", lambda *_a: retired)
    with (
        tempfile.TemporaryDirectory(prefix="eom-poststart-proof-dac-", dir="/run") as temporary,
        ExitStack() as cleanup,
    ):
        parent = Path(temporary)
        os.chown(parent, 0, owner.pw_gid)
        parent.chmod(0o750)
        root = parent / "benchmark"
        root.mkdir(mode=0o711)
        proofs = parent / "proofs"
        proofs.mkdir(mode=0o750)
        os.chown(proofs, 0, owner.pw_gid)
        owner_root = parent / "owner"
        owner_inputs = owner_root / invocation.execution_id / "inputs"
        owner_inputs.mkdir(parents=True, mode=0o700)
        for path in (owner_inputs, owner_inputs.parent, owner_root):
            cleanup.callback(path.chmod, 0o700)
            cleanup.callback(os.chown, path, 0, 0)
        body = association().model_dump(mode="json")
        body.update(owner_pid=2**30, expires_ns=1)
        associated = BenchmarkLaunchAssociation.model_validate(seal(body, "association_sha256"))
        path = owner_inputs / "association.json"
        path.write_bytes(benchmark_launch_control_bytes(associated))
        path.chmod(0o600)
        os.chown(path, owner.pw_uid, owner.pw_gid)
        for path in (owner_inputs, owner_inputs.parent, owner_root):
            path.chmod(0o700)
            os.chown(path, owner.pw_uid, owner.pw_gid)
        monkeypatch.setattr(handoff, "_HANDOFF_ROOT", root)
        monkeypatch.setattr(inspection, "BENCHMARK_HANDOFF_ROOT", root)
        monkeypatch.setattr(inspection, "BENCHMARK_OWNER_ROOT", owner_root)
        monkeypatch.setattr(inspection, "_PROOF_ROOT", proofs)
        handoff.prepare_benchmark_handoff(request, invocation, staged_inputs())
        execution = root / invocation.execution_id
        body = prepared(associated).model_dump(mode="json")
        body["controller_release"] = controller.source_commit
        before = BenchmarkLaunchPrepared.model_validate(seal(body, "prepared_sha256"))
        body = completed(associated, before).model_dump(mode="json")
        body.update(original_outcome="FAILED", started_ns=100000, completed_ns=300000)
        complete = BenchmarkLaunchCompleted.model_validate(seal(body, "completion_sha256"))
        for name, value in (("root-prepared.json", before), ("root-completion.json", complete)):
            path = execution / name
            path.write_bytes(benchmark_launch_control_bytes(value))
            path.chmod(0o640)
            os.chown(path, 0, owner.pw_gid)
        partial = execution / "outputs/cold-documents.f32"
        # Temporarily change only this new synthetic file, never a production file.
        os.chown(partial, 0, owner.pw_gid)
        partial.chmod(0o600)
        partial.write_bytes(b"synthetic partial result")
        partial.chmod(0o640)
        os.chown(partial, native.pw_uid, owner.pw_gid)
        result = inspection.mint_benchmark_poststart_observation(
            request, invocation, controller=controller
        )
        proof = proofs / (invocation.execution_id + ".json")
        assert (proof.stat().st_uid, proof.stat().st_gid, proof.stat().st_mode & 0o777) == (
            0,
            owner.pw_gid,
            0o440,
        )
        child = os.fork()
        if child == 0:
            try:
                os.setgroups([])
                os.setresgid(owner.pw_gid, owner.pw_gid, owner.pw_gid)
                os.setresuid(owner.pw_uid, owner.pw_uid, owner.pw_uid)
                assert not os.getgroups()
                with pytest.raises(PermissionError):
                    (execution / "invocation.json").read_bytes()
                with pytest.raises(PermissionError):
                    proof.open("wb")
                with pytest.raises(ValueError, match="ROOT_REQUIRED"):
                    inspection.mint_benchmark_poststart_observation(
                        request, invocation, controller=controller
                    )
                with inspection.FixedBenchmarkPoststartInspection(
                    invocation.execution_id, result.raw_sha256
                ).capture(request, invocation) as captured:
                    assert captured.observation == result.observation
                    captured.assert_current()
                os._exit(0)
            except BaseException:
                os._exit(1)
        assert os.waitpid(child, 0)[1] == 0
        assert proof.read_bytes() and partial.stat().st_size > 0
