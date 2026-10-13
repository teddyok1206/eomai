"""Fixed QUERY compilation/protocol only; no admission, DB or native execution."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.admission import workflow_admission, workflow_definition_is_admitted
from eom_workflow.compiler import WorkflowDefinitionError, compile_definition_data
from eom_workflow.definition_execution_protocol import (
    DefinitionExecutionProtocolError,
    definition_execution_protocol,
)
from eom_workflow.reference_query_workflow import (
    REFERENCE_QUERY_EXECUTION_PROTOCOL,
    REFERENCE_QUERY_WORKFLOW_KEY,
    ReferenceQueryStep,
    ReferenceQueryWorkflowDefinition,
    parse_reference_query_workflow_definition,
)
from eom_workflow.schemas import RESULT_SCHEMA_FILES

from tests.unit.test_reference_query_workflow_contracts import definition_body


def test_fixed_query_compiles_without_a_codex_role_and_replays_exactly() -> None:
    body = definition_body()
    compiled = compile_definition_data(body, "synthetic-query-definition", set())
    assert isinstance(compiled.definition, ReferenceQueryWorkflowDefinition)
    assert tuple(compiled.steps_by_key) == ("encode_reference_query", "complete")
    assert isinstance(compiled.steps_by_key["encode_reference_query"], ReferenceQueryStep)
    assert compiled.automatic_review_rework is None
    assert compiled.as_dict() == body
    assert compiled.canonical_bytes == canonical_json_bytes(body)
    assert compiled.sha256 == sha256_bytes(compiled.canonical_bytes)
    assert definition_execution_protocol(compiled.definition) == REFERENCE_QUERY_EXECUTION_PROTOCOL
    reversed_keys = dict(reversed(tuple(body.items())))
    replay = compile_definition_data(reversed_keys, "synthetic-query-replay", {"support"})
    assert replay.canonical_bytes == compiled.canonical_bytes and replay.sha256 == compiled.sha256
    assert not workflow_definition_is_admitted(REFERENCE_QUERY_WORKFLOW_KEY, "1.0.0")
    assert workflow_admission(REFERENCE_QUERY_WORKFLOW_KEY, "1.0.0") is None
    assert "embedding-reference-query-result@1.0" not in RESULT_SCHEMA_FILES


@pytest.mark.parametrize(
    "change",
    (
        "document_schema",
        "role_schema",
        "document_key",
        "document_result",
        "agent",
        "attempt_bool",
        "attempt_two",
        "rework",
        "order",
        "extra_step",
        "extra_authority",
    ),
)
def test_query_compile_never_infers_another_purpose_or_repairs_input(change: str) -> None:
    body = definition_body()
    if change == "document_schema":
        body["schema_version"] = "1.1"
    elif change == "role_schema":
        body["schema_version"] = "1.0"
    elif change == "document_key":
        body["definition_key"] = "local-embedding-index"
    elif change == "document_result":
        body["steps"][0]["result_schema"] = "incremental-embedding-result@1.0"
    elif change == "agent":
        body["steps"][0]["worker_role"] = "support"
    elif change == "attempt_bool":
        body["limits"]["max_step_attempts"] = True
    elif change == "attempt_two":
        body["limits"]["max_step_attempts"] = 2
    elif change == "rework":
        body["limits"]["max_rework_cycles"] = 1
    elif change == "order":
        body["steps"].reverse()
    elif change == "extra_step":
        body["steps"].append(deepcopy(body["steps"][1]))
    else:
        body["authority"] = "ADMIN"
    with pytest.raises(WorkflowDefinitionError, match="schema validation"):
        compile_definition_data(body, "synthetic-corrupt-query", {"support"})


@pytest.mark.parametrize("field", ("shell", "command", "module", "CALLABLE", "sql", "template"))
def test_query_retains_the_existing_recursive_unsafe_key_guard(field: str) -> None:
    body = definition_body()
    body["steps"][0][field] = "synthetic-unsafe-value"
    with pytest.raises(WorkflowDefinitionError, match="unsafe workflow field"):
        compile_definition_data(body, "synthetic-unsafe-query", set())


@pytest.mark.parametrize("change", ("authority", "boolean", "operation", "nested_extra"))
def test_protocol_revalidates_raw_copied_values_without_lossy_dump(change: str) -> None:
    definition = parse_reference_query_workflow_definition(definition_body())
    update: dict[str, Any]
    if change == "authority":
        update = {"authority": "ADMIN"}
    elif change == "boolean":
        update = {"limits": definition.limits.model_copy(update={"max_step_attempts": True})}
    elif change == "operation":
        update = {
            "steps": (
                definition.steps[0].model_copy(update={"operation": "BUILD_LOCAL_EMBEDDINGS"}),
                definition.steps[1],
            )
        }
    else:
        update = {
            "steps": (
                definition.steps[0].model_copy(update={"worker_role": "support"}),
                definition.steps[1],
            )
        }
    with pytest.raises(DefinitionExecutionProtocolError, match="reference query"):
        definition_execution_protocol(definition.model_copy(update=update))


def test_query_protocol_rejects_unvalidated_constructed_and_wrong_typed_values() -> None:
    definition = ReferenceQueryWorkflowDefinition.model_construct(
        **(definition_body() | {"schema_version": "1.1"})
    )
    with pytest.raises(DefinitionExecutionProtocolError):
        definition_execution_protocol(definition)
