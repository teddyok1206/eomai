"""Mixed metadata through actual existing owners; no IAM or model execution claim."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_catalog_service.local_embedding_completion_artifacts import (
    resolve_native_embedding_completion,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import content_sha256
from eom_orchestrator.embedding_encoding_reservation_storage import EncodingReservation
from eom_orchestrator.embedding_encoding_reservations import ObservedEncodingReads, _results
from eom_orchestrator.file_set_control_artifacts import ControlFileSetIdentity
from eom_orchestrator.local_embedding_completion_artifacts import NativeEmbeddingCompletionPublisher
from eom_workflow.local_embedding_encoding_dispatch import (
    build_supported_owned_incremental_embedding_input,
    parse_supported_embedding_association,
    parse_supported_embedding_attached,
    parse_supported_embedding_completed,
    parse_supported_embedding_intent,
    parse_supported_embedding_read,
    validate_supported_embedding_association,
    validate_supported_embedding_completions,
)
from eom_workflow.local_embedding_encoding_ownership_v2 import (
    EmbeddingEncodingAttachedEventV2,
    EmbeddingEncodingReadResultV2,
)
from eom_workflow.local_embedding_workflow_receipt_v2 import (
    LocalEmbeddingStepOutputV2,
    parse_supported_local_embedding_step_output,
    parse_supported_local_embedding_workflow_receipt,
    validate_supported_local_embedding_step_output,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_embedding_encoding_reservations import _records
from tests.unit.test_mixed_native_workflow_carriers import carrier_fixture


def test_mixed_numeric_builder_produces_original_unchanged_input() -> None:
    f = carrier_fixture()
    # The authoritative fixture resolves entries from the same pure plan input.
    from tests.unit.test_local_embedding_source_plan_v2 import inputs

    _, resolved, _ = inputs("CONTENT_ONLY")
    built = build_supported_owned_incremental_embedding_input(
        f["plan"],
        resolved.entries,
        f["association"].owned_jobs,
        native_launch_job_id=f["association"].intent.native_launch_job_id,
        resources=f["request"].resource_profile,
    )
    assert built == f["input"]
    assert built.schema_version == "incremental-embedding-input/1.0"
    validate_supported_embedding_association(
        f["association"],
        f["plan"],
        built,
        f["request"].resource_profile,
        f["request"].request_sha256,
    )
    validate_supported_embedding_completions(f["events"], f["association"], built, f["result"])


def test_partial_and_full_registry_reuse_never_enter_numeric_batch_again() -> None:
    from eom_workflow_runner.local_embedding_native_executor import _encoding_requests

    from tests.unit.test_local_embedding_source_plan_v2 import inputs

    f = carrier_fixture()
    jobs = f["association"].owned_jobs
    assert len(jobs) == 2
    reused = frozenset((jobs[0].request.encoding.encoding_sha256,))
    requests = _encoding_requests(f["plan"], reusable_encodings=reused)
    assert tuple(row.encoding for row in requests) == (jobs[1].request.encoding,)
    _, resolved, _ = inputs("CONTENT_ONLY")
    built = build_supported_owned_incremental_embedding_input(
        f["plan"],
        resolved.entries,
        (jobs[1],),
        native_launch_job_id=f["association"].intent.native_launch_job_id,
        resources=f["request"].resource_profile,
    )
    assert tuple(row.encoding for row in built.rows) == (jobs[1].request.encoding,)
    assert built.schema_version == "incremental-embedding-input/1.0"
    assert not _encoding_requests(
        f["plan"],
        reusable_encodings=frozenset(job.request.encoding.encoding_sha256 for job in jobs),
    )


def test_mixed_reservation_read_preserves_original_computational_job() -> None:
    f = carrier_fixture()
    records = tuple(
        EncodingReservation(
            Mock(status="SUCCEEDED"),
            event.owned_job,
            EmbeddingEncodingAttachedEventV2.model_validate(
                seal(
                    {
                        "schema_version": "embedding-encoding-ownership/2.0",
                        "record_type": "ATTACHED",
                        "owned_job": event.owned_job.model_dump(mode="json"),
                        "intent": event.intent.model_dump(mode="json"),
                    },
                    "event_sha256",
                )
            ),
            event,
        )
        for event in f["events"]
    )
    values = _results(records, ObservedEncodingReads(f["association"].intent, frozenset()))
    assert all(isinstance(value, EmbeddingEncodingReadResultV2) for value in values)
    assert tuple(value.completion for value in values) == f["events"]
    assert all(
        value.owned_job.request.schema_version == "embedding-encoding-job/1.0" for value in values
    )


def test_new_reader_borrows_original_owner1_without_retagging() -> None:
    from eom_orchestrator.state_machine import JobState
    from eom_workflow.local_embedding_encoding_job import EmbeddingEncodingReadResult

    f = carrier_fixture()
    records = _records(f["original"].base, JobState.SUCCEEDED)
    values = _results(records, ObservedEncodingReads(f["association"].intent, frozenset()))
    assert all(isinstance(value, EmbeddingEncodingReadResult) for value in values)
    assert tuple(value.completion for value in values) == f["original"].base.completions


@pytest.mark.parametrize("kind", ["association", "attached", "completed", "read", "intent"])
def test_supported_metadata_rejects_copied_unvalidated_extra(kind: str) -> None:
    f = carrier_fixture()
    event = f["events"][0]
    values = {
        "association": (parse_supported_embedding_association, f["association"]),
        "attached": (
            parse_supported_embedding_attached,
            EmbeddingEncodingAttachedEventV2.model_validate(
                seal(
                    {
                        "schema_version": "embedding-encoding-ownership/2.0",
                        "record_type": "ATTACHED",
                        "owned_job": event.owned_job.model_dump(mode="json"),
                        "intent": event.intent.model_dump(mode="json"),
                    },
                    "event_sha256",
                )
            ),
        ),
        "completed": (parse_supported_embedding_completed, event),
        "read": (
            parse_supported_embedding_read,
            EmbeddingEncodingReadResultV2.model_validate(
                seal(
                    {
                        "schema_version": "embedding-encoding-ownership/2.0",
                        "record_type": "READ_RESULT",
                        "owned_job": event.owned_job.model_dump(mode="json"),
                        "owner_intent": event.intent.model_dump(mode="json"),
                        "status": "COMPLETED",
                        "completion": event.model_dump(mode="json"),
                    },
                    "read_sha256",
                )
            ),
        ),
        "intent": (parse_supported_embedding_intent, f["association"].intent),
    }
    parser, value = values[kind]
    assert parser(value) == value
    with pytest.raises(ValueError):
        parser(value.model_copy(update={"unexpected": True}))


def test_completion2_actual_commit_replay_and_catalog_resolution(tmp_path: Path) -> None:
    owner, _ = _publisher(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    owner.settings = replace(owner.settings, workspace_root=workspace)
    publisher = NativeEmbeddingCompletionPublisher(owner, source_commit="a" * 40)
    receipt = carrier_fixture()["receipt"]
    identity = ControlFileSetIdentity(
        receipt.receipt_owner_job_id, "artifact_" + "e" * 32, "rev_" + "e" * 32
    )
    output = publisher.publish(receipt, identity=identity)
    assert isinstance(output, LocalEmbeddingStepOutputV2)
    assert publisher.publish(receipt, identity=identity) == output
    assert validate_supported_local_embedding_step_output(output, receipt) == output
    with owner.sessions.begin() as session:
        resolved = resolve_native_embedding_completion(
            session, CatalogSettings(nas_artifact_root=owner.settings.nas_artifact_root), output
        )
        assert resolved == receipt
    assert parse_supported_local_embedding_step_output(output) == output
    assert parse_supported_local_embedding_workflow_receipt(receipt) == receipt


def test_completion2_cannot_be_parsed_or_validated_as_family1() -> None:
    f = carrier_fixture()
    with pytest.raises(ValueError):
        from tests.unit.local_embedding_workflow_receipt_fixtures import receipt_fixture

        validate_supported_local_embedding_step_output(f["output"], receipt_fixture().receipt)
    malformed = f["output"].model_dump(mode="json") | {
        "schema_version": "local-embedding-step-output/1.0"
    }
    malformed["output_sha256"] = content_sha256(
        {key: value for key, value in malformed.items() if key != "output_sha256"}
    )
    with pytest.raises(ValueError):
        parse_supported_local_embedding_step_output(malformed)
