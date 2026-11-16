"""Private gateway OS adapter: synthetic unit observations and local files/sockets."""

from __future__ import annotations

import os
import subprocess
import tempfile
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_kakao_archive_contracts import canonical_bytes
from eom_kakao_archive_contracts.kakao_remote import (
    GatewayLeaseGrant,
    GatewayRevocation,
    ProfileFence,
    gateway_execution_digest,
)
from eom_orchestrator import kakao_gateway_runtime as runtime
from eom_orchestrator import kakao_runtime_os as shared
from eom_orchestrator.kakao_browser_runtime import BrowserRunHandle

ROOT = Path(__file__).resolve().parents[2]
BOOT = "12345678-1234-1234-1234-123456789abc"
HASH = "sha256:" + "f" * 64


def grant(**updates):
    now = datetime.now(UTC)
    return GatewayLeaseGrant.model_validate(
        {
            "schema_version": "kakao-remote-gateway-grant/1.0",
            "lease_id": "kakaoremotelease_" + "1" * 32,
            "source_binding_id": "kakaobinding_" + "2" * 32,
            "profile_id": "kakaoprofile_" + "3" * 32,
            "fence_epoch": 4,
            "gateway_epoch": 5,
            "grant_revision": 1,
            "issued_at": now - timedelta(seconds=1),
            "authorized_at": now,
            "expires_at": now + timedelta(seconds=30),
            "absolute_expires_at": now + timedelta(minutes=19),
            **updates,
        }
    )


def successor(original, **updates):
    return GatewayLeaseGrant.model_validate({**original.model_dump(), **updates})


def revoked(original):
    return GatewayRevocation(
        schema_version="kakao-remote-gateway-revocation/1.0",
        lease_id=original.lease_id,
        fence_epoch=original.fence_epoch,
        gateway_epoch=original.gateway_epoch,
        grant_revision=original.grant_revision,
        reason="LOGOUT",
    )


def browser(original):
    return BrowserRunHandle(
        ProfileFence(
            schema_version="kakao-profile-fence/1.0",
            profile_id=original.profile_id,
            browser_run_id="kakaobrowserrun_" + "4" * 32,
            fence_epoch=original.fence_epoch,
            mode="MANUAL",
        ),
        HASH,
        BOOT,
        "b" * 32,
        44,
        444,
        runtime.BROWSER_CGROUP,
    )


def observed(original, **updates):
    value = {name: "" for name in runtime.PROPERTIES}
    value.update(
        {
            "LoadState": "loaded",
            "FragmentPath": str(runtime.TEMPLATE),
            "NeedDaemonReload": "no",
            "User": "eom-kakao-remote",
            "Group": "eom-kakao-proxy",
            "Type": "notify",
            "NotifyAccess": "main",
            "KillMode": "control-group",
            "Restart": "no",
            "ActiveState": "active",
            "SubState": "running",
            "MainPID": "1234",
            "ControlPID": "0",
            "ExecMainPID": "1234",
            "ExecMainStartTimestampMonotonic": "123456",
            "InvocationID": "c" * 32,
            "ControlGroup": runtime.CGROUP,
            "StatusText": "KAKAO_GATEWAY_STARTED:" + gateway_execution_digest(original),
            "Result": "success",
            "ExecMainCode": "1",
            "ExecMainStatus": "0",
            **updates,
        }
    )
    return value


def inactive(original, **updates):
    return observed(original, ActiveState="inactive", SubState="dead", MainPID="0", **updates)


def handle(original):
    return runtime.GatewayRunHandle(original, BOOT, "c" * 32, 1234, 123456, runtime.CGROUP)


@pytest.fixture
def gate(monkeypatch):
    monkeypatch.setattr(runtime, "_control_lock", lambda: nullcontext())
    monkeypatch.setattr(runtime, "_boot_id", lambda: BOOT)
    monkeypatch.setattr(runtime, "_cgroup_closed", lambda: "EMPTY")
    monkeypatch.setattr(runtime.FixedKakaoGatewayRuntime, "_installed", lambda _: None)
    return runtime.FixedKakaoGatewayRuntime(HASH, HASH)


