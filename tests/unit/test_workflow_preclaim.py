from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import cast
from unittest.mock import Mock

import eom_workflow_runner.engine as engine_module
import pytest
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.readiness import (
    ReadinessStatus,
    RuntimeReadinessCheck,
    RuntimeReadinessReport,
    WorkflowRuntimeNotReady,
)
from eom_workflow_runner.repository import CommandCandidate, CommandExecutionFamily
from sqlalchemy.orm import Session, sessionmaker


class _RegistryStagingUnavailable:
    def evaluate(self) -> RuntimeReadinessReport:
        return RuntimeReadinessReport(
            (
                RuntimeReadinessCheck(
                    name="catalog_registry_staging",
                    status=ReadinessStatus.FAIL,
                    code="CATALOG_REGISTRY_STAGING_INVALID",
                    detail="permission denied",
                ),
            )
        )


@contextmanager
def _read_session() -> Iterator[object]:
    yield object()


def test_registry_staging_failure_precedes_command_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = object.__new__(WorkflowRunner)
    runner.sessions = cast(sessionmaker[Session], _read_session)
    runner.readiness = _RegistryStagingUnavailable()
    candidate = Mock(spec=CommandCandidate)
    candidate.family = CommandExecutionFamily.ROLE
    candidate.created_at = datetime.now(UTC)
    candidate.command_id = "wfcmd_" + "1" * 32
    monkeypatch.setattr(
        engine_module,
        "peek_command_candidate",
        lambda *_args, **kwargs: (
            candidate if kwargs["family"] is CommandExecutionFamily.ROLE else None
        ),
    )
    monkeypatch.setattr(
        engine_module,
        "claim_command_candidate",
        lambda *_args, **_kwargs: pytest.fail("runtime-not-ready command was claimed"),
    )

    with pytest.raises(WorkflowRuntimeNotReady) as captured:
        runner.run_once("workflow_" + "0" * 32)

    assert captured.value.report.failed_codes == ("CATALOG_REGISTRY_STAGING_INVALID",)
