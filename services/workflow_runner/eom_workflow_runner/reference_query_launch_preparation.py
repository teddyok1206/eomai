"""Device-neutral original QUERY identity/input preparation; no SQL, staging or launch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_reference_query_v11 import (
    parse_embedding_reference_query_input_v11,
)
from eom_catalog_contracts.public_solution_query import PublicSolutionQueryInput
from eom_identifiers import content_sha256, new_job_id, new_revision_id
from eom_workflow.reference_query_execution import (
    ReferenceQueryLaunchAssociation,
    SupportedReferenceQueryNativeInput,
    parse_reference_query_launch_association,
    validate_reference_query_launch_association,
)

from eom_workflow_runner.reference_query_source_read import (
    SupportedResolvedReferenceQuerySources,
    build_supported_reference_query_native_input,
)
from eom_workflow_runner.repository import CommandLeaseIdentity


@dataclass(frozen=True, slots=True)
class ReferenceQueryLaunchCandidate:
    """Small identity/input relation, not current source authority or physical admission."""

    association: ReferenceQueryLaunchAssociation
    request: SupportedReferenceQueryNativeInput

    def __post_init__(self) -> None:
        launch = parse_reference_query_launch_association(self.association)
        request = (
            PublicSolutionQueryInput.model_validate(raw_similarity_contract_value(self.request))
            if isinstance(self.request, PublicSolutionQueryInput)
            else parse_embedding_reference_query_input_v11(self.request)
        )
        if (
            launch.native_launch_job_id != request.job_id
            or launch.query_request_id != request.query_request_id
            or launch.query_request_sha256 != request.request_sha256
            or launch.query_input_set_sha256 != request.input_set_sha256
            or launch.context_request_sha256 != request.context_request_sha256
            or launch.recipe_sha256 != request.recipe.recipe_sha256
        ):
            raise ValueError("REFERENCE_QUERY_LAUNCH_CANDIDATE_INVALID")
        object.__setattr__(self, "association", launch)
        object.__setattr__(self, "request", request)


def prepare_reference_query_launch_candidate(
    sources: SupportedResolvedReferenceQuerySources,
    *,
    workflow_id: str,
    step_run_id: str,
    command_lease: CommandLeaseIdentity,
    existing: ReferenceQueryLaunchAssociation | None,
) -> ReferenceQueryLaunchCandidate:
    """Caller retains current source/command authority and device-specific allocation guard.

    Replay reuses original identity/time, not the current command generation.
    The candidate alone cannot allocate a durable Job or admit computation.
    """
    sources.__post_init__()
    workflow = sources.request
    launch = None if existing is None else parse_reference_query_launch_association(existing)
    if launch is not None and (
        launch.workflow_id != workflow_id or launch.step_run_id != step_run_id
    ):
        raise ValueError("REFERENCE_QUERY_LAUNCH_CANDIDATE_OWNER_MISMATCH")
    job_id = new_job_id() if launch is None else launch.native_launch_job_id
    query_id = (
        "embeddingquery_" + new_revision_id().removeprefix("rev_")
        if launch is None
        else launch.query_request_id
    )
    native = build_supported_reference_query_native_input(
        sources, job_id=job_id, query_request_id=query_id
    )
    if launch is None:
        body = dict(
            schema_version="reference-query-launch-association/1.0",
            purpose="REFERENCE_QUERY",
            workflow_id=workflow_id,
            step_run_id=step_run_id,
            step_key="encode_reference_query",
            attempt=1,
            workflow_request_sha256=workflow.request_sha256,
            context_request_sha256=workflow.context_request.request_sha256,
            native_launch_job_id=job_id,
            query_request_id=query_id,
            query_request_sha256=native.request_sha256,
            query_input_set_sha256=native.input_set_sha256,
            recipe_sha256=native.recipe.recipe_sha256,
            runtime_bundle=workflow.runtime_bundle.model_dump(mode="json"),
            resource_profile_sha256=workflow.resource_profile.resource_profile_sha256,
            original_command_id=command_lease.command_id,
            original_command_generation=command_lease.lease_generation,
            launched_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )
        launch = parse_reference_query_launch_association(
            body | {"association_sha256": content_sha256(body)}
        )
    validate_reference_query_launch_association(
        launch, workflow, sources.policy, sources.bundle, native
    )
    return ReferenceQueryLaunchCandidate(launch, native)
