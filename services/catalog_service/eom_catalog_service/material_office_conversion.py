"""Root producer delegates conversion to the unchanged Catalog Office owner."""

import os
import pwd
import stat
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from eom_catalog_contracts.document_review import OfficeDocumentReviewConversionIdentity
from eom_catalog_contracts.material_office_conversion import (
    MaterialOfficeCommand,
    MaterialOfficeReply,
)
from eom_identifiers import sha256_file

from eom_catalog_service.material_learning_source import (
    MaterialSourceFileFingerprint,
    validate_material_source_file,
)
from eom_catalog_service.office_converter_worker import INSTANCE_PATTERN
from eom_catalog_service.office_document_converter import SystemdOfficeDocumentConverter

_STAGING = Path("/var/lib/eom-catalog-api/staging")
_ROOT = _STAGING / "office-conversion"


def run_in_catalog_owner() -> None:
    """Only this trusted helper receives the fixed conversion command, never DB/auth."""
    if os.geteuid() != pwd.getpwnam("eom-catalog-manager").pw_uid:
        raise ValueError("MATERIAL_OFFICE_CONVERTER_OWNER_INVALID")
    raw = sys.argv[-1]
    if len(raw) > 4096:
        raise ValueError("MATERIAL_OFFICE_COMMAND_INVALID")
    command = MaterialOfficeCommand.model_validate_json(raw)
    converter = SystemdOfficeDocumentConverter(_STAGING)
    workspace = converter.get_or_create_workspace(command.instance_id)
    conversion = None
    if command.operation != "CREATE":
        source = workspace / ("original." + command.source_format.lower())
        metadata = source.lstat()
        if (
            source.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.geteuid()
            or not 8 <= metadata.st_size <= 256 * 1024**2
            or sha256_file(source) != command.source_sha256
        ):
            raise ValueError("MATERIAL_OFFICE_SOURCE_INVALID")
        if command.operation == "READ" or (workspace / "conversion-outcome.json").exists():
            assert command.source_sha256 is not None
            conversion = converter.read_completed(
                workspace,
                source_format=command.source_format,
                expected_source_sha256=command.source_sha256,
            )
        else:
            conversion = converter.convert(workspace, source_format=command.source_format)
    print(
        MaterialOfficeReply(
            operation=command.operation,
            instance_id=command.instance_id,
            source_sha256=command.source_sha256,
            conversion=conversion,
        ).model_dump_json(),
        flush=True,
    )


