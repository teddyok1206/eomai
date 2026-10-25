"""Bulk pointer shapes and original 1.0 event frames; not genuine new corpus or numerical proof."""

from eom_catalog_contracts.embedding_gpu_control import EmbeddingGpuAllocationRequest
from eom_catalog_contracts.embedding_work_batch import EmbeddingWorkBatchInput
from eom_identifiers import content_sha256
from eom_workflow.embedding_batch_plan import (
    EmbeddingBatchAllocation,
    EmbeddingBatchBound,
    EmbeddingBatchFailure,
    EmbeddingBatchRoute,
)
from eom_workflow.embedding_batch_plan_v11 import (
    BATCH_PLAN_V11_PROTOCOL,
    BATCH_SELECTION_V11_SCHEMA_REF,
    EmbeddingBatchPlanRequestV11,
    EmbeddingBatchSelectionV11,
)
from eom_workflow.embedding_device_routing import (
    EmbeddingGpuAllocationObservation,
    plan_embedding_device_route,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_plan import member, planning_case


def bulk_planning_case(count=520, *, batch_id=None, status="ACQUIRED"):
    case = planning_case(purpose="INDEX", batch_id=batch_id, status=status)
    anchors = [anchor.model_dump(mode="json") for anchor in case.selection.anchors[:count]]
    template = case.selection.anchors[0].model_dump(mode="json")
    for ordinal in range(2, count):
        source = template["source"] | dict(
            item_id="item_" + f"{ordinal:032x}",
            item_revision_id="itemrev_" + f"{ordinal:032x}",
        )
        anchors.append(template | dict(source=source, profile=None, solution_evidence=None))
    case.selection = EmbeddingBatchSelectionV11.model_validate(
        seal(
            case.selection.model_dump(mode="json")
            | dict(schema_version=BATCH_PLAN_V11_PROTOCOL, anchors=anchors),
            "selection_sha256",
        )
    )
    case.request = EmbeddingBatchPlanRequestV11.model_validate(
        seal(
            case.request.model_dump(mode="json")
            | dict(
                schema_version=BATCH_PLAN_V11_PROTOCOL,
                selection_manifest=member(
                    "selection.json", BATCH_SELECTION_V11_SCHEMA_REF, case.selection, "1"
                ).model_dump(mode="json"),
                selection_sha256=case.selection.selection_sha256,
                child_selection_sha256s=list(case.selection.child_selection_sha256s),
            ),
            "request_sha256",
        )
    )
    control = EmbeddingGpuAllocationRequest.model_validate(
        seal(
            case.allocation.control_request.model_dump(mode="json")
            | dict(
                parent_request_sha256=case.request.request_sha256,
                child_set_sha256=content_sha256(list(case.request.child_selection_sha256s)),
            ),
            "message_sha256",
        )
    )
    case.allocation = EmbeddingBatchAllocation.model_validate(
        seal(
            case.allocation.model_dump(mode="json")
            | dict(
                request_sha256=case.request.request_sha256,
                control_request=control.model_dump(mode="json"),
            ),
            "record_sha256",
        )
    )
    observation = EmbeddingGpuAllocationObservation.model_validate(
        seal(
            case.route.observation.model_dump(mode="json")
            | {"request_sha256": case.request.request_sha256},
            "observation_sha256",
        )
    )
    decision = plan_embedding_device_route(case.policy, observation)
    case.route = EmbeddingBatchRoute.model_validate(
        seal(
            case.route.model_dump(mode="json")
            | dict(
                request_sha256=case.request.request_sha256,
                allocation_record_sha256=case.allocation.record_sha256,
                observation=observation.model_dump(mode="json"),
                decision=decision.model_dump(mode="json"),
            ),
            "record_sha256",
        )
    )
    case.batch = EmbeddingWorkBatchInput.model_validate(
        seal(
            case.batch.model_dump(mode="json")
            | {"routing_decision_sha256": decision.decision_sha256},
            "request_sha256",
        )
    )
    case.bound = EmbeddingBatchBound.model_validate(
        seal(
            case.bound.model_dump(mode="json")
            | dict(
                request_sha256=case.request.request_sha256,
                route_record_sha256=case.route.record_sha256,
                batch_request_sha256=case.batch.request_sha256,
                children=[
                    old.model_dump(mode="json") | {"selection_sha256": key}
                    for old, key in zip(
                        case.bound.children, case.request.child_selection_sha256s, strict=True
                    )
                ],
            ),
            "record_sha256",
        )
    )
    case.failure = EmbeddingBatchFailure.model_validate(
        seal(
            case.failure.model_dump(mode="json")
            | dict(
                request_sha256=case.request.request_sha256,
                evidence=case.request.selection_manifest.model_dump(mode="json"),
            ),
            "record_sha256",
        )
    )
    return case
