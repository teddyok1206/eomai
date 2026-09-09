from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import LegacyLearnedItemPointer
from eom_catalog_service import legacy_item_learning_service as learning_service
from eom_catalog_service.legacy_item_learning_service import (
    LegacyItemLearningCoordinator,
    LegacyItemLearningError,
    LegacyItemLearningPresetPin,
)
from eom_catalog_service.legacy_item_promotion_service import LegacyItemPromotion
from eom_orchestrator.control_service import compute_control_document_hash


class _PinSession:
    def __init__(self, rows: Sequence[SimpleNamespace | None]) -> None:
        self._rows = iter(rows)
        self.executed: list[object] = []
        self.scalar_statements: list[object] = []

    def execute(self, statement: object) -> None:
        self.executed.append(statement)

    def scalar(self, statement: object) -> SimpleNamespace | None:
        self.scalar_statements.append(statement)
        return next(self._rows)


class _PinSessions:
    def __init__(self, rows: Sequence[SimpleNamespace | None]) -> None:
        self._rows = rows
        self.session: _PinSession | None = None

    @contextmanager
    def begin(self) -> Iterator[_PinSession]:
        self.session = _PinSession(self._rows)
        yield self.session


def _promotion() -> LegacyItemPromotion:
    return LegacyItemPromotion(
        source=LegacyLearnedItemPointer.model_validate(
            {
                "item_id": "item_" + "1" * 32,
                "item_revision_id": "itemrev_" + "2" * 32,
                "item_manifest_sha256": "sha256:" + "3" * 64,
                "item_content": {
                    "artifact_id": "artifact_" + "4" * 32,
                    "artifact_revision_id": "rev_" + "5" * 32,
                    "member_path": "assessment-item-content.json",
                    "schema_ref": "eom://schemas/item-registry/assessment-item-content-v1",
                    "media_type": "application/json",
                    "sha256": "sha256:" + "6" * 64,
                },
                "extraction_acceptance_id": "itemacceptance_" + "7" * 32,
                "extraction_acceptance_sha256": "sha256:" + "8" * 64,
                "item_origin_profile_id": "originprofile_" + "9" * 32,
                "item_origin_profile_sha256": "sha256:" + "a" * 64,
                "lifecycle_state": "APPROVED",
            }
        ),
        item_created=True,
        origin_created=True,
    )


def _pin() -> LegacyItemLearningPresetPin:
    return LegacyItemLearningPresetPin(
        preset_id="execpreset_" + "1" * 32,
        preset_revision_id="execpresetrev_" + "2" * 32,
        preset_content_sha256="sha256:" + "3" * 64,
        capacity_policy_id="capacity_" + "4" * 32,
        capacity_policy_revision_id="capacityrev_" + "5" * 32,
        capacity_policy_content_sha256="sha256:" + "6" * 64,
        capacity_current_revision_id="capacityrev_" + "7" * 32,
        capacity_current_content_sha256="sha256:" + "8" * 64,
    )