class CatalogOwnerMaterialOfficeConverter:
    """Same converter port; only exact temporary input ownership is handed off."""

    def __init__(self) -> None:
        if os.geteuid() != 0:
            raise ValueError("MATERIAL_OFFICE_COORDINATOR_INVALID")
        tools = SystemdOfficeDocumentConverter(_STAGING)
        self.libreoffice, self.h2orestart_bundle = tools.libreoffice, tools.h2orestart_bundle

    def _call(self, command: MaterialOfficeCommand) -> MaterialOfficeReply:
        package = Path(__file__).resolve().parents[1]
        for path in (package, Path(__file__).resolve()):
            info = path.stat()
            if info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022:
                raise ValueError("MATERIAL_OFFICE_INSTALLED_SOURCE_INVALID")
        properties = (
            "NoNewPrivileges=yes",
            "PrivateTmp=yes",
            "PrivateNetwork=yes",
            "ProtectHome=yes",
            "ProtectSystem=strict",
            "RuntimeMaxSec=240",
            "ReadWritePaths=" + str(_ROOT),
            "InaccessiblePaths=/mnt/nas /home/eom/EOM /home/eom/EOMIS /etc/eom "
            "/root/.codex /srv/eom/worker-homes /var/run/docker.sock",
        )
        args = [
            "/usr/bin/systemd-run",
            "--quiet",
            "--wait",
            "--pipe",
            "--collect",
            "--unit=eom-material-office-" + uuid4().hex[:20],
            "--uid=eom-catalog-manager",
            "--gid=eom-api",
            "--service-type=exec",
        ]
        args.extend(flag for prop in properties for flag in ("--property", prop))
        args.extend(
            (
                "--",
                sys.executable,
                "-I",
                "-B",
                "-c",
                "import sys; sys.path.insert(0, " + repr(str(package)) + "); "
                "from eom_catalog_service.material_office_conversion import run_in_catalog_owner; "
                "run_in_catalog_owner()",
                command.model_dump_json(),
            )
        )
        try:
            completed = subprocess.run(
                args,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=255,
                check=False,
                env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError("MATERIAL_OFFICE_CONVERSION_FAILED") from error
        if completed.returncode or len(completed.stdout) > 8192 or len(completed.stderr) > 65536:
            raise ValueError("MATERIAL_OFFICE_CONVERSION_FAILED")
        reply = MaterialOfficeReply.model_validate_json(completed.stdout)
        if (reply.operation, reply.instance_id, reply.source_sha256) != (
            command.operation,
            command.instance_id,
            command.source_sha256,
        ):
            raise ValueError("MATERIAL_OFFICE_REPLY_MISMATCH")
        return reply

    def get_or_create_workspace(self, instance_id: str) -> Path:
        self._call(
            MaterialOfficeCommand(
                operation="CREATE",
                instance_id=instance_id,
                source_format="HWPX",
                source_sha256=None,
            )
        )
        return _ROOT / instance_id

    def _source(self, workspace: Path, source_format: str) -> tuple[Path, os.stat_result]:
        if (
            os.geteuid() != 0
            or workspace.parent != _ROOT
            or workspace.resolve() != workspace
            or INSTANCE_PATTERN.fullmatch(workspace.name) is None
            or source_format not in {"HWP", "HWPX"}
        ):
            raise ValueError("MATERIAL_OFFICE_COMMAND_INVALID")
        account = pwd.getpwnam("eom-catalog-manager")
        for directory in (_ROOT, workspace):
            metadata = directory.lstat()
            if (
                directory.is_symlink()
                or not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != account.pw_uid
                or metadata.st_mode & 0o077
            ):
                raise ValueError("MATERIAL_OFFICE_WORKSPACE_INVALID")
        source = workspace / ("original." + source_format.lower())
        metadata = source.lstat()
        if (
            source.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid not in {0, account.pw_uid}
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or not 8 <= metadata.st_size <= 256 * 1024**2
        ):
            raise ValueError("MATERIAL_OFFICE_SOURCE_INVALID")
        return source, metadata

    def validate_source(
        self, workspace: Path, *, fingerprint: MaterialSourceFileFingerprint
    ) -> None:
        """Accept the two exact handoff owners, never the observed UID by itself."""
        source, metadata = self._source(workspace, fingerprint.source_format)
        validate_material_source_file(source, fingerprint, expected_owner_uid=metadata.st_uid)

    def _read(
        self, workspace: Path, *, source_format: str, operation: str, expected: str | None = None
    ) -> OfficeDocumentReviewConversionIdentity:
        source, metadata = self._source(workspace, source_format)
        account = pwd.getpwnam("eom-catalog-manager")
        digest = sha256_file(source)
        if expected is not None and digest != expected:
            raise ValueError("MATERIAL_OFFICE_SOURCE_INVALID")
        if metadata.st_uid == 0:
            os.chown(source, account.pw_uid, account.pw_gid)
        reply = self._call(
            MaterialOfficeCommand.model_validate(
                dict(
                    operation=operation,
                    instance_id=workspace.name,
                    source_format=source_format,
                    source_sha256=digest,
                )
            )
        )
        assert reply.conversion is not None
        return reply.conversion

    def convert(
        self, workspace: Path, *, source_format: str
    ) -> OfficeDocumentReviewConversionIdentity:
        return self._read(workspace, source_format=source_format, operation="CONVERT")

    def read_completed(
        self, workspace: Path, *, source_format: str, expected_source_sha256: str
    ) -> OfficeDocumentReviewConversionIdentity:
        return self._read(
            workspace,
            source_format=source_format,
            operation="READ",
            expected=expected_source_sha256,
        )
