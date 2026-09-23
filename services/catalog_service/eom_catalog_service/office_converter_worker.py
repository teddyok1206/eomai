"""Fixed-workspace LibreOffice converter executed only by a sandboxed systemd unit."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import sys
import zipfile
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import Final

from eom_catalog_contracts import OfficeDocumentConversionOutcome
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_file

CONVERSION_ROOT: Final = Path("/var/lib/eom-catalog-api/staging/office-conversion")
LIBREOFFICE: Final = Path("/usr/bin/libreoffice")
LIBREOFFICE_MATH_COMPONENT: Final = Path("/usr/lib/libreoffice/program/libsmlo.so")
UNOPKG: Final = Path("/usr/bin/unopkg")
H2ORESTART_BUNDLE: Final = Path("/srv/eom/vendor/h2orestart/0.7.14-eom.1/H2Orestart.oxt")
H2ORESTART_BUNDLE_SHA256: Final = "2b3ead8f1c782ba47cdc800262e99196850b525347843f0bd9b76e8431a7de96"
MAX_SOURCE_BYTES: Final = 256 * 1024 * 1024
MAX_OUTPUT_BYTES: Final = 256 * 1024 * 1024
MAX_HWPX_MEMBERS: Final = 4096
MAX_HWPX_EXPANDED_BYTES: Final = 512 * 1024 * 1024
MAX_LOG_BYTES: Final = 256 * 1024
INSTANCE_PATTERN: Final = re.compile(r"^officeconv_[0-9a-f]{32}$")
HWP_SIGNATURE: Final = bytes.fromhex("d0cf11e0a1b11ae1")
PDF_SIGNATURE: Final = re.compile(rb"^%PDF-[12]\.[0-9]")


class OfficeConverterError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "OFFICE_DOCUMENT_CONVERSION_EXECUTION_FAILED",
        stage: str = "LIBREOFFICE_EXECUTION",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage


def _require_regular(
    path: Path,
    *,
    minimum: int,
    maximum: int,
    owner_uid: int | None = None,
) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise OfficeConverterError("required conversion file is unavailable") from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or not minimum <= metadata.st_size <= maximum
        or (owner_uid is not None and metadata.st_uid != owner_uid)
    ):
        raise OfficeConverterError("conversion file metadata is unsafe")
    return metadata


def _require_tool(path: Path, *, executable: bool) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise OfficeConverterError("Office converter dependency is unavailable") from exc
    metadata = _require_regular(resolved, minimum=1, maximum=256 * 1024 * 1024)
    if (
        metadata.st_uid != 0
        or metadata.st_gid != 0
        or metadata.st_mode & 0o022
        or not os.access(resolved, os.X_OK if executable else os.R_OK)
    ):
        raise OfficeConverterError("Office converter dependency identity is unsafe")
    return resolved


def _safe_member_name(name: str) -> bool:
    member = PurePosixPath(name)
    return (
        bool(name)
        and "\\" not in name
        and not member.is_absolute()
        and ".." not in member.parts
        and not name.startswith("/")
    )


def _validate_hwpx(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if not 1 <= len(infos) <= MAX_HWPX_MEMBERS:
                raise OfficeConverterError("HWPX member count is invalid")
            if infos[0].filename != "mimetype" or infos[0].compress_type != zipfile.ZIP_STORED:
                raise OfficeConverterError("HWPX mimetype is not the first stored member")
            seen: set[str] = set()
            total = 0
            for info in infos:
                folded = info.filename.casefold()
                unix_mode = (info.external_attr >> 16) & 0o170000
                if (
                    not _safe_member_name(info.filename)
                    or info.is_dir()
                    or folded in seen
                    or unix_mode not in {0, stat.S_IFREG}
                ):
                    raise OfficeConverterError("HWPX contains an unsafe member")
                seen.add(folded)
                total += info.file_size
                if total > MAX_HWPX_EXPANDED_BYTES:
                    raise OfficeConverterError("HWPX expands beyond the safe bound")
                if info.file_size and info.compress_size == 0:
                    raise OfficeConverterError("HWPX compression metadata is invalid")
                if info.compress_size and info.file_size / info.compress_size > 200:
                    raise OfficeConverterError("HWPX compression ratio exceeds the safe bound")
            if archive.read("mimetype") != b"application/hwp+zip":
                raise OfficeConverterError("HWPX mimetype bytes differ")
    except (KeyError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
        if isinstance(exc, OfficeConverterError):
            raise
        raise OfficeConverterError("HWPX package cannot be read safely") from exc


def validate_office_source(path: Path, source_format: str, owner_uid: int) -> None:
    """Validate one bounded Office source before admission or conversion."""

    _require_regular(path, minimum=8, maximum=MAX_SOURCE_BYTES, owner_uid=owner_uid)
    with path.open("rb") as stream:
        prefix = stream.read(8)
    if source_format == "HWP":
        if prefix != HWP_SIGNATURE:
            raise OfficeConverterError("HWP source signature is invalid")
    elif source_format == "HWPX":
        if not prefix.startswith(b"PK\x03\x04"):
            raise OfficeConverterError("HWPX source signature is invalid")
        _validate_hwpx(path)
    else:
        raise OfficeConverterError("Office source format is unsupported")


def _bounded_log(path: Path) -> None:
    metadata = _require_regular(path, minimum=0, maximum=MAX_LOG_BYTES, owner_uid=os.getuid())
    if metadata.st_mode & 0o077:
        raise OfficeConverterError("Office converter log permissions are unsafe")


def convert_workspace(
    instance: str,
    *,
    conversion_root: Path = CONVERSION_ROOT,
    libreoffice: Path = LIBREOFFICE,
    libreoffice_math_component: Path = LIBREOFFICE_MATH_COMPONENT,
    unopkg: Path = UNOPKG,
    h2orestart_bundle: Path = H2ORESTART_BUNDLE,
    h2orestart_bundle_sha256: str = H2ORESTART_BUNDLE_SHA256,
    run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> Path:
    """Convert the one fixed source member in an already staged private workspace."""

    if INSTANCE_PATTERN.fullmatch(instance) is None:
        raise OfficeConverterError("Office conversion instance identity is invalid")
    workspace = conversion_root / instance
    try:
        workspace_metadata = workspace.lstat()
    except OSError as exc:
        raise OfficeConverterError("Office conversion workspace is unavailable") from exc
    if (
        workspace.is_symlink()
        or not stat.S_ISDIR(workspace_metadata.st_mode)
        or workspace_metadata.st_uid != os.getuid()
        or workspace_metadata.st_mode & 0o077
    ):
        raise OfficeConverterError("Office conversion workspace metadata is unsafe")
    source_candidates = tuple(
        path for path in (workspace / "original.hwp", workspace / "original.hwpx") if path.exists()
    )
    if len(source_candidates) != 1:
        raise OfficeConverterError("Office conversion requires exactly one source")
    source = source_candidates[0]
    source_format = "HWPX" if source.suffix.casefold() == ".hwpx" else "HWP"
    try:
        validate_office_source(source, source_format, os.getuid())
    except OfficeConverterError as exc:
        raise OfficeConverterError(
            str(exc),
            code="OFFICE_DOCUMENT_CONVERSION_SOURCE_INVALID",
            stage="SOURCE_VALIDATION",
        ) from exc
    try:
        actual_libreoffice = _require_tool(libreoffice, executable=True)
        _require_tool(libreoffice_math_component, executable=False)
        actual_unopkg = _require_tool(unopkg, executable=True)
        actual_h2orestart_bundle = _require_tool(h2orestart_bundle, executable=False)
    except OfficeConverterError as exc:
        raise OfficeConverterError(
            str(exc),
            code="OFFICE_DOCUMENT_CONVERSION_DEPENDENCY_INVALID",
            stage="DEPENDENCY_VALIDATION",
        ) from exc
    with actual_h2orestart_bundle.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != h2orestart_bundle_sha256:
            raise OfficeConverterError(
                "H2Orestart bundle hash differs from the reviewed release",
                code="OFFICE_DOCUMENT_CONVERSION_DEPENDENCY_INVALID",
                stage="DEPENDENCY_VALIDATION",
            )
    output_directory = workspace / "converted"
    profile_directory = workspace / "profile"
    home_directory = workspace / "home"
    cache_directory = workspace / "cache"
    for directory in (output_directory, profile_directory, home_directory, cache_directory):
        directory.mkdir(mode=0o700)
    output = output_directory / "original.pdf"
    stdout = workspace / "libreoffice.stdout.log"
    stderr = workspace / "libreoffice.stderr.log"
    with stdout.open("xb") as stdout_stream, stderr.open("xb") as stderr_stream:
        stdout.chmod(0o600)
        stderr.chmod(0o600)
        try:
            registered = run(
                [
                    str(actual_unopkg),
                    f"-env:UserInstallation={profile_directory.as_uri()}",
                    "add",
                    "--force",
                    "--suppress-license",
                    str(actual_h2orestart_bundle),
                ],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=stdout_stream,
                stderr=stderr_stream,
                timeout=30,
                env={
                    "HOME": str(home_directory),
                    "XDG_CACHE_HOME": str(cache_directory),
                    "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8",
                    "PATH": "/usr/bin:/bin",
                    "TZ": "UTC",
                },
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OfficeConverterError(
                "H2Orestart profile registration failed to execute",
                code="OFFICE_DOCUMENT_CONVERSION_EXTENSION_FAILED",
                stage="EXTENSION_REGISTRATION",
            ) from exc
        if registered.returncode != 0:
            raise OfficeConverterError(
                "H2Orestart profile registration returned failure",
                code="OFFICE_DOCUMENT_CONVERSION_EXTENSION_FAILED",
                stage="EXTENSION_REGISTRATION",
            )
        try:
            completed = run(
                [
                    str(actual_libreoffice),
                    f"-env:UserInstallation={profile_directory.as_uri()}",
                    "--headless",
                    "--invisible",
                    "--nologo",
                    "--nodefault",
                    "--nofirststartwizard",
                    "--norestore",
                    "--nolockcheck",
                    "--convert-to",
                    "pdf:writer_pdf_Export",
                    "--outdir",
                    str(output_directory),
                    str(source),
                ],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=stdout_stream,
                stderr=stderr_stream,
                timeout=150,
                env={
                    "HOME": str(home_directory),
                    # H2Orestart resolves XDG_CACHE_HOME before falling back to the
                    # account home.  The account home is intentionally read-only in the
                    # converter sandbox, so keep its logger cache inside this one request.
                    "XDG_CACHE_HOME": str(cache_directory),
                    "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8",
                    "PATH": "/usr/bin:/bin",
                    "SAL_USE_VCLPLUGIN": "svp",
                    "TZ": "UTC",
                },
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OfficeConverterError(
                "LibreOffice conversion failed to execute",
                code="OFFICE_DOCUMENT_CONVERSION_EXECUTION_FAILED",
                stage="LIBREOFFICE_EXECUTION",
            ) from exc
    _bounded_log(stdout)
    _bounded_log(stderr)
    if completed.returncode != 0:
        raise OfficeConverterError(
            "LibreOffice conversion returned failure",
            code="OFFICE_DOCUMENT_CONVERSION_RETURNED_FAILURE",
            stage="LIBREOFFICE_EXECUTION",
        )
    try:
        _require_regular(output, minimum=8, maximum=MAX_OUTPUT_BYTES, owner_uid=os.getuid())
    except OfficeConverterError as exc:
        raise OfficeConverterError(
            str(exc),
            code=(
                "OFFICE_DOCUMENT_CONVERSION_OUTPUT_MISSING"
                if not output.exists()
                else "OFFICE_DOCUMENT_CONVERSION_OUTPUT_INVALID"
            ),
            stage="OUTPUT_VALIDATION",
        ) from exc
    with output.open("rb") as stream:
        if PDF_SIGNATURE.fullmatch(stream.read(8)) is None:
            raise OfficeConverterError(
                "LibreOffice output is not a supported PDF",
                code="OFFICE_DOCUMENT_CONVERSION_OUTPUT_INVALID",
                stage="OUTPUT_VALIDATION",
            )
    output.chmod(0o600)
    return output


def _write_outcome(
    instance: str,
    *,
    error: OfficeConverterError | None,
    conversion_root: Path = CONVERSION_ROOT,
    h2orestart_bundle: Path = H2ORESTART_BUNDLE,
) -> None:
    workspace = conversion_root / instance
    candidates = tuple(
        path for path in (workspace / "original.hwp", workspace / "original.hwpx") if path.exists()
    )
    if len(candidates) != 1:
        return
    source = candidates[0]
    source_metadata = _require_regular(
        source,
        minimum=8,
        maximum=MAX_SOURCE_BYTES,
        owner_uid=os.getuid(),
    )
    stdout = workspace / "libreoffice.stdout.log"
    stderr = workspace / "libreoffice.stderr.log"
    for log in (stdout, stderr):
        if not log.exists():
            descriptor = os.open(
                log,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
                0o600,
            )
            os.close(descriptor)
        _bounded_log(log)
    output = workspace / "converted/original.pdf"
    value: dict[str, object] = {
        "schema_version": "office-document-conversion-outcome/1.0",
        "instance_id": instance,
        "status": "ERROR" if error is not None else "OK",
        "stage": error.stage if error is not None else "OUTPUT_VALIDATED",
        "source_format": "HWPX" if source.suffix.casefold() == ".hwpx" else "HWP",
        "source_sha256": sha256_file(source),
        "source_bytes": source_metadata.st_size,
        "h2orestart_sha256": sha256_file(h2orestart_bundle),
        "stdout_sha256": sha256_file(stdout),
        "stdout_bytes": stdout.stat().st_size,
        "stderr_sha256": sha256_file(stderr),
        "stderr_bytes": stderr.stat().st_size,
    }
    if error is None:
        output_metadata = _require_regular(
            output,
            minimum=8,
            maximum=MAX_OUTPUT_BYTES,
            owner_uid=os.getuid(),
        )
        value["output_sha256"] = sha256_file(output)
        value["output_bytes"] = output_metadata.st_size
    else:
        value["error_code"] = error.code
    value["outcome_sha256"] = content_sha256(value)
    outcome = OfficeDocumentConversionOutcome.model_validate(value)
    payload = canonical_json_bytes(outcome.model_dump(mode="json", exclude_none=True))
    target = workspace / "conversion-outcome.json"
    descriptor = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written < 1:
                raise OfficeConverterError("conversion outcome write made no progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        return 64
    try:
        convert_workspace(arguments[0])
    except OfficeConverterError as exc:
        with suppress(OSError, ValueError, OfficeConverterError):
            _write_outcome(arguments[0], error=exc)
        return 1
    except (OSError, RuntimeError, ValueError):
        error = OfficeConverterError(
            "Office conversion failed before a typed adapter result was available",
            code="OFFICE_DOCUMENT_CONVERSION_EXECUTION_FAILED",
            stage="LIBREOFFICE_EXECUTION",
        )
        with suppress(OSError, ValueError, OfficeConverterError):
            _write_outcome(arguments[0], error=error)
        return 1
    try:
        _write_outcome(arguments[0], error=None)
    except (OSError, ValueError, OfficeConverterError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
