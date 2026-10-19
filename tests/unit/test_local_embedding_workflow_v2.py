"""Pure mixed-definition compilation; no runner, database or native execution."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow import schemas
from eom_workflow.admission import WORKFLOW_ADMISSION_BY_IDENTITY, workflow_admission
from eom_workflow.compiler import (
    WorkflowDefinitionError,
    compile_definition,
    compile_definition_data,
)
from eom_workflow.definition_execution_protocol import (
    DefinitionExecutionProtocolError,
    definition_execution_protocol,
)
from eom_workflow.local_embedding_workflow import (
    LocalEmbeddingStep,
    LocalEmbeddingWorkflowContractError,
    LocalEmbeddingWorkflowDefinition,
    parse_local_embedding_workflow_definition,
)
from eom_workflow.local_embedding_workflow_v2 import (
    LocalEmbeddingWorkflowDefinitionV2,
    load_local_embedding_definition_v2_schema,
    parse_local_embedding_workflow_definition_v2,
)
from eom_workflow.models import AgentStep, TerminalStep
from eom_workflow.schemas import LocalEmbeddingAdmissionContractError
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/workflows/local-embedding-index.v2.yaml"
EXPECTED_COMPILED = "sha256:4e2eb98850068405604a854eea8cf323e85bc7e764cf8f5009d59cb88a10e173"
SCHEMA_RAW_SHA = "sha256:64fe5bbf63c7c2ee4e3b7994b2eb4293610bd82dee569a809def0ceb4910cb67"


def _definition() -> dict[str, Any]:
    value = yaml.safe_load(CONFIG.read_text())
    assert isinstance(value, dict)
    return value


def test_schema_first_resource_is_exact_independent_and_hash_pinned() -> None:
    relative = "workflow-definition-v1_4.schema.json"
    raw = (ROOT / "schemas/workflow" / relative).read_bytes()
    assert raw == (ROOT / "packages/workflow/eom_workflow/resources" / relative).read_bytes()
    assert 0 < len(raw) <= 64 * 1024 and sha256_bytes(raw) == SCHEMA_RAW_SHA
    expected_id = "https://eom.local/schemas/workflow/" + relative
    expected_resource = (
        "definition-v2",
        relative,
        expected_id,
        SCHEMA_RAW_SHA,
    )
    assert expected_resource == schemas.WORKFLOW_DEFINITION_V1_4_SCHEMA_RESOURCE
    schema = load_local_embedding_definition_v2_schema()
    assert schema == json.loads(raw)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_definition())
    schema["properties"]["schema_version"]["const"] = "forged"
    assert load_local_embedding_definition_v2_schema() == json.loads(raw)


def test_real_definition2_compiles_without_codex_and_staged_replay_preserves_hash() -> None:
    with patch("eom_workflow.compiler._validate_semantics") as agent_semantics:
        compiled = compile_definition(CONFIG, set())
    agent_semantics.assert_not_called()
    assert type(compiled.definition) is LocalEmbeddingWorkflowDefinitionV2
    assert not isinstance(compiled.definition, LocalEmbeddingWorkflowDefinition)
    assert tuple(compiled.steps_by_key) == ("encode_batch", "complete")
    assert type(compiled.steps_by_key["encode_batch"]) is LocalEmbeddingStep
    assert type(compiled.steps_by_key["complete"]) is TerminalStep
    assert not any(isinstance(step, AgentStep) for step in compiled.definition.steps)
    assert compiled.automatic_review_rework is None
    assert compiled.definition.steps[0].result_schema == "incremental-embedding-result@1.0"
    assert definition_execution_protocol(compiled.definition) == "local-embedding/1.0"
    assert compiled.canonical_bytes == canonical_json_bytes(_definition())
    assert compiled.sha256 == EXPECTED_COMPILED
    staged = json.loads(compiled.canonical_bytes)
    replay = compile_definition_data(staged, "persisted-definition-snapshot", set())
    assert replay.canonical_bytes == compiled.canonical_bytes
    assert replay.sha256 == EXPECTED_COMPILED
    assert workflow_admission("local-embedding-index", "2.0.0").role_protocol_version == (
        "local-embedding/1.0"
    )
    assert workflow_admission("local-embedding-index", "2.0.1") is None


def test_old_definition_schema_yaml_canonical_hash_and_admissions_are_unchanged() -> None:
    relative = "workflow-definition-v1_1.schema.json"
    raw = (ROOT / "schemas/workflow" / relative).read_bytes()
    assert raw == (ROOT / "packages/workflow/eom_workflow/resources" / relative).read_bytes()
    assert sha256_bytes(raw) == (
        "sha256:c3321ba4c337c40b5e2d2c1b29c4c3f8bf66d443e14ab4d4799b5b34c40608d1"
    )
    path = ROOT / "config/workflows/local-embedding-index.v1.yaml"
    assert sha256_bytes(path.read_bytes()) == (
        "sha256:12670ab448b1013fe8d54852bef2a22d22515c0415aaaeba023cdd9519b40c2e"
    )
    old = compile_definition(path, set())
    assert type(old.definition) is LocalEmbeddingWorkflowDefinition
    assert old.sha256 == ("sha256:5098dcfd92996bf5136b776fe7c0c3786d5f1a38fa5ce581109f646dc3b9046d")
    assert definition_execution_protocol(old.definition) == "local-embedding/1.0"
    old_admissions = [
        [row.definition_key, row.definition_version, row.role_protocol_version]
        for key, row in WORKFLOW_ADMISSION_BY_IDENTITY.items()
        if key != ("local-embedding-index", "2.0.0")
    ]
    assert content_sha256(old_admissions) == (
        "sha256:31f86f8fa2c3bb5626df9d9d7add22b7309b6e84ebbb10716bdf28b6b33eb3e7"
    )
    with pytest.raises(LocalEmbeddingWorkflowContractError):
        parse_local_embedding_workflow_definition(_definition())
    with pytest.raises(LocalEmbeddingAdmissionContractError):
        parse_local_embedding_workflow_definition_v2(old.as_dict())


@pytest.mark.parametrize(
    "change",
    ["extra", "key", "version", "schema", "worker", "operation", "result", "reverse", "third"],
)
def test_definition2_has_no_purpose_repair_or_generic_executor_fallback(change: str) -> None:
    value = _definition()
    if change == "extra":
        value["actor_context"] = {"role": "ADMIN"}
    elif change in {"key", "version", "schema"}:
        key, bad = {
            "key": ("definition_key", "local-embedding-private-chat-query"),
            "version": ("definition_version", "1.0.0"),
            "schema": ("schema_version", "1.3"),
        }[change]
        value[key] = bad
    elif change == "worker":
        value["steps"][0]["worker_role"] = "authoring"
    elif change == "operation":
        value["steps"][0]["operation"] = "RUN_COMMAND"
    elif change == "result":
        value["steps"][0]["result_schema"] = "incremental-embedding-result@2.0"
    elif change == "reverse":
        value["steps"].reverse()
    else:
        value["steps"].append(deepcopy(value["steps"][1]))
    with pytest.raises((LocalEmbeddingAdmissionContractError, ValueError)):
        parse_local_embedding_workflow_definition_v2(value)
    with pytest.raises(WorkflowDefinitionError):
        compile_definition_data(value, "forged-definition2", set())


@pytest.mark.parametrize("bad", [False, True, 0.0, 1.0, "0", -1, 1])
def test_definition2_rejects_non_exact_integer_limits(bad: object) -> None:
    value = _definition()
    value["limits"]["max_rework_cycles"] = bad
    with pytest.raises((LocalEmbeddingAdmissionContractError, ValueError)):
        parse_local_embedding_workflow_definition_v2(value)


@pytest.mark.parametrize("change", ["root_extra", "step_extra", "terminal_extra", "limits_bool"])
def test_protocol_revalidates_actual_frozen_values_without_erasing_extra_fields(
    change: str,
) -> None:
    parsed = parse_local_embedding_workflow_definition_v2(_definition())
    if change == "root_extra":
        forged = parsed.model_copy(update={"command": "not-allowed"})
    elif change == "step_extra":
        first = parsed.steps[0].model_copy(update={"worker_role": "authoring"})
        forged = parsed.model_copy(update={"steps": (first, parsed.steps[1])})
    elif change == "terminal_extra":
        last = parsed.steps[1].model_copy(update={"command": "not-allowed"})
        forged = parsed.model_copy(update={"steps": (parsed.steps[0], last)})
    else:
        forged = parsed.model_copy(
            update={"limits": parsed.limits.model_copy(update={"max_step_attempts": True})}
        )
    with pytest.raises((LocalEmbeddingAdmissionContractError, ValueError)):
        parse_local_embedding_workflow_definition_v2(forged)
    with pytest.raises(DefinitionExecutionProtocolError):
        definition_execution_protocol(forged)


def test_installed_schema_wrong_hash_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    original = schemas.WORKFLOW_DEFINITION_V1_4_SCHEMA_RESOURCE
    schemas._local_embedding_admission_schema.cache_clear()
    try:
        with monkeypatch.context() as context:
            context.setattr(
                schemas,
                "WORKFLOW_DEFINITION_V1_4_SCHEMA_RESOURCE",
                (*original[:3], "sha256:" + "0" * 64),
            )
            with pytest.raises(LocalEmbeddingAdmissionContractError, match="SCHEMA_UNAVAILABLE"):
                load_local_embedding_definition_v2_schema()
    finally:
        schemas._local_embedding_admission_schema.cache_clear()
