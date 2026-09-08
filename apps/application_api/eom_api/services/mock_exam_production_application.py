"""Authorized application use cases for resumable 25-Item mock-exam production."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Never, Protocol

from eom_api_contracts.deliverables import CreateDeliverableRequest, DeliverableView
from eom_api_contracts.mock_exam_execution import (
    MockExamAnalysisPolicyPointerV1,
    MockExamAssemblyIntentV1,
    MockExamExplicitAnalysisReviewSetV1,
    MockExamExplicitRatingSetV1,
    MockExamGenerationBlockResolutionV1,
    MockExamGraphPublicationInputV1,
    MockExamProductionExecutionV1,
    MockExamRatingPolicyPointerV1,
)
from eom_catalog_contracts.mock_exam_production_plan import MockExamProductionPlanV1
from eom_operator_identity import (
    ActorContext,
    ActorSource,
    ActorType,
    OperatorProjection,
    PermissionKey,
)

_PRODUCTION_REQUEST_ID = re.compile(r"^productionreq_[0-9a-f]{32}$")


class MockExamProductionApplicationError(RuntimeError):
    """Stable operator/application error containing no content or credentials."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MockExamAccessPolicyPointer:
    """Small immutable value extracted from the execution's pinned preset revision."""

    access_policy_revision_id: str
    access_policy_sha256: str


