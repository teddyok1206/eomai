"""Exact device pairing through existing current consumer/Artifact read owners."""

from __future__ import annotations

import json

from eom_catalog_contracts.inference_transfer_embedding import MAX_EMBEDDING_INPUT_BYTES
from eom_catalog_contracts.mixed_embedding_index import parse_supported_embedding_index
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.embedding_artifact_store import EMBEDDING_INDEX_ARTIFACT_TYPE
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy.orm import Session

from eom_catalog_service.embedding_device_index_pair import (
    EmbeddingDeviceIndexPair,
    EmbeddingDeviceIndexPairError,
    pair_embedding_device_indexes,
)
from eom_catalog_service.embedding_registry_application import read_pinned_embedding_index
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryRead,
    SupportedEmbeddingIndex,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext


def resolve_embedding_device_index_pair(
    session: Session,
    caller: EmbeddingRegistryCaller,
    *,
    cpu_owner: CatalogEmbeddingRegistryVerifier,
    cpu_intent: EmbeddingRegistryRead,
    cuda_owner: CatalogEmbeddingRegistryVerifier,
    cuda_intent: EmbeddingRegistryRead,
    artifact_reader: PinnedArtifactReadContext,
) -> EmbeddingDeviceIndexPair:
    """Resolve exact revisions; this returned small value never grants future access.

    Each public Registry read performs actual current source, registered metadata,
    Artifact and vector validation. No latest selection or mutable index discovery
    belongs here. QUERY owners still reauthorize their original pins before work,
    commit and subsequent reads; a failed pair is never GPU BUSY/CPU fallback.
    """
    root = session.get_transaction()
    if (
        type(caller) is not EmbeddingRegistryCaller
        or type(cpu_owner) is not CatalogEmbeddingRegistryVerifier
        or type(cuda_owner) is not CatalogEmbeddingRegistryVerifier
        or type(cpu_intent) is not EmbeddingRegistryRead
        or type(cuda_intent) is not EmbeddingRegistryRead
        or root is None
        or not root.is_active
        or session.get_nested_transaction() is not None
        or session.new
        or session.dirty
        or session.deleted
        or session.get_bind() is not cpu_owner.engine
        or cpu_owner.engine is not cuda_owner.engine
        or cpu_owner.identity_fence is None
        or cuda_owner.identity_fence is None
        or cpu_owner.settings != cuda_owner.settings
        or artifact_reader.settings != cpu_owner.settings
    ):
        raise EmbeddingDeviceIndexPairError("EMBEDDING_DEVICE_INDEX_AUTHORITY_UNAVAILABLE")
    artifact_reader.require_session(session)
    cpu_scope, cuda_scope = cpu_intent.scope, cuda_intent.scope
    if (
        cpu_scope.corpus_id != cuda_scope.corpus_id
        or cpu_scope.graph_snapshot != cuda_scope.graph_snapshot
        or cpu_scope.policy_revision_id != cuda_scope.policy_revision_id
        or cpu_scope.policy_sha256 != cuda_scope.policy_sha256
        or cpu_scope.maximum_sources != cuda_scope.maximum_sources
        or cpu_scope.namespace.model_dump(mode="json", exclude={"space_sha256"})
        != cuda_scope.namespace.model_dump(mode="json", exclude={"space_sha256"})
        or cpu_owner.configuration.source_classes != cuda_owner.configuration.source_classes
        or cpu_owner.configuration.namespace != cpu_scope.namespace
        or cuda_owner.configuration.namespace != cuda_scope.namespace
        or cpu_owner.configuration.space.runtime.device != "CPU"
        or cuda_owner.configuration.space.runtime.device != "CUDA"
    ):
        raise EmbeddingDeviceIndexPairError("EMBEDDING_DEVICE_INDEX_NAMESPACE_MISMATCH")

    resolved = tuple(
        read_pinned_embedding_index(session, caller, intent, owner)
        for intent, owner in ((cpu_intent, cpu_owner), (cuda_intent, cuda_owner))
    )
    if resolved[0].sources != resolved[1].sources or resolved[0].profiles != resolved[1].profiles:
        raise EmbeddingDeviceIndexPairError("EMBEDDING_DEVICE_INDEX_CURRENT_TARGET_SET_MISMATCH")
    indexes: list[SupportedEmbeddingIndex] = []
    members: list[ArtifactMemberPointer] = []
    for intent, reading in zip((cpu_intent, cuda_intent), resolved, strict=True):
        pin = intent.selection.index
        if pin is None or reading.intent != intent:
            raise EmbeddingDeviceIndexPairError("EMBEDDING_DEVICE_INDEX_POINTER_MISMATCH")
        member = pin.index_manifest
        raw = artifact_reader.read_pinned(
            **member.model_dump(mode="python"),
            expected_artifact_types=(EMBEDDING_INDEX_ARTIFACT_TYPE,),
            expected_primary_file="index.json",
            max_bytes=MAX_EMBEDDING_INPUT_BYTES,
        ).payload
        index = parse_supported_embedding_index(json.loads(raw))
        if canonical_json_bytes(index.model_dump(mode="json")) != raw or (
            index.bindings != reading.bindings
        ):
            raise EmbeddingDeviceIndexPairError(
                "EMBEDDING_DEVICE_INDEX_CURRENT_TARGET_SET_MISMATCH"
            )
        indexes.append(index)
        members.append(member)
    pair = pair_embedding_device_indexes(
        cpu_member=members[0],
        cpu_index=indexes[0],
        cuda_member=members[1],
        cuda_index=indexes[1],
    )
    for owner, intent in ((cpu_owner, cpu_intent), (cuda_owner, cuda_intent)):
        if session.get_transaction() is not root or not root.is_active:
            raise EmbeddingDeviceIndexPairError("EMBEDDING_DEVICE_INDEX_AUTHORITY_UNAVAILABLE")
        owner.authorize_scope(session, caller, intent.scope)
    artifact_reader.revalidate_provenance()
    if session.get_transaction() is not root or not root.is_active:
        raise EmbeddingDeviceIndexPairError("EMBEDDING_DEVICE_INDEX_AUTHORITY_UNAVAILABLE")
    return pair