def test_identity_pins_all_immutable_fields_but_not_heartbeat_revision():
    first = grant()
    renewal = successor(
        first,
        grant_revision=2,
        authorized_at=first.authorized_at + timedelta(seconds=5),
        expires_at=first.expires_at + timedelta(seconds=5),
    )
    assert gateway_execution_digest(first) == gateway_execution_digest(renewal)
    for field, value in (
        ("gateway_epoch", 6),
        ("fence_epoch", 5),
        ("lease_id", "kakaoremotelease_" + "9" * 32),
        ("source_binding_id", "kakaobinding_" + "9" * 32),
        ("profile_id", "kakaoprofile_" + "9" * 32),
        ("issued_at", first.issued_at - timedelta(seconds=1)),
        ("absolute_expires_at", first.absolute_expires_at - timedelta(seconds=1)),
    ):
        assert gateway_execution_digest(
            successor(first, **{field: value})
        ) != gateway_execution_digest(first)


def test_observe_current_heartbeat_same_invocation_without_launch(gate, monkeypatch):
    first = grant()
    current = successor(first, grant_revision=2)
    monkeypatch.setattr(runtime, "_current", lambda: current)
    monkeypatch.setattr(runtime, "_show", lambda: observed(first))
    launch = Mock()
    monkeypatch.setattr(runtime.subprocess, "run", launch)
    result = gate.observe_dispatch(first, dispatched_boot_id=BOOT)
    assert result == handle(current)
    launch.assert_not_called()


@pytest.mark.parametrize("terminal", ["ready", "failed"])
def test_pending_gateway_is_observed_until_ready_or_closed(gate, monkeypatch, terminal):
    value = grant()
    pending = observed(value, ActiveState="activating", SubState="start", Job="42", StatusText="")
    final = (
        observed(value)
        if terminal == "ready"
        else inactive(value, Result="exit-code", ExecMainStatus="1")
    )
    monkeypatch.setattr(runtime, "_current", lambda: value)
    monkeypatch.setattr(runtime, "_show", Mock(side_effect=[pending, final]))
    launch = Mock()
    monkeypatch.setattr(runtime.subprocess, "run", launch)
    with pytest.raises(runtime.KakaoGatewayRuntimeError, match="START_PENDING"):
        gate.observe_dispatch(value, dispatched_boot_id=BOOT)
    result = gate.observe_dispatch(value, dispatched_boot_id=BOOT)
    assert isinstance(
        result, runtime.GatewayRunHandle if terminal == "ready" else runtime.ClosedGatewayDispatch
    )
    launch.assert_not_called()


@pytest.mark.parametrize("history", [False, True])
def test_missing_protected_grant_is_only_first_use_without_history(gate, monkeypatch, history):
    monkeypatch.setattr(runtime, "_current", Mock(side_effect=FileNotFoundError))
    monkeypatch.setattr(runtime, "_has_grant_history", lambda: history)
    if history:
        with pytest.raises(runtime.KakaoGatewayRuntimeError, match="PUBLICATION_UNCERTAIN"):
            gate.observe_grant()
    else:
        assert gate.observe_grant() is None


def test_revoked_running_gateway_can_only_be_recovered_for_teardown(gate, monkeypatch):
    value = grant()
    monkeypatch.setattr(runtime, "_current", lambda: revoked(value))
    monkeypatch.setattr(runtime, "_show", lambda: observed(value))
    assert gate.observe_for_stop(value, dispatched_boot_id=BOOT) == handle(value)
    with pytest.raises(runtime.KakaoGatewayRuntimeError, match="RUN_MISMATCH"):
        gate.observe_dispatch(value, dispatched_boot_id=BOOT)


