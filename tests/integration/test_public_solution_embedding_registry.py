"""Disposable PostgreSQL metadata transactions, not live report/Graph admission.

Synthetic source captures are explicit test ports. Real constraints, transaction
rollback, CAS and replay are exercised; no encoder, worker, NAS or live DB is used.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingVectorRowRef
from eom_catalog_contracts.inference_transfer_experiment import population_sha256
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_contracts.public_solution_embedding_registry import (
    RegisterPublicSolutionIndexCommand,
)
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_registry_application import register_embedding_index
from eom_catalog_service.embedding_registry_models import (
    EmbeddingEncodingRecord,
    EmbeddingIndexRecord,
    EmbeddingIndexRevisionRecord,
    EmbeddingSourceBindingRecord,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    ResolvedEmbeddingRegistration,
)
from eom_catalog_service.embedding_registry_repository import EmbeddingRegistryRepository
from eom_catalog_service.embedding_source_associations import embedding_binding_lookup_key
from eom_catalog_service.public_solution_encoding import prepare_public_solution_encoding
from eom_catalog_service.public_solution_index_assembly import assemble_public_solution_index
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_embedding_registry_application import _artifact, _fixture
from tests.integration.test_embedding_registry_persistence import (
    registry_session as registry_session,
)
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.embedding_registry_application_fixtures import SyntheticVerifier
from tests.unit.inference_transfer_embedding_fixtures import seal, vector_shard
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_public_solution_encoding import public_entry

pytestmark = pytest.mark.integration
CALLER = EmbeddingRegistryCaller("operator_" + "1" * 32)


def public_fixture(engine, *, creative=False):
    old, captured = _fixture(engine)
    base = captured.entries[0].profile.source_basis
    body = public_entry(creative=creative).model_dump(mode="json")
    source = base.source.model_dump(mode="json")
    if creative:
        source["source_class"] = "APPROVED_ITEM"
    body.update(
        source=source,
        base_analysis_run_id=base.solution_evidence.base_analysis_run_id,
        graph_snapshot=old.graph_snapshot.model_dump(mode="json"),
        policy_revision_id=old.policy_revision_id,
        policy_sha256=old.policy_sha256,
    )
    if not creative:
        body["evidence"]["solution"] = base.solution_evidence.model_dump(mode="json")
    entry = PublicSolutionEmbeddingEntry.model_validate(seal(body, "entry_sha256"))
    namespace = PublicSolutionIndexNamespace(
        storage_partition="public-test-" + uuid4().hex,
        space_sha256=captured.index.space.space_sha256,
        recipe_sha256=entry.recipe.recipe_sha256,
    )
    encoding = prepare_public_solution_encoding(
        entry, space=captured.index.space, storage_partition=namespace.storage_partition
    ).input.encoding
    shard = vector_shard((encoding,), space=captured.index.space)
    shard_pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + uuid4().hex,
        artifact_revision_id="rev_" + uuid4().hex,
        member_path="shard.json",
        schema_ref="eom://schemas/knowledge/embedding-vector-shard/1.0",
        media_type="application/json",
        sha256=content_sha256(shard.model_dump(mode="json")),
    )
    rows = (
        RegisteredEmbeddingRow(
            encoding,
            EmbeddingVectorRowRef(
                shard_manifest=shard_pointer, row_index=0, encoding_sha256=encoding.encoding_sha256
            ),
        ),
    )
    assembled = assemble_public_solution_index(
        (entry,),
        available_rows=rows,
        shards=((shard_pointer, shard),),
        namespace=namespace,
        space=captured.index.space,
        index_id="embeddingindex_" + uuid4().hex,
        index_revision_id="embeddingindexrev_" + uuid4().hex,
        previous_manifest=None,
        created_at=NOW,
    )
    index = assembled.index
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + uuid4().hex,
        artifact_revision_id="rev_" + uuid4().hex,
        member_path="index.json",
        schema_ref="eom://schemas/knowledge/embedding-index-manifest/3.0",
        media_type="application/json",
        sha256=content_sha256(index.model_dump(mode="json")),
    )
    command = RegisterPublicSolutionIndexCommand.model_validate(
        seal(
            old.model_dump(mode="json")
            | {
                "schema_version": "embedding-registry-registration-command/3.0",
                "namespace": namespace.model_dump(mode="json"),
                "index_id": index.index_id,
                "index_revision_id": index.index_revision_id,
                "index_manifest": pointer.model_dump(mode="json"),
                "index_sha256": index.index_sha256,
                "source_set_sha256": population_sha256((entry.source,)),
                "binding_set_sha256": content_sha256(
                    [binding.binding_sha256 for binding in index.bindings]
                ),
            },
            "request_sha256",
        )
    )
    with Session(engine) as session, session.begin():
        _artifact(session, shard_pointer, shard.model_dump(mode="json"))
        _artifact(session, pointer, index.model_dump(mode="json"))
    return command, ResolvedEmbeddingRegistration(
        command.corpus_id,
        index,
        assembled.shards,
        None,
        (entry.source,),
        (entry,),
        base_analysis_run_ids=((entry.source.item_revision_id, entry.base_analysis_run_id),),
    )


@pytest.mark.parametrize("creative", (False, True))
def test_registration_replay_scalar_provenance_and_indexed_antijoin(guarded_engine, creative):
    command, capture = public_fixture(guarded_engine, creative=creative)
    owner = SyntheticVerifier(capture)
    with Session(guarded_engine) as session, session.begin():
        first = register_embedding_index(session, CALLER, command, owner, now=NOW)
    with Session(guarded_engine) as session, session.begin():
        replay = register_embedding_index(session, CALLER, command, owner, now=NOW)
        assert not first.replayed and replay.replayed and replay.current_lock_version == 2
        repository = EmbeddingRegistryRepository(session)
        selected, version = repository.current_namespace_revision(
            command.corpus_id, command.namespace
        )
        assert selected.namespace == command.namespace and version == 2
        binding = capture.index.bindings[0]
        key = embedding_binding_lookup_key(binding)
        assert not repository.missing_bindings((key,))
        assert repository.missing_bindings(
            (replace(key, solution_pointer_sha256="sha256:" + "f" * 64),)
        )
        row = repository.bindings((key,))[binding.binding_sha256]
        assert row.review_job_id is None and row.review_evidence_sha256 is None
        assert (row.solution_analysis_run_id is None) == creative
        assert row.evidence_kind == "PUBLIC_SOLUTION_REPORT"
        assert row.solution_pointer_sha256 == content_sha256(
            binding.evidence.model_dump(mode="json")
        )


def test_interrupted_registration_rolls_back_and_same_identity_recovers(guarded_engine):
    command, capture = public_fixture(guarded_engine, creative=True)
    owner = SyntheticVerifier(capture)
    with (
        pytest.raises(RuntimeError, match="synthetic interruption"),
        Session(guarded_engine) as session,
        session.begin(),
    ):
        register_embedding_index(session, CALLER, command, owner, now=NOW)
        raise RuntimeError("synthetic interruption")
    with Session(guarded_engine) as session, session.begin():
        assert session.get(EmbeddingIndexRecord, command.index_id) is None
        assert session.get(EmbeddingIndexRevisionRecord, command.index_revision_id) is None
        assert (
            session.get(EmbeddingEncodingRecord, capture.index.bindings[0].encoding.encoding_sha256)
            is None
        )
        assert not register_embedding_index(session, CALLER, command, owner, now=NOW).replayed


def test_concurrent_same_operation_commits_one_revision(guarded_engine):
    command, capture = public_fixture(guarded_engine, creative=True)
    start = Barrier(2)

    def submit():
        with Session(guarded_engine) as session, session.begin():
            start.wait(timeout=15)
            return register_embedding_index(
                session, CALLER, command, SyntheticVerifier(capture), now=NOW
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit) for _ in range(2)]
        outcomes = [future.result(timeout=30) for future in futures]
    assert sorted(value.replayed for value in outcomes) == [False, True]
    with Session(guarded_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(EmbeddingIndexRevisionRecord)
                .where(EmbeddingIndexRevisionRecord.index_id == command.index_id)
            )
            == 1
        )


def test_public_association_has_real_partial_unique_btree(guarded_engine):
    with guarded_engine.connect() as connection:
        rows = dict(
            connection.execute(
                text(
                    "SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='app' "
                    "AND indexname IN ('uq_embedding_binding_public_solution',"
                    "'ix_embedding_binding_public_solution_delta')"
                )
            ).all()
        )
    assert len(rows) == 2
    assert "UNIQUE INDEX" in rows["uq_embedding_binding_public_solution"]
    assert all(
        "USING btree" in value and "PUBLIC_SOLUTION_REPORT" in value for value in rows.values()
    )
    command, capture = public_fixture(guarded_engine, creative=True)
    with Session(guarded_engine) as session, session.begin():
        register_embedding_index(session, CALLER, command, SyntheticVerifier(capture), now=NOW)
        row = session.get(EmbeddingSourceBindingRecord, capture.index.bindings[0].binding_sha256)
        body = {
            column.name: getattr(row, column.name)
            for column in EmbeddingSourceBindingRecord.__table__.columns
        }
        body["binding_sha256"] = "sha256:" + uuid4().hex * 2
        with pytest.raises(DBAPIError) as failed, session.begin_nested():
            session.add(EmbeddingSourceBindingRecord(**body))
            session.flush()
        assert failed.value.orig.diag.constraint_name == "uq_embedding_binding_public_solution"
