"""Synthetic pointer metadata only; no current source, authentication or Artifact grant."""

from __future__ import annotations

from dataclasses import replace

from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingEncodingIdentity,
    embedding_input_set_sha256,
)
from eom_identifiers import content_sha256
from eom_workflow.local_embedding_encoding_job import (
    EmbeddingEncodingJobReference,
    EmbeddingEncodingJobRequest,
    EmbeddingEncodingReadResult,
    LocalEmbeddingLaunchIntent,
    LocalEmbeddingOwnedJob,
)

from tests.unit.inference_transfer_embedding_fixtures import (
    embedding_input,
    embedding_result,
    encoding_identity,
    seal,
)
from tests.unit.local_embedding_admission_fixtures import (
    NativeAdmissionFixture,
    member,
    native_fixture,
)


def reservation_fixture(*seeds: str, ordinal: int = 1) -> NativeAdmissionFixture:
    fixture = native_fixture(*seeds)
    body = fixture.association.intent.model_dump(mode="json") | {
        "workflow_id": "workflow_" + f"{ordinal:032x}",
        "step_run_id": "steprun_" + f"{ordinal:032x}",
        "native_launch_job_id": "job_" + f"{ordinal:032x}",
        "command_id": "wfcmd_" + f"{ordinal:032x}",
    }
    intent = type(fixture.association.intent).model_validate(seal(body, "intent_sha256"))
    fixture = replace(
        fixture, association=fixture.association.model_copy(update={"intent": intent})
    )
    return fixture_for_jobs(fixture, fixture.association.owned_jobs)


def fixture_for_jobs(
    fixture: NativeAdmissionFixture,
    jobs: tuple[LocalEmbeddingOwnedJob, ...],
) -> NativeAdmissionFixture:
    keys = {job.request.encoding.encoding_sha256 for job in jobs}
    rows = tuple(row for row in fixture.native_input.rows if row.encoding.encoding_sha256 in keys)
    body = fixture.native_input.model_dump(mode="json") | {
        "job_id": fixture.association.intent.native_launch_job_id,
        "rows": [row.model_dump(mode="json") for row in rows],
        "input_set_sha256": embedding_input_set_sha256(tuple(row.encoding for row in rows)),
    }
    native_input = type(fixture.native_input).model_validate(seal(body, "request_sha256"))
    input_pointer = member(
        "input.json",
        fixture.association.owned_input.schema_ref,
        native_input.model_dump(mode="json"),
        "7",
    )
    association = type(fixture.association).model_validate(
        seal(
            fixture.association.model_dump(mode="json")
            | {
                "owned_jobs": [job.model_dump(mode="json") for job in jobs],
                "owned_input": input_pointer.model_dump(mode="json"),
                "owned_input_request_sha256": native_input.request_sha256,
                "owned_input_set_sha256": native_input.input_set_sha256,
            },
            "association_sha256",
        )
    )
    result = embedding_result(native_input)
    completions = []
    for row_index, job in enumerate(jobs):
        template = fixture.completions[0].model_dump(mode="json")
        shard_pointer = member(
            "shard.json",
            template["receipt"]["shard_manifest"]["schema_ref"],
            result.shard.model_dump(mode="json"),
        ).model_copy(
            update={
                "artifact_id": "artifact_"
                + association.intent.native_launch_job_id.removeprefix("job_"),
                "artifact_revision_id": "rev_"
                + association.intent.native_launch_job_id.removeprefix("job_"),
            }
        )
        receipt = seal(
            template["receipt"]
            | {
                "native_launch_job_id": association.intent.native_launch_job_id,
                "result_manifest": member(
                    "result.json",
                    template["receipt"]["result_manifest"]["schema_ref"],
                    result.model_dump(mode="json"),
                )
                .model_copy(
                    update={
                        "artifact_id": shard_pointer.artifact_id,
                        "artifact_revision_id": shard_pointer.artifact_revision_id,
                    }
                )
                .model_dump(mode="json"),
                "result_sha256": result.result_sha256,
                "shard_manifest": shard_pointer.model_dump(mode="json"),
                "shard_sha256": result.shard.shard_sha256,
                "binary_member": shard_pointer.model_dump(mode="json")
                | {
                    "member_path": "vectors.f32",
                    "schema_ref": template["receipt"]["binary_member"]["schema_ref"],
                    "media_type": "application/octet-stream",
                    "sha256": result.shard.binary.sha256,
                },
                "row_ref": {
                    "shard_manifest": shard_pointer.model_dump(mode="json"),
                    "row_index": row_index,
                    "encoding_sha256": job.request.encoding.encoding_sha256,
                },
            },
            "receipt_sha256",
        )
        completions.append(
            type(fixture.completions[0]).model_validate(
                seal(
                    template
                    | {
                        "owned_job": job.model_dump(mode="json"),
                        "intent": association.intent.model_dump(mode="json"),
                        "launch_association_sha256": association.association_sha256,
                        "receipt": receipt,
                    },
                    "event_sha256",
                )
            )
        )
    return replace(
        fixture,
        association=association,
        native_input=native_input,
        result=result,
        completions=tuple(completions),
    )


