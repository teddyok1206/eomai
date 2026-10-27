"""The mixed selection composer preserves order and never trusts browser authority."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from eom_api_contracts.curated_document_assembly import (
    CuratedDocumentAssemblyDraftV1,
    ExternalSourcePlacement,
    PastExamItemPlacement,
    RegisteredItemPlacement,
)
from eom_catalog_contracts import (
    CuratedExternalDocumentPlacement,
    CuratedPastExamItemPlacement,
    CuratedRegisteredItemPlacement,
    OriginArtifactMemberPointer,
    validate_contract,
)
from eom_catalog_service import curated_document_assembly_resolution as resolution
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey


def _actor(*permissions: PermissionKey) -> ActorContext:
    return ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id="operator_" + "1" * 32,
        session_id="apisession_" + "2" * 32,
        request_id="curated-test-1",
        authentication_time=datetime(2026, 10, 27, 11, 0, tzinfo=UTC),
        permissions=frozenset(permissions),
        source=ActorSource.APPLICATION_API,
    )


def _draft() -> CuratedDocumentAssemblyDraftV1:
    graph_id = "graphrev_" + "a" * 32
    graph_hash = "sha256:" + "b" * 64
    return CuratedDocumentAssemblyDraftV1(
        schema_version="curated-document-assembly-draft/1.0",
        placements=(
            ExternalSourcePlacement(
                placement_kind="EXTERNAL_SOURCE_DOCUMENT",
                position=1,
                source_id="extitem_" + "2" * 32,
                source_revision_id="extitemrev_" + "3" * 32,
                observation_sha256="sha256:" + "4" * 64,
                edition=3,
                source_format="HWPX",
            ),
            RegisteredItemPlacement(
                placement_kind="REGISTERED_ITEM_REVISION",
                position=2,
                item_id="item_" + "5" * 32,
                item_revision_id="itemrev_" + "6" * 32,
                item_manifest_sha256="sha256:" + "7" * 64,
                graph_snapshot_revision_id=graph_id,
                graph_snapshot_sha256=graph_hash,
            ),
            ExternalSourcePlacement(
                placement_kind="EXTERNAL_SOURCE_DOCUMENT",
                position=3,
                source_id="extitem_" + "1" * 32,
                source_revision_id="extitemrev_" + "8" * 32,
                observation_sha256="sha256:" + "9" * 64,
                edition=2,
                source_format="HWP",
            ),
            PastExamItemPlacement(
                placement_kind="PAST_EXAM_ITEM_REVISION",
                position=4,
                item_id="item_" + "c" * 32,
                item_revision_id="itemrev_" + "d" * 32,
                item_manifest_sha256="sha256:" + "e" * 64,
                graph_snapshot_revision_id=graph_id,
                graph_snapshot_sha256=graph_hash,
            ),
        ),
    )


def _resolved_source(selection: ExternalSourcePlacement) -> CuratedExternalDocumentPlacement:
    media_type = (
        "application/vnd.hancom.hwpx"
        if selection.source_format == "HWPX"
        else "application/vnd.hancom.hwp"
    )
    return CuratedExternalDocumentPlacement(
        position=selection.position,
        source_id=selection.source_id,
        source_revision_id=selection.source_revision_id,
        external_number="10310" if selection.position == 1 else "10311",
        observation_sha256=selection.observation_sha256,
        edition=selection.edition,
        source_format=selection.source_format,
        source_file_id="sourcefile_" + "f" * 32,
        document_artifact=OriginArtifactMemberPointer(
            artifact_id="artifact_" + "1" * 32,
            artifact_revision_id="rev_" + "2" * 32,
            member_path=f"source/{selection.position}.hwp",
            schema_ref="eom://schemas/content-intake/source-file/1.0",
            media_type=media_type,
            sha256="sha256:" + "3" * 64,
        ),
        document_size_bytes=100,
    )


def _resolved_item(
    selection: RegisteredItemPlacement | PastExamItemPlacement,
) -> CuratedRegisteredItemPlacement | CuratedPastExamItemPlacement:
    if isinstance(selection, PastExamItemPlacement):
        return CuratedPastExamItemPlacement.model_validate(selection.model_dump(mode="json"))
    return CuratedRegisteredItemPlacement.model_validate(selection.model_dump(mode="json"))


def test_curated_mixed_manifest_preserves_display_order_and_pins_exact_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = _draft()
    calls: list[str] = []

    def resolve_items(_session: Any, selected: tuple[Any, ...]) -> tuple[Any, ...]:
        calls.append("items")
        assert [row.position for row in selected] == [2, 4]
        return tuple(_resolved_item(row) for row in selected)

    def resolve_source(_session: Any, _media: Any, selected: Any) -> Any:
        calls.append(selected.source_id)
        return _resolved_source(selected)

    monkeypatch.setattr(resolution, "resolve_curated_registered_items", resolve_items)
    monkeypatch.setattr(resolution, "resolve_curated_external_document", resolve_source)
    actor = _actor(
        PermissionKey.ITEM_READ,
        PermissionKey.DELIVERABLE_CREATE,
        PermissionKey.CONTENT_INTAKE_READ,
    )

    manifest = resolution.resolve_curated_document_assembly_manifest(
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        draft=draft,
        actor=actor,
        assembly_id="assembly_" + "4" * 32,
        assembly_revision_id="assemblyrev_" + "5" * 32,
        created_at=datetime(2026, 10, 27, 11, 36, tzinfo=UTC),
    )

    assert calls == ["items", "extitem_" + "1" * 32, "extitem_" + "2" * 32]
    assert [row.placement_kind for row in manifest.placements] == [
        "EXTERNAL_SOURCE_DOCUMENT",
        "REGISTERED_ITEM_REVISION",
        "EXTERNAL_SOURCE_DOCUMENT",
        "PAST_EXAM_ITEM_REVISION",
    ]
    assert [row.position for row in manifest.placements] == [1, 2, 3, 4]
    assert manifest.selection_sha256 == content_sha256(draft.model_dump(mode="json"))
    validate_contract("curated-document-assembly-manifest-v1", manifest.model_dump(mode="json"))


def test_curated_mixed_manifest_requires_actor_rights_before_resolving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def should_not_resolve(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("unauthorized source resolution")

    monkeypatch.setattr(resolution, "resolve_curated_registered_items", should_not_resolve)
    monkeypatch.setattr(resolution, "resolve_curated_external_document", should_not_resolve)
    common = {
        "draft": _draft(),
        "assembly_id": "assembly_" + "4" * 32,
        "assembly_revision_id": "assemblyrev_" + "5" * 32,
        "created_at": datetime(2026, 10, 27, 11, 36, tzinfo=UTC),
    }
    with pytest.raises(resolution.CuratedDocumentAssemblyResolutionError) as denied:
        resolution.resolve_curated_document_assembly_manifest(  # type: ignore[arg-type]
            None, None, actor=_actor(PermissionKey.ITEM_READ), **common
        )
    assert denied.value.code == "CURATED_ASSEMBLY_PERMISSION_DENIED"

    with pytest.raises(resolution.CuratedDocumentAssemblyResolutionError) as source_denied:
        resolution.resolve_curated_document_assembly_manifest(  # type: ignore[arg-type]
            None,
            None,
            actor=_actor(PermissionKey.ITEM_READ, PermissionKey.DELIVERABLE_CREATE),
            **common,
        )
    assert source_denied.value.code == "CURATED_SOURCE_PERMISSION_DENIED"


def test_curated_mixed_manifest_rejects_invalid_identity_before_source_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        resolution,
        "resolve_curated_registered_items",
        lambda *_args: pytest.fail("invalid identity reached source read"),
    )
    with pytest.raises(resolution.CuratedDocumentAssemblyResolutionError) as invalid:
        resolution.resolve_curated_document_assembly_manifest(  # type: ignore[arg-type]
            None,
            None,
            draft=_draft(),
            actor=_actor(
                PermissionKey.ITEM_READ,
                PermissionKey.DELIVERABLE_CREATE,
                PermissionKey.CONTENT_INTAKE_READ,
            ),
            assembly_id="bad-id",
            assembly_revision_id="assemblyrev_" + "5" * 32,
            created_at=datetime(2026, 10, 27, 11, 36),
        )
    assert invalid.value.code == "CURATED_ASSEMBLY_IDENTITY_INVALID"
