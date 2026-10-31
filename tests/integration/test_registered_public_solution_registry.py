"""Opt-in disposable PostgreSQL transactions; synthetic authority, no model/NAS.

Actual FK/unique constraints, index head CAS, immutable origins and rollback are
exercised. Source/report permission and bytes remain a separate owner acceptance.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from eom_catalog_contracts.inference_transfer_experiment import population_sha256
from eom_catalog_contracts.registered_public_solution_embedding import (
    RegisteredPublicSolutionEmbeddingEntry,
)
from eom_catalog_contracts.registered_public_solution_index import PublicSolutionEmbeddingIndexV4
from eom_catalog_contracts.registered_public_solution_registry import (
    RegisterPublicSolutionIndexCommandV4,
)
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_registry_application import (
    register_embedding_index,
    verify_embedding_index_registration_observation,
)
from eom_catalog_service.embedding_registry_models import (
    EmbeddingEncodingRecord,
    EmbeddingIndexRecord,
    EmbeddingIndexRevisionRecord,
    EmbeddingSourceBindingRecord,
)
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryError
from eom_catalog_service.public_solution_encoding import prepare_public_solution_encoding
from eom_catalog_service.public_solution_index_assembly import assemble_public_solution_binding
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_embedding_registry_application import _artifact
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_public_solution_embedding_registry import CALLER, public_fixture
from tests.unit.embedding_registry_application_fixtures import SyntheticVerifier
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_registered_public_solution_embedding import registered_entry
from tests.unit.test_registered_public_solution_migration import registered_public_migration

pytestmark = pytest.mark.integration


def registered_fixture(engine):
    old, capture = public_fixture(engine)
    original = capture.entries[0]
    body = registered_entry().model_dump(mode="json")
    source = original.source.model_dump(mode="json")
    source["source_class"] = "APPROVED_ITEM"
    body.update(
        source=source,
        base_analysis_run_id=original.base_analysis_run_id,
        graph_snapshot=original.graph_snapshot.model_dump(mode="json"),
        policy_revision_id=original.policy_revision_id,
        policy_sha256=original.policy_sha256,
        recipe=original.recipe.model_dump(mode="json"),
        public_solution=original.public_solution.model_dump(mode="json"),
    )
    proof = body["evidence"]["solution"]
    proof.update(
        base_analysis_run_id=original.base_analysis_run_id,
        solution_analysis_run_id=original.evidence.solution.solution_analysis_run_id,
    )
    proof["pointer_sha256"] = seal(proof, "pointer_sha256")["pointer_sha256"]
    entry = RegisteredPublicSolutionEmbeddingEntry.model_validate(seal(body, "entry_sha256"))
    parent_binding = capture.index.bindings[0]
    encoded = prepare_public_solution_encoding(
        entry, space=capture.index.space, storage_partition=old.namespace.storage_partition
    )
    assert encoded.input.encoding == parent_binding.encoding
    binding = assemble_public_solution_binding(
        entry,
        row=RegisteredEmbeddingRow(parent_binding.encoding, parent_binding.row_ref),
        space=capture.index.space,
        namespace=old.namespace,
    )
    body = capture.index.model_dump(mode="json")
    body.update(
        schema_version="embedding-index-manifest/4.0",
        index_revision_id="embeddingindexrev_" + uuid4().hex,
        previous_manifest=old.index_manifest.model_dump(mode="json"),
        bindings=[binding.model_dump(mode="json")],
    )
    index = PublicSolutionEmbeddingIndexV4.model_validate(seal(body, "index_sha256"))
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + uuid4().hex,
        artifact_revision_id="rev_" + uuid4().hex,
        member_path="index.json",
        schema_ref="eom://schemas/knowledge/embedding-index-manifest/4.0",
        media_type="application/json",
        sha256=content_sha256(index.model_dump(mode="json")),
    )
    body = old.model_dump(mode="json")
    body.update(
        schema_version="embedding-registry-registration-command/4.0",
        index_revision_id=index.index_revision_id,
        index_manifest=pointer.model_dump(mode="json"),
        index_sha256=index.index_sha256,
        expected_current_index_revision_id=old.index_revision_id,
        expected_lock_version=2,
        operation_key="registered-public:" + uuid4().hex,
        source_set_sha256=population_sha256((entry.source,)),
        binding_set_sha256=content_sha256([binding.binding_sha256]),
    )
    command = RegisterPublicSolutionIndexCommandV4.model_validate(seal(body, "request_sha256"))
    with Session(engine) as session, session.begin():
        _artifact(session, pointer, index.model_dump(mode="json"))
    return (old, capture), (
        command,
        replace(
            capture,
            index=index,
            previous=(old.index_manifest, capture.index),
            entries=(entry,),
            sources=(entry.source,),
        ),
    )


def test_index3_to4_reuses_numeric_row_and_replay_never_rewinds_current_head(guarded_engine):
    (old, before), (command, after) = registered_fixture(guarded_engine)
    owner = SyntheticVerifier(before, after)
    with Session(guarded_engine) as session, session.begin():
        register_embedding_index(session, CALLER, old, owner, now=NOW)
    with Session(guarded_engine) as session, session.begin():
        receipt = register_embedding_index(session, CALLER, command, owner, now=NOW)
        assert (
            verify_embedding_index_registration_observation(
                session, CALLER, command, receipt, owner
            )
            == after
        )
    with Session(guarded_engine) as session, session.begin():
        replay = register_embedding_index(session, CALLER, command, owner, now=NOW)
        previous = register_embedding_index(session, CALLER, old, owner, now=NOW)
        assert replay.replayed and replay.is_current
        assert previous.replayed and not previous.is_current
        assert previous.current_index_revision_id == command.index_revision_id
        assert session.get(EmbeddingIndexRecord, command.index_id).lock_version == 3
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
        for expected, captured in ((old, before), (command, after)):
            row = session.get(
                EmbeddingSourceBindingRecord, captured.index.bindings[0].binding_sha256
            )
            assert (
                row.binding_manifest_artifact_revision_id
                == expected.index_manifest.artifact_revision_id
            )
            assert row.binding_manifest_schema_ref == expected.index_manifest.schema_ref
            assert row.review_job_id is None and row.review_evidence_sha256 is None


def test_concurrent_successor_has_one_revision_and_one_replay(guarded_engine):
    (old, before), (command, after) = registered_fixture(guarded_engine)
    with Session(guarded_engine) as session, session.begin():
        register_embedding_index(session, CALLER, old, SyntheticVerifier(before), now=NOW)
    start = Barrier(2)

    def submit():
        with Session(guarded_engine) as session, session.begin():
            start.wait(timeout=15)
            return register_embedding_index(
                session, CALLER, command, SyntheticVerifier(before, after), now=NOW
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [
            future.result(timeout=30) for future in [executor.submit(submit) for _ in range(2)]
        ]
    assert sorted(value.replayed for value in outcomes) == [False, True]
    with Session(guarded_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(EmbeddingIndexRevisionRecord)
                .where(EmbeddingIndexRevisionRecord.index_id == command.index_id)
            )
            == 2
        )


def test_interrupted_successor_rolls_back_then_same_command_recovers(guarded_engine):
    (old, before), (command, after) = registered_fixture(guarded_engine)
    owner = SyntheticVerifier(before, after)
    with Session(guarded_engine) as session, session.begin():
        register_embedding_index(session, CALLER, old, owner, now=NOW)
    with (
        pytest.raises(RuntimeError, match="interrupted"),
        Session(guarded_engine) as session,
        session.begin(),
    ):
        register_embedding_index(session, CALLER, command, owner, now=NOW)
        raise RuntimeError("interrupted")
    with Session(guarded_engine) as session, session.begin():
        assert session.get(EmbeddingIndexRevisionRecord, command.index_revision_id) is None
        assert (
            session.get(EmbeddingSourceBindingRecord, after.index.bindings[0].binding_sha256)
            is None
        )
        assert (
            session.get(EmbeddingIndexRecord, command.index_id).current_index_revision_id
            == old.index_revision_id
        )
        assert not register_embedding_index(session, CALLER, command, owner, now=NOW).replayed


def test_stale_compare_and_swap_cannot_replace_current_revision(guarded_engine):
    (old, before), (command, after) = registered_fixture(guarded_engine)
    owner = SyntheticVerifier(before, after)
    with Session(guarded_engine) as session, session.begin():
        register_embedding_index(session, CALLER, old, owner, now=NOW)
    body = command.model_dump(mode="json") | {"expected_lock_version": 3}
    stale = RegisterPublicSolutionIndexCommandV4.model_validate(seal(body, "request_sha256"))
    with Session(guarded_engine) as session, session.begin():
        with pytest.raises(EmbeddingRegistryError, match="STALE_CURRENT"):
            register_embedding_index(session, CALLER, stale, owner, now=NOW)
        assert (
            session.get(EmbeddingIndexRecord, command.index_id).current_index_revision_id
            == old.index_revision_id
        )
        assert (
            session.get(EmbeddingSourceBindingRecord, after.index.bindings[0].binding_sha256)
            is None
        )


def test_downgrade_refuses_successor_history_without_deleting_it(guarded_engine, monkeypatch):
    (old, before), (command, after) = registered_fixture(guarded_engine)
    with Session(guarded_engine) as session, session.begin():
        owner = SyntheticVerifier(before, after)
        register_embedding_index(session, CALLER, old, owner, now=NOW)
        register_embedding_index(session, CALLER, command, owner, now=NOW)
    module = registered_public_migration()
    with guarded_engine.connect() as connection, connection.begin():
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        with pytest.raises(DBAPIError, match="absent successor history"), connection.begin_nested():
            module.downgrade()
    with Session(guarded_engine) as session:
        assert session.get(EmbeddingIndexRevisionRecord, command.index_revision_id) is not None
