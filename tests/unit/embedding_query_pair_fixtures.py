"""Synthetic exact device pins and original event frames, not current IAM or GPU proof."""

from eom_catalog_contracts.embedding_reference_query import ReferenceQuerySpaces
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSpace
from eom_catalog_contracts.similarity_context import SimilarityIndexPin, SimilarityViewSelection
from eom_catalog_contracts.similarity_context_v2 import (
    SimilarityIndexPinV2,
    SimilarityViewSelectionV2,
)
from eom_identifiers import content_sha256
from eom_workflow.embedding_batch_plan import (
    EmbeddingBatchAllocation,
    EmbeddingBatchBound,
    EmbeddingBatchRoute,
)
from eom_workflow.embedding_batch_plan_v12 import (
    BATCH_PLAN_V12_PROTOCOL,
    BATCH_SELECTION_V12_SCHEMA_REF,
    EmbeddingBatchPlanRequestV12,
    EmbeddingBatchSelectionV12,
)
from eom_workflow.embedding_device_routing import (
    EmbeddingGpuAllocationObservation,
    plan_embedding_device_route,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_plan import member, planning_case
from tests.unit.test_embedding_batch_route import route_case


def paired_query_case(
    *, batch_id=None, status="ACQUIRED", mixed=False, actor_id="operator_" + "1" * 32
):
    value = planning_case(batch_id=batch_id, status=status)
    pairs = []
    for pair in route_case(status)["indexes"]:
        rows = {}
        for name in ("cpu", "cuda"):
            pin = getattr(pair, name)
            pointer = pin.manifest.model_dump(mode="json")
            if mixed:
                pointer["schema_ref"] = "eom://schemas/knowledge/embedding-index-manifest/2.0"
            query_space = EmbeddingSpace.model_validate(
                seal(pin.space.model_dump(mode="json") | {"purpose": "QUERY"}, "space_sha256")
            )
            index_type = SimilarityIndexPinV2 if mixed else SimilarityIndexPin
            view_type = SimilarityViewSelectionV2 if mixed else SimilarityViewSelection
            rows[name] = view_type(
                view=pair.view,
                recipe=value.selection.recipe,
                index=index_type(
                    index_id=pin.index_id,
                    index_revision_id=pin.index_revision_id,
                    index_manifest=pointer,
                    index_sha256=pin.index_sha256,
                    storage_partition=pair.storage_partition,
                    spaces=ReferenceQuerySpaces(query=query_space, document=pin.space),
                ),
            ).model_dump(mode="json")
        pairs.append(rows)
    value.selection = EmbeddingBatchSelectionV12.model_validate(
        seal(
            value.selection.model_dump(mode="json")
            | dict(
                schema_version=BATCH_PLAN_V12_PROTOCOL,
                source_classes=["APPROVED_ITEM", "PAST_EXAM"],
                index_pairs=pairs,
                query=value.selection.query.model_dump(mode="json")
                | {"consumer_purpose": "PAST_EXAM_VARIATION"},
                scope=seal(
                    value.selection.scope.model_dump(mode="json") | {"actor_id": actor_id},
                    "scope_sha256",
                ),
            ),
            "selection_sha256",
        )
    )
    value.request = EmbeddingBatchPlanRequestV12.model_validate(
        seal(
            value.request.model_dump(mode="json")
            | dict(
                schema_version=BATCH_PLAN_V12_PROTOCOL,
                scope=value.selection.scope.model_dump(mode="json"),
                selection_manifest=member(
                    "selection.json", BATCH_SELECTION_V12_SCHEMA_REF, value.selection, "1"
                ).model_dump(mode="json"),
                selection_sha256=value.selection.selection_sha256,
                child_selection_sha256s=list(value.selection.child_selection_sha256s),
            ),
            "request_sha256",
        )
    )
    control = type(value.allocation.control_request).model_validate(
        seal(
            value.allocation.control_request.model_dump(mode="json")
            | dict(
                parent_request_sha256=value.request.request_sha256,
                child_set_sha256=content_sha256(list(value.request.child_selection_sha256s)),
            ),
            "message_sha256",
        )
    )
    value.allocation = EmbeddingBatchAllocation.model_validate(
        seal(
            value.allocation.model_dump(mode="json")
            | dict(
                request_sha256=value.request.request_sha256,
                control_request=control.model_dump(mode="json"),
            ),
            "record_sha256",
        )
    )
    observation = EmbeddingGpuAllocationObservation.model_validate(
        seal(
            value.route.observation.model_dump(mode="json")
            | {"request_sha256": value.request.request_sha256},
            "observation_sha256",
        )
    )
    decision = plan_embedding_device_route(value.policy, observation)
    value.route = EmbeddingBatchRoute.model_validate(
        seal(
            value.route.model_dump(mode="json")
            | dict(
                request_sha256=value.request.request_sha256,
                allocation_record_sha256=value.allocation.record_sha256,
                observation=observation.model_dump(mode="json"),
                decision=decision.model_dump(mode="json"),
            ),
            "record_sha256",
        )
    )
    value.batch = type(value.batch).model_validate(
        seal(
            value.batch.model_dump(mode="json")
            | {
                "routing_decision_sha256": decision.decision_sha256,
                "scope": value.selection.scope.model_dump(mode="json"),
                "children": [
                    child.model_dump(mode="json")
                    | {"scope_sha256": value.selection.scope.scope_sha256}
                    for child in value.batch.children
                ],
            },
            "request_sha256",
        )
    )
    value.bound = EmbeddingBatchBound.model_validate(
        seal(
            value.bound.model_dump(mode="json")
            | dict(
                request_sha256=value.request.request_sha256,
                route_record_sha256=value.route.record_sha256,
                batch_request_sha256=value.batch.request_sha256,
                children=[
                    c.model_dump(mode="json") | {"selection_sha256": key}
                    for c, key in zip(
                        value.bound.children, value.request.child_selection_sha256s, strict=True
                    )
                ],
            ),
            "record_sha256",
        )
    )
    value.failure = type(value.failure).model_validate(
        seal(
            value.failure.model_dump(mode="json")
            | dict(
                request_sha256=value.request.request_sha256,
                evidence=value.request.selection_manifest.model_dump(mode="json"),
            ),
            "record_sha256",
        )
    )
    return value
