from __future__ import annotations

import stat
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest
from eom_catalog_contracts import OfficeDocumentReviewMemberPointer
from eom_catalog_service.document_review_hwpx import (
    DocumentReviewHwpxError,
    DocumentReviewReplacement,
    apply_document_review_hwpx_correction,
    build_document_review_hwpx_correction_plan,
)
from eom_identifiers import sha256_file

HH = "http://www.hancom.co.kr/hwpml/2011/head"
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"


def _zip_info(name: str, *, stored: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    return info


def _write_hwpx(path: Path, *, split_text: bool = False, duplicate: bool = False) -> None:
    header = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<hh:head xmlns:hh="{HH}"><hh:refList>'
        '<hh:charProperties itemCnt="1">'
        '<hh:charPr id="0" textColor="#000000" height="1000"/>'
        "</hh:charProperties></hh:refList></hh:head>"
    ).encode()
    if split_text:
        runs = (
            '<hp:run charPrIDRef="0"><hp:t>앞 수정 </hp:t></hp:run>'
            '<hp:run charPrIDRef="0"><hp:t>전 문장 뒤</hp:t></hp:run>'
        )
    else:
        runs = '<hp:run charPrIDRef="0"><hp:t>앞 수정 전 문장 뒤</hp:t></hp:run>'
    second = (
        '<hp:p><hp:run charPrIDRef="0"><hp:t>또 수정 전 문장</hp:t></hp:run></hp:p>'
        if duplicate
        else ""
    )
    section = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">'
        f"<hp:p>{runs}</hp:p>{second}</hs:sec>"
    ).encode()
    with zipfile.ZipFile(path, "x") as archive:
        archive.writestr(_zip_info("mimetype", stored=True), b"application/hwp+zip")
        archive.writestr(_zip_info("Contents/header.xml"), header)
        archive.writestr(_zip_info("Contents/content.hpf"), b"<package/>")
        archive.writestr(_zip_info("META-INF/container.xml"), b"<container/>")
        archive.writestr(_zip_info("Contents/section0.xml"), section)
    path.chmod(0o600)


def _pointer(path: Path, *, review: bool) -> OfficeDocumentReviewMemberPointer:
    return OfficeDocumentReviewMemberPointer(
        artifact_id="artifact_" + ("1" if review else "2") * 32,
        artifact_revision_id="rev_" + ("3" if review else "4") * 32,
        member_path="result.json" if review else "source/original.hwpx",
        sha256=("sha256:" + "a" * 64) if review else sha256_file(path),
        content_length=1024 if review else path.stat().st_size,
        media_type="application/json" if review else "application/vnd.hancom.hwpx",
        schema_ref=(
            "eom://schemas/document-review/review-result/1.0"
            if review
            else "eom://schemas/document-review/editable-hwpx/1.0"
        ),
    )


def _replacement() -> DocumentReviewReplacement:
    return DocumentReviewReplacement(
        finding_id="reviewfinding_" + "5" * 32,
        finding_code="TYPO_CONFIRMED",
        before_text="수정 전 문장",
        after_text="수정 후 문장",
    )


