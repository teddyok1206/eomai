"""Real FD/channel composition over synthetic identity/installation/GPU ports only."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_gpu_batch_worker as worker
from eom_catalog_service.embedding_gpu_control_channel import EmbeddingGpuChannelError
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_catalog_service.embedding_native_stdio import NativeEmbeddingHandoffError
from eom_identifiers import sha256_bytes

from tests.unit.test_embedding_gpu_batch_stdio import cuda_descriptors as cuda_descriptors
from tests.unit.test_embedding_gpu_control_channel import endpoints


@pytest.fixture
def ports(monkeypatch, cuda_descriptors):
    import eom_gpu_lease
    from eom_catalog_service import (
        embedding_cuda_probe_resource_files,
        embedding_gpu_allocation,
        embedding_native_cuda_backend,
        embedding_native_installation_admission,
        embedding_runtime_files,
        embedding_runtime_process_identity,
    )

    events, state = [], {"busy": False, "retention_failure": False}

    # These tests run synthetic worker ports in threads of the pytest process.
    # Real process-default timer/termination is tested in isolated child processes.
    @contextmanager
    def synthetic_compute_deadline(_seconds):
        yield

    monkeypatch.setattr(worker, "_hard_compute_deadline", synthetic_compute_deadline)
    batch, backend, scope, resources, life, descriptors = cuda_descriptors
    lease = object()

    def require_identity(profile):
        assert profile == "CUDA_INDEX_FP32"
        events.append("identity")

    class Files:
        def __init__(self, uid):
            assert uid == 0
            events.append("files")

        def assert_unchanged(self):
            events.append("files-current")

    @contextmanager
    def claim():
        events.append("claim")
        try:
            yield None if state["busy"] else lease
        finally:
            events.append("worker-lease-close")

    @contextmanager
    def capture(device, actual):
        from tests.unit.test_embedding_gpu_control import control_case

        ready = control_case()[1]
        assert actual is lease and device == ready.expected_device_capture
        events.append("capture")
        try:
            yield SimpleNamespace(
                shared_gpu_lease=SimpleNamespace(holder_start_time_ticks=456),
                resource_descriptors=ready.resource_fds,
                assert_current=lambda: events.append("resources-current"),
            )
        finally:
            events.append("capture-close")

    def retain(actual):
        assert actual is lease
        events.append("retention-request")
        if state["retention_failure"]:
            raise ValueError("retention uncertain")

    @contextmanager
    def ownership(captured):
        events.append("device-open")
        try:
            yield lease
        finally:
            events.append("device-close")

    def admission(files, configuration, *, receipt_raw_sha256):
        from tests.unit.test_embedding_gpu_control import control_case

        ready = control_case()[1]
        events.append("receipt")
        return SimpleNamespace(device_capture=ready.expected_device_capture), b""

    def backend_scope(configuration, *, receipt_raw_sha256, ownership):
        assert ownership is lease
        events.append("model-scope")
        return scope()

    monkeypatch.setattr(worker, "require_native_embedding_identity", require_identity)
    monkeypatch.setattr(
        worker,
        "os",
        SimpleNamespace(
            getpid=lambda: 123,
            geteuid=lambda: 1234,
            getegid=lambda: 1234,
            getgroups=lambda: [1234, 2468],
        ),
    )
    monkeypatch.setattr(embedding_runtime_files, "NumericalRuntimeFileSnapshots", Files)
    monkeypatch.setattr(
        embedding_native_installation_admission, "read_pinned_cuda_admission_receipt", admission
    )
    monkeypatch.setattr(embedding_gpu_allocation, "hold_native_embedding_gpu_allocation", claim)
    monkeypatch.setattr(
        embedding_cuda_probe_resource_files, "capture_cuda_probe_resource_files", capture
    )
    monkeypatch.setattr(
        embedding_cuda_probe_resource_files, "open_cuda_probe_device_access", ownership
    )
    monkeypatch.setattr(eom_gpu_lease, "request_unit_gpu_lease_retention", retain)
    monkeypatch.setattr(embedding_native_cuda_backend, "native_cuda_backend_scope", backend_scope)
    monkeypatch.setattr(
        embedding_runtime_files, "read_live_runtime_os_file", lambda *args, **kwargs: b"stat"
    )
    monkeypatch.setattr(
        embedding_runtime_process_identity, "native_process_start_ticks", lambda raw, pid: 456
    )
    return batch, backend, resources, life, descriptors, events, state


def pins(request):
    config = request.configuration
    return NativeEmbeddingBackendPins(
        config.configuration_id,
        config.configuration_revision_id,
        config.configuration_sha256,
        config.configuration_raw_sha256,
        request.receipt_raw_sha256,
    )


def test_worker_connects_original_lease_ready_grant_fd_work_ack_then_local_cleanup(ports, tmp_path):
    batch, backend, resources, life, descriptors, events, _ = ports
    with endpoints(requested=False, ready=False, granted=False, bound=False) as (
        root,
        native,
        case,
        *_,
    ):
        root.send_request()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                worker.run_native_embedding_gpu_batch_worker,
                native,
                descriptors,
                expected_backend=pins(case[0]),
                resources=resources,
                maximum_total_output_bytes=64 * 1024**2,
            )
            assert root.receive_allocation() == case[1]
            assert not life and not backend.calls and "device-open" not in events
            assert os.lseek(descriptors.input, 0, os.SEEK_CUR) == 0
            root.send_grant(case[3])
            root.bind_batch(
                batch, input_raw_sha256=sha256_bytes(case[7]), input_byte_count=len(case[7])
            )
            while (claim := root.authorize_next(lambda _: None)) is None:
                pass
            assert not future.done() and life == ["open", "closed"]
            assert "device-close" not in events and "worker-lease-close" not in events
            raw = (tmp_path / "result.json").read_bytes()
            assert sha256_bytes(raw) == claim.result_raw_sha256

            def verify(actual):
                assert actual == claim
                assert sha256_bytes((tmp_path / "vectors.f32").read_bytes()) == claim.vectors_sha256

            root.acknowledge_result(verify)
            result = future.result(timeout=2)
        assert result.result_sha256 == json.loads(raw)["result_sha256"]
        assert events[0] == "identity" and events.count("claim") == 1
        assert events[-3:] == ["device-close", "capture-close", "worker-lease-close"]
        assert (
            events.index("retention-request")
            < events.index("device-open")
            < events.index("model-scope")
        )
        assert life == ["open", "closed"] and len(backend.calls) == 2


def test_busy_never_reads_numeric_input_opens_device_or_constructs_model(ports, tmp_path):
    _, backend, resources, life, descriptors, events, state = ports
    state["busy"] = True
    with endpoints(requested=False, ready=False, granted=False, bound=False) as (
        root,
        native,
        case,
        *_,
    ):
        root.send_request()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                worker.run_native_embedding_gpu_batch_worker,
                native,
                descriptors,
                expected_backend=pins(case[0]),
                resources=resources,
                maximum_total_output_bytes=64 * 1024**2,
            )
            assert root.receive_allocation() == case[2]
            assert future.result(timeout=2) == case[2]
        assert events.count("claim") == 1 and events[-1] == "worker-lease-close"
        assert not {"capture", "retention-request", "device-open", "model-scope"} & set(events)
        assert not life and not backend.calls
        assert os.lseek(descriptors.input, 0, os.SEEK_CUR) == 0
        assert (
            (tmp_path / "result.json").read_bytes()
            == (tmp_path / "vectors.f32").read_bytes()
            == b""
        )


def test_configuration_mismatch_is_failure_before_claim_not_busy_fallback(ports):
    _, backend, resources, life, descriptors, events, _ = ports
    with endpoints(requested=False, ready=False, granted=False, bound=False) as (
        root,
        native,
        case,
        *_,
    ):
        root.send_request()
        expected = replace(pins(case[0]), receipt_raw_sha256="sha256:" + "b" * 64)
        with pytest.raises(ValueError, match="BINDING_INVALID"):
            worker.run_native_embedding_gpu_batch_worker(
                native,
                descriptors,
                expected_backend=expected,
                resources=resources,
                maximum_total_output_bytes=64 * 1024**2,
            )
        with pytest.raises(EmbeddingGpuChannelError):
            root.receive_allocation()
        assert events == ["identity"] and not life and not backend.calls


def test_invalid_native_identity_closes_channel_without_reading_request_or_claiming(
    ports, monkeypatch
):
    _, backend, resources, life, descriptors, events, _ = ports

    def denied(_):
        raise PermissionError("native identity mismatch")

    monkeypatch.setattr(worker, "require_native_embedding_identity", denied)
    with endpoints(requested=False, ready=False, granted=False, bound=False) as (
        root,
        native,
        case,
        *_,
    ):
        root.send_request()
        with pytest.raises(PermissionError):
            worker.run_native_embedding_gpu_batch_worker(
                native,
                descriptors,
                expected_backend=pins(case[0]),
                resources=resources,
                maximum_total_output_bytes=64 * 1024**2,
            )
        with pytest.raises(EmbeddingGpuChannelError):
            root.receive_allocation()
    assert not events and not life and not backend.calls
    assert os.lseek(descriptors.input, 0, os.SEEK_CUR) == 0


@pytest.mark.parametrize("fault", ["retention", "lost_grant", "source_denied"])
def test_all_original_error_paths_close_lease_without_fallback_or_model_retry(
    ports, tmp_path, fault
):
    batch, backend, resources, life, descriptors, events, state = ports
    state["retention_failure"] = fault == "retention"
    with endpoints(requested=False, ready=False, granted=False, bound=False) as (
        root,
        native,
        case,
        *_,
    ):
        root.send_request()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                worker.run_native_embedding_gpu_batch_worker,
                native,
                descriptors,
                expected_backend=pins(case[0]),
                resources=resources,
                maximum_total_output_bytes=64 * 1024**2,
            )
            if fault == "retention":
                with pytest.raises(EmbeddingGpuChannelError):
                    root.receive_allocation()
            else:
                assert root.receive_allocation() == case[1]
                if fault == "lost_grant":
                    root.close()
                else:
                    root.send_grant(case[3])
                    root.bind_batch(
                        batch, input_raw_sha256=sha256_bytes(case[7]), input_byte_count=len(case[7])
                    )

                    def denied(_):
                        raise PermissionError("source revoked")

                    with pytest.raises(EmbeddingGpuChannelError):
                        root.authorize_next(denied)
            with pytest.raises((ValueError, NativeEmbeddingHandoffError)):
                future.result(timeout=2)
        assert events.count("claim") == 1 and events[-1] == "worker-lease-close"
        assert not life and not backend.calls
        assert (
            (tmp_path / "result.json").read_bytes()
            == (tmp_path / "vectors.f32").read_bytes()
            == b""
        )
