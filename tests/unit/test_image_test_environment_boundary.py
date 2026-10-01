from __future__ import annotations

import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
IMAGE_TEST_MANIFEST = REPOSITORY_ROOT / "config/testing/image-unit-tests.txt"
IMAGE_IMPORT_ROOTS = (
    "PIL",
    "eom_image_candidate_runner",
    "eom_image_provider",
    "eom_image_trainer",
    "numpy",
)


def _manifest_paths() -> tuple[str, ...]:
    return tuple(
        line.strip()
        for line in IMAGE_TEST_MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _imports_image_runtime(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
    return any(
        module == root or module.startswith(f"{root}.")
        for module in imported
        for root in IMAGE_IMPORT_ROOTS
    )


def test_image_unit_test_manifest_is_sorted_unique_and_complete() -> None:
    manifest = _manifest_paths()
    assert manifest == tuple(sorted(set(manifest)))
    assert all((REPOSITORY_ROOT / path).is_file() for path in manifest)

    detected = tuple(
        str(path.relative_to(REPOSITORY_ROOT))
        for path in sorted((REPOSITORY_ROOT / "tests/unit").glob("test_*.py"))
        if _imports_image_runtime(path)
    )
    assert manifest == detected


def test_image_test_environment_is_python312_and_excludes_gpu_runtime() -> None:
    environment = (REPOSITORY_ROOT / "infra/conda/eom-image-test.environment.yml").read_text(
        encoding="utf-8"
    )
    requirements = (REPOSITORY_ROOT / "infra/conda/eom-image-test.requirements.lock").read_text(
        encoding="utf-8"
    )

    assert "python=3.12.13" in environment
    assert "-r eom-api.requirements.lock" in requirements
    assert "numpy==2.4.6" in requirements
    assert "pillow==12.3.0" in requirements
    assert "torch" not in requirements.casefold()
    assert "diffusers" not in requirements.casefold()
