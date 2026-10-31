"""Closed source-side metadata family; no implicit upgrade, authority or native wire change."""

from __future__ import annotations

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_work_batch import (
    PublicSolutionWorkBatchInput,
    SupportedEmbeddingWorkBatchInput,
    parse_supported_embedding_work_batch_input,
)

from eom_workflow.embedding_batch_plan import (
    BATCH_PLAN_PROTOCOL,
    BATCH_PLAN_SCHEMA_SHA256,
    BATCH_SELECTION_SCHEMA_REF,
    MAX_BATCH_PLAN_BYTES,
    EmbeddingBatchAllocation,
    EmbeddingBatchBound,
    EmbeddingBatchPlanRequest,
    EmbeddingBatchRoute,
    EmbeddingBatchSelection,
    embedding_batch_query_key_value,
    validate_embedding_batch_allocation_values,
    validate_embedding_batch_binding_values,
    validate_embedding_batch_plan_control_values,
    validate_embedding_batch_query_context_values,
    validate_embedding_batch_route_values,
)
from eom_workflow.embedding_batch_plan import embedding_batch_query_key as v1_query_key
from eom_workflow.embedding_batch_plan import (
    validate_embedding_batch_query_context as validate_v1_query_context,
)
from eom_workflow.embedding_batch_plan_v11 import (
    BATCH_PLAN_V11_PROTOCOL,
    BATCH_PLAN_V11_SCHEMA_SHA256,
    BATCH_SELECTION_V11_SCHEMA_REF,
    MAX_BULK_BATCH_SELECTION_BYTES,
    EmbeddingBatchPlanRequestV11,
    EmbeddingBatchSelectionV11,
)
from eom_workflow.embedding_batch_plan_v12 import (
    BATCH_PLAN_V12_PROTOCOL,
    BATCH_PLAN_V12_SCHEMA_SHA256,
    BATCH_SELECTION_V12_SCHEMA_REF,
    EmbeddingBatchPlanRequestV12,
    EmbeddingBatchSelectionV12,
    validate_embedding_batch_query_index_controls,
)
from eom_workflow.embedding_batch_plan_v13 import (
    BATCH_PLAN_V13_PROTOCOL,
    BATCH_PLAN_V13_SCHEMA_SHA256,
    BATCH_SELECTION_V13_SCHEMA_REF,
    EmbeddingBatchPlanRequestV13,
    EmbeddingBatchSelectionV13,
)
from eom_workflow.embedding_batch_plan_v14 import (
    BATCH_PLAN_V14_PROTOCOL,
    BATCH_PLAN_V14_SCHEMA_SHA256,
    BATCH_SELECTION_V14_SCHEMA_REF,
    EmbeddingBatchPlanRequestV14,
    EmbeddingBatchSelectionV14,
    validate_public_batch_query_context,
    validate_public_query_index_controls,
)
from eom_workflow.embedding_batch_plan_v15 import (
    BATCH_PLAN_V15_PROTOCOL,
    BATCH_PLAN_V15_SCHEMA_SHA256,
    BATCH_SELECTION_V15_SCHEMA_REF,
    EmbeddingBatchPlanRequestV15,
    EmbeddingBatchSelectionV15,
)
from eom_workflow.embedding_batch_plan_v16 import (
    BATCH_PLAN_V16_PROTOCOL,
    BATCH_PLAN_V16_SCHEMA_SHA256,
    BATCH_SELECTION_V16_SCHEMA_REF,
    EmbeddingBatchPlanRequestV16,
    EmbeddingBatchSelectionV16,
)
from eom_workflow.embedding_device_routing import (
    EmbeddingDeviceRoutingDecision,
    EmbeddingDeviceRoutingPolicy,
)
from eom_workflow.reference_query_execution import (
    PublicReferenceQueryWorkflowRequest,
    ReferenceQueryWorkflowRequestV4,
    SupportedReferenceQueryWorkflowRequest,
    parse_supported_reference_query_workflow_request,
)

