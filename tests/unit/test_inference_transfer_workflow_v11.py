"""Three-axis purpose successors and immutable history; no actual worker or DB."""

from __future__ import annotations

import copy
from contextlib import nullcontext
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_catalog_service.inference_transfer_comparison import (
    prepare_pair_comparison,
    prepare_pair_comparison_v11,
)
from eom_identifiers import content_sha256, sha256_bytes
from eom_workflow import compile_definition
from eom_workflow.control_schemas import validate_control_contract
from eom_workflow.inference_transfer import (
    TRANSFER_PAIR_PROTOCOL,
    TRANSFER_PAIR_PROTOCOL_V11,
    TRANSFER_PAIR_RESULT_SCHEMA,
    TRANSFER_PAIR_RESULT_SCHEMA_V11,
    InferenceTransferPairWorkerRequestV11,
    validate_inference_transfer_execution_plan,
    validate_inference_transfer_execution_plan_v11,
    validate_inference_transfer_worker_result,
    validate_inference_transfer_worker_result_v11,
)
from eom_workflow.inference_transfer_control import (
    ResolvedExecutionPlanV21,
    ResolvedExecutionPlanV22,
)
from eom_workflow.inference_transfer_materialization import (
    InferenceTransferMaterializationContext,
    InferenceTransferMaterializationContextV11,
    validate_inference_transfer_materialization_plan,
    validate_inference_transfer_materialization_plan_v11,
)
from eom_workflow.inference_transfer_workflow import (
    InferenceTransferWorkflowRequest,
    InferenceTransferWorkflowRequestV11,
)
from eom_workflow.models import InferenceTransferPairRoleResultV11, RoleWorkerInput, WorkflowRequest
from eom_workflow.schemas import (
    WorkflowSchemaError,
    constrained_result_schema,
    load_codex_result_schema,
    load_inference_transfer_workflow_request_schema_v11,
    load_role_input_schema,
    load_role_result_schema,
    role_schema_bundle_hash,
    validate_inference_transfer_workflow_request,
    validate_inference_transfer_workflow_request_v11,
    validate_role_input,
    validate_role_result,
)
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.inference_transfer_admission import (
    InferenceTransferSubmissionContext,
    admit_inference_transfer_workflow_request,
)
from eom_workflow_runner.models import WorkflowDefinitionRecord, WorkflowInstanceRecord
from eom_workflow_runner.repository import (
    create_workflow_instance,
    inference_transfer_business_fingerprint,
    load_persisted_inference_transfer_workflow_request,
    workflow_request_storage_document,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.unit.inference_transfer_execution_fixtures import transfer_plan
from tests.unit.inference_transfer_fixtures import NOW, profile, request, result, sha
from tests.unit.inference_transfer_invocation_fixtures import rehash
from tests.unit.inference_transfer_pair_v11_fixtures import pair_result_v11
from tests.unit.inference_transfer_workflow_fixtures import (
    OPERATOR_ID,
    OTHER_OPERATOR_ID,
    definition,
    submission_context,
    workflow_request,
)

ROOT = Path(__file__).resolve().parents[2]


def materialization_context() -> InferenceTransferMaterializationContext:
    workflow = workflow_request()
    worker = RoleWorkerInput.model_validate(
        {
            "protocol_version": TRANSFER_PAIR_PROTOCOL,
            "job_id": "job_" + "1" * 32,
            "workflow_id": "workflow_" + "1" * 32,
            "step_run_id": "steprun_" + "1" * 32,
            "attempt": 1,
            "role": "support",
            "request": workflow.worker_request().model_dump(mode="json"),
            "upstream_artifacts": [],
            "artifact": {
                "logical_artifact_id": "artifact_" + "8" * 32,
                "revision_id": "rev_" + "8" * 32,
                "file_name": "result.json",
                "media_type": "application/json",
            },
        }
    )
    return InferenceTransferMaterializationContext(
        workflow_id=worker.workflow_id,
        workflow_request=workflow,
        worker_input=worker,
        core_prompt_sha256=sha("5"),
        prompt_sha256=sha("6"),
    )


def materialization_plan(context: InferenceTransferMaterializationContext) -> dict[str, Any]:
    body = transfer_plan(context.workflow_request.comparison).model_dump(mode="json") | {
        "access_policy_revision_id": context.workflow_request.access_policy_revision_id,
        "access_policy_sha256": context.workflow_request.access_policy_sha256,
        "requester_permissions_sha256": context.workflow_request.requester_permissions_sha256,
        "core_prompt_sha256": context.core_prompt_sha256,
        "prompt_sha256": context.prompt_sha256,
    }
    return rehash(body, "plan_sha256")


def _workflow() -> InferenceTransferWorkflowRequestV11:
    body = workflow_request().model_dump(mode="json") | {
        "schema_version": "inference-transfer-workflow-request/1.1",
        "request_name": "ITEM_INFERENCE_TRANSFER_PAIR_REQUEST_V11",
        "execution_preset_key": "item-inference-transfer-comparison-axes",
    }
    return validate_inference_transfer_workflow_request_v11(rehash(body, "request_sha256"))


def _context() -> InferenceTransferMaterializationContextV11:
    old = materialization_context()
    document = old.model_dump(mode="json")
    document["workflow_request"] = _workflow().model_dump(mode="json")
    document["worker_input"]["protocol_version"] = TRANSFER_PAIR_PROTOCOL_V11
    document["worker_input"]["request"] = _workflow().worker_request().model_dump(mode="json")
    return InferenceTransferMaterializationContextV11.model_validate(document)


def _plan() -> dict[str, Any]:
    body = materialization_plan(materialization_context()) | {
        "schema_version": "resolved-execution-plan/22.0",
        "workflow_definition_version": "1.1.0",
        "resolver_version": "22.0.0",
    }
    return rehash(body, "plan_sha256")


def _result() -> InferenceTransferPairRoleResultV11:
    source = _context().worker_input
    return InferenceTransferPairRoleResultV11(
        job_id=source.job_id,
        workflow_id=source.workflow_id,
        step_run_id=source.step_run_id,
        artifact=source.artifact,
        completed_at=NOW,
        output=pair_result_v11(),
    )


def _definition() -> WorkflowDefinitionRecord:
    compiled = compile_definition(
        ROOT / "config/workflows/item-inference-transfer-comparison.v1_1.yaml", {"support"}
    )
    return WorkflowDefinitionRecord(
        definition_id="wfdef_" + "2" * 32,
        definition_key=compiled.definition.definition_key,
        definition_version=compiled.definition.definition_version,
        schema_version=compiled.definition.schema_version,
        canonical_definition=compiled.as_dict(),
        definition_hash=compiled.sha256,
        active=True,
        source_path=compiled.source_path,
    )


def _session() -> Mock:
    session = Mock(spec=Session)
    session.scalar.return_value = None
    session.begin_nested.return_value = nullcontext()
    return session


def _create(
    session: Mock, *, actor_id: str = OPERATOR_ID, key: str = "synthetic-axes-submission"
) -> tuple[WorkflowInstanceRecord, bool]:
    return create_workflow_instance(
        cast(Session, session),
        definition=_definition(),
        request=_workflow(),
        idempotency_key=key,
        actor_type="human",
        actor_id=actor_id,
        inference_transfer_context=submission_context(actor_id),
    )


@pytest.mark.parametrize(
    "relative",
    [
        "roles/item-inference-transfer-pair-input-v2.schema.json",
        "roles/item-inference-transfer-pair-result-v2.schema.json",
        "control-plane/resolved-execution-plan-v22.schema.json",
        "inference-transfer-workflow-request-v1_1.schema.json",
    ],
)
def test_successor_canonical_and_package_schema_bytes_match(relative: str) -> None:
    canonical = ROOT / "schemas/workflow" / relative
    mirror = ROOT / "packages/workflow/eom_workflow/resources" / relative
    assert canonical.read_bytes() == mirror.read_bytes()
    import json

    schema = json.loads(canonical.read_bytes())
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


def test_workflow_wrapper_worker_and_role_protocol_are_explicit_successors() -> None:
    workflow = _workflow()
    source = _context().worker_input
    assert isinstance(workflow.worker_request(), InferenceTransferPairWorkerRequestV11)
    assert workflow.worker_request() == source.request
    assert "requester_permissions_sha256" not in source.request.model_dump(mode="json")
    assert source.protocol_version == TRANSFER_PAIR_PROTOCOL_V11
    assert (
        validate_role_input(source.model_dump(mode="json"), "support", TRANSFER_PAIR_PROTOCOL_V11)
        == source
    )
    assert (
        validate_inference_transfer_workflow_request_v11(workflow.model_dump(mode="json"))
        == workflow
    )


@pytest.mark.parametrize("version", ["workflow-role/1.28.0", TRANSFER_PAIR_PROTOCOL])
def test_v11_worker_request_cannot_be_reinterpreted_under_older_protocol(version: str) -> None:
    body = _context().worker_input.model_dump(mode="json") | {"protocol_version": version}
    with pytest.raises(ValidationError, match="isolated protocol successor"):
        RoleWorkerInput.model_validate(body)
    with pytest.raises(WorkflowSchemaError):
        validate_role_input(body, "support", version)


def test_legacy_pair_request_is_rejected_by_new_protocol_even_with_same_profile_pins() -> None:
    body = materialization_context().worker_input.model_dump(mode="json") | {
        "protocol_version": TRANSFER_PAIR_PROTOCOL_V11
    }
    with pytest.raises(ValidationError, match="isolated protocol successor"):
        RoleWorkerInput.model_validate(body)
    with pytest.raises(WorkflowSchemaError):
        validate_role_input(body, "support", TRANSFER_PAIR_PROTOCOL_V11)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "inference-transfer-workflow-request/1.0"),
        ("request_name", "ITEM_INFERENCE_TRANSFER_PAIR_REQUEST"),
        ("execution_preset_key", "item-inference-transfer-comparison"),
        ("actor_id", OPERATOR_ID),
        ("role", "ADMIN"),
        ("permissions", ["ALL"]),
    ],
)
def test_new_wrapper_rejects_old_purpose_or_caller_authority(field: str, value: Any) -> None:
    body = rehash(_workflow().model_dump(mode="json") | {field: value}, "request_sha256")
    with pytest.raises(WorkflowSchemaError):
        validate_inference_transfer_workflow_request_v11(body)
    with pytest.raises(ValidationError):
        InferenceTransferWorkflowRequestV11.model_validate(body)


