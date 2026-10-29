"""Continuation pins preserve the original target set, policy and identity authority."""

from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_learning_cohort import (
    CREATIVE_COHORT_SCHEMA_REF,
    CreativeLearningCohort,
)
from eom_catalog_contracts.creative_learning_continuation import (
    CREATIVE_CONTINUATION_REF,
    CreativeLearningContinuation,
    CreativeLearningExecutionScope,
    validate_creative_continuation_parent,
)
from eom_catalog_service.creative_cohort_preparation import creative_cohort_workflow_key
from eom_catalog_service.creative_learning_cohort import read_creative_execution_scope
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer

from tests.unit.test_creative_learning_cohort import cohort_value


def continuation_case():
    parent = CreativeLearningCohort.model_validate(cohort_value())
    payload = canonical_json_bytes(parent.model_dump(mode="json"))
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
        member_path="cohort.json",
        schema_ref=CREATIVE_COHORT_SCHEMA_REF,
        media_type="application/json",
        sha256=sha256_bytes(payload),
    )
    body = {
        "schema_version": "creative-learning-continuation/1.0",
        "cohort_id": "creativecohort_" + "c" * 32,
        "parent_cohort": pointer.model_dump(mode="json"),
        "requested_by_operator_id": parent.requested_by_operator_id,
        "target_set_sha256": parent.target_set_sha256,
        "source_commit": "d" * 40,
        "workflow_definition_version": "2.0.0",
        "workflow_definition_sha256": "sha256:" + "e" * 64,
        "extraction_preset": {
            "preset_id": "execpreset_" + "f" * 32,
            "preset_revision_id": "execpresetrev_" + "1" * 32,
            "sha256": "sha256:" + "2" * 64,
        },
        "content_pack_release_id": "packrel_" + "3" * 32,
        "continuation_reason": "SOURCE_VISUAL_CONTRACT_SUCCESSOR",
    }
    continuation = CreativeLearningContinuation.model_validate(
        {**body, "cohort_sha256": content_sha256(body)}
    )
    return parent, pointer, continuation


def test_scope_reuses_the_exact_parent_targets_and_all_unchanged_policies():
    parent, pointer, continuation = continuation_case()
    original = parent.model_dump(mode="json")
    validate_creative_continuation_parent(continuation, parent, pointer)
    scope = CreativeLearningExecutionScope(parent, continuation)
    assert scope.cohort.targets is parent.targets
    assert "targets" not in continuation.model_dump(mode="json")
    assert len(continuation.model_dump_json()) < 4096
    assert scope.cohort.analysis_preset is parent.analysis_preset
    assert scope.cohort.capacity_policy_revision_id == parent.capacity_policy_revision_id
    assert scope.cohort.risk_policy_sha256 == parent.risk_policy_sha256
    assert scope.cohort.access_policy_sha256 == parent.access_policy_sha256
    assert scope.workflow_definition_version == "2.0.0"
    assert scope.workflow_definition_sha256 == continuation.workflow_definition_sha256
    assert scope.extraction_preset == continuation.extraction_preset
    assert scope.content_pack_release_id == continuation.content_pack_release_id
    assert parent.model_dump(mode="json") == original
    old = CreativeLearningExecutionScope(parent)
    assert old.workflow_definition_version == "1.0.0" and old.cohort_id == parent.cohort_id
    assert creative_cohort_workflow_key(parent, parent.targets[1]) != creative_cohort_workflow_key(
        parent, parent.targets[1], execution_cohort_id=scope.cohort_id
    )


