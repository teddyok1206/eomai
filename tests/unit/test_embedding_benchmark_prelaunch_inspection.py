"""Synthetic ownership and machine state only; never production/Identity/compute admission."""

from __future__ import annotations

import os
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_benchmark_prelaunch_failure import (
    benchmark_prelaunch_failure_bytes,
)
from eom_catalog_service import embedding_benchmark_handoff as handoff
from eom_catalog_service import embedding_benchmark_prelaunch_inspection as module
from eom_identifiers import sha256_bytes
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity
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
from tests.unit.test_embedding_benchmark_handoff import synthetic_root


@pytest.fixture
def staged(tmp_path, monkeypatch):
    root = synthetic_root(tmp_path, monkeypatch)
    request, invocation = owner_request(), worker_invocation(1)
    handoff.prepare_benchmark_handoff(request, invocation, staged_inputs())
    owner_root = tmp_path / "owner"
    owner_inputs = owner_root / invocation.execution_id / "inputs"
    owner_inputs.mkdir(parents=True, mode=0o700)
    owner_root.chmod(0o700)
    owner_inputs.parent.chmod(0o700)
    body = association().model_dump(mode="json", exclude={"association_sha256"})
    body.update(owner_pid=2**30, expires_ns=1)
    value = BenchmarkLaunchAssociation.model_validate(seal(body, "association_sha256"))
    path = owner_inputs / "association.json"
    path.write_bytes(benchmark_launch_control_bytes(value))
    path.chmod(0o600)
    execution = root / invocation.execution_id
    path = execution / "root-uncertain.json"
    path.write_bytes(benchmark_launch_control_bytes(uncertain(value)))
    path.chmod(0o640)
    proof_root = tmp_path / "recovery"
    proof_root.mkdir(mode=0o750)
    proof_root.chmod(0o750)
    monkeypatch.setattr(module, "BENCHMARK_HANDOFF_ROOT", root)
    monkeypatch.setattr(module, "BENCHMARK_OWNER_ROOT", owner_root)
    monkeypatch.setattr(module, "_PROOF_ROOT", proof_root)
    monkeypatch.setattr(module, "_ROOT_UID", os.getuid())
    monkeypatch.setattr(module, "_ROOT_GID", os.getgid())
    monkeypatch.setattr(
        module, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.getuid(), os.getgid())
    )
    state = {"boot": "00000000-0000-0000-0000-000000000001", "epoch": 1}

    @dataclass(frozen=True)
    class MachineObservation:
        boot_id: str
        epoch: int

        def snapshot_value(self):
            return {"boot_id": self.boot_id, "epoch": self.epoch}

    class Machine:
        def __init__(self, controller, *, execution_id, owner_pid, expires_ns):
            assert (
                execution_id == invocation.execution_id and owner_pid == 2**30 and expires_ns == 1
            )

        def observe(self):
            return MachineObservation(state["boot"], state["epoch"])

    monkeypatch.setattr(module, "CapturedBenchmarkPrelaunchMachine", Machine)
    return SimpleNamespace(
        request=request,
        invocation=invocation,
        controller=observation().controller,
        execution=execution,
        proof=proof_root / (invocation.execution_id + ".json"),
        association=owner_inputs / "association.json",
        state=state,
    )


def mint(fixture):
    return module.mint_benchmark_prelaunch_observation(
        fixture.request, fixture.invocation, controller=fixture.controller
    )


def inspector(fixture, raw_sha256):
    return module.FixedBenchmarkPrelaunchInspection(fixture.invocation.execution_id, raw_sha256)


def test_root_mints_create_once_proof_without_reading_source_text_or_changing_originals(
    staged, monkeypatch
):
    before = module._layout_snapshot(staged.invocation)
    monkeypatch.setattr(
        module.BenchmarkRootStagedFiles,
        "read_inputs",
        lambda *_a: pytest.fail("source question bytes must not be read"),
    )
    original_open = os.open
    output_reads = []

    def opened(path, flags, *args, **kwargs):
        assert not str(path).endswith("benchmark-inputs.json")
        if str(path) in module.benchmark_local_output_members(1):
            output_reads.append(flags & os.O_ACCMODE)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", opened)
    result = mint(staged)
    assert result.created and output_reads == [os.O_RDONLY] * 16
    assert result.raw_sha256 == sha256_bytes(staged.proof.read_bytes())
    assert result.raw_sha256 != result.observation.observation_sha256
    assert staged.proof.stat().st_mode & 0o777 == 0o440
    assert module._layout_snapshot(staged.invocation) == before
    first_epoch = module._epoch(staged.proof.stat())
    replay = mint(staged)
    assert not replay.created and replay.observation == result.observation
    assert replay.raw_sha256 == result.raw_sha256
    assert module._epoch(staged.proof.stat()) == first_epoch
    with inspector(staged, result.raw_sha256).capture(
        staged.request, staged.invocation
    ) as captured:
        assert captured.observation == result.observation
        captured.assert_current()


