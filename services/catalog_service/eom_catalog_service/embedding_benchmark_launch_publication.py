"""Validate original native bytes and publish once through the existing Artifact owner.

Concrete owner adapter; state/Artifact commit remain Orchestrator responsibilities.
"""

from __future__ import annotations

import os
import pwd
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from eom_catalog_contracts.embedding_device_benchmark import (
    BENCHMARK_LAUNCH_ARTIFACT_TYPE,
    EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF,
    MAX_BENCHMARK_OUTPUT_BYTES,
    BenchmarkColdTiming,
    BenchmarkLaunchReceipt,
    BenchmarkResourceEvidence,
    BenchmarkStagedInputs,
    BenchmarkTokenWitness,
    BenchmarkWorkerInvocation,
    BenchmarkWorkerResult,
    benchmark_local_output_members,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark_bytes,
)
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkLaunchAuthorization
from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetIdentity,
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_orchestrator.inference_transfer_cpu_handoff import (
    fixed_owner_identity,
    protected_cpu_handoff_directory,
    read_protected_cpu_handoff_member,
)
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.embedding_benchmark_launch_control import (
    BenchmarkLaunchCompleted,
    BenchmarkLaunchPrepared,
    benchmark_launch_control_bytes,
)

from eom_catalog_service.embedding_benchmark_cpu_reference import (
    CPU_SCORE_SCHEMA,
    BenchmarkRowVector,
    build_cpu_benchmark_reference,
)
from eom_catalog_service.embedding_benchmark_layout import BENCHMARK_HANDOFF_ROOT
from eom_catalog_service.embedding_benchmark_native_observation import (
    ObservedBenchmarkNativeSession,
)
from eom_catalog_service.embedding_runtime_files import fixed_native_embedding_profile

_JSON_DEFINITIONS = {
    "worker-result.json": "workerResult",
    "resources.json": "resources",
    "timings.json": "invocationTimings",
    "token-witness.json": "tokenWitness",
    "session.json": "session",
    "cold-timing.json": "coldTiming",
    "near-tie-reference.json": "nearTieReference",
}


class _PublicationArguments(TypedDict):
    members: tuple[ControlFileSetMember, ...]
    primary_file: str
    artifact_type: str
    manifest_version: str
    idempotency_key: str
    source_commit: str


@dataclass(frozen=True, slots=True)
class ValidatedBenchmarkOutput:
    """One local validation boundary; retain only matrices needed by CPU reference."""

    result: BenchmarkWorkerResult
    documents: tuple[BenchmarkRowVector, ...]
    queries: tuple[BenchmarkRowVector, ...]


def _cpu_publication_identity(invocation: BenchmarkWorkerInvocation) -> ControlFileSetIdentity:
    """Separate typed identities, stable for this original invocation, not content hashes."""

    def suffix(role: str) -> str:
        return content_sha256(
            {
                "purpose": "CPU_FIRST_BENCHMARK_PUBLICATION_IDENTITY",
                "invocation_sha256": invocation.invocation_sha256,
                "role": role,
            }
        ).removeprefix("sha256:")[:32]

    return ControlFileSetIdentity(
        "job_" + suffix("JOB"), "artifact_" + suffix("ARTIFACT"), "rev_" + suffix("REVISION")
    )


