"""Operator CLI presentation, never actual credentials, Control writes or model execution."""

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from eomctl import control_plane as module
from typer.testing import CliRunner

from tests.unit.test_kakao_concept_contracts import ROOT


@pytest.mark.parametrize("timestamp,valid", [("2026-11-17T16:00:00Z", True), ("wrong-date", False)])
def test_cli_uses_public_owner_exact_pins_and_utc(timestamp, valid, monkeypatch):
    engine, publish = Mock(), Mock()
    publish.return_value.model_dump.return_value = {
        "preset_revision_id": "execpresetrev_" + "1" * 32
    }
    monkeypatch.setattr(module, "build_engine", lambda: engine)
    monkeypatch.setattr(module, "bootstrap_kakao_concepts", publish)
    monkeypatch.setattr(module.Settings, "from_environment", lambda: Mock())
    source = ROOT / "config/control-plane/kakao-concepts-v1/instructions/kakao-concepts.md"
    result = CliRunner().invoke(
        module.control_plane_app,
        [
            "bootstrap-kakao-concepts",
            "--source-commit",
            "a" * 40,
            "--actor-id",
            "fixture-operator",
            "--created-at",
            timestamp,
            "--base-preset-revision-id",
            "execpresetrev_" + "2" * 32,
            "--base-preset-sha256",
            "sha256:" + "3" * 64,
            "--instruction-path",
            str(source),
        ],
    )
    assert result.exit_code == (0 if valid else 1), result.output
    engine.dispose.assert_called_once()
    if valid:
        assert publish.call_args.kwargs["created_at"] == datetime(2026, 11, 17, 16, tzinfo=UTC)
        assert publish.call_args.kwargs["base_preset_revision_id"] == "execpresetrev_" + "2" * 32
        assert '"status": "SUCCEEDED"' in result.output
    else:
        publish.assert_not_called()
        assert "CONTROL_BOOTSTRAP_INVALID" in result.output
