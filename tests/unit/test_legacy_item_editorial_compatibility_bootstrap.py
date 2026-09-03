from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import eom_orchestrator.legacy_item_editorial_compatibility_bootstrap as editorial_bootstrap
import pytest
from eom_orchestrator.control_models import ExecutionPresetRecord, ExecutionPresetRevisionRecord
from eom_orchestrator.control_service import ControlPlaneError, compute_control_document_hash
from eom_orchestrator.legacy_item_editorial_compatibility_bootstrap import (
    EDITORIAL_COMPATIBILITY_EVALUATION_ARTIFACT_KEY,
    EDITORIAL_COMPATIBILITY_PLATFORM_ARTIFACT_KEY,
    EDITORIAL_COMPATIBILITY_ROLE_ARTIFACT_KEY,
    _build_non_live_evaluation_report,
    _find_or_create_draft,
    _require_exact_six_slot_registry,
    load_legacy_item_editorial_compatibility_bootstrap_manifest,
)
from eom_orchestrator.worker_registry import WorkerSlot
from eom_workflow import ExecutionPresetEvaluationReport
from eom_workflow.control_schemas import validate_control_contract
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[2]
CONFIG_V1 = ROOT / "config/control-plane/legacy-item-editorial-compatibility-v1"
CONFIG = ROOT / "config/control-plane/legacy-item-editorial-compatibility-v2"


def _instruction_bundle() -> dict[str, object]:
    return {
        "bundle_id": "instrbundle_" + "1" * 32,
        "bundle_revision_id": "instrrev_" + "2" * 32,
        "manifest_artifact": {
            "artifact_id": "artifact_" + "3" * 32,
            "artifact_revision_id": "rev_" + "4" * 32,
            "sha256": "sha256:" + "5" * 64,
            "schema_ref": "eom://schemas/workflow/bundle-manifest/1.0",
            "media_type": "application/json",
            "logical_name": "manifest.json",
        },
        "manifest_sha256": "sha256:" + "6" * 64,
    }


def _role_policies(*, timeout_seconds: int) -> list[dict[str, object]]:
    return [
        {
            "role": "support",
            "model_candidates": [{"model": "gpt-5.6-terra", "reasoning_effort": "high"}],
            "instruction_bundle": _instruction_bundle(),
            "reference_bundle": None,
            "worker_pool_key": "support",
            "timeout_seconds": timeout_seconds,
            "sandbox": "read-only",
            "network": "disabled",
        }
    ]


def _preset_revision(
    *, seed: str, state: str, revision_number: int, timeout_seconds: int
) -> ExecutionPresetRevisionRecord:
    manifest = load_legacy_item_editorial_compatibility_bootstrap_manifest(
        CONFIG if timeout_seconds == 7200 else CONFIG_V1
    )
    document: dict[str, Any] = {
        "schema_version": "execution-preset-revision/1.0",
        "preset_id": "execpreset_" + "7" * 32,
        "preset_revision_id": "execpresetrev_" + seed * 32,
        "revision_number": revision_number,
        "state": state,
        "display_name": manifest.display_name,
        "description": manifest.description,
        "role_policies": _role_policies(timeout_seconds=timeout_seconds),
        "capacity_policy_revision_id": "capacityrev_" + "8" * 32,
        "general_knowledge_policy": manifest.general_knowledge_policy,
        "compatible_workflow_protocols": list(manifest.compatible_workflow_protocols),
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": manifest.created_at,
    }
    return cast(
        ExecutionPresetRevisionRecord,
        SimpleNamespace(
            preset_id=document["preset_id"],
            preset_revision_id=document["preset_revision_id"],
            revision_number=revision_number,
            state=state,
            canonical_document=document,
        ),
    )


