"""Guarded disposable metadata transactions; no production source/Artifact admission.

The verifier below is deliberately test-only: it checks synthetic canonical JSON
metadata and actual approved/accepted DB states, not report bytes, permissions or
NAS vectors. Official owner composition remains unavailable in production. Parent
and independent child processes are the trusted test driver, never worker users.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import re
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_contracts.embedding_registry import RegisterEmbeddingIndexCommand
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingIndexManifest,
    EmbeddingSourceBinding,
    EmbeddingVectorShardManifest,
)
from eom_catalog_contracts.inference_transfer_experiment import (
    ExperimentView,
    StagedExperimentEntry,
    population_sha256,
)
from eom_catalog_service.embedding_registry_application import (
    lookup_missing_embedding_bindings,
    register_embedding_index,
    verify_embedding_index_registration_observation,
)
from eom_catalog_service.embedding_registry_models import (
    EmbeddingEncodingRecord,
    EmbeddingIndexRecord,
    EmbeddingIndexRevisionRecord,
    EmbeddingSourceBindingRecord,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingBindingLookupKey,
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    EmbeddingRegistryServiceCaller,
    ResolvedEmbeddingRegistration,
)
from eom_catalog_service.embedding_registry_repository import (
    ASSOCIATION_COLUMNS,
    EmbeddingRegistryRepository,
)
from eom_catalog_service.knowledge_graph_models import KnowledgeGraphSnapshotRecord
from eom_catalog_service.models import ItemRecord, ItemRevisionRecord
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_operator_identity import LocalIndexingServiceReference
from eom_orchestrator.database import build_engine
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import Engine, Table, event, func, select, text
from sqlalchemy.orm import Session

from scripts.api.testdb_guard import (
    TestDatabaseManifest as DisposableDatabaseManifest,
)
from scripts.api.testdb_guard import validate_application_schema_metadata, validate_state_directory
from tests.integration.test_embedding_registry_persistence import _binding_source_ids, _seed
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.embedding_registry_application_fixtures import SyntheticVerifier, capture_pair
from tests.unit.inference_transfer_embedding_fixtures import index_pointer, seal
from tests.unit.inference_transfer_fixtures import NOW

pytestmark = pytest.mark.integration


def _artifact(session: Session, pointer: ArtifactMemberPointer, document: dict[str, Any]) -> None:
    """Canonical approved DB metadata only; this fixture never claims a real NAS commit."""
    assert pointer.sha256 == content_sha256(document)
    job_id = "job_" + uuid4().hex
    session.add(
        JobRecord(
            job_id=job_id,
            protocol_version="embedding-registry-test/1.0",
            idempotency_key="fixture:" + uuid4().hex,
            request_hash=content_sha256(document),
            task_type="synthetic-index-metadata",
            request={},
            status="SUCCEEDED",
            logical_artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
        )
    )
    session.flush()
    session.add(
        ArtifactRecord(
            logical_artifact_id=pointer.artifact_id,
            job_id=job_id,
            artifact_type="synthetic-index-metadata",
            approved=True,
        )
    )
    session.flush()
    session.add(
        ArtifactRevisionRecord(
            revision_id=pointer.artifact_revision_id,
            logical_artifact_id=pointer.artifact_id,
            job_id=job_id,
            content_hash=pointer.sha256,
            manifest_hash=content_sha256({"fixture": pointer.sha256}),
            content_bytes=len(canonical_json_bytes(document)),
            nas_path="synthetic:unmaterialized",
            manifest={
                "primary_file": pointer.member_path,
                "files": [
                    {
                        "file_name": pointer.member_path,
                        "sha256": pointer.sha256,
                        "schema_ref": pointer.schema_ref,
                        "media_type": pointer.media_type,
                        "bytes": len(canonical_json_bytes(document)),
                    }
                ],
            },
            result=document,
            approved=True,
        )
    )
    session.flush()


def _fixture(
    engine: Engine, *, view: ExperimentView = "METADATA_ONLY"
) -> tuple[RegisterEmbeddingIndexCommand, ResolvedEmbeddingRegistration]:
    command, original = capture_pair(view=view)
    with Session(engine) as session, session.begin():
        seed = _seed(session)
        item_id, item_revision, base_run, solution_run = _binding_source_ids(session, seed)
        item = session.get(ItemRecord, item_id)
        revision = session.get(ItemRevisionRecord, item_revision)
        graph = session.get(KnowledgeGraphSnapshotRecord, seed["snapshot"])
        assert item is not None and revision is not None and graph is not None
        item.lifecycle_state = "ACTIVE"
        revision.revision_state = "APPROVED"
        revision.approved_at = NOW
        revision.approved_by = "synthetic-test-owner"
        for run_id in (base_run, solution_run):
            run = session.get(KnowledgeAnalysisRunRecord, run_id)
            assert run is not None
            run.state = "ACCEPTED"
            run.accepted_result_artifact_id = seed["artifact"]
            run.accepted_result_artifact_revision_id = seed["artifact_revision"]
            run.accepted_result_sha256 = revision.manifest_sha256
        session.flush()
        entry_body = original.entries[0].model_dump(mode="json")
        basis = entry_body["profile"]["source_basis"]
        basis["source"].update(item_id=item_id, item_revision_id=item_revision)
        basis["source"]["artifact_member"].update(
            artifact_id=seed["artifact"], artifact_revision_id=seed["artifact_revision"]
        )
        basis["solution_evidence"].update(
            base_analysis_run_id=base_run, solution_analysis_run_id=solution_run
        )
        basis["solution_evidence"] = seal(basis["solution_evidence"], "pointer_sha256")
        basis["graph_snapshot"].update(
            graph_id=graph.graph_id, graph_snapshot_revision_id=graph.graph_snapshot_revision_id
        )
        entry_body["profile"].update(
            profile_id="inferenceprofile_" + uuid4().hex,
            profile_revision_id="inferenceprofilerev_" + uuid4().hex,
        )
        entry_body["profile"] = seal(entry_body["profile"], "profile_sha256")
        if entry_body["content"] is not None:
            entry_body["content"]["original_source"] = basis["source"]["artifact_member"]
        entry = StagedExperimentEntry.model_validate(entry_body)
        binding_body = original.index.bindings[0].model_dump(mode="json")
        binding_body.update(
            source=basis["source"],
            solution_evidence=basis["solution_evidence"],
            graph_snapshot=basis["graph_snapshot"],
            policy_revision_id=seed["policy"],
        )
        binding_body["profile"].update(
            profile_id=entry.profile.profile_id,
            profile_revision_id=entry.profile.profile_revision_id,
            profile_sha256=entry.profile.profile_sha256,
        )
        partition = "registry-test-" + uuid4().hex
        binding_body["encoding"]["storage_partition"] = partition
        binding_body["encoding"] = seal(binding_body["encoding"], "encoding_sha256")
        shard_body = original.shards[0][1].model_dump(mode="json")
        shard_body["rows"] = [binding_body["encoding"]]
        shard_body["input_set_sha256"] = content_sha256(shard_body["rows"])
        shard = EmbeddingVectorShardManifest.model_validate(seal(shard_body, "shard_sha256"))
        shard_pointer = ArtifactMemberPointer(
            artifact_id="artifact_" + uuid4().hex,
            artifact_revision_id="rev_" + uuid4().hex,
            member_path="shard.json",
            schema_ref="eom://schemas/knowledge/embedding-vector-shard/1.0",
            media_type="application/json",
            sha256=content_sha256(shard.model_dump(mode="json")),
        )
        binding_body["row_ref"].update(
            shard_manifest=shard_pointer.model_dump(mode="json"),
            encoding_sha256=binding_body["encoding"]["encoding_sha256"],
        )
        binding = EmbeddingSourceBinding.model_validate(seal(binding_body, "binding_sha256"))
        index_body = original.index.model_dump(mode="json")
        index_body.update(
            index_id="embeddingindex_" + uuid4().hex,
            index_revision_id="embeddingindexrev_" + uuid4().hex,
            storage_partition=partition,
            bindings=[binding.model_dump(mode="json")],
            shards=[shard_pointer.model_dump(mode="json")],
        )
        index = EmbeddingIndexManifest.model_validate(seal(index_body, "index_sha256"))
        pointer = ArtifactMemberPointer.model_validate(
            index_pointer(index).model_dump(mode="json")
            | {
                "artifact_id": "artifact_" + uuid4().hex,
                "artifact_revision_id": "rev_" + uuid4().hex,
            }
        )
        body = command.model_dump(mode="json")
        body.update(
            corpus_id=seed["corpus"],
            graph_snapshot=binding.graph_snapshot.model_dump(mode="json"),
            policy_revision_id=seed["policy"],
            index_id=index.index_id,
            index_revision_id=index.index_revision_id,
            index_manifest=pointer.model_dump(mode="json"),
            index_sha256=index.index_sha256,
            operation_key="fixture-registration:" + uuid4().hex,
            source_set_sha256=population_sha256((binding.source,)),
            binding_set_sha256=content_sha256([binding.binding_sha256]),
        )
        body["namespace"]["storage_partition"] = partition
        command = RegisterEmbeddingIndexCommand.model_validate(seal(body, "request_sha256"))
        _artifact(session, shard_pointer, shard.model_dump(mode="json"))
        _artifact(session, pointer, index.model_dump(mode="json"))
        resolved = ResolvedEmbeddingRegistration(
            command.corpus_id, index, ((shard_pointer, shard),), None, (binding.source,), (entry,)
        )
    return command, resolved


def _successor(
    engine: Engine, command: RegisterEmbeddingIndexCommand, capture: ResolvedEmbeddingRegistration
) -> tuple[RegisterEmbeddingIndexCommand, ResolvedEmbeddingRegistration]:
    body = capture.index.model_dump(mode="json")
    body.update(
        index_revision_id="embeddingindexrev_" + uuid4().hex,
        previous_manifest=command.index_manifest.model_dump(mode="json"),
    )
    index = EmbeddingIndexManifest.model_validate(seal(body, "index_sha256"))
    pointer = ArtifactMemberPointer.model_validate(
        index_pointer(index).model_dump(mode="json")
        | {"artifact_id": "artifact_" + uuid4().hex, "artifact_revision_id": "rev_" + uuid4().hex}
    )
    body = command.model_dump(mode="json")
    body.update(
        index_revision_id=index.index_revision_id,
        index_manifest=pointer.model_dump(mode="json"),
        index_sha256=index.index_sha256,
        expected_current_index_revision_id=command.index_revision_id,
        expected_lock_version=2,
        operation_key="fixture-registration:" + uuid4().hex,
    )
    successor = RegisterEmbeddingIndexCommand.model_validate(seal(body, "request_sha256"))
    with Session(engine) as session, session.begin():
        _artifact(session, pointer, index.model_dump(mode="json"))
    return successor, replace(
        capture, index=index, previous=(command.index_manifest, capture.index)
    )


class MetadataVerifier(SyntheticVerifier):
    """Synthetic metadata-checking test port, NOT the production official resolver."""

    def resolve_registration(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        command: RegisterEmbeddingIndexCommand,
    ) -> ResolvedEmbeddingRegistration:
        capture = super().resolve_registration(session, caller, command)
        for binding in capture.index.bindings:
            item = session.get(ItemRecord, binding.source.item_id)
            source = session.get(ItemRevisionRecord, binding.source.item_revision_id)
            assert item is not None and source is not None
            if item.lifecycle_state != "ACTIVE" or source.revision_state != "APPROVED":
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")
            for run_id in (
                binding.solution_evidence.base_analysis_run_id,
                binding.solution_evidence.solution_analysis_run_id,
            ):
                run = session.get(KnowledgeAnalysisRunRecord, run_id)
                if run is None or run.state != "ACCEPTED":
                    raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")
        for pointer, payload in ((command.index_manifest, capture.index), *capture.shards):
            artifact = session.get(ArtifactRecord, pointer.artifact_id)
            revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
            if (
                artifact is None
                or revision is None
                or not artifact.approved
                or not revision.approved
            ):
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_POINTER_INVALID")
            if (
                revision.logical_artifact_id != pointer.artifact_id
                or revision.result != payload.model_dump(mode="json")
            ):
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_POINTER_INVALID")
        return capture


CALLER = EmbeddingRegistryCaller("operator_" + "1" * 32)


def test_initial_query_capture_reads_actual_index_artifact_and_does_not_lock_current_head(
    guarded_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real SQL/file-set; initial source/IAM only are explicit synthetic seams."""
    from eom_catalog_contracts.embedding_reference_query import ReferenceQuerySpaces
    from eom_catalog_contracts.inference_transfer_experiment import VIEWS
    from eom_catalog_service.embedding_registry_catalog_adapter import (
        CatalogEmbeddingRegistryVerifier,
        EmbeddingRegistryOwnerConfiguration,
    )
    from eom_catalog_service.embedding_registry_ports import (
        ReferenceQueryContextPreparation,
        ResolvedEmbeddingLookup,
        SelectedEmbeddingSources,
    )
    from eom_catalog_service.settings import CatalogSettings
    from eom_orchestrator.embedding_artifact_store import (
        EmbeddingArtifactStore,
        EmbeddingIndexPublicationScope,
    )
    from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
    from eom_orchestrator.settings import Settings

    command, capture = _fixture(guarded_engine)
    settings = Settings(
        nas_artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspaces",
        staging_root=tmp_path / "staging",
    )
    settings.nas_artifact_root.mkdir(mode=0o700)
    settings.workspace_root.mkdir(mode=0o700)
    workspace = settings.workspace_root / "index"
    workspace.mkdir(mode=0o700)
    published = EmbeddingArtifactStore(
        ControlFileSetPublisher(guarded_engine, settings),
        source_commit="a" * 40,
    ).publish_index(
        index=capture.index,
        shards=capture.shards,
        previous=None,
        scope=EmbeddingIndexPublicationScope(
            command.graph_snapshot,
            command.policy_revision_id,
            command.policy_sha256,
        ),
        workspace=workspace,
    )
    command = RegisterEmbeddingIndexCommand.model_validate(
        seal(
            command.model_dump(mode="json")
            | {"index_manifest": published.index_manifest.model_dump(mode="json")},
            "request_sha256",
        )
    )
    with Session(guarded_engine) as session, session.begin():
        register_embedding_index(session, CALLER, command, SyntheticVerifier(capture), now=NOW)
    verifier = CatalogEmbeddingRegistryVerifier(
        guarded_engine,
        EmbeddingRegistryOwnerConfiguration(
            command.corpus_id,
            command.namespace,
            capture.index.space,
            capture.index.recipe,
            ("PAST_EXAM",),
        ),
        identity_fence=Mock(),
        settings=CatalogSettings(nas_artifact_root=settings.nas_artifact_root),
    )
    scope = EmbeddingRegistryLookup(
        command.corpus_id,
        command.namespace,
        command.graph_snapshot,
        command.policy_revision_id,
        command.policy_sha256,
    )
    chosen = SelectedEmbeddingSources(scope, (capture.sources[0].item_revision_id,))
    captures = 0

    def source(_session, caller, selection):
        nonlocal captures
        assert _session.get_transaction().is_active and not _session.in_nested_transaction()
        assert caller == CALLER and selection == chosen
        captures += 1
        if captures == 2:
            # The reader keeps its pinned revision, not a lock on the mutable head.
            with Session(guarded_engine) as writer, writer.begin():
                assert (
                    writer.scalar(
                        select(EmbeddingIndexRecord)
                        .where(
                            EmbeddingIndexRecord.index_id == command.index_id,
                        )
                        .with_for_update(nowait=True)
                    )
                    is not None
                )
        return ResolvedEmbeddingLookup(
            command.corpus_id,
            capture.index.space,
            capture.index.recipe,
            capture.sources,
            capture.entries,
        )

    monkeypatch.setattr(verifier, "resolve_selected_sources", source)
    query_space = type(capture.index.space).model_validate(
        seal(
            capture.index.space.model_dump(mode="json") | {"purpose": "QUERY"},
            "space_sha256",
        )
    )
    preparation = ReferenceQueryContextPreparation(
        "similarityrequest_" + uuid4().hex,
        chosen,
        ReferenceQuerySpaces(query=query_space, document=capture.index.space),
        VIEWS,
        "OPTIONAL",
        8,
    )
    statements = []

    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.upper())

    event.listen(guarded_engine, "before_cursor_execute", observe)
    try:
        with Session(guarded_engine) as session, session.begin():
            result = verifier.prepare_reference_query_context_in_session(
                session, CALLER, preparation
            )
    finally:
        event.remove(guarded_engine, "before_cursor_execute", observe)
    assert captures == 2 and result.anchor.source == capture.sources[0]
    indexes = tuple(row.index for row in result.views if row.index is not None)
    assert len(indexes) == 1 and indexes[0].index_manifest == published.index_manifest
    assert indexes[0].index_revision_id == command.index_revision_id
    assert not any(s.lstrip().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)
    # The only write-style lock belongs to the independent writer used above.
    assert sum("FOR UPDATE NOWAIT" in s for s in statements) == 1


