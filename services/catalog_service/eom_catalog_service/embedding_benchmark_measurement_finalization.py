"""Resolve six real launch Artifacts and finalize their original measurement Job.

Measurement is not GPU activation. Missing independent activation proofs remain
NOT_RUN, even when the completed numerical/performance comparison favors CUDA.
"""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts.embedding_device_benchmark import (
    BENCHMARK_LAUNCH_ARTIFACT_TYPE,
    EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF,
    MAX_BENCHMARK_ENVELOPE_BYTES,
    BenchmarkDevice,
    BenchmarkDeviceResult,
    BenchmarkGateAssessment,
    BenchmarkOwnerGateEvidence,
    BenchmarkOwnerRequest,
    BenchmarkOwnerResult,
    BenchmarkPublishedVectorSample,
    BenchmarkResourceEvidence,
    BenchmarkRuntime,
    BenchmarkSession,
    BenchmarkStagedInputs,
    BenchmarkTimingEvidence,
    BenchmarkVectorEvidence,
    EmbeddingDeviceBenchmarkMessage,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark_bytes,
)
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.embedding_benchmark_jobs import (
    BENCHMARK_JOB_TASK,
    require_benchmark_job_in_session,
)
from eom_orchestrator.embedding_benchmark_launch_history import CompletedBenchmarkLaunch
from eom_orchestrator.embedding_benchmark_measurement_publication import (
    BENCHMARK_MEASUREMENT_MEMBERS,
    BenchmarkMeasurementArtifactPublisher,
    BenchmarkMeasurementFiles,
    BenchmarkMeasurementPublicationError,
    PublishedBenchmarkMeasurement,
    benchmark_measurement_member_schema,
)
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkExecutionOwner
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.models import JobRecord
from eom_orchestrator.state_machine import JobState
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.embedding_benchmark_launch_control import (
    BenchmarkLaunchCompleted,
    BenchmarkLaunchPrepared,
    parse_benchmark_launch_control_bytes,
)
from sqlalchemy.orm import Session

from eom_catalog_service.embedding_benchmark_numerical_assessment import (
    assess_benchmark_series_numerics,
)
from eom_catalog_service.embedding_benchmark_owner_admission import CatalogBenchmarkOwnerAdmission
from eom_catalog_service.embedding_benchmark_timing_evidence import assess_benchmark_series_timings
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings

_CONTROL = "eom://schemas/workflow/embedding-benchmark-launch-control/1.0#/$defs/"


@dataclass(frozen=True, slots=True)
class _LaunchEvidence:
    receipt: ArtifactMemberPointer
    resources: ArtifactMemberPointer
    tokens: ArtifactMemberPointer
    preparation: ArtifactMemberPointer
    completion: ArtifactMemberPointer
    prepared: BenchmarkLaunchPrepared
    completed: BenchmarkLaunchCompleted


