"""Real temporary FD transport with synthetic root metadata/ACK/compute; no CUDA or launch."""

from __future__ import annotations

import ast
import fcntl
import os
import signal
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_native_cuda_probe import (
    parse_native_cuda_probe_lease_ready,
    parse_native_cuda_probe_result,
)
from eom_catalog_service import embedding_native_cuda_probe as probe
from eom_catalog_service import embedding_native_probe_transport as transport

from tests.unit.test_embedding_native_cuda_probe import case as case
from tests.unit.test_embedding_native_cuda_probe_ready import ready_case as ready_case


@pytest.fixture
def channels(tmp_path, monkeypatch, ready_case):
    request, raw, ready, result, _refs = ready_case
    paths = tuple(tmp_path / name for name in ("input.json", "ready.json", "result.json"))
    paths[0].write_bytes(raw)
    for path in paths:
        path.touch(exist_ok=True)
        path.chmod(0o600)
    descriptors = tuple(
        os.open(path, os.O_RDONLY if i == 0 else os.O_WRONLY) for i, path in enumerate(paths)
    )
    original = os.fstat

    def synthetic_root(fd):
        value = original(fd)
        return SimpleNamespace(
            **{name: getattr(value, name) for name in dir(value) if name.startswith("st_")}
            | {"st_uid": 0}
        )

    monkeypatch.setattr(os, "fstat", synthetic_root)
    monkeypatch.setattr(probe, "require_native_embedding_identity", lambda _: None)
    monkeypatch.setattr(probe.signal, "pthread_sigmask", lambda *_: None)
    monkeypatch.setattr(probe.signal, "sigpending", lambda: set())
    events = []
    prepared = SimpleNamespace(ready=ready, assert_current=lambda: events.append("fence"))

    @contextmanager
    def prepare(given, given_raw):
        assert given == request and given_raw == raw
        events.append("prepared")
        try:
            yield prepared
        finally:
            events.append("snapshots_rechecked")

    def ack(profile, number):
        assert profile == "CUDA_INDEX_FP32"
        assert parse_native_cuda_probe_lease_ready(paths[1].read_bytes()) == ready
        if number == signal.SIGUSR1:
            assert paths[2].read_bytes() == b""
            events.append("ack_ready")
        else:
            assert number == signal.SIGUSR2
            assert parse_native_cuda_probe_result(paths[2].read_bytes()) == result
            events.append("ack_final")

    def observe(value):
        assert value is prepared and "ack_ready" in events and "ack_final" not in events
        events.append("cuda_observation_synthetic")
        return result

    monkeypatch.setattr(probe, "_prepare_cuda_probe", prepare)
    monkeypatch.setattr(probe, "wait_native_probe_owner_ack", ack)
    monkeypatch.setattr(probe, "_observe_after_ready_ack", observe)
    try:
        yield request, paths, descriptors, events, prepared, ready_case
    finally:
        for fd in descriptors:
            os.close(fd)


def run(channels):
    request, _, (source, ready, result), *_ = channels
    probe.run_native_cuda_probe(
        request.execution_id, input_fd=source, ready_fd=ready, result_fd=result
    )


def test_two_distinct_immutable_reports_and_ack_order(channels):
    run(channels)
    assert channels[3] == [
        "prepared",
        "ack_ready",
        "fence",
        "cuda_observation_synthetic",
        "ack_final",
        "fence",
        "snapshots_rechecked",
    ]


@pytest.mark.parametrize(
    "fault",
    (
        "input_ready_alias",
        "ready_result_alias",
        "input_mode",
        "nonempty_ready",
        "nonempty_result",
        "append",
        "offset",
    ),
)
def test_bad_three_channel_handoff_never_prepares_or_computes(channels, fault):
    _, paths, (source, ready, result), events, *_ = channels
    if fault == "input_ready_alias":
        os.dup2(source, ready)
    elif fault == "ready_result_alias":
        os.dup2(ready, result)
    elif fault == "input_mode":
        paths[0].chmod(0o644)
    elif fault.startswith("nonempty"):
        paths[1 if fault.endswith("ready") else 2].write_bytes(b"old failed evidence")
    elif fault == "append":
        fcntl.fcntl(ready, fcntl.F_SETFL, os.O_APPEND)
    else:
        os.lseek(source, 1, os.SEEK_SET)
    with pytest.raises(ValueError):
        run(channels)
    assert events == []


