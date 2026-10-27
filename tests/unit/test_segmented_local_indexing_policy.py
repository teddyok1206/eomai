"""Schema-first candidate only; current 1.1/1.2 policy dispatch stays closed."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest
from eom_catalog_contracts import load_schema, validate_contract
from eom_catalog_contracts.local_indexing_mixed_policy import (
    LocalIndexingMixedAccessPolicy,
    parse_supported_local_indexing_access_policy,
)
from eom_catalog_contracts.segmented_local_indexing_policy import (
    SEGMENTED_LOCAL_INDEXING_POLICY_SCHEMA,
    SegmentedLocalIndexingAccessPolicy,
    local_indexing_publication_policy_bytes,
    parse_local_indexing_publication_policy,
    parse_segmented_local_indexing_access_policy,
    segmented_local_indexing_policy_bytes,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalServiceError,
)
from eom_catalog_service.local_indexing_policy_publication import (
    LocalIndexingPolicyPublicationError,
    publish_local_indexing_access_policy,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from sqlalchemy.orm import Session

from tests.unit.test_local_indexing_mixed_policy import mixed_policy_document
from tests.unit.test_local_indexing_source_authority import MetadataSession


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
    assert parse_local_indexing_publication_policy(policy) == policy
    assert local_indexing_publication_policy_bytes(policy) == canonical_json_bytes(body)
    old = LocalIndexingMixedAccessPolicy.model_validate(mixed_policy_document())
    assert parse_local_indexing_publication_policy(old) == old
    assert local_indexing_publication_policy_bytes(old) == canonical_json_bytes(
        old.model_dump(mode="json")
    )
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


def test_owner_publication_still_requires_real_postgres_root() -> None:
    policy = SegmentedLocalIndexingAccessPolicy.model_validate(candidate_document())
    with Session() as session, pytest.raises(LocalIndexingPolicyPublicationError) as caught:
        publish_local_indexing_access_policy(session, policy)
    assert caught.value.code == "LOCAL_INDEXING_POLICY_CONTEXT_INVALID"
    forged = policy.model_copy(update={"injected_authority": "ADMIN"})
    with Session() as session, pytest.raises(ValueError):
        publish_local_indexing_access_policy(session, forged)
    assert session.get_transaction() is None


def test_pinned_segmented_read_is_distinct_from_existing_runtime_reader() -> None:
    policy = SegmentedLocalIndexingAccessPolicy.model_validate(candidate_document())
    session = MetadataSession(policy)  # type: ignore[arg-type]
    actual = KnowledgeRetrievalApplicationService.resolve_segmented_local_indexing_access_policy(
        cast(Session, session), policy.access_policy_revision_id, sha256=policy.content_sha256
    )
    assert actual == policy
    assert session.calls[0]._for_update_arg is None
    with pytest.raises(KnowledgeRetrievalServiceError) as caught:
        KnowledgeRetrievalApplicationService.resolve_local_indexing_access_policy(
            cast(Session, session), policy.access_policy_revision_id, sha256=policy.content_sha256
        )
    assert caught.value.code == "KNOWLEDGE_RETRIEVAL_POLICY_INVALID"


@pytest.mark.parametrize("fault", ("schema", "state", "hash", "document"))
def test_segmented_reader_rejects_stale_or_forged_metadata(fault: str) -> None:
    policy = SegmentedLocalIndexingAccessPolicy.model_validate(candidate_document())
    session = MetadataSession(policy)  # type: ignore[arg-type]
    if fault == "schema":
        session.policy.schema_version = "education-retrieval-access-policy/1.2"
    elif fault == "state":
        session.policy.state = "RETIRED"
    elif fault == "hash":
        session.policy.content_sha256 = "sha256:" + "f" * 64
    else:
        session.policy.canonical_document["maximum_page_sources"] = 8
    with pytest.raises(KnowledgeRetrievalServiceError):
        KnowledgeRetrievalApplicationService.resolve_segmented_local_indexing_access_policy(
            cast(Session, session), policy.access_policy_revision_id, sha256=policy.content_sha256
        )
