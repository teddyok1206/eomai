"""JSON Schema 2020-12 validation backed by wheel-owned resources."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_FILES = {
    "model-manifest": "local-image-model-manifest-v1.schema.json",
    "generation-request": "local-image-generation-request-v1.schema.json",
    "generation-receipt": "local-image-generation-receipt-v1.schema.json",
}
SCHEMA_SHA256 = {
    "model-manifest": "sha256:f3c0d55b27e16785c14f04a52be0c84cfc23cb7fe10f9e40654891f907804fd3",
    "generation-request": "sha256:8107b01c9f088bbf0b9d3c63e58c29252a5125acf5f5fb157be74f02cdb3839e",
    "generation-receipt": "sha256:eccd1c2b335ee6709c3962e3649784f16db120cc68eed7faf2e491db6efc3982",
}


@lru_cache(maxsize=len(SCHEMA_FILES))
def load_schema(name: str) -> dict[str, Any]:
    try:
        filename = SCHEMA_FILES[name]
    except KeyError as exc:
        raise ValueError(f"unknown local image contract: {name}") from exc
    resource = files("eom_image_contracts").joinpath("schemas", filename)
    raw = resource.read_bytes()
    if "sha256:" + hashlib.sha256(raw).hexdigest() != SCHEMA_SHA256[name]:
        raise ValueError(f"local image contract hash mismatch: {name}")
    value: dict[str, Any] = json.loads(raw.decode("utf-8"))
    Draft202012Validator.check_schema(value)
    return value


def validate_contract(name: str, value: dict[str, Any]) -> None:
    Draft202012Validator(load_schema(name), format_checker=FormatChecker()).validate(value)
