"""Actual common private Workflow/history/Artifact/composition; synthetic source IAM and math.

Public DOCUMENT values are built with the same declared space/recipe as the
canonical QUERY. This is not real-file public source or live model acceptance.
"""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingVectorRowRef
from eom_catalog_contracts.private_chat_query_prepare import private_chat_query_context_request_id
from eom_catalog_contracts.registered_public_solution_similarity import (
    PublicSolutionSimilarityViewV4,
    public_solution_reference_for_entry,
)
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_registry_ports import (
    AuthorizedEmbeddingReadProfile,
    EmbeddingRegistryCaller,
    EmbeddingRegistryLookup,
    EmbeddingRegistryRead,
    MaterializedEmbeddingReadRow,
    ResolvedPinnedEmbeddingIndex,
)
from eom_catalog_service.private_chat_similarity_ports import PrivateChatQueryUnavailable
from eom_catalog_service.public_solution_encoding import prepare_public_solution_encoding
from eom_catalog_service.public_solution_index_assembly import (
    assemble_registered_public_solution_index,
)
from eom_catalog_service.public_solution_similarity_read import CatalogPublicSolutionSimilarityRead
from eom_catalog_service.public_solution_similarity_service import VerifiedPublicSolutionQueryRead
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_orchestrator.models import ArtifactRevisionRecord, Base, JobRecord
from eom_workflow.compiler import compile_definition
from eom_workflow.private_chat_query_execution_v2 import PrivateChatQueryWorkflowRequestV2
from eom_workflow_runner import private_chat_similarity_read as reader_module
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from sqlalchemy import func, select

from tests.unit.inference_transfer_embedding_fixtures import seal, shard_pointer, vector_shard
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_native_embedding_query_handoff import prepared as reference_prepared
from tests.unit.test_private_chat_public_query_source_owner import make_private_public_source_case
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_similarity_read import (
    corrupt_scalar_read,
    make_private_similarity_read_case,
)
from tests.unit.test_public_solution_similarity_contracts import member


@pytest.fixture
def common_read(tmp_path, monkeypatch):
    compiled = compile_definition(
        Path(__file__).resolve().parents[2]
        / "config/workflows/local-embedding-private-chat-query.v2.yaml",
        set(),
    )
    current = make_private_public_source_case(
        tmp_path,
        monkeypatch,
        definition_sha256=compiled.sha256,
        resource_profile=reference_prepared().workflow_request.resource_profile,
    )
    return make_common_private_similarity_read_case(current, tmp_path, monkeypatch)


