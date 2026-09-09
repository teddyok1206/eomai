"""Trusted, read-only runtime observation for the Stage-C quiescence gate."""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import stat
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, NoReturn, Protocol

from eom_identifiers import content_sha256

AUTOMATION_ENV_PATH = Path("/etc/eom/legacy-item-automation.env")
CATALOG_UNIT = "eom-catalog-application-runner.service"
RUNTIME_DROPIN_ROOT = Path("/run/systemd/system/eom-catalog-application-runner.service.d")
WORKFLOW_HOLD_ROOT = Path("/etc/systemd/system/eom-workflow-runner.service.d")
MAX_AUTOMATION_ENV_BYTES = 64 * 1024
_ENVIRONMENT_FILE = re.compile(r"(?P<path>/[^ ]+) \(ignore_errors=(?:yes|no)\)")
_AUTOMATION_VARIABLE = "EOM_LEGACY_ITEM_AUTOMATION_MODE"
_AUTOMATION_ASSIGNMENT = _AUTOMATION_VARIABLE + "="


class PdfLearningRuntimeError(RuntimeError):
    """A trusted runtime fact could not be observed exactly."""


@dataclass(frozen=True)
class PdfLearningRuntimeObservation:
    automation_mode: Literal["DISABLED"]
    volatile_auto_overlay_present: Literal[False]
    deployment_hold: Literal[False]
    runtime_fingerprint_sha256: str


class PdfLearningRuntimeBoundary(Protocol):
    def observe(self) -> PdfLearningRuntimeObservation: ...