def _read_launch_evidence(
    session: Session, reader: PinnedArtifactReadContext, launch: CompletedBenchmarkLaunch
) -> _LaunchEvidence:
    """Read registered owner-produced members, never caller-supplied gate verdicts."""
    artifact = launch.receipt.worker_result

    def read(name: str, schema: str) -> tuple[ArtifactMemberPointer, bytes, str]:
        pointer = reader.member_pointer(
            artifact.artifact_id,
            artifact.artifact_revision_id,
            name,
            schema_ref=schema,
            media_type="application/json",
        )
        value = reader.read_pinned(
            **pointer.model_dump(mode="python"),
            expected_artifact_types=(BENCHMARK_LAUNCH_ARTIFACT_TYPE,),
            expected_primary_file="worker-result.json",
            max_bytes=MAX_BENCHMARK_ENVELOPE_BYTES,
        )
        return pointer, value.payload, value.producer_job_id

    receipt, raw_receipt, producer_id = read(
        "launch-receipt.json", EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF + "#/$defs/launchReceipt"
    )
    session_pointer, raw_session, _ = read(
        "session.json", EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF + "#/$defs/session"
    )
    native_session = parse_embedding_device_benchmark_bytes(raw_session)
    resource, raw_resource, _ = read(
        "resources.json", EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF + "#/$defs/resources"
    )
    prepared_pointer, raw_prepared, _ = read("root-prepared.json", _CONTROL + "prepared")
    completed_pointer, raw_completed, _ = read("root-completion.json", _CONTROL + "completed")
    prepared = parse_benchmark_launch_control_bytes(raw_prepared)
    completed = parse_benchmark_launch_control_bytes(raw_completed)
    resources = parse_embedding_device_benchmark_bytes(raw_resource)
    producer = session.get(JobRecord, producer_id, populate_existing=True)
    invocation = launch.invocation
    if (
        parse_embedding_device_benchmark_bytes(raw_receipt) != launch.receipt
        or session_pointer != launch.receipt.session
        or not isinstance(native_session, BenchmarkSession)
        or (
            native_session.execution_id,
            native_session.invocation_sha256,
            native_session.launch_ordinal,
        )
        != (invocation.execution_id, invocation.invocation_sha256, invocation.launch_ordinal)
        or embedding_device_benchmark_bytes(launch.receipt) != raw_receipt
        or not isinstance(resources, BenchmarkResourceEvidence)
        or resources != launch.result.resources
        or embedding_device_benchmark_bytes(resources) != raw_resource
        or not isinstance(prepared, BenchmarkLaunchPrepared)
        or not isinstance(completed, BenchmarkLaunchCompleted)
        or producer is None
        or producer.request.get("source_commit") != prepared.controller_release
        or (prepared.job_id, prepared.execution_id, prepared.invocation_sha256)
        != (invocation.job_id, invocation.execution_id, invocation.invocation_sha256)
        or (
            completed.job_id,
            completed.execution_id,
            completed.invocation_sha256,
            completed.device,
            completed.launch_ordinal,
        )
        != (
            invocation.job_id,
            invocation.execution_id,
            invocation.invocation_sha256,
            invocation.device,
            invocation.launch_ordinal,
        )
        or completed.association_sha256 != prepared.association_sha256
        or completed.prepared_sha256 != prepared.prepared_sha256
        or completed.original_outcome != "SUCCEEDED"
        or completed.cleanup != "CONFIRMED"
        or (invocation.device == "CUDA" and completed.resources != resources)
    ):
        raise ValueError("BENCHMARK_MEASUREMENT_LAUNCH_CLOSURE_INVALID")
    # The numerical reader materializes and validates these actual bytes once.
    tokens = reader.member_pointer(
        artifact.artifact_id,
        artifact.artifact_revision_id,
        "token-witness.json",
        schema_ref=EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF + "#/$defs/tokenWitness",
        media_type="application/json",
    )
    if launch.result.token_witness is None or tokens.sha256 != launch.result.token_witness.sha256:
        raise ValueError("BENCHMARK_MEASUREMENT_TOKEN_CLOSURE_INVALID")
    return _LaunchEvidence(
        receipt, resource, tokens, prepared_pointer, completed_pointer, prepared, completed
    )


