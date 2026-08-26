from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from eom_catalog_contracts import (
    CreateKnowledgeAnalysisBatchCommand,
    KnowledgeAnalysisBatchRequest,
    validate_contract,
)
from eom_identifiers import content_sha256
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError


def _request() -> dict[str, object]:
    return {
        "schema_version": "knowledge-analysis-batch-request/1.0",
        "preset_key": "knowledge-analysis",
        "general_knowledge_mode": "AUXILIARY_UNATTRIBUTED",
        "risk_policy_revision_id": "analysisriskrev_" + "1" * 32,
        "review_policy": "PREAUTHORIZED_APPROVE_VALIDATED",
        "ranges": [
            {
                "ordinal": 0,
                "source": {
                    "source_kind": "DOCUMENT_REVISION",
                    "source_class": "TEXTBOOK",
                    "document_revision_id": "edudocrev_" + "2" * 32,
                    "first_physical_page": 1,
                    "last_physical_page": 4,
                    "curriculum_unit_keys": ["1-(1)"],
                },
                "execution": {
                    "mode": "REUSE_ACCEPTED",
                    "accepted_analysis_run_id": "analysisrun_" + "3" * 32,
                },
            },
            {
                "ordinal": 1,
                "source": {
                    "source_kind": "DOCUMENT_REVISION",
                    "source_class": "TEXTBOOK",
                    "document_revision_id": "edudocrev_" + "2" * 32,
                    "first_physical_page": 5,
                    "last_physical_page": 8,
                    "curriculum_unit_keys": ["1-(1)"],
                },
                "execution": {
                    "mode": "EXECUTE",
                    "predecessor_analysis_run_id": "analysisrun_" + "4" * 32,
                },
            },
        ],
    }


def test_batch_schema_and_typed_contract_accept_ordered_pinned_ranges() -> None:
    value = _request()
    validate_contract("knowledge-analysis-batch-request", value)
    parsed = KnowledgeAnalysisBatchRequest.model_validate(value)

    assert len(parsed.ranges) == 2
    assert parsed.ranges[0].execution.mode == "REUSE_ACCEPTED"
    assert parsed.ranges[1].execution.mode == "EXECUTE"


def test_batch_schema_rejects_unknown_fields_before_typed_validation() -> None:
    value = _request()
    value["secret"] = "forbidden"

    with pytest.raises(JsonSchemaValidationError):
        validate_contract("knowledge-analysis-batch-request", value)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["ranges"][1].update(ordinal=2), "contiguous"),
        (
            lambda value: value["ranges"][1]["source"].update(first_physical_page=4),
            "overlap",
        ),
        (
            lambda value: value["ranges"][1]["execution"].update(
                predecessor_analysis_run_id="analysisrun_" + "3" * 32
            ),
            "unique",
        ),
    ],
)
def test_typed_batch_contract_rejects_ambiguous_range_identity(
    mutation: object, message: str
) -> None:
    value = _request()
    mutation(value)

    with pytest.raises(ValidationError, match=message):
        KnowledgeAnalysisBatchRequest.model_validate(value)


def test_batch_command_is_canonically_hashed_and_has_no_auth_material() -> None:
    request = KnowledgeAnalysisBatchRequest.model_validate(_request())
    canonical = {
        "request": request.model_dump(mode="json"),
        "requested_by": "operator_" + "5" * 32,
    }
    command = CreateKnowledgeAnalysisBatchCommand(
        request=request,
        requested_by=canonical["requested_by"],
        authorized_at=datetime(2026, 8, 26, tzinfo=UTC),
        idempotency_key="batch-create:" + "6" * 32,
        submission_sha256=content_sha256(canonical),
    )

    assert command.submission_sha256 == content_sha256(canonical)
    assert not ({"session_id", "token", "password"} & set(command.model_dump(mode="json")))

    replay_after_lost_response = CreateKnowledgeAnalysisBatchCommand(
        request=request,
        requested_by=canonical["requested_by"],
        authorized_at=datetime(2026, 8, 26, 1, tzinfo=UTC),
        idempotency_key=command.idempotency_key,
        submission_sha256=command.submission_sha256,
    )
    assert replay_after_lost_response.submission_sha256 == command.submission_sha256


def test_batch_schema_canonical_and_packaged_bytes_are_pinned() -> None:
    expected = "6050ea59b635cb50e718e76dd92967ddb88f55dede0e67fed3b55376ec65ce7e"
    for path in (
        "schemas/knowledge/knowledge-analysis-batch-request-v1.schema.json",
        "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge/"
        "knowledge-analysis-batch-request-v1.schema.json",
    ):
        with open(path, "rb") as schema_file:
            assert hashlib.sha256(schema_file.read()).hexdigest() == expected