def make_common_private_similarity_read_case(current, tmp_path, monkeypatch):
    """Shared same-space DOCUMENT values; retain the supplied real DB/Artifact owners."""
    space = current.policy.spaces.document
    namespace = current.owner.configuration.registry.namespace
    capture = current.capture
    encodings = {}
    for entry in capture.entries:
        value = prepare_public_solution_encoding(
            entry, space=space, storage_partition=namespace.storage_partition
        )
        assert value.input is not None
        encodings[value.input.encoding.encoding_sha256] = value.input.encoding
    shard = vector_shard(tuple(encodings[key] for key in sorted(encodings)), space=space)
    shard_member = shard_pointer(shard, "a")
    rows = tuple(
        RegisteredEmbeddingRow(
            encoding,
            EmbeddingVectorRowRef(
                shard_manifest=shard_member,
                row_index=ordinal,
                encoding_sha256=encoding.encoding_sha256,
            ),
        )
        for ordinal, encoding in enumerate(shard.rows)
    )
    selected = current.request.context_request.views[0]
    index = assemble_registered_public_solution_index(
        capture.entries,
        available_rows=rows,
        shards=((shard_member, shard),),
        namespace=namespace,
        space=space,
        index_id=selected.index.index_id,
        index_revision_id="embeddingindexrev_" + uuid4().hex,
        previous_manifest=None,
        created_at=NOW,
    ).index
    context = current.request.context_request.model_dump(mode="json")
    context["request_id"] = private_chat_query_context_request_id(current.old.projection.origin)
    context["views"][0]["index"].update(
        index_revision_id=index.index_revision_id,
        index_sha256=index.index_sha256,
        index_manifest=member(
            index, schema="eom://schemas/knowledge/embedding-index-manifest/4.0", name="index.json"
        ).model_dump(mode="json"),
    )
    request = PrivateChatQueryWorkflowRequestV2.model_validate(
        seal(
            current.request.model_dump(mode="json")
            | {"context_request": seal(context, "request_sha256")},
            "request_sha256",
        )
    )
    scope = EmbeddingRegistryLookup(
        capture.corpus_id,
        namespace,
        request.context_request.graph_snapshot,
        request.context_request.policy_revision_id,
        request.context_request.policy_sha256,
        request.context_request.maximum_sources,
    )
    document = ResolvedPinnedEmbeddingIndex(
        EmbeddingRegistryRead(
            scope,
            PublicSolutionSimilarityViewV4.model_validate(
                request.context_request.views[0].model_dump(mode="json")
            ),
        ),
        capture.sources,
        tuple(
            AuthorizedEmbeddingReadProfile(
                entry.source.item_revision_id, public_solution_reference_for_entry(entry).profile
            )
            for entry in capture.entries
        ),
        index.bindings,
        tuple(
            MaterializedEmbeddingReadRow(row, (1.0,) + (0.0,) * (space.model_spec.dimension - 1))
            for row in rows
        ),
    )
    state = SimpleNamespace(capture=capture, document=document, reads=0)

    def public_read(application, session, caller, context):
        assert application.catalog is current.owner.catalog
        assert session.get_bind() is current.old.publisher.engine
        assert session.get_transaction() is not None and not session.in_nested_transaction()
        assert caller.operator_id == current.old.projection.origin.actor_id
        assert context == request.context_request
        state.reads += 1
        if current.old.fault.public_revoked or current.old.fault.value == "public":
            raise SimilarityContextReadError("SOURCE_REVOKED")
        return state.capture, state.document

    monkeypatch.setattr(
        CatalogPublicSolutionSimilarityRead, "read_private_documents_in_session", public_read
    )
    source = SimpleNamespace(
        owner=current.owner,
        publisher=current.old.publisher,
        request=request,
        policy=current.policy,
        bundle=current.old.bundle,
        projection=current.old.projection,
        fault=current.old.fault,
        events=current.old.events,
    )
    Base.metadata.create_all(
        source.publisher.engine,
        tables=[
            WorkflowDefinitionRecord.__table__,
            WorkflowInstanceRecord.__table__,
            WorkflowCommandRecord.__table__,
            WorkflowStepRunRecord.__table__,
        ],
    )
    result = make_private_similarity_read_case(source, tmp_path, monkeypatch)
    result.public = state
    return result


def read_in(session, value, caller=None):
    return value.read.resolve_public_private_chat_query_in_session(
        session,
        value.caller if caller is None else caller,
        value.request,
    )


def read(value):
    with value.native.publisher.sessions.begin() as session:
        return read_in(session, value)


def test_common_canonical_read_and_three_source_ranking_never_encode_again(common_read):
    value = common_read
    with value.native.publisher.sessions() as session:
        before = session.scalar(select(func.count()).select_from(JobRecord))
    query = read(value)
    assert type(query) is VerifiedPublicSolutionQueryRead
    assert query.request.rows[0].text == TEXT
    assert query.result_member == value.native.history()[1].records[2].payload.result
    first = value.read.compose_public_similarity(value.caller, value.request)
    replay = value.read.compose_public_similarity(value.caller, value.request)
    assert first == replay and first.status == "READY" and len(first.candidates) == 3
    assert {candidate.evidence.kind for candidate in first.candidates} == {
        "ACCEPTED_SOLUTION_ANALYSIS",
        "REGISTERED_CREATIVE_SOURCE_REPORT",
        "ACCEPTED_REGISTERED_SOLUTION_ANALYSIS",
    }
    assert first.query_execution.result_member == query.result_member
    assert TEXT not in repr(query) and value.native.encodes == len(value.native.runs) == 1
    with value.native.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == before


def test_empty_authorized_document_scope_has_no_fictional_scored_execution(common_read):
    value = common_read
    value.public.capture = replace(
        value.public.capture, sources=(), entries=(), base_analysis_run_ids=()
    )
    value.public.document = replace(
        value.public.document, sources=(), profiles=(), bindings=(), numerical_rows=()
    )
    result = value.read.compose_public_similarity(value.caller, value.request)
    assert result.status == "EMPTY" and result.query_execution is None and not result.candidates
    assert result.population.scored_count == 0 and value.native.encodes == 1


