"""Synthetic NVIDIA XML/query ports; no driver/model call or production cleanup acceptance."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_cuda_probe_gpu_clients as clients

from tests.unit.test_embedding_native_cuda_probe import case as case


def document(device, rows=""):
    return (
        '<?xml version="1.0"?>\n' + clients._DTD.decode() + "\n<nvidia_smi_log>"
        f"<driver_version>{device.numeric_device.driver_version}</driver_version>"
        "<attached_gpus>1</attached_gpus>"
        f'<gpu id="0000{device.pci_bus_id}"><uuid>{device.gpu_uuid}</uuid>'
        f"<pci><pci_bus_id>0000{device.pci_bus_id}</pci_bus_id></pci>"
        f"<processes>{rows}</processes></gpu></nvidia_smi_log>"
    ).encode()


def row(pid, kind="C"):
    return (
        f"<process_info><pid>{pid}</pid><type>{kind}</type>"
        "<process_name>discarded</process_name></process_info>"
    )


def test_empty_or_any_context_type_and_duplicate_pid_have_explicit_set_meaning(case):
    device = case[2].device_capture
    assert clients.parse_cuda_probe_gpu_clients(document(device), device) == ()
    rows = row(203, "G") + row(123, "C") + row(203, "C+G") + row(999, "O")
    assert clients.parse_cuda_probe_gpu_clients(document(device, rows), device) == (123, 203, 999)


@pytest.mark.parametrize(
    "fault",
    [
        "driver",
        "uuid",
        "pci",
        "gpu_id",
        "missing_processes",
        "unsupported_processes",
        "duplicate_gpu",
        "duplicate_uuid",
        "duplicate_driver",
        "duplicate_pid",
        "unknown_row",
        "old_dtd",
        "entities",
        "malformed",
        "too_large",
        "too_deep",
        "too_many_rows",
    ],
)
def test_malformed_unsupported_or_other_device_is_not_empty_success(case, fault):
    device = case[2].device_capture
    raw = document(device, row(123))
    if fault == "driver":
        raw = raw.replace(device.numeric_device.driver_version.encode(), b"999.1")
    elif fault == "uuid":
        raw = raw.replace(device.gpu_uuid.encode(), b"GPU-ffffffff-ffff-ffff-ffff-ffffffffffff")
    elif fault == "pci":
        raw = raw.replace(b"<pci_bus_id>", b"<pci_bus_id>ffff")
    elif fault == "gpu_id":
        raw = raw.replace(b'<gpu id="0000', b'<gpu id="ffff')
    elif fault == "missing_processes":
        raw = raw.replace(b"<processes>", b"<not_processes>").replace(
            b"</processes>", b"</not_processes>"
        )
    elif fault == "unsupported_processes":
        raw = document(device, "N/A")
    elif fault == "duplicate_gpu":
        raw = raw.replace(b"</nvidia_smi_log>", b"<gpu/></nvidia_smi_log>")
    elif fault == "duplicate_uuid":
        raw = raw.replace(b"</uuid>", b"</uuid><uuid>other</uuid>")
    elif fault == "duplicate_driver":
        raw = raw.replace(
            b"</driver_version>", b"</driver_version><driver_version>other</driver_version>"
        )
    elif fault == "duplicate_pid":
        raw = raw.replace(b"</pid>", b"</pid><pid>456</pid>")
    elif fault == "unknown_row":
        raw = document(device, "<not_a_process/>")
    elif fault == "old_dtd":
        raw = raw.replace(b"v13.dtd", b"v12.dtd")
    elif fault == "entities":
        raw = raw.replace(b"<nvidia_smi_log>", b'<!ENTITY hostile "x"><nvidia_smi_log>')
    elif fault == "malformed":
        raw = raw[:-1]
    elif fault == "too_large":
        raw += b" " * clients._MAX_XML_BYTES
    elif fault == "too_deep":
        raw = raw.replace(b"<attached_gpus>", b"<x>" * 65 + b"</x>" * 65 + b"<attached_gpus>")
    else:
        raw = document(device, row(123) * 1025)
    with pytest.raises(ValueError):
        clients.parse_cuda_probe_gpu_clients(raw, device)


@pytest.mark.parametrize("pid", ("0", "-1", "True", "1.0", "1e2", "01", "2147483648"))
def test_unknown_pid_is_not_an_empty_process_list(case, pid):
    device = case[2].device_capture
    with pytest.raises(ValueError):
        clients.parse_cuda_probe_gpu_clients(document(device, row(pid)), device)


@pytest.mark.parametrize("fault", (None, "nonzero", "timeout", "missing_binary", "tool_changed"))
def test_query_is_fixed_readonly_bounded_and_rechecked_without_retry(case, monkeypatch, fault):
    device = case[2].device_capture
    events = []

    class Files:
        def __init__(self, uid):
            assert uid == 0

        def observe_protected_member_identity(self, path):
            assert path == Path("/usr/bin/nvidia-smi")
            events.append("tool")

        def assert_unchanged(self):
            events.append("tool_recheck")
            if fault == "tool_changed":
                raise ValueError("synthetic tool identity drift")

    def query(args, **kwargs):
        events.append("query")
        assert args == ("/usr/bin/nvidia-smi", "-q", "-x", "-i", device.gpu_uuid)
        assert kwargs["timeout"] == 15 and kwargs["cwd"] == "/" and kwargs["check"] is False
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}
        if fault == "timeout":
            raise subprocess.TimeoutExpired(args, 15)
        if fault == "missing_binary":
            raise FileNotFoundError("synthetic missing utility")
        return SimpleNamespace(
            returncode=int(fault == "nonzero"), stdout=document(device), stderr=b""
        )

    monkeypatch.setattr(clients.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(clients, "NumericalRuntimeFileSnapshots", Files)
    monkeypatch.setattr(
        clients,
        "observe_runtime_device",
        lambda given: (
            events.append("device") if given == device else pytest.fail("wrong expected GPU")
        ),
    )
    monkeypatch.setattr(clients.subprocess, "run", query)
    if fault:
        with pytest.raises(ValueError):
            clients.observe_cuda_probe_gpu_clients(device)
    else:
        assert clients.observe_cuda_probe_gpu_clients(device) == ()
        assert events == ["device", "tool", "query", "tool_recheck", "device"]
    assert events.count("query") == 1
