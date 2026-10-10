"""Typed synthetic ports: no real session, source, SQL, socket, or model acceptance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.errors import ApiError
from eom_api.lifespan import AppServices, build_services
from eom_api.services.idempotency_service import IdempotencyClaim
from eom_api.services.inference_transfer_snapshot import InferenceTransferSnapshotApplicationService
from eom_api.services.inference_transfer_snapshot_port import InferenceTransferSnapshotReadError
from eom_api.services.inference_transfer_submission import (
    AuthorizedInferenceTransferSubmission,
    InferenceTransferSubmissionApplicationService,
)
from eom_api.services.inference_transfer_workflow_read import (
    InferenceTransferWorkflowReadApplicationService,
    InferenceTransferWorkflowReadError,
)
from eom_api.settings import ApiSecrets, ApiSettings
from eom_catalog_contracts.inference_transfer_invocation import (
    InferenceTransferPairSubmitRequest,
    InferenceTransferWorkflowReadRequest,
    InferenceTransferWorkflowReadResult,
)
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotPrepareRequest,
    InferenceTransferSnapshotReadRequest,
    InferenceTransferSnapshotRecord,
    InferenceTransferSnapshotRequest,
    InferenceTransferSnapshotResult,
)
from eom_identifiers import content_sha256
from eom_identity_service.tokens import AccessAuthentication
from eom_operator_identity import (
    ActorContext,
    OperatorProjection,
    OperatorStatus,
    PermissionKey,
    RoleKey,
)
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tests.unit.inference_transfer_fixtures import request as pair_request
from tests.unit.inference_transfer_invocation_fixtures import WORKFLOW_ID, read_result
from tests.unit.inference_transfer_snapshot_fixtures import (
    hashed,
    snapshot_header,
    snapshot_prepare,
    snapshot_prepare_result,
    snapshot_read_result,
    snapshot_records,
)

ACTOR_ID = "operator_" + "a" * 32
NOW = datetime(2026, 10, 10, 9, tzinfo=UTC)
PERMISSIONS = frozenset(
    {
        PermissionKey.WORKFLOW_START,
        PermissionKey.WORKFLOW_READ,
        PermissionKey.ITEM_READ,
        PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
        PermissionKey.KNOWLEDGE_ANALYSIS_READ,
        PermissionKey.CONTENT_INTAKE_READ,
    }
)


def authentication(permissions: frozenset[PermissionKey] = PERMISSIONS) -> AccessAuthentication:
    return AccessAuthentication(
        operator=OperatorProjection(
            operator_id=ACTOR_ID,
            username="synthetic-transfer-operator",
            display_name="Synthetic transfer operator",
            status=OperatorStatus.ACTIVE,
            must_change_password=False,
            roles=(RoleKey.VIEWER,),
            effective_permissions=tuple(sorted(permissions, key=str)),
            resource_version=1,
            created_at=NOW,
            updated_at=NOW,
        ),
        session_id="apisession_" + "b" * 32,
        authenticated_at=NOW,
        access_expires_at=NOW + timedelta(hours=1),
        permissions=permissions,
        password_change_required=False,
    )


class SnapshotReader:
    def __init__(
        self,
        *,
        records: tuple[InferenceTransferSnapshotRecord, ...] | None = None,
        prepare: InferenceTransferSnapshotPrepareRequest | None = None,
    ) -> None:
        self.records = snapshot_records() if records is None else records
        self.prepared = snapshot_prepare_result(
            self.records,
            header=snapshot_header(
                self.records, prepare=prepare or snapshot_prepare(), actor_id=ACTOR_ID
            ),
        )
        self.calls: list[tuple[str, InferenceTransferSnapshotRequest]] = []
        self.failure: str | None = None
        self.prepare_reply: InferenceTransferSnapshotResult | None = None
        self.read_reply: InferenceTransferSnapshotResult | None = None

    def execute(
        self, actor_id: str, request: InferenceTransferSnapshotRequest
    ) -> InferenceTransferSnapshotResult:
        self.calls.append((actor_id, request))
        if self.failure is not None:
            raise InferenceTransferSnapshotReadError(self.failure)
        if isinstance(request, InferenceTransferSnapshotPrepareRequest):
            return self.prepare_reply or self.prepared
        assert isinstance(request, InferenceTransferSnapshotReadRequest)
        if self.read_reply is not None:
            return self.read_reply
        by_revision = {row.index_entry.source_item_revision_id: row for row in self.records}
        selected = tuple(
            by_revision[row.source_item_revision_id] for row in request.selected_index_entries
        )
        return snapshot_read_result(
            selected,
            request=request,
            baselines=(),
            limitations=("Synthetic owner does not execute the official Graph baseline.",),
        )


def selection(
    reader: SnapshotReader, *, reverse: bool = False
) -> InferenceTransferPairSubmitRequest:
    # Missing reports still select original exact pointers, never fabricated replacements.
    originals = snapshot_records()
    left = originals[1 if reverse else 0].staged_entry
    right = originals[0 if reverse else 1].staged_entry
    assert left is not None and right is not None
    return hashed(
        InferenceTransferPairSubmitRequest,
        "submission_sha256",
        comparison=pair_request(left.profile, right.profile),
        snapshot_prepare=reader.prepared.header.prepare,
        expected_header_sha256=reader.prepared.header.header_sha256,
    )


class Starter:
    def __init__(self) -> None:
        self.calls: list[tuple[AuthorizedInferenceTransferSubmission, ActorContext, str]] = []

    def start(
        self,
        submission: AuthorizedInferenceTransferSubmission,
        actor: ActorContext,
        *,
        idempotency_key: str,
    ) -> tuple[str, str, int]:
        self.calls.append((submission, actor, idempotency_key))
        return "wfcmd_" + "c" * 32, WORKFLOW_ID, 1


class WorkflowReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, InferenceTransferWorkflowReadRequest]] = []
        self.failure: str | None = None
        self.reply: InferenceTransferWorkflowReadResult | None = None

    def execute(
        self, actor_id: str, request: InferenceTransferWorkflowReadRequest
    ) -> InferenceTransferWorkflowReadResult:
        self.calls.append((actor_id, request))
        if self.failure is not None:
            raise InferenceTransferWorkflowReadError(self.failure)
        return self.reply or read_result(verified=request.mode == "CANONICAL_RESULT")


class MemoryIdempotency:
    def __init__(self) -> None:
        self.requests: dict[tuple[str, str, str], str] = {}
        self.responses: dict[str, dict[str, Any]] = {}
        self.claims: list[tuple[str, str, str]] = []
        self.failures: list[str] = []

    @staticmethod
    def request_hash(**values: Any) -> str:
        return content_sha256(values)

    def claim(
        self, *, operator_id: str, endpoint_key: str, raw_key: str, request_sha256: str
    ) -> IdempotencyClaim:
        key = (operator_id, endpoint_key, raw_key)
        self.claims.append(key)
        if key in self.requests and self.requests[key] != request_sha256:
            raise ApiError(409, "API_IDEMPOTENCY_CONFLICT", "Conflict", "Synthetic key conflict.")
        self.requests[key] = request_sha256
        record_id = "apiidem_" + content_sha256(key).removeprefix("sha256:")[:32]
        return IdempotencyClaim(record_id, self.responses.get(record_id), 202)

    def complete(self, claim: IdempotencyClaim, *, body: dict[str, Any], **values: Any) -> None:
        self.responses[claim.record_id] = body

    def fail_final(self, claim: IdempotencyClaim, error_code: str) -> None:
        self.failures.append(error_code)

    @staticmethod
    def submission_key(**values: Any) -> str:
        return "api:" + content_sha256(values).removeprefix("sha256:")


class Audit:
    def __init__(self) -> None:
        self.events: list[str] = []

    def append(self, context: object, *, event_type: str, **values: Any) -> None:
        self.events.append(event_type)


@dataclass
class ApiHarness:
    client: TestClient
    services: AppServices
    snapshots: SnapshotReader
    starter: Starter
    workflows: WorkflowReader
    idempotency: MemoryIdempotency
    authentication: AccessAuthentication


def harness(reader: SnapshotReader | None = None) -> ApiHarness:
    services = build_services(
        ApiSettings(),
        ApiSecrets(
            database_url=SecretStr("postgresql+psycopg://invalid:invalid@127.0.0.1:1/invalid"),
            token_hash_key=SecretStr("TEST_ONLY_API_TOKEN_HASH_KEY_0123456789"),
            fingerprint_key=SecretStr("TEST_ONLY_FINGERPRINT_KEY_012345678901"),
        ),
    )
    snapshots, starter, workflows, idempotency = (
        reader or SnapshotReader(),
        Starter(),
        WorkflowReader(),
        MemoryIdempotency(),
    )
    services.audit = Audit()  # type: ignore[assignment]
    services.idempotency = idempotency  # type: ignore[assignment]
    services.inference_transfer_snapshots = InferenceTransferSnapshotApplicationService(snapshots)
    services.inference_transfer_submissions = InferenceTransferSubmissionApplicationService(
        services.inference_transfer_snapshots, starter
    )
    services.inference_transfer_workflow_reads = InferenceTransferWorkflowReadApplicationService(
        workflows
    )
    app = create_app(services)
    value = ApiHarness(
        TestClient(app, base_url="http://localhost"),
        services,
        snapshots,
        starter,
        workflows,
        idempotency,
        authentication(),
    )

    def authenticated(request: Request) -> AccessAuthentication:
        request.state.request_context.authentication = value.authentication
        return value.authentication

    app.dependency_overrides[get_authentication] = authenticated
    return value
