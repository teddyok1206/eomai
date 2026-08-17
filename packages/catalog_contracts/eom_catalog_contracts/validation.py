"""JSON Schema 2020-12 validation for catalog contracts."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "schemas"
SCHEMA_FILES = {
    "intake-manifest": SCHEMA_ROOT / "content-intake" / "intake-manifest-v1.schema.json",
    "mapping-proposal": SCHEMA_ROOT / "content-intake" / "mapping-proposal-v1.schema.json",
    "uncertainties": SCHEMA_ROOT / "content-intake" / "uncertainties-v1.schema.json",
    "human-decision": SCHEMA_ROOT / "content-intake" / "human-decision-v1.schema.json",
    "content-pack": SCHEMA_ROOT / "content-pack" / "content-pack-v1.schema.json",
    "content-pack-profile": SCHEMA_ROOT / "content-pack" / "profile-v1.schema.json",
    "prompt-envelope": SCHEMA_ROOT / "content-pack" / "prompt-envelope-v1.schema.json",
    "item-revision-manifest": SCHEMA_ROOT
    / "item-registry"
    / "item-revision-manifest-v1.schema.json",
}


@lru_cache(maxsize=32)
def load_schema(name: str) -> dict[str, Any]:
    try:
        path = SCHEMA_FILES[name]
    except KeyError as exc:
        raise ValueError(f"unknown catalog contract: {name}") from exc
    value: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(value)
    return value


def validate_contract(name: str, value: dict[str, Any]) -> None:
    Draft202012Validator(load_schema(name), format_checker=FormatChecker()).validate(value)
