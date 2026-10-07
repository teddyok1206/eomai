"""Owner-scoped conversations, idempotent submission and immutable history projection."""

from __future__ import annotations

import base64
import re
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.general_chat import (
    CHAT_MESSAGE_SCHEMA,
    CHAT_RESULT_SCHEMA,
    ChatBoundaryValue,
    StoredChatMessage,
    read_stored_chat_message,
)
from eom_protocol.general_chat_views import (
    GeneralChatConversation,
    GeneralChatCreate,
    GeneralChatList,
    GeneralChatMessage,
    GeneralChatSlot,
    GeneralChatSubmission,
    GeneralChatSummary,
)
from eom_protocol.models import UtcDatetime
from pydantic import Field

from eom_orchestrator.general_chat_artifacts import ChatEvidencePort
from eom_orchestrator.general_chat_evidence import (
    chat_pointer,
    require_evidence,
    result_evidence,
    user_evidence,
)
from eom_orchestrator.general_chat_models import (
    GeneralChatConversationRecord,
    GeneralChatTurnRecord,
)
from eom_orchestrator.general_chat_repository import GeneralChatRepository
from eom_orchestrator.general_chat_state import ChatError, chat_runtime_available, public_chat_state


def chat_now() -> datetime:
    return datetime.now(UTC)


def chat_intent(*parts: str) -> str:
    return sha256_bytes(canonical_json_bytes(parts))


def require_chat_key(value: str) -> None:
    if re.fullmatch(r"[A-Za-z0-9_.:-]{16,128}", value) is None:
        raise ChatError("GENERAL_CHAT_IDEMPOTENCY_INVALID")


class ChatCursor(ChatBoundaryValue):
    kind: Literal["conversations", "messages"]
    scope: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    before_time: UtcDatetime | None = None
    before_id: str | None = Field(default=None, pattern=r"^chat_[0-9a-f]{32}$")
    before_sequence: int | None = Field(default=None, ge=1)

    def encode(self) -> str:
        return (
            base64.urlsafe_b64encode(
                canonical_json_bytes(self.model_dump(mode="json")),
            )
            .decode()
            .rstrip("=")
        )


def chat_cursor(
    value: str | None, *, kind: Literal["conversations", "messages"], scope: str
) -> ChatCursor | None:
    if value is None:
        return None
    try:
        if not 0 < len(value) <= 1024:
            raise ValueError("cursor bound")
        cursor = ChatCursor.model_validate_json(
            base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True),
        )
        if (cursor.kind, cursor.scope) != (kind, scope):
            raise ValueError("cursor scope")
        if kind == "conversations":
            if (
                cursor.before_time is None
                or cursor.before_id is None
                or cursor.before_sequence is not None
            ):
                raise ValueError("conversation cursor")
        elif (
            cursor.before_sequence is None
            or cursor.before_time is not None
            or cursor.before_id is not None
        ):
            raise ValueError("message cursor")
        return cursor
    except ValueError as exc:
        raise ChatError("GENERAL_CHAT_CURSOR_INVALID") from exc