def _capacity_reasons(
    request: BenchmarkOwnerRequest,
    inputs: BenchmarkStagedInputs,
    launches: tuple[CompletedBenchmarkLaunch, ...],
) -> tuple[str, ...]:
    reasons: set[str] = set()
    policy = request.execution_policy
    for launch in launches:
        resource = launch.result.resources
        if resource is None:
            raise ValueError("BENCHMARK_MEASUREMENT_RESOURCES_MISSING")
        if resource.peak_rss_bytes > policy.rss_limit_bytes:
            reasons.add("RSS_LIMIT_EXCEEDED")
        if resource.oom_count:
            reasons.add("OOM_OBSERVED")
        if resource.other_consumer_overlap_count:
            reasons.add("GPU_CONSUMER_OVERLAP")
        if launch.invocation.device == "CUDA" and (
            not resource.owner_observation_count
            or resource.peak_reserved_gpu_bytes is None
            or resource.peak_whole_process_gpu_bytes is None
            or resource.peak_whole_device_gpu_bytes is None
        ):
            reasons.add("GPU_OWNER_OBSERVATION_MISSING")
        # Reserved allocator memory is included in whole-process VRAM. The frozen
        # design caps each observation; summing would double-count the allocation.
        if (
            launch.invocation.device == "CUDA"
            and max(
                resource.peak_reserved_gpu_bytes or 0, resource.peak_whole_process_gpu_bytes or 0
            )
            > policy.gpu_limit_bytes
        ):
            reasons.add("GPU_LIMIT_EXCEEDED")
        if launch.invocation.launch_ordinal not in (1, 2):
            continue
        if tuple(sample.batch_size for sample in resource.capacity_samples) != (1, 4):
            reasons.add("CAPACITY_PROGRAM_INCOMPLETE")
        for sample in resource.capacity_samples:
            if (sample.input_text_sha256, sample.token_ids_sha256) != (
                inputs.capacity.input_text_sha256,
                inputs.capacity.token_ids_sha256,
            ):
                reasons.add("CAPACITY_INPUT_MISMATCH")
            if sample.peak_rss_bytes > policy.rss_limit_bytes:
                reasons.add("RSS_LIMIT_EXCEEDED")
            if launch.invocation.device == "CUDA" and (
                sample.peak_reserved_gpu_bytes is None
                or sample.peak_whole_process_gpu_bytes is None
            ):
                reasons.add("GPU_CAPACITY_OBSERVATION_MISSING")
            if (
                max(sample.peak_reserved_gpu_bytes or 0, sample.peak_whole_process_gpu_bytes or 0)
                > policy.gpu_limit_bytes
            ):
                reasons.add("GPU_LIMIT_EXCEEDED")
    return tuple(sorted(reasons))


