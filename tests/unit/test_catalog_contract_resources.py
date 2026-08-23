from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from importlib.resources import files
from pathlib import Path

import pytest
from eom_catalog_contracts import (
    CatalogSchemaError,
    catalog_schema_inventory,
    load_schema,
    validate_contract,
)
from jsonschema import ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RESOURCE_ROOT = files("eom_catalog_contracts").joinpath("resources")


def _prompt_envelope() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "pack_release_id": "packrel_" + "0" * 32,
        "pack_release_sha256": "sha256:" + "0" * 64,
        "profile_key": "authoring-default",
        "profile_version": "0.1.0",
        "profile_sha256": "sha256:" + "0" * 64,
        "template_path": "prompt-templates/authoring.md",
        "template_sha256": "sha256:" + "0" * 64,
        "render_context_sha256": "sha256:" + "0" * 64,
        "rendered_prompt_sha256": "sha256:" + "0" * 64,
        "workflow_id": "workflow_" + "0" * 32,
        "step_run_id": "steprun_" + "0" * 32,
        "source_intake_batch_ids": ["intake_" + "0" * 32],
    }


def test_catalog_schema_resources_match_canonical_sources() -> None:
    entries = catalog_schema_inventory()
    assert len(entries) == 18
    assert len({name for name, _ in entries}) == len(entries)
    assert len({entry.resource_path for _, entry in entries}) == len(entries)
    for name, entry in entries:
        canonical = REPOSITORY_ROOT / entry.canonical_path
        resource = RESOURCE_ROOT.joinpath(entry.resource_path.removeprefix("resources/"))
        raw = resource.read_bytes()
        assert raw == canonical.read_bytes(), name
        assert "sha256:" + hashlib.sha256(raw).hexdigest() == entry.sha256, name
        assert isinstance(load_schema(name), dict)


def test_prompt_envelope_validates_and_invalid_fixture_is_rejected() -> None:
    value = _prompt_envelope()
    validate_contract("prompt-envelope", value)
    with pytest.raises(ValidationError):
        validate_contract("prompt-envelope", {**value, "workflow_id": "invalid"})


def test_catalog_loader_has_no_repository_relative_schema_fallback() -> None:
    source_path = REPOSITORY_ROOT / "packages/catalog_contracts/eom_catalog_contracts/validation.py"
    source = source_path.read_text(encoding="utf-8")
    assert "Path(__file__)" not in source
    assert "parents[" not in source
    assert "/schemas" not in source


def test_unknown_catalog_schema_is_typed_error() -> None:
    with pytest.raises(CatalogSchemaError, match="unknown catalog contract schema"):
        load_schema("not-a-real-contract")


@pytest.fixture(scope="module")
def platform_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    wheel_dir = tmp_path_factory.mktemp("catalog-contract-wheel")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
            str(REPOSITORY_ROOT),
        ],
        cwd=wheel_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = tuple(wheel_dir.glob("eom_platform-*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def test_built_wheel_contains_catalog_schemas_and_record(platform_wheel: Path) -> None:
    prefix = "eom_catalog_contracts/resources/"
    expected = {
        entry.resource_path.removeprefix("resources/") for _, entry in catalog_schema_inventory()
    }
    with zipfile.ZipFile(platform_wheel) as archive:
        names = set(archive.namelist())
        packaged = {
            name.removeprefix(prefix)
            for name in names
            if name.startswith(prefix) and name.endswith(".schema.json")
        }
        assert packaged == expected
        record_name = next(name for name in names if name.endswith(".dist-info/RECORD"))
        record = archive.read(record_name).decode("utf-8")
        for _, entry in catalog_schema_inventory():
            member = prefix + entry.resource_path.removeprefix("resources/")
            assert member in record
            assert archive.read(member) == (REPOSITORY_ROOT / entry.canonical_path).read_bytes()


def test_installed_wheel_loads_catalog_schemas_without_source_checkout(
    platform_wheel: Path, tmp_path: Path
) -> None:
    installed = tmp_path / "site-packages"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-index",
            "--no-compile",
            "--target",
            str(installed),
            str(platform_wheel),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    script = """
import importlib.util
import sys
from pathlib import Path

installed, repository = map(Path, sys.argv[1:])
sys.path.insert(0, str(installed))
from eom_catalog_contracts import catalog_schema_inventory, load_schema, validate_contract

spec = importlib.util.find_spec("eom_catalog_contracts")
assert spec is not None and spec.origin is not None
assert Path(spec.origin).resolve().is_relative_to(installed.resolve())
assert str(repository.resolve()) not in str(Path(spec.origin).resolve())
for name, _ in catalog_schema_inventory():
    load_schema(name)
value = {
    "schema_version": "1.0",
    "pack_release_id": "packrel_" + "0" * 32,
    "pack_release_sha256": "sha256:" + "0" * 64,
    "profile_key": "authoring-default",
    "profile_version": "0.1.0",
    "profile_sha256": "sha256:" + "0" * 64,
    "template_path": "prompt-templates/authoring.md",
    "template_sha256": "sha256:" + "0" * 64,
    "render_context_sha256": "sha256:" + "0" * 64,
    "rendered_prompt_sha256": "sha256:" + "0" * 64,
    "workflow_id": "workflow_" + "0" * 32,
    "step_run_id": "steprun_" + "0" * 32,
    "source_intake_batch_ids": ["intake_" + "0" * 32],
}
validate_contract("prompt-envelope", value)
print("installed_catalog_contract_resources=PASS")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(installed), str(REPOSITORY_ROOT)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "installed_catalog_contract_resources=PASS"
