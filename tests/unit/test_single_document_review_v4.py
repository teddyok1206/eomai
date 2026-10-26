"""Single-document successor semantics, historical identity and downstream delivery."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_api.errors import ApiError
from eom_api.services.command_adapter import CommandAdapter
from eom_api.services.query_adapter import QueryAdapter
from eom_catalog_contracts import (
    DocumentReviewHwpxCorrectionPlanV2,
    PdfDocumentReviewResultMemberPointerV2,
    validate_contract,
)
from eom_catalog_service.document_review_hwpx import (
    apply_document_review_hwpx_correction,
    build_document_review_hwpx_correction_plan,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_file
from eom_orchestrator.execution_materializer import _admitted_document_review_contract
from eom_orchestrator.pdf_document_review_bootstrap import (
    load_pdf_document_review_bootstrap_manifest,
)
from eom_workflow import (
    PdfDocumentReviewOutput,
    PdfDocumentReviewOutputV4,
    PdfDocumentReviewRoleResultV4,
    ResolvedExecutionPlanV13,
    RoleWorkerInput,
    WorkflowRequest,
    compile_definition,
    single_document_review_contract_for_definition,
    single_document_review_contract_for_schema_ref,
)
from eom_workflow.schemas import (
    constrained_result_schema,
    load_role_result_schema,
    role_schema_bundle_hash,
    validate_role_input,
    validate_role_result,
)
from eom_workflow_runner.repository import workflow_request_storage_document
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from tests.api.test_paired_document_review_replay import _ReplaySession
from tests.unit.test_document_review_hwpx import _base_pointer, _replacement, _write_hwpx
from tests.unit.test_pdf_document_review_projection import _records, _request, _workflow
from tests.unit.test_pdf_document_review_protocol import _input, _result

ROOT = Path(__file__).resolve().parents[2]
AXES = (
    "SCIENTIFIC_ACCURACY",
    "ANSWER_UNIQUENESS",
    "SOLUTION_CONSISTENCY",
    "CURRICULUM_SCOPE",
    "ORIGINALITY",
    "VISUAL_CONTENT",
    "EDITORIAL_CLARITY",
    "TYPOGRAPHY",
    "DOCUMENT_STRUCTURE",
    "ASSESSMENT_BALANCE",
)


def result_v4() -> dict[str, Any]:
    value = copy.deepcopy(_result())
    value["protocol_version"] = "workflow-role/1.28.0"
    output = value["output"]
    template = output["verification_targets"][0]
    output["verification_targets"] = [
        dict(
            template,
            target_id=f"reviewtarget_{index:032x}",
            axis=axis,
            status="FAILED" if axis == "ANSWER_UNIQUENESS" else "VERIFIED",
        )
        for index, axis in enumerate(AXES, 1)
    ]
    output["review_status"] = "NEEDS_HUMAN_DECISION"
    return value


def test_v4_accepts_failed_targets_and_confirmed_findings_without_relabelling() -> None:
    value = result_v4()
    untouched = copy.deepcopy(value)
    Draft202012Validator(load_role_result_schema("pdf-document-review-result@4.0")).validate(value)
    result = validate_role_result(value, "support", "pdf-document-review-result@4.0")
    assert isinstance(result, PdfDocumentReviewRoleResultV4)
    assert result.output.review_status == "NEEDS_HUMAN_DECISION"
    assert len(result.output.findings) == 1
    assert value == untouched
    legacy = copy.deepcopy(value)
    legacy["protocol_version"] = "workflow-role/1.25.0"
    with pytest.raises(ValueError, match="candidate dispositions"):
        validate_role_result(legacy, "support", "pdf-document-review-result@1.0")


@pytest.mark.parametrize("status", ["VERIFIED", "FAILED", "INSUFFICIENT"])
@pytest.mark.parametrize("uncertain", [False, True])
def test_schema_and_typed_status_policy_agree(status: str, uncertain: bool) -> None:
    value = result_v4()
    output = value["output"]
    for target in output["verification_targets"]:
        target["status"] = status
    if uncertain:
        output["candidate_findings"][0]["disposition"] = "UNCERTAIN"
        output["findings"] = []
    expected = "NEEDS_HUMAN_DECISION" if uncertain or status != "VERIFIED" else "COMPLETE"
    output["review_status"] = expected
    schema = Draft202012Validator(load_role_result_schema("pdf-document-review-result@4.0"))
    schema.validate(value)
    PdfDocumentReviewRoleResultV4.model_validate(value)
    output["review_status"] = "COMPLETE" if expected != "COMPLETE" else "NEEDS_HUMAN_DECISION"
    assert list(schema.iter_errors(value))
    with pytest.raises(ValidationError, match="status differs"):
        PdfDocumentReviewRoleResultV4.model_validate(value)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unordered"])
def test_v4_rejects_missing_duplicate_or_unordered_targets(mutation: str) -> None:
    value = result_v4()
    targets = value["output"]["verification_targets"]
    if mutation == "missing":
        targets.pop()
    elif mutation == "duplicate":
        targets[-1]["axis"] = targets[0]["axis"]
    else:
        targets.reverse()
    with pytest.raises(ValueError):
        validate_role_result(value, "support", "pdf-document-review-result@4.0")


def test_new_protocol_admission_projection_and_instructions_match() -> None:
    manifest = load_pdf_document_review_bootstrap_manifest(
        ROOT / "config/control-plane/pdf-document-review-v6"
    )
    assert manifest.compatible_workflow_protocols[-1] == "workflow-role/1.28.0"
    assert manifest.instruction_revision_number == 6
    compiled = compile_definition(
        ROOT / "config/workflows/pdf-document-review.v1.3.yaml", {"support"}
    )
    assert compiled.definition.definition_version == "1.3.0"
    worker = _input()
    worker["protocol_version"] = "workflow-role/1.28.0"
    validate_role_input(worker, "support", "workflow-role/1.28.0")
    schema = constrained_result_schema(
        "pdf-document-review-result@4.0", RoleWorkerInput.model_validate(worker)
    )
    assert schema["properties"]["protocol_version"]["const"] == "workflow-role/1.28.0"
    output_ref = schema["properties"]["output"]["$ref"].split("/")[-1]
    assert (
        "INSUFFICIENT" in schema["$defs"][output_ref]["properties"]["review_status"]["description"]
    )
    notice = _admitted_document_review_contract(
        ResolvedExecutionPlanV13.model_construct(workflow_definition_version="1.3.0")
    ).decode()
    assert "pdf-document-review-result@4.0" in notice
    assert "NEEDS_HUMAN_DECISION" in notice
    assert "No Graph evidence" in notice


@pytest.mark.parametrize(
    ("protocol", "sha"),
    [
        (
            "workflow-role/1.25.0",
            "94d6262a483c83d193571d183b9ba00083276e0eb146db83f4d91350aba22c61",
        ),
        (
            "workflow-role/1.26.0",
            "5c4c2a9225abeab576fbb819188e945c2415513d60f343a7790841c098599a51",
        ),
        (
            "workflow-role/1.27.0",
            "fbb22ebc5f64200345c706a4018cc319efd074fb9a4dbdb9e65a8d0c6d7625c7",
        ),
    ],
)
def test_historical_protocol_hashes_unchanged(protocol: str, sha: str) -> None:
    assert role_schema_bundle_hash(protocol) == f"sha256:{sha}"


@pytest.mark.parametrize(
    ("lookup", "value"),
    [
        (single_document_review_contract_for_definition, "1.2.0"),
        (single_document_review_contract_for_schema_ref, "file:///unexpected.json"),
    ],
)
def test_unknown_contract_never_falls_back_to_legacy(lookup: Any, value: str) -> None:
    with pytest.raises(ValueError, match="unsupported"):
        lookup(value)


def v4_records() -> tuple[Any, ...]:
    step, pointer, job, artifact, revision, event = _records()
    value = PdfDocumentReviewRoleResultV4.model_validate(result_v4()).model_dump(mode="json")
    result_hash = content_sha256(value)
    result_length = len(canonical_json_bytes(value))
    pointer = pointer.model_copy(
        update={"result_schema": "pdf-document-review-result@4.0", "content_hash": result_hash}
    )
    step.result_schema = pointer.result_schema
    step.output_pointer_manifest = pointer.model_dump(mode="json")
    job.protocol_version = "workflow-role/1.28.0"
    job.request = dict(job.request, protocol_version=job.protocol_version)
    job.request_hash = content_sha256(
        {
            "protocol_version": job.protocol_version,
            "task_type": job.task_type,
            "request": job.request,
        }
    )
    revision.result = value
    revision.content_hash = result_hash
    revision.content_bytes = result_length
    revision.manifest = dict(
        revision.manifest, content_hash=result_hash, content_bytes=result_length
    )
    revision.manifest_hash = content_sha256(revision.manifest)
    event.data = dict(event.data, content_hash=result_hash)
    return step, pointer, job, artifact, revision, event


def test_exact_new_revision_projects_and_preserves_non_complete_status() -> None:
    step, pointer, job, artifact, revision, event = v4_records()
    result = QueryAdapter._validated_pdf_document_review_result(
        workflow=_workflow(),
        workflow_id=step.workflow_id,
        definition_version="1.3.0",
        review_request=_request(),
        step=step,
        pointer=pointer,
        job=job,
        artifact=artifact,
        revision=revision,
        event=event,
    )
    assert isinstance(result, PdfDocumentReviewRoleResultV4)
    workflow = _workflow()
    workflow.definition_version = "1.3.0"
    view = QueryAdapter._pdf_document_review(workflow, result, None)
    assert isinstance(view.result, PdfDocumentReviewOutputV4)
    assert view.result.review_status == "NEEDS_HUMAN_DECISION"
    assert view.model_dump(mode="json")["result"]["review_status"] == "NEEDS_HUMAN_DECISION"
    with pytest.raises(ApiError):
        QueryAdapter._validated_pdf_document_review_result(
            workflow=_workflow(),
            workflow_id=step.workflow_id,
            definition_version="1.0.0",
            review_request=_request(),
            step=step,
            pointer=pointer,
            job=job,
            artifact=artifact,
            revision=revision,
            event=event,
        )


@pytest.mark.parametrize("damage", ["hash", "pointer_schema", "protocol", "missing"])
def test_new_pointer_integrity_does_not_relax_existing_checks(damage: str) -> None:
    step, pointer, job, artifact, revision, event = v4_records()
    if damage == "hash":
        revision.content_hash = "sha256:" + "0" * 64
    elif damage == "pointer_schema":
        pointer = pointer.model_copy(update={"result_schema": "pdf-document-review-result@1.0"})
    elif damage == "protocol":
        job.protocol_version = "workflow-role/1.25.0"
    else:
        revision = None
    with pytest.raises(ApiError):
        QueryAdapter._validated_pdf_document_review_result(
            workflow=_workflow(),
            workflow_id=step.workflow_id,
            definition_version="1.3.0",
            review_request=_request(),
            step=step,
            pointer=pointer,
            job=job,
            artifact=artifact,
            revision=revision,
            event=event,
        )


def test_historical_complete_still_has_its_original_meaning() -> None:
    old = PdfDocumentReviewOutput.model_validate(_result()["output"])
    assert old.review_status == "COMPLETE"
    assert old.verification_targets[0].status == "FAILED"


@pytest.mark.parametrize("definition_version", ["1.0.0", "1.3.0"])
def test_same_key_replay_keeps_exact_receipt_without_current_activation(
    definition_version: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = _workflow()
    workflow.definition_version = definition_version
    request = WorkflowRequest(
        request_name="PDF_DOCUMENT_REVIEW_REQUEST",
        image_mode="skip",
        execution_preset_key="pdf-document-review",
        pdf_document_review_request=_request(),
    )
    workflow.initial_request = workflow_request_storage_document(request)
    command = SimpleNamespace(command_id="wfcmd_" + "4" * 32)
    adapter = object.__new__(CommandAdapter)
    adapter.sessions = lambda: _ReplaySession(workflow, command)  # type: ignore[assignment]

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("same-key replay consulted current runtime activation")

    monkeypatch.setattr("eom_api.services.command_adapter.admitted_workflow_definition", forbidden)
    result = adapter.start_pdf_document_review(
        _request(),
        SimpleNamespace(actor_id=workflow.created_actor_id),  # type: ignore[arg-type]
        idempotency_key="review-single-replay",
    )
    assert result == (command.command_id, workflow.workflow_id, workflow.lock_version)


def test_v4_correction_uses_successor_plan_and_existing_redline_renderer(tmp_path: Path) -> None:
    source, output = tmp_path / "source.hwpx", tmp_path / "redline.hwpx"
    _write_hwpx(source)
    before = sha256_file(source)
    pointer = PdfDocumentReviewResultMemberPointerV2(
        artifact_id="artifact_" + "1" * 32,
        artifact_revision_id="rev_" + "2" * 32,
        sha256="sha256:" + "3" * 64,
        content_length=1024,
    )
    plan = build_document_review_hwpx_correction_plan(
        source,
        correction_id="doccorrection_" + "6" * 32,
        workflow_id="workflow_" + "7" * 32,
        review_result=pointer,
        base_hwpx=_base_pointer(source),
        replacements=(_replacement(),),
    )
    assert isinstance(plan, DocumentReviewHwpxCorrectionPlanV2)
    validate_contract("document-review-hwpx-correction-plan-v2", plan.model_dump(mode="json"))
    result = apply_document_review_hwpx_correction(source, output, plan)
    assert result.plan_sha256 == plan.plan_sha256
    assert sha256_file(source) == before
    assert result.output_member.sha256 == sha256_file(output)


@pytest.mark.parametrize(
    "relative",
    [
        "workflow/roles/pdf-document-review-input-v4.schema.json",
        "workflow/roles/pdf-document-review-result-v4.schema.json",
        "workflow/control-plane/pdf-document-review-control-bootstrap-v6.schema.json",
        "catalog/catalog-application/document-review-pdf-annotation-request-v4.schema.json",
        "catalog/catalog-application/document-review-hwpx-correction-request-v2.schema.json",
        "document-review/document-review-hwpx-correction-plan-v2.schema.json",
    ],
)
def test_successor_schemas_are_mirrored_and_valid(relative: str) -> None:
    canonical = ROOT / "schemas" / relative
    parts = relative.split("/")
    packaged = (
        ROOT / "packages/workflow/eom_workflow/resources" / "/".join(parts[1:])
        if parts[0] == "workflow"
        else ROOT
        / "packages/catalog_contracts/eom_catalog_contracts/resources"
        / ("/".join(parts[1:]) if parts[0] == "catalog" else relative)
    )
    assert canonical.read_bytes() == packaged.read_bytes()
    Draft202012Validator.check_schema(json.loads(canonical.read_bytes()))
