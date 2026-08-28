from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_orchestrator.capability_observer import (
    REQUIRED_EXEC_HELP_FLAGS,
    ReviewedCapabilityPolicy,
    load_reviewed_capability_policy,
    observe_codex_cli_surface,
)
from eom_orchestrator.control_models import CodexAuthBindingRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.worker_auth import observe_worker_auth, project_worker_auth_health
from eom_orchestrator.worker_auth_exec import (
    AUTH_REQUIRED_EXIT,
    PROBE_TIMEOUT_EXIT,
    execute,
)
from eom_orchestrator.worker_registry import WorkerSlot
from eom_orchestrator.worker_systemd import WorkerAuthSystemdObservation

NOW = datetime(2026, 8, 23, 15, 0, tzinfo=UTC)


def _slot() -> WorkerSlot:
    return WorkerSlot(
        slot_id="01",
        linux_user="eom-cdx-01",
        role="authoring",
        enabled=True,
    )


def test_worker_auth_observation_is_ttl_bounded_and_sanitized() -> None:
    observed = observe_worker_auth(
        slot=_slot(),
        binding_id="authbinding_" + "1" * 32,
        account_label="slot01-account",
        observed_at=NOW,
        ttl=timedelta(minutes=15),
        probe=lambda _slot: WorkerAuthSystemdObservation(
            "AUTH_REQUIRED", "CODEX_LOGIN_REQUIRED", "eom-worker-auth-01.service"
        ),
        cli_version_observer=lambda: "0.147.0",
    )

    assert observed.state == "AUTH_REQUIRED"
    assert observed.reason_code == "CODEX_LOGIN_REQUIRED"
    assert observed.codex_cli_version == "0.147.0"
    assert observed.valid_until == NOW + timedelta(minutes=15)
    assert set(observed.document()) == {
        "schema_version",
        "binding_id",
        "slot_key",
        "account_label",
        "state",
        "reason_code",
        "codex_cli_version",
        "observed_at",
        "valid_until",
    }
    assert observed.document()["observed_at"] == "2026-08-23T15:00:00Z"
    assert observed.document()["valid_until"] == "2026-08-23T15:15:00Z"
    assert "credential" not in repr(observed).casefold()
    assert "token" not in repr(observed).casefold()


def test_auth_binding_persistence_has_no_credential_or_path_columns() -> None:
    column_names = {column.name for column in CodexAuthBindingRecord.__table__.columns}

    assert column_names == {
        "binding_id",
        "worker_slot_id",
        "current_assignment_revision_id",
        "account_label",
        "state",
        "reason_code",
        "codex_cli_version",
        "observed_at",
        "valid_until",
        "resource_version",
        "created_at",
        "updated_at",
    }
    assert not any(
        marker in name
        for name in column_names
        for marker in ("token", "secret", "credential", "password", "path", "session")
    )


def test_worker_auth_observation_fails_closed_when_cli_is_unavailable() -> None:
    observed = observe_worker_auth(
        slot=_slot(),
        binding_id="authbinding_" + "2" * 32,
        account_label="slot01-account",
        observed_at=NOW,
        ttl=timedelta(minutes=15),
        probe=lambda _slot: WorkerAuthSystemdObservation(
            "READY", None, "eom-worker-auth-01.service"
        ),
        cli_version_observer=lambda: None,
    )

    assert observed.state == "DEGRADED"
    assert observed.reason_code == "CODEX_CLI_UNAVAILABLE"
    assert observed.codex_cli_version == "0.0.0"


def test_expired_ready_health_projects_stale_without_mutation() -> None:
    binding = SimpleNamespace(
        binding_id="authbinding_" + "4" * 32,
        worker_slot_id="01",
        account_label="slot01-account",
        state="READY",
        reason_code=None,
        codex_cli_version="0.147.0",
        observed_at=NOW,
        valid_until=NOW + timedelta(minutes=15),
    )

    projected = project_worker_auth_health(
        binding,
        as_of=NOW + timedelta(minutes=16),  # type: ignore[arg-type]
    )

    assert projected.state == "STALE"
    assert projected.reason_code == "OBSERVATION_EXPIRED"
    assert binding.state == "READY"


@pytest.mark.parametrize("ttl", (timedelta(0), timedelta(hours=1, seconds=1)))
def test_worker_auth_observation_rejects_unreviewed_ttl(ttl: timedelta) -> None:
    with pytest.raises(ValueError, match="TTL"):
        observe_worker_auth(
            slot=_slot(),
            binding_id="authbinding_" + "3" * 32,
            account_label="slot01-account",
            observed_at=NOW,
            ttl=ttl,
            probe=lambda _slot: WorkerAuthSystemdObservation(
                "READY", None, "eom-worker-auth-01.service"
            ),
            cli_version_observer=lambda: "0.147.0",
        )


