"""Pinned, textbook-only Graph evidence for a scientific review input."""

from __future__ import annotations

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
