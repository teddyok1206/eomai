"""PDF/OCR command adapter: root coordinates; eom-image parses local bytes only."""

import os
import pwd
import stat
import subprocess
from pathlib import Path
from uuid import uuid4

from eom_orchestrator.pdf_render_isolation import PDF_RENDER_SANDBOX


def _regular_local(path: str) -> Path:
    value = Path(path)
    metadata = value.lstat()
    if (
        not value.is_absolute()
        or value.resolve() != value
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or not 1 <= metadata.st_size <= 256 * 1024**2
        or any(character in path for character in ":\n\r")
    ):
        raise ValueError("MATERIAL_PDF_SANDBOX_INPUT_INVALID")
    return value


class MaterialPdfSandboxRunner:
    """Reuse the existing PDF sandbox, with one exact read-only input bind.

    A whole PDF is not recopied or streamed once per page. The sole writable
    host directory is a fresh extractor-owned temporary PNG workspace. No DB,
    NAS, auth file or inherited environment is available to parsing subprocesses.
    """

    def __call__(
        self, command: list[str], *, max_output_bytes: int = 4 * 1024 * 1024
    ) -> subprocess.CompletedProcess[bytes]:
        if os.geteuid() != 0 or not command:
            raise ValueError("MATERIAL_PDF_SANDBOX_OWNER_INVALID")
        program = Path(command[0])
        if program not in {
            Path("/usr/bin/pdfinfo"),
            Path("/usr/bin/pdftotext"),
            Path("/usr/bin/pdftoppm"),
            Path("/usr/bin/tesseract"),
        }:
            raise ValueError("MATERIAL_PDF_SANDBOX_PROGRAM_INVALID")
        tool = program.stat()
        if tool.st_uid != 0 or tool.st_mode & 0o022 or not stat.S_ISREG(tool.st_mode):
            raise ValueError("MATERIAL_PDF_SANDBOX_PROGRAM_INVALID")
        arguments = list(command[1:])
        properties = [*PDF_RENDER_SANDBOX, "RuntimeMaxSec=300"]
        if arguments not in (["-v"], ["--version"]):
            source_index = 0 if program.name in {"pdfinfo", "tesseract"} else len(arguments) - 2
            if not 0 <= source_index < len(arguments):
                raise ValueError("MATERIAL_PDF_SANDBOX_COMMAND_INVALID")
            source = _regular_local(arguments[source_index])
            properties += [
                "TemporaryFileSystem=/run/eom-material-pdf:ro",
                f"BindReadOnlyPaths={source}:/run/eom-material-pdf/input",
            ]
            arguments[source_index] = "/run/eom-material-pdf/input"
            if program.name == "pdftoppm":
                destination = Path(arguments[-1])
                parent = destination.parent
                metadata = parent.lstat()
                account = pwd.getpwnam("eom-image")
                if (
                    destination.name != "page"
                    or parent.parent != Path("/tmp")
                    or not parent.name.startswith("eom-textbook-ocr-")
                    or parent.resolve() != parent
                    or not stat.S_ISDIR(metadata.st_mode)
                    or metadata.st_uid not in {0, account.pw_uid}
                    or stat.S_IMODE(metadata.st_mode) != 0o700
                ):
                    raise ValueError("MATERIAL_PDF_SANDBOX_OUTPUT_INVALID")
                os.chown(parent, account.pw_uid, account.pw_gid)
                properties.append(f"BindPaths={parent}:/run/eom-material-pdf/output")
                arguments[-1] = "/run/eom-material-pdf/output/page"
        invocation = [
            "/usr/bin/systemd-run",
            "--quiet",
            "--wait",
            "--pipe",
            "--collect",
            "--unit=eom-material-pdf-" + uuid4().hex[:20],
            "--uid=eom-image",
            "--gid=eom-image",
            "--service-type=exec",
        ]
        invocation.extend(flag for prop in properties for flag in ("--property", prop))
        invocation.extend(("--", str(program), *arguments))
        try:
            result = subprocess.run(
                invocation,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=False,
                timeout=315,
                env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError("MATERIAL_PDF_SANDBOX_EXECUTION_FAILED") from error
        if (
            result.returncode
            or len(result.stdout) > max_output_bytes
            or len(result.stderr) > 1024**2
        ):
            raise ValueError("MATERIAL_PDF_SANDBOX_EXECUTION_FAILED")
        return subprocess.CompletedProcess(command, 0, result.stdout, result.stderr)
