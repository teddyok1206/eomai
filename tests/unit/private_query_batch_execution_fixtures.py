"""Real private source/control/receipt files; synthetic IAM, documents and GPU observations."""

from types import SimpleNamespace as NS

from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_workflow.native_private_chat_query_coordinator import NativePrivateQueryBatchExecuted
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation
from eom_workflow.private_chat_query_submission_context import (
    build_private_chat_query_submission_context,
)
from eom_workflow_runner.private_chat_query_batch_material import PreparedBatchPrivateChatQuery
from eom_workflow_runner.private_chat_query_source_read import (
    build_private_chat_public_query_native_input,
)
from eom_workflow_runner.query_batch_binding import prepare_private_chat_query_batch_binding

from tests.unit.embedding_batch_execution_fixtures import execution_case
from tests.unit.embedding_batch_publication_fixtures import replace_receipt_parent
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.private_chat_batch_plan_fixtures import private_planning_case_for_parent
from tests.unit.test_private_chat_batch_plan_admission import make_private_batch_admission_case


def private_query_batch_case(tmp_path, monkeypatch, *, publisher=None, key, bind=True):
    value = make_private_batch_admission_case(tmp_path, monkeypatch, publisher=publisher, key=key)
    planned = private_planning_case_for_parent(
        NS(
            request=value.request,
            selection=value.selection,
            routing=value.routing,
            cpu=value.policies["CPU"],
            cuda=value.policies["CUDA"],
        )
    )
    child = planned.child
    origin_context = build_private_chat_query_submission_context(child, value.selection.origin)
    with value.publisher.sessions.begin() as session:
        sources = value.owner.cuda.resolve_submission(session, child, origin_context)
        native = build_private_chat_public_query_native_input(
            sources, job_id="job_" + key, query_request_id="embeddingquery_" + key
        )
    launch = PrivateChatQueryLaunchAssociation.model_validate(
        seal(
            dict(
                schema_version="private-chat-query-launch-association/1.0",
                purpose="PRIVATE_CHAT_QUERY",
                workflow_id="workflow_" + key,
                step_run_id="steprun_" + key,
                step_key="encode_private_chat_query",
                attempt=1,
                workflow_request_sha256=child.request_sha256,
                context_request_sha256=child.context_request.request_sha256,
                basis_sha256=child.context_request.query_basis.basis_sha256,
                native_launch_job_id=native.job_id,
                query_request_id=native.query_request_id,
                query_request_sha256=native.request_sha256,
                query_input_set_sha256=native.input_set_sha256,
                recipe_sha256=native.recipe.recipe_sha256,
                runtime_bundle=child.runtime_bundle.model_dump(mode="json"),
                resource_profile_sha256=child.resource_profile.resource_profile_sha256,
                original_command_id="wfcmd_" + key,
                original_command_generation=1,
                launched_at="2026-10-24T19:00:00Z",
            ),
            "association_sha256",
        )
    )
    material = PreparedBatchPrivateChatQuery(child, sources.policy, sources.bundle, launch, native)
    bound, batch = prepare_private_chat_query_batch_binding(value.request, planned.route, material)
    planned.batch, planned.bound = batch, bound
    numeric = execution_case(planned=planned)
    store = EmbeddingBatchPlanStore(value.request, value.selection, value.routing)

    def authorize(binding):
        assert binding == bound.children[0]  # Explicit synthetic child command/lease seam.

    with value.publisher.sessions.begin() as session, value.owner.admit(session, value.request):
        store.allocate(session, planned.allocation)
        history = store.route(session, planned.route)
        if bind:
            history = store.bind(session, bound, batch, authorize_child=authorize)
    value.child, value.origin_context, value.sources = child, origin_context, sources
    value.native, value.launch, value.planned = native, launch, planned
    value.material = material
    value.numeric, value.store, value.history = numeric, store, history
    if not bind:
        return value
    receipt = replace_receipt_parent(numeric.receipt, history.job_id)
    saved = value.controls.publish_batch_execution_receipt(
        receipt, idempotency_key="private-query-batch-proof:" + key
    )
    executed = NativePrivateQueryBatchExecuted(
        batch_receipt=saved.member,
        batch_receipt_sha256=receipt.receipt_sha256,
        child_ordinal=0,
        result_sha256=numeric.result.children[0].result.result_sha256,
        completed_observed_at=receipt.completed.retired_at,
    )
    value.receipt, value.saved, value.executed = receipt, saved, executed
    return value
