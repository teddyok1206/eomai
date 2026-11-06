"""Known engine-error markers are not confused with ordinary scientific symbols."""

from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from eom_catalog_service.office_pdf_quality import (
    OfficePdfMathQualityError,
    require_office_pdf_math_quality,
)


def _fake_document(monkeypatch, *, font="OpenSymbol", color=0x800000, text="\u00bf", pages=1):
    class Document:
        is_pdf = True
        is_encrypted = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def __len__(self):
            return pages

        def __iter__(self):
            span = {"font": font, "color": color, "text": text}
            yield SimpleNamespace(
                get_text=lambda *_args, **_kwargs: {"blocks": [{"lines": [{"spans": [span]}]}]}
            )

    monkeypatch.setattr(
        "eom_catalog_service.office_pdf_quality.fitz.open", lambda _path: Document()
    )


def test_known_math_error_is_rejected(monkeypatch, tmp_path: Path) -> None:
    _fake_document(monkeypatch)
    with pytest.raises(OfficePdfMathQualityError, match="parser-error"):
        require_office_pdf_math_quality(tmp_path / "output.pdf")


@pytest.mark.parametrize(
    "override",
    [
        {"text": "?"},
        {"text": "x"},
        {"font": "Helvetica"},
        {"color": 0},
        {"font": "NotoSansCJKkr-Regular"},
        {"text": "\u00d7"},
    ],
)
def test_normal_text_and_symbols_are_not_false_positives(
    monkeypatch, tmp_path: Path, override
) -> None:
    _fake_document(monkeypatch, **override)
    require_office_pdf_math_quality(tmp_path / "output.pdf")


def test_subsetted_engine_font_is_still_rejected(monkeypatch, tmp_path: Path) -> None:
    _fake_document(monkeypatch, font="ABCDEF+OpenSymbol")
    with pytest.raises(OfficePdfMathQualityError, match="parser-error"):
        require_office_pdf_math_quality(tmp_path / "output.pdf")


@pytest.mark.parametrize("pages", [0, 513])
def test_page_bound_is_explicit(monkeypatch, tmp_path: Path, pages: int) -> None:
    _fake_document(monkeypatch, pages=pages)
    with pytest.raises(OfficePdfMathQualityError, match="page range"):
        require_office_pdf_math_quality(tmp_path / "output.pdf")


def test_real_pdf_is_opened_without_modification(tmp_path: Path) -> None:
    path = tmp_path / "normal.pdf"
    with fitz.open() as document:
        document.new_page().insert_text((40, 40), "x = 3; normal question?")
        document.save(path)
    original = path.read_bytes()
    require_office_pdf_math_quality(path)
    assert path.read_bytes() == original


def test_invalid_pdf_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "invalid.pdf"
    path.write_bytes(b"%PDF-1.7\nnot a real PDF")
    with pytest.raises(OfficePdfMathQualityError):
        require_office_pdf_math_quality(path)
