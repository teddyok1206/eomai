"""systemd adapter for the Workflow retirement quiescence port."""

from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Never

from eom_workflow_runner.retirement_quiescence import (
    WORKFLOW_RUNNER_DEPLOYMENT_HOLD_DIRECTORY,
    WORKFLOW_RUNNER_DEPLOYMENT_HOLD_PATH,
    WORKFLOW_RUNNER_UNIT_NAME,
    WorkflowRunnerQuiescenceEvidence,
)

_SYSTEMCTL = Path("/usr/bin/systemctl")
_HOLD_DIRECTORY = Path(WORKFLOW_RUNNER_DEPLOYMENT_HOLD_DIRECTORY)
_HOLD_PATH = Path(WORKFLOW_RUNNER_DEPLOYMENT_HOLD_PATH)
_PROPERTIES = frozenset(
    {
        "ActiveState",
        "SubState",
        "MainPID",
        "UnitFileState",
        "Job",
        "LoadState",
        "FragmentPath",
        "DropInPaths",
        "RefuseManualStart",
        "NeedDaemonReload",
    }
)
_TOKEN = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX_OUTPUT_BYTES = 4096
_MAX_HOLD_BYTES = 4096

CommandRunner = Callable[..., subprocess.CompletedProcess[bytes]]


class WorkflowRunnerQuiescenceAdapterError(RuntimeError):
    """Stable failure to obtain exact host-service quiescence evidence."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SystemdWorkflowRunnerQuiescenceAdapter:
    """Read the exact unit state and persistent deployment-hold identity."""

    def __init__(
        self,
        *,
        command_runner: CommandRunner = subprocess.run,
        hold_path: Path = _HOLD_PATH,
    ) -> None:
        self._command_runner = command_runner
        self._hold_path = hold_path
        self._hold_directory = hold_path.parent

    def observe(self) -> WorkflowRunnerQuiescenceEvidence:
        properties = self._observe_unit()
        hold_directory_metadata, hold_metadata, hold_sha256 = self._observe_hold()
        return WorkflowRunnerQuiescenceEvidence(
            load_state=properties["LoadState"],
            active_state=properties["ActiveState"],
            sub_state=properties["SubState"],
            main_pid=int(properties["MainPID"]),
            unit_file_state=properties["UnitFileState"],
            job=properties["Job"],
            fragment_path=properties["FragmentPath"],
            drop_in_paths=_parse_drop_in_paths(properties["DropInPaths"]),
            refuse_manual_start=properties["RefuseManualStart"] == "yes",
            need_daemon_reload=properties["NeedDaemonReload"] == "yes",
            hold_directory_path=str(self._hold_directory),
            hold_directory_owner_uid=hold_directory_metadata.st_uid,
            hold_directory_group_gid=hold_directory_metadata.st_gid,
            hold_directory_mode=stat.S_IMODE(hold_directory_metadata.st_mode),
            hold_path=str(self._hold_path),
            hold_sha256=hold_sha256,
            hold_owner_uid=hold_metadata.st_uid,
            hold_group_gid=hold_metadata.st_gid,
            hold_mode=stat.S_IMODE(hold_metadata.st_mode),
        )

    def _observe_unit(self) -> dict[str, str]:
        argv: Sequence[str] = (
            str(_SYSTEMCTL),
            "show",
            WORKFLOW_RUNNER_UNIT_NAME,
            "--no-pager",
            "--property=ActiveState",
            "--property=SubState",
            "--property=MainPID",
            "--property=UnitFileState",
            "--property=Job",
            "--property=LoadState",
            "--property=FragmentPath",
            "--property=DropInPaths",
            "--property=RefuseManualStart",
            "--property=NeedDaemonReload",
        )
        try:
            completed = self._command_runner(
                argv,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
                env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise WorkflowRunnerQuiescenceAdapterError(
                "PRODUCTION_RETIREMENT_QUIESCENCE_UNAVAILABLE",
                "Workflow runner quiescence evidence is unavailable",
            ) from exc
        if (
            completed.returncode != 0
            or completed.stderr
            or len(completed.stdout) > _MAX_OUTPUT_BYTES
        ):
            _fail(
                "PRODUCTION_RETIREMENT_QUIESCENCE_UNAVAILABLE",
                "Workflow runner quiescence evidence is unavailable",
            )
        try:
            text = completed.stdout.decode("ascii", errors="strict")
        except UnicodeDecodeError as exc:
            raise WorkflowRunnerQuiescenceAdapterError(
                "PRODUCTION_RETIREMENT_QUIESCENCE_INVALID",
                "Workflow runner quiescence evidence is malformed",
            ) from exc
        properties: dict[str, str] = {}
        for line in text.splitlines():
            key, separator, value = line.partition("=")
            if not separator or key not in _PROPERTIES or key in properties:
                _fail(
                    "PRODUCTION_RETIREMENT_QUIESCENCE_INVALID",
                    "Workflow runner quiescence evidence is malformed",
                )
            properties[key] = value
        if set(properties) != _PROPERTIES or not _valid_properties(properties):
            _fail(
                "PRODUCTION_RETIREMENT_QUIESCENCE_INVALID",
                "Workflow runner quiescence evidence is incomplete or malformed",
            )
        return properties

    def _observe_hold(self) -> tuple[os.stat_result, os.stat_result, str]:
        directory_descriptor: int | None = None
        file_descriptor: int | None = None
        try:
            directory_descriptor = os.open(
                self._hold_directory,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY,
            )
            directory_metadata = os.fstat(directory_descriptor)
            file_descriptor = os.open(
                self._hold_path.name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory_descriptor,
            )
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise WorkflowRunnerQuiescenceAdapterError(
                    "PRODUCTION_RETIREMENT_QUIESCENCE_INVALID",
                    "Workflow runner deployment hold identity is invalid",
                ) from exc
            raise WorkflowRunnerQuiescenceAdapterError(
                "PRODUCTION_RETIREMENT_QUIESCENCE_UNAVAILABLE",
                "Workflow runner deployment hold evidence is unavailable",
            ) from exc
        finally:
            if file_descriptor is None and directory_descriptor is not None:
                os.close(directory_descriptor)
        assert directory_descriptor is not None
        assert file_descriptor is not None
        try:
            metadata = os.fstat(file_descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or not 0 < metadata.st_size <= _MAX_HOLD_BYTES
            ):
                _fail(
                    "PRODUCTION_RETIREMENT_QUIESCENCE_INVALID",
                    "Workflow runner deployment hold identity is invalid",
                )
            content = _read_bounded(file_descriptor)
            final_metadata = os.fstat(file_descriptor)
            final_directory_metadata = os.fstat(directory_descriptor)
        except OSError as exc:
            raise WorkflowRunnerQuiescenceAdapterError(
                "PRODUCTION_RETIREMENT_QUIESCENCE_UNAVAILABLE",
                "Workflow runner deployment hold evidence is unavailable",
            ) from exc
        finally:
            os.close(file_descriptor)
            os.close(directory_descriptor)
        if (
            len(content) != metadata.st_size
            or len(content) > _MAX_HOLD_BYTES
            or _node_identity(final_metadata) != _node_identity(metadata)
            or _node_identity(final_directory_metadata) != _node_identity(directory_metadata)
        ):
            _fail(
                "PRODUCTION_RETIREMENT_QUIESCENCE_INVALID",
                "Workflow runner deployment hold changed during observation",
            )
        return (
            directory_metadata,
            metadata,
            "sha256:" + hashlib.sha256(content).hexdigest(),
        )


def _parse_drop_in_paths(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    paths = tuple(value.split(" "))
    if any(not path.startswith("/") for path in paths):
        _fail(
            "PRODUCTION_RETIREMENT_QUIESCENCE_INVALID",
            "Workflow runner drop-in identity is malformed",
        )
    return paths


def _read_bounded(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    remaining = _MAX_HOLD_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _node_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _valid_properties(properties: dict[str, str]) -> bool:
    return (
        _TOKEN.fullmatch(properties["ActiveState"]) is not None
        and _TOKEN.fullmatch(properties["SubState"]) is not None
        and _TOKEN.fullmatch(properties["LoadState"]) is not None
        and _TOKEN.fullmatch(properties["UnitFileState"]) is not None
        and properties["MainPID"].isdigit()
        and (not properties["Job"] or properties["Job"].isdigit())
        and properties["FragmentPath"].startswith("/")
        and properties["RefuseManualStart"] in {"yes", "no"}
        and properties["NeedDaemonReload"] in {"yes", "no"}
    )


def _fail(code: str, message: str) -> Never:
    raise WorkflowRunnerQuiescenceAdapterError(code, message)
