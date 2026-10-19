"""Opt-in marker-guarded disposable PostgreSQL metadata tests, never production.

Synthetic Graph/policy rows below test relational constraints only; they do not
claim source admission, report acceptance, a registry service or usable retrieval.
All registry and source metadata is rolled back, not deleted from immutable history.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Event
from typing import Any, cast
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSourceBinding
from eom_catalog_service.embedding_registry_models import (
    EmbeddingEncodingRecord,
    EmbeddingIndexRecord,
    EmbeddingIndexRevisionRecord,
    EmbeddingSourceBindingRecord,
)
from eom_catalog_service.embedding_registry_ports import RegisteredReviewEmbeddingBindingLookupKey
from eom_catalog_service.embedding_registry_repository import (
    REGISTERED_REVIEW_ASSOCIATION_COLUMNS,
    EmbeddingRegistryRepository,
    binding_columns,
    binding_origin,
)
from eom_catalog_service.knowledge_graph_models import (
    EducationRetrievalAccessPolicyRevisionRecord,
    KnowledgeCorpusRecord,
    KnowledgeCorpusRevisionRecord,
    KnowledgeGraphSnapshotRecord,
)
from eom_catalog_service.models import (
    ContentPackRecord,
    ContentPackReleaseRecord,
    ItemRecord,
    ItemRevisionRecord,
)
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.knowledge_analysis_models import (
    KnowledgeAnalysisRiskPolicyRevisionRecord,
    KnowledgeAnalysisRunRecord,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_orchestrator.repository import ensure_protocol_version
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow_runner.models import WorkflowStepRunRecord
from sqlalchemy import Engine, delete, event, func, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from tests.integration.test_control_plane_persistence import _complete_control_plane, _workflow
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal, source_binding
from tests.unit.inference_transfer_fixtures import NOW, sha
from tests.unit.test_embedding_registry_models import migration_module
from tests.unit.test_registered_review_embedding_migration import registered_review_migration

pytestmark = pytest.mark.integration


@pytest.fixture
def registry_session(guarded_engine: Engine) -> Iterator[Session]:
    with guarded_engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, expire_on_commit=False) as session:
            yield session
        if transaction.is_active:
            transaction.rollback()


def _seed(session: Session) -> dict[str, Any]:
    """One synthetic relational hierarchy, no worker/model/source bytes or credentials."""
    seed = uuid4().hex
    actor = "operator_" + seed
    corpus, corpus_revision, graph = "corpus_" + seed, "corpusrev_" + seed, "graph_" + seed
    snapshot, policy = "graphrev_" + seed, "accessrev_" + seed
    job, artifact, artifact_revision = "job_" + seed, "artifact_" + seed, "rev_" + seed
    session.add(
        OperatorRecord(
            operator_id=actor,
            username="embedding-" + seed,
            normalized_username="embedding-" + seed,
            display_name="Synthetic relational fixture",
            status="ACTIVE",
            must_change_password=True,
            role_version=1,
            created_by="test",
        )
    )
    protocol = "embedding-registry-test/1.0"
    ensure_protocol_version(session, protocol, sha())
    # No ORM relationship orders this protocol insert before the unrelated Job row.
    session.flush()
    session.add(
        JobRecord(
            job_id=job,
            protocol_version=protocol,
            idempotency_key="fixture:" + seed,
            request_hash=sha(),
            task_type="synthetic-registry-fixture",
            request={},
            status="SUCCEEDED",
            logical_artifact_id=artifact,
            revision_id=artifact_revision,
        )
    )
    session.flush()
    session.add(
        ArtifactRecord(
            logical_artifact_id=artifact,
            job_id=job,
            artifact_type="synthetic-registry-fixture",
            approved=True,
        )
    )
    session.flush()
    session.add(
        ArtifactRevisionRecord(
            revision_id=artifact_revision,
            logical_artifact_id=artifact,
            job_id=job,
            content_hash=sha(),
            manifest_hash=sha(),
            content_bytes=2,
            nas_path="synthetic:unmaterialized",
            manifest={},
            result={},
            approved=True,
        )
    )
    session.add(
        KnowledgeCorpusRecord(
            corpus_id=corpus,
            corpus_key="fixture-" + seed,
            display_name="Synthetic registry",
            graph_id=graph,
            lifecycle_state="ACTIVE",
            lock_version=1,
            created_by_operator_id=actor,
        )
    )
    session.add(
        EducationRetrievalAccessPolicyRevisionRecord(
            access_policy_revision_id=policy,
            schema_version="education-retrieval-access-policy/1.0",
            state="RELEASED",
            content_sha256="sha256:" + seed * 2,
            canonical_document={},
            created_by="test",
            created_at=NOW,
        )
    )
    session.flush()
    session.add(
        KnowledgeCorpusRevisionRecord(
            corpus_revision_id=corpus_revision,
            corpus_id=corpus,
            revision_number=1,
            source_set_sha256=sha(),
            state="PUBLISHED",
            created_by_operator_id=actor,
            created_at=NOW,
        )
    )
    session.flush()
    session.add(
        KnowledgeGraphSnapshotRecord(
            graph_snapshot_revision_id=snapshot,
            graph_id=graph,
            corpus_revision_id=corpus_revision,
            revision_number=1,
            state="PUBLISHED",
            ontology_version="synthetic",
            publisher_version="test",
            manifest_artifact_id=artifact,
            manifest_artifact_revision_id=artifact_revision,
            projection_artifact_id=artifact,
            projection_artifact_revision_id=artifact_revision,
            manifest_sha256="sha256:" + uuid4().hex * 2,
            snapshot_sha256=sha(),
            source_count=1,
            node_count=1,
            edge_count=0,
            anchor_count=1,
            created_by_operator_id=actor,
            created_at=NOW,
        )
    )
    session.flush()
    return {
        "actor": actor,
        "job": job,
        "corpus": corpus,
        "snapshot": snapshot,
        "policy": policy,
        "artifact": artifact,
        "artifact_revision": artifact_revision,
    }


def _head(session: Session, seed: dict[str, Any]) -> EmbeddingIndexRecord:
    row = EmbeddingIndexRecord(
        index_id="embeddingindex_" + uuid4().hex,
        corpus_id=seed["corpus"],
        storage_partition="synthetic-" + uuid4().hex,
        space_sha256=sha(),
        view="METADATA_ONLY",
        recipe_sha256=sha(),
        projection_version="accepted-solution-comparison/1.0",
        population_scope="ALL_ADMITTED_GRAPH_ITEMS",
        current_index_revision_id=None,
        lock_version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(row)
    session.flush()
    return row


def _revision(
    session: Session,
    seed: dict[str, Any],
    head: EmbeddingIndexRecord,
    *,
    manifest_schema_ref: str = "eom://schemas/knowledge/embedding-index-manifest/1.0",
) -> EmbeddingIndexRevisionRecord:
    row = EmbeddingIndexRevisionRecord(
        index_revision_id="embeddingindexrev_" + uuid4().hex,
        index_id=head.index_id,
        revision_number=1,
        previous_index_revision_id=None,
        graph_snapshot_revision_id=seed["snapshot"],
        policy_revision_id=seed["policy"],
        policy_sha256=sha(),
        manifest_artifact_id=seed["artifact"],
        manifest_artifact_revision_id=seed["artifact_revision"],
        manifest_member_path="index.json",
        manifest_schema_ref=manifest_schema_ref,
        manifest_media_type="application/json",
        manifest_sha256=sha(),
        index_sha256=sha(),
        source_set_sha256=sha(),
        binding_set_sha256=sha(),
        eligible_source_count=1,
        binding_count=1,
        operation_key="registry-fixture:" + uuid4().hex,
        registration_request_sha256=sha(),
        created_at=NOW,
    )
    session.add(row)
    session.flush()
    return row


def test_exact_new_tables_guards_and_composite_fks_installed(guarded_engine: Engine) -> None:
    with guarded_engine.connect() as connection:
        for table in (
            EmbeddingEncodingRecord,
            EmbeddingSourceBindingRecord,
            EmbeddingIndexRecord,
            EmbeddingIndexRevisionRecord,
        ):
            assert (
                connection.scalar(
                    text("SELECT to_regclass(:name)"), {"name": "app." + table.__tablename__}
                )
                is not None
            )
        triggers = set(
            connection.scalars(
                text(
                    "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND "
                    "tgrelid IN ('app.embedding_encodings'::regclass,"
                    "'app.embedding_source_bindings'::regclass,'app.embedding_indexes'::regclass,"
                    "'app.embedding_index_revisions'::regclass)"
                )
            )
        )
        assert triggers == {
            "embedding_encodings_immutable",
            "embedding_source_bindings_immutable",
            "embedding_index_revisions_immutable",
            "embedding_indexes_identity_immutable",
        }


def test_head_cas_wrong_index_dangling_and_identity_guard(registry_session: Session) -> None:
    session = registry_session
    seed = _seed(session)
    head, other = _head(session, seed), _head(session, seed)
    revision = _revision(session, seed, head)
    for changed in ("embeddingindexrev_" + uuid4().hex, revision.index_revision_id):
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(
                update(EmbeddingIndexRecord)
                .where(EmbeddingIndexRecord.index_id == other.index_id)
                .values(
                    current_index_revision_id=changed,
                    lock_version=2,
                    updated_at=NOW + timedelta(seconds=1),
                )
            )
    update_result = session.execute(
        update(EmbeddingIndexRecord)
        .where(
            EmbeddingIndexRecord.index_id == head.index_id,
            EmbeddingIndexRecord.lock_version == 1,
            EmbeddingIndexRecord.current_index_revision_id.is_(None),
        )
        .values(
            current_index_revision_id=revision.index_revision_id,
            lock_version=2,
            updated_at=NOW + timedelta(seconds=1),
        )
    )
    assert cast(CursorResult[Any], update_result).rowcount == 1
    replay = session.execute(
        update(EmbeddingIndexRecord)
        .where(
            EmbeddingIndexRecord.index_id == head.index_id, EmbeddingIndexRecord.lock_version == 1
        )
        .values(current_index_revision_id=revision.index_revision_id, lock_version=2)
    )
    assert cast(CursorResult[Any], replay).rowcount == 0
    for values in ({"space_sha256": sha("b")}, {"lock_version": 3}):
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(
                update(EmbeddingIndexRecord)
                .where(EmbeddingIndexRecord.index_id == head.index_id)
                .values(**values)
            )
    with pytest.raises(DBAPIError), session.begin_nested():
        session.execute(
            delete(EmbeddingIndexRecord).where(EmbeddingIndexRecord.index_id == head.index_id)
        )


def test_encoding_key_row_unique_artifact_pairing_and_immutable(registry_session: Session) -> None:
    session = registry_session
    seed, other = _seed(session), _seed(session)
    body = {
        "encoding_sha256": "sha256:" + uuid4().hex * 2,
        "storage_partition": "synthetic",
        "space_sha256": sha(),
        "input_text_sha256": "sha256:" + uuid4().hex * 2,
        "shard_artifact_id": seed["artifact"],
        "shard_artifact_revision_id": seed["artifact_revision"],
        "shard_member_path": "shard.json",
        "shard_schema_ref": "eom://schemas/knowledge/embedding-vector-shard/1.0",
        "shard_media_type": "application/json",
        "shard_sha256": sha(),
        "row_index": 0,
        "registered_at": NOW,
    }
    session.add(EmbeddingEncodingRecord(**body))
    session.flush()
    for changed in (
        {"encoding_sha256": "sha256:" + uuid4().hex * 2},
        {
            "encoding_sha256": "sha256:" + uuid4().hex * 2,
            "input_text_sha256": "sha256:" + uuid4().hex * 2,
        },
        {
            "encoding_sha256": "sha256:" + uuid4().hex * 2,
            "input_text_sha256": "sha256:" + uuid4().hex * 2,
            "shard_artifact_revision_id": other["artifact_revision"],
        },
        {
            "encoding_sha256": "sha256:" + uuid4().hex * 2,
            "input_text_sha256": "sha256:" + uuid4().hex * 2,
            "row_index": 1024,
        },
    ):
        with pytest.raises(DBAPIError), session.begin_nested():
            session.add(EmbeddingEncodingRecord(**(body | changed)))
            session.flush()
    for statement in (
        update(EmbeddingEncodingRecord)
        .where(EmbeddingEncodingRecord.encoding_sha256 == body["encoding_sha256"])
        .values(row_index=0),
        delete(EmbeddingEncodingRecord).where(
            EmbeddingEncodingRecord.encoding_sha256 == body["encoding_sha256"]
        ),
    ):
        with pytest.raises(DBAPIError, match="immutable") as rejected, session.begin_nested():
            session.execute(statement)
        assert getattr(rejected.value.orig, "sqlstate", None) == "23514"
    assert (
        session.scalar(
            select(EmbeddingEncodingRecord.row_index).where(
                EmbeddingEncodingRecord.encoding_sha256 == body["encoding_sha256"]
            )
        )
        == body["row_index"]
    )


def _binding_source_ids(session: Session, seed: dict[str, Any]) -> tuple[str, str, str, str]:
    """Reuse the existing synthetic plan fixture, not real analysis/report admission."""
    plan_id, _, _ = _complete_control_plane(session)
    plan = session.get(ResolvedExecutionPlanRecord, plan_id)
    assert plan is not None
    base_workflow, solution_workflow = _workflow(session), _workflow(session)
    suffix = uuid4().hex
    pack_id, release_id = "contentpack_" + suffix, "packrel_" + suffix
    item_id, item_revision = "item_" + suffix, "itemrev_" + suffix
    step_id, risk_id = "steprun_" + suffix, "riskpolicyrev_" + suffix
    session.add(
        ContentPackRecord(
            content_pack_id=pack_id,
            pack_key="registry-" + suffix,
            display_name="Synthetic relational pack",
            description="test",
            locale="ko-KR",
            domain_key="TEST",
        )
    )
    session.add(
        ItemRecord(item_id=item_id, lifecycle_state="DRAFT", created_by="test", lock_version=1)
    )
    session.add(
        WorkflowStepRunRecord(
            step_run_id=step_id,
            workflow_id=base_workflow.workflow_id,
            step_key="fixture",
            attempt=1,
            step_type="terminal",
            worker_role=None,
            state="SUCCEEDED",
            platform_job_id=seed["job"],
            input_pointer_manifest={},
        )
    )
    session.add(
        KnowledgeAnalysisRiskPolicyRevisionRecord(
            risk_policy_revision_id=risk_id,
            schema_version="synthetic",
            state="RELEASED",
            content_sha256="sha256:" + suffix * 2,
            canonical_document={},
            created_by="test",
            created_at=NOW,
        )
    )
    session.flush()
    session.add(
        ContentPackReleaseRecord(
            content_pack_release_id=release_id,
            content_pack_id=pack_id,
            version="1.0.0",
            schema_version="1.0",
            state="DRAFT",
            source_tree_sha256=sha(),
            bundle_sha256="sha256:" + suffix * 2,
            manifest_sha256=sha(),
            bundle_artifact_id=seed["artifact"],
            bundle_artifact_revision_id=seed["artifact_revision"],
            canonical_manifest_json={},
            compatibility_json={},
            lock_version=1,
        )
    )
    session.flush()
    session.add(
        ItemRevisionRecord(
            item_revision_id=item_revision,
            item_id=item_id,
            revision_number=1,
            revision_state="DRAFT",
            registration_key="fixture:" + suffix,
            content_pack_release_id=release_id,
            workflow_id=base_workflow.workflow_id,
            workflow_definition_version=base_workflow.definition_version,
            source_workflow_step_run_id=step_id,
            manifest_artifact_id=seed["artifact"],
            manifest_artifact_revision_id=seed["artifact_revision"],
            manifest_sha256=sha(),
            item_type_key="synthetic",
            metadata_json={},
            metadata_sha256=sha(),
            created_by="test",
            lock_version=1,
        )
    )
    session.flush()
    run_ids = []
    for workflow in (base_workflow, solution_workflow):
        run_suffix = uuid4().hex
        run_id = "analysisrun_" + run_suffix
        session.add(
            KnowledgeAnalysisRunRecord(
                analysis_run_id=run_id,
                analysis_request_id="knowledgeanalysis_" + run_suffix,
                request_sha256=sha(),
                submission_sha256=sha(),
                idempotency_key="fixture:" + run_suffix,
                canonical_request={"synthetic": True},
                source_kind="APPROVED_ITEM_REVISION",
                source_revision_id=item_revision,
                item_id=item_id,
                item_revision_id=item_revision,
                source_artifact_id=seed["artifact"],
                source_artifact_revision_id=seed["artifact_revision"],
                source_sha256=sha(),
                workflow_id=workflow.workflow_id,
                plan_id=plan_id,
                preset_id=plan.preset_id,
                preset_revision_id=plan.preset_revision_id,
                risk_policy_revision_id=risk_id,
                risk_policy_sha256=sha(),
                state="REQUESTED",
                lock_version=1,
                created_by_operator_id=seed["actor"],
            )
        )
        run_ids.append(run_id)
    session.flush()
    return item_id, item_revision, run_ids[0], run_ids[1]


def test_binding_relational_happy_unique_pairing_and_immutable_not_admission(
    registry_session: Session,
) -> None:
    session = registry_session
    seed = _seed(session)
    item_id, item_revision, base_run, solution_run = _binding_source_ids(session, seed)
    encoding = "sha256:" + uuid4().hex * 2
    session.add(
        EmbeddingEncodingRecord(
            encoding_sha256=encoding,
            storage_partition="synthetic",
            space_sha256=sha(),
            input_text_sha256="sha256:" + uuid4().hex * 2,
            shard_artifact_id=seed["artifact"],
            shard_artifact_revision_id=seed["artifact_revision"],
            shard_member_path="shard.json",
            shard_schema_ref="eom://schemas/knowledge/embedding-vector-shard/1.0",
            shard_media_type="application/json",
            shard_sha256=sha(),
            row_index=0,
            registered_at=NOW,
        )
    )
    session.flush()
    body = {
        "binding_sha256": "sha256:" + uuid4().hex * 2,
        "encoding_sha256": encoding,
        "item_id": item_id,
        "item_revision_id": item_revision,
        "source_class": "APPROVED_ITEM",
        "source_sha256": sha(),
        "base_analysis_run_id": base_run,
        "solution_analysis_run_id": solution_run,
        "solution_pointer_sha256": sha(),
        "profile_id": "inferenceprofile_" + uuid4().hex,
        "profile_revision_id": "inferenceprofilerev_" + uuid4().hex,
        "profile_sha256": sha(),
        "graph_snapshot_revision_id": seed["snapshot"],
        "policy_revision_id": seed["policy"],
        "policy_sha256": sha(),
        "view": "METADATA_ONLY",
        "recipe_sha256": sha(),
        "projection_version": "accepted-solution-comparison/1.0",
        "binding_manifest_artifact_id": seed["artifact"],
        "binding_manifest_artifact_revision_id": seed["artifact_revision"],
        "binding_manifest_member_path": "index.json",
        "binding_manifest_schema_ref": "eom://schemas/knowledge/embedding-index-manifest/1.0",
        "binding_manifest_media_type": "application/json",
        "binding_manifest_sha256": sha(),
        "registered_at": NOW,
    }
    session.add(EmbeddingSourceBindingRecord(**body))
    session.flush()
    other_item = "item_" + uuid4().hex
    session.add(
        ItemRecord(item_id=other_item, lifecycle_state="DRAFT", created_by="test", lock_version=1)
    )
    session.flush()
    for changed in (
        {},
        {"item_id": other_item},
        {"item_revision_id": "itemrev_" + uuid4().hex},
        {"encoding_sha256": "sha256:" + uuid4().hex * 2},
        {"solution_analysis_run_id": base_run},
        {"profile_sha256": "sha256:bad"},
    ):
        changed_body = body | {"binding_sha256": "sha256:" + uuid4().hex * 2} | changed
        with pytest.raises(DBAPIError), session.begin_nested():
            session.add(EmbeddingSourceBindingRecord(**changed_body))
            session.flush()
    for statement in (
        update(EmbeddingSourceBindingRecord)
        .where(EmbeddingSourceBindingRecord.binding_sha256 == body["binding_sha256"])
        .values(profile_sha256=sha()),
        delete(EmbeddingSourceBindingRecord).where(
            EmbeddingSourceBindingRecord.binding_sha256 == body["binding_sha256"]
        ),
    ):
        with pytest.raises(DBAPIError, match="immutable") as rejected, session.begin_nested():
            session.execute(statement)
        assert getattr(rejected.value.orig, "sqlstate", None) == "23514"
    # FK existence is intentionally not source eligibility: a future owner must reject
    # these DRAFT Items/REQUESTED analyses before real registry admission.
    assert (
        session.scalar(
            select(EmbeddingSourceBindingRecord.binding_sha256).where(
                EmbeddingSourceBindingRecord.binding_sha256 == body["binding_sha256"]
            )
        )
        == body["binding_sha256"]
    )


def test_binding_sha_batch_read_refreshes_every_scalar_and_exact_first_origin(
    registry_session: Session,
) -> None:
    """Actual immutable SQL rows replace forged local values, never grant source admission."""
    session = registry_session
    seed = _seed(session)
    item_id, item_revision, base_run, solution_run = _binding_source_ids(session, seed)
    body = source_binding().model_dump(mode="json")
    body["source"].update(item_id=item_id, item_revision_id=item_revision)
    body["solution_evidence"].update(
        base_analysis_run_id=base_run, solution_analysis_run_id=solution_run
    )
    body["solution_evidence"] = seal(body["solution_evidence"], "pointer_sha256")
    body["graph_snapshot"]["graph_snapshot_revision_id"] = seed["snapshot"]
    body["policy_revision_id"] = seed["policy"]
    body["row_ref"]["shard_manifest"].update(
        artifact_id=seed["artifact"], artifact_revision_id=seed["artifact_revision"]
    )
    expected: dict[str, tuple[dict[str, Any], ArtifactMemberPointer]] = {}
    originals: dict[str, EmbeddingSourceBindingRecord] = {}
    for ordinal in range(2):
        body["profile"].update(
            profile_id="inferenceprofile_" + uuid4().hex,
            profile_revision_id="inferenceprofilerev_" + uuid4().hex,
        )
        binding = EmbeddingSourceBinding.model_validate(seal(body, "binding_sha256"))
        if ordinal == 0:
            session.add(
                EmbeddingEncodingRecord(
                    **binding.encoding.model_dump(mode="python"),
                    **{
                        "shard_" + name: value
                        for name, value in binding.row_ref.shard_manifest.model_dump(
                            mode="python"
                        ).items()
                    },
                    row_index=binding.row_ref.row_index,
                    registered_at=NOW,
                )
            )
            session.flush()
        origin = ArtifactMemberPointer(
            artifact_id=seed["artifact"],
            artifact_revision_id=seed["artifact_revision"],
            member_path="index.json",
            schema_ref="eom://schemas/knowledge/embedding-index-manifest/1.0",
            media_type="application/json",
            sha256=sha("b" if ordinal == 0 else "c"),
        )
        scalars = binding_columns(binding)
        origin_columns = {
            "binding_manifest_" + name: value
            for name, value in origin.model_dump(mode="python").items()
        }
        assert set(scalars) | set(origin_columns) | {"registered_at"} == {
            column.name for column in EmbeddingSourceBindingRecord.__table__.columns
        }
        row = EmbeddingSourceBindingRecord(**scalars, **origin_columns, registered_at=NOW)
        session.add(row)
        expected[binding.binding_sha256] = scalars, origin
        originals[binding.binding_sha256] = row
    session.flush()
    # Poison only identity-map values: real history stays untouched and triggers stay enabled.
    # With autoflush disabled this read cannot repair itself through UPDATE or expiry.
    for key, row in originals.items():
        scalars, origin = expected[key]
        for name, value in scalars.items():
            set_committed_value(
                row, name, "forged-null" if value is None else value + ":forged-local"
            )
        for name, value in origin.model_dump(mode="python").items():
            set_committed_value(row, "binding_manifest_" + name, value + ":forged-local")
        assert row.binding_manifest_sha256 != origin.sha256
    assert not session.dirty
    statements: list[str] = []

    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.upper())

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", observe)
    try:
        repository = EmbeddingRegistryRepository(session)
        assert repository.bindings_by_sha256(()) == {}
        assert statements == []
        keys = tuple(expected)
        with session.no_autoflush:
            found = repository.bindings_by_sha256((*keys, keys[0], sha("f")))
    finally:
        event.remove(connection, "before_cursor_execute", observe)
    assert len(statements) == 1 and statements[0].lstrip().startswith("SELECT ")
    assert "WHERE EMBEDDING_SOURCE_BINDINGS.BINDING_SHA256 IN " in statements[0]
    assert set(found) == set(expected)
    for key, (scalars, origin) in expected.items():
        assert found[key] is originals[key]
        assert {name: getattr(found[key], name) for name in scalars} == scalars
        assert binding_origin(found[key]).manifest == origin


def test_revision_append_only_and_nonempty_downgrade_refusal(registry_session: Session) -> None:
    session = registry_session
    seed = _seed(session)
    head = _head(session, seed)
    revision = _revision(session, seed, head)
    for statement in (
        update(EmbeddingIndexRevisionRecord)
        .where(EmbeddingIndexRevisionRecord.index_revision_id == revision.index_revision_id)
        .values(binding_count=1),
        delete(EmbeddingIndexRevisionRecord).where(
            EmbeddingIndexRevisionRecord.index_revision_id == revision.index_revision_id
        ),
    ):
        with pytest.raises(DBAPIError, match="immutable") as rejected, session.begin_nested():
            session.execute(statement)
        assert getattr(rejected.value.orig, "sqlstate", None) == "23514"
    assert (
        session.scalar(
            select(EmbeddingIndexRevisionRecord.binding_count).where(
                EmbeddingIndexRevisionRecord.index_revision_id == revision.index_revision_id
            )
        )
        == revision.binding_count
    )
    with (
        pytest.raises(DBAPIError, match="requires empty registry"),
        session.begin_nested(),
        Operations.context(MigrationContext.configure(session.connection())),
    ):
        migration_module().downgrade()
    assert (
        session.scalar(
            select(EmbeddingIndexRecord.index_id).where(
                EmbeddingIndexRecord.index_id == head.index_id
            )
        )
        == head.index_id
    )


def _registered_review_binding_body(session: Session) -> dict[str, Any]:
    """Real FK rows only, not proof of accepted V2, a role review or source admission."""
    seed = _seed(session)
    item_id, item_revision, base_run, _solution_run = _binding_source_ids(session, seed)
    encoding = "sha256:" + uuid4().hex * 2
    session.add(
        EmbeddingEncodingRecord(
            encoding_sha256=encoding,
            storage_partition="synthetic-review",
            space_sha256=sha(),
            input_text_sha256="sha256:" + uuid4().hex * 2,
            shard_artifact_id=seed["artifact"],
            shard_artifact_revision_id=seed["artifact_revision"],
            shard_member_path="shard.json",
            shard_schema_ref="eom://schemas/knowledge/embedding-vector-shard/1.0",
            shard_media_type="application/json",
            shard_sha256=sha(),
            row_index=0,
            registered_at=NOW,
        )
    )
    session.flush()
    return {
        "binding_sha256": "sha256:" + uuid4().hex * 2,
        "encoding_sha256": encoding,
        "item_id": item_id,
        "item_revision_id": item_revision,
        "source_class": "APPROVED_ITEM",
        "source_sha256": sha(),
        "evidence_kind": "REGISTERED_ITEM_REVIEW_SOLUTION",
        "base_analysis_run_id": base_run,
        "solution_analysis_run_id": None,
        "solution_pointer_sha256": None,
        "review_job_id": seed["job"],
        "review_evidence_sha256": sha(),
        "profile_id": "inferenceprofile_" + uuid4().hex,
        "profile_revision_id": "inferenceprofilerev_" + uuid4().hex,
        "profile_sha256": sha(),
        "graph_snapshot_revision_id": seed["snapshot"],
        "policy_revision_id": seed["policy"],
        "policy_sha256": sha(),
        "view": "CONTENT_ONLY",
        "recipe_sha256": sha(),
        "projection_version": "registered-item-review-comparison/1.0",
        "binding_manifest_artifact_id": seed["artifact"],
        "binding_manifest_artifact_revision_id": seed["artifact_revision"],
        "binding_manifest_member_path": "index.json",
        "binding_manifest_schema_ref": "eom://schemas/knowledge/embedding-index-manifest/2.0",
        "binding_manifest_media_type": "application/json",
        "binding_manifest_sha256": sha(),
        "registered_at": NOW,
    }


def test_registered_review_xor_real_foreign_keys_partial_unique_and_history_guards(
    registry_session: Session,
) -> None:
    session = registry_session
    body = _registered_review_binding_body(session)
    session.add(EmbeddingSourceBindingRecord(**body))
    session.flush()
    row = session.get(EmbeddingSourceBindingRecord, body["binding_sha256"])
    assert row is not None and row.base_analysis_run_id == body["base_analysis_run_id"]
    assert row.review_job_id == body["review_job_id"]
    assert row.solution_analysis_run_id is None and row.solution_pointer_sha256 is None
    for changed, sqlstate in (
        ({}, "23505"),
        ({"review_job_id": "job_" + uuid4().hex}, "23503"),
        ({"base_analysis_run_id": "analysisrun_" + uuid4().hex}, "23503"),
        ({"review_job_id": None}, "23514"),
        ({"review_evidence_sha256": None}, "23514"),
        ({"review_evidence_sha256": "bad-hash"}, "23514"),
        ({"solution_analysis_run_id": body["base_analysis_run_id"]}, "23514"),
        ({"solution_pointer_sha256": sha()}, "23514"),
        ({"source_class": "PAST_EXAM"}, "23514"),
        ({"evidence_kind": "ACCEPTED_SOLUTION_ANALYSIS"}, "23514"),
        ({"projection_version": "accepted-solution-comparison/1.0"}, "23514"),
        (
            {"binding_manifest_schema_ref": "eom://schemas/knowledge/embedding-index-manifest/1.0"},
            "23514",
        ),
    ):
        with pytest.raises(DBAPIError) as rejected, session.begin_nested():
            session.add(
                EmbeddingSourceBindingRecord(
                    **(body | {"binding_sha256": "sha256:" + uuid4().hex * 2} | changed)
                )
            )
            session.flush()
        assert getattr(rejected.value.orig, "sqlstate", None) == sqlstate
    for statement in (
        update(EmbeddingSourceBindingRecord)
        .where(EmbeddingSourceBindingRecord.binding_sha256 == body["binding_sha256"])
        .values(review_evidence_sha256=sha("b")),
        delete(EmbeddingSourceBindingRecord).where(
            EmbeddingSourceBindingRecord.binding_sha256 == body["binding_sha256"]
        ),
    ):
        with pytest.raises(DBAPIError, match="immutable") as rejected, session.begin_nested():
            session.execute(statement)
        assert getattr(rejected.value.orig, "sqlstate", None) == "23514"
    with (
        pytest.raises(DBAPIError, match="absent successor history") as refused,
        session.begin_nested(),
        Operations.context(MigrationContext.configure(session.connection())),
    ):
        registered_review_migration().downgrade()
    assert getattr(refused.value.orig, "sqlstate", None) == "23514"
    assert session.get(EmbeddingSourceBindingRecord, body["binding_sha256"]) is row


def test_mixed_namespace_and_manifest_successor_do_not_allow_past_exam_scope(
    registry_session: Session,
) -> None:
    session = registry_session
    seed = _seed(session)
    body = {
        "index_id": "embeddingindex_" + uuid4().hex,
        "corpus_id": seed["corpus"],
        "storage_partition": "synthetic-review",
        "space_sha256": sha(),
        "view": "CONTENT_ONLY",
        "recipe_sha256": sha(),
        "projection_version": "mixed-solution-comparison/2.0",
        "population_scope": "ALL_ADMITTED_GRAPH_ITEMS",
        "current_index_revision_id": None,
        "lock_version": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    head = EmbeddingIndexRecord(**body)
    session.add(head)
    session.flush()
    revision = _revision(
        session,
        seed,
        head,
        manifest_schema_ref="eom://schemas/knowledge/embedding-index-manifest/2.0",
    )
    assert revision.manifest_schema_ref.endswith("/2.0")
    for changed in (
        {"population_scope": "OCCURRENCE_BACKED_PAST_EXAM"},
        {"projection_version": "registered-item-review-comparison/1.0"},
    ):
        with pytest.raises(DBAPIError) as rejected, session.begin_nested():
            session.add(
                EmbeddingIndexRecord(
                    **(body | {"index_id": "embeddingindex_" + uuid4().hex} | changed)
                )
            )
            session.flush()
        assert getattr(rejected.value.orig, "sqlstate", None) == "23514"


def test_registered_review_partial_indexes_are_real_btree_and_unique(
    registry_session: Session,
) -> None:
    rows = registry_session.execute(
        text(
            "SELECT index_class.relname,access_method.amname,indexes.indisunique,"
            "indexes.indisvalid,pg_get_expr(indexes.indpred,indexes.indrelid) "
            "FROM pg_index indexes JOIN pg_class relation ON relation.oid=indexes.indrelid "
            "JOIN pg_namespace namespace ON namespace.oid=relation.relnamespace "
            "JOIN pg_class index_class ON index_class.oid=indexes.indexrelid "
            "JOIN pg_am access_method ON access_method.oid=index_class.relam "
            "WHERE namespace.nspname='app' AND relation.relname='embedding_source_bindings' "
            "AND index_class.relname IN ('uq_embedding_binding_registered_review',"
            "'ix_embedding_binding_review_delta')"
        )
    ).all()
    assert len(rows) == 2
    for name, method, unique, valid, predicate in rows:
        assert method == "btree" and valid is True
        assert unique is (name == "uq_embedding_binding_registered_review")
        assert "REGISTERED_ITEM_REVIEW_SOLUTION" in predicate


def test_registered_review_batch_lookup_and_antijoin_use_real_nonnull_keys(
    registry_session: Session,
) -> None:
    session = registry_session
    body = _registered_review_binding_body(session)
    session.add(EmbeddingSourceBindingRecord(**body))
    session.flush()
    key = RegisteredReviewEmbeddingBindingLookupKey(
        **{name: body[name] for name in REGISTERED_REVIEW_ASSOCIATION_COLUMNS}
    )
    absent = replace(key, review_evidence_sha256=sha("f"))
    repository = EmbeddingRegistryRepository(session)
    statements: list[str] = []

    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", observe)
    try:
        assert set(repository.bindings((key, absent))) == {body["binding_sha256"]}
        assert repository.missing_bindings((absent, key)) == (absent,)
    finally:
        event.remove(connection, "before_cursor_execute", observe)
    assert len(statements) == 2
    assert " IN (" in statements[0] and "VALUES" in statements[1]
    assert all("evidence_kind" in statement for statement in statements)


def test_registered_review_concurrent_duplicate_uses_the_partial_unique(
    guarded_engine: Engine,
) -> None:
    """Two real transactions, disposable metadata only; no registered review authority."""
    with Session(guarded_engine) as session, session.begin():
        body = _registered_review_binding_body(session)
    first_inserted, second_entered, release_first = Event(), Event(), Event()

    def first() -> str:
        with Session(guarded_engine) as session, session.begin():
            session.add(EmbeddingSourceBindingRecord(**body))
            session.flush()
            first_inserted.set()
            assert release_first.wait(15)
        return "INSERTED"

    def second() -> str:
        assert first_inserted.wait(15)
        with guarded_engine.connect() as connection:

            def entering(_connection, _cursor, statement, _parameters, _context, _many):
                if statement.lstrip().startswith("INSERT INTO embedding_source_bindings"):
                    second_entered.set()

            event.listen(connection, "before_cursor_execute", entering)
            try:
                with Session(bind=connection) as session, session.begin():
                    session.add(
                        EmbeddingSourceBindingRecord(
                            **(body | {"binding_sha256": "sha256:" + uuid4().hex * 2})
                        )
                    )
                    session.flush()
            except DBAPIError as error:
                assert getattr(error.orig, "sqlstate", None) == "23505"
                assert (
                    getattr(getattr(error.orig, "diag", None), "constraint_name", None)
                    == "uq_embedding_binding_registered_review"
                )
                return "DUPLICATE"
            finally:
                event.remove(connection, "before_cursor_execute", entering)
        raise AssertionError("duplicate registered association was inserted")

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_result = executor.submit(first)
        try:
            assert first_inserted.wait(15)
            second_result = executor.submit(second)
            assert second_entered.wait(15)
        finally:
            release_first.set()
        assert first_result.result(timeout=20) == "INSERTED"
        assert second_result.result(timeout=20) == "DUPLICATE"
    with Session(guarded_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(EmbeddingSourceBindingRecord)
                .where(EmbeddingSourceBindingRecord.item_revision_id == body["item_revision_id"])
            )
            == 1
        )
