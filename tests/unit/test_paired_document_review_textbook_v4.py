"""Paired textbook successor is additive and keeps examined evidence distinct from support."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_api.errors import ApiError
from eom_api.services import query_adapter as query_module
from eom_api.services.query_adapter import QueryAdapter
from eom_catalog_contracts import ReviewTextbookEvidence
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.evidence_usage_validation import EvidenceUsageValidationError
from eom_orchestrator.review_textbook_evidence_validation import (
    validate_paired_document_textbook_for_commit,
)
from eom_workflow import (
    ArtifactPointer,
    PairedDocumentReviewRequest,
    PairedDocumentReviewRoleResultV4,
    PairedDocumentReviewWorkerRequestV3,
    ResolvedExecutionPlanV26,
    RoleWorkerInput,
    compile_definition,
    validate_control_contract,
)
from eom_workflow.schemas import (
    constrained_result_schema,
    load_codex_result_schema,
    load_role_result_schema,
    validate_role_input,
    validate_role_result,
)
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from tests.unit.test_document_review_v3_protocol import _result
from tests.unit.test_paired_document_review_v3_projection import _projection_fixture
from tests.unit.test_pdf_document_review_protocol import _paired_worker_input
from tests.unit.test_review_textbook_evidence import _binding, _usage

ROOT = Path(__file__).resolve().parents[2]


def _result_v4() -> dict[str, object]:
    value = copy.deepcopy(_result())
    value["protocol_version"] = "workflow-role/1.32.0"
    output = value["output"]
    assert isinstance(output, dict)
    binding = ReviewTextbookEvidence.model_validate(_binding())
    output["textbook_usage"] = _usage(binding)
    output["textbook_usage"]["citations"][0]["evidence_id"] = "evidenceitem_" + "a" * 32
    output["textbook_usage"]["citations"][0]["conclusion_paths"] = [
        "/verification_targets/2/conclusion",
        "/verification_targets/6/conclusion",
    ]
    output["textbook_usage"]["usage_sha256"] = content_sha256(
        {key: part for key, part in output["textbook_usage"].items() if key != "usage_sha256"}
    )
    return value


def test_paired_textbook_successor_schemas_are_immutable_resources() -> None:
    for name in (
        "paired-document-review-input-v4.schema.json",
        "paired-document-review-result-v4.schema.json",
    ):
        canonical = ROOT / "schemas/workflow/roles" / name
        packaged = ROOT / "packages/workflow/eom_workflow/resources/roles" / name
        assert canonical.read_bytes() == packaged.read_bytes()
        Draft202012Validator.check_schema(json.loads(canonical.read_text(encoding="utf-8")))
    assert load_role_result_schema("pdf-document-review-result@6.0")["properties"][
        "protocol_version"
    ] == {"const": "workflow-role/1.32.0"}
    assert (
        compile_definition(
            ROOT / "config/workflows/pdf-document-review.v1.5.yaml", {"support"}
        ).definition.definition_version
        == "1.5.0"
    )


def test_paired_textbook_plan_pins_exact_request_and_evidence() -> None:
    review = _paired_worker_input().request.review_request
    binding_value = _binding()
    binding_value["review_input_sha256"] = review.request_sha256
    binding_value["binding_sha256"] = content_sha256(
        {key: value for key, value in binding_value.items() if key != "binding_sha256"}
    )
    binding = ReviewTextbookEvidence.model_validate(binding_value)
    instruction = {
        "bundle_id": "instrbundle_" + "a" * 32,
        "bundle_revision_id": "instrrev_" + "b" * 32,
        "manifest_artifact": {
            "artifact_id": "artifact_" + "c" * 32,
            "artifact_revision_id": "rev_" + "d" * 32,
            "sha256": "sha256:" + "e" * 64,
            "schema_ref": "eom://schemas/workflow/bundle-manifest/1.0",
            "media_type": "application/json",
            "logical_name": "manifest.json",
        },
        "manifest_sha256": "sha256:" + "f" * 64,
    }
    plan = {
        "schema_version": "resolved-execution-plan/26.0",
        "plan_id": "execplan_" + "1" * 32,
        "workflow_id": "workflow_" + "2" * 32,
        "workload_class": "CODEX",
        "preset_id": "execpreset_" + "3" * 32,
        "preset_revision_id": "execpresetrev_" + "4" * 32,
        "preset_sha256": "sha256:" + "5" * 64,
        "workflow_definition_key": "pdf-document-review",
        "workflow_definition_version": "1.5.0",
        "workflow_definition_sha256": "sha256:" + "6" * 64,
        "review_request_sha256": review.request_sha256,
        "documents": [value.model_dump(mode="json") for value in review.documents],
        "textbook_evidence": binding.model_dump(mode="json"),
        "capacity_policy_revision_id": "capacityrev_" + "7" * 32,
        "steps": [
            {
                "step_key": "review_document",
                "role": "support",
                "model": "gpt-5.6-terra",
                "reasoning_effort": "xhigh",
                "instruction_bundle": instruction,
                "reference_bundle": None,
                "worker_pool_key": "customer-support",
                "timeout_seconds": 3600,
                "sandbox": "read-only",
                "network": "disabled",
                "general_knowledge_mode": "ALLOWED_WITH_PROVENANCE",
                "evidence_access": "EVIDENCE_CONTEXT",
            }
        ],
        "resolver_version": "26.0.0",
        "resolved_at": "2026-10-26T00:00:00Z",
    }
    plan["plan_sha256"] = content_sha256(plan)
    validate_control_contract("resolved-execution-plan-v26", plan)
    parsed = ResolvedExecutionPlanV26.model_validate(plan)
    assert parsed.textbook_evidence == binding
    plan["review_request_sha256"] = "sha256:" + "0" * 64
    plan["plan_sha256"] = content_sha256(
        {key: value for key, value in plan.items() if key != "plan_sha256"}
    )
    with pytest.raises(ValidationError, match="paired textbook plan differs"):
        ResolvedExecutionPlanV26.model_validate(plan)


def test_paired_textbook_successor_can_record_inspected_but_insufficient_evidence() -> None:
    value = _result_v4()
    output = value["output"]
    assert isinstance(output, dict)
    item = output["item_reviews"][0]
    item["evidence_status"] = "INSUFFICIENT"
    output["review_status"] = "NEEDS_HUMAN_DECISION"
    parsed = validate_role_result(value, "support", "pdf-document-review-result@6.0")
    assert isinstance(parsed, PairedDocumentReviewRoleResultV4)
    assert parsed.output.item_reviews[0].evidence_citation_ids
    assert parsed.output.item_reviews[0].evidence_status == "INSUFFICIENT"
    with pytest.raises(ValidationError):
        PairedDocumentReviewRoleResultV4.model_validate(
            {**value, "output": {**output, "textbook_usage": None}}
        )


def test_paired_textbook_worker_input_rejects_other_request_hash() -> None:
    value = _paired_worker_input().model_dump(mode="json")
    value["protocol_version"] = "workflow-role/1.32.0"
    binding = _binding()
    binding["review_input_sha256"] = value["request"]["review_request"]["request_sha256"]
    binding["binding_sha256"] = content_sha256(
        {key: part for key, part in binding.items() if key != "binding_sha256"}
    )
    value["request"]["textbook_evidence"] = binding
    validate_role_input(value, "support", "workflow-role/1.32.0")
    worker = RoleWorkerInput.model_validate(value)
    assert isinstance(worker.request.textbook_evidence, ReviewTextbookEvidence)
    constrained = constrained_result_schema("pdf-document-review-result@6.0", worker)
    assert constrained["properties"]["protocol_version"]["const"] == "workflow-role/1.32.0"
    assert constrained["$defs"]["evidence_usage"]["properties"]["manifest_sha256"]["const"] == (
        worker.request.textbook_evidence.publication.manifest_sha256
    )
    assert load_codex_result_schema("pdf-document-review-result@6.0")
    value["request"]["textbook_evidence"]["review_input_sha256"] = "sha256:" + "0" * 64
    value["request"]["textbook_evidence"]["binding_sha256"] = content_sha256(
        {
            key: part
            for key, part in value["request"]["textbook_evidence"].items()
            if key != "binding_sha256"
        }
    )
    with pytest.raises(ValidationError, match="belongs to another request"):
        RoleWorkerInput.model_validate(value)


def test_paired_textbook_result_without_exact_plan_cannot_be_committed() -> None:
    result = validate_role_result(_result_v4(), "support", "pdf-document-review-result@6.0")
    assert isinstance(result, PairedDocumentReviewRoleResultV4)
    value = _paired_worker_input().model_dump(mode="json")
    value["protocol_version"] = "workflow-role/1.32.0"
    binding = _binding()
    binding["review_input_sha256"] = value["request"]["review_request"]["request_sha256"]
    binding["binding_sha256"] = content_sha256(
        {key: part for key, part in binding.items() if key != "binding_sha256"}
    )
    value["request"]["textbook_evidence"] = binding
    worker = validate_role_input(value, "support", "workflow-role/1.32.0")
    with pytest.raises(EvidenceUsageValidationError, match="exact request"):
        validate_paired_document_textbook_for_commit(
            object(),  # type: ignore[arg-type]
            plan_id=None,
            worker_input=worker,
            result=result,
            result_artifact_id="artifact_" + "1" * 32,
            result_artifact_revision_id="rev_" + "2" * 32,
            result_content_sha256="sha256:" + "3" * 64,
            canonical_artifact_root=Path("/nonexistent-test-root"),
        )


def test_paired_textbook_projection_requires_its_exact_commit_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow, _, step, pointer, job, artifact, revision, event = _projection_fixture(monkeypatch)
    binding = ReviewTextbookEvidence.model_validate(_binding())
    value = _result_v4()
    output = value["output"]
    assert isinstance(output, dict)
    output["review_request_sha256"] = binding.review_input_sha256
    result = PairedDocumentReviewRoleResultV4.model_validate(value)
    content = result.model_dump(mode="json")
    content_hash = content_sha256(content)
    content_bytes = len(canonical_json_bytes(content))
    request = PairedDocumentReviewRequest.model_construct(
        request_sha256=binding.review_input_sha256
    )
    worker_request = PairedDocumentReviewWorkerRequestV3.model_construct(
        review_request=request,
        textbook_evidence=binding,
    )
    worker_input = RoleWorkerInput.model_construct(
        protocol_version="workflow-role/1.32.0",
        job_id=result.job_id,
        workflow_id=result.workflow_id,
        step_run_id=result.step_run_id,
        attempt=1,
        role="support",
        request=worker_request,
        artifact=SimpleNamespace(
            logical_artifact_id=result.artifact.logical_artifact_id,
            revision_id=result.artifact.revision_id,
        ),
    )
    monkeypatch.setattr(query_module.RoleWorkerInput, "model_validate", lambda _value: worker_input)
    monkeypatch.setattr(
        query_module,
        "load_persisted_workflow_request",
        lambda _value: SimpleNamespace(document_review_textbook_evidence=binding),
    )
    workflow.definition_version = "1.5.0"
    step.result_schema = "pdf-document-review-result@6.0"
    pointer = ArtifactPointer(
        step_key="review_document",
        attempt=1,
        job_id=result.job_id,
        logical_artifact_id=result.artifact.logical_artifact_id,
        revision_id=result.artifact.revision_id,
        content_hash=content_hash,
        result_schema="pdf-document-review-result@6.0",
    )
    step.output_pointer_manifest = pointer.model_dump(mode="json")
    job.protocol_version = "workflow-role/1.32.0"
    job.request_hash = content_sha256(
        {
            "protocol_version": job.protocol_version,
            "task_type": job.task_type,
            "request": job.request,
        }
    )
    revision.result = content
    revision.content_hash = content_hash
    revision.content_bytes = content_bytes
    revision.manifest = dict(
        revision.manifest, content_hash=content_hash, content_bytes=content_bytes
    )
    revision.manifest_hash = content_sha256(revision.manifest)
    publication = binding.publication
    receipt: dict[str, object] = {
        "schema_version": "review-textbook-validation-receipt/1.0",
        "plan_id": workflow.runtime_context["execution_plan"]["plan_id"],
        "plan_sha256": workflow.runtime_context["execution_plan"]["plan_sha256"],
        "workflow_id": workflow.workflow_id,
        "step_run_id": step.step_run_id,
        "job_id": result.job_id,
        "attempt": 1,
        "review_input_sha256": binding.review_input_sha256,
        "binding_sha256": binding.binding_sha256,
        "graph_snapshot_revision_id": publication.graph_snapshot.graph_snapshot_revision_id,
        "evidence_bundle_revision_id": publication.evidence_bundle_revision_id,
        "evidence_manifest_artifact": publication.manifest_artifact.model_dump(mode="json"),
        "evidence_manifest_sha256": publication.manifest_sha256,
        "evidence_context_artifact": publication.context_artifact.model_dump(mode="json"),
        "usage_sha256": result.output.textbook_usage.usage_sha256,
        "result_artifact_id": pointer.logical_artifact_id,
        "result_artifact_revision_id": pointer.revision_id,
        "result_content_sha256": content_hash,
    }
    receipt["receipt_sha256"] = content_sha256(receipt)
    event.data = {
        "logical_artifact_id": pointer.logical_artifact_id,
        "revision_id": pointer.revision_id,
        "content_hash": content_hash,
        "review_textbook_validation_receipt": receipt,
    }
    admitted = QueryAdapter._validated_paired_document_review_result(
        workflow=workflow,
        review_request=request,
        step=step,
        pointer=pointer,
        job=job,
        artifact=artifact,
        revision=revision,
        event=event,
    )
    assert isinstance(admitted, PairedDocumentReviewRoleResultV4)
    del event.data["review_textbook_validation_receipt"]
    with pytest.raises(ApiError, match="receipt"):
        QueryAdapter._validated_paired_document_review_result(
            workflow=workflow,
            review_request=request,
            step=step,
            pointer=pointer,
            job=job,
            artifact=artifact,
            revision=revision,
            event=event,
        )
