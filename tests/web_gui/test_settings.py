from __future__ import annotations

import pytest
from eom_web_gui.settings import UpstreamSettings
from pydantic import ValidationError


def test_workflow_start_timeout_is_bounded_separately_from_short_requests() -> None:
    settings = UpstreamSettings()

    assert settings.request_timeout_seconds == 5.0
    assert settings.workflow_start_timeout_seconds == 150.0


@pytest.mark.parametrize("value", [29.9, 165.1])
def test_workflow_start_timeout_rejects_unsafe_bounds(value: float) -> None:
    with pytest.raises(ValidationError):
        UpstreamSettings(workflow_start_timeout_seconds=value)
