"""Exact root recovery composition over synthetic Linux ports; no GPU/systemd/DB effects."""

import os
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_gpu_control import embedding_gpu_control_bytes
from eom_catalog_contracts.embedding_gpu_failed_retirement import FailedEmbeddingGpuRetirement
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_catalog_service import embedding_gpu_batch_controller as controller
from eom_catalog_service import embedding_gpu_failed_reconciliation as app
from eom_catalog_service import embedding_retired_failure_read as reader_app
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    TerminalCudaLeaseIdentity,
    UngrantedEmbeddingGpuBatchResources,
)
from eom_catalog_service.embedding_gpu_batch_launch import native_embedding_gpu_batch_environment
from eom_catalog_service.gpu_unit_terminal_observation import StoppedGpuUnit
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.worker_systemd import FixedUnitStatus
from eom_workflow.embedding_encoding_recovery import RetiredEmbeddingRootFailure

from tests.unit.test_embedding_gpu_batch_controller import driver as driver
from tests.unit.test_embedding_gpu_batch_controller import machine as machine


@pytest.fixture
def failed(driver, monkeypatch):
    allocation = driver.captured.prepared.request
    launch = driver.captured.prepared.launch
    unit = app.native_embedding_gpu_batch_unit(launch.attempt_hex)
    grant, _raw = controller._grant(driver.captured, driver.ready, driver.batch)
    lease = driver.ready.resources.shared_gpu_lease
    resources = UngrantedEmbeddingGpuBatchResources(
        driver.ready.resources.device_nodes,
        TerminalCudaLeaseIdentity(lease.lease_gid, lease.parent_epoch, lease.lock_epoch, 123),
        driver.ready.resources.pid1_descriptor,
    )
    terminal = replace(
        driver.terminal,
        status=FixedUnitStatus("loaded", "failed", "failed", "exit-code", 1, 1, 100, False),
    )
    state = SimpleNamespace(
        allocation=allocation,
        invocation=terminal.invocation_id,
        unit=unit,
        terminal=terminal,
        grant=grant,
        resources=resources,
        store=1,
        stopped=StoppedGpuUnit("loaded", terminal.invocation_id, 1),
        effects=[],
        records=[],
        events=[],
        reserved=False,
        clients=(),
        cgroup_empty=True,
        effect_fault=False,
    )
    execution = app.GPU_BATCH_RUNTIME_ROOT / launch.attempt_hex
    lifetime = app.GPU_BATCH_LIFETIME_ROOT / unit / state.invocation
    data = {
        execution / "allocation.json": embedding_gpu_control_bytes(allocation),
        execution / "launch.env": native_embedding_gpu_batch_environment(launch),
        Path("/etc/systemd/system") / app.GPU_BATCH_TEMPLATE: (
            Path(__file__).parents[2] / "infra/systemd" / app.GPU_BATCH_TEMPLATE
        ).read_bytes(),
        app.embedding_gpu_batch_descriptor_path(
            launch.attempt_hex
        ): app.embedding_gpu_batch_descriptor_bytes(launch.attempt_hex),
        execution / "input-grant.json": embedding_gpu_control_bytes(grant),
        lifetime / "ack/intent.json": embedding_gpu_control_bytes(grant),
        lifetime / "ack/result.json": canonical_json_bytes(
            dict(
                event="EMBEDDING_GPU_BATCH_GRANT_SENT_NOT_COMPLETED",
                grant_message_sha256=grant.message_sha256,
            )
        ),
    }
    files = Mock(spec=app.NumericalRuntimeFileSnapshots)

    def read(path, *, sha256, maximum):
        value = data[path]
        if sha256_bytes(value) != sha256 or len(value) > maximum:
            raise ValueError("synthetic protected hash mismatch")
        return value

    files.read.side_effect = read
    files.observe_protected_member_bytes.side_effect = lambda path, **_kw: SimpleNamespace(
        raw=data[path]
    )
    state.files, state.data = files, data
    monkeypatch.setattr(app, "NumericalRuntimeFileSnapshots", lambda: files)
    monkeypatch.setattr(os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(
        app,
        "os",
        SimpleNamespace(
            getresuid=lambda: (0, 0, 0), close=lambda _fd: state.events.append("close")
        ),
    )
    monkeypatch.setattr(
        app, "grp", SimpleNamespace(getgrnam=lambda _name: SimpleNamespace(gr_gid=lease.lease_gid))
    )
    monkeypatch.setattr(
        app, "time", SimpleNamespace(monotonic_ns=lambda: allocation.expires_monotonic_ns + 1)
    )
    monkeypatch.setattr(
        app,
        "read_pinned_cuda_admission_receipt",
        lambda *_a, **_kw: (
            SimpleNamespace(device_capture=driver.ready.readiness.expected_device_capture),
            b"synthetic",
        ),
    )
    monkeypatch.setattr(app, "inspect_embedding_gpu_batch_unit", lambda *_a, **_kw: state.terminal)
    monkeypatch.setattr(
        app, "observe_embedding_gpu_batch_terminal_metadata", lambda *_a, **_kw: (123, state.store)
    )
    monkeypatch.setattr(
        app,
        "observe_embedding_gpu_batch_unit_policy",
        lambda _u: driver.ready.effective_policy_sha256,
    )
    monkeypatch.setattr(
        app, "observe_terminal_embedding_gpu_batch_resources", lambda **_kw: state.resources
    )
    state.observe_device = Mock()
    monkeypatch.setattr(app, "observe_runtime_device", state.observe_device)
    monkeypatch.setattr(app, "observe_cuda_probe_gpu_clients", lambda _device: state.clients)

    def empty(observed_unit):
        assert observed_unit == unit
        if not state.cgroup_empty:
            raise ValueError("synthetic original cgroup still active")

    monkeypatch.setattr(app, "require_embedding_gpu_batch_cgroup_empty", empty)
    monkeypatch.setattr(app, "observe_stopped_gpu_unit", lambda *_a, **_kw: state.stopped)

    @contextmanager
    def release(value, *, unit):
        assert value is resources and unit == state.unit and state.stopped.stored_descriptors == 0
        state.events.append("hold-released-original-lease")
        yield
        state.events.append("release-original-lease")

    monkeypatch.setattr(app, "hold_released_terminal_embedding_gpu_batch_resources", release)

    def reserve(root, original_unit, invocation, phase):
        assert root == app.GPU_BATCH_LIFETIME_ROOT and original_unit == unit
        assert invocation == state.invocation and phase == "retirement"
        if state.reserved:
            raise FileExistsError("synthetic original phase already reserved")
        state.reserved = True
        return 901

    def record(fd, name, raw):
        assert fd == 901
        state.events.append(name)
        state.records.append((name, raw))

    def effect(action, original_unit):
        assert original_unit == unit
        state.events.append(action)
        state.effects.append(action)
        if state.effect_fault:
            raise ValueError("synthetic effect uncertain")
        if action == "CLEAN_FDSTORE":
            state.stopped = replace(state.stopped, stored_descriptors=0)

    monkeypatch.setattr(app, "reserve_unit_effect_phase", reserve)
    monkeypatch.setattr(app, "write_unit_effect_record", record)
    monkeypatch.setattr(app, "apply_embedding_gpu_batch_effect", effect)
    return state


def invoke(failed):
    return app.retire_failed_granted_embedding_gpu_batch(
        failed.allocation, invocation_id=failed.invocation
    )


def test_schema_is_mirrored_and_new_result_has_no_computation_or_source_claim(failed):
    result = invoke(failed)
    root = Path(__file__).resolve().parents[2]
    name = "embedding-gpu-failed-retirement-v1.schema.json"
    raw = (root / "schemas/knowledge" / name).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge" / name
        ).read_bytes()
    )
    assert sha256_bytes(raw) == CATALOG_SCHEMA_RESOURCES["embedding-gpu-failed-retirement"].sha256
    assert result.original_outcome == "FAILED" and result.stored_descriptors == 0
    assert failed.effects == ["RESET_FAILED", "CLEAN_FDSTORE"]
    assert failed.events.index("intent.json") < failed.events.index("RESET_FAILED")
    assert failed.events.index("hold-released-original-lease") < failed.events.index("result.json")
    assert not {"ready", "constructor_calls", "forward_calls", "actor", "authority"}.intersection(
        result.model_dump()
    )
    with pytest.raises(FileExistsError):
        invoke(failed)
    assert failed.effects == ["RESET_FAILED", "CLEAN_FDSTORE"]


