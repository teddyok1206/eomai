"""Dedicated capacity claims and exact-claim worker evidence admission."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.general_chat import (
    CHAT_INPUT_SCHEMA,
    CHAT_RESULT_SCHEMA,
    ChatContextMessage,
    ChatTurnInput,
    ChatTurnResult,
    read_chat_turn_input,
    read_chat_turn_result,
)
from sqlalchemy.orm import Session

from eom_orchestrator.general_chat_artifacts import ChatEvidencePort
from eom_orchestrator.general_chat_evidence import (
    chat_pointer,
    request_evidence,
    require_evidence,
)
from eom_orchestrator.general_chat_models import GeneralChatCapacityRecord, GeneralChatTurnRecord
from eom_orchestrator.general_chat_owner import GeneralChatConversationOwner, chat_now
from eom_orchestrator.general_chat_repository import GeneralChatRepository
from eom_orchestrator.general_chat_state import (
    CHAT_HEARTBEAT_TTL,
    ChatError,
    ChatTurnState,
    require_chat_transition,
)


@dataclass(frozen=True, slots=True)
class ChatClaim:
    runtime_id: str
    conversation_id: str
    turn_id: str
    claim_id: str


class GeneralChatExecutionService:
    def __init__(
        self,
        repository: GeneralChatRepository,
        evidence: ChatEvidencePort,
        *,
        clock: Callable[[], datetime] = chat_now,
    ) -> None:
        self.repository = repository
        self.evidence = evidence
        self.clock = clock

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
        if capacity.expires_at is None or capacity.expires_at <= self.clock():
            raise ChatError("GENERAL_CHAT_RECONCILIATION_REQUIRED")
        return capacity, turn

    def _touch(self, session: Session, turn: GeneralChatTurnRecord) -> None:
        conversation = self.repository.conversation_record(session, turn.conversation_id, lock=True)
        self.repository.touch(conversation, now=self.clock())

    def _request(self, turn: GeneralChatTurnRecord) -> ChatTurnInput:
        pointer = chat_pointer(
            turn.request_artifact_id,
            turn.request_revision_id,
            turn.request_sha256,
            CHAT_INPUT_SCHEMA,
        )
        payloads = self.evidence.read((pointer,))
        if len(payloads) != 1 or turn.claim_id is None:
            raise ChatError("GENERAL_CHAT_POINTER_INVALID")
        require_evidence(pointer, payloads[0], schema_ref=CHAT_INPUT_SCHEMA)
        return request_evidence(
            payloads[0],
            conversation_id=turn.conversation_id,
            turn_id=turn.turn_id,
            claim_id=turn.claim_id,
        )

    def prepare(self, claim: ChatClaim) -> ChatTurnInput:
        with self.repository.sessions.begin() as session:
            _, turn = self._locked_claim(session, claim)
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
        if replay is not None:
            return self._request(replay)
        assert context is not None
        owner = GeneralChatConversationOwner(self.repository, self.evidence, clock=self.clock)
        projected = owner.project_messages(claim.conversation_id, context)
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
        request = ChatTurnInput(
            conversation_id=claim.conversation_id,
            turn_id=claim.turn_id,
            claim_id=claim.claim_id,
            messages=messages,
            context_sha256=sha256_bytes(
                canonical_json_bytes([value.model_dump() for value in messages])
            ),
        )
        read_chat_turn_input(request.model_dump(mode="json"))
        payload = canonical_json_bytes(request.model_dump(mode="json"))
        pointer = self.evidence.publish(
            payload=payload,
            schema_ref=CHAT_INPUT_SCHEMA,
            intent="chat-request:" + claim.claim_id,
            created_at=self.clock(),
        )
        require_evidence(pointer, payload, schema_ref=CHAT_INPUT_SCHEMA)
        with self.repository.sessions.begin() as session:
            _, turn = self._locked_claim(session, claim)
            if turn.state == "RUNNING":
                if turn.request_sha256 != pointer.sha256:
                    raise ChatError("GENERAL_CHAT_REQUEST_CONFLICT")
            else:
                require_chat_transition(turn.state, ChatTurnState.RUNNING)
                turn.request_artifact_id = pointer.artifact_id
                turn.request_revision_id = pointer.artifact_revision_id
                turn.request_sha256 = pointer.sha256
                turn.state = ChatTurnState.RUNNING.value
                self._touch(session, turn)
        return request

    def complete(self, claim: ChatClaim, result: ChatTurnResult) -> None:
        with self.repository.sessions.begin() as session:
            turn = self.repository.turn(session, claim.turn_id)
            if (turn.conversation_id, turn.claim_id) != (claim.conversation_id, claim.claim_id):
                raise ChatError("GENERAL_CHAT_CLAIM_MISMATCH")
        request = self._request(turn)
        read_chat_turn_result(result.model_dump(mode="json"), request=request)
        payload = canonical_json_bytes(result.model_dump(mode="json"))
        digest = sha256_bytes(payload)
        with self.repository.sessions.begin() as session:
            self.repository.capacity(session, lock=True)
            turn = self.repository.turn(session, claim.turn_id, lock=True)
            if turn.state in {"COMPLETED", "FAILED"}:
                if turn.result_sha256 != digest:
                    raise ChatError("GENERAL_CHAT_RESULT_CONFLICT")
                return
            _, turn = self._locked_claim(session, claim)
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
            schema_ref=CHAT_RESULT_SCHEMA,
            intent="chat-result:" + claim.claim_id,
            created_at=self.clock(),
        )
        require_evidence(pointer, payload, schema_ref=CHAT_RESULT_SCHEMA)
        with self.repository.sessions.begin() as session:
            # Serialize final admission with claims; a duplicate completion may arrive
            # after another valid completion has already released the capacity.
            self.repository.capacity(session, lock=True)
            turn = self.repository.turn(session, claim.turn_id, lock=True)
            if turn.state in {"COMPLETED", "FAILED"}:
                if turn.result_sha256 != digest or turn.claim_id != claim.claim_id:
                    raise ChatError("GENERAL_CHAT_RESULT_CONFLICT")
                return
            capacity, turn = self._locked_claim(session, claim)
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
