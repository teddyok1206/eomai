from __future__ import annotations

import os
from pathlib import Path

import pytest
from eom_workflow_runner.settings import (
    DEFAULT_HUMAN_ACTOR_CONFIG,
    DEFAULT_WORKFLOW_DEFINITION,
    DEFAULT_WORKFLOW_PROMPT_ROOT,
    DEFAULT_WORKFLOW_RUNNER_CONFIG,
    WorkflowSettings,
)


def test_workflow_settings_use_operator_owned_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in (
        "EOM_WORKFLOW_DEFINITION",
        "EOM_HUMAN_ACTOR_CONFIG",
        "EOM_WORKFLOW_RUNNER_CONFIG",
        "EOM_WORKFLOW_PROMPT_ROOT",
    ):
        monkeypatch.delenv(variable, raising=False)

    settings = WorkflowSettings.from_environment()

    assert settings.definition_path == DEFAULT_WORKFLOW_DEFINITION
    assert settings.actor_config_path == DEFAULT_HUMAN_ACTOR_CONFIG
    assert settings.runner_config_path == DEFAULT_WORKFLOW_RUNNER_CONFIG
    assert settings.prompt_root == DEFAULT_WORKFLOW_PROMPT_ROOT
    assert Path("/etc/eom/workflows/generic-item-development.yaml") == (DEFAULT_WORKFLOW_DEFINITION)
    assert Path("/etc/eom/human-actors.yaml") == DEFAULT_HUMAN_ACTOR_CONFIG
    assert Path("/etc/eom/workflow-runner.yaml") == DEFAULT_WORKFLOW_RUNNER_CONFIG
    assert Path("/etc/eom/workflow-prompts") == DEFAULT_WORKFLOW_PROMPT_ROOT


@pytest.mark.parametrize(
    ("variable", "value"),
    (
        ("EOM_WORKFLOW_DEFINITION", "definition.yaml"),
        ("EOM_HUMAN_ACTOR_CONFIG", "actors.yaml"),
        ("EOM_WORKFLOW_RUNNER_CONFIG", "runner.yaml"),
        ("EOM_WORKFLOW_PROMPT_ROOT", "prompts"),
    ),
)
def test_workflow_settings_reject_relative_overrides(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValueError, match=rf"{variable} must be an absolute path"):
        WorkflowSettings.from_environment()


def test_operator_yaml_is_validated_without_following_symlinks(tmp_path: Path) -> None:
    actors = tmp_path / "actors.yaml"
    actors.write_text(
        "version: 1\nactors:\n  - actor_id: reviewer_01\n    role: reviewer\n    enabled: true\n",
        encoding="utf-8",
    )
    linked = tmp_path / "actors-linked.yaml"
    linked.symlink_to(actors)

    settings = WorkflowSettings(actor_config_path=actors)
    assert settings.load_actors().role_for("reviewer_01") == "reviewer"

    with pytest.raises(ValueError, match="invalid workflow configuration"):
        WorkflowSettings(actor_config_path=linked).load_actors()


def test_operator_yaml_size_is_bounded(tmp_path: Path) -> None:
    actors = tmp_path / "actors.yaml"
    descriptor = os.open(actors, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as target:
        target.write(b" " * 1_048_577)

    with pytest.raises(ValueError, match="invalid workflow configuration"):
        WorkflowSettings(actor_config_path=actors).load_actors()


def test_runner_configuration_installer_has_narrow_operator_scope() -> None:
    source = Path("scripts/workflow/install_runner_configuration.sh").read_text(encoding="utf-8")

    assert 'WORKFLOW_ROOT="${CONFIG_ROOT}/workflows"' in source
    assert 'PROMPT_ROOT="${CONFIG_ROOT}/workflow-prompts"' in source
    assert 'install -d -o root -g eom -m 0750 "${WORKFLOW_ROOT}"' in source
    assert 'install -o root -g eom -m 0640 "${source}" "${target}"' in source
    assert 'install -d -o root -g eom -m 0750 "${CONFIG_ROOT}"' not in source
    for forbidden in ("pip install", "conda install", "npm install", "systemctl restart"):
        assert forbidden not in source
