"""Fixed unit selection and bounded commands; positive root/systemd ports are synthetic."""

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_benchmark_unit_control as control
from eom_catalog_service.embedding_benchmark_cuda_observation import (
    CUDA_BENCHMARK_SOCKET_SHA256,
    CUDA_BENCHMARK_TEMPLATE_SHA256,
)
from eom_identifiers import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def root(monkeypatch):
    monkeypatch.setattr(control.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(control.os, "getresgid", lambda: (0, 0, 0))


@pytest.mark.parametrize("device", ("CPU", "CUDA"))
def test_pinned_templates_are_repo_bytes_and_old_cuda_aliases_are_unchanged(
    root, monkeypatch, device
):
    calls = []

    class Files:
        def __init__(self, uid):
            assert uid == 0

        def read(self, path, *, sha256, maximum):
            assert path.parent == Path("/etc/systemd/system") and maximum == 65536
            raw = (ROOT / "infra/systemd" / path.name).read_bytes()
            assert sha256_bytes(raw) == sha256
            calls.append(path.name)
            return raw

        def assert_unchanged(self):
            calls.append("fence")

    monkeypatch.setattr(control, "NumericalRuntimeFileSnapshots", Files)
    units = control.FixedRootBenchmarkUnits(device, "a" * 32)
    assert units.capture_installed() and calls == [units.template, units.socket_template, "fence"]
    assert CUDA_BENCHMARK_TEMPLATE_SHA256 == control.CUDA_BENCHMARK_TEMPLATE_SHA256
    assert CUDA_BENCHMARK_SOCKET_SHA256 == control.CUDA_BENCHMARK_SOCKET_SHA256


@pytest.mark.parametrize(
    "device,execution", (("GPU", "a" * 32), ("CPU", "../x"), ("CPU", "A" * 32), ("CUDA", "a" * 31))
)
def test_foreign_family_or_execution_is_never_a_command_target(root, device, execution):
    with pytest.raises(ValueError, match="IDENTITY_INVALID"):
        control.FixedRootBenchmarkUnits(device, execution)


def test_real_nonroot_is_rejected_before_names_or_commands():
    if os.getuid() == 0:
        pytest.skip("requires actual nonroot")
    with pytest.raises(ValueError, match="ROOT_REQUIRED"):
        control.FixedRootBenchmarkUnits("CPU", "a" * 32)


@pytest.mark.parametrize("device", ("cpu", "cuda"))
def test_socket_identity_matches_workflow_owner_service_without_new_group_membership(device):
    def fields(name):
        return dict(
            line.split("=", 1)
            for line in (ROOT / "infra/systemd" / name).read_text().splitlines()
            if line and not line.startswith(("#", "[")) and "=" in line
        )

    owner = fields("eom-workflow-runner.service")
    listener = fields(f"eom-embedding-benchmark-{device}@.socket")
    assert listener["SocketUser"] == owner["User"] == "eom-workflow-runner"
    assert listener["SocketGroup"] == owner["Group"] == "eom"
    assert listener["SocketMode"] == "0600"


@pytest.mark.parametrize("device", ("CPU", "CUDA"))
def test_only_fixed_names_are_passed_to_bounded_systemctl(root, monkeypatch, device):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        assert kwargs == dict(capture_output=True, check=False, timeout=10, env=control._ENV)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(
        control, "subprocess", SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired)
    )
    units = control.FixedRootBenchmarkUnits(device, "a" * 32)
    units.start_socket()
    units.start_service()
    units.stop_socket()
    assert calls == [
        ("/usr/bin/systemctl", "start", units.socket),
        ("/usr/bin/systemctl", "--no-block", "start", units.service),
        ("/usr/bin/systemctl", "stop", units.socket),
    ]


def test_cuda_can_never_use_cpu_retirement_to_bypass_retained_gpu_lifetime(root, monkeypatch):
    monkeypatch.setattr(
        control.subprocess, "run", lambda *a, **k: pytest.fail("GPU retirement bypass")
    )
    units = control.FixedRootBenchmarkUnits("CUDA", "a" * 32)
    with pytest.raises(ValueError, match="CPU_RETIREMENT_REQUIRED"):
        units.retire_cpu_service("SUCCEEDED")


@pytest.mark.parametrize("fault", ("exit", "stdout", "stderr", "timeout", "oserror"))
def test_uncertain_effect_has_no_implicit_retry(root, monkeypatch, fault):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if fault == "timeout":
            raise subprocess.TimeoutExpired(args, 10)
        if fault == "oserror":
            raise OSError("synthetic IO failure")
        return SimpleNamespace(
            returncode=1 if fault == "exit" else 0,
            stdout=b"x" * 16385 if fault == "stdout" else b"",
            stderr=b"x" * 16385 if fault == "stderr" else b"",
        )

    monkeypatch.setattr(
        control, "subprocess", SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired)
    )
    units = control.FixedRootBenchmarkUnits("CPU", "a" * 32)
    with pytest.raises(ValueError, match="EFFECT_UNCERTAIN"):
        units.start_service()
    assert len(calls) == 1