def test_saved_wrapper_loader_preserves_both_families_without_upgrading() -> None:
    for original in (workflow_request(), _workflow()):
        stored = workflow_request_storage_document(original)
        loaded = load_persisted_inference_transfer_workflow_request(stored)
        assert type(loaded) is type(original)
        assert loaded == original
        assert workflow_request_storage_document(loaded) == stored
    with pytest.raises(WorkflowSchemaError):
        validate_inference_transfer_workflow_request(_workflow().model_dump(mode="json"))
    with pytest.raises(WorkflowSchemaError):
        validate_inference_transfer_workflow_request_v11(workflow_request().model_dump(mode="json"))


def test_canonical_axis_tuple_is_preserved_but_generation_has_uniform_items() -> None:
    canonical = load_role_result_schema(TRANSFER_PAIR_RESULT_SCHEMA_V11)
    output = canonical["$defs"]["InferenceTransferPairResultV11"]
    axes = output["properties"]["axes"]
    assert len(axes["prefixItems"]) == 3 and axes["items"] is False
    assert "allOf" in output
    generation = load_codex_result_schema(TRANSFER_PAIR_RESULT_SCHEMA_V11)
    generated_axes = generation["$defs"]["InferenceTransferPairResultV11"]["properties"]["axes"]
    assert "prefixItems" not in generated_axes
    assert isinstance(generated_axes["items"], dict)
    assert generated_axes["minItems"] == generated_axes["maxItems"] == 3
    assert "allOf" not in generation["$defs"]["InferenceTransferPairResultV11"]
    assert load_role_result_schema(TRANSFER_PAIR_RESULT_SCHEMA_V11) == canonical


