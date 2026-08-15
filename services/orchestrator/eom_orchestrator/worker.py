"""One-shot Codex worker adapter using a confined transient systemd unit."""

from __future__ import annotations

import json
import os
import pwd
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eom_protocol import ErrorCode, WorkerInput
from eom_protocol.validation import load_schema
from jsonschema import Draft202012Validator

from eom_orchestrator.errors import PlatformError
from eom_orchestrator.settings import Settings
from eom_orchestrator.worker_registry import WorkerSlot

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
        workspace = self.settings.workspace_root / slot.linux_user / job_id
        if workspace.exists():
            raise PlatformError(ErrorCode.WORKER_EXEC_FAILED, "worker workspace already exists")
        workspace.mkdir(mode=0o700, parents=False)
        account = pwd.getpwnam(slot.linux_user)
        os.chown(workspace, account.pw_uid, account.pw_gid)

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
            os.chown(path, account.pw_uid, account.pw_gid)
            path.chmod(0o400)
        return workspace, schema_path, prompt_path

    def _argv(
        self,
        *,
        workspace: Path,
        schema_path: Path,
        slot: WorkerSlot,
        unit_name: str,
    ) -> list[str]:
        home = self.settings.worker_home_root / slot.linux_user
        return [
            "/usr/bin/systemd-run",
            "--quiet",
            "--wait",
            "--pipe",
            "--collect",
            "--service-type=exec",
            f"--unit={unit_name}",
            f"--uid={slot.linux_user}",
            f"--gid={slot.linux_user}",
            f"--working-directory={workspace}",
            f"--setenv=HOME={home}",
            f"--setenv=CODEX_HOME={home / '.codex'}",
            "--property=NoNewPrivileges=yes",
            "--property=ProtectSystem=strict",
            "--property=ProtectHome=read-only",
            "--property=PrivateTmp=yes",
            "--property=InaccessiblePaths=/mnt/nas",
            "--property=InaccessiblePaths=/var/run/docker.sock",
            "--property=InaccessiblePaths=/home/eom/EOM",
            "--property=InaccessiblePaths=/etc/eom",
            "--property=InaccessiblePaths=/srv/eom/staging",
            f"--property=ReadWritePaths={workspace}",
            f"--property=ReadWritePaths={home}",
            "--property=UMask=0077",
            "--property=MemoryMax=6G",
            "--property=CPUQuota=200%",
            "--property=TasksMax=256",
            str(self.settings.codex_binary),
            "exec",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--ignore-user-config",
            "--skip-git-repo-check",
            "--color",
            "never",
            "--cd",
            str(workspace),
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(workspace / "result.json"),
            "-",
        ]

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
        unit_name = f"eom-worker-{job_id.replace('_', '-')}"
        argv = self._argv(
            workspace=workspace,
            schema_path=schema_path,
            slot=slot,
            unit_name=unit_name,
        )
        stdout_path = staging / "worker.stdout.log"
        stderr_path = staging / "worker.stderr.log"
        try:
            with prompt_path.open("rb") as prompt:
                completed = subprocess.run(
                    argv,
                    stdin=prompt,
                    capture_output=True,
                    timeout=self.settings.worker_timeout_seconds,
                    check=False,
                    env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"},
                )
        except subprocess.TimeoutExpired as exc:
            subprocess.run(
                ["/usr/bin/systemctl", "stop", f"{unit_name}.service"],
                capture_output=True,
                check=False,
                timeout=30,
            )
            self._write_capture(stdout_path, exc.stdout)
            self._write_capture(stderr_path, exc.stderr)
            raise PlatformError(ErrorCode.WORKER_TIMEOUT, "worker execution timed out") from exc
        except OSError as exc:
            raise PlatformError(ErrorCode.WORKER_EXEC_FAILED, "failed to start worker") from exc

        self._write_capture(stdout_path, completed.stdout)
        self._write_capture(stderr_path, completed.stderr)
        run = WorkerRun(
            exit_code=completed.returncode,
            result_path=workspace / "result.json",
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            unit_name=unit_name,
        )
        return run

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
