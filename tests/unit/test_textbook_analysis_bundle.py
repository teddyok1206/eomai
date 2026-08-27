from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_catalog_contracts import (
    TextbookAnalysisBundleManifest,
    TextbookAnalysisBundleManifestV2,
    validate_contract,
)
from eom_textbook_analysis.bundle import (
    CurriculumMappingSpec,
    ExtractedMultimodalPage,
    PdfInspection,
    TextbookBundleBuildError,
    TextbookBundleBuildRequest,
    _assert_ocr_image,
    _requires_ocr,
    build_textbook_analysis_bundle,
    build_textbook_multimodal_analysis_bundle,
)


class FakeExtractor:
    implementation = "fake-pdf-text"
    version = "1.0.0"
    implementation_sha256 = "sha256:" + "f" * 64
    options_sha256 = "sha256:" + "e" * 64

    def __init__(
        self,
        pages: tuple[str, ...],
        *,
        source_page_count: int = 20,
        encrypted: bool = False,
    ) -> None:
        self._pages = pages
        self._inspection = PdfInspection(
            page_count=source_page_count,
            encrypted=encrypted,
        )

    def inspect(self, source_path: Path) -> PdfInspection:
        assert source_path.is_file()
        return self._inspection

    def extract(
        self, source_path: Path, first_physical_page: int, last_physical_page: int
    ) -> tuple[str, ...]:
        assert source_path.is_file()
        assert (first_physical_page, last_physical_page) == (16, 19)
        return self._pages


def _png(width: int, height: int, marker: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + bytes((8, 0, 0, 0, 0))
        + b"fixture"
        + bytes((marker,))
    )


class FakeMultimodalExtractor(FakeExtractor):
    def __init__(
        self,
        pages: tuple[ExtractedMultimodalPage, ...],
        *,
        source_page_count: int = 20,
    ) -> None:
        super().__init__(tuple(page.text for page in pages), source_page_count=source_page_count)
        self._multimodal_pages = pages

    def extract_multimodal(
        self, source_path: Path, first_physical_page: int, last_physical_page: int
    ) -> tuple[ExtractedMultimodalPage, ...]:
        assert source_path.is_file()
        assert (first_physical_page, last_physical_page) == (16, 19)
        return self._multimodal_pages


def _request(
    tmp_path: Path, source: Path, output_name: str = "bundle"
) -> TextbookBundleBuildRequest:
    source_bytes = source.read_bytes()
    return TextbookBundleBuildRequest(
        source_path=source,
        expected_source_sha256="sha256:" + hashlib.sha256(source_bytes).hexdigest(),
        expected_source_size_bytes=len(source_bytes),
        expected_source_page_count=20,
        publisher_key="miraen",
        publisher_label="미래엔",
        title="통합과학1",
        curriculum_volume="I",
        first_physical_page=16,
        last_physical_page=19,
        printed_page_offset=-2,
        mappings=(
            CurriculumMappingSpec(
                eom_unit_key="1-(1)",
                eom_unit_label="시간과 공간",
                first_physical_page=16,
                last_physical_page=19,
                mapping_kind="PRIMARY",
                confidence_milli=1000,
            ),
        ),
        output_directory=(tmp_path / output_name).absolute(),
        generated_by="codex-data-analysis-pilot",
        generated_at=datetime(2026, 8, 24, 18, 0, tzinfo=UTC),
    )


def _make_source(tmp_path: Path) -> Path:
    source = (tmp_path / "source.pdf").absolute()
    source.write_bytes(b"%PDF-1.7\nreview fixture\n")
    source.chmod(0o400)
    return source


def _make_writable_for_cleanup(output: Path) -> None:
    if not output.exists():
        return
    output.chmod(0o700)
    pages = output / "pages"
    if pages.exists():
        pages.chmod(0o700)
        for child in pages.iterdir():
            child.chmod(0o600)
    images = output / "images"
    if images.exists():
        images.chmod(0o700)
        for child in images.iterdir():
            child.chmod(0o600)
    for child in output.iterdir():
        if child.is_file():
            child.chmod(0o600)


