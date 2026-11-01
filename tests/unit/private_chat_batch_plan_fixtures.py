"""Finite parent metadata only: original private text, fake child association and source grant."""

from types import SimpleNamespace as NS

from eom_catalog_contracts.embedding_work_batch import PrivateChatWorkBatchInput
from eom_catalog_contracts.registered_public_solution_similarity import (
    PublicSolutionSimilarityViewV4,
)
from eom_identifiers import content_sha256
from eom_orchestrator.general_chat_public_query_projection import project_private_chat_public_query
from eom_orchestrator.general_chat_similarity_basis import PreparedPrivateChatQuery
from eom_workflow.embedding_batch_plan import (
    EmbeddingBatchBound,
    EmbeddingBatchFailure,
    EmbeddingBatchRoute,
)
from eom_workflow.embedding_batch_plan_v17 import (
    EmbeddingBatchPlanRequestV17,
    validate_private_batch_query_context,
    validate_private_query_batch_controls,
)
from eom_workflow.embedding_device_routing import (
    EmbeddingGpuAllocationObservation,
    plan_embedding_device_route,
)
from eom_workflow_runner.embedding_batch_allocation_candidate import (
    new_embedding_batch_allocation_candidate,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_device_routing import allocation_document
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_batch_plan import child_request, private_parent_case


def private_planning_case(*, batch_id=None, status="ACQUIRED"):
    original = private_parent_case()
    request = original.request
    if batch_id is not None:
        request = EmbeddingBatchPlanRequestV17.model_validate(
            seal(request.model_dump(mode="json") | {"batch_id": batch_id}, "request_sha256")
        )
    value = NS(**(vars(original) | {"request": request}))
    policy, selection = value.routing, value.selection
    validate_private_query_batch_controls(request, selection, policy, value.cpu, value.cuda)
    allocation = new_embedding_batch_allocation_candidate(request, policy)
    observation = EmbeddingGpuAllocationObservation.model_validate(
        seal(
            allocation_document(policy, status)
            | dict(
                request_sha256=request.request_sha256,
                allocation_attempt_id=allocation.control_request.allocation_attempt_id,
            ),
            "observation_sha256",
        )
    )
    decision = plan_embedding_device_route(policy, observation)
    route = EmbeddingBatchRoute.model_validate(
        seal(
            dict(
                schema_version="embedding-batch-plan/1.0",
                message_type="ROUTED",
                request_sha256=request.request_sha256,
                allocation_record_sha256=allocation.record_sha256,
                observation=observation.model_dump(mode="json"),
                decision=decision.model_dump(mode="json"),
            ),
            "record_sha256",
        )
    )
    _, child = child_request(value, status=status)
    validate_private_batch_query_context(request, selection, decision, 0, child)
    profile = decision.selected.profile
    native = project_private_chat_public_query(
        PreparedPrivateChatQuery(selection.origin.basis, TEXT),
        PublicSolutionSimilarityViewV4.model_validate(
            child.context_request.views[0].model_dump(mode="json")
        ),
        context_request_sha256=child.context_request.request_sha256,
        job_id="job_" + "7" * 32,
        query_request_id="embeddingquery_" + "8" * 32,
        batch_size=profile.resource_profile.batch_size,
        threads=profile.resource_profile.threads,
    ).native
    batch = PrivateChatWorkBatchInput.model_validate(
        seal(
            dict(
                schema_version="embedding-work-batch-input/3.0",
                purpose="PRIVATE_CHAT_QUERY",
                scope=selection.scope.model_dump(mode="json"),
                routing_decision_sha256=decision.decision_sha256,
                resource_profile_sha256=profile.resource_profile.resource_profile_sha256,
                timeout_seconds=profile.resource_profile.timeout_seconds,
                vector_max_bytes=native.spaces.query.model_spec.dimension * 4,
                children=[
                    dict(
                        scope_sha256=selection.scope.scope_sha256,
                        request=native.model_dump(mode="json"),
                    )
                ],
            ),
            "request_sha256",
        )
    )
    bound = EmbeddingBatchBound.model_validate(
        seal(
            dict(
                schema_version="embedding-batch-plan/1.0",
                message_type="BOUND",
                request_sha256=request.request_sha256,
                route_record_sha256=route.record_sha256,
                batch_request_sha256=batch.request_sha256,
                resource_profile_sha256=batch.resource_profile_sha256,
                children=[
                    dict(
                        selection_sha256=request.child_selection_sha256s[0],
                        workflow_id="workflow_" + "1" * 32,
                        step_run_id="steprun_" + "2" * 32,
                        native_job_id=native.job_id,
                        workflow_request_sha256=child.request_sha256,
                        native_input_sha256=native.request_sha256,
                        launch_association_sha256=content_sha256(
                            {"synthetic_private_launch": native.request_sha256}
                        ),
                    )
                ],
            ),
            "record_sha256",
        )
    )
    failure = EmbeddingBatchFailure.model_validate(
        seal(
            dict(
                schema_version="embedding-batch-plan/1.0",
                message_type="FAILED",
                request_sha256=request.request_sha256,
                error_code="SOURCE_REVOKED",
                evidence=request.selection_manifest.model_dump(mode="json"),
            ),
            "record_sha256",
        )
    )
    return NS(
        **(
            vars(value)
            | dict(
                policy=policy,
                selection=selection,
                allocation=allocation,
                route=route,
                decision=decision,
                child=child,
                native=native,
                batch=batch,
                bound=bound,
                failure=failure,
            )
        )
    )
