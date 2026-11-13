from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from eom_hwpx_builder.native_item_split import (
    NativeItemSplitError,
    discover_native_item_split,
    split_native_exam,
)
from eom_hwpx_builder.util import sha256_file
from eom_hwpx_contracts.native_item_split import NativeItemSplitPlan, native_split_contract_sha256
from eom_hwpx_contracts.validation import validate_contract
from pydantic import ValidationError

from tests.hwpx.helpers import png_bytes, synthetic_parts, write_hwpx
from tests.hwpx.test_curated_native_merge import header

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"


def paragraph(text: str, *, inner: str = "", identifier: int = 0) -> str:
    return (
        f'<hp:p id="{identifier}" paraPrIDRef="0" styleIDRef="0">'
        f'<hp:run charPrIDRef="0"><hp:t>{text}</hp:t>{inner}</hp:run></hp:p>'
    )


def section(content: str) -> bytes:
    return f'<hs:sec xmlns:hs="urn:synthetic:section" xmlns:hp="{HP}">{content}</hs:sec>'.encode()


def source(tmp_path: Path, *, sections: tuple[bytes, ...] | None = None, transform=None) -> Path:
    context = '<hp:secPr id="sec"><hp:pagePr width="59500" height="84200"/></hp:secPr>'
    context += '<hp:ctrl><hp:colPr type="NEWSPAPER" colCount="2"/></hp:ctrl>'
    picture = (
        '<hp:pic id="picture"><hp:img binaryItemIDRef="image1"/>'
        '<hp:imgRect left="2" right="99"/></hp:pic>'
    )
    table = '<hp:tbl id="table" rowCnt="1" colCnt="1"><hp:tr><hp:tc>'
    table += paragraph("2. 이 숫자는 표 안의 문장") + "</hp:tc></hp:tr></hp:tbl>"
    equation = '<hp:equation id="equation"><hp:script>x^2 + y^2 = z^2</hp:script></hp:equation>'
    if sections is None:
        sections = (
            section(
                paragraph("시험지 전체 제목", inner=context)
                + paragraph("1. 첫 번째 문항", inner=picture + table + equation, identifier=1)
                + paragraph("① ② ③ ④ ⑤", identifier=2)
                + paragraph("2. 두 번째 문항", identifier=3)
            ),
        )
    parts = [
        (member, header() if member == "Contents/header.xml" else data, method)
        for member, data, method in synthetic_parts()
        if not member.startswith(("Extra/", "Contents/section"))
    ]
    parts = [
        (member, data.replace(b' secCnt="1"', f' secCnt="{len(sections)}"'.encode()), method)
        for member, data, method in parts
    ]
    for index, content in enumerate(sections):
        parts.append((f"Contents/section{index}.xml", content, zipfile.ZIP_DEFLATED))
    for index in range(1, len(sections)):
        parts = [
            (
                member,
                data.replace(
                    b"</opf:manifest>",
                    (
                        f'<opf:item id="section{index}" href="section{index}.xml" '
                        'media-type="application/xml"/></opf:manifest>'
                    ).encode(),
                ).replace(
                    b"</opf:spine>",
                    f'<opf:itemref idref="section{index}"/></opf:spine>'.encode(),
                )
                if member == "Contents/content.hpf"
                else data,
                method,
            )
            for member, data, method in parts
        ]
    # Unused original figure: should not be duplicated in each item file.
    parts.append(("BinData/unused.png", png_bytes(output=True), zipfile.ZIP_DEFLATED))
    parts.append(("Preview/PrvImage.png", png_bytes(), zipfile.ZIP_DEFLATED))
    parts = [
        (
            member,
            data.replace(
                b"</opf:manifest>",
                b'<opf:item id="unused" href="BinData/unused.png" '
                b'media-type="image/png"/></opf:manifest>',
            )
            if member == "Contents/content.hpf"
            else data,
            method,
        )
        for member, data, method in parts
    ]
    return write_hwpx(tmp_path / "original.hwpx", transform(parts) if transform else parts)


