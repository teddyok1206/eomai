"""Explicit manual benchmark control and Artifact reads under actual Identity/source fences."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass

from eom_catalog_contracts.embedding_device_benchmark import (
    BENCHMARK_LAUNCH_ARTIFACT_TYPE,
    BENCHMARK_POLICY_ARTIFACT_TYPE,
    BENCHMARK_POLICY_SCHEMA_REF,
    EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF,
    MAX_BENCHMARK_ENVELOPE_BYTES,
    MAX_BENCHMARK_OUTPUT_BYTES,
    BenchmarkColdTiming,
    BenchmarkExecutionPolicy,
    BenchmarkLocalBinary,
    BenchmarkNearTieReference,
    BenchmarkOwnerRequest,
    BenchmarkQueryTiming,
    BenchmarkStagedInputs,
    BenchmarkTokenWitness,
    benchmark_local_output_members,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark_bytes,
    validate_benchmark_invocation,
)
from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.validation import catalog_schema_registry
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_identity_service import (
    AuthenticatedOperatorSession,
    AuthenticatedSessionFence,
    CapturedOperatorAuthorizationFence,
)
from eom_identity_service.repository import active_role_assignments
from eom_operator_identity import PermissionKey, RoleKey
from eom_orchestrator.embedding_benchmark_launch_history import CompletedBenchmarkLaunch
from eom_orchestrator.file_set_control_artifacts import CONTROL_FILE_SET_PROTOCOL
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from eom_catalog_service.embedding_benchmark_cpu_reference import (
    CPU_REFERENCE_SCHEMA,
    validate_cpu_benchmark_reference,
)
from eom_catalog_service.embedding_benchmark_numerical_assessment import BenchmarkNumericalLaunch
from eom_catalog_service.embedding_benchmark_sources import CatalogBenchmarkSourceAdmission
from eom_catalog_service.embedding_benchmark_timing_evidence import BenchmarkLaunchTimings
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings


@dataclass(frozen=True, slots=True)
class BenchmarkOwnerConfiguration:
    """Reviewed installed selection for one exact request, never worker-provided authority."""

    request_sha256: str
    execution_policy: ArtifactMemberPointer
    execution_policy_sha256: str

    def __post_init__(self) -> None:
        pointer = ArtifactMemberPointer.model_validate(
            self.execution_policy.model_dump(mode="json")
        )
        adapter = TypeAdapter(Sha256)
        adapter.validate_python(self.request_sha256)
        adapter.validate_python(self.execution_policy_sha256)
        if (
            pointer.member_path != "policy.json"
            or pointer.schema_ref != BENCHMARK_POLICY_SCHEMA_REF
            or pointer.media_type != "application/json"
        ):
            raise ValueError("BENCHMARK_OWNER_CONFIGURATION_INVALID")
        object.__setattr__(self, "execution_policy", pointer)


@dataclass(frozen=True, slots=True)
class BenchmarkCpuNumericalReference:
    """Resolved immutable CPU1 bytes, not publication chronology or source authority."""

    pointer: ArtifactMemberPointer
    raw: bytes
    scores: bytes


def _read_cpu_numerical_reference(
    reader: PinnedArtifactReadContext,
    request: BenchmarkOwnerRequest,
    pointer: ArtifactMemberPointer,
    raw: bytes,
) -> BenchmarkCpuNumericalReference:
    reference = parse_embedding_device_benchmark_bytes(raw)
    if not isinstance(reference, BenchmarkNearTieReference) or (
        reference.score_binary.artifact_id,
        reference.score_binary.artifact_revision_id,
    ) != (pointer.artifact_id, pointer.artifact_revision_id):
        raise ValueError("BENCHMARK_CPU_REFERENCE_CLOSURE_INVALID")
    binary = reader.read_pinned(
        **reference.score_binary.model_dump(mode="python"),
        expected_artifact_types=(BENCHMARK_LAUNCH_ARTIFACT_TYPE,),
        expected_primary_file="worker-result.json",
        max_bytes=272,
    ).payload
    validate_cpu_benchmark_reference(request, pointer, raw, binary)
    return BenchmarkCpuNumericalReference(pointer, raw, binary)


class CatalogBenchmarkOwnerAdmission:
    """No login, identity minting, policy publication/selection or compute launch here."""

    def __init__(
        self,
        engine: Engine,
        configuration: BenchmarkOwnerConfiguration,
        *,
        capture: AuthenticatedOperatorSession,
        session_fence: AuthenticatedSessionFence,
        settings: CatalogSettings | None = None,
    ) -> None:
        configuration.__post_init__()
        self.configuration = configuration
        self._settings = settings or CatalogSettings.from_environment()
        self._control = CapturedOperatorAuthorizationFence(
            capture, session_fence, PermissionKey.EXECUTION_PRESET_MANAGE
        )
        self._source = CatalogBenchmarkSourceAdmission(
            engine, capture=capture, session_fence=session_fence, settings=self._settings
        )

    def _fence(self, session: Session, request: BenchmarkOwnerRequest) -> None:
        embedding_device_benchmark_bytes(request)
        if (
            request.request_sha256 != self.configuration.request_sha256
            or request.execution_policy.policy_sha256 != self.configuration.execution_policy_sha256
            or request.operator_audit_id != self._control.capture.operator_id
        ):
            raise ValueError("BENCHMARK_OWNER_SELECTION_MISMATCH")
        self._control.fence_current_operator(session, request.operator_audit_id)
        if RoleKey.ADMIN.value not in {
            role.role_key for _, role in active_role_assignments(session, request.operator_audit_id)
        }:
            raise ValueError("BENCHMARK_OWNER_ADMIN_REQUIRED")

    def _policy(self, session: Session, request: BenchmarkOwnerRequest) -> None:
        pointer = self.configuration.execution_policy
        reader = PinnedArtifactReadContext(session, self._settings)
        reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
        reader.require_file_set(
            pointer.artifact_id,
            pointer.artifact_revision_id,
            ("policy.json",),
            manifest_version=CONTROL_FILE_SET_PROTOCOL,
        )
        raw = reader.read_pinned(
            **pointer.model_dump(mode="python"),
            expected_artifact_types=(BENCHMARK_POLICY_ARTIFACT_TYPE,),
            expected_primary_file="policy.json",
            max_bytes=MAX_BENCHMARK_ENVELOPE_BYTES,
        ).payload
        policy = parse_embedding_device_benchmark_bytes(raw)
        if (
            not isinstance(policy, BenchmarkExecutionPolicy)
            or embedding_device_benchmark_bytes(policy) != raw
            or policy != request.execution_policy
        ):
            raise ValueError("BENCHMARK_OWNER_POLICY_MISMATCH")
        reader.require_session(session)

    @contextmanager
    def admit_in_session(
        self, session: Session, request: BenchmarkOwnerRequest
    ) -> Iterator[BenchmarkStagedInputs]:
        self._fence(session, request)
        self._policy(session, request)
        with self._source.admit_in_session(session, request) as inputs:
            yield inputs
            self._fence(session, request)

    def admit_execution_in_session(
        self, session: Session, request: BenchmarkOwnerRequest
    ) -> AbstractContextManager[BenchmarkStagedInputs]:
        """Explicit compute-purpose entry, not the source-only admission interface."""
        return self.admit_in_session(session, request)

    def read_in_session(
        self, session: Session, request: BenchmarkOwnerRequest, pointer: ArtifactMemberPointer
    ) -> bytes:
        """The journal's explicit current root, never an ambient or captured SQL session."""
        pointer = ArtifactMemberPointer.model_validate(pointer.model_dump(mode="json"))
        expected_schemas = {
            "worker-result.json": EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF + "#/$defs/workerResult",
            "near-tie-reference.json": CPU_REFERENCE_SCHEMA,
        }
        if (
            pointer.schema_ref != expected_schemas.get(pointer.member_path)
            or pointer.media_type != "application/json"
        ):
            raise ValueError("BENCHMARK_OWNER_RESULT_POINTER_INVALID")
        with self.admit_in_session(session, request):
            reader = PinnedArtifactReadContext(session, self._settings)
            reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
            raw = reader.read_pinned(
                **pointer.model_dump(mode="python"),
                expected_artifact_types=(BENCHMARK_LAUNCH_ARTIFACT_TYPE,),
                expected_primary_file="worker-result.json",
                max_bytes=MAX_BENCHMARK_ENVELOPE_BYTES,
            ).payload
            if pointer.member_path == "near-tie-reference.json":
                _read_cpu_numerical_reference(reader, request, pointer, raw)
            reader.require_session(session)
            return raw

    def read_cpu_numerical_reference_in_session(
        self, session: Session, request: BenchmarkOwnerRequest, pointer: ArtifactMemberPointer
    ) -> BenchmarkCpuNumericalReference:
        """Materialize the exact CPU1 seal and f64 member through the existing source root."""
        pointer = ArtifactMemberPointer.model_validate(pointer.model_dump(mode="json"))
        if (
            pointer.member_path != "near-tie-reference.json"
            or pointer.schema_ref != CPU_REFERENCE_SCHEMA
            or pointer.media_type != "application/json"
        ):
            raise ValueError("BENCHMARK_OWNER_RESULT_POINTER_INVALID")
        with self.admit_in_session(session, request):
            reader = PinnedArtifactReadContext(session, self._settings)
            reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
            raw = reader.read_pinned(
                **pointer.model_dump(mode="python"),
                expected_artifact_types=(BENCHMARK_LAUNCH_ARTIFACT_TYPE,),
                expected_primary_file="worker-result.json",
                max_bytes=MAX_BENCHMARK_ENVELOPE_BYTES,
            ).payload
            resolved = _read_cpu_numerical_reference(reader, request, pointer, raw)
            reader.revalidate_provenance()
            reader.require_session(session)
            return resolved

    def read_launch_numerics_in_session(
        self, session: Session, request: BenchmarkOwnerRequest, launch: CompletedBenchmarkLaunch
    ) -> BenchmarkNumericalLaunch:
        """Resolve original token/f32 members once; pure assessment owns their numeric meaning."""
        invocation, receipt, result = launch.invocation, launch.receipt, launch.result
        embedding_device_benchmark_bytes(invocation)
        embedding_device_benchmark_bytes(receipt)
        result_raw = embedding_device_benchmark_bytes(result)
        identity = receipt.worker_result.artifact_id, receipt.worker_result.artifact_revision_id
        witness_descriptor = result.token_witness
        if (
            receipt.invocation_sha256 != invocation.invocation_sha256
            or receipt.job_id != invocation.job_id
            or receipt.execution_id != invocation.execution_id
            or receipt.device != invocation.device
            or receipt.launch_ordinal != invocation.launch_ordinal
            or receipt.cleanup != "CONFIRMED"
            or result.status != "COMPLETED"
            or result.execution_id != invocation.execution_id
            or result.invocation_sha256 != invocation.invocation_sha256
            or result.device != invocation.device
            or result.launch_ordinal != invocation.launch_ordinal
            or witness_descriptor is None
            or sha256_bytes(result_raw) != receipt.worker_result.sha256
            or (receipt.session.artifact_id, receipt.session.artifact_revision_id) != identity
        ):
            raise ValueError("BENCHMARK_OWNER_NUMERICAL_CLOSURE_INVALID")
        descriptors: dict[str, BenchmarkLocalBinary] = {}
        for sample in result.vectors:
            sample_name = sample.binary.member_name
            if sample_name in descriptors and descriptors[sample_name] != sample.binary:
                raise ValueError("BENCHMARK_OWNER_NUMERICAL_CLOSURE_INVALID")
            descriptors[sample_name] = sample.binary
        if (
            set(descriptors)
            != {
                name
                for name in benchmark_local_output_members(invocation.launch_ordinal)
                if name.endswith(".f32")
            }
            or sum(value.byte_count for value in descriptors.values()) > MAX_BENCHMARK_OUTPUT_BYTES
        ):
            raise ValueError("BENCHMARK_OWNER_NUMERICAL_CLOSURE_INVALID")
        with self.admit_in_session(session, request) as inputs:
            validate_benchmark_invocation(request, invocation, inputs)
            reader = PinnedArtifactReadContext(session, self._settings)
            reader.prefetch((identity,))
            original = reader.member_pointer(
                *identity,
                "worker-result.json",
                schema_ref=EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF + "#/$defs/workerResult",
                media_type="application/json",
            )
            if original != receipt.worker_result:
                raise ValueError("BENCHMARK_OWNER_NUMERICAL_CLOSURE_INVALID")
            witness_pointer = reader.member_pointer(
                *identity,
                witness_descriptor.member_name,
                schema_ref=witness_descriptor.schema_ref,
                media_type="application/json",
            )
            witness_raw = reader.read_pinned(
                **witness_pointer.model_dump(mode="python"),
                expected_artifact_types=(BENCHMARK_LAUNCH_ARTIFACT_TYPE,),
                expected_primary_file="worker-result.json",
                max_bytes=witness_descriptor.byte_count,
            ).payload
            if (
                witness_pointer.sha256 != witness_descriptor.sha256
                or len(witness_raw) != witness_descriptor.byte_count
            ):
                raise ValueError("BENCHMARK_OWNER_NUMERICAL_CLOSURE_INVALID")
            try:
                witness = parse_embedding_device_benchmark_bytes(
                    witness_raw, maximum_bytes=MAX_BENCHMARK_OUTPUT_BYTES
                )
                if (
                    not isinstance(witness, BenchmarkTokenWitness)
                    or embedding_device_benchmark_bytes(witness) != witness_raw
                    or witness.invocation_sha256 != invocation.invocation_sha256
                    or witness.launch_ordinal != invocation.launch_ordinal
                ):
                    raise ValueError()
            except (ValueError, RecursionError, SchemaError):
                raise ValueError("BENCHMARK_OWNER_NUMERICAL_MEMBER_INVALID") from None
            binaries = []
            for name, descriptor in sorted(descriptors.items()):
                pointer = reader.member_pointer(
                    *identity,
                    name,
                    schema_ref="eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0",
                    media_type="application/octet-stream",
                )
                if pointer.sha256 != descriptor.sha256:
                    raise ValueError("BENCHMARK_OWNER_NUMERICAL_CLOSURE_INVALID")
                raw = reader.read_pinned(
                    **pointer.model_dump(mode="python"),
                    expected_artifact_types=(BENCHMARK_LAUNCH_ARTIFACT_TYPE,),
                    expected_primary_file="worker-result.json",
                    max_bytes=descriptor.byte_count,
                ).payload
                if len(raw) != descriptor.byte_count:
                    raise ValueError("BENCHMARK_OWNER_NUMERICAL_CLOSURE_INVALID")
                binaries.append((name, raw))
            reader.revalidate_provenance()
            reader.require_session(session)
            return BenchmarkNumericalLaunch(invocation, result, witness, tuple(binaries))

    def read_launch_timings_in_session(
        self, session: Session, request: BenchmarkOwnerRequest, launch: CompletedBenchmarkLaunch
    ) -> BenchmarkLaunchTimings:
        """Exact receipt Artifact timing members, under current original-source authority."""
        invocation, receipt, result = launch.invocation, launch.receipt, launch.result
        embedding_device_benchmark_bytes(invocation)
        embedding_device_benchmark_bytes(receipt)
        result_raw = embedding_device_benchmark_bytes(result)
        identity = receipt.worker_result.artifact_id, receipt.worker_result.artifact_revision_id
        if (
            receipt.invocation_sha256 != invocation.invocation_sha256
            or receipt.job_id != invocation.job_id
            or receipt.execution_id != invocation.execution_id
            or receipt.device != invocation.device
            or receipt.launch_ordinal != invocation.launch_ordinal
            or receipt.cleanup != "CONFIRMED"
            or result.status != "COMPLETED"
            or result.execution_id != invocation.execution_id
            or result.invocation_sha256 != invocation.invocation_sha256
            or result.device != invocation.device
            or result.launch_ordinal != invocation.launch_ordinal
            or result.timings is None
            or sha256_bytes(result_raw) != receipt.worker_result.sha256
            or (receipt.session.artifact_id, receipt.session.artifact_revision_id) != identity
        ):
            raise ValueError("BENCHMARK_OWNER_TIMING_CLOSURE_INVALID")
        with self.admit_in_session(session, request) as inputs:
            validate_benchmark_invocation(request, invocation, inputs)
            reader = PinnedArtifactReadContext(session, self._settings)
            reader.prefetch((identity,))
            original = reader.member_pointer(
                *identity,
                "worker-result.json",
                schema_ref=EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF + "#/$defs/workerResult",
                media_type="application/json",
            )
            if original != receipt.worker_result:
                raise ValueError("BENCHMARK_OWNER_TIMING_CLOSURE_INVALID")

            def fragment[Timing: (BenchmarkColdTiming, BenchmarkQueryTiming)](
                name: str, definition: str, model: type[Timing]
            ) -> Timing:
                pointer = reader.member_pointer(
                    *identity,
                    name,
                    schema_ref=EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF + "#/$defs/" + definition,
                    media_type="application/json",
                )
                raw = reader.read_pinned(
                    **pointer.model_dump(mode="python"),
                    expected_artifact_types=(BENCHMARK_LAUNCH_ARTIFACT_TYPE,),
                    expected_primary_file="worker-result.json",
                    max_bytes=65536,
                ).payload
                try:
                    document = json.loads(raw)
                    Draft202012Validator(
                        {"$ref": pointer.schema_ref}, registry=catalog_schema_registry()
                    ).validate(document)
                    value = model.model_validate(document)
                    if canonical_json_bytes(value) != raw:
                        raise ValueError()
                    return value
                except (ValueError, RecursionError, SchemaError):
                    raise ValueError("BENCHMARK_OWNER_TIMING_MEMBER_INVALID") from None

            cold = fragment("cold-timing.json", "coldTiming", BenchmarkColdTiming)
            queries = (
                tuple(
                    fragment(f"query-timing-{q}-{r}.json", "queryTiming", BenchmarkQueryTiming)
                    for q in (1, 2)
                    for r in range(1, 6)
                )
                if invocation.launch_ordinal in (1, 2)
                else ()
            )
            reader.revalidate_provenance()
            reader.require_session(session)
            return BenchmarkLaunchTimings(invocation, result.timings, cold, queries)
