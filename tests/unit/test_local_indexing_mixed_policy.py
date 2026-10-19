"""Synthetic policy successors and owner seams, not installed IAM or source grants."""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import load_schema, validate_contract
from eom_catalog_contracts.local_indexing_mixed_policy import (
    LOCAL_INDEXING_MIXED_POLICY_SCHEMA,
    LocalIndexingMixedAccessPolicy,
    parse_local_indexing_mixed_access_policy,
    parse_supported_local_indexing_access_policy,
    supported_local_indexing_access_policy_bytes,
)
from eom_catalog_contracts.local_indexing_policy import (
    LocalIndexingAccessPolicy,
    require_local_indexing_source_policy,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_catalog_service import local_indexing_policy_publication as publication
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalServiceError,
)
from eom_catalog_service.local_indexing_source_ports import LocalIndexingSourceError
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.orm import Session

from tests.unit.test_local_indexing_policy_contracts import policy_document
from tests.unit.test_local_indexing_policy_publication import source_policy
from tests.unit.test_local_indexing_runtime_admission import installed as installed
from tests.unit.test_local_indexing_service_contracts import identity
from tests.unit.test_local_indexing_source_authority import MetadataSession
from tests.unit.test_local_indexing_source_authority import owner as owner
from tests.unit.test_postgres_local_indexing_fence import case as case


def mixed_policy_document(**changes):
    body = policy_document()
    body.update(
        schema_version="education-retrieval-access-policy/1.2",
        source_classes=["APPROVED_ITEM", "PAST_EXAM"],
        answer_bearing_use="ACCEPTED_SOLUTION_OR_REGISTERED_REVIEW_PROJECTION_ONLY",
    )
    body["namespaces"][0]["projection_version"] = "mixed-solution-comparison/2.0"
    body["namespaces"][0]["population_scope"] = "ALL_ADMITTED_GRAPH_ITEMS"
    body.update(changes)
    body["content_sha256"] = content_sha256(
        {key: value for key, value in body.items() if key != "content_sha256"}
    )
    return body


def mixed_policy():
    return LocalIndexingMixedAccessPolicy.model_validate(mixed_policy_document())


def upgrade_owner(owner):
    body = mixed_policy_document(
        service=owner.policy.service.model_dump(mode="json"),
        runtime_configuration_sha256=owner.policy.runtime_configuration_sha256,
    )
    policy = LocalIndexingMixedAccessPolicy.model_validate(body)
    owner.policy = policy
    owner.intent = replace(
        owner.intent,
        namespace=policy.namespaces[0],
        source_classes=policy.source_classes,
        service_policy_sha256=policy.content_sha256,
    )
    owner.session = MetadataSession(policy)
    owner.retrieval.resolve_local_indexing_access_policy.return_value = policy
    owner.retrieval.resolve_access_policy.return_value.allowed_source_classes = (
        policy.source_classes
    )
    return owner


def test_schema_first_mirror_hash_and_closed_legacy_dispatch():
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES[LOCAL_INDEXING_MIXED_POLICY_SCHEMA]
    raw = (root / entry.canonical_path).read_bytes()
    assert sha256_bytes(raw) == entry.sha256
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    Draft202012Validator.check_schema(load_schema(LOCAL_INDEXING_MIXED_POLICY_SCHEMA))
    body = mixed_policy_document()
    validate_contract(LOCAL_INDEXING_MIXED_POLICY_SCHEMA, body)
    policy = mixed_policy()
    canonical = canonical_json_bytes(body)
    assert supported_local_indexing_access_policy_bytes(policy) == canonical
    assert parse_local_indexing_mixed_access_policy(canonical) == policy
    assert parse_supported_local_indexing_access_policy(policy) == policy
    old = LocalIndexingAccessPolicy.model_validate(policy_document())
    assert parse_supported_local_indexing_access_policy(old) == old
    assert type(parse_supported_local_indexing_access_policy(old)) is LocalIndexingAccessPolicy
    with pytest.raises(ValueError):
        LocalIndexingAccessPolicy.model_validate(body)
    with pytest.raises(ValueError):
        LocalIndexingMixedAccessPolicy.model_validate(old)