@pytest.mark.parametrize("field", ["owner", "target", "parent", "self", "hash"])
def test_continuation_cannot_broaden_owner_or_target_set_or_replace_parent(field):
    parent, pointer, continuation = continuation_case()
    value = continuation.model_dump(mode="json")
    if field == "owner":
        value["requested_by_operator_id"] = "operator_" + "0" * 32
    elif field == "target":
        value["target_set_sha256"] = "sha256:" + "0" * 64
    elif field == "parent":
        value["parent_cohort"]["artifact_revision_id"] = "rev_" + "0" * 32
    elif field == "self":
        value["cohort_id"] = parent.cohort_id
    else:
        value["source_commit"] = "0" * 40
    if field != "hash":
        value["cohort_sha256"] = content_sha256(
            {k: v for k, v in value.items() if k != "cohort_sha256"}
        )
    with pytest.raises(ValueError):
        parsed = CreativeLearningContinuation.model_validate(value)
        validate_creative_continuation_parent(parsed, parent, pointer)


def reader_case():
    parent, pointer, continuation = continuation_case()
    parent_publication = NS(
        artifact_id=pointer.artifact_id,
        artifact_revision_id=pointer.artifact_revision_id,
        primary_file="cohort.json",
        primary_sha256=pointer.sha256,
    )
    data = canonical_json_bytes(continuation.model_dump(mode="json"))
    published = NS(
        artifact_id="artifact_" + "4" * 32,
        artifact_revision_id="rev_" + "5" * 32,
        primary_file="continuation.json",
        primary_sha256=sha256_bytes(data),
    )
    publisher = Mock()
    publisher.read_published_revision.side_effect = lambda **kwargs: (
        parent_publication
        if kwargs["artifact_revision_id"] == pointer.artifact_revision_id
        else published
    )
    artifacts = Mock()
    artifacts.read_member.side_effect = lambda **kwargs: (
        canonical_json_bytes(parent.model_dump(mode="json"))
        if kwargs["member_path"] == "cohort.json"
        else data
    )
    return NS(**locals())


def test_reader_resolves_exactly_one_parent_without_list_latest_or_target_copy():
    value = reader_case()
    scope, published = read_creative_execution_scope(
        value.artifacts, value.publisher, value.published.artifact_revision_id
    )
    assert scope.cohort == value.parent and scope.continuation == value.continuation
    assert published == value.published
    assert value.publisher.read_published_revision.call_count == 2
    assert (
        value.artifacts.read_member.call_args_list[0].kwargs["schema_ref"]
        == CREATIVE_CONTINUATION_REF
    )
    assert value.artifacts.read_member.call_args_list[1].kwargs["sha256"] == value.pointer.sha256


def test_base_cohort_read_remains_the_same_contract():
    value = reader_case()
    scope, published = read_creative_execution_scope(
        value.artifacts, value.publisher, value.pointer.artifact_revision_id
    )
    assert scope.cohort == value.parent and scope.continuation is None
    assert published.primary_file == "cohort.json"
    value.artifacts.read_member.assert_called_once()


def test_missing_or_hash_invalid_parent_is_not_replaced_by_current():
    value = reader_case()
    original = value.artifacts.read_member.side_effect

    def broken(**kwargs):
        if kwargs["member_path"] == "cohort.json":
            raise ValueError("HASH_MISMATCH")
        return original(**kwargs)

    value.artifacts.read_member.side_effect = broken
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        read_creative_execution_scope(
            value.artifacts, value.publisher, value.published.artifact_revision_id
        )
    assert value.publisher.read_published_revision.call_count == 2


def test_continuation_schema_is_frozen_and_package_exact():
    from hashlib import sha256

    root = Path(__file__).resolve().parents[2]
    relative = "external-item/creative-learning-continuation-v1.schema.json"
    canonical = root / "schemas" / relative
    assert (
        canonical.read_bytes()
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts/resources" / relative
        ).read_bytes()
    )
    assert (
        sha256(canonical.read_bytes()).hexdigest()
        == "b6849b0872634dfb07c0463b3e9bf40af542deefde8a2ba0b81e258be85aba2e"
    )
    _parent, _pointer, continuation = continuation_case()
    assert (
        CreativeLearningContinuation.model_validate_json(continuation.model_dump_json())
        == continuation
    )
    with pytest.raises(ValueError):
        continuation.source_commit = "0" * 40
