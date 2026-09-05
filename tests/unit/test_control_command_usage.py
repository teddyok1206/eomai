from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from eom_identifiers import content_sha256
from eom_orchestrator.control_commands import _terminalize_record
from eom_workflow import CodexControlCommandResultV2, CodexUsageObservation


def test_successful_observe_terminalizes_with_exact_usage_snapshot() -> None:
    observed_at = datetime(2026, 9, 5, 1, 2, tzinfo=UTC)
    usage_document: dict[str, object] = {
        "schema_version": "codex-usage-observation/1.0",
        "command_id": "codexcmd_" + "1" * 32,
        "binding_id": "authbinding_" + "2" * 32,
        "slot_key": "slot01",
        "account_type": "chatgpt",
        "plan_type": "plus",
        "windows": [
            {
                "limit_id": "codex",
                "limit_name": None,
                "window_kind": "SECONDARY",
                "used_percent": 27,
                "window_duration_minutes": 10080,
                "resets_at": (observed_at + timedelta(days=4)).isoformat().replace("+00:00", "Z"),
            }
        ],
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "observation_sha256": "sha256:" + "0" * 64,
    }
    usage_document["observation_sha256"] = content_sha256(
        {key: value for key, value in usage_document.items() if key != "observation_sha256"}
    )
    usage = CodexUsageObservation.model_validate(usage_document)
    record = SimpleNamespace(
        command_id=usage.command_id,
        command_type="OBSERVE",
        binding_id=usage.binding_id,
        state="PROCESSING",
        lease_owner="runner",
        lease_expires_at=observed_at + timedelta(minutes=1),
        result_resource_version=None,
        result_document=None,
        error_code=None,
        processed_at=None,
    )

    _terminalize_record(
        record,
        outcome="SUCCEEDED",
        result_resource_version=2,
        binding_state="READY",
        reason_code=None,
        processed_at=observed_at + timedelta(seconds=1),
        usage_observation=usage,
    )

    result = CodexControlCommandResultV2.model_validate(record.result_document)
    assert result.usage_observation == usage
    assert result.result_sha256 != "sha256:" + "0" * 64