@pytest.mark.parametrize(
    "field,value",
    (
        ("schema_version", "education-retrieval-access-policy/1.3"),
        ("answer_bearing_use", "ACCEPTED_SOLUTION_PROJECTION_ONLY"),
        ("maximum_sources", True),
        ("maximum_sources", 1025),
        ("maximum_sources", 0),
        ("source_classes", ["TEXTBOOK"]),
        ("source_classes", ["PAST_EXAM", "APPROVED_ITEM"]),
        ("source_classes", ["APPROVED_ITEM", "APPROVED_ITEM"]),
        ("purpose", "ITEM_PREPARATION"),
        ("state", "ACTIVE"),
        ("runtime_configuration_sha256", "latest"),
        ("created_at", "2026-10-19T09:00:00+09:00"),
        ("source_access_policy_revision_id", "accessrev_" + "e" * 32),
        ("roles", ["ADMIN"]),
        ("token", "SECRET_MARKER"),
    ),
)
def test_closed_source_use_version_budget_and_non_authority_fields(field, value):
    body = mixed_policy_document(**{field: value})
    # UTC and sorted semantic equality additionally belong to the frozen model;
    # the reused released timestamp schema admits ISO offsets syntactically.
    if field not in {"source_access_policy_revision_id", "created_at"} and not (
        field == "source_classes" and value == ["PAST_EXAM", "APPROVED_ITEM"]
    ):
        with pytest.raises(SchemaError):
            validate_contract(LOCAL_INDEXING_MIXED_POLICY_SCHEMA, body)
    with pytest.raises(ValueError) as caught:
        LocalIndexingMixedAccessPolicy.model_validate(body)
    assert "SECRET_MARKER" not in str(caught.value)


@pytest.mark.parametrize("fault", ("legacy", "occurrence", "space", "recipe", "partition", "views"))
def test_namespaces_are_only_ordered_mixed_all_same_space_recipe_partition(fault):
    body = mixed_policy_document()
    first = body["namespaces"][0]
    second = {**first, "view": "METADATA_ONLY"}
    if fault == "legacy":
        first["projection_version"] = "accepted-solution-comparison/1.0"
    elif fault == "occurrence":
        first["population_scope"] = "OCCURRENCE_BACKED_PAST_EXAM"
    elif fault in {"space", "recipe"}:
        first[fault + "_sha256"] = "sha256:" + "f" * 64
    elif fault == "partition":
        second["storage_partition"] = "another"
    else:
        second["view"] = first["view"]
    with pytest.raises(ValueError):
        LocalIndexingMixedAccessPolicy.model_validate(
            mixed_policy_document(namespaces=[first, second])
        )


def test_copied_and_constructed_nested_values_and_hash_cannot_bypass_schema():
    policy = mixed_policy()
    forged = (
        policy.model_copy(update={"token": "SECRET_MARKER"}),
        policy.model_copy(update={"maximum_sources": 1}),
        policy.model_copy(
            update={"service": policy.service.model_copy(update={"roles": ["ADMIN"]})}
        ),
        policy.model_copy(update={"space": policy.space.model_copy(update={"roles": ["ADMIN"]})}),
        policy.model_copy(update={"recipe": policy.recipe.model_copy(update={"roles": ["ADMIN"]})}),
        policy.model_copy(
            update={"namespaces": (policy.namespaces[0].model_copy(update={"roles": ["ADMIN"]}),)}
        ),
        LocalIndexingMixedAccessPolicy.model_construct(
            **{**policy.__dict__, "maximum_sources": True}
        ),
    )
    for value in forged:
        with pytest.raises(ValueError):
            supported_local_indexing_access_policy_bytes(value)
    for field in type(policy).model_fields:
        body = deepcopy(mixed_policy_document())
        del body[field]
        with pytest.raises(ValueError):
            LocalIndexingMixedAccessPolicy.model_validate(body)