def test_generation_relaxation_does_not_relax_canonical_admission() -> None:
    body = _result().model_dump(mode="json")
    body["output"]["axes"][0], body["output"]["axes"][1] = (
        body["output"]["axes"][1],
        body["output"]["axes"][0],
    )
    body["output"] = rehash(body["output"], "result_sha256")
    Draft202012Validator(load_codex_result_schema(TRANSFER_PAIR_RESULT_SCHEMA_V11)).validate(body)
    with pytest.raises(WorkflowSchemaError):
        validate_role_result(body, "support", TRANSFER_PAIR_RESULT_SCHEMA_V11)
    with pytest.raises(ValidationError):
        InferenceTransferPairRoleResultV11.model_validate(body)


def test_generation_schema_has_only_local_resolvable_references() -> None:
    schema = constrained_result_schema(TRANSFER_PAIR_RESULT_SCHEMA_V11, _context().worker_input)
    pending: list[object] = [schema]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            reference = value.get("$ref")
            if reference is not None:
                assert isinstance(reference, str) and reference.startswith("#/")
                resolved: Any = schema
                for segment in reference[2:].split("/"):
                    resolved = resolved[segment.replace("~1", "/").replace("~0", "~")]
                assert isinstance(resolved, dict)
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    Draft202012Validator(schema).validate(_result().model_dump(mode="json"))


