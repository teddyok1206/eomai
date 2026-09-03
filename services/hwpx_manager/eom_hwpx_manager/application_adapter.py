"""Fixed-unit adapters for the non-root application HWPX build manager."""

from __future__ import annotations

import grp
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

from eom_hwpx_manager.adapter import BuilderRun, HwpxBuilderAdapter
from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode

BUILD_ID = re.compile(r"\Ahwpxbuild_[0-9a-f]{32}\Z", re.ASCII)
SYSTEMCTL = Path("/usr/bin/systemctl")
SYSTEMCTL_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"}
WORKSPACE_ROOT_MODE = 0o2770
WORKSPACE_DIRECTORY_MODE = 0o770
WORKSPACE_FILE_MODE = 0o440


class _FixedApplicationBuilderAdapter(HwpxBuilderAdapter):
    """Use one fixed root-installed unit and a private group workspace handoff."""

    operation: str
    unit_template: str
    log_name: str

    def create_workspace(self, workspace_id: str) -> Path:
        if BUILD_ID.fullmatch(workspace_id) is None:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED,
                "invalid HWPX application workspace identifier",
            )
        root = self.settings.workspace_root
        try:
            root_metadata = root.lstat()
        except OSError as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_UNAVAILABLE,
                "HWPX application workspace root is unavailable",
            ) from exc
        try:
            builder_gid = grp.getgrnam(self.settings.builder_user).gr_gid
        except KeyError as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_UNAVAILABLE,
                "HWPX builder identity is unavailable",
            ) from exc
        if not self._root_contract_ready(root_metadata, builder_gid, os.getgroups()):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_UNAVAILABLE,
                "HWPX application workspace group boundary is unavailable",
            )
        workspace = root / workspace_id
        try:
            # The root-owned workspace parent supplies the trusted handoff group.
            # Per-build directories intentionally have no setgid bit because the
            # hardened Manager service runs with RestrictSUIDSGID=yes.  Descendant
            # groups are applied explicitly through fd-safe finalization instead.
            workspace.mkdir(mode=0o700)
            self._finalize_directory(workspace, builder_gid)
        except OSError as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED,
                "HWPX application workspace could not be created",
            ) from exc
        metadata = workspace.lstat()
        if (
            metadata.st_uid != os.geteuid()
            or metadata.st_gid != root_metadata.st_gid
            or stat.S_IMODE(metadata.st_mode) != WORKSPACE_DIRECTORY_MODE
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED,
                "HWPX application workspace metadata mismatch",
            )
        return workspace

    @staticmethod
    def _root_contract_ready(
        metadata: os.stat_result, builder_gid: int, process_groups: list[int]
    ) -> bool:
        return bool(
            stat.S_ISDIR(metadata.st_mode)
            and metadata.st_uid == 0
            and metadata.st_gid == builder_gid
            and stat.S_IMODE(metadata.st_mode) == WORKSPACE_ROOT_MODE
            and builder_gid in process_groups
        )

    def stage_file(self, workspace: Path, relative_path: str, source: Path) -> Path:
        target = self._target(workspace, relative_path)
        try:
            source_metadata = source.lstat()
        except OSError as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_REFERENCE_MISSING,
                "required HWPX input is missing",
            ) from exc
        if not stat.S_ISREG(source_metadata.st_mode) or source.is_symlink():
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED,
                "HWPX input is not a regular file",
            )
        self._prepare_parent(workspace, target.parent)
        shutil.copyfile(source, target)
        self._finalize_file(target, workspace.lstat().st_gid)
        self._verify_staged_file(workspace, target)
        return target

    def write_json(self, workspace: Path, relative_path: str, value: dict[str, Any]) -> Path:
        target = self._target(workspace, relative_path)
        self._prepare_parent(workspace, target.parent)
        target.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        self._finalize_file(target, workspace.lstat().st_gid)
        self._verify_staged_file(workspace, target)
        return target

    def run(
        self, workspace: Path, operation: str, arguments: list[str], log_root: Path
    ) -> BuilderRun:
        if (
            BUILD_ID.fullmatch(workspace.name) is None
            or workspace.parent != self.settings.workspace_root
            or not self._workspace_ready(workspace)
            or operation != self.operation
            or arguments != ["--request", "request.json", "--result", "result.json"]
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED,
                "HWPX application fixed-unit request is invalid",
            )
        unit_name = f"{self.unit_template}@{workspace.name}.service"
        log_root.mkdir(mode=0o750, parents=True, exist_ok=True)
        stdout = log_root / f"{self.log_name}.stdout.log"
        stderr = log_root / f"{self.log_name}.stderr.log"
        try:
            completed = subprocess.run(
                [str(SYSTEMCTL), "--no-ask-password", "--wait", "start", unit_name],
                capture_output=True,
                timeout=self.settings.timeout_seconds + 30,
                check=False,
                env=SYSTEMCTL_ENV,
            )
        except subprocess.TimeoutExpired as exc:
            self._sanitized_capture(stdout, unit_name, "TIMEOUT")
            self._sanitized_capture(stderr, unit_name, "TIMEOUT")
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_TIMEOUT,
                "fixed HWPX builder unit timed out",
            ) from exc
        self._sanitized_capture(stdout, unit_name, "COMPLETED")
        self._sanitized_capture(stderr, unit_name, "FAILED" if completed.returncode else "EMPTY")
        return BuilderRun(completed.returncode, workspace, stdout, stderr, unit_name)

    @staticmethod
    def _target(workspace: Path, relative_path: str) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts or "\\" in relative_path:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED,
                "unsafe HWPX application workspace path",
            )
        return workspace / relative

    @staticmethod
    def _prepare_parent(workspace: Path, parent: Path) -> None:
        if not _FixedApplicationBuilderAdapter._workspace_ready(workspace):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED,
                "unsafe HWPX application workspace",
            )
        workspace_metadata = workspace.lstat()
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        current = workspace
        for part in parent.relative_to(workspace).parts:
            current = current / part
            metadata = current.lstat()
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or current.is_symlink()
                or metadata.st_uid != os.geteuid()
            ):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_BUILDER_FAILED,
                    "unsafe HWPX application workspace directory",
                )
            _FixedApplicationBuilderAdapter._finalize_directory(current, workspace_metadata.st_gid)

    @staticmethod
    def _workspace_ready(workspace: Path) -> bool:
        try:
            metadata = workspace.lstat()
        except OSError:
            return False
        return bool(
            stat.S_ISDIR(metadata.st_mode)
            and not workspace.is_symlink()
            and metadata.st_uid == os.geteuid()
            and metadata.st_gid in os.getgroups()
            and stat.S_IMODE(metadata.st_mode) == WORKSPACE_DIRECTORY_MODE
        )

    @staticmethod
    def _finalize_directory(path: Path, builder_gid: int) -> None:
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
                raise OSError("unsafe HWPX application workspace directory")
            os.fchown(fd, -1, builder_gid)
            os.fchmod(fd, WORKSPACE_DIRECTORY_MODE)
            finalized = os.fstat(fd)
            if (
                finalized.st_uid != os.geteuid()
                or finalized.st_gid != builder_gid
                or stat.S_IMODE(finalized.st_mode) != WORKSPACE_DIRECTORY_MODE
            ):
                raise OSError("HWPX application workspace directory contract mismatch")
        finally:
            os.close(fd)

    @staticmethod
    def _finalize_file(path: Path, builder_gid: int) -> None:
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
                raise OSError("unsafe HWPX application staged file")
            os.fchown(fd, -1, builder_gid)
            os.fchmod(fd, WORKSPACE_FILE_MODE)
            finalized = os.fstat(fd)
            if (
                finalized.st_uid != os.geteuid()
                or finalized.st_gid != builder_gid
                or stat.S_IMODE(finalized.st_mode) != WORKSPACE_FILE_MODE
            ):
                raise OSError("HWPX application staged file contract mismatch")
        finally:
            os.close(fd)

    @staticmethod
    def _verify_staged_file(workspace: Path, target: Path) -> None:
        workspace_metadata = workspace.lstat()
        metadata = target.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or target.is_symlink()
            or metadata.st_uid != os.geteuid()
            or metadata.st_gid != workspace_metadata.st_gid
            or stat.S_IMODE(metadata.st_mode) != WORKSPACE_FILE_MODE
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED,
                "HWPX application staged file metadata mismatch",
            )

    @staticmethod
    def _sanitized_capture(path: Path, unit_name: str, result: str) -> None:
        path.write_text(f"unit={unit_name} result={result}\n", encoding="ascii")
        path.chmod(0o600)


class FixedKordocBuilderAdapter(_FixedApplicationBuilderAdapter):
    """Execute the pinned Kordoc renderer through its fixed systemd unit."""

    operation = "render-kordoc"
    unit_template = "eom-hwpx-kordoc"
    log_name = "hwpx-render-kordoc"


class FixedQuestionTemplateBuilderAdapter(_FixedApplicationBuilderAdapter):
    """Execute the approved question-template renderer through its fixed systemd unit."""

    operation = "render"
    unit_template = "eom-hwpx-builder"
    log_name = "hwpx-render-question-template"


class FixedContentTeamBuilderAdapter(_FixedApplicationBuilderAdapter):
    """Execute the reviewed content-team handoff in its fixed isolated unit."""

    operation = "render-content-team"
    unit_template = "eom-hwpx-content-team"
    log_name = "hwpx-render-content-team"
