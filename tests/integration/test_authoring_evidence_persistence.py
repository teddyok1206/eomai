"""Guarded PostgreSQL + committed local V5 Evidence; not live source/IAM acceptance.

Publication, replay, relational constraints and Artifact byte resolution are real.
Graph/source/report eligibility and ranking are explicit synthetic fixture seams.
No model, worker, operating DB, NAS or user authentication is used.
"""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_contracts import (
    CreateEvidenceBundleCommand,
    EvidenceBundlePublicationResultV5,
    EvidenceEntryV5,
)
from eom_catalog_service.knowledge_graph_models import (
    EducationRetrievalAccessPolicyRevisionRecord,
    EducationRetrievalRequestRecord,
    EvidenceBundleRecord,
    EvidenceBundleRevisionRecord,
    KnowledgeCorpusRevisionRecord,
    KnowledgeGraphSnapshotRecord,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalServiceError,
)
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactReadContext,
    PinnedArtifactResolutionError,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from tests.integration.test_embedding_registry_persistence import _binding_source_ids, _seed
from tests.integration.test_local_indexing_source_policy import policies
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_authoring_reference_selection import case

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def evidence(guarded_engine, tmp_path, monkeypatch):
    assert guarded_engine.dialect.name == "postgresql"
    settings = CatalogSettings(
        staging_root=tmp_path / "staging",
        nas_artifact_root=tmp_path / "artifacts",
        intake_root=tmp_path / "intake",
    )
    settings.staging_root.mkdir(mode=0o700)
    settings.nas_artifact_root.mkdir(mode=0o700)
    service = KnowledgeRetrievalApplicationService(guarded_engine, settings)
    with Session(guarded_engine) as session, session.begin():
        seed = _seed(session)
        item_id, revision_id, *_ = _binding_source_ids(session, seed)
    # A real committed, bounded graph Artifact; its document is deliberately not
    # scientific source evidence. The fixture does not run the source resolver.
    graph_path = tmp_path / "graph.json"
    graph_path.write_bytes(canonical_json_bytes({"synthetic_graph": uuid4().hex}))
    graph = service.artifacts.commit_file_set(
        files={"projections/manifest.json": graph_path},
        primary_file="projections/manifest.json",
        artifact_type="knowledge-graph-snapshot-manifest",
        idempotency_key="synthetic-authoring-graph:" + uuid4().hex,
        request={"synthetic": True},
        result={},
        file_metadata={
            "projections/manifest.json": {
                "schema_ref": "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/2.0",
                "media_type": "application/json",
            }
        },
    )
    policy, _ = policies()
    corpus_revision, snapshot = "corpusrev_" + uuid4().hex, "graphrev_" + uuid4().hex
    now = datetime.now(UTC)
    with Session(guarded_engine) as session, session.begin():
        previous = session.get(KnowledgeGraphSnapshotRecord, seed["snapshot"])
        session.add(
            KnowledgeCorpusRevisionRecord(
                corpus_revision_id=corpus_revision,
                corpus_id=seed["corpus"],
                revision_number=2,
                previous_corpus_revision_id=previous.corpus_revision_id,
                source_set_sha256=content_sha256({"synthetic": uuid4().hex}),
                state="PUBLISHED",
                created_by_operator_id=seed["actor"],
                created_at=now,
            )
        )
        session.add(
            EducationRetrievalAccessPolicyRevisionRecord(
                access_policy_revision_id=policy.access_policy_revision_id,
                schema_version=policy.schema_version,
                state=policy.state,
                content_sha256=policy.content_sha256,
                canonical_document=policy.model_dump(mode="json"),
                created_by="synthetic-evidence-test",
                created_at=policy.created_at,
            )
        )
        session.flush()
        values = {
            column.key: getattr(previous, column.key) for column in previous.__table__.columns
        }
        values.update(
            graph_snapshot_revision_id=snapshot,
            corpus_revision_id=corpus_revision,
            revision_number=2,
            previous_graph_snapshot_revision_id=previous.graph_snapshot_revision_id,
            manifest_artifact_id=graph.artifact_id,
            manifest_artifact_revision_id=graph.revision_id,
            manifest_sha256=graph.content_hash,
            created_at=now,
        )
        session.add(KnowledgeGraphSnapshotRecord(**values))
    original = case()
    entry = original.manifest.entries[0].model_dump(mode="json")
    entry["source"].update(item_id=item_id, item_revision_id=revision_id)
    entry["source"]["artifact_member"].update(
        artifact_id=seed["artifact"], artifact_revision_id=seed["artifact_revision"]
    )
    entry = EvidenceEntryV5.model_validate(entry)
    # These are the only scientific eligibility/ranking seams. The official
    # writer still builds and commits the exact request, context and V5 manifest.
    monkeypatch.setattr(service, "_candidates", Mock(return_value=()))
    monkeypatch.setattr(
        service, "_rank_and_render", Mock(return_value=((entry,), "Synthetic reference context."))
    )
    command = dict(
        operation="CREATE_EVIDENCE_BUNDLE",
        graph_snapshot_revision_id=snapshot,
        query_kind="ITEM_PREPARATION",
        curriculum_scope=None,
        topic_keys=["synthetic.reference"],
        target_item_revision_id=None,
        required_item_elements=[],
        source_classes=["PAST_EXAM"],
        evidence_budget=policy.maximum_budget.model_dump(mode="json"),
        access_policy_revision_id=policy.access_policy_revision_id,
        requester_role="EDITOR",
        requester_permission_keys=["knowledge_graph:read", "knowledge_graph:retrieve"],
        requested_by=seed["actor"],
        idempotency_key="synthetic-authoring-evidence:" + uuid4().hex,
    )
    command["submission_sha256"] = content_sha256(
        {key: value for key, value in command.items() if key != "idempotency_key"}
    )
    command = CreateEvidenceBundleCommand.model_validate(command)
    publication = service.create(command, require_solution_evidence=True)
    assert isinstance(publication, EvidenceBundlePublicationResultV5)
    return SimpleNamespace(
        engine=guarded_engine,
        settings=settings,
        service=service,
        command=command,
        publication=publication,
        actor=seed["actor"],
        entry=entry,
    )


