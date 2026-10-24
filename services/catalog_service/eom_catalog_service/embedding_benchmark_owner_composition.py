"""Explicit fresh-operator benchmark composition; no login, root helper or implicit run."""

from __future__ import annotations

import os
import re

from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    benchmark_policy_schema_ref,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark_bytes,
)
from eom_identifiers import sha256_bytes
from eom_identity_service import AuthenticatedOperatorSession, AuthenticatedSessionFence
from eom_orchestrator.embedding_benchmark_launch_recovery import BenchmarkLaunchRecoveryApplication
from eom_orchestrator.embedding_benchmark_poststart_failure import (
    BenchmarkPoststartFailureApplication,
)
from eom_orchestrator.embedding_benchmark_preack_recovery import (
    BenchmarkPreackRecoveryApplication,
)
from eom_orchestrator.embedding_benchmark_prelaunch_failure import (
    BenchmarkPrelaunchFailureApplication,
)
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkExecutionOwner
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.inference_transfer_cpu_handoff import fixed_owner_identity
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.embedding_benchmark_budget600_poststart_inspection import (
    FixedBudget600PoststartInspection,
)
from eom_catalog_service.embedding_benchmark_launch_execution import FixedBenchmarkLaunchExecution
from eom_catalog_service.embedding_benchmark_launch_publication import (
    BenchmarkLaunchArtifactPublisher,
)
from eom_catalog_service.embedding_benchmark_owner_admission import (
    BenchmarkOwnerConfiguration,
    CatalogBenchmarkOwnerAdmission,
)
from eom_catalog_service.embedding_benchmark_poststart_inspection import (
    FixedBenchmarkPoststartInspection,
)
from eom_catalog_service.embedding_benchmark_preack_inspection import (
    FixedBenchmarkFailedAttemptInspection,
    FixedBenchmarkPreackInspection,
)
from eom_catalog_service.embedding_benchmark_prelaunch_inspection import (
    FixedBenchmarkPrelaunchInspection,
)
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_catalog_service.settings import CatalogSettings


def _owner_admission(
    publisher: ControlFileSetPublisher,
    *,
    request: BenchmarkOwnerRequest,
    configuration: BenchmarkOwnerConfiguration,
    capture: AuthenticatedOperatorSession,
    session_fence: AuthenticatedSessionFence,
) -> tuple[BenchmarkOwnerRequest, str, CatalogBenchmarkOwnerAdmission]:
    """Shared construction checks, not a cached operator/source authorization grant."""
    identity = fixed_owner_identity()
    if (
        os.getresuid() != (identity.owner_uid,) * 3
        or os.getresgid() != (identity.owner_gid,) * 3
        or os.getgroups()
        or type(publisher) is not ControlFileSetPublisher
        or type(configuration) is not BenchmarkOwnerConfiguration
        or type(capture) is not AuthenticatedOperatorSession
        or type(session_fence) is not AuthenticatedSessionFence
    ):
        raise ValueError()
    configuration.__post_init__()
    session_fence.__post_init__()
    checked = parse_embedding_device_benchmark_bytes(embedding_device_benchmark_bytes(request))
    if not isinstance(checked, BenchmarkOwnerRequest):
        raise ValueError()
    # Only the released long-running benchmark may select Identity's existing
    # one-hour ceiling; the actual session/token/permission fences stay unchanged.
    maximum_fresh_auth_seconds = (
        3600
        if checked.schema_version == "embedding-device-benchmark-request/1.2"
        and checked.execution_policy.schema_version == "embedding-device-benchmark-policy/1.2"
        and checked.execution_policy.timeout_seconds == 1200
        else 900
    )
    commit = publisher.settings.runtime_source_commit
    if (
        type(commit) is not str
        or re.fullmatch(r"[0-9a-f]{40}", commit) is None
        or capture.operator_id != checked.operator_audit_id
        or session_fence.owner.fresh_auth_seconds > maximum_fresh_auth_seconds
        or configuration.request_sha256 != checked.request_sha256
        or configuration.execution_policy_sha256 != checked.execution_policy.policy_sha256
        or configuration.execution_policy.schema_ref
        != benchmark_policy_schema_ref(checked.execution_policy)
        or configuration.execution_policy.sha256
        != sha256_bytes(embedding_device_benchmark_bytes(checked.execution_policy))
    ):
        raise ValueError()
    admission = CatalogBenchmarkOwnerAdmission(
        publisher.engine,
        configuration,
        capture=capture,
        session_fence=session_fence,
        settings=CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root),
    )
    return checked, commit, admission


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
        checked, commit, admission = _owner_admission(
            publisher,
            request=request,
            configuration=configuration,
            capture=capture,
            session_fence=session_fence,
        )
        if (
            type(cpu) is not NativeEmbeddingBackendPins
            or type(cuda) is not NativeEmbeddingBackendPins
        ):
            raise ValueError()
        cpu.__post_init__()
        cuda.__post_init__()
        if (
            controller_release != commit
            or cpu.configuration_revision_id == cuda.configuration_revision_id
        ):
            raise ValueError()
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


