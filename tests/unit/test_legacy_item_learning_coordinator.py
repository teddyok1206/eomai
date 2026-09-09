from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
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


class _PinSession:
    def __init__(self, rows: list[SimpleNamespace | None]) -> None:
        self._rows = iter(rows)

    def scalar(self, _statement: object) -> SimpleNamespace | None:
        return next(self._rows)


class _PinSessions:
    def __init__(self, rows: list[SimpleNamespace | None]) -> None:
        self._rows = rows

    @contextmanager
    def begin(self) -> Iterator[_PinSession]:
        yield _PinSession(self._rows)


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
            preset_id=pin.preset_id,
            state="ACTIVE",
            current_revision_id=pin.preset_revision_id,
        ),
        SimpleNamespace(
            preset_id=pin.preset_id,
            state="RELEASED",
            content_sha256=pin.preset_content_sha256,
            capacity_policy_revision_id=pin.capacity_policy_revision_id,
            canonical_document={},
        ),
        SimpleNamespace(
            capacity_policy_id=pin.capacity_policy_id,
            state="RELEASED",
            content_sha256=pin.capacity_policy_content_sha256,
            canonical_document={},
        ),
        SimpleNamespace(
            capacity_policy_id=pin.capacity_policy_id,
            state="ACTIVE",
            current_revision_id=pin.capacity_current_revision_id,
        ),
        SimpleNamespace(
            capacity_policy_id=pin.capacity_policy_id,
            state="RELEASED",
            content_sha256=pin.capacity_current_content_sha256,
            canonical_document={},
        ),
    ]


def _stub_pin_documents(
    monkeypatch: pytest.MonkeyPatch,
    pin: LegacyItemLearningPresetPin,
) -> tuple[Mock, Mock, Mock]:
    preset_validator = Mock(
        return_value=SimpleNamespace(
            preset_id=pin.preset_id,
            preset_revision_id=pin.preset_revision_id,
            capacity_policy_revision_id=pin.capacity_policy_revision_id,
            content_sha256=pin.preset_content_sha256,
            state="RELEASED",
        )
    )
    capacity_validator = Mock(
        return_value=SimpleNamespace(
            capacity_policy_id=pin.capacity_policy_id,
            capacity_policy_revision_id=pin.capacity_policy_revision_id,
            content_sha256=pin.capacity_policy_content_sha256,
            state="RELEASED",
        )
    )
    current_capacity_validator = Mock(
        return_value=SimpleNamespace(
            capacity_policy_id=pin.capacity_policy_id,
            capacity_policy_revision_id=pin.capacity_current_revision_id,
            content_sha256=pin.capacity_current_content_sha256,
            state="RELEASED",
        )
    )
    monkeypatch.setattr(
        learning_service.ExecutionPresetRevision,
        "model_validate",
        preset_validator,
    )
    monkeypatch.setattr(
        learning_service.WorkerCapacityPolicyV2,
        "model_validate",
        capacity_validator,
    )
    monkeypatch.setattr(
        learning_service.WorkerCapacityPolicyV3,
        "model_validate",
        current_capacity_validator,
    )
    return preset_validator, capacity_validator, current_capacity_validator


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

    coordinator.preset_pin_guard = cast(Any, reject)
    command = cast(Any, SimpleNamespace(requested_by="operator_learning"))

    with pytest.raises(LegacyItemLearningError, match="pointer differs"):
        coordinator.promote_and_schedule(
            command,
            risk_policy_revision_id="analysisriskrev_" + "b" * 32,
            preset_pin=_pin(),
        )

    coordinator.promotion.promote.assert_not_called()
    coordinator.analyses.create_with_pinned_preset.assert_not_called()


def test_preset_pin_guard_accepts_all_exact_pointers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin = _pin()
    coordinator = object.__new__(LegacyItemLearningCoordinator)
    coordinator.sessions = cast(Any, _PinSessions(_pin_rows(pin)))
    _stub_pin_documents(monkeypatch, pin)

    with coordinator.preset_pin_guard(pin):
        pass


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
