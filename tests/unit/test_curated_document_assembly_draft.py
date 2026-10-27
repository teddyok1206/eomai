"""The mixed-source assembly draft preserves provenance without publishing an Item."""

import json
from pathlib import Path

import pytest
from eom_api_contracts.curated_document_assembly import CuratedDocumentAssemblyDraftV1
from jsonschema import Draft202012Validator
from pydantic import ValidationError

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "schemas/api/v1/curated-document-assembly-draft-v1.schema.json"
    ).read_text(encoding="utf-8")
)


def _external(position: int = 1) -> dict[str, object]:
    return {
        "placement_kind": "EXTERNAL_SOURCE_DOCUMENT",
        "position": position,
        "source_id": "extitem_" + "1" * 32,
        "source_revision_id": "extitemrev_" + "2" * 32,
        "observation_sha256": "sha256:" + "3" * 64,
        "edition": 3,
        "source_format": "HWP",
    }


def _item(position: int = 2, kind: str = "PAST_EXAM_ITEM_REVISION") -> dict[str, object]:
    return {
        "placement_kind": kind,
        "position": position,
        "item_id": "item_" + "4" * 32,
        "item_revision_id": "itemrev_" + "5" * 32,
        "item_manifest_sha256": "sha256:" + "6" * 64,
        "graph_snapshot_revision_id": "graphrev_" + "7" * 32,
        "graph_snapshot_sha256": "sha256:" + "8" * 64,
    }


def test_mixed_draft_validates_with_json_schema_and_pydantic() -> None:
    Draft202012Validator.check_schema(SCHEMA)
    body = {
        "schema_version": "curated-document-assembly-draft/1.0",
        "placements": [_external(), _item()],
    }
    Draft202012Validator(SCHEMA).validate(body)
    parsed = CuratedDocumentAssemblyDraftV1.model_validate(body)
    assert parsed.placements[0].placement_kind == "EXTERNAL_SOURCE_DOCUMENT"
    assert parsed.placements[1].placement_kind == "PAST_EXAM_ITEM_REVISION"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda rows: rows[0].update({"edition": 1}),
        lambda rows: rows[0].update({"source_format": "PDF"}),
        lambda rows: rows[0].update({"source_revision_id": "itemrev_" + "2" * 32}),
        lambda rows: rows[1].update({"graph_snapshot_sha256": "8" * 64}),
        lambda rows: rows[1].update({"source_class": "PAST_EXAM"}),
    ],
)
def test_invalid_pointer_or_unexpected_fields_fail_both_contracts(mutate) -> None:
    placements = [_external(), _item()]
    mutate(placements)
    body = {"schema_version": "curated-document-assembly-draft/1.0", "placements": placements}
    assert not Draft202012Validator(SCHEMA).is_valid(body)
    with pytest.raises(ValidationError):
        CuratedDocumentAssemblyDraftV1.model_validate(body)


def test_draft_requires_contiguous_positions_and_unique_source_identity() -> None:
    base = {"schema_version": "curated-document-assembly-draft/1.0"}
    with pytest.raises(ValidationError):
        CuratedDocumentAssemblyDraftV1.model_validate(
            {**base, "placements": [_external(), _item(position=3)]}
        )
    with pytest.raises(ValidationError):
        CuratedDocumentAssemblyDraftV1.model_validate(
            {**base, "placements": [_external(), {**_external(position=2), "edition": 2}]}
        )
    with pytest.raises(ValidationError):
        CuratedDocumentAssemblyDraftV1.model_validate(
            {**base, "placements": [_item(position=1), _item(kind="REGISTERED_ITEM_REVISION")]}
        )
