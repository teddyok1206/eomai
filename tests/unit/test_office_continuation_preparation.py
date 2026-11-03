"""Native continuation preparation keeps the admitted owner and one immutable commit."""

from contextlib import nullcontext
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_learning_continuation import (
    CreativeLearningExecutionScope,
    CreativeLearningOfficeContinuation,
)
from eom_catalog_service import creative_office_continuation_preparation as owner
from eom_orchestrator.control_service import ControlPlaneError

from tests.unit.test_creative_registered_report import proposal
from tests.unit.test_office_creative_continuation import office_continuation_case


def case(monkeypatch, tmp_path):
    previous, pointer, expected = office_continuation_case()
    session = Mock()
    monkeypatch.setattr(owner, "build_session_factory", lambda _: lambda: nullcontext(session))
    artifacts, publisher, source = Mock(), Mock(), Mock()
    publisher.find_published.return_value = None
    monkeypatch.setattr(owner, "CatalogArtifactService", lambda *args: artifacts)
    monkeypatch.setattr(owner, "ControlFileSetPublisher", lambda *args: publisher)
    monkeypatch.setattr(owner, "ControlArtifactPublisher", lambda *args: object())
    resolved, _ = proposal()
    monkeypatch.setattr(owner, "resolve_completed_creative_learning_proposal", lambda *a: resolved)
    monkeypatch.setattr(owner, "CatalogExternalItemLearningSourceAuthorizer", lambda *a: source)
    monkeypatch.setattr(owner, "ExternalItemPreviewProjectionService", lambda *a, **kw: object())
    monkeypatch.setattr(owner, "effective_permissions", lambda *a: owner._PERMISSIONS)
    native = Mock(return_value=NS(preset_revision_id="execpresetrev_" + "a" * 32))
    monkeypatch.setattr(owner, "prepare_office_item_learning_execution_policy", native)

    def preset(pin):
        return NS(
            preset_id=pin.preset_id,
            preset_revision_id=pin.preset_revision_id,
            content_sha256=pin.sha256,
        )

    controls = Mock(
        return_value=NS(
            extraction=preset(expected.extraction_preset),
            analysis=preset(expected.analysis_preset),
            capacity=NS(
                capacity_policy_id=expected.capacity_policy.capacity_policy_id,
                capacity_policy_revision_id=expected.capacity_policy.capacity_policy_revision_id,
                content_sha256=expected.capacity_policy.sha256,
            ),
        )
    )
    monkeypatch.setattr(owner, "release_creative_office_parallel_controls", controls)
    monkeypatch.setattr(
        owner,
        "prepare_creative_registration_pack",
        lambda *a, **kw: expected.content_pack_release_id,
    )
    publication = NS(
        artifact_id=pointer.artifact_id,
        artifact_revision_id=pointer.artifact_revision_id,
        primary_file=pointer.member_path,
        primary_sha256=pointer.sha256,
    )
    stored = {}

    def read(_a, _p, revision):
        if revision == pointer.artifact_revision_id:
            return previous, publication
        return stored["scope"], stored["publication"]

    monkeypatch.setattr(owner, "read_creative_execution_scope", read)

    def publish(**kwargs):
        value = CreativeLearningOfficeContinuation.model_validate_json(
            kwargs["members"][0].source.read_bytes()
        )
        stored["scope"] = CreativeLearningExecutionScope(previous.cohort, value, previous)
        stored["publication"] = NS(artifact_revision_id="rev_" + "e" * 32)
        publisher.find_published.return_value = stored["publication"]
        return stored["publication"]

    publisher.publish_first_observation.side_effect = publish
    args = dict(
        predecessor_revision_id=pointer.artifact_revision_id,
        controls=NS(
            source_commit="a" * 40, definition=NS(sha256=expected.workflow_definition_sha256)
        ),
        pack_directory=tmp_path,
        settings=NS(staging_root=tmp_path),
        catalog_settings=object(),
    )
    return NS(**locals())


def test_preparation_reuses_targets_and_replays_without_start_or_second_commit(
    monkeypatch, tmp_path
):
    value = case(monkeypatch, tmp_path)
    result = owner.prepare_creative_office_continuation(object(), **value.args)
    scope, _ = result
    assert scope.cohort is value.previous.cohort
    assert scope.cohort.targets is value.previous.cohort.targets
    assert scope.predecessor_scope is value.previous
    assert scope.workflow_definition_version == "3.0.0"
    assert scope.max_in_flight_sources == 8
    assert scope.continuation.max_report_workers == 4
    assert value.controls.call_args.kwargs["analysis_revision_id"] == (
        value.previous.analysis_preset.preset_revision_id
    )
    assert owner.prepare_creative_office_continuation(object(), **value.args) == result
    value.publisher.publish_first_observation.assert_called_once()
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("fault", ["permission", "source", "seed"])
def test_revoked_owner_or_foreign_seed_cannot_release_native_controls(monkeypatch, tmp_path, fault):
    value = case(monkeypatch, tmp_path)
    if fault == "permission":
        monkeypatch.setattr(owner, "effective_permissions", lambda *a: frozenset())
    elif fault == "source":
        value.source.reauthorize.side_effect = ValueError("REVOKED")
    else:
        monkeypatch.setattr(
            owner,
            "resolve_completed_creative_learning_proposal",
            lambda *a: NS(operator_id="operator_" + "0" * 32, work=value.resolved.work),
        )
    with pytest.raises(ValueError):
        owner.prepare_creative_office_continuation(object(), **value.args)
    value.native.assert_not_called()
    value.controls.assert_not_called()
    value.publisher.publish_first_observation.assert_not_called()


def test_partial_publication_resumes_the_same_immutable_commit(monkeypatch, tmp_path):
    value = case(monkeypatch, tmp_path)
    value.publisher.find_published.side_effect = ControlPlaneError(
        "CONTROL_FILE_SET_INCOMPLETE", "synthetic interrupted commit"
    )
    scope, _ = owner.prepare_creative_office_continuation(object(), **value.args)
    assert scope.cohort is value.previous.cohort
    value.publisher.publish_first_observation.assert_called_once()


def test_replay_of_another_scope_is_rejected(monkeypatch, tmp_path):
    value = case(monkeypatch, tmp_path)
    owner.prepare_creative_office_continuation(object(), **value.args)
    value.stored["scope"] = value.previous
    with pytest.raises(ValueError, match="REPLAY_MISMATCH"):
        owner.prepare_creative_office_continuation(object(), **value.args)
    value.publisher.publish_first_observation.assert_called_once()
