"""Official missing-binding discovery into the existing atomic native START queue.

This application neither runs the model nor owns a new queue/target registry. The
installed service composition must supply actual current authority and an executor.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from eom_catalog_contracts.local_indexing_policy import local_indexing_authorization_audit_sha256
from eom_catalog_service.embedding_index_refresh_plan import plan_index_membership_refresh
from eom_catalog_service.embedding_registry_application import prepare_missing_embedding_bindings
from eom_catalog_service.local_embedding_source_plan import build_local_embedding_source_plan
from eom_identifiers import content_sha256
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_workflow.local_embedding_index_refresh import (
    IndexMembershipRefreshBasis,
)
from eom_workflow.local_embedding_request import (
    local_embedding_request_actor,
    parse_local_embedding_executable_request,
)
from eom_workflow.local_embedding_workflow import (
    LOCAL_EMBEDDING_WORKFLOW_KEY,
    LOCAL_EMBEDDING_WORKFLOW_VERSION,
)

from eom_workflow_runner.local_embedding_native_executor import CatalogNativeEmbeddingExecutor
from eom_workflow_runner.local_embedding_owner_admission import CatalogLocalEmbeddingOwnerAdmission
from eom_workflow_runner.local_embedding_submission import (
    LocalEmbeddingWorkflowSubmitted,
    start_local_embedding_in_session,
)
from eom_workflow_runner.repository import admitted_workflow_definition


class ReconciliationState(StrEnum):
    NO_PUBLISHED_GRAPH = "NO_PUBLISHED_GRAPH"
    NO_ELIGIBLE_SOURCE = "NO_ELIGIBLE_SOURCE"
    WAITING_FOR_SOLUTION_REPORT = "WAITING_FOR_SOLUTION_REPORT"
    VIEW_UNAVAILABLE = "VIEW_UNAVAILABLE"
    UP_TO_DATE = "UP_TO_DATE"
    QUEUED = "QUEUED"
    REPLAYED = "REPLAYED"
    TERMINAL_INCOMPLETE = "TERMINAL_INCOMPLETE"


@dataclass(frozen=True, slots=True)
class LocalEmbeddingReconciliationResult:
    """Small observation only: neither a completion receipt nor educational approval."""

    state: ReconciliationState
    graph_snapshot_revision_id: str | None
    eligible_source_count: int = 0
    missing_report_revision_ids: tuple[str, ...] = ()
    unavailable_view_count: int = 0
    missing_binding_count: int = 0
    selected_target_count: int = 0
    reusable_encoding_count: int = 0
    index_refresh_reason: str | None = None
    workflow_id: str | None = None
    command_id: str | None = None
    workflow_state: str | None = None
    command_state: str | None = None


class LocalEmbeddingServiceReconciliation:
    """One bounded observation/submission; scheduling is the installed owner's job."""

    def __init__(self, executor: CatalogNativeEmbeddingExecutor, *, maximum_targets: int = 64):
        if (
            type(executor) is not CatalogNativeEmbeddingExecutor
            or type(executor.owner) is not CatalogLocalEmbeddingOwnerAdmission
            or executor.owner.catalog.engine is not executor.publisher.engine
            or type(maximum_targets) is not int
            or not 1 <= maximum_targets <= 1024
        ):
            raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_CONFIGURATION_INVALID")
        self.executor, self.maximum_targets = executor, maximum_targets
        self.owner = executor.owner
        self.controls = LocalEmbeddingControlArtifactPublisher(
            executor.publisher, source_commit=executor.source_commit
        )

    def run_once(self) -> LocalEmbeddingReconciliationResult:
        owner, executor = self.owner, self.executor
        with executor.publisher.sessions.begin() as session:
            query = owner.current_reconciliation_lookup(session)
            if query is None:
                return LocalEmbeddingReconciliationResult(
                    ReconciliationState.NO_PUBLISHED_GRAPH, None
                )
            controls = owner.resolve_reconciliation_controls(
                session, query, executor.runtime_profile
            )
            prepared = prepare_missing_embedding_bindings(
                session, controls.caller, query, owner.catalog
            )
            missing, resolved = prepared.observation, prepared.resolved
            source_ids = {source.item_revision_id for source in resolved.sources}
            profile_ids = {
                entry.profile.source_basis.source.item_revision_id for entry in resolved.entries
            }
            missing_reports = tuple(sorted(source_ids - profile_ids))
            unavailable = len(profile_ids) - missing.available_view_count
            targets = tuple(sorted({row.item_revision_id for row in missing.missing}))[
                : self.maximum_targets
            ]
            if (
                missing.eligible_source_count != len(source_ids)
                or not profile_ids.issubset(source_ids)
                or unavailable < 0
                or not set(targets).issubset(profile_ids)
            ):
                raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_SOURCE_MISMATCH")
            refresh: IndexMembershipRefreshBasis | None = None
            if prepared.bindings:
                previous = owner.catalog.resolve_indexing_namespace_predecessor(
                    session, controls.caller, query
                )
                refresh = plan_index_membership_refresh(
                    eligible_sources=resolved.sources,
                    available_bindings=prepared.bindings,
                    previous=previous,
                )
                if refresh is not None:
                    # One already available source witnesses this metadata-only
                    # request, even while more sources need vectors. Publish
                    # usable membership before the next ordinary seed/delta.
                    targets = (min(b.source.item_revision_id for b in prepared.bindings),)
            observed = LocalEmbeddingReconciliationResult(
                state=ReconciliationState.UP_TO_DATE,
                graph_snapshot_revision_id=query.graph_snapshot.graph_snapshot_revision_id,
                eligible_source_count=missing.eligible_source_count,
                missing_report_revision_ids=missing_reports,
                unavailable_view_count=unavailable,
                missing_binding_count=len(missing.missing),
                selected_target_count=len(targets),
                reusable_encoding_count=len(missing.reusable_rows),
                index_refresh_reason=None if refresh is None else refresh.reason,
            )
            # Fresh current checks also apply to no-op/report-wait observations.
            late = owner.resolve_reconciliation_controls(session, query, executor.runtime_profile)
            if late != controls:
                raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_SOURCE_MISMATCH")
            if not targets:
                state = (
                    ReconciliationState.NO_ELIGIBLE_SOURCE
                    if not source_ids
                    else ReconciliationState.WAITING_FOR_SOLUTION_REPORT
                    if missing_reports
                    else ReconciliationState.VIEW_UNAVAILABLE
                    if unavailable
                    else ReconciliationState.UP_TO_DATE
                )
                return replace(observed, state=state)
            definition = admitted_workflow_definition(
                session,
                definition_key=LOCAL_EMBEDDING_WORKFLOW_KEY,
                definition_version=LOCAL_EMBEDDING_WORKFLOW_VERSION,
            )
            if definition is None or definition.definition_hash != (
                controls.policy.workflow_definition_sha256
            ):
                raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_DEFINITION_UNAVAILABLE")
            plan = build_local_embedding_source_plan(query, resolved, target_revision_ids=targets)
            plan_key = content_sha256(
                {"plan": plan.plan_sha256, "source_commit": self.controls.source_commit}
            )
            # Only Orchestrator publishes; retained source/service locks protect
            # this preparation root. No model/claim happens while locks are held.
            saved = self.controls.publish_observed_source_plan(
                plan, idempotency_key="local-embedding-plan:" + plan_key.removeprefix("sha256:")
            )
            body = {
                "schema_version": "local-embedding-workflow-request/1.2",
                "request_name": "LOCAL_EMBEDDING_WORKFLOW_REQUEST",
                "purpose": "LOCAL_EMBEDDING",
                "workflow_definition_key": LOCAL_EMBEDDING_WORKFLOW_KEY,
                "workflow_definition_version": LOCAL_EMBEDDING_WORKFLOW_VERSION,
                "workflow_definition_sha256": definition.definition_hash,
                "actor_context": {
                    "kind": "LOCAL_INDEXING_SERVICE",
                    **controls.caller.service.model_dump(mode="json"),
                    "service_policy_revision_id": controls.grant.access_policy_revision_id,
                    "service_policy_sha256": controls.grant.content_sha256,
                    "authorization_audit_sha256": local_indexing_authorization_audit_sha256(
                        controls.grant
                    ),
                },
                "corpus_id": query.corpus_id,
                "graph_snapshot": query.graph_snapshot.model_dump(mode="json"),
                "access_policy_revision_id": query.policy_revision_id,
                "access_policy_sha256": query.policy_sha256,
                "namespace": query.namespace.model_dump(mode="json"),
                "space": executor.runtime_profile.space.model_dump(mode="json"),
                "runtime_bundle": executor.runtime_profile.runtime_bundle.model_dump(mode="json"),
                "resource_profile": executor.runtime_profile.resource_profile.model_dump(
                    mode="json"
                ),
                "source_plan": saved.member.model_dump(mode="json"),
                "source_plan_sha256": plan.plan_sha256,
                "native_execution_policy": owner.configuration.native_execution_policy.model_dump(
                    mode="json"
                ),
                "native_execution_policy_sha256": controls.policy.policy_sha256,
            }
            if refresh is not None:
                body |= {
                    "schema_version": "local-embedding-workflow-request/1.3",
                    "reconciliation_basis": refresh.model_dump(mode="json"),
                }
            request = parse_local_embedding_executable_request(
                body | {"request_sha256": content_sha256(body)}
            )
            actor_type, actor_id = local_embedding_request_actor(request)
            started = start_local_embedding_in_session(
                session,
                definition=definition,
                request=request,
                idempotency_key="local-embedding-reconcile:"
                + request.request_sha256.removeprefix("sha256:"),
                actor_type=actor_type,
                actor_id=actor_id,
                owner=owner,
                executor=executor,
            )
            if not isinstance(started, LocalEmbeddingWorkflowSubmitted):
                raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_SOURCE_MISMATCH")
            state = (
                ReconciliationState.TERMINAL_INCOMPLETE
                if started.workflow.state in {"COMPLETED", "FAILED", "CANCELLED"}
                or started.command.state in {"FAILED", "CANCELLED"}
                else ReconciliationState.QUEUED
                if started.workflow_created or started.command_created
                else ReconciliationState.REPLAYED
            )
            return replace(
                observed,
                state=state,
                workflow_id=started.workflow.workflow_id,
                command_id=started.command.command_id,
                workflow_state=started.workflow.state,
                command_state=started.command.state,
            )
