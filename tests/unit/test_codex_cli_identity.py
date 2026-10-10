from __future__ import annotations

import os
import subprocess

import pytest
from eom_orchestrator import codex_cli_identity as identity

from tests.unit.test_codex_compatibility_runtime import protected_runtime as protected_runtime


@pytest.fixture
def selected_cli(protected_runtime, monkeypatch):
    launcher, _, _, reference, _ = protected_runtime
    monkeypatch.setattr(identity, "DISTRIBUTION_ROOT", launcher.parent.parent)
    monkeypatch.setattr(
        identity.subprocess,
        "run",
        lambda command, **_: subprocess.CompletedProcess(command, 0, b"codex-cli 0.162.1\n"),
    )
    return reference


def test_capture_is_frozen_exact_bytes_and_version(selected_cli):
    guard = identity.capture_codex_cli_identity(selected_cli)
    assert guard.identity.cli_version == "0.162.1"
    assert guard.identity.cli_launcher_sha256 == identity.protected_file_hash(guard.launcher)
    assert guard.identity.cli_binary_sha256 == identity.protected_file_hash(guard.native_binary)
    guard.assert_unchanged()


@pytest.mark.parametrize("component", ["launcher", "native", "reference", "ancestor"])
def test_selected_runtime_changed_metadata_or_reference_fails(
    selected_cli, protected_runtime, component
):
    guard = identity.capture_codex_cli_identity(selected_cli)
    launcher, native, _, reference, overrides = protected_runtime
    if component == "reference":
        reference.unlink()
        reference.symlink_to(native)
    elif component == "ancestor":
        overrides[reference.parent] = {"st_uid": 1000}
    else:
        path = launcher if component == "launcher" else native
        path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError):
        guard.assert_unchanged()


def test_selected_runtime_observation_is_one_immutable_epoch(
    selected_cli, protected_runtime, monkeypatch
):
    native = protected_runtime[1]

    def update_during_version(command, **_):
        native.write_bytes(b"new executable during version observation")
        return subprocess.CompletedProcess(command, 0, b"codex-cli 0.162.1\n")

    monkeypatch.setattr(identity.subprocess, "run", update_during_version)
    with pytest.raises(ValueError, match="changed"):
        identity.capture_codex_cli_identity(selected_cli)


@pytest.mark.parametrize(
    "output", [b"", b"codex-cli latest\n", b"codex-cli 0.162.1 extra\n", b"x" * 129]
)
def test_version_is_not_inferred_or_truncated(selected_cli, monkeypatch, output):
    monkeypatch.setattr(
        identity.subprocess,
        "run",
        lambda command, **_: subprocess.CompletedProcess(command, 0, output),
    )
    with pytest.raises(ValueError):
        identity.capture_codex_cli_identity(selected_cli)


def test_each_turn_checks_identity_without_rehashing(selected_cli, monkeypatch):
    guard = identity.capture_codex_cli_identity(selected_cli)

    def forbid_read(*_):
        raise AssertionError("no executable reads on subsequent admission")

    monkeypatch.setattr(os, "read", forbid_read)
    guard.assert_unchanged()


def test_unsupported_launcher_layout_is_not_adopted(selected_cli, protected_runtime):
    selected_cli.unlink()
    selected_cli.symlink_to(protected_runtime[1])
    with pytest.raises(ValueError, match="layout"):
        identity.capture_codex_cli_identity(selected_cli)