class SystemdPdfLearningRuntimeObserver:
    """Prove the running Catalog process inherited the current disabled config.

    The environment file is read through a stable no-follow descriptor.  Catalog must be active,
    its declared EnvironmentFiles must include that exact path, and its process start must not
    predate the file's last mutation.  Any runtime drop-in or workflow deployment-hold residue is
    rejected rather than interpreted.
    """

    def __init__(
        self,
        *,
        automation_env_path: Path = AUTOMATION_ENV_PATH,
        runtime_dropin_root: Path = RUNTIME_DROPIN_ROOT,
        workflow_hold_root: Path = WORKFLOW_HOLD_ROOT,
        systemctl_path: Path = Path("/usr/bin/systemctl"),
    ) -> None:
        self.automation_env_path = automation_env_path
        self.runtime_dropin_root = runtime_dropin_root
        self.workflow_hold_root = workflow_hold_root
        self.systemctl_path = systemctl_path

    def observe(self) -> PdfLearningRuntimeObservation:
        properties = self._unit_properties()
        try:
            process_started_at = datetime.strptime(
                self._one(properties, "ExecMainStartTimestamp"),
                "%a %Y-%m-%d %H:%M:%S %Z",
            ).replace(tzinfo=UTC)
        except ValueError as exc:
            raise PdfLearningRuntimeError("Catalog process start time is invalid") from exc
        environment_files = properties.get("EnvironmentFiles", ())
        environment_paths = self._environment_paths(environment_files)
        if environment_paths.count(self.automation_env_path) != 1:
            self._fail("running Catalog automation configuration is not authoritative")
        environment_observations: list[tuple[str, bytes, os.stat_result]] = []
        automation_payload: bytes | None = None
        for path in environment_paths:
            payload, identity = self._read_configuration(path)
            assignments = self._automation_assignments(payload)
            if path == self.automation_env_path:
                if assignments != ("DISABLED",):
                    self._fail("Catalog automation mode is not disabled")
                automation_payload = payload
            elif assignments:
                self._fail("another Catalog environment file overrides automation mode")
            environment_observations.append((str(path), payload, identity))
        if automation_payload is None:
            self._fail("running Catalog automation configuration is not authoritative")
        mode = self._automation_mode(automation_payload)
        explicit_environment = self._one(properties, "Environment")
        try:
            explicit_assignments = shlex.split(explicit_environment)
        except ValueError as exc:
            raise PdfLearningRuntimeError("Catalog unit environment is invalid") from exc
        if any(value.startswith(_AUTOMATION_ASSIGNMENT) for value in explicit_assignments):
            self._fail("Catalog unit environment overrides automation mode")
        if (
            self._one(properties, "ActiveState") != "active"
            or not self._one(properties, "MainPID").isdigit()
            or int(self._one(properties, "MainPID")) < 1
            or process_started_at.timestamp()
            < max(identity.st_mtime for _, _, identity in environment_observations)
        ):
            self._fail("running Catalog automation configuration is not authoritative")
        overlay_entries = self._directory_entries(self.runtime_dropin_root)
        hold_entries = self._directory_entries(self.workflow_hold_root)
        if overlay_entries or hold_entries:
            self._fail("automation overlay or deployment hold is present")
        fingerprint = content_sha256(
            {
                "schema_version": "pdf-learning-runtime-observation/1.0",
                "automation_mode": mode,
                "environment_file_observations": [
                    {
                        "path": path,
                        "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
                        "identity": self._stat_identity(identity),
                    }
                    for path, payload, identity in environment_observations
                ],
                "catalog_main_pid": int(self._one(properties, "MainPID")),
                "catalog_process_started_at": process_started_at.isoformat().replace("+00:00", "Z"),
                "environment_files": list(environment_files),
                "runtime_dropin_entries": list(overlay_entries),
                "workflow_hold_entries": list(hold_entries),
            }
        )
        return PdfLearningRuntimeObservation(
            automation_mode="DISABLED",
            volatile_auto_overlay_present=False,
            deployment_hold=False,
            runtime_fingerprint_sha256=fingerprint,
        )

    def _read_configuration(self, path: Path | None = None) -> tuple[bytes, os.stat_result]:
        configured_path = path or self.automation_env_path
        descriptor = -1
        try:
            before = configured_path.lstat()
            if (
                configured_path.is_symlink()
                or not stat.S_ISREG(before.st_mode)
                or before.st_uid != 0
                or stat.S_IMODE(before.st_mode) not in {0o640, 0o644}
                or before.st_nlink != 1
                or before.st_size < 1
                or before.st_size > MAX_AUTOMATION_ENV_BYTES
            ):
                self._fail("Catalog automation environment file is invalid")
            descriptor = os.open(
                configured_path,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            opened = os.fstat(descriptor)
            payload = os.read(descriptor, MAX_AUTOMATION_ENV_BYTES + 1)
            closed = os.fstat(descriptor)
            if (
                self._stat_identity(before) != self._stat_identity(opened)
                or self._stat_identity(opened) != self._stat_identity(closed)
                or len(payload) != opened.st_size
            ):
                self._fail("Catalog automation environment changed while reading")
            return payload, opened
        except PdfLearningRuntimeError:
            raise
        except OSError as exc:
            raise PdfLearningRuntimeError("Catalog automation environment is unavailable") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    @staticmethod
    def _automation_mode(payload: bytes) -> str:
        values = SystemdPdfLearningRuntimeObserver._automation_assignments(payload)
        if values != ("DISABLED",):
            raise PdfLearningRuntimeError("Catalog automation mode is not disabled")
        return values[0]

    @staticmethod
    def _automation_assignments(payload: bytes) -> tuple[str, ...]:
        try:
            lines = payload.decode("utf-8").splitlines()
        except UnicodeError as exc:
            raise PdfLearningRuntimeError("Catalog automation environment is invalid") from exc
        values: list[str] = []
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line.endswith("\\"):
                raise PdfLearningRuntimeError("Catalog automation environment is ambiguous")
            name, separator, raw_value = line.partition("=")
            if name.strip() != _AUTOMATION_VARIABLE:
                continue
            if not separator:
                raise PdfLearningRuntimeError("Catalog automation environment is invalid")
            value = raw_value.strip()
            if value[:1] in {"'", '"'}:
                try:
                    parsed = shlex.split(value)
                except ValueError as exc:
                    raise PdfLearningRuntimeError(
                        "Catalog automation environment is invalid"
                    ) from exc
                if len(parsed) != 1:
                    raise PdfLearningRuntimeError("Catalog automation environment is invalid")
                value = parsed[0]
            elif any(character.isspace() for character in value):
                raise PdfLearningRuntimeError("Catalog automation environment is ambiguous")
            values.append(value)
        return tuple(values)

    @staticmethod
    def _environment_paths(values: tuple[str, ...]) -> tuple[Path, ...]:
        paths: list[Path] = []
        for value in values:
            matches = tuple(_ENVIRONMENT_FILE.finditer(value))
            if not matches or " ".join(match.group(0) for match in matches) != value:
                raise PdfLearningRuntimeError("Catalog EnvironmentFiles evidence is invalid")
            for match in matches:
                path = Path(match.group("path"))
                if path in paths:
                    raise PdfLearningRuntimeError("Catalog EnvironmentFiles evidence is invalid")
                paths.append(path)
        return tuple(paths)

    def _unit_properties(self) -> dict[str, tuple[str, ...]]:
        try:
            completed = subprocess.run(
                [
                    str(self.systemctl_path),
                    "show",
                    CATALOG_UNIT,
                    "-p",
                    "ActiveState",
                    "-p",
                    "MainPID",
                    "-p",
                    "ExecMainStartTimestamp",
                    "-p",
                    "EnvironmentFiles",
                    "-p",
                    "Environment",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise PdfLearningRuntimeError("Catalog unit evidence is unavailable") from exc
        properties: dict[str, list[str]] = {}
        for line in completed.stdout.splitlines():
            key, separator, value = line.partition("=")
            if not separator or not key or (not value and key != "Environment"):
                self._fail("Catalog unit evidence is invalid")
            properties.setdefault(key, []).append(value)
        return {key: tuple(values) for key, values in properties.items()}

    @staticmethod
    def _one(properties: dict[str, tuple[str, ...]], key: str) -> str:
        values = properties.get(key, ())
        if len(values) != 1:
            raise PdfLearningRuntimeError("Catalog unit evidence is incomplete")
        return values[0]

    @staticmethod
    def _directory_entries(path: Path) -> tuple[str, ...]:
        try:
            if not path.exists():
                return ()
            metadata = path.lstat()
            if path.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
                raise PdfLearningRuntimeError("runtime control directory is invalid")
            return tuple(sorted(entry.name for entry in path.iterdir()))
        except PdfLearningRuntimeError:
            raise
        except OSError as exc:
            raise PdfLearningRuntimeError("runtime control directory is unavailable") from exc

    @staticmethod
    def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_uid,
            value.st_gid,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
        )

    @staticmethod
    def _fail(message: str) -> NoReturn:
        raise PdfLearningRuntimeError(message)


__all__ = [
    "PdfLearningRuntimeBoundary",
    "PdfLearningRuntimeError",
    "PdfLearningRuntimeObservation",
    "SystemdPdfLearningRuntimeObserver",
]
