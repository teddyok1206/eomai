"""Resolve sealed root pre-ACK evidence and recheck the original unit without effects."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.embedding_benchmark_preack_recovery import (
    MAX_PREACK_RECOVERY_BYTES,
    BenchmarkPreackObservation,
    parse_benchmark_preack_bytes,
    require_benchmark_preack_observation,
)
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    BenchmarkWorkerInvocation,
)
from eom_orchestrator.inference_transfer_cpu_handoff import fixed_owner_identity
from eom_orchestrator.systemd_unit_processes import root_owned_unit_processes

from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots

PREACK_PROOF_ROOT = Path("/run/eom-incremental-embeddings/benchmark-preack-recovery")


def _require(value: bool) -> None:
    if not value:
        raise ValueError("BENCHMARK_PREACK_INSPECTION_INVALID")


def _require_original_unit_retired(observation: BenchmarkPreackObservation) -> None:
    # Read-only PID1 properties are available to the owner; root-only retirement
    # effects and the protected original intent/result remain a separate boundary.
    properties = (
        "LoadState",
        "ActiveState",
        "SubState",
        "MainPID",
        "NFileDescriptorStore",
        "InvocationID",
        "Job",
        "ControlGroup",
        "NeedDaemonReload",
        "DropInPaths",
    )
    result = subprocess.run(
        (
            "/usr/bin/systemctl",
            "show",
            observation.native_service,
            *("--property=" + key for key in properties),
        ),
        capture_output=True,
        check=False,
        timeout=10,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC"},
    )
    _require(result.returncode == 0 and len(result.stdout) <= 16384 and len(result.stderr) <= 16384)
    values: dict[str, str] = {}
    for line in result.stdout.decode("ascii").splitlines():
        key, separator, value = line.partition("=")
        _require(bool(separator) and key in properties and key not in values)
        values[key] = value
    _require(
        set(values) == set(properties)
        and values["LoadState"] in {"loaded", "not-found"}
        and values["ActiveState"] == "inactive"
        and values["SubState"] == "dead"
        and values["MainPID"] == "0"
        and values["NFileDescriptorStore"] == "0"
        and values["InvocationID"] in {"", observation.native_invocation_id}
        and values["Job"] in {"", "0"}
        and values["ControlGroup"] == ""
        and values["NeedDaemonReload"] == "no"
        and values["DropInPaths"] == ""
    )
    try:
        _require(root_owned_unit_processes(observation.native_service) == ())
    except FileNotFoundError:
        _require(not (Path("/sys/fs/cgroup/system.slice") / observation.native_service).exists())


class CapturedBenchmarkPreackInspection:
    def __init__(
        self, observation: BenchmarkPreackObservation, files: NumericalRuntimeFileSnapshots
    ) -> None:
        self.observation, self.files, self.active = observation, files, True

    def assert_current(self) -> None:
        _require(self.active)
        self.files.assert_unchanged()
        _require(
            Path("/proc/sys/kernel/random/boot_id").read_text().strip() == self.observation.boot_id
        )
        _require_original_unit_retired(self.observation)
        self.files.assert_unchanged()


@dataclass(frozen=True, slots=True)
class FixedBenchmarkPreackInspection:
    execution_id: str
    expected_raw_sha256: str

    def __post_init__(self) -> None:
        _require(re.fullmatch(r"[0-9a-f]{32}", self.execution_id) is not None)
        _require(re.fullmatch(r"sha256:[0-9a-f]{64}", self.expected_raw_sha256) is not None)

    @contextmanager
    def capture(
        self, request: BenchmarkOwnerRequest, invocation: BenchmarkWorkerInvocation
    ) -> Iterator[CapturedBenchmarkPreackInspection]:
        owner = fixed_owner_identity()
        _require(
            invocation.execution_id == self.execution_id
            and (os.getresuid(), os.getresgid())
            in (
                ((0, 0, 0), (0, 0, 0)),
                ((owner.owner_uid,) * 3, (owner.owner_gid,) * 3),
            )
        )
        files = NumericalRuntimeFileSnapshots(0)
        raw = files.read(
            PREACK_PROOF_ROOT / (self.execution_id + ".json"),
            sha256=self.expected_raw_sha256,
            maximum=MAX_PREACK_RECOVERY_BYTES,
        )
        observation = parse_benchmark_preack_bytes(raw)
        _require(isinstance(observation, BenchmarkPreackObservation))
        assert isinstance(observation, BenchmarkPreackObservation)
        require_benchmark_preack_observation(request, invocation, observation)
        captured = CapturedBenchmarkPreackInspection(observation, files)
        captured.assert_current()
        try:
            yield captured
        finally:
            captured.active = False
