"""Actual test-local file-set publication and Catalog read; not production source authority."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_service.embedding_encoder_adapter import encode_incremental_batch
from eom_catalog_service.local_embedding_encoding_artifacts import (
    CatalogLocalEmbeddingEncodingArtifacts,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.embedding_artifact_store import EmbeddingArtifactStore
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_workflow.local_embedding_encoding_job import (
    EmbeddingEncodingCompletedEvent,
    LocalEmbeddingLaunchAssociation,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.local_embedding_admission_fixtures import native_fixture
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend


@pytest.fixture
def published(tmp_path: Path):
    fixture = native_fixture()
    publisher, _engine = _publisher(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    publisher.settings = replace(publisher.settings, workspace_root=workspace)
    input_receipt = LocalEmbeddingControlArtifactPublisher(
        publisher, source_commit="a" * 40
    ).publish_owned_input(
        fixture.native_input,
        idempotency_key="synthetic-encoding-input",
        created_at=NOW,
    )
    association = LocalEmbeddingLaunchAssociation.model_validate(
        seal(
            fixture.association.model_dump(mode="json")
            | {"owned_input": input_receipt.member.model_dump(mode="json")},
            "association_sha256",
        )
    )
    backend = SyntheticNativeBackend(fixture.native_input.space)
    backend.batch_size = backend.threads = 4
    encoded = encode_incremental_batch(fixture.native_input, backend)
    for name, raw in (
        ("result.json", canonical_json_bytes(encoded.result.model_dump(mode="json"))),
        ("vectors.f32", encoded.vectors),
    ):
        path = workspace / name
        path.write_bytes(raw)
        path.chmod(0o600)
    outputs = EmbeddingArtifactStore(publisher, source_commit="a" * 40).publish_owned_batch(
        workflow_request=fixture.request,
        plan=fixture.plan,
        policy=fixture.policy,
        association=association,
        request=fixture.native_input,
        workspace=workspace,
        created_at=NOW,
    )
    events = []
    for ordinal, owned in enumerate(association.owned_jobs):
        receipt = seal(
            {
                "native_launch_job_id": association.intent.native_launch_job_id,
                "result_manifest": outputs.result.model_dump(mode="json"),
                "result_sha256": encoded.result.result_sha256,
                "shard_manifest": outputs.shard.model_dump(mode="json"),
                "shard_sha256": encoded.result.shard.shard_sha256,
                "binary_member": outputs.binary.model_dump(mode="json"),
                "row_ref": {
                    "shard_manifest": outputs.shard.model_dump(mode="json"),
                    "row_index": ordinal,
                    "encoding_sha256": owned.request.encoding.encoding_sha256,
                },
            },
            "receipt_sha256",
        )
        events.append(
            EmbeddingEncodingCompletedEvent.model_validate(
                seal(
                    {
                        "schema_version": "embedding-encoding-job/1.0",
                        "record_type": "COMPLETED",
                        "owned_job": owned.model_dump(mode="json"),
                        "intent": association.intent.model_dump(mode="json"),
                        "launch_association_sha256": association.association_sha256,
                        "receipt": receipt,
                    },
                    "event_sha256",
                )
            )
        )
    return publisher, fixture, association, tuple(events), outputs, encoded.result


def reader(publisher, session):
    return CatalogLocalEmbeddingEncodingArtifacts(
        session, CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
    )


def test_resolves_real_test_owned_input_result_binary_and_exact_closure(published) -> None:
    publisher, fixture, association, events, _outputs, result = published
    with publisher.sessions.begin() as session:
        resolved = reader(publisher, session).resolve_result(association, events)
        assert resolved.request == fixture.native_input
        assert resolved.result == result


def test_shared_rows_do_not_open_winner_input_and_group_one_file_set_once(
    published, monkeypatch
) -> None:
    publisher, _fixture, _association, events, _outputs, _result = published
    with publisher.sessions.begin() as session:
        resolver = reader(publisher, session)
        original = resolver.reader.read_pinned
        names = []

        def track(_self, **kwargs):
            names.append(kwargs["member_path"])
            assert kwargs["member_path"] != "input.json"
            return original(**kwargs)

        monkeypatch.setattr(type(resolver.reader), "read_pinned", track)
        resolver.verify_shared_rows(tuple((event.owned_job, event) for event in events))
        assert names == ["result.json", "shard.json", "vectors.f32"]


@pytest.mark.parametrize("fault", ("producer", "unapproved", "binary", "wrong_row"))
def test_shared_invalid_producer_lifecycle_bytes_or_row_never_becomes_reusable(
    published, fault: str
) -> None:
    publisher, _fixture, _association, events, outputs, _result = published
    if fault in {"producer", "unapproved"}:
        with publisher.sessions.begin() as session:
            if fault == "producer":
                session.get(JobRecord, outputs.owner_job_id).status = "RUNNING"
            else:
                session.get(
                    ArtifactRevisionRecord, outputs.binary.artifact_revision_id
                ).approved = False
    if fault == "binary":
        with publisher.sessions() as session:
            revision = session.get(ArtifactRevisionRecord, outputs.binary.artifact_revision_id)
            path = Path(revision.nas_path) / "vectors.f32"
        path.write_bytes(b"corrupt")
    if fault == "wrong_row":
        body = events[0].model_dump(mode="json")
        body["receipt"]["row_ref"]["row_index"] = 1
        body["receipt"] = seal(body["receipt"], "receipt_sha256")
        events = (EmbeddingEncodingCompletedEvent.model_validate(seal(body, "event_sha256")),)
    with publisher.sessions.begin() as session, pytest.raises(ValueError):
        reader(publisher, session).verify_shared_rows(
            tuple((event.owned_job, event) for event in events)
        )


def test_other_owned_input_cannot_be_substituted_under_valid_pointer(published) -> None:
    publisher, _fixture, association, _events, _outputs, _result = published
    body = association.model_dump(mode="json")
    body["owned_input_request_sha256"] = "sha256:" + "0" * 64
    changed = LocalEmbeddingLaunchAssociation.model_validate(seal(body, "association_sha256"))
    with (
        publisher.sessions.begin() as session,
        pytest.raises(ValueError, match="OWNED_INPUT_MISMATCH"),
    ):
        reader(publisher, session).resolve_input(changed)


@pytest.mark.parametrize("selection", ("empty", "duplicate"))
def test_empty_or_duplicate_shared_rows_are_not_a_completion_proof(
    published, selection: str
) -> None:
    publisher, _fixture, _association, events, _outputs, _result = published
    chosen = () if selection == "empty" else ((events[0].owned_job, events[0]),) * 2
    with publisher.sessions.begin() as session, pytest.raises(ValueError):
        reader(publisher, session).verify_shared_rows(chosen)