class GeneralChatConversationOwner:
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

    def slot(self) -> GeneralChatSlot:
        now = self.clock()
        with self.repository.read_snapshot() as session:
            capacity = self.repository.capacity(session)
            if not chat_runtime_available(
                runtime_id=capacity.runtime_id,
                heartbeat_at=capacity.heartbeat_at,
                expires_at=capacity.expires_at,
                now=now,
            ):
                return GeneralChatSlot(
                    state="UNAVAILABLE",
                    unavailable_reason="전용 대화 서비스의 실행 상태를 확인 중입니다.",
                )
            return GeneralChatSlot(state="BUSY" if capacity.active_turn_id else "READY")

    def conversations(self, *, actor_id: str, cursor: str | None) -> GeneralChatList:
        scope = chat_intent("chat-list", actor_id)
        page = chat_cursor(cursor, kind="conversations", scope=scope)
        before = None
        if page is not None:
            assert page.before_time is not None and page.before_id is not None
            before = (page.before_time, page.before_id)
        with self.repository.read_snapshot() as session:
            self.repository.require_actor(session, actor_id)
            rows = self.repository.conversations(session, actor_id, before=before)
            values = tuple(
                GeneralChatSummary(
                    conversation_id=row.conversation_id,
                    title=row.title,
                    resource_version=row.resource_version,
                    updated_at=row.updated_at,
                )
                for row in rows[:50]
            )
        more = len(rows) > 50
        next_cursor = None
        if more:
            last = values[-1]
            next_cursor = ChatCursor(
                kind="conversations",
                scope=scope,
                before_time=last.updated_at,
                before_id=last.conversation_id,
            ).encode()
        return GeneralChatList(values=values, has_more=more, next_cursor=next_cursor)

    def create(
        self,
        *,
        actor_id: str,
        request: GeneralChatCreate,
        idempotency_key: str,
    ) -> GeneralChatConversation:
        require_chat_key(idempotency_key)
        key = chat_intent("chat-create", actor_id, idempotency_key)
        request_hash = sha256_bytes(canonical_json_bytes(request.model_dump()))
        now = self.clock()
        with self.repository.sessions.begin() as session:
            self.repository.require_actor(session, actor_id)
            self.repository.lock_intent(session, key)
            row = self.repository.create_receipt(session, actor_id, key)
            if row is not None:
                if row.create_request_sha256 != request_hash:
                    raise ChatError("GENERAL_CHAT_IDEMPOTENCY_CONFLICT")
            else:
                row = GeneralChatConversationRecord(
                    conversation_id="chat_" + sha256(key.encode()).hexdigest()[:32],
                    owner_id=actor_id,
                    title=request.title,
                    resource_version=1,
                    next_sequence=1,
                    create_key_sha256=key,
                    create_request_sha256=request_hash,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                session.flush()
            conversation_id = row.conversation_id
        return self.conversation(actor_id=actor_id, conversation_id=conversation_id, cursor=None)

    def submit(
        self,
        *,
        actor_id: str,
        conversation_id: str,
        request: GeneralChatSubmission,
        idempotency_key: str,
    ) -> GeneralChatConversation:
        require_chat_key(idempotency_key)
        key = chat_intent("chat-submit", actor_id, conversation_id, idempotency_key)
        request_hash = sha256_bytes(canonical_json_bytes(request.model_dump()))
        now = self.clock()
        with self.repository.sessions.begin() as session:
            self.repository.require_actor(session, actor_id)
            self.repository.lock_intent(session, key)
            conversation = self.repository.owned(session, actor_id, conversation_id, lock=True)
            receipt = self.repository.turn_receipt(session, conversation_id, key)
            if receipt is not None:
                if receipt.submission_request_sha256 != request_hash:
                    raise ChatError("GENERAL_CHAT_IDEMPOTENCY_CONFLICT")
            else:
                if conversation.resource_version != request.expected_version:
                    raise ChatError("GENERAL_CHAT_STALE_REVISION")
                if self.repository.active_turn(session, conversation_id):
                    raise ChatError("GENERAL_CHAT_TURN_IN_PROGRESS")
                capacity = self.repository.capacity(session)
                if not chat_runtime_available(
                    runtime_id=capacity.runtime_id,
                    heartbeat_at=capacity.heartbeat_at,
                    expires_at=capacity.expires_at,
                    now=now,
                ):
                    raise ChatError("GENERAL_CHAT_NOT_READY")
                turn_id = "chatturn_" + sha256(key.encode()).hexdigest()[:32]
                message = StoredChatMessage(
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    role="user",
                    text=request.text,
                )
                payload = canonical_json_bytes(message.model_dump())
                read_stored_chat_message(payload)
                pointer = self.evidence.publish(
                    payload=payload,
                    schema_ref=CHAT_MESSAGE_SCHEMA,
                    intent="chat-user:" + key,
                    created_at=now,
                )
                require_evidence(pointer, payload, schema_ref=CHAT_MESSAGE_SCHEMA)
                session.add(
                    GeneralChatTurnRecord(
                        turn_id=turn_id,
                        conversation_id=conversation_id,
                        user_sequence=conversation.next_sequence,
                        expected_version=request.expected_version,
                        submission_key_sha256=key,
                        submission_request_sha256=request_hash,
                        state="QUEUED",
                        input_artifact_id=pointer.artifact_id,
                        input_revision_id=pointer.artifact_revision_id,
                        input_sha256=pointer.sha256,
                        created_at=now,
                    )
                )
                conversation.next_sequence += 2
                self.repository.touch(conversation, now=now)
        return self.conversation(actor_id=actor_id, conversation_id=conversation_id, cursor=None)

    def conversation(
        self,
        *,
        actor_id: str,
        conversation_id: str,
        cursor: str | None,
    ) -> GeneralChatConversation:
        scope = chat_intent("chat-messages", actor_id, conversation_id)
        page = chat_cursor(cursor, kind="messages", scope=scope)
        with self.repository.read_snapshot() as session:
            self.repository.require_actor(session, actor_id)
            conversation = self.repository.owned(session, actor_id, conversation_id)
            rows = self.repository.history(
                session,
                conversation_id,
                limit=51,
                before=None if page is None else page.before_sequence,
            )
            selected = tuple(reversed(rows[:50]))
            more = len(rows) > 50
            title, version, updated_at = (
                conversation.title,
                conversation.resource_version,
                conversation.updated_at,
            )
        # No DB transaction remains open while materializing large canonical bytes.
        messages = self.project_messages(conversation_id, selected)
        next_cursor = None
        if more:
            next_cursor = ChatCursor(
                kind="messages",
                scope=scope,
                before_sequence=selected[0].user_sequence,
            ).encode()
        return GeneralChatConversation(
            conversation_id=conversation_id,
            title=title,
            resource_version=version,
            updated_at=updated_at,
            messages=messages,
            has_more=more,
            next_cursor=next_cursor,
        )

    def project_messages(
        self,
        conversation_id: str,
        turns: tuple[GeneralChatTurnRecord, ...],
    ) -> tuple[GeneralChatMessage, ...]:
        pointers = []
        for turn in turns:
            pointers.append(
                chat_pointer(
                    turn.input_artifact_id,
                    turn.input_revision_id,
                    turn.input_sha256,
                    CHAT_MESSAGE_SCHEMA,
                )
            )
            if turn.state == "COMPLETED":
                pointers.append(
                    chat_pointer(
                        turn.output_artifact_id,
                        turn.output_revision_id,
                        turn.output_sha256,
                        CHAT_RESULT_SCHEMA,
                    )
                )
        materialized = self.evidence.read(tuple(pointers))
        if len(materialized) != len(pointers):
            raise ChatError("GENERAL_CHAT_POINTER_INVALID")
        payloads = iter(materialized)
        messages = []
        for turn in turns:
            payload = next(payloads)
            require_evidence(
                chat_pointer(
                    turn.input_artifact_id,
                    turn.input_revision_id,
                    turn.input_sha256,
                    CHAT_MESSAGE_SCHEMA,
                ),
                payload,
                schema_ref=CHAT_MESSAGE_SCHEMA,
            )
            user = user_evidence(payload, conversation_id=conversation_id, turn_id=turn.turn_id)
            state = public_chat_state(turn.state)
            messages.append(
                GeneralChatMessage(
                    turn_id=turn.turn_id,
                    sequence=turn.user_sequence,
                    role="user",
                    text=user.text,
                    state=state,
                    created_at=turn.created_at,
                )
            )
            reply = ""
            if turn.state == "COMPLETED":
                assert turn.claim_id is not None and turn.request_sha256 is not None
                payload = next(payloads)
                require_evidence(
                    chat_pointer(
                        turn.output_artifact_id,
                        turn.output_revision_id,
                        turn.output_sha256,
                        CHAT_RESULT_SCHEMA,
                    ),
                    payload,
                    schema_ref=CHAT_RESULT_SCHEMA,
                )
                result = result_evidence(
                    payload,
                    conversation_id=conversation_id,
                    turn_id=turn.turn_id,
                    claim_id=turn.claim_id,
                    request_sha256=turn.request_sha256,
                    expected_status="SUCCEEDED",
                )
                reply = result.reply
            messages.append(
                GeneralChatMessage(
                    turn_id=turn.turn_id,
                    sequence=turn.user_sequence + 1,
                    role="assistant",
                    text=reply,
                    state=state,
                    created_at=turn.completed_at or turn.created_at,
                )
            )
        if next(payloads, None) is not None:
            raise ChatError("GENERAL_CHAT_POINTER_INVALID")
        return tuple(messages)
