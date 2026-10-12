"""Protocol-only invariants; no database, source authorization, model or GPU work."""

from __future__ import annotations

import ast
import copy
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest
from eom_catalog_contracts.inference_transfer_embedding import embedding_input_set_sha256
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow import (
    EmbeddingEncodingAttachedEvent,
    EmbeddingEncodingCompletedEvent,
    EmbeddingEncodingJobOwnerPort,
    EmbeddingEncodingReadResult,
    LocalEmbeddingLaunchAssociation,
    LocalEmbeddingResourceProfile,
    parse_embedding_encoding_job_message,
    parse_local_embedding_execution_policy,
    parse_local_embedding_source_plan,
    parse_local_embedding_workflow_request_v11,
    require_local_embedding_operator_seed,
    schemas,
    validate_embedding_encoding_completion,
    validate_local_embedding_launch_association,
    validate_local_embedding_plan_entries,
    validate_local_embedding_request_references,
    validate_local_embedding_runtime_profile,
)
from eom_workflow.schemas import (
    LOCAL_EMBEDDING_SCHEMA_RESOURCES,
    LocalEmbeddingAdmissionContractError,
    LocalEmbeddingSchemaName,
    load_local_embedding_admission_schema,
    local_embedding_admission_schema_registry,
    validate_local_embedding_admission_message,
)
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import sha
from tests.unit.inference_transfer_snapshot_fixtures import snapshot_v3_record
from tests.unit.local_embedding_admission_fixtures import native_fixture, resources, runtime_profile
from tests.unit.test_embedding_runtime_bundle_contracts import _bundle

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name,filename,schema_id,expected", LOCAL_EMBEDDING_SCHEMA_RESOURCES)
def test_closed_schema_mirror_and_registered_identity(
    name: str, filename: str, schema_id: str, expected: str
) -> None:
    canonical = (ROOT / "schemas/workflow" / filename).read_bytes()
    packaged = (ROOT / "packages/workflow/eom_workflow/resources" / filename).read_bytes()
    assert canonical == packaged
    assert sha256_bytes(canonical) == expected
    schema = load_local_embedding_admission_schema(cast(LocalEmbeddingSchemaName, name))
    assert schema["$id"] == schema_id
    Draft202012Validator.check_schema(schema)
    schema["title"] = "synthetic caller mutation"
    assert (
        load_local_embedding_admission_schema(cast(LocalEmbeddingSchemaName, name))["title"]
        != schema["title"]
    )
    assert local_embedding_admission_schema_registry().contents(schema_id)["$id"] == schema_id
    local_embedding_admission_schema_registry().contents(schema_id)["type"] = "null"
    assert (
        load_local_embedding_admission_schema(cast(LocalEmbeddingSchemaName, name)).get("type")
        != "null"
    )


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
def test_exact_protocol_roundtrip_and_control_runtime_closure(device: Any) -> None:
    f = native_fixture(device=device)
    assert (
        parse_local_embedding_workflow_request_v11(f.request.model_dump(mode="json")) == f.request
    )
    assert parse_local_embedding_execution_policy(f.policy.model_dump(mode="json")) == f.policy
    assert parse_local_embedding_source_plan(f.plan.model_dump(mode="json")) == f.plan
    validate_local_embedding_request_references(f.request, f.plan, f.policy)
    validate_local_embedding_runtime_profile(f.policy.profiles[0], _bundle(device))
    validate_local_embedding_plan_entries(f.plan, f.entries)
    validate_local_embedding_launch_association(
        f.association, f.plan, f.native_input, f.request.resource_profile, f.request.request_sha256
    )
    assert (
        parse_embedding_encoding_job_message(f.association.model_dump(mode="json")) == f.association
    )
    for event in f.completions:
        assert parse_embedding_encoding_job_message(event.model_dump(mode="json")) == event
        validate_embedding_encoding_completion(event, f.association, f.native_input, f.result)
        assert (
            event.owned_job.job_reference.allocated_artifact_id
            != event.receipt.result_manifest.artifact_id
        )
    assert f.request.resource_profile.memory_max_bytes == 6 * 1024**3
    assert f.request.resource_profile.gpu_vram_max_bytes == (8 * 1024**3 if device == "CUDA" else 0)