@pytest.mark.parametrize(
    "raw", (b"", b"{}", b"[]", b"null", b"\xff", b'{"a":1,"a":2}', b'{"a":NaN}', b"x" * 65537)
)
def test_wire_decode_is_bounded_duplicate_free_and_canonical(raw):
    with pytest.raises(ValueError):
        parse_local_indexing_mixed_access_policy(raw)
    with pytest.raises(ValueError):
        parse_local_indexing_mixed_access_policy(
            b" " + supported_local_indexing_access_policy_bytes(mixed_policy())
        )


def test_pinned_source_policy_is_not_broadened_to_make_mixed_policy_work():
    source = source_policy(allowed_source_classes=["APPROVED_ITEM", "PAST_EXAM"])
    policy = LocalIndexingMixedAccessPolicy.model_validate(
        mixed_policy_document(
            source_access_policy_revision_id=source.access_policy_revision_id,
            source_access_policy_sha256=source.content_sha256,
        )
    )
    assert require_local_indexing_source_policy(policy, source) is None
    restricted = source_policy()
    policy = LocalIndexingMixedAccessPolicy.model_validate(
        mixed_policy_document(
            source_access_policy_revision_id=restricted.access_policy_revision_id,
            source_access_policy_sha256=restricted.content_sha256,
        )
    )
    with pytest.raises(ValueError):
        require_local_indexing_source_policy(policy, restricted)


def test_actual_reader_and_source_authority_keep_current_iam_and_pinned_metadata(owner):
    owner = upgrade_owner(owner)
    actual = KnowledgeRetrievalApplicationService.resolve_local_indexing_access_policy(
        owner.session, owner.policy.access_policy_revision_id, sha256=owner.policy.content_sha256
    )
    assert actual == owner.policy and type(actual) is LocalIndexingMixedAccessPolicy
    assert len(owner.session.calls) == 1
    assert owner.session.calls[0]._for_update_arg is None
    assert owner.session.calls[0].get_execution_options()["populate_existing"]
    owner.session.calls.clear()
    assert owner.authority.authorize_scope(owner.session, owner.intent) == owner.policy
    owner.iam.assert_called_once_with(owner.session)
    assert len(owner.session.calls) == 2
    assert owner.session.calls[0]._for_update_arg.read
    owner.retrieval.resolve_access_policy.assert_called_once_with(
        owner.session,
        owner.policy.source_access_policy_revision_id,
        sha256=owner.policy.source_access_policy_sha256,
    )


@pytest.mark.parametrize(
    "fault", ("source_class", "runtime", "namespace", "metadata_schema", "hash", "state")
)
def test_mixed_reader_and_gate_never_fall_back_or_borrow_legacy_permission(owner, fault):
    owner = upgrade_owner(owner)
    if fault in {"metadata_schema", "hash", "state"}:
        if fault == "metadata_schema":
            owner.session.policy.schema_version = "education-retrieval-access-policy/1.1"
        elif fault == "hash":
            owner.session.policy.content_sha256 = "sha256:" + "f" * 64
        else:
            owner.session.policy.state = "RETIRED"
        with pytest.raises(KnowledgeRetrievalServiceError):
            KnowledgeRetrievalApplicationService.resolve_local_indexing_access_policy(
                owner.session,
                owner.policy.access_policy_revision_id,
                sha256=owner.policy.content_sha256,
            )
    else:
        if fault == "source_class":
            owner.retrieval.resolve_access_policy.return_value.allowed_source_classes = (
                "PAST_EXAM",
            )
        elif fault == "runtime":
            changed = owner.policy.model_dump(mode="json")
            changed["runtime_configuration_sha256"] = "sha256:" + "f" * 64
            owner.retrieval.resolve_local_indexing_access_policy.return_value = (
                LocalIndexingMixedAccessPolicy.model_validate(mixed_policy_document(**changed))
            )
        else:
            old = LocalIndexingAccessPolicy.model_validate(policy_document())
            owner.intent = replace(owner.intent, namespace=old.namespaces[0])
        with pytest.raises(LocalIndexingSourceError, match="FORBIDDEN"):
            owner.authority.authorize_scope(owner.session, owner.intent)


