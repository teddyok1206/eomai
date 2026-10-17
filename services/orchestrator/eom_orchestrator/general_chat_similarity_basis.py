"""Owned-turn read only: no public-corpus query, enrollment, dispatch or publication."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts.embedding_private_chat_query import EmbeddingPrivateChatQueryInput
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
    build_private_chat_query_basis,
    private_chat_query_text_sha256,
)
from eom_catalog_contracts.private_chat_similarity import PrivateChatSimilarityRequest
from eom_catalog_contracts.similarity_context import SimilarityViewSelection
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat import CHAT_MESSAGE_SCHEMA
from eom_protocol.general_chat_grounding import GROUNDED_MESSAGE_SCHEMA
from eom_workflow.private_chat_query_execution import (
    PrivateChatQueryExecutionPolicy,
    PrivateChatQueryWorkflowRequest,
    validate_private_chat_query_request_references,
)

from eom_orchestrator.general_chat_artifacts import ChatEvidencePort
from eom_orchestrator.general_chat_evidence import chat_pointer, require_evidence, user_evidence
from eom_orchestrator.general_chat_repository import GeneralChatRepository
from eom_orchestrator.general_chat_state import ChatError


@dataclass(frozen=True, slots=True)
class PreparedPrivateChatQuery:
    """Temporary bounded text at the canonical read boundary, not DB/wire/corpus data."""

    basis: PrivateChatQueryBasis
    text: str

    def __post_init__(self) -> None:
        value = PrivateChatQueryBasis.model_validate(raw_similarity_contract_value(self.basis))
        if value.query_text_sha256 != private_chat_query_text_sha256(self.text):
            raise ValueError("private Chat projection differs from its pinned text hash")


def _owned_message_hint(
    repository: GeneralChatRepository, *, actor_id: str, conversation_id: str, turn_id: str
) -> ArtifactMemberPointer:
    with repository.read_snapshot() as session:
        repository.require_actor(session, actor_id)
        repository.owned(session, actor_id, conversation_id)
        turn = repository.turn(session, turn_id)
        if turn.conversation_id != conversation_id:
            raise ChatError("GENERAL_CHAT_NOT_FOUND")
        return chat_pointer(
            turn.input_artifact_id,
            turn.input_revision_id,
            turn.input_sha256,
            CHAT_MESSAGE_SCHEMA,
        )


def read_owned_private_chat_query(
    repository: GeneralChatRepository,
    evidence: ChatEvidencePort,
    *,
    actor_id: str,
    conversation_id: str,
    turn_id: str,
) -> PreparedPrivateChatQuery:
    """Reuse owner authorization, one exact Artifact read, then a fresh ownership fence.

    The authenticated owner supplies actor_id. This library leaf is not an exposed
    worker tool or a grant to search any public Item/profile/Graph index.
    """
    hint = _owned_message_hint(
        repository, actor_id=actor_id, conversation_id=conversation_id, turn_id=turn_id
    )
    try:
        pointers = evidence.resolve_family((hint,))
        if type(pointers) is not tuple or len(pointers) != 1:
            raise ValueError("message family resolution differs")
        pointer = ArtifactMemberPointer.model_validate(raw_similarity_contract_value(pointers[0]))
        if pointer.schema_ref not in {CHAT_MESSAGE_SCHEMA, GROUNDED_MESSAGE_SCHEMA} or (
            pointer.model_copy(update={"schema_ref": CHAT_MESSAGE_SCHEMA}) != hint
        ):
            raise ValueError("resolved message pointer differs")
        payloads = evidence.read((pointer,))
        if type(payloads) is not tuple or len(payloads) != 1:
            raise ValueError("message member read differs")
        payload = payloads[0]
        if type(payload) is not bytes or not 0 < len(payload) <= 256000:
            raise ValueError("message member byte budget differs")
        require_evidence(pointer, payload, schema_ref=pointer.schema_ref)
        message = user_evidence(payload, conversation_id=conversation_id, turn_id=turn_id)
        expected_schema = (
            CHAT_MESSAGE_SCHEMA
            if message.schema_version == "general-chat-message/1.0"
            else GROUNDED_MESSAGE_SCHEMA
        )
        if pointer.schema_ref != expected_schema or canonical_json_bytes(message) != payload:
            raise ValueError("message schema or canonical bytes differ")
        result = PreparedPrivateChatQuery(
            basis=build_private_chat_query_basis(
                conversation_id=conversation_id,
                turn_id=turn_id,
                message=pointer,
                text=message.text,
            ),
            text=message.text,
        )
    except Exception:
        raise ChatError("GENERAL_CHAT_POINTER_INVALID") from None
    # Do not reuse the old repeatable-read snapshot to claim current revocation safety.
    if hint != _owned_message_hint(
        repository, actor_id=actor_id, conversation_id=conversation_id, turn_id=turn_id
    ):
        raise ChatError("GENERAL_CHAT_POINTER_INVALID")
    return result


def build_private_chat_query_encoding_input(
    prepared: PreparedPrivateChatQuery,
    request: PrivateChatSimilarityRequest,
    *,
    job_id: str,
    query_request_id: str,
    batch_size: int,
    threads: int,
) -> EmbeddingPrivateChatQueryInput:
    """Project one exact owned question; this does NOT admit/submit a private QUERY.

    The future private-context owner must reauthorize the pinned parent/index and
    this exact basis at admission and delivery. No old reference policy is borrowed.
    """
    if type(prepared) is not PreparedPrivateChatQuery:
        raise ValueError("PRIVATE_CHAT_QUERY_PROJECTION_INVALID")
    prepared.__post_init__()
    request = PrivateChatSimilarityRequest.model_validate(raw_similarity_contract_value(request))
    if request.query_basis != prepared.basis:
        raise ValueError("PRIVATE_CHAT_QUERY_BASIS_MISMATCH")
    selection = request.views[0]
    selection = SimilarityViewSelection.model_validate(raw_similarity_contract_value(selection))
    if selection.view != "CONTENT_ONLY" or selection.index is None:
        raise ValueError("PRIVATE_CHAT_QUERY_INDEX_UNAVAILABLE")
    encoding_body = {
        "storage_partition": selection.index.storage_partition,
        "space_sha256": selection.index.spaces.query.space_sha256,
        # Encoding identity uses a canonical JSON string; the basis uses raw UTF-8.
        "input_text_sha256": content_sha256(prepared.text),
    }
    encoding = EmbeddingEncodingIdentity.model_validate(
        encoding_body | {"encoding_sha256": content_sha256(encoding_body)}
    )
    row = ReferenceQueryTextInput(view="CONTENT_ONLY", encoding=encoding, text=prepared.text)
    body = {
        "schema_version": "embedding-private-chat-query-input/1.0",
        "job_id": job_id,
        "query_request_id": query_request_id,
        "context_request_sha256": request.request_sha256,
        "basis": prepared.basis.model_dump(mode="json"),
        "spaces": selection.index.spaces.model_dump(mode="json"),
        "document_recipe": selection.recipe.model_dump(mode="json"),
        "row": row.model_dump(mode="json"),
        "batch_size": batch_size,
        "threads": threads,
        "input_set_sha256": embedding_input_set_sha256((encoding,)),
    }
    return EmbeddingPrivateChatQueryInput.model_validate(
        body | {"request_sha256": content_sha256(body)}
    )


def prepare_private_chat_query_execution_input(
    prepared: PreparedPrivateChatQuery,
    request: PrivateChatQueryWorkflowRequest,
    policy: PrivateChatQueryExecutionPolicy,
    bundle: EmbeddingRuntimeBundle,
    *,
    job_id: str,
    query_request_id: str,
) -> EmbeddingPrivateChatQueryInput:
    """Use the selected private controls, not free batch/thread or a reference policy.

    Supplied values are not current ownership/session/native admission. The owner
    must acquire that authority independently before any staging or execution.
    """
    request, _ = validate_private_chat_query_request_references(request, policy, bundle)
    return build_private_chat_query_encoding_input(
        prepared,
        request.context_request,
        job_id=job_id,
        query_request_id=query_request_id,
        batch_size=request.resource_profile.batch_size,
        threads=request.resource_profile.threads,
    )