@pytest.mark.parametrize(
    "field,value",
    [
        ("threads", True),
        ("batch_size", 1.0),
        ("maximum_active_launches", True),
        ("maximum_active_launches", 2),
        ("memory_max_bytes", "6442450944"),
        ("timeout_seconds", 1801),
        ("tasks_max", 65),
        ("cpu_quota_percent", 0),
        ("gpu_vram_max_bytes", 8 * 1024**3 + 1),
        ("network", "ENABLED"),
        ("physical_gpu_lease", "NONE"),
        ("output_max_bytes", 64 * 1024**2 + 1),
    ],
)
def test_resource_profile_strict_values(field: str, value: object) -> None:
    body = resources("CUDA").model_dump(mode="json")
    body[field] = value
    with pytest.raises((ValidationError, ValueError)):
        LocalEmbeddingResourceProfile.model_validate(
            body if isinstance(value, float) else seal(body, "resource_profile_sha256")
        )


@pytest.mark.parametrize(
    "field,value", [("gpu_vram_max_bytes", 4), ("physical_gpu_lease", "SHARED_GPU0")]
)
def test_cpu_profile_cannot_claim_gpu(field: str, value: object) -> None:
    body = resources().model_dump(mode="json")
    body[field] = value
    with pytest.raises(ValidationError):
        LocalEmbeddingResourceProfile.model_validate(seal(body, "resource_profile_sha256"))


@pytest.mark.parametrize(
    "mutation",
    [
        "default",
        "duplicate",
        "order",
        "device",
        "query",
        "timestamp",
        "hash",
        "service",
        "fallback",
    ],
)
def test_policy_closed_semantic_errors(mutation: str) -> None:
    f = native_fixture()
    body = f.policy.model_dump(mode="json")
    if mutation == "default":
        body["default_device"] = "CUDA"
    elif mutation == "duplicate":
        body["profiles"] *= 2
    elif mutation == "order":
        body["profiles"].insert(0, runtime_profile("CUDA").model_dump(mode="json"))
    elif mutation == "device":
        body["profiles"][0]["resource_profile"] = resources("CUDA").model_dump(mode="json")
    elif mutation == "query":
        body["profiles"][0]["space"]["purpose"] = "QUERY"
        body["profiles"][0]["space"] = seal(body["profiles"][0]["space"], "space_sha256")
    elif mutation == "timestamp":
        body["created_at"] = "2026-10-12T00:00:00+09:00"
    elif mutation == "service":
        body["admission_mode"] = "BACKGROUND_SERVICE"
    elif mutation == "fallback":
        body["gpu_busy"] = "FALLBACK_CPU"
    body = seal(body, "policy_sha256")
    if mutation == "hash":
        body["policy_sha256"] = sha("f")
    with pytest.raises(
        LocalEmbeddingAdmissionContractError, match="LOCAL_EMBEDDING_CONTRACT_INVALID"
    ):
        parse_local_embedding_execution_policy(body)


def test_sorted_dual_policy_may_pin_gpu_default_without_claiming_activation() -> None:
    body = native_fixture().policy.model_dump(mode="json")
    body["profiles"].append(runtime_profile("CUDA").model_dump(mode="json"))
    body["default_device"] = "CUDA"
    assert (
        parse_local_embedding_execution_policy(seal(body, "policy_sha256")).default_device == "CUDA"
    )


def test_runtime_bundle_batch_recipe_is_not_overridden_by_profile() -> None:
    profile = runtime_profile()
    body = profile.model_dump(mode="json")
    body["resource_profile"]["batch_size"] = 2
    body["resource_profile"] = seal(body["resource_profile"], "resource_profile_sha256")
    with pytest.raises(ValueError, match="numerical recipe"):
        validate_local_embedding_runtime_profile(type(profile).model_validate(body), _bundle("CPU"))