type SupportedEmbeddingBatchRequest = (
    EmbeddingBatchPlanRequest
    | EmbeddingBatchPlanRequestV11
    | EmbeddingBatchPlanRequestV12
    | EmbeddingBatchPlanRequestV13
    | EmbeddingBatchPlanRequestV14
    | EmbeddingBatchPlanRequestV15
    | EmbeddingBatchPlanRequestV16
)
type SupportedEmbeddingBatchSelection = (
    EmbeddingBatchSelection
    | EmbeddingBatchSelectionV11
    | EmbeddingBatchSelectionV12
    | EmbeddingBatchSelectionV13
    | EmbeddingBatchSelectionV14
    | EmbeddingBatchSelectionV15
    | EmbeddingBatchSelectionV16
)


def parse_embedding_batch_plan_request(value: object) -> SupportedEmbeddingBatchRequest:
    document = raw_similarity_contract_value(value)
    if not isinstance(document, dict):
        raise ValueError("EMBEDDING_BATCH_PLAN_INVALID")
    version = document.get("schema_version")
    if version == BATCH_PLAN_PROTOCOL:
        return EmbeddingBatchPlanRequest.model_validate(document)
    if version == BATCH_PLAN_V11_PROTOCOL:
        return EmbeddingBatchPlanRequestV11.model_validate(document)
    if version == BATCH_PLAN_V12_PROTOCOL:
        return EmbeddingBatchPlanRequestV12.model_validate(document)
    if version == BATCH_PLAN_V13_PROTOCOL:
        return EmbeddingBatchPlanRequestV13.model_validate(document)
    if version == BATCH_PLAN_V14_PROTOCOL:
        return EmbeddingBatchPlanRequestV14.model_validate(document)
    if version == BATCH_PLAN_V15_PROTOCOL:
        return EmbeddingBatchPlanRequestV15.model_validate(document)
    if version == BATCH_PLAN_V16_PROTOCOL:
        return EmbeddingBatchPlanRequestV16.model_validate(document)
    raise ValueError("EMBEDDING_BATCH_PLAN_INVALID")


def parse_embedding_batch_selection(value: object) -> SupportedEmbeddingBatchSelection:
    document = raw_similarity_contract_value(value)
    if not isinstance(document, dict):
        raise ValueError("EMBEDDING_BATCH_PLAN_INVALID")
    version = document.get("schema_version")
    if version == BATCH_PLAN_PROTOCOL:
        return EmbeddingBatchSelection.model_validate(document)
    if version == BATCH_PLAN_V11_PROTOCOL:
        return EmbeddingBatchSelectionV11.model_validate(document)
    if version == BATCH_PLAN_V12_PROTOCOL:
        return EmbeddingBatchSelectionV12.model_validate(document)
    if version == BATCH_PLAN_V13_PROTOCOL:
        return EmbeddingBatchSelectionV13.model_validate(document)
    if version == BATCH_PLAN_V14_PROTOCOL:
        return EmbeddingBatchSelectionV14.model_validate(document)
    if version == BATCH_PLAN_V15_PROTOCOL:
        return EmbeddingBatchSelectionV15.model_validate(document)
    if version == BATCH_PLAN_V16_PROTOCOL:
        return EmbeddingBatchSelectionV16.model_validate(document)
    raise ValueError("EMBEDDING_BATCH_PLAN_INVALID")


def embedding_batch_plan_schema_identity(
    request: SupportedEmbeddingBatchRequest,
) -> tuple[str, str]:
    if (
        type(request) is EmbeddingBatchPlanRequestV16
        and request.schema_version == BATCH_PLAN_V16_PROTOCOL
    ):
        return BATCH_PLAN_V16_PROTOCOL, BATCH_PLAN_V16_SCHEMA_SHA256
    if (
        type(request) is EmbeddingBatchPlanRequestV15
        and request.schema_version == BATCH_PLAN_V15_PROTOCOL
    ):
        return BATCH_PLAN_V15_PROTOCOL, BATCH_PLAN_V15_SCHEMA_SHA256
    if (
        type(request) is EmbeddingBatchPlanRequestV14
        and request.schema_version == BATCH_PLAN_V14_PROTOCOL
    ):
        return BATCH_PLAN_V14_PROTOCOL, BATCH_PLAN_V14_SCHEMA_SHA256
    if (
        type(request) is EmbeddingBatchPlanRequestV13
        and request.schema_version == BATCH_PLAN_V13_PROTOCOL
    ):
        return BATCH_PLAN_V13_PROTOCOL, BATCH_PLAN_V13_SCHEMA_SHA256
    if (
        type(request) is EmbeddingBatchPlanRequestV12
        and request.schema_version == BATCH_PLAN_V12_PROTOCOL
    ):
        return BATCH_PLAN_V12_PROTOCOL, BATCH_PLAN_V12_SCHEMA_SHA256
    if (
        type(request) is EmbeddingBatchPlanRequestV11
        and request.schema_version == BATCH_PLAN_V11_PROTOCOL
    ):
        return BATCH_PLAN_V11_PROTOCOL, BATCH_PLAN_V11_SCHEMA_SHA256
    if type(request) is EmbeddingBatchPlanRequest and request.schema_version == BATCH_PLAN_PROTOCOL:
        return BATCH_PLAN_PROTOCOL, BATCH_PLAN_SCHEMA_SHA256
    raise ValueError("EMBEDDING_BATCH_PLAN_INVALID")


