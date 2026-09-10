from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from eom_catalog_service.models import ItemRevisionRecord
from eom_catalog_service.pdf_learning_completion_service import PdfLearningCompletionError
from eom_catalog_service.pdf_learning_completion_source import (
    PostgresPdfLearningCompletionSource,
    _analysis_history_scope_is_exact,
)
from eom_workflow_runner.models import WorkflowInstanceRecord
from test_knowledge_analysis_artifact import _request as _historical_v2_request


def _item_manifest_fixture() -> tuple[
    ItemRevisionRecord,
    WorkflowInstanceRecord,
    dict[str, object],
]:
    workflow_created_at = datetime(2026, 9, 1, tzinfo=UTC)
    workflow = WorkflowInstanceRecord(
        workflow_id="workflow_" + "1" * 32,
        definition_key="knowledge-item-production",
        definition_version="1.4.0",
        created_at=workflow_created_at,
    )
    revision = ItemRevisionRecord(
        item_id="item_" + "2" * 32,
        item_revision_id="itemrev_" + "3" * 32,
        revision_number=1,
        content_pack_release_id="packrel_" + "4" * 32,
        workflow_id=workflow.workflow_id,
        workflow_definition_version=workflow.definition_version,
        metadata_sha256="sha256:" + "5" * 64,
        created_at=workflow_created_at + timedelta(seconds=3),
    )
    manifest: dict[str, object] = {
        "schema_version": "1.0",
        "item_id": revision.item_id,
        "item_revision_id": revision.item_revision_id,
        "revision_number": revision.revision_number,
        "content_pack": {"release_id": revision.content_pack_release_id},
        "workflow": {
            "workflow_id": workflow.workflow_id,
            "definition_key": workflow.definition_key,
            "definition_version": workflow.definition_version,
        },
        "components": [],
        "metadata": {"sha256": revision.metadata_sha256},
        "created_at": workflow_created_at.isoformat().replace("+00:00", "Z"),
    }
    return revision, workflow, manifest


def test_item_manifest_timestamp_is_pinned_to_producing_workflow() -> None:
    revision, workflow, manifest = _item_manifest_fixture()

    PostgresPdfLearningCompletionSource._validate_item_manifest(
        revision,
        workflow,
        (),
        manifest,
    )

    assert revision.created_at != workflow.created_at


def test_item_manifest_rejects_revision_timestamp_substitution() -> None:
    revision, workflow, manifest = _item_manifest_fixture()
    manifest["created_at"] = revision.created_at.isoformat().replace("+00:00", "Z")

    with pytest.raises(ValueError, match="canonical database rows"):
        PostgresPdfLearningCompletionSource._validate_item_manifest(
            revision,
            workflow,
            (),
            manifest,
        )


def test_valid_historical_analysis_request_is_typed_then_excluded() -> None:
    source = object.__new__(PostgresPdfLearningCompletionSource)
    request = _historical_v2_request().model_dump(mode="json")

    assert source._validated_historical_analysis_request(request) is True


def test_malformed_historical_analysis_request_fails_closed() -> None:
    source = object.__new__(PostgresPdfLearningCompletionSource)
    request = _historical_v2_request().model_dump(mode="json")
    request["request_sha256"] = "sha256:" + "f" * 64

    with pytest.raises(PdfLearningCompletionError, match="does not validate exactly"):
        source._validated_historical_analysis_request(request)


def test_v9_analysis_history_scope_accepts_520_leaves_plus_six_predecessors() -> None:
    accepted = {f"analysisrun_{index:032x}" for index in range(520)}
    predecessors = {f"analysisrun_{10_000 + index:032x}" for index in range(6)}

    assert _analysis_history_scope_is_exact(
        accepted_ids=accepted,
        predecessor_ids=predecessors,
        scoped_ids=accepted | predecessors,
    )


@pytest.mark.parametrize("predecessor_count", [0, 33])
def test_v9_analysis_history_scope_rejects_out_of_policy_predecessor_count(
    predecessor_count: int,
) -> None:
    accepted = {f"analysisrun_{index:032x}" for index in range(520)}
    predecessors = {f"analysisrun_{10_000 + index:032x}" for index in range(predecessor_count)}

    assert not _analysis_history_scope_is_exact(
        accepted_ids=accepted,
        predecessor_ids=predecessors,
        scoped_ids=accepted | predecessors,
    )


def test_v9_analysis_history_scope_rejects_missing_or_extra_rows() -> None:
    accepted = {f"analysisrun_{index:032x}" for index in range(520)}
    predecessors = {f"analysisrun_{10_000 + index:032x}" for index in range(6)}
    exact = accepted | predecessors

    assert not _analysis_history_scope_is_exact(
        accepted_ids=accepted,
        predecessor_ids=predecessors,
        scoped_ids=exact - {next(iter(predecessors))},
    )
    assert not _analysis_history_scope_is_exact(
        accepted_ids=accepted,
        predecessor_ids=predecessors,
        scoped_ids=exact | {"analysisrun_" + "f" * 32},
    )
