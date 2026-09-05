from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.worker_registry import WorkerSlot
from eom_orchestrator.worker_usage import _read_handoff, _validate_observation
from eom_orchestrator.worker_usage_exec import _normalized_windows, _observation_document
from eom_workflow import CodexUsageObservation

NOW = datetime(2026, 9, 5, 1, 2, 3, tzinfo=UTC)
COMMAND_ID = "codexcmd_" + "1" * 32
BINDING_ID = "authbinding_" + "2" * 32


def _slot() -> WorkerSlot:
    return WorkerSlot.model_validate(
        {
            "slot_id": "01",
            "linux_user": "eom-cdx-01",
            "role": "authoring",
            "enabled": True,
        }
    )


def _rate_limits() -> dict[str, object]:
    return {
        "rateLimits": {},
        "rateLimitsByLimitId": {
            "codex": {
                "limitId": "codex",
                "limitName": "Codex",
                "planType": "plus",
                "primary": {
                    "usedPercent": 12,
                    "windowDurationMins": 300,
                    "resetsAt": 1_788_230_400,
                },
                "secondary": {
                    "usedPercent": 34,
                    "windowDurationMins": 10080,
                    "resetsAt": 1_788_748_800,
                },
            }
        },
    }


def test_usage_projection_keeps_only_sanitized_sorted_windows() -> None:
    document = _observation_document(
        command_id=COMMAND_ID,
        binding_id=BINDING_ID,
        slot_id="01",
        account_result={
            "account": {
                "type": "chatgpt",
                "planType": "plus",
                "email": "must-not-survive@example.invalid",
            },
            "requiresOpenaiAuth": True,
        },
        usage_result=_rate_limits(),
    )

    observation = CodexUsageObservation.model_validate(document)
    assert observation.observation_sha256 == content_sha256(
        {
            key: value
            for key, value in observation.model_dump(mode="json").items()
            if key != "observation_sha256"
        }
    )
    assert [(window.window_kind, window.used_percent) for window in observation.windows] == [
        ("PRIMARY", 12),
        ("SECONDARY", 34),
    ]
    serialized = json.dumps(document)
    assert "email" not in serialized
    assert "credit" not in serialized.casefold()
    assert "token" not in serialized.casefold()

    drifted = document | {"observation_sha256": "sha256:" + "f" * 64}
    with pytest.raises(ControlPlaneError, match="identity differs"):
        _validate_observation(
            drifted,
            slot=_slot(),
            command_id=COMMAND_ID,
            binding_id=BINDING_ID,
        )


def test_usage_projection_rejects_missing_windows_and_non_chatgpt_auth() -> None:
    with pytest.raises(ValueError, match="no usage windows"):
        _normalized_windows({"rateLimits": {}})
    with pytest.raises(PermissionError, match="ChatGPT"):
        _observation_document(
            command_id=COMMAND_ID,
            binding_id=BINDING_ID,
            slot_id="01",
            account_result={"account": {"type": "apiKey"}},
            usage_result=_rate_limits(),
        )


def test_handoff_is_same_descriptor_bounded_and_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o770)
    handoff = tmp_path / f"{COMMAND_ID}.json"
    handoff.write_text('{"safe":true}', encoding="utf-8")
    handoff.chmod(0o640)
    monkeypatch.setattr(
        "eom_orchestrator.worker_usage.pwd.getpwnam",
        lambda _user: SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid()),
    )

    assert _read_handoff(slot=_slot(), path=handoff, missing_ok=False) == {"safe": True}
    assert not handoff.exists()
