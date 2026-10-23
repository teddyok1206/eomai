"""Synthetic budget/Unix/kernel-file checks only; no installed admission or model inference."""

from __future__ import annotations

import os
import socket
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_contracts.embedding_device_benchmark import BenchmarkExecutionPolicy
from eom_catalog_service import embedding_benchmark_budget_entrypoint as entry
from eom_catalog_service import embedding_benchmark_channel as channel
from eom_catalog_service import embedding_benchmark_control_channel as control_transport
from eom_catalog_service import embedding_benchmark_launch as launch
from eom_catalog_service import embedding_benchmark_launch_execution as execution
from eom_catalog_service import embedding_benchmark_launch_workspace as workspace
from eom_catalog_service import embedding_benchmark_series_control as series
from eom_catalog_service import embedding_benchmark_unit_control as control
from eom_catalog_service.embedding_benchmark_control_channel import BenchmarkLaunchControlChannel
from eom_catalog_service.embedding_benchmark_launch_publication import (
    BenchmarkLaunchArtifactPublisher,
)
from eom_catalog_service.embedding_benchmark_unit_policy import (
    benchmark_unit_family,
    benchmark_unit_family_from_fragment,
    benchmark_unit_family_from_service,
)
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_identifiers import sha256_bytes
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkLaunchAuthorization
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity
from eom_workflow.embedding_benchmark_launch_control import BenchmarkLaunchAssociation