@pytest.mark.parametrize("constructed", [False, True])
def test_runtime_profile_copied_or_constructed_bool_int_is_revalidated(constructed: bool) -> None:
    profile = runtime_profile()
    resources = profile.resource_profile
    broken_resource = (
        type(resources).model_construct(**(resources.__dict__ | {"maximum_active_launches": True}))
        if constructed
        else resources.model_copy(update={"maximum_active_launches": True})
    )
    broken = profile.model_copy(update={"resource_profile": broken_resource})
    with pytest.raises(ValueError):
        validate_local_embedding_runtime_profile(broken, _bundle("CPU"))


@pytest.mark.parametrize("constructed", [False, True])
def test_runtime_bundle_copied_or_constructed_recipe_is_revalidated(constructed: bool) -> None:
    bundle = _bundle("CPU")
    recipe = bundle.numerical_runtime.recipe
    broken_recipe = (
        type(recipe).model_construct(**(recipe.__dict__ | {"threads": True}))
        if constructed
        else recipe.model_copy(update={"threads": True})
    )
    broken_runtime = bundle.numerical_runtime.model_copy(update={"recipe": broken_recipe})
    broken = bundle.model_copy(update={"numerical_runtime": broken_runtime})
    with pytest.raises(ValueError):
        validate_local_embedding_runtime_profile(runtime_profile(), broken)


def test_owner_request_helper_does_not_serialize_copied_bool_into_a_grant() -> None:
    f = native_fixture()
    broken = f.request.model_copy(
        update={
            "resource_profile": f.request.resource_profile.model_copy(
                update={"maximum_active_launches": True}
            )
        }
    )
    with pytest.raises(ValueError):
        require_local_embedding_operator_seed(broken)
    with pytest.raises(ValueError):
        validate_local_embedding_request_references(broken, f.plan, f.policy)


def test_native_raw_value_tree_has_nesting_collection_and_integer_only_bounds() -> None:
    resource = resources()
    nested: Any = {"foreign": "synthetic"}
    for _ in range(34):
        nested = {"foreign": nested}
    with pytest.raises(ValueError):
        type(resource).model_validate(resource.__dict__ | {"foreign": nested})
    with pytest.raises(ValueError):
        type(resource).model_validate(resource.__dict__ | {"foreign": [0] * 1025})
    with pytest.raises(ValueError):
        type(resource).model_validate(resource.__dict__ | {"batch_size": 1.0})
    with pytest.raises(ValueError):
        type(resource).model_validate(resource.__dict__ | {"foreign": {1, 2}})


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "foreign",
        "order",
        "coverage_overlap",
        "space",
        "recipe",
        "partition",
        "source_hash",
        "encoding_set",
        "graph",
        "occurrence",
        "hash",
    ],
)
def test_source_plan_rejects_inexact_coverage_and_pins(mutation: str) -> None:
    body = native_fixture().plan.model_dump(mode="json")
    if mutation == "missing":
        body["demands"].pop()
    elif mutation == "duplicate":
        body["demands"].append(copy.deepcopy(body["demands"][0]))
    elif mutation == "foreign":
        body["demands"][0]["source_revision_id"] = "itemrev_" + "e" * 32
    elif mutation == "order":
        body["sources"].reverse()
    elif mutation == "coverage_overlap":
        body["missing_solution_report_revision_ids"] = [body["demands"][0]["source_revision_id"]]
    elif mutation == "space":
        body["namespace"]["space_sha256"] = sha("f")
    elif mutation == "recipe":
        body["namespace"]["recipe_sha256"] = sha("f")
    elif mutation == "partition":
        body["demands"][0]["encoding"]["storage_partition"] = "foreign-partition"
        body["demands"][0]["encoding"] = seal(body["demands"][0]["encoding"], "encoding_sha256")
    elif mutation == "source_hash":
        body["source_set_sha256"] = sha("f")
    elif mutation == "encoding_set":
        body["encoding_set_sha256"] = sha("f")
    elif mutation == "graph":
        body["graph_snapshot"]["manifest_sha256"] = sha("f")
    elif mutation == "occurrence":
        body["namespace"]["population_scope"] = "OCCURRENCE_BACKED_PAST_EXAM"
    body = seal(body, "plan_sha256")
    if mutation == "hash":
        body["plan_sha256"] = sha("f")
    with pytest.raises(LocalEmbeddingAdmissionContractError):
        parse_local_embedding_source_plan(body)


