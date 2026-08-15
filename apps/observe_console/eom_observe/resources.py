"""Package resource locations used by the service at runtime."""

from __future__ import annotations

from importlib.resources import files
from importlib.resources.abc import Traversable


def static_resource(name: str | None = None) -> Traversable:
    root = files("eom_observe").joinpath("static")
    return root.joinpath(name) if name is not None else root


def worker_slot_resource() -> Traversable:
    return files("eom_observe").joinpath("resources", "worker-slots.example.yaml")