def _collect_measurement(
    owner: BenchmarkExecutionOwner,
    request: BenchmarkOwnerRequest,
    *,
    job_id: str,
    settings: CatalogSettings,
) -> BenchmarkMeasurementFiles:
    admission = owner.admission
    if type(admission) is not CatalogBenchmarkOwnerAdmission:
        raise ValueError("BENCHMARK_MEASUREMENT_OWNER_INVALID")
    with (
        owner.sessions() as session,
        session.begin(),
        admission.admit_execution_in_session(session, request) as inputs,
    ):
        job = require_benchmark_job_in_session(session, request, job_id=job_id)
        history = owner.journal.read(session, request, job_id=job_id)
        if history.job_state != JobState.VALIDATING_RESULT:
            raise ValueError("BENCHMARK_MEASUREMENT_SERIES_NOT_READY")
        launches = owner.journal.require_completed_launches(session, request, job_id=job_id)
        first = launches[0]
        reference = admission.read_cpu_numerical_reference_in_session(
            session, request, first.receipt.evidence
        )
        numerical_launches = tuple(
            admission.read_launch_numerics_in_session(session, request, launch)
            for launch in launches
        )
        numerical = assess_benchmark_series_numerics(
            request,
            inputs,
            numerical_launches,
            reference_pointer=reference.pointer,
            reference_raw=reference.raw,
            reference_scores=reference.scores,
        )
        timing = assess_benchmark_series_timings(
            request,
            inputs,
            tuple(
                admission.read_launch_timings_in_session(session, request, launch)
                for launch in launches
            ),
        )
        reader = PinnedArtifactReadContext(session, settings)
        reader.prefetch(
            tuple(
                (
                    launch.receipt.worker_result.artifact_id,
                    launch.receipt.worker_result.artifact_revision_id,
                )
                for launch in launches
            )
        )
        evidence = tuple(_read_launch_evidence(session, reader, launch) for launch in launches)
        if len({row.prepared.controller_release for row in evidence}) != 1 or any(
            len(
                {
                    row.prepared.backend
                    for launch, row in zip(launches, evidence, strict=True)
                    if launch.invocation.device == device
                }
            )
            != 1
            for device in ("CPU", "CUDA")
        ):
            raise ValueError("BENCHMARK_MEASUREMENT_RUNTIME_MIXED")
        members: dict[str, bytes] = {"rank-evidence.f64": numerical.score_binary}

        def put(name: str, value: EmbeddingDeviceBenchmarkMessage) -> ArtifactMemberPointer:
            # All callers supply released benchmark models, checked by the codec.
            raw = embedding_device_benchmark_bytes(value)
            members[name] = raw
            return ArtifactMemberPointer(
                artifact_id=job.logical_artifact_id,
                artifact_revision_id=job.revision_id,
                member_path=name,
                schema_ref=benchmark_measurement_member_schema(name),
                media_type="application/json",
                sha256=sha256_bytes(raw),
            )

        devices: dict[BenchmarkDevice, BenchmarkDeviceResult] = {}
        device_inputs: tuple[
            tuple[BenchmarkDevice, BenchmarkRuntime, BenchmarkTimingEvidence], ...
        ] = (
            ("CPU", request.cpu, timing.cpu),
            ("CUDA", request.cuda, timing.cuda),
        )
        for device, runtime, clocks in device_inputs:
            selected = tuple(
                (launch, row)
                for launch, row in zip(launches, evidence, strict=True)
                if launch.invocation.device == device
            )
            vector_pointers = []
            for purpose, rows, space in (
                ("DOCUMENT", request.document_rows, runtime.spaces.document),
                ("QUERY", request.query_rows, runtime.spaces.query),
            ):
                samples = []
                for launch, _row in selected:
                    for sample in launch.result.vectors:
                        if sample.purpose != purpose:
                            continue
                        pointer = reader.member_pointer(
                            launch.receipt.worker_result.artifact_id,
                            launch.receipt.worker_result.artifact_revision_id,
                            sample.binary.member_name,
                            schema_ref="eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0",
                            media_type="application/octet-stream",
                        )
                        samples.append(
                            BenchmarkPublishedVectorSample(
                                launch_ordinal=launch.invocation.launch_ordinal,
                                sample=sample,
                                binary_member=pointer,
                            )
                        )
                body = dict(
                    schema_version="embedding-device-benchmark-vector-evidence/1.0",
                    device=device,
                    purpose=purpose,
                    space=space,
                    rows=rows,
                    samples=tuple(samples),
                )
                vector_pointers.append(
                    put(
                        device.lower()
                        + ("-documents.json" if purpose == "DOCUMENT" else "-queries.json"),
                        BenchmarkVectorEvidence.model_validate(
                            body | {"evidence_sha256": content_sha256(body)}
                        ),
                    )
                )
            devices[device] = BenchmarkDeviceResult(
                device=device,
                spaces=runtime.spaces,
                document_vectors=vector_pointers[0],
                query_vectors=vector_pointers[1],
                token_witness=selected[0][1].tokens,
                timing_evidence=put(f"{device.lower()}-timings.json", clocks),
                resource_evidence=tuple(row.resources for _launch, row in selected),
                timings=clocks.gate_timings,
                launch_receipts=tuple(row.receipt for _launch, row in selected),
            )
        numerical_pointer = put("numerical-evidence.json", numerical.evidence)
        failures = tuple(
            name.upper()
            for name in (
                "norm_failures",
                "cosine_failures",
                "component_failures",
                "query_score_failures",
                "wide_gap_order_failures",
                "cluster_order_failures",
                "top5_boundary_failures",
                "same_device_failures",
            )
            if getattr(numerical.evidence, name)
        )
        capacity = _capacity_reasons(request, inputs, launches)
        overlap = any(
            launch.result.resources is not None
            and launch.result.resources.other_consumer_overlap_count
            for launch in launches
        )

        def measured_gate(
            name: str, reasons: tuple[str, ...], pointer: ArtifactMemberPointer
        ) -> BenchmarkGateAssessment:
            return BenchmarkGateAssessment.model_validate(
                dict(
                    gate=name,
                    status="FAIL" if reasons else "PASS",
                    reason_codes=tuple(sorted(reasons)),
                    evidence=pointer,
                )
            )

        gate_rows = (
            measured_gate("SOURCE_AUTHORIZATION", (), request.input_manifest),
            measured_gate("RUNTIME", (), evidence[0].preparation),
            measured_gate("NUMERICAL", failures, numerical_pointer),
            measured_gate(
                "PERFORMANCE", timing.performance.reasons, devices["CUDA"].timing_evidence
            ),
            measured_gate("CAPACITY", capacity, evidence[1].resources),
            BenchmarkGateAssessment(
                gate="SANDBOX",
                status="NOT_RUN",
                reason_codes=("SANDBOX_EVIDENCE_NOT_RECORDED",),
                evidence=None,
            ),
            measured_gate(
                "GPU_LEASE", ("GPU_CONSUMER_OVERLAP",) if overlap else (), evidence[1].completion
            ),
            measured_gate("CLEANUP", (), evidence[5].completion),
            BenchmarkGateAssessment(
                gate="IMAGE_TRAINER_REGRESSION",
                status="NOT_RUN",
                reason_codes=("IMAGE_TRAINER_REGRESSION_NOT_RECORDED",),
                evidence=None,
            ),
        )
        gate_body = dict(
            schema_version="embedding-device-benchmark-owner-gate-evidence/1.0",
            request_sha256=request.request_sha256,
            gates=gate_rows,
        )
        gates = BenchmarkOwnerGateEvidence.model_validate(
            gate_body | {"evidence_sha256": content_sha256(gate_body)}
        )
        gate_pointer = put("owner-gates.json", gates)
        result_body = dict(
            schema_version="embedding-device-benchmark-result/1.0",
            kind="OWNER_RESULT",
            purpose="LOCAL_EMBEDDING_DEVICE_BENCHMARK",
            benchmark_id=request.benchmark_id,
            benchmark_revision_id=request.benchmark_revision_id,
            request_sha256=request.request_sha256,
            status="MEASURED",
            reason_codes=tuple(
                sorted(gate.gate + "_" + gate.status for gate in gate_rows if gate.status != "PASS")
            ),
            cpu=devices["CPU"],
            cuda=devices["CUDA"],
            numerical_evidence=numerical_pointer,
            near_tie_reference=reference.pointer,
            owner_gate_evidence=gate_pointer,
        )
        result = BenchmarkOwnerResult.model_validate(
            result_body | {"result_sha256": content_sha256(result_body)}
        )
        put("result.json", result)
        reader.revalidate_provenance()
        if owner.journal.read(session, request, job_id=job_id) != history:
            raise ValueError("BENCHMARK_MEASUREMENT_HISTORY_CHANGED")
        return BenchmarkMeasurementFiles(
            result,
            gates,
            tuple(row.receipt for row in launches),
            tuple((name, members[name]) for name in BENCHMARK_MEASUREMENT_MEMBERS),
        )