@pytest.mark.parametrize(
    "change",
    [
        {"Job": "42"},
        {"ControlPID": "9"},
        {"MainPID": "9"},
        {"ControlGroup": "/other"},
        {"ActiveState": "activating"},
        {"DropInPaths": "/tmp/other"},
    ],
)
def test_uncertain_or_pending_unit_cannot_be_closed(gate, monkeypatch, change):
    value = grant()
    monkeypatch.setattr(runtime, "_current", lambda: value)
    monkeypatch.setattr(runtime, "_show", lambda: {**inactive(value), **change})
    with pytest.raises(runtime.KakaoGatewayRuntimeError):
        gate.observe_dispatch(value, dispatched_boot_id=BOOT)


def test_old_epoch_and_reboot_running_are_not_adopted(gate, monkeypatch):
    first = grant()
    monkeypatch.setattr(runtime, "_current", lambda: successor(first, gateway_epoch=6))
    with pytest.raises(runtime.KakaoGatewayRuntimeError, match="FENCE_MISMATCH"):
        gate.observe_dispatch(first, dispatched_boot_id=BOOT)
    monkeypatch.setattr(runtime, "_current", lambda: first)
    monkeypatch.setattr(runtime, "_show", lambda: observed(first))
    monkeypatch.setattr(runtime, "_boot_id", lambda: "abcdefab-1234-1234-1234-123456789abc")
    with pytest.raises(runtime.KakaoGatewayRuntimeError, match="RUN_MISMATCH"):
        gate.observe_dispatch(first, dispatched_boot_id=BOOT)


def test_fresh_successor_requires_reobserved_closure_browser_and_current_authority(
    gate, monkeypatch
):
    old = grant()
    fresh = successor(old, lease_id="kakaoremotelease_" + "9" * 32, gateway_epoch=6)
    monkeypatch.setattr(runtime, "_current", lambda: old)
    monkeypatch.setattr(runtime, "_show", lambda: inactive(old))
    prior = gate.observe_dispatch(old, dispatched_boot_id=BOOT)
    monkeypatch.setattr(
        runtime,
        "_show",
        Mock(
            side_effect=[
                inactive(old),
                observed(fresh, InvocationID="d" * 32, ExecMainStartTimestampMonotonic="223456"),
            ]
        ),
    )
    events = []
    monkeypatch.setattr(runtime, "_browser_ready", lambda *_: events.append("browser"))
    monkeypatch.setattr(runtime, "_publish", lambda *args, **kw: events.append("publish"))
    launch = Mock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(runtime.subprocess, "run", launch)
    result = gate.start(
        fresh,
        browser(fresh),
        prior=prior,
        assert_current=lambda _: events.append("authority"),
        observe_browser=Mock(),
    )
    assert result.grant == fresh and events == ["browser", "authority", "publish"]
    assert launch.call_count == 1
    monkeypatch.setattr(runtime, "_show", lambda: inactive(old, Job="42"))
    with pytest.raises(runtime.KakaoGatewayRuntimeError, match="STOP_UNCONFIRMED"):
        gate.start(
            fresh, browser(fresh), prior=prior, assert_current=Mock(), observe_browser=Mock()
        )
    assert launch.call_count == 1


def test_start_timeout_is_observed_without_duplicate_launch(gate, monkeypatch):
    current = grant()
    state = {"current": None}

    def read():
        if state["current"] is None:
            raise FileNotFoundError
        return state["current"]

    monkeypatch.setattr(runtime, "_current", read)
    monkeypatch.setattr(runtime, "_has_grant_history", lambda: False)
    monkeypatch.setattr(
        runtime, "_show", lambda: inactive(current, ExecMainStartTimestampMonotonic="0")
    )
    monkeypatch.setattr(runtime, "_browser_ready", Mock())
    monkeypatch.setattr(runtime, "_publish", lambda value, **kw: state.update(current=value))
    launch = Mock(side_effect=subprocess.TimeoutExpired("systemctl", 20))
    monkeypatch.setattr(runtime.subprocess, "run", launch)
    with pytest.raises(runtime.KakaoGatewayRuntimeError, match="START_UNCERTAIN"):
        gate.start(
            current, browser(current), prior=None, assert_current=Mock(), observe_browser=Mock()
        )
    monkeypatch.setattr(runtime, "_show", lambda: observed(current))
    assert gate.observe_dispatch(current, dispatched_boot_id=BOOT) == handle(current)
    assert launch.call_count == 1