def test_missing_report_and_unavailable_view_are_explicit_not_fake_demands() -> None:
    body = native_fixture().plan.model_dump(mode="json")
    first, second = body.pop("demands")
    body["demands"] = []
    body["missing_solution_report_revision_ids"] = [first["source_revision_id"]]
    body["unavailable_views"] = [
        {"source_revision_id": second["source_revision_id"], "reason": "EMPTY_VIEW"}
    ]
    body["encoding_set_sha256"] = embedding_input_set_sha256(())
    plan = parse_local_embedding_source_plan(seal(body, "plan_sha256"))
    assert plan.demands == ()
    assert plan.missing_solution_report_revision_ids
    validate_local_embedding_plan_entries(plan, ())


def test_multiple_sources_may_reference_one_computational_encoding() -> None:
    body = native_fixture().plan.model_dump(mode="json")
    body["demands"][1]["encoding"] = copy.deepcopy(body["demands"][0]["encoding"])
    body["encoding_set_sha256"] = content_sha256([body["demands"][0]["encoding"]])
    plan = parse_local_embedding_source_plan(seal(body, "plan_sha256"))
    assert len(plan.demands) == 2


def test_occurrence_namespace_retains_full_v3_but_profile_core_remains_v2() -> None:
    f, record = native_fixture("a"), snapshot_v3_record()
    assert record.staged_entry is not None
    body = f.plan.model_dump(mode="json")
    body["sources"] = [record.source.model_dump(mode="json")]
    body["source_set_sha256"] = content_sha256(body["sources"])
    body["namespace"]["population_scope"] = "OCCURRENCE_BACKED_PAST_EXAM"
    body["demands"][0]["profile"] = (
        record.index_entry.profile.model_dump(mode="json") if record.index_entry.profile else None
    )
    body["demands"][0]["solution_evidence"] = (
        record.staged_entry.profile.source_basis.solution_evidence.model_dump(mode="json")
    )
    plan = parse_local_embedding_source_plan(seal(body, "plan_sha256"))
    assert "page_inputs" in plan.sources[0].model_dump(mode="json")
    assert "page_inputs" not in record.staged_entry.profile.source_basis.source.model_dump(
        mode="json"
    )
    validate_local_embedding_plan_entries(plan, (record.staged_entry,))


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "source", "profile", "report", "graph", "text", "projection"],
)
def test_entry_closure_requires_exact_profile_source_report_view(mutation: str) -> None:
    f = native_fixture()
    entries = f.entries
    if mutation == "missing":
        entries = entries[:1]
    elif mutation == "duplicate":
        entries = (entries[0], entries[0])
    else:
        body = entries[0].model_dump(mode="json")
        if mutation == "source":
            body["profile"]["source_basis"]["source"]["item_id"] = "item_" + "f" * 32
        elif mutation == "profile":
            body["profile"]["profile_revision_id"] = "inferenceprofilerev_" + "f" * 32
        elif mutation == "report":
            evidence = body["profile"]["source_basis"]["solution_evidence"]
            evidence["solution_report"]["sha256"] = sha("f")
            body["profile"]["source_basis"]["solution_evidence"] = seal(evidence, "pointer_sha256")
        elif mutation == "graph":
            body["profile"]["source_basis"]["graph_snapshot"]["graph_id"] = "graph_" + "f" * 32
        elif mutation == "text":
            body["content"]["text"] = "synthetic changed view"
            body["content"]["text_sha256"] = content_sha256(body["content"]["text"])
        elif mutation == "projection":
            body["profile"]["extraction"]["extractor_version"] = "foreign/1.0"
        body["profile"] = seal(body["profile"], "profile_sha256")
        # The helper must also reject model_construct/copy bypasses, not just parsed entries.
        entries = (entries[0].model_construct(**body), entries[1])
    with pytest.raises(ValueError):
        validate_local_embedding_plan_entries(f.plan, entries)


