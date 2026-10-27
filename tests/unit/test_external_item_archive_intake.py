"""Workbook staging is an exact temporary materialization, not a new canonical file."""

from __future__ import annotations

from pathlib import Path

import pytest
from eom_catalog_service.external_item_archive_intake import (
    ExternalItemArchiveIntakeService,
    ExternalItemIntakeError,
    _copy_exact_regular_file,
)
from eom_identifiers import sha256_file


def test_workbook_local_copy_requires_exact_hash_and_rejects_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"test workbook transport bytes")
    expected = sha256_file(source)
    target = tmp_path / "copy.xlsx"
    _copy_exact_regular_file(source, target, expected)
    assert sha256_file(target) == expected

    link = tmp_path / "link.xlsx"
    link.symlink_to(source)
    with pytest.raises(ExternalItemIntakeError) as captured:
        _copy_exact_regular_file(link, tmp_path / "unsafe.xlsx", expected)
    assert captured.value.code == "EXTERNAL_ITEM_WORKBOOK_UNAVAILABLE"

    with pytest.raises(ExternalItemIntakeError) as captured:
        _copy_exact_regular_file(source, tmp_path / "wrong.xlsx", "sha256:" + "0" * 64)
    assert captured.value.code == "EXTERNAL_ITEM_WORKBOOK_CHANGED"


def test_external_archive_marks_owner_unverified_not_placeholder(tmp_path: Path) -> None:
    workbook = tmp_path / "original.xlsx"
    workbook.write_bytes(b"pinned external workbook")
    received: dict[str, object] = {}

    class StopAfterDeclaration:
        def create(self, _source_directory: Path, **kwargs: object) -> None:
            received.update(kwargs)
            raise RuntimeError("declaration captured before any commit")

    service = object.__new__(ExternalItemArchiveIntakeService)
    service.intake = StopAfterDeclaration()  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="declaration captured"):
        service.commit_workbook(
            workbook, expected_sha256=sha256_file(workbook), received_by="guiadmin"
        )
    assert received["received_by"] == "guiadmin"
    assert received["source_owner_type"] == "other"
    assert received["source_owner_reference"] == "notion-export-owner-unverified"
