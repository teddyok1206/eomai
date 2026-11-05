#!/usr/bin/env python3
"""Catalog reauthorization derives the actor from a persisted material Workflow."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from scripts.contracts.generate_material_learning_schemas import (
    BASE,
    ROOT,
    SHA,
    enum,
    identifier,
    nullable,
    record,
    version,
)


def schemas() -> dict[str, dict[str, Any]]:
    operation = version("AUTHORIZE_MATERIAL_LEARNING_INPUT")
    values = {
        "authorization-request": record(
            schema_version=version("material-learning-authorization-request/1.0"),
            operation=operation,
            workflow_id=identifier("workflow"),
            step_run_id=identifier("steprun"),
            plan_id=identifier("execplan"),
            plan_sha256=SHA,
            input_sha256=SHA,
        ),
        "authorization-reply": record(
            schema_version=version("material-learning-authorization-reply/1.0"),
            operation=operation,
            status=enum("SUCCESS", "FAILED"),
            request_sha256=SHA,
            input_sha256=nullable(SHA),
            error_code=nullable(
                enum(
                    "MATERIAL_LEARNING_AUTHORIZATION_FAILED",
                    "MATERIAL_LEARNING_AUTHORIZATION_UNAVAILABLE",
                )
            ),
        ),
    }
    return {
        name: {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": BASE + name + "/1.0",
            "title": f"EOM material learning {name} 1.0",
            **value,
        }
        for name, value in values.items()
    }


def main() -> None:
    for name, document in schemas().items():
        payload = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode()
        filename = f"material-learning-{name}-v1.schema.json"
        for directory in (
            ROOT / "schemas/material-learning",
            ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/material-learning",
        ):
            (directory / filename).write_bytes(payload)
        print(f"material-learning-{name}-v1 sha256:{hashlib.sha256(payload).hexdigest()}")


if __name__ == "__main__":
    main()
