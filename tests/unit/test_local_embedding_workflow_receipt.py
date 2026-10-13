"""Protocol-only receipt checks; no source grants, publisher, DB, NAS or numerical work."""

from __future__ import annotations

import ast
import copy
from pathlib import Path
from typing import Any, cast

import pytest
from eom_catalog_contracts.inference_transfer_embedding import embedding_input_set_sha256
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow import (
    LOCAL_EMBEDDING_RECEIPT_SCHEMA_RESOURCES,
    LocalEmbeddingStepOutput,
    LocalEmbeddingWorkflowReceipt,
    local_embedding_step_output_bytes,
    local_embedding_workflow_receipt_bytes,
    parse_local_embedding_step_output,
    parse_local_embedding_workflow_receipt,
    validate_local_embedding_step_output,
    validate_local_embedding_workflow_receipt,
)
from eom_workflow.local_embedding_workflow_receipt import ResolvedNativeIndexCoverage
from eom_workflow.models import ArtifactPointer
from eom_workflow.schemas import (
    LOCAL_EMBEDDING_SCHEMA_RESOURCES,
    ROLE_SCHEMA_FILES,
    LocalEmbeddingAdmissionContractError,
    LocalEmbeddingReceiptSchemaName,
    load_local_embedding_receipt_schema,
    local_embedding_receipt_schema_registry,
    validate_local_embedding_receipt_message,
)
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from tests.unit.inference_transfer_embedding_fixtures import (
    index_manifest,
    seal,
    shard_pointer,
    source_binding,
    vector_shard,
)
from tests.unit.inference_transfer_fixtures import sha
from tests.unit.local_embedding_admission_fixtures import member, native_fixture
from tests.unit.local_embedding_workflow_receipt_fixtures import (
    NativeReceiptFixture,
    receipt_fixture,
)

ROOT = Path(__file__).resolve().parents[2]


def validate_fixture(
    fixture: NativeReceiptFixture,
    receipt: LocalEmbeddingWorkflowReceipt | None = None,
    *,
    borrowed_only: bool = False,
) -> LocalEmbeddingWorkflowReceipt:
    native = fixture.native
    return validate_local_embedding_workflow_receipt(
        receipt or fixture.receipt,
        native.request,
        native.plan,
        native.policy,
        workflow_id=native.association.intent.workflow_id,
        step_run_id=native.association.intent.step_run_id,
        receipt_owner_job_id=fixture.receipt.receipt_owner_job_id,
        launch_association=None if borrowed_only else native.association,
        owned_input=None if borrowed_only else native.native_input,
    )


