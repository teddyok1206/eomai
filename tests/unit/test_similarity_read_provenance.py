"""Real temporary QUERY/receipt bytes and late lifecycle; synthetic IAM/Workflow ports."""

from __future__ import annotations

from dataclasses import replace

import pytest
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactReadContext,
    PinnedArtifactResolutionError,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_workflow_runner.reference_query_consumer_read import CatalogCompletedReferenceQueryRead

from tests.unit.test_reference_query_consumer_read import completed as completed


@pytest.mark.parametrize("kind", ("query_revision", "receipt_revision", "query_job", "receipt_job"))
def test_outer_read_window_rechecks_canonical_provenance_after_common_and_late_checks(
    completed, kind
):
    case = completed
    owner = case.reader.owner
    with case.reader.sessions.begin() as session:
        provenance = PinnedArtifactReadContext(session, owner.settings)
        reader = CatalogCompletedReferenceQueryRead(
            owner,
            workflow_id=case.reader.workflow_id,
            request=case.reader.request,
            artifact_reader=provenance,
        )
        value = reader.resolve_reference_query_in_session(
            session, case.caller, case.value.request.context_request, case.value.sources.prepared
        )
        # An outer current-source/composition check can overlap a supported
        # lifecycle change after the canonical consumer has already returned.
        revision_id = (
            value.result_member.artifact_revision_id
            if kind.startswith("query")
            else case.output.receipt.artifact_revision_id
        )
        with case.reader.sessions.begin() as other:
            revision = other.get(ArtifactRevisionRecord, revision_id)
            if kind.endswith("revision"):
                revision.approved = False
            else:
                other.get(JobRecord, revision.job_id).status = "FAILED"
        with pytest.raises(PinnedArtifactResolutionError):
            provenance.revalidate_provenance()
    assert len(case.value.runs) == 1  # no retry/repair or model invocation on read


@pytest.mark.parametrize("fault", ("root", "settings"))
def test_shared_reader_cannot_move_to_another_root_or_settings(completed, fault):
    case = completed
    with case.reader.sessions.begin() as first, case.reader.sessions.begin() as second:
        settings = case.reader.owner.settings
        if fault == "settings":
            settings = replace(settings, nas_artifact_root=settings.nas_artifact_root / "other")
        provenance = PinnedArtifactReadContext(first, settings)
        reader = CatalogCompletedReferenceQueryRead(
            case.reader.owner,
            workflow_id=case.reader.workflow_id,
            request=case.reader.request,
            artifact_reader=provenance,
        )
        with pytest.raises(SimilarityContextReadError):
            reader.resolve_reference_query_in_session(
                second if fault == "root" else first,
                case.caller,
                case.value.request.context_request,
                case.value.sources.prepared,
            )
