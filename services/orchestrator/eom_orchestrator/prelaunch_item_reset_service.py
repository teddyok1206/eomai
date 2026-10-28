"""One exact, owner-authorized prelaunch reset coordinated through component ports.

Ordinary Item retirement is not this use case. No module here imports Catalog,
Workflow or HWPX implementation packages; the local composition root supplies them.
"""

from __future__ import annotations

from contextlib import AbstractContextManager, ExitStack
from datetime import UTC, datetime
from typing import Protocol

import psycopg
from eom_protocol.prelaunch_item_reset import (
    ArtifactResetObservation,
    BuildResetObservation,
    CatalogResetObservation,
    PrelaunchItemResetPlan,
    PrelaunchItemResetReceipt,
    ResetBackupPin,
    WorkflowResetObservation,
    reset_digest,
)
from psycopg.pq import TransactionStatus

from eom_orchestrator.metadata_reset_transaction import MetadataResetTransaction


class ResetHostFence(Protocol):
    def verify(self) -> None: ...
    def verify_backup(self, database: str, backup: ResetBackupPin) -> None: ...


class CatalogResetPort(Protocol):
    def observe_prelaunch_catalog(
        self, cursor: MetadataResetTransaction
    ) -> CatalogResetObservation: ...
    def protected_catalog_digest(
        self, cursor: MetadataResetTransaction, item_ids: tuple[str, ...]
    ) -> str: ...
    def prelaunch_mutations(
        self, cursor: MetadataResetTransaction
    ) -> AbstractContextManager[None]: ...
    def prelaunch_lookup_indexes(
        self, cursor: MetadataResetTransaction
    ) -> AbstractContextManager[None]: ...
    def delete_prelaunch_retrievals(self, cursor: MetadataResetTransaction) -> None: ...
    def delete_prelaunch_indexes(self, cursor: MetadataResetTransaction) -> None: ...
    def delete_prelaunch_graphs(self, cursor: MetadataResetTransaction) -> None: ...
    def delete_prelaunch_items(self, cursor: MetadataResetTransaction) -> None: ...
    def delete_prelaunch_document_reviews(
        self, cursor: MetadataResetTransaction, workflow_ids: tuple[str, ...]
    ) -> None: ...
    def verify_retained_catalog(self, cursor: MetadataResetTransaction) -> None: ...
    def deleted_prelaunch_targets_absent(
        self,
        cursor: MetadataResetTransaction,
        item_ids: tuple[str, ...],
        revisions: tuple[str, ...],
    ) -> bool: ...


class WorkflowResetPort(Protocol):
    def observe_prelaunch_workflows(
        self, cursor: MetadataResetTransaction, item_ids: tuple[str, ...]
    ) -> WorkflowResetObservation: ...
    def prelaunch_mutations(
        self, cursor: MetadataResetTransaction
    ) -> AbstractContextManager[None]: ...
    def delete_prelaunch_graph_plans(self, cursor: MetadataResetTransaction) -> None: ...
    def delete_prelaunch_workflows(
        self, cursor: MetadataResetTransaction, workflow_ids: tuple[str, ...]
    ) -> None: ...
    def verify_prelaunch_workflow_absence(
        self, cursor: MetadataResetTransaction, ids: tuple[str, ...]
    ) -> None: ...


class ArtifactResetPort(Protocol):
    def observe_prelaunch_artifacts(
        self, cursor: MetadataResetTransaction, workflows: tuple[str, ...], items: tuple[str, ...]
    ) -> ArtifactResetObservation: ...
    def protected_artifact_digest(
        self, cursor: MetadataResetTransaction, item_ids: tuple[str, ...]
    ) -> str: ...
    def prelaunch_mutations(
        self, cursor: MetadataResetTransaction
    ) -> AbstractContextManager[None]: ...
    def delete_prelaunch_analyses(
        self, cursor: MetadataResetTransaction, item_ids: tuple[str, ...]
    ) -> None: ...
    def delete_prelaunch_leases(
        self, cursor: MetadataResetTransaction, workflow_ids: tuple[str, ...]
    ) -> None: ...
    def delete_exclusive_reset_jobs(
        self, cursor: MetadataResetTransaction, job_ids: tuple[str, ...]
    ) -> None: ...
    def reset_remaining_jobs(
        self, cursor: MetadataResetTransaction, ids: tuple[str, ...]
    ) -> int: ...