def reseal_receipt(body: dict[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(body)
    body["registration_command"] = seal(body["registration_command"], "request_sha256")
    body["registration_result"]["request_sha256"] = body["registration_command"]["request_sha256"]
    body["registration_result"] = seal(body["registration_result"], "result_sha256")
    return seal(body, "receipt_sha256")


@pytest.mark.parametrize("corruption", [None, "duplicate", "missing", "index", "demand"])
def test_bounded_operation_proves_full_corpus_without_shrinking_denominator(
    corruption: str | None,
) -> None:
    fixture = receipt_fixture(borrowed_only=True)
    full = fixture.native
    selected = native_fixture("c" if corruption == "demand" else "a")
    shard = vector_shard(
        tuple(row.encoding for row in full.native_input.rows), space=full.plan.space
    )
    bindings = tuple(
        source_binding(
            entry,
            view=full.plan.namespace.view,
            recipe=full.plan.recipe,
            space=full.plan.space,
            shard=shard,
            pointer=shard_pointer(shard),
        )
        for entry in full.entries
    )
    index = index_manifest(
        *bindings,
        space=full.plan.space,
        view=full.plan.namespace.view,
        revision_seed="3" if corruption == "index" else "2",
    )
    body = fixture.receipt.model_dump(mode="json")
    body.update(
        workflow_request_sha256=selected.request.request_sha256,
        source_plan=selected.request.source_plan.model_dump(mode="json"),
        source_plan_sha256=selected.plan.plan_sha256,
    )
    receipt = parse_local_embedding_workflow_receipt(seal(body, "receipt_sha256"))
    arguments = dict(
        workflow_id=receipt.workflow_id,
        step_run_id=receipt.step_run_id,
        receipt_owner_job_id=receipt.receipt_owner_job_id,
        launch_association=None,
        owned_input=None,
    )
    with pytest.raises(ValueError, match="whole-plan"):
        validate_local_embedding_workflow_receipt(
            receipt, selected.request, selected.plan, selected.policy, **arguments
        )
    sources = full.plan.sources
    if corruption == "duplicate":
        sources = (*sources, sources[0])
    if corruption == "missing":
        sources = sources[:1]
    coverage = ResolvedNativeIndexCoverage(index, sources)
    if corruption is None:
        actual = validate_local_embedding_workflow_receipt(
            receipt,
            selected.request,
            selected.plan,
            selected.policy,
            index_coverage=coverage,
            **arguments,
        )
        assert actual.registration_command.eligible_source_count == 2
        assert len(selected.plan.sources) == 1 and actual.registration_command.binding_count == 2
    else:
        with pytest.raises(ValueError, match="full index or corpus"):
            validate_local_embedding_workflow_receipt(
                receipt,
                selected.request,
                selected.plan,
                selected.policy,
                index_coverage=coverage,
                **arguments,
            )


@pytest.mark.parametrize(
    "name,filename,schema_id,expected", LOCAL_EMBEDDING_RECEIPT_SCHEMA_RESOURCES
)
def test_closed_mirror_raw_hash_registered_refs_and_isolation(
    name: str,
    filename: str,
    schema_id: str,
    expected: str,
) -> None:
    canonical = (ROOT / "schemas/workflow" / filename).read_bytes()
    packaged = (ROOT / "packages/workflow/eom_workflow/resources" / filename).read_bytes()
    assert canonical == packaged and sha256_bytes(canonical) == expected
    schema_name = cast(LocalEmbeddingReceiptSchemaName, name)
    schema = load_local_embedding_receipt_schema(schema_name)
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == schema_id and schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert local_embedding_receipt_schema_registry().contents(schema_id)["$id"] == schema_id
    local_embedding_receipt_schema_registry().contents(schema_id)["type"] = "null"
    schema["title"] = "synthetic mutation"
    assert load_local_embedding_receipt_schema(schema_name)["title"] != schema["title"]
    assert local_embedding_receipt_schema_registry().contents(schema_id)["type"] == "object"


def test_released_four_family_and_role_resources_remain_exact() -> None:
    expected = (
        "sha256:042c77c73507eca65d58223186117c456e6171eb0ed2abfd1ad55c908a36bee1",
        "sha256:8ba4b285504c2c0c4ad668def7b276c71d900bf889a498c7cb6d6c24d822372e",
        "sha256:8ee755604333e84772d62c037d2487ead6f6f4b25a71eb92fa05c12bda748549",
        "sha256:07f1a6abc3635a927900149f949ade9dad28690b3948a0a7370bfc291c6d0963",
    )
    assert tuple(resource[3] for resource in LOCAL_EMBEDDING_SCHEMA_RESOURCES) == expected
    for _, filename, _, raw_hash in LOCAL_EMBEDDING_SCHEMA_RESOURCES:
        assert sha256_bytes((ROOT / "schemas/workflow" / filename).read_bytes()) == raw_hash
        assert (
            sha256_bytes(
                (ROOT / "packages/workflow/eom_workflow/resources" / filename).read_bytes()
            )
            == raw_hash
        )
    assert not {r[1] for r in LOCAL_EMBEDDING_RECEIPT_SCHEMA_RESOURCES}.intersection(
        ROLE_SCHEMA_FILES
    )
    with pytest.raises(ValidationError):
        ArtifactPointer.model_validate(receipt_fixture().output.model_dump(mode="json"))


@pytest.mark.parametrize("borrowed_only", [False, True])
@pytest.mark.parametrize("historical", [False, True])
def test_public_roundtrip_exact_context_and_raw_semantic_separation(
    borrowed_only: bool,
    historical: bool,
) -> None:
    fixture = receipt_fixture(borrowed_only=borrowed_only, historical=historical)
    receipt, output = fixture.receipt, fixture.output
    assert parse_local_embedding_workflow_receipt(receipt) == receipt
    assert parse_local_embedding_step_output(output.model_dump(mode="json")) == output
    assert validate_fixture(fixture, borrowed_only=borrowed_only) == receipt
    assert validate_local_embedding_step_output(output, receipt) == output
    assert local_embedding_workflow_receipt_bytes(receipt) == canonical_json_bytes(
        receipt.model_dump(mode="json")
    )
    assert local_embedding_step_output_bytes(output) == canonical_json_bytes(
        output.model_dump(mode="json")
    )
    assert output.receipt.sha256 == sha256_bytes(local_embedding_workflow_receipt_bytes(receipt))
    assert output.receipt.sha256 != output.receipt_sha256
    assert len(local_embedding_step_output_bytes(output)) < 8 * 1024
    assert len(local_embedding_workflow_receipt_bytes(receipt)) < 64 * 1024
    with pytest.raises(ValidationError):
        receipt.attempt = 2


@pytest.mark.parametrize("kind", ["step-output", "workflow-receipt"])
def test_every_schema_required_field_is_required_on_wire(kind: str) -> None:
    fixture = receipt_fixture()
    value = fixture.output if kind == "step-output" else fixture.receipt
    parser = (
        parse_local_embedding_step_output
        if kind == "step-output"
        else parse_local_embedding_workflow_receipt
    )
    for field in value.model_dump(mode="json"):
        document = value.model_dump(mode="json")
        del document[field]
        with pytest.raises(
            LocalEmbeddingAdmissionContractError, match="LOCAL_EMBEDDING_CONTRACT_INVALID"
        ):
            parser(document)


@pytest.mark.parametrize("kind", ["step-output", "workflow-receipt"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt", True),
        ("attempt", 1.0),
        ("attempt", "1"),
        ("attempt", 2),
        ("step_key", "compare_pair"),
        ("purpose", "CODEX"),
        ("execution_result_schema", "embedding-registry-registration-result@1.0"),
        ("workflow_id", "workflow_latest"),
        ("receipt_owner_job_id", "job_latest"),
    ],
)
def test_strict_closed_scalar_values(kind: str, field: str, value: object) -> None:
    fixture = receipt_fixture()
    original = fixture.output if kind == "step-output" else fixture.receipt
    body = original.model_dump(mode="json")
    body[field] = value
    parser = (
        parse_local_embedding_step_output
        if kind == "step-output"
        else parse_local_embedding_workflow_receipt
    )
    with pytest.raises(LocalEmbeddingAdmissionContractError):
        parser(body)


@pytest.mark.parametrize(
    "path,value",
    [
        (("receipt", "member_path"), "result.json"),
        (("receipt", "schema_ref"), "eom://schemas/knowledge/incremental-embedding-result/1.0"),
        (("receipt", "media_type"), "application/octet-stream"),
        (("receipt_schema",), "eom://schemas/workflow/local-embedding-workflow-receipt/1.1"),
        (("receipt_sha256",), sha("0")),
        (("output_sha256",), sha("0")),
    ],
)
def test_carrier_wrong_pointer_schema_or_semantic_hash(
    path: tuple[str, ...], value: object
) -> None:
    body = receipt_fixture().output.model_dump(mode="json")
    target = body
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises((LocalEmbeddingAdmissionContractError, ValueError)):
        output = parse_local_embedding_step_output(
            body if path == ("output_sha256",) else seal(body, "output_sha256")
        )
        validate_local_embedding_step_output(output, receipt_fixture().receipt)


@pytest.mark.parametrize("field", ["workflow_id", "step_run_id", "receipt_owner_job_id"])
def test_valid_resealed_carrier_still_requires_same_receipt_identity(field: str) -> None:
    fixture = receipt_fixture()
    body = fixture.output.model_dump(mode="json")
    body[field] = body[field].split("_")[0] + "_" + "f" * 32
    output = parse_local_embedding_step_output(seal(body, "output_sha256"))
    with pytest.raises(ValueError, match="exact receipt"):
        validate_local_embedding_step_output(output, fixture.receipt)


@pytest.mark.parametrize(
    "path,value",
    [
        (("attempt",), True),
        (("registration_command", "eligible_source_count"), True),
        (("registration_command", "binding_count"), 0),
        (("registration_command", "eligible_source_count"), 1025),
        (("registration_result", "current_lock_version"), True),
        (("registration_result", "replayed"), 1),
        (("source_plan", "member_path"), "input.json"),
        (("native_launch_job_id",), None),
        (("launch_association_sha256",), None),
        (("registration_observed_at",), "2026-10-12T09:00:00+09:00"),
        (("registration_observed_at",), "2000-01-01T00:00:00Z"),
        (("receipt_sha256",), sha("0")),
    ],
)
def test_invalid_receipt_scalar_nested_and_temporal_closure(
    path: tuple[str, ...], value: object
) -> None:
    body = receipt_fixture().receipt.model_dump(mode="json")
    target = body
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises((LocalEmbeddingAdmissionContractError, ValueError, TypeError)):
        parse_local_embedding_workflow_receipt(
            body if path == ("receipt_sha256",) else reseal_receipt(body)
        )


@pytest.mark.parametrize(
    "path,value",
    [
        (("workflow_request_sha256",), sha("0")),
        (("workflow_definition_sha256",), sha("0")),
        (("source_plan_sha256",), sha("0")),
        (("registration_command", "eligible_source_count"), 3),
        (("registration_command", "binding_count"), 1),
        (("registration_command", "namespace", "storage_partition"), "other-partition"),
        (("registration_command", "namespace", "space_sha256"), sha("0")),
        (("registration_command", "namespace", "recipe_sha256"), sha("0")),
        (("registration_command", "namespace", "view"), "METADATA_ONLY"),
        (("registration_command", "namespace", "population_scope"), "OCCURRENCE_BACKED_PAST_EXAM"),
        (("registration_command", "source_set_sha256"), sha("0")),
        (("registration_command", "corpus_id"), "corpus_" + "0" * 32),
        (("registration_command", "policy_sha256"), sha("0")),
        (("registration_command", "policy_revision_id"), "accessrev_" + "0" * 32),
        (
            ("registration_command", "graph_snapshot", "graph_snapshot_revision_id"),
            "graphrev_" + "0" * 32,
        ),
    ],
)
def test_valid_receipt_requires_exact_request_plan_namespace_counts_and_scope(
    path: tuple[str, ...],
    value: object,
) -> None:
    fixture = receipt_fixture()
    body = fixture.receipt.model_dump(mode="json")
    target = body
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    receipt = parse_local_embedding_workflow_receipt(reseal_receipt(body))
    with pytest.raises(ValueError, match="resolved Workflow context"):
        validate_fixture(fixture, receipt)


@pytest.mark.parametrize("field", ["workflow_id", "step_run_id", "receipt_owner_job_id"])
def test_expected_owner_context_ids_are_not_taken_from_receipt(field: str) -> None:
    fixture = receipt_fixture()
    body = fixture.receipt.model_dump(mode="json")
    body[field] = body[field].split("_")[0] + "_" + "f" * 32
    with pytest.raises(ValueError, match="resolved Workflow context"):
        validate_fixture(fixture, parse_local_embedding_workflow_receipt(reseal_receipt(body)))


@pytest.mark.parametrize(
    "path",
    [
        ("attempt",),
        ("registration_command", "expected_lock_version"),
        ("registration_result", "registered_lock_version"),
    ],
)
def test_copied_and_constructed_actual_bool_tree_is_not_serialized_to_integer(
    path: tuple[str, ...],
) -> None:
    fixture = receipt_fixture()
    value = fixture.receipt
    if len(path) == 1:
        bad = value.model_copy(update={path[0]: True})
    else:
        child = getattr(value, path[0]).model_copy(update={path[1]: True})
        bad = value.model_copy(update={path[0]: child})
    with pytest.raises(LocalEmbeddingAdmissionContractError):
        local_embedding_workflow_receipt_bytes(bad)
    constructed = LocalEmbeddingStepOutput.model_construct(
        **(fixture.output.__dict__ | {"attempt": True})
    )
    with pytest.raises(LocalEmbeddingAdmissionContractError):
        local_embedding_step_output_bytes(constructed)


def test_historical_receipt_observations_are_not_refreshed_or_silently_substituted() -> None:
    first, later = receipt_fixture(), receipt_fixture(historical=True)
    before = local_embedding_workflow_receipt_bytes(first.receipt)
    assert validate_fixture(first) == first.receipt
    assert validate_fixture(later) == later.receipt
    assert first.receipt.registration_result.is_current is True
    assert later.receipt.registration_result.is_current is False
    with pytest.raises(ValueError):
        validate_local_embedding_step_output(first.output, later.receipt)
    assert local_embedding_workflow_receipt_bytes(first.receipt) == before


def test_maximum_count_is_small_metadata_not_a_binding_array_or_scope_grant() -> None:
    fixture = receipt_fixture()
    body = fixture.receipt.model_dump(mode="json")
    body["registration_command"].update(eligible_source_count=1024, binding_count=1024)
    receipt = parse_local_embedding_workflow_receipt(reseal_receipt(body))
    assert len(local_embedding_workflow_receipt_bytes(receipt)) < 64 * 1024
    assert "bindings" not in receipt.model_dump(mode="json")
    with pytest.raises(ValueError, match="resolved Workflow context"):
        validate_fixture(fixture, receipt)


@pytest.mark.parametrize(
    "field", ["operation_key", "index_id", "index_revision_id", "index_sha256"]
)
def test_resealed_forged_registration_result_does_not_match_its_command(field: str) -> None:
    body = receipt_fixture().receipt.model_dump(mode="json")
    result = body["registration_result"]
    result[field] = (
        "synthetic-forged-operation"
        if field == "operation_key"
        else sha("0")
        if field == "index_sha256"
        else result[field].split("_")[0] + "_" + "0" * 32
    )
    result = seal(result, "result_sha256")
    body["registration_result"] = result
    with pytest.raises(LocalEmbeddingAdmissionContractError):
        parse_local_embedding_workflow_receipt(seal(body, "receipt_sha256"))


def test_copied_runtime_recipe_in_resolved_context_is_not_already_validated() -> None:
    fixture = receipt_fixture()
    native = fixture.native
    request = native.request.model_copy(
        update={
            "resource_profile": native.request.resource_profile.model_copy(update={"threads": True})
        }
    )
    with pytest.raises((ValueError, ValidationError)):
        validate_local_embedding_workflow_receipt(
            fixture.receipt,
            request,
            native.plan,
            native.policy,
            workflow_id=fixture.receipt.workflow_id,
            step_run_id=fixture.receipt.step_run_id,
            receipt_owner_job_id=fixture.receipt.receipt_owner_job_id,
            launch_association=native.association,
            owned_input=native.native_input,
        )


def test_no_zero_demand_receipt_and_no_nullable_association_bypass() -> None:
    fixture = receipt_fixture(borrowed_only=True)
    native = fixture.native
    plan_body = native.plan.model_dump(mode="json")
    plan_body.update(
        demands=[],
        missing_solution_report_revision_ids=[s.item_revision_id for s in native.plan.sources],
        encoding_set_sha256=embedding_input_set_sha256(()),
    )
    plan = type(native.plan).model_validate(seal(plan_body, "plan_sha256"))
    request_body = native.request.model_dump(mode="json")
    request_body.update(
        source_plan=member(
            "source-plan.json",
            native.request.source_plan.schema_ref,
            plan.model_dump(mode="json"),
            "2",
        ).model_dump(mode="json"),
        source_plan_sha256=plan.plan_sha256,
    )
    request = type(native.request).model_validate(seal(request_body, "request_sha256"))
    body = fixture.receipt.model_dump(mode="json")
    body.update(
        workflow_request_sha256=request.request_sha256,
        source_plan=request.source_plan.model_dump(mode="json"),
        source_plan_sha256=plan.plan_sha256,
    )
    receipt = parse_local_embedding_workflow_receipt(reseal_receipt(body))
    with pytest.raises(ValueError, match="resolved Workflow context"):
        validate_local_embedding_workflow_receipt(
            receipt,
            request,
            plan,
            native.policy,
            workflow_id=receipt.workflow_id,
            step_run_id=receipt.step_run_id,
            receipt_owner_job_id=receipt.receipt_owner_job_id,
            launch_association=None,
            owned_input=None,
        )
    with pytest.raises(ValueError):
        validate_fixture(fixture)


def test_original_association_generation_is_audit_not_current_recovery_authority() -> None:
    fixture = receipt_fixture()
    native = fixture.native
    intent = seal(
        native.association.intent.model_dump(mode="json") | {"lease_generation": 2}, "intent_sha256"
    )
    association = type(native.association).model_validate(
        seal(native.association.model_dump(mode="json") | {"intent": intent}, "association_sha256")
    )
    with pytest.raises(ValueError, match="original launch association"):
        validate_local_embedding_workflow_receipt(
            fixture.receipt,
            native.request,
            native.plan,
            native.policy,
            workflow_id=fixture.receipt.workflow_id,
            step_run_id=fixture.receipt.step_run_id,
            receipt_owner_job_id=fixture.receipt.receipt_owner_job_id,
            launch_association=association,
            owned_input=native.native_input,
        )
    # No current command/token parameter is present: the original association is
    # retained provenance only; actual linked recovery still needs its owner gate.
    assert validate_fixture(fixture) == fixture.receipt


@pytest.mark.parametrize(
    "kind,maximum", [("step-output", 8 * 1024), ("workflow-receipt", 64 * 1024)]
)
def test_byte_cap_precedes_schema_construction(
    kind: str, maximum: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = receipt_fixture()
    body = (fixture.output if kind == "step-output" else fixture.receipt).model_dump(mode="json")
    body["padding"] = "x" * maximum

    def unexpected(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("oversized metadata reached schema construction")

    monkeypatch.setattr("eom_workflow.schemas.Draft202012Validator", unexpected)
    with pytest.raises(
        LocalEmbeddingAdmissionContractError, match="LOCAL_EMBEDDING_CONTRACT_INVALID"
    ):
        validate_local_embedding_receipt_message(cast(LocalEmbeddingReceiptSchemaName, kind), body)


@pytest.mark.parametrize(
    "extra", ["role", "lease_token", "current_authority", "bindings", "vectors", "source_text"]
)
def test_closed_receipt_has_no_authority_payload_or_complete_binding_blob(extra: str) -> None:
    body = receipt_fixture().receipt.model_dump(mode="json") | {extra: "synthetic"}
    with pytest.raises(LocalEmbeddingAdmissionContractError):
        parse_local_embedding_workflow_receipt(body)


@pytest.mark.parametrize("kind", ["step-output", "workflow-receipt"])
@pytest.mark.parametrize("invalid_tree", ["depth", "cycle", "object", "collection"])
def test_direct_message_limits_precede_any_canonical_serialization(
    kind: str, invalid_tree: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    value: dict[str, Any] = {}
    if invalid_tree == "depth":
        for _ in range(34):
            value = {"nested": value}
    elif invalid_tree == "cycle":
        value["self"] = value
    elif invalid_tree == "object":
        value = {str(number): number for number in range(65)}
    else:
        value = {"items": list(range(1025))}
    calls = 0

    def unexpected(*_args: object, **_kwargs: object) -> bytes:
        nonlocal calls
        calls += 1
        raise AssertionError("unbounded value reached canonical serializer")

    monkeypatch.setattr("eom_workflow.schemas.canonical_json_bytes", unexpected)
    with pytest.raises(
        LocalEmbeddingAdmissionContractError, match="LOCAL_EMBEDDING_CONTRACT_INVALID"
    ):
        validate_local_embedding_receipt_message(cast(LocalEmbeddingReceiptSchemaName, kind), value)
    assert calls == 0


def test_contract_dependency_direction_has_no_runtime_or_storage_import() -> None:
    source = (
        ROOT / "packages/workflow/eom_workflow/local_embedding_workflow_receipt.py"
    ).read_text()
    tree = ast.parse(source)
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any(
        name
        and name.startswith(
            (
                "eom_orchestrator",
                "eom_catalog_service",
                "eom_identity_service",
                "sqlalchemy",
                "torch",
                "subprocess",
            )
        )
        for name in imports
    )
