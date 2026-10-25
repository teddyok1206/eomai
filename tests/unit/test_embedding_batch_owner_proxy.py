"""Concrete GPU flow/real owner input staging with synthetic OS, source and wire adapters."""

from __future__ import annotations

import os
from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_batch_owner_proxy as proxy
from eom_catalog_service import embedding_batch_owner_workspace as workspace
from eom_catalog_service import embedding_gpu_batch_controller as controller
from eom_catalog_service.embedding_batch_owner_channel import EmbeddingBatchOwnerChannel
from eom_catalog_service.embedding_benchmark_channel import BenchmarkUnixPeer
from eom_catalog_service.embedding_benchmark_handoff import benchmark_owner_start_ticks
from eom_catalog_service.embedding_gpu_batch_controller import (
    CompletedEmbeddingGpuBatch,
    UnavailableEmbeddingGpuBatch,
)
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity
from eom_workflow.embedding_batch_plan import EmbeddingBatchBound

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_owner_control import RELEASE
from tests.unit.test_embedding_batch_plan import planning_case
from tests.unit.test_embedding_gpu_batch_controller import driver as driver
from tests.unit.test_embedding_gpu_batch_observation import machine as machine


@pytest.fixture
def bridge(driver, tmp_path, monkeypatch):
    identity = CpuHandoffIdentity(os.getuid(), os.getgid())
    peer = BenchmarkUnixPeer(os.getpid(), identity.owner_uid, identity.owner_gid)
    birth = benchmark_owner_start_ticks(peer.pid, uid=peer.uid, gid=peer.gid)
    root = tmp_path / "owner"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(workspace, "BATCH_OWNER_ROOT", root)
    monkeypatch.setattr(workspace, "fixed_owner_identity", lambda: identity)
    monkeypatch.setattr(proxy, "fixed_owner_identity", lambda: identity)
    monkeypatch.setattr(
        proxy, "os", SimpleNamespace(getresuid=lambda: (0, 0, 0), getresgid=lambda: (0, 0, 0))
    )
    binding = planning_case().bound.model_dump(mode="json")
    binding.update(
        request_sha256=driver.captured.prepared.request.parent_request_sha256,
        batch_request_sha256=driver.batch.request_sha256,
        resource_profile_sha256=driver.batch.resource_profile_sha256,
    )
    for child, native in zip(binding["children"], driver.batch.children, strict=True):
        child.update(
            native_job_id=native.request.job_id, native_input_sha256=native.request.request_sha256
        )
    binding = EmbeddingBatchBound.model_validate(seal(binding, "record_sha256"))
    channel = object.__new__(EmbeddingBatchOwnerChannel)
    channel.request = driver.captured.prepared.request
    channel.side = "ROOT"
    channel.controller_release = RELEASE
    value = SimpleNamespace(
        driver=driver,
        channel=channel,
        peer=peer,
        birth=birth,
        notices=[],
        closed=False,
        staged=None,
        corrupt=False,
    )

    def send_ready(notice):
        value.notices.append(notice)

    def receive_binding():
        # This is an explicit synthetic current-source seam, not live Catalog IAM.
        batch = driver.owner.admit_allocation(channel.request, driver.ready)
        value.staged = workspace.stage_owner_embedding_batch(
            channel.request, value.notices[-1], binding, batch
        )
        if value.corrupt:
            (
                root
                / channel.request.allocation_attempt_id.removeprefix("embeddingallocation_")
                / "batch-input.json"
            ).write_bytes(b"changed")
        return value.staged.notice

    def check(batch, child):
        if driver.owner.authorize_child(batch, child) is not None:
            raise ValueError("synthetic source fence returned false")

    monkeypatch.setattr(channel, "require_direct_peer", lambda: value.peer)
    monkeypatch.setattr(channel, "send_ready", send_ready)
    monkeypatch.setattr(channel, "receive_binding", receive_binding)
    monkeypatch.setattr(channel, "check_child", check)
    monkeypatch.setattr(channel, "send_completed", value.notices.append)
    monkeypatch.setattr(channel, "send_busy", value.notices.append)
    monkeypatch.setattr(channel, "close", lambda: setattr(value, "closed", True))
    return value


@pytest.mark.parametrize("cleared_invocation", (False, True))
def test_existing_root_lifecycle_uses_owner_staging_and_each_source_fence(
    bridge, monkeypatch, cleared_invocation
):
    value, driver = bridge, bridge.driver
    retire = controller.retire_embedding_gpu_batch
    if cleared_invocation:

        def cleared(*args, **kwargs):
            original = retire(*args, **kwargs)
            return replace(original, retired_unit=replace(original.retired_unit, invocation_id=""))

        monkeypatch.setattr(controller, "retire_embedding_gpu_batch", cleared)
    result = proxy.run_embedding_gpu_batch_with_owner(
        driver.captured, value.channel, owner_start_ticks=value.birth
    )
    assert isinstance(result, CompletedEmbeddingGpuBatch)
    assert value.closed and [notice.message_type for notice in value.notices] == [
        "ROOT_READY",
        "ROOT_COMPLETED",
    ]
    completed = value.notices[-1]
    assert completed.bound_message_sha256 == value.staged.notice.message_sha256
    assert completed.result_raw_sha256 == result.output_claim.result_raw_sha256
    assert completed.grant == result.grant
    assert completed.unit_invocation_id == driver.ready.unit.invocation_id
    assert driver.authorization_count == 4 * len(driver.batch.children)
    assert driver.events.index("result-ACK") < driver.events.index("retire")


