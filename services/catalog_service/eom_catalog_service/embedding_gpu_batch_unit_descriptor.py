"""One original root-only absolute OpenFile binding for systemd without specifier support."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from eom_orchestrator.inference_transfer_cpu_handoff import (
    create_protected_cpu_handoff_member,
    fixed_owner_identity,
    protected_cpu_handoff_directory,
)
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation, inspect_fixed_unit

from eom_catalog_service.embedding_gpu_batch_launch import (
    GPU_BATCH_RUNTIME_ROOT,
    GPU_BATCH_TEMPLATE,
    native_embedding_gpu_batch_unit,
)

_UNIT_ROOT = Path("/run/systemd/system")
_MEMBER = "10-allocation.conf"
_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}


def embedding_gpu_batch_descriptor_path(attempt_hex: str) -> Path:
    unit = native_embedding_gpu_batch_unit(attempt_hex)
    return _UNIT_ROOT / (unit + ".d") / _MEMBER


def embedding_gpu_batch_descriptor_bytes(attempt_hex: str) -> bytes:
    native_embedding_gpu_batch_unit(attempt_hex)
    allocation = GPU_BATCH_RUNTIME_ROOT / attempt_hex / "allocation.json"
    return f"[Service]\nOpenFile=\nOpenFile={allocation}:gpu-batch-allocation:read-only\n".encode(
        "ascii"
    )


def require_embedding_gpu_batch_descriptor(attempt_hex: str, drop_in_paths: str) -> None:
    if drop_in_paths != str(embedding_gpu_batch_descriptor_path(attempt_hex)):
        raise ValueError("EMBEDDING_GPU_BATCH_UNIT_DESCRIPTOR_INVALID")


def inspect_embedding_gpu_batch_unit(unit_name: str, *, template: str) -> CpuUnitObservation:
    attempt = unit_name.partition("@")[2].removesuffix(".service")
    if template != GPU_BATCH_TEMPLATE or unit_name != native_embedding_gpu_batch_unit(attempt):
        raise ValueError("EMBEDDING_GPU_BATCH_UNIT_DESCRIPTOR_INVALID")
    return inspect_fixed_unit(
        unit_name,
        template=GPU_BATCH_TEMPLATE,
        expected_drop_in_paths=(str(embedding_gpu_batch_descriptor_path(attempt)),),
    )


def prepare_embedding_gpu_batch_descriptor(attempt_hex: str) -> None:
    """Exclusive materialization only; no model, request replay or arbitrary unit properties."""
    if os.getresuid() != (0, 0, 0) or os.getresgid() != (0, 0, 0):
        raise ValueError("EMBEDDING_GPU_BATCH_UNIT_DESCRIPTOR_INVALID")
    path = embedding_gpu_batch_descriptor_path(attempt_hex)
    # PID1 created only this original instance's directory via RuntimeDirectory.
    with protected_cpu_handoff_directory(
        path.parent, owner=fixed_owner_identity(), uid=0, gid=0, mode=0o700
    ) as directory:
        if os.listdir(directory):
            raise ValueError("EMBEDDING_GPU_BATCH_UNIT_DESCRIPTOR_ALREADY_PRESENT")
        create_protected_cpu_handoff_member(
            directory,
            _MEMBER,
            embedding_gpu_batch_descriptor_bytes(attempt_hex),
            owner_gid=0,
            mode=0o444,
        )
        os.fsync(directory)
    result = subprocess.run(
        ("/usr/bin/systemctl", "--no-ask-password", "daemon-reload"),
        capture_output=True,
        check=False,
        timeout=10,
        env=_ENV,
    )
    if result.returncode != 0 or len(result.stdout) > 16384 or len(result.stderr) > 16384:
        raise ValueError("EMBEDDING_GPU_BATCH_UNIT_DESCRIPTOR_RELOAD_UNCERTAIN")
