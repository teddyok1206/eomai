"""Dedicated worker-source compatibility; no model, installation or device admission."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

from tests.unit.test_embedding_numerical_family_source import PINNED_CPU_IMPLEMENTATIONS

ROOT = Path(__file__).resolve().parents[2]


def test_v12_worker_imports_preserve_actual_numerical_pins_without_ml() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    roots = (*project["tool"]["setuptools"]["packages"]["find"]["where"], "packages/gpu_lease")
    code = f"""
import json, os, sys
sys.path[:0] = {[str(ROOT / root) for root in roots]!r}
import eom_catalog_service.embedding_benchmark_budget1200_cpu
import eom_catalog_service.embedding_benchmark_budget1200_cuda
from eom_catalog_service.embedding_offline_backend import observed_embedding_implementation_pins
ml = {{'torch', 'transformers', 'numpy', 'tokenizers', 'safetensors'}}
assert not ml.intersection(sys.modules)
print(json.dumps([pin.model_dump(mode='json') for pin in
    observed_embedding_implementation_pins(expected_owner_uid=os.geteuid())]))
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code], capture_output=True, check=False, timeout=30
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [
        {"component": component, "recipe_version": recipe, "sha256": digest}
        for component, recipe, _path, digest in PINNED_CPU_IMPLEMENTATIONS
    ]