@pytest.mark.parametrize(
    "fault",
    ("root", "live", "invocation", "cgroup", "grant", "allocation", "device_busy", "late_file"),
)
def test_unknown_or_changed_identity_is_not_cleanup_or_fallback(failed, monkeypatch, fault):
    if fault == "root":
        monkeypatch.setattr(app.os, "getresuid", lambda: (1000, 1000, 1000))
    elif fault == "live":
        failed.terminal = replace(failed.terminal, main_pid=123)
    elif fault == "invocation":
        failed.invocation = "f" * 32
    elif fault == "cgroup":
        failed.cgroup_empty = False
    elif fault == "device_busy":
        failed.clients = (999,)
    elif fault == "late_file":
        failed.files.assert_unchanged.side_effect = ValueError("synthetic file changed")
    else:
        name = "input-grant.json" if fault == "grant" else "allocation.json"
        target = next(path for path in failed.data if path.name == name)
        failed.data[target] = b"synthetic changed bytes"
    with pytest.raises((ValueError, KeyError)):
        invoke(failed)
    assert not failed.effects and not failed.records


def test_unexpired_allocation_cannot_enter_failure_retirement(failed, monkeypatch):
    monkeypatch.setattr(app.time, "monotonic_ns", lambda: failed.allocation.expires_monotonic_ns)
    with pytest.raises(ValueError):
        invoke(failed)
    failed.files.read.assert_not_called()
    assert not failed.effects