def _verify_original_sources_in_session(
    owner: BenchmarkExecutionOwner,
    session: Session,
    request: BenchmarkOwnerRequest,
    result: BenchmarkOwnerResult,
    settings: CatalogSettings,
    *,
    job_id: str,
    vector_members: dict[str, bytes],
) -> None:
    """Close original external pointers in the caller's current database root.

    Orchestrator has verified these sealed measurement bytes. This same closure
    applies before COMMITTING becomes SUCCEEDED and on historical replay; neither
    staging nor prior success grants authority to missing or revoked members.
    """
    admission = owner.admission
    if type(admission) is not CatalogBenchmarkOwnerAdmission:
        raise ValueError("BENCHMARK_MEASUREMENT_OWNER_INVALID")
    with admission.admit_execution_in_session(session, request) as inputs:
        history = owner.journal.read(session, request, job_id=job_id)
        if history.job_state not in {JobState.COMMITTING, JobState.SUCCEEDED}:
            raise ValueError("BENCHMARK_MEASUREMENT_REPLAY_INCOMPLETE")
        launches = owner.journal.require_completed_launches(session, request, job_id=job_id)
        reference = admission.read_cpu_numerical_reference_in_session(
            session, request, launches[0].receipt.evidence
        )
        if result.near_tie_reference != reference.pointer:
            raise ValueError("BENCHMARK_MEASUREMENT_REPLAY_REFERENCE_INVALID")
        # These readers validate all actual immutable token/f32 hashes and clocks.
        # They do not encode, select fastest repetitions, or rerun the numerical assessor.
        for launch in launches:
            admission.read_launch_numerics_in_session(session, request, launch)
        timings = assess_benchmark_series_timings(
            request,
            inputs,
            tuple(
                admission.read_launch_timings_in_session(session, request, launch)
                for launch in launches
            ),
        )
        reader = PinnedArtifactReadContext(session, settings)
        reader.prefetch(
            tuple(
                (
                    launch.receipt.worker_result.artifact_id,
                    launch.receipt.worker_result.artifact_revision_id,
                )
                for launch in launches
            )
        )
        evidence = tuple(_read_launch_evidence(session, reader, launch) for launch in launches)
        for device, timing in (
            (result.cpu, timings.cpu),
            (result.cuda, timings.cuda),
        ):
            if device is None:
                raise ValueError("BENCHMARK_MEASUREMENT_REPLAY_DEVICE_MISSING")
            selected = tuple(
                (launch, proof)
                for launch, proof in zip(launches, evidence, strict=True)
                if launch.invocation.device == device.device
            )
            if (
                device.launch_receipts != tuple(proof.receipt for _launch, proof in selected)
                or device.resource_evidence != tuple(proof.resources for _launch, proof in selected)
                or device.token_witness != selected[0][1].tokens
                or device.timings != timing.gate_timings
            ):
                raise ValueError("BENCHMARK_MEASUREMENT_REPLAY_DEVICE_INVALID")
            for purpose, pointer in (
                ("DOCUMENT", device.document_vectors),
                ("QUERY", device.query_vectors),
            ):
                raw = vector_members[pointer.member_path]
                vectors = parse_embedding_device_benchmark_bytes(raw)
                expected_samples = tuple(
                    (
                        launch.invocation.launch_ordinal,
                        sample,
                        launch.receipt.worker_result.artifact_id,
                        launch.receipt.worker_result.artifact_revision_id,
                    )
                    for launch, _proof in selected
                    for sample in launch.result.vectors
                    if sample.purpose == purpose
                )
                if (
                    not isinstance(vectors, BenchmarkVectorEvidence)
                    or tuple(
                        (
                            sample.launch_ordinal,
                            sample.sample,
                            sample.binary_member.artifact_id,
                            sample.binary_member.artifact_revision_id,
                        )
                        for sample in vectors.samples
                    )
                    != expected_samples
                ):
                    raise ValueError("BENCHMARK_MEASUREMENT_REPLAY_VECTORS_INVALID")
        reader.revalidate_provenance()
        if owner.journal.read(session, request, job_id=job_id) != history:
            raise ValueError("BENCHMARK_MEASUREMENT_HISTORY_CHANGED")


