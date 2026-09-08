"""systemd adapter for the Workflow retirement quiescence port."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Never

from eom_workflow_runner.retirement_quiescence import WorkflowRunnerQuiescenceEvidence

_SYSTEMCTL = Path("/usr/bin/systemctl")
_UNIT = "eom-workflow-runner.service"
_PROPERTIES = frozenset({"ActiveState", "SubState", "UnitFileState"})
_MAX_OUTPUT_BYTES = 4096

CommandRunner = Callable[..., subprocess.CompletedProcess[bytes]]


class WorkflowRunnerQuiescenceAdapterError(RuntimeError):
    """Stable failure to obtain exact host-service quiescence evidence."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SystemdWorkflowRunnerQuiescenceAdapter:
    """Read three exact unit properties without a shell or privileged mutation."""

    def __init__(self, *, command_runner: CommandRunner = subprocess.run) -> None:
        self._command_runner = command_runner

    def observe(self) -> WorkflowRunnerQuiescenceEvidence:
        argv: Sequence[str] = (
            str(_SYSTEMCTL),
            "show",
            _UNIT,
            "--no-pager",
            "--property=ActiveState",
            "--property=SubState",
            "--property=UnitFileState",
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
            if not separator or key not in _PROPERTIES or key in properties or not value:
                _fail(
                    "PRODUCTION_RETIREMENT_QUIESCENCE_INVALID",
                    "Workflow runner quiescence evidence is malformed",
                )
            properties[key] = value
        if set(properties) != _PROPERTIES:
            _fail(
                "PRODUCTION_RETIREMENT_QUIESCENCE_INVALID",
                "Workflow runner quiescence evidence is incomplete",
            )
        return WorkflowRunnerQuiescenceEvidence(
            active_state=properties["ActiveState"],
            sub_state=properties["SubState"],
            unit_file_state=properties["UnitFileState"],
        )


def _fail(code: str, message: str) -> Never:
    raise WorkflowRunnerQuiescenceAdapterError(code, message)
