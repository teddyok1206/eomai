from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import eom_workflow_runner.engine as engine_module
import pytest
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.readiness import (
    ReadinessStatus,
    RuntimeReadinessCheck,
    RuntimeReadinessReport,
    WorkflowRuntimeNotReady,
)


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
    runner.sessions = _read_session
    runner.readiness = _RegistryStagingUnavailable()
    monkeypatch.setattr(engine_module, "claimable_command_exists", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        engine_module,
        "claim_next_command",
        lambda *_args, **_kwargs: pytest.fail("runtime-not-ready command was claimed"),
    )

    with pytest.raises(WorkflowRuntimeNotReady) as captured:
        runner.run_once("workflow_" + "0" * 32)

    assert captured.value.report.failed_codes == ("CATALOG_REGISTRY_STAGING_INVALID",)
