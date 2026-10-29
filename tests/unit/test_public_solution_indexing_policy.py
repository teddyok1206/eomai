"""Public service policy and actual-owner seams; no deployment or IAM grants."""

from dataclasses import replace

import pytest
from eom_catalog_contracts.local_indexing_mixed_policy import (
    parse_supported_local_indexing_access_policy,
)
from eom_catalog_contracts.local_indexing_policy import LocalIndexingAccessPolicy
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_contracts.public_solution_indexing_policy import PublicSolutionIndexingAccessPolicy
from eom_catalog_contracts.segmented_local_indexing_policy import (
    parse_local_indexing_publication_policy,
)
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalApplicationService
from eom_identifiers import content_sha256

from tests.unit.test_local_indexing_policy_contracts import policy_document
from tests.unit.test_local_indexing_runtime_admission import installed as installed
from tests.unit.test_local_indexing_source_authority import MetadataSession
from tests.unit.test_local_indexing_source_authority import owner as owner
from tests.unit.test_postgres_local_indexing_fence import case as case
from tests.unit.test_public_solution_encoding import public_recipe


def public_policy_document(**changes):
    body = policy_document()
    recipe = public_recipe()
    old = body["namespaces"][0]
    namespace = PublicSolutionIndexNamespace(
        storage_partition=old["storage_partition"],
        space_sha256=old["space_sha256"],
        recipe_sha256=recipe.recipe_sha256,
    )
    body.update(
        schema_version="education-retrieval-access-policy/1.4",
        namespaces=[namespace.model_dump(mode="json")],
        recipe=recipe.model_dump(mode="json"),
        source_classes=["APPROVED_ITEM", "PAST_EXAM"],
        maximum_sources=16384,
        maximum_page_sources=1024,
        answer_bearing_use="VERIFIABLE_PUBLIC_SOLUTION_ONLY",
    )
    body.update(changes)
    body["content_sha256"] = content_sha256(
        {key: value for key, value in body.items() if key != "content_sha256"}
    )
    return body


def test_explicit_policy_dispatch_preserves_old_family_and_requires_new_scope():
    policy = PublicSolutionIndexingAccessPolicy.model_validate(public_policy_document())
    assert parse_supported_local_indexing_access_policy(policy) == policy
    assert parse_local_indexing_publication_policy(policy) == policy
    with pytest.raises(ValueError):
        LocalIndexingAccessPolicy.model_validate(policy.model_dump(mode="json"))
    with pytest.raises(ValueError):
        PublicSolutionIndexingAccessPolicy.model_validate(policy_document())


@pytest.mark.parametrize(
    "field,value",
    (
        ("maximum_sources", 16385),
        ("maximum_sources", True),
        ("maximum_page_sources", 1025),
        ("maximum_page_sources", 0),
        ("source_classes", ["TEXTBOOK"]),
        ("source_classes", ["PAST_EXAM", "APPROVED_ITEM"]),
        ("state", "ACTIVE"),
        ("answer_bearing_use", "ACCEPTED_SOLUTION_PROJECTION_ONLY"),
        ("purpose", "ITEM_PREPARATION"),
        ("roles", ["ADMIN"]),
        ("actor_context", {"role": "ADMIN"}),
    ),
)
def test_limits_and_actual_authority_cannot_be_widened_in_policy_fields(field, value):
    with pytest.raises(ValueError):
        PublicSolutionIndexingAccessPolicy.model_validate(public_policy_document(**{field: value}))


def test_same_actual_service_fence_and_source_policy_validate_public_pages(owner):
    policy = PublicSolutionIndexingAccessPolicy.model_validate(
        public_policy_document(
            service=owner.policy.service.model_dump(mode="json"),
            runtime_configuration_sha256=owner.policy.runtime_configuration_sha256,
        )
    )
    selection = replace(
        owner.intent,
        namespace=policy.namespaces[0],
        recipe=policy.recipe,
        source_classes=policy.source_classes,
        service_policy_sha256=policy.content_sha256,
    )
    owner.retrieval.resolve_local_indexing_access_policy.return_value = policy
    owner.retrieval.resolve_access_policy.return_value.allowed_source_classes = (
        policy.source_classes
    )
    session = MetadataSession(policy)
    assert owner.authority.authorize_scope(session, selection) == policy
    assert owner.iam.called
    assert (
        KnowledgeRetrievalApplicationService.resolve_local_indexing_access_policy(
            session, policy.access_policy_revision_id, sha256=policy.content_sha256
        )
        == policy
    )
