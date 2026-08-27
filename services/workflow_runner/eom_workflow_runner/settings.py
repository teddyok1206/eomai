"""Validated workflow runner and human actor configuration."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

DEFAULT_WORKFLOW_DEFINITION = Path("/etc/eom/workflows/generic-item-development.yaml")
DEFAULT_HUMAN_ACTOR_CONFIG = Path("/etc/eom/human-actors.yaml")
DEFAULT_WORKFLOW_RUNNER_CONFIG = Path("/etc/eom/workflow-runner.yaml")
DEFAULT_WORKFLOW_PROMPT_ROOT = Path("/etc/eom/workflow-prompts")
MAX_WORKFLOW_CONFIGURATION_BYTES = 1_048_576
MAX_WORKFLOW_COMMAND_LEASE_SECONDS = 14_400


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
    command_lease_seconds: int = Field(ge=10, le=MAX_WORKFLOW_COMMAND_LEASE_SECONDS)
    max_commands_per_run: int = Field(ge=1, le=1000)


@dataclass(frozen=True)
class WorkflowSettings:
    definition_path: Path = DEFAULT_WORKFLOW_DEFINITION
    actor_config_path: Path = DEFAULT_HUMAN_ACTOR_CONFIG
    runner_config_path: Path = DEFAULT_WORKFLOW_RUNNER_CONFIG
    prompt_root: Path = DEFAULT_WORKFLOW_PROMPT_ROOT

    def __post_init__(self) -> None:
        configured = {
            "EOM_WORKFLOW_DEFINITION": self.definition_path,
            "EOM_HUMAN_ACTOR_CONFIG": self.actor_config_path,
            "EOM_WORKFLOW_RUNNER_CONFIG": self.runner_config_path,
            "EOM_WORKFLOW_PROMPT_ROOT": self.prompt_root,
        }
        for variable, path in configured.items():
            if not path.is_absolute():
                raise ValueError(f"{variable} must be an absolute path")

    @classmethod
    def from_environment(cls) -> WorkflowSettings:
        return cls(
            definition_path=Path(
                os.environ.get(
                    "EOM_WORKFLOW_DEFINITION",
                    str(DEFAULT_WORKFLOW_DEFINITION),
                )
            ),
            actor_config_path=Path(
                os.environ.get(
                    "EOM_HUMAN_ACTOR_CONFIG",
                    str(DEFAULT_HUMAN_ACTOR_CONFIG),
                )
            ),
            runner_config_path=Path(
                os.environ.get(
                    "EOM_WORKFLOW_RUNNER_CONFIG",
                    str(DEFAULT_WORKFLOW_RUNNER_CONFIG),
                )
            ),
            prompt_root=Path(
                os.environ.get(
                    "EOM_WORKFLOW_PROMPT_ROOT",
                    str(DEFAULT_WORKFLOW_PROMPT_ROOT),
                )
            ),
        )

    def load_actors(self) -> HumanActorConfig:
        return _load_yaml_model(self.actor_config_path, HumanActorConfig)

    def load_runner(self) -> RunnerConfig:
        return _load_yaml_model(self.runner_config_path, RunnerConfig)


def load_workflow_yaml(path: Path) -> object:
    """Load bounded operator configuration without following the final symlink."""

    try:
        if not path.is_absolute():
            raise OSError("workflow configuration path is not absolute")
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or path.resolve(strict=True) != path.absolute()
            or not os.access(path, os.R_OK)
        ):
            raise OSError("workflow configuration file is unsafe")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, encoding="utf-8") as source:
            content = source.read(MAX_WORKFLOW_CONFIGURATION_BYTES + 1)
        if len(content) > MAX_WORKFLOW_CONFIGURATION_BYTES:
            raise OSError("workflow configuration file is too large")
        return yaml.safe_load(content)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"invalid workflow configuration: {path.name}") from exc


def _load_yaml_model[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    try:
        return model.model_validate(load_workflow_yaml(path))
    except ValidationError as exc:
        raise ValueError(f"invalid workflow configuration: {path.name}") from exc
