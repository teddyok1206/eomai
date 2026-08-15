"""Load immutable release metadata embedded in the installed wheel."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files


@dataclass(frozen=True)
class BuildInfo:
    source_commit: str
    package_version: str
    build_timestamp_utc: datetime

    @property
    def is_release(self) -> bool:
        return len(self.source_commit) == 40 and all(
            character in "0123456789abcdef" for character in self.source_commit
        )


@lru_cache(maxsize=1)
def get_build_info() -> BuildInfo:
    resource = files("eom_observe").joinpath("build-info.json")
    try:
        value = json.loads(resource.read_text(encoding="utf-8"))
        source_commit = str(value["source_commit"])
        package_version = str(value["package_version"])
        timestamp = datetime.fromisoformat(str(value["build_timestamp_utc"]).replace("Z", "+00:00"))
        if timestamp.tzinfo is None or len(source_commit) != 40:
            raise ValueError("invalid build metadata")
        return BuildInfo(source_commit, package_version, timestamp.astimezone(UTC))
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        try:
            package_version = version("eom-observe")
        except PackageNotFoundError:
            package_version = "0.0.0+source"
        return BuildInfo("unbuilt", package_version, datetime(1970, 1, 1, tzinfo=UTC))
