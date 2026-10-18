"""Real temporary publication/bytes; synthetic native/IAM and PostgreSQL read snapshot."""

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.chat_similarity_provenance import (
    CHAT_SIMILARITY_PROVENANCE_MEMBER,
    CHAT_SIMILARITY_PROVENANCE_REF,
    MAX_CHAT_SIMILARITY_PROVENANCE_BYTES,
    ChatSimilarityProvenanceError,
    build_chat_similarity_provenance,
    validate_chat_similarity_provenance,
)
from eom_catalog_contracts.private_chat_query_prepare import (
    parse_private_chat_query_prepare_request,
    private_chat_query_context_request_id,
    validate_private_chat_query_prepare_reply,
)
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_catalog_contracts.private_chat_similarity import PrivateChatSimilarityContext
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator import general_chat_artifacts as store_module
from eom_orchestrator.control_artifact_resolution import (
    ControlArtifactResolutionError,
    resolve_control_artifact_members,
)
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.general_chat_artifacts import GeneralChatArtifactStore
from eom_orchestrator.general_chat_rag_broker import rag_tool_knowledge
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_protocol.general_chat_grounding import ChatKnowledgeItem, ChatKnowledgeSnapshot
from eom_protocol.general_chat_rag_knowledge import ChatRagPolicy, ChatRagScope
from eom_protocol.general_chat_rag_tools import (
    ChatRagToolTranscript,
    ChatToolOutcomeV2,
    ChatToolRecordV2,
    ChatToolRequestV2,
)
from eom_protocol.general_chat_rag_turn import (
    RagChatAnswer,
    RagChatAnswerSection,
    RagChatTurnInput,
)
from eom_protocol.general_chat_tools import ChatDiscoveryCard, ChatSearchCommand
from jsonschema import Draft202012Validator
from sqlalchemy import create_engine, func, select, tuple_

from tests.unit.general_chat_rag_fixtures import result as turn_result
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_control_artifact_batch_resolution import _Engine as SnapshotRows
from tests.unit.test_control_file_set_publication import _contains_bytes, _publisher
from tests.unit.test_general_chat_agent_search import arguments
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_prepare_exchange import case as case
from tests.unit.test_private_chat_query_source import source_case
from tests.unit.test_private_chat_similarity_service import case as context_case
from tests.unit.test_private_chat_similarity_service import compose


@pytest.fixture
def prepared(case):
    prepare_case = case
    origin = prepare_case.request.origin
    request, owner = context_case()
    context = compose(request, owner).model_dump(mode="json")
    assert context["candidates"]
    scope = ChatRagScope(
        snapshot=ChatKnowledgeSnapshot(
            graph_snapshot_revision_id=context["request"]["graph_snapshot"][
                "graph_snapshot_revision_id"
            ],
            sha256="sha256:" + "0" * 64,
        ),
        policy=ChatRagPolicy(
            access_policy_revision_id=context["request"]["policy_revision_id"],
            sha256=context["request"]["policy_sha256"],
        ),
    )
    turn = RagChatTurnInput.model_validate(
        source_case(question=TEXT).prepared.model_dump(mode="json")
        | {"rag_scope": scope.model_dump(mode="json")}
    )
    origin_document = origin.model_dump(mode="json")
    origin_document["ticket"]["request_sha256"] = sha256_bytes(canonical_json_bytes(turn))
    origin_document["request_member"]["sha256"] = origin_document["ticket"]["request_sha256"]
    origin = ChatPrivateQueryOrigin.model_validate(seal(origin_document, "origin_sha256"))
    context["request"] = seal(
        context["request"]
        | {
            "query_basis": origin.basis.model_dump(mode="json"),
            "request_id": private_chat_query_context_request_id(origin),
            "top_k": 64,
        },
        "request_sha256",
    )
    context["query_execution"]["basis_sha256"] = origin.basis.basis_sha256
    context = PrivateChatSimilarityContext.model_validate(seal(context, "context_sha256"))
    native = parse_private_chat_query_prepare_request(
        seal(
            prepare_case.request.model_dump(mode="json")
            | {
                "origin": origin.model_dump(mode="json"),
                "graph_snapshot": context.request.graph_snapshot.model_dump(mode="json"),
                "policy_revision_id": context.request.policy_revision_id,
                "policy_sha256": context.request.policy_sha256,
            },
            "request_sha256",
        )
    )
    reply = validate_private_chat_query_prepare_reply(
        native,
        {
            "schema_version": "system-rag-private-chat-query-prepare-reply/1.0",
            "action": native.action,
            "request_id": native.request_id,
            "request_sha256": native.request_sha256,
            "status": "READY",
            "workflow_id": "workflow_" + "1" * 32,
            "context": context.model_dump(mode="json"),
            "error_code": None,
        },
    )
    refs = tuple(
        ChatKnowledgeItem(
            item_id=c.source.item_id,
            item_revision_id=c.source.item_revision_id,
            manifest_sha256="sha256:" + "f" * 64,
        )
        for c in context.candidates[:6]
    )
    record = ChatToolRecordV2(
        request=ChatToolRequestV2(
            rpc_request_id="chatwrpc_" + "2" * 32,
            ticket=origin.ticket,
            sequence=1,
            command=ChatSearchCommand(arguments=arguments("TOPIC", terms=["전자기"])),
        ),
        outcome=ChatToolOutcomeV2(
            status="SUCCEEDED",
            cards=tuple(
                ChatDiscoveryCard(
                    item=ref,
                    display_name="합성 문항",
                    approval="APPROVED",
                    source_kind="PAST_EXAM"
                    if c.source.source_class == "PAST_EXAM"
                    else "GENERATED",
                    graph_membership="INDEXED",
                )
                for ref, c in zip(refs, context.candidates, strict=False)
            ),
            snapshot=scope.snapshot,
            truncated=False,
            context=None,
            rag_context=None,
            error_code=None,
        ),
    )
    provenance = build_chat_similarity_provenance(
        record=record,
        scope=scope,
        native_request=native,
        native_reply=reply,
        delivered_native_items=refs,
    )
    return SimpleNamespace(
        record=record,
        provenance=provenance,
        native=native,
        reply=reply,
        scope=scope,
        refs=refs,
        turn=turn,
    )


