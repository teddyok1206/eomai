"""Catalog adapter for the fixed sandboxed Office-to-PDF converter unit."""

from __future__ import annotations

import os
import secrets
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Final, Protocol

from eom_catalog_contracts import OfficeDocumentReviewConversionIdentity
from eom_identifiers import sha256_file

from eom_catalog_service.office_converter_worker import (
    H2ORESTART_JAR,
    INSTANCE_PATTERN,
    LIBREOFFICE,
    MAX_OUTPUT_BYTES,
    PDF_SIGNATURE,
)

SYSTEMCTL: Final = Path("/usr/bin/systemctl")
CONVERSION_DIRECTORY: Final = "office-conversion"


class OfficeDocumentConversionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CommandRunner(Protocol):
    def __call__(
        self,
        arguments: list[str],
        *,
        check: bool,
        capture_output: bool,
        timeout: float,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[bytes]: ...


def _run_command(
    arguments: list[str],
    *,
    check: bool,
    capture_output: bool,
    timeout: float,
    env: dict[str, str],
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        arguments,
        check=check,
        capture_output=capture_output,
        timeout=timeout,
        env=env,
    )


def _require_root_file(path: Path, *, executable: bool) -> Path:
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as exc:
        raise OfficeDocumentConversionError(
            "OFFICE_DOCUMENT_CONVERTER_UNAVAILABLE",
            "Office converter dependency is unavailable",
        ) from exc
    required_access = os.X_OK if executable else os.R_OK
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or metadata.st_mode & 0o022
        or not os.access(resolved, required_access)
    ):
        raise OfficeDocumentConversionError(
            "OFFICE_DOCUMENT_CONVERTER_IDENTITY_INVALID",
            "Office converter dependency identity is unsafe",
        )
    return resolved


def _version(
    libreoffice: Path,
    *,
    run: CommandRunner,
) -> str:
    try:
        completed = run(
            [str(libreoffice), "--version"],
            check=False,
            capture_output=True,
            timeout=10.0,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OfficeDocumentConversionError(
            "OFFICE_DOCUMENT_CONVERTER_UNAVAILABLE",
            "Office converter version could not be read",
        ) from exc
    if completed.returncode != 0 or not 1 <= len(completed.stdout) <= 4096:
        raise OfficeDocumentConversionError(
            "OFFICE_DOCUMENT_CONVERTER_VERSION_INVALID",
            "Office converter version response is invalid",
        )
    try:
        version = completed.stdout.decode("utf-8", errors="strict").strip()
    except UnicodeError as exc:
        raise OfficeDocumentConversionError(
            "OFFICE_DOCUMENT_CONVERTER_VERSION_INVALID",
            "Office converter version encoding is invalid",
        ) from exc
    if not version or len(version) > 128:
        raise OfficeDocumentConversionError(
            "OFFICE_DOCUMENT_CONVERTER_VERSION_INVALID",
            "Office converter version is outside the supported bound",
        )
    return version


class SystemdOfficeDocumentConverter:
    """Start only the fixed Office converter unit for one private workspace."""

    def __init__(
        self,
        staging_root: Path,
        *,
        systemctl: Path = SYSTEMCTL,
        libreoffice: Path = LIBREOFFICE,
        h2orestart_jar: Path = H2ORESTART_JAR,
        run: CommandRunner = _run_command,
        token_hex: Callable[[int], str] = secrets.token_hex,
    ) -> None:
        self.staging_root = staging_root
        self.systemctl = _require_root_file(systemctl, executable=True)
        self.libreoffice = _require_root_file(libreoffice, executable=True)
        self.h2orestart_jar = _require_root_file(h2orestart_jar, executable=False)
        self.run = run
        self.token_hex = token_hex

    def create_workspace(self) -> Path:
        root = self.staging_root / CONVERSION_DIRECTORY
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if root.is_symlink() or root.stat().st_mode & 0o077:
            raise OfficeDocumentConversionError(
                "OFFICE_DOCUMENT_CONVERTER_WORKSPACE_INVALID",
                "Office conversion root is unsafe",
            )
        instance = f"officeconv_{self.token_hex(16)}"
        if INSTANCE_PATTERN.fullmatch(instance) is None:
            raise OfficeDocumentConversionError(
                "OFFICE_DOCUMENT_CONVERTER_INSTANCE_INVALID",
                "Office conversion instance identity is invalid",
            )
        workspace = root / instance
        workspace.mkdir(mode=0o700)
        return workspace

    def convert(
        self, workspace: Path, *, source_format: str
    ) -> OfficeDocumentReviewConversionIdentity:
        if (
            workspace.parent != self.staging_root / CONVERSION_DIRECTORY
            or INSTANCE_PATTERN.fullmatch(workspace.name) is None
            or source_format not in {"HWP", "HWPX"}
        ):
            raise OfficeDocumentConversionError(
                "OFFICE_DOCUMENT_CONVERTER_REQUEST_INVALID",
                "Office conversion request is outside the fixed workspace contract",
            )
        unit = f"eom-office-converter@{workspace.name}.service"
        try:
            completed = self.run(
                [str(self.systemctl), "start", unit],
                check=False,
                capture_output=True,
                timeout=180.0,
                env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OfficeDocumentConversionError(
                "OFFICE_DOCUMENT_CONVERSION_FAILED",
                "Office conversion unit failed to execute",
            ) from exc
        if (
            completed.returncode != 0
            or len(completed.stdout) > 64 * 1024
            or len(completed.stderr) > 64 * 1024
        ):
            raise OfficeDocumentConversionError(
                "OFFICE_DOCUMENT_CONVERSION_FAILED",
                "Office conversion unit returned failure",
            )
        output = workspace / "converted/original.pdf"
        try:
            metadata = output.lstat()
        except OSError as exc:
            raise OfficeDocumentConversionError(
                "OFFICE_DOCUMENT_CONVERSION_OUTPUT_MISSING",
                "Office conversion PDF is missing",
            ) from exc
        if (
            output.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or not 8 <= metadata.st_size <= MAX_OUTPUT_BYTES
        ):
            raise OfficeDocumentConversionError(
                "OFFICE_DOCUMENT_CONVERSION_OUTPUT_INVALID",
                "Office conversion PDF metadata is unsafe",
            )
        with output.open("rb") as stream:
            if PDF_SIGNATURE.fullmatch(stream.read(8)) is None:
                raise OfficeDocumentConversionError(
                    "OFFICE_DOCUMENT_CONVERSION_OUTPUT_INVALID",
                    "Office conversion output is not a supported PDF",
                )
        return OfficeDocumentReviewConversionIdentity(
            conversion_kind="LIBREOFFICE_H2ORESTART_PDF",
            review_pdf_sha256=sha256_file(output),
            libreoffice_version=_version(self.libreoffice, run=self.run),
            libreoffice_sha256=sha256_file(self.libreoffice),
            h2orestart_sha256=sha256_file(self.h2orestart_jar),
        )
