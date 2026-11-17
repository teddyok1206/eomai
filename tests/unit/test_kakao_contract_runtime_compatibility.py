"""Shared pure contracts coexist with independently pinned API and worker validators."""

from __future__ import annotations

import json
import tomllib
from importlib.resources import files
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]


def test_contract_dependency_accepts_both_existing_pins_without_unbounded_upgrade():
    metadata = tomllib.loads((ROOT / "packages/kakao_archive_contracts/pyproject.toml").read_text())
    dependencies = {
        requirement.name: requirement
        for requirement in map(Requirement, metadata["project"]["dependencies"])
    }
    validator = dependencies["jsonschema"].specifier
    assert "4.25.1" in validator
    assert "4.26.0" in validator
    assert "4.25.0" not in validator
    assert "4.27.0" not in validator
    assert "5.0.0" not in validator
    assert str(dependencies["pydantic"].specifier) == "==2.13.4"


def test_selected_catalog_environment_includes_the_declared_photo_decoder():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    optional = {
        requirement.name.lower(): requirement
        for requirement in map(Requirement, project["optional-dependencies"]["kakao-runtime"])
    }
    locked = {
        requirement.name.lower(): requirement
        for requirement in map(
            Requirement,
            (ROOT / "infra/conda/eom-api.requirements.lock").read_text().splitlines(),
        )
    }
    # The API/Catalog deployment selects this feature; --no-deps wheel installs
    # cannot discover an omitted optional dependency from a successful pip check.
    assert str(locked["pillow"].specifier) == str(optional["pillow"].specifier) == "==11.3.0"


@pytest.mark.parametrize(
    "name",
    sorted(
        member.name
        for member in files("eom_kakao_archive_contracts").joinpath("schemas").iterdir()
        if member.name.endswith(".schema.json")
    ),
)
def test_all_packaged_worker_schemas_are_valid_under_selected_runtime(name):
    schema = json.loads(files("eom_kakao_archive_contracts").joinpath("schemas", name).read_bytes())
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)