class MockExamProductionRunnerPort(Protocol):
    def initialize(
        self,
        plan: MockExamProductionPlanV1,
        actor: ActorContext,
        *,
        production_request_id: str,
        at: datetime,
    ) -> MockExamProductionExecutionV1: ...

    def get(self, execution_id: str) -> MockExamProductionExecutionV1: ...

    def advance_items(
        self,
        plan: MockExamProductionPlanV1,
        execution_id: str,
        actor: ActorContext,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1: ...

    def advance_analyses(
        self,
        plan: MockExamProductionPlanV1,
        execution_id: str,
        actor: ActorContext,
        policy: MockExamAnalysisPolicyPointerV1,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1: ...

    def review_analyses(
        self,
        plan: MockExamProductionPlanV1,
        execution_id: str,
        actor: ActorContext,
        review_set: MockExamExplicitAnalysisReviewSetV1,
        policy: MockExamAnalysisPolicyPointerV1,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1: ...

    def publish_next_graph_batch(
        self,
        plan: MockExamProductionPlanV1,
        execution_id: str,
        actor: ActorContext,
        publication_input: MockExamGraphPublicationInputV1,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1: ...

    def publish_ratings(
        self,
        plan: MockExamProductionPlanV1,
        execution_id: str,
        actor: ActorContext,
        rating_set: MockExamExplicitRatingSetV1,
        policy: MockExamRatingPolicyPointerV1,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1: ...

    def advance_assembly(
        self,
        plan: MockExamProductionPlanV1,
        execution_id: str,
        actor: ActorContext,
        intent: MockExamAssemblyIntentV1,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1: ...

    def advance_hwpx(
        self,
        plan: MockExamProductionPlanV1,
        execution_id: str,
        actor: ActorContext,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1: ...


class DeliverableCommandPort(Protocol):
    def create_deliverable(
        self,
        request: CreateDeliverableRequest,
        actor: ActorContext,
    ) -> tuple[str, str, int]: ...


class DeliverableQueryPort(Protocol):
    def deliverable(self, deliverable_id: str) -> DeliverableView: ...


class AuthenticatedOperatorAccess(Protocol):
    @property
    def operator(self) -> OperatorProjection: ...

    @property
    def session_id(self) -> str: ...

    @property
    def authenticated_at(self) -> datetime: ...

    @property
    def permissions(self) -> frozenset[PermissionKey]: ...

    @property
    def password_change_required(self) -> bool: ...


class AccessAuthenticationPort(Protocol):
    def authenticate_access(
        self,
        raw_token: str,
        *,
        now: datetime | None = None,
    ) -> AuthenticatedOperatorAccess: ...


class MockExamProductionReleasePort(Protocol):
    def production_plan(self) -> MockExamProductionPlanV1: ...

    def analysis_policy(self) -> MockExamAnalysisPolicyPointerV1: ...

    def rating_policy(self) -> MockExamRatingPolicyPointerV1: ...

    def access_policy(
        self,
        generation: MockExamGenerationBlockResolutionV1,
    ) -> MockExamAccessPolicyPointer: ...


class MockExamProductionDeliverableService:
    """Create/replay one deterministic MOCK_EXAM deliverable per production request."""

    def __init__(self, commands: DeliverableCommandPort, queries: DeliverableQueryPort) -> None:
        self._commands = commands
        self._queries = queries

    def ensure_assembly_intent(
        self,
        production_request_id: str,
        actor: ActorContext,
    ) -> MockExamAssemblyIntentV1:
        if _PRODUCTION_REQUEST_ID.fullmatch(production_request_id) is None:
            _fail(
                "PRODUCTION_REQUEST_ID_INVALID",
                "production request identity is invalid",
            )
        suffix = production_request_id.removeprefix("productionreq_")
        deliverable_key = f"mock-exam-production-{suffix}"
        title = f"통합과학 모의고사 {suffix[:8]}"
        edition = f"production-{suffix[:12]}"
        request = CreateDeliverableRequest(
            deliverable_key=deliverable_key,
            deliverable_type="MOCK_EXAM",
            title=title,
            edition=edition,
        )
        _command_id, deliverable_id, revision_number = self._commands.create_deliverable(
            request,
            actor,
        )
        view = self._queries.deliverable(deliverable_id)
        if (
            view.deliverable_id != deliverable_id
            or view.deliverable_key != deliverable_key
            or view.deliverable_type != "MOCK_EXAM"
            or view.title != title
            or view.edition != edition
            or view.lifecycle_state != "PLANNED"
            or view.deliverable_revision_id is None
            or view.revision_number != revision_number
            or revision_number != 1
        ):
            _fail(
                "PRODUCTION_DELIVERABLE_REPLAY_CONFLICT",
                "the production request resolves to a different deliverable revision",
            )
        return MockExamAssemblyIntentV1(
            deliverable_id=deliverable_id,
            deliverable_revision_id=view.deliverable_revision_id,
            form_key=f"production-{suffix}",
            display_label=title,
        )


class MockExamOperatorAuthenticator:
    """Convert one live authenticated session into a CLI actor without granting permissions."""

    def __init__(self, authentication: AccessAuthenticationPort) -> None:
        self._authentication = authentication

    def authenticate(
        self,
        raw_access_token: str,
        *,
        request_id: str,
        at: datetime,
    ) -> ActorContext:
        authentication = self._authentication.authenticate_access(raw_access_token, now=at)
        if authentication.password_change_required:
            _fail(
                "AUTH_PASSWORD_CHANGE_REQUIRED",
                "the operator must change the temporary password first",
            )
        return ActorContext(
            actor_type=ActorType.OPERATOR,
            operator_id=authentication.operator.operator_id,
            session_id=authentication.session_id,
            request_id=request_id,
            authentication_time=authentication.authenticated_at,
            permissions=authentication.permissions,
            source=ActorSource.CLI,
        )


class MockExamProductionApplicationService:
    """Authorize, resolve immutable inputs, and advance exactly one requested phase."""

    def __init__(
        self,
        *,
        runner: MockExamProductionRunnerPort,
        releases: MockExamProductionReleasePort,
        deliverables: MockExamProductionDeliverableService,
        fresh_auth_seconds: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if fresh_auth_seconds < 60:
            raise ValueError("fresh authentication window must be at least 60 seconds")
        self._runner = runner
        self._releases = releases
        self._deliverables = deliverables
        self._fresh_auth_age = timedelta(seconds=fresh_auth_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))

    def inspect_plan(self, actor: ActorContext) -> MockExamProductionPlanV1:
        self._authorize(actor, {PermissionKey.WORKFLOW_READ}, at=self._now(), fresh=False)
        return self._releases.production_plan()

    def initialize(
        self,
        production_request_id: str,
        actor: ActorContext,
    ) -> MockExamProductionExecutionV1:
        at = self._now()
        self._authorize(
            actor,
            {PermissionKey.WORKFLOW_READ, PermissionKey.WORKFLOW_START},
            at=at,
            fresh=False,
        )
        return self._runner.initialize(
            self._releases.production_plan(),
            actor,
            production_request_id=production_request_id,
            at=at,
        )

    def get(self, execution_id: str, actor: ActorContext) -> MockExamProductionExecutionV1:
        at = self._now()
        self._authorize(actor, {PermissionKey.WORKFLOW_READ}, at=at, fresh=False)
        return self._owned_checkpoint(execution_id, actor)

    def advance_items(
        self,
        execution_id: str,
        actor: ActorContext,
    ) -> MockExamProductionExecutionV1:
        at = self._now()
        self._authorize(
            actor,
            {
                PermissionKey.WORKFLOW_READ,
                PermissionKey.WORKFLOW_START,
                PermissionKey.WORKFLOW_APPROVE,
                PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
            },
            at=at,
            fresh=True,
        )
        self._owned_checkpoint(execution_id, actor)
        return self._runner.advance_items(
            self._releases.production_plan(), execution_id, actor, at=at
        )

    def advance_analyses(
        self,
        execution_id: str,
        actor: ActorContext,
    ) -> MockExamProductionExecutionV1:
        at = self._now()
        self._authorize(
            actor,
            {
                PermissionKey.KNOWLEDGE_ANALYSIS_CREATE,
                PermissionKey.KNOWLEDGE_ANALYSIS_READ,
            },
            at=at,
            fresh=True,
        )
        self._owned_checkpoint(execution_id, actor)
        return self._runner.advance_analyses(
            self._releases.production_plan(),
            execution_id,
            actor,
            self._releases.analysis_policy(),
            at=at,
        )

    def review_analyses(
        self,
        execution_id: str,
        actor: ActorContext,
        review_set: MockExamExplicitAnalysisReviewSetV1,
    ) -> MockExamProductionExecutionV1:
        at = self._now()
        self._authorize(
            actor,
            {
                PermissionKey.KNOWLEDGE_ANALYSIS_READ,
                PermissionKey.KNOWLEDGE_ANALYSIS_REVIEW,
            },
            at=at,
            fresh=True,
        )
        self._owned_checkpoint(execution_id, actor)
        return self._runner.review_analyses(
            self._releases.production_plan(),
            execution_id,
            actor,
            review_set,
            self._releases.analysis_policy(),
            at=at,
        )

    def publish_graph(
        self,
        execution_id: str,
        actor: ActorContext,
        publication_input: MockExamGraphPublicationInputV1,
    ) -> MockExamProductionExecutionV1:
        at = self._now()
        self._authorize(
            actor,
            {
                PermissionKey.KNOWLEDGE_GRAPH_READ,
                PermissionKey.KNOWLEDGE_GRAPH_PUBLISH,
            },
            at=at,
            fresh=True,
        )
        checkpoint = self._owned_checkpoint(execution_id, actor)
        generation = checkpoint.generation_block_resolution
        if generation is None:
            _fail(
                "PRODUCTION_GENERATION_BLOCK_UNRESOLVED",
                "the execution has not pinned its generation block",
            )
        access = self._releases.access_policy(generation)
        if (
            publication_input.access_policy_revision_id != access.access_policy_revision_id
            or publication_input.access_policy_sha256 != access.access_policy_sha256
        ):
            _fail(
                "PRODUCTION_ACCESS_POLICY_POINTER_MISMATCH",
                "graph publication input differs from the pinned preset access policy",
            )
        return self._runner.publish_next_graph_batch(
            self._releases.production_plan(),
            execution_id,
            actor,
            publication_input,
            at=at,
        )

    def publish_ratings(
        self,
        execution_id: str,
        actor: ActorContext,
        rating_set: MockExamExplicitRatingSetV1,
    ) -> MockExamProductionExecutionV1:
        at = self._now()
        self._authorize(
            actor,
            {
                PermissionKey.ITEM_READ,
                PermissionKey.WORKFLOW_APPROVE,
            },
            at=at,
            fresh=True,
        )
        self._owned_checkpoint(execution_id, actor)
        return self._runner.publish_ratings(
            self._releases.production_plan(),
            execution_id,
            actor,
            rating_set,
            self._releases.rating_policy(),
            at=at,
        )

    def advance_assembly(
        self,
        execution_id: str,
        actor: ActorContext,
    ) -> MockExamProductionExecutionV1:
        at = self._now()
        self._authorize(
            actor,
            {
                PermissionKey.DELIVERABLE_CREATE,
                PermissionKey.DELIVERABLE_READ,
            },
            at=at,
            fresh=False,
        )
        checkpoint = self._owned_checkpoint(execution_id, actor)
        if checkpoint.state != "ASSEMBLY" and checkpoint.assembly_intent is None:
            _fail(
                "PRODUCTION_ASSEMBLY_NOT_READY",
                "the execution is not ready to provision its mock-exam deliverable",
            )
        intent = self._deliverables.ensure_assembly_intent(
            checkpoint.production_request_id,
            actor,
        )
        if checkpoint.assembly_intent is not None and checkpoint.assembly_intent != intent:
            _fail(
                "PRODUCTION_ASSEMBLY_INTENT_MISMATCH",
                "the replayed deliverable differs from the pinned assembly intent",
            )
        return self._runner.advance_assembly(
            self._releases.production_plan(),
            execution_id,
            actor,
            intent,
            at=at,
        )

    def advance_hwpx(
        self,
        execution_id: str,
        actor: ActorContext,
    ) -> MockExamProductionExecutionV1:
        at = self._now()
        self._authorize(
            actor,
            {PermissionKey.HWPX_BUILD_CREATE, PermissionKey.HWPX_READ},
            at=at,
            fresh=False,
        )
        self._owned_checkpoint(execution_id, actor)
        return self._runner.advance_hwpx(
            self._releases.production_plan(), execution_id, actor, at=at
        )

    def _owned_checkpoint(
        self,
        execution_id: str,
        actor: ActorContext,
    ) -> MockExamProductionExecutionV1:
        checkpoint = self._runner.get(execution_id)
        plan = self._releases.production_plan()
        if checkpoint.operator_id != actor.actor_id:
            _fail(
                "PRODUCTION_EXECUTION_OPERATOR_MISMATCH",
                "the authenticated operator does not own this production execution",
            )
        if (
            checkpoint.production_plan_id != plan.production_plan_id
            or checkpoint.production_plan_sha256 != plan.plan_sha256
        ):
            _fail(
                "PRODUCTION_PLAN_POINTER_MISMATCH",
                "the execution does not pin the released static production plan",
            )
        return checkpoint

    def _authorize(
        self,
        actor: ActorContext,
        required: set[PermissionKey],
        *,
        at: datetime,
        fresh: bool,
    ) -> None:
        if (
            actor.actor_type is not ActorType.OPERATOR
            or actor.operator_id is None
            or actor.session_id is None
        ):
            _fail(
                "PRODUCTION_OPERATOR_AUTHENTICATION_REQUIRED",
                "an authenticated operator session is required",
            )
        missing = required.difference(actor.permissions)
        if missing:
            _fail(
                "PRODUCTION_OPERATOR_PERMISSION_DENIED",
                "the authenticated operator lacks a required phase permission",
            )
        if at.tzinfo is None or at.utcoffset() != timedelta(0):
            _fail("PRODUCTION_CLOCK_INVALID", "the application clock must use UTC")
        age = at - actor.authentication_time
        if age < timedelta(0) or (fresh and age > self._fresh_auth_age):
            _fail(
                "PRODUCTION_OPERATOR_REAUTHENTICATION_REQUIRED",
                "this production phase requires recent operator authentication",
            )

    def _now(self) -> datetime:
        return self._clock()


def _fail(code: str, message: str) -> Never:
    raise MockExamProductionApplicationError(code, message)
