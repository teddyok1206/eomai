"""Release metadata embedded in the non-editable Application API wheel."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import cast


@dataclass(frozen=True)
class BuildInfo:
    package_version: str
    source_commit: str
    build_timestamp_utc: str


def get_build_info() -> BuildInfo:
    resource = files("eom_api").joinpath("build-info.json")
    if not resource.is_file():
        return BuildInfo("0.1.0", "unknown", "unknown")
    raw = cast(dict[str, str], json.loads(resource.read_text(encoding="utf-8")))
    return BuildInfo(
        package_version=raw["package_version"],
        source_commit=raw["source_commit"],
        build_timestamp_utc=raw["build_timestamp_utc"],
    )
