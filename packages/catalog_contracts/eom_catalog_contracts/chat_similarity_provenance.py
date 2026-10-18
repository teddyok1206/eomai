"""Owner-only sibling metadata: native observations are not citations or permission."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.general_chat_grounding import ChatKnowledgeItem
from eom_protocol.general_chat_rag_knowledge import ChatRagScope, read_rag
from eom_protocol.general_chat_rag_tools import ChatToolRecordV2
from eom_protocol.general_chat_tools import ChatSearchCommand
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.private_chat_query_prepare import (
    PrivateChatQueryPrepareReply,
    PrivateChatQueryPrepareRequest,
    validate_private_chat_query_prepare_reply,
)

CHAT_SIMILARITY_PROVENANCE_REF = "eom://schemas/knowledge/general-chat-similarity-provenance/1.0"
CHAT_SIMILARITY_PROVENANCE_MEMBER = "chat/similarity-provenance.json"
MAX_CHAT_SIMILARITY_PROVENANCE_BYTES = 640 * 1024
CHAT_SIMILARITY_LIMITATIONS = (
    "AUXILIARY_NOT_SOURCE_EVIDENCE",
    "SINGLE_USER_MESSAGE_ONLY",
    "SCORES_ARE_NOT_SOLUTION_EQUALITY_OR_APPROVAL",
    "FILTERED_GLOBAL_TOP64_IS_NOT_FILTERED_TOP_K",
)


class ChatSimilarityProvenanceError(ValueError):
    def __init__(self) -> None:
        super().__init__("CHAT_SIMILARITY_PROVENANCE_INVALID")


class ChatSimilaritySiblingMember(FrozenModel):
    """Small immutable sibling descriptor, not an independent Artifact lifecycle."""

    member_path: Literal["chat/evidence.json"]
    schema_ref: Literal["eom://schemas/general-chat/tool-record/2.0"]
    media_type: Literal["application/json"]
    sha256: Sha256


class ChatSimilarityProvenance(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, "general-chat-similarity-provenance", MAX_CHAT_SIMILARITY_PROVENANCE_BYTES
        )

    schema_version: Literal["general-chat-similarity-provenance/1.0"]
    scope: ChatRagScope
    native_request: PrivateChatQueryPrepareRequest
    native_reply: PrivateChatQueryPrepareReply
    tool_record_member: ChatSimilaritySiblingMember
    delivered_native_items: tuple[ChatKnowledgeItem, ...] = Field(max_length=6)
    selection_policy: Literal["TOPIC_FILTERED_GLOBAL_TOP64_NATIVE_THEN_GRAPH"]
    limitations: tuple[str, ...] = Field(min_length=4, max_length=4)
    provenance_sha256: Sha256

    @model_validator(mode="after")
    def exact_native_observation(self) -> ChatSimilarityProvenance:
        query = self.native_request
        reply = validate_private_chat_query_prepare_reply(query, self.native_reply)
        if (
            query.action != "PREPARE_PRIVATE_CHAT_QUERY"
            or reply.status != "READY"
            or reply.context is None
            or reply.context.request.top_k != 64
            or query.graph_snapshot.graph_snapshot_revision_id
            != self.scope.snapshot.graph_snapshot_revision_id
            or (query.policy_revision_id, query.policy_sha256)
            != (self.scope.policy.access_policy_revision_id, self.scope.policy.sha256)
            or self.limitations != CHAT_SIMILARITY_LIMITATIONS
            or self.provenance_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"provenance_sha256"}))
        ):
            raise ChatSimilarityProvenanceError()
        # A native source's analyzed component SHA is not its Item manifest SHA.
        native = {
            (c.source.item_id, c.source.item_revision_id): i
            for i, c in enumerate(reply.context.candidates)
        }
        keys = tuple((ref.item_id, ref.item_revision_id) for ref in self.delivered_native_items)
        if len(set(keys)) != len(keys) or any(key not in native for key in keys):
            raise ChatSimilarityProvenanceError()
        ranks = tuple(native[key] for key in keys)
        if ranks != tuple(sorted(ranks)):
            raise ChatSimilarityProvenanceError()
        return self


def validate_chat_similarity_provenance(
    record: ChatToolRecordV2, value: object
) -> ChatSimilarityProvenance:
    """Validate the sibling and exact offered records; this does not authorize a source."""
    try:
        record = read_rag("Record", raw_similarity_contract_value(record), ChatToolRecordV2)
        provenance = ChatSimilarityProvenance.model_validate(raw_similarity_contract_value(value))
        command = record.request.command
        if (
            not isinstance(command, ChatSearchCommand)
            or command.arguments.kind != "TOPIC"
            or record.outcome.status == "FAILED"
            or record.outcome.context is not None
            or record.outcome.rag_context is not None
            or provenance.native_request.origin.ticket != record.request.ticket
            or provenance.scope.snapshot != record.outcome.snapshot
            or provenance.tool_record_member.sha256
            != sha256_bytes(canonical_json_bytes(record.model_dump(mode="json")))
        ):
            raise ChatSimilarityProvenanceError()
        by_revision = {card.item.item_revision_id: card for card in record.outcome.cards}
        if (
            tuple(
                card.item for card in record.outcome.cards[: len(provenance.delivered_native_items)]
            )
            != provenance.delivered_native_items
        ):
            raise ChatSimilarityProvenanceError()
        for ref in provenance.delivered_native_items:
            card = by_revision.get(ref.item_revision_id)
            if (
                card is None
                or card.item != ref
                or card.approval != "APPROVED"
                or card.graph_membership != "INDEXED"
                or (
                    command.arguments.source != "ALL"
                    and card.source_kind
                    != ("PAST_EXAM" if command.arguments.source == "PAST_EXAM" else "GENERATED")
                )
            ):
                raise ChatSimilarityProvenanceError()
        return provenance
    except (ValueError, TypeError, SchemaError):
        raise ChatSimilarityProvenanceError() from None


def build_chat_similarity_provenance(
    *,
    record: ChatToolRecordV2,
    scope: ChatRagScope,
    native_request: PrivateChatQueryPrepareRequest,
    native_reply: PrivateChatQueryPrepareReply,
    delivered_native_items: tuple[ChatKnowledgeItem, ...],
) -> ChatSimilarityProvenance:
    try:
        record_document = raw_similarity_contract_value(record)
        body = dict(
            schema_version="general-chat-similarity-provenance/1.0",
            scope=raw_similarity_contract_value(scope),
            native_request=raw_similarity_contract_value(native_request),
            native_reply=raw_similarity_contract_value(native_reply),
            tool_record_member=dict(
                member_path="chat/evidence.json",
                schema_ref="eom://schemas/general-chat/tool-record/2.0",
                media_type="application/json",
                sha256=sha256_bytes(canonical_json_bytes(record_document)),
            ),
            delivered_native_items=raw_similarity_contract_value(delivered_native_items),
            selection_policy="TOPIC_FILTERED_GLOBAL_TOP64_NATIVE_THEN_GRAPH",
            limitations=list(CHAT_SIMILARITY_LIMITATIONS),
        )
        return validate_chat_similarity_provenance(
            record, body | {"provenance_sha256": content_sha256(body)}
        )
    except (ValueError, TypeError, SchemaError):
        raise ChatSimilarityProvenanceError() from None
