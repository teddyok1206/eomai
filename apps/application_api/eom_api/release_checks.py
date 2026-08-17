"""Checks for immutable resources embedded in the installed API release."""

from __future__ import annotations

import hashlib
from importlib.resources import files


def packaged_openapi_valid() -> bool:
    contract = files("eom_api").joinpath("openapi/eom-api-v1.openapi.json")
    checksum = files("eom_api").joinpath("openapi/eom-api-v1.sha256")
    if not contract.is_file() or not checksum.is_file():
        return False
    expected = checksum.read_text(encoding="ascii").strip().split()[0]
    return hashlib.sha256(contract.read_bytes()).hexdigest() == expected
