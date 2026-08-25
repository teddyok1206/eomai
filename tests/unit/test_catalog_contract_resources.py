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
PHASE8_SCHEMA_SHA256 = {
    "knowledge-graph-projection": (
        "sha256:b3a78a44dab9cb3a5525e5e1bfe5bc195044221867c92df2a98b08b358701102"
    ),
    "knowledge-graph-publication-result": (
        "sha256:c0d81175e94434888c84832e8edb64257370e998b7ebe41f5c382672638f657d"
    ),
    "knowledge-graph-publication": (
        "sha256:4594e9f479744d3ecf266d8e68367d5a207f82cc1001602864249bb9c471fd6d"
    ),
    "knowledge-graph-snapshot-manifest-v2": (
        "sha256:2fe24ad351ca7dcd10a9ba7909bf0fe0fe6fb2bf7715ca3dac02d1697cf60d09"
    ),
    "knowledge-graph-structure-manifest": (
        "sha256:818ecc197f3d5fdcd24b18ec73c4de5a76ca6db85fb5f01672e7067a3dde4cf9"
    ),
}

PHASE9_SCHEMA_SHA256 = {
    "catalog-application-request-v3": (
        "sha256:f94dcef9b685d830cfe4518ef1f7937e2e1cc14877cdea1c2b3a18064f049494"
    ),
    "catalog-application-response-v3": (
        "sha256:197bdc748aeeee9835e37ce49f6ca350f4c261af12f664e5d7b2ed5749dc40ea"
    ),
    "education-retrieval-access-policy": (
        "sha256:83e7fd1dc6cc78e74f3b35556a1eaf3039745e9d52fce04e46ad254490219afe"
    ),
    "education-retrieval-request-v2": (
        "sha256:d73d33141c3df357dc8508630931092d5b4d2f948cc1cd212766d5650caa9062"
    ),
    "evidence-bundle-manifest-v2": (
        "sha256:a908f3dffd665292e5b171d799e8e1e95faa0ed5a4df3cfdc426c8f4f4bfcdaa"
    ),
    "evidence-bundle-publication-result": (
        "sha256:2f511f842bea023a3c430e0e40d12e02861c1d39b9cfb7de2691ace32415c654"
    ),
}

PHASE11_SCHEMA_SHA256 = {
    "assessment-assembly-manifest": (
        "sha256:785d470fceff548e4d6d01a4b5c964bd1193f659d66c4844bce07fb7a3ee62c6"
    ),
    "legacy-usage-import-manifest": (
        "sha256:c25893647ebab2969b8f403f409a52c3fa78d169277d1cc00db483f2ee21c3a0"
    ),
    "legacy-usage-mapping-contract": (
        "sha256:9e697413fe059e3041b6e828d5ec280f27b9cf83466969625a45d1066d9f8548"
    ),
    "legacy-usage-row-proposal": (
        "sha256:60824ea6e061eeb56e447af4312e15296d9a88abee42a70ef45808af5049957f"
    ),
    "product-usage-graph-projection": (
        "sha256:ac5a3d66d83769a523e2dd8331c9562650a04de3e2368a3f9d91968fa8076820"
    ),
}


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
    assert len(entries) == 73
    assert len({name for name, _ in entries}) == len(entries)
    assert len({entry.resource_path for _, entry in entries}) == len(entries)
    assert {
        "educational-document-types",
        "educational-document-rights-attestation",
        "educational-document-registration-request",
        "educational-document-revision-manifest",
        "educational-document-registration-receipt",
        "educational-retrieval-requirement",
        "evidence-bundle-publication-result-v2",
        "catalog-application-request-v4",
        "catalog-application-response-v4",
        "catalog-application-request-v5",
        "catalog-application-response-v5",
        "catalog-application-response-v6",
        "knowledge-analysis-types-v3",
        "knowledge-analysis-request-v3",
        "knowledge-analysis-proposal-receipt-v2",
        "knowledge-analysis-result-v3",
        "knowledge-graph-projection-v2",
        "knowledge-graph-snapshot-manifest-v3",
        "evidence-bundle-manifest-v3",
        "evidence-bundle-publication-result-v3",
        "legacy-source-rights-review-v2",
        "legacy-source-selection-v2",
        "textbook-analysis-bundle-manifest",
        *PHASE11_SCHEMA_SHA256,
    }.issubset({name for name, _ in entries})
    for name, entry in entries:
        canonical = REPOSITORY_ROOT / entry.canonical_path
        resource = RESOURCE_ROOT.joinpath(entry.resource_path.removeprefix("resources/"))
        raw = resource.read_bytes()
        assert raw == canonical.read_bytes(), name
        assert "sha256:" + hashlib.sha256(raw).hexdigest() == entry.sha256, name
        assert isinstance(load_schema(name), dict)


def test_phase8_graph_contract_bytes_are_pinned_before_publication() -> None:
    inventory = dict(catalog_schema_inventory())
    assert {name: inventory[name].sha256 for name in PHASE8_SCHEMA_SHA256} == PHASE8_SCHEMA_SHA256


def test_phase9_retrieval_contract_bytes_are_pinned_before_publication() -> None:
    inventory = dict(catalog_schema_inventory())
    assert {name: inventory[name].sha256 for name in PHASE9_SCHEMA_SHA256} == PHASE9_SCHEMA_SHA256


def test_phase11_legacy_usage_contract_bytes_are_pinned_before_rollout() -> None:
    inventory = dict(catalog_schema_inventory())
    assert {name: inventory[name].sha256 for name in PHASE11_SCHEMA_SHA256} == PHASE11_SCHEMA_SHA256


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
