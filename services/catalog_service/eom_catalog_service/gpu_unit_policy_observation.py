"""Bounded effective-policy readback through closed-purpose GPU entrypoints."""

from __future__ import annotations

import re
import subprocess
from typing import Literal

from eom_identifiers import sha256_bytes

from eom_catalog_service.embedding_benchmark_unit_policy import benchmark_unit_family_from_service
from eom_catalog_service.image_gpu_unit_identity import image_gpu_unit_template

_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}


def observe_gpu_unit_policy(
    unit: str, *, worker_account: Literal["eom-image", "eom-embedding-cuda"]
) -> str:
    """Readback/hash only: caller still pins template, process, source and lease."""
    if type(unit) is not str or type(worker_account) is not str:
        raise ValueError("GPU_UNIT_POLICY_INVALID")
    if worker_account == "eom-image":
        image_gpu_unit_template(unit)
    elif worker_account == "eom-embedding-cuda":
        try:
            benchmark_unit_family_from_service("CUDA", unit)
        except ValueError:
            raise ValueError("GPU_UNIT_POLICY_INVALID") from None
    else:
        raise ValueError("GPU_UNIT_POLICY_INVALID")
    return _observe_gpu_unit_policy(unit, worker_account=worker_account)


def observe_native_cuda_index_unit_policy(unit: str) -> str:
    """INDEX physical-policy readback only; original owner/source and root ACK are separate."""
    if (
        type(unit) is not str
        or re.fullmatch(r"eom-embedding-native-cuda-index@[0-9a-f]{32}\.service", unit) is None
    ):
        raise ValueError("GPU_UNIT_POLICY_INVALID")
    return _observe_gpu_unit_policy(unit, worker_account="eom-embedding-cuda")


def _observe_gpu_unit_policy(
    unit: str, *, worker_account: Literal["eom-image", "eom-embedding-cuda"]
) -> str:
    expected = {
        "User": worker_account,
        "Group": worker_account,
        "SupplementaryGroups": "eom-gpu-lease",
        "Type": "oneshot",
        "RemainAfterExit": "yes",
        "NotifyAccess": "main",
        "FileDescriptorStoreMax": "1",
        "FileDescriptorStorePreserve": "yes",
        "CollectMode": "inactive",
        "Restart": "no",
        "KillMode": "control-group",
        "NoNewPrivileges": "yes",
        "PrivateNetwork": "yes",
        "PrivateDevices": "no",
        "DevicePolicy": "closed",
        "CapabilityBoundingSet": "",
        "AmbientCapabilities": "",
    }
    try:
        result = subprocess.run(
            (
                "/usr/bin/systemctl",
                "show",
                unit,
                *("--property=" + field for field in (*expected, "DeviceAllow")),
            ),
            capture_output=True,
            check=False,
            timeout=10,
            env=_ENV,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("GPU_UNIT_POLICY_UNAVAILABLE") from None
    if result.returncode != 0 or len(result.stdout) > 16384 or len(result.stderr) > 16384:
        raise ValueError("GPU_UNIT_POLICY_UNAVAILABLE")
    fields, devices = {}, []
    for line in result.stdout.decode("ascii").splitlines():
        key, separator, value = line.partition("=")
        if not separator:
            raise ValueError("GPU_UNIT_POLICY_INVALID")
        if key == "DeviceAllow":
            devices.append(value)
        elif key in expected and key not in fields:
            fields[key] = value
        else:
            raise ValueError("GPU_UNIT_POLICY_INVALID")
    if (
        fields != expected
        or len(devices) != 5
        or set(devices)
        != {
            "char-rtc r",
            "/dev/nvidia0 rw",
            "/dev/nvidiactl rw",
            "/dev/nvidia-uvm rw",
            "/dev/nvidia-uvm-tools rw",
        }
    ):
        raise ValueError("GPU_UNIT_POLICY_INVALID")
    return sha256_bytes(result.stdout)
