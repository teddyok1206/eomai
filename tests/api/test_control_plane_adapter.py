from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from eom_api.services.control_plane_adapter import ControlPlaneAdapter
from eom_identifiers import content_sha256


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
