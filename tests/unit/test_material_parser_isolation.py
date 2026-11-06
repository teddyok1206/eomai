"""Parser adapters keep external bytes out of root/DB/NAS and preserve owner replies."""

import subprocess
from pathlib import Path

import pytest
from eom_catalog_contracts.material_office_conversion import (
    MaterialOfficeCommand,
    MaterialOfficeReply,
)
from eom_catalog_service import material_office_conversion as office
from eom_catalog_service import material_pdf_isolation as pdf


def test_office_schema_accepts_only_closed_instance_not_arbitrary_path():
    valid = dict(
        operation="CREATE",
        instance_id="officeconv_" + "a" * 32,
        source_format="HWPX",
        source_sha256=None,
    )
    assert MaterialOfficeCommand.model_validate(valid).operation == "CREATE"
    for changes in (
        {"instance_id": "../../source"},
        {"path": "/mnt/nas"},
        {"operation": "READ"},
        {"source_sha256": "sha256:" + "1" * 64},
    ):
        with pytest.raises(ValueError):
            MaterialOfficeCommand.model_validate(valid | changes)


def test_office_reply_requires_result_for_non_create():
    with pytest.raises(ValueError):
        MaterialOfficeReply(
            operation="READ",
            instance_id="officeconv_" + "a" * 32,
            source_sha256="sha256:" + "1" * 64,
            conversion=None,
        )


def test_pdf_tool_uses_readonly_bind_and_fixed_unprivileged_identity(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7\nfixture")
    monkeypatch.setattr(pdf.os, "geteuid", lambda: 0)
    monkeypatch.setattr(pdf, "_expose_readonly_input", lambda _path: None)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, b"Pages: 1\n", b"")

    monkeypatch.setattr(pdf.subprocess, "run", run)
    result = pdf.MaterialPdfSandboxRunner()(["/usr/bin/pdfinfo", str(source)])
    assert result.stdout == b"Pages: 1\n" and len(calls) == 1
    command, kwargs = calls[0]
    assert "--uid=eom-image" in command and "--gid=eom-image" in command
    assert f"BindReadOnlyPaths={source}:/run/eom-material-pdf/input" in command
    assert "PrivateNetwork=yes" in command and "ProtectSystem=strict" in command
    assert command[-2:] == ["/usr/bin/pdfinfo", "/run/eom-material-pdf/input"]
    assert "DATABASE_URL" not in kwargs["env"]


@pytest.mark.parametrize("fault", ["symlink", "program", "nonroot", "oversize"])
def test_pdf_rejects_unsafe_inputs_before_launch(tmp_path, monkeypatch, fault):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7\nfixture")
    monkeypatch.setattr(pdf.os, "geteuid", lambda: 1 if fault == "nonroot" else 0)
    calls = []
    monkeypatch.setattr(pdf.subprocess, "run", lambda *a, **k: calls.append(a))
    program = "/bin/sh" if fault == "program" else "/usr/bin/pdfinfo"
    if fault == "symlink":
        link = tmp_path / "link.pdf"
        link.symlink_to(source)
        source = link
    if fault == "oversize":
        with source.open("r+b") as stream:
            stream.truncate(256 * 1024**2 + 1)
    with pytest.raises(ValueError):
        pdf.MaterialPdfSandboxRunner()([program, str(source)])
    assert not calls


def test_root_converter_rejects_nonroot_owner(monkeypatch):
    monkeypatch.setattr(office.os, "geteuid", lambda: 1)
    with pytest.raises(ValueError, match="COORDINATOR_INVALID"):
        office.CatalogOwnerMaterialOfficeConverter()


def test_textbook_extractor_command_port_preserves_default_recipe(tmp_path):
    from eom_textbook_analysis.bundle import PopplerTextExtractor

    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7")
    calls = []

    def run(command, *, max_output_bytes=4 * 1024**2):
        calls.append(command)
        if command[-1] == "-v":
            return subprocess.CompletedProcess(command, 0, b"", b"pdftotext version 22.12.0\n")
        if Path(command[0]).name == "pdfinfo":
            return subprocess.CompletedProcess(command, 0, b"Pages: 1\nEncrypted: no\n", b"")
        return subprocess.CompletedProcess(command, 0, "자료\f".encode(), b"")

    extractor = PopplerTextExtractor(
        pdftotext=Path("/usr/bin/pdftotext"), pdfinfo=Path("/usr/bin/pdfinfo"), run=run
    )
    assert extractor.inspect(source).page_count == 1
    assert extractor.extract(source, 1, 1) == ("자료\n",)
    assert len(calls) == 3
