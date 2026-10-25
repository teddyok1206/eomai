"""One replaceable application adapter boundary; numerical CPU behavior remains fixed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from eom_catalog_contracts.embedding_reference_query import EmbeddingReferenceQueryResult
from eom_orchestrator.native_embedding_query_handoff import PreparedNativeQuery
from eom_orchestrator.native_embedding_query_systemd import FixedNativeQueryLauncher

from eom_workflow_runner.reference_query_owner_admission import CatalogReferenceQueryOwnerAdmission
from eom_workflow_runner.repository import CommandLeaseIdentity


@dataclass(frozen=True, slots=True)
class CpuReferenceQueryExecutionContext:
    owner: CatalogReferenceQueryOwnerAdmission
    command_lease: CommandLeaseIdentity


class CpuReferenceQueryExecution(Protocol):
    @property
    def launcher(self) -> FixedNativeQueryLauncher: ...

    def run(
        self, prepared: PreparedNativeQuery, *, source: CpuReferenceQueryExecutionContext
    ) -> EmbeddingReferenceQueryResult:
        """No SQL root survives this call; source is an actual current-owner fence, not a grant."""
        ...


class FixedCpuReferenceQueryExecution:
    def __init__(self, launcher: FixedNativeQueryLauncher) -> None:
        self.launcher = launcher

    def run(
        self, prepared: PreparedNativeQuery, *, source: CpuReferenceQueryExecutionContext
    ) -> EmbeddingReferenceQueryResult:
        return self.launcher.run(prepared)
