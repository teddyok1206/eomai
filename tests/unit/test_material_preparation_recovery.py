"""Preparation maintenance is closed and service drain is observed, not claimed."""

import subprocess
from datetime import UTC, datetime

import pytest
from eom_catalog_contracts.material_preparation_recovery import RecoverMaterialPreparationCommand
from eom_catalog_service import material_preparation_drain as owner


def command_data():
    return dict(
        actor_id="operator_" + "1" * 32,
        run_id="materialrun_" + "2" * 32,
        expected_updated_at=datetime.now(UTC).isoformat(),
        expected_input_sha256="sha256:" + "3" * 64,
        target_profile_sha256="sha256:" + "4" * 64,
        error_code="CREATIVE_PAGE_RENDERER_FAILED",
    )


def test_recovery_command_is_closed_and_does_not_accept_runtime_authority():
    assert (
        RecoverMaterialPreparationCommand.model_validate(command_data()).operation
        == "RECOVER_MATERIAL_PREPARATION"
    )
    for changes in (
        {"profile": {}},
        {"path": "/tmp/arbitrary"},
        {"service_drained": True},
        {"error_code": "UNKNOWN"},
        {"actor_id": "ADMIN"},
    ):
        with pytest.raises(ValueError):
            RecoverMaterialPreparationCommand.model_validate(command_data() | changes)


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "active",
        "failed",
        "pid",
        "job",
        "missing",
        "nonroot",
        "child",
        "child_timeout",
        "child_oversize",
        "child_failed_read",
    ],
)
def test_fixed_drain_requires_observed_stopped_service(monkeypatch, fault):
    state = dict(
        LoadState="loaded",
        ActiveState="inactive",
        SubState="dead",
        MainPID="0",
        ControlPID="0",
        Job="",
    )
    if fault == "active":
        state.update(ActiveState="active", SubState="running")
    elif fault == "failed":
        state.update(ActiveState="failed", SubState="failed")
    elif fault == "pid":
        state["MainPID"] = "123"
    elif fault == "job":
        state["Job"] = "123"
    elif fault == "missing":
        state["LoadState"] = "not-found"
    calls = []

    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        if "list-units" in arguments:
            if fault == "child_timeout":
                raise subprocess.TimeoutExpired(arguments, 10)
            return subprocess.CompletedProcess(
                arguments,
                1 if fault == "child_failed_read" else 0,
                b"x" * 65537
                if fault == "child_oversize"
                else b"eom-material-pdf-fixture.service running"
                if fault == "child"
                else b"",
                b"",
            )
        return subprocess.CompletedProcess(
            arguments, 0, "\n".join(f"{k}={v}" for k, v in state.items()).encode(), b""
        )

    monkeypatch.setattr(owner.os, "geteuid", lambda: 1 if fault == "nonroot" else 0)
    monkeypatch.setattr(owner.subprocess, "run", run)
    if fault is None:
        owner.StoppedMaterialPreparationService().require_quiescent()
        assert "eom-material-learning.service" in calls[0][0]
        assert "DATABASE_URL" not in calls[0][1]["env"]
        assert "list-units" in calls[1][0]
        assert "eom-material-office-*.service" in calls[1][0]
        assert "eom-office-converter@*.service" in calls[1][0]
    else:
        with pytest.raises(ValueError, match="MATERIAL_PREPARATION_"):
            owner.StoppedMaterialPreparationService().require_quiescent()