def validate_benchmark_output_bytes(
    invocation: BenchmarkWorkerInvocation,
    inputs: BenchmarkStagedInputs,
    observed: ObservedBenchmarkNativeSession,
    completion: BenchmarkLaunchCompleted,
    members: dict[str, bytes],
) -> ValidatedBenchmarkOutput:
    """One explicit bounded result materialization, O(total bytes + samples*d).

    Caller owns root origin/unit cleanup and protected file capture. This function
    verifies hashes, exact source/purpose/row ranges, tokens and native/owner clocks;
    it cannot attest source authority, numerical parity, performance or cleanup.
    """
    if set(members) != set(benchmark_local_output_members(invocation.launch_ordinal)):
        raise ValueError("BENCHMARK_PUBLICATION_MEMBERS_INVALID")
    if (
        any(type(raw) is not bytes or not raw for raw in members.values())
        or sum(len(raw) for raw in members.values()) > MAX_BENCHMARK_OUTPUT_BYTES
    ):
        raise ValueError("BENCHMARK_PUBLICATION_SIZE_INVALID")
    result = parse_embedding_device_benchmark_bytes(members["worker-result.json"])
    if (
        not isinstance(result, BenchmarkWorkerResult)
        or result.status != "COMPLETED"
        or result.execution_id != invocation.execution_id
        or result.invocation_sha256 != invocation.invocation_sha256
        or result.device != invocation.device
        or result.launch_ordinal != invocation.launch_ordinal
        or embedding_device_benchmark_bytes(result) != members["worker-result.json"]
        or completion.original_outcome != "SUCCEEDED"
        or completion.execution_id != invocation.execution_id
        or completion.invocation_sha256 != invocation.invocation_sha256
        or completion.device != invocation.device
        or completion.launch_ordinal != invocation.launch_ordinal
        or completion.job_id != invocation.job_id
    ):
        # Failed/partial evidence remains local and in original root records;
        # never rewrite it as a completed result or dispatch a replacement here.
        raise ValueError("BENCHMARK_PUBLICATION_RESULT_INCOMPLETE")
    session = observed.session
    if (
        session.execution_id != invocation.execution_id
        or session.invocation_sha256 != invocation.invocation_sha256
        or session.launch_ordinal != invocation.launch_ordinal
        or result.resources != observed.resources
        or (invocation.device == "CUDA" and completion.resources != observed.resources)
        or type(observed.owner_started_ns) is not int
        or type(observed.cold_completed_ns) is not int
        or not 0
        < observed.owner_started_ns
        <= completion.started_ns
        < observed.cold_completed_ns
        <= completion.completed_ns
    ):
        raise ValueError("BENCHMARK_PUBLICATION_OWNER_EVIDENCE_INVALID")
    resources = parse_embedding_device_benchmark_bytes(members["resources.json"])
    if (
        not isinstance(resources, BenchmarkResourceEvidence)
        or resources != result.resources
        or embedding_device_benchmark_bytes(resources) != members["resources.json"]
    ):
        raise ValueError("BENCHMARK_PUBLICATION_RESOURCES_INVALID")
    assert result.token_witness is not None and result.timings is not None
    witness_raw = members["token-witness.json"]
    witness = parse_embedding_device_benchmark_bytes(
        witness_raw, maximum_bytes=MAX_BENCHMARK_OUTPUT_BYTES
    )
    if (
        not isinstance(witness, BenchmarkTokenWitness)
        or len(witness_raw) != result.token_witness.byte_count
        or sha256_bytes(witness_raw) != result.token_witness.sha256
        or embedding_device_benchmark_bytes(witness) != witness_raw
        or witness.invocation_sha256 != invocation.invocation_sha256
        or witness.launch_ordinal != invocation.launch_ordinal
    ):
        raise ValueError("BENCHMARK_PUBLICATION_TOKENS_INVALID")
    if invocation.launch_ordinal in (1, 2) and members[
        "timings.json"
    ] != embedding_device_benchmark_bytes(result.timings):
        raise ValueError("BENCHMARK_PUBLICATION_TIMINGS_INVALID")
    if tuple((t.query_ordinal, t.repetition, t.encode_ns) for t in observed.queries) != tuple(
        (t.query_ordinal, t.repetition, t.encode_ns) for t in result.timings.query_encode_ns
    ):
        raise ValueError("BENCHMARK_PUBLICATION_QUERY_CLOCKS_INVALID")
    binary_hashes = {
        name: sha256_bytes(raw) for name, raw in members.items() if name.endswith(".f32")
    }
    supplementary_offset = 0
    documents: tuple[BenchmarkRowVector, ...] = ()
    queries: list[BenchmarkRowVector] = []
    for vector, tokens in zip(result.vectors, witness.samples, strict=True):
        key = vector.key
        if key != tokens.key:
            raise ValueError("BENCHMARK_PUBLICATION_SAMPLE_ORDER_INVALID")
        expected_tokens: tuple[tuple[str, int, str | None], ...]
        if key.phase in {"COLD_DOCUMENT", "WARM_DOCUMENT", "QUERY"}:
            selected = (
                inputs.documents
                if key.phase != "QUERY"
                else (inputs.queries[(key.query_ordinal or 1) - 1],)
            )
            expected_tokens = tuple(
                (row.row.row_sha256, row.token_count, row.token_ids_sha256) for row in selected
            )
            expected_rows = tuple(row.row.row_sha256 for row in selected)
        else:
            fixture = (
                inputs.capacity
                if key.phase == "CAPACITY"
                else inputs.synthetic_cases[(key.synthetic_case or 1) - 1]
            )
            expected_tokens = (
                (fixture.input_text_sha256, fixture.token_count, fixture.token_ids_sha256),
            ) * key.batch_size
            expected_rows = ()
        actual_tokens = tuple(
            (row.row_sha256, row.token_count, row.token_ids_sha256)
            for batch in tokens.batches
            for row in batch.rows
        )
        expected_space = (
            invocation.runtime.spaces.query
            if vector.purpose == "QUERY"
            else invocation.runtime.spaces.document
        )
        raw = members[vector.binary.member_name]
        if vector.binary.member_name == "supplementary-documents.f32":
            if vector.byte_offset != supplementary_offset:
                raise ValueError("BENCHMARK_PUBLICATION_VECTOR_RANGE_INVALID")
            supplementary_offset += vector.byte_count
        if (
            vector.ordered_rows != expected_rows
            or vector.space_sha256 != expected_space.space_sha256
            or actual_tokens != expected_tokens
            or vector.binary.byte_count != len(raw)
            or vector.binary.sha256 != binary_hashes[vector.binary.member_name]
        ):
            raise ValueError("BENCHMARK_PUBLICATION_VECTOR_ASSOCIATION_INVALID")
        sample = raw[vector.byte_offset : vector.byte_offset + vector.byte_count]
        decoded = read_unit_vectors(
            sample,
            dimension=1024,
            row_count=vector.row_count,
            expected_sha256=sha256_bytes(sample),
        )
        if invocation.launch_ordinal == 1 and key.phase == "COLD_DOCUMENT":
            documents = tuple(
                (row.row, values) for row, values in zip(inputs.documents, decoded, strict=True)
            )
        elif invocation.launch_ordinal == 1 and key.phase == "QUERY" and key.repetition == 1:
            assert key.query_ordinal is not None
            queries.append((inputs.queries[key.query_ordinal - 1].row, decoded[0]))
    if supplementary_offset != len(members.get("supplementary-documents.f32", b"")):
        raise ValueError("BENCHMARK_PUBLICATION_VECTOR_RANGE_INVALID")
    # Checkpoint vector hashes must identify the exact committed cold/query files.
    for checkpoint in session.checkpoints:
        if checkpoint.vector is not None:
            pointer = checkpoint.vector
            raw = members[pointer.member_name]
            if pointer.sha256 != binary_hashes[pointer.member_name] or pointer.byte_count != len(
                raw
            ):
                raise ValueError("BENCHMARK_PUBLICATION_CHECKPOINT_BYTES_INVALID")
    return ValidatedBenchmarkOutput(result, documents, tuple(queries))