def build_benchmark_prelaunch_failure_application(
    publisher: ControlFileSetPublisher,
    *,
    request: BenchmarkOwnerRequest,
    configuration: BenchmarkOwnerConfiguration,
    capture: AuthenticatedOperatorSession,
    session_fence: AuthenticatedSessionFence,
    inspection: FixedBenchmarkPrelaunchInspection,
) -> BenchmarkPrelaunchFailureApplication:
    """Select the protected root-proof adapter and actual fresh operator admission.

    Construction reads neither proof/OS observations nor SQL/Artifact bytes. Root
    provenance, current OS state and real administrator/source authority are still
    independently checked by the application before its failure-recording effect.
    Closure starts no compute and requires no native backend or capacity claim.
    """
    try:
        if type(inspection) is not FixedBenchmarkPrelaunchInspection:
            raise ValueError()
        inspection.__post_init__()
        _checked, _commit, admission = _owner_admission(
            publisher,
            request=request,
            configuration=configuration,
            capture=capture,
            session_fence=session_fence,
        )
        return BenchmarkPrelaunchFailureApplication(
            publisher.sessions, admission=admission, inspection=inspection
        )
    except (ValueError, TypeError, SchemaError, AttributeError, KeyError, OSError):
        raise ValueError("BENCHMARK_PRELAUNCH_COMPOSITION_INVALID") from None


def build_benchmark_poststart_failure_application(
    publisher: ControlFileSetPublisher,
    *,
    request: BenchmarkOwnerRequest,
    configuration: BenchmarkOwnerConfiguration,
    capture: AuthenticatedOperatorSession,
    session_fence: AuthenticatedSessionFence,
    inspection: FixedBenchmarkPoststartInspection | FixedBudget600PoststartInspection,
) -> BenchmarkPoststartFailureApplication:
    """Select actual protected partial-failure inspection; no launch or source grant."""
    try:
        if type(inspection) not in (
            FixedBenchmarkPoststartInspection,
            FixedBudget600PoststartInspection,
        ):
            raise ValueError()
        inspection.__post_init__()
        _checked, _commit, admission = _owner_admission(
            publisher,
            request=request,
            configuration=configuration,
            capture=capture,
            session_fence=session_fence,
        )
        return BenchmarkPoststartFailureApplication(
            publisher.sessions, admission=admission, inspection=inspection
        )
    except (ValueError, TypeError, SchemaError, AttributeError, KeyError, OSError):
        raise ValueError("BENCHMARK_POSTSTART_COMPOSITION_INVALID") from None


def build_benchmark_preack_recovery_application(
    publisher: ControlFileSetPublisher,
    *,
    request: BenchmarkOwnerRequest,
    configuration: BenchmarkOwnerConfiguration,
    capture: AuthenticatedOperatorSession,
    session_fence: AuthenticatedSessionFence,
    inspection: FixedBenchmarkPreackInspection,
) -> BenchmarkPreackRecoveryApplication:
    """Bind current real operator/source authority, not a root JSON permission grant."""
    if type(inspection) is not FixedBenchmarkPreackInspection:
        raise ValueError("BENCHMARK_PREACK_COMPOSITION_INVALID")
    inspection.__post_init__()
    _checked, _commit, admission = _owner_admission(
        publisher,
        request=request,
        configuration=configuration,
        capture=capture,
        session_fence=session_fence,
    )
    return BenchmarkPreackRecoveryApplication(
        publisher.sessions, admission=admission, inspection=inspection
    )


def build_benchmark_failed_attempt_recovery_application(
    publisher: ControlFileSetPublisher,
    *,
    request: BenchmarkOwnerRequest,
    configuration: BenchmarkOwnerConfiguration,
    capture: AuthenticatedOperatorSession,
    session_fence: AuthenticatedSessionFence,
    inspection: FixedBenchmarkFailedAttemptInspection,
) -> BenchmarkLaunchRecoveryApplication:
    """Only a pinned root terminal proof, with the same actual caller/source admission."""
    if type(inspection) is not FixedBenchmarkFailedAttemptInspection:
        raise ValueError("BENCHMARK_FAILED_ATTEMPT_COMPOSITION_INVALID")
    inspection.__post_init__()
    _checked, _commit, admission = _owner_admission(
        publisher,
        request=request,
        configuration=configuration,
        capture=capture,
        session_fence=session_fence,
    )
    return BenchmarkLaunchRecoveryApplication(
        publisher.sessions, admission=admission, inspection=inspection
    )