@pytest.mark.parametrize("failure", ["authority", "browser", "cgroup"])
def test_no_publish_or_launch_when_required_proof_fails(gate, monkeypatch, failure):
    value = grant()
    monkeypatch.setattr(
        runtime, "_show", lambda: inactive(value, ExecMainStartTimestampMonotonic="0")
    )
    monkeypatch.setattr(runtime, "_current", Mock(side_effect=FileNotFoundError))
    monkeypatch.setattr(runtime, "_has_grant_history", lambda: False)
    monkeypatch.setattr(
        runtime,
        "_browser_ready",
        Mock(side_effect=ValueError("browser") if failure == "browser" else None),
    )
    if failure == "cgroup":
        monkeypatch.setattr(runtime, "_cgroup_closed", Mock(side_effect=ValueError("cgroup")))
    current = Mock(side_effect=ValueError("authority") if failure == "authority" else None)
    publish, launch = Mock(), Mock()
    monkeypatch.setattr(runtime, "_publish", publish)
    monkeypatch.setattr(runtime.subprocess, "run", launch)
    with pytest.raises(ValueError):
        gate.start(
            value, browser(value), prior=None, assert_current=current, observe_browser=Mock()
        )
    publish.assert_not_called()
    launch.assert_not_called()


def test_renewal_replays_same_value_without_start_and_rejects_expiry(gate, monkeypatch):
    current = grant()
    monkeypatch.setattr(runtime, "_show", lambda: observed(current))
    monkeypatch.setattr(runtime, "_current", lambda: current)
    monkeypatch.setattr(runtime, "_browser_ready", Mock())
    publish = Mock()
    monkeypatch.setattr(runtime, "_publish", publish)
    launch = Mock()
    monkeypatch.setattr(runtime.subprocess, "run", launch)
    gate.renew(
        handle(current), current, browser(current), assert_current=Mock(), observe_browser=Mock()
    )
    publish.assert_called_once_with(current, expected=current)
    launch.assert_not_called()
    expired = successor(
        current,
        issued_at=current.issued_at - timedelta(seconds=60),
        authorized_at=current.authorized_at - timedelta(seconds=60),
        expires_at=current.expires_at - timedelta(seconds=60),
        absolute_expires_at=current.absolute_expires_at - timedelta(seconds=60),
    )
    monkeypatch.setattr(runtime, "_current", lambda: expired)
    with pytest.raises(runtime.KakaoGatewayRuntimeError):
        gate.renew(
            handle(expired),
            current,
            browser(current),
            assert_current=Mock(),
            observe_browser=Mock(),
        )
    assert publish.call_count == 1


def test_stop_timeout_requires_same_execution_job_empty_and_whole_cgroup(gate, monkeypatch):
    value = grant()
    monkeypatch.setattr(runtime, "_current", lambda: value)
    publish = Mock()
    monkeypatch.setattr(runtime, "_publish", publish)
    monkeypatch.setattr(runtime, "_show", Mock(side_effect=[observed(value), inactive(value)]))
    stop = Mock(side_effect=subprocess.TimeoutExpired("systemctl", 5))
    monkeypatch.setattr(runtime.subprocess, "run", stop)
    result = gate.stop(handle(value), revoked(value))
    assert result.cgroup_state == "EMPTY" and stop.call_count == 1
    publish.assert_called_once_with(revoked(value), expected=value)
    monkeypatch.setattr(
        runtime, "_show", Mock(side_effect=[observed(value), inactive(value, Job="8")])
    )
    with pytest.raises(runtime.KakaoGatewayRuntimeError, match="STOP_UNCONFIRMED"):
        gate.stop(handle(value), revoked(value))


