#!/usr/bin/env python3
"""Acquire a pinned unmerged BGE safetensors candidate; never install or activate it."""

from __future__ import annotations

import argparse
import importlib.metadata
from pathlib import Path
from urllib.request import urlopen

from eom_catalog_contracts.item_inference_transfer import LocalEmbeddingModelSpec

from scripts.embedding._install_experiment_snapshot import (
    BGE_FILES,
    BGE_REPOSITORY,
    BGE_RUNTIME_VERSIONS,
    BGE_UPSTREAM_REVISION,
    reviewed_bge_model_spec,
)
from scripts.embedding.model_snapshot_acquisition import (
    acquire_reviewed_model,
    build_experiment_spec,
    require_owned_acquisition_store,
)


def experiment_spec() -> LocalEmbeddingModelSpec:
    actual = tuple((name, importlib.metadata.version(name)) for name, _ in BGE_RUNTIME_VERSIONS)
    if actual != BGE_RUNTIME_VERSIONS:
        raise ValueError("BGE experiment requires the independently reviewed exact CPU runtime")
    spec = build_experiment_spec(
        repository=BGE_REPOSITORY,
        revision=BGE_UPSTREAM_REVISION,
        files=BGE_FILES,
        dimension=1024,
        maximum_tokens=2048,
        pooling="CLS",
        prefix="",
        runtime_versions=actual,
    )
    if spec.model_dump(mode="json") != reviewed_bge_model_spec():
        raise ValueError("BGE experiment recipe differs from independent admission pins")
    return spec


def acquire(model_store: Path) -> LocalEmbeddingModelSpec:
    require_owned_acquisition_store(model_store)
    return acquire_reviewed_model(model_store, experiment_spec(), opener=urlopen)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-store", type=Path, required=True)
    args = parser.parse_args()
    acquire(args.model_store)


if __name__ == "__main__":
    main()