def test_atomic_registration_historical_replay_and_stale_identity_map(
    guarded_engine: Engine,
) -> None:
    command, capture = _fixture(guarded_engine)
    owner = MetadataVerifier(capture)
    with Session(guarded_engine) as session, session.begin():
        first = register_embedding_index(session, CALLER, command, owner, now=NOW)
    successor, next_capture = _successor(guarded_engine, command, capture)
    owner.captures[next_capture.index.index_revision_id] = next_capture
    with Session(guarded_engine) as reader, reader.begin():
        cached = reader.get(EmbeddingIndexRecord, command.index_id)
        assert cached is not None and cached.lock_version == 2
        with Session(guarded_engine) as writer, writer.begin():
            register_embedding_index(
                writer, CALLER, successor, owner, now=NOW + timedelta(seconds=1)
            )
        assert cached.lock_version == 2
        replay = register_embedding_index(
            reader, CALLER, command, owner, now=NOW + timedelta(seconds=2)
        )
        assert replay.replayed and not replay.is_current and replay.current_lock_version == 3
        selected, version = EmbeddingRegistryRepository(reader).current_namespace_revision(
            command.corpus_id, command.namespace
        )
        assert selected.index_revision_id == successor.index_revision_id and version == 3
        assert selected.index_manifest == successor.index_manifest
        statements: list[str] = []

        def observe(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement.upper())

        event.listen(guarded_engine, "before_cursor_execute", observe)
        try:
            verified = verify_embedding_index_registration_observation(
                reader, CALLER, command, first, owner
            )
        finally:
            event.remove(guarded_engine, "before_cursor_execute", observe)
        assert verified == capture
        assert not any(s.lstrip().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)
        assert (
            reader.get(EmbeddingIndexRecord, command.index_id).current_index_revision_id
            == successor.index_revision_id
        )
        assert replay.registered_at == first.registered_at
        assert replay.current_index_revision_id == successor.index_revision_id
        assert cached.lock_version == 3
    with Session(guarded_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(EmbeddingIndexRevisionRecord)
                .where(EmbeddingIndexRevisionRecord.index_id == command.index_id)
            )
            == 2
        )
        binding = session.scalar(
            select(EmbeddingSourceBindingRecord).where(
                EmbeddingSourceBindingRecord.binding_sha256
                == capture.index.bindings[0].binding_sha256
            )
        )
        assert (
            binding is not None
            and binding.binding_manifest_artifact_revision_id
            == command.index_manifest.artifact_revision_id
        )


