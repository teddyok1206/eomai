"""Explicit worker configuration resolution shared by runtime entry points."""

from __future__ import annotations

from dataclasses import dataclass

from eom_orchestrator.settings import Settings, WorkerConfigSource
from eom_orchestrator.worker_registry import WorkerRegistry, WorkerSlot


@dataclass(frozen=True)
class ResolvedWorkerConfiguration:
    source: WorkerConfigSource
    registry: WorkerRegistry
    live_worker: WorkerSlot


def resolve_worker_configuration(settings: Settings) -> ResolvedWorkerConfiguration:
    """Load the explicit config and resolve the deterministic live authoring worker."""
    registry = WorkerRegistry.load(settings.worker_config)
    live_worker = registry.select("authoring")
    return ResolvedWorkerConfiguration(
        source=settings.worker_config_source,
        registry=registry,
        live_worker=live_worker,
    )
