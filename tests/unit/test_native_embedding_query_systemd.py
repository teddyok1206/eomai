"""Synthetic unit observations and real temporary shared flock; no installed QUERY grant."""

from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from eom_identifiers import sha256_file
from eom_orchestrator import native_embedding_cpu_execution as cpu
from eom_orchestrator import native_embedding_query_systemd as launcher
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_inference_transfer_cpu_systemd import observation
from tests.unit.test_native_embedding_query_handoff import prepared


def setup_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, states: list[tuple[str, str]]
) -> tuple[launcher.FixedNativeQueryLauncher, list[tuple[str, ...]]]:
    root = tmp_path / "owner"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(cpu, "CAPACITY_ROOT", root)
    monkeypatch.setattr(
        cpu, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.geteuid(), os.getegid())
    )
    monkeypatch.setattr(launcher, "require_fixed_cpu_unit_template", lambda *_a: None)
    monkeypatch.setattr(launcher, "require_native_cpu_environment_file", lambda *_a: None)
    monkeypatch.setattr(launcher, "require_native_cpu_runtime_roots", lambda: None)
    monkeypatch.setattr(cpu, "require_no_active_native_cpu_execution", lambda: None)
    monkeypatch.setattr(cpu, "require_empty_native_cpu_cgroup", lambda *_a: None)
    reads = iter(states)

    def observe(_self: Any, _id: str) -> Any:
        a, b = next(reads)
        return observation(a), observation(b, main=True)

    monkeypatch.setattr(launcher.FixedNativeQueryLauncher, "_observe", observe)
    monkeypatch.setattr(
        launcher, "materialize_native_query_output", lambda _: "synthetic-query-result"
    )
    calls: list[tuple[str, ...]] = []

    def start(args: tuple[str, ...], **_kw: Any) -> Any:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(cpu.subprocess, "run", start)
    return launcher.FixedNativeQueryLauncher("a" * 64, "b" * 64, lambda: None), calls


def test_real_template_hashes_root_prepare_and_readonly_numeric_profile() -> None:
    root = Path(__file__).resolve().parents[2]
    for name, digest in (
        (launcher.PREPARE_TEMPLATE, launcher.PREPARE_TEMPLATE_SHA256),
        (launcher.QUERY_TEMPLATE, launcher.QUERY_TEMPLATE_SHA256),
    ):
        assert sha256_file(root / "infra/systemd" / name) == "sha256:" + digest
    source = (root / "infra/systemd" / launcher.QUERY_TEMPLATE).read_text()
    assert "Requires=eom-embedding-native-query-prepare@%i.service" in source
    assert "eom_catalog_service.embedding_native_cpu QUERY " in source
    assert "ReadWritePaths" not in source and "SupplementaryGroups" not in source
    prepare_source = (root / "infra/systemd" / launcher.PREPARE_TEMPLATE).read_text()
    assert "EOM_EMBEDDING_QUERY_PREPARE_ENTRYPOINT} QUERY %i" in prepare_source
    assert "EnvironmentFile=/etc/eom/embedding-native-query-owner.env" in prepare_source
    assert "ReadWritePaths=/run/eom-embedding-native-query" in prepare_source
    assert "InaccessiblePaths=/opt/eom/embedding-models" in prepare_source
    cpu.validate_fixed_native_cpu_resources(prepared().workflow_request.resource_profile)


@pytest.mark.parametrize("replay", (False, True))
def test_exact_terminal_readback_or_one_start_never_substitutes_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replay: bool,
) -> None:
    states = (
        [("success", "success"), ("success", "success")]
        if replay
        else [("fresh", "fresh"), ("success", "success"), ("success", "success")]
    )
    adapter, calls = setup_launcher(tmp_path, monkeypatch, states)
    value = prepared()
    assert adapter.run(value) == "synthetic-query-result"
    assert calls == (
        []
        if replay
        else [
            (
                "/usr/bin/systemctl",
                "--no-ask-password",
                "start",
                launcher.native_query_unit_names(value.execution_id)[1],
            )
        ]
    )
    assert all("cpu-index" not in arg for call in calls for arg in call)


@pytest.mark.parametrize("state", ("running", "failed", "timeout"))
def test_uncertain_failed_or_active_existing_handle_never_restarts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    adapter, calls = setup_launcher(tmp_path, monkeypatch, [("success", state)])
    with pytest.raises(launcher.NativeQueryLaunchError, match="UNCERTAIN"):
        adapter.run(prepared())
    assert calls == []


def test_timeout_reobserves_the_same_query_invocation_without_second_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, calls = setup_launcher(
        tmp_path, monkeypatch, [("fresh", "fresh"), ("success", "success"), ("success", "success")]
    )

    def timeout(args: tuple[str, ...], **_kw: Any) -> None:
        calls.append(args)
        raise subprocess.TimeoutExpired(args, 210)

    monkeypatch.setattr(cpu.subprocess, "run", timeout)
    assert adapter.run(prepared()) == "synthetic-query-result" and len(calls) == 1


def test_changed_terminal_invocation_cannot_be_accepted_as_original_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, calls = setup_launcher(tmp_path, monkeypatch, [])
    pair = observation("success"), observation("success", main=True)
    changed = pair[0], replace(pair[1], invocation_id="b" * 32)
    values = iter((pair, changed))
    monkeypatch.setattr(launcher.FixedNativeQueryLauncher, "_observe", lambda *_: next(values))
    with pytest.raises(launcher.NativeQueryLaunchError, match="UNCERTAIN"):
        adapter.run(prepared())
    assert calls == []


def test_query_owner_environment_and_template_seal_are_required_before_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, calls = setup_launcher(tmp_path, monkeypatch, [])
    reads: list[Path] = []

    def require(path: Path, _hash: str) -> None:
        reads.append(path)
        if path.name == "embedding-native-query-owner.env":
            raise ValueError("synthetic missing QUERY purpose seal")

    monkeypatch.setattr(launcher, "require_native_cpu_environment_file", require)
    with pytest.raises(launcher.NativeQueryLaunchError):
        adapter.run(prepared())
    assert reads == [
        Path("/etc/eom/embedding-native-cpu.env"),
        Path("/etc/eom/embedding-native-query-owner.env"),
    ]
    assert calls == []


def test_bootstrap_preserves_legacy_index_arity_and_requires_explicit_query_purpose() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "scripts/embedding/prepare_native_index.py").read_text()
    assert source.index("value.st_uid != 0") < source.index("native_embedding_query_handoff")
    assert "len(sys.argv) == 2" in source
    assert 'len(sys.argv) == 3 and sys.argv[1] == "QUERY"' in source
    assert "eval(" not in source and "import_module(" not in source


def test_schema_failure_has_stable_redacted_launch_error_and_no_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, calls = setup_launcher(tmp_path, monkeypatch, [("success", "success")])

    def corrupt(_prepared: Any) -> Any:
        raise SchemaError("synthetic result contents must not escape")

    monkeypatch.setattr(launcher, "materialize_native_query_output", corrupt)
    with pytest.raises(launcher.NativeQueryLaunchError, match=r"^NATIVE_QUERY_UNCERTAIN$"):
        adapter.run(prepared())
    assert calls == []
