"""Image-specific consumers of the shared synthetic PID1/worker FD observation ports."""

from __future__ import annotations

import dataclasses

import pytest
from eom_catalog_service import embedding_cuda_probe_resource_observation as owner
from eom_identifiers import canonical_json_bytes
from pydantic import TypeAdapter

from tests.unit.test_embedding_cuda_probe_resource_observation import kernel as kernel
from tests.unit.test_embedding_cuda_probe_resource_observation import released as released
from tests.unit.test_embedding_native_cuda_probe import case as case
from tests.unit.test_embedding_native_cuda_probe_ready import ready_case as ready_case

UNIT = "eom-image-provider@imgreq_" + "a" * 32 + ".service"


def observe(kernel):
    ready, _, state, _ = kernel
    state["expected_unit"] = UNIT
    return owner.observe_image_unit_gpu_resources(
        unit=UNIT,
        pid=ready.pid,
        start_time_ticks=ready.start_time_ticks,
        worker_uid=ready.worker_uid,
        lease_gid=ready.supplementary_gids[0],
    )


def test_image_finds_actual_lock_fd_without_a_worker_report_or_broadening_probe_identity(kernel):
    observed = observe(kernel)
    assert type(observed) is owner.ImageUnitGpuResources
    assert observed.pid1_descriptor == 80
    assert observed.shared_gpu_lease.holder_pid == 123
    assert not hasattr(observed, "assert_owned")
    assert not hasattr(observed, "acknowledge")
    with pytest.raises(ValueError):
        owner.observe_cuda_probe_retained_resources(observed, unit=UNIT)


def test_image_retained_readback_does_not_read_dead_worker_fds_or_release_store(kernel):
    observed = observe(kernel)
    kernel[2]["worker_fds"] = []
    kernel[2]["unheld_worker"] = True
    assert owner.observe_image_unit_gpu_retained_resources(observed, unit=UNIT) == observed


@pytest.mark.parametrize(
    "fault",
    [
        "missing_worker",
        "duplicate_worker",
        "invalid_worker_name",
        "too_many_worker",
        "unheld_worker",
        "unheld_pid1",
        "missing_pid1",
        "duplicate_pid1",
    ],
)
def test_image_missing_or_ambiguous_or_unheld_resources_do_not_pass(kernel, monkeypatch, fault):
    state = kernel[2]
    if fault == "missing_worker":
        state["worker_fds"] = []
    elif fault == "duplicate_worker":
        state["worker_fds"] = ["14", "15"]
        state["worker_lock_fds"] = {14, 15}
    elif fault == "invalid_worker_name":
        state["worker_fds"] = ["../14"]
    elif fault == "too_many_worker":
        monkeypatch.setattr(owner, "_MAX_IMAGE_WORKER_FDS", 1)
        state["worker_fds"] = ["10", "14"]
    elif fault in {"unheld_worker", "unheld_pid1"}:
        state[fault] = True
    elif fault == "missing_pid1":
        state["pid1"] = []
    else:
        state["pid1"] = ["80", "81"]
    with pytest.raises(ValueError):
        observe(kernel)


def test_nonroot_and_unknown_unit_cannot_observe_image_resources(kernel, monkeypatch):
    ready = kernel[0]
    with pytest.raises(ValueError):
        owner.observe_image_unit_gpu_resources(
            unit="eom-image-new-unknown@x.service",
            pid=ready.pid,
            start_time_ticks=ready.start_time_ticks,
            worker_uid=ready.worker_uid,
            lease_gid=2468,
        )
    monkeypatch.setattr(owner.os, "getresuid", lambda: (1000, 1000, 1000))
    with pytest.raises(ValueError):
        observe(kernel)


def test_existing_cuda_observation_fields_and_serialized_bytes_remain_unchanged(kernel):
    image = observe(kernel)
    cuda = owner.CudaProbeResourceObservation(
        image.device_nodes, image.shared_gpu_lease, image.pid1_descriptor
    )
    assert tuple(field.name for field in dataclasses.fields(cuda)) == (
        "device_nodes",
        "shared_gpu_lease",
        "pid1_descriptor",
    )
    raw = canonical_json_bytes(TypeAdapter(type(cuda)).dump_python(cuda, mode="json"))
    assert raw == canonical_json_bytes(TypeAdapter(type(image)).dump_python(image, mode="json"))
    assert TypeAdapter(type(cuda)).validate_json(raw) == cuda


def test_image_release_reuses_same_exclusive_hold_without_unlocking_borrowed_description(released):
    cuda, _, _, events = released
    image = owner.ImageUnitGpuResources(
        cuda.device_nodes, cuda.shared_gpu_lease, cuda.pid1_descriptor
    )
    with owner.hold_released_image_unit_gpu_resources(image):
        assert events == ["open", "flock"]
        events.append("post-check")
    assert events == ["open", "flock", "post-check", "close"]


def test_image_release_does_not_claim_success_while_pid1_still_retains_lock(released):
    cuda, _, state, events = released
    state["still_retained"] = True
    image = owner.ImageUnitGpuResources(
        cuda.device_nodes, cuda.shared_gpu_lease, cuda.pid1_descriptor
    )
    with (
        pytest.raises(ValueError, match="RELEASE_UNCERTAIN"),
        owner.hold_released_image_unit_gpu_resources(image),
    ):
        pytest.fail("retained physical lock was treated as released")
    assert events == ["open", "flock", "close"]
