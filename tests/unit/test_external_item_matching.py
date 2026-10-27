"""External Item proposals must preserve editorial and physical-format meaning."""

from __future__ import annotations

from eom_catalog_contracts import EXTERNAL_ITEM_COLUMNS, ExternalItemCellObservation
from eom_catalog_service.external_item_archive import (
    ExternalItemArchiveInventory,
    ExternalItemDocumentMember,
)
from eom_catalog_service.external_item_matching import (
    ExternalItemMatchStatus,
    propose_external_item_edition_links,
    propose_external_item_links,
)
from eom_catalog_service.external_item_xlsx import DecodedExternalItemRow


def _row(
    number: str = "00042", *, second: str = "", third: str = "", rejected: str = "No"
) -> DecodedExternalItemRow:
    values = {"U": number, "M": second, "N": third, "X": rejected}
    return DecodedExternalItemRow(
        row_number=2,
        external_number=number,
        cells=tuple(
            ExternalItemCellObservation(
                column=column,
                present=column in values,
                cell_type="s" if column in values else None,
                raw_text=values.get(column, ""),
            )
            for column in EXTERNAL_ITEM_COLUMNS
        ),
    )


def _document(
    *,
    name: str = "N제/2025_기구_00042.hwp",
    sha: str = "sha256:" + "a" * 64,
    detected: str = "HWP_BINARY",
) -> ExternalItemDocumentMember:
    return ExternalItemDocumentMember(
        member_name=name,
        display_filename=name.rsplit("/", 1)[-1],
        external_number="00042",
        declared_format="HWP",
        detected_format=detected,
        size_bytes=12,
        sha256=sha,
    )


def _inventory(*documents: ExternalItemDocumentMember) -> ExternalItemArchiveInventory:
    return ExternalItemArchiveInventory(
        archive_sha256="sha256:" + "f" * 64,
        archive_size_bytes=100,
        total_member_count=len(documents),
        skipped_member_count=0,
        documents=documents,
    )


def test_third_edition_wins_and_double_encoded_link_matches_numbered_file() -> None:
    row = _row(
        second="N제/old_00042.hwp",
        third="N%25EC%25A0%259C/2025_%25EA%25B8%25B0%25EA%25B5%25AC.hwp",
    )
    result = propose_external_item_links((row,), _inventory(_document()))[0]
    assert result.status == ExternalItemMatchStatus.MATCHED
    assert result.final_edition == 3
    assert result.display_filename == "2025_기구.hwp"
    assert result.selected_member is not None


def test_second_edition_only_when_third_absent_and_not_rejected() -> None:
    row = _row(second="N제/2025_기구 1.hwp")
    result = propose_external_item_links((row,), _inventory(_document()))[0]
    assert result.status == ExternalItemMatchStatus.MATCHED
    assert result.final_edition == 2
    assert result.display_filename == "2025_기구 1.hwp"
    rejected = propose_external_item_links(
        (_row(second="N제/2025_기구.hwp", rejected="Yes"),), _inventory(_document())
    )[0]
    assert rejected.status == ExternalItemMatchStatus.REJECTED
    assert rejected.selected_member is None


def test_same_bytes_duplicate_is_deterministic_but_different_bytes_conflict() -> None:
    first = _document(name="N제/B/2025_기구_00042.hwp")
    second = _document(name="N제/A/2025_기구_00042.hwp")
    row = _row(third="N제/2025_기구.hwp")
    result = propose_external_item_links((row,), _inventory(first, second))[0]
    assert result.status == ExternalItemMatchStatus.MATCHED_IDENTICAL_COPIES
    assert result.selected_member == second
    conflict = propose_external_item_links(
        (row,), _inventory(first, _document(name=second.member_name, sha="sha256:" + "b" * 64))
    )[0]
    assert conflict.status == ExternalItemMatchStatus.CONTENT_CONFLICT
    assert conflict.selected_member is None


def test_older_number_and_parenthesized_copy_are_only_filename_annotations() -> None:
    original = _document(name="N제/A/2025_기구_12345_00042.hwp")
    copy = _document(name="N제/B/2025_기구 (2)_12345_00042.hwp")
    row = _row(third="N제/2025_기구.hwp")
    result = propose_external_item_links((row,), _inventory(original, copy))[0]
    assert result.status == ExternalItemMatchStatus.MATCHED_IDENTICAL_COPIES
    assert result.selected_member == original


def test_hwp_extension_with_hwpx_content_uses_detected_hwpx() -> None:
    row = _row(third="N제/2025_기구.hwp")
    result = propose_external_item_links((row,), _inventory(_document(detected="HWPX_PACKAGE")))[0]
    assert result.status == ExternalItemMatchStatus.MATCHED_DETECTED_HWPX
    assert result.selected_member is not None
    assert result.selected_member.detected_format == "HWPX_PACKAGE"
    assert result.display_filename == "2025_기구.hwp"


def test_missing_unsupported_and_unsafe_links_are_not_silently_substituted() -> None:
    document = _document()
    for link, expected in (
        ("N제/2025_기구.ai", ExternalItemMatchStatus.LINK_UNSUPPORTED),
        ("../2025_기구.hwp", ExternalItemMatchStatus.LINK_UNSUPPORTED),
        ("N제/다른파일.hwp", ExternalItemMatchStatus.NAME_MISMATCH),
    ):
        result = propose_external_item_links((_row(third=link),), _inventory(document))[0]
        assert result.status == expected
        assert result.selected_member is None


def test_all_editorial_links_are_observed_even_when_row_is_rejected() -> None:
    row = _row(
        second="N제/2025_기구.hwp",
        third="N제/다른파일.hwp",
        rejected="Yes",
    )
    links = propose_external_item_edition_links((row,), _inventory(_document()))
    assert [(link.edition, link.status) for link in links] == [
        (2, ExternalItemMatchStatus.MATCHED),
        (3, ExternalItemMatchStatus.NAME_MISMATCH),
    ]
    assert propose_external_item_links((row,), _inventory(_document()))[0].status == "REJECTED"
