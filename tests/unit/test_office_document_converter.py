from __future__ import annotations

import hashlib
import stat
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_service.office_converter_worker import (
    H2ORESTART_BUNDLE,
    H2ORESTART_BUNDLE_SHA256,
    LIBREOFFICE_MATH_COMPONENT,
    OfficeConverterError,
    _write_outcome,
    convert_workspace,
    validate_office_source,
)
from eom_catalog_service.office_document_converter import (
    OfficeDocumentConversionError,
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
    calls: list[list[str]] = []

    def fake_run(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(arguments)
        assert kwargs["env"]["XDG_CACHE_HOME"] == str(workspace / "cache")
        assert (workspace / "cache").stat().st_mode & 0o777 == 0o700
        if "--outdir" in arguments:
            output_directory = Path(arguments[arguments.index("--outdir") + 1])
            (output_directory / "original.pdf").write_bytes(b"%PDF-1.7\nconverted")
        return subprocess.CompletedProcess(arguments, 0, b"", b"")

    output = convert_workspace(
        instance,
        conversion_root=tmp_path,
        libreoffice=Path("/bin/true"),
        libreoffice_math_component=Path("/bin/true"),
        unopkg=Path("/bin/true"),
        h2orestart_bundle=Path("/bin/true"),
        h2orestart_bundle_sha256=hashlib.sha256(Path("/bin/true").read_bytes()).hexdigest(),
        run=fake_run,
    )

    assert output.read_bytes().startswith(b"%PDF-1.7")
    assert output.stat().st_mode & 0o777 == 0o600
    assert calls[0][1:5] == [
        f"-env:UserInstallation={(workspace / 'profile').as_uri()}",
        "add",
        "--force",
        "--suppress-license",
    ]
    assert calls[0][-1] == "/usr/bin/true"
    assert "--outdir" in calls[1]


def test_fixed_workspace_worker_rejects_unreviewed_extension_bundle(tmp_path: Path) -> None:
    instance = "officeconv_" + "4" * 32
    workspace = tmp_path / instance
    workspace.mkdir(mode=0o700)
    _write_minimal_hwpx(workspace / "original.hwpx")

    with pytest.raises(OfficeConverterError, match="bundle hash differs"):
        convert_workspace(
            instance,
            conversion_root=tmp_path,
            libreoffice=Path("/bin/true"),
            libreoffice_math_component=Path("/bin/true"),
            unopkg=Path("/bin/true"),
            h2orestart_bundle=Path("/bin/true"),
            h2orestart_bundle_sha256="0" * 64,
        )


def test_fixed_workspace_worker_pins_compatibility_extension_identity() -> None:
    assert Path("/srv/eom/vendor/h2orestart/0.7.14-eom.1/H2Orestart.oxt") == H2ORESTART_BUNDLE
    assert H2ORESTART_BUNDLE_SHA256 == (
        "2b3ead8f1c782ba47cdc800262e99196850b525347843f0bd9b76e8431a7de96"
    )
    assert Path("/usr/lib/libreoffice/program/libsmlo.so") == LIBREOFFICE_MATH_COMPONENT


def test_fixed_workspace_worker_requires_libreoffice_math_component(tmp_path: Path) -> None:
    instance = "officeconv_" + "5" * 32
    workspace = tmp_path / instance
    workspace.mkdir(mode=0o700)
    _write_minimal_hwpx(workspace / "original.hwpx")

    with pytest.raises(OfficeConverterError, match="dependency is unavailable") as error:
        convert_workspace(
            instance,
            conversion_root=tmp_path,
            libreoffice=Path("/bin/true"),
            libreoffice_math_component=tmp_path / "missing-libsmlo.so",
            unopkg=Path("/bin/true"),
            h2orestart_bundle=Path("/bin/true"),
            h2orestart_bundle_sha256=hashlib.sha256(Path("/bin/true").read_bytes()).hexdigest(),
        )

    assert error.value.code == "OFFICE_DOCUMENT_CONVERSION_DEPENDENCY_INVALID"
    assert error.value.stage == "DEPENDENCY_VALIDATION"


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
            libreoffice_math_component=Path("/bin/true"),
            unopkg=Path("/bin/true"),
            h2orestart_bundle=Path("/bin/true"),
            h2orestart_bundle_sha256=hashlib.sha256(Path("/bin/true").read_bytes()).hexdigest(),
        )


def test_shared_office_source_validation_rejects_unsafe_hwpx_before_conversion(
    tmp_path: Path,
) -> None:
    source = tmp_path / "unsafe.hwpx"
    with zipfile.ZipFile(source, "x") as archive:
        archive.writestr(_zip_info("mimetype", stored=True), b"application/hwp+zip")
        archive.writestr(_zip_info("../escape.xml"), b"<escape/>")
    source.chmod(0o600)

    with pytest.raises(OfficeConverterError, match="unsafe member"):
        validate_office_source(source, "HWPX", source.stat().st_uid)


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
            (workspace / "libreoffice.stdout.log").write_bytes(b"")
            (workspace / "libreoffice.stderr.log").write_bytes(b"")
            (workspace / "libreoffice.stdout.log").chmod(0o600)
            (workspace / "libreoffice.stderr.log").chmod(0o600)
            _write_outcome(
                workspace.name,
                error=None,
                conversion_root=workspace.parent,
                h2orestart_bundle=Path("/bin/true"),
            )
            return subprocess.CompletedProcess(arguments, 0, b"", b"")
        return subprocess.CompletedProcess(arguments, 0, b"LibreOffice 24.2.7.2\n", b"")

    converter = SystemdOfficeDocumentConverter(
        staging_root,
        systemctl=Path("/bin/true"),
        libreoffice=Path("/bin/true"),
        h2orestart_bundle=Path("/bin/true"),
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


def test_catalog_adapter_returns_exact_typed_converter_failure(tmp_path: Path) -> None:
    staging_root = tmp_path / "staging"
    staging_root.mkdir(mode=0o700)

    def fake_run(
        arguments: list[str],
        *,
        check: bool,
        capture_output: bool,
        timeout: float,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[bytes]:
        del check, capture_output, timeout, env
        workspace = staging_root / "office-conversion" / ("officeconv_" + "6" * 32)
        (workspace / "libreoffice.stdout.log").write_bytes(b"")
        (workspace / "libreoffice.stderr.log").write_bytes(b"bounded failure")
        (workspace / "libreoffice.stdout.log").chmod(0o600)
        (workspace / "libreoffice.stderr.log").chmod(0o600)
        _write_outcome(
            workspace.name,
            error=OfficeConverterError(
                "conversion returned failure",
                code="OFFICE_DOCUMENT_CONVERSION_RETURNED_FAILURE",
                stage="LIBREOFFICE_EXECUTION",
            ),
            conversion_root=workspace.parent,
            h2orestart_bundle=Path("/bin/true"),
        )
        return subprocess.CompletedProcess(arguments, 1, b"", b"")

    converter = SystemdOfficeDocumentConverter(
        staging_root,
        systemctl=Path("/bin/true"),
        libreoffice=Path("/bin/true"),
        h2orestart_bundle=Path("/bin/true"),
        run=fake_run,
        token_hex=lambda _: "6" * 32,
    )
    workspace = converter.create_workspace()
    (workspace / "original.hwpx").write_bytes(b"PK\x03\x04test")
    (workspace / "original.hwpx").chmod(0o600)

    with pytest.raises(
        OfficeDocumentConversionError,
        match="typed converter stage",
    ) as error:
        converter.convert(workspace, source_format="HWPX")

    assert error.value.code == "OFFICE_DOCUMENT_CONVERSION_RETURNED_FAILURE"


def test_office_converter_unit_and_polkit_are_fixed_and_nas_is_inaccessible() -> None:
    root = Path(__file__).resolve().parents[2]
    unit = (root / "infra/systemd/eom-office-converter@.service").read_text(encoding="utf-8")
    polkit = (root / "infra/polkit/50-eom-worker-units.rules").read_text(encoding="utf-8")

    assert "User=eom-catalog-manager" in unit
    assert "InaccessiblePaths=/mnt/nas" in unit
    assert "PrivateNetwork=true" in unit
    assert "ReadWritePaths=/var/lib/eom-catalog-api/staging/office-conversion/%i" in unit
    assert "ReadOnlyPaths=/srv/eom/vendor/h2orestart/0.7.14-eom.1/H2Orestart.oxt" in unit
    assert "eom_catalog_service.office_converter_worker %i" in unit
    assert "^eom-office-converter@officeconv_[0-9a-f]{32}\\.service$" in polkit
    assert 'subject.user === "eom-catalog-manager"' in polkit


def test_office_converter_installer_pins_reviewed_ubuntu_packages() -> None:
    root = Path(__file__).resolve().parents[2]
    installer = (root / "scripts/catalog/install_office_document_converter.sh").read_text(
        encoding="utf-8"
    )

    assert "libreoffice-writer" in installer
    assert "libreoffice-math" in installer
    assert "libreoffice-h2orestart" in installer
    assert "/usr/lib/libreoffice/program/libsmlo.so" in installer
    assert "/etc/libreoffice/registry/math.xcd" in installer
    assert '"${libreoffice_math_version}" == "${libreoffice_version}"' in installer
    assert '"${verify_only}" == false' in installer
    assert '"${VERSION_ID:-}" == "24.04"' in installer
    assert '"${libreoffice_version}" == 4:24.2.*' in installer
    assert '"${distribution_h2orestart_version}" == 0.6.*' in installer
    assert "H2ORESTART_VERSION=0.7.14-eom.1" in installer
    assert "H2ORESTART_DECLARED_VERSION=0.7.14.1" in installer
    assert "2b3ead8f1c782ba47cdc800262e99196850b525347843f0bd9b76e8431a7de96" in installer
    assert "ea68732e8ac46f088cdff378c3b184d9251e8703874446c382b04393b0405fa2" in installer
    assert "ConvGraphics-crop-compatibility.patch" in installer
    assert "--no-install-recommends" in installer
    assert "curl" not in installer and "wget" not in installer


def test_deployers_close_office_converter_dependency_set() -> None:
    root = Path(__file__).resolve().parents[2]
    release = (root / "scripts/api/deploy_release.sh").read_text(encoding="utf-8")
    identities = (root / "scripts/infra/deploy_service_identities.sh").read_text(encoding="utf-8")

    assert 'sudo -n "${OFFICE_CONVERTER_INSTALLER}"' in release
    assert 'sudo -n "${OFFICE_CONVERTER_INSTALLER}" --verify' in release
    assert '"${REPOSITORY}/scripts/catalog/install_office_document_converter.sh"' in identities


def test_h2orestart_compatibility_patch_is_pinned_and_bounded() -> None:
    root = Path(__file__).resolve().parents[2]
    patch = root / "third_party/h2orestart/0.7.14-eom.1/ConvGraphics-crop-compatibility.patch"
    content = patch.read_text(encoding="utf-8")

    assert hashlib.sha256(patch.read_bytes()).hexdigest() == (
        "ea68732e8ac46f088cdff378c3b184d9251e8703874446c382b04393b0405fa2"
    )
    assert "new ByteArrayInputStream(imageAsByteArray)" in content
    assert "GraphicProvider.storeGraphic can abort" in content
    assert "catch (IOException | RuntimeException e)" in content
    assert content.count("source/soffice/ConvGraphics.java") == 4
