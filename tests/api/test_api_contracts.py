from __future__ import annotations

import json
from pathlib import Path

import pytest
from eom_api_contracts.auth import LoginRequest
from eom_api_contracts.operators import CreateOperatorRequest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas" / "api" / "v1"


def test_api_json_schemas_are_draft_2020_12() -> None:
    schemas = sorted(SCHEMA_ROOT.glob("*.schema.json"))
    assert schemas
    for path in schemas:
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(document)


def test_request_contracts_forbid_unknown_fields_and_redact_secrets() -> None:
    login = LoginRequest(
        username="admin",
        password="TEST_ONLY valid password 42",
        client_name="contract-test",
    )
    assert "TEST_ONLY valid password 42" not in repr(login)
    with pytest.raises(ValidationError):
        LoginRequest.model_validate(
            {
                "username": "admin",
                "password": "TEST_ONLY valid password 42",
                "client_name": "contract-test",
                "unknown": True,
            }
        )


def test_operator_contract_never_serializes_temporary_password() -> None:
    request = CreateOperatorRequest(
        username="review01",
        display_name="검토자",
        temporary_password="TEST_ONLY temporary password 42",
        initial_roles=("REVIEWER",),
    )
    assert "TEST_ONLY temporary password 42" not in request.model_dump_json()
