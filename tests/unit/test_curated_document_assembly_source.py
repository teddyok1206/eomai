"""Catalog reauthorizes a source-only placement without inventing an Item revision."""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from typing import Any

import pytest
from eom_api_contracts.curated_document_assembly import ExternalSourcePlacement
from eom_catalog_service.curated_document_assembly_source import (
    CuratedDocumentAssemblySourceError,
    resolve_curated_external_document,
)


def _selection() -> ExternalSourcePlacement:
    return ExternalSourcePlacement(
        placement_kind="EXTERNAL_SOURCE_DOCUMENT",
        position=1,
        source_id="extitem_" + "1" * 32,
        source_revision_id="extitemrev_" + "2" * 32,
        observation_sha256="sha256:" + "3" * 64,
        edition=3,
        source_format="HWPX",
    )


def _rows() -> tuple[SimpleNamespace, ...]:
    selection = _selection()
    source_file_id = "sourcefile_" + "4" * 32
    sha256 = "sha256:" + "5" * 64
    media_type = "application/vnd.hancom.hwpx"
    return (
        SimpleNamespace(
            source_id=selection.source_id,
            current_revision_id=selection.source_revision_id,
            source_namespace="notion-integrated-science",
            external_number="10310",
        ),
        SimpleNamespace(
            revision_id=selection.source_revision_id,
            source_id=selection.source_id,
            observation_sha256=selection.observation_sha256,
            external_number="10310",
            import_id="extimport_" + "6" * 32,
            match_status="MATCHED_DETECTED_HWPX",
            selected_source_file_id=source_file_id,
        ),
        SimpleNamespace(
            import_id="extimport_" + "6" * 32,
            source_namespace="notion-integrated-science",
            state="COMPLETED",
        ),
        SimpleNamespace(
            source_revision_id=selection.source_revision_id,
            source_file_id=source_file_id,
            edition=3,
            match_status="MATCHED_DETECTED_HWPX",
            document_sha256=sha256,
        ),
        SimpleNamespace(
            source_file_id=source_file_id,
            artifact_id="artifact_" + "7" * 32,
            artifact_revision_id="rev_" + "8" * 32,
            relative_path="source/10310.hwp",
            media_type=media_type,
            sha256=sha256,
            size_bytes=24,
        ),
    )


class _Session:
    def __init__(self, row: tuple[SimpleNamespace, ...] | None) -> None:
        self.row = row
        self.locked = False

    def execute(self, statement: Any) -> _Session:
        self.locked = statement._for_update_arg is not None
        return self

    def one_or_none(self) -> tuple[SimpleNamespace, ...] | None:
        return self.row


class _Media:
    def __init__(self, row: tuple[SimpleNamespace, ...]) -> None:
        document = row[4]
        self.stream = BytesIO(b"example placeholder bytes")
        self.resolved = SimpleNamespace(
            source_file_id=document.source_file_id,
            artifact_id=document.artifact_id,
            artifact_revision_id=document.artifact_revision_id,
            member_path=document.relative_path,
            media_type=document.media_type,
            member=SimpleNamespace(
                stream=self.stream,
                sha256=document.sha256,
                content_length=document.size_bytes,
            ),
        )
        self.opened = False

    def open(self, query: Any) -> Any:
        assert query.source_revision_id == _selection().source_revision_id
        self.opened = True
        return self.resolved


def test_curated_source_resolves_current_final_edition_and_detected_format() -> None:
    row = _rows()
    session = _Session(row)
    media = _Media(row)

    resolved = resolve_curated_external_document(session, media, _selection())  # type: ignore[arg-type]

    # Runtime SELECT-only authority must not require PostgreSQL UPDATE privilege.
    assert not session.locked
    assert media.opened
    assert media.stream.closed
    assert resolved.external_number == "10310"
    assert resolved.source_format == "HWPX"
    assert resolved.document_artifact.media_type == "application/vnd.hancom.hwpx"
    assert resolved.document_artifact.member_path == "source/10310.hwp"


def test_curated_source_rejects_stale_or_changed_pointer_before_build() -> None:
    row = _rows()
    session = _Session(None)
    media = _Media(row)
    with pytest.raises(CuratedDocumentAssemblySourceError) as stale:
        resolve_curated_external_document(session, media, _selection())  # type: ignore[arg-type]
    assert stale.value.code == "CURATED_SOURCE_STALE"
    assert not media.opened

    row = _rows()
    row[1].observation_sha256 = "sha256:" + "f" * 64
    session = _Session(row)
    media = _Media(row)
    with pytest.raises(CuratedDocumentAssemblySourceError) as changed:
        resolve_curated_external_document(session, media, _selection())  # type: ignore[arg-type]
    assert changed.value.code == "CURATED_SOURCE_POINTER_INVALID"
    assert not media.opened

    row = _rows()
    row[3].match_status = "MATCHED"
    session = _Session(row)
    media = _Media(row)
    with pytest.raises(CuratedDocumentAssemblySourceError) as inconsistent:
        resolve_curated_external_document(session, media, _selection())  # type: ignore[arg-type]
    assert inconsistent.value.code == "CURATED_SOURCE_POINTER_INVALID"
    assert not media.opened

    row = _rows()
    session = _Session(row)
    media = _Media(row)
    media.resolved.member.sha256 = "sha256:" + "f" * 64
    with pytest.raises(CuratedDocumentAssemblySourceError) as mismatch:
        resolve_curated_external_document(session, media, _selection())  # type: ignore[arg-type]
    assert mismatch.value.code == "CURATED_SOURCE_POINTER_INVALID"
    assert media.stream.closed
