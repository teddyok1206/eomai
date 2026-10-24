"""Root controller with synthetic OS/unit ports; no GPU, login, DB or service effects."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_gpu_control import parse_embedding_gpu_control
from eom_catalog_contracts.embedding_work_batch_result import embedding_work_batch_result_bytes
from eom_catalog_service import embedding_gpu_batch_controller as controller
from eom_catalog_service import embedding_gpu_batch_observation as observer
from eom_catalog_service.embedding_gpu_batch_lifetime import (
    EmbeddingGpuBatchRetirement,
    EmbeddingGpuBatchTerminalObservation,
)
from eom_catalog_service.gpu_unit_terminal_observation import StoppedGpuUnit
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.worker_systemd import FixedUnitStatus

from tests.unit.test_embedding_gpu_batch_observation import machine as machine
from tests.unit.test_embedding_gpu_control import control_case
from tests.unit.test_embedding_gpu_control_channel import synthetic_result
from tests.unit.test_embedding_native_probe_observation import process_stat


@pytest.fixture
def driver(machine, monkeypatch):
    captured = observer.capture_embedding_gpu_batch_machine(machine.prepared)
    ready = observer.observe_embedding_gpu_batch_ready(captured, machine.ready)
    batch = control_case()[6]
    result, vectors = synthetic_result()
    raw = embedding_work_batch_result_bytes(result)
    terminal = replace(
        ready.unit,
        main_pid=0,
        exited_monotonic=200,
        status=FixedUnitStatus("loaded", "active", "exited", "success", 1, 0, 100, False),
    )
    original_terminal = EmbeddingGpuBatchTerminalObservation(ready, terminal, "SUCCEEDED")
    retired = EmbeddingGpuBatchRetirement(
        original_terminal,
        StoppedGpuUnit("loaded", ready.unit.invocation_id, 0),
        "2026-10-24T00:00:00Z",
    )
    state = SimpleNamespace(
        captured=captured,
        ready=ready,
        batch=batch,
        result=result,
        vectors=vectors,
        raw=raw,
        original=ready.unit,
        unit=ready.unit,
        terminal=terminal,
        retired=retired,
        events=[],
        records=[],
        closed=[],
        files={},
        claimed=False,
        busy=False,
        authorize_fault=None,
        authorization_count=0,
        cleanup_fault=False,
        claim_fault=None,
        child_index=0,
        frame_fault=False,
        store=0,
        clients=(),
        pids=(),
        ack_present=False,
        metadata_pid=123,
    )

    class Connection:
        def setsockopt(self, *args):
            assert args == (controller.socket.SOL_SOCKET, controller.socket.SO_PASSCRED, 1)
            state.events.append("passcred")

        def connect(self, path):
            assert path == str(captured.execution / "control.sock")
            state.events.append("connect")

        def close(self):
            state.events.append("connection-close")

    state.connection = Connection()
    state.claim_dispatch = controller._claim_dispatch

    class SourceOwner:
        def admit_allocation(self, request, observed):
            assert request == captured.prepared.request and observed == ready
            state.events.append("actual-owner-admission")
            return batch

        def authorize_child(self, batch_sha256, child_sha256):
            assert batch_sha256 == batch.request_sha256
            assert child_sha256 in {child.request.request_sha256 for child in batch.children}
            state.authorization_count += 1
            state.events.append("source-fence")
            if state.authorize_fault == "deny":
                raise PermissionError("source revoked")
            if state.authorize_fault == "false":
                return False

    state.owner = SourceOwner()

    class Channel:
        def __init__(self, connection, request, **kwargs):
            assert connection is state.connection and request == captured.prepared.request
            assert kwargs["expected_peer"] == controller._ACTIVATOR
            assert kwargs["expected_sender"].pid == ready.readiness.pid
            state.fence = kwargs["peer_fence"]
            state.fence(controller._ACTIVATOR)

        def send_request(self):
            state.events.append("request")

        def receive_allocation(self):
            state.events.append("allocation")
            if state.busy:
                state.unit = terminal
                return control_case(expires_ns=machine.request.expires_monotonic_ns)[2]
            return ready.readiness

        def send_grant(self, grant):
            state.grant = grant
            state.events.append("grant")
            if state.frame_fault:
                raise ValueError("grant delivery uncertain")

        def bind_batch(self, value, *, input_raw_sha256, input_byte_count):
            assert value == batch
            state.events.append("channel-bind")

        def authorize_next(self, authorize):
            state.child_index += 1
            if state.child_index <= len(batch.children):
                authorize(
                    SimpleNamespace(
                        child_request_sha256=batch.children[
                            state.child_index - 1
                        ].request.request_sha256
                    )
                )
                return None
            body = {
                "schema_version": "embedding-gpu-allocation-control/1.0",
                "message_type": "RESULT_READY",
                "allocation_attempt_id": captured.prepared.request.allocation_attempt_id,
                "allocation_request_sha256": captured.prepared.request.message_sha256,
                "grant_message_sha256": state.grant.message_sha256,
                "batch_request_sha256": batch.request_sha256,
                "result_raw_sha256": sha256_bytes(state.raw),
                "result_sha256": result.result_sha256,
                "result_byte_count": len(state.raw),
                "vectors_sha256": sha256_bytes(state.vectors),
                "vectors_byte_count": len(state.vectors),
            }
            if state.claim_fault == "hash":
                body["result_raw_sha256"] = "sha256:" + "f" * 64
            if state.claim_fault == "self":
                body["result_sha256"] = "sha256:" + "f" * 64
            state.claim = parse_embedding_gpu_control(
                body | {"message_sha256": content_sha256(body)}
            )
            return state.claim

        def acknowledge_result(self, verify):
            verify(state.claim)
            assert state.fence.phase == "TERMINATING"
            state.events.append("result-ACK")
            state.unit = terminal
            # Reproduce legitimate exit before the post-send peer fence.
            state.fence(controller._ACTIVATOR)

        def close(self):
            state.events.append("channel-close")
            state.unit = terminal

    @contextmanager
    def directory(*args, **kwargs):
        yield 900

    def create(fd, name, raw, **kwargs):
        assert fd == 900
        if name in state.files:
            raise FileExistsError(name)
        state.files[name] = raw
        state.events.append(name)

    def reserve(root, unit, invocation, phase):
        assert root == controller.GPU_BATCH_LIFETIME_ROOT
        assert unit == machine.unit_name and invocation == ready.unit.invocation_id
        state.events.append("reserve-" + phase)
        return 901

    def record(fd, name, raw):
        assert fd == 901
        state.records.append((name, json.loads(raw)))
        state.events.append("record-" + name)

    def bind(*args):
        state.events.append("input-bind")
        machine.grant_exists = True

    def inspect(*args, **kwargs):
        return state.unit

    def retire(*args):
        state.events.append("retire")
        if state.cleanup_fault:
            raise ValueError("retirement outcome uncertain")
        return retired

    def process(path, **kwargs):
        return {
            "stat": process_stat(123, start=456),
            "status": machine.status,
            "cgroup": machine.cgroup,
        }[path.name]

    monkeypatch.setattr(
        controller,
        "os",
        SimpleNamespace(getresuid=lambda: (0, 0, 0), close=lambda fd: state.closed.append(fd)),
    )
    monkeypatch.setattr(
        controller,
        "socket",
        SimpleNamespace(
            socket=lambda *args: state.connection,
            AF_UNIX=1,
            SOCK_STREAM=2,
            SOCK_CLOEXEC=4,
            SOL_SOCKET=5,
            SO_PASSCRED=6,
        ),
    )
    monkeypatch.setattr(controller.time, "monotonic_ns", lambda: 10**9)
    monkeypatch.setattr(controller, "_claim_dispatch", lambda _: state.events.append("dispatch"))
    monkeypatch.setattr(
        controller, "_socket_effect", lambda action, _: state.events.append("socket-" + action)
    )
    monkeypatch.setattr(controller, "_wait_started", lambda _: ready.unit)
    monkeypatch.setattr(controller, "inspect_embedding_gpu_batch_unit", inspect)
    monkeypatch.setattr(controller, "read_live_runtime_os_file", process)
    monkeypatch.setattr(controller, "EmbeddingGpuControlChannel", Channel)
    monkeypatch.setattr(controller, "protected_cpu_handoff_directory", directory)
    monkeypatch.setattr(controller, "create_protected_cpu_handoff_member", create)
    monkeypatch.setattr(
        controller,
        "read_protected_cpu_handoff_member",
        lambda _, name, **kwargs: state.raw if name == "result.json" else state.vectors,
    )
    monkeypatch.setattr(controller, "bind_embedding_gpu_batch_handoff", bind)
    monkeypatch.setattr(controller, "reserve_unit_effect_phase", reserve)
    monkeypatch.setattr(controller, "write_unit_effect_record", record)
    monkeypatch.setattr(
        controller, "observe_embedding_gpu_batch_terminal", lambda *args: original_terminal
    )
    monkeypatch.setattr(controller, "retire_embedding_gpu_batch", retire)
    monkeypatch.setattr(
        controller,
        "observe_embedding_gpu_batch_terminal_metadata",
        lambda *args, **kwargs: (state.metadata_pid, state.store),
    )
    monkeypatch.setattr(
        controller,
        "require_embedding_gpu_batch_cgroup_empty",
        lambda _: (_ for _ in ()).throw(ValueError("own cgroup not empty")) if state.pids else None,
    )
    monkeypatch.setattr(controller, "observe_cuda_probe_gpu_clients", lambda _: state.clients)
    monkeypatch.setattr(controller, "observe_runtime_device", lambda _: None)
    monkeypatch.setattr(
        controller,
        "require_unit_effect_phase_absent",
        lambda *args: (
            (_ for _ in ()).throw(ValueError("ACK present")) if state.ack_present else None
        ),
    )
    monkeypatch.setattr(
        controller,
        "apply_embedding_gpu_batch_effect",
        lambda action, _: state.events.append(action),
    )
    monkeypatch.setattr(
        controller, "observe_stopped_gpu_unit", lambda *args, **kwargs: retired.retired_unit
    )
    state.create = create
    return state


def test_original_grant_sources_outputs_and_retirement_form_one_flow(driver):
    result = controller.run_embedding_gpu_batch(driver.captured, source_owner=driver.owner)
    assert isinstance(result, controller.CompletedEmbeddingGpuBatch)
    assert result.batch == driver.batch and result.result == driver.result
    assert result.retirement == driver.retired
    assert len(result.child_vectors) == len(driver.batch.children)
    assert all(
        view.readonly and view.obj is result.child_vectors[0].obj for view in result.child_vectors
    )
    assert b"".join(result.child_vectors) == driver.vectors
    events = driver.events
    assert events.index("dispatch") < events.index("socket-start") < events.index("connect")
    assert (
        events.index("actual-owner-admission") < events.index("input-bind") < events.index("grant")
    )
    assert events.index("result-ACK") < events.index("retire") < events.index("socket-stop")
    assert driver.authorization_count == 4 * len(driver.batch.children)


@pytest.mark.parametrize("fault", ["deny", "false"])
def test_actual_owner_denial_never_grants_or_falls_back_and_retires_original(driver, fault):
    driver.authorize_fault = fault
    with pytest.raises((ValueError, PermissionError)):
        controller.run_embedding_gpu_batch(driver.captured, source_owner=driver.owner)
    assert "grant" not in driver.events and "input-bind" not in driver.events
    assert driver.events.count("retire") == 1


@pytest.mark.parametrize("fault", ["hash", "self", "binary", "noncanonical"])
def test_invalid_actual_result_is_not_acked_published_or_reencoded(driver, fault):
    driver.claim_fault = fault
    if fault == "binary":
        driver.vectors = bytes(len(driver.vectors))  # valid claimed hash, invalid norm/child hash
    if fault == "noncanonical":
        driver.raw = b" " + driver.raw
    with pytest.raises(ValueError):
        controller.run_embedding_gpu_batch(driver.captured, source_owner=driver.owner)
    assert "result-ACK" not in driver.events
    assert driver.events.count("grant") == 1 and driver.events.count("retire") == 1


def test_unknown_grant_delivery_never_resubmits_or_returns_busy(driver):
    driver.frame_fault = True
    with pytest.raises(ValueError, match="delivery uncertain"):
        controller.run_embedding_gpu_batch(driver.captured, source_owner=driver.owner)
    assert driver.events.count("grant") == 1 and driver.events.count("retire") == 1
    assert "result-ACK" not in driver.events


def test_uncertain_cleanup_is_not_automatically_repeated(driver):
    driver.cleanup_fault = True
    with pytest.raises(ValueError, match="retirement outcome uncertain") as error:
        controller.run_embedding_gpu_batch(driver.captured, source_owner=driver.owner)
    assert driver.events.count("retire") == 1
    assert error.value.__notes__ == ["EMBEDDING_GPU_BATCH_RETIREMENT_RECONCILIATION_REQUIRED"]


def test_failure_before_validated_ready_uses_only_ungranted_cleanup(driver, monkeypatch):
    cleaned = []

    def invalid(*args):
        raise ValueError("original READY failed independent validation")

    def cleanup(captured, *, original):
        assert captured is driver.captured and original == driver.original
        cleaned.append(original)
        return driver.retired.retired_unit

    monkeypatch.setattr(controller, "observe_embedding_gpu_batch_ready", invalid)
    monkeypatch.setattr(controller, "retire_failed_ungranted_embedding_gpu_batch", cleanup)
    with pytest.raises(ValueError, match="READY failed independent validation"):
        controller.run_embedding_gpu_batch(driver.captured, source_owner=driver.owner)
    assert cleaned == [driver.original]
    assert "retire" not in driver.events and "grant" not in driver.events
    assert "actual-owner-admission" not in driver.events and "socket-stop" in driver.events


def test_busy_proof_allows_an_unrelated_image_holder_and_never_loads_batch(driver):
    driver.busy = True
    driver.clients = (9876,)
    result = controller.run_embedding_gpu_batch(driver.captured, source_owner=driver.owner)
    assert isinstance(result, controller.UnavailableEmbeddingGpuBatch)
    assert result.original_unit.succeeded and result.retired_unit.stored_descriptors == 0
    assert driver.events.count("STOP") == 1 and "socket-stop" in driver.events
    assert "actual-owner-admission" not in driver.events and "grant" not in driver.events
    assert "retire" not in driver.events  # acquired lease cleanup is not BUSY cleanup


@pytest.mark.parametrize("fault", ["store", "pid", "clients", "pids", "ack", "failed"])
def test_busy_claim_needs_independent_no_compute_proof(driver, fault):
    driver.busy = True
    if fault == "store":
        driver.store = 1
    elif fault == "pid":
        driver.metadata_pid = 124
    elif fault == "clients":
        driver.clients = (123,)
    elif fault == "pids":
        driver.pids = (123,)
    elif fault == "ack":
        driver.ack_present = True
    else:
        # Channel fixture captures terminal by reference; mutate the expected outcome via port.
        original = controller._wait_terminal

        # Fault does not change immutable frame or historical terminal.
        def failed(captured, unit):
            terminal = original(captured, unit)
            return replace(
                terminal,
                status=FixedUnitStatus("loaded", "failed", "failed", "exit-code", 1, 1, 100, False),
            )

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(controller, "_wait_terminal", failed)
            with pytest.raises(ValueError):
                controller.run_embedding_gpu_batch(driver.captured, source_owner=driver.owner)
        return
    with pytest.raises(ValueError):
        controller.run_embedding_gpu_batch(driver.captured, source_owner=driver.owner)
    assert "STOP" not in driver.events and "grant" not in driver.events


def test_active_peer_fence_is_cheap_and_rejects_process_birth_or_cgroup_change(driver, monkeypatch):
    fence = controller._WorkerFence(driver.captured, driver.original)
    fence.phase = "ACTIVE"
    monkeypatch.setattr(
        controller,
        "inspect_embedding_gpu_batch_unit",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("systemctl per active frame")),
    )
    fence(controller._ACTIVATOR)
    monkeypatch.setattr(
        controller,
        "read_live_runtime_os_file",
        lambda path, **kwargs: (
            process_stat(123, start=457) if path.name == "stat" else b"wrong cgroup"
        ),
    )
    with pytest.raises(ValueError):
        fence(controller._ACTIVATOR)


def test_fast_busy_zombie_requires_original_terminal_not_an_invented_birth(driver, monkeypatch):
    fence = controller._WorkerFence(driver.captured, driver.original)
    calls = []

    def ended(*args, **kwargs):
        calls.append("read-original-terminal")
        return driver.terminal

    monkeypatch.setattr(fence, "_live", lambda: (_ for _ in ()).throw(ValueError("zombie")))
    monkeypatch.setattr(controller, "_wait_terminal", ended)
    fence(controller._ACTIVATOR)
    assert calls == ["read-original-terminal"] and fence.start_ticks == 456
    driver.metadata_pid = 124
    with pytest.raises(ValueError):
        fence(controller._ACTIVATOR)


def test_final_ack_allows_pid1_status_settling_but_not_another_invocation(driver, monkeypatch):
    fence = controller._WorkerFence(driver.captured, driver.original)
    fence.phase = "TERMINATING"
    driver.unit = replace(driver.original, main_pid=0, exited_monotonic=200)
    monkeypatch.setattr(
        controller,
        "observe_embedding_gpu_batch_terminal_metadata",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("terminal must be checked separately")
        ),
    )
    fence(controller._ACTIVATOR)
    driver.unit = replace(driver.unit, invocation_id="c" * 32)
    with pytest.raises(ValueError):
        fence(controller._ACTIVATOR)


def test_terminal_wait_observes_settling_without_extending_numeric_deadline(driver, monkeypatch):
    observations = iter(
        [replace(driver.original, main_pid=0, exited_monotonic=200), driver.terminal]
    )
    sleeps = []
    monkeypatch.setattr(
        controller, "inspect_embedding_gpu_batch_unit", lambda *args, **kwargs: next(observations)
    )
    monkeypatch.setattr(controller.time, "sleep", sleeps.append)
    assert controller._wait_terminal(driver.captured, driver.original) == driver.terminal
    assert sleeps == [0.05]


def test_dispatch_marker_is_exclusive_before_any_start_effect(driver, monkeypatch):
    # Exercise the real function rather than this fixture's flow-level dispatch stub.
    fresh = replace(
        driver.original,
        main_pid=0,
        exited_monotonic=0,
        invocation_id="",
        status=FixedUnitStatus("loaded", "inactive", "dead", "success", 0, 0, 0, False),
    )
    monkeypatch.setattr(
        controller, "inspect_embedding_gpu_batch_unit", lambda *args, **kwargs: fresh
    )
    driver.claim_dispatch(driver.captured)
    with pytest.raises(FileExistsError):
        driver.claim_dispatch(driver.captured)
    assert "socket-start" not in driver.events
    assert json.loads(driver.files["controller-started.json"])["root_pid"] == 456


@pytest.mark.parametrize(
    "action,unit,valid",
    [
        ("start", "eom-embedding-native-gpu-batch@" + "a" * 32 + ".service", True),
        ("stop", "eom-embedding-native-gpu-batch@" + "a" * 32 + ".service", True),
        ("restart", "eom-embedding-native-gpu-batch@" + "a" * 32 + ".service", False),
        ("start", "eom-api.service", False),
    ],
)
def test_socket_effect_is_fixed_and_bounded(monkeypatch, action, unit, valid):
    calls = []

    def run(arguments, **kwargs):
        calls.append(arguments)
        assert kwargs["timeout"] == 10 and kwargs["env"] == controller._ENV
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(controller, "os", SimpleNamespace(getresuid=lambda: (0, 0, 0)))
    monkeypatch.setattr(controller, "subprocess", SimpleNamespace(run=run))
    if valid:
        controller._socket_effect(action, unit)
        assert calls[0] == (
            "/usr/bin/systemctl",
            "--no-ask-password",
            action,
            unit.removesuffix("service") + "socket",
        )
    else:
        with pytest.raises(ValueError):
            controller._socket_effect(action, unit)
        assert not calls
