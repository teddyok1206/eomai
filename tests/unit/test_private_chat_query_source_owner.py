"""Real local control files/publisher; Chat/IAM/public Catalog authority is synthetic."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryOwnerConfiguration
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.private_chat_similarity_ports import PreparedPrivateChatDocumentScope
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.embedding_runtime_bundle_artifacts import (
    EmbeddingRuntimeBundleArtifactPublisher,
)
from eom_orchestrator.general_chat_state import ChatError
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_workflow.private_chat_query_execution import (
    PrivateChatQueryExecutionPolicy,
    PrivateChatQueryWorkflowRequest,
)
from eom_workflow_runner.private_chat_query_source_read import (
    CatalogPrivateChatQuerySourceOwner,
    PrivateChatQueryOwnerConfiguration,
    build_private_chat_query_native_input,
    read_pinned_private_chat_query_controls,
)
from sqlalchemy import func, select, update

from tests.unit.embedding_registry_application_fixtures import capture_pair
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import runtime_profile
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_embedding_registry_catalog_adapter import _read_selection
from tests.unit.test_local_embedding_control_artifacts import NOW
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_execution import execution_case
from tests.unit.test_private_chat_query_source import source_case


@pytest.fixture
def source(tmp_path, monkeypatch):
    publisher, _ = _publisher(tmp_path)
    publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    request, policy, bundle = execution_case()
    saved_bundle = EmbeddingRuntimeBundleArtifactPublisher(
        ControlArtifactPublisher(publisher.engine, publisher.settings), source_commit="a" * 40
    ).publish(bundle, created_at=NOW)
    policy = PrivateChatQueryExecutionPolicy.model_validate(
        seal(
            policy.model_dump(mode="json")
            | {"runtime_bundle": saved_bundle.bundle.model_dump(mode="json")},
            "policy_sha256",
        )
    )
    controls = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    saved_policy = controls.publish_private_chat_query_policy(
        policy, idempotency_key="private-owner-test:policy", created_at=NOW
    )
    chat_source = source_case(question=TEXT)
    projection = chat_source.execution.materialize_live_private_query(chat_source.ticket)
    context = seal(
        request.context_request.model_dump(mode="json")
        | {"query_basis": projection.origin.basis.model_dump(mode="json")},
        "request_sha256",
    )
    request = PrivateChatQueryWorkflowRequest.model_validate(
        seal(
            request.model_dump(mode="json")
            | {
                "operator_audit": request.operator_audit.model_dump(mode="json")
                | {"operator_id": projection.origin.actor_id},
                "context_request": context,
                "native_execution_policy": saved_policy.member.model_dump(mode="json"),
                "native_execution_policy_sha256": policy.policy_sha256,
                "runtime_bundle": saved_bundle.bundle.model_dump(mode="json"),
            },
            "request_sha256",
        )
    )
    selected = request.context_request.views[0]
    config = PrivateChatQueryOwnerConfiguration(
        EmbeddingRegistryOwnerConfiguration(
            "corpus_" + "1" * 32,
            EmbeddingIndexNamespace(
                storage_partition=selected.index.storage_partition,
                space_sha256=policy.spaces.document.space_sha256,
                view="CONTENT_ONLY",
                recipe_sha256=selected.recipe.recipe_sha256,
                population_scope="OCCURRENCE_BACKED_PAST_EXAM",
            ),
            policy.spaces.document,
            selected.recipe,
            request.context_request.source_classes,
        ),
        saved_policy.member,
        policy.policy_sha256,
        saved_bundle.bundle,
    )
    fault = SimpleNamespace(value=None, session=None, public_revoked=False)
    events = []

    def identity(session, actor):
        assert actor == projection.origin.actor_id
        events.append("identity")
        if fault.value == "identity" or (
            fault.value == "late_identity" and events.count("identity") == 2
        ):
            raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN")

    def materialize(ticket):
        events.append("materialize")
        assert ticket == projection.origin.ticket
        if fault.value == "chat":
            raise ChatError("GENERAL_CHAT_FORBIDDEN")
        if fault.value == "text":
            return projection.model_copy(update={"text": TEXT + "DO_NOT_DISCLOSE"})
        return chat_source.execution.materialize_live_private_query(ticket)

    def authorize(origin):
        events.append("authorize")
        if fault.value == "public_during_private_auth":
            fault.public_revoked = True
        if fault.value == "claim":
            raise ChatError("GENERAL_CHAT_CLAIM_MISMATCH")
        if fault.value == "origin":
            return ChatPrivateQueryOrigin.model_validate(
                seal(
                    origin.model_dump(mode="json") | {"runtime_id": "chatrt_" + "f" * 32},
                    "origin_sha256",
                )
            )
        if fault.value == "producer":
            with publisher.sessions.begin() as writer:
                writer.execute(
                    update(JobRecord)
                    .where(JobRecord.job_id == saved_policy.owner_job_id)
                    .values(status="FAILED")
                )
        if fault.value == "pending":
            fault.session.add(JobRecord(job_id="job_" + "f" * 32))
        return chat_source.execution.authorize_live_private_query(origin)

    owner = CatalogPrivateChatQuerySourceOwner(
        publisher.engine,
        config,
        chat=SimpleNamespace(materialize=materialize, authorize=authorize),
        identity_fence=SimpleNamespace(fence_current_operator=identity),
        settings=CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root),
    )
    documents = PreparedPrivateChatDocumentScope(request.context_request.request_sha256, ())

    def prepare(session, caller, context, *, artifact_reader):
        assert session is fault.session and caller.operator_id == projection.origin.actor_id
        assert context == request.context_request
        artifact_reader.require_session(session)
        events.append("public_prepare")
        if fault.public_revoked:
            raise SimilarityContextReadError("SOURCE_REVOKED")
        return documents

    def read(session, caller, context, prepared, *, artifact_reader):
        assert prepared == documents and session is fault.session
        artifact_reader.require_session(session)
        events.append("public_read")
        if fault.value == "public":
            raise SimilarityContextReadError("SOURCE_REVOKED")
        return (object(),) if fault.value != "index" else ()

    monkeypatch.setattr(owner.catalog, "prepare_private_chat_document_scope_in_session", prepare)
    monkeypatch.setattr(owner.catalog, "read_private_chat_document_index_in_session", read)
    return SimpleNamespace(
        owner=owner,
        publisher=publisher,
        request=request,
        policy=policy,
        bundle=bundle,
        projection=projection,
        fault=fault,
        events=events,
        controls=controls,
        saved_policy=saved_policy,
    )


def test_private_owner_resolves_current_original_question_and_real_canonical_controls(source):
    with source.publisher.sessions.begin() as session:
        source.fault.session = session
        root = session.get_transaction()
        result = source.owner.resolve_sources(session, source.request, source.projection.origin)
        assert result.projection == source.projection and result.policy == source.policy
        assert TEXT not in repr(result)
        native = build_private_chat_query_native_input(
            result, job_id="job_" + "a" * 32, query_request_id="embeddingquery_" + "b" * 32
        )
        assert native.row.text == TEXT and native.basis == source.projection.origin.basis
        assert source.events == [
            "identity",
            "materialize",
            "public_prepare",
            "public_read",
            "authorize",
            "identity",
            "public_prepare",
        ]
        assert session.get_transaction() is root and not session.new and not session.dirty
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 2
        for job in session.scalars(select(JobRecord)):
            assert TEXT.encode() not in canonical_json_bytes(job.request)
        for revision in session.scalars(select(ArtifactRevisionRecord)):
            assert TEXT.encode() not in canonical_json_bytes(revision.result)


@pytest.mark.parametrize(
    "fault,code",
    [
        ("identity", "SOURCE_ACCESS_DENIED"),
        ("late_identity", "SOURCE_ACCESS_DENIED"),
        ("chat", "SOURCE_ACCESS_DENIED"),
        ("claim", "AUTHORITY_UNAVAILABLE"),
        ("origin", "SOURCE_REVOKED"),
        ("text", "SOURCE_POINTER_INVALID"),
        ("producer", "SOURCE_POINTER_INVALID"),
        ("pending", "AUTHORITY_UNAVAILABLE"),
        ("public", "SOURCE_REVOKED"),
        ("public_during_private_auth", "SOURCE_REVOKED"),
        ("index", "INDEX_POINTER_INVALID"),
    ],
)
def test_current_private_and_public_changes_refuse_delivery_with_redacted_error(
    source, fault, code
):
    source.fault.value = fault
    with source.publisher.sessions.begin() as session:
        source.fault.session = session
        with pytest.raises(SimilarityContextReadError) as error:
            source.owner.resolve_sources(session, source.request, source.projection.origin)
        assert error.value.code == code
        assert TEXT not in str(error.value) and "DO_NOT_DISCLOSE" not in str(error.value)
        # The deliberate pending row is a negative fixture, never persisted.
        session.rollback()


@pytest.mark.parametrize("fault", ["actor", "basis", "policy", "runtime", "extra"])
def test_request_metadata_cannot_supply_other_actor_or_controls(source, fault):
    body = source.request.model_dump(mode="json")
    if fault == "actor":
        body["operator_audit"]["operator_id"] = "operator_" + "f" * 32
    elif fault == "basis":
        context = body["context_request"]
        context["query_basis"] = seal(
            context["query_basis"] | {"turn_id": "chatturn_" + "f" * 32}, "basis_sha256"
        )
        body["context_request"] = seal(context, "request_sha256")
    elif fault == "policy":
        body["native_execution_policy_sha256"] = "sha256:" + "f" * 64
    elif fault == "runtime":
        body["runtime_bundle"]["bundle_revision_id"] = "embeddingbundlerev_" + "f" * 32
    else:
        body["authority"] = TEXT
    request = (
        source.request.model_copy(update=body)
        if fault == "extra"
        else PrivateChatQueryWorkflowRequest.model_validate(seal(body, "request_sha256"))
    )
    with source.publisher.sessions.begin() as session:
        source.fault.session = session
        with pytest.raises(SimilarityContextReadError, match="SOURCE_POINTER_INVALID") as error:
            source.owner.resolve_sources(session, request, source.projection.origin)
        assert TEXT not in str(error.value) and source.events == []


@pytest.mark.parametrize("name", ["policy.json", "bundle.json"])
def test_selected_control_bytes_are_required_and_never_repaired(source, name):
    path = next(source.publisher.settings.nas_artifact_root.rglob(name))
    path.write_bytes(path.read_bytes() + b"invalid")
    with source.publisher.sessions.begin() as session:
        source.fault.session = session
        with pytest.raises(SimilarityContextReadError, match="SOURCE_POINTER_INVALID"):
            source.owner.resolve_sources(session, source.request, source.projection.origin)
    assert path.read_bytes().endswith(b"invalid")


def test_policy_replay_and_conflict_use_existing_owner_without_question_storage(source):
    key = "private-owner-test:policy"
    assert (
        source.controls.publish_private_chat_query_policy(
            source.policy, idempotency_key=key, created_at=NOW
        )
        == source.saved_policy
    )
    changed = PrivateChatQueryExecutionPolicy.model_validate(
        seal(
            source.policy.model_dump(mode="json")
            | {
                "continuation_mode": "OPERATOR_REQUEST_ONLY",
                "gpu_busy": "WAIT",
                "created_at": "2026-10-13T15:00:01Z",
            },
            "policy_sha256",
        )
    )
    with pytest.raises(ControlPlaneError) as conflict:
        source.controls.publish_private_chat_query_policy(
            changed, idempotency_key=key, created_at=NOW
        )
    assert conflict.value.code == "CONTROL_FILE_SET_CONFLICT"
    with source.publisher.sessions.begin() as session:
        source.fault.session = session
        assert (
            read_pinned_private_chat_query_controls(
                PinnedArtifactReadContext(session, source.owner.settings),
                source.owner.configuration,
            )[0]
            == source.policy
        )


@pytest.mark.parametrize("fault", ["private_extra", "reference", "bad_hash"])
def test_invalid_policy_family_rejected_before_new_publication(source, fault):
    value = (
        source.policy.model_copy(update={"actor_text": TEXT})
        if fault == "private_extra"
        else source.policy.model_copy(
            update={"purpose": "REFERENCE_QUERY"}
            if fault == "reference"
            else {"policy_sha256": "sha256:" + "f" * 64}
        )
    )
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_CONTROL_INVALID") as error:
        source.controls.publish_private_chat_query_policy(
            value, idempotency_key="bad-policy", created_at=NOW
        )
    assert TEXT not in str(error.value)
    with source.publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 2


@pytest.mark.parametrize("fault", ["missing", "nested", "new"])
def test_source_owner_requires_clean_original_root_before_any_owner_read(source, fault):
    with source.publisher.sessions() as session:
        source.fault.session = session
        if fault != "missing":
            session.begin()
            if fault == "nested":
                session.begin_nested()
            else:
                session.add(JobRecord(job_id="job_" + "f" * 32))
        with pytest.raises(SimilarityContextReadError, match="AUTHORITY_UNAVAILABLE"):
            source.owner.resolve_sources(session, source.request, source.projection.origin)
        assert source.events == []
        session.rollback()


@pytest.mark.parametrize("space", [None, runtime_profile("CPU").space])
def test_document_selection_fixture_derives_query_from_exact_selected_space(space):
    command, capture = capture_pair(view="CONTENT_ONLY", space=space)
    read, _registered = _read_selection(command, capture.index)
    selected = read.selection.index.spaces
    assert selected.query.purpose == "QUERY" and selected.document.purpose == "DOCUMENT"
    assert selected.query.model_spec == selected.document.model_spec
    assert selected.query.runtime == selected.document.runtime
    if space is not None:
        assert selected == execution_case()[1].spaces
