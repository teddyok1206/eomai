"""Dedicated capacity claims and exact-claim worker evidence admission."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypedDict
from uuid import uuid4

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.private_chat_query_read import (
    ChatPrivateQueryOrigin,
    LiveChatQueryProjection,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat import (
    CHAT_INPUT_SCHEMA,
    CHAT_MESSAGE_SCHEMA,
    CHAT_RESULT_SCHEMA,
    ChatContextMessage,
    ChatTurnInput,
)
from eom_protocol.general_chat_dispatch import (
    CHAT_DISPATCH_SCHEMA,
    ChatDispatchReceipt,
    ChatExecutionIdentity,
    read_chat_dispatch,
)
from eom_protocol.general_chat_evidence_families import chat_evidence_schema_family
from eom_protocol.general_chat_grounding import (
    AGENT_INPUT_SCHEMA,
    AGENT_RESULT_SCHEMA,
    GROUNDED_INPUT_SCHEMA,
    GROUNDED_RESULT_SCHEMA,
    AgentChatTurnInput,
    AgentChatTurnResult,
    ChatAgentState,
    ChatKnowledgeContext,
    GroundedChatTurnInput,
    StoredGroundedChatMessage,
)
from eom_protocol.general_chat_rag_knowledge import ChatRagPolicy, ChatRagScope
from eom_protocol.general_chat_rag_turn import (
    RAG_INPUT_SCHEMA,
    RAG_RESULT_SCHEMA,
    RagChatTurnInput,
    RagChatTurnResult,
)
from eom_protocol.general_chat_turn_contracts import (
    ChatInputContract,
    ChatResultContract,
    read_chat_input,
    read_chat_result,
)
from eom_protocol.general_chat_worker_messages import (
    ChatWorkerExecute,
    ChatWorkerRequest,
    ChatWorkerTicket,
    chat_worker_protocol_version,
    chat_worker_ticket,
    read_chat_worker_ticket,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.orm import Session

from eom_orchestrator.general_chat_artifacts import ChatEvidencePort
from eom_orchestrator.general_chat_evidence import (
    chat_pointer,
    dispatch_evidence,
    request_evidence,
    require_evidence,
)
from eom_orchestrator.general_chat_knowledge import ChatKnowledgePort, ChatRagKnowledgePort
from eom_orchestrator.general_chat_models import GeneralChatCapacityRecord, GeneralChatTurnRecord
from eom_orchestrator.general_chat_owner import GeneralChatConversationOwner, chat_now
from eom_orchestrator.general_chat_rag_access import authorize_rag_context, prepare_rag_scope
from eom_orchestrator.general_chat_rag_broker import ChatRagToolBroker, rag_tool_knowledge
from eom_orchestrator.general_chat_repository import GeneralChatRepository
from eom_orchestrator.general_chat_similarity_basis import read_owned_private_chat_query
from eom_orchestrator.general_chat_state import (
    CHAT_HEARTBEAT_TTL,
    ChatError,
    ChatTurnState,
    require_chat_transition,
)
from eom_orchestrator.general_chat_tool_broker import ChatToolBroker, agent_tool_knowledge


@dataclass(frozen=True, slots=True)
class ChatClaim:
    runtime_id: str
    conversation_id: str
    turn_id: str
    claim_id: str


@dataclass(frozen=True, slots=True)
class _LiveChatToolRead:
    claim: ChatClaim
    actor_id: str
    request: ArtifactMemberPointer
    dispatch: ArtifactMemberPointer
    message: ArtifactMemberPointer


@dataclass(frozen=True, slots=True)
class _ResolvedChatExecution:
    request: ChatInputContract
    receipt: ChatDispatchReceipt
    input_member: ArtifactMemberPointer
    dispatch_member: ArtifactMemberPointer


class ChatPreparationRejected(ChatError):
    """Exact claim was terminated before any worker dispatch became admissible."""


class _PreparedChatFields(TypedDict):
    conversation_id: str
    turn_id: str
    claim_id: str
    messages: tuple[ChatContextMessage, ...]
    context_sha256: str
    knowledge: ChatKnowledgeContext | None
    agent_state: ChatAgentState | None


class GeneralChatExecutionService:
    def __init__(
        self,
        repository: GeneralChatRepository,
        evidence: ChatEvidencePort,
        *,
        clock: Callable[[], datetime] = chat_now,
        knowledge: ChatKnowledgePort | None = None,
        rag_knowledge: ChatRagKnowledgePort | None = None,
        rag_policy: ChatRagPolicy | None = None,
    ) -> None:
        self.repository = repository
        self.evidence = evidence
        self.clock = clock
        self.knowledge = knowledge
        self.rag_knowledge = rag_knowledge
        self.rag_policy = rag_policy

    def tool_broker(self, command: ChatWorkerRequest) -> ChatToolBroker | ChatRagToolBroker:
        if (
            not isinstance(command.command, ChatWorkerExecute)
            or not isinstance(command.command.turn, (AgentChatTurnInput, RagChatTurnInput))
            or self.knowledge is None
        ):
            raise ChatError("GENERAL_CHAT_PROTOCOL_INVALID")
        prepared = command.command.turn
        ticket = chat_worker_ticket(prepared, policy_sha256=command.policy_sha256)

        def require_scope() -> str:
            return self.require_live_tool_actor(ticket)

        require_scope()
        if isinstance(prepared, RagChatTurnInput):
            if self.rag_knowledge is None:
                raise ChatError("GENERAL_CHAT_NOT_READY")
            return ChatRagToolBroker(
                rpc_request_id=command.request_id,
                ticket=ticket,
                prepared=prepared,
                actor_guard=require_scope,
                knowledge=self.knowledge,
                rag_knowledge=self.rag_knowledge,
                evidence=self.evidence,
            )
        return ChatToolBroker(
            rpc_request_id=command.request_id,
            ticket=ticket,
            actor_guard=require_scope,
            knowledge=self.knowledge,
            evidence=self.evidence,
        )

    def _live_tool_read(self, ticket: ChatWorkerTicket) -> _LiveChatToolRead:
        try:
            ticket = read_chat_worker_ticket(raw_similarity_contract_value(ticket))
        except (ValueError, TypeError, SchemaError):
            raise ChatError("GENERAL_CHAT_PROTOCOL_INVALID") from None
        with self.repository.sessions.begin() as session:
            capacity = self.repository.capacity(session)
            if capacity.runtime_id is None:
                raise ChatError("GENERAL_CHAT_CLAIM_MISMATCH")
            claim = ChatClaim(
                capacity.runtime_id, ticket.conversation_id, ticket.turn_id, ticket.claim_id
            )
            _, turn = self._live_claim(session, claim)
            if turn.state != "RUNNING" or turn.request_sha256 != ticket.request_sha256:
                raise ChatError("GENERAL_CHAT_CLAIM_MISMATCH")
            conversation = self.repository.conversation_record(session, ticket.conversation_id)
            self.repository.require_actor(session, conversation.owner_id)
            return _LiveChatToolRead(
                claim,
                conversation.owner_id,
                chat_pointer(
                    turn.request_artifact_id,
                    turn.request_revision_id,
                    turn.request_sha256,
                    CHAT_INPUT_SCHEMA,
                ),
                chat_pointer(
                    turn.dispatch_artifact_id,
                    turn.dispatch_revision_id,
                    turn.dispatch_sha256,
                    CHAT_DISPATCH_SCHEMA,
                ),
                chat_pointer(
                    turn.input_artifact_id,
                    turn.input_revision_id,
                    turn.input_sha256,
                    CHAT_MESSAGE_SCHEMA,
                ),
            )

    def require_live_tool_actor(self, ticket: ChatWorkerTicket) -> str:
        """Shared live claim/actor guard; a ticket by itself is never authority."""
        return self._live_tool_read(ticket).actor_id

    def materialize_live_private_query(self, ticket: ChatWorkerTicket) -> LiveChatQueryProjection:
        """Read the exact active question, without submitting/authorizing numerical work."""
        before = self._live_tool_read(ticket)
        try:
            resolved = self._read_execution_pointers(before.claim, before.request, before.dispatch)
            if (
                not isinstance(resolved.request, RagChatTurnInput)
                or resolved.receipt.ticket != ticket
            ):
                raise ChatError("GENERAL_CHAT_POINTER_INVALID")
            question = read_owned_private_chat_query(
                self.repository,
                self.evidence,
                actor_id=before.actor_id,
                conversation_id=before.claim.conversation_id,
                turn_id=before.claim.turn_id,
            )
            last = resolved.request.messages[-1]
            if last.role != "user" or last.text != question.text:
                raise ChatError("GENERAL_CHAT_POINTER_INVALID")
            body = {
                "schema_version": "general-chat-private-query-origin/1.0",
                "actor_id": before.actor_id,
                "runtime_id": before.claim.runtime_id,
                "ticket": resolved.receipt.ticket.model_dump(mode="json"),
                "request_member": resolved.input_member.model_dump(mode="json"),
                "dispatch_member": resolved.dispatch_member.model_dump(mode="json"),
                "basis": question.basis.model_dump(mode="json"),
            }
            origin = ChatPrivateQueryOrigin.model_validate(
                body | {"origin_sha256": content_sha256(body)}
            )
            projection = LiveChatQueryProjection(
                schema_version="general-chat-private-query-projection/1.0",
                origin=origin,
                text=question.text,
            )
        except ChatError:
            raise
        except Exception:
            # A raw canonical request or schema error may contain the private question.
            raise ChatError("GENERAL_CHAT_POINTER_INVALID") from None
        if self._live_tool_read(ticket) != before:
            raise ChatError("GENERAL_CHAT_POINTER_INVALID")
        return projection

    def authorize_live_private_query(
        self, origin: ChatPrivateQueryOrigin
    ) -> ChatPrivateQueryOrigin:
        """Fresh owner/claim/pointer reauthorization; never a cached origin grant."""
        try:
            origin = ChatPrivateQueryOrigin.model_validate(raw_similarity_contract_value(origin))
        except (ValueError, TypeError, SchemaError):
            raise ChatError("GENERAL_CHAT_PROTOCOL_INVALID") from None
        current = self.materialize_live_private_query(origin.ticket).origin
        if current != origin:
            raise ChatError("GENERAL_CHAT_POINTER_INVALID")
        return current

    def heartbeat(self, *, runtime_id: str) -> None:
        """Only the resident owner, after its isolated-worker admission, calls this."""
        if re.fullmatch(r"chatrt_[0-9a-f]{32}", runtime_id) is None:
            raise ChatError("GENERAL_CHAT_RUNTIME_INVALID")
        now = self.clock()
        with self.repository.sessions.begin() as session:
            capacity = self.repository.capacity(session, lock=True)
            if capacity.runtime_id != runtime_id:
                if capacity.active_turn_id is not None:
                    raise ChatError("GENERAL_CHAT_RECONCILIATION_REQUIRED")
                if (
                    capacity.heartbeat_at is not None
                    and now - capacity.heartbeat_at <= CHAT_HEARTBEAT_TTL
                ):
                    raise ChatError("GENERAL_CHAT_RUNTIME_IN_USE")
            capacity.runtime_id = runtime_id
            capacity.heartbeat_at = now

    def withdraw(self, *, runtime_id: str) -> bool:
        """Revoke availability, preserving any exact claim and unknown execution."""
        if re.fullmatch(r"chatrt_[0-9a-f]{32}", runtime_id) is None:
            raise ChatError("GENERAL_CHAT_RUNTIME_INVALID")
        with self.repository.sessions.begin() as session:
            capacity = self.repository.capacity(session, lock=True)
            if capacity.runtime_id != runtime_id:
                return False
            # The existing capacity invariant pairs runtime/heartbeat presence.
            # Expire availability without erasing the runtime behind an active claim.
            capacity.heartbeat_at = self.clock() - CHAT_HEARTBEAT_TTL - timedelta(seconds=1)
            return True

    def claim_next(self, *, runtime_id: str) -> ChatClaim | None:
        now = self.clock()
        with self.repository.sessions.begin() as session:
            capacity = self.repository.capacity(session, lock=True)
            if (
                capacity.runtime_id != runtime_id
                or capacity.heartbeat_at is None
                or not timedelta(0) <= now - capacity.heartbeat_at <= CHAT_HEARTBEAT_TTL
            ):
                raise ChatError("GENERAL_CHAT_NOT_READY")
            if capacity.active_turn_id is not None:
                if capacity.expires_at is None or capacity.expires_at <= now:
                    raise ChatError("GENERAL_CHAT_RECONCILIATION_REQUIRED")
                return None
            turn = self.repository.next_queued(session)
            if turn is None:
                return None
            require_chat_transition(turn.state, ChatTurnState.CLAIMED)
            claim_id = "chatclaim_" + uuid4().hex
            turn.state = ChatTurnState.CLAIMED.value
            turn.claim_id = claim_id
            capacity.active_turn_id = turn.turn_id
            capacity.claim_id = claim_id
            capacity.expires_at = now + timedelta(minutes=30)
            conversation = self.repository.conversation_record(
                session, turn.conversation_id, lock=True
            )
            self.repository.touch(conversation, now=now)
            return ChatClaim(
                runtime_id=runtime_id,
                conversation_id=turn.conversation_id,
                turn_id=turn.turn_id,
                claim_id=claim_id,
            )

    def _locked_claim(
        self,
        session: Session,
        claim: ChatClaim,
    ) -> tuple[GeneralChatCapacityRecord, GeneralChatTurnRecord]:
        capacity = self.repository.capacity(session, lock=True)
        turn = self.repository.turn(session, claim.turn_id, lock=True)
        if (
            capacity.runtime_id != claim.runtime_id
            or capacity.active_turn_id != claim.turn_id
            or capacity.claim_id != claim.claim_id
            or turn.claim_id != claim.claim_id
            or turn.conversation_id != claim.conversation_id
        ):
            raise ChatError("GENERAL_CHAT_CLAIM_MISMATCH")
        return capacity, turn

    def _live_claim(
        self, session: Session, claim: ChatClaim
    ) -> tuple[GeneralChatCapacityRecord, GeneralChatTurnRecord]:
        capacity, turn = self._locked_claim(session, claim)
        if capacity.expires_at is None or capacity.expires_at <= self.clock():
            raise ChatError("GENERAL_CHAT_RECONCILIATION_REQUIRED")
        return capacity, turn

    def _recovery_claim(
        self, session: Session, claim: ChatClaim
    ) -> tuple[GeneralChatCapacityRecord, GeneralChatTurnRecord]:
        capacity, turn = self._locked_claim(session, claim)
        now = self.clock()
        if capacity.expires_at is None:
            raise ChatError("GENERAL_CHAT_RECONCILIATION_REQUIRED")
        if capacity.heartbeat_at is None or now - capacity.heartbeat_at <= CHAT_HEARTBEAT_TTL:
            raise ChatError("GENERAL_CHAT_RECOVERY_NOT_QUIESCENT")
        return capacity, turn

    def active_claim(self) -> ChatClaim | None:
        """Exact pending identity snapshot; neither takeover nor inference permission."""
        with self.repository.sessions.begin() as session:
            capacity = self.repository.capacity(session, lock=True)
            if capacity.active_turn_id is None:
                return None
            if capacity.runtime_id is None or capacity.claim_id is None:
                raise ChatError("GENERAL_CHAT_CLAIM_MISMATCH")
            turn = self.repository.turn(session, capacity.active_turn_id)
            if turn.claim_id != capacity.claim_id or turn.state not in {
                "CLAIMED",
                "RUNNING",
                "COMMITTING",
            }:
                raise ChatError("GENERAL_CHAT_CLAIM_MISMATCH")
            return ChatClaim(capacity.runtime_id, turn.conversation_id, turn.turn_id, turn.claim_id)

    def _touch(self, session: Session, turn: GeneralChatTurnRecord) -> None:
        conversation = self.repository.conversation_record(session, turn.conversation_id, lock=True)
        self.repository.touch(conversation, now=self.clock())

    def _execution(
        self, turn: GeneralChatTurnRecord, claim: ChatClaim
    ) -> tuple[ChatInputContract, ChatDispatchReceipt]:
        if (turn.conversation_id, turn.turn_id, turn.claim_id) != (
            claim.conversation_id,
            claim.turn_id,
            claim.claim_id,
        ):
            raise ChatError("GENERAL_CHAT_CLAIM_MISMATCH")
        request_pointer = chat_pointer(
            turn.request_artifact_id,
            turn.request_revision_id,
            turn.request_sha256,
            CHAT_INPUT_SCHEMA,
        )
        dispatch_pointer = chat_pointer(
            turn.dispatch_artifact_id,
            turn.dispatch_revision_id,
            turn.dispatch_sha256,
            CHAT_DISPATCH_SCHEMA,
        )
        resolved = self._read_execution_pointers(claim, request_pointer, dispatch_pointer)
        return resolved.request, resolved.receipt

    def _read_execution_pointers(
        self,
        claim: ChatClaim,
        request_pointer: ArtifactMemberPointer,
        dispatch_pointer: ArtifactMemberPointer,
    ) -> _ResolvedChatExecution:
        hints = (request_pointer, dispatch_pointer)
        resolved = self.evidence.resolve_family(hints)
        try:
            if type(resolved) is not tuple or len(resolved) != 2:
                raise ValueError("execution pointer family differs")
            checked = tuple(
                ArtifactMemberPointer.model_validate(raw_similarity_contract_value(value))
                for value in resolved
            )
            for hint, pointer in zip(hints, checked, strict=True):
                if (
                    pointer.schema_ref not in chat_evidence_schema_family(hint.schema_ref)
                    or pointer.model_copy(update={"schema_ref": hint.schema_ref}) != hint
                ):
                    raise ValueError("execution member differs from exact original pointer")
            request_pointer, dispatch_pointer = checked
        except (ValueError, TypeError, SchemaError):
            raise ChatError("GENERAL_CHAT_POINTER_INVALID") from None
        payloads = self.evidence.read((request_pointer, dispatch_pointer))
        if len(payloads) != 2:
            raise ChatError("GENERAL_CHAT_POINTER_INVALID")
        require_evidence(request_pointer, payloads[0], schema_ref=request_pointer.schema_ref)
        require_evidence(dispatch_pointer, payloads[1], schema_ref=dispatch_pointer.schema_ref)
        request = request_evidence(
            payloads[0],
            conversation_id=claim.conversation_id,
            turn_id=claim.turn_id,
            claim_id=claim.claim_id,
        )
        receipt = dispatch_evidence(payloads[1], request=request, input_pointer=request_pointer)
        if receipt.runtime_id != claim.runtime_id:
            raise ChatError("GENERAL_CHAT_CLAIM_MISMATCH")
        return _ResolvedChatExecution(request, receipt, request_pointer, dispatch_pointer)

    def execution_receipt(self, claim: ChatClaim) -> ChatDispatchReceipt:
        """Read exact canonical provenance even after expiry; never grants dispatch."""
        with self.repository.sessions.begin() as session:
            turn = self.repository.turn(session, claim.turn_id)
        _, receipt = self._execution(turn, claim)
        return receipt

    def prepare(self, claim: ChatClaim, *, identity: ChatExecutionIdentity) -> ChatInputContract:
        try:
            return self._prepare(claim, identity=identity)
        except ChatError as error:
            if error.code not in {
                "GENERAL_CHAT_FORBIDDEN",
                "GENERAL_CHAT_POINTER_INVALID",
                "GENERAL_CHAT_APPLICATION_UNAVAILABLE",
                "GENERAL_CHAT_NOT_READY",
            }:
                raise
            with self.repository.sessions.begin() as session:
                capacity, turn = self._live_claim(session, claim)
                if (
                    turn.state != "CLAIMED"
                    or turn.request_artifact_id is not None
                    or turn.dispatch_artifact_id is not None
                ):
                    raise
                require_chat_transition(turn.state, ChatTurnState.FAILED)
                turn.state = "FAILED"
                turn.failure_code = error.code
                turn.completed_at = self.clock()
                capacity.active_turn_id = None
                capacity.claim_id = None
                capacity.expires_at = None
                self._touch(session, turn)
            raise ChatPreparationRejected(error.code) from None

    def _prepare(self, claim: ChatClaim, *, identity: ChatExecutionIdentity) -> ChatInputContract:
        identity = ChatExecutionIdentity.model_validate(identity.model_dump(mode="json"))
        with self.repository.sessions.begin() as session:
            _, turn = self._live_claim(session, claim)
            if turn.state == "RUNNING":
                replay = turn
                context = None
            else:
                require_chat_transition(turn.state, ChatTurnState.RUNNING)
                replay = None
                history = self.repository.history(
                    session,
                    turn.conversation_id,
                    limit=19,
                    before=turn.user_sequence,
                    completed_only=True,
                )
                context = (*reversed(history), turn)
            conversation = self.repository.conversation_record(session, turn.conversation_id)
            actor_id = conversation.owner_id
        if replay is not None:
            request, receipt = self._execution(replay, claim)
            if receipt.identity != identity:
                raise ChatError("GENERAL_CHAT_EXECUTION_POLICY_MISMATCH")
            return request
        assert context is not None
        owner = GeneralChatConversationOwner(
            self.repository,
            self.evidence,
            clock=self.clock,
            knowledge=self.knowledge,
            rag_knowledge=self.rag_knowledge,
        )
        resolved_turns = owner.resolved_turns(claim.conversation_id, context, actor_id=actor_id)
        projected = owner.project_messages(
            claim.conversation_id, context, actor_id=actor_id, resolved=resolved_turns
        )
        messages = tuple(
            ChatContextMessage(role=value.role, text=value.text)
            for value in projected
            if value.text
        )
        # Drop only complete oldest exchanges; never truncate a scientific sentence silently.
        while len(canonical_json_bytes([value.model_dump() for value in messages])) > 128000:
            if len(messages) <= 1:
                raise ChatError("GENERAL_CHAT_CONTEXT_INVALID")
            messages = messages[2:]
        context_hash = sha256_bytes(
            canonical_json_bytes([value.model_dump() for value in messages])
        )
        input_schema = CHAT_INPUT_SCHEMA
        dispatch_schema = CHAT_DISPATCH_SCHEMA
        policy_protocol = chat_worker_protocol_version(identity.policy)
        if policy_protocol in {2, 3, 4}:
            if self.knowledge is None:
                raise ChatError("GENERAL_CHAT_NOT_READY")
            user = resolved_turns[turn.turn_id].user
            selection = user.selection if isinstance(user, StoredGroundedChatMessage) else None
            if selection is None and policy_protocol in {3, 4}:
                for previous in reversed(context[:-1]):
                    prepared_knowledge = resolved_turns[previous.turn_id].item
                    if prepared_knowledge is not None:
                        selection = prepared_knowledge.selection
                        break
            # Follow-up questions reuse the last explicit pinned selection, never latest.
            if selection is None and not isinstance(user, StoredGroundedChatMessage):
                for t in reversed(context[:-1]):
                    message = resolved_turns[t.turn_id].user
                    if isinstance(message, StoredGroundedChatMessage):
                        selection = message.selection
                        break
            resolved_knowledge = self.knowledge.resolve(
                actor_id=actor_id, selection=selection, purpose="MATERIALIZE"
            )
            prepared_values = _PreparedChatFields(
                conversation_id=claim.conversation_id,
                turn_id=claim.turn_id,
                claim_id=claim.claim_id,
                messages=messages,
                context_sha256=context_hash,
                knowledge=resolved_knowledge.context,
                agent_state=resolved_knowledge.agent_state,
            )
            if policy_protocol == 4:
                if self.rag_knowledge is None or self.rag_policy is None:
                    raise ChatError("GENERAL_CHAT_NOT_READY")
                prior_rag = None
                prior_scope = None
                for previous in reversed(context[:-1]):
                    history_value = resolved_turns[previous.turn_id]
                    if isinstance(history_value.request, RagChatTurnInput):
                        prior_rag = history_value.rag
                        prior_scope = history_value.request.rag_scope
                        break
                snapshot = None if selection is None else selection.snapshot
                if prior_scope is not None:
                    if snapshot is not None and snapshot != prior_scope.snapshot:
                        raise ChatError("GENERAL_CHAT_POINTER_INVALID")
                    snapshot = prior_scope.snapshot
                rag_scope: ChatRagScope | None
                if prior_rag is not None:
                    authorize_rag_context(self.rag_knowledge, actor_id=actor_id, context=prior_rag)
                    rag_scope = prior_rag.scope
                else:
                    rag_scope = prepare_rag_scope(
                        self.rag_knowledge,
                        actor_id=actor_id,
                        policy=self.rag_policy if prior_scope is None else prior_scope.policy,
                        snapshot=snapshot,
                    )
                request = RagChatTurnInput(
                    **prepared_values, rag_scope=rag_scope, rag_knowledge=prior_rag
                )
            else:
                input_type = AgentChatTurnInput if policy_protocol == 3 else GroundedChatTurnInput
                request = input_type(**prepared_values)
            input_schema = (
                RAG_INPUT_SCHEMA
                if isinstance(request, RagChatTurnInput)
                else AGENT_INPUT_SCHEMA
                if isinstance(request, AgentChatTurnInput)
                else GROUNDED_INPUT_SCHEMA
            )
            dispatch_schema = (
                "eom://schemas/general-chat/dispatch/5.0"
                if identity.policy.schema_version == "general-chat-worker-policy/5.0"
                else "eom://schemas/general-chat/dispatch/4.0"
                if isinstance(request, RagChatTurnInput)
                else "eom://schemas/general-chat/dispatch/3.0"
                if isinstance(request, AgentChatTurnInput)
                else "eom://schemas/general-chat/dispatch/2.0"
            )
        else:
            request = ChatTurnInput(
                conversation_id=claim.conversation_id,
                turn_id=claim.turn_id,
                claim_id=claim.claim_id,
                messages=messages,
                context_sha256=context_hash,
            )
        read_chat_input(request.model_dump(mode="json"))
        payload = canonical_json_bytes(request.model_dump(mode="json"))
        pointer = self.evidence.publish(
            payload=payload,
            schema_ref=input_schema,
            intent="chat-request:" + claim.claim_id,
            created_at=self.clock(),
        )
        require_evidence(pointer, payload, schema_ref=input_schema)
        dispatch = read_chat_dispatch(
            ChatDispatchReceipt(
                schema_version="general-chat-dispatch/5.0"
                if identity.policy.schema_version == "general-chat-worker-policy/5.0"
                else "general-chat-dispatch/4.0"
                if isinstance(request, RagChatTurnInput)
                else "general-chat-dispatch/3.0"
                if isinstance(request, AgentChatTurnInput)
                else "general-chat-dispatch/2.0"
                if isinstance(request, GroundedChatTurnInput)
                else "general-chat-dispatch/1.0",
                runtime_id=claim.runtime_id,
                identity=identity,
                ticket=chat_worker_ticket(request, policy_sha256=identity.policy.sha256),
                input=pointer,
            ).model_dump(mode="json")
        )
        dispatch_payload = canonical_json_bytes(dispatch.model_dump(mode="json"))
        dispatch_pointer = self.evidence.publish(
            payload=dispatch_payload,
            schema_ref=dispatch_schema,
            intent="chat-dispatch:" + claim.claim_id,
            created_at=self.clock(),
        )
        require_evidence(dispatch_pointer, dispatch_payload, schema_ref=dispatch_schema)
        with self.repository.sessions.begin() as session:
            _, turn = self._live_claim(session, claim)
            if turn.state == "RUNNING":
                if (turn.request_sha256, turn.dispatch_sha256) != (
                    pointer.sha256,
                    dispatch_pointer.sha256,
                ):
                    raise ChatError("GENERAL_CHAT_REQUEST_CONFLICT")
            else:
                require_chat_transition(turn.state, ChatTurnState.RUNNING)
                turn.request_artifact_id = pointer.artifact_id
                turn.request_revision_id = pointer.artifact_revision_id
                turn.request_sha256 = pointer.sha256
                turn.dispatch_artifact_id = dispatch_pointer.artifact_id
                turn.dispatch_revision_id = dispatch_pointer.artifact_revision_id
                turn.dispatch_sha256 = dispatch_pointer.sha256
                turn.state = ChatTurnState.RUNNING.value
                self._touch(session, turn)
        return request

    def complete(self, claim: ChatClaim, result: ChatResultContract) -> None:
        self._complete(claim, result, guard=self._live_claim)

    def reconcile_known_result(self, claim: ChatClaim, result: ChatResultContract) -> None:
        """Finish only an exact quiescent known claim; never renew/re-execute it."""
        self._complete(claim, result, guard=self._recovery_claim)

    def _complete(
        self,
        claim: ChatClaim,
        result: ChatResultContract,
        *,
        guard: Callable[
            [Session, ChatClaim], tuple[GeneralChatCapacityRecord, GeneralChatTurnRecord]
        ],
    ) -> None:
        with self.repository.sessions.begin() as session:
            turn = self.repository.turn(session, claim.turn_id)
            if (turn.conversation_id, turn.claim_id) != (claim.conversation_id, claim.claim_id):
                raise ChatError("GENERAL_CHAT_CLAIM_MISMATCH")
            actor_id = self.repository.conversation_record(session, claim.conversation_id).owner_id
        request, _ = self._execution(turn, claim)
        read_chat_result(result.model_dump(mode="json"), request=request)
        if isinstance(request, AgentChatTurnInput) and isinstance(result, AgentChatTurnResult):
            agent_tool_knowledge(request, result, self.evidence)
        elif isinstance(request, RagChatTurnInput) and isinstance(result, RagChatTurnResult):
            resolved = rag_tool_knowledge(request, result, self.evidence)
            if result.status == "SUCCEEDED":
                with self.repository.read_snapshot() as session:
                    self.repository.require_actor(session, actor_id)
                if resolved.selections and self.knowledge is None:
                    raise ChatError("GENERAL_CHAT_FORBIDDEN")
                for selection in resolved.selections:
                    assert self.knowledge is not None
                    self.knowledge.resolve(
                        actor_id=actor_id, selection=selection, purpose="AUTHORIZE"
                    )
                for rag_context in resolved.rag_contexts:
                    authorize_rag_context(
                        self.rag_knowledge, actor_id=actor_id, context=rag_context
                    )
        result_schema = (
            RAG_RESULT_SCHEMA
            if isinstance(request, RagChatTurnInput)
            else AGENT_RESULT_SCHEMA
            if isinstance(request, AgentChatTurnInput)
            else GROUNDED_RESULT_SCHEMA
            if isinstance(request, GroundedChatTurnInput)
            else CHAT_RESULT_SCHEMA
        )
        payload = canonical_json_bytes(result.model_dump(mode="json"))
        digest = sha256_bytes(payload)
        with self.repository.sessions.begin() as session:
            self.repository.capacity(session, lock=True)
            turn = self.repository.turn(session, claim.turn_id, lock=True)
            if turn.state in {"COMPLETED", "FAILED"}:
                if turn.result_sha256 != digest:
                    raise ChatError("GENERAL_CHAT_RESULT_CONFLICT")
                return
            _, turn = guard(session, claim)
            if isinstance(request, RagChatTurnInput) and result.status == "SUCCEEDED":
                self.repository.require_actor(session, actor_id)
            if turn.state == "COMMITTING":
                if turn.result_sha256 != digest:
                    raise ChatError("GENERAL_CHAT_RESULT_CONFLICT")
            else:
                # Pin every terminal result before file publication, including failure.
                # Otherwise competing success/failure reports can commit incompatible evidence.
                require_chat_transition(turn.state, ChatTurnState.COMMITTING)
                turn.state = ChatTurnState.COMMITTING.value
                turn.result_sha256 = digest
                turn.result_status = result.status
                turn.failure_code = result.failure_code
                self._touch(session, turn)
        pointer = self.evidence.publish(
            payload=payload,
            schema_ref=result_schema,
            intent="chat-result:" + claim.claim_id,
            created_at=self.clock(),
        )
        require_evidence(pointer, payload, schema_ref=result_schema)
        with self.repository.sessions.begin() as session:
            # Serialize final admission with claims; a duplicate completion may arrive
            # after another valid completion has already released the capacity.
            self.repository.capacity(session, lock=True)
            turn = self.repository.turn(session, claim.turn_id, lock=True)
            if turn.state in {"COMPLETED", "FAILED"}:
                if turn.result_sha256 != digest or turn.claim_id != claim.claim_id:
                    raise ChatError("GENERAL_CHAT_RESULT_CONFLICT")
                return
            capacity, turn = guard(session, claim)
            if isinstance(request, RagChatTurnInput) and result.status == "SUCCEEDED":
                self.repository.require_actor(session, actor_id)
            target = (
                ChatTurnState.COMPLETED if result.status == "SUCCEEDED" else ChatTurnState.FAILED
            )
            require_chat_transition(turn.state, target)
            turn.state = target.value
            turn.output_artifact_id = pointer.artifact_id
            turn.output_revision_id = pointer.artifact_revision_id
            turn.output_sha256 = pointer.sha256
            turn.result_sha256 = digest
            turn.failure_code = result.failure_code
            turn.completed_at = self.clock()
            capacity.active_turn_id = None
            capacity.claim_id = None
            capacity.expires_at = None
            self._touch(session, turn)
