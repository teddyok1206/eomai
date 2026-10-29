"""Official missing-binding discovery into the existing atomic native START queue.

This application neither runs the model nor owns a new queue/target registry. The
installed service composition must supply actual current authority and an executor.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from eom_catalog_contracts.embedding_index_families import embedding_entry_source
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingIndexManifest,
    EmbeddingSourceBinding,
)
from eom_catalog_contracts.local_indexing_mixed_policy import (
    LocalIndexingMixedAccessPolicy,
    supported_local_indexing_authorization_audit_sha256,
)
from eom_catalog_contracts.mixed_embedding_index import (
    MixedEmbeddingIndexManifest,
    RegisteredReviewEmbeddingSourceBinding,
)
from eom_catalog_contracts.mixed_embedding_registry import MixedEmbeddingIndexNamespace
from eom_catalog_contracts.public_solution_embedding_index import (
    PublicSolutionEmbeddingIndex,
    PublicSolutionEmbeddingSourceBinding,
    PublicSolutionIndexNamespace,
)
from eom_catalog_contracts.public_solution_indexing_policy import PublicSolutionIndexingAccessPolicy
from eom_catalog_service.embedding_index_refresh_plan import (
    mixed_index_membership_refresh_reason,
    plan_index_membership_refresh,
    public_index_membership_refresh_reason,
)
from eom_catalog_service.embedding_registry_application import prepare_missing_embedding_bindings
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryLookup,
    ResolvedEmbeddingLookup,
    SelectedEmbeddingSources,
)
from eom_catalog_service.local_embedding_source_plan import build_local_embedding_source_plan
from eom_catalog_service.local_embedding_source_plan_v2 import build_local_embedding_source_plan_v2
from eom_catalog_service.local_embedding_source_plan_v3 import build_local_embedding_source_plan_v3
from eom_identifiers import content_sha256
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingRuntimeProfile
from eom_workflow.local_embedding_index_refresh import (
    IndexMembershipRefreshBasis,
)
from eom_workflow.local_embedding_request_v2 import (
    SupportedLocalEmbeddingRequest,
    parse_supported_local_embedding_request,
    supported_local_embedding_request_actor,
)
from eom_workflow.local_embedding_source_plan import LocalEmbeddingSourcePlan
from eom_workflow.local_embedding_source_plan_v2 import LocalEmbeddingSourcePlanV2
from eom_workflow.local_embedding_source_plan_v3 import LocalEmbeddingSourcePlanV3
from eom_workflow.local_embedding_workflow import (
    LOCAL_EMBEDDING_WORKFLOW_KEY,
    LOCAL_EMBEDDING_WORKFLOW_VERSION,
)
from eom_workflow.local_embedding_workflow_v2 import LOCAL_EMBEDDING_WORKFLOW_V2_VERSION
from sqlalchemy.orm import Session

from eom_workflow_runner.local_embedding_native_executor import CatalogNativeEmbeddingExecutor
from eom_workflow_runner.local_embedding_owner_admission import (
    CatalogLocalEmbeddingOwnerAdmission,
    ServiceReconciliationControls,
)
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
    PREPARED = "PREPARED"
    BATCH_COMPLETED = "BATCH_COMPLETED"
    GPU_DEFERRED = "GPU_DEFERRED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
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


@dataclass(frozen=True, slots=True)
class PreparedLocalEmbeddingReconciliation:
    """A plan pointer and observation, never runtime/source authority or a queue claim."""

    observed: LocalEmbeddingReconciliationResult
    request: SupportedLocalEmbeddingRequest | None = None


def local_embedding_reconciliation_key(request: SupportedLocalEmbeddingRequest) -> str:
    """Stable original submission identity, shared by discovery and interrupted replay."""
    checked = parse_supported_local_embedding_request(request)
    return "local-embedding-reconcile:" + checked.request_sha256.removeprefix("sha256:")


class LocalEmbeddingServicePreparation:
    """Source/coverage preparation before physical allocation, without a numerical executor."""

    def __init__(
        self,
        owner: CatalogLocalEmbeddingOwnerAdmission,
        publisher: ControlFileSetPublisher,
        runtime_profile: LocalEmbeddingRuntimeProfile,
        *,
        source_commit: str,
        maximum_targets: int = 64,
    ) -> None:
        if (
            type(owner) is not CatalogLocalEmbeddingOwnerAdmission
            or type(publisher) is not ControlFileSetPublisher
            or owner.catalog.engine is not publisher.engine
            or owner.settings.nas_artifact_root != publisher.settings.nas_artifact_root
            or type(runtime_profile) is not LocalEmbeddingRuntimeProfile
            or runtime_profile.space != owner.configuration.registry.space
            or type(maximum_targets) is not int
            or not 1 <= maximum_targets <= 1024
        ):
            raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_CONFIGURATION_INVALID")
        self.owner, self.publisher, self.runtime_profile = owner, publisher, runtime_profile
        self.maximum_targets = maximum_targets
        self.controls = LocalEmbeddingControlArtifactPublisher(
            publisher, source_commit=source_commit
        )

    def prepare_once(self) -> PreparedLocalEmbeddingReconciliation:
        owner, publisher, runtime_profile = self.owner, self.publisher, self.runtime_profile
        with publisher.sessions.begin() as session:
            query = owner.current_reconciliation_lookup(session)
            if query is None:
                return PreparedLocalEmbeddingReconciliation(
                    LocalEmbeddingReconciliationResult(ReconciliationState.NO_PUBLISHED_GRAPH, None)
                )
            controls = owner.resolve_reconciliation_controls(session, query, runtime_profile)
            mixed = isinstance(query.namespace, MixedEmbeddingIndexNamespace)
            public = isinstance(query.namespace, PublicSolutionIndexNamespace)
            if mixed != isinstance(
                controls.grant, LocalIndexingMixedAccessPolicy
            ) or public != isinstance(controls.grant, PublicSolutionIndexingAccessPolicy):
                raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_SOURCE_MISMATCH")
            prepared = prepare_missing_embedding_bindings(
                session, controls.caller, query, owner.catalog
            )
            missing, resolved = prepared.observation, prepared.resolved
            source_ids = {source.item_revision_id for source in resolved.sources}
            profile_ids = {
                embedding_entry_source(entry).item_revision_id for entry in resolved.entries
            }
            missing_reports = tuple(sorted(source_ids - profile_ids))
            unavailable = len(profile_ids) - missing.available_view_count
            reusable = {row.encoding.encoding_sha256 for row in missing.reusable_rows}
            uncached_targets = {
                row.item_revision_id
                for row in missing.missing
                if row.encoding_sha256 not in reusable
            }
            # A new Graph can invalidate every binding, not its immutable vectors.
            # Finish new numerical work before repeatedly rebinding a cached prefix.
            target_ids = uncached_targets or {row.item_revision_id for row in missing.missing}
            targets = tuple(sorted(target_ids))[: self.maximum_targets]
            if (
                missing.eligible_source_count != len(source_ids)
                or not profile_ids.issubset(source_ids)
                or unavailable < 0
                or not set(targets).issubset(profile_ids)
            ):
                raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_SOURCE_MISMATCH")
            refresh: IndexMembershipRefreshBasis | None = None
            refresh_reason: str | None = None
            if prepared.bindings:
                previous = owner.catalog.resolve_indexing_namespace_predecessor(
                    session, controls.caller, query
                )
                if public:
                    public_previous = None
                    if previous is not None:
                        pointer, prior_public = previous
                        if not isinstance(prior_public, PublicSolutionEmbeddingIndex):
                            raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_SOURCE_MISMATCH")
                        public_previous = pointer, prior_public
                    public_bindings = tuple(
                        binding
                        for binding in prepared.bindings
                        if isinstance(binding, PublicSolutionEmbeddingSourceBinding)
                    )
                    if len(public_bindings) != len(prepared.bindings):
                        raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_SOURCE_MISMATCH")
                    refresh_reason = public_index_membership_refresh_reason(
                        eligible_sources=resolved.sources,
                        available_bindings=public_bindings,
                        previous=public_previous,
                    )
                    if refresh_reason is not None:
                        # One exact available witness keeps the native batch small;
                        # completion independently captures and registers the full head.
                        targets = (
                            min(binding.source.item_revision_id for binding in public_bindings),
                        )
                elif mixed:
                    mixed_bindings = tuple(
                        binding
                        for binding in prepared.bindings
                        if isinstance(
                            binding,
                            (EmbeddingSourceBinding, RegisteredReviewEmbeddingSourceBinding),
                        )
                    )
                    if len(mixed_bindings) != len(prepared.bindings):
                        raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_SOURCE_MISMATCH")
                    mixed_previous = None
                    if previous is not None:
                        pointer, prior_index = previous
                        if not isinstance(prior_index, MixedEmbeddingIndexManifest):
                            raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_SOURCE_MISMATCH")
                        mixed_previous = pointer, prior_index
                    refresh_reason = mixed_index_membership_refresh_reason(
                        eligible_sources=resolved.sources,
                        available_bindings=mixed_bindings,
                        previous=mixed_previous,
                    )
                    if refresh_reason is not None:
                        # Metadata-only work reuses the entire currently available
                        # subset (<=1024), not newly missing rows. maximum_targets
                        # remains the bound for new numerical work, not this read.
                        targets = tuple(
                            sorted(b.source.item_revision_id for b in prepared.bindings)
                        )
                else:
                    legacy_bindings = tuple(
                        b for b in prepared.bindings if isinstance(b, EmbeddingSourceBinding)
                    )
                    if len(legacy_bindings) != len(prepared.bindings):
                        raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_SOURCE_MISMATCH")
                    legacy_previous = None
                    if previous is not None:
                        legacy_pointer, legacy_index = previous
                        if not isinstance(legacy_index, EmbeddingIndexManifest):
                            raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_SOURCE_MISMATCH")
                        legacy_previous = legacy_pointer, legacy_index
                    refresh = plan_index_membership_refresh(
                        eligible_sources=resolved.sources,
                        available_bindings=legacy_bindings,
                        previous=legacy_previous,
                    )
                    refresh_reason = None if refresh is None else refresh.reason
                if refresh is not None:
                    # One already available source witnesses this metadata-only
                    # request, even while more sources need vectors. Publish
                    # usable membership before the next ordinary seed/delta.
                    targets = (min(b.source.item_revision_id for b in prepared.bindings),)
            if refresh_reason is None and missing.missing and not uncached_targets:
                # A new Graph can require bindings for already registered vectors.
                # Keep real plan demands; the existing membership-only owner must
                # recapture those rows before it can publish without computation.
                refresh_reason = "REUSABLE_ENCODINGS_NOT_BOUND"
            observed = LocalEmbeddingReconciliationResult(
                state=ReconciliationState.UP_TO_DATE,
                graph_snapshot_revision_id=query.graph_snapshot.graph_snapshot_revision_id,
                eligible_source_count=missing.eligible_source_count,
                missing_report_revision_ids=missing_reports,
                unavailable_view_count=unavailable,
                missing_binding_count=len(missing.missing),
                selected_target_count=len(targets),
                reusable_encoding_count=len(missing.reusable_rows),
                index_refresh_reason=refresh_reason,
            )
            # Fresh current checks also apply to no-op/report-wait observations.
            late = owner.resolve_reconciliation_controls(session, query, runtime_profile)
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
                return PreparedLocalEmbeddingReconciliation(replace(observed, state=state))
            request = self._prepare_request(session, controls, query, resolved, targets, refresh)
            return PreparedLocalEmbeddingReconciliation(
                replace(observed, state=ReconciliationState.PREPARED), request
            )

    def prepare_matching(
        self,
        counterpart: LocalEmbeddingServicePreparation,
        request: SupportedLocalEmbeddingRequest,
        *,
        maximum_sources: int = 1024,
    ) -> SupportedLocalEmbeddingRequest:
        """Rebuild this device's plan for the original pinned selection, not its missing queue.

        Both actual owners reauthorize in this root. No request DTO grants source
        access and neither a current head nor a newly missing target replaces it.
        """
        if (
            type(counterpart) is not LocalEmbeddingServicePreparation
            or counterpart.publisher.engine is not self.publisher.engine
            or counterpart.owner.settings.nas_artifact_root != self.owner.settings.nas_artifact_root
            or type(maximum_sources) is not int
            or not 1 <= maximum_sources <= 1024
        ):
            raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_SOURCE_MISMATCH")
        request = parse_supported_local_embedding_request(request)
        registry = self.owner.configuration.registry
        if (
            request.corpus_id != registry.corpus_id
            or request.namespace.view != registry.namespace.view
            or request.namespace.projection_version != registry.namespace.projection_version
            or request.namespace.population_scope != registry.namespace.population_scope
            or request.namespace.storage_partition != registry.namespace.storage_partition
        ):
            raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_SOURCE_MISMATCH")
        query = EmbeddingRegistryLookup(
            request.corpus_id,
            registry.namespace,
            request.graph_snapshot,
            request.access_policy_revision_id,
            request.access_policy_sha256,
            maximum_sources,
        )
        with self.publisher.sessions.begin() as session:
            original = counterpart.owner.resolve_sources(session, request)
            controls = self.owner.resolve_reconciliation_controls(
                session, query, self.runtime_profile
            )
            if controls.caller != counterpart.owner.registry_caller(request):
                raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_SOURCE_MISMATCH")
            targets = tuple(sorted(s.item_revision_id for s in original.admission.plan.sources))
            selected = self.owner.catalog.resolve_selected_sources(
                session, controls.caller, SelectedEmbeddingSources(query, targets)
            )
            if selected.recipe != original.admission.plan.recipe or {
                s.item_revision_id: s for s in selected.sources
            } != {s.item_revision_id: s for s in original.admission.plan.sources}:
                raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_SOURCE_MISMATCH")
            matched = self._prepare_request(session, controls, query, selected, targets, None)
            counterpart.owner.fence_current_actor(session, request)
            return matched

    def _prepare_request(
        self,
        session: Session,
        controls: ServiceReconciliationControls,
        query: EmbeddingRegistryLookup,
        resolved: ResolvedEmbeddingLookup,
        targets: tuple[str, ...],
        refresh: IndexMembershipRefreshBasis | None,
    ) -> SupportedLocalEmbeddingRequest:
        owner, runtime_profile = self.owner, self.runtime_profile
        mixed = isinstance(query.namespace, MixedEmbeddingIndexNamespace)
        public = isinstance(query.namespace, PublicSolutionIndexNamespace)
        definition_version = (
            LOCAL_EMBEDDING_WORKFLOW_V2_VERSION
            if mixed or public
            else LOCAL_EMBEDDING_WORKFLOW_VERSION
        )
        definition = admitted_workflow_definition(
            session,
            definition_key=LOCAL_EMBEDDING_WORKFLOW_KEY,
            definition_version=definition_version,
        )
        if definition is None or definition.definition_hash != (
            controls.policy.workflow_definition_sha256
        ):
            raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_DEFINITION_UNAVAILABLE")
        plan: LocalEmbeddingSourcePlan | LocalEmbeddingSourcePlanV2 | LocalEmbeddingSourcePlanV3
        if public:
            plan = build_local_embedding_source_plan_v3(
                query, resolved, target_revision_ids=targets
            )
        elif mixed:
            plan = build_local_embedding_source_plan_v2(
                query,
                resolved,
                target_revision_ids=targets,
                base_analysis_run_ids=dict(resolved.base_analysis_run_ids),
            )
        else:
            plan = build_local_embedding_source_plan(query, resolved, target_revision_ids=targets)
        plan_key = content_sha256(
            {"plan": plan.plan_sha256, "source_commit": self.controls.source_commit}
        )
        # Only Orchestrator publishes; retained source/service locks protect
        # this preparation root. No model/claim happens while locks are held.
        plan_publication_key = "local-embedding-plan:" + plan_key.removeprefix("sha256:")
        if isinstance(plan, LocalEmbeddingSourcePlanV3):
            saved = self.controls.publish_observed_source_plan_v3(
                plan, idempotency_key=plan_publication_key
            )
        elif isinstance(plan, LocalEmbeddingSourcePlanV2):
            saved = self.controls.publish_observed_source_plan_v2(
                plan, idempotency_key=plan_publication_key
            )
        else:
            saved = self.controls.publish_observed_source_plan(
                plan, idempotency_key=plan_publication_key
            )
        authorization_audit = supported_local_indexing_authorization_audit_sha256(controls.grant)
        body = {
            "schema_version": "local-embedding-workflow-request/3.0"
            if public
            else "local-embedding-workflow-request/2.0"
            if mixed
            else "local-embedding-workflow-request/1.2",
            "request_name": "LOCAL_EMBEDDING_WORKFLOW_REQUEST",
            "purpose": "LOCAL_EMBEDDING",
            "workflow_definition_key": LOCAL_EMBEDDING_WORKFLOW_KEY,
            "workflow_definition_version": definition_version,
            "workflow_definition_sha256": definition.definition_hash,
            "actor_context": {
                "kind": "LOCAL_INDEXING_SERVICE",
                **controls.caller.service.model_dump(mode="json"),
                "service_policy_revision_id": controls.grant.access_policy_revision_id,
                "service_policy_sha256": controls.grant.content_sha256,
                "authorization_audit_sha256": authorization_audit,
            },
            "corpus_id": query.corpus_id,
            "graph_snapshot": query.graph_snapshot.model_dump(mode="json"),
            "access_policy_revision_id": query.policy_revision_id,
            "access_policy_sha256": query.policy_sha256,
            "namespace": query.namespace.model_dump(mode="json"),
            "space": runtime_profile.space.model_dump(mode="json"),
            "runtime_bundle": runtime_profile.runtime_bundle.model_dump(mode="json"),
            "resource_profile": runtime_profile.resource_profile.model_dump(mode="json"),
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
        request = parse_supported_local_embedding_request(
            body | {"request_sha256": content_sha256(body)}
        )
        # Artifact publication can consume time. Retain the source locks and
        # repeat current authority, not immutable plan/material hashing.
        owner.catalog.authorize_scope(session, controls.caller, query)
        owner.fence_current_actor(session, request)
        return request


class LocalEmbeddingServiceReconciliation:
    """Existing prepare/atomic START facade; scheduling stays with the installed owner."""

    def __init__(self, executor: CatalogNativeEmbeddingExecutor, *, maximum_targets: int = 64):
        if type(executor) is not CatalogNativeEmbeddingExecutor:
            raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_CONFIGURATION_INVALID")
        self.executor, self.owner = executor, executor.owner
        self.preparation = LocalEmbeddingServicePreparation(
            executor.owner,
            executor.publisher,
            executor.runtime_profile,
            source_commit=executor.source_commit,
            maximum_targets=maximum_targets,
        )
        self.controls = self.preparation.controls

    @property
    def maximum_targets(self) -> int:
        return self.preparation.maximum_targets

    @maximum_targets.setter
    def maximum_targets(self, value: int) -> None:
        if type(value) is not int or not 1 <= value <= 1024:
            raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_CONFIGURATION_INVALID")
        self.preparation.maximum_targets = value

    def run_once(self) -> LocalEmbeddingReconciliationResult:
        return self.submit_prepared(self.preparation.prepare_once())

    def submit_prepared(
        self, prepared: PreparedLocalEmbeddingReconciliation
    ) -> LocalEmbeddingReconciliationResult:
        """Official START reauthorizes a prepared pointer; it carries no reusable grant."""
        if type(prepared) is not PreparedLocalEmbeddingReconciliation:
            raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_CONFIGURATION_INVALID")
        observed, request = prepared.observed, prepared.request
        if request is None:
            return observed
        owner, executor = self.owner, self.executor
        with executor.publisher.sessions.begin() as session:
            # Preparation carries no authority through this gap. Official START
            # reacquires the actual current service/source/plan admission here.
            definition = admitted_workflow_definition(
                session,
                definition_key=request.workflow_definition_key,
                definition_version=request.workflow_definition_version,
            )
            if (
                definition is None
                or definition.definition_hash != request.workflow_definition_sha256
            ):
                raise ValueError("LOCAL_EMBEDDING_RECONCILIATION_DEFINITION_UNAVAILABLE")
            actor_type, actor_id = supported_local_embedding_request_actor(request)
            started = start_local_embedding_in_session(
                session,
                definition=definition,
                request=request,
                idempotency_key=local_embedding_reconciliation_key(request),
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
