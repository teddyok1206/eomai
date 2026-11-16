from __future__ import annotations

import pytest
from eom_web_gui.settings import SessionSettings, UpstreamSettings, WebSettings
from pydantic import ValidationError


def test_tripled_gui_login_lifetime_keeps_other_session_controls():
    before = SessionSettings()
    after = SessionSettings(ttl_seconds=5400)
    assert after.ttl_seconds == before.ttl_seconds * 3
    assert after.model_dump(exclude={"ttl_seconds"}) == before.model_dump(exclude={"ttl_seconds"})


def test_workflow_start_timeout_is_bounded_separately_from_short_requests() -> None:
    settings = UpstreamSettings()

    assert settings.request_timeout_seconds == 5.0
    assert settings.workflow_start_timeout_seconds == 150.0


@pytest.mark.parametrize("value", [29.9, 165.1])
def test_workflow_start_timeout_rejects_unsafe_bounds(value: float) -> None:
    with pytest.raises(ValidationError):
        UpstreamSettings(workflow_start_timeout_seconds=value)


def test_kakao_transport_configuration_is_optional_and_requires_https_session_boundary():
    assert WebSettings().kakao_remote_transport is None
    policy = {
        "expected_origin": "https://studio.example.invalid",
        "static_paths": ["/studio/admin/remote/vnc.html"],
    }
    for changes in ({}, {"sessions": {"cookie_secure": True}}):
        with pytest.raises(ValidationError):
            WebSettings.model_validate({"kakao_remote_transport": policy, **changes})
    configured = WebSettings.model_validate(
        {
            "server": {"allowed_hosts": ["studio.example.invalid"]},
            "sessions": {"cookie_secure": True},
            "kakao_remote_transport": policy,
        }
    )
    assert configured.kakao_remote_transport.static_paths == frozenset(policy["static_paths"])
    with pytest.raises(ValidationError):
        WebSettings.model_validate(
            configured.model_dump()
            | {"kakao_remote_transport": policy | {"static_paths": ["/private"]}}
        )
