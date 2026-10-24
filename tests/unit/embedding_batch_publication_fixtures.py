"""Actual publisher/plan storage; explicitly synthetic child, OS and current IAM leaves."""

from __future__ import annotations

import time
from types import SimpleNamespace

from eom_catalog_contracts.embedding_gpu_control import EmbeddingGpuAllocationRequest
from eom_catalog_contracts.embedding_work_batch import EmbeddingWorkBatchInput
from eom_catalog_contracts.embedding_work_batch_binary import validate_embedding_work_batch_binary
from eom_catalog_service.embedding_batch_owner_channel import EmbeddingBatchOwnerChannel
from eom_catalog_service.embedding_batch_owner_workspace import StagedOwnerEmbeddingBatch
from eom_identifiers import content_sha256
from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_workflow.embedding_batch_plan import (
    EmbeddingBatchAllocation,
    EmbeddingBatchBound,
    EmbeddingBatchFailure,
    EmbeddingBatchRoute,
)
from eom_workflow.embedding_device_routing import (
    EmbeddingGpuAllocationObservation,
    plan_embedding_device_route,
)
from eom_workflow_runner.embedding_batch_execution_publication import (
    CatalogEmbeddingBatchExecutionPublication,
)
from eom_workflow_runner.embedding_batch_result_read import VerifiedLocalEmbeddingBatchResult
from eom_workflow_runner.embedding_batch_source_authorization import (
    CatalogEmbeddingBatchSourceAuthorization,
)
from sqlalchemy.orm import Session

from tests.unit.embedding_batch_execution_fixtures import execution_case
from tests.unit.inference_transfer_embedding_fixtures import seal


def publication_case(value, monkeypatch, *, stage="BOUND"):
    original, request = value.case, value.request
    control = EmbeddingGpuAllocationRequest.model_validate(
        seal(
            original.allocation.control_request.model_dump(mode="json")
            | {
                "parent_request_sha256": request.request_sha256,
                "routing_policy_sha256": original.policy.policy_sha256,
                "child_set_sha256": content_sha256(list(request.child_selection_sha256s)),
                "expires_monotonic_ns": time.monotonic_ns() + 180 * 10**9,
            },
            "message_sha256",
        )
    )
    allocation = EmbeddingBatchAllocation.model_validate(
        seal(
            original.allocation.model_dump(mode="json")
            | {
                "request_sha256": request.request_sha256,
                "control_request": control.model_dump(mode="json"),
            },
            "record_sha256",
        )
    )
    observation = EmbeddingGpuAllocationObservation.model_validate(
        seal(
            original.route.observation.model_dump(mode="json")
            | {
                "request_sha256": request.request_sha256,
            },
            "observation_sha256",
        )
    )
    decision = plan_embedding_device_route(original.policy, observation)
    route = EmbeddingBatchRoute.model_validate(
        seal(
            original.route.model_dump(mode="json")
            | {
                "request_sha256": request.request_sha256,
                "allocation_record_sha256": allocation.record_sha256,
                "observation": observation.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
            },
            "record_sha256",
        )
    )
    batch = EmbeddingWorkBatchInput.model_validate(
        seal(
            original.batch.model_dump(mode="json")
            | {
                "scope": request.scope.model_dump(mode="json"),
                "routing_decision_sha256": decision.decision_sha256,
                "children": [
                    child.model_dump(mode="json")
                    | {
                        "scope_sha256": request.scope.scope_sha256,
                    }
                    for child in original.batch.children
                ],
            },
            "request_sha256",
        )
    )
    bound = EmbeddingBatchBound.model_validate(
        seal(
            original.bound.model_dump(mode="json")
            | {
                "request_sha256": request.request_sha256,
                "route_record_sha256": route.record_sha256,
                "batch_request_sha256": batch.request_sha256,
                "children": [
                    child.model_dump(mode="json")
                    | {
                        "selection_sha256": selected,
                    }
                    for child, selected in zip(
                        original.bound.children, request.child_selection_sha256s, strict=True
                    )
                ],
            },
            "record_sha256",
        )
    )
    planned = SimpleNamespace(allocation=allocation, batch=batch, bound=bound)
    numeric = execution_case(planned=planned)
    authorization = object.__new__(CatalogEmbeddingBatchSourceAuthorization)
    authorization._batch = batch
    value.source_denied = False
    value.source_calls = []

    def authorize(self):
        assert self is authorization
        value.source_calls.append("current")
        if value.denied or value.source_denied:
            raise PermissionError("synthetic child authority revoked")

    def binding(self, child):
        assert child in bound.children
        authorize(self)

    monkeypatch.setattr(CatalogEmbeddingBatchSourceAuthorization, "authorize_batch", authorize)
    monkeypatch.setattr(CatalogEmbeddingBatchSourceAuthorization, "authorize_binding", binding)
    # These unit/DB tests don't claim OS/root or original child Job proof. The
    # separate real framing/files/privileged suites cover those adapter leaves.
    monkeypatch.setattr(VerifiedLocalEmbeddingBatchResult, "assert_current", lambda _: None)
    channel = object.__new__(EmbeddingBatchOwnerChannel)
    channel.request = control
    monkeypatch.setattr(
        EmbeddingBatchOwnerChannel,
        "acknowledged_completion",
        property(lambda actual: numeric.completed if actual is channel else None),
    )
    verified = VerifiedLocalEmbeddingBatchResult(
        StagedOwnerEmbeddingBatch(numeric.frames.bound, batch, (), ()),
        numeric.frames.ready,
        numeric.completed,
        numeric.result,
        validate_embedding_work_batch_binary(batch, numeric.result, numeric.vectors),
        (),
        (),
    )
    store = EmbeddingBatchPlanStore(request, value.selection, original.policy)
    with Session(value.engine) as session, session.begin():
        with value.owner.admit(session, request):
            store.allocate(session, allocation)
            if stage != "ALLOCATED":
                store.route(session, route)
            if stage == "BOUND":
                store.bind(session, bound, batch, authorize_child=authorization.authorize_binding)
            elif stage == "FAILED":
                failure = EmbeddingBatchFailure.model_validate(
                    seal(
                        original.failure.model_dump(mode="json")
                        | {
                            "request_sha256": request.request_sha256,
                            "evidence": request.selection_manifest.model_dump(mode="json"),
                        },
                        "record_sha256",
                    )
                )
                store.record_failure(session, failure)
        history = store.read(session)
    assert history is not None
    value.numeric, value.channel = numeric, channel
    value.verified, value.authorization = verified, authorization
    value.store, value.history = store, history
    value.receipt = replace_receipt_parent(numeric.receipt, history.job_id)
    value.operation = CatalogEmbeddingBatchExecutionPublication(
        value.owner, request, authorization, value.publisher, source_commit="a" * 40
    )
    return value


def replace_receipt_parent(receipt, parent_job_id):
    return type(receipt).model_validate(
        seal(
            receipt.model_dump(mode="json") | {"parent_plan_job_id": parent_job_id},
            "receipt_sha256",
        )
    )