def _local(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def test_redline_hwpx_creates_new_package_and_marks_only_replacement_red(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "redline.hwpx"
    _write_hwpx(source)
    source_hash = sha256_file(source)
    plan = build_document_review_hwpx_correction_plan(
        source,
        correction_id="doccorrection_" + "6" * 32,
        workflow_id="workflow_" + "7" * 32,
        review_result=_pointer(source, review=True),
        base_hwpx=_pointer(source, review=False),
        replacements=(_replacement(),),
    )

    result = apply_document_review_hwpx_correction(source, output, plan)

    assert sha256_file(source) == source_hash
    assert result.output_member.sha256 == sha256_file(output)
    assert result.output_member.sha256 != source_hash
    assert output.stat().st_mode & 0o777 == 0o600
    with zipfile.ZipFile(output) as archive:
        assert archive.infolist()[0].filename == "mimetype"
        assert archive.infolist()[0].compress_type == zipfile.ZIP_STORED
        header = ElementTree.fromstring(archive.read("Contents/header.xml"))
        properties = [node for node in header.iter() if _local(node.tag) == "charPr"]
        assert [(node.attrib["id"], node.attrib["textColor"]) for node in properties] == [
            ("0", "#000000"),
            ("1", "#FF0000"),
        ]
        section = ElementTree.fromstring(archive.read("Contents/section0.xml"))
        runs = [node for node in section.iter() if _local(node.tag) == "run"]
        assert ["".join(node.itertext()) for node in runs] == ["앞 ", "수정 후 문장", " 뒤"]
        assert [node.attrib["charPrIDRef"] for node in runs] == ["0", "1", "0"]


def test_redline_hwpx_applies_multiple_nonoverlapping_edits_in_one_run(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "redline.hwpx"
    _write_hwpx(source)
    plan = build_document_review_hwpx_correction_plan(
        source,
        correction_id="doccorrection_" + "6" * 32,
        workflow_id="workflow_" + "7" * 32,
        review_result=_pointer(source, review=True),
        base_hwpx=_pointer(source, review=False),
        replacements=(
            DocumentReviewReplacement(
                finding_id="reviewfinding_" + "5" * 32,
                finding_code="WORDING_CONFIRMED",
                before_text="앞",
                after_text="전면",
            ),
            DocumentReviewReplacement(
                finding_id="reviewfinding_" + "8" * 32,
                finding_code="WORDING_CONFIRMED",
                before_text="뒤",
                after_text="후면",
            ),
        ),
    )

    apply_document_review_hwpx_correction(source, output, plan)

    with zipfile.ZipFile(output) as archive:
        section = ElementTree.fromstring(archive.read("Contents/section0.xml"))
        runs = [node for node in section.iter() if _local(node.tag) == "run"]
        assert ["".join(node.itertext()) for node in runs] == ["전면", " 수정 전 문장 ", "후면"]
        assert [node.attrib["charPrIDRef"] for node in runs] == ["1", "0", "1"]


def test_plan_rejects_ambiguous_replacement_text(tmp_path: Path) -> None:
    source = tmp_path / "duplicate.hwpx"
    _write_hwpx(source, duplicate=True)

    with pytest.raises(DocumentReviewHwpxError) as error:
        build_document_review_hwpx_correction_plan(
            source,
            correction_id="doccorrection_" + "6" * 32,
            workflow_id="workflow_" + "7" * 32,
            review_result=_pointer(source, review=True),
            base_hwpx=_pointer(source, review=False),
            replacements=(_replacement(),),
        )
    assert error.value.code == "DOCUMENT_REVIEW_HWPX_REPLACEMENT_AMBIGUOUS"


def test_plan_rejects_replacement_crossing_text_runs(tmp_path: Path) -> None:
    source = tmp_path / "split.hwpx"
    _write_hwpx(source, split_text=True)

    with pytest.raises(DocumentReviewHwpxError) as error:
        build_document_review_hwpx_correction_plan(
            source,
            correction_id="doccorrection_" + "6" * 32,
            workflow_id="workflow_" + "7" * 32,
            review_result=_pointer(source, review=True),
            base_hwpx=_pointer(source, review=False),
            replacements=(_replacement(),),
        )
    assert error.value.code == "DOCUMENT_REVIEW_HWPX_EDIT_CROSSES_RUN"


def test_plan_rejects_traversal_member(tmp_path: Path) -> None:
    source = tmp_path / "unsafe.hwpx"
    with zipfile.ZipFile(source, "x") as archive:
        archive.writestr(_zip_info("mimetype", stored=True), b"application/hwp+zip")
        archive.writestr(_zip_info("../Contents/header.xml"), b"<head/>")
    source.chmod(0o600)

    with pytest.raises(DocumentReviewHwpxError) as error:
        build_document_review_hwpx_correction_plan(
            source,
            correction_id="doccorrection_" + "6" * 32,
            workflow_id="workflow_" + "7" * 32,
            review_result=_pointer(source, review=True),
            base_hwpx=_pointer(source, review=False),
            replacements=(_replacement(),),
        )
    assert error.value.code == "DOCUMENT_REVIEW_HWPX_MEMBER_UNSAFE"
