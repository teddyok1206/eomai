"""One shared candidate constructor for INDEX and QUERY; not a physical allocation grant."""

from __future__ import annotations

import time
from uuid import uuid4

from eom_catalog_contracts.embedding_gpu_control import (
    EmbeddingGpuAllocationRequest,
    embedding_gpu_allocation_window_seconds,
)
from eom_catalog_contracts.embedding_work_batch import MAX_EMBEDDING_WORK_BATCH_SECONDS
from eom_identifiers import content_sha256
from eom_workflow.embedding_batch_plan import BATCH_PLAN_PROTOCOL, EmbeddingBatchAllocation
from eom_workflow.embedding_batch_plan_family import (
    SupportedEmbeddingBatchRequest,
    parse_embedding_batch_plan_request,
    validate_embedding_batch_allocation,
)
from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingPolicy
from eom_workflow.native_embedding_backend_selection import NativeCudaBackendSelection


def new_embedding_batch_allocation_candidate(
    parent: SupportedEmbeddingBatchRequest,
    policy: EmbeddingDeviceRoutingPolicy,
    *,
    now_monotonic_ns: int | None = None,
) -> EmbeddingBatchAllocation:
    """Only the newly committed official allocation may dispatch this candidate.

    Nonce/time are not scientific identity. On replay the existing parent store
    retains the original allocation, never this freshly proposed value.
    """
    parent = parse_embedding_batch_plan_request(parent)
    policy = EmbeddingDeviceRoutingPolicy.model_validate(policy)
    backend = policy.cuda.backend.backend
    now = time.monotonic_ns() if now_monotonic_ns is None else now_monotonic_ns
    if not isinstance(backend, NativeCudaBackendSelection) or type(now) is not int or now < 0:
        raise ValueError("EMBEDDING_BATCH_ALLOCATION_CANDIDATE_INVALID")
    body = dict(
        schema_version="embedding-gpu-allocation-control/1.0",
        message_type="ALLOCATION_REQUEST",
        allocation_attempt_id="embeddingallocation_" + uuid4().hex,
        parent_request_sha256=parent.request_sha256,
        child_set_sha256=content_sha256(list(parent.child_selection_sha256s)),
        routing_policy_sha256=policy.policy_sha256,
        purpose=parent.purpose,
        configuration=backend.configuration.model_dump(mode="json"),
        receipt_raw_sha256=backend.receipt_raw_sha256,
        expires_monotonic_ns=now
        + embedding_gpu_allocation_window_seconds(
            min(
                policy.cuda.profile.resource_profile.timeout_seconds,
                MAX_EMBEDDING_WORK_BATCH_SECONDS,
            )
        )
        * 10**9,
    )
    control = EmbeddingGpuAllocationRequest.model_validate(
        body | {"message_sha256": content_sha256(body)}
    )
    body = dict(
        schema_version=BATCH_PLAN_PROTOCOL,
        message_type="ALLOCATION",
        request_sha256=parent.request_sha256,
        control_request=control.model_dump(mode="json"),
    )
    result = EmbeddingBatchAllocation.model_validate(body | {"record_sha256": content_sha256(body)})
    validate_embedding_batch_allocation(parent, policy, result)
    return result