@dataclass(frozen=True, slots=True)
class _CatalogBenchmarkMeasurementSourceValidator:
    owner: BenchmarkExecutionOwner
    settings: CatalogSettings

    def validate_in_session(
        self,
        session: Session,
        request: BenchmarkOwnerRequest,
        *,
        job_id: str,
        value: BenchmarkMeasurementFiles,
    ) -> None:
        _verify_original_sources_in_session(
            self.owner,
            session,
            request,
            value.result,
            self.settings,
            job_id=job_id,
            vector_members=dict(value.members),
        )


def _verify_committed_sources(
    owner: BenchmarkExecutionOwner,
    request: BenchmarkOwnerRequest,
    published: PublishedBenchmarkMeasurement,
    settings: CatalogSettings,
) -> None:
    """Reauthorize every returned external pointer without model/numerical execution."""
    with (
        owner.sessions() as session,
        session.begin(),
        owner.admission.admit_execution_in_session(session, request),
    ):
        history = owner.journal.read(session, request, job_id=published.job_id)
        if history.job_state != JobState.SUCCEEDED:
            raise ValueError("BENCHMARK_MEASUREMENT_REPLAY_INCOMPLETE")
        reader = PinnedArtifactReadContext(session, settings)
        reader.prefetch(
            ((published.result_member.artifact_id, published.result_member.artifact_revision_id),)
        )
        members = {}
        for device in (published.result.cpu, published.result.cuda):
            if device is None:
                raise ValueError("BENCHMARK_MEASUREMENT_REPLAY_DEVICE_MISSING")
            for pointer in (device.document_vectors, device.query_vectors):
                members[pointer.member_path] = reader.read_pinned(
                    **pointer.model_dump(mode="python"),
                    expected_artifact_types=(BENCHMARK_JOB_TASK,),
                    expected_primary_file="result.json",
                    max_bytes=MAX_BENCHMARK_ENVELOPE_BYTES,
                ).payload
        _verify_original_sources_in_session(
            owner,
            session,
            request,
            published.result,
            settings,
            job_id=published.job_id,
            vector_members=members,
        )
        reader.revalidate_provenance()
        if owner.journal.read(session, request, job_id=published.job_id) != history:
            raise ValueError("BENCHMARK_MEASUREMENT_HISTORY_CHANGED")


