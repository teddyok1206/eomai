"""Orchestrator-only Artifact publication of exact creative worker page inputs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from eom_catalog_contracts.external_item_learning_pages import (
    EXTERNAL_ITEM_LEARNING_PAGE_IMAGE_SCHEMA_REF,
    EXTERNAL_ITEM_LEARNING_PAGE_SET_SCHEMA,
    EXTERNAL_ITEM_LEARNING_PAGE_SET_SCHEMA_REF,
)
from eom_catalog_contracts.external_item_learning_work import ExternalItemLearningPageArtifact
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes

from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.external_item_learning_page_render import RenderedExternalItemLearningPages
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
    PublishedControlFileSet,
)

_ARTIFACT_TYPE = "control_external_item_learning_pages"
_ARTIFACT_MANIFEST_VERSION = "external-item-learning-page-set-artifact/1.0"
_PRIMARY_FILE = "page-set-manifest.json"


class CreativePageSetPublisher(Protocol):
    def publish_first_observation(
        self,
        *,
        members: tuple[ControlFileSetMember, ...],
        primary_file: str,
        artifact_type: str,
        manifest_version: str,
        idempotency_key: str,
        source_commit: str,
    ) -> PublishedControlFileSet: ...


def external_item_learning_page_artifact(
    receipt: PublishedControlFileSet,
) -> ExternalItemLearningPageArtifact:
    """Turn the existing publication receipt into a typed immutable member pin."""

    if receipt.primary_file != _PRIMARY_FILE:
        raise ValueError("CREATIVE_PAGE_PUBLICATION_RECEIPT_INVALID")
    return ExternalItemLearningPageArtifact(
        artifact_id=receipt.artifact_id,
        artifact_revision_id=receipt.artifact_revision_id,
        sha256=receipt.primary_sha256,
        file_set_manifest_sha256=receipt.manifest_sha256,
    )


def read_external_item_learning_page_artifact(
    publisher: ControlFileSetPublisher, artifact: ExternalItemLearningPageArtifact
) -> PublishedControlFileSet:
    """Recheck the approved file-set closure without publishing or resolving latest."""

    published = publisher.read_published_revision(
        artifact_revision_id=artifact.artifact_revision_id,
        artifact_type=artifact.artifact_type,
    )
    if (
        published.artifact_id != artifact.artifact_id
        or published.primary_file != artifact.member_path
        or published.primary_sha256 != artifact.sha256
        or published.manifest_sha256 != artifact.file_set_manifest_sha256
        or Path(published.nas_path)
        != publisher.settings.nas_artifact_root
        / artifact.artifact_id
        / artifact.artifact_revision_id
    ):
        raise ControlPlaneError(
            "CONTROL_POINTER_MANIFEST_MISMATCH", "creative page Artifact differs from work"
        )
    return published


def publish_external_item_learning_pages(
    publisher: CreativePageSetPublisher,
    rendered: RenderedExternalItemLearningPages,
    *,
    source_commit: str,
) -> PublishedControlFileSet:
    """Reuse the existing resumable file-set owner, never commit the source PDF."""

    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise ValueError("CREATIVE_PAGE_PUBLICATION_SOURCE_INVALID")
    manifest = rendered.manifest
    validate_contract(EXTERNAL_ITEM_LEARNING_PAGE_SET_SCHEMA, manifest.model_dump(mode="json"))
    expected_manifest_bytes = canonical_json_bytes(manifest.model_dump(mode="json"))
    if (
        rendered.manifest_path != rendered.workspace / _PRIMARY_FILE
        or not rendered.manifest_path.is_file()
        or rendered.manifest_path.is_symlink()
        or rendered.manifest_path.read_bytes() != expected_manifest_bytes
        or tuple(rendered.workspace / page.member_path for page in manifest.pages)
        != rendered.page_paths
        or any(path.is_symlink() for path in rendered.page_paths)
    ):
        raise ValueError("CREATIVE_PAGE_PUBLICATION_INPUT_INVALID")
    members = [
        ControlFileSetMember(
            _PRIMARY_FILE,
            rendered.manifest_path,
            sha256_bytes(expected_manifest_bytes),
            len(expected_manifest_bytes),
            EXTERNAL_ITEM_LEARNING_PAGE_SET_SCHEMA_REF,
            "application/json",
        )
    ]
    members.extend(
        ControlFileSetMember(
            page.member_path,
            path,
            page.sha256,
            page.content_length,
            EXTERNAL_ITEM_LEARNING_PAGE_IMAGE_SCHEMA_REF,
            "image/png",
        )
        for page, path in zip(manifest.pages, rendered.page_paths, strict=True)
    )
    idempotency_hash = content_sha256(
        {
            "page_set_sha256": manifest.manifest_sha256,
            "source_commit": source_commit,
            "artifact_type": _ARTIFACT_TYPE,
        }
    )
    return publisher.publish_first_observation(
        members=tuple(sorted(members, key=lambda member: member.file_name)),
        primary_file=_PRIMARY_FILE,
        artifact_type=_ARTIFACT_TYPE,
        manifest_version=_ARTIFACT_MANIFEST_VERSION,
        idempotency_key="creative-page-set:" + idempotency_hash[7:],
        source_commit=source_commit,
    )
