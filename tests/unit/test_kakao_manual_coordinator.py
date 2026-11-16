"""Coordinator source tests: accepted intent progress, never new authority or relaunch."""

import fcntl
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.kakao_manual import KakaoManualIntent
from eom_catalog_contracts.kakao_manual_runtime_values import (
    manual_profile_fence,
    recorded_manual_gateway_grant,
)
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_manual_composition import build_kakao_manual_runtime
from eom_catalog_service.kakao_manual_coordinator import KakaoManualCoordinator
from eom_orchestrator import kakao_manual_runtime as runtime_module
from eom_orchestrator.kakao_browser_runtime import (
    BrowserRunHandle,
    BrowserStageObservation,
    ClosedBrowserDispatch,
)
from eom_orchestrator.kakao_gateway_runtime import ClosedGatewayDispatch, GatewayRunHandle
from eom_orchestrator.kakao_manual_runtime import KakaoManualRuntimeError


def intent(**changes):
    now = datetime.now(UTC)
    return KakaoManualIntent.model_validate(
        {
            "lease_id": "kakaoremotelease_" + "1" * 32,
            "source_binding_id": "kakaobinding_" + "2" * 32,
            "profile_id": "kakaoprofile_" + "3" * 32,
            "browser_run_id": "kakaobrowserrun_" + "4" * 32,
            "owner_operator_id": "operator_" + "5" * 32,
            "identity_session_id": "apisession_" + "6" * 32,
            "command_sha256": "sha256:" + "a" * 64,
            "dispatch_boot_id": "12345678-1234-1234-1234-123456789abc",
            "fence_epoch": 1,
            "gateway_epoch": 1,
            "resource_version": 1,
            "phase": "PREPARING",
            "grant_revision": 0,
            "created_at": now,
            "authorized_at": None,
            "expires_at": None,
            "absolute_expires_at": now + timedelta(minutes=20),
            "browser": None,
            **changes,
        }
    )


def setup_owner(value):
    state = SimpleNamespace(value=value)
    owner = Mock()
    runtime = Mock()
    owner.get_current_intent.side_effect = lambda: state.value
    owner.reconcile_authority.side_effect = lambda _: state.value

    def prepare(*args, **kwargs):
        state.value = intent(
            **{
                **state.value.model_dump(),
                "grant_revision": 1,
                "authorized_at": state.value.created_at,
                "expires_at": state.value.created_at + timedelta(seconds=30),
                "resource_version": state.value.resource_version + 1,
            }
        )
        return state.value

    def ready(*args, **kwargs):
        state.value = intent(**{**state.value.model_dump(), "phase": "ACTIVE"})
        return state.value

    def fail(*args, **kwargs):
        state.value = intent(
            **{
                **state.value.model_dump(),
                "phase": "ERROR",
                "last_error": kwargs["error"],
                "ended_reason": "RUNTIME_FAILED",
            }
        )
        return state.value

    def close(*args, **kwargs):
        kwargs["observe_stopped"](state.value)
        state.value = intent(**{**state.value.model_dump(), "phase": "ENDED"})
        return state.value

    owner.prepare_gateway.side_effect = prepare
    owner.accept_ready.side_effect = ready
    owner.fail_session.side_effect = fail
    owner.accept_closed.side_effect = close
    return state, owner, runtime, KakaoManualCoordinator(owner, runtime)


def test_timeout_pending_then_ready_preserves_one_intent_and_never_renews():
    state, owner, runtime, coordinator = setup_owner(intent())
    original = state.value
    runtime.ensure_browser.side_effect = [
        KakaoManualRuntimeError("KAKAO_BROWSER_START_UNCERTAIN"),
        KakaoManualRuntimeError("KAKAO_BROWSER_START_PENDING"),
        None,
    ]
    assert coordinator.advance_once() == "WAITING"
    assert coordinator.advance_once() == "WAITING"
    assert state.value == original
    owner.fail_session.assert_not_called()
    assert coordinator.advance_once() == "ACTIVE"
    owner.prepare_gateway.assert_called_once()
    owner.accept_ready.assert_called_once()
    assert coordinator.advance_once() == "ACTIVE"
    runtime.deliver_grant.assert_called_once_with(state.value)
    owner.renew_session.assert_not_called()


