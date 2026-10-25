"""Marker-guarded PostgreSQL publication/replay; source, IAM, OS and model not exercised."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetPublisher,
)
from eom_orchestrator.local_embedding_control_artifacts import (
    REFERENCE_QUERY_PREPARATION_ARTIFACT_TYPE,
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.models import JobRecord
from eom_orchestrator.settings import Settings
from eom_workflow.reference_query_routed_preparation import (
    RoutedReferenceQueryPreparation,
    parse_reference_query_routed_preparation,
    routed_reference_query_preparation_key,
)
from sqlalchemy import select

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_reference_query_routed_preparation import preparation_case

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def publication(guarded_engine, tmp_path):
    artifacts, workspace = tmp_path / "artifacts", tmp_path / "workspace"
    artifacts.mkdir(mode=0o700)
    workspace.mkdir(mode=0o700)
    publisher = ControlFileSetPublisher(
        guarded_engine,
        Settings(
            staging_root=tmp_path / "staging", workspace_root=workspace, nas_artifact_root=artifacts
        ),
    )
    return LocalEmbeddingControlArtifactPublisher(
        publisher, source_commit="a" * 40
    ), preparation_case(key="routed-preparation:" + uuid4().hex)


def read_value(adapter, value):
    pointer = adapter.find_routed_reference_query_preparation(
        operator_id=value.operator_id, idempotency_key=value.idempotency_key
    )
    assert pointer is not None
    with adapter.publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext.for_session(
            session, CatalogSettings(nas_artifact_root=adapter.publisher.settings.nas_artifact_root)
        )
        reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
        reader.require_file_set(
            pointer.artifact_id,
            pointer.artifact_revision_id,
            (pointer.member_path,),
            manifest_version=CONTROL_FILE_SET_PROTOCOL,
        )
        raw = reader.read_pinned(
            **pointer.model_dump(mode="python"),
            expected_artifact_types=(REFERENCE_QUERY_PREPARATION_ARTIFACT_TYPE,),
            expected_primary_file="preparation.json",
            max_bytes=65536,
        ).payload
        parsed = parse_reference_query_routed_preparation(raw)
        reader.revalidate_provenance()
    return pointer, parsed


def test_original_metadata_survives_publication_only_interruption_and_same_request_replay(
    publication,
):
    adapter, value = publication
    assert (
        adapter.find_routed_reference_query_preparation(
            operator_id=value.operator_id, idempotency_key=value.idempotency_key
        )
        is None
    )
    first = adapter.publish_routed_reference_query_preparation(value)
    assert adapter.publish_routed_reference_query_preparation(value) == first
    pointer, parsed = read_value(adapter, value)
    assert pointer == first.member and parsed == value
    with adapter.publisher.sessions.begin() as session:
        key = routed_reference_query_preparation_key(value.operator_id, value.idempotency_key)
        rows = tuple(session.scalars(select(JobRecord).where(JobRecord.idempotency_key == key)))
        assert len(rows) == 1 and rows[0].status == "SUCCEEDED"
        # Files remain canonical Artifacts, never full request/text/vector DB values.
        request_bytes = canonical_json_bytes(rows[0].request)
        assert b'"parent"' not in request_bytes
        assert b'"selection_manifest"' not in request_bytes
        assert b'"password"' not in request_bytes
        assert not session.scalar(
            select(JobRecord.job_id)
            .where(
                JobRecord.task_type == "embedding_batch_plan",
                JobRecord.request["batch_id"].astext == value.parent.batch_id,
            )
            .limit(1)
        )


def test_same_key_foreign_intent_conflicts_without_replacing_original_publication(publication):
    adapter, value = publication
    first = adapter.publish_routed_reference_query_preparation(value)
    body = value.model_dump(mode="json")
    body["intent_sha256"] = "sha256:" + "f" * 64
    body["parent"] = seal(
        body["parent"] | {"parent_request_sha256": body["intent_sha256"]}, "request_sha256"
    )
    other = RoutedReferenceQueryPreparation.model_validate(seal(body, "preparation_sha256"))
    with pytest.raises(ControlPlaneError):
        adapter.publish_routed_reference_query_preparation(other)
    pointer, parsed = read_value(adapter, value)
    assert pointer == first.member and parsed == value


def test_concurrent_same_original_preparation_has_one_job_and_one_exact_artifact(publication):
    adapter, value = publication
    barrier = Barrier(2)

    def publish():
        barrier.wait(timeout=10)
        return adapter.publish_routed_reference_query_preparation(value)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = tuple(pool.map(lambda _ordinal: publish(), range(2)))
    assert a == b
    assert read_value(adapter, value) == (a.member, value)
    with adapter.publisher.sessions.begin() as session:
        key = routed_reference_query_preparation_key(value.operator_id, value.idempotency_key)
        assert (
            len(tuple(session.scalars(select(JobRecord).where(JobRecord.idempotency_key == key))))
            == 1
        )