def plan_for(path: Path):
    return discover_native_item_split(
        path, expected_source_sha256=sha256_file(path), source_role="MAIN", expected_numbers=(1, 2)
    )


def test_split_preserves_native_subtrees_binary_viewport_and_removes_other_items(
    tmp_path: Path,
) -> None:
    path = source(tmp_path)
    before = path.read_bytes()
    plan = plan_for(path)
    validate_contract("native-item-split", plan.model_dump(mode="json"))
    results = split_native_exam(path, tmp_path / "out", plan=plan)
    assert tuple(result.item_number for result in results) == (1, 2)
    assert results[0].counts.tables == 1
    assert results[0].counts.equations == 1
    assert results[0].counts.pictures == 1
    assert results[1].counts.pictures == 0
    assert all(result.context_sha256 for result in results)
    for result in results:
        validate_contract("native-item-split", result.model_dump(mode="json"))
    with zipfile.ZipFile(tmp_path / "out/001.hwpx") as archive:
        data = archive.read("Contents/section0.xml")
        assert "첫 번째" in data.decode()
        assert "두 번째" not in data.decode()
        assert "시험지 전체 제목" not in data.decode()
        assert b"<hp:tbl" in data and b"<hp:equation" in data
        assert b'left="2" right="99"' in data
        assert b'colCount="2"' in data and b"<hp:secPr" in data
        assert archive.read("BinData/image1.png") == png_bytes()
        assert "BinData/unused.png" not in archive.namelist()
        assert not any(name.startswith("Preview/") for name in archive.namelist())
        assert archive.read("Contents/header.xml").count(b"First") == header().count(b"First")
    with zipfile.ZipFile(tmp_path / "out/002.hwpx") as archive:
        assert not any(name.startswith("BinData/") for name in archive.namelist())
    assert path.read_bytes() == before
    again = split_native_exam(path, tmp_path / "again", plan=plan)
    assert again == results
    assert (tmp_path / "again/001.hwpx").read_bytes() == (tmp_path / "out/001.hwpx").read_bytes()


def test_nested_table_numbers_never_create_top_level_items(tmp_path: Path) -> None:
    assert tuple(item.item_number for item in plan_for(source(tmp_path)).items) == (1, 2)


def test_cross_section_continuation_keeps_all_paragraphs_in_original_order(tmp_path: Path) -> None:
    path = source(
        tmp_path,
        sections=(
            section(paragraph("1. 첫 번째") + paragraph("계속됨")),
            section(paragraph("이전 문항의 뒷부분") + paragraph("2. 두 번째")),
        ),
    )
    plan = plan_for(path)
    assert len(plan.items[0].ranges) == 2
    results = split_native_exam(path, tmp_path / "out", plan=plan)
    assert results[0].counts.paragraphs == 3
    with zipfile.ZipFile(tmp_path / "out/001.hwpx") as archive:
        first = archive.read("Contents/section0.xml").decode()
        second = archive.read("Contents/section1.xml").decode()
        assert "계속됨" in first and "뒷부분" in second and "두 번째" not in second


@pytest.mark.parametrize("texts", [("1. A", "1. B", "2. C"), ("1. A", "3. C"), ("2. B", "1. A")])
def test_missing_duplicate_or_out_of_order_headings_fail(
    tmp_path: Path, texts: tuple[str, ...]
) -> None:
    path = source(tmp_path, sections=(section("".join(paragraph(text) for text in texts)),))
    with pytest.raises(NativeItemSplitError, match="NUMBER_COVERAGE_INVALID"):
        plan_for(path)


def test_changed_source_is_not_implicitly_replanned(tmp_path: Path) -> None:
    path = source(tmp_path)
    plan = plan_for(path)
    with path.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(NativeItemSplitError, match="SOURCE_CHANGED"):
        split_native_exam(path, tmp_path / "out", plan=plan)
    assert not (tmp_path / "out").exists()