def test_service_audit_is_parseable_but_explicitly_unavailable() -> None:
    f = native_fixture()
    body = f.request.model_dump(mode="json")
    body["actor_context"] = {
        "kind": "LOCAL_INDEXING_SERVICE",
        "service_id": "localindexservice_" + "1" * 32,
        "service_revision_id": "localindexservicerev_" + "2" * 32,
        "service_identity_sha256": sha("1"),
        "service_policy_revision_id": "accessrev_" + "2" * 32,
        "service_policy_sha256": sha("2"),
        "authorization_audit_sha256": sha("3"),
    }
    request = parse_local_embedding_workflow_request_v11(seal(body, "request_sha256"))
    with pytest.raises(
        LocalEmbeddingAdmissionContractError, match=r"^LOCAL_EMBEDDING_SERVICE_UNAVAILABLE$"
    ):
        require_local_embedding_operator_seed(request)
    assert require_local_embedding_operator_seed(f.request).operator_id == "operator_" + "1" * 32


@pytest.mark.parametrize(
    "field", ["source_plan_sha256", "native_execution_policy_sha256", "workflow_definition_sha256"]
)
def test_request_control_semantic_hashes_are_not_raw_member_hashes(field: str) -> None:
    f = native_fixture()
    body = f.request.model_dump(mode="json")
    body[field] = sha("f")
    changed = parse_local_embedding_workflow_request_v11(seal(body, "request_sha256"))
    with pytest.raises(ValueError):
        validate_local_embedding_request_references(changed, f.plan, f.policy)


@pytest.mark.parametrize(
    "pointer,field,value",
    [
        ("source_plan", "member_path", "input.json"),
        (
            "native_execution_policy",
            "schema_ref",
            "eom://schemas/workflow/local-embedding-execution-policy/2.0",
        ),
        ("source_plan", "media_type", "text/plain"),
        ("source_plan", "member_path", "../source-plan.json"),
    ],
)
def test_control_member_pins_are_fixed(pointer: str, field: str, value: str) -> None:
    body = native_fixture().request.model_dump(mode="json")
    body[pointer][field] = value
    with pytest.raises(LocalEmbeddingAdmissionContractError):
        parse_local_embedding_workflow_request_v11(seal(body, "request_sha256"))


def test_raw_control_mismatch_does_not_substitute_latest_or_semantic_hash() -> None:
    f = native_fixture()
    body = f.request.model_dump(mode="json")
    body["source_plan"]["sha256"] = f.plan.plan_sha256
    changed = parse_local_embedding_workflow_request_v11(seal(body, "request_sha256"))
    with pytest.raises(ValueError):
        validate_local_embedding_request_references(changed, f.plan, f.policy)


@pytest.mark.parametrize(
    "field,value",
    [
        ("corpus_id", "corpus_" + "f" * 32),
        ("access_policy_revision_id", "accessrev_" + "f" * 32),
        ("access_policy_sha256", sha("f")),
    ],
)
def test_request_scope_must_equal_exact_source_plan(field: str, value: str) -> None:
    f = native_fixture()
    body = f.request.model_dump(mode="json")
    body[field] = value
    changed = parse_local_embedding_workflow_request_v11(seal(body, "request_sha256"))
    with pytest.raises(ValueError):
        validate_local_embedding_request_references(changed, f.plan, f.policy)


def test_parseable_large_budget_is_not_an_owner_policy_grant() -> None:
    f = native_fixture()
    body = f.request.model_dump(mode="json")
    body["resource_profile"]["memory_max_bytes"] = 32 * 1024**3
    body["resource_profile"] = seal(body["resource_profile"], "resource_profile_sha256")
    changed = parse_local_embedding_workflow_request_v11(seal(body, "request_sha256"))
    assert changed.resource_profile.memory_max_bytes == 32 * 1024**3
    with pytest.raises(ValueError):
        validate_local_embedding_request_references(changed, f.plan, f.policy)


