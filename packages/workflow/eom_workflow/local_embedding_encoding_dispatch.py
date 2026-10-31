"""Explicit supported ownership families around unchanged numeric encoding messages."""

from __future__ import annotations

from eom_catalog_contracts.embedding_contract_values import raw_similarity_contract_value
from eom_catalog_contracts.embedding_index_families import SupportedEmbeddingEntry
from eom_catalog_contracts.inference_transfer_embedding import (
    IncrementalEmbeddingInput,
    IncrementalEmbeddingResult,
)
from eom_catalog_contracts.inference_transfer_experiment import (
    StagedExperimentEntry,
    experiment_view_text,
)
from eom_catalog_contracts.mixed_embedding_index import (
    RegisteredReviewEmbeddingEntry,
    registered_review_embedding_text,
)
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_contracts.registered_public_solution_embedding import (
    RegisteredPublicSolutionEmbeddingEntry,
)

from eom_workflow.local_embedding_encoding_job import (
    EmbeddingEncodingAttachedEvent,
    EmbeddingEncodingCompletedEvent,
    EmbeddingEncodingJobMessage,
    EmbeddingEncodingReadResult,
    LocalEmbeddingLaunchAssociation,
    LocalEmbeddingLaunchIntent,
    LocalEmbeddingOwnedJob,
    build_owned_embedding_input_values,
    build_owned_incremental_embedding_input,
    parse_embedding_encoding_job_message,
    validate_embedding_encoding_completions,
    validate_local_embedding_launch_association,
)
from eom_workflow.local_embedding_encoding_ownership_v2 import (
    EmbeddingEncodingAttachedEventV2,
    EmbeddingEncodingCompletedEventV2,
    EmbeddingEncodingOwnershipMessageV2,
    EmbeddingEncodingReadResultV2,
    LocalEmbeddingLaunchAssociationV2,
    LocalEmbeddingLaunchIntentV2,
    parse_embedding_encoding_ownership_v2,
    validate_embedding_encoding_completions_v2,
    validate_local_embedding_launch_association_v2,
)
from eom_workflow.local_embedding_encoding_ownership_v3 import (
    EmbeddingEncodingAttachedEventV3,
    EmbeddingEncodingCompletedEventV3,
    EmbeddingEncodingOwnershipMessageV3,
    EmbeddingEncodingReadResultV3,
    LocalEmbeddingLaunchAssociationV3,
    LocalEmbeddingLaunchIntentV3,
    parse_embedding_encoding_ownership_v3,
    validate_embedding_encoding_completions_v3,
    validate_local_embedding_launch_association_v3,
)
from eom_workflow.local_embedding_encoding_ownership_v4 import (
    EmbeddingEncodingAttachedEventV4,
    EmbeddingEncodingCompletedEventV4,
    EmbeddingEncodingOwnershipMessageV4,
    EmbeddingEncodingReadResultV4,
    LocalEmbeddingLaunchAssociationV4,
    LocalEmbeddingLaunchIntentV4,
    parse_embedding_encoding_ownership_v4,
    validate_embedding_encoding_completions_v4,
    validate_local_embedding_launch_association_v4,
)
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingResourceProfile
from eom_workflow.local_embedding_source_plan import LocalEmbeddingSourcePlan
from eom_workflow.local_embedding_source_plan_v2 import (
    LocalEmbeddingSourcePlanV2,
    parse_local_embedding_source_plan_v2,
    validate_local_embedding_plan_entries_v2,
)
from eom_workflow.local_embedding_source_plan_v3 import (
    LocalEmbeddingSourcePlanV3,
    parse_local_embedding_source_plan_v3,
    validate_local_embedding_plan_entries_v3,
)
from eom_workflow.local_embedding_source_plan_v4 import (
    LocalEmbeddingSourcePlanV4,
    parse_local_embedding_source_plan_v4,
    validate_local_embedding_plan_entries_v4,
)