def test_schema_mirror_and_all_external_references_resolve(prepared):
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES["general-chat-similarity-provenance"]
    raw = (root / entry.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == entry.sha256
    Draft202012Validator.check_schema(load_schema("general-chat-similarity-provenance"))
    assert (
        validate_chat_similarity_provenance(prepared.record, prepared.provenance)
        == prepared.provenance
    )
    assert prepared.scope.snapshot.sha256 != prepared.native.graph_snapshot.manifest_sha256
    assert all(
        ref.manifest_sha256 != c.source.artifact_member.sha256
        for ref, c in zip(prepared.refs, prepared.reply.context.candidates, strict=False)
    )
    encoded = canonical_json_bytes(prepared.provenance)
    assert b'"text"' not in encoded and b'"vectors"' not in encoded


def test_frozen_v4_transcript_accepts_record_without_treating_the_companion_as_evidence(prepared):
    transcript = ChatRagToolTranscript(scope=prepared.turn.rag_scope)
    transcript.observe(prepared.record)
    assert transcript.sequence == 1
    assert tuple(transcript.items.offered.values()) == prepared.refs
    assert transcript.items.context is None and transcript.rag_context is None
    assert prepared.record.request.ticket.request_sha256 == sha256_bytes(
        canonical_json_bytes(prepared.turn)
    )


@pytest.mark.parametrize(
    "field", ["actor_role", "text", "password", "path", "vectors", "permission", "latest"]
)
def test_closed_companion_rejects_extra_fields_before_publication(prepared, field):
    value = prepared.provenance.model_dump(mode="json") | {field: "PRIVATE_DETAIL"}
    with pytest.raises(ChatSimilarityProvenanceError, match="CHAT_SIMILARITY_PROVENANCE_INVALID"):
        validate_chat_similarity_provenance(prepared.record, value)


def test_oversized_companion_is_rejected_with_a_content_free_error(prepared):
    value = prepared.provenance.model_dump(mode="json")
    value["untrusted_padding"] = "x" * MAX_CHAT_SIMILARITY_PROVENANCE_BYTES
    with pytest.raises(ChatSimilarityProvenanceError) as caught:
        validate_chat_similarity_provenance(prepared.record, value)
    assert str(caught.value) == "CHAT_SIMILARITY_PROVENANCE_INVALID"


@pytest.mark.parametrize(
    "change",
    [
        "hash",
        "sibling",
        "revision",
        "policy",
        "reply",
        "origin",
        "delivered",
        "reversed",
        "member",
        "top_k",
    ],
)
def test_exact_native_sibling_scope_and_delivery_are_bound(prepared, change):
    value = deepcopy(prepared.provenance.model_dump(mode="json"))
    if change == "hash":
        value["provenance_sha256"] = "sha256:" + "a" * 64
    elif change == "sibling":
        value["tool_record_member"]["sha256"] = "sha256:" + "a" * 64
    elif change == "revision":
        value["scope"]["snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "a" * 32
    elif change == "policy":
        value["scope"]["policy"]["sha256"] = "sha256:" + "a" * 64
    elif change == "reply":
        value["native_reply"]["request_sha256"] = "sha256:" + "a" * 64
    elif change == "origin":
        value["native_request"]["origin"]["actor_id"] = "operator_" + "a" * 32
    elif change == "delivered":
        value["delivered_native_items"][0]["manifest_sha256"] = "sha256:" + "a" * 64
    elif change == "reversed":
        assert len(value["delivered_native_items"]) > 1
        value["delivered_native_items"].reverse()
    elif change == "member":
        value["tool_record_member"]["member_path"] = "other/evidence.json"
    else:
        context = value["native_reply"]["context"]
        context["request"] = seal(context["request"] | {"top_k": 8}, "request_sha256")
        value["native_reply"]["context"] = seal(context, "context_sha256")
    if change != "hash":
        value = seal(value, "provenance_sha256")
    with pytest.raises(ChatSimilarityProvenanceError):
        validate_chat_similarity_provenance(prepared.record, value)


@pytest.mark.parametrize("kind", ["RECENT", "EXAM"])
def test_non_topic_command_cannot_claim_similarity_selection(prepared, kind):
    args = (
        arguments()
        if kind == "RECENT"
        else arguments(
            "EXAM",
            administration_year=2025,
            administration_month=6,
            target_school_level="HIGH_SCHOOL",
            target_grade=1,
            subject_key="science",
        )
    )
    record = prepared.record.model_copy(
        update={
            "request": prepared.record.request.model_copy(
                update={"command": ChatSearchCommand(arguments=args)}
            )
        }
    )
    with pytest.raises(ChatSimilarityProvenanceError):
        build_chat_similarity_provenance(
            record=record,
            scope=prepared.scope,
            native_request=prepared.native,
            native_reply=prepared.reply,
            delivered_native_items=prepared.refs,
        )


def test_other_original_claim_is_rejected_even_with_coherently_recomputed_hashes(prepared):
    value = prepared.provenance.model_dump(mode="json")
    origin = value["native_request"]["origin"]
    origin["ticket"]["claim_id"] = "chatclaim_" + "d" * 32
    value["native_request"]["origin"] = seal(origin, "origin_sha256")
    value["native_request"] = seal(value["native_request"], "request_sha256")
    value["native_reply"]["request_sha256"] = value["native_request"]["request_sha256"]
    with pytest.raises(ChatSimilarityProvenanceError):
        validate_chat_similarity_provenance(prepared.record, seal(value, "provenance_sha256"))


def test_pending_is_not_empty_or_ready_provenance(prepared):
    value = prepared.provenance.model_dump(mode="json")
    value["native_reply"].update(status="PENDING", context=None)
    with pytest.raises(ChatSimilarityProvenanceError):
        validate_chat_similarity_provenance(prepared.record, seal(value, "provenance_sha256"))


def test_claimed_native_first_policy_requires_the_actual_record_order(prepared):
    assert len(prepared.record.outcome.cards) > 1
    outcome = prepared.record.outcome.model_copy(
        update={"cards": tuple(reversed(prepared.record.outcome.cards))}
    )
    record = prepared.record.model_copy(update={"outcome": outcome})
    with pytest.raises(ChatSimilarityProvenanceError):
        build_chat_similarity_provenance(
            record=record,
            scope=prepared.scope,
            native_request=prepared.native,
            native_reply=prepared.reply,
            delivered_native_items=prepared.refs,
        )


@pytest.mark.parametrize("fault", ["PENDING", "NOT_INDEXED", "PAST_EXAM_FILTER"])
def test_native_delivery_does_not_claim_unapproved_unindexed_or_wrong_source(prepared, fault):
    document = prepared.record.model_dump(mode="json")
    if fault == "PENDING":
        document["outcome"]["cards"][0]["approval"] = "PENDING"
    elif fault == "NOT_INDEXED":
        document["outcome"]["cards"][0]["graph_membership"] = "NOT_INDEXED"
    else:
        document["request"]["command"]["arguments"]["source"] = "PAST_EXAM"
        document["outcome"]["cards"][0]["source_kind"] = "GENERATED"
    record = ChatToolRecordV2.model_validate(document)
    with pytest.raises(ChatSimilarityProvenanceError):
        build_chat_similarity_provenance(
            record=record,
            scope=prepared.scope,
            native_request=prepared.native,
            native_reply=prepared.reply,
            delivered_native_items=prepared.refs,
        )


@pytest.fixture
def store(tmp_path, monkeypatch):
    files, engine = _publisher(tmp_path)
    metadata = create_engine(str(engine.url))
    evidence = GeneralChatArtifactStore(
        metadata, ControlArtifactPublisher(engine, files.settings), source_commit="a" * 40
    )

    def sqlite_read_snapshot(engine, reads):
        # Publication is real SQLite, while PostgreSQL's typed JSON/read-only
        # transaction is a declared metadata fixture. Production SQL is unchanged.
        ids = {(read.pointer.artifact_id, read.pointer.artifact_revision_id) for read in reads}
        with engine.connect() as connection:
            rows = (
                connection.execute(
                    select(
                        ArtifactRevisionRecord.logical_artifact_id.label("artifact_id"),
                        ArtifactRevisionRecord.revision_id,
                        ArtifactRevisionRecord.nas_path,
                        ArtifactRevisionRecord.manifest,
                        ArtifactRevisionRecord.approved.label("revision_approved"),
                        ArtifactRecord.approved.label("artifact_approved"),
                    )
                    .join(
                        ArtifactRecord,
                        ArtifactRecord.logical_artifact_id
                        == ArtifactRevisionRecord.logical_artifact_id,
                    )
                    .where(
                        tuple_(
                            ArtifactRevisionRecord.logical_artifact_id,
                            ArtifactRevisionRecord.revision_id,
                        ).in_(ids)
                    )
                )
                .mappings()
                .all()
            )
        return resolve_control_artifact_members(SnapshotRows(rows), reads)

    monkeypatch.setattr(store_module, "resolve_control_artifact_members", sqlite_read_snapshot)
    yield evidence
    metadata.dispose()
    engine.dispose()


def test_real_file_set_commit_exact_replay_and_frozen_record_read(store, prepared):
    pointer = store.publish_similarity_record(prepared.record, prepared.provenance)
    assert store.publish_similarity_record(prepared.record, prepared.provenance) == pointer
    assert store.read((pointer,)) == (canonical_json_bytes(prepared.record),)
    assert store.read_similarity_provenance(pointer) == prepared.provenance
    result = turn_result(prepared.turn).model_copy(
        update={
            "tool_records": (pointer,),
            "answer": RagChatAnswer(
                answer_sections=(
                    RagChatAnswerSection(
                        section_id="section_1",
                        markdown="찾은 후보의 본문 확인이 필요합니다.",
                        support_kind="INSUFFICIENT_EVIDENCE",
                        citation_keys=(),
                    ),
                ),
                limitations=(),
            ),
        }
    )
    resolved = rag_tool_knowledge(prepared.turn, result, store)
    assert resolved.item is None and resolved.rag is None
    assert (
        tuple(ref for selection in resolved.selections for ref in selection.references)
        == prepared.refs
    )
    with store.file_sets.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
        assert len(revision.manifest["files"]) == 2
        assert revision.approved
        assert not _contains_bytes(revision.manifest) and not _contains_bytes(revision.result)
        assert "text" not in session.get(JobRecord, revision.job_id).request
    assert not tuple(store.publisher.settings.staging_root.glob("chat-similarity-*"))


def test_real_legacy_single_member_record_stays_readable_without_a_companion(store, prepared):
    pointer = store.publish(
        payload=canonical_json_bytes(prepared.record),
        schema_ref="eom://schemas/general-chat/tool-record/2.0",
        intent="synthetic-legacy-tool",
        created_at=datetime(2026, 10, 18, tzinfo=UTC),
    )
    assert store.read_similarity_provenance(pointer) is None
    assert store.read((pointer,)) == (canonical_json_bytes(prepared.record),)


@pytest.mark.parametrize(
    "fault", ["corrupt_companion", "missing_companion", "unapproved", "wrong_carrier"]
)
def test_read_rejects_corrupt_or_unapproved_companion(store, prepared, fault):
    pointer = store.publish_similarity_record(prepared.record, prepared.provenance)
    with store.file_sets.sessions.begin() as session:
        revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
        member = Path(revision.nas_path) / CHAT_SIMILARITY_PROVENANCE_MEMBER
        if fault == "corrupt_companion":
            member.write_bytes(b"corrupt")
        elif fault == "missing_companion":
            member.unlink()
        elif fault == "unapproved":
            revision.approved = False
        else:
            pointer = pointer.model_copy(update={"schema_ref": CHAT_SIMILARITY_PROVENANCE_REF})
    with pytest.raises((ChatSimilarityProvenanceError, ControlArtifactResolutionError)):
        store.read_similarity_provenance(pointer)


@pytest.mark.parametrize("fault", ["removed", "duplicate", "wrong_schema", "wrong_version"])
def test_new_file_set_cannot_masquerade_as_legacy_or_resolve_another_companion(
    store, prepared, fault
):
    pointer = store.publish_similarity_record(prepared.record, prepared.provenance)
    with store.file_sets.sessions.begin() as session:
        revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
        manifest = deepcopy(revision.manifest)
        companion = next(
            m for m in manifest["files"] if m["file_name"] == CHAT_SIMILARITY_PROVENANCE_MEMBER
        )
        if fault == "removed":
            manifest["files"].remove(companion)
        elif fault == "duplicate":
            manifest["files"].append(deepcopy(companion))
        elif fault == "wrong_schema":
            companion["schema_ref"] = "eom://schemas/knowledge/other/1.0"
        else:
            manifest["manifest_version"] = "other-tool-files/1.0"
        revision.manifest = manifest
    with pytest.raises((ChatSimilarityProvenanceError, ControlArtifactResolutionError)):
        store.read_similarity_provenance(pointer)


def test_invalid_companion_cannot_publish_either_member(store, prepared):
    invalid = prepared.provenance.model_copy(update={"provenance_sha256": "sha256:" + "b" * 64})
    with pytest.raises(ChatSimilarityProvenanceError):
        store.publish_similarity_record(prepared.record, invalid)
    with store.file_sets.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0
    assert not store.publisher.settings.staging_root.exists()


def test_publication_failure_cleans_only_temporary_materialization(store, prepared, monkeypatch):
    publish = Mock(side_effect=RuntimeError("synthetic commit interruption"))
    monkeypatch.setattr(store.file_sets, "publish_first_observation", publish)
    with pytest.raises(RuntimeError, match="synthetic commit interruption"):
        store.publish_similarity_record(prepared.record, prepared.provenance)
    assert publish.call_count == 1
    assert not tuple(store.publisher.settings.staging_root.glob("chat-similarity-*"))


def test_same_key_different_companion_is_not_an_in_place_update(store, prepared):
    pointer = store.publish_similarity_record(prepared.record, prepared.provenance)
    alternate = build_chat_similarity_provenance(
        record=prepared.record,
        scope=prepared.scope,
        native_request=prepared.native,
        native_reply=prepared.reply,
        delivered_native_items=(),
    )
    with pytest.raises(ControlPlaneError):
        store.publish_similarity_record(prepared.record, alternate)
    assert store.read_similarity_provenance(pointer) == prepared.provenance


def test_existing_legacy_key_is_not_upgraded_or_backfilled_in_place(store, prepared):
    request = prepared.record.request
    pointer = store.publish(
        payload=canonical_json_bytes(prepared.record),
        schema_ref="eom://schemas/general-chat/tool-record/2.0",
        intent=f"chat-tool:{request.ticket.claim_id}:{request.sequence}",
        created_at=datetime(2026, 10, 18, tzinfo=UTC),
    )
    with pytest.raises(ControlPlaneError):
        store.publish_similarity_record(prepared.record, prepared.provenance)
    assert store.read_similarity_provenance(pointer) is None
    assert store.read((pointer,)) == (canonical_json_bytes(prepared.record),)