def _prepare_probe_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path.chmod(0o700)
    codex_home = tmp_path / ".codex"
    codex_home.mkdir(mode=0o700)
    monkeypatch.setattr(
        "eom_orchestrator.worker_auth_exec._validate_identity",
        lambda _user: (tmp_path, os.geteuid(), os.getegid()),
    )
    monkeypatch.setattr("eom_orchestrator.worker_auth_exec._validate_codex_binary", lambda: None)


def test_fixed_identity_probe_discards_success_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepare_probe_home(tmp_path, monkeypatch)
    results = iter(
        (
            subprocess.CompletedProcess((), 0, b"codex-cli 0.147.0\n", b""),
            subprocess.CompletedProcess(
                (), 0, b"credential-like account output", b"secret-like diagnostics"
            ),
        )
    )
    monkeypatch.setattr(
        "eom_orchestrator.worker_auth_exec.subprocess.run",
        lambda *_args, **_kwargs: next(results),
    )

    assert execute("01") == 0

    output = capsys.readouterr()
    assert output.out == "CODEX_AUTH_READY\n"
    assert output.err == ""
    assert "account" not in output.out
    assert "secret" not in output.out


def test_fixed_identity_probe_maps_nonzero_status_without_output_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepare_probe_home(tmp_path, monkeypatch)
    results = iter(
        (
            subprocess.CompletedProcess((), 0, b"codex-cli 0.147.0\n", b""),
            subprocess.CompletedProcess((), 1, b"device-code-like", b"token-like"),
        )
    )
    monkeypatch.setattr(
        "eom_orchestrator.worker_auth_exec.subprocess.run",
        lambda *_args, **_kwargs: next(results),
    )

    assert execute("01") == AUTH_REQUIRED_EXIT
    assert capsys.readouterr().out == "CODEX_AUTH_REQUIRED\n"


def test_fixed_identity_probe_maps_timeout_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepare_probe_home(tmp_path, monkeypatch)
    calls = 0

    def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess((), 0, b"codex-cli 0.147.0\n", b"")
        raise subprocess.TimeoutExpired(("codex", "login", "status"), 30)

    monkeypatch.setattr("eom_orchestrator.worker_auth_exec.subprocess.run", run)

    assert execute("01") == PROBE_TIMEOUT_EXIT
    assert calls == 2
    assert capsys.readouterr().out == "CODEX_AUTH_PROBE_TIMEOUT\n"


def test_reviewed_capability_policy_is_bounded_and_protected(tmp_path: Path) -> None:
    path = tmp_path / "capabilities.yaml"
    path.write_text(
        "version: 1\n"
        "expected_codex_cli_version: 0.147.0\n"
        "models:\n"
        "  - model: gpt-5.6-terra\n"
        "    reasoning_efforts: [medium, high, xhigh]\n",
        encoding="utf-8",
    )
    path.chmod(0o600)

    policy = load_reviewed_capability_policy(path, require_root_owned=False)

    assert isinstance(policy, ReviewedCapabilityPolicy)
    assert policy.expected_codex_cli_version == "0.147.0"
    assert policy.models[0].model == "gpt-5.6-terra"
    assert tuple(policy.models[0].reasoning_efforts) == ("medium", "high", "xhigh")

    path.chmod(0o602)
    with pytest.raises(ControlPlaneError) as captured:
        load_reviewed_capability_policy(path, require_root_owned=False)
    assert captured.value.code == "CONTROL_CAPABILITY_POLICY_INVALID"


def test_cli_surface_observation_returns_only_allowlisted_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_help = " ".join(sorted(REQUIRED_EXEC_HELP_FLAGS)) + " device-code secret-value"
    monkeypatch.setattr(
        "eom_orchestrator.capability_observer.observe_codex_cli_version",
        lambda: "0.147.0",
    )
    monkeypatch.setattr(
        "eom_orchestrator.capability_observer.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess((), 0, raw_help, "token-like"),
    )

    version, flags = observe_codex_cli_surface()

    assert version == "0.147.0"
    assert flags == REQUIRED_EXEC_HELP_FLAGS
    assert "device-code" not in repr((version, flags))
    assert "secret-value" not in repr((version, flags))


def test_cli_surface_observation_rejects_missing_contract_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    help_without_model = " ".join(sorted(REQUIRED_EXEC_HELP_FLAGS - {"--model"}))
    monkeypatch.setattr(
        "eom_orchestrator.capability_observer.observe_codex_cli_version",
        lambda: "0.147.0",
    )
    monkeypatch.setattr(
        "eom_orchestrator.capability_observer.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess((), 0, help_without_model, ""),
    )

    with pytest.raises(ControlPlaneError) as captured:
        observe_codex_cli_surface()
    assert captured.value.code == "CONTROL_CAPABILITY_OBSERVATION_FAILED"
