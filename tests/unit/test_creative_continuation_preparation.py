"""The existing admitted owner can prepare only a fixed-source continuation."""

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_learning_cohort import CreativeLearningCohort
from eom_catalog_contracts.creative_learning_continuation import (
    CreativeLearningContinuation,
    CreativeLearningExecutionScope,
)
from eom_catalog_service import creative_continuation_preparation as preparation
from eom_catalog_service.creative_learning_cohort import COHORT_ARTIFACT_TYPE
from eom_identifiers import sha256_bytes
from eom_workflow.control_plane import ExecutionPresetRevision

from tests.unit.test_creative_learning_cohort import cohort_value
from tests.unit.test_creative_registered_report import proposal
from tests.unit.test_external_item_learning_execution_resolver import _published_preset
from tests.unit.test_external_item_learning_workflow_admission import _definition

ROOT = Path(__file__).resolve().parents[2]


def case(monkeypatch, tmp_path):
    parent = CreativeLearningCohort.model_validate(cohort_value())
    seed, _ = proposal()
    parent_publication = NS(
        artifact_id="artifact_" + "1" * 32,
        artifact_revision_id="rev_" + "2" * 32,
        primary_sha256="sha256:" + "3" * 64,
    )
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=None)
    sessions = Mock(return_value=session)
    sessions.begin.side_effect = lambda: nullcontext(session)
    monkeypatch.setattr(preparation, "build_session_factory", lambda engine: sessions)
    artifacts = Mock()
    publisher = Mock()
    publisher.find_published.return_value = None
    monkeypatch.setattr(preparation, "CatalogArtifactService", lambda *args: artifacts)
    monkeypatch.setattr(preparation, "ControlFileSetPublisher", lambda *args: publisher)
    monkeypatch.setattr(
        preparation, "read_creative_cohort", lambda *args: (parent, parent_publication)
    )
    monkeypatch.setattr(
        preparation, "resolve_completed_creative_learning_proposal", lambda *args: seed
    )
    monkeypatch.setattr(
        preparation, "CatalogExternalItemLearningSourceAuthorizer", lambda *args: Mock()
    )
    monkeypatch.setattr(
        preparation, "ExternalItemPreviewProjectionService", lambda *args, **kwargs: object()
    )
    monkeypatch.setattr(
        preparation, "effective_permissions", lambda *args: preparation._PERMISSIONS
    )
    registration = Mock()
    registration.find_registered_source.return_value = NS(
        lineage=NS(selection=parent.seed_selection)
    )
    monkeypatch.setattr(
        preparation, "CreativeItemRegistrationService", lambda *args, **kwargs: registration
    )
    _, preset_row = _published_preset(successor=True)
    extraction = ExecutionPresetRevision.model_validate(preset_row.canonical_document)
    controls = Mock(return_value=extraction)
    monkeypatch.setattr(preparation, "release_creative_source_controls", controls)
    import_definition = Mock(return_value=(_definition(successor=True), True))
    monkeypatch.setattr(preparation, "import_workflow_definition", import_definition)
    pack = Mock(return_value="packrel_" + "4" * 32)
    monkeypatch.setattr(preparation, "prepare_creative_registration_pack", pack)
    stored = {}

    def publish(**kwargs):
        payload = kwargs["members"][0].source.read_bytes()
        continuation = CreativeLearningContinuation.model_validate_json(payload)
        published = NS(artifact_revision_id="rev_" + "5" * 32)
        stored.update(
            scope=CreativeLearningExecutionScope(parent, continuation), published=published
        )
        publisher.find_published.return_value = published
        assert kwargs["artifact_type"] == COHORT_ARTIFACT_TYPE
        assert kwargs["members"][0].sha256 == sha256_bytes(payload)
        return published

    publisher.publish_first_observation.side_effect = publish
    monkeypatch.setattr(
        preparation,
        "read_creative_execution_scope",
        lambda *args: (stored["scope"], stored["published"]),
    )
    args = dict(
        parent_revision_id=parent_publication.artifact_revision_id,
        instruction_directory=ROOT
        / "config/control-plane/creative-source-learning-v1/instructions",
        pack_directory=ROOT / "content/packs/external-creative-item/1.1.0",
        definition_path=ROOT / "config/workflows/external-item-learning.v2.yaml",
        source_commit="a" * 40,
        settings=NS(staging_root=tmp_path),
        catalog_settings=object(),
    )
    return NS(**locals())


def test_preparation_references_original_targets_and_replays_without_publishing_again(
    monkeypatch, tmp_path
):
    value = case(monkeypatch, tmp_path)
    scope, published = preparation.prepare_creative_source_continuation(object(), **value.args)
    assert scope.cohort is value.parent and scope.cohort.targets is value.parent.targets
    assert (
        scope.continuation.parent_cohort.artifact_revision_id
        == value.parent_publication.artifact_revision_id
    )
    assert scope.workflow_definition_version == "2.0.0"
    assert (
        value.controls.call_args.kwargs["baseline_revision_id"]
        == value.parent.extraction_preset.preset_revision_id
    )
    assert (
        value.controls.call_args.kwargs["capacity_revision_id"]
        == value.parent.capacity_policy_revision_id
    )
    assert (
        value.registration.find_registered_source.call_args.kwargs["requested_by_operator_id"]
        == value.parent.requested_by_operator_id
    )
    scope2, published2 = preparation.prepare_creative_source_continuation(object(), **value.args)
    assert scope2 == scope and published2 == published
    value.publisher.publish_first_observation.assert_called_once()
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("failure", ["permission", "source", "seed"])
def test_preparation_cannot_expand_or_borrow_another_owner_before_control_changes(
    monkeypatch, tmp_path, failure
):
    value = case(monkeypatch, tmp_path)
    if failure == "permission":
        monkeypatch.setattr(preparation, "effective_permissions", lambda *args: frozenset())
    elif failure == "source":
        authorizer = Mock()
        authorizer.reauthorize.side_effect = ValueError("source revoked")
        monkeypatch.setattr(
            preparation, "CatalogExternalItemLearningSourceAuthorizer", lambda *args: authorizer
        )
    else:
        value.registration.find_registered_source.return_value = None
    with pytest.raises(ValueError):
        preparation.prepare_creative_source_continuation(object(), **value.args)
    value.controls.assert_not_called()
    value.publisher.publish_first_observation.assert_not_called()
    value.import_definition.assert_not_called()