def large_completion_fixture(count: int) -> NativeAdmissionFixture:
    fixture = native_fixture("a")
    native_input = embedding_input(
        *(f"synthetic row {number}" for number in range(count)), space=fixture.native_input.space
    )
    jobs = []
    for number, row in enumerate(native_input.rows, start=16):
        request = EmbeddingEncodingJobRequest.model_validate(
            seal(
                {
                    "schema_version": "embedding-encoding-job/1.0",
                    "record_type": "REQUEST",
                    "purpose": "LOCAL_EMBEDDING",
                    "space": native_input.space.model_dump(mode="json"),
                    "encoding": row.encoding.model_dump(mode="json"),
                },
                "request_sha256",
            )
        )
        jobs.append(
            LocalEmbeddingOwnedJob(
                job_reference=EmbeddingEncodingJobReference(
                    job_id="job_" + f"{number:032x}",
                    request_sha256=request.request_sha256,
                    allocated_artifact_id="artifact_" + f"{number:032x}",
                    allocated_artifact_revision_id="rev_" + f"{number:032x}",
                ),
                request=request,
            )
        )
    return fixture_for_jobs(replace(fixture, native_input=native_input), tuple(jobs))


def requests(fixture: NativeAdmissionFixture) -> tuple[EmbeddingEncodingJobRequest, ...]:
    return tuple(job.request for job in fixture.association.owned_jobs)


def partition_fixture(fixture: NativeAdmissionFixture, partition: str) -> NativeAdmissionFixture:
    """Isolate disposable computational keys without changing released runtime identity."""
    by_key: dict[str, EmbeddingEncodingIdentity] = {
        row.encoding.encoding_sha256: encoding_identity(
            row.text, fixture.native_input.space, storage_partition=partition
        )
        for row in fixture.native_input.rows
    }
    plan_body = fixture.plan.model_dump(mode="json")
    plan_body["namespace"]["storage_partition"] = partition
    for demand in plan_body["demands"]:
        demand["encoding"] = by_key[demand["encoding"]["encoding_sha256"]].model_dump(mode="json")
    encodings = tuple(sorted(by_key.values(), key=lambda value: value.encoding_sha256))
    plan_body["encoding_set_sha256"] = embedding_input_set_sha256(encodings)
    plan = type(fixture.plan).model_validate(seal(plan_body, "plan_sha256"))
    source_pointer = member(
        "source-plan.json", fixture.request.source_plan.schema_ref, plan.model_dump(mode="json")
    )
    request = type(fixture.request).model_validate(
        seal(
            fixture.request.model_dump(mode="json")
            | {
                "namespace": plan.namespace.model_dump(mode="json"),
                "source_plan": source_pointer.model_dump(mode="json"),
                "source_plan_sha256": plan.plan_sha256,
            },
            "request_sha256",
        )
    )
    intent = type(fixture.association.intent).model_validate(
        seal(
            fixture.association.intent.model_dump(mode="json")
            | {
                "workflow_request_sha256": request.request_sha256,
                "source_plan": source_pointer.model_dump(mode="json"),
                "source_plan_sha256": plan.plan_sha256,
            },
            "intent_sha256",
        )
    )
    input_body = fixture.native_input.model_dump(mode="json")
    for row in input_body["rows"]:
        row["encoding"] = by_key[row["encoding"]["encoding_sha256"]].model_dump(mode="json")
    input_body["rows"].sort(key=lambda row: row["encoding"]["encoding_sha256"])
    input_body["input_set_sha256"] = embedding_input_set_sha256(encodings)
    native_input = type(fixture.native_input).model_validate(seal(input_body, "request_sha256"))
    jobs = []
    for job in fixture.association.owned_jobs:
        computational = EmbeddingEncodingJobRequest.model_validate(
            seal(
                job.request.model_dump(mode="json")
                | {
                    "encoding": by_key[job.request.encoding.encoding_sha256].model_dump(mode="json")
                },
                "request_sha256",
            )
        )
        jobs.append(
            LocalEmbeddingOwnedJob(
                job_reference=job.job_reference.model_copy(
                    update={"request_sha256": computational.request_sha256}
                ),
                request=computational,
            )
        )
    jobs.sort(key=lambda job: job.request.encoding.encoding_sha256)
    return fixture_for_jobs(
        replace(
            fixture,
            plan=plan,
            request=request,
            native_input=native_input,
            association=fixture.association.model_copy(update={"intent": intent}),
        ),
        tuple(jobs),
    )


def references(fixture: NativeAdmissionFixture) -> tuple[EmbeddingEncodingJobReference, ...]:
    return tuple(
        sorted(
            (job.job_reference for job in fixture.association.owned_jobs),
            key=lambda ref: ref.job_id,
        )
    )


def read_result(
    job: LocalEmbeddingOwnedJob,
    intent: LocalEmbeddingLaunchIntent,
) -> EmbeddingEncodingReadResult:
    body = {
        "schema_version": "embedding-encoding-job/1.0",
        "record_type": "READ_RESULT",
        "owned_job": job.model_dump(mode="json"),
        "owner_intent": intent.model_dump(mode="json"),
        "status": "OWNED",
        "completion": None,
    }
    return EmbeddingEncodingReadResult.model_validate(body | {"read_sha256": content_sha256(body)})