def test_build_textbook_analysis_bundle_is_deterministic_and_hash_verified(
    tmp_path: Path,
) -> None:
    source = _make_source(tmp_path)
    first_output = tmp_path / "bundle-one"
    second_output = tmp_path / "bundle-two"
    try:
        first = build_textbook_analysis_bundle(
            _request(tmp_path, source, "bundle-one"),
            FakeExtractor(("시간\n", "공간\n", "측\ufffd정\n", "신호\n")),
        )
        second = build_textbook_analysis_bundle(
            _request(tmp_path, source, "bundle-two"),
            FakeExtractor(("시간\n", "공간\n", "측\ufffd정\n", "신호\n")),
        )

        assert first == second
        assert first.bundle_state == "PRE_CANONICAL_REVIEW_ONLY"
        assert first.canonical_source is None
        assert first.scope.first_physical_page == 16
        assert first.scope.last_physical_page == 19
        assert first.curriculum_mappings[0].evidence_anchor_ids == tuple(
            page.anchor_id for page in first.pages
        )
        assert first.pages[2].extraction_state == "TEXT_WITH_WARNINGS"
        assert first.pages[2].replacement_character_count == 1
        manifest_value = json.loads((first_output / "manifest.json").read_text())
        validate_contract("textbook-analysis-bundle-manifest", manifest_value)
        assert TextbookAnalysisBundleManifest.model_validate(manifest_value) == first
        assert not tuple(first_output.glob("*.pdf"))

        for page in first.pages:
            member = first_output / page.member_path
            assert member.is_file() and not member.is_symlink()
            assert "sha256:" + hashlib.sha256(member.read_bytes()).hexdigest() == page.member_sha256
            assert page.member_path.startswith("pages/")
        index = first_output / first.index_member.member_path
        assert "sha256:" + hashlib.sha256(index.read_bytes()).hexdigest() == (
            first.index_member.member_sha256
        )
        assert stat_mode(first_output) == 0o500
        assert stat_mode(first_output / "pages") == 0o500
        assert stat_mode(first_output / "manifest.json") == 0o400
    finally:
        _make_writable_for_cleanup(first_output)
        _make_writable_for_cleanup(second_output)


