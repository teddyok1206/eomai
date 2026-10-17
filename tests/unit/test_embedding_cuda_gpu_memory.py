"""Synthetic NVIDIA XML with actual shared parser; no model/driver effect."""

from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_cuda_probe_gpu_clients as owner

from tests.unit.test_embedding_cuda_probe_gpu_clients import document, row
from tests.unit.test_embedding_native_cuda_probe import case as case

MIB = 1024**2


def memory_document(device, *, total="16303 MiB", used="2 MiB", processes=()):
    rows = "".join(
        row(pid).replace("</process_info>", f"<used_memory>{amount}</used_memory></process_info>")
        for pid, amount in processes
    )
    raw = document(device, rows)
    memory = f"<fb_memory_usage><total>{total}</total><used>{used}</used></fb_memory_usage>"
    return raw.replace(b"<processes>", memory.encode() + b"<processes>")


def test_integer_display_counters_are_upper_bounds_and_absent_process_list_is_not_fabricated(case):
    device = case[2].device_capture
    result = owner.parse_cuda_gpu_memory(memory_document(device), device)
    assert result.device_used_bytes_upper_bound == 3 * MIB - 1
    assert result.device_total_bytes_upper_bound == 16304 * MIB - 1
    assert result.processes == ()


def test_duplicate_equal_pid_is_deduplicated_not_summed_and_independent_counters_need_not_be_atomic(
    case,
):
    device = case[2].device_capture
    raw = memory_document(
        device, used="2 MiB", processes=((203, "3 MiB"), (123, "0 MiB"), (203, "3 MiB"))
    )
    result = owner.parse_cuda_gpu_memory(raw, device)
    assert tuple((r.pid, r.used_bytes_upper_bound) for r in result.processes) == (
        (123, MIB - 1),
        (203, 4 * MIB - 1),
    )
    assert owner.parse_cuda_probe_gpu_clients(raw, device) == (123, 203)


def test_eight_gib_display_is_not_rounded_down_to_make_policy_pass(case):
    device = case[2].device_capture
    for value, within in (("8191 MiB", True), ("8192 MiB", False)):
        result = owner.parse_cuda_gpu_memory(memory_document(device, used=value), device)
        assert (result.device_used_bytes_upper_bound <= 8 * 1024**3) is within


@pytest.mark.parametrize(
    "fault",
    (
        "missing",
        "unknown",
        "float",
        "negative",
        "range",
        "total0",
        "used_above_total",
        "duplicate_counter",
        "pid_conflict",
        "missing_process_memory",
        "uuid",
        "entity",
    ),
)
def test_unknown_or_ambiguous_counters_never_become_zero_or_a_smaller_peak(case, fault):
    device = case[2].device_capture
    raw = memory_document(device, processes=((123, "2 MiB"),))
    if fault == "missing":
        raw = document(device)
    elif fault == "unknown":
        raw = raw.replace(b"<used>2 MiB", b"<used>N/A")
    elif fault == "float":
        raw = raw.replace(b"<used>2 MiB", b"<used>2.0 MiB")
    elif fault == "negative":
        raw = raw.replace(b"<used>2 MiB", b"<used>-1 MiB")
    elif fault == "range":
        raw = raw.replace(b"<used>2 MiB", b"<used>65536 MiB")
    elif fault == "total0":
        raw = memory_document(device, total="0 MiB", used="0 MiB")
    elif fault == "used_above_total":
        raw = memory_document(device, total="1 MiB", used="2 MiB")
    elif fault == "duplicate_counter":
        raw = raw.replace(b"</used>", b"</used><used>1 MiB</used>")
    elif fault == "pid_conflict":
        raw = memory_document(device, processes=((123, "2 MiB"), (123, "1 MiB")))
    elif fault == "missing_process_memory":
        raw = raw.replace(b"<used_memory>2 MiB</used_memory>", b"")
    elif fault == "uuid":
        raw = raw.replace(device.gpu_uuid.encode(), b"other")
    else:
        raw = raw.replace(b"<processes>", b'<!ENTITY malicious "x"><processes>')
    with pytest.raises(ValueError, match="CUDA_GPU_MEMORY_QUERY_INVALID"):
        owner.parse_cuda_gpu_memory(raw, device)


def test_memory_query_reuses_fixed_command_and_device_tool_fences(case, monkeypatch):
    device = case[2].device_capture
    events = []

    class Files:
        def __init__(self, uid):
            assert uid == 0

        def observe_protected_member_identity(self, path):
            assert str(path) == "/usr/bin/nvidia-smi"
            events.append("tool")

        def assert_unchanged(self):
            events.append("tool_recheck")

    def query(args, **kwargs):
        assert args == ("/usr/bin/nvidia-smi", "-q", "-x", "-i", device.gpu_uuid)
        assert kwargs["timeout"] == 15 and kwargs["cwd"] == "/"
        events.append("query")
        return SimpleNamespace(returncode=0, stdout=memory_document(device), stderr=b"")

    monkeypatch.setattr(owner.os, "getresuid", lambda: (0,) * 3)
    monkeypatch.setattr(owner, "NumericalRuntimeFileSnapshots", Files)
    monkeypatch.setattr(owner, "observe_runtime_device", lambda given: events.append("device"))
    monkeypatch.setattr(owner.subprocess, "run", query)
    assert owner.observe_cuda_gpu_memory(device).device_used_bytes_upper_bound == 3 * MIB - 1
    assert events == ["device", "tool", "query", "tool_recheck", "device"]


def test_nonroot_cannot_query_process_memory(case, monkeypatch):
    monkeypatch.setattr(owner.os, "getresuid", lambda: (1000,) * 3)
    monkeypatch.setattr(
        owner.subprocess, "run", lambda *_a, **_kw: pytest.fail("queried before guard")
    )
    with pytest.raises(ValueError, match="CUDA_GPU_MEMORY_QUERY_UNAVAILABLE"):
        owner.observe_cuda_gpu_memory(case[2].device_capture)