def test_actual_bounded_lookup_reads_bindings_then_encodings_once(guarded_engine: Engine) -> None:
    command, capture = _fixture(guarded_engine)
    owner = MetadataVerifier(capture)
    with Session(guarded_engine) as session, session.begin():
        register_embedding_index(session, CALLER, command, owner, now=NOW)
    statements = []

    def observe(
        _connection: Any, _cursor: Any, statement: str, _parameters: Any, _context: Any, _many: Any
    ) -> None:
        statements.append(statement)

    event.listen(guarded_engine, "before_cursor_execute", observe)
    try:
        with Session(guarded_engine) as session, session.begin():
            query = EmbeddingRegistryLookup(
                command.corpus_id,
                command.namespace,
                command.graph_snapshot,
                command.policy_revision_id,
                command.policy_sha256,
            )
            result = lookup_missing_embedding_bindings(session, CALLER, query, owner)
            assert not result.missing and len(result.reusable_rows) == 1
    finally:
        event.remove(guarded_engine, "before_cursor_execute", observe)
    assert len(statements) == 2
    assert "embedding_source_bindings" in statements[0] and " IN (" in statements[0]
    assert "embedding_encodings" in statements[1] and " IN (" in statements[1]
    assert not any(
        "metadata_json" in statement or "vectors" in statement for statement in statements
    )