def _pin_rows(pin: LegacyItemLearningPresetPin) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            preset_key="knowledge-analysis",
            preset_id=pin.preset_id,
            state="ACTIVE",
            current_revision_id=pin.preset_revision_id,
        ),
        SimpleNamespace(
            preset_revision_id=pin.preset_revision_id,
            preset_id=pin.preset_id,
            schema_version="execution-preset-revision/1.0",
            revision_number=1,
            state="RELEASED",
            display_name="Knowledge analysis",
            description="Pinned knowledge-analysis execution policy.",
            content_sha256=pin.preset_content_sha256,
            capacity_policy_revision_id=pin.capacity_policy_revision_id,
            general_knowledge_policy="DENY",
            compatible_workflow_protocols=["workflow-role/1.3.0"],
            canonical_document={
                "kind": "preset",
                "content_sha256": pin.preset_content_sha256,
            },
        ),
        SimpleNamespace(
            capacity_policy_revision_id=pin.capacity_policy_revision_id,
            capacity_policy_id=pin.capacity_policy_id,
            schema_version="worker-capacity-policy/1.1",
            revision_number=2,
            state="RELEASED",
            max_configured_slots=6,
            max_active_codex=3,
            max_active_per_slot=1,
            max_active_gpu=1,
            max_active_knowledge_analysis=2,
            content_sha256=pin.capacity_policy_content_sha256,
            canonical_document={
                "kind": "capacity",
                "content_sha256": pin.capacity_policy_content_sha256,
            },
        ),
        SimpleNamespace(
            policy_key="fixed-host",
            capacity_policy_id=pin.capacity_policy_id,
            state="ACTIVE",
            current_revision_id=pin.capacity_current_revision_id,
        ),
        SimpleNamespace(
            capacity_policy_revision_id=pin.capacity_current_revision_id,
            capacity_policy_id=pin.capacity_policy_id,
            schema_version="worker-capacity-policy/1.2",
            revision_number=3,
            state="RELEASED",
            max_configured_slots=6,
            max_active_codex=3,
            max_active_per_slot=1,
            max_active_gpu=1,
            max_active_knowledge_analysis=2,
            content_sha256=pin.capacity_current_content_sha256,
            canonical_document={
                "kind": "current-capacity",
                "content_sha256": pin.capacity_current_content_sha256,
            },
        ),
    ]


def _stub_pin_documents(
    monkeypatch: pytest.MonkeyPatch,
    pin: LegacyItemLearningPresetPin,
) -> tuple[Mock, Mock, Mock]:
    service_module = cast(Any, learning_service)
    preset_validator = Mock(
        return_value=SimpleNamespace(
            schema_version="execution-preset-revision/1.0",
            preset_id=pin.preset_id,
            preset_revision_id=pin.preset_revision_id,
            revision_number=1,
            capacity_policy_revision_id=pin.capacity_policy_revision_id,
            display_name="Knowledge analysis",
            description="Pinned knowledge-analysis execution policy.",
            general_knowledge_policy="DENY",
            compatible_workflow_protocols=("workflow-role/1.3.0",),
            content_sha256=pin.preset_content_sha256,
            state="RELEASED",
            model_dump=Mock(
                return_value={
                    "kind": "preset",
                    "content_sha256": pin.preset_content_sha256,
                }
            ),
        )
    )
    capacity_validator = Mock(
        return_value=SimpleNamespace(
            schema_version="worker-capacity-policy/1.1",
            capacity_policy_id=pin.capacity_policy_id,
            capacity_policy_revision_id=pin.capacity_policy_revision_id,
            revision_number=2,
            max_configured_slots=6,
            max_active_codex=3,
            max_active_per_slot=1,
            max_active_gpu=1,
            max_active_knowledge_analysis=2,
            content_sha256=pin.capacity_policy_content_sha256,
            state="RELEASED",
            model_dump=Mock(
                return_value={
                    "kind": "capacity",
                    "content_sha256": pin.capacity_policy_content_sha256,
                }
            ),
        )
    )
    current_capacity_validator = Mock(
        return_value=SimpleNamespace(
            schema_version="worker-capacity-policy/1.2",
            capacity_policy_id=pin.capacity_policy_id,
            capacity_policy_revision_id=pin.capacity_current_revision_id,
            revision_number=3,
            max_configured_slots=6,
            max_active_codex=3,
            max_active_per_slot=1,
            max_active_gpu=1,
            max_active_knowledge_analysis=2,
            content_sha256=pin.capacity_current_content_sha256,
            state="RELEASED",
            model_dump=Mock(
                return_value={
                    "kind": "current-capacity",
                    "content_sha256": pin.capacity_current_content_sha256,
                }
            ),
        )
    )
    monkeypatch.setattr(
        service_module.ExecutionPresetRevision,
        "model_validate",
        preset_validator,
    )
    monkeypatch.setattr(
        service_module.WorkerCapacityPolicyV2,
        "model_validate",
        capacity_validator,
    )
    monkeypatch.setattr(
        service_module.WorkerCapacityPolicyV3,
        "model_validate",
        current_capacity_validator,
    )
    monkeypatch.setattr(
        service_module,
        "compute_control_document_hash",
        lambda document, hash_field: document[hash_field],
    )
    return preset_validator, capacity_validator, current_capacity_validator