@pytest.mark.parametrize("cleared_invocation", (False, True))
def test_verified_busy_only_reports_original_unexecuted_terminal_without_staging(
    bridge, monkeypatch, cleared_invocation
):
    value, driver = bridge, bridge.driver
    driver.busy = True
    if cleared_invocation:
        monkeypatch.setattr(
            controller,
            "observe_stopped_gpu_unit",
            lambda *_a, **_kw: replace(driver.retired.retired_unit, invocation_id=""),
        )
    result = proxy.run_embedding_gpu_batch_with_owner(
        driver.captured, value.channel, owner_start_ticks=value.birth
    )
    assert isinstance(result, UnavailableEmbeddingGpuBatch)
    assert value.staged is None and value.closed
    assert [notice.message_type for notice in value.notices] == ["ROOT_BUSY"]
    assert "input-bind" not in driver.events and "grant" not in driver.events
    assert value.notices[0].unit_invocation_id == result.original_unit.invocation_id


@pytest.mark.parametrize("busy", (False, True))
def test_other_nonempty_retired_invocation_is_not_cleared_current_state(bridge, monkeypatch, busy):
    driver = bridge.driver
    driver.busy = busy
    if busy:
        monkeypatch.setattr(
            controller,
            "observe_stopped_gpu_unit",
            lambda *_a, **_kw: replace(driver.retired.retired_unit, invocation_id="f" * 32),
        )
    else:
        retire = controller.retire_embedding_gpu_batch

        def changed(*args, **kwargs):
            original = retire(*args, **kwargs)
            return replace(
                original, retired_unit=replace(original.retired_unit, invocation_id="f" * 32)
            )

        monkeypatch.setattr(controller, "retire_embedding_gpu_batch", changed)
    with pytest.raises(ValueError, match="EMBEDDING_BATCH_OWNER_PROXY_INVALID"):
        proxy.run_embedding_gpu_batch_with_owner(
            driver.captured, bridge.channel, owner_start_ticks=bridge.birth
        )
    assert bridge.closed
    assert not any(
        notice.message_type in {"ROOT_BUSY", "ROOT_COMPLETED"} for notice in bridge.notices
    )


@pytest.mark.parametrize("fault", ("birth", "uid", "request", "not_root"))
def test_wrong_original_peer_or_root_identity_never_starts_the_gpu_unit(bridge, monkeypatch, fault):
    value, driver = bridge, bridge.driver
    birth = value.birth
    if fault == "birth":
        birth += 1
    elif fault == "uid":
        value.peer = BenchmarkUnixPeer(value.peer.pid, value.peer.uid + 1, value.peer.gid)
    elif fault == "request":
        value.channel.request = value.channel.request.model_copy(
            update={"message_sha256": "sha256:" + "f" * 64}
        )
    else:
        monkeypatch.setattr(proxy.os, "getresuid", lambda: (1000, 1000, 1000))
    with pytest.raises(ValueError):
        proxy.run_embedding_gpu_batch_with_owner(
            driver.captured, value.channel, owner_start_ticks=birth
        )
    assert value.closed and "dispatch" not in driver.events


def test_unknown_or_changed_staged_input_never_gets_gpu_compute_grant(bridge):
    bridge.corrupt = True
    with pytest.raises((ValueError, RuntimeError)):
        proxy.run_embedding_gpu_batch_with_owner(
            bridge.driver.captured, bridge.channel, owner_start_ticks=bridge.birth
        )
    assert bridge.closed
    assert "input-bind" not in bridge.driver.events and "grant" not in bridge.driver.events
    assert not any(notice.message_type == "ROOT_BUSY" for notice in bridge.notices)


def test_source_denial_is_not_converted_to_busy_or_a_successful_completion(bridge):
    bridge.driver.authorize_fault = "deny"
    with pytest.raises((ValueError, PermissionError)):
        proxy.run_embedding_gpu_batch_with_owner(
            bridge.driver.captured, bridge.channel, owner_start_ticks=bridge.birth
        )
    assert bridge.closed
    assert [notice.message_type for notice in bridge.notices] == ["ROOT_READY"]
    assert "grant" not in bridge.driver.events


def test_child_checks_do_not_rewalk_the_entire_numerical_prefix(bridge, monkeypatch):
    value, driver = bridge, bridge.driver
    owner = proxy.RootEmbeddingBatchOwnerProxy(
        driver.captured, value.channel, owner_start_ticks=value.birth
    )
    owner.admit_allocation(driver.captured.prepared.request, driver.ready)
    monkeypatch.setattr(
        type(driver.captured), "assert_current", lambda _: pytest.fail("per-child prefix scan")
    )
    for _ in range(8):
        owner.authorize_child(
            driver.batch.request_sha256, driver.batch.children[0].request.request_sha256
        )
    assert driver.authorization_count == 8