def test_rehashed_but_different_range_is_rejected(tmp_path: Path) -> None:
    path = source(tmp_path)
    value = plan_for(path).model_dump(mode="json")
    value["items"][0]["ranges"][0]["end_paragraph"] -= 1
    value["plan_sha256"] = native_split_contract_sha256(
        {k: v for k, v in value.items() if k != "plan_sha256"}
    )
    plan = NativeItemSplitPlan.model_validate(value)
    with pytest.raises(NativeItemSplitError, match="PLAN_CHANGED"):
        split_native_exam(path, tmp_path / "out", plan=plan)


@pytest.mark.parametrize(
    "old,new,error",
    [
        (b'binaryItemIDRef="image1"', b'binaryItemIDRef="absent"', "BINARY_REFERENCE_MISSING"),
        (b'charPrIDRef="0"', b'charPrIDRef="999"', "RESOURCE_REFERENCE_MISSING"),
        (
            b'<hp:pic id="picture"',
            b'<hp:pic href="file:///etc/passwd" id="picture"',
            "EXTERNAL_REFERENCE",
        ),
        (
            b'<hp:pic id="picture"',
            b'<hp:pic src="missing.png" id="picture"',
            "PACKAGE_REFERENCE_MISSING",
        ),
        (
            b'<hp:pic id="picture"',
            b'<hp:pic strangeIDRef="88" id="picture"',
            "REFERENCE_UNSUPPORTED",
        ),
        (
            b'<hp:pic id="picture"',
            b'<hp:pic linkListIDRef="99" id="picture"',
            "LINKED_FRAME_UNSUPPORTED",
        ),
    ],
)
def test_unresolved_or_external_references_fail_before_any_output(
    tmp_path: Path, old: bytes, new: bytes, error: str
) -> None:
    def transform(parts):
        return [
            (name, data.replace(old, new) if name.endswith("section0.xml") else data, method)
            for name, data, method in parts
        ]

    with pytest.raises(NativeItemSplitError, match=error):
        plan_for(source(tmp_path, transform=transform))


def test_header_referenced_image_is_retained(tmp_path: Path) -> None:
    def transform(parts):
        return [
            (
                name,
                data.replace(
                    b'<hh:borderFill id="1"/>',
                    b'<hh:borderFill id="1"><hh:img binaryItemIDRef="unused"/></hh:borderFill>',
                )
                if name.endswith("header.xml")
                else data,
                method,
            )
            for name, data, method in parts
        ]

    path = source(tmp_path, transform=transform)
    results = split_native_exam(path, tmp_path / "out", plan=plan_for(path))
    assert results[1].binary_sha256
    with zipfile.ZipFile(tmp_path / "out/002.hwpx") as archive:
        assert archive.read("BinData/unused.png") == png_bytes(output=True)


def test_models_are_frozen_and_hash_and_unknown_fields_are_checked(tmp_path: Path) -> None:
    plan = plan_for(source(tmp_path))
    with pytest.raises(ValidationError):
        plan.source_role = "SOLUTIONS"
    value = plan.model_dump(mode="json")
    value["source_sha256"] = "sha256:" + "1" * 64
    with pytest.raises(ValidationError, match="PLAN_HASH_MISMATCH"):
        NativeItemSplitPlan.model_validate(value)
    value = plan.model_dump(mode="json")
    value["path"] = "/etc/passwd"
    with pytest.raises(ValidationError):
        NativeItemSplitPlan.model_validate(value)


def test_replay_never_overwrites_an_output_directory(tmp_path: Path) -> None:
    path = source(tmp_path)
    plan = plan_for(path)
    split_native_exam(path, tmp_path / "out", plan=plan)
    before = (tmp_path / "out/001.hwpx").read_bytes()
    with pytest.raises(FileExistsError):
        split_native_exam(path, tmp_path / "out", plan=plan)
    assert (tmp_path / "out/001.hwpx").read_bytes() == before


