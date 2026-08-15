from pathlib import Path

import pytest
from eom_orchestrator.errors import PlatformError
from eom_orchestrator.worker_registry import WorkerRegistry


def test_example_registry_selects_authoring_slot() -> None:
    registry = WorkerRegistry.load(Path("config/worker-slots.example.yaml"))
    slot = registry.select("authoring")
    assert slot.slot_id == "01"
    assert slot.linux_user == "eom-cdx-01"
    assert registry.global_codex_concurrency == 3


def test_registry_rejects_missing_role() -> None:
    registry = WorkerRegistry.load(Path("config/worker-slots.example.yaml"))
    with pytest.raises(PlatformError, match="no enabled worker"):
        registry.select("missing")
