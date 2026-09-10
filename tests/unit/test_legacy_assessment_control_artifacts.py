from __future__ import annotations

from typing import cast

import pytest
from eom_catalog_contracts import PdfLearningItemCompletionShard, completion_identity_sha256
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.control_artifacts import (
    ControlArtifactPublisher,
    PublishedControlArtifact,
)
from eom_orchestrator.legacy_assessment_control_artifacts import (
    COMPLETION_RECEIPT_ARTIFACT_TYPE,
    COMPLETION_RECEIPT_SCHEMA_REF_V3,
    COMPLETION_SHARD_ARTIFACT_TYPE,
    LegacyAssessmentControlArtifactPublisher,
)
from eom_workflow import ControlArtifactPointer
from test_pdf_learning_completion import _receipt, _v12_receipt, validate_payload


class _RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def publish_bytes(self, **values: object) -> PublishedControlArtifact:
        self.calls.append(values)
        payload = values["payload"]
        assert isinstance(payload, bytes)
        index = len(self.calls)
        return PublishedControlArtifact(
            job_id="job_" + f"{index:032x}",
            pointer=ControlArtifactPointer(
                artifact_id="artifact_" + f"{index:032x}",
                artifact_revision_id="rev_" + f"{index:032x}",
                sha256=sha256_bytes(payload),
                schema_ref=str(values["schema_ref"]),
                media_type=str(values["media_type"]),
                logical_name=str(values["logical_name"]),
            ),
            manifest_sha256="sha256:" + f"{index:064x}",
        )


def test_completion_components_use_bounded_full_identity_publications() -> None:
    payload = _receipt()
    receipt = validate_payload(payload)
    shard = PdfLearningItemCompletionShard.model_validate(payload.shard_documents[0])
    recording = _RecordingPublisher()
    adapter = LegacyAssessmentControlArtifactPublisher(
        cast(ControlArtifactPublisher, recording),
        source_release=receipt.source_release,
    )

    shard_pointer = adapter.commit_completion_shard(
        shard,
        completion_map_sha256=receipt.completion_map_sha256,
        created_at=receipt.observed_at_utc,
    )
    receipt_pointer = adapter.commit_completion_receipt(
        receipt,
        completion_identity=completion_identity_sha256(receipt),
    )

    shard_call, receipt_call = recording.calls
    assert shard_call["artifact_type"] == COMPLETION_SHARD_ARTIFACT_TYPE
    assert receipt_call["artifact_type"] == COMPLETION_RECEIPT_ARTIFACT_TYPE
    assert len(cast(bytes, shard_call["payload"])) < 2 * 1024 * 1024
    assert len(cast(bytes, receipt_call["payload"])) < 2 * 1024 * 1024
    expected_key_hash = content_sha256(
        {
            "completion_map_sha256": receipt.completion_map_sha256,
            "shard_index": shard.shard_index,
            "shard_sha256": shard.shard_sha256,
        }
    ).removeprefix("sha256:")
    assert shard_call["idempotency_key"] == ("pdf-learning-shard:" + expected_key_hash)
    assert len(str(shard_call["idempotency_key"])) == len("pdf-learning-shard:") + 64
    assert shard_pointer.sha256 == sha256_bytes(cast(bytes, shard_call["payload"]))
    assert receipt_pointer.sha256 == sha256_bytes(cast(bytes, receipt_call["payload"]))


def test_completion_receipt_rejects_source_release_drift_before_publication() -> None:
    payload = _receipt()
    receipt = validate_payload(payload)
    recording = _RecordingPublisher()
    adapter = LegacyAssessmentControlArtifactPublisher(
        cast(ControlArtifactPublisher, recording),
        source_release=receipt.source_release.model_copy(update={"git_tree": "f" * 40}),
    )

    with pytest.raises(ValueError, match="installed admission"):
        adapter.commit_completion_receipt(
            receipt,
            completion_identity=completion_identity_sha256(receipt),
        )

    assert recording.calls == []


def test_v12_completion_receipt_publishes_with_exact_v3_schema_pointer() -> None:
    receipt = validate_payload(_v12_receipt())
    recording = _RecordingPublisher()
    adapter = LegacyAssessmentControlArtifactPublisher(
        cast(ControlArtifactPublisher, recording),
        source_release=receipt.source_release,
    )

    pointer = adapter.commit_completion_receipt(
        receipt,
        completion_identity=completion_identity_sha256(receipt),
    )

    assert recording.calls[0]["schema_ref"] == COMPLETION_RECEIPT_SCHEMA_REF_V3
    assert pointer.schema_ref == COMPLETION_RECEIPT_SCHEMA_REF_V3
