"""Schema-first candidate only; current 1.1/1.2 policy dispatch stays closed."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts import load_schema, validate_contract
from eom_catalog_contracts.local_indexing_mixed_policy import (
    LocalIndexingMixedAccessPolicy,
    parse_supported_local_indexing_access_policy,
)
from eom_catalog_contracts.segmented_local_indexing_policy import (
    SEGMENTED_LOCAL_INDEXING_POLICY_SCHEMA,
    SegmentedLocalIndexingAccessPolicy,
    parse_segmented_local_indexing_access_policy,
    segmented_local_indexing_policy_bytes,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator

from tests.unit.test_local_indexing_mixed_policy import mixed_policy_document


def candidate_document(**changes: object) -> dict[str, object]:
    body: dict[str, object] = deepcopy(mixed_policy_document())
    body["schema_version"] = "education-retrieval-access-policy/1.3"
    body.pop("maximum_sources")
    body["maximum_page_sources"] = 1024
    body["maximum_population_sources"] = 10000
    body.update(changes)
    body["content_sha256"] = content_sha256(
        {key: value for key, value in body.items() if key != "content_sha256"}
    )
    return body


def test_mirrored_schema_and_frozen_value_do_not_activate_old_dispatch() -> None:
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES[SEGMENTED_LOCAL_INDEXING_POLICY_SCHEMA]
    raw = (root / entry.canonical_path).read_bytes()
    assert sha256_bytes(raw) == entry.sha256
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    Draft202012Validator.check_schema(load_schema(SEGMENTED_LOCAL_INDEXING_POLICY_SCHEMA))
    body = candidate_document()
    validate_contract(SEGMENTED_LOCAL_INDEXING_POLICY_SCHEMA, body)
    policy = SegmentedLocalIndexingAccessPolicy.model_validate(body)
    assert policy.maximum_page_sources == 1024
    assert policy.maximum_population_sources == 10000
    assert segmented_local_indexing_policy_bytes(policy) == canonical_json_bytes(body)
    assert parse_segmented_local_indexing_access_policy(canonical_json_bytes(body)) == policy
    with pytest.raises(ValueError):
        parse_supported_local_indexing_access_policy(body)
    with pytest.raises(ValueError):
        LocalIndexingMixedAccessPolicy.model_validate(body)


@pytest.mark.parametrize(
    "change",
    (
        {"maximum_page_sources": 1025},
        {"maximum_page_sources": 0},
        {"maximum_population_sources": 1024},
        {"maximum_population_sources": 1048577},
        {"maximum_page_sources": 8, "maximum_population_sources": 10000},
        {"maximum_page_sources": True},
        {"maximum_population_sources": True},
        {"maximum_sources": 1024},
    ),
)
def test_limits_and_predecessor_field_are_not_interchangeable(
    change: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        SegmentedLocalIndexingAccessPolicy.model_validate(candidate_document(**change))


def test_canonical_bytes_and_member_scope_are_closed() -> None:
    raw = canonical_json_bytes(candidate_document())
    with pytest.raises(ValueError):
        parse_segmented_local_indexing_access_policy(b" " + raw)
    with pytest.raises(ValueError):
        SegmentedLocalIndexingAccessPolicy.model_validate(
            candidate_document(source_classes=["PAST_EXAM", "APPROVED_ITEM"])
        )
    with pytest.raises(ValueError):
        SegmentedLocalIndexingAccessPolicy.model_validate(
            candidate_document(source_access_policy_revision_id="accessrev_" + "e" * 32)
        )
