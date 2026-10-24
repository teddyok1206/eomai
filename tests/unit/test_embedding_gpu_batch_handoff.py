"""Root handoff guards before filesystem effects; no root privilege or model work."""

from __future__ import annotations

import os
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_gpu_control import embedding_gpu_control_bytes
from eom_catalog_service import embedding_gpu_batch_handoff as handoff
from eom_identifiers import sha256_bytes
from eom_orchestrator import inference_transfer_cpu_handoff as shared

from tests.unit.test_embedding_gpu_batch_launch import launch_pins
from tests.unit.test_embedding_gpu_control import control_case


def case(monkeypatch):
    original = control_case(expires_ns=time.monotonic_ns() + 30 * 10**9)
    pins = replace(
        launch_pins(),
        root_pid=os.getpid(),
        allocation_raw_sha256=sha256_bytes(embedding_gpu_control_bytes(original[0])),
        resource_profile_sha256=original[6].resource_profile_sha256,
    )
    monkeypatch.setattr(
        handoff, "os", SimpleNamespace(getresuid=lambda: (0, 0, 0), getpid=lambda: pins.root_pid)
    )
    monkeypatch.setattr(
        handoff, "fixed_owner_identity", lambda: pytest.fail("invalid binding reached filesystem")
    )
    return pins, original


@pytest.mark.parametrize(
    "fault", ["nonroot", "partial_root", "pid", "hash", "attempt", "backend", "expired", "extra"]
)
def test_invalid_original_allocation_cannot_prepare_any_files(monkeypatch, fault):
    pins, original = case(monkeypatch)
    request = original[0]
    if fault in ("nonroot", "partial_root"):
        identity = (1234, 1234, 1234) if fault == "nonroot" else (0, 1234, 0)
        monkeypatch.setattr(handoff.os, "getresuid", lambda: identity)
    elif fault == "pid":
        pins = replace(pins, root_pid=pins.root_pid + 1)
    elif fault == "hash":
        pins = replace(pins, allocation_raw_sha256="sha256:" + "b" * 64)
    elif fault == "attempt":
        pins = replace(pins, attempt_hex="b" * 32)
    elif fault == "backend":
        pins = replace(pins, backend=replace(pins.backend, receipt_raw_sha256="sha256:" + "b" * 64))
    elif fault == "expired":
        monkeypatch.setattr(time, "monotonic_ns", lambda: request.expires_monotonic_ns)
    else:
        request = request.model_copy(update={"authority": "ROOT"})
    with pytest.raises(ValueError):
        handoff.prepare_embedding_gpu_batch_handoff(pins, request)


@pytest.mark.parametrize("fault", ["profile", "timeout", "vectors"])
def test_late_bound_batch_must_fit_original_fixed_resources_before_intent(monkeypatch, fault):
    pins, original = case(monkeypatch)
    if fault == "profile":
        pins = replace(pins, resource_profile_sha256="sha256:" + "b" * 64)
    elif fault == "timeout":
        pins = replace(pins, timeout_seconds=1)
    else:
        pins = replace(pins, vector_max_bytes=4)
    prepared = handoff.PreparedEmbeddingGpuBatch(pins, original[0], (0,) * 9)
    with pytest.raises(ValueError):
        handoff.bind_embedding_gpu_batch_handoff(prepared, original[3], original[6])


def test_new_late_bound_primitive_never_relaxes_original_nonempty_input(monkeypatch):
    owner = shared.CpuHandoffIdentity(1234, 1234)
    monkeypatch.setattr(shared, "os", SimpleNamespace(geteuid=lambda: 0))
    monkeypatch.setattr(
        shared,
        "_create_native_descriptor_files",
        lambda *args, **kwargs: pytest.fail("empty legacy input reached writer"),
    )
    with pytest.raises(shared.CpuHandoffError, match="INPUT_INVALID"):
        shared.create_native_cpu_descriptor_handoff(
            handoff.GPU_BATCH_RUNTIME_ROOT, "a" * 32, b"", owner=owner
        )
