"""Fixed readonly NVIDIA process query for probe cleanup; not model/GPU admission."""

from __future__ import annotations

import os
import re
import subprocess
import xml.etree.ElementTree as ET

from eom_catalog_contracts.embedding_installed_runtime_proof import CudaRuntimeDeviceCapture

from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots
from eom_catalog_service.embedding_runtime_os_identity import observe_runtime_device

_MAX_XML_BYTES = 256 * 1024
_DTD = b'<!DOCTYPE nvidia_smi_log SYSTEM "nvsmi_device_v13.dtd">'
_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("NATIVE_CUDA_PROBE_GPU_CLIENT_QUERY_INVALID")


def _one_text(node: ET.Element, name: str) -> str:
    children = node.findall(name)
    _require(len(children) == 1 and len(children[0]) == 0 and children[0].text is not None)
    return (children[0].text or "").strip()


def _pci(value: str) -> str:
    match = re.fullmatch(r"([0-9a-fA-F]{4,8}):([0-9a-fA-F]{2}):([0-9a-fA-F]{2})\.([0-7])", value)
    _require(match is not None)
    assert match is not None
    domain, bus, device, function = (int(group, 16) for group in match.groups())
    _require(domain <= 0xFFFF)
    return f"{domain:04x}:{bus:02x}:{device:02x}.{function}"


def parse_cuda_probe_gpu_clients(raw: bytes, expected: CudaRuntimeDeviceCapture) -> tuple[int, ...]:
    """Strict critical projection of vendor XML; discarded process names never drive cleanup."""
    expected = CudaRuntimeDeviceCapture.model_validate(expected)
    _require(type(raw) is bytes and 0 < len(raw) <= _MAX_XML_BYTES)
    lines = raw.splitlines()
    declarations = [line for line in lines if line.startswith(b"<!DOCTYPE")]
    _require(declarations == [_DTD])
    document = b"\n".join(line for line in lines if line != _DTD)
    _require(b"<!" not in document)  # No embedded DTD/entity expansion or alternate declaration.
    try:
        root = ET.fromstring(document)
    except (ET.ParseError, ValueError):
        raise ValueError("NATIVE_CUDA_PROBE_GPU_CLIENT_QUERY_INVALID") from None
    stack, count = [(root, 1)], 0
    while stack:
        node, depth = stack.pop()
        count += 1
        _require(depth <= 64 and count <= 16384)
        stack.extend((child, depth + 1) for child in node)
    _require(root.tag == "nvidia_smi_log")
    _require(_one_text(root, "driver_version") == expected.numeric_device.driver_version)
    attached = _one_text(root, "attached_gpus")
    _require(re.fullmatch(r"[1-9][0-9]{0,2}", attached) is not None)
    gpus = root.findall("gpu")
    _require(len(gpus) == 1)
    gpu = gpus[0]
    _require(_one_text(gpu, "uuid") == expected.gpu_uuid)
    _require(_pci(gpu.get("id", "")) == expected.pci_bus_id)
    pci = gpu.findall("pci")
    _require(len(pci) == 1 and _pci(_one_text(pci[0], "pci_bus_id")) == expected.pci_bus_id)
    containers = gpu.findall("processes")
    _require(len(containers) == 1)
    processes = containers[0]
    _require(not (processes.text or "").strip() and len(processes) <= 1024)
    pids: set[int] = set()
    for row in processes:
        _require(row.tag == "process_info")
        value = _one_text(row, "pid")
        _require(re.fullmatch(r"[1-9][0-9]{0,9}", value) is not None and int(value) <= 2147483647)
        pids.add(int(value))
    return tuple(sorted(pids))


def observe_cuda_probe_gpu_clients(expected: CudaRuntimeDeviceCapture) -> tuple[int, ...]:
    """Root OS utility readback only; cannot accept worker/model-supplied commands or flags."""
    from pathlib import Path

    _require(os.getresuid() == (0, 0, 0))
    expected = CudaRuntimeDeviceCapture.model_validate(expected)
    observe_runtime_device(expected)
    files = NumericalRuntimeFileSnapshots(0)
    files.observe_protected_member_identity(Path("/usr/bin/nvidia-smi"))
    try:
        result = subprocess.run(
            ("/usr/bin/nvidia-smi", "-q", "-x", "-i", expected.gpu_uuid),
            capture_output=True,
            check=False,
            timeout=15,
            cwd="/",
            env=_ENV,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("NATIVE_CUDA_PROBE_GPU_CLIENT_QUERY_UNAVAILABLE") from None
    _require(result.returncode == 0 and len(result.stderr) <= 16384)
    pids = parse_cuda_probe_gpu_clients(result.stdout, expected)
    files.assert_unchanged()
    observe_runtime_device(expected)
    return pids
