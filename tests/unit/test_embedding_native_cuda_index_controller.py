"""Synthetic root controller ports, not installed units, GPU computation or release proof."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service import embedding_native_cuda_index_controller as control
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_catalog_service.embedding_native_cuda_index_entry import NativeCudaIndexLaunchPins
from eom_catalog_service.embedding_native_cuda_index_launch import (
    native_cuda_index_backend_environment_bytes,
)
from eom_catalog_service.embedding_native_cuda_index_lifetime import NativeCudaIndexRetirement
from eom_catalog_service.embedding_native_cuda_index_unacknowledged import (
    UnacknowledgedNativeCudaIndexRetirement,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation
from eom_orchestrator.native_embedding_cuda_index_handoff import PreparedNativeCudaIndex
from eom_orchestrator.worker_systemd import FixedUnitStatus

from tests.unit.local_embedding_admission_fixtures import native_fixture

ROOT = Path(__file__).resolve().parents[2]


def status(state="running", *, invocation="b" * 32, started=100):
    active, sub, result, code, exit_status, pid, exited = {
        "fresh": ("inactive", "dead", "success", 0, 0, 0, 0),
        "queued": ("activating", "start", "success", 0, 0, 0, 0),
        "running": ("activating", "start", "success", 0, 0, 123, 0),
        "success": ("active", "exited", "success", 1, 0, 0, 200),
        "failure": ("failed", "failed", "exit-code", 1, 1, 0, 200),
        "timeout": ("failed", "failed", "timeout", 2, 15, 0, 200),
    }[state]
    return CpuUnitObservation(
        FixedUnitStatus(
            "loaded",
            active,
            sub,
            result,
            code,
            exit_status,
            0 if state in {"fresh", "queued"} else started,
            False,
        ),
        pid,
        exited,
        "" if state == "fresh" else invocation,
        "/etc/systemd/system/" + control.CUDA_INDEX_TEMPLATE,
        "",
    )


@pytest.fixture
def setup(monkeypatch, tmp_path):
    fixture = native_fixture(device="CUDA")
    prepared = PreparedNativeCudaIndex("a" * 32, fixture.association, fixture.native_input)
    backend = NativeEmbeddingBackendPins(
        "embeddingnativeconfig_" + "c" * 32,
        "embeddingnativeconfigrev_" + "d" * 32,
        "sha256:" + "e" * 64,
        "sha256:" + "f" * 64,
        "sha256:" + "1" * 64,
    )
    binding = SimpleNamespace(owner_pid=321, owner_start_ticks=432)
    launch = NativeCudaIndexLaunchPins(
        prepared.execution_id,
        prepared.request.job_id,
        prepared.association.association_sha256,
        prepared.association.owned_input.sha256,
        180 * 10**9,
        backend.configuration_id,
        backend.configuration_revision_id,
        backend.configuration_sha256,
        backend.configuration_raw_sha256,
        backend.receipt_raw_sha256,
    )
    captured = SimpleNamespace(
        basis=SimpleNamespace(launch=launch),
        execution=tmp_path,
        assert_current=Mock(),
        __enter__=Mock(),
        __exit__=Mock(),
    )
    # Context protocol lookup is on the type; Mock provides the real context-manager seam.
    context = Mock()
    context.__enter__ = Mock(return_value=captured)
    context.__exit__ = Mock(return_value=False)
    deployment = Mock(assert_unchanged=Mock())
    monkeypatch.setattr(control.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(control, "NumericalRuntimeFileSnapshots", lambda *_a: deployment)
    monkeypatch.setattr(control, "_deployment", Mock(return_value=backend))
    monkeypatch.setattr(control, "read_prepared_native_cuda_index", Mock(return_value=prepared))
    monkeypatch.setattr(control, "read_native_cuda_index_owner_binding", Mock(return_value=binding))
    monkeypatch.setattr(control, "require_native_cuda_index_owner_current", Mock())
    monkeypatch.setattr(control, "prepare_native_cuda_index_handoff", Mock())
    monkeypatch.setattr(control, "_write_launch_environment", Mock())
    monkeypatch.setattr(
        control, "capture_native_cuda_index_launch_files", Mock(return_value=context)
    )
    monkeypatch.setattr(control, "inspect_cpu_unit", Mock(return_value=status("fresh")))
    monkeypatch.setattr(control, "_start", Mock())
    monkeypatch.setattr(control.time, "monotonic_ns", lambda: 0)
    sleep = Mock()
    monkeypatch.setattr(control.time, "sleep", sleep)
    result = NativeCudaIndexRetirement(SimpleNamespace(original_outcome="SUCCEEDED"), Mock(), "now")
    monkeypatch.setattr(control, "_run_started", Mock(return_value=result))
    return SimpleNamespace(
        prepared=prepared,
        backend=backend,
        binding=binding,
        launch=launch,
        captured=captured,
        context=context,
        deployment=deployment,
        sleep=sleep,
        result=result,
    )


def test_full_fixed_controller_composes_original_input_and_real_retirement_only(setup):
    result = control.run_native_cuda_index_controller(setup.prepared.execution_id)
    assert result.succeeded and result.execution_id == setup.prepared.execution_id
    assert result.job_id == setup.prepared.request.job_id
    assert result.association_sha256 == setup.prepared.association.association_sha256
    control.prepare_native_cuda_index_handoff.assert_called_once_with(setup.prepared.execution_id)
    basis = control.capture_native_cuda_index_launch_files.call_args.args[0]
    assert basis.owner_pid == 321 and basis.owner_start_ticks == 432
    assert basis.request == setup.prepared.request
    assert basis.launch.association_sha256 == setup.prepared.association.association_sha256
    assert basis.launch.expires_ns == 180 * 10**9
    control._start.assert_called_once_with(
        control.native_cuda_index_unit(setup.prepared.execution_id)
    )
    control._run_started.assert_called_once_with(setup.captured)
    assert setup.deployment.assert_unchanged.call_count == 2
    setup.context.__exit__.assert_called_once()


@pytest.mark.parametrize("fault", ["root", "identity", "already", "input", "owner", "deadline"])
def test_before_dispatch_failure_never_starts_model_or_retries(setup, monkeypatch, fault):
    if fault == "root":
        monkeypatch.setattr(control.os, "getresuid", lambda: (1000, 1000, 1000))
    if fault == "already":
        control.inspect_cpu_unit.return_value = status("running")
    if fault == "input":
        control.read_prepared_native_cuda_index.side_effect = [setup.prepared, None]
    if fault == "owner":
        control.read_native_cuda_index_owner_binding.side_effect = [setup.binding, None]
    if fault == "deadline":
        ticks = iter([0, 181 * 10**9])
        monkeypatch.setattr(control.time, "monotonic_ns", lambda: next(ticks))
    with pytest.raises(ValueError):
        control.run_native_cuda_index_controller("../bad" if fault == "identity" else "a" * 32)
    control._start.assert_not_called()
    control._run_started.assert_not_called()


def test_dispatch_uncertainty_is_not_replayed_or_guessed_failed(setup):
    control._start.side_effect = ValueError("NATIVE_CUDA_INDEX_CONTROLLER_START_UNCERTAIN")
    with pytest.raises(ValueError, match="START_UNCERTAIN"):
        control.run_native_cuda_index_controller("a" * 32)
    control._start.assert_called_once()
    control._run_started.assert_not_called()
    setup.context.__exit__.assert_called_once()


@pytest.mark.parametrize("state", ["success", "failure", "timeout"])
def test_terminal_detection_keeps_timeout_and_original_failure(state):
    assert control._is_terminal(status(state))
    assert not control._is_terminal(status("running"))
    assert not control._is_terminal(status("queued"))


def test_first_actual_invocation_is_pinned_not_queued_start():
    assert control._pin_invocation(status("fresh"), None) is None
    assert control._pin_invocation(status("queued"), None) is None
    original = control._pin_invocation(status(), None)
    assert original == status()
    assert control._pin_invocation(status("success"), original) is original
    for changed in (status(invocation="c" * 32), status(started=101), status("fresh")):
        with pytest.raises(ValueError, match="INVOCATION_CHANGED"):
            control._pin_invocation(changed, original)


@pytest.mark.parametrize("state", ["failure", "timeout"])
def test_before_ready_terminal_uses_exact_failed_unit_not_fabricated_ready(
    setup, monkeypatch, state
):
    # The fixture replaced the high-level runner, so obtain its original saved implementation.
    run_loop = ORIGINAL_RUN_STARTED
    terminal = SimpleNamespace(original_outcome="FAILED")
    retired = UnacknowledgedNativeCudaIndexRetirement(terminal, Mock(), "now")
    control.inspect_cpu_unit.return_value = status(state)
    observe = Mock(return_value=terminal)
    retire = Mock(return_value=retired)
    monkeypatch.setattr(control, "observe_unacknowledged_native_cuda_index_terminal", observe)
    monkeypatch.setattr(control, "retire_unacknowledged_native_cuda_index_unit", retire)
    assert run_loop(setup.captured) == retired
    observe.assert_called_once_with(setup.captured, expected_unit=status(state))
    retire.assert_called_once_with(terminal, setup.captured)
    assert not control.NativeCudaIndexControllerOutcome(
        setup.prepared.execution_id,
        setup.prepared.request.job_id,
        setup.prepared.association.association_sha256,
        setup.prepared.association.owned_input.sha256,
        retired,
    ).succeeded


def test_success_without_observed_ack_is_not_accepted_or_cleaned(setup, monkeypatch):
    control.inspect_cpu_unit.return_value = status("success")
    retire = Mock()
    monkeypatch.setattr(control, "retire_unacknowledged_native_cuda_index_unit", retire)
    with pytest.raises(ValueError, match="READY_MISSING"):
        ORIGINAL_RUN_STARTED(setup.captured)
    retire.assert_not_called()


def test_ready_ack_terminal_and_retirement_are_ordered_once(setup, monkeypatch, tmp_path):
    (tmp_path / "ready.json").write_bytes(b"untrusted hint")
    control.inspect_cpu_unit.side_effect = [status("queued"), status(), status("success")]
    ready = SimpleNamespace(unit=status())
    terminal = SimpleNamespace(terminal_unit=status("success"))
    events = []
    monkeypatch.setattr(
        control, "observe_native_cuda_index_ready", lambda _c: (events.append("observe"), ready)[1]
    )
    monkeypatch.setattr(
        control, "acknowledge_native_cuda_index_ready", lambda *_a: events.append("ack")
    )
    monkeypatch.setattr(
        control,
        "verify_native_cuda_index_terminal",
        lambda *_a: (events.append("terminal"), terminal)[1],
    )
    monkeypatch.setattr(
        control,
        "retire_native_cuda_index_unit",
        lambda *_a: (events.append("retire"), setup.result)[1],
    )
    assert ORIGINAL_RUN_STARTED(setup.captured) == setup.result
    assert events == ["observe", "ack", "terminal", "retire"]


def test_ack_uncertainty_cannot_fall_into_unacknowledged_cleanup(setup, monkeypatch, tmp_path):
    (tmp_path / "ready.json").write_bytes(b"hint")
    control.inspect_cpu_unit.return_value = status()
    monkeypatch.setattr(
        control, "observe_native_cuda_index_ready", lambda _c: SimpleNamespace(unit=status())
    )
    ack = Mock(side_effect=ValueError("ACK_UNCERTAIN"))
    retire = Mock()
    monkeypatch.setattr(control, "acknowledge_native_cuda_index_ready", ack)
    monkeypatch.setattr(control, "retire_unacknowledged_native_cuda_index_unit", retire)
    with pytest.raises(ValueError, match="ACK_UNCERTAIN"):
        ORIGINAL_RUN_STARTED(setup.captured)
    ack.assert_called_once()
    retire.assert_not_called()


@pytest.mark.parametrize("fault", ["not_ready", "changed", "other_invocation"])
def test_ready_retries_only_incomplete_writer_never_an_invalid_observation(
    setup, monkeypatch, tmp_path, fault
):
    (tmp_path / "ready.json").write_bytes(b"hint")
    ready = SimpleNamespace(unit=status())
    if fault == "other_invocation":
        ready.unit = status(invocation="c" * 32)
    observe = Mock()
    observe.side_effect = (
        [ValueError("NATIVE_CUDA_INDEX_OBSERVATION_NOT_READY"), ready]
        if fault == "not_ready"
        else [ValueError("INPUT_CHANGED") if fault == "changed" else ready]
    )
    control.inspect_cpu_unit.side_effect = [status(), status(), status("success")]
    ack = Mock()
    terminal = SimpleNamespace(terminal_unit=status("success"))
    monkeypatch.setattr(control, "observe_native_cuda_index_ready", observe)
    monkeypatch.setattr(control, "acknowledge_native_cuda_index_ready", ack)
    monkeypatch.setattr(control, "verify_native_cuda_index_terminal", lambda *_a: terminal)
    monkeypatch.setattr(control, "retire_native_cuda_index_unit", lambda *_a: setup.result)
    if fault == "not_ready":
        assert ORIGINAL_RUN_STARTED(setup.captured) == setup.result
        assert observe.call_count == 2
        ack.assert_called_once_with(ready, setup.captured)
    else:
        with pytest.raises(ValueError):
            ORIGINAL_RUN_STARTED(setup.captured)
        ack.assert_not_called()


def test_deadline_does_not_authorize_blind_stop_or_repeat_start(setup, monkeypatch):
    control.inspect_cpu_unit.return_value = status("queued")
    monkeypatch.setattr(control.time, "monotonic_ns", lambda: 191 * 10**9)
    with pytest.raises(ValueError, match="TERMINATION_UNCERTAIN"):
        ORIGINAL_RUN_STARTED(setup.captured)
    control._start.assert_not_called()
    setup.sleep.assert_not_called()


@pytest.mark.parametrize("fault", [None, "cpu", "purpose", "hash", "dynamic"])
def test_root_selection_and_static_environment_are_separate_from_owner_input(monkeypatch, fault):
    backend = NativeEmbeddingBackendPins(
        "embeddingnativeconfig_" + "c" * 32,
        "embeddingnativeconfigrev_" + "d" * 32,
        "sha256:" + "e" * 64,
        "sha256:" + "f" * 64,
        "sha256:" + "1" * 64,
    )
    environment = native_cuda_index_backend_environment_bytes(backend)
    value = {
        "schema_version": "native-embedding-backend-selection/1.0",
        "purpose": "REFERENCE_QUERY" if fault == "purpose" else "INDEX",
        "backend": {
            "device": "CUDA",
            "configuration": {
                "configuration_id": backend.configuration_id,
                "configuration_revision_id": backend.configuration_revision_id,
                "configuration_sha256": backend.configuration_sha256,
                "configuration_raw_sha256": backend.configuration_raw_sha256,
            },
            "receipt_raw_sha256": backend.receipt_raw_sha256,
            "cuda_environment_raw_sha256": sha256_bytes(environment),
        },
    }
    if fault == "cpu":
        value["backend"]["device"] = "CPU"
    files = Mock(assert_unchanged=Mock())
    files.observe_protected_member_bytes.return_value = SimpleNamespace(
        raw=canonical_json_bytes(value)
    )
    files.read.return_value = (
        environment if fault != "dynamic" else b"EOM_CUDA_INDEX_EXPIRES_NS=1\n" + environment
    )
    if fault == "hash":
        files.read.side_effect = ValueError("HASH_CHANGED")
    if fault is None:
        assert ORIGINAL_DEPLOYMENT(files) == backend
        files.assert_unchanged.assert_called_once()
        assert files.read.call_args.kwargs["sha256"] == sha256_bytes(environment)
    else:
        with pytest.raises(ValueError):
            ORIGINAL_DEPLOYMENT(files)


@pytest.mark.parametrize("state", [0, 1])
def test_cli_never_emits_arbitrary_diagnostics(monkeypatch, capsys, state):
    monkeypatch.setattr(control.sys, "argv", ["root-controller", "a" * 32])
    monkeypatch.setattr(
        control,
        "run_native_cuda_index_controller",
        lambda _e: SimpleNamespace(succeeded=state == 0),
    )
    assert control.main() == state
    assert capsys.readouterr() == ("", "")


def test_unit_and_start_only_polkit_preserve_separate_root_and_worker_boundaries():
    unit = (ROOT / "infra/systemd" / control.CUDA_INDEX_CONTROLLER_TEMPLATE).read_text()
    assert "User=root\nGroup=root\n" in unit
    assert "CUDA_INDEX %i" in unit and " -I -B " in unit
    assert "WorkingDirectory=/opt/eom/embedding-cuda-loader-empty" in unit
    assert "CAP_CHOWN CAP_DAC_READ_SEARCH CAP_SYS_PTRACE" in unit
    assert "InaccessiblePaths=-/run/systemd/private" not in unit
    assert "PrivateNetwork=yes" in unit and "Restart=no" in unit
    rules = (ROOT / "infra/polkit/49-eom-native-cuda-index.rules").read_text()
    assert "eom-embedding-native-cuda-index-owner@" in rules
    assert 'subject.user === "eom-workflow-runner"' in rules
    assert 'action.lookup("verb") === "start"' in rules
    assert rules.count("return polkit.Result.YES") == 1
    assert "eom-embedding-native-cuda-index@" in rules
    source = (ROOT / "scripts/embedding/prepare_native_index.py").read_text()
    assert 'sys.argv[1] == "CUDA_INDEX"' in source
    assert 'release.parent != Path("/opt/eom/embedding-owner-releases")' in source


@pytest.mark.parametrize("fault", [None, "root", "unit", "timeout", "exit", "oversized"])
def test_exact_root_dispatch_has_one_bounded_noninteractive_start(monkeypatch, fault):
    monkeypatch.setattr(
        control.os, "getresuid", lambda: (1000,) * 3 if fault == "root" else (0,) * 3
    )
    unit = control.native_cuda_index_unit("a" * 32)
    process = Mock(return_value=SimpleNamespace(returncode=0, stdout=b"", stderr=b""))
    if fault == "timeout":
        process.side_effect = control.subprocess.TimeoutExpired("systemctl", 10)
    if fault == "exit":
        process.return_value.returncode = 1
    if fault == "oversized":
        process.return_value.stdout = b"x" * 16385
    monkeypatch.setattr(control.subprocess, "run", process)
    if fault is None:
        ORIGINAL_START(unit)
    else:
        with pytest.raises(ValueError):
            ORIGINAL_START("--all" if fault == "unit" else unit)
    if fault in {"root", "unit"}:
        process.assert_not_called()
    else:
        process.assert_called_once()
        assert process.call_args.args[0] == (
            "/usr/bin/systemctl",
            "--no-ask-password",
            "--no-block",
            "start",
            unit,
        )
        assert process.call_args.kwargs["timeout"] == 10
        assert "shell" not in process.call_args.kwargs


ORIGINAL_RUN_STARTED = control._run_started
ORIGINAL_DEPLOYMENT = control._deployment
ORIGINAL_START = control._start
