"""Fixed QUERY local/root descriptor handoff; no source, claim or physical launch grant."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eom_catalog_contracts.embedding_reference_query import (
    MAX_REFERENCE_QUERY_BYTES,
    EmbeddingReferenceQueryResult,
    parse_embedding_reference_query_result,
    raw_similarity_contract_value,
)
from eom_catalog_contracts.embedding_reference_query_v11 import (
    EmbeddingReferenceQueryInputV11,
    parse_embedding_reference_query_input_v11,
    validate_reference_query_result_v11,
)
from eom_catalog_contracts.embedding_runtime_bundle import (
    MAX_RUNTIME_BUNDLE_BYTES,
    EmbeddingRuntimeBundle,
    parse_embedding_runtime_bundle,
)
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_identifiers import canonical_json_bytes
from eom_workflow.reference_query_execution import (
    ReferenceQueryExecutionPolicy,
    ReferenceQueryLaunchAssociation,
    ReferenceQueryWorkflowRequest,
    parse_reference_query_execution_policy,
    parse_reference_query_launch_association,
    parse_reference_query_workflow_request,
    validate_reference_query_launch_association,
)

from eom_orchestrator.inference_transfer_cpu_handoff import (
    CpuHandoffError,
    CpuHandoffIdentity,
    create_native_cpu_descriptor_handoff,
    ensure_protected_cpu_owner_workspace,
    fixed_owner_identity,
    protected_cpu_handoff_directory,
    read_protected_cpu_handoff_member,
    write_protected_cpu_owner_member,
)
from eom_orchestrator.native_embedding_cpu_execution import validate_fixed_native_cpu_resources

OWNER_ROOT = Path("/var/lib/eom-workflow-runner/incremental-embeddings/query")
RUNTIME_ROOT = Path("/run/eom-embedding-native-query")
MAX_BINARY_BYTES = 64 * 1024**2


class NativeQueryHandoffError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def validate_native_query_execution_id(value: str) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{32}", value, re.ASCII) is None:
        raise NativeQueryHandoffError("NATIVE_QUERY_EXECUTION_ID_INVALID")
    return value


@dataclass(frozen=True, slots=True)
class PreparedNativeQuery:
    """Five existing literal contracts at an explicit temporary materialization boundary."""

    execution_id: str
    workflow_request: ReferenceQueryWorkflowRequest
    policy: ReferenceQueryExecutionPolicy
    bundle: EmbeddingRuntimeBundle
    association: ReferenceQueryLaunchAssociation
    request: EmbeddingReferenceQueryInputV11

    def __post_init__(self) -> None:
        validate_native_query_execution_id(self.execution_id)
        workflow = parse_reference_query_workflow_request(self.workflow_request)
        policy = parse_reference_query_execution_policy(self.policy)
        bundle = parse_embedding_runtime_bundle(raw_similarity_contract_value(self.bundle))
        association = parse_reference_query_launch_association(self.association)
        request = parse_embedding_reference_query_input_v11(self.request)
        validate_reference_query_launch_association(association, workflow, policy, bundle, request)
        validate_fixed_native_cpu_resources(workflow.resource_profile)
        if request.job_id != "job_" + self.execution_id:
            raise NativeQueryHandoffError("NATIVE_QUERY_ASSOCIATION_INPUT_MISMATCH")
        object.__setattr__(self, "workflow_request", workflow)
        object.__setattr__(self, "policy", policy)
        object.__setattr__(self, "bundle", bundle)
        object.__setattr__(self, "association", association)
        object.__setattr__(self, "request", request)

    @property
    def workspace(self) -> Path:
        return OWNER_ROOT / self.execution_id

    def owner_members(self) -> tuple[tuple[str, bytes], ...]:
        return tuple(
            (name, canonical_json_bytes(value.model_dump(mode="json")))
            for name, value in (
                ("workflow.json", self.workflow_request),
                ("policy.json", self.policy),
                ("bundle.json", self.bundle),
                ("association.json", self.association),
                ("input.json", self.request),
            )
        )


def _owner() -> CpuHandoffIdentity:
    owner = fixed_owner_identity()
    if os.geteuid() != owner.owner_uid:
        raise NativeQueryHandoffError("NATIVE_QUERY_OWNER_REQUIRED")
    return owner


def require_native_query_owner_root() -> None:
    """Read-only deployment prerequisite, before numerical launch/allocation.

    Do not silently create or repair the controller-owned root during a query.
    Retained ancestor descriptors enforce the same layout as actual staging.
    """
    owner = fixed_owner_identity()
    try:
        with protected_cpu_handoff_directory(
            OWNER_ROOT, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
        ):
            pass
    except CpuHandoffError:
        raise NativeQueryHandoffError("NATIVE_QUERY_OWNER_LAYOUT_INVALID") from None


def _write(directory: int, name: str, raw: bytes, owner: CpuHandoffIdentity) -> None:
    try:
        write_protected_cpu_owner_member(directory, name, raw, owner=owner)
    except CpuHandoffError as error:
        raise NativeQueryHandoffError(error.code.replace("NATIVE_CPU_", "NATIVE_QUERY_")) from None


def stage_native_query(prepared: PreparedNativeQuery) -> None:
    prepared.__post_init__()
    owner = _owner()
    ensure_protected_cpu_owner_workspace(OWNER_ROOT, prepared.execution_id, owner=owner)
    with protected_cpu_handoff_directory(
        prepared.workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        for name, raw in prepared.owner_members():
            _write(directory, name, raw, owner)


def _canonical_value(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise NativeQueryHandoffError("NATIVE_QUERY_CANONICAL_INPUT_INVALID")
    return value


def _read_prepared(execution_id: str, owner: CpuHandoffIdentity) -> PreparedNativeQuery:
    execution_id = validate_native_query_execution_id(execution_id)
    with protected_cpu_handoff_directory(
        OWNER_ROOT / execution_id, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:

        def read(name: str) -> dict[str, Any]:
            return _canonical_value(
                read_protected_cpu_handoff_member(
                    directory,
                    name,
                    uid=owner.owner_uid,
                    gid=owner.owner_gid,
                    mode=0o600,
                    maximum_bytes=(
                        MAX_RUNTIME_BUNDLE_BYTES
                        if name == "bundle.json"
                        else MAX_REFERENCE_QUERY_BYTES
                    ),
                )
            )

        return PreparedNativeQuery(
            execution_id,
            parse_reference_query_workflow_request(read("workflow.json")),
            parse_reference_query_execution_policy(read("policy.json")),
            parse_embedding_runtime_bundle(read("bundle.json")),
            parse_reference_query_launch_association(read("association.json")),
            parse_embedding_reference_query_input_v11(read("input.json")),
        )


def mark_native_query_launch_started(prepared: PreparedNativeQuery) -> None:
    """Call only after the current source/command owner has committed its original launch."""
    owner = _owner()
    if _read_prepared(prepared.execution_id, owner) != prepared:
        raise NativeQueryHandoffError("NATIVE_QUERY_STAGED_INPUT_CHANGED")
    with protected_cpu_handoff_directory(
        prepared.workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        _write(
            directory,
            ".launch-started",
            prepared.association.association_sha256.encode("ascii"),
            owner,
        )


def prepare_native_query_handoff(execution_id: str) -> None:
    if os.geteuid() != 0:
        raise NativeQueryHandoffError("NATIVE_QUERY_ROOT_REQUIRED")
    owner = fixed_owner_identity()
    prepared = _read_prepared(execution_id, owner)
    with protected_cpu_handoff_directory(
        prepared.workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        marker = read_protected_cpu_handoff_member(
            directory, ".launch-started", uid=owner.owner_uid, gid=owner.owner_gid, mode=0o600
        )
    if marker != prepared.association.association_sha256.encode("ascii"):
        raise NativeQueryHandoffError("NATIVE_QUERY_LAUNCH_MARKER_INVALID")
    try:
        create_native_cpu_descriptor_handoff(
            RUNTIME_ROOT,
            execution_id,
            canonical_json_bytes(prepared.request.model_dump(mode="json")),
            owner=owner,
        )
    except CpuHandoffError as error:
        raise NativeQueryHandoffError(error.code.replace("NATIVE_CPU_", "NATIVE_QUERY_")) from None


def materialize_native_query_output(prepared: PreparedNativeQuery) -> EmbeddingReferenceQueryResult:
    owner = _owner()
    if _read_prepared(prepared.execution_id, owner) != prepared:
        raise NativeQueryHandoffError("NATIVE_QUERY_STAGED_INPUT_CHANGED")
    with protected_cpu_handoff_directory(
        RUNTIME_ROOT / prepared.execution_id, owner=owner, uid=0, gid=owner.owner_gid, mode=0o750
    ) as directory:
        result_raw = read_protected_cpu_handoff_member(
            directory,
            "result.json",
            uid=0,
            gid=owner.owner_gid,
            mode=0o640,
            maximum_bytes=MAX_REFERENCE_QUERY_BYTES,
        )
        vectors = read_protected_cpu_handoff_member(
            directory,
            "vectors.f32",
            uid=0,
            gid=owner.owner_gid,
            mode=0o640,
            maximum_bytes=min(
                MAX_BINARY_BYTES,
                prepared.request.spaces.query.model_spec.dimension * len(prepared.request.rows) * 4,
            ),
        )
    result = parse_embedding_reference_query_result(_canonical_value(result_raw))
    validate_reference_query_result_v11(prepared.request, result)
    read_unit_vectors(
        vectors,
        dimension=result.shard.dimension,
        row_count=result.shard.row_count,
        expected_sha256=result.shard.binary.sha256,
    )
    with protected_cpu_handoff_directory(
        prepared.workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        _write(directory, "vectors.f32", vectors, owner)
        _write(directory, "result.json", result_raw, owner)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("execution_id")
    arguments = parser.parse_args()
    try:
        prepare_native_query_handoff(arguments.execution_id)
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
