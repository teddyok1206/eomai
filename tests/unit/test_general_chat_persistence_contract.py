from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from eom_api_contracts.general_chat import GeneralChatCreate as ApiChatCreate
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.general_chat_evidence import require_evidence, user_evidence
from eom_orchestrator.general_chat_models import (
    GeneralChatCapacityRecord,
    GeneralChatConversationRecord,
    GeneralChatTurnRecord,
)
from eom_orchestrator.general_chat_owner import ChatCursor, chat_cursor, chat_intent
from eom_orchestrator.general_chat_state import (
    CHAT_TRANSITIONS,
    ChatError,
    ChatTurnState,
    public_chat_state,
    require_chat_transition,
)
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat import (
    CHAT_MEMBER,
    CHAT_MESSAGE_SCHEMA,
    StoredChatMessage,
    read_stored_chat_message,
)
from eom_protocol.general_chat_views import GeneralChatCreate
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError
from sqlalchemy import ForeignKeyConstraint, LargeBinary, Table

ROOT = Path(__file__).resolve().parents[2]
MODELS = (GeneralChatConversationRecord, GeneralChatTurnRecord, GeneralChatCapacityRecord)


@pytest.mark.parametrize("prior", list(ChatTurnState))
@pytest.mark.parametrize("target", list(ChatTurnState))
def test_chat_transition_table_is_explicit_and_terminal_history_cannot_resume(
    prior: ChatTurnState,
    target: ChatTurnState,
) -> None:
    if target in CHAT_TRANSITIONS[prior]:
        require_chat_transition(prior.value, target)
    else:
        with pytest.raises(ChatError, match="INVALID_TRANSITION"):
            require_chat_transition(prior.value, target)


def test_public_contract_is_shared_without_orchestrator_to_api_dependency() -> None:
    assert ApiChatCreate is GeneralChatCreate
    for path in (ROOT / "services/orchestrator/eom_orchestrator").glob("general_chat*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(("eom_api", "eom_api_contracts"))
    for state in ChatTurnState:
        assert public_chat_state(state.value) in {
            "QUEUED",
            "RUNNING",
            "COMPLETED",
            "FAILED",
            "CANCELLED",
        }
    with pytest.raises(ChatError, match="INVALID_STATE"):
        public_chat_state("invented")


def test_chat_models_have_pointer_only_rows_and_independent_indexed_capacity() -> None:
    for model in MODELS:
        table = cast(Table, model.__table__)
        assert not any(isinstance(column.type, LargeBinary) for column in table.columns)
        assert not {"text", "reply", "messages", "content", "transcript"} & set(
            table.columns.keys()
        )
        assert not {"worker_slot_id", "worker_lease_id", "native_thread_id"} & set(
            table.columns.keys()
        )
        assert all(len(str(value.name).encode()) <= 63 for value in table.constraints if value.name)
        assert all(len(str(value.name).encode()) <= 63 for value in table.indexes)
    turn = cast(Table, GeneralChatTurnRecord.__table__)
    foreign = {value.name for value in turn.constraints if isinstance(value, ForeignKeyConstraint)}
    assert {
        "fk_chat_input_revision",
        "fk_chat_request_revision",
        "fk_chat_output_revision",
    } <= foreign
    indexes = {str(value.name): value for value in turn.indexes}
    assert set(indexes) == {"uq_chat_one_active", "ix_chat_fifo"}
    assert indexes["uq_chat_one_active"].unique
    assert "QUEUED" in str(indexes["ix_chat_fifo"].dialect_options["postgresql"]["where"])


@pytest.mark.parametrize(
    "canonical,leaf",
    [
        (
            "schemas/artifact-member/artifact-member-v1.schema.json",
            "artifact-member-v1.schema.json",
        ),
        (
            "schemas/general-chat/general-chat-message.schema.json",
            "general-chat-message.schema.json",
        ),
    ],
)
def test_stored_contract_package_mirrors_and_schema_dialect(canonical: str, leaf: str) -> None:
    payload = (ROOT / canonical).read_bytes()
    assert payload == (ROOT / "packages/protocol/eom_protocol/schemas" / leaf).read_bytes()
    schema = json.loads(payload)
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "member", ["/absolute", "../escape", "a/../b", "a//b", "a\\b", "a/", "a\x00b"]
)
def test_neutral_member_pointer_rejects_unsafe_paths_in_schema_and_model(member: str) -> None:
    document = {
        "artifact_id": "artifact_" + "1" * 32,
        "artifact_revision_id": "rev_" + "2" * 32,
        "member_path": member,
        "schema_ref": CHAT_MESSAGE_SCHEMA,
        "media_type": "application/json",
        "sha256": "sha256:" + "3" * 64,
    }
    schema = json.loads(
        (ROOT / "schemas/artifact-member/artifact-member-v1.schema.json").read_bytes()
    )
    with pytest.raises(SchemaError):
        Draft202012Validator(schema).validate(document)
    with pytest.raises(ValidationError):
        ArtifactMemberPointer.model_validate(document)


def test_message_evidence_binds_role_conversation_turn_and_hash() -> None:
    message = StoredChatMessage(
        conversation_id="chat_" + "1" * 32,
        turn_id="chatturn_" + "2" * 32,
        role="user",
        text="한글 질문",
    )
    payload = canonical_json_bytes(message.model_dump())
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + "3" * 32,
        artifact_revision_id="rev_" + "4" * 32,
        member_path=CHAT_MEMBER,
        schema_ref=CHAT_MESSAGE_SCHEMA,
        media_type="application/json",
        sha256=sha256_bytes(payload),
    )
    assert (
        user_evidence(payload, conversation_id=message.conversation_id, turn_id=message.turn_id)
        == message
    )
    require_evidence(pointer, payload, schema_ref=CHAT_MESSAGE_SCHEMA)
    with pytest.raises(ChatError, match="POINTER_INVALID"):
        user_evidence(payload, conversation_id="chat_" + "9" * 32, turn_id=message.turn_id)
    with pytest.raises(ChatError, match="POINTER_INVALID"):
        require_evidence(pointer, payload + b" ", schema_ref=CHAT_MESSAGE_SCHEMA)
    for text in ("", "   ", "nul\x00", "x" * 16001):
        with pytest.raises((SchemaError, ValidationError)):
            read_stored_chat_message(canonical_json_bytes({**message.model_dump(), "text": text}))
    with pytest.raises(ValidationError):
        message.text = "mutated"  # type: ignore[misc]


def test_cursor_scoped_to_owner_conversation_and_projection_kind() -> None:
    scope = chat_intent("owner", "conversation")
    encoded = ChatCursor(kind="messages", scope=scope, before_sequence=51).encode()
    parsed = chat_cursor(encoded, kind="messages", scope=scope)
    assert parsed is not None and parsed.before_sequence == 51
    for value, kind, other_scope in (
        (encoded, "messages", chat_intent("other-owner")),
        (encoded, "conversations", scope),
        ("not base64!", "messages", scope),
        ("x" * 1025, "messages", scope),
        (
            ChatCursor(kind="messages", scope=scope, before_time=datetime.now(UTC)).encode(),
            "messages",
            scope,
        ),
    ):
        with pytest.raises(ChatError, match="CURSOR_INVALID"):
            chat_cursor(value, kind=kind, scope=other_scope)  # type: ignore[arg-type]
    assert chat_intent("a", "bc") != chat_intent("ab", "c")
