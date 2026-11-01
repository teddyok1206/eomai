"""Owned exact-question materialization into the unchanged common QUERY2 contract.

This owner-local value neither authorizes Chat/source access nor admits a native
purpose. A private execution successor must bind its basis and this exact input.
"""

from dataclasses import dataclass, field

from eom_catalog_contracts.embedding_reference_query import (
    ReferenceQueryTextInput,
    raw_similarity_contract_value,
)
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingRuntimeBundle
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingEncodingIdentity,
    embedding_input_set_sha256,
)
from eom_catalog_contracts.private_chat_query_basis import (
    PrivateChatQueryBasis,
    private_chat_query_text_sha256,
)
from eom_catalog_contracts.public_solution_query import (
    PublicSolutionQueryInput,
    PublicSolutionQueryResult,
    validate_public_solution_query_result,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    PublicSolutionSimilarityViewV4,
)
from eom_identifiers import content_sha256
from eom_workflow.private_chat_query_execution_v2 import (
    PrivateChatQueryExecutionPolicyV2,
    PrivateChatQueryWorkflowRequestV2,
    validate_private_chat_public_query_execution_input,
    validate_private_chat_public_query_request_references,
)
from jsonschema.exceptions import ValidationError as SchemaError

from eom_orchestrator.general_chat_similarity_basis import PreparedPrivateChatQuery


@dataclass(frozen=True, slots=True)
class PreparedPrivateChatPublicQuery:
    """Private provenance stays at the owner, not in a public corpus or numerical payload."""

    basis: PrivateChatQueryBasis
    native: PublicSolutionQueryInput = field(repr=False)

    def __post_init__(self) -> None:
        try:
            basis = PrivateChatQueryBasis.model_validate(raw_similarity_contract_value(self.basis))
            native = PublicSolutionQueryInput.model_validate(
                raw_similarity_contract_value(self.native)
            )
            if basis.query_text_sha256 != private_chat_query_text_sha256(native.rows[0].text):
                raise ValueError()
            object.__setattr__(self, "basis", basis)
            object.__setattr__(self, "native", native)
        except (ValueError, TypeError, AttributeError, SchemaError):
            raise ValueError("PRIVATE_CHAT_PUBLIC_QUERY_PROJECTION_INVALID") from None


def project_private_chat_public_query(
    prepared: PreparedPrivateChatQuery,
    view: PublicSolutionSimilarityViewV4,
    *,
    context_request_sha256: str,
    job_id: str,
    query_request_id: str,
    batch_size: int,
    threads: int,
) -> PreparedPrivateChatPublicQuery:
    """One exact row, no normalization, summary, invented solution, model or fallback."""
    try:
        if type(prepared) is not PreparedPrivateChatQuery:
            raise ValueError()
        prepared.__post_init__()
        view = PublicSolutionSimilarityViewV4.model_validate(raw_similarity_contract_value(view))
        encoding_body = dict(
            storage_partition=view.index.storage_partition,
            space_sha256=view.index.spaces.query.space_sha256,
            input_text_sha256=content_sha256(prepared.text),
        )
        encoding = EmbeddingEncodingIdentity.model_validate(
            encoding_body | dict(encoding_sha256=content_sha256(encoding_body))
        )
        row = ReferenceQueryTextInput(view="CONCRETE_FACETS", encoding=encoding, text=prepared.text)
        body = dict(
            schema_version="embedding-reference-query-input/2.0",
            job_id=job_id,
            query_request_id=query_request_id,
            context_request_sha256=context_request_sha256,
            spaces=view.index.spaces.model_dump(mode="json"),
            recipe=view.recipe.model_dump(mode="json"),
            rows=[row.model_dump(mode="json")],
            batch_size=batch_size,
            threads=threads,
            input_set_sha256=embedding_input_set_sha256((encoding,)),
        )
        native = PublicSolutionQueryInput.model_validate(
            body | dict(request_sha256=content_sha256(body))
        )
        return PreparedPrivateChatPublicQuery(prepared.basis, native)
    except (ValueError, TypeError, AttributeError, SchemaError):
        raise ValueError("PRIVATE_CHAT_PUBLIC_QUERY_PROJECTION_INVALID") from None


def validate_private_chat_public_query_result(
    prepared: PreparedPrivateChatPublicQuery, result: PublicSolutionQueryResult
) -> PublicSolutionQueryResult:
    """Exact original basis/numerical association; actual live ownership remains mandatory."""
    try:
        if type(prepared) is not PreparedPrivateChatPublicQuery:
            raise ValueError()
        prepared.__post_init__()
        result = PublicSolutionQueryResult.model_validate(raw_similarity_contract_value(result))
        validate_public_solution_query_result(prepared.native, result)
        return result
    except (ValueError, TypeError, AttributeError, SchemaError):
        raise ValueError("PRIVATE_CHAT_PUBLIC_QUERY_RESULT_INVALID") from None


def prepare_private_chat_public_query_execution_input(
    prepared: PreparedPrivateChatQuery,
    request: PrivateChatQueryWorkflowRequestV2,
    policy: PrivateChatQueryExecutionPolicyV2,
    bundle: EmbeddingRuntimeBundle,
    *,
    job_id: str,
    query_request_id: str,
) -> PreparedPrivateChatPublicQuery:
    """Close private policy/basis2, then reuse the existing exact QUERY2 projection.

    CPU/CUDA comes only from the owner-selected, pinned policy/index pair. This
    function neither changes device after execution nor borrows reference policy.
    """
    try:
        request, policy = validate_private_chat_public_query_request_references(
            request, policy, bundle
        )
        if type(prepared) is not PreparedPrivateChatQuery:
            raise ValueError()
        prepared.__post_init__()
        if prepared.basis != request.context_request.query_basis:
            raise ValueError()
        view = PublicSolutionSimilarityViewV4.model_validate(
            request.context_request.views[0].model_dump(mode="json")
        )
        result = project_private_chat_public_query(
            prepared,
            view,
            context_request_sha256=request.context_request.request_sha256,
            job_id=job_id,
            query_request_id=query_request_id,
            batch_size=request.resource_profile.batch_size,
            threads=request.resource_profile.threads,
        )
        validate_private_chat_public_query_execution_input(request, policy, bundle, result.native)
        return result
    except (ValueError, TypeError, AttributeError, SchemaError):
        raise ValueError("PRIVATE_CHAT_PUBLIC_QUERY_EXECUTION_INPUT_INVALID") from None
