"""Concrete immutable-byte composition with synthetic source/IAM ports, never live admission."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import EvidenceBudget
from eom_catalog_contracts.embedding_registry import RegisterEmbeddingIndexCommand
from eom_catalog_contracts.embedding_vector_binary import pack_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import (
    RESULT_SCHEMA_REF,
    EmbeddingIndexManifest,
    EmbeddingVectorShardManifest,
)
from eom_catalog_service import inference_transfer_catalog_adapter as source_module
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_registry_application import (
    validate_resolved_embedding_registration,
)
from eom_catalog_service.embedding_registry_catalog_adapter import (
    CatalogEmbeddingRegistryVerifier,
    EmbeddingRegistryOwnerConfiguration,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingBindingOrigin,
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
)
from eom_catalog_service.inference_transfer_catalog_adapter import (
    AcceptedInferenceTransferProfileInput,
    CatalogInferenceTransferSourceAdapter,
    InferenceTransferCorpusReadCommand,
)
from eom_catalog_service.inference_transfer_scope import InferenceTransferPopulationScope
from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    AdmittedInferenceTransferSource,
    InferenceTransferServiceError,
)
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    CatalogInferenceTransferSnapshotSourceAdapter,
    InferenceTransferSessionCapture,
    InferenceTransferSessionCapturePhase,
)
from eom_catalog_service.knowledge_graph_models import KnowledgeGraphSnapshotRecord
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalServiceError,
    ReadOnlyCandidatePoolScope,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_operator_identity import PermissionKey
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from sqlalchemy.orm import Session

from tests.unit.embedding_registry_application_fixtures import capture_pair
from tests.unit.inference_transfer_embedding_fixtures import (
    embedding_result,
    index_pointer,
    seal,
    shard_pointer,
    source_binding,
)
from tests.unit.test_inference_transfer_snapshot_catalog_adapter import owner_input
from tests.unit.test_pinned_artifact_read_context import MetadataSession


class OwnerSession(MetadataSession):
    def __init__(self, command: RegisterEmbeddingIndexCommand, *records: object) -> None:
        super().__init__(*records)
        self.corpus = SimpleNamespace(
            lifecycle_state="ACTIVE", graph_id=command.graph_snapshot.graph_id
        )
        self.graph = SimpleNamespace(graph_id=command.graph_snapshot.graph_id)

    def scalar(self, statement: Any) -> object:
        model = statement.column_descriptions[0]["entity"]
        return self.corpus if model.__name__ == "KnowledgeCorpusRecord" else object()

    def get(self, model: type[Any], identity: str) -> Any:
        if model is KnowledgeGraphSnapshotRecord:
            return self.graph
        return super().get(model, identity)

    def scalars(self, statement: Any) -> list[Any]:
        rows = super().scalars(statement)
        selected = next(iter(statement.compile().params.values()))
        if rows and isinstance(rows[0], ArtifactRevisionRecord):
            return [row for row in rows if (row.logical_artifact_id, row.revision_id) in selected]
        if rows and isinstance(rows[0], ArtifactRecord):
            return [row for row in rows if row.logical_artifact_id in selected]
        return [row for row in rows if row.job_id in selected]


def _file_set(
    root: Path,
    artifact_id: str,
    revision_id: str,
    artifact_type: str,
    primary: str,
    members: dict[str, tuple[bytes, str, str]],
    job_seed: str,
) -> tuple[object, ...]:
    directory = root / artifact_id / revision_id
    directory.mkdir(parents=True)
    files = []
    for name, (payload, schema, media) in members.items():
        (directory / name).write_bytes(payload)
        files.append(
            dict(
                file_name=name,
                sha256=sha256_bytes(payload),
                bytes=len(payload),
                schema_ref=schema,
                media_type=media,
            )
        )
    job_id = "job_" + job_seed * 32
    primary_payload = members[primary][0]
    manifest = dict(
        manifest_version="control-file-set/1.0",
        job_id=job_id,
        logical_artifact_id=artifact_id,
        revision_id=revision_id,
        artifact_type=artifact_type,
        primary_file=primary,
        content_hash=sha256_bytes(primary_payload),
        content_bytes=len(primary_payload),
        files=files,
    )
    return (
        JobRecord(
            job_id=job_id,
            protocol_version="fixture/1.0",
            idempotency_key=job_id,
            request_hash=sha256_bytes(b"request"),
            task_type=artifact_type,
            request={},
            status="SUCCEEDED",
            logical_artifact_id=artifact_id,
            revision_id=revision_id,
        ),
        ArtifactRecord(
            logical_artifact_id=artifact_id,
            job_id=job_id,
            artifact_type=artifact_type,
            approved=True,
        ),
        ArtifactRevisionRecord(
            revision_id=revision_id,
            logical_artifact_id=artifact_id,
            job_id=job_id,
            content_hash=sha256_bytes(primary_payload),
            manifest_hash=content_sha256(manifest),
            content_bytes=len(primary_payload),
            nas_path=str(directory),
            manifest=manifest,
            result={},
            approved=True,
        ),
    )


@pytest.fixture
def owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    command, resolved = capture_pair()
    original = resolved.shards[0][1]
    vector = pack_unit_vectors(
        ((1.0,) + (0.0,) * (original.dimension - 1),), dimension=original.dimension
    )
    shard_body = original.model_dump(mode="json")
    shard_body["binary"]["sha256"] = sha256_bytes(vector)
    shard = EmbeddingVectorShardManifest.model_validate(seal(shard_body, "shard_sha256"))
    pointer = shard_pointer(shard)
    binding = source_binding(resolved.entries[0], shard=shard, pointer=pointer)
    index_body = resolved.index.model_dump(mode="json")
    index_body.update(
        shards=[pointer.model_dump(mode="json")], bindings=[binding.model_dump(mode="json")]
    )
    index = EmbeddingIndexManifest.model_validate(seal(index_body, "index_sha256"))
    index_member = index_pointer(index)
    body = command.model_dump(mode="json")
    body.update(
        index_manifest=index_member.model_dump(mode="json"),
        index_sha256=index.index_sha256,
        binding_set_sha256=content_sha256([binding.binding_sha256]),
    )
    command = RegisterEmbeddingIndexCommand.model_validate(seal(body, "request_sha256"))
    result = embedding_result().model_dump(mode="json")
    result["shard"] = shard.model_dump(mode="json")
    result["input_set_sha256"] = shard.input_set_sha256
    result = seal(result, "result_sha256")
    numerical = _file_set(
        tmp_path,
        pointer.artifact_id,
        pointer.artifact_revision_id,
        "control_incremental_embedding",
        "result.json",
        {
            "result.json": (canonical_json_bytes(result), RESULT_SCHEMA_REF, "application/json"),
            "shard.json": (
                canonical_json_bytes(shard.model_dump(mode="json")),
                pointer.schema_ref,
                "application/json",
            ),
            "vectors.f32": (vector, shard.binary.schema_ref, "application/octet-stream"),
        },
        "c",
    )
    publication = _file_set(
        tmp_path,
        index_member.artifact_id,
        index_member.artifact_revision_id,
        "control_embedding_index",
        "index.json",
        {
            "index.json": (
                canonical_json_bytes(index.model_dump(mode="json")),
                index_member.schema_ref,
                "application/json",
            ),
        },
        "d",
    )
    session = OwnerSession(command, *numerical, *publication)
    verifier = CatalogEmbeddingRegistryVerifier(
        cast(Any, object()),
        EmbeddingRegistryOwnerConfiguration(
            command.corpus_id, command.namespace, index.space, index.recipe, ("PAST_EXAM",)
        ),
        identity_fence=Mock(),
        settings=CatalogSettings(nas_artifact_root=tmp_path),
    )
    scope = cast(
        ReadOnlyCandidatePoolScope,
        SimpleNamespace(requester_permission_keys=("knowledge_graph:publish",)),
    )
    corpus = AdmittedInferenceTransferCorpus(
        (resolved.entries[0].profile,),
        (),
        False,
        0,
        (
            AdmittedInferenceTransferSource(
                binding.solution_evidence.base_analysis_run_id, binding.source
            ),
        ),
    )

    def capture(
        _session: Session, _command: Any, _recipe: Any, **options: Any
    ) -> InferenceTransferSessionCapture:
        options["artifact_reader"].require_session(_session)
        options["identity_fence"].fence_current_operator(_session, _command.actor_id)
        if options.get("phase") is InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE:
            return InferenceTransferSessionCapture(scope)
        return InferenceTransferSessionCapture(scope, corpus, resolved.entries)

    monkeypatch.setattr(verifier.sources, "capture_in_session", Mock(side_effect=capture))
    return verifier, session, command, index, binding, scope, tmp_path


def test_canonical_committed_index_shard_result_binary_and_source_composition(
    owner: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier, session, command, index, binding, _scope, _root = owner
    caller = EmbeddingRegistryCaller("operator_" + "1" * 32)
    monkeypatch.setattr(verifier, "_guard", lambda operation: operation())
    resolved = verifier.resolve_registration(session, caller, command)
    assert validate_resolved_embedding_registration(command, resolved) == resolved
    references = verifier.verify_registered_references(
        session,
        caller,
        command,
        (RegisteredEmbeddingRow(binding.encoding, binding.row_ref),),
        (EmbeddingBindingOrigin(binding.binding_sha256, command.index_manifest),),
    )
    assert (
        references.origins[0].binding == binding
        and references.shards[0][1] == resolved.shards[0][1]
    )
    assert resolved.index == index
    assert all(
        statement.get_execution_options()["populate_existing"] for statement in session.statements
    )


@pytest.mark.parametrize(
    "failure,code",
    [
        ("fence", "EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE"),
        ("publish", "EMBEDDING_REGISTRY_FORBIDDEN"),
        ("corpus", "EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH"),
        ("binary", "EMBEDDING_REGISTRY_POINTER_INVALID"),
        ("producer", "EMBEDDING_REGISTRY_POINTER_INVALID"),
        ("approval", "EMBEDDING_REGISTRY_POINTER_INVALID"),
        ("version", "EMBEDDING_REGISTRY_POINTER_INVALID"),
    ],
)
def test_owner_refuses_missing_authority_lifecycle_and_byte_drift(
    owner: tuple[Any, ...], failure: str, code: str
) -> None:
    verifier, session, command, _index, binding, scope, root = owner
    if failure == "fence":
        verifier.identity_fence = None
    elif failure == "publish":
        scope.requester_permission_keys = ()
    elif failure == "corpus":
        session.corpus.lifecycle_state = "RETIRED"
    elif failure == "binary":
        p = binding.row_ref.shard_manifest
        (root / p.artifact_id / p.artifact_revision_id / "vectors.f32").write_bytes(b"corrupt")
    elif failure == "producer":
        session.get(JobRecord, "job_" + "c" * 32).status = "RUNNING"
    elif failure == "version":
        revision = session.get(ArtifactRevisionRecord, command.index_manifest.artifact_revision_id)
        revision.manifest["manifest_version"] = "catalog-file-set/1.0"
        revision.manifest_hash = content_sha256(revision.manifest)
    else:
        session.get(ArtifactRecord, binding.row_ref.shard_manifest.artifact_id).approved = False
    with pytest.raises(EmbeddingRegistryError, match=code):
        verifier.resolve_registration(
            session, EmbeddingRegistryCaller("operator_" + "1" * 32), command
        )
    if failure == "fence":
        assert not session.statements and not verifier.sources.capture_in_session.called


def test_lookup_is_read_scoped_and_retained_reference_values_are_revalidated(
    owner: tuple[Any, ...],
) -> None:
    verifier, session, command, _index, binding, scope, _root = owner
    scope.requester_permission_keys = ()
    query = EmbeddingRegistryLookup(
        command.corpus_id,
        command.namespace,
        command.graph_snapshot,
        command.policy_revision_id,
        command.policy_sha256,
    )
    caller = EmbeddingRegistryCaller("operator_" + "1" * 32)
    assert verifier.resolve_lookup(session, caller, query).sources == (binding.source,)
    forged = binding.row_ref.model_copy(update={"row_index": -1})
    with pytest.raises(EmbeddingRegistryError, match="POINTER_INVALID"):
        verifier.verify_registered_references(
            session, caller, query, (RegisteredEmbeddingRow(binding.encoding, forged),), ()
        )
    with pytest.raises(EmbeddingRegistryError, match="SOURCE_PIN_MISMATCH"):
        verifier.resolve_lookup(session, caller, replace(query, corpus_id="corpus_" + "f" * 32))


def _scope_owner(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    command, resolved = capture_pair()
    request = InferenceTransferCorpusReadCommand(
        "operator_" + "1" * 32,
        command.graph_snapshot,
        command.policy_revision_id,
        command.policy_sha256,
        ("PAST_EXAM",),
        1024,
        InferenceTransferPopulationScope.ALL_ADMITTED_GRAPH_ITEMS,
    )
    actor = SimpleNamespace(status="ACTIVE", deleted_at=None, must_change_password=False)
    session = Mock()
    session.get.return_value = actor
    session.scalars.return_value = ()
    session.execute.return_value = ()
    permissions = {
        PermissionKey.ITEM_READ,
        PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
        PermissionKey.KNOWLEDGE_ANALYSIS_READ,
        PermissionKey.CONTENT_INTAKE_READ,
    }
    roles = [(object(), SimpleNamespace(role_key="REVIEWER"))]
    monkeypatch.setattr(
        source_module, "effective_permissions", lambda _session, _actor: permissions
    )
    monkeypatch.setattr(source_module, "active_role_assignments", lambda _session, _actor: roles)
    source = object.__new__(CatalogInferenceTransferSourceAdapter)
    source.retrieval = Mock()
    source.retrieval.resolve_access_policy.return_value = SimpleNamespace(
        allowed_requester_roles=("REVIEWER",),
        answer_bearing_roles=("REVIEWER",),
        maximum_budget=EvidenceBudget(
            max_documents=1,
            max_item_revisions=64,
            max_graph_nodes=64,
            max_claims=64,
            max_context_tokens=4096,
        ),
    )
    source.retrieval.resolve_snapshot_pointer.return_value = request.graph_snapshot
    source.retrieval.admit_read_only_candidate_pool.return_value = SimpleNamespace(
        truncated=False, candidates=()
    )
    monkeypatch.setattr(source, "_resolve_profile_inputs", Mock(return_value=((), 0)))
    snapshot = object.__new__(CatalogInferenceTransferSnapshotSourceAdapter)
    snapshot.sources = source
    monkeypatch.setattr(snapshot, "_materialize_entries", Mock(return_value={}))
    reader = Mock(spec=PinnedArtifactReadContext)
    fence = Mock()
    return (
        snapshot,
        session,
        request,
        resolved.index.recipe,
        reader,
        fence,
        actor,
        permissions,
        roles,
    )


@pytest.mark.parametrize(
    "denial", ["disabled", "deleted", "password", "permission", "worker", "fence"]
)
def test_in_session_capture_uses_actual_existing_operator_scope_before_member_io(
    monkeypatch: pytest.MonkeyPatch,
    denial: str,
) -> None:
    snapshot, session, request, recipe, reader, fence, actor, permissions, roles = _scope_owner(
        monkeypatch
    )
    if denial == "disabled":
        actor.status = "DISABLED"
    elif denial == "deleted":
        actor.deleted_at = object()
    elif denial == "password":
        actor.must_change_password = True
    elif denial == "permission":
        permissions.remove(PermissionKey.KNOWLEDGE_ANALYSIS_READ)
    elif denial == "worker":
        roles[0][1].role_key = "WORKER"
    else:
        fence = None
    with pytest.raises(InferenceTransferServiceError):
        snapshot.capture_in_session(
            session,
            request,
            recipe,
            identity_fence=fence,
            artifact_reader=reader,
            phase=InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE,
        )
    assert not reader.prefetch.called and not reader.read_member.called
    assert not snapshot.sources.retrieval.admit_read_only_candidate_pool.called


def test_in_session_capture_batches_fences_then_delegates_unchanged_source_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot, session, request, recipe, reader, fence, *_ = _scope_owner(monkeypatch)
    result = snapshot.capture_in_session(
        session, request, recipe, identity_fence=fence, artifact_reader=reader
    )
    fence.fence_current_operator.assert_called_once_with(session, request.actor_id)
    assert result.corpus is not None and not result.corpus.sources
    calls = session.scalars.call_args_list
    assert len(calls) == 3 and len(session.execute.call_args_list) == 1
    membership = calls[0].args[0]
    assert membership._limit_clause.value == 1025
    source_lock = session.execute.call_args.args[0]
    run_lock = calls[1].args[0]
    assert source_lock._for_update_arg.read and run_lock._for_update_arg.read
    assert source_lock.get_execution_options()["populate_existing"]
    assert run_lock.get_execution_options()["populate_existing"]
    reader.prefetch.assert_called_once_with(
        (
            (
                request.graph_snapshot.manifest_artifact.artifact_id,
                request.graph_snapshot.manifest_artifact.artifact_revision_id,
            ),
        )
    )
    reader.verify_member.assert_called_once()
    snapshot.sources.retrieval.admit_read_only_candidate_pool.assert_called_once_with(
        session, result.scope, artifact_reader=reader
    )
    snapshot.sources._resolve_profile_inputs.assert_called_once_with(
        session,
        snapshot.sources.retrieval.admit_read_only_candidate_pool.return_value,
        artifact_reader=reader,
    )


def test_in_session_capture_refuses_truncated_membership_without_partial_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot, session, request, recipe, reader, fence, *_ = _scope_owner(monkeypatch)
    session.scalars.return_value = (object(),) * 1025
    with pytest.raises(InferenceTransferServiceError, match="POPULATION_TRUNCATED"):
        snapshot.capture_in_session(
            session, request, recipe, identity_fence=fence, artifact_reader=reader
        )
    assert (
        not reader.prefetch.called
        and not snapshot.sources.retrieval.admit_read_only_candidate_pool.called
    )


def test_injected_member_reader_preserves_official_item_projection_and_shared_read() -> None:
    load_owner_input = cast(
        Callable[[str], tuple[AcceptedInferenceTransferProfileInput, Any, bytes]], owner_input
    )
    value, _candidate, payload = load_owner_input("a")
    _command, resolved = capture_pair()
    adapter = object.__new__(CatalogInferenceTransferSnapshotSourceAdapter)
    adapter.engine = Mock()
    reader = Mock()
    reader.read_member.return_value = payload
    entries = adapter._materialize_entries(
        resolved.index.recipe, (value, value), artifact_reader=reader
    )
    assert len(entries) == 1 and next(iter(entries.values())).profile == value.profile
    assert next(iter(entries.values())).content is not None
    reader.read_member.assert_called_once()
    assert not adapter.engine.called


def test_injected_reader_cannot_replace_existing_historical_reuse_context() -> None:
    application = object.__new__(KnowledgeRetrievalApplicationService)
    with pytest.raises(KnowledgeRetrievalServiceError) as error:
        application.admit_read_only_candidate_pool(
            Mock(), Mock(), reuse_context=Mock(), artifact_reader=Mock()
        )
    assert error.value.code == "KNOWLEDGE_RETRIEVAL_REUSE_CONTEXT_INVALID"