def test_pending_then_terminal_failure_is_preserved_through_physical_closure():
    state, owner, runtime, coordinator = setup_owner(intent())
    runtime.ensure_browser.side_effect = [
        KakaoManualRuntimeError("KAKAO_BROWSER_START_PENDING"),
        KakaoManualRuntimeError("KAKAO_MANUAL_BROWSER_ATTEMPT_CLOSED"),
    ]
    assert coordinator.advance_once() == "WAITING"
    assert coordinator.advance_once() == "ERROR"
    assert state.value.last_error == "START_FAILED"
    assert coordinator.advance_once() == "ENDED"
    assert state.value.last_error == "START_FAILED"
    owner.accept_ready.assert_not_called()
    runtime.close.assert_called_once()


def test_gateway_timeout_recovers_without_repreparing_browser_or_grant():
    _, owner, runtime, coordinator = setup_owner(intent())
    runtime.ensure_gateway.side_effect = [
        KakaoManualRuntimeError("KAKAO_GATEWAY_START_UNCERTAIN"),
        KakaoManualRuntimeError("KAKAO_GATEWAY_START_PENDING"),
        None,
    ]
    assert [coordinator.advance_once() for _ in range(3)] == ["WAITING", "WAITING", "ACTIVE"]
    runtime.ensure_browser.assert_called_once()
    owner.prepare_gateway.assert_called_once()
    owner.fail_session.assert_not_called()


def test_authority_expiry_precedes_os_work_and_closes_without_new_grant():
    _, owner, runtime, coordinator = setup_owner(intent(phase="STOPPING", ended_reason="EXPIRED"))
    assert coordinator.advance_once() == "ENDED"
    runtime.ensure_browser.assert_not_called()
    runtime.deliver_grant.assert_not_called()
    owner.renew_session.assert_not_called()


def test_repeated_error_does_not_rewrite_failure_history():
    _, owner, runtime, coordinator = setup_owner(intent(phase="ERROR", last_error="START_FAILED"))
    runtime.close.side_effect = KakaoManualRuntimeError("KAKAO_MANUAL_STOP_UNCONFIRMED")
    assert coordinator.advance_once() == "ERROR"
    owner.fail_session.assert_not_called()


def test_bounded_observer_contention_does_not_fail_an_active_session():
    _, owner, runtime, coordinator = setup_owner(running_intent())
    runtime.observe_runtime.side_effect = KakaoManualRuntimeError("KAKAO_MANUAL_OBSERVATION_BUSY")
    assert coordinator.advance_once() == "WAITING"
    owner.fail_session.assert_not_called()


def test_concurrent_tick_and_cas_conflict_leave_latest_owner_untouched():
    _, owner, _, coordinator = setup_owner(intent())
    coordinator._tick.acquire()
    try:
        assert coordinator.advance_once() == "WAITING"
    finally:
        coordinator._tick.release()
    owner.get_current_intent.assert_not_called()
    owner.reconcile_authority.side_effect = KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
    assert coordinator.advance_once() == "WAITING"
    owner.fail_session.assert_not_called()


@pytest.mark.parametrize(
    "environment", [{}, {"EOM_KAKAO_MANUAL_MODE": "DISABLED"}, {"EOM_KAKAO_MANUAL_MODE": "ENABLED"}]
)
def test_missing_installation_pins_never_construct_runtime(environment):
    assert build_kakao_manual_runtime(Mock(), environment) is None


def test_invalid_mode_does_not_guess_active_runtime():
    with pytest.raises(ValueError, match="CONFIGURATION_INVALID"):
        build_kakao_manual_runtime(Mock(), {"EOM_KAKAO_MANUAL_MODE": "yes"})


def running_intent(**changes):
    first = intent()
    return intent(
        **{
            **first.model_dump(),
            "grant_revision": 1,
            "authorized_at": first.created_at,
            "expires_at": first.created_at + timedelta(seconds=30),
            "phase": "ACTIVE",
            **changes,
        }
    )