def embedding_batch_selection_schema_ref(selection: SupportedEmbeddingBatchSelection) -> str:
    if (
        type(selection) is EmbeddingBatchSelectionV16
        and selection.schema_version == BATCH_PLAN_V16_PROTOCOL
    ):
        return BATCH_SELECTION_V16_SCHEMA_REF
    if (
        type(selection) is EmbeddingBatchSelectionV15
        and selection.schema_version == BATCH_PLAN_V15_PROTOCOL
    ):
        return BATCH_SELECTION_V15_SCHEMA_REF
    if (
        type(selection) is EmbeddingBatchSelectionV14
        and selection.schema_version == BATCH_PLAN_V14_PROTOCOL
    ):
        return BATCH_SELECTION_V14_SCHEMA_REF
    if (
        type(selection) is EmbeddingBatchSelectionV13
        and selection.schema_version == BATCH_PLAN_V13_PROTOCOL
    ):
        return BATCH_SELECTION_V13_SCHEMA_REF
    if (
        type(selection) is EmbeddingBatchSelectionV12
        and selection.schema_version == BATCH_PLAN_V12_PROTOCOL
    ):
        return BATCH_SELECTION_V12_SCHEMA_REF
    if (
        type(selection) is EmbeddingBatchSelectionV11
        and selection.schema_version == BATCH_PLAN_V11_PROTOCOL
    ):
        return BATCH_SELECTION_V11_SCHEMA_REF
    if (
        type(selection) is EmbeddingBatchSelection
        and selection.schema_version == BATCH_PLAN_PROTOCOL
    ):
        return BATCH_SELECTION_SCHEMA_REF
    raise ValueError("EMBEDDING_BATCH_PLAN_INVALID")


def embedding_batch_selection_read_maximum(request: SupportedEmbeddingBatchRequest) -> int:
    protocol, _sha = embedding_batch_plan_schema_identity(request)
    return (
        MAX_BULK_BATCH_SELECTION_BYTES
        if protocol in {BATCH_PLAN_V11_PROTOCOL, BATCH_PLAN_V13_PROTOCOL, BATCH_PLAN_V16_PROTOCOL}
        else MAX_BATCH_PLAN_BYTES
    )


def validate_embedding_batch_plan_controls(
    request: SupportedEmbeddingBatchRequest,
    selection: SupportedEmbeddingBatchSelection,
    policy: EmbeddingDeviceRoutingPolicy,
) -> None:
    request = parse_embedding_batch_plan_request(request)
    selection = parse_embedding_batch_selection(selection)
    if request.schema_version != selection.schema_version:
        raise ValueError("EMBEDDING_BATCH_PLAN_INVALID")
    validate_embedding_batch_plan_control_values(
        request, selection, EmbeddingDeviceRoutingPolicy.model_validate(policy)
    )
    if isinstance(selection, EmbeddingBatchSelectionV12):
        validate_embedding_batch_query_index_controls(selection, policy)
    elif isinstance(selection, EmbeddingBatchSelectionV14 | EmbeddingBatchSelectionV15):
        validate_public_query_index_controls(selection, policy)


