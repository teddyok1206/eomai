"""Narrow role-preparation port; no worker authority or alternate execution path."""

from __future__ import annotations

from typing import Protocol

from eom_catalog_contracts.similarity_context import SimilarityContext, SimilarityContextRequest
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
from eom_orchestrator.similarity_materialization import SimilarityMaterializationContext
from eom_workflow.models import WorkerRequest
from sqlalchemy.orm import Session

from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord


class SimilaritySessionContextReader(Protocol):
    def compose_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: SimilarityContextRequest,
    ) -> SimilarityContext:
        """Retain the caller root/fence for first, member and late reads without inner roots."""
        ...


class SimilarityRoleContextProvider(Protocol):
    def prepare(
        self,
        session: Session,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: WorkerRequest,
    ) -> SimilarityMaterializationContext | None:
        """Caller owns the command-fenced root; actual source authority is rechecked later."""
        ...