def _artifact(seed: str, logical_name: str) -> dict[str, object]:
    return {
        "artifact_id": "artifact_" + seed * 32,
        "artifact_revision_id": "rev_" + seed * 32,
        "sha256": "sha256:" + seed * 64,
        "schema_ref": "eom://schemas/workflow/bundle-manifest/1.0",
        "media_type": "application/json",
        "logical_name": logical_name,
    }


def _instruction_pointer() -> dict[str, object]:
    return {
        "bundle_id": "instrbundle_" + "a" * 32,
        "bundle_revision_id": "instrrev_" + "a" * 32,
        "manifest_artifact": _artifact("a", "manifest.json"),
        "manifest_sha256": "sha256:" + "a" * 64,
    }


def _capacity_pools(*, isolated_extraction: bool) -> list[dict[str, object]]:
    pools: list[dict[str, object]] = [
        {
            "pool_key": "authoring",
            "roles": ["authoring"],
            "slot_keys": ["slot01"],
            "max_active": 1,
        },
        {
            "pool_key": "review",
            "roles": ["review"],
            "slot_keys": ["slot02"],
            "max_active": 1,
        },
        {
            "pool_key": "image",
            "roles": ["image"],
            "slot_keys": ["slot03"],
            "max_active": 1,
        },
        {
            "pool_key": "item-management",
            "roles": ["item_management"],
            "slot_keys": ["slot04"],
            "max_active": 1,
        },
    ]
    if isolated_extraction:
        pools.extend(
            (
                {
                    "pool_key": "support",
                    "roles": ["support"],
                    "slot_keys": ["slot05"],
                    "max_active": 1,
                },
                {
                    "pool_key": "legacy-extraction",
                    "roles": ["support"],
                    "slot_keys": ["slot06"],
                    "max_active": 1,
                },
            )
        )
    else:
        pools.append(
            {
                "pool_key": "support",
                "roles": ["support"],
                "slot_keys": ["slot05", "slot06"],
                "max_active": 2,
            }
        )
    return pools


def _exact_pin_fixture() -> tuple[
    LegacyItemLearningPresetPin,
    list[SimpleNamespace],
    tuple[dict[str, object], dict[str, object], dict[str, object]],
]:
    now = datetime(2026, 9, 9, 1, 2, 3, tzinfo=UTC).isoformat().replace("+00:00", "Z")
    preset_id = "execpreset_" + "1" * 32
    preset_revision_id = "execpresetrev_" + "2" * 32
    capacity_policy_id = "capacity_" + "4" * 32
    capacity_revision_id = "capacityrev_" + "5" * 32
    capacity_current_revision_id = "capacityrev_" + "7" * 32
    preset: dict[str, object] = {
        "schema_version": "execution-preset-revision/1.0",
        "preset_id": preset_id,
        "preset_revision_id": preset_revision_id,
        "revision_number": 1,
        "state": "RELEASED",
        "display_name": "Knowledge analysis",
        "description": "Pinned knowledge-analysis execution policy.",
        "role_policies": [
            {
                "role": "support",
                "model_candidates": [{"model": "gpt-5.6-terra", "reasoning_effort": "high"}],
                "instruction_bundle": _instruction_pointer(),
                "reference_bundle": None,
                "worker_pool_key": "support",
                "timeout_seconds": 1800,
                "sandbox": "read-only",
                "network": "disabled",
            }
        ],
        "capacity_policy_revision_id": capacity_revision_id,
        "general_knowledge_policy": "DENY",
        "compatible_workflow_protocols": ["workflow-role/1.3.0"],
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": now,
    }
    capacity: dict[str, object] = {
        "schema_version": "worker-capacity-policy/1.1",
        "capacity_policy_id": capacity_policy_id,
        "capacity_policy_revision_id": capacity_revision_id,
        "revision_number": 2,
        "state": "RELEASED",
        "max_configured_slots": 6,
        "max_active_codex": 3,
        "max_active_per_slot": 1,
        "max_active_gpu": 1,
        "max_active_knowledge_analysis": 2,
        "pools": _capacity_pools(isolated_extraction=False),
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": now,
    }
    current_capacity: dict[str, object] = {
        **capacity,
        "schema_version": "worker-capacity-policy/1.2",
        "capacity_policy_revision_id": capacity_current_revision_id,
        "revision_number": 3,
        "pools": _capacity_pools(isolated_extraction=True),
    }
    for document in (preset, capacity, current_capacity):
        document["content_sha256"] = compute_control_document_hash(document, "content_sha256")
    pin = LegacyItemLearningPresetPin(
        preset_id=preset_id,
        preset_revision_id=preset_revision_id,
        preset_content_sha256=cast(str, preset["content_sha256"]),
        capacity_policy_id=capacity_policy_id,
        capacity_policy_revision_id=capacity_revision_id,
        capacity_policy_content_sha256=cast(str, capacity["content_sha256"]),
        capacity_current_revision_id=capacity_current_revision_id,
        capacity_current_content_sha256=cast(str, current_capacity["content_sha256"]),
    )
    rows = _pin_rows(pin)
    rows[1].canonical_document = preset
    rows[2].canonical_document = capacity
    rows[4].canonical_document = current_capacity
    return pin, rows, (preset, capacity, current_capacity)


