"""HWPX protocol bundle identity for platform job history."""

from __future__ import annotations

from importlib.resources import files

from eom_hwpx_contracts.validation import SCHEMA_FILES
from eom_identifiers import content_sha256

HWPX_PROTOCOL_VERSION = "hwpx-poc/1.0"
HWPX_KORDOC_PROTOCOL_VERSION = "hwpx-kordoc/1.0"
HWPX_CONTENT_TEAM_PROTOCOL_VERSION = "hwpx-content-team/1.0"
HWPX_CONTENT_TEAM_PROTOCOL_VERSION_V2 = "hwpx-content-team/2.0"
HWPX_TEMPLATE_SCHEMA_NAMES = ("item-document", "build-result")
HWPX_KORDOC_SCHEMA_NAMES = ("kordoc-render-request", "kordoc-build-result")
HWPX_CONTENT_TEAM_SCHEMA_NAMES = (
    "content-team-render-request",
    "content-team-build-result",
)
HWPX_CONTENT_TEAM_SCHEMA_NAMES_V2 = (
    "content-team-render-request-v2",
    "content-team-build-result-v2",
)


def hwpx_schema_bundle_hash() -> str:
    root = files("eom_hwpx_contracts").joinpath("schemas")
    return content_sha256(
        {
            name: root.joinpath(SCHEMA_FILES[name]).read_text(encoding="utf-8")
            for name in HWPX_TEMPLATE_SCHEMA_NAMES
        }
    )


def kordoc_schema_bundle_hash() -> str:
    root = files("eom_hwpx_contracts").joinpath("schemas")
    return content_sha256(
        {
            name: root.joinpath(SCHEMA_FILES[name]).read_text(encoding="utf-8")
            for name in HWPX_KORDOC_SCHEMA_NAMES
        }
    )


def content_team_schema_bundle_hash() -> str:
    root = files("eom_hwpx_contracts").joinpath("schemas")
    return content_sha256(
        {
            name: root.joinpath(SCHEMA_FILES[name]).read_text(encoding="utf-8")
            for name in HWPX_CONTENT_TEAM_SCHEMA_NAMES
        }
    )


def content_team_schema_bundle_hash_v2() -> str:
    root = files("eom_hwpx_contracts").joinpath("schemas")
    return content_sha256(
        {
            name: root.joinpath(SCHEMA_FILES[name]).read_text(encoding="utf-8")
            for name in HWPX_CONTENT_TEAM_SCHEMA_NAMES_V2
        }
    )
