"""Real bounded PDF rasterization for a source-only creative Item worker."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from eom_catalog_contracts.external_item_learning_source import ExternalItemLearningSource
from eom_identifiers import content_sha256, sha256_bytes, sha256_file
from eom_orchestrator.external_item_learning_page_render import (
    _run_isolated,
    _split_png_stream,
    render_external_item_learning_pages,
)
from eom_orchestrator.pdf_render_isolation import PDF_RENDER_SANDBOX
from eom_orchestrator.source_pdf_crop_processing import _SANDBOX as CROP_PDF_SANDBOX

from tests.unit.test_external_item_learning_source_contract import _source


def _direct_fixture_runner(
    executable: Path,
    arguments: tuple[str, ...],
    pdf_bytes: bytes,
    *,
    timeout_seconds: float,
    maximum_stdout: int,
) -> bytes:
    """Test-only Poppler execution over a synthetic, locally generated PDF."""

    completed = subprocess.run(
        [str(executable), *arguments],
        input=pdf_bytes,
        capture_output=True,
        check=True,
        timeout=timeout_seconds,
    )
    assert len(completed.stdout) <= maximum_stdout
    return completed.stdout


def _pdf(page_count: int = 1) -> bytes:
    """Small valid PDF fixture, assembled without a PDF library or checked-in binary."""

    assert page_count in {1, 2}
    stream = b"BT /F1 12 Tf 72 720 Td (Creative item fixture) Tj ET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            b"<< /Type /Pages /Kids [3 0 R"
            + (b" 6 0 R" if page_count == 2 else b"")
            + b"] /Count "
            + str(page_count).encode()
            + b" >>"
        ),
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    if page_count == 2:
        objects.extend(
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Contents 7 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
                b"<< /Length "
                + str(len(stream)).encode()
                + b" >>\nstream\n"
                + stream
                + b"endstream",
            )
        )
    body = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(body))
        body.extend(f"{index} 0 obj\n".encode())
        body.extend(obj)
        body.extend(b"\nendobj\n")
    xref = len(body)
    body.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode())
    body.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(body)


def _source_for_pdf(payload: bytes) -> ExternalItemLearningSource:
    source = _source()
    preview = source["preview_manifest"]
    assert isinstance(preview, dict)
    conversion = preview["conversion"]
    assert isinstance(conversion, dict)
    preview["pdf_sha256"] = sha256_bytes(payload)
    preview["pdf_bytes"] = len(payload)
    conversion["review_pdf_sha256"] = preview["pdf_sha256"]
    preview["manifest_sha256"] = content_sha256(
        {key: value for key, value in preview.items() if key != "manifest_sha256"}
    )
    source["input_sha256"] = content_sha256(
        {key: value for key, value in source.items() if key != "input_sha256"}
    )
    return ExternalItemLearningSource.model_validate(source)


@pytest.mark.skipif(
    shutil.which("pdfinfo") is None or shutil.which("pdftoppm") is None,
    reason="Poppler tools are not installed",
)
def test_render_one_real_pdf_page_without_copying_pdf_to_manifest(tmp_path: Path) -> None:
    payload = _pdf()
    source = _source_for_pdf(payload)
    result = render_external_item_learning_pages(
        source, payload, workspace=tmp_path / "creative-page-set", run=_direct_fixture_runner
    )
    assert len(result.manifest.pages) == 1
    assert result.manifest.preview_pdf_sha256 == source.preview_manifest.pdf_sha256
    assert result.manifest.pages[0].sha256 == sha256_file(result.page_paths[0])
    assert result.manifest.pages[0].height_px == 2400
    assert result.manifest_path.exists()
    assert b"preview.pdf" not in result.manifest_path.read_bytes()
    assert not result.workspace.joinpath("preview.pdf").exists()


def test_reject_wrong_pdf_before_creating_workspace(tmp_path: Path) -> None:
    payload = _pdf()
    source = _source_for_pdf(payload)
    destination = tmp_path / "not-created"
    with pytest.raises(ValueError, match="CREATIVE_PAGE_SOURCE_INVALID"):
        render_external_item_learning_pages(source, payload + b"changed", workspace=destination)
    assert not destination.exists()


def test_production_runner_uses_existing_isolated_pdf_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], bytes]] = []

    def fake_run(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        payload = kwargs.get("input")
        assert isinstance(payload, bytes)
        calls.append((arguments, payload))
        return subprocess.CompletedProcess(arguments, 0, b"Pages: 1\nEncrypted: no\n", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    output = _run_isolated(
        Path("/usr/bin/pdfinfo"),
        ("-",),
        b"%PDF-fixture",
        timeout_seconds=20,
        maximum_stdout=262144,
    )
    assert output.startswith(b"Pages: 1")
    command, supplied_pdf = calls[0]
    assert supplied_pdf == b"%PDF-fixture"
    assert command[:5] == ["/usr/bin/systemd-run", "--quiet", "--wait", "--pipe", "--collect"]
    assert "--uid=eom-image" in command
    assert "--gid=eom-image" in command
    assert "PrivateNetwork=yes" in command
    assert any(value.startswith("InaccessiblePaths=/mnt/nas ") for value in command)
    assert PDF_RENDER_SANDBOX is CROP_PDF_SANDBOX


@pytest.mark.skipif(
    shutil.which("pdfinfo") is None or shutil.which("pdftoppm") is None,
    reason="Poppler tools are not installed",
)
def test_render_two_pages_in_one_bounded_pdf_transfer(tmp_path: Path) -> None:
    payload = _pdf(page_count=2)
    result = render_external_item_learning_pages(
        _source_for_pdf(payload),
        payload,
        workspace=tmp_path / "two-page-set",
        run=_direct_fixture_runner,
    )
    assert tuple(page.physical_page for page in result.manifest.pages) == (1, 2)
    assert tuple(path.name for path in result.page_paths) == ("page-0001.png", "page-0002.png")


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="Poppler is not installed")
def test_page_stream_rejects_wrong_count_and_corrupt_crc() -> None:
    output = _direct_fixture_runner(
        Path("/usr/bin/pdftoppm"),
        ("-f", "1", "-l", "1", "-png", "-scale-to", "2400", "-"),
        _pdf(),
        timeout_seconds=20,
        maximum_stdout=16 * 1024 * 1024,
    )
    assert len(_split_png_stream(output, expected_pages=1)) == 1
    with pytest.raises(ValueError, match="CREATIVE_PAGE_STREAM_INVALID"):
        _split_png_stream(output, expected_pages=2)
    corrupted = bytearray(output)
    corrupted[-8] ^= 1
    with pytest.raises(ValueError, match="CREATIVE_PAGE_STREAM_INVALID"):
        _split_png_stream(bytes(corrupted), expected_pages=1)
