"""Archive stage materializes only the verified selected bytes locally."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from eom_catalog_service.external_item_archive import inspect_external_item_archive
from eom_catalog_service.external_item_archive_staging import (
    ExternalItemStageError,
    plan_external_item_archive_batches,
    stage_external_item_archive_batch,
)
from eom_identifiers import sha256_file


def _archive(path: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("N제/문항_00042.hwp", bytes.fromhex("d0cf11e0a1b11ae1") + b"content")
        archive.writestr("N제/문항_00043.hwp", b"PK\x03\x04hwpx")
        archive.writestr("N제/readme.txt", b"unselected")


def test_stage_preserves_original_name_but_detects_actual_hwpx(tmp_path: Path) -> None:
    archive_path = tmp_path / "source.zip"
    _archive(archive_path)
    inventory = inspect_external_item_archive(archive_path)
    batches = plan_external_item_archive_batches(inventory)
    assert len(batches) == 1
    staged = stage_external_item_archive_batch(
        archive_path, inventory, batches[0], tmp_path / "stage"
    )
    assert len(staged.documents) == 2
    actual_hwpx = staged.documents[1]
    assert actual_hwpx.original_filename == "문항_00043.hwp"
    assert actual_hwpx.relative_path.endswith(".hwpx")
    assert actual_hwpx.media_type == "application/vnd.hancom.hwpx"
    assert sha256_file(staged.source_directory / actual_hwpx.relative_path) == actual_hwpx.sha256
    index = json.loads((staged.source_directory / staged.index_relative_path).read_text())
    assert index["archive_sha256"] == inventory.archive_sha256
    assert len(index["documents"]) == 2
    assert not (staged.source_directory / "readme.txt").exists()


def test_stage_rejects_changed_archive_before_materializing_documents(tmp_path: Path) -> None:
    archive_path = tmp_path / "source.zip"
    _archive(archive_path)
    inventory = inspect_external_item_archive(archive_path)
    with archive_path.open("ab") as output:
        output.write(b"changed")
    with pytest.raises(ExternalItemStageError) as captured:
        stage_external_item_archive_batch(
            archive_path, inventory, inventory.documents, tmp_path / "stage"
        )
    assert captured.value.code == "EXTERNAL_ITEM_STAGE_ARCHIVE_CHANGED"
    assert not list((tmp_path / "stage").glob("document-*"))