def test_overlap_has_one_exact_computational_key_and_separate_original_plans() -> None:
    ab, bc = native_fixture("a", "b"), native_fixture("b", "c")
    left = {
        job.request.encoding.input_text_sha256: job.request for job in ab.association.owned_jobs
    }
    right = {
        job.request.encoding.input_text_sha256: job.request for job in bc.association.owned_jobs
    }
    shared = set(left) & set(right)
    assert len(shared) == 1
    key = next(iter(shared))
    assert left[key] == right[key]
    assert left[key].idempotency_key == "embedding-encode:" + left[key].encoding.encoding_sha256
    assert ab.plan.plan_sha256 != bc.plan.plan_sha256
    subset = native_fixture("b", "c", owned_seeds=("c",))
    assert len(subset.plan.demands) == 2 and len(subset.association.owned_jobs) == 1
    validate_local_embedding_launch_association(
        subset.association,
        subset.plan,
        subset.native_input,
        subset.request.resource_profile,
        subset.request.request_sha256,
    )
    assert subset.association.owned_input_set_sha256 != subset.plan.encoding_set_sha256


@pytest.mark.parametrize(
    "mutation",
    [
        "order",
        "duplicate",
        "job",
        "allocation",
        "launch",
        "input_set",
        "input_path",
        "hash",
        "attempt",
        "generation",
        "credential",
    ],
)
def test_owned_launch_closed_identity_and_fence_audit(mutation: str) -> None:
    body = native_fixture().association.model_dump(mode="json")
    if mutation == "order":
        body["owned_jobs"].reverse()
    elif mutation == "duplicate":
        body["owned_jobs"].append(copy.deepcopy(body["owned_jobs"][0]))
    elif mutation == "job":
        body["owned_jobs"][1]["job_reference"]["job_id"] = body["owned_jobs"][0]["job_reference"][
            "job_id"
        ]
    elif mutation == "allocation":
        body["owned_jobs"][1]["job_reference"]["allocated_artifact_id"] = body["owned_jobs"][0][
            "job_reference"
        ]["allocated_artifact_id"]
    elif mutation == "launch":
        body["intent"]["native_launch_job_id"] = body["owned_jobs"][0]["job_reference"]["job_id"]
    elif mutation == "input_set":
        body["owned_input_set_sha256"] = sha("f")
    elif mutation == "input_path":
        body["owned_input"]["member_path"] = "source-plan.json"
    elif mutation == "attempt":
        body["intent"]["attempt"] = True
    elif mutation == "generation":
        body["intent"]["lease_generation"] = 0
    elif mutation == "credential":
        body["intent"]["lease_token"] = "synthetic-forbidden-credential-field"
    body["intent"] = seal(body["intent"], "intent_sha256")
    body = seal(body, "association_sha256")
    if mutation == "hash":
        body["association_sha256"] = sha("f")
    with pytest.raises(LocalEmbeddingAdmissionContractError):
        parse_embedding_encoding_job_message(body)


@pytest.mark.parametrize(
    "field", ["source_plan_sha256", "workflow_request_sha256", "resource_profile_sha256"]
)
def test_owned_launch_requires_original_exact_control_intent(field: str) -> None:
    f = native_fixture()
    body = f.association.model_dump(mode="json")
    body["intent"][field] = sha("f")
    body["intent"] = seal(body["intent"], "intent_sha256")
    changed = LocalEmbeddingLaunchAssociation.model_validate(seal(body, "association_sha256"))
    with pytest.raises(ValueError):
        validate_local_embedding_launch_association(
            changed, f.plan, f.native_input, f.request.resource_profile, f.request.request_sha256
        )