def test_each_exam_loads_the_original_package_once_not_once_per_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import eom_hwpx_builder.native_item_split as adapter

    path = source(
        tmp_path,
        sections=(section("".join(paragraph(f"{number}. 문항") for number in range(1, 26))),),
    )
    plan = adapter.discover_native_item_split(
        path, expected_source_sha256=sha256_file(path), source_role="SOLUTIONS"
    )
    actual_read = adapter.read_package
    original_loads = 0

    def observe_read(target, *args, **kwargs):
        nonlocal original_loads
        if target == path:
            original_loads += 1
        return actual_read(target, *args, **kwargs)

    monkeypatch.setattr(adapter, "read_package", observe_read)
    results = adapter.split_native_exam(path, tmp_path / "out", plan=plan)
    assert len(results) == 25
    assert original_loads == 1
    assert {result.source_role for result in results} == {"SOLUTIONS"}


def test_field_reference_does_not_resolve_to_a_style_or_another_item(tmp_path: Path) -> None:
    path = source(
        tmp_path,
        sections=(
            section(
                paragraph("1. 첫 번째", inner='<hp:fieldBegin id="fieldA"/>')
                + paragraph("2. 두 번째", inner='<hp:fieldEnd beginIDRef="fieldA"/>')
            ),
        ),
    )
    plan = plan_for(path)
    with pytest.raises(NativeItemSplitError, match="FIELD_REFERENCE_MISSING"):
        split_native_exam(path, tmp_path / "out", plan=plan)
    assert not (tmp_path / "out/002.hwpx").exists()


def test_native_equation_script_is_not_confused_with_active_script(tmp_path: Path) -> None:
    path = source(tmp_path)
    assert split_native_exam(path, tmp_path / "good", plan=plan_for(path))[0].counts.equations == 1

    def transform(parts):
        return [
            (
                name,
                data.replace(b"</hs:sec>", b"<hp:script>evil</hp:script></hs:sec>")
                if name.endswith("section0.xml")
                else data,
                method,
            )
            for name, data, method in parts
        ]

    bad = tmp_path / "bad"
    bad.mkdir()
    with pytest.raises(NativeItemSplitError, match="ACTIVE_CONTENT"):
        plan_for(source(bad, transform=transform))


def test_existing_section_geometry_is_not_duplicated(tmp_path: Path) -> None:
    context = '<hp:secPr><hp:pagePr width="99"/></hp:secPr>'
    path = source(
        tmp_path,
        sections=(section(paragraph("1. 첫 번째", inner=context) + paragraph("2. 두 번째")),),
    )
    results = split_native_exam(path, tmp_path / "out", plan=plan_for(path))
    assert results[0].context_sha256 == ()
    assert len(results[1].context_sha256) == 1
    with zipfile.ZipFile(tmp_path / "out/001.hwpx") as archive:
        assert archive.read("Contents/section0.xml").count(b"<hp:secPr") == 1


def test_range_order_and_hash_remain_native_not_text_only(tmp_path: Path) -> None:
    path = source(tmp_path)
    plan = plan_for(path)
    value = plan.model_dump(mode="json")
    value["items"][0]["ranges"][0]["subtree_sha256"] = "sha256:" + "a" * 64
    value["plan_sha256"] = native_split_contract_sha256(
        {key: item for key, item in value.items() if key != "plan_sha256"}
    )
    changed = NativeItemSplitPlan.model_validate(value)
    with pytest.raises(NativeItemSplitError, match="PLAN_CHANGED"):
        split_native_exam(path, tmp_path / "out", plan=changed)


def test_zip_container_is_not_sufficient_to_claim_hwpx(tmp_path: Path) -> None:
    def transform(parts):
        return [
            (name, b"application/not-hwpx" if name == "mimetype" else data, method)
            for name, data, method in parts
        ]

    with pytest.raises(NativeItemSplitError, match="SOURCE_FORMAT_INVALID"):
        plan_for(source(tmp_path, transform=transform))
