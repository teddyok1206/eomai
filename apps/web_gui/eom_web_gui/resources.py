"""Installed resource resolution without source-checkout fallbacks."""

import json
from importlib.resources import files
from importlib.resources.abc import Traversable


def static_resource(name: str | None = None) -> Traversable:
    root = files("eom_web_gui").joinpath("static")
    return root.joinpath(name) if name else root


def installed_web_source_commit() -> str | None:
    """Return a validated packaged commit, or no diagnostic in source/development installs."""

    try:
        value = json.loads(files("eom_web_gui").joinpath("build-info.json").read_text("ascii"))
    except (FileNotFoundError, UnicodeError, json.JSONDecodeError):
        return None
    commit = value.get("source_commit") if isinstance(value, dict) else None
    if (
        isinstance(commit, str)
        and len(commit) == 40
        and all(character in "0123456789abcdef" for character in commit)
    ):
        return commit
    return None
