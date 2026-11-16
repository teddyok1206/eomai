"""Fixed OS observation/closure composition only; no real unit/profile/network changes."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_orchestrator import kakao_collection_browser_runtime as runtime
from eom_orchestrator.kakao_browser_runtime import BrowserRunHandle, ClosedBrowserDispatch

from tests.unit.test_kakao_collection_browser_contracts import intent


def handle(value):
    return BrowserRunHandle(
        runtime.collection_profile_fence(value),
        value.command_sha256,
        value.dispatch_boot_id,
        "5" * 32,
        123,
        456,
        "/system.slice/eom-kakao-browser.service",
    )


def stopped(value, *, reboot=False):
    return ClosedBrowserDispatch(
        runtime.collection_profile_fence(value),
        value.command_sha256,
        value.dispatch_boot_id,
        "00000000-0000-0000-0000-000000000000" if reboot else value.dispatch_boot_id,
        datetime.now(UTC),
        "EMPTY",
        "REBOOT_UNCLEAN" if reboot else "START_NOT_CONFIRMED",
        "" if reboot else "5" * 32,
        0 if reboot else 456,
        "success",
        1,
        0,
    )


@pytest.fixture
def system(monkeypatch):
    value = intent()
    browser = SimpleNamespace(
        observe_dispatch=Mock(return_value=handle(value)),
        observe_stage=Mock(return_value=SimpleNamespace(staged=True)),
        stop=Mock(),
        observe_idle=Mock(),
        boot_identity=Mock(return_value=value.dispatch_boot_id),
    )
    gateway = SimpleNamespace(
        observe_idle=Mock(
            side_effect=lambda: SimpleNamespace(
                boot_id=value.dispatch_boot_id, observed_at=datetime.now(UTC)
            )
        )
    )
    lock = Mock(return_value=False)
    monkeypatch.setattr(runtime, "profile_lock_released", lock)
    return SimpleNamespace(
        value=value,
        browser=browser,
        gateway=gateway,
        lock=lock,
        service=runtime.FixedKakaoCollectionBrowserRuntime(browser, gateway),
    )


def stopping(value, *, known=True):
    return value.model_copy(
        update=dict(
            phase="STOPPING",
            browser_invocation_id="5" * 32 if known else None,
            browser_pid=123 if known else None,
            browser_monotonic_us=456 if known else None,
            browser_observed_at=datetime.now(UTC) if known else None,
        )
    )


def test_running_observation_uses_fixed_exact_dispatch_and_actual_profile_gateway_probes(system):
    result = system.service.observe_running(system.value)
    assert result.kind == "RUNNING" and result.invocation_id == "5" * 32
    assert result.profile_locked and result.gateway_stopped
    system.browser.observe_dispatch.assert_called_once_with(
        runtime.collection_profile_fence(system.value),
        command_sha256=system.value.command_sha256,
        dispatched_boot_id=system.value.dispatch_boot_id,
    )
    system.gateway.observe_idle.assert_called_once()
    system.browser.stop.assert_not_called()


def test_unlocked_profile_or_closed_dispatch_is_not_running(system):
    system.lock.return_value = True
    with pytest.raises(runtime.KakaoCollectionBrowserRuntimeError, match="RUNNING_UNCONFIRMED"):
        system.service.observe_running(system.value)
    system.browser.observe_dispatch.return_value = stopped(system.value)
    with pytest.raises(runtime.KakaoCollectionBrowserRuntimeError, match="ATTEMPT_CLOSED"):
        system.service.observe_running(system.value)


def test_stop_is_explicit_and_still_running_process_is_not_closure(system):
    with pytest.raises(runtime.KakaoCollectionBrowserRuntimeError, match="STOP_NOT_REQUESTED"):
        system.service.close(system.value)
    system.browser.stop.assert_not_called()
    with pytest.raises(runtime.KakaoCollectionBrowserRuntimeError, match="STOP_UNCONFIRMED"):
        system.service.close(stopping(system.value))
    system.browser.stop.assert_called_once()


def test_exact_running_process_is_stopped_then_reobserved_without_restart(system):
    value = stopping(system.value)
    system.browser.observe_dispatch.side_effect = [handle(value), stopped(value)]
    system.lock.return_value = True
    result = system.service.close(value)
    assert result.kind == "STOPPED" and not result.profile_locked
    assert result.invocation_id == value.browser_invocation_id
    system.browser.stop.assert_called_once_with(handle(value))
    assert system.browser.observe_dispatch.call_count == 2


def test_changed_invocation_is_not_stopped_as_the_old_process(system):
    changed = stopping(system.value).model_copy(update=dict(browser_invocation_id="a" * 32))
    with pytest.raises(runtime.KakaoCollectionBrowserRuntimeError, match="EXECUTION_CHANGED"):
        system.service.close(changed)
    system.browser.stop.assert_not_called()


def test_never_staged_reservation_requires_physical_idle_and_released_lock(system):
    value = stopping(system.value, known=False)
    system.browser.observe_stage.return_value = SimpleNamespace(staged=False)
    system.lock.return_value = True
    result = system.service.close(value)
    assert result.kind == "PRE_READY_FAILED" and result.invocation_id is None
    system.browser.observe_idle.assert_called_once()
    system.browser.observe_dispatch.assert_not_called()
    system.browser.stop.assert_not_called()


def test_missing_staged_input_is_not_silent_recovery_of_a_known_running_epoch(system):
    system.browser.observe_stage.return_value = SimpleNamespace(staged=False)
    with pytest.raises(runtime.KakaoCollectionBrowserRuntimeError, match="INPUT_LOST"):
        system.service.close(stopping(system.value))
    system.browser.stop.assert_not_called()


def test_reboot_is_closed_unclean_not_successful_old_invocation_reuse(system):
    value = stopping(system.value)
    actual = stopped(value, reboot=True)
    system.browser.observe_dispatch.return_value = actual
    system.browser.boot_identity.return_value = actual.observed_boot_id
    system.gateway.observe_idle.side_effect = lambda: SimpleNamespace(
        boot_id=actual.observed_boot_id, observed_at=datetime.now(UTC)
    )
    system.lock.return_value = True
    result = system.service.close(value)
    assert result.kind == "REBOOT_UNCLEAN" and result.observed_boot_id != value.dispatch_boot_id
    assert result.invocation_id == value.browser_invocation_id
    system.browser.stop.assert_not_called()


def test_unowned_live_gateway_blocks_auto_cleanup_without_touching_anything_else(system):
    system.gateway.observe_idle.side_effect = ValueError("synthetic gateway not idle")
    with pytest.raises(ValueError, match="gateway not idle"):
        system.service.close(stopping(system.value))
    system.browser.observe_stage.assert_not_called()
    system.browser.stop.assert_not_called()


def test_unclean_process_exit_is_preserved_as_failure_not_clean_stop(system):
    value = stopping(system.value)
    system.browser.observe_dispatch.return_value = replace(
        stopped(value), unit_result="exit-code", main_exit_status=7
    )
    system.lock.return_value = True
    result = system.service.close(value)
    assert result.kind == "STOPPED" and result.runtime_error == "RUNTIME_LOST"
