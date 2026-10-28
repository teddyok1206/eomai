"""Local deployment-owner fence for the installed prelaunch reset command."""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from eom_protocol.prelaunch_item_reset import ResetBackupPin
from sqlalchemy.engine import URL

from eom_orchestrator.settings import _read_secret_environment

RESET_PAUSED_UNITS = (
    "eom-embedding-index-owner.service",
    "eom-reference-query-owner.service",
    "eom-workflow-runner.service",
    "eom-workflow-maintenance.service",
    "eom-hwpx-application-runner.service",
    "eom-catalog-application-runner.service",
    "eom-general-chat.service",
)
BACKUP_ROOT = Path("/mnt/nas/eom/backups/postgresql")


def _file_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


class InstalledPrelaunchResetFence:
    def __init__(self) -> None:
        path = Path(__file__).absolute()
        if len(path.parts) < 8 or path.parts[:4] != ("/", "opt", "eom", "maintenance-releases"):
            raise ValueError("ITEM_RESET_INSTALLED_RELEASE_REQUIRED")
        self.source_commit = path.parts[4]
        if re.fullmatch(r"[0-9a-f]{40}", self.source_commit) is None:
            raise ValueError("ITEM_RESET_INSTALLED_RELEASE_REQUIRED")
        for member in (path, *path.parents):
            meta = member.lstat()
            if stat.S_ISLNK(meta.st_mode) or meta.st_uid != 0 or stat.S_IMODE(meta.st_mode) & 0o022:
                raise ValueError("ITEM_RESET_PROTECTED_RELEASE_REQUIRED")

    def authorize_local_owner(self) -> None:
        if (
            os.getuid() != os.geteuid()
            or os.getgid() != os.getegid()
            or pwd.getpwuid(os.geteuid()).pw_name != "eom"
            or os.geteuid() == 0
        ):
            raise ValueError("ITEM_RESET_LOCAL_OWNER_REQUIRED")

    def verify(self) -> None:
        self.authorize_local_owner()
        for unit in RESET_PAUSED_UNITS:
            result = subprocess.run(
                ["/usr/bin/systemctl", "show", unit, "--property=ActiveState,MainPID,ControlPID"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
            if values != {"ActiveState": "inactive", "MainPID": "0", "ControlPID": "0"}:
                raise ValueError(f"ITEM_RESET_SERVICE_NOT_QUIESCENT:{unit}")
        running = subprocess.run(
            [
                "/usr/bin/systemctl",
                "list-units",
                "--no-legend",
                "--no-pager",
                "--state=running,activating,deactivating",
                "eom-embedding-native*",
                "eom-reference-query-native*",
                "eom-embedding-benchmark-*@*.service",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if running.stdout.strip():
            raise ValueError("ITEM_RESET_NATIVE_EXECUTION_NOT_QUIESCENT")

    def owner_database_url(self) -> URL:
        """Use the existing deployment-owner credential, not a relaxed runtime role."""
        self.authorize_local_owner()
        path = Path("/etc/eom/secrets/postgres.env")
        meta = path.lstat()
        if (
            not stat.S_ISREG(meta.st_mode)
            or meta.st_uid != 0
            or meta.st_nlink != 1
            or stat.S_IMODE(meta.st_mode) & 0o027
            or meta.st_size > 16384
        ):
            raise ValueError("ITEM_RESET_OWNER_CONFIGURATION_INVALID")
        values = _read_secret_environment(path)
        if any(
            not values.get(key) for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
        ):
            raise ValueError("ITEM_RESET_OWNER_CONFIGURATION_INVALID")
        return URL.create(
            "postgresql+psycopg",
            username=values["POSTGRES_USER"],
            password=values["POSTGRES_PASSWORD"],
            host="127.0.0.1",
            port=5432,
            database=values["POSTGRES_DB"],
        )

    def verify_backup(self, database: str, backup: ResetBackupPin) -> None:
        path = BACKUP_ROOT / backup.file_name
        manifest_path = path.with_suffix(".manifest.json")
        meta = manifest_path.lstat()
        if not stat.S_ISREG(meta.st_mode) or meta.st_size > 16384:
            raise ValueError("ITEM_RESET_BACKUP_MANIFEST_INVALID")
        value = json.loads(manifest_path.read_bytes())
        if (
            value.get("database") != database
            or value.get("file") != backup.file_name
            or value.get("sha256") != backup.sha256
            or value.get("size_bytes") != backup.size_bytes
        ):
            raise ValueError("ITEM_RESET_BACKUP_PIN_MISMATCH")
        created = datetime.strptime(value["created_at_utc"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        if not 0 <= (datetime.now(UTC) - created).total_seconds() <= 7200:
            raise ValueError("ITEM_RESET_FRESH_BACKUP_REQUIRED")
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size != backup.size_bytes:
                raise ValueError("ITEM_RESET_BACKUP_BYTES_INVALID")
            digest = hashlib.sha256()
            while data := os.read(descriptor, 1024 * 1024):
                digest.update(data)
            after = os.fstat(descriptor)
            if digest.hexdigest() != backup.sha256 or _file_identity(after) != _file_identity(
                before
            ):
                raise ValueError("ITEM_RESET_BACKUP_BYTES_CHANGED")
        finally:
            os.close(descriptor)
