"""Frozen installation/source and bounded watcher tests; no real unit, GPU or signal."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service import image_gpu_unit_guardian as guardian
from eom_catalog_service.image_gpu_unit_identity import (
    image_gpu_unit_role,
    image_gpu_unit_templates,
)
from eom_catalog_service.image_gpu_unit_lifetime import ImageGpuUnitRetirement, RetiredImageGpuUnit
from eom_catalog_service.image_gpu_unit_observation import (
    ImageGpuUnitTerminalObservation,
    ImageGpuUnitUnleasedTerminalObservation,
)
from eom_identifiers import sha256_bytes

from tests.unit.test_embedding_native_probe_observation import terminal as terminal_unit
from tests.unit.test_image_gpu_unit_observation import COMMAND, UNIT, observe
from tests.unit.test_image_gpu_unit_observation import image as image


@pytest.fixture
def guarded(image, monkeypatch):
    ready = observe(image)
    ended = replace(terminal_unit(), fragment_path=ready.unit.fragment_path)
    terminal = ImageGpuUnitTerminalObservation(ready, ended, "SUCCEEDED", "2026-10-17T03:00:00Z")
    bootstrap = b"synthetic root bootstrap"
    source = {}
    for template in image_gpu_unit_templates():
        role = image_gpu_unit_role(template.replace("@.service", "@x.service"))
        command = list(COMMAND)
        command[0] = (
            "/srv/eom/conda/envs/eom-image/bin/python3.11"
            if role == "PROVIDER"
            else "/srv/eom/conda/envs/eom-image-trainer/bin/python3.11"
        )
        command[4] = role
        source[template] = (
            "ExecStart=" + " ".join(command) + "\nTimeoutStartSec=930\nTimeoutStopSec=30\n"
        ).encode()
    pins = guardian.ImageGpuInstallationPins(
        tuple((name, sha256_bytes(raw)) for name, raw in source.items()),
        sha256_bytes(bootstrap),
        ready.device,
    )
    state = {
        "units": [ready.unit, ended],
        "index": 0,
        "clock": 0,
        "descriptors": [1],
        "effects": [],
        "reads": [],
        "changed": False,
        "source": source,
        "pins": pins,
        "sleeps": [],
    }

    class Files:
        def __init__(self, uid):
            assert uid == 0

        def read(self, path, *, sha256, maximum):
            raw = bootstrap if path.name == "run_gpu_unit.py" else source[path.name]
            if sha256 != sha256_bytes(raw):
                raise ValueError("synthetic source drift")
            assert len(raw) <= maximum
            state["reads"].append(path)
            return raw

        def assert_unchanged(self):
            if state["changed"]:
                raise ValueError("synthetic source drift")

    def actual(*args, **kwargs):
        assert args == (UNIT,) and kwargs == {
            "template": ready.unit_name.split("@")[0] + "@.service"
        }
        index = min(state["index"], len(state["units"]) - 1)
        state["index"] += 1
        return state["units"][index]

    def descriptors(unit):
        assert unit == UNIT
        return (
            state["descriptors"].pop(0)
            if len(state["descriptors"]) > 1
            else state["descriptors"][0]
        )

    def capture(*args, **kwargs):
        assert (
            args == (UNIT,)
            and kwargs["template_sha256"]
            == dict(pins.templates)[ready.unit_name.split("@")[0] + "@.service"]
        )
        return ready

    def unleased(*args, **kwargs):
        assert args == (UNIT,)
        return ImageGpuUnitUnleasedTerminalObservation(
            UNIT,
            kwargs["template_sha256"],
            kwargs["bootstrap_sha256"],
            ready.effective_policy_sha256,
            kwargs["expected_unit"],
            "SUCCEEDED",
            "2026-10-17T03:00:00Z",
        )

    def acknowledge(value):
        assert value == ready
        state["effects"].append("ack")

    def retire(value):
        state["effects"].append(
            "retire-leased" if type(value) is ImageGpuUnitTerminalObservation else "retire-unleased"
        )
        return ImageGpuUnitRetirement(
            value, RetiredImageGpuUnit("loaded", ""), "2026-10-17T03:00:01Z"
        )

    def sleep(seconds):
        assert seconds in {0.2, 1.0}
        state["sleeps"].append(seconds)
        state["clock"] += seconds

    monkeypatch.setattr(guardian.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(guardian, "NumericalRuntimeFileSnapshots", Files)
    monkeypatch.setattr(guardian, "inspect_cpu_unit", actual)
    monkeypatch.setattr(guardian, "image_gpu_unit_descriptor_count", descriptors)
    monkeypatch.setattr(guardian, "observe_image_gpu_unit_ready", capture)
    monkeypatch.setattr(guardian, "observe_unleased_image_gpu_unit_terminal", unleased)
    monkeypatch.setattr(guardian, "acknowledge_image_gpu_unit_ready", acknowledge)
    monkeypatch.setattr(guardian, "verify_image_gpu_unit_terminal", lambda value: terminal)
    monkeypatch.setattr(guardian, "retire_image_gpu_unit", retire)
    monkeypatch.setattr(guardian, "retire_unleased_image_gpu_unit", retire)
    monkeypatch.setattr(
        guardian, "time", SimpleNamespace(monotonic=lambda: state["clock"], sleep=sleep)
    )
    return ready, terminal, state


def test_guard_captures_all19_sources_once_then_ack_and_retire_one_invocation(guarded):
    _, terminal, state = guarded
    result = guardian.manage_image_gpu_unit_lifetime(UNIT, installation=state["pins"])
    assert result.original_terminal == terminal
    assert state["effects"] == ["ack", "retire-leased"]
    assert len(state["reads"]) == 20 and len(set(state["reads"])) == 20


def test_guard_waits_for_main_start_without_claiming_start_pre_is_ready(guarded):
    ready, terminal, state = guarded
    pre = replace(
        ready.unit,
        main_pid=0,
        status=replace(ready.unit.status, sub_state="start-pre", exec_main_started_monotonic=0),
    )
    state["units"] = [pre, ready.unit, terminal.terminal_unit]
    state["descriptors"] = [0, 1]
    guardian.manage_image_gpu_unit_lifetime(UNIT, installation=state["pins"])
    assert state["effects"] == ["ack", "retire-leased"] and state["index"] == 3
    assert state["sleeps"] == [0.2, 1.0]


def test_cache_no_lease_exit_uses_distinct_terminal_without_ack(guarded):
    _, terminal, state = guarded
    state["units"], state["descriptors"] = [terminal.terminal_unit], [0]
    result = guardian.manage_image_gpu_unit_lifetime(UNIT, installation=state["pins"])
    assert type(result.original_terminal) is ImageGpuUnitUnleasedTerminalObservation
    assert state["effects"] == ["retire-unleased"]


def test_dead_retained_unit_without_ready_capture_is_explicitly_fenced_not_reinterpreted(guarded):
    _, terminal, state = guarded
    state["units"] = [terminal.terminal_unit]
    with pytest.raises(ValueError, match="UNOBSERVED_RETAINED_EXIT"):
        guardian.manage_image_gpu_unit_lifetime(UNIT, installation=state["pins"])
    assert state["effects"] == []


@pytest.mark.parametrize("fault", ("invocation", "start", "source"))
def test_guard_rejects_identity_drift_after_ack_without_mutating_terminal(
    guarded, monkeypatch, fault
):
    ready, terminal, state = guarded
    if fault == "invocation":
        state["units"][1] = replace(terminal.terminal_unit, invocation_id="f" * 32)
    elif fault == "start":
        ended = terminal.terminal_unit
        state["units"][1] = replace(
            ended,
            status=replace(
                ended.status,
                exec_main_started_monotonic=ended.status.exec_main_started_monotonic + 1,
            ),
        )
    else:

        def ack(value):
            assert value == ready
            state["effects"].append("ack")
            state["changed"] = True

        monkeypatch.setattr(guardian, "acknowledge_image_gpu_unit_ready", ack)
    with pytest.raises(ValueError):
        guardian.manage_image_gpu_unit_lifetime(UNIT, installation=state["pins"])
    assert state["effects"] == ["ack"]


def test_guard_budget_expiry_never_stops_or_restarts_a_worker(guarded, monkeypatch):
    ready, _, state = guarded
    state["units"], state["descriptors"] = [ready.unit], [0]
    monkeypatch.setattr(guardian.time, "sleep", lambda _: state.update(clock=1000000))
    with pytest.raises(ValueError, match="OBSERVATION_EXPIRED"):
        guardian.manage_image_gpu_unit_lifetime(UNIT, installation=state["pins"])
    assert state["effects"] == []


@pytest.mark.parametrize("fault", ("missing", "duplicate", "unknown", "hash", "mutable"))
def test_installation_requires_exact_closed_immutable19_pins(guarded, fault):
    _, _, state = guarded
    pins = state["pins"]
    rows = pins.templates
    if fault == "missing":
        rows = rows[:-1]
    elif fault == "duplicate":
        rows = (*rows[:-1], rows[0])
    elif fault == "unknown":
        rows = (*rows[:-1], ("other@.service", rows[-1][1]))
    elif fault == "hash":
        rows = (*rows[:-1], (rows[-1][0], "invalid"))
    else:
        rows = list(rows)
    with pytest.raises(ValueError):
        guardian.ImageGpuInstallationPins(rows, pins.bootstrap_sha256, pins.device)
    assert state["effects"] == []


def test_other_template_source_drift_blocks_current_unit_before_ack(guarded):
    _, _, state = guarded
    name = image_gpu_unit_templates()[-1]
    state["source"][name] += b"# changed\n"
    with pytest.raises(ValueError, match="source drift"):
        guardian.manage_image_gpu_unit_lifetime(UNIT, installation=state["pins"])
    assert state["effects"] == []


def test_all19_commands_must_use_fixed_shared_bootstrap_not_legacy_lock(guarded):
    _, _, state = guarded
    name = image_gpu_unit_templates()[-1]
    state["source"][name] = state["source"][name].replace(
        b"/run/eom-gpu-lease/gpu0.lock", b"/var/lib/eom-image/gpu0.lock"
    )
    pins = state["pins"]
    state["pins"] = replace(
        pins, templates=tuple((name, sha256_bytes(raw)) for name, raw in state["source"].items())
    )
    with pytest.raises(ValueError, match="ENTRYPOINT_INVALID"):
        guardian.manage_image_gpu_unit_lifetime(UNIT, installation=state["pins"])
    assert state["effects"] == []


def test_guard_has_no_nonroot_entry(guarded, monkeypatch):
    _, _, state = guarded
    monkeypatch.setattr(guardian.os, "getresuid", lambda: (984, 984, 984))
    with pytest.raises(ValueError, match="OWNER_REQUIRED"):
        guardian.manage_image_gpu_unit_lifetime(UNIT, installation=state["pins"])
    assert state["reads"] == [] and state["effects"] == []


@pytest.mark.parametrize(
    "raw",
    (
        b"TimeoutStartSec=infinity\nTimeoutStopSec=1\n",
        b"TimeoutStartSec=1\nTimeoutStartSec=2\nTimeoutStopSec=1\n",
        b"TimeoutStartSec=1\n",
        b"TimeoutStartSec=86401\nTimeoutStopSec=1\n",
        b"TimeoutStartSec=1\nTimeoutStopSec=301\n",
    ),
)
def test_guard_timeout_is_bounded_from_pinned_template_not_caller_fallback(raw):
    with pytest.raises(ValueError, match="TIMEOUT_INVALID"):
        guardian._timeout(raw)


@pytest.fixture
def launcher(monkeypatch):
    unit = "eom-image-gpu-lifetime@eom\\x2dimage\\x2dprovider\\x40request.service.service"
    state = {"fresh": True, "result": 0, "calls": [], "pin": "sha256:" + "a" * 64}

    class Files:
        def __init__(self, uid):
            assert uid == 0

        def read(self, path, *, sha256, maximum):
            assert path == Path("/etc/systemd/system") / guardian.GUARDIAN_TEMPLATE
            assert sha256 == state["pin"]
            return b"synthetic reviewed root guardian"

        def observe_protected_member_identity(self, path):
            assert path == Path("/usr/bin/systemd-escape")

        def assert_unchanged(self):
            pass

    def inspect(unit_name, *, template):
        assert unit_name == unit and template == guardian.GUARDIAN_TEMPLATE
        return SimpleNamespace(fresh=state["fresh"])

    def command(args, **kwargs):
        state["calls"].append(args)
        if args[0] == "/usr/bin/systemd-escape":
            assert args == (
                "/usr/bin/systemd-escape",
                "--template=" + guardian.GUARDIAN_TEMPLATE,
                UNIT,
            )
            return SimpleNamespace(returncode=0, stdout=(unit + "\n").encode(), stderr=b"")
        assert args == ("/usr/bin/systemctl", "--no-ask-password", "--no-block", "start", unit)
        if state["result"] == "timeout":
            raise guardian.subprocess.TimeoutExpired(args, 10)
        return SimpleNamespace(returncode=state["result"])

    monkeypatch.setattr(guardian.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(guardian, "NumericalRuntimeFileSnapshots", Files)
    monkeypatch.setattr(guardian, "inspect_cpu_unit", inspect)
    monkeypatch.setattr(guardian.subprocess, "run", command)
    return unit, state


def test_root_dispatch_starts_one_fresh_fixed_guardian_only(launcher):
    unit, state = launcher
    assert (
        guardian.start_image_gpu_unit_guardian(UNIT, guardian_template_sha256=state["pin"]) == unit
    )
    assert len(state["calls"]) == 2


def test_root_dispatch_never_restarts_previous_guardian(launcher):
    _, state = launcher
    state["fresh"] = False
    with pytest.raises(ValueError, match="GUARDIAN_NOT_FRESH"):
        guardian.start_image_gpu_unit_guardian(UNIT, guardian_template_sha256=state["pin"])
    assert len(state["calls"]) == 1


@pytest.mark.parametrize("result", (1, "timeout"))
def test_root_dispatch_uncertainty_does_not_reissue_start(launcher, result):
    _, state = launcher
    state["result"] = result
    with pytest.raises(ValueError, match="SUBMISSION_UNCERTAIN"):
        guardian.start_image_gpu_unit_guardian(UNIT, guardian_template_sha256=state["pin"])
    assert len(state["calls"]) == 2
