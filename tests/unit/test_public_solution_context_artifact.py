"""Real existing publisher with temporary SQLite/Artifacts; no live user or native GPU claim."""

from __future__ import annotations

from dataclasses import replace

import pytest
from eom_catalog_contracts.public_solution_delivery import (
    validate_public_solution_similarity_delivery,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    parse_supported_public_solution_similarity_context,
    parse_supported_public_solution_similarity_request,
)
from eom_catalog_contracts.similarity_context import parse_similarity_context
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.similarity_context_artifact import publish_public_solution_similarity_context
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy import func, select

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_public_solution_similarity_contracts import public_similarity_case
from tests.unit.test_registered_public_solution_similarity_contracts import (
    registered_similarity_case,
)
from tests.unit.test_similarity_context_artifact import KEY, SOURCE, publish, publisher_for
from tests.unit.test_similarity_context_contracts import context_body


@pytest.fixture(params=(3, 4))
def context(request):
    return (public_similarity_case if request.param == 3 else registered_similarity_case)()[1]


def public_publish(publisher, context):
    return publish_public_solution_similarity_context(
        publisher,
        context=context,
        expected_request=context.request,
        idempotency_key=KEY,
        source_commit=SOURCE,
    )


def test_public_replay_keeps_one_canonical_member_and_small_db_pointers(tmp_path, context):
    publisher = publisher_for(tmp_path)
    first = public_publish(publisher, context)
    (primary,) = tuple(publisher.settings.nas_artifact_root.rglob("context.json"))
    before = primary.stat()
    assert primary.read_bytes() == canonical_json_bytes(context.model_dump(mode="json"))
    assert sha256_bytes(primary.read_bytes()) == first.delivery.context_member.sha256
    assert first.delivery.context_member.sha256 != first.delivery.context_sha256
    assert public_publish(publisher, context) == first
    after = primary.stat()
    assert (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_size) == (
        after.st_dev,
        after.st_ino,
        after.st_mtime_ns,
        after.st_size,
    )
    assert (
        validate_public_solution_similarity_delivery(
            first.delivery, context, expected_request=context.request
        )
        == context
    )
    assert not tuple(publisher.settings.workspace_root.iterdir())
    with publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 1
        job = session.get(JobRecord, first.owner_job_id)
        assert job is not None and job.status == "SUCCEEDED"
        request_bytes = canonical_json_bytes(job.request)
        assert b'"candidates"' not in request_bytes and b'"query_execution"' not in request_bytes
        assert b'"vectors"' not in request_bytes and len(request_bytes) < 16384


def test_old_key_cannot_be_reinterpreted_as_public_context_or_spawn_a_second_result(
    tmp_path, context
):
    publisher = publisher_for(tmp_path)
    legacy = parse_similarity_context(context_body())
    original = publish(publisher, legacy)
    with pytest.raises(ControlPlaneError):
        public_publish(publisher, context)
    assert publish(publisher, legacy) == original
    with publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 1


@pytest.mark.parametrize("fault", ("source", "hash", "nested", "failed", "foreign_request"))
def test_wrong_scope_and_unchecked_values_never_reach_the_commit_owner(tmp_path, context, fault):
    publisher = publisher_for(tmp_path)
    request = context.request
    source = SOURCE
    if fault == "source":
        source = "invalid"
    elif fault == "hash":
        context = context.model_copy(update={"context_sha256": "sha256:" + "0" * 64})
    elif fault == "nested":
        context = context.model_copy(update={"request": request.model_copy(update={"top_k": True})})
    elif fault == "failed":
        body = context.model_dump(mode="json")
        body.update(
            status="FAILED",
            population=None,
            query_execution=None,
            candidates=[],
            error_code="SOURCE_REVOKED",
        )
        context = parse_supported_public_solution_similarity_context(seal(body, "context_sha256"))
    else:
        request = parse_supported_public_solution_similarity_request(
            seal(
                request.model_dump(mode="json") | {"request_id": "similarityrequest_" + "0" * 32},
                "request_sha256",
            )
        )
    with pytest.raises((ValueError, SchemaError)):
        publish_public_solution_similarity_context(
            publisher,
            context=context,
            expected_request=request,
            idempotency_key=KEY,
            source_commit=source,
        )
    with publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 0


@pytest.mark.parametrize(
    "field",
    (
        "primary_file",
        "primary_sha256",
        "job_id",
        "artifact_id",
        "artifact_revision_id",
        "manifest_sha256",
        "missing_receipt",
    ),
)
def test_receipt_failure_preserves_committed_publication_and_original_key(
    tmp_path, context, monkeypatch, field
):
    publisher = publisher_for(tmp_path)
    original = publisher.publish_first_observation
    calls = []

    def wrong(**kwargs):
        actual = original(**kwargs)
        calls.append(actual)
        return None if field == "missing_receipt" else replace(actual, **{field: "wrong"})

    with monkeypatch.context() as patch:
        patch.setattr(publisher, "publish_first_observation", wrong)
        with pytest.raises(ValueError, match="PUBLICATION_RECEIPT_INVALID"):
            public_publish(publisher, context)
    assert len(calls) == 1
    first = public_publish(publisher, context)
    assert first.owner_job_id == calls[0].job_id
    assert first.delivery.context_member.artifact_revision_id == calls[0].artifact_revision_id
    with publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 1
