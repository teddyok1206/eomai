"""Closed checkpoint payload construction, not execution or publication authority."""

from datetime import datetime

from eom_catalog_contracts.embedding_registry import (
    EmbeddingIndexRegistrationResult,
    RegisterEmbeddingIndexCommand,
)
from eom_catalog_contracts.mixed_embedding_registry import (
    EmbeddingIndexRegistrationResultV2,
    RegisterEmbeddingIndexCommandV2,
)
from eom_catalog_contracts.public_solution_embedding_registry import (
    PublicSolutionIndexRegistrationResult,
    RegisterPublicSolutionIndexCommand,
)
from eom_catalog_contracts.registered_public_solution_registry import (
    PublicSolutionIndexRegistrationResultV4,
    RegisterPublicSolutionIndexCommandV4,
)

from eom_workflow.local_embedding_workflow_receipt import LocalEmbeddingStepOutput
from eom_workflow.local_embedding_workflow_receipt_v2 import (
    LocalEmbeddingStepOutputV2,
    SupportedLocalEmbeddingStepOutput,
)
from eom_workflow.local_embedding_workflow_receipt_v3 import LocalEmbeddingStepOutputV3
from eom_workflow.local_embedding_workflow_receipt_v4 import LocalEmbeddingStepOutputV4
from eom_workflow.native_embedding_coordinator import (
    NativeCoordinatorCompleted,
    NativeCoordinatorIndexPrepared,
    NativeCoordinatorRegistered,
)
from eom_workflow.native_embedding_coordinator_v2 import (
    NativeCoordinatorCompletedV2,
    NativeCoordinatorIndexPreparedV2,
    NativeCoordinatorRegisteredV2,
)
from eom_workflow.native_embedding_coordinator_v3 import (
    NativeCoordinatorCompletedV3,
    NativeCoordinatorIndexPreparedV3,
    NativeCoordinatorRegisteredV3,
)
from eom_workflow.native_embedding_coordinator_v4 import (
    NativeCoordinatorCompletedV4,
    NativeCoordinatorIndexPreparedV4,
    NativeCoordinatorRegisteredV4,
)

type NativeIndexRegistrationCommand = (
    RegisterEmbeddingIndexCommand
    | RegisterEmbeddingIndexCommandV2
    | RegisterPublicSolutionIndexCommand
    | RegisterPublicSolutionIndexCommandV4
)
type NativeIndexRegistrationResult = (
    EmbeddingIndexRegistrationResult
    | EmbeddingIndexRegistrationResultV2
    | PublicSolutionIndexRegistrationResult
    | PublicSolutionIndexRegistrationResultV4
)
type NativePreparedPayload = (
    NativeCoordinatorIndexPrepared
    | NativeCoordinatorIndexPreparedV2
    | NativeCoordinatorIndexPreparedV3
    | NativeCoordinatorIndexPreparedV4
)
type NativeRegisteredPayload = (
    NativeCoordinatorRegistered
    | NativeCoordinatorRegisteredV2
    | NativeCoordinatorRegisteredV3
    | NativeCoordinatorRegisteredV4
)
type NativeCompletedPayload = (
    NativeCoordinatorCompleted
    | NativeCoordinatorCompletedV2
    | NativeCoordinatorCompletedV3
    | NativeCoordinatorCompletedV4
)


def native_prepared_payload(
    command: NativeIndexRegistrationCommand, *, created_at: datetime
) -> NativePreparedPayload:
    if isinstance(command, RegisterPublicSolutionIndexCommandV4):
        return NativeCoordinatorIndexPreparedV4(
            registration_command=command, index_created_at=created_at
        )
    if isinstance(command, RegisterPublicSolutionIndexCommand):
        return NativeCoordinatorIndexPreparedV3(
            registration_command=command, index_created_at=created_at
        )
    if isinstance(command, RegisterEmbeddingIndexCommandV2):
        return NativeCoordinatorIndexPreparedV2(
            registration_command=command, index_created_at=created_at
        )
    if isinstance(command, RegisterEmbeddingIndexCommand):
        return NativeCoordinatorIndexPrepared(
            registration_command=command, index_created_at=created_at
        )
    raise ValueError("LOCAL_EMBEDDING_COORDINATOR_FAMILY_MISMATCH")


def native_registered_payload(
    result: NativeIndexRegistrationResult, *, observed_at: datetime
) -> NativeRegisteredPayload:
    if isinstance(result, PublicSolutionIndexRegistrationResultV4):
        return NativeCoordinatorRegisteredV4(
            registration_result=result, registration_observed_at=observed_at
        )
    if isinstance(result, PublicSolutionIndexRegistrationResult):
        return NativeCoordinatorRegisteredV3(
            registration_result=result, registration_observed_at=observed_at
        )
    if isinstance(result, EmbeddingIndexRegistrationResultV2):
        return NativeCoordinatorRegisteredV2(
            registration_result=result, registration_observed_at=observed_at
        )
    if isinstance(result, EmbeddingIndexRegistrationResult):
        return NativeCoordinatorRegistered(
            registration_result=result, registration_observed_at=observed_at
        )
    raise ValueError("LOCAL_EMBEDDING_COORDINATOR_FAMILY_MISMATCH")


def native_completed_payload(output: SupportedLocalEmbeddingStepOutput) -> NativeCompletedPayload:
    if isinstance(output, LocalEmbeddingStepOutputV4):
        return NativeCoordinatorCompletedV4(output=output)
    if isinstance(output, LocalEmbeddingStepOutputV3):
        return NativeCoordinatorCompletedV3(output=output)
    if isinstance(output, LocalEmbeddingStepOutputV2):
        return NativeCoordinatorCompletedV2(output=output)
    if isinstance(output, LocalEmbeddingStepOutput):
        return NativeCoordinatorCompleted(output=output)
    raise ValueError("LOCAL_EMBEDDING_COORDINATOR_FAMILY_MISMATCH")
