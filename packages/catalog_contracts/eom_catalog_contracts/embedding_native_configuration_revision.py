"""Pure existing-schema revision projection; no identity allocation, IO or admission."""

from __future__ import annotations

import re

from eom_identifiers import content_sha256

from eom_catalog_contracts.embedding_native_installation_evidence import (
    RootLocalNativeConfigurationPin,
)
from eom_catalog_contracts.embedding_native_runtime_config import (
    InstalledEmbeddingNativeRuntimeConfig,
    installed_embedding_native_runtime_config_bytes,
    parse_installed_embedding_native_runtime_config,
    parse_installed_embedding_native_runtime_config_bytes,
    validate_installed_embedding_native_runtime_config_raw,
)


def derive_native_configuration_revision(
    original_raw: bytes,
    predecessor: RootLocalNativeConfigurationPin,
    revision_id: str,
) -> tuple[InstalledEmbeddingNativeRuntimeConfig, bytes]:
    """Keep every numerical/host/resource pin and schema family; change exactly two values.

    The caller supplies the independently pinned predecessor and a new revision.
    Neither this small value nor the result authenticates the caller, publishes a
    file, certifies a prefix or replaces the existing actual same-live probe/seal.
    """
    predecessor = RootLocalNativeConfigurationPin.model_validate(predecessor)
    original = parse_installed_embedding_native_runtime_config_bytes(original_raw)
    validate_installed_embedding_native_runtime_config_raw(
        original, original_raw, predecessor.configuration_raw_sha256
    )
    if (
        original.configuration_id != predecessor.configuration_id
        or original.configuration_revision_id != predecessor.configuration_revision_id
        or original.config_sha256 != predecessor.configuration_sha256
        or type(revision_id) is not str
        or re.fullmatch(r"embeddingnativeconfigrev_[0-9a-f]{32}", revision_id, re.ASCII) is None
        or revision_id == original.configuration_revision_id
    ):
        raise ValueError("EMBEDDING_NATIVE_CONFIGURATION_REVISION_INVALID")
    body = original.model_dump(mode="json", exclude={"config_sha256"})
    body["configuration_revision_id"] = revision_id
    successor = parse_installed_embedding_native_runtime_config(
        body | {"config_sha256": content_sha256(body)}
    )
    return successor, installed_embedding_native_runtime_config_bytes(successor)