class BenchmarkLaunchArtifactPublisher:
    """No compute dispatch. A separate publication Job uses the existing file-set owner."""

    def __init__(self, publisher: ControlFileSetPublisher, *, source_commit: str) -> None:
        self.publisher, self.source_commit = publisher, source_commit

    def publish(
        self,
        invocation: BenchmarkWorkerInvocation,
        inputs: BenchmarkStagedInputs,
        observed: ObservedBenchmarkNativeSession,
        prepared: BenchmarkLaunchPrepared,
        completion: BenchmarkLaunchCompleted,
        *,
        authorization: BenchmarkLaunchAuthorization,
    ) -> BenchmarkLaunchReceipt:
        owner = fixed_owner_identity()
        if (
            os.getresuid() != (owner.owner_uid,) * 3
            or os.getresgid() != (owner.owner_gid,) * 3
            or type(authorization) is not BenchmarkLaunchAuthorization
        ):
            raise ValueError("BENCHMARK_PUBLICATION_OWNER_REQUIRED")
        authorization.assert_invocation(invocation)
        root = BENCHMARK_HANDOFF_ROOT / invocation.execution_id
        with protected_cpu_handoff_directory(
            root, owner=owner, uid=0, gid=owner.owner_gid, mode=0o750
        ) as directory:
            for name, record in (
                ("root-prepared.json", prepared),
                ("root-completion.json", completion),
            ):
                raw = read_protected_cpu_handoff_member(
                    directory, name, uid=0, gid=owner.owner_gid, mode=0o640, maximum_bytes=65536
                )
                if raw != benchmark_launch_control_bytes(record):
                    raise ValueError("BENCHMARK_PUBLICATION_ROOT_RECORD_CHANGED")
        native = pwd.getpwnam(
            fixed_native_embedding_profile(invocation.runtime.profile).worker_user
        )
        names = benchmark_local_output_members(invocation.launch_ordinal)
        with protected_cpu_handoff_directory(
            root / "outputs", owner=owner, uid=0, gid=owner.owner_gid, mode=0o750
        ) as directory:
            if set(os.listdir(directory)) != set(names):
                raise ValueError("BENCHMARK_PUBLICATION_MEMBERS_INVALID")
            members = {
                name: read_protected_cpu_handoff_member(
                    directory,
                    name,
                    uid=native.pw_uid,
                    gid=owner.owner_gid,
                    mode=0o640,
                    maximum_bytes=MAX_BENCHMARK_OUTPUT_BYTES,
                )
                for name in names
            }
        validated = validate_benchmark_output_bytes(
            invocation, inputs, observed, completion, members
        )
        result = validated.result
        assert result.timings is not None
        cold = BenchmarkColdTiming(
            launch_ordinal=invocation.launch_ordinal,
            end_to_end_ns=observed.cold_completed_ns - observed.owner_started_ns,
            startup_ns=result.timings.startup_ns,
            load_hash_ns=result.timings.load_hash_ns,
            encode_ns=result.timings.cold_encode_ns,
        )
        members.update(
            {
                "session.json": embedding_device_benchmark_bytes(observed.session),
                "root-prepared.json": benchmark_launch_control_bytes(prepared),
                "root-completion.json": benchmark_launch_control_bytes(completion),
                "cold-timing.json": canonical_json_bytes(cold.model_dump(mode="json")),
            }
        )
        identity = None
        if invocation.launch_ordinal == 1:
            identity = _cpu_publication_identity(invocation)
            reference, scores = build_cpu_benchmark_reference(
                invocation,
                validated.documents,
                validated.queries,
                artifact_id=identity.artifact_id,
                artifact_revision_id=identity.artifact_revision_id,
            )
            members["near-tie-reference.json"] = embedding_device_benchmark_bytes(reference)
            members["rank-evidence.f64"] = scores
        members.update(
            {
                f"query-timing-{t.query_ordinal}-{t.repetition}.json": canonical_json_bytes(
                    t.model_dump(mode="json")
                )
                for t in observed.queries
            }
        )

        def schema(name: str) -> str:
            if name.startswith("root-"):
                definition = "prepared" if name == "root-prepared.json" else "completed"
                return (
                    "eom://schemas/workflow/embedding-benchmark-launch-control/1.0#/$defs/"
                    + definition
                )
            if name.endswith(".f32"):
                return "eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0"
            if name == "rank-evidence.f64":
                return CPU_SCORE_SCHEMA
            definition = (
                "queryTiming" if name.startswith("query-timing-") else _JSON_DEFINITIONS[name]
            )
            return EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF + "#/$defs/" + definition

        # Explicit publication materialization. Native/root bytes are never modified.
        with tempfile.TemporaryDirectory(
            prefix="benchmark-publication-", dir=self.publisher.settings.workspace_root
        ) as temporary:
            files = []
            # The existing file-set protocol requires unique lexical member order.
            # Native program order is a different invariant and stays in its result.
            for name in sorted(members):
                raw = members[name]
                path = Path(temporary) / name
                path.write_bytes(raw)
                path.chmod(0o600)
                files.append(
                    ControlFileSetMember(
                        name,
                        path,
                        sha256_bytes(raw),
                        len(raw),
                        schema(name),
                        "application/octet-stream"
                        if name.endswith((".f32", ".f64"))
                        else "application/json",
                    )
                )
            authorization.assert_invocation(invocation)
            arguments: _PublicationArguments = dict(
                members=tuple(files),
                primary_file="worker-result.json",
                artifact_type=BENCHMARK_LAUNCH_ARTIFACT_TYPE,
                manifest_version=CONTROL_FILE_SET_PROTOCOL,
                idempotency_key="embedding-benchmark-launch:"
                + invocation.invocation_sha256.removeprefix("sha256:"),
                source_commit=self.source_commit,
            )
            if identity is None:
                published = self.publisher.publish_first_observation(**arguments)
            else:
                published = self.publisher.publish_identified_first_observation(
                    identity=identity, **arguments
                )
            # Commit is not a distributed transaction with the source grant. A late
            # revocation preserves committed bytes/key and the unresolved original;
            # it never triggers another model run or an invented rollback deletion.
            authorization.assert_invocation(invocation)
        if published.job_id == invocation.job_id:
            raise ValueError("BENCHMARK_PUBLICATION_JOB_MUST_BE_SEPARATE")
        if identity is not None and (
            published.job_id,
            published.artifact_id,
            published.artifact_revision_id,
        ) != (identity.job_id, identity.artifact_id, identity.artifact_revision_id):
            raise ValueError("BENCHMARK_CPU_REFERENCE_PUBLICATION_IDENTITY_CHANGED")

        def pointer(name: str) -> dict[str, str]:
            return ArtifactMemberPointer(
                artifact_id=published.artifact_id,
                artifact_revision_id=published.artifact_revision_id,
                member_path=name,
                schema_ref=schema(name),
                media_type="application/json",
                sha256=sha256_bytes(members[name]),
            ).model_dump(mode="json")

        body = dict(
            schema_version="embedding-device-benchmark-launch-receipt/1.0",
            job_id=invocation.job_id,
            execution_id=invocation.execution_id,
            launch_ordinal=invocation.launch_ordinal,
            device=invocation.device,
            invocation_sha256=invocation.invocation_sha256,
            observed_runtime_sha256=invocation.runtime.numerical_runtime.runtime_sha256,
            worker_result=pointer("worker-result.json"),
            session=pointer("session.json"),
            evidence=pointer(
                "near-tie-reference.json" if identity is not None else "root-completion.json"
            ),
            cleanup="CONFIRMED",
        )
        return BenchmarkLaunchReceipt.model_validate(
            body | {"receipt_sha256": content_sha256(body)}
        )
