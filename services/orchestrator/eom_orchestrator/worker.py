"""One-shot Codex worker adapter using fixed systemd template units."""

from __future__ import annotations

import grp
import json
import os
import pwd
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eom_protocol import ErrorCode, WorkerInput
from eom_protocol.validation import load_schema
from jsonschema import Draft202012Validator

from eom_orchestrator.errors import PlatformError
from eom_orchestrator.settings import Settings
from eom_orchestrator.worker_registry import WorkerSlot
from eom_orchestrator.worker_systemd import (
    launch_worker_unit,
    systemctl_start_argv,
    validate_job_id,
    worker_unit_name,
)

MAX_RESULT_BYTES = 1024 * 1024

WORKER_PROMPT = """Read worker-input.json and return only the JSON object required by
worker-result.schema.json. The schema fixes all identifiers; copy them exactly and never derive an
identifier from another identifier. For EOM_PLATFORM_SMOKE_TEST, return the required ok result and
a current UTC completed_at ending in Z. Do not access PostgreSQL, NAS, Docker, the repository,
another worker, or external tools. Do not create another artifact.
"""


@dataclass(frozen=True)
class WorkerRun:
    exit_code: int
    result_path: Path
    stdout_path: Path
    stderr_path: Path
    unit_name: str


class CodexWorkerAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _prepare_workspace(
        self, worker_input: WorkerInput, slot: WorkerSlot
    ) -> tuple[Path, Path, Path]:
        return self._prepare_workspace_document(
            job_id=worker_input.job_id,
            input_document=worker_input.model_dump(mode="json"),
            output_schema=worker_output_schema(worker_input),
            prompt_text=WORKER_PROMPT,
            slot=slot,
        )

    def _prepare_workspace_document(
        self,
        *,
        job_id: str,
        input_document: dict[str, Any],
        output_schema: dict[str, Any],
        prompt_text: str,
        slot: WorkerSlot,
    ) -> tuple[Path, Path, Path]:
        Draft202012Validator.check_schema(output_schema)
        account = pwd.getpwnam(slot.linux_user)
        private_group = grp.getgrnam(slot.linux_user)
        if account.pw_gid != private_group.gr_gid:
            raise PlatformError(
                ErrorCode.WORKER_UNAVAILABLE,
                "worker primary group does not match worker identity",
            )
        if private_group.gr_gid not in os.getgroups() and private_group.gr_gid != os.getgid():
            raise PlatformError(
                ErrorCode.WORKER_UNAVAILABLE,
                "runner is not a member of the worker private group",
            )
        worker_root = self.settings.workspace_root / slot.linux_user
        root_stat = worker_root.lstat()
        root_mode = stat.S_IMODE(root_stat.st_mode)
        if (
            worker_root.is_symlink()
            or not stat.S_ISDIR(root_stat.st_mode)
            or root_stat.st_gid != private_group.gr_gid
            or not root_mode & stat.S_ISGID
            or root_mode & 0o007
            or root_mode & 0o070 != 0o070
        ):
            raise PlatformError(
                ErrorCode.WORKER_UNAVAILABLE,
                "worker workspace root violates the private-group boundary",
            )
        try:
            validate_job_id(job_id)
        except ValueError as exc:
            raise PlatformError(
                ErrorCode.WORKER_EXEC_FAILED, "invalid worker job identity"
            ) from exc
        workspace = worker_root / job_id
        if workspace.parent != worker_root:
            raise PlatformError(ErrorCode.WORKER_EXEC_FAILED, "worker workspace escaped root")
        if workspace.exists():
            raise PlatformError(ErrorCode.WORKER_EXEC_FAILED, "worker workspace already exists")
        workspace.mkdir(mode=0o2770, parents=False)
        os.chown(workspace, -1, private_group.gr_gid)
        workspace.chmod(0o2770)

        input_path = workspace / "worker-input.json"
        schema_path = workspace / "worker-result.schema.json"
        prompt_path = workspace / "prompt.txt"
        input_path.write_text(
            json.dumps(input_document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        schema_path.write_text(
            json.dumps(output_schema, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        prompt_path.write_text(prompt_text, encoding="utf-8")
        for path in (input_path, schema_path, prompt_path):
            file_stat = path.lstat()
            if path.is_symlink() or not stat.S_ISREG(file_stat.st_mode):
                raise PlatformError(
                    ErrorCode.WORKER_EXEC_FAILED,
                    "worker input is not a regular file",
                )
            os.chown(path, -1, private_group.gr_gid)
            path.chmod(0o640)
        return workspace, schema_path, prompt_path

    def _argv(
        self,
        *,
        slot: WorkerSlot,
        job_id: str,
    ) -> list[str]:
        return list(systemctl_start_argv(worker_unit_name(slot, job_id)))

    def run(self, worker_input: WorkerInput, slot: WorkerSlot, staging: Path) -> WorkerRun:
        workspace, schema_path, prompt_path = self._prepare_workspace(worker_input, slot)
        return self._execute(
            job_id=worker_input.job_id,
            workspace=workspace,
            schema_path=schema_path,
            prompt_path=prompt_path,
            slot=slot,
            staging=staging,
        )

    def run_structured(
        self,
        *,
        job_id: str,
        input_document: dict[str, Any],
        output_schema: dict[str, Any],
        prompt_text: str,
        slot: WorkerSlot,
        staging: Path,
    ) -> WorkerRun:
        workspace, schema_path, prompt_path = self._prepare_workspace_document(
            job_id=job_id,
            input_document=input_document,
            output_schema=output_schema,
            prompt_text=prompt_text,
            slot=slot,
        )
        return self._execute(
            job_id=job_id,
            workspace=workspace,
            schema_path=schema_path,
            prompt_path=prompt_path,
            slot=slot,
            staging=staging,
        )

    def _execute(
        self,
        *,
        job_id: str,
        workspace: Path,
        schema_path: Path,
        prompt_path: Path,
        slot: WorkerSlot,
        staging: Path,
    ) -> WorkerRun:
        del schema_path, prompt_path
        unit_name = worker_unit_name(slot, job_id)
        stdout_path = staging / "worker.stdout.log"
        stderr_path = staging / "worker.stderr.log"
        try:
            completed = launch_worker_unit(
                slot,
                job_id,
                timeout_seconds=self.settings.worker_timeout_seconds,
            )
        except OSError as exc:
            raise PlatformError(ErrorCode.WORKER_UNAVAILABLE, "failed to start worker") from exc

        self._collect_capture(
            workspace / "worker.stdout.log", stdout_path, completed.command_stdout
        )
        self._collect_capture(
            workspace / "worker.stderr.log", stderr_path, completed.command_stderr
        )
        run = WorkerRun(
            exit_code=completed.exit_code,
            result_path=workspace / "result.json",
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            unit_name=unit_name,
        )
        return run

    @classmethod
    def _collect_capture(cls, source: Path, destination: Path, fallback: bytes) -> None:
        try:
            metadata = source.lstat()
        except FileNotFoundError:
            cls._write_capture(destination, fallback)
            return
        if source.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise PlatformError(ErrorCode.WORKER_EXEC_FAILED, "worker log is not a regular file")
        if metadata.st_size > MAX_RESULT_BYTES:
            raise PlatformError(ErrorCode.WORKER_EXEC_FAILED, "worker log exceeds size limit")
        cls._write_capture(destination, source.read_bytes())

    @staticmethod
    def _write_capture(path: Path, value: bytes | str | None) -> None:
        if value is None:
            data = b""
        elif isinstance(value, str):
            data = value.encode("utf-8", errors="replace")
        else:
            data = value
        path.write_bytes(data[-MAX_RESULT_BYTES:])
        path.chmod(0o600)


def load_worker_result(path: Path, workspace: Path) -> object:
    try:
        file_stat = path.lstat()
    except FileNotFoundError as exc:
        raise PlatformError(
            ErrorCode.WORKER_RESULT_MISSING, "worker result.json is missing"
        ) from exc
    if not stat.S_ISREG(file_stat.st_mode) or path.is_symlink():
        raise PlatformError(ErrorCode.WORKER_RESULT_INVALID, "worker result is not a regular file")
    if file_stat.st_size > MAX_RESULT_BYTES:
        raise PlatformError(ErrorCode.WORKER_RESULT_INVALID, "worker result exceeds size limit")
    if path.resolve().parent != workspace.resolve():
        raise PlatformError(ErrorCode.WORKER_RESULT_INVALID, "worker result escaped workspace")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PlatformError(
            ErrorCode.WORKER_RESULT_INVALID, "worker result is malformed JSON"
        ) from exc


def worker_output_schema(worker_input: WorkerInput) -> dict[str, Any]:
    schema = load_schema("worker-result")
    properties = _schema_mapping(schema, "properties")
    _schema_mapping(properties, "job_id")["const"] = worker_input.job_id
    artifact = _schema_mapping(properties, "artifact")
    artifact_properties = _schema_mapping(artifact, "properties")
    _schema_mapping(artifact_properties, "logical_artifact_id")["const"] = (
        worker_input.artifact.logical_artifact_id
    )
    _schema_mapping(artifact_properties, "revision_id")["const"] = worker_input.artifact.revision_id
    return schema


def _schema_mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"worker result schema is missing object: {key}")
    return value
