"""Truthful owner-only READY/non-ready observations, not source authorization."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.general_chat_grounding import ChatKnowledgeItem
from eom_protocol.general_chat_rag_knowledge import ChatRagScope, read_rag
from eom_protocol.general_chat_rag_tools import ChatToolRecordV2
from eom_protocol.general_chat_tools import ChatSearchCommand
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.chat_similarity_provenance import (
    CHAT_SIMILARITY_LIMITATIONS,
    ChatSimilarityProvenanceError,
    ChatSimilaritySiblingMember,
)
from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.private_chat_query_prepare import (
    PrivateChatQueryPrepareReply,
    PrivateChatQueryPrepareRequest,
    parse_private_chat_query_prepare_request,
    validate_private_chat_query_prepare_reply,
)
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin

CHAT_SIMILARITY_OBSERVATION_REF = "eom://schemas/knowledge/general-chat-similarity-observation/1.0"
CHAT_SIMILARITY_OBSERVATION_MEMBER = "chat/similarity-observation.json"
MAX_CHAT_SIMILARITY_OBSERVATION_BYTES = 640 * 1024
type ObservationStatus = Literal["READY", "PENDING", "UNAVAILABLE", "FAILED", "UNKNOWN"]
type ObservationPhase = Literal["SCOPE", "QUERY", "METADATA", "COMPLETE"]
type ObservationError = Literal[
    "SCOPE_UNAVAILABLE",
    "QUERY_PENDING",
    "QUERY_UNAVAILABLE",
    "QUERY_FAILED",
    "QUERY_OUTCOME_UNKNOWN",
    "METADATA_UNAVAILABLE",
    "INTEGRITY_REJECTED",
]


def validate_observed_native_reply(
    original: PrivateChatQueryPrepareRequest, value: object
) -> PrivateChatQueryPrepareReply:
    """Correlate actual READ bytes; never relabel a READ acknowledgement PREPARE."""
    original = parse_private_chat_query_prepare_request(original)
    document = raw_similarity_contract_value(value)
    if not isinstance(document, dict) or original.action != "PREPARE_PRIVATE_CHAT_QUERY":
        raise ChatSimilarityProvenanceError()
    if document.get("action") == "READ_PRIVATE_CHAT_QUERY":
        body = original.model_dump(mode="json", exclude={"request_sha256"})
        body["action"] = "READ_PRIVATE_CHAT_QUERY"
        expected = parse_private_chat_query_prepare_request(
            body | {"request_sha256": content_sha256(body)}
        )
    else:
        expected = original
    return validate_private_chat_query_prepare_reply(expected, document)


class ChatSimilarityObservation(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, "general-chat-similarity-observation", MAX_CHAT_SIMILARITY_OBSERVATION_BYTES
        )

    schema_version: Literal["general-chat-similarity-observation/1.0"]
    origin: ChatPrivateQueryOrigin
    scope: ChatRagScope
    status: ObservationStatus
    phase: ObservationPhase
    native_request: PrivateChatQueryPrepareRequest | None
    native_reply: PrivateChatQueryPrepareReply | None
    tool_record_member: ChatSimilaritySiblingMember
    delivered_native_items: tuple[ChatKnowledgeItem, ...] = Field(max_length=6)
    error_code: ObservationError | None
    limitations: tuple[str, ...] = Field(min_length=4, max_length=4)
    observation_sha256: Sha256

    @model_validator(mode="after")
    def exact_observation(self) -> ChatSimilarityObservation:
        query, reply = self.native_request, self.native_reply
        if (
            self.limitations != CHAT_SIMILARITY_LIMITATIONS
            or self.observation_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"observation_sha256"}))
        ):
            raise ChatSimilarityProvenanceError()
        if self.status == "UNAVAILABLE" and self.error_code != {
            "SCOPE": "SCOPE_UNAVAILABLE",
            "QUERY": "QUERY_UNAVAILABLE",
            "METADATA": "METADATA_UNAVAILABLE",
        }.get(self.phase):
            raise ChatSimilarityProvenanceError()
        if self.status == "FAILED" and self.error_code != "INTEGRITY_REJECTED":
            raise ChatSimilarityProvenanceError()
        if query is not None and (
            query.action != "PREPARE_PRIVATE_CHAT_QUERY"
            or query.origin != self.origin
            or query.graph_snapshot.graph_snapshot_revision_id
            != self.scope.snapshot.graph_snapshot_revision_id
            or (query.policy_revision_id, query.policy_sha256)
            != (self.scope.policy.access_policy_revision_id, self.scope.policy.sha256)
        ):
            raise ChatSimilarityProvenanceError()
        if reply is not None:
            if query is None:
                raise ChatSimilarityProvenanceError()
            reply = validate_observed_native_reply(query, reply)
        if self.status == "READY":
            if reply is None or reply.context is None or reply.context.request.top_k != 64:
                raise ChatSimilarityProvenanceError()
            ranks = {
                (c.source.item_id, c.source.item_revision_id): n
                for n, c in enumerate(reply.context.candidates)
            }
            keys = tuple((r.item_id, r.item_revision_id) for r in self.delivered_native_items)
            if len(set(keys)) != len(keys) or any(k not in ranks for k in keys):
                raise ChatSimilarityProvenanceError()
            if tuple(ranks[k] for k in keys) != tuple(sorted(ranks[k] for k in keys)):
                raise ChatSimilarityProvenanceError()
        return self


def validate_chat_similarity_observation(
    record: ChatToolRecordV2, value: object
) -> ChatSimilarityObservation:
    try:
        record = read_rag("Record", raw_similarity_contract_value(record), ChatToolRecordV2)
        observation = ChatSimilarityObservation.model_validate(raw_similarity_contract_value(value))
        command = record.request.command
        if (
            not isinstance(command, ChatSearchCommand)
            or command.arguments.kind != "TOPIC"
            or observation.origin.ticket != record.request.ticket
            or observation.tool_record_member.sha256 != sha256_bytes(canonical_json_bytes(record))
            or record.outcome.context is not None
            or record.outcome.rag_context is not None
        ):
            raise ChatSimilarityProvenanceError()
        if record.outcome.status != "FAILED" and (
            observation.scope.snapshot != record.outcome.snapshot
            or (observation.status != "READY" and record.outcome.status == "EMPTY")
        ):
            raise ChatSimilarityProvenanceError()
        native = observation.delivered_native_items
        if observation.status == "READY" and record.outcome.status == "FAILED":
            raise ChatSimilarityProvenanceError()
        if tuple(c.item for c in record.outcome.cards[: len(native)]) != native:
            raise ChatSimilarityProvenanceError()
        observed = observation.native_reply
        sources = (
            {c.source.item_revision_id: c.source.source_class for c in observed.context.candidates}
            if observed is not None and observed.context is not None
            else {}
        )
        for card in record.outcome.cards[: len(native)]:
            if (
                card.approval != "APPROVED"
                or card.graph_membership != "INDEXED"
                or (
                    command.arguments.source != "ALL"
                    and card.source_kind
                    != ("PAST_EXAM" if command.arguments.source == "PAST_EXAM" else "GENERATED")
                )
            ):
                raise ChatSimilarityProvenanceError()
            if card.source_kind != (
                "PAST_EXAM" if sources[card.item.item_revision_id] == "PAST_EXAM" else "GENERATED"
            ):
                raise ChatSimilarityProvenanceError()
        return observation
    except (ValueError, TypeError, SchemaError):
        raise ChatSimilarityProvenanceError() from None


def build_chat_similarity_observation(
    *,
    record: ChatToolRecordV2,
    origin: ChatPrivateQueryOrigin,
    scope: ChatRagScope,
    status: ObservationStatus,
    phase: ObservationPhase,
    native_request: PrivateChatQueryPrepareRequest | None,
    native_reply: PrivateChatQueryPrepareReply | None,
    delivered_native_items: tuple[ChatKnowledgeItem, ...],
    error_code: ObservationError | None,
) -> ChatSimilarityObservation:
    body = dict(
        schema_version="general-chat-similarity-observation/1.0",
        origin=raw_similarity_contract_value(origin),
        scope=raw_similarity_contract_value(scope),
        status=status,
        phase=phase,
        native_request=raw_similarity_contract_value(native_request),
        native_reply=raw_similarity_contract_value(native_reply),
        tool_record_member=dict(
            member_path="chat/evidence.json",
            schema_ref="eom://schemas/general-chat/tool-record/2.0",
            media_type="application/json",
            sha256=sha256_bytes(canonical_json_bytes(record)),
        ),
        delivered_native_items=raw_similarity_contract_value(delivered_native_items),
        error_code=error_code,
        limitations=list(CHAT_SIMILARITY_LIMITATIONS),
    )
    return validate_chat_similarity_observation(
        record, body | {"observation_sha256": content_sha256(body)}
    )
