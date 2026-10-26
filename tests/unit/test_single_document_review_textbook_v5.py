"""Unactivated single-document successor binds textbook usage to science conclusions."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
from eom_api.errors import ApiError
from eom_api.services.query_adapter import QueryAdapter
from eom_catalog_contracts import ReviewTextbookEvidence
from eom_catalog_contracts.knowledge import (
    EvidenceBundleManifestV3,
    EvidenceBundlePublicationResultV3,
)
from eom_catalog_contracts.validation import catalog_schema_registry, validate_contract
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator import execution_materializer
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.evidence_usage_validation import EvidenceUsageValidationError
from eom_orchestrator.review_textbook_evidence_validation import (
    validate_single_document_textbook_for_commit,
)
from eom_workflow.control_plane import ResolvedExecutionPlanV25, ReviewTextbookValidationReceipt
from eom_workflow.control_schemas import validate_control_contract
from eom_workflow.document_review import (
    PdfDocumentReviewRequest,
    PdfDocumentReviewWorkerRequestV5,
    validate_single_document_review_textbook_usage,
)
from eom_workflow.models import PdfDocumentReviewRoleResultV5, RoleWorkerInput, WorkflowRequest
from eom_workflow.schemas import (
    constrained_result_schema,
    load_codex_result_schema,
    role_schema_bundle_hash,
    validate_role_input,
    validate_role_result,
)
from eom_workflow_runner.repository import workflow_request_storage_document
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from tests.unit.test_knowledge_analysis_document_contracts import document_source
from tests.unit.test_pdf_document_review_protocol import _input
from tests.unit.test_review_textbook_evidence import _binding, _manifest, _publication, _usage
from tests.unit.test_single_document_review_v4 import _workflow, result_v4, v4_records


def _result_v5() -> dict[str, Any]:
    value = result_v4()
    value["protocol_version"] = "workflow-role/1.31.0"
    usage = _usage_from_binding()
    usage["citations"][0]["conclusion_paths"] = [
        "/verification_targets/0/conclusion",
        "/verification_targets/3/conclusion",
    ]
    usage["usage_sha256"] = content_sha256(
        {key: item for key, item in usage.items() if key != "usage_sha256"}
    )
    value["output"]["textbook_usage"] = usage
    return value


def _usage_from_binding() -> dict[str, Any]:
    binding = _input_v5()["request"]["textbook_evidence"]
    return _usage(ReviewTextbookEvidence.model_validate(binding))


def _schema() -> dict[str, Any]:
    raw = (
        resources.files("eom_workflow")
        .joinpath("resources/roles/pdf-document-review-result-v5.schema.json")
        .read_text(encoding="utf-8")
    )
    return json.loads(raw)


def _input_v5() -> dict[str, Any]:
    value = _input()
    value["protocol_version"] = "workflow-role/1.31.0"
    binding = _binding()
    binding["review_input_sha256"] = value["request"]["review_request"]["request_sha256"]
    binding["binding_sha256"] = content_sha256(
        {key: item for key, item in binding.items() if key != "binding_sha256"}
    )
    value["request"]["textbook_evidence"] = binding
    return value


def test_textbook_grounded_single_input_is_schema_and_model_valid() -> None:
    value = _input_v5()
    schema = json.loads(
        resources.files("eom_workflow")
        .joinpath("resources/roles/pdf-document-review-input-v5.schema.json")
        .read_text(encoding="utf-8")
    )
    Draft202012Validator(
        schema, format_checker=FormatChecker(), registry=catalog_schema_registry()
    ).validate(value)
    PdfDocumentReviewWorkerRequestV5.model_validate(value["request"])
    assert isinstance(
        RoleWorkerInput.model_validate(value).request,
        PdfDocumentReviewWorkerRequestV5,
    )
    wrong = _input_v5()
    wrong["request"]["textbook_evidence"]["review_input_sha256"] = "sha256:" + "0" * 64
    wrong["request"]["textbook_evidence"]["binding_sha256"] = content_sha256(
        {
            key: item
            for key, item in wrong["request"]["textbook_evidence"].items()
            if key != "binding_sha256"
        }
    )
    with pytest.raises(ValidationError, match="belongs to another request"):
        PdfDocumentReviewWorkerRequestV5.model_validate(wrong["request"])
    predecessor = _input_v5()
    predecessor["protocol_version"] = "workflow-role/1.28.0"
    with pytest.raises(ValidationError, match="isolated protocol successor"):
        RoleWorkerInput.model_validate(predecessor)


def test_workflow_request_selects_successor_without_changing_predecessor_storage() -> None:
    source = _input_v5()["request"]
    review_request = PdfDocumentReviewRequest.model_validate(source["review_request"])
    legacy = WorkflowRequest(
        request_name="PDF_DOCUMENT_REVIEW_REQUEST",
        image_mode="skip",
        execution_preset_key="pdf-document-review",
        pdf_document_review_request=review_request,
    )
    assert "document_review_textbook_evidence" not in workflow_request_storage_document(legacy)
    binding = ReviewTextbookEvidence.model_validate(source["textbook_evidence"])
    successor = WorkflowRequest.model_validate(
        {
            **legacy.model_dump(mode="json"),
            "document_review_textbook_evidence": binding.model_dump(mode="json"),
        }
    )
    assert isinstance(successor.worker_request(), PdfDocumentReviewWorkerRequestV5)
    assert (
        workflow_request_storage_document(successor)["document_review_textbook_evidence"][
            "binding_sha256"
        ]
        == binding.binding_sha256
    )
    with pytest.raises(ValidationError, match="single document textbook evidence differs"):
        WorkflowRequest(
            request_name="CUSTOMER_SUPPORT_REQUEST",
            image_mode="skip",
            document_review_textbook_evidence=binding,
        )


def test_successor_plan_schema_pins_same_textbook_binding_as_worker_request() -> None:
    worker = PdfDocumentReviewWorkerRequestV5.model_validate(_input_v5()["request"])
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
    plan: dict[str, Any] = {
        "schema_version": "resolved-execution-plan/25.0",
        "plan_id": "execplan_" + "1" * 32,
        "workflow_id": "workflow_" + "2" * 32,
        "workload_class": "CODEX",
        "preset_id": "execpreset_" + "3" * 32,
        "preset_revision_id": "execpresetrev_" + "4" * 32,
        "preset_sha256": "sha256:" + "5" * 64,
        "workflow_definition_key": "pdf-document-review",
        "workflow_definition_version": "1.4.0",
        "workflow_definition_sha256": "sha256:" + "6" * 64,
        "review_request_sha256": worker.review_request.request_sha256,
        "document": worker.review_request.document.model_dump(mode="json"),
        "textbook_evidence": worker.textbook_evidence.model_dump(mode="json"),
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
            }
        ],
        "resolver_version": "25.0.0",
        "resolved_at": "2026-10-26T00:00:00Z",
    }
    plan["plan_sha256"] = content_sha256(plan)
    validate_control_contract("resolved-execution-plan-v25", plan)
    admitted = ResolvedExecutionPlanV25.model_validate(plan)
    assert admitted.textbook_evidence == worker.textbook_evidence
    changed = dict(plan)
    changed["review_request_sha256"] = "sha256:" + "0" * 64
    changed["plan_sha256"] = content_sha256(
        {key: value for key, value in changed.items() if key != "plan_sha256"}
    )
    with pytest.raises(ValidationError, match="belongs to another request"):
        ResolvedExecutionPlanV25.model_validate(changed)


def test_textbook_grounded_single_result_is_schema_and_model_valid() -> None:
    value = _result_v5()
    Draft202012Validator(
        _schema(), format_checker=FormatChecker(), registry=catalog_schema_registry()
    ).validate(value)
    result = PdfDocumentReviewRoleResultV5.model_validate(value)
    assert result.output.textbook_usage.citations[0].conclusion_paths == (
        "/verification_targets/0/conclusion",
        "/verification_targets/3/conclusion",
    )


def test_successor_registry_and_worker_projection_bind_exact_review_evidence() -> None:
    worker_input = validate_role_input(_input_v5(), "support", "workflow-role/1.31.0")
    result = _result_v5()
    assert isinstance(
        validate_role_result(result, "support", "pdf-document-review-result@5.0"),
        PdfDocumentReviewRoleResultV5,
    )
    projected = constrained_result_schema("pdf-document-review-result@5.0", worker_input)
    usage = projected["$defs"]["ReviewTextbookUsage"]
    assert usage["properties"]["binding_sha256"]["const"] == (
        worker_input.request.textbook_evidence.binding_sha256
    )
    assert "usage_sha256" not in usage["properties"]
    assert role_schema_bundle_hash("workflow-role/1.31.0").startswith("sha256:")
    assert load_codex_result_schema("pdf-document-review-result@5.0")


def test_worker_omitted_usage_hash_is_derived_but_supplied_mismatch_is_rejected() -> None:
    value = _result_v5()
    del value["output"]["textbook_usage"]["usage_sha256"]
    admitted = validate_role_result(value, "support", "pdf-document-review-result@5.0")
    assert isinstance(admitted, PdfDocumentReviewRoleResultV5)
    assert admitted.output.textbook_usage.usage_sha256.startswith("sha256:")
    value["output"]["textbook_usage"]["usage_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="typed validation"):
        validate_role_result(value, "support", "pdf-document-review-result@5.0")


def test_supported_curriculum_conclusion_cannot_omit_textbook_citation() -> None:
    value = _result_v5()
    usage = value["output"]["textbook_usage"]
    usage["citations"][0]["conclusion_paths"] = ["/verification_targets/0/conclusion"]
    usage["usage_sha256"] = content_sha256(
        {key: item for key, item in usage.items() if key != "usage_sha256"}
    )
    with pytest.raises(ValidationError, match="cover science axes"):
        PdfDocumentReviewRoleResultV5.model_validate(value)


def test_insufficient_science_conclusion_still_identifies_examined_textbook() -> None:
    value = _result_v5()
    value["output"]["verification_targets"][0]["status"] = "INSUFFICIENT"
    value["output"]["verification_targets"][3]["status"] = "INSUFFICIENT"
    result = PdfDocumentReviewRoleResultV5.model_validate(value)
    assert result.output.review_status == "NEEDS_HUMAN_DECISION"
    assert len(result.output.textbook_usage.citations[0].conclusion_paths) == 2


def test_trusted_single_review_validation_reopens_exact_textbook_manifest() -> None:
    worker_input = validate_role_input(_input_v5(), "support", "workflow-role/1.31.0")
    assert isinstance(worker_input.request, PdfDocumentReviewWorkerRequestV5)
    result = validate_role_result(_result_v5(), "support", "pdf-document-review-result@5.0")
    assert isinstance(result, PdfDocumentReviewRoleResultV5)
    binding = worker_input.request.textbook_evidence
    validate_single_document_review_textbook_usage(
        result.output, worker_input.request, _manifest(binding)
    )
    with pytest.raises(ValueError, match="non-textbook source"):
        validate_single_document_review_textbook_usage(
            result.output,
            worker_input.request,
            _manifest(binding, source_class="PAST_EXAM"),
        )


def test_materializer_reopens_only_authorized_textbook_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publication_value = _publication().model_dump(mode="json")
    manifest_value: dict[str, Any] = {
        "schema_version": "evidence-bundle-manifest/3.0",
        "evidence_bundle_id": publication_value["evidence_bundle_id"],
        "evidence_bundle_revision_id": publication_value["evidence_bundle_revision_id"],
        "revision_number": 1,
        "retrieval_request_id": publication_value["retrieval_request_id"],
        "retrieval_request_sha256": publication_value["retrieval_request_sha256"],
        "graph_snapshot": publication_value["graph_snapshot"],
        "access_policy_revision_id": publication_value["access_policy_revision_id"],
        "access_policy_sha256": publication_value["access_policy_sha256"],
        "requester_permissions_sha256": publication_value["requester_permissions_sha256"],
        "materials": {"context_markdown": publication_value["context_artifact"]},
        "entries": [
            {
                "evidence_id": "evidenceitem_" + "9" * 32,
                "evidence_kind": "DOCUMENT",
                "use": "GROUNDING",
                "source": document_source(),
                "graph_node_ids": ["knode_document"],
                "anchor_ids": ["anchor_document"],
                "relevance_milli": 1000,
                "answer_bearing": False,
            }
        ],
        "budget": publication_value["budget"],
        "created_at": "2026-10-26T00:00:00Z",
    }
    manifest_value["manifest_sha256"] = content_sha256(manifest_value)
    validate_contract("evidence-bundle-manifest-v3", manifest_value)
    manifest = EvidenceBundleManifestV3.model_validate(manifest_value)
    manifest_payload = canonical_json_bytes(manifest.model_dump(mode="json"))
    publication_value["schema_version"] = "evidence-bundle-publication-result/3.0"
    member = publication_value["manifest_artifact"]
    assert isinstance(member, dict)
    member["schema_ref"] = "eom://schemas/knowledge/evidence-bundle-manifest/3.0"
    member["sha256"] = sha256_bytes(manifest_payload)
    publication_value["manifest_sha256"] = manifest.manifest_sha256
    publication_value["result_sha256"] = content_sha256(
        {key: value for key, value in publication_value.items() if key != "result_sha256"}
    )
    publication = EvidenceBundlePublicationResultV3.model_validate(publication_value)
    binding_value = _binding()
    binding_value["publication"] = publication.model_dump(mode="json")
    binding_value["binding_sha256"] = content_sha256(
        {key: value for key, value in binding_value.items() if key != "binding_sha256"}
    )
    binding = ReviewTextbookEvidence.model_validate(binding_value)
    manifest_revision = binding.publication.manifest_artifact.artifact_revision_id
    context_revision = binding.publication.context_artifact.artifact_revision_id
    monkeypatch.setattr(execution_materializer, "_canonical_root", lambda path: path)

    def read_member(_session: object, *, pointer: object, **_kwargs: object) -> bytes:
        return manifest_payload if pointer == binding.publication.manifest_artifact else b"textbook"

    monkeypatch.setattr(execution_materializer, "_knowledge_member_payload", read_member)
    materials = execution_materializer.resolve_textbook_review_materials(
        object(),  # type: ignore[arg-type]
        binding=binding,
        canonical_artifact_root=Path("/nonexistent-test-root"),
        authorized_artifact_revision_ids=frozenset({manifest_revision, context_revision}),
    )
    assert materials.manifest_payload == manifest_payload
    assert materials.context_payload == b"textbook"
    with pytest.raises(ControlPlaneError, match="not authorized"):
        execution_materializer.resolve_textbook_review_materials(
            object(),  # type: ignore[arg-type]
            binding=binding,
            canonical_artifact_root=Path("/nonexistent-test-root"),
            authorized_artifact_revision_ids=frozenset({manifest_revision}),
        )


def test_textbook_receipt_schema_and_model_preserve_distinct_hashes() -> None:
    binding = ReviewTextbookEvidence.model_validate(_input_v5()["request"]["textbook_evidence"])
    publication = binding.publication
    receipt: dict[str, Any] = {
        "schema_version": "review-textbook-validation-receipt/1.0",
        "plan_id": "execplan_" + "1" * 32,
        "plan_sha256": "sha256:" + "2" * 64,
        "workflow_id": "workflow_" + "3" * 32,
        "step_run_id": "steprun_" + "4" * 32,
        "job_id": "job_" + "5" * 32,
        "attempt": 1,
        "review_input_sha256": binding.review_input_sha256,
        "binding_sha256": binding.binding_sha256,
        "graph_snapshot_revision_id": publication.graph_snapshot.graph_snapshot_revision_id,
        "evidence_bundle_revision_id": publication.evidence_bundle_revision_id,
        "evidence_manifest_artifact": publication.manifest_artifact.model_dump(mode="json"),
        "evidence_manifest_sha256": publication.manifest_sha256,
        "evidence_context_artifact": publication.context_artifact.model_dump(mode="json"),
        "usage_sha256": _usage_from_binding()["usage_sha256"],
        "result_artifact_id": "artifact_" + "6" * 32,
        "result_artifact_revision_id": "rev_" + "7" * 32,
        "result_content_sha256": "sha256:" + "8" * 64,
    }
    receipt["receipt_sha256"] = content_sha256(receipt)
    validate_control_contract("review-textbook-validation-receipt", receipt)
    admitted = ReviewTextbookValidationReceipt.model_validate(receipt)
    assert admitted.evidence_manifest_sha256 == publication.manifest_sha256
    assert admitted.evidence_manifest_artifact.sha256 == publication.manifest_artifact.sha256
    wrong = dict(receipt)
    wrong["usage_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError, match="pointers or hash differ"):
        ReviewTextbookValidationReceipt.model_validate(wrong)


def test_completed_single_review_reader_requires_exact_textbook_receipt() -> None:
    step, pointer, job, artifact, revision, event = v4_records()
    result = PdfDocumentReviewRoleResultV5.model_validate(_result_v5())
    result_value = result.model_dump(mode="json")
    result_hash = content_sha256(result_value)
    result_length = len(canonical_json_bytes(result_value))
    pointer = pointer.model_copy(
        update={"result_schema": "pdf-document-review-result@5.0", "content_hash": result_hash}
    )
    step.result_schema = pointer.result_schema
    step.output_pointer_manifest = pointer.model_dump(mode="json")
    job.protocol_version = "workflow-role/1.31.0"
    job.request = _input_v5()
    job.request_hash = content_sha256(
        {
            "protocol_version": job.protocol_version,
            "task_type": job.task_type,
            "request": job.request,
        }
    )
    revision.result = result_value
    revision.content_hash = result_hash
    revision.content_bytes = result_length
    revision.manifest = dict(
        revision.manifest, content_hash=result_hash, content_bytes=result_length
    )
    revision.manifest_hash = content_sha256(revision.manifest)
    workflow = _workflow()
    workflow.definition_version = "1.4.0"
    binding = ReviewTextbookEvidence.model_validate(_input_v5()["request"]["textbook_evidence"])
    review_request = PdfDocumentReviewRequest.model_validate(
        _input_v5()["request"]["review_request"]
    )
    workflow.initial_request = workflow_request_storage_document(
        WorkflowRequest(
            request_name="PDF_DOCUMENT_REVIEW_REQUEST",
            image_mode="skip",
            execution_preset_key="pdf-document-review",
            pdf_document_review_request=review_request,
            document_review_textbook_evidence=binding,
        )
    )
    workflow.runtime_context = {
        "execution_plan": {
            "plan_id": "execplan_" + "1" * 32,
            "plan_sha256": "sha256:" + "2" * 64,
        }
    }
    publication = binding.publication
    receipt: dict[str, Any] = {
        "schema_version": "review-textbook-validation-receipt/1.0",
        "plan_id": workflow.runtime_context["execution_plan"]["plan_id"],
        "plan_sha256": workflow.runtime_context["execution_plan"]["plan_sha256"],
        "workflow_id": workflow.workflow_id,
        "step_run_id": step.step_run_id,
        "job_id": pointer.job_id,
        "attempt": step.attempt,
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
        "result_content_sha256": result_hash,
    }
    receipt["receipt_sha256"] = content_sha256(receipt)
    event.data = dict(
        event.data,
        content_hash=result_hash,
        review_textbook_validation_receipt=receipt,
    )
    admitted = QueryAdapter._validated_pdf_document_review_result(
        workflow=workflow,
        workflow_id=workflow.workflow_id,
        definition_version="1.4.0",
        review_request=review_request,
        step=step,
        pointer=pointer,
        job=job,
        artifact=artifact,
        revision=revision,
        event=event,
    )
    assert isinstance(admitted, PdfDocumentReviewRoleResultV5)
    assert QueryAdapter._pdf_document_review(workflow, admitted, None).result is not None
    event.data["review_textbook_validation_receipt"] = None
    with pytest.raises(ApiError, match="receipt"):
        QueryAdapter._validated_pdf_document_review_result(
            workflow=workflow,
            workflow_id=workflow.workflow_id,
            definition_version="1.4.0",
            review_request=review_request,
            step=step,
            pointer=pointer,
            job=job,
            artifact=artifact,
            revision=revision,
            event=event,
        )


def test_trusted_single_review_rejects_other_request_binding() -> None:
    value = _result_v5()
    other_binding = ReviewTextbookEvidence.model_validate(_binding())
    usage = value["output"]["textbook_usage"]
    usage["binding_sha256"] = other_binding.binding_sha256
    usage["usage_sha256"] = content_sha256(
        {key: item for key, item in usage.items() if key != "usage_sha256"}
    )
    result = validate_role_result(value, "support", "pdf-document-review-result@5.0")
    assert isinstance(result, PdfDocumentReviewRoleResultV5)
    worker_input = PdfDocumentReviewWorkerRequestV5.model_validate(_input_v5()["request"])
    with pytest.raises(ValueError, match="different binding"):
        validate_single_document_review_textbook_usage(
            result.output, worker_input, _manifest(worker_input.textbook_evidence)
        )


def test_trusted_single_review_rejects_blank_science_conclusion() -> None:
    value = _result_v5()
    value["output"]["verification_targets"][0]["conclusion"] = " "
    result = validate_role_result(value, "support", "pdf-document-review-result@5.0")
    assert isinstance(result, PdfDocumentReviewRoleResultV5)
    worker_input = PdfDocumentReviewWorkerRequestV5.model_validate(_input_v5()["request"])
    with pytest.raises(ValueError, match="does not resolve to a science conclusion"):
        validate_single_document_review_textbook_usage(
            result.output, worker_input, _manifest(worker_input.textbook_evidence)
        )


def test_successor_without_exact_plan_cannot_reach_artifact_commit() -> None:
    successor = validate_role_result(_result_v5(), "support", "pdf-document-review-result@5.0")
    assert isinstance(successor, PdfDocumentReviewRoleResultV5)
    worker_input = validate_role_input(_input_v5(), "support", "workflow-role/1.31.0")
    with pytest.raises(EvidenceUsageValidationError, match="exact typed request"):
        validate_single_document_textbook_for_commit(
            object(),  # type: ignore[arg-type]
            plan_id=None,
            worker_input=worker_input,
            result=successor,
            result_artifact_id="artifact_" + "1" * 32,
            result_artifact_revision_id="rev_" + "2" * 32,
            result_content_sha256="sha256:" + "3" * 64,
            canonical_artifact_root=Path("/nonexistent-test-root"),
        )


def test_predecessor_schema_does_not_accept_successor_textbook_result() -> None:
    value = _result_v5()
    predecessor = resources.files("eom_workflow").joinpath(
        "resources/roles/pdf-document-review-result-v4.schema.json"
    )
    schema = json.loads(predecessor.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(value))