@pytest.mark.parametrize(
    "mutation",
    ["file_set", "row_shard", "reservation_allocation", "foreign_encoding", "wrong_launch", "hash"],
)
def test_completion_rejects_conflated_allocations_and_shared_pointers(mutation: str) -> None:
    body = native_fixture().completions[0].model_dump(mode="json")
    receipt = body["receipt"]
    if mutation == "file_set":
        receipt["binary_member"]["artifact_revision_id"] = "rev_" + "e" * 32
    elif mutation == "row_shard":
        receipt["row_ref"]["shard_manifest"]["sha256"] = sha("f")
    elif mutation == "reservation_allocation":
        body["owned_job"]["job_reference"]["allocated_artifact_id"] = receipt["result_manifest"][
            "artifact_id"
        ]
    elif mutation == "foreign_encoding":
        receipt["row_ref"]["encoding_sha256"] = sha("f")
    elif mutation == "wrong_launch":
        receipt["native_launch_job_id"] = "job_" + "f" * 32
    body["receipt"] = seal(receipt, "receipt_sha256")
    body = seal(body, "event_sha256")
    if mutation == "hash":
        body["event_sha256"] = sha("f")
    with pytest.raises(LocalEmbeddingAdmissionContractError):
        parse_embedding_encoding_job_message(body)


@pytest.mark.parametrize(
    "mutation",
    [
        "row_index",
        "result_raw",
        "result_semantic",
        "shard_raw",
        "shard_semantic",
        "binary",
        "association",
    ],
)
def test_completion_reparse_then_actual_result_closure(mutation: str) -> None:
    f = native_fixture()
    body = f.completions[0].model_dump(mode="json")
    receipt = body["receipt"]
    if mutation == "row_index":
        receipt["row_ref"]["row_index"] = 2
    elif mutation == "result_raw":
        receipt["result_manifest"]["sha256"] = f.result.result_sha256
    elif mutation == "result_semantic":
        receipt["result_sha256"] = receipt["result_manifest"]["sha256"]
    elif mutation == "shard_raw":
        receipt["shard_manifest"]["sha256"] = f.result.shard.shard_sha256
        receipt["row_ref"]["shard_manifest"] = copy.deepcopy(receipt["shard_manifest"])
    elif mutation == "shard_semantic":
        receipt["shard_sha256"] = receipt["shard_manifest"]["sha256"]
    elif mutation == "binary":
        receipt["binary_member"]["sha256"] = sha("f")
    elif mutation == "association":
        body["launch_association_sha256"] = sha("f")
    body["receipt"] = seal(receipt, "receipt_sha256")
    changed = EmbeddingEncodingCompletedEvent.model_validate(seal(body, "event_sha256"))
    with pytest.raises(ValueError):
        validate_embedding_encoding_completion(changed, f.association, f.native_input, f.result)


@pytest.mark.parametrize(
    "status", ["OWNED", "BORROWED", "COMPLETED", "FAILED", "CANCELLED", "UNCERTAIN"]
)
def test_closed_job_read_result_keeps_original_allocation_and_pointer_receipt(status: Any) -> None:
    f = native_fixture()
    event = f.completions[0]
    body = seal(
        {
            "schema_version": "embedding-encoding-job/1.0",
            "record_type": "READ_RESULT",
            "owned_job": event.owned_job.model_dump(mode="json"),
            "owner_intent": event.intent.model_dump(mode="json"),
            "status": status,
            "completion": event.model_dump(mode="json") if status == "COMPLETED" else None,
        },
        "read_sha256",
    )
    parsed = parse_embedding_encoding_job_message(body)
    assert isinstance(parsed, EmbeddingEncodingReadResult)
    assert parsed.owned_job.job_reference == event.owned_job.job_reference
    body["completion"] = None if status == "COMPLETED" else event.model_dump(mode="json")
    with pytest.raises(LocalEmbeddingAdmissionContractError):
        parse_embedding_encoding_job_message(seal(body, "read_sha256"))


def test_attachment_event_and_io_free_owner_port_are_not_an_implementation() -> None:
    f = native_fixture()
    body = seal(
        {
            "schema_version": "embedding-encoding-job/1.0",
            "record_type": "ATTACHED",
            "owned_job": f.association.owned_jobs[0].model_dump(mode="json"),
            "intent": f.association.intent.model_dump(mode="json"),
        },
        "event_sha256",
    )
    assert isinstance(parse_embedding_encoding_job_message(body), EmbeddingEncodingAttachedEvent)
    with pytest.raises(TypeError):
        cast(Any, EmbeddingEncodingJobOwnerPort)()


