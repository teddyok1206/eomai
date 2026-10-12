"""Exact owner-configured runtime bundle resolution over one unchanged legacy payload."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.embedding_runtime_bundle import (
    MAX_RUNTIME_BUNDLE_BYTES,
    EmbeddingRuntimeBundle,
    EmbeddingRuntimeBundlePointer,
    parse_embedding_runtime_bundle,
    validate_embedding_payload_manifest,
    validate_embedding_runtime_bundle_pointer,
)
from jsonschema.exceptions import ValidationError as JsonSchemaError

from eom_catalog_service.local_embedding_adapter import (
    LocalEmbeddingError,
    ProtectedEmbeddingManifest,
    ResolvedLocalEmbeddingPayload,
    read_protected_embedding_manifest,
    resolve_local_embedding_payload,
)


class EmbeddingBundleResolutionError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ConfiguredEmbeddingBundle:
    """Trusted owner installation configuration; never deserialized from worker input."""

    bundle_store_root: Path
    payload_store_root: Path
    pointer: EmbeddingRuntimeBundlePointer
    expected_owner_uid: int = 0


@dataclass(frozen=True, slots=True)
class ResolvedEmbeddingBundle:
    bundle: EmbeddingRuntimeBundle
    payload: ResolvedLocalEmbeddingPayload
    manifest: ProtectedEmbeddingManifest

    def assert_unchanged(self) -> None:
        try:
            self.manifest.assert_unchanged()
            self.payload.assert_unchanged()
        except LocalEmbeddingError as exc:
            raise EmbeddingBundleResolutionError("EMBEDDING_BUNDLE_CHANGED") from exc


def resolve_configured_embedding_bundle(
    configured: ConfiguredEmbeddingBundle,
) -> ResolvedEmbeddingBundle:
    """Read/hash one small successor manifest, then reuse the authoritative legacy resolver.

    The owner must admit the released pointer and operator before configuring this adapter.
    Artifact storage URIs or request claims cannot override these configured local roots.
    """
    try:
        pointer = EmbeddingRuntimeBundlePointer.model_validate(
            configured.pointer.model_dump(mode="json")
        )
        if type(configured.expected_owner_uid) is not int or configured.expected_owner_uid < 0:
            raise EmbeddingBundleResolutionError("EMBEDDING_BUNDLE_CONFIGURATION_INVALID")
        path = (
            configured.bundle_store_root
            / pointer.bundle_id
            / pointer.bundle_revision_id
            / "bundle.json"
        )
        manifest = read_protected_embedding_manifest(
            path,
            expected_owner_uid=configured.expected_owner_uid,
            maximum_bytes=MAX_RUNTIME_BUNDLE_BYTES,
        )
        if manifest.sha256 != pointer.bundle_raw_sha256:
            raise EmbeddingBundleResolutionError("EMBEDDING_BUNDLE_HASH_MISMATCH")
        bundle = parse_embedding_runtime_bundle(json.loads(manifest.raw))
        validate_embedding_runtime_bundle_pointer(bundle, pointer, manifest.raw)
        payload = resolve_local_embedding_payload(
            configured.payload_store_root,
            bundle.payload_model_spec,
            expected_owner_uid=configured.expected_owner_uid,
        )
        validate_embedding_payload_manifest(bundle, payload.manifest.raw)
        result = ResolvedEmbeddingBundle(bundle, payload, manifest)
        result.assert_unchanged()
        return result
    except EmbeddingBundleResolutionError:
        raise
    except LocalEmbeddingError as exc:
        raise EmbeddingBundleResolutionError(exc.code) from exc
    except (OSError, ValueError, TypeError, KeyError, AttributeError, JsonSchemaError) as exc:
        raise EmbeddingBundleResolutionError("EMBEDDING_BUNDLE_INVALID") from exc
