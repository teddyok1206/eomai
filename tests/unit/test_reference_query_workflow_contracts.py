"""Fixed definition/source resource tests; no release, admission or native activation."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow import (
    REFERENCE_QUERY_EXECUTION_SCHEMA_RESOURCE,
    REFERENCE_QUERY_WORKFLOW_KEY,
    ReferenceQueryContractError,
    load_reference_query_execution_schema,
    parse_reference_query_workflow_definition,
    workflow_definition_is_admitted,
)
from eom_workflow import schemas as schema_owner
from eom_workflow.compiler import compile_definition_data
from eom_workflow.schemas import (
    LOCAL_EMBEDDING_RECEIPT_SCHEMA_RESOURCES,
    LOCAL_EMBEDDING_SCHEMA_RESOURCES,
    load_local_embedding_admission_schema,
    load_local_embedding_receipt_schema,
    reference_query_execution_schema_registry,
)
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def definition_body() -> dict[str, Any]:
    return {
        "schema_version": "1.2",
        "definition_key": "local-embedding-reference-query",
        "definition_version": "1.0.0",
        "start_step": "encode_reference_query",
        "limits": {"max_rework_cycles": 0, "max_step_attempts": 1},
        "steps": [
            {
                "key": "encode_reference_query",
                "type": "application",
                "operation": "BUILD_REFERENCE_QUERY_EMBEDDINGS",
                "result_schema": "embedding-reference-query-result@1.0",
                "on_success": "complete",
            },
            {"key": "complete", "type": "terminal", "terminal_status": "COMPLETED"},
        ],
    }


def test_exact_closed_schema_mirror_hash_and_existing_value_refs() -> None:
    name, schema_id, expected = REFERENCE_QUERY_EXECUTION_SCHEMA_RESOURCE
    raw = (ROOT / "schemas/workflow" / name).read_bytes()
    assert raw == (ROOT / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert (
        sha256_bytes(raw)
        == expected
        == ("sha256:68e741506fec708956096aa5af6199e7c03821219385775cf9623aea88246c9b")
    )
    schema = load_reference_query_execution_schema()
    assert schema["$id"] == schema_id
    assert set(schema["$defs"]) == {
        "definition",
        "request",
        "policy",
        "launch",
        "receipt",
        "step-output",
    }
    Draft202012Validator.check_schema(schema)
    for value in schema["$defs"].values():
        assert value["additionalProperties"] is False
        assert set(value["properties"]) == set(value["required"])
    assert schema["$defs"]["policy"]["properties"]["continuation_mode"] == {
        "const": "OPERATOR_REQUEST_ONLY"
    }


def test_definition_round_trip_is_frozen_and_compilable_but_not_admission_offered() -> None:
    definition = parse_reference_query_workflow_definition(definition_body())
    assert definition.schema_version == "1.2"
    assert len(definition.steps) == 2
    assert definition.limits.max_step_attempts == 1
    assert parse_reference_query_workflow_definition(definition) == definition
    assert canonical_json_bytes(definition.model_dump(mode="json")) == canonical_json_bytes(
        parse_reference_query_workflow_definition(
            dict(reversed(tuple(definition_body().items())))
        ).model_dump(mode="json")
    )
    assert not workflow_definition_is_admitted(REFERENCE_QUERY_WORKFLOW_KEY, "1.0.0")
    compiled = compile_definition_data(definition_body(), "synthetic-unoffered-query", set())
    assert compiled.definition == definition


@pytest.mark.parametrize(
    "change",
    [
        "version",
        "key",
        "attempt",
        "bool",
        "rework",
        "operation",
        "role",
        "order",
        "terminal",
        "path",
    ],
)
def test_definition_cannot_change_purpose_role_limits_or_execution(change: str) -> None:
    body = definition_body()
    if change == "version":
        body["schema_version"] = "1.1"
    elif change == "key":
        body["definition_key"] = "local-embedding-index"
    elif change == "attempt":
        body["limits"]["max_step_attempts"] = 2
    elif change == "bool":
        body["limits"]["max_rework_cycles"] = False
    elif change == "rework":
        body["limits"]["max_rework_cycles"] = 1
    elif change == "operation":
        body["steps"][0]["operation"] = "BUILD_LOCAL_EMBEDDINGS"
    elif change == "role":
        body["steps"][0]["worker_role"] = "authoring"
    elif change == "order":
        body["steps"].reverse()
    elif change == "terminal":
        body["steps"][1]["terminal_status"] = "FAILED"
    else:
        body["source_path"] = "/mnt/nas"
    with pytest.raises(ReferenceQueryContractError, match="CONTRACT_INVALID"):
        parse_reference_query_workflow_definition(body)


def test_raw_nested_copy_and_public_schema_mutation_are_not_repaired() -> None:
    definition = parse_reference_query_workflow_definition(definition_body())
    for copied in (
        definition.model_copy(update={"authority": "ADMIN"}),
        definition.model_copy(
            update={"limits": definition.limits.model_copy(update={"max_step_attempts": True})}
        ),
        definition.model_copy(
            update={
                "steps": (
                    definition.steps[0].model_copy(update={"operation": "BUILD_LOCAL_EMBEDDINGS"}),
                    definition.steps[1],
                )
            }
        ),
    ):
        with pytest.raises(ReferenceQueryContractError):
            parse_reference_query_workflow_definition(copied)
    schema = load_reference_query_execution_schema()
    schema["$defs"]["definition"]["properties"]["schema_version"]["const"] = "broken"
    registry = reference_query_execution_schema_registry()
    resource = registry.contents(REFERENCE_QUERY_EXECUTION_SCHEMA_RESOURCE[1])
    resource["$defs"]["definition"]["additionalProperties"] = True
    assert parse_reference_query_workflow_definition(definition_body()) == definition


def test_document_resource_families_remain_the_same_exact_public_inventories() -> None:
    assert tuple(value[0] for value in LOCAL_EMBEDDING_SCHEMA_RESOURCES) == (
        "request",
        "source-plan",
        "encoding-job",
        "execution-policy",
    )
    assert tuple(value[0] for value in LOCAL_EMBEDDING_RECEIPT_SCHEMA_RESOURCES) == (
        "step-output",
        "workflow-receipt",
    )
    for group in (LOCAL_EMBEDDING_SCHEMA_RESOURCES, LOCAL_EMBEDDING_RECEIPT_SCHEMA_RESOURCES):
        for _, filename, _, expected in group:
            raw = (ROOT / "schemas/workflow" / filename).read_bytes()
            assert (
                raw == (ROOT / "packages/workflow/eom_workflow/resources" / filename).read_bytes()
            )
            assert sha256_bytes(raw) == expected
    policy = load_local_embedding_admission_schema("execution-policy")
    assert policy["properties"]["admission_mode"]["const"] == "OPERATOR_SEED_ONLY"
    assert (
        load_local_embedding_receipt_schema("workflow-receipt")["properties"]["purpose"]["const"]
        == "LOCAL_EMBEDDING"
    )


def test_new_domain_modules_have_no_infrastructure_or_runtime_imports() -> None:
    for name in ("reference_query_workflow.py", "reference_query_execution.py"):
        tree = ast.parse((ROOT / "packages/workflow/eom_workflow" / name).read_text())
        imports = {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        imports.update(
            item.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for item in node.names
        )
        assert not imports & {
            "sqlalchemy",
            "torch",
            "os",
            "pathlib",
            "subprocess",
            "httpx",
            "eom_orchestrator",
            "eom_catalog_service",
            "eom_gpu_lease",
        }


@pytest.mark.parametrize("missing", [True, False])
def test_missing_or_corrupt_new_resource_remains_explicit_schema_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: bool
) -> None:
    filename = REFERENCE_QUERY_EXECUTION_SCHEMA_RESOURCE[0]
    if not missing:
        (tmp_path / filename).write_bytes(b"{}")
    schema_owner._reference_query_execution_schema.cache_clear()
    schema_owner._reference_query_execution_registry.cache_clear()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(schema_owner, "WORKFLOW_RESOURCE_ROOT", tmp_path)
            with pytest.raises(ReferenceQueryContractError, match="SCHEMA_UNAVAILABLE"):
                parse_reference_query_workflow_definition(definition_body())
    finally:
        schema_owner._reference_query_execution_schema.cache_clear()
        schema_owner._reference_query_execution_registry.cache_clear()
    assert parse_reference_query_workflow_definition(definition_body()).schema_version == "1.2"


def test_missing_required_existing_schema_dependency_is_unavailable_not_bad_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_dependency() -> None:
        raise schema_owner.LocalEmbeddingAdmissionContractError(
            "LOCAL_EMBEDDING_SCHEMA_UNAVAILABLE"
        )

    schema_owner._reference_query_execution_registry.cache_clear()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(
                schema_owner, "local_embedding_admission_schema_registry", missing_dependency
            )
            with pytest.raises(ReferenceQueryContractError, match="SCHEMA_UNAVAILABLE"):
                parse_reference_query_workflow_definition(definition_body())
            with pytest.raises(ReferenceQueryContractError, match="SCHEMA_UNAVAILABLE"):
                reference_query_execution_schema_registry()
    finally:
        schema_owner._reference_query_execution_registry.cache_clear()
