"""Pinned text sources and citation integrity: no DB, network or model consumption."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat import ChatContextMessage, read_chat_turn_input
from eom_protocol.general_chat_grounding import (
    ChatAnswerSection,
    ChatCitationReceipt,
    ChatGroundedAnswer,
    ChatKnowledgeContext,
    ChatKnowledgeItem,
    ChatKnowledgeSelection,
    ChatKnowledgeSnapshot,
    ChatKnowledgeSource,
    GroundedChatSubmission,
    GroundedChatTurnInput,
    GroundedChatTurnResult,
    StoredGroundedChatMessage,
    chat_knowledge_context,
    grounding_validator,
    read_grounded_chat_input,
    read_grounded_chat_result,
    read_grounding,
    validate_chat_citations,
)
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
HASH = "sha256:" + "a" * 64


def item(number: int = 1) -> ChatKnowledgeItem:
    return ChatKnowledgeItem(
        item_id=f"item_{number:032x}",
        item_revision_id=f"itemrev_{number:032x}",
        manifest_sha256=HASH,
    )


def source(number: int = 1, *, kind: str = "REGISTRY_DIRECT") -> ChatKnowledgeSource:
    return ChatKnowledgeSource.model_validate(
        {
            "key": f"S{number}",
            "item": item(number),
            "display_name": "합성 테스트 문항",
            "kind": kind,
            "approval": "APPROVED",
            "pointer": ArtifactMemberPointer(
                artifact_id=f"artifact_{number:032x}",
                artifact_revision_id=f"rev_{number:032x}",
                schema_ref="eom://schemas/assessment-item-content/3.0",
                media_type="application/json",
                member_path="content/item.json",
                sha256=HASH,
            ),
            "location": "canonical item content",
            "text": "속도가 일정하다. 단위는 m/s이다.",
            "graph_node_ids": [],
        }
    )


def context() -> ChatKnowledgeContext:
    return chat_knowledge_context(
        selection=ChatKnowledgeSelection(references=(item(),), snapshot=None),
        sources=(source(),),
        limitations=("그림 픽셀은 이번 텍스트 경로에서 제공되지 않습니다.",),
    )


def request() -> GroundedChatTurnInput:
    messages = (ChatContextMessage(role="user", text="이 문항의 단위를 설명해 주세요."),)
    return read_grounded_chat_input(
        GroundedChatTurnInput(
            conversation_id="chat_" + "1" * 32,
            turn_id="chatturn_" + "2" * 32,
            claim_id="chatclaim_" + "3" * 32,
            messages=messages,
            context_sha256=sha256_bytes(
                canonical_json_bytes([message.model_dump() for message in messages])
            ),
            knowledge=context(),
        ).model_dump(mode="json")
    )


def result() -> GroundedChatTurnResult:
    prepared = request()
    return GroundedChatTurnResult(
        conversation_id=prepared.conversation_id,
        turn_id=prepared.turn_id,
        claim_id=prepared.claim_id,
        request_sha256=sha256_bytes(canonical_json_bytes(prepared.model_dump(mode="json"))),
        knowledge_sha256=prepared.knowledge.context_sha256,
        status="SUCCEEDED",
        answer=ChatGroundedAnswer(
            answer_sections=(
                ChatAnswerSection(
                    section_id="section_1",
                    markdown="자료에 제시된 속도의 단위는 m/s입니다.",
                    support_kind="SOURCE_SUPPORTED",
                    citation_keys=("S1",),
                ),
            ),
            limitations=(),
        ),
        failure_code=None,
    )


def test_schema_is_offline_mirrored_and_all_definitions_validate() -> None:
    leaf = "general-chat-grounding.schema.json"
    canonical = (ROOT / "schemas/general-chat" / leaf).read_bytes()
    assert canonical == (ROOT / "packages/protocol/eom_protocol/schemas" / leaf).read_bytes()
    document = json.loads(canonical)
    Draft202012Validator.check_schema(document)
    for name in document["$defs"]:
        grounding_validator(name)
    assert (
        read_grounded_chat_result(result().model_dump(mode="json"), request=request()) == result()
    )


def test_plain_v1_rejects_grounded_input_and_its_bytes_are_not_reinterpreted() -> None:
    with pytest.raises(SchemaError):
        read_chat_turn_input(request().model_dump(mode="json"))


def test_request_and_context_are_frozen_and_hashes_are_distinct() -> None:
    prepared = request()
    assert prepared.context_sha256 != prepared.knowledge.context_sha256
    assert prepared.knowledge.selection.references[0].manifest_sha256 != (
        prepared.knowledge.context_sha256
    )
    with pytest.raises(ValidationError):
        prepared.knowledge.context_sha256 = HASH
    assert read_grounded_chat_input(prepared.model_dump(mode="json")) == prepared


@pytest.mark.parametrize("field", ["credentials", "nas_path", "native_thread_id", "permissions"])
def test_boundary_rejects_private_handles_and_caller_permission_claims(field: str) -> None:
    document = request().model_dump(mode="json")
    document[field] = "untrusted"
    with pytest.raises(SchemaError):
        read_grounded_chat_input(document)


@pytest.mark.parametrize("field", ["context_sha256", "text", "location", "sha256"])
def test_context_content_and_pointer_tampering_fails(field: str) -> None:
    document = context().model_dump(mode="json")
    if field == "context_sha256":
        document[field] = HASH
    elif field == "sha256":
        document["sources"][0]["pointer"][field] = "sha256:" + "b" * 64
    else:
        document["sources"][0][field] = "changed"
    with pytest.raises(ValidationError):
        read_grounding("Context", document, ChatKnowledgeContext)


def test_duplicate_revision_with_different_hash_is_not_a_new_selection() -> None:
    with pytest.raises(ValidationError):
        ChatKnowledgeSelection(
            references=(
                item(),
                item().model_copy(update={"manifest_sha256": "sha256:" + "b" * 64}),
            ),
            snapshot=None,
        )


@pytest.mark.parametrize("count", [0, 4])
def test_selection_has_a_bounded_nonempty_identity_set(count: int) -> None:
    with pytest.raises(ValidationError):
        ChatKnowledgeSelection(references=tuple(item(i) for i in range(count)), snapshot=None)


def test_every_selected_item_requires_direct_content_and_graph_requires_snapshot() -> None:
    with pytest.raises(ValidationError):
        chat_knowledge_context(
            selection=ChatKnowledgeSelection(references=(item(), item(2)), snapshot=None),
            sources=(source(),),
            limitations=(),
        )
    graph = source(2, kind="GRAPH_ANALYSIS").model_copy(update={"item": item()})
    with pytest.raises(ValidationError):
        chat_knowledge_context(
            selection=context().selection, sources=(source(), graph), limitations=()
        )
    snapshot = ChatKnowledgeSnapshot(graph_snapshot_revision_id="graphrev_" + "4" * 32, sha256=HASH)
    accepted = chat_knowledge_context(
        selection=context().selection.model_copy(update={"snapshot": snapshot}),
        sources=(source(), graph),
        limitations=(),
    )
    assert accepted.sources[1].kind == "GRAPH_ANALYSIS"


def test_unapproved_direct_content_is_not_promoted_to_graph_evidence() -> None:
    document = source().model_dump(mode="json")
    document["approval"] = "PENDING"
    assert read_grounding("Source", document, ChatKnowledgeSource).approval == "PENDING"
    document["kind"] = "SOLUTION_REPORT"
    with pytest.raises((SchemaError, ValidationError)):
        read_grounding("Source", document, ChatKnowledgeSource)


@pytest.mark.parametrize(
    "update",
    [
        {"key": "S2"},
        {"item": item(2)},
        {"text": "\x00untrusted"},
        {"graph_node_ids": ("node_1", "node_1")},
    ],
)
def test_source_binding_keys_and_text_are_not_implicit(update: dict[str, object]) -> None:
    changed = source().model_copy(update=update)
    with pytest.raises((SchemaError, ValidationError)):
        chat_knowledge_context(selection=context().selection, sources=(changed,), limitations=())


def test_duplicate_member_and_location_fails_without_list_scan() -> None:
    duplicate = source().model_copy(update={"key": "S2"})
    with pytest.raises(ValidationError):
        chat_knowledge_context(
            selection=context().selection, sources=(source(), duplicate), limitations=()
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("conversation_id", "chat_" + "9" * 32),
        ("turn_id", "chatturn_" + "9" * 32),
        ("claim_id", "chatclaim_" + "9" * 32),
        ("request_sha256", HASH),
        ("knowledge_sha256", HASH),
    ],
)
def test_citation_receipt_is_bound_to_exact_turn_and_input(field: str, value: str) -> None:
    changed = result().model_copy(update={field: value})
    with pytest.raises(ValueError):
        validate_chat_citations(request(), changed)


def test_unknown_source_citation_does_not_pass_even_if_key_has_valid_format() -> None:
    document = result().model_dump(mode="json")
    document["answer"]["answer_sections"][0]["citation_keys"] = ["S9"]
    with pytest.raises(ValueError):
        read_grounded_chat_result(document, request=request())


@pytest.mark.parametrize(
    "kind,keys",
    [
        ("SOURCE_SUPPORTED", []),
        ("GENERAL_KNOWLEDGE", ["S1"]),
        ("INSUFFICIENT_EVIDENCE", ["S1"]),
        ("MODEL_INFERENCE", ["S1", "S1"]),
    ],
)
def test_section_separates_source_fact_inference_and_general_knowledge(
    kind: str, keys: list[str]
) -> None:
    with pytest.raises(ValidationError):
        ChatAnswerSection.model_validate(
            {
                "section_id": "section_1",
                "markdown": "내용",
                "support_kind": kind,
                "citation_keys": keys,
            }
        )


@pytest.mark.parametrize("markdown", ["내용 [S1]", "없는 출처 [S10]", "내용\x00"])
def test_free_text_cannot_forge_owner_rendered_citation_markers(markdown: str) -> None:
    with pytest.raises(ValidationError):
        ChatAnswerSection(
            section_id="section_1",
            markdown=markdown,
            support_kind="GENERAL_KNOWLEDGE",
            citation_keys=(),
        )


def test_citation_receipt_is_reproducible_not_educational_approval() -> None:
    receipt = validate_chat_citations(request(), result())
    assert receipt == validate_chat_citations(request(), result())
    assert receipt.used_source_keys == ("S1",)
    assert receipt.verified_references == (item(),)
    assert receipt.result_sha256 == sha256_bytes(
        canonical_json_bytes(result().model_dump(mode="json"))
    )
    assert receipt.meaning == "CITATION_LINK_INTEGRITY_NOT_SCIENTIFIC_APPROVAL"
    assert (
        read_grounding("Receipt", receipt.model_dump(mode="json"), ChatCitationReceipt) == receipt
    )


@pytest.mark.parametrize("model", [GroundedChatSubmission, StoredGroundedChatMessage])
def test_user_payloads_reject_nul(
    model: type[GroundedChatSubmission] | type[StoredGroundedChatMessage],
) -> None:
    value = {"text": "질문\x00", "selection": context().selection}
    if model is GroundedChatSubmission:
        value["expected_version"] = 1
    else:
        value.update(conversation_id=request().conversation_id, turn_id=request().turn_id)
    with pytest.raises(ValidationError):
        model.model_validate(value)


@pytest.mark.parametrize(
    "update",
    [
        {"status": "FAILED"},
        {"failure_code": "CODEX_TIMEOUT"},
        {"answer": None},
        {"failure_code": "UNKNOWN_ERROR"},
    ],
)
def test_result_rejects_partial_success_or_unknown_failure(update: dict[str, object]) -> None:
    document = result().model_dump(mode="json") | update
    with pytest.raises((SchemaError, ValidationError)):
        read_grounded_chat_result(document, request=request())


def test_declared_failure_preserves_identity_without_publishing_partial_answer() -> None:
    failed = result().model_copy(
        update={"status": "FAILED", "answer": None, "failure_code": "CODEX_TURN_FAILED"}
    )
    assert read_grounded_chat_result(failed.model_dump(mode="json"), request=request()).reply == ""
    assert validate_chat_citations(request(), failed).used_source_keys == ()
