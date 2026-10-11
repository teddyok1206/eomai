"""Two fixed CPU resource profiles; all process/policy observations are synthetic."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_orchestrator import inference_transfer_cpu_installation as installation
from eom_orchestrator import inference_transfer_cpu_systemd as cpu
from eom_orchestrator.inference_transfer_cpu_handoff import OWNER_ROOT, CpuHandoffIdentity
from eom_orchestrator.inference_transfer_experiment_ports import (
    CpuExperimentRunError,
    LocalExperimentInput,
)

from tests.unit.inference_transfer_fixtures import NOW, sha
from tests.unit.test_inference_transfer_cpu_installation import properties
from tests.unit.test_inference_transfer_cpu_systemd import EXECUTION, observation, status_document

ROOT = Path(__file__).resolve().parents[2]


def test_existing_e5_defaults_and_pinned_files_remain_unchanged() -> None:
    assert cpu.cpu_resource_limits().template == cpu.CPU_TEMPLATE
    assert cpu.cpu_resource_limits().memory_max_bytes == 2 * 1024**3
    assert cpu.FixedCpuExperimentLauncher().profile is cpu.CpuResourceProfile.E5
    assert cpu.cpu_unit_names(EXECUTION) == (
        f"eom-embedding-experiment-prepare@{EXECUTION}.service",
        f"eom-embedding-experiment@{EXECUTION}.service",
    )
    for name, expected in (
        (cpu.CPU_TEMPLATE, "1097b66b9ac385e0f9b6ae28e2c45b33ca6fb497532a6e80245fb24c110ff832"),
        (
            cpu.PREPARE_TEMPLATE,
            "432f8d2cd0a9997f01edec6c559217c3a2bb5956a3341bde76d420722b7c9a4b",
        ),
        (installation.PROBE, "310fdb4e8d49dd89c19edcb3db08a352f6facf405ddb9a4fc7d59db430ae1dfb"),
    ):
        assert hashlib.sha256((ROOT / "infra/systemd" / name).read_bytes()).hexdigest() == expected


def test_bge_template_changes_only_description_and_fixed_memory_ceiling() -> None:
    original = (ROOT / "infra/systemd" / cpu.CPU_TEMPLATE).read_text()
    bge = (ROOT / "infra/systemd" / cpu.BGE_CPU_TEMPLATE).read_text()
    assert (
        bge.replace("isolated BGE CPU", "isolated CPU").replace("MemoryMax=6G", "MemoryMax=2G")
        == original
    )
    limits = cpu.cpu_resource_limits(cpu.CpuResourceProfile.BGE)
    assert limits.template_sha256 == hashlib.sha256(bge.encode()).hexdigest()
    assert limits.memory_max_bytes == 6 * 1024**3 and limits.timeout_seconds == 1800
    assert "CPUQuota=400%" in bge and "Restart=no" in bge
    assert "StartLimitBurst=1" in bge and "PrivateNetwork=yes" in bge
    assert cpu.cpu_unit_names(EXECUTION, profile=cpu.CpuResourceProfile.BGE) == (
        cpu.cpu_unit_names(EXECUTION)[0],
        f"eom-embedding-experiment-bge@{EXECUTION}.service",
    )


def test_resource_values_and_launcher_are_frozen() -> None:
    limits = cpu.cpu_resource_limits(cpu.CpuResourceProfile.BGE)
    launcher = cpu.FixedCpuExperimentLauncher(profile=cpu.CpuResourceProfile.BGE)
    with pytest.raises(FrozenInstanceError):
        limits.memory_max_bytes = 1  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        launcher.profile = cpu.CpuResourceProfile.E5  # type: ignore[misc]
    with pytest.raises(TypeError):
        cpu._RESOURCE_LIMITS[cpu.CpuResourceProfile.BGE] = limits  # type: ignore[index]


@pytest.mark.parametrize("wrong", ["BGE", "E5", "arbitrary.service", None, 6, object()])
def test_resource_profile_requires_closed_enum_before_any_io(
    monkeypatch: pytest.MonkeyPatch, wrong: Any
) -> None:
    monkeypatch.setattr(cpu, "_require_template", lambda *_a: pytest.fail("no template read"))
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: pytest.fail("no process"))
    for operation in (
        lambda: cpu.cpu_resource_limits(wrong),
        lambda: cpu.cpu_unit_names(EXECUTION, profile=wrong),
        lambda: cpu.require_cpu_runtime(profile=wrong),
        lambda: cpu.FixedCpuExperimentLauncher(profile=wrong),
    ):
        with pytest.raises(ValueError, match="RESOURCE_PROFILE_INVALID"):
            operation()


def test_resource_profile_does_not_accept_unit_timeout_or_memory_overrides() -> None:
    constructor: Any = cpu.FixedCpuExperimentLauncher
    for name, value in (("unit", "arbitrary.service"), ("memory", "99G"), ("timeout", 0)):
        with pytest.raises(TypeError):
            constructor(**{name: value})


@pytest.mark.parametrize("profile", list(cpu.CpuResourceProfile))
def test_runtime_checks_only_exact_selected_main_shared_prepare_and_protected_interpreter(
    monkeypatch: pytest.MonkeyPatch, profile: cpu.CpuResourceProfile
) -> None:
    checks: list[tuple[str, str]] = []
    paths: list[Path] = []
    monkeypatch.setattr(
        cpu, "_require_template", lambda name, digest: checks.append((name, digest))
    )

    def root_path(path: Path, **_kwargs: Any) -> Any:
        paths.append(path)
        return SimpleNamespace(stat=lambda: SimpleNamespace(st_mode=stat.S_IFREG | 0o555))

    monkeypatch.setattr(cpu, "_root_path", root_path)
    cpu.require_cpu_runtime(profile=profile)
    limits = cpu.cpu_resource_limits(profile)
    assert checks == [
        (cpu.PREPARE_TEMPLATE, cpu.PREPARE_TEMPLATE_SHA256),
        (limits.template, limits.template_sha256),
    ]
    assert paths == [cpu.PREPARE_PYTHON, cpu.CPU_PYTHON]


def bge_observation(kind: str, *, main: bool = False) -> cpu.CpuUnitObservation:
    value = observation(kind, main=main)
    return (
        replace(value, fragment_path=str(cpu.UNIT_ROOT / cpu.BGE_CPU_TEMPLATE)) if main else value
    )


def fake_bge_launcher(
    monkeypatch: pytest.MonkeyPatch, states: list[cpu.CpuUnitObservation]
) -> tuple[
    LocalExperimentInput, list[Any], list[LocalExperimentInput], list[cpu.CpuResourceProfile]
]:
    checks: list[cpu.CpuResourceProfile] = []
    calls: list[Any] = []
    copied: list[LocalExperimentInput] = []
    values = iter(states)
    monkeypatch.setattr(
        cpu, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.geteuid(), os.getegid())
    )
    monkeypatch.setattr(cpu, "require_cpu_runtime", lambda *, profile: checks.append(profile))

    def inspect(unit: str, *, template: str) -> cpu.CpuUnitObservation:
        value = next(values)
        assert value.fragment_path == str(cpu.UNIT_ROOT / template)
        assert unit == template.replace("@.service", f"@{EXECUTION}.service")
        return value

    monkeypatch.setattr(cpu, "inspect_cpu_unit", inspect)
    monkeypatch.setattr(cpu, "materialize_cpu_output", copied.append)

    def start(argv: tuple[str, ...], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", start)
    return (
        LocalExperimentInput(OWNER_ROOT / EXECUTION, EXECUTION, NOW, sha(), 100),
        calls,
        copied,
        checks,
    )


def test_explicit_bge_profile_starts_one_fixed_unit_after_selected_protection_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final = [bge_observation("success"), bge_observation("success", main=True)]
    prepared, calls, copied, checks = fake_bge_launcher(
        monkeypatch, [bge_observation("fresh"), bge_observation("fresh", main=True), *final, *final]
    )
    cpu.FixedCpuExperimentLauncher(profile=cpu.CpuResourceProfile.BGE).run(prepared)
    assert checks == [cpu.CpuResourceProfile.BGE] and copied == [prepared] and len(calls) == 1
    assert calls[0][0] == (
        cpu.SYSTEMCTL,
        "--no-ask-password",
        "start",
        cpu.cpu_unit_names(EXECUTION, profile=cpu.CpuResourceProfile.BGE)[1],
    )
    assert calls[0][1]["timeout"] == 1830 and calls[0][1]["env"] == cpu._ENVIRONMENT


@pytest.mark.parametrize("state", ["success", "running", "failed", "timeout"])
def test_bge_attempted_instance_cannot_restart_or_fall_back_to_e5(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    prepared, calls, copied, _checks = fake_bge_launcher(
        monkeypatch, [bge_observation("fresh"), bge_observation(state, main=True)]
    )
    with pytest.raises(CpuExperimentRunError, match="UNCERTAIN"):
        cpu.FixedCpuExperimentLauncher(profile=cpu.CpuResourceProfile.BGE).run(prepared)
    assert calls == copied == []


def test_bge_timeout_keeps_uncertainty_and_has_no_second_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _calls, copied, _checks = fake_bge_launcher(
        monkeypatch, [bge_observation("fresh"), bge_observation("fresh", main=True)]
    )
    attempts = 0

    def timeout(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        raise subprocess.TimeoutExpired("fixed-bge-start", 1830)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(CpuExperimentRunError, match="UNCERTAIN"):
        cpu.FixedCpuExperimentLauncher(profile=cpu.CpuResourceProfile.BGE).run(prepared)
    assert attempts == 1 and copied == []


def test_bge_runtime_missing_is_terminal_before_start_without_e5_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, calls, copied, _checks = fake_bge_launcher(monkeypatch, [])
    selected: list[cpu.CpuResourceProfile] = []

    def missing(*, profile: cpu.CpuResourceProfile) -> None:
        selected.append(profile)
        raise FileNotFoundError("missing fixed profile")

    monkeypatch.setattr(cpu, "require_cpu_runtime", missing)
    with pytest.raises(CpuExperimentRunError, match="KNOWN_FAILED"):
        cpu.FixedCpuExperimentLauncher(profile=cpu.CpuResourceProfile.BGE).run(prepared)
    assert selected == [cpu.CpuResourceProfile.BGE] and calls == copied == []


@pytest.mark.parametrize("wrong", [cpu.CPU_TEMPLATE, "/tmp/arbitrary.service"])
def test_bge_status_does_not_accept_a_different_template(
    monkeypatch: pytest.MonkeyPatch, wrong: str
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess(
            [], 0, status_document(FragmentPath=str(cpu.UNIT_ROOT / wrong)), b""
        ),
    )
    with pytest.raises(ValueError, match="STATUS_INVALID"):
        cpu.inspect_cpu_unit(
            cpu.cpu_unit_names(EXECUTION, profile=cpu.CpuResourceProfile.BGE)[1],
            template=cpu.BGE_CPU_TEMPLATE,
        )


def profile_policies() -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    main = properties(cpu.CPU_TEMPLATE) | {"MemoryMax": str(2 * 1024**3)}
    bge = properties(cpu.BGE_CPU_TEMPLATE) | {"MemoryMax": str(6 * 1024**3)}
    probe = properties(installation.PROBE) | {"MemoryMax": str(2 * 1024**3)}
    prepare = properties(cpu.PREPARE_TEMPLATE, root=True)
    return main, bge, probe, prepare


def test_bge_effective_policy_preserves_every_old_sandbox_property_except_fixed_memory() -> None:
    installation.validate_bge_effective_policies(*profile_policies())


@pytest.mark.parametrize("key", list(installation._SANDBOX))
def test_bge_effective_policy_rejects_each_changed_property(key: str) -> None:
    main, bge, probe, prepare = profile_policies()
    bge[key] = "unreviewed"
    with pytest.raises(ValueError, match=r"POLICY_(INVALID|MISMATCH)"):
        installation.validate_bge_effective_policies(main, bge, probe, prepare)


def test_bge_effective_policy_cannot_reinterpret_changed_e5_memory() -> None:
    main, bge, probe, prepare = profile_policies()
    main["MemoryMax"] = probe["MemoryMax"] = str(6 * 1024**3)
    with pytest.raises(ValueError, match="POLICY_INVALID"):
        installation.validate_bge_effective_policies(main, bge, probe, prepare)


def test_bge_public_profile_check_reads_policy_after_exact_bytes_and_never_launches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Any] = []
    main, bge, probe, prepare = profile_policies()
    prepare_unit, main_unit = cpu.cpu_unit_names(installation._INSTANCE)
    bge_unit = cpu.cpu_unit_names(installation._INSTANCE, profile=cpu.CpuResourceProfile.BGE)[1]
    values = {main_unit: main, bge_unit: bge, installation.PROBE: probe, prepare_unit: prepare}
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        installation,
        "require_cpu_runtime",
        lambda *, profile=cpu.CpuResourceProfile.E5: calls.append(("runtime", profile)),
    )
    monkeypatch.setattr(
        installation, "_checked_file", lambda path, digest: calls.append(("bytes", path, digest))
    )

    def read(unit: str) -> dict[str, str]:
        assert len([call for call in calls if call[0] in {"runtime", "bytes"}]) == 4
        calls.append(("read", unit))
        return values[unit]

    monkeypatch.setattr(installation, "_properties", read)
    monkeypatch.setattr(
        installation, "verify_polkit_scope", lambda *, profile: calls.append(("pkcheck", profile))
    )
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: pytest.fail("no unit/model execution"))
    installation.verify_bge_cpu_resource_profile()
    assert calls[:2] == [
        ("runtime", cpu.CpuResourceProfile.E5),
        ("runtime", cpu.CpuResourceProfile.BGE),
    ]
    assert calls[-1] == ("pkcheck", cpu.CpuResourceProfile.BGE)


def test_bge_public_profile_check_denies_nonroot_before_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 990)
    monkeypatch.setattr(installation, "require_cpu_runtime", lambda **_k: pytest.fail("no read"))
    with pytest.raises(ValueError, match="ROOT_REQUIRED"):
        installation.verify_bge_cpu_resource_profile()


def test_bge_polkit_checks_only_fixed_start_authority_not_prepare_restart_or_worker_grants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    @contextmanager
    def subject(user: str) -> Any:
        yield installation.PolkitSubject(
            123, 456, 990 if user == "eom-workflow-runner" else 979, 122
        )

    def run(argv: tuple[str, ...], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0 if len(calls) == 1 else 1)

    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(installation, "_temporary_polkit_subject", subject)
    monkeypatch.setattr(subprocess, "run", run)
    installation.verify_polkit_scope(profile=cpu.CpuResourceProfile.BGE)
    assert len(calls) == 6 and all(call[0] == "/usr/bin/pkcheck" for call in calls)
    assert (
        calls[0][7]
        == cpu.cpu_unit_names(installation._INSTANCE, profile=cpu.CpuResourceProfile.BGE)[1]
    )
    assert calls[0][-1] == "start" and calls[3][-1] == "restart"
    assert calls[4][7] == "eom-embedding-experiment-bge@invalid.service"


def test_polkit_successor_preserves_original_rule_bytes_except_one_fixed_prefix() -> None:
    path = ROOT / "infra/polkit/50-eom-worker-units.rules"
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == installation.POLKIT_SHA256
    original = (
        raw.decode()
        .replace(
            "    var embeddingBgeExperimentUnit = "
            "/^eom-embedding-experiment-bge@embeddingexecution_[0-9a-f]{32}\\.service$/;\n",
            "",
        )
        .replace(
            "embeddingExperimentUnit.test(unit) || embeddingBgeExperimentUnit.test(unit)",
            "embeddingExperimentUnit.test(unit)",
        )
    )
    assert hashlib.sha256(original.encode()).hexdigest() == (
        "fc63581550983bdfe9742556d8f1331ac51925ffa962302c9b3c38ffed72b08a"
    )
