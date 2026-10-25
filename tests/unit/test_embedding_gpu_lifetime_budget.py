"""Total allocation vs numeric budget; no actual runtime, GPU or privilege proof."""

import os
import socket
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_gpu_control import (
    EMBEDDING_GPU_CONTROLLER_UNIT_SECONDS,
    EMBEDDING_GPU_WORKER_UNIT_SECONDS,
    MAX_EMBEDDING_GPU_ALLOCATION_SECONDS,
    EmbeddingGpuControlError,
    embedding_gpu_allocation_window_seconds,
    embedding_gpu_control_bytes,
    parse_embedding_gpu_control_bytes,
)
from eom_catalog_contracts.embedding_work_batch import MAX_EMBEDDING_WORK_BATCH_SECONDS
from eom_catalog_service import embedding_batch_control_workspace as control_workspace
from eom_catalog_service import embedding_gpu_batch_observation as observation
from eom_catalog_service.embedding_batch_control_connection import BATCH_CONTROL_TEMPLATE_SHA256
from eom_catalog_service.embedding_benchmark_channel import (
    BenchmarkChannelError,
    BenchmarkUnixPeer,
    FrameLifetimeProfile,
    _Frames,
)
from eom_identifiers import sha256_bytes

from tests.unit.test_embedding_gpu_control import control_case

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("numeric", (1, 30, 180))
def test_total_window_adds_bounded_control_allowance_without_raising_compute_limit(numeric):
    assert embedding_gpu_allocation_window_seconds(numeric) == 240 + numeric
    assert MAX_EMBEDDING_WORK_BATCH_SECONDS == 180
    assert MAX_EMBEDDING_GPU_ALLOCATION_SECONDS == 420
    assert EMBEDDING_GPU_WORKER_UNIT_SECONDS == 480
    assert EMBEDDING_GPU_CONTROLLER_UNIT_SECONDS == 540


@pytest.mark.parametrize("numeric", (0, -1, 181, True, 180.0, "180"))
def test_bad_or_unbounded_numerical_budget_is_not_a_longer_compute_grant(numeric):
    with pytest.raises(EmbeddingGpuControlError):
        embedding_gpu_allocation_window_seconds(numeric)


@pytest.mark.parametrize("seconds", (5, 180, 420))
def test_explicit_request_deadline_survives_legacy_decode_and_current_checks(monkeypatch, seconds):
    now = 10**12
    request = control_case(expires_ns=now + seconds * 10**9)[0]
    original = embedding_gpu_control_bytes(request)
    monkeypatch.setattr(control_workspace, "time", SimpleNamespace(monotonic_ns=lambda: now))
    control_workspace._deadline(request)
    assert embedding_gpu_control_bytes(parse_embedding_gpu_control_bytes(original)) == original
    # A later policy/window must never renew the original absolute deadline.
    monkeypatch.setattr(
        control_workspace,
        "time",
        SimpleNamespace(monotonic_ns=lambda: request.expires_monotonic_ns),
    )
    with pytest.raises(ValueError):
        control_workspace._deadline(request)
    assert embedding_gpu_control_bytes(request) == original


@pytest.mark.parametrize("delta", (0, -1, 420 * 10**9 + 1))
def test_workspace_rejects_expired_or_overlong_window_before_file_materialization(
    monkeypatch, delta
):
    now = 10**12
    request = control_case(expires_ns=now + delta)[0]
    monkeypatch.setattr(control_workspace, "time", SimpleNamespace(monotonic_ns=lambda: now))
    with pytest.raises(ValueError):
        control_workspace._deadline(request)


def test_installed_template_candidates_and_expected_hashes_share_the_bounded_budget():
    unit_root = ROOT / "infra/systemd"
    worker = (unit_root / "eom-embedding-native-gpu-batch@.service").read_bytes()
    controller = (unit_root / "eom-embedding-native-gpu-batch-owner@.service").read_bytes()
    assert f"TimeoutStartSec={EMBEDDING_GPU_WORKER_UNIT_SECONDS}\n".encode() in worker
    assert f"TimeoutStartSec={EMBEDDING_GPU_CONTROLLER_UNIT_SECONDS}\n".encode() in controller
    assert sha256_bytes(worker) == observation._SERVICE_SHA
    assert sha256_bytes(controller).removeprefix("sha256:") == BATCH_CONTROL_TEMPLATE_SHA256


def test_benchmark_cannot_borrow_the_longer_allocation_window():
    left, right = socket.socketpair()
    try:
        with pytest.raises(BenchmarkChannelError):
            _Frames(
                left,
                BenchmarkUnixPeer(os.getpid(), os.getuid(), os.getgid()),
                lambda _: None,
                time.monotonic_ns() + 420 * 10**9,
            )
        assert left.fileno() == -1
    finally:
        left.close()
        right.close()


@pytest.mark.parametrize("override", (180, 420, 1200))
def test_allocation_profile_does_not_accept_a_caller_selected_lifetime(override):
    left, right = socket.socketpair()
    try:
        with pytest.raises(BenchmarkChannelError):
            _Frames(
                left,
                BenchmarkUnixPeer(os.getpid(), os.getuid(), os.getgid()),
                lambda _: None,
                time.monotonic_ns() + 5 * 10**9,
                maximum_lifetime_seconds=override,
                lifetime_profile=FrameLifetimeProfile.EMBEDDING_ALLOCATION,
            )
        assert left.fileno() == -1
    finally:
        left.close()
        right.close()