from tests.unit import test_embedding_device_benchmark_files as file_fixture
from tests.unit import test_embedding_device_benchmark_worker as worker_fixture
from tests.unit.embedding_benchmark_control_fixtures import association
from tests.unit.embedding_device_benchmark_fixtures import (
    benchmark_policy,
    owner_request,
    staged_inputs,
    worker_invocation,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_device_benchmark_budget import (
    successor_invocation,
    successor_invocation_v12,
    successor_policy,
    successor_policy_v12,
    successor_request,
)

ROOT = Path(__file__).resolve().parents[2]


def peer() -> channel.BenchmarkUnixPeer:
    return channel.BenchmarkUnixPeer(os.getpid(), os.getuid(), os.getgid())


def pins(expires_ns: int) -> launch.BenchmarkLaunchPins:
    return launch.BenchmarkLaunchPins(
        "1" * 32,
        "sha256:" + "f" * 64,
        os.getpid(),
        expires_ns,
        NativeEmbeddingBackendPins(
            "embeddingnativeconfig_" + "a" * 32,
            "embeddingnativeconfigrev_" + "b" * 32,
            "sha256:" + "c" * 64,
            "sha256:" + "d" * 64,
            "sha256:" + "e" * 64,
        ),
    )


@pytest.mark.parametrize("device", ("CPU", "CUDA"))
@pytest.mark.parametrize(
    "policy", (None, benchmark_policy(), successor_policy(), successor_policy_v12())
)
def test_selected_unit_family_is_exact_pinned_bytes_and_matching_closed_observations(
    device: Any, policy: BenchmarkExecutionPolicy | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    family = benchmark_unit_family(device, policy)
    expected_seconds = (
        1200
        if policy is not None and policy.timeout_seconds == 1200
        else (600 if policy is not None and policy.timeout_seconds == 600 else 180)
    )
    assert family.timeout_seconds == expected_seconds
    assert sha256_bytes((ROOT / "infra/systemd" / family.service_template).read_bytes()) == (
        family.service_sha256
    )
    assert sha256_bytes((ROOT / "infra/systemd" / family.socket_template).read_bytes()) == (
        family.socket_sha256
    )
    raw = (ROOT / "infra/systemd" / family.service_template).read_text()
    expected_unit_timeout = 1500 if expected_seconds == 1200 else expected_seconds
    assert f"TimeoutStartSec={expected_unit_timeout}\n" in raw
    assert f"-m {family.entrypoint_module} " in raw
    expected_stop = "TimeoutStopSec=10" if expected_seconds == 1200 else "TimeoutStopSec=5"
    for unchanged in ("MemoryMax=6G", "CPUQuota=400%", "TasksMax=64", expected_stop):
        assert unchanged in raw
    fragment = "/etc/systemd/system/" + family.service_template
    service = family.service_template.replace("@.service", "@" + "a" * 32 + ".service")
    assert benchmark_unit_family_from_fragment(device, fragment) == family
    assert benchmark_unit_family_from_service(device, service) == family
    monkeypatch.setattr(control, "require_root_benchmark_control", lambda: None)
    units = control.FixedRootBenchmarkUnits(device, "a" * 32, policy)
    assert units.family == family and units.service == service


@pytest.mark.parametrize(
    "value",
    ("/tmp/eom-embedding-benchmark-cpu@.service", "latest", "", None, True),
)
def test_unknown_fragment_is_not_a_budget_or_retirement_authority(value: Any) -> None:
    with pytest.raises(ValueError):
        benchmark_unit_family_from_fragment("CPU", value)


@pytest.mark.parametrize(
    "value",
    (
        "eom-embedding-benchmark-cpu-budget600@" + "A" * 32 + ".service",
        "eom-embedding-benchmark-cpu-budget600@" + "a" * 31 + ".service",
        "eom-embedding-benchmark-cuda-budget600@" + "a" * 32 + ".service",
        "eom-embedding-benchmark-cpu-budget900@" + "a" * 32 + ".service",
        "eom-embedding-benchmark-cpu-budget600@../x.service",
        True,
    ),
)
def test_service_selection_rejects_cross_device_or_invented_family_and_instance(value: Any) -> None:
    with pytest.raises(ValueError):
        benchmark_unit_family_from_service("CPU", value)


@pytest.mark.parametrize("new", (False, True))
@pytest.mark.parametrize("overrun", (False, True))
def test_socket_activation_uses_exact_policy_budget_not_caller_duration(
    new: bool, overrun: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = successor_policy() if new else benchmark_policy()
    now = 10**12
    monkeypatch.setattr(launch, "time", SimpleNamespace(monotonic_ns=lambda: now))
    monkeypatch.setenv("LISTEN_PID", str(os.getpid()))
    monkeypatch.setenv("LISTEN_FDS", "1")
    monkeypatch.setenv("LISTEN_FDNAMES", "benchmark-control")
    closed: list[int] = []
    monkeypatch.setattr(os, "close", closed.append)
    value = pins(now + policy.timeout_seconds * 10**9 + int(overrun))
    if overrun:
        with pytest.raises(ValueError), launch.benchmark_socket_activation(value, policy=policy):
            pytest.fail("overrun took activation ownership")
        assert closed == []
    else:
        with launch.benchmark_socket_activation(value, policy=policy):
            pass
        assert closed == [3]


@pytest.mark.parametrize("new", (False, True))
@pytest.mark.parametrize("cleanup", (False, True))
@pytest.mark.parametrize("overrun", (False, True))
def test_frames_compute_and_cleanup_are_selected_from_released_policy(
    new: bool, cleanup: bool, overrun: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = successor_policy() if new else benchmark_policy()
    now = 10**12
    monkeypatch.setattr(channel, "time", SimpleNamespace(monotonic_ns=lambda: now))
    bound = policy.timeout_seconds + (30 if cleanup else 0)
    left, right = socket.socketpair()
    try:
        if overrun:
            with pytest.raises(ValueError):
                channel._Frames(
                    left,
                    peer(),
                    lambda _: None,
                    now + bound * 10**9 + 1,
                    policy=policy,
                    maximum_lifetime_seconds=bound,
                )
            assert left.fileno() == -1
        else:
            frames = channel._Frames(
                left,
                peer(),
                lambda _: None,
                now + bound * 10**9,
                policy=policy,
                maximum_lifetime_seconds=bound,
            )
            frames.close()
    finally:
        left.close()
        right.close()


def test_scalar600_without_released_policy_cannot_extend_private_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 10**12
    monkeypatch.setattr(channel, "time", SimpleNamespace(monotonic_ns=lambda: now))
    left, right = socket.socketpair()
    try:
        with pytest.raises(ValueError):
            channel._Frames(
                left, peer(), lambda _: None, now + 600 * 10**9, maximum_lifetime_seconds=600
            )
        assert left.fileno() == -1
    finally:
        left.close()
        right.close()


@pytest.mark.parametrize("new", (False, True))
def test_control_transport_uses_original_association_deadline_plus_cleanup_only(
    new: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = successor_policy() if new else benchmark_policy()
    now = 10**12
    monkeypatch.setattr(channel, "time", SimpleNamespace(monotonic_ns=lambda: now))
    association_fixture: Any = association
    value = BenchmarkLaunchAssociation.model_validate(
        seal(
            association_fixture().model_dump(mode="json")
            | {"expires_ns": now + policy.timeout_seconds * 10**9},
            "association_sha256",
        )
    )
    left, right = socket.socketpair()
    try:
        control_channel = BenchmarkLaunchControlChannel(
            left,
            value,
            side="OWNER",
            expected_peer=peer(),
            peer_fence=lambda _: None,
            controller_release="a" * 40,
            policy=policy,
        )
        assert control_channel._transport().expires_ns == value.expires_ns + 30 * 10**9
        control_channel.close()
    finally:
        left.close()
        right.close()


@pytest.mark.parametrize("new", (False, True))
@pytest.mark.parametrize("overrun", (False, True))
def test_root_listener_selection_lifetime_is_separate_from_compute_and_authentication(
    new: bool, overrun: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 10**12
    request = successor_request() if new else owner_request()
    bound = 3600 if new else 900
    monkeypatch.setattr(series, "time", SimpleNamespace(monotonic_ns=lambda: now))
    monkeypatch.setattr(series, "require_root_benchmark_control", lambda: None)
    monkeypatch.setattr(
        series, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.getuid(), os.getgid())
    )
    monkeypatch.setattr(series, "benchmark_owner_start_ticks", lambda *a, **k: 1)
    backend = pins(now).backend
    kwargs: dict[str, Any] = dict(
        request=request,
        owner_pid=os.getpid(),
        owner_start_ticks=1,
        accept_until_ns=now + bound * 10**9 + int(overrun),
        cpu=backend,
        cuda=replace(backend, configuration_revision_id="embeddingnativeconfigrev_" + "e" * 32),
        controller_release="a" * 40,
    )
    if overrun:
        with pytest.raises(ValueError):
            series.BenchmarkRootSeriesSelection(**kwargs)
    else:
        selected = series.BenchmarkRootSeriesSelection(**kwargs)
        assert selected.accept_until_ns == now + bound * 10**9
        assert request.execution_policy.timeout_seconds == (600 if new else 180)


@pytest.mark.parametrize("new", (False, True))
def test_root_receives_association_under_exact_selected_policy_only(
    new: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    import struct

    from eom_workflow.embedding_benchmark_launch_control import benchmark_launch_control_bytes

    now = 10**12
    policy = successor_policy() if new else benchmark_policy()
    fixture: Any = association
    value = BenchmarkLaunchAssociation.model_validate(
        seal(
            fixture().model_dump(mode="json") | {"expires_ns": now + 600 * 10**9},
            "association_sha256",
        )
    )
    for module in (channel, control_transport):
        monkeypatch.setattr(module, "time", SimpleNamespace(monotonic_ns=lambda: now))
    left, right = socket.socketpair()
    raw = benchmark_launch_control_bytes(value)
    right.sendall(struct.pack("!I", len(raw)) + raw)
    try:
        kwargs: dict[str, Any] = dict(
            expected_peer=peer(),
            peer_fence=lambda _: None,
            controller_release="a" * 40,
            accept_until_ns=now + (3600 if new else 900) * 10**9,
            policy=policy,
        )
        if new:
            accepted = BenchmarkLaunchControlChannel.accept_root_association(left, **kwargs)
            assert accepted.association == value
            accepted.close()
        else:
            with pytest.raises(ValueError):
                BenchmarkLaunchControlChannel.accept_root_association(left, **kwargs)
            assert left.fileno() == -1
    finally:
        left.close()
        right.close()


@pytest.mark.parametrize("new", (False, True))
def test_staging_actual_policy_controls_deadline_before_materialization(
    new: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = successor_request() if new else owner_request()
    invocation = successor_invocation() if new else worker_invocation()
    now = 10**12
    monkeypatch.setattr(workspace, "time", SimpleNamespace(monotonic_ns=lambda: now))
    monkeypatch.setattr(workspace, "BENCHMARK_OWNER_ROOT", tmp_path)
    monkeypatch.setattr(
        workspace, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.getuid(), os.getgid())
    )
    monkeypatch.setattr(workspace, "benchmark_owner_start_ticks", lambda *a, **k: 1)
    monkeypatch.setattr(BenchmarkLaunchAuthorization, "assert_invocation", lambda *a: None)
    authorization = object.__new__(BenchmarkLaunchAuthorization)
    seconds = request.execution_policy.timeout_seconds
    with pytest.raises(ValueError, match="DEADLINE"):
        workspace.stage_owner_benchmark_launch(
            request,
            invocation,
            staged_inputs(),
            authorization=authorization,
            expires_ns=now + seconds * 10**9 + 1,
        )
    assert not list(tmp_path.iterdir())
    staged = workspace.stage_owner_benchmark_launch(
        request,
        invocation,
        staged_inputs(),
        authorization=authorization,
        expires_ns=now + seconds * 10**9,
    )
    assert workspace.read_owner_benchmark_launch(invocation.execution_id) == staged


@pytest.mark.parametrize("ordinal", (1, 2, 3, 4, 5, 6))
def test_budget600_runs_unchanged_full_and_cold_program_with_synthetic_backend(
    ordinal: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(file_fixture, "worker_invocation", successor_invocation)
    monkeypatch.setattr(worker_fixture, "worker_invocation", successor_invocation)
    result, backend, events, _root, checkpoints = worker_fixture.run_scenario(
        tmp_path, monkeypatch, ordinal, deadline_seconds=300
    )
    assert result.status == "COMPLETED"
    assert result.invocation_sha256 == successor_invocation(ordinal).invocation_sha256
    assert len(checkpoints) == (21 if ordinal in (1, 2) else 1)
    assert backend.closed and events.count("constructor") == 1


@pytest.mark.parametrize("fault", (None, "legacy", "other_unit", "foreign_invocation"))
def test_new_entry_binds_real_invocation_and_exact_unit_before_old_leaf_execution(
    fault: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = worker_invocation() if fault == "legacy" else successor_invocation()
    selection = pins(10**18)
    events: list[str] = []

    class Files:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            events.append("capture")

        def __enter__(self) -> Files:
            return self

        def __exit__(self, *args: Any) -> None:
            events.append("close")

        def read_invocation(self) -> Any:
            return successor_invocation(4) if fault == "foreign_invocation" else value

    monkeypatch.setattr(entry, "BenchmarkWorkerLocalFiles", Files)
    family = benchmark_unit_family("CPU", successor_policy())
    unit = family.service_template.replace("@.service", "@" + "1" * 32 + ".service")
    monkeypatch.setattr(
        entry,
        "read_live_runtime_os_file",
        lambda *a, **k: (
            f"0::/system.slice/{unit}\n" if fault != "other_unit" else "0::/other.service\n"
        ).encode(),
    )

    @contextmanager
    def activation(*args: Any, **kwargs: Any) -> Any:
        assert kwargs["policy"] == successor_policy()
        events.append("activation")
        yield

    monkeypatch.setattr(entry, "benchmark_socket_activation", activation)

    def execute(*args: Any) -> int:
        events.append("execute")
        return 0

    if fault is None:
        assert (
            entry.execute_budget600_benchmark(
                selection, 1, profile="CPU_INDEX_FP32", execute=execute
            )
            == 0
        )
        assert events == ["capture", "close", "activation", "execute"]
    else:
        with pytest.raises(ValueError):
            entry.execute_budget600_benchmark(
                selection, 1, profile="CPU_INDEX_FP32", execute=execute
            )
        assert events == ["capture", "close"]


@pytest.mark.parametrize("profile,device", (("CPU_INDEX_FP32", "CPU"), ("CUDA_INDEX_FP32", "CUDA")))
def test_v12_budget_entry_binds_1200_second_invocation_and_dedicated_unit(
    profile: str, device: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    ordinal = 1 if device == "CPU" else 2
    value = successor_invocation_v12(ordinal)
    selection = replace(pins(10**18), execution_id=value.execution_id)

    class Files:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            events.append("capture")

        def __enter__(self) -> Files:
            return self

        def __exit__(self, *args: Any) -> None:
            events.append("close")

        def read_invocation(self) -> Any:
            return value

    family = benchmark_unit_family(device, successor_policy_v12())
    unit = family.service_template.replace("@.service", "@" + value.execution_id + ".service")
    monkeypatch.setattr(entry, "BenchmarkWorkerLocalFiles", Files)
    monkeypatch.setattr(
        entry, "read_live_runtime_os_file", lambda *a, **k: f"0::/system.slice/{unit}\n".encode()
    )

    @contextmanager
    def activation(*args: Any, **kwargs: Any) -> Any:
        assert kwargs["policy"] == successor_policy_v12()
        events.append("activation")
        yield

    monkeypatch.setattr(entry, "benchmark_socket_activation", activation)

    def execute(*args: Any) -> int:
        events.append("execute")
        return 0

    assert (
        entry.execute_budget_benchmark(
            selection, 1, profile=profile, timeout_seconds=1200, execute=execute
        )
        == 0
    )
    assert events == ["capture", "close", "activation", "execute"]


@pytest.mark.parametrize("missing", (None, "embedding_benchmark_budget_entrypoint.py"))
def test_owner600_preflight_requires_explicit_installed_successor_entries_before_reservation(
    missing: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    members: list[str] = []
    templates: list[str] = []

    class Files:
        def __init__(self, uid: int) -> None:
            assert uid == 0

        def read(self, path: Path, **kwargs: Any) -> bytes:
            templates.append(path.name)
            raw = (ROOT / "infra/systemd" / path.name).read_bytes()
            assert sha256_bytes(raw) == kwargs["sha256"]
            return raw

        def observe_protected_member_identity(self, path: Path) -> None:
            members.append(path.name)
            if path.name == missing:
                raise ValueError("synthetic missing installed successor")

        def assert_unchanged(self) -> None:
            pass

    monkeypatch.setattr(execution, "NumericalRuntimeFileSnapshots", Files)
    monkeypatch.setattr(execution, "require_benchmark_series_listener", lambda _: None)
    monkeypatch.setattr(
        execution, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.getuid(), os.getgid())
    )
    monkeypatch.setattr(
        execution, "capture_benchmark_runtime_installation", lambda *a, **k: Files(0)
    )
    request = successor_request()
    publication_port: Any = SimpleNamespace()
    publisher = BenchmarkLaunchArtifactPublisher(publication_port, source_commit="a" * 40)
    selected = execution.FixedBenchmarkLaunchExecution(
        request,
        cpu=pins(1).backend,
        cuda=pins(1).backend,
        controller_release="a" * 40,
        publisher=publisher,
    )
    if missing:
        with pytest.raises(ValueError, match="missing installed"):
            selected.assert_installed(request)
        return
    selected.assert_installed(request)
    assert len(templates) == 4 and all("budget600" in name for name in templates)
    assert members.count("embedding_benchmark_entrypoint.py") == 2
    assert members.count("embedding_benchmark_budget_entrypoint.py") == 2
    assert "embedding_benchmark_budget600_cpu.py" in members
    assert "embedding_benchmark_budget600_cuda.py" in members