def finalize_completed_benchmark_measurement(
    owner: BenchmarkExecutionOwner,
    publisher: ControlFileSetPublisher,
    request: BenchmarkOwnerRequest,
    *,
    job_id: str,
) -> PublishedBenchmarkMeasurement:
    """Current authorized original-Job finalization/recovery; never launch a model or select GPU."""
    if (
        type(owner) is not BenchmarkExecutionOwner
        or type(owner.admission) is not CatalogBenchmarkOwnerAdmission
        or type(publisher) is not ControlFileSetPublisher
        or owner.sessions.kw.get("bind") is not publisher.engine
    ):
        raise ValueError("BENCHMARK_MEASUREMENT_OWNER_INVALID")
    settings = CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
    publication = BenchmarkMeasurementArtifactPublisher(
        owner,
        publisher.settings,
        source_validator=_CatalogBenchmarkMeasurementSourceValidator(owner, settings),
    )
    replay = publication.replay(request, job_id=job_id)
    if replay is not None:
        _verify_committed_sources(owner, request, replay, settings)
        return replay
    with (
        owner.sessions() as session,
        session.begin(),
        owner.admission.admit_execution_in_session(session, request),
    ):
        job = require_benchmark_job_in_session(session, request, job_id=job_id)
        recover = job.status == JobState.COMMITTING
    value = (
        None
        if recover
        else _collect_measurement(
            owner,
            request,
            job_id=job_id,
            settings=settings,
        )
    )
    try:
        published = publication.publish(request, job_id=job_id, value=value)
        _verify_committed_sources(owner, request, published, settings)
        return published
    except BenchmarkMeasurementPublicationError as exc:
        if exc.code != "BENCHMARK_MEASUREMENT_REPLAY_REQUIRED":
            raise
        replay = publication.replay(request, job_id=job_id)
        if replay is None:
            raise ValueError("BENCHMARK_MEASUREMENT_REPLAY_INCOMPLETE") from exc
        _verify_committed_sources(owner, request, replay, settings)
        return replay