def counts(value):
    with Session(value.engine) as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (
                JobRecord,
                ArtifactRevisionRecord,
                EducationRetrievalRequestRecord,
                EvidenceBundleRecord,
                EvidenceBundleRevisionRecord,
            )
        )


def read(value, *, publication=None, actor=None):
    with Session(value.engine) as session, session.begin():
        session.execute(text("SET TRANSACTION READ ONLY"))
        assert session.scalar(text("SHOW transaction_read_only")) == "on"
        result = value.service.read_published_item_evidence_in_session(
            session,
            publication or value.publication,
            requested_by=actor or value.actor,
            artifact_reader=PinnedArtifactReadContext(session, value.settings),
        )
        assert not session.new and not session.dirty and not session.deleted
        return result


def test_committed_v5_original_publication_replay_and_root_read_do_not_write(evidence):
    before = counts(evidence)
    assert evidence.service.create(evidence.command) == evidence.publication
    manifest = read(evidence)
    assert read(evidence) == manifest
    assert manifest.entries == (evidence.entry,)
    assert manifest.created_at == evidence.publication.published_at
    assert manifest.materials.context_markdown == evidence.publication.context_artifact
    assert counts(evidence) == before


@pytest.mark.parametrize(
    "field,value",
    (
        ("evidence_bundle_id", "evidence_" + "f" * 32),
        ("evidence_bundle_revision_id", "evidencerev_" + "f" * 32),
        ("retrieval_request_id", "retrieval_" + "f" * 32),
        ("requester_permissions_sha256", "sha256:" + "f" * 64),
        ("manifest_sha256", "sha256:" + "f" * 64),
        ("access_policy_sha256", "sha256:" + "f" * 64),
    ),
)
def test_valid_but_foreign_publication_pins_never_resolve_latest(evidence, field, value):
    before = counts(evidence)
    raw = evidence.publication.model_dump(mode="json") | {field: value}
    changed = EvidenceBundlePublicationResultV5.model_validate(seal(raw, "result_sha256"))
    with pytest.raises(KnowledgeRetrievalServiceError) as caught:
        read(evidence, publication=changed)
    assert caught.value.code == "KNOWLEDGE_RETRIEVAL_PUBLICATION_INVALID"
    assert counts(evidence) == before


def test_another_operator_cannot_reuse_the_original_evidence(evidence):
    before = counts(evidence)
    with pytest.raises(KnowledgeRetrievalServiceError) as caught:
        read(evidence, actor="operator_" + "f" * 32)
    assert caught.value.code == "KNOWLEDGE_RETRIEVAL_PUBLICATION_INVALID"
    assert counts(evidence) == before


@pytest.mark.parametrize("member", ("manifest_artifact", "context_artifact"))
@pytest.mark.parametrize("damage", ("bytes", "missing"))
def test_actual_corrupted_or_missing_committed_members_fail_without_republication(
    evidence, member, damage
):
    pointer = getattr(evidence.publication, member)
    with Session(evidence.engine) as session:
        revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
        target = Path(revision.nas_path) / pointer.member_path
    assert target.is_relative_to(evidence.settings.nas_artifact_root)
    before = counts(evidence)
    if damage == "missing":
        target.rename(target.with_name(target.name + ".preserved"))
    else:
        target.write_bytes(b"synthetic-corruption")
    with pytest.raises(PinnedArtifactResolutionError):
        read(evidence)
    assert counts(evidence) == before


def test_reader_from_another_root_cannot_be_reused(evidence):
    with Session(evidence.engine) as first, first.begin():
        reader = PinnedArtifactReadContext(first, evidence.settings)
        with (
            Session(evidence.engine) as second,
            second.begin(),
            pytest.raises(PinnedArtifactResolutionError),
        ):
            evidence.service.read_published_item_evidence_in_session(
                second,
                evidence.publication,
                requested_by=evidence.actor,
                artifact_reader=reader,
            )
