"""Manager checks the actual mixed output independently of Builder reports."""

import zipfile

import pytest
from eom_hwpx_builder.curated_renderer import render_curated_workspace
from eom_hwpx_contracts import parse_content_team_markdown, parse_content_team_markdown_v2
from eom_hwpx_contracts.curated_mixed import CuratedEditorialSegment
from eom_hwpx_manager.content_team_output_acceptance import ContentTeamOutputExpectation
from eom_hwpx_manager.curated_materialization import CuratedMaterialization
from eom_hwpx_manager.curated_output_acceptance import verify_curated_output
from eom_hwpx_manager.errors import HwpxManagerError
from eom_identifiers import sha256_bytes

from tests.hwpx import test_curated_mixed_renderer as fixtures

handoff_bytes = fixtures.handoff_bytes
stage_mixed = fixtures.stage_mixed


def render(root, handoff):
    request, canonical = stage_mixed(root, handoff)
    editorial = []
    for segment in request.segments:
        if not isinstance(segment, CuratedEditorialSegment):
            continue
        parser = (
            parse_content_team_markdown if segment.position == 4 else parse_content_team_markdown_v2
        )
        editorial.append(
            ContentTeamOutputExpectation(
                position=segment.position,
                item_revision_id=segment.item_revision_id,
                draft=parser((root / segment.markdown_file).read_bytes()),
                images=tuple(image.binding for image in segment.images),
            )
        )
    materialization = CuratedMaterialization(request, tuple(canonical.values()), tuple(editorial))
    result = render_curated_workspace(root / "request.json", root / "result.json")
    return materialization, result


def test_real_mixed_package_is_independently_accepted(tmp_path, handoff_bytes):
    root = tmp_path / "workspace"
    inputs, result = render(root, handoff_bytes)
    accepted = verify_curated_output(root, inputs, result)
    assert accepted.section_count == 5
    assert accepted.table_count == result.native_table_count > 0
    assert accepted.equation_count == result.native_equation_count > 0
    assert accepted.sha256 == result.output_sha256


@pytest.mark.parametrize(
    "mutation", ["text", "geometry", "equation", "resource", "binary", "external", "order"]
)
def test_forged_success_cannot_publish_mutated_native_content(tmp_path, handoff_bytes, mutation):
    root = tmp_path / "workspace"
    inputs, result = render(root, handoff_bytes)
    path = root / "output/assembled.hwpx"
    with zipfile.ZipFile(path) as archive:
        entries = [(info, archive.read(info)) for info in archive.infolist()]
    replacements = {
        "text": ("Contents/section1.xml", b"\xec\xa0\x95\xeb\x8b\xb5", b"ALTERED"),
        "geometry": ("Contents/section0.xml", b'width="', b'width="9'),
        "equation": ("Contents/section0.xml", b"</hp:script>", b"+999</hp:script>"),
        "resource": ("Contents/header.xml", b'height="', b'height="9'),
        "external": ("Contents/content.hpf", b"BinData/", b"/tmp/BinData/"),
    }
    changed = False
    with zipfile.ZipFile(path, "w") as archive:
        source = dict((info.filename, raw) for info, raw in entries)
        for info, raw in entries:
            if mutation == "binary" and info.filename.startswith("BinData/") and not changed:
                raw += b"TAMPERED"
                changed = True
            elif mutation == "order" and info.filename in {
                "Contents/section1.xml",
                "Contents/section2.xml",
            }:
                raw = source[
                    "Contents/section2.xml"
                    if "section1" in info.filename
                    else "Contents/section1.xml"
                ]
                changed = True
            elif mutation in replacements:
                name, old, new = replacements[mutation]
                if info.filename == name:
                    assert old in raw, (mutation, raw[:400])
                    raw = raw.replace(old, new, 1)
                    changed = True
            archive.writestr(info, raw)
    assert changed
    # A self-consistent forged output hash/result is still not authority.
    forged = result.model_copy(
        update={
            "output_sha256": sha256_bytes(path.read_bytes()),
            "output_size_bytes": path.stat().st_size,
        }
    )
    with pytest.raises(HwpxManagerError):
        verify_curated_output(root, inputs, forged)


def test_result_identity_and_counts_are_not_trusted(tmp_path, handoff_bytes):
    root = tmp_path / "workspace"
    inputs, result = render(root, handoff_bytes)
    for changes in (
        {"build_id": "hwpxbuild_" + "0" * 32},
        {"binary_count": 0},
        {"input_plan_sha256": "sha256:" + "0" * 64},
        {"section_source_positions": (1, 2, 3, 5, 4)},
    ):
        with pytest.raises(HwpxManagerError):
            verify_curated_output(root, inputs, result.model_copy(update=changes))
