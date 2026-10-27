"""Workbook staging is an exact temporary materialization, not a new canonical file."""

from __future__ import annotations

from pathlib import Path

import pytest
from eom_catalog_service.external_item_archive_intake import (
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