def test_copied_extra_namespace_is_rejected_by_read_intent_before_any_authority(owner):
    owner = upgrade_owner(owner)
    with pytest.raises(LocalIndexingSourceError, match="SCOPE_INVALID"):
        replace(
            owner.intent, namespace=owner.intent.namespace.model_copy(update={"roles": ["ADMIN"]})
        )
    owner.iam.assert_not_called()


def test_new_policy_publication_retains_no_implicit_root_or_sqlite_fallback():
    with (
        Session() as session,
        pytest.raises(publication.LocalIndexingPolicyPublicationError) as caught,
    ):
        publication.publish_local_indexing_access_policy(session, mixed_policy())
    assert caught.value.code == "LOCAL_INDEXING_POLICY_CONTEXT_INVALID"
    with Session() as session, pytest.raises(ValueError):
        publication.publish_local_indexing_access_policy(
            session, mixed_policy().model_copy(update={"roles": ["ADMIN"]})
        )
    assert session.get_transaction() is None


@pytest.mark.parametrize("replay", (False, True))
@pytest.mark.parametrize("fault", (None, "document", "schema", "hash", "extra"))
def test_publication_closed_dispatch_reuses_existing_identity_source_and_replay_logic(
    monkeypatch, replay, fault
):
    policy = mixed_policy()
    principal = "synthetic_owner"
    record = SimpleNamespace(
        schema_version=policy.schema_version,
        state=policy.state,
        content_sha256=policy.content_sha256,
        canonical_document=policy.model_dump(mode="json"),
        created_by=principal,
        created_at=policy.created_at,
    )
    if fault == "document":
        record.canonical_document["maximum_sources"] = 1
    elif fault == "schema":
        record.schema_version = "education-retrieval-access-policy/1.1"
    elif fault == "hash":
        record.content_sha256 = "sha256:" + "f" * 64
    elif fault == "extra":
        record.canonical_document["roles"] = ["ADMIN"]
    session = SimpleNamespace(
        scalar=Mock(
            side_effect=[
                SimpleNamespace(lifecycle_state="ACTIVE", graph_id=policy.graph_id),
                None if replay else policy.access_policy_revision_id,
                record,
            ]
        ),
        begin_nested=Mock(side_effect=lambda: nullcontext()),
    )
    monkeypatch.setattr(publication, "_publication_root", lambda _session: nullcontext(principal))
    current = Mock(return_value=identity())
    monkeypatch.setattr(publication, "lock_current_local_indexing_service_metadata", current)
    source = SimpleNamespace(
        access_policy_revision_id=policy.source_access_policy_revision_id,
        content_sha256=policy.source_access_policy_sha256,
        allowed_source_classes=policy.source_classes,
        allowed_query_kinds=("ITEM_PREPARATION",),
        answer_bearing_roles=("EDITOR",),
        maximum_budget=SimpleNamespace(max_item_revisions=64),
    )
    source_owner = Mock(return_value=source)
    monkeypatch.setattr(
        KnowledgeRetrievalApplicationService, "lock_source_access_policy", source_owner
    )
    if fault is None:
        result = publication.publish_local_indexing_access_policy(session, policy)
        assert result.created is not replay and result.policy_sha256 == policy.content_sha256
        assert result.published_by == principal
    else:
        with pytest.raises(publication.LocalIndexingPolicyPublicationError) as caught:
            publication.publish_local_indexing_access_policy(session, policy)
        assert caught.value.code in {
            "LOCAL_INDEXING_POLICY_PUBLICATION_CONFLICT",
            "LOCAL_INDEXING_POLICY_SCOPE_INVALID",
        }
    current.assert_called_once_with(session, policy.service)
    source_owner.assert_called_once_with(
        session, policy.source_access_policy_revision_id, sha256=policy.source_access_policy_sha256
    )
    assert session.scalar.call_count == 3 and session.begin_nested.call_count == 1
