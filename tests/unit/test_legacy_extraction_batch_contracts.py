from __future__ import annotations

from datetime import UTC, datetime

import pytest
from eom_catalog_contracts import (
    LegacyCorpusSourceBinding,
    LegacyExtractionBatchWorkUnit,
    LegacyExtractionBatchWorkUnitV2,
    LegacyItemExtractionBatchManifest,
    LegacyItemExtractionBatchManifestV2,
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


def _inventory_pointer(seed: str, *, inventory_seed: str) -> dict[str, str]:
    return {
        "inventory_id": "legacyinventory_" + inventory_seed * 32,
        "inventory_sha256": "sha256:" + inventory_seed * 64,
        "entry_key": "legacyentry_" + seed * 32,
        "content_sha256": "sha256:" + seed * 64,
    }


def _manifest_v2() -> LegacyItemExtractionBatchManifestV2:
    request = _request()
    binding = LegacyCorpusSourceBinding(
        bundle_member_id="assessbundlemember_" + "8" * 32,
        reviewed_inventory_source=_inventory_pointer("9", inventory_seed="8"),
        corpus_inventory_source=_inventory_pointer("9", inventory_seed="c"),
    )
    unit = LegacyExtractionBatchWorkUnitV2(
        work_unit_id="legacyworkunit_" + "a" * 32,
        ordinal=0,
        request=request,
        expected_item_numbers_sha256=content_sha256({"item_numbers": [1]}),
        execution_mode="EXECUTE",
        reuse_accepted=None,
        corpus_source_bindings=(binding,),
    )
    value = {
        "schema_version": "legacy-item-extraction-batch/1.1",
        "extraction_batch_id": "legacybatch_" + "b" * 32,
        "idempotency_key": "full-corpus-v2",
        "inventory_id": "legacyinventory_" + "c" * 32,
        "inventory_sha256": "sha256:" + "c" * 64,
        "inventory_artifact": {
            "artifact_id": "artifact_" + "d" * 32,
            "artifact_revision_id": "rev_" + "d" * 32,
            "member_path": "legacy-source-inventory.json",
            "schema_ref": "eom://schemas/legacy-knowledge/legacy-source-inventory/2.0",
            "media_type": "application/json",
            "sha256": "sha256:" + "d" * 64,
        },
        "failure_policy": "CONTINUE_AND_COLLECT",
        "work_units": [unit.model_dump(mode="json")],
        "created_at": "2026-09-03T00:00:00Z",
        "manifest_sha256": "sha256:" + "0" * 64,
    }
    value["manifest_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "manifest_sha256"}
    )
    return LegacyItemExtractionBatchManifestV2.model_validate(value)


def test_batch_v2_is_schema_valid_and_binds_corpus_inventory() -> None:
    manifest = _manifest_v2()
    validate_contract("legacy-item-extraction-batch-v2", manifest.model_dump(mode="json"))
    binding = manifest.work_units[0].corpus_source_bindings[0]
    assert (
        binding.reviewed_inventory_source.content_sha256
        == binding.corpus_inventory_source.content_sha256
    )


def test_batch_v2_rejects_content_or_inventory_binding_drift() -> None:
    with pytest.raises(ValueError, match="content hashes differ"):
        LegacyCorpusSourceBinding(
            bundle_member_id="assessbundlemember_" + "8" * 32,
            reviewed_inventory_source=_inventory_pointer("9", inventory_seed="8"),
            corpus_inventory_source=_inventory_pointer("7", inventory_seed="c"),
        )

    value = _manifest_v2().model_dump(mode="python")
    value["work_units"][0]["corpus_source_bindings"][0]["corpus_inventory_source"][
        "inventory_id"
    ] = "legacyinventory_" + "e" * 32
    with pytest.raises(ValueError, match="does not belong"):
        LegacyItemExtractionBatchManifestV2.model_validate(value)