type SupportedEmbeddingIntent = (
    LocalEmbeddingLaunchIntent
    | LocalEmbeddingLaunchIntentV2
    | LocalEmbeddingLaunchIntentV3
    | LocalEmbeddingLaunchIntentV4
)
type SupportedEmbeddingAssociation = (
    LocalEmbeddingLaunchAssociation
    | LocalEmbeddingLaunchAssociationV2
    | LocalEmbeddingLaunchAssociationV3
    | LocalEmbeddingLaunchAssociationV4
)
type SupportedEmbeddingAttachedEvent = (
    EmbeddingEncodingAttachedEvent
    | EmbeddingEncodingAttachedEventV2
    | EmbeddingEncodingAttachedEventV3
    | EmbeddingEncodingAttachedEventV4
)
type SupportedEmbeddingCompletedEvent = (
    EmbeddingEncodingCompletedEvent
    | EmbeddingEncodingCompletedEventV2
    | EmbeddingEncodingCompletedEventV3
    | EmbeddingEncodingCompletedEventV4
)
type SupportedEmbeddingReadResult = (
    EmbeddingEncodingReadResult
    | EmbeddingEncodingReadResultV2
    | EmbeddingEncodingReadResultV3
    | EmbeddingEncodingReadResultV4
)
type SupportedEmbeddingMessage = (
    EmbeddingEncodingJobMessage
    | EmbeddingEncodingOwnershipMessageV2
    | EmbeddingEncodingOwnershipMessageV3
    | EmbeddingEncodingOwnershipMessageV4
)


def build_supported_owned_incremental_embedding_input(
    plan: LocalEmbeddingSourcePlan
    | LocalEmbeddingSourcePlanV2
    | LocalEmbeddingSourcePlanV3
    | LocalEmbeddingSourcePlanV4,
    entries: tuple[SupportedEmbeddingEntry, ...],
    owned_jobs: tuple[LocalEmbeddingOwnedJob, ...],
    *,
    native_launch_job_id: str,
    resources: LocalEmbeddingResourceProfile,
) -> IncrementalEmbeddingInput:
    if isinstance(plan, LocalEmbeddingSourcePlanV3 | LocalEmbeddingSourcePlanV4):
        checked_public: LocalEmbeddingSourcePlanV3 | LocalEmbeddingSourcePlanV4
        public_entries = tuple(
            entry
            for entry in entries
            if isinstance(
                entry, PublicSolutionEmbeddingEntry | RegisteredPublicSolutionEmbeddingEntry
            )
        )
        if len(public_entries) != len(entries):
            raise ValueError("LOCAL_EMBEDDING_OWNERSHIP_FAMILY_MISMATCH")
        if isinstance(plan, LocalEmbeddingSourcePlanV4):
            checked_public = parse_local_embedding_source_plan_v4(plan)
            validate_local_embedding_plan_entries_v4(checked_public, public_entries)
        else:
            checked_public = parse_local_embedding_source_plan_v3(plan)
            original_entries = tuple(
                entry for entry in public_entries if isinstance(entry, PublicSolutionEmbeddingEntry)
            )
            if len(original_entries) != len(public_entries):
                raise ValueError("LOCAL_EMBEDDING_OWNERSHIP_FAMILY_MISMATCH")
            validate_local_embedding_plan_entries_v3(checked_public, original_entries)
        public_texts = {
            entry.source.item_revision_id: entry.public_solution.text for entry in public_entries
        }
        return build_owned_embedding_input_values(
            space=checked_public.space,
            planned_encodings=tuple(demand.encoding for demand in checked_public.demands),
            encoding_texts=tuple(
                (demand.encoding, public_texts[demand.source_revision_id])
                for demand in checked_public.demands
            ),
            owned_jobs=owned_jobs,
            native_launch_job_id=native_launch_job_id,
            resources=resources,
        )
    if isinstance(plan, LocalEmbeddingSourcePlan):
        legacy = tuple(entry for entry in entries if isinstance(entry, StagedExperimentEntry))
        if len(legacy) != len(entries):
            raise ValueError("LOCAL_EMBEDDING_OWNERSHIP_FAMILY_MISMATCH")
        return build_owned_incremental_embedding_input(
            plan,
            legacy,
            owned_jobs,
            native_launch_job_id=native_launch_job_id,
            resources=resources,
        )
    plan = parse_local_embedding_source_plan_v2(plan)
    mixed_entries = tuple(
        entry
        for entry in entries
        if isinstance(entry, (StagedExperimentEntry, RegisteredReviewEmbeddingEntry))
    )
    if len(mixed_entries) != len(entries):
        raise ValueError("LOCAL_EMBEDDING_OWNERSHIP_FAMILY_MISMATCH")
    validate_local_embedding_plan_entries_v2(plan, mixed_entries)
    by_source = {
        entry.profile.source_basis.source.item_revision_id: entry for entry in mixed_entries
    }
    texts = {
        source: registered_review_embedding_text(entry, plan.namespace.view)
        if isinstance(entry, RegisteredReviewEmbeddingEntry)
        else experiment_view_text(entry, plan.namespace.view)
        for source, entry in by_source.items()
    }
    return build_owned_embedding_input_values(
        space=plan.space,
        planned_encodings=tuple(demand.encoding for demand in plan.demands),
        encoding_texts=tuple(
            (demand.encoding, texts[demand.source_revision_id]) for demand in plan.demands
        ),
        owned_jobs=owned_jobs,
        native_launch_job_id=native_launch_job_id,
        resources=resources,
    )