@pytest.mark.parametrize("phase", ["bindings", "encodings"])
def test_actual_independent_writer_commit_keeps_discovery_coherent(
    guarded_engine, monkeypatch, phase
):
    from eom_catalog_service.embedding_registry_application import (
        prepare_missing_embedding_bindings,
    )

    command, capture = _fixture(guarded_engine)
    owner = MetadataVerifier(capture)
    query = EmbeddingRegistryLookup(
        command.corpus_id,
        command.namespace,
        command.graph_snapshot,
        command.policy_revision_id,
        command.policy_sha256,
    )
    from eom_catalog_service.embedding_registry_repository import EmbeddingRegistryRepository

    original = getattr(EmbeddingRegistryRepository, phase)
    committed = False

    def read_then_commit(repository, keys):
        nonlocal committed
        captured = original(repository, keys)
        if not committed:
            committed = True
            with Session(guarded_engine) as writer, writer.begin():
                register_embedding_index(writer, CALLER, command, owner, now=NOW)
        return captured

    monkeypatch.setattr(EmbeddingRegistryRepository, phase, read_then_commit)
    with Session(guarded_engine) as reader, reader.begin():
        first = prepare_missing_embedding_bindings(reader, CALLER, query, owner)
        assert len(first.observation.missing) == 1 and not first.bindings
        second = prepare_missing_embedding_bindings(reader, CALLER, query, owner)
        assert not second.observation.missing and len(second.bindings) == 1
        assert len(second.observation.reusable_rows) == 1


