"""Actual typed source/control/receipt values, synthetic IAM/numerics and temporary storage."""

from __future__ import annotations

from dataclasses import replace

from eom_catalog_contracts.embedding_work_batch import EmbeddingWorkBatchInput
from eom_identifiers import content_sha256
from eom_workflow.embedding_batch_plan import (
    EmbeddingBatchBound,
    EmbeddingBatchRoute,
    EmbeddingBatchSelection,
)
from eom_workflow.embedding_device_routing import (
    EmbeddingDeviceRoutingPolicy,
    EmbeddingGpuAllocationObservation,
    plan_embedding_device_route,
)
from eom_workflow.native_reference_query_coordinator import NativeQueryBatchExecuted
from eom_workflow.reference_query_execution import (
    parse_reference_query_launch_association,
    parse_supported_reference_query_workflow_request,
)
from eom_workflow_runner.reference_query_source_read import build_reference_query_native_input

from tests.unit.embedding_batch_publication_fixtures import publication_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import runtime_profile
from tests.unit.test_embedding_batch_plan import planning_case
from tests.unit.test_embedding_batch_plan_admission import source_case
from tests.unit.test_embedding_device_routing import policy_document
from tests.unit.test_embedding_runtime_bundle_contracts import _bundle, _pointer
from tests.unit.test_reference_query_execution_contracts import case
from tests.unit.test_reference_query_launch_preparation import sources_for


def query_plan_case(*, key, query=None):
    """Pure immutable QUERY/plan values, with no storage or authority leaf."""
    query = query or case(device="CUDA")
    native = type(query.native_input).model_validate(
        seal(
            query.native_input.model_dump(mode="json")
            | {
                "job_id": "job_" + key,
                "query_request_id": "embeddingquery_" + key,
            },
            "request_sha256",
        )
    )
    launch = parse_reference_query_launch_association(
        seal(
            query.launch.model_dump(mode="json")
            | {
                "workflow_id": "workflow_" + key,
                "step_run_id": "steprun_" + key,
                "native_launch_job_id": native.job_id,
                "query_request_id": native.query_request_id,
                "query_request_sha256": native.request_sha256,
            },
            "association_sha256",
        )
    )
    query = replace(query, native_input=native, launch=launch)
    template = planning_case()
    # Independently valid CPU and CUDA bundle/profile values. There is no installed
    # numerical proof in this fixture; neither adapter nor model runs here.
    cpu = _bundle("CPU")
    body = cpu.model_dump(mode="json")
    body["execution_model_spec"] = seal(
        body["execution_model_spec"]
        | {
            "model_revision_id": "embeddingmodelrev_" + "f" * 32,
        },
        "manifest_sha256",
    )
    body["bundle_revision_id"] = "embeddingbundlerev_" + "f" * 32
    cpu = type(cpu).model_validate(seal(body, "bundle_sha256"))
    profile = runtime_profile("CPU")
    body = profile.model_dump(mode="json")
    body["space"] = seal(
        body["space"]
        | {
            "model_spec": cpu.execution_model_spec.model_dump(mode="json"),
        },
        "space_sha256",
    )
    body["runtime_bundle"] = _pointer(cpu).model_dump(mode="json")
    body["runtime_bundle"]["manifest_member"]["artifact_revision_id"] = "rev_" + "f" * 32
    cpu_profile = type(profile).model_validate(body)
    body = policy_document("REFERENCE_QUERY")
    body["cpu"]["profile"] = cpu_profile.model_dump(mode="json")
    body["cuda"]["profile"] = runtime_profile("CUDA").model_dump(mode="json")
    template.policy = EmbeddingDeviceRoutingPolicy.model_validate(seal(body, "policy_sha256"))
    context = query.request.context_request
    scope = seal(
        template.selection.scope.model_dump(mode="json")
        | {
            "actor_id": query.request.operator_audit.operator_id,
            "access_policy_sha256": context.policy_sha256,
        },
        "scope_sha256",
    )
    body = template.selection.model_dump(mode="json") | {
        "scope": scope,
        "anchors": [context.anchor.model_dump(mode="json")],
        "views": [view.view for view in context.views],
        "query": dict(
            consumer_purpose=context.consumer_purpose,
            topics=list(context.topics),
            unit_ids=list(context.unit_ids),
            maximum_sources=context.maximum_sources,
            top_k=context.top_k,
        ),
    }
    template.selection = EmbeddingBatchSelection.model_validate(seal(body, "selection_sha256"))
    observation = EmbeddingGpuAllocationObservation.model_validate(
        seal(
            template.route.observation.model_dump(mode="json")
            | {"policy_sha256": template.policy.policy_sha256},
            "observation_sha256",
        )
    )
    decision = plan_embedding_device_route(template.policy, observation)
    template.route = EmbeddingBatchRoute.model_validate(
        seal(
            template.route.model_dump(mode="json")
            | {
                "observation": observation.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
            },
            "record_sha256",
        )
    )
    template.batch = EmbeddingWorkBatchInput.model_validate(
        seal(
            template.batch.model_dump(mode="json")
            | {
                "scope": scope,
                "routing_decision_sha256": decision.decision_sha256,
                "children": [
                    {
                        "scope_sha256": scope["scope_sha256"],
                        "request": query.native_input.model_dump(mode="json"),
                    }
                ],
            },
            "request_sha256",
        )
    )
    bound_child = template.bound.children[0].model_dump(mode="json") | {
        "workflow_id": query.launch.workflow_id,
        "step_run_id": query.launch.step_run_id,
        "native_job_id": query.launch.native_launch_job_id,
        "workflow_request_sha256": query.request.request_sha256,
        "launch_association_sha256": query.launch.association_sha256,
        "native_input_sha256": query.native_input.request_sha256,
    }
    template.bound = EmbeddingBatchBound.model_validate(
        seal(
            template.bound.model_dump(mode="json") | {"children": [bound_child]},
            "record_sha256",
        )
    )
    return query, template


