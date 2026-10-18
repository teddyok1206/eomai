"""Actual bounded parser with synthetic systemctl only; no root or unit operations."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_service import gpu_unit_terminal_observation as reader

from tests.unit.test_embedding_native_probe_observation import terminal


@pytest.fixture
def facts(monkeypatch):
    template = "eom-embedding-native-cuda-index@.service"
    unit = template.replace("@", "@" + "a" * 32)
    previous = terminal()
    previous = replace(
        previous,
        fragment_path="/etc/systemd/system/" + template,
        status=replace(
            previous.status,
            active_state="failed",
            sub_state="failed",
            result="exit-code",
            exec_main_status=1,
        ),
    )
    state = SimpleNamespace(
        template=template, unit=unit, expected=previous, fault=None, calls=0, store="1", pid="123"
    )

    def run(args, **kwargs):
        state.calls += 1
        assert args[:3] == ("/usr/bin/systemctl", "show", state.unit)
        assert kwargs == dict(capture_output=True, check=False, timeout=10, env=reader._ENV)
        fields = dict(
            ExecMainPID=state.pid,
            NFileDescriptorStore=state.store,
            InvocationID=previous.invocation_id,
            ExecMainStartTimestampMonotonic=str(previous.status.exec_main_started_monotonic),
        )
        if state.fault == "timeout":
            raise reader.subprocess.TimeoutExpired(args, 10)
        if state.fault in fields:
            fields[state.fault] = "wrong"
        raw = "".join(f"{key}={value}\n" for key, value in fields.items()).encode()
        if state.fault == "duplicate":
            raw += b"ExecMainPID=123\n"
        if state.fault == "missing":
            raw = raw.split(b"\n", 1)[1]
        if state.fault == "unknown":
            raw += b"Unexpected=123\n"
        if state.fault == "unicode":
            raw = b"\xff"
        if state.fault == "oversize":
            raw = b"0" * 16385
        return SimpleNamespace(returncode=1 if state.fault == "exit" else 0, stdout=raw, stderr=b"")

    monkeypatch.setattr(reader.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(reader.subprocess, "run", run)
    return state


def observe(state):
    return reader.observe_failed_gpu_unit_metadata(
        state.unit, template=state.template, expected=state.expected
    )


@pytest.mark.parametrize("store", ("0", "1"))
def test_actual_pid_and_zero_or_one_store_are_retained_without_fake_birth(facts, store):
    facts.store = store
    assert observe(facts) == (123, int(store))


@pytest.mark.parametrize(
    "fault",
    (
        "timeout",
        "ExecMainPID",
        "NFileDescriptorStore",
        "InvocationID",
        "ExecMainStartTimestampMonotonic",
        "duplicate",
        "missing",
        "unknown",
        "unicode",
        "oversize",
        "exit",
    ),
)
def test_malformed_or_changed_original_metadata_fails_closed(facts, fault):
    facts.fault = fault
    with pytest.raises(ValueError, match="GPU_UNIT_TERMINATION_UNCERTAIN"):
        observe(facts)


@pytest.mark.parametrize("pid", ("0", "-1", "2147483648", "0123", "1.0"))
def test_actual_terminal_pid_is_required_not_mainpid_zero_or_coercion(facts, pid):
    facts.pid = pid
    with pytest.raises(ValueError, match="GPU_UNIT_TERMINATION_UNCERTAIN"):
        observe(facts)


@pytest.mark.parametrize("fault", ("root", "unit", "template", "outcome", "fragment"))
def test_reject_bad_root_or_original_before_systemctl(facts, monkeypatch, fault):
    if fault == "root":
        monkeypatch.setattr(reader.os, "getresuid", lambda: (1000,) * 3)
    elif fault == "unit":
        facts.unit = "eom-embedding-benchmark-cuda@" + "a" * 32 + ".service"
    elif fault == "template":
        facts.template = "../bad@.service"
    elif fault == "fragment":
        facts.expected = replace(facts.expected, fragment_path="/other/template")
    else:
        facts.expected = replace(
            facts.expected,
            status=replace(
                facts.expected.status,
                active_state="active",
                sub_state="exited",
                result="success",
                exec_main_status=0,
            ),
        )
    with pytest.raises(ValueError, match="GPU_UNIT_TERMINATION_UNCERTAIN"):
        observe(facts)
    assert facts.calls == 0
