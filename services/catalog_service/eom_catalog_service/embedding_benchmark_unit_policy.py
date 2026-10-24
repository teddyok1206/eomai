"""Closed benchmark unit identities; no root commands, runtime or source authority."""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType

from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkDevice,
    BenchmarkExecutionPolicy,
    benchmark_timeout_seconds,
)

BUDGET1200_OWNER_RELEASE = "d381e6bc480606a828898ebe2e9942dd8a143677"
_BUDGET1200_SITE = (
    "/opt/eom/embedding-owner-releases/" + BUDGET1200_OWNER_RELEASE + "/site-packages"
)
_BUDGET1200_CPU_BOOTSTRAP = (
    'import runpy,sys;sys.path.insert(0,"' + _BUDGET1200_SITE + '");'
    'runpy.run_module("eom_catalog_service.embedding_benchmark_budget1200_cpu",run_name="__main__")'
)
_BUDGET1200_CUDA_BOOTSTRAP = (
    "import runpy,signal,sys;signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGUSR1});"
    "sys.exit(1) if signal.SIGUSR1 in signal.sigpending() else None;"
    'sys.path.insert(0,"' + _BUDGET1200_SITE + '");'
    'runpy.run_module("eom_catalog_service.embedding_benchmark_budget1200_cuda",run_name="__main__")'
)


@dataclass(frozen=True, slots=True)
class BenchmarkUnitFamily:
    service_template: str
    socket_template: str
    service_sha256: str
    socket_sha256: str
    entrypoint_module: str
    timeout_seconds: int
    bootstrap_program: str | None = None

    @property
    def interpreter_arguments(self) -> tuple[str, ...]:
        """Exact admitted argv, shared by unit-byte tests and live process verification."""
        if self.bootstrap_program is not None:
            return ("-I", "-B", "-c", self.bootstrap_program)
        return ("-I", "-B", "-m", self.entrypoint_module)


_FAMILIES = MappingProxyType(
    {
        ("CPU", 180): BenchmarkUnitFamily(
            "eom-embedding-benchmark-cpu@.service",
            "eom-embedding-benchmark-cpu@.socket",
            "sha256:512d2b563c8e73ec0cc39a4679f7acb9bb1ccf4a380eeb22a417a1c6cc275350",
            "sha256:ea94f5a5bf5d28373dad0ae0260c0c7cc3c477216d4201e0e904e2d9245b3c02",
            "eom_catalog_service.embedding_benchmark_cpu",
            180,
        ),
        ("CUDA", 180): BenchmarkUnitFamily(
            "eom-embedding-benchmark-cuda@.service",
            "eom-embedding-benchmark-cuda@.socket",
            "sha256:5955e54a578c5f547019298525eb44a8d8814fcbf8afb0070861a3b0a815b6eb",
            "sha256:63bfab8b2be928e92ccb8b8c500186e3b49cbdff1fd2e4b8f0aaec4df724c522",
            "eom_catalog_service.embedding_benchmark_cuda",
            180,
        ),
        ("CPU", 600): BenchmarkUnitFamily(
            "eom-embedding-benchmark-cpu-budget600@.service",
            "eom-embedding-benchmark-cpu-budget600@.socket",
            "sha256:74f0b5f53adaf280e7b5c43e6a010ad7d3225bad641989f64fadb706dd802cfb",
            "sha256:b78ee198db1eea42470da3a6c4274f6eaf4b750fbfaca805a7c647e74b9253a3",
            "eom_catalog_service.embedding_benchmark_budget600_cpu",
            600,
        ),
        ("CUDA", 600): BenchmarkUnitFamily(
            "eom-embedding-benchmark-cuda-budget600@.service",
            "eom-embedding-benchmark-cuda-budget600@.socket",
            "sha256:96b7f9d95fc5f835279c29738ce1aba283e7e64c984c37aa86116e17342dc13a",
            "sha256:5faad17ec5e80bbbb3e8fb05be274358f243a47825f9b32966dfad6d7b24f4f9",
            "eom_catalog_service.embedding_benchmark_budget600_cuda",
            600,
        ),
        ("CPU", 1200): BenchmarkUnitFamily(
            "eom-embedding-benchmark-cpu-budget1200@.service",
            "eom-embedding-benchmark-cpu-budget1200@.socket",
            "sha256:c34214dd6eb551f15987dfb07f548487ba829f603bcd4b06b44149543c586f1b",
            "sha256:1bd3fca6c88b8f58de33393617b6d3213762d0c45020eba09cb58ab6296d72a7",
            "eom_catalog_service.embedding_benchmark_budget1200_cpu",
            1200,
            _BUDGET1200_CPU_BOOTSTRAP,
        ),
        ("CUDA", 1200): BenchmarkUnitFamily(
            "eom-embedding-benchmark-cuda-budget1200@.service",
            "eom-embedding-benchmark-cuda-budget1200@.socket",
            "sha256:e28a653509229b6e073d107924a06eac0861f8fa7ffdbced163b1ed63b66336e",
            "sha256:32213967e9fb94d508b9db525c33090545f5a195d3f662c7481d70f5599b9770",
            "eom_catalog_service.embedding_benchmark_budget1200_cuda",
            1200,
            _BUDGET1200_CUDA_BOOTSTRAP,
        ),
    }
)
_FRAGMENT_FAMILIES = MappingProxyType(
    {
        (device, "/etc/systemd/system/" + family.service_template): family
        for (device, _), family in _FAMILIES.items()
    }
)
_SERVICE_FAMILIES = MappingProxyType(
    {
        (device, family.service_template.partition("@")[0]): family
        for (device, _), family in _FAMILIES.items()
    }
)


def benchmark_unit_family(
    device: BenchmarkDevice, policy: BenchmarkExecutionPolicy | None = None
) -> BenchmarkUnitFamily:
    """Select immutable bytes from an exact released policy; absence means legacy only."""
    if type(device) is not str or device not in {"CPU", "CUDA"}:
        raise ValueError("BENCHMARK_UNIT_IDENTITY_INVALID")
    seconds = 180 if policy is None else benchmark_timeout_seconds(policy)
    family = _FAMILIES.get((device, seconds))
    if family is None:
        raise ValueError("BENCHMARK_UNIT_FAMILY_NOT_RELEASED")
    return family


def benchmark_unit_family_from_fragment(
    device: BenchmarkDevice, fragment_path: str
) -> BenchmarkUnitFamily:
    """Classify an exact observed known fragment; no filesystem or permission grant."""
    if type(device) is not str or type(fragment_path) is not str:
        raise ValueError("BENCHMARK_UNIT_IDENTITY_INVALID")
    family = _FRAGMENT_FAMILIES.get((device, fragment_path))
    if family is None:
        raise ValueError("BENCHMARK_UNIT_IDENTITY_INVALID")
    return family


def benchmark_unit_family_from_service(device: BenchmarkDevice, unit: str) -> BenchmarkUnitFamily:
    """Classify one known service family with an exact immutable execution instance."""
    if type(device) is not str or type(unit) is not str:
        raise ValueError("BENCHMARK_UNIT_IDENTITY_INVALID")
    prefix, separator, instance = unit.partition("@")
    if not separator or re.fullmatch(r"[0-9a-f]{32}\.service", instance) is None:
        raise ValueError("BENCHMARK_UNIT_IDENTITY_INVALID")
    family = _SERVICE_FAMILIES.get((device, prefix))
    if family is None:
        raise ValueError("BENCHMARK_UNIT_IDENTITY_INVALID")
    return family
