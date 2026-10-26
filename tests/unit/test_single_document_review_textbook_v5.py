"""Unactivated single-document successor binds textbook usage to science conclusions."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

import pytest
from eom_catalog_contracts import ReviewTextbookEvidence
from eom_catalog_contracts.validation import catalog_schema_registry
from eom_identifiers import content_sha256
from eom_workflow.document_review import (
    PdfDocumentReviewWorkerRequestV5,
    validate_single_document_review_textbook_usage,
)
from eom_workflow.models import PdfDocumentReviewRoleResultV5, RoleWorkerInput
from eom_workflow.schemas import (
    constrained_result_schema,
    load_codex_result_schema,
    role_schema_bundle_hash,
    validate_role_input,
    validate_role_result,
)
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from tests.unit.test_pdf_document_review_protocol import _input
from tests.unit.test_review_textbook_evidence import _binding, _manifest, _usage
from tests.unit.test_single_document_review_v4 import result_v4


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


def test_predecessor_schema_does_not_accept_successor_textbook_result() -> None:
    value = _result_v5()
    predecessor = resources.files("eom_workflow").joinpath(
        "resources/roles/pdf-document-review-result-v4.schema.json"
    )
    schema = json.loads(predecessor.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(value))
