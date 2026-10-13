"""Per-encoding existing-Job contracts and pointer-only owner ports, without IO."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, Protocol

from eom_catalog_contracts.inference_transfer_embedding import (
    INPUT_SCHEMA_REF,
    RESULT_SCHEMA_REF,
    SHARD_SCHEMA_REF,
    EmbeddingEncodingIdentity,
    EmbeddingSpace,
    EmbeddingTextInput,
    EmbeddingVectorRowRef,
    IncrementalEmbeddingInput,
    IncrementalEmbeddingResult,
    embedding_input_set_sha256,
    parse_incremental_embedding_input,
    parse_incremental_embedding_result,
    validate_incremental_embedding_result,
)
from eom_catalog_contracts.inference_transfer_experiment import (
    StagedExperimentEntry,
    experiment_view_text,
)
from eom_catalog_contracts.models import Sha256
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, TypeAdapter, model_validator

from eom_workflow.local_embedding_execution_policy import LocalEmbeddingResourceProfile
from eom_workflow.local_embedding_source_plan import (
    LOCAL_EMBEDDING_SOURCE_PLAN_SCHEMA_REF,
    LocalEmbeddingSourcePlan,
    parse_local_embedding_source_plan,
    validate_local_embedding_plan_entries,
)
from eom_workflow.models import ArtifactId, JobId, RevisionId, StepRunId, WorkflowId
from eom_workflow.schemas import (
    LocalEmbeddingAdmissionContractError,
    NativeEmbeddingContract,
    validate_local_embedding_admission_message,
)

EMBEDDING_ENCODING_JOB_SCHEMA_REF = "eom://schemas/workflow/embedding-encoding-job/1.0"
EMBEDDING_ENCODING_IDEMPOTENCY_PREFIX = "embedding-encode:"


def _hash(value: NativeEmbeddingContract, field: str) -> None:
    if len(canonical_json_bytes(value.model_dump(mode="json"))) > 64 * 1024**2:
        raise ValueError("native encoding metadata exceeds its byte bound")
    if getattr(value, field) != content_sha256(value.model_dump(mode="json", exclude={field})):
        raise ValueError("native encoding metadata canonical hash differs")


def _member(
    pointer: ArtifactMemberPointer, path: str, schema: str, media: str = "application/json"
) -> None:
    if pointer.member_path != path or pointer.schema_ref != schema or pointer.media_type != media:
        raise ValueError("native encoding Artifact member closure differs")


class EmbeddingEncodingJobRequest(NativeEmbeddingContract):
    """Computational key excludes actor, source, Graph, batch, launch and timestamps."""

    schema_version: Literal["embedding-encoding-job/1.0"] = "embedding-encoding-job/1.0"
    record_type: Literal["REQUEST"] = "REQUEST"
    purpose: Literal["LOCAL_EMBEDDING"] = "LOCAL_EMBEDDING"
    space: EmbeddingSpace
    encoding: EmbeddingEncodingIdentity
    request_sha256: Sha256

    @property
    def idempotency_key(self) -> str:
        return EMBEDDING_ENCODING_IDEMPOTENCY_PREFIX + self.encoding.encoding_sha256

    @model_validator(mode="after")
    def exact_request(self) -> EmbeddingEncodingJobRequest:
        if (
            self.space.purpose != "DOCUMENT"
            or self.encoding.space_sha256 != self.space.space_sha256
        ):
            raise ValueError("encoding Job requires its exact document space")
        _hash(self, "request_sha256")
        return self


class EmbeddingEncodingJobReference(NativeEmbeddingContract):
    """Original existing Job allocations remain immutable and unused by shared output."""

    job_id: JobId
    request_sha256: Sha256
    allocated_artifact_id: ArtifactId
    allocated_artifact_revision_id: RevisionId


class LocalEmbeddingLaunchIntent(NativeEmbeddingContract):
    """Exact original intent and public fence audit, never a persisted lease credential."""

    workflow_id: WorkflowId
    step_run_id: StepRunId
    step_key: Literal["encode_batch"] = "encode_batch"
    attempt: int = Field(ge=1, le=1, strict=True)
    native_launch_job_id: JobId
    workflow_request_sha256: Sha256
    source_plan: ArtifactMemberPointer
    source_plan_sha256: Sha256
    resource_profile_sha256: Sha256
    command_id: str = Field(pattern=r"^wfcmd_[0-9a-f]{32}$")
    runner_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    lease_generation: int = Field(ge=1, le=2147483647, strict=True)
    intent_sha256: Sha256

    @model_validator(mode="after")
    def exact_intent(self) -> LocalEmbeddingLaunchIntent:
        _member(self.source_plan, "source-plan.json", LOCAL_EMBEDDING_SOURCE_PLAN_SCHEMA_REF)
        _hash(self, "intent_sha256")
        return self


class LocalEmbeddingOwnedJob(NativeEmbeddingContract):
    job_reference: EmbeddingEncodingJobReference
    request: EmbeddingEncodingJobRequest

    @model_validator(mode="after")
    def exact_job_request(self) -> LocalEmbeddingOwnedJob:
        if self.job_reference.request_sha256 != self.request.request_sha256:
            raise ValueError("encoding Job reference differs from its immutable request")
        return self


class LocalEmbeddingLaunchAssociation(NativeEmbeddingContract):
    """The owned subset is a separate immutable value, not a mutated original plan."""

    schema_version: Literal["embedding-encoding-job/1.0"] = "embedding-encoding-job/1.0"
    record_type: Literal["LAUNCH_ASSOCIATION"] = "LAUNCH_ASSOCIATION"
    intent: LocalEmbeddingLaunchIntent
    owned_jobs: tuple[LocalEmbeddingOwnedJob, ...] = Field(min_length=1, max_length=1024)
    owned_input: ArtifactMemberPointer
    owned_input_request_sha256: Sha256
    owned_input_set_sha256: Sha256
    association_sha256: Sha256

    @model_validator(mode="after")
    def exact_owned_subset(self) -> LocalEmbeddingLaunchAssociation:
        _member(self.owned_input, "input.json", INPUT_SCHEMA_REF)
        encodings = tuple(job.request.encoding for job in self.owned_jobs)
        keys = tuple(encoding.encoding_sha256 for encoding in encodings)
        if keys != tuple(
            sorted(set(keys))
        ) or self.owned_input_set_sha256 != embedding_input_set_sha256(encodings):
            raise ValueError("owned encoding subset must be sorted, unique and exact")
        for field in ("job_id", "allocated_artifact_id", "allocated_artifact_revision_id"):
            ids = tuple(getattr(job.job_reference, field) for job in self.owned_jobs)
            if len(ids) != len(set(ids)):
                raise ValueError("owned subset repeats existing Job allocations")
        if (
            self.intent.native_launch_job_id
            in {job.job_reference.job_id for job in self.owned_jobs}
            or len({encoding.storage_partition for encoding in encodings}) != 1
            or any(job.request.space != self.owned_jobs[0].request.space for job in self.owned_jobs)
        ):
            raise ValueError("owned subset mixes launch/reservation Jobs, space or partition")
        _hash(self, "association_sha256")
        return self


class EmbeddingSharedRowReceipt(NativeEmbeddingContract):
    """One canonical result/shard/binary file set and row; never vector bytes."""

    native_launch_job_id: JobId
    result_manifest: ArtifactMemberPointer
    result_sha256: Sha256
    shard_manifest: ArtifactMemberPointer
    shard_sha256: Sha256
    binary_member: ArtifactMemberPointer
    row_ref: EmbeddingVectorRowRef
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def exact_file_set(self) -> EmbeddingSharedRowReceipt:
        _member(self.result_manifest, "result.json", RESULT_SCHEMA_REF)
        _member(self.shard_manifest, "shard.json", SHARD_SCHEMA_REF)
        _member(
            self.binary_member,
            "vectors.f32",
            "eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0",
            "application/octet-stream",
        )
        if (
            len(
                {
                    (p.artifact_id, p.artifact_revision_id)
                    for p in (self.result_manifest, self.shard_manifest, self.binary_member)
                }
            )
            != 1
            or self.row_ref.shard_manifest != self.shard_manifest
        ):
            raise ValueError("shared row receipt mixes file sets or shard pointers")
        _hash(self, "receipt_sha256")
        return self


class EmbeddingEncodingAttachedEvent(NativeEmbeddingContract):
    schema_version: Literal["embedding-encoding-job/1.0"] = "embedding-encoding-job/1.0"
    record_type: Literal["ATTACHED"] = "ATTACHED"
    owned_job: LocalEmbeddingOwnedJob
    intent: LocalEmbeddingLaunchIntent
    event_sha256: Sha256

    @model_validator(mode="after")
    def exact_attachment(self) -> EmbeddingEncodingAttachedEvent:
        if self.owned_job.job_reference.job_id == self.intent.native_launch_job_id:
            raise ValueError("encoding reservation and native launch are distinct Jobs")
        _hash(self, "event_sha256")
        return self


class EmbeddingEncodingCompletedEvent(NativeEmbeddingContract):
    schema_version: Literal["embedding-encoding-job/1.0"] = "embedding-encoding-job/1.0"
    record_type: Literal["COMPLETED"] = "COMPLETED"
    owned_job: LocalEmbeddingOwnedJob
    intent: LocalEmbeddingLaunchIntent
    launch_association_sha256: Sha256
    receipt: EmbeddingSharedRowReceipt
    event_sha256: Sha256

    @model_validator(mode="after")
    def exact_completion(self) -> EmbeddingEncodingCompletedEvent:
        reference = self.owned_job.job_reference
        if (
            reference.job_id == self.intent.native_launch_job_id
            or self.receipt.native_launch_job_id != self.intent.native_launch_job_id
            or self.receipt.row_ref.encoding_sha256
            != self.owned_job.request.encoding.encoding_sha256
            or reference.allocated_artifact_id == self.receipt.result_manifest.artifact_id
            or reference.allocated_artifact_revision_id
            == self.receipt.result_manifest.artifact_revision_id
        ):
            raise ValueError("encoding completion changes Job allocation, launch or row identity")
        _hash(self, "event_sha256")
        return self


class EmbeddingEncodingReadResult(NativeEmbeddingContract):
    """Owner-observed state; OWNED/BORROWED labels do not establish caller authority."""

    schema_version: Literal["embedding-encoding-job/1.0"] = "embedding-encoding-job/1.0"
    record_type: Literal["READ_RESULT"] = "READ_RESULT"
    owned_job: LocalEmbeddingOwnedJob
    owner_intent: LocalEmbeddingLaunchIntent
    status: Literal["OWNED", "BORROWED", "COMPLETED", "FAILED", "CANCELLED", "UNCERTAIN"]
    completion: EmbeddingEncodingCompletedEvent | None
    read_sha256: Sha256

    @model_validator(mode="after")
    def exact_state_receipt(self) -> EmbeddingEncodingReadResult:
        if (self.status == "COMPLETED") != (self.completion is not None):
            raise ValueError("encoding read state and completion differ")
        if self.completion is not None and (
            self.completion.owned_job != self.owned_job
            or self.completion.intent != self.owner_intent
        ):
            raise ValueError("encoding read result has a foreign owner or completion")
        if self.owned_job.job_reference.job_id == self.owner_intent.native_launch_job_id:
            raise ValueError("encoding read result conflates launch/reservation Job")
        _hash(self, "read_sha256")
        return self


type EmbeddingEncodingJobMessage = Annotated[
    EmbeddingEncodingJobRequest
    | LocalEmbeddingLaunchAssociation
    | EmbeddingEncodingAttachedEvent
    | EmbeddingEncodingCompletedEvent
    | EmbeddingEncodingReadResult,
    Field(discriminator="record_type"),
]
_MESSAGE_ADAPTER: TypeAdapter[EmbeddingEncodingJobMessage] = TypeAdapter(
    EmbeddingEncodingJobMessage
)


def parse_embedding_encoding_job_message(value: object) -> EmbeddingEncodingJobMessage:
    validate_local_embedding_admission_message("encoding-job", value)
    try:
        return _MESSAGE_ADAPTER.validate_python(value)
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


class EmbeddingEncodingJobOwnerPort(Protocol):
    """Implemented only by Orchestrator in a current authenticated, lease-fenced owner scope.

    Reserve/attach is one short atomic existing-Job transaction; implementations
    admit only 1..1,024 sorted unique requests from the bounded source plan,
    return originals on replay and conflict on changed immutable intent. Read
    references/completion batches have the same bounds. This Protocol has no
    implementation/default and takes no authority DTO or worker.
    """

    def reserve_and_attach(
        self, requests: tuple[EmbeddingEncodingJobRequest, ...], intent: LocalEmbeddingLaunchIntent
    ) -> tuple[EmbeddingEncodingReadResult, ...]: ...

    def bind_launch(self, association: LocalEmbeddingLaunchAssociation) -> None: ...

    def complete(
        self, events: tuple[EmbeddingEncodingCompletedEvent, ...]
    ) -> tuple[EmbeddingEncodingReadResult, ...]: ...

    def read(
        self, references: tuple[EmbeddingEncodingJobReference, ...]
    ) -> tuple[EmbeddingEncodingReadResult, ...]: ...


def build_owned_incremental_embedding_input(
    plan: LocalEmbeddingSourcePlan,
    entries: tuple[StagedExperimentEntry, ...],
    owned_jobs: tuple[LocalEmbeddingOwnedJob, ...],
    *,
    native_launch_job_id: str,
    resources: LocalEmbeddingResourceProfile,
) -> IncrementalEmbeddingInput:
    """Materialize only this exact reserved subset, never mutate the original plan.

    Current source/command authority belongs to Catalog and the reservation owner.
    This pure builder validates their values. Source lookup/dedup is O(N), plus
    input-byte hashing and stable encoding order; no worker or storage IO occurs.
    """
    plan = parse_local_embedding_source_plan(plan.model_dump(mode="json"))
    resources = LocalEmbeddingResourceProfile.model_validate(resources)
    native_launch_job_id = TypeAdapter(JobId).validate_python(native_launch_job_id, strict=True)
    if type(owned_jobs) is not tuple or not 1 <= len(owned_jobs) <= 1024:
        raise ValueError("owned numerical input requires a nonempty bounded reservation tuple")
    checked = tuple(LocalEmbeddingOwnedJob.model_validate(job) for job in owned_jobs)
    keys = tuple(job.request.encoding.encoding_sha256 for job in checked)
    planned = {d.encoding.encoding_sha256: d.encoding for d in plan.demands}
    if (
        keys != tuple(sorted(set(keys)))
        or resources.device != plan.space.runtime.device
        or any(
            job.request.space != plan.space
            or planned.get(job.request.encoding.encoding_sha256) != job.request.encoding
            or job.job_reference.job_id == native_launch_job_id
            for job in checked
        )
        or any(
            len({getattr(job.job_reference, field) for job in checked}) != len(checked)
            for field in ("job_id", "allocated_artifact_id", "allocated_artifact_revision_id")
        )
    ):
        raise ValueError(
            "owned numerical input differs from plan, space or distinct Job allocations"
        )
    validate_local_embedding_plan_entries(plan, entries)
    by_source = {entry.profile.source_basis.source.item_revision_id: entry for entry in entries}
    selected = set(keys)
    by_encoding: dict[str, EmbeddingTextInput] = {}
    for demand in plan.demands:
        key = demand.encoding.encoding_sha256
        if key not in selected:
            continue
        text = experiment_view_text(by_source[demand.source_revision_id], plan.namespace.view)
        if text is None or not text.strip():
            raise ValueError("owned numerical input has no exact materialized view")
        row = EmbeddingTextInput(encoding=demand.encoding, text=text)
        prior = by_encoding.get(key)
        if prior is not None and prior != row:
            raise ValueError("owned numerical input has an encoding collision")
        by_encoding[key] = row
    if set(by_encoding) != selected:
        raise ValueError("owned numerical input is not exactly covered by current entries")
    rows = tuple(by_encoding[key] for key in keys)
    body = {
        "schema_version": "incremental-embedding-input/1.0",
        "job_id": native_launch_job_id,
        "space": plan.space.model_dump(mode="json"),
        "rows": [row.model_dump(mode="json") for row in rows],
        "batch_size": resources.batch_size,
        "threads": resources.threads,
        "input_set_sha256": embedding_input_set_sha256(tuple(row.encoding for row in rows)),
    }
    return parse_incremental_embedding_input(body | {"request_sha256": content_sha256(body)})


def validate_local_embedding_launch_association(
    association: LocalEmbeddingLaunchAssociation,
    plan: LocalEmbeddingSourcePlan,
    owned_input: IncrementalEmbeddingInput,
    resources: LocalEmbeddingResourceProfile,
    workflow_request_sha256: str,
) -> None:
    """Check an exact owned subset; never mutate/reinterpret Workflow request 1.0."""
    association = LocalEmbeddingLaunchAssociation.model_validate(association)
    plan = LocalEmbeddingSourcePlan.model_validate(plan)
    plan = parse_local_embedding_source_plan(plan.model_dump(mode="json"))
    owned_input = parse_incremental_embedding_input(owned_input.model_dump(mode="json"))
    resources = LocalEmbeddingResourceProfile.model_validate(resources)
    encodings = tuple(job.request.encoding for job in association.owned_jobs)
    planned = {demand.encoding.encoding_sha256: demand.encoding for demand in plan.demands}
    if (
        association.intent.workflow_request_sha256 != workflow_request_sha256
        or association.intent.source_plan_sha256 != plan.plan_sha256
        or association.intent.source_plan.sha256
        != sha256_bytes(canonical_json_bytes(plan.model_dump(mode="json")))
        or association.intent.resource_profile_sha256 != resources.resource_profile_sha256
        or association.owned_input.sha256
        != sha256_bytes(canonical_json_bytes(owned_input.model_dump(mode="json")))
        or association.owned_input_request_sha256 != owned_input.request_sha256
        or association.owned_input_set_sha256 != owned_input.input_set_sha256
        or association.intent.native_launch_job_id != owned_input.job_id
        or encodings != tuple(row.encoding for row in owned_input.rows)
        or any(planned.get(row.encoding_sha256) != row for row in encodings)
        or owned_input.space != plan.space
        or owned_input.space != association.owned_jobs[0].request.space
        or resources.device != owned_input.space.runtime.device
        or owned_input.batch_size != resources.batch_size
        or owned_input.threads != resources.threads
    ):
        raise ValueError(
            "native launch association differs from original plan or exact owned input"
        )


@dataclass(frozen=True, slots=True)
class _CompletionContext:
    association: LocalEmbeddingLaunchAssociation
    owned_input: IncrementalEmbeddingInput
    result: IncrementalEmbeddingResult
    by_encoding: dict[str, LocalEmbeddingOwnedJob]
    input_raw_sha256: str
    result_raw_sha256: str
    shard_raw_sha256: str


def _completion_context(
    association: LocalEmbeddingLaunchAssociation,
    owned_input: IncrementalEmbeddingInput,
    result: IncrementalEmbeddingResult,
) -> _CompletionContext:
    association = LocalEmbeddingLaunchAssociation.model_validate(association)
    owned_input = parse_incremental_embedding_input(owned_input.model_dump(mode="json"))
    result = parse_incremental_embedding_result(result.model_dump(mode="json"))
    # Preserve the existing public Catalog rule and its constant-two parse pipeline.
    # A batch runs this once, not once for each row in the same immutable file set.
    validate_incremental_embedding_result(owned_input, result)
    if tuple(job.request.encoding for job in association.owned_jobs) != tuple(
        row.encoding for row in owned_input.rows
    ):
        raise ValueError(
            "encoding completion differs from exact launch, owned request or shared row"
        )
    return _CompletionContext(
        association=association,
        owned_input=owned_input,
        result=result,
        by_encoding={job.request.encoding.encoding_sha256: job for job in association.owned_jobs},
        input_raw_sha256=sha256_bytes(canonical_json_bytes(owned_input.model_dump(mode="json"))),
        result_raw_sha256=sha256_bytes(canonical_json_bytes(result.model_dump(mode="json"))),
        shard_raw_sha256=sha256_bytes(canonical_json_bytes(result.shard.model_dump(mode="json"))),
    )


def _validate_completion_event(
    event: EmbeddingEncodingCompletedEvent,
    context: _CompletionContext,
) -> None:
    association, owned_input, result = context.association, context.owned_input, context.result
    receipt = event.receipt
    if (
        event.intent != association.intent
        or event.launch_association_sha256 != association.association_sha256
        or context.by_encoding.get(event.owned_job.request.encoding.encoding_sha256)
        != event.owned_job
        or association.owned_input_request_sha256 != owned_input.request_sha256
        or association.owned_input_set_sha256 != owned_input.input_set_sha256
        or association.intent.native_launch_job_id != result.job_id
        or receipt.result_sha256 != result.result_sha256
        or receipt.result_manifest.sha256 != context.result_raw_sha256
        or receipt.shard_sha256 != result.shard.shard_sha256
        or receipt.shard_manifest.sha256 != context.shard_raw_sha256
        or receipt.binary_member.sha256 != result.shard.binary.sha256
        or receipt.row_ref.row_index >= len(result.shard.rows)
        or result.shard.rows[receipt.row_ref.row_index] != event.owned_job.request.encoding
        or association.owned_input.sha256 != context.input_raw_sha256
    ):
        raise ValueError(
            "encoding completion differs from exact launch, owned request or shared row"
        )


def validate_embedding_encoding_completion(
    event: EmbeddingEncodingCompletedEvent,
    association: LocalEmbeddingLaunchAssociation,
    owned_input: IncrementalEmbeddingInput,
    result: IncrementalEmbeddingResult,
) -> None:
    """Pure known-output closure; actual binary/lifecycle/authority remain owner gates."""
    event = EmbeddingEncodingCompletedEvent.model_validate(event)
    _validate_completion_event(event, _completion_context(association, owned_input, result))


def validate_embedding_encoding_completions(
    events: tuple[EmbeddingEncodingCompletedEvent, ...],
    association: LocalEmbeddingLaunchAssociation,
    owned_input: IncrementalEmbeddingInput,
    result: IncrementalEmbeddingResult,
) -> None:
    """Exact whole owned set with one O(n+bytes) pipeline, never an authority grant."""
    if type(events) is not tuple or not 1 <= len(events) <= 1024:
        raise ValueError(
            "encoding completion differs from exact launch, owned request or shared row"
        )
    events = tuple(EmbeddingEncodingCompletedEvent.model_validate(event) for event in events)
    context = _completion_context(association, owned_input, result)
    keys = tuple(event.owned_job.request.encoding.encoding_sha256 for event in events)
    if keys != tuple(sorted(set(keys))) or keys != tuple(context.by_encoding):
        raise ValueError(
            "encoding completion differs from exact launch, owned request or shared row"
        )
    for event in events:
        _validate_completion_event(event, context)
