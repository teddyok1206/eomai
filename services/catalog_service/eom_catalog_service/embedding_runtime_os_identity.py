"""Fixed bounded Linux numerical identity read-back; no ML import, subprocess or GPU query."""

from __future__ import annotations

import platform
import re
import sys
from pathlib import Path

from eom_catalog_contracts.embedding_installed_runtime_proof import (
    CpuRuntimeDeviceCapture,
    CudaRuntimeDeviceCapture,
    RuntimeDeviceCapture,
)
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingNumericalDevice

from eom_catalog_service.embedding_runtime_files import (
    read_live_runtime_os_file,
)
from eom_catalog_service.embedding_runtime_files import (
    require_runtime_proof as _require,
)


def require_native_runtime_interpreter(prefix: Path) -> str:
    _require(
        sys.version_info[:3] == (3, 12, 13)
        and platform.python_implementation() == "CPython"
        and sys.platform == "linux"
        and platform.machine() == "x86_64",
        "INTERPRETER_UNSUPPORTED",
    )
    _require(
        Path(sys.prefix) == prefix and Path(sys.executable) == prefix / "bin/python3.12",
        "INTERPRETER_PREFIX_MISMATCH",
    )
    return platform.python_version()


def observe_runtime_device(
    capture: RuntimeDeviceCapture,
    *,
    proc_root: Path = Path("/proc"),
    owner_uid: int = 0,
) -> EmbeddingNumericalDevice:
    if isinstance(capture, CpuRuntimeDeviceCapture):
        raw = read_live_runtime_os_file(
            proc_root / "cpuinfo", maximum=2 * 1024**2, owner_uid=owner_uid
        )
        identities: set[tuple[str, int, int, int]] = set()
        for block in raw.decode("utf-8").strip().split("\n\n"):
            fields: dict[str, str] = {}
            for line in block.splitlines():
                key, separator, value = line.partition(":")
                _require(bool(separator) and key.strip() not in fields, "CPUINFO_INVALID")
                fields[key.strip()] = value.strip()
            _require(
                {"processor", "vendor_id", "cpu family", "model", "stepping"} <= fields.keys(),
                "CPUINFO_INVALID",
            )
            vendor = fields["vendor_id"]
            _require(re.fullmatch(r"[A-Za-z0-9_-]{1,32}", vendor) is not None, "CPUINFO_INVALID")
            numbers = tuple(fields[key] for key in ("cpu family", "model", "stepping"))
            _require(
                all(re.fullmatch(r"[0-9]{1,3}", value) for value in numbers), "CPUINFO_INVALID"
            )
            identities.add((vendor, int(numbers[0]), int(numbers[1]), int(numbers[2])))
        _require(len(identities) == 1, "CPU_HETEROGENEOUS")
        vendor, family, model, stepping = next(iter(identities))
        actual = EmbeddingNumericalDevice(
            kind="CPU",
            hardware_model=f"{vendor} family {family} model {model} stepping {stepping}",
            compute_capability=None,
            driver_version=None,
        )
    else:
        assert isinstance(capture, CudaRuntimeDeviceCapture)
        driver_text = read_live_runtime_os_file(
            proc_root / "driver/nvidia/version", maximum=4096, owner_uid=owner_uid
        ).decode("utf-8")
        drivers = re.findall(
            r"^NVRM version:.*?\b([0-9]{3}\.[0-9]+\.[0-9]+)\b", driver_text, re.MULTILINE
        )
        _require(len(drivers) == 1, "DRIVER_OBSERVATION_INVALID")
        info_raw = read_live_runtime_os_file(
            proc_root / "driver/nvidia/gpus" / capture.pci_bus_id / "information",
            maximum=16384,
            owner_uid=owner_uid,
        )
        fields = {}
        for line in info_raw.decode("utf-8").splitlines():
            key, separator, value = line.partition(":")
            _require(bool(separator) and key.strip() not in fields, "GPU_OBSERVATION_INVALID")
            fields[key.strip()] = value.strip()
        boot = (
            read_live_runtime_os_file(
                proc_root / "sys/kernel/random/boot_id", maximum=64, owner_uid=owner_uid
            )
            .decode("ascii")
            .strip()
        )
        _require(
            fields.get("GPU UUID") == capture.gpu_uuid
            and fields.get("Bus Location") == capture.pci_bus_id
            and fields.get("Device Minor") == str(capture.device_minor)
            and boot == capture.boot_id,
            "GPU_CAPTURE_STALE",
        )
        actual = EmbeddingNumericalDevice(
            kind="CUDA",
            hardware_model=fields["Model"],
            compute_capability=capture.numeric_device.compute_capability,
            driver_version=drivers[0],
        )
    _require(actual == capture.numeric_device, "DEVICE_CAPTURE_MISMATCH")
    return actual