class _PresetHistorySession:
    def __init__(
        self,
        *,
        logical: ExecutionPresetRecord,
        revisions: tuple[ExecutionPresetRevisionRecord, ...],
        current: ExecutionPresetRevisionRecord | None,
    ) -> None:
        self.logical = logical
        self.revisions = revisions
        self.current = current

    def scalar(self, _statement: object) -> ExecutionPresetRecord:
        return self.logical

    def scalars(self, _statement: object) -> tuple[ExecutionPresetRevisionRecord, ...]:
        return self.revisions

    def get(
        self, model: type[ExecutionPresetRevisionRecord], identity: str
    ) -> ExecutionPresetRevisionRecord | None:
        assert model is ExecutionPresetRevisionRecord
        if self.current is not None and self.current.preset_revision_id == identity:
            return self.current
        return None


def _select_or_create_revision(
    monkeypatch: pytest.MonkeyPatch,
    *,
    manifest_directory: Path,
    current: ExecutionPresetRevisionRecord,
    revisions: tuple[ExecutionPresetRevisionRecord, ...],
    created: ExecutionPresetRevisionRecord | None,
) -> ExecutionPresetRevisionRecord:
    logical = cast(
        ExecutionPresetRecord,
        SimpleNamespace(
            preset_id=current.preset_id,
            preset_key="legacy-item-editorial-compatibility",
            current_revision_id=current.preset_revision_id,
            state="ACTIVE",
        ),
    )
    fake_session = _PresetHistorySession(
        logical=logical,
        revisions=revisions,
        current=current,
    )

    @contextmanager
    def fake_transaction(_sessions: object) -> Iterator[Session]:
        yield cast(Session, fake_session)

    def fake_create(*_args: object, **kwargs: object) -> ExecutionPresetRevisionRecord:
        assert kwargs["created_at"] == datetime(2026, 9, 3, 0, 0, tzinfo=UTC)
        if created is None:
            raise AssertionError("preset revision creation was not expected")
        return created

    monkeypatch.setattr(editorial_bootstrap, "transaction", fake_transaction)
    monkeypatch.setattr(editorial_bootstrap, "create_execution_preset_draft", fake_create)
    manifest = load_legacy_item_editorial_compatibility_bootstrap_manifest(manifest_directory)
    return _find_or_create_draft(
        cast(sessionmaker[Session], object()),
        manifest=manifest,
        role_policies=_role_policies(timeout_seconds=manifest.timeout_seconds),
        capacity_policy_revision_id="capacityrev_" + "8" * 32,
        actor_id="editorial-bootstrap-test",
    )


def test_editorial_compatibility_bootstrap_is_schema_first_and_source_only() -> None:
    manifest = load_legacy_item_editorial_compatibility_bootstrap_manifest(CONFIG)

    validate_control_contract(
        "legacy-item-editorial-compatibility-control-bootstrap-v2",
        manifest.model_dump(mode="json"),
    )
    assert manifest.schema_version == "legacy-item-editorial-compatibility-control-bootstrap/2.0"
    assert manifest.preset_key == "legacy-item-editorial-compatibility"
    assert manifest.compatible_workflow_protocols == ("workflow-role/1.16.0",)
    assert manifest.slot_key == "slot05"
    assert manifest.worker_pool_key == "support"
    assert manifest.model == "gpt-5.6-terra"
    assert manifest.reasoning_effort == "high"
    assert manifest.general_knowledge_policy == "DENY"
    assert manifest.timeout_seconds == 7200
    role = (CONFIG / manifest.role_instruction_path).read_text(encoding="utf-8")
    assert "Read both authority documents in full" in role
    assert "do not invent, add, or silently import EOM editorial" in " ".join(role.split())
    for artifact_key in (
        EDITORIAL_COMPATIBILITY_PLATFORM_ARTIFACT_KEY,
        EDITORIAL_COMPATIBILITY_ROLE_ARTIFACT_KEY,
        EDITORIAL_COMPATIBILITY_EVALUATION_ARTIFACT_KEY,
    ):
        assert len(f"control-bootstrap:{artifact_key}:{'a' * 64}") <= 128


