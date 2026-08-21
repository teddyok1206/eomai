"""Fixed-template Kordoc adapter for the non-root application build manager."""

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
WORKSPACE_FILE_MODE = 0o440


class FixedKordocBuilderAdapter(HwpxBuilderAdapter):
    """Use one fixed root-installed unit and a private group workspace handoff."""

    def create_workspace(self, workspace_id: str) -> Path:
        if BUILD_ID.fullmatch(workspace_id) is None:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED,
                "invalid Kordoc application workspace identifier",
            )
        root = self.settings.workspace_root
        try:
            root_metadata = root.lstat()
        except OSError as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_UNAVAILABLE,
                "Kordoc application workspace root is unavailable",
            ) from exc
        try:
            builder_gid = grp.getgrnam(self.settings.builder_user).gr_gid
        except KeyError as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_UNAVAILABLE,
                "Kordoc builder identity is unavailable",
            ) from exc
        if not self._root_contract_ready(root_metadata, builder_gid, os.getgroups()):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_UNAVAILABLE,
                "Kordoc application workspace group boundary is unavailable",
            )
        workspace = root / workspace_id
        try:
            workspace.mkdir(mode=WORKSPACE_ROOT_MODE)
            workspace.chmod(WORKSPACE_ROOT_MODE)
        except OSError as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED,
                "Kordoc application workspace could not be created",
            ) from exc
        metadata = workspace.lstat()
        if (
            metadata.st_uid != os.geteuid()
            or metadata.st_gid != root_metadata.st_gid
            or stat.S_IMODE(metadata.st_mode) != WORKSPACE_ROOT_MODE
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED,
                "Kordoc application workspace metadata mismatch",
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
                "required Kordoc input is missing",
            ) from exc
        if not stat.S_ISREG(source_metadata.st_mode) or source.is_symlink():
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED,
                "Kordoc input is not a regular file",
            )
        self._prepare_parent(workspace, target.parent)
        shutil.copyfile(source, target)
        target.chmod(WORKSPACE_FILE_MODE)
        self._verify_staged_file(workspace, target)
        return target

    def write_json(self, workspace: Path, relative_path: str, value: dict[str, Any]) -> Path:
        target = self._target(workspace, relative_path)
        self._prepare_parent(workspace, target.parent)
        target.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        target.chmod(WORKSPACE_FILE_MODE)
        self._verify_staged_file(workspace, target)
        return target

    def run(
        self, workspace: Path, operation: str, arguments: list[str], log_root: Path
    ) -> BuilderRun:
        if (
            BUILD_ID.fullmatch(workspace.name) is None
            or workspace.parent != self.settings.workspace_root
            or not self._workspace_ready(workspace)
            or operation != "render-kordoc"
            or arguments != ["--request", "request.json", "--result", "result.json"]
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED,
                "Kordoc application fixed-unit request is invalid",
            )
        unit_name = f"eom-hwpx-kordoc@{workspace.name}.service"
        log_root.mkdir(mode=0o750, parents=True, exist_ok=True)
        stdout = log_root / "hwpx-render-kordoc.stdout.log"
        stderr = log_root / "hwpx-render-kordoc.stderr.log"
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
                "fixed Kordoc builder unit timed out",
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
                "unsafe Kordoc application workspace path",
            )
        return workspace / relative

    @staticmethod
    def _prepare_parent(workspace: Path, parent: Path) -> None:
        if not FixedKordocBuilderAdapter._workspace_ready(workspace):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED,
                "unsafe Kordoc application workspace",
            )
        workspace_metadata = workspace.lstat()
        parent.mkdir(mode=WORKSPACE_ROOT_MODE, parents=True, exist_ok=True)
        current = workspace
        for part in parent.relative_to(workspace).parts:
            current = current / part
            metadata = current.lstat()
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or current.is_symlink()
                or metadata.st_uid != os.geteuid()
                or metadata.st_gid != workspace_metadata.st_gid
            ):
                raise HwpxManagerError(
                    HwpxManagerErrorCode.HWPX_BUILDER_FAILED,
                    "unsafe Kordoc application workspace directory",
                )
            current.chmod(WORKSPACE_ROOT_MODE)

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
            and stat.S_IMODE(metadata.st_mode) == WORKSPACE_ROOT_MODE
        )

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
                "Kordoc application staged file metadata mismatch",
            )

    @staticmethod
    def _sanitized_capture(path: Path, unit_name: str, result: str) -> None:
        path.write_text(f"unit={unit_name} result={result}\n", encoding="ascii")
        path.chmod(0o600)
