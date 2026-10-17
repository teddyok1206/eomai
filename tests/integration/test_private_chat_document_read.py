"""Real disposable DB/file reads; source population and operator IAM are synthetic."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_contracts.embedding_registry import RegisterEmbeddingIndexCommand
from eom_catalog_contracts.embedding_vector_binary import pack_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import (
    RESULT_SCHEMA_REF,
    SHARD_SCHEMA_REF,
    EmbeddingIndexManifest,
    EmbeddingSourceBinding,
    EmbeddingSpace,
    EmbeddingVectorShardManifest,
    IncrementalEmbeddingResult,
)
from eom_catalog_contracts.private_chat_similarity import PrivateChatSimilarityRequest
from eom_catalog_service.embedding_registry_application import register_embedding_index
from eom_catalog_service.embedding_registry_catalog_adapter import (
    CatalogEmbeddingRegistryVerifier,
    EmbeddingRegistryOwnerConfiguration,
)
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryError
from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    AdmittedInferenceTransferSource,
)
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    InferenceTransferSessionCapture,
    InferenceTransferSessionCapturePhase,
)
from eom_catalog_service.knowledge_graph_models import (
    KnowledgeCorpusRecord,
    KnowledgeGraphPublicationRecord,
)
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.embedding_artifact_store import (
    EmbeddingArtifactStore,
    EmbeddingIndexPublicationScope,
)
from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_orchestrator.settings import Settings
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from tests.integration.test_embedding_registry_application import CALLER, _fixture
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.embedding_registry_application_fixtures import SyntheticVerifier
from tests.unit.inference_transfer_embedding_fixtures import embedding_result, seal
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_embedding_private_chat_query import private_context_request
from tests.unit.test_embedding_registry_catalog_adapter import _read_selection

pytestmark = pytest.mark.integration


@pytest.fixture
def registered(
    guarded_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
):
    assert guarded_engine.dialect.name == "postgresql"
    assert not tmp_path.is_relative_to(Path("/mnt/nas"))
    requested = getattr(request, "param", True)
    command, capture = _fixture(
        guarded_engine,
        view="CONTENT_ONLY",
        space=requested if isinstance(requested, EmbeddingSpace) else None,
    )
    if getattr(request, "param", True):
        with Session(guarded_engine) as session, session.begin():
            corpus = session.get(KnowledgeCorpusRecord, command.corpus_id)
            assert corpus is not None
            session.add(
                KnowledgeGraphPublicationRecord(
                    publication_id="graphpub_" + uuid4().hex,
                    corpus_id=command.corpus_id,
                    graph_snapshot_revision_id=command.graph_snapshot.graph_snapshot_revision_id,
                    idempotency_key="private-document-graph:" + uuid4().hex,
                    request_sha256=command.request_sha256,
                    published_by_operator_id=corpus.created_by_operator_id,
                    authorized_at=NOW,
                    requested_at=NOW,
                    published_at=NOW,
                )
            )
    settings = Settings(
        nas_artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspaces",
        staging_root=tmp_path / "staging",
    )
    settings.nas_artifact_root.mkdir(mode=0o700)
    settings.workspace_root.mkdir(mode=0o700)
    local = settings.workspace_root / "numeric"
    local.mkdir(mode=0o700)
    original = capture.shards[0][1]
    binary = pack_unit_vectors(
        ((1.0,) + (0.0,) * (original.dimension - 1),), dimension=original.dimension
    )
    body = original.model_dump(mode="json")
    body["binary"]["sha256"] = sha256_bytes(binary)
    shard = EmbeddingVectorShardManifest.model_validate(seal(body, "shard_sha256"))
    result = IncrementalEmbeddingResult.model_validate(
        seal(
            embedding_result().model_dump(mode="json")
            | {"shard": shard.model_dump(mode="json"), "input_set_sha256": shard.input_set_sha256},
            "result_sha256",
        )
    )
    members = []
    for name, payload, schema, media in (
        ("result.json", canonical_json_bytes(result), RESULT_SCHEMA_REF, "application/json"),
        ("shard.json", canonical_json_bytes(shard), SHARD_SCHEMA_REF, "application/json"),
        ("vectors.f32", binary, shard.binary.schema_ref, "application/octet-stream"),
    ):
        path = local / name
        path.write_bytes(payload)
        members.append(
            ControlFileSetMember(name, path, sha256_bytes(payload), len(payload), schema, media)
        )
    publisher = ControlFileSetPublisher(guarded_engine, settings)
    numerical = publisher.publish(
        members=tuple(members),
        primary_file="result.json",
        artifact_type="control_incremental_embedding",
        manifest_version=CONTROL_FILE_SET_PROTOCOL,
        idempotency_key="private-document-test:" + uuid4().hex,
        source_commit="a" * 40,
        created_at=NOW,
    )
    pointer = ArtifactMemberPointer(
        artifact_id=numerical.artifact_id,
        artifact_revision_id=numerical.artifact_revision_id,
        member_path="shard.json",
        schema_ref=SHARD_SCHEMA_REF,
        media_type="application/json",
        sha256=content_sha256(shard),
    )
    body = capture.index.bindings[0].model_dump(mode="json")
    body["row_ref"]["shard_manifest"] = pointer.model_dump(mode="json")
    binding = EmbeddingSourceBinding.model_validate(seal(body, "binding_sha256"))
    index = EmbeddingIndexManifest.model_validate(
        seal(
            capture.index.model_dump(mode="json")
            | {
                "bindings": [binding.model_dump(mode="json")],
                "shards": [pointer.model_dump(mode="json")],
            },
            "index_sha256",
        )
    )
    capture = replace(capture, index=index, shards=((pointer, shard),))
    publication_workspace = settings.workspace_root / "index"
    publication_workspace.mkdir(mode=0o700)
    published = EmbeddingArtifactStore(publisher, source_commit="a" * 40).publish_index(
        index=index,
        shards=capture.shards,
        previous=None,
        scope=EmbeddingIndexPublicationScope(
            command.graph_snapshot, command.policy_revision_id, command.policy_sha256
        ),
        workspace=publication_workspace,
    )
    command = RegisterEmbeddingIndexCommand.model_validate(
        seal(
            command.model_dump(mode="json")
            | {
                "index_manifest": published.index_manifest.model_dump(mode="json"),
                "index_sha256": index.index_sha256,
                "binding_set_sha256": content_sha256([binding.binding_sha256]),
            },
            "request_sha256",
        )
    )
    with Session(guarded_engine) as session, session.begin():
        register_embedding_index(session, CALLER, command, SyntheticVerifier(capture), now=NOW)
    verifier = CatalogEmbeddingRegistryVerifier(
        guarded_engine,
        EmbeddingRegistryOwnerConfiguration(
            command.corpus_id, command.namespace, index.space, index.recipe, ("PAST_EXAM",)
        ),
        identity_fence=Mock(),
        settings=CatalogSettings(nas_artifact_root=settings.nas_artifact_root),
    )
    corpus = AdmittedInferenceTransferCorpus(
        (capture.entries[0].profile,),
        (),
        False,
        0,
        (
            AdmittedInferenceTransferSource(
                binding.solution_evidence.base_analysis_run_id, binding.source
            ),
        ),
    )
    phases = []
    fault = SimpleNamespace(value=None)

    def source(session, source_command, _recipe, **options):
        assert session.get_transaction().is_active and not session.in_nested_transaction()
        assert source_command.actor_id == CALLER.operator_id
        assert source_command.source_revision_ids == ()
        phases.append(options["phase"])
        scope = SimpleNamespace(requester_permission_keys=("knowledge_graph:publish",))
        if phases.count(InferenceTransferSessionCapturePhase.CAPTURE_POPULATION) >= 2:
            if fault.value == "denied":
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")
            if fault.value == "source":
                return InferenceTransferSessionCapture(
                    scope, replace(corpus, profiles=(), sources=()), ()
                )
        if options["phase"] is InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE:
            return InferenceTransferSessionCapture(scope)
        return InferenceTransferSessionCapture(scope, corpus, capture.entries)

    monkeypatch.setattr(verifier.sources, "capture_in_session", source)
    selection, _registered = _read_selection(command, index)
    request = PrivateChatSimilarityRequest.model_validate(
        seal(
            private_context_request(selection.selection).model_dump(mode="json")
            | {
                "graph_snapshot": command.graph_snapshot.model_dump(mode="json"),
                "policy_revision_id": command.policy_revision_id,
                "policy_sha256": command.policy_sha256,
                "source_classes": ["PAST_EXAM"],
            },
            "request_sha256",
        )
    )
    return SimpleNamespace(
        verifier=verifier,
        request=request,
        phases=phases,
        fault=fault,
        settings=settings,
        binding=binding,
    )


@pytest.mark.parametrize(
    "fault", [None, "source", "denied", "index.json", "result.json", "shard.json", "vectors.f32"]
)
def test_private_read_registered_db_and_real_files_reauthorize_before_delivery(
    registered, guarded_engine, fault
):
    value, statements = registered, []

    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.upper())

    with Session(guarded_engine) as session, session.begin():
        root = session.get_transaction()
        prepared = value.verifier.prepare_private_chat_document_scope_in_session(
            session, CALLER, value.request
        )
        value.phases.clear()
        value.fault.value = fault
        if fault is not None and fault.endswith((".json", ".f32")):
            path = next(value.settings.nas_artifact_root.rglob(fault))
            path.write_bytes(path.read_bytes() + b"invalid")
        event.listen(guarded_engine, "before_cursor_execute", observe)
        try:
            if fault is None:
                result = value.verifier.read_private_chat_document_index_in_session(
                    session, CALLER, value.request, prepared
                )
                assert result[0].bindings == (value.binding,)
                assert result[0].numerical_rows[0].values[0] == 1.0
                assert (
                    value.phases.count(InferenceTransferSessionCapturePhase.CAPTURE_POPULATION) == 2
                )
            else:
                code = {"source": "SOURCE_REVOKED", "denied": "SOURCE_ACCESS_DENIED"}.get(
                    fault, "INDEX_POINTER_INVALID"
                )
                with pytest.raises(SimilarityContextReadError, match=code):
                    value.verifier.read_private_chat_document_index_in_session(
                        session, CALLER, value.request, prepared
                    )
        finally:
            event.remove(guarded_engine, "before_cursor_execute", observe)
        assert session.get_transaction() is root
        assert not session.new and not session.dirty and not session.deleted
    assert not any(s.lstrip().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)
    assert not any("FOR UPDATE" in s for s in statements)


@pytest.mark.parametrize("registered", [False], indirect=True)
def test_private_read_rejects_unpublished_graph_even_with_registered_index(
    registered, guarded_engine
):
    with (
        Session(guarded_engine) as session,
        session.begin(),
        pytest.raises(SimilarityContextReadError, match="SOURCE_POINTER_INVALID"),
    ):
        registered.verifier.prepare_private_chat_document_scope_in_session(
            session, CALLER, registered.request
        )
