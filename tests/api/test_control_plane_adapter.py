from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from eom_api.services.control_plane_adapter import ControlPlaneAdapter
from eom_identifiers import content_sha256
from eom_orchestrator.control_commands import _terminalize_record
from eom_orchestrator.worker_usage_exec import (
    _catalog_snapshot,
    _normalized_model,
    _observation_document,
)
from eom_workflow import CodexUsageObservationV2


@pytest.mark.parametrize(
    ("slot_key", "request_schema"),
    [
        ("slot05", "codex-auth-enrollment-request/1.0"),
        ("slot06", "codex-auth-enrollment-request/1.1"),
    ],
)
def test_auth_enrollment_projection_removes_internal_schema_discriminator(
    slot_key: str,
    request_schema: str,
) -> None:
    requested_at = datetime(2026, 8, 29, 13, 20, tzinfo=UTC)
    row = SimpleNamespace(
        enrollment_id="authflow_" + "1" * 32,
        binding_id="authbinding_" + "2" * 32,
        canonical_document={
            "schema_version": request_schema,
            "slot_key": slot_key,
        },
        requested_account_label="textbook-analysis-slot06",
        state="REQUESTED",
        challenge_revealed_at=None,
        assignment_revision_id=None,
        error_code=None,
        requested_at=requested_at,
        started_at=None,
        expires_at=requested_at + timedelta(minutes=10),
        completed_at=None,
        resource_version=1,
    )

    projection = ControlPlaneAdapter._enrollment(
        row,  # type: ignore[arg-type]
        challenge_available=False,
    )

    assert projection.slot_key == slot_key
    assert "schema_version" not in projection.model_dump(mode="json")