def os_runtime(value, monkeypatch):
    browser, gateway = Mock(), Mock()
    fence = manual_profile_fence(value)
    run = BrowserRunHandle(
        fence,
        value.command_sha256,
        value.dispatch_boot_id,
        "b" * 32,
        42,
        100,
        "/system.slice/eom-kakao-browser.service",
    )
    browser.observe_stage.return_value = BrowserStageObservation(True, fence)
    browser.observe_dispatch.return_value = run
    browser.boot_identity.return_value = value.dispatch_boot_id
    gateway.boot_identity.return_value = value.dispatch_boot_id
    gateway.observe_grant.return_value = None
    gateway.observe_idle.return_value = SimpleNamespace(never_dispatched=True)
    browser.observe_idle.return_value = SimpleNamespace(never_dispatched=True)
    if value.grant_revision:
        grant = recorded_manual_gateway_grant(value)
        gateway.observe_grant.return_value = grant
        gateway.observe_dispatch.return_value = GatewayRunHandle(
            grant,
            value.dispatch_boot_id,
            "c" * 32,
            43,
            101,
            "/system.slice/eom-kakao-gateway.service",
        )
        gateway.observe_for_stop.return_value = gateway.observe_dispatch.return_value
    monkeypatch.setattr(runtime_module, "profile_lock_released", lambda: False)
    return runtime_module.FixedKakaoManualRuntime(browser, gateway, Mock(), Mock(), Mock())


def closed_browser(value):
    return ClosedBrowserDispatch(
        manual_profile_fence(value),
        value.command_sha256,
        value.dispatch_boot_id,
        value.dispatch_boot_id,
        datetime.now(UTC),
        "EMPTY",
        "START_NOT_CONFIRMED",
        "b" * 32,
        100,
        "exit-code",
        1,
        1,
    )


def closed_gateway(value):
    return ClosedGatewayDispatch(
        recorded_manual_gateway_grant(value),
        value.dispatch_boot_id,
        value.dispatch_boot_id,
        datetime.now(UTC),
        "EMPTY",
        "c" * 32,
        101,
        "success",
        1,
        0,
    )


def test_runtime_timeout_observes_same_staged_browser_without_launch(monkeypatch):
    value = intent()
    runtime = os_runtime(value, monkeypatch)
    runtime.browser.observe_stage.side_effect = [
        BrowserStageObservation(False, None),
        BrowserStageObservation(True, manual_profile_fence(value)),
        BrowserStageObservation(True, manual_profile_fence(value)),
    ]
    runtime.browser.start.side_effect = KakaoManualRuntimeError("KAKAO_BROWSER_START_UNCERTAIN")
    runtime.browser.observe_dispatch.side_effect = [
        KakaoManualRuntimeError("KAKAO_BROWSER_START_PENDING"),
        runtime.browser.observe_dispatch.return_value,
    ]
    with pytest.raises(KakaoManualRuntimeError, match="START_UNCERTAIN"):
        runtime.ensure_browser(value)
    with pytest.raises(KakaoManualRuntimeError, match="START_PENDING"):
        runtime.ensure_browser(value)
    runtime.ensure_browser(value)
    runtime.browser.start.assert_called_once()


def test_runtime_staged_closed_attempt_cannot_relaunch(monkeypatch):
    value = intent()
    runtime = os_runtime(value, monkeypatch)
    runtime.browser.observe_dispatch.return_value = closed_browser(value)
    with pytest.raises(KakaoManualRuntimeError, match="ATTEMPT_CLOSED"):
        runtime.ensure_browser(value)
    runtime.browser.start.assert_not_called()


def test_runtime_exact_protected_predecessor_not_latest_or_adjacent(monkeypatch):
    value = intent(fence_epoch=7, gateway_epoch=7)
    runtime = os_runtime(value, monkeypatch)
    prior = intent(fence_epoch=3, gateway_epoch=3, phase="ENDED")
    runtime.browser.observe_stage.return_value = BrowserStageObservation(
        False, manual_profile_fence(prior)
    )
    runtime.resolve_predecessor.return_value = prior
    runtime.browser.observe_dispatch.return_value = closed_browser(prior)
    runtime.ensure_browser(value)
    runtime.resolve_predecessor.assert_called_once_with(value, 3)
    runtime.browser.start.assert_called_once()
    assert runtime.browser.start.call_args.kwargs["prior"].fence == manual_profile_fence(prior)


def test_runtime_only_delivers_recorded_renewal_and_admission_waits_for_delivery(monkeypatch):
    value = running_intent()
    runtime = os_runtime(value, monkeypatch)
    successor = intent(
        **{
            **value.model_dump(),
            "grant_revision": 2,
            "authorized_at": value.authorized_at + timedelta(seconds=1),
            "expires_at": value.expires_at + timedelta(seconds=1),
        }
    )
    with pytest.raises(KakaoManualRuntimeError, match="GRANT_MISMATCH"):
        runtime.observe_runtime(successor)
    runtime.deliver_grant(successor)
    assert runtime.gateway.renew.call_args.args[1] == recorded_manual_gateway_grant(successor)
    runtime.gateway.observe_grant.return_value = recorded_manual_gateway_grant(successor)
    runtime.observe_runtime(successor)
    runtime.deliver_grant(successor)
    runtime.gateway.renew.assert_called_once()