@pytest.mark.parametrize("fault", ("ready_timeout", "early_final", "input_change_after_ready_ack"))
def test_no_cuda_observation_before_valid_ready_ack_and_current_input(channels, monkeypatch, fault):
    if fault == "early_final":
        monkeypatch.setattr(probe.signal, "sigpending", lambda: {signal.SIGUSR2})
    else:

        def ack(_, number):
            assert number == signal.SIGUSR1
            if fault == "ready_timeout":
                raise ValueError("NATIVE_CUDA_PROBE_OWNER_OBSERVATION_MISSING")
            channels[1][0].write_bytes(b"changed after root signal")

        monkeypatch.setattr(probe, "wait_native_probe_owner_ack", ack)
    with pytest.raises(ValueError):
        run(channels)
    assert "cuda_observation_synthetic" not in channels[3]
    assert channels[1][2].read_bytes() == b""
    assert channels[1][1].stat().st_size > 0
    assert channels[3][-1] == "snapshots_rechecked"


def test_final_timeout_keeps_both_observed_reports_not_success(channels, monkeypatch):
    previous = probe.wait_native_probe_owner_ack

    def ack(profile, number):
        if number == signal.SIGUSR2:
            raise ValueError("NATIVE_CUDA_PROBE_OWNER_OBSERVATION_MISSING")
        previous(profile, number)

    monkeypatch.setattr(probe, "wait_native_probe_owner_ack", ack)
    with pytest.raises(ValueError, match="OWNER_OBSERVATION_MISSING"):
        run(channels)
    assert channels[1][1].stat().st_size > 0 and channels[1][2].stat().st_size > 0
    assert "ack_final" not in channels[3]


@pytest.mark.parametrize("number", (signal.SIGUSR1, signal.SIGUSR2))
@pytest.mark.parametrize("uid", (None, 1000, 0))
def test_only_root_and_correct_phase_signal_are_acknowledgements(monkeypatch, number, uid):
    response = None if uid is None else SimpleNamespace(si_signo=number, si_uid=uid)
    monkeypatch.setattr(transport.signal, "sigtimedwait", lambda *_: response)
    if uid == 0:
        transport.wait_native_probe_owner_ack("CUDA_INDEX_FP32", number)
    else:
        with pytest.raises(ValueError, match="OWNER_OBSERVATION_MISSING"):
            transport.wait_native_probe_owner_ack("CUDA_INDEX_FP32", number)


def test_actual_after_ack_composition_reuses_existing_observer_and_no_model_recipe(
    channels, monkeypatch
):
    from eom_catalog_contracts.embedding_native_cpu_probe import NativeProbeFilesystemDenials
    from eom_catalog_service import embedding_cuda_probe_resource_files as resources
    from eom_catalog_service import embedding_installed_runtime_observer as observers
    from eom_catalog_service import embedding_offline_backend as backend

    request, raw, ready, expected, refs = channels[5]
    events = []
    owned = SimpleNamespace(assert_owned=lambda: events.append("held"))

    @contextmanager
    def open_devices(files):
        assert files == "synthetic resource capture"
        events.append("rw_open")
        try:
            yield owned
        finally:
            events.append("rw_close")

    class Observer:
        def __init__(self, configured, *, cuda_ownership):
            assert configured.pointer == request.installed_proof and cuda_ownership is owned
            events.append("protected_observer")

    def observe(*, profile, runtime_observer, cuda_ownership):
        assert profile == "CUDA_INDEX_FP32" and isinstance(runtime_observer, Observer)
        assert cuda_ownership is owned
        events.append("no_model_recipe")
        return refs["bundle"].numerical_runtime

    prepared = probe._PreparedCudaProbe(
        request,
        raw,
        refs["configuration"],
        refs["configuration_raw"],
        refs["proof"],
        refs["proof_raw"],
        None,
        SimpleNamespace(bundle=refs["bundle"], manifest=SimpleNamespace(raw=refs["bundle_raw"])),
        "synthetic resource capture",
        ready,
    )
    monkeypatch.setattr(
        probe._PreparedCudaProbe, "assert_current", lambda _: events.append("current")
    )
    monkeypatch.setattr(
        probe,
        "_probe_denials",
        lambda _: {name: "DENIED" for name in NativeProbeFilesystemDenials.model_fields},
    )
    monkeypatch.setattr(resources, "open_cuda_probe_device_access", open_devices)
    monkeypatch.setattr(observers, "ProtectedInstalledEmbeddingRuntimeObserver", Observer)
    monkeypatch.setattr(backend, "observe_native_runtime_without_model", observe)
    # Restore the real production composition, not the transport fixture's fake callback.
    assert REAL_OBSERVE(prepared) == expected
    assert events == [
        "current",
        "rw_open",
        "protected_observer",
        "no_model_recipe",
        "current",
        "rw_close",
    ]


REAL_OBSERVE = probe._observe_after_ready_ack


