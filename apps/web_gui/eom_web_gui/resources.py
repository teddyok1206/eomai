"""Installed resource resolution without source-checkout fallbacks."""

from importlib.resources import files
from importlib.resources.abc import Traversable


def static_resource(name: str | None = None) -> Traversable:
    root = files("eom_web_gui").joinpath("static")
    return root.joinpath(name) if name else root
