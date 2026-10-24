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
from eom_workflow.reference_query_execution import parse_reference_query_launch_association

from tests.unit.embedding_batch_publication_fixtures import publication_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import runtime_profile
from tests.unit.test_embedding_batch_plan import planning_case
from tests.unit.test_embedding_batch_plan_admission import source_case
from tests.unit.test_embedding_device_routing import policy_document
from tests.unit.test_embedding_runtime_bundle_contracts import _bundle, _pointer
from tests.unit.test_reference_query_execution_contracts import case
from tests.unit.test_reference_query_launch_preparation import sources_for


def query_batch_case(tmp_path, monkeypatch, publisher, *, key):
    query = case(device="CUDA")
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
