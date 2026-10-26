"""Pinned, textbook-only Graph evidence for a scientific review input."""

from __future__ import annotations

import re
from typing import Literal

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.knowledge import (
    EducationalRetrievalRequirement,
    EvidenceBundleManifestV3,
    EvidenceBundleManifestV4,
    EvidenceBundlePublicationResultV3,
    EvidenceBundlePublicationResultV4,
)
from eom_catalog_contracts.models import FrozenModel, Sha256


class ReviewTextbookEvidence(FrozenModel):
    """Catalog publication and exact textbook entries bound to one review input.

    The manifest check requires materialized, hash-validated Catalog bytes. Merely
    validating this compact pointer cannot prove what the reviewer was shown.
    """

    schema_version: Literal["review-textbook-evidence/1.0"] = "review-textbook-evidence/1.0"
    review_input_sha256: Sha256
    requirement: EducationalRetrievalRequirement
    publication: EvidenceBundlePublicationResultV3 | EvidenceBundlePublicationResultV4
    textbook_evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=128)
    binding_sha256: Sha256

    @model_validator(mode="after")
    def exact_textbook_scope_and_hash(self) -> ReviewTextbookEvidence:
        if self.requirement.source_classes != ("TEXTBOOK",):
            raise ValueError("review evidence must request textbook sources exclusively")
        if self.requirement.query_kind != "ITEM_PREPARATION":
            raise ValueError("review textbook evidence requires a bounded topic query")
        if self.textbook_evidence_ids != tuple(sorted(set(self.textbook_evidence_ids))):
            raise ValueError("textbook evidence IDs must be sorted and unique")
        if any(
            len(value) != 45
            or not value.startswith("evidenceitem_")
            or any(char not in "0123456789abcdef" for char in value[13:])
            for value in self.textbook_evidence_ids
        ):
            raise ValueError("textbook evidence ID is invalid")
        if content_sha256(self.model_dump(mode="json", exclude={"binding_sha256"})) != (
            self.binding_sha256
        ):
            raise ValueError("review textbook evidence binding hash differs")
        return self

    def verify_manifest(
        self, manifest: EvidenceBundleManifestV3 | EvidenceBundleManifestV4
    ) -> None:
        """Prove that every cited entry is in this exact published textbook bundle."""

        publication = self.publication
        if (
            manifest.schema_version.rsplit("/", maxsplit=1)[-1]
            != publication.schema_version.rsplit("/", maxsplit=1)[-1]
            or manifest.evidence_bundle_id != publication.evidence_bundle_id
            or manifest.evidence_bundle_revision_id != publication.evidence_bundle_revision_id
            or manifest.retrieval_request_id != publication.retrieval_request_id
            or manifest.retrieval_request_sha256 != publication.retrieval_request_sha256
            or manifest.graph_snapshot != publication.graph_snapshot
            or manifest.access_policy_revision_id != publication.access_policy_revision_id
            or manifest.access_policy_sha256 != publication.access_policy_sha256
            or manifest.requester_permissions_sha256 != publication.requester_permissions_sha256
            or manifest.manifest_sha256 != publication.manifest_sha256
            or manifest.materials.context_markdown != publication.context_artifact
        ):
            raise ValueError("review textbook manifest differs from pinned publication")
        textbook_entries = tuple(
            entry for entry in manifest.entries if entry.source.source_class == "TEXTBOOK"
        )
        if len(textbook_entries) != len(manifest.entries):
            raise ValueError("textbook-only review bundle contains a non-textbook source")
        if not any(entry.use == "GROUNDING" for entry in textbook_entries):
            raise ValueError("review bundle has no grounding textbook evidence")
        if self.textbook_evidence_ids != tuple(
            sorted(entry.evidence_id for entry in textbook_entries)
        ):
            raise ValueError("review textbook evidence IDs differ from pinned manifest")


class ReviewTextbookCitation(FrozenModel):
    """One textbook grounding entry applied to bounded result conclusion paths."""

    evidence_id: str = Field(pattern=r"^evidenceitem_[0-9a-f]{32}$")
    anchor_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    conclusion_paths: tuple[str, ...] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def canonical_paths_and_anchors(self) -> ReviewTextbookCitation:
        if self.anchor_ids != tuple(sorted(set(self.anchor_ids))) or any(
            re.fullmatch(r"anchor_[a-z0-9][a-z0-9_-]{0,63}", value) is None
            for value in self.anchor_ids
        ):
            raise ValueError("review textbook citation anchors must be sorted valid IDs")
        if self.conclusion_paths != tuple(sorted(set(self.conclusion_paths))):
            raise ValueError("review textbook conclusion paths must be sorted and unique")
        for pointer in self.conclusion_paths:
            if (
                len(pointer) < 2
                or len(pointer) > 512
                or not pointer.startswith("/")
                or any(
                    not token
                    or re.search(r"~(?![01])", token)
                    or any(ord(char) < 32 for char in token)
                    for token in pointer[1:].split("/")
                )
            ):
                raise ValueError("review textbook conclusion is not a canonical JSON Pointer")
        return self


class ReviewTextbookUsage(FrozenModel):
    """Self-hashed cited use; output-specific receipt still validates each result path."""

    schema_version: Literal["review-textbook-usage/1.0"] = "review-textbook-usage/1.0"
    binding_sha256: Sha256
    citations: tuple[ReviewTextbookCitation, ...] = Field(min_length=1, max_length=128)
    usage_sha256: Sha256

    @model_validator(mode="after")
    def canonical_usage(self) -> ReviewTextbookUsage:
        evidence_ids = tuple(value.evidence_id for value in self.citations)
        if evidence_ids != tuple(sorted(set(evidence_ids))):
            raise ValueError("review textbook citations must have sorted unique evidence IDs")
        if content_sha256(self.model_dump(mode="json", exclude={"usage_sha256"})) != (
            self.usage_sha256
        ):
            raise ValueError("review textbook usage hash differs")
        return self

    def verify_manifest(
        self,
        binding: ReviewTextbookEvidence,
        manifest: EvidenceBundleManifestV3 | EvidenceBundleManifestV4,
    ) -> None:
        """Prove exact permitted grounding IDs and source anchors, not scientific truth."""

        if self.binding_sha256 != binding.binding_sha256:
            raise ValueError("review textbook usage refers to a different binding")
        binding.verify_manifest(manifest)
        entries = {entry.evidence_id: entry for entry in manifest.entries}
        for citation in self.citations:
            entry = entries.get(citation.evidence_id)
            if (
                entry is None
                or citation.evidence_id not in binding.textbook_evidence_ids
                or entry.use != "GROUNDING"
                or not set(citation.anchor_ids).issubset(entry.anchor_ids)
            ):
                raise ValueError("review textbook citation lacks pinned grounding anchors")