def test_missing_proof_and_model_supplied_observation_do_not_create_authority(staged):
    with (
        pytest.raises(module.BenchmarkPrelaunchInspectionError),
        inspector(staged, "sha256:" + "0" * 64).capture(staged.request, staged.invocation),
    ):
        pytest.fail("missing proof")
    with pytest.raises(module.BenchmarkPrelaunchInspectionError):
        module.FixedBenchmarkPrelaunchInspection(observation(), "sha256:" + "0" * 64)
    assert not staged.proof.exists()


@pytest.mark.parametrize(
    "fault", ("hash", "mode", "acl", "root_acl", "symlink", "hardlink", "producer", "json")
)
def test_untrusted_proof_identity_and_bytes_fail_closed(staged, monkeypatch, fault):
    result = mint(staged)
    expected = result.raw_sha256
    if fault == "hash":
        expected = "sha256:" + "0" * 64
    elif fault == "mode":
        staged.proof.chmod(0o640)
    elif fault == "acl":
        acl = bytearray(handoff.benchmark_read_acl(os.getuid() + 5, "INPUT"))
        acl[6] = 4  # Preserve exact0440 mode; only the additional named grant differs.
        os.setxattr(
            staged.proof,
            "system.posix_acl_access",
            bytes(acl),
        )
        assert staged.proof.stat().st_mode & 0o777 == 0o440
    elif fault == "root_acl":
        os.setxattr(
            staged.proof.parent,
            "system.posix_acl_default",
            handoff.benchmark_read_acl(os.getuid() + 5, "DIRECTORY"),
        )
    elif fault == "symlink":
        original = staged.proof.with_suffix(".original")
        staged.proof.rename(original)
        staged.proof.symlink_to(original)
    elif fault == "hardlink":
        os.link(staged.proof, staged.proof.with_suffix(".alias"))
    elif fault == "producer":
        inode = staged.proof.stat().st_ino
        original_fstat = os.fstat

        def metadata(fd):
            value = original_fstat(fd)
            if value.st_ino != inode:
                return value
            fields = {name: getattr(value, name) for name in dir(value) if name.startswith("st_")}
            return SimpleNamespace(**(fields | {"st_uid": os.getuid() + 50}))

        monkeypatch.setattr(os, "fstat", metadata)
    else:
        staged.proof.chmod(0o600)
        staged.proof.write_bytes(b"{}")
        staged.proof.chmod(0o440)
        expected = sha256_bytes(b"{}")
    with (
        pytest.raises((ValueError, OSError)),
        inspector(staged, expected).capture(staged.request, staged.invocation),
    ):
        pytest.fail("untrusted proof")


@pytest.mark.parametrize("name", module._ABSENT)
@pytest.mark.parametrize("symlink", (False, True))
def test_any_start_evidence_including_dangling_symlink_prevents_mint(staged, name, symlink):
    path = staged.execution / name
    if symlink:
        path.symlink_to(staged.execution / "does-not-exist")
    else:
        path.touch()
    with pytest.raises(module.BenchmarkPrelaunchInspectionError, match="START_EVIDENCE_PRESENT"):
        mint(staged)
    assert not staged.proof.exists()


@pytest.mark.parametrize("fault", ("uncertainty", "association", "output", "member", "controller"))
def test_original_closure_or_membership_cannot_be_substituted(staged, fault):
    if fault == "uncertainty":
        (staged.execution / "root-uncertain.json").unlink()
    elif fault == "association":
        body = association().model_dump(mode="json", exclude={"association_sha256"})
        body["job_id"] = "job_" + "f" * 32
        staged.association.write_bytes(
            benchmark_launch_control_bytes(
                BenchmarkLaunchAssociation.model_validate(seal(body, "association_sha256"))
            )
        )
    elif fault == "output":
        (staged.execution / "outputs/cold-documents.f32").write_bytes(b"used")
    elif fault == "member":
        (staged.execution / "outputs/extra").touch()
    else:
        result = mint(staged)
        staged.controller = staged.controller.model_copy(update={"source_commit": "c" * 40})
        with pytest.raises(module.BenchmarkPrelaunchInspectionError, match="PROOF_CONFLICT"):
            mint(staged)
        assert result.raw_sha256 == sha256_bytes(staged.proof.read_bytes())
        return
    with pytest.raises((ValueError, RuntimeError, OSError)):
        mint(staged)
    assert not staged.proof.exists()


