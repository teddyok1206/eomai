"""Synthetic contract checks, not source authorization, execution or activation evidence."""

from __future__ import annotations

import ast
import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts import catalog_schema_registry
from eom_catalog_contracts.inference_transfer_embedding import (
    INCREMENTAL_EMBEDDING_RESULT_SCHEMA,
    INPUT_SCHEMA_REF,
    EmbeddingExecutionRuntime,
    EmbeddingSpace,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_workflow import local_embedding_workflow as contracts
from eom_workflow.local_embedding_workflow import (
    LOCAL_EMBEDDING_EXECUTION_PROTOCOL,
    LOCAL_EMBEDDING_INPUT_SCHEMA_REF,
    LOCAL_EMBEDDING_RESULT_SCHEMA,
    LocalEmbeddingStep,
    LocalEmbeddingWorkflowContractError,
    LocalEmbeddingWorkflowDefinition,
    LocalEmbeddingWorkflowRequest,
    load_local_embedding_definition_schema,
    load_local_embedding_workflow_request_schema,
    parse_local_embedding_workflow_definition,
    parse_local_embedding_workflow_request,
)
from eom_workflow.models import TerminalStep, WorkflowDefinition
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from tests.unit.inference_transfer_fixtures import embedding_model, profile, sha

ROOT = Path(__file__).resolve().parents[2]
_LEGACY_DEFINITION_SHA256 = "ce31a3f90594eb3f0ca89e492a0a2514694c6601d10780bd66f9b71ebea31a44"


def _definition() -> dict[str, Any]:
    return {
        "schema_version": "1.1",
        "definition_key": "local-embedding-index",
        "definition_version": "1.0.0",
        "start_step": "encode_batch",
        "limits": {"max_rework_cycles": 0, "max_step_attempts": 1},
        "steps": [
            {
                "key": "encode_batch",
                "type": "application",
                "operation": "BUILD_LOCAL_EMBEDDINGS",
                "result_schema": INCREMENTAL_EMBEDDING_RESULT_SCHEMA,
                "on_success": "complete",
            },
            {"key": "complete", "type": "terminal", "terminal_status": "COMPLETED"},
        ],
    }


def _space(*, device: str = "CPU") -> EmbeddingSpace:
    runtime = EmbeddingExecutionRuntime.model_validate(
        {
            "device": device,
            "precision": "FLOAT32",
            "tf32_enabled": False,
            "execution_runtime_sha256": sha("a" if device == "CPU" else "b"),
        }
    )
    body: dict[str, Any] = {
        "model_spec": embedding_model("intfloat/multilingual-e5-small").model_dump(mode="json"),
        "purpose": "DOCUMENT",
        "runtime": runtime.model_dump(mode="json"),
    }
    return EmbeddingSpace.model_validate(body | {"space_sha256": content_sha256(body)})


def _rehash(body: dict[str, Any]) -> dict[str, Any]:
    body = deepcopy(body)
    body["request_sha256"] = content_sha256(
        {key: value for key, value in body.items() if key != "request_sha256"}
    )
    return body


def _request(*, device: str = "CPU") -> dict[str, Any]:
    return _rehash(
        {
            "schema_version": "local-embedding-workflow-request/1.0",
            "request_name": "LOCAL_EMBEDDING_WORKFLOW_REQUEST",
            "workflow_definition_key": "local-embedding-index",
            "workflow_definition_version": "1.0.0",
            "requested_by_operator_id": "operator_" + "1" * 32,
            "requester_permissions_sha256": sha("2"),
            "graph_snapshot": profile("a").source_basis.graph_snapshot.model_dump(mode="json"),
            "access_policy_revision_id": "accessrev_" + "3" * 32,
            "access_policy_sha256": sha("3"),
            "space": _space(device=device).model_dump(mode="json"),
            "input_artifact": {
                "artifact_id": "artifact_" + "4" * 32,
                "artifact_revision_id": "rev_" + "5" * 32,
                "member_path": "input.json",
                "schema_ref": INPUT_SCHEMA_REF,
                "media_type": "application/json",
                "sha256": sha("6"),
            },
            "input_set_sha256": sha("7"),
        }
    )


def _reject_definition(body: dict[str, Any]) -> None:
    with pytest.raises(LocalEmbeddingWorkflowContractError) as caught:
        parse_local_embedding_workflow_definition(body)
    assert str(caught.value) == "LOCAL_EMBEDDING_WORKFLOW_INVALID"


def _reject_request(body: dict[str, Any]) -> None:
    with pytest.raises(LocalEmbeddingWorkflowContractError) as caught:
        parse_local_embedding_workflow_request(body)
    assert str(caught.value) == "LOCAL_EMBEDDING_WORKFLOW_INVALID"


def test_schema_first_package_mirrors_and_released_definition_bytes_are_preserved() -> None:
    for name in (
        "workflow-definition-v1_1.schema.json",
        "local-embedding-workflow-request-v1.schema.json",
    ):
        assert (ROOT / "schemas/workflow" / name).read_bytes() == (
            ROOT / "packages/workflow/eom_workflow/resources" / name
        ).read_bytes()
    for path in (
        ROOT / "schemas/workflow/workflow-definition.schema.json",
        ROOT / "packages/workflow/eom_workflow/resources/workflow-definition.schema.json",
    ):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == _LEGACY_DEFINITION_SHA256
    Draft202012Validator.check_schema(load_local_embedding_definition_schema())
    Draft202012Validator.check_schema(load_local_embedding_workflow_request_schema())


def test_one_application_purpose_round_trips_without_worker_or_pack() -> None:
    checked = parse_local_embedding_workflow_definition(_definition())
    assert isinstance(checked.steps[0], LocalEmbeddingStep)
    assert isinstance(checked.steps[1], TerminalStep)
    assert checked.model_dump(mode="json") == _definition()
    assert LOCAL_EMBEDDING_RESULT_SCHEMA == INCREMENTAL_EMBEDDING_RESULT_SCHEMA
    assert LOCAL_EMBEDDING_EXECUTION_PROTOCOL == "local-embedding/1.0"
    assert "worker_role" not in checked.steps[0].model_dump(mode="json")
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(_definition())
    with pytest.raises(ValidationError):
        checked.steps[0].operation = "DELETE_SOURCES"  # type: ignore[assignment]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", "1.0"),
        ("definition_key", "customer-support"),
        ("definition_version", "2.0.0"),
        ("start_step", "complete"),
        ("automatic_review_rework", {"source_review_step": "review", "target_authoring_step": "a"}),
    ),
)
def test_definition_namespace_and_purpose_are_closed(field: str, value: Any) -> None:
    body = _definition()
    body[field] = value
    _reject_definition(body)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("type", "agent"),
        ("key", "custom_step"),
        ("operation", "RUN_COMMAND"),
        ("result_schema", "authoring-result@1.0"),
        ("on_success", "encode_batch"),
        ("worker_role", "support"),
        ("worker_role", "image"),
        ("command", "/bin/true"),
        ("module", "untrusted.backend"),
        ("content_pack", {}),
    ),
)
def test_step_cannot_be_an_agent_or_generic_executor(field: str, value: Any) -> None:
    body = _definition()
    body["steps"][0][field] = value
    _reject_definition(body)


