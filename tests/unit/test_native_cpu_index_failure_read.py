"""Real CPU evidence composition with explicit synthetic unit/kernel/filesystem leaves."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service import native_cpu_index_failure_read as module
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation
from eom_orchestrator.worker_systemd import FixedUnitStatus


@pytest.fixture
def original(monkeypatch):
    prepare = CpuUnitObservation(
        FixedUnitStatus("loaded", "active", "exited", "success", 1, 0, 100, False),
        0,
        200,
        "1" * 32,
        "/etc/systemd/system/" + module.PREPARE_TEMPLATE,
        "",
    )
    numeric = CpuUnitObservation(
        FixedUnitStatus("loaded", "failed", "failed", "timeout", 2, 15, 300, False),
        0,
        400,
        "2" * 32,
        "/etc/systemd/system/" + module.INDEX_TEMPLATE,
        "",
    )
    value = SimpleNamespace(prepare=prepare, numeric=numeric)
    monkeypatch.setattr(module.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(module, "_boot_id", lambda: "12345678-1234-1234-1234-123456789abc")
    reader = Mock(spec=module.NumericalRuntimeFileSnapshots)
    monkeypatch.setattr(module, "NumericalRuntimeFileSnapshots", lambda: reader)
    templates = Mock()
    monkeypatch.setattr(module, "_templates", templates)
    empty = Mock()
    monkeypatch.setattr(module, "_empty_original_unit", empty)

    def observe(unit, *, template):
        assert unit.endswith("@" + "a" * 32 + ".service")
        assert template in (module.PREPARE_TEMPLATE, module.INDEX_TEMPLATE)
        return value.prepare if template == module.PREPARE_TEMPLATE else value.numeric

    inspect = Mock(side_effect=observe)
    monkeypatch.setattr(module, "inspect_cpu_unit", inspect)
    value.reader, value.templates, value.empty, value.inspect = reader, templates, empty, inspect
    return value


def test_original_timeout_has_stronger_root_proof_without_weakening_generic_observation(original):
    assert not original.numeric.failed  # Existing generic timeout remains uncertain.
    proof = module.capture_retired_native_cpu_index_failure("job_" + "a" * 32)
    assert proof.numeric_result == "timeout" and proof.numeric_exec_main_status == 15
    assert original.inspect.call_count == 4 and original.empty.call_count == 4
    with module.read_retired_native_cpu_index_failure(proof) as resolved:
        assert resolved.proof == proof
    assert original.inspect.call_count == 8 and original.reader.assert_unchanged.call_count == 2


@pytest.mark.parametrize(
    "fault", ("pid", "running", "success", "fresh", "time", "invocation", "prepare", "code")
)
def test_unknown_active_or_foreign_units_never_produce_recovery_proof(original, fault):
    numeric = original.numeric
    if fault == "pid":
        original.numeric = replace(numeric, main_pid=123)
    elif fault == "running":
        original.numeric = replace(numeric, status=replace(numeric.status, active_state="active"))
    elif fault == "success":
        original.numeric = replace(numeric, status=replace(numeric.status, result="success"))
    elif fault == "fresh":
        original.numeric = replace(
            numeric, status=replace(numeric.status, exec_main_started_monotonic=0)
        )
    elif fault == "time":
        original.numeric = replace(numeric, exited_monotonic=1)
    elif fault == "invocation":
        original.numeric = replace(numeric, invocation_id=original.prepare.invocation_id)
    elif fault == "code":
        original.numeric = replace(numeric, status=replace(numeric.status, exec_main_code=0))
    else:
        original.prepare = replace(original.prepare, main_pid=456)
    with pytest.raises(ValueError):
        module.capture_retired_native_cpu_index_failure("job_" + "a" * 32)
    original.empty.assert_not_called()


@pytest.mark.parametrize("change", ("invocation", "boot", "template"))
def test_late_original_identity_or_file_change_invalidates_whole_window(
    original, monkeypatch, change
):
    proof = module.capture_retired_native_cpu_index_failure("job_" + "a" * 32)
    with pytest.raises(ValueError), module.read_retired_native_cpu_index_failure(proof):
        if change == "invocation":
            original.numeric = replace(original.numeric, invocation_id="f" * 32)
        elif change == "boot":
            monkeypatch.setattr(module, "_boot_id", lambda: "f2345678-1234-1234-1234-123456789abc")
        else:
            original.reader.assert_unchanged.side_effect = ValueError("synthetic changed template")


def test_nonroot_cannot_capture_or_resolve_evidence(original, monkeypatch):
    proof = module.capture_retired_native_cpu_index_failure("job_" + "a" * 32)
    original.inspect.reset_mock()
    monkeypatch.setattr(module.os, "getresuid", lambda: (1000, 1000, 1000))
    with pytest.raises(ValueError):
        module.capture_retired_native_cpu_index_failure("job_" + "a" * 32)
    with pytest.raises(ValueError), module.read_retired_native_cpu_index_failure(proof):
        pytest.fail("nonroot entered physical evidence window")
    original.inspect.assert_not_called()


@pytest.mark.parametrize("fault", ("fd", "group", "pid", "duplicate", "missing_field"))
def test_physical_emptiness_is_independent_of_claimed_pid0(monkeypatch, fault):
    unit = "eom-embedding-native-cpu-index@" + "a" * 32 + ".service"
    raw = b"NFileDescriptorStore=0\nControlGroup=\n"
    if fault == "fd":
        raw = raw.replace(b"Store=0", b"Store=1")
    elif fault == "group":
        raw = raw.replace(b"ControlGroup=\n", b"ControlGroup=/somewhere/else\n")
    elif fault == "duplicate":
        raw += b"ControlGroup=\n"
    elif fault == "missing_field":
        raw = b"NFileDescriptorStore=0\n"
    monkeypatch.setattr(
        module.subprocess, "run", Mock(return_value=SimpleNamespace(stdout=raw, stderr=b""))
    )
    monkeypatch.setattr(
        module, "root_owned_unit_processes", lambda _: (123,) if fault == "pid" else ()
    )
    with pytest.raises(ValueError):
        module._empty_original_unit(unit)
