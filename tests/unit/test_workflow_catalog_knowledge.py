from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_workflow import ArtifactPointer, WorkflowRequest
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord


def _pointer() -> ArtifactPointer:
    return ArtifactPointer(
        step_key="image",
        attempt=1,
        job_id="job_" + "1" * 32,
        logical_artifact_id="artifact_" + "2" * 32,
        revision_id="rev_" + "3" * 32,
        content_hash="sha256:" + "4" * 64,
        result_schema="image-result@2.0",
    )


def _result(workflow_id: str = "workflow_" + "5" * 32) -> dict[str, Any]:
    pointer = _pointer()
    return {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.1.0",
        "job_id": pointer.job_id,
        "workflow_id": workflow_id,
        "step_run_id": "steprun_" + "6" * 32,
        "role": "image",
        "status": "ok",
        "artifact": {
            "logical_artifact_id": pointer.logical_artifact_id,
            "revision_id": pointer.revision_id,
            "file_name": "result.json",
            "media_type": "application/json",
        },
        "output": {
            "image_review": {
                "decision": "asset_approved",
                "artifact_revision_id": "rev_" + "7" * 32,
                "summary": "고정 자산 포인터를 확인했습니다.",
            }
        },
        "completed_at": "2026-08-22T00:00:00Z",
    }


class _Artifacts:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value

    def load_json_revision(self, **pointer: str | int) -> dict[str, Any]:
        expected = _pointer()
        assert pointer == {
            "artifact_id": expected.logical_artifact_id,
            "revision_id": expected.revision_id,
            "content_hash": expected.content_hash,
        }
        return self.value


def _service(value: dict[str, Any]) -> WorkflowCatalogService:
    service = object.__new__(WorkflowCatalogService)
    service.artifacts = cast(Any, _Artifacts(value))
    return service


def _workflow() -> WorkflowInstanceRecord:
    return cast(
        WorkflowInstanceRecord,
        SimpleNamespace(
            workflow_id="workflow_" + "5" * 32,
            runtime_context={
                "stimulus_asset": {
                    "artifact_revision_id": "rev_" + "7" * 32,
                }
            },
        ),
    )


def _request() -> WorkflowRequest:
    return WorkflowRequest.model_validate(
        {
            "request_name": "KNOWLEDGE_ITEM_REQUEST",
            "image_mode": "required",
            "content_pack": {"pack_key": "general-knowledge-item", "environment": "test"},
            "profiles": {
                "authoring": "knowledge-authoring",
                "review": "knowledge-review",
                "image": "fixed-stimulus-review",
                "registration": "structured-registration",
            },
            "source_intake": {"batch_ids": []},
            "registry_intent": {"mode": "CREATE_ITEM"},
            "item_brief": {
                "subject": "일반 과학",
                "topic": "변인 사이의 관계",
                "task_type": "data_interpretation",
                "difficulty": "medium",
                "quality_profile": "balanced",
                "original_request_sha256": "8" * 64,
            },
            "stimulus_asset": {"asset_key": "eom-question-template-reference-v1"},
        }
    )


def test_prompt_context_materializes_only_validated_pinned_upstream_json() -> None:
    workflow = _workflow()
    step = cast(
        WorkflowStepRunRecord,
        SimpleNamespace(step_key="review"),
    )
    context = _service(_result())._prompt_context(
        workflow,
        step,
        _request(),
        (_pointer(),),
        "packrel_" + "9" * 32,
    )
    embedded = json.loads(context["upstream"]["image"]["result_json"])
    assert embedded["workflow_id"] == workflow.workflow_id
    assert embedded["artifact"]["revision_id"] == _pointer().revision_id


def test_prompt_context_rejects_schema_valid_result_from_another_workflow() -> None:
    with pytest.raises(ValueError, match="immutable pointer"):
        _service(_result("workflow_" + "a" * 32))._load_upstream_result(_workflow(), _pointer())


def test_prompt_context_rejects_duplicate_step_pointers() -> None:
    step = cast(WorkflowStepRunRecord, SimpleNamespace(step_key="review"))
    with pytest.raises(ValueError, match="duplicate upstream"):
        _service(_result())._prompt_context(
            _workflow(),
            step,
            _request(),
            (_pointer(), _pointer()),
            "packrel_" + "9" * 32,
        )
