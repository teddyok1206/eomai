"""Explicit supported ownership families around unchanged numeric encoding messages."""

from __future__ import annotations

from eom_catalog_contracts.embedding_contract_values import raw_similarity_contract_value
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
    SupportedEmbeddingEntry,
    registered_review_embedding_text,
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
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingResourceProfile
from eom_workflow.local_embedding_source_plan import LocalEmbeddingSourcePlan
from eom_workflow.local_embedding_source_plan_v2 import (
    LocalEmbeddingSourcePlanV2,
    parse_local_embedding_source_plan_v2,
    validate_local_embedding_plan_entries_v2,
)

type SupportedEmbeddingIntent = LocalEmbeddingLaunchIntent | LocalEmbeddingLaunchIntentV2
type SupportedEmbeddingAssociation = (
    LocalEmbeddingLaunchAssociation | LocalEmbeddingLaunchAssociationV2
)
type SupportedEmbeddingAttachedEvent = (
    EmbeddingEncodingAttachedEvent | EmbeddingEncodingAttachedEventV2
)
type SupportedEmbeddingCompletedEvent = (
    EmbeddingEncodingCompletedEvent | EmbeddingEncodingCompletedEventV2
)
type SupportedEmbeddingReadResult = EmbeddingEncodingReadResult | EmbeddingEncodingReadResultV2
type SupportedEmbeddingMessage = EmbeddingEncodingJobMessage | EmbeddingEncodingOwnershipMessageV2


def build_supported_owned_incremental_embedding_input(
    plan: LocalEmbeddingSourcePlan | LocalEmbeddingSourcePlanV2,
    entries: tuple[SupportedEmbeddingEntry, ...],
    owned_jobs: tuple[LocalEmbeddingOwnedJob, ...],
    *,
    native_launch_job_id: str,
    resources: LocalEmbeddingResourceProfile,
) -> IncrementalEmbeddingInput:
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
    validate_local_embedding_plan_entries_v2(plan, entries)
    by_source = {entry.profile.source_basis.source.item_revision_id: entry for entry in entries}
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
    raise ValueError("LOCAL_EMBEDDING_CONTRACT_INVALID")


def parse_supported_embedding_intent(value: object) -> SupportedEmbeddingIntent:
    document = raw_similarity_contract_value(value)
    if isinstance(document, dict) and isinstance(document.get("source_plan"), dict):
        schema = document["source_plan"].get("schema_ref")
        if schema == "eom://schemas/workflow/local-embedding-source-plan/1.0":
            return LocalEmbeddingLaunchIntent.model_validate(document)
        if schema == "eom://schemas/workflow/local-embedding-source-plan/2.0":
            return LocalEmbeddingLaunchIntentV2.model_validate(document)
    raise ValueError("LOCAL_EMBEDDING_CONTRACT_INVALID")


def parse_supported_embedding_association(value: object) -> SupportedEmbeddingAssociation:
    result = parse_supported_embedding_message(value)
    if not isinstance(result, LocalEmbeddingLaunchAssociation | LocalEmbeddingLaunchAssociationV2):
        raise ValueError("LOCAL_EMBEDDING_CONTRACT_INVALID")
    return result


def parse_supported_embedding_attached(value: object) -> SupportedEmbeddingAttachedEvent:
    result = parse_supported_embedding_message(value)
    if not isinstance(result, EmbeddingEncodingAttachedEvent | EmbeddingEncodingAttachedEventV2):
        raise ValueError("LOCAL_EMBEDDING_CONTRACT_INVALID")
    return result


def parse_supported_embedding_completed(value: object) -> SupportedEmbeddingCompletedEvent:
    result = parse_supported_embedding_message(value)
    if not isinstance(result, EmbeddingEncodingCompletedEvent | EmbeddingEncodingCompletedEventV2):
        raise ValueError("LOCAL_EMBEDDING_CONTRACT_INVALID")
    return result


def parse_supported_embedding_read(value: object) -> SupportedEmbeddingReadResult:
    result = parse_supported_embedding_message(value)
    if not isinstance(result, EmbeddingEncodingReadResult | EmbeddingEncodingReadResultV2):
        raise ValueError("LOCAL_EMBEDDING_CONTRACT_INVALID")
    return result


def validate_supported_embedding_association(
    association: SupportedEmbeddingAssociation,
    plan: LocalEmbeddingSourcePlan | LocalEmbeddingSourcePlanV2,
    owned_input: IncrementalEmbeddingInput,
    resources: LocalEmbeddingResourceProfile,
    workflow_request_sha256: str,
) -> None:
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
