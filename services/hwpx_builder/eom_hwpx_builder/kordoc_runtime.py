"""Fixed-command adapter for the pinned, offline Kordoc Node runtime."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode

KORDOC_VERSION: Final[Literal["4.9.0"]] = "4.9.0"
MINIMUM_NODE_MAJOR = 20
MAX_BRIDGE_OUTPUT_BYTES = 64 * 1024


class KordocBridgeReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    kordoc_version: Literal["4.9.0"]
    source_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    output_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    validation_ok: bool
    validation_issue_count: int = Field(ge=0, le=1000)
    parse_success: bool
    parsed_markdown_sha256: str | None = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    parse_warning_count: int = Field(ge=0, le=1000)
    parsed_table_count: int = Field(ge=0, le=20)


class KordocCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["READY"]
    node_major: int = Field(ge=MINIMUM_NODE_MAJOR)
    kordoc_version: Literal["4.9.0"]
    offline_required: Literal[True]


@dataclass(frozen=True)
class KordocRuntimeSettings:
    node_binary: Path = Path("/srv/eom/conda/envs/eom-hwpx/bin/node")
    runtime_root: Path = Path("/srv/eom/conda/envs/eom-hwpx/share/eom-kordoc")
    home: Path = Path("/var/lib/eom-hwpx")
    timeout_seconds: int = 120


class KordocRenderRuntime(Protocol):
    def render(self, workspace: Path, preset: str) -> KordocBridgeReport: ...


class KordocRuntime:
    def __init__(self, settings: KordocRuntimeSettings | None = None) -> None:
        self.settings = settings or KordocRuntimeSettings()

    @staticmethod
    def _bridge_path() -> Path:
        return Path(str(files("eom_hwpx_builder").joinpath("kordoc_bridge.mjs"))).resolve()

    def _validate_install(self) -> tuple[Path, Path, Path]:
        node = self.settings.node_binary
        runtime = self.settings.runtime_root
        bridge = self._bridge_path()
        try:
            node_stat = node.stat()
            runtime_stat = runtime.stat()
            bridge_stat = bridge.stat()
        except OSError as exc:
            raise HwpxError(
                HwpxErrorCode.HWPX_KORDOC_RUNTIME_UNAVAILABLE,
                "pinned Kordoc runtime is unavailable",
            ) from exc
        if (
            not stat.S_ISREG(node_stat.st_mode)
            or not os.access(node, os.X_OK)
            or not stat.S_ISDIR(runtime_stat.st_mode)
            or runtime.is_symlink()
            or not stat.S_ISREG(bridge_stat.st_mode)
            or bridge.is_symlink()
            or not (runtime / "package.json").is_file()
            or (runtime / "package.json").is_symlink()
        ):
            raise HwpxError(
                HwpxErrorCode.HWPX_KORDOC_RUNTIME_UNAVAILABLE,
                "pinned Kordoc runtime layout is invalid",
            )
        return node.resolve(), runtime.resolve(), bridge

    def _environment(
        self, workspace: Path | None = None, preset: str | None = None
    ) -> dict[str, str]:
        environment = {
            "HOME": str(self.settings.home),
            "PATH": "/usr/bin:/bin",
            "KORDOC_OFFLINE": "1",
            "EOM_KORDOC_RUNTIME": str(self.settings.runtime_root.resolve()),
        }
        if workspace is not None:
            environment["KORDOC_ROOT"] = str(workspace.resolve())
        if preset is not None:
            environment["EOM_KORDOC_PRESET"] = preset
        return environment

    def _run(
        self, arguments: list[str], *, workspace: Path | None = None, preset: str | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        node, _, bridge = self._validate_install()
        try:
            completed = subprocess.run(
                [str(node), str(bridge), *arguments],
                cwd=workspace,
                env=self._environment(workspace, preset),
                capture_output=True,
                timeout=self.settings.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HwpxError(
                HwpxErrorCode.HWPX_KORDOC_RUNTIME_UNAVAILABLE,
                "Kordoc runtime could not complete",
            ) from exc
        if (
            completed.returncode != 0
            or len(completed.stdout) > MAX_BRIDGE_OUTPUT_BYTES
            or len(completed.stderr) > MAX_BRIDGE_OUTPUT_BYTES
        ):
            raise HwpxError(
                HwpxErrorCode.HWPX_KORDOC_RENDER_FAILED,
                "Kordoc renderer returned a sanitized failure",
            )
        return completed

    def capabilities(self) -> KordocCapability:
        completed = self._run(["--capabilities"])
        try:
            value: Any = json.loads(completed.stdout)
            capability = KordocCapability.model_validate(value)
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
            raise HwpxError(
                HwpxErrorCode.HWPX_KORDOC_DEPENDENCY_MISMATCH,
                "Kordoc capability response is invalid",
            ) from exc
        if capability.node_major < MINIMUM_NODE_MAJOR:
            raise HwpxError(
                HwpxErrorCode.HWPX_KORDOC_DEPENDENCY_MISMATCH,
                "Kordoc requires the pinned Node capability",
            )
        return capability

    def render(self, workspace: Path, preset: str) -> KordocBridgeReport:
        self._run([], workspace=workspace, preset=preset)
        report_path = workspace / ".kordoc-report.json"
        output_path = workspace / ".kordoc-generated.hwpx"
        try:
            report_stat = report_path.lstat()
            output_stat = output_path.lstat()
            raw = report_path.read_bytes()
        except OSError as exc:
            raise HwpxError(
                HwpxErrorCode.HWPX_KORDOC_RENDER_FAILED, "Kordoc output is missing"
            ) from exc
        if (
            not stat.S_ISREG(report_stat.st_mode)
            or not stat.S_ISREG(output_stat.st_mode)
            or report_path.is_symlink()
            or output_path.is_symlink()
            or len(raw) > MAX_BRIDGE_OUTPUT_BYTES
        ):
            raise HwpxError(HwpxErrorCode.HWPX_KORDOC_RENDER_FAILED, "Kordoc output is unsafe")
        try:
            return KordocBridgeReport.model_validate_json(raw)
        except ValidationError as exc:
            raise HwpxError(
                HwpxErrorCode.HWPX_KORDOC_VALIDATION_FAILED,
                "Kordoc validation report is invalid",
            ) from exc