@pytest.mark.parametrize(
    "path,value",
    [
        (("job_id",), "job_" + "f" * 32),
        (("workflow_id",), "workflow_" + "f" * 32),
        (("step_run_id",), "steprun_" + "f" * 32),
        (("artifact", "revision_id"), "rev_" + "f" * 32),
        (("output", "request_id"), "transferrequest_" + "f" * 32),
        (("output", "request_sha256"), sha("f")),
        (("output", "left_profile", "profile_sha256"), sha("f")),
        (("output", "right_profile", "profile_revision_id"), "inferenceprofilerev_" + "f" * 32),
        (("output", "rubric", "rubric_sha256"), sha("f")),
    ],
)
def test_constrained_schema_binds_outer_and_inner_exact_pins(
    path: tuple[str, ...], value: str
) -> None:
    schema = constrained_result_schema(TRANSFER_PAIR_RESULT_SCHEMA_V11, _context().worker_input)
    body = _result().model_dump(mode="json")
    target = body
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = value
    with pytest.raises(SchemaValidationError):
        Draft202012Validator(schema).validate(body)


@pytest.mark.parametrize("axis_index", [0, 1, 2])
@pytest.mark.parametrize("side", ["left_claim_ids", "right_claim_ids"])
def test_constrained_generation_rejects_unselected_axis_refs(axis_index: int, side: str) -> None:
    schema = constrained_result_schema(TRANSFER_PAIR_RESULT_SCHEMA_V11, _context().worker_input)
    body = _result().model_dump(mode="json")
    body["output"]["axes"][axis_index][side] = ["transferclaim_absent"]
    with pytest.raises(SchemaValidationError):
        Draft202012Validator(schema).validate(body)


@pytest.mark.parametrize("new_schema", [False, True])
def test_result_projection_cannot_bind_opposite_worker_family(new_schema: bool) -> None:
    schema_id = TRANSFER_PAIR_RESULT_SCHEMA_V11 if new_schema else TRANSFER_PAIR_RESULT_SCHEMA
    worker = materialization_context().worker_input if new_schema else _context().worker_input
    with pytest.raises(WorkflowSchemaError, match="purpose differs"):
        constrained_result_schema(schema_id, worker)


