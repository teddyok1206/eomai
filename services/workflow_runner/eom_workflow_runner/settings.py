"""Validated workflow runner and human actor configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class HumanActor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,127}$")
    role: str = Field(pattern=r"^(requester|reviewer|admin)$")
    enabled: bool


class HumanActorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1)
    actors: tuple[HumanActor, ...]

    @model_validator(mode="after")
    def actor_ids_are_unique(self) -> HumanActorConfig:
        actor_ids = [actor.actor_id for actor in self.actors]
        if len(actor_ids) != len(set(actor_ids)):
            raise ValueError("human actor ids must be unique")
        return self

    def role_for(self, actor_id: str) -> str:
        matches = [actor for actor in self.actors if actor.actor_id == actor_id and actor.enabled]
        if not matches:
            raise ValueError("actor is unknown or disabled")
        return matches[0].role


class RunnerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1)
    poll_interval_seconds: int = Field(ge=1, le=60)
    command_lease_seconds: int = Field(ge=10, le=3600)
    max_commands_per_run: int = Field(ge=1, le=1000)


@dataclass(frozen=True)
class WorkflowSettings:
    definition_path: Path = REPOSITORY_ROOT / "config/workflows/generic-item-development.v1.yaml"
    actor_config_path: Path = REPOSITORY_ROOT / "config/human-actors.example.yaml"
    runner_config_path: Path = REPOSITORY_ROOT / "config/workflow-runner.example.yaml"
    prompt_root: Path = REPOSITORY_ROOT / "content/prompt-templates/placeholders"

    @classmethod
    def from_environment(cls) -> WorkflowSettings:
        return cls(
            definition_path=Path(
                os.environ.get(
                    "EOM_WORKFLOW_DEFINITION",
                    str(REPOSITORY_ROOT / "config/workflows/generic-item-development.v1.yaml"),
                )
            ),
            actor_config_path=Path(
                os.environ.get(
                    "EOM_HUMAN_ACTOR_CONFIG",
                    str(REPOSITORY_ROOT / "config/human-actors.example.yaml"),
                )
            ),
            runner_config_path=Path(
                os.environ.get(
                    "EOM_WORKFLOW_RUNNER_CONFIG",
                    str(REPOSITORY_ROOT / "config/workflow-runner.example.yaml"),
                )
            ),
            prompt_root=Path(
                os.environ.get(
                    "EOM_WORKFLOW_PROMPT_ROOT",
                    str(REPOSITORY_ROOT / "content/prompt-templates/placeholders"),
                )
            ),
        )

    def load_actors(self) -> HumanActorConfig:
        return _load_yaml_model(self.actor_config_path, HumanActorConfig)

    def load_runner(self) -> RunnerConfig:
        return _load_yaml_model(self.runner_config_path, RunnerConfig)


def _load_yaml_model[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    try:
        raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
        return model.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ValueError(f"invalid workflow configuration: {path.name}") from exc