def test_service_actor_uses_same_real_registration_replay_and_missing_lookup(
    guarded_engine: Engine,
) -> None:
    """Actual Registry SQL, explicitly synthetic service IAM/source admission only."""
    command, capture = _fixture(guarded_engine)
    caller = EmbeddingRegistryServiceCaller(
        LocalIndexingServiceReference(
            service_id="localindexservice_" + uuid4().hex,
            service_revision_id="localindexservicerev_" + uuid4().hex,
            service_identity_sha256="sha256:" + "a" * 64,
        )
    )
    verifier = MetadataVerifier(capture)

    def check_selection(session, actual, _intent):
        assert session.in_transaction() and actual == caller
        assert not hasattr(actual, "operator_id")

    verifier.authorize_scope = Mock(side_effect=check_selection)
    with Session(guarded_engine) as session, session.begin():
        first = register_embedding_index(session, caller, command, verifier, now=NOW)
    with Session(guarded_engine) as session, session.begin():
        replay = register_embedding_index(session, caller, command, verifier, now=NOW)
        query = EmbeddingRegistryLookup(
            command.corpus_id,
            command.namespace,
            command.graph_snapshot,
            command.policy_revision_id,
            command.policy_sha256,
        )
        missing = lookup_missing_embedding_bindings(session, caller, query, verifier)
        assert not first.replayed and replay.replayed and replay.is_current
        assert first.registered_at == replay.registered_at
        assert not missing.missing and len(missing.reusable_rows) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(EmbeddingIndexRevisionRecord)
                .where(EmbeddingIndexRevisionRecord.index_id == command.index_id)
            )
            == 1
        )
    assert verifier.authorize_scope.call_count >= 3


