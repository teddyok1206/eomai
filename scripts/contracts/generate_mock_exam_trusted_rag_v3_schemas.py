#!/usr/bin/env python3
"""Generate canonical and package-mirror schemas for mock-exam trusted-RAG V3."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eom_api_contracts import (
    MockExamProductionExecutionV3,
    MockExamReviewEligibilityObservationV3,
)
from eom_catalog_contracts import (
    MockExamItemReviewDecisionV3,
    MockExamItemReviewPublicationResultV3,
    MockExamProductionPlanV3,
    MockExamReviewEligibilityResultV3,
)
from jsonschema import Draft202012Validator
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]


def _close(value: object) -> None:
    if isinstance(value, dict):
        value.pop("default", None)
        properties = value.get("properties")
        if isinstance(properties, dict):
            value["additionalProperties"] = False
            value["required"] = list(properties)
        for child in value.values():
            _close(child)
    elif isinstance(value, list):
        for child in value:
            _close(child)


def _schema(model: type[BaseModel], schema_id: str) -> dict[str, Any]:
    value: dict[str, Any] = model.model_json_schema(mode="validation")
    value["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    value["$id"] = schema_id
    _close(value)
    return value


def _strict_api_sha256_patterns(value: object) -> None:
    """Mirror the V3 recursive validator without narrowing historical API models."""

    if isinstance(value, dict):
        if value.get("pattern") == r"^(?:sha256:)?[0-9a-f]{64}$":
            value["pattern"] = r"^sha256:[0-9a-f]{64}$"
        for child in value.values():
            _strict_api_sha256_patterns(child)
    elif isinstance(value, list):
        for child in value:
            _strict_api_sha256_patterns(child)


def _approval_conditions() -> list[dict[str, object]]:
    return [
        {
            "if": {
                "properties": {"approval_state": {"const": "PENDING"}},
                "required": ["approval_state"],
            },
            "then": {
                "properties": {
                    "approved_at": {"type": "null"},
                    "reviewer_operator_id": {"type": "null"},
                }
            },
        },
        {
            "if": {
                "properties": {"approval_state": {"const": "APPROVED"}},
                "required": ["approval_state"],
            },
            "then": {
                "properties": {
                    "approved_at": {"format": "date-time", "type": "string"},
                    "reviewer_operator_id": {
                        "pattern": "^operator_[0-9a-f]{32}$",
                        "type": "string",
                    },
                }
            },
        },
    ]


def _catalog_eligibility_conditions() -> list[dict[str, object]]:
    return [
        *_approval_conditions(),
        {
            "if": {
                "properties": {
                    "finding_counts": {
                        "properties": {"blocking": {"const": 0}},
                        "required": ["blocking"],
                    }
                },
                "required": ["finding_counts"],
            },
            "then": {
                "properties": {
                    "eligible": {"const": True},
                    "eligibility_reason": {"const": "ELIGIBLE"},
                }
            },
            "else": {
                "properties": {
                    "eligible": {"const": False},
                    "eligibility_reason": {"const": "REVIEW_BLOCKING_FINDINGS"},
                }
            },
        },
    ]


def _api_eligibility_conditions() -> list[dict[str, object]]:
    return [
        *_approval_conditions(),
        {
            "if": {
                "properties": {"eligibility": {"const": "ELIGIBLE"}},
                "required": ["eligibility"],
            },
            "then": {"properties": {"finding_blocking_count": {"const": 0}}},
            "else": {"properties": {"finding_blocking_count": {"minimum": 1}}},
        },
    ]


def _payload(schema: dict[str, Any]) -> bytes:
    Draft202012Validator.check_schema(schema)
    return (json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _write_mirrors(schema: dict[str, Any], *destinations: Path) -> None:
    payload = _payload(schema)
    for destination in destinations:
        destination.write_bytes(payload)


def _catalog_application_v13_schemas() -> tuple[dict[str, Any], dict[str, Any]]:
    """Derive the additive trusted-RAG envelope without rewriting V12."""

    source_root = ROOT / "schemas/catalog-application"
    request = json.loads(
        (source_root / "catalog-application-request-v12.schema.json").read_text(encoding="utf-8")
    )
    response = json.loads(
        (source_root / "catalog-application-response-v12.schema.json").read_text(encoding="utf-8")
    )
    request["$id"] = "eom://schemas/catalog-application/catalog-application-request-v13"
    request["title"] = "EOM Catalog Application Trusted RAG Review Request V13"
    response["$id"] = "eom://schemas/catalog-application/catalog-application-response-v13"
    response["title"] = "EOM Catalog Application Trusted RAG Review Response V13"
    encoded = json.dumps(response)
    encoded = encoded.replace(
        "mock-exam-item-review-publication-result-v2.schema.json",
        "mock-exam-item-review-publication-result-v3.schema.json",
    ).replace(
        "mock-exam-review-eligibility-result-v2.schema.json",
        "mock-exam-review-eligibility-result-v3.schema.json",
    )
    return request, json.loads(encoded)


def main() -> None:
    catalog_root = ROOT / "schemas/assessment-assembly"
    catalog_package_root = (
        ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/assessment-assembly"
    )
    api_root = ROOT / "schemas/api/v1"
    api_package_root = ROOT / "packages/api_contracts/eom_api_contracts/schemas"
    catalog_application_root = ROOT / "schemas/catalog-application"
    catalog_application_package_root = (
        ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/catalog-application"
    )

    catalog_schemas: tuple[tuple[str, dict[str, Any]], ...] = (
        (
            "mock-exam-production-plan-v3.schema.json",
            _schema(
                MockExamProductionPlanV3,
                "eom://schemas/assessment-assembly/mock-exam-production-plan/3.0",
            ),
        ),
        (
            "mock-exam-item-review-decision-v3.schema.json",
            _schema(
                MockExamItemReviewDecisionV3,
                "https://eom.local/schemas/assessment-assembly/"
                "mock-exam-item-review-decision-v3.schema.json",
            ),
        ),
        (
            "mock-exam-item-review-publication-result-v3.schema.json",
            _schema(
                MockExamItemReviewPublicationResultV3,
                "https://eom.local/schemas/assessment-assembly/"
                "mock-exam-item-review-publication-result-v3.schema.json",
            ),
        ),
        (
            "mock-exam-review-eligibility-result-v3.schema.json",
            _schema(
                MockExamReviewEligibilityResultV3,
                "https://eom.local/schemas/assessment-assembly/"
                "mock-exam-review-eligibility-result-v3.schema.json",
            ),
        ),
    )
    catalog_schemas[-1][1]["allOf"] = _catalog_eligibility_conditions()
    for file_name, schema in catalog_schemas:
        _write_mirrors(
            schema,
            catalog_root / file_name,
            catalog_package_root / file_name,
        )

    application_request, application_response = _catalog_application_v13_schemas()
    for file_name, schema in (
        ("catalog-application-request-v13.schema.json", application_request),
        ("catalog-application-response-v13.schema.json", application_response),
    ):
        _write_mirrors(
            schema,
            catalog_application_root / file_name,
            catalog_application_package_root / file_name,
        )

    api_schemas: tuple[tuple[str, dict[str, Any]], ...] = (
        (
            "mock-exam-production-execution-v3.schema.json",
            _schema(
                MockExamProductionExecutionV3,
                "https://eom.local/schemas/api/v1/mock-exam-production-execution-v3.schema.json",
            ),
        ),
        (
            "mock-exam-review-eligibility-v3.schema.json",
            _schema(
                MockExamReviewEligibilityObservationV3,
                "https://eom.local/schemas/api/v1/mock-exam-review-eligibility-v3.schema.json",
            ),
        ),
    )
    api_schemas[-1][1]["allOf"] = _api_eligibility_conditions()
    for file_name, schema in api_schemas:
        _strict_api_sha256_patterns(schema)
        _write_mirrors(
            schema,
            api_root / file_name,
            api_package_root / file_name,
        )


if __name__ == "__main__":
    main()
