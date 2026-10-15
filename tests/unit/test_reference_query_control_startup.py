"""Actual temporary canonical control bytes; startup read is not source/user authority."""

import pytest
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_workflow.reference_query_execution import validate_reference_query_policy_bundle
from eom_workflow_runner.reference_query_source_read import (
    read_pinned_reference_query_controls,
    read_selected_reference_query_controls,
)

from tests.unit.test_reference_query_owner_admission import source as source


def test_startup_and_request_share_exact_control_closure_without_source_capture(source):
    config = source.owner.configuration
    with source.publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext(session, source.owner.settings)
        first = read_selected_reference_query_controls(
            reader,
            policy_member=config.native_execution_policy,
            policy_sha256=config.native_execution_policy_sha256,
            runtime_bundle=config.runtime_bundle,
        )
        second = read_pinned_reference_query_controls(reader, config)
    assert first == second
    assert validate_reference_query_policy_bundle(*first) == first
    assert source.calls == []


def test_wrong_policy_semantic_pin_is_not_startup_readiness(source):
    config = source.owner.configuration
    with source.publisher.sessions.begin() as session, pytest.raises(ValueError):
        read_selected_reference_query_controls(
            PinnedArtifactReadContext(session, source.owner.settings),
            policy_member=config.native_execution_policy,
            policy_sha256="sha256:" + "0" * 64,
            runtime_bundle=config.runtime_bundle,
        )
    assert source.calls == []