@pytest.mark.parametrize(
    "reason", ["USER_ENDED", "EXPIRED", "SESSION_REVOKED", "SOURCE_REVOKED", "RUNTIME_FAILED"]
)
def test_runtime_teardown_closes_gateway_first_preserves_actual_reason(monkeypatch, reason):
    value = running_intent(phase="STOPPING", ended_reason=reason)
    runtime = os_runtime(value, monkeypatch)
    events = []
    runtime.gateway.stop.side_effect = lambda *args: events.append("gateway")
    runtime.browser.stop.side_effect = lambda *args: events.append("browser")
    runtime.gateway.observe_for_stop.side_effect = [
        runtime.gateway.observe_for_stop.return_value,
        closed_gateway(value),
    ]
    runtime.browser.observe_dispatch.side_effect = [
        runtime.browser.observe_dispatch.return_value,
        closed_browser(value),
    ]
    monkeypatch.setattr(runtime_module, "profile_lock_released", lambda: True)
    observation = runtime.close(value)
    assert events == ["gateway", "browser"]
    expected = "RUNTIME_LOST" if reason == "RUNTIME_FAILED" else reason
    assert runtime.gateway.stop.call_args.args[1].reason == expected
    assert observation.browser_stopped and observation.gateway_stopped
    runtime.gateway.renew.assert_not_called()


def test_runtime_never_marks_closed_while_profile_remains_locked(monkeypatch):
    value = intent(phase="ERROR", last_error="START_FAILED")
    runtime = os_runtime(value, monkeypatch)
    runtime.browser.observe_dispatch.return_value = closed_browser(value)
    with pytest.raises(KakaoManualRuntimeError, match="STOP_UNCONFIRMED"):
        runtime.close(value)


def test_runtime_first_intent_reboot_before_staging_never_launches(monkeypatch):
    value = intent()
    runtime = os_runtime(value, monkeypatch)
    runtime.browser.observe_stage.return_value = BrowserStageObservation(False, None)
    runtime.browser.boot_identity.return_value = "87654321-1234-1234-1234-123456789abc"
    with pytest.raises(KakaoManualRuntimeError, match="REBOOT_UNCLEAN"):
        runtime.ensure_browser(value)
    runtime.browser.start.assert_not_called()


def test_parallel_assets_and_heartbeat_observations_do_not_collide_on_os_lock(
    monkeypatch, tmp_path
):
    value = running_intent()
    runtime = os_runtime(value, monkeypatch)
    original = runtime.browser.observe_dispatch.return_value
    lock_path = tmp_path / "control.lock"
    lock_path.touch(mode=0o600)
    entered, release, second_started = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def probe(*args, **kwargs):
        fd = os.open(lock_path, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            calls.append(value.lease_id)
            if len(calls) == 1:
                entered.set()
                assert release.wait(timeout=2)
            return original
        finally:
            os.close(fd)

    def second_read():
        second_started.set()
        return runtime.observe_runtime(value)

    runtime.browser.observe_dispatch.side_effect = probe
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(runtime.observe_runtime, value)
        assert entered.wait(timeout=2)
        second = pool.submit(second_read)
        assert second_started.wait(timeout=2)
        assert not second.done()
        release.set()
        observations = [
            first.result(timeout=3),
            second.result(timeout=3),
            pool.submit(runtime.observe_runtime, value).result(timeout=3),
        ]
    assert len(calls) == 3
    assert all(observed.lease_id == value.lease_id for observed in observations)
    assert len({observed.observed_at for observed in observations}) == 3
    runtime.gateway.renew.assert_not_called()


def test_observation_wait_is_bounded_without_cached_authorization(monkeypatch):
    value = running_intent()
    runtime = os_runtime(value, monkeypatch)
    lock = Mock()
    lock.acquire.return_value = False
    object.__setattr__(runtime, "_observation_lock", lock)
    with pytest.raises(KakaoManualRuntimeError, match="OBSERVATION_BUSY"):
        runtime.observe_runtime(value)
    lock.acquire.assert_called_once_with(timeout=2)
    runtime.browser.observe_dispatch.assert_not_called()
    lock.release.assert_not_called()