def parse_supported_embedding_message(value: object) -> SupportedEmbeddingMessage:
    document = raw_similarity_contract_value(value)
    if isinstance(document, dict):
        if document.get("schema_version") == "embedding-encoding-job/1.0":
            return parse_embedding_encoding_job_message(document)
        if document.get("schema_version") == "embedding-encoding-ownership/2.0":
            return parse_embedding_encoding_ownership_v2(document)
        if document.get("schema_version") == "embedding-encoding-ownership/3.0":
            return parse_embedding_encoding_ownership_v3(document)
        if document.get("schema_version") == "embedding-encoding-ownership/4.0":
            return parse_embedding_encoding_ownership_v4(document)
    raise ValueError("LOCAL_EMBEDDING_CONTRACT_INVALID")


def parse_supported_embedding_intent(value: object) -> SupportedEmbeddingIntent:
    document = raw_similarity_contract_value(value)
    if isinstance(document, dict) and isinstance(document.get("source_plan"), dict):
        schema = document["source_plan"].get("schema_ref")
        if schema == "eom://schemas/workflow/local-embedding-source-plan/1.0":
            return LocalEmbeddingLaunchIntent.model_validate(document)
        if schema == "eom://schemas/workflow/local-embedding-source-plan/2.0":
            return LocalEmbeddingLaunchIntentV2.model_validate(document)
        if schema == "eom://schemas/workflow/local-embedding-source-plan/3.0":
            return LocalEmbeddingLaunchIntentV3.model_validate(document)
        if schema == "eom://schemas/workflow/local-embedding-source-plan/4.0":
            return LocalEmbeddingLaunchIntentV4.model_validate(document)
    raise ValueError("LOCAL_EMBEDDING_CONTRACT_INVALID")


def embedding_ownership_version(intent: SupportedEmbeddingIntent) -> str:
    """Closed metadata family selection, not an inference from current/latest work."""
    checked = parse_supported_embedding_intent(intent)
    return {
        "eom://schemas/workflow/local-embedding-source-plan/1.0": "embedding-encoding-job/1.0",
        "eom://schemas/workflow/local-embedding-source-plan/2.0": (
            "embedding-encoding-ownership/2.0"
        ),
        "eom://schemas/workflow/local-embedding-source-plan/3.0": (
            "embedding-encoding-ownership/3.0"
        ),
        "eom://schemas/workflow/local-embedding-source-plan/4.0": (
            "embedding-encoding-ownership/4.0"
        ),
    }[checked.source_plan.schema_ref]


def parse_supported_embedding_association(value: object) -> SupportedEmbeddingAssociation:
    result = parse_supported_embedding_message(value)
    if not isinstance(
        result,
        LocalEmbeddingLaunchAssociation
        | LocalEmbeddingLaunchAssociationV2
        | LocalEmbeddingLaunchAssociationV3
        | LocalEmbeddingLaunchAssociationV4,
    ):
        raise ValueError("LOCAL_EMBEDDING_CONTRACT_INVALID")
    return result


def parse_supported_embedding_attached(value: object) -> SupportedEmbeddingAttachedEvent:
    result = parse_supported_embedding_message(value)
    if not isinstance(
        result,
        EmbeddingEncodingAttachedEvent
        | EmbeddingEncodingAttachedEventV2
        | EmbeddingEncodingAttachedEventV3
        | EmbeddingEncodingAttachedEventV4,
    ):
        raise ValueError("LOCAL_EMBEDDING_CONTRACT_INVALID")
    return result


