"""Typed application ports for reviewed legacy-source selection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from eom_catalog_contracts import (
    LegacyKnowledgeContractErrorCode,
    LegacyRightsReviewPointerV2,
    LegacySelectedOriginalSourceV2,
    LegacySourceInventoryEntry,
    LegacySourceRightsReviewV2,
    LegacySourceSelectionV2,
)

from eom_catalog_service.intake_service import IntakeSourceDeclaration


class LegacySourceSelectionError(RuntimeError):
    """Content-free failure at the reviewed legacy selection boundary."""

    def __init__(self, code: LegacyKnowledgeContractErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True)
class LegacySelectionValidation:
    selection_id: str
    selection_sha256: str
    inventory_id: str
    inventory_sha256: str
    intended_corpus_key: str
    source_owner_reference: str
    selected_source_count: int
    comparison_evidence_count: int
    selected_byte_count: int


@dataclass(frozen=True)
class LegacyContentIntakeReceipt:
    intake_batch_id: str
    state: str
    source_fingerprint: str
    source_manifest_artifact_id: str
    source_manifest_artifact_revision_id: str
    source_manifest_sha256: str


@dataclass(frozen=True)
class LegacySelectionArtifactReceipt:
    artifact_id: str
    artifact_revision_id: str
    content_sha256: str
    manifest_sha256: str


@dataclass(frozen=True)
class LegacySelectionIntakeResult:
    validation: LegacySelectionValidation
    intake: LegacyContentIntakeReceipt
    selection_artifact: LegacySelectionArtifactReceipt


@dataclass(frozen=True)
class SelectedInventoryEntry:
    selected: LegacySelectedOriginalSourceV2
    entry: LegacySourceInventoryEntry


@dataclass(frozen=True)
class MaterializedLegacySelection:
    directory: Path
    declarations: tuple[IntakeSourceDeclaration, ...]


class LegacyRightsReviewResolver(Protocol):
    def resolve(self, pointer: LegacyRightsReviewPointerV2) -> LegacySourceRightsReviewV2: ...


class LegacyContentIntakeBoundary(Protocol):
    def create(
        self,
        source_directory: Path,
        *,
        batch_name: str,
        received_by: str,
        purpose: str,
        source_owner_type: str,
        source_owner_reference: str,
        source_declarations: tuple[IntakeSourceDeclaration, ...],
    ) -> LegacyContentIntakeReceipt: ...


class LegacySelectionArtifactBoundary(Protocol):
    def commit(
        self,
        selection: LegacySourceSelectionV2,
        intake: LegacyContentIntakeReceipt,
    ) -> LegacySelectionArtifactReceipt: ...
