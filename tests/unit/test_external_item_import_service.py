"""Catalog import stores source-only revisions and rejects stale Artifact metadata."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from eom_catalog_contracts import ExternalItemImportManifest
from eom_catalog_service.external_item_import_service import (
    ExternalItemImportError,
    _publish_rows,
    _resolve_source_files,
)
from eom_catalog_service.external_item_models import (
    ExternalItemEditionDocumentRecord,
    ExternalItemImportRecord,
    ExternalItemSourceRecord,
    ExternalItemSourceRevisionRecord,
)
from eom_identifiers import content_sha256

from tests.unit.test_external_item_import_contract import _manifest


def _source_pointer_fixture(*, wrong_document_hash: bool = False):
    manifest = ExternalItemImportManifest.model_validate(_manifest())
    file_sha = "sha256:" + ("0" if wrong_document_hash else "9") * 64
    workbook = SimpleNamespace(
        source_file_id=manifest.workbook_source_file_id,
        intake_batch_id="intake_w",
        original_filename="source.xlsx",
        relative_path="source/source.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes=100,
        sha256=manifest.workbook_sha256,
        artifact_id=manifest.workbook_artifact_id,
        artifact_revision_id=manifest.workbook_artifact_revision_id,
    )
    selected = SimpleNamespace(
        source_file_id=manifest.rows[0].selected_source_file_id,
        intake_batch_id="intake_d",
        original_filename="문항_00042.hwp",
        relative_path="source/document.hwp",
        media_type="application/vnd.hancom.hwpx",
        size_bytes=200,
        sha256=file_sha,
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
    )
    sources = [workbook, selected]
    batches = []
    revisions = []
    artifacts = []
    jobs = []
    for index, source in enumerate(sources):
        content_hash = "sha256:" + str(index + 1) * 64
        artifact_manifest = {
            "manifest_version": "catalog-file-set/1.0",
            "artifact_type": "content-intake-source",
            "files": [
                {
                    "file_name": source.relative_path,
                    "sha256": source.sha256,
                    "bytes": source.size_bytes,
                    "media_type": source.media_type,
                }
            ],
        }
        batches.append(
            SimpleNamespace(
                intake_batch_id=source.intake_batch_id,
                state="ANALYSIS_PENDING",
                source_manifest_artifact_id=source.artifact_id,
                source_manifest_artifact_revision_id=source.artifact_revision_id,
                source_manifest_sha256=content_hash,
            )
        )
        revisions.append(
            SimpleNamespace(
                revision_id=source.artifact_revision_id,
                logical_artifact_id=source.artifact_id,
                job_id=f"job_{index}",
                approved=True,
                content_hash=content_hash,
                manifest_hash=content_sha256(artifact_manifest),
                manifest=artifact_manifest,
            )
        )
        artifacts.append(
            SimpleNamespace(
                logical_artifact_id=source.artifact_id,
                job_id=f"job_{index}",
                approved=True,
                artifact_type="content-intake-source",
            )
        )
        jobs.append(
            SimpleNamespace(
                job_id=f"job_{index}",
                status="SUCCEEDED",
                logical_artifact_id=source.artifact_id,
                revision_id=source.artifact_revision_id,
            )
        )
    session = MagicMock()
    session.scalars.side_effect = [sources, batches, revisions, artifacts, jobs]
    return manifest, session


def test_source_pointer_check_requires_exact_workbook_and_document_artifacts() -> None:
    manifest, session = _source_pointer_fixture()
    result = _resolve_source_files(session, manifest)
    assert set(result) == {
        manifest.workbook_source_file_id,
        manifest.rows[0].selected_source_file_id,
    }
    assert session.scalars.call_count == 5


def test_source_pointer_check_fails_closed_on_selected_hash_mismatch() -> None:
    manifest, session = _source_pointer_fixture(wrong_document_hash=True)
    with pytest.raises(ExternalItemImportError) as captured:
        _resolve_source_files(session, manifest)
    assert captured.value.code == "EXTERNAL_ITEM_DOCUMENT_POINTER_INVALID"


def test_atomic_publication_creates_only_external_source_revisions() -> None:
    manifest = ExternalItemImportManifest.model_validate(_manifest())
    session = MagicMock()
    session.scalars.side_effect = [[], []]
    _publish_rows(session, manifest)
    imported = session.add.call_args_list[0].args[0]
    source = session.add.call_args_list[1].args[0]
    revision = session.add_all.call_args.args[0][0]
    edition = session.add_all.call_args.args[0][1]
    assert isinstance(imported, ExternalItemImportRecord)
    assert imported.mapping_document["mapping_revision_id"] == manifest.mapping.mapping_revision_id
    assert isinstance(source, ExternalItemSourceRecord)
    assert isinstance(revision, ExternalItemSourceRevisionRecord)
    assert isinstance(edition, ExternalItemEditionDocumentRecord)
    assert edition.source_file_id == revision.selected_source_file_id
    assert revision.external_number == "00042"
    assert revision.selected_source_file_id == manifest.rows[0].selected_source_file_id
    assert source.current_revision_id == revision.revision_id
    assert revision.revision_number == 1