def test_usage_result_projection_exposes_only_sanitized_allowance() -> None:
    observed_at = datetime(2026, 9, 5, 1, 2, tzinfo=UTC)
    usage: dict[str, object] = {
        "schema_version": "codex-usage-observation/1.0",
        "command_id": "codexcmd_" + "1" * 32,
        "binding_id": "authbinding_" + "2" * 32,
        "slot_key": "slot01",
        "account_type": "chatgpt",
        "plan_type": "edu",
        "windows": [
            {
                "limit_id": "codex",
                "limit_name": "Codex",
                "window_kind": "SECONDARY",
                "used_percent": 41,
                "window_duration_minutes": 10080,
                "resets_at": (observed_at + timedelta(days=3)).isoformat().replace("+00:00", "Z"),
            }
        ],
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "observation_sha256": "sha256:" + "0" * 64,
    }
    usage["observation_sha256"] = content_sha256(
        {key: value for key, value in usage.items() if key != "observation_sha256"}
    )
    document: dict[str, object] = {
        "schema_version": "codex-control-command-result/1.1",
        "command_id": "codexcmd_" + "1" * 32,
        "command_type": "OBSERVE",
        "binding_id": "authbinding_" + "2" * 32,
        "outcome": "SUCCEEDED",
        "result_resource_version": 3,
        "binding_state": "READY",
        "reason_code": None,
        "processed_at": (observed_at + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        "usage_observation": usage,
        "result_sha256": "sha256:" + "0" * 64,
    }
    document["result_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "result_sha256"}
    )

    projected = ControlPlaneAdapter._usage_from_result(document)

    assert projected is not None
    assert projected.plan_type == "edu"
    assert projected.windows[0].window_duration_minutes == 10080
    serialized = projected.model_dump_json()
    assert "binding_id" not in serialized
    assert "account_type" not in serialized
    assert "sha256" not in serialized

    document["result_sha256"] = "sha256:" + "3" * 64
    with pytest.raises(ValueError, match="result hash differs"):
        ControlPlaneAdapter._usage_from_result(document)


@pytest.mark.parametrize("available", [True, False])
@pytest.mark.parametrize("binding_state", ["READY", "DEGRADED"])
def test_native_catalog_projection_is_separate_from_usage_and_capability(
    available: bool,
    binding_state: str,
) -> None:
    catalog = _catalog_snapshot(
        cli_version="0.160.0",
        models=(
            _normalized_model(
                {
                    "id": "observed-model",
                    "model": "observed-model",
                    "displayName": "Observed model",
                    "hidden": False,
                    "isDefault": True,
                    "defaultReasoningEffort": "medium",
                    "supportedReasoningEfforts": [{"reasoningEffort": "medium"}],
                    "inputModalities": ["text", "image"],
                    "privateField": "never-projected",
                }
            ),
        )
        if available
        else (),
        reason_code=None if available else "CODEX_MODEL_CATALOG_TIMEOUT",
    )
    document = _observation_document(
        command_id="codexcmd_" + "1" * 32,
        binding_id="authbinding_" + "2" * 32,
        slot_id="01",
        account_result={"account": {"type": "chatgpt", "planType": "plus"}},
        usage_result={
            "rateLimits": {"primary": {"usedPercent": 100 if binding_state == "DEGRADED" else 20}}
        },
        model_catalog=catalog,
    )
    row = SimpleNamespace(
        command_id=document["command_id"],
        binding_id=document["binding_id"],
        command_type="OBSERVE",
        attempts=1,
        requested_at=catalog.observed_at,
    )
    _terminalize_record(
        row,
        outcome="SUCCEEDED",
        result_resource_version=3,
        binding_state=binding_state,
        reason_code=None,
        processed_at=datetime.now(UTC),
        usage_observation=CodexUsageObservationV2.model_validate(document),
    )
    usage, projected = ControlPlaneAdapter._observation_views(row.result_document)
    assert usage is not None
    assert projected is not None
    assert projected.model_dump(mode="json") == catalog.model_dump(mode="json")
    assert projected.state == ("OBSERVED" if available else "UNAVAILABLE")
    assert usage.windows[0].used_percent == (100 if binding_state == "DEGRADED" else 20)
    assert "never-projected" not in projected.model_dump_json()
    command = ControlPlaneAdapter._command(row)  # type: ignore[arg-type]
    assert command.model_catalog == projected
    assert command.state == "SUCCEEDED"
    with pytest.raises(ValueError, match="identity differs"):
        ControlPlaneAdapter._observation_views(
            row.result_document, expected_binding_id="authbinding_" + "3" * 32
        )
    with pytest.raises(ValueError, match="identity differs"):
        ControlPlaneAdapter._observation_views(row.result_document, expected_slot_key="slot02")
    row.result_document["result_sha256"] = "sha256:" + "4" * 64
    with pytest.raises(ValueError, match="result hash differs"):
        ControlPlaneAdapter._observation_views(row.result_document)


def test_capability_snapshot_projection_keeps_its_own_freshness_and_hash() -> None:
    observed_at = datetime(2026, 10, 9, tzinfo=UTC)
    document = {
        "schema_version": "codex-capability-snapshot/1.0",
        "capability_snapshot_id": "capsnap_" + "4" * 32,
        "binding_id": "authbinding_" + "2" * 32,
        "codex_cli_version": "0.160.0",
        "source": "LOCAL_OBSERVATION",
        "capabilities": [
            {"model": "approved-model", "reasoning_efforts": ["high"], "state": "AVAILABLE"}
        ],
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "valid_until": (observed_at + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }
    document["snapshot_sha256"] = content_sha256(document)
    row = SimpleNamespace(
        capability_snapshot_id=document["capability_snapshot_id"],
        binding_id=document["binding_id"],
        codex_cli_version=document["codex_cli_version"],
        source=document["source"],
        snapshot_sha256=document["snapshot_sha256"],
        canonical_document=document,
        observed_at=observed_at,
        valid_until=observed_at + timedelta(hours=1),
    )
    projected = ControlPlaneAdapter._capability_snapshot(row)  # type: ignore[arg-type]
    assert projected.observed_at == row.observed_at
    assert projected.valid_until == row.valid_until
    assert projected.snapshot_sha256 == row.snapshot_sha256
    assert "capabilities" not in projected.model_dump_json()
    assert projected.source == "LOCAL_OBSERVATION"
    row.valid_until += timedelta(seconds=1)
    with pytest.raises(ValueError, match="identity differs"):
        ControlPlaneAdapter._capability_snapshot(row)  # type: ignore[arg-type]
