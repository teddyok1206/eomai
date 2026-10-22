"""600-second routing over synthetic protected metadata/kernel ports; no GPU or root effect."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_benchmark_cuda_ready import BenchmarkCudaReady
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
)
from eom_catalog_service import embedding_benchmark_cuda_lifetime as lifetime
from eom_catalog_service import embedding_benchmark_cuda_observation as observation
from eom_catalog_service import embedding_cuda_probe_resource_observation as resources
from eom_catalog_service.embedding_benchmark_launch import benchmark_launch_environment_bytes
from eom_catalog_service.embedding_benchmark_unit_policy import (
    benchmark_unit_family,
    benchmark_unit_family_from_fragment,
    benchmark_unit_family_from_service,
)
from eom_identifiers import sha256_bytes

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_cuda_observation import benchmark as benchmark
from tests.unit.test_embedding_benchmark_cuda_observation import observe
from tests.unit.test_embedding_cuda_probe_resource_observation import benchmark_report
from tests.unit.test_embedding_cuda_probe_resource_observation import case as case
from tests.unit.test_embedding_cuda_probe_resource_observation import kernel as kernel
from tests.unit.test_embedding_cuda_probe_resource_observation import ready_case as ready_case
from tests.unit.test_embedding_device_benchmark_budget import successor_policy
from tests.unit.test_embedding_native_probe_observation import ledger as ledger
from tests.unit.test_embedding_native_probe_observation import running

ROOT = Path(__file__).resolve().parents[2]


def budget_family():
    return benchmark_unit_family("CUDA", successor_policy())


def budget_unit(execution_id):
    return budget_family().service_template.replace("@.service", f"@{execution_id}.service")


def budget_launch_basis(state):
    body = state.invocation.model_dump(mode="json")
    body.update(
        schema_version="embedding-device-benchmark-invocation/1.1",
        execution_policy=successor_policy().model_dump(mode="json"),
    )
    invocation = BenchmarkWorkerInvocation.model_validate(seal(body, "invocation_sha256"))
    raw = embedding_device_benchmark_bytes(invocation)
    pins = replace(state.pins, invocation_raw_sha256=sha256_bytes(raw))
    env_raw = benchmark_launch_environment_bytes(pins)
    environment = replace(state.environment, environment_raw_sha256=sha256_bytes(env_raw))
    parent = observation._ROOT / invocation.execution_id
    state.files[parent / "invocation.json"] = raw
    state.files[parent / "launch.env"] = env_raw
    family = budget_family()
    for name in (family.service_template, family.socket_template):
        state.files[Path("/etc/systemd/system") / name] = (
            ROOT / "infra/systemd" / name
        ).read_bytes()
    staging_member = (
        "lib/python3.12/site-packages/eom_catalog_service/embedding_device_benchmark_files.py"
    )
    inventory = replace(
        state.inventory,
        entries=tuple(
            replace(entry, sha256=observation._READY_IMPLEMENTATIONS_V11[0][1])
            if entry.relative_member == staging_member
            else entry
            for entry in state.inventory.entries
        ),
    )
    return invocation, environment, inventory, pins


def test_actual_launch_capture_selects_new_pinned_service_socket_only_for_explicit_policy(
    benchmark,
):
    state = benchmark
    invocation, environment, inventory, pins = budget_launch_basis(state)
    family = budget_family()
    captured = observation.capture_benchmark_cuda_launch_files(
        invocation, environment, backend=state.backend, inventory=inventory
    )
    assert captured.service_template == family.service_template
    assert captured.pins == pins
    assert state.resource_calls == state.policy_calls == state.ready_reads == 0
    assert state.reads[:2] == [
        Path("/etc/systemd/system") / family.service_template,
        Path("/etc/systemd/system") / family.socket_template,
    ]


@pytest.mark.parametrize("seconds", (180, 600))
def test_legacy_and_budget_policy_cannot_borrow_the_other_prefix_staging_source(benchmark, seconds):
    state = benchmark
    if seconds == 600:
        invocation, environment, inventory, _pins = budget_launch_basis(state)
        foreign_digest = observation._READY_IMPLEMENTATIONS[0][1]
    else:
        invocation, environment, inventory = state.invocation, state.environment, state.inventory
        foreign_digest = observation._READY_IMPLEMENTATIONS_V11[0][1]
    inventory = replace(
        inventory,
        entries=tuple(
            replace(entry, sha256=foreign_digest)
            if entry.relative_member.endswith("/embedding_device_benchmark_files.py")
            else entry
            for entry in inventory.entries
        ),
    )
    with pytest.raises(ValueError, match="ENTRY_SOURCE_MISMATCH"):
        observation.capture_benchmark_cuda_launch_files(
            invocation, environment, backend=state.backend, inventory=inventory
        )
    assert state.reads == []
    assert state.resource_calls == state.policy_calls == state.ready_reads == 0


@pytest.mark.parametrize("seconds", (180, 600))
def test_observed_exact_fragment_selects_the_same_closed_cleanup_family(seconds):
    family = benchmark_unit_family("CUDA", None if seconds == 180 else successor_policy())
    unit = replace(running(), fragment_path="/etc/systemd/system/" + family.service_template)
    execution = "a" * 32
    expected = family.service_template.replace("@.service", f"@{execution}.service")
    assert observation.benchmark_cuda_unit_template(unit) == family.service_template
    assert observation.benchmark_cuda_unit_name(unit, execution) == expected
    assert benchmark_unit_family_from_service("CUDA", expected) == family


@pytest.mark.parametrize("which", ("capture", "observation"))
def test_pinned_capture_and_actual_fragment_must_not_cross_policy_families(benchmark, which):
    state = benchmark
    ready = observe(state)
    captured = observation.capture_benchmark_cuda_pinned_files(
        state.invocation, state.environment, backend=state.backend, inventory=state.inventory
    )
    if which == "capture":
        captured = replace(captured, service_template=budget_family().service_template)
    else:
        ready = replace(
            ready,
            unit=replace(
                ready.unit, fragment_path="/etc/systemd/system/" + budget_family().service_template
            ),
            cgroup="/system.slice/" + budget_unit(ready.execution_id),
        )
    before = state.resource_calls, state.policy_calls, tuple(state.reads)
    with pytest.raises(ValueError, match="PINNED_TEMPLATE_CHANGED"):
        observation.require_benchmark_cuda_observation_basis(ready, captured)
    assert (state.resource_calls, state.policy_calls, tuple(state.reads)) == before


@pytest.mark.parametrize(
    "fragment",
    (
        "/etc/systemd/system/eom-embedding-benchmark-cuda-budget601@.service",
        "/etc/systemd/system/eom-embedding-benchmark-cpu-budget600@.service",
        "/usr/lib/systemd/system/eom-embedding-benchmark-cuda-budget600@.service",
        "/etc/systemd/system/eom-embedding-benchmark-cuda-budget600@" + "a" * 32 + ".service",
        "/etc/systemd/system/../system/eom-embedding-benchmark-cuda-budget600@.service",
    ),
)
def test_unknown_or_other_purpose_fragment_is_not_a_cuda_cleanup_identity(fragment):
    with pytest.raises(ValueError, match="BENCHMARK_UNIT_IDENTITY_INVALID"):
        benchmark_unit_family_from_fragment("CUDA", fragment)
    with pytest.raises(ValueError, match="BENCHMARK_UNIT_IDENTITY_INVALID"):
        observation.benchmark_cuda_unit_name(replace(running(), fragment_path=fragment), "a" * 32)


@pytest.mark.parametrize(
    "unit",
    (
        "eom-embedding-benchmark-cuda-budget601@" + "a" * 32 + ".service",
        "eom-embedding-benchmark-cpu-budget600@" + "a" * 32 + ".service",
        "eom-embedding-benchmark-cuda-budget600@" + "a" * 31 + ".service",
        "eom-embedding-benchmark-cuda-budget600@" + "A" * 32 + ".service",
        "eom-embedding-benchmark-cuda-budget600@" + "a" * 32 + ".socket",
        "eom-embedding-benchmark-cuda-budget600@../wrong.service",
        "eom-embedding-benchmark-cuda-budget600@" + "a" * 32 + ".service\n",
    ),
)
def test_unknown_service_or_instance_is_rejected_before_any_lifetime_effect(monkeypatch, unit):
    monkeypatch.setattr(lifetime.os, "getresuid", lambda: (0, 0, 0))
    command = Mock(side_effect=AssertionError("unit command before exact family guard"))
    monkeypatch.setattr(lifetime.subprocess, "run", command)
    with pytest.raises(ValueError, match="BENCHMARK_UNIT_IDENTITY_INVALID"):
        lifetime._effect("ACK", unit)
    command.assert_not_called()


def test_budget_ready_and_retained_readers_apply_the_same_actual_worker_pid1_inode_fences(kernel):
    report = benchmark_report(kernel)
    unit = budget_unit(report.execution_id)
    kernel[2]["expected_unit"] = unit
    observed = resources.observe_benchmark_cuda_ready_resources(report, unit=unit, lease_gid=2468)
    assert observed.pid1_descriptor == 80
    assert observed.shared_gpu_lease.holder_pid == report.pid
    kernel[2]["unheld_worker"] = True
    assert resources.observe_benchmark_cuda_retained_resources(observed, unit=unit) is observed
    with pytest.raises(ValueError):
        resources.observe_cuda_probe_retained_resources(observed, unit=unit)
    # The private6c4 candidate intentionally does not backport native CUDA INDEX APIs.
    assert not hasattr(resources, "observe_native_cuda_index_retained_resources")


def test_budget_pre_ack_terminal_resource_read_has_no_fabricated_worker_birth(kernel):
    report = benchmark_report(kernel)
    unit = budget_unit(report.execution_id)
    kernel[2]["expected_unit"] = unit
    kernel[2]["unheld_worker"] = True
    observed = resources.observe_unacknowledged_benchmark_gpu_resources(
        unit=unit, terminal_pid=report.pid, lease_gid=2468
    )
    assert observed.pid1_descriptor == 80 and observed.shared_gpu_lease.holder_pid == report.pid
    assert not hasattr(observed.shared_gpu_lease, "holder_start_time_ticks")


@pytest.mark.parametrize("purpose", ("ready", "retained", "unacknowledged"))
@pytest.mark.parametrize("fault", ("unknown_family", "wrong_instance", "wrong_purpose"))
def test_invalid_budget_resource_identity_is_rejected_before_kernel_or_gpu_reads(
    kernel, monkeypatch, purpose, fault
):
    report = benchmark_report(kernel)
    original_unit = budget_unit(report.execution_id)
    kernel[2]["expected_unit"] = original_unit
    observed = resources.observe_benchmark_cuda_ready_resources(
        report, unit=original_unit, lease_gid=2468
    )
    unit = original_unit
    if fault == "unknown_family":
        unit = unit.replace("budget600", "budget601")
    elif fault == "wrong_purpose":
        unit = unit.replace("benchmark-cuda-budget600", "native-cuda-probe")
    elif purpose == "ready":
        unit = budget_unit("f" * 32)
    else:
        unit = unit.replace("@", "@invalid-")
    kernel_reader = Mock(side_effect=AssertionError("kernel read before exact identity guard"))
    monkeypatch.setattr(resources, "_observe_native_report_resources", kernel_reader)
    monkeypatch.setattr(resources, "_assert_retained_resources", kernel_reader)
    monkeypatch.setattr(resources, "_named_device_nodes", kernel_reader)
    with pytest.raises(ValueError, match="BENCHMARK_CUDA_RESOURCE_OBSERVATION_INVALID"):
        if purpose == "ready":
            resources.observe_benchmark_cuda_ready_resources(report, unit=unit, lease_gid=2468)
        elif purpose == "retained":
            resources.observe_benchmark_cuda_retained_resources(observed, unit=unit)
        else:
            resources.observe_unacknowledged_benchmark_gpu_resources(
                unit=unit, terminal_pid=report.pid, lease_gid=2468
            )
    kernel_reader.assert_not_called()


def test_budget_resource_extension_does_not_accept_a_different_report_message(kernel, monkeypatch):
    prototype = kernel[0]
    unit = budget_unit(prototype.execution_id)
    kernel_reader = Mock(side_effect=AssertionError("kernel read before exact message guard"))
    monkeypatch.setattr(resources, "_observe_native_report_resources", kernel_reader)
    with pytest.raises(ValueError, match="BENCHMARK_CUDA_RESOURCE_OBSERVATION_INVALID"):
        resources.observe_benchmark_cuda_ready_resources(prototype, unit=unit, lease_gid=2468)
    with pytest.raises(ValueError):
        resources.observe_cuda_probe_resources(prototype, unit=unit, lease_gid=2468)
    assert type(prototype) is not BenchmarkCudaReady
    kernel_reader.assert_not_called()