def test_v11_role_result_admits_three_axes_and_exact_decisive_grounding() -> None:
    parsed = validate_role_result(
        _result().model_dump(mode="json"), "support", TRANSFER_PAIR_RESULT_SCHEMA_V11
    )
    assert isinstance(parsed, InferenceTransferPairRoleResultV11)
    validate_inference_transfer_worker_result_v11(_workflow().worker_request(), parsed.output)
    body = parsed.output.model_dump(mode="json")
    body["axes"][2]["left_claim_ids"] = ["transferclaim_condition"]
    invalid = type(parsed.output).model_validate(rehash(body, "result_sha256"))
    with pytest.raises(ValueError, match="decisive claims"):
        validate_inference_transfer_worker_result_v11(_workflow().worker_request(), invalid)


def test_legacy_result_validator_cannot_accept_new_worker_purpose() -> None:
    with pytest.raises(ValueError):
        validate_inference_transfer_worker_result(_workflow().worker_request(), result())


@pytest.mark.parametrize("new_schema", [False, True])
def test_role_result_cannot_be_parsed_as_opposite_family(new_schema: bool) -> None:
    body = _result().model_dump(mode="json")
    if new_schema:
        body.update(
            protocol_version=TRANSFER_PAIR_PROTOCOL, output=result().model_dump(mode="json")
        )
    schema_id = TRANSFER_PAIR_RESULT_SCHEMA_V11 if new_schema else TRANSFER_PAIR_RESULT_SCHEMA
    with pytest.raises(WorkflowSchemaError):
        validate_role_result(body, "support", schema_id)


def test_resolved_v22_plan_and_materialization_context_bind_all_exact_pins() -> None:
    context = _context()
    validate_control_contract("resolved-execution-plan-v22", _plan())
    assert isinstance(ResolvedExecutionPlanV22.model_validate(_plan()), ResolvedExecutionPlanV22)
    checked = validate_inference_transfer_materialization_plan_v11(_plan(), context=context)
    assert checked.workflow_definition_version == "1.1.0"
    assert (
        checked.requester_permissions_sha256
        == context.workflow_request.requester_permissions_sha256
    )


@pytest.mark.parametrize("new_plan", [False, True])
def test_opposite_execution_plan_version_is_rejected(new_plan: bool) -> None:
    plan = _plan() if new_plan else materialization_plan(materialization_context())
    if new_plan:
        with pytest.raises(ValueError):
            validate_inference_transfer_materialization_plan(
                plan, context=materialization_context()
            )
    else:
        with pytest.raises(ValueError):
            validate_inference_transfer_materialization_plan_v11(plan, context=_context())
    model = ResolvedExecutionPlanV21 if new_plan else ResolvedExecutionPlanV22
    with pytest.raises(ValidationError):
        model.model_validate(plan)


@pytest.mark.parametrize("new_plan", [False, True])
def test_execution_plan_helper_rejects_opposite_request_family_with_identical_inner_pins(
    new_plan: bool,
) -> None:
    context = _context() if new_plan else materialization_context()
    opposite_request = (
        workflow_request().worker_request() if new_plan else _workflow().worker_request()
    )
    validator = (
        validate_inference_transfer_execution_plan_v11
        if new_plan
        else validate_inference_transfer_execution_plan
    )
    with pytest.raises(ValueError):
        cast(Any, validator)(
            _plan() if new_plan else materialization_plan(context),
            request=opposite_request,
            workflow_id=context.workflow_id,
            step_key=context.step_key,
            core_prompt_sha256=context.core_prompt_sha256,
            prompt_sha256=context.prompt_sha256,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("workflow_id", "workflow_" + "f" * 32),
        ("access_policy_revision_id", "accessrev_" + "f" * 32),
        ("access_policy_sha256", sha("f")),
        ("requester_permissions_sha256", sha("f")),
        ("comparison_request_sha256", sha("f")),
        ("core_prompt_sha256", sha("f")),
        ("prompt_sha256", sha("f")),
    ],
)
def test_rehashed_v22_plan_cannot_substitute_independent_context(field: str, value: str) -> None:
    plan = rehash(_plan() | {field: value}, "plan_sha256")
    with pytest.raises(ValueError):
        validate_inference_transfer_materialization_plan_v11(plan, context=_context())


