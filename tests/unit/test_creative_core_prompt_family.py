"""The V2 role must not inherit the historical V1-only core output instruction."""

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_source_draft import CREATIVE_SOURCE_STATEMENT_GUIDANCE
from eom_catalog_contracts.external_item_learning_result_v2 import (
    INDEPENDENT_SOURCE_SOLUTION_GUIDANCE,
)
from eom_workflow.models import ExternalItemLearningWorkerRequest
from eom_workflow_runner import engine

from tests.unit.test_external_item_learning_execution_plan import _plan


@pytest.mark.parametrize("successor", [False, True])
def test_actual_role_executor_selects_matching_core_without_mutating_v1(monkeypatch, successor):
    executor = object.__new__(engine.PlatformRoleJobExecutor)
    executor.workflow_settings = NS(prompt_root=Path("/synthetic/prompts"))
    executor.sessions = lambda: nullcontext(Mock())
    executor.creative_page_publisher = Mock()
    executor.similarity_context_provider = None
    executor.orchestrator = NS(submit_workflow_role=Mock(return_value=object()))
    monkeypatch.setattr(
        engine, "prepare_external_item_learning_execution_context", Mock(return_value=object())
    )
    monkeypatch.setattr(engine, "read_platform_role_result", lambda *args: NS(status="QUEUED"))
    step = NS(
        step_run_id="steprun_" + "a" * 32,
        step_key="extract",
        attempt=1,
        worker_role="support",
        result_schema="external-item-learning-result@2.0"
        if successor
        else "external-item-learning-result@1.0",
        input_pointer_manifest={},
    )
    result = executor.execute(
        workflow=NS(
            workflow_id="workflow_" + "b" * 32, definition_version="2.0.0" if successor else "1.0.0"
        ),
        step=step,
        request=ExternalItemLearningWorkerRequest(
            work_input=_plan(successor=successor)["work_input"]
        ),
        upstream=(),
        idempotency_key="synthetic-matching-source-core",
        prompt_text=None,
    )
    assert result.status == "QUEUED"
    passed = executor.orchestrator.submit_workflow_role.call_args.kwargs
    if successor:
        assert passed["prompt_path"] is None
        assert "external-item-learning-result@2.0" in passed["prompt_text"]
        assert "external-item-learning-result@1.0" not in passed["prompt_text"]
        assert "independent public solution" in passed["prompt_text"]
        assert "field-specific policy" in passed["prompt_text"]
        assert INDEPENDENT_SOURCE_SOLUTION_GUIDANCE in passed["prompt_text"]
        assert CREATIVE_SOURCE_STATEMENT_GUIDANCE in passed["prompt_text"]
    else:
        assert passed["prompt_text"] is None
        assert passed["prompt_path"] == Path("/synthetic/prompts/external-item-learning.txt")
