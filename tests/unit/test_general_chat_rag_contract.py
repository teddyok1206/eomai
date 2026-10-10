"""CHAT-RAG-2 schema/model, exact-source and mixed-tool contracts; no model/DB/NAS."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat_grounding import (
    AgentChatTurnInput,
    ChatAnswerSection,
    ChatGroundingViews,
    ChatKnowledgeSelection,
    chat_knowledge_context,
    read_agent,
)
from eom_protocol.general_chat_rag_knowledge import (
    ChatRagArguments,
    ChatRagAuthorizeCommand,
    ChatRagCatalogReply,
    ChatRagCatalogRequest,
    ChatRagContext,
    ChatRagPrepareCommand,
    ChatRagRetrieveCommand,
    chat_rag_context,
    rag_validator,
    read_rag,
    read_rag_catalog_reply,
)
from eom_protocol.general_chat_rag_tools import (
    RAG_TOOL_RECORD_SCHEMA,
    ChatRagCommand,
    ChatRagToolTranscript,
    ChatToolOutcomeV2,
    ChatToolRecordV2,
    ChatToolReplyV2,
    ChatToolRequestV2,
    failed_rag_tool,
)
from eom_protocol.general_chat_rag_turn import (
    ChatGroundingViewsV2,
    ChatRagSourceCard,
    ChatTurnGroundingViewV2,
    RagChatAnswerSection,
    RagChatTurnInput,
    read_rag_chat_result,
    validate_rag_citations,
)
from eom_protocol.general_chat_tools import ChatDiscoveryCard, ChatReadCommand, ChatSearchCommand
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.general_chat_rag_fixtures import (
    HASH,
    context,
    request,
    result,
    scope,
    source,
    ticket,
)
from tests.unit.test_general_chat_agent_search import arguments as item_arguments
from tests.unit.test_general_chat_grounding_contract import item
from tests.unit.test_general_chat_grounding_contract import source as item_source

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "schemas/general-chat"


def arguments() -> ChatRagArguments:
    return ChatRagArguments(terms=("전자기",), source_classes=("TEXTBOOK",))


def record(sequence: int, command: object, outcome: ChatToolOutcomeV2) -> ChatToolRecordV2:
    return ChatToolRecordV2(
        request=ChatToolRequestV2.model_validate(
            {
                "rpc_request_id": "chatwrpc_" + "a" * 32,
                "ticket": ticket(),
                "sequence": sequence,
                "command": command,
            }
        ),
        outcome=outcome,
    )


def rag_outcome(knowledge: ChatRagContext) -> ChatToolOutcomeV2:
    return ChatToolOutcomeV2(
        status="SUCCEEDED",
        cards=(),
        context=None,
        rag_context=knowledge,
        snapshot=knowledge.scope.snapshot,
        truncated=False,
        error_code=None,
    )


def test_schema_first_mirrors_and_predecessor_bytes_are_preserved() -> None:
    paths = sorted(
        p
        for p in BASE.glob("*.json")
        if "-v4." not in p.name
        and "-v5." not in p.name
        and p.name != "general-chat-rag.schema.json"
    )
    assert len(paths) == 28
    assert hashlib.sha256(
        b"".join(p.name.encode() + b"\0" + p.read_bytes() for p in paths)
    ).hexdigest() == ("cadfcf5b94725568a201b1f1627f0d0ee8c3abb519d00b4e1232f27398a3cb6e")
    for path in [BASE / "general-chat-rag.schema.json", *BASE.glob("*-v4.schema.json")]:
        assert (
            path.read_bytes()
            == (ROOT / "packages/protocol/eom_protocol/schemas" / path.name).read_bytes()
        )
        Draft202012Validator.check_schema(json.loads(path.read_bytes()))
    for name in json.loads((BASE / "general-chat-rag.schema.json").read_bytes())["$defs"]:
        rag_validator(name)
    completed = subprocess.run(
        [
            "/srv/eom/conda/envs/eom-api/bin/python",
            str(ROOT / "scripts/contracts/generate_general_chat_rag_schemas.py"),
            "--check",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_textbook_reference_is_not_an_item_or_verbatim_pdf_quote() -> None:
    knowledge = context()
    assert read_rag("Context", knowledge.model_dump(mode="json"), ChatRagContext) == knowledge
    assert knowledge.sources[0].reference.source.source_kind == "DOCUMENT_REVISION"
    assert knowledge.sources[0].text_kind == "APPROVED_ANALYSIS_NOT_VERBATIM_SOURCE"
    assert "item_id" not in knowledge.sources[0].reference.source.model_dump()
    assert "intake_batch_id" not in knowledge.sources[0].reference.source.model_dump()
    assert (
        knowledge.sources[0].reference.accepted_result
        != knowledge.sources[0].reference.analysis_member
    )
    with pytest.raises(ValidationError):
        knowledge.context_sha256 = HASH


@pytest.mark.parametrize(
    "field", ["permissions", "requester_role", "actor_id", "nas_path", "policy"]
)
def test_model_arguments_cannot_choose_authority_or_files(field: str) -> None:
    value = arguments().model_dump(mode="json")
    value[field] = "privileged"
    with pytest.raises(SchemaError):
        read_rag("Arguments", value, ChatRagArguments)


@pytest.mark.parametrize(
    "path", ["/source.pdf", "../source.pdf", "source//a.pdf", "a\\b.pdf", "a/./b.pdf"]
)
def test_original_member_paths_are_storage_neutral_and_safe(path: str) -> None:
    value = source().reference.model_dump(mode="json")
    value["source"]["artifact_member"]["member_path"] = path
    with pytest.raises(SchemaError):
        rag_validator("Reference").validate(value)


@pytest.mark.parametrize("terms", [[], ["x"], ["전자기", "전자기"], ["A B"], ["전기"] * 9])
def test_retrieval_terms_are_bounded_and_distinct(terms: list[str]) -> None:
    value = arguments().model_dump(mode="json")
    value["terms"] = terms
    with pytest.raises((SchemaError, ValidationError)):
        read_rag("Arguments", value, ChatRagArguments)


def test_exact_scope_hash_and_source_content_hash_are_separate() -> None:
    knowledge = context()
    value = knowledge.model_dump(mode="json")
    value["sources"][0]["text"] = "changed"
    with pytest.raises(ValidationError, match="hash"):
        read_rag("Context", value, ChatRagContext)
    different = scope().model_copy(
        update={"policy": scope().policy.model_copy(update={"sha256": "sha256:" + "b" * 64})}
    )
    with pytest.raises(ValidationError, match="prior"):
        ChatRagRetrieveCommand(scope=different, arguments=arguments(), prior_context=knowledge)


@pytest.mark.parametrize(
    "sources",
    [
        (source(key="R2"),),
        (source(), source(key="R2")),
        (source(text="x" * 4500), source(2, text="y" * 4500)),
    ],
)
def test_context_rejects_retargeted_duplicate_or_oversized_sources(sources) -> None:
    with pytest.raises((SchemaError, ValidationError)):
        chat_rag_context(scope=scope(), sources=sources, limitations=())


@pytest.mark.parametrize(
    "changed",
    [
        {"schema_ref": "eom://schemas/knowledge/unapproved/1.0"},
        {"media_type": "image/png"},
        {"member_path": "evidence/other.json"},
    ],
)
def test_accepted_result_cannot_be_an_unrelated_artifact_member(changed: dict[str, str]) -> None:
    value = source().reference.model_dump(mode="json")
    value["accepted_result"].update(changed)
    with pytest.raises(SchemaError):
        rag_validator("Reference").validate(value)


@pytest.mark.parametrize("field", ["scope", "context"])
def test_failed_catalog_reply_cannot_leak_partial_evidence(field: str) -> None:
    value = {
        "schema_version": "chat-rag-catalog-reply/1.0",
        "operation": "CHAT_RAG",
        "status": "FAILED",
        "scope": None,
        "context": None,
        "error_code": "CHAT_KNOWLEDGE_FORBIDDEN",
    }
    value[field] = (
        scope().model_dump(mode="json") if field == "scope" else context().model_dump(mode="json")
    )
    with pytest.raises(SchemaError):
        read_rag("CatalogReply", value, ChatRagCatalogReply)


def test_catalog_request_contains_actual_actor_but_model_arguments_do_not() -> None:
    query = ChatRagCatalogRequest(
        actor_id="operator_" + "c" * 32,
        command=ChatRagRetrieveCommand(scope=scope(), arguments=arguments(), prior_context=None),
    )
    assert read_rag("CatalogRequest", query.model_dump(mode="json"), ChatRagCatalogRequest) == query


def test_catalog_retrieve_success_requires_materialized_context() -> None:
    query = ChatRagCatalogRequest(
        actor_id="operator_" + "c" * 32,
        command=ChatRagRetrieveCommand(scope=scope(), arguments=arguments(), prior_context=None),
    )
    reply = ChatRagCatalogReply(status="SUCCEEDED", scope=scope(), context=None, error_code=None)
    with pytest.raises(ValueError, match="materialize"):
        read_rag_catalog_reply(reply.model_dump(mode="json"), request=query)
    complete = reply.model_copy(update={"context": context()})
    assert read_rag_catalog_reply(complete.model_dump(mode="json"), request=query) == complete
    empty = reply.model_copy(update={"status": "EMPTY"})
    assert read_rag_catalog_reply(empty.model_dump(mode="json"), request=query) == empty


def test_prepare_and_reauthorize_replies_cannot_switch_pins() -> None:
    actor = "operator_" + "c" * 32
    prepare = ChatRagCatalogRequest(
        actor_id=actor,
        command=ChatRagPrepareCommand(snapshot=scope().snapshot, policy=scope().policy),
    )
    reply = ChatRagCatalogReply(status="SUCCEEDED", scope=scope(), context=None, error_code=None)
    assert read_rag_catalog_reply(reply.model_dump(mode="json"), request=prepare) == reply
    changed = reply.model_dump(mode="json")
    changed["scope"]["policy"]["sha256"] = "sha256:" + "b" * 64
    with pytest.raises(ValueError, match="pins"):
        read_rag_catalog_reply(changed, request=prepare)
    query = ChatRagCatalogRequest(
        actor_id=actor, command=ChatRagAuthorizeCommand(context=context())
    )
    authorized = reply.model_copy(update={"context": context()})
    assert read_rag_catalog_reply(authorized.model_dump(mode="json"), request=query) == authorized
    changed = authorized.model_copy(update={"context": context(source(2, key="R1"))})
    with pytest.raises(ValueError, match="replace"):
        read_rag_catalog_reply(changed.model_dump(mode="json"), request=query)


def test_offline_schema_definitions_share_one_immutable_parsed_registry(monkeypatch) -> None:
    from eom_protocol import general_chat_rag_knowledge as contracts

    names = tuple(json.loads((BASE / "general-chat-rag.schema.json").read_bytes())["$defs"])
    original = Path.read_bytes
    counts: dict[str, int] = {}

    def observed(path: Path) -> bytes:
        counts[path.name] = counts.get(path.name, 0) + 1
        return original(path)

    contracts._rag_resources.cache_clear()
    contracts.rag_validator.cache_clear()
    monkeypatch.setattr(Path, "read_bytes", observed)
    for name in names:
        contracts.rag_validator(name)
    assert len(counts) == 5
    assert set(counts.values()) == {1}


def test_mixed_item_and_textbook_citations_have_distinct_exact_references() -> None:
    selected = chat_knowledge_context(
        selection=ChatKnowledgeSelection(references=(item(),), snapshot=scope().snapshot),
        sources=(item_source(),),
        limitations=(),
    )
    value = request(knowledge=context()).model_dump(mode="json")
    value["knowledge"] = selected.model_dump(mode="json")
    prepared = read_rag("Input", value, RagChatTurnInput)
    answer = result(prepared).model_dump(mode="json")
    answer["answer"]["answer_sections"][0]["citation_keys"] = ["S1", "R1"]
    verified = read_rag_chat_result(answer, request=prepared)
    receipt = validate_rag_citations(prepared, verified, item=selected, rag=prepared.rag_knowledge)
    assert receipt.used_source_keys == ("S1", "R1")
    assert receipt.verified_references == (item(),)
    assert receipt.verified_rag_references[0].source.source_kind == "DOCUMENT_REVISION"


def test_v4_result_requires_exact_context_and_structured_r_citations() -> None:
    prepared = request(knowledge=context())
    assert read_rag("Input", prepared.model_dump(mode="json"), RagChatTurnInput) == prepared
    answer = result(prepared)
    assert read_rag_chat_result(answer.model_dump(mode="json"), request=prepared) == answer
    receipt = validate_rag_citations(prepared, answer, item=None, rag=prepared.rag_knowledge)
    assert receipt.used_source_keys == ("R1",)
    assert receipt.verified_references == ()
    assert len(receipt.verified_rag_references) == 1
    assert "[R1]" in answer.reply
    assert receipt.meaning == "CITATION_LINK_INTEGRITY_NOT_SCIENTIFIC_APPROVAL"
    for key, changed in [
        ("claim_id", "chatclaim_" + "f" * 32),
        ("request_sha256", HASH),
        ("knowledge_sha256", HASH),
        ("agent_state_sha256", HASH),
    ]:
        value = answer.model_dump(mode="json")
        value[key] = changed
        with pytest.raises(ValueError):
            read_rag_chat_result(value, request=prepared)
    with pytest.raises(ValueError):
        validate_rag_citations(prepared, answer, item=None, rag=context(source(2, key="R1")))


def test_legacy_reader_rejects_v4_instead_of_reinterpreting_it() -> None:
    with pytest.raises(SchemaError):
        read_agent("Input", request().model_dump(mode="json"), AgentChatTurnInput)
    with pytest.raises(ValidationError):
        ChatAnswerSection(
            section_id="section_1",
            markdown="old answer",
            support_kind="SOURCE_SUPPORTED",
            citation_keys=("R1",),
        )
    # Preserve released V2's literal text meaning; R markers were not citations in V2.
    ChatAnswerSection(
        section_id="section_1",
        markdown="literal [R1]",
        support_kind="GENERAL_KNOWLEDGE",
        citation_keys=(),
    )


@pytest.mark.parametrize(
    "changed",
    [
        {"markdown": "invented [R1]"},
        {"markdown": "invented [S1]"},
        {"citation_keys": ["R4"]},
        {"citation_keys": []},
        {"citation_keys": ["R1", "R1"]},
        {"support_kind": "GENERAL_KNOWLEDGE"},
    ],
)
def test_r_citation_markers_and_support_cannot_be_forged(changed) -> None:
    value = result(request(knowledge=context())).answer.answer_sections[0].model_dump()
    value.update(changed)
    with pytest.raises(ValidationError):
        RagChatAnswerSection.model_validate(value)


def test_missing_context_cannot_substantiate_r_claims_or_system_observation() -> None:
    prepared = request()
    answer = result(prepared)
    with pytest.raises(ValueError, match="outside"):
        validate_rag_citations(prepared, answer, item=None, rag=None)
    value = answer.model_dump(mode="json")
    value["answer"]["answer_sections"][0].update(
        support_kind="SYSTEM_OBSERVATION", citation_keys=[]
    )
    from eom_protocol.general_chat_rag_turn import RagChatTurnResult

    with pytest.raises(ValueError, match="observation"):
        validate_rag_citations(
            prepared, RagChatTurnResult.model_validate(value), item=None, rag=None
        )


def test_interleaved_tools_reuse_offered_item_rule_and_append_r_keys() -> None:
    transcript = ChatRagToolTranscript(scope=scope())
    search = ChatSearchCommand(arguments=item_arguments())
    discovered = ChatToolOutcomeV2(
        status="SUCCEEDED",
        cards=(
            ChatDiscoveryCard(
                item=item(),
                display_name="합성 문항",
                approval="APPROVED",
                source_kind="PAST_EXAM",
                graph_membership="INDEXED",
            ),
        ),
        snapshot=scope().snapshot,
        truncated=False,
        context=None,
        rag_context=None,
        error_code=None,
    )
    transcript.observe(record(1, search, discovered))
    rag_command = ChatRagCommand(arguments=arguments())
    transcript.observe(record(2, rag_command, rag_outcome(context())))
    selected = chat_knowledge_context(
        selection=ChatKnowledgeSelection(references=(item(),), snapshot=scope().snapshot),
        sources=(item_source(),),
        limitations=(),
    )
    read = ChatReadCommand.model_validate({"arguments": {"references": [item()]}})
    transcript.observe(
        record(
            3,
            read,
            ChatToolOutcomeV2(
                status="SUCCEEDED",
                cards=(),
                snapshot=scope().snapshot,
                context=selected,
                rag_context=None,
                truncated=False,
                error_code=None,
            ),
        )
    )
    transcript.observe(record(4, rag_command, rag_outcome(context(source(), source(2)))))
    assert transcript.items.reads == 1 and transcript.items.searches == 1
    assert transcript.items.context == selected and transcript.rag_reads == 2
    assert [s.key for s in transcript.rag_context.sources] == ["R1", "R2"]
    assert transcript.command_error(rag_command) == "CHAT_KNOWLEDGE_READ_LIMIT"
    assert transcript.command_error(read) == "CHAT_KNOWLEDGE_READ_LIMIT"
    transcript.observe(record(5, rag_command, failed_rag_tool("CHAT_KNOWLEDGE_READ_LIMIT")))
    assert transcript.rag_context.sources[0] == source()


@pytest.mark.parametrize(
    "change", ["retarget", "policy", "snapshot", "class", "identity", "sequence"]
)
def test_tool_transcript_rejects_silent_evidence_or_claim_changes(change: str) -> None:
    transcript = ChatRagToolTranscript(scope=scope())
    command = ChatRagCommand(arguments=arguments())
    transcript.observe(record(1, command, rag_outcome(context())))
    knowledge = context(source(), source(2))
    if change == "retarget":
        knowledge = context(source(2, key="R1"))
    elif change in {"policy", "snapshot"}:
        value = knowledge.model_dump(mode="json")
        value["scope"][change]["sha256"] = "sha256:" + "b" * 64
        value["context_sha256"] = sha256_bytes(
            canonical_json_bytes({k: v for k, v in value.items() if k != "context_sha256"})
        )
        knowledge = ChatRagContext.model_validate(value)
    elif change == "class":
        command = ChatRagCommand(
            arguments=ChatRagArguments(terms=("전자기",), source_classes=("PAST_EXAM",))
        )
    second = record(3 if change == "sequence" else 2, command, rag_outcome(knowledge))
    if change == "identity":
        value = second.model_dump(mode="json")
        value["request"]["ticket"]["claim_id"] = "chatclaim_" + "e" * 32
        second = ChatToolRecordV2.model_validate(value)
    with pytest.raises(ValueError):
        transcript.observe(second)


def test_tools_without_scope_and_reads_without_offer_fail_explicitly() -> None:
    transcript = ChatRagToolTranscript(scope=None)
    command = ChatRagCommand(arguments=arguments())
    assert transcript.command_error(command) == "CHAT_KNOWLEDGE_UNAVAILABLE"
    transcript.observe(record(1, command, failed_rag_tool("CHAT_KNOWLEDGE_UNAVAILABLE")))
    read = ChatReadCommand.model_validate({"arguments": {"references": [item()]}})
    assert transcript.command_error(read) == "CHAT_KNOWLEDGE_NOT_OFFERED"
    with pytest.raises(ValueError):
        transcript.observe(record(2, read, failed_rag_tool("CHAT_KNOWLEDGE_UNAVAILABLE")))


def test_tool_reply_hash_binds_the_canonical_v2_record() -> None:
    evidence = record(1, ChatRagCommand(arguments=arguments()), rag_outcome(context()))
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + "d" * 32,
        artifact_revision_id="rev_" + "e" * 32,
        member_path="chat/evidence.json",
        schema_ref=RAG_TOOL_RECORD_SCHEMA,
        media_type="application/json",
        sha256=sha256_bytes(canonical_json_bytes(evidence.model_dump(mode="json"))),
    )
    reply = ChatToolReplyV2(record=evidence, pointer=pointer)
    assert read_rag("Reply", reply.model_dump(mode="json"), ChatToolReplyV2) == reply
    with pytest.raises(ValidationError):
        ChatToolReplyV2(record=evidence, pointer=pointer.model_copy(update={"sha256": HASH}))


def test_rag_source_card_is_not_an_item_navigation_target() -> None:
    prepared = request(knowledge=context())
    evidence = prepared.rag_knowledge.sources[0]
    receipt = validate_rag_citations(
        prepared, result(prepared), item=None, rag=prepared.rag_knowledge
    )
    view = ChatGroundingViewsV2(
        conversation_id=prepared.conversation_id,
        values=(
            ChatTurnGroundingViewV2(
                turn_id=prepared.turn_id,
                sources=(
                    ChatRagSourceCard(
                        key=evidence.key,
                        reference=evidence.reference,
                        display_name=evidence.display_name,
                        location=evidence.location,
                    ),
                ),
                receipt=receipt,
                observed_at=None,
            ),
        ),
    )
    assert read_rag("Views", view.model_dump(mode="json"), ChatGroundingViewsV2) == view
    assert "item" not in view.values[0].sources[0].model_dump()
    with pytest.raises(ValidationError):
        ChatGroundingViews.model_validate(view.model_dump(mode="json"))
