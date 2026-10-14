"""Orchestrator-only canonical auxiliary context publication; current authority is upstream."""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.similarity_context import (
    SIMILARITY_CONTEXT_REF,
    SimilarityContext,
    SimilarityContextRequest,
)
from eom_catalog_contracts.similarity_delivery import (
    SimilarityContextDelivery,
    validate_deliverable_similarity_context,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.models import JobId
from pydantic import TypeAdapter, ValidationError

from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetMember,
    ControlFileSetPublisher,
    PublishedControlFileSet,
)

SIMILARITY_CONTEXT_ARTIFACT_TYPE = "control_system_rag_similarity_context"


@dataclass(frozen=True, slots=True)
class PublishedSimilarityContext:
    """Publication lineage, not a source grant or consumer-activation receipt."""

    owner_job_id: str
    delivery: SimilarityContextDelivery
    manifest_sha256: str


def publish_similarity_context(
    publisher: ControlFileSetPublisher,
    *,
    context: SimilarityContext,
    expected_request: SimilarityContextRequest,
    idempotency_key: str,
    source_commit: str,
) -> PublishedSimilarityContext:
    """Caller holds actual current source/operator fences through publication and late checks.

    The existing publisher owns commit/replay, not this leaf. Failures after its return
    may already have committed; preserve and reconcile the original immutable key.
    """
    if type(source_commit) is not str or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise ValueError("SIMILARITY_CONTEXT_PUBLICATION_SOURCE_INVALID")
    checked = validate_deliverable_similarity_context(context, expected_request=expected_request)
    raw = canonical_json_bytes(checked.model_dump(mode="json"))
    digest = sha256_bytes(raw)
    member = "context.json"
    with tempfile.TemporaryDirectory(
        prefix="similarity-context-", dir=publisher.settings.workspace_root
    ) as directory:
        path = Path(directory) / member
        path.write_bytes(raw)
        path.chmod(0o600)
        published = publisher.publish_first_observation(
            members=(
                ControlFileSetMember(
                    member, path, digest, len(raw), SIMILARITY_CONTEXT_REF, "application/json"
                ),
            ),
            primary_file=member,
            artifact_type=SIMILARITY_CONTEXT_ARTIFACT_TYPE,
            manifest_version=CONTROL_FILE_SET_PROTOCOL,
            idempotency_key=idempotency_key,
            source_commit=source_commit,
        )
    if (
        type(published) is not PublishedControlFileSet
        or published.primary_file != member
        or published.primary_sha256 != digest
    ):
        raise ValueError("SIMILARITY_CONTEXT_PUBLICATION_RECEIPT_INVALID")
    try:
        job_id = TypeAdapter(JobId).validate_python(published.job_id)
        manifest_sha256 = TypeAdapter(Sha256).validate_python(published.manifest_sha256)
        pointer = ArtifactMemberPointer(
            artifact_id=published.artifact_id,
            artifact_revision_id=published.artifact_revision_id,
            member_path=member,
            schema_ref=SIMILARITY_CONTEXT_REF,
            media_type="application/json",
            sha256=digest,
        )
    except ValidationError:
        raise ValueError("SIMILARITY_CONTEXT_PUBLICATION_RECEIPT_INVALID") from None
    return PublishedSimilarityContext(
        owner_job_id=job_id,
        delivery=SimilarityContextDelivery(
            schema_version="system-rag-similarity-delivery/1.0",
            context_member=pointer,
            request_sha256=checked.request.request_sha256,
            context_sha256=checked.context_sha256,
        ),
        manifest_sha256=manifest_sha256,
    )