@pytest.mark.parametrize(
    "fault", ("proof", "ctime", "output", "absence", "boot", "machine", "association")
)
def test_late_proof_snapshot_or_machine_changes_block_commit(staged, fault):
    result = mint(staged)
    with (
        pytest.raises((ValueError, OSError)),
        inspector(staged, result.raw_sha256).capture(staged.request, staged.invocation) as captured,
    ):
        if fault == "proof":
            staged.proof.chmod(0o640)
        elif fault == "ctime":
            # Restore mode and mtime: ctime still detects the protected metadata change.
            target = staged.execution / "outputs/cold-documents.f32"
            before = target.stat()
            target.chmod(0o600)
            target.chmod(0o640)
            os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
        elif fault == "output":
            (staged.execution / "outputs/cold-documents.f32").write_bytes(b"used")
        elif fault == "absence":
            (staged.execution / "control.sock").symlink_to("missing")
        elif fault == "boot":
            staged.state["boot"] = "00000000-0000-0000-0000-000000000002"
        elif fault == "machine":
            staged.state["epoch"] += 1
        else:
            staged.association.write_bytes(staged.association.read_bytes())
        captured.assert_current()


def test_stale_proof_is_not_rewritten_or_refreshed(staged):
    result = mint(staged)
    before = staged.proof.read_bytes()
    staged.state["epoch"] += 1
    with pytest.raises(module.BenchmarkPrelaunchInspectionError, match="PROOF_STALE"):
        mint(staged)
    assert staged.proof.read_bytes() == before
    with (
        pytest.raises(module.BenchmarkPrelaunchInspectionError, match="PROOF_STALE"),
        inspector(staged, result.raw_sha256).capture(staged.request, staged.invocation),
    ):
        pytest.fail("no stale reuse")


def test_nonroot_cannot_mint_and_parsed_proof_does_not_bypass_capture(staged, monkeypatch):
    monkeypatch.setattr(os, "getresuid", lambda: (os.getuid() + 1,) * 3)
    with pytest.raises(module.BenchmarkPrelaunchInspectionError, match="ROOT_REQUIRED"):
        mint(staged)
    assert not staged.proof.exists()


def test_schema_valid_root_file_with_different_snapshot_is_not_authority(staged):
    result = mint(staged)
    body = result.observation.model_dump(mode="json", exclude={"observation_sha256"})
    body["snapshot_sha256"] = "sha256:" + "f" * 64
    replacement = module.BenchmarkPrelaunchObservation.model_validate(
        seal(body, "observation_sha256")
    )
    raw = benchmark_prelaunch_failure_bytes(replacement)
    staged.proof.chmod(0o600)
    staged.proof.write_bytes(raw)
    staged.proof.chmod(0o440)
    with (
        pytest.raises(module.BenchmarkPrelaunchInspectionError, match="PROOF_STALE"),
        inspector(staged, sha256_bytes(raw)).capture(staged.request, staged.invocation),
    ):
        pytest.fail("parsed file is not enough")


def test_capture_exit_only_closes_and_does_not_recheck_after_application_commit(staged):
    result = mint(staged)
    with inspector(staged, result.raw_sha256).capture(
        staged.request, staged.invocation
    ) as captured:
        captured.assert_current()  # The application owns the final in-transaction fence.
        staged.state["epoch"] += 1  # Simulate drift after that transaction has committed.
    with pytest.raises(module.BenchmarkPrelaunchInspectionError, match="CAPTURE_CLOSED"):
        captured.assert_current()
    with (
        pytest.raises(module.BenchmarkPrelaunchInspectionError, match="PROOF_STALE"),
        inspector(staged, result.raw_sha256).capture(staged.request, staged.invocation),
    ):
        pytest.fail("new capture must independently reject drift")


def test_concurrent_exact_creation_never_overwrites_the_winning_root_proof(staged, monkeypatch):
    original = mint(staged)
    raw = staged.proof.read_bytes()
    staged.proof.unlink()
    real_open = os.open
    injected = False

    def open_once(path, flags, *args, **kwargs):
        nonlocal injected
        if str(path) == staged.proof.name and flags & os.O_EXCL and not injected:
            injected = True
            descriptor = real_open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, **kwargs)
            try:
                assert os.write(descriptor, raw) == len(raw)
                os.fchmod(descriptor, 0o440)
            finally:
                os.close(descriptor)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", open_once)
    replay = mint(staged)
    assert injected and not replay.created and replay.observation == original.observation
    assert replay.raw_sha256 == original.raw_sha256 and staged.proof.read_bytes() == raw


def test_partial_proof_write_is_preserved_without_repair_or_replay(staged, monkeypatch):
    real_write = os.write
    writes = 0

    def partial(descriptor, raw):
        nonlocal writes
        writes += 1
        if writes == 1:
            return real_write(descriptor, raw[:10])
        raise OSError("synthetic proof write failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "write", partial)
        with pytest.raises(module.BenchmarkPrelaunchInspectionError, match="MINT_UNAVAILABLE"):
            mint(staged)
    assert staged.proof.stat().st_size == 10
    before = module._epoch(staged.proof.stat())
    with pytest.raises(ValueError):
        mint(staged)
    assert module._epoch(staged.proof.stat()) == before