def test_materialization_copied_old_request_or_role_protocol_cannot_bypass_validation() -> None:
    context = _context()
    copied = context.model_copy(update={"workflow_request": workflow_request()})
    with pytest.raises(ValueError):
        validate_inference_transfer_materialization_plan_v11(_plan(), context=copied)
    copied = context.model_copy(
        update={
            "worker_input": context.worker_input.model_copy(
                update={"protocol_version": TRANSFER_PAIR_PROTOCOL}
            )
        }
    )
    with pytest.raises(ValueError):
        validate_inference_transfer_materialization_plan_v11(_plan(), context=copied)


def test_wrapper_loader_rejects_missing_null_and_copied_purpose_without_repair() -> None:
    body = _workflow().model_dump(mode="json")
    del body["left_profile"]["extraction"]["prompt_sha256"]
    with pytest.raises(WorkflowSchemaError):
        load_persisted_inference_transfer_workflow_request(rehash(body, "request_sha256"))
    copied = _workflow().model_copy(update={"request_name": "CUSTOMER_SUPPORT_REQUEST"})
    with pytest.raises(WorkflowSchemaError):
        validate_inference_transfer_workflow_request_v11(
            rehash(copied.model_dump(mode="json"), "request_sha256")
        )
    isolated = load_inference_transfer_workflow_request_schema_v11()
    isolated["properties"]["request_name"]["const"] = "CUSTOMER_SUPPORT_REQUEST"
    assert (
        load_inference_transfer_workflow_request_schema_v11()["properties"]["request_name"]["const"]
        == "ITEM_INFERENCE_TRANSFER_PAIR_REQUEST_V11"
    )


@pytest.mark.parametrize(
    "invalid",
    [
        "legacy-request",
        "legacy-definition",
        "legacy-protocol",
        "foreign-purpose",
        "missing-context",
    ],
)
def test_v11_admission_rejects_before_any_repository_operation(invalid: str) -> None:
    session = _session()
    target = _definition()
    source: InferenceTransferWorkflowRequest = _workflow()
    context: InferenceTransferSubmissionContext | None = submission_context()
    if invalid == "legacy-request":
        source = workflow_request()
    elif invalid == "legacy-definition":
        target = definition()
    elif invalid == "legacy-protocol":
        target.canonical_definition = copy.deepcopy(target.canonical_definition)
        target.canonical_definition["steps"][0]["result_schema"] = TRANSFER_PAIR_RESULT_SCHEMA
    elif invalid == "foreign-purpose":
        target.definition_key = "customer-support"
    elif invalid == "missing-context":
        context = None
    with pytest.raises(WorkflowError):
        create_workflow_instance(
            cast(Session, session),
            definition=target,
            request=source,
            idempotency_key="synthetic-invalid-axes",
            actor_type="human",
            actor_id=OPERATOR_ID,
            inference_transfer_context=context,
        )
    for method in (
        session.scalar,
        session.execute,
        session.add,
        session.flush,
        session.begin_nested,
    ):
        method.assert_not_called()


def test_generic_item_request_cannot_enter_new_comparison_definition() -> None:
    with pytest.raises(WorkflowError):
        admit_inference_transfer_workflow_request(
            definition_key="item-inference-transfer-comparison",
            definition_version="1.1.0",
            role_protocol_version=TRANSFER_PAIR_PROTOCOL_V11,
            request=WorkflowRequest(request_name="PLACEHOLDER_REQUEST", image_mode="skip"),
            actor_type="human",
            actor_id=OPERATOR_ID,
            submission_context=submission_context(),
        )


