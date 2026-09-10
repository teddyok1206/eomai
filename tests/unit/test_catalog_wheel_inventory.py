from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from shutil import copy2, copytree
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]


def test_platform_wheel_contains_and_imports_evidence_receipt_runtime(tmp_path: Path) -> None:
    """Prove setuptools discovery reaches the source-isolated Catalog runtime."""

    source = tmp_path / "source"
    source.mkdir()
    copy2(ROOT / "pyproject.toml", source / "pyproject.toml")
    for package_root in ("packages", "services", "apps", "tools"):
        copytree(
            ROOT / package_root,
            source / package_root,
            ignore=lambda _directory, names: {name for name in names if name == "__pycache__"},
        )
    build = subprocess.run(
        (
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(tmp_path),
            str(source),
        ),
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    wheels = tuple(tmp_path.glob("eom_platform-*.whl"))
    assert len(wheels) == 1
    wheel = wheels[0]
    with ZipFile(wheel) as archive:
        assert "eom_catalog_service/evidence_usage_receipts.py" in archive.namelist()

    imported = subprocess.run(
        (
            sys.executable,
            "-I",
            "-c",
            (
                "import sys; "
                "sys.path.insert(0, sys.argv[1]); "
                "from eom_catalog_service.evidence_usage_receipts import "
                "OrchestratorEvidenceUsageReceiptResolver as Resolver; "
                "from eom_catalog_service.workflow_catalog import WorkflowCatalogService; "
                "assert Resolver.__module__ == "
                "'eom_catalog_service.evidence_usage_receipts'; "
                "assert WorkflowCatalogService.__module__ == "
                "'eom_catalog_service.workflow_catalog'; "
                "print(Resolver.__module__)"
            ),
            str(wheel),
        ),
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert imported.returncode == 0, imported.stderr
    assert imported.stdout.strip() == "eom_catalog_service.evidence_usage_receipts"
