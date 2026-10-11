#!/usr/bin/env python3
"""Acquire one byte-pinned official CPU experiment snapshot; never activate production."""

from __future__ import annotations

import argparse
import importlib.metadata
from pathlib import Path
from typing import Final
from urllib.request import urlopen

from eom_catalog_contracts.item_inference_transfer import LocalEmbeddingModelSpec

from scripts.embedding.model_snapshot_acquisition import (
    acquire_reviewed_model,
    build_experiment_spec,
    require_owned_acquisition_store,
)

REPOSITORY: Final = "intfloat/multilingual-e5-small"
UPSTREAM_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
# Primary upstream metadata, reviewed 2026-10-10. Each acquired byte is reverified.
FILES = (
    (
        "1_Pooling/config.json",
        200,
        "987f7a67a38fa564c849bb5d277c52ab9088a84368fc0be31a354125aebb12a0",
    ),
    ("config.json", 655, "69137736cab8b8903a07fe8afaafdda25aac55415a12a55d1bffa9f581abf959"),
    (
        "model.safetensors",
        470641600,
        "1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477",
    ),
    (
        "sentencepiece.bpe.model",
        5069051,
        "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865",
    ),
    (
        "special_tokens_map.json",
        167,
        "d05497f1da52c5e09554c0cd874037a083e1dc1b9cfd48034d1c717f1afc07a7",
    ),
    (
        "tokenizer.json",
        17082730,
        "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
    ),
    (
        "tokenizer_config.json",
        443,
        "a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b",
    ),
)


def experiment_spec() -> LocalEmbeddingModelSpec:
    return build_experiment_spec(
        repository=REPOSITORY,
        revision=UPSTREAM_REVISION,
        files=FILES,
        dimension=384,
        maximum_tokens=512,
        pooling="MEAN",
        prefix="query: ",
        runtime_versions=tuple(
            (name, importlib.metadata.version(name))
            for name in ("safetensors", "tokenizers", "torch", "transformers")
        ),
    )


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
