"""Shared byte-pinned developer acquisition for the two reviewed offline recipes.

No model is loaded, no production path is written and no installation is implied.
Existing JSON Schema/Pydantic models validate recipes before network access.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO, Literal
from urllib.request import Request

from eom_catalog_contracts import validate_contract
from eom_catalog_contracts.item_inference_transfer import LocalEmbeddingModelSpec
from eom_identifiers import canonical_json_bytes, content_sha256


def build_experiment_spec(
    *,
    repository: Literal["intfloat/multilingual-e5-small", "BAAI/bge-m3"],
    revision: str,
    files: tuple[tuple[str, int, str], ...],
    dimension: Literal[384, 1024],
    maximum_tokens: int,
    pooling: Literal["MEAN", "CLS"],
    prefix: Literal["", "query: "],
    runtime_versions: tuple[tuple[str, str], ...],
) -> LocalEmbeddingModelSpec:
    recipe = {
        "schema_version": "item-local-embedding-model-spec/1.0",
        "provider_family": "transformers-local-dense/1.0",
        "upstream_repo": repository,
        "upstream_revision": revision,
        "license_id": "MIT",
        "dimension": dimension,
        "maximum_tokens": maximum_tokens,
        "pooling": pooling,
        "normalization": "L2",
        "dtype": "float32",
        "query_prefix": prefix,
        "document_prefix": prefix,
        "truncation": "REJECT_OVERFLOW",
        "files": [
            {"member_path": name, "size_bytes": size, "sha256": "sha256:" + digest}
            for name, size, digest in files
        ],
        "runtime_versions": [
            {"name": name, "version": version} for name, version in runtime_versions
        ],
    }
    body = {
        **recipe,
        "model_id": "embeddingmodel_" + content_sha256(repository)[7:39],
        "model_revision_id": "embeddingmodelrev_" + content_sha256(recipe)[7:39],
    }
    value = {**body, "manifest_sha256": content_sha256(body)}
    validate_contract("item-inference-transfer", value)
    return LocalEmbeddingModelSpec.model_validate(value)


def require_owned_acquisition_store(model_store: Path) -> None:
    """Reject unsafe materialization locations before runtime probing or downloading."""
    if (
        not model_store.is_absolute()
        or model_store.is_symlink()
        or model_store.resolve() != model_store
    ):
        raise ValueError("explicit absolute nonsymlink experiment model store required")
    metadata = model_store.stat()
    if not model_store.is_dir() or metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
        raise ValueError("experiment model store must be an owned nonwritable-by-others directory")


def acquire_reviewed_model(
    model_store: Path,
    spec: LocalEmbeddingModelSpec,
    *,
    opener: Callable[..., BinaryIO],
) -> LocalEmbeddingModelSpec:
    """Materialize verified upstream bytes; retain partial failure without replay.

    An owned temporary store is not canonical production storage. The independent
    protected installer revalidates every source member and does not trust this
    developer process or its manifest as an authorization grant.
    """
    require_owned_acquisition_store(model_store)
    spec = LocalEmbeddingModelSpec.model_validate(spec.model_dump(mode="json"))
    validate_contract("item-inference-transfer", spec.model_dump(mode="json"))
    model_directory = model_store / spec.model_id
    model_directory.mkdir(mode=0o700, exist_ok=False)
    snapshot = model_directory / spec.model_revision_id
    snapshot.mkdir(mode=0o700, exist_ok=False)
    for member in spec.files:
        target = snapshot / member.member_path
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        request = Request(
            f"https://huggingface.co/{spec.upstream_repo}/resolve/"
            f"{spec.upstream_revision}/{member.member_path}",
            headers={"User-Agent": "EOM-offline-embedding-acquisition/1.0"},
        )
        digest = hashlib.sha256()
        size = 0
        descriptor = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
        )
        with os.fdopen(descriptor, "wb") as output, opener(request, timeout=60) as response:
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > member.size_bytes:
                    raise ValueError("model download exceeds immutable file size")
                digest.update(block)
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if size != member.size_bytes or "sha256:" + digest.hexdigest() != member.sha256:
            raise ValueError("model download differs from pinned upstream file identity")
        target.chmod(0o400)
        print(f"EMBEDDING_FILE_VERIFIED={member.member_path}", flush=True)
    manifest = snapshot / "manifest.json"
    descriptor = os.open(
        manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o400
    )
    with os.fdopen(descriptor, "wb") as output:
        output.write(canonical_json_bytes(spec.model_dump(mode="json")))
        output.flush()
        os.fsync(output.fileno())
    print(f"EMBEDDING_EXPERIMENT_MODEL_STORE={model_store}", flush=True)
    print(f"EMBEDDING_EXPERIMENT_MANIFEST_SHA256={spec.manifest_sha256}", flush=True)
    print("PRODUCTION_ACTIVATION=NOT_PERFORMED", flush=True)
    return spec
