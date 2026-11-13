"""Only byte-exact reviewed editor scaffolding is sanitized; no JS parser or execution."""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
from eom_hwpx_builder.archive import read_package
from eom_hwpx_builder.curated_package_merge import (
    NativeDocumentReadProfile,
    merge_native_hwpx,
    parse_native_document,
)
from eom_hwpx_builder.errors import HwpxError
from eom_hwpx_builder.native_item_split import NativeItemSplitError, split_native_exam
from eom_hwpx_contracts.native_item_split import NativeItemSplitResult
from eom_hwpx_contracts.validation import validate_contract
from pydantic import ValidationError

from tests.hwpx.test_native_item_split import plan_for, source

type Parts = list[tuple[str, bytes, int]]
_HEADER = "var Documents = XHwpDocuments;var Document = Documents.Active_XHwpDocument;".encode(
    "utf-16le"
)
_SOURCE = "function OnDocument_New(){\r\n\t//todo :\r\n}".encode("utf-16le")


def _source(tmp_path: Path, change: Callable[[Parts], Parts] | None = None) -> Path:
    def add(parts: Parts) -> Parts:
        entries = []
        for name, raw, method in parts:
            if name == "Contents/content.hpf":
                raw = raw.replace(
                    b"</opf:manifest>",
                    (
                        b'<opf:item id="headersc" href="Scripts/headerScripts" '
                        b'media-type="application/x-javascript ;charset=utf-16"/>'
                        b'<opf:item id="sourcesc" href="Scripts/sourceScripts" '
                        b'media-type="application/x-javascript ;charset=utf-16"/>'
                        b"</opf:manifest>"
                    ),
                )
                raw = raw.replace(b"</opf:spine>", b'<opf:itemref idref="sourcesc"/></opf:spine>')
            entries.append((name, raw, method))
        entries.extend(
            [
                ("Scripts/headerScripts", _HEADER, zipfile.ZIP_DEFLATED),
                ("Scripts/sourceScripts", _SOURCE, zipfile.ZIP_DEFLATED),
            ]
        )
        return change(entries) if change else entries

    return source(tmp_path, transform=add)


def test_only_split_profile_can_read_exact_default_pair_and_record_exclusion(
    tmp_path: Path,
) -> None:
    path = _source(tmp_path)
    before = path.read_bytes()
    with pytest.raises(HwpxError):
        parse_native_document(read_package(path))
    with pytest.raises(HwpxError):
        merge_native_hwpx((path,), tmp_path / "not-permitted.hwpx")
    parsed = parse_native_document(
        read_package(path), profile=NativeDocumentReadProfile.NATIVE_SPLIT_V1
    )
    assert tuple(p.member_path for p in parsed.excluded_parts) == (
        "Scripts/headerScripts",
        "Scripts/sourceScripts",
    )
    assert tuple(p.bytes for p in parsed.excluded_parts) == (150, 80)
    results = split_native_exam(path, tmp_path / "out", plan=plan_for(path))
    for number, result in enumerate(results, 1):
        assert result.excluded_source_parts == parsed.excluded_parts
        validate_contract("native-item-split", result.model_dump(mode="json"))
        with zipfile.ZipFile(tmp_path / f"out/{number:03d}.hwpx") as z:
            assert not any(name.startswith("Scripts/") for name in z.namelist())
            assert b"headersc" not in z.read("Contents/content.hpf")
            assert b"sourcesc" not in z.read("Contents/content.hpf")
    assert path.read_bytes() == before
    assert split_native_exam(path, tmp_path / "again", plan=plan_for(path)) == results


@pytest.mark.parametrize(
    "replacement",
    [
        _SOURCE + "\r\nalert(1);".encode("utf-16le"),
        "function OnDocument_New(){\r\n\t//todo :\r\n}\r\n// harmless\r\nDocument.Save();".encode(
            "utf-16le"
        ),
        "function OnDocument_New(){\r\n\t//todo :\u2028Document.Save();\r\n}".encode("utf-16le"),
        "function OnDocument_Ne\u200bw(){\r\n\t//todo :\r\n}".encode("utf-16le"),
        b"function OnDocument_New(){\r\n\t//todo :\r\n}",
        "function OnDocument_New(){\r\n\t//todo :\r\n}".encode("utf-16be"),
        b"\xff\xfe" + _SOURCE,
        _SOURCE + b"\x00\x00",
    ],
)
def test_any_source_script_byte_encoding_comment_or_unicode_change_is_rejected(
    tmp_path: Path, replacement: bytes
) -> None:
    def change(parts: Parts) -> Parts:
        return [(n, replacement if n == "Scripts/sourceScripts" else b, m) for n, b, m in parts]

    path = _source(tmp_path, change)
    with pytest.raises(HwpxError, match="exact reviewed empty editor template"):
        plan_for(path)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("case", ["header", "missing", "extra", "unlisted", "duplicate"])
def test_script_pair_must_be_exact_and_explicitly_manifested(tmp_path: Path, case: str) -> None:
    def change(parts: Parts) -> Parts:
        entries = []
        for name, payload, method in parts:
            if case == "header" and name == "Scripts/headerScripts":
                payload = payload + b"\x00\x00"
            if case == "missing" and name == "Scripts/sourceScripts":
                continue
            if case == "unlisted" and name == "Contents/content.hpf":
                import re

                payload = re.sub(rb'<opf:item id="headersc"[^>]*/>', b"", payload)
            if case == "duplicate" and name == "Contents/content.hpf":
                payload = payload.replace(
                    b"</opf:manifest>",
                    (
                        b'<opf:item id="headersc2" href="Scripts/headerScripts" '
                        b'media-type="application/x-javascript ;charset=utf-16"/>'
                        b"</opf:manifest>"
                    ),
                )
            entries.append((name, payload, method))
        if case == "extra":
            entries.append(("Scripts/other.js", _SOURCE, zipfile.ZIP_DEFLATED))
        return entries

    with pytest.raises(HwpxError):
        plan_for(_source(tmp_path, change))


def test_document_content_cannot_depend_on_the_excluded_template(tmp_path: Path) -> None:
    def change(parts: Parts) -> Parts:
        return [
            (
                name,
                raw.replace(
                    b'<hp:pic id="picture"', b'<hp:pic href="Scripts/sourceScripts" id="picture"'
                )
                if name == "Contents/section0.xml"
                else raw,
                method,
            )
            for name, raw, method in parts
        ]

    with pytest.raises(NativeItemSplitError, match="EMPTY_SCRIPT_REFERENCED_BY_CONTENT"):
        plan_for(_source(tmp_path, change))


def test_exclusion_receipt_rejects_tampered_hash_and_old_empty_receipts_still_read(
    tmp_path: Path,
) -> None:
    path = _source(tmp_path)
    result = split_native_exam(path, tmp_path / "out", plan=plan_for(path))[0]
    payload = result.model_dump(mode="json")
    payload["excluded_source_parts"][0]["sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError, match="EXCLUDED_TEMPLATE_CHANGED"):
        NativeItemSplitResult.model_validate(payload)
    payload = result.model_dump(mode="json")
    payload.pop("excluded_source_parts")
    assert NativeItemSplitResult.model_validate(payload).excluded_source_parts == ()