@pytest.fixture
def installed_file_tree(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="gateway-os-", dir=ROOT / "staging") as directory:
        path = Path(directory)
        path.chmod(0o2750)
        monkeypatch.setattr(runtime, "GRANT", path / "grant.json")
        monkeypatch.setattr(runtime, "CONTROL_LOCK", path / "control.lock")
        runtime.CONTROL_LOCK.touch(mode=0o600)
        monkeypatch.setattr(runtime.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=os.getuid()))
        monkeypatch.setattr(runtime.grp, "getgrnam", lambda _: SimpleNamespace(gr_gid=os.getgid()))
        yield path


def test_real_protected_atomic_publish_replay_stale_and_revocation(installed_file_tree):
    value = grant()
    with runtime._control_lock():
        runtime._publish(value, expected=None)
        before = runtime.GRANT.stat()
        runtime._publish(value, expected=None)
        assert before.st_ino == runtime.GRANT.stat().st_ino
        assert runtime._current() == value
        newer = successor(value, grant_revision=2)
        runtime._publish(newer, expected=value)
        with pytest.raises(runtime.KakaoGatewayRuntimeError, match="GRANT_STALE"):
            runtime._publish(value, expected=value)
        runtime._publish(revoked(newer), expected=newer)
        assert runtime._current() == revoked(newer)
    assert not list(installed_file_tree.glob("*.next"))


def test_real_publish_recovers_exact_staged_bytes_only(installed_file_tree):
    import hashlib

    value = grant()
    raw = canonical_bytes(value.model_dump(mode="json"))
    pending = installed_file_tree / ("grant-" + hashlib.sha256(raw).hexdigest() + ".next")
    pending.write_bytes(raw)
    pending.chmod(0o640)
    with runtime._control_lock():
        runtime._publish(value, expected=None)
    assert runtime._current() == value and not pending.exists()


def test_owner_checks_browser_identity_without_raw_vnc_access(monkeypatch):
    value = grant()
    current = browser(value)
    observe = Mock(return_value=current)
    raw_identity = Mock(side_effect=AssertionError("Catalog must not connect to raw VNC"))
    monkeypatch.setattr(runtime.pwd, "getpwnam", raw_identity)
    runtime._browser_ready(value, current, observe)
    observe.assert_called_once_with(current.fence)
    raw_identity.assert_not_called()
    with pytest.raises(runtime.KakaoGatewayRuntimeError, match="BROWSER_MISMATCH"):
        runtime._browser_ready(successor(value, fence_epoch=5), current, observe)


@pytest.mark.parametrize(
    "unit", ["arbitrary.service", "../eom-kakao-browser.service", "eom-kakao-browser.service;stop"]
)
def test_shared_os_adapter_never_observes_arbitrary_unit(unit):
    with pytest.raises(shared.KakaoRuntimeOsError, match="UNIT_UNTRUSTED"):
        shared.show_unit(unit, runtime.PROPERTIES)


def test_shared_show_parser_requires_exact_closed_property_set():
    value = observed(grant())
    raw = "\n".join(f"{key}={item}" for key, item in value.items()).encode()
    assert shared.parse_unit_observation(raw, runtime.PROPERTIES) == value
    with pytest.raises(shared.KakaoRuntimeOsError, match="OBSERVATION_INVALID"):
        shared.parse_unit_observation(raw + b"\nJob=42", runtime.PROPERTIES)
    with pytest.raises(shared.KakaoRuntimeOsError, match="OBSERVATION_INVALID"):
        shared.parse_unit_observation(raw.replace(b"Job=\n", b""), runtime.PROPERTIES)


