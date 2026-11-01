"""Original private launch/input values shared by CPU and GPU; no SQL or execution grant."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from eom_catalog_contracts.embedding_private_chat_query import (
    EmbeddingPrivateChatQueryInput,
    SupportedPrivateNumericalQueryInput,
    parse_private_numerical_query_input,
)
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_identifiers import content_sha256, new_job_id, new_revision_id
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation

from eom_workflow_runner.private_chat_query_source_read import (
    ResolvedPrivateChatPublicQuerySources,
    ResolvedPrivateChatQuerySources,
    build_supported_private_chat_query_native_input,
    validate_supported_current_private_chat_query_input,
)
from eom_workflow_runner.repository import CommandLeaseIdentity


@dataclass(frozen=True, slots=True)
class PrivateChatQueryLaunchCandidate:
    association: PrivateChatQueryLaunchAssociation
    request: SupportedPrivateNumericalQueryInput = field(repr=False)

    def __post_init__(self) -> None:
        try:
            launch = PrivateChatQueryLaunchAssociation.model_validate(
                raw_similarity_contract_value(self.association)
            )
            native = parse_private_numerical_query_input(
                raw_similarity_contract_value(self.request)
            )
            recipe = (
                native.document_recipe
                if isinstance(native, EmbeddingPrivateChatQueryInput)
                else native.recipe
            )
            if (
                launch.native_launch_job_id != native.job_id
                or launch.query_request_id != native.query_request_id
                or launch.query_request_sha256 != native.request_sha256
                or launch.query_input_set_sha256 != native.input_set_sha256
                or launch.context_request_sha256 != native.context_request_sha256
                or launch.recipe_sha256 != recipe.recipe_sha256
            ):
                raise ValueError()
        except Exception:
            raise ValueError("PRIVATE_CHAT_QUERY_LAUNCH_CANDIDATE_INVALID") from None
        object.__setattr__(self, "association", launch)
        object.__setattr__(self, "request", native)


def prepare_private_chat_query_launch_candidate(
    sources: ResolvedPrivateChatQuerySources | ResolvedPrivateChatPublicQuerySources,
    *,
    workflow_id: str,
    step_run_id: str,
    command_lease: CommandLeaseIdentity,
    existing: PrivateChatQueryLaunchAssociation | None,
) -> PrivateChatQueryLaunchCandidate:
    """Current owner and physical adapter are separate; replay retains old IDs/time/generation."""
    try:
        sources.__post_init__()
        request = sources.request
        launch = (
            None
            if existing is None
            else PrivateChatQueryLaunchAssociation.model_validate(
                raw_similarity_contract_value(existing)
            )
        )
        if launch is not None and (
            launch.workflow_id != workflow_id or launch.step_run_id != step_run_id
        ):
            raise ValueError()
        job_id = new_job_id() if launch is None else launch.native_launch_job_id
        query_id = (
            "embeddingquery_" + new_revision_id().removeprefix("rev_")
            if launch is None
            else launch.query_request_id
        )
        native = build_supported_private_chat_query_native_input(
            sources, job_id=job_id, query_request_id=query_id
        )
        if launch is None:
            body = dict(
                schema_version="private-chat-query-launch-association/1.0",
                purpose="PRIVATE_CHAT_QUERY",
                workflow_id=workflow_id,
                step_run_id=step_run_id,
                step_key="encode_private_chat_query",
                attempt=1,
                workflow_request_sha256=request.request_sha256,
                context_request_sha256=request.context_request.request_sha256,
                basis_sha256=request.context_request.query_basis.basis_sha256,
                native_launch_job_id=job_id,
                query_request_id=query_id,
                query_request_sha256=native.request_sha256,
                query_input_set_sha256=native.input_set_sha256,
                recipe_sha256=request.context_request.views[0].recipe.recipe_sha256,
                runtime_bundle=request.runtime_bundle.model_dump(mode="json"),
                resource_profile_sha256=request.resource_profile.resource_profile_sha256,
                original_command_id=command_lease.command_id,
                original_command_generation=command_lease.lease_generation,
                launched_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
            launch = PrivateChatQueryLaunchAssociation.model_validate(
                body | {"association_sha256": content_sha256(body)}
            )
        validate_supported_current_private_chat_query_input(sources, launch, native)
        return PrivateChatQueryLaunchCandidate(launch, native)
    except Exception:
        raise ValueError("PRIVATE_CHAT_QUERY_LAUNCH_CANDIDATE_INVALID") from None