@pytest.mark.parametrize("value", (True, False, 0, 2, "1", 1.0))
def test_no_automatic_retry_or_coerced_attempt_limit(value: Any) -> None:
    body = _definition()
    body["limits"]["max_step_attempts"] = value
    _reject_definition(body)
    with pytest.raises(ValidationError):
        LocalEmbeddingWorkflowDefinition.model_validate(body)


def test_step_order_terminal_and_length_are_closed() -> None:
    reversed_body = _definition()
    reversed_body["steps"].reverse()
    _reject_definition(reversed_body)
    repeated = _definition()
    repeated["steps"].append(deepcopy(repeated["steps"][1]))
    _reject_definition(repeated)
    failed_terminal = _definition()
    failed_terminal["steps"][1]["terminal_status"] = "FAILED"
    _reject_definition(failed_terminal)
    checked = parse_local_embedding_workflow_definition(_definition())
    terminal = checked.steps[1].model_copy(update={"terminal_status": "FAILED"})
    with pytest.raises(ValidationError):
        LocalEmbeddingWorkflowDefinition.model_validate(
            checked.model_copy(update={"steps": (checked.steps[0], terminal)})
        )


def test_frozen_step_and_definition_copy_do_not_bypass_literal_validation() -> None:
    step = LocalEmbeddingStep().model_copy(update={"operation": "RUN_COMMAND"})
    with pytest.raises(ValidationError):
        LocalEmbeddingStep.model_validate(step)
    checked = parse_local_embedding_workflow_definition(_definition())
    with pytest.raises(ValidationError):
        LocalEmbeddingWorkflowDefinition.model_validate(
            checked.model_copy(update={"schema_version": "1.0"})
        )


def test_installed_schema_getters_do_not_expose_cached_mutable_schema() -> None:
    first = load_local_embedding_definition_schema()
    first["properties"]["schema_version"]["const"] = "tampered"
    assert load_local_embedding_definition_schema()["properties"]["schema_version"]["const"] == (
        "1.1"
    )
    other = load_local_embedding_workflow_request_schema()
    other["properties"]["request_name"]["const"] = "tampered"
    assert load_local_embedding_workflow_request_schema()["properties"]["request_name"][
        "const"
    ] == ("LOCAL_EMBEDDING_WORKFLOW_REQUEST")


