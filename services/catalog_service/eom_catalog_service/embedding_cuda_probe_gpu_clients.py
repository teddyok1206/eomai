"""Fixed readonly NVIDIA process query for probe cleanup; not model/GPU admission."""

from __future__ import annotations

import os
import re
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass

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


def _gpu_processes(raw: bytes, expected: CudaRuntimeDeviceCapture) -> tuple[ET.Element, ET.Element]:
    """One bounded parser/device identity check; callers choose only their required counters."""
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
    return gpu, processes


def _process_pid(row: ET.Element) -> int:
    _require(row.tag == "process_info")
    value = _one_text(row, "pid")
    _require(re.fullmatch(r"[1-9][0-9]{0,9}", value) is not None and int(value) <= 2147483647)
    return int(value)


def parse_cuda_probe_gpu_clients(raw: bytes, expected: CudaRuntimeDeviceCapture) -> tuple[int, ...]:
    """Strict critical projection of vendor XML; discarded process names never drive cleanup."""
    _gpu, processes = _gpu_processes(raw, expected)
    pids: set[int] = set()
    for row in processes:
        pids.add(_process_pid(row))
    return tuple(sorted(pids))


@dataclass(frozen=True, slots=True)
class CudaProcessMemory:
    pid: int
    used_bytes_upper_bound: int

    def __post_init__(self) -> None:
        _require(type(self.pid) is int and 0 < self.pid <= 2147483647)
        _require(_is_memory_bound(self.used_bytes_upper_bound))


@dataclass(frozen=True, slots=True)
class CudaGpuMemorySnapshot:
    """Conservative integer-MiB display bounds, not exact NVML byte measurements."""

    device_used_bytes_upper_bound: int
    device_total_bytes_upper_bound: int
    processes: tuple[CudaProcessMemory, ...]

    def __post_init__(self) -> None:
        _require(
            _is_memory_bound(self.device_used_bytes_upper_bound)
            and _is_memory_bound(self.device_total_bytes_upper_bound)
            and self.device_total_bytes_upper_bound > 1024**2 - 1
            and self.device_used_bytes_upper_bound <= self.device_total_bytes_upper_bound
        )
        _require(type(self.processes) is tuple and len(self.processes) <= 1024)
        previous = 0
        for process in self.processes:
            _require(
                type(process) is CudaProcessMemory
                and process.pid > previous
                and process.used_bytes_upper_bound <= self.device_total_bytes_upper_bound
            )
            previous = process.pid


def _is_memory_bound(value: int) -> bool:
    return (
        type(value) is int
        and 1024**2 - 1 <= value < 64 * 1024**3
        and value % 1024**2 == 1024**2 - 1
    )


def _memory_upper_bound(text: str) -> int:
    match = re.fullmatch(r"(0|[1-9][0-9]{0,4}) MiB", text)
    _require(match is not None)
    assert match is not None
    count = int(match[1])
    _require(count < 65536)  # Existing evidence counter range, not the8GiB admission policy.
    return (count + 1) * 1024**2 - 1


def parse_cuda_gpu_memory(raw: bytes, expected: CudaRuntimeDeviceCapture) -> CudaGpuMemorySnapshot:
    try:
        gpu, processes = _gpu_processes(raw, expected)
        memory = gpu.findall("fb_memory_usage")
        _require(len(memory) == 1)
        total = _memory_upper_bound(_one_text(memory[0], "total"))
        used = _memory_upper_bound(_one_text(memory[0], "used"))
        _require(total >= used)
        by_pid: dict[int, int] = {}
        for row in processes:
            pid = _process_pid(row)
            amount = _memory_upper_bound(_one_text(row, "used_memory"))
            _require(amount <= total and (pid not in by_pid or by_pid[pid] == amount))
            by_pid[pid] = amount
        return CudaGpuMemorySnapshot(
            used, total, tuple(CudaProcessMemory(pid, by_pid[pid]) for pid in sorted(by_pid))
        )
    except ValueError:
        raise ValueError("CUDA_GPU_MEMORY_QUERY_INVALID") from None


def _observe_nvidia_projection[Observation](
    expected: CudaRuntimeDeviceCapture,
    parser: Callable[[bytes, CudaRuntimeDeviceCapture], Observation],
) -> Observation:
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
    projection = parser(result.stdout, expected)
    files.assert_unchanged()
    observe_runtime_device(expected)
    return projection


def observe_cuda_probe_gpu_clients(expected: CudaRuntimeDeviceCapture) -> tuple[int, ...]:
    """Root OS utility readback only; cannot accept worker/model-supplied commands or flags."""
    return _observe_nvidia_projection(expected, parse_cuda_probe_gpu_clients)


def observe_cuda_gpu_memory(expected: CudaRuntimeDeviceCapture) -> CudaGpuMemorySnapshot:
    """Fixed root query; a counter snapshot grants no model/GPU/source access."""
    try:
        return _observe_nvidia_projection(expected, parse_cuda_gpu_memory)
    except (ValueError, OSError, subprocess.TimeoutExpired):
        raise ValueError("CUDA_GPU_MEMORY_QUERY_UNAVAILABLE") from None
