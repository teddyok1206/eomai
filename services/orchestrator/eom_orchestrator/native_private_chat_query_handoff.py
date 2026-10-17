"""Private-question CPU descriptors; no source, command or physical-launch grant."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eom_catalog_contracts.embedding_private_chat_query import (
    MAX_PRIVATE_CHAT_QUERY_BYTES,
    EmbeddingPrivateChatQueryInput,
    EmbeddingPrivateChatQueryResult,
    validate_private_chat_query_result,
)
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_runtime_bundle import (
    MAX_RUNTIME_BUNDLE_BYTES,
    EmbeddingRuntimeBundle,
    parse_embedding_runtime_bundle,
)
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_identifiers import canonical_json_bytes
from eom_workflow.private_chat_query_execution import (
    PrivateChatQueryExecutionPolicy,
    PrivateChatQueryWorkflowRequest,
)
from eom_workflow.private_chat_query_publication import (
    PrivateChatQueryLaunchAssociation,
    validate_private_chat_query_launch,
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
from eom_orchestrator.native_embedding_query_handoff import validate_native_query_execution_id

OWNER_ROOT = Path("/var/lib/eom-workflow-runner/incremental-embeddings/private-chat-query")
RUNTIME_ROOT = Path("/run/eom-embedding-native-private-chat-query")


class NativePrivateQueryHandoffError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PreparedNativePrivateChatQuery:
    execution_id: str
    workflow_request: PrivateChatQueryWorkflowRequest
    policy: PrivateChatQueryExecutionPolicy
    bundle: EmbeddingRuntimeBundle
    association: PrivateChatQueryLaunchAssociation
    request: EmbeddingPrivateChatQueryInput

    def __post_init__(self) -> None:
        try:
            validate_native_query_execution_id(self.execution_id)
            request = PrivateChatQueryWorkflowRequest.model_validate(
                raw_similarity_contract_value(self.workflow_request)
            )
            policy = PrivateChatQueryExecutionPolicy.model_validate(
                raw_similarity_contract_value(self.policy)
            )
            bundle = parse_embedding_runtime_bundle(raw_similarity_contract_value(self.bundle))
            launch = PrivateChatQueryLaunchAssociation.model_validate(
                raw_similarity_contract_value(self.association)
            )
            native = EmbeddingPrivateChatQueryInput.model_validate(
                raw_similarity_contract_value(self.request)
            )
            validate_private_chat_query_launch(launch, request, policy, bundle, native)
            validate_fixed_native_cpu_resources(request.resource_profile)
            if native.job_id != "job_" + self.execution_id:
                raise ValueError()
        except Exception:
            # Nested schema failures can contain private question bytes.
            raise NativePrivateQueryHandoffError("NATIVE_PRIVATE_QUERY_INPUT_INVALID") from None
        for field, value in (
            ("workflow_request", request),
            ("policy", policy),
            ("bundle", bundle),
            ("association", launch),
            ("request", native),
        ):
            object.__setattr__(self, field, value)

    @property
    def workspace(self) -> Path:
        return OWNER_ROOT / self.execution_id

    def owner_members(self) -> tuple[tuple[str, bytes], ...]:
        return tuple(
            (name, canonical_json_bytes(value))
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
        raise NativePrivateQueryHandoffError("NATIVE_PRIVATE_QUERY_OWNER_REQUIRED")
    return owner


def require_native_private_query_owner_root() -> None:
    owner = fixed_owner_identity()
    try:
        with protected_cpu_handoff_directory(
            OWNER_ROOT, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
        ):
            pass
    except CpuHandoffError:
        raise NativePrivateQueryHandoffError("NATIVE_PRIVATE_QUERY_OWNER_LAYOUT_INVALID") from None


def stage_native_private_chat_query(prepared: PreparedNativePrivateChatQuery) -> None:
    prepared.__post_init__()
    owner = _owner()
    ensure_protected_cpu_owner_workspace(OWNER_ROOT, prepared.execution_id, owner=owner)
    with protected_cpu_handoff_directory(
        prepared.workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        for name, raw in prepared.owner_members():
            write_protected_cpu_owner_member(directory, name, raw, owner=owner)


def _canonical_value(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise NativePrivateQueryHandoffError("NATIVE_PRIVATE_QUERY_CANONICAL_INPUT_INVALID")
    return value


def _read_prepared(execution_id: str, owner: CpuHandoffIdentity) -> PreparedNativePrivateChatQuery:
    validate_native_query_execution_id(execution_id)
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
                    maximum_bytes=MAX_RUNTIME_BUNDLE_BYTES
                    if name == "bundle.json"
                    else MAX_PRIVATE_CHAT_QUERY_BYTES,
                )
            )

        try:
            return PreparedNativePrivateChatQuery(
                execution_id,
                PrivateChatQueryWorkflowRequest.model_validate(read("workflow.json")),
                PrivateChatQueryExecutionPolicy.model_validate(read("policy.json")),
                parse_embedding_runtime_bundle(read("bundle.json")),
                PrivateChatQueryLaunchAssociation.model_validate(read("association.json")),
                EmbeddingPrivateChatQueryInput.model_validate(read("input.json")),
            )
        except Exception:
            raise NativePrivateQueryHandoffError(
                "NATIVE_PRIVATE_QUERY_STAGED_INPUT_INVALID"
            ) from None


def mark_native_private_query_launch_started(prepared: PreparedNativePrivateChatQuery) -> None:
    """Owner must first commit the original origin/claim/launch under its SQL fences."""
    prepared.__post_init__()
    owner = _owner()
    if _read_prepared(prepared.execution_id, owner) != prepared:
        raise NativePrivateQueryHandoffError("NATIVE_PRIVATE_QUERY_STAGED_INPUT_CHANGED")
    with protected_cpu_handoff_directory(
        prepared.workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        write_protected_cpu_owner_member(
            directory,
            ".launch-started",
            prepared.association.association_sha256.encode("ascii"),
            owner=owner,
        )


def prepare_native_private_query_handoff(execution_id: str) -> None:
    if os.geteuid() != 0:
        raise NativePrivateQueryHandoffError("NATIVE_PRIVATE_QUERY_ROOT_REQUIRED")
    owner = fixed_owner_identity()
    prepared = _read_prepared(execution_id, owner)
    with protected_cpu_handoff_directory(
        prepared.workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        marker = read_protected_cpu_handoff_member(
            directory, ".launch-started", uid=owner.owner_uid, gid=owner.owner_gid, mode=0o600
        )
    if marker != prepared.association.association_sha256.encode("ascii"):
        raise NativePrivateQueryHandoffError("NATIVE_PRIVATE_QUERY_LAUNCH_MARKER_INVALID")
    create_native_cpu_descriptor_handoff(
        RUNTIME_ROOT, execution_id, canonical_json_bytes(prepared.request), owner=owner
    )


def materialize_native_private_query_output(
    prepared: PreparedNativePrivateChatQuery,
) -> EmbeddingPrivateChatQueryResult:
    prepared.__post_init__()
    owner = _owner()
    if _read_prepared(prepared.execution_id, owner) != prepared:
        raise NativePrivateQueryHandoffError("NATIVE_PRIVATE_QUERY_STAGED_INPUT_CHANGED")
    with protected_cpu_handoff_directory(
        RUNTIME_ROOT / prepared.execution_id, owner=owner, uid=0, gid=owner.owner_gid, mode=0o750
    ) as directory:
        raw = read_protected_cpu_handoff_member(
            directory,
            "result.json",
            uid=0,
            gid=owner.owner_gid,
            mode=0o640,
            maximum_bytes=MAX_PRIVATE_CHAT_QUERY_BYTES,
        )
        vectors = read_protected_cpu_handoff_member(
            directory,
            "vectors.f32",
            uid=0,
            gid=owner.owner_gid,
            mode=0o640,
            maximum_bytes=prepared.request.spaces.query.model_spec.dimension * 4,
        )
    try:
        result = EmbeddingPrivateChatQueryResult.model_validate(_canonical_value(raw))
        validate_private_chat_query_result(prepared.request, result)
        read_unit_vectors(
            vectors,
            dimension=result.shard.dimension,
            row_count=1,
            expected_sha256=result.shard.binary.sha256,
        )
    except Exception:
        raise NativePrivateQueryHandoffError("NATIVE_PRIVATE_QUERY_OUTPUT_INVALID") from None
    with protected_cpu_handoff_directory(
        prepared.workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        write_protected_cpu_owner_member(directory, "vectors.f32", vectors, owner=owner)
        write_protected_cpu_owner_member(directory, "result.json", raw, owner=owner)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("execution_id")
    arguments = parser.parse_args()
    try:
        prepare_native_private_query_handoff(arguments.execution_id)
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
