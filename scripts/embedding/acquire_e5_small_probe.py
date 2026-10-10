#!/usr/bin/env python3
"""Acquire one byte-pinned official CPU experiment snapshot; never activate production."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import os
from pathlib import Path
from urllib.request import Request, urlopen

from eom_catalog_contracts import validate_contract
from eom_catalog_contracts.item_inference_transfer import LocalEmbeddingModelSpec
from eom_identifiers import canonical_json_bytes, content_sha256

REPOSITORY = "intfloat/multilingual-e5-small"
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
    recipe = {
        "schema_version": "item-local-embedding-model-spec/1.0",
        "provider_family": "transformers-local-dense/1.0",
        "upstream_repo": REPOSITORY,
        "upstream_revision": UPSTREAM_REVISION,
        "license_id": "MIT",
        "dimension": 384,
        "maximum_tokens": 512,
        "pooling": "MEAN",
        "normalization": "L2",
        "dtype": "float32",
        "query_prefix": "query: ",
        "document_prefix": "query: ",
        "truncation": "REJECT_OVERFLOW",
        "files": [
            {"member_path": name, "size_bytes": size, "sha256": "sha256:" + digest}
            for name, size, digest in FILES
        ],
        "runtime_versions": [
            {"name": name, "version": importlib.metadata.version(name)}
            for name in ("safetensors", "tokenizers", "torch", "transformers")
        ],
    }
    body = {
        **recipe,
        "model_id": "embeddingmodel_" + content_sha256(REPOSITORY)[7:39],
        "model_revision_id": "embeddingmodelrev_" + content_sha256(recipe)[7:39],
    }
    value = {**body, "manifest_sha256": content_sha256(body)}
    validate_contract("item-inference-transfer", value)
    return LocalEmbeddingModelSpec.model_validate(value)


def acquire(model_store: Path) -> LocalEmbeddingModelSpec:
    if (
        not model_store.is_absolute()
        or model_store.is_symlink()
        or model_store.resolve() != model_store
    ):
        raise ValueError("explicit absolute nonsymlink experiment model store required")
    metadata = model_store.stat()
    if not model_store.is_dir() or metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
        raise ValueError("experiment model store must be an owned nonwritable-by-others directory")
    spec = experiment_spec()
    model_directory = model_store / spec.model_id
    model_directory.mkdir(mode=0o700, exist_ok=False)
    snapshot = model_directory / spec.model_revision_id
    snapshot.mkdir(mode=0o700, exist_ok=False)
    for name, expected_size, expected_hash in FILES:
        target = snapshot / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        request = Request(
            f"https://huggingface.co/{REPOSITORY}/resolve/{UPSTREAM_REVISION}/{name}",
            headers={"User-Agent": "EOM-offline-embedding-acquisition/1.0"},
        )
        digest = hashlib.sha256()
        size = 0
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output, urlopen(request, timeout=60) as response:
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > expected_size:
                    raise ValueError("model download exceeds immutable file size")
                digest.update(block)
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if size != expected_size or digest.hexdigest() != expected_hash:
            raise ValueError("model download differs from pinned upstream file identity")
        target.chmod(0o400)
        print(f"EMBEDDING_FILE_VERIFIED={name}", flush=True)
    manifest = snapshot / "manifest.json"
    descriptor = os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    with os.fdopen(descriptor, "wb") as output:
        output.write(canonical_json_bytes(spec.model_dump(mode="json")))
        output.flush()
        os.fsync(output.fileno())
    print(f"EMBEDDING_EXPERIMENT_MODEL_STORE={model_store}", flush=True)
    print(f"EMBEDDING_EXPERIMENT_MANIFEST_SHA256={spec.manifest_sha256}", flush=True)
    print("PRODUCTION_ACTIVATION=NOT_PERFORMED", flush=True)
    return spec


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-store", type=Path, required=True)
    args = parser.parse_args()
    acquire(args.model_store)


if __name__ == "__main__":
    main()
