"""Mixed Assembly storage remains separate from Item-only examination placements."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import eom_catalog_service.external_item_models
import eom_catalog_service.knowledge_graph_models
import eom_catalog_service.models  # noqa: F401
import pytest
from eom_api_contracts.curated_document_assembly import (
    CuratedDocumentAssemblyDraftV1,
    ExternalSourcePlacement,
    PastExamItemPlacement,
    RegisteredItemPlacement,
)
from eom_catalog_contracts import CuratedDocumentAssemblyManifestV1
from eom_catalog_service import curated_document_assembly_service as service_module
from eom_catalog_service.curated_document_assembly_models import (
    CuratedDocumentAssemblyPlacementRecord,
    CuratedDocumentAssemblyRecord,
    CuratedDocumentAssemblyRevisionRecord,
)
from eom_catalog_service.curated_document_assembly_service import (
    CuratedDocumentAssemblyError,
    CuratedDocumentAssemblyService,
    _stable_id,
)
from eom_identifiers import content_sha256
from eom_operator_identity import PermissionKey
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from tests.unit.test_curated_document_assembly_manifest import _manifest
from tests.unit.test_curated_document_assembly_resolution import _actor


def test_curated_storage_has_pinned_revisions_without_binary_payloads() -> None:
    tables = (
        CuratedDocumentAssemblyRecord.__table__,
        CuratedDocumentAssemblyRevisionRecord.__table__,
        CuratedDocumentAssemblyPlacementRecord.__table__,
    )
    assert {table.name for table in tables} == {
        "curated_document_assemblies",
        "curated_document_assembly_revisions",
        "curated_document_assembly_placements",
    }
    assert all(
        "BYTEA" not in str(CreateTable(table).compile(dialect=postgresql.dialect()))
        for table in tables
    )
    recent = next(
        index
        for index in CuratedDocumentAssemblyRecord.__table__.indexes
        if index.name == "ix_curated_document_owner_recent"
    )
    recent_sql = str(CreateIndex(recent).compile(dialect=postgresql.dialect()))
    assert "created_by, created_at DESC, assembly_id DESC" in recent_sql
    revision_uniques = {
        tuple(constraint.columns.keys())
        for constraint in CuratedDocumentAssemblyRevisionRecord.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("created_by", "idempotency_key") in revision_uniques
    assert ("assembly_id", "assembly_revision_id") in revision_uniques
    assert any(
        constraint.name == "fk_curated_document_assembly_current_revision"
        and len(constraint.elements) == 2
        for constraint in CuratedDocumentAssemblyRecord.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    )
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in CuratedDocumentAssemblyPlacementRecord.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "source_file_id IS NOT NULL" in checks["ck_curated_placement_pointer_shape"]
    assert "item_revision_id IS NOT NULL" in checks["ck_curated_placement_pointer_shape"]


class _Session:
    def __init__(self, rows: tuple[CuratedDocumentAssemblyPlacementRecord, ...]) -> None:
        self.rows = rows

    def scalars(self, _statement: Any) -> tuple[CuratedDocumentAssemblyPlacementRecord, ...]:
        return self.rows

    def get(self, _record_type: type[Any], _key: str) -> Any:
        return self.aggregate


def test_curated_placement_index_matches_immutable_manifest_exactly() -> None:
    manifest = CuratedDocumentAssemblyManifestV1.model_validate(_manifest())
    rows = CuratedDocumentAssemblyService._placement_rows(manifest)
    assert len(rows) == 3
    assert [row.placement_kind for row in rows] == [
        "EXTERNAL_SOURCE_DOCUMENT",
        "PAST_EXAM_ITEM_REVISION",
        "REGISTERED_ITEM_REVISION",
    ]
    assert rows[0].source_revision_id == manifest.placements[0].source_revision_id
    assert rows[0].item_revision_id is None
    assert rows[1].item_revision_id == manifest.placements[1].item_revision_id
    assert rows[1].source_id is None
    assert CuratedDocumentAssemblyService._placements_match(  # type: ignore[arg-type]
        _Session(rows), manifest
    )

    rows[1].item_revision_id = "itemrev_" + "f" * 32
    assert not CuratedDocumentAssemblyService._placements_match(  # type: ignore[arg-type]
        _Session(rows), manifest
    )


def test_curated_replay_checks_request_permissions_and_placement_projection() -> None:
    value = _manifest()
    placements = value["placements"]
    assert isinstance(placements, list)
    draft = CuratedDocumentAssemblyDraftV1(
        schema_version="curated-document-assembly-draft/1.0",
        placements=(
            ExternalSourcePlacement.model_validate(
                {name: placements[0][name] for name in ExternalSourcePlacement.model_fields}
            ),
            PastExamItemPlacement.model_validate(
                {name: placements[1][name] for name in PastExamItemPlacement.model_fields}
            ),
            RegisteredItemPlacement.model_validate(
                {name: placements[2][name] for name in RegisteredItemPlacement.model_fields}
            ),
        ),
    )
    actor = _actor(
        PermissionKey.ITEM_READ,
        PermissionKey.DELIVERABLE_CREATE,
        PermissionKey.CONTENT_INTAKE_READ,
    )
    value["selection_sha256"] = content_sha256(draft.model_dump(mode="json"))
    value["created_by"] = actor.actor_id
    identity = {"actor_id": actor.actor_id, "idempotency_key": "test-replay-key"}
    value["assembly_id"] = _stable_id("assembly_", identity)
    value["assembly_revision_id"] = _stable_id("assemblyrev_", {**identity, "revision": "1"})
    value["manifest_sha256"] = content_sha256(
        {key: field for key, field in value.items() if key != "manifest_sha256"}
    )
    manifest = CuratedDocumentAssemblyManifestV1.model_validate(value)
    request_sha256 = "sha256:" + "a" * 64
    existing = SimpleNamespace(
        request_sha256=request_sha256,
        selection_sha256=manifest.selection_sha256,
        canonical_document=manifest.model_dump(mode="json"),
        manifest_sha256=manifest.manifest_sha256,
        assembly_id=manifest.assembly_id,
        assembly_revision_id=manifest.assembly_revision_id,
        created_at=manifest.created_at,
        revision_state="INPUT_PINNED",
        idempotency_key="test-replay-key",
        created_by=actor.actor_id,
        revision_number=1,
        previous_revision_id=None,
    )
    session = _Session(CuratedDocumentAssemblyService._placement_rows(manifest))
    session.aggregate = SimpleNamespace(created_by=actor.actor_id)
    assert (
        CuratedDocumentAssemblyService._replay(  # type: ignore[arg-type]
            session, existing, draft, actor, request_sha256
        )
        == manifest
    )

    session.rows[1].item_revision_id = "itemrev_" + "f" * 32
    with pytest.raises(CuratedDocumentAssemblyError) as corrupted:
        CuratedDocumentAssemblyService._replay(  # type: ignore[arg-type]
            session, existing, draft, actor, request_sha256
        )
    assert corrupted.value.code == "CURATED_ASSEMBLY_REPLAY_POINTER_INVALID"

    with pytest.raises(CuratedDocumentAssemblyError) as conflict:
        CuratedDocumentAssemblyService._replay(  # type: ignore[arg-type]
            session, existing, draft, actor, "sha256:" + "f" * 64
        )
    assert conflict.value.code == "CURATED_ASSEMBLY_IDEMPOTENCY_CONFLICT"


def test_curated_create_uses_current_operator_authority_not_stale_api_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = _actor(PermissionKey.ITEM_READ)

    class _OperatorSession:
        operator = SimpleNamespace(status="ACTIVE", deleted_at=None, must_change_password=False)

        def get(self, _record_type: type[Any], _key: str) -> Any:
            return self.operator

    session = _OperatorSession()
    permissions = frozenset({PermissionKey.ITEM_READ, PermissionKey.DELIVERABLE_CREATE})
    monkeypatch.setattr(service_module, "effective_permissions", lambda _session, _id: permissions)
    refreshed = CuratedDocumentAssemblyService._authorized_actor(  # type: ignore[arg-type]
        session, actor
    )
    assert refreshed.permissions == permissions
    assert actor.permissions == frozenset({PermissionKey.ITEM_READ})

    session.operator.must_change_password = True
    with pytest.raises(CuratedDocumentAssemblyError, match="CURATED_ASSEMBLY_PERMISSION_DENIED"):
        CuratedDocumentAssemblyService._authorized_actor(  # type: ignore[arg-type]
            session, actor
        )


def test_curated_read_rechecks_owner_permissions_hash_and_placement_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = _actor(PermissionKey.ITEM_READ, PermissionKey.CONTENT_INTAKE_READ)
    value = _manifest()
    value["created_by"] = actor.actor_id
    value["manifest_sha256"] = content_sha256(
        {key: field for key, field in value.items() if key != "manifest_sha256"}
    )
    manifest = CuratedDocumentAssemblyManifestV1.model_validate(value)
    aggregate = SimpleNamespace(
        assembly_id=manifest.assembly_id,
        current_revision_id=manifest.assembly_revision_id,
        created_by=actor.actor_id,
    )
    revision = SimpleNamespace(
        assembly_id=manifest.assembly_id,
        assembly_revision_id=manifest.assembly_revision_id,
        created_by=actor.actor_id,
        revision_state="INPUT_PINNED",
        canonical_document=manifest.model_dump(mode="json"),
        created_at=manifest.created_at,
        manifest_sha256=manifest.manifest_sha256,
        selection_sha256=manifest.selection_sha256,
    )

    class _ReadSession(_Session):
        def __enter__(self) -> _ReadSession:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get(self, record_type: type[Any], _key: str) -> Any:
            return {
                CuratedDocumentAssemblyRecord: aggregate,
                CuratedDocumentAssemblyRevisionRecord: revision,
            }[record_type]

    session = _ReadSession(CuratedDocumentAssemblyService._placement_rows(manifest))
    service = object.__new__(CuratedDocumentAssemblyService)
    service.sessions = lambda: session  # type: ignore[method-assign]
    monkeypatch.setattr(
        CuratedDocumentAssemblyService,
        "_authorized_actor",
        staticmethod(lambda _session, _actor: actor),
    )
    assert service.read(manifest.assembly_id, actor=actor) == manifest

    aggregate.created_by = "operator_" + "f" * 32
    with pytest.raises(CuratedDocumentAssemblyError, match="CURATED_ASSEMBLY_NOT_FOUND"):
        service.read(manifest.assembly_id, actor=actor)
    aggregate.created_by = actor.actor_id

    revision.canonical_document = {
        **revision.canonical_document,
        "selection_sha256": "sha256:" + "0" * 64,
    }
    with pytest.raises(CuratedDocumentAssemblyError, match="CURATED_ASSEMBLY_POINTER_INVALID"):
        service.read(manifest.assembly_id, actor=actor)
    revision.canonical_document = manifest.model_dump(mode="json")

    session.rows[0].source_revision_id = "extitemrev_" + "f" * 32
    with pytest.raises(CuratedDocumentAssemblyError, match="CURATED_ASSEMBLY_POINTER_INVALID"):
        service.read(manifest.assembly_id, actor=actor)


def test_curated_recent_list_is_owner_scoped_keyset_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = _actor(PermissionKey.ITEM_READ)
    manifest = CuratedDocumentAssemblyManifestV1.model_validate(_manifest())
    captured: list[object] = []

    class _ListSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, statement):
            captured.append(statement)
            return SimpleNamespace(
                all=lambda: [
                    (
                        manifest.assembly_id,
                        manifest.assembly_revision_id,
                        manifest.created_at,
                        manifest.manifest_sha256,
                        "INPUT_PINNED",
                        actor.actor_id,
                        len(manifest.placements),
                    ),
                    (
                        "assembly_" + "f" * 32,
                        "assemblyrev_" + "f" * 32,
                        manifest.created_at,
                        manifest.manifest_sha256,
                        "INPUT_PINNED",
                        actor.actor_id,
                        1,
                    ),
                ]
            )

    service = object.__new__(CuratedDocumentAssemblyService)
    service.sessions = lambda: _ListSession()  # type: ignore[method-assign]
    monkeypatch.setattr(
        CuratedDocumentAssemblyService,
        "_authorized_actor",
        staticmethod(lambda _session, _actor: actor),
    )
    values, cursor = service.list_recent(actor=actor, limit=1)
    assert len(values) == 1 and values[0].assembly_id == manifest.assembly_id
    assert cursor is not None and cursor.endswith("|" + manifest.assembly_id)
    query = str(
        captured[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert f"created_by = '{actor.actor_id}'" in query
    assert "jsonb_array_length" in query
    assert "ORDER BY" in query and "DESC" in query
    service.list_recent(actor=actor, limit=1, cursor=cursor)
    with pytest.raises(CuratedDocumentAssemblyError, match="CURATED_ASSEMBLY_LIST_INVALID"):
        service.list_recent(actor=actor, cursor="not-a-cursor")
