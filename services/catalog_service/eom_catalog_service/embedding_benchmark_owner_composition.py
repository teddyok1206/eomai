"""Explicit fresh-operator six-launch composition; no login, root helper or implicit run."""

from __future__ import annotations

import os
import re

from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark_bytes,
)
from eom_identifiers import sha256_bytes
from eom_identity_service import AuthenticatedOperatorSession, AuthenticatedSessionFence
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkExecutionOwner
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.inference_transfer_cpu_handoff import fixed_owner_identity
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.embedding_benchmark_launch_execution import FixedBenchmarkLaunchExecution
from eom_catalog_service.embedding_benchmark_launch_publication import (
    BenchmarkLaunchArtifactPublisher,
)
from eom_catalog_service.embedding_benchmark_owner_admission import (
    BenchmarkOwnerConfiguration,
    CatalogBenchmarkOwnerAdmission,
)
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_catalog_service.settings import CatalogSettings


def build_benchmark_execution_owner(
    publisher: ControlFileSetPublisher,
    *,
    request: BenchmarkOwnerRequest,
    configuration: BenchmarkOwnerConfiguration,
    capture: AuthenticatedOperatorSession,
    session_fence: AuthenticatedSessionFence,
    cpu: NativeEmbeddingBackendPins,
    cuda: NativeEmbeddingBackendPins,
    controller_release: str,
) -> BenchmarkExecutionOwner:
    """Assemble one actual current capture and selected installed owners, never a grant.

    Construction reads OS identity only, not SQL or Artifact bytes. The owner
    still admits the actual administrator, policy, sources and original Job before
    numerical effects. A separate reviewed root controller must serve the exact
    original stage; this function cannot start/retry it or authenticate a user.
    """
    try:
        identity = fixed_owner_identity()
        if (
            os.getresuid() != (identity.owner_uid,) * 3
            or os.getresgid() != (identity.owner_gid,) * 3
            or os.getgroups()
            or type(publisher) is not ControlFileSetPublisher
            or type(configuration) is not BenchmarkOwnerConfiguration
            or type(capture) is not AuthenticatedOperatorSession
            or type(session_fence) is not AuthenticatedSessionFence
            or type(cpu) is not NativeEmbeddingBackendPins
            or type(cuda) is not NativeEmbeddingBackendPins
        ):
            raise ValueError()
        configuration.__post_init__()
        session_fence.__post_init__()
        cpu.__post_init__()
        cuda.__post_init__()
        checked = parse_embedding_device_benchmark_bytes(embedding_device_benchmark_bytes(request))
        commit = publisher.settings.runtime_source_commit
        if not isinstance(checked, BenchmarkOwnerRequest) or (
            type(commit) is not str
            or re.fullmatch(r"[0-9a-f]{40}", commit) is None
            or controller_release != commit
            or capture.operator_id != checked.operator_audit_id
            or session_fence.owner.fresh_auth_seconds > 900
            or configuration.request_sha256 != checked.request_sha256
            or configuration.execution_policy_sha256 != checked.execution_policy.policy_sha256
            or configuration.execution_policy.sha256
            != sha256_bytes(embedding_device_benchmark_bytes(checked.execution_policy))
            or cpu.configuration_revision_id == cuda.configuration_revision_id
        ):
            raise ValueError()
        admission = CatalogBenchmarkOwnerAdmission(
            publisher.engine,
            configuration,
            capture=capture,
            session_fence=session_fence,
            settings=CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root),
        )
        execution = FixedBenchmarkLaunchExecution(
            checked,
            cpu=cpu,
            cuda=cuda,
            controller_release=commit,
            publisher=BenchmarkLaunchArtifactPublisher(publisher, source_commit=commit),
        )
        return BenchmarkExecutionOwner(publisher.sessions, admission=admission, execution=execution)
    except (ValueError, TypeError, SchemaError, AttributeError, KeyError, OSError):
        # Schema representations can contain untrusted extras or private input.
        raise ValueError("BENCHMARK_OWNER_COMPOSITION_INVALID") from None
