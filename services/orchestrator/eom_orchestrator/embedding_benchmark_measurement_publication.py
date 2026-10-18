"""Commit a completed measurement under its original benchmark Job and Artifact IDs."""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from eom_catalog_contracts.embedding_device_benchmark import (
    EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF,
    MAX_BENCHMARK_OUTPUT_BYTES,
    BenchmarkLaunchReceipt,
    BenchmarkNumericalEvidence,
    BenchmarkOwnerGateEvidence,
    BenchmarkOwnerRequest,
    BenchmarkOwnerResult,
    BenchmarkTimingEvidence,
    BenchmarkVectorEvidence,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark_bytes,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_orchestrator.artifacts import (
    StagedFile,
    StagedFileSet,
    commit_file_set_artifact,
    stage_file_set_artifact,
)
from eom_orchestrator.embedding_benchmark_jobs import require_benchmark_job_in_session
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkExecutionOwner
from eom_orchestrator.file_set_control_artifacts import CONTROL_FILE_SET_PROTOCOL
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_orchestrator.repository import create_artifact_records
from eom_orchestrator.settings import Settings
from eom_orchestrator.state_machine import JobState, transition_job

_JSON_MEMBERS = {
    "result.json": "ownerResult",
    "owner-gates.json": "ownerGateEvidence",
    "numerical-evidence.json": "numericalEvidence",
    "cpu-documents.json": "vectorEvidence",
    "cpu-queries.json": "vectorEvidence",
    "cuda-documents.json": "vectorEvidence",
    "cuda-queries.json": "vectorEvidence",
    "cpu-timings.json": "timingEvidence",
    "cuda-timings.json": "timingEvidence",
}
BENCHMARK_MEASUREMENT_MEMBERS = tuple(sorted((*_JSON_MEMBERS, "rank-evidence.f64")))
_COMMITTING = "BENCHMARK_MEASUREMENT_COMMITTING"
_COMMITTED = "BENCHMARK_MEASUREMENT_COMMITTED"
_INTENT_FIELDS = {
    "request_sha256",
    "content_hash",
    "manifest_hash",
    "result_sha256",
    "launch_receipt_sha256s",
    "source_commit",
}


class BenchmarkMeasurementPublicationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class BenchmarkMeasurementFiles:
    """Bounded application materialization, not numerical or source authority."""

    result: BenchmarkOwnerResult
    gates: BenchmarkOwnerGateEvidence
    launch_receipts: tuple[BenchmarkLaunchReceipt, ...]
    members: tuple[tuple[str, bytes], ...]


class BenchmarkMeasurementSourceValidator(Protocol):
    """Required Catalog closure in the original publisher's final transaction."""

    def validate_in_session(
        self,
        session: Session,
        request: BenchmarkOwnerRequest,
        *,
        job_id: str,
        value: BenchmarkMeasurementFiles,
    ) -> None:
        """Reauthorize original external members; never reassess or dispatch a model."""
        ...


@dataclass(frozen=True, slots=True)
class PublishedBenchmarkMeasurement:
    job_id: str
    result: BenchmarkOwnerResult
    gates: BenchmarkOwnerGateEvidence
    result_member: ArtifactMemberPointer
    created: bool


def benchmark_measurement_member_schema(name: str) -> str:
    if name == "rank-evidence.f64":
        return "eom://schemas/knowledge/embedding-benchmark-scores-f64le/1.0"
    try:
        return EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF + "#/$defs/" + _JSON_MEMBERS[name]
    except KeyError:
        raise BenchmarkMeasurementPublicationError("BENCHMARK_MEASUREMENT_MEMBER_INVALID") from None


def _invalid() -> BenchmarkMeasurementPublicationError:
    return BenchmarkMeasurementPublicationError("BENCHMARK_MEASUREMENT_PUBLICATION_INVALID")


def validate_benchmark_measurement_files(
    request: BenchmarkOwnerRequest,
    artifact_id: str,
    revision_id: str,
    value: BenchmarkMeasurementFiles,
) -> None:
    """Verify fixed immutable payload closure; Catalog owns actual numerical assessment."""
    if type(value) is not BenchmarkMeasurementFiles or (
        tuple(name for name, _raw in value.members) != BENCHMARK_MEASUREMENT_MEMBERS
        or sum(len(raw) for _name, raw in value.members) > MAX_BENCHMARK_OUTPUT_BYTES
        or any(type(raw) is not bytes or not raw for _name, raw in value.members)
        or len(value.launch_receipts) != 6
        or tuple(receipt.launch_ordinal for receipt in value.launch_receipts) != tuple(range(1, 7))
        or len({receipt.execution_id for receipt in value.launch_receipts}) != 6
        or value.result.status != "MEASURED"
        or value.result.request_sha256 != request.request_sha256
        or value.result.benchmark_id != request.benchmark_id
        or value.result.benchmark_revision_id != request.benchmark_revision_id
        or value.gates.request_sha256 != request.request_sha256
    ):
        raise _invalid()
    members = dict(value.members)
    parsed_members = {}
    for name in _JSON_MEMBERS:
        parsed = parse_embedding_device_benchmark_bytes(
            members[name], maximum_bytes=MAX_BENCHMARK_OUTPUT_BYTES
        )
        parsed_members[name] = parsed
        if embedding_device_benchmark_bytes(parsed) != members[name]:
            raise _invalid()
    if members["result.json"] != embedding_device_benchmark_bytes(value.result) or members[
        "owner-gates.json"
    ] != embedding_device_benchmark_bytes(value.gates):
        raise _invalid()
    pointers = (value.result.owner_gate_evidence, value.result.numerical_evidence)
    # Result/device references within this file set preserve preallocated identities.
    local_pointers = [pointer for pointer in pointers if isinstance(pointer, ArtifactMemberPointer)]
    for device in (value.result.cpu, value.result.cuda):
        if device is None:
            raise _invalid()
        local_pointers.extend(
            (device.document_vectors, device.query_vectors, device.timing_evidence)
        )
        if device.spaces != (request.cpu if device.device == "CPU" else request.cuda).spaces:
            raise _invalid()
        for pointer, purpose, rows, space in (
            (device.document_vectors, "DOCUMENT", request.document_rows, device.spaces.document),
            (device.query_vectors, "QUERY", request.query_rows, device.spaces.query),
        ):
            vector = parsed_members.get(pointer.member_path)
            if not isinstance(vector, BenchmarkVectorEvidence) or (
                vector.device != device.device
                or vector.purpose != purpose
                or vector.rows != rows
                or vector.space != space
            ):
                raise _invalid()
        timing = parsed_members.get(device.timing_evidence.member_path)
        if not isinstance(timing, BenchmarkTimingEvidence) or (
            timing.device != device.device or timing.gate_timings != device.timings
        ):
            raise _invalid()
        original = tuple(
            receipt for receipt in value.launch_receipts if receipt.device == device.device
        )
        if any(
            (pointer.artifact_id, pointer.artifact_revision_id, pointer.sha256)
            != (
                receipt.worker_result.artifact_id,
                receipt.worker_result.artifact_revision_id,
                sha256_bytes(embedding_device_benchmark_bytes(receipt)),
            )
            for pointer, receipt in zip(device.launch_receipts, original, strict=True)
        ):
            raise _invalid()
        if any(
            (pointer.artifact_id, pointer.artifact_revision_id)
            != (receipt.worker_result.artifact_id, receipt.worker_result.artifact_revision_id)
            for pointer, receipt in zip(device.resource_evidence, original, strict=True)
        ) or (
            (device.token_witness.artifact_id, device.token_witness.artifact_revision_id)
            != (
                original[0].worker_result.artifact_id,
                original[0].worker_result.artifact_revision_id,
            )
        ):
            raise _invalid()
    for pointer in local_pointers:
        if (
            pointer.artifact_id != artifact_id
            or pointer.artifact_revision_id != revision_id
            or pointer.member_path not in members
            or pointer.schema_ref != benchmark_measurement_member_schema(pointer.member_path)
            or pointer.media_type != "application/json"
            or pointer.sha256 != sha256_bytes(members[pointer.member_path])
        ):
            raise _invalid()
    numerical = parsed_members["numerical-evidence.json"]
    if not isinstance(numerical, BenchmarkNumericalEvidence) or (
        numerical.score_binary.byte_count != len(members["rank-evidence.f64"])
        or numerical.score_binary.sha256 != sha256_bytes(members["rank-evidence.f64"])
        or numerical.input_set_sha256 != request.input_set_sha256
        or numerical.family_sha256 != request.family.family_sha256
        or numerical.near_tie_reference != value.result.near_tie_reference
    ):
        raise _invalid()
    if value.result.near_tie_reference != value.launch_receipts[0].evidence:
        raise _invalid()
    local_gates = {pointer.member_path: pointer for pointer in local_pointers}
    for gate in value.gates.gates:
        gate_pointer = gate.evidence
        if (
            gate_pointer is not None
            and gate_pointer.artifact_id == artifact_id
            and (local_gates.get(gate_pointer.member_path) != gate_pointer)
        ):
            raise _invalid()


def _epoch(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_member(path: Path, *, maximum: int) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    except OSError:
        raise BenchmarkMeasurementPublicationError(
            "BENCHMARK_MEASUREMENT_MEMBER_UNAVAILABLE"
        ) from None
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum
        ):
            raise _invalid()
        chunks = []
        remaining = before.st_size + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if (
            len(raw) != before.st_size
            or _epoch(before) != _epoch(os.fstat(descriptor))
            or (_epoch(before) != _epoch(path.lstat()))
        ):
            raise _invalid()
        return raw
    except OSError:
        raise BenchmarkMeasurementPublicationError(
            "BENCHMARK_MEASUREMENT_MEMBER_UNAVAILABLE"
        ) from None
    finally:
        os.close(descriptor)


@contextmanager
def _measurement_lock(settings: Settings, job_id: str) -> Iterator[None]:
    """One local fixed-Job publication lock; state/hash intent remains canonical in DB."""
    if re.fullmatch(r"job_[0-9a-f]{32}", job_id) is None or (
        not settings.staging_root.is_absolute() or ".." in settings.staging_root.parts
    ):
        raise _invalid()
    directory = settings.staging_root / job_id
    directory.mkdir(mode=0o750, parents=True, exist_ok=True)
    for ancestor in (directory, *directory.parents):
        value = ancestor.lstat()
        sticky_tmp = ancestor == Path("/tmp") and value.st_uid == 0 and value.st_mode & stat.S_ISVTX
        if not stat.S_ISDIR(value.st_mode) or (
            value.st_uid not in {0, os.geteuid()} or (value.st_mode & 0o022 and not sticky_tmp)
        ):
            raise _invalid()
    path = directory / "benchmark-measurement.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        initial = os.fstat(descriptor)
        if (
            not stat.S_ISREG(initial.st_mode)
            or initial.st_uid != os.geteuid()
            or initial.st_nlink != 1
            or stat.S_IMODE(initial.st_mode) != 0o600
            or initial != path.lstat()
        ):
            raise _invalid()
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BenchmarkMeasurementPublicationError(
                "BENCHMARK_MEASUREMENT_PUBLICATION_BUSY"
            ) from None
        if (initial.st_dev, initial.st_ino) != (path.stat().st_dev, path.stat().st_ino):
            raise _invalid()
        yield
    finally:
        os.close(descriptor)


class BenchmarkMeasurementArtifactPublisher:
    """Existing original Job only; no source impersonation, model dispatch or default selection."""

    def __init__(
        self,
        owner: BenchmarkExecutionOwner,
        settings: Settings,
        *,
        source_validator: BenchmarkMeasurementSourceValidator,
    ) -> None:
        if type(owner) is not BenchmarkExecutionOwner or (
            settings.runtime_source_commit is None
            or re.fullmatch(r"[0-9a-f]{40}", settings.runtime_source_commit) is None
        ):
            raise _invalid()
        self.owner, self.settings = owner, settings
        self.source_validator = source_validator

    def _current(
        self, session: Session, request: BenchmarkOwnerRequest, job_id: str
    ) -> tuple[JobRecord, tuple[BenchmarkLaunchReceipt, ...]]:
        job = require_benchmark_job_in_session(session, request, job_id=job_id)
        if job.status not in {JobState.VALIDATING_RESULT, JobState.COMMITTING, JobState.SUCCEEDED}:
            raise _invalid()
        return job, self.owner.journal.require_completed(session, request, job_id=job_id)

    @staticmethod
    def _intent(session: Session, job_id: str) -> dict[str, object]:
        events = tuple(
            session.scalars(
                select(JobEventRecord).where(
                    JobEventRecord.job_id == job_id, JobEventRecord.event == _COMMITTING
                )
            )
        )
        if len(events) != 1 or set(events[0].data) != _INTENT_FIELDS:
            raise _invalid()
        intent = dict(events[0].data)
        for key in ("request_sha256", "content_hash", "manifest_hash", "result_sha256"):
            digest = intent[key]
            if not isinstance(digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
                raise _invalid()
        source = intent["source_commit"]
        if not isinstance(source, str) or re.fullmatch(r"[0-9a-f]{40}", source) is None:
            raise _invalid()
        return intent

    def _recover(
        self,
        directory: Path,
        request: BenchmarkOwnerRequest,
        job: JobRecord,
        receipts: tuple[BenchmarkLaunchReceipt, ...],
        intent: dict[str, object],
    ) -> tuple[StagedFileSet, BenchmarkMeasurementFiles]:
        try:
            directory_valid = (
                directory.is_absolute()
                and ".." not in directory.parts
                and all(
                    stat.S_ISDIR(ancestor.lstat().st_mode)
                    for ancestor in (directory, *directory.parents)
                )
            )
        except OSError:
            directory_valid = False
        if not directory_valid:
            raise _invalid()
        if intent["request_sha256"] != request.request_sha256 or intent[
            "launch_receipt_sha256s"
        ] != [receipt.receipt_sha256 for receipt in receipts]:
            raise _invalid()
        raw = _read_member(directory / "manifest.json", maximum=65536)
        manifest = json.loads(raw)
        if (
            not isinstance(manifest, dict)
            or canonical_json_bytes(manifest) != raw
            or (
                sha256_bytes(raw) != intent["manifest_hash"]
                or manifest.get("manifest_version") != CONTROL_FILE_SET_PROTOCOL
                or manifest.get("job_id") != job.job_id
                or manifest.get("logical_artifact_id") != job.logical_artifact_id
                or manifest.get("revision_id") != job.revision_id
                or manifest.get("artifact_type") != job.task_type
                or manifest.get("primary_file") != "result.json"
            )
        ):
            raise _invalid()
        descriptors = manifest.get("files")
        if (
            not isinstance(descriptors, list)
            or tuple(row.get("file_name") for row in descriptors if isinstance(row, dict))
            != BENCHMARK_MEASUREMENT_MEMBERS
        ):
            raise _invalid()
        if (
            any(
                not isinstance(row, dict)
                or set(row) != {"file_name", "sha256", "bytes", "schema_ref", "media_type"}
                or type(row.get("bytes")) is not int
                or not (0 < row["bytes"] <= MAX_BENCHMARK_OUTPUT_BYTES)
                for row in descriptors
            )
            or sum(row["bytes"] for row in descriptors) > MAX_BENCHMARK_OUTPUT_BYTES
        ):
            raise _invalid()
        members, staged_files = [], []
        for row in descriptors:
            name = row["file_name"]
            payload = _read_member(directory / name, maximum=MAX_BENCHMARK_OUTPUT_BYTES)
            if (
                row.get("bytes") != len(payload)
                or row.get("sha256") != sha256_bytes(payload)
                or row.get("schema_ref") != benchmark_measurement_member_schema(name)
                or row.get("media_type")
                != ("application/octet-stream" if name.endswith(".f64") else "application/json")
            ):
                raise _invalid()
            members.append((name, payload))
            staged_files.append(StagedFile(name, directory / name, row["sha256"], row["bytes"]))
        values = dict(members)
        result = parse_embedding_device_benchmark_bytes(values["result.json"])
        gates = parse_embedding_device_benchmark_bytes(values["owner-gates.json"])
        if not isinstance(result, BenchmarkOwnerResult) or not isinstance(
            gates, BenchmarkOwnerGateEvidence
        ):
            raise _invalid()
        value = BenchmarkMeasurementFiles(result, gates, receipts, tuple(members))
        validate_benchmark_measurement_files(
            request, job.logical_artifact_id, job.revision_id, value
        )
        if (
            intent["result_sha256"] != result.result_sha256
            or intent["content_hash"] != sha256_bytes(values["result.json"])
            or manifest.get("content_hash") != intent["content_hash"]
            or manifest.get("content_bytes") != len(values["result.json"])
        ):
            raise _invalid()
        staged = StagedFileSet(
            directory,
            directory / "manifest.json",
            manifest,
            tuple(staged_files),
            sha256_bytes(values["result.json"]),
            len(values["result.json"]),
            sha256_bytes(raw),
            job.logical_artifact_id,
            job.revision_id,
        )
        return staged, value

    @staticmethod
    def _published(
        job: JobRecord, value: BenchmarkMeasurementFiles, *, created: bool
    ) -> PublishedBenchmarkMeasurement:
        raw = dict(value.members)["result.json"]
        pointer = ArtifactMemberPointer(
            artifact_id=job.logical_artifact_id,
            artifact_revision_id=job.revision_id,
            member_path="result.json",
            schema_ref=benchmark_measurement_member_schema("result.json"),
            media_type="application/json",
            sha256=sha256_bytes(raw),
        )
        return PublishedBenchmarkMeasurement(
            job.job_id, value.result, value.gates, pointer, created
        )

    def replay(
        self, request: BenchmarkOwnerRequest, *, job_id: str
    ) -> PublishedBenchmarkMeasurement | None:
        """Fresh exact committed replay, independent of temporary staging or today's encoder."""
        with (
            _measurement_lock(self.settings, job_id),
            self.owner.sessions() as session,
            session.begin(),
            self.owner.admission.admit_execution_in_session(session, request),
        ):
            job, receipts = self._current(session, request, job_id)
            if job.status != JobState.SUCCEEDED:
                return None
            intent = self._intent(session, job_id)
            revision = session.get(ArtifactRevisionRecord, job.revision_id, populate_existing=True)
            logical = session.get(ArtifactRecord, job.logical_artifact_id, populate_existing=True)
            final = self.settings.nas_artifact_root / job.logical_artifact_id / job.revision_id
            if (
                logical is None
                or revision is None
                or (
                    not logical.approved
                    or not revision.approved
                    or logical.job_id != job_id
                    or logical.artifact_type != job.task_type
                    or revision.job_id != job_id
                    or revision.logical_artifact_id != job.logical_artifact_id
                    or revision.nas_path != str(final)
                    or revision.content_hash != intent["content_hash"]
                    or revision.manifest_hash != intent["manifest_hash"]
                )
            ):
                raise _invalid()
            staged, value = self._recover(final, request, job, receipts, intent)
            if (
                revision.result != value.result.model_dump(mode="json")
                or revision.manifest != staged.manifest
                or revision.content_bytes != staged.primary_bytes
            ):
                raise _invalid()
            return self._published(job, value, created=False)

    def publish(
        self,
        request: BenchmarkOwnerRequest,
        *,
        job_id: str,
        value: BenchmarkMeasurementFiles | None,
    ) -> PublishedBenchmarkMeasurement:
        """Resume a sealed COMMITTING intent, or seal one actual new measurement."""
        with _measurement_lock(self.settings, job_id):
            with (
                self.owner.sessions() as session,
                session.begin(),
                self.owner.admission.admit_execution_in_session(session, request),
            ):
                job, receipts = self._current(session, request, job_id)
                if job.status == JobState.SUCCEEDED:
                    raise BenchmarkMeasurementPublicationError(
                        "BENCHMARK_MEASUREMENT_REPLAY_REQUIRED"
                    )
                identity, revision_id = job.logical_artifact_id, job.revision_id
                staging = self.settings.staging_root / job_id / "benchmark-measurement"
                if job.status == JobState.COMMITTING:
                    staged, value = self._recover(
                        staging, request, job, receipts, self._intent(session, job_id)
                    )
                else:
                    if value is None or value.launch_receipts != receipts:
                        raise _invalid()
                    validate_benchmark_measurement_files(request, identity, revision_id, value)
                    with tempfile.TemporaryDirectory(
                        prefix="benchmark-measurement-", dir=self.settings.workspace_root
                    ) as temporary:
                        paths = {}
                        for name, raw in value.members:
                            path = Path(temporary) / name
                            path.write_bytes(raw)
                            paths[name] = path
                        staged = stage_file_set_artifact(
                            files=paths,
                            primary_file="result.json",
                            job_id=job_id,
                            logical_artifact_id=identity,
                            revision_id=revision_id,
                            artifact_type=job.task_type,
                            staging=staging,
                            created_at=job.created_at,
                            manifest_version=CONTROL_FILE_SET_PROTOCOL,
                            file_metadata={
                                name: {
                                    "schema_ref": benchmark_measurement_member_schema(name),
                                    "media_type": "application/octet-stream"
                                    if name.endswith(".f64")
                                    else "application/json",
                                }
                                for name, _raw in value.members
                            },
                        )
                    intent = dict(
                        request_sha256=request.request_sha256,
                        content_hash=staged.primary_hash,
                        manifest_hash=staged.manifest_hash,
                        result_sha256=value.result.result_sha256,
                        launch_receipt_sha256s=[receipt.receipt_sha256 for receipt in receipts],
                        source_commit=self.settings.runtime_source_commit,
                    )
                    transition_job(session, job_id, JobState.COMMITTING, _COMMITTING, data=intent)
            # The preceding current-source root is committed; NAS never shares its transaction.
            final = commit_file_set_artifact(staged, self.settings.nas_artifact_root)
            assert value is not None
            with (
                self.owner.sessions() as session,
                session.begin(),
                self.owner.admission.admit_execution_in_session(session, request),
            ):
                current, current_receipts = self._current(session, request, job_id)
                if (
                    current.status != JobState.COMMITTING
                    or current_receipts != value.launch_receipts
                ):
                    raise _invalid()
                self._recover(
                    final, request, current, current_receipts, self._intent(session, job_id)
                )
                # Sealed local bytes and worker-result JSON do not resolve their
                # external members. Fail in this root, before recording success.
                self.source_validator.validate_in_session(
                    session, request, job_id=job_id, value=value
                )
                create_artifact_records(
                    session,
                    job=current,
                    content_hash=staged.primary_hash,
                    manifest_hash=staged.manifest_hash,
                    content_bytes=staged.primary_bytes,
                    nas_path=str(final),
                    manifest=staged.manifest,
                    result=value.result.model_dump(mode="json"),
                )
                transition_job(
                    session,
                    job_id,
                    JobState.SUCCEEDED,
                    _COMMITTED,
                    data={
                        "logical_artifact_id": identity,
                        "revision_id": revision_id,
                        "content_hash": staged.primary_hash,
                    },
                )
                return self._published(current, value, created=True)
