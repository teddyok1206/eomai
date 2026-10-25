from __future__ import annotations

import hashlib
import subprocess
import sys
import tomllib
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
        # The same installed wheel owns both metadata families. Numerical input/
        # result1 stays separate; omitting a successor resource must fail here,
        # before a root-owned service can select that release.
        required_members = {
            "eom_catalog_service/evidence_usage_receipts.py",
            "eom_catalog_service/ordinary_item_graph_publication_service.py",
            "eom_catalog_service/registered_review_embedding_capture.py",
            "eom_catalog_contracts/resources/knowledge/mixed-embedding-index-v2.schema.json",
            "eom_catalog_contracts/resources/knowledge/system-rag-similarity-reader-configuration-v2.schema.json",
            "eom_workflow/resources/local-embedding-workflow-request-v2.schema.json",
            "eom_workflow/resources/embedding-encoding-ownership-v2.schema.json",
            "eom_workflow/resources/native-embedding-coordinator-v2.schema.json",
            "eom_workflow/resources/local-indexing-owner-configuration-v4.schema.json",
            "eom_workflow/resources/reference-query-owner-configuration-v2.schema.json",
            "eom_workflow_runner/reference_query_batch_driver.py",
            "eom_workflow_runner/reference_query_batch_executor.py",
            "eom_workflow_runner/reference_query_batch_group.py",
            "eom_workflow_runner/reference_query_batch_material.py",
        }
        assert required_members <= set(archive.namelist())
        bootstrap_member = "eom_catalog_service/embedding_owner_bootstrap.py"
        assert not any(".data/" in name for name in archive.namelist())
        assert (
            archive.read(bootstrap_member)
            == (
                ROOT / "services/catalog_service/eom_catalog_service/embedding_owner_bootstrap.py"
            ).read_bytes()
        )
        # Byte parity through the numerical installer's existing source mapping;
        # no root/prefix admission, new instruction execution or .data exception.
        from eom_catalog_service import embedding_runtime_prefix_closure as closure

        project_bytes = (source / "pyproject.toml").read_bytes()
        project = tomllib.loads(project_bytes.decode())
        pins = {}
        for base in project["tool"]["setuptools"]["packages"]["find"]["where"]:
            for path in (source / base).rglob("*"):
                if path.is_file():
                    raw = path.read_bytes()
                    pins[path.relative_to(source).as_posix()] = (
                        "sha256:" + hashlib.sha256(raw).hexdigest(),
                        len(raw),
                    )
        payload = closure._source_payload(
            closure._Source(pins, {"pyproject.toml": project_bytes}), "eom-platform"
        )
        wheel_payload = {}
        for name in archive.namelist():
            if not name.endswith("/") and not name.startswith("eom_platform-0.1.0.dist-info/"):
                raw = archive.read(name)
                wheel_payload[name] = ("sha256:" + hashlib.sha256(raw).hexdigest(), len(raw))
        assert payload == wheel_payload

    installed = tmp_path / "owner-install"
    staged = subprocess.run(
        (
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-index",
            "--no-compile",
            "--no-cache-dir",
            "--target",
            str(installed),
            str(wheel),
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    assert staged.returncode == 0, staged.stderr
    assert (installed / "eom_catalog_service/embedding_owner_bootstrap.py").read_bytes() == (
        ROOT / "services/catalog_service/eom_catalog_service/embedding_owner_bootstrap.py"
    ).read_bytes()

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

    # Each order starts a fresh interpreter. Cached source imports cannot hide a
    # Catalog/runner composition cycle, nor can runtime depend on checkout paths.
    import_orders = (
        (
            "eom_workflow_runner.document_embedding_cpu_execution",
            "eom_workflow_runner.document_embedding_batch_material",
            "eom_workflow_runner.document_embedding_execution",
            "eom_workflow_runner.local_indexing_service_runtime",
        ),
        (
            "eom_workflow_runner.reference_query_batch_driver",
            "eom_catalog_service.ordinary_item_graph_publication_service",
            "eom_workflow_runner.local_embedding_native_executor",
            "eom_catalog_service.similarity_read_runtime",
        ),
        (
            "eom_workflow_runner.reference_query_owner_runtime",
            "eom_catalog_service.embedding_registry_catalog_adapter",
            "eom_orchestrator.embedding_encoding_reservations",
        ),
    )
    for modules in import_orders:
        checked = subprocess.run(
            (
                sys.executable,
                "-I",
                "-B",
                "-c",
                (
                    "import importlib, sys; "
                    "sys.path.insert(0, sys.argv[1]); "
                    f"names = {modules!r}; "
                    "loaded = [importlib.import_module(name) for name in names]; "
                    "assert all(module.__file__.startswith(sys.argv[1] + '/') "
                    "for module in loaded)"
                ),
                str(wheel),
            ),
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
        )
        assert checked.returncode == 0, checked.stderr