def test_revoked_service_replay_fails_before_registry_sql(guarded_engine: Engine) -> None:
    """A denial from the trusted test port must precede metadata disclosure/mutation."""
    command, capture = _fixture(guarded_engine)
    verifier = MetadataVerifier(capture)
    caller = EmbeddingRegistryServiceCaller(
        LocalIndexingServiceReference(
            service_id="localindexservice_" + uuid4().hex,
            service_revision_id="localindexservicerev_" + uuid4().hex,
            service_identity_sha256="sha256:" + "b" * 64,
        )
    )
    verifier.authorize_scope = Mock()
    with Session(guarded_engine) as session, session.begin():
        register_embedding_index(session, caller, command, verifier, now=NOW)
    verifier.authorize_scope.side_effect = EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")
    statements = []

    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(guarded_engine, "before_cursor_execute", observe)
    try:
        with (
            Session(guarded_engine) as session,
            session.begin(),
            pytest.raises(EmbeddingRegistryError, match="FORBIDDEN"),
        ):
            register_embedding_index(session, caller, command, verifier, now=NOW)
    finally:
        event.remove(guarded_engine, "before_cursor_execute", observe)
    assert not statements


def test_actual_antijoin_has_exact_btree_index_path(guarded_engine: Engine) -> None:
    command, capture = _fixture(guarded_engine)
    with Session(guarded_engine) as session, session.begin():
        register_embedding_index(session, CALLER, command, MetadataVerifier(capture), now=NOW)
    binding = capture.index.bindings[0]
    key = EmbeddingBindingLookupKey(
        binding.source.item_revision_id,
        binding.graph_snapshot.graph_snapshot_revision_id,
        binding.policy_revision_id,
        binding.recipe.recipe_sha256,
        binding.view,
        binding.projection_version,
        binding.solution_evidence.base_analysis_run_id,
        binding.profile.profile_revision_id,
        binding.solution_evidence.solution_analysis_run_id,
        binding.encoding.encoding_sha256,
    )
    probe = Mock(spec=Session)
    probe.execute.return_value.all.return_value = []
    EmbeddingRegistryRepository(probe).missing_bindings((key,))
    statement = probe.execute.call_args.args[0]
    sql = str(
        statement.compile(dialect=guarded_engine.dialect, compile_kwargs={"literal_binds": True})
    )
    with guarded_engine.connect() as connection, connection.begin():
        # Tiny synthetic fixtures favor sequential scans. This verifies an exact
        # installed B-tree path, not the planner's production-scale default choice.
        connection.execute(text("SET LOCAL enable_seqscan=off"))
        plan = connection.scalar(text("EXPLAIN (FORMAT JSON) " + sql))
    assert plan is not None
    # A failure diagnostic must not emit exact source identities or parameter values.
    sanitized = []
    pending = [plan[0]["Plan"]]
    while pending:
        node = pending.pop()
        sanitized.append(
            {
                "node": node["Node Type"],
                "index": node.get("Index Name"),
                "relation": node.get("Relation Name"),
                "equalities": tuple(
                    name
                    for name in ASSOCIATION_COLUMNS
                    if any(
                        re.search(
                            rf'\b{name}\b"?(?:\s*\)|\s*::\s*[a-zA-Z_]\w*)*\s*=',
                            node.get(field, ""),
                        )
                        for field in ("Index Cond", "Filter", "Recheck Cond", "Join Filter")
                    )
                ),
                **{
                    field: tuple(
                        name
                        for name in ASSOCIATION_COLUMNS
                        if re.search(rf"\b{name}\b", node.get(field, ""))
                    )
                    for field in ("Index Cond", "Filter", "Recheck Cond", "Join Filter")
                },
            }
        )
        pending.extend(node.get("Plans", ()))
    # Print only this bounded safe projection; pytest truncates nested assert values.
    print("SANITIZED_INDEX_PLAN " + json.dumps(sanitized, separators=(",", ":")))
    assert not any(node["node"] == "Seq Scan" for node in sanitized), sanitized
    accesses = [
        node
        for node in sanitized
        if node["relation"] == "embedding_source_bindings" and node["index"] is not None
    ]
    assert len(accesses) == 1, sanitized
    access = accesses[0]
    # The observed tiny-fixture path indexes the encoding and applies the other
    # nine exact predicates as filters. Never claim composite-index usage.
    assert "encoding_sha256" in access["Index Cond"], sanitized
    assert set(access["equalities"]) == set(ASSOCIATION_COLUMNS), sanitized
    assert set(access["Index Cond"]) | set(access["Filter"]) | set(access["Recheck Cond"]) == set(
        ASSOCIATION_COLUMNS
    ), sanitized
    index_metadata = text(
        "SELECT method.amname,relation.relname,index_record.indisvalid,"
        "index_record.indisunique,ARRAY(SELECT pg_get_indexdef(index_record.indexrelid,n,true) "
        "FROM generate_series(1,index_record.indnkeyatts) AS n ORDER BY n) "
        "FROM pg_index index_record JOIN pg_class index_class "
        "ON index_class.oid=index_record.indexrelid JOIN pg_am method "
        "ON method.oid=index_class.relam JOIN pg_class relation "
        "ON relation.oid=index_record.indrelid JOIN pg_namespace namespace "
        "ON namespace.oid=relation.relnamespace WHERE namespace.nspname='app' "
        "AND relation.relname='embedding_source_bindings' AND index_class.relname=:index"
    )
    with guarded_engine.connect() as connection:
        method, relation, valid, _unique, columns = connection.execute(
            index_metadata, {"index": access["index"]}
        ).one()
        source_columns = {
            str(index.name): tuple(column.name for column in index.columns)
            for index in cast(Table, EmbeddingSourceBindingRecord.__table__).indexes
        }
        source_columns["uq_embedding_binding_association"] = ASSOCIATION_COLUMNS
        assert method == "btree" and relation == "embedding_source_bindings" and valid
        assert tuple(columns) == source_columns[access["index"]]
        assert columns[0] in access["Index Cond"], sanitized
        # Availability is distinct from the planner's chosen single-row path.
        method, relation, valid, unique, columns = connection.execute(
            index_metadata, {"index": "uq_embedding_binding_association"}
        ).one()
        assert method == "btree" and relation == "embedding_source_bindings" and valid and unique
        assert tuple(columns) == ASSOCIATION_COLUMNS


