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
)
from eom_protocol.general_chat_grounding import (
    GROUNDED_MESSAGE_SCHEMA,
    ChatGroundingViews,
    ChatInputContract,
    ChatKnowledgeItem,
    ChatKnowledgeSelection,
    ChatKnowledgeSnapshot,
    ChatKnowledgeSourceCard,
    ChatResultContract,
    ChatTurnGroundingView,
    GroundedChatSubmission,
    GroundedChatTurnInput,
    GroundedChatTurnResult,
    StoredGroundedChatMessage,
    read_chat_result,
    read_grounding,
    validate_chat_citations,
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
    request_evidence,
    require_evidence,
    result_evidence,
    user_evidence,
)
from eom_orchestrator.general_chat_knowledge import ChatKnowledgePort
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
        knowledge: ChatKnowledgePort | None = None,
    ) -> None:
        self.repository = repository
        self.evidence = evidence
        self.clock = clock
        self.knowledge = knowledge

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
        request: GeneralChatSubmission | GroundedChatSubmission,
        idempotency_key: str,
    ) -> GeneralChatConversation:
        require_chat_key(idempotency_key)
        key = chat_intent("chat-submit", actor_id, conversation_id, idempotency_key)
        if isinstance(request, GroundedChatSubmission) and request.selection is not None:
            if self.knowledge is None:
                raise ChatError("GENERAL_CHAT_NOT_READY")
            self.knowledge.resolve(
                actor_id=actor_id, selection=request.selection, purpose="AUTHORIZE"
            )
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
                message: StoredChatMessage | StoredGroundedChatMessage
                if isinstance(request, GroundedChatSubmission):
                    message = StoredGroundedChatMessage(
                        conversation_id=conversation_id,
                        turn_id=turn_id,
                        text=request.text,
                        selection=request.selection,
                    )
                else:
                    message = StoredChatMessage(
                        conversation_id=conversation_id,
                        turn_id=turn_id,
                        role="user",
                        text=request.text,
                    )
                payload = canonical_json_bytes(message.model_dump())
                message_schema = (
                    GROUNDED_MESSAGE_SCHEMA
                    if isinstance(message, StoredGroundedChatMessage)
                    else CHAT_MESSAGE_SCHEMA
                )
                user_evidence(payload, conversation_id=conversation_id, turn_id=turn_id)
                pointer = self.evidence.publish(
                    payload=payload,
                    schema_ref=message_schema,
                    intent="chat-user:" + key,
                    created_at=now,
                )
                require_evidence(pointer, payload, schema_ref=message_schema)
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
        messages = self.project_messages(conversation_id, selected, actor_id=actor_id)
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

    def resolved_turns(
        self,
        conversation_id: str,
        turns: tuple[GeneralChatTurnRecord, ...],
        *,
        actor_id: str | None,
    ) -> dict[
        str,
        tuple[
            StoredChatMessage | StoredGroundedChatMessage,
            ChatInputContract | None,
            ChatResultContract | None,
        ],
    ]:
        hints = []
        for turn in turns:
            hints.append(
                chat_pointer(
                    turn.input_artifact_id,
                    turn.input_revision_id,
                    turn.input_sha256,
                    CHAT_MESSAGE_SCHEMA,
                )
            )
            if turn.state == "COMPLETED":
                hints.append(
                    chat_pointer(
                        turn.request_artifact_id,
                        turn.request_revision_id,
                        turn.request_sha256,
                        "eom://schemas/general-chat/turn-input/1.0",
                    )
                )
                hints.append(
                    chat_pointer(
                        turn.output_artifact_id,
                        turn.output_revision_id,
                        turn.output_sha256,
                        CHAT_RESULT_SCHEMA,
                    )
                )
        pointers = self.evidence.resolve_family(tuple(hints))
        materialized = self.evidence.read(pointers)
        if len(materialized) != len(pointers):
            raise ChatError("GENERAL_CHAT_POINTER_INVALID")
        payloads = iter(zip(pointers, materialized, strict=True))
        result = {}
        groups: dict[ChatKnowledgeSnapshot | None, dict[str, ChatKnowledgeItem]] = {}
        for turn in turns:
            pointer, payload = next(payloads)
            require_evidence(pointer, payload, schema_ref=pointer.schema_ref)
            user = user_evidence(payload, conversation_id=conversation_id, turn_id=turn.turn_id)
            request = None
            answer = None
            selections = []
            if isinstance(user, StoredGroundedChatMessage) and user.selection is not None:
                selections.append(user.selection)
            if turn.state == "COMPLETED":
                if turn.claim_id is None or turn.request_sha256 is None:
                    raise ChatError("GENERAL_CHAT_POINTER_INVALID")
                pointer, payload = next(payloads)
                require_evidence(pointer, payload, schema_ref=pointer.schema_ref)
                request = request_evidence(
                    payload,
                    conversation_id=conversation_id,
                    turn_id=turn.turn_id,
                    claim_id=turn.claim_id,
                )
                pointer, payload = next(payloads)
                require_evidence(pointer, payload, schema_ref=pointer.schema_ref)
                answer = result_evidence(
                    payload,
                    conversation_id=conversation_id,
                    turn_id=turn.turn_id,
                    claim_id=turn.claim_id,
                    request_sha256=turn.request_sha256,
                    expected_status="SUCCEEDED",
                )
                read_chat_result(answer.model_dump(mode="json"), request=request)
                if isinstance(request, GroundedChatTurnInput) and request.knowledge is not None:
                    selections.append(request.knowledge.selection)
            for selection in selections:
                group = groups.setdefault(selection.snapshot, {})
                for ref in selection.references:
                    existing = group.get(ref.item_revision_id)
                    if existing is not None and existing != ref:
                        raise ChatError("GENERAL_CHAT_POINTER_INVALID")
                    group[ref.item_revision_id] = ref
            result[turn.turn_id] = (user, request, answer)
        if next(payloads, None) is not None:
            raise ChatError("GENERAL_CHAT_POINTER_INVALID")
        for snapshot, group in groups.items():
            if self.knowledge is None or actor_id is None:
                raise ChatError("GENERAL_CHAT_FORBIDDEN")
            refs = tuple(group.values())
            for index in range(0, len(refs), 3):
                self.knowledge.resolve(
                    actor_id=actor_id,
                    selection=ChatKnowledgeSelection(
                        references=refs[index : index + 3], snapshot=snapshot
                    ),
                    purpose="AUTHORIZE",
                )
        return result

    def project_messages(
        self,
        conversation_id: str,
        turns: tuple[GeneralChatTurnRecord, ...],
        *,
        actor_id: str | None = None,
    ) -> tuple[GeneralChatMessage, ...]:
        resolved = self.resolved_turns(conversation_id, turns, actor_id=actor_id)
        messages = []
        for turn in turns:
            user, _, answer = resolved[turn.turn_id]
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
            messages.append(
                GeneralChatMessage(
                    turn_id=turn.turn_id,
                    sequence=turn.user_sequence + 1,
                    role="assistant",
                    text="" if answer is None else answer.reply,
                    state=state,
                    created_at=turn.completed_at or turn.created_at,
                )
            )
        return tuple(messages)

    def grounding(
        self, *, actor_id: str, conversation_id: str, turn_ids: tuple[str, ...]
    ) -> ChatGroundingViews:
        if not 1 <= len(turn_ids) <= 50 or len(set(turn_ids)) != len(turn_ids):
            raise ChatError("GENERAL_CHAT_PROTOCOL_INVALID")
        from sqlalchemy import select

        with self.repository.read_snapshot() as session:
            self.repository.require_actor(session, actor_id)
            self.repository.owned(session, actor_id, conversation_id)
            rows = tuple(
                session.scalars(
                    select(GeneralChatTurnRecord)
                    .where(
                        GeneralChatTurnRecord.conversation_id == conversation_id,
                        GeneralChatTurnRecord.turn_id.in_(turn_ids),
                    )
                    .order_by(GeneralChatTurnRecord.user_sequence)
                )
            )
        if {row.turn_id for row in rows} != set(turn_ids):
            raise ChatError("GENERAL_CHAT_NOT_FOUND")
        resolved = self.resolved_turns(conversation_id, rows, actor_id=actor_id)
        values = []
        for row in rows:
            _, request, answer = resolved[row.turn_id]
            sources: tuple[ChatKnowledgeSourceCard, ...] = ()
            receipt = None
            observed = None
            if isinstance(request, GroundedChatTurnInput) and isinstance(
                answer, GroundedChatTurnResult
            ):
                receipt = validate_chat_citations(request, answer)
                observed = None if request.agent_state is None else request.agent_state.observed_at
                if request.knowledge is not None:
                    sources = tuple(
                        ChatKnowledgeSourceCard.model_validate(
                            source.model_dump(
                                mode="json",
                                include={
                                    "key",
                                    "item",
                                    "display_name",
                                    "kind",
                                    "approval",
                                    "location",
                                },
                            )
                        )
                        for source in request.knowledge.sources
                        if source.key in receipt.used_source_keys
                    )
            values.append(
                ChatTurnGroundingView(
                    turn_id=row.turn_id, sources=sources, receipt=receipt, observed_at=observed
                )
            )
        return read_grounding(
            "Views",
            ChatGroundingViews(conversation_id=conversation_id, values=tuple(values)).model_dump(
                mode="json"
            ),
            ChatGroundingViews,
        )
