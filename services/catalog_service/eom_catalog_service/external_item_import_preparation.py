"""Build one atomic source-only import from reviewed archive/Intake observations."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts import (
    EXTERNAL_ITEM_IMPORT_MANIFEST_SCHEMA,
    ExternalItemImportManifest,
    ExternalItemWorkbookMapping,
    validate_contract,
)
from eom_identifiers import content_sha256

from eom_catalog_service.external_item_archive import ExternalItemArchiveInventory
from eom_catalog_service.external_item_matching import (
    ExternalItemEditionLinkMatch,
    ExternalItemLinkMatch,
    propose_external_item_edition_links,
    propose_external_item_links,
)
from eom_catalog_service.external_item_observations import (
    ExternalItemWorkbookPointer,
    bind_external_item_observation,
)
from eom_catalog_service.external_item_xlsx import DecodedExternalItemRow


class ExternalItemImportPreparationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CommittedExternalItemSource:
    source_file_id: str
    sha256: str
    original_filename: str


def prepare_external_item_import(
    *,
    actor_id: str,
    mapping: ExternalItemWorkbookMapping,
    workbook_source_file_id: str,
    workbook: ExternalItemWorkbookPointer,
    inventory: ExternalItemArchiveInventory,
    rows: tuple[DecodedExternalItemRow, ...],
    committed_documents: tuple[CommittedExternalItemSource, ...],
) -> ExternalItemImportManifest:
    """Require every matched source member to have an exact committed file pointer."""

    if not rows or len(rows) > mapping.maximum_rows:
        raise ExternalItemImportPreparationError(
            "EXTERNAL_ITEM_IMPORT_ROW_COUNT_INVALID", "mapped row count is invalid"
        )
    by_identity: dict[tuple[str, str], CommittedExternalItemSource] = {}
    for source in committed_documents:
        key = (source.sha256, source.original_filename)
        previous = by_identity.setdefault(key, source)
        if previous != source:
            raise ExternalItemImportPreparationError(
                "EXTERNAL_ITEM_IMPORT_FILE_AMBIGUOUS", "committed file hash is ambiguous"
            )
    proposals = propose_external_item_links(rows, inventory)
    editions_by_row: dict[int, list[ExternalItemEditionLinkMatch]] = {}
    for edition_link in propose_external_item_edition_links(rows, inventory):
        editions_by_row.setdefault(edition_link.row_number, []).append(edition_link)
    manifest_rows: list[dict[str, object]] = []
    for row, proposal in zip(rows, proposals, strict=True):
        source_file_id, source_sha256 = _selected_file(proposal, by_identity)
        observation = bind_external_item_observation(row, mapping=mapping, workbook=workbook)
        edition_links = []
        for edition in editions_by_row.get(row.row_number, []):
            edition_file_id, edition_sha256 = _selected_file(edition, by_identity)
            edition_links.append(
                {
                    "edition": edition.edition,
                    "match_status": edition.status.value,
                    "selected_source_file_id": edition_file_id,
                    "selected_document_sha256": edition_sha256,
                }
            )
        manifest_rows.append(
            {
                "observation": observation.model_dump(mode="json"),
                "match_status": proposal.status.value,
                "selected_source_file_id": source_file_id,
                "selected_document_sha256": source_sha256,
                "edition_links": edition_links,
            }
        )
    body: dict[str, object] = {
        "schema_version": "external-item-import-manifest/1.0",
        "source_namespace": mapping.source_namespace,
        "actor_id": actor_id,
        "mapping": mapping.model_dump(mode="json"),
        "workbook_source_file_id": workbook_source_file_id,
        "workbook_artifact_id": workbook.artifact_id,
        "workbook_artifact_revision_id": workbook.artifact_revision_id,
        "workbook_sha256": workbook.sha256,
        "archive_sha256": inventory.archive_sha256,
        "rows": manifest_rows,
    }
    body["request_sha256"] = content_sha256(body)
    validate_contract(EXTERNAL_ITEM_IMPORT_MANIFEST_SCHEMA, body)
    return ExternalItemImportManifest.model_validate(body)


def _selected_file(
    proposal: ExternalItemLinkMatch | ExternalItemEditionLinkMatch,
    by_identity: dict[tuple[str, str], CommittedExternalItemSource],
) -> tuple[str | None, str | None]:
    selected = proposal.selected_member
    if selected is None:
        return None, None
    committed = by_identity.get((selected.sha256, selected.display_filename))
    if committed is None:
        raise ExternalItemImportPreparationError(
            "EXTERNAL_ITEM_IMPORT_FILE_MISSING",
            "matched document has no exact committed source file",
        )
    return committed.source_file_id, committed.sha256
