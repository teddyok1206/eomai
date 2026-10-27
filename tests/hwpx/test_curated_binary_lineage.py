from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from eom_hwpx_builder.content_team_exam_renderer import _merge_item_packages
from eom_hwpx_builder.curated_binary_lineage import remap_curated_binary_lineage
from eom_hwpx_builder.errors import HwpxError

from tests.hwpx.helpers import png_bytes, synthetic_parts, write_hwpx


def _replace_member(source: Path, target: Path, member: str, before: bytes, after: bytes) -> None:
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, "w") as output:
        for info in original.infolist():
            payload = original.read(info)
            if info.filename == member:
                assert payload.count(before) == 1
                payload = payload.replace(before, after)
            output.writestr(info, payload)


def _sources_and_candidate(tmp_path: Path) -> tuple[Path, Path, Path]:
    first = write_hwpx(tmp_path / "first.hwpx", synthetic_parts(reference_image=png_bytes()))
    second = write_hwpx(
        tmp_path / "second.hwpx", synthetic_parts(reference_image=png_bytes(output=True))
    )
    correct = tmp_path / "build/correct.hwpx"
    _merge_item_packages((first, second), correct)
    return first, second, correct


def test_curated_lineage_restores_the_second_sources_image_after_manifest_id_collision(
    tmp_path: Path,
) -> None:
    first, second, correct = _sources_and_candidate(tmp_path)
    wrong = tmp_path / "wrong.hwpx"
    _replace_member(
        correct,
        wrong,
        "Contents/section1.xml",
        b'binaryItemIDRef="eomExam002Binary000"',
        b'binaryItemIDRef="eomExam001Binary000"',
    )

    repaired = tmp_path / "repaired.hwpx"
    changes = remap_curated_binary_lineage((first, second), wrong, repaired)

    assert len(changes) == 1
    assert changes[0].position == 2
    assert changes[0].previous_manifest_id == "eomExam001Binary000"
    assert changes[0].corrected_manifest_id == "eomExam002Binary000"
    with zipfile.ZipFile(repaired) as package:
        assert b'binaryItemIDRef="eomExam002Binary000"' in package.read("Contents/section1.xml")
        assert package.read("BinData/item-002-000.png") == png_bytes(output=True)

    again = tmp_path / "repaired-again.hwpx"
    assert remap_curated_binary_lineage((first, second), repaired, again) == ()


def test_curated_lineage_rejects_missing_exact_source_image(tmp_path: Path) -> None:
    first, second, correct = _sources_and_candidate(tmp_path)
    changed_media = tmp_path / "changed-media.hwpx"
    _replace_member(
        correct,
        changed_media,
        "BinData/item-002-000.png",
        png_bytes(output=True),
        png_bytes(dimensions=(802, 500)),
    )

    with pytest.raises(HwpxError, match="source media is not embedded"):
        remap_curated_binary_lineage((first, second), changed_media, tmp_path / "not-created.hwpx")
    assert not (tmp_path / "not-created.hwpx").exists()


def test_curated_lineage_rejects_changed_reference_node_order(tmp_path: Path) -> None:
    first, second, correct = _sources_and_candidate(tmp_path)
    changed_shape = tmp_path / "changed-shape.hwpx"
    _replace_member(
        correct,
        changed_shape,
        "Contents/section1.xml",
        b'<hp:pic id="pic1"',
        b'<hp:tbl id="pic1"',
    )

    with pytest.raises(HwpxError, match="binary reference order differs"):
        remap_curated_binary_lineage((first, second), changed_shape, tmp_path / "not-created.hwpx")


def test_curated_lineage_rejects_section_count_mismatch(tmp_path: Path) -> None:
    first, second, correct = _sources_and_candidate(tmp_path)
    with pytest.raises(HwpxError, match="section count differs"):
        remap_curated_binary_lineage((first,), correct, tmp_path / "not-created.hwpx")
    assert second.exists()


def test_curated_lineage_never_overwrites_an_existing_candidate(tmp_path: Path) -> None:
    first, second, correct = _sources_and_candidate(tmp_path)
    output = tmp_path / "already-present.hwpx"
    output.write_bytes(b"immutable existing result")

    with pytest.raises(HwpxError, match="curated inputs are invalid"):
        remap_curated_binary_lineage((first, second), correct, output)
    assert output.read_bytes() == b"immutable existing result"