def test_already_released_failure_does_not_inspect_or_interrupt_unrelated_gpu(failed):
    failed.store = 0
    failed.stopped = replace(failed.stopped, stored_descriptors=0)
    failed.clients = (999,)
    assert invoke(failed).stored_descriptors == 0
    assert failed.effects == ["RESET_FAILED"]
    failed.observe_device.assert_not_called()


def test_uncertain_effect_preserves_intent_and_is_not_repeated(failed):
    failed.effect_fault = True
    with pytest.raises(ValueError, match="effect uncertain"):
        invoke(failed)
    assert [name for name, _raw in failed.records] == ["intent.json"]
    assert failed.effects == ["RESET_FAILED"]
    with pytest.raises(FileExistsError):
        invoke(failed)
    assert failed.effects == ["RESET_FAILED"]


@pytest.mark.parametrize(
    "fault",
    (
        None,
        "intent_hash",
        "intent_extra",
        "outcome",
        "result_extra",
        "different_invocation",
        "late_unit",
    ),
)
def test_new_root_result_resolves_pinned_actual_failure_without_historical_ready(
    failed, monkeypatch, fault
):
    result = invoke(failed)
    raw = canonical_json_bytes(result)
    proof = RetiredEmbeddingRootFailure(
        allocation_attempt_id=result.allocation_attempt_id,
        invocation_id=result.invocation_id,
        retirement_sha256=sha256_bytes(raw),
        retired_at=result.observed_at,
        parent_plan_job_id="job_" + "e" * 32,
        parent_request_sha256="sha256:" + "f" * 64,
        original_outcome="FAILED",
        stored_descriptors=0,
    )
    data = dict(failed.records)
    import json

    if fault == "intent_extra":
        body = json.loads(data["intent.json"])
        body["observation"]["authority"] = "ADMIN"
        data["intent.json"] = canonical_json_bytes(body)
    elif fault == "outcome":
        body = json.loads(data["intent.json"])
        body["observation"]["original_terminal"]["main_pid"] = 123
        data["intent.json"] = canonical_json_bytes(body)
    if fault in {"intent_extra", "outcome"}:
        result = FailedEmbeddingGpuRetirement.model_validate(
            result.model_dump(mode="json") | {"intent_sha256": sha256_bytes(data["intent.json"])}
        )
        data["result.json"] = canonical_json_bytes(result)
    if fault == "result_extra":
        data["result.json"] = canonical_json_bytes(result.model_dump(mode="json") | {"ready": {}})
    if fault == "different_invocation":
        data["result.json"] = canonical_json_bytes(
            result.model_dump(mode="json") | {"invocation_id": "f" * 32}
        )
    proof = RetiredEmbeddingRootFailure.model_validate(
        proof.model_dump(mode="json") | {"retirement_sha256": sha256_bytes(data["result.json"])}
    )
    reader = Mock(spec=("read", "assert_unchanged"))

    def read(path, *, sha256, maximum):
        payload = data[path.name]
        if fault == "intent_hash" and path.name == "intent.json":
            raise ValueError("synthetic original intent hash mismatch")
        assert sha256_bytes(payload) == sha256 and len(payload) <= maximum
        return payload

    reader.read.side_effect = read
    monkeypatch.setattr(reader_app, "NumericalRuntimeFileSnapshots", lambda: reader)
    monkeypatch.setattr(reader_app.os, "getresuid", lambda: (0, 0, 0))
    observe = Mock(return_value=failed.stopped)
    if fault == "late_unit":
        observe.side_effect = (failed.stopped, replace(failed.stopped, stored_descriptors=1))
    monkeypatch.setattr(reader_app, "observe_stopped_gpu_unit", observe)
    if fault is None:
        with reader_app.read_retired_embedding_failure(proof) as resolved:
            assert resolved.allocation_request_sha256 == failed.allocation.message_sha256
        reader.assert_unchanged.assert_called_once()
    else:
        with pytest.raises(ValueError), reader_app.read_retired_embedding_failure(proof):
            pass
