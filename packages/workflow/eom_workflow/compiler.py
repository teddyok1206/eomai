"""Safe compiler for declarative, domain-neutral workflow definitions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from eom_identifiers import canonical_json_bytes, sha256_bytes
from pydantic import ValidationError

from eom_workflow.models import (
    AgentStep,
    DecisionStep,
    HumanGateStep,
    TerminalStep,
    WorkflowDefinition,
)
from eom_workflow.schemas import (
    RESULT_SCHEMA_FILES,
    ROLE_RESULT_SCHEMAS,
    load_definition_schema,
    validate_schema_message,
)

UNSAFE_KEYS = frozenset(
    {
        "eval",
        "exec",
        "shell",
        "command",
        "expression",
        "import",
        "sql",
        "module",
        "function",
        "callable",
        "template",
    }
)


class WorkflowDefinitionError(ValueError):
    pass


@dataclass(frozen=True)
class CompiledWorkflowDefinition:
    definition: WorkflowDefinition
    canonical_bytes: bytes
    sha256: str
    source_path: str

    def as_dict(self) -> dict[str, Any]:
        value: object = json.loads(self.canonical_bytes)
        if not isinstance(value, dict):
            raise WorkflowDefinitionError("compiled definition is not an object")
        return value

    @property
    def steps_by_key(self) -> dict[str, AgentStep | DecisionStep | HumanGateStep | TerminalStep]:
        return {step.key: step for step in self.definition.steps}


def compile_definition(path: Path, available_worker_roles: set[str]) -> CompiledWorkflowDefinition:
    try:
        raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise WorkflowDefinitionError("unable to read workflow definition") from exc
    return compile_definition_data(raw, str(path), available_worker_roles)


def compile_definition_data(
    raw: object, source_path: str, available_worker_roles: set[str]
) -> CompiledWorkflowDefinition:
    if not isinstance(raw, dict):
        raise WorkflowDefinitionError("workflow definition must be an object")
    _reject_unsafe_keys(raw)
    try:
        validate_schema_message(load_definition_schema(), raw, "workflow-definition")
        definition = WorkflowDefinition.model_validate(raw)
    except (ValidationError, ValueError) as exc:
        raise WorkflowDefinitionError("workflow definition failed schema validation") from exc
    _validate_semantics(definition, available_worker_roles)
    canonical = canonical_json_bytes(definition)
    return CompiledWorkflowDefinition(
        definition=definition,
        canonical_bytes=canonical,
        sha256=sha256_bytes(canonical),
        source_path=source_path,
    )


def _validate_semantics(definition: WorkflowDefinition, available_worker_roles: set[str]) -> None:
    keys = [step.key for step in definition.steps]
    if len(keys) != len(set(keys)):
        raise WorkflowDefinitionError("workflow step keys must be unique")
    steps = {step.key: step for step in definition.steps}
    if definition.start_step not in steps:
        raise WorkflowDefinitionError("workflow start step does not exist")
    terminals = [step for step in definition.steps if isinstance(step, TerminalStep)]
    if not terminals:
        raise WorkflowDefinitionError("workflow definition requires a terminal step")

    forward: dict[str, tuple[str, ...]] = {}
    for step in definition.steps:
        targets: tuple[str, ...]
        if isinstance(step, AgentStep):
            if step.worker_role not in available_worker_roles:
                raise WorkflowDefinitionError(f"worker role is unavailable: {step.worker_role}")
            expected_schema = ROLE_RESULT_SCHEMAS[step.worker_role]
            if (
                step.result_schema != expected_schema
                or step.result_schema not in RESULT_SCHEMA_FILES
            ):
                raise WorkflowDefinitionError(
                    f"result schema does not match worker role: {step.key}"
                )
            targets = (step.on_success,)
        elif isinstance(step, DecisionStep):
            targets = tuple(step.branches.values())
        elif isinstance(step, HumanGateStep):
            targets = (step.on_approve,)
            for target in step.allowed_rework_targets:
                if target not in steps or not isinstance(steps[target], AgentStep):
                    raise WorkflowDefinitionError(f"invalid human rework target: {target}")
        else:
            targets = ()
        missing = [target for target in targets if target not in steps]
        if missing:
            raise WorkflowDefinitionError(
                f"step {step.key} has missing transition target: {missing[0]}"
            )
        forward[step.key] = targets

    reachable: set[str] = set()
    pending = [definition.start_step]
    while pending:
        key = pending.pop()
        if key in reachable:
            continue
        reachable.add(key)
        pending.extend(forward[key])
    unreachable = sorted(set(keys) - reachable)
    if unreachable:
        raise WorkflowDefinitionError(f"unreachable workflow step: {unreachable[0]}")


def evaluate_decision(step: DecisionStep, initial_request: dict[str, Any]) -> str:
    if step.operator not in {"input_equals", "input_in"}:
        raise WorkflowDefinitionError(f"operator requires runtime context: {step.operator}")
    value = resolve_json_pointer(initial_request, step.field)
    branch = str(value)
    try:
        return step.branches[branch]
    except KeyError as exc:
        raise WorkflowDefinitionError(
            f"decision {step.key} has no branch for sanitized input value"
        ) from exc


def resolve_json_pointer(document: object, pointer: str) -> object:
    if not pointer.startswith("/"):
        raise WorkflowDefinitionError("JSON Pointer must start with slash")
    current = document
    for encoded in pointer[1:].split("/"):
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        else:
            raise WorkflowDefinitionError("JSON Pointer does not resolve")
    return current


def _reject_unsafe_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise WorkflowDefinitionError("workflow definition keys must be strings")
            if key.lower() in UNSAFE_KEYS:
                raise WorkflowDefinitionError(f"unsafe workflow field is forbidden: {key}")
            _reject_unsafe_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_unsafe_keys(item)