@pytest.mark.parametrize("device", ("CPU", "CUDA"))
def test_native_pointer_request_is_nominal_not_activation_or_authority(device: str) -> None:
    body = _request(device=device)
    checked = parse_local_embedding_workflow_request(body)
    assert checked.model_dump(mode="json") == body
    assert checked.input_artifact.schema_ref == LOCAL_EMBEDDING_INPUT_SCHEMA_REF == INPUT_SCHEMA_REF
    assert checked.space.runtime.device == device
    assert "text" not in body and "source_admission_artifact" not in body
    assert checked.request_sha256 == content_sha256(
        checked.model_dump(mode="json", exclude={"request_sha256"})
    )
    validator = Draft202012Validator(
        load_local_embedding_workflow_request_schema(),
        registry=catalog_schema_registry(),
        format_checker=FormatChecker(),
    )
    validator.validate(body)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("requested_by_operator_id", "ADMIN"),
        ("requested_by_operator_id", "worker-support"),
        ("access_policy_revision_id", "latest"),
        ("request_name", "ITEM_GENERATION_REQUEST"),
        ("workflow_definition_key", "customer-support"),
        ("workflow_definition_version", "2.0.0"),
        ("authorized", True),
        ("worker_role", "support"),
        ("content_pack", {}),
        ("source_admission_artifact", {}),
        ("password", "synthetic-secret-not-a-real-credential"),
    ),
)
def test_request_cannot_supply_authority_or_another_purpose(field: str, value: Any) -> None:
    body = _request()
    body[field] = value
    _reject_request(_rehash(body))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("member_path", "../input.json"),
        ("member_path", "request.json"),
        ("schema_ref", "eom://schemas/knowledge/not-registered-input/1.0"),
        ("schema_ref", "file:///tmp/input.json"),
        ("media_type", "application/octet-stream"),
        ("artifact_id", "latest"),
        ("sha256", "missing-hash"),
    ),
)
def test_input_artifact_pointer_is_exact_and_safe(field: str, value: str) -> None:
    body = _request()
    body["input_artifact"][field] = value
    _reject_request(_rehash(body))


def test_hash_graph_and_nested_space_forgeries_fail_closed() -> None:
    bad_hash = _request()
    bad_hash["input_set_sha256"] = sha("8")
    _reject_request(bad_hash)
    bad_graph = _request()
    bad_graph["graph_snapshot"]["manifest_sha256"] = sha("f")
    _reject_request(_rehash(bad_graph))
    bad_space = _request()
    bad_space["space"]["space_sha256"] = sha("f")
    _reject_request(_rehash(bad_space))
    checked = parse_local_embedding_workflow_request(_request())
    forged = checked.model_copy(
        update={"space": checked.space.model_copy(update={"space_sha256": sha("f")})}
    )
    forged = forged.model_copy(
        update={
            "request_sha256": content_sha256(
                forged.model_dump(mode="json", exclude={"request_sha256"})
            )
        }
    )
    with pytest.raises(ValidationError):
        LocalEmbeddingWorkflowRequest.model_validate(forged)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("request_name", "CUSTOMER_SUPPORT_REQUEST"),
        ("requested_by_operator_id", "ADMIN"),
        ("workflow_definition_key", "customer-support"),
    ),
)
def test_frozen_native_copy_requires_full_validation_after_rehash(field: str, value: str) -> None:
    checked = parse_local_embedding_workflow_request(_request())
    forged = checked.model_copy(update={field: value})
    forged = forged.model_copy(
        update={
            "request_sha256": content_sha256(
                forged.model_dump(mode="json", exclude={"request_sha256"})
            )
        }
    )
    with pytest.raises(ValidationError):
        LocalEmbeddingWorkflowRequest.model_validate(forged)


def test_byte_budget_and_errors_do_not_expose_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    body = _request()
    size = len(canonical_json_bytes(body))
    monkeypatch.setattr(contracts, "MAX_LOCAL_EMBEDDING_WORKFLOW_BYTES", size)
    assert parse_local_embedding_workflow_request(body)
    monkeypatch.setattr(contracts, "MAX_LOCAL_EMBEDDING_WORKFLOW_BYTES", size - 1)
    _reject_request(body)
    private = _request()
    private["private_payload"] = "SYNTHETIC_PRIVATE_TEXT" * 10000
    with pytest.raises(LocalEmbeddingWorkflowContractError) as caught:
        parse_local_embedding_workflow_request(private)
    assert "SYNTHETIC_PRIVATE_TEXT" not in str(caught.value)


def test_contract_source_has_no_infrastructure_or_numerical_import() -> None:
    source = ROOT / "packages/workflow/eom_workflow/local_embedding_workflow.py"
    names: set[str] = set()
    for node in ast.walk(ast.parse(source.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names.intersection(
        {
            "torch",
            "transformers",
            "sqlalchemy",
            "subprocess",
            "eom_orchestrator",
            "eom_catalog_service",
            "eom_workflow_runner",
        }
    )
