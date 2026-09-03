#!/usr/bin/env python3
"""Generate protocol-first content-team item schemas from the frozen Pydantic contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eom_catalog_contracts import AssessmentItemContentV2
from eom_workflow.models import (
    ContentTeamAuthoringRoleResultV7,
    ContentTeamRegistrationRoleResultV7,
    ContentTeamReviewRoleResultV7,
)
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def _explicit_closed_contract(value: object) -> None:
    if isinstance(value, dict):
        value.pop("default", None)
        properties = value.get("properties")
        if isinstance(properties, dict):
            value["additionalProperties"] = False
            value["required"] = list(properties)
        for child in value.values():
            _explicit_closed_contract(child)
    elif isinstance(value, list):
        for child in value:
            _explicit_closed_contract(child)


def _schema(model: type[Any], schema_id: str) -> bytes:
    value = model.model_json_schema(mode="validation")
    value["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    value["$id"] = schema_id
    _explicit_closed_contract(value)
    Draft202012Validator.check_schema(value)
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def main() -> None:
    catalog_payload = _schema(
        AssessmentItemContentV2,
        "eom://schemas/item-registry/assessment-item-content-v2",
    )
    for path in (
        ROOT / "schemas/item-registry/assessment-item-content-v2.schema.json",
        ROOT
        / "packages/catalog_contracts/eom_catalog_contracts/resources/item-registry"
        / "assessment-item-content-v2.schema.json",
    ):
        path.write_bytes(catalog_payload)

    roles = {
        "authoring": ContentTeamAuthoringRoleResultV7,
        "review": ContentTeamReviewRoleResultV7,
        "registration": ContentTeamRegistrationRoleResultV7,
    }
    for role, model in roles.items():
        file_name = f"{role}-result-v7.schema.json"
        payload = _schema(
            model,
            f"https://eom.local/schemas/workflow/roles/{file_name}",
        )
        for root in (
            ROOT / "schemas/workflow/roles",
            ROOT / "packages/workflow/eom_workflow/resources/roles",
        ):
            (root / file_name).write_bytes(payload)


if __name__ == "__main__":
    main()