def validate_embedding_batch_allocation(
    request: SupportedEmbeddingBatchRequest,
    policy: EmbeddingDeviceRoutingPolicy,
    allocation: EmbeddingBatchAllocation,
) -> None:
    validate_embedding_batch_allocation_values(
        parse_embedding_batch_plan_request(request),
        EmbeddingDeviceRoutingPolicy.model_validate(policy),
        EmbeddingBatchAllocation.model_validate(allocation),
    )


def validate_embedding_batch_route_record(
    request: SupportedEmbeddingBatchRequest,
    policy: EmbeddingDeviceRoutingPolicy,
    allocation: EmbeddingBatchAllocation,
    route: EmbeddingBatchRoute,
) -> None:
    request = parse_embedding_batch_plan_request(request)
    policy = EmbeddingDeviceRoutingPolicy.model_validate(policy)
    allocation = EmbeddingBatchAllocation.model_validate(allocation)
    route = EmbeddingBatchRoute.model_validate(route)
    validate_embedding_batch_allocation_values(request, policy, allocation)
    validate_embedding_batch_route_values(request, policy, allocation, route)


def validate_embedding_batch_binding(
    request: SupportedEmbeddingBatchRequest,
    route: EmbeddingBatchRoute,
    bound: EmbeddingBatchBound,
    batch: SupportedEmbeddingWorkBatchInput | None = None,
) -> None:
    request = parse_embedding_batch_plan_request(request)
    if batch is not None:
        batch = parse_supported_embedding_work_batch_input(batch)
        if isinstance(
            request, EmbeddingBatchPlanRequestV14 | EmbeddingBatchPlanRequestV15
        ) != isinstance(batch, PublicSolutionWorkBatchInput):
            raise ValueError("EMBEDDING_BATCH_PLAN_INVALID")
    validate_embedding_batch_binding_values(
        request,
        EmbeddingBatchRoute.model_validate(route),
        EmbeddingBatchBound.model_validate(bound),
        batch,
    )


def embedding_batch_query_key(request: SupportedEmbeddingBatchRequest, ordinal: int) -> str:
    request = parse_embedding_batch_plan_request(request)
    if isinstance(
        request,
        EmbeddingBatchPlanRequestV12 | EmbeddingBatchPlanRequestV14 | EmbeddingBatchPlanRequestV15,
    ):
        return embedding_batch_query_key_value(request, ordinal)
    # INDEX1.1 must not expand conversational authority.
    return v1_query_key(
        EmbeddingBatchPlanRequest.model_validate(raw_similarity_contract_value(request)), ordinal
    )


def validate_embedding_batch_query_context(
    selection: SupportedEmbeddingBatchSelection,
    decision: EmbeddingDeviceRoutingDecision,
    ordinal: int,
    request: SupportedReferenceQueryWorkflowRequest,
) -> None:
    selection = parse_embedding_batch_selection(selection)
    if isinstance(selection, EmbeddingBatchSelectionV14 | EmbeddingBatchSelectionV15):
        request = parse_supported_reference_query_workflow_request(request)
        if not isinstance(request, PublicReferenceQueryWorkflowRequest) or (
            isinstance(selection, EmbeddingBatchSelectionV15)
            != isinstance(request, ReferenceQueryWorkflowRequestV4)
        ):
            raise ValueError("EMBEDDING_BATCH_PLAN_INVALID")
        validate_public_batch_query_context(
            selection, EmbeddingDeviceRoutingDecision.model_validate(decision), ordinal, request
        )
        return
    if isinstance(selection, EmbeddingBatchSelectionV12):
        request = parse_supported_reference_query_workflow_request(request)
        if isinstance(request, PublicReferenceQueryWorkflowRequest):
            raise ValueError("EMBEDDING_BATCH_PLAN_INVALID")
        decision = EmbeddingDeviceRoutingDecision.model_validate(decision)
        validate_embedding_batch_query_context_values(selection, decision, ordinal, request)
        context = request.context_request
        if (
            context.views != selection.selected_views(decision.selected.backend.device)
            or context.source_classes != selection.source_classes
            or context.vector_mode != "REQUIRED"
        ):
            raise ValueError("EMBEDDING_BATCH_PLAN_INVALID")
        return
    validate_v1_query_context(
        EmbeddingBatchSelection.model_validate(raw_similarity_contract_value(selection)),
        decision,
        ordinal,
        request,
    )
