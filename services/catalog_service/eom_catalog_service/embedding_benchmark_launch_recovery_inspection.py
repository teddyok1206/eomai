"""Resolve sealed launch-recovery evidence; recheck the original unit without effects."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from eom_catalog_contracts.embedding_benchmark_failed_attempt import (
    BenchmarkFailedAttemptObservation,
    parse_benchmark_failed_attempt_bytes,
    require_benchmark_failed_attempt_observation,
)
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

# The protected byte reader opens each ancestor read-only. The /run runtime root
# intentionally grants only traversal to the owner, so keep readable root proofs
# under the existing root-owned /opt hierarchy instead of broadening /run access.
RECOVERY_PROOF_ROOT = Path("/opt/eom/embedding-benchmark-preack-proofs")


def _require(value: bool) -> None:
    if not value:
        raise ValueError("BENCHMARK_PREACK_INSPECTION_INVALID")


def _require_original_unit_retired(
    observation: BenchmarkPreackObservation | BenchmarkFailedAttemptObservation,
) -> None:
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


class CapturedBenchmarkLaunchInspection:
    def __init__(
        self,
        observation: BenchmarkPreackObservation | BenchmarkFailedAttemptObservation,
        files: NumericalRuntimeFileSnapshots,
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
    ) -> Iterator[CapturedBenchmarkLaunchInspection]:
        with _capture_root_proof(
            self.execution_id, self.expected_raw_sha256, request, invocation, kind="PREACK"
        ) as captured:
            yield captured


@dataclass(frozen=True, slots=True)
class FixedBenchmarkFailedAttemptInspection:
    execution_id: str
    expected_raw_sha256: str

    def __post_init__(self) -> None:
        _require(re.fullmatch(r"[0-9a-f]{32}", self.execution_id) is not None)
        _require(re.fullmatch(r"sha256:[0-9a-f]{64}", self.expected_raw_sha256) is not None)

    @contextmanager
    def capture(
        self, request: BenchmarkOwnerRequest, invocation: BenchmarkWorkerInvocation
    ) -> Iterator[CapturedBenchmarkLaunchInspection]:
        with _capture_root_proof(
            self.execution_id, self.expected_raw_sha256, request, invocation, kind="FAILED"
        ) as captured:
            yield captured


@contextmanager
def _capture_root_proof(
    execution_id: str,
    expected_raw_sha256: str,
    request: BenchmarkOwnerRequest,
    invocation: BenchmarkWorkerInvocation,
    *,
    kind: Literal["PREACK", "FAILED"],
) -> Iterator[CapturedBenchmarkLaunchInspection]:
    owner = fixed_owner_identity()
    _require(
        invocation.execution_id == execution_id
        and (os.getresuid(), os.getresgid())
        in (
            ((0, 0, 0), (0, 0, 0)),
            ((owner.owner_uid,) * 3, (owner.owner_gid,) * 3),
        )
    )
    files = NumericalRuntimeFileSnapshots(0)
    raw = files.read(
        RECOVERY_PROOF_ROOT / (execution_id + ".json"),
        sha256=expected_raw_sha256,
        maximum=MAX_PREACK_RECOVERY_BYTES,
    )
    observation: BenchmarkPreackObservation | BenchmarkFailedAttemptObservation
    if kind == "PREACK":
        parsed = parse_benchmark_preack_bytes(raw)
        _require(isinstance(parsed, BenchmarkPreackObservation))
        assert isinstance(parsed, BenchmarkPreackObservation)
        observation = require_benchmark_preack_observation(request, invocation, parsed)
    else:
        failed = parse_benchmark_failed_attempt_bytes(raw)
        _require(isinstance(failed, BenchmarkFailedAttemptObservation))
        assert isinstance(failed, BenchmarkFailedAttemptObservation)
        observation = require_benchmark_failed_attempt_observation(request, invocation, failed)
    captured = CapturedBenchmarkLaunchInspection(observation, files)
    captured.assert_current()
    try:
        yield captured
    finally:
        captured.active = False
