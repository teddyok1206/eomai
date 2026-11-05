"""Guarded PG save/archive/replay and IAM; source bytes are a synthetic test leaf."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from eom_catalog_contracts.curated_document_assembly import CuratedDocumentAssemblyManifestV1
from eom_catalog_contracts.curated_document_assembly_draft import RegisteredItemPlacement
from eom_catalog_contracts.curated_document_assembly_library import (
    CuratedDocumentAssemblyDraftV2,
    CuratedDocumentAssemblyRemovalInput,
)
from eom_catalog_service import curated_document_assembly_service as module
from eom_catalog_service.curated_document_assembly_models import (
    CuratedDocumentAssemblyPlacementRecord,
    CuratedDocumentAssemblyRecord,
    CuratedDocumentAssemblyRevisionRecord,
)
from eom_catalog_service.curated_document_assembly_service import (
    CuratedDocumentAssemblyError,
    CuratedDocumentAssemblyService,
)
from eom_catalog_service.knowledge_graph_models import KnowledgeGraphSnapshotRecord
from eom_catalog_service.models import ItemRecord, ItemRevisionRecord
from eom_hwpx_manager.curated_application_service import CuratedHwpxApplicationService
from eom_hwpx_manager.curated_build_models import HwpxCuratedBuildRecord
from eom_identifiers import content_sha256
from eom_identity_service.models import OperatorRecord, OperatorRoleAssignmentRecord, RoleRecord
from eom_identity_service.repository import seed_builtin_rbac
from eom_operator_identity import PermissionKey
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_embedding_registry_persistence import _binding_source_ids, _seed
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.test_curated_document_assembly_resolution import _actor
from tests.unit.test_curated_hwpx_build import build_inputs

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
ROOT = Path(__file__).resolve().parents[2]


def migration():
    spec = spec_from_file_location(
        "curated_library_migration",
        ROOT / "migrations/versions/20261105_0073_curated_assembly_library.py",
    )
    assert spec and spec.loader
    value = module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_empty_library_metadata_roundtrips_without_changing_predecessor_selection(guarded_engine):
    with guarded_engine.begin() as connection:
        history = connection.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM curated_document_assemblies "
                "WHERE title<>'' OR removed_at IS NOT NULL)"
            )
        )
        if history:
            pytest.skip("this disposable DB already has preserved library history")
        with Operations.context(MigrationContext.configure(connection)):
            migration().downgrade()
            assert not connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema='app' AND table_name='curated_document_assemblies' "
                    "AND column_name='title')"
                )
            )
            migration().upgrade()
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261105_0073"


@pytest.fixture
def library(guarded_engine, monkeypatch):
    with Session(guarded_engine) as session, session.begin():
        seed = _seed(session)
        item_id, revision_id, *_ = _binding_source_ids(session, seed)
        seed_builtin_rbac(session)
        session.get(OperatorRecord, seed["actor"]).must_change_password = False
        item = session.get(ItemRecord, item_id)
        item.lifecycle_state, item.current_revision_id = "ACTIVE", revision_id
        revision = session.get(ItemRevisionRecord, revision_id)
        revision.revision_state = "APPROVED"
        graph = session.get(KnowledgeGraphSnapshotRecord, seed["snapshot"])
        pointer = RegisteredItemPlacement(
            placement_kind="REGISTERED_ITEM_REVISION",
            position=1,
            item_id=item_id,
            item_revision_id=revision_id,
            item_manifest_sha256=revision.manifest_sha256,
            graph_snapshot_revision_id=graph.graph_snapshot_revision_id,
            graph_snapshot_sha256=graph.snapshot_sha256,
        )
        role = session.scalar(select(RoleRecord).where(RoleRecord.role_key == "ADMIN"))
        assert role is not None
        other = "operator_" + uuid4().hex
        session.add(
            OperatorRecord(
                operator_id=other,
                username=other[-32:],
                normalized_username=other[-32:],
                display_name="Disposable library peer",
                status="ACTIVE",
                must_change_password=False,
                created_by="test",
            )
        )
        session.flush()
        assignments = []
        for actor_id in (seed["actor"], other):
            assignment = OperatorRoleAssignmentRecord(
                operator_role_assignment_id="oprole_" + uuid4().hex,
                operator_id=actor_id,
                role_id=role.role_id,
                assigned_by="test",
                assigned_at=datetime.now(UTC),
            )
            session.add(assignment)
            assignments.append(assignment.operator_role_assignment_id)
    actor = _actor(*PermissionKey).model_copy(update={"operator_id": seed["actor"]})
    peer = actor.model_copy(update={"operator_id": other})
    draft = CuratedDocumentAssemblyDraftV2(
        schema_version="curated-document-assembly-draft/2.0",
        title="공유하지 않은 조립",
        placements=(pointer,),
    )

    def resolve(_session, _media, *, draft, actor, assembly_id, assembly_revision_id, created_at):
        # Source bytes/admission have their independent resolver suites. The leaf
        # returns typed metadata against actual fixture Item/Graph foreign keys.
        value = dict(
            schema_version="curated-document-assembly-manifest/1.0",
            assembly_id=assembly_id,
            assembly_revision_id=assembly_revision_id,
            selection_sha256=content_sha256(draft.model_dump(mode="json")),
            placements=[row.model_dump(mode="json") for row in draft.placements],
            created_by=actor.actor_id,
            created_at=created_at.isoformat().replace("+00:00", "Z"),
        )
        value["manifest_sha256"] = content_sha256(value)
        return CuratedDocumentAssemblyManifestV1.model_validate(value)

    monkeypatch.setattr(module, "resolve_curated_document_assembly_manifest", resolve)
    service = CuratedDocumentAssemblyService(guarded_engine, NS())
    return NS(
        engine=guarded_engine,
        service=service,
        actor=actor,
        peer=peer,
        draft=draft,
        assignment=assignments[0],
    )


def create(value, suffix="one"):
    return value.service.create(
        value.draft, actor=value.actor, idempotency_key="library-save-" + suffix + uuid4().hex
    )


def remove(value, manifest, key="library-removal-fixed-key"):
    return value.service.remove_from_list(
        manifest.assembly_id,
        CuratedDocumentAssemblyRemovalInput(
            assembly_revision_id=manifest.assembly_revision_id,
            manifest_sha256=manifest.manifest_sha256,
        ),
        actor=value.actor,
        idempotency_key=key,
    )


def test_concurrent_same_titled_save_keeps_one_revision_and_same_v1_selection(library):
    value, start = library, Barrier(2)
    key = "library-save-concurrent-" + uuid4().hex

    def save():
        start.wait(timeout=10)
        return value.service.create(value.draft, actor=value.actor, idempotency_key=key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = [future.result(timeout=30) for future in (pool.submit(save), pool.submit(save))]
    assert a == b
    assert a.selection_sha256 == content_sha256(value.draft.selection().model_dump(mode="json"))
    with Session(value.engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(CuratedDocumentAssemblyRevisionRecord)
                .where(CuratedDocumentAssemblyRevisionRecord.assembly_id == a.assembly_id)
            )
            == 1
        )
        assert session.get(CuratedDocumentAssemblyRecord, a.assembly_id).title == value.draft.title
    with pytest.raises(CuratedDocumentAssemblyError, match="IDEMPOTENCY_CONFLICT"):
        value.service.create(
            value.draft.model_copy(update={"title": "다른 제목"}),
            actor=value.actor,
            idempotency_key=key,
        )


def test_concurrent_removal_preserves_manifest_placements_and_delivery_identity(
    library, monkeypatch
):
    from tests.integration.test_curated_hwpx_delivery import _Renderer

    value, start = library, Barrier(2)
    manifest = create(value)
    monkeypatch.setattr(
        module,
        "reauthorize_curated_registered_items",
        lambda _session, _placements: manifest.placements,
    )
    build_service = CuratedHwpxApplicationService(
        value.engine,
        assemblies=value.service,
        renderer=_Renderer(value.engine),
        input_pins=NS(pin_inputs=lambda source, **_a: build_inputs(source)),
    )
    build, created = build_service.request_build(
        manifest.assembly_id,
        assembly_revision_id=manifest.assembly_revision_id,
        manifest_sha256=manifest.manifest_sha256,
        actor=value.actor,
        idempotency_key="library-preserved-build-" + uuid4().hex,
    )
    assert created

    def archive():
        start.wait(timeout=10)
        return remove(value, manifest)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = [
            future.result(timeout=30) for future in (pool.submit(archive), pool.submit(archive))
        ]
    assert a == b
    assert value.service.list_recent_titled(actor=value.actor)[0] == ()
    assert value.service.list_recent(actor=value.actor)[0] == ()
    assert value.service.read(manifest.assembly_id, actor=value.actor) == manifest
    assert (
        build_service.get_build(build.build_id, actor=value.actor).assembly_revision_id
        == manifest.assembly_revision_id
    )
    with Session(value.engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(CuratedDocumentAssemblyPlacementRecord)
                .where(
                    CuratedDocumentAssemblyPlacementRecord.assembly_revision_id
                    == manifest.assembly_revision_id
                )
            )
            == 1
        )
        assert session.get(HwpxCuratedBuildRecord, build.build_id) is not None
        assert (
            session.get(ItemRecord, value.draft.placements[0].item_id).lifecycle_state == "ACTIVE"
        )
    # Removing a list entry must not strand a previously requested delivery.
    # Finish this synthetic output through its application so independent FIFO
    # suites do not accidentally claim the library fixture's pending build.
    completed = build_service.process_next()
    assert completed.build_id == build.build_id and completed.state == "SUCCEEDED"
    assert value.service.list_recent_titled(actor=value.actor)[0] == ()


def test_wrong_owner_stale_hash_revoked_role_and_key_reuse_do_not_remove(library):
    value = library
    first, other = create(value), create(value, "two")
    pin = CuratedDocumentAssemblyRemovalInput(
        assembly_revision_id=first.assembly_revision_id,
        manifest_sha256=first.manifest_sha256,
    )
    assert value.service.list_recent_titled(actor=value.peer)[0] == ()
    with pytest.raises(CuratedDocumentAssemblyError, match="NOT_FOUND"):
        value.service.remove_from_list(
            first.assembly_id, pin, actor=value.peer, idempotency_key="library-other-owner-key"
        )
    with pytest.raises(CuratedDocumentAssemblyError, match="POINTER_INVALID"):
        value.service.remove_from_list(
            first.assembly_id,
            pin.model_copy(update={"manifest_sha256": "sha256:" + "0" * 64}),
            actor=value.actor,
            idempotency_key="library-stale-hash-key",
        )
    remove(value, first)
    with pytest.raises(CuratedDocumentAssemblyError, match="IDEMPOTENCY_CONFLICT"):
        remove(value, other)
    with Session(value.engine) as session, session.begin():
        session.get(OperatorRoleAssignmentRecord, value.assignment).revoked_at = datetime.now(UTC)
    with pytest.raises(CuratedDocumentAssemblyError, match="PERMISSION_DENIED"):
        remove(value, other, "library-role-revoked-key")
    with Session(value.engine) as session:
        assert session.get(CuratedDocumentAssemblyRecord, other.assembly_id).removed_at is None


def test_terminal_removal_and_title_cannot_be_rewritten_or_lost_by_downgrade(library):
    value, manifest = library, create(library)
    remove(value, manifest)
    for change in (
        "title='rewrite'",
        "removed_at=NULL,removal_idempotency_key=NULL,removal_request_sha256=NULL",
    ):
        with pytest.raises(DBAPIError), value.engine.begin() as connection:
            connection.execute(
                text(
                    f"UPDATE curated_document_assemblies SET {change} WHERE assembly_id=:identity"
                ),
                {"identity": manifest.assembly_id},
            )
    with (
        value.engine.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="HISTORY_EXISTS"),
    ):
        migration().downgrade()
