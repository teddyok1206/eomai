"""Publish one reviewed numerical bundle through the existing Artifact commit owner."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from eom_catalog_contracts.embedding_runtime_bundle import (
    RUNTIME_BUNDLE_SCHEMA_REF,
    EmbeddingRuntimeBundle,
    EmbeddingRuntimeBundlePointer,
    embedding_runtime_bundle_bytes,
    parse_embedding_runtime_bundle,
    validate_embedding_runtime_bundle_pointer,
)
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_identifiers import content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.models import JobId
from eom_workflow import ControlArtifactPointer
from pydantic import TypeAdapter

from eom_orchestrator.control_artifacts import ControlArtifactPublisher

RUNTIME_BUNDLE_ARTIFACT_TYPE = "control_embedding_runtime_bundle"
RUNTIME_BUNDLE_MEMBER = "bundle.json"


class EmbeddingBundlePublicationError(ValueError):
    """A content-free boundary error, not a claim that an attempted commit never happened."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PublishedEmbeddingRuntimeBundle:
    owner_job_id: str
    bundle: EmbeddingRuntimeBundlePointer
    manifest_sha256: str


class EmbeddingRuntimeBundleArtifactPublisher:
    """No model loading, new persistence or authority: the installation owner admits callers.

    Source commit is supplied by installed composition. Bundle IDs are owner-assigned;
    Artifact identities come only from the existing publisher's actual immutable receipt.
    """

    def __init__(self, publisher: ControlArtifactPublisher, *, source_commit: str) -> None:
        if type(source_commit) is not str or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
            raise EmbeddingBundlePublicationError("EMBEDDING_BUNDLE_SOURCE_INVALID")
        self.publisher = publisher
        self.source_commit = source_commit

    def publish(
        self, bundle: EmbeddingRuntimeBundle, *, created_at: datetime
    ) -> PublishedEmbeddingRuntimeBundle:
        try:
            checked = parse_embedding_runtime_bundle(bundle.model_dump(mode="json"))
            timestamp = TypeAdapter(UtcDatetime).validate_python(created_at)
            raw = embedding_runtime_bundle_bytes(checked)
        except Exception:
            raise EmbeddingBundlePublicationError("EMBEDDING_BUNDLE_CONTEXT_INVALID") from None

        # Content is deliberately excluded: changed bytes at the same identity must conflict,
        # not silently allocate a second artifact for the same immutable bundle revision.
        key = "embedding-runtime-bundle-artifact:" + content_sha256(
            {"bundle_id": checked.bundle_id, "bundle_revision_id": checked.bundle_revision_id}
        ).removeprefix("sha256:")
        published = self.publisher.publish_bytes(
            payload=raw,
            logical_name=RUNTIME_BUNDLE_MEMBER,
            schema_ref=RUNTIME_BUNDLE_SCHEMA_REF,
            media_type="application/json",
            artifact_type=RUNTIME_BUNDLE_ARTIFACT_TYPE,
            idempotency_key=key,
            created_at=timestamp,
            source_commit=self.source_commit,
        )
        try:
            owner_job_id = TypeAdapter(JobId).validate_python(published.job_id)
            manifest_sha256 = TypeAdapter(Sha256).validate_python(published.manifest_sha256)
            member = ControlArtifactPointer.model_validate(
                published.pointer.model_dump(mode="json")
            )
            if (
                member.logical_name != RUNTIME_BUNDLE_MEMBER
                or member.schema_ref != RUNTIME_BUNDLE_SCHEMA_REF
                or member.media_type != "application/json"
                or member.sha256 != sha256_bytes(raw)
            ):
                raise ValueError("runtime bundle owner receipt differs")
            pointer = EmbeddingRuntimeBundlePointer(
                bundle_id=checked.bundle_id,
                bundle_revision_id=checked.bundle_revision_id,
                bundle_sha256=checked.bundle_sha256,
                bundle_raw_sha256=member.sha256,
                manifest_member=ArtifactMemberPointer(
                    artifact_id=member.artifact_id,
                    artifact_revision_id=member.artifact_revision_id,
                    member_path=member.logical_name,
                    schema_ref=member.schema_ref,
                    media_type=member.media_type,
                    sha256=member.sha256,
                ),
            )
            validate_embedding_runtime_bundle_pointer(checked, pointer, raw)
            return PublishedEmbeddingRuntimeBundle(owner_job_id, pointer, manifest_sha256)
        except Exception:
            # Preserve the real owner's history. Reconcile this same key, never resubmit a
            # new identity or claim that this post-publication failure means no write occurred.
            raise EmbeddingBundlePublicationError("EMBEDDING_BUNDLE_RECEIPT_INVALID") from None
