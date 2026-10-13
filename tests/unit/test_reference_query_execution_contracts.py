"""Synthetic pointer closure; no authority, Job allocation or native execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta, timezone

import pytest
from eom_catalog_contracts.embedding_reference_query import (
    REFERENCE_QUERY_RESULT_REF,
    EmbeddingReferenceQueryResult,
    parse_embedding_reference_query_result,
)
from eom_catalog_contracts.embedding_reference_query_v11 import (
    REFERENCE_QUERY_INPUT_V11_REF,
    EmbeddingReferenceQueryInputV11,
    parse_embedding_reference_query_input_v11,
)
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingRuntimeBundle
from eom_catalog_contracts.inference_transfer_embedding import SHARD_SCHEMA_REF, EmbeddingSpace
from eom_catalog_contracts.models import FrozenModel
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow import (
    REFERENCE_QUERY_POLICY_REF,
    REFERENCE_QUERY_RECEIPT_REF,
    ReferenceQueryExecutionPolicy,
    ReferenceQueryLaunchAssociation,
    ReferenceQueryStepOutput,
    ReferenceQueryWorkflowReceipt,
    ReferenceQueryWorkflowRequest,
    parse_reference_query_execution_policy,
    parse_reference_query_launch_association,
    parse_reference_query_step_output,
    parse_reference_query_workflow_receipt,
    parse_reference_query_workflow_request,
    validate_reference_query_launch_association,
    validate_reference_query_request_references,
    validate_reference_query_step_output,
    validate_reference_query_workflow_receipt,
)

from tests.unit.inference_transfer_embedding_fixtures import encoding_identity, seal
from tests.unit.inference_transfer_fixtures import NOW, sha
from tests.unit.local_embedding_admission_fixtures import runtime_profile
from tests.unit.test_embedding_reference_query_v11_contracts import input_body, result_body
from tests.unit.test_embedding_runtime_bundle_contracts import _bundle
from tests.unit.test_similarity_context_contracts import context_request_body


def pointer(
    path: str, schema: str, digest: str, *, seed: str = "b", media: str = "application/json"
) -> ArtifactMemberPointer:
    return ArtifactMemberPointer(
        artifact_id="artifact_" + seed * 32,
        artifact_revision_id="rev_" + seed * 32,
        member_path=path,
        schema_ref=schema,
        media_type=media,
        sha256=digest,
    )


@dataclass(frozen=True)
class Case:
    bundle: EmbeddingRuntimeBundle
    policy: ReferenceQueryExecutionPolicy
    request: ReferenceQueryWorkflowRequest
    launch: ReferenceQueryLaunchAssociation
    native_input: EmbeddingReferenceQueryInputV11
    result: EmbeddingReferenceQueryResult
    receipt: ReferenceQueryWorkflowReceipt
    output: ReferenceQueryStepOutput


def case(*, definition_sha256: str | None = None) -> Case:
    profile, bundle = runtime_profile("CPU"), _bundle("CPU")
    query = EmbeddingSpace.model_validate(
        seal(profile.space.model_dump(mode="json") | {"purpose": "QUERY"}, "space_sha256")
    )
    spaces = {
        "query": query.model_dump(mode="json"),
        "document": profile.space.model_dump(mode="json"),
    }
    context = context_request_body()
    for index, view in enumerate(context["views"]):
        view["index"]["spaces"] = spaces
        view["index"]["index_id"] = "embeddingindex_" + str(index + 1) * 32
    context = seal(context, "request_sha256")
    policy = parse_reference_query_execution_policy(
        seal(
            {
                "schema_version": "reference-query-execution-policy/1.0",
                "purpose": "REFERENCE_QUERY",
                "continuation_mode": "OPERATOR_REQUEST_ONLY",
                "workflow_definition_sha256": definition_sha256 or sha("d"),
                "spaces": spaces,
                "runtime_bundle": profile.runtime_bundle.model_dump(mode="json"),
                "resource_profile": profile.resource_profile.model_dump(mode="json"),
                "gpu_busy": "WAIT",
                "created_at": NOW.isoformat().replace("+00:00", "Z"),
            },
            "policy_sha256",
        )
    )
    request = parse_reference_query_workflow_request(
        seal(
            {
                "schema_version": "reference-query-workflow-request/1.0",
                "request_name": "REFERENCE_QUERY_WORKFLOW_REQUEST",
                "purpose": "REFERENCE_QUERY",
                "workflow_definition_key": "local-embedding-reference-query",
                "workflow_definition_version": "1.0.0",
                "workflow_definition_sha256": definition_sha256 or sha("d"),
                "operator_audit": {
                    "kind": "OPERATOR",
                    "operator_id": "operator_" + "1" * 32,
                    "requester_permissions_sha256": sha("a"),
                },
                "context_request": context,
                "runtime_bundle": profile.runtime_bundle.model_dump(mode="json"),
                "resource_profile": profile.resource_profile.model_dump(mode="json"),
                "native_execution_policy": pointer(
                    "policy.json",
                    REFERENCE_QUERY_POLICY_REF,
                    sha256_bytes(canonical_json_bytes(policy.model_dump(mode="json"))),
                    seed="e",
                ).model_dump(mode="json"),
                "native_execution_policy_sha256": policy.policy_sha256,
            },
            "request_sha256",
        )
    )
    native = input_body()
    native["spaces"], native["threads"], native["context_request_sha256"] = (
        spaces,
        4,
        request.context_request.request_sha256,
    )
    for row in native["rows"]:
        row["encoding"] = encoding_identity(row["text"], query).model_dump(mode="json")
    native["input_set_sha256"] = content_sha256([row["encoding"] for row in native["rows"]])
    native_input = parse_embedding_reference_query_input_v11(seal(native, "request_sha256"))
    result = parse_embedding_reference_query_result(result_body(native_input))
    launch = parse_reference_query_launch_association(
        seal(
            {
                "schema_version": "reference-query-launch-association/1.0",
                "purpose": "REFERENCE_QUERY",
                "workflow_id": "workflow_" + "1" * 32,
                "step_run_id": "steprun_" + "1" * 32,
                "step_key": "encode_reference_query",
                "attempt": 1,
                "workflow_request_sha256": request.request_sha256,
                "context_request_sha256": request.context_request.request_sha256,
                "native_launch_job_id": native_input.job_id,
                "query_request_id": native_input.query_request_id,
                "query_request_sha256": native_input.request_sha256,
                "query_input_set_sha256": native_input.input_set_sha256,
                "recipe_sha256": native_input.recipe.recipe_sha256,
                "runtime_bundle": profile.runtime_bundle.model_dump(mode="json"),
                "resource_profile_sha256": profile.resource_profile.resource_profile_sha256,
                "original_command_id": "wfcmd_" + "1" * 32,
                "original_command_generation": 1,
                "launched_at": NOW.isoformat().replace("+00:00", "Z"),
            },
            "association_sha256",
        )
    )
    receipt = parse_reference_query_workflow_receipt(
        seal(
            {
                "schema_version": "reference-query-workflow-receipt/1.0",
                "purpose": "REFERENCE_QUERY",
                "workflow_id": launch.workflow_id,
                "workflow_definition_sha256": request.workflow_definition_sha256,
                "workflow_request_sha256": request.request_sha256,
                "context_request_sha256": request.context_request.request_sha256,
                "step_run_id": launch.step_run_id,
                "step_key": "encode_reference_query",
                "attempt": 1,
                "receipt_owner_job_id": "job_" + "c" * 32,
                "query_artifact_owner_job_id": "job_" + "b" * 32,
                "native_launch_job_id": native_input.job_id,
                "launch_association_sha256": launch.association_sha256,
                "execution_result_schema": "embedding-reference-query-result@1.0",
                "query_input": pointer(
                    "input.json",
                    REFERENCE_QUERY_INPUT_V11_REF,
                    sha256_bytes(canonical_json_bytes(native_input.model_dump(mode="json"))),
                ).model_dump(mode="json"),
                "query_execution": {
                    "job_id": native_input.job_id,
                    "query_request_id": native_input.query_request_id,
                    "request_sha256": native_input.request_sha256,
                    "input_set_sha256": native_input.input_set_sha256,
                    "result_member": pointer(
                        "result.json",
                        REFERENCE_QUERY_RESULT_REF,
                        sha256_bytes(canonical_json_bytes(result.model_dump(mode="json"))),
                    ).model_dump(mode="json"),
                    "result_sha256": result.result_sha256,
                },
                "shard": pointer(
                    "shard.json",
                    SHARD_SCHEMA_REF,
                    sha256_bytes(canonical_json_bytes(result.shard.model_dump(mode="json"))),
                ).model_dump(mode="json"),
                "binary": pointer(
                    "vectors.f32",
                    "eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0",
                    result.shard.binary.sha256,
                    media="application/octet-stream",
                ).model_dump(mode="json"),
                "runtime_bundle": profile.runtime_bundle.model_dump(mode="json"),
                "resource_profile_sha256": profile.resource_profile.resource_profile_sha256,
                "published_at": NOW.isoformat().replace("+00:00", "Z"),
            },
            "receipt_sha256",
        )
    )
    output = parse_reference_query_step_output(
        seal(
            {
                "schema_version": "reference-query-step-output/1.0",
                "purpose": "REFERENCE_QUERY",
                "workflow_id": launch.workflow_id,
                "step_run_id": launch.step_run_id,
                "step_key": "encode_reference_query",
                "attempt": 1,
                "receipt_owner_job_id": receipt.receipt_owner_job_id,
                "execution_result_schema": "embedding-reference-query-result@1.0",
                "receipt_schema": REFERENCE_QUERY_RECEIPT_REF,
                "receipt": pointer(
                    "receipt.json",
                    REFERENCE_QUERY_RECEIPT_REF,
                    sha256_bytes(canonical_json_bytes(receipt.model_dump(mode="json"))),
                    seed="c",
                ).model_dump(mode="json"),
                "receipt_sha256": receipt.receipt_sha256,
            },
            "output_sha256",
        )
    )
    return Case(bundle, policy, request, launch, native_input, result, receipt, output)


def checked_receipt(c: Case, receipt: ReferenceQueryWorkflowReceipt) -> None:
    validate_reference_query_workflow_receipt(
        receipt,
        c.request,
        c.policy,
        c.bundle,
        c.launch,
        c.native_input,
        c.result,
        workflow_id=c.launch.workflow_id,
        step_run_id=c.launch.step_run_id,
        query_artifact_owner_job_id=c.receipt.query_artifact_owner_job_id,
        receipt_owner_job_id=c.receipt.receipt_owner_job_id,
    )


def test_full_exact_pointer_hash_runtime_request_launch_receipt_carrier_closure() -> None:
    c = case()
    validate_reference_query_request_references(c.request, c.policy, c.bundle)
    validate_reference_query_launch_association(
        c.launch, c.request, c.policy, c.bundle, c.native_input
    )
    checked_receipt(c, c.receipt)
    validate_reference_query_step_output(c.output, c.receipt)
    assert c.native_input.batch_size == c.request.resource_profile.batch_size == 4
    assert c.native_input.threads == 4 and c.result.shard.row_count == 1
    assert c.output.receipt.sha256 != c.output.receipt_sha256


@pytest.mark.parametrize(
    "field",
    [
        "authority",
        "admitted",
        "approved",
        "token",
        "provider_capture",
        "source_path",
        "text",
        "vectors",
    ],
)
def test_all_fixed_frames_reject_extra_grants_paths_or_bodies(field: str) -> None:
    c = case()
    values: tuple[tuple[Callable[[object], FrozenModel], FrozenModel, str], ...] = (
        (parse_reference_query_workflow_request, c.request, "request_sha256"),
        (parse_reference_query_execution_policy, c.policy, "policy_sha256"),
        (parse_reference_query_launch_association, c.launch, "association_sha256"),
        (parse_reference_query_workflow_receipt, c.receipt, "receipt_sha256"),
        (parse_reference_query_step_output, c.output, "output_sha256"),
    )
    for parse, value, hashfield in values:
        document = seal(value.model_dump(mode="json") | {field: "untrusted"}, hashfield)
        with pytest.raises(ValueError):
            parse(document)
        with pytest.raises(ValueError):
            parse(value.model_copy(update={field: "untrusted"}))


@pytest.mark.parametrize(
    "field",
    ["definition", "policy_raw", "policy_semantic", "bundle", "resource", "context", "purpose"],
)
def test_controller_exact_policy_bundle_and_context_are_not_silently_substituted(
    field: str,
) -> None:
    c = case()
    body = c.request.model_dump(mode="json")
    if field == "definition":
        body["workflow_definition_sha256"] = sha("a")
    elif field == "policy_raw":
        body["native_execution_policy"]["sha256"] = sha("a")
    elif field == "policy_semantic":
        body["native_execution_policy_sha256"] = sha("a")
    elif field == "bundle":
        body["runtime_bundle"]["bundle_revision_id"] = "embeddingbundlerev_" + "f" * 32
    elif field == "resource":
        body["resource_profile"]["threads"] = 3
        body["resource_profile"] = seal(body["resource_profile"], "resource_profile_sha256")
    elif field == "context":
        body["context_request"]["views"][0]["index"]["index_revision_id"] = (
            "embeddingindexrev_" + "f" * 32
        )
        body["context_request"] = seal(body["context_request"], "request_sha256")
    else:
        body["context_request"]["consumer_purpose"] = "GENERAL_CHAT"
    with pytest.raises(ValueError):
        request = parse_reference_query_workflow_request(seal(body, "request_sha256"))
        validate_reference_query_launch_association(
            c.launch, request, c.policy, c.bundle, c.native_input
        )


@pytest.mark.parametrize(
    "field", ["request", "context", "input", "job", "recipe", "generation", "time"]
)
def test_launch_history_hashes_and_strict_scalars_are_not_new_permission(field: str) -> None:
    c = case()
    body = c.launch.model_dump(mode="json")
    key = {
        "request": "workflow_request_sha256",
        "context": "context_request_sha256",
        "input": "query_request_sha256",
        "job": "native_launch_job_id",
        "recipe": "recipe_sha256",
    }
    if field == "job":
        body[key[field]] = "job_" + "f" * 32
    elif field == "generation":
        body["original_command_generation"] = True
    elif field == "time":
        body["launched_at"] = (NOW - timedelta(seconds=1)).isoformat()
    else:
        body[key[field]] = sha("f")
    with pytest.raises(ValueError):
        launch = parse_reference_query_launch_association(seal(body, "association_sha256"))
        validate_reference_query_launch_association(
            launch, c.request, c.policy, c.bundle, c.native_input
        )


@pytest.mark.parametrize(
    "field",
    [
        "owner",
        "context",
        "association",
        "input_raw",
        "result_raw",
        "result_semantic",
        "shard_raw",
        "binary_raw",
        "foreign_artifact",
        "path",
        "schema",
        "media",
        "time",
    ],
)
def test_receipt_dangling_stale_hash_member_and_foreign_publication_fail_exact_closure(
    field: str,
) -> None:
    c = case()
    body = c.receipt.model_dump(mode="json")
    if field == "owner":
        body["query_artifact_owner_job_id"] = "job_" + "f" * 32
    elif field == "context":
        body["context_request_sha256"] = sha("f")
    elif field == "association":
        body["launch_association_sha256"] = sha("f")
    elif field == "input_raw":
        body["query_input"]["sha256"] = sha("f")
    elif field == "result_raw":
        body["query_execution"]["result_member"]["sha256"] = sha("f")
    elif field == "result_semantic":
        body["query_execution"]["result_sha256"] = sha("f")
    elif field == "shard_raw":
        body["shard"]["sha256"] = sha("f")
    elif field == "binary_raw":
        body["binary"]["sha256"] = sha("f")
    elif field == "foreign_artifact":
        body["binary"]["artifact_revision_id"] = "rev_" + "f" * 32
    elif field == "path":
        body["query_input"]["member_path"] = "/tmp/input.json"
    elif field == "schema":
        body["query_input"]["schema_ref"] = (
            "eom://schemas/knowledge/embedding-reference-query-input/1.0"
        )
    elif field == "media":
        body["binary"]["media_type"] = "image/png"
    else:
        body["published_at"] = (NOW - timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError):
        checked_receipt(c, parse_reference_query_workflow_receipt(seal(body, "receipt_sha256")))


def test_job_concepts_do_not_require_gratuitous_unequal_allocation() -> None:
    c = case()
    body = c.receipt.model_dump(mode="json")
    body["receipt_owner_job_id"] = body["query_artifact_owner_job_id"]
    receipt = parse_reference_query_workflow_receipt(seal(body, "receipt_sha256"))
    validate_reference_query_workflow_receipt(
        receipt,
        c.request,
        c.policy,
        c.bundle,
        c.launch,
        c.native_input,
        c.result,
        workflow_id=c.launch.workflow_id,
        step_run_id=c.launch.step_run_id,
        query_artifact_owner_job_id=receipt.query_artifact_owner_job_id,
        receipt_owner_job_id=receipt.receipt_owner_job_id,
    )


def test_raw_nested_boolean_copy_missing_construct_and_utc_are_revalidated() -> None:
    c = case()
    for copied in (
        c.request.model_copy(
            update={
                "resource_profile": c.request.resource_profile.model_copy(update={"threads": True})
            }
        ),
        c.request.model_copy(
            update={"context_request": c.request.context_request.model_copy(update={"top_k": True})}
        ),
        c.request.model_copy(
            update={
                "runtime_bundle": c.request.runtime_bundle.model_copy(update={"authority": "ADMIN"})
            }
        ),
        ReferenceQueryWorkflowRequest.model_construct(request_sha256=c.request.request_sha256),
    ):
        with pytest.raises(ValueError):
            parse_reference_query_workflow_request(copied)
    for time in (NOW.replace(tzinfo=None), NOW.astimezone(timezone(timedelta(hours=9)))):
        with pytest.raises(ValueError):
            parse_reference_query_execution_policy(c.policy.model_copy(update={"created_at": time}))
    with pytest.raises(ValueError):
        parse_reference_query_launch_association(
            c.launch.model_copy(update={"original_command_generation": 1.0})
        )
    with pytest.raises(ValueError):
        validate_reference_query_step_output(
            c.output.model_copy(update={"attempt": True}), c.receipt
        )


def test_carrier_raw_hash_and_exact_owner_are_not_semantic_hash_aliases() -> None:
    c = case()
    body = c.output.model_dump(mode="json")
    body["receipt"]["sha256"] = c.receipt.receipt_sha256
    with pytest.raises(ValueError):
        validate_reference_query_step_output(
            parse_reference_query_step_output(seal(body, "output_sha256")), c.receipt
        )
    body = c.output.model_dump(mode="json")
    body["receipt_owner_job_id"] = "job_" + "f" * 32
    with pytest.raises(ValueError):
        validate_reference_query_step_output(
            parse_reference_query_step_output(seal(body, "output_sha256")), c.receipt
        )


def test_nonempty_topic_scope_is_preserved_and_no_index_cannot_launch() -> None:
    c = case()
    body = c.request.model_dump(mode="json")
    body["context_request"]["topics"] = ["전하"]
    body["context_request"] = seal(body["context_request"], "request_sha256")
    request = parse_reference_query_workflow_request(seal(body, "request_sha256"))
    assert request.context_request.topics == ("전하",)
    for view in body["context_request"]["views"]:
        view["index"] = None
    body["context_request"] = seal(body["context_request"], "request_sha256")
    with pytest.raises(ValueError):
        parse_reference_query_workflow_request(seal(body, "request_sha256"))


def test_native_rows_cannot_cross_the_exact_registered_index_partition() -> None:
    c = case()
    document = c.native_input.model_dump(mode="json")
    for row in document["rows"]:
        row["encoding"] = encoding_identity(
            row["text"], c.native_input.spaces.query, storage_partition="other-partition"
        ).model_dump(mode="json")
    document["rows"].sort(key=lambda row: row["encoding"]["encoding_sha256"])
    document["input_set_sha256"] = content_sha256([row["encoding"] for row in document["rows"]])
    native = parse_embedding_reference_query_input_v11(seal(document, "request_sha256"))
    launch = c.launch.model_dump(mode="json")
    launch["query_request_sha256"] = native.request_sha256
    launch["query_input_set_sha256"] = native.input_set_sha256
    with pytest.raises(ValueError, match="exact controller"):
        validate_reference_query_launch_association(
            parse_reference_query_launch_association(seal(launch, "association_sha256")),
            c.request,
            c.policy,
            c.bundle,
            native,
        )


def test_no_report_anchor_stays_absent_without_an_invented_profile() -> None:
    c = case()
    document = c.request.model_dump(mode="json")
    document["context_request"]["anchor"]["profile"] = None
    document["context_request"]["anchor"]["solution_evidence"] = None
    document["context_request"] = seal(document["context_request"], "request_sha256")
    request = parse_reference_query_workflow_request(seal(document, "request_sha256"))
    assert request.context_request.anchor.profile is None
    assert request.context_request.anchor.solution_evidence is None