def test_editorial_compatibility_v1_manifest_remains_immutable_history() -> None:
    manifest = load_legacy_item_editorial_compatibility_bootstrap_manifest(CONFIG_V1)

    validate_control_contract(
        "legacy-item-editorial-compatibility-control-bootstrap",
        manifest.model_dump(mode="json"),
    )
    assert manifest.schema_version == "legacy-item-editorial-compatibility-control-bootstrap/1.0"
    assert manifest.timeout_seconds == 3600
    assert (CONFIG_V1 / manifest.platform_instruction_path).read_bytes() == (
        CONFIG / manifest.platform_instruction_path
    ).read_bytes()
    assert (CONFIG_V1 / manifest.role_instruction_path).read_bytes() == (
        CONFIG / manifest.role_instruction_path
    ).read_bytes()


def test_editorial_compatibility_evaluation_uses_existing_non_live_contract() -> None:
    document = _build_non_live_evaluation_report(
        preset_revision_id="execpresetrev_" + "a" * 32,
        policy_sha256="sha256:" + "b" * 64,
        evaluation_cases_total=65,
        completed_at=datetime(2026, 9, 3, 0, 1, tzinfo=UTC),
    )

    validate_control_contract("execution-preset-evaluation-report", document)
    report = ExecutionPresetEvaluationReport.model_validate(document)
    assert report.scope == "NON_LIVE"
    assert report.cases_total == report.cases_passed == 65
    assert report.report_sha256 == compute_control_document_hash(document, "report_sha256")


def test_editorial_compatibility_v2_appends_successor_without_rewriting_v1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_draft = _preset_revision(seed="a", state="DRAFT", revision_number=1, timeout_seconds=3600)
    old_release = _preset_revision(
        seed="b", state="RELEASED", revision_number=2, timeout_seconds=3600
    )
    successor = _preset_revision(seed="c", state="DRAFT", revision_number=3, timeout_seconds=7200)

    selected = _select_or_create_revision(
        monkeypatch,
        manifest_directory=CONFIG,
        current=old_release,
        revisions=(old_draft, old_release),
        created=successor,
    )

    assert selected is successor
    assert old_draft.canonical_document["role_policies"] == _role_policies(timeout_seconds=3600)
    assert old_release.canonical_document["role_policies"] == _role_policies(timeout_seconds=3600)


def test_editorial_compatibility_v2_reuses_matching_partial_successor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_draft = _preset_revision(seed="a", state="DRAFT", revision_number=1, timeout_seconds=3600)
    old_release = _preset_revision(
        seed="b", state="RELEASED", revision_number=2, timeout_seconds=3600
    )
    successor = _preset_revision(seed="c", state="DRAFT", revision_number=3, timeout_seconds=7200)

    selected = _select_or_create_revision(
        monkeypatch,
        manifest_directory=CONFIG,
        current=old_release,
        revisions=(old_draft, old_release, successor),
        created=None,
    )

    assert selected is successor


def test_editorial_compatibility_v2_replays_current_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _preset_revision(seed="d", state="RELEASED", revision_number=4, timeout_seconds=7200)

    selected = _select_or_create_revision(
        monkeypatch,
        manifest_directory=CONFIG,
        current=current,
        revisions=(current,),
        created=None,
    )

    assert selected is current


def test_editorial_compatibility_v1_cannot_replace_current_v2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _preset_revision(seed="d", state="RELEASED", revision_number=4, timeout_seconds=7200)

    with pytest.raises(ControlPlaneError) as captured:
        _select_or_create_revision(
            monkeypatch,
            manifest_directory=CONFIG_V1,
            current=current,
            revisions=(current,),
            created=None,
        )

    assert captured.value.code == "CONTROL_BOOTSTRAP_CONFLICT"


def test_editorial_compatibility_requires_exact_six_slot_registry() -> None:
    roles = ("authoring", "review", "image", "item_management", "support", "support")
    slots = tuple(
        WorkerSlot.model_validate(
            {
                "slot_id": f"{index:02d}",
                "linux_user": f"eom-cdx-{index:02d}",
                "role": roles[index - 1],
                "enabled": True,
                "gpu": index == 3,
            }
        )
        for index in range(1, 7)
    )
    _require_exact_six_slot_registry(slots)

    with pytest.raises(ControlPlaneError, match="exact six-slot inventory"):
        _require_exact_six_slot_registry(slots[:-1])
