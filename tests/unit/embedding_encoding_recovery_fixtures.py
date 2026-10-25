"""Synthetic root-retirement references; these are not OS or maintenance authority."""

from eom_workflow.embedding_encoding_recovery import (
    ENCODING_RECOVERY_PROTOCOL,
    EmbeddingEncodingRetryDeclaration,
    KnownFailedEmbeddingEncoding,
)
from eom_workflow.embedding_unpublished_recovery import UnpublishedEmbeddingEncodingFailure
from eom_workflow.local_embedding_encoding_job import EmbeddingEncodingJobReference

from tests.unit.inference_transfer_embedding_fixtures import seal


def known_failure(owned, native_launch_job_id):
    return KnownFailedEmbeddingEncoding.model_validate(
        seal(
            dict(
                schema_version=ENCODING_RECOVERY_PROTOCOL,
                record_type="FAILURE",
                owned_job=owned.model_dump(mode="json"),
                native_launch_job_id=native_launch_job_id,
                root=dict(
                    allocation_attempt_id="embeddingallocation_" + "e" * 32,
                    invocation_id="e" * 32,
                    retirement_sha256="sha256:" + "e" * 64,
                    retired_at="2026-10-25T05:31:15.046825Z",
                    parent_plan_job_id="job_" + "f" * 32,
                    parent_request_sha256="sha256:" + "f" * 64,
                    original_outcome="FAILED",
                    stored_descriptors=0,
                ),
            ),
            "event_sha256",
        )
    )


def declaration(owned, *, seed="f", attempt=1, predecessor=None, predecessor_failure_sha256=None):
    successor = EmbeddingEncodingJobReference(
        job_id="job_" + seed * 32,
        request_sha256=owned.request.request_sha256,
        allocated_artifact_id="artifact_" + seed * 32,
        allocated_artifact_revision_id="rev_" + seed * 32,
    )
    predecessor = predecessor or owned.job_reference
    return EmbeddingEncodingRetryDeclaration.model_validate(
        seal(
            dict(
                schema_version=ENCODING_RECOVERY_PROTOCOL,
                record_type="RETRY",
                logical_job=owned.job_reference.model_dump(mode="json"),
                predecessor=predecessor.model_dump(mode="json"),
                successor=successor.model_dump(mode="json"),
                encoding_sha256=owned.request.encoding.encoding_sha256,
                attempt=attempt,
                predecessor_failure_sha256=predecessor_failure_sha256 or "sha256:" + "e" * 64,
            ),
            "event_sha256",
        )
    )


def unpublished_failure(owned, native_launch_job_id):
    body = known_failure(owned, native_launch_job_id).model_dump(mode="json")
    body["schema_version"] = "embedding-encoding-recovery/2.0"
    body["root"] |= dict(
        original_outcome="SUCCEEDED",
        controller_invocation_id="c" * 32,
        controller_outcome="FAILED",
    )
    return UnpublishedEmbeddingEncodingFailure.model_validate(seal(body, "event_sha256"))
