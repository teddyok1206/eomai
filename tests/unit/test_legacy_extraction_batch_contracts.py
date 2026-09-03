from __future__ import annotations

from datetime import UTC, datetime

import pytest
from eom_catalog_contracts import (
    LegacyExtractionBatchWorkUnit,
    LegacyItemExtractionBatchManifest,
    validate_contract,
)
from eom_identifiers import content_sha256
from test_legacy_item_extraction_service import _request


def _work_unit(*, seed: str = "a", ordinal: int = 0) -> LegacyExtractionBatchWorkUnit:
    request = _request(seed=seed)
    return LegacyExtractionBatchWorkUnit(
        work_unit_id="legacyworkunit_" + seed * 32,
        ordinal=ordinal,
        request=request,
        expected_item_numbers_sha256=content_sha256({"item_numbers": [1]}),
        execution_mode="EXECUTE",
        reuse_accepted=None,
    )


def _manifest() -> LegacyItemExtractionBatchManifest:
    value = {
        "schema_version": "legacy-item-extraction-batch/1.0",
        "extraction_batch_id": "legacybatch_" + "b" * 32,
        "idempotency_key": "full-scope-test",
        "inventory_id": "legacyinventory_" + "c" * 32,
        "inventory_sha256": "sha256:" + "d" * 64,
        "failure_policy": "CONTINUE_AND_COLLECT",
        "work_units": [_work_unit()],
        "created_at": datetime(2026, 9, 3, tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        "manifest_sha256": "sha256:" + "0" * 64,
    }
    hash_payload = {
        key: ([unit.model_dump(mode="json") for unit in item] if key == "work_units" else item)
        for key, item in value.items()
        if key != "manifest_sha256"
    }
    value["manifest_sha256"] = content_sha256(hash_payload)
    return LegacyItemExtractionBatchManifest.model_validate(value)


def test_batch_manifest_is_schema_valid_and_hash_bound() -> None:
    manifest = _manifest()
    validate_contract("legacy-item-extraction-batch", manifest.model_dump(mode="json"))
    assert manifest.work_units[0].request.extraction_request_id.startswith("itemextractreq_")


def test_batch_rejects_non_contiguous_or_duplicate_work_units() -> None:
    first = _work_unit()
    with pytest.raises(ValueError, match="unique"):
        value = _manifest().model_dump(mode="python")
        second = _work_unit(seed="e")
        second = second.model_copy(
            update={
                "work_unit_id": first.work_unit_id,
                "ordinal": 1,
                "request": second.request.model_copy(update={"work_unit_ordinal": 1}),
            }
        )
        second_request = second.request.model_dump(mode="json")
        second = second.model_copy(
            update={
                "request": second.request.model_copy(
                    update={
                        "request_sha256": content_sha256(
                            {
                                key: item
                                for key, item in second_request.items()
                                if key != "request_sha256"
                            }
                        )
                    }
                )
            }
        )
        value["work_units"] = [first.model_dump(mode="python"), second.model_dump(mode="python")]
        value["manifest_sha256"] = content_sha256(
            {
                key: (
                    [first.model_dump(mode="json"), second.model_dump(mode="json")]
                    if key == "work_units"
                    else item
                )
                for key, item in value.items()
                if key != "manifest_sha256"
            }
        )
        LegacyItemExtractionBatchManifest.model_validate(value)
