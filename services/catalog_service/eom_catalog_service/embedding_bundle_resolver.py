"""Exact owner-configured runtime bundle resolution over one unchanged legacy payload."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from eom_catalog_contracts.embedding_runtime_bundle import (
    MAX_RUNTIME_BUNDLE_BYTES,
    EmbeddingRuntimeBundle,
    EmbeddingRuntimeBundlePointer,
    parse_embedding_runtime_bundle,
    validate_embedding_payload_manifest,
    validate_embedding_runtime_bundle_pointer,
)
from eom_identifiers import sha256_bytes
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
class _ResolvedBundleWitness:
    configured: ConfiguredEmbeddingBundle
    bundle: EmbeddingRuntimeBundle
    payload: ResolvedLocalEmbeddingPayload
    manifest: ProtectedEmbeddingManifest
    members: tuple[tuple[str, int, str], ...]

    def __deepcopy__(self, memo: dict[int, object]) -> _ResolvedBundleWitness:
        # A copied witness still binds the original authoritative read objects.
        return self


@dataclass(frozen=True, slots=True)
class ResolvedEmbeddingBundle:
    bundle: EmbeddingRuntimeBundle
    payload: ResolvedLocalEmbeddingPayload
    manifest: ProtectedEmbeddingManifest
    _resolution_witness: _ResolvedBundleWitness | None = field(
        default=None, repr=False, compare=False
    )

    def assert_unchanged(self) -> None:
        try:
            self.manifest.assert_unchanged()
            self.payload.assert_unchanged()
        except LocalEmbeddingError as exc:
            raise EmbeddingBundleResolutionError("EMBEDDING_BUNDLE_CHANGED") from exc


def resolve_configured_embedding_bundle(
    configured: ConfiguredEmbeddingBundle,
    *,
    observe_member_identity: Callable[[Path], None] | None = None,
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
        if observe_member_identity is not None:
            observe_member_identity(path)
        manifest = read_protected_embedding_manifest(
            path,
            expected_owner_uid=configured.expected_owner_uid,
            maximum_bytes=MAX_RUNTIME_BUNDLE_BYTES,
        )
        if manifest.sha256 != pointer.bundle_raw_sha256:
            raise EmbeddingBundleResolutionError("EMBEDDING_BUNDLE_HASH_MISMATCH")
        bundle = parse_embedding_runtime_bundle(json.loads(manifest.raw))
        validate_embedding_runtime_bundle_pointer(bundle, pointer, manifest.raw)
        if observe_member_identity is not None:
            root = (
                configured.payload_store_root
                / bundle.payload_model_spec.model_id
                / bundle.payload_model_spec.model_revision_id
            )
            observe_member_identity(root / "manifest.json")
            for member in bundle.payload_model_spec.files:
                observe_member_identity(root / member.member_path)
        payload = resolve_local_embedding_payload(
            configured.payload_store_root,
            bundle.payload_model_spec,
            expected_owner_uid=configured.expected_owner_uid,
        )
        validate_embedding_payload_manifest(bundle, payload.manifest.raw)
        members = tuple(
            (member.member_path, member.size_bytes, member.sha256)
            for member in bundle.payload_model_spec.files
        )
        if not members:
            raise EmbeddingBundleResolutionError("EMBEDDING_BUNDLE_INVALID")
        # Only the authoritative public payload resolver minted these original audited objects.
        witness = _ResolvedBundleWitness(configured, bundle, payload, manifest, members)
        result = ResolvedEmbeddingBundle(bundle, payload, manifest, witness)
        result.assert_unchanged()
        return result
    except EmbeddingBundleResolutionError:
        raise
    except LocalEmbeddingError as exc:
        raise EmbeddingBundleResolutionError(exc.code) from exc
    except (OSError, ValueError, TypeError, KeyError, AttributeError, JsonSchemaError) as exc:
        raise EmbeddingBundleResolutionError("EMBEDDING_BUNDLE_INVALID") from exc


def validate_resolved_embedding_bundle(
    configured: ConfiguredEmbeddingBundle, resolved: ResolvedEmbeddingBundle
) -> None:
    """Reuse original audited objects, not a constructed snapshot or an authority capability.

    The private witness records ordinary Python construction provenance, not a security
    boundary against arbitrary Python code. Worker wire values never construct this adapter.
    """
    try:
        witness = resolved._resolution_witness
        pointer = EmbeddingRuntimeBundlePointer.model_validate(
            configured.pointer.model_dump(mode="json")
        )
        members = tuple(
            (member.member_path, member.size_bytes, member.sha256)
            for member in resolved.bundle.payload_model_spec.files
        )
        if (
            type(resolved) is not ResolvedEmbeddingBundle
            or witness is None
            or type(witness) is not _ResolvedBundleWitness
            or witness.configured != configured
            or witness.bundle is not resolved.bundle
            or witness.payload is not resolved.payload
            or witness.manifest is not resolved.manifest
            or not members
            or members != witness.members
            or len({name for name, _size, _sha in members}) != len(members)
            or resolved.payload.model_spec != resolved.bundle.payload_model_spec
            or resolved.manifest.path
            != configured.bundle_store_root
            / pointer.bundle_id
            / pointer.bundle_revision_id
            / "bundle.json"
            or resolved.payload.root
            != configured.payload_store_root
            / resolved.bundle.payload_model_spec.model_id
            / resolved.bundle.payload_model_spec.model_revision_id
            or resolved.payload.manifest.path != resolved.payload.root / "manifest.json"
            or resolved.manifest.sha256 != sha256_bytes(resolved.manifest.raw)
        ):
            raise EmbeddingBundleResolutionError("EMBEDDING_BUNDLE_SNAPSHOT_INVALID")
        resolved.assert_unchanged()
        validate_embedding_runtime_bundle_pointer(resolved.bundle, pointer, resolved.manifest.raw)
        validate_embedding_payload_manifest(resolved.bundle, resolved.payload.manifest.raw)
        resolved.assert_unchanged()
    except EmbeddingBundleResolutionError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise EmbeddingBundleResolutionError("EMBEDDING_BUNDLE_SNAPSHOT_INVALID") from exc
