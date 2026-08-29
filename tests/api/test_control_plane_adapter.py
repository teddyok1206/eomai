from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from eom_api.services.control_plane_adapter import ControlPlaneAdapter


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