def test_v11_actor_scoped_fingerprint_exact_replay_and_global_key_conflict() -> None:
    first, created = _create(_session())
    assert created and first.role_schema_version == TRANSFER_PAIR_PROTOCOL_V11
    assert first.request_payload == _workflow().model_dump(mode="json")
    assert first.created_actor_id == OPERATOR_ID
    assert first.request_hash == inference_transfer_business_fingerprint(
        _definition(), _workflow(), actor_type="human", actor_id=OPERATOR_ID
    )
    assert first.request_hash != inference_transfer_business_fingerprint(
        _definition(), _workflow(), actor_type="human", actor_id=OTHER_OPERATOR_ID
    )
    replay = _session()
    replay.scalar.return_value = first
    assert _create(replay) == (first, False)
    replay.add.assert_not_called()
    with pytest.raises(WorkflowError) as error:
        _create(replay, actor_id=OTHER_OPERATOR_ID)
    assert error.value.code == WorkflowErrorCode.WORKFLOW_COMMAND_DUPLICATE


@pytest.mark.parametrize("foreign_actor", [False, True])
def test_v11_concurrent_unique_claim_replay_does_not_rewrite_winner(foreign_actor: bool) -> None:
    winner, _ = _create(_session())
    before = workflow_request_storage_document(_workflow())
    raced = _session()
    raced.scalar.side_effect = [None, None, None, winner]
    raced.flush.side_effect = IntegrityError("synthetic concurrent global key", {}, Exception())
    if foreign_actor:
        with pytest.raises(WorkflowError) as error:
            _create(raced, actor_id=OTHER_OPERATOR_ID)
        assert error.value.code == WorkflowErrorCode.WORKFLOW_COMMAND_DUPLICATE
    else:
        assert _create(raced) == (winner, False)
    assert winner.request_payload == before
    assert winner.created_actor_id == OPERATOR_ID
    assert raced.scalar.call_count == 4


def test_historical_role_bundle_schema_prompt_and_json_bytes_are_unchanged() -> None:
    assert (
        role_schema_bundle_hash(TRANSFER_PAIR_PROTOCOL)
        == "sha256:fc65246c255e51d9500797abc976bc68d4a3eb81483301c132e098b74614f8dc"
    )
    assert (
        sha256_bytes(
            (
                ROOT / "schemas/workflow/roles/item-inference-transfer-pair-input-v1.schema.json"
            ).read_bytes()
        )
        == "sha256:e4673de257746d949de08c2edbdf32192cce69128e14cd96d30845f431f2e0be"
    )
    assert (
        sha256_bytes(
            (
                ROOT / "schemas/workflow/roles/item-inference-transfer-pair-result-v1.schema.json"
            ).read_bytes()
        )
        == "sha256:0eb141318465aba3f8e8c062b5f224f14e168ec9ec29ffdba8a4ab2f6a0ee86b"
    )
    assert (
        content_sha256(result().model_dump(mode="json"))
        == "sha256:95878ede4e4355ca3e493b0ba1736ebee076f40f199f19a33991ce6838fcd177"
    )
    old = prepare_pair_comparison(request(), left=profile("a"), right=profile("b"))
    new = prepare_pair_comparison_v11(request(), left=profile("a"), right=profile("b"))
    assert (
        old.prompt_sha256
        == "sha256:a101f23f4ffb30ca986bd11682c94ec9483cf99532d5086c74dae2a6b940dc0e"
    )
    assert old.prompt_version.endswith("/1.0") and new.prompt_version.endswith("/1.1")
    assert "axes는 CONCEPT" not in old.prompt_text
    assert "axes는 CONCEPT" in new.prompt_text
    assert old.context_bytes == new.context_bytes
    assert old.prompt_sha256 != new.prompt_sha256
    assert (
        load_role_input_schema("support", TRANSFER_PAIR_PROTOCOL)["properties"]["protocol_version"][
            "const"
        ]
        == TRANSFER_PAIR_PROTOCOL
    )
