"""ZIP transport inventory is bounded and never extracts untrusted entries."""

from __future__ import annotations

import stat
import unicodedata
import zipfile
from pathlib import Path

import pytest
from eom_catalog_service.external_item_archive import (
    ExternalItemArchiveError,
    _display_filename,
    inspect_external_item_archive,
)


def _archive(path: Path, *, duplicate: bool = False, unsafe: bool = False) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("N제/문항_00042.hwp", bytes.fromhex("d0cf11e0a1b11ae1") + b"content")
        archive.writestr("N제/문항_00043.hwpx", b"PK\x03\x04rest")
        archive.writestr("__MACOSX/N제/._문항_00042.hwp", b"mac metadata")
        archive.writestr("N제/non-document.svg", b"<svg/>")
        if duplicate:
            archive.writestr("N제/문항_00042.hwp", b"different")
        if unsafe:
            member = zipfile.ZipInfo("../문항_00044.hwp")
            member.create_system = 3
            member.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(member, b"outside")


def test_archive_inventory_only_hashes_selected_documents(tmp_path: Path) -> None:
    path = tmp_path / "sources.zip"
    _archive(path)
    result = inspect_external_item_archive(path)
    assert result.total_member_count == 4
    assert result.skipped_member_count == 2
    assert tuple(doc.external_number for doc in result.documents) == ("00042", "00043")
    assert tuple(doc.detected_format for doc in result.documents) == ("HWP_BINARY", "HWPX_PACKAGE")
    assert result.documents[0].display_filename == "문항_00042.hwp"
    assert result.documents[0].sha256.startswith("sha256:")
    assert inspect_external_item_archive(path, expected_sha256=result.archive_sha256) == result


@pytest.mark.parametrize(
    ("option", "code"),
    [
        ({"duplicate": True}, "EXTERNAL_ITEM_ARCHIVE_MEMBER_UNSAFE"),
        ({"unsafe": True}, "EXTERNAL_ITEM_ARCHIVE_MEMBER_UNSAFE"),
    ],
)
def test_archive_rejects_ambiguous_selected_member(
    tmp_path: Path, option: dict[str, bool], code: str
) -> None:
    path = tmp_path / "sources.zip"
    _archive(path, **option)
    with pytest.raises(ExternalItemArchiveError) as captured:
        inspect_external_item_archive(path)
    assert captured.value.code == code


def test_archive_requires_exact_envelope_hash_and_rejects_symlink(tmp_path: Path) -> None:
    path = tmp_path / "sources.zip"
    _archive(path)
    with pytest.raises(ExternalItemArchiveError) as captured:
        inspect_external_item_archive(path, expected_sha256="sha256:" + "0" * 64)
    assert captured.value.code == "EXTERNAL_ITEM_ARCHIVE_HASH_MISMATCH"

    link = tmp_path / "link.zip"
    link.symlink_to(path)
    with pytest.raises(ExternalItemArchiveError) as captured:
        inspect_external_item_archive(link)
    assert captured.value.code == "EXTERNAL_ITEM_ARCHIVE_FILE_INVALID"


def test_numbered_prefix_does_not_hide_five_digit_suffix(tmp_path: Path) -> None:
    path = tmp_path / "sources.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("N제/2025_00044.hwp", bytes.fromhex("d0cf11e0a1b11ae1") + b"body")
    result = inspect_external_item_archive(path)
    assert tuple(doc.external_number for doc in result.documents) == ("00044",)


def test_cp437_decoded_utf8_filename_is_recovered_only_for_display() -> None:
    broken = unicodedata.normalize("NFD", "문항_00042.hwp").encode("utf-8").decode("cp437")
    assert _display_filename(broken, utf8_flag=False) == "문항_00042.hwp"
    assert _display_filename("plain_00042.hwp", utf8_flag=False) == "plain_00042.hwp"