@pytest.mark.parametrize("history", [False, True])
def test_idle_first_inventory_is_not_history_recovery(gate, monkeypatch, history):
    value = grant()
    monkeypatch.setattr(
        runtime,
        "_show",
        lambda: inactive(
            value,
            ExecMainPID="0",
            ExecMainStartTimestampMonotonic="0",
            InvocationID="",
            StatusText="",
        ),
    )
    monkeypatch.setattr(runtime, "_has_grant_history", lambda: history)
    publish, launch = Mock(), Mock()
    monkeypatch.setattr(runtime, "_publish", publish)
    monkeypatch.setattr(runtime.subprocess, "run", launch)
    result = gate.observe_idle()
    assert result.unit == runtime.UNIT and result.boot_id == BOOT
    assert result.never_dispatched is (not history) and result.cgroup_state == "EMPTY"
    publish.assert_not_called()
    launch.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"Job": "9"},
        {"MainPID": "9"},
        {"ControlPID": "9"},
        {"ActiveState": "active", "SubState": "running"},
        {"ControlGroup": "/other"},
    ],
)
def test_idle_probe_rejects_non_idle(gate, monkeypatch, change):
    monkeypatch.setattr(runtime, "_show", lambda: {**inactive(grant()), **change})
    with pytest.raises(runtime.KakaoGatewayRuntimeError, match="IDLE_UNCONFIRMED"):
        gate.observe_idle()


def test_physically_closed_failed_gateway_is_never_fresh_installation(gate, monkeypatch):
    monkeypatch.setattr(
        runtime,
        "_show",
        lambda: observed(
            grant(),
            ActiveState="failed",
            SubState="failed",
            MainPID="0",
            ExecMainPID="0",
            ExecMainStartTimestampMonotonic="0",
            InvocationID="",
            StatusText="",
        ),
    )
    assert gate.observe_idle().never_dispatched is False


def test_staging_trace_disables_never_dispatched_inventory(installed_file_tree):
    assert runtime._has_grant_history() is False
    (installed_file_tree / "grant-incomplete.next").touch()
    assert runtime._has_grant_history() is True


@pytest.mark.parametrize("trace", ["same-grant", "foreign-grant", "unknown"])
def test_first_start_rejects_interrupted_grant_history(
    gate, installed_file_tree, monkeypatch, trace
):
    import hashlib

    value = grant()
    raw = canonical_bytes(
        (successor(value, gateway_epoch=6) if trace == "foreign-grant" else value).model_dump(
            mode="json"
        )
    )
    name = (
        "unknown-entry"
        if trace == "unknown"
        else "grant-" + hashlib.sha256(raw).hexdigest() + ".next"
    )
    pending = installed_file_tree / name
    pending.write_bytes(raw)
    pending.chmod(0o640)
    monkeypatch.setattr(
        runtime,
        "_show",
        lambda: inactive(
            value,
            ExecMainPID="0",
            ExecMainStartTimestampMonotonic="0",
            InvocationID="",
            StatusText="",
        ),
    )
    publish, launch, authority, observe_browser = Mock(), Mock(), Mock(), Mock()
    monkeypatch.setattr(runtime, "_publish", publish)
    monkeypatch.setattr(runtime.subprocess, "run", launch)
    assert not runtime.GRANT.exists()
    assert gate.observe_idle().never_dispatched is False
    with pytest.raises(runtime.KakaoGatewayRuntimeError, match="PRIOR_REQUIRED"):
        gate.start(
            value,
            browser(value),
            prior=None,
            assert_current=authority,
            observe_browser=observe_browser,
        )
    publish.assert_not_called()
    launch.assert_not_called()
    authority.assert_not_called()
    observe_browser.assert_not_called()
    assert pending.read_bytes() == raw and not runtime.GRANT.exists()
