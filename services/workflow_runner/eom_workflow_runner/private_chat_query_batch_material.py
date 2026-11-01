"""Private common QUERY2 CUDA publication values, not a CPU handoff or compute grant."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingRuntimeBundle,
    parse_embedding_runtime_bundle,
)
from eom_catalog_contracts.public_solution_query import (
    PublicSolutionQueryInput,
    PublicSolutionQueryResult,
    validate_public_solution_query_result,
)
from eom_orchestrator.inference_transfer_cpu_handoff import fixed_owner_identity
from eom_orchestrator.native_private_chat_query_handoff import OWNER_ROOT
from eom_workflow.private_chat_query_execution_v2 import (
    PrivateChatQueryExecutionPolicyV2,
    PrivateChatQueryWorkflowRequestV2,
)
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation
from eom_workflow.private_chat_query_publication_v2 import validate_private_chat_public_query_launch

from eom_workflow_runner.query_batch_publication_files import (
    require_query_batch_publication_layout,
    stage_query_batch_publication_files,
)

PRIVATE_QUERY_PUBLICATION_ROOT = OWNER_ROOT


@dataclass(frozen=True, slots=True)
class PreparedBatchPrivateChatQuery:
    workflow_request: PrivateChatQueryWorkflowRequestV2
    policy: PrivateChatQueryExecutionPolicyV2
    bundle: EmbeddingRuntimeBundle
    association: PrivateChatQueryLaunchAssociation
    request: PublicSolutionQueryInput = field(repr=False)

    def __post_init__(self) -> None:
        try:
            workflow = PrivateChatQueryWorkflowRequestV2.model_validate(
                raw_similarity_contract_value(self.workflow_request)
            )
            policy = PrivateChatQueryExecutionPolicyV2.model_validate(
                raw_similarity_contract_value(self.policy)
            )
            bundle = parse_embedding_runtime_bundle(raw_similarity_contract_value(self.bundle))
            launch = PrivateChatQueryLaunchAssociation.model_validate(
                raw_similarity_contract_value(self.association)
            )
            native = PublicSolutionQueryInput.model_validate(
                raw_similarity_contract_value(self.request)
            )
            validate_private_chat_public_query_launch(launch, workflow, policy, bundle, native)
            if (
                workflow.resource_profile.device != "CUDA"
                or native.spaces.query.runtime.device != "CUDA"
            ):
                raise ValueError()
        except Exception:
            # Nested validation must not render private question bytes.
            raise ValueError("PRIVATE_CHAT_QUERY_BATCH_MATERIAL_INVALID") from None
        for name, value in (
            ("workflow_request", workflow),
            ("policy", policy),
            ("bundle", bundle),
            ("association", launch),
            ("request", native),
        ):
            object.__setattr__(self, name, value)

    @property
    def workspace(self) -> Path:
        return PRIVATE_QUERY_PUBLICATION_ROOT / self.association.native_launch_job_id.removeprefix(
            "job_"
        )


def require_private_batch_query_publication_layout() -> None:
    try:
        require_query_batch_publication_layout(
            PRIVATE_QUERY_PUBLICATION_ROOT, fixed_owner_identity()
        )
    except (ValueError, OSError):
        raise ValueError("PRIVATE_CHAT_QUERY_BATCH_MATERIAL_INVALID") from None


def stage_private_batch_query_publication(
    prepared: PreparedBatchPrivateChatQuery,
    result: PublicSolutionQueryResult,
    vectors: memoryview,
) -> None:
    try:
        if type(prepared) is not PreparedBatchPrivateChatQuery:
            raise ValueError()
        result = PublicSolutionQueryResult.model_validate(raw_similarity_contract_value(result))
        validate_public_solution_query_result(prepared.request, result)
        stage_query_batch_publication_files(
            PRIVATE_QUERY_PUBLICATION_ROOT,
            fixed_owner_identity(),
            prepared.request,
            result,
            vectors,
        )
    except (ValueError, OSError):
        raise ValueError("PRIVATE_CHAT_QUERY_BATCH_MATERIAL_INVALID") from None
