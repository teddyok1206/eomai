from __future__ import annotations

import stat
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_service.office_converter_worker import (
    OfficeConverterError,
    convert_workspace,
)
from eom_catalog_service.office_document_converter import (
    SystemdOfficeDocumentConverter,
)


def _zip_info(name: str, *, stored: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    return info


def _write_minimal_hwpx(path: Path) -> None:
    with zipfile.ZipFile(path, "x") as archive:
        archive.writestr(_zip_info("mimetype", stored=True), b"application/hwp+zip")
        archive.writestr(_zip_info("Contents/header.xml"), b"<header/>")
    path.chmod(0o600)


def test_fixed_workspace_worker_converts_hwpx_to_bounded_pdf(tmp_path: Path) -> None:
    instance = "officeconv_" + "1" * 32
    workspace = tmp_path / instance
    workspace.mkdir(mode=0o700)
    _write_minimal_hwpx(workspace / "original.hwpx")

    def fake_run(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        output_directory = Path(arguments[arguments.index("--outdir") + 1])
        (output_directory / "original.pdf").write_bytes(b"%PDF-1.7\nconverted")
        return subprocess.CompletedProcess(arguments, 0, b"", b"")

    output = convert_workspace(
        instance,
        conversion_root=tmp_path,
        libreoffice=Path("/bin/true"),
        h2orestart_jar=Path("/bin/true"),
        run=fake_run,
    )

    assert output.read_bytes().startswith(b"%PDF-1.7")
    assert output.stat().st_mode & 0o777 == 0o600


def test_fixed_workspace_worker_rejects_unsafe_hwpx_member(tmp_path: Path) -> None:
    instance = "officeconv_" + "2" * 32
    workspace = tmp_path / instance
    workspace.mkdir(mode=0o700)
    source = workspace / "original.hwpx"
    with zipfile.ZipFile(source, "x") as archive:
        archive.writestr(_zip_info("mimetype", stored=True), b"application/hwp+zip")
        archive.writestr(_zip_info("../escape.xml"), b"<escape/>")
    source.chmod(0o600)

    with pytest.raises(OfficeConverterError, match="unsafe member"):
        convert_workspace(
            instance,
            conversion_root=tmp_path,
            libreoffice=Path("/bin/true"),
            h2orestart_jar=Path("/bin/true"),
        )


def test_catalog_adapter_starts_only_fixed_unit_and_pins_converter_identity(
    tmp_path: Path,
) -> None:
    staging_root = tmp_path / "staging"
    staging_root.mkdir(mode=0o700)
    calls: list[list[str]] = []

    def fake_run(
        arguments: list[str],
        *,
        check: bool,
        capture_output: bool,
        timeout: float,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[bytes]:
        del check, capture_output, timeout, env
        calls.append(arguments)
        if "start" in arguments:
            workspace = staging_root / "office-conversion" / ("officeconv_" + "3" * 32)
            output = workspace / "converted/original.pdf"
            output.parent.mkdir(mode=0o700)
            output.write_bytes(b"%PDF-1.7\nconverted")
            output.chmod(0o600)
            return subprocess.CompletedProcess(arguments, 0, b"", b"")
        return subprocess.CompletedProcess(arguments, 0, b"LibreOffice 24.2.7.2\n", b"")

    converter = SystemdOfficeDocumentConverter(
        staging_root,
        systemctl=Path("/bin/true"),
        libreoffice=Path("/bin/true"),
        h2orestart_jar=Path("/bin/true"),
        run=fake_run,
        token_hex=lambda _: "3" * 32,
    )
    workspace = converter.create_workspace()
    (workspace / "original.hwpx").write_bytes(b"PK\x03\x04test")
    (workspace / "original.hwpx").chmod(0o600)

    identity = converter.convert(workspace, source_format="HWPX")

    assert calls[0][-2:] == [
        "start",
        "eom-office-converter@officeconv_33333333333333333333333333333333.service",
    ]
    assert identity.conversion_kind == "LIBREOFFICE_H2ORESTART_PDF"
    assert identity.libreoffice_version == "LibreOffice 24.2.7.2"


def test_office_converter_unit_and_polkit_are_fixed_and_nas_is_inaccessible() -> None:
    root = Path(__file__).resolve().parents[2]
    unit = (root / "infra/systemd/eom-office-converter@.service").read_text(encoding="utf-8")
    polkit = (root / "infra/polkit/50-eom-worker-units.rules").read_text(encoding="utf-8")

    assert "User=eom-catalog-manager" in unit
    assert "InaccessiblePaths=/mnt/nas" in unit
    assert "PrivateNetwork=true" in unit
    assert "ReadWritePaths=/var/lib/eom-catalog-api/staging/office-conversion/%i" in unit
    assert "eom_catalog_service.office_converter_worker %i" in unit
    assert "^eom-office-converter@officeconv_[0-9a-f]{32}\\.service$" in polkit
    assert 'subject.user === "eom-catalog-manager"' in polkit