class HwpxResetPort(Protocol):
    def observe_prelaunch_builds(
        self, cursor: MetadataResetTransaction, item_ids: tuple[str, ...]
    ) -> BuildResetObservation: ...
    def protected_build_digest(
        self, cursor: MetadataResetTransaction, item_ids: tuple[str, ...]
    ) -> str: ...
    def prelaunch_mutations(
        self, cursor: MetadataResetTransaction
    ) -> AbstractContextManager[None]: ...
    def delete_prelaunch_builds(
        self, cursor: MetadataResetTransaction, item_ids: tuple[str, ...]
    ) -> None: ...


class PrelaunchItemResetService:
    def __init__(
        self,
        *,
        catalog: CatalogResetPort,
        workflows: WorkflowResetPort,
        artifacts: ArtifactResetPort,
        hwpx: HwpxResetPort,
        host: ResetHostFence,
    ) -> None:
        self.catalog, self.workflows, self.artifacts, self.hwpx, self.host = (
            catalog,
            workflows,
            artifacts,
            hwpx,
            host,
        )

    def _observe(
        self,
        cursor: MetadataResetTransaction,
        database: str,
        backup: ResetBackupPin,
        created_at: str,
    ) -> PrelaunchItemResetPlan:
        catalog = self.catalog.observe_prelaunch_catalog(cursor)
        workflows = self.workflows.observe_prelaunch_workflows(cursor, catalog.item_ids)
        artifacts = self.artifacts.observe_prelaunch_artifacts(
            cursor, workflows.workflow_ids, catalog.item_ids
        )
        builds = self.hwpx.observe_prelaunch_builds(cursor, catalog.item_ids)
        body = {
            "schema_version": "prelaunch-item-reset-plan/1.0",
            "scope": "AI_PRELAUNCH_20261028",
            "database": database,
            "item_ids": catalog.item_ids,
            "item_revision_ids": catalog.item_revision_ids,
            "workflow_ids": workflows.workflow_ids,
            "job_ids": artifacts.job_ids,
            "graph_pins": [x.model_dump(mode="json") for x in catalog.graph_pins],
            "baseline_sha256": reset_digest(
                (
                    catalog.baseline_sha256,
                    workflows.baseline_sha256,
                    artifacts.baseline_sha256,
                    builds.baseline_sha256,
                )
            ),
            "protected_sha256": reset_digest(
                (catalog.protected_sha256, artifacts.protected_sha256, builds.protected_sha256)
            ),
            "backup": backup.model_dump(mode="json"),
            "created_at_utc": created_at,
        }
        return PrelaunchItemResetPlan.model_validate(body | {"plan_sha256": reset_digest(body)})

    def prepare(
        self, connection: psycopg.Connection[tuple[object, ...]], backup: ResetBackupPin
    ) -> PrelaunchItemResetPlan:
        if connection.info.transaction_status != TransactionStatus.IDLE:
            raise ValueError("ITEM_RESET_ROOT_TRANSACTION_REQUIRED")
        self.host.verify()
        database = connection.info.dbname
        self.host.verify_backup(database, backup)
        created_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        with connection.transaction(), connection.cursor() as raw:
            raw.execute("SET LOCAL lock_timeout='5s'")
            cursor = MetadataResetTransaction(raw)
            cursor.freeze_writes()
            plan = self._observe(cursor, database, backup, created_at)
            self.host.verify()
            return plan

    def apply(
        self, connection: psycopg.Connection[tuple[object, ...]], plan: PrelaunchItemResetPlan
    ) -> PrelaunchItemResetReceipt:
        if connection.info.transaction_status != TransactionStatus.IDLE:
            raise ValueError("ITEM_RESET_ROOT_TRANSACTION_REQUIRED")
        plan = PrelaunchItemResetPlan.model_validate(plan.model_dump(mode="json"))
        if connection.info.dbname != plan.database:
            raise ValueError("ITEM_RESET_DATABASE_MISMATCH")
        self.host.verify()
        self.host.verify_backup(plan.database, plan.backup)
        with connection.transaction(), connection.cursor() as raw:
            raw.execute("SET LOCAL lock_timeout='5s'")
            raw.execute("SET LOCAL statement_timeout='240s'")
            cursor = MetadataResetTransaction(raw)
            cursor.freeze_writes()
            replay = self.catalog.deleted_prelaunch_targets_absent(
                cursor, plan.item_ids, plan.item_revision_ids
            )
            if not replay:
                if self._observe(cursor, plan.database, plan.backup, plan.created_at_utc) != plan:
                    raise ValueError("ITEM_RESET_PLAN_DRIFT")
                with ExitStack() as stack:
                    for owner in (self.catalog, self.workflows, self.hwpx, self.artifacts):
                        stack.enter_context(owner.prelaunch_mutations(cursor))
                    stack.enter_context(self.catalog.prelaunch_lookup_indexes(cursor))
                    self.catalog.delete_prelaunch_retrievals(cursor)
                    self.catalog.delete_prelaunch_indexes(cursor)
                    self.workflows.delete_prelaunch_graph_plans(cursor)
                    self.catalog.delete_prelaunch_graphs(cursor)
                    self.hwpx.delete_prelaunch_builds(cursor, plan.item_ids)
                    self.artifacts.delete_prelaunch_analyses(cursor, plan.item_ids)
                    self.catalog.delete_prelaunch_items(cursor)
                    self.catalog.delete_prelaunch_document_reviews(cursor, plan.workflow_ids)
                    self.artifacts.delete_prelaunch_leases(cursor, plan.workflow_ids)
                    self.workflows.delete_prelaunch_workflows(cursor, plan.workflow_ids)
                    self.artifacts.delete_exclusive_reset_jobs(cursor, plan.job_ids)
                    self._verify(cursor, plan)
            else:
                self._verify(cursor, plan)
            self.host.verify()
            remaining = self.artifacts.reset_remaining_jobs(cursor, plan.job_ids)
            return PrelaunchItemResetReceipt.model_validate(
                {
                    "schema_version": "prelaunch-item-reset-receipt/1.0",
                    "plan_sha256": plan.plan_sha256,
                    "database": plan.database,
                    "deleted_items": len(plan.item_ids),
                    "deleted_item_revisions": len(plan.item_revision_ids),
                    "deleted_workflows": len(plan.workflow_ids),
                    "candidate_jobs": len(plan.job_ids),
                    "shared_jobs_preserved": remaining,
                    "exclusive_jobs_deleted": len(plan.job_ids) - remaining,
                    "protected_sha256": plan.protected_sha256,
                    "nas_action": "PRESERVED",
                    "outcome": "COMPLETED",
                }
            )

    def _verify(self, cursor: MetadataResetTransaction, plan: PrelaunchItemResetPlan) -> None:
        self.catalog.verify_retained_catalog(cursor)
        self.workflows.verify_prelaunch_workflow_absence(cursor, plan.workflow_ids)
        protected = reset_digest(
            (
                self.catalog.protected_catalog_digest(cursor, plan.item_ids),
                self.artifacts.protected_artifact_digest(cursor, plan.item_ids),
                self.hwpx.protected_build_digest(cursor, plan.item_ids),
            )
        )
        if protected != plan.protected_sha256:
            raise ValueError("ITEM_RESET_PROTECTED_DATA_CHANGED")