def test_common_document_from_another_vector_space_cannot_supply_scores(common_read):
    value = common_read
    document = value.public.document
    scope = document.intent.scope
    value.public.document = replace(
        document,
        intent=replace(
            document.intent,
            scope=replace(
                scope,
                namespace=scope.namespace.model_copy(update={"space_sha256": "sha256:" + "f" * 64}),
            ),
        ),
    )
    with pytest.raises(SimilarityContextReadError):
        value.read.compose_public_similarity(value.caller, value.request)
    assert value.native.encodes == 1


def test_common_source_withdrawal_during_ranking_prevents_delivery(common_read, monkeypatch):
    value = common_read
    original = reader_module.compose_private_chat_public_similarity

    def compose(*args, **kwargs):
        result = original(*args, **kwargs)
        value.source.fault.public_revoked = True
        return result

    monkeypatch.setattr(reader_module, "compose_private_chat_public_similarity", compose)
    with pytest.raises(SimilarityContextReadError, match="SOURCE_REVOKED"):
        value.read.compose_public_similarity(value.caller, value.request)
    assert value.native.encodes == 1


@pytest.mark.parametrize("state", ("REQUESTED", "RUNNING", "FAILED", "CANCELLED"))
def test_common_nonterminal_or_failed_original_is_not_reencoded(common_read, monkeypatch, state):
    value = common_read
    with value.native.publisher.sessions.begin() as session:
        assert (
            corrupt_scalar_read(monkeypatch, session, WorkflowInstanceRecord, "state", state) == []
        )
        if state in {"REQUESTED", "RUNNING"}:
            assert read_in(session, value) == PrivateChatQueryUnavailable("QUERY_NOT_OFFERED")
        else:
            with pytest.raises(SimilarityContextReadError, match="QUERY_RESULT_INVALID"):
                read_in(session, value)
    assert value.native.encodes == 1


@pytest.mark.parametrize("member_name", ("intent.json", "result.json", "shard.json", "vectors.f32"))
def test_common_corrupt_committed_output_is_not_readable_or_disclosed(common_read, member_name):
    value = common_read
    pointer = value.native.history()[1].records[2].payload.result
    with value.native.publisher.sessions() as session:
        revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
        target = Path(revision.nas_path, member_name)
    target.write_bytes(b"PRIVATE_CORRUPTION_NOT_FOR_ERRORS")
    with pytest.raises(SimilarityContextReadError) as error:
        read(value)
    assert "PRIVATE_CORRUPTION_NOT_FOR_ERRORS" not in str(error.value)
    assert value.native.encodes == 1


@pytest.mark.parametrize("fault", ("identity", "claim", "public_during_private_auth"))
def test_common_current_authority_cannot_be_replaced_by_old_completion(common_read, fault):
    common_read.source.fault.value = fault
    with pytest.raises(SimilarityContextReadError):
        read(common_read)
    assert common_read.native.encodes == 1


def test_common_other_caller_is_rejected_before_private_materialization(common_read):
    value = common_read
    before = len(value.source.events)
    with (
        value.native.publisher.sessions.begin() as session,
        pytest.raises(SimilarityContextReadError, match="SOURCE_ACCESS_DENIED"),
    ):
        read_in(session, value, EmbeddingRegistryCaller("operator_" + "f" * 32))
    assert len(value.source.events) == before


def test_legacy_reader_interface_cannot_relabel_common2_as_context1(common_read):
    with pytest.raises(SimilarityContextReadError, match="SOURCE_POINTER_INVALID"):
        common_read.read.prepare_private_chat_similarity(common_read.caller, common_read.request)
    assert common_read.native.encodes == 1


@pytest.mark.parametrize(
    "field,value",
    (
        ("created_actor_id", "operator_" + "f" * 32),
        ("runtime_context", {}),
        ("request_payload", {}),
        ("request_hash", "sha256:" + "f" * 64),
    ),
)
def test_common_changed_original_identity_cannot_borrow_receipt(
    common_read, monkeypatch, field, value
):
    with common_read.native.publisher.sessions.begin() as session:
        witnessed = corrupt_scalar_read(monkeypatch, session, WorkflowInstanceRecord, field, value)
        with pytest.raises(SimilarityContextReadError, match="QUERY_RESULT_INVALID"):
            read_in(session, common_read)
        assert witnessed