def test_analysis_identity_replays_only_the_same_item_policy_and_preset_revision() -> None:
    promoted = _promotion()
    first = LegacyItemLearningCoordinator._analysis_command(
        promoted,
        risk_policy_revision_id="analysisriskrev_" + "b" * 32,
        preset_key="knowledge-analysis",
        preset_revision_id="execpresetrev_" + "c" * 32,
        requested_by="operator_learning",
    )
    replay = LegacyItemLearningCoordinator._analysis_command(
        promoted,
        risk_policy_revision_id="analysisriskrev_" + "b" * 32,
        preset_key="knowledge-analysis",
        preset_revision_id="execpresetrev_" + "c" * 32,
        requested_by="operator_learning",
    )
    changed = LegacyItemLearningCoordinator._analysis_command(
        promoted,
        risk_policy_revision_id="analysisriskrev_" + "b" * 32,
        preset_key="knowledge-analysis",
        preset_revision_id="execpresetrev_" + "d" * 32,
        requested_by="operator_learning",
    )

    assert first == replay
    assert first.source.source_class == "PAST_EXAM"
    assert first.general_knowledge_mode == "DISABLED"
    assert changed.idempotency_key != first.idempotency_key


def test_retry_identity_pins_one_predecessor_without_changing_source_semantics() -> None:
    first = LegacyItemLearningCoordinator._retry_command(
        item_revision_id="itemrev_" + "2" * 32,
        risk_policy_revision_id="analysisriskrev_" + "b" * 32,
        predecessor_analysis_run_id="analysisrun_" + "d" * 32,
        preset_key="knowledge-analysis",
        requested_by="operator_learning",
    )
    replay = LegacyItemLearningCoordinator._retry_command(
        item_revision_id="itemrev_" + "2" * 32,
        risk_policy_revision_id="analysisriskrev_" + "b" * 32,
        predecessor_analysis_run_id="analysisrun_" + "d" * 32,
        preset_key="knowledge-analysis",
        requested_by="operator_learning",
    )

    assert first == replay
    assert first.predecessor_analysis_run_id == "analysisrun_" + "d" * 32
    assert first.source.source_class == "PAST_EXAM"
    assert first.general_knowledge_mode == "DISABLED"


def test_preset_pin_drift_fails_before_item_promotion() -> None:
    coordinator = object.__new__(LegacyItemLearningCoordinator)
    coordinator.promotion = Mock()
    coordinator.analyses = Mock()

    @contextmanager
    def reject(_pin: LegacyItemLearningPresetPin) -> Iterator[None]:
        raise LegacyItemLearningError("LEGACY_ITEM_LEARNING_PRESET_PIN_DRIFT", "pointer differs")
        yield  # pragma: no cover - required for the contextmanager type

    coordinator.preset_pin_guard = cast(Any, reject)  # type: ignore[method-assign]
    command = cast(Any, SimpleNamespace(requested_by="operator_learning"))

    with pytest.raises(LegacyItemLearningError, match="pointer differs"):
        coordinator.promote_and_schedule(
            command,
            risk_policy_revision_id="analysisriskrev_" + "b" * 32,
            preset_pin=_pin(),
        )

    coordinator.promotion.promote.assert_not_called()
    coordinator.analyses.create_with_pinned_preset.assert_not_called()


