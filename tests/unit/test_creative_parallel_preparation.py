"""Purpose admission references the original source/owner and is exactly replayable."""

from contextlib import nullcontext
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_learning_continuation import (
    CreativeLearningExecutionScope,
    CreativeLearningParallelContinuation,
)
from eom_catalog_service import creative_continuation_preparation as preparation

from tests.unit.test_creative_learning_parallel_continuation import parallel_case
from tests.unit.test_creative_registered_report import proposal


def case(monkeypatch, tmp_path):
    previous, pointer, value = parallel_case()
    parallel = CreativeLearningParallelContinuation.model_validate(value)
    session = Mock()
    sessions = Mock(return_value=nullcontext(session))
    monkeypatch.setattr(preparation, "build_session_factory", lambda _engine: sessions)
    artifacts = Mock()
    publisher = Mock()
    publisher.find_published.return_value = None
    monkeypatch.setattr(preparation, "CatalogArtifactService", lambda *args: artifacts)
    monkeypatch.setattr(preparation, "ControlFileSetPublisher", lambda *args: publisher)
    monkeypatch.setattr(preparation, "ControlArtifactPublisher", lambda *args: object())
    resolved, _ = proposal()
    monkeypatch.setattr(
        preparation, "resolve_completed_creative_learning_proposal", lambda *args: resolved
    )
    authorizer = Mock()
    monkeypatch.setattr(
        preparation, "CatalogExternalItemLearningSourceAuthorizer", lambda *args: authorizer
    )
    monkeypatch.setattr(
        preparation, "ExternalItemPreviewProjectionService", lambda *args, **kwargs: object()
    )
    monkeypatch.setattr(
        preparation, "effective_permissions", lambda *args: preparation._PERMISSIONS
    )
    publication = NS(
        artifact_id=pointer.artifact_id,
        artifact_revision_id=pointer.artifact_revision_id,
        primary_file=pointer.member_path,
        primary_sha256=pointer.sha256,
    )
    stored = {}

    def read(_artifacts, _publisher, revision):
        if revision == pointer.artifact_revision_id:
            return previous, publication
        return stored["scope"], stored["publication"]

    monkeypatch.setattr(preparation, "read_creative_execution_scope", read)
    controls = Mock(
        return_value=NS(
            extraction=NS(
                preset_id=parallel.extraction_preset.preset_id,
                preset_revision_id=parallel.extraction_preset.preset_revision_id,
                content_sha256=parallel.extraction_preset.sha256,
            ),
            analysis=NS(
                preset_id=parallel.analysis_preset.preset_id,
                preset_revision_id=parallel.analysis_preset.preset_revision_id,
                content_sha256=parallel.analysis_preset.sha256,
            ),
            capacity=NS(
                capacity_policy_id=parallel.capacity_policy.capacity_policy_id,
                capacity_policy_revision_id=parallel.capacity_policy.capacity_policy_revision_id,
                content_sha256=parallel.capacity_policy.sha256,
            ),
        )
    )
    monkeypatch.setattr(preparation, "release_creative_parallel_controls", controls)

    def publish(**kwargs):
        document = CreativeLearningParallelContinuation.model_validate_json(
            kwargs["members"][0].source.read_bytes()
        )
        stored["scope"] = CreativeLearningExecutionScope(previous.cohort, document, previous)
        stored["publication"] = NS(artifact_revision_id="rev_" + "f" * 32)
        publisher.find_published.return_value = stored["publication"]
        return stored["publication"]

    publisher.publish_first_observation.side_effect = publish
    args = dict(
        predecessor_revision_id=pointer.artifact_revision_id,
        source_commit="a" * 40,
        settings=NS(staging_root=tmp_path),
        catalog_settings=object(),
    )
    return NS(**locals())


def test_exact_admitted_owner_replays_one_successor_without_copying_targets(monkeypatch, tmp_path):
    value = case(monkeypatch, tmp_path)
    scope, published = preparation.prepare_creative_parallel_continuation(object(), **value.args)
    assert scope.cohort is value.previous.cohort
    assert scope.cohort.targets is value.previous.cohort.targets
    assert scope.predecessor_scope is value.previous
    assert scope.content_pack_release_id == value.previous.content_pack_release_id
    assert scope.workflow_definition_sha256 == value.previous.workflow_definition_sha256
    again = preparation.prepare_creative_parallel_continuation(object(), **value.args)
    assert again == (scope, published)
    value.publisher.publish_first_observation.assert_called_once()
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("fault", ["permission", "source", "seed"])
def test_revoked_or_foreign_owner_cannot_release_controls(monkeypatch, tmp_path, fault):
    value = case(monkeypatch, tmp_path)
    if fault == "permission":
        monkeypatch.setattr(preparation, "effective_permissions", lambda *args: frozenset())
    elif fault == "source":
        value.authorizer.reauthorize.side_effect = ValueError("revoked")
    else:
        value.resolved = NS(operator_id="operator_" + "0" * 32, work=value.resolved.work)
        monkeypatch.setattr(
            preparation,
            "resolve_completed_creative_learning_proposal",
            lambda *args: value.resolved,
        )
    with pytest.raises(ValueError):
        preparation.prepare_creative_parallel_continuation(object(), **value.args)
    value.controls.assert_not_called()
    value.publisher.publish_first_observation.assert_not_called()
