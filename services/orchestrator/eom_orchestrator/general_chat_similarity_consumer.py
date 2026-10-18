"""Optional claim-scoped TOPIC enrichment through existing owner/Catalog ports."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from time import monotonic
from typing import Protocol

from eom_catalog_contracts.chat_private_query_scope import ChatPrivateQueryScopeReply
from eom_catalog_contracts.chat_ranked_candidate_read import (
    ChatRankedCandidateKey,
    ChatRankedCandidateReadReply,
    build_chat_ranked_candidate_read_request,
    chat_ranked_candidate_keys,
    validate_chat_ranked_candidate_read_reply,
)
from eom_catalog_contracts.chat_similarity_observation import (
    ChatSimilarityObservation,
    ObservationError,
    ObservationPhase,
    ObservationStatus,
    build_chat_similarity_observation,
    validate_observed_native_reply,
)
from eom_catalog_contracts.private_chat_query_prepare import (
    PrivateChatQueryPrepareProtocolError,
    PrivateChatQueryPrepareReply,
    PrivateChatQueryPrepareRequest,
    parse_private_chat_query_prepare_request,
    validate_private_chat_query_prepare_reply,
)
from eom_catalog_contracts.private_chat_query_read import (
    ChatPrivateQueryOrigin,
    LiveChatQueryProjection,
)
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat_grounding import ChatKnowledgeItem
from eom_protocol.general_chat_rag_knowledge import ChatRagScope, RagError
from eom_protocol.general_chat_rag_tools import ChatToolOutcomeV2, ChatToolRecordV2, failed_rag_tool
from eom_protocol.general_chat_tools import ChatSearchArguments
from eom_protocol.general_chat_worker_messages import ChatWorkerTicket
from jsonschema.exceptions import ValidationError as SchemaError

from eom_orchestrator.general_chat_socket import ChatTransportError
from eom_orchestrator.general_chat_state import ChatError
from eom_orchestrator.private_chat_query_completion import wait_for_original_private_chat_query
from eom_orchestrator.private_chat_query_prepare_client import (
    PRIVATE_CHAT_QUERY_RPC_TIMEOUT,
    PrivateChatQueryPrepareClient,
)

MAX_CHAT_SIMILARITY_TURN_SECONDS = 300.0


class LiveChatQueryPort(Protocol):
    def materialize_live_private_query(
        self, ticket: ChatWorkerTicket
    ) -> LiveChatQueryProjection: ...
    def authorize_live_private_query(
        self, origin: ChatPrivateQueryOrigin
    ) -> ChatPrivateQueryOrigin: ...


class ChatSimilarityCatalogPort(Protocol):
    def resolve_private_query_scope(
        self, *, actor_id: str, scope: ChatRagScope
    ) -> ChatPrivateQueryScopeReply: ...
    def read_ranked_candidates(
        self,
        *,
        actor_id: str,
        scope: ChatRagScope,
        arguments: ChatSearchArguments,
        candidates: tuple[ChatRankedCandidateKey, ...],
    ) -> ChatRankedCandidateReadReply: ...


class ChatSimilarityEvidencePort(Protocol):
    def publish_similarity_observation(
        self, record: ChatToolRecordV2, observation: ChatSimilarityObservation
    ) -> ArtifactMemberPointer: ...


@dataclass(frozen=True, slots=True)
class ChatSimilarityPorts:
    catalog: ChatSimilarityCatalogPort
    native: PrivateChatQueryPrepareClient
    evidence: ChatSimilarityEvidencePort
    stop: Event


@dataclass(frozen=True, slots=True)
class ChatSimilaritySelection:
    outcome: ChatToolOutcomeV2
    origin: ChatPrivateQueryOrigin
    scope: ChatRagScope
    status: ObservationStatus
    phase: ObservationPhase
    request: PrivateChatQueryPrepareRequest | None
    reply: PrivateChatQueryPrepareReply | None
    native_items: tuple[ChatKnowledgeItem, ...]
    error: ObservationError | None

    def observation(self, record: ChatToolRecordV2) -> ChatSimilarityObservation:
        return build_chat_similarity_observation(
            record=record,
            origin=self.origin,
            scope=self.scope,
            status=self.status,
            phase=self.phase,
            native_request=self.request,
            native_reply=self.reply,
            delivered_native_items=self.native_items,
            error_code=self.error,
        )


class ChatSimilarityTurn:
    """Identity cache only; every use rechecks the live claim and source authority."""

    def __init__(
        self,
        *,
        source: LiveChatQueryPort,
        ticket: ChatWorkerTicket,
        scope: ChatRagScope,
        ports: ChatSimilarityPorts,
    ) -> None:
        self.source, self.ticket, self.scope, self.ports = source, ticket, scope, ports
        self.deadline = monotonic() + MAX_CHAT_SIMILARITY_TURN_SECONDS
        self.original: PrivateChatQueryPrepareRequest | None = None
        self.ack: PrivateChatQueryPrepareReply | None = None
        self.last: PrivateChatQueryPrepareReply | None = None
        self.unknown = False
        self.rejected: RagError | None = None

    def _reserve_rpc(self) -> None:
        if self.ports.stop.is_set() or self.deadline - monotonic() < PRIVATE_CHAT_QUERY_RPC_TIMEOUT:
            raise ChatError("GENERAL_CHAT_APPLICATION_UNAVAILABLE")

    def _remember(self, reply: PrivateChatQueryPrepareReply) -> None:
        assert self.original is not None
        reply = validate_private_chat_query_prepare_reply(self.original, reply)
        self.ack, self.last = reply, reply

    def _read_original(self) -> PrivateChatQueryPrepareReply:
        assert self.original is not None and self.ack is not None
        self._reserve_rpc()
        reply = validate_observed_native_reply(
            self.original, self.ports.native.read_original(self.original, self.ack)
        )
        if reply.workflow_id is not None and reply.workflow_id != self.ack.workflow_id:
            raise ChatError("GENERAL_CHAT_POINTER_INVALID")
        self.last = reply
        return reply

    def _native(self) -> PrivateChatQueryPrepareReply:
        assert self.original is not None
        if self.ack is None:
            self._reserve_rpc()
            reply = wait_for_original_private_chat_query(
                self.ports.native,
                self.original,
                stop=self.ports.stop,
                deadline=self.deadline,
                on_acknowledged=self._remember,
            )
            self.last = validate_observed_native_reply(self.original, reply)
            return self.last
        if self.last is not None and self.last.status in {"FAILED", "UNAVAILABLE"}:
            return self.last
        return self._read_original()

    def select(
        self,
        *,
        actor_id: str,
        arguments: ChatSearchArguments,
        graph: ChatToolOutcomeV2,
    ) -> ChatSimilaritySelection:
        """Graph is already authorized. Caller must not pass failures or non-TOPIC work."""
        if (
            arguments.kind != "TOPIC"
            or graph.status == "FAILED"
            or graph.snapshot != self.scope.snapshot
        ):
            raise ChatError("GENERAL_CHAT_POINTER_INVALID")
        origin = self.source.materialize_live_private_query(self.ticket).origin
        if origin.actor_id != actor_id or origin.ticket != self.ticket:
            raise ChatError("GENERAL_CHAT_FORBIDDEN")
        if self.original is not None and self.original.origin != origin:
            raise ChatError("GENERAL_CHAT_POINTER_INVALID")
        phase: ObservationPhase = "SCOPE"

        def fallback(
            status: ObservationStatus,
            error: ObservationError,
            *,
            rejection: RagError | None = None,
        ) -> ChatSimilaritySelection:
            if self.source.authorize_live_private_query(origin) != origin:
                raise ChatError("GENERAL_CHAT_POINTER_INVALID")
            outcome = (
                graph
                if graph.cards and rejection is None
                else failed_rag_tool(rejection or "CHAT_KNOWLEDGE_UNAVAILABLE")
            )
            return ChatSimilaritySelection(
                outcome,
                origin,
                self.scope,
                status,
                phase,
                None if phase == "SCOPE" else self.original,
                None if phase == "SCOPE" else self.last,
                (),
                error,
            )

        def reject(code: RagError = "CHAT_KNOWLEDGE_POINTER_INVALID") -> ChatSimilaritySelection:
            self.rejected = code
            return fallback("FAILED", "INTEGRITY_REJECTED", rejection=code)

        if self.rejected is not None:
            phase = "SCOPE" if self.original is None else "QUERY"
            return reject(self.rejected)
        if self.unknown:
            phase = "QUERY"
            return fallback("UNKNOWN", "QUERY_OUTCOME_UNKNOWN")
        try:
            self._reserve_rpc()
            resolved = self.ports.catalog.resolve_private_query_scope(
                actor_id=actor_id, scope=self.scope
            )
            if resolved.status == "FAILED":
                if resolved.error_code != "CHAT_KNOWLEDGE_UNAVAILABLE":
                    return reject(
                        "CHAT_KNOWLEDGE_FORBIDDEN"
                        if resolved.error_code == "CHAT_KNOWLEDGE_FORBIDDEN"
                        else "CHAT_KNOWLEDGE_POINTER_INVALID"
                    )
                return fallback("UNAVAILABLE", "SCOPE_UNAVAILABLE")
            if resolved.scope != self.scope or resolved.graph_snapshot is None:
                raise ChatError("GENERAL_CHAT_POINTER_INVALID")
            body = dict(
                schema_version="system-rag-private-chat-query-prepare-request/1.0",
                action="PREPARE_PRIVATE_CHAT_QUERY",
                request_id="chatqueryprepare_" + origin.origin_sha256.removeprefix("sha256:")[:32],
                origin=origin.model_dump(mode="json"),
                graph_snapshot=resolved.graph_snapshot.model_dump(mode="json"),
                policy_revision_id=self.scope.policy.access_policy_revision_id,
                policy_sha256=self.scope.policy.sha256,
            )
            native = parse_private_chat_query_prepare_request(
                body | {"request_sha256": content_sha256(body)}
            )
            if self.original is not None and self.original != native:
                raise ChatError("GENERAL_CHAT_POINTER_INVALID")
            self.original = native
            phase = "QUERY"
            reply = self._native()
            if reply.status != "READY":
                if reply.status == "PENDING":
                    return fallback("PENDING", "QUERY_PENDING")
                if reply.status == "UNAVAILABLE" or reply.error_code in {
                    "AUTHORITY_UNAVAILABLE",
                    "PRIVATE_CHAT_QUERY_EXECUTION_FAILED",
                }:
                    return fallback("UNAVAILABLE", "QUERY_UNAVAILABLE")
                return reject(
                    "CHAT_KNOWLEDGE_FORBIDDEN"
                    if reply.error_code in {"SOURCE_ACCESS_DENIED", "SOURCE_REVOKED"}
                    else "CHAT_KNOWLEDGE_POINTER_INVALID"
                )
            assert reply.context is not None
            phase = "METADATA"
            if self.source.authorize_live_private_query(origin) != origin:
                raise ChatError("GENERAL_CHAT_POINTER_INVALID")
            candidates = chat_ranked_candidate_keys(reply.context)
            query = build_chat_ranked_candidate_read_request(
                actor_id=actor_id,
                scope=self.scope,
                arguments=arguments,
                candidates=candidates,
            )
            self._reserve_rpc()
            metadata = validate_chat_ranked_candidate_read_reply(
                query,
                self.ports.catalog.read_ranked_candidates(
                    actor_id=actor_id,
                    scope=self.scope,
                    arguments=arguments,
                    candidates=candidates,
                ),
            )
            if metadata.status == "FAILED":
                if metadata.error_code == "CHAT_KNOWLEDGE_UNAVAILABLE":
                    return fallback("UNAVAILABLE", "METADATA_UNAVAILABLE")
                return reject(
                    "CHAT_KNOWLEDGE_FORBIDDEN"
                    if metadata.error_code == "CHAT_KNOWLEDGE_FORBIDDEN"
                    else "CHAT_KNOWLEDGE_POINTER_INVALID"
                )
            # Reauthorize the original native population after the metadata read.
            fresh = self._read_original()
            if fresh.status != "READY" or fresh.context != reply.context:
                return reject(
                    "CHAT_KNOWLEDGE_FORBIDDEN"
                    if fresh.error_code in {"SOURCE_ACCESS_DENIED", "SOURCE_REVOKED"}
                    else "CHAT_KNOWLEDGE_POINTER_INVALID"
                )
            if self.source.authorize_live_private_query(origin) != origin:
                raise ChatError("GENERAL_CHAT_POINTER_INVALID")
            merged = list(metadata.cards)
            by_revision = {c.item.item_revision_id: c.item for c in merged}
            for card in graph.cards:
                prior = by_revision.get(card.item.item_revision_id)
                if prior is not None and prior != card.item:
                    raise ChatError("GENERAL_CHAT_POINTER_INVALID")
                if prior is None:
                    by_revision[card.item.item_revision_id] = card.item
                    merged.append(card)
            cards = tuple(merged[:6])
            outcome = ChatToolOutcomeV2(
                status="SUCCEEDED" if cards else "EMPTY",
                cards=cards,
                snapshot=self.scope.snapshot,
                truncated=metadata.truncated or graph.truncated or len(merged) > 6,
                context=None,
                rag_context=None,
                error_code=None,
            )
            return ChatSimilaritySelection(
                outcome,
                origin,
                self.scope,
                "READY",
                "COMPLETE",
                native,
                fresh,
                tuple(c.item for c in metadata.cards),
                None,
            )
        except ChatTransportError as error:
            if error.kind == "INVALID":
                return reject()
            if phase == "QUERY":
                self.unknown = True
                return fallback("UNKNOWN", "QUERY_OUTCOME_UNKNOWN")
            return fallback(
                "UNAVAILABLE", "SCOPE_UNAVAILABLE" if phase == "SCOPE" else "METADATA_UNAVAILABLE"
            )
        except ChatError as error:
            if error.code not in {"GENERAL_CHAT_APPLICATION_UNAVAILABLE", "GENERAL_CHAT_NOT_READY"}:
                return reject(
                    "CHAT_KNOWLEDGE_FORBIDDEN"
                    if error.code == "GENERAL_CHAT_FORBIDDEN"
                    else "CHAT_KNOWLEDGE_POINTER_INVALID"
                )
            return fallback(
                "UNAVAILABLE",
                "SCOPE_UNAVAILABLE"
                if phase == "SCOPE"
                else "QUERY_UNAVAILABLE"
                if phase == "QUERY"
                else "METADATA_UNAVAILABLE",
            )
        except PrivateChatQueryPrepareProtocolError as error:
            if str(error) == "PRIVATE_CHAT_QUERY_UNAVAILABLE":
                return fallback("UNAVAILABLE", "QUERY_UNAVAILABLE")
            return reject()
        except (ValueError, SchemaError):
            return reject()
