"""A completed import is rechecked against the original A:AF workbook observation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from eom_catalog_contracts import ExternalItemImportManifest
from eom_catalog_service.external_item_import_audit import (
    ExternalItemImportAuditError,
    _verify_editions,
    _verify_rows,
)
from eom_catalog_service.external_item_observations import (
    ExternalItemWorkbookPointer,
    external_item_search_facets,
)
from eom_catalog_service.external_item_xlsx import DecodedExternalItemRow

from tests.unit.test_external_item_import_contract import _manifest


def _case():
    manifest = ExternalItemImportManifest.model_validate(_manifest())
    observed = manifest.rows[0].observation
    facets = external_item_search_facets(observed)
    decoded = DecodedExternalItemRow(
        row_number=observed.row_number,
        external_number=observed.external_number,
        cells=observed.cells,
    )
    source = SimpleNamespace(
        source_id="extitem_" + "a" * 32,
        source_namespace=observed.source_namespace,
        external_number=observed.external_number,
    )
    revision = SimpleNamespace(
        revision_id="extitemrev_" + "b" * 32,
        source_id=source.source_id,
        row_number=observed.row_number,
        external_number=observed.external_number,
        worksheet_name=observed.worksheet_name,
        observation_sha256=observed.observation_sha256,
        cells=[cell.model_dump(mode="json") for cell in observed.cells],
        match_status="MATCHED_DETECTED_HWPX",
        selected_source_file_id=manifest.rows[0].selected_source_file_id,
        unit_major=facets.major_unit,
        unit_minor=facets.minor_unit,
        field_label=facets.field,
        grade_label=facets.grade,
        author_label=facets.author,
    )
    workbook = ExternalItemWorkbookPointer(
        artifact_id=manifest.workbook_artifact_id,
        artifact_revision_id=manifest.workbook_artifact_revision_id,
        sha256=manifest.workbook_sha256,
    )
    return manifest.mapping, workbook, decoded, revision, source


def test_audit_accepts_exact_workbook_row_and_recomputes_facets() -> None:
    mapping, workbook, decoded, revision, source = _case()
    counts = _verify_rows((decoded,), ((revision, source),), mapping=mapping, workbook=workbook)
    assert counts == {"MATCHED_DETECTED_HWPX": 1}


@pytest.mark.parametrize(
    "tamper",
    [
        lambda revision, source: setattr(revision, "external_number", "00043"),
        lambda revision, source: setattr(source, "source_namespace", "other"),
        lambda revision, source: setattr(revision, "unit_major", "잘못된 단원"),
        lambda revision, source: revision.cells[0].update({"raw_text": "변조"}),
    ],
)
def test_audit_rejects_changed_source_or_cells(tamper) -> None:
    mapping, workbook, decoded, revision, source = _case()
    tamper(revision, source)
    with pytest.raises(ExternalItemImportAuditError) as captured:
        _verify_rows((decoded,), ((revision, source),), mapping=mapping, workbook=workbook)
    assert captured.value.code == "EXTERNAL_ITEM_AUDIT_ROW_MISMATCH"


def test_audit_rejects_dropped_revision() -> None:
    mapping, workbook, decoded, _, _ = _case()
    with pytest.raises(ExternalItemImportAuditError) as captured:
        _verify_rows((decoded,), (), mapping=mapping, workbook=workbook)
    assert captured.value.code == "EXTERNAL_ITEM_AUDIT_ROW_COUNT"


def test_audit_requires_original_edition_set_and_exact_file_hash() -> None:
    _, _, decoded, revision, source = _case()
    edition = SimpleNamespace(
        source_revision_id=revision.revision_id,
        edition=3,
        source_file_id=revision.selected_source_file_id,
        document_sha256="sha256:" + "9" * 64,
    )
    file = SimpleNamespace(sha256=edition.document_sha256)
    _verify_editions((decoded,), ((revision, source),), ((edition, file),))
    with pytest.raises(ExternalItemImportAuditError) as captured:
        _verify_editions((decoded,), ((revision, source),), ())
    assert captured.value.code == "EXTERNAL_ITEM_AUDIT_EDITION_SET"
    with pytest.raises(ExternalItemImportAuditError) as captured:
        _verify_editions((decoded,), ((revision, source),), ((edition, None),))
    assert captured.value.code == "EXTERNAL_ITEM_AUDIT_DOCUMENT_POINTER"
    revision.selected_source_file_id = "sourcefile_" + "c" * 32
    with pytest.raises(ExternalItemImportAuditError) as captured:
        _verify_editions((decoded,), ((revision, source),), ((edition, file),))
    assert captured.value.code == "EXTERNAL_ITEM_AUDIT_SELECTED_DOCUMENT"
