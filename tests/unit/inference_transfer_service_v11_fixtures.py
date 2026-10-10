"""Synthetic successor lineage; no actual principal, DB, NAS or worker execution."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from eom_catalog_contracts.inference_transfer_invocation_v11 import (
    InferenceTransferWorkflowReadRequestV11,
)
from eom_catalog_service.inference_transfer_worker_preparation import (
    prepare_inference_transfer_worker_comparison_v11,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_protocol.models import ArtifactManifest
from eom_workflow import compile_definition
from eom_workflow.inference_transfer_control import ResolvedExecutionPlanV22
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequestV11
from eom_workflow.models import InferenceTransferPairRoleResultV11, RoleWorkerInput
from eom_workflow_runner.repository import inference_transfer_business_fingerprint

from tests.unit.inference_transfer_pair_v11_fixtures import pair_result_v11
from tests.unit.inference_transfer_workflow_read_fixtures import owner_fixture


def owner_fixture_v11(monkeypatch: pytest.MonkeyPatch, state: str = "COMPLETED") -> SimpleNamespace:
    build = cast(Callable[[pytest.MonkeyPatch, str], SimpleNamespace], owner_fixture)
    value = build(monkeypatch, state)
    request_body = value.request.model_dump(mode="json", exclude={"request_sha256"})
    request_body.update(
        schema_version="inference-transfer-workflow-request/1.1",
        request_name="ITEM_INFERENCE_TRANSFER_PAIR_REQUEST_V11",
        execution_preset_key="item-inference-transfer-comparison-axes",
    )
    request = InferenceTransferWorkflowRequestV11.model_validate(
        request_body | {"request_sha256": content_sha256(request_body)}
    )
    compiled = compile_definition(
        Path("config/workflows/item-inference-transfer-comparison.v1_1.yaml"), {"support"}
    )
    definition = value.definition
    definition.definition_version = compiled.definition.definition_version
    definition.canonical_definition = compiled.as_dict()
    definition.definition_hash = compiled.sha256
    definition.source_path = compiled.source_path
    workflow = value.workflow
    workflow.definition_version = definition.definition_version
    workflow.definition_hash = definition.definition_hash
    workflow.role_schema_version = "workflow-role/1.30.0"
    workflow.initial_request = request.model_dump(mode="json")
    workflow.request_payload = workflow.initial_request
    workflow.request_hash = inference_transfer_business_fingerprint(
        definition, request, actor_type="human", actor_id=workflow.created_actor_id
    )
    worker_body = value.job.request | {
        "protocol_version": "workflow-role/1.30.0",
        "request": request.worker_request().model_dump(mode="json"),
    }
    worker = RoleWorkerInput.model_validate(worker_body)
    role_result = InferenceTransferPairRoleResultV11(
        job_id=worker.job_id,
        workflow_id=worker.workflow_id,
        step_run_id=worker.step_run_id,
        artifact=worker.artifact,
        completed_at=value.role_result.completed_at,
        output=pair_result_v11(request.comparison),
    )
    document = role_result.model_dump(mode="json")
    manifest_body = value.revision.manifest | {
        "content_hash": content_sha256(document),
        "content_bytes": len(canonical_json_bytes(document)),
    }
    manifest = ArtifactManifest.model_validate(manifest_body)
    value.job.protocol_version = worker.protocol_version
    value.job.request = worker.model_dump(mode="json")
    value.job.request_hash = content_sha256(
        {
            "protocol_version": value.job.protocol_version,
            "task_type": value.job.task_type,
            "request": value.job.request,
        }
    )
    value.revision.content_hash = manifest.content_hash
    value.revision.content_bytes = manifest.content_bytes
    value.revision.manifest = manifest.model_dump(mode="json")
    value.revision.manifest_hash = content_sha256(value.revision.manifest)
    pointer = value.step.output_pointer_manifest | {
        "result_schema": "item-inference-transfer-pair-result@1.1",
        "content_hash": manifest.content_hash,
    }
    value.step.result_schema = pointer["result_schema"]
    value.step.output_pointer_manifest = pointer
    workflow.runtime_context["artifact_pointers"] = [pointer]
    final = workflow.runtime_context["final_pointer_manifest"]
    final.update(
        definition_hash=definition.definition_hash,
        artifact_pointers=[pointer],
        comparison_result=pointer,
    )
    prepared = prepare_inference_transfer_worker_comparison_v11(
        request.comparison, left=request.left_profile, right=request.right_profile
    )
    plan_body = value.plan.canonical_document.copy()
    plan_body.update(
        schema_version="resolved-execution-plan/22.0",
        resolver_version="22.0.0",
        workflow_definition_version="1.1.0",
        workflow_definition_sha256=definition.definition_hash,
        core_prompt_sha256=prepared.core_prompt_sha256,
        prompt_sha256=prepared.prompt_sha256,
    )
    plan_body["plan_sha256"] = content_sha256(
        {key: item for key, item in plan_body.items() if key != "plan_sha256"}
    )
    plan = ResolvedExecutionPlanV22.model_validate(plan_body)
    value.plan.canonical_document = plan.model_dump(mode="json")
    value.plan.plan_sha256 = plan.plan_sha256
    value.plan.resolver_version = plan.resolver_version
    workflow.runtime_context["execution_plan"]["plan_sha256"] = plan.plan_sha256
    value.step.input_pointer_manifest["transfer_prompt"] = {
        "prompt_version": prepared.prompt_version,
        "core_prompt_sha256": prepared.core_prompt_sha256,
        "prompt_sha256": prepared.prompt_sha256,
        "workflow_request_sha256": request.request_sha256,
    }
    value.owner.artifacts.load_json_revision.return_value = document
    value.request, value.document, value.role_result = request, document, role_result
    return value


def read_request_v11(mode: str = "CANONICAL_RESULT") -> InferenceTransferWorkflowReadRequestV11:
    body = {
        "schema_version": "inference-transfer-workflow-read-request/1.1",
        "workflow_id": "workflow_" + "1" * 32,
        "mode": mode,
    }
    return InferenceTransferWorkflowReadRequestV11.model_validate(
        body | {"read_sha256": content_sha256(body)}
    )