def test_failed_real_cas_savepoint_leaves_no_new_metadata(
    guarded_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    command, capture = _fixture(guarded_engine)

    def refuse_advance(_self: EmbeddingRegistryRepository, _command: Any, _now: Any) -> bool:
        return False

    monkeypatch.setattr(EmbeddingRegistryRepository, "advance", refuse_advance)
    with Session(guarded_engine) as session, session.begin():
        with pytest.raises(EmbeddingRegistryError, match="STALE_CURRENT"):
            register_embedding_index(session, CALLER, command, MetadataVerifier(capture), now=NOW)
        assert session.get(EmbeddingIndexRecord, command.index_id) is None
        assert session.get(EmbeddingIndexRevisionRecord, command.index_revision_id) is None
        assert (
            session.get(EmbeddingEncodingRecord, capture.index.bindings[0].encoding.encoding_sha256)
            is None
        )
        assert (
            session.get(EmbeddingSourceBindingRecord, capture.index.bindings[0].binding_sha256)
            is None
        )


def _guard_process_engine(engine: Engine, expected_database: str) -> None:
    """Repeat the existing disposable-state/owner/marker fence in each test process."""
    state = validate_state_directory(Path(os.environ["EOM_API_TEST_STATE"]))
    manifest = DisposableDatabaseManifest.load(state / "manifest.json")
    assert engine.url.database == expected_database == manifest.database
    assert engine.url.username == manifest.owner_role
    with engine.connect() as connection:
        owner, marker = connection.execute(
            text(
                "SELECT owner.rolname, obj_description(namespace.oid, 'pg_namespace') "
                "FROM pg_namespace namespace JOIN pg_roles owner ON owner.oid=namespace.nspowner "
                "WHERE namespace.nspname='app'"
            )
        ).one()
        path, usage, create = connection.execute(
            text(
                "SELECT current_schemas(false),has_schema_privilege(current_user,'app','USAGE'),"
                "has_schema_privilege(current_user,'app','CREATE')"
            )
        ).one()
        validate_application_schema_metadata(
            manifest,
            schema_owner=owner,
            schema_comment=marker,
            effective_search_path=tuple(path),
            has_usage=usage,
            has_create=create,
        )
        assert (
            connection.scalar(text("SELECT version_num FROM app.alembic_version"))
            == CURRENT_MIGRATION_REVISION
        )


def _process_register(
    command: RegisterEmbeddingIndexCommand,
    capture: ResolvedEmbeddingRegistration,
    expected_database: str,
    queue: Any,
    start: Any,
) -> None:
    engine = build_engine(os.environ["EOM_DATABASE_URL"])
    try:
        _guard_process_engine(engine, expected_database)
        queue.put(("READY", os.getpid()))
        assert start.wait(30)
        with Session(engine) as session, session.begin():
            result = register_embedding_index(
                session, CALLER, command, MetadataVerifier(capture), now=NOW
            )
        queue.put(("OK", result.replayed, result.current_lock_version))
    except EmbeddingRegistryError as error:
        queue.put(("ERROR", error.code))
    finally:
        engine.dispose()


def test_independent_process_same_key_creation_is_one_revision(guarded_engine: Engine) -> None:
    command, capture = _fixture(guarded_engine)
    context = multiprocessing.get_context("spawn")
    queue, start = context.Queue(), context.Event()
    processes = [
        context.Process(
            target=_process_register,
            args=(command, capture, guarded_engine.url.database, queue, start),
        )
        for _ in range(2)
    ]
    try:
        for process in processes:
            process.start()
        ready = [queue.get(timeout=30) for _ in processes]
        assert all(value[0] == "READY" for value in ready)
        assert len({value[1] for value in ready}) == 2
        start.set()
        results = [queue.get(timeout=30) for _ in processes]
        assert sorted(results) == [("OK", False, 2), ("OK", True, 2)]
        for process in processes:
            process.join(timeout=30)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        queue.close()
    with Session(guarded_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(EmbeddingIndexRevisionRecord)
                .where(EmbeddingIndexRevisionRecord.index_id == command.index_id)
            )
            == 1
        )


