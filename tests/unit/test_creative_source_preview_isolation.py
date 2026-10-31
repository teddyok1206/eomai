"""A bad original cannot starve other slots, erase history or masquerade as accepted."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_preview_preparation import CreativePreviewPreparationResult
from eom_catalog_contracts.validation import load_schema
from eom_catalog_service.creative_preview_preparation import CreativeSourcePreviewDeferred
from jsonschema import Draft202012Validator

from tests.unit.test_creative_parallel_execution import driver_case


def deferred(source, **changes):
    return CreativeSourcePreviewDeferred(
        CreativePreviewPreparationResult.model_validate(
            {
                "source_id": source.target.source_id,
                "source_revision_id": source.target.source_revision_id,
                "edition": source.target.selected_edition,
                "status": "DEFERRED",
                "error_code": "OFFICE_DOCUMENT_CONVERSION_OUTPUT_MISSING",
                **changes,
            }
        )
    )


def test_one_bad_original_is_not_accepted_and_other_sources_finish_once(monkeypatch):
    case = driver_case(monkeypatch, count=11)
    attempted = []

    def advance(source):
        attempted.append(source.target.source_id)
        if source.target.source_id == case.targets[0].source_id:
            raise deferred(source)
        source.state = "READY_TO_PUBLISH"

    case.owner.advance_report = Mock(side_effect=advance)
    for _ in range(12):
        result = case.driver.advance_once()
        if case.executor.pending:
            case.executor.complete()
        if result.state == "BLOCKED_SOURCES":
            break
    assert result.state == "BLOCKED_SOURCES"
    assert result.verified_count == 10 and len(result.blocked_sources) == 1
    assert len(attempted) == len(set(attempted)) == 11
    assert result.blocked_sources == (
        (case.targets[0].external_number, "OFFICE_DOCUMENT_CONVERSION_OUTPUT_MISSING"),
    )
    assert case.owner.targets == case.targets
    case.driver.close()


def test_all_bad_originals_terminate_without_spinning_or_false_completion(monkeypatch):
    case = driver_case(monkeypatch, count=11)
    case.owner.advance_report = Mock(
        side_effect=lambda source: (_ for _ in ()).throw(deferred(source))
    )
    case.driver.advance_once()
    result = case.driver.advance_once()
    assert result.state == "BLOCKED_SOURCES" and result.verified_count == 0
    assert len(result.blocked_sources) == 11
    assert case.owner.advance_report.call_count == 11
    assert case.executor.calls == 0
    case.driver.close()


@pytest.mark.parametrize("fault", ["authority", "hash", "foreign_revision", "foreign_edition"])
def test_unrelated_or_foreign_failure_still_stops_instead_of_becoming_a_skip(monkeypatch, fault):
    case = driver_case(monkeypatch)

    def advance(source):
        if fault == "authority":
            raise ValueError("SOURCE_PERMISSION_DENIED")
        if fault == "hash":
            raise ValueError("SOURCE_HASH_MISMATCH")
        raise deferred(
            source,
            **(
                {"source_revision_id": "extitemrev_" + "f" * 32}
                if fault == "foreign_revision"
                else {"edition": 1}
            ),
        )

    case.owner.advance_report = Mock(side_effect=advance)
    with pytest.raises(ValueError):
        case.driver.advance_once()
    assert not case.driver.blocked and case.driver.verified_count == 0
    case.driver.close()


def test_result_schema_is_packaged_identically_and_only_known_source_error_is_deferred():
    schema = load_schema("creative-preview-preparation-result-v1")
    Draft202012Validator.check_schema(schema)
    repository = Path(__file__).resolve().parents[2]
    canonical = (
        repository / "schemas/external-item/creative-preview-preparation-result-v1.schema.json"
    )
    packaged = (
        repository
        / "packages/catalog_contracts/eom_catalog_contracts/resources"
        / "external-item/creative-preview-preparation-result-v1.schema.json"
    )
    assert canonical.read_bytes() == packaged.read_bytes()
    value = {
        "schema_version": "creative-preview-preparation-result/1.0",
        "source_id": "extitem_" + "a" * 32,
        "source_revision_id": "extitemrev_" + "b" * 32,
        "edition": 3,
        "status": "DEFERRED",
        "error_code": "OFFICE_DOCUMENT_CONVERSION_OUTPUT_MISSING",
    }
    assert CreativePreviewPreparationResult.model_validate(value).status == "DEFERRED"
    for changes in (
        {"error_code": "SOURCE_PERMISSION_DENIED"},
        {"status": "READY"},
        {"edition": True},
        {"override": True},
    ):
        with pytest.raises(ValueError):
            CreativePreviewPreparationResult.model_validate(value | changes)
        assert not Draft202012Validator(schema).is_valid(value | changes)
