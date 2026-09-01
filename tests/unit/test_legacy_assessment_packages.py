from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest
from eom_catalog_service import legacy_assessment_packages
from eom_catalog_service.legacy_assessment_packages import (
    LegacyAssessmentPackageError,
    inspect_hwpx_package,
)

MINIMAL_XML = b'<?xml version="1.0" encoding="UTF-8"?><root />'


def _hwpx(path: Path, extra: tuple[tuple[str | zipfile.ZipInfo, bytes], ...] = ()) -> Path:
    members: tuple[tuple[str | zipfile.ZipInfo, bytes], ...] = (
        ("mimetype", b"application/hwp+zip"),
        ("version.xml", MINIMAL_XML),
        ("Contents/header.xml", MINIMAL_XML),
        ("Contents/section0.xml", MINIMAL_XML),
        ("Contents/content.hpf", MINIMAL_XML),
        ("META-INF/container.xml", MINIMAL_XML),
        ("META-INF/manifest.xml", MINIMAL_XML),
        *extra,
    )
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members:
            archive.writestr(name, payload)
    return path


def test_hwpx_inspection_returns_bounded_topology_without_content(tmp_path: Path) -> None:
    path = _hwpx(tmp_path / "sample.hwpx", (("BinData/image1.png", b"PNG"),))

    result = inspect_hwpx_package(path)

    assert result.member_count == 8
    assert result.xml_member_count == 6
    assert result.media_member_count == 1
    assert result.section_count == 1
    assert not hasattr(result, "content")


@pytest.mark.parametrize("name", ("../escape.xml", "/absolute.xml", "a\\b.xml"))
def test_hwpx_inspection_rejects_unsafe_member_paths(tmp_path: Path, name: str) -> None:
    path = _hwpx(tmp_path / "unsafe.hwpx", ((name, MINIMAL_XML),))

    with pytest.raises(LegacyAssessmentPackageError) as raised:
        inspect_hwpx_package(path)
    assert raised.value.code == "LEGACY_ASSESSMENT_HWPX_MEMBER_UNSAFE"


def test_hwpx_inspection_rejects_symlink_members(tmp_path: Path) -> None:
    symlink = zipfile.ZipInfo("BinData/link.png")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    path = _hwpx(tmp_path / "symlink.hwpx", ((symlink, b"target"),))

    with pytest.raises(LegacyAssessmentPackageError) as raised:
        inspect_hwpx_package(path)
    assert raised.value.code == "LEGACY_ASSESSMENT_HWPX_MEMBER_UNSAFE"


def test_hwpx_inspection_rejects_case_colliding_members(tmp_path: Path) -> None:
    path = _hwpx(
        tmp_path / "collision.hwpx",
        (("BinData/Image.png", b"a"), ("BinData/image.png", b"b")),
    )

    with pytest.raises(LegacyAssessmentPackageError) as raised:
        inspect_hwpx_package(path)
    assert raised.value.code == "LEGACY_ASSESSMENT_HWPX_MEMBER_UNSAFE"


def test_hwpx_inspection_rejects_external_relationships(tmp_path: Path) -> None:
    external = b'<Relationships><Relationship TargetMode="External" /></Relationships>'
    path = _hwpx(tmp_path / "external.hwpx", (("META-INF/external.xml", external),))

    with pytest.raises(LegacyAssessmentPackageError) as raised:
        inspect_hwpx_package(path)
    assert raised.value.code == "LEGACY_ASSESSMENT_HWPX_EXTERNAL_LINK"


def test_hwpx_inspection_enforces_xml_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _hwpx(tmp_path / "large-xml.hwpx")
    monkeypatch.setattr(legacy_assessment_packages, "MAX_HWPX_XML_BYTES", 8)

    with pytest.raises(LegacyAssessmentPackageError) as raised:
        inspect_hwpx_package(path)
    assert raised.value.code == "LEGACY_ASSESSMENT_HWPX_XML_LIMIT"


def test_hwpx_inspection_rejects_symlink_input(tmp_path: Path) -> None:
    target = _hwpx(tmp_path / "source.hwpx")
    link = tmp_path / "link.hwpx"
    link.symlink_to(target)

    with pytest.raises(LegacyAssessmentPackageError) as raised:
        inspect_hwpx_package(link)
    assert raised.value.code == "LEGACY_ASSESSMENT_HWPX_FILE_INVALID"
