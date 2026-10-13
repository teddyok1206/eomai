"""Real temporary owner publication/read with synthetic source/launch metadata only.

Never production authority, genuine native execution, model or NAS acceptance.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactResolutionError
from eom_catalog_service.reference_query_artifact_read import CatalogReferenceQueryArtifacts
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.embedding_artifact_store import (
    EmbeddingArtifactStore,
    PublishedReferenceQueryArtifacts,
)
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.models import JobRecord
from eom_workflow.reference_query_execution import (
    ReferenceQueryWorkflowReceipt,
    parse_reference_query_workflow_receipt,
)
from sqlalchemy import select

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_embedding_reference_query_artifact_store import (
    PreparedQuery,
    prepare,
    prepare_three_views,
    publish,
)
from tests.unit.test_reference_query_execution_contracts import case


@dataclass
class Publication:
    value: PreparedQuery
    publisher: ControlFileSetPublisher
    published: PublishedReferenceQueryArtifacts
    receipt: ReferenceQueryWorkflowReceipt


@pytest.fixture(params=(False, True), ids=("two-views", "three-views"))
def publication(tmp_path: Path, request: pytest.FixtureRequest) -> Publication:
    base = case()
    value = prepare_three_views(tmp_path, base) if request.param else prepare(tmp_path, base)
    publisher, _engine = _publisher(tmp_path)
    value.store = EmbeddingArtifactStore(publisher, source_commit="a" * 40)
    published = publish(value)
    current = value.case
    native = current.native_input
    receipt = parse_reference_query_workflow_receipt(
        seal(
            current.receipt.model_dump(mode="json")
            | {
                "workflow_request_sha256": current.request.request_sha256,
                "context_request_sha256": current.request.context_request.request_sha256,
                "launch_association_sha256": current.launch.association_sha256,
                "query_artifact_owner_job_id": published.owner_job_id,
                "query_input": published.input.model_dump(mode="json"),
                "query_execution": {
                    "job_id": native.job_id,
                    "query_request_id": native.query_request_id,
                    "request_sha256": native.request_sha256,
                    "input_set_sha256": native.input_set_sha256,
                    "result_member": published.result.model_dump(mode="json"),
                    "result_sha256": value.result.result_sha256,
                },
                "shard": published.shard.model_dump(mode="json"),
                "binary": published.binary.model_dump(mode="json"),
            },
            "receipt_sha256",
        )
    )
    return Publication(value, publisher, published, receipt)


def arguments(publication: Publication) -> dict[str, Any]:
    current = publication.value.case
    return {
        "workflow_request": current.request,
        "policy": current.policy,
        "bundle": current.bundle,
        "launch": current.launch,
        "receipt": publication.receipt,
        "workflow_id": current.launch.workflow_id,
        "step_run_id": current.launch.step_run_id,
        "receipt_owner_job_id": publication.receipt.receipt_owner_job_id,
    }


def reader(publication: Publication, session: Any) -> CatalogReferenceQueryArtifacts:
    return CatalogReferenceQueryArtifacts(
        session, CatalogSettings(nas_artifact_root=publication.publisher.settings.nas_artifact_root)
    )


def test_exact_committed_members_actual_producer_and_replay(publication: Publication) -> None:
    with publication.publisher.sessions() as session, session.begin():
        adapter = reader(publication, session)
        first = adapter.resolve_publication(**arguments(publication))
        assert first == adapter.resolve_publication(**arguments(publication))
        assert first.request == publication.value.case.native_input
        assert first.result == publication.value.result
        assert first.binary == publication.value.binary
        assert first.publication_job_id == publication.published.owner_job_id
        assert first.request.spaces.query.purpose == "QUERY"
        assert first.request.batch_size == 4
        job = session.scalar(select(JobRecord))
        assert job is not None
        persisted = canonical_json_bytes(job.request)
        assert b'"rows"' not in persisted and b'"text"' not in persisted


@pytest.mark.parametrize("member", ("input.json", "result.json", "shard.json", "vectors.f32"))
def test_corrupt_canonical_member_does_not_resolve(publication: Publication, member: str) -> None:
    pointer = publication.published.result
    path = (
        publication.publisher.settings.nas_artifact_root
        / pointer.artifact_id
        / pointer.artifact_revision_id
        / member
    )
    path.write_bytes(b"corrupt canonical bytes")
    with (
        publication.publisher.sessions() as session,
        session.begin(),
        pytest.raises(PinnedArtifactResolutionError),
    ):
        reader(publication, session).resolve_publication(**arguments(publication))


def test_receipt_cannot_forge_actual_publication_producer(publication: Publication) -> None:
    bad = parse_reference_query_workflow_receipt(
        seal(
            publication.receipt.model_dump(mode="json")
            | {"query_artifact_owner_job_id": "job_" + "f" * 32},
            "receipt_sha256",
        )
    )
    with (
        publication.publisher.sessions() as session,
        session.begin(),
        pytest.raises(ValueError, match="PRODUCER_MISMATCH"),
    ):
        reader(publication, session).resolve_publication(
            **(arguments(publication) | {"receipt": bad})
        )


def test_changed_expected_workflow_identity_does_not_resolve(publication: Publication) -> None:
    with publication.publisher.sessions() as session, session.begin(), pytest.raises(ValueError):
        reader(publication, session).resolve_publication(
            **(arguments(publication) | {"workflow_id": "workflow_" + "f" * 32})
        )


def test_current_producer_failure_is_not_cached_by_successful_read(
    publication: Publication,
) -> None:
    with publication.publisher.sessions() as session, session.begin():
        adapter = reader(publication, session)
        adapter.resolve_publication(**arguments(publication))
        job = session.get(JobRecord, publication.published.owner_job_id)
        assert job is not None
        job.status = "FAILED"  # Temporary unit fixture only, not historical repair.
        with pytest.raises(PinnedArtifactResolutionError):
            adapter.resolve_publication(**arguments(publication))
