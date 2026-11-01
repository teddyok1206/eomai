"""Original launch1 values and private request2 reconstruction, without copying questions."""

from typing import Final, Literal, Self

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingRuntimeBundle
from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.public_solution_query import PublicSolutionQueryInput
from eom_identifiers import content_sha256
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ConfigDict, model_validator

from eom_workflow.private_chat_query_execution_v2 import (
    PrivateChatQueryExecutionPolicyV2,
    PrivateChatQueryWorkflowRequestV2,
    validate_private_chat_public_query_execution_input,
)
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation
from eom_workflow.schemas import NativeEmbeddingContract, validate_local_embedding_admission_message

PRIVATE_CHAT_PUBLIC_QUERY_RECORD_REF: Final = (
    "eom://schemas/workflow/private-chat-query-execution-record/2.0"
)


class PrivateChatPublicQueryExecutionRecord(NativeEmbeddingContract):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    schema_version: Literal["private-chat-query-execution-record/2.0"]
    purpose: Literal["PRIVATE_CHAT_QUERY"]
    workflow_request: PrivateChatQueryWorkflowRequestV2
    launch: PrivateChatQueryLaunchAssociation
    record_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        document = raw_similarity_contract_value(value)
        validate_local_embedding_admission_message("private-chat-publication-v2", document)
        return document

    @model_validator(mode="after")
    def exact_record(self) -> Self:
        request, launch = self.workflow_request, self.launch
        if (
            launch.workflow_request_sha256 != request.request_sha256
            or launch.context_request_sha256 != request.context_request.request_sha256
            or launch.basis_sha256 != request.context_request.query_basis.basis_sha256
            or launch.runtime_bundle != request.runtime_bundle
            or launch.resource_profile_sha256 != request.resource_profile.resource_profile_sha256
            or launch.recipe_sha256 != request.context_request.views[0].recipe.recipe_sha256
            or self.record_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_EXECUTION_RECORD_INVALID")
        return self


def validate_private_chat_public_query_launch(
    launch: PrivateChatQueryLaunchAssociation,
    request: PrivateChatQueryWorkflowRequestV2,
    policy: PrivateChatQueryExecutionPolicyV2,
    bundle: EmbeddingRuntimeBundle,
    native: PublicSolutionQueryInput,
) -> PrivateChatPublicQueryExecutionRecord:
    """Close supplied private parent/native hashes; not live origin or unit admission."""
    try:
        launch = PrivateChatQueryLaunchAssociation.model_validate(
            raw_similarity_contract_value(launch)
        )
        request = PrivateChatQueryWorkflowRequestV2.model_validate(
            raw_similarity_contract_value(request)
        )
        policy = PrivateChatQueryExecutionPolicyV2.model_validate(
            raw_similarity_contract_value(policy)
        )
        native = validate_private_chat_public_query_execution_input(request, policy, bundle, native)
        if (
            launch.native_launch_job_id != native.job_id
            or launch.query_request_id != native.query_request_id
            or launch.query_request_sha256 != native.request_sha256
            or launch.query_input_set_sha256 != native.input_set_sha256
            or launch.launched_at < policy.created_at
        ):
            raise ValueError()
        body = dict(
            schema_version="private-chat-query-execution-record/2.0",
            purpose="PRIVATE_CHAT_QUERY",
            workflow_request=request.model_dump(mode="json"),
            launch=launch.model_dump(mode="json"),
        )
        return PrivateChatPublicQueryExecutionRecord.model_validate(
            body | dict(record_sha256=content_sha256(body))
        )
    except (ValueError, TypeError, AttributeError, SchemaError):
        raise ValueError("PRIVATE_CHAT_QUERY_LAUNCH_PROVENANCE_INVALID") from None