@pytest.mark.parametrize("model", ["request", "policy", "plan", "association"])
def test_frozen_instances_and_nested_copy_bypasses_are_revalidated(model: str) -> None:
    f = native_fixture()
    value = getattr(f, model)
    with pytest.raises(ValidationError):
        value.schema_version = "foreign"
    if model == "policy":
        broken = value.model_copy(
            update={
                "profiles": (
                    value.profiles[0].model_copy(
                        update={
                            "resource_profile": value.profiles[0].resource_profile.model_copy(
                                update={"threads": 0}
                            )
                        }
                    ),
                )
            }
        )
    elif model == "plan":
        broken = value.model_copy(update={"demands": ()})
    elif model == "association":
        broken = value.model_copy(
            update={"intent": value.intent.model_copy(update={"attempt": True})}
        )
    else:
        broken = value.model_copy(
            update={"space": value.space.model_copy(update={"space_sha256": sha("f")})}
        )
    with pytest.raises(ValueError):
        type(value).model_validate(broken)


@pytest.mark.parametrize(
    "family,attribute",
    [
        ("request", "request"),
        ("source-plan", "plan"),
        ("execution-policy", "policy"),
        ("encoding-job", "association"),
    ],
)
@pytest.mark.parametrize(
    "extra", ["authority", "worker_role", "storage_uri", "model_path", "source_text", "vectors"]
)
def test_closed_frames_reject_authority_paths_and_payloads_content_free(
    family: Any, attribute: str, extra: str
) -> None:
    body = getattr(native_fixture(), attribute).model_dump(mode="json")
    body[extra] = "synthetic-secret-marker-not-a-real-secret"
    with pytest.raises(LocalEmbeddingAdmissionContractError) as caught:
        validate_local_embedding_admission_message(family, body)
    assert str(caught.value) == "LOCAL_EMBEDDING_CONTRACT_INVALID"
    assert "synthetic-secret-marker" not in str(caught.value)


def test_installed_schema_hash_drift_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    class BadResource:
        def joinpath(self, name: str) -> BadResource:
            return self

        def open(self, mode: str) -> BytesIO:
            assert mode == "rb"
            return BytesIO(b'{"type":"object"}')

    schemas._local_embedding_admission_schema.cache_clear()
    schemas._local_embedding_admission_schema_registry.cache_clear()
    try:
        monkeypatch.setattr(schemas, "WORKFLOW_RESOURCE_ROOT", BadResource())
        with pytest.raises(
            LocalEmbeddingAdmissionContractError, match="LOCAL_EMBEDDING_SCHEMA_UNAVAILABLE"
        ):
            load_local_embedding_admission_schema("request")
    finally:
        schemas._local_embedding_admission_schema.cache_clear()
        schemas._local_embedding_admission_schema_registry.cache_clear()


def test_contract_dependency_direction_no_runtime_authority_or_behavior_imports() -> None:
    forbidden = {
        "sqlalchemy",
        "subprocess",
        "torch",
        "transformers",
        "eom_workflow_runner",
        "eom_orchestrator",
        "eom_catalog_service",
        "eom_identity_service",
        "socket",
        "requests",
    }
    for name in (
        "local_embedding_request",
        "local_embedding_source_plan",
        "local_embedding_encoding_job",
        "local_embedding_execution_policy",
    ):
        tree = ast.parse((ROOT / "packages/workflow/eom_workflow" / f"{name}.py").read_text())
        imports = {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        imports |= {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert not imports & forbidden
    body = native_fixture().plan.model_dump(mode="json")
    assert b'"text":' not in canonical_json_bytes(body)
    assert b'"vectors":' not in canonical_json_bytes(body)
    assert b'"row_ref":' not in canonical_json_bytes(body)