def test_multimodal_bundle_has_one_exact_png_for_every_page(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    first_output = tmp_path / "multimodal-one"
    second_output = tmp_path / "multimodal-two"
    pages = tuple(
        ExtractedMultimodalPage(
            text=f"page {physical_page}\n",
            png_bytes=_png(1200, 1800, physical_page),
            width_pixels=1200,
            height_pixels=1800,
            render_dpi=180,
        )
        for physical_page in range(16, 20)
    )
    try:
        first = build_textbook_multimodal_analysis_bundle(
            _request(tmp_path, source, "multimodal-one"), FakeMultimodalExtractor(pages)
        )
        second = build_textbook_multimodal_analysis_bundle(
            _request(tmp_path, source, "multimodal-two"), FakeMultimodalExtractor(pages)
        )

        assert first == second
        assert first.schema_version == "textbook-analysis-bundle-manifest/2.0"
        assert len(first.pages) == 4
        assert tuple(page.physical_page for page in first.pages) == (16, 17, 18, 19)
        manifest_value = json.loads((first_output / "manifest.json").read_text())
        validate_contract("textbook-analysis-bundle-manifest-v2", manifest_value)
        assert TextbookAnalysisBundleManifestV2.model_validate(manifest_value) == first
        for page in first.pages:
            image = first_output / page.image_member_path
            assert image.is_file() and not image.is_symlink()
            assert page.image_member_path == f"images/page-{page.physical_page:06d}.png"
            assert _sha256(image.read_bytes()) == page.image_sha256
            assert (page.image_width_pixels, page.image_height_pixels) == (1200, 1800)
        assert stat_mode(first_output / "images") == 0o500
        assert stat_mode(first_output / "images/page-000016.png") == 0o400
        assert (
            first.bundle_id
            != build_textbook_analysis_bundle(
                _request(tmp_path, source, "historical-text"),
                FakeExtractor(tuple(page.text for page in pages)),
            ).bundle_id
        )
    finally:
        _make_writable_for_cleanup(first_output)
        _make_writable_for_cleanup(second_output)
        _make_writable_for_cleanup(tmp_path / "historical-text")


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def test_multimodal_bundle_rejects_missing_or_inconsistent_page_image(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    short_output = tmp_path / "multimodal-short"
    bad_output = tmp_path / "multimodal-bad"
    valid_pages = tuple(
        ExtractedMultimodalPage(
            text=f"page {physical_page}\n",
            png_bytes=_png(1200, 1800, physical_page),
            width_pixels=1200,
            height_pixels=1800,
            render_dpi=180,
        )
        for physical_page in range(16, 20)
    )
    try:
        with pytest.raises(TextbookBundleBuildError, match="PAGE_BOUNDARY_INVALID"):
            build_textbook_multimodal_analysis_bundle(
                _request(tmp_path, source, "multimodal-short"),
                FakeMultimodalExtractor(valid_pages[:-1]),
            )
        bad_pages = (
            ExtractedMultimodalPage(
                text=valid_pages[0].text,
                png_bytes=valid_pages[0].png_bytes,
                width_pixels=999,
                height_pixels=1800,
                render_dpi=180,
            ),
            *valid_pages[1:],
        )
        with pytest.raises(TextbookBundleBuildError, match="MULTIMODAL_PAGE_INVALID"):
            build_textbook_multimodal_analysis_bundle(
                _request(tmp_path, source, "multimodal-bad"),
                FakeMultimodalExtractor(bad_pages),
            )
    finally:
        _make_writable_for_cleanup(short_output)
        _make_writable_for_cleanup(bad_output)


def stat_mode(path: Path) -> int:
    return os.stat(path, follow_symlinks=False).st_mode & 0o7777


def test_build_rejects_stale_identity_encryption_and_existing_output(tmp_path: Path) -> None:
    source = _make_source(tmp_path)

    stale = _request(tmp_path, source)
    stale = TextbookBundleBuildRequest(
        **{
            **stale.__dict__,
            "expected_source_sha256": "sha256:" + "0" * 64,
        }
    )
    with pytest.raises(TextbookBundleBuildError, match="SOURCE_IDENTITY_MISMATCH"):
        build_textbook_analysis_bundle(stale, FakeExtractor(("a", "b", "c", "d")))
    assert not stale.output_directory.exists()

    encrypted = _request(tmp_path, source, "encrypted")
    with pytest.raises(TextbookBundleBuildError, match="PDF_ENCRYPTED"):
        build_textbook_analysis_bundle(
            encrypted,
            FakeExtractor(("a", "b", "c", "d"), encrypted=True),
        )
    assert not encrypted.output_directory.exists()

    existing = _request(tmp_path, source, "existing")
    existing.output_directory.mkdir()
    with pytest.raises(TextbookBundleBuildError, match="OUTPUT_NOT_NEW"):
        build_textbook_analysis_bundle(existing, FakeExtractor(("a", "b", "c", "d")))


def test_build_rejects_symlink_source_and_page_boundary_drift(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    link = (tmp_path / "source-link.pdf").absolute()
    link.symlink_to(source)
    linked = _request(tmp_path, source, "linked")
    linked = TextbookBundleBuildRequest(**{**linked.__dict__, "source_path": link})
    with pytest.raises(TextbookBundleBuildError, match="SOURCE_IDENTITY_MISMATCH"):
        build_textbook_analysis_bundle(linked, FakeExtractor(("a", "b", "c", "d")))

    output = tmp_path / "short-pages"
    try:
        with pytest.raises(TextbookBundleBuildError, match="PAGE_BOUNDARY_INVALID"):
            build_textbook_analysis_bundle(
                _request(tmp_path, source, "short-pages"),
                FakeExtractor(("a", "b", "c")),
            )
    finally:
        _make_writable_for_cleanup(output)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("통합과학 " * 30, False),
        ("integrated science " * 30, True),
        ("통합과학", True),
        ("", True),
    ],
)
def test_ocr_fallback_requires_both_bounded_text_and_korean_evidence(
    text: str, expected: bool
) -> None:
    assert (
        _requires_ocr(
            text,
            minimum_text_characters=100,
            minimum_hangul_characters=20,
        )
        is expected
    )


def test_ocr_image_boundary_rejects_invalid_bytes_and_symlinks(tmp_path: Path) -> None:
    image = tmp_path / "page.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    _assert_ocr_image(image)

    invalid = tmp_path / "invalid.png"
    invalid.write_bytes(b"not-a-png")
    with pytest.raises(TextbookBundleBuildError, match="TEXTBOOK_OCR_IMAGE_INVALID"):
        _assert_ocr_image(invalid)

    linked = tmp_path / "linked.png"
    linked.symlink_to(image)
    with pytest.raises(TextbookBundleBuildError, match="TEXTBOOK_OCR_IMAGE_INVALID"):
        _assert_ocr_image(linked)