def query_batch_case(tmp_path, monkeypatch, publisher, *, key):
    query, template = query_plan_case(key=key)
    value = source_case(tmp_path, monkeypatch, publisher=publisher, key=key, planned=template)
    # Distinct application request per disposable test, not a new identity on replay.
    value.request = type(value.request).model_validate(
        seal(
            value.request.model_dump(mode="json") | {"batch_id": "embeddingbatch_" + key},
            "request_sha256",
        )
    )
    value = publication_case(value, monkeypatch)
    saved = value.operation.publish(value.channel, value.verified)
    value.query, value.sources, value.saved = query, sources_for(query), saved
    value.executed = NativeQueryBatchExecuted(
        batch_receipt=saved.member,
        batch_receipt_sha256=value.receipt.receipt_sha256,
        child_ordinal=0,
        result_sha256=value.numeric.result.children[0].result.result_sha256,
        completed_observed_at=value.receipt.completed.retired_at,
    )
    # Keep key derivation in tests explicit without relying on random content hashes.
    assert value.receipt.allocation.child_set_sha256 == content_sha256(
        list(value.request.child_selection_sha256s)
    )
    return value


def two_query_plan_case(*, definition_sha256=None):
    """Two distinct selected anchors; all numerical/source text remains synthetic."""
    first, template = query_plan_case(
        key="a" * 32, query=case(device="CUDA", definition_sha256=definition_sha256)
    )
    other_anchor = planning_case().selection.anchors[1]
    context = seal(
        first.request.context_request.model_dump(mode="json")
        | {
            "request_id": "similarityrequest_" + "b" * 32,
            "anchor": other_anchor.model_dump(mode="json"),
        },
        "request_sha256",
    )
    request = parse_supported_reference_query_workflow_request(
        seal(first.request.model_dump(mode="json") | {"context_request": context}, "request_sha256")
    )
    second = replace(first, request=request)
    native = build_reference_query_native_input(
        sources_for(second), job_id="job_" + "b" * 32, query_request_id="embeddingquery_" + "b" * 32
    )
    launch = parse_reference_query_launch_association(
        seal(
            first.launch.model_dump(mode="json")
            | {
                "workflow_id": "workflow_" + "b" * 32,
                "step_run_id": "steprun_" + "b" * 32,
                "workflow_request_sha256": request.request_sha256,
                "context_request_sha256": request.context_request.request_sha256,
                "native_launch_job_id": native.job_id,
                "query_request_id": native.query_request_id,
                "query_request_sha256": native.request_sha256,
                "query_input_set_sha256": native.input_set_sha256,
            },
            "association_sha256",
        )
    )
    second = replace(second, native_input=native, launch=launch)
    template.selection = EmbeddingBatchSelection.model_validate(
        seal(
            template.selection.model_dump(mode="json")
            | {
                "anchors": [
                    first.request.context_request.anchor.model_dump(mode="json"),
                    other_anchor.model_dump(mode="json"),
                ]
            },
            "selection_sha256",
        )
    )
    return (first, second), template