def parse_supported_embedding_completed(value: object) -> SupportedEmbeddingCompletedEvent:
    result = parse_supported_embedding_message(value)
    if not isinstance(
        result,
        EmbeddingEncodingCompletedEvent
        | EmbeddingEncodingCompletedEventV2
        | EmbeddingEncodingCompletedEventV3
        | EmbeddingEncodingCompletedEventV4,
    ):
        raise ValueError("LOCAL_EMBEDDING_CONTRACT_INVALID")
    return result


def parse_supported_embedding_read(value: object) -> SupportedEmbeddingReadResult:
    result = parse_supported_embedding_message(value)
    if not isinstance(
        result,
        EmbeddingEncodingReadResult
        | EmbeddingEncodingReadResultV2
        | EmbeddingEncodingReadResultV3
        | EmbeddingEncodingReadResultV4,
    ):
        raise ValueError("LOCAL_EMBEDDING_CONTRACT_INVALID")
    return result


def validate_supported_embedding_association(
    association: SupportedEmbeddingAssociation,
    plan: LocalEmbeddingSourcePlan
    | LocalEmbeddingSourcePlanV2
    | LocalEmbeddingSourcePlanV3
    | LocalEmbeddingSourcePlanV4,
    owned_input: IncrementalEmbeddingInput,
    resources: LocalEmbeddingResourceProfile,
    workflow_request_sha256: str,
) -> None:
    if isinstance(association, LocalEmbeddingLaunchAssociationV4) and isinstance(
        plan, LocalEmbeddingSourcePlanV4
    ):
        validate_local_embedding_launch_association_v4(
            association, plan, owned_input, resources, workflow_request_sha256
        )
        return
    if isinstance(association, LocalEmbeddingLaunchAssociationV3) and isinstance(
        plan, LocalEmbeddingSourcePlanV3
    ):
        validate_local_embedding_launch_association_v3(
            association, plan, owned_input, resources, workflow_request_sha256
        )
        return
    if isinstance(association, LocalEmbeddingLaunchAssociationV2) and isinstance(
        plan, LocalEmbeddingSourcePlanV2
    ):
        validate_local_embedding_launch_association_v2(
            association, plan, owned_input, resources, workflow_request_sha256
        )
    elif isinstance(association, LocalEmbeddingLaunchAssociation) and isinstance(
        plan, LocalEmbeddingSourcePlan
    ):
        validate_local_embedding_launch_association(
            association, plan, owned_input, resources, workflow_request_sha256
        )
    else:
        raise ValueError("LOCAL_EMBEDDING_OWNERSHIP_FAMILY_MISMATCH")


def validate_supported_embedding_completions(
    events: tuple[SupportedEmbeddingCompletedEvent, ...],
    association: SupportedEmbeddingAssociation,
    owned_input: IncrementalEmbeddingInput,
    result: IncrementalEmbeddingResult,
) -> None:
    if isinstance(association, LocalEmbeddingLaunchAssociationV4) and all(
        isinstance(event, EmbeddingEncodingCompletedEventV4) for event in events
    ):
        validate_embedding_encoding_completions_v4(
            tuple(
                event for event in events if isinstance(event, EmbeddingEncodingCompletedEventV4)
            ),
            association,
            owned_input,
            result,
        )
        return
    if isinstance(association, LocalEmbeddingLaunchAssociationV3) and all(
        isinstance(event, EmbeddingEncodingCompletedEventV3) for event in events
    ):
        validate_embedding_encoding_completions_v3(
            tuple(
                event for event in events if isinstance(event, EmbeddingEncodingCompletedEventV3)
            ),
            association,
            owned_input,
            result,
        )
        return
    if isinstance(association, LocalEmbeddingLaunchAssociationV2) and all(
        isinstance(event, EmbeddingEncodingCompletedEventV2) for event in events
    ):
        validate_embedding_encoding_completions_v2(
            tuple(
                event for event in events if isinstance(event, EmbeddingEncodingCompletedEventV2)
            ),
            association,
            owned_input,
            result,
        )
    elif isinstance(association, LocalEmbeddingLaunchAssociation) and all(
        isinstance(event, EmbeddingEncodingCompletedEvent) for event in events
    ):
        validate_embedding_encoding_completions(
            tuple(event for event in events if isinstance(event, EmbeddingEncodingCompletedEvent)),
            association,
            owned_input,
            result,
        )
    else:
        raise ValueError("LOCAL_EMBEDDING_OWNERSHIP_FAMILY_MISMATCH")