def test_independent_process_competing_cas_advances_exactly_once(guarded_engine: Engine) -> None:
    command, capture = _fixture(guarded_engine)
    with Session(guarded_engine) as session, session.begin():
        register_embedding_index(session, CALLER, command, MetadataVerifier(capture), now=NOW)
    first, first_capture = _successor(guarded_engine, command, capture)
    second, second_capture = _successor(guarded_engine, command, capture)
    context = multiprocessing.get_context("spawn")
    queue, start = context.Queue(), context.Event()
    processes = [
        context.Process(
            target=_process_register,
            args=(candidate, resolved, guarded_engine.url.database, queue, start),
        )
        for candidate, resolved in ((first, first_capture), (second, second_capture))
    ]
    try:
        for process in processes:
            process.start()
        ready = [queue.get(timeout=30) for _ in processes]
        assert all(value[0] == "READY" for value in ready)
        assert len({value[1] for value in ready}) == 2
        start.set()
        results = [queue.get(timeout=30) for _ in processes]
        assert sorted(results) == [("ERROR", "EMBEDDING_INDEX_STALE_CURRENT"), ("OK", False, 3)]
        for process in processes:
            process.join(timeout=30)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        queue.close()
    with Session(guarded_engine) as session:
        head = session.get(EmbeddingIndexRecord, command.index_id)
        assert head is not None and head.lock_version == 3
        assert head.current_index_revision_id in {first.index_revision_id, second.index_revision_id}
        assert (
            session.scalar(
                select(func.count())
                .select_from(EmbeddingIndexRevisionRecord)
                .where(EmbeddingIndexRevisionRecord.index_id == command.index_id)
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(EmbeddingEncodingRecord)
                .where(
                    EmbeddingEncodingRecord.storage_partition == command.namespace.storage_partition
                )
            )
            == 1
        )
