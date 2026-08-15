"""HWPX protocol bundle identity for platform job history."""

from __future__ import annotations

from importlib.resources import files

from eom_hwpx_contracts.validation import SCHEMA_FILES
from eom_identifiers import content_sha256

HWPX_PROTOCOL_VERSION = "hwpx-poc/1.0"


def hwpx_schema_bundle_hash() -> str:
    root = files("eom_hwpx_contracts").joinpath("schemas")
    return content_sha256(
        {
            name: root.joinpath(file_name).read_text(encoding="utf-8")
            for name, file_name in sorted(SCHEMA_FILES.items())
        }
    )
