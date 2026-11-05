"""A subproject build cache must never become a platform Python package."""

from __future__ import annotations

import tomllib
from pathlib import Path

from setuptools import find_namespace_packages

ROOT = Path(__file__).resolve().parents[2]


def test_package_discovery_excludes_old_subproject_build_copies(tmp_path: Path) -> None:
    settings = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]
    for name in ("eom_example", "build/lib/eom_example", "eomctl"):
        directory = tmp_path / name
        directory.mkdir(parents=True)
        (directory / "__init__.py").write_text("", encoding="utf-8")
    found = find_namespace_packages(str(tmp_path), exclude=settings["packages"]["find"]["exclude"])
    assert "eom_example" in found
    assert "eomctl" in found
    assert not any(name == "build" or name.startswith("build.") for name in found)


def test_material_learning_resources_are_explicitly_packaged() -> None:
    settings = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]
    assert "resources/material-learning/*.json" in settings["package-data"]["eom_catalog_contracts"]
