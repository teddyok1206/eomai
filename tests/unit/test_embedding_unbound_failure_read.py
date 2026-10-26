"""Concrete original reader with explicitly synthetic OS/file-provenance leaves."""

import os
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_gpu_control import EmbeddingGpuAllocationRequest
from eom_catalog_service import embedding_unbound_failure_read as reader
from eom_catalog_service.embedding_gpu_batch_launch import (
    NativeEmbeddingGpuBatchLaunchPins,
    native_embedding_gpu_batch_environment,
)
from eom_catalog_service.embedding_gpu_batch_unit_descriptor import (
    embedding_gpu_batch_descriptor_bytes,
)
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_catalog_service.gpu_unit_terminal_observation import StoppedGpuUnit
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.embedding_unbound_control_failure import UnboundEmbeddingControlFailure

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_plan import planning_case
from tests.unit.test_embedding_native_probe_observation import terminal
from tests.unit.test_embedding_unbound_control_failure import proof_document


@pytest.fixture
def original(monkeypatch, tmp_path):
    allocated = planning_case(purpose="INDEX").allocation.control_request
    allocation = EmbeddingGpuAllocationRequest.model_validate(
        seal(allocated.model_dump(mode="json") | {"expires_monotonic_ns": 1}, "message_sha256")
    )
    raw = canonical_json_bytes(allocation)
    attempt = allocation.allocation_attempt_id.removeprefix("embeddingallocation_")
    launch = NativeEmbeddingGpuBatchLaunchPins(
        attempt,
        sha256_bytes(raw),
        123,
        "sha256:" + "4" * 64,
        180,
        16 * 1024**2,
        64 * 1024**2,
        NativeEmbeddingBackendPins(
            allocation.configuration.configuration_id,
            allocation.configuration.configuration_revision_id,
            allocation.configuration.configuration_sha256,
            allocation.configuration.configuration_raw_sha256,
            allocation.receipt_raw_sha256,
        ),
    )
    launch_raw = native_embedding_gpu_batch_environment(launch)
    descriptor = embedding_gpu_batch_descriptor_bytes(attempt)
    proof = UnboundEmbeddingControlFailure.model_validate(
        proof_document(
            parent_request_sha256=allocation.parent_request_sha256,
            allocation_attempt_id=allocation.allocation_attempt_id,
            allocation_request_sha256=allocation.message_sha256,
            allocation_raw_sha256=sha256_bytes(raw),
            launch_raw_sha256=sha256_bytes(launch_raw),
            descriptor_raw_sha256=sha256_bytes(descriptor),
        )
    )
    directory = tmp_path / attempt
    directory.mkdir()
    for name, mode in (("input.json", 0o600), ("result.json", 0o640), ("vectors.f32", 0o640)):
        (directory / name).touch(mode=mode)
    root = replace(terminal(), invocation_id=proof.controller_invocation_id)
    root = replace(
        root,
        status=replace(
            root.status,
            active_state="failed",
            sub_state="failed",
            result="exit-code",
            exec_main_status=1,
        ),
    )
    native = replace(
        root,
        invocation_id="",
        exited_monotonic=0,
        status=replace(
            root.status,
            active_state="inactive",
            sub_state="dead",
            result="success",
            exec_main_code=0,
            exec_main_status=0,
            exec_main_started_monotonic=0,
        ),
    )
    snapshots = Mock(spec=reader.NumericalRuntimeFileSnapshots)
    bodies = {"allocation.json": raw, "launch.env": launch_raw, "10-allocation.conf": descriptor}

    def read(path, *, sha256, maximum):
        value = bodies.get(path.name)
        if value is not None:
            assert sha256_bytes(value) == sha256 and len(value) <= maximum
            return value
        return b"synthetic fixed template; hash adapter separately covered"

    snapshots.read.side_effect = read
    snapshots.observe_protected_member_bytes.side_effect = lambda path, **kw: SimpleNamespace(
        raw=path.read_bytes()
    )
    root_observe, native_observe = Mock(return_value=root), Mock(return_value=native)
    metadata = Mock(return_value=(123, 0))
    stopped = Mock(return_value=StoppedGpuUnit("loaded", "", 0))
    monkeypatch.setattr(reader.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(reader.os, "getresgid", lambda: (0, 0, 0))
    monkeypatch.setattr(reader, "GPU_BATCH_RUNTIME_ROOT", tmp_path)
    monkeypatch.setattr(
        reader, "read_live_runtime_os_file", lambda *a, **kw: proof.boot_id.encode()
    )
    monkeypatch.setattr(reader, "NumericalRuntimeFileSnapshots", lambda: snapshots)
    monkeypatch.setattr(reader, "inspect_cpu_unit", root_observe)
    monkeypatch.setattr(reader, "inspect_embedding_gpu_batch_unit", native_observe)
    monkeypatch.setattr(reader, "observe_failed_gpu_unit_metadata", metadata)
    monkeypatch.setattr(reader, "observe_uninvoked_embedding_gpu_batch_unit", stopped)
    monkeypatch.setattr(reader, "root_owned_unit_processes", lambda unit: ())
    monkeypatch.setattr(
        reader, "fixed_owner_identity", lambda: SimpleNamespace(owner_gid=os.getgid())
    )
    return SimpleNamespace(
        proof=proof,
        allocation=allocation,
        directory=directory,
        snapshots=snapshots,
        root=root_observe,
        native=native_observe,
        metadata=metadata,
        stopped=stopped,
        bodies=bodies,
    )


def test_exact_root_no_grant_and_late_fences_without_invented_retirement(original):
    with reader.read_unbound_embedding_control_failure(original.proof) as resolved:
        assert resolved.allocation == original.allocation
        assert resolved.proof == original.proof
    assert original.root.call_count == original.native.call_count == 2
    assert original.snapshots.assert_unchanged.call_count == 2
    assert all("retirement" not in str(call) for call in original.snapshots.read.call_args_list)


@pytest.mark.parametrize(
    "fault",
    (
        "root",
        "invocation",
        "pid",
        "store",
        "native_started",
        "native_fd",
        "input",
        "result",
        "vectors",
        "grant",
        "boot",
        "descriptor",
    ),
)
def test_uncertain_or_granted_context_never_enters_mutation_window(original, monkeypatch, fault):
    if fault == "root":
        monkeypatch.setattr(reader.os, "getresuid", lambda: (1000, 1000, 1000))
    elif fault == "invocation":
        original.root.return_value = replace(original.root.return_value, invocation_id="f" * 32)
    elif fault == "pid":
        original.metadata.return_value = (456, 0)
    elif fault == "store":
        original.metadata.return_value = (123, 1)
    elif fault == "native_started":
        original.native.return_value = replace(original.native.return_value, invocation_id="f" * 32)
    elif fault == "native_fd":
        original.stopped.return_value = StoppedGpuUnit("loaded", "", 1)
    elif fault in {"input", "result", "vectors"}:
        (
            original.directory
            / {"input": "input.json", "result": "result.json", "vectors": "vectors.f32"}[fault]
        ).write_bytes(b"x")
    elif fault == "grant":
        (original.directory / "input-grant.json").touch()
    elif fault == "boot":
        monkeypatch.setattr(reader, "read_live_runtime_os_file", lambda *a, **kw: b"wrong")
    else:
        original.bodies["10-allocation.conf"] = b"wrong descriptor"
    with (
        pytest.raises((ValueError, AssertionError)),
        reader.read_unbound_embedding_control_failure(original.proof),
    ):
        pytest.fail("invalid physical context entered mutation window")


@pytest.mark.parametrize("fault", ("file", "unit", "grant"))
def test_late_change_is_not_success(original, fault):
    with pytest.raises(ValueError), reader.read_unbound_embedding_control_failure(original.proof):
        if fault == "file":
            original.snapshots.assert_unchanged.side_effect = ValueError("changed epoch")
        elif fault == "unit":
            original.native.return_value = replace(original.native.return_value, main_pid=123)
        else:
            (original.directory / "input-grant.json").touch()
