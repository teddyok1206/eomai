"""Bounded check for the known StarMath parser-error rendering, not a math proof."""

from pathlib import Path

import fitz  # type: ignore[import-untyped]

MAX_QUALITY_PAGES = 512
MAX_QUALITY_SPANS = 500_000
_MATH_ERROR_COLOR = 0x800000


class OfficePdfMathQualityError(ValueError):
    """The derived PDF is unreadable or contains a known renderer error marker."""


def require_office_pdf_math_quality(path: Path) -> None:
    try:
        with fitz.open(path) as document:
            if (
                not document.is_pdf
                or document.is_encrypted
                or not 1 <= len(document) <= MAX_QUALITY_PAGES
            ):
                raise OfficePdfMathQualityError("Office PDF page range or encryption is invalid")
            count = 0
            for page in document:
                for block in page.get_text(
                    "dict", flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES
                )["blocks"]:
                    for line in block.get("lines", ()):
                        for span in line["spans"]:
                            count += 1
                            if count > MAX_QUALITY_SPANS:
                                raise OfficePdfMathQualityError(
                                    "Office PDF quality span bound exceeded"
                                )
                            if (
                                span["font"].split("+")[-1] == "OpenSymbol"
                                and span["color"] == _MATH_ERROR_COLOR
                                and "\u00bf" in span["text"]
                            ):
                                raise OfficePdfMathQualityError(
                                    "Office PDF contains a StarMath parser-error marker"
                                )
    except OfficePdfMathQualityError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise OfficePdfMathQualityError("Office PDF could not be inspected") from error
