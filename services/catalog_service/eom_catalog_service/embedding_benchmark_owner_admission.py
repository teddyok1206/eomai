"""Explicit manual benchmark control and Artifact reads under actual Identity/source fences."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass

from eom_catalog_contracts.embedding_device_benchmark import (
    BENCHMARK_LAUNCH_ARTIFACT_TYPE,
    BENCHMARK_POLICY_ARTIFACT_TYPE,
    BENCHMARK_POLICY_SCHEMA_REF,
    EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF,
    MAX_BENCHMARK_ENVELOPE_BYTES,
    BenchmarkExecutionPolicy,
    BenchmarkOwnerRequest,
    BenchmarkStagedInputs,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark_bytes,
)
from eom_catalog_contracts.models import Sha256
from eom_identity_service import (
    AuthenticatedOperatorSession,
    AuthenticatedSessionFence,
    CapturedOperatorAuthorizationFence,
)
from eom_identity_service.repository import active_role_assignments
from eom_operator_identity import PermissionKey, RoleKey
from eom_orchestrator.file_set_control_artifacts import CONTROL_FILE_SET_PROTOCOL
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import TypeAdapter
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from eom_catalog_service.embedding_benchmark_sources import CatalogBenchmarkSourceAdmission
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
        if (
            pointer.member_path != "worker-result.json"
            or pointer.schema_ref != EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF + "#/$defs/workerResult"
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
            reader.require_session(session)
            return raw