@pytest.mark.parametrize("retention_fails", (False, True))
def test_real_preparation_requests_retention_but_never_opens_rw_or_computes(
    monkeypatch, ready_case, retention_fails
):
    import eom_gpu_lease
    from eom_catalog_service import embedding_cuda_probe_resource_files as resources

    request, raw, expected, _result, refs = ready_case
    events = []
    lease = SimpleNamespace(close=lambda: events.append("lease_close"))
    captured = SimpleNamespace(
        assert_current=lambda: events.append("path_check"),
        shared_gpu_lease=SimpleNamespace(
            holder_pid=expected.pid, holder_start_time_ticks=expected.start_time_ticks
        ),
        resource_descriptors=expected.resource_fds,
    )

    @contextmanager
    def capture(device, given_lease):
        assert device == refs["proof"].device_capture and given_lease is lease
        events.append("path_capture")
        try:
            yield captured
        finally:
            events.append("path_close")

    def retention(given_lease):
        assert given_lease is lease
        events.append("retention_requested")
        if retention_fails:
            raise ValueError("synthetic notification failure")

    monkeypatch.setattr(probe, "require_native_embedding_identity", lambda _: None)
    monkeypatch.setattr(
        probe,
        "_load_probe_metadata",
        lambda _: (
            None,
            refs["configuration"],
            refs["configuration_raw"],
            refs["proof"],
            refs["proof_raw"],
            SimpleNamespace(
                bundle=refs["bundle"], manifest=SimpleNamespace(raw=refs["bundle_raw"])
            ),
        ),
    )
    monkeypatch.setattr(eom_gpu_lease, "acquire_shared_gpu_lease", lambda: lease)
    monkeypatch.setattr(eom_gpu_lease, "request_unit_gpu_lease_retention", retention)
    monkeypatch.setattr(resources, "capture_cuda_probe_resource_files", capture)
    monkeypatch.setattr(probe.os, "geteuid", lambda: expected.worker_uid)
    monkeypatch.setattr(probe.os, "getegid", lambda: expected.worker_gid)
    monkeypatch.setattr(probe.os, "getgroups", lambda: list(expected.supplementary_gids))
    monkeypatch.setattr(
        probe._PreparedCudaProbe, "assert_current", lambda _: events.append("fence")
    )
    # R/W opening and observation are intentionally not replaced: preparation must not call them.
    if retention_fails:
        with (
            pytest.raises(ValueError, match="notification failure"),
            probe._prepare_cuda_probe(request, raw),
        ):
            pytest.fail("failed retention must not emit a ready frame")
        assert events == ["path_capture", "retention_requested", "path_close", "lease_close"]
    else:
        with probe._prepare_cuda_probe(request, raw) as prepared:
            assert prepared.ready == expected
            events.append("ready_only")
        assert events == [
            "path_capture",
            "retention_requested",
            "path_check",
            "fence",
            "ready_only",
            "fence",
            "path_close",
            "lease_close",
        ]


@pytest.mark.parametrize("run_fails", (False, True))
def test_main_keeps_diagnostics_separate_and_closes_both_owned_channels(monkeypatch, run_fails):
    events = []
    monkeypatch.setattr(probe.sys, "argv", ["fixed-probe", "b" * 32])
    monkeypatch.setattr(probe.fcntl, "fcntl", lambda descriptor, *_: descriptor + 40)
    monkeypatch.setattr(probe.os, "close", lambda fd: events.append(("close", fd)))

    @contextmanager
    def quiet():
        events.append("quiet")
        yield

    def run(execution, **channels):
        assert execution == "b" * 32
        assert channels == {"input_fd": 0, "ready_fd": 42, "result_fd": 41}
        events.append("run")
        if run_fails:
            raise ValueError("synthetic private diagnostic must not be printed")

    monkeypatch.setattr(probe, "discard_native_embedding_diagnostics", quiet)
    monkeypatch.setattr(probe, "run_native_cuda_probe", run)
    assert probe.main() == int(run_fails)
    assert events == ["quiet", "run", ("close", 42), ("close", 41)]


def test_worker_import_is_stdlib_first_and_has_no_model_constructor_or_launch():
    tree = ast.parse(Path(probe.__file__).read_text())
    names = {node.module or "" for node in tree.body if isinstance(node, ast.ImportFrom)}
    assert not any(
        name.startswith(("torch", "transformers", "pydantic", "eom_gpu_lease")) for name in names
    )
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not {"from_pretrained", "forward", "encode", "Popen", "run", "system"} & calls
    code = """
import sys
import eom_catalog_service.embedding_native_cuda_probe
assert not any(n in sys.modules for n in ('torch','transformers','eom_gpu_lease'))
print('NO_CUDA_IMPORT=PASS')
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=15, check=True
    )
    assert result.stdout.strip() == "NO_CUDA_IMPORT=PASS" and not result.stderr