def test_preset_pin_guard_accepts_all_exact_pointers_and_canonical_hashes() -> None:
    pin, rows, _ = _exact_pin_fixture()
    coordinator = object.__new__(LegacyItemLearningCoordinator)
    sessions = _PinSessions(rows)
    coordinator.sessions = cast(Any, sessions)

    with coordinator.preset_pin_guard(pin):
        pass

    assert sessions.session is not None
    assert len(sessions.session.executed) == 1
    assert "pg_advisory_xact_lock_shared" in str(sessions.session.executed[0])
    assert len(sessions.session.scalar_statements) == 5
    assert all(
        "FOR SHARE" not in str(statement) and "FOR UPDATE" not in str(statement)
        for statement in sessions.session.scalar_statements
    )


@pytest.mark.parametrize(
    ("document_index", "row_index"),
    ((0, 1), (1, 2), (2, 4)),
    ids=("preset", "pinned-capacity", "current-capacity"),
)
def test_preset_pin_guard_rejects_self_consistent_declared_row_pin_hash_split(
    document_index: int,
    row_index: int,
) -> None:
    pin, rows, documents = _exact_pin_fixture()
    changed = deepcopy(documents[document_index])
    changed["created_at"] = "2026-09-09T01:02:04Z"
    rows[row_index].canonical_document = changed
    pin_hashes = (
        pin.preset_content_sha256,
        pin.capacity_policy_content_sha256,
        pin.capacity_current_content_sha256,
    )
    assert changed["content_sha256"] == rows[row_index].content_sha256 == pin_hashes[document_index]
    assert compute_control_document_hash(changed, "content_sha256") != changed["content_sha256"]
    coordinator = object.__new__(LegacyItemLearningCoordinator)
    coordinator.sessions = cast(Any, _PinSessions(rows))

    with pytest.raises(LegacyItemLearningError) as error, coordinator.preset_pin_guard(pin):
        pass

    assert error.value.code == "LEGACY_ITEM_LEARNING_PRESET_PIN_DRIFT"


@pytest.mark.parametrize(
    ("row_index", "field", "changed_value"),
    (
        (1, "preset_revision_id", "execpresetrev_" + "9" * 32),
        (2, "schema_version", "worker-capacity-policy/1.2"),
        (4, "state", "DRAFT"),
    ),
    ids=("row-identity", "row-schema", "row-state"),
)
def test_preset_pin_guard_rejects_row_identity_schema_or_state_drift(
    row_index: int,
    field: str,
    changed_value: str,
) -> None:
    pin, rows, _ = _exact_pin_fixture()
    setattr(rows[row_index], field, changed_value)
    coordinator = object.__new__(LegacyItemLearningCoordinator)
    coordinator.sessions = cast(Any, _PinSessions(rows))

    with pytest.raises(LegacyItemLearningError) as error, coordinator.preset_pin_guard(pin):
        pass

    assert error.value.code == "LEGACY_ITEM_LEARNING_PRESET_PIN_DRIFT"


def test_preset_pin_guard_rejects_capacity_current_drift_before_content_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin = _pin()
    rows = _pin_rows(pin)
    rows[3].current_revision_id = "capacityrev_" + "9" * 32
    coordinator = object.__new__(LegacyItemLearningCoordinator)
    coordinator.sessions = cast(Any, _PinSessions(rows))
    preset_validator, _, _ = _stub_pin_documents(monkeypatch, pin)

    with pytest.raises(LegacyItemLearningError) as error, coordinator.preset_pin_guard(pin):
        pass

    assert error.value.code == "LEGACY_ITEM_LEARNING_PRESET_PIN_DRIFT"
    preset_validator.assert_not_called()
