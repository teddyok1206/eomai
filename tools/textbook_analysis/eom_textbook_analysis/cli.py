"""Command-line entry point for protected textbook analysis bundles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eom_textbook_analysis.bundle import (
    PdfTextExtractor,
    PopplerTesseractTextExtractor,
    PopplerTextExtractor,
    TextbookBundleBuildRequest,
    build_textbook_analysis_bundle,
    load_mapping_specs,
    utc_now,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--source-size", required=True, type=int)
    parser.add_argument("--source-pages", required=True, type=int)
    parser.add_argument("--publisher-key", required=True)
    parser.add_argument("--publisher-label", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--volume", required=True, choices=("I", "II"))
    parser.add_argument("--first-page", required=True, type=int)
    parser.add_argument("--last-page", required=True, type=int)
    parser.add_argument("--printed-page-offset", type=int)
    parser.add_argument("--mappings", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--generated-by", default="codex-data-analysis-pilot")
    parser.add_argument("--pdftotext", required=True, type=Path)
    parser.add_argument("--pdfinfo", required=True, type=Path)
    parser.add_argument("--ocr-mode", choices=("off", "fallback", "all"), default="off")
    parser.add_argument("--pdftoppm", type=Path)
    parser.add_argument("--tesseract", type=Path)
    parser.add_argument("--tessdata-directory", type=Path)
    parser.add_argument("--ocr-language", default="kor+eng")
    parser.add_argument("--ocr-dpi", type=int, default=180)
    parser.add_argument("--minimum-text-characters", type=int, default=100)
    parser.add_argument("--minimum-hangul-characters", type=int, default=20)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    request = TextbookBundleBuildRequest(
        source_path=arguments.source.absolute(),
        expected_source_sha256=arguments.source_sha256,
        expected_source_size_bytes=arguments.source_size,
        expected_source_page_count=arguments.source_pages,
        publisher_key=arguments.publisher_key,
        publisher_label=arguments.publisher_label,
        title=arguments.title,
        curriculum_volume=arguments.volume,
        first_physical_page=arguments.first_page,
        last_physical_page=arguments.last_page,
        printed_page_offset=arguments.printed_page_offset,
        mappings=load_mapping_specs(arguments.mappings.absolute()),
        output_directory=arguments.output.absolute(),
        generated_by=arguments.generated_by,
        generated_at=utc_now(),
    )
    if arguments.ocr_mode == "off":
        if any(
            value is not None
            for value in (
                arguments.pdftoppm,
                arguments.tesseract,
                arguments.tessdata_directory,
            )
        ):
            raise SystemExit("OCR paths require --ocr-mode=fallback or --ocr-mode=all")
        extractor: PdfTextExtractor = PopplerTextExtractor(
            pdftotext=arguments.pdftotext,
            pdfinfo=arguments.pdfinfo,
        )
    else:
        if any(
            value is None
            for value in (
                arguments.pdftoppm,
                arguments.tesseract,
                arguments.tessdata_directory,
            )
        ):
            raise SystemExit(
                "--pdftoppm, --tesseract, and --tessdata-directory are required for OCR"
            )
        extractor = PopplerTesseractTextExtractor(
            pdftotext=arguments.pdftotext,
            pdfinfo=arguments.pdfinfo,
            pdftoppm=arguments.pdftoppm,
            tesseract=arguments.tesseract,
            tessdata_directory=arguments.tessdata_directory,
            ocr_mode=arguments.ocr_mode,
            ocr_language=arguments.ocr_language,
            ocr_dpi=arguments.ocr_dpi,
            minimum_text_characters=arguments.minimum_text_characters,
            minimum_hangul_characters=arguments.minimum_hangul_characters,
        )
    manifest = build_textbook_analysis_bundle(request, extractor)
    print(
        json.dumps(
            {
                "bundle_id": manifest.bundle_id,
                "bundle_state": manifest.bundle_state,
                "manifest_sha256": manifest.manifest_sha256,
                "page_count": len(manifest.pages),
                "mapping_count": len(manifest.curriculum_mappings),
                "output_directory": str(request.output_directory),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
